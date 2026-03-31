---
title: 实体分发组件与处理器模式——运行时的可扩展脚本派发系统
published: 2026-03-31
description: 深入解析 EntityDispatcherComponent 和 AHandler 的设计，理解基于反射的运行时 Handler 注册机制、泛型 Handler 的动态实例化，以及脚本系统与 ECS 框架的桥接模式。
tags: [Unity, ECS, 反射, 泛型, 脚本系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 实体分发组件与处理器模式——运行时的可扩展脚本派发系统

## 前言

在大型游戏中，不同类型的实体（敌人 AI、技能逻辑、任务系统）都需要"处理器"——一段处理该类实体的代码。

传统方式：硬编码 `if (entity is Enemy) { ... } else if (entity is Skill) { ... }`

更好的方式：通过类型查找对应的处理器，实现**数据驱动的分发**。

这就是 `EntityDispatcherComponent` 和 `AHandler` 的核心价值。

---

## 一、AHandler——处理器的抽象基类

```csharp
// HandlerAttribute：标记这是一个 Handler 类
public class HandlerAttribute: BaseAttribute { }

// 泛型 Handler 基类（带类型参数版本）
public abstract class AHandler<T>: AHandler { }

// 非泛型 Handler 基类
[Handler]
public abstract class AHandler { }
```

`AHandler` 是所有处理器的基类，通过 `[Handler]` 特性（即 `HandlerAttribute`）标记自己。

**为什么设计成空类？**

`AHandler` 的职责只是"成为基类"——建立继承层次。具体的"处理什么"由子类定义。

框架不规定处理器有什么方法，因为不同的处理器场景完全不同：
- AI 处理器：有 `Update`、`OnAttacked` 等方法
- 技能处理器：有 `OnActivate`、`OnTick` 等方法
- 任务处理器：有 `Check`、`Complete` 等方法

用一个共同基类而不是接口，是为了让 `Dictionary<Type, AHandler>` 能存储所有类型的处理器。

---

## 二、IHasHandler——声明实体有对应的处理器

```csharp
public interface IHasHandler
{
    T GetHandler<T>() where T : AHandler;
    bool TryGetHandler<T>(out T handler) where T : AHandler;
}
```

实现 `IHasHandler` 的实体声明"我有对应的处理器"。

**为什么用接口而不是直接调用 EntityDispatcherComponent？**

接口屏蔽了实现细节。调用方只需要：

```csharp
entity.GetHandler<SkillHandler>();
```

不需要知道背后是 `EntityDispatcherComponent.Instance.GetHandler<SkillHandler>(entity.GetType())`。

这是**迪米特法则**（最少知识原则）的体现：调用方只需要了解直接相关的接口，不需要了解整个处理器系统的细节。

---

## 三、EntityDispatcherComponent——处理器的中央注册表

```csharp
[ComponentOf(typeof(Scene))]
public class EntityDispatcherComponent: Entity, IAwake, IDestroy, ILoad
{
    [StaticField]
    public static EntityDispatcherComponent Instance;
    
    public Dictionary<Type, AHandler> Handlers = new();
    
    // 三种查询方式
    public T GetHandler<T>(Type entityType) where T: AHandler { ... }      // 泛型，找不到抛异常
    public AHandler GetHandler(Type entityType) { ... }                    // 非泛型，找不到抛异常
    public bool TryGetHandler(Type entityType, out AHandler handler) { ... } // 找不到返回 false
}
```

`Handlers = Dictionary<Type, AHandler>` 是处理器的注册表：

- 键：实体类型（`typeof(Player)`、`typeof(SkillScript)` 等）
- 值：对应的处理器实例

### 3.1 三种查询方式的设计

提供三个重载，覆盖不同的使用场景：

```csharp
// 确定存在时使用（找不到会崩溃提醒你）
T handler = component.GetHandler<SkillHandler>(typeof(SkillScript));

// 不确定是否存在时使用（安全查询）
if (component.TryGetHandler(typeof(SomeScript), out AHandler h))
{
    // 找到了
}
```

"确定存在就 GetHandler（抛异常快速定位问题），不确定就 TryGetHandler（安全处理）"——这是 C# 标准库的惯例设计（`Dictionary.TryGetValue` 的同款模式）。

---

## 四、LoadHandlers——反射动态加载处理器

```csharp
public static void LoadHandlers(IEnumerable<Type> types, Dictionary<Type, AHandler> handlers)
{
    foreach (var type in types)
    {
        if (type.IsAbstract) continue;
        
        if (type.ContainsGenericParameters) // 泛型 Handler 需要特殊处理
        {
            // ... 泛型 Handler 的动态实例化
            continue;
        }
        
        // 普通 Handler
        AHandler aHandler = Activator.CreateInstance(type) as AHandler;
        Type scriptType = type.BaseType.GetGenericArguments()[0]; // 从基类泛型参数获取脚本类型
        handlers.Add(scriptType, aHandler);
    }
}
```

**普通 Handler 的注册逻辑**：

通过反射读取 Handler 基类的泛型参数来确定它处理的脚本类型：

```csharp
// 例子：SkillScriptHandler 的定义
public class SkillScriptHandler: AHandler<SkillScript> { ... }

// 运行时推断：
type = typeof(SkillScriptHandler)
type.BaseType = typeof(AHandler<SkillScript>)
type.BaseType.GetGenericArguments()[0] = typeof(SkillScript) // 就是键
```

不需要在 Handler 上显式写 `[HandleType(typeof(SkillScript))]` 之类的特性，泛型参数本身就是元数据。

### 4.1 泛型 Handler 的动态实例化

```csharp
if (type.ContainsGenericParameters) // 未封闭的泛型类型
{
    if (typeof(IGenericEvtScriptHandler).IsAssignableFrom(type))
    {
        // 获取所有事件类型
        var lst = EventMap.GetEventTypes();
        foreach (var t in lst)
        {
            var stype = sDefinition.MakeGenericType(t);  // 实体类型
            var htype = hDefinition.MakeGenericType(t);  // Handler 类型
            handlers.Add(stype, Activator.CreateInstance(htype) as AHandler);
        }
    }
}
```

对于泛型 Handler（如 `class GenericHandler<T>: AHandler<SomeScript<T>>`），需要为每种类型参数创建一个实例：

```
GenericHandler<int> → 处理 SomeScript<int>
GenericHandler<string> → 处理 SomeScript<string>
```

`MakeGenericType(t)` 在运行时封闭泛型类型，`Activator.CreateInstance(htype)` 创建实例。

这实现了"**编写一次 Handler，自动处理所有类型变体**"。

---

## 五、EntityDispatcherComponentSystem——系统的生命周期

```csharp
[FriendOf(typeof(EntityDispatcherComponent))]
public static partial class EntityDispatcherComponentSystem
{
    [EntitySystem]
    private static void Awake(this EntityDispatcherComponent self)
    {
        EntityDispatcherComponent.Instance = self;
        self.Load(); // 立即加载所有 Handler
    }

    [EntitySystem]
    private static void Destroy(this EntityDispatcherComponent self)
    {
        self.Handlers.Clear();
        EntityDispatcherComponent.Instance = null;
    }

    [EntitySystem]
    private static void Load(this EntityDispatcherComponent self)
    {
        self.Handlers.Clear();
        var types = EventSystem.Instance.GetTypes(typeof(HandlerAttribute));
        // ... 调用 LoadHandlers
    }
}
```

**实现了 `ILoad` 接口**：当热更新发生时，`Load` 会被重新调用，重新扫描和注册所有 Handler。

这确保了热更新后，如果 Handler 的实现改变了，新的实现会被注册进来。

### FriendOf 特性

```csharp
[FriendOf(typeof(EntityDispatcherComponent))]
```

这是 ECS 框架定义的特性，表示这个系统类可以访问 `EntityDispatcherComponent` 的私有成员。

类似 C++ 的 `friend` 关键字，但通过特性实现，比 C++ 更灵活（可以在编译期生效也可以在运行时标记）。

---

## 六、HandlerHelper——多环境的处理器查找

```csharp
public static class HandlerHelper
{
    // 主要入口：优先通过 EntityDispatcherComponent（运行时）
    // 回退：直接反射扫描（编辑器/单测环境）
    public static bool TryGetHandler<T>(Type baseType, out T handler) where T: AHandler
    {
        handler = null;
        if (EntityDispatcherComponent.Instance != null)
        {
            return EntityDispatcherComponent.Instance.TryGetHandler<T>(baseType, out handler);
        }

        // EntityDispatcherComponent 不存在时，直接反射查找（编辑器工具等场景）
        if (handlers.Count == 0)
        {
            // 扫描所有带 [Handler] 特性的类...
        }
        // ...
    }
}
```

`HandlerHelper` 实现了双模式查找：

1. **运行时模式**（游戏运行中）：通过 `EntityDispatcherComponent.Instance` 快速查找（O(1)）
2. **离线模式**（编辑器工具、单元测试）：直接反射扫描，无需 EntityDispatcherComponent

这种**优雅降级**设计，让同一套 API 在游戏运行时和工具代码中都能使用。

---

## 七、设计总结

这套 Handler 体系的设计亮点：

| 特性 | 实现 |
|---|---|
| 类型安全 | 泛型 `GetHandler<T>` 返回正确类型 |
| 运行时发现 | 通过 `[HandlerAttribute]` 反射注册 |
| 热更新支持 | 实现 `ILoad`，热更后重新注册 |
| 泛型 Handler | 动态实例化，一次编写覆盖多类型 |
| 优雅降级 | HandlerHelper 支持有无 EntityDispatcherComponent 两种模式 |
| 快速失败 | GetHandler 找不到时抛异常，TryGetHandler 返回 false |

---

## 写给初学者

这套处理器模式体现了"数据驱动"的设计思想：

**不是"代码调用处理器"，而是"类型决定处理器"。**

这个思想在游戏开发中非常有价值：
- 策划配置了一种新类型的技能脚本
- 程序员只需要写对应的 Handler，带上 `[Handler]` 特性
- 框架自动发现并注册，无需修改任何其他代码

开放-关闭原则（对扩展开放，对修改关闭）在这里得到了完美体现。
