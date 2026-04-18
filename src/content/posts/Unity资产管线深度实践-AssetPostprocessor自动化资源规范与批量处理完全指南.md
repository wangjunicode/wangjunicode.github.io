---
title: Unity资产管线深度实践：AssetPostprocessor自动化资源规范与批量处理完全指南
published: 2026-04-18
description: 深度剖析Unity资产管线机制，通过AssetPostprocessor实现纹理压缩格式自动设置、模型导入规范化、音频配置标准化等自动化流程，结合AssetImporter API与自定义资产规则引擎，构建企业级资源管理体系。
tags: [Unity, 资产管线, AssetPostprocessor, 资源管理, 自动化]
category: 工具链与工程化
draft: false
---

# Unity资产管线深度实践：AssetPostprocessor自动化资源规范与批量处理完全指南

## 一、为什么需要资产管线自动化？

在中大型游戏项目中，美术资产的规范化管理是影响项目质量和包体大小的核心因素之一。常见的痛点包括：

- **纹理压缩格式不统一**：Android端某张UI图被设置为RGBA32，导致内存暴涨
- **模型顶点数超标**：美术导入时Read/Write Enable未关闭，内存翻倍
- **音频格式混乱**：背景音乐被设置为Decompress On Load，加载时占用大量内存
- **Mipmap滥用**：2D UI纹理开启了Mipmap，白白浪费显存

手动规范靠Code Review很难兜底，而`AssetPostprocessor`正是Unity官方提供的自动化解决方案。

---

## 二、AssetPostprocessor 核心机制

### 2.1 什么是 AssetPostprocessor

`AssetPostprocessor`是Unity Editor提供的编辑器扩展类，当资产被导入时，Unity会自动调用该类的回调方法，允许开发者在导入流程中插入自定义逻辑。

```
资产文件放入Project → Unity检测到变化 → ImportAsset流程
    → AssetPostprocessor.OnPreprocess*() 【导入前】
    → Unity默认导入器处理
    → AssetPostprocessor.OnPostprocess*() 【导入后】
    → 资产写入Library缓存
```

### 2.2 主要回调方法

| 方法 | 触发时机 | 典型用途 |
|------|----------|----------|
| `OnPreprocessTexture()` | 纹理导入前 | 设置压缩格式、Mipmap |
| `OnPostprocessTexture(Texture2D)` | 纹理导入后 | 二次处理像素数据 |
| `OnPreprocessModel()` | 模型导入前 | 设置导入参数 |
| `OnPostprocessModel(GameObject)` | 模型导入后 | 修改网格数据 |
| `OnPreprocessAudio()` | 音频导入前 | 设置压缩格式 |
| `OnPostprocessAudio(AudioClip)` | 音频导入后 | 分析音频数据 |
| `OnPreprocessAnimation()` | 动画导入前 | 设置动画压缩 |
| `OnPostprocessAllAssets(...)` | 所有资产处理完后 | 全量资产分析 |

---

## 三、纹理自动化规范系统

### 3.1 路径约定驱动的纹理规则

通过资产路径来区分资产类型，是最简洁高效的规则定义方式：

```
Assets/Art/UI/          → UI纹理：RGBA Compressed ASTC 4x4（不含Mipmap）
Assets/Art/Characters/  → 角色纹理：ASTC 4x4（含Mipmap）
Assets/Art/Terrain/     → 地形纹理：ASTC 6x6（节省显存）
Assets/Art/FX/          → 特效纹理：ASTC 4x4（不含Mipmap）
```

### 3.2 完整纹理后处理器实现

```csharp
using UnityEditor;
using UnityEngine;
using System.IO;

/// <summary>
/// 纹理资产自动化规范处理器
/// 根据资产路径自动设置压缩格式、Mipmap、最大尺寸等参数
/// </summary>
public class TextureAssetPostprocessor : AssetPostprocessor
{
    // 路径规则配置表（优先级从高到低）
    private static readonly TextureRule[] Rules = new TextureRule[]
    {
        new TextureRule
        {
            PathContains = "Assets/Art/UI/",
            MaxSize = 1024,
            GenerateMipMaps = false,
            AndroidFormat = TextureImporterFormat.ASTC_4x4,
            IOSFormat = TextureImporterFormat.ASTC_4x4,
            PCFormat = TextureImporterFormat.DXT5,
            WrapMode = TextureWrapMode.Clamp,
            FilterMode = FilterMode.Bilinear,
        },
        new TextureRule
        {
            PathContains = "Assets/Art/Characters/",
            MaxSize = 2048,
            GenerateMipMaps = true,
            AndroidFormat = TextureImporterFormat.ASTC_4x4,
            IOSFormat = TextureImporterFormat.ASTC_4x4,
            PCFormat = TextureImporterFormat.DXT5,
            WrapMode = TextureWrapMode.Repeat,
            FilterMode = FilterMode.Trilinear,
        },
        new TextureRule
        {
            PathContains = "Assets/Art/Terrain/",
            MaxSize = 2048,
            GenerateMipMaps = true,
            AndroidFormat = TextureImporterFormat.ASTC_6x6,
            IOSFormat = TextureImporterFormat.ASTC_6x6,
            PCFormat = TextureImporterFormat.DXT1,
            WrapMode = TextureWrapMode.Repeat,
            FilterMode = FilterMode.Trilinear,
        },
        new TextureRule
        {
            PathContains = "Assets/Art/FX/",
            MaxSize = 512,
            GenerateMipMaps = false,
            AndroidFormat = TextureImporterFormat.ASTC_4x4,
            IOSFormat = TextureImporterFormat.ASTC_4x4,
            PCFormat = TextureImporterFormat.DXT5,
            WrapMode = TextureWrapMode.Clamp,
            FilterMode = FilterMode.Bilinear,
        },
    };

    void OnPreprocessTexture()
    {
        // 跳过PackageCache和内置资源
        if (assetPath.Contains("PackageCache") || assetPath.Contains("com.unity"))
            return;

        TextureImporter importer = (TextureImporter)assetImporter;
        TextureRule rule = FindMatchingRule(assetPath);
        
        if (rule == null) return;

        // ---- 基础参数 ----
        importer.maxTextureSize = rule.MaxSize;
        importer.mipmapEnabled = rule.GenerateMipMaps;
        importer.wrapMode = rule.WrapMode;
        importer.filterMode = rule.FilterMode;
        importer.isReadable = false; // 默认关闭Read/Write，节省内存
        importer.sRGBTexture = !assetPath.Contains("_N.") && !assetPath.Contains("_Normal"); // 法线图使用Linear

        // ---- Android平台设置 ----
        TextureImporterPlatformSettings androidSettings = importer.GetPlatformTextureSettings("Android");
        androidSettings.overridden = true;
        androidSettings.maxTextureSize = rule.MaxSize;
        androidSettings.format = rule.AndroidFormat;
        androidSettings.compressionQuality = (int)TextureCompressionQuality.Normal;
        importer.SetPlatformTextureSettings(androidSettings);

        // ---- iOS平台设置 ----
        TextureImporterPlatformSettings iosSettings = importer.GetPlatformTextureSettings("iPhone");
        iosSettings.overridden = true;
        iosSettings.maxTextureSize = rule.MaxSize;
        iosSettings.format = rule.IOSFormat;
        iosSettings.compressionQuality = (int)TextureCompressionQuality.Normal;
        importer.SetPlatformTextureSettings(iosSettings);

        // ---- PC平台设置（编辑器预览用） ----
        TextureImporterPlatformSettings pcSettings = importer.GetPlatformTextureSettings("Standalone");
        pcSettings.overridden = true;
        pcSettings.maxTextureSize = rule.MaxSize;
        pcSettings.format = rule.PCFormat;
        importer.SetPlatformTextureSettings(pcSettings);

        Debug.Log($"[TexturePostprocessor] 自动设置规范: {Path.GetFileName(assetPath)} → {rule.AndroidFormat}, MaxSize={rule.MaxSize}, Mipmap={rule.GenerateMipMaps}");
    }

    private TextureRule FindMatchingRule(string path)
    {
        foreach (var rule in Rules)
        {
            if (path.Contains(rule.PathContains))
                return rule;
        }
        return null;
    }

    private class TextureRule
    {
        public string PathContains;
        public int MaxSize;
        public bool GenerateMipMaps;
        public TextureImporterFormat AndroidFormat;
        public TextureImporterFormat IOSFormat;
        public TextureImporterFormat PCFormat;
        public TextureWrapMode WrapMode;
        public FilterMode FilterMode;
    }
}
```

---

## 四、模型导入自动化规范

### 4.1 模型导入的常见问题

| 问题 | 危害 | 自动化解法 |
|------|------|-----------|
| Read/Write Enable = true | 内存翻倍 | `OnPreprocessModel`关闭 |
| 未勾选Optimize Mesh | 渲染效率低 | 自动启用 |
| 骨骼导入包含所有骨骼 | 骨骼数量暴增 | 设置SkinWeights |
| 材质导入未分离 | 材质命名混乱 | 自动设置MaterialImportMode |

```csharp
/// <summary>
/// 模型资产自动化规范处理器
/// </summary>
public class ModelAssetPostprocessor : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        if (assetPath.Contains("PackageCache")) return;

        ModelImporter importer = (ModelImporter)assetImporter;

        // ---- 网格优化 ----
        importer.isReadable = false;              // 关闭Read/Write
        importer.optimizeMeshPolygons = true;     // 多边形优化
        importer.optimizeMeshVertices = true;     // 顶点优化
        importer.meshCompression = ModelImporterMeshCompression.Low; // 网格压缩

        // ---- 动画处理 ----
        bool isCharacter = assetPath.Contains("Characters") || assetPath.Contains("NPCs");
        if (!isCharacter)
        {
            // 非角色模型：关闭动画导入
            importer.animationType = ModelImporterAnimationType.None;
        }
        else
        {
            // 角色模型：使用人形骨骼，启用Optimize Game Objects
            importer.animationType = ModelImporterAnimationType.Human;
            importer.optimizeGameObjects = true;
            importer.skinWeights = ModelImporterSkinWeights.FourBones; // 最多4骨骼影响
        }

        // ---- 材质处理 ----
        // 模型本身不导入材质，由代码动态赋材质
        importer.materialImportMode = ModelImporterMaterialImportMode.None;

        // ---- 法线处理 ----
        // 如果模型有法线则导入，否则计算
        importer.importNormals = ModelImporterNormals.Import;
        importer.importTangents = isCharacter ? ModelImporterTangents.CalculateMikk : ModelImporterTangents.None;

        // ---- 碰撞体 ----
        importer.addCollider = false; // 不自动添加碰撞体

        // ---- 光照贴图 ----
        bool isEnvironment = assetPath.Contains("Environment") || assetPath.Contains("Scene");
        importer.generateSecondaryUV = isEnvironment; // 只有场景物件需要UV2用于光照贴图
    }

    /// <summary>
    /// 模型导入后：检查顶点数上限并发出警告
    /// </summary>
    void OnPostprocessModel(GameObject gameObject)
    {
        if (assetPath.Contains("PackageCache")) return;

        int totalVertices = 0;
        int totalTriangles = 0;

        foreach (MeshFilter mf in gameObject.GetComponentsInChildren<MeshFilter>())
        {
            if (mf.sharedMesh != null)
            {
                totalVertices += mf.sharedMesh.vertexCount;
                totalTriangles += mf.sharedMesh.triangles.Length / 3;
            }
        }

        foreach (SkinnedMeshRenderer smr in gameObject.GetComponentsInChildren<SkinnedMeshRenderer>())
        {
            if (smr.sharedMesh != null)
            {
                totalVertices += smr.sharedMesh.vertexCount;
                totalTriangles += smr.sharedMesh.triangles.Length / 3;
            }
        }

        // 超限警告阈值
        const int WARNING_VERTICES = 50000;
        const int ERROR_VERTICES = 100000;

        if (totalVertices > ERROR_VERTICES)
        {
            Debug.LogError($"[ModelPostprocessor] ❌ 模型顶点数严重超标！{gameObject.name}: {totalVertices} 顶点 (上限 {ERROR_VERTICES})");
        }
        else if (totalVertices > WARNING_VERTICES)
        {
            Debug.LogWarning($"[ModelPostprocessor] ⚠️ 模型顶点数偏高！{gameObject.name}: {totalVertices} 顶点 (建议 {WARNING_VERTICES} 以下)");
        }
    }
}
```

---

## 五、音频导入自动化规范

### 5.1 Unity音频导入模式对比

| Load Type | 内存占用 | CPU占用 | 适用场景 |
|-----------|----------|---------|----------|
| Decompress On Load | 高（原始PCM）| 低 | 短音效（<1MB） |
| Compressed In Memory | 中等 | 解码时较高 | 中等长度音效 |
| Streaming | 极低 | 持续IO | 背景音乐（BGM） |

```csharp
/// <summary>
/// 音频资产自动化规范处理器
/// </summary>
public class AudioAssetPostprocessor : AssetPostprocessor
{
    void OnPreprocessAudio()
    {
        if (assetPath.Contains("PackageCache")) return;

        AudioImporter importer = (AudioImporter)assetImporter;
        string fileName = Path.GetFileNameWithoutExtension(assetPath).ToLower();
        string path = assetPath.ToLower();

        AudioImporterSampleSettings settings = importer.defaultSampleSettings;

        // ---- 背景音乐（BGM）：流式加载 ----
        if (path.Contains("/bgm/") || path.Contains("/music/") || fileName.StartsWith("bgm_") || fileName.StartsWith("music_"))
        {
            settings.loadType = AudioClipLoadType.Streaming;
            settings.compressionFormat = AudioCompressionFormat.Vorbis;
            settings.quality = 0.5f; // Vorbis质量50%，平衡质量与体积
            settings.sampleRateSetting = AudioSampleRateSetting.OptimizeSampleRate;
        }
        // ---- 常用短音效：Compressed In Memory ----
        else if (path.Contains("/sfx/") || path.Contains("/sound/") || path.Contains("/effects/"))
        {
            settings.loadType = AudioClipLoadType.CompressedInMemory;
            settings.compressionFormat = AudioCompressionFormat.ADPCM; // ADPCM解码快
            settings.quality = 1.0f;
            settings.sampleRateSetting = AudioSampleRateSetting.PreserveSampleRate;
        }
        // ---- 极短音效（如按钮音）：Decompress On Load ----
        else if (path.Contains("/ui/") && path.Contains("audio"))
        {
            settings.loadType = AudioClipLoadType.DecompressOnLoad;
            settings.compressionFormat = AudioCompressionFormat.ADPCM;
        }
        else
        {
            // 默认：Compressed In Memory + Vorbis
            settings.loadType = AudioClipLoadType.CompressedInMemory;
            settings.compressionFormat = AudioCompressionFormat.Vorbis;
            settings.quality = 0.7f;
        }

        importer.defaultSampleSettings = settings;

        // 强制单声道（移动端节省内存）
        bool isBGM = path.Contains("/bgm/") || path.Contains("/music/");
        importer.forceToMono = !isBGM; // BGM保留立体声，音效强制单声道
        importer.loadInBackground = isBGM; // BGM后台加载

        Debug.Log($"[AudioPostprocessor] 自动设置: {Path.GetFileName(assetPath)} → {settings.loadType}, {settings.compressionFormat}, Mono={importer.forceToMono}");
    }
}
```

---

## 六、批量重新导入工具

当规则修改后，需要对历史资产进行批量重新导入。以下是一个完整的批量处理工具：

```csharp
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.IO;

/// <summary>
/// 资产规范批量修复工具
/// 菜单：Tools/AssetPipeline/重新导入规范化
/// </summary>
public class AssetReimportBatchTool : EditorWindow
{
    [MenuItem("Tools/AssetPipeline/资产规范批量修复工具")]
    public static void ShowWindow()
    {
        GetWindow<AssetReimportBatchTool>("资产规范批量修复");
    }

    private bool _reimportTextures = true;
    private bool _reimportModels = true;
    private bool _reimportAudios = true;
    private string _targetFolder = "Assets/Art";
    private bool _isRunning = false;
    private int _processedCount = 0;
    private int _totalCount = 0;

    void OnGUI()
    {
        GUILayout.Label("资产规范批量修复工具", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        _targetFolder = EditorGUILayout.TextField("目标目录", _targetFolder);
        EditorGUILayout.Space();

        _reimportTextures = EditorGUILayout.Toggle("重新导入纹理", _reimportTextures);
        _reimportModels = EditorGUILayout.Toggle("重新导入模型", _reimportModels);
        _reimportAudios = EditorGUILayout.Toggle("重新导入音频", _reimportAudios);

        EditorGUILayout.Space();

        if (_isRunning)
        {
            float progress = _totalCount > 0 ? (float)_processedCount / _totalCount : 0;
            EditorGUI.ProgressBar(EditorGUILayout.GetControlRect(), progress, $"{_processedCount}/{_totalCount}");
        }
        else
        {
            if (GUILayout.Button("开始批量修复", GUILayout.Height(40)))
            {
                RunBatchReimport();
            }
        }
    }

    private void RunBatchReimport()
    {
        List<string> assetPaths = new List<string>();
        string[] extensions = GetTargetExtensions();
        
        foreach (string ext in extensions)
        {
            string[] guids = AssetDatabase.FindAssets($"t:{GetTypeFilter(ext)}", new[] { _targetFolder });
            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                if (path.EndsWith(ext, System.StringComparison.OrdinalIgnoreCase))
                    assetPaths.Add(path);
            }
        }

        _totalCount = assetPaths.Count;
        _processedCount = 0;
        _isRunning = true;

        // 使用AssetDatabase.StartAssetEditing批量导入，减少磁盘IO
        AssetDatabase.StartAssetEditing();
        try
        {
            foreach (string path in assetPaths)
            {
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
                _processedCount++;

                // 每100个刷新一次UI
                if (_processedCount % 100 == 0)
                {
                    EditorUtility.DisplayProgressBar("批量重新导入", $"正在处理: {Path.GetFileName(path)}", (float)_processedCount / _totalCount);
                }
            }
        }
        finally
        {
            AssetDatabase.StopAssetEditing();
            AssetDatabase.Refresh();
            EditorUtility.ClearProgressBar();
            _isRunning = false;
        }

        Debug.Log($"[批量修复] 完成！共处理 {_processedCount} 个资产");
        EditorUtility.DisplayDialog("完成", $"批量修复完成，共处理 {_processedCount} 个资产", "确定");
    }

    private string[] GetTargetExtensions()
    {
        var exts = new List<string>();
        if (_reimportTextures) exts.AddRange(new[] { ".png", ".jpg", ".tga", ".psd", ".exr" });
        if (_reimportModels) exts.AddRange(new[] { ".fbx", ".obj", ".blend" });
        if (_reimportAudios) exts.AddRange(new[] { ".mp3", ".wav", ".ogg", ".aiff" });
        return exts.ToArray();
    }

    private string GetTypeFilter(string ext)
    {
        if (ext == ".png" || ext == ".jpg" || ext == ".tga" || ext == ".psd" || ext == ".exr") return "Texture2D";
        if (ext == ".fbx" || ext == ".obj" || ext == ".blend") return "Model";
        if (ext == ".mp3" || ext == ".wav" || ext == ".ogg" || ext == ".aiff") return "AudioClip";
        return "Object";
    }
}
```

---

## 七、资产规范检查报告工具

```csharp
/// <summary>
/// 资产规范性检查报告生成器
/// 扫描全项目资产并生成不合规资产清单
/// </summary>
public class AssetComplianceChecker : EditorWindow
{
    [MenuItem("Tools/AssetPipeline/规范检查报告")]
    public static void ShowWindow()
    {
        GetWindow<AssetComplianceChecker>("资产规范检查");
    }

    private Vector2 _scrollPos;
    private List<string> _violations = new List<string>();

    void OnGUI()
    {
        if (GUILayout.Button("扫描全项目", GUILayout.Height(30)))
        {
            RunCheck();
        }

        EditorGUILayout.LabelField($"发现 {_violations.Count} 处不合规资产：", EditorStyles.boldLabel);
        
        _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
        foreach (string v in _violations)
        {
            EditorGUILayout.HelpBox(v, MessageType.Warning);
        }
        EditorGUILayout.EndScrollView();
    }

    private void RunCheck()
    {
        _violations.Clear();

        // 检查纹理
        string[] texGuids = AssetDatabase.FindAssets("t:Texture2D", new[] { "Assets/Art" });
        foreach (string guid in texGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            TextureImporter ti = AssetImporter.GetAtPath(path) as TextureImporter;
            if (ti == null) continue;

            // 检查UI纹理是否开了Mipmap
            if (path.Contains("/UI/") && ti.mipmapEnabled)
                _violations.Add($"[纹理] UI图开启了Mipmap: {path}");

            // 检查是否开了Read/Write
            if (ti.isReadable)
                _violations.Add($"[纹理] Read/Write Enable已开启（内存翻倍）: {path}");

            // 检查Android平台设置
            var androidSettings = ti.GetPlatformTextureSettings("Android");
            if (!androidSettings.overridden)
                _violations.Add($"[纹理] Android平台压缩格式未设置（使用默认）: {path}");
        }

        // 检查模型
        string[] modelGuids = AssetDatabase.FindAssets("t:Model", new[] { "Assets/Art" });
        foreach (string guid in modelGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            ModelImporter mi = AssetImporter.GetAtPath(path) as ModelImporter;
            if (mi == null) continue;

            if (mi.isReadable)
                _violations.Add($"[模型] Read/Write Enable已开启: {path}");
            if (!mi.optimizeMeshPolygons)
                _violations.Add($"[模型] 未启用网格优化: {path}");
        }

        Debug.Log($"[规范检查] 完成，发现 {_violations.Count} 处不合规");
        Repaint();
    }
}
```

---

## 八、高级技巧：ScriptableObject配置驱动的规则引擎

对于规则频繁变化的团队，可以将规则提取到ScriptableObject中，策划也可以调整：

```csharp
[CreateAssetMenu(menuName = "AssetPipeline/纹理规则配置", fileName = "TextureRuleConfig")]
public class TextureRuleConfig : ScriptableObject
{
    public List<TextureRuleEntry> Rules = new List<TextureRuleEntry>();

    // 单例访问，从Resources加载
    private static TextureRuleConfig _instance;
    public static TextureRuleConfig Instance
    {
        get
        {
            if (_instance == null)
                _instance = Resources.Load<TextureRuleConfig>("TextureRuleConfig");
            return _instance;
        }
    }
}

[System.Serializable]
public class TextureRuleEntry
{
    [Header("路径匹配（支持通配符）")]
    public string PathPattern;

    [Header("纹理参数")]
    public int MaxSize = 1024;
    public bool GenerateMipMaps = false;
    public TextureWrapMode WrapMode = TextureWrapMode.Clamp;
    public FilterMode FilterMode = FilterMode.Bilinear;

    [Header("Android")]
    public TextureImporterFormat AndroidFormat = TextureImporterFormat.ASTC_4x4;

    [Header("iOS")]
    public TextureImporterFormat IOSFormat = TextureImporterFormat.ASTC_4x4;

    [Header("PC/编辑器")]
    public TextureImporterFormat PCFormat = TextureImporterFormat.DXT5;
}
```

---

## 九、最佳实践总结

### 9.1 命名与路径约定

```
Assets/Art/
├── UI/           → UI纹理（ASTC 4x4, 无Mipmap, Clamp）
├── Characters/   → 角色纹理（ASTC 4x4, 有Mipmap）
├── Environment/  → 场景纹理（ASTC 6x6, 有Mipmap, UV2）
├── FX/           → 特效纹理（ASTC 4x4, 无Mipmap）
├── Terrain/      → 地形纹理（ASTC 6x6）
Audio/
├── BGM/          → 背景音乐（Streaming, Vorbis, 立体声）
├── SFX/          → 音效（CompressedInMemory, ADPCM, 单声道）
└── UI/           → UI音效（DecompressOnLoad, ADPCM）
```

### 9.2 性能优化要点

1. **批量导入用`AssetDatabase.StartAssetEditing()`包裹**：避免每次导入都触发全量刷新
2. **`OnPreprocessTexture`比`OnPostprocessTexture`更高效**：前者在生成前设置，避免重复压缩
3. **规则匹配用字符串Contains而非Regex**：导入时调用频率极高，正则开销不可忽视
4. **避免在Postprocessor中调用`AssetDatabase.Refresh()`**：会触发递归导入循环

### 9.3 团队协作规范

| 规范项 | 说明 |
|--------|------|
| Postprocessor代码纳入版本控制 | 确保所有人环境一致 |
| 规则变更需写CHANGELOG | 记录哪些资产受影响 |
| 新美术资产先放入规范目录 | 导入时自动应用规则 |
| CI/CD中加入合规检查步骤 | 发布前扫描不合规资产 |
| 新同学入职必读规范文档 | 减少返工成本 |

### 9.4 常见陷阱

```csharp
// ❌ 错误：在Postprocessor中直接修改资产会触发无限循环
void OnPostprocessTexture(Texture2D texture)
{
    // 不要在这里调用AssetDatabase.ImportAsset(assetPath)！
}

// ✅ 正确：使用EditorApplication.delayCall延迟执行
void OnPostprocessTexture(Texture2D texture)
{
    string path = assetPath; // 捕获路径
    EditorApplication.delayCall += () =>
    {
        AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
    };
}
```

---

## 十、总结

Unity资产管线自动化是大型项目工程化的基石。通过`AssetPostprocessor`实现：

- **纹理规范**：根据路径自动设置ASTC压缩、Mipmap、最大尺寸
- **模型规范**：自动关闭Read/Write、启用Mesh优化、设置LOD
- **音频规范**：根据类型自动选择Streaming/Compressed模式

配合批量重新导入工具和合规检查报告，可以从根源上解决资产规范问题，每个月为团队节省数十小时的返工成本，并保持包体和内存的持续可控。
