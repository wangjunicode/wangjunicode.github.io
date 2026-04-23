---
title: 可视化脚本接口体系 ScriptInterfaces 设计解析——从泛型脚本到黑板事件的契约层架构
published: 2026-04-23
description: 深入解析游戏框架中 ScriptInterfaces.cs 定义的一组可视化脚本接口：IGenericScript、IGenericEvtScript、IBlackboardGenericScript 等接口的设计意图、层次关系，以及它们如何作为战斗逻辑与可视化脚本系统之间的"契约层"发挥作用。
tags: [Unity, 游戏框架, 可视化脚本, 战斗系统, 架构设计]
category: 游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在复杂的游戏战斗框架中，战斗逻辑的可扩展性与可维护性是永恒的挑战。`ScriptInterfaces.cs` 定义了一组精心设计的空接口，它们是可视化脚本系统（UniScript）与底层 ECS 框架之间的**契约层**——用接口类型约束而非实现耦合，实现了战斗逻辑的可视化编辑与代码解耦。

---

## 一、完整接口定义

```csharp
namespace VGame.Framework
{
    // 用于泛型脚本 handler 实例化
    public interface IGenericEvtScriptHandler { }
    
    // 用于 blackboard 泛型脚本 handler 实例化
    public interface IBlackboardGenericScriptHandler { }
    
    // 黑板泛型脚本
    public interface IBlackboardGenericScript { }

    // 用于序列化泛型脚本
    public interface IGenericScript { }

    // 事件泛型脚本
    public interface IGenericEvtScript { }

    // 用于脚本序列化的事件参数
    public interface IScriptEventArg { }
    
    public interface IScriptNeedCheckEvent
    {
        public bool check(IScriptNeedCheckEvent other);
    }
    
    public interface IPassiveEventArg : IScriptEventArg { }
    
    // 返回实际进度结果
    public interface IProgressScript
    {
        public string GetProgress();
    }
}
```

---

## 二、接口分组与职责分析

这 9 个接口可以按职责分为三组：

```
ScriptInterfaces
├── 脚本实体接口（标记型）
│   ├── IGenericScript          —— 可序列化的泛型脚本
│   ├── IGenericEvtScript       —— 事件驱动的泛型脚本  
│   └── IBlackboardGenericScript —— 基于黑板的泛型脚本
│
├── Handler 接口（标记型）
│   ├── IGenericEvtScriptHandler      —— 事件脚本 handler
│   └── IBlackboardGenericScriptHandler —— 黑板脚本 handler
│
└── 功能接口（有方法）
    ├── IScriptEventArg         —— 脚本事件参数基接口
    ├── IPassiveEventArg        —— 被动技能事件参数（继承自 IScriptEventArg）
    ├── IScriptNeedCheckEvent   —— 需要校验的事件（含 check 方法）
    └── IProgressScript         —— 进度查询接口
```

---

## 三、标记接口的设计哲学

### 3.1 为什么用空接口？

标记接口（Marker Interface）是一种经典模式，其价值在于**类型约束**而非行为定义：

```csharp
// 反射注册时，扫描实现了 IGenericScript 的所有类
var scriptTypes = AppDomain.CurrentDomain.GetAssemblies()
    .SelectMany(a => a.GetTypes())
    .Where(t => typeof(IGenericScript).IsAssignableFrom(t) && !t.IsInterface)
    .ToList();
```

相比 Attribute 标记，接口约束可以：
- 在编译期被 IDE 感知（自动补全、跳转）
- 参与泛型约束 `where T : IGenericScript`
- 被 Analyzer 静态分析工具检查

### 3.2 三类脚本的区别

| 接口 | 语义 | 典型场景 |
|---|---|---|
| `IGenericScript` | 基础可序列化脚本 | 技能效果节点、条件判断 |
| `IGenericEvtScript` | 事件响应脚本 | 监听战斗事件、触发连锁效果 |
| `IBlackboardGenericScript` | 依赖黑板数据的脚本 | AI 行为树节点、状态条件 |

**黑板（Blackboard）** 是 AI 和可视化脚本中的共享数据存储区，类似于 ECS 中的全局组件：

```
战斗黑板:
  ├── 当前目标 target
  ├── 生命值百分比 hpRatio  
  ├── 技能冷却状态 skillCooldowns
  └── 战场局势 battleState

IBlackboardGenericScript 节点可以读写这些数据
IGenericEvtScript 节点响应事件时不直接访问黑板
```

---

## 四、Handler 层的双重接口

Handler 是脚本系统的执行器，有两个标记接口分别对应两类脚本：

```csharp
// 事件脚本 handler：处理 IGenericEvtScript 实例
public class DamageEventScriptHandler : IGenericEvtScriptHandler
{
    // 当某个 IGenericEvtScript 触发时执行
    public void Execute(IGenericEvtScript script, IScriptEventArg arg)
    {
        // 处理伤害事件脚本逻辑
    }
}

// 黑板脚本 handler：处理 IBlackboardGenericScript 实例  
public class AIBehaviorScriptHandler : IBlackboardGenericScriptHandler
{
    public void Execute(IBlackboardGenericScript script, Blackboard board)
    {
        // 基于黑板数据执行 AI 行为
    }
}
```

这种分离体现了**单一职责原则**：事件驱动的脚本和黑板驱动的脚本在运行时走不同的执行路径。

---

## 五、事件参数的继承体系

```
IScriptEventArg（基础标记）
└── IPassiveEventArg（被动技能事件参数）

IScriptNeedCheckEvent（需要校验的特殊事件）
```

### 5.1 IScriptEventArg

所有脚本事件参数的基接口，使框架可以统一处理任意类型的事件参数：

```csharp
// 统一的脚本事件分发
void DispatchScriptEvent(IGenericEvtScript script, IScriptEventArg arg)
{
    // 根据 arg 的具体类型分发到对应 handler
    switch (arg)
    {
        case IPassiveEventArg passive:
            HandlePassiveEvent(script, passive);
            break;
        default:
            HandleGenericEvent(script, arg);
            break;
    }
}
```

### 5.2 IPassiveEventArg — 被动技能的专属参数

`IPassiveEventArg` 继承自 `IScriptEventArg`，专门用于被动技能触发时携带的参数。被动技能（Passive Skill）的触发往往需要携带触发者、触发条件等额外上下文：

```csharp
public class OnHitPassiveArg : IPassiveEventArg
{
    public Unit attacker;
    public Unit target;
    public float damageDealt;
    public bool isCritical;
}
```

### 5.3 IScriptNeedCheckEvent — 有校验逻辑的事件

这是最有趣的接口，它带有一个 `check` 方法：

```csharp
public interface IScriptNeedCheckEvent
{
    public bool check(IScriptNeedCheckEvent other);
}
```

其语义是：**判断两个事件是否"匹配"**，用于事件过滤和精准触发：

```csharp
// 示例：只有当攻击目标类型匹配时才触发被动
public class AttackTypeCheckEvent : IScriptNeedCheckEvent
{
    public UnitType requiredType;
    
    public bool check(IScriptNeedCheckEvent other)
    {
        if (other is AttackTypeCheckEvent otherEvt)
        {
            return otherEvt.requiredType == this.requiredType;
        }
        return false;
    }
}
```

这种设计避免了大量 if/else 的事件类型判断，让每种事件自己负责匹配逻辑——**多态替代条件分支**。

---

## 六、IProgressScript — 进度查询

```csharp
public interface IProgressScript
{
    public string GetProgress();
}
```

实现此接口的脚本可以向外暴露进度信息，常用于：
- 任务/成就的完成进度（"已击杀 3/10 只怪物"）
- 技能充能状态（"充能进度 60%"）
- 活动关卡的推进情况

通过统一接口，UI 层可以用同一套代码展示任意类型的进度：

```csharp
void RefreshProgressUI(IProgressScript script)
{
    progressText.text = script.GetProgress(); // 调用方无需知道具体实现
}
```

---

## 七、整体架构视图

```
可视化脚本编辑器（UniScript）
        │
        │ 序列化/反序列化
        ▼
  脚本数据层 (IGenericScript / IGenericEvtScript / IBlackboardGenericScript)
        │
        │ 运行时实例化
        ▼
  Handler 执行层 (IGenericEvtScriptHandler / IBlackboardGenericScriptHandler)
        │
        │ 事件参数传递
        ▼
  事件参数层 (IScriptEventArg → IPassiveEventArg, IScriptNeedCheckEvent)
        │
        ▼
  战斗 ECS 系统（Entity / Component / System）
```

---

## 八、总结

`ScriptInterfaces.cs` 虽然只有不到 50 行代码，却承载了战斗可视化脚本系统的全部类型契约：

1. **标记接口**（`IGenericScript` 系列）通过类型约束替代 Attribute，支持泛型、静态分析和反射注册
2. **Handler 双轨**（事件 vs 黑板）体现了不同脚本执行路径的职责分离
3. **事件参数继承**（`IPassiveEventArg`）为被动技能提供了专属类型通道
4. **自校验事件**（`IScriptNeedCheckEvent`）用多态消除了条件分支，让事件匹配逻辑内聚到事件本身
5. **进度接口**（`IProgressScript`）为 UI 层提供了统一的查询协议

这是一个用接口定义语言来描述系统边界的典型范例，值得在自研框架设计中借鉴。
