---
title: 调用处理器机制——IInvoke 与 InvokeAttribute 的精准分发设计
published: 2026-03-31
description: 深入解析 IInvoke 接口族和 InvokeAttribute 的设计，理解 Invoke 与 Publish 的本质区别、结构体消息的性能优势，以及如何用类型+整数 ID 实现精准的调用分发。
tags: [Unity, ECS, 调用分发, 结构体, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 调用处理器机制——IInvoke 与 InvokeAttribute 的精准分发设计

## 前言

上篇文章我们分析了 `IEvent`（事件发布）。今天分析相关但本质不同的 `IInvoke`（调用处理）。

理解两者的区别，对于正确设计模块间通信至关重要。

```csharp
// IInvoke.cs
public abstract class AInvokeHandler<A>: IInvoke where A: struct
{
    public Type Type => typeof(A);
    public abstract void Handle(A a);
}
```

---

## 一、AInvokeHandler——精准调用的处理器

```csharp
public interface IInvoke
{
    Type Type { get; }
}

public abstract class AInvokeHandler<A>: IInvoke where A: struct
{
    public Type Type => typeof(A);
    public abstract void Handle(A a);
}

public abstract class AInvokeHandler<A, T>: IInvoke where A: struct
{
    public Type Type => typeof(A);
    public abstract T Handle(A a);
}
```

两个泛型版本：
- `AInvokeHandler<A>`：无返回值的调用处理器（类似 `void` 函数）
- `AInvokeHandler<A, T>`：有返回值的调用处理器（类似有返回值的函数）

### 1.1 where A: struct——为什么参数必须是结构体？

```csharp
where A: struct
```

与 `ATimer<T>` 的 `where T: class` 相反，`IInvoke` 的参数要求是**结构体**（值类型）。

**原因**：

Invoke 的调用非常频繁（比如定时器每次触发）。如果参数是引用类型（class），每次调用都要在堆上分配一个对象，造成 GC 压力。

结构体（struct）在栈上分配，传递时是值复制，不产生 GC 分配：

```csharp
// struct：栈上分配，传值，无 GC
public struct TimerCallback
{
    public object Args; // Args 可以是引用类型，但包装体是 struct
}

// 调用时
EventSystem.Instance.Invoke(timerType, new TimerCallback { Args = data });
// new struct 在栈上，函数返回后自动回收，无需 GC
```

这是一个重要的性能优化。

---

## 二、InvokeAttribute——类型+整数 ID 的双维度分发

```csharp
public class InvokeAttribute: BaseAttribute
{
    public int Type { get; }

    public InvokeAttribute(int type = 0)
    {
        this.Type = type;
    }
}
```

`InvokeAttribute` 接受一个 `int type` 参数（默认为 0）。

这个整数 ID 允许**同一种消息类型注册多个不同的处理器**：

```csharp
// 不同的定时器类型，使用相同的 TimerCallback 结构，但不同的 type ID
[Invoke(TimerType.MonsterRespawn)]
public class MonsterRespawnTimer: AInvokeHandler<TimerCallback>
{
    public override void Handle(TimerCallback a)
    {
        RespawnManager.RespawnMonster(a.Args as MonsterData);
    }
}

[Invoke(TimerType.BuffExpire)]
public class BuffExpireTimer: AInvokeHandler<TimerCallback>
{
    public override void Handle(TimerCallback a)
    {
        BuffManager.ExpireBuff(a.Args as BuffData);
    }
}
```

两个处理器都处理 `TimerCallback`，但通过不同的 `type` ID 区分。

---

## 三、EventSystem 中的注册和查找

```csharp
// 注册（EventSystem.Add 时）
this.allInvokes = new Dictionary<Type, Dictionary<int, object>>();
foreach (var type in types[typeof(InvokeAttribute)])
{
    object obj = Activator.CreateInstance(type);
    IInvoke iInvoke = obj as IInvoke;
    
    object[] attrs = type.GetCustomAttributes(typeof(InvokeAttribute), false);
    foreach (object attr in attrs)
    {
        if (!this.allInvokes.TryGetValue(iInvoke.Type, out var dict))
        {
            dict = new Dictionary<int, object>();
            this.allInvokes.Add(iInvoke.Type, dict);
        }
        InvokeAttribute invokeAttribute = attr as InvokeAttribute;
        dict.Add(invokeAttribute.Type, obj);
    }
}
```

数据结构是二维字典：

```
allInvokes:
  typeof(TimerCallback) → {
    TimerType.MonsterRespawn → MonsterRespawnTimer 实例
    TimerType.BuffExpire     → BuffExpireTimer 实例
  }
  typeof(ConfigLoadArg) → {
    0 → DefaultConfigLoader 实例
  }
```

### 3.1 调用时的查找

```csharp
public void Invoke<A>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers))
    {
        throw new Exception($"Invoke error: {typeof(A).Name}"); // 必须有处理器！
    }

    if (!invokeHandlers.TryGetValue(type, out var invokeHandler))
    {
        throw new Exception($"Invoke error: {typeof(A).Name} {type}"); // 必须有对应 ID！
    }

    var aInvokeHandler = invokeHandler as AInvokeHandler<A>;
    aInvokeHandler.Handle(args);
}
```

**注意**：`Invoke` 找不到处理器时会**抛出异常**。

这是 `Invoke` 和 `Publish` 最大的语义区别：

- `Publish` 找不到订阅者：静默返回（事件可以无人订阅）
- `Invoke` 找不到处理器：抛出异常（调用必须有被调用方）

---

## 四、有返回值的调用

```csharp
public abstract class AInvokeHandler<A, T>: IInvoke where A: struct
{
    public Type Type => typeof(A);
    public abstract T Handle(A a);
}
```

带返回值版本允许"函数式调用"：

```csharp
// 示例：根据配置类型获取对应的加载器
public struct GetLoaderArg { public string ConfigType; }

[Invoke(0)]
public class ConfigLoaderSelector: AInvokeHandler<GetLoaderArg, IConfigLoader>
{
    public override IConfigLoader Handle(GetLoaderArg a)
    {
        return a.ConfigType switch
        {
            "json" => new JsonLoader(),
            "csv"  => new CsvLoader(),
            _      => throw new Exception($"未知配置类型: {a.ConfigType}")
        };
    }
}

// 调用
IConfigLoader loader = EventSystem.Instance.Invoke<GetLoaderArg, IConfigLoader>(
    0, new GetLoaderArg { ConfigType = "json" }
);
```

这类似**策略模式**：根据参数决定用哪个策略对象，但由框架负责查找。

---

## 五、框架注释揭示的设计哲学

框架代码中有一段精辟的注释：

```
// Invoke类似函数，必须有被调用方，否则异常
// 调用者和被调用者属于同一模块
// 比如MoveComponent中的Timer计时器，调用和被调用的代码均属于移动模块
//
// 既然Invoke像函数，为什么不直接用函数？
// 因为有时候不方便直接调用：
//   - Config加载，客户端和服务端加载方式不一样
//   - TimerComponent需要根据Id分发
//
// 注意，不要把Invoke当函数使用，这样会造成代码可读性降低
// 能用函数不要用Invoke
```

这段注释非常清晰地划定了 `Invoke` 的使用边界：

**应该用 Invoke 的场景**：
1. 同一模块内，但调用方和实现方在不同类/程序集中
2. 需要根据类型/ID 动态分发（如定时器回调）
3. 客户端/服务端有不同实现（需要运行时选择）

**不应该用 Invoke 的场景**：
1. 能直接调用的地方（直接函数调用可读性更好）
2. 跨模块通信（用 `Publish` 代替）

---

## 六、定时器系统中的 Invoke 应用

回顾 `LogicTimerComponent` 中的定时器触发：

```csharp
case TimerClass.OnceTimer:
{
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    timerAction.Recycle();
    break;
}
```

`timerAction.Type` 是一个整数 ID（如 `TimerType.MonsterRespawn`），`TimerCallback` 是消息体。

这样设计的好处：
- `LogicTimerComponent` 不需要知道定时器触发后要做什么
- 不同类型的定时器有不同的处理器
- 处理器由各自的模块定义，完全解耦

---

## 七、struct 的性能深入分析

```csharp
where A: struct
```

struct 在 Invoke 中的性能优势：

```csharp
// 实际调用
EventSystem.Instance.Invoke(type, new TimerCallback { Args = data });
```

`new TimerCallback { ... }` 创建的是结构体，在**调用栈**上分配，方法返回后自动释放，不进入 GC 堆。

如果是 class：
```csharp
EventSystem.Instance.Invoke(type, new TimerCallbackClass { Args = data });
// 每次 Invoke 在堆上分配一个对象 → GC 压力
```

对于每秒可能触发几千次的定时器，这个优化非常显著。

---

## 八、设计总结

| 特性 | IInvoke | IEvent |
|---|---|---|
| 参数约束 | struct（值类型） | 无约束 |
| 无处理器时 | 抛出异常 | 静默 |
| 返回值 | 支持（AInvokeHandler<A, T>） | 不支持 |
| 分发维度 | 类型 + 整数 ID | 类型 + SceneType |
| 适用关系 | 同模块，精准调用 | 跨模块，广播 |

---

## 写给初学者

`IInvoke` 和 `IEvent` 共同构成了 ECS 框架的通信体系：

- **IInvoke**：内部机制，精准调用，类似"打电话"（必须有人接）
- **IEvent**：外部通知，广播事件，类似"发广播"（可以没人听）

选择哪个，取决于：
1. 调用者是否知道/关心被调用者的存在？（知道→Invoke，不知道→Publish）
2. 是否需要返回值？（需要→Invoke，不需要→都可以）
3. 是否必须有处理器？（必须→Invoke，可选→Publish）

理解这个区别，是写出设计良好的游戏架构的关键一步。
