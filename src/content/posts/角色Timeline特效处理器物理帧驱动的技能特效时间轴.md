---
title: 角色Timeline特效处理器——物理帧驱动的技能特效时间轴
published: 2026-03-31
description: 深入解析游戏技能特效与Timeline的联动机制，从物理帧事件到StartTimePointer遍历的完整特效触发流程
tags: [Unity, 特效系统, Timeline]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 角色Timeline特效处理器——物理帧驱动的技能特效时间轴

手游战斗中的技能特效令人眼花缭乱：释放技能时粒子喷发、命中时爆炸光效、移动时残影拖尾……这些特效不是简单调用`PlayEffect()`，而是精确地绑定在动画时间轴的特定帧上。

VGame项目用`TimelineTickEvent`实现了这套"物理帧驱动的Timeline特效处理"，本文深入分析这套机制。

## 一、物理帧 vs 渲染帧

```csharp
[Event(SceneType.Current)]
public class TimelineTickEvent : AEvent<Evt_TimelineTick>
{
    // 物理帧驱动（而非渲染帧）
    protected override void Run(Scene scene, Evt_TimelineTick args)
    {
        // 关键判断：受timescale影响，没有往前走过1帧
        if (!args.changeFrame)
        {
            return; // 没有推进帧就不处理
        }
        ProcessEffect(args.unit, args.timeline);
    }
}
```

`Evt_TimelineTick`是由帧同步系统（TrueSync）在每个逻辑帧触发的事件，而不是Unity的渲染帧（MonoBehaviour.Update）。

**为什么用物理帧而不是渲染帧？**

帧同步游戏中，逻辑和表现是分离的：
- **逻辑层**（物理帧）：确定性计算，所有客户端必须结果完全一致
- **表现层**（渲染帧）：视觉表现，可以有差异

技能触发的**时机**（第几帧）属于逻辑层，必须基于物理帧。如果用渲染帧，不同设备帧率不同，特效触发时机就不一致。

`args.changeFrame`判断本次物理tick是否真的推进了逻辑帧（帧同步可能因为等待其他客户端的数据而暂停推进），没有推进就不需要检查特效。

## 二、特效配置的查找路径

```csharp
private void ProcessEffect(Unit unit, Timeline timeline)
{
    var effectComp = unit.GetComponent<EffectComponent>();
    if (effectComp == null) return;
    
    var timelineComp = unit.GetComponent<TimelineComponent>();
    
    // 优先使用Override路径（技能特效覆盖）
    // 否则使用角色默认特效配置
    var effectInfo = !string.IsNullOrEmpty(timelineComp.OverrideEffectJsonPath) 
        ? RootMotionComponent.Instance.TryGetData<EffectInfo>(timelineComp.OverrideEffectJsonPath)
        : effectComp.EffectInfo;
    
    if (effectInfo != null)
    {
        ProcessTimelineEffect(unit, timeline);
    }
}
```

特效有两个来源：
1. **角色默认特效（effectComp.EffectInfo）**：角色自身的常规特效（如移动粒子、待机发光）
2. **Override特效（timelineComp.OverrideEffectJsonPath）**：当前播放技能的专属特效

Override设计允许同一套特效组件支持不同技能的不同特效，而不需要每个技能都挂载独立的特效组件。

## 三、遍历Timeline寻找动画特效节点

```csharp
private void ProcessTimelineEffect(Unit unit, Timeline timeline)
{
    if (timeline == null) return;
    
    foreach (var timePointer in timeline.timePointers)
    {
        // 只处理"开始时间指针"（StartTimePointer）
        if (timePointer is not StartTimePointer) continue;
        
        // 处理嵌套Timeline引用（Timeline可以引用子Timeline）
        if (timePointer.target is CLIP_TimelineReference clipTimelineReference)
        {
            ProcessTimelineEffect(unit, clipTimelineReference.RefTimeline);
            continue;
        }
        
        // 只处理"播放动画"类型的Clip
        if (timePointer.target is not CLIP_PlayAnimation playAnimationClip) continue;
        
        // 没有开启特效功能的动画Clip，跳过
        if (!playAnimationClip.playEffect) continue;
        
        // Clip结束或未开始，跳过
        if (timeline.currentTime >= playAnimationClip.endTime || 
            timeline.currentTime < playAnimationClip.startTime) continue;
        
        // 获取特效需要的上下文组件
        var characterGo = unit.GetComponent<GameObjectComponent>().GameObject;
        var terrainViewComp = unit.Domain.GetComponent<TerrainViewComponent>();
        var vpComp = unit.GetComponent<VirtualSkeletonPointComponent>();
        var cameraComp = unit.Domain.GetComponent<CameraComponent>();
        var characterEffect = characterGo.GetComponent<CharacterEffect>();
        
        if (terrainViewComp != null && characterEffect != null)
        {
            characterEffect.UpdateEffect(
                unit, 
                playAnimationClip.AnimationClipKey, 
                timeline.currentTime, 
                playAnimationClip.startTime,
                playAnimationClip.startCutFrame,
                // ...更多参数
            );
        }
    }
}
```

几个重要的设计细节：

**StartTimePointer的语义**：Timeline由一系列时间指针（TimePointer）组成，`StartTimePointer`代表一个Clip的开始时刻。只遍历`StartTimePointer`意味着每当某个动画Clip开始播放时，检查它是否需要触发特效。

**递归处理子Timeline**：`CLIP_TimelineReference`是对另一条Timeline的引用，实现了Timeline的嵌套复用（类似函数调用）。遇到引用就递归进去处理，支持任意深度的嵌套。

**时间范围检查**：只有当`currentTime`在`[startTime, endTime]`内，才认为这个Clip正在播放，需要更新特效。这防止了Clip未开始或已结束时触发特效。

## 四、EffectComponent的初始化

```csharp
[FriendOf(typeof(EffectComponent))]
public static partial class EffectComponentSystem
{
    [EntitySystem]
    private static void Awake(this EffectComponent self)
    {
        string effectPath = string.Empty;
        
        // 从角色配置表读取特效JSON路径
        var charaConf = self.GetParent<Unit>().GetConfig<CBaseCharacter>();
        if (charaConf != null)
        {
            effectPath = charaConf.Effect;
        }
        
        // 加载EffectInfo（特效描述JSON）
        if (!string.IsNullOrEmpty(effectPath))
        {
            self.EffectInfo = RootMotionComponent.Instance
                .TryGetData<EffectInfo>(PathUtil.GetEffectJSONPath(effectPath));
        }
        
        // 把EffectInfo注入到角色的CharacterEffect组件
        var characterEffect = self.Parent.GetComponent<GameObjectComponent>()
            .GameObject.GetOrAddComponent<CharacterEffect>();
        characterEffect.effectInfo = self.EffectInfo;
    }
}
```

`CharacterEffect`是Unity Component（挂在GameObject上），`EffectComponent`是ET Component（挂在Unit实体上）。

**两层特效组件**：
- `EffectComponent`：逻辑层，管理特效配置数据（EffectInfo）
- `CharacterEffect`：表现层，实际触发和播放粒子特效

`RootMotionComponent.Instance.TryGetData<EffectInfo>(path)`从缓存中读取EffectInfo JSON数据，避免重复IO。`TryGetData`是安全版本，路径不存在时返回null而不是抛异常。

## 五、角色显隐特效的触发

`GameObjectComponentSystem`中有另一套重要特效逻辑——角色出场/退场特效：

```csharp
// 角色显示时
if (argv.bShow)
{
    goComp.ApplyLogicActive();
    if (!argv.bIgnoreEff)
    {
        // 战斗中：播放英雄入场特效（有帧同步约束）
        if (BattleAPI.IsInBattle(BattleSptComp))
            EffectSystem.Instance.PlayHeroEnterEffect(unitGo, null, updatemode, false);
        else
            EffectSystem.Instance.PlayHeroEnterEffect(unitGo, null, updatemode, true);
    }
}
// 角色隐藏时
else
{
    if (!argv.bIgnoreEff)
    {
        // 播放退场特效，特效播完后才真正隐藏GameObject
        EffectSystem.Instance.PlayHeroExitEffect(unitGo, async () =>
        {
            await TimerComponent.Instance.WaitFrameAsync();
            goComp.ApplyLogicActive(); // 特效播完后隐藏
        }, updatemode);
    }
    else
    {
        goComp.ApplyLogicActive(); // 无特效直接隐藏
    }
}
```

**退场时的延迟隐藏**：调用`PlayHeroExitEffect`并传入回调，等退场动画（如消散效果）播完后，才真正`SetActive(false)`。如果立刻隐藏，玩家会看到角色突然消失，体验很差。

**战斗内外的差异**：战斗中用帧同步控制的时间轴（`false`参数关闭某些非同步特效），战斗外用Unity标准时间轴，保证帧同步一致性。

## 六、VirtualSkeletonPointComponent的用途

```csharp
var vpComp = unit.GetComponent<VirtualSkeletonPointComponent>();
```

`VirtualSkeletonPoint`（虚拟骨骼挂点）用于定义特效播放的世界位置：
- "右手特效"：附着在右手骨骼
- "脚下特效"：附着在脚部骨骼
- "头顶特效"：附着在头部骨骼

特效从`effectInfo`里读取"挂点名称"，通过`VirtualSkeletonPointComponent`查找对应的骨骼世界坐标，在那里生成粒子系统。

## 七、总结

Timeline特效系统的设计展示了：

1. **物理帧驱动**：确保帧同步游戏中特效触发的一致性
2. **changeFrame防冗余**：只有逻辑帧推进时才处理特效
3. **Override覆盖机制**：技能专属特效可以覆盖角色默认特效
4. **递归子Timeline**：支持Timeline嵌套复用
5. **延迟隐藏**：退场特效播完后才真正隐藏，视觉流畅

对新手来说，最值得学习的是"物理帧和渲染帧分离"的思想——在需要确定性的逻辑（帧同步）里，永远用物理帧驱动，不要依赖渲染帧的时机。
