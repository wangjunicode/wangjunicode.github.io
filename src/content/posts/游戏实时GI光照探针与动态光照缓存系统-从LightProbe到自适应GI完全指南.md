---
title: 游戏实时GI光照探针与动态光照缓存系统：从Light Probe到自适应GI完全指南
published: 2026-04-24
description: 深度解析游戏实时全局光照的工程实现，涵盖Light Probe Group优化布局、运行时动态采样、APV自适应探针体积、Realtime GI缓存更新策略与移动端GI近似方案，含完整Unity工程代码。
tags: [全局光照, Light Probe, APV, 实时GI, 动态光照, Unity, 渲染优化, 游戏开发]
category: 游戏开发
draft: false
---

# 游戏实时GI光照探针与动态光照缓存系统完全指南

## 一、全局光照（GI）技术概述与工程选型

全局光照（Global Illumination）是模拟光线在场景中多次弹射后形成的间接光照效果，是游戏画面真实感的核心技术之一。然而，完整的路径追踪实时GI对硬件要求极高，游戏客户端必须在画质与性能之间寻找平衡点。

### 1.1 GI技术方案对比

```
游戏客户端GI方案全谱

烘焙方案（离线预计算）：
  ├── Lightmap 烘焙        精度高，静态场景；运行期无开销
  ├── Light Probe 烘焙     支持动态物体接收GI；内存较低
  └── Reflection Probe     镜面反射GI；需要预烘焙

实时/混合方案：
  ├── Unity Realtime GI    动态环境光传播；仅低频光照
  ├── APV 自适应探针体积   Unity 2022+ 高密度探针；动态场景
  ├── Lumen (UE5)          屏幕空间+SDF实时GI；高端硬件
  └── DDGI (DirectX)       GPU光线追踪实时GI；次时代

移动端近似方案：
  ├── 球谐函数（SH）采样   4字节/探针；极低开销
  ├── 环境颜色梯度          天空盒上/下半球颜色
  └── 静态Lightmap + 动态AO 经典移动端方案
```

### 1.2 当前项目的推荐策略

对于追求视觉品质的移动端游戏：
- **静态场景** → Lightmap 烘焙 + Light Probe（小内存）
- **动态物体** → 运行时 Light Probe 采样 + 动态混合
- **室外开放场景** → APV（Unity 2022+）+ Realtime GI（仅PC/主机）
- **超移动端** → SH环境光 + 方向环境光近似

---

## 二、Light Probe Group 深度优化

### 2.1 探针布局的物理依据

Light Probe 的采样精度取决于探针密度和布局质量。错误的布局会导致物体移动时光照突变（"光照跳变"问题）。

```csharp
/// <summary>
/// 自动化 Light Probe 布局工具
/// 基于场景几何分析，在关键区域自动密集布置探针
/// </summary>
#if UNITY_EDITOR
using UnityEditor;

public static class LightProbeAutoLayout
{
    /// <summary>
    /// 在场景中的关键区域自动布置 Light Probe
    /// </summary>
    [MenuItem("Tools/Light Probe/Auto Layout Probes")]
    public static void AutoLayoutProbes()
    {
        // 收集场景中所有静态渲染器（确定探针放置的参考范围）
        Renderer[] staticRenderers = Object.FindObjectsOfType<Renderer>()
            .Where(r => GameObjectUtility.GetStaticEditorFlags(r.gameObject)
                        .HasFlag(StaticEditorFlags.ContributeGI))
            .ToArray();

        if (staticRenderers.Length == 0)
        {
            EditorUtility.DisplayDialog("Light Probe Auto Layout", 
                "场景中没有标记为 Contribute GI 的静态对象", "OK");
            return;
        }

        // 计算场景包围盒
        Bounds sceneBounds = staticRenderers[0].bounds;
        foreach (var renderer in staticRenderers)
            sceneBounds.Encapsulate(renderer.bounds);

        // 生成探针网格
        List<Vector3> probePositions = GenerateProbeGrid(sceneBounds, staticRenderers);

        // 创建 Light Probe Group
        GameObject probeGroupGO = new GameObject("Auto Light Probe Group");
        LightProbeGroup probeGroup = probeGroupGO.AddComponent<LightProbeGroup>();
        probeGroup.probePositions = probePositions.ToArray();

        Debug.Log($"[LightProbeLayout] 自动生成 {probePositions.Count} 个探针");
        Undo.RegisterCreatedObjectUndo(probeGroupGO, "Auto Layout Light Probes");
    }

    private static List<Vector3> GenerateProbeGrid(Bounds bounds, Renderer[] renderers)
    {
        var positions = new List<Vector3>();
        
        // 基础网格间距
        float horizontalSpacing = 3f;
        float verticalSpacing = 1.5f;
        
        Vector3 min = bounds.min;
        Vector3 max = bounds.max;
        
        // 在场景范围内生成三层网格
        float[] heights = { 0.5f, 1.8f, 4f }; // 地面层、人物层、天空层
        
        for (float x = min.x; x <= max.x; x += horizontalSpacing)
        {
            for (float z = min.z; z <= max.z; z += horizontalSpacing)
            {
                foreach (float heightOffset in heights)
                {
                    // 地面探测：找到实际地面高度
                    float groundHeight = FindGroundHeight(x, z, min.y, max.y);
                    Vector3 probePos = new Vector3(x, groundHeight + heightOffset, z);
                    
                    // 过滤掉在几何体内部的探针
                    if (!IsInsideGeometry(probePos, renderers))
                    {
                        positions.Add(probePos);
                    }
                }
            }
        }
        
        // 在动态物体活动区域额外加密
        DenseProbesAroundDynamicAreas(positions, horizontalSpacing * 0.5f);
        
        return positions;
    }

    private static float FindGroundHeight(float x, float z, float minY, float maxY)
    {
        Ray ray = new Ray(new Vector3(x, maxY + 1f, z), Vector3.down);
        if (Physics.Raycast(ray, out RaycastHit hit, maxY - minY + 2f, 
            LayerMask.GetMask("Default", "Ground")))
        {
            return hit.point.y;
        }
        return minY;
    }

    private static bool IsInsideGeometry(Vector3 pos, Renderer[] renderers)
    {
        // 简化判断：使用 CheckSphere 检测是否在碰撞体内
        return Physics.CheckSphere(pos, 0.1f, LayerMask.GetMask("Default"));
    }

    private static void DenseProbesAroundDynamicAreas(List<Vector3> positions, float spacing)
    {
        // 找到所有动态对象活动区域（通过 Tag 或特殊 Trigger 区域标记）
        var dynamicZones = Object.FindObjectsOfType<Collider>()
            .Where(c => c.gameObject.CompareTag("LightProbeDenseZone"))
            .Select(c => c.bounds)
            .ToArray();
        
        foreach (var zone in dynamicZones)
        {
            for (float x = zone.min.x; x <= zone.max.x; x += spacing)
            for (float y = zone.min.y; y <= zone.max.y; y += 1f)
            for (float z = zone.min.z; z <= zone.max.z; z += spacing)
            {
                positions.Add(new Vector3(x, y, z));
            }
        }
    }
}
#endif
```

### 2.2 运行时动态 Light Probe 采样

```csharp
/// <summary>
/// 动态光照缓存组件：为动态物体提供高效的 Light Probe 采样
/// 支持插值过渡、混合模式与更新频率控制
/// </summary>
[RequireComponent(typeof(Renderer))]
public class DynamicLightProbeReceiver : MonoBehaviour
{
    [Header("采样配置")]
    [SerializeField] private float _updateInterval = 0.1f;   // 更新间隔（秒）
    [SerializeField] private bool _interpolate = true;        // 是否平滑插值
    [SerializeField] private float _interpolationSpeed = 5f; // 插值速度
    
    [Header("高级选项")]
    [SerializeField] private bool _useOcclusionProbe = true;    // 使用遮挡探针
    [SerializeField] private Vector3 _sampleOffsetFromCenter = Vector3.up * 0.5f;

    private Renderer _renderer;
    private MaterialPropertyBlock _propertyBlock;
    
    // 球谐函数系数（表示间接光照）
    private SphericalHarmonicsL2 _currentSH;
    private SphericalHarmonicsL2 _targetSH;
    private Vector4[] _occlusionProbes;
    private Vector4 _currentOcclusion;
    private Vector4 _targetOcclusion;
    
    private float _lastUpdateTime;
    private bool _initialized;

    // 球谐函数 Shader 属性 ID（避免字符串查找）
    private static readonly int[] _shCoeffIds = new int[27];
    private static readonly int _lightProbeUsageId = Shader.PropertyToID("unity_ProbeVolumeParams");
    private static readonly int _occlusionId = Shader.PropertyToID("unity_ProbesOcclusion");

    static DynamicLightProbeReceiver()
    {
        // 预缓存 SH 系数的 Shader 属性 ID
        for (int i = 0; i < 27; i++)
        {
            _shCoeffIds[i] = Shader.PropertyToID($"unity_SH{GetSHPropertySuffix(i)}");
        }
    }

    private void Awake()
    {
        _renderer = GetComponent<Renderer>();
        _propertyBlock = new MaterialPropertyBlock();
        _occlusionProbes = new Vector4[1];
        _initialized = false;
    }

    private void Start()
    {
        // 立即进行初始采样
        SampleLightProbe(immediate: true);
    }

    private void Update()
    {
        if (Time.time - _lastUpdateTime >= _updateInterval)
        {
            SampleLightProbe(immediate: false);
            _lastUpdateTime = Time.time;
        }
        
        if (_interpolate && _initialized)
        {
            // 平滑插值当前SH系数到目标值
            InterpolateSH();
        }
    }

    private void SampleLightProbe(bool immediate)
    {
        // 采样位置（通常在物体中心偏上，避免采样到地面下）
        Vector3 samplePosition = transform.position + 
            transform.TransformDirection(_sampleOffsetFromCenter);
        
        // 采样 Light Probe
        LightProbes.GetInterpolatedProbe(samplePosition, _renderer, out _targetSH);
        
        if (_useOcclusionProbe)
        {
            // 采样遮挡探针（4光源遮挡系数）
            LightProbes.GetInterpolatedLightAndOcclusionProbes(
                new[] { samplePosition }, 
                new SphericalHarmonicsL2[1], 
                _occlusionProbes
            );
            _targetOcclusion = _occlusionProbes[0];
        }
        
        if (!_initialized || immediate)
        {
            _currentSH = _targetSH;
            _currentOcclusion = _targetOcclusion;
            _initialized = true;
            ApplySHToPropertyBlock();
        }
    }

    private void InterpolateSH()
    {
        float t = _interpolationSpeed * Time.deltaTime;
        bool changed = false;
        
        // 插值 SH 系数（L2 有 27 个系数）
        for (int channel = 0; channel < 3; channel++)
        {
            for (int coeff = 0; coeff < 9; coeff++)
            {
                float current = _currentSH[channel, coeff];
                float target = _targetSH[channel, coeff];
                float newVal = Mathf.Lerp(current, target, t);
                
                if (!Mathf.Approximately(current, newVal))
                {
                    _currentSH[channel, coeff] = newVal;
                    changed = true;
                }
            }
        }
        
        if (_useOcclusionProbe)
        {
            Vector4 newOcclusion = Vector4.Lerp(_currentOcclusion, _targetOcclusion, t);
            if (newOcclusion != _currentOcclusion)
            {
                _currentOcclusion = newOcclusion;
                changed = true;
            }
        }
        
        if (changed)
        {
            ApplySHToPropertyBlock();
        }
    }

    private void ApplySHToPropertyBlock()
    {
        _renderer.GetPropertyBlock(_propertyBlock);
        
        // 将 SH 系数写入 MaterialPropertyBlock
        // Unity Standard SH 格式：unity_SHAr, unity_SHAg, unity_SHAb, unity_SHBr...
        Vector4 SHAr = new Vector4(_currentSH[0, 3], _currentSH[0, 1], _currentSH[0, 2], _currentSH[0, 0] - _currentSH[0, 6]);
        Vector4 SHAg = new Vector4(_currentSH[1, 3], _currentSH[1, 1], _currentSH[1, 2], _currentSH[1, 0] - _currentSH[1, 6]);
        Vector4 SHAb = new Vector4(_currentSH[2, 3], _currentSH[2, 1], _currentSH[2, 2], _currentSH[2, 0] - _currentSH[2, 6]);
        Vector4 SHBr = new Vector4(_currentSH[0, 4], _currentSH[0, 6], _currentSH[0, 5] * 3, _currentSH[0, 7]);
        Vector4 SHBg = new Vector4(_currentSH[1, 4], _currentSH[1, 6], _currentSH[1, 5] * 3, _currentSH[1, 7]);
        Vector4 SHBb = new Vector4(_currentSH[2, 4], _currentSH[2, 6], _currentSH[2, 5] * 3, _currentSH[2, 7]);
        Vector4 SHC  = new Vector4(_currentSH[0, 8], _currentSH[2, 8], _currentSH[1, 8], 1f);
        
        _propertyBlock.SetVector("unity_SHAr", SHAr);
        _propertyBlock.SetVector("unity_SHAg", SHAg);
        _propertyBlock.SetVector("unity_SHAb", SHAb);
        _propertyBlock.SetVector("unity_SHBr", SHBr);
        _propertyBlock.SetVector("unity_SHBg", SHBg);
        _propertyBlock.SetVector("unity_SHBb", SHBb);
        _propertyBlock.SetVector("unity_SHC", SHC);
        
        if (_useOcclusionProbe)
        {
            _propertyBlock.SetVector("unity_ProbesOcclusion", _currentOcclusion);
        }
        
        _renderer.SetPropertyBlock(_propertyBlock);
    }

    private static string GetSHPropertySuffix(int index)
    {
        string[] suffixes = { "Ar", "Ag", "Ab", "Br", "Bg", "Bb", "C" };
        return index < suffixes.Length ? suffixes[index] : index.ToString();
    }
}
```

---

## 三、APV（自适应探针体积）深度实践

### 3.1 APV 的核心优势

APV（Adaptive Probe Volumes）是 Unity 2022 HDRP/URP 引入的新一代探针系统，相比传统 Light Probe Group 有以下改进：

```
传统 Light Probe Group vs APV

传统 LPG：
  ✗ 手动布置探针，调试繁琐
  ✗ 探针密度均匀，室外大空间浪费
  ✗ 不支持场景流式加载动态更新
  ✓ 兼容性好，Unity 所有版本

APV：
  ✓ 按场景几何自动密度适配（细节区域密，开阔区稀）
  ✓ 支持运行时场景流式加载，探针分块管理
  ✓ 更精确的漏光控制（Brick Validity Threshold）
  ✓ Shader 端更高效（Sparse Volume 查找）
  ✗ 仅 Unity 2022+ HDRP/URP
```

### 3.2 APV 运行时动态加载

```csharp
/// <summary>
/// APV 动态场景加载集成：在流式场景加载时同步加载对应的 APV 探针数据
/// </summary>
public class APVStreamingManager : MonoBehaviour
{
    [System.Serializable]
    public class SceneProbeBrick
    {
        public string SceneName;
        public Vector3 BrickCenter;
        public float BrickSize;
        public string ProbeBrickAssetPath; // Addressables 路径
    }

    [SerializeField] private List<SceneProbeBrick> _registeredBricks;
    
    private Dictionary<string, AsyncOperationHandle<ProbeReferenceVolumeAsset>> 
        _loadedBricks = new Dictionary<string, AsyncOperationHandle<ProbeReferenceVolumeAsset>>();

    private void OnEnable()
    {
        SceneManager.sceneLoaded += OnSceneLoaded;
        SceneManager.sceneUnloaded += OnSceneUnloaded;
    }

    private void OnDisable()
    {
        SceneManager.sceneLoaded -= OnSceneLoaded;
        SceneManager.sceneUnloaded -= OnSceneUnloaded;
    }

    private async void OnSceneLoaded(Scene scene, LoadSceneMode mode)
    {
        // 查找该场景对应的探针 Brick 数据
        var bricks = _registeredBricks.Where(b => b.SceneName == scene.name).ToList();
        
        foreach (var brick in bricks)
        {
            if (!_loadedBricks.ContainsKey(brick.SceneName))
            {
                await LoadProbeBrickAsync(brick);
            }
        }
    }

    private async Task LoadProbeBrickAsync(SceneProbeBrick brick)
    {
        var handle = Addressables.LoadAssetAsync<ProbeReferenceVolumeAsset>(
            brick.ProbeBrickAssetPath);
        
        await handle.Task;
        
        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            // 动态加载 APV 数据到 ProbeReferenceVolume
            ProbeReferenceVolume.instance.AddPendingAssetLoading(handle.Result);
            _loadedBricks[brick.SceneName] = handle;
            
            Debug.Log($"[APVStreaming] 加载探针数据: {brick.SceneName}");
        }
        else
        {
            Debug.LogError($"[APVStreaming] 加载失败: {brick.ProbeBrickAssetPath}");
        }
    }

    private void OnSceneUnloaded(Scene scene)
    {
        if (_loadedBricks.TryGetValue(scene.name, out var handle))
        {
            // 卸载对应的探针数据
            Addressables.Release(handle);
            _loadedBricks.Remove(scene.name);
            
            Debug.Log($"[APVStreaming] 卸载探针数据: {scene.name}");
        }
    }
}
```

---

## 四、动态光照缓存更新策略

### 4.1 光照缓存分级更新系统

```csharp
/// <summary>
/// 动态光照缓存管理器：根据物体重要性和距离分级调度探针更新
/// 实现"近处高频更新，远处低频更新"的性能优化策略
/// </summary>
public class LightCacheUpdateScheduler : MonoBehaviour
{
    public enum UpdatePriority
    {
        Critical = 0,   // 主角、近处物体：每帧更新
        High = 1,        // 重要 NPC：每 2 帧
        Normal = 2,      // 普通动态物体：每 5 帧
        Low = 3,         // 远处物体：每 10 帧
        Background = 4   // 背景装饰：每 30 帧
    }

    [System.Serializable]
    public class LightCacheEntry
    {
        public DynamicLightProbeReceiver Receiver;
        public UpdatePriority Priority;
        public int UpdateFrameInterval;
        public int NextUpdateFrame;
    }

    private static readonly int[] PriorityIntervals = { 1, 2, 5, 10, 30 };
    
    private List<LightCacheEntry> _entries = new List<LightCacheEntry>();
    private int _currentFrame;
    
    // 分帧更新：每帧最多处理的探针数量
    [SerializeField] private int _maxUpdatesPerFrame = 20;

    private void Update()
    {
        _currentFrame++;
        ProcessScheduledUpdates();
    }

    /// <summary>
    /// 注册动态光照接收器
    /// </summary>
    public void Register(DynamicLightProbeReceiver receiver, UpdatePriority priority)
    {
        var entry = new LightCacheEntry
        {
            Receiver = receiver,
            Priority = priority,
            UpdateFrameInterval = PriorityIntervals[(int)priority],
            NextUpdateFrame = _currentFrame + Random.Range(0, PriorityIntervals[(int)priority])
        };
        
        _entries.Add(entry);
    }

    /// <summary>
    /// 根据物体与相机的距离自动调整优先级
    /// </summary>
    public void UpdatePriorityByDistance(Transform cameraTransform)
    {
        foreach (var entry in _entries)
        {
            if (entry.Receiver == null) continue;
            
            float distance = Vector3.Distance(
                entry.Receiver.transform.position, 
                cameraTransform.position
            );
            
            UpdatePriority newPriority = distance switch
            {
                < 5f  => UpdatePriority.Critical,
                < 15f => UpdatePriority.High,
                < 30f => UpdatePriority.Normal,
                < 60f => UpdatePriority.Low,
                _     => UpdatePriority.Background
            };
            
            if (newPriority != entry.Priority)
            {
                entry.Priority = newPriority;
                entry.UpdateFrameInterval = PriorityIntervals[(int)newPriority];
            }
        }
    }

    private void ProcessScheduledUpdates()
    {
        int updatesThisFrame = 0;
        
        foreach (var entry in _entries)
        {
            if (updatesThisFrame >= _maxUpdatesPerFrame) break;
            if (entry.Receiver == null) continue;
            
            if (_currentFrame >= entry.NextUpdateFrame)
            {
                // 触发探针采样更新
                entry.Receiver.ForceUpdate();
                entry.NextUpdateFrame = _currentFrame + entry.UpdateFrameInterval;
                updatesThisFrame++;
            }
        }
    }

    public void Unregister(DynamicLightProbeReceiver receiver)
    {
        _entries.RemoveAll(e => e.Receiver == receiver);
    }
}
```

### 4.2 移动端 GI 近似：高效 SH 环境光

```csharp
/// <summary>
/// 移动端环境光 SH 近似系统：用极低开销模拟动态天光变化
/// 适用于不支持 Light Probe 的老旧设备或性能敏感场景
/// </summary>
public class MobileAmbientLightSystem : MonoBehaviour
{
    [Header("天光配置")]
    [SerializeField] private Gradient _skyColorGradient;      // 随时间变化的天空颜色
    [SerializeField] private Gradient _groundColorGradient;   // 随时间变化的地面颜色
    [SerializeField] private float _skyIntensity = 1.5f;
    [SerializeField] private float _groundIntensity = 0.5f;
    
    [Header("动态更新")]
    [SerializeField] private bool _linkToGameTime = true;     // 关联游戏内时间
    [SerializeField] private float _updateInterval = 0.5f;   // 更新间隔（秒）
    
    private float _lastUpdateTime;
    private SphericalHarmonicsL2 _ambientSH;
    private static readonly int _ambientSHId = Shader.PropertyToID("unity_AmbientSkyColor");

    private void Update()
    {
        if (Time.time - _lastUpdateTime < _updateInterval) return;
        _lastUpdateTime = Time.time;
        
        float timeOfDay = _linkToGameTime ? GameTimeManager.Instance.NormalizedTimeOfDay : 0.5f;
        UpdateAmbientSH(timeOfDay);
    }

    private void UpdateAmbientSH(float timeNormalized)
    {
        Color skyColor = _skyColorGradient.Evaluate(timeNormalized) * _skyIntensity;
        Color groundColor = _groundColorGradient.Evaluate(timeNormalized) * _groundIntensity;
        Color equatorColor = Color.Lerp(groundColor, skyColor, 0.5f);
        
        // 用上/中/下三个方向颜色构建 L1 SH（近似 L2 精度的环境光）
        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = skyColor;
        RenderSettings.ambientEquatorColor = equatorColor;
        RenderSettings.ambientGroundColor = groundColor;
        
        // 高级：直接写入 SH 全局变量（用于不受 RenderSettings 控制的物体）
        DynamicGI.UpdateEnvironment();
    }

    /// <summary>
    /// 手动设置特定区域的 SH 环境光（用于室内区域的光照替换）
    /// </summary>
    public static void SetLocalAmbientSH(Renderer targetRenderer, 
        Color ambientColor, float ambientIntensity)
    {
        var propertyBlock = new MaterialPropertyBlock();
        targetRenderer.GetPropertyBlock(propertyBlock);
        
        // 构建均匀颜色的 SH（L0 项）
        SphericalHarmonicsL2 sh = new SphericalHarmonicsL2();
        sh.AddAmbientLight(ambientColor * ambientIntensity);
        
        // 将 SH 写入 MaterialPropertyBlock
        ApplySHToBlock(ref propertyBlock, ref sh);
        targetRenderer.SetPropertyBlock(propertyBlock);
    }

    private static void ApplySHToBlock(ref MaterialPropertyBlock block, 
        ref SphericalHarmonicsL2 sh)
    {
        // 提取 SH 系数并设置到 PropertyBlock
        block.SetVector("unity_SHAr", new Vector4(sh[0, 3], sh[0, 1], sh[0, 2], sh[0, 0]));
        block.SetVector("unity_SHAg", new Vector4(sh[1, 3], sh[1, 1], sh[1, 2], sh[1, 0]));
        block.SetVector("unity_SHAb", new Vector4(sh[2, 3], sh[2, 1], sh[2, 2], sh[2, 0]));
        block.SetVector("unity_SHBr", new Vector4(sh[0, 4], sh[0, 5], sh[0, 6], sh[0, 7]));
        block.SetVector("unity_SHBg", new Vector4(sh[1, 4], sh[1, 5], sh[1, 6], sh[1, 7]));
        block.SetVector("unity_SHBb", new Vector4(sh[2, 4], sh[2, 5], sh[2, 6], sh[2, 7]));
        block.SetVector("unity_SHC", new Vector4(sh[0, 8], sh[2, 8], sh[1, 8], 1f));
    }
}
```

---

## 五、Light Probe 漏光修复与调试工具

### 5.1 漏光问题诊断与修复

```csharp
/// <summary>
/// Light Probe 漏光可视化调试工具
/// 在 Scene 视图中显示探针采样到的光照信息，帮助识别漏光区域
/// </summary>
#if UNITY_EDITOR
[CustomEditor(typeof(LightProbeGroup))]
public class LightProbeGroupDebugEditor : Editor
{
    private bool _showDebugGizmos = false;
    private float _gizmoScale = 0.3f;
    private Color _validColor = Color.white;
    private Color _suspiciousColor = Color.red;
    private float _brightnessThreshold = 2.0f; // 超过此亮度判定为可疑（可能漏光）

    public override void OnInspectorGUI()
    {
        base.OnInspectorGUI();
        
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("调试工具", EditorStyles.boldLabel);
        
        _showDebugGizmos = EditorGUILayout.Toggle("显示光照信息", _showDebugGizmos);
        _gizmoScale = EditorGUILayout.Slider("Gizmo 大小", _gizmoScale, 0.1f, 1f);
        _brightnessThreshold = EditorGUILayout.FloatField("漏光亮度阈值", _brightnessThreshold);
        
        if (GUILayout.Button("检测可疑探针"))
        {
            DetectSuspiciousProbes();
        }
        
        if (GUILayout.Button("烘焙后验证"))
        {
            ValidateAfterBake();
        }
    }

    private void DetectSuspiciousProbes()
    {
        var probeGroup = (LightProbeGroup)target;
        var positions = probeGroup.probePositions;
        int suspiciousCount = 0;
        
        // 遍历所有探针，检查是否有异常高亮的探针（可能是漏光）
        SphericalHarmonicsL2[] bakedProbes = LightmapSettings.lightProbes?.bakedProbes;
        if (bakedProbes == null || bakedProbes.Length != positions.Length)
        {
            Debug.LogWarning("[LightProbeDebug] 请先烘焙场景后再检测");
            return;
        }
        
        for (int i = 0; i < positions.Length && i < bakedProbes.Length; i++)
        {
            // 计算探针的平均亮度（L0 项）
            float brightness = CalculateSHBrightness(bakedProbes[i]);
            if (brightness > _brightnessThreshold)
            {
                Debug.LogWarning($"[LightProbeDebug] 可疑探针 #{i}: 亮度={brightness:F2}, 位置={probeGroup.transform.TransformPoint(positions[i])}");
                suspiciousCount++;
            }
        }
        
        Debug.Log($"[LightProbeDebug] 检测完成：{suspiciousCount}/{positions.Length} 个可疑探针");
    }

    private float CalculateSHBrightness(SphericalHarmonicsL2 sh)
    {
        // L0 项代表均匀环境光（最能体现整体亮度）
        float r = sh[0, 0];
        float g = sh[1, 0];
        float b = sh[2, 0];
        return Mathf.Max(r, g, b);
    }

    private void ValidateAfterBake()
    {
        Debug.Log("[LightProbeDebug] 开始烘焙后验证...");
        // 可扩展：自动对比烘焙前后的探针数据
    }

    private void OnSceneGUI()
    {
        if (!_showDebugGizmos) return;
        
        var probeGroup = (LightProbeGroup)target;
        var bakedProbes = LightmapSettings.lightProbes?.bakedProbes;
        if (bakedProbes == null) return;
        
        for (int i = 0; i < probeGroup.probePositions.Length && i < bakedProbes.Length; i++)
        {
            Vector3 worldPos = probeGroup.transform.TransformPoint(probeGroup.probePositions[i]);
            float brightness = CalculateSHBrightness(bakedProbes[i]);
            
            Handles.color = brightness > _brightnessThreshold ? _suspiciousColor : _validColor;
            Handles.SphereHandleCap(0, worldPos, Quaternion.identity, _gizmoScale, EventType.Repaint);
        }
    }
}
#endif
```

---

## 六、Shader 侧 SH 光照计算

```hlsl
// LightProbeSH.hlsl
// 在 Shader 中高效计算球谐函数光照

// 球谐系数（由 MaterialPropertyBlock 或全局 Shader 变量提供）
float4 unity_SHAr;
float4 unity_SHAg;
float4 unity_SHAb;
float4 unity_SHBr;
float4 unity_SHBg;
float4 unity_SHBb;
float4 unity_SHC;

/// 计算 L1+L2 球谐光照（标准 Unity SH 评估）
float3 EvaluateSH(float3 normalWS)
{
    float3 result;
    
    // L1 项（线性）：评估 4 个系数与法线方向的点积
    float4 normal4 = float4(normalWS, 1.0);
    result.r = dot(unity_SHAr, normal4);
    result.g = dot(unity_SHAg, normal4);
    result.b = dot(unity_SHAb, normal4);
    
    // L2 项（二次）：评估 4 个系数
    float4 normalSq = float4(normalWS.x * normalWS.y, 
                              normalWS.y * normalWS.z, 
                              normalWS.z * normalWS.x, 
                              normalWS.z * normalWS.z);
    
    result.r += dot(unity_SHBr, normalSq);
    result.g += dot(unity_SHBg, normalSq);
    result.b += dot(unity_SHBb, normalSq);
    
    // L2 最后一项
    float x2y2 = normalWS.x * normalWS.x - normalWS.y * normalWS.y;
    result += unity_SHC.rgb * x2y2;
    
    return max(float3(0, 0, 0), result);
}

/// 快速近似版本（仅 L0+L1，移动端低端设备）
float3 EvaluateSHFast(float3 normalWS)
{
    float4 normal4 = float4(normalWS, 1.0);
    float3 result;
    result.r = dot(unity_SHAr, normal4);
    result.g = dot(unity_SHAg, normal4);
    result.b = dot(unity_SHAb, normal4);
    return max(float3(0, 0, 0), result);
}

// ===== 使用示例 =====
// 在 PBR 光照计算中添加 GI 贡献：
//
// float3 indirectDiffuse = EvaluateSH(normalWS);
// float3 finalColor = directLighting + indirectDiffuse * albedo * ao;
```

---

## 七、最佳实践与常见问题

### 7.1 Light Probe 布局规范

| 场景类型 | 建议探针密度 | 布局要点 |
|---------|------------|---------|
| 室内走廊 | 每 2m × 1.5m | 沿墙壁、门口加密；高度2层 |
| 室外开阔地 | 每 5m × 3m | 关注光线明暗交界处 |
| 室外建筑阴影区 | 每 2m × 1.5m | 阴影边界密集布探 |
| 高度差区域 | 额外垂直层 | 楼梯、斜坡必须多层 |
| 无动态物体区 | 可不放 | 节省内存与烘焙时间 |

### 7.2 常见问题排查

```
问题：角色走入阴影时身上仍有明显亮斑（漏光）
原因：探针跨越遮挡物采样到了明亮区域的光照
解决：在遮挡物两侧各放一排探针，让三角形插值不跨越几何体

问题：角色移动时光照突变（Popping）  
原因：相邻 Light Probe 四面体差异过大
解决：
  1. 增加过渡区域探针密度
  2. 启用 Probe 平滑插值（DynamicLightProbeReceiver._interpolate = true）
  3. 使用 BlendedProbes 特性（Unity 2022+）

问题：APV 在移动端性能差
原因：Sparse Volume 查找开销过高
解决：移动端降级为传统 LPG，或使用 SH 近似方案

问题：Light Probe 数量过多导致内存超标
原因：每个探针存储 27 个 float（L2 SH）= 108 字节
解决：
  1. 减少远处探针密度
  2. 使用 L1 SH（9 个 float）降低精度
  3. 对远处探针进行聚合合并
```

### 7.3 性能数据参考

| 方案 | 每帧 CPU 开销 | 内存占用 | 画质 | 适用平台 |
|------|-------------|---------|------|---------|
| 传统 LPG（静态） | < 0.1ms | 低 | ★★★ | 全平台 |
| 动态 LPG 采样（本文方案） | 0.2~0.5ms | 低 | ★★★ | 全平台 |
| APV 烘焙 | < 0.2ms | 中 | ★★★★ | Unity 2022+ |
| Realtime GI | 2~5ms | 高 | ★★★★ | PC/主机 |
| 路径追踪 GI | >10ms | 高 | ★★★★★ | 高端PC |

动态光照缓存系统是游戏环境真实感的基础设施。通过合理的探针布局、分级更新调度、平滑插值过渡以及移动端 SH 近似降级策略，可以在兼顾视觉效果的同时将 GI 系统的运行时开销控制在可接受范围内，是现代游戏客户端必须掌握的核心渲染技术。
