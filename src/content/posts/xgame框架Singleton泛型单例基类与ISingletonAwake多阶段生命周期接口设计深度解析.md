---
title: xgame框架Singleton泛型单例基类与ISingletonAwake多阶段生命周期接口设计深度解析
date: 2026-05-03
tags:
  - Unity
  - 游戏框架
  - 单例模式
  - 生命周期
  - CSharp泛型
categories:
  - xgame框架源码解析
description: 深度解析xgame框架中Singleton<T>泛型单例基类的完整实现，重点讲解ISingleton接口的Register/Destroy语义、StaticField静态字段标记的热重载兼容设计、ISingletonAwake多参数泛型接口体系、以及ISingletonUpdate/LateUpdate/FixedUpdate三段帧驱动接口的职责划分与工程最佳实践。
encryptedKey: henhaoji123
---

## 前言

几乎所有游戏框架都会有单例系统，但真正设计得精良的单例并不多见。xgame 框架中的 `Singleton<T>` 不仅解决了"全局唯一实例"这个基本需求，还针对**热重载**、**帧驱动**、**生命周期管理**等游戏特有场景做出了专门设计。本文将从源码出发，逐一拆解这套单例体系的设计精髓。

---

## 一、ISingleton 接口：比 Dispose 更精细的生命周期

```csharp
public interface ISingleton : IDisposable
{
    void Register();
    void Destroy();
    bool IsDisposed();
}
```

标准的 `IDisposable` 只有一个 `Dispose`，而 `ISingleton` 将生命周期拆成了三步：

| 方法 | 调用时机 | 语义 |
|------|---------|------|
| `Register()` | 首次激活时，由 Game 主循环调用 | 声明"我已就位" |
| `Dispose()` | IDisposable 约定，可被 `using` 触发 | 资源释放 |
| `Destroy()` | 由 Game 主循环主动调用 | 安全卸载并调用 Dispose |
| `IsDisposed()` | 任意时刻查询 | 防止对已销毁单例的访问 |

这种分离的价值在于：`Destroy()` 可以先把全局引用置空（`instance = null`），再执行 `Dispose()`，避免在析构过程中其他代码意外拿到一个"正在析构"的实例。

---

## 二、Singleton<T> 泛型实现：自引用约束与静态字段

```csharp
public abstract class Singleton<T> : ISingleton where T : Singleton<T>, new()
{
    private bool isDisposed;
    
    [StaticField]
    private static T instance;

    public static T Instance => instance;
    ...
}
```

### 2.1 自引用泛型约束

`where T : Singleton<T>, new()` 是经典的 **CRTP（Curiously Recurring Template Pattern）** 在 C# 中的实现：

- `T : Singleton<T>`：确保子类继承自以自身为参数的基类，`instance` 字段的类型就是子类本身，**无需类型转换**
- `new()`：约束 T 必须有无参构造函数，支持反射实例化
- 这使得 `EventSystem.Instance` 直接返回 `EventSystem` 类型，而非需要强转的基类类型

### 2.2 [StaticField] 标记：热重载的关键

```csharp
[StaticField]
private static T instance;
```

`StaticField` 是框架自定义的 Analyzer 特性标记。在 xgame 框架中，热重载时框架需要知道哪些静态字段需要被**重置**——普通的热重载只替换代码，但静态字段的值会保留。

通过 `[StaticField]` 标记，Roslyn Analyzer 或运行时扫描工具可以枚举出所有需要在热重载时清理的静态字段，防止"僵尸单例"问题（旧代码的单例实例残留在新代码的静态字段中）。

---

## 三、Register 与 Destroy 的互锁设计

```csharp
public void Register()
{
    if (instance != null)
        throw new Exception($"singleton register twice! {typeof(T).Name}");
    instance = (T)this;
}

public void Destroy()
{
    if (this.isDisposed) return;
    this.isDisposed = true;
    
    T t = instance;
    instance = null;  // 先清空引用
    t.Dispose();      // 再执行 Dispose
}
```

`Register` 有**重复注册保护**：如果一个单例被注册两次（热重载期间常见），立刻抛异常，及早发现问题。

`Destroy` 的执行顺序值得关注：
1. 设置 `isDisposed = true`（防止重入）
2. 保存引用到局部变量 `t`
3. **立即将 `instance` 置空**
4. 调用 `t.Dispose()`

这个顺序确保在 `Dispose()` 执行期间，外部访问 `T.Instance` 会得到 `null`，而不是一个半死不活的实例。这是并发/异步环境下非常重要的安全保证。

---

## 四、ISingletonAwake 多参数接口体系

```csharp
public interface ISingletonAwake
{
    void Awake();
}

public interface ISingletonAwake<A>
{
    void Awake(A a);
}

public interface ISingletonAwake<A, B>
{
    void Awake(A a, B b);
}

public interface ISingletonAwake<A, B, C>
{
    void Awake(A a, B b, C c);
}
```

与 Entity 系统的 `IAwakeSystem` 对应，`ISingletonAwake` 为单例的初始化提供了**带参数的 Awake 语义**。

相比在构造函数中传参，这种设计的优势：

1. **延迟初始化**：单例对象可以先通过 `new()` 创建（无参构造），然后在框架完成其他初始化后再调用 `Awake()`，避免构造顺序依赖
2. **参数明确**：`Awake(A a, B b)` 比构造函数更清晰地表达"初始化需要什么"
3. **可测试性**：Mock 测试时可以独立控制 Awake 调用时机
4. **热重载友好**：热重载后可以重新调用 `Awake` 恢复状态，而构造函数在热重载时无法重新触发

典型用法：

```csharp
public class NetworkManager : Singleton<NetworkManager>, ISingletonAwake<string>
{
    private string serverAddress;
    
    public void Awake(string address)
    {
        this.serverAddress = address;
        // 初始化网络连接
    }
}

// 注册时：
var nm = new NetworkManager();
nm.Register();
nm.Awake("192.168.1.1:8080");
```

---

## 五、帧驱动接口三件套

```csharp
public interface ISingletonUpdate     { void Update(); }
public interface ISingletonLateUpdate { void LateUpdate(); }
public interface ISingletonFixedUpdate{ void FixedUpdate(); }
```

以及对应的：

```csharp
public interface ISingletonFixedUpdate
{
    // 对应 Unity 的 FixedUpdate（物理帧）
    void FixedUpdate();
}
```

这三个接口对应 Unity 的三个核心更新循环：

| 接口 | 对应 Unity 回调 | 典型用途 |
|------|--------------|---------|
| `ISingletonUpdate` | `Update()` | 逻辑更新、输入处理 |
| `ISingletonLateUpdate` | `LateUpdate()` | 相机跟随、UI 刷新 |
| `ISingletonFixedUpdate` | `FixedUpdate()` | 物理计算、帧同步逻辑 |

**不直接用 MonoBehaviour 的原因**：xgame 框架的大量逻辑运行在非 MonoBehaviour 的纯 C# 层，通过单例接口+`Game` 主循环的方式，可以在不挂载 GameObject 的情况下获得完整的帧驱动能力，也更容易做服务端移植。

### Game 主循环的驱动方式

在 `Game.cs` 中（简化版）：

```csharp
public static void Update()
{
    foreach (ISingleton singleton in singletons)
    {
        if (singleton is ISingletonUpdate update)
            update.Update();
    }
}
```

框架维护一个有序的单例列表，每帧按注册顺序依次驱动，确保系统调用顺序可控。

---

## 六、完整生命周期时序图

```
new T()                  ← 无参构造（不执行业务初始化）
    ↓
Register()               ← 设置 T.instance = this
    ↓
Awake() / Awake<A>(a)    ← 执行业务初始化
    ↓
[进入帧循环]
    FixedUpdate()        ← 物理帧（如有实现）
    Update()             ← 逻辑帧（如有实现）
    LateUpdate()         ← 后期更新（如有实现）
    ↓
Destroy()                ← 主动销毁
    ├─ isDisposed = true
    ├─ instance = null
    └─ Dispose()         ← 资源释放
```

---

## 七、工程实践建议

### 7.1 避免在构造函数中访问其他单例

```csharp
// ❌ 危险：构造期间其他单例可能未就绪
public MySystem() 
{
    var logger = LogManager.Instance; // 可能为 null！
}

// ✅ 正确：在 Awake 中访问
public void Awake()
{
    var logger = LogManager.Instance; // 此时所有单例已注册
}
```

### 7.2 正确判断单例存活状态

```csharp
// ❌ 只判断 null
if (EventSystem.Instance != null) { ... }

// ✅ 同时判断 IsDisposed
if (EventSystem.Instance != null && !EventSystem.Instance.IsDisposed()) { ... }
```

### 7.3 不在 Dispose 中访问其他单例

因为 `Destroy` 时单例引用已被清空，`Dispose` 执行期间访问其他单例可能拿到 null，应在 `Destroy` 前完成跨单例的清理工作（可重写 `Destroy` 方法添加前置逻辑）。

### 7.4 热重载时的注意事项

`[StaticField]` 标记的字段在热重载时会被框架自动重置。如果你的单例有缓存数据需要在热重载后重新初始化，请在 `Awake` 中完成，而非在字段初始化器中。

---

## 八、总结

xgame 框架的 Singleton 体系将看似简单的全局单例模式提升到了工程级别：

1. **自引用泛型约束**：类型安全，无需强转，`T.Instance` 直接是子类类型
2. **Register/Destroy 生命周期拆分**：比 IDisposable 更精细，支持延迟激活和安全卸载
3. **[StaticField] 热重载标记**：静态字段的存在被框架感知，热重载时自动清理
4. **ISingletonAwake 多参数初始化**：带参数的延迟初始化，优于构造函数传参
5. **帧驱动接口三件套**：脱离 MonoBehaviour 获得完整帧驱动能力，服务端友好
6. **Destroy 的安全顺序**：先清空全局引用，再 Dispose，防止析构期间被误用

这套设计为 xgame 框架的所有核心系统（EventSystem、TimerComponent、CoroutineLockComponent 等）提供了一致且可靠的生命周期管理基础。
