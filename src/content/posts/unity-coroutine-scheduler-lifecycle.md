---
title: 协程调度器：统一管理 Unity 协程生命周期的工程方案
published: 2026-03-31
description: 深入解析游戏框架中协程调度器的设计，理解如何避免协程泄漏、实现协程分组管理和与 ETTask 异步系统的协同工作。
tags: [Unity, 协程, 调度器, 生命周期管理]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 协程的问题

Unity 的协程（Coroutine）是很多游戏逻辑的"银弹"，但它有几个固有问题：

1. **泄漏风险**：GameObject 销毁后，它启动的协程会停止，但如果通过其他 MonoBehaviour 启动，协程会继续运行
2. **无法追踪**：启动 100 个协程后，你不知道哪些还在运行
3. **无法分组停止**：想停掉"某个功能相关的所有协程"，没有内置方法
4. **异常处理**：协程内的异常会被静默吞掉

---

## 协程调度器的核心设计

```csharp
public class CoroutineScheduler : Singleton<CoroutineScheduler>
{
    private MonoBehaviour _runner;  // 实际运行协程的 MonoBehaviour
    
    // 分组管理：组名 → 协程列表
    private Dictionary<string, List<Coroutine>> _groups = new();
    
    public void Init(MonoBehaviour runner)
    {
        _runner = runner;
    }
    
    // 启动协程（带分组）
    public Coroutine Start(IEnumerator routine, string group = "default")
    {
        if (_runner == null)
        {
            Log.Error("CoroutineScheduler not initialized!");
            return null;
        }
        
        var coroutine = _runner.StartCoroutine(WrapCoroutine(routine, group));
        
        if (!_groups.ContainsKey(group))
            _groups[group] = new List<Coroutine>();
        
        _groups[group].Add(coroutine);
        return coroutine;
    }
    
    // 包装协程：添加异常捕获 + 完成时清理
    private IEnumerator WrapCoroutine(IEnumerator routine, string group)
    {
        Coroutine handle = null;
        
        while (true)
        {
            object current;
            try
            {
                if (!routine.MoveNext()) break;
                current = routine.Current;
            }
            catch (Exception e)
            {
                Log.Error($"Coroutine exception in group '{group}': {e}");
                break;
            }
            yield return current;
        }
        
        // 自动从分组中移除（延迟移除避免迭代器冲突）
        // handle 赋值在 Start 后，这里只做标记
    }
    
    // 停止某组的所有协程
    public void StopGroup(string group)
    {
        if (_groups.TryGetValue(group, out var coroutines))
        {
            foreach (var co in coroutines)
            {
                if (co != null)
                    _runner.StopCoroutine(co);
            }
            _groups.Remove(group);
        }
    }
    
    // 停止所有协程
    public void StopAll()
    {
        _runner.StopAllCoroutines();
        _groups.Clear();
    }
}
```

---

## ETTask.Coroutine() 的内部实现

回顾 ETTask 中的 `.Coroutine()` 方法：

```csharp
// ETTask 的扩展方法
public static void Coroutine(this ETTask task)
{
    InnerCoroutine(task).Coroutine();
}

private static async ETVoid InnerCoroutine(ETTask task)
{
    try
    {
        await task;
    }
    catch (Exception e)
    {
        ETTask.ExceptionHandler?.Invoke(e);
    }
}
```

`.Coroutine()` 本质上是 "fire-and-forget" 模式：启动一个不被 await 的异步任务，但确保异常不会被静默吞掉。

ETTask 和 Unity 协程各有适用场景：

| 场景 | 推荐方式 |
|------|---------|
| 需要返回值 | ETTask\<T\> |
| 需要 await 等待完成 | ETTask |
| 不关心完成时机 | ETTask.Coroutine() |
| 需要 yield return WaitForSeconds | 传统协程（或 TimerComponent） |
| 需要 yield return UnityWebRequest | CoroutineHelper.HttpGet |

---

## 协程与 ETTask 的互相转换

### 协程 → ETTask

```csharp
// 把协程包装成 ETTask
public static async ETTask FromCoroutine(IEnumerator routine)
{
    ETTask tcs = ETTask.Create(true);
    
    CoroutineScheduler.Instance.Start(RunAndComplete(routine, tcs));
    
    await tcs;
}

private static IEnumerator RunAndComplete(IEnumerator routine, ETTask tcs)
{
    yield return routine;
    tcs.SetResult();
}

// 使用
await CoroutineConverter.FromCoroutine(SomeLegacyCoroutine());
```

### ETTask → 协程（用于不支持 async/await 的场景）

```csharp
// 把 ETTask 转成协程（场景：需要在 IEnumerator 中等待 ETTask）
public static IEnumerator ToCoroutine(ETTask task)
{
    while (!task.IsCompleted)
        yield return null;
}

// 在协程中等待 ETTask
IEnumerator LoadAndShowUI()
{
    yield return CoroutineConverter.ToCoroutine(LoadUIAsync());
    ShowUI();
}
```

---

## 避免协程泄漏的最佳实践

### 使用 CoroutineCanceller

```csharp
public class UIPopup : MonoBehaviour
{
    private Coroutine _animCoroutine;
    
    public void Show()
    {
        // 停止旧的动画协程
        if (_animCoroutine != null)
        {
            StopCoroutine(_animCoroutine);
        }
        
        _animCoroutine = StartCoroutine(ShowAnimation());
    }
    
    public void Hide()
    {
        if (_animCoroutine != null)
        {
            StopCoroutine(_animCoroutine);
            _animCoroutine = null;
        }
        StartCoroutine(HideAnimation());
    }
    
    private void OnDestroy()
    {
        // 确保组件销毁时停止所有协程
        StopAllCoroutines();
    }
}
```

---

## 总结

协程调度器解决了 Unity 协程的几个核心问题：

| 问题 | 解决方案 |
|------|---------|
| 协程泄漏 | 分组管理 + 场景切换时 StopAll |
| 无法追踪 | 字典存储分组协程列表 |
| 异常静默 | WrapCoroutine 中捕获并记录 |
| 分组停止 | StopGroup(groupName) |

在新项目中，推荐优先使用 ETTask（更安全、更可追踪），传统协程作为特殊场景的补充（如需要 yield return 特殊 Unity 对象时）。
