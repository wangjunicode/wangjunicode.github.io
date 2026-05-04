---
title: xgame框架Scene与Root场景根节点深度解析-Domain自引用与进程级场景树初始化设计
date: 2026-05-04
tags:
  - Unity
  - 游戏框架
  - ECS
  - Scene
  - 单例模式
  - 场景管理
categories:
  - xgame框架源码解析
description: 深度解析xgame框架中Scene密封类与Root单例的完整设计，重点讲解Scene作为Domain自引用节点的特殊身份、双构造函数的id/instanceId分离策略、Parent属性的空值宽容重写、SceneType语义分层与RootScene快速访问链、以及Root作为进程级场景树根的Singleton生命周期管理与EntitySceneFactory的工厂封装模式。
encryptedKey: henhaoji123
---

## 前言

在 xgame 框架的 ECS 数据树中，所有 Entity 都必须挂载在某个 `Domain` 下才能获得 `InstanceId` 并注册到 `EventSystem`。那 Domain 本身由谁来担任？答案是 `Scene`。`Scene` 是框架中唯一一种可以将 `Domain` 设为自身的 Entity，它是整棵数据树的"根锚点"。本文结合 `Scene.cs`、`Root.cs` 和 `SceneType.cs` 源码，完整拆解这套场景树设计。

---

## 一、Scene 的特殊身份：Domain 自引用节点

普通 Entity 的 Domain 由父节点传递而来：

```csharp
// Entity.cs — 设置 Parent 时触发
this.Domain = this.parent.domain;
```

但 Scene 重写了 `Domain` 属性，允许直接赋值：

```csharp
// Scene.cs
public new Entity Domain
{
    get => this.domain;
    set => this.domain = value;  // 无校验，直接写
}
```

在 Scene 的构造函数中：

```csharp
public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = instanceId;
    this.InstanceId = instanceId;   // id == instanceId，无需 IdGenerater 分配
    this.IsCreated = true;
    this.IsNew = true;
    this.Parent = parent;
    this.Domain = this;             // ← 关键：Domain 指向自身
    this.IsRegister = true;
    Log.Info($"scene create: {this.SceneType} ...");
}
```

**`this.Domain = this` 的意义：** Scene 自己就是 Domain，它不依赖外部 Domain 传播链就能完成注册。这意味着 Scene 是整棵子树的"根锚点"——挂载到 Scene 下的任何 Entity，都会通过 Domain 传播链自动获得 InstanceId 并注册。

---

## 二、双构造函数：id 与 instanceId 的分离策略

Scene 提供了两个构造函数：

```csharp
// 构造函数 A：id == instanceId（进程级 Scene）
public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = instanceId;
    this.InstanceId = instanceId;
    // ...
}

// 构造函数 B：id 与 instanceId 独立（跨区 Scene，如服务端 Zone Scene）
public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = id;
    this.InstanceId = instanceId;
    // ...
}
```

**为什么需要区分 id 和 instanceId？**

- `Id`：逻辑标识，可在网络消息中传输，代表"是哪个区/哪个玩家"
- `InstanceId`：运行时标识，进程内唯一，包含进程号和时间戳编码，用于 EventSystem 注册

对于进程级 Scene（如 `SceneType.Process`），两者相同，用 `instanceId` 填充即可。对于需要跨区通信的 Scene（如多区服务器），两者需要独立分配，以便网络层正确路由。

---

## 三、Parent 属性重写：空值宽容设计

普通 Entity 的 Parent setter 在 `value == null` 时直接抛异常：

```csharp
// Entity.cs
if (value == null)
    throw new Exception($"cant set parent null: ...");
```

Scene 重写了 Parent：

```csharp
// Scene.cs
public new Entity Parent
{
    set
    {
        if (value == null)
        {
            //this.parent = this; // 注释掉的方案：自引用
            return;  // 静默返回，不报错
        }
        this.parent = value;
        this.parent.Children.Add(this.Id, this);
    }
}
```

**设计意图：** 进程最顶层的 Scene（如 Root.Scene）没有父节点，允许 `null`。同时注意这里直接操作 `this.parent.Children.Add(...)` 而不是通过 `AddToChildren`（后者会额外处理 DB 镜像和 Domain 传播）——Scene 的 Domain 已经自引用，不需要走普通的传播路径。

---

## 四、SceneType 语义分层

```csharp
public SceneType SceneType { get; }
```

`SceneType` 是一个枚举，在框架中承担场景语义标注的角色。常见值包括：

| SceneType | 含义 |
|-----------|------|
| `Process` | 进程级根 Scene，整棵 Entity 树的起点 |
| `Client`  | 客户端逻辑 Scene |
| `Zone`    | 服务端分区 Scene |
| `Map`     | 地图场景 |

`RootScene` 快速访问链利用了这一分层：

```csharp
// Entity.cs
public Scene RootScene => 
    ((Scene)Domain).SceneType == SceneType.Client 
        ? (Scene)Domain 
        : (Scene)Domain.Parent?.Parent;
```

对于客户端 Entity，Domain 本身就是 RootScene；对于服务端多层嵌套场景，通过两次向上导航（`Parent?.Parent`）找到 Zone 层的根 Scene。这是一个硬编码的深度假设，适用于框架约定的两层嵌套结构。

---

## 五、Root 单例：进程级场景树的唯一入口

```csharp
public class Root : Singleton<Root>
{
    public Scene Scene { get; }

    public Root()
    {
        this.Scene = EntitySceneFactory.CreateScene(0, SceneType.Process, "Process");
    }

    public override void Dispose()
    {
        this.Scene.Dispose();
    }
}
```

**Root 的职责极为简单，但定位至关重要：**

1. 继承 `Singleton<Root>`，确保全局唯一
2. 在构造函数中通过工厂创建进程级 `Scene`（Zone=0，SceneType=Process）
3. `Dispose` 时级联销毁整棵 Scene 树

**为什么用 Singleton 而不是 static？**

`Singleton<Root>` 接入了框架的生命周期管理（`ISingletonAwake`、`Register/Destroy`），可以在热重载时被正确销毁和重建，而 `static` 字段在这些场景下会残留旧数据。

---

## 六、EntitySceneFactory：工厂封装的创建约定

`Root` 通过 `EntitySceneFactory.CreateScene(...)` 而非直接 `new Scene(...)` 来创建场景。工厂的价值在于：

1. **参数标准化**：统一处理 `instanceId` 的生成逻辑（通过 `IdGenerater`）
2. **挂载约定**：封装父节点挂载逻辑，调用方无需关心 `Parent` 赋值顺序
3. **扩展点**：未来如需在创建时触发额外系统事件，只需修改工厂，不影响调用方

这遵循了"Don't construct Entity directly"的框架约定——所有 Entity 的创建应通过 `AddChild`、`AddComponent` 或专用工厂方法进行，而不是直接 `new`。

---

## 七、Scene 的 Destroy 系统：轻量生命周期钩子

```csharp
public static partial class SceneSystem
{
    [EntitySystem]
    private static void Destroy(this Scene self)
    {
        Log.Info($"scene dispose: {self.SceneType} {self.Name} {self.Id} {self.InstanceId} {self.Zone}");
    }
}
```

`Scene` 实现了 `IDestroy` 接口，在 `Dispose` 时通过 `EventSystem.Instance.Destroy(this)` 触发此方法。这里只做日志记录，但这是一个标准的扩展点——子类或系统可以在此处做资源卸载、网络断开通知等清理工作。

`[EntitySystem]` 特性是框架的自动注册标记，`EventSystem` 启动时通过反射扫描所有带此特性的方法，构建类型到系统方法的分发表。

---

## 八、完整生命周期图

```
游戏启动
    │
    ▼
Root.Instance                   (Singleton<Root> 初始化)
    │
    ▼
EntitySceneFactory.CreateScene  (工厂创建 Process Scene)
    │
    ▼
new Scene(instanceId, ...)
    ├── Domain = this            (自引用，成为根锚点)
    ├── IsRegister = true        (注册到 EventSystem)
    └── Parent = null            (无父节点，静默返回)
    │
    ▼
AddChild<GameComponent>()       (挂载游戏组件)
    ├── component.Domain = scene (Domain 传播)
    ├── InstanceId 分配
    └── EventSystem.Awake()
    │
    ▼
游戏运行中...
    │
    ▼
Root.Dispose()
    └── scene.Dispose()
        ├── DisposeInternal()   (递归注销 + 触发 Destroy)
        └── DetachAll...()      (清引用 + 归还对象池)
```

---

## 九、总结

| 设计点 | 实现方案 | 价值 |
|--------|---------|------|
| Domain 自引用 | `this.Domain = this` | Scene 成为子树根锚点，无需外部 Domain |
| 双构造函数 | id / instanceId 分离 | 同时支持单进程和跨区多进程场景 |
| Parent 空值宽容 | 静默 return | 顶层 Scene 无需父节点，不破坏树结构 |
| SceneType 分层 | 枚举语义标注 | RootScene 快速访问，多层场景结构清晰 |
| Root 单例 | `Singleton<Root>` | 接入框架生命周期，支持热重载 |
| 工厂创建 | `EntitySceneFactory` | 封装创建约定，统一 Id 生成和挂载顺序 |

`Scene` 和 `Root` 的简洁代码量背后，是整个 xgame ECS 框架最深层的基础设施。理解它们，就理解了整棵游戏对象树的生长方式。
