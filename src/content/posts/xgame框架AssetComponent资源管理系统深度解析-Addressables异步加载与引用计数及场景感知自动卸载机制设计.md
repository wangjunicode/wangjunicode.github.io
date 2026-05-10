---
title: xgame框架AssetComponent资源管理系统深度解析-Addressables异步加载与引用计数及场景感知自动卸载机制设计
date: 2026-05-10
tags: [Unity, xgame, ECS, 资源管理, Addressables, 引用计数, 异步加载, 架构设计]
categories: [游戏开发, 框架源码解析]
description: 深入剖析xgame框架AssetComponent的设计原理，揭示游戏资源系统如何通过Addressables异步加载、引用计数防泄漏、场景感知自动卸载三大机制，打造零内存泄漏的高性能资源管理体系。
encryptedKey: henhaoji123
---

# xgame框架AssetComponent资源管理系统深度解析

## 前言

资源管理是游戏客户端最容易出问题的模块之一。内存泄漏、重复加载、场景切换后残留资源……这些问题在项目规模扩大后会集中爆发。

xgame框架的 `AssetComponent` 从设计之初就将**引用计数 + 场景生命周期绑定**作为核心约束，结合 Unity Addressables 的异步加载能力，构建了一套能在大型项目中稳定运行的资源管理体系。

---

## 一、整体架构

```
业务代码
    ↓  await assetComponent.LoadAsync<T>(path)
AssetComponent（ECS Component，挂载在 Scene 上）
    ├── AssetHandleDict          // path → AssetHandle（引用计数容器）
    ├── SceneAssetTracker        // Scene → 该场景持有的所有 handle key
    └── Addressables 底层 API
           ├── LoadAssetAsync<T>
           ├── InstantiateAsync
           └── ReleaseAsset / ReleaseInstance
```

核心思想：
1. **所有加载必须经过 AssetComponent**，禁止直接调用 `Resources.Load` 或裸 `Addressables`
2. **引用计数归零才真正卸载**，多处同时持有同一资源不会重复加载
3. **场景销毁时自动 Release 该场景的所有 handle**，做到零手动清理

---

## 二、AssetHandle 引用计数容器

```csharp
/// <summary>
/// 单个资源的引用计数容器
/// </summary>
public class AssetHandle : IDisposable
{
    public  string  Key      { get; }        // Addressables address/label
    public  int     RefCount { get; private set; }
    private AsyncOperationHandle operationHandle;
    private bool    isLoaded;

    internal AssetHandle(string key)
    {
        Key      = key;
        RefCount = 0;
        isLoaded = false;
    }

    /// <summary>
    /// 首次加载（仅在 RefCount 从 0→1 时真正触发 Addressables 请求）
    /// </summary>
    internal async ETTask<T> LoadAsync<T>() where T : Object
    {
        RefCount++;
        if (!isLoaded)
        {
            // 真正的 Addressables 异步加载
            operationHandle = Addressables.LoadAssetAsync<T>(Key);
            await operationHandle.Task;
            isLoaded = true;
        }
        return (T)operationHandle.Result;
    }

    /// <summary>
    /// 减少引用计数；归零时释放底层 handle
    /// </summary>
    internal void Release()
    {
        RefCount--;
        if (RefCount <= 0)
        {
            Dispose();
        }
    }

    public void Dispose()
    {
        if (isLoaded)
        {
            Addressables.Release(operationHandle);
            isLoaded = false;
        }
        RefCount = 0;
    }
}
```

关键设计点：
- **幂等加载**：同一 key 的第二次 `LoadAsync` 直接返回缓存结果，不会发起第二次 IO
- **懒释放**：`RefCount--` 不立即卸载；只有归零才调用 `Addressables.Release`
- 防止计数溢出为负：`Release` 后置检查 `<= 0` 而非 `== 0`

---

## 三、AssetComponent 核心 API

```csharp
[ComponentOf(typeof(Scene))]
public class AssetComponent : Entity, IAwake, IDestroy
{
    // path → AssetHandle
    private readonly Dictionary<string, AssetHandle> handleDict
        = new Dictionary<string, AssetHandle>();

    // sceneInstanceId → HashSet<string> 该场景持有的 key
    private readonly Dictionary<long, HashSet<string>> sceneTracker
        = new Dictionary<long, HashSet<string>>();

    // ────────────────────────────────────────
    // 公开 API
    // ────────────────────────────────────────

    /// <summary>
    /// 异步加载资源；自动绑定到 callerScene 的生命周期
    /// </summary>
    public async ETTask<T> LoadAsync<T>(
        string key,
        Scene  callerScene) where T : Object
    {
        if (!handleDict.TryGetValue(key, out var handle))
        {
            handle = new AssetHandle(key);
            handleDict[key] = handle;
        }

        // 在 SceneTracker 中记录本次持有关系
        TrackSceneAsset(callerScene.InstanceId, key);

        return await handle.LoadAsync<T>();
    }

    /// <summary>
    /// 异步实例化 Prefab；返回 GameObject，同样受引用计数管理
    /// </summary>
    public async ETTask<GameObject> InstantiateAsync(
        string    key,
        Transform parent,
        Scene     callerScene)
    {
        // 先确保资源已加载（引用计数 +1）
        var prefab = await LoadAsync<GameObject>(key, callerScene);
        // 实例化时再 +1（实例拥有独立引用）
        TrackSceneAsset(callerScene.InstanceId, key);
        handleDict[key].RefCount++;

        return Object.Instantiate(prefab, parent);
    }

    /// <summary>
    /// 手动释放单个资源引用
    /// </summary>
    public void Release(string key, Scene callerScene)
    {
        UntrackSceneAsset(callerScene.InstanceId, key);

        if (handleDict.TryGetValue(key, out var handle))
        {
            handle.Release();
            if (handle.RefCount <= 0)
            {
                handleDict.Remove(key);
            }
        }
    }

    // ────────────────────────────────────────
    // 场景生命周期钩子
    // ────────────────────────────────────────

    /// <summary>
    /// 场景销毁时，自动释放该场景持有的所有资源引用
    /// IDestroy 由 EventSystem 在 Scene.Dispose() 时调用
    /// </summary>
    public void OnSceneDestroy(long sceneInstanceId)
    {
        if (!sceneTracker.TryGetValue(sceneInstanceId, out var keys))
            return;

        foreach (var key in keys)
        {
            if (handleDict.TryGetValue(key, out var handle))
            {
                handle.Release();
                if (handle.RefCount <= 0)
                    handleDict.Remove(key);
            }
        }
        sceneTracker.Remove(sceneInstanceId);
    }

    // ────────────────────────────────────────
    // 内部辅助
    // ────────────────────────────────────────

    private void TrackSceneAsset(long sceneId, string key)
    {
        if (!sceneTracker.TryGetValue(sceneId, out var set))
        {
            set = new HashSet<string>();
            sceneTracker[sceneId] = set;
        }
        set.Add(key);
    }

    private void UntrackSceneAsset(long sceneId, string key)
    {
        if (sceneTracker.TryGetValue(sceneId, out var set))
            set.Remove(key);
    }
}
```

---

## 四、场景感知自动卸载机制

这是 `AssetComponent` 最有价值的设计：**资源生命周期与场景生命周期强绑定**。

```
Scene A 启动
    │
    ├── LoadAsync("hero_prefab", sceneA)    ← RefCount=1，sceneA tracker 记录
    ├── LoadAsync("ui_atlas",    sceneA)    ← RefCount=1，sceneA tracker 记录
    │
    │  ← 场景 A 运行中...
    │
Scene A Dispose()
    │
    └── OnSceneDestroy(sceneA.InstanceId)
            ├── Release("hero_prefab")     ← RefCount 0 → Addressables.Release
            └── Release("ui_atlas")        ← RefCount 0 → Addressables.Release
```

如果同一资源同时被 Scene A 和 Scene B 使用（例如公共 Atlas）：

```
Scene A LoadAsync("common_atlas")  → RefCount=1
Scene B LoadAsync("common_atlas")  → RefCount=2

Scene A Dispose → Release("common_atlas") → RefCount=1（仍持有，不卸载）
Scene B Dispose → Release("common_atlas") → RefCount=0 → 真正卸载
```

这种行为无需业务层任何额外代码，完全由 `sceneTracker` 自动管理。

---

## 五、ETTask 与 Addressables 的桥接

xgame 使用 `ETTask` 作为异步基础设施，需要将 `AsyncOperationHandle.Task`（`System.Threading.Task`）桥接到 ETTask：

```csharp
// ETTask 扩展方法：将 Unity AsyncOperationHandle 转为 ETTask
public static async ETTask<T> ToETTask<T>(
    this AsyncOperationHandle<T> handle)
{
    if (handle.IsDone)
        return handle.Result;

    // 注册到 MainThreadSynchronizationContext，保证回调在主线程执行
    var tcs = ETTask<T>.Create(true);
    handle.Completed += op =>
    {
        if (op.Status == AsyncOperationStatus.Succeeded)
            tcs.SetResult(op.Result);
        else
            tcs.SetException(new Exception($"Addressables load failed: {op.DebugName}"));
    };
    return await tcs;
}
```

这样，`LoadAsync` 内部用 `await handle.Task.ToETTask()` 就能无缝接入 xgame 的协程体系，同时保证：
- 回调在主线程执行（Unity API 线程安全）
- 异常通过 ETTask 的 `try/catch` 正常传播

---

## 六、常见陷阱与规避方案

### 6.1 忘记 Release 导致内存泄漏

**症状**：场景反复切换后内存持续增长  
**原因**：手动持有资源但未在合适时机 `Release`  
**规避**：只用 `LoadAsync(key, callerScene)` 方式加载，依赖场景销毁自动释放；避免将资源挂在长生命周期的 Entity 上

### 6.2 RefCount 超前归零

**症状**：资源被卸载但仍有代码在使用，出现 MissingReferenceException  
**原因**：`Release` 调用次数多于 `LoadAsync` 调用次数  
**规避**：一次 `LoadAsync` 对应一次 `Release`，不要在循环中多次 Release 同一资源

### 6.3 场景切换时异步加载未完成

**症状**：加载中途切换场景，资源回调触发时场景已销毁  
**规避**：在异步加载前保存 `ETCancellationToken`，场景销毁时取消未完成的加载任务

```csharp
public async ETTask SafeLoadAsync<T>(
    string              key,
    Scene               callerScene,
    ETCancellationToken cancellationToken) where T : Object
{
    var result = await assetComponent.LoadAsync<T>(key, callerScene);
    cancellationToken.ThrowIfCancellationRequested();   // 场景已销毁则抛出
    return result;
}
```

---

## 七、总结

| 特性 | 实现机制 |
|------|---------|
| 零重复 IO | AssetHandle 引用计数，首次加载后缓存 |
| 零手动清理 | sceneTracker 绑定场景生命周期，自动 Release |
| 共享资源安全 | RefCount > 0 时不卸载，所有 Scene 释放后才真正卸载 |
| 异步无阻塞 | ETTask + Addressables 桥接，主线程安全回调 |
| 取消支持 | ETCancellationToken 防止场景销毁后回调污染 |

`AssetComponent` 的设计哲学是**让正确的行为成为默认行为**：只要通过统一 API 加载，引用计数和生命周期绑定就自动生效，业务开发者无需关心底层释放细节。这正是 ECS 组件化架构的最大价值所在。
