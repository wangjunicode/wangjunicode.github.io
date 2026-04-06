---
title: Unity资源加载优化：Async加载与进度回调
published: 2026-03-31
description: 深度解析Unity资源异步加载的完整方案，涵盖Addressables异步加载与引用管理、场景异步加载进度反馈、Resource.LoadAsync与AssetBundle对比、加载优先级队列、预加载策略（关卡开始前预加载下一关所需资源）、加载屏幕与进度条设计，以及防止加载闪烁的最佳实践。
tags: [Unity, 资源加载, Addressables, 异步加载, 性能优化]
category: 资源管理
draft: false
---

## 一、Addressables 异步加载

```csharp
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
using System.Collections.Generic;
using System.Threading.Tasks;

/// <summary>
/// 资源加载管理器（基于 Addressables）
/// </summary>
public class AssetLoader : MonoBehaviour
{
    private static AssetLoader instance;
    public static AssetLoader Instance => instance;

    // 跟踪所有活跃的加载句柄（用于释放）
    private Dictionary<string, AsyncOperationHandle> activeHandles 
        = new Dictionary<string, AsyncOperationHandle>();

    void Awake() { instance = this; }

    // ============ 异步加载接口 ============

    /// <summary>
    /// 异步加载资产（Task 风格）
    /// </summary>
    public async Task<T> LoadAsync<T>(string address) where T : UnityEngine.Object
    {
        if (activeHandles.ContainsKey(address))
        {
            var existingHandle = activeHandles[address];
            await existingHandle.Task;
            return (T)existingHandle.Result;
        }
        
        var handle = Addressables.LoadAssetAsync<T>(address);
        activeHandles[address] = handle;
        
        await handle.Task;
        
        if (handle.Status != AsyncOperationStatus.Succeeded)
        {
            Debug.LogError($"[AssetLoader] Failed to load: {address}");
            activeHandles.Remove(address);
            return null;
        }
        
        return handle.Result;
    }

    /// <summary>
    /// 批量加载（带进度回调）
    /// </summary>
    public async Task<List<T>> LoadBatchAsync<T>(List<string> addresses,
        System.Action<float> onProgress = null) where T : UnityEngine.Object
    {
        var results = new List<T>();
        int total = addresses.Count;
        int completed = 0;
        
        var tasks = new List<Task<T>>();
        
        foreach (var address in addresses)
        {
            tasks.Add(LoadAsync<T>(address));
        }
        
        // 并行加载（比顺序加载快）
        while (tasks.Count > 0)
        {
            var finished = await Task.WhenAny(tasks);
            tasks.Remove(finished);
            
            T result = await finished;
            if (result != null) results.Add(result);
            
            completed++;
            onProgress?.Invoke((float)completed / total);
        }
        
        return results;
    }

    /// <summary>
    /// 预加载（不立即使用，提前缓存到内存）
    /// </summary>
    public async Task PreloadAsync(List<string> addresses, 
        System.Action<float> onProgress = null)
    {
        int total = addresses.Count;
        int completed = 0;
        
        foreach (var address in addresses)
        {
            if (!activeHandles.ContainsKey(address))
            {
                var handle = Addressables.LoadAssetAsync<UnityEngine.Object>(address);
                activeHandles[address] = handle;
                await handle.Task;
            }
            
            completed++;
            onProgress?.Invoke((float)completed / total);
        }
    }

    /// <summary>
    /// 释放资源引用
    /// </summary>
    public void Release(string address)
    {
        if (activeHandles.TryGetValue(address, out var handle))
        {
            Addressables.Release(handle);
            activeHandles.Remove(address);
        }
    }

    /// <summary>
    /// 批量释放（场景切换时调用）
    /// </summary>
    public void ReleaseAll()
    {
        foreach (var handle in activeHandles.Values)
            Addressables.Release(handle);
        activeHandles.Clear();
    }
}
```

---

## 二、场景异步加载控制器

```csharp
/// <summary>
/// 场景加载管理器（带进度条和加载屏）
/// </summary>
public class SceneLoadManager : MonoBehaviour
{
    private static SceneLoadManager instance;
    public static SceneLoadManager Instance => instance;

    [Header("加载界面")]
    [SerializeField] private GameObject loadingScreen;
    [SerializeField] private UnityEngine.UI.Slider progressBar;
    [SerializeField] private UnityEngine.UI.Text progressText;
    [SerializeField] private UnityEngine.UI.Text loadingTipText;
    [SerializeField] private UnityEngine.UI.Image loadingBackground;
    
    [Header("加载提示")]
    [SerializeField] private string[] loadingTips;
    [SerializeField] private float tipChangeInterval = 3f;
    
    // 最小加载时间（防止加载屏一闪而过，影响体验）
    [SerializeField] private float minLoadingTime = 1.5f;

    void Awake() { instance = this; }

    /// <summary>
    /// 加载场景
    /// </summary>
    public async Task LoadSceneAsync(string sceneName, Sprite backgroundSprite = null)
    {
        // 显示加载屏
        ShowLoadingScreen(backgroundSprite);
        
        float startTime = Time.time;
        float fakeProgress = 0f;     // 伪进度（保证不会太快）
        
        // 异步加载场景（先卸载旧场景资源）
        var operation = UnityEngine.SceneManagement.SceneManager.LoadSceneAsync(
            sceneName, UnityEngine.SceneManagement.LoadSceneMode.Single);
        
        // 阻止自动激活（等进度条到90%再激活）
        operation.allowSceneActivation = false;
        
        // 更新进度
        while (!operation.isDone)
        {
            // Unity 加载进度：0-0.9 加载资源，0.9 激活场景
            float loadProgress = Mathf.Clamp01(operation.progress / 0.9f);
            
            // 伪进度平滑（避免卡在某个值）
            fakeProgress = Mathf.MoveTowards(fakeProgress, loadProgress, Time.deltaTime * 0.5f);
            
            float elapsed = Time.time - startTime;
            float timeProgress = Mathf.Clamp01(elapsed / minLoadingTime);
            
            // 取两者中的较小值（都完成才能推进）
            float displayProgress = Mathf.Min(fakeProgress, timeProgress);
            
            UpdateProgressUI(displayProgress);
            
            // 加载资源完成 + 最小时间到了 → 激活场景
            if (loadProgress >= 0.99f && elapsed >= minLoadingTime)
            {
                operation.allowSceneActivation = true;
            }
            
            await Task.Yield();
        }
        
        // 等一帧确保场景完全初始化
        await Task.Yield();
        
        HideLoadingScreen();
    }

    void ShowLoadingScreen(Sprite background)
    {
        loadingScreen.SetActive(true);
        progressBar.value = 0f;
        progressText.text = "0%";
        
        if (background != null && loadingBackground != null)
            loadingBackground.sprite = background;
        
        // 开始提示轮播
        StartCoroutine(CycleTips());
    }

    void HideLoadingScreen()
    {
        StopAllCoroutines();
        loadingScreen.SetActive(false);
    }

    void UpdateProgressUI(float progress)
    {
        progressBar.value = progress;
        progressText.text = $"{progress * 100:F0}%";
    }

    System.Collections.IEnumerator CycleTips()
    {
        if (loadingTips == null || loadingTips.Length == 0) yield break;
        
        while (true)
        {
            loadingTipText.text = loadingTips[UnityEngine.Random.Range(0, loadingTips.Length)];
            yield return new WaitForSecondsRealtime(tipChangeInterval);
        }
    }
}
```

---

## 三、加载优先级队列

```csharp
/// <summary>
/// 资源加载优先级队列（高优先级资源先加载）
/// </summary>
public class PriorityAssetLoader : MonoBehaviour
{
    public enum LoadPriority { Critical = 0, High = 1, Normal = 2, Low = 3 }

    private class LoadRequest
    {
        public string Address;
        public LoadPriority Priority;
        public System.Action<UnityEngine.Object> OnComplete;
        public System.Type AssetType;
    }

    private SortedList<int, Queue<LoadRequest>> queues 
        = new SortedList<int, Queue<LoadRequest>>();
    
    private bool isProcessing;
    private const int MAX_CONCURRENT = 3; // 最大并发加载数
    private int currentConcurrent;

    public void Request<T>(string address, System.Action<T> onComplete,
        LoadPriority priority = LoadPriority.Normal) where T : UnityEngine.Object
    {
        int key = (int)priority;
        if (!queues.ContainsKey(key))
            queues[key] = new Queue<LoadRequest>();
        
        queues[key].Enqueue(new LoadRequest
        {
            Address = address,
            Priority = priority,
            AssetType = typeof(T),
            OnComplete = obj => onComplete?.Invoke(obj as T)
        });
        
        ProcessQueue();
    }

    void ProcessQueue()
    {
        while (currentConcurrent < MAX_CONCURRENT && HasPendingRequests())
        {
            var request = DequeueHighestPriority();
            if (request != null)
            {
                currentConcurrent++;
                _ = LoadAndCallback(request);
            }
        }
    }

    bool HasPendingRequests()
    {
        foreach (var queue in queues.Values)
            if (queue.Count > 0) return true;
        return false;
    }

    LoadRequest DequeueHighestPriority()
    {
        foreach (var queue in queues.Values)
            if (queue.Count > 0) return queue.Dequeue();
        return null;
    }

    async Task LoadAndCallback(LoadRequest request)
    {
        var handle = Addressables.LoadAssetAsync<UnityEngine.Object>(request.Address);
        await handle.Task;
        
        currentConcurrent--;
        
        if (handle.Status == AsyncOperationStatus.Succeeded)
            request.OnComplete?.Invoke(handle.Result);
        else
            Debug.LogError($"[PriorityLoader] Failed: {request.Address}");
        
        ProcessQueue(); // 完成一个，继续处理队列
    }
}
```

---

## 四、加载策略建议

| 策略 | 触发时机 | 适用资源 |
|------|----------|----------|
| 立即加载 | 进入场景前 | 必要资源（地图/角色）|
| 预加载（后台）| 游戏开始时 | 常用音效/特效 |
| 按需加载 | 进入某区域时 | 远端区域资源 |
| 流式加载 | 开放世界移动时 | 地形/植被 |
| 延迟加载 | 空闲时 | 非关键装饰资源 |

**加载屏最佳实践：**
1. 最小展示时间（1.5s）防止闪烁
2. 提示/故事片段让等待不无聊
3. 进度条平滑过渡（不要跳变）
4. 加载完成时淡出（而不是立即消失）
5. 移动端：加载期间降低屏幕亮度省电
