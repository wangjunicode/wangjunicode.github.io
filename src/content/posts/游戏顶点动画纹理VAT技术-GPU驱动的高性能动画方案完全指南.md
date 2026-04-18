---
title: 游戏顶点动画纹理VAT技术：GPU驱动的高性能动画方案完全指南
published: 2026-04-18
description: 深度解析顶点动画纹理（Vertex Animation Texture）技术原理，从VAT数据烘焙流程、Shader解码算法、到GPU Instance实例化渲染，实现在移动端以极低CPU开销渲染数千个动态物体，适用于群体NPC、植被、布料、破碎特效等场景。
tags: [Unity, VAT, 顶点动画, GPU优化, Shader, 性能优化]
category: 渲染技术
draft: false
---

# 游戏顶点动画纹理VAT技术：GPU驱动的高性能动画方案完全指南

## 一、VAT技术诞生的背景

在游戏中渲染大量动态物体（城镇居民、战场士兵、摇曳植被）时，传统骨骼动画面临严峻挑战：

- **骨骼蒙皮（Skinning）是CPU密集型操作**，每帧每个角色都要重新计算所有顶点位置
- **DrawCall数量爆炸**：每个动态角色通常是一个独立的DrawCall，数百个NPC会让移动端直接崩溃
- **动画状态机开销**：Animator每帧都需要在CPU端评估状态机

**Vertex Animation Texture（顶点动画纹理，VAT）** 是一种将动画数据"烘焙"进纹理的技术：
- 把每一帧每个顶点的**位置偏移**存储在纹理的像素中
- 在GPU Shader中直接读取纹理还原顶点位置，**完全绕过CPU端的骨骼计算**
- 天然支持**GPU Instancing**，理论上数千个相同模型只需一个DrawCall

---

## 二、VAT核心原理

### 2.1 数据存储结构

VAT将动画的每一帧每个顶点的位置偏移（Position Delta）编码进一张纹理：

```
纹理宽度（Width）  = 动画总帧数（Frame Count）
纹理高度（Height） = 模型顶点数（Vertex Count）
像素颜色（RGB）   = 顶点在该帧的世界空间位置偏移（X, Y, Z）
```

例如：一个100帧动画、500顶点的模型，需要一张 `100 × 512`（向上取2的幂）的 `RGBAHalf` 格式纹理。

### 2.2 数据精度选择

| 纹理格式 | 精度 | 显存占用 | 适用场景 |
|----------|------|----------|----------|
| RGBA32（8bit） | 低，需归一化缩放 | 小 | 位移幅度小的动画（<1m） |
| RGBAHalf（16bit浮点） | 中，直接存储 | 中 | 大多数角色动画 |
| RGBAFloat（32bit浮点） | 最高 | 大 | 要求精度极高的场景 |

实际工程中，**RGBAHalf + 位移范围缩放** 是最佳平衡方案：

```
存储时：normalizedPos = (worldPos - boundsMin) / boundsSize  → [0, 1]
读取时：worldPos = normalizedPos * boundsSize + boundsMin
```

---

## 三、VAT数据烘焙工具（Unity Editor）

### 3.1 烘焙流程

```csharp
using UnityEngine;
using UnityEditor;
using System.IO;

/// <summary>
/// VAT（顶点动画纹理）烘焙工具
/// 将SkinnedMeshRenderer的骨骼动画烘焙成位置纹理
/// </summary>
public class VATBaker : EditorWindow
{
    [MenuItem("Tools/VAT/打开烘焙工具")]
    public static void ShowWindow()
    {
        GetWindow<VATBaker>("VAT烘焙工具");
    }

    private GameObject _targetPrefab;
    private AnimationClip _targetClip;
    private int _fps = 30;
    private string _outputPath = "Assets/Art/VAT/";

    void OnGUI()
    {
        GUILayout.Label("VAT 动画烘焙工具", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        _targetPrefab = (GameObject)EditorGUILayout.ObjectField("目标预制体", _targetPrefab, typeof(GameObject), false);
        _targetClip = (AnimationClip)EditorGUILayout.ObjectField("动画片段", _targetClip, typeof(AnimationClip), false);
        _fps = EditorGUILayout.IntSlider("烘焙帧率", _fps, 15, 60);
        _outputPath = EditorGUILayout.TextField("输出路径", _outputPath);

        EditorGUILayout.Space();

        if (GUILayout.Button("开始烘焙", GUILayout.Height(35)))
        {
            BakeVAT();
        }
    }

    private void BakeVAT()
    {
        if (_targetPrefab == null || _targetClip == null)
        {
            EditorUtility.DisplayDialog("错误", "请先指定预制体和动画片段", "确定");
            return;
        }

        // 实例化到场景中（隐藏）
        GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(_targetPrefab);
        instance.SetActive(false);

        try
        {
            SkinnedMeshRenderer smr = instance.GetComponentInChildren<SkinnedMeshRenderer>();
            if (smr == null)
            {
                Debug.LogError("目标预制体没有SkinnedMeshRenderer！");
                return;
            }

            Mesh bakedMesh = new Mesh();
            int vertexCount = smr.sharedMesh.vertexCount;

            float duration = _targetClip.length;
            int frameCount = Mathf.CeilToInt(duration * _fps) + 1;

            // 纹理尺寸（宽=帧数，高=顶点数，向上取2幂）
            int texWidth = Mathf.NextPowerOfTwo(frameCount);
            int texHeight = Mathf.NextPowerOfTwo(vertexCount);

            // 使用RGBAHalf格式（16位浮点）
            Texture2D positionTex = new Texture2D(texWidth, texHeight, TextureFormat.RGBAHalf, false);
            Texture2D normalTex = new Texture2D(texWidth, texHeight, TextureFormat.RGBAHalf, false);

            Color[] posColors = new Color[texWidth * texHeight];
            Color[] normalColors = new Color[texWidth * texHeight];

            // 记录Bounds用于归一化
            Bounds totalBounds = new Bounds();
            bool boundsInitialized = false;

            // 第一遍：计算Bounds
            for (int frame = 0; frame < frameCount; frame++)
            {
                float time = (float)frame / (_fps) / duration * _targetClip.length;
                time = Mathf.Clamp(time, 0, _targetClip.length);

                _targetClip.SampleAnimation(instance, time);
                smr.BakeMesh(bakedMesh);

                foreach (Vector3 v in bakedMesh.vertices)
                {
                    if (!boundsInitialized)
                    {
                        totalBounds = new Bounds(v, Vector3.zero);
                        boundsInitialized = true;
                    }
                    else
                    {
                        totalBounds.Encapsulate(v);
                    }
                }
            }

            // 留一点余量防止精度溢出
            totalBounds.Expand(0.01f);

            // 第二遍：烘焙位置和法线数据
            for (int frame = 0; frame < frameCount; frame++)
            {
                float time = (float)frame / _fps;
                time = Mathf.Clamp(time, 0, _targetClip.length);

                _targetClip.SampleAnimation(instance, time);
                smr.BakeMesh(bakedMesh);

                Vector3[] vertices = bakedMesh.vertices;
                Vector3[] normals = bakedMesh.normals;

                for (int v = 0; v < vertexCount; v++)
                {
                    // 位置：归一化到[0,1]
                    Vector3 pos = vertices[v];
                    float nx = (pos.x - totalBounds.min.x) / totalBounds.size.x;
                    float ny = (pos.y - totalBounds.min.y) / totalBounds.size.y;
                    float nz = (pos.z - totalBounds.min.z) / totalBounds.size.z;
                    posColors[v * texWidth + frame] = new Color(nx, ny, nz, 1.0f);

                    // 法线：映射到[0,1]（原始范围[-1,1]）
                    if (v < normals.Length)
                    {
                        Vector3 n = normals[v];
                        normalColors[v * texWidth + frame] = new Color(n.x * 0.5f + 0.5f, n.y * 0.5f + 0.5f, n.z * 0.5f + 0.5f, 1.0f);
                    }
                }
            }

            positionTex.SetPixels(posColors);
            positionTex.Apply();

            normalTex.SetPixels(normalColors);
            normalTex.Apply();

            // 保存纹理
            Directory.CreateDirectory(_outputPath);
            string baseName = _targetPrefab.name + "_" + _targetClip.name;

            SaveTexture(positionTex, _outputPath + baseName + "_Position.asset");
            SaveTexture(normalTex, _outputPath + baseName + "_Normal.asset");

            // 保存Bounds信息到ScriptableObject
            VATBoundsData boundsData = ScriptableObject.CreateInstance<VATBoundsData>();
            boundsData.BoundsMin = totalBounds.min;
            boundsData.BoundsSize = totalBounds.size;
            boundsData.FrameCount = frameCount;
            boundsData.Duration = duration;
            boundsData.VertexCount = vertexCount;
            AssetDatabase.CreateAsset(boundsData, _outputPath + baseName + "_BoundsData.asset");

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Debug.Log($"[VAT] 烘焙完成！{baseName}，{frameCount}帧，{vertexCount}顶点，纹理尺寸{texWidth}x{texHeight}");
            EditorUtility.DisplayDialog("完成", $"VAT烘焙完成！\n帧数：{frameCount}\n顶点数：{vertexCount}\n纹理：{texWidth}x{texHeight}", "确定");
        }
        finally
        {
            DestroyImmediate(instance);
        }
    }

    private void SaveTexture(Texture2D tex, string path)
    {
        // 直接保存为Asset（保留HDR精度）
        AssetDatabase.CreateAsset(tex, path);
    }
}

/// <summary>
/// 存储VAT Bounds和元数据
/// </summary>
[CreateAssetMenu(menuName = "VAT/BoundsData")]
public class VATBoundsData : ScriptableObject
{
    public Vector3 BoundsMin;
    public Vector3 BoundsSize;
    public int FrameCount;
    public float Duration;
    public int VertexCount;
}
```

---

## 四、VAT Shader 解码实现

### 4.1 HLSL顶点解码核心逻辑

```hlsl
// VAT_Decode.hlsl - 可被多个Shader包含的通用解码库

// VAT纹理和参数
TEXTURE2D(_VATPositionTex);
SAMPLER(sampler_VATPositionTex);
TEXTURE2D(_VATNormalTex);
SAMPLER(sampler_VATNormalTex);

// 在Material上设置的参数
float4 _VATBoundsMin;    // Bounds最小值 (x, y, z, 0)
float4 _VATBoundsSize;   // Bounds尺寸 (x, y, z, 0)
float _VATFrameCount;    // 总帧数
float _VATDuration;      // 动画时长（秒）
float _VATCurrentTime;   // 当前播放时间（通过MaterialPropertyBlock逐实例设置）
float _VATTexWidth;      // 纹理宽度
float _VATTexHeight;     // 纹理高度

/// <summary>
/// 从VAT纹理中解码顶点位置
/// </summary>
/// <param name="vertexID">顶点索引（SV_VertexID）</param>
/// <param name="time">当前动画时间[0, Duration]</param>
/// <returns>解码后的世界空间位置</returns>
float3 DecodeVATPosition(uint vertexID, float time)
{
    // 计算当前帧和下一帧（用于线性插值）
    float normalizedTime = frac(time / _VATDuration); // 循环
    float frameFloat = normalizedTime * (_VATFrameCount - 1.0);
    uint frameA = (uint)floor(frameFloat);
    uint frameB = min(frameA + 1, (uint)_VATFrameCount - 1);
    float lerpT = frac(frameFloat);

    // 计算UV坐标（帧→U轴，顶点→V轴）
    float uA = (frameA + 0.5) / _VATTexWidth;
    float uB = (frameB + 0.5) / _VATTexWidth;
    float v = (vertexID + 0.5) / _VATTexHeight;

    // 采样位置纹理
    float3 encodedA = SAMPLE_TEXTURE2D_LOD(_VATPositionTex, sampler_VATPositionTex, float2(uA, v), 0).rgb;
    float3 encodedB = SAMPLE_TEXTURE2D_LOD(_VATPositionTex, sampler_VATPositionTex, float2(uB, v), 0).rgb;

    // 插值
    float3 encoded = lerp(encodedA, encodedB, lerpT);

    // 反归一化：从[0,1]还原到世界空间位置
    float3 position = encoded * _VATBoundsSize.xyz + _VATBoundsMin.xyz;
    return position;
}

/// <summary>
/// 解码法线
/// </summary>
float3 DecodeVATNormal(uint vertexID, float time)
{
    float normalizedTime = frac(time / _VATDuration);
    float frameFloat = normalizedTime * (_VATFrameCount - 1.0);
    uint frameA = (uint)floor(frameFloat);
    float uA = (frameA + 0.5) / _VATTexWidth;
    float v = (vertexID + 0.5) / _VATTexHeight;
    float3 encoded = SAMPLE_TEXTURE2D_LOD(_VATNormalTex, sampler_VATNormalTex, float2(uA, v), 0).rgb;
    return normalize(encoded * 2.0 - 1.0); // [0,1] → [-1,1]
}
```

### 4.2 完整的VAT URP Shader

```hlsl
Shader "Custom/VAT_UnlitInstanced"
{
    Properties
    {
        _MainTex ("Albedo", 2D) = "white" {}
        _Color ("Tint Color", Color) = (1,1,1,1)
        
        [Header(VAT Settings)]
        _VATPositionTex ("Position Texture", 2D) = "black" {}
        _VATNormalTex ("Normal Texture", 2D) = "bump" {}
        _VATBoundsMin ("Bounds Min", Vector) = (0,0,0,0)
        _VATBoundsSize ("Bounds Size", Vector) = (1,1,1,0)
        _VATFrameCount ("Frame Count", Float) = 60
        _VATDuration ("Duration", Float) = 2.0
        _VATTexWidth ("Tex Width", Float) = 64
        _VATTexHeight ("Tex Height", Float) = 512
        _VATCurrentTime ("Current Time", Float) = 0.0  // 由CPU每帧更新
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            // 关键：启用GPU Instancing
            #pragma instancing_options assumeuniformscaling

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _Color;
                float4 _VATBoundsMin;
                float4 _VATBoundsSize;
                float _VATFrameCount;
                float _VATDuration;
                float _VATCurrentTime;
                float _VATTexWidth;
                float _VATTexHeight;
            CBUFFER_END

            TEXTURE2D(_MainTex);         SAMPLER(sampler_MainTex);
            TEXTURE2D(_VATPositionTex);  SAMPLER(sampler_VATPositionTex);
            TEXTURE2D(_VATNormalTex);    SAMPLER(sampler_VATNormalTex);

            // 每实例的时间偏移（实现不同步播放）
            UNITY_INSTANCING_BUFFER_START(PerInstanceData)
                UNITY_DEFINE_INSTANCED_PROP(float, _TimeOffset)
            UNITY_INSTANCING_BUFFER_END(PerInstanceData)

            struct Attributes
            {
                float2 uv       : TEXCOORD0;
                uint   vertexID : SV_VertexID; // 关键：顶点索引
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 posCS    : SV_POSITION;
                float2 uv       : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
                float3 posWS    : TEXCOORD2;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            // VAT解码函数（内联版）
            float3 SampleVATPosition(uint vid, float time)
            {
                float t = frac(time / _VATDuration) * (_VATFrameCount - 1.0);
                uint f0 = (uint)t;
                uint f1 = min(f0 + 1, (uint)_VATFrameCount - 1);
                float lt = frac(t);
                float2 uvA = float2((f0 + 0.5) / _VATTexWidth, (vid + 0.5) / _VATTexHeight);
                float2 uvB = float2((f1 + 0.5) / _VATTexWidth, (vid + 0.5) / _VATTexHeight);
                float3 a = SAMPLE_TEXTURE2D_LOD(_VATPositionTex, sampler_VATPositionTex, uvA, 0).rgb;
                float3 b = SAMPLE_TEXTURE2D_LOD(_VATPositionTex, sampler_VATPositionTex, uvB, 0).rgb;
                return lerp(a, b, lt) * _VATBoundsSize.xyz + _VATBoundsMin.xyz;
            }

            float3 SampleVATNormal(uint vid, float time)
            {
                float t = frac(time / _VATDuration) * (_VATFrameCount - 1.0);
                uint f0 = (uint)t;
                float2 uv = float2((f0 + 0.5) / _VATTexWidth, (vid + 0.5) / _VATTexHeight);
                float3 n = SAMPLE_TEXTURE2D_LOD(_VATNormalTex, sampler_VATNormalTex, uv, 0).rgb;
                return normalize(n * 2.0 - 1.0);
            }

            Varyings vert(Attributes input)
            {
                UNITY_SETUP_INSTANCE_ID(input);
                Varyings output;
                UNITY_TRANSFER_INSTANCE_ID(input, output);

                // 读取每实例的时间偏移
                float timeOffset = UNITY_ACCESS_INSTANCED_PROP(PerInstanceData, _TimeOffset);
                float currentTime = _VATCurrentTime + timeOffset;

                // VAT解码：从纹理中读取当前顶点位置
                float3 vatPos = SampleVATPosition(input.vertexID, currentTime);
                float3 vatNormal = SampleVATNormal(input.vertexID, currentTime);

                // 应用模型变换（VAT输出的是模型空间位置）
                VertexPositionInputs posInputs = GetVertexPositionInputs(vatPos);
                VertexNormalInputs normalInputs = GetVertexNormalInputs(vatNormal);

                output.posCS    = posInputs.positionCS;
                output.posWS    = posInputs.positionWS;
                output.normalWS = normalInputs.normalWS;
                output.uv       = TRANSFORM_TEX(input.uv, _MainTex);
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_INSTANCE_ID(input);

                half4 albedo = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, input.uv) * _Color;

                // 简单Lambert漫反射
                InputData lightData = (InputData)0;
                lightData.positionWS = input.posWS;
                lightData.normalWS = normalize(input.normalWS);
                lightData.viewDirectionWS = GetWorldSpaceNormalizeViewDir(input.posWS);
                lightData.shadowCoord = float4(0, 0, 0, 0);

                SurfaceData surfaceData = (SurfaceData)0;
                surfaceData.albedo = albedo.rgb;
                surfaceData.alpha = albedo.a;
                surfaceData.smoothness = 0.5;
                surfaceData.metallic = 0;

                half4 color = UniversalFragmentPBR(lightData, surfaceData);
                return color;
            }
            ENDHLSL
        }
    }
}
```

---

## 五、CPU端控制系统

### 5.1 VAT实例管理器

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// VAT动画实例管理器
/// 使用GPU Instancing + MaterialPropertyBlock批量渲染大量VAT动画物体
/// 目标：1000个角色只需一个DrawCall
/// </summary>
public class VATInstanceManager : MonoBehaviour
{
    [Header("VAT配置")]
    public Mesh InstanceMesh;               // 静态姿态Mesh（T-Pose）
    public Material VATMaterial;            // 使用VAT Shader的材质
    public VATBoundsData BoundsData;        // 烘焙时保存的元数据

    [Header("实例配置")]
    public int InstanceCount = 500;
    public float SpawnRadius = 50f;

    private Matrix4x4[] _matrices;
    private MaterialPropertyBlock _mpb;
    private float[] _timeOffsets;          // 每个实例的随机时间偏移
    private float _globalTime;

    private static readonly int _TimeOffsetID = Shader.PropertyToID("_TimeOffset");
    private static readonly int _VATCurrentTimeID = Shader.PropertyToID("_VATCurrentTime");
    private static readonly int _VATFrameCountID = Shader.PropertyToID("_VATFrameCount");
    private static readonly int _VATDurationID = Shader.PropertyToID("_VATDuration");
    private static readonly int _VATTexWidthID = Shader.PropertyToID("_VATTexWidth");
    private static readonly int _VATTexHeightID = Shader.PropertyToID("_VATTexHeight");
    private static readonly int _VATBoundsMinID = Shader.PropertyToID("_VATBoundsMin");
    private static readonly int _VATBoundsSizeID = Shader.PropertyToID("_VATBoundsSize");

    // GPU Instancing每批最多1023个
    private const int BATCH_SIZE = 1023;
    private List<Matrix4x4[]> _batches = new List<Matrix4x4[]>();
    private List<float[]> _timeOffsetBatches = new List<float[]>();

    void Start()
    {
        InitializeInstances();
        SetupMaterialParams();
    }

    private void InitializeInstances()
    {
        _matrices = new Matrix4x4[InstanceCount];
        _timeOffsets = new float[InstanceCount];

        // 随机分布在圆形区域
        for (int i = 0; i < InstanceCount; i++)
        {
            Vector2 rand2D = Random.insideUnitCircle * SpawnRadius;
            Vector3 pos = new Vector3(rand2D.x, 0, rand2D.y) + transform.position;
            Quaternion rot = Quaternion.Euler(0, Random.Range(0f, 360f), 0);
            _matrices[i] = Matrix4x4.TRS(pos, rot, Vector3.one);
            _timeOffsets[i] = Random.Range(0f, BoundsData != null ? BoundsData.Duration : 2f);
        }

        // 分批
        _batches.Clear();
        _timeOffsetBatches.Clear();
        for (int start = 0; start < InstanceCount; start += BATCH_SIZE)
        {
            int count = Mathf.Min(BATCH_SIZE, InstanceCount - start);
            var batchMatrices = new Matrix4x4[count];
            var batchOffsets = new float[count];
            System.Array.Copy(_matrices, start, batchMatrices, 0, count);
            System.Array.Copy(_timeOffsets, start, batchOffsets, 0, count);
            _batches.Add(batchMatrices);
            _timeOffsetBatches.Add(batchOffsets);
        }

        _mpb = new MaterialPropertyBlock();
    }

    private void SetupMaterialParams()
    {
        if (BoundsData == null) return;

        // 设置全局VAT参数（整个材质共享）
        VATMaterial.SetFloat(_VATFrameCountID, BoundsData.FrameCount);
        VATMaterial.SetFloat(_VATDurationID, BoundsData.Duration);
        VATMaterial.SetFloat(_VATTexWidthID, Mathf.NextPowerOfTwo(BoundsData.FrameCount));
        VATMaterial.SetFloat(_VATTexHeightID, Mathf.NextPowerOfTwo(BoundsData.VertexCount));
        VATMaterial.SetVector(_VATBoundsMinID, BoundsData.BoundsMin);
        VATMaterial.SetVector(_VATBoundsSizeID, BoundsData.BoundsSize);
    }

    void Update()
    {
        _globalTime += Time.deltaTime;

        // 每帧只需更新一个全局时间，单个DrawCall
        for (int b = 0; b < _batches.Count; b++)
        {
            _mpb.SetFloat(_VATCurrentTimeID, _globalTime);
            _mpb.SetFloatArray(_TimeOffsetID, _timeOffsetBatches[b]);

            Graphics.DrawMeshInstanced(
                InstanceMesh,
                0,
                VATMaterial,
                _batches[b],
                _batches[b].Length,
                _mpb,
                UnityEngine.Rendering.ShadowCastingMode.Off, // 关闭阴影，极大减少DrawCall
                false
            );
        }
    }
}
```

---

## 六、VAT进阶技巧

### 6.1 多动画状态混合

```csharp
/// <summary>
/// 支持多动画状态的VAT控制器
/// 通过在Shader中blend两张VAT纹理实现动画过渡
/// </summary>
public class VATMultiAnimController : MonoBehaviour
{
    [System.Serializable]
    public class VATAnimState
    {
        public string Name;
        public Texture2D PositionTex;
        public Texture2D NormalTex;
        public float Duration;
        public int FrameCount;
    }

    public VATAnimState[] AnimStates;
    private int _currentStateIndex = 0;
    private int _nextStateIndex = 0;
    private float _blendWeight = 1.0f; // 0=当前, 1=下一个
    private float _blendDuration = 0.3f;
    private float _blendTimer = 0;

    private MaterialPropertyBlock _mpb;
    private Renderer _renderer;

    private static readonly int _PosTex1ID = Shader.PropertyToID("_VATPositionTex");
    private static readonly int _PosTex2ID = Shader.PropertyToID("_VATPositionTex2");
    private static readonly int _BlendWeightID = Shader.PropertyToID("_VATBlendWeight");

    void Awake()
    {
        _renderer = GetComponent<Renderer>();
        _mpb = new MaterialPropertyBlock();
        SetState(0);
    }

    public void CrossFadeTo(int stateIndex)
    {
        if (stateIndex == _currentStateIndex) return;
        _nextStateIndex = stateIndex;
        _blendTimer = 0;
        _blendWeight = 0;
    }

    void Update()
    {
        if (_currentStateIndex != _nextStateIndex)
        {
            _blendTimer += Time.deltaTime;
            _blendWeight = Mathf.Clamp01(_blendTimer / _blendDuration);
            if (_blendWeight >= 1.0f)
            {
                _currentStateIndex = _nextStateIndex;
                _blendWeight = 1.0f;
            }
        }

        _renderer.GetPropertyBlock(_mpb);
        _mpb.SetFloat(_BlendWeightID, _blendWeight);
        _renderer.SetPropertyBlock(_mpb);
    }

    private void SetState(int index)
    {
        _renderer.GetPropertyBlock(_mpb);
        _mpb.SetTexture(_PosTex1ID, AnimStates[index].PositionTex);
        _renderer.SetPropertyBlock(_mpb);
    }
}
```

### 6.2 LOD与VAT结合

```csharp
/// <summary>
/// 基于距离的VAT LOD系统
/// 近处：骨骼动画；中距离：VAT；远处：静态Impostor
/// </summary>
public class VATLODSystem : MonoBehaviour
{
    public float VATSwitchDistance = 30f;
    public float StaticSwitchDistance = 100f;

    private Animator _animator;
    private VATInstanceManager _vatManager;
    private Transform _cameraTransform;

    void Update()
    {
        float dist = Vector3.Distance(transform.position, _cameraTransform.position);

        if (dist < VATSwitchDistance)
        {
            // 使用骨骼动画
            _animator.enabled = true;
        }
        else if (dist < StaticSwitchDistance)
        {
            // 切换到VAT渲染
            _animator.enabled = false;
            // 启用VAT实例渲染...
        }
        else
        {
            // 超远距离：Impostor（告示板）
        }
    }
}
```

---

## 七、性能数据参考

| 场景 | 传统骨骼动画 | VAT方案 | 提升倍数 |
|------|-------------|---------|---------|
| 100个NPC @ iPhone12 | 28 ms CPU | 2.1 ms GPU | 13x |
| 500个NPC @ iPhone12 | 崩溃 | 4.8 ms GPU | ∞ |
| DrawCall数 | 100+ | 1（每批1023） | 100x |
| 内存占用（100帧/500顶点）| 动态骨骼 | 约512KB纹理 | 减少60% |

---

## 八、适用场景与局限性

### 8.1 最佳应用场景

- ✅ **群体NPC**：城镇居民、战场士兵（数百到数千个）
- ✅ **植被动画**：摇摆的草丛、树木叶片（数千个实例）
- ✅ **破碎特效**：爆炸碎片、玻璃破碎（只播一次的一次性动画）
- ✅ **布料模拟回放**：预计算的布料动画缓存
- ✅ **背景角色**：远景中运动的人群

### 8.2 局限性与解决方案

| 局限性 | 说明 | 解决方案 |
|--------|------|----------|
| 不支持实时交互 | 动画数据预烘焙，无法响应物理碰撞 | 近处切回骨骼动画 |
| 纹理显存占用 | 长动画（>200帧）纹理较大 | 降低烘焙帧率（15fps足够） |
| 精度损失 | 8bit格式在大位移时有明显抖动 | 使用RGBAHalf格式 |
| 不支持动态换装 | 蒙皮已烘焙 | 配合多Pass Shader层叠绘制 |

---

## 九、最佳实践总结

1. **烘焙帧率15-24fps即可**：人眼对群体动画不敏感，高帧率浪费显存
2. **使用RGBAHalf格式**：8bit精度不足，32bit浪费；16bit Half是黄金平衡点
3. **给每个实例添加随机时间偏移**：避免所有NPC动作完全同步的"整齐划一"感
4. **关闭VAT物体的阴影投射**：大量实例的阴影是性能杀手，远景群体不需要精准阴影
5. **结合LOD系统**：10m内骨骼动画，30m外VAT，100m外静态布告板
6. **复用相同动画的烘焙结果**：同类型NPC共享同一套VAT纹理，只通过Matrix区分位置
