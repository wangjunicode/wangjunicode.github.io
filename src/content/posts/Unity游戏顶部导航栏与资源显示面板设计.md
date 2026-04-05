---
title: Unity游戏顶部导航栏与资源显示面板设计
published: 2026-03-31
description: 深入解析顶部导航栏（Header Panel）的事件驱动显隐机制、多视图切换、资源货币显示及返回/回到首页按钮的动态显示逻辑实现。
tags: [Unity, UI系统, 导航栏, 资源显示]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏顶部导航栏与资源显示面板设计

## 为什么顶部导航栏值得专门设计

大多数游戏在不同的功能界面（商城、背包、成就等）都有一个顶部导航栏（Header），显示：
- 当前页面标题
- 返回按钮（< 返回）
- 回到主界面按钮（⌂）
- 玩家当前资源（金币、钻石等）

如果每个功能界面都各自管理这个顶部栏，会导致大量重复代码。更好的方案是：**顶部栏是一个独立的常驻面板，通过事件系统接收配置更新。**

`HeaderPanel` 正是这样设计的。

---

## 事件驱动的显示/隐藏

```csharp
protected override void Initialize()
{
    InitHeader();
    YIUIComponent.ClientScene.GetComponent<EventDispatcherComponent>()
        .RegisterEvent<Evt_UI_ShowHeader>(ShowHeader);
    YIUIComponent.ClientScene.GetComponent<EventDispatcherComponent>()
        .RegisterEvent<Evt_UI_HideHeader>(HideHeader);
}
```

`Evt_UI_ShowHeader` 和 `Evt_UI_HideHeader` 是全局事件，任何界面想显示/隐藏顶部栏，只需要发布这两个事件，不需要持有 `HeaderPanel` 的引用。

```csharp
// 任意界面显示顶部栏的使用方式
EventSystem.Instance.Publish(YIUIComponent.ClientScene, new Evt_UI_ShowHeader
{
    ShowHomeButton = true,          // 显示"回到主界面"按钮
    ShowBackButton = true,          // 显示"返回"按钮
    Title = "背包",                  // 标题
    SubTitle = "道具管理",            // 副标题（可选）
    HomeCallback = null,             // null = 使用默认行为
    BackCallback = null,             // null = 使用默认行为
    ViewData = new HeaderResourceViewData  // 右侧显示资源
    {
        ResourceDataList = resourceList
    }
});
```

这种设计的优势：
1. **零耦合**：功能界面不知道 HeaderPanel 的存在，只发布事件
2. **统一管理**：HeaderPanel 是唯一知道"如何显示顶部栏"的地方
3. **可替换**：如果将来顶部栏设计变了，只改 HeaderPanel，所有功能界面不用改

---

## 返回与主界面按钮的逻辑

```csharp
protected override void OnEventReturnAction()
{
    if (_backCallback != null)
        _backCallback();      // 调用自定义返回逻辑
    else
        DefaultReturnAction().Coroutine();  // 使用默认：关闭当前面板
}

private async ETTask DefaultReturnAction()
{
    // 关闭 Panel 栈顶界面
    await PanelMgr.Inst.CloseTopPanelInPanelStackAsync();
}

protected override void OnEventHomeAction()
{
    if (_homeCallback != null)
        _homeCallback();  // 调用自定义回主界面逻辑
    else
        DefaultHomeAction().Coroutine();
    
    // 无论自定义还是默认，都卸载战斗准备资源
    EventSystem.Instance.Publish(YIUIComponent.ClientScene, new Evt_UnLoadBattlePrepare());
}
```

**自定义回调的价值**：

大多数情况下，"返回"就是关闭当前页，"主界面"就是回到 Lobby。但某些场景需要特殊处理：
- 在战斗准备界面，"返回"可能需要弹确认弹窗（"确认退出？"）
- 在某个多步骤向导中，"返回"可能是回到上一步而不是关闭整个面板

通过 `_backCallback` 和 `_homeCallback` 传入自定义逻辑，同时保留默认行为作为兜底，是"策略模式"的典型应用。

---

## 回主界面按钮的条件显示

```csharp
u_ComBtn_HomeRectTransform.gameObject.Active(
    showHomeButton && YIUIComponent.ClientScene.Player().IsAnyCultivationScriptCompleted()
);
```

**注意**：回主界面按钮不是只要 `showHomeButton=true` 就显示，还要额外检查 `IsAnyCultivationScriptCompleted()`（是否完成了任意培养脚本/任务）。

这个条件的业务含义：在游戏早期（还没完成任何培养任务的新玩家），主界面按钮不显示，强制玩家按顺序完成新手引导。当有培养任务完成后，才开放自由返回主界面的能力。

这是通过 UI 层控制新手流程的典型做法——通过按钮的可见性引导玩家的行为路径。

---

## 多子视图的多态切换

```csharp
private async ETTask ShowView(IHeaderViewData viewData)
{
    switch (viewData)
    {
        case HeaderCultivationViewData cultivationViewData:
            await OpenViewAsync<HeaderCultivationView, HeaderCultivationViewData>(cultivationViewData);
            break;
        case HeaderResourceViewData resourceViewData:
            await OpenViewAsync<HeaderResourceView, HeaderResourceViewData>(resourceViewData);
            break;
        default:
            await HideView(false);  // 不识别的类型 → 隐藏视图区域
            break;
    }
}
```

`IHeaderViewData` 是一个标记接口（Marker Interface），`HeaderCultivationViewData` 和 `HeaderResourceViewData` 都实现它。通过 `switch` 的模式匹配（C# 7.0+），根据运行时类型分发到正确的子视图。

**为什么不用子类多态（虚方法）**：

如果用多态，需要在每个 ViewData 上加 `virtual/override`，然后让 ViewData 知道如何打开对应的视图——这让数据对象依赖了 UI 系统，违反了分层原则。用 `switch` 匹配让 UI 层决定"什么数据对应什么视图"，更符合 MVC 架构。

---

## HeaderResourceView：资源对象池

```csharp
private void CurrencyInfo(List<ResourceData> resourceDataList)
{
    foreach (var resourceData in resourceDataList)
    {
        var resourceItem = CreateItem<Item_Resource>(
            u_ComCurrencyBtnGroupRectTransform, 
            ItemResourcePath
        );
        resourceItem.UpdateCurrencyInfo(
            resourceData.ItemId, 
            resourceData.Num, 
            resourceData.ShowAdd, 
            RechargeDiamond  // 点击充值的回调
        );
    }
}

private T CreateItem<T>(Transform parent, string assPath) where T : UIBase, IUIBasePoolable
{
    var pool = UIBasePoolManager<T>.GetUIBasePool(assPath, parent);
    var item = pool.Get();
    item.OwnerRectTransform.SetParent(parent, false);
    return item;
}
```

`UIBasePoolManager<T>.GetUIBasePool(assPath, parent)` 是框架提供的 UI 对象池，支持：
- 按资源路径区分不同类型的对象池
- 支持 `IUIBasePoolable` 接口的 `OnRelease` 清理回调
- 父节点（parent）用于定位对象（不同父节点可能用不同池）

**泛型约束**：`where T : UIBase, IUIBasePoolable` 确保传入的类型既是 YIUI 的 UIBase（有 OwnerRectTransform），又实现了对象池接口（有 OnRelease 回调）。

---

## 充值功能的占位处理

```csharp
private void RechargeDiamond(int itemId)
{
    if (itemId == 1001000001)
        UIHelper.ShowTips("钻石充值暂未开放");
    else if (itemId == 1001000002)
        UIHelper.ShowTips("金币充值暂未开放");
}
```

这是一个典型的"功能占位"实现：充值功能还没开发完，但 UI 按钮已经有了。通过显示"暂未开放"的提示，既保留了入口位置，又不让玩家误以为是 Bug（如果点了没有反应）。

**注意硬编码 ID**：`1001000001` 和 `1001000002` 没有用常量名，是一个技术债。正确做法是定义常量：

```csharp
private const int DiamondItemId = 1001000001;
private const int GoldItemId = 1001000002;
```

---

## 预加载依赖声明

```csharp
public override void GetDependentRes(List<string> lstRes, List<string> lstOther, ParamVo paramVo)
{
    base.GetDependentRes(lstRes, lstOther, paramVo);
    lstRes.Add(Item_Resource.ResLoadPath);           // 资源条目 Prefab
    lstRes.Add(HeaderResourceViewPath);              // 资源视图 Prefab
    lstRes.Add(HeaderCultivationViewPath);           // 培养视图 Prefab
    lstRes.Add(HeaderCultivationConditionItem.ResLoadPath);  // 培养条件条目
}
```

通过 `GetDependentRes` 声明面板需要的资源，框架在面板打开前预加载，避免显示时的卡顿。

注意 `lstRes`（需要等待加载完成的资源）和 `lstOther`（可以后台加载的资源）的区别：
- `lstRes`：面板出现前必须加载完毕（图片、Prefab 等关键资源）
- `lstOther`：面板可以先显示，这些资源在后台加载（可能用于延迟加载的部分）

---

## 总结

顶部导航栏的设计展示了：

1. **事件驱动的全局 UI 控制**：任何界面通过发布事件控制导航栏，零耦合
2. **策略模式**：`_backCallback`/`_homeCallback` 允许覆盖默认行为，同时保留默认
3. **条件可见性**：按钮的显示不只是 `SetActive(true)`，还有业务条件检查
4. **模式匹配多态**：`switch (viewData) { case TypeA: ... case TypeB: ... }` 优于数据对象依赖视图
5. **对象池**：资源条目从 `UIBasePoolManager` 取出，不重复创建
6. **预加载声明**：`GetDependentRes` 声明依赖，框架提前加载
