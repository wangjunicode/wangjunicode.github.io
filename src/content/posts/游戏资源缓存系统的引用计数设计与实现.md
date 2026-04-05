---
title: 游戏资源缓存系统的引用计数设计与实现
published: 2026-03-31
description: 深入解析基于引用计数的资源缓存机制，理解 Borrow/Return 模式如何避免资源泄漏和重复加载，以及加载器组件的分层设计思路。
tags: [Unity, 资源管理, 引用计数, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么资源管理是游戏开发的难题？

刚入行的同学可能觉得资源加载很简单：`Resources.Load` 或者 `Addressables.LoadAssetAsync`，获取到对象就行了。

但在大型项目中，资源管理的复杂度远超想象：

1. **同一资源被多个系统同时使用**：场景中有 5 个角色使用同一套装备贴图，何时卸载？
2. **异步加载的竞争**：同一资源被同时发起两次加载请求，应该加载几次？
3. **内存泄漏**：加载后忘记卸载，内存持续增长。
4. **过早卸载**：还有人在用的资源被卸载，导致空引用崩溃。

**引用计数（Reference Counting）** 是解决这些问题的经典方案。

---

## 引用计数的基本思想

引用计数的规则极其简单：

> 每次有人"借用"资源，计数 +1；每次有人"归还"资源，计数 -1；计数归零时，自动释放资源。

就像图书馆借书：借出一本 +1，还书 -1，没有人借的书就可以下架了。

---

## AssetCache 的设计

`AssetCache.cs` 是框架资源缓存的核心，基于引用计数实现：

```csharp
public class ObjectInfo
{
    public int refCnt;    // 引用计数
    public object obj;    // 实际资源对象
}

public class AssetCache
{
    private static Dictionary<string, ObjectInfo> s_objectDict = new();
    
    // 借用资源（引用计数 +1）
    public static ObjectInfo Borrow(string path)
    {
        ObjectInfo info = null;
        if (!s_objectDict.TryGetValue(path, out info))
        {
            info = new ObjectInfo();  // 首次访问，创建条目
        }
        info.refCnt++;
        s_objectDict[path] = info;
        return info;
    }
    
    // 归还资源（引用计数 -1，归零时释放）
    public static void Return(string path)
    {
        if (s_objectDict.TryGetValue(path, out var info))
        {
            info.refCnt--;
            if (info.refCnt <= 0)
            {
                if (info.obj != null)
                {
                    AssetDelegates.OnReleaseAsset?.Invoke(info.obj);  // 释放底层资源
                    info.obj = null;
                }
                s_objectDict.Remove(path);  // 从缓存中移除
            }
        }
    }
}
```

`ObjectInfo` 只有两个字段：计数和资源对象。这是最精简的引用计数实现。

---

## 获取缓存资源的三种方式

系统提供了三个不同语义的获取方法：

### 1. `GetCachedAsset<T>`：纯粹读取，不触发加载

```csharp
public static T GetCachedAsset<T>(string path) where T : class
{
    lock (s_objectDict)
    {
        return s_objectDict.TryGetValue(path, out var info) ? info.obj as T : null;
    }
}
```

只读缓存，没有就返回 null，不做任何其他操作。适合"检查是否已缓存"的场景。

### 2. `GetCachedAssetAutoLoad<T>`：读取+编辑器保底加载

```csharp
public static T GetCachedAssetAutoLoad<T>(string path) where T : class
{
    lock (s_objectDict)
    {
#if UNITY_EDITOR
        if (!EngineDefine.DeepProfileMode)
        {
            if (!s_objectDict.ContainsKey(path))
            {
                bool isConfig = path.EndsWith(".json") || path.EndsWith(".bytes");
                Log.Warning(ZString.Format("保底加载{0}", path));
                AssetDelegates.LoadFunc?.Invoke(path, isConfig);
            }
        }
#endif
        return s_objectDict.TryGetValue(path, out var info) ? info.obj as T : null;
    }
}
```

在编辑器模式下，如果资源未缓存，会自动触发同步加载（"保底加载"）。这是为了方便开发调试，正式发包时该逻辑不会执行。

### 3. `HasCachedAsset`：仅检查是否存在

```csharp
public static bool HasCachedAsset(string path)
{
    return s_objectDict.ContainsKey(path);
}
```

---

## 加载器的分层架构

`LoaderComponent.cs` 是资源加载的上层调度：

```csharp
public class LoaderComponent : Singleton<LoaderComponent>
{
    public List<ALoader> DynamicLoaders = new();
    private Dictionary<string, ALoader> _loaderMap = new();
    
    // 获取或创建一个 Loader（动态资源加载器）
    public ALoader Get(string name)
    {
        if (!_loaderMap.TryGetValue(name, out var loader))
        {
            loader = CreateLoader(name);
        }
        return loader;
    }
    
    // 释放 Loader（卸载其管理的所有资源）
    public void Release(ALoader loader)
    {
        loader.Release();
        DynamicLoaders.Remove(loader);
        _loaderMap.Remove(loader.Name);
    }
}
```

`ALoader` 是加载器的基类，每个 Loader 管理一批资源。这种设计允许"按模块"管理资源生命周期：

```
场景 Loader  → 管理该场景的所有资源
角色 Loader  → 管理一个角色的所有资源
动态 Loader  → 管理按路径动态加载的资源
```

卸载某个模块时，只需 `LoaderComponent.Release(sceneLoader)`，该 Loader 管理的所有资源会自动释放。

---

## LoaderManageComponent：自动清理管理器

`LoaderManageComponent.cs` 实现了基于"权重"的自动清理策略：

```csharp
public class LoaderManageComponent : Singleton<LoaderManageComponent>
{
    public int WEIGHT_LIMIT = 10000;
    
    public void ManageLoaders()
    {
        int curWeight = 0;
        for (int i = LoaderComponent.Instance.DynamicLoaders.Count - 1; i >= 0; i--)
        {
            var loader = LoaderComponent.Instance.DynamicLoaders[i];
            curWeight += loader.ResCache.Count;
            if (curWeight > WEIGHT_LIMIT)
            {
                Log.Info($"Loader清理: {loader}");
                LoaderComponent.Instance.Release(loader);
            }
        }
    }
}
```

逻辑是：遍历所有动态加载器，累计它们持有的资源数量（权重）。当总权重超过 10000 时，逆序清理超出的 Loader。

**逆序清理的原因**：动态 Loader 通常按使用时间顺序排列，逆序就是先清理最早（最少最近使用）的 Loader，这是 LRU（Least Recently Used）缓存淘汰策略的近似实现。

---

## 资源加载的完整流程

以 `ResManager.LoadAsync<T>` 为例，追踪一次完整的资源加载：

```csharp
public static async ETTask<T> LoadAsync<T>(string path, bool isConfig = false) where T : Object
{
    // 1. 优先查缓存
    T go = AssetCache.GetCachedAssetAutoLoad<T>(path);
    if (go != null)
    {
        return go;  // 缓存命中，直接返回
    }

    // 2. 构建 Loader
    var loader = LoaderComponent.Instance.Get(ZString.Format("dynamic_{0}", path));
    
    // 3. 添加加载任务
    loader.AddLoadTask(path);
    
    // 4. 异步加载（等待完成）
    await loader.StartLoadTaskAsync(null);
    
    // 5. 从缓存中获取（加载完成后已写入缓存）
    go = AssetCache.GetCachedAssetAutoLoad<T>(path);
    return go;
}
```

注意这里的设计：加载完成后不是直接返回 handle 的结果，而是**再次查询缓存**。这是因为 `ALoader` 内部会调用 `AssetCache.Borrow()` 将资源写入缓存，所以通过缓存获取能确保引用计数正确更新。

---

## SetCachedAsset：热更新资源的关键接口

```csharp
public static void SetCachedAsset<T>(string path, T newData) where T : class
{
    lock (s_objectDict)
    {
        if (s_objectDict.ContainsKey(path))
        {
            s_objectDict[path].obj = newData;   // 只替换对象，不改变引用计数
        }
    }
}
```

这个方法允许在不改变引用计数的情况下更新缓存中的资源对象。这在**热更新**场景中极其有用：

- 热更新下载了新版本的资源
- 通过 `SetCachedAsset` 将新对象写入缓存
- 所有持有该资源的系统在下次使用时自动获得新版本

---

## 引用计数的常见陷阱

### 陷阱一：只借不还

```csharp
// ❌ 忘记归还
public async ETTask LoadCharacter(string path)
{
    AssetCache.Borrow(path);
    // 使用资源...
    // 忘记 Return！
}

// ✅ 正确：确保 Return（用 try-finally 或 IDisposable 包装）
public async ETTask LoadCharacter(string path, ETCancellationToken token)
{
    AssetCache.Borrow(path);
    try
    {
        // 使用资源...
        await SomeWork(token);
    }
    finally
    {
        AssetCache.Return(path);  // 无论如何都会执行
    }
}
```

### 陷阱二：重复 Return

```csharp
// ❌ 调用了两次 Return
AssetCache.Return(path);
AssetCache.Return(path);  // 引用计数变成负数或触发二次释放
```

**防御建议**：把 Borrow/Return 封装进 RAII 风格的 class：

```csharp
public class AssetHandle : IDisposable
{
    private string _path;
    
    public AssetHandle(string path)
    {
        _path = path;
        AssetCache.Borrow(path);
    }
    
    public T GetAsset<T>() where T : class
        => AssetCache.GetCachedAsset<T>(_path);
    
    public void Dispose()
    {
        if (_path != null)
        {
            AssetCache.Return(_path);
            _path = null;  // 防止重复 Return
        }
    }
}

// 使用
using (var handle = new AssetHandle("Characters/Hero"))
{
    var prefab = handle.GetAsset<GameObject>();
    // ...
}  // 离开 using 块自动 Return
```

### 陷阱三：跨线程访问

注意 `GetCachedAsset` 和 `GetCachedAssetAutoLoad` 都使用了 `lock (s_objectDict)`，但 `Borrow` 和 `Return` 没有加锁。在严格单线程环境（游戏主循环）中这没问题，但如果有后台线程加载的场景需要特别注意。

---

## 总结

这套资源缓存系统的设计原则：

| 原则 | 实现 |
|------|------|
| 引用计数避免泄漏 | Borrow +1，Return -1，归零释放 |
| 分层管理 | Loader → AssetCache 两层 |
| 按需清理 | LoaderManageComponent 权重清理 |
| 编辑器友好 | AutoLoad 保底，方便调试 |
| 热更新支持 | SetCachedAsset 无缝替换 |

资源管理是游戏稳定性的基石。掌握引用计数思维，是写出不泄内存、不崩溃的游戏程序的必备技能。
