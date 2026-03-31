---
title: 延迟初始化与热重载——Start 系统和 Load 系统的设计差异
published: 2026-03-31
description: 解析 IStartSystem 和 ILoadSystem 的设计区别，理解为什么需要延迟一帧初始化、Load 系统如何支持代码热重载，以及两者在 EventSystem 调度中的不同处理方式。
tags: [Unity, ECS, 热更新, 生命周期, 延迟初始化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 延迟初始化与热重载——Start 系统和 Load 系统的设计差异

## 前言

在 ECS 框架的生命周期中，`Awake` 是"立即初始化"，那如果我需要"延迟一帧后初始化"呢？

如果我热更新了代码，需要所有相关实体重新初始化呢？

这就是 `IStartSystem` 和 `ILoadSystem` 解决的两个完全不同的问题。虽然它们看起来都是"初始化"，但用途截然不同。

---

## 一、IStartSystem——延迟一帧的初始化

```csharp
public interface IStart {}

public interface IStartSystem : ISystemType
{
    void Run(object o);
}

[ObjectSystem]
[EntitySystem]
public abstract class StartSystem<T> : IStartSystem where T: Entity, IStart
{
    public void Run(object o)
    {
        this.Start((T)o);
    }

    public Type Type() => typeof(T);
    public Type SystemType() => typeof(IStartSystem);
    public InstanceQueueIndex GetInstanceQueueIndex() => InstanceQueueIndex.Start;

    protected abstract void Start(T self);
}
```

注意几个细节：

### 1.1 Run 参数是 object 而非 Entity

```csharp
void Run(object o);
```

`IStartSystem` 的 `Run` 接受 `object` 而非 `Entity`（其他系统接受 `Entity`）。

这可能是历史遗留设计，或者是为了兼容某些特殊用途。实际使用中，传入的依然是 `Entity`，在 `StartSystem<T>.Run` 中也是把 `o` 直接转型为 `(T)o`。

### 1.2 InstanceQueueIndex.Start——专用队列

```csharp
public InstanceQueueIndex GetInstanceQueueIndex() => InstanceQueueIndex.Start;
```

`Start` 有自己的专用队列 `queues[InstanceQueueIndex.Start]`。

在 `EventSystem` 中，`Start` 的调用时机是：

```csharp
public void FixedUpdate()
{
    Start(); // 在 FixedUpdate 开始时先处理所有待 Start 的实体
    // ... 然后处理 FixedUpdate
}

public void Update()
{
    Start(); // 在 Update 开始时也调用
    // ...
}
```

注意 `Start()` 在每个更新阶段开始时都被调用一次，但 `Start` 队列中的实体处理完后**不会重新入队**（对比 `Update` 会重新入队）：

```csharp
public void Start()
{
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Start];
    int count = queue.Count;
    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        // ...
        // 注意：这里没有 queue.Enqueue(instanceId)
        foreach (IStartSystem iStartSystem in iStartSystems)
        {
            iStartSystem.Run(component);
        }
    }
}
```

**`Start` 只执行一次，不重复。这就是它与 `Update` 的根本区别。**

### 1.3 为什么需要延迟的 Start？

假设你有这样的逻辑：

```csharp
// 同一帧内
Entity player = entity.AddComponent<PlayerComponent>(); // Awake 立即调用
Entity weapon = entity.AddComponent<WeaponComponent>(); // Awake 立即调用
```

如果 `PlayerComponent.Awake` 需要访问 `WeaponComponent`，就会失败——因为此时 `WeaponComponent` 还没加上。

```csharp
// PlayerComponent 的 Awake（有问题的写法）
protected override void Awake(PlayerComponent self)
{
    WeaponComponent weapon = self.GetComponent<WeaponComponent>(); // 此时还是 null！
}
```

用 `Start` 解决：

```csharp
// PlayerComponent 的 Start（正确写法）
protected override void Start(PlayerComponent self)
{
    // Start 在第一个 FixedUpdate/Update 之前调用
    // 此时 WeaponComponent 已经加上了
    WeaponComponent weapon = self.GetComponent<WeaponComponent>(); // 有值了！
}
```

---

## 二、ILoadSystem——热重载后的重新初始化

```csharp
public interface ILoad {}

public interface ILoadSystem: ISystemType
{
    void Run(Entity o);
}

[ObjectSystem]
public abstract class LoadSystem<T> : ILoadSystem where T: Entity, ILoad
{
    void ILoadSystem.Run(Entity o)
    {
        this.Load((T)o);
    }

    Type ISystemType.Type() => typeof(T);
    Type ISystemType.SystemType() => typeof(ILoadSystem);
    InstanceQueueIndex ISystemType.GetInstanceQueueIndex() => InstanceQueueIndex.Load;

    protected abstract void Load(T self);
}
```

注意：`LoadSystem` 只有 `[ObjectSystem]`，**没有** `[EntitySystem]`。

这个区别很重要。

### 2.1 [ObjectSystem] vs [EntitySystem] 的区别

- `[ObjectSystem]`：系统在 `EventSystem.Add()` 时被扫描和实例化
- `[EntitySystem]`：（额外含义）系统方法支持运行时热替换

`LoadSystem` 只标记 `[ObjectSystem]`，意味着它的设计侧重于"被框架发现和调用"，而不是"热更替换方法实现"。

### 2.2 Load 的触发时机

在 `EventSystem.Load()` 中：

```csharp
public void Load()
{
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Load];
    int count = queue.Count;
    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        // ...
        List<object> iLoadSystems = this.typeSystems.GetSystems(component.GetType(), typeof(ILoadSystem));
        
        queue.Enqueue(instanceId); // 重新入队！Load 会被循环调用
        
        foreach (ILoadSystem iLoadSystem in iLoadSystems)
        {
            iLoadSystem.Run(component);
        }
    }
}
```

注意 `Load` 和 `Start` 的关键区别：`Load` 处理后**重新入队**（`queue.Enqueue(instanceId)`），意味着**每次 `EventSystem.Load()` 被调用时，所有注册了 `ILoad` 的实体都会执行 `Load`**。

`Load()` 通常在以下场景被调用：
1. **热更新后**：代码重新加载后，所有配置/资源依赖的缓存需要重建
2. **场景切换后**：某些需要重新初始化的缓存数据
3. **程序集重新加载**：`EventSystem.Add(newTypes)` 后，通知相关实体重新加载

### 2.3 Load 的典型用途

```csharp
// 配置管理器实现 ILoad
public class ConfigManager: Entity, ILoad
{
    private Dictionary<int, SkillConfig> skillConfigs;
    
    // 每次代码热更新后都会被调用
    protected override void Load(ConfigManager self)
    {
        // 重新加载配置（因为热更新后配置类型可能改变）
        self.skillConfigs = new Dictionary<int, SkillConfig>();
        // ... 从资源文件重新加载
    }
}
```

如果不用 `Load` 而用 `Awake`：热更新后，配置管理器的内部状态（缓存的配置数据）不会更新，可能导致游戏使用旧的配置数据。

用 `Load`，每次热更新后自动重新加载所有依赖的配置，保证数据最新。

---

## 三、Start 与 Load 的对比

| 特性 | IStartSystem | ILoadSystem |
|---|---|---|
| 触发时机 | 第一帧（Update/FixedUpdate 前） | 显式调用 `EventSystem.Load()` |
| 执行次数 | 只执行一次 | 每次调用 `Load()` 都执行 |
| 典型用途 | 延迟初始化，处理组件间依赖 | 热更新后重新加载配置/缓存 |
| 特性标记 | `[ObjectSystem][EntitySystem]` | 只有 `[ObjectSystem]` |
| 类比 | Unity 的 Start | 配置刷新/热重载 |

---

## 四、完整示例——Start 处理组件依赖

```csharp
// 角色组件——创建时立即初始化自己的基础属性
public class CharacterComponent: Entity, IAwake<string>, IStart
{
    public string Name;
    public WeaponComponent MainWeapon;
}

[ObjectSystem]
public class CharacterAwakeSystem: AwakeSystem<CharacterComponent, string>
{
    protected override void Awake(CharacterComponent self, string name)
    {
        // 立即执行的初始化
        self.Name = name;
    }
}

[ObjectSystem]
public class CharacterStartSystem: StartSystem<CharacterComponent>
{
    protected override void Start(CharacterComponent self)
    {
        // 延迟一帧，此时其他组件已经 Awake 完毕
        self.MainWeapon = self.GetComponent<WeaponComponent>();
        if (self.MainWeapon == null)
        {
            Log.Warning($"{self.Name} 没有武器组件！");
        }
    }
}
```

---

## 五、完整示例——Load 处理热重载

```csharp
// 技能配置缓存——支持热重载
public class SkillConfigCache: Entity, ILoad
{
    // 这个字典会在每次热更新后重建
    public Dictionary<int, SkillData> Configs = new();
}

[ObjectSystem]
public class SkillConfigCacheLoadSystem: LoadSystem<SkillConfigCache>
{
    protected override void Load(SkillConfigCache self)
    {
        self.Configs.Clear();
        // 重新从资源加载所有技能配置
        foreach (var config in Resources.LoadAll<SkillData>("Configs/Skills"))
        {
            self.Configs[config.Id] = config;
        }
        Log.Info($"技能配置重新加载完成，共 {self.Configs.Count} 个");
    }
}
```

---

## 六、不同初始化方式的选择指南

```
需要初始化逻辑？
│
├── 只需执行一次？
│   ├── 不依赖其他组件 → Awake（立即执行）
│   └── 依赖同一帧添加的其他组件 → Start（延迟一帧）
│
└── 需要重复执行？
    ├── 热更新/程序集重载后需要刷新 → Load
    └── 每帧都需要 → Update/FixedUpdate
```

---

## 七、写给初学者

`Start` 解决的是**时序问题**：多个组件同时创建时，初始化顺序不确定，延迟一帧可以保证所有组件都已就绪。

`Load` 解决的是**热更新问题**：代码修改后重新加载，某些缓存数据需要用新的类型/逻辑重新生成。

这两个问题在大型游戏项目中都很真实：

- 角色有10个组件，它们的初始化互相依赖——`Start` 解决这个问题
- 游戏上线后发现技能配置有误，热更修复后需要重新加载——`Load` 解决这个问题

在项目中合理运用这两种初始化方式，能让代码更健壮、热更体验更顺畅。
