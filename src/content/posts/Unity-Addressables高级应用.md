---
title: Unity Addressables 高级应用：资源加载与热更深度实践
published: 2026-03-21
description: "深度讲解 Unity Addressables 的高级使用技巧，包括 Group 策略设计、Bundle 分包方案、依赖分析、异步加载性能优化、催更机制实现，以及大型项目中 Addressables 的架构设计和常见陷阱规避。"
tags: [Addressables, 资源管理, 热更新, Unity, 架构设计]
category: 架构设计
draft: false
encryptedKey: henhaoji123
---

## Addressables vs Resources vs AssetBundle

```
三种资源加载方式的演变：

Resources（老方式，不推荐）：
  优点：简单直接，Resources.Load("path")
  缺点：
    所有资源打进安装包
    无法热更
    构建后路径无法修改
    
AssetBundle（底层方式）：
  优点：灵活，可以精确控制
  缺点：
    API 繁琐（需要手动管理依赖、引用计数）
    Bundle 策略需要手动实现
    容易出现内存泄露
    
Addressables（推荐）：
  优点：
    自动依赖管理
    统一的加载/卸载 API
    内置引用计数
    支持远程加载（热更资源）
    可视化依赖分析工具
  缺点：
    有学习成本
    调试相对麻烦
    首次构建较慢
```

---

## 一、Addressables Group 策略

### 1.1 Group 的设计原则

```
Group 的本质：
  一个 Group 对应一个或多个 AssetBundle
  同一 Group 内的资源默认打包在一起
  
Group 划分策略（关键决策）：

策略1：按功能模块划分
  Group: "UI_Common"（通用 UI 资源）
  Group: "Level_1"（第1关所有资源）
  Group: "Level_2"（第2关所有资源）
  Group: "Character_Warrior"（战士角色资源）
  
策略2：按资源类型划分
  Group: "Textures_UI"
  Group: "Audio_BGM"
  Group: "Prefabs_Common"

推荐：功能模块 + 大小控制
  原则：一个 Bundle 大小约 2~5MB（太小：请求数多；太大：更新代价大）
```

### 1.2 Bundle 依赖分析

```
依赖分析工具：
  Window → Asset Management → Addressables → Analyze
  
  分析项：
  "Check Duplicate Bundle Dependencies"：
    找出被多个 Group 依赖的资源（会被重复打包！）
    
  例：
    Level_1 Group 包含 Level1_Boss.prefab
    Level_2 Group 包含 Level2_Boss.prefab
    两个 Boss 都使用 CommonShader.mat
    
    如果 CommonShader.mat 不在单独的 Group 中：
    → 它会被同时打进 Level_1 和 Level_2 的 Bundle（浪费！）
    
  解决：把共享资源放到独立的 "Shared" Group
```

### 1.3 代码中的 Group 控制

```csharp
// 通过代码控制 Addressable Asset Group 设置
#if UNITY_EDITOR
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;

public class AddressablesSetup
{
    [UnityEditor.MenuItem("Tools/Addressables/Setup Groups")]
    static void SetupGroups()
    {
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        
        // 设置 Group 的 Bundle 模式
        // PackTogether：整个 Group 打成一个 Bundle
        // PackSeparately：每个资产单独打一个 Bundle
        // PackTogetherByLabel：按 Label 分组打包
        
        foreach (var group in settings.groups)
        {
            var schema = group.GetSchema<BundledAssetGroupSchema>();
            if (schema == null) continue;
            
            // 根据 Group 名称设置策略
            if (group.name.StartsWith("Level_"))
            {
                schema.BundleMode = BundledAssetGroupSchema.BundlePackingMode.PackTogether;
            }
            else if (group.name == "Characters")
            {
                schema.BundleMode = BundledAssetGroupSchema.BundlePackingMode.PackSeparately;
            }
        }
        
        Debug.Log("Addressables Groups configured!");
    }
}
#endif
```

---

## 二、异步加载的性能优化

### 2.1 预加载与生命周期管理

```csharp
/// <summary>
/// 资源加载管理器：封装 Addressables，提供生命周期管理
/// </summary>
public class AddressablesManager : Singleton<AddressablesManager>
{
    // 已加载资源的句柄缓存（避免重复加载）
    private readonly Dictionary<string, AsyncOperationHandle> _handleCache = new();
    
    // 引用计数（多个系统可能加载同一资源）
    private readonly Dictionary<string, int> _refCounts = new();
    
    /// <summary>
    /// 加载资源（带引用计数）
    /// </summary>
    public async UniTask<T> LoadAsync<T>(string address, CancellationToken ct = default)
        where T : Object
    {
        // 已缓存，直接返回
        if (_handleCache.TryGetValue(address, out var cachedHandle))
        {
            _refCounts[address]++;
            return cachedHandle.Result as T;
        }
        
        // 发起加载
        var handle = Addressables.LoadAssetAsync<T>(address);
        _handleCache[address] = handle;
        _refCounts[address] = 1;
        
        try
        {
            await handle.Task.AsUniTask(cancellationToken: ct);
        }
        catch (Exception e)
        {
            // 加载失败，清理缓存
            _handleCache.Remove(address);
            _refCounts.Remove(address);
            Debug.LogError($"[Addressables] Failed to load {address}: {e.Message}");
            throw;
        }
        
        return handle.Result as T;
    }
    
    /// <summary>
    /// 释放资源（减少引用计数，为 0 时实际释放）
    /// </summary>
    public void Release(string address)
    {
        if (!_refCounts.TryGetValue(address, out int count)) return;
        
        count--;
        if (count <= 0)
        {
            // 引用计数为 0，真正释放
            if (_handleCache.TryGetValue(address, out var handle))
            {
                Addressables.Release(handle);
                _handleCache.Remove(address);
            }
            _refCounts.Remove(address);
        }
        else
        {
            _refCounts[address] = count;
        }
    }
    
    /// <summary>
    /// 预加载一批资源（关卡加载阶段使用）
    /// </summary>
    public async UniTask PreloadAsync(IEnumerable<string> addresses, 
                                       Action<float> progressCallback = null,
                                       CancellationToken ct = default)
    {
        var list = addresses.ToList();
        int total = list.Count;
        int loaded = 0;
        
        // 并行加载所有资源（最大化带宽利用）
        var tasks = list.Select(async address =>
        {
            await LoadAsync<Object>(address, ct);
            loaded++;
            progressCallback?.Invoke((float)loaded / total);
        });
        
        await UniTask.WhenAll(tasks.Select(t => t.AsUniTask(ct)));
    }
}
```

### 2.2 场景加载与卸载

```csharp
/// <summary>
/// 场景管理器：基于 Addressables 的场景切换
/// </summary>
public class SceneLoader : MonoBehaviour
{
    private AsyncOperationHandle<SceneInstance> _currentSceneHandle;
    
    public async UniTask LoadSceneAsync(string sceneAddress, 
                                         LoadSceneMode mode = LoadSceneMode.Single,
                                         CancellationToken ct = default)
    {
        // 显示加载界面
        LoadingUI.Show();
        
        try
        {
            // 卸载上一个场景
            if (_currentSceneHandle.IsValid())
            {
                var unloadHandle = Addressables.UnloadSceneAsync(_currentSceneHandle);
                await unloadHandle.Task.AsUniTask(cancellationToken: ct);
            }
            
            // 加载新场景
            var handle = Addressables.LoadSceneAsync(sceneAddress, mode);
            
            // 显示加载进度
            while (!handle.IsDone)
            {
                LoadingUI.SetProgress(handle.PercentComplete);
                await UniTask.NextFrame(ct);
            }
            
            _currentSceneHandle = handle;
        }
        finally
        {
            LoadingUI.Hide();
        }
    }
}
```

---

## 三、热更新集成

### 3.1 热更检查流程

```csharp
/// <summary>
/// 热更新管理器
/// </summary>
public class HotUpdateManager : MonoBehaviour
{
    [SerializeField] private string _catalogUrl; // 远程 Catalog 地址
    
    public async UniTask<bool> CheckForUpdatesAsync(CancellationToken ct = default)
    {
        Debug.Log("[HotUpdate] Checking for updates...");
        
        try
        {
            // 1. 检查 Catalog 更新（catalog.json 是资源清单）
            var checkHandle = Addressables.CheckForCatalogUpdates(autoReleaseHandle: false);
            var catalogs = await checkHandle.Task.AsUniTask(cancellationToken: ct);
            
            if (catalogs == null || catalogs.Count == 0)
            {
                Debug.Log("[HotUpdate] No updates available");
                Addressables.Release(checkHandle);
                return false;
            }
            
            Debug.Log($"[HotUpdate] Found {catalogs.Count} catalog updates");
            
            // 2. 更新 Catalog
            var updateHandle = Addressables.UpdateCatalogs(catalogs);
            await updateHandle.Task.AsUniTask(cancellationToken: ct);
            Addressables.Release(updateHandle);
            Addressables.Release(checkHandle);
            
            return true;
        }
        catch (Exception e)
        {
            Debug.LogError($"[HotUpdate] Check failed: {e.Message}");
            return false; // 检查失败不阻止游戏启动
        }
    }
    
    public async UniTask DownloadUpdatesAsync(
        IList<string> addresses,
        Action<float> progressCallback,
        CancellationToken ct = default)
    {
        // 1. 计算需要下载的大小
        var sizeHandle = Addressables.GetDownloadSizeAsync(addresses.Cast<object>());
        long totalBytes = await sizeHandle.Task.AsUniTask(cancellationToken: ct);
        Addressables.Release(sizeHandle);
        
        if (totalBytes <= 0)
        {
            Debug.Log("[HotUpdate] Nothing to download");
            return;
        }
        
        Debug.Log($"[HotUpdate] Downloading {totalBytes / 1024 / 1024f:F1} MB...");
        
        // 2. 下载
        var downloadHandle = Addressables.DownloadDependenciesAsync(
            addresses.Cast<object>(), 
            Addressables.MergeMode.Union
        );
        
        while (!downloadHandle.IsDone)
        {
            float progress = downloadHandle.PercentComplete;
            progressCallback?.Invoke(progress);
            await UniTask.Delay(100, cancellationToken: ct); // 每 100ms 报告一次进度
        }
        
        if (downloadHandle.Status == AsyncOperationStatus.Failed)
        {
            Addressables.Release(downloadHandle);
            throw new Exception($"Download failed: {downloadHandle.OperationException?.Message}");
        }
        
        Addressables.Release(downloadHandle);
        Debug.Log("[HotUpdate] Download complete!");
    }
}
```

### 3.2 完整启动流程

```csharp
public class GameBootstrap : MonoBehaviour
{
    [SerializeField] private HotUpdateManager _hotUpdateManager;
    [SerializeField] private DownloadProgressUI _downloadUI;
    
    async void Start()
    {
        // 完整的游戏启动流程
        await Boot(this.destroyCancellationToken);
    }
    
    private async UniTask Boot(CancellationToken ct)
    {
        // 1. 初始化 Addressables
        var initHandle = Addressables.InitializeAsync();
        await initHandle.Task.AsUniTask(cancellationToken: ct);
        
        // 2. 检查热更（不阻塞太久）
        bool hasUpdates = false;
        try
        {
            using var timeoutCts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);
            hasUpdates = await _hotUpdateManager.CheckForUpdatesAsync(linked.Token);
        }
        catch (OperationCanceledException)
        {
            Debug.LogWarning("[Boot] Update check timed out, proceeding with cached resources");
        }
        
        // 3. 如果有更新，询问/自动下载
        if (hasUpdates)
        {
            _downloadUI.Show();
            
            var allLabels = new[] { "Remote_Critical" }; // 关键资源 Label
            await _hotUpdateManager.DownloadUpdatesAsync(
                allLabels,
                progress => _downloadUI.SetProgress(progress),
                ct
            );
            
            _downloadUI.Hide();
        }
        
        // 4. 加载主场景
        await SceneLoader.Instance.LoadSceneAsync("MainMenu", cancellationToken: ct);
    }
}
```

---

## 四、常见陷阱与解决方案

### 4.1 循环依赖陷阱

```
问题：
  GroupA 中的 Prefab 引用了 GroupB 中的 Material
  GroupB 中的 Prefab 引用了 GroupA 中的 Texture
  
  加载 GroupA → 需要 GroupB → GroupB 又需要 GroupA
  → 形成循环依赖，可能导致加载死锁或资源重复
  
解决：
  使用 Addressables Analyze 工具检测循环依赖
  提取公共依赖到 "Shared" Group
  严格控制 Group 之间的依赖方向
```

### 4.2 内存泄露问题

```csharp
// ❌ 忘记释放 Handle
async void LoadAndForget(string address)
{
    var handle = Addressables.LoadAssetAsync<GameObject>(address);
    var prefab = await handle.Task;
    Instantiate(prefab);
    // 忘记 Addressables.Release(handle) → 内存泄露！
}

// ✅ 正确释放
async UniTask LoadAndInstantiate(string address)
{
    var handle = Addressables.LoadAssetAsync<GameObject>(address);
    
    try
    {
        var prefab = await handle.Task.AsUniTask();
        var instance = Instantiate(prefab);
        
        // 注意：实例化后，可以释放 handle（prefab 数据已被 instance 引用）
        // 但如果还需要从 prefab 再次实例化，就不要释放
        Addressables.Release(handle);
        
        return instance;
    }
    catch
    {
        Addressables.Release(handle); // 失败时也要释放
        throw;
    }
}
```

---

## 总结

Addressables 在大型项目中的最佳实践：

| 方面 | 建议 |
|------|------|
| Group 划分 | 按功能模块，控制每个 Bundle 2~5MB |
| 共享资源 | 单独 Group，避免重复打包 |
| 依赖分析 | 定期运行 Analyze，发现并修复问题 |
| 加载管理 | 封装 Addressables，统一管理引用计数 |
| 热更流程 | 启动时检查+下载，进入游戏前确保资源最新 |
| 内存管理 | 明确每个 Handle 的生命周期，严格释放 |

---

*本文是「游戏客户端开发进阶路线」系列的资源管理篇。*
