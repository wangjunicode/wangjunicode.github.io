---
title: 游戏UI层级管理系统设计与实现
published: 2026-03-31
description: 详解Unity游戏中UI层级划分策略、层管理器的实现原理，以及多面板共存时的排序与遮挡处理。
tags: [Unity, UI框架, 层级管理]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏UI层级管理系统设计与实现

## 前言

你有没有遇到过这样的问题：确认弹窗被游戏HUD覆盖住了；新手引导箭头出现在了全屏界面的背后；关闭按钮被Toast提示遮住了点不到？

这些都是 UI 层级管理不当导致的。一个成熟的游戏 UI 框架，层级系统是它最基础也最重要的基础设施之一。本文通过分析 YIUIFramework 的源码，深入讲解层级管理系统的设计与实现。

---

## 为什么需要层级系统？

在 Unity 中，UGUI 的渲染顺序由以下因素决定：
1. Canvas 的 `sortingOrder`
2. 同一 Canvas 下，Hierarchy 里的先后顺序（后面的在前面）
3. Canvas 组件的 `renderMode`

如果没有统一的层级管理，每个面板都自己设置 `sortingOrder`，很快就会出现冲突。游戏有几十甚至上百个界面，靠约定"主界面用100，弹窗用200"这样的方式根本不可靠。

**层级系统的本质**：把 UI 按功能优先级分组，同组内按动态规则排序。

---

## EPanelLayer：层级枚举定义

```csharp
public enum EPanelLayer
{
    Top    = 0,  // 最高层：新手引导、强制弹窗
    Tips   = 1,  // 提示层：Toast、确认弹窗、跑马灯
    Popup  = 2,  // 弹窗层：非全屏界面，可并存
    Panel  = 3,  // 面板层：全屏界面，受返回键影响
    Scene  = 4,  // 场景层：血条、飘字等2D场景UI
    Bottom = 5,  // 最低层：背景、底部装饰
    Cache  = 6,  // 缓存层：不显示，用于预加载缓存
    Count  = 7,  // 用于计数
    Any    = 8,  // 匹配所有层
}
```

**层级设计的第一性原理**：层级数字越小，显示越靠前。这个顺序反映了业务优先级：
- 新手引导（Top）必须盖住一切，否则玩家看不到引导箭头
- 提示文字（Tips）要在弹窗上面，否则弹窗关闭时的 Toast 会被遮住
- 全屏面板（Panel）是游戏主要内容
- 场景 UI（Scene）在全屏面板下面，游戏进战斗后才显示

⚠️ **重要警告**：枚举的数值不能修改！代码注释明确写了"只能新增，不允许修改"。因为这些数值可能被序列化存储，修改会导致已有数据错乱。

---

## PanelMgr Root：层级容器初始化

层级系统的物理基础是一组 GameObject 容器：

```csharp
private async ETTask<bool> InitRoot()
{
    // 加载 UIRoot 预制体（挂载了 Canvas 和 Camera）
    UIRoot = await YIUILoader.Instance.InstantiateGameObjectAsync(UIRootLoadPath, "UIRoot");
    Object.DontDestroyOnLoad(UIRoot); // 跨场景不销毁
    
    // 关键：UIRoot 偏移到远离 3D 场景的位置，防止与世界坐标叠加
    UIRoot.transform.position = new Vector3(RootPosOffset, RootPosOffset, 0);

    // 创建各层级的 RectTransform 容器
    const int len = (int)EPanelLayer.Count;
    for (var i = len - 1; i >= 0; i--)
    {
        var layer = new GameObject($"Layer{i}-{(EPanelLayer)i}");
        var rect = layer.AddComponent<RectTransform>();
        rect.SetParent(UILayerRoot);
        
        // 全屏覆盖设置
        rect.anchorMax = Vector2.one;
        rect.anchorMin = Vector2.zero;
        rect.sizeDelta = Vector2.zero;
        
        // Z 轴偏移：每层间隔 1000 单位，用于 3D 模型穿插的深度隔离
        rect.localPosition = new Vector3(0, 0, i * LayerDistance);
        
        m_AllPanelLayer.Add((EPanelLayer)i, rectDic);
    }
}
```

**关键设计点分析：**

### 1. UIRoot 坐标偏移
```csharp
UIRoot.transform.position = new Vector3(RootPosOffset, RootPosOffset, 0);
// RootPosOffset = 1000
```

这个 1000 的偏移看起来奇怪，但有重要意义：游戏场景中的 3D 物体在世界坐标 (0,0,0) 附近，如果 UI 根节点也在原点，编辑器里调整 UI 时很容易误选到 3D 对象。偏移后，UI 和 3D 场景在空间上分开，不互相干扰。

### 2. Z 轴层级隔离
```csharp
rect.localPosition = new Vector3(0, 0, i * LayerDistance);
// LayerDistance = 1000
```

每层之间的 Z 轴间距是 1000 个单位。这解决了什么问题？

当 UI 中有 3D 模型（如角色立绘、道具展示）时，模型的深度测试可能穿透不同层级的 UI。通过 Z 轴物理隔离，确保上层的 UI 内容永远遮盖下层，即使里面有 3D 模型也不会穿帮。

### 3. 数据结构设计
```csharp
private Dictionary<EPanelLayer, Dictionary<RectTransform, List<PanelInfo>>> m_AllPanelLayer;
```

三层嵌套：
- 外层 `Dictionary<EPanelLayer, ...>`：按层级分类
- 中层 `Dictionary<RectTransform, ...>`：层级容器（当前每层只有一个，但支持扩展）
- 内层 `List<PanelInfo>`：该层内的面板列表，**顺序即渲染顺序**

---

## 层级内的排序规则

同一层级内，面板的前后顺序由 `Priority` 属性和添加时机共同决定：

```csharp
// BasePanel 中的优先级定义
public virtual int Priority => 0;

// 排序规则（来自 PanelMgr_AddRemove.cs）：
// 1. Priority 大的在前面（靠近屏幕）
// 2. 相同 Priority 时，后添加的在前面
```

这个设计让面板能主动声明自己的重要程度。例如：

```csharp
// 普通战斗 UI
public class BattleHUDPanel : BasePanel
{
    public override EPanelLayer Layer => EPanelLayer.Scene;
    public override int Priority => 0; // 默认优先级
}

// 技能释放特效 UI
public class SkillEffectPanel : BasePanel
{
    public override EPanelLayer Layer => EPanelLayer.Scene;
    public override int Priority => 10; // 比 HUD 高，显示在前面
}
```

---

## 层级的显示与隐藏控制

```csharp
public void SetLayerActive(EPanelLayer panelLayer, bool isActive)
{
    var rect = GetLayerRect(panelLayer);
    if (rect == null) return;
    rect.gameObject.SetActive(isActive);
}
```

这个 API 允许批量控制一整层的显示状态。典型使用场景：

```csharp
// 进入战斗时，隐藏 Scene 层以外的所有层
PanelMgr.Inst.SetLayerActive(EPanelLayer.Bottom, false);
PanelMgr.Inst.SetLayerActive(EPanelLayer.Panel, false);

// 退出战斗，恢复
PanelMgr.Inst.SetLayerActive(EPanelLayer.Bottom, true);
PanelMgr.Inst.SetLayerActive(EPanelLayer.Panel, true);
```

---

## 特殊层：Cache 缓存层

```csharp
public RectTransform UICache
{
    get
    {
        if (m_UICache == null)
            m_UICache = GetLayerRect(EPanelLayer.Cache);
        return m_UICache;
    }
}
```

Cache 层的面板：
- **强制隐藏**（SetActive(false) 或 Canvas.enabled = false）
- **不参与任何 UI 交互**
- **保持在内存中，避免重复加载开销**

哪些面板适合缓存？
- **频繁打开关闭的面板**：如背包、地图
- **加载耗时的面板**：如包含大量资源的商城
- **需要保持状态的面板**：如正在上传图片的面板

哪些面板不应该缓存？
- **每次打开都需要新数据的面板**（虽然可以在 OnOpen 里刷新，但要注意清理）
- **包含大量 Texture 资源的面板**（缓存会占用大量内存）
- **只使用一次的面板**：如新手引导完成提示

---

## 屏蔽层（Block）机制

框架还实现了一个屏蔽层：

```csharp
// 初始化时在所有层上方添加屏蔽层
InitAddUIBlock();
```

屏蔽层是一个透明的全屏遮挡物，激活后阻止所有 UI 交互。使用场景：
- **网络请求等待中**：防止用户重复点击
- **场景过渡动画**：过渡期间禁止任何操作
- **面板动画播放中**：`BanLayerOptionForever` 会临时激活它

```csharp
// 临时禁止操作（动画期间调用）
var foreverCode = m_PanelMgr.BanLayerOptionForever();

// 动画结束后恢复
m_PanelMgr.RecoverLayerOptionForever(foreverCode);
```

返回的 `foreverCode` 是一个令牌，用于配对禁用和恢复操作，支持嵌套调用（多个地方同时禁用，全部恢复后才真正解锁）。

---

## UI Camera 配置

```csharp
UICamera.clearFlags = CameraClearFlags.Depth; // 只清除深度，保留背景渲染
UICamera.orthographic = true; // 正交投影
UICamera.transform.localPosition = new Vector3(
    UILayerRoot.localPosition.x,
    UILayerRoot.localPosition.y,
    -LayerDistance  // 摄像机在所有层的后面
);
```

**为什么用正交投影？**

正交投影下，物体的大小不随距离变化。UI 元素的位置在像素坐标系里是固定的，不需要透视效果。用正交投影避免了近大远小导致的层级 UI 大小错误。

**设计分辨率**：
```csharp
public const int DesignScreenWidth = 1920;
public const int DesignScreenHeight = 1080;
```

框架锁定了 1920×1080 的设计分辨率。所有 UI 都按这个分辨率设计，然后通过 Canvas Scaler 缩放到实际屏幕分辨率。

---

## 实际开发中的常见错误

### 错误 1：随意设置面板 Layer

新人常犯的错误：
```csharp
// 错误！Tips 层的弹窗应该放在 Popup 层
public class ItemDetailPanel : BasePanel
{
    public override EPanelLayer Layer => EPanelLayer.Tips; // 不对！
}
```

正确做法：根据面板的功能语义选择层级。物品详情是弹窗，应该用 `Popup` 层。`Tips` 层留给 Toast 和确认框。

### 错误 2：直接操作 Hierarchy 改变顺序

```csharp
// 错误！不要直接操作 Transform 父子关系
transform.SetAsLastSibling(); // 绕过了 PanelMgr 的管理
```

所有层级操作必须通过 `PanelMgr` 的接口，否则内部的 `m_AllPanelLayer` 数据结构就和实际 GameObject 层级不一致了。

### 错误 3：忘记检查 Cache 层的面板状态

```csharp
// 从缓存取出面板时，记得重新激活
public override EPanelOption PanelOption => EPanelOption.Cache; // 启用缓存

public async ETTask<bool> OnOpen(ItemData data)
{
    // ⚠️ 缓存的面板 GameObject 是 active=false 状态进来的
    // 框架会自动 SetActive(true)，但你的数据要手动刷新
    m_ItemNameText.text = data.Name; // 正确：每次打开都刷新
    return true;
}
```

---

## 总结

层级系统的核心价值是**把 UI 的显示优先级从"程序员脑子里的约定"变成"代码里的强制约束"**。

关键设计总结：
1. **枚举值不可修改**，只能追加，保护已有数据
2. **Z 轴物理隔离**，解决含 3D 模型的 UI 穿帮问题
3. **Cache 层实现内存复用**，减少频繁加载开销
4. **Block 层实现操作锁**，防止并发交互
5. **Priority 属性**让面板声明自己的排序优先级

对于初学者，记住一条原则：**UI 的任何层级操作，都要通过 PanelMgr 的接口进行，永远不要直接操作 GameObject 的 Hierarchy 位置**。
