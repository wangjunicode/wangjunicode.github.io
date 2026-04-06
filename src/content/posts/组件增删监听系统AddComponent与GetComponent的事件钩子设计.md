---
title: 组件增删监听系统——AddComponent 与 GetComponent 的事件钩子设计
published: 2026-03-31
description: 深入解析 IAddComponentSystem 和 IGetComponentSystem 的设计，理解组件操作拦截机制，以及 GetComponent 钩子如何实现智能脏数据追踪的优化方案。
tags: [Unity, ECS, 组件系统, 优化, 设计模式]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 组件增删监听系统——AddComponent 与 GetComponent 的事件钩子设计

## 前言

在 ECS 框架中，实体的组件是动态添加和获取的。但有时候，我们希望在"某个组件被添加到实体上"或"某个组件被访问时"触发额外逻辑。

这就是 `IAddComponentSystem` 和 `IGetComponentSystem` 的用武之地——它们是组件操作的"拦截钩子"。

注意 `IGetComponentSystem` 文件里有一段非常有价值的注释，揭示了它的设计意图：

```csharp
// GetComponentSystem有巨大作用，比如每次保存Unit的数据不需要所有组件都保存，只需要保存Unit变化过的组件
// 是否变化可以通过判断该组件是否GetComponent，Get了就记录该组件
// 这样可以只保存Unit变化过的组件
// 再比如传送也可以做此类优化
```

这段注释透露了一个精妙的性能优化设计思路，我们来深入分析。

---

## 一、IAddComponentSystem——组件被添加时的通知

```csharp
public interface IAddComponent {}

public interface IAddComponentSystem: ISystemType
{
    void Run(Entity o, Entity component);
}

[ObjectSystem]
public abstract class AddComponentSystem<T> : IAddComponentSystem where T: Entity, IAddComponent
{
    void IAddComponentSystem.Run(Entity o, Entity component)
    {
        this.AddComponent((T)o, component);
    }

    Type ISystemType.SystemType() => typeof(IAddComponentSystem);
    InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.None;
    Type ISystemType.Type() => typeof(T);

    protected abstract void AddComponent(T self, Entity component);
}
```

### 1.1 Run 有两个参数

与 `AwakeSystem` 不同，`AddComponentSystem` 的 `Run` 方法接受两个参数：

- `o`：被添加了组件的实体（宿主）
- `component`：被添加的组件本身

这让钩子可以根据具体是哪个组件被添加来做不同处理：

```csharp
// 玩家实体，监听自身组件的变化
public class PlayerEntity: Entity, IAddComponent { }

[ObjectSystem]
public class PlayerAddComponentSystem: AddComponentSystem<PlayerEntity>
{
    protected override void AddComponent(PlayerEntity self, Entity component)
    {
        if (component is HealthComponent health)
        {
            Log.Info($"玩家 {self.Id} 添加了生命组件，初始血量: {health.Hp}");
        }
        else if (component is WeaponComponent weapon)
        {
            // 添加武器时，更新玩家的攻击力显示
            self.RefreshAttackDisplay();
        }
    }
}
```

### 1.2 InstanceQueueIndex.None

```csharp
InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.None;
```

`InstanceQueueIndex.None = -1`，意味着 `AddComponentSystem` **不会被加入任何更新队列**。

这是对的——添加组件是事件触发的（有组件添加时才调用），不是每帧循环调用的。

在 `EventSystem.RegisterSystem` 中：

```csharp
for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
{
    if (!oneTypeSystems.QueueFlag[i])
    {
        continue;
    }
    this.queues[i].Enqueue(component.InstanceId);
}
```

`QueueFlag[-1]` 超出范围不会被添加，实现了"不入队"的效果。

框架在调用 `AddComponent` 时直接调用 `EventSystem.AddComponent(entity, component)`，不经过队列。

---

## 二、IGetComponentSystem——访问组件时的通知

```csharp
public interface IGetComponent {}

public interface IGetComponentSystem: ISystemType
{
    void Run(Entity o, Entity component);
}

[ObjectSystem]
public abstract class GetComponentSystem<T> : IGetComponentSystem where T: Entity, IGetComponent
{
    void IGetComponentSystem.Run(Entity o, Entity component)
    {
        this.GetComponent((T)o, component);
    }

    Type ISystemType.SystemType() => typeof(IGetComponentSystem);
    InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.None;
    Type ISystemType.Type() => typeof(T);

    protected abstract void GetComponent(T self, Entity component);
}
```

`GetComponentSystem` 的结构与 `AddComponentSystem` 几乎完全一样——但它在"获取组件"时被触发。

---

## 三、注释揭示的精妙设计——脏数据追踪

注释中提到的优化思路值得深入探讨：

### 3.1 传统保存方案的问题

在多人游戏中，玩家单位（Unit）可能有数十个组件（生命值、技能、道具、状态等）。

传统的保存方案：

```csharp
// 玩家离线时，保存所有组件
void SaveUnit(Unit unit)
{
    SaveHealthComponent(unit.GetComponent<HealthComponent>());
    SaveSkillComponent(unit.GetComponent<SkillComponent>());
    SaveInventoryComponent(unit.GetComponent<InventoryComponent>());
    // ... 保存所有组件
}
```

问题：即使大部分组件没有变化（玩家在安全区待了一会儿），我们也保存了所有组件，浪费了大量 IO。

### 3.2 基于 GetComponent 的脏追踪

用 `GetComponentSystem` 可以这样实现：

```csharp
// 单元实体，监听组件被访问
public class UnitEntity: Entity, IGetComponent
{
    // 记录被修改过的组件
    public HashSet<Type> DirtyComponents = new HashSet<Type>();
}

[ObjectSystem]
public class UnitGetComponentSystem: GetComponentSystem<UnitEntity>
{
    protected override void GetComponent(UnitEntity self, Entity component)
    {
        // 当某个组件被 GetComponent 获取时，记录它"可能被修改了"
        self.DirtyComponents.Add(component.GetType());
    }
}

// 保存时只保存脏组件
void SaveUnit(UnitEntity unit)
{
    foreach (Type type in unit.DirtyComponents)
    {
        Entity component = unit.GetComponent(type);
        // 序列化并保存这个组件
        SaveComponent(component);
    }
    unit.DirtyComponents.Clear(); // 清除脏标记
}
```

核心思路：**谁被访问过，谁可能被修改了，只保存访问过的组件。**

这是一种"乐观假设"——假设访问就意味着修改。比"保守假设"（每次都全量保存）节省大量 IO，比"精确追踪"（只追踪实际写入的字段）实现更简单。

### 3.3 传送优化也类似

注释中提到"传送也可以做此类优化"。

玩家传送时，需要将玩家状态同步到新服务器（跨服玩法）。不需要同步所有组件，只需要同步"被访问过"的组件（因为访问意味着数据可能已经更新）。

---

## 四、两者的调用时机

在 `EventSystem` 中：

```csharp
// AddComponentSystem：在 entity.AddComponent 时被调用
public void AddComponent(Entity entity, Entity component)
{
    List<object> iAddSystem = this.typeSystems.GetSystems(entity.GetType(), typeof(IAddComponentSystem));
    if (iAddSystem == null) return;

    foreach (IAddComponentSystem addComponentSystem in iAddSystem)
    {
        addComponentSystem.Run(entity, component);
    }
}

// GetComponentSystem：在 entity.GetComponent 时被调用
public void GetComponent(Entity entity, Entity component)
{
    List<object> iGetSystem = this.typeSystems.GetSystems(entity.GetType(), typeof(IGetComponentSystem));
    if (iGetSystem == null) return;

    foreach (IGetComponentSystem getSystem in iGetSystem)
    {
        getSystem.Run(entity, component);
    }
}
```

---

## 五、注意事项——性能开销

`GetComponent` 在游戏运行时可能被非常频繁地调用（每帧多次，甚至每个实体每帧多次）。

如果你实现了 `GetComponentSystem`，需要注意：

1. **方法要轻量**：`GetComponent` 钩子里的代码会在每次 `GetComponent` 时执行，不要做耗时操作
2. **避免递归**：如果钩子里又调用了 `GetComponent`，会再次触发钩子，可能导致无限递归
3. **考虑必要性**：`IGetComponent` 只在真正需要追踪时才使用，不要给所有实体都加

---

## 六、完整对比

| 特性 | IAddComponentSystem | IGetComponentSystem |
|---|---|---|
| 触发时机 | `entity.AddComponent()` | `entity.GetComponent()` |
| 参数 | (宿主实体, 被加组件) | (宿主实体, 被访问组件) |
| 更新队列 | None（事件驱动） | None（事件驱动） |
| 典型用途 | 组件联动初始化 | 脏数据追踪 |
| 调用频率 | 组件变化时 | 可能非常频繁 |

---

## 七、写给初学者

这两个系统体现了 ECS 框架的一个核心理念：**让框架行为可被拦截和扩展，而不是在核心代码中写死所有逻辑。**

传统面向对象：

```csharp
// 在 AddComponent 方法里加 if-else
void AddComponent(Entity component)
{
    components.Add(component);
    if (this is Player p && component is WeaponComponent w)
    {
        p.RefreshAttack();
    }
    // ... 各种特殊逻辑
}
```

ECS 方式：

```csharp
// 框架核心代码保持干净
void AddComponent(Entity component) 
{
    components.Add(component);
    EventSystem.Instance.AddComponent(this, component); // 通知外部钩子
}

// 具体逻辑在各自的系统类里
class PlayerAddComponentSystem: AddComponentSystem<Player>
{
    protected override void AddComponent(Player self, Entity component) { ... }
}
```

核心代码稳定，扩展逻辑分散到各个系统——这就是开闭原则（对扩展开放，对修改关闭）在 ECS 中的体现。
