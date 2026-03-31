---
title: Unity 内存管理深度优化：GC Zero Allocation实战
published: 2026-03-31
description: 深度解析Unity运行时GC零分配的工程实践，涵盖GC触发原理（Gen0/1/2分代回收）、常见GC Alloc来源（字符串/装箱/Lambda/LINQ/协程）、使用Struct避免装箱、对象池的正确实现、SpanT与MemoryT零拷贝技术、NativeArray无GC压力的批量计算，以及使用Memory Profiler追踪内存快照的完整工作流。
tags: [Unity, 内存优化, GC, 零分配, 性能优化]
category: 性能优化
draft: false
---

## 一、GC 分配来源排查

```csharp
using System;
using System.Collections.Generic;
using Unity.Collections;
using UnityEngine;

/// <summary>
/// 常见 GC Alloc 来源与修复
/// </summary>
public class GCAllocPatterns
{
    // ============ 问题1：字符串拼接 ============
    
    // ❌ 每次都分配新字符串（GC）
    void BadStringConcat(int score, int combo)
    {
        string text = "Score: " + score + " × " + combo; // 分配3个string
    }

    // ✅ 使用 StringBuilder 复用
    private System.Text.StringBuilder sb = new System.Text.StringBuilder(64);
    void GoodStringConcat(int score, int combo)
    {
        sb.Clear();
        sb.Append("Score: ").Append(score).Append(" × ").Append(combo);
        string text = sb.ToString(); // 只分配最终string
    }

    // ✅ 更好：直接设置 UI Text，避免 ToString()
    void BestStringConcat(UnityEngine.UI.Text label, int score, int combo)
    {
        sb.Clear();
        sb.Append("Score: ").Append(score).Append(" × ").Append(combo);
        label.text = sb.ToString();
    }

    // ============ 问题2：foreach 装箱 ============
    
    Dictionary<int, GameObject> entityMap = new Dictionary<int, GameObject>();
    
    // ❌ Dictionary.KeyCollection 的 GetEnumerator 可能分配（结构体，但旧版本有问题）
    void BadForeach()
    {
        foreach (var kv in entityMap) // 某些情况下装箱
        {
            // ...
        }
    }

    // ✅ 将 keys 缓存到 List，避免每帧 GetEnumerator
    private List<int> cachedKeys = new List<int>(64);
    void GoodForeach()
    {
        cachedKeys.Clear();
        cachedKeys.AddRange(entityMap.Keys);
        for (int i = 0; i < cachedKeys.Count; i++)
        {
            // 处理 entityMap[cachedKeys[i]]
        }
    }

    // ============ 问题3：Lambda/Delegate 捕获 ============

    // ❌ 每次调用创建新闭包对象
    void BadLambda()
    {
        int threshold = 100;
        var enemies = new List<Enemy>();
        var result = enemies.FindAll(e => e.HP < threshold); // 每次 new Predicate<Enemy>
    }

    // ✅ 缓存 Predicate，或使用 for 循环
    private List<Enemy> resultBuffer = new List<Enemy>();
    void GoodLambda(List<Enemy> enemies, int threshold)
    {
        resultBuffer.Clear();
        for (int i = 0; i < enemies.Count; i++)
        {
            if (enemies[i].HP < threshold)
                resultBuffer.Add(enemies[i]);
        }
    }

    // ============ 问题4：协程 ============

    // ❌ 每次 yield return 等待时间都分配 WaitForSeconds
    System.Collections.IEnumerator BadCoroutine()
    {
        while (true)
        {
            yield return new WaitForSeconds(1f); // 每次都 new！
        }
    }

    // ✅ 缓存等待对象
    private WaitForSeconds cachedWait1s = new WaitForSeconds(1f);
    System.Collections.IEnumerator GoodCoroutine()
    {
        while (true)
        {
            yield return cachedWait1s; // 复用，零分配
        }
    }

    // ============ 问题5：GetComponent ============

    // ❌ 每帧查找
    void BadGetComponent()
    {
        GetComponent<Rigidbody>(); // 慢 + 有时会分配
    }

    // ✅ Awake 时缓存
    Rigidbody rb;
    void Awake() { rb = GetComponent<Rigidbody>(); }
}
```

---

## 二、NativeArray 零GC批量计算

```csharp
using Unity.Collections;
using Unity.Jobs;
using Unity.Burst;

/// <summary>
/// 使用 NativeArray 批量处理伤害（无GC，多线程安全）
/// </summary>
public class NativeArrayExample : MonoBehaviour
{
    private NativeArray<float> hpArray;
    private NativeArray<float> damageArray;
    private NativeArray<bool> deadArray;

    void Start()
    {
        int entityCount = 1000;
        
        // NativeArray 分配在 Native 内存中，不受 GC 管理
        hpArray     = new NativeArray<float>(entityCount, Allocator.Persistent);
        damageArray = new NativeArray<float>(entityCount, Allocator.Persistent);
        deadArray   = new NativeArray<bool>(entityCount, Allocator.Persistent);
        
        // 初始化
        for (int i = 0; i < entityCount; i++)
        {
            hpArray[i]     = 100f;
            damageArray[i] = 0f;
        }
    }

    void OnDestroy()
    {
        // 必须手动释放！
        if (hpArray.IsCreated)  hpArray.Dispose();
        if (damageArray.IsCreated) damageArray.Dispose();
        if (deadArray.IsCreated) deadArray.Dispose();
    }

    void Update()
    {
        // 提交 Job（多线程批量处理HP扣减）
        var job = new ApplyDamageJob
        {
            HP     = hpArray,
            Damage = damageArray,
            Dead   = deadArray
        };
        
        JobHandle handle = job.Schedule(hpArray.Length, 64); // 64 = batch size
        handle.Complete();
        
        // 处理死亡
        for (int i = 0; i < deadArray.Length; i++)
        {
            if (deadArray[i])
            {
                // 处理死亡逻辑
                deadArray[i] = false;
            }
        }
    }
}

[BurstCompile]
public struct ApplyDamageJob : IJobParallelFor
{
    public NativeArray<float> HP;
    [ReadOnly] public NativeArray<float> Damage;
    [WriteOnly] public NativeArray<bool> Dead;
    
    public void Execute(int index)
    {
        HP[index] -= Damage[index];
        Dead[index] = HP[index] <= 0;
        Damage[index] = 0; // 清空伤害
    }
}
```

---

## 三、对象池的正确实现

```csharp
/// <summary>
/// 泛型对象池（零GC）
/// </summary>
public class ObjectPool<T> where T : class, new()
{
    private Stack<T> pool = new Stack<T>();
    private Func<T> createFunc;
    private Action<T> resetFunc;
    private int maxSize;

    public ObjectPool(Func<T> createFunc = null, Action<T> resetFunc = null, 
        int initialSize = 10, int maxSize = 100)
    {
        this.createFunc = createFunc ?? (() => new T());
        this.resetFunc = resetFunc;
        this.maxSize = maxSize;
        
        // 预热
        for (int i = 0; i < initialSize; i++)
            pool.Push(this.createFunc());
    }

    public T Get()
    {
        return pool.Count > 0 ? pool.Pop() : createFunc();
    }

    public void Return(T obj)
    {
        if (pool.Count >= maxSize) return; // 超出上限则丢弃
        resetFunc?.Invoke(obj);
        pool.Push(obj);
    }

    public int Available => pool.Count;
}

// 使用示例
public class DamageNumberPool
{
    private static ObjectPool<System.Text.StringBuilder> sbPool 
        = new ObjectPool<System.Text.StringBuilder>(
            () => new System.Text.StringBuilder(32),
            sb => sb.Clear(),
            initialSize: 20);
    
    public static System.Text.StringBuilder GetSB() => sbPool.Get();
    public static void ReturnSB(System.Text.StringBuilder sb) => sbPool.Return(sb);
}
```

---

## 四、Memory Profiler 工作流

```
GC 零分配调试工作流：

1. 打开 Window → Analysis → Memory Profiler
2. 运行游戏，进入目标场景
3. 点击 "Capture Memory Snapshot"（拍快照）
4. 在 Inspector 中查找：
   - Managed Heap（托管堆）：过大说明有分配泄漏
   - GC.Alloc 高频对象：找到是什么类型在反复分配
5. 使用 ProfilerMarker + 深度 Profile 定位到具体代码行
6. 验证修复：修复后对比前后快照的 GC Alloc 减少量
```

**GC 分配速查表：**

| 操作 | 是否分配 | 修复方案 |
|------|----------|----------|
| `new Object()` | ✓ | 对象池 |
| `"a" + "b"` | ✓ | StringBuilder |
| `List.ToArray()` | ✓ | 复用数组/Span |
| `Action<int> = () => {}` | ✓ | 缓存委托 |
| `new WaitForSeconds(1)` | ✓ | 缓存等待对象 |
| `Dictionary<K,V>` foreach | 可能 | 用 for+Keys列表 |
| `NativeArray<T>` 操作 | ✗ | 已是零GC |
| `stackalloc float[10]` | ✗ | 栈分配，临时使用 |
