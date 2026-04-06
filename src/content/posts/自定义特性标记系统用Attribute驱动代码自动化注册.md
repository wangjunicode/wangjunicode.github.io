---
title: 自定义特性标记系统——用 Attribute 驱动代码自动化注册
published: 2026-03-31
description: 深度解析 EntitySystemAttribute 的设计原理，理解 C# 特性（Attribute）如何与反射配合实现代码自动化发现和注册，掌握 ECS 框架的元编程基础。
tags: [Unity, ECS, 反射, 特性, 元编程]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 自定义特性标记系统——用 Attribute 驱动代码自动化注册

## 前言

你有没有见过这种代码：

```csharp
[EntitySystem]
private static void Awake(this Player self)
{
    // 初始化逻辑
}
```

那个 `[EntitySystem]` 标签是什么？它怎么起作用的？

今天我们来深入分析 `EntitySystemAttribute`，理解 C# 特性（Attribute）的工作原理，以及它如何让框架实现"写了方法，系统自动知道并调用它"的魔法。

```csharp
using System;

namespace ET
{
    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method)]
    public class EntitySystemAttribute: BaseAttribute
    {
    }
}
```

---

## 一、什么是 C# 特性（Attribute）？

特性（Attribute）是 C# 的**元编程**工具——它允许你在代码上附加额外的描述信息，这些信息可以在运行时通过反射读取。

**类比**：想象你是仓库管理员，货物上贴了不同的标签：
- "易碎" → 搬运时要小心
- "冷藏" → 放冷藏区
- "急件" → 优先处理

这些标签不改变货物本身，但告诉管理系统"该怎么对待这个货物"。

C# 的 Attribute 就是给代码贴标签，告诉框架"该怎么对待这段代码"。

---

## 二、EntitySystemAttribute 的定义

```csharp
[AttributeUsage(AttributeTargets.Class | AttributeTargets.Method)]
public class EntitySystemAttribute: BaseAttribute
{
}
```

虽然只有三行，但每一部分都很重要。

### 2.1 继承 BaseAttribute

```csharp
public class EntitySystemAttribute: BaseAttribute
```

`EntitySystemAttribute` 继承自 `BaseAttribute`，而不是直接继承 `System.Attribute`。

这说明框架有自己的特性基类体系。`BaseAttribute` 可能添加了一些通用功能，或者仅仅是为了在框架的反射扫描中快速过滤（只扫描继承自 `BaseAttribute` 的特性，而不是所有 `System.Attribute`）。

### 2.2 AttributeUsage 限制使用范围

```csharp
[AttributeUsage(AttributeTargets.Class | AttributeTargets.Method)]
```

`[AttributeUsage]` 本身也是一个特性，用来描述"这个特性可以用在哪里"：

- `AttributeTargets.Class`：可以标记类
- `AttributeTargets.Method`：可以标记方法
- `|`：或运算，两者都允许

如果你尝试把 `[EntitySystem]` 标记在字段或属性上，编译器会报错：

```csharp
[EntitySystem]
public int Health; // 编译错误！EntitySystem 不能用于字段
```

这是一种**编译期保护**，防止特性被错误使用。

**所有可用的 AttributeTargets**：
```
Class       - 类
Method      - 方法
Property    - 属性
Field       - 字段
Interface   - 接口
Struct      - 结构体
Assembly    - 程序集
Event       - 事件
Parameter   - 方法参数
ReturnValue - 返回值
All         - 所有目标
```

### 2.3 空的类体

```csharp
public class EntitySystemAttribute: BaseAttribute
{
    // 空的！
}
```

特性类体是空的，没有任何字段或方法。

这说明 `[EntitySystem]` 纯粹是一个**标记**（Marker），只表示"我是 EntitySystem 方法/类"，不携带任何额外信息。

与携带数据的特性对比：

```csharp
// 携带数据的特性
[SerializeField]                    // 标记型，无数据
[Range(0, 100)]                     // 携带数据：最小值0，最大值100
[Tooltip("这是玩家的生命值")]         // 携带数据：提示文本
[EntitySystem]                      // 标记型，无数据
```

---

## 三、框架如何使用这个特性？

`EntitySystemAttribute` 本身只是一个标记，它的价值在于框架在**启动时扫描所有程序集**，找到标有 `[EntitySystem]` 的方法，然后自动注册它们。

伪代码示意：

```csharp
// 框架启动时的扫描逻辑（伪代码）
public static void ScanAndRegister()
{
    foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
    {
        foreach (Type type in assembly.GetTypes())
        {
            foreach (MethodInfo method in type.GetMethods())
            {
                // 检查方法是否有 EntitySystemAttribute 标记
                if (method.GetCustomAttribute<EntitySystemAttribute>() != null)
                {
                    // 将这个方法注册到对应的 System 中
                    EventSystem.Register(method);
                }
            }
        }
    }
}
```

这就是**反射驱动注册**的核心思路：

1. 框架扫描程序集
2. 找到带有特定特性的代码
3. 自动完成注册/初始化

开发者只需要在方法上加一个 `[EntitySystem]`，框架就会自动处理剩下的事情。

---

## 四、实际使用示例

```csharp
// 在自己的系统文件中
public static partial class PlayerSystem
{
    [EntitySystem]
    private static void Awake(this Player self)
    {
        self.health = 100;
        self.name = "玩家";
        Log.Info("Player 创建完成");
    }
    
    [EntitySystem]
    private static void Update(this Player self)
    {
        // 每帧更新逻辑
        self.UpdateMovement();
    }
    
    [EntitySystem]
    private static void Destroy(this Player self)
    {
        Log.Info("Player 被销毁");
    }
}
```

框架扫描后，会自动在 `Player` 实体的 `Awake`、`Update`、`Destroy` 生命周期回调这些方法。

开发者不需要手动注册："框架，请在 Player Awake 时调用 PlayerSystem.Awake"——打上标签，框架自动知道。

---

## 五、与静态扩展方法的配合

注意上面的方法签名：

```csharp
private static void Awake(this Player self)
```

这是 C# 的**扩展方法**（Extension Method）：
- `static` 表示是静态方法
- `this Player self` 表示这是 `Player` 类型的扩展方法

扩展方法 + `[EntitySystem]` 特性，构成了 ECS 框架的核心模式：

1. **数据与逻辑分离**：`Player` 类只包含数据（字段）
2. **扩展方法**：在不修改 `Player` 类的情况下，为其添加逻辑
3. **特性标记**：告诉框架这些扩展方法是系统方法，需要在特定生命周期调用

这种设计极大地提高了代码的可维护性：添加新功能只需要新建文件，不需要修改核心类。

---

## 六、`[EntitySystem]` vs `[EnableMethod]`

代码中还出现了另一个特性 `[EnableMethod]`（在 `Scene.cs` 中）：

```csharp
[EnableMethod]
[DebuggerDisplay("ViewName,nq")]
[ChildOf]
public sealed class Scene: Entity, IDestroy
```

`[EnableMethod]` 和 `[EntitySystem]` 的作用范围不同：
- `[EntitySystem]` 用于**方法**，标记具体的系统处理函数
- `[EnableMethod]` 用于**类**，可能告诉框架"这个类的方法可以被热更新动态替换"

这体现了特性系统的灵活性：不同的特性类服务于不同的框架功能，但它们遵循相同的使用方式（方括号标记）。

---

## 七、特性的工作原理——深入反射机制

```csharp
// 特性在编译后，会作为元数据保存在程序集中
// 运行时通过反射可以读取

MethodInfo method = typeof(PlayerSystem).GetMethod("Awake");
EntitySystemAttribute attr = method.GetCustomAttribute<EntitySystemAttribute>();

if (attr != null)
{
    Console.WriteLine("这是一个 EntitySystem 方法，需要注册到框架中");
}
```

**反射的性能注意事项**：

反射操作（`GetType()`、`GetMethods()`、`GetCustomAttribute()`）比直接代码调用慢很多，因为它需要动态查询类型信息。

但注意：**框架扫描通常只在启动时执行一次**，扫描结果缓存在字典中。运行时实际调用时，使用的是缓存的结果（委托或方法指针），没有反射开销。

---

## 八、特性的命名约定

C# 约定：特性类名以 `Attribute` 结尾，但使用时可以省略 `Attribute`：

```csharp
// 完整名称
[EntitySystemAttribute]

// 简写（等价，更常用）
[EntitySystem]
```

编译器会自动尝试补全 `Attribute` 后缀。

---

## 九、框架中的特性体系

从本文分析的特性来看，框架中有一整套特性体系：

```
BaseAttribute（基类）
├── EntitySystemAttribute  - 标记 ECS 系统方法
├── EventAttribute         - 标记事件处理方法
├── InvokeAttribute        - 标记调用处理器
├── ObjectSystemAttribute  - 标记对象系统
└── ...更多
```

这套特性体系构成了框架的"声明式编程接口"：

开发者通过声明特性来表达意图，框架通过扫描特性来自动执行注册和调用。这是一种**约定优于配置**（Convention over Configuration）的设计哲学。

---

## 十、写给初学者

特性（Attribute）是 C# 高级特性中最重要的之一，很多框架都大量使用它：

- Unity 的 `[SerializeField]`、`[Range]`、`[Header]`
- ASP.NET 的 `[HttpGet]`、`[Authorize]`、`[Route]`
- Entity Framework 的 `[Table]`、`[Column]`、`[Key]`

理解特性的关键认知转变：

**从"代码告诉计算机做什么"，到"代码描述自己是什么，框架决定如何处理它"。**

这就是**元编程**的本质——用代码来描述代码，让框架根据描述自动生成行为。

掌握了这个思维，你会发现很多看起来"很神奇"的框架行为，其实都是反射 + 特性在背后工作。
