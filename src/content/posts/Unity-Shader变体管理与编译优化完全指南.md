---
title: Unity Shader变体管理与编译优化完全指南
published: 2026-03-27
description: 深入讲解 Unity Shader 变体（Shader Variant）的产生机制、收集策略、预编译管理、运行时加载优化，以及大型项目中的变体爆炸问题治理方案，结合完整代码示例与工程实践。
tags: [Shader, Shader变体, ShaderVariant, 编译优化, Unity, 渲染优化, 打包优化, 移动端]
category: 渲染技术
draft: false
---

# Unity Shader变体管理与编译优化完全指南

## 一、Shader 变体的本质与危害

### 1.1 什么是 Shader 变体

Shader 变体（Shader Variant）是 Unity 编译器根据 `#pragma multi_compile` 和 `#pragma shader_feature` 宏为每种关键字组合生成的独立 Shader 程序版本：

```hlsl
// 示例 Shader（产生多少变体？）
Shader "Game/Character"
{
    SubShader
    {
        Pass
        {
            HLSLPROGRAM
            
            // multi_compile：打包时保留所有变体，无论是否使用
            #pragma multi_compile _ MAIN_LIGHT_SHADOWS
            #pragma multi_compile _ MAIN_LIGHT_SHADOWS_CASCADE MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile _ ADDITIONAL_LIGHTS_VERTEX ADDITIONAL_LIGHTS
            #pragma multi_compile_fragment _ SHADOWS_SOFT
            
            // shader_feature：只保留材质中实际启用的变体
            #pragma shader_feature_local _NORMALMAP
            #pragma shader_feature_local _EMISSION
            #pragma shader_feature_local _METALLIC_MAP _ROUGHNESS_MAP
            
            // 内置变体（Unity 自动添加）
            // #pragma multi_compile_fog
            // #pragma multi_compile_instancing
            
            ENDHLSL
        }
    }
}

/*
 变体计算：
 MAIN_LIGHT_SHADOWS：          2 种（ON/OFF）
 MAIN_LIGHT_SHADOWS_CASCADE：  3 种
 ADDITIONAL_LIGHTS：           3 种
 SHADOWS_SOFT：                2 种
 _NORMALMAP：                  2 种
 _EMISSION：                   2 种
 _METALLIC/ROUGHNESS：         3 种
 
 总计（仅 multi_compile）：2×3×3×2 = 36 个变体
 加上 shader_feature：×2×2×3 = 36×12 = 432 个变体！
 
 再乘以平台数（iOS/Android/PC）和 Pass 数...
 大型项目轻松达到数万个变体
*/
```

### 1.2 变体爆炸的危害

| 危害类型 | 具体表现 | 影响程度 |
|---------|---------|---------|
| 打包体积膨胀 | 每个变体编译后的字节码都占包体 | ⚠️ 严重 |
| 加载时间延长 | 运行时编译/加载变体造成卡顿 | ⚠️ 严重 |
| 内存占用增加 | GPU Program 缓存占用 | ⚠️ 中等 |
| 构建时间暴增 | CI 构建从10分钟变成60分钟 | ⚠️ 中等 |
| 首次渲染卡顿 | 第一次使用某个材质触发 JIT 编译 | ⚠️ 严重 |

---

## 二、理解 multi_compile vs shader_feature

### 2.1 核心区别

```hlsl
// =============================================
// multi_compile：强制包含所有变体
// =============================================
#pragma multi_compile _ SHADOWS_ENABLED

// → 打包时无论材质用不用，两个变体都包含
// → 可在运行时用 Shader.EnableKeyword() 动态切换
// → 适用：全局渲染特性开关（阴影、雾效等）

// =============================================
// shader_feature：仅包含材质实际使用的变体
// =============================================
#pragma shader_feature _NORMALMAP

// → 打包时扫描所有材质，只包含用到的变体
// → 不能在运行时动态切换（材质未包含对应变体）
// → 适用：材质特有功能（法线贴图、自发光等）

// =============================================
// shader_feature_local：限定为本 Shader 的局部关键字
// =============================================
#pragma shader_feature_local _EMISSION  // 推荐！

// → 关键字不污染全局关键字空间（上限 256 个）
// → shader_feature_local 上限 64 个（不影响全局）
// → 大型项目务必优先使用 _local 变体
```

### 2.2 关键字空间限制

```csharp
// 检测全局关键字数量（防止超限）
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.Linq;

public class ShaderKeywordAnalyzer
{
    [MenuItem("Tools/Shader/Analyze Global Keywords")]
    public static void AnalyzeGlobalKeywords()
    {
        var allShaders = Resources.FindObjectsOfTypeAll<Shader>();
        var globalKeywords = new HashSet<string>();
        var localKeywords = new Dictionary<string, List<string>>();
        
        foreach (var shader in allShaders)
        {
            // 使用 ShaderUtil 获取关键字（Editor Only）
            #if UNITY_EDITOR
            var keywords = ShaderUtil.GetShaderGlobalKeywords(shader);
            foreach (var kw in keywords)
                globalKeywords.Add(kw);
            
            var localKws = ShaderUtil.GetShaderLocalKeywords(shader);
            if (localKws.Length > 0)
                localKeywords[shader.name] = new List<string>(localKws);
            #endif
        }
        
        Debug.Log($"[Shader分析] 全局关键字总数: {globalKeywords.Count}/256");
        
        if (globalKeywords.Count > 200)
        {
            Debug.LogWarning($"⚠️ 全局关键字即将超限！当前 {globalKeywords.Count}/256");
        }
        
        // 输出高频关键字
        Debug.Log("全局关键字列表（按名称排序）:\n" + 
                  string.Join("\n", globalKeywords.OrderBy(k => k).Take(30)));
    }
}
```

---

## 三、Shader 变体收集系统

### 3.1 ShaderVariantCollection 机制

```csharp
// Shader 变体收集工具（Editor）
using UnityEditor;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;
using System.IO;

public class ShaderVariantCollector : EditorWindow
{
    private string outputPath = "Assets/ShaderVariants/CollectedVariants.shadervariants";
    private bool includeEditorShaders = false;
    
    [MenuItem("Tools/Shader/Variant Collector")]
    static void ShowWindow()
    {
        GetWindow<ShaderVariantCollector>("变体收集器");
    }
    
    private void OnGUI()
    {
        GUILayout.Label("Shader 变体收集工具", EditorStyles.boldLabel);
        outputPath = EditorGUILayout.TextField("输出路径", outputPath);
        includeEditorShaders = EditorGUILayout.Toggle("包含编辑器 Shader", includeEditorShaders);
        
        EditorGUILayout.Space();
        
        if (GUILayout.Button("从所有材质收集变体"))
            CollectVariantsFromMaterials();
        
        if (GUILayout.Button("分析当前 ShaderVariantCollection"))
            AnalyzeExistingCollection();
        
        if (GUILayout.Button("过滤冗余变体"))
            StripUnusedVariants();
    }
    
    // 从项目所有材质中收集变体
    private void CollectVariantsFromMaterials()
    {
        var collection = new ShaderVariantCollection();
        var materialGuids = AssetDatabase.FindAssets("t:Material");
        
        int processed = 0;
        var shaderVariantMap = new Dictionary<Shader, HashSet<ShaderVariantCollection.ShaderVariant>>();
        
        foreach (var guid in materialGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat == null || mat.shader == null) continue;
            
            // 跳过编辑器 Shader
            if (!includeEditorShaders && mat.shader.name.StartsWith("Hidden/")) continue;
            
            // 获取材质启用的关键字
            var enabledKeywords = mat.enabledKeywords;
            var keywordStrings = new string[enabledKeywords.Length];
            for (int i = 0; i < enabledKeywords.Length; i++)
                keywordStrings[i] = enabledKeywords[i].name;
            
            // 为每个 Pass 创建变体
            int passCount = mat.shader.passCount;
            for (int passIdx = 0; passIdx < passCount; passIdx++)
            {
                // 获取 Pass 类型
                var passType = mat.GetPassName(passIdx) switch
                {
                    "UniversalForward" => PassType.Normal,
                    "ShadowCaster" => PassType.ShadowCaster,
                    "DepthOnly" => PassType.Deferred,
                    _ => PassType.Normal
                };
                
                var variant = new ShaderVariantCollection.ShaderVariant(
                    mat.shader, passType, keywordStrings);
                
                collection.Add(variant);
            }
            
            processed++;
            EditorUtility.DisplayProgressBar("收集变体", $"处理 {processed}/{materialGuids.Length}", 
                (float)processed / materialGuids.Length);
        }
        
        EditorUtility.ClearProgressBar();
        
        // 确保目录存在
        string dir = Path.GetDirectoryName(outputPath);
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
        
        AssetDatabase.CreateAsset(collection, outputPath);
        AssetDatabase.SaveAssets();
        
        Debug.Log($"[变体收集] 完成！共收集 {collection.variantCount} 个变体 → {outputPath}");
    }
    
    // 分析变体集合的统计信息
    private void AnalyzeExistingCollection()
    {
        var collection = AssetDatabase.LoadAssetAtPath<ShaderVariantCollection>(outputPath);
        if (collection == null)
        {
            Debug.LogError($"无法加载 {outputPath}");
            return;
        }
        
        Debug.Log($"[变体分析]\n" +
                  $"  总变体数: {collection.variantCount}\n" +
                  $"  Shader 数: {collection.shaderCount}");
    }
    
    // 过滤冗余变体（移除不需要的关键字组合）
    private void StripUnusedVariants()
    {
        var collection = AssetDatabase.LoadAssetAtPath<ShaderVariantCollection>(outputPath);
        if (collection == null) return;
        
        int before = collection.variantCount;
        
        // 这里实现自定义过滤逻辑
        // 例如：移除非移动端平台的 PC-only 变体
        
        int after = collection.variantCount;
        Debug.Log($"[变体过滤] {before} → {after}，减少 {before - after} 个变体");
    }
}
```

### 3.2 运行时录制变体（Play Mode 收集）

```csharp
// 运行时自动变体录制系统
using UnityEngine;
using UnityEngine.Rendering;

public class RuntimeVariantRecorder : MonoBehaviour
{
    #if UNITY_EDITOR
    private UnityEditor.ShaderVariantCollection recordingCollection;
    private bool isRecording = false;
    
    [UnityEditor.MenuItem("Tools/Shader/Start Runtime Recording")]
    static void StartRecording()
    {
        if (!Application.isPlaying)
        {
            Debug.LogError("请在 Play Mode 下使用！");
            return;
        }
        
        var recorder = FindObjectOfType<RuntimeVariantRecorder>();
        if (recorder == null)
        {
            var go = new GameObject("_ShaderVariantRecorder");
            recorder = go.AddComponent<RuntimeVariantRecorder>();
        }
        recorder.BeginRecording();
    }
    
    [UnityEditor.MenuItem("Tools/Shader/Stop and Save Recording")]
    static void StopRecording()
    {
        var recorder = FindObjectOfType<RuntimeVariantRecorder>();
        recorder?.StopAndSave();
    }
    
    public void BeginRecording()
    {
        recordingCollection = new UnityEditor.ShaderVariantCollection();
        ShaderVariantCollection.WarmUp();  // 清除缓存，确保录制准确
        
        // 开始录制新变体
        isRecording = true;
        Debug.Log("[变体录制] 开始！请执行游戏中的各种操作来覆盖所有场景...");
    }
    
    public void StopAndSave()
    {
        if (!isRecording) return;
        isRecording = false;
        
        // 保存录制结果
        string savePath = $"Assets/ShaderVariants/Runtime_Recorded_{System.DateTime.Now:yyyyMMdd_HHmm}.shadervariants";
        UnityEditor.AssetDatabase.CreateAsset(recordingCollection, savePath);
        UnityEditor.AssetDatabase.SaveAssets();
        
        Debug.Log($"[变体录制] 完成！已保存到 {savePath}\n" +
                  $"收录变体数: {recordingCollection.variantCount}");
    }
    #endif
}
```

---

## 四、变体预热（Shader Warmup）

### 4.1 为什么需要 Warmup

```
未预热的场景：
  玩家进入新场景 
  → 渲染新材质 
  → 驱动发现变体未编译 
  → GPU JIT 编译（50ms~300ms！）
  → 玩家感知到卡顿/掉帧

预热后的场景：
  Loading 阶段预热所有变体 
  → 进入场景 
  → 所有变体已在 GPU 缓存中 
  → 零延迟渲染
```

### 4.2 分帧渐进式 Warmup

```csharp
// 分帧预热系统（避免 Loading 时单帧冻结）
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections;
using System.Collections.Generic;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;

public class ShaderWarmupManager : MonoBehaviour
{
    [Header("变体集合资产")]
    [SerializeField] private ShaderVariantCollection mainVariantCollection;
    [SerializeField] private AssetReference[] additionalCollectionRefs;
    
    [Header("预热策略")]
    [SerializeField] private int variantsPerFrame = 10;       // 每帧预热数量
    [SerializeField] private bool warmupOnStart = true;
    [SerializeField] private bool enableProgressCallback = true;
    
    public event System.Action<float> OnWarmupProgress;  // 进度 [0,1]
    public event System.Action OnWarmupComplete;
    
    private bool isWarmedUp = false;
    
    private void Start()
    {
        if (warmupOnStart)
            StartCoroutine(ProgressiveWarmup());
    }
    
    // 阻塞式全量预热（在 Loading 画面使用）
    public void WarmupAll()
    {
        if (mainVariantCollection != null)
        {
            mainVariantCollection.WarmUp();
            Debug.Log($"[Shader Warmup] 全量预热完成，{mainVariantCollection.variantCount} 个变体");
        }
        isWarmedUp = true;
    }
    
    // 分帧渐进式预热（推荐：在 Loading 进度条期间）
    public IEnumerator ProgressiveWarmup()
    {
        if (mainVariantCollection == null)
        {
            Debug.LogWarning("[Shader Warmup] 未指定 ShaderVariantCollection！");
            OnWarmupComplete?.Invoke();
            yield break;
        }
        
        // 先加载附加变体集合
        var allCollections = new List<ShaderVariantCollection> { mainVariantCollection };
        foreach (var assetRef in additionalCollectionRefs)
        {
            var handle = assetRef.LoadAssetAsync<ShaderVariantCollection>();
            yield return handle;
            if (handle.Status == AsyncOperationStatus.Succeeded)
                allCollections.Add(handle.Result);
        }
        
        // 分批次预热
        int totalVariants = 0;
        foreach (var col in allCollections)
            totalVariants += col.variantCount;
        
        int warmedCount = 0;
        float startTime = Time.realtimeSinceStartup;
        
        // Unity 的 WarmUp 是同步全量的，无法逐个预热
        // 我们通过 time-slicing 分帧控制
        foreach (var col in allCollections)
        {
            float batchStart = Time.realtimeSinceStartup;
            
            // 异步分批预热（利用 Graphics.WarmupAllShaders() 的底层机制）
            col.WarmUp();  // 本身是同步的，但可以在加载线程/Loading帧执行
            
            warmedCount += col.variantCount;
            float progress = (float)warmedCount / totalVariants;
            OnWarmupProgress?.Invoke(progress);
            
            float elapsed = Time.realtimeSinceStartup - batchStart;
            Debug.Log($"[Shader Warmup] 批次完成，{col.variantCount} 个变体，耗时 {elapsed * 1000f:F1}ms");
            
            // 给渲染线程喘息机会
            yield return null;
        }
        
        isWarmedUp = true;
        float totalTime = Time.realtimeSinceStartup - startTime;
        Debug.Log($"[Shader Warmup] 全部完成！{totalVariants} 个变体，总耗时 {totalTime * 1000f:F1}ms");
        
        OnWarmupComplete?.Invoke();
    }
    
    // 场景切换时的增量预热（仅预热新场景的变体）
    public IEnumerator WarmupForScene(string sceneName)
    {
        string collectionPath = $"ShaderVariants/Scene_{sceneName}";
        var handle = Addressables.LoadAssetAsync<ShaderVariantCollection>(collectionPath);
        yield return handle;
        
        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            var collection = handle.Result;
            collection.WarmUp();
            Debug.Log($"[Shader Warmup] 场景 {sceneName} 增量预热完成，{collection.variantCount} 个变体");
        }
    }
}
```

### 4.3 Loading 界面集成

```csharp
// Loading 界面集成预热
using UnityEngine;
using UnityEngine.UI;
using System.Collections;

public class GameLoadingScreen : MonoBehaviour
{
    [SerializeField] private Slider progressSlider;
    [SerializeField] private Text statusText;
    [SerializeField] private ShaderWarmupManager warmupManager;
    
    // 加载阶段权重分配
    private const float WEIGHT_ASSETS = 0.6f;
    private const float WEIGHT_SHADER_WARMUP = 0.3f;
    private const float WEIGHT_INIT = 0.1f;
    
    private float currentProgress = 0f;
    
    private void Start()
    {
        StartCoroutine(LoadingSequence());
    }
    
    private IEnumerator LoadingSequence()
    {
        // 阶段1：资源加载（60%）
        statusText.text = "加载游戏资源...";
        yield return StartCoroutine(LoadGameAssets(progress => {
            currentProgress = progress * WEIGHT_ASSETS;
            UpdateProgressUI(currentProgress);
        }));
        
        // 阶段2：Shader 预热（30%）
        statusText.text = "预热着色器...";
        warmupManager.OnWarmupProgress += (p) => {
            currentProgress = WEIGHT_ASSETS + p * WEIGHT_SHADER_WARMUP;
            UpdateProgressUI(currentProgress);
        };
        
        yield return StartCoroutine(warmupManager.ProgressiveWarmup());
        
        // 阶段3：系统初始化（10%）
        statusText.text = "初始化游戏系统...";
        yield return StartCoroutine(InitializeGameSystems(progress => {
            currentProgress = WEIGHT_ASSETS + WEIGHT_SHADER_WARMUP + progress * WEIGHT_INIT;
            UpdateProgressUI(currentProgress);
        }));
        
        // 进入游戏
        statusText.text = "准备完毕！";
        UpdateProgressUI(1f);
        yield return new WaitForSeconds(0.3f);
        
        // UnityEngine.SceneManagement.SceneManager.LoadScene("MainGame");
    }
    
    private void UpdateProgressUI(float progress)
    {
        progressSlider.value = progress;
    }
    
    private IEnumerator LoadGameAssets(System.Action<float> progressCallback)
    {
        // 模拟资源加载
        for (int i = 0; i <= 100; i++)
        {
            progressCallback?.Invoke(i / 100f);
            yield return null;
        }
    }
    
    private IEnumerator InitializeGameSystems(System.Action<float> progressCallback)
    {
        progressCallback?.Invoke(0.5f);
        yield return null;
        progressCallback?.Invoke(1f);
    }
}
```

---

## 五、构建时变体裁剪

### 5.1 IPreprocessShaders 接口

```csharp
// 自定义构建时变体裁剪器
using UnityEditor.Build;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;

public class ShaderVariantStripper : IPreprocessShaders
{
    // 裁剪优先级（数值越小越早执行）
    public int callbackOrder => 100;
    
    // 需要保留的关键字白名单
    private static readonly HashSet<string> MobileAllowedKeywords = new HashSet<string>
    {
        "_NORMALMAP",
        "_EMISSION",
        "MAIN_LIGHT_SHADOWS",
        "SHADOWS_SOFT",
        "_ADDITIONAL_LIGHTS",
        "FOG_LINEAR",
        "INSTANCING_ON",
    };
    
    // 移动端不需要的关键字（强制裁剪）
    private static readonly HashSet<string> MobileStrippedKeywords = new HashSet<string>
    {
        "MAIN_LIGHT_SHADOWS_SCREEN",    // 屏幕空间阴影（移动端不支持）
        "SCREEN_SPACE_OCCLUSION",        // SSAO（移动端关闭）
        "_DETAIL_MULX2",                 // 细节贴图（低端机不用）
        "LIGHTMAP_SHADOW_MIXING",        // 光照贴图阴影混合（性能换质量）
        "SHADOWS_SHADOWMASK",            // Shadow Mask（烘焙项目可能需要）
        "DIRLIGHTMAP_COMBINED",          // 方向光照贴图（省内存可去掉）
        "_REFLECTION_PROBE_BLENDING",    // 反射探针混合（高端才需要）
        "DYNAMICLIGHTMAP_ON",            // 动态 GI
    };
    
    private int totalVariants = 0;
    private int strippedVariants = 0;
    
    public void OnProcessShader(Shader shader, ShaderSnippetData snippet, IList<ShaderCompilerData> data)
    {
        // 判断当前构建目标
        bool isMobile = IsTargetMobile(snippet);
        
        // 日志统计
        int before = data.Count;
        totalVariants += before;
        
        for (int i = data.Count - 1; i >= 0; i--)
        {
            if (ShouldStripVariant(data[i], shader, snippet, isMobile))
            {
                data.RemoveAt(i);
                strippedVariants++;
            }
        }
        
        int after = data.Count;
        if (before != after)
        {
            Debug.Log($"[变体裁剪] {shader.name} ({snippet.passName}): " +
                      $"{before} → {after} 个变体 (裁剪了 {before - after})");
        }
    }
    
    private bool ShouldStripVariant(ShaderCompilerData data, Shader shader, 
                                     ShaderSnippetData snippet, bool isMobile)
    {
        var keywords = data.shaderKeywordSet;
        
        // 1. 移动端强制裁剪
        if (isMobile)
        {
            foreach (var stripped in MobileStrippedKeywords)
            {
                if (keywords.IsEnabled(new ShaderKeyword(stripped)))
                    return true;  // 裁剪掉
            }
        }
        
        // 2. 无效关键字组合裁剪（互斥关键字同时开启）
        bool hasCascade = keywords.IsEnabled(new ShaderKeyword("MAIN_LIGHT_SHADOWS_CASCADE"));
        bool hasScreen = keywords.IsEnabled(new ShaderKeyword("MAIN_LIGHT_SHADOWS_SCREEN"));
        if (hasCascade && hasScreen)
            return true;  // 两种阴影模式不能同时开启
        
        // 3. 裁剪不在白名单中的关键字（严格模式）
        // 此模式仅在你完全清楚所需变体时使用
        /*
        if (IsStrictModeEnabled())
        {
            foreach (var kw in GetEnabledKeywords(keywords))
            {
                if (!MobileAllowedKeywords.Contains(kw))
                    return true;
            }
        }
        */
        
        return false;
    }
    
    private bool IsTargetMobile(ShaderSnippetData snippet)
    {
        // 通过 EditorUserBuildSettings 判断当前构建目标
        #if UNITY_EDITOR
        return UnityEditor.EditorUserBuildSettings.activeBuildTarget == 
               UnityEditor.BuildTarget.Android ||
               UnityEditor.EditorUserBuildSettings.activeBuildTarget == 
               UnityEditor.BuildTarget.iOS;
        #else
        return false;
        #endif
    }
}
```

### 5.2 URP 专用变体裁剪

```csharp
// URP Shader Graph 变体裁剪
using UnityEditor.Build;
using UnityEditor.Rendering;
using UnityEngine.Rendering;
using System.Collections.Generic;

public class URPVariantStripper : IPreprocessShaders
{
    public int callbackOrder => 200;
    
    // URP 变体裁剪配置
    private struct URPStripConfig
    {
        public bool stripShadowCascades;
        public bool stripShadowScreen;
        public bool stripSSAO;
        public bool stripDeferredRendering;
        public bool stripDebugDisplay;
        public bool stripXRKeywords;
    }
    
    private URPStripConfig GetStripConfig()
    {
        // 可从 Project Settings 或自定义 ScriptableObject 读取
        return new URPStripConfig
        {
            stripShadowCascades = false,
            stripShadowScreen = true,    // 移动端关闭屏幕空间阴影
            stripSSAO = true,            // 移动端关闭 SSAO
            stripDeferredRendering = true, // 移动端无延迟渲染
            stripDebugDisplay = true,    // 发布版本去掉调试关键字
            stripXRKeywords = true       // 非 XR 项目去掉 XR 关键字
        };
    }
    
    // URP 需要裁剪的 Shader 关键字映射
    private static readonly Dictionary<string, string[]> URPKeywordStrip = new Dictionary<string, string[]>
    {
        ["Mobile"] = new[]
        {
            "_SCREEN_SPACE_OCCLUSION",
            "MAIN_LIGHT_SHADOWS_SCREEN",
            "_DEFERRED_RENDERING",
            "_GBUFFER_NORMALS_OCT",
            "DEBUG_DISPLAY",
            "USE_UNITY_CROSSFADE",
        },
        ["PC"] = new[]
        {
            "DEBUG_DISPLAY",  // 发布版统一去掉
        }
    };
    
    private static readonly HashSet<string> XRKeywords = new HashSet<string>
    {
        "UNITY_SINGLE_PASS_STEREO",
        "STEREO_INSTANCING_ON",
        "STEREO_MULTIVIEW_ON",
    };
    
    public void OnProcessShader(Shader shader, ShaderSnippetData snippet, IList<ShaderCompilerData> data)
    {
        // 只处理 URP 相关 Shader
        if (!IsURPShader(shader)) return;
        
        var config = GetStripConfig();
        
        for (int i = data.Count - 1; i >= 0; i--)
        {
            if (ShouldStripURPVariant(data[i], config))
                data.RemoveAt(i);
        }
    }
    
    private bool IsURPShader(Shader shader)
    {
        return shader.name.Contains("Universal Render Pipeline") ||
               shader.name.Contains("URP") ||
               shader.name.Contains("Lit") ||
               shader.name.Contains("SimpleUnlit");
    }
    
    private bool ShouldStripURPVariant(ShaderCompilerData data, URPStripConfig config)
    {
        var keywords = data.shaderKeywordSet;
        
        if (config.stripShadowScreen && 
            keywords.IsEnabled(new ShaderKeyword("MAIN_LIGHT_SHADOWS_SCREEN")))
            return true;
        
        if (config.stripSSAO && 
            keywords.IsEnabled(new ShaderKeyword("_SCREEN_SPACE_OCCLUSION")))
            return true;
        
        if (config.stripDeferredRendering && 
            keywords.IsEnabled(new ShaderKeyword("_DEFERRED_RENDERING")))
            return true;
        
        if (config.stripDebugDisplay && 
            keywords.IsEnabled(new ShaderKeyword("DEBUG_DISPLAY")))
            return true;
        
        if (config.stripXRKeywords)
        {
            foreach (var xrKw in XRKeywords)
            {
                if (keywords.IsEnabled(new ShaderKeyword(xrKw)))
                    return true;
            }
        }
        
        return false;
    }
}
```

---

## 六、运行时 Shader 管理优化

### 6.1 Shader 异步编译

```csharp
// 异步 Shader 编译管理器（Unity 2021.2+）
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;

public class AsyncShaderCompileManager : MonoBehaviour
{
    [Header("异步编译设置")]
    [SerializeField] private bool enableAsyncCompile = true;
    [SerializeField] private Material placeholderMaterial;  // 编译期间的占位材质
    
    // 待编译的 Shader 队列
    private Queue<(Material mat, System.Action<Material> callback)> pendingCompiles;
    
    private void Awake()
    {
        pendingCompiles = new Queue<(Material, System.Action<Material>)>();
        
        // 启用异步着色器编译（减少运行时卡顿）
        #if UNITY_EDITOR
        UnityEditor.EditorSettings.asyncShaderCompilation = enableAsyncCompile;
        #endif
    }
    
    // 请求异步编译一个 Shader
    public void RequestAsyncCompile(Material material, System.Action<Material> onReady)
    {
        if (material == null) return;
        
        // 检查是否已就绪（Shader 已编译）
        if (IsShaderReady(material.shader))
        {
            onReady?.Invoke(material);
            return;
        }
        
        // 加入等待队列，先用占位材质显示
        pendingCompiles.Enqueue((material, onReady));
    }
    
    private bool IsShaderReady(Shader shader)
    {
        // Unity 提供的 API（2021.2+）
        // return !ShaderUtil.anythingCompiling;  // 全局判断
        return true;  // 简化示例
    }
    
    private void Update()
    {
        // 检查队列中的 Shader 是否已编译完成
        int checkCount = Mathf.Min(5, pendingCompiles.Count);
        for (int i = 0; i < checkCount; i++)
        {
            var (mat, callback) = pendingCompiles.Peek();
            if (IsShaderReady(mat.shader))
            {
                pendingCompiles.Dequeue();
                callback?.Invoke(mat);
            }
            else break;  // 队列有序，第一个未就绪则停止检查
        }
    }
}
```

### 6.2 Shader 变体按需加载（AssetBundle）

```csharp
// 按需加载 Shader 变体的策略
using UnityEngine;
using UnityEngine.AddressableAssets;
using System.Collections;
using System.Collections.Generic;

public class ShaderVariantStreamingManager : MonoBehaviour
{
    // 场景 → 变体集合的映射
    private static readonly Dictionary<string, string> SceneVariantMap = new Dictionary<string, string>
    {
        ["City"]    = "ShaderVariants/City.shadervariants",
        ["Forest"]  = "ShaderVariants/Forest.shadervariants",
        ["Dungeon"] = "ShaderVariants/Dungeon.shadervariants",
    };
    
    private HashSet<string> loadedScenes = new HashSet<string>();
    private Dictionary<string, ShaderVariantCollection> cachedCollections = 
        new Dictionary<string, ShaderVariantCollection>();
    
    // 场景加载前预热对应变体
    public IEnumerator PrepareForScene(string sceneName)
    {
        if (loadedScenes.Contains(sceneName)) yield break;
        
        if (!SceneVariantMap.TryGetValue(sceneName, out var assetPath))
        {
            Debug.LogWarning($"[ShaderVariant] 未找到场景 {sceneName} 的变体集合");
            yield break;
        }
        
        // 加载变体集合
        var handle = Addressables.LoadAssetAsync<ShaderVariantCollection>(assetPath);
        yield return handle;
        
        if (handle.Status == UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationStatus.Succeeded)
        {
            var collection = handle.Result;
            cachedCollections[sceneName] = collection;
            
            // 异步预热（分散到多帧）
            float startTime = Time.realtimeSinceStartup;
            collection.WarmUp();
            float elapsed = (Time.realtimeSinceStartup - startTime) * 1000f;
            
            loadedScenes.Add(sceneName);
            Debug.Log($"[ShaderVariant] 场景 {sceneName} 变体预热完成，" +
                      $"{collection.variantCount} 个变体，耗时 {elapsed:F1}ms");
        }
    }
    
    // 场景卸载时释放变体集合
    public void UnloadSceneVariants(string sceneName)
    {
        if (cachedCollections.TryGetValue(sceneName, out var collection))
        {
            Addressables.Release(collection);
            cachedCollections.Remove(sceneName);
            loadedScenes.Remove(sceneName);
            Debug.Log($"[ShaderVariant] 已卸载场景 {sceneName} 的变体集合");
        }
    }
}
```

---

## 七、变体数量监控与 CI 集成

### 7.1 构建报告分析

```csharp
// 构建后的 Shader 变体统计报告
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using System.Collections.Generic;
using System.Text;

public class ShaderVariantBuildReport : IPostprocessBuildWithReport
{
    public int callbackOrder => 0;
    
    public void OnPostprocessBuild(BuildReport report)
    {
        AnalyzeShaderVariants(report);
    }
    
    private void AnalyzeShaderVariants(BuildReport report)
    {
        var sb = new StringBuilder();
        sb.AppendLine("=== Shader 变体构建报告 ===");
        sb.AppendLine($"构建目标: {report.summary.platform}");
        sb.AppendLine($"构建时间: {report.summary.buildEndedAt - report.summary.buildStartedAt:mm\\:ss}");
        sb.AppendLine();
        
        // 统计所有 Shader 的大小
        ulong totalShaderSize = 0;
        var shaderFiles = new Dictionary<string, ulong>();
        
        foreach (var file in report.GetFiles())
        {
            if (file.path.EndsWith(".shader") || file.type == BuildFileType.DebugInfo)
            {
                totalShaderSize += file.size;
                shaderFiles[file.path] = file.size;
            }
        }
        
        sb.AppendLine($"Shader 总大小: {FormatBytes(totalShaderSize)}");
        sb.AppendLine($"包体总大小: {FormatBytes(report.summary.totalSize)}");
        sb.AppendLine($"Shader 占比: {(float)totalShaderSize / report.summary.totalSize * 100:F1}%");
        sb.AppendLine();
        
        // 检查是否超过阈值
        const ulong SHADER_SIZE_LIMIT = 50 * 1024 * 1024;  // 50 MB 警戒线
        if (totalShaderSize > SHADER_SIZE_LIMIT)
        {
            sb.AppendLine($"⚠️ 警告：Shader 大小 {FormatBytes(totalShaderSize)} 超过 {FormatBytes(SHADER_SIZE_LIMIT)} 警戒线！");
            sb.AppendLine("建议：检查 IPreprocessShaders 裁剪规则，增加移动端变体过滤");
        }
        
        Debug.Log(sb.ToString());
        
        // 写入报告文件（供 CI 系统读取）
        System.IO.File.WriteAllText("Build/shader_variant_report.txt", sb.ToString());
    }
    
    private string FormatBytes(ulong bytes)
    {
        if (bytes < 1024) return $"{bytes} B";
        if (bytes < 1024 * 1024) return $"{bytes / 1024f:F1} KB";
        return $"{bytes / (1024f * 1024f):F1} MB";
    }
}
```

### 7.2 变体数量 CI 检查脚本

```bash
#!/bin/bash
# shader_variant_check.sh - CI/CD 阶段检查 Shader 变体数量

REPORT_FILE="Build/shader_variant_report.txt"
MAX_SHADER_SIZE_MB=50
BUILD_LOG="Build/UnityBuildLog.txt"

echo "=== Shader 变体 CI 检查 ==="

# 从构建日志提取变体数量
if [ -f "$BUILD_LOG" ]; then
    VARIANT_COUNT=$(grep -oP "Shader variants included in the build: \K[0-9]+" "$BUILD_LOG" | tail -1)
    echo "变体总数: $VARIANT_COUNT"
    
    # 检查变体数量阈值
    MAX_VARIANTS=50000
    if [ -n "$VARIANT_COUNT" ] && [ "$VARIANT_COUNT" -gt "$MAX_VARIANTS" ]; then
        echo "❌ 错误：变体数量 $VARIANT_COUNT 超过限制 $MAX_VARIANTS"
        echo "请检查 Shader 中的 multi_compile 关键字，考虑改为 shader_feature"
        exit 1
    fi
fi

# 检查报告文件
if [ -f "$REPORT_FILE" ]; then
    if grep -q "⚠️" "$REPORT_FILE"; then
        echo "⚠️ 发现 Shader 大小警告："
        grep "⚠️" "$REPORT_FILE"
        exit 1
    fi
fi

echo "✅ Shader 变体检查通过"
exit 0
```

---

## 八、最佳实践总结

### 8.1 变体管理决策树

```
定义着色器关键字时：
  问：这个特性需要在运行时动态全局切换？
    是 → multi_compile（全局）
    否 → 
      问：仅影响特定材质？
        是 → shader_feature_local（首选）
        否 → shader_feature（全局，但按材质裁剪）

命名规则：
  全局渲染特性（阴影/雾效/GI）  → multi_compile
  材质特有功能（法线贴图/自发光） → shader_feature_local _FEATURE_NAME
  禁止使用全大写无前缀关键字（污染全局空间）
```

### 8.2 变体优化量化目标

| 项目规模 | 目标变体总数 | Shader 包体 | 预热时间 |
|---------|------------|-----------|---------|
| 小型移动游戏 | < 5,000 | < 10 MB | < 1s |
| 中型手游 | < 20,000 | < 30 MB | < 3s |
| 大型 MMO/MOBA | < 50,000 | < 80 MB | < 8s |
| 主机/PC 大作 | < 200,000 | < 300 MB | < 15s |

### 8.3 常见问题速查

| 问题 | 根因 | 解决方案 |
|------|------|---------|
| 首次渲染卡顿 | 变体未预热，JIT 编译 | 添加 ShaderVariantCollection 预热 |
| 包体中 Shader 占比过高 | 变体爆炸或无效变体 | 实现 IPreprocessShaders 裁剪 |
| 全局关键字超出 256 上限 | 使用了过多全局 multi_compile | 改为 shader_feature_local |
| 材质切换 Shader 后效果错误 | shader_feature 变体未包含 | 改为 multi_compile 或检查材质变体收集 |
| 编辑器中效果正确但包体中异常 | shader_feature 对应变体被裁剪 | 将该变体加入 ShaderVariantCollection |
| CI 构建 Shader 编译时间过长 | 变体数量过多 | 增加 IPreprocessShaders 裁剪力度 |

---

## 结语

Shader 变体管理是大型 Unity 项目中最容易被忽视、但影响又极大的工程问题。通过规范使用 `shader_feature_local`、建立完善的变体收集与预热流程、在 CI 阶段加入变体数量检查，可以将 Shader 包体减少 50%~80%，消除因变体编译导致的运行时卡顿。这是每一个走向大厂商业项目的 Unity 工程师必须掌握的核心技能。
