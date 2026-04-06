---
title: Buff状态系统的图驱动设计与生命周期管理
published: 2026-03-31
description: 深入解析基于 FlowGraph 的 Buff 系统架构，理解 Buff 如何通过图执行引擎管理复杂的状态效果
tags: [Unity, 战斗系统, Buff系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Buff状态系统的图驱动设计与生命周期管理

Buff 系统是游戏战斗深度的重要来源。从简单的"持续掉血"到复杂的"击中敌人时触发连锁效果"，Buff 的多样性让战斗充满变化。本文深入解析一套商业级 Buff 系统的设计，特别是它如何借鉴技能系统的图驱动思路，实现极高的可配置性。

---

## 第一性原理：Buff 本质上是什么？

Buff（和 Debuff）本质上是：**附着在某个实体上、持续一段时间、对实体状态产生影响的逻辑单元**。

但"对状态产生影响"可以极其复杂：
- 增加攻击力 20%（属性修改）
- 每秒扣 100 血（持续效果）
- 受到攻击时有30%概率格挡（条件触发）
- 达到3层时爆发，造成额外伤害（堆叠触发）
- 与另一个 Buff 组合时有特殊效果（联动效果）

如果每种 Buff 都写一个 C# 类，100 种 Buff 就是 100 个类，维护成本极高。**最优解是：将 Buff 的行为描述从代码中分离，让策划在工具中配置**——这正是图驱动的核心价值。

---

## Buff 数据模型

```csharp
public class SimpleBuff
{
    public Entity owner;           // Buff 附着的单位
    public int buffConfigId;       // Buff 配置ID（对应策划配置表）
    public int level;              // Buff 等级
    public PassiveSkillInstance ownerSkill; // 谁给的这个Buff
    public BuffGraph graph;        // 驱动这个Buff的图（核心）
}
```

`BuffGraph` 是 Buff 行为的执行引擎，与 `SkillGraph` 是同源的节点图系统：

```csharp
public class BuffGraph : FlowGraph
{
    public SimpleBuff buff;  // 关联的 Buff 数据
    public bool loadFromCache;  // 是否从缓存加载（优化）
    // 继承自 FlowGraph 的黑板、节点等
}
```

---

## BuffComponent：Buff 管理器

每个 Unit 都持有 `BuffComponent`，负责管理所有 Buff 实例：

```csharp
[FriendOf(typeof(BuffComponent))]
public static partial class BuffComponentSystem
{
    [EntitySystem]
    private static void Awake(this BuffComponent self)
    {
        self.m_owner = self.Parent;  // 缓存宿主引用
    }
    
    [EntitySystem]
    private static void Destroy(this BuffComponent self)
    {
        // 销毁时停止所有 Buff 图
        foreach (var simpleBuff in self.buffs)
        {
            simpleBuff.graph?.Stop(false);
        }
    }
    
    [EntitySystem]
    private static void Reset(this BuffComponent self)
    {
        // 重置时清空所有 Buff（战斗重置时用）
        self.buffs.Clear();
        self.buffs2.Clear();
        self.m_toAddBuffs.Clear();
        self.m_toAddBuffs2.Clear();
    }
}
```

### 添加 Buff

```csharp
public static SimpleBuff AddBuff(this BuffComponent self, int id, int level = 1, 
    IBlackboard bb = null, PassiveSkillInstance addedby = null, 
    bool FromCache = false, bool bAutoStart = true)
{
    // 立即添加（不再走帧末队列，直接生效）
    SimpleBuff ret = self.AddBuffImmediately(new BuffComponent.BuffOpInfo { 
        id = id, level = level, addedby = addedby, 
        bb = bb, add = true, fromCache = FromCache 
    }, bAutoStart);
    
    // 通知事件系统（UI更新、成就统计等）
    self.m_owner.GetComponent<EventDispatcherComponent>().FireEvent(new Evt_OnAddBuff()
    {
        BuffId = id,
        Level = level,
        Source = addedby
    });
    
    return ret;
}
```

`bAutoStart` 参数支持"先创建、后手动启动"的延迟启动模式，用于需要在启动前注入参数的场景。

### 移除 Buff

```csharp
// 通过引用移除（精确）
public static void RemoveBuff(this BuffComponent self, SimpleBuff buff)
{
    self.RemoveBuffImmediately(new BuffComponent.BuffOpInfo() { add = false, buff = buff });
}

// 通过 ID 移除（移除所有同 ID 的 Buff）
public static void RemoveBuff(this BuffComponent self, int id)
{
    self.RemoveBuffImmediately(new BuffComponent.BuffOpInfo() { add = false, id = id });
}
```

移除时会将 BuffGraph 放回缓存：

```csharp
private static void RemoveBuffImmediately(this BuffComponent self, SimpleBuff buff)
{
    // 触发离开事件（让 Buff 图有机会做清理，如移除属性加成）
    self.m_owner.GetComponent<EventDispatcherComponent>().FireEvent(new BuffComponent.BuffEventInfo
    {
        Type = BuffComponent.EBuffEventType.Exit,
        Buff = buff
    });
    
    // 调用 Buff 处理器的终结逻辑
    buff.GetHandler<SimpleBuffHandler>().Finalize(buff);
    self.buffs.Remove(buff);
    
    // 回收 BuffGraph 到对象池（核心性能优化）
    var buffCache = self.m_owner.ClientScene().GetComponent<BuffCacheComponent>();
    var buffInfo = buff.graph;
    if (buffInfo != null && buffInfo.loadFromCache)
    {
        buffCache.SetBuffIntoCache(buffInfo.buff.buffConfigId, buffInfo);
    }
}
```

---

## SimpleBuffHandler：Buff 的生命周期管理

`SimpleBuffHandler` 实现了 Buff 从创建到销毁的完整生命周期：

```csharp
public class SimpleBuffHandler : AHandler<SimpleBuff>
{
    // 初始化：创建 Buff 图并启动
    public void Init(SimpleBuff buff, Entity owner, int id, int level, 
        PassiveSkillInstance addedby, IBlackboard bb, bool fromCache, bool bAutoStart)
    {
        buff.owner = owner;
        buff.buffConfigId = id;
        buff.level = level;
        buff.ownerSkill = addedby;
        LoadAndStartGraph(buff, fromCache, bb, bAutoStart);
    }

    // 终结：停止图执行
    public void Finalize(SimpleBuff buff)
    {
        buff.graph?.Stop();
        buff.owner = null;  // 断开引用
    }
    
    // 每帧更新
    public void Update(SimpleBuff buff)
    {
        buff.graph?.UpdateGraph(EngineDefine.fixedDeltaTime_Orignal);
    }
}
```

### Buff 图的加载与初始化

```csharp
private void LoadAndStartGraph(SimpleBuff buff, bool loadFromCache = false, 
    IBlackboard bb = null, bool bAutoStart = true)
{
    var cfg = CfgManager.tables.TBPassiveSkill.Get(buff.buffConfigId, buff.level);
    if (cfg == null) return;

    var buffGraph = cfg.GraphId;
    if (buffGraph.GraphId > 0)
    {
        BuffGraph info = null;
        var path = PathUtil.GetBuffGraphPath(buffGraph.GraphId);
        var buffCache = buff.owner.ClientScene().GetComponent<BuffCacheComponent>();
        
        // 优先从缓存池获取
        if (loadFromCache)
        {
            info = buffCache.TryGetBuff(buffGraph.GraphId);
        }
        
        // 缓存未命中，从文件加载
        if (info == null)
        {
            info = SerializeHelper.Deserialize<BuffGraph>(path);
        }

        if (info == null) return;
        
        // 缓存初始黑板状态（用于重置）
        if (loadFromCache)
        {
            buffCache.SetInitBB(buffGraph.GraphId, info.blackboard);
        }
        
        // 注入运行环境
        info.buff = buff;
        info.engine = buff.owner.CurrentScene().GetComponent<BattleComponent>()?.Engine;
        
        // 注入 self 变量
        var v = info.localBlackboard.GetVariable<Entity>("self");
        if (v == null) v = info.localBlackboard.AddVariable<Entity>("self");
        v.value = buff.owner;
        v.isReadonly = true;
        
        // 设置黑板参数（如Buff的初始持续时间、触发概率等）
        BParamUtility.SetToBlackboard(buffGraph.Args, info.localBlackboard);
        info.blackboard.OverwriteFrom(bb, false);  // 外部黑板覆盖（调用方传入的参数）
        
        if (bAutoStart)
        {
            info.StartGraph(buff.owner as IUniAgent, info.localBlackboard, 
                Graph.UpdateMode.Manual, loadFromCache: loadFromCache);
        }
        buff.graph = info;
    }
}
```

几个关键设计：

**① 缓存初始黑板状态**

```csharp
buffCache.SetInitBB(buffGraph.GraphId, info.blackboard);
```

当 Buff 图从缓存取出时，黑板可能还保留着上次使用的值。保存初始黑板状态，使用时重置，确保每次 Buff 行为一致。

**② 黑板参数系统**

```csharp
BParamUtility.SetToBlackboard(buffGraph.Args, info.localBlackboard);
```

`buffGraph.Args` 是配置表中为这个 Buff 图设置的参数（如"持续时间=5秒"、"触发概率=30%"），通过参数系统注入黑板，Buff 图内部直接读取黑板变量，不需要修改代码就能配置不同的参数值。

---

## Buff 缓存系统

```csharp
public static class BuffCacheComponentSystem
{
    // 将 Buff 图放入缓存池
    public static void SetBuffIntoCache(this BuffCacheComponent self, int buffId, BuffGraph buffGraph)
    {
        if (!self.buffCache.ContainsKey(buffId))
        {
            self.buffCache[buffId] = new Stack<BuffGraph>();
        }
        buffGraph.Reset();  // 重置图状态
        self.buffCache[buffId].Push(buffGraph);
    }
    
    // 从缓存池取出
    public static BuffGraph TryGetBuff(this BuffCacheComponent self, int buffId)
    {
        if (self.buffCache.TryGetValue(buffId, out var stack))
        {
            if (stack.TryPop(out var graph))
            {
                return graph;
            }
        }
        return null;
    }
}
```

对象池的核心思路：
- `SetBuffIntoCache`：Buff 移除时，不销毁图对象，而是重置状态后放入池子
- `TryGetBuff`：添加新 Buff 时，先从池子取，取不到才反序列化新建

战斗中频繁添加/移除同类型 Buff（如命中时触发的短暂减速 Buff），对象池可以极大减少 GC 压力。

---

## 被动技能附着的 Buff 管理

被动技能（PassiveSkill）添加的 Buff 需要整批管理：

```csharp
// 移除某个被动技能添加的所有 Buff
public static void RemoveAllBuffByAttachmentImmediately(this BuffComponent self, PassiveSkillInstance addBy)
{
    self.buffs2.Clear();
    self.buffs2.AddRange(self.buffs);  // 用副本迭代，避免迭代中修改
    foreach (var buff in self.buffs2)
    {
        if (buff.ownerSkill == addBy)
        {
            self.RemoveBuffImmediately(buff);
        }
    }
}
```

当被动技能失效（如换了装备、角色死亡）时，调用此方法一次性清除该被动技能添加的所有 Buff。`buff.ownerSkill` 记录了"谁添加的"，实现了精确的批量管理。

---

## Buff 与数值系统的协作

Buff 通过 NumericComponent 的修改器系统修改属性：

```csharp
// 典型 Buff 图节点的行为（伪代码）
// Enter 事件时：
var handle = numeric.ModifyPart(ENumericId.Atk, ENumericPart.Add, 100, self);
// 存储 handle 到黑板

// Exit 事件时（Buff 结束）：
numeric.RestorePart(ENumericId.Atk, ENumericPart.Add, savedHandle);
```

Buff 图中的节点（如 `BN_AddNumeric`）在进入时添加修改器、退出时移除修改器，保证了属性加成的完整生命周期管理。

---

## 多种 Buff 架构模式

### 持续型 Buff
- 进入时添加数值修改器
- 保持运行状态
- 退出时移除修改器

### 计时型 Buff
- 进入时设置计时器（黑板变量）
- 每帧更新计时
- 时间到 → 结束图（自动触发 Finalize）

### 触发型 Buff
- 进入时注册事件监听
- 收到事件（如受到攻击）时执行特定逻辑
- 退出时注销事件监听

### 堆叠型 Buff
- 通过黑板变量记录层数
- 每次 `AddBuff` 时增加一层（或重新开始计时）
- 达到特定层数触发效果

---

## 事件驱动的 Buff 状态通知

```csharp
// Buff 被添加时的事件
self.m_owner.GetComponent<EventDispatcherComponent>().FireEvent(new Evt_OnAddBuff()
{
    BuffId = id,
    Level = level,
    Source = addedby
});

// Buff 移除时的事件（内部实现）
self.m_owner.GetComponent<EventDispatcherComponent>().FireEvent(new BuffComponent.BuffEventInfo
{
    Type = BuffComponent.EBuffEventType.Exit,
    Buff = buff
});
```

这些事件让 UI 系统、成就系统、AI 系统等可以非侵入地响应 Buff 变化，无需修改 BuffComponent 本身。

---

## 常见 Buff 设计的代码模式

### 攻击力持续加成 Buff

```
[StartGraph]
  → [AddNumericModifier: Atk +100] → 存储 handle
  → [WaitForever]  // 持续存在，直到外部移除

[StopGraph] (Buff 被移除时触发)
  → [RemoveNumericModifier: handle]
```

### 计时 Buff（5秒加速）

```
[StartGraph]
  → [AddNumericModifier: MoveSpeed +50%] → 存储 handle  
  → [Wait: 5秒]
  → [RemoveNumericModifier: handle]
  → [StopGraph: success]
```

### 触发 Buff（受击时有概率格挡）

```
[StartGraph]
  → [RegisterEventListener: OnReceiveAttack]
  → [WaitForever]

[OnReceiveAttack Event]
  → [RandCheck: 30%]
    ├── [True] → [TriggerParry]
    └── [False] → [Continue]
```

---

## 性能与正确性保证

**① 迭代安全性**

```csharp
public static void RemoveAllBuffImmediately(this BuffComponent self)
{
    self.buffs2.Clear();
    self.buffs2.AddRange(self.buffs);  // 复制列表
    foreach (var buff in self.buffs2)  // 迭代复本
    {
        self.RemoveBuffImmediately(buff);  // 修改原列表
    }
}
```

移除所有 Buff 时，先复制列表再迭代，避免"迭代中修改列表"的异常。

**② 对象池减少 GC**

Buff 图通过 `BuffCacheComponent` 缓存，避免频繁的序列化/反序列化。

**③ 直接移除而非延迟队列**

注意到原代码中有注释掉的延迟队列代码（`m_toAddBuffs`），最终选择了直接操作（`AddBuffImmediately`）。这是因为延迟处理会导致 Buff 效果有一帧延迟，在帧同步战斗中可能影响一致性。

---

## 总结

| 特性 | 实现方式 |
|------|---------|
| 行为配置化 | FlowGraph 图驱动，策划配置 |
| 参数化 | 黑板变量 + BParamUtility |
| 对象池 | BuffCacheComponent |
| 精确来源追踪 | ownerSkill 引用 |
| 属性修改可撤销 | ModifierHandle 句柄 |
| 事件通知 | EventDispatcherComponent |
| 迭代安全 | 复制列表后迭代 |

Buff 系统设计的精髓在于：**将"做什么"（FlowGraph）和"对谁做"（SimpleBuff + BuffComponent）分离**。策划可以自由设计 Buff 的行为逻辑，程序提供基础设施，两者通过配置表衔接，实现了真正的"数据驱动"架构。
