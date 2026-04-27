---
title: ECS框架场景工厂与根场景系统EntitySceneFactory与Root与SceneHelper完整解析
published: 2026-04-27
description: 深入解析游戏ECS框架中场景创建体系的设计，涵盖EntitySceneFactory的两种创建重载、Root单例根场景的启动职责、SceneHelper扩展方法对Domain/Zone访问的封装，以及SceneType枚举驱动的场景分类与按位标志查询机制。
tags: [Unity, ECS, 游戏框架, C#, 设计模式]
category: 技术
draft: false
encryptedKey: henhaoji123
---

## 前言

在ET/ECS架构的Unity游戏框架中，`Scene` 是承载所有游戏逻辑的"领域容器"——它是Entity数据树的根，也是 `Domain` 机制的实体化载体。围绕 `Scene` 的创建与访问，框架设计了一套清晰的工厂/单例/辅助方法体系：

- **`EntitySceneFactory`**：场景的工厂类，封装创建细节
- **`Root`**：程序进程级的根场景单例，管理最顶层Scene
- **`SceneHelper`**：扩展方法库，提供从任意Entity访问Domain/Zone/RootScene的便捷入口
- **`SceneType`**：枚举驱动的场景分类，支持按位标志查询

本文将逐一深入解析这四个组件的设计思路与工程实践。

---

## 一、EntitySceneFactory：职责单一的工厂静态类

```csharp
public static class EntitySceneFactory
{
    public static Scene CreateScene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent = null)
    {
        Scene scene = new Scene(id, instanceId, zone, sceneType, name, parent);
        return scene;
    }

    public static Scene CreateScene(int zone, SceneType sceneType, string name, Entity parent = null)
    {
        long instanceId = IdGenerater.Instance.GenerateInstanceId();
        Scene scene = new Scene(zone, instanceId, zone, sceneType, name, parent);
        return scene;
    }
}
```

### 1.1 两种创建重载的设计意图

工厂提供了两个重载，分别面向不同使用场景：

| 重载 | 使用场景 | ID来源 |
|------|---------|--------|
| `CreateScene(id, instanceId, zone, ...)` | 反序列化恢复、从持久化数据重建场景 | 外部指定（来自存储） |
| `CreateScene(zone, sceneType, ...)` | 运行时动态创建新场景 | `IdGenerater` 自动生成 |

第二个重载中，注意 `id` 参数直接传入了 `zone`：

```csharp
Scene scene = new Scene(zone, instanceId, zone, sceneType, name, parent);
//                      ^id     ^instanceId  ^zone
```

这意味着对于运行时创建的场景，其 `Id` 与 `Zone` 保持相同——Zone值同时充当场景的逻辑标识符。这是一种轻量的约定：在客户端单机场景下，Zone/Id通常是固定的小整数，不需要全局唯一的雪花ID。

### 1.2 工厂模式的封装价值

Scene构造函数参数较多（id/instanceId/zone/sceneType/name/parent），且不同场景有不同的ID生成策略。工厂类将这些差异封装在内部，外部调用方无需关心：

```csharp
// 简洁的调用方
Scene clientScene = EntitySceneFactory.CreateScene(1, SceneType.Client, "Client");
Scene processScene = EntitySceneFactory.CreateScene(0, SceneType.Process, "Process");
```

相比直接 `new Scene(...)` 散落在代码各处，工厂模式让创建逻辑集中可维护。

---

## 二、Root：进程级根场景单例

```csharp
public class Root: Singleton<Root>
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

### 2.1 Root在框架生命周期中的位置

`Root` 是整个ECS实体树的"大地"——所有Scene最终都挂载在 `Root.Instance.Scene` 下（或其子树中）。它继承自 `Singleton<Root>`，保证进程内唯一实例。

框架启动序列：

```
1. Game.AddSingleton<Root>()
      └── new Root()
             └── EntitySceneFactory.CreateScene(0, SceneType.Process, "Process")
                    └── new Scene(...) → Domain设置 → EventSystem注册
```

`Root.Scene` 是 `SceneType.Process` 类型，代表进程本身的顶层逻辑容器。在客户端框架中，随后会在此Scene下创建 `SceneType.Client` 子场景，并将所有游戏组件挂载其上。

### 2.2 Dispose的级联清理

```csharp
public override void Dispose()
{
    this.Scene.Dispose();
}
```

Root Dispose时直接Dispose其持有的根Scene，触发Entity两阶段Dispose的级联清理：

```
Root.Dispose()
  └── Scene.Dispose()
        ├── DisposeInternal()（递归注销所有子Entity的EventSystem注册）
        └── DetachAllChildrenRecursively()（递归回收所有组件和子节点到对象池）
```

这是整个框架关闭时的"总开关"，一行代码完成所有资源的有序释放。

### 2.3 为什么不用静态字段

`Root` 继承 `Singleton<Root>` 而非直接使用静态字段 `static Root instance`，有两个工程优势：

1. **生命周期可控**：Singleton由 `Game` 统一管理添加/移除，可以按序初始化和销毁
2. **热重载支持**：域重载时可以销毁旧Root、创建新Root，静态字段难以做到干净的二次初始化

---

## 三、SceneHelper：Domain访问的扩展方法封装

```csharp
public static class SceneHelper
{
    public static int DomainZone(this Entity entity)
    {
        return ((Scene) entity.Domain)?.Zone ?? 0;
    }

    public static Scene DomainScene(this Entity entity)
    {
        return (Scene) entity.Domain;
    }

    public static Scene Root(this Entity entity)
    {
        return (Scene)entity.RootScene;
    }
}
```

### 3.1 Domain概念回顾

在ECS框架中，每个Entity都有一个 `Domain` 属性，指向其所在实体树的"领域根Scene"。Domain的赋值在Entity.Domain setter中递归传播——父Entity设置Domain后，所有子Entity和组件都自动继承相同的Domain。

`SceneHelper` 在此基础上提供了三个便捷扩展：

### 3.2 DomainZone：获取区域编号

```csharp
int zone = someEntity.DomainZone();
```

等价于 `((Scene)someEntity.Domain)?.Zone ?? 0`。Zone是场景的逻辑分区号，在网络游戏中通常对应服务器区号或房间号，客户端单机框架中通常为0或固定值。

使用 `?.Zone ?? 0` 的防御写法：若Domain尚未设置（null），安全返回0而非抛出NullReferenceException。

### 3.3 DomainScene：获取当前Domain Scene

```csharp
Scene scene = someEntity.DomainScene();
```

将 `entity.Domain`（类型为 `Entity`）强转为 `Scene` 返回。由于框架约定Domain始终是Scene类型，这里的强转是安全的。

典型用途——在System中访问当前Scene上的全局组件：

```csharp
public class PlayerMoveSystem: IUpdateSystem
{
    void Update(PlayerComponent self)
    {
        // 通过DomainScene访问场景级配置组件
        var config = self.DomainScene().GetComponent<SceneConfigComponent>();
    }
}
```

### 3.4 Root：访问根场景

```csharp
Scene rootScene = someEntity.Root();
```

`entity.RootScene` 是Entity中指向整个实体树最顶层Scene的引用（对应 `Root.Instance.Scene`）。此扩展方法让跨层访问根场景无需依赖 `Root.Instance` 单例，减少了对单例的直接耦合。

---

## 四、SceneType：枚举驱动的场景分类

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
        if (((ulong) a & (ulong) b) == 0)
            return false;
        return true;
    }
}
```

### 4.1 三种内置场景类型

| SceneType | 用途 |
|-----------|------|
| `None = -1` | 哨兵值，表示未指定类型或无效场景 |
| `Process = 0` | 进程级场景，由Root持有，框架启动时创建 |
| `Client = 1` | 客户端逻辑场景，挂载在Process Scene下 |
| `Current = 2` | 当前激活的游戏场景（地图/关卡等动态场景） |

这套枚举反映了客户端框架的典型层次：

```
Root.Scene (Process)
  └── ClientScene (Client)
        └── CurrentScene (Current)  ← 随关卡切换销毁重建
```

### 4.2 HasSameFlag：按位标志查询

```csharp
public static bool HasSameFlag(this SceneType a, SceneType b)
{
    if (((ulong) a & (ulong) b) == 0)
        return false;
    return true;
}
```

虽然当前的枚举值（0/1/2）并未全部设计为位标志，但 `HasSameFlag` 为未来扩展做了准备。当SceneType需要同时表达多个类型（如 `Client | Current`）时，这个方法能直接支持：

```csharp
// 未来扩展：某个处理器同时处理Client和Current
[EventAttribute(SceneType.Client | SceneType.Current)]
```

`(ulong)` 强转确保负值（`None = -1`）在位运算时按无符号处理，避免符号位带来的逻辑错误。

### 4.3 EventAttribute中的SceneType约束

`SceneType` 与 `EventAttribute` 结合，实现了事件处理的场景隔离：

```csharp
[EventAttribute(SceneType.Client)]
public class PlayerInputHandler : AEvent<InputEvent>
{
    protected override void Run(Scene scene, InputEvent evt) { ... }
}
```

`EventSystem` 在分发事件时，会通过 `HasSameFlag` 校验事件处理器注册的SceneType与当前Scene.SceneType是否匹配，确保不同场景层的事件互不干扰。

---

## 五、四组件协作全景

将四个组件串联，就是框架的完整场景初始化链路：

```
程序启动
  │
  ├─ Game.AddSingleton<Root>()
  │     └─ Root() 构造
  │           └─ EntitySceneFactory.CreateScene(0, Process, "Process")
  │                 └─ new Scene(...)
  │
  ├─ 创建Client Scene
  │     └─ EntitySceneFactory.CreateScene(1, Client, "Client", parent: Root.Instance.Scene)
  │
  └─ 任意Entity通过SceneHelper访问Domain
        ├─ entity.DomainZone()  → 获取区号
        ├─ entity.DomainScene() → 获取Client/Current Scene
        └─ entity.Root()        → 获取Process Scene
```

---

## 六、总结

这套场景体系的设计体现了几个核心原则：

1. **工厂封装创建细节**：`EntitySceneFactory` 隐藏ID生成策略差异，调用方专注语义
2. **单例管理生命周期**：`Root` 通过 `Singleton` 体系统一初始化/销毁，支持热重载
3. **扩展方法减少耦合**：`SceneHelper` 让Entity访问Domain信息无需依赖单例，代码更干净
4. **枚举驱动事件隔离**：`SceneType` 与 `EventAttribute` 配合，场景层之间事件互不串扰

理解这套场景工厂体系，是深入掌握整个ECS框架实体树构建与事件分发机制的关键基础。
