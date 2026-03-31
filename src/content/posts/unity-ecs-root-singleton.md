---
title: 根场景单例——游戏世界的起点与生命周期管理
published: 2026-03-31
description: 解析 Root 单例类如何作为整个游戏世界的起点，理解进程级场景的设计意图、单例生命周期管理以及 ECS 实体树的根节点架构。
tags: [Unity, ECS, 单例, 场景管理, 生命周期]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 根场景单例——游戏世界的起点与生命周期管理

## 前言

每个程序都有一个"起点"。

在 ECS 框架中，所有的场景、实体都需要挂载在一个树形结构上。那么，树的根是什么？

`Root` 类就是答案——它是整个 ECS 世界的根节点，是所有其他场景和实体的最终归宿。

```csharp
namespace ET
{
    // 管理根部的Scene
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
}
```

短短几行，但承载了整个游戏世界的起始逻辑。

---

## 一、Root 的位置——整个 ECS 树的根

在典型的 ECS 架构中，实体以树形结构组织：

```
Root.Scene（Process Scene，根场景）
├── Client Scene（客户端场景）
│   ├── UI Scene
│   ├── Game Scene
│   └── ...
└── 其他子场景
```

`Root.Scene` 是所有场景的最终父节点。当你访问任何实体的 `entity.RootScene`，最终都会指向这个根场景。

---

## 二、Singleton<Root> 单例模式

```csharp
public class Root: Singleton<Root>
```

`Root` 继承自 `Singleton<Root>`，这是泛型单例模式：

```csharp
// 访问方式
Root.Instance.Scene
```

**为什么根场景需要是单例？**

逻辑很简单：整个进程只有一个"根"。如果有多个"根"，整个树结构就变成了"森林"，管理起来更复杂，而且很多全局操作（比如"找到所有实体"）就需要遍历多个根。

单例确保全局唯一，所有代码都能通过 `Root.Instance` 找到同一个入口。

---

## 三、SceneType.Process——进程级场景

```csharp
this.Scene = EntitySceneFactory.CreateScene(0, SceneType.Process, "Process");
```

根场景的类型是 `SceneType.Process`——代表"进程"级别的场景。

```csharp
public enum SceneType
{
    None = -1,
    Process = 0,  // 进程级，最顶层
    Client = 1,   // 客户端场景
    Current = 2   // 当前活跃场景
}
```

**场景类型的层级语义**：

- `Process`（进程）：整个程序运行期间存在，代表这个程序进程本身。所有其他场景都在它下面。
- `Client`（客户端）：代表一个客户端连接或逻辑分区。
- `Current`（当前）：代表当前玩家所处的游戏场景（战场、城镇等）。

这种分层设计让框架可以针对不同级别的场景做不同的处理（比如进程场景的资源不会被卸载，而当前场景切换时资源会释放）。

---

## 四、构造函数——在哪里初始化？

```csharp
public Root()
{
    this.Scene = EntitySceneFactory.CreateScene(0, SceneType.Process, "Process");
}
```

`Root` 在构造函数中创建了根场景。

**注意**：Zone 参数传的是 `0`，Name 是 `"Process"`，没有父节点（`parent = null`，使用默认值）。

这是有意义的：Process 场景是最顶层的，它没有父节点。

**什么时候 Root 被创建？**

通常在游戏启动时，框架会初始化所有单例：

```csharp
// 游戏启动代码（伪代码）
void Start()
{
    // 初始化所有单例，Root 在其中
    Game.AddSingleton<Root>();
    // ... 其他单例初始化
}
```

`Root` 一旦被创建，它的 `Scene` 就作为整个 ECS 世界的根存在，直到游戏关闭。

---

## 五、Dispose——资源清理的责任链

```csharp
public override void Dispose()
{
    this.Scene.Dispose();
}
```

当 `Root` 被销毁时，它负责销毁它所管理的 `Scene`。

**这里体现了一个重要的设计原则：谁创建，谁销毁。**

`Root` 在构造函数中创建了 `Scene`，所以在 `Dispose` 中负责销毁它。

`Scene.Dispose()` 会递归地销毁所有子场景和子实体——因为父节点被销毁时，所有子节点也应该被清理。

这构成了一个**责任链**：
```
Root.Dispose()
  → Scene.Dispose()
    → 子场景1.Dispose()
      → 子实体1.Dispose()
      → 子实体2.Dispose()
    → 子场景2.Dispose()
      → ...
```

整棵树在根节点被销毁时自动全部清理，不需要手动逐一清理。

---

## 六、Scene 属性的只读性

```csharp
public Scene Scene { get; }
```

`Scene` 属性只有 `get`，没有 `set`——一旦在构造函数中设置，就不能再改变。

**为什么根场景不应该被替换？**

根场景是整个实体树的锚点。如果根场景可以被替换，那么所有持有 `Root.Instance.Scene` 引用的代码都可能失效，整个系统的稳定性就无从保证。

这种设计叫做**不变性**（Immutability）——某些关键对象一旦初始化就不允许改变，保证系统的一致性。

---

## 七、实体树的实际应用

理解了 `Root` 的作用，我们来看它在实际游戏流程中的使用：

**游戏启动**：
```csharp
// 初始化根场景
Game.AddSingleton<Root>();
// Root 构造函数自动创建 Process 场景
```

**创建客户端场景**：
```csharp
// 在 Process 场景下创建 Client 场景
Scene clientScene = EntitySceneFactory.CreateScene(
    1, SceneType.Client, "Client", Root.Instance.Scene);
```

**查找根场景**：
```csharp
// 任何实体都可以找到根场景
Scene rootScene = entity.Root(); // 通过 SceneHelper 扩展方法
// 等价于 (Scene)entity.RootScene
```

**游戏关闭**：
```csharp
// 销毁 Root 会级联清理所有实体
Root.Instance.Dispose();
Game.RemoveSingleton<Root>();
```

---

## 八、Process 场景的特殊地位

`SceneType.Process` 场景之所以特殊，还在于它的 `Domain` 属性：

在 `Scene` 的构造函数中：
```csharp
this.Domain = this; // Scene 将自己设置为自己的 Domain
```

`Domain` 是"归属场景"的概念——每个实体都属于某个 Domain。

对于 Process 场景，它就是自己的 Domain。其他场景和实体的 Domain 最终追溯到它们直接所属的 Scene。

---

## 九、设计总结

`Root` 类的设计体现了几个核心原则：

| 原则 | 体现 |
|---|---|
| 单一根节点 | 单例模式，全局唯一 |
| 责任分明 | 构造函数创建，Dispose 销毁 |
| 不变性 | Scene 只读，根场景不可替换 |
| 级联清理 | Dispose 触发整棵树的清理 |
| 语义清晰 | SceneType.Process 明确表达"进程级" |

---

## 写给初学者

`Root` 是一个非常简洁的类，但它的设计思想值得深入理解：

**为什么需要一个"根"？**

数据结构中，树形结构需要根节点。游戏中的实体树也一样——有了根，才能进行统一管理（遍历所有实体、级联销毁、查找父节点等）。

**单例的争议**

单例模式有很多争议（难以测试、隐式依赖等），但在"进程全局唯一"的场景下（比如游戏的根场景），单例是合理的选择。

理解每个设计模式的适用场景，而不是教条地"单例有害"或"单例很好"——这是成熟工程师的判断力。
