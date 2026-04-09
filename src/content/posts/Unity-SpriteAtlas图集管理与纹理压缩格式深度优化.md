---
title: Unity SpriteAtlas图集管理与纹理压缩格式深度优化：从移动端适配到显存精准管控
published: 2026-04-09
description: 深度解析Unity SpriteAtlas图集系统的完整工程实践，涵盖SpriteAtlas V2配置与图集打包策略、ASTC/ETC2/PVRTC纹理压缩格式选型（移动端适配矩阵）、运行时图集引用计数与按需加载、Addressables集成的动态图集加载、纹理内存精准管控（Texture Streaming与Mipmap策略）、图集合并与DrawCall优化原理，以及一套完整的移动端纹理质量分级方案。
tags: [Unity, SpriteAtlas, 纹理压缩, ASTC, ETC2, 内存优化, 游戏开发, 移动端]
category: 性能优化
draft: false
---

## 一、SpriteAtlas 系统架构与核心原理

### 1.1 图集的本质：降低 DrawCall

Sprite 图集（SpriteAtlas）的核心价值在于**将多张小纹理合并为一张大纹理**，使原本因纹理切换而产生的多个 DrawCall 合并为一个。

```
无图集（多DrawCall）：
Sprite A（纹理1）→ DrawCall 1
Sprite B（纹理2）→ DrawCall 2
Sprite C（纹理3）→ DrawCall 3

有图集（合并DrawCall）：
Sprite A + B + C（同一图集纹理）→ DrawCall 1（合并！）
```

### 1.2 SpriteAtlas V2 配置详解

```csharp
// SpriteAtlas Import Settings 关键参数说明（通过代码配置）
using UnityEditor;
using UnityEditor.U2D;
using UnityEngine.U2D;
using UnityEngine;

#if UNITY_EDITOR
/// <summary>
/// SpriteAtlas自动配置工具
/// 按平台输出最优压缩设置
/// </summary>
public static class SpriteAtlasConfigurator
{
    /// <summary>
    /// 配置UI图集（界面元素，要求清晰）
    /// </summary>
    public static void ConfigureUIAtlas(SpriteAtlas atlas)
    {
        var settings = new SpriteAtlasPackingSettings
        {
            blockOffset   = 1,        // 边距1px，防止纹理出血
            enableRotation = false,   // UI图集关闭旋转（防止显示错误）
            enableTightPacking = false, // 关闭紧密打包（提高缓存命中）
            padding       = 4         // 图片间距4px，防止相邻像素渗色
        };
        atlas.SetPackingSettings(settings);
        
        var textureSettings = new SpriteAtlasTextureSettings
        {
            readable          = false, // 不需要CPU可读
            generateMipMaps   = false, // UI通常不需要Mipmap（避免内存浪费）
            sRGB              = true,  // UI纹理使用sRGB空间
            filterMode        = FilterMode.Bilinear,
            anisoLevel        = 1
        };
        atlas.SetTextureSettings(textureSettings);
        
        // Android 平台配置
        ConfigurePlatformSettings(atlas, "Android",
            TextureImporterFormat.ASTC_6x6, // ASTC 6x6：高压缩率，支持透明
            maxTextureSize: 2048,
            quality: 50
        );
        
        // iOS 平台配置
        ConfigurePlatformSettings(atlas, "iPhone",
            TextureImporterFormat.ASTC_6x6, // iOS同样支持ASTC
            maxTextureSize: 2048,
            quality: 50
        );
        
        // PC/Editor 配置
        ConfigurePlatformSettings(atlas, "Standalone",
            TextureImporterFormat.DXT5,    // PC使用DXT5（不透明DXT1）
            maxTextureSize: 4096,
            quality: 100
        );
    }
    
    /// <summary>
    /// 配置游戏世界Sprite图集（角色、特效）
    /// </summary>
    public static void ConfigureGameSpriteAtlas(SpriteAtlas atlas, bool hasAlpha)
    {
        var settings = new SpriteAtlasPackingSettings
        {
            blockOffset        = 1,
            enableRotation     = true,  // 游戏场景可开启旋转节省空间
            enableTightPacking = true,  // 开启紧密打包（最大化利用空间）
            padding            = 2
        };
        atlas.SetPackingSettings(settings);
        
        var textureSettings = new SpriteAtlasTextureSettings
        {
            generateMipMaps = true, // 游戏世界Sprite需要Mipmap（远近缩放）
            sRGB            = true,
            filterMode      = FilterMode.Bilinear
        };
        atlas.SetTextureSettings(textureSettings);
        
        // 根据是否有透明度选择格式
        var androidFormat = hasAlpha
            ? TextureImporterFormat.ASTC_4x4  // 有透明：ASTC 4x4（质量更高）
            : TextureImporterFormat.ETC2_RGB4; // 无透明：ETC2 RGB（更小）
        
        ConfigurePlatformSettings(atlas, "Android", androidFormat, 2048, 75);
        ConfigurePlatformSettings(atlas, "iPhone",
            hasAlpha ? TextureImporterFormat.ASTC_4x4 : TextureImporterFormat.PVRTC_RGB4,
            2048, 75
        );
    }
    
    private static void ConfigurePlatformSettings(
        SpriteAtlas atlas, 
        string platform, 
        TextureImporterFormat format,
        int maxTextureSize,
        int quality)
    {
        var platformSettings = atlas.GetPlatformSettings(platform);
        platformSettings.overridden     = true;
        platformSettings.maxTextureSize = maxTextureSize;
        platformSettings.format         = format;
        platformSettings.compressionQuality = quality;
        atlas.SetPlatformSettings(platformSettings);
    }
}
#endif
```

---

## 二、纹理压缩格式深度解析

### 2.1 移动端压缩格式对比矩阵

| 格式 | 压缩率 | 质量 | 透明通道 | 支持平台 | 推荐场景 |
|------|-------|------|---------|---------|--------|
| **ASTC 4x4** | 8:1 | ★★★★★ | ✅ | ARM Mali/Adreno/Apple | 高质量角色、UI精细元素 |
| **ASTC 6x6** | 18:1 | ★★★★ | ✅ | 同上 | UI通用，平衡质量与体积 |
| **ASTC 8x8** | 32:1 | ★★★ | ✅ | 同上 | 背景、贴图细节要求低 |
| **ETC2 RGBA8** | 4:1 | ★★★ | ✅ | OpenGL ES 3.0+ | Android兼容性优先 |
| **ETC2 RGB4** | 6:1 | ★★★★ | ❌ | OpenGL ES 3.0+ | 不透明Android纹理 |
| **PVRTC RGB4** | 8:1 | ★★★ | ❌ | PowerVR (老款iOS) | 已逐步淘汰 |
| **DXT1** | 6:1 | ★★★★ | ❌ | PC/Xbox | PC不透明纹理 |
| **DXT5** | 4:1 | ★★★★ | ✅ | PC/Xbox | PC透明纹理 |
| **BC7** | 4:1 | ★★★★★ | ✅ | PC DX11+ | PC高质量纹理 |

### 2.2 平台适配策略代码

```csharp
using UnityEngine;
using UnityEditor;

/// <summary>
/// 纹理导入设置自动化工具
/// 根据纹理类型、目标平台自动选择最优压缩格式
/// </summary>
public class TextureImportOptimizer : AssetPostprocessor
{
    // ─── 纹理规范（按命名约定自动分类） ────────────────────────
    // _UI    → UI元素，无Mipmap，ASTC 6x6
    // _Char  → 角色纹理，有Mipmap，ASTC 4x4  
    // _BG    → 背景，有Mipmap，ASTC 8x8
    // _FX    → 特效，无Mipmap，ASTC 6x6
    // _N     → 法线贴图，专用压缩
    
    void OnPreprocessTexture()
    {
        var importer = assetImporter as TextureImporter;
        if (importer == null) return;
        
        string path = assetPath.ToLower();
        
        // 只处理指定目录
        if (!path.Contains("/textures/") && !path.Contains("/sprites/")) return;
        
        // 根据命名约定配置
        if (path.Contains("_ui") || path.Contains("/ui/"))
            ConfigureUITexture(importer);
        else if (path.Contains("_n.") || path.Contains("_normal"))
            ConfigureNormalMap(importer);
        else if (path.Contains("_bg") || path.Contains("/background/"))
            ConfigureBackgroundTexture(importer);
        else
            ConfigureDefaultTexture(importer);
    }
    
    private void ConfigureUITexture(TextureImporter importer)
    {
        importer.textureType          = TextureImporterType.Sprite;
        importer.mipmapEnabled        = false;  // UI无Mipmap
        importer.filterMode           = FilterMode.Bilinear;
        importer.maxTextureSize       = 2048;
        
        SetPlatformOverride(importer, "Android", 
            TextureImporterFormat.ASTC_6x6, 2048);
        SetPlatformOverride(importer, "iPhone",  
            TextureImporterFormat.ASTC_6x6, 2048);
        SetPlatformOverride(importer, "Standalone", 
            TextureImporterFormat.DXT5, 4096);
    }
    
    private void ConfigureNormalMap(TextureImporter importer)
    {
        importer.textureType    = TextureImporterType.NormalMap;
        importer.mipmapEnabled  = true;
        
        // 法线贴图使用专用压缩（保留XY精度）
        SetPlatformOverride(importer, "Android",    TextureImporterFormat.ASTC_4x4, 1024);
        SetPlatformOverride(importer, "iPhone",     TextureImporterFormat.ASTC_4x4, 1024);
        SetPlatformOverride(importer, "Standalone", TextureImporterFormat.BC5,      2048);
    }
    
    private void ConfigureBackgroundTexture(TextureImporter importer)
    {
        importer.mipmapEnabled  = true;
        importer.filterMode     = FilterMode.Trilinear;
        importer.anisoLevel     = 4;
        
        // 背景图尺寸通常较大，使用更激进压缩
        SetPlatformOverride(importer, "Android",    TextureImporterFormat.ASTC_8x8, 2048);
        SetPlatformOverride(importer, "iPhone",     TextureImporterFormat.ASTC_8x8, 2048);
        SetPlatformOverride(importer, "Standalone", TextureImporterFormat.DXT1,     4096);
    }
    
    private void ConfigureDefaultTexture(TextureImporter importer)
    {
        importer.mipmapEnabled = true;
        
        SetPlatformOverride(importer, "Android",    TextureImporterFormat.ASTC_6x6, 2048);
        SetPlatformOverride(importer, "iPhone",     TextureImporterFormat.ASTC_6x6, 2048);
        SetPlatformOverride(importer, "Standalone", TextureImporterFormat.DXT5,     4096);
    }
    
    private static void SetPlatformOverride(
        TextureImporter importer, 
        string platform, 
        TextureImporterFormat format, 
        int maxSize)
    {
        var settings = importer.GetPlatformTextureSettings(platform);
        settings.overridden     = true;
        settings.maxTextureSize = maxSize;
        settings.format         = format;
        settings.compressionQuality = 100;
        importer.SetPlatformTextureSettings(settings);
    }
}
```

---

## 三、运行时图集管理：引用计数与按需加载

### 3.1 基于 Addressables 的动态图集加载

```csharp
using UnityEngine;
using UnityEngine.U2D;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
using System.Collections.Generic;
using System.Threading.Tasks;

/// <summary>
/// 动态图集加载管理器
/// 配合 Addressables 实现按需加载、引用计数自动释放
/// </summary>
public class SpriteAtlasManager : MonoBehaviour
{
    private static SpriteAtlasManager instance;
    public static SpriteAtlasManager Instance => instance;
    
    // 已加载图集的缓存（图集名 → 图集对象）
    private readonly Dictionary<string, SpriteAtlas> atlasCache  = new();
    
    // 引用计数（图集名 → 引用次数）
    private readonly Dictionary<string, int> referenceCount       = new();
    
    // 加载操作句柄（用于正确释放）
    private readonly Dictionary<string, AsyncOperationHandle<SpriteAtlas>> handles = new();
    
    // 正在加载中的请求（防止重复加载）
    private readonly Dictionary<string, Task<SpriteAtlas>> pendingLoads = new();
    
    void Awake()
    {
        if (instance != null && instance != this) { Destroy(gameObject); return; }
        instance = this;
        DontDestroyOnLoad(gameObject);
        
        // 注册Sprite图集请求回调
        SpriteAtlasManager.atlasRequested += OnAtlasRequested;
    }
    
    void OnDestroy()
    {
        SpriteAtlasManager.atlasRequested -= OnAtlasRequested;
    }
    
    // ─── Sprite图集请求（Unity内部回调） ──────────────────────
    // 当某个Sprite所在图集未加载时，Unity会触发此回调
    private void OnAtlasRequested(string atlasTag, System.Action<SpriteAtlas> callback)
    {
        Debug.Log($"[AtlasManager] 图集请求：{atlasTag}");
        
        // 如果已缓存，立即返回
        if (atlasCache.TryGetValue(atlasTag, out var cachedAtlas))
        {
            callback?.Invoke(cachedAtlas);
            return;
        }
        
        // 异步加载
        LoadAtlasAsync(atlasTag).ContinueWith(task =>
        {
            if (task.IsCompletedSuccessfully)
                callback?.Invoke(task.Result);
            else
                Debug.LogError($"[AtlasManager] 图集加载失败：{atlasTag}");
        }, TaskScheduler.FromCurrentSynchronizationContext());
    }
    
    /// <summary>
    /// 主动预加载图集（在场景加载时预热）
    /// </summary>
    public async Task<SpriteAtlas> PreloadAtlasAsync(string atlasAddressableKey)
    {
        return await LoadAtlasAsync(atlasAddressableKey);
    }
    
    private async Task<SpriteAtlas> LoadAtlasAsync(string key)
    {
        // 如果已缓存，增加引用计数并返回
        if (atlasCache.TryGetValue(key, out var cached))
        {
            referenceCount[key]++;
            return cached;
        }
        
        // 如果正在加载，等待同一个Task
        if (pendingLoads.TryGetValue(key, out var pending))
            return await pending;
        
        // 发起新的加载
        var loadTask = LoadFromAddressables(key);
        pendingLoads[key] = loadTask;
        
        var result = await loadTask;
        pendingLoads.Remove(key);
        return result;
    }
    
    private async Task<SpriteAtlas> LoadFromAddressables(string key)
    {
        var handle = Addressables.LoadAssetAsync<SpriteAtlas>(key);
        handles[key] = handle;
        
        await handle.Task;
        
        if (handle.Status != AsyncOperationStatus.Succeeded)
        {
            handles.Remove(key);
            throw new System.Exception($"Failed to load atlas: {key}");
        }
        
        var atlas        = handle.Result;
        atlasCache[key]  = atlas;
        referenceCount[key] = 1;
        
        Debug.Log($"[AtlasManager] 图集加载成功：{key} | 尺寸：{atlas.tag}");
        return atlas;
    }
    
    /// <summary>
    /// 释放图集引用（引用计数归零时自动卸载）
    /// </summary>
    public void ReleaseAtlas(string key)
    {
        if (!referenceCount.ContainsKey(key)) return;
        
        referenceCount[key]--;
        if (referenceCount[key] > 0) return;
        
        // 引用计数归零，卸载图集
        if (handles.TryGetValue(key, out var handle))
        {
            Addressables.Release(handle);
            handles.Remove(key);
        }
        
        atlasCache.Remove(key);
        referenceCount.Remove(key);
        
        Debug.Log($"[AtlasManager] 图集已卸载：{key}");
    }
    
    /// <summary>
    /// 获取已加载图集中的Sprite
    /// </summary>
    public Sprite GetSprite(string atlasKey, string spriteName)
    {
        if (!atlasCache.TryGetValue(atlasKey, out var atlas))
        {
            Debug.LogWarning($"[AtlasManager] 图集未加载：{atlasKey}");
            return null;
        }
        return atlas.GetSprite(spriteName);
    }
    
    public int GetAtlasCount() => atlasCache.Count;
    public int GetReferenceCount(string key) => referenceCount.TryGetValue(key, out int count) ? count : 0;
}
```

### 3.2 UI 图片组件的图集感知封装

```csharp
using UnityEngine;
using UnityEngine.UI;
using System.Threading.Tasks;

/// <summary>
/// 图集感知的Image组件封装
/// 自动管理图集加载/引用计数，使用结束后自动释放
/// </summary>
[RequireComponent(typeof(Image))]
public class AtlasAwareImage : MonoBehaviour
{
    [SerializeField] private string atlasKey;    // Addressables中的图集Key
    [SerializeField] private string spriteName;  // 图集内的Sprite名称
    
    private Image   imageComponent;
    private string  loadedAtlasKey;
    private bool    isLoaded;
    
    void Awake()
    {
        imageComponent = GetComponent<Image>();
    }
    
    async void Start()
    {
        if (!string.IsNullOrEmpty(atlasKey) && !string.IsNullOrEmpty(spriteName))
            await LoadSpriteAsync(atlasKey, spriteName);
    }
    
    void OnDestroy()
    {
        ReleaseCurrentAtlas();
    }
    
    /// <summary>
    /// 异步设置Sprite（自动管理图集生命周期）
    /// </summary>
    public async Task LoadSpriteAsync(string atlas, string sprite)
    {
        // 释放旧图集引用
        ReleaseCurrentAtlas();
        
        // 预加载新图集
        await SpriteAtlasManager.Instance.PreloadAtlasAsync(atlas);
        
        // 获取Sprite并设置
        var sp = SpriteAtlasManager.Instance.GetSprite(atlas, sprite);
        if (sp != null)
        {
            imageComponent.sprite = sp;
            imageComponent.enabled = true;
        }
        else
        {
            Debug.LogWarning($"[AtlasImage] Sprite未找到：{atlas}/{sprite}");
        }
        
        loadedAtlasKey = atlas;
        isLoaded       = true;
    }
    
    private void ReleaseCurrentAtlas()
    {
        if (!isLoaded || string.IsNullOrEmpty(loadedAtlasKey)) return;
        SpriteAtlasManager.Instance.ReleaseAtlas(loadedAtlasKey);
        loadedAtlasKey = null;
        isLoaded       = false;
    }
}
```

---

## 四、纹理内存管控

### 4.1 Texture Streaming（流式纹理加载）

```csharp
using UnityEngine;

/// <summary>
/// 纹理流式加载配置管理器
/// 根据相机距离动态调整Mipmap加载级别，节省显存
/// </summary>
public class TextureStreamingManager : MonoBehaviour
{
    [Header("流式加载配置")]
    [SerializeField] private bool  enableStreaming      = true;
    [SerializeField] private float memoryBudgetMB       = 512f; // 纹理流式加载显存预算
    [SerializeField] private int   maxMipReduction      = 3;    // 最大Mip级别降低
    [SerializeField] private float discardLevelBias     = 0f;   // 正值=更激进卸载
    
    void Awake()
    {
        ConfigureTextureStreaming();
    }
    
    private void ConfigureTextureStreaming()
    {
        // 全局开关
        QualitySettings.streamingMipmapsActive      = enableStreaming;
        QualitySettings.streamingMipmapsMemoryBudget = memoryBudgetMB;
        QualitySettings.streamingMipmapsMaxLevelReduction = maxMipReduction;
        QualitySettings.streamingMipmapsRenderersPerFrame = 512; // 每帧更新的渲染器数量
        
        // 额外控制
        Texture.streamingMipmapUploadThresholdSize   = 32768; // 超过32KB才流式加载
    }
    
    void Update()
    {
        // 实时监控纹理流式加载状态
        if (Time.frameCount % 300 == 0) // 每5秒打印一次
            LogStreamingStats();
    }
    
    private void LogStreamingStats()
    {
        Debug.Log(
            $"[TextureStream] 所需显存: {Texture.desiredTextureMemory / 1024 / 1024:F1}MB" +
            $" | 当前加载: {Texture.currentTextureMemory / 1024 / 1024:F1}MB" +
            $" | 目标显存: {Texture.targetTextureMemory / 1024 / 1024:F1}MB" +
            $" | 预算: {Texture.streamingMipmapUploadThresholdSize}B"
        );
    }
}
```

### 4.2 纹理内存统计与泄漏检测

```csharp
using UnityEngine;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// 运行时纹理内存占用统计工具
/// 帮助发现纹理泄漏和超规纹理
/// </summary>
public class TextureMemoryProfiler : MonoBehaviour
{
    [System.Serializable]
    public class TextureInfo
    {
        public string name;
        public int    width, height;
        public int    memoryBytes;
        public string format;
        public bool   hasMipmap;
        public bool   isStreaming;
    }
    
    private List<TextureInfo> textureReport = new();
    
    [ContextMenu("生成纹理内存报告")]
    public void GenerateReport()
    {
        textureReport.Clear();
        var textures = Resources.FindObjectsOfTypeAll<Texture2D>();
        long totalBytes = 0;
        
        foreach (var tex in textures)
        {
            // 跳过编辑器内置纹理
            if (tex.hideFlags != HideFlags.None) continue;
            
            int memBytes = UnityEngine.Profiling.Profiler.GetRuntimeMemorySizeLong(tex) > 0
                ? (int)UnityEngine.Profiling.Profiler.GetRuntimeMemorySizeLong(tex)
                : EstimateTextureSize(tex);
            
            totalBytes += memBytes;
            
            textureReport.Add(new TextureInfo
            {
                name       = tex.name,
                width      = tex.width,
                height     = tex.height,
                memoryBytes = memBytes,
                format     = tex.format.ToString(),
                hasMipmap  = tex.mipmapCount > 1,
                isStreaming = tex.streamingMipmaps
            });
        }
        
        // 按内存从大到小排序
        textureReport = textureReport.OrderByDescending(t => t.memoryBytes).ToList();
        
        // 打印 Top 20
        Debug.Log($"=== 纹理内存报告 ===  总计: {totalBytes / 1024 / 1024:F1} MB ===");
        for (int i = 0; i < Mathf.Min(20, textureReport.Count); i++)
        {
            var t = textureReport[i];
            Debug.Log(
                $"[{i+1:D2}] {t.name.PadRight(40)} " +
                $"{t.width}x{t.height} " +
                $"{t.format.PadRight(15)} " +
                $"{t.memoryBytes / 1024:F0}KB " +
                $"{(t.hasMipmap ? "Mip" : "---")} " +
                $"{(t.isStreaming ? "Stream" : "------")}"
            );
        }
        
        // 警告：超规纹理（超过2048x2048）
        var oversized = textureReport.Where(t => t.width > 2048 || t.height > 2048).ToList();
        if (oversized.Count > 0)
        {
            Debug.LogWarning($"[TextureProfiler] 发现 {oversized.Count} 张超规纹理（>2048）：");
            foreach (var t in oversized)
                Debug.LogWarning($"  ⚠️ {t.name}: {t.width}x{t.height}");
        }
    }
    
    private int EstimateTextureSize(Texture2D tex)
    {
        int pixels = tex.width * tex.height;
        float bpp = tex.format switch
        {
            TextureFormat.ASTC_4x4   => 8f,
            TextureFormat.ASTC_6x6   => 3.56f,
            TextureFormat.ASTC_8x8   => 2f,
            TextureFormat.ETC2_RGB   => 4f,
            TextureFormat.ETC2_RGBA8 => 8f,
            TextureFormat.DXT1       => 4f,
            TextureFormat.DXT5       => 8f,
            TextureFormat.RGBA32     => 32f,
            TextureFormat.RGB24      => 24f,
            _                        => 32f
        };
        
        int baseSize = (int)(pixels * bpp / 8);
        return tex.mipmapCount > 1 ? (int)(baseSize * 1.33f) : baseSize; // Mipmap增加1/3
    }
}
```

---

## 五、图集打包策略最佳实践

### 5.1 图集分包设计原则

```
图集分包策略（按使用场景）：

Atlas_Common      常驻图集（所有界面通用元素：按钮、边框、图标）
Atlas_Main_UI     主界面专属图集（主城、背包、商店）
Atlas_Battle_UI   战斗界面图集（技能图标、血条、伤害数字）
Atlas_Char_XXX    角色头像图集（按角色分组，按需加载）
Atlas_FX_XXX      特效图集（按技能/场景分组）
Atlas_Loading     Loading界面图集（优先加载）
```

```csharp
/// <summary>
/// 图集加载预算管理 —— 防止一次性加载过多图集导致内存峰值
/// </summary>
public class AtlasBudgetManager : MonoBehaviour
{
    [Header("内存预算")]
    [SerializeField] private float maxAtlasMemoryMB = 200f; // 图集最大总内存
    
    // 各图集的优先级（高优先级图集不会被自动卸载）
    private static readonly Dictionary<string, int> AtlasPriority = new()
    {
        { "Atlas_Common",   100 }, // 永久常驻
        { "Atlas_Loading",  90  }, // 加载期间常驻
        { "Atlas_Main_UI",  50  }, // 主界面时常驻
        { "Atlas_Battle_UI",60  }, // 战斗时常驻
    };
    
    private Dictionary<string, float> atlasLastAccessTime = new();
    
    /// <summary>
    /// 检查并清理低优先级图集
    /// </summary>
    public void TrimAtlasCache(SpriteAtlasManager manager)
    {
        // 收集当前内存用量
        long currentMemory = Resources.FindObjectsOfTypeAll<SpriteAtlas>()
            .Sum(a => (long)UnityEngine.Profiling.Profiler.GetRuntimeMemorySizeLong(a));
        
        float currentMB = currentMemory / 1024f / 1024f;
        if (currentMB <= maxAtlasMemoryMB) return;
        
        Debug.Log($"[AtlasBudget] 图集内存 {currentMB:F1}MB 超出预算 {maxAtlasMemoryMB}MB，开始清理");
        
        // 找出最久未访问且优先级最低的图集
        var candidates = atlasLastAccessTime
            .OrderBy(kvp => AtlasPriority.GetValueOrDefault(kvp.Key, 0))
            .ThenBy(kvp => kvp.Value) // 按最后访问时间升序
            .Take(3);
        
        foreach (var (key, _) in candidates)
        {
            if (manager.GetReferenceCount(key) == 0)
            {
                manager.ReleaseAtlas(key);
                atlasLastAccessTime.Remove(key);
                Debug.Log($"[AtlasBudget] 已清理图集：{key}");
            }
        }
    }
    
    public void RecordAccess(string atlasKey)
    {
        atlasLastAccessTime[atlasKey] = Time.realtimeSinceStartup;
    }
}
```

---

## 六、Editor 工具：图集质量检查

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine.U2D;
using System.IO;

/// <summary>
/// 图集质量检查工具（Editor菜单）
/// </summary>
public static class AtlasQualityChecker
{
    [MenuItem("Tools/图集质量检查")]
    public static void CheckAllAtlases()
    {
        string[] guids = AssetDatabase.FindAssets("t:SpriteAtlas");
        int issueCount = 0;
        
        foreach (string guid in guids)
        {
            string path  = AssetDatabase.GUIDToAssetPath(guid);
            var    atlas = AssetDatabase.LoadAssetAtPath<SpriteAtlas>(path);
            if (atlas == null) continue;
            
            issueCount += CheckAtlas(atlas, path);
        }
        
        Debug.Log($"=== 图集检查完成，发现 {issueCount} 个问题 ===");
    }
    
    private static int CheckAtlas(SpriteAtlas atlas, string path)
    {
        int issues = 0;
        
        // 检查1：图集尺寸
        var texSetting = atlas.GetTextureSettings();
        if (!texSetting.generateMipMaps && path.Contains("game"))
        {
            Debug.LogWarning($"[AtlasCheck] {path}: 游戏场景图集建议开启Mipmap");
            issues++;
        }
        
        // 检查2：Android是否配置了ASTC
        var androidSetting = atlas.GetPlatformSettings("Android");
        if (!androidSetting.overridden)
        {
            Debug.LogWarning($"[AtlasCheck] {path}: 未配置Android平台压缩格式，将使用默认格式（可能浪费内存）");
            issues++;
        }
        else if (androidSetting.format != TextureImporterFormat.ASTC_4x4 
              && androidSetting.format != TextureImporterFormat.ASTC_6x6
              && androidSetting.format != TextureImporterFormat.ASTC_8x8
              && androidSetting.format != TextureImporterFormat.ETC2_RGBA8)
        {
            Debug.LogWarning($"[AtlasCheck] {path}: Android使用非推荐格式 {androidSetting.format}");
            issues++;
        }
        
        // 检查3：图集尺寸是否超过2048
        if (androidSetting.maxTextureSize > 2048)
        {
            Debug.LogWarning($"[AtlasCheck] {path}: 图集最大尺寸 {androidSetting.maxTextureSize} 超过2048，可能影响兼容性");
            issues++;
        }
        
        return issues;
    }
}
#endif
```

---

## 七、总结与优化清单

| 优化项 | 原则 |
|-------|------|
| **图集分组** | 按界面/场景分组，同屏同时显示的Sprite放同一图集 |
| **压缩格式** | Android/iOS 优先 ASTC，PC 用 DXT；无透明通道选更小格式 |
| **图集尺寸** | 移动端单张图集不超过 2048x2048（部分老机型限制） |
| **Mipmap** | UI 图集关闭 Mipmap；世界空间 Sprite 开启 |
| **引用计数** | 按需加载 + 引用计数释放，防止图集常驻内存 |
| **流式加载** | 大尺寸世界纹理开启 Texture Streaming |
| **DrawCall** | 同图集的 Sprite 在同一 Canvas/SortingLayer 才能合批 |
| **监控工具** | 定期运行纹理内存报告，发现超规纹理 |

掌握 SpriteAtlas 与纹理压缩的完整工程体系，是移动端游戏客户端工程师实现"高画质 + 低内存"双重目标的关键所在。合理的图集规划能将 DrawCall 从数百降至数十，纹理压缩格式的精细选型则可将显存占用降低 4~8 倍。
