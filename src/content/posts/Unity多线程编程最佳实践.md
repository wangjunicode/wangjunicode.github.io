---
title: Unity 多线程编程：Job System 与 async/await 最佳实践
published: 2026-03-21
description: "深入讲解 Unity 中的多线程编程模式，包括 Task/async/await 的正确使用、UniTask 的性能优势、Job System 的多核并行计算、线程安全设计，以及在游戏开发中常见的并发陷阱与解决方案。"
tags: [多线程, async/await, UniTask, Job System, Unity]
category: 技术基础
draft: false
---

## Unity 多线程的特殊性

```
Unity 的线程模型：
  主线程（Main Thread）：所有 Unity API 调用必须在这里
    - Transform、GameObject、Component 的访问
    - 物理、渲染、音频
    - MonoBehaviour 的生命周期方法
    
  后台线程：可以做纯计算工作
    - 网络 I/O
    - 文件读写
    - 数据计算（不涉及 Unity API）
    - 图像处理

常见错误：
❌ 在后台线程中访问 transform.position
❌ 在 async 方法中忘记切回主线程
❌ 多线程访问同一个非线程安全集合
```

---

## 一、async/await 基础

### 1.1 Task vs UniTask

```csharp
// Task（C# 标准）：在 Unity 中的问题
// 1. Task 使用线程池，切回 Unity 主线程麻烦
// 2. Task 对象在 IL2CPP 下有 GC 开销
// 3. Task 没有 PlayerLoop 集成（不能在 Update 阶段执行）

// ❌ Task 在 Unity 中的问题示例
async Task LoadDataBad()
{
    var data = await File.ReadAllTextAsync("path");
    
    // 问题：这里可能在任意线程执行，不一定是主线程！
    gameObject.SetActive(true); // 危险！可能在非主线程访问 Unity API
}

// ✅ UniTask（推荐）：专为 Unity 设计
// - 基于值类型，零 GC 分配
// - 与 PlayerLoop 集成（Update、FixedUpdate、LateUpdate 阶段）
// - 自动在主线程恢复

using Cysharp.Threading.Tasks;

async UniTask LoadDataGood()
{
    // 切换到后台线程做 I/O
    await UniTask.SwitchToThreadPool();
    var data = await File.ReadAllTextAsync("path");
    
    // 切回主线程
    await UniTask.SwitchToMainThread();
    
    // 现在安全地访问 Unity API
    gameObject.SetActive(true);
}
```

### 1.2 UniTask 常用 API

```csharp
// 等待一帧
await UniTask.NextFrame();
await UniTask.Yield(); // 等价

// 等待指定帧数
await UniTask.DelayFrame(5);

// 等待时间（与 Time.timeScale 有关）
await UniTask.Delay(TimeSpan.FromSeconds(1f));
await UniTask.Delay(1000); // 1000ms

// 等待时间（不受 timeScale 影响）
await UniTask.Delay(1000, ignoreTimeScale: true);

// 等待条件（轮询）
await UniTask.WaitUntil(() => isReady);
await UniTask.WaitWhile(() => isLoading);

// 等待 Unity 事件（UnityEvent/button.onClick）
await button.OnClickAsync();

// 等待多个 Task
await UniTask.WhenAll(task1, task2, task3); // 全部完成
await UniTask.WhenAny(task1, task2, task3); // 任意一个完成

// 超时
var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5f));
try
{
    await SomeOperation(cts.Token);
}
catch (OperationCanceledException)
{
    Debug.Log("操作超时");
}

// 在 PlayerLoop 的特定阶段执行
await UniTask.Yield(PlayerLoopTiming.FixedUpdate);
await UniTask.Yield(PlayerLoopTiming.LateUpdate);
```

### 1.3 取消令牌的正确使用

```csharp
public class EnemyAI : MonoBehaviour
{
    private CancellationTokenSource _cts;
    
    void OnEnable()
    {
        // 组件启用时创建新的 CancellationTokenSource
        _cts = new CancellationTokenSource();
        RunAILoop(_cts.Token).Forget();
    }
    
    void OnDisable()
    {
        // 组件禁用时取消所有异步操作
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
    }
    
    private async UniTaskVoid RunAILoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                // 执行 AI 逻辑
                await Think(ct);
                await Act(ct);
            }
            catch (OperationCanceledException)
            {
                // 正常取消，不是错误
                break;
            }
            catch (Exception e)
            {
                Debug.LogError($"AI Error: {e.Message}");
                await UniTask.Delay(1000, cancellationToken: ct); // 出错后等待一秒再试
            }
        }
    }
    
    private async UniTask Think(CancellationToken ct)
    {
        // 等待 200ms（AI 思考时间）
        await UniTask.Delay(200, cancellationToken: ct);
        // 做决策...
    }
    
    private async UniTask Act(CancellationToken ct)
    {
        // 执行行动
        await UniTask.Delay(500, cancellationToken: ct);
    }
    
    // Unity 推荐：使用 destroyCancellationToken
    // 这个 Token 在 GameObject 被 Destroy 时自动取消
    async void Start()
    {
        await DoSomething(this.destroyCancellationToken);
    }
    
    async UniTask DoSomething(CancellationToken ct)
    {
        await UniTask.Delay(1000, cancellationToken: ct);
        // 不需要检查 gameObject.activeSelf，Token 自动处理
        Debug.Log("Done!");
    }
}
```

---

## 二、线程安全设计

### 2.1 主线程调度器

```csharp
/// <summary>
/// 主线程调度器：允许后台线程将工作分发到主线程执行
/// </summary>
public class MainThreadDispatcher : MonoBehaviour
{
    private static readonly Queue<Action> _pending = new();
    private static readonly object _lock = new();
    
    private static MainThreadDispatcher _instance;
    
    void Awake()
    {
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }
    
    void Update()
    {
        lock (_lock)
        {
            while (_pending.Count > 0)
            {
                _pending.Dequeue().Invoke();
            }
        }
    }
    
    /// <summary>
    /// 从任意线程安全地调用主线程代码
    /// </summary>
    public static void EnqueueOnMainThread(Action action)
    {
        lock (_lock)
        {
            _pending.Enqueue(action);
        }
    }
}

// 使用示例：后台下载完成后更新 UI
async void DownloadImage(string url)
{
    // 在后台线程下载
    byte[] imageData = await DownloadBytesAsync(url);
    
    // 回到主线程更新 UI
    MainThreadDispatcher.EnqueueOnMainThread(() =>
    {
        var texture = new Texture2D(1, 1);
        texture.LoadImage(imageData);
        _image.texture = texture;
    });
}
```

### 2.2 并发集合的正确使用

```csharp
using System.Collections.Concurrent;

// ❌ 多线程修改普通 List（线程不安全）
List<Message> _messages = new(); // 危险！

void OnMessageReceived(Message msg)
{
    // 如果从后台线程调用，可能与主线程的 Update 同时修改 _messages
    _messages.Add(msg); // 数据竞争！
}

// ✅ 使用 ConcurrentQueue（线程安全队列）
ConcurrentQueue<Message> _pendingMessages = new();

void OnMessageReceived(Message msg)
{
    _pendingMessages.Enqueue(msg); // 线程安全
}

void Update()
{
    // 在主线程中处理消息
    while (_pendingMessages.TryDequeue(out var msg))
    {
        ProcessMessage(msg); // 在主线程安全处理
    }
}

// ✅ 使用 ConcurrentDictionary（线程安全字典）
ConcurrentDictionary<int, PlayerData> _playerCache = new();

// 后台线程可以安全写入
_playerCache.AddOrUpdate(playerId, newData, (key, old) => newData);

// 主线程可以安全读取
if (_playerCache.TryGetValue(playerId, out var data))
{
    Debug.Log(data.Name);
}
```

### 2.3 volatile 和 Interlocked

```csharp
public class SharedCounter
{
    // volatile：确保多线程间的可见性（但不保证原子性）
    private volatile int _value = 0;
    
    // ❌ 不是原子操作
    public void Increment_Bad() => _value++; // Read-Modify-Write，非原子
    
    // ✅ Interlocked：原子操作
    public void Increment() => Interlocked.Increment(ref _value);
    public void Add(int amount) => Interlocked.Add(ref _value, amount);
    public int Read() => Interlocked.CompareExchange(ref _value, 0, 0);
}

// ReaderWriterLockSlim：读多写少的场景（允许多个并发读取）
public class ThreadSafeCache<T>
{
    private readonly Dictionary<int, T> _cache = new();
    private readonly ReaderWriterLockSlim _rwLock = new();
    
    public T Get(int key)
    {
        _rwLock.EnterReadLock();
        try
        {
            return _cache.TryGetValue(key, out var value) ? value : default;
        }
        finally
        {
            _rwLock.ExitReadLock();
        }
    }
    
    public void Set(int key, T value)
    {
        _rwLock.EnterWriteLock();
        try
        {
            _cache[key] = value;
        }
        finally
        {
            _rwLock.ExitWriteLock();
        }
    }
}
```

---

## 三、Job System 并行计算（补充 ECS 章节）

### 3.1 在 MonoBehaviour 中使用 Job

```csharp
using Unity.Jobs;
using Unity.Collections;
using Unity.Burst;
using Unity.Mathematics;

// 不使用 ECS，直接在 MonoBehaviour 中调度 Job
public class CrowdSimulation : MonoBehaviour
{
    private NativeArray<float3> _positions;
    private NativeArray<float3> _velocities;
    private JobHandle _currentJob;
    
    [SerializeField] private int _crowdSize = 1000;
    
    void Start()
    {
        _positions = new NativeArray<float3>(_crowdSize, Allocator.Persistent);
        _velocities = new NativeArray<float3>(_crowdSize, Allocator.Persistent);
        
        // 初始化...
    }
    
    void Update()
    {
        // 等待上一帧的 Job 完成（如果还没完成）
        _currentJob.Complete();
        
        // 从 NativeArray 读取结果，更新渲染...
        
        // 调度新的 Job（让它在本帧结束前/下帧开始前完成）
        var job = new UpdateCrowdJob
        {
            Positions = _positions,
            Velocities = _velocities,
            DeltaTime = Time.deltaTime,
            Target = PlayerPosition
        };
        
        _currentJob = job.Schedule(_crowdSize, 64); // 64个一批，并行
        
        // 注意：不要立即 Complete()，让 Job 与主线程并行执行
        // Unity 会在下帧开始前确保 Job 完成
        JobHandle.ScheduleBatchedJobs(); // 立即提交 Job 到工作线程
    }
    
    void LateUpdate()
    {
        // 最迟在 LateUpdate 拿到结果
        _currentJob.Complete();
        
        // 可以在这里用 _positions 更新 Transform
    }
    
    void OnDestroy()
    {
        _currentJob.Complete(); // 确保 Job 完成才能 Dispose
        _positions.Dispose();
        _velocities.Dispose();
    }
    
    private Vector3 PlayerPosition => Player.Instance?.transform.position ?? Vector3.zero;
}

[BurstCompile]
struct UpdateCrowdJob : IJobParallelFor
{
    public NativeArray<float3> Positions;
    [ReadOnly] public NativeArray<float3> Velocities;
    public float DeltaTime;
    public float3 Target;
    
    public void Execute(int index)
    {
        float3 pos = Positions[index];
        float3 vel = Velocities[index];
        
        // 向目标移动（简单群体行为）
        float3 toTarget = math.normalize(Target - pos);
        vel = math.lerp(vel, toTarget * 5f, DeltaTime * 2f);
        
        Positions[index] = pos + vel * DeltaTime;
    }
}
```

---

## 四、常见并发陷阱

### 4.1 死锁

```csharp
// ❌ 在异步方法中使用 .Result 或 .Wait()（可能死锁）
async UniTask<Data> FetchData() => /* ... */ default;

void SomeMethod()
{
    var data = FetchData().GetAwaiter().GetResult(); // 危险！在 Unity 主线程上可能死锁
}

// ✅ 全程使用 async/await
async UniTask SomeMethod()
{
    var data = await FetchData(); // 安全
}
```

### 4.2 竞态条件

```csharp
// ❌ 竞态条件：两个协程同时检查和修改同一状态
private bool _isLoading = false;

async UniTask LoadLevel(string name)
{
    if (_isLoading) return;  // 检查
    _isLoading = true;        // 修改（检查和修改之间可能被抢占）
    
    await SceneManager.LoadSceneAsync(name);
    _isLoading = false;
}

// ✅ 使用 SemaphoreSlim 保证互斥
private SemaphoreSlim _loadSemaphore = new SemaphoreSlim(1, 1);

async UniTask LoadLevel(string name)
{
    if (!await _loadSemaphore.WaitAsync(TimeSpan.Zero)) return; // 原子操作，已有加载则跳过
    
    try
    {
        await SceneManager.LoadSceneAsync(name);
    }
    finally
    {
        _loadSemaphore.Release();
    }
}
```

---

## 总结

Unity 多线程编程的核心原则：

| 场景 | 推荐方案 |
|------|---------|
| 异步操作（网络、文件、等待） | UniTask + async/await |
| 大量并行计算（无 Unity API） | Job System + Burst |
| 后台计算回到主线程更新 UI | UniTask.SwitchToMainThread() |
| 多线程共享数据 | ConcurrentQueue/Dictionary |
| 防止重复执行 | SemaphoreSlim |
| 帧率无关的等待 | UniTask.Delay + ignoreTimeScale |

**黄金法则**：Unity API 只能在主线程调用。其他工作可以在后台线程做，但最终必须切回主线程更新游戏对象。

> **下一篇**：[游戏本地化系统：从文本到多语言的完整解决方案]
