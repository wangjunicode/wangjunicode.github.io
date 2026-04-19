---
title: UI系统架构总览 —— YIUIFramework 深度解析
published: 2024-01-01
description: "UI系统架构总览 —— YIUIFramework 深度解析 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: UI系统
draft: false
encryptedKey: henhaoji123
---

# UI系统架构总览 —— YIUIFramework 深度解析

## 1. 系统概述

本项目的 UI 系统基于 **YIUIFramework**（作者：亦亦，开源框架）深度集成到 ET ECS 架构中。YIUIFramework 是一套专为 Unity 设计的 UI 框架，提供面板分层、生命周期管理、数据绑定等功能，与 ET 的异步系统（ETTask）无缝结合，实现了高性能、易扩展的 UI 管理。

核心特性：
- **分层管理**：Panel 按 EPanelLayer 枚举分层（Background、Main、Panel、PopUp、Top、Toast 等）
- **数据绑定**：BindableProperty<T> 实现响应式数据驱动
- **异步加载**：全面支持 ETTask 异步操作
- **对象池支持**：UI 面板可池化复用，减少 GC

---

## 2. 架构分层

```
┌─────────────────────────────────────────────┐
│              UI 分层（EPanelLayer）           │
│  [Toast] [Debug]  ← 最顶层                   │
│  [System] [PopUp] ← 弹窗层                   │
│  [Panel]          ← 主界面层                  │
│  [Main]           ← 主要内容层                │
│  [Background]     ← 背景层                   │
├─────────────────────────────────────────────┤
│         YIUIPanelMgr（面板管理器）            │
│  - 打开/关闭 Panel                           │
│  - 堆栈管理（Back 返回）                      │
│  - 层级排序                                   │
├─────────────────────────────────────────────┤
│         YIUIFactory（工厂系统）               │
│  - 实例化 UI 预制体                           │
│  - 绑定 UIBindCDETable                       │
│  - 初始化 UIBase 组件                         │
├─────────────────────────────────────────────┤
│         YIUILoader（资源加载）                │
│  - 基于 Addressables 加载                    │
│  - 加载缓存与释放管理                          │
└─────────────────────────────────────────────┘
```

---

## 3. 核心类关系

### 3.1 UIBase —— 所有 UI 的基类

```csharp
// 框架中所有 UI 元素均继承自 UIBase
public abstract class UIBase : MonoBehaviour
{
    public bool UIBaseInit { get; private set; }  // 是否已初始化
    public UIBindCDETable CDETable { get; set; }  // 绑定表
    
    // 生命周期（sealed，子类重写对应虚方法）
    protected sealed override void SealedInitialize() { InitPanelViewData(); }
    protected abstract void OnCreate();    // 创建时
    protected abstract void OnOpen();      // 打开时（每次）
    protected abstract void OnClose();     // 关闭时
    protected abstract void OnDestroy();   // 销毁时
}
```

### 3.2 BasePanel —— 面板基类

```csharp
public abstract partial class BasePanel : BaseWindow, IYIUIPanel
{
    // 所在层级 - 子类重写决定面板属于哪一层
    public virtual EPanelLayer Layer => EPanelLayer.Panel;

    // 界面选项 - 是否覆盖背景、是否独占等
    public virtual EPanelOption PanelOption => EPanelOption.None;

    // 堆栈操作 - Back键行为：隐藏、关闭、还是忽略
    public virtual EPanelStackOption StackOption => EPanelStackOption.Visible;

    // 优先级 - 同层级中数字大的显示在前面
    public virtual int Priority => 0;

    // Canvas 引用，通过它控制面板的显隐
    [HideInInspector]
    public Canvas OwnerCanvas;

    public virtual void SetVisiblie(bool isVisible)
    {
        if (!OwnerCanvas) return;
        OwnerCanvas.enabled = isVisible;  // 不 SetActive，保留层级关系
    }
}
```

### 3.3 UIBindCDETable —— 组件绑定表

UIBindCDETable 是 YIUIFramework 的核心绑定机制，在编辑器中通过代码生成，将预制体上的所有 UI 组件引用自动绑定到 C# 代码，省去手动 `GetComponent` 的繁琐。

```csharp
// 生成示例（假设 MainPanel）
public partial class MainPanel
{
    // 由代码生成工具自动填充
    private Button    m_CloseBtn;
    private Text      m_TitleText;
    private Image     m_BgImage;
    
    partial void InitPanelViewData()
    {
        // CDETable 中存储了所有组件引用
        m_CloseBtn  = CDETable.GetComponentByName<Button>("CloseBtn");
        m_TitleText = CDETable.GetComponentByName<Text>("TitleText");
    }
}
```

---

## 4. 数据绑定系统 —— BindableProperty<T>

### 4.1 核心实现

```csharp
// 位置：Assets/Plugins/YIUIFramework/BindableProperty/BindableProperty.cs
public class BindableProperty<T>
{
    protected T mValue;

    public T Value
    {
        get => GetValue();
        set
        {
            // 值相同时不触发事件（优化）
            if (value == null && mValue == null) return;
            if (value != null && value.Equals(mValue)) return;

            mValue = value;
            mOnValueChanged?.Invoke(value);  // 通知所有订阅者
        }
    }

    private Action<T> mOnValueChanged = (v) => { };

    // 注册监听
    public void Register(Action<T> onValueChanged)
    {
        mOnValueChanged += onValueChanged;
    }

    // 注销监听（防止内存泄漏）
    public void UnRegister(Action<T> onValueChanged)
    {
        mOnValueChanged -= onValueChanged;
    }
    
    // 强制触发（即使值未变）
    public void SetValueAndForceNotify(T newValue)
    {
        mValue = newValue;
        mOnValueChanged?.Invoke(newValue);
    }
}
```

### 4.2 使用示例

```csharp
public class PlayerInfoPanel : BasePanel
{
    // 声明可观察属性
    private BindableProperty<int> _hp = new BindableProperty<int>(100);
    private BindableProperty<string> _name = new BindableProperty<string>("玩家");

    protected override void OnCreate()
    {
        // 绑定 HP 变化到血条 UI
        _hp.Register(UpdateHpBar);
        _name.Register(name => m_NameText.text = name);
    }

    protected override void OnDestroy()
    {
        // 必须注销，防止内存泄漏
        _hp.UnRegister(UpdateHpBar);
    }

    private void UpdateHpBar(int hp)
    {
        m_HpBar.value = hp / 100f;
        m_HpText.text = $"HP: {hp}";
    }

    // 当战斗事件来临时，直接赋值自动更新 UI
    public void OnHpChange(int newHp)
    {
        _hp.Value = newHp;  // 自动触发 UpdateHpBar
    }
}
```

---

## 5. UI 工厂系统 —— YIUIFactory

### 5.1 同步创建

```csharp
// 位置：Assets/Plugins/YIUIFramework/Factory/YIUIFactory_UI.cs
public static class YIUIFactory
{
    // 按类型创建，框架内部根据 UIBindHelper 找到对应的预制体路径
    public static T Create<T>() where T : UIBase
    {
        var data = UIBindHelper.GetBindVoByType<T>();
        if (data == null) return null;
        var vo = data.Value;
        return (T)Create(vo);
    }

    // 核心创建逻辑
    private static UIBase Create(UIBindVo vo)
    {
        var obj = YIUILoader.Instance.InstantiateGameObject(vo.ResLoadPath);
        // ... 绑定 CDETable，初始化 UIBase
    }
    
    // 获取或创建（池化复用逻辑）
    public static T GetOrCreateCommon<T>(GameObject obj) where T : UIBase
    {
        var cdeTable = obj.GetComponent<UIBindCDETable>();
        if (cdeTable.UIBase == null)
        {
            return CreateCommon<T>(obj);  // 首次创建
        }
        else
        {
            if (!cdeTable.UIBase.UIBaseInit)
            {
                // 已有实例但未初始化，重新初始化
                var bingVo = UIBindHelper.GetBindVoByType(typeof(T));
                CreateByObjVo<T>(bingVo.Value, obj, cdeTable.UIBase as T);
            }
        }
        return cdeTable.UIBase as T;
    }
}
```

### 5.2 异步创建

```csharp
// 位置：Assets/Plugins/YIUIFramework/Factory/YIUIFactory_UI_Async.cs
public static partial class YIUIFactory
{
    // 异步创建面板，避免阻塞主线程
    public static async ETTask<T> CreateAsync<T>() where T : UIBase
    {
        var data = UIBindHelper.GetBindVoByType<T>();
        if (data == null) return null;
        
        // 异步加载资源
        var obj = await YIUILoader.Instance.InstantiateGameObjectAsync(data.Value.ResLoadPath);
        return CreateByObj<T>(data.Value, obj);
    }
}
```

---

## 6. 面板生命周期详解

### 6.1 完整生命周期流程

```
YIUIPanelMgr.Open<T>()
    ↓
YIUIFactory.CreateAsync<T>()  // 异步加载预制体
    ↓
UIBase.Initialize()            // 框架内部初始化
    ├── SealedInitialize()     // 密封，调用 InitPanelViewData()
    └── InitPanelViewData()    // 绑定代码生成的 UI 组件引用
    ↓
OnCreate()                     // 开发者重写，注册事件、初始化数据
    ↓
OnOpen(params)                 // 每次打开时调用，可传参
    ↓
[面板处于激活状态]
    ↓
OnClose()                      // 关闭时，做收尾工作（不销毁）
    ↓
OnDestroy()                    // 真正销毁时，反注册所有事件
```

### 6.2 状态转换

| 状态 | 说明 | 对应方法 |
|------|------|---------|
| Created | 首次创建，组件绑定完成 | `OnCreate()` |
| Open | 可见且可交互 | `OnOpen()` |
| Visible | 可见但可能不响应输入 | - |
| Invisible | 隐藏（Canvas禁用）但存活 | `SetVisiblie(false)` |
| Closed | 关闭，可能进对象池 | `OnClose()` |
| Destroyed | 完全销毁 | `OnDestroy()` |

---

## 7. 与 ET ECS 的集成方式

YIUIFramework 本身是 MonoBehaviour 体系，而 ET 是纯 C# ECS。项目通过以下方式集成：

```csharp
// ETTaskWaitCallback.cs - ET 的等待回调桥接
public class ETTaskWaitCallback : MonoBehaviour
{
    // 允许 UI 动画等异步操作与 ETTask 系统集成
    public static ETTask WaitCallback(Action<Action> callback)
    {
        var tcs = ETTask.Create(fromPool: true);
        callback(() => tcs.SetResult());
        return tcs;
    }
}

// ETTaskWaitUntil.cs - 轮询等待条件满足
public class ETTaskWaitUntil : MonoBehaviour
{
    public static async ETTask WaitUntil(Func<bool> predicate)
    {
        while (!predicate())
        {
            await TimerComponent.Instance.WaitFrameAsync();
        }
    }
}
```

---

## 8. HUD 与战斗 UI

战斗 UI（HUD）独立于普通 Panel 系统，直接挂在战斗 View 层，由 ECS 事件驱动更新：

```csharp
// 战斗 HP 条更新示例
[Event(SceneType.Battle)]
public class Evt_OnHpChange_HudHandler : AEvent<Evt_OnHpChange>
{
    protected override void Run(Scene scene, Evt_OnHpChange args)
    {
        // 根据 Unit 找到对应 HUD
        var hud = HudManager.Instance.GetHud(args.Unit.Id);
        hud?.UpdateHp(args.CurHp, args.MaxHp);
    }
}
```

---

## 9. 性能优化策略

### 9.1 UI Canvas 分离
- 静态 UI 元素放在独立 Canvas，减少 Rebuild
- 频繁更新的 HUD 使用单独 Canvas

### 9.2 SetActive vs Canvas.enabled
```csharp
// 框架选择 Canvas.enabled 而不是 SetActive
// 原因：SetActive 会销毁 Canvas 的顶点缓存，重新激活时触发全量重建
// Canvas.enabled = false 保留缓存，重新开启几乎无开销
public virtual void SetVisiblie(bool isVisible)
{
    OwnerCanvas.enabled = isVisible;  // ✓ 推荐方式
    // gameObject.SetActive(isVisible); // ✗ 开销大
}
```

### 9.3 图集合批
- 同一 Panel 内的图片尽量使用同一图集（SpriteAtlas）
- 图集命名遵循 `{模块名}_atlas` 规范

---

## 10. 常见问题与最佳实践

**Q: 面板打开很慢怎么办？**  
A: 检查是否同步加载了大资源。应使用 `CreateAsync` + 显示 Loading。大面板可考虑预加载（在进入对应模块前提前加载）。

**Q: 如何正确传参给面板？**  
A: 通过 `OnOpen` 的参数传入，而非构造时传入。面板可能被池化复用，每次 `Open` 都需要重新初始化数据。

**Q: BindableProperty 注册后面板销毁了还会被调用吗？**  
A: 会！必须在 `OnDestroy` 中 `UnRegister`，否则持有引用导致内存泄漏和空指针。

**Q: 同一面板同时打开两次会怎样？**  
A: YIUIPanelMgr 默认会先关闭已有实例再打开新的。若需要多实例，需要在 PanelOption 中配置。

**Q: UI 层级混乱怎么排查？**  
A: 检查 `Layer`（面板所在层）和 `Priority`（层内排序）。同层中 Priority 数字大的显示在前，相同时后加入的在前。
