---
title: 游戏纹理流式加载与Mipmap动态管理：移动端显存优化完全指南
published: 2026-04-15
description: 深入讲解Unity纹理流式加载（Texture Streaming）系统原理与实践，涵盖Mipmap层级动态控制、按需加载策略、移动端ASTC/ETC2压缩格式选型、运行时纹理内存预算管理、以及基于相机距离的纹理LOD系统实战，帮助移动端游戏将GPU显存占用降低40%以上。
tags: [Unity, 纹理, Mipmap, Texture Streaming, 内存优化, 移动端优化]
category: 性能优化
draft: false
---

# 游戏纹理流式加载与Mipmap动态管理：移动端显存优化完全指南

## 引言：纹理内存的挑战

纹理资源通常占据移动端游戏GPU显存的60-80%。一个中等规模的开放世界手游，场景纹理总量可能高达2GB以上，而主流Android旗舰机型的GPU显存仅有2-4GB。如何在有限显存内呈现高质量画面，是每个移动端游戏开发者面临的核心挑战。

**纹理内存管理的核心矛盾**：
- 近处物体需要高分辨率纹理（清晰度）
- 远处物体只需低分辨率纹理（性能）
- 显存总量有限，无法将所有纹理保持最高质量
- 动态场景中物体距离随时变化

**Mipmap与纹理流式加载正是解决这一矛盾的核心技术**。

## 一、Mipmap体系原理深解

### 1.1 Mipmap层级计算

```
Mipmap层级示例（1024×1024纹理）：
  Level 0: 1024×1024 = 4MB  (100%精度，近处使用)
  Level 1:  512×512  = 1MB  (50%精度)
  Level 2:  256×256  = 256KB(25%精度)
  Level 3:  128×128  = 64KB (12.5%精度)
  Level 4:   64×64   = 16KB (6.25%精度，远处使用)
  Level 5:   32×32   = 4KB
  Level 6:   16×16   = 1KB
  Level 7:    8×8    = 256B
  Level 8:    4×4    = 64B
  Level 9:    2×2    = 16B
  Level 10:   1×1    = 4B
  
总内存：≈ 5.33MB（比Level 0单独增加约33%）
但带来显著的缓存命中率提升和避免远距离采样走样
```

### 1.2 Unity内置纹理流式加载系统

Unity 2018.2+ 内置了 **Texture Streaming（Mipmap Streaming）**，可以根据相机距离动态加载所需Mipmap层级：

```csharp
/// <summary>
/// 纹理流式加载系统配置与监控
/// </summary>
public class TextureStreamingSetup : MonoBehaviour
{
    [Header("内存预算设置")]
    [Tooltip("纹理流式加载的GPU显存预算（字节）")]
    [SerializeField] private long _memoryBudgetBytes = 512 * 1024 * 1024; // 512MB
    
    [Tooltip("最大降级Mipmap层级数")]
    [SerializeField] private int _maxLevelReduction = 2;
    
    [Header("调试显示")]
    [SerializeField] private bool _showDebugInfo = false;
    
    void Awake()
    {
        ConfigureTextureStreaming();
    }
    
    private void ConfigureTextureStreaming()
    {
        // 启用纹理流式加载
        QualitySettings.streamingMipmapsActive = true;
        
        // 设置内存预算
        QualitySettings.streamingMipmapsMemoryBudget = 
            _memoryBudgetBytes / (1024 * 1024); // 转换为MB
        
        // 最大降级层级（当内存不足时最多降低几级Mipmap）
        QualitySettings.streamingMipmapsMaxLevelReduction = _maxLevelReduction;
        
        // 参与流式加载的渲染器数量上限（影响CPU计算开销）
        QualitySettings.streamingMipmapsMaxFileIORequests = 1024;
        
        // 纹理加载系统的优先级
        // 1.0 = 标准，值越高LOD质量越好（需要更多内存）
        QualitySettings.streamingMipmapsRenderersPerFrame = 512;
        
        Debug.Log($"[TextureStreaming] 已配置：预算={_memoryBudgetBytes / 1024 / 1024}MB，" +
                  $"最大降级={_maxLevelReduction}");
    }
    
    void OnGUI()
    {
        if (!_showDebugInfo) return;
        
#if UNITY_EDITOR || DEVELOPMENT_BUILD
        GUILayout.BeginArea(new Rect(10, 200, 400, 200));
        GUILayout.Label($"=== Texture Streaming Stats ===");
        GUILayout.Label($"当前流式内存: {Texture.currentTextureMemory / 1024 / 1024}MB");
        GUILayout.Label($"目标纹理内存: {Texture.targetTextureMemory / 1024 / 1024}MB");
        GUILayout.Label($"期望纹理内存: {Texture.desiredTextureMemory / 1024 / 1024}MB");
        GUILayout.Label($"非流式内存:   {Texture.nonStreamingTextureMemory / 1024 / 1024}MB");
        GUILayout.Label($"等待加载数量: {Texture.streamingMipmapUploadCount}");
        GUILayout.EndArea();
#endif
    }
}
```

### 1.3 单个纹理的流式配置

```csharp
// 通过代码检查和控制单个纹理的流式加载状态
public class TextureStreamingInspector : MonoBehaviour
{
    [SerializeField] private Texture2D _targetTexture;
    
    void Start()
    {
        InspectTexture(_targetTexture);
    }
    
    public static void InspectTexture(Texture2D texture)
    {
        if (texture == null) return;
        
        Debug.Log($"=== 纹理流式状态: {texture.name} ===");
        Debug.Log($"  分辨率: {texture.width}×{texture.height}");
        Debug.Log($"  Mipmap数量: {texture.mipmapCount}");
        Debug.Log($"  是否流式: {texture.streamingMipmaps}");
        Debug.Log($"  加载完成Mip级别: {texture.loadedMipmapLevel}");
        Debug.Log($"  请求的Mip级别: {texture.requestedMipmapLevel}");
        Debug.Log($"  最小Mip级别: {texture.minimumMipmapLevel}");
        Debug.Log($"  格式: {texture.format}");
        Debug.Log($"  显存大小: {Profiler.GetRuntimeMemorySizeLong(texture) / 1024}KB");
    }
    
    /// <summary>
    /// 强制加载指定纹理到最高Mipmap（用于重要场景过场CG）
    /// </summary>
    public static void ForceHighestQuality(Texture2D texture)
    {
        texture.requestedMipmapLevel = 0; // 0 = 最高质量
        // 等待加载完成...
    }
    
    /// <summary>
    /// 释放纹理到最低Mipmap（用于场景卸载前节省内存）
    /// </summary>
    public static void ForceLowQuality(Texture2D texture)
    {
        texture.requestedMipmapLevel = texture.mipmapCount - 1; // 最低质量
    }
    
    /// <summary>
    /// 恢复自动管理
    /// </summary>
    public static void RestoreAutoManagement(Texture2D texture)
    {
        texture.ClearRequestedMipmapLevel();
    }
}
```

## 二、自定义纹理LOD控制系统

### 2.1 基于相机距离的纹理LOD管理器

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 自定义纹理LOD管理器
/// 根据对象与相机的距离，动态控制Mipmap请求级别
/// 补充Unity内置TextureStreaming的不足，实现更精细的控制
/// </summary>
public class TextureLODManager : MonoBehaviour
{
    [System.Serializable]
    public class LODThreshold
    {
        [Tooltip("距离阈值（米）")]
        public float Distance;
        [Tooltip("请求的Mipmap降级层数（0=最高质量，2=降2级）")]
        public int MipmapLevelReduction;
    }
    
    [Header("LOD阈值配置")]
    [SerializeField] private LODThreshold[] _lodThresholds = new LODThreshold[]
    {
        new LODThreshold { Distance = 20f,  MipmapLevelReduction = 0 },
        new LODThreshold { Distance = 50f,  MipmapLevelReduction = 1 },
        new LODThreshold { Distance = 100f, MipmapLevelReduction = 2 },
        new LODThreshold { Distance = 200f, MipmapLevelReduction = 3 },
    };
    
    [Header("更新设置")]
    [SerializeField] private float _updateInterval = 0.5f; // 每0.5秒更新一次
    [SerializeField] private int _maxUpdatePerFrame = 20;   // 每帧最多更新20个对象
    
    private Camera _mainCamera;
    private float _nextUpdateTime;
    
    // 已注册的纹理LOD控制器列表
    private List<TextureLODObject> _registeredObjects = new List<TextureLODObject>();
    private int _updateIndex; // 轮询索引
    
    public static TextureLODManager Instance { get; private set; }
    
    void Awake()
    {
        Instance = this;
        _mainCamera = Camera.main;
    }
    
    void Update()
    {
        if (Time.time < _nextUpdateTime) return;
        _nextUpdateTime = Time.time + _updateInterval;
        
        UpdateTextureLODs();
    }
    
    private void UpdateTextureLODs()
    {
        if (_registeredObjects.Count == 0) return;
        
        Vector3 cameraPos = _mainCamera.transform.position;
        int count = Mathf.Min(_maxUpdatePerFrame, _registeredObjects.Count);
        
        for (int i = 0; i < count; i++)
        {
            // 轮询方式，避免一帧内更新所有对象
            int index = (_updateIndex + i) % _registeredObjects.Count;
            var obj = _registeredObjects[index];
            
            if (obj == null || !obj.gameObject.activeInHierarchy) continue;
            
            float distance = Vector3.Distance(cameraPos, obj.transform.position);
            int lodLevel = CalculateLODLevel(distance);
            obj.ApplyLODLevel(lodLevel);
        }
        
        _updateIndex = (_updateIndex + count) % Mathf.Max(1, _registeredObjects.Count);
    }
    
    private int CalculateLODLevel(float distance)
    {
        for (int i = _lodThresholds.Length - 1; i >= 0; i--)
        {
            if (distance >= _lodThresholds[i].Distance)
                return _lodThresholds[i].MipmapLevelReduction;
        }
        return 0; // 最高质量
    }
    
    public void Register(TextureLODObject obj)
    {
        if (!_registeredObjects.Contains(obj))
            _registeredObjects.Add(obj);
    }
    
    public void Unregister(TextureLODObject obj)
    {
        _registeredObjects.Remove(obj);
    }
    
    void OnDestroy()
    {
        Instance = null;
    }
}

/// <summary>
/// 挂载到游戏对象上，注册到TextureLODManager进行管理
/// </summary>
public class TextureLODObject : MonoBehaviour
{
    private Renderer[] _renderers;
    private List<Texture2D> _managedTextures = new List<Texture2D>();
    private int _currentLODLevel = -1; // -1 = 未初始化
    
    void Awake()
    {
        _renderers = GetComponentsInChildren<Renderer>();
        CollectManagedTextures();
    }
    
    void OnEnable()
    {
        TextureLODManager.Instance?.Register(this);
    }
    
    void OnDisable()
    {
        TextureLODManager.Instance?.Unregister(this);
        RestoreTextures();
    }
    
    private void CollectManagedTextures()
    {
        _managedTextures.Clear();
        
        foreach (var r in _renderers)
        {
            foreach (var mat in r.sharedMaterials)
            {
                if (mat == null) continue;
                
                // 收集主纹理和法线贴图
                AddTextureIfStreaming(mat.mainTexture as Texture2D);
                AddTextureIfStreaming(
                    mat.GetTexture("_BumpMap") as Texture2D);
                AddTextureIfStreaming(
                    mat.GetTexture("_MetallicGlossMap") as Texture2D);
            }
        }
    }
    
    private void AddTextureIfStreaming(Texture2D tex)
    {
        if (tex != null && tex.streamingMipmaps && !_managedTextures.Contains(tex))
        {
            _managedTextures.Add(tex);
        }
    }
    
    /// <summary>
    /// 应用LOD级别（由TextureLODManager调用）
    /// </summary>
    public void ApplyLODLevel(int lodLevel)
    {
        if (_currentLODLevel == lodLevel) return; // 无变化跳过
        _currentLODLevel = lodLevel;
        
        foreach (var tex in _managedTextures)
        {
            if (tex == null) continue;
            
            if (lodLevel == 0)
            {
                // 恢复自动管理
                tex.ClearRequestedMipmapLevel();
            }
            else
            {
                // 请求降级Mipmap
                int targetLevel = Mathf.Min(
                    tex.mipmapCount - 1,
                    tex.loadedMipmapLevel + lodLevel);
                tex.requestedMipmapLevel = targetLevel;
            }
        }
    }
    
    private void RestoreTextures()
    {
        foreach (var tex in _managedTextures)
        {
            tex?.ClearRequestedMipmapLevel();
        }
        _currentLODLevel = -1;
    }
}
```

## 三、纹理压缩格式选型指南

### 3.1 移动端纹理压缩格式对比

```csharp
/// <summary>
/// 纹理格式选型决策系统
/// 根据设备GPU类型和图片内容自动选择最优压缩格式
/// </summary>
public static class TextureFormatSelector
{
    /// <summary>
    /// 纹理用途分类
    /// </summary>
    public enum TextureUsage
    {
        Albedo,         // 漫反射颜色（支持透明）
        NormalMap,      // 法线贴图
        MaskMap,        // 遮罩（金属度/粗糙度/AO/自发光）
        UIElement,      // UI纹理（高质量，支持透明）
        Particle,       // 粒子特效（支持透明）
        Lightmap,       // 光照贴图（HDR）
        CubemapFace,    // 环境反射
    }
    
    /// <summary>
    /// 获取推荐纹理格式
    /// </summary>
    public static TextureFormat GetRecommendedFormat(
        TextureUsage usage, bool hasAlpha, bool isHDR)
    {
        // iOS (PowerVR / Apple GPU) → 支持 ASTC
        // Android High-end (Adreno 6xx, Mali-G7x) → 支持 ASTC
        // Android Low-end (Mali-T, Adreno 3xx) → 使用 ETC2
        
        bool supportsASTC = SystemInfo.SupportsTextureFormat(TextureFormat.ASTC_4x4);
        
        if (isHDR)
        {
            return TextureFormat.BC6H; // 或 EAC_RG 用于移动端
        }
        
        switch (usage)
        {
            case TextureUsage.Albedo:
                if (hasAlpha)
                    return supportsASTC ? TextureFormat.ASTC_4x4 : TextureFormat.ETC2_RGBA8;
                else
                    return supportsASTC ? TextureFormat.ASTC_6x6 : TextureFormat.ETC2_RGB;
                
            case TextureUsage.NormalMap:
                // 法线贴图需要较高精度，使用4x4 ASTC或 EAC
                return supportsASTC ? TextureFormat.ASTC_4x4 : TextureFormat.EAC_RG;
                
            case TextureUsage.MaskMap:
                // 遮罩图精度要求低，可用8x8 ASTC节省内存
                return supportsASTC ? TextureFormat.ASTC_8x8 : TextureFormat.ETC2_RGBA8;
                
            case TextureUsage.UIElement:
                // UI需要无损或近无损，使用高质量ASTC
                return supportsASTC ? TextureFormat.ASTC_4x4 : TextureFormat.ETC2_RGBA8;
                
            case TextureUsage.Particle:
                return supportsASTC ? TextureFormat.ASTC_6x6 : TextureFormat.ETC2_RGBA8;
                
            case TextureUsage.Lightmap:
                return TextureFormat.RGB9e5Float; // HDR光照贴图
                
            default:
                return supportsASTC ? TextureFormat.ASTC_6x6 : TextureFormat.ETC2_RGB;
        }
    }
    
    /// <summary>
    /// 运行时检查格式支持情况
    /// </summary>
    public static void LogSupportedFormats()
    {
        var formats = new[]
        {
            (TextureFormat.ASTC_4x4,    "ASTC 4x4"),
            (TextureFormat.ASTC_6x6,    "ASTC 6x6"),
            (TextureFormat.ASTC_8x8,    "ASTC 8x8"),
            (TextureFormat.ETC2_RGB,    "ETC2 RGB"),
            (TextureFormat.ETC2_RGBA8,  "ETC2 RGBA8"),
            (TextureFormat.EAC_RG,      "EAC RG（法线贴图）"),
            (TextureFormat.BC7,         "BC7（PC端）"),
        };
        
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("=== 当前设备纹理格式支持情况 ===");
        foreach (var (format, name) in formats)
        {
            bool supported = SystemInfo.SupportsTextureFormat(format);
            sb.AppendLine($"  {name}: {(supported ? "✅ 支持" : "❌ 不支持")}");
        }
        Debug.Log(sb.ToString());
    }
}
```

### 3.2 纹理内存占用估算工具

```csharp
/// <summary>
/// 纹理内存占用分析工具
/// 帮助开发者在制作阶段评估纹理内存消耗
/// </summary>
public static class TextureMemoryCalculator
{
    /// <summary>
    /// 估算纹理内存占用（包含所有Mipmap层级）
    /// </summary>
    public static long EstimateMemorySize(
        int width, int height, TextureFormat format, bool includeMipmaps)
    {
        long baseSize = CalculateLevelSize(width, height, format);
        
        if (!includeMipmaps) return baseSize;
        
        // Mipmap总内存 ≈ baseSize * 4/3
        return baseSize * 4 / 3;
    }
    
    private static long CalculateLevelSize(int width, int height, TextureFormat format)
    {
        // 计算单个Mipmap层级的字节数
        switch (format)
        {
            // 未压缩格式
            case TextureFormat.RGBA32:    return (long)width * height * 4;
            case TextureFormat.RGB24:     return (long)width * height * 3;
            case TextureFormat.RGBAHalf:  return (long)width * height * 8;
            case TextureFormat.RGBAFloat: return (long)width * height * 16;
            
            // ASTC（4x4 block = 16字节）
            case TextureFormat.ASTC_4x4:
                return (long)Mathf.CeilToInt(width / 4f) * 
                       Mathf.CeilToInt(height / 4f) * 16;
            case TextureFormat.ASTC_6x6:
                return (long)Mathf.CeilToInt(width / 6f) * 
                       Mathf.CeilToInt(height / 6f) * 16;
            case TextureFormat.ASTC_8x8:
                return (long)Mathf.CeilToInt(width / 8f) * 
                       Mathf.CeilToInt(height / 8f) * 16;
            
            // ETC2 (每个4x4块8字节RGB，16字节RGBA)
            case TextureFormat.ETC2_RGB:
                return (long)Mathf.CeilToInt(width / 4f) * 
                       Mathf.CeilToInt(height / 4f) * 8;
            case TextureFormat.ETC2_RGBA8:
                return (long)Mathf.CeilToInt(width / 4f) * 
                       Mathf.CeilToInt(height / 4f) * 16;
            
            // BC格式（PC端）
            case TextureFormat.BC1:  // DXT1
                return (long)Mathf.CeilToInt(width / 4f) * 
                       Mathf.CeilToInt(height / 4f) * 8;
            case TextureFormat.BC3:  // DXT5
            case TextureFormat.BC7:
                return (long)Mathf.CeilToInt(width / 4f) * 
                       Mathf.CeilToInt(height / 4f) * 16;
            
            default:
                // 默认按RGBA32估算
                return (long)width * height * 4;
        }
    }
    
    /// <summary>
    /// 生成纹理内存报告
    /// </summary>
    public static string GenerateReport(Texture2D[] textures)
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("=== 纹理内存分析报告 ===");
        
        long totalMemory = 0;
        var formatGroups = new Dictionary<TextureFormat, (int Count, long Memory)>();
        
        foreach (var tex in textures)
        {
            if (tex == null) continue;
            long size = Profiler.GetRuntimeMemorySizeLong(tex);
            totalMemory += size;
            
            if (!formatGroups.ContainsKey(tex.format))
                formatGroups[tex.format] = (0, 0);
            
            var group = formatGroups[tex.format];
            formatGroups[tex.format] = (group.Count + 1, group.Memory + size);
            
            // 显示超过1MB的大纹理
            if (size > 1024 * 1024)
            {
                sb.AppendLine($"  ⚠️ 大纹理: {tex.name} ({tex.width}×{tex.height} " +
                              $"{tex.format}) = {size / 1024 / 1024}MB");
            }
        }
        
        sb.AppendLine($"\n总内存: {totalMemory / 1024 / 1024}MB");
        sb.AppendLine("\n按格式分类:");
        foreach (var kv in formatGroups)
        {
            sb.AppendLine($"  {kv.Key}: {kv.Value.Count}张, " +
                          $"{kv.Value.Memory / 1024 / 1024}MB");
        }
        
        return sb.ToString();
    }
}
```

## 四、运行时纹理内存预算系统

### 4.1 纹理内存预算管理器

```csharp
/// <summary>
/// 运行时纹理内存预算管理器
/// 监控显存使用情况，在超过阈值时自动降级低优先级纹理
/// </summary>
public class TextureMemoryBudgetManager : MonoBehaviour
{
    [Header("内存预算配置")]
    [Tooltip("纹理内存软上限（MB），达到时开始降级低优先级纹理")]
    [SerializeField] private float _softLimitMB = 400f;
    [Tooltip("纹理内存硬上限（MB），超过时强制降级所有非关键纹理")]
    [SerializeField] private float _hardLimitMB = 512f;
    
    [Header("监控间隔")]
    [SerializeField] private float _checkInterval = 2f;
    
    private float _nextCheckTime;
    
    // 纹理优先级注册表
    private SortedDictionary<int, List<Texture2D>> _priorityGroups 
        = new SortedDictionary<int, List<Texture2D>>();
    
    public static TextureMemoryBudgetManager Instance { get; private set; }
    
    void Awake()
    {
        Instance = this;
    }
    
    void Update()
    {
        if (Time.time < _nextCheckTime) return;
        _nextCheckTime = Time.time + _checkInterval;
        CheckAndAdjustMemory();
    }
    
    /// <summary>
    /// 注册纹理到指定优先级组
    /// 优先级越低，内存压力时越先被降级
    /// </summary>
    public void RegisterTexture(Texture2D texture, int priority)
    {
        if (!_priorityGroups.ContainsKey(priority))
            _priorityGroups[priority] = new List<Texture2D>();
        
        if (!_priorityGroups[priority].Contains(texture))
            _priorityGroups[priority].Add(texture);
    }
    
    public void UnregisterTexture(Texture2D texture)
    {
        foreach (var group in _priorityGroups.Values)
        {
            if (group.Remove(texture)) break;
        }
    }
    
    private void CheckAndAdjustMemory()
    {
        float currentMemoryMB = 
            (Texture.currentTextureMemory + Texture.nonStreamingTextureMemory) 
            / (1024f * 1024f);
        
        if (currentMemoryMB > _hardLimitMB)
        {
            // 强制模式：降级所有低优先级纹理
            DegradePriorityGroup(0, maxDegradation: 3);
            DegradePriorityGroup(1, maxDegradation: 2);
            Debug.LogWarning($"[TextureBudget] 硬限制触发！" +
                             $"当前={currentMemoryMB:F0}MB 限制={_hardLimitMB}MB");
        }
        else if (currentMemoryMB > _softLimitMB)
        {
            // 软限制：仅降级最低优先级
            DegradePriorityGroup(0, maxDegradation: 2);
        }
        else if (currentMemoryMB < _softLimitMB * 0.7f)
        {
            // 内存充足：恢复纹理质量
            RestoreAllTextures();
        }
    }
    
    private void DegradePriorityGroup(int priority, int maxDegradation)
    {
        if (!_priorityGroups.TryGetValue(priority, out var group)) return;
        
        foreach (var tex in group)
        {
            if (tex == null) continue;
            int targetLevel = Mathf.Min(tex.mipmapCount - 1, maxDegradation);
            tex.requestedMipmapLevel = targetLevel;
        }
    }
    
    private void RestoreAllTextures()
    {
        foreach (var group in _priorityGroups.Values)
        {
            foreach (var tex in group)
            {
                tex?.ClearRequestedMipmapLevel();
            }
        }
    }
    
    void OnGUI()
    {
#if UNITY_EDITOR || DEVELOPMENT_BUILD
        float currentMB = Texture.currentTextureMemory / (1024f * 1024f);
        float targetMB = Texture.targetTextureMemory / (1024f * 1024f);
        
        Color barColor = currentMB > _hardLimitMB ? Color.red :
                         currentMB > _softLimitMB ? Color.yellow : Color.green;
        
        GUILayout.BeginArea(new Rect(Screen.width - 250, 10, 240, 80));
        GUI.color = barColor;
        GUILayout.Label($"纹理内存: {currentMB:F0}MB / {_hardLimitMB}MB");
        GUILayout.Label($"目标内存: {targetMB:F0}MB");
        
        // 简易进度条
        float ratio = currentMB / _hardLimitMB;
        GUI.DrawTexture(
            new Rect(0, 50, 240 * ratio, 20), 
            Texture2D.whiteTexture);
        
        GUI.color = Color.white;
        GUILayout.EndArea();
#endif
    }
}
```

## 五、场景纹理预加载策略

### 5.1 场景切换时的纹理预热系统

```csharp
/// <summary>
/// 场景加载时的纹理预热管理器
/// 在场景转换的Loading阶段，预先将关键纹理加载到最高质量
/// 避免进入场景后纹理逐渐清晰的不良体验
/// </summary>
public class SceneTexturePrewarmer : MonoBehaviour
{
    [Header("预热配置")]
    [SerializeField] private Texture2D[] _criticalTextures; // 必须预热的关键纹理
    [SerializeField] private float _prewarmTimeout = 5f;    // 最大等待时间
    
    /// <summary>
    /// 预热关键纹理（在Loading界面时调用）
    /// </summary>
    public async System.Threading.Tasks.Task PrewarmAsync()
    {
        float startTime = Time.realtimeSinceStartup;
        
        // 强制请求最高质量
        foreach (var tex in _criticalTextures)
        {
            if (tex != null && tex.streamingMipmaps)
            {
                tex.requestedMipmapLevel = 0;
            }
        }
        
        // 等待纹理加载完成
        while (Time.realtimeSinceStartup - startTime < _prewarmTimeout)
        {
            if (AllCriticalTexturesLoaded()) break;
            
            await System.Threading.Tasks.Task.Yield();
        }
        
        Debug.Log($"[TexturePrewarmer] 预热完成，耗时: " +
                  $"{Time.realtimeSinceStartup - startTime:F2}s");
    }
    
    private bool AllCriticalTexturesLoaded()
    {
        foreach (var tex in _criticalTextures)
        {
            if (tex == null) continue;
            
            // 检查纹理是否已加载到请求的Mipmap级别
            if (tex.loadedMipmapLevel > tex.requestedMipmapLevel)
                return false;
        }
        return true;
    }
    
    /// <summary>
    /// 场景退出时释放关键纹理的预热锁定
    /// </summary>
    public void ReleasePrewarm()
    {
        foreach (var tex in _criticalTextures)
        {
            tex?.ClearRequestedMipmapLevel();
        }
    }
}

/// <summary>
/// 纹理异步下载与缓存系统（用于热更新纹理）
/// </summary>
public class RuntimeTextureCacheSystem
{
    private static readonly Dictionary<string, Texture2D> _cache 
        = new Dictionary<string, Texture2D>();
    
    /// <summary>
    /// 从URL加载纹理（带本地缓存）
    /// </summary>
    public static async System.Threading.Tasks.Task<Texture2D> LoadFromUrlAsync(
        string url, bool useCache = true)
    {
        // 检查内存缓存
        if (useCache && _cache.TryGetValue(url, out var cached))
            return cached;
        
        // 检查磁盘缓存
        string cacheKey = System.Convert.ToBase64String(
            System.Security.Cryptography.MD5.Create()
            .ComputeHash(System.Text.Encoding.UTF8.GetBytes(url)));
        
        string cachePath = System.IO.Path.Combine(
            Application.persistentDataPath, "TextureCache", cacheKey + ".png");
        
        Texture2D texture = null;
        
        if (useCache && System.IO.File.Exists(cachePath))
        {
            // 从磁盘缓存加载
            byte[] bytes = System.IO.File.ReadAllBytes(cachePath);
            texture = new Texture2D(2, 2);
            texture.LoadImage(bytes);
        }
        else
        {
            // 从网络下载
            using (var www = UnityEngine.Networking.UnityWebRequest.Get(url))
            {
                www.downloadHandler = new UnityEngine.Networking.DownloadHandlerTexture();
                await www.SendWebRequest();
                
                if (www.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
                {
                    texture = ((UnityEngine.Networking.DownloadHandlerTexture)
                               www.downloadHandler).texture;
                    
                    // 保存到磁盘缓存
                    if (useCache)
                    {
                        System.IO.Directory.CreateDirectory(
                            System.IO.Path.GetDirectoryName(cachePath));
                        System.IO.File.WriteAllBytes(cachePath, 
                            texture.EncodeToPNG());
                    }
                }
            }
        }
        
        if (texture != null && useCache)
            _cache[url] = texture;
        
        return texture;
    }
    
    /// <summary>
    /// 清理内存缓存中未使用的纹理
    /// </summary>
    public static void ClearUnusedCache()
    {
        var toRemove = new List<string>();
        foreach (var kv in _cache)
        {
            if (kv.Value == null) toRemove.Add(kv.Key);
        }
        foreach (var key in toRemove) _cache.Remove(key);
    }
}
```

## 六、Editor工具：纹理优化分析

### 6.1 纹理优化建议工具（Editor窗口）

```csharp
#if UNITY_EDITOR
using UnityEditor;
using System.Linq;

/// <summary>
/// 纹理优化分析Editor工具
/// 扫描项目中的纹理，给出内存优化建议
/// </summary>
public class TextureOptimizationWindow : EditorWindow
{
    private Vector2 _scrollPos;
    private List<TextureOptimizationIssue> _issues;
    
    [MenuItem("Tools/Game/纹理优化分析")]
    static void ShowWindow()
    {
        GetWindow<TextureOptimizationWindow>("纹理优化分析");
    }
    
    public class TextureOptimizationIssue
    {
        public Texture2D Texture;
        public string AssetPath;
        public string IssueType;
        public string Suggestion;
        public long EstimatedSavingBytes;
    }
    
    void OnGUI()
    {
        EditorGUILayout.LabelField("纹理优化分析工具", EditorStyles.boldLabel);
        
        if (GUILayout.Button("扫描项目纹理"))
        {
            ScanProjectTextures();
        }
        
        if (_issues != null)
        {
            EditorGUILayout.LabelField($"发现 {_issues.Count} 个优化建议：");
            
            long totalSaving = _issues.Sum(i => i.EstimatedSavingBytes);
            EditorGUILayout.LabelField(
                $"预估可节省: {totalSaving / 1024 / 1024}MB", 
                EditorStyles.boldLabel);
            
            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
            foreach (var issue in _issues)
            {
                EditorGUILayout.BeginHorizontal("box");
                
                if (GUILayout.Button(
                    issue.Texture.name, 
                    GUILayout.Width(200)))
                {
                    Selection.activeObject = issue.Texture;
                    EditorGUIUtility.PingObject(issue.Texture);
                }
                
                EditorGUILayout.LabelField(
                    issue.IssueType, 
                    GUILayout.Width(150));
                EditorGUILayout.LabelField(
                    issue.Suggestion, 
                    GUILayout.ExpandWidth(true));
                EditorGUILayout.LabelField(
                    $"-{issue.EstimatedSavingBytes / 1024}KB", 
                    GUILayout.Width(80));
                
                EditorGUILayout.EndHorizontal();
            }
            EditorGUILayout.EndScrollView();
        }
    }
    
    private void ScanProjectTextures()
    {
        _issues = new List<TextureOptimizationIssue>();
        
        string[] guids = AssetDatabase.FindAssets("t:Texture2D");
        
        foreach (string guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;
            
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (texture == null) continue;
            
            // 检查1：非2的幂次方纹理
            if (!IsPowerOfTwo(texture.width) || !IsPowerOfTwo(texture.height))
            {
                _issues.Add(new TextureOptimizationIssue
                {
                    Texture = texture,
                    AssetPath = path,
                    IssueType = "NPOT纹理",
                    Suggestion = $"分辨率{texture.width}×{texture.height}非2的幂，无法启用Mipmap和压缩",
                    EstimatedSavingBytes = 
                        Profiler.GetRuntimeMemorySizeLong(texture) / 2
                });
            }
            
            // 检查2：过大的UI纹理
            if (importer.textureType == TextureImporterType.Sprite && 
                (texture.width > 512 || texture.height > 512))
            {
                _issues.Add(new TextureOptimizationIssue
                {
                    Texture = texture,
                    AssetPath = path,
                    IssueType = "大尺寸UI纹理",
                    Suggestion = $"UI纹理{texture.width}×{texture.height}建议不超过512×512",
                    EstimatedSavingBytes = 
                        Profiler.GetRuntimeMemorySizeLong(texture) * 3 / 4
                });
            }
            
            // 检查3：未启用Mipmap的大型场景纹理
            if (importer.textureType == TextureImporterType.Default &&
                !importer.mipmapEnabled &&
                texture.width >= 1024)
            {
                _issues.Add(new TextureOptimizationIssue
                {
                    Texture = texture,
                    AssetPath = path,
                    IssueType = "未启用Mipmap",
                    Suggestion = "大型场景纹理建议启用Mipmap，避免远处采样走样",
                    EstimatedSavingBytes = 0 // 启用Mipmap会增加1/3内存，但提升性能
                });
            }
            
            // 检查4：使用RGBA32而非压缩格式
            if (texture.format == TextureFormat.RGBA32 && 
                Profiler.GetRuntimeMemorySizeLong(texture) > 1024 * 1024)
            {
                long currentSize = Profiler.GetRuntimeMemorySizeLong(texture);
                long estimatedCompressedSize = currentSize / 8; // ASTC约为1/8压缩率
                
                _issues.Add(new TextureOptimizationIssue
                {
                    Texture = texture,
                    AssetPath = path,
                    IssueType = "未压缩格式",
                    Suggestion = "建议使用ASTC/ETC2压缩格式，可节省约75-87.5%内存",
                    EstimatedSavingBytes = currentSize - estimatedCompressedSize
                });
            }
        }
        
        // 按节省内存从大到小排序
        _issues.Sort((a, b) => 
            b.EstimatedSavingBytes.CompareTo(a.EstimatedSavingBytes));
    }
    
    private static bool IsPowerOfTwo(int value)
    {
        return value > 0 && (value & (value - 1)) == 0;
    }
}
#endif
```

## 七、最佳实践总结

### 7.1 纹理内存优化策略表

| 优化策略 | 适用场景 | 内存节省 | 实施难度 |
|---------|---------|---------|---------|
| ASTC压缩 | 所有场景纹理 | 75-90% | 低 |
| 启用Mipmap流式加载 | 开放世界场景 | 30-50% | 低 |
| 纹理图集 | UI、植被、小道具 | 20-40% | 中 |
| 自定义Mipmap LOD | 角色、重要场景物体 | 10-30% | 中 |
| 纹理压缩预算管理 | 内存敏感设备 | 15-25% | 高 |
| 非2的幂次方修正 | 旧版资源 | 0-50% | 低 |

### 7.2 分设备档位纹理策略

```csharp
/// <summary>
/// 根据设备性能档位设置纹理质量
/// </summary>
public class DeviceAdaptiveTextureQuality
{
    public enum DeviceTier { Low, Mid, High }
    
    public static void Configure(DeviceTier tier)
    {
        switch (tier)
        {
            case DeviceTier.Low:
                // 低端机：限制纹理分辨率、禁用流式加载外的Mipmap
                QualitySettings.masterTextureLimit = 2; // 1/4分辨率
                QualitySettings.streamingMipmapsMemoryBudget = 128;
                break;
                
            case DeviceTier.Mid:
                QualitySettings.masterTextureLimit = 1; // 1/2分辨率
                QualitySettings.streamingMipmapsMemoryBudget = 256;
                break;
                
            case DeviceTier.High:
                QualitySettings.masterTextureLimit = 0; // 原始分辨率
                QualitySettings.streamingMipmapsMemoryBudget = 512;
                break;
        }
    }
}
```

### 7.3 性能黄金法则

```
纹理内存优化三原则：

1. 「压得住」：始终使用GPU压缩格式（ASTC/ETC2）
   → 拒绝RGBA32在移动端出现在场景纹理中

2. 「用多少，加载多少」：启用Mipmap流式加载
   → 远处物体用低分辨率Mipmap，仅近处物体加载最高质量

3. 「不用了就放」：场景切换时及时释放无用纹理
   → Addressables.Release() 确保引用计数归零触发卸载
```

## 结语

纹理流式加载与Mipmap动态管理是移动端游戏性能优化的最高ROI策略之一。正确实施后，通常可以：
- 将GPU显存占用降低 **40-60%**
- 减少加载时间 **20-40%**（只加载必要层级）
- 提升帧率稳定性（减少显存抖动引起的卡顿）

建议按以下优先级逐步落地：
1. **立竿见影**：为所有场景纹理启用ASTC/ETC2压缩
2. **短期**：配置Texture Streaming系统和内存预算
3. **中期**：基于重要性建立自定义Mipmap LOD控制
4. **长期**：建立纹理内存监控与自动降级保障体系

每项优化都值得在真实设备上做前后对比测试，用数据驱动决策。
