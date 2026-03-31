---
title: 如何用扩展方法让 Unity 协程与 ETTask 异步系统无缝协作
published: 2026-03-31
description: 解析 CoroutineHelper 如何通过扩展方法桥接 Unity 的 AsyncOperation 到 ETTask 系统，以及 UnityWebRequest 的异步封装实践。
tags: [Unity, 协程桥接, 扩展方法, 网络请求]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 问题：Unity 的异步 API 不能直接 await

Unity 有大量返回 `AsyncOperation` 的异步 API：

```csharp
// 这些都返回 AsyncOperation 或其子类
var op = Resources.LoadAsync<GameObject>("Prefabs/Hero");
var op = SceneManager.LoadSceneAsync("GameScene");
var op = AssetBundle.LoadFromFileAsync("path/to/bundle");
var op = Addressables.LoadAssetAsync<GameObject>("key");
```

如果我们的框架用 `ETTask` 替代了 `System.Task`，这些 Unity 原生的异步操作就无法直接 `await`——编译器不认识 `AsyncOperation` 的 `GetAwaiter` 方法。

`CoroutineHelper` 通过**扩展方法**解决了这个问题。

---

## 核心实现：GetAwaiter 扩展方法

```csharp
public static class CoroutineHelper
{
    // 让 AsyncOperation 可以被 await（返回 ETTask）
    public static async ETTask GetAwaiter(this AsyncOperation asyncOperation)
    {
        ETTask task = ETTask.Create(true);                         // 从对象池创建
        asyncOperation.completed += _ => { task.SetResult(); };   // 完成时触发
        await task;                                                // 等待完成
    }
}
```

有了这个扩展方法后，任何 `AsyncOperation` 都可以直接用 `await`：

```csharp
// 加载场景
await SceneManager.LoadSceneAsync("BattleScene");

// 加载资源
var op = Resources.LoadAsync<GameObject>("Prefabs/Hero");
await op;
var hero = op.asset as GameObject;

// 加载 AssetBundle
await AssetBundle.LoadFromFileAsync("path/to/bundle");
```

---

## 扩展方法的工作原理

C# 允许给任意类型添加"扩展方法"，只需：
1. 写在静态类中
2. 方法第一个参数用 `this` 修饰，指定要扩展的类型

```csharp
public static class StringExtensions
{
    // 给 string 类型添加 ToInt 方法
    public static int ToInt(this string str)
    {
        return int.Parse(str);
    }
}

// 使用
int n = "42".ToInt();  // 等价于 StringExtensions.ToInt("42")
```

对于 `await` 来说，编译器查找的是被 `await` 的对象的 `GetAwaiter()` 方法（可以是扩展方法）。所以给 `AsyncOperation` 添加 `GetAwaiter` 扩展方法，就让它支持了 `await`。

---

## completed 事件的生命周期

```csharp
asyncOperation.completed += _ => { task.SetResult(); };
```

Unity 的 `AsyncOperation.completed` 是一个 `Action<AsyncOperation>` 事件，在异步操作完成时被触发（只触发一次）。

这里用 Lambda 注册了回调：当 `asyncOperation` 完成时，调用 `task.SetResult()`，通知所有等待 `task` 的代码继续执行。

**为什么不用 `asyncOperation.isDone`？**

轮询 `isDone` 需要每帧检查，浪费 CPU。事件回调是事件驱动的——只在完成时触发一次，没有额外开销。

---

## HTTP 请求封装

```csharp
public static async ETTask<string> HttpGet(string link)
{
    try
    {
        UnityWebRequest req = UnityWebRequest.Get(link);
        await req.SendWebRequest();   // SendWebRequest 返回 UnityWebRequestAsyncOperation
        return req.downloadHandler.text;
    }
    catch (Exception e)
    {
        // 截短 URL（去掉查询参数）以避免日志中暴露敏感信息
        throw new Exception($"http request fail: {link.Substring(0, link.IndexOf('?'))}\n{e}");
    }
}
```

`UnityWebRequest.SendWebRequest()` 返回 `UnityWebRequestAsyncOperation`，它继承自 `AsyncOperation`，因此也可以直接 `await`（借助上面的扩展方法）。

使用示例：

```csharp
// 获取服务器配置
public async ETTask LoadRemoteConfig()
{
    string json = await CoroutineHelper.HttpGet(
        "https://config.example.com/game/config.json");
    
    var config = JsonUtility.FromJson<GameConfig>(json);
    ApplyConfig(config);
}
```

---

## Addressables 的桥接

Addressables 使用的是 `AsyncOperationHandle<T>`，不直接继承 `AsyncOperation`。通常通过 `.Task` 属性桥接到 C# Task：

```csharp
// 直接用 Addressables 异步（不走 ETTask）
var handle = Addressables.LoadAssetAsync<GameObject>("key");
return await handle.Task;  // C# Task 桥接
```

但 ETTask 框架中，通常在 `ResManager` 中统一处理，外部直接调用 `ResManager.LoadAsync<T>`，不直接接触 Addressables API。

---

## 实战：场景加载进度条

结合 `AsyncOperation` 的 `progress` 属性，可以实现加载进度条：

```csharp
public async ETTask LoadSceneWithProgress(string sceneName, Action<float> onProgress)
{
    var op = SceneManager.LoadSceneAsync(sceneName);
    op.allowSceneActivation = false;  // 不自动激活，等进度达到 0.9 再激活
    
    // 等待加载完成（不用 await，因为需要在等待过程中汇报进度）
    while (!op.isDone)
    {
        float progress = Mathf.Clamp01(op.progress / 0.9f);  // 0~0.9 映射到 0~1
        onProgress?.Invoke(progress);
        
        if (op.progress >= 0.9f)
        {
            onProgress?.Invoke(1f);     // 报告 100%
            op.allowSceneActivation = true;  // 激活场景
        }
        
        await TimerComponent.Instance.WaitFrameAsync();  // 等一帧
    }
}
```

---

## 与协程的对比

实现同样的功能，协程版本：

```csharp
// 协程版本：无法直接返回值
IEnumerator LoadSceneCoroutine(string sceneName)
{
    var op = SceneManager.LoadSceneAsync(sceneName);
    yield return op;
    Debug.Log("加载完成");
    // 问题：无法返回加载结果给调用者
}

// ETTask 版本：可以返回值，可以被 await
async ETTask<GameObject> LoadPrefabAsync(string path)
{
    var op = Addressables.LoadAssetAsync<GameObject>(path);
    await op.Task;
    return op.Result;  // 直接返回结果！
}
```

ETTask 版本可以链式编程，代码更线性、更容易理解。

---

## 总结

`CoroutineHelper` 展示了两个优雅的工程技巧：

**扩展方法 + GetAwaiter**：
通过给 `AsyncOperation` 添加 `GetAwaiter` 扩展，无需修改 Unity 内部代码，就让全部原生异步 API 支持了 `await ETTask` 语法。

**事件回调转 Task**：
`asyncOperation.completed += _ => task.SetResult()` 是将事件回调模式转换为 Task 模式的标准做法。这种转换技巧在很多场景都能用到：UI 事件、物理回调、网络回调……

掌握这两个技巧，你就能轻松地为任何不支持 `await` 的异步 API 添加 ETTask 支持。
