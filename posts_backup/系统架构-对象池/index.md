---
title: 游戏对象池系统：从入门到生产级实现
published: 2021-08-04
description: "深入讲解对象池设计与实现：从为什么需要对象池（GC原理与性能数据）出发，实现支持泛型、生命周期回调、最大容量限制的C#对象池，再到Unity GameObject专用对象池，涵盖预热、异步加载、定时清理等生产级特性，并总结常见使用误区。"
tags: [Unity, C#, 架构设计, 性能优化]
category: 架构设计
draft: false
---

做游戏这几年，对象池是我接触得最早、用得最多的架构模式之一。每次优化性能，第一步几乎都是把高频创建销毁的对象池化。这篇文章把我的对象池实践经验系统整理一遍。

---

## 为什么需要对象池

### GC 是怎么让游戏卡顿的

Unity 使用的是 Mono/.NET 的垃圾回收机制（GC）。当你调用 `new` 或 `Instantiate` 时，内存从托管堆分配；当对象不再被引用时，GC 会在"某个时机"回收这块内存。

问题在于 GC 回收是**非实时的**，它会在内存压力达到阈值时触发，而这个过程是**Stop-the-World**——游戏主线程会暂停等待 GC 完成。如果你的帧目标是 60FPS（每帧 16.6ms），一次 GC 耗时 5ms，这帧就直接超时了，玩家会感受到明显的卡顿。

### 性能数据对比

我在项目里做过测试（Unity 2021，Android，1000次操作）：

| 操作方式 | 耗时（ms）| 内存分配 |
|---------|----------|---------|
| Instantiate + Destroy | ~2.3ms | 每次分配 |
| 对象池 Get/Release | ~0.02ms | 几乎为零 |

差距超过 100 倍。对于子弹、特效这类**每秒可能触发几十次**的对象，不用对象池几乎必然出现 GC 卡顿。

### 什么时候需要对象池

- 对象频繁创建销毁（每秒超过 10 次就要考虑）
- 对象创建成本高（复杂的 `Awake`/`Start` 逻辑）
- 对象生命周期短（子弹、粒子、飘字）

---

## 基础实现：泛型对象池

先实现一个通用的 C# 泛型对象池，不依赖 Unity，可以用于任何 C# 项目。

```csharp
using System;
using System.Collections.Generic;

/// <summary>
/// 泛型对象池，线程不安全（游戏主线程使用）
/// </summary>
public class ObjectPool<T> where T : class
{
    private readonly Stack<T> _pool;
    private readonly Func<T> _createFunc;
    private readonly Action<T> _onGet;
    private readonly Action<T> _onRelease;
    private readonly Action<T> _onDestroy;
    private readonly int _maxSize;

    private int _totalCreated;

    /// <summary>
    /// 当前池中空闲对象数量
    /// </summary>
    public int CountInactive => _pool.Count;

    /// <summary>
    /// 已创建的对象总数（包含正在使用中的）
    /// </summary>
    public int CountAll => _totalCreated;

    /// <summary>
    /// 正在使用中的对象数量
    /// </summary>
    public int CountActive => _totalCreated - _pool.Count;

    /// <param name="createFunc">创建新对象的工厂方法</param>
    /// <param name="onGet">从池中取出时的回调</param>
    /// <param name="onRelease">归还到池中时的回调</param>
    /// <param name="onDestroy">池满时销毁多余对象的回调</param>
    /// <param name="defaultCapacity">初始预分配容量</param>
    /// <param name="maxSize">池的最大容量，超出则直接销毁归还的对象</param>
    public ObjectPool(
        Func<T> createFunc,
        Action<T> onGet = null,
        Action<T> onRelease = null,
        Action<T> onDestroy = null,
        int defaultCapacity = 16,
        int maxSize = 100)
    {
        _createFunc = createFunc ?? throw new ArgumentNullException(nameof(createFunc));
        _onGet = onGet;
        _onRelease = onRelease;
        _onDestroy = onDestroy;
        _maxSize = maxSize;
        _pool = new Stack<T>(defaultCapacity);
    }

    /// <summary>
    /// 从池中取出一个对象（池空时自动创建）
    /// </summary>
    public T Get()
    {
        T obj;
        if (_pool.Count > 0)
        {
            obj = _pool.Pop();
        }
        else
        {
            obj = _createFunc();
            _totalCreated++;
        }
        _onGet?.Invoke(obj);
        return obj;
    }

    /// <summary>
    /// 将对象归还到池中
    /// </summary>
    public void Release(T obj)
    {
        if (obj == null) return;

        _onRelease?.Invoke(obj);

        if (_pool.Count < _maxSize)
        {
            _pool.Push(obj);
        }
        else
        {
            // 超出最大容量，直接销毁
            _onDestroy?.Invoke(obj);
            _totalCreated--;
        }
    }

    /// <summary>
    /// 预热：提前创建指定数量的对象
    /// </summary>
    public void Prewarm(int count)
    {
        for (int i = 0; i < count; i++)
        {
            var obj = _createFunc();
            _totalCreated++;
            _onRelease?.Invoke(obj); // 触发"归还"回调，设置初始隐藏状态等
            _pool.Push(obj);
        }
    }

    /// <summary>
    /// 清空池中所有对象
    /// </summary>
    public void Clear()
    {
        while (_pool.Count > 0)
        {
            var obj = _pool.Pop();
            _onDestroy?.Invoke(obj);
        }
        _totalCreated = 0;
    }
}
```

### 使用示例

```csharp
// 以子弹为例
public class BulletData
{
    public float Speed;
    public int Damage;
    public Vector3 Direction;
    public bool IsActive;
}

// 创建对象池
var bulletPool = new ObjectPool<BulletData>(
    createFunc: () => new BulletData(),
    onGet: bullet => { bullet.IsActive = true; },
    onRelease: bullet =>
    {
        // ⚠️ 归还时必须重置状态！这是最常见的使用误区
        bullet.IsActive = false;
        bullet.Speed = 0;
        bullet.Damage = 0;
    },
    onDestroy: bullet => { /* 纯数据对象，不需要特殊销毁 */ },
    defaultCapacity: 50,
    maxSize: 200
);

// 取出
var bullet = bulletPool.Get();
bullet.Speed = 20f;
bullet.Damage = 10;
bullet.Direction = Vector3.forward;

// 归还
bulletPool.Release(bullet);
```

---

## 进阶实现：Unity GameObject 对象池

游戏里更常见的是需要对 `GameObject` 进行池化。这里封装一个生产级的 Unity 对象池：

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Unity GameObject 对象池
/// 支持：同步/异步加载、预热、最大容量、定时清理
/// </summary>
public class GameObjectPool : MonoBehaviour
{
    [Header("对象池配置")]
    [SerializeField] private GameObject _prefab;
    [SerializeField] private int _defaultCapacity = 10;
    [SerializeField] private int _maxSize = 50;
    [SerializeField] private bool _prewarmOnStart = true;

    [Header("自动清理配置")]
    [SerializeField] private bool _autoClean = true;
    [SerializeField] private float _cleanInterval = 60f; // 每60秒清理一次
    [SerializeField] private int _keepMinCount = 5;     // 保留最少5个

    private readonly Stack<GameObject> _inactiveObjects = new();
    private int _totalCount;
    private float _lastCleanTime;

    // 生命周期回调
    public event Action<GameObject> OnGetCallback;
    public event Action<GameObject> OnReleaseCallback;

    public int CountInactive => _inactiveObjects.Count;
    public int CountAll => _totalCount;
    public int CountActive => _totalCount - _inactiveObjects.Count;

    private void Start()
    {
        if (_prewarmOnStart && _prefab != null)
        {
            Prewarm(_defaultCapacity);
        }
    }

    private void Update()
    {
        // 定时清理：避免内存长期堆积
        if (_autoClean && Time.time - _lastCleanTime > _cleanInterval)
        {
            TrimExcess();
        }
    }

    /// <summary>
    /// 同步取出对象（如果池空则立即创建）
    /// </summary>
    public GameObject Get(Vector3 position = default, Quaternion rotation = default)
    {
        GameObject obj;

        if (_inactiveObjects.Count > 0)
        {
            obj = _inactiveObjects.Pop();
        }
        else
        {
            obj = CreateNew();
        }

        obj.transform.SetPositionAndRotation(position, rotation);
        obj.SetActive(true);

        OnGetCallback?.Invoke(obj);
        return obj;
    }

    /// <summary>
    /// 归还对象到池中
    /// </summary>
    public void Release(GameObject obj)
    {
        if (obj == null) return;

        // 确保对象属于这个池
        obj.transform.SetParent(transform);
        obj.SetActive(false);

        OnReleaseCallback?.Invoke(obj);

        if (_inactiveObjects.Count < _maxSize)
        {
            _inactiveObjects.Push(obj);
        }
        else
        {
            // 超出最大容量，销毁
            Destroy(obj);
            _totalCount--;
        }
    }

    /// <summary>
    /// 延迟归还（常用于有销毁动画的对象）
    /// </summary>
    public void ReleaseDelay(GameObject obj, float delay)
    {
        StartCoroutine(ReleaseDelayCoroutine(obj, delay));
    }

    private IEnumerator ReleaseDelayCoroutine(GameObject obj, float delay)
    {
        yield return new WaitForSeconds(delay);
        Release(obj);
    }

    /// <summary>
    /// 预热：提前创建对象放入池中
    /// </summary>
    public void Prewarm(int count)
    {
        int createCount = Mathf.Min(count, _maxSize - _inactiveObjects.Count);
        for (int i = 0; i < createCount; i++)
        {
            var obj = CreateNew();
            obj.SetActive(false);
            _inactiveObjects.Push(obj);
        }
    }

    /// <summary>
    /// 清理多余对象（保留 keepMinCount 个）
    /// </summary>
    public void TrimExcess()
    {
        _lastCleanTime = Time.time;

        while (_inactiveObjects.Count > _keepMinCount)
        {
            var obj = _inactiveObjects.Pop();
            Destroy(obj);
            _totalCount--;
        }
    }

    /// <summary>
    /// 清空所有空闲对象
    /// </summary>
    public void Clear()
    {
        while (_inactiveObjects.Count > 0)
        {
            var obj = _inactiveObjects.Pop();
            Destroy(obj);
        }
        _totalCount = 0;
    }

    private GameObject CreateNew()
    {
        var obj = Instantiate(_prefab, transform);
        obj.name = _prefab.name; // 去掉 "(Clone)" 后缀，方便调试
        _totalCount++;
        return obj;
    }
}
```

### 异步预热（针对 Addressables 资源）

```csharp
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;

public class AsyncGameObjectPool : MonoBehaviour
{
    [SerializeField] private AssetReference _prefabRef;
    [SerializeField] private int _prewarmCount = 10;

    private GameObject _prefab;
    private readonly Stack<GameObject> _pool = new();
    private bool _isReady;

    private async void Start()
    {
        // 异步加载 Prefab
        var handle = Addressables.LoadAssetAsync<GameObject>(_prefabRef);
        _prefab = await handle.Task;
        _isReady = true;

        // 预热
        for (int i = 0; i < _prewarmCount; i++)
        {
            var obj = Instantiate(_prefab, transform);
            obj.SetActive(false);
            _pool.Push(obj);
        }
    }

    public GameObject Get()
    {
        if (!_isReady)
        {
            Debug.LogWarning("Pool is not ready yet!");
            return null;
        }

        var obj = _pool.Count > 0 ? _pool.Pop() : Instantiate(_prefab, transform);
        obj.SetActive(true);
        return obj;
    }

    public void Release(GameObject obj)
    {
        obj.SetActive(false);
        obj.transform.SetParent(transform);
        _pool.Push(obj);
    }
}
```

---

## 对象池管理器：统一管理多种类型

实际项目里往往有子弹、特效、飘字等多种需要池化的对象，用一个管理器统一管理会更方便：

```csharp
using System.Collections.Generic;
using UnityEngine;

public class PoolManager : MonoBehaviour
{
    public static PoolManager Instance { get; private set; }

    [System.Serializable]
    public class PoolConfig
    {
        public string Key;
        public GameObject Prefab;
        public int DefaultCapacity = 10;
        public int MaxSize = 50;
    }

    [SerializeField] private List<PoolConfig> _poolConfigs = new();

    private readonly Dictionary<string, GameObjectPool> _pools = new();

    private void Awake()
    {
        Instance = this;
        foreach (var config in _poolConfigs)
        {
            CreatePool(config);
        }
    }

    private void CreatePool(PoolConfig config)
    {
        var poolObj = new GameObject($"Pool_{config.Key}");
        poolObj.transform.SetParent(transform);
        var pool = poolObj.AddComponent<GameObjectPool>();
        // 通过反射或公开方法设置配置...
        _pools[config.Key] = pool;
    }

    public GameObject Get(string key, Vector3 position = default, Quaternion rotation = default)
    {
        if (_pools.TryGetValue(key, out var pool))
        {
            return pool.Get(position, rotation);
        }
        Debug.LogError($"Pool '{key}' not found!");
        return null;
    }

    public void Release(string key, GameObject obj)
    {
        if (_pools.TryGetValue(key, out var pool))
        {
            pool.Release(obj);
        }
    }
}

// 使用
PoolManager.Instance.Get("Bullet", firePoint.position, Quaternion.LookRotation(dir));
PoolManager.Instance.Release("Bullet", bullet);
```

---

## 让池化对象自我管理

让 GameObject 知道自己属于哪个池，到时间了自动归还：

```csharp
/// <summary>
/// 挂载在池化对象上，实现自动归还
/// </summary>
public class PooledObject : MonoBehaviour
{
    private GameObjectPool _ownerPool;
    private Coroutine _autoReleaseCoroutine;

    public void Init(GameObjectPool pool)
    {
        _ownerPool = pool;
    }

    /// <summary>
    /// 激活并设置自动归还时间
    /// </summary>
    public void ActivateWithLifetime(float lifetime)
    {
        gameObject.SetActive(true);
        if (_autoReleaseCoroutine != null)
            StopCoroutine(_autoReleaseCoroutine);
        _autoReleaseCoroutine = StartCoroutine(AutoRelease(lifetime));
    }

    public void ReturnToPool()
    {
        if (_autoReleaseCoroutine != null)
        {
            StopCoroutine(_autoReleaseCoroutine);
            _autoReleaseCoroutine = null;
        }
        _ownerPool?.Release(gameObject);
    }

    private IEnumerator AutoRelease(float delay)
    {
        yield return new WaitForSeconds(delay);
        ReturnToPool();
    }
}
```

---

## 常见使用误区

### 误区一：不同 Prefab 混用同一个池

```csharp
// ❌ 错误！把不同的子弹放进同一个池
var pool = new GameObjectPool();
pool.Release(bulletA_Instance); // BulletA 的实例
var obj = pool.Get();           // 可能取出 BulletA，但你以为是 BulletB
```

**每种 Prefab 必须有独立的池。**

### 误区二：归还时不重置状态

```csharp
// ❌ 错误！归还后没有重置，下次取出时携带上一次的脏数据
public void Release(GameObject bullet)
{
    bullet.SetActive(false);
    pool.Push(bullet);
}

// ✅ 正确：归还时彻底重置
public void Release(GameObject bullet)
{
    var bulletComp = bullet.GetComponent<Bullet>();
    bulletComp.Reset(); // 重置速度、伤害、命中标记等所有状态
    bullet.SetActive(false);
    pool.Push(bullet);
}
```

这是我见过最常见的 bug 来源。子弹上次打了一个怪，归还时没有清除"已命中"标记，下次取出来直接失效。

### 误区三：对象池无上限

对象池本质上是"用内存换时间"，如果不设上限，某些极端情况（比如技能 bug 触发了大量对象）会让内存暴涨。**务必设置 `maxSize`。**

### 误区四：频率很低的对象也用池

对象池有维护成本。如果一个对象每30秒才创建一次，直接 `Instantiate` 更简单，不需要池化。

---

## 性能调优建议

1. **预热时机**：在加载界面预热，避免游戏开始后因为第一次创建对象导致卡顿
2. **池大小调优**：通过 Profiler 观察 `CountActive` 的峰值，`maxSize` 设为峰值的 1.5 倍左右
3. **定时清理**：战斗结束后（进入大厅、切换地图）是清理池的好时机，不要等 GC
4. **用 Stack 而不是 List**：Stack 的 Push/Pop 是 O(1)，而 `List` 的 `foreach` 查找是 O(n)（原来代码的问题）
