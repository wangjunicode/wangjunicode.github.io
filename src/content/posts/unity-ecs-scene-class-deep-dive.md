---
title: 场景实体深度解析——ECS 框架中 Scene 的双重角色与生命周期
published: 2026-03-31
description: 从架构设计角度深度解析 Scene 类的双重身份（实体 + 容器），理解 Domain 自引用、Parent 覆写、sealed 密封类设计以及调试器展示的工程实践。
tags: [Unity, ECS, 场景架构, 生命周期, 设计模式]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 场景实体深度解析——ECS 框架中 Scene 的双重角色与生命周期

## 前言

之前我们从"工厂"和"辅助工具"的角度分析了场景。今天换一个视角——深入 `Scene` 类本身的实现细节，理解它作为 ECS 框架中最特殊实体的独特设计。

```csharp
[EnableMethod]
[DebuggerDisplay("ViewName,nq")]
[ChildOf]
public sealed class Scene: Entity, IDestroy
```

三个特性标记、一个密封声明、继承 `Entity` 同时实现 `IDestroy`……这开头就很有意思。

---

## 一、Scene 的双重身份

**Scene 既是实体，又是容器。**

它继承自 `Entity`，拥有所有实体的属性（Id、InstanceId、父子关系等）。同时，它又是其他实体的"家"——其他实体挂载在场景下，场景管理它们的生命周期。

这种"元素也可以是容器"的设计，在软件工程中叫做**组合模式**（Composite Pattern）：

```
Entity（单纯实体）
Scene（实体 + 容器）= Entity + Children 管理能力
```

文件树结构也是同样的模式：文件是叶节点，目录是容器节点，但目录本身也可以是另一个目录的子节点。

---

## 二、sealed——为什么不允许继承？

```csharp
public sealed class Scene: Entity, IDestroy
```

`sealed` 关键字禁止其他类继承 `Scene`。

**设计意图**：

场景是框架的基础设施，它的行为必须可预测。如果允许继承，子类可能覆写关键方法（如 `Parent`、`Domain`），破坏场景树的一致性。

用 `sealed` 是在说："场景就是场景，不需要也不允许有'特殊场景'这种东西。"

如果不同类型的场景需要不同行为，应该通过**组件**（Component）来扩展，而不是通过继承：

```csharp
// 正确方式：给场景加组件
scene.AddComponent<BattleSceneComponent>();

// 错误方式（被禁止）：继承 Scene
class BattleScene: Scene { ... } // 编译错误！
```

**`sealed` 的性能优势**：

密封类的虚方法调用不需要虚表查找，编译器可以内联，有微小的性能提升。对于 ECS 这种高频调用的框架来说，每一点优化都值得。

---

## 三、三个特性标记的含义

```csharp
[EnableMethod]      // 允许方法被热更动态替换
[DebuggerDisplay("ViewName,nq")]  // 调试器显示
[ChildOf]           // 可以作为其他场景的子节点
```

### 3.1 [EnableMethod]

表示该类的方法支持热更新动态替换。在支持热更新的框架中，这是很重要的标记——告诉热更系统"这个类的方法在运行时可以被新实现替换"。

### 3.2 [DebuggerDisplay("ViewName,nq")]

这是 .NET 提供的调试器显示特性：

```csharp
[DebuggerDisplay("ViewName,nq")]
```

- `ViewName`：使用 `ViewName` 属性的值作为调试器显示文本
- `nq`：no quotes，不加引号

在 Visual Studio 或 Rider 中，当你 hover 一个 `Scene` 对象时，显示的不是 `{ET.Scene}` 这种默认格式，而是场景的 `ViewName`（比如 `Scene (Client)`）。

这是一个细节，但对调试体验影响很大。

### 3.3 [ChildOf]

标记这个类可以作为某种实体的子节点（Components 或 Children）。框架用这个特性来验证实体树的合法性。

---

## 四、Domain 的自引用设计

```csharp
public new Entity Domain
{
    get => this.domain;
    set => this.domain = value;
}
```

`Scene` 覆写了 `Entity` 的 `Domain` 属性，使用 `new` 关键字（而非 `override`）隐藏了父类的实现。

在构造函数中：

```csharp
this.Domain = this; // 场景将自己设置为自己的 Domain
```

这是一个关键设计：**Scene 是自己的 Domain**。

**为什么？**

`Domain` 的语义是"实体所属的场景"。Scene 本身就是一个场景，所以它所属的"场景"就是它自己。

这使得 `entity.DomainScene()` 的实现非常简单：
```csharp
public static Scene DomainScene(this Entity entity)
{
    return (Scene) entity.Domain;
}
```

对于普通实体，`Domain` 指向它所在的场景；对于 `Scene` 本身，`Domain` 就是它自己。整个体系自洽。

---

## 五、Parent 属性的覆写

```csharp
public new Entity Parent
{
    get
    {
        return this.parent;
    }
    set
    {
        if (value == null)
        {
            return;
        }
        this.parent = value;
        this.parent.Children.Add(this.Id, this);
    }
}
```

`Scene` 覆写了 `Parent` 属性，添加了一个重要逻辑：**当设置父节点时，自动将自己添加到父节点的 Children 字典中**。

```csharp
this.parent.Children.Add(this.Id, this);
```

这使得父子关系建立时的一致性由场景自己保证，调用方不需要手动维护双向关系。

**null 值的特殊处理**：

```csharp
if (value == null)
{
    return; // 不处理 null，保持 parent 不变
}
```

注意注释掉的代码：
```csharp
// this.parent = this;
```

这段被注释的代码原本的意图可能是"没有父节点时，父节点指向自己"（类似 Domain 的自引用）。但这样会导致层级遍历时出现无限循环，所以被注释掉了，改为直接返回。

这个注释是很好的"历史痕迹"——保留了设计演化的轨迹。

---

## 六、两个构造函数的区别

```csharp
// 构造函数1：id 和 instanceId 相同（简化版）
public Scene(long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = instanceId;
    this.InstanceId = instanceId;
    // ...
}

// 构造函数2：id 和 instanceId 分离（完整版）
public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = id;
    this.InstanceId = instanceId;
    // ...
}
```

两个构造函数的区别在于 `Id` 和 `InstanceId` 是否相同。

**第一个**：适合本地创建的场景（客户端创建，ID 由本地生成）
**第二个**：适合需要精确控制 ID 的场景（比如服务器指定了 ID，客户端同步时需要保持一致）

---

## 七、构造函数中的完整初始化序列

```csharp
public Scene(long id, long instanceId, int zone, SceneType sceneType, string name, Entity parent)
{
    this.Id = id;
    this.InstanceId = instanceId;
    this.Zone = zone;
    this.SceneType = sceneType;
    this.Name = name;
    this.IsCreated = true;    // 标记：已创建
    this.IsNew = true;        // 标记：是新建的
    this.Parent = parent;     // 设置父节点（触发 Children.Add）
    this.Domain = this;       // 自引用 Domain
    this.IsRegister = true;   // 注册到全局追踪系统
    Log.Info($"scene create: {this.SceneType} {this.Name} {this.Id}...");
}
```

这个序列展示了创建一个场景的完整步骤：

1. 设置标识信息（Id、Zone、类型、名称）
2. 标记状态（IsCreated、IsNew）
3. 建立父子关系（Parent）
4. 设置 Domain 自引用
5. 注册到全局系统（IsRegister）
6. 打印日志

**每一步的顺序都有意义**：

`Parent` 必须在 `Domain` 之前设置，因为普通实体的 `Domain` 是从父节点继承的。但 `Scene` 的 `Domain` 是自己，所以顺序影响不大。

`IsRegister = true` 触发实体注册到全局管理（方便后续通过 ID 查找），放在最后保证其他字段已经初始化完毕。

---

## 八、Destroy 系统钩子

```csharp
public static partial class SceneSystem
{
    [EntitySystem]
    private static void Destroy(this Scene self)
    {
        Log.Info($"scene dispose: {self.SceneType} {self.Name} {self.Id} ...");
    }
}
```

当 `Scene` 被销毁时，框架会调用这个 `Destroy` 方法。

目前只是打印日志，但它是一个扩展点：如果将来需要在场景销毁时做清理（断开网络连接、释放资源等），可以在这里添加。

`IDestroy` 接口是框架的生命周期约定：实现了 `IDestroy` 的实体，在被销毁时会自动调用其 `Destroy` 系统方法。

---

## 九、ViewName 的覆写

```csharp
protected override string ViewName
{
    get
    {
        return $"{this.GetType().Name} ({this.SceneType})";    
    }
}
```

`Scene` 覆写了父类的 `ViewName`，格式是"类名 (场景类型)"：

```
"Scene (Process)"
"Scene (Client)"
"Scene (Current)"
```

配合之前分析的 `GetDebugString()`，场景的路径看起来像：

```
Scene (Client) -> Scene (Current) -> Player
```

清晰展示了实体在哪个场景层级下。

---

## 十、Scene 类与普通 Entity 的对比

| 特性 | 普通 Entity | Scene |
|---|---|---|
| 可继承 | 通常可以 | 不可（sealed） |
| Domain | 指向所在场景 | 指向自己 |
| Parent | 直接赋值 | 赋值 + 维护 Children |
| InstanceId | 通常与 Id 不同 | 可以相同（简化版） |
| Destroy 钩子 | 可选 | 必须（实现 IDestroy） |

---

## 写给初学者

`Scene` 类的设计体现了几个高级工程技巧：

1. **sealed 的用法**：不是所有类都应该允许继承。关键基础设施类用 sealed 保护稳定性。

2. **new vs override**：覆写父类成员时，`override` 是多态覆写（运行时动态分发），`new` 是隐藏（编译时静态分发）。`Scene.Domain` 用 `new` 是因为它改变了 Domain 的语义（自引用），而不只是改变实现。

3. **构造函数的完整性**：构造函数结束时，对象应该处于完整、一致的状态。`Scene` 的构造函数在返回前完成了所有必要的初始化。

4. **自引用的哲学**：`this.Domain = this` 这种自引用看起来奇怪，但在树形结构的根节点上是自然的——"我的归宿就是我自己"。
