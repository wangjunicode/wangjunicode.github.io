---
title: Unity Progressive Lightmapper深度调优：烘焙参数精通与大型场景增量烘焙工程实践完全指南
published: 2026-05-08
description: 系统讲解Unity Progressive CPU/GPU Lightmapper的核心参数与底层算法，深入解析Lightmap分辨率、采样数、降噪策略、子场景增量烘焙、Baked GI与Mixed模式对比，并提供一套可直接投入生产的自动化烘焙管线工具链。
tags: [渲染, 光照, Lightmap, 烘焙, URP, 性能优化]
category: 渲染
draft: false
---

# Unity Progressive Lightmapper深度调优：烘焙参数精通与大型场景增量烘焙工程实践完全指南

## 1. 烘焙光照的本质与 Progressive 算法

### 1.1 为什么需要光照烘焙

实时光照计算在移动端有严苛的性能限制。一盏使用阴影的实时方向光，在中低端手机上每帧需要至少两次全场景渲染（主渲染 + 阴影图渲染），显著拉高 GPU 负担。

**烘焙光照的核心优势：**
- 静态物体的阴影、间接光照（GI）**预计算一次，运行时零 GPU 消耗**
- 可以使用光线追踪算法（路径追踪），实现无法实时渲染的高质量 GI
- 支持 Area Light、Emissive 材质作为光源，这类光源无法实时渲染

### 1.2 Progressive Lightmapper 算法原理

Unity 的 Progressive Lightmapper 使用**路径追踪（Path Tracing）+ 重要性采样**算法，是蒙特卡洛积分的一种变体：

```
// 渲染方程（简化）
Lo(x, ω_o) = Le(x, ω_o) + ∫ Li(x, ω_i) * f(x, ω_i, ω_o) * cos(θ_i) dω_i

// Progressive 的求解方式：
// 1. 从每个 texel 发射 N 条光线（采样数）
// 2. 每条光线弹射 M 次（最大弹射次数）
// 3. 累积所有样本的蒙特卡洛估计
// 4. 结果随采样数增加逐渐收敛（Progressive = 渐进式收敛）
```

**CPU vs GPU Progressive 对比：**

| 指标 | CPU Progressive | GPU Progressive |
|------|----------------|----------------|
| 烘焙速度 | 较慢 | 快 2~10 倍 |
| 内存占用 | 低 | 高（需 VRAM） |
| 稳定性 | 高 | 复杂场景可能崩溃 |
| 适用场景 | 生产流程 | 快速预览迭代 |

---

## 2. 核心参数深度解析

### 2.1 Lightmap 分辨率体系

```
场景设置路径：Window > Rendering > Lighting > Lightmapping Settings
```

**关键参数：**

```csharp
// 通过 API 读取/设置 Lightmap 参数
using UnityEngine;
using UnityEditor;

public static class LightmapParamHelper
{
    // Texel 密度：每个 Unity 单位占用多少个 Lightmap 像素
    // 值越大越精细，但 Lightmap 贴图越大
    public static void SetLightmapResolution(float texelsPerUnit)
    {
        LightmapEditorSettings.bakeResolution = texelsPerUnit;
        // 建议值：
        // 移动端室内场景：8~16 texels/unit
        // 移动端室外场景：4~8  texels/unit
        // PC 高质量：     20~40 texels/unit
    }

    // Lightmap 贴图尺寸上限
    public static void SetLightmapMaxSize(int maxAtlasSize)
    {
        LightmapEditorSettings.maxAtlasSize = maxAtlasSize;
        // 移动端：512 或 1024（VRAM 紧张）
        // PC：   1024 或 2048
        // 单张 2048 RGB 贴图约占 12MB，需平衡数量与大小
    }

    // Lightmap 压缩
    // 注意：压缩后会有精度损失，影响光照效果
    public static void SetCompression(bool compress)
    {
        LightmapEditorSettings.textureCompression = compress;
    }
}
```

**分辨率调试技巧：**  
在 Scene 视图中选择 Baked Lightmap 可视化模式，能直观看到各物体的 Lightmap 使用密度，便于发现分辨率浪费或不足的区域。

### 2.2 采样数（Samples）调优

采样数是影响烘焙质量和速度的最关键参数：

```
采样数 2 倍 → 噪点减少约 √2 倍 → 烘焙时间增加约 2 倍
```

**分级配置策略：**

| 阶段 | Direct Samples | Indirect Samples | Environment Samples | 用途 |
|------|---------------|-----------------|--------------------|----|
| 快速预览 | 32 | 64 | 128 | 美术快速检查效果 |
| 中等质量 | 128 | 512 | 512 | 日常迭代 |
| 正式发布 | 512 | 2048 | 2048 | 最终构建 |
| 最高质量 | 2048 | 8192 | 4096 | 宣传材料 |

```csharp
public static class LightmapQualityPreset
{
    [MenuItem("Tools/Lighting/Set Quality - Preview")]
    public static void SetPreview()
    {
        LightmapEditorSettings.directSampleCount = 32;
        LightmapEditorSettings.indirectSampleCount = 64;
        LightmapEditorSettings.environmentSampleCount = 128;
        LightmapEditorSettings.maxBounces = 2;
        LightmapEditorSettings.filteringMode = LightmapEditorSettings.FilterMode.None;
        Debug.Log("[Lightmap] 已设置为快速预览模式");
    }

    [MenuItem("Tools/Lighting/Set Quality - Release")]
    public static void SetRelease()
    {
        LightmapEditorSettings.directSampleCount = 512;
        LightmapEditorSettings.indirectSampleCount = 2048;
        LightmapEditorSettings.environmentSampleCount = 2048;
        LightmapEditorSettings.maxBounces = 4;
        LightmapEditorSettings.filteringMode = LightmapEditorSettings.FilterMode.Auto;
        Debug.Log("[Lightmap] 已设置为发布质量模式");
    }
}
```

### 2.3 降噪（Denoising）策略

降噪器是低采样数下提升视觉质量的关键：

```csharp
// Unity 支持三种降噪器
public enum DenoiserType
{
    None,       // 不降噪，需要高采样数
    Optix,      // NVIDIA OptiX AI 降噪（需要 NVIDIA GPU）
    OpenImage,  // Intel Open Image Denoise（通用，推荐）
    Radeon,     // AMD Radeon ProRender（AMD GPU）
}

// 建议配置
LightmapEditorSettings.filteringMode = LightmapEditorSettings.FilterMode.Auto;
// Auto 模式会自动选择可用的最优降噪器
```

**降噪器使用注意事项：**

1. **OpenImageDenoise** 是跨平台最稳定的选择，推荐在 CI/CD 流水线中使用
2. 降噪会消除部分有效的高频细节（尤其是小光源），建议对比降噪前后效果
3. 降噪后仍有噪点说明采样数过低，应增加采样数而非依赖降噪器

### 2.4 间接分辨率（Indirect Resolution）

间接光照贡献图（Irradiance Cache）的分辨率通常可以比 Lightmap 更低：

```csharp
// 间接分辨率 = 直接分辨率的 1/4 ~ 1/2 即可获得不错效果
LightmapEditorSettings.realtimeResolution = 2;  // 间接光照分辨率（小值即可）

// 原因：间接光照本身是低频信号（变化平缓），
// 不需要像直接光照阴影边缘那样高频细节
```

---

## 3. 光照模式深度对比

### 3.1 Baked / Mixed / Realtime 三种模式

```csharp
// 通过 Light 组件设置
Light light = GetComponent<Light>();

// 完全烘焙：直接光+间接光全部烘焙，无运行时开销
light.lightmapBakeType = LightmapBakeType.Baked;

// 混合模式：间接光烘焙，直接光实时计算（支持动态阴影）
light.lightmapBakeType = LightmapBakeType.Mixed;

// 完全实时：不参与烘焙，纯实时计算
light.lightmapBakeType = LightmapBakeType.Realtime;
```

**Mixed 模式的子模式（Lighting Mode）：**

```
ProjectSettings > Graphics > Lighting Mode
```

| 模式 | 原理 | 适用场景 | 性能 |
|------|------|---------|------|
| Shadowmask | 动态阴影+烘焙阴影叠加，远处用 Lightmap | 开放世界，需要动态人物阴影 | 中等 |
| Subtractive | 直接光烘焙，动态阴影从 Lightmap 中减去 | 移动端，性能要求极高 | 最佳 |
| Distance Shadowmask | Shadowmask 的距离分级版本 | 大世界场景分级渲染 | 中等偏低 |

**移动端推荐组合：**
```
方向光：Mixed + Subtractive 模式
点光/聚光：Baked（完全烘焙，无运行时开销）
```

### 3.2 Light Probe 与 Lightmap 协同

```csharp
// 动态物体（角色、道具）不参与 Lightmap，使用 Light Probe 采样周围光照
// 确保动态物体受烘焙光照影响

// Light Probe Group 放置原则
// 1. 光照变化明显的区域多放（窗边、门洞）
// 2. 开阔无遮挡区域少放（减少内存和采样开销）
// 3. 不要放在碰撞体内部（会采样错误光照值）

// Probe Volume（Unity 6 新特性：Adaptive Probe Volumes）
// 优势：自动分布，不需要手动放置
using UnityEngine.Rendering;
// APV 配置在 Volume Profile 中进行
```

---

## 4. 大型场景增量烘焙工程实践

### 4.1 多场景分区烘焙

```csharp
// LightmapBakeManager.cs - 多场景批量烘焙工具
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.IO;

public class LightmapBakeManager : EditorWindow
{
    private List<SceneAsset> _scenesToBake = new List<SceneAsset>();
    private bool _isBaking;
    private int _currentIndex;

    [MenuItem("Tools/Lighting/Batch Bake Manager")]
    public static void ShowWindow()
    {
        GetWindow<LightmapBakeManager>("批量烘焙管理器");
    }

    private void OnGUI()
    {
        GUILayout.Label("场景列表", EditorStyles.boldLabel);
        
        for (int i = 0; i < _scenesToBake.Count; i++)
        {
            EditorGUILayout.BeginHorizontal();
            _scenesToBake[i] = (SceneAsset)EditorGUILayout.ObjectField(
                _scenesToBake[i], typeof(SceneAsset), false);
            if (GUILayout.Button("X", GUILayout.Width(20)))
                _scenesToBake.RemoveAt(i--);
            EditorGUILayout.EndHorizontal();
        }

        if (GUILayout.Button("+ 添加场景"))
            _scenesToBake.Add(null);

        EditorGUILayout.Space();

        if (!_isBaking)
        {
            if (GUILayout.Button("开始批量烘焙", GUILayout.Height(30)))
                StartBatchBake();
        }
        else
        {
            EditorGUI.ProgressBar(
                EditorGUILayout.GetControlRect(GUILayout.Height(20)),
                (float)_currentIndex / _scenesToBake.Count,
                $"烘焙中 {_currentIndex}/{_scenesToBake.Count}");
            if (GUILayout.Button("取消"))
                CancelBake();
        }
    }

    private void StartBatchBake()
    {
        _isBaking = true;
        _currentIndex = 0;
        BakeNextScene();
    }

    private void BakeNextScene()
    {
        if (_currentIndex >= _scenesToBake.Count)
        {
            _isBaking = false;
            EditorUtility.DisplayDialog("烘焙完成", 
                $"成功烘焙 {_scenesToBake.Count} 个场景", "确定");
            return;
        }

        var sceneAsset = _scenesToBake[_currentIndex];
        if (sceneAsset == null) { _currentIndex++; BakeNextScene(); return; }

        string scenePath = AssetDatabase.GetAssetPath(sceneAsset);
        
        // 打开场景
        UnityEditor.SceneManagement.EditorSceneManager.OpenScene(scenePath);
        
        // 清除旧的 Lightmap 数据
        Lightmapping.Clear();
        
        // 异步烘焙（避免阻塞编辑器）
        Lightmapping.BakeAsync();
        Lightmapping.completed += OnBakeCompleted;
    }

    private void OnBakeCompleted()
    {
        Lightmapping.completed -= OnBakeCompleted;
        
        // 保存场景
        UnityEditor.SceneManagement.EditorSceneManager.SaveOpenScenes();
        
        // 导出烘焙报告
        ExportBakeReport(_scenesToBake[_currentIndex]);
        
        _currentIndex++;
        BakeNextScene();
    }

    private void ExportBakeReport(SceneAsset scene)
    {
        // 记录烘焙结果到 CSV（便于后续分析）
        string reportPath = $"Assets/LightmapReports/{scene.name}_bake_report.txt";
        Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
        
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"场景：{scene.name}");
        sb.AppendLine($"烘焙时间：{System.DateTime.Now}");
        sb.AppendLine($"Lightmap 数量：{LightmapSettings.lightmaps.Length}");
        
        for (int i = 0; i < LightmapSettings.lightmaps.Length; i++)
        {
            var lm = LightmapSettings.lightmaps[i];
            sb.AppendLine($"  [{i}] {lm.lightmapColor?.name ?? "null"} " +
                         $"({lm.lightmapColor?.width}x{lm.lightmapColor?.height})");
        }
        
        File.WriteAllText(reportPath, sb.ToString());
        AssetDatabase.Refresh();
        Debug.Log($"[LightmapBake] 报告已保存至 {reportPath}");
    }

    private void CancelBake()
    {
        Lightmapping.Cancel();
        _isBaking = false;
    }
}
```

### 4.2 增量烘焙：只重烘修改的区域

```csharp
// IncrementalBakeHelper.cs - 基于场景变更检测的增量烘焙
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

public static class IncrementalBakeHelper
{
    private const string HASH_CACHE_KEY = "LightmapHashCache";

    /// <summary>
    /// 计算场景中所有静态物体变换的哈希，用于检测是否需要重新烘焙
    /// </summary>
    public static string CalculateSceneHash()
    {
        var sb = new StringBuilder();
        
        // 收集所有参与烘焙的静态物体
        foreach (var renderer in Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None))
        {
            if (!GameObjectUtility.AreStaticEditorFlagsSet(
                renderer.gameObject, StaticEditorFlags.ContributeGI)) continue;
            
            var t = renderer.transform;
            sb.Append(renderer.gameObject.name);
            sb.Append(t.position); sb.Append(t.rotation); sb.Append(t.lossyScale);
            sb.Append(renderer.lightmapScaleOffset);
        }
        
        // 收集光源参数
        foreach (var light in Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
        {
            if (light.lightmapBakeType == LightmapBakeType.Realtime) continue;
            sb.Append(light.type); sb.Append(light.color);
            sb.Append(light.intensity); sb.Append(light.transform.position);
        }
        
        using var md5 = MD5.Create();
        byte[] hash = md5.ComputeHash(Encoding.UTF8.GetBytes(sb.ToString()));
        return System.BitConverter.ToString(hash).Replace("-", "");
    }

    /// <summary>
    /// 检查是否需要重新烘焙（与缓存的哈希比对）
    /// </summary>
    public static bool NeedsRebake(string sceneName)
    {
        string cacheKey = $"{HASH_CACHE_KEY}_{sceneName}";
        string cachedHash = EditorPrefs.GetString(cacheKey, "");
        string currentHash = CalculateSceneHash();
        return cachedHash != currentHash;
    }

    /// <summary>
    /// 烘焙完成后更新哈希缓存
    /// </summary>
    public static void UpdateHashCache(string sceneName)
    {
        string cacheKey = $"{HASH_CACHE_KEY}_{sceneName}";
        EditorPrefs.SetString(cacheKey, CalculateSceneHash());
        Debug.Log($"[IncrementalBake] 已更新场景 {sceneName} 的烘焙哈希缓存");
    }

    [MenuItem("Tools/Lighting/Smart Incremental Bake")]
    public static void SmartBake()
    {
        string sceneName = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;
        
        if (!NeedsRebake(sceneName))
        {
            bool force = EditorUtility.DisplayDialog(
                "增量烘焙",
                $"场景 {sceneName} 自上次烘焙以来未发生变化，是否强制重新烘焙？",
                "强制烘焙", "跳过");
            if (!force) { Debug.Log("[IncrementalBake] 场景未变化，跳过烘焙"); return; }
        }

        Debug.Log($"[IncrementalBake] 开始烘焙场景 {sceneName}...");
        Lightmapping.BakeAsync();
        Lightmapping.completed += () =>
        {
            UpdateHashCache(sceneName);
            Debug.Log($"[IncrementalBake] 烘焙完成！");
        };
    }
}
```

### 4.3 Lightmap 运行时动态切换

```csharp
// LightmapSwitcher.cs - 运行时切换不同时段的 Lightmap（昼/夜）
using UnityEngine;

[System.Serializable]
public struct LightmapSet
{
    public string Name;
    public Texture2D[] LightmapColors;
    public Texture2D[] LightmapDirectionals;
    public LightProbes LightProbes;
}

public class LightmapSwitcher : MonoBehaviour
{
    [SerializeField] private LightmapSet[] _lightmapSets;
    [SerializeField] private float _blendDuration = 2f;
    
    private int _currentSetIndex = 0;
    private int _targetSetIndex = 0;
    private float _blendProgress = 1f;
    
    // 为每个 Renderer 缓存其 LightmapIndex
    private Renderer[] _staticRenderers;
    private int[] _originalLightmapIndices;

    private void Awake()
    {
        // 缓存场景中所有静态 Renderer
        _staticRenderers = FindObjectsByType<Renderer>(FindObjectsSortMode.None);
        _originalLightmapIndices = new int[_staticRenderers.Length];
        for (int i = 0; i < _staticRenderers.Length; i++)
            _originalLightmapIndices[i] = _staticRenderers[i].lightmapIndex;
    }

    public void SwitchTo(int setIndex)
    {
        if (setIndex < 0 || setIndex >= _lightmapSets.Length) return;
        _targetSetIndex = setIndex;
        _blendProgress = 0f;
        
        // 立即切换（无过渡）
        ApplyLightmapSet(_lightmapSets[setIndex]);
    }

    private void ApplyLightmapSet(LightmapSet set)
    {
        // 构建 LightmapData 数组
        var lightmaps = new LightmapData[set.LightmapColors.Length];
        for (int i = 0; i < set.LightmapColors.Length; i++)
        {
            lightmaps[i] = new LightmapData
            {
                lightmapColor = set.LightmapColors[i],
                lightmapDir = set.LightmapDirectionals != null && i < set.LightmapDirectionals.Length
                    ? set.LightmapDirectionals[i] : null
            };
        }
        LightmapSettings.lightmaps = lightmaps;
        
        // 切换 Light Probes
        if (set.LightProbes != null)
            LightmapSettings.lightProbes = set.LightProbes;
        
        _currentSetIndex = _targetSetIndex;
    }
}
```

---

## 5. CI/CD 自动化烘焙流水线

### 5.1 命令行触发烘焙

```bash
# 在 CI 流水线（如 Jenkins、GitHub Actions）中触发烘焙
Unity -quit -batchmode -projectPath /path/to/project \
    -executeMethod LightmapBakePipeline.BakeAll \
    -logFile bake_log.txt
```

```csharp
// LightmapBakePipeline.cs - CI 烘焙入口
using UnityEditor;
using UnityEngine;

public static class LightmapBakePipeline
{
    /// <summary>
    /// 命令行触发全量烘焙（-executeMethod LightmapBakePipeline.BakeAll）
    /// </summary>
    public static void BakeAll()
    {
        // 解析命令行参数
        var args = System.Environment.GetCommandLineArgs();
        string quality = "release";
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == "-lightmapQuality")
                quality = args[i + 1];
        }

        // 设置质量
        if (quality == "preview")
            LightmapQualityPreset.SetPreview();
        else
            LightmapQualityPreset.SetRelease();

        // 同步烘焙（批处理模式下需要同步）
        bool success = Lightmapping.Bake();
        
        if (success)
        {
            AssetDatabase.SaveAssets();
            Debug.Log("[CI-Bake] 烘焙成功！");
            EditorApplication.Exit(0);
        }
        else
        {
            Debug.LogError("[CI-Bake] 烘焙失败！");
            EditorApplication.Exit(1);
        }
    }
}
```

---

## 6. 常见问题与调试技巧

### 6.1 漏光问题（Light Leaking）

**症状：** 室内场景的外墙背光面出现不正常的亮色。  
**原因：** 场景几何体太薄，光线探针或路径追踪射线穿透了墙体。

**解决方案：**
```
1. 增加墙体厚度（建议 >= 0.2 Unity 单位）
2. 对室内区域添加 LightProbe Proxy Volume 阻挡
3. 对外墙添加 Backface Culling，并确保法线方向正确
4. 减小 Bias 参数（但过小会产生自阴影噪点）
```

### 6.2 Lightmap UV 重叠

```csharp
// 检测 Lightmap UV 重叠的编辑器工具
[MenuItem("Tools/Lighting/Check UV Overlaps")]
public static void CheckUVOverlaps()
{
    var renderers = Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None);
    int overlapCount = 0;
    
    foreach (var r in renderers)
    {
        if (r.TryGetComponent<MeshFilter>(out var mf) && mf.sharedMesh != null)
        {
            // Unity 提供了 Unwrapping.GenerateSecondaryUVSet 来自动生成不重叠的 UV2
            var mesh = mf.sharedMesh;
            if (mesh.uv2 == null || mesh.uv2.Length == 0)
            {
                Debug.LogWarning($"[UV Check] {r.gameObject.name} 缺少 UV2（Lightmap UV），将由 Unity 自动生成", r);
                overlapCount++;
            }
        }
    }
    Debug.Log($"[UV Check] 检测完成，共发现 {overlapCount} 个需要关注的 UV 问题");
}
```

### 6.3 常见调优数据参考

| 场景类型 | 贴图大小 | 分辨率 | 采样数（发布） | 典型烘焙时长 |
|---------|---------|-------|------------|-----------|
| 小型室内（< 20 静态物体） | 512x512 | 10 | 512/2048 | 5~15 分钟 |
| 中型室内关卡 | 1024x1024 x4 | 20 | 512/2048 | 30~60 分钟 |
| 大型开放场景 | 2048x2048 x8 | 8 | 256/1024 | 2~4 小时 |
| 超大世界（分区烘焙） | 每区 1024x1024 | 6 | 256/512 | 每区 20~40 分钟 |

---

## 7. 最佳实践总结

| 实践 | 建议 |
|------|------|
| **分级质量** | 维护 Preview/Debug/Release 三套参数预设，脚本一键切换 |
| **增量烘焙** | 基于场景哈希检测变更，未修改场景跳过烘焙节省 CI 时间 |
| **UV2 检查** | 烘焙前自动检测 UV2 重叠，提前修复避免返工 |
| **分区烘焙** | 大场景拆分为独立 Scene，并行烘焙缩短总时间 |
| **降噪器** | 优先使用 OpenImageDenoise，支持无 GPU 的 CI 机器 |
| **Mixed 模式** | 移动端优先用 Subtractive，PC 用 Shadowmask |
| **Light Probe** | 动态物体区域 Probe 密度 > 静态区域，过渡区域增加 |
| **Lightmap 压缩** | iOS 用 ASTC，Android 用 ETC2，避免使用 BC6H（移动端不支持） |
| **版本控制** | Lightmap 贴图体积大，存到 LFS 或使用专门的构建产物服务器 |
| **运行时切换** | 昼夜切换通过预烘焙多套 Lightmap 实现，避免实时重烘代价 |

---

## 结语

Progressive Lightmapper 的调优是光照质量与烘焙成本之间的精密权衡。通过理解路径追踪算法原理、掌握采样数与降噪器的组合策略、建立工程化的批量增量烘焙流水线，可以在大型项目中实现"美术自助烘焙、CI 定期全量烘焙"的高效工作流。对于追求极致视觉表现的游戏项目，光照烘焙的工程化投入会带来远超预期的回报。
