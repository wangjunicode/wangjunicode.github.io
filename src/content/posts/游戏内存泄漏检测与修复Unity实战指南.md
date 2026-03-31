---
title: 游戏内存泄漏检测与修复：Unity实战指南
published: 2026-03-31
description: 深入解析Unity游戏内存泄漏的常见原因、检测方法和修复方案，涵盖UnityEngine Object未释放、事件订阅泄漏、协程泄漏、Texture/AudioClip未销毁、静态引用、Addressables未释放等典型场景，以及Memory Profiler和内存快照对比分析。
tags: [Unity, 内存泄漏, 性能优化, Memory Profiler, 调试]
category: 性能优化
draft: false
---

## 一、内存泄漏的危害

手游内存泄漏会导致：

1. **OOM崩溃**：Android 设备内存耗尽，系统杀死进程
2. **运行缓慢**：内存压力触发频繁 GC，帧率下降
3. **发热严重**：GC 频繁运行消耗 CPU 时间
4. **用户流失**：崩溃率上升直接影响留存

---

## 二、常见泄漏类型

### 2.1 事件订阅泄漏（最常见）

```csharp
// ❌ 错误：订阅后不取消，对象无法被GC回收
public class EnemyUI : MonoBehaviour
{
    void Start()
    {
        // 每次初始化都添加订阅，但从不移除
        GameManager.OnPlayerDied += HandlePlayerDied; // 泄漏！
        EventBus<DamageEvent>.Subscribe(HandleDamage);  // 泄漏！
    }
    
    void HandlePlayerDied() { }
    void HandleDamage(DamageEvent e) { }
}

// ✅ 正确：配对的订阅/取消订阅
public class EnemyUI : MonoBehaviour
{
    void OnEnable()
    {
        GameManager.OnPlayerDied += HandlePlayerDied;
        EventBus<DamageEvent>.Subscribe(HandleDamage);
    }
    
    void OnDisable()
    {
        GameManager.OnPlayerDied -= HandlePlayerDied;
        EventBus<DamageEvent>.Unsubscribe(HandleDamage);
    }
    
    void OnDestroy()
    {
        // 双重保险（特别是禁用后销毁的情况）
        GameManager.OnPlayerDied -= HandlePlayerDied;
    }
}
```

### 2.2 静态引用泄漏

```csharp
// ❌ 错误：静态列表持有 MonoBehaviour 引用
public class EnemyManager
{
    // 场景卸载后，enemies 中的对象已销毁，但 List 仍持有引用
    private static List<Enemy> enemies = new List<Enemy>(); 
    
    public static void Register(Enemy e) => enemies.Add(e);
    // 没有对应的 Unregister！
}

// ✅ 正确：使用 RuntimeSet ScriptableObject（OnDisable 自动清空）
// 或确保 Enemy.OnDestroy 时调用 Unregister

public class Enemy : MonoBehaviour
{
    void OnEnable()  => EnemyManager.Register(this);
    void OnDisable() => EnemyManager.Unregister(this); // 配对清理
}
```

### 2.3 Texture/Sprite 未释放

```csharp
// ❌ 错误：动态加载的纹理从不释放
public class AvatarLoader : MonoBehaviour
{
    async void LoadAvatar(string url)
    {
        using var req = UnityEngine.Networking.UnityWebRequestTexture.GetTexture(url);
        await req.SendWebRequest();
        var tex = UnityEngine.Networking.DownloadHandlerTexture.GetContent(req);
        GetComponent<UnityEngine.UI.RawImage>().texture = tex;
        // tex 没有存储引用，也没有设置释放机制！
    }
}

// ✅ 正确：跟踪并在不需要时释放
public class AvatarLoader : MonoBehaviour
{
    private Texture2D loadedTexture;
    
    async void LoadAvatar(string url)
    {
        using var req = UnityEngine.Networking.UnityWebRequestTexture.GetTexture(url);
        await req.SendWebRequest();
        
        // 释放旧纹理
        if (loadedTexture != null)
            Destroy(loadedTexture);
        
        loadedTexture = UnityEngine.Networking.DownloadHandlerTexture.GetContent(req);
        GetComponent<UnityEngine.UI.RawImage>().texture = loadedTexture;
    }
    
    void OnDestroy()
    {
        if (loadedTexture != null)
            Destroy(loadedTexture);
    }
}
```

### 2.4 协程泄漏

```csharp
// ❌ 错误：对象销毁后协程仍在运行（持有 this 引用）
public class HealSystem : MonoBehaviour
{
    void Start()
    {
        // 如果 HealSystem 被销毁，这个协程还在跑
        StartCoroutine(HealRoutine());
    }
    
    IEnumerator HealRoutine()
    {
        while (true) // 永远运行
        {
            yield return new WaitForSeconds(1f);
            // this 可能已经被销毁
        }
    }
}

// ✅ 正确：守护条件 + 保存引用
public class HealSystem : MonoBehaviour
{
    private Coroutine healCoroutine;
    
    void OnEnable()  => healCoroutine = StartCoroutine(HealRoutine());
    void OnDisable()
    {
        if (healCoroutine != null)
        {
            StopCoroutine(healCoroutine);
            healCoroutine = null;
        }
    }
    
    IEnumerator HealRoutine()
    {
        while (this != null && gameObject.activeInHierarchy) // 守护条件
        {
            yield return new WaitForSeconds(1f);
            // 安全执行
        }
    }
}
```

### 2.5 Addressables 未释放

```csharp
// ❌ 错误：多次 LoadAssetAsync 但没有 Release
public class WeaponSpawner : MonoBehaviour
{
    async void SpawnWeapon(string weaponId)
    {
        // 每次调用都会增加引用计数，但从不减少
        var handle = Addressables.LoadAssetAsync<GameObject>(weaponId);
        var prefab = await handle.Task;
        Instantiate(prefab);
        // handle 泄漏！
    }
}

// ✅ 正确：跟踪 Handle，在不需要时释放
public class WeaponSpawner : MonoBehaviour
{
    private List<UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationHandle> handles 
        = new List<UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationHandle>();
    
    async void SpawnWeapon(string weaponId)
    {
        var handle = Addressables.LoadAssetAsync<GameObject>(weaponId);
        handles.Add(handle);
        
        var prefab = await handle.Task;
        if (handle.Status == UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationStatus.Succeeded)
            Instantiate(prefab);
    }
    
    void OnDestroy()
    {
        foreach (var handle in handles)
            Addressables.Release(handle);
        handles.Clear();
    }
}
```

---

## 三、内存泄漏检测工具

### 3.1 Unity Memory Profiler

```csharp
/// <summary>
/// 运行时内存监控
/// </summary>
public class MemoryMonitor : MonoBehaviour
{
    [SerializeField] private float reportInterval = 30f;
    [SerializeField] private float warningThresholdMB = 1500f;
    
    private float timer;
    private long lastMonoMemory;

    void Update()
    {
        timer += Time.deltaTime;
        if (timer >= reportInterval)
        {
            timer = 0;
            ReportMemory();
        }
    }

    void ReportMemory()
    {
        long monoMemory = System.GC.GetTotalMemory(false) / 1024 / 1024; // MB
        long unityMemory = (long)(UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong() 
            / 1024 / 1024); // MB
        long reservedMemory = (long)(UnityEngine.Profiling.Profiler.GetTotalReservedMemoryLong() 
            / 1024 / 1024); // MB
        
        long monoGrowth = monoMemory - lastMonoMemory;
        lastMonoMemory = monoMemory;
        
        string report = $"[Memory] Mono: {monoMemory}MB (Δ{monoGrowth:+0;-0}MB) | " +
                        $"Unity: {unityMemory}MB | Reserved: {reservedMemory}MB";
        
        if (unityMemory > warningThresholdMB)
            Debug.LogWarning($"⚠️ {report}");
        else
            Debug.Log(report);
        
        // 如果 Mono 内存持续增长，可能有泄漏
        if (monoGrowth > 50)
            Debug.LogWarning($"[Memory] 🔴 Mono memory growing rapidly: +{monoGrowth}MB");
    }
    
    [ContextMenu("Force GC")]
    void ForceGC()
    {
        System.GC.Collect();
        Resources.UnloadUnusedAssets();
        Debug.Log("[Memory] GC collected + UnloadUnusedAssets called");
    }
}
```

### 3.2 内存快照比较工具

```csharp
/// <summary>
/// 简单的对象计数快照（辅助发现泄漏）
/// </summary>
public static class MemorySnapshot
{
    private static Dictionary<string, int> snapshot = new Dictionary<string, int>();

    /// <summary>
    /// 拍摄当前 Unity Object 数量快照
    /// </summary>
    [System.Diagnostics.Conditional("UNITY_EDITOR")]
    public static void TakeSnapshot(string label)
    {
        #if UNITY_EDITOR
        snapshot.Clear();
        
        var allObjects = Resources.FindObjectsOfTypeAll<UnityEngine.Object>();
        foreach (var obj in allObjects)
        {
            string typeName = obj.GetType().Name;
            if (!snapshot.ContainsKey(typeName)) snapshot[typeName] = 0;
            snapshot[typeName]++;
        }
        
        Debug.Log($"[MemSnapshot] '{label}': {allObjects.Length} objects total");
        #endif
    }

    /// <summary>
    /// 与上次快照比较，输出差异
    /// </summary>
    [System.Diagnostics.Conditional("UNITY_EDITOR")]
    public static void CompareWithSnapshot(string label)
    {
        #if UNITY_EDITOR
        var current = new Dictionary<string, int>();
        var allObjects = Resources.FindObjectsOfTypeAll<UnityEngine.Object>();
        
        foreach (var obj in allObjects)
        {
            string typeName = obj.GetType().Name;
            if (!current.ContainsKey(typeName)) current[typeName] = 0;
            current[typeName]++;
        }
        
        var differences = new List<string>();
        
        foreach (var kv in current)
        {
            int old = snapshot.TryGetValue(kv.Key, out int v) ? v : 0;
            int diff = kv.Value - old;
            if (diff > 0)
                differences.Add($"{kv.Key}: +{diff} (was {old}, now {kv.Value})");
        }
        
        if (differences.Count > 0)
        {
            Debug.LogWarning($"[MemSnapshot] '{label}' diff (potential leaks):\n" + 
                string.Join("\n", differences));
        }
        else
        {
            Debug.Log($"[MemSnapshot] '{label}': No significant changes");
        }
        #endif
    }
}
```

---

## 四、泄漏修复 Checklist

| 检查项 | 修复方案 |
|--------|----------|
| C# 事件订阅 | OnEnable 订阅，OnDisable/OnDestroy 取消 |
| Unity Message/Action | 同上 |
| 协程 | OnDisable 停止，使用守护条件 |
| 动态创建的 Texture | 存引用，OnDestroy 时 Destroy |
| Addressables Handle | 跟踪所有 Handle，统一在 OnDestroy 释放 |
| 静态列表/字典 | 确保配对的注册/注销，场景卸载时清空 |
| RenderTexture | 不再使用时 Release() |
| Native 数组 (NativeArray) | 使用后 Dispose() 或 using |
| 场景切换 | 确保旧场景资源完全卸载 |

**调试工具：**
- Unity Memory Profiler Package（详细快照）
- Unity Profiler Memory 模块
- VS/Rider 内存分析器（Mono 托管内存）
- LeakSanitizer（原生内存）
