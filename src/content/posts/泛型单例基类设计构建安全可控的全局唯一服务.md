---
title: 泛型单例基类设计——构建安全可控的全局唯一服务
published: 2026-03-31
description: 深入解析 Singleton<T> 泛型基类和 ISingletonAwake 接口族的设计，理解双重保护的单例注册机制、StaticField 标注的意义，以及单例与普通静态类的工程取舍。
tags: [Unity, ECS, 单例模式, 泛型设计, 全局服务]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 泛型单例基类设计——构建安全可控的全局唯一服务

## 前言

单例模式（Singleton Pattern）是游戏开发中最常见的模式之一，也是争议最多的模式之一。

"单例有害"是一个流行的说法，但事实是：**合理使用的单例非常有用，滥用才是问题所在**。

今天我们来分析 ECS 框架中的单例基类 `Singleton<T>` 和配套接口，理解一个精心设计的单例系统应该是什么样的。

---

## 一、ISingleton 接口——定义单例的契约

```csharp
public interface ISingleton: IDisposable
{
    void Register();
    void Destroy();
    bool IsDisposed();
}
```

所有单例都必须实现这个接口，包含三个操作：

- `Register()`：将实例注册为全局唯一
- `Destroy()`：销毁单例并清理资源
- `IsDisposed()`：查询是否已被销毁

继承 `IDisposable` 表示单例支持 `using` 语法，可以被 `using` 块管理（虽然单例一般不这样用）。

**为什么需要这个接口？**

`Game` 类需要管理所有单例，但不知道具体是哪种单例。`ISingleton` 提供了统一的管理接口：

```csharp
private static readonly Stack<ISingleton> singletons = new Stack<ISingleton>();
```

通过 `ISingleton` 接口，`Game` 可以管理任何单例，无需关心具体类型。

---

## 二、Singleton<T>——自我注册的泛型实现

```csharp
public abstract class Singleton<T>: ISingleton where T: Singleton<T>, new()
{
    private bool isDisposed;
    
    [StaticField]
    private static T instance;

    public static T Instance => instance;

    public void Register()
    {
        if (instance != null)
        {
            throw new Exception($"singleton register twice! {typeof(T).Name}");
        }
        instance = (T)this;
    }

    public void Destroy()
    {
        if (this.isDisposed) return;
        this.isDisposed = true;
        
        T t = instance;
        instance = null; // 先清空，防止在 Dispose 过程中再次访问
        t.Dispose();
    }

    public bool IsDisposed() => this.isDisposed;

    public virtual void Dispose() { }
}
```

### 2.1 泛型约束 `where T: Singleton<T>, new()`

```csharp
where T: Singleton<T>, new()
```

- `T: Singleton<T>`：**CRTP（Curiously Recurring Template Pattern）奇异递归模板模式**
  - `T` 必须继承自 `Singleton<T>`（自己继承以自己为参数的类）
  - 这确保 `instance` 字段是 `T` 类型而非 `Singleton` 基类类型
- `new()`：`T` 必须有无参构造函数，因为 `Game.AddSingleton<T>()` 中会 `new T()`

CRTP 的作用：

```csharp
// 没有 CRTP：instance 是基类类型
private static Singleton instance; // 访问时需要强制转换

// 有 CRTP：instance 直接是子类型
private static T instance; // 直接可用，类型安全
public static T Instance => instance; // 返回正确类型
```

### 2.2 Register 的双重保护

```csharp
public void Register()
{
    if (instance != null)
    {
        throw new Exception($"singleton register twice! {typeof(T).Name}");
    }
    instance = (T)this;
}
```

如果同一个单例类型注册两次，直接抛出异常。

这是**快速失败原则**（Fail Fast）：与其在后续代码中出现奇怪的 Bug，不如在错误的源头立刻报错。

### 2.3 [StaticField] 注解

```csharp
[StaticField]
private static T instance;
```

`[StaticField]` 是框架自定义的特性，用于标记在热更新或场景重置时需要清理的静态字段。

在支持热更新的游戏中，如果代码热更新后静态字段不清理，可能会残留旧的单例实例，导致新代码访问旧数据。`[StaticField]` 告诉热更新系统："热更时请清理这个字段"。

### 2.4 Destroy 的安全顺序

```csharp
public void Destroy()
{
    if (this.isDisposed) return;
    this.isDisposed = true;
    
    T t = instance;
    instance = null; // 先清空
    t.Dispose();     // 再销毁
}
```

先设置 `instance = null`，再调用 `Dispose()`。

为什么先清空？如果 `Dispose()` 内部又访问了 `Instance`（比如解注册某些事件时调用了其他单例），此时 `instance` 已经是 null，不会意外获取到正在销毁的实例。

---

## 三、ISingletonAwake——单例的初始化接口

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

单例的 Awake 接口与实体的 IAwake 设计一致，支持 0-3 个参数。

在 `Game.AddSingleton<T>()` 中：

```csharp
public static T AddSingleton<T>() where T: Singleton<T>, new()
{
    T singleton = new T();
    if (singleton is ISingletonAwake singletonAwake)
    {
        singletonAwake.Awake(); // 如果实现了 ISingletonAwake，自动调用 Awake
    }
    AddSingleton(singleton);
    return singleton;
}
```

单例创建后自动检测是否实现了 `ISingletonAwake`，如果实现了就调用 `Awake()`。

**带参数的 Awake 需要显式调用**：

```csharp
// 带参数时，必须先创建再手动调用 Awake
var singleton = Game.AddSingleton<ConfigManager>();
((ISingletonAwake<string>)singleton).Awake("configs/");
```

或者在 Game 中添加对应的重载方法。

---

## 四、单例 vs 静态类——如何选择？

很多功能既可以用单例也可以用静态类实现：

```csharp
// 方案A：静态类
public static class TimeManager
{
    private static long currentTime;
    public static long GetTime() => currentTime;
    public static void Update() { currentTime = ...; }
}

// 方案B：单例
public class TimeManager: Singleton<TimeManager>
{
    private long currentTime;
    public long GetTime() => currentTime;
    public void Update() { currentTime = ...; }
}
```

**选择单例而非静态类的理由**：

1. **支持生命周期管理**：单例可以 `Destroy()`，静态类的静态字段需要手动清理
2. **支持继承和接口**：单例可以实现 `ISingletonUpdate` 等接口，静态类不行
3. **支持热更新清理**：`[StaticField]` 可以标记热更时需要清理，静态类字段处理更麻烦
4. **支持依赖注入测试**：单例可以通过接口替换，便于单元测试

**选择静态类而非单例的理由**：

1. **无状态的工具方法**：如 `TimeHelper`，只提供计算方法，无需生命周期管理
2. **更简洁**：不需要 `Instance.` 前缀
3. **编译期保证**：静态类的方法在编译时解析，无运行时查找

---

## 五、使用示例

```csharp
// 定义一个需要 Awake 初始化的单例
public class NetworkManager: Singleton<NetworkManager>, ISingletonAwake<string>
{
    private string serverAddress;
    
    public void Awake(string address)
    {
        this.serverAddress = address;
    }
    
    public void Connect()
    {
        // 连接到 serverAddress
    }
    
    public override void Dispose()
    {
        // 断开连接，清理资源
    }
}

// 注册单例
var networkMgr = Game.AddSingleton<NetworkManager>();
((ISingletonAwake<string>)networkMgr).Awake("192.168.1.1:8080");

// 使用
NetworkManager.Instance.Connect();

// 游戏关闭
Game.Close(); // 自动销毁所有单例，调用每个单例的 Dispose
```

---

## 六、单例销毁顺序

```csharp
// Game.Close() 中
while (singletons.Count > 0)
{
    ISingleton iSingleton = singletons.Pop(); // 用 Stack，后进先出
    iSingleton.Destroy();
}
```

`Game` 用 **Stack（栈）** 存储单例，销毁时先进后出（LIFO）。

这确保了**后创建的单例先销毁**。

为什么这个顺序重要？

如果 B 单例在创建时依赖了 A 单例（B 在 A 之后创建），那么销毁时必须先销毁 B（否则 B 的 Dispose 还在访问 A，但 A 已经 null 了）。

栈的 LIFO 顺序自然保证了依赖的逆序销毁。

---

## 七、设计总结

`Singleton<T>` 的设计体现了几个重要原则：

| 设计点 | 实现 | 价值 |
|---|---|---|
| CRTP 约束 | `where T: Singleton<T>` | 类型安全的 Instance |
| 双重注册保护 | `Register` 时检查 | 快速暴露错误 |
| [StaticField] | 标记静态字段 | 热更新安全 |
| 先清空后 Dispose | `instance = null; t.Dispose()` | 避免销毁中的循环访问 |
| LIFO 销毁 | Stack 存储 | 依赖的安全逆序销毁 |
| ISingleton 接口 | 统一管理 | Game 可以管理任意单例 |
