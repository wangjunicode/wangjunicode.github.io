---
title: Unity游戏每日任务界面与关卡选择系统实现
published: 2026-03-31
description: 解析日常任务界面的场景选择列表动态生成、ToggleGroup单选机制、毛玻璃背景处理、YIUITweenComponent统一动画管理及事件驱动关卡进入流程。
tags: [Unity, UI系统, 任务界面, 关卡选择]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏每日任务界面与关卡选择系统实现

## 日常任务界面的功能定位

日常任务界面（Daily Panel）是玩家每天开始游戏必经的入口，它承载了：
- 当日可选关卡的列表展示
- 关卡的单选交互（同时只能选一个关卡）
- 开始游戏按钮（进入选中的关卡）
- 返回大厅的导航

从技术角度，这个界面的有趣之处在于：
1. 关卡列表通过**配置过滤+动态实例化**生成（而不是预先布局好固定数量的按钮）
2. 选择状态使用 Unity 内置的 **ToggleGroup** 管理单选
3. 界面背景使用**毛玻璃效果**（TranslucentImage）处理

---

## 关卡列表的动态生成

```csharp
public void InitSelectSceneItem()
{
    // 数据过滤：只显示 Id > 1000 的关卡（通过 LINQ 筛选）
    var dataList = CfgManager.tables.TbGameScene.DataList
        .Where(x => x.Id > 1000)
        .ToList();
    
    for (int i = 0; i < dataList.Count; i++)
    {
        Sub_DailySelectSceneItem sub_SelectTeamItem;
        
        if (SelectTeamItemList.Count <= i)
        {
            // 数量不足时，克隆模板创建新 Item
            var originTrans = u_UISub_DailySelectSceneItem.OwnerRectTransform;
            var parent = originTrans.parent;
            var newTransform = UnityEngine.Object.Instantiate(originTrans);
            newTransform.SetParent(parent, false);
            
            // 通过 YIUIFactory 创建 YIUI 组件（绑定逻辑层）
            sub_SelectTeamItem = YIUIFactory.CreateCommon<Sub_DailySelectSceneItem>(
                u_UISub_DailySelectSceneItem.UIPkgName,   // 资源包名
                u_UISub_DailySelectSceneItem.UIResName,    // 资源名
                newTransform.gameObject                    // 挂载目标
            );
            SelectTeamItemList.Add(sub_SelectTeamItem);
        }
        
        sub_SelectTeamItem = SelectTeamItemList[i];
        sub_SelectTeamItem.Refresh(dataList[i], i);
    }
    
    // 统一处理 ToggleGroup 绑定
    for (int i = 0; i < SelectTeamItemList.Count; i++)
    {
        var item = SelectTeamItemList[i];
        var data = item.gameScene;
        item.u_ComW_SelectTeamTglToggle.onValueChanged.AddListener(
            (isOn) => OnSelctScene(isOn, data));
        item.u_ComW_SelectTeamTglToggle.group = u_ComW_SetCharBtnGroupComponentToggleGroup;
        item.u_ComW_SelectTeamTglToggle.isOn = SelectSceneId == data.Id;
    }
}
```

**分两个循环的原因**：

第一个循环：创建/复用 Item，刷新 Item 数据（`Refresh`）
第二个循环：绑定 Toggle 事件和 ToggleGroup

为什么分开？`Refresh` 中可能修改 Toggle 的初始状态，如果在第一个循环里就绑定 `onValueChanged`，设置初始状态时会立即触发回调，可能造成选中状态混乱。分开循环，确保所有 Item 的数据都刷新完毕后，再统一绑定事件和设置初始选中状态。

---

## 模板 + 克隆的动态列表生成

```csharp
// u_UISub_DailySelectSceneItem 是 Prefab 中预先放置的"模板" Item
u_UISub_DailySelectSceneItem.OwnerGameObject.SetActive(false);  // 模板本身不可见
```

在 `Initialize` 中，把模板设为不可见。运行时通过 `Instantiate` 克隆出新的 Item，设置数据后显示。

这是 Unity UI 开发中常见的"模板克隆"模式：
- 美术只需要设计好一个 Item 的样式（模板）
- 程序克隆出 N 个，动态设置不同数据

与对象池的区别：克隆模式不归还复用，每次初始化都重新克隆（因为数量相对稳定，每日任务关卡数量不会频繁变化）。

---

## ToggleGroup 实现单选逻辑

```csharp
// 所有 Item 的 Toggle 都加入同一个 ToggleGroup
item.u_ComW_SelectTeamTglToggle.group = u_ComW_SetCharBtnGroupComponentToggleGroup;
```

Unity 的 `ToggleGroup` 保证了同一组内只有一个 Toggle 处于 `isOn=true` 状态。当一个 Toggle 被选中，组内其他 Toggle 自动变为未选中。

```csharp
void OnSelctScene(bool isOn, GameScene scene)
{
    if (!isOn) return;  // 只响应"选中"事件，忽略"取消选中"
    SelectSceneId = scene.Id;
}
```

`onValueChanged` 会在两个时机触发：
1. Toggle 从 Off → On：`isOn = true`（选中了这个关卡）
2. Toggle 从 On → Off（因为选了其他关卡）：`isOn = false`（取消了这个关卡）

`if (!isOn) return;` 过滤掉第2种情况——我们只关心"选中了哪个"，不关心"取消了哪个"。

---

## 毛玻璃背景的处理

```csharp
protected override async ETTask<bool> OnOpen()
{
    await ETTask.CompletedTask;
    
    // 毛玻璃（TranslucentImage）需要知道从哪个摄像机采样
    if (u_ComBottomBtnListTranslucentImage != null)
    {
        var brainGO = GameObject.Find("DisplayCinemachineBrain");
        if (brainGO != null)
        {
            var camera = brainGO.GetComponentInChildren<Camera>();
            u_ComBottomBtnListTranslucentImage.source = 
                camera.GetComponent<TranslucentImageSource>();
        }
    }
    return true;
}
```

`TranslucentImage`（毛玻璃效果组件）需要一个 `TranslucentImageSource` 才能工作——`Source` 组件挂在摄像机上，负责捕获当前帧的画面快照作为模糊底图。

**为什么要在 `OnOpen` 里动态绑定**，而不是在 Inspector 里直接拖拽？

- 大厅的摄像机（`DisplayCinemachineBrain`）可能在运行时才激活
- 不同场景可能有不同的摄像机，硬编码 Inspector 引用会在切换场景后失效
- 通过 `GameObject.Find` 动态找到摄像机，更灵活

---

## YIUITweenComponent 统一管理动画

```csharp
private YIUITweenComponent yIUITweenComponent;

protected override void Initialize()
{
    yIUITweenComponent = OwnerRectTransform.InitializeTweenComponent();
    // ...
}

protected override async ETTask OnOpenTween()
{
    await yIUITweenComponent.PlayOnShow();  // 播放所有子组件的出现动画
}

protected override async ETTask OnCloseTween()
{
    await yIUITweenComponent.PlayOnHide();  // 播放所有子组件的消失动画
}
```

这是上一篇讲到的 `YIUITweenComponent` 系统在实际面板中的使用。每个面板只需要：
1. 在 `Initialize` 中 `InitializeTweenComponent()`（扫描子节点的动画组件）
2. `OnOpenTween` 中 `PlayOnShow()`
3. `OnCloseTween` 中 `PlayOnHide()`

具体的动画效果（哪些元素缩放/淡入/滑入）完全由美术在子节点上配置 `IUIDOTween` 实现类，程序不需要关心细节。

---

## 进入关卡的事件驱动

```csharp
protected override async void OnEventStartDailyAction()
{
    int sceneId = SelectSceneId;
    Log.Info("sceneId:" + sceneId);
    
    // 先关闭当前面板
    Close();
    
    // 设置 PVE 模式
    YIUIComponent.ClientScene.GetComponent<DungeonComponent>()
        .SetDebugePVE(ePVEMode.Normal);
    
    // 通过事件进入关卡（而不是直接调用场景加载）
    EventSystem.Instance.Publish(YIUIComponent.ClientScene, 
        new Evt_EnterPVE() { sceneId = sceneId });
}
```

进入关卡不直接调用 `SceneManager.LoadScene`，而是发布 `Evt_EnterPVE` 事件。这是 UI 层与游戏逻辑层解耦的体现：
- UI 层只知道"玩家想进入 sceneId=100004 的关卡"
- 具体怎么加载场景、如何过渡（淡出、加载界面等）由监听 `Evt_EnterPVE` 的系统处理
- 如果将来过渡效果要改（从淡入淡出改为切格动画），只改监听者，不改 DailyPanel

---

## 邮件/消息的跨界面通知

```csharp
protected override void OnEventClickMailAction()
{
    // 打开手机面板，默认显示好友标签页
    EventSystem.Instance.Publish(YIUIComponent.ClientScene, 
        new Evt_ShowUIPanel<EPhonePanelViewEnum> 
        { 
            PanelName = PanelNameDefine.PhonePanel, 
            p1 = EPhonePanelViewEnum.FriendView 
        });
}
```

点击邮件图标会打开"手机"面板（一个模拟手机界面的全屏 UI），并指定默认显示"好友"标签页（`EPhonePanelViewEnum.FriendView`）。

使用 `Evt_ShowUIPanel<EPhonePanelViewEnum>` 泛型事件，允许携带类型化的参数（`EPhonePanelViewEnum`），而不是 object 类型的弱类型参数。这让代码在编译期就能发现类型错误，而不是等到运行时才崩溃。

---

## 数据过滤的 LINQ 使用

```csharp
var dataList = CfgManager.tables.TbGameScene.DataList
    .Where(x => x.Id > 1000)
    .ToList();
```

`Where(x => x.Id > 1000)` 过滤掉 Id ≤ 1000 的关卡（代码注释说是"CE需要的场景"，可能是 "Competitive/Content Evaluation"）。

**`ToList()` 的必要性**：

`Where` 返回的是 `IEnumerable<T>`，是懒执行的（每次遍历都重新计算）。`ToList()` 立即执行并创建一个列表，确保后续访问 `dataList.Count` 等操作的一致性，避免每次访问都重新过滤一次。

---

## 注意：现有代码中的硬编码

```csharp
// 代码中存在的硬编码
public int SelectSceneId = 100004;  // 默认选中的场景ID是硬编码
// TODO 硬编码一下，筛选CE需要的场景
var dataList = CfgManager.tables.TbGameScene.DataList.Where(x => x.Id > 1000).ToList();
```

代码中有 `TODO` 注释，说明这些硬编码是临时的（开发阶段）。正式版本应该：
- 默认选中的场景 ID 来自玩家存档或配置表（而不是硬编码 100004）
- 场景过滤条件来自配置表字段（如 `ShowInDaily = true`），而不是 `Id > 1000`

这些 `TODO` 是很好的代码健康指标——记录了"目前的技术债在哪里"，以及"将来应该怎么改"。

---

## 总结

日常任务界面虽然功能相对简单，但展示了多个 Unity UI 开发的核心模式：

1. **模板克隆生成列表**：模板 SetActive(false)，`Instantiate` 克隆，绑定数据
2. **分两轮循环**：第一轮创建/刷新，第二轮绑定事件，避免初始化时触发回调
3. **ToggleGroup 单选**：`onValueChanged` 过滤 `isOn=false` 的事件
4. **动态摄像机绑定**：`OnOpen` 时找到摄像机，避免 Inspector 硬编码引用
5. **YIUITweenComponent**：3行代码完成完整的进出动画管理
6. **事件驱动关卡进入**：发布事件而非直接加载场景，保持 UI 层的纯粹性
