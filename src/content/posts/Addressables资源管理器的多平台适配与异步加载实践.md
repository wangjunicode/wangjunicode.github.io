---
title: Addressables 资源管理器的多平台适配与异步加载实践
published: 2026-03-31
description: 深入解析基于 Addressables 的资源管理器设计，理解编辑器保底加载、运行时禁止同步加载和异步实例化的工程决策。
tags: [Unity, 资源管理, Addressables, 多平台适配]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## ResManager 的设计目标

`ResManager.cs` 是游戏中所有资源加载操作的统一入口。它的核心设计目标：

1. **统一接口**：业务代码不需要知道资源来自哪里（编辑器直接读文件 vs 运行时用 Addressables）
2. **防止同步加载**：游戏运行时禁止同步加载资源，强制使用异步
3. **编辑器保底**：编辑器开发期间提供便利的保底加载方案
4. **缓存集成**：与 `AssetCache` 无缝集成，避免重复加载

---

## 三套加载路径

### 路径一：编辑器同步加载（仅编辑器）

```csharp
#if UNITY_EDITOR
public static T EditorLoad<T>(string path, bool isConfig = false) where T : class
{
    if (isConfig)
    {
        // 配置文件：直接读文件系统
        path = Path.Combine(ConfigComponent.RootPath, path);
        return File.ReadAllText(path) as T;
    }
    
    // 资源：通过 Addressables 同步加载（WaitForCompletion）
    var handler = Addressables.LoadAssetAsync<T>(path);
    handler.WaitForCompletion();
    return handler.Result;
}
#endif
```

编辑器中 `WaitForCompletion()` 是允许的，因为编辑器不是实时游戏，短暂卡帧可以接受。

### 路径二：运行时同步加载（仅限非运行时）

```csharp
public static GameObject LoadPrefab(string path)
{
    // 1. 先查缓存
    var res = AssetCache.GetCachedAssetAutoLoad<GameObject>(path);
    if (res != null) return res;

    // 2. 运行时禁止同步加载！
    if (Application.isPlaying)
    {
        Log.Warning($"load asset({path}) synchronously in game is not allowed");
        return null;  // 直接返回 null，而不是真的加载
    }

    // 3. 编辑器非运行时：AssetDatabase 保底
#if UNITY_EDITOR
    return AssetDatabase.LoadAssetAtPath<GameObject>($"Assets/Bundles/{path}");
#endif
    
    // 4. 非编辑器非运行时（理论上不应该到这）
    return Addressables.LoadAssetAsync<GameObject>(path).WaitForCompletion();
}
```

**关键设计**：运行时调用同步加载 API **不会抛异常，而是记录警告并返回 null**。

这个设计看起来"奇怪"，但有深意：
- 如果直接抛异常，可能导致游戏崩溃，影响用户体验
- 返回 null 后，调用方会看到空引用，在调试时能定位到问题
- Warning 日志记录了问题发生的地方，便于修复

### 路径三：运行时异步加载（标准路径）

```csharp
public static async ETTask<GameObject> InstantiatePrefabAsync(
    GameObject prefab, 
    Transform parent = null, 
    bool worldPositionStays = false)
{
#if UNITY_2022_3_50
    // Unity 2022.3.50+ 支持真正的异步实例化
    AsyncInstantiateOperation<GameObject> request = 
        Object.InstantiateAsync(prefab, parent);
    
    while (!request.isDone)
    {
        if (TimerComponent.Instance != null)
        {
            await TimerComponent.Instance.WaitFrameAsync();  // 每帧检查
        }
        else
        {
            request.WaitForCompletion();  // 没有 TimerComponent 就同步等待
            break;
        }
    }
    
    return request.Result.Length > 0 ? request.Result[0] : null;
#else
    // 旧版 Unity：同步实例化（没有更好的方法）
    return Object.Instantiate(prefab, parent, worldPositionStays);
#endif
}
```

注意版本号宏 `#if UNITY_2022_3_50`——这是针对特定 Unity 版本的功能开关，`Object.InstantiateAsync` 是 Unity 2022.3.50+ 才支持的新特性。

---

## 资源存在性检查与缓存

```csharp
private static Dictionary<string, bool> assetExistCache = new();

public static bool AssetExist(string key)
{
    // 先查缓存（避免重复的 Addressables 查询）
    if (assetExistCache.TryGetValue(key, out var cachedExist))
        return cachedExist;
    
    cachedExist = _assetExists(key);
    assetExistCache[key] = cachedExist;
    return cachedExist;
}

private static bool _assetExists(string key)
{
    if (!Application.isPlaying) return false;
    
    foreach (var locator in Addressables.ResourceLocators)
    {
        if (locator.Locate(key, null, out _))
            return true;
    }
    return false;
}
```

Addressables 的 `Locate` 操作有一定开销，使用字典缓存结果，相同 key 的第二次查询是 O(1)。

**注意**：这个缓存不会过期。如果 Addressables 目录在运行时动态更新（如热更新添加新资源），缓存可能返回过期的 `false` 值。对于这种场景，需要在更新后调用 `assetExistCache.Clear()`。

---

## 编辑器与运行时的分支策略

`ResManager` 大量使用编译宏来区分行为：

```csharp
#if UNITY_EDITOR
    // 编辑器专属逻辑
    return AssetDatabase.LoadAssetAtPath<T>(path);
#else
    // 运行时逻辑
    return Addressables.LoadAssetAsync<T>(path).WaitForCompletion();
#endif
```

更细粒度的分支：

```csharp
#if UNITY_EDITOR && !ENABLE_ADDRESSABLES_IN_EDITOR
    // 编辑器中不用 Addressables（直接读文件更快）
    return EditorLoadDirect(path);
#elif UNITY_ANDROID
    // Android 特定处理（可能需要解压 StreamingAssets）
    return LoadFromStreamingAssets(path);
#else
    // 通用路径
    return Addressables.LoadAssetAsync<T>(path);
#endif
```

这种多平台适配策略是游戏开发的常态——不同平台的资源管理方式可能完全不同。

---

## 实例化的多种方式

```csharp
// 同步实例化（仅编辑器/预加载场景）
GameObject go = ResManager.InstantiatePrefabByPath("Characters/Hero");

// 异步实例化（游戏运行时）
GameObject go = await ResManager.InstantiatePrefabAsync(prefab, parent);
```

`InstantiatePrefabByPath` 内部先查缓存，再实例化：

```csharp
public static GameObject InstantiatePrefabByPath(string path)
{
    var prefab = AssetCache.GetCachedAssetAutoLoad<GameObject>(path);
    if (prefab == null) return null;
    return Object.Instantiate(prefab);
}
```

注意：`GetCachedAssetAutoLoad` 会触发"保底加载"（编辑器中自动加载未缓存的资源），所以这个方法在编辑器中是安全的。

---

## 总结

`ResManager` 展示了资源管理的几个核心工程决策：

| 决策 | 理由 |
|------|------|
| 运行时禁止同步加载 | 避免主线程卡顿 |
| 编辑器保底加载 | 开发便利，不影响发布性能 |
| 统一通过 AssetCache | 引用计数管理，避免资源泄漏 |
| 存在性检查缓存 | 避免 Addressables 重复查询开销 |
| 版本宏适配 | 利用新版 Unity 特性，兼容旧版 |

理解这套资源管理器的设计，是构建大型 Unity 游戏资源管线的基础。它把复杂的多平台、多模式资源加载逻辑封装在统一接口背后，让业务代码保持简洁。
