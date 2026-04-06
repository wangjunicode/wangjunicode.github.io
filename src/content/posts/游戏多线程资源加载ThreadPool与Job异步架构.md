---
title: 游戏多线程资源加载：ThreadPool与Job异步架构
published: 2026-03-31
description: 深入解析Unity游戏中多线程资源加载的完整方案，涵盖主线程与工作线程职责划分、ThreadPool资产解析、C# async/await与Unity协程的配合、加载优先级队列、内存预算控制，以及高性能大型游戏资源调度系统设计。
tags: [Unity, 多线程, 资源加载, 性能优化, 异步编程]
category: 性能优化
draft: false
encryptedKey:henhaoji123
---

## 一、Unity 线程模型

Unity 有严格的线程限制：

| 操作 | 允许线程 | 说明 |
|------|----------|------|
| Unity API (GameObject, Transform等) | 主线程 | 严禁在子线程调用 |
| 数学计算、算法 | 任意线程 | 无状态计算可并行 |
| 文件 IO | 任意线程 | 建议使用 Task/ThreadPool |
| Mesh 创建 | 主线程 | Mesh 数据处理可在子线程，创建在主线程 |
| Texture2D.LoadImage | 主线程 | 数据解码可在子线程 |
| JSON 解析 | 任意线程 | 纯 C# 操作 |
| AssetBundle.LoadAsset | 主线程 | AB 加载可用异步API |

---

## 二、高性能资源加载管道

```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

/// <summary>
/// 资源加载请求
/// </summary>
public class LoadRequest
{
    public string Path;
    public Type AssetType;
    public int Priority;              // 优先级（数值越小越优先）
    public Action<UnityEngine.Object> OnComplete;
    public Action<float> OnProgress;
    public CancellationToken CancelToken;
    
    // 内部状态
    internal byte[] RawData;          // 工作线程读取的原始数据
    internal LoadState State;
    
    public enum LoadState
    {
        Queued,       // 等待调度
        FileReading,  // 工作线程正在读文件
        MainThread,   // 等待主线程处理
        Done,
        Failed,
        Cancelled
    }
}

/// <summary>
/// 多线程资源加载管理器
/// </summary>
public class AsyncResourceLoader : MonoBehaviour
{
    private static AsyncResourceLoader instance;
    public static AsyncResourceLoader Instance => instance;

    [Header("并发配置")]
    [SerializeField] private int maxConcurrentReads = 4;    // 同时进行的文件读取数
    [SerializeField] private int mainThreadBudgetMs = 4;    // 每帧主线程处理时间预算（毫秒）
    [SerializeField] private int memoryCacheSizeMB = 256;   // 内存缓存大小

    // 请求队列（优先级队列）
    private SortedSet<LoadRequest> requestQueue = new SortedSet<LoadRequest>(
        Comparer<LoadRequest>.Create((a, b) =>
            a.Priority != b.Priority ? a.Priority - b.Priority :
            string.Compare(a.Path, b.Path)));
    
    // 主线程处理队列（工作线程准备好的数据）
    private ConcurrentQueue<LoadRequest> mainThreadQueue = new ConcurrentQueue<LoadRequest>();
    
    // 内存缓存
    private Dictionary<string, CacheEntry> memoryCache = new Dictionary<string, CacheEntry>();
    private long currentCacheSizeBytes;
    private long maxCacheSizeBytes;

    // 并发控制
    private SemaphoreSlim readSemaphore;
    
    private readonly object queueLock = new object();
    
    private System.Diagnostics.Stopwatch frameTimer = new System.Diagnostics.Stopwatch();

    void Awake()
    {
        instance = this;
        readSemaphore = new SemaphoreSlim(maxConcurrentReads, maxConcurrentReads);
        maxCacheSizeBytes = (long)memoryCacheSizeMB * 1024 * 1024;
    }

    void Update()
    {
        // 派发新的加载任务
        DispatchPendingRequests();
        
        // 主线程处理（有时间预算）
        ProcessMainThreadQueue();
    }

    /// <summary>
    /// 异步加载资源
    /// </summary>
    public Task<T> LoadAsync<T>(string path, int priority = 100,
        CancellationToken cancel = default) where T : UnityEngine.Object
    {
        // 先检查内存缓存
        if (memoryCache.TryGetValue(path, out var cached))
        {
            cached.LastAccessTime = Time.realtimeSinceStartup;
            return Task.FromResult(cached.Asset as T);
        }
        
        var tcs = new TaskCompletionSource<T>();
        
        var request = new LoadRequest
        {
            Path = path,
            AssetType = typeof(T),
            Priority = priority,
            CancelToken = cancel,
            OnComplete = asset => tcs.SetResult(asset as T),
        };
        
        // 注册取消
        cancel.Register(() =>
        {
            request.State = LoadRequest.LoadState.Cancelled;
            tcs.TrySetCanceled();
        });
        
        lock (queueLock)
            requestQueue.Add(request);
        
        return tcs.Task;
    }

    void DispatchPendingRequests()
    {
        lock (queueLock)
        {
            var toDispatch = new List<LoadRequest>();
            
            foreach (var req in requestQueue)
            {
                if (req.State == LoadRequest.LoadState.Queued)
                {
                    toDispatch.Add(req);
                    if (toDispatch.Count >= maxConcurrentReads) break;
                }
            }
            
            foreach (var req in toDispatch)
            {
                req.State = LoadRequest.LoadState.FileReading;
                requestQueue.Remove(req);
                _ = ReadFileAsync(req); // 异步执行，不等待
            }
        }
    }

    async Task ReadFileAsync(LoadRequest request)
    {
        await readSemaphore.WaitAsync(request.CancelToken);
        
        try
        {
            if (request.CancelToken.IsCancellationRequested) return;
            
            // 工作线程：读取文件字节
            string fullPath = Path.Combine(Application.streamingAssetsPath, request.Path);
            
            if (!File.Exists(fullPath))
            {
                request.State = LoadRequest.LoadState.Failed;
                mainThreadQueue.Enqueue(request);
                return;
            }
            
            request.RawData = await File.ReadAllBytesAsync(fullPath, request.CancelToken);
            
            // 如果是 JSON，可以在工作线程解析
            // 如果是图片，可以在工作线程解码像素数据
            
            // 告知主线程：我准备好了
            request.State = LoadRequest.LoadState.MainThread;
            mainThreadQueue.Enqueue(request);
        }
        catch (OperationCanceledException)
        {
            request.State = LoadRequest.LoadState.Cancelled;
        }
        catch (Exception e)
        {
            Debug.LogError($"[AsyncLoader] File read error: {request.Path}, {e.Message}");
            request.State = LoadRequest.LoadState.Failed;
            mainThreadQueue.Enqueue(request);
        }
        finally
        {
            readSemaphore.Release();
        }
    }

    void ProcessMainThreadQueue()
    {
        frameTimer.Restart();
        
        while (mainThreadQueue.TryDequeue(out var request))
        {
            // 检测帧时间预算
            if (frameTimer.ElapsedMilliseconds > mainThreadBudgetMs)
            {
                mainThreadQueue.Enqueue(request); // 放回队列下帧继续
                break;
            }
            
            if (request.State == LoadRequest.LoadState.Cancelled) continue;
            
            if (request.State == LoadRequest.LoadState.Failed)
            {
                request.OnComplete?.Invoke(null);
                continue;
            }
            
            // 主线程：根据类型创建 Unity 资产
            UnityEngine.Object asset = CreateAsset(request);
            
            if (asset != null)
            {
                // 存入缓存
                AddToCache(request.Path, asset);
                request.OnComplete?.Invoke(asset);
            }
        }
    }

    UnityEngine.Object CreateAsset(LoadRequest request)
    {
        if (request.RawData == null) return null;
        
        if (request.AssetType == typeof(Texture2D))
        {
            var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            texture.LoadImage(request.RawData);  // 主线程
            texture.Apply(false, true); // makeNoLongerReadable = true（释放CPU内存）
            return texture;
        }
        
        if (request.AssetType == typeof(TextAsset))
        {
            // TextAsset 直接包装文本
            return null; // Unity TextAsset 不能直接 new，需要用 AssetBundle
        }
        
        if (request.AssetType == typeof(AudioClip))
        {
            // AudioClip 需要用 UnityWebRequestMultimedia 加载
            // 这里是简化示例
            return null;
        }
        
        return null;
    }

    void AddToCache(string path, UnityEngine.Object asset)
    {
        // LRU 缓存淘汰
        long assetSize = EstimateAssetSize(asset);
        
        while (currentCacheSizeBytes + assetSize > maxCacheSizeBytes && memoryCache.Count > 0)
        {
            EvictLeastRecentlyUsed();
        }
        
        memoryCache[path] = new CacheEntry
        {
            Asset = asset,
            SizeBytes = assetSize,
            LastAccessTime = Time.realtimeSinceStartup
        };
        currentCacheSizeBytes += assetSize;
    }

    void EvictLeastRecentlyUsed()
    {
        string lruKey = null;
        float oldestTime = float.MaxValue;
        
        foreach (var kv in memoryCache)
        {
            if (kv.Value.LastAccessTime < oldestTime)
            {
                oldestTime = kv.Value.LastAccessTime;
                lruKey = kv.Key;
            }
        }
        
        if (lruKey != null)
        {
            currentCacheSizeBytes -= memoryCache[lruKey].SizeBytes;
            UnityEngine.Object.Destroy(memoryCache[lruKey].Asset);
            memoryCache.Remove(lruKey);
        }
    }

    long EstimateAssetSize(UnityEngine.Object asset)
    {
        if (asset is Texture2D tex)
            return tex.width * tex.height * 4L; // RGBA32
        return 1024; // 默认1KB
    }

    public void ClearCache()
    {
        foreach (var entry in memoryCache.Values)
            UnityEngine.Object.Destroy(entry.Asset);
        memoryCache.Clear();
        currentCacheSizeBytes = 0;
    }
    
    class CacheEntry
    {
        public UnityEngine.Object Asset;
        public long SizeBytes;
        public float LastAccessTime;
    }
}
```

---

## 三、async/await 与 Unity 协程的混合使用

```csharp
/// <summary>
/// 异步加载在 Unity MonoBehaviour 中的最佳实践
/// </summary>
public class AsyncLoadExample : MonoBehaviour
{
    async void Start()
    {
        // async void 在 Unity 中是安全的入口点
        // 但内部异常不会被传播，需要 try/catch
        
        try
        {
            await LoadGameResources();
        }
        catch (Exception e)
        {
            Debug.LogError($"资源加载失败: {e.Message}");
        }
    }

    async Task LoadGameResources()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        
        // 并行加载多个资源
        var textureTask = AsyncResourceLoader.Instance.LoadAsync<Texture2D>(
            "textures/hero.png", priority: 1, cts.Token);
        
        var configTask = LoadConfig(cts.Token);
        
        // 等待所有资源加载完成
        await Task.WhenAll(textureTask, configTask);
        
        // 切回主线程（Task 默认可能在工作线程回调）
        // 使用 UniTask 的 SwitchToMainThread 或自定义调度器
        
        Debug.Log("所有资源加载完成");
    }

    async Task<GameConfig> LoadConfig(CancellationToken cancel)
    {
        // 模拟异步配置加载
        await Task.Delay(100, cancel);
        return new GameConfig { Version = "1.0" };
    }
}

public class GameConfig { public string Version; }
```

---

## 四、加载进度与 Loading 页面

```csharp
/// <summary>
/// 加载进度管理（支持多阶段进度）
/// </summary>
public class LoadingProgressTracker
{
    private List<LoadingStage> stages = new List<LoadingStage>();
    private int currentStageIndex = 0;
    
    public float TotalProgress
    {
        get
        {
            if (stages.Count == 0) return 0f;
            float total = 0;
            float totalWeight = 0;
            foreach (var s in stages)
            {
                total += s.Progress * s.Weight;
                totalWeight += s.Weight;
            }
            return totalWeight > 0 ? total / totalWeight : 0f;
        }
    }
    
    public string CurrentStageName => 
        currentStageIndex < stages.Count ? stages[currentStageIndex].Name : "完成";
    
    public void AddStage(string name, float weight = 1f)
    {
        stages.Add(new LoadingStage { Name = name, Weight = weight });
    }
    
    public void UpdateStageProgress(int stageIndex, float progress)
    {
        if (stageIndex >= 0 && stageIndex < stages.Count)
        {
            stages[stageIndex].Progress = Mathf.Clamp01(progress);
            currentStageIndex = stageIndex;
        }
    }
    
    class LoadingStage
    {
        public string Name;
        public float Progress;
        public float Weight;
    }
}
```

---

## 五、性能指标

| 场景 | 主线程 IO | 多线程 IO |
|------|----------|----------|
| 加载 10MB 纹理 | ~120ms 主线程卡顿 | ~20ms 主线程（文件在工作线程读） |
| 解析 1000行 JSON | ~15ms 主线程 | ~15ms 工作线程（主线程不感知） |
| 同时加载 5 张纹理 | 串行 ~600ms | 并行 ~150ms |

多线程加载的核心收益：**主线程帧率平稳，加载时不掉帧**。
