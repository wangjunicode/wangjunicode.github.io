---
title: 01 ECS框架核心设计与实现
published: 2024-01-01
description: "01 ECS框架核心设计与实现 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
---

# 01 ECS框架核心设计与实现

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

ECS（Entity-Component-System）是一种以数据为中心的架构模式，在游戏引擎领域被广泛采用。与传统的面向对象继承体系不同，ECS 将"数据（Data）"与"行为（Behavior）"彻底分离：

- **Entity（实体）**：一个轻量级的标识符，携带若干 Component 数据
- **Component（组件）**：纯数据，挂载在实体上，无逻辑
- **System（系统）**：遍历具有特定 Component 组合的实体，统一执行行为逻辑

本项目基于 ET 框架的思路，在 Unity 上实现了一套**以 Entity 为核心节点、以 EventSystem 为系统调度中枢**的 ECS 变体。与纯 ECS 不同，本框架的 Entity 本身也持有数据（字段），System 以外挂的形式（`AwakeSystem`、`UpdateSystem` 等）绑定到 Entity 类型上，由 `EventSystem` 统一分发调用。

### 核心价值

1. **职责分离**：Entity 只管数据，System 只管逻辑，相互解耦
2. **热重载友好**：System 以反射注册的方式绑定，新增/修改 System 无需改动 Entity 本身
3. **生命周期统一**：Awake → Start → Update → LateUpdate → Destroy 全链路由框架管理
4. **内存高效**：Entity 和容器对象都走对象池，GC 压力极低

---

## 2. 架构设计

### 2.1 整体结构图

```
Game（静态调度入口）
 └── Singleton 系统
      ├── EventSystem（核心调度）
      │    ├── TypeSystems（类型→System 映射表）
      │    ├── allEntities（InstanceId → Entity 全局注册表）
      │    ├── queues[]（Update/LateUpdate/FixedUpdate 分发队列）
      │    └── allEvents（事件发布/订阅）
      ├── ObjectPool（对象池单例）
      ├── IdGenerater（全局 ID 生成器）
      ├── Root（根 Scene 持有者）
      └── CoroutineLockComponent（协程锁管理）

Entity（数据节点）
 ├── Id（业务 ID）
 ├── InstanceId（运行时唯一 ID）
 ├── Domain（所属 Scene，ECS 树根）
 ├── Parent（父节点）
 ├── Children（子实体，按 Id 索引）
 └── Components（组件，按 Type 索引）
```

### 2.2 系统注册流程

```
程序启动
  ↓
AssemblyHelper.GetAllType()  ← 扫描所有程序集
  ↓
EventSystem.Instance.Add(allTypes)
  ↓
遍历所有带 [ObjectSystem] 特性的类
  ↓
创建实例 → 按 Type() + SystemType() 存入 TypeSystems
  ↓
遍历带 [EventAttribute] 的类 → 注册 allEvents
  ↓
遍历带 [InvokeAttribute] 的类 → 注册 allInvokes
```

### 2.3 Entity 生命周期

```
Create(type, isFromPool)
  ↓
设置 ComponentParent / Parent
  ↓
Domain 被设置（触发 IsRegister = true）
  ↓
EventSystem.RegisterSystem(entity) → 加入 allEntities + queues
  ↓
EventSystem.Awake(entity)          ← 调用 AwakeSystem.Run()
  ↓
[每帧] EventSystem.Update()        ← 调用 UpdateSystem.Run()
  ↓
entity.Dispose()
  ↓
DisposeInternal()                  ← IsRegister=false，InstanceId=0
  ↓
EventSystem.Destroy(entity)        ← 调用 DestroySystem.Run()
  ↓
DetachAllChildrenRecursively()     ← 递归释放子节点，回收对象池
```

---

## 3. 核心代码展示

### 3.1 Entity 状态标志位设计

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Entity.cs

[Flags]
public enum EntityStatus : byte
{
    None       = 0,
    IsFromPool = 1,         // 是否来自对象池，影响 Dispose 时是否回收
    IsRegister = 1 << 1,    // 是否已注册到 EventSystem
    IsComponent = 1 << 2,   // 是否作为 Component 挂载（区别于 Child）
    IsCreated  = 1 << 3,    // 是否已经初始化过（防止重复反序列化）
    IsNew      = 1 << 4,    // 是否是新建的（非反序列化），影响 DB 容器的回收
}
```

**要点**：用一个 `byte` 的位域存储 5 个布尔状态，既节省内存又能原子化批量检查。

### 3.2 Domain 设置触发注册

```csharp
// Entity.cs - Domain 属性 setter（节选）

public Entity Domain
{
    get => this.domain;
    private set
    {
        if (value == null)
            throw new Exception($"domain cant set null: {this.GetType().Name}");
        if (this.domain == value) return;

        Entity preDomain = this.domain;
        this.domain = value;

        if (preDomain == null)
        {
            // 首次加入 ECS 树：生成 InstanceId 并注册到 EventSystem
            this.InstanceId = IdGenerater.Instance.GenerateInstanceId();
            this.IsRegister = true;    // ← 触发 EventSystem.RegisterSystem(this, true)

            // 反序列化时恢复 Components / Children 父子关系
            if (this.componentsDB != null) { /* ... */ }
            if (this.childrenDB != null)   { /* ... */ }
        }

        // 递归将子节点的 Domain 也更新为新 domain
        if (this.children != null)
            foreach (Entity entity in this.children.Values)
                entity.Domain = this.domain;

        if (this.components != null)
            foreach (Entity component in this.components.Values)
                component.Domain = this.domain;

        // 如果是反序列化出来的，触发 Deserialize 回调
        if (!this.IsCreated)
        {
            this.IsCreated = true;
            EventSystem.Instance.Deserialize(this);
        }
    }
}
```

### 3.3 AddComponent 典型流程

```csharp
// Entity.cs
public K AddComponent<K>(bool isFromPool = false) where K : Entity, IAwake, new()
{
    Type type = typeof(K);
    if (this.components != null && this.components.ContainsKey(type))
        throw new Exception($"entity already has component: {type.FullName}");

    // 1. 创建实例（来自对象池 or new）
    Entity component = Create(type, isFromPool);
    component.Id = this.Id;        // Component 的 Id 与宿主 Entity 相同
    component.ComponentParent = this;  // 2. 挂到 this 上，触发 Domain 传播 → 触发 IsRegister

    // 3. 触发 Awake 生命周期
    EventSystem.Instance.Awake(component);

    // 4. 通知宿主 Entity（如果实现了 IAddComponent 接口）
    if (this is IAddComponent)
        EventSystem.Instance.AddComponent(this, component);

    return component as K;
}
```

### 3.4 EventSystem 的 Update 分发

```csharp
// EventSystem.cs - Update()

public void Update()
{
    Start();   // 先跑一次 StartSystem（保证新加入的实体在第一帧执行 Start）

    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Update];
    int count = queue.Count;  // ← 记录初始数量，避免本帧新注册的实体被立即调用

    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        if (!this.allEntities.TryGetValue(instanceId, out Entity component)) continue;
        if (component.IsDisposed) continue;

        List<object> iUpdateSystems = this.typeSystems.GetSystems(component.GetType(), typeof(IUpdateSystem));
        if (iUpdateSystems == null) continue;

        queue.Enqueue(instanceId);  // 重新入队，下帧继续

        foreach (IUpdateSystem iUpdateSystem in iUpdateSystems)
        {
            try { iUpdateSystem.Run(component); }
            catch (Exception e) { Log.Error(e); }
        }
    }
}
```

---

## 4. 设计亮点

### 4.1 Data-Behavior 双层分离

本框架对原版 ECS 做了工程化改良：Entity 既是数据节点，又充当标识符，而 System 以外挂文件形式存在（`PlayerSystem.cs`、`MonsterSystem.cs` 等），与 Entity 定义文件完全分离。这样多人协作时冲突概率大幅降低。

### 4.2 基于位域的高效状态管理

用 `EntityStatus` 枚举 + 位运算代替多个 `bool` 字段，一次内存读写可检查多个状态，在频繁创建/销毁场景下性能优势明显。

### 4.3 队列快照防重入

Update 中先记录 `count = queue.Count`，再循环，保证本帧新注册的实体不会在同一帧内被调用 Update，彻底避免"注册时序"导致的 Bug。

### 4.4 Domain 机制

Entity 树必须有 Domain（Scene 类型）才能激活。这个设计保证了实体必须挂在场景树上才会被 EventSystem 感知，孤立的 Entity 不会被调度，大幅降低悬空引用风险。

---

## 5. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| 端架构 | 客户端 + 服务端双端 | 纯 Unity 客户端 |
| 热重载 | 支持（ET6 ILRuntime/Roslyn） | 暂不支持热重载 |
| System 注册 | 反射扫描所有 Assembly | 同，新增 `RegisterOneEvent` 手动注册接口 |
| 物理回调 | 无 FixedUpdate 队列 | 新增 `FixedUpdate`/`LateFixedUpdate`/`Physics` 队列 |
| Destroy 流程 | 单阶段 Run | 两阶段：`BeforeRun` → `Run`，便于资源预清理 |
| 视图调试 | 无 | `ENABLE_VIEW` 宏：在 Hierarchy 实时显示 Entity 树 |
| Handler 系统 | 无 | 新增 `AHandler`/`GetHandler<T>()` 供 Entity 直接获取关联 Handler |

---

## 6. 常见问题与最佳实践

### Q1：Entity 创建后为何 Awake 没有触发？

**原因**：Entity 没有被挂到 ECS 树（没有设置 Domain）。  
**解决**：确保使用 `entity.Parent = someParent` 或 `parent.AddChild<T>()` / `parent.AddComponent<T>()`，这些方法会自动传播 Domain。

### Q2：如何正确销毁一个 Entity？

```csharp
// ✅ 正确
entity.Dispose();

// ❌ 错误：不要手动清除父子关系再 Dispose，框架内部会处理
entity.Parent.RemoveComponent(entity);
entity.Dispose();  // 会导致重复 RemoveComponent
```

### Q3：Component 和 Child 的区别是什么？

| | Component | Child |
|---|---|---|
| 挂载位置 | `entity.components`（Type 为键） | `entity.children`（Id 为键） |
| 同类限制 | 一个 Entity 只能有一个同类型的 Component | 可以有多个同类型的 Child |
| 典型用途 | 附属功能模块（技能组件、背包组件） | 大量同类业务实体（子弹、道具） |

### Q4：如何写一个 UpdateSystem？

```csharp
// 1. 让 Entity 实现 IUpdate 接口
public class PlayerMoveComponent : Entity, IAwake, IUpdate
{
    public float Speed;
}

// 2. 继承 UpdateSystem<T> 实现逻辑
[ObjectSystem]
public class PlayerMoveComponentUpdateSystem : UpdateSystem<PlayerMoveComponent>
{
    protected override void Update(PlayerMoveComponent self)
    {
        // 每帧执行移动逻辑
    }
}
```

### Q5：为什么不用 MonoBehaviour？

MonoBehaviour 的生命周期由 Unity 引擎控制，难以在纯 C# 代码中单元测试，也难以在服务端复用。ECS 的 System 是纯 C# 类，可以在任何环境下运行。

---

## 7. 总结

本框架的 ECS 实现是**"轻量 ECS + 完整生命周期"**的融合方案：

- Entity 作为数据容器，通过对象池提升内存效率
- EventSystem 作为统一调度中枢，通过反射 + 队列实现 System 分发
- Domain/Scene 机制保证 Entity 树的完整性和安全性

理解了这套架构，你就掌握了整个项目的骨架。后续所有系统（UI、战斗、网络）都建立在这个骨架之上。
