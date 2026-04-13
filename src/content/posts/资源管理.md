---
title: 资源管理
published: 2020-06-05
description: "全面介绍 Unity 游戏资源管理体系：可热更与不可热更资源划分、AssetBundle 打包策略、引用计数与生命周期管理、异步加载队列设计及内存优化实践。"
tags: [游戏开发, Unity, C#, 资源管理, 性能优化]
category: 游戏开发
draft: false
---

## 概述

资源管理是 Unity 游戏工程的核心基础设施，直接影响包体大小、热更效率、运行时内存和加载性能。本文从**资源分类**到**加载架构**，完整梳理一套可落地的资源管理体系。

---

## 一、可热更 vs 不可热更资源

### 资源划分原则

游戏工程中的资源按是否可以在不更新安装包的情况下替换，分为两类：

**可热更资源**（运行时动态加载，可通过 CDN 下发替换）
- 美术资源：贴图、模型、动画、特效、音效
- 配置文件：Excel 导出的 JSON/二进制表
- Lua 脚本（xLua/toLua 方案）
- UI 图集、字体
- 场景（不含内置于 Scene 的 C# 脚本逻辑）

**不可热更资源**（编译进安装包，无法远程替换）
- 需编译的 C# 代码
- SDK 及第三方插件（Android `.aar`、iOS `.framework`）
- 平台相关的 Native 层代码
- Unity 引擎本体

```
安装包（APK/IPA）
├── 不可热更资源（编译产物）
│   ├── libil2cpp.so / Assembly-CSharp.dll
│   ├── SDK 插件
│   └── 平台配置
└── 首包资源（少量必要热更资源，内嵌安装包）
    └── streaming assets / 内置 AB 包
```

### 大包 vs 小包策略

| 方案 | 说明 | 适用平台 |
|------|------|---------|
| 大包 | 安装包内嵌所有资源，首次启动无需下载 | iOS（App Store 审核要求） |
| 小包 | 安装包仅含必要代码，资源启动后热更下载 | Android、PC |

小包方案流程：
```
用户安装（小包，~50MB）
    ↓
启动 → 检查热更版本
    ↓
下载差异资源包（CDN）
    ↓
进入游戏
```

![资源管理架构](/images/posts/资源管理/image-20230905081339998.png)

---

## 二、AssetBundle 打包策略

AssetBundle（AB 包）是 Unity 热更资源的基本单元。打包粒度直接影响热更流量和加载效率。

### 常见打包粒度对比

| 策略 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| 按模块打包 | 一个功能模块（如副本、商城）一个 AB | 热更针对性强 | 包体偏大，冗余较多 |
| 按场景打包 | 每个场景及其依赖单独打包 | 加载场景时按需加载 | 不同场景共用资源冗余 |
| 按角色打包 | 每个角色（模型/动画/特效）独立 AB | 角色热更精确 | AB 数量多，管理复杂 |
| 按资源类型打包 | 所有 UI 图集一个 AB，所有音效一个 AB | 管理简单 | 热更时整包更新 |

### 实践建议

1. **共享依赖单独打包**：多个 AB 都引用的 Shader、公共图集应单独打一个 AB，避免冗余
2. **图集按 UI 界面分组**：同一个界面的 Sprite 打进同一图集，避免打开界面触发多个 AB 加载
3. **场景大资源拆分**：大场景的地形、建筑分开打包，支持流式加载

```csharp
// AssetBundle 构建配置示例（Editor 脚本）
[MenuItem("Build/Build AssetBundles")]
static void BuildABs()
{
    var buildMap = new List<AssetBundleBuild>();
    
    // UI 图集：按界面分组
    buildMap.Add(new AssetBundleBuild
    {
        assetBundleName = "ui/main_panel",
        assetNames = new[] 
        { 
            "Assets/UI/MainPanel/atlas_main.spriteatlas",
            "Assets/UI/MainPanel/MainPanel.prefab"
        }
    });
    
    // 角色：每个角色独立
    foreach (var charDir in Directory.GetDirectories("Assets/Characters"))
    {
        string charName = Path.GetFileName(charDir).ToLower();
        buildMap.Add(new AssetBundleBuild
        {
            assetBundleName = $"characters/{charName}",
            assetNames = AssetDatabase.FindAssets("", new[] { charDir })
                .Select(AssetDatabase.GUIDToAssetPath).ToArray()
        });
    }
    
    BuildPipeline.BuildAssetBundles(
        "Assets/StreamingAssets/AB",
        buildMap.ToArray(),
        BuildAssetBundleOptions.ChunkBasedCompression,
        BuildTarget.Android
    );
}
```

---

## 三、引用计数与生命周期管理

AssetBundle 加载后必须管理其生命周期，防止内存泄漏（未卸载）或 MissingReference（提前卸载）。

### 引用计数模型

```csharp
public class AssetBundleRef
{
    public AssetBundle AB;
    public int RefCount;
    public float LastUseTime;
    
    public void Retain()  => RefCount++;
    public void Release() => RefCount--;
    
    public bool CanUnload => RefCount <= 0 
        && Time.realtimeSinceStartup - LastUseTime > 30f; // 30s 无引用后卸载
}

public class AssetBundleManager
{
    private Dictionary<string, AssetBundleRef> _abCache = new();
    
    public AssetBundle LoadAB(string abName)
    {
        if (_abCache.TryGetValue(abName, out var abRef))
        {
            abRef.Retain();
            abRef.LastUseTime = Time.realtimeSinceStartup;
            return abRef.AB;
        }
        
        // 先加载依赖
        string[] deps = _manifest.GetAllDependencies(abName);
        foreach (var dep in deps) LoadAB(dep);
        
        var ab = AssetBundle.LoadFromFile(GetABPath(abName));
        _abCache[abName] = new AssetBundleRef { AB = ab, RefCount = 1 };
        return ab;
    }
    
    public void ReleaseAB(string abName)
    {
        if (_abCache.TryGetValue(abName, out var abRef))
        {
            abRef.Release();
            // 不立即卸载，等待 GC 周期统一清理
        }
        
        // 同步释放依赖
        foreach (var dep in _manifest.GetAllDependencies(abName))
            ReleaseAB(dep);
    }
    
    // 定期（如切换场景时）清理无引用 AB
    public void UnloadUnusedABs()
    {
        var toRemove = _abCache
            .Where(kv => kv.Value.CanUnload)
            .Select(kv => kv.Key).ToList();
        
        foreach (var name in toRemove)
        {
            _abCache[name].AB.Unload(false); // false：卸载AB但不卸载已加载的Asset
            _abCache.Remove(name);
        }
    }
}
```

### Asset 与 GameObject 生命周期

Unity 资源的三种内存形态：

```
AssetBundle（.ab 文件映射到内存）
    └── LoadAsset<T> → Asset（纹理/Mesh/预制体数据）
            └── Instantiate → GameObject（场景中的实例）
```

卸载策略：
- `ab.Unload(false)`：卸载 AB 但保留已 LoadAsset 出的 Asset（常用）
- `ab.Unload(true)`：卸载 AB 并强制卸载 Asset（危险，场景中的引用会断）
- `Resources.UnloadUnusedAssets()`：在切场景等时机调用，GC 未引用的 Asset

---

## 四、异步加载队列设计

同步加载 AB 会阻塞主线程造成卡顿，生产环境必须使用异步加载。

### 基于协程的异步加载

```csharp
public class AsyncAssetLoader : MonoBehaviour
{
    // 加载请求队列
    private Queue<LoadRequest> _requestQueue = new();
    private bool _isLoading = false;
    
    public struct LoadRequest
    {
        public string ABName;
        public string AssetName;
        public Action<Object> Callback;
        public int Priority;  // 优先级，数字越大越先加载
    }
    
    public void RequestLoad(string abName, string assetName, 
        Action<Object> callback, int priority = 0)
    {
        _requestQueue.Enqueue(new LoadRequest 
        { 
            ABName = abName, 
            AssetName = assetName, 
            Callback = callback,
            Priority = priority
        });
        
        if (!_isLoading)
            StartCoroutine(ProcessQueue());
    }
    
    private IEnumerator ProcessQueue()
    {
        _isLoading = true;
        while (_requestQueue.Count > 0)
        {
            // 按优先级取出请求
            var req = DequeueByPriority();
            yield return StartCoroutine(LoadAssetAsync(req));
        }
        _isLoading = false;
    }
    
    private IEnumerator LoadAssetAsync(LoadRequest req)
    {
        // 异步加载 AB
        var abReq = AssetBundle.LoadFromFileAsync(GetPath(req.ABName));
        yield return abReq;
        
        if (abReq.assetBundle == null)
        {
            Debug.LogError($"Failed to load AB: {req.ABName}");
            req.Callback?.Invoke(null);
            yield break;
        }
        
        // 异步加载 Asset
        var assetReq = abReq.assetBundle.LoadAssetAsync(req.AssetName);
        yield return assetReq;
        
        req.Callback?.Invoke(assetReq.asset);
    }
}
```

### 实用封装（支持 async/await）

```csharp
// 支持 Task 的异步加载封装
public static class AssetLoader
{
    public static async Task<T> LoadAsync<T>(string path) where T : Object
    {
        var tcs = new TaskCompletionSource<T>();
        
        // 解析 AB 名和 Asset 名
        ParsePath(path, out string abName, out string assetName);
        
        AsyncAssetLoader.Instance.RequestLoad(abName, assetName, asset => 
        {
            tcs.SetResult(asset as T);
        });
        
        return await tcs.Task;
    }
}

// 使用示例
async void LoadHero()
{
    var prefab = await AssetLoader.LoadAsync<GameObject>("characters/hero/HeroPrefab");
    Instantiate(prefab, Vector3.zero, Quaternion.identity);
}
```

---

## 五、内存优化实践

### 纹理内存优化

纹理通常是内存大户，优化要点：

1. **使用正确的压缩格式**
   - Android：ETC2（RGB）/ ASTC（含 Alpha）
   - iOS：PVRTC / ASTC
   - 避免使用 RGBA32（未压缩，是 ASTC 的 4~8 倍大小）

2. **合理设置 Mipmap**
   - UI 图集关闭 Mipmap（UI 始终以原始尺寸显示）
   - 3D 场景贴图开启 Mipmap（远景自动降级采样）

3. **图集 Max Size 按需设置**
   - 主界面图集：1024 或 2048
   - 角色细节贴图：512
   - 远景地形：256

```csharp
// Editor 批量设置纹理压缩格式
[MenuItem("Tools/Optimize Textures")]
static void OptimizeTextures()
{
    string[] guids = AssetDatabase.FindAssets("t:Texture2D", new[] {"Assets/UI"});
    foreach (var guid in guids)
    {
        string path = AssetDatabase.GUIDToAssetPath(guid);
        var importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null) continue;
        
        // UI 纹理关闭 Mipmap，使用 ASTC 压缩
        importer.mipmapEnabled = false;
        
        var settings = importer.GetPlatformTextureSettings("Android");
        settings.overridden = true;
        settings.format = TextureImporterFormat.ASTC_6x6;
        importer.SetPlatformTextureSettings(settings);
        
        AssetDatabase.ImportAsset(path);
    }
    AssetDatabase.Refresh();
}
```

### 场景切换时的内存清理

```csharp
// 场景切换管理器
public class SceneTransitionManager
{
    public async Task SwitchScene(string sceneName)
    {
        // 1. 显示 Loading UI
        LoadingPanel.Show();
        
        // 2. 卸载当前场景
        await SceneManager.UnloadSceneAsync(currentScene);
        
        // 3. 清理 AB 引用计数为 0 的包
        ABManager.Instance.UnloadUnusedABs();
        
        // 4. 强制 GC
        GC.Collect();
        await Resources.UnloadUnusedAssets();
        
        // 5. 加载新场景
        await SceneManager.LoadSceneAsync(sceneName, LoadSceneMode.Additive);
        
        LoadingPanel.Hide();
    }
}
```

### Profiler 关注指标

使用 Unity Profiler / Memory Profiler 关注以下指标：

| 指标 | 参考上限 | 说明 |
|------|---------|------|
| Texture Memory | < 200MB | 纹理占用是内存主体 |
| Total Reserved | < 500MB | 中低端 Android 设备基准 |
| GC Alloc/frame | < 1KB | 高频 GC 会造成卡顿 |
| Mono Heap | < 50MB | Lua/C# 托管堆 |

---

## 总结

Unity 资源管理的核心是：**资源分层**（热更/不热更）、**AB 合理分组**（减少冗余，精准热更）、**引用计数保生命周期**（不泄漏不提前卸载）、**异步加载不卡主线程**、**定期清理释放内存**。随着项目规模增大，推荐引入 Addressables 或自研资源管理框架，将 AB 路径、版本管理、差分更新统一处理。
