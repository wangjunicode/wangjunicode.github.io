---
title: 内存管理深度：从 GC 原理到零分配编程
published: 2026-03-21
description: "深度解析 Unity/C# 的垃圾回收机制，从 GC 代际原理到内存分配分析，讲解如何通过对象池、Span<T>、结构体优化、零分配模式消除 GC 压力，实现移动端流畅稳定的帧率。"
tags: [内存管理, GC优化, 零分配编程, Unity, 性能优化]
category: 性能优化
draft: false
---

## 为什么 GC 是游戏的敌人

```
GC（Garbage Collection）的工作原理：

1. 追踪堆上的所有对象
2. 标记仍然可达的对象
3. 清除不可达对象，整理内存

GC 的问题：
  - Stop-The-World：GC 工作时，游戏逻辑暂停
  - 单次 GC 耗时：轻则 1ms，重则 10~100ms
  - GC 触发时机不可预测（内存分配达到阈值时触发）

在游戏中：
  16.7ms 预算（60fps）→ 一次 GC 可能吃掉 30%~300% 预算
  结果：帧率波动，玩家感受到"卡顿"
```

---

## 一、理解 .NET 的分代 GC

### 1.1 分代 GC 的原理

```
.NET GC 将堆分为三代：

Gen 0（第0代）：新创建的小对象
  - 收集频繁（约每几百 KB 分配一次）
  - 速度快（约 0.5~2ms）
  - 大多数临时对象在这里被清除

Gen 1（第1代）：从 Gen 0 存活下来的对象
  - 收集频率较低
  - 通常是中等生命周期的对象

Gen 2（第2代）：长期存活的对象
  - 收集频率最低（完整 GC）
  - 但收集时最慢（5~50ms 甚至更长）
  - Full GC：清理所有代

LOH（Large Object Heap）：大对象（> 85KB）
  - 不参与分代，直接分配在这里
  - 不会被整理（碎片化问题）
  - 只在完整 GC 时被收集
```

### 1.2 识别 GC 分配

```csharp
// 如何识别会产生 GC 分配的代码

// 1. 装箱（Boxing）：值类型转换为 object
int value = 42;
object boxed = value;  // ← GC 分配！将 int 装箱到堆上

// 常见的隐式装箱
Debug.Log("Value: " + value);  // string.Concat 接受 object，int 被装箱

// ✅ 避免装箱
Debug.Log($"Value: {value}"); // 字符串插值，现代编译器可以优化
Debug.Log("Value: " + value.ToString()); // 显式转换，无装箱

// 2. 闭包捕获
var list = new List<int>();
Action closure = () => list.Add(1); // ← 创建了捕获 list 的对象，GC 分配

// 每次创建委托都会分配（如果有捕获）

// 3. LINQ 操作
var result = items.Where(x => x > 0).ToList(); // 多次迭代器分配

// 4. foreach 在某些集合上
foreach (var item in list) { }  // List<T>: 无分配
foreach (var item in dict) { }  // Dictionary: 分配枚举器对象（KeyValuePair 结构体枚举器除外）

// 5. 字符串拼接在循环中
string result = "";
for (int i = 0; i < 100; i++)
    result += i.ToString(); // 每次 += 都创建新字符串！

// ✅ 使用 StringBuilder
var sb = new System.Text.StringBuilder();
for (int i = 0; i < 100; i++)
    sb.Append(i);
string result = sb.ToString(); // 只有最后一次分配
```

### 1.3 用 Profiler 分析内存分配

```
Unity Profiler 内存分析步骤：

1. 打开 Profiler（Window → Analysis → Profiler）
2. 选择 "Memory" 模块
3. 运行游戏，找到帧率波动的帧
4. 查看 GC Alloc 列：数字 > 0 的都有堆分配
5. 按 GC Alloc 排序，找出分配最多的方法

关键指标：
  GC Alloc / frame：每帧 GC 分配量
  目标：< 1KB/frame（理想：0 B/frame）
  
告警线：
  > 10KB/frame：会频繁触发 GC
  > 100KB/frame：几乎每帧 GC
```

---

## 二、零分配编程技巧

### 2.1 对象池（已在性能章节讲过，这里补充细节）

```csharp
// 字符串 Builder 池（避免 StringBuilder 反复创建）
public static class StringBuilderPool
{
    private static readonly Stack<StringBuilder> _pool = new(8);
    
    public static StringBuilder Get()
    {
        return _pool.Count > 0 ? _pool.Pop().Clear() : new StringBuilder(256);
    }
    
    public static void Return(StringBuilder sb) => _pool.Push(sb);
    
    // 便捷方法：自动归还
    public static string Build(Action<StringBuilder> buildAction)
    {
        var sb = Get();
        buildAction(sb);
        var result = sb.ToString();
        Return(sb);
        return result;
    }
}

// 使用
var msg = StringBuilderPool.Build(sb =>
{
    sb.Append(playerName);
    sb.Append(" 造成了 ");
    sb.Append(damage);
    sb.Append(" 点伤害");
});
```

### 2.2 Span<T> 和 Memory<T>

```csharp
// Span<T>：不分配新内存的"视图"
// 可以指向：栈上的数组、堆上的数组的切片、非托管内存

// 传统方式（有分配）
byte[] ProcessData_Old(byte[] data, int offset, int length)
{
    byte[] slice = new byte[length];          // ← GC 分配
    Array.Copy(data, offset, slice, 0, length);
    // 处理 slice...
    return slice;
}

// Span 方式（零分配）
void ProcessData_New(ReadOnlySpan<byte> data)
{
    // 直接操作 data，无需复制
    for (int i = 0; i < data.Length; i++)
    {
        // 处理 data[i]
    }
}

// 调用
byte[] buffer = new byte[1024];
ReadOnlySpan<byte> slice = buffer.AsSpan(offset: 100, length: 50); // 零分配
ProcessData_New(slice);

// 字符串解析（零分配）
ReadOnlySpan<char> ParseName(ReadOnlySpan<char> fullString, char delimiter)
{
    int idx = fullString.IndexOf(delimiter);
    return idx >= 0 ? fullString[..idx] : fullString;
}

// 栈上分配（stackalloc）- 用于小数组
Span<int> stackBuffer = stackalloc int[16]; // 栈上分配，方法结束自动释放
for (int i = 0; i < 16; i++)
    stackBuffer[i] = i * 2;
```

### 2.3 结构体优化

```csharp
// 使用结构体而非类，减少 GC 压力
// 结构体存在栈上或内联在包含它的类/结构体中，不需要 GC 管理

// ❌ 用类存储小数据（每个实例都有 GC 开销）
public class DamageInfo
{
    public int Amount;
    public DamageType Type;
    public bool IsCritical;
}

// ✅ 用结构体（值类型，栈上分配）
public struct DamageInfo
{
    public int Amount;
    public DamageType Type;
    public bool IsCritical;
}

// 注意：结构体传参是值拷贝
// 如果结构体较大（> 16字节），考虑用 ref 传递
void ApplyDamage(ref DamageInfo info, BattleUnit target) // ref 避免拷贝
{
    target.HP -= info.Amount;
}

// readonly struct：不可变结构体，编译器可以做额外优化
public readonly struct Vector2Int
{
    public readonly int X;
    public readonly int Y;
    
    public Vector2Int(int x, int y) { X = x; Y = y; }
    
    // 所有方法都是 readonly，不允许修改字段
    public float Magnitude() => MathF.Sqrt(X * X + Y * Y);
}
```

### 2.4 ArrayPool 和 MemoryPool

```csharp
using System.Buffers;

// ArrayPool：借用/归还数组，避免频繁 new
public void ProcessBuffer(int size)
{
    // 从池中借一个至少 size 大的数组
    byte[] buffer = ArrayPool<byte>.Shared.Rent(size);
    
    try
    {
        // 使用 buffer[0..size]（注意：租借的数组可能比 size 大）
        Span<byte> span = buffer.AsSpan(0, size);
        
        // 处理数据...
    }
    finally
    {
        // 归还（必须归还！否则池会耗尽）
        ArrayPool<byte>.Shared.Return(buffer, clearArray: false);
    }
}

// 在 Unity 中使用 NativeArray（ECS/Jobs 场景）
using Unity.Collections;

void ProcessWithNative(int count)
{
    // Allocator.Temp：方法内使用，方法结束自动释放（不需要 Dispose）
    var tempArray = new NativeArray<float>(count, Allocator.Temp);
    
    // Allocator.TempJob：在 Job 中使用，4帧内必须 Dispose
    var jobArray = new NativeArray<float>(count, Allocator.TempJob);
    jobArray.Dispose(); // 必须显式释放
    
    // Allocator.Persistent：长期存在，需要在 OnDestroy 中 Dispose
    var persistentArray = new NativeArray<float>(count, Allocator.Persistent);
    // ... 在 OnDestroy 中 persistentArray.Dispose();
}
```

---

## 三、零 GC 的实战策略

### 3.1 避免 LINQ 的运行时分配

```csharp
// ❌ LINQ 在热路径中（每帧）
void Update()
{
    var nearbyEnemies = _enemies
        .Where(e => Vector3.Distance(e.Position, _player.Position) < 10f)
        .OrderBy(e => e.HP)
        .ToList(); // 分配新 List
    
    foreach (var enemy in nearbyEnemies)
        AttackEnemy(enemy);
}

// ✅ 手动实现，零分配（使用预分配缓冲区）
private readonly List<Enemy> _nearbyEnemiesCache = new List<Enemy>(32);

void Update()
{
    _nearbyEnemiesCache.Clear(); // 清空但不释放内存
    
    float playerX = _player.Position.x;
    float playerZ = _player.Position.z;
    float rangeSquared = 10f * 10f;
    
    foreach (var enemy in _enemies)
    {
        float dx = enemy.Position.x - playerX;
        float dz = enemy.Position.z - playerZ;
        if (dx * dx + dz * dz < rangeSquared)
            _nearbyEnemiesCache.Add(enemy);
    }
    
    // 手动排序（避免 OrderBy 分配）
    _nearbyEnemiesCache.Sort(CompareByHP); // 使用缓存的 Comparison
    
    foreach (var enemy in _nearbyEnemiesCache)
        AttackEnemy(enemy);
}

private static int CompareByHP(Enemy a, Enemy b) => a.HP.CompareTo(b.HP);
```

### 3.2 避免闭包分配

```csharp
// ❌ 在 Update 中创建捕获外部变量的委托
void Update()
{
    float threshold = GetCurrentThreshold();
    
    _enemies.RemoveAll(e => e.HP < threshold); // 创建捕获 threshold 的闭包
}

// ✅ 方案1：避免 RemoveAll，手动删除
void Update()
{
    float threshold = GetCurrentThreshold();
    
    for (int i = _enemies.Count - 1; i >= 0; i--)
    {
        if (_enemies[i].HP < threshold)
            _enemies.RemoveAt(i);
    }
}

// ✅ 方案2：缓存委托（适合条件固定的情况）
// 如果 threshold 不变，可以缓存委托
private Predicate<Enemy> _isDeadPredicate;
private float _cachedThreshold = -1;

void Update()
{
    float threshold = GetCurrentThreshold();
    
    if (!Mathf.Approximately(threshold, _cachedThreshold))
    {
        _cachedThreshold = threshold;
        _isDeadPredicate = e => e.HP < _cachedThreshold; // 只在阈值变化时重建
    }
    
    _enemies.RemoveAll(_isDeadPredicate);
}
```

---

## 四、内存泄露的检测与修复

### 4.1 Unity 中常见的内存泄露

```csharp
// 泄露1：事件未取消订阅
public class EnemyUI : MonoBehaviour
{
    void Start()
    {
        // ❌ 订阅了，但 OnDestroy 没有取消
        GameEvents.OnEnemyKilled += UpdateKillCount;
    }
    
    void OnDestroy()
    {
        // ✅ 必须取消订阅
        GameEvents.OnEnemyKilled -= UpdateKillCount;
    }
    
    void UpdateKillCount() { /* ... */ }
}

// 泄露2：Addressables 资源未释放
public class AssetLoader : MonoBehaviour
{
    private AsyncOperationHandle<GameObject> _handle;
    
    async void LoadAsset()
    {
        _handle = Addressables.LoadAssetAsync<GameObject>("EnemyPrefab");
        var prefab = await _handle.Task;
        // 使用 prefab...
    }
    
    void OnDestroy()
    {
        // ✅ 必须释放 Addressables 资源
        if (_handle.IsValid())
            Addressables.Release(_handle);
    }
}

// 泄露3：RenderTexture 未释放
RenderTexture rt = new RenderTexture(256, 256, 0);
// 使用 rt...

// ✅ 使用完后释放
rt.Release();
Destroy(rt);
```

### 4.2 内存泄露检测工具

```
Unity Memory Profiler（专门的内存分析工具）：

1. Window → Analysis → Memory Profiler
2. 运行游戏，在怀疑有泄露的时候截取快照
3. 一段时间后再截取快照
4. 比较两次快照：新增了哪些对象？

关注：
  - Texture2D：是否有不断增加的纹理？
  - AudioClip：是否有未释放的音频数据？
  - Mesh：是否有动态创建但未销毁的 Mesh？
  - 托管对象：是否有增长中的大量相同类型对象？
```

---

## 总结

内存管理的核心原则：

```
减少分配（减少 GC 触发）：
  ✅ 使用结构体代替小类
  ✅ 使用对象池复用对象
  ✅ 使用 ArrayPool/NativeArray
  ✅ 使用 Span<T> 代替切片复制
  ✅ 避免热路径中的 LINQ 和闭包

防止泄露（防止内存增长）：
  ✅ 事件订阅必须有取消订阅
  ✅ Addressables 资源使用后释放
  ✅ RenderTexture/NativeArray 显式 Dispose

监控工具：
  - Unity Profiler（CPU 内存分配分析）
  - Memory Profiler（堆对象快照对比）
```

**在实际项目中的应用顺序**：
1. 先用 Profiler 找到最大的 GC 分配点
2. 针对性优化（通常 80% 的 GC 来自 20% 的代码）
3. 保持 per-frame GC alloc < 1KB 的目标

> 不要过早优化，但要知道在哪里优化。

---

*本文是「游戏客户端开发进阶路线」系列的性能优化篇。*
