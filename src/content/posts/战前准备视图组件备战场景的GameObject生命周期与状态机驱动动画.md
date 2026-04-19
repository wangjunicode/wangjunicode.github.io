---
title: 战前准备视图组件——备战场景的GameObject生命周期与状态机驱动动画
published: 2026-03-31
description: 解析战前备战界面的视图组件设计，包括场景预制体DontDestroyOnLoad管理、Animator状态机驱动与相机近远裁剪面调整
tags: [Unity, UI系统, 战斗系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战前准备视图组件——备战场景的GameObject生命周期与状态机驱动动画

PVP或副本战斗开始前，玩家通常需要看到一个"战前准备"界面：展示我方角色阵容、查看敌方信息、进行最后的策略调整……这个界面背后的技术实现比看起来复杂。

xgame项目的`PreBattleViewComponentSystem`管理了战前备战场景的完整生命周期，本文深入分析这套设计。

## 一、战前备战场景的特殊性

战前备战有几个特殊需求：
1. 需要在战斗场景加载之前展示（此时战斗资源还没完全加载）
2. 切换到战斗场景时，备战界面要无缝消失（不能有黑屏闪烁）
3. 备战界面的角色模型位置要与战斗初始位置对齐（保证视觉连续性）

## 二、PreBattleGo的DontDestroyOnLoad

```csharp
public static void CreatePreBattleGo(this PreBattleViewComponent self, Evt_InitPreBattleScene argv)
{
    if (self.BCreate) return; // 防止重复创建
    
    // 加载备战场景预制体
    var prefab = AssetCache.GetCachedAssetAutoLoad<GameObject>(PreBattleViewComponent.PreBattleGOPath);
    self.PreBattleGo = UnityEngine.Object.Instantiate(prefab);
    
    // 关键：不随场景销毁
    UnityEngine.Object.DontDestroyOnLoad(self.PreBattleGo);
    
    self.IsShowingScene = true;
    self.InitPos(); // 设置位置对准我方主角
    
    // 角色背景预制体
    var characterPrefab = AssetCache.GetCachedAssetAutoLoad<GameObject>(PreBattleViewComponent.UnitBGPath);
    self.UnitBGGo = UnityEngine.Object.Instantiate(characterPrefab);
    UnityEngine.Object.DontDestroyOnLoad(self.UnitBGGo);
    self.UnitBGGo.SetActive(false); // 初始不显示角色背景
    
    self.BCreate = true;
}
```

`DontDestroyOnLoad`确保备战场景预制体在场景切换时不会被销毁。这样：
1. 在加载战斗场景时，备战界面仍然可见（Loading期间不会黑屏）
2. 战斗场景加载完成后，可以精确控制备战界面的淡出时机

## 三、状态机驱动的动画切换

```csharp
public static void OnPreBattleUIStateChange(this PreBattleViewComponent self, EPreBattleState state)
{
    if (self.PreBattleGo != null)
    {
        // 根据状态初始化位置
        if (state == EPreBattleState.Init)
            self.InitPos();
        
        if (state == EPreBattleState.CharacterView)
            self.InitUnitBGPos(); // 切换到角色查看时，对准当前查看的角色
        
        // 用Animator状态机参数驱动动画
        var ani = self.PreBattleGo.GetComponent<Animator>();
        ani.SetInteger("State", (int)state);
        
        var unitAni = self.UnitBGGo.GetComponent<Animator>();
        unitAni.SetInteger("State", (int)state);
    }
}
```

`EPreBattleState`枚举的每个值对应一个界面状态（初始化、主视图、角色详情等），直接映射到Animator的整数参数`State`。

**为什么用Animator的整数参数而不是直接调用`Animator.Play()`？**

用`SetInteger("State", value)`的优势：
1. **状态机控制过渡**：Animator可以设置状态间的混合时间，比直接Play更流畅
2. **防重复**：Animator会检测参数是否真的改变了，不会重复触发动画
3. **艺术家友好**：动画师可以在Animator Controller里调整过渡条件，不需要改代码

## 四、bHasStory标志的Animator联动

```csharp
public static void SetHasStory(this PreBattleViewComponent self, bool bHasStory)
{
    var ani = self.PreBattleGo.GetComponent<Animator>();
    ani.SetBool("bHasStory", bHasStory);
}
```

当当前战斗有剧情前情（`bHasStory=true`），备战界面的Animator会显示一个"查看剧情"按钮或相关动画。这样不需要在代码里手动控制按钮的显示/隐藏，而是通过Animator参数驱动——美术可以自由调整"有剧情时按钮出现的动画效果"，完全不依赖程序。

## 五、相机裁剪面的调整

```csharp
public static void SetActive(this PreBattleViewComponent self, bool isShow)
{
    if (self.IsShowingScene == isShow) return; // 防重复
    
    if (!isShow)
    {
        // 隐藏备战场景时，恢复相机的近远裁剪面
        var cameraComponent = self.CurrentScene().GetComponent<CameraComponent>();
        cameraComponent.GetMainCamera().nearClipPlane = 0.03f;
        cameraComponent.GetMainCamera().farClipPlane = 1000f;
    }
    
    self.PreBattleGo.SetActive(isShow);
    self.IsShowingScene = isShow;
}
```

备战界面可能需要特殊的相机裁剪设置（比如nearClipPlane更大，让近处的UI不被裁剪），隐藏时恢复到战斗的标准设置（nearClipPlane=0.03f）。

这个细节处理防止了"切换回战斗视角时，近处物体因为裁剪面设置不当而消失"的视觉bug。

## 六、InitPos：角色模型位置与战斗初始位置对齐

```csharp
public static void InitPos(this PreBattleViewComponent self)
{
    var TeamComp = self.CurrentScene().GetComponent<TeamComponent>();
    var team = TeamComp.GetMyTeam();
    if (team == null || team.TeamMember.Count == 0) return;
    
    // 取队伍中的第一个成员作为主要位置参考
    var mainMember = team.TeamMember[0];
    self.PreBattleGo.transform.SetPositionAndRotation(
        mainMember.Position.ToVector3(),
        mainMember.Rotation.ToQuaternion());
}
```

备战场景预制体的位置直接用战斗数据中角色的世界坐标设置。这确保了备战界面里角色站的位置，和战斗开始后角色初始站立的位置完全一致——视觉上没有任何"跳变"。

`BattleAPI.GetViewForceIdx`的另一段代码：

```csharp
public static void InitUnitBGPos(this PreBattleViewComponent self)
{
    var TeamComp = self.CurrentScene().GetComponent<TeamComponent>();
    var team = TeamComp.GetMyTeam();
    int idx = BattleAPI.GetViewForceIdx(team); // 获取当前"视图焦点"角色的索引
    if (idx < 0) idx = 0;
    var Member = BattleAPI.GetMemberByIdx(team, idx);
    self.UnitBGGo.transform.SetPositionAndRotation(
        Member.Position.ToVector3(),
        Member.Rotation.ToQuaternion());
    self.UnitBGGo.SetActive(true);
}
```

切换到"角色详情"视图时，背景预制体（`UnitBGGo`）也要对准当前查看的角色位置，提供沉浸感的背景。

## 七、Destroy时的清理逻辑

```csharp
[EntitySystem]
private static void Destroy(this PreBattleViewComponent self)
{
    // 如果在显示详情，发布退出事件
    if (self.IsShowingDetail)
        EventSystem.Instance.Publish(YIUIComponent.ClientScene, new Evt_ExitPrepareDetail());
    
    // 如果在显示备战主界面，发布退出事件
    if (self.IsShowing)
        EventSystem.Instance.Publish(YIUIComponent.ClientScene, new Evt_ExitPrepare());
    
    // 如果已经加载了角色单位，发布卸载事件
    if (self.IsLoadedUnit)
        EventSystem.Instance.Publish(YIUIComponent.ClientScene, new Evt_UnLoadBattlePrepare());
    
    // 销毁DontDestroyOnLoad的游戏对象
    if (self.PreBattleGo != null)
        UnityEngine.Object.Destroy(self.PreBattleGo);
    if (self.UnitBGGo != null)
        UnityEngine.Object.Destroy(self.UnitBGGo);
    
    // 注销事件
    self.ClientScene().GetComponent<EventDispatcherComponent>()
        .UnRegisterEvent<Evt_InitPreBattleScene>(self.CreatePreBattleGo);
    
    self.BCreate = false;
}
```

三个`IsShowing`标志（`IsShowingDetail`、`IsShowing`、`IsLoadedUnit`）的检查确保了任何中途销毁的情况（用户快速退出、网络断线等）都能正确清理所有状态。

**`DontDestroyOnLoad`对象必须手动销毁**：这些对象不随场景切换清理，因此在组件销毁时明确调用`UnityEngine.Object.Destroy`是必须的，否则会内存泄漏。

## 八、OpenCultivation：养成模式的备战

```csharp
public static async ETTask OpenCultivation(this PreBattleViewComponent self)
{
    await OpenLoading(self);       // 显示Loading界面
    await self.LoadUnit();          // 加载角色单位
    await CloseLoading(self);      // 关闭Loading界面
    // 然后显示养成备战专属UI...
}
```

养成模式和普通PVP模式的备战流程有差异，但都通过同一个`PreBattleViewComponent`管理。`OpenCultivation`是养成专属的入口，与普通的备战流程有不同的Loading和UI显示逻辑。

## 九、总结

战前备战视图组件的设计展示了：

1. **DontDestroyOnLoad跨场景持久化**：备战界面在战斗加载期间保持可见
2. **Animator参数驱动**：代码只设置状态值，动画由Animator控制，艺术家可独立调整
3. **位置对齐**：备战模型位置与战斗初始位置一致，无缝过渡
4. **多状态清理**：Destroy时通过isShowing标志发布所有必要的退出事件

对新手来说，"用Animator参数替代直接控制动画"是代码和美术资产解耦的重要技巧——代码只关心"现在是什么状态"，动画效果是什么由美术决定。
