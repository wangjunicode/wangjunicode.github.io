---
title: 帧更新系统三兄弟——Update、FixedUpdate 与 LateUpdate 的差异与应用
published: 2026-03-31
description: 深入解析 ECS 框架中三种帧更新系统的设计原理，理解 InstanceQueueIndex 调度机制，掌握何时用哪种更新系统以及帧同步场景下的最佳实践。
tags: [Unity, ECS, 更新循环, 帧同步, 调度机制]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 帧更新系统三兄弟——Update、FixedUpdate 与 LateUpdate 的差异与应用

## 前言

每个 Unity 开发者都知道 `Update()`、`FixedUpdate()`、`LateUpdate()`。

但在 ECS 框架中，这三种更新方式有完全不同的实现机制，而且还多了 `LateFixedUpdate`——一个 Unity 原生并没有的更新阶段。

今天我们来深入分析这套帧更新系统，理解它的设计思路和实际应用场景。

---

## 一、统一的接口模式

三种更新系统的代码结构几乎相同，我们先看最简单的 `IUpdateSystem`：

```csharp
public interface IUpdate {}

public interface IUpdateSystem: ISystemType
{
    void Run(Entity o);
}

[ObjectSystem]
[EntitySystem]
public abstract class UpdateSystem<T> : IUpdateSystem where T: Entity, IUpdate
{
    void IUpdateSystem.Run(Entity o)
    {
#if ONLY_CLIENT
        using var _ = ProfilingMarker.Update<T>.Marker.Auto();
#endif
        this.Update((T)o);
    }

    Type ISystemType.Type() => typeof(T);
    Type ISystemType.SystemType() => typeof(IUpdateSystem);
    InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.Update;

    protected abstract void Update(T self);
}
```

模式一目了然：
1. 空接口 `IUpdate` 标记实体"需要每帧更新"
2. `IUpdateSystem` 定义系统方法签名
3. `UpdateSystem<T>` 提供模板，子类只需实现 `Update(T self)`
4. `GetInstanceQueueIndex()` 返回 `InstanceQueueIndex.Update`——这是调度的关键

---

## 二、InstanceQueueIndex——更新队列的标识

```csharp
public enum InstanceQueueIndex
{
    None = -1,
    Start,         // 0
    Update,        // 1
    LateUpdate,    // 2
    Load,          // 3
    FixedUpdate,   // 4
    LateFixedUpdate, // 5
    Physics,       // 6
    Reset,         // 7
    Max,           // 8
}
```

每个索引对应 `EventSystem` 中的一个 `Queue<long>`。

实体注册时（`RegisterSystem`），框架检查该实体类型有哪些系统，并把实体 ID 加入对应的队列：

```csharp
// EventSystem.RegisterSystem 中
for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
{
    if (!oneTypeSystems.QueueFlag[i])
    {
        continue;
    }
    this.queues[i].Enqueue(component.InstanceId);
}
```

**`QueueFlag` 数组**：每个系统的 `GetInstanceQueueIndex()` 结果预先存在 `QueueFlag` 中。注册实体时，只需遍历这个布尔数组，O(n) 时间（n 为队列数量，最多 8 个），非常高效。

---

## 三、三种更新系统的对比

### 3.1 Update——普通帧更新

```csharp
InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.Update;
```

每个渲染帧调用一次（对应 Unity 的 `Update`）。

**适用场景**：
- UI 状态更新
- 动画逻辑
- 非物理的移动（基于 `Time.deltaTime`）
- 输入处理

**注意**：由于渲染帧率不稳定（可能是 30fps、60fps、144fps 或更低），`Update` 的调用间隔不固定。逻辑应该用 `deltaTime` 来保证帧率无关性。

### 3.2 FixedUpdate——固定帧更新

```csharp
InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.FixedUpdate;
```

以固定间隔调用（对应 Unity 的 `FixedUpdate`）。

**适用场景**：
- 物理模拟
- 帧同步逻辑（本项目的主要用途）
- 需要确定性的计算
- 网络同步相关的逻辑

**为什么帧同步要用 FixedUpdate？**

帧同步要求所有客户端以相同的逻辑步进顺序推进游戏状态。`FixedUpdate` 以固定时间间隔（如 `EngineDefine.fixedDeltaTime_Orignal`）调用，无论渲染帧率如何变化，逻辑帧都以相同的频率推进。

### 3.3 LateUpdate——延后帧更新

```csharp
InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.LateUpdate;
```

在普通 Update 完成后调用（对应 Unity 的 `LateUpdate`）。

**适用场景**：
- 摄像机跟随（在角色 Update 移动之后，摄像机再更新位置）
- 需要在其他所有 Update 完成后才能计算的逻辑
- 最终渲染前的修正

### 3.4 LateFixedUpdate——新增的延后固定帧

```csharp
public interface ILateFixedUpdate {}

[ObjectSystem]
[EntitySystem]
public abstract class LateFixedUpdateSystem<T> : ILateFixedUpdateSystem where T: Entity, ILateFixedUpdate
{
    public void LateRun(Entity o) { this.LateFixedUpdate((T)o); }
    InstanceQueueIndex GetInstanceQueueIndex() => InstanceQueueIndex.LateFixedUpdate;
    protected virtual void LateFixedUpdate(T self) {} // virtual，有默认空实现
}
```

这是 Unity 原生没有的阶段，框架自己添加的。

注意 `LateFixedUpdate` 方法是 `virtual`（不是 `abstract`），有默认空实现。这意味着子类可以不覆写它——因为很多系统可能只需要 `FixedUpdate`，`LateFixedUpdate` 是可选的。

**适用场景**：
- 在物理/逻辑帧计算后，做最终的状态同步
- 类似"每帧的后处理"，但在逻辑帧上

---

## 四、EventSystem 中的更新驱动

在 `EventSystem` 中可以看到这些队列是如何被驱动的：

```csharp
// 在 FixedUpdate 阶段
public void FixedUpdate()
{
    Start(); // 先处理待 Start 的实体
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.FixedUpdate];
    int count = queue.Count;
    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        // 检查实体是否还存在
        if (!this.allEntities.TryGetValue(instanceId, out Entity component)) continue;
        if (component.IsDisposed) continue;

        List<object> iUpdateSystems = this.typeSystems.GetSystems(component.GetType(), typeof(IFixedUpdateSystem));
        if (iUpdateSystems == null) continue;

        queue.Enqueue(instanceId); // 重新入队，下次继续处理

        foreach (IFixedUpdateSystem iUpdateSystem in iUpdateSystems)
        {
            iUpdateSystem.Run(component);
        }
    }
}
```

**关键设计：先获取数量，再处理**

```csharp
int count = queue.Count;
while (count-- > 0)
```

这里先取 `queue.Count`，然后只处理这些已有的元素。为什么？

因为在处理过程中，系统可能创建新的实体（这些实体也实现了 `IFixedUpdate`）。新实体被 `RegisterSystem` 后会加入队列。

如果不先固定 count，可能陷入"处理 → 创建新实体 → 继续处理 → 创建更多 → ..."的无限循环。

先固定 count，本帧只处理已有的实体，新增的留到下一帧。

**`queue.Enqueue(instanceId)` ——循环队列**

处理完后把 ID 重新放回队列，形成循环。这样实体只需要注册一次，就会在每一帧都被处理。

与 `Awake` 的不同：Awake 处理完不重新入队（只触发一次），Update 处理完后重新入队（每帧触发）。

---

## 五、IsDisposed 检查的重要性

```csharp
if (component.IsDisposed)
{
    continue; // 跳过已销毁的实体
}
```

在大型游戏中，每帧都有实体被创建和销毁。当一个实体被销毁时，它的 InstanceId 可能还在队列中（因为队列是先进先出，清理不是即时的）。

`IsDisposed` 检查确保我们不会对已销毁的实体执行更新逻辑。

这是防御性编程的典型应用：即使队列中有"脏"数据，也能安全处理。

---

## 六、BeforeFixedUpdate——Update 之前的特殊阶段

```csharp
public void BeforeFixedUpdate()
{
    Start();
    // 处理 Physics 队列
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Physics];
    // ... 收集物理相关实体
}
```

`BeforeFixedUpdate` 在所有 `FixedUpdate` 之前调用：
1. 先处理待 `Start` 的实体
2. 收集需要物理计算的实体

这体现了游戏帧循环的精细控制：不同的逻辑在帧内不同时刻执行，确保依赖关系正确。

---

## 七、实际使用示例

```csharp
// 一个同时需要 FixedUpdate 和 LateFixedUpdate 的组件
public class MovementComponent: Entity, IFixedUpdate, ILateFixedUpdate
{
    public Vector3 Position;
    public Vector3 Velocity;
    public Vector3 RenderedPosition; // 插值渲染位置
}

[ObjectSystem]
public class MovementFixedUpdateSystem: FixedUpdateSystem<MovementComponent>
{
    protected override void FixedUpdate(MovementComponent self)
    {
        // 物理帧：更新逻辑位置
        self.Position += self.Velocity * EngineDefine.fixedDeltaTime;
    }
}

[ObjectSystem]
public class MovementLateFixedUpdateSystem: LateFixedUpdateSystem<MovementComponent>
{
    protected override void LateFixedUpdate(MovementComponent self)
    {
        // 物理帧后：计算渲染插值
        self.RenderedPosition = Vector3.Lerp(self.RenderedPosition, self.Position, 0.5f);
    }
}
```

---

## 八、选择更新类型的决策树

```
需要每帧更新？
├── 是否需要确定性/帧同步？
│   ├── 是 → FixedUpdate
│   └── 否 → 是否需要在其他 Update 之后执行？
│              ├── 是 → LateUpdate
│              └── 否 → Update
└── 是否是物理帧后的处理？
    └── 是 → LateFixedUpdate
```

**经验规则**：
- 游戏逻辑（战斗、技能、移动计算）→ `FixedUpdate`
- UI、摄像机、视觉效果 → `Update` / `LateUpdate`
- 物理帧后的状态同步 → `LateFixedUpdate`

---

## 九、写给初学者

理解这套更新系统，关键是理解两个维度：

**维度1：时机**
- Update/LateUpdate：渲染帧，频率随设备性能变化
- FixedUpdate/LateFixedUpdate：逻辑帧，固定频率

**维度2：顺序**
- Update < LateUpdate（普通帧内）
- FixedUpdate < LateFixedUpdate（物理帧内）

选错了更新类型，会导致画面抖动（用 Update 做物理）、逻辑不同步（用 LateUpdate 做帧同步逻辑）等问题。

理解每种更新类型的语义，是写出正确游戏逻辑的基础。
