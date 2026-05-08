---
title: xgame框架IEvent与AEvent事件抽象层深度解析-同步异步双模式事件基类与SceneType场景感知分发机制设计
date: 2026-05-08
tags:
  - Unity
  - xgame框架
  - 事件系统
  - 异步编程
  - ECS
categories:
  - 技术
description: 深入解析xgame框架中IEvent接口与AEvent/AAsyncEvent事件抽象基类的设计，剖析EventAttribute场景类型感知注册、IInvoke与AInvokeHandler精准分发机制、AEvent同步处理与AAsyncEvent异步处理双模式、以及EventSystem.Publish与Invoke的职责边界划分，结合BaseInvokeArg资源加载协调结构体与SceneType枚举的工程设计。
encryptedKey: henhaoji123
---

xgame 框架的事件系统在 `EventSystem` 之上抽象了一套以 `IEvent`、`AEvent`、`AAsyncEvent` 为核心的事件处理体系。与常见的 C# `event` 委托不同，这套设计将事件类型、处理器、Scene 作用域三者紧密结合，实现了热重载友好、场景隔离、同步异步双驱动的工业级事件总线。本文将从源码出发，完整解析这套抽象层的设计意图与工程实践。

---

## 一、IEvent 接口：类型标识契约

```csharp
public interface IEvent
{
    Type Type { get; }
}
```

`IEvent` 是所有事件处理器的根接口，只有一个 `Type` 属性，用于声明"本处理器处理哪种事件类型"。这种设计使 `EventSystem` 能在不依赖泛型的前提下，统一管理所有类型的事件处理器。

框架中还定义了两个辅助标记接口，用于区分两类事件参数的来源：

```csharp
// EventDispatcher 路由事件（组件内部分发）
public interface IEventDispatcherArg { }

// EventSystem 全局事件
public interface IEventSystemArg { }
```

这两个标记接口目前仅作为语义约束，帮助 Roslyn 静态分析器识别事件数据结构的归属。

---

## 二、AEvent：同步事件处理基类

```csharp
public abstract class AEvent<A> : IEvent
{
    public Type Type => typeof(A);  // 自动从泛型参数推断事件类型

    protected abstract void Run(Scene scene, A evt);

    public virtual void Handle(Scene scene, A evt)
    {
        try
        {
            Run(scene, evt);
        }
        catch (Exception e)
        {
            Log.Error(e);
        }
    }
}
```

### 2.1 设计亮点

**泛型参数即类型键**：`Type` 属性直接返回 `typeof(A)`，无需手动指定，泛型参数天然成为事件的注册键。这意味着在 `EventSystem.allEvents` 字典中，`Dictionary<Type, List<EventInfo>>`，事件类型 `A` 就是 Key。

**Scene 作为上下文**：每个处理方法都接收 `Scene scene` 参数，而非全局单例。这是 xgame 框架"以 Scene 为隔离域"设计哲学的体现——相同事件在不同 Scene 中可以有不同的处理逻辑，互不干扰。

**异常隔离**：`Handle()` 方法包裹了 try-catch，确保单个处理器异常不会导致整个事件链中断。子类通过 `Run()` 实现业务逻辑，Handle() 负责安全执行。

### 2.2 使用示例

```csharp
// 定义事件数据（结构体，零 GC）
public struct OnPlayerDead
{
    public long PlayerId;
    public int Reason;
}

// 实现处理器
[Event(SceneType.Current)]
public class OnPlayerDead_BattleHandler : AEvent<OnPlayerDead>
{
    protected override void Run(Scene scene, OnPlayerDead evt)
    {
        var player = scene.GetChild<PlayerEntity>(evt.PlayerId);
        player?.PlayDeathAnimation();
    }
}

// 触发
EventSystem.Instance.Publish(currentScene, new OnPlayerDead { PlayerId = 1001, Reason = 0 });
```

---

## 三、AAsyncEvent：异步事件处理基类

```csharp
public abstract class AAsyncEvent<A> : IEvent
{
    public Type Type => typeof(A);

    protected abstract ETTask Run(Scene scene, A evt);

    public virtual async ETTask Handle(Scene scene, A evt)
    {
        try
        {
            await Run(scene, evt);
        }
        catch (Exception e)
        {
            Log.Error(e);
        }
    }
}
```

`AAsyncEvent` 与 `AEvent` 的核心区别在于 `Run()` 返回 `ETTask`，支持 `await` 异步操作。

### 3.1 EventSystem 中的双模式分发

```csharp
public void Publish<T>(Scene scene, T a)
{
    foreach (EventInfo eventInfo in iEvents)
    {
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue;

        if (eventInfo.IEvent is AEvent<T> aEvent)
        {
            // 同步路径：直接调用
            aEvent.Handle(scene, a);
        }
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
        {
            // 异步路径：fire-and-forget
            aAsyncEvent.Handle(scene, a).Coroutine();
        }
    }
}
```

同步处理器直接调用，异步处理器通过 `.Coroutine()` 以即发即忘模式启动协程，不阻塞 `Publish` 调用方。

`PublishAsync` 版本则等待所有异步处理器完成：

```csharp
public async ETTask PublishAsync<T>(Scene scene, T a)
{
    using ListComponent<ETTask> list = ListComponent<ETTask>.Create();
    
    foreach (EventInfo eventInfo in iEvents)
    {
        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);  // 同步立即执行
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            list.Add(aAsyncEvent.Handle(scene, a));  // 收集异步任务
    }
    
    await ETTaskHelper.WaitAll(list);  // 等待所有异步完成
}
```

---

## 四、EventAttribute：场景感知注册

```csharp
[AttributeUsage(AttributeTargets.Class, AllowMultiple = true)]
public class EventAttribute : BaseAttribute
{
    public SceneType SceneType { get; }

    public EventAttribute(SceneType sceneType)
    {
        this.SceneType = sceneType;
    }
}
```

`EventAttribute` 携带 `SceneType` 参数，标记处理器在哪种场景下生效。结合 `EventSystem.Add()` 的注册逻辑：

```csharp
foreach (var type in types[typeof(EventAttribute)])
{
    IEvent obj = Activator.CreateInstance(type) as IEvent;
    object[] attrs = type.GetCustomAttributes(typeof(EventAttribute), false);
    foreach (object attr in attrs)
    {
        EventAttribute eventAttribute = attr as EventAttribute;
        EventInfo eventInfo = new(obj, eventAttribute.SceneType);
        this.allEvents[eventType].Add(eventInfo);
    }
}
```

处理器被包装为 `EventInfo(IEvent, SceneType)` 存储。发布事件时：

```csharp
if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
    continue;  // SceneType 不匹配，跳过
```

`SceneType.None` 是通配符，表示在任意 Scene 都会触发；其他类型只在匹配的 Scene 中触发。

### SceneType 枚举设计

```csharp
public enum SceneType
{
    None = -1,    // 通配，任意 Scene 都响应
    Process = 0,  // 进程级 Scene（跨场景单例）
    Client = 1,   // 客户端主 Scene
    Current = 2   // 当前活跃 Scene
}
```

`SceneTypeHelper.HasSameFlag()` 提供了位运算的扩展匹配：

```csharp
public static bool HasSameFlag(this SceneType a, SceneType b)
{
    if (((ulong)a & (ulong)b) == 0) return false;
    return true;
}
```

虽然目前枚举值不以位标志方式使用，但这个扩展方法为未来扩展成多 Scene 复合匹配预留了空间。

---

## 五、IInvoke 与 AInvokeHandler：精准分发机制

### 5.1 Invoke 与 Publish 的本质区别

框架在源码中有明确注释：

```
Invoke 类似函数，必须有被调用方，否则异常。
调用者跟被调用者属于同一模块，比如 TimerComponent 中的 Timer 计时器。

Publish 是事件，抛出去可以没人订阅。
调用者跟被调用者属于两个模块，比如任务系统订阅道具使用事件。

注意：不要把 Invoke 当函数使用，这样会造成代码可读性降低，能用函数不要用 Invoke。
```

Invoke 的本质是**通过类型和 int 键精准路由到唯一处理器**：

```csharp
public interface IInvoke
{
    Type Type { get; }  // 参数类型
}

// 无返回值的处理器
public abstract class AInvokeHandler<A> : IInvoke where A : struct
{
    public Type Type => typeof(A);
    public abstract void Handle(A a);
}

// 有返回值的处理器
public abstract class AInvokeHandler<A, T> : IInvoke where A : struct
{
    public Type Type => typeof(A);
    public abstract T Handle(A a);
}
```

注意 `A : struct` 约束——Invoke 参数必须是结构体，确保零 GC 分配。

### 5.2 InvokeAttribute：类型+int 双重定位

```csharp
public class InvokeAttribute : BaseAttribute
{
    public int Type { get; }  // 同一参数类型下的子类型区分

    public InvokeAttribute(int type = 0)
    {
        this.Type = type;
    }
}
```

`allInvokes` 的数据结构：

```csharp
private Dictionary<Type, Dictionary<int, object>> allInvokes;
// 外层 Key: 参数类型 A（如 TimerCallback）
// 内层 Key: InvokeAttribute.Type（如 TimerClass.Once = 0, Repeat = 1）
```

这使得同一类参数可以根据 int 键路由到不同的处理器——典型应用是 `TimerComponent` 中区分不同定时器类型的回调。

### 5.3 EventSystem.Invoke 调用流程

```csharp
public void Invoke<A>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers))
        throw new Exception($"Invoke error: {typeof(A).Name}");  // 必须有处理器

    if (!invokeHandlers.TryGetValue(type, out var invokeHandler))
        throw new Exception($"Invoke error: {typeof(A).Name} {type}");

    var aInvokeHandler = invokeHandler as AInvokeHandler<A>;
    aInvokeHandler.Handle(args);
}
```

`Invoke` 找不到处理器时直接抛异常——这与 `Publish`（找不到订阅者静默返回）的处理策略截然不同，精准体现了"Invoke 是必须有被调用方的函数"的语义。

---

## 六、BaseInvokeArg：资源加载协调结构体

```csharp
public class StartLoadDependentCodeHelper
{
    static int uniqueCode;
    public static int GetCode() => uniqueCode++;
}

public struct StartLoadDependentResourcesArg
{
    public int UniqueCode;
}

public struct EndLoadDependentResourcesArg
{
    public int UniqueCode;
}
```

这三个类型解决了一个实际问题：**依赖代码模块的异步资源加载协调**。

`StartLoadDependentCodeHelper.GetCode()` 生成全局递增的唯一码，在启动依赖资源加载时通过 Invoke 广播 `StartLoadDependentResourcesArg`，完成后广播 `EndLoadDependentResourcesArg`，框架可以通过匹配 `UniqueCode` 追踪特定加载任务的完整生命周期。

这是 Invoke 机制的一个典型应用：资源加载触发方与监听方属于同一模块，必须有处理方响应，正好符合 Invoke 的语义。

---

## 七、EventSystem 的动态注册接口

框架还提供了两个运行时动态注册事件处理器的方法：

```csharp
// 方式一：自动从 Attribute 读取 SceneType
public void RegisterOneEvent(Type hdrType)

// 方式二：手动指定 SceneType（支持热更新场景下的动态注册）
public void RegisterOneEvent2(Type hdrType, SceneType scenType)
```

源码注释特别提醒：

```csharp
/// <summary>
/// This is bad, when EventSystem reloads, all event registered by this is dropped
/// </summary>
```

`RegisterOneEvent2` 是一种"bad practice"——热重载时 EventSystem 会清空并重新注册所有 Attribute 标记的处理器，运行时动态注册的处理器会丢失。在实际工程中，应尽量避免运行时动态注册，优先使用 `[Event(SceneType.XXX)]` 标记。

---

## 八、性能优化设计

### 8.1 ProfilingMarker 条件编译

```csharp
public void Publish<T>(Scene scene, T a)
{
    VProfiler.BeginDeepSample("EventSystem.Publish");
#if ONLY_CLIENT
    using var _ = ProfilingMarker.EvtMarker<T>.Marker.Auto();
#endif
    // ...事件分发...
    VProfiler.EndDeepSample();
}
```

`ProfilingMarker.EvtMarker<T>` 是泛型静态类，每个事件类型生成唯一的 `ProfilerMarker` 实例，方便在 Unity Profiler 中精准定位哪种事件的分发耗时过高。`#if ONLY_CLIENT` 确保该开销在非客户端构建（如服务器）中完全消除。

### 8.2 结构体事件参数

所有 Publish 和 Invoke 的参数都推荐使用 `struct`：
- Publish 的 `<T>` 没有约束，但事件系统整体倾向于结构体（无 GC）
- Invoke 的 `<A>` 强制要求 `where A : struct`

结构体参数直接在栈上传递，不产生堆内存分配，在高频事件（如帧更新、战斗事件）场景下对 GC 友好。

---

## 九、Publish 与 Invoke 的职责边界

| 维度 | Publish | Invoke |
|------|---------|--------|
| 处理器数量 | 0 到 N 个 | 严格 1 个 |
| 无处理器时 | 静默返回 | 抛出异常 |
| 模块关系 | 跨模块（解耦） | 同模块（紧耦合） |
| 典型场景 | 任务系统监听道具使用 | 定时器回调分发 |
| 支持异步 | ✅（AAsyncEvent）| ❌（仅同步）|
| 支持返回值 | ❌ | ✅（AInvokeHandler\<A,T>）|
| 场景过滤 | ✅（SceneType）| ❌ |

这张对比表揭示了设计的核心逻辑：Publish 用于解耦的广播通知，Invoke 用于模块内的有保证函数调用。二者不可混用——用 Invoke 替代函数会破坏代码可读性，用 Publish 替代 Invoke 会失去"必须有响应"的保证。

---

## 十、总结

xgame 框架的 `IEvent` / `AEvent` / `AAsyncEvent` 抽象层，通过以下几个关键设计实现了事业级的事件总线：

1. **泛型参数即类型键**：避免手动注册，消除反射错误风险。
2. **Scene 作为隔离域**：相同事件在不同 Scene 各自处理，天然支持多实例场景。
3. **同步异步双模式**：`AEvent` 与 `AAsyncEvent` 统一接口，Publish 自动路由。
4. **`[Event]` 属性驱动注册**：热重载时自动重建注册表，无需手动管理生命周期。
5. **Invoke 的精准分发**：类型 + int 双重定位唯一处理器，语义清晰，错误提前暴露。
6. **结构体参数 + 条件编译 Profiler**：兼顾零 GC 性能与可观测性。

掌握这套事件抽象层的设计，对于在 xgame 框架上构建复杂游戏系统（战斗、任务、UI 联动等）至关重要。
