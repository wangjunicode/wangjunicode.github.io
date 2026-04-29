---
title: xgame框架Scene实体深度解析-自管理Domain与双构造模式及子场景树的完整设计
published: 2026-04-29
description: 深入剖析xgame框架中Scene实体的源码设计，分析Scene作为ECS世界根节点的特殊地位——自管理Domain、覆盖Parent赋值、双构造器支持序列化恢复，以及SceneType枚举与位运算标志机制在多场景管理中的应用。
tags: [Unity, xgame, ECS, Scene, 游戏框架, 架构设计]
category: 游戏框架
draft: false
encryptedKey: henhaoji123
---

## 前言

在 xgame 框架的 ECS 体系中，`Entity` 是一切对象的基类，而 `Scene` 是对 `Entity` 的特化——它不仅是普通实体，更是其他实体的**容器与根节点**。每个游戏世界、每个系统域，都以一个 `Scene` 实例为起点。

本文将从源码出发，深度分析 `Scene`、`SceneType` 的设计细节，揭示其作为 ECS 世界根节点的特殊机制。

---

## 一、Scene 类的整体结构

```csharp
[EnableMethod]
[DebuggerDisplay("ViewName,nq")]
[ChildOf]
public sealed class Scene : Entity, IDestroy
{
    public int Zone { get; }
    public SceneType SceneType { get; }
    public string Name { get; set; }

    public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent) { ... }
    public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent) { ... }

    public Scene Get(long id) { ... }

    public new Entity Domain { get => this.domain; set => this.domain = value; }
    public new Entity Parent { get { ... } set { ... } }

    protected override string ViewName => $"{this.GetType().Name} ({this.SceneType})";
}
```

### 关键设计要点一览

| 特性 | 说明 |
|------|------|
| `sealed` | 不允许继承，保证 Scene 行为的确定性 |
| `[ChildOf]` | 无参数，表示可以挂在任意 Entity 下 |
| `[EnableMethod]` | 允许框架反射调用其扩展方法 |
| 实现 `IDestroy` | 拥有销毁回调，在日志中打印场景信息 |
| 覆盖 `Domain` 和 `Parent` | 自管理 Domain，覆盖 Parent 的默认赋值逻辑 |

---

## 二、双构造器：普通创建 vs 序列化恢复

`Scene` 提供了两个构造器，对应两种不同的创建场景。

### 2.1 单 ID 构造器（运行时创建）

```csharp
public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = instanceId;
    this.InstanceId = instanceId;
    this.Zone = zone;
    this.SceneType = sceneType;
    this.Name = name;
    this.IsCreated = true;
    this.IsNew = true;
    this.Parent = parent;
    this.Domain = this;
    this.IsRegister = true;
}
```

**特点**：`Id` 与 `InstanceId` 相同，都使用 `instanceId`。这是**全新创建**的场景，在客户端运行时最常见。

- `IsCreated = true`：标记对象已被创建
- `IsNew = true`：标记为新对象（区别于从存档恢复的对象）
- `Domain = this`：**Scene 将自身设为自己的 Domain**，这是核心设计之一
- `IsRegister = true`：立即注册到 ECS 系统，触发事件系统的 Awake 流程

### 2.2 双 ID 构造器（序列化恢复）

```csharp
public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = id;
    this.InstanceId = instanceId;
    // ... 其余与第一个构造器相同
}
```

**特点**：`Id` 与 `InstanceId` 不同。用于**从存档或服务端数据恢复**场景时，需要保持原始的稳定 `Id`（数据库主键），同时分配新的运行时 `InstanceId`。

这种设计在 MMO 或需要持久化场景状态的游戏中非常关键：重进游戏时，逻辑 `Id` 不变，但运行时 `InstanceId` 随每次加载刷新，防止旧引用意外命中新对象。

---

## 三、自管理 Domain——最核心的设计

### 3.1 Domain 的含义

在 xgame ECS 中，`Domain` 表示一个实体归属于哪个"逻辑域"。同一个 Domain 下的 Entity 共享资源池、事件注册范围等。

普通 Entity 的 Domain 由其父节点传递而来，但 `Scene` 覆盖了 `Domain` 属性：

```csharp
public new Entity Domain
{
    get => this.domain;
    set => this.domain = value;
}
```

并在构造时执行：

```csharp
this.Domain = this;
```

**Scene 将自身设为自己的 Domain**。这意味着：

- 挂载在 Scene 下的所有 Entity，其 Domain 指向这个 Scene
- Scene 是 Domain 树的"天花板"，不再向上追溯
- 多个 Scene 可以是相互隔离的独立 Domain

这种设计是 ECS 多场景隔离的基础：不同 Scene 下的实体不会共享 Domain，事件分发、对象池等都可以按 Domain 隔离。

### 3.2 覆盖 Parent 赋值

```csharp
public new Entity Parent
{
    get => this.parent;
    set
    {
        if (value == null)
        {
            return;  // null 直接忽略，不赋值
        }
        this.parent = value;
        this.parent.Children.Add(this.Id, this);  // 主动注册到父节点 Children
    }
}
```

普通 Entity 的 Parent 赋值通常包含更复杂的 Domain 传播逻辑，但 `Scene` 因为 Domain 是自己，所以覆盖了这套逻辑：

1. 忽略 `null` 父节点赋值（根场景没有父节点，不需要处理）
2. 直接把自己加入父节点的 `Children` 字典

这样 Scene 可以作为子场景挂在另一个 Scene 下，形成场景树，同时又各自维护独立的 Domain。

---

## 四、子场景树：Scene.Get(long id)

```csharp
public Scene Get(long id)
{
    if (this.Children == null)
    {
        return null;
    }
    if (!this.Children.TryGetValue(id, out Entity entity))
    {
        return null;
    }
    return entity as Scene;
}
```

`Get` 方法从当前 Scene 的直接子节点中查找指定 `id` 的 Scene。这是**一层查找**，不递归。

典型用法：

```csharp
// 根场景挂着多个子场景
Scene clientScene = Root.Instance.Get(clientSceneId);
Scene battleScene = Root.Instance.Get(battleSceneId);
```

子场景的生命周期由父场景管理，父场景销毁时，子场景也会随之销毁（通过 ECS 的实体树递归销毁机制）。

---

## 五、Destroy 系统——日志打点

```csharp
[EntitySystem]
private static void Destroy(this Scene self)
{
    Log.Info($"scene dispose: {self.SceneType} {self.Name} {self.Id} {self.InstanceId} {self.Zone}");
}
```

场景销毁时打印一条包含完整信息的日志：类型、名称、Id、InstanceId、Zone。这为线上问题排查提供了清晰的生命周期追踪链路——从创建时的 `scene create:...` 到销毁时的 `scene dispose:...`，完整记录了一个 Scene 的一生。

---

## 六、ViewName 调试支持

```csharp
protected override string ViewName => $"{this.GetType().Name} ({this.SceneType})";
```

配合 `[DebuggerDisplay("ViewName,nq")]`，在 IDE 调试器中查看 Scene 对象时，会显示形如 `Scene (Client)` 的友好名称，而不是默认的类型全名。这对大型项目中管理多个 Scene 实例非常实用。

---

## 七、SceneType 枚举与位运算扩展

```csharp
public enum SceneType
{
    None    = -1,
    Process = 0,
    Client  = 1,
    Current = 2
}

public static class SceneTypeHelper
{
    public static bool HasSameFlag(this SceneType a, SceneType b)
    {
        if (((ulong)a & (ulong)b) == 0)
        {
            return false;
        }
        return true;
    }
}
```

### 7.1 三种核心场景类型

| 值 | 名称 | 含义 |
|----|------|------|
| -1 | None | 无效/未初始化场景 |
| 0 | Process | 进程级场景，整个进程唯一，挂载全局单例组件 |
| 1 | Client | 客户端主场景，玩家会话的顶层容器 |
| 2 | Current | 当前活跃场景，通常指玩家当前所在的游戏场景 |

### 7.2 HasSameFlag 位运算检查

`HasSameFlag` 将枚举值转换为 `ulong` 后做按位与操作，用于检查两个场景类型是否存在**标志位重叠**。

```csharp
SceneType a = SceneType.Client;   // 1 = 0b01
SceneType b = SceneType.Current;  // 2 = 0b10
a.HasSameFlag(b)  // 0b01 & 0b10 = 0 → false，无重叠

SceneType c = (SceneType)3;  // 0b11，同时拥有 Client 和 Current 标志
c.HasSameFlag(SceneType.Client)   // 0b11 & 0b01 = 1 → true
c.HasSameFlag(SceneType.Current)  // 0b11 & 0b10 = 2 → true
```

这种设计允许通过组合枚举值来表达"多重场景类型"，适用于需要在多个上下文中共享的特殊场景。

---

## 八、Scene 的典型使用模式

### 8.1 进程启动时创建根 Process 场景

```csharp
// 框架初始化时
var processScene = new Scene(
    instanceId: IdGenerater.Instance.GenerateInstanceId(),
    zone: 0,
    sceneType: SceneType.Process,
    name: "Process",
    parent: null  // 进程场景无父节点
);
// 此时 Domain = processScene 自身
```

### 8.2 玩家登录后创建 Client 场景

```csharp
var clientScene = new Scene(
    instanceId: IdGenerater.Instance.GenerateInstanceId(),
    zone: playerId,
    sceneType: SceneType.Client,
    name: "Client",
    parent: processScene  // 挂在进程场景下
);
// clientScene 自管理 Domain，与 processScene 隔离
```

### 8.3 进入战斗创建 Current 场景

```csharp
var battleScene = new Scene(
    instanceId: IdGenerater.Instance.GenerateInstanceId(),
    zone: playerId,
    sceneType: SceneType.Current,
    name: "Battle",
    parent: clientScene  // 挂在客户端场景下
);
// battleScene 独立 Domain，战斗实体与大厅实体隔离
```

---

## 九、设计总结

`Scene` 在 xgame ECS 中扮演着"世界根节点"的角色，其设计有几个核心原则：

1. **Domain 自治**：Scene 是自己的 Domain，形成天然的系统隔离边界
2. **Parent 受控**：覆盖 Parent 赋值，主动管理子节点注册，不依赖基类的 Domain 传播逻辑
3. **双构造器**：区分"全新创建"与"序列化恢复"两种场景，Id 与 InstanceId 的分离设计保障了持久化场景的正确性
4. **树形组织**：Scene 可以作为子节点挂在另一个 Scene 下，通过 `Get(id)` 查询子场景，构建层次化的场景管理结构
5. **类型枚举 + 位运算**：`SceneType` 支持组合标志，灵活表达多场景上下文
6. **调试友好**：`DebuggerDisplay` + `ViewName` 确保在 IDE 中快速识别场景实例

理解 Scene 的这些设计，是深入理解 xgame ECS 实体树与 Domain 机制的关键一步。
