---
title: 09 Scene 场景管理与 Domain 机制
published: 2024-01-01
description: "09 Scene 场景管理与 Domain 机制 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 09 Scene 场景管理与 Domain 机制

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

在本框架中，`Scene` 不是 Unity 的场景（UnityScene），而是 ECS 框架层的一个特殊 Entity，充当**整棵实体树的根节点**。每个 Scene 有一个类型（`SceneType`），用于标识它代表的逻辑层次（全局进程、客户端、战斗室、UI 等）。

`Domain` 机制是理解 Scene 的关键：**一个 Entity 必须有 Domain（Scene 根）才能被 EventSystem 感知**。Domain 通过 Entity 树自动向下传播，保证树上的每个节点都知道自己属于哪个 Scene。

### 核心职责

| 职责 | 描述 |
|---|---|
| ECS 树根节点 | Scene 是所有 Entity 挂载的顶层节点 |
| 事件作用域 | Publish/Subscribe 时按 SceneType 过滤，精确投递 |
| 全局根（Root） | `Root` 单例持有 Process Scene，是整棵树的起点 |
| Domain 传播 | Entity 挂载时自动传播 Domain，触发 InstanceId 生成和 EventSystem 注册 |

**核心文件**：
- `X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Scene.cs`
- `X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Root.cs`
- `X:\UnityProj\Assets\Scripts\Core\ECS\Entity\EntitySceneFactory.cs`

---

## 2. 架构设计

### 2.1 Scene 继承体系

```
DisposeObject
  └── Entity
        └── Scene（密封类，sealed）
              ├── Id = InstanceId（Scene 的 Id 与 InstanceId 相同）
              ├── Zone: int（分区号）
              ├── SceneType: SceneType（类型枚举）
              ├── Name: string（调试名称）
              └── Domain = this（Scene 自身就是 Domain）
```

**注意**：Scene 是 `sealed`（密封类），不允许被继承。它是 ECS 树的"容器节点"，业务逻辑应通过挂载 Component 或 Child 实现，而不是继承 Scene。

### 2.2 典型 Scene 树结构

```
Root.Scene（SceneType.Process，id=1）← 整棵树的根
  ├── ClientScene（SceneType.Client）← 客户端主场景
  │    ├── UIScene（SceneType.UI）   ← UI 子场景
  │    │    └── UIManagerComponent
  │    ├── PlayerEntity              ← 玩家实体
  │    │    ├── MoveComponent
  │    │    └── BagComponent
  │    └── MapScene（SceneType.Map） ← 地图子场景
  │         └── MonsterManager
  └── NetworkScene（SceneType.Network）← 网络场景
       └── SessionComponent
```

### 2.3 SceneType 枚举

SceneType 用于区分不同类型的场景，主要作用：

1. **事件过滤**：`Publish<T>(scene, evt)` 只通知 `SceneType` 匹配的处理器
2. **场景标识**：方便调试和日志定位

```csharp
// 典型的 SceneType 定义（项目自定义）
public enum SceneType
{
    None    = 0,  // 全局事件（不过滤）
    Process = 1,  // 进程根场景
    Client  = 2,  // 客户端主场景
    UI      = 3,  // UI 场景
    Map     = 4,  // 地图场景
    Network = 5,  // 网络场景
    // ...
}
```

---

## 3. 核心代码展示

### 3.1 Scene 类实现

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Scene.cs

[EnableMethod]
[ChildOf]
public sealed class Scene : Entity, IDestroy
{
    public int Zone { get; }         // 分区号（分布式场景中区分服务分区）
    public SceneType SceneType { get; } // 场景类型
    public string Name { get; set; }    // 调试名称

    // 构造函数 1：instanceId == id（常用于客户端场景）
    public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent)
    {
        this.Id = instanceId;
        this.InstanceId = instanceId;
        this.Zone = zone;
        this.SceneType = sceneType;
        this.Name = name;
        this.IsCreated = true;
        this.IsNew = true;
        this.Parent = parent;        // 设置父节点，触发 Domain 传播
        this.Domain = this;          // ← 关键：Scene 的 Domain 是自己！
        this.IsRegister = true;      // 立即注册到 EventSystem
        Log.Info($"scene create: {this.SceneType} {this.Name} {this.Id}");
    }

    // 构造函数 2：id != instanceId（服务端恢复已有场景）
    public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent)
    {
        this.Id = id;
        this.InstanceId = instanceId;
        // 其余同上
    }

    // 重写 Domain 属性：Scene 的 Domain 必须是自身
    public new Entity Domain
    {
        get => this.domain;
        set => this.domain = value;  // 允许外部设置（通常只有 Scene 自己设置 = this）
    }

    // 重写 Parent 属性：加入父节点的 Children 字典
    public new Entity Parent
    {
        get => this.parent;
        set
        {
            if (value == null) return;
            this.parent = value;
            this.parent.Children.Add(this.Id, this);  // Scene 作为 Child 挂载
        }
    }

    // 按 Id 查找子 Scene
    public Scene Get(long id)
    {
        if (this.Children == null) return null;
        if (!this.Children.TryGetValue(id, out Entity entity)) return null;
        return entity as Scene;
    }

    protected override string ViewName => $"{GetType().Name} ({this.SceneType})";
}
```

### 3.2 Root —— ECS 树的根节点

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Root.cs

public class Root : Singleton<Root>
{
    public Scene Scene { get; }

    public Root()
    {
        // 创建进程根 Scene，Zone=0，无父节点
        this.Scene = EntitySceneFactory.CreateScene(0, SceneType.Process, "Process");
    }

    public override void Dispose()
    {
        this.Scene.Dispose();  // 销毁根 Scene，会递归销毁所有子节点
    }
}

// 全局访问
Root.Instance.Scene  // → Process Scene（整棵树的根）
```

### 3.3 EntitySceneFactory —— Scene 工厂

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\EntitySceneFactory.cs

public static class EntitySceneFactory
{
    // 完整参数版本（服务端恢复场景时用，id 和 instanceId 分离）
    public static Scene CreateScene(long id, long instanceId, int zone,
                                    SceneType sceneType, string name, Entity parent = null)
    {
        return new Scene(id, instanceId, zone, sceneType, name, parent);
    }

    // 简化版本（客户端新建场景，instanceId 由 IdGenerater 自动生成）
    public static Scene CreateScene(int zone, SceneType sceneType, string name,
                                    Entity parent = null)
    {
        long instanceId = IdGenerater.Instance.GenerateInstanceId();
        // Scene(zone, instanceId, zone, ...) → Zone 同时作为 Id 使用
        return new Scene(zone, instanceId, zone, sceneType, name, parent);
    }
}
```

### 3.4 Domain 传播的完整流程

```csharp
// 以 Entity.ComponentParent 属性为例（Component 挂载时触发）

private Entity ComponentParent
{
    set
    {
        if (value == null)
            throw new Exception($"cant set parent null: {GetType().Name}");

        this.parent = value;
        this.IsComponent = true;  // 标记为 Component 模式

        // 将自己加入父节点的 components 字典
        this.parent.Components.Add(GetType(), this);

        // ← 触发 Domain 传播的关键：
        this.Domain = this.parent.domain;
    }
}

// Entity.Domain 的 setter（传播核心）
private set
{
    if (value == null)
        throw new Exception($"domain cant set null: {GetType().Name}");
    if (this.domain == value) return;

    Entity preDomain = this.domain;
    this.domain = value;

    if (preDomain == null)
    {
        // 首次挂上 ECS 树：生成 InstanceId，注册到 EventSystem
        this.InstanceId = IdGenerater.Instance.GenerateInstanceId();
        this.IsRegister = true;  // → EventSystem.RegisterSystem(this)
    }

    // 递归将子节点的 Domain 同步更新
    if (this.children != null)
        foreach (Entity entity in this.children.Values)
            entity.Domain = this.domain;

    if (this.components != null)
        foreach (Entity component in this.components.Values)
            component.Domain = this.domain;

    // 若是反序列化出来的节点，触发 Deserialize 回调
    if (!this.IsCreated)
    {
        this.IsCreated = true;
        EventSystem.Instance.Deserialize(this);
    }
}
```

### 3.5 SceneSystem —— Scene 的销毁回调

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\Entity\Scene.cs

public static partial class SceneSystem
{
    [EntitySystem]
    private static void Destroy(this Scene self)
    {
        Log.Info($"scene dispose: {self.SceneType} {self.Name} {self.Id} {self.Zone}");
    }
}
```

---

## 4. 事件系统中的 SceneType 过滤

Domain 机制与事件系统深度集成：每次 `Publish` 时，都会根据 SceneType 过滤处理器：

```csharp
// EventSystem.cs - Publish
public void Publish<T>(Scene scene, T a)
{
    SceneType sceneType = scene.SceneType;  // 获取发布者的 SceneType

    foreach (EventInfo eventInfo in iEvents)
    {
        // 过滤：只响应 SceneType 匹配或 SceneType.None（全局）的处理器
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue;

        // ...执行处理器
    }
}
```

**示例**：

```csharp
// 只在 Client Scene 中响应（SceneType.Client）
[Event(SceneType.Client)]
public class PlayerLoginHandler : AEvent<PlayerLoginEvent>
{
    protected override void Run(Scene scene, PlayerLoginEvent evt)
    {
        // 只有当 scene.SceneType == SceneType.Client 时才会被调用
    }
}

// 全局处理（SceneType.None）：所有场景类型都会触发
[Event(SceneType.None)]
public class GlobalErrorHandler : AEvent<ErrorEvent>
{
    protected override void Run(Scene scene, ErrorEvent evt)
    {
        Log.Error($"[{scene.SceneType}] Error: {evt.Message}");
    }
}
```

---

## 5. Scene 的创建与销毁实践

### 5.1 创建子 Scene

```csharp
// 在 Client Scene 下创建 UI 子场景
Scene clientScene = Root.Instance.Scene.Get(clientSceneId);

Scene uiScene = EntitySceneFactory.CreateScene(
    zone:      0,
    sceneType: SceneType.UI,
    name:      "UIScene",
    parent:    clientScene  // ← 挂载到 Client Scene 下
);

// 现在可以向 uiScene 下添加 Entity
uiScene.AddComponent<UIManagerComponent>();
```

### 5.2 销毁 Scene

```csharp
// 销毁整个子场景及其所有子节点
uiScene.Dispose();
// → 触发 SceneSystem.Destroy 日志
// → 递归 Dispose 所有子 Entity 和 Component
// → 从父节点的 children 中移除
```

### 5.3 查找 Domain（所在 Scene）

```csharp
// 从任意 Entity 获取其所在 Scene
Entity someEntity = ...;
Scene scene = someEntity.Domain as Scene;

// 或获取它的 SceneType
SceneType sceneType = (someEntity.Domain as Scene)?.SceneType ?? SceneType.None;
```

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| Scene 是否密封 | 是 | 是 |
| Domain = this | 相同 | 相同 |
| EntitySceneFactory | 相同 | 相同 |
| SceneType 定义 | 服务端多 Scene 类型（Gate/Map/Realm...） | 客户端 Scene 类型（Client/UI/Map/Network...） |
| Root 根场景 | SceneType.Process | 相同 |
| Zone 参数 | 多区服务端，Zone 用于玩家路由 | 客户端保留参数，通常为0 |
| 子场景嵌套 | 支持 | 支持，且 Get(id) 方法可查找直接子 Scene |

---

## 7. 常见问题与最佳实践

### Q1：Scene 和普通 Entity 的最大区别是什么？

1. **Domain = this**：Scene 是自己的 Domain，普通 Entity 的 Domain 指向最近的祖先 Scene
2. **Id == InstanceId**：Scene 的两个 ID 相同（通常）
3. **不走对象池**：Scene 不使用 `isFromPool`，每次都是 `new`
4. **密封类**：不能被继承，只能通过挂载 Component/Child 扩展功能

### Q2：一个 Entity 如何知道自己在哪个 Scene 下？

```csharp
// entity.Domain 就是最近的祖先 Scene
Scene ownerScene = entity.Domain as Scene;
```

### Q3：为什么 Entity 不设置 Domain 就无法被 EventSystem 管理？

因为 `IsRegister = true` 的前提是 `Domain` 被首次设置：

```csharp
if (preDomain == null)
{
    this.InstanceId = IdGenerater.Instance.GenerateInstanceId();
    this.IsRegister = true;  // ← 只有这里才会触发注册
}
```

孤立的 Entity（未挂到任何 Scene 树）永远不会有 Domain，也就不会有 InstanceId，更不会被 EventSystem 驱动。这是框架的安全设计。

### Q4：可以有多个根 Scene 吗？

`Root` 单例持有唯一的 Process Scene，但你可以在 Process Scene 下挂多个子 Scene（如 ClientScene、NetworkScene）。理论上可以在 Process Scene 同级创建另一个 Scene，但通常没有必要。

---

## 8. 总结

Scene 和 Domain 机制构成了 ECS 框架的"树形命名空间"：

- **Scene** 是 ECS 树的分区节点，通过 SceneType 区分逻辑层次
- **Domain** 自动向下传播，确保树上每个节点都能找到自己的根
- **事件过滤** 基于 SceneType 实现精确投递，避免不同场景间的事件干扰
- **Root** 持有整棵树的根，程序启动后第一个创建，关闭时最后一个销毁

对于新手来说，最重要的理解是：**Entity 必须挂到 Scene 树上才能"活着"**，没有 Domain 的 Entity 是框架看不见的死对象。
