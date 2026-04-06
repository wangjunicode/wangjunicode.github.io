---
title: 对象基类与可销毁对象——ECS 对象层次结构的设计哲学
published: 2026-03-31
description: 深入解析 Object 基类和 DisposeObject 的设计，理解 IDisposable 模式在游戏开发中的应用、ISupportInitialize 接口的语义，以及 IPool 接口在对象池复用中的关键作用。
tags: [Unity, ECS, 对象设计, 对象池, IDisposable]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# 对象基类与可销毁对象——ECS 对象层次结构的设计哲学

## 前言

在面向对象设计中，类的继承层次需要精心设计。今天我们来分析 ECS 框架中最底层的两个类：`Object` 和 `DisposeObject`。

虽然它们看起来极其简单，但它们是整个框架对象体系的基础。

```csharp
// Object.cs
public abstract class Object { }

// DisposeObject.cs
public abstract class DisposeObject: Object, IDisposable, ISupportInitialize
{
    public virtual void Dispose() { }
    public virtual void BeginInit() { }
    public virtual void EndInit() { }
}

public interface IPool
{
    bool IsFromPool { get; set; }
}
```

---

## 一、Object——最简洁的基类

```csharp
public abstract class Object { }
```

三个词组成一个类：`public abstract class Object`。

它什么都不做，什么都不定义，只是存在。

**为什么需要这样一个空的基类？**

### 1.1 统一继承树的根

有了 `Object` 基类，框架中所有重要的类都有一个共同祖先：

```
Object
├── DisposeObject
│   └── Entity（实体）
└── Singleton<T>（单例）
```

这使得类型过滤和反射操作更容易：

```csharp
// 检查某个类型是否是框架对象
bool isFrameworkObject = typeof(Object).IsAssignableFrom(someType);
```

### 1.2 为什么用 abstract？

`abstract` 表示 `Object` 不能被直接实例化（`new Object()` 会报错）。

这是正确的设计——没有人需要一个"纯粹的 Object 实例"。所有实例都应该是具体的子类（Entity、Singleton 等）。

### 1.3 不继承 System.Object 的命名选择

.NET 中所有类都隐式继承 `System.Object`（有 `ToString`、`Equals`、`GetHashCode` 等方法）。

这里的 `ET.Object` 是另一个类，通过命名空间区分：

```csharp
// 框架的 Object
ET.Object myObj = ...;

// .NET 的 Object（通常省略命名空间）
System.Object obj = ...;
```

框架的 `Object` 没有任何行为，比 `System.Object` 更纯粹。

---

## 二、DisposeObject——可销毁资源的基类

```csharp
public abstract class DisposeObject: Object, IDisposable, ISupportInitialize
{
    public virtual void Dispose() { }
    public virtual void BeginInit() { }
    public virtual void EndInit() { }
}
```

### 2.1 IDisposable——资源清理的标准接口

```csharp
public abstract class DisposeObject: Object, IDisposable
```

`IDisposable` 是 .NET 的标准接口，定义了 `Dispose()` 方法。

实现了 `IDisposable` 的对象可以：
1. 被 `using` 语句管理（自动调用 Dispose）
2. 被垃圾回收器在终结时处理

**在游戏 ECS 中的特殊含义**：

Entity 继承自 `DisposeObject`，调用 `entity.Dispose()` 不是 GC 相关的操作，而是"从 ECS 框架中注销、放回对象池"的操作。

这是一种语义重用——借用了 .NET 的 `IDisposable` 接口，但赋予了游戏特定的含义。

**`virtual void Dispose()` 的默认空实现**：

```csharp
public virtual void Dispose() { }
```

不是 `abstract`（不强制子类实现），而是 `virtual`（允许子类覆写）。

原因：不是所有子类都需要自定义销毁逻辑。Entity 的 Dispose 由框架统一处理，子类不需要（通常也不应该）覆写它。

### 2.2 ISupportInitialize——两阶段初始化接口

```csharp
public interface ISupportInitialize
{
    void BeginInit();
    void EndInit();
}
```

`ISupportInitialize` 是 .NET Framework 中 `System.ComponentModel` 命名空间的接口，用于支持"批量属性设置"的两阶段初始化模式。

**设计背景**：当一个对象有多个属性需要设置，且每次设置都可能触发验证/重绘时，批量设置完再"应用"会更高效：

```csharp
// 不好的方式：每设置一个属性就触发一次更新
entity.SetX(10);     // 触发更新
entity.SetY(20);     // 触发更新
entity.SetZ(30);     // 触发更新

// 好的方式：批量设置，最后一次触发
entity.BeginInit();  // 暂停自动更新
entity.SetX(10);     // 不触发
entity.SetY(20);     // 不触发
entity.SetZ(30);     // 不触发
entity.EndInit();    // 批量应用所有变更
```

在 ECS 框架中，这主要用于数据导入/序列化场景：

```csharp
// 从存档恢复实体
entity.BeginInit();
// ... 批量设置大量字段
entity.EndInit(); // 统一初始化完成
```

---

## 三、IPool——对象池的标记接口

```csharp
public interface IPool
{
    bool IsFromPool { get; set; }
}
```

`IPool` 是对象池复用的关键接口：

### 3.1 IsFromPool 的作用

```csharp
bool IsFromPool { get; set; }
```

这个属性记录"这个对象是从对象池取出来的，还是 new 出来的"。

**为什么需要知道这个？**

在对象的销毁逻辑中：

```csharp
public virtual void Dispose()
{
    // ... 清空数据
    
    if (this.IsFromPool)
    {
        ObjectPool.Instance.Recycle(this); // 从池中取出的，放回池
    }
    // 不从池中取出的，什么都不做，让 GC 回收
}
```

- 从对象池取出：销毁时放回池（复用）
- 直接 new：销毁时让 GC 回收（正常内存管理）

如果没有这个标记，放回池的判断就需要额外的逻辑（比如检查池中是否有这个对象，开销更大）。

### 3.2 对象池复用的完整流程

```csharp
// 从池中创建（推荐方式）
Entity entity = ObjectPool.Instance.Fetch<Player>();
entity.IsFromPool = true; // 标记

// 使用...

// 销毁（放回池）
entity.Dispose(); // 内部根据 IsFromPool 决定是 Recycle 还是让 GC 回收
```

---

## 四、继承层次的价值

将这些类的继承关系串起来：

```
System.Object（所有.NET对象的根）
    └── ET.Object（框架对象的根，抽象）
            └── ET.DisposeObject（可销毁对象，实现 IDisposable + ISupportInitialize）
                    └── ET.Entity（ECS 实体）
```

每层继承都有其意义：

- `ET.Object`：标记"这是框架内的对象"
- `DisposeObject`：标记"这个对象有生命周期，需要显式清理"
- `Entity`：ECS 实体，有父子关系、组件系统等

---

## 五、为什么不直接让 Entity 继承 IDisposable？

看起来可以这样做：

```csharp
// 简化版
public class Entity: IDisposable { ... }
```

但通过 `DisposeObject` 中间层，获得了：

1. **`BeginInit/EndInit`**：批量初始化支持（通过 ISupportInitialize）
2. **层次清晰**：`DisposeObject` 是"可销毁对象"的通用概念，不只是 Entity 可以用
3. **重用性**：其他非实体对象（如某些管理类）也可以继承 `DisposeObject` 获得相同的生命周期能力

---

## 六、写给初学者

`Object` 和 `DisposeObject` 是极简的类，但它们体现了几个重要设计原则：

1. **单一职责**：`Object` 只做"作为基类"这一件事，不多不少
2. **可扩展性**：`virtual Dispose()` 而非 `abstract`，子类可以不关心销毁细节
3. **标准接口**：借用 .NET 标准接口（`IDisposable`、`ISupportInitialize`），而非重复造轮子
4. **对象池标记**：`IPool` 让对象知道自己的来源，简化池管理逻辑

复杂的框架总是建立在这些简单基础之上。理解这些"小积木"，才能真正理解整个大厦。
