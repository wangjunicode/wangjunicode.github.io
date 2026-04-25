---
title: 游戏客户端Shader预编译与PSO管线状态缓存深度实践完全指南
published: 2026-04-25
description: 深入解析Unity游戏中Shader预编译策略、ShaderVariantCollection收集方案、PSO（Pipeline State Object）离线缓存与运行时预热技术，彻底消除首帧Stutter卡顿问题，涵盖移动端与PC端的差异化优化方案与工程化落地最佳实践。
tags: [Shader, PSO, 性能优化, Unity, GPU, 渲染]
category: 渲染技术
draft: false
---

# 游戏客户端Shader预编译与PSO管线状态缓存深度实践完全指南

## 一、为什么Shader卡顿是顽固的性能噩梦

在游戏开发中，玩家反馈最多的性能问题之一是"第一次进入某场景/使用某技能时会卡顿一下"。这种现象被称为 **Shader编译卡顿（Shader Compilation Stutter）**，根本原因是：

- GPU驱动在渲染管线首次执行时需要即时编译Shader字节码为机器码
- 在D3D12/Vulkan/Metal等现代图形API中，还需要创建完整的 **PSO（Pipeline State Object）**
- PSO创建包含Shader编译、光栅化状态、混合状态、格式匹配等，耗时可高达 **100ms～500ms**

```
传统OpenGL（隐式状态机）：
  渲染调用 → 驱动隐式验证状态 → 可能触发后台编译 → 首帧卡顿

现代API（Vulkan/D3D12/Metal）：
  必须显式创建PSO → CPU端创建开销 → 若在渲染线程同步创建 → 主线程卡顿
```

### 1.1 Unity中的Shader编译时机

```csharp
// Unity内部流程（简化）
// 1. 加载Material时：读取Shader资产，但不编译GPU程序
// 2. 首次SetPass时：检查Shader变体是否已编译
//    - 若未编译 → 触发同步编译 → 主线程卡顿
//    - 若已预热 → 直接使用缓存 → 无卡顿
// 3. D3D12/Vulkan后端：SetPass还需创建PSO
//    - PSO创建 = Shader编译 + 状态对象创建
//    - 同步创建时间：50ms~500ms
```

### 1.2 Stutter的量化分析

通过 Unity Profiler 捕获首帧卡顿时序：

```
帧 1:  16ms  (正常)
帧 2:  17ms  (正常)
帧 3: 387ms  ← Shader编译触发 (严重卡顿)
帧 4:  16ms  (恢复)
帧 5:  15ms  (正常)
```

---

## 二、ShaderVariantCollection：变体收集与预热基础

### 2.1 Shader变体爆炸问题

现代游戏Shader大量使用 `#pragma multi_compile` 和 `#pragma shader_feature`，导致变体数量指数级增长：

```hlsl
// 一个包含以下关键字的Shader
#pragma multi_compile _ SHADOWS_ON SHADOWS_OFF      // 3 种
#pragma multi_compile _ FOG_LINEAR FOG_EXP2         // 3 种
#pragma multi_compile _ LIGHTMAP_ON                 // 2 种
#pragma multi_compile _ VERTEX_COLORS               // 2 种

// 理论变体数：3 × 3 × 2 × 2 = 36 个变体
// 实际项目中某些Shader有数千个变体
```

### 2.2 ShaderVariantCollection的工作原理

```csharp
// ShaderVariantCollection是一个变体白名单
// 记录：Shader + PassType + 关键字组合
// 预热时：将白名单内的变体提前编译

[Serializable]
public struct ShaderVariant
{
    public Shader shader;
    public PassType passType;      // ForwardBase, ForwardAdd, ShadowCaster...
    public string[] keywords;      // 激活的关键字列表
}
```

### 2.3 运行时收集ShaderVariantCollection

**方法一：Unity内置录制（编辑器）**

```
Edit → Project Settings → Graphics → Shader Stripping
→ 勾选 "Log Shader Compilation"
→ 运行游戏，遍历所有场景/技能/UI
→ Edit → Project Settings → Graphics → Save to Asset
```

**方法二：代码驱动的自动收集**

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;
#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.Rendering;
#endif

/// <summary>
/// 运行时Shader变体自动收集器
/// 通过Hook渲染管线获取实际使用的变体组合
/// </summary>
public class ShaderVariantCollector : MonoBehaviour
{
#if UNITY_EDITOR
    private static readonly Dictionary<Shader, HashSet<ShaderVariantData>> s_CollectedVariants
        = new Dictionary<Shader, HashSet<ShaderVariantData>>();
    
    private struct ShaderVariantData : System.IEquatable<ShaderVariantData>
    {
        public PassType PassType;
        public string[] Keywords;
        
        public bool Equals(ShaderVariantData other)
        {
            if (PassType != other.PassType) return false;
            if (Keywords.Length != other.Keywords.Length) return false;
            var thisSet = new HashSet<string>(Keywords);
            foreach (var kw in other.Keywords)
                if (!thisSet.Contains(kw)) return false;
            return true;
        }
        
        public override int GetHashCode()
        {
            int hash = PassType.GetHashCode();
            foreach (var kw in Keywords)
                hash ^= kw.GetHashCode();
            return hash;
        }
    }

    private void OnEnable()
    {
        // Hook Shader编译事件（Unity 2021.2+）
        ShaderUtil.allowAsyncCompilation = false; // 强制同步，便于捕获
    }

    /// <summary>
    /// 遍历场景中所有Renderer，收集变体信息
    /// </summary>
    [ContextMenu("Collect All Scene Variants")]
    public void CollectSceneVariants()
    {
        var renderers = FindObjectsOfType<Renderer>();
        foreach (var renderer in renderers)
        {
            foreach (var material in renderer.sharedMaterials)
            {
                if (material == null) continue;
                CollectMaterialVariants(material);
            }
        }
        Debug.Log($"[ShaderVariantCollector] 已收集 {s_CollectedVariants.Count} 个Shader的变体信息");
    }

    private void CollectMaterialVariants(Material mat)
    {
        var shader = mat.shader;
        if (!s_CollectedVariants.TryGetValue(shader, out var variantSet))
        {
            variantSet = new HashSet<ShaderVariantData>();
            s_CollectedVariants[shader] = variantSet;
        }

        // 获取Material当前激活的关键字
        var keywords = mat.shaderKeywords;
        
        // 枚举所有Pass类型
        int passCount = ShaderUtil.GetShaderActiveSubshaderIndex(shader);
        // 简化：记录ForwardBase变体
        variantSet.Add(new ShaderVariantData
        {
            PassType = PassType.ForwardBase,
            Keywords = keywords
        });
    }

    /// <summary>
    /// 将收集结果保存为ShaderVariantCollection资产
    /// </summary>
    [ContextMenu("Save to ShaderVariantCollection")]
    public void SaveToCollection()
    {
        var svc = new ShaderVariantCollection();
        foreach (var kvp in s_CollectedVariants)
        {
            foreach (var variantData in kvp.Value)
            {
                var variant = new ShaderVariantCollection.ShaderVariant
                {
                    shader = kvp.Key,
                    passType = variantData.PassType,
                    keywords = variantData.Keywords
                };
                try { svc.Add(variant); }
                catch (System.Exception e)
                {
                    Debug.LogWarning($"[ShaderVariantCollector] 跳过无效变体: {e.Message}");
                }
            }
        }

        string savePath = "Assets/ShaderVariants/AutoCollected.shadervariants";
        System.IO.Directory.CreateDirectory("Assets/ShaderVariants");
        AssetDatabase.CreateAsset(svc, savePath);
        AssetDatabase.SaveAssets();
        Debug.Log($"[ShaderVariantCollector] 已保存到 {savePath}，共 {svc.variantCount} 个变体");
    }
#endif
}
```

---

## 三、运行时Shader预热系统

### 3.1 基础预热流程

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections;
using System.Collections.Generic;

/// <summary>
/// 游戏启动时的Shader预热管理器
/// 在Loading界面期间异步预热，彻底消除游戏过程中的编译卡顿
/// </summary>
public class ShaderWarmupManager : MonoBehaviour
{
    [Header("预热配置")]
    [SerializeField] private List<ShaderVariantCollection> _variantCollections;
    [SerializeField] private bool _warmupOnStart = true;
    [SerializeField] private int _warmupBatchSize = 10;  // 每帧预热批次数
    
    [Header("进度回调")]
    public System.Action<float> OnProgress;  // 0~1进度
    public System.Action OnComplete;

    private bool _isWarmedUp = false;
    private static ShaderWarmupManager s_Instance;

    public static bool IsWarmedUp => s_Instance != null && s_Instance._isWarmedUp;

    private void Awake()
    {
        s_Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    private void Start()
    {
        if (_warmupOnStart)
            StartCoroutine(WarmupCoroutine());
    }

    /// <summary>
    /// 分帧异步预热：避免单帧长时间阻塞
    /// </summary>
    private IEnumerator WarmupCoroutine()
    {
        Debug.Log("[ShaderWarmup] 开始Shader预热...");
        float startTime = Time.realtimeSinceStartup;

        // 统计总变体数
        int totalVariants = 0;
        foreach (var svc in _variantCollections)
            if (svc != null) totalVariants += svc.variantCount;

        int warmedCount = 0;

        foreach (var svc in _variantCollections)
        {
            if (svc == null) continue;

            // Unity提供的批量预热API（2021+）
            // 注意：WarmUpProgressively是分帧的，不会单帧阻塞
            var enumerator = WarmupCollectionProgressively(svc);
            
            while (enumerator.MoveNext())
            {
                warmedCount++;
                float progress = (float)warmedCount / totalVariants;
                OnProgress?.Invoke(progress);
                
                // 每批次后等一帧，避免卡顿
                if (warmedCount % _warmupBatchSize == 0)
                    yield return null;
            }
        }

        float elapsed = Time.realtimeSinceStartup - startTime;
        _isWarmedUp = true;
        Debug.Log($"[ShaderWarmup] 预热完成！耗时 {elapsed:F2}s，共预热 {warmedCount} 个变体");
        OnProgress?.Invoke(1.0f);
        OnComplete?.Invoke();
    }

    /// <summary>
    /// 逐个预热ShaderVariantCollection中的变体
    /// </summary>
    private IEnumerable WarmupCollectionProgressively(ShaderVariantCollection svc)
    {
        // Unity 2021.2+ 推荐使用 WarmUp()，内部已做了分批处理
        // 对于更精细控制，可以使用ShaderVariantCollection.WarmUpProgressively
        svc.WarmUp();
        yield return null;
    }

    /// <summary>
    /// 针对特定Shader的即时预热（进入特定关卡前调用）
    /// </summary>
    public static void WarmupShaderImmediate(Shader shader, string[] keywords = null)
    {
        if (shader == null) return;
        
        var tempSVC = new ShaderVariantCollection();
        var variant = new ShaderVariantCollection.ShaderVariant
        {
            shader = shader,
            passType = PassType.ForwardBase,
            keywords = keywords ?? new string[0]
        };
        
        try
        {
            tempSVC.Add(variant);
            tempSVC.WarmUp();
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"[ShaderWarmup] 预热失败: {shader.name}, {e.Message}");
        }
    }
}
```

### 3.2 Loading界面集成

```csharp
/// <summary>
/// Loading界面控制器：在预热期间显示进度条
/// </summary>
public class LoadingScreenController : MonoBehaviour
{
    [SerializeField] private UnityEngine.UI.Slider _progressBar;
    [SerializeField] private TMPro.TextMeshProUGUI _progressText;
    [SerializeField] private ShaderWarmupManager _warmupManager;

    private void OnEnable()
    {
        _warmupManager.OnProgress += UpdateProgress;
        _warmupManager.OnComplete += OnWarmupComplete;
    }

    private void OnDisable()
    {
        _warmupManager.OnProgress -= UpdateProgress;
        _warmupManager.OnComplete -= OnWarmupComplete;
    }

    private void UpdateProgress(float progress)
    {
        _progressBar.value = progress;
        int percent = Mathf.RoundToInt(progress * 100);
        
        // 将Shader预热进度映射到总进度的前60%
        // 后40%可以给资源加载等其他初始化
        _progressText.text = percent < 60 
            ? $"优化图形资源... {percent}%" 
            : $"加载游戏资源... {percent}%";
    }

    private void OnWarmupComplete()
    {
        // 可以开始加载主场景
        UnityEngine.SceneManagement.SceneManager.LoadSceneAsync("MainScene");
    }
}
```

---

## 四、PSO预热：现代图形API的关键挑战

### 4.1 什么是PSO

PSO（Pipeline State Object）是D3D12/Vulkan/Metal中的核心概念，将以下状态打包为一个不可变对象：

```
PSO = {
    VertexShader,
    PixelShader,
    InputLayout（顶点格式），
    RasterizerState（背面剔除、填充模式、深度偏移），
    BlendState（颜色混合模式），
    DepthStencilState（深度测试、模板测试），
    RenderTargetFormats（颜色/深度缓冲格式），
    SampleCount（MSAA采样数）
}
```

### 4.2 Unity PSO预热（URP/HDRP）

Unity 2021.2+ 提供了 `Experimental.Rendering.ShaderWarmup` API：

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Experimental.Rendering;

/// <summary>
/// PSO离屏预渲染预热系统
/// 核心思路：在1x1的离屏RenderTexture上执行一次完整渲染
/// 触发驱动完成PSO创建和缓存，后续实际渲染时直接使用缓存
/// </summary>
public class PSOWarmupSystem : MonoBehaviour
{
    [Header("PSO预热配置")]
    [SerializeField] private List<Material> _materialsToWarmup;
    [SerializeField] private Mesh _warmupMesh;  // 使用简单Mesh即可（如Quad）
    
    // 离屏RT：1x1分辨率，节省GPU内存
    private RenderTexture _offscreenRT;
    private Camera _offscreenCamera;

    private void Awake()
    {
        CreateOffscreenResources();
    }

    private void CreateOffscreenResources()
    {
        // 创建1x1的离屏RT，匹配主相机格式
        _offscreenRT = new RenderTexture(1, 1, 24, RenderTextureFormat.ARGB32)
        {
            name = "PSO_Warmup_RT",
            hideFlags = HideFlags.HideAndDontSave
        };
        _offscreenRT.Create();

        // 创建专用离屏相机
        var go = new GameObject("PSO_Warmup_Camera")
        {
            hideFlags = HideFlags.HideAndDontSave
        };
        _offscreenCamera = go.AddComponent<Camera>();
        _offscreenCamera.enabled = false;
        _offscreenCamera.targetTexture = _offscreenRT;
        _offscreenCamera.cullingMask = 0;  // 不渲染任何层
    }

    /// <summary>
    /// 执行PSO预热渲染
    /// </summary>
    public void ExecutePSOWarmup()
    {
        if (_warmupMesh == null)
            _warmupMesh = CreateQuadMesh();

        // 使用CommandBuffer执行离屏预渲染
        var cmd = new CommandBuffer { name = "PSO_Warmup" };

        foreach (var material in _materialsToWarmup)
        {
            if (material == null) continue;
            
            // 在离屏RT上绘制，触发PSO创建
            cmd.SetRenderTarget(_offscreenRT);
            cmd.DrawMesh(_warmupMesh, Matrix4x4.identity, material, 0, -1);
        }

        // 执行Command Buffer
        Graphics.ExecuteCommandBuffer(cmd);
        cmd.Release();

        // 强制完成GPU操作，确保PSO已创建
        GL.Flush();
        
        Debug.Log($"[PSOWarmup] PSO预热完成，处理了 {_materialsToWarmup.Count} 个Material");
    }

    /// <summary>
    /// 使用Unity 2022+ ShaderWarmup API（推荐）
    /// </summary>
    public void ExecuteWithShaderWarmupAPI()
    {
        // ShaderWarmup.WarmupShader是Unity官方为PSO预热提供的API
        // 它会在后台处理所有变体的PSO创建
        var warmupParams = new ShaderWarmupParams();
        
        foreach (var mat in _materialsToWarmup)
        {
            if (mat == null) continue;
            // 触发shader编译和PSO创建
            // 内部会创建临时DrawCall到离屏表面
            ShaderWarmup.WarmupShader(mat.shader, warmupParams);
        }
    }

    private Mesh CreateQuadMesh()
    {
        var mesh = new Mesh { name = "WarmupQuad" };
        mesh.vertices = new Vector3[]
        {
            new Vector3(-0.5f, -0.5f, 0),
            new Vector3( 0.5f, -0.5f, 0),
            new Vector3( 0.5f,  0.5f, 0),
            new Vector3(-0.5f,  0.5f, 0)
        };
        mesh.uv = new Vector2[]
        {
            new Vector2(0, 0),
            new Vector2(1, 0),
            new Vector2(1, 1),
            new Vector2(0, 1)
        };
        mesh.triangles = new int[] { 0, 1, 2, 0, 2, 3 };
        mesh.RecalculateNormals();
        return mesh;
    }

    private void OnDestroy()
    {
        if (_offscreenRT != null)
        {
            _offscreenRT.Release();
            Destroy(_offscreenRT);
        }
        if (_offscreenCamera != null)
            Destroy(_offscreenCamera.gameObject);
    }
}
```

---

## 五、Shader变体裁剪：从源头减少变体数量

### 5.1 IPreprocessShaders接口

```csharp
#if UNITY_EDITOR
using UnityEditor.Build;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;

/// <summary>
/// Shader变体构建时裁剪处理器
/// 在打包时移除项目中实际不使用的Shader变体
/// 可以大幅减少包体大小和预热时间
/// </summary>
public class ShaderVariantStripper : IPreprocessShaders
{
    // 优先级：数值越小越先执行
    public int callbackOrder => 0;

    // 需要保留的关键字白名单
    private static readonly HashSet<string> s_AllowedKeywords = new HashSet<string>
    {
        "SHADOWS_SOFT",
        "SHADOWS_SCREEN",
        "DIRECTIONAL",
        "LIGHTMAP_ON",
        "_MAIN_LIGHT_SHADOWS",
        "_MAIN_LIGHT_SHADOWS_CASCADE",
        // 根据项目实际情况填写...
    };

    // 需要强制裁剪的关键字黑名单
    private static readonly HashSet<string> s_ForbiddenKeywords = new HashSet<string>
    {
        "INSTANCING_ON",        // 如果项目不用GPU Instancing
        "STEREO_INSTANCING_ON", // 非VR项目
        "UNITY_SINGLE_PASS_STEREO",
        "_DETAIL_MULX2",        // 如果不用Detail贴图
    };

    private int _totalVariantsIn = 0;
    private int _totalVariantsOut = 0;

    public void OnProcessShader(Shader shader, ShaderSnippetData snippet, 
                                 IList<ShaderCompilerData> shaderCompilerData)
    {
        _totalVariantsIn += shaderCompilerData.Count;

        for (int i = shaderCompilerData.Count - 1; i >= 0; i--)
        {
            if (ShouldStrip(shader, snippet, shaderCompilerData[i]))
            {
                shaderCompilerData.RemoveAt(i);
            }
        }

        _totalVariantsOut += shaderCompilerData.Count;
        
        // 打印裁剪效果
        if (shaderCompilerData.Count == 0)
        {
            Debug.Log($"[ShaderStripper] 已完全裁剪: {shader.name} / {snippet.passType}");
        }
    }

    private bool ShouldStrip(Shader shader, ShaderSnippetData snippet, 
                               ShaderCompilerData data)
    {
        var keywords = data.shaderKeywordSet;

        // 规则1：包含黑名单关键字的变体全部裁剪
        foreach (var forbidden in s_ForbiddenKeywords)
        {
            var kw = new ShaderKeyword(forbidden);
            if (keywords.IsEnabled(kw))
                return true;
        }

        // 规则2：非移动平台裁剪移动端专属变体
        #if !UNITY_ANDROID && !UNITY_IOS
        if (keywords.IsEnabled(new ShaderKeyword("_ASTC_COMPRESSED")))
            return true;
        #endif

        // 规则3：裁剪指定Shader的特定Pass
        if (shader.name.Contains("DebugShader"))
        {
            // Debug Shader只保留编辑器中使用
            return true;
        }

        return false;
    }
}
#endif
```

### 5.2 构建时变体统计工具

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// Shader变体分析工具
/// 帮助开发者了解项目中变体分布情况，找到优化重点
/// </summary>
public class ShaderVariantAnalyzer : EditorWindow
{
    [MenuItem("Tools/Shader/变体分析工具")]
    public static void ShowWindow()
    {
        GetWindow<ShaderVariantAnalyzer>("Shader变体分析");
    }

    private Vector2 _scrollPos;
    private List<(Shader shader, int count)> _variantStats;

    private void OnGUI()
    {
        GUILayout.Label("Shader变体统计分析", EditorStyles.boldLabel);
        
        if (GUILayout.Button("分析所有Shader变体"))
        {
            AnalyzeVariants();
        }

        if (_variantStats != null)
        {
            GUILayout.Space(10);
            GUILayout.Label($"总计 {_variantStats.Sum(x => x.count)} 个变体");
            GUILayout.Space(5);

            _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);
            foreach (var (shader, count) in _variantStats.OrderByDescending(x => x.count).Take(20))
            {
                EditorGUILayout.BeginHorizontal();
                GUILayout.Label(shader.name, GUILayout.Width(400));
                
                // 颜色警告：变体数过多
                var style = count > 500 ? new GUIStyle(EditorStyles.label) { normal = { textColor = Color.red } }
                          : count > 100 ? new GUIStyle(EditorStyles.label) { normal = { textColor = Color.yellow } }
                          : EditorStyles.label;
                GUILayout.Label($"{count} 变体", style);
                
                if (GUILayout.Button("选中", GUILayout.Width(60)))
                    Selection.activeObject = shader;
                
                EditorGUILayout.EndHorizontal();
            }
            EditorGUILayout.EndScrollView();
        }
    }

    private void AnalyzeVariants()
    {
        _variantStats = new List<(Shader, int)>();
        string[] guids = AssetDatabase.FindAssets("t:Shader");
        
        foreach (var guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(path);
            if (shader == null) continue;
            
            // 统计该Shader的总变体数
            int variantCount = ShaderUtil.GetVariantCount(shader, true);
            _variantStats.Add((shader, variantCount));
        }

        Debug.Log($"[ShaderVariantAnalyzer] 分析完成，共 {guids.Length} 个Shader");
    }
}
#endif
```

---

## 六、移动端专项优化

### 6.1 GLES vs Vulkan的差异

```csharp
/// <summary>
/// 移动端图形API适配器
/// 针对GLES和Vulkan的不同特性采用不同预热策略
/// </summary>
public static class MobileGraphicsAdapter
{
    public static bool IsVulkan => SystemInfo.graphicsDeviceType == GraphicsDeviceType.Vulkan;
    public static bool IsGLES3  => SystemInfo.graphicsDeviceType == GraphicsDeviceType.OpenGLES3;
    public static bool IsMetal  => SystemInfo.graphicsDeviceType == GraphicsDeviceType.Metal;

    /// <summary>
    /// 根据图形API选择最优预热策略
    /// </summary>
    public static ShaderWarmupStrategy GetOptimalStrategy()
    {
        if (IsVulkan)
        {
            // Vulkan：PSO创建开销大，必须提前预热
            // 且支持Pipeline Cache，可以持久化缓存
            return ShaderWarmupStrategy.FullPSOWarmup;
        }
        else if (IsMetal)
        {
            // Metal：系统级缓存较好，但首次仍有开销
            return ShaderWarmupStrategy.ShaderVariantWarmup;
        }
        else // GLES3
        {
            // GLES3：驱动会在后台编译，预热效果有限
            // 但仍建议预热高频使用的Shader
            return ShaderWarmupStrategy.CriticalShadersOnly;
        }
    }

    public enum ShaderWarmupStrategy
    {
        FullPSOWarmup,          // 完整PSO预热（Vulkan推荐）
        ShaderVariantWarmup,    // 变体预热（Metal推荐）
        CriticalShadersOnly     // 仅预热关键Shader（GLES3）
    }
}
```

### 6.2 Vulkan Pipeline Cache持久化

```csharp
/// <summary>
/// Vulkan Pipeline Cache持久化管理
/// 将PSO编译结果缓存到磁盘，下次启动时直接加载
/// 注意：不同设备/驱动的Cache不可复用，需按设备标识缓存
/// </summary>
public class VulkanPipelineCacheManager
{
    private static string GetCachePath()
    {
        // 按设备型号+驱动版本生成唯一缓存路径
        string deviceKey = $"{SystemInfo.graphicsDeviceID}_{SystemInfo.graphicsDeviceVendorID}";
        string driverKey = SystemInfo.graphicsDeviceVersion.GetHashCode().ToString("X8");
        return System.IO.Path.Combine(
            Application.persistentDataPath, 
            "PSO_Cache", 
            $"{deviceKey}_{driverKey}.bin"
        );
    }

    public static bool HasCache()
    {
        return System.IO.File.Exists(GetCachePath());
    }

    public static void LogCacheInfo()
    {
        string path = GetCachePath();
        if (System.IO.File.Exists(path))
        {
            var info = new System.IO.FileInfo(path);
            Debug.Log($"[VulkanPSO] 发现Pipeline Cache: {info.Length / 1024}KB，" +
                     $"创建时间: {info.CreationTime}");
        }
        else
        {
            Debug.Log("[VulkanPSO] 未找到Pipeline Cache，本次将重新编译PSO");
        }
    }

    // Unity侧无法直接控制Vulkan Pipeline Cache
    // 但可以通过PlayerSettings配置启用
    // Edit → Project Settings → Player → Android → Vulkan Settings
    // → 勾选 "Apply display rotation during rendering"
    // → 同时确保 "ASTC HDR Textures" 等选项匹配目标设备
}
```

---

## 七、完整预热系统架构

```csharp
/// <summary>
/// 统一Shader预热入口
/// 在GameManager或App启动流程中调用
/// </summary>
public class GameStartupWarmup : MonoBehaviour
{
    [Header("预热资源")]
    [SerializeField] private ShaderVariantCollection[] _criticalCollections;
    [SerializeField] private ShaderVariantCollection[] _normalCollections;
    [SerializeField] private Material[] _psoWarmupMaterials;

    public async System.Threading.Tasks.Task<bool> ExecuteFullWarmupAsync(
        System.IProgress<float> progress = null,
        System.Threading.CancellationToken ct = default)
    {
        float totalSteps = 3f;
        int currentStep = 0;

        // Step 1: 预热关键Shader变体（角色、UI等高频使用）
        Debug.Log("[Startup] Step 1/3: 预热关键Shader变体...");
        foreach (var svc in _criticalCollections)
        {
            if (ct.IsCancellationRequested) return false;
            if (svc != null) svc.WarmUp();
        }
        progress?.Report(++currentStep / totalSteps);

        // Step 2: PSO离屏预热
        Debug.Log("[Startup] Step 2/3: PSO管线预热...");
        var psoWarmup = GetComponent<PSOWarmupSystem>();
        if (psoWarmup != null && MobileGraphicsAdapter.IsVulkan)
        {
            psoWarmup.ExecutePSOWarmup();
        }
        // 等待1帧，让GPU完成PSO创建
        await System.Threading.Tasks.Task.Yield();
        progress?.Report(++currentStep / totalSteps);

        // Step 3: 预热普通Shader变体（场景环境等）
        Debug.Log("[Startup] Step 3/3: 预热普通Shader变体...");
        foreach (var svc in _normalCollections)
        {
            if (ct.IsCancellationRequested) return false;
            if (svc != null) svc.WarmUp();
        }
        progress?.Report(++currentStep / totalSteps);

        Debug.Log("[Startup] Shader预热全部完成！");
        return true;
    }
}
```

---

## 八、最佳实践总结

### 8.1 建设性原则

| 阶段 | 操作 | 工具/API |
|------|------|---------|
| 开发期 | 收集实际使用的变体 | ShaderVariantCollector |
| 构建期 | 裁剪无用变体 | IPreprocessShaders |
| 运行时 | 分帧预热变体 | ShaderVariantCollection.WarmUp() |
| 首帧 | PSO离屏预热 | CommandBuffer + OffscreenRT |
| Vulkan | Pipeline Cache持久化 | PlayerSettings配置 |

### 8.2 常见陷阱

1. **预热时机太晚**：必须在首次渲染相关内容**之前**完成预热
2. **变体收集不完整**：容易漏掉动态材质（运行时设置关键字的情况）
3. **GLES驱动差异**：部分Android驱动即使预热也会重新编译
4. **PSO格式不匹配**：离屏预热RT的格式必须与实际渲染目标格式一致

### 8.3 验证方法

```csharp
// 使用Profiler标记验证预热效果
using Unity.Profiling;

ProfilerMarker s_ShaderCompileMarker = new ProfilerMarker("Shader.Parse");
ProfilerMarker s_PSOCreateMarker = new ProfilerMarker("GfxDevice.CreateGeometry");

// 在Profiler中观察这两个标记：
// - 预热前：游戏过程中频繁出现
// - 预热后：仅在预热阶段出现，游戏过程中消失
```

### 8.4 效果指标参考

| 优化措施 | 效果 |
|---------|------|
| ShaderVariantCollection预热 | 消除80%~90%的Shader编译卡顿 |
| Shader变体裁剪 | 减少50%~70%的包体Shader大小 |
| PSO离屏预热（Vulkan） | 消除首帧100ms~500ms卡顿 |
| Vulkan Pipeline Cache | 二次启动PSO创建时间减少60%~80% |

---

## 总结

Shader预编译与PSO管线缓存是消除游戏卡顿的关键技术。核心要素：

1. **收集阶段**：用录制工具或代码收集完整的ShaderVariantCollection
2. **裁剪阶段**：用IPreprocessShaders在构建时移除无用变体
3. **预热阶段**：游戏启动Loading期间分帧预热，不阻塞主线程
4. **PSO预热**：使用离屏渲染触发PSO创建，彻底消除首帧卡顿
5. **持久化缓存**：Vulkan环境下启用Pipeline Cache，加快后续启动速度

合理运用这套体系，可以将玩家体验到的Stutter卡顿降低90%以上，是商业游戏上线前必不可少的优化环节。
