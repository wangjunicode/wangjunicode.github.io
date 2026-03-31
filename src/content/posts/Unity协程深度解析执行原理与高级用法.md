---
title: Unity协程深度解析：执行原理与高级用法
published: 2026-03-31
description: 全面解析Unity协程的底层执行机制（IEnumerator状态机/MoveNext调用时机）、协程的正确启动/停止方式、常用等待类型（WaitForSeconds/WaitUntil/WaitForEndOfFrame）的性能差异、协程链式调用、协程池化方案、协程与UniTask的选型对比，以及常见协程陷阱（在对象销毁后继续执行/GC问题）。
tags: [Unity, 协程, Coroutine, UniTask, 游戏开发]
category: 工程实践
draft: false
---

## 一、协程执行原理

```csharp
// Unity 协程本质：C# 迭代器（IEnumerator）
// Unity 在每帧合适的时机调用 MoveNext()

// 编译器将 yield return 转换为状态机：
IEnumerator MyCoroutine() // 源码
{
    yield return null;
    yield return new WaitForSeconds(2f);
    DoSomething();
}

// 等价的状态机（编译器生成）：
class MyCoroutine_StateMachine : IEnumerator
{
    int _state = 0;
    
    public bool MoveNext()
    {
        switch (_state)
        {
            case 0:
                _state = 1;
                Current = null; // yield return null
                return true;   // 告诉Unity：还没结束，下帧继续
                
            case 1:
                _state = 2;
                Current = new WaitForSeconds(2f);
                return true;
                
            case 2:
                DoSomething();
                return false;  // 结束
        }
        return false;
    }
    
    public object Current { get; private set; }
    public void Reset() { _state = 0; }
}
```

---

## 二、等待类型性能对比

```csharp
using System.Collections;
using UnityEngine;

public class CoroutinePerformanceGuide : MonoBehaviour
{
    // ========== 各种等待方式的性能 ==========
    
    IEnumerator WaitExamples()
    {
        // ✅ 推荐：WaitForSeconds（Unity内部优化，不每帧检查）
        yield return new WaitForSeconds(2f);
        
        // ✅ 推荐（缓存复用，避免GC）
        var wait = new WaitForSeconds(0.1f);
        for (int i = 0; i < 100; i++)
        {
            yield return wait; // 不要写 new WaitForSeconds(0.1f) 在循环里！
        }
        
        // ✅ WaitForEndOfFrame：渲染后执行（截图等用途）
        yield return new WaitForEndOfFrame();
        
        // ✅ WaitForFixedUpdate：等待下次 FixedUpdate
        yield return new WaitForFixedUpdate();
        
        // ⚠️ 注意：WaitUntil 每帧调用委托，有GC分配
        yield return new WaitUntil(() => isEnemyDead); // 每帧new WaitUntil内部的检查
        
        // ✅ 对于简单条件，用 while+yield null 替代 WaitUntil（无额外GC）
        while (!isEnemyDead)
            yield return null;
        
        // yield return null：等待1帧（最常用）
        yield return null;
        
        // 嵌套协程：等待另一个协程完成
        yield return StartCoroutine(SubCoroutine());
    }
    
    private bool isEnemyDead;

    IEnumerator SubCoroutine()
    {
        yield return new WaitForSeconds(1f);
    }
}
```

---

## 三、协程陷阱与正确用法

```csharp
/// <summary>
/// 协程常见陷阱修复指南
/// </summary>
public class CoroutinePitfalls : MonoBehaviour
{
    // ========== 陷阱1：GameObject销毁后协程继续执行 ==========
    
    // ❌ 错误：协程引用了已销毁的对象
    IEnumerator BadCoroutine(Transform target)
    {
        while (true)
        {
            transform.LookAt(target.position); // 如果 target 被销毁，报错！
            yield return null;
        }
    }
    
    // ✅ 正确：检查引用有效性
    IEnumerator SafeCoroutine(Transform target)
    {
        while (target != null) // Unity已重载 == null 检查
        {
            transform.LookAt(target.position);
            yield return null;
        }
    }
    
    // ========== 陷阱2：在OnDisable后协程不会自动停止 ==========
    
    private Coroutine myCoroutine;
    
    void OnEnable()
    {
        myCoroutine = StartCoroutine(MyLongCoroutine());
    }
    
    void OnDisable()
    {
        // ✅ 必须手动停止
        if (myCoroutine != null)
        {
            StopCoroutine(myCoroutine);
            myCoroutine = null;
        }
    }
    
    IEnumerator MyLongCoroutine()
    {
        while (true)
        {
            yield return new WaitForSeconds(1f);
            Debug.Log("Still running...");
        }
    }
    
    // ========== 陷阱3：StopCoroutine 需要匹配方式 ==========
    
    // ❌ 错误：StartCoroutine和StopCoroutine方式不匹配
    void StartWrong()
    {
        StartCoroutine("MyCoroutine"); // 字符串方式启动
    }
    
    void StopWrong()
    {
        // StopCoroutine(myCoroutineRef); // 用引用停止字符串启动的协程无效！
    }
    
    // ✅ 正确方式一：用引用匹配
    Coroutine coroutineRef;
    void StartRight()
    {
        coroutineRef = StartCoroutine(MyCoroutine());
    }
    void StopRight()
    {
        if (coroutineRef != null) StopCoroutine(coroutineRef);
    }
    
    // ✅ 正确方式二：字符串匹配（仅限同一MonoBehaviour上）
    void StartRight2() => StartCoroutine("MyCoroutine");
    void StopRight2()  => StopCoroutine("MyCoroutine");
    
    IEnumerator MyCoroutine() { yield return null; }
    
    // ========== 陷阱4：协程不能跨MonoBehaviour调用 ==========
    // StartCoroutine 只能在挂载该协程的 MonoBehaviour 上调用
    // 解决方案：使用 CoroutineRunner 单例
}

/// <summary>
/// 全局协程执行器（用于在非MonoBehaviour代码中运行协程）
/// </summary>
public class CoroutineRunner : MonoBehaviour
{
    private static CoroutineRunner instance;
    
    public static CoroutineRunner Instance
    {
        get
        {
            if (instance == null)
            {
                var go = new GameObject("[CoroutineRunner]");
                DontDestroyOnLoad(go);
                instance = go.AddComponent<CoroutineRunner>();
            }
            return instance;
        }
    }
    
    public static Coroutine Run(IEnumerator coroutine)
        => Instance.StartCoroutine(coroutine);
    
    public static void Stop(Coroutine coroutine)
    {
        if (instance != null && coroutine != null)
            instance.StopCoroutine(coroutine);
    }
}
```

---

## 四、协程池化（减少GC）

```csharp
/// <summary>
/// 可复用的缓存等待对象（减少GC）
/// </summary>
public static class WaitCache
{
    private static Dictionary<float, WaitForSeconds> waitCache 
        = new Dictionary<float, WaitForSeconds>();
    
    private static WaitForEndOfFrame waitForEndOfFrame = new WaitForEndOfFrame();
    private static WaitForFixedUpdate waitForFixedUpdate = new WaitForFixedUpdate();

    public static WaitForEndOfFrame EndOfFrame => waitForEndOfFrame;
    public static WaitForFixedUpdate FixedUpdate => waitForFixedUpdate;

    /// <summary>
    /// 获取缓存的 WaitForSeconds（相同时间值复用同一实例）
    /// </summary>
    public static WaitForSeconds Seconds(float seconds)
    {
        if (!waitCache.TryGetValue(seconds, out var wait))
        {
            wait = new WaitForSeconds(seconds);
            waitCache[seconds] = wait;
        }
        return wait;
    }
}

// 使用示例
public class OptimizedCoroutine : MonoBehaviour
{
    IEnumerator SpawnEnemies()
    {
        while (true)
        {
            SpawnEnemy();
            yield return WaitCache.Seconds(3f); // 复用缓存，无GC
        }
    }
    
    void SpawnEnemy() { }
}
```

---

## 五、协程 vs UniTask 选型

| 维度 | 协程 | UniTask |
|------|------|---------|
| 语法 | `yield return` | `await` |
| 错误处理 | 无法直接 try-catch | 完整异常处理 |
| 取消 | StopCoroutine | CancellationToken |
| 性能 | 有GC分配 | 近零GC |
| 返回值 | 只能 out 参数 | 直接返回值 |
| 调试 | 困难（无堆栈）| 完整堆栈跟踪 |
| 学习曲线 | 低 | 中 |

**推荐：**
- 简单计时/延迟 → 协程（简单够用）
- 异步资源加载/网络/复杂流程控制 → UniTask
