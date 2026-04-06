---
title: 游戏包体优化与安装包瘦身完全指南：从APK/IPA到云端分发
published: 2026-04-03
description: 深度解析游戏安装包体积优化全链路，涵盖资源压缩、代码裁剪、纹理格式优化、AssetBundle分包、OBB/ODR云端分发等核心技术，帮助游戏从500MB瘦身到100MB以内
tags: [包体优化, Unity, 安装包, 资源压缩, AssetBundle, 移动端]
category: 性能优化
draft: false
encryptedKey: henhaoji123
---

# 游戏包体优化与安装包瘦身完全指南：从APK/IPA到云端分发

## 1. 为什么包体大小如此重要

在移动游戏市场，包体大小直接影响下载转化率。Google Play 数据表明：

- 包体每增加 6MB，安装转化率下降约 1%
- 超过 100MB 的 APK 需要 WiFi 才能下载（部分运营商限制）
- iOS 通过蜂窝网络下载限制为 200MB（随版本调整）
- 包体越小，用户留存率越高，特别是在网络条件较差的地区

典型优化目标：

| 游戏类型 | 理想包体 | 可接受包体 |
|---------|---------|---------|
| 超休闲游戏 | < 30MB | < 50MB |
| 休闲游戏 | < 60MB | < 100MB |
| 中度游戏 | < 100MB | < 200MB |
| 重度游戏 | < 200MB | < 500MB |

---

## 2. 包体构成分析

### 2.1 典型包体组成

```
APK结构分析（以200MB游戏为例）：
├── assets/（AssetBundle资源）     ~120MB (60%)
│   ├── 纹理资源                   ~70MB
│   ├── 音频资源                   ~30MB
│   └── 其他资源                   ~20MB
├── lib/（原生库）                   ~25MB (12.5%)
│   ├── libil2cpp.so                ~20MB
│   └── libUnity.so                  ~5MB
├── classes.dex（托管代码）          ~15MB (7.5%)
├── res/（Android原生资源）           ~5MB (2.5%)
└── META-INF + 其他                 ~35MB (17.5%)
```

### 2.2 快速包体分析工具

```csharp
// Editor工具：包体分析器
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.IO;
using System.Linq;

public class PackageSizeAnalyzer : EditorWindow
{
    private Dictionary<string, long> _assetSizes = new();
    private Vector2 _scrollPos;
    private string _searchFilter = "";
    private SortMode _sortMode = SortMode.SizeDesc;

    public enum SortMode { SizeDesc, SizeAsc, Name }

    [MenuItem("Tools/包体优化/包体分析器")]
    public static void ShowWindow()
    {
        GetWindow<PackageSizeAnalyzer>("包体分析器");
    }

    private void OnGUI()
    {
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("扫描资源", GUILayout.Width(100)))
            ScanAssets();
        _searchFilter = EditorGUILayout.TextField("搜索：", _searchFilter);
        _sortMode = (SortMode)EditorGUILayout.EnumPopup("排序：", _sortMode);
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.LabelField($"总计：{_assetSizes.Count} 个资源，" +
            $"大小：{FormatSize(_assetSizes.Values.Sum())}");

        var filtered = FilterAndSort();
        _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
        
        foreach (var kv in filtered)
        {
            EditorGUILayout.BeginHorizontal();
            var style = GetSizeStyle(kv.Value);
            EditorGUILayout.LabelField($"[{FormatSize(kv.Value)}]", style, GUILayout.Width(80));
            
            var asset = AssetDatabase.LoadAssetAtPath<Object>(kv.Key);
            EditorGUILayout.ObjectField(asset, typeof(Object), false);
            EditorGUILayout.EndHorizontal();
        }
        
        EditorGUILayout.EndScrollView();
    }

    private void ScanAssets()
    {
        _assetSizes.Clear();
        string[] allAssets = AssetDatabase.GetAllAssetPaths();
        
        foreach (var path in allAssets)
        {
            if (!path.StartsWith("Assets/")) continue;
            
            string fullPath = Path.GetFullPath(path);
            if (!File.Exists(fullPath)) continue;
            
            long size = new FileInfo(fullPath).Length;
            _assetSizes[path] = size;
        }
        
        Debug.Log($"扫描完成，共 {_assetSizes.Count} 个资源");
    }

    private IEnumerable<KeyValuePair<string, long>> FilterAndSort()
    {
        var filtered = _assetSizes.AsEnumerable();
        
        if (!string.IsNullOrEmpty(_searchFilter))
            filtered = filtered.Where(kv => kv.Key.Contains(_searchFilter));

        return _sortMode switch
        {
            SortMode.SizeDesc => filtered.OrderByDescending(kv => kv.Value),
            SortMode.SizeAsc  => filtered.OrderBy(kv => kv.Value),
            SortMode.Name     => filtered.OrderBy(kv => kv.Key),
            _ => filtered
        };
    }

    private GUIStyle GetSizeStyle(long size)
    {
        var style = new GUIStyle(EditorStyles.label);
        style.normal.textColor = size switch
        {
            > 10 * 1024 * 1024 => Color.red,    // >10MB
            > 1 * 1024 * 1024  => Color.yellow, // >1MB
            _                  => Color.white
        };
        return style;
    }

    private string FormatSize(long bytes)
    {
        if (bytes >= 1024 * 1024) return $"{bytes / 1024f / 1024f:F2}MB";
        if (bytes >= 1024) return $"{bytes / 1024f:F1}KB";
        return $"{bytes}B";
    }
}
```

---

## 3. 纹理压缩优化

纹理通常占包体的 50-70%，是优化的重中之重。

### 3.1 压缩格式选择

```
平台压缩格式最佳实践：

Android:
  ASTC 6x6  → 高质量，现代设备（推荐）
  ETC2      → 兼容性最好，OpenGL ES 3.0+
  ETC1      → 老设备，不支持Alpha通道

iOS:
  ASTC 6x6  → A8芯片以上推荐
  PVRTC4    → 老设备，需要POT纹理
  ASTC 4x4  → 最高质量（尺寸较大）

压缩比对比（1024x1024 RGBA图）：
  未压缩(RGBA32)：4MB
  ASTC 4x4      ：1MB（4:1）
  ASTC 6x6      ：0.44MB（9:1）
  ASTC 8x8      ：0.25MB（16:1）
  ETC2          ：0.5MB（8:1）
```

### 3.2 批量纹理优化工具

```csharp
// 批量设置纹理压缩格式
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;

public class TextureCompressBatchProcessor : EditorWindow
{
    private TextureImporterFormat _androidFormat = TextureImporterFormat.ASTC_6x6;
    private TextureImporterFormat _iosFormat = TextureImporterFormat.ASTC_6x6;
    private int _maxTextureSize = 1024;
    private bool _generateMipMaps = true;
    private string _targetFolder = "Assets/Textures";

    [MenuItem("Tools/包体优化/批量纹理压缩")]
    public static void ShowWindow()
    {
        GetWindow<TextureCompressBatchProcessor>("批量纹理压缩");
    }

    private void OnGUI()
    {
        EditorGUILayout.LabelField("批量纹理压缩设置", EditorStyles.boldLabel);
        
        _targetFolder = EditorGUILayout.TextField("目标文件夹：", _targetFolder);
        _androidFormat = (TextureImporterFormat)EditorGUILayout.EnumPopup("Android格式：", _androidFormat);
        _iosFormat = (TextureImporterFormat)EditorGUILayout.EnumPopup("iOS格式：", _iosFormat);
        _maxTextureSize = EditorGUILayout.IntPopup("最大尺寸：", _maxTextureSize,
            new[] { "256", "512", "1024", "2048" },
            new[] { 256, 512, 1024, 2048 });
        _generateMipMaps = EditorGUILayout.Toggle("生成MipMaps：", _generateMipMaps);

        EditorGUILayout.Space();
        if (GUILayout.Button("开始批量压缩"))
            BatchCompress();

        if (GUILayout.Button("分析潜在节省空间"))
            AnalyzePotentialSavings();
    }

    private void BatchCompress()
    {
        string[] texturePaths = AssetDatabase.FindAssets("t:Texture2D", new[] { _targetFolder });
        int processed = 0;

        try
        {
            foreach (string guid in texturePaths)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                EditorUtility.DisplayProgressBar("处理中...", path, (float)processed / texturePaths.Length);
                
                ProcessTexture(path);
                processed++;
            }
        }
        finally
        {
            EditorUtility.ClearProgressBar();
            AssetDatabase.Refresh();
        }

        Debug.Log($"完成！处理了 {processed} 个纹理");
    }

    private void ProcessTexture(string path)
    {
        var importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer == null) return;

        bool changed = false;

        // 设置最大尺寸
        if (importer.maxTextureSize > _maxTextureSize)
        {
            importer.maxTextureSize = _maxTextureSize;
            changed = true;
        }

        // MipMap
        if (importer.mipmapEnabled != _generateMipMaps)
        {
            importer.mipmapEnabled = _generateMipMaps;
            changed = true;
        }

        // Android格式
        var androidSettings = importer.GetPlatformTextureSettings("Android");
        if (androidSettings.format != _androidFormat)
        {
            androidSettings.overridden = true;
            androidSettings.format = _androidFormat;
            importer.SetPlatformTextureSettings(androidSettings);
            changed = true;
        }

        // iOS格式
        var iosSettings = importer.GetPlatformTextureSettings("iPhone");
        if (iosSettings.format != _iosFormat)
        {
            iosSettings.overridden = true;
            iosSettings.format = _iosFormat;
            importer.SetPlatformTextureSettings(iosSettings);
            changed = true;
        }

        if (changed)
            importer.SaveAndReimport();
    }

    private void AnalyzePotentialSavings()
    {
        string[] texturePaths = AssetDatabase.FindAssets("t:Texture2D", new[] { _targetFolder });
        long totalSaved = 0;

        foreach (string guid in texturePaths)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;

            // 模拟计算节省
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (tex == null) continue;

            long currentSize = (long)tex.width * tex.height * 4; // 假设RGBA32
            long compressedSize = (long)tex.width * tex.height / 4; // 假设8:1压缩
            totalSaved += currentSize - compressedSize;
        }

        Debug.Log($"预计可节省：{totalSaved / 1024f / 1024f:F2}MB");
    }
}
```

### 3.3 图集优化策略

```csharp
// 图集自动打包配置
[CreateAssetMenu(menuName = "Tools/AtlasConfig")]
public class AtlasConfig : ScriptableObject
{
    [Header("图集设置")]
    public string atlasName;
    public string[] folderPaths;
    public int maxAtlasSize = 2048;
    public bool allowRotation = false;
    public bool tightPacking = true;
    
    [Header("压缩设置")]
    public bool enableAndroidCompression = true;
    public bool enableIOSCompression = true;
}

// 使用Unity Sprite Atlas API自动配置
using UnityEditor;
using UnityEditor.U2D;
using UnityEngine.U2D;

public static class AtlasAutoBuilder
{
    [MenuItem("Tools/包体优化/重建所有图集")]
    public static void RebuildAllAtlases()
    {
        string[] atlasPaths = AssetDatabase.FindAssets("t:SpriteAtlas");
        
        foreach (string guid in atlasPaths)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var atlas = AssetDatabase.LoadAssetAtPath<SpriteAtlas>(path);
            
            // 获取图集设置
            var settings = atlas.GetTextureSettings();
            settings.generateMipMaps = false; // UI图集不需要MipMap
            atlas.SetTextureSettings(settings);

            // 设置压缩
            var androidPlatform = atlas.GetPlatformSettings("Android");
            androidPlatform.overridden = true;
            androidPlatform.format = TextureImporterFormat.ASTC_6x6;
            androidPlatform.maxTextureSize = 2048;
            atlas.SetPlatformSettings(androidPlatform);

            var iosPlatform = atlas.GetPlatformSettings("iPhone");
            iosPlatform.overridden = true;
            iosPlatform.format = TextureImporterFormat.ASTC_6x6;
            iosPlatform.maxTextureSize = 2048;
            atlas.SetPlatformSettings(iosPlatform);
        }

        SpriteAtlasUtility.PackAllAtlases(EditorUserBuildSettings.activeBuildTarget);
        Debug.Log("所有图集已重建");
    }
}
```

---

## 4. 音频压缩优化

### 4.1 音频格式策略

```
音频压缩最佳实践：

背景音乐(BGM)：
  格式：Vorbis (OGG) @ Quality 70-80
  加载：Streaming（流式）
  通道：Stereo → 考虑降为Mono（节省50%）
  
音效(SFX)：
  格式：ADPCM（小文件优先）或 Vorbis
  加载：DecompressOnLoad（内存解压）
  通道：短音效用Mono

语音(Voice)：
  格式：Vorbis @ Quality 60-70
  加载：CompressedInMemory

压缩比参考：
  WAV 44100Hz Stereo 1分钟 ≈ 10MB
  Vorbis Quality 70        ≈ 0.8MB（12:1）
  ADPCM                    ≈ 2.5MB（4:1）
```

### 4.2 音频批量优化

```csharp
using UnityEditor;
using UnityEngine;
using System.Linq;

public class AudioOptimizer : EditorWindow
{
    [MenuItem("Tools/包体优化/音频优化")]
    public static void ShowWindow()
    {
        GetWindow<AudioOptimizer>("音频优化");
    }

    [MenuItem("Tools/包体优化/一键优化所有音频")]
    public static void OptimizeAllAudio()
    {
        string[] audioPaths = AssetDatabase.FindAssets("t:AudioClip");
        int optimized = 0;

        foreach (string guid in audioPaths)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            if (!path.StartsWith("Assets/")) continue;
            
            var importer = AssetImporter.GetAtPath(path) as AudioImporter;
            if (importer == null) continue;

            var defaultSettings = importer.defaultSampleSettings;
            bool changed = false;

            // 根据文件长度选择策略
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(path);
            bool isLong = clip != null && clip.length > 10f; // 超过10秒视为BGM

            if (isLong)
            {
                // BGM：流式 + Vorbis
                if (defaultSettings.loadType != AudioClipLoadType.Streaming)
                {
                    defaultSettings.loadType = AudioClipLoadType.Streaming;
                    changed = true;
                }
                if (defaultSettings.compressionFormat != AudioCompressionFormat.Vorbis)
                {
                    defaultSettings.compressionFormat = AudioCompressionFormat.Vorbis;
                    defaultSettings.quality = 0.7f;
                    changed = true;
                }
                // BGM强制单声道（可选，需评估音质）
                // importer.forceToMono = true;
            }
            else
            {
                // SFX：内存解压 + ADPCM
                if (defaultSettings.loadType != AudioClipLoadType.DecompressOnLoad)
                {
                    defaultSettings.loadType = AudioClipLoadType.DecompressOnLoad;
                    changed = true;
                }
                if (defaultSettings.compressionFormat != AudioCompressionFormat.ADPCM)
                {
                    defaultSettings.compressionFormat = AudioCompressionFormat.ADPCM;
                    changed = true;
                }
            }

            if (changed)
            {
                importer.defaultSampleSettings = defaultSettings;
                importer.SaveAndReimport();
                optimized++;
            }
        }

        Debug.Log($"音频优化完成，共优化 {optimized} 个音频文件");
    }
}
```

---

## 5. 代码裁剪与IL2CPP优化

### 5.1 Managed Stripping（托管代码裁剪）

```xml
<!-- Assets/link.xml - 保护不被裁剪的类型 -->
<linker>
  <!-- 保留整个程序集 -->
  <assembly fullname="UnityEngine" preserve="all"/>
  
  <!-- 保留特定命名空间 -->
  <assembly fullname="Assembly-CSharp">
    <namespace fullname="MyGame.Core" preserve="all"/>
    
    <!-- 保留特定类型 -->
    <type fullname="MyGame.Network.NetworkManager" preserve="all"/>
    
    <!-- 保留类型的特定成员 -->
    <type fullname="MyGame.Data.SaveData">
      <method name="OnDeserialize"/>
      <field name="playerLevel"/>
    </type>
  </assembly>
  
  <!-- 反射使用的类型必须保留 -->
  <assembly fullname="Newtonsoft.Json" preserve="all"/>
</linker>
```

```csharp
// 在Player Settings中配置裁剪级别
// Build Settings → Player Settings → Other Settings → Managed Stripping Level
// 
// None     → 不裁剪（包体最大，兼容性最好）
// Minimal  → 裁剪未使用的程序集
// Low      → 保守裁剪（推荐生产环境）
// Medium   → 中等裁剪
// High     → 激进裁剪（需充分测试）

// 使用Editor脚本强制设置
using UnityEditor;

public static class BuildConfig
{
    [MenuItem("Build/设置裁剪级别-高")]
    public static void SetHighStripping()
    {
        PlayerSettings.stripEngineCode = true;
        // Unity 2020+
#if UNITY_2020_1_OR_NEWER
        PlayerSettings.managedStrippingLevel = ManagedStrippingLevel.High;
#endif
        Debug.Log("已设置高级代码裁剪");
    }
}
```

### 5.2 IL2CPP编译优化

```
IL2CPP优化配置（Player Settings）：

C++ Compiler Configuration:
  Debug   → 最大包体，包含调试信息
  Release → 标准优化
  Master  → 最激进优化（推荐发布）

Script Call Optimization:
  Slow and Safe     → 安全但慢
  Fast but No Exceptions → 最小包体，不处理异常（谨慎使用）

Use incremental GC:
  ✓ 减少GC卡顿

Enable Exceptions:
  Full         → 完整异常处理（开发环境）
  Explicitly Thrown Only → 只处理显式抛出（生产环境推荐）
```

---

## 6. AssetBundle分包策略

### 6.1 分包原则

```
分包策略框架：

首包（必须）：
├── 核心引擎代码
├── 启动场景资源
├── 登录界面资源
└── 基础UI框架

按需下载（热更新包）：
├── 章节/关卡资源
├── 角色资源
├── 技能特效资源
├── 背景音乐
└── 剧情语音
```

### 6.2 智能分包管理器

```csharp
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;
using System.Collections.Generic;
using System.Threading.Tasks;
using Cysharp.Threading.Tasks;

/// <summary>
/// 游戏资源分包下载管理器
/// </summary>
public class DLCDownloadManager : MonoBehaviour
{
    private static DLCDownloadManager _instance;
    public static DLCDownloadManager Instance => _instance;

    // 下载状态追踪
    private readonly Dictionary<string, DLCDownloadState> _downloadStates = new();
    
    public enum DLCStatus { NotDownloaded, Downloading, Downloaded, Failed }
    
    [System.Serializable]
    public class DLCDownloadState
    {
        public string groupName;
        public DLCStatus status;
        public float progress;
        public long totalBytes;
        public long downloadedBytes;
        public string errorMessage;
    }

    private void Awake()
    {
        _instance = this;
    }

    /// <summary>
    /// 检查DLC包是否需要下载
    /// </summary>
    public async UniTask<long> GetDownloadSizeAsync(string groupName)
    {
        var handle = Addressables.GetDownloadSizeAsync(groupName);
        await handle.Task;
        
        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            long size = handle.Result;
            Addressables.Release(handle);
            return size;
        }
        
        return -1;
    }

    /// <summary>
    /// 下载DLC包（带进度回调）
    /// </summary>
    public async UniTask<bool> DownloadDLCAsync(
        string groupName,
        System.Action<float, long, long> onProgress = null,
        System.Action<string> onError = null)
    {
        if (_downloadStates.TryGetValue(groupName, out var state) 
            && state.status == DLCStatus.Downloading)
        {
            Debug.LogWarning($"[DLC] {groupName} 正在下载中，跳过重复请求");
            return false;
        }

        var downloadState = new DLCDownloadState
        {
            groupName = groupName,
            status = DLCStatus.Downloading
        };
        _downloadStates[groupName] = downloadState;

        // 获取总大小
        downloadState.totalBytes = await GetDownloadSizeAsync(groupName);
        
        if (downloadState.totalBytes == 0)
        {
            // 已缓存，无需下载
            downloadState.status = DLCStatus.Downloaded;
            return true;
        }

        var downloadHandle = Addressables.DownloadDependenciesAsync(groupName, false);

        while (!downloadHandle.IsDone)
        {
            downloadState.progress = downloadHandle.PercentComplete;
            downloadState.downloadedBytes = (long)(downloadState.totalBytes * downloadState.progress);
            
            onProgress?.Invoke(
                downloadState.progress,
                downloadState.downloadedBytes,
                downloadState.totalBytes);

            await UniTask.Yield();
        }

        if (downloadHandle.Status == AsyncOperationStatus.Succeeded)
        {
            downloadState.status = DLCStatus.Downloaded;
            downloadState.progress = 1f;
            Addressables.Release(downloadHandle);
            Debug.Log($"[DLC] {groupName} 下载完成，大小：{FormatSize(downloadState.totalBytes)}");
            return true;
        }
        else
        {
            string errorMsg = downloadHandle.OperationException?.Message ?? "未知错误";
            downloadState.status = DLCStatus.Failed;
            downloadState.errorMessage = errorMsg;
            onError?.Invoke(errorMsg);
            Addressables.Release(downloadHandle);
            Debug.LogError($"[DLC] {groupName} 下载失败：{errorMsg}");
            return false;
        }
    }

    /// <summary>
    /// 批量检查并下载多个DLC
    /// </summary>
    public async UniTask<bool> EnsureDLCsAsync(
        string[] groupNames,
        System.Action<string, float> onGroupProgress = null)
    {
        foreach (string groupName in groupNames)
        {
            long size = await GetDownloadSizeAsync(groupName);
            
            if (size > 0)
            {
                bool success = await DownloadDLCAsync(
                    groupName,
                    (progress, downloaded, total) =>
                        onGroupProgress?.Invoke(groupName, progress));

                if (!success) return false;
            }
        }
        return true;
    }

    public DLCStatus GetStatus(string groupName)
    {
        return _downloadStates.TryGetValue(groupName, out var state)
            ? state.status
            : DLCStatus.NotDownloaded;
    }

    private string FormatSize(long bytes)
    {
        if (bytes >= 1024 * 1024) return $"{bytes / 1024f / 1024f:F2}MB";
        if (bytes >= 1024) return $"{bytes / 1024f:F1}KB";
        return $"{bytes}B";
    }
}
```

---

## 7. Android OBB 与 iOS On-Demand Resources

### 7.1 Android APK Expansion Files (OBB)

```csharp
// Player Settings 配置
// Build Settings → Player Settings → Publishing Settings
// ✓ Split Application Binary → 启用OBB分包
// Main OBB Size → 2GB（最大）

// 运行时OBB下载（使用Google Play Plugin）
using Google.Play.Common;
using Google.Play.AppUpdate;

public class OBBDownloader : MonoBehaviour
{
    private AppUpdateManager _appUpdateManager;

    private async void Start()
    {
        _appUpdateManager = new AppUpdateManager();
        await CheckAndDownloadOBB();
    }

    private async System.Threading.Tasks.Task CheckAndDownloadOBB()
    {
        // 检查OBB是否已存在
        string obbPath = Application.persistentDataPath;
        
        // 对于Unity自动管理的OBB，检查StreamingAssets访问
        if (!IsOBBMounted())
        {
            Debug.Log("OBB未挂载，等待下载...");
            // 显示下载UI，等待Google Play Store下载完成
            ShowOBBDownloadUI();
        }
    }

    private bool IsOBBMounted()
    {
        // 尝试访问一个OBB中的已知资源来判断是否已挂载
        try
        {
            var asset = Resources.Load("OBBCheckAsset");
            return asset != null;
        }
        catch
        {
            return false;
        }
    }

    private void ShowOBBDownloadUI()
    {
        // 显示提示界面告知用户需要下载额外资源
        // 通常配合加载界面使用
    }
}
```

### 7.2 iOS On-Demand Resources (ODR)

```csharp
// iOS ODR 资源下载管理
#if UNITY_IOS
using UnityEngine.iOS;
using System.Collections;

public class ODRManager : MonoBehaviour
{
    private OnDemandResourcesRequest _currentRequest;

    /// <summary>
    /// 请求下载ODR资源标签
    /// </summary>
    public IEnumerator RequestODRTagAsync(string tag, System.Action onComplete, System.Action<string> onError)
    {
        _currentRequest = OnDemandResources.PreloadAsync(new[] { tag });

        // 显示进度
        while (!_currentRequest.isDone)
        {
            float progress = _currentRequest.progress;
            Debug.Log($"[ODR] 下载 {tag}：{progress * 100:F0}%");
            yield return null;
        }

        if (_currentRequest.error != null)
        {
            string errorMsg = _currentRequest.error;
            onError?.Invoke(errorMsg);
            _currentRequest.Dispose();
            yield break;
        }

        Debug.Log($"[ODR] {tag} 下载完成");
        onComplete?.Invoke();
        
        // 注意：不要立即释放，保持资源在内存中
        // _currentRequest.Dispose(); // 在不需要时调用
    }

    /// <summary>
    /// 释放ODR资源（让系统决定是否清理）
    /// </summary>
    public void ReleaseODRTag()
    {
        _currentRequest?.Dispose();
        _currentRequest = null;
    }
}
#endif
```

---

## 8. 构建流水线自动化优化

### 8.1 自动化构建脚本

```csharp
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using System;
using System.IO;

public static class AutomatedBuildPipeline
{
    // CI/CD 调用入口
    public static void BuildAndroid()
    {
        ApplyProductionSettings();
        
        string outputPath = $"Builds/Android/game_{DateTime.Now:yyyyMMdd_HHmm}.apk";
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath));

        var buildOptions = new BuildPlayerOptions
        {
            scenes = GetEnabledScenes(),
            locationPathName = outputPath,
            target = BuildTarget.Android,
            options = BuildOptions.None
        };

        BuildReport report = BuildPipeline.BuildPlayer(buildOptions);
        PrintBuildReport(report);
    }

    private static void ApplyProductionSettings()
    {
        // 代码裁剪
        PlayerSettings.stripEngineCode = true;
#if UNITY_2020_1_OR_NEWER
        PlayerSettings.managedStrippingLevel = ManagedStrippingLevel.High;
#endif
        // IL2CPP优化
        PlayerSettings.SetIl2CppCompilerConfiguration(
            BuildTargetGroup.Android, 
            Il2CppCompilerConfiguration.Master);

        // 关闭开发模式
        EditorUserBuildSettings.development = false;
        EditorUserBuildSettings.connectProfiler = false;

        // Android特定设置
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel22;
        PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
        
        // 启用分包
        EditorUserBuildSettings.buildAppBundle = true; // AAB格式（Google Play推荐）
        
        Debug.Log("生产构建配置已应用");
    }

    private static string[] GetEnabledScenes()
    {
        return Array.ConvertAll(
            EditorBuildSettings.scenes,
            s => s.path);
    }

    private static void PrintBuildReport(BuildReport report)
    {
        var summary = report.summary;
        Debug.Log($"构建结果：{summary.result}");
        Debug.Log($"包体大小：{summary.totalSize / 1024f / 1024f:F2}MB");
        Debug.Log($"构建时间：{summary.totalTime.TotalSeconds:F1}s");
        Debug.Log($"错误数：{summary.totalErrors}，警告数：{summary.totalWarnings}");

        if (summary.result == BuildResult.Succeeded)
        {
            Debug.Log($"✅ 构建成功：{summary.outputPath}");
        }
        else
        {
            Debug.LogError($"❌ 构建失败！");
        }
    }
}
```

### 8.2 包体大小监控

```csharp
// 构建后自动分析包体并生成报告
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using System.Text;

public class BuildSizeReporter : IPostprocessBuildWithReport
{
    public int callbackOrder => int.MaxValue;

    public void OnPostprocessBuild(BuildReport report)
    {
        AnalyzeAndReport(report);
    }

    private void AnalyzeAndReport(BuildReport report)
    {
        var sb = new StringBuilder();
        sb.AppendLine("=== 包体大小分析报告 ===");
        sb.AppendLine($"总大小：{report.summary.totalSize / 1024f / 1024f:F2}MB");
        sb.AppendLine();

        // 按类别统计
        var categoryGroups = new System.Collections.Generic.Dictionary<string, long>();

        foreach (var file in report.GetFiles())
        {
            string category = GetCategory(file.path);
            categoryGroups.TryAdd(category, 0);
            categoryGroups[category] += (long)file.size;
        }

        sb.AppendLine("按类别分布：");
        foreach (var kv in categoryGroups.OrderByDescending(x => x.Value))
        {
            float percent = kv.Value * 100f / report.summary.totalSize;
            sb.AppendLine($"  {kv.Key,-25} {kv.Value / 1024f / 1024f,8:F2}MB ({percent,5:F1}%)");
        }

        // TOP 10 最大文件
        sb.AppendLine();
        sb.AppendLine("TOP 10 最大文件：");
        
        var topFiles = report.GetFiles()
            .OrderByDescending(f => f.size)
            .Take(10);

        foreach (var file in topFiles)
        {
            sb.AppendLine($"  {file.size / 1024f / 1024f,6:F2}MB  {file.path}");
        }

        string reportPath = "Builds/build_size_report.txt";
        File.WriteAllText(reportPath, sb.ToString());
        Debug.Log($"包体分析报告已保存到：{reportPath}");
        Debug.Log(sb.ToString());
    }

    private string GetCategory(string path)
    {
        if (path.Contains("Texture") || path.Contains(".png") || path.Contains(".jpg"))
            return "纹理";
        if (path.Contains("Audio") || path.Contains(".ogg") || path.Contains(".wav"))
            return "音频";
        if (path.Contains(".dll") || path.Contains("il2cpp"))
            return "代码";
        if (path.Contains("Shader"))
            return "Shader";
        if (path.Contains("Mesh") || path.Contains(".fbx"))
            return "模型";
        return "其他";
    }
}
```

---

## 9. 最佳实践总结

### 优化优先级矩阵

```
优先级 | 优化项                      | 预期收益  | 实施难度
───────┼─────────────────────────────┼──────────┼────────
最高   | 纹理压缩格式（ASTC/ETC2）   | 30-50%   | 低
最高   | 移除未使用资源               | 10-30%   | 低
高     | 音频格式优化                 | 10-20%   | 低
高     | IL2CPP Master模式            | 5-15%    | 低
高     | 托管代码裁剪                 | 5-20%    | 中
中     | Shader变体裁剪               | 5-15%    | 中
中     | 资源分包（按需下载）         | 40-70%   | 高
低     | 模型LOD优化                  | 5-10%    | 中
低     | 图片转图集                   | 3-8%     | 中
```

### 10. 检查清单

```
□ 所有纹理使用平台专用压缩格式（ASTC/ETC2）
□ 纹理尺寸不超过实际显示需求（最大1024或2048）
□ UI纹理关闭MipMap
□ BGM使用Streaming+Vorbis
□ SFX使用ADPCM
□ 删除所有未引用资源
□ 配置合理的link.xml防止必要代码被裁剪
□ IL2CPP设置为Master模式
□ 管理代码裁剪级别至少设为Low
□ 开启AAB格式构建（Android Play Asset Delivery）
□ 配置按需下载分包策略
□ 建立包体大小CI监控，超阈值告警
□ 定期运行包体分析报告（每个迭代）
```

---

## 总结

游戏包体优化是一项系统工程，需要从资源、代码、构建流程三个维度协同推进。核心原则是：**能压缩的压缩，能延迟加载的延迟，能按需下载的分包**。通过本文的技术方案，大多数游戏可以将包体压缩到原来的 40%-60%，显著提升用户下载转化率和留存。
