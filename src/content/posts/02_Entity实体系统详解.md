---
title: 02 Entity 实体系统详解
published: 2024-01-01
description: "02 Entity 实体系统详解 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
---

# 02 Entity 实体系统详解

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

`Entity` 是整个框架的核心数据节点。你可以把它理解为游戏世界中的一切"有身份的对象"——玩家、怪物、背包、技能配置……都是 Entity。

与 Unity 的 `GameObject` 类似，Entity 也支持父子层级结构；与 MonoBehaviour 不同，Entity 是**纯 C# 对象**，不依赖 Unity 引擎的场景管理，生命周期完全由框架控制。

**核心特性一览：**

| 特性 | 说明 |
|---|---|
| 树形父子关系 | 每个 Entity 有唯一 Parent，支持递归查找 |
| Component 组合 | 同一 Entity 可挂载多种功能 Component（每种类型唯一） |
| 双 ID 体系 | `Id`（业务持久化）+ `InstanceId`（运行时唯一） |
| 对象池友好 | 支持 `isFromPool` 参数，降低 GC 压力 |
| 自动生命周期 | Awake/Start/Update/Destroy 由 EventSystem 自动分发 |
| 编辑器可视化 | 开启 `ENABLE_VIEW` 宏后，Entity 树实时显示在 Hierarchy |

---

## 2. 架构设计

### 2.1 类继承结构

```
DisposeObject（基类，管理 Dispose 状态）
  └── Entity（核心节点）
        ├── Scene（场景/Domain 节点，特殊的根实体）
        └── 所有业务 Entity（PlayerEntity、MonsterEntity 等）
```

`Entity` 继承自 `DisposeObject` 并实现了 `IHasHandler` 接口，保证了统一的资源释放入口和 Handler 查找能力。

### 2.2 核心字段结构

```csharp
public partial class Entity : DisposeObject, IHasHandler
{
    // === 身份 ===
    public long Id { get; set; }               // 业务 ID（持久化、跨进程引用）
    public long InstanceId { get; protected set; }  // 运行时唯一 ID（每次创建都不同）

    // === 状态 ===
    private EntityStatus status;              // 位域状态标志（见下节）

    // === 树形结构 ===
    protected Entity parent;                  // 父节点
    protected Entity domain;                  // 所属 Scene（Domain）

    // === 子节点存储 ===
    private Dictionary<long, Entity> children;      // 普通子节点（Id → Entity）
    private HashSet<Entity>          childrenDB;     // 可序列化子节点（ISerializeToEntity）

    // === 组件存储 ===
    private Dictionary<Type, Entity> components;    // 组件（Type → Entity）
    private HashSet<Entity>          componentsDB;   // 可序列化组件

    // === Handler 缓存 ===
    protected AHandler _handlerCache;
    protected bool bFindHandler;
}
```

### 2.3 双 ID 体系

```
Id（业务 ID）：
  - 由 IdGenerater.GenerateId() 生成
  - 当前实现为自增 long，用于数据库存储、网络传输、同类 Entity 区分
  - Component 的 Id = 宿主 Entity 的 Id

InstanceId（运行时 ID）：
  - 由 IdGenerater.GenerateInstanceId() 生成（时间 + 进程 + 序号编码）
  - 每次 Create 都会重新生成，用于 EventSystem 的全局注册表
  - IsDisposed 判断：InstanceId == 0 即为已销毁
```

---

## 3. 核心代码展示

### 3.1 EntityStatus 位域状态管理

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Entity.cs

[Flags]
public enum EntityStatus : byte
{
    None       = 0,
    IsFromPool = 1,       // 来自对象池，Dispose 时需要回收
    IsRegister = 1 << 1,  // 已注册到 EventSystem
    IsComponent = 1 << 2, // 以 Component 形式挂载（vs 以 Child 形式）
    IsCreated  = 1 << 3,  // 已完成初始化（防止重复 Deserialize）
    IsNew      = 1 << 4,  // 新建的（非反序列化），影响 DB 容器回收逻辑
}

// 典型的读写方式（以 IsFromPool 为例）：
private bool IsFromPool
{
    get => (this.status & EntityStatus.IsFromPool) == EntityStatus.IsFromPool;
    set
    {
        if (value) this.status |= EntityStatus.IsFromPool;
        else       this.status &= ~EntityStatus.IsFromPool;
    }
}
```

### 3.2 IsRegister 触发注册/注销

```csharp
protected bool IsRegister
{
    get => (this.status & EntityStatus.IsRegister) == EntityStatus.IsRegister;
    set
    {
        if (this.IsRegister == value) return;
        if (value) this.status |= EntityStatus.IsRegister;
        else       this.status &= ~EntityStatus.IsRegister;

        // 核心：通知 EventSystem 注册或注销
        EventSystem.Instance.RegisterSystem(this, value);

#if ENABLE_VIEW && UNITY_EDITOR
        // 编辑器模式下：同步创建/销毁对应的 GameObject 用于可视化
        if (value)
        {
            this.viewGO = new UnityEngine.GameObject(this.ViewName);
            this.viewGO.AddComponent<ComponentView>().Component = this;
            var targetParent = this.Parent == null
                ? UnityEngine.GameObject.Find("Global").transform
                : this.Parent.viewGO.transform;
            this.viewGO.transform.SetParent(targetParent);
        }
        else
        {
            UnityEngine.Object.Destroy(this.viewGO);
            this.viewGO = null;
        }
#endif
    }
}
```

### 3.3 Parent 属性的严格校验

```csharp
public Entity Parent
{
    get => this.parent;
    private set
    {
        if (value == null)  throw new Exception($"cant set parent null: {GetType().Name}");
        if (value == this)  throw new Exception($"cant set parent self: {GetType().Name}");
        // Domain 为 null 意味着 parent 不在 ECS 树上，禁止挂载
        if (value.Domain == null)
            throw new Exception($"cant set parent because parent domain is null: ...");

        if (this.parent != null && this.parent != value)
            this.parent.RemoveFromChildren(this);  // 先从旧父节点移除

        this.parent = value;
        this.IsComponent = false;          // 标记为 Child 模式
        this.parent.AddToChildren(this);   // 加入新父节点的 children 字典
        this.Domain = this.parent.domain;  // 传播 Domain（触发 InstanceId 生成和注册）
    }
}
```

### 3.4 Dispose 的两阶段处理

```csharp
public sealed override void Dispose()
{
    if (this.IsDisposed) return;

    // 阶段一：递归注销所有子节点，触发 Destroy 事件
    DisposeInternal();

    // 阶段二：递归清理数据容器，从父节点摘除，回收到对象池
    DetachAllChildrenRecursively();

    base.Dispose();
}

private void DisposeInternal()
{
    this.IsRegister = false;   // 从 EventSystem 注销
    this.InstanceId = 0;       // 标记为已销毁

    // 先递归处理所有 children 和 components
    if (this.children != null)
        foreach (var child in children.Values)
            child.DisposeInternal();

    if (this.components != null)
        foreach (var child in components.Values)
            child.DisposeInternal();

    // 触发 Destroy 事件（如果实现了 IDestroy 接口）
    if (this is IDestroy)
        EventSystem.Instance.Destroy(this);
}
```

### 3.5 GetComponent 触发 GetComponentSystem

```csharp
public K GetComponent<K>() where K : Entity
{
    if (this.components == null) return null;

    Entity component;
    if (!this.components.TryGetValue(typeof(K), out component))
        return default;

    // 如果宿主实现了 IGetComponent，触发 GetComponentSystem 回调
    // 这允许宿主在组件被访问时做一些额外处理（如懒初始化）
    if (this is IGetComponent)
        EventSystem.Instance.GetComponent(this, component);

    return (K)component;
}
```

### 3.6 多重泛型 AddChild 支持

```csharp
// 无参数版本
public T AddChild<T>(bool isFromPool = false) where T : Entity, IAwake
{
    T component = (T)Entity.Create(typeof(T), isFromPool);
    component.Id = IdGenerater.Instance.GenerateId();  // 子节点有独立 Id
    component.Parent = this;
    EventSystem.Instance.Awake(component);
    return component;
}

// 带 1 个初始化参数
public T AddChild<T, A>(A a, bool isFromPool = false) where T : Entity, IAwake<A>
{
    T component = (T)Entity.Create(typeof(T), isFromPool);
    component.Id = IdGenerater.Instance.GenerateId();
    component.Parent = this;
    EventSystem.Instance.Awake(component, a);  // 带参数的 Awake
    return component;
}

// 支持最多 4 个初始化参数（AddChild<T,A,B,C,D>）
```

---

## 4. 父子关系 vs 组件关系详解

### 4.1 概念对比

| 维度 | Child（子实体） | Component（组件） |
|---|---|---|
| 存储方式 | `children: Dictionary<long, Entity>` | `components: Dictionary<Type, Entity>` |
| 键类型 | `entity.Id`（long） | `entity.GetType()` |
| 同类限制 | **可以有多个同类型** | **每种类型只能有一个** |
| Id 生成 | 框架自动生成独立 Id | 与宿主 Entity 共享同一个 Id |
| 典型场景 | 怪物列表、子弹列表、背包格子 | 移动组件、战斗属性、技能组件 |
| IsComponent 标志 | false | true |

### 4.2 序列化控制（DB 容器）

框架为序列化提供了两套平行的存储容器：

- `children` / `childrenDB`：只有实现了 `ISerializeToEntity` 接口的子节点才进入 `childrenDB`
- `components` / `componentsDB`：同理

这样可以精确控制哪些 Entity 需要持久化，哪些只是临时运行时对象（如特效实体）。

---

## 5. 编辑器可视化（ENABLE_VIEW）

开启 `ENABLE_VIEW` 宏后，每个注册的 Entity 都会在 Unity Hierarchy 中创建一个对应的 `GameObject`，并挂载 `ComponentView` 组件，可直接在 Inspector 中查看 Entity 的字段值：

```
Global (GameObject)
 ├── Process (Scene)
 │    └── Client (Scene)
 │         ├── PlayerEntity
 │         │    ├── MoveComponent
 │         │    ├── BagComponent
 │         │    └── SkillComponent
 │         └── MonsterManager
 │              └── MonsterEntity[101]
 │              └── MonsterEntity[102]
```

**注意**：`ENABLE_VIEW` 仅用于调试，正式包务必关闭，否则每次创建/销毁 Entity 都会有 Hierarchy 操作开销。

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| `GetParentOfType<T>()` | 无 | 新增，支持向上递归查找指定类型的祖先 |
| `GetOrAddComponent<K>()` | 无 | 新增，获取不到则自动添加 |
| `GetChildRecursion<K>()` | 无 | 新增，递归查找子树中的 Entity |
| `ChangeParent()` | 无 | 新增，安全地将 Entity 移动到新父节点 |
| Handler 系统 | 无 | 新增 `GetHandler<T>()` / `TryGetHandler<T>()` |
| Destroy 阶段 | 单阶段 | 两阶段（`DisposeInternal` + `DetachAllChildrenRecursively`），更清晰 |
| `GetDebugString()` | 无 | 新增，返回 `"祖先 -> 父 -> 自身"` 形式的调试路径 |

---

## 7. 常见问题与最佳实践

### Q1：AddComponent 和 AddChild 应该怎么选？

**原则**：如果这个对象"是宿主的某种能力/属性"，用 Component；如果这个对象"是宿主管理的一批同类实例之一"，用 Child。

```csharp
// ✅ 玩家有一个背包组件 → Component
player.AddComponent<BagComponent>();

// ✅ 背包里有多个道具 → Child
bagComponent.AddChild<ItemEntity, int>(itemId);

// ❌ 错误：把多个同类怪物用 Component 存（同类 Component 只能一个）
monsterManager.AddComponent<MonsterEntity>(); // 第二次会 throw
```

### Q2：IsDisposed 如何正确判断？

```csharp
// 框架提供的判断方式
bool disposed = entity.IsDisposed;  // 等价于 entity.InstanceId == 0

// 在异步回调中务必检查
async ETTask SomeAsync(PlayerEntity player)
{
    await ETTask.Delay(1000);
    if (player.IsDisposed) return;  // ← 异步等待后必须检查
    player.GetComponent<MoveComponent>().Speed = 10;
}
```

### Q3：如何避免 "domain is null" 异常？

只要确保 Parent 链上存在 Scene 节点，Domain 就会自动传播。如果需要临时创建不挂树的 Entity，在加入树之前不要调用任何触发注册的操作。

### Q4：Entity 与 MonoBehaviour 如何配合？

推荐的做法是：Entity 持有业务逻辑，MonoBehaviour（View 层）持有对 Entity 的引用，由 Entity 主动驱动 View 更新：

```csharp
// View 层（MonoBehaviour）
public class PlayerView : MonoBehaviour
{
    public long EntityInstanceId;  // 只存 ID，不直接引用 Entity
    
    private PlayerEntity GetEntity()
        => EventSystem.Instance.Get(EntityInstanceId) as PlayerEntity;
}
```

---

## 8. 总结

Entity 系统是整个框架的基石。它用位域状态管理、双 ID 体系、Domain 传播机制，构建了一套**安全、高效、可序列化**的实体树。

新手重点掌握：
1. `AddComponent<T>()` vs `AddChild<T>()` 的选择标准
2. Dispose 的两阶段机制，避免在 Destroy 回调中误操作已销毁对象
3. `IsDisposed` 检查在所有异步回调入口处是必须的
