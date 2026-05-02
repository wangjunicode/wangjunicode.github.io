---
title: 游戏客户端多线程资源加载与异步管线系统完全指南：Thread-Safe Asset Pipeline深度实践
published: 2026-05-02
description: 深度解析游戏客户端多线程资源加载管线设计，涵盖线程安全资产管理、异步加载调度、优先级队列、预加载策略、加载进度反馈、内存压力感知、与Addressables的深度整合，以及Unity Job System在资源处理中的应用，附完整工程代码。
tags: [资源加载, 多线程, 异步管线, Addressables, Job System, 性能优化, Unity]
category: 性能优化
draft: false
---

# 游戏客户端多线程资源加载与异步管线系统完全指南：Thread-Safe Asset Pipeline深度实践

## 概述

现代游戏的资源体量日益庞大，单帧加载模式已经无法满足流畅体验的需求。本文深度解析游戏客户端多线程资源加载管线的设计与实现：从基础的异步请求队列，到优先级调度、内存压力感知、预加载预测，再到与Unity Addressables的深度整合，帮助开发者构建工业级的资源加载系统。

## 一、资源加载系统架构设计

### 1.1 分层架构

```
┌─────────────────────────────────────┐
│           游戏业务层                  │
│  (UI、角色、场景 请求资源)              │
└──────────────┬──────────────────────┘
               │ LoadRequest
┌──────────────▼──────────────────────┐
│         请求调度层（Request Layer）   │
│  优先级队列、去重、依赖分析、预测预加载   │
└──────────────┬──────────────────────┘
               │ 分配给Worker
┌──────────────▼──────────────────────┐
│         异步工作线程池                │
│  IO线程：磁盘读取、Bundle解压         │
│  处理线程：纹理解压、Mesh构建          │
└──────────────┬──────────────────────┘
               │ MainThread回调
┌──────────────▼──────────────────────┐
│         主线程上传层                  │
│  GPU纹理上传、Asset对象创建            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│         缓存层（Cache Layer）         │
│  内存缓存、引用计数、LRU淘汰            │
└─────────────────────────────────────┘
```

### 1.2 加载请求优先级

```csharp
using System;

/// <summary>
/// 资源加载请求优先级
/// </summary>
public enum LoadPriority
{
    Critical = 0,    // 关键资源（阻塞游戏进程，如登录背景）
    High = 1,        // 高优先级（当前帧即将显示）
    Normal = 2,      // 普通优先级（预见性加载）
    Low = 3,         // 低优先级（后台预加载）
    Background = 4   // 后台预热（空闲时处理）
}

/// <summary>
/// 资源类型（影响加载策略）
/// </summary>
public enum AssetCategory
{
    Texture,
    Audio,
    Prefab,
    ScriptableObject,
    AnimationClip,
    Shader,
    Scene,
    Bundle
}

/// <summary>
/// 资源加载请求
/// </summary>
public class AssetLoadRequest
{
    public string Key;                   // Addressables键或路径
    public Type AssetType;              // 资源类型
    public LoadPriority Priority;        // 优先级
    public AssetCategory Category;       // 资源分类
    public Action<UnityEngine.Object> OnComplete;  // 加载完成回调
    public Action<float> OnProgress;    // 进度回调
    public Action<string> OnError;      // 错误回调
    public float SubmitTime;            // 提交时间（用于调试）
    public string RequesterId;          // 请求方标识（调试用）
    public bool AllowCache = true;      // 是否允许缓存
    public int TimeoutSeconds = 30;     // 超时时间
    internal int _retryCount = 0;       // 重试次数
    internal const int MAX_RETRY = 3;

    public AssetLoadRequest(string key, Type assetType, LoadPriority priority = LoadPriority.Normal)
    {
        Key = key;
        AssetType = assetType;
        Priority = priority;
        SubmitTime = UnityEngine.Time.realtimeSinceStartup;
    }
}
```

## 二、线程安全优先级队列

### 2.1 请求队列实现

```csharp
using System;
using System.Collections.Generic;
using System.Threading;

/// <summary>
/// 线程安全的优先级加载队列
/// 支持多优先级分桶，高优先级请求可插队
/// </summary>
public class ThreadSafeLoadQueue
{
    // 按优先级分桶存储（0=Critical, 4=Background）
    private readonly Queue<AssetLoadRequest>[] _buckets;
    private readonly int _bucketCount;
    private readonly object _lock = new object();
    private readonly SemaphoreSlim _semaphore; // 通知Worker有新任务

    // 去重表（同一资源不重复加载）
    private readonly HashSet<string> _pendingKeys = new HashSet<string>();
    // 等待同一资源的多个回调
    private readonly Dictionary<string, List<Action<UnityEngine.Object>>> _pendingCallbacks
        = new Dictionary<string, List<Action<UnityEngine.Object>>>();

    public int TotalPending
    {
        get
        {
            lock (_lock)
            {
                int count = 0;
                foreach (var bucket in _buckets)
                    count += bucket.Count;
                return count;
            }
        }
    }

    public ThreadSafeLoadQueue(int maxConcurrent = 4)
    {
        _bucketCount = Enum.GetValues(typeof(LoadPriority)).Length;
        _buckets = new Queue<AssetLoadRequest>[_bucketCount];
        for (int i = 0; i < _bucketCount; i++)
            _buckets[i] = new Queue<AssetLoadRequest>();
        _semaphore = new SemaphoreSlim(0, int.MaxValue);
    }

    /// <summary>
    /// 提交加载请求（线程安全）
    /// </summary>
    public void Enqueue(AssetLoadRequest request)
    {
        lock (_lock)
        {
            // 去重处理
            if (_pendingKeys.Contains(request.Key))
            {
                // 资源正在加载中，注册回调等待完成
                if (!_pendingCallbacks.ContainsKey(request.Key))
                    _pendingCallbacks[request.Key] = new List<Action<UnityEngine.Object>>();

                if (request.OnComplete != null)
                    _pendingCallbacks[request.Key].Add(request.OnComplete);

                // 如果新请求优先级更高，升级已有请求的优先级
                UpgradePriority(request.Key, request.Priority);
                return;
            }

            _pendingKeys.Add(request.Key);
            int bucketIndex = (int)request.Priority;
            _buckets[bucketIndex].Enqueue(request);
        }

        // 通知Worker线程有新任务
        _semaphore.Release();
    }

    /// <summary>
    /// 取出优先级最高的请求（会阻塞直到有任务，或超时返回null）
    /// </summary>
    public AssetLoadRequest Dequeue(int timeoutMs = 1000)
    {
        if (!_semaphore.Wait(timeoutMs))
            return null;

        lock (_lock)
        {
            for (int i = 0; i < _bucketCount; i++)
            {
                if (_buckets[i].Count > 0)
                {
                    var request = _buckets[i].Dequeue();
                    return request;
                }
            }
        }
        return null;
    }

    /// <summary>
    /// 资源加载完成，通知所有等待的回调
    /// </summary>
    public void NotifyCompleted(string key, UnityEngine.Object asset)
    {
        List<Action<UnityEngine.Object>> callbacks = null;

        lock (_lock)
        {
            _pendingKeys.Remove(key);
            _pendingCallbacks.TryGetValue(key, out callbacks);
            _pendingCallbacks.Remove(key);
        }

        // 在主线程执行所有回调
        if (callbacks != null)
        {
            foreach (var cb in callbacks)
                cb?.Invoke(asset);
        }
    }

    private void UpgradePriority(string key, LoadPriority newPriority)
    {
        // 找到并移动到更高优先级桶
        for (int i = (int)newPriority + 1; i < _bucketCount; i++)
        {
            var tempQueue = new Queue<AssetLoadRequest>(_buckets[i]);
            _buckets[i].Clear();
            AssetLoadRequest foundRequest = null;

            while (tempQueue.Count > 0)
            {
                var req = tempQueue.Dequeue();
                if (req.Key == key)
                {
                    foundRequest = req;
                }
                else
                {
                    _buckets[i].Enqueue(req);
                }
            }

            if (foundRequest != null)
            {
                foundRequest.Priority = newPriority;
                _buckets[(int)newPriority].Enqueue(foundRequest);
                return;
            }
        }
    }

    public void Clear()
    {
        lock (_lock)
        {
            foreach (var bucket in _buckets)
                bucket.Clear();
            _pendingKeys.Clear();
            _pendingCallbacks.Clear();
        }
    }
}
```

## 三、核心加载管线实现

### 3.1 资源加载管线管理器

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;

/// <summary>
/// 游戏资源加载管线核心管理器
/// 基于Addressables + 优先级队列 + 内存感知
/// </summary>
public class AssetPipelineManager : MonoBehaviour
{
    private static AssetPipelineManager _instance;
    public static AssetPipelineManager Instance => _instance;

    [Header("加载配置")]
    [SerializeField] private int _maxConcurrentLoads = 6;        // 最大并发加载数
    [SerializeField] private int _mainThreadBudgetMs = 4;        // 主线程每帧预算（毫秒）
    [SerializeField] private float _memoryPressureThreshold = 0.85f; // 内存压力阈值（系统内存使用率）
    [SerializeField] private bool _enablePreloading = true;

    // 核心组件
    private ThreadSafeLoadQueue _loadQueue;
    private AssetCacheManager _cacheManager;
    private LoadingProgressTracker _progressTracker;

    // 当前活跃的加载操作
    private readonly Dictionary<string, AsyncOperationHandle> _activeHandles
        = new Dictionary<string, AsyncOperationHandle>();
    private readonly object _handlesLock = new object();

    // 并发控制
    private SemaphoreSlim _concurrencySemaphore;

    // 帧预算计时器
    private System.Diagnostics.Stopwatch _frameTimer = new System.Diagnostics.Stopwatch();

    // 内存感知
    private float _lastMemoryCheck = 0;
    private bool _memoryPressure = false;
    private const float MEMORY_CHECK_INTERVAL = 5f;

    // 统计
    public struct LoadStats
    {
        public int TotalRequests;
        public int CacheHits;
        public int LoadErrors;
        public float AverageLoadTimeMs;
        public int ActiveLoads;
    }
    private LoadStats _stats;

    private void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);

        _loadQueue = new ThreadSafeLoadQueue();
        _cacheManager = new AssetCacheManager(512); // 512MB缓存上限
        _progressTracker = new LoadingProgressTracker();
        _concurrencySemaphore = new SemaphoreSlim(_maxConcurrentLoads, _maxConcurrentLoads);

        StartCoroutine(ProcessLoadQueue());
        StartCoroutine(MonitorMemoryPressure());
    }

    /// <summary>
    /// 加载资源（主要入口）
    /// </summary>
    public void LoadAsset<T>(
        string key,
        Action<T> onComplete,
        LoadPriority priority = LoadPriority.Normal,
        Action<float> onProgress = null,
        string requesterId = null) where T : UnityEngine.Object
    {
        _stats.TotalRequests++;

        // 优先检查缓存
        if (_cacheManager.TryGetCached<T>(key, out T cached))
        {
            _stats.CacheHits++;
            onComplete?.Invoke(cached);
            return;
        }

        var request = new AssetLoadRequest(key, typeof(T), priority)
        {
            OnComplete = (obj) => onComplete?.Invoke(obj as T),
            OnProgress = onProgress,
            RequesterId = requesterId ?? "Unknown"
        };

        _loadQueue.Enqueue(request);
    }

    /// <summary>
    /// 异步加载资源（async/await版本）
    /// </summary>
    public async Task<T> LoadAssetAsync<T>(
        string key,
        LoadPriority priority = LoadPriority.Normal) where T : UnityEngine.Object
    {
        // 检查缓存
        if (_cacheManager.TryGetCached<T>(key, out T cached))
            return cached;

        var tcs = new TaskCompletionSource<T>();

        LoadAsset<T>(key, (asset) =>
        {
            if (asset != null)
                tcs.TrySetResult(asset);
            else
                tcs.TrySetException(new Exception($"加载失败：{key}"));
        }, priority);

        return await tcs.Task;
    }

    /// <summary>
    /// 批量预加载（后台低优先级）
    /// </summary>
    public void PreloadAssets(IEnumerable<string> keys, Action onAllComplete = null)
    {
        if (!_enablePreloading || _memoryPressure) return;

        int remaining = 0;
        var keyList = new List<string>(keys);
        remaining = keyList.Count;

        if (remaining == 0)
        {
            onAllComplete?.Invoke();
            return;
        }

        foreach (var key in keyList)
        {
            LoadAsset<UnityEngine.Object>(key, (obj) =>
            {
                Interlocked.Decrement(ref remaining);
                if (remaining <= 0)
                    onAllComplete?.Invoke();
            }, LoadPriority.Background);
        }
    }

    /// <summary>
    /// 主循环：处理加载队列（在主线程执行，通过帧预算限制）
    /// </summary>
    private IEnumerator ProcessLoadQueue()
    {
        while (true)
        {
            _frameTimer.Restart();

            // 在帧预算内尽量处理请求
            while (_loadQueue.TotalPending > 0 && !_memoryPressure)
            {
                // 检查并发上限
                if (!_concurrencySemaphore.Wait(0))
                    break;

                AssetLoadRequest request = _loadQueue.Dequeue(0);
                if (request == null)
                {
                    _concurrencySemaphore.Release();
                    break;
                }

                // 启动异步加载（不阻塞主线程）
                StartCoroutine(LoadAssetCoroutine(request));

                // 检查帧预算
                if (_frameTimer.ElapsedMilliseconds >= _mainThreadBudgetMs)
                    break;
            }

            yield return null;
        }
    }

    private IEnumerator LoadAssetCoroutine(AssetLoadRequest request)
    {
        float startTime = Time.realtimeSinceStartup;
        _stats.ActiveLoads++;

        string key = request.Key;
        AsyncOperationHandle handle;

        try
        {
            // 使用Addressables加载
            handle = Addressables.LoadAssetAsync<UnityEngine.Object>(key);

            lock (_handlesLock)
                _activeHandles[key] = handle;
        }
        catch (Exception e)
        {
            Debug.LogError($"[AssetPipeline] 启动加载失败：{key} - {e.Message}");
            _stats.LoadErrors++;
            _stats.ActiveLoads--;
            _concurrencySemaphore.Release();
            request.OnError?.Invoke(e.Message);
            yield break;
        }

        // 等待加载完成，同时报告进度
        while (!handle.IsDone)
        {
            request.OnProgress?.Invoke(handle.PercentComplete);
            yield return null;
        }

        _stats.ActiveLoads--;
        _concurrencySemaphore.Release();

        lock (_handlesLock)
            _activeHandles.Remove(key);

        float loadTime = (Time.realtimeSinceStartup - startTime) * 1000f;

        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            var asset = handle.Result as UnityEngine.Object;

            // 更新缓存
            if (request.AllowCache)
                _cacheManager.Cache(key, asset);

            // 更新统计
            UpdateAverageLoadTime(loadTime);

            Debug.Log($"[AssetPipeline] 加载成功：{key} ({loadTime:F1}ms)");

            // 触发完成回调
            request.OnComplete?.Invoke(asset);

            // 通知等待同一资源的其他请求
            _loadQueue.NotifyCompleted(key, asset);
        }
        else
        {
            string error = handle.OperationException?.Message ?? "未知错误";
            Debug.LogError($"[AssetPipeline] 加载失败：{key} - {error}");
            _stats.LoadErrors++;

            // 重试逻辑
            if (request._retryCount < AssetLoadRequest.MAX_RETRY)
            {
                request._retryCount++;
                Debug.Log($"[AssetPipeline] 重试加载（第{request._retryCount}次）：{key}");
                _loadQueue.Enqueue(request);
            }
            else
            {
                request.OnError?.Invoke(error);
            }

            Addressables.Release(handle);
        }
    }

    private IEnumerator MonitorMemoryPressure()
    {
        while (true)
        {
            yield return new WaitForSeconds(MEMORY_CHECK_INTERVAL);

            // 获取系统内存使用情况
            long totalMemory = SystemInfo.systemMemorySize * 1024L * 1024L;
            long usedMemory = (long)(UnityEngine.Profiling.Profiler.GetTotalReservedMemoryLong());
            float usageRatio = (float)usedMemory / totalMemory;

            bool newPressureState = usageRatio > _memoryPressureThreshold;
            if (newPressureState != _memoryPressure)
            {
                _memoryPressure = newPressureState;
                if (_memoryPressure)
                {
                    Debug.LogWarning($"[AssetPipeline] 内存压力警告！使用率：{usageRatio:P1}，暂停后台预加载");
                    // 触发缓存清理
                    _cacheManager.EvictLRU(0.3f); // 清理30%的LRU缓存
                }
                else
                {
                    Debug.Log("[AssetPipeline] 内存压力解除，恢复预加载");
                }
            }
        }
    }

    private void UpdateAverageLoadTime(float newTimeMs)
    {
        _stats.AverageLoadTimeMs = (_stats.AverageLoadTimeMs * 0.9f) + (newTimeMs * 0.1f);
    }

    /// <summary>
    /// 释放资源（减少引用计数，引用为0时真正释放）
    /// </summary>
    public void ReleaseAsset(string key)
    {
        _cacheManager.Release(key);
    }

    /// <summary>
    /// 获取加载统计信息
    /// </summary>
    public LoadStats GetStats() => _stats;

    private void OnDestroy()
    {
        // 释放所有活跃的Addressables句柄
        lock (_handlesLock)
        {
            foreach (var handle in _activeHandles.Values)
            {
                if (handle.IsValid())
                    Addressables.Release(handle);
            }
            _activeHandles.Clear();
        }
    }
}
```

## 四、资源缓存管理器

### 4.1 LRU缓存 + 引用计数

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 资产缓存管理器
/// 实现LRU淘汰 + 引用计数，防止资源泄漏
/// </summary>
public class AssetCacheManager
{
    private class CacheEntry
    {
        public UnityEngine.Object Asset;
        public int RefCount;
        public float LastAccessTime;
        public long EstimatedSizeBytes;
        public string Key;
    }

    // LRU链表（最近使用在头部）
    private readonly LinkedList<string> _lruList = new LinkedList<string>();
    private readonly Dictionary<string, LinkedListNode<string>> _lruNodes
        = new Dictionary<string, LinkedListNode<string>>();
    private readonly Dictionary<string, CacheEntry> _cache = new Dictionary<string, CacheEntry>();

    private readonly long _maxCacheSizeBytes;
    private long _currentCacheSizeBytes = 0;
    private readonly object _lock = new object();

    // 缓存统计
    public int CachedCount => _cache.Count;
    public long CachedSizeMB => _currentCacheSizeBytes / (1024 * 1024);

    public AssetCacheManager(long maxSizeMB = 512)
    {
        _maxCacheSizeBytes = maxSizeMB * 1024 * 1024;
    }

    /// <summary>
    /// 缓存资源
    /// </summary>
    public void Cache(string key, UnityEngine.Object asset)
    {
        if (asset == null) return;

        long estimatedSize = EstimateSize(asset);

        lock (_lock)
        {
            if (_cache.TryGetValue(key, out CacheEntry existing))
            {
                // 更新访问时间
                existing.LastAccessTime = Time.realtimeSinceStartup;
                MoveToHead(key);
                return;
            }

            // 检查容量，必要时淘汰
            while (_currentCacheSizeBytes + estimatedSize > _maxCacheSizeBytes && _lruList.Count > 0)
            {
                EvictLRUEntry();
            }

            var entry = new CacheEntry
            {
                Asset = asset,
                RefCount = 1,
                LastAccessTime = Time.realtimeSinceStartup,
                EstimatedSizeBytes = estimatedSize,
                Key = key
            };

            _cache[key] = entry;
            _currentCacheSizeBytes += estimatedSize;

            var node = _lruList.AddFirst(key);
            _lruNodes[key] = node;
        }
    }

    /// <summary>
    /// 尝试获取缓存（同时增加引用计数）
    /// </summary>
    public bool TryGetCached<T>(string key, out T asset) where T : UnityEngine.Object
    {
        lock (_lock)
        {
            if (_cache.TryGetValue(key, out CacheEntry entry) && entry.Asset is T typedAsset)
            {
                entry.RefCount++;
                entry.LastAccessTime = Time.realtimeSinceStartup;
                MoveToHead(key);
                asset = typedAsset;
                return true;
            }
        }
        asset = null;
        return false;
    }

    /// <summary>
    /// 释放引用（引用计数减1，为0时从缓存移除并释放Addressables句柄）
    /// </summary>
    public void Release(string key)
    {
        lock (_lock)
        {
            if (!_cache.TryGetValue(key, out CacheEntry entry)) return;

            entry.RefCount--;
            if (entry.RefCount <= 0)
            {
                RemoveEntry(key);
            }
        }
    }

    /// <summary>
    /// 淘汰指定比例的LRU缓存（内存压力时调用）
    /// </summary>
    public void EvictLRU(float ratio = 0.3f)
    {
        lock (_lock)
        {
            int targetEvict = (int)(_lruList.Count * ratio);
            for (int i = 0; i < targetEvict; i++)
            {
                if (_lruList.Count == 0) break;
                string lastKey = _lruList.Last.Value;
                var entry = _cache[lastKey];

                // 有引用的不淘汰
                if (entry.RefCount > 0)
                {
                    // 跳过，找下一个
                    continue;
                }

                RemoveEntry(lastKey);
            }

            Debug.Log($"[AssetCache] LRU淘汰完成，当前缓存：{CachedCount}个，{CachedSizeMB}MB");
        }
    }

    private void EvictLRUEntry()
    {
        // 从尾部移除最久未使用的条目
        var node = _lruList.Last;
        while (node != null)
        {
            var entry = _cache[node.Value];
            if (entry.RefCount <= 0)
            {
                RemoveEntry(node.Value);
                return;
            }
            node = node.Previous;
        }
    }

    private void RemoveEntry(string key)
    {
        if (!_cache.TryGetValue(key, out CacheEntry entry)) return;

        _currentCacheSizeBytes -= entry.EstimatedSizeBytes;
        _cache.Remove(key);

        if (_lruNodes.TryGetValue(key, out var node))
        {
            _lruList.Remove(node);
            _lruNodes.Remove(key);
        }

        // 释放Addressables引用
        if (entry.Asset != null)
        {
            UnityEngine.AddressableAssets.Addressables.Release(entry.Asset);
        }
    }

    private void MoveToHead(string key)
    {
        if (!_lruNodes.TryGetValue(key, out var node)) return;
        _lruList.Remove(node);
        var newNode = _lruList.AddFirst(key);
        _lruNodes[key] = newNode;
    }

    private long EstimateSize(UnityEngine.Object asset)
    {
        // 根据资源类型估算大小
        return asset switch
        {
            Texture2D tex => tex.width * tex.height * 4L, // RGBA32
            AudioClip clip => (long)(clip.samples * clip.channels * 2), // PCM 16bit
            Mesh mesh => mesh.vertexCount * 48L, // 估算每顶点48字节
            _ => 1024 * 64 // 默认64KB
        };
    }

    /// <summary>
    /// 获取缓存详情（调试用）
    /// </summary>
    public string GetCacheReport()
    {
        lock (_lock)
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine($"=== Asset Cache Report ===");
            sb.AppendLine($"总计：{CachedCount}个，{CachedSizeMB}MB / {_maxCacheSizeBytes / 1024 / 1024}MB");
            foreach (var kvp in _cache)
            {
                var e = kvp.Value;
                sb.AppendLine($"  {kvp.Key}: RefCount={e.RefCount}, Size={e.EstimatedSizeBytes / 1024}KB, LastAccess={e.LastAccessTime:F1}s");
            }
            return sb.ToString();
        }
    }
}
```

## 五、预加载预测系统

### 5.1 基于场景图的预测预加载

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 预加载预测器：基于场景转换图预测并提前加载可能需要的资源
/// </summary>
public class PreloadPredictor : MonoBehaviour
{
    [System.Serializable]
    public class SceneResourceManifest
    {
        public string SceneName;
        public List<string> RequiredAssetKeys = new List<string>();
        public List<string> NextPossibleScenes = new List<string>();
    }

    [SerializeField] private List<SceneResourceManifest> _sceneManifests;

    // 场景资源图：场景名 -> 所需资源
    private Dictionary<string, SceneResourceManifest> _manifestMap
        = new Dictionary<string, SceneResourceManifest>();

    // 当前场景
    private string _currentScene;

    private void Start()
    {
        foreach (var manifest in _sceneManifests)
        {
            _manifestMap[manifest.SceneName] = manifest;
        }

        _currentScene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;

        // 立即预加载当前场景的资源
        PreloadForScene(_currentScene);
    }

    /// <summary>
    /// 通知即将切换到某场景（触发提前预加载）
    /// </summary>
    public void NotifySceneTransition(string nextSceneName)
    {
        Debug.Log($"[PreloadPredictor] 预测即将切换到：{nextSceneName}");
        PreloadForScene(nextSceneName);

        // 预加载下下个场景（更低优先级）
        if (_manifestMap.TryGetValue(nextSceneName, out var manifest))
        {
            foreach (var possibleNext in manifest.NextPossibleScenes)
            {
                if (_manifestMap.TryGetValue(possibleNext, out var nextManifest))
                {
                    // 极低优先级后台预热
                    AssetPipelineManager.Instance?.PreloadAssets(nextManifest.RequiredAssetKeys);
                }
            }
        }
    }

    private void PreloadForScene(string sceneName)
    {
        if (!_manifestMap.TryGetValue(sceneName, out var manifest)) return;

        Debug.Log($"[PreloadPredictor] 预加载场景资源：{sceneName}，共{manifest.RequiredAssetKeys.Count}个");

        // 分批次预加载，避免峰值IO
        StartCoroutine(BatchPreload(manifest.RequiredAssetKeys));
    }

    private System.Collections.IEnumerator BatchPreload(List<string> keys)
    {
        const int BATCH_SIZE = 5;
        for (int i = 0; i < keys.Count; i += BATCH_SIZE)
        {
            var batch = keys.GetRange(i, Mathf.Min(BATCH_SIZE, keys.Count - i));
            AssetPipelineManager.Instance?.PreloadAssets(batch);
            yield return new WaitForSeconds(0.5f); // 每批次间隔0.5s
        }
    }
}
```

## 六、加载进度追踪与UI集成

### 6.1 进度追踪器

```csharp
using System;
using System.Collections.Generic;

/// <summary>
/// 加载进度追踪器：聚合多个资源的加载进度，用于显示加载界面
/// </summary>
public class LoadingProgressTracker
{
    private class TrackEntry
    {
        public string Key;
        public float Progress;
        public bool IsComplete;
        public float Weight; // 权重（影响总进度计算）
    }

    private readonly Dictionary<string, TrackEntry> _entries = new Dictionary<string, TrackEntry>();
    private readonly object _lock = new object();

    public event Action<float> OnProgressChanged;
    public event Action OnAllComplete;

    public float TotalProgress
    {
        get
        {
            lock (_lock)
            {
                if (_entries.Count == 0) return 1f;
                float totalWeight = 0, completedWeight = 0;
                foreach (var e in _entries.Values)
                {
                    totalWeight += e.Weight;
                    completedWeight += e.Progress * e.Weight;
                }
                return totalWeight > 0 ? completedWeight / totalWeight : 1f;
            }
        }
    }

    /// <summary>
    /// 注册要追踪的资源
    /// </summary>
    public void Track(string key, float weight = 1f)
    {
        lock (_lock)
        {
            _entries[key] = new TrackEntry { Key = key, Weight = weight };
        }
    }

    /// <summary>
    /// 更新进度
    /// </summary>
    public void UpdateProgress(string key, float progress)
    {
        lock (_lock)
        {
            if (!_entries.TryGetValue(key, out var entry)) return;
            entry.Progress = UnityEngine.Mathf.Clamp01(progress);
        }

        OnProgressChanged?.Invoke(TotalProgress);
    }

    /// <summary>
    /// 标记完成
    /// </summary>
    public void MarkComplete(string key)
    {
        bool allDone = false;

        lock (_lock)
        {
            if (!_entries.TryGetValue(key, out var entry)) return;
            entry.Progress = 1f;
            entry.IsComplete = true;

            allDone = true;
            foreach (var e in _entries.Values)
            {
                if (!e.IsComplete) { allDone = false; break; }
            }
        }

        OnProgressChanged?.Invoke(TotalProgress);

        if (allDone)
        {
            OnAllComplete?.Invoke();
        }
    }

    public void Reset()
    {
        lock (_lock) { _entries.Clear(); }
    }
}
```

### 6.2 加载界面集成示例

```csharp
using UnityEngine;
using UnityEngine.UI;
using System.Collections.Generic;

/// <summary>
/// 加载界面控制器：展示资源加载进度
/// </summary>
public class LoadingScreenController : MonoBehaviour
{
    [SerializeField] private Slider _progressBar;
    [SerializeField] private Text _progressText;
    [SerializeField] private Text _loadingTipText;
    [SerializeField] private string[] _loadingTips;

    private LoadingProgressTracker _tracker;
    private float _displayProgress = 0f;
    private const float PROGRESS_LERP_SPEED = 2f;

    private void OnEnable()
    {
        // 随机加载提示
        if (_loadingTipText != null && _loadingTips.Length > 0)
        {
            _loadingTipText.text = _loadingTips[Random.Range(0, _loadingTips.Length)];
        }
    }

    public void StartLoading(List<string> assetKeys, System.Action onComplete = null)
    {
        _tracker = new LoadingProgressTracker();
        _tracker.OnProgressChanged += UpdateDisplay;
        _tracker.OnAllComplete += () =>
        {
            Debug.Log("[LoadingScreen] 所有资源加载完成");
            onComplete?.Invoke();
        };

        // 注册所有要追踪的资源
        foreach (var key in assetKeys)
        {
            _tracker.Track(key);
        }

        // 发起加载请求
        foreach (var key in assetKeys)
        {
            string capturedKey = key;
            AssetPipelineManager.Instance?.LoadAsset<UnityEngine.Object>(
                key,
                (_) => _tracker.MarkComplete(capturedKey),
                LoadPriority.High,
                (progress) => _tracker.UpdateProgress(capturedKey, progress)
            );
        }
    }

    private void Update()
    {
        // 平滑进度条（避免跳跃）
        if (_tracker != null)
        {
            float targetProgress = _tracker.TotalProgress;
            _displayProgress = Mathf.Lerp(_displayProgress, targetProgress, Time.deltaTime * PROGRESS_LERP_SPEED);

            if (_progressBar != null)
                _progressBar.value = _displayProgress;

            if (_progressText != null)
                _progressText.text = $"{(_displayProgress * 100):F0}%";
        }
    }

    private void UpdateDisplay(float progress)
    {
        // 进度变化在主线程处理（Update中平滑）
    }
}
```

## 七、Unity Job System在资源处理中的应用

### 7.1 Job加速纹理处理

```csharp
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using Unity.Burst;

/// <summary>
/// 使用Job System并行处理纹理通道分离（多线程安全）
/// 例如：从RGBA纹理中分离出金属度/粗糙度通道
/// </summary>
[BurstCompile]
public struct TextureChannelSplitJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<Color32> SourcePixels;
    [WriteOnly] public NativeArray<Color32> MetallicOutput;  // R=金属度, A=平滑度
    [WriteOnly] public NativeArray<Color32> OcclusionOutput; // G=遮蔽

    public void Execute(int index)
    {
        Color32 src = SourcePixels[index];

        // 分离通道
        MetallicOutput[index] = new Color32(src.r, src.r, src.r, src.a);
        OcclusionOutput[index] = new Color32(src.g, src.g, src.g, 255);
    }
}

/// <summary>
/// 纹理通道分离工具
/// </summary>
public static class TextureJobProcessor
{
    /// <summary>
    /// 异步分离纹理通道（不阻塞主线程）
    /// </summary>
    public static System.Collections.IEnumerator SplitTextureChannelsAsync(
        Texture2D source,
        System.Action<Texture2D, Texture2D> onComplete)
    {
        int pixelCount = source.width * source.height;

        // 在主线程获取像素数据
        var sourcePixels = new NativeArray<Color32>(source.GetPixels32(), Allocator.TempJob);
        var metallicPixels = new NativeArray<Color32>(pixelCount, Allocator.TempJob);
        var occlusionPixels = new NativeArray<Color32>(pixelCount, Allocator.TempJob);

        var job = new TextureChannelSplitJob
        {
            SourcePixels = sourcePixels,
            MetallicOutput = metallicPixels,
            OcclusionOutput = occlusionPixels
        };

        // 并行调度（在Job线程执行，不阻塞主线程）
        JobHandle handle = job.Schedule(pixelCount, 64);

        // 等待完成（不使用WaitForCompletion，让主线程继续渲染）
        while (!handle.IsCompleted)
            yield return null;

        handle.Complete();

        // 创建纹理（必须在主线程）
        Texture2D metallicTex = new Texture2D(source.width, source.height, TextureFormat.RGBA32, false);
        metallicTex.SetPixels32(metallicPixels.ToArray());
        metallicTex.Apply();

        Texture2D occlusionTex = new Texture2D(source.width, source.height, TextureFormat.R8, false);
        occlusionTex.SetPixels32(occlusionPixels.ToArray());
        occlusionTex.Apply();

        // 释放Native内存
        sourcePixels.Dispose();
        metallicPixels.Dispose();
        occlusionPixels.Dispose();

        onComplete?.Invoke(metallicTex, occlusionTex);
    }
}
```

## 八、最佳实践总结

### 8.1 加载系统设计检查清单

```
✅ 架构设计
  □ 业务层只通过统一接口请求资源，不直接调用Addressables
  □ 优先级系统覆盖所有加载场景（Critical/High/Normal/Low/Background）
  □ 请求去重：同一资源多次请求只加载一次
  □ 引用计数与手动释放结合防止内存泄漏

✅ 性能控制
  □ 限制每帧主线程加载时间（帧预算 2-4ms）
  □ 并发加载数量不超过系统IO能力（4-8为宜）
  □ 内存压力监控，自动降级为同步模式
  □ 进度回调在主线程执行，UI访问安全

✅ 缓存策略
  □ LRU淘汰优先释放最久未使用的资源
  □ 引用计数不为0的资源不会被淘汰
  □ 缓存容量上限结合设备内存动态设置
  □ 场景切换时主动释放无关缓存

✅ 预加载策略
  □ 场景加载完成前预先加载下个场景资源
  □ 分批次提交预加载请求，避免IO峰值
  □ 内存压力时自动暂停预加载
  □ 玩家行为预测：进入特定区域触发相关资源预热

✅ 错误处理
  □ 加载失败自动重试（最多3次）
  □ 超时检测（默认30秒）
  □ 降级策略：Addressables失败时尝试本地Resources
  □ 错误上报到监控系统
```

### 8.2 典型性能数据参考

| 场景 | 推荐配置 |
|------|---------|
| 移动端低配 | maxConcurrent=2, frameBudget=2ms, cache=128MB |
| 移动端中配 | maxConcurrent=4, frameBudget=3ms, cache=256MB |
| PC端 | maxConcurrent=8, frameBudget=4ms, cache=512MB |
| 主机端 | maxConcurrent=6, frameBudget=3ms, cache=1024MB |

## 九、总结

多线程资源加载管线是现代游戏客户端架构的关键基础设施。通过合理的优先级调度、并发控制、LRU缓存和预加载预测，可以将资源加载的等待感降至最低。

**核心要点：**
1. **分层架构**：业务层 → 调度层 → 执行层 → 缓存层，职责分离
2. **优先级队列**去重合并，避免重复加载和IO浪费
3. **帧预算控制**，防止加载逻辑抢占渲染时间
4. **引用计数 + LRU**双重缓存策略，平衡命中率与内存占用
5. **内存压力感知**，动态调整加载策略防止OOM
6. **Job System**加速离线资源处理，充分利用多核CPU
