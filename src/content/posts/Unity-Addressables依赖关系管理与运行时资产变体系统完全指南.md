---
title: Unity Addressables依赖关系管理与运行时资产变体系统完全指南
published: 2026-04-22
description: 深度解析Unity Addressables的依赖关系图构建、循环依赖检测、运行时资产变体（AssetVariant）实现，以及基于Bundle粒度的智能拆包策略，帮助团队构建可维护、高性能的资产管理体系。
tags: [Unity, Addressables, 资产管理, 资产变体, 热更新, Bundle]
category: 资产管理
draft: false
---

# Unity Addressables依赖关系管理与运行时资产变体系统完全指南

## 一、Addressables依赖关系核心机制

### 1.1 依赖关系的本质

在Unity Addressables中，每个可寻址资产（Addressable Asset）都可能依赖其他资产。理解这些依赖关系对于：
- **避免资产重复打包**（导致包体膨胀）
- **正确设计Bundle拆包策略**（影响加载性能）
- **防止循环依赖导致的加载死锁**

至关重要。

```
典型的资产依赖图：

Character.prefab
├── CharacterMesh.fbx          → 打包在 characters.bundle
├── SwordTexture.png           → 打包在 textures.bundle
├── Character.controller       → 打包在 animations.bundle
│   └── IdleAnimation.anim    → 打包在 animations.bundle
└── CharacterMaterial.mat      → 打包在 materials.bundle
    ├── MainTexture.png        → ⚠️ 已在 textures.bundle（复用）
    └── NormalMap.png          → ⚠️ 若没有正确配置，会被重复打入 materials.bundle！
```

---

## 二、依赖关系分析与可视化工具

### 2.1 构建完整依赖图

```csharp
using UnityEditor;
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

/// <summary>
/// Addressables依赖关系分析器
/// 构建完整的资产依赖图，检测重复打包和循环依赖
/// </summary>
public class AddressablesDependencyAnalyzer
{
    // 资产节点
    public class AssetNode
    {
        public string AssetPath;
        public string AssetGuid;
        public string AddressableGroup; // 为空表示非Addressable资产
        public string BundleName;
        public long FileSizeBytes;
        public HashSet<AssetNode> Dependencies = new HashSet<AssetNode>();
        public HashSet<AssetNode> Dependents = new HashSet<AssetNode>();  // 被哪些资产依赖
        
        public bool IsAddressable => !string.IsNullOrEmpty(AddressableGroup);
        
        public override string ToString() => 
            $"[{AddressableGroup ?? "非Addressable"}] {System.IO.Path.GetFileName(AssetPath)}";
    }
    
    private Dictionary<string, AssetNode> _nodeMap = new Dictionary<string, AssetNode>();
    
    /// <summary>
    /// 构建完整的依赖关系图
    /// </summary>
    public void BuildDependencyGraph()
    {
        _nodeMap.Clear();
        
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        if (settings == null)
        {
            Debug.LogError("未找到Addressables配置");
            return;
        }
        
        // 收集所有Addressable资产
        var allAddressables = new List<(string path, string group)>();
        foreach (var group in settings.groups)
        {
            if (group == null) continue;
            foreach (var entry in group.entries)
            {
                allAddressables.Add((entry.AssetPath, group.Name));
            }
        }
        
        Debug.Log($"[DependencyAnalyzer] 开始分析 {allAddressables.Count} 个Addressable资产...");
        
        // 为每个资产构建节点
        foreach (var (path, group) in allAddressables)
        {
            GetOrCreateNode(path, group);
        }
        
        // 递归分析依赖
        foreach (var (path, _) in allAddressables)
        {
            AnalyzeDependencies(_nodeMap[path], new HashSet<string>());
        }
        
        Debug.Log($"[DependencyAnalyzer] 分析完成，共 {_nodeMap.Count} 个资产节点");
    }
    
    private AssetNode GetOrCreateNode(string assetPath, string groupName = null)
    {
        if (!_nodeMap.TryGetValue(assetPath, out var node))
        {
            node = new AssetNode
            {
                AssetPath = assetPath,
                AssetGuid = AssetDatabase.AssetPathToGUID(assetPath),
                AddressableGroup = groupName,
                FileSizeBytes = GetFileSize(assetPath)
            };
            _nodeMap[assetPath] = node;
        }
        return node;
    }
    
    private void AnalyzeDependencies(AssetNode node, HashSet<string> visitedPaths)
    {
        if (visitedPaths.Contains(node.AssetPath)) return;
        visitedPaths.Add(node.AssetPath);
        
        // 获取直接依赖
        string[] deps = AssetDatabase.GetDependencies(node.AssetPath, false);
        
        foreach (string depPath in deps)
        {
            if (depPath == node.AssetPath) continue;
            
            var depNode = GetOrCreateNode(depPath);
            node.Dependencies.Add(depNode);
            depNode.Dependents.Add(node);
            
            // 递归分析依赖的依赖
            AnalyzeDependencies(depNode, new HashSet<string>(visitedPaths));
        }
    }
    
    /// <summary>
    /// 检测重复打包的资产（非Addressable但被多个Bundle引用）
    /// </summary>
    public List<AssetNode> FindDuplicatedAssets(int minReferenceCount = 2)
    {
        return _nodeMap.Values
            .Where(node => !node.IsAddressable 
                        && node.Dependents.Count >= minReferenceCount
                        && node.Dependents.Select(d => d.AddressableGroup).Distinct().Count() >= minReferenceCount)
            .OrderByDescending(node => node.FileSizeBytes * node.Dependents.Count)
            .ToList();
    }
    
    /// <summary>
    /// 检测循环依赖链
    /// </summary>
    public List<List<AssetNode>> FindCircularDependencies()
    {
        var cycles = new List<List<AssetNode>>();
        var visited = new HashSet<string>();
        var recursionStack = new List<AssetNode>();
        
        foreach (var node in _nodeMap.Values.Where(n => n.IsAddressable))
        {
            if (!visited.Contains(node.AssetPath))
            {
                DetectCycle(node, visited, recursionStack, cycles);
            }
        }
        
        return cycles;
    }
    
    private bool DetectCycle(AssetNode node, HashSet<string> visited, 
        List<AssetNode> recursionStack, List<List<AssetNode>> cycles)
    {
        visited.Add(node.AssetPath);
        recursionStack.Add(node);
        
        foreach (var dep in node.Dependencies)
        {
            if (!visited.Contains(dep.AssetPath))
            {
                if (DetectCycle(dep, visited, recursionStack, cycles))
                    return true;
            }
            else if (recursionStack.Contains(dep))
            {
                // 找到循环依赖
                int cycleStart = recursionStack.IndexOf(dep);
                var cycle = recursionStack.Skip(cycleStart).ToList();
                cycles.Add(cycle);
                return true;
            }
        }
        
        recursionStack.Remove(node);
        return false;
    }
    
    private long GetFileSize(string assetPath)
    {
        if (System.IO.File.Exists(assetPath))
            return new System.IO.FileInfo(assetPath).Length;
        return 0;
    }
    
    /// <summary>
    /// 生成分析报告
    /// </summary>
    public string GenerateReport()
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("=== Addressables依赖关系分析报告 ===\n");
        
        // 重复打包检测
        var duplicates = FindDuplicatedAssets();
        sb.AppendLine($"【重复打包检测】发现 {duplicates.Count} 个可能重复打包的资产：");
        foreach (var dup in duplicates.Take(20))
        {
            long wastedSize = dup.FileSizeBytes * (dup.Dependents.Count - 1);
            sb.AppendLine($"  {System.IO.Path.GetFileName(dup.AssetPath)}");
            sb.AppendLine($"    - 被 {dup.Dependents.Count} 个资产引用（不同Group）");
            sb.AppendLine($"    - 文件大小: {dup.FileSizeBytes / 1024f:F1} KB");
            sb.AppendLine($"    - 预计浪费空间: {wastedSize / 1024f:F1} KB");
            sb.AppendLine($"    - 建议: 将此资产单独设为Addressable或创建共享Bundle");
        }
        
        // 循环依赖检测
        var cycles = FindCircularDependencies();
        sb.AppendLine($"\n【循环依赖检测】发现 {cycles.Count} 个循环依赖链：");
        foreach (var cycle in cycles)
        {
            sb.AppendLine($"  循环链: {string.Join(" → ", cycle.Select(n => n.AssetPath))}");
        }
        
        return sb.ToString();
    }
}
```

### 2.2 可视化编辑器窗口

```csharp
using UnityEditor;
using UnityEngine;

public class AddressablesDependencyWindow : EditorWindow
{
    [MenuItem("Tools/Addressables/依赖关系分析器")]
    public static void ShowWindow()
    {
        GetWindow<AddressablesDependencyWindow>("依赖分析器");
    }
    
    private AddressablesDependencyAnalyzer _analyzer = new AddressablesDependencyAnalyzer();
    private string _report = "";
    private Vector2 _scrollPos;
    private bool _analyzed = false;
    
    private void OnGUI()
    {
        EditorGUILayout.LabelField("Addressables 依赖关系分析", EditorStyles.boldLabel);
        EditorGUILayout.Space();
        
        if (GUILayout.Button("分析依赖关系（可能耗时1-5分钟）", GUILayout.Height(40)))
        {
            RunAnalysis();
        }
        
        if (_analyzed)
        {
            EditorGUILayout.Space();
            EditorGUILayout.LabelField("分析结果：", EditorStyles.boldLabel);
            
            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
            EditorGUILayout.TextArea(_report, GUILayout.ExpandHeight(true));
            EditorGUILayout.EndScrollView();
            
            EditorGUILayout.Space();
            if (GUILayout.Button("导出报告"))
            {
                string path = EditorUtility.SaveFilePanel("保存报告", "", "DependencyReport.txt", "txt");
                if (!string.IsNullOrEmpty(path))
                    System.IO.File.WriteAllText(path, _report);
            }
        }
    }
    
    private void RunAnalysis()
    {
        EditorUtility.DisplayProgressBar("分析中", "正在构建依赖图...", 0.3f);
        try
        {
            _analyzer.BuildDependencyGraph();
            EditorUtility.DisplayProgressBar("分析中", "正在生成报告...", 0.8f);
            _report = _analyzer.GenerateReport();
            _analyzed = true;
        }
        finally
        {
            EditorUtility.ClearProgressBar();
        }
    }
}
```

---

## 三、运行时资产变体系统（Asset Variants）

### 3.1 资产变体的应用场景

| 场景 | 变体类型 | 示例 |
|------|----------|------|
| 画质分级 | 高/中/低品质纹理 | character_hd.png / character_sd.png |
| 语言本地化 | 多语言图集 | ui_atlas_zh.spriteatlas / ui_atlas_en.spriteatlas |
| 平台差异 | iOS/Android专属 | shader_metal / shader_opengl |
| 设备性能 | 高端/低端机型 | particle_full / particle_lite |
| 节日主题 | 换肤/主题包 | ui_skin_default / ui_skin_spring |

### 3.2 基于Addressables Label的变体系统

```csharp
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
using System.Collections.Generic;
using System.Threading.Tasks;

/// <summary>
/// 运行时资产变体管理器
/// 通过Addressables Labels实现多变体资产的动态切换
/// </summary>
public class AssetVariantManager : MonoBehaviour
{
    public static AssetVariantManager Instance { get; private set; }
    
    // 变体维度定义
    public enum QualityVariant { High, Medium, Low }
    public enum LanguageVariant { Chinese, English, Japanese, Korean }
    public enum ThemeVariant { Default, Spring, Summer, Halloween, Christmas }
    
    // 当前激活的变体配置
    private QualityVariant _currentQuality = QualityVariant.High;
    private LanguageVariant _currentLanguage = LanguageVariant.Chinese;
    private ThemeVariant _currentTheme = ThemeVariant.Default;
    
    // Label映射表
    private static readonly Dictionary<QualityVariant, string> QualityLabels = new()
    {
        { QualityVariant.High,   "quality_high" },
        { QualityVariant.Medium, "quality_medium" },
        { QualityVariant.Low,    "quality_low" }
    };
    
    private static readonly Dictionary<LanguageVariant, string> LanguageLabels = new()
    {
        { LanguageVariant.Chinese,  "lang_zh" },
        { LanguageVariant.English,  "lang_en" },
        { LanguageVariant.Japanese, "lang_ja" },
        { LanguageVariant.Korean,   "lang_ko" }
    };
    
    private static readonly Dictionary<ThemeVariant, string> ThemeLabels = new()
    {
        { ThemeVariant.Default,    "theme_default" },
        { ThemeVariant.Spring,     "theme_spring" },
        { ThemeVariant.Summer,     "theme_summer" },
        { ThemeVariant.Halloween,  "theme_halloween" },
        { ThemeVariant.Christmas,  "theme_christmas" }
    };
    
    // 已加载的资产缓存（按变体键缓存）
    private Dictionary<string, AsyncOperationHandle> _loadedAssets = new();
    
    private void Awake()
    {
        Instance = this;
        // 从存档读取用户设置
        LoadVariantSettings();
    }
    
    /// <summary>
    /// 加载指定变体的资产
    /// </summary>
    /// <param name="address">资产基础地址（不含变体后缀）</param>
    /// <param name="dimension">变体维度：quality/language/theme</param>
    public async Task<T> LoadVariantAsync<T>(string address, string dimension = "quality")
    {
        string variantLabel = GetCurrentLabel(dimension);
        string cacheKey = $"{address}:{variantLabel}";
        
        // 检查缓存
        if (_loadedAssets.TryGetValue(cacheKey, out var cachedHandle))
        {
            if (cachedHandle.IsValid() && cachedHandle.Status == AsyncOperationStatus.Succeeded)
            {
                return (T)cachedHandle.Result;
            }
        }
        
        // 构建带变体Label的加载键
        // Addressables会根据Label筛选出对应变体
        var handle = Addressables.LoadAssetAsync<T>(
            new AssetReferenceWithLabel(address, variantLabel));
        
        await handle.Task;
        
        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            _loadedAssets[cacheKey] = handle;
            return handle.Result;
        }
        
        // 回退到默认变体
        Debug.LogWarning($"[AssetVariant] 未找到变体 {variantLabel} 的资产 {address}，回退到默认");
        return await LoadDefaultAsync<T>(address);
    }
    
    private async Task<T> LoadDefaultAsync<T>(string address)
    {
        var handle = Addressables.LoadAssetAsync<T>(address);
        await handle.Task;
        return handle.Status == AsyncOperationStatus.Succeeded ? handle.Result : default;
    }
    
    /// <summary>
    /// 切换质量变体（会释放旧变体资产，加载新变体）
    /// </summary>
    public async Task SwitchQualityVariant(QualityVariant newQuality)
    {
        if (newQuality == _currentQuality) return;
        
        string oldLabel = QualityLabels[_currentQuality];
        string newLabel = QualityLabels[newQuality];
        
        Debug.Log($"[AssetVariant] 切换质量变体: {oldLabel} → {newLabel}");
        
        // 卸载旧变体的缓存
        var keysToRelease = new List<string>(_loadedAssets.Keys
            .Where(k => k.EndsWith($":{oldLabel}")));
        
        foreach (var key in keysToRelease)
        {
            Addressables.Release(_loadedAssets[key]);
            _loadedAssets.Remove(key);
        }
        
        _currentQuality = newQuality;
        
        // 通知UI等系统刷新资产
        OnVariantChanged?.Invoke("quality", newLabel);
        
        // 保存设置
        PlayerPrefs.SetInt("QualityVariant", (int)newQuality);
    }
    
    public System.Action<string, string> OnVariantChanged;
    
    private string GetCurrentLabel(string dimension)
    {
        return dimension switch
        {
            "quality"  => QualityLabels[_currentQuality],
            "language" => LanguageLabels[_currentLanguage],
            "theme"    => ThemeLabels[_currentTheme],
            _ => dimension
        };
    }
    
    private void LoadVariantSettings()
    {
        _currentQuality  = (QualityVariant)PlayerPrefs.GetInt("QualityVariant", (int)QualityVariant.High);
        _currentLanguage = (LanguageVariant)PlayerPrefs.GetInt("LanguageVariant", (int)LanguageVariant.Chinese);
        _currentTheme    = (ThemeVariant)PlayerPrefs.GetInt("ThemeVariant", (int)ThemeVariant.Default);
    }
    
    private void OnDestroy()
    {
        // 释放所有已加载资产
        foreach (var handle in _loadedAssets.Values)
        {
            if (handle.IsValid())
                Addressables.Release(handle);
        }
        _loadedAssets.Clear();
    }
}

// 辅助类：带Label的资产引用
public class AssetReferenceWithLabel : AssetReference
{
    private string _label;
    
    public AssetReferenceWithLabel(string address, string label) : base(address)
    {
        _label = label;
    }
}
```

### 3.3 自动刷新资产变体的UI组件

```csharp
using UnityEngine;
using UnityEngine.UI;
using System.Threading.Tasks;

/// <summary>
/// 支持变体的图片加载组件
/// 自动响应变体切换事件，重新加载对应变体的图片
/// </summary>
[RequireComponent(typeof(Image))]
public class VariantImage : MonoBehaviour
{
    [Tooltip("资产基础地址（不含变体标识）")]
    public string BaseAddress;
    
    [Tooltip("变体维度")]
    public string VariantDimension = "quality";
    
    private Image _image;
    private Sprite _currentSprite;
    
    private void Awake()
    {
        _image = GetComponent<Image>();
    }
    
    private async void Start()
    {
        await LoadVariantSprite();
        
        // 订阅变体切换事件
        if (AssetVariantManager.Instance != null)
        {
            AssetVariantManager.Instance.OnVariantChanged += OnVariantChanged;
        }
    }
    
    private async void OnVariantChanged(string dimension, string newLabel)
    {
        if (dimension == VariantDimension)
        {
            await LoadVariantSprite();
        }
    }
    
    private async Task LoadVariantSprite()
    {
        if (string.IsNullOrEmpty(BaseAddress)) return;
        
        var sprite = await AssetVariantManager.Instance
            .LoadVariantAsync<Sprite>(BaseAddress, VariantDimension);
        
        if (sprite != null)
        {
            _image.sprite = sprite;
            _currentSprite = sprite;
        }
    }
    
    private void OnDestroy()
    {
        if (AssetVariantManager.Instance != null)
        {
            AssetVariantManager.Instance.OnVariantChanged -= OnVariantChanged;
        }
    }
}
```

---

## 四、Bundle粒度设计策略

### 4.1 Bundle粒度对比

```
Bundle粒度策略对比：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
策略          | 优点                    | 缺点
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每资产一Bundle| 最精细热更、最小更新包  | Bundle数量爆炸（数千个）、
              |                         | 启动时请求数过多
──────────────────────────────────────────────────
按场景分Bundle| 场景加载清晰            | 跨场景共享资产重复打包风险
──────────────────────────────────────────────────
按类型分Bundle| 纹理/音频/Prefab分组   | 热更新粒度粗（改一张图要
              |                         | 更新整个纹理Bundle）
──────────────────────────────────────────────────
按模块分Bundle| 功能模块独立更新        | 需要仔细设计模块边界
（推荐）      | 依赖关系清晰            |
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 4.2 推荐的Bundle架构

```csharp
/*
推荐的Bundle分层架构：

Layer 1: 基础共享层（always cached，不热更）
├── core_framework.bundle    → 框架代码、基础Shader
├── common_textures.bundle   → 通用UI纹理、图标
└── audio_common.bundle      → 通用音效

Layer 2: 核心玩法层（启动时下载）
├── gameplay_core.bundle     → 核心玩法Prefab
├── characters_base.bundle   → 基础角色资产
└── scenes_lobby.bundle      → 大厅场景

Layer 3: 内容层（按需下载）
├── characters_hero_001.bundle
├── characters_hero_002.bundle
├── stage_001.bundle
├── stage_002.bundle
└── ...

Layer 4: 热更新层（差量更新）
├── config_tables.bundle     → 策划配置表
├── ui_skins.bundle          → UI皮肤
└── activity_assets.bundle   → 活动资产
*/

// 通过AddressableAssets Settings配置Bundle打包规则
// 以下是通过代码动态配置的示例（适用于CI/CD流水线）

#if UNITY_EDITOR
using UnityEditor.AddressableAssets;
using UnityEditor.AddressableAssets.Settings;
using UnityEditor.AddressableAssets.Settings.GroupSchemas;

public static class AddressablesBundleConfigurator
{
    [UnityEditor.MenuItem("Tools/Addressables/配置Bundle架构")]
    public static void ConfigureBundleArchitecture()
    {
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        
        // 配置共享层：防止资产重复打包
        ConfigureSharedGroup(settings);
        
        // 配置角色按模块打包
        ConfigureCharacterGroups(settings);
        
        Debug.Log("[Addressables] Bundle架构配置完成");
    }
    
    private static void ConfigureSharedGroup(AddressableAssetSettings settings)
    {
        // 创建或获取共享资产组
        var sharedGroup = settings.FindGroup("SharedAssets") 
            ?? settings.CreateGroup("SharedAssets", false, false, true, null,
                typeof(BundledAssetGroupSchema), typeof(ContentUpdateGroupSchema));
        
        // 配置为Pack Together（所有共享资产打入同一Bundle）
        var schema = sharedGroup.GetSchema<BundledAssetGroupSchema>();
        schema.BundleMode = BundledAssetGroupSchema.BundlePackingMode.PackTogether;
        schema.BundleNaming = BundledAssetGroupSchema.BundleNamingStyle.FileNameHash;
        
        // 设置为本地缓存（不通过CDN更新）
        schema.LoadPath.SetVariableByName(settings, AddressableAssetSettings.kLocalLoadPath);
        schema.BuildPath.SetVariableByName(settings, AddressableAssetSettings.kLocalBuildPath);
        
        Debug.Log($"[Addressables] 共享资产组已配置: {sharedGroup.Name}");
    }
    
    private static void ConfigureCharacterGroups(AddressableAssetSettings settings)
    {
        // 为每个角色创建独立的Bundle组（便于精细热更）
        string[] heroIds = { "hero_001", "hero_002", "hero_003" };
        
        foreach (string heroId in heroIds)
        {
            string groupName = $"Character_{heroId}";
            var group = settings.FindGroup(groupName)
                ?? settings.CreateGroup(groupName, false, false, true, null,
                    typeof(BundledAssetGroupSchema), typeof(ContentUpdateGroupSchema));
            
            var schema = group.GetSchema<BundledAssetGroupSchema>();
            schema.BundleMode = BundledAssetGroupSchema.BundlePackingMode.PackTogether;
            
            // 配置从CDN加载（支持热更）
            schema.LoadPath.SetVariableByName(settings, AddressableAssetSettings.kRemoteLoadPath);
            schema.BuildPath.SetVariableByName(settings, AddressableAssetSettings.kRemoteBuildPath);
        }
    }
}
#endif
```

### 4.3 依赖抽取：防止重复打包

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.AddressableAssets;
using System.Linq;

/// <summary>
/// 自动检测并修复重复打包问题
/// 将被多个Bundle引用的资产提取到共享Bundle中
/// </summary>
public static class DuplicateAssetFixer
{
    [UnityEditor.MenuItem("Tools/Addressables/自动修复重复打包")]
    public static void AutoFixDuplicates()
    {
        var analyzer = new AddressablesDependencyAnalyzer();
        analyzer.BuildDependencyGraph();
        
        var duplicates = analyzer.FindDuplicatedAssets(minReferenceCount: 2);
        var settings = AddressableAssetSettingsDefaultObject.Settings;
        
        // 获取或创建共享资产组
        var sharedGroup = settings.FindGroup("SharedAssets_Auto")
            ?? settings.CreateGroup("SharedAssets_Auto", false, false, true, null,
                typeof(BundledAssetGroupSchema));
        
        int fixedCount = 0;
        long savedBytes = 0;
        
        foreach (var dupNode in duplicates)
        {
            // 只处理纹理、材质等美术资产，跳过代码脚本
            string ext = System.IO.Path.GetExtension(dupNode.AssetPath).ToLower();
            if (ext is not (".png" or ".jpg" or ".tga" or ".mat" or ".fbx" or ".wav" or ".ogg"))
                continue;
            
            // 将重复资产设为Addressable并加入共享组
            var entry = settings.CreateOrMoveEntry(
                AssetDatabase.AssetPathToGUID(dupNode.AssetPath),
                sharedGroup);
            
            if (entry != null)
            {
                entry.address = dupNode.AssetPath; // 使用路径作为Address
                fixedCount++;
                savedBytes += dupNode.FileSizeBytes * (dupNode.Dependents.Count - 1);
                
                Debug.Log($"[DuplicateFixer] 已提取: {System.IO.Path.GetFileName(dupNode.AssetPath)} " +
                         $"（节省 {dupNode.FileSizeBytes / 1024f:F1}KB × {dupNode.Dependents.Count - 1} 份）");
            }
        }
        
        AssetDatabase.SaveAssets();
        Debug.Log($"[DuplicateFixer] 修复完成 | 处理资产: {fixedCount} 个 | " +
                 $"预计节省包体: {savedBytes / (1024f * 1024f):F2} MB");
    }
}
#endif
```

---

## 五、运行时预加载与引用计数管理

### 5.1 智能预加载策略

```csharp
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
using System.Collections.Generic;
using System.Threading.Tasks;

/// <summary>
/// Addressables引用计数管理器
/// 防止重复加载同一资产，并在引用归零时自动卸载
/// </summary>
public class AddressablesRefCounter
{
    private class RefEntry
    {
        public AsyncOperationHandle Handle;
        public int RefCount;
        public float LastAccessTime;
    }
    
    private Dictionary<string, RefEntry> _entries = new();
    private const float UnloadDelay = 30f; // 引用归零后30秒才真正卸载
    
    public async Task<T> AcquireAsync<T>(string address)
    {
        if (!_entries.TryGetValue(address, out var entry))
        {
            // 首次加载
            var handle = Addressables.LoadAssetAsync<T>(address);
            await handle.Task;
            
            if (handle.Status != AsyncOperationStatus.Succeeded)
            {
                Debug.LogError($"[RefCounter] 加载失败: {address}");
                return default;
            }
            
            entry = new RefEntry { Handle = handle, RefCount = 0 };
            _entries[address] = entry;
        }
        
        entry.RefCount++;
        entry.LastAccessTime = Time.realtimeSinceStartup;
        
        return (T)entry.Handle.Result;
    }
    
    public void Release(string address)
    {
        if (!_entries.TryGetValue(address, out var entry))
        {
            Debug.LogWarning($"[RefCounter] 尝试释放未加载的资产: {address}");
            return;
        }
        
        entry.RefCount = Mathf.Max(0, entry.RefCount - 1);
        entry.LastAccessTime = Time.realtimeSinceStartup;
        
        // 引用归零时记录时间，由GC协程延迟卸载
        if (entry.RefCount == 0)
        {
            Debug.Log($"[RefCounter] 引用归零: {address}，{UnloadDelay}s后卸载");
        }
    }
    
    /// <summary>
    /// 定期调用（如每30秒），清理引用归零且超时的资产
    /// </summary>
    public void CollectGarbage()
    {
        float currentTime = Time.realtimeSinceStartup;
        var toRemove = new List<string>();
        
        foreach (var kvp in _entries)
        {
            if (kvp.Value.RefCount == 0 && 
                currentTime - kvp.Value.LastAccessTime > UnloadDelay)
            {
                Addressables.Release(kvp.Value.Handle);
                toRemove.Add(kvp.Key);
                Debug.Log($"[RefCounter] 已卸载: {kvp.Key}");
            }
        }
        
        foreach (var key in toRemove)
            _entries.Remove(key);
    }
    
    /// <summary>
    /// 预加载资产组（进入场景前预热）
    /// </summary>
    public async Task PreloadGroupAsync(string label, System.IProgress<float> progress = null)
    {
        var locations = await Addressables.LoadResourceLocationsAsync(label).Task;
        
        if (locations == null || locations.Count == 0)
        {
            Debug.LogWarning($"[RefCounter] 未找到Label为 {label} 的资产");
            return;
        }
        
        int total = locations.Count;
        int loaded = 0;
        
        var tasks = new List<Task>();
        foreach (var loc in locations)
        {
            // 并发预加载，限制最大并发数
            if (tasks.Count >= 5)
            {
                await Task.WhenAny(tasks);
                tasks.RemoveAll(t => t.IsCompleted);
            }
            
            var address = loc.PrimaryKey;
            tasks.Add(Task.Run(async () =>
            {
                await AcquireAsync<Object>(address);
                loaded++;
                progress?.Report((float)loaded / total);
            }));
        }
        
        await Task.WhenAll(tasks);
        Debug.Log($"[RefCounter] 预加载完成: {label} | 共 {total} 个资产");
    }
}
```

---

## 六、最佳实践总结

### 6.1 Addressables资产管理核心原则

```
原则1：每个资产的归属Bundle必须明确
  ✅ 每个美术资产都应属于某个明确的Group
  ❌ 避免让资产隐式地被多个Bundle重复打包

原则2：共享资产单独提取
  ✅ 被2个以上Bundle引用的资产 → 移入SharedAssets Group
  ✅ 定期运行依赖分析器检查重复

原则3：Bundle粒度与热更新粒度匹配
  ✅ 需要频繁热更的内容 → 独立Bundle（如活动资产）
  ✅ 稳定不变的基础资产 → 合并Bundle（减少启动请求数）

原则4：始终配对 Acquire/Release
  ✅ 使用引用计数管理器，避免手动调用Addressables.Release
  ✅ 在MonoBehaviour.OnDestroy中释放资产引用

原则5：变体资产用Label区分，不用不同Address
  ✅ character_texture [label:quality_high]
  ✅ character_texture [label:quality_low]
  ❌ character_texture_hd / character_texture_sd（两个不同Address）
```

### 6.2 常见问题排查

| 问题 | 排查方法 | 解决方案 |
|------|----------|----------|
| Bundle包体异常大 | 运行依赖分析器，查找重复资产 | 将共享资产提取到SharedAssets Group |
| 加载某资产时卡顿 | 检查依赖链深度（依赖的依赖） | 预加载依赖Bundle，或拆分超深依赖链 |
| 热更新后资产仍旧版 | 检查Content State文件是否更新 | 确保Build时更新了catalog.json |
| 内存不断增长 | 检查是否有未Release的Handle | 使用引用计数管理器统一管理生命周期 |
| 变体切换后资产不刷新 | 检查OnVariantChanged事件订阅 | 确保UI组件在Start中订阅事件 |

通过本文的完整方案，团队可以建立一套从依赖分析、Bundle设计、变体管理到运行时引用计数的完整Addressables资产管理体系，显著降低包体大小、提升加载性能，并支持灵活的运行时内容切换。
