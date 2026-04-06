---
title: 手游自适应画质系统设计——基于性能分动态调节LOD等级
published: 2026-03-31
description: 深入剖析移动端手游自适应画质系统，从FPS监控到LOD评分触发，实现设备自动降配保帧
tags: [Unity, 性能优化, 自适应画质]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# 手游自适应画质系统设计——基于性能分动态调节LOD等级

移动端手游面临一个根本性的矛盾：高中低端机型的性能差距可以达到10倍，但游戏必须在所有机型上流畅运行。

解决这个矛盾有两种思路：
1. **静态分级**：按设备型号预设高中低三档画质配置
2. **动态自适应**：运行时持续监控FPS和温度，自动升降画质

静态分级简单，但有两个问题：一是新机型层出不穷，配置表难以维护；二是同一设备在不同游戏场景下的压力差别很大（空场景帧数高，大规模战斗帧数低）。

本文分析VGame项目的`AdaptiveLodMgr`系统，它实现了基于性能评分的动态画质调节。

## 一、系统整体架构

```
AdaptiveLodMgr（驱动器）
    ├── AdaptiveLodScoreMgr（评分管理器）
    ├── AdaptiveLodConfig（单项LOD功能配置）
    │     └── FPSChangeRateController（FPS变化率控制器）
    └── LodFeature*（各画质功能实现）
          ├── LodFeatureEffectOffscreenLevel（屏外特效等级）
          ├── LodFeaturePerObjectShadow（角色投影开关）
          ├── LodFeatureRenderScale（渲染分辨率缩放）
          └── LodFeatureTargetFPS（目标帧率控制）
```

**核心理念**：把"要不要降配"（评分触发）和"怎么降配"（功能实现）分离开来。

## 二、可调节的画质功能项

系统支持多种画质调节维度，每种都有独立的实现类：

```csharp
// 渲染分辨率缩放（如将1080P降为720P渲染）
public class LodFeatureRenderScale : LodFeatureBase { }

// 屏外特效等级（屏幕外的粒子特效降级）
public class LodFeatureEffectOffscreenLevel : LodFeatureBase { }

// 每对象投影（是否为每个角色生成独立阴影）
public class LodFeaturePerObjectShadow : LodFeatureBase { }

// 目标帧率（将60帧目标降为30帧）
public class LodFeatureTargetFPS : LodFeatureBase { }
```

**为什么要把每项功能做成独立类而不是if-else？**

这是开闭原则的体现。新增一种画质调节维度（比如关闭景深），只需新增`LodFeatureDepthOfField`类，不需要修改`AdaptiveLodMgr`。每项功能的升档/降档逻辑、回滚逻辑都封装在自己的类里，互不干扰。

## 三、评分触发机制

`AdaptiveLodScoreMgr`维护两种评分字典：

```csharp
public class AdaptiveLodScoreMgr : SingletonMono<AdaptiveLodScoreMgr>
{
    // 视觉影响评级 → 分数
    // 视觉影响越大，降配需要更高的性能压力分才触发
    private Dictionary<VisImpactLv, int> VisImpackLvDict;

    // 性能因子类型 → 当前分数
    // 每帧更新，FPS低/温度高时分数累积
    private Dictionary<TriggerConditionType, int> PerformanceDict;
    
    public int GetScoreDefault(VisImpactLv visImpactLv)
    {
        return VisImpackLvDict[visImpactLv]; // 获取该视觉等级的触发阈值
    }
    
    public int GetScoreDefault(TriggerConditionType performance)
    {
        return PerformanceDict[performance]; // 获取性能因子的当前分值
    }
}
```

**这套评分机制的精妙之处**：

不同画质功能的"视觉影响"不同。比如：
- 关闭投影（`PerObjectShadow`）：视觉影响大，需要性能压力很高才触发
- 降低屏外特效等级：视觉影响小，稍微有点性能压力就可以触发

通过`VisImpactLv`（视觉影响等级）来控制触发顺序，保证优先降低视觉影响小的功能，保留视觉影响大的功能。

## 四、LOD配置的初始化流程

```csharp
public partial class AdaptiveLodMgr : SingletonMono<AdaptiveLodMgr>
{
    private AdaptiveLodFullData lodFullData;
    private Dictionary<int, AdaptiveLodConfig> allLodDict;
    
    public void Awake()
    {
        InitLoadConfig();   // 1. 加载配置文件
        InitAllLodDict();   // 2. 初始化LOD字典
        InitScoreComponent(); // 3. 初始化评分组件
        isHasInit = true;
    }
    
    private void InitLoadConfig()
    {
        // 加载配置ScriptableObject（运行时配置，可热更）
        var temp = ResManager.Load<System.Object>("Profile/AdaptiveLod_Android.asset");
        lodFullData = temp as AdaptiveLodFullData;
    }
    
    private void InitAllLodDict()
    {
        foreach (var lodData in lodFullData.AdaptiveLodList)
        {
            if (lodData.mute) continue; // 跳过被禁用的LOD功能
            
            int lodType = (int)lodData.lodType;
            AdaptiveLodConfig config = new AdaptiveLodConfig();
            config.Init(lodData, lodData.triggerDatas);
            allLodDict[lodType] = config;
        }
    }
}
```

注意配置文件名`AdaptiveLod_Android.asset`——原来有分平台加载的逻辑（被注释掉了），说明项目早期确实做过iOS/Android/PC的差异化配置，后来统一了，但保留了灵活性。

## 五、Update轮询：分帧优化思路

```csharp
public void Update()
{
    if (!IsEnableAdaptiveLod()) return;
    if (IsOnlyBattle && !RenderManager.isInBattleScene) return;
    if (!isHasInit) return;
    
    // 第一步：更新所有LOD的计时器状态
    foreach (var i in allLodDict)
    {
        i.Value.UpdateUpTimer();
    }
    
    // 第二步：执行自适应逻辑（评分 → 触发降配/升配）
    AdaptiveLogic();
}
```

注意代码注释掉的分帧逻辑：

```csharp
// 分帧逻辑（被注释）
// if (EnableSplitFrame)
// {
//     frameCount++;
//     if (frameCount <= splitFrameCount) return;
//     frameCount = 0;
// }
```

这是一个性能优化思路：不需要每帧都评估LOD，每60帧评估一次就够了（玩家感知不到1秒内的配置变化）。但分帧会导致"计时器"逻辑复杂，所以最终取消了，直接每帧运行，但`AdaptiveLogic`内部做了防抖处理。

## 六、升档/降档的时机控制

频繁切换画质等级会让玩家明显感知到屏幕抖动，需要防抖机制：

```csharp
public class AdaptiveLodConfig
{
    // 升档计时器：帧数低的状态持续N秒后才降配
    // 升档计时器：帧数恢复后需要持续M秒才升配（比降配更慢）
    public void UpdateUpTimer()
    {
        // isUpTimerOver：升档等待时间是否到了
    }
}
```

**为什么降配快、升配慢？**

这是用户体验层面的考量：
- 帧率下降时应该快速响应降配，防止玩家感受到卡顿
- 帧率恢复时应该慢慢升配，如果画质频繁高低变化，玩家会看到画质忽好忽差，体验反而更差

典型策略：FPS连续3秒低于45帧 → 降配；FPS连续15秒稳定60帧 → 升配。

## 七、重置机制：场景切换时的处理

```csharp
public void Reset()
{
    if (!IsEnableAdaptiveLod()) return;
    DebugLog("[AdaptiveLodMgr]: Reset");
    ResetAllAdaptiveLodState();
}
```

场景切换（如战斗 → 大厅）时调用`Reset()`：
1. 清空所有已触发的降配状态（关闭投影要重新开启、渲染分辨率要恢复等）
2. 清空评分历史（新场景从零开始评估）

这很重要——如果不Reset，玩家从激烈战斗（高压）进入大厅（低压），大厅会保持战斗时的低画质配置，画面很丑但游戏流畅，玩家会困惑。

## 八、电量与温度的联动

代码中有一个有趣的接口：

```csharp
public void UpdateBatteryEvent(EDeviceThermalStatus thermalStatus, bool isCharging, bool shouldNotic = false)
{
    // 目前是空实现，留待接入设备温度SDK
}
```

这是预留的扩展点。手机过热时，即使帧率还可以，也应该主动降配，防止系统强制降频导致突然大卡。国内大部分手游已经接入第三方温控SDK（如`DeviceBattery`），当手机温度超过某个阈值时，主动降配+提示用户"游戏已开启省电模式"。

## 九、实战中遇到的问题

**问题1：测试机表现好，低端机掉帧**

原因：公司测试机都是中高端机，自适应系统根本没机会触发。需要建立专门的低端机测试流程，且需要GM指令强制触发降配。

```csharp
#if ENABLE_GM
LODMgr.Instance.IsAdaptiveLodConsole = false; // GM强制禁用自适应
#endif
```

**问题2：降配状态在热更后丢失**

热更时ECS世界会重建，MonoSingleton的状态丢失。需要在重建后调用一次`Initialize()`重新加载配置。

**问题3：Editor模式的不稳定FPS**

在Unity Editor里FPS本来就不稳定（各种Debug开销），自适应系统会频繁触发降配/升配。解决方案：Editor下强制禁用自适应。

## 十、总结：自适应系统的设计哲学

| 维度 | 设计决策 |
|------|---------|
| 配置驱动 | LOD功能项、触发阈值全部来自配置文件，策划可直接调整 |
| 功能解耦 | 每种画质调节独立实现，新增功能不影响现有逻辑 |
| 评分触发 | 用"积分"而非即时FPS决策，避免抖动 |
| 视觉优先 | 视觉影响大的功能最后才降配 |
| 场景隔离 | 场景切换时完整Reset，防止状态污染 |

对新手来说，理解自适应系统的精髓就一句话：**在玩家察觉不到的前提下，让游戏在任何设备上都保持最好的体验**。
