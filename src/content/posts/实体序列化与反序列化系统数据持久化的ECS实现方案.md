---
title: 实体序列化与反序列化系统——数据持久化的 ECS 实现方案
published: 2026-03-31
description: 解析 ISerializeToEntity 接口和 IDeserializeSystem 的设计，理解序列化在游戏中的作用、反序列化后初始化的时机选择，以及 ECS 框架如何通过接口标记实现数据持久化。
tags: [Unity, ECS, 序列化, 数据持久化, 存档]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 实体序列化与反序列化系统——数据持久化的 ECS 实现方案

## 前言

游戏数据的持久化是每个游戏必须面对的问题：玩家关闭游戏后，角色数据、背包物品、游戏进度应该如何保存？下次进入时如何恢复？

在 ECS 框架中，这通过**序列化**和**反序列化**系统来实现。今天我们来分析 `ISerializeToEntity` 和 `IDeserializeSystem` 的设计。

```csharp
// ISerializeToEntity.cs
public interface ISerializeToEntity { }

// IDeserializeSystem.cs
public abstract class DeserializeSystem<T> : IDeserializeSystem where T: Entity, IDeserialize
{
    void IDeserializeSystem.Run(Entity o)
    {
        this.Deserialize((T)o);
    }
    protected abstract void Deserialize(T self);
}
```

---

## 一、ISerializeToEntity——标记可序列化的实体

```csharp
public interface ISerializeToEntity { }
```

这是一个**空标记接口**，没有任何方法。

实现这个接口的实体，表示"我可以被序列化保存"。

**为什么是空接口？**

序列化的具体过程（把字段转成什么格式、用什么协议）由序列化框架处理（比如 MessagePack、Protobuf、JSON）。`ISerializeToEntity` 只是标记"这个类参与序列化"，不定义序列化如何进行。

**与 `[Serializable]` 的区别**：

.NET 有 `[System.Serializable]` 特性，但它是用于内置序列化（BinaryFormatter）的，不够灵活，且有安全问题。

ECS 框架用接口标记替代特性标记，因为接口可以通过反射更方便地过滤（`typeof(ISerializeToEntity).IsAssignableFrom(type)`）。

---

## 二、IDeserialize 与 DeserializeSystem——反序列化后的初始化

```csharp
public interface IDeserialize { }

[ObjectSystem]
[EntitySystem]
public abstract class DeserializeSystem<T> : IDeserializeSystem where T: Entity, IDeserialize
{
    void IDeserializeSystem.Run(Entity o)
    {
        this.Deserialize((T)o);
    }

    Type ISystemType.SystemType() => typeof(IDeserializeSystem);
    InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.None;
    Type ISystemType.Type() => typeof(T);

    protected abstract void Deserialize(T self);
}
```

### 2.1 为什么需要反序列化系统？

**序列化保存的是"数据快照"，但不是"运行时状态"。**

举个例子：

```csharp
public class SkillComponent: Entity, ISerializeToEntity, IDeserialize
{
    // 序列化字段（持久化的数据）
    public int SkillId;
    public int Level;
    
    // 运行时字段（不序列化）
    [NonSerialized]
    public SkillConfig Config; // 技能配置，从配置表加载
    [NonSerialized]
    public bool IsReady;       // 运行时状态，每次启动重新计算
}
```

数据从磁盘加载后，`Config` 和 `IsReady` 是空的——因为它们没有被序列化。

这时需要 `DeserializeSystem` 来重建这些运行时状态：

```csharp
[ObjectSystem]
public class SkillComponentDeserializeSystem: DeserializeSystem<SkillComponent>
{
    protected override void Deserialize(SkillComponent self)
    {
        // 从配置表重新加载配置
        self.Config = ConfigManager.GetSkillConfig(self.SkillId);
        
        // 重新计算初始状态
        self.IsReady = true;
        
        Log.Info($"技能 {self.SkillId} 反序列化完成");
    }
}
```

### 2.2 Deserialize vs Awake 的区别

初看起来，`Deserialize` 和 `Awake` 很像——都是初始化。区别在于：

- **Awake**：全新创建实体时调用，通常需要传入初始参数
- **Deserialize**：从已有数据（存档、网络同步数据）重建实体时调用，参数已经在实体字段中

```csharp
// 全新创建（走 Awake）
SkillComponent skill = entity.AddComponent<SkillComponent, int>(101); // 传 skillId

// 从存档恢复（走 Deserialize）
SkillComponent skill = Deserialize<SkillComponent>(savedData); // 数据已在字段中
EventSystem.Instance.Deserialize(skill); // 触发 Deserialize 系统
```

### 2.3 EventSystem.Deserialize 的调用

```csharp
// EventSystem 中
public void Deserialize(Entity component)
{
    List<object> iDeserializeSystems = 
        this.typeSystems.GetSystems(component.GetType(), typeof(IDeserializeSystem));
    if (iDeserializeSystems == null) return;

    foreach (IDeserializeSystem deserializeSystem in iDeserializeSystems)
    {
        try
        {
            deserializeSystem.Run(component);
        }
        catch (Exception e)
        {
            Log.Error(e);
        }
    }
}
```

这是直接调用（不经过队列），说明反序列化是**立即同步**的操作。

---

## 三、序列化的完整流程

```
保存：
实体字段 → 序列化框架（MessagePack/Protobuf）→ 二进制数据 → 磁盘/数据库

恢复：
磁盘/数据库 → 二进制数据 → 序列化框架 → 实体字段（数据恢复）
                                    ↓
                           EventSystem.Deserialize(entity)（运行时状态重建）
```

---

## 四、实际游戏中的应用场景

### 4.1 玩家存档

```csharp
// 保存
void SavePlayer(PlayerEntity player)
{
    byte[] data = Serializer.Serialize(player); // ISerializeToEntity 标记的字段被序列化
    File.WriteAllBytes("save/player.dat", data);
}

// 加载
PlayerEntity LoadPlayer()
{
    byte[] data = File.ReadAllBytes("save/player.dat");
    PlayerEntity player = Deserializer.Deserialize<PlayerEntity>(data);
    EventSystem.Instance.Deserialize(player); // 重建运行时状态
    return player;
}
```

### 4.2 网络同步

在多人游戏中，服务端维护权威状态，客户端从服务端接收数据：

```csharp
// 客户端接收到服务端的角色数据
void OnReceiveUnitData(UnitData data)
{
    UnitEntity unit = entityManager.GetUnit(data.UnitId);
    if (unit == null)
    {
        // 新实体，反序列化创建
        unit = Deserializer.Deserialize<UnitEntity>(data.Bytes);
        EventSystem.Instance.Deserialize(unit);
    }
    else
    {
        // 已有实体，更新数据
        Deserializer.MergeDeserialize(unit, data.Bytes);
        EventSystem.Instance.Deserialize(unit); // 重建可能改变的运行时状态
    }
}
```

---

## 五、[ObjectSystem][EntitySystem] 双标记的意义

```csharp
[ObjectSystem]
[EntitySystem]
public abstract class DeserializeSystem<T>
```

- `[ObjectSystem]`：系统类在框架启动时被扫描和实例化
- `[EntitySystem]`：系统方法支持热更新替换

特别是 `[EntitySystem]` 对反序列化很重要：如果游戏热更新了，数据格式或初始化逻辑可能改变，需要能替换 `Deserialize` 的实现。

---

## 六、InstanceQueueIndex.None 的含义

```csharp
InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.None;
```

反序列化不加入任何更新队列。它是按需触发的（显式调用 `EventSystem.Instance.Deserialize(entity)`），而非每帧自动调用。

---

## 七、与其他序列化方案的对比

| 方案 | 适用场景 | 优缺点 |
|---|---|---|
| `[SerializeField]` (Unity) | 编辑器序列化 | 简单，但只用于 Inspector |
| `[System.Serializable]` (.NET) | BinaryFormatter | 简单，但不安全、不灵活 |
| `ISerializeToEntity` + 自定义框架 | 游戏数据持久化 | 灵活、性能好，但复杂度高 |
| JSON (Newtonsoft) | 配置文件 | 可读性好，但性能差 |

大型游戏通常使用 Protobuf 或 MessagePack 配合自定义标记（如 `ISerializeToEntity`），在性能和灵活性之间取得平衡。

---

## 八、写给初学者

序列化是游戏开发中不可避免的话题，关键是理解两个概念：

1. **持久化数据**：需要跨会话保存的（角色等级、背包物品）
2. **运行时数据**：每次启动重新计算的（配置缓存、AI状态机）

`ISerializeToEntity` 标记哪些数据需要持久化，`DeserializeSystem` 负责启动时重建运行时数据。

两者配合，实现了"保存你需要保存的，重新计算你能重新计算的"——这是高效游戏存档系统的核心原则。
