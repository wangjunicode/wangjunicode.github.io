---
title: 技能系统设计与实现（SkillComponent）
published: 2024-01-01
description: "技能系统设计与实现（SkillComponent） - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
---

# 技能系统设计与实现（SkillComponent）

## 1. 系统概述

本项目技能系统基于 **NodeCanvas FlowCanvas（改版为 UniScript）** 可视化图驱动，每个技能是一张 `SkillGraph`（流图），技能逻辑通过节点连线定义，策划可以在不写代码的情况下配置技能行为。

**架构关键点：**
- 每个 `Unit` 挂载一个 `SkillComponent`，持有当前所有活跃的 `SkillGraph` 实例
- `SkillMgrComponent` 负责技能的预加载与实例池化
- 技能执行走 FSM → SkillComponent → SkillGraph 调用链
- 帧同步下：技能图的 `UpdateMode = Manual`，由 `LockStepComponent` 统一驱动

---

## 2. 核心类结构

```
SkillMgrComponent（技能管理器，负责加载）
    └── SkillGraphAsset（技能资产，从 Addressables 加载）
            └── SkillGraph（运行时实例，继承 FlowGraph）

SkillComponent（挂在每个 Unit 上，负责执行）
    ├── SkillList: List<SkillGraph>   // 当前活跃的技能图实例
    ├── StartSkill(skillId)           // 启动技能
    ├── StopAll()                     // 停止所有技能
    └── EnterFrame(fixedDeltaTime)    // 帧同步驱动
```

---

## 3. 核心代码解析

### 3.1 启动技能

```csharp
// 位置：Hotfix/Battle/Function/GamePlay/Skill/SkillComponentSystem.cs
[FriendOf(typeof(SkillComponent))]
public static partial class SkillComponentSystem
{
    // 开启技能（await 等待技能完整执行结束）
    public static async ETTask<bool> StartSkill(this SkillComponent self, int skillId)
    {
        var info = self.AddSkillInfo(skillId);  // 从池中取或新建 SkillGraph 实例
        return await info.Start();              // 异步启动，等待技能结束
    }

    // 技能参数传递（链式调用，策划友好）
    // 用法：bool result = await GetOrAddSkillInfo(skillId).AddVariable("test",0).Start();
    public static SkillGraph AddVariable<T>(this SkillGraph skill, string key, T value)
    {
        var old = skill.localBlackboard.GetVariable(key);
        if (old != null)
        {
            if (old.varType == typeof(T))
            {
                ((Variable<T>)(old)).value = value;
                return skill;
            }
            old.value = value;
            return skill;
        }
        // 变量不存在时，新建并添加到 Blackboard
        var variable = new Variable<T>();
        variable.name = key;
        variable.value = value;
        skill.localBlackboard.AddVariable(variable);
        return skill;
    }
```

### 3.2 帧同步驱动技能执行

```csharp
    // EnterFrame 由 LockStepComponent 在每个 Fixed Tick 调用
    public static void EnterFrame(this SkillComponent self, FP fixedDeltaTime)
    {
        VProfiler.BeginDeepSample("SkillComponent.EnterFrame");
        var unit = self.GetParent<Unit>();
        
        // Host 单元（服务端影子或AI Host）不执行技能图
        if (unit.bHost) return;
        
        for (int i = 0; i < self.SkillList.Count; i++)
        {
            var skill = self.SkillList[i];
            // 只驱动正在运行且 UpdateMode 为 Manual 的技能图
            // Manual 模式：不依赖 Unity MonoBehaviour Update，完全由代码手动驱动
            if (skill.isRunning && skill.updateMode == Graph.UpdateMode.Manual)
            {
                skill.UpdateGraph(fixedDeltaTime);
            }
        }
        VProfiler.EndDeepSample();
    }
```

### 3.3 技能加载与同步

```csharp
    // 同步加载已预加载的技能（帧同步不能异步，需提前预加载）
    private static void SyncLoadedSkil(this SkillComponent self, Evt_SyncLoadedSkill arg)
    {
        // 校验是否是本 Unit 的技能
        if (arg.unit != self.GetParent<Unit>()) return;
        self.AddSkillInfo(arg.skillId);
    }
```

### 3.4 技能停止

```csharp
    public static void StopAll(this SkillComponent self)
    {
        foreach (var skill in self.SkillList)
        {
            if (skill.isRunning)
            {
                skill.Stop();
            }
        }
        self.SkillList.Clear();
    }
```

---

## 4. SkillMgrComponent —— 技能资产管理

```csharp
// Hotfix/Battle/Model/Framework/Skill/SkillMgrComponent.cs
public class SkillMgrComponent : Entity, IAwake, IDestroy
{
    // 已加载的技能资产缓存（skillId → SkillGraphAsset）
    public Dictionary<int, SkillGraphAsset> SkillAssetDict { get; set; }
    
    // 运行时技能图实例池（skillId → 空闲实例列表）
    public Dictionary<int, List<SkillGraph>> SkillGraphPool { get; set; }
}

[FriendOf(typeof(SkillMgrComponent))]
public static partial class SkillMgrComponentSystem
{
    // 预加载：在战斗开始前加载所有本场战斗需要的技能资产
    public static async ETTask PreloadSkills(this SkillMgrComponent self, List<int> skillIds)
    {
        foreach (int skillId in skillIds)
        {
            if (self.SkillAssetDict.ContainsKey(skillId)) continue;
            
            // 异步从 Addressables 加载技能图资产
            var asset = await YIUILoader.LoadAssetAsync<SkillGraphAsset>(GetSkillPath(skillId));
            if (asset != null)
            {
                self.SkillAssetDict[skillId] = asset;
            }
        }
    }
    
    // 从池中获取技能图实例（避免每次 new）
    public static SkillGraph GetOrCreateSkillGraph(this SkillMgrComponent self, int skillId)
    {
        if (self.SkillGraphPool.TryGetValue(skillId, out var pool) && pool.Count > 0)
        {
            var graph = pool[pool.Count - 1];
            pool.RemoveAt(pool.Count - 1);
            return graph;
        }
        
        // 池中没有，克隆一份新的（从 Asset 克隆，不修改原始资产）
        if (self.SkillAssetDict.TryGetValue(skillId, out var asset))
        {
            return asset.GetGraphCopy() as SkillGraph;
        }
        return null;
    }
    
    // 用完归还
    public static void ReturnSkillGraph(this SkillMgrComponent self, int skillId, SkillGraph graph)
    {
        if (!self.SkillGraphPool.ContainsKey(skillId))
        {
            self.SkillGraphPool[skillId] = new List<SkillGraph>();
        }
        graph.Reset();  // 重置图状态
        self.SkillGraphPool[skillId].Add(graph);
    }
}
```

---

## 5. 技能图节点扩展

UniScript（FlowCanvas 定制版）允许扩展自定义节点：

```csharp
// 自定义 ActionTask 节点示例：播放 Timeline
[Category("VGame/Timeline")]
[Name("Play Timeline")]
public class PlayTimeline : ActionTask
{
    // 节点参数（可在 Inspector 中配置，或连接 Blackboard 变量）
    [RequiredField] public BBParameter<string> timelineName;
    [BlackboardOnly] public BBParameter<Unit> unit;

    protected override string OnInit() => null;

    protected override void OnExecute()
    {
        var u = unit.value;
        if (u == null) { EndAction(false); return; }
        
        var timelineComp = u.GetComponent<TimelineComponent>();
        timelineComp.Play(timelineName.value).Coroutine();
        EndAction(true);
    }
}
```

---

## 6. Motion Warping（动作瞄准系统）

```csharp
// Hotfix/Battle/Model/Framework/Skill/MotionWarpingData.cs
// Motion Warping：在技能动画播放时，实时将角色位置"拉向"目标点
[MemoryPackable]
public partial class MotionWarpingData
{
    public FP startTime = 0;       // 从技能第几帧开始生效
    public FP endTime = FP.MaxValue; // 结束时间

    public bool updateTargetPoint = true;  // 每帧实时更新目标位置（追踪移动目标）
    public bool forceAlign = false;        // 到达后强制对齐（不允许偏差）

    // 移向敌人的百分比（1=完全到达，0.5=走一半距离）
    public FP percentToEnemy = 1;
    public TSVector offset = new TSVector(0, 0, -1);  // 最终偏移

    // 生效条件：默认闪避状态下不生效（被打断时自然停止移动）
    public ConditionTask wrapCondition = new CT_CheckInDodge();
}
```

---

## 7. Root Motion 系统

```csharp
// Hotfix/Battle/Model/Framework/Skill/RootMotionData.cs
// 从动画文件提取的根运动数据，按帧存储位置和旋转
[MemoryPackable]
public partial class RootMotionData
{
    public List<TSVector> rootMotionPositions;     // 每帧位置偏移量（定点数）
    public List<TSQuaternion> rootMotionRotations; // 每帧旋转

    // 按时间插值获取采样数据（用于帧同步中精确驱动角色移动）
    public void GetSampleData(FP time, ref TSVector displacement, ref TSQuaternion rotation)
    {
        var frameIdx = (time / EngineDefine.fixedDeltaTime_Orignal).AsInt();
        var nextFrameIdx = frameIdx + 1;
        
        TSVector d1 = TSVector.zero, d2 = TSVector.zero;
        TSQuaternion r1 = TSQuaternion.identity, r2 = TSQuaternion.identity;
        
        GetSampleData(frameIdx, ref d1, ref r1);
        GetSampleData(nextFrameIdx, ref d2, ref r2);
        
        // 两帧之间线性插值（定点数 Lerp）
        var t = (time - frameIdx * EngineDefine.fixedDeltaTime_Orignal) 
                / EngineDefine.fixedDeltaTime_Orignal;
        displacement = TSVector.Lerp(d1, d2, t);
        rotation = TSQuaternion.Slerp(r1, r2, t);
    }
}
```

---

## 8. FSM 与技能系统的协作

```
用户按技能键
    ↓
LockStepComponent.OnInputVKey(EInputKey.Skill_1)
    ↓
FSMComponent.TryManualCondition(EInputKey.Skill_1)
    ↓
UniFSM 检查当前状态是否允许触发 Skill_1 条件转移
    ↓（允许）
FSM 切换到 CustomSkill 状态
    ↓
CustomSkill 状态的 OnEnter 回调
    ↓
SkillComponent.StartSkill(skillId)   // 启动技能图
    ↓
SkillGraph 开始执行（Manual 模式，逐帧 UpdateGraph）
    ↓
技能图结束（EndAction）→ FSMComponent.SetIdle() → 回到 Idle 状态
```

---

## 9. 常见问题与最佳实践

**Q: 技能图必须 `ManualUpdate` 吗？**  
A: 是的。帧同步游戏中，所有逻辑必须在 Fixed Tick 中按顺序执行。如果用 Unity 的 `Update` 驱动，时序无法保证，会导致不同客户端执行顺序不一致。

**Q: 技能被打断如何处理？**  
A: 调用 `SkillComponent.StopSkill(skillId)`，技能图的 `Stop()` 会触发图内所有 `OnInterrupt` 回调，做清理工作（停止移动、清除Buff等）。

**Q: 技能图资产热更新后，运行时实例会更新吗？**  
A: 不会。`SkillMgrComponent` 中池化的 `SkillGraph` 实例是 Clone，资产更新后需要清空池、重新从新资产克隆。热更新重启战斗后生效。

**Q: 同一技能多实例并发怎么处理？**  
A: `SkillGraphPool` 支持多实例。同一技能 ID 的多个并发实例，从池中取不同的 Clone 实例，各自独立执行，互不干扰。
