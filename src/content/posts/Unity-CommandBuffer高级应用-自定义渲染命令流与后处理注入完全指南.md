---
title: Unity CommandBuffer高级应用：自定义渲染命令流、后处理注入与渲染管线扩展完全指南
published: 2026-04-16
description: 深度解析Unity CommandBuffer的工作原理与高级应用技巧，涵盖渲染事件注入、自定义后处理效果、MRT多目标绘制、GPU资源上传、DrawMesh/DrawRenderer高级用法、Compute命令编排，以及与ScriptableRenderPass的协作模式，附完整代码示例与性能优化最佳实践。
tags: [Unity, CommandBuffer, 渲染管线, 后处理, 图形编程]
category: 渲染技术
draft: false
---

# Unity CommandBuffer 高级应用：自定义渲染命令流、后处理注入与渲染管线扩展完全指南

## 一、CommandBuffer 概述

### 1.1 什么是 CommandBuffer

`CommandBuffer` 是 Unity 提供的一种低层级渲染命令录制机制。它本质上是一个 **GPU 命令列表**，可以在渲染流水线的特定阶段注入自定义渲染操作：

```
Unity 渲染流水线（含 CommandBuffer 注入点）：

Frame Start
    │
    ▼  CameraEvent.BeforeDepthTexture
    ├─────────────────────────────────── [注入点1] 深度预处理
    │  Depth PrePass
    │
    ▼  CameraEvent.AfterDepthTexture  
    ├─────────────────────────────────── [注入点2] 深度后处理
    │  GBuffer / Opaques
    │
    ▼  CameraEvent.AfterGBuffer
    ├─────────────────────────────────── [注入点3] GBuffer处理
    │  Lighting
    │
    ▼  CameraEvent.BeforeForwardOpaque
    ├─────────────────────────────────── [注入点4] 不透明前处理
    │  Forward Opaques
    │
    ▼  CameraEvent.AfterForwardOpaque
    ├─────────────────────────────────── [注入点5] 不透明后处理  ★常用
    │  Skybox / Transparents
    │
    ▼  CameraEvent.AfterSkybox
    │
    ▼  CameraEvent.BeforeImageEffects
    ├─────────────────────────────────── [注入点6] 后处理前     ★常用
    │  Image Effects (Post-Processing)
    │
    ▼  CameraEvent.AfterEverything
    └─────────────────────────────────── [注入点7] 帧结束
```

### 1.2 CommandBuffer vs ScriptableRenderPass

| 特性 | CommandBuffer（Legacy）| ScriptableRenderPass（URP）|
|------|----------------------|--------------------------|
| 适用管线 | Built-in / URP 两者兼容 | URP 专用 |
| 注入方式 | `camera.AddCommandBuffer()` | `renderer.EnqueuePass()` |
| 资源管理 | 手动 | 半自动（URP 管理 RTHandle）|
| 执行顺序控制 | CameraEvent 枚举 | RenderPassEvent 精确排序 |
| RenderGraph 支持 | ❌ | ✓（Unity 6+）|
| 多平台优化 | 有限 | ✓ TBDR 感知 |
| **使用场景** | 插件兼容/Built-in 项目 | 新 URP 项目首选 |

### 1.3 CommandBuffer 的实际应用场景

```
CommandBuffer 核心应用场景：
1. 镜面/传送门渲染      → BeforeForwardOpaque 注入额外相机渲染
2. 屏幕空间贴花         → AfterGBuffer 读取深度写入 GBuffer
3. 全局描边效果         → AfterForwardOpaque 后处理模糊叠加
4. 自定义阴影           → BeforeLighting 注入自定义 Shadow Map
5. GPU 粒子系统         → 使用 DrawProceduralIndirect 绘制粒子
6. 截图/录制            → AfterEverything 读回 Backbuffer
7. XR 注入             → 在 VR 渲染特定事件注入 Pass
```

---

## 二、CommandBuffer 核心 API 详解

### 2.1 基础命令 API

```csharp
using UnityEngine;
using UnityEngine.Rendering;

public static class CommandBufferAPIGuide
{
    public static void DemonstrateBasicAPIs(Camera camera, Material mat,
        Mesh mesh, RenderTexture rt)
    {
        var cmd = new CommandBuffer { name = "MyCustomCommandBuffer" };
        
        // ─── 渲染目标控制 ───────────────────────────────────────────────────
        
        // 设置单渲染目标
        cmd.SetRenderTarget(rt);
        
        // 设置 MRT（多渲染目标）
        RenderTargetIdentifier[] colorTargets = {
            new RenderTargetIdentifier(rt),
            new RenderTargetIdentifier(BuiltinRenderTextureType.GBuffer1)
        };
        cmd.SetRenderTarget(colorTargets, 
            new RenderTargetIdentifier(BuiltinRenderTextureType.Depth));
        
        // 恢复相机目标
        cmd.SetRenderTarget(BuiltinRenderTextureType.CameraTarget);
        
        // ─── 清除操作 ───────────────────────────────────────────────────────
        cmd.ClearRenderTarget(
            clearDepth: true, 
            clearColor: true, 
            backgroundColor: Color.black,
            depth: 1.0f);
        
        // ─── 纹理操作 ───────────────────────────────────────────────────────
        
        // 获取临时 RT（帧内复用池）
        int tempId = Shader.PropertyToID("_TempBlurRT");
        cmd.GetTemporaryRT(tempId, camera.pixelWidth / 2, camera.pixelHeight / 2,
            0, FilterMode.Bilinear, RenderTextureFormat.ARGB32);
        
        // Blit（全屏后处理必备）
        cmd.Blit(BuiltinRenderTextureType.CameraTarget, tempId);
        cmd.Blit(tempId, BuiltinRenderTextureType.CameraTarget, mat, 0);
        
        // Blit 带 Viewport（部分区域）
        cmd.SetViewport(new Rect(0, 0, 256, 256));
        cmd.Blit(tempId, rt, mat, 1);
        
        // 释放临时 RT
        cmd.ReleaseTemporaryRT(tempId);
        
        // ─── 绘制命令 ───────────────────────────────────────────────────────
        
        // 绘制单个 Mesh
        cmd.DrawMesh(mesh, Matrix4x4.TRS(Vector3.zero, Quaternion.identity, Vector3.one), 
            mat, 0, 0);
        
        // 绘制场景中的 Renderer
        cmd.DrawRenderer(camera.GetComponent<Renderer>(), mat, 0, 0);
        
        // GPU Instancing 批量绘制
        Matrix4x4[] matrices = new Matrix4x4[1000];
        cmd.DrawMeshInstanced(mesh, 0, mat, 0, matrices);
        
        // Procedural 绘制（无 VBO，Shader 自行计算顶点）
        cmd.DrawProcedural(
            Matrix4x4.identity, mat, 0,
            MeshTopology.Triangles,
            vertexCount: 3,    // 全屏三角形
            instanceCount: 1);
        
        // ─── Shader 参数设置 ─────────────────────────────────────────────────
        
        cmd.SetGlobalTexture("_GlobalTex", rt);
        cmd.SetGlobalFloat("_GlobalFloat", 1.0f);
        cmd.SetGlobalVector("_GlobalVec", new Vector4(1, 2, 3, 4));
        cmd.SetGlobalMatrix("_GlobalMat", Matrix4x4.identity);
        cmd.SetGlobalBuffer("_GlobalBuffer", null); // GraphicsBuffer
        
        // 使用 MaterialPropertyBlock（避免材质实例化）
        var mpb = new MaterialPropertyBlock();
        mpb.SetFloat("_Intensity", 2.0f);
        cmd.DrawMesh(mesh, Matrix4x4.identity, mat, 0, 0, mpb);
        
        // ─── Compute Shader 命令 ─────────────────────────────────────────────
        
        ComputeShader cs = null; // 假设已赋值
        if (cs != null)
        {
            int kernel = cs.FindKernel("Main");
            cmd.SetComputeTextureParam(cs, kernel, "_Output", rt);
            cmd.DispatchCompute(cs, kernel, 
                Mathf.CeilToInt(rt.width / 8f),
                Mathf.CeilToInt(rt.height / 8f),
                1);
        }
        
        // ─── 注入到相机 ──────────────────────────────────────────────────────
        camera.AddCommandBuffer(CameraEvent.AfterForwardOpaque, cmd);
        
        // 移除
        // camera.RemoveCommandBuffer(CameraEvent.AfterForwardOpaque, cmd);
    }
}
```

### 2.2 RenderTargetIdentifier 完整用法

```csharp
/// <summary>
/// RenderTargetIdentifier 的各种构造方式
/// </summary>
public static class RenderTargetIdentifierGuide
{
    public static void Demonstrate()
    {
        // 1. 从 BuiltinRenderTextureType（内置渲染纹理）
        var cameraTarget = new RenderTargetIdentifier(BuiltinRenderTextureType.CameraTarget);
        var depth = new RenderTargetIdentifier(BuiltinRenderTextureType.Depth);
        var gBuffer0 = new RenderTargetIdentifier(BuiltinRenderTextureType.GBuffer0);
        var motionVectors = new RenderTargetIdentifier(BuiltinRenderTextureType.MotionVectors);
        
        // 2. 从 Shader Property ID（GetTemporaryRT 分配的 RT）
        int tempId = Shader.PropertyToID("_BlurTemp");
        var tempRT = new RenderTargetIdentifier(tempId);
        
        // 3. 从 RenderTexture 对象
        RenderTexture rt = new RenderTexture(512, 512, 24);
        var fromRT = new RenderTargetIdentifier(rt);
        
        // 4. 从 Texture（上传到 GPU 的纹理）
        Texture2D tex = Texture2D.whiteTexture;
        var fromTex = new RenderTargetIdentifier(tex);
        
        // 5. 指定 Cube Face（渲染到 CubemapFace）
        var cubeFace = new RenderTargetIdentifier(rt, 0, 
            CubemapFace.PositiveX, depthSlice: 0);
        
        // 6. 指定 MipMap Level
        var mipLevel = new RenderTargetIdentifier(rt, mipLevel: 2,
            CubemapFace.Unknown, depthSlice: 0);
    }
}
```

---

## 三、自定义后处理效果完整实现

### 3.1 屏幕空间扭曲（Heat Wave Effect）

```csharp
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// 屏幕空间热浪扭曲效果（基于 CommandBuffer 实现）
/// 在指定区域内对屏幕 UV 进行扭曲，模拟热浪/折射效果
/// </summary>
[RequireComponent(typeof(Camera))]
public class HeatWaveEffect : MonoBehaviour
{
    [Header("扭曲参数")]
    public Texture2D distortionNoise;       // 扭曲噪声贴图
    [Range(0f, 0.1f)]
    public float distortionStrength = 0.02f;
    [Range(0f, 5f)]
    public float noiseScrollSpeed = 1.0f;
    
    [Header("颜色偏移")]
    public bool enableChromaticAberration = true;
    [Range(0f, 0.01f)]
    public float chromaOffset = 0.003f;
    
    private Camera _camera;
    private CommandBuffer _cmd;
    private Material _heatWaveMat;
    private int _grabPassId;
    private int _distortedId;
    
    // Shader Property IDs（静态缓存避免重复哈希）
    private static readonly int s_NoiseTexId      = Shader.PropertyToID("_NoiseTex");
    private static readonly int s_StrengthId      = Shader.PropertyToID("_DistortStrength");
    private static readonly int s_ScrollSpeedId   = Shader.PropertyToID("_ScrollSpeed");
    private static readonly int s_ChromaOffsetId  = Shader.PropertyToID("_ChromaOffset");
    private static readonly int s_GrabTexId       = Shader.PropertyToID("_GrabTex");
    
    private void Awake()
    {
        _camera = GetComponent<Camera>();
        _grabPassId   = Shader.PropertyToID("_HeatWaveGrabRT");
        _distortedId  = Shader.PropertyToID("_HeatWaveDistortedRT");
    }
    
    private void OnEnable()
    {
        if (_heatWaveMat == null)
        {
            var shader = Shader.Find("Custom/HeatWave");
            if (shader == null)
            {
                Debug.LogError("HeatWave shader not found!");
                enabled = false;
                return;
            }
            _heatWaveMat = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
        }
        
        BuildCommandBuffer();
        _camera.AddCommandBuffer(CameraEvent.BeforeImageEffects, _cmd);
    }
    
    private void OnDisable()
    {
        if (_cmd != null)
        {
            _camera.RemoveCommandBuffer(CameraEvent.BeforeImageEffects, _cmd);
            _cmd.Release();
            _cmd = null;
        }
    }
    
    private void BuildCommandBuffer()
    {
        _cmd?.Release();
        _cmd = new CommandBuffer { name = "HeatWaveEffect" };
        
        int screenW = _camera.pixelWidth;
        int screenH = _camera.pixelHeight;
        
        // Step 1: 抓取当前屏幕颜色
        _cmd.GetTemporaryRT(_grabPassId, screenW, screenH, 0,
            FilterMode.Bilinear, RenderTextureFormat.ARGB32);
        _cmd.Blit(BuiltinRenderTextureType.CameraTarget, _grabPassId);
        
        // Step 2: 申请输出 RT
        _cmd.GetTemporaryRT(_distortedId, screenW, screenH, 0,
            FilterMode.Bilinear, RenderTextureFormat.ARGB32);
        
        // Step 3: 设置材质参数
        _cmd.SetGlobalTexture(s_GrabTexId, _grabPassId);
        _cmd.SetGlobalTexture(s_NoiseTexId, distortionNoise);
        _cmd.SetGlobalFloat(s_StrengthId, distortionStrength);
        _cmd.SetGlobalFloat(s_ScrollSpeedId, noiseScrollSpeed);
        _cmd.SetGlobalFloat(s_ChromaOffsetId, enableChromaticAberration ? chromaOffset : 0f);
        
        // Step 4: 执行扭曲 Shader
        _cmd.Blit(_grabPassId, _distortedId, _heatWaveMat, 0);
        
        // Step 5: 写回相机目标
        _cmd.Blit(_distortedId, BuiltinRenderTextureType.CameraTarget);
        
        // 释放临时 RT
        _cmd.ReleaseTemporaryRT(_grabPassId);
        _cmd.ReleaseTemporaryRT(_distortedId);
    }
    
    // 当参数变化时重建 CommandBuffer
    private void OnValidate()
    {
        if (_cmd != null && _heatWaveMat != null)
        {
            // 仅更新材质参数，不重建整个 CommandBuffer
            _heatWaveMat.SetFloat(s_StrengthId, distortionStrength);
            _heatWaveMat.SetFloat(s_ScrollSpeedId, noiseScrollSpeed);
        }
    }
    
    private void OnDestroy()
    {
        if (_heatWaveMat != null)
            DestroyImmediate(_heatWaveMat);
    }
}
```

对应的 Shader：

```hlsl
Shader "Custom/HeatWave"
{
    Properties
    {
        _NoiseTex       ("Noise Texture",   2D)     = "bump" {}
        _GrabTex        ("Grab Texture",    2D)     = "white" {}
        _DistortStrength("Distort Strength",Float)  = 0.02
        _ScrollSpeed    ("Scroll Speed",    Float)  = 1.0
        _ChromaOffset   ("Chroma Offset",  Float)   = 0.003
    }
    
    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "" }
        ZTest Always ZWrite Off Cull Off
        
        Pass
        {
            Name "HeatWave"
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            
            sampler2D _NoiseTex;
            sampler2D _GrabTex;
            float _DistortStrength;
            float _ScrollSpeed;
            float _ChromaOffset;
            
            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f    { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            
            v2f vert(appdata v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv  = v.uv;
                return o;
            }
            
            half4 frag(v2f i) : SV_Target
            {
                float2 uv = i.uv;
                
                // 采样噪声贴图（两层叠加制造湍流感）
                float2 noiseUV1 = uv + float2(_Time.y * _ScrollSpeed * 0.3, _Time.y * _ScrollSpeed * 0.5);
                float2 noiseUV2 = uv * 0.7 + float2(-_Time.y * _ScrollSpeed * 0.2, _Time.y * _ScrollSpeed * 0.4);
                
                float2 noise1 = tex2D(_NoiseTex, noiseUV1).rg * 2.0 - 1.0;
                float2 noise2 = tex2D(_NoiseTex, noiseUV2).rg * 2.0 - 1.0;
                float2 offset = (noise1 + noise2) * 0.5 * _DistortStrength;
                
                // 色差分离（红绿蓝通道使用略不同的偏移）
                float2 uvR = uv + offset + float2(_ChromaOffset, 0);
                float2 uvG = uv + offset;
                float2 uvB = uv + offset - float2(_ChromaOffset, 0);
                
                half r = tex2D(_GrabTex, uvR).r;
                half g = tex2D(_GrabTex, uvG).g;
                half b = tex2D(_GrabTex, uvB).b;
                
                return half4(r, g, b, 1.0);
            }
            ENDHLSL
        }
    }
}
```

---

## 四、DrawRenderer 高级用法：动态轮廓线

```csharp
/// <summary>
/// 基于 CommandBuffer 的动态高亮轮廓线效果
/// 原理：将目标物体渲染到 Mask RT → 模糊 Mask → 差值得到轮廓 → 叠加到主画面
/// </summary>
public class OutlineHighlightSystem : MonoBehaviour
{
    [Header("轮廓设置")]
    public Color outlineColor = Color.yellow;
    [Range(1, 8)]
    public int blurRadius = 3;
    [Range(0f, 2f)]
    public float outlineWidth = 1.5f;
    
    private Camera _camera;
    private CommandBuffer _outlineCmd;
    private Material _blurMat;
    private Material _outlineMat;
    
    // 当前高亮的对象列表
    private readonly System.Collections.Generic.List<Renderer> _highlightedRenderers 
        = new System.Collections.Generic.List<Renderer>();
    
    private static readonly int s_MaskId    = Shader.PropertyToID("_OutlineMask");
    private static readonly int s_BlurredId = Shader.PropertyToID("_OutlineBlurred");
    private static readonly int s_ColorId   = Shader.PropertyToID("_OutlineColor");
    private static readonly int s_WidthId   = Shader.PropertyToID("_OutlineWidth");
    
    private void Awake()
    {
        _camera = GetComponent<Camera>();
        _blurMat   = new Material(Shader.Find("Hidden/GaussianBlur")) 
                     { hideFlags = HideFlags.HideAndDontSave };
        _outlineMat = new Material(Shader.Find("Hidden/OutlineComposite")) 
                     { hideFlags = HideFlags.HideAndDontSave };
    }
    
    /// <summary>
    /// 添加需要高亮显示的 Renderer
    /// </summary>
    public void AddHighlight(Renderer renderer)
    {
        if (!_highlightedRenderers.Contains(renderer))
        {
            _highlightedRenderers.Add(renderer);
            RebuildCommandBuffer();
        }
    }
    
    /// <summary>
    /// 移除高亮
    /// </summary>
    public void RemoveHighlight(Renderer renderer)
    {
        if (_highlightedRenderers.Remove(renderer))
        {
            RebuildCommandBuffer();
        }
    }
    
    private void RebuildCommandBuffer()
    {
        // 清理旧的 CommandBuffer
        if (_outlineCmd != null)
        {
            _camera.RemoveCommandBuffer(CameraEvent.BeforeImageEffects, _outlineCmd);
            _outlineCmd.Release();
            _outlineCmd = null;
        }
        
        if (_highlightedRenderers.Count == 0) return;
        
        _outlineCmd = new CommandBuffer { name = "OutlineHighlight" };
        
        int w = _camera.pixelWidth;
        int h = _camera.pixelHeight;
        
        // Step 1: 渲染高亮对象到 Mask（纯白色）
        _outlineCmd.GetTemporaryRT(s_MaskId, w, h, 0, FilterMode.Bilinear, 
            RenderTextureFormat.R8);
        _outlineCmd.SetRenderTarget(s_MaskId);
        _outlineCmd.ClearRenderTarget(false, true, Color.black);
        
        // 白色填充材质
        var fillMat = new Material(Shader.Find("Hidden/SimpleFill"));
        fillMat.color = Color.white;
        
        foreach (var r in _highlightedRenderers)
        {
            if (r != null)
            {
                // 用白色渲染目标物体轮廓 Mask
                _outlineCmd.DrawRenderer(r, fillMat, 0, 0);
            }
        }
        
        // Step 2: 高斯模糊 Mask（横向）
        _outlineCmd.GetTemporaryRT(s_BlurredId, w, h, 0, FilterMode.Bilinear, 
            RenderTextureFormat.R8);
        _outlineCmd.SetGlobalFloat("_BlurRadius", blurRadius);
        _outlineCmd.Blit(s_MaskId, s_BlurredId, _blurMat, 0);  // 横向
        _outlineCmd.Blit(s_BlurredId, s_MaskId, _blurMat, 1);  // 纵向
        
        // Step 3: 轮廓合成（模糊Mask - 原始Mask = 轮廓区域）并叠加到主画面
        _outlineMat.SetColor(s_ColorId, outlineColor);
        _outlineMat.SetFloat(s_WidthId, outlineWidth);
        _outlineCmd.SetGlobalTexture("_OriginalMask", s_BlurredId);
        _outlineCmd.SetGlobalTexture("_BlurredMask",  s_MaskId);
        
        _outlineCmd.Blit(BuiltinRenderTextureType.CameraTarget,
            BuiltinRenderTextureType.CameraTarget, _outlineMat);
        
        // 释放临时 RT
        _outlineCmd.ReleaseTemporaryRT(s_MaskId);
        _outlineCmd.ReleaseTemporaryRT(s_BlurredId);
        
        _camera.AddCommandBuffer(CameraEvent.BeforeImageEffects, _outlineCmd);
    }
    
    private void OnDestroy()
    {
        if (_outlineCmd != null)
            _camera.RemoveCommandBuffer(CameraEvent.BeforeImageEffects, _outlineCmd);
        
        if (_blurMat   != null) DestroyImmediate(_blurMat);
        if (_outlineMat != null) DestroyImmediate(_outlineMat);
    }
}
```

---

## 五、GPU 资源上传与 Compute 命令编排

### 5.1 CommandBuffer 中的 Compute Dispatch 序列

```csharp
/// <summary>
/// 复杂 Compute Shader 管线的 CommandBuffer 编排示例
/// 演示：粒子模拟 → 排序 → 渲染 的完整 GPU 计算流程
/// </summary>
public class GPUParticlePipeline : MonoBehaviour
{
    public ComputeShader simulationCS;
    public ComputeShader bitonicSortCS;
    public Material particleRenderMat;
    
    private GraphicsBuffer _particleBuffer;
    private GraphicsBuffer _sortKeysBuffer;
    private GraphicsBuffer _indirectArgsBuffer;
    private CommandBuffer _simulationCmd;
    private Camera _mainCamera;
    
    private const int ParticleCount = 100000;
    
    private int _kernelSimulate;
    private int _kernelSort;
    private int _kernelSortStep;
    
    private void Start()
    {
        _mainCamera = Camera.main;
        
        // 分配 GPU 缓冲区
        _particleBuffer = new GraphicsBuffer(
            GraphicsBuffer.Target.Structured,
            ParticleCount,
            System.Runtime.InteropServices.Marshal.SizeOf<ParticleData>());
        
        _sortKeysBuffer = new GraphicsBuffer(
            GraphicsBuffer.Target.Structured,
            ParticleCount, sizeof(ulong));  // 64-bit sort key [depth(32) | index(32)]
        
        // Indirect Draw 参数缓冲（5个 uint: vertexCount, instanceCount, startVertex, startInstance, ？）
        _indirectArgsBuffer = new GraphicsBuffer(
            GraphicsBuffer.Target.IndirectArguments,
            1, 5 * sizeof(uint));
        _indirectArgsBuffer.SetData(new uint[] { 6, (uint)ParticleCount, 0, 0, 0 });
        
        _kernelSimulate = simulationCS.FindKernel("SimulateParticles");
        _kernelSort     = bitonicSortCS.FindKernel("BitonicSort");
        _kernelSortStep = bitonicSortCS.FindKernel("BitonicSortStep");
        
        BuildPipelineCommandBuffer();
    }
    
    private void BuildPipelineCommandBuffer()
    {
        _simulationCmd?.Release();
        _simulationCmd = new CommandBuffer { name = "GPUParticlePipeline" };
        
        // ── Stage 1: 模拟更新 ──────────────────────────────────────────────
        _simulationCmd.SetComputeBufferParam(simulationCS, _kernelSimulate,
            "_Particles", _particleBuffer);
        _simulationCmd.SetComputeFloatParam(simulationCS, "_DeltaTime", Time.deltaTime);
        _simulationCmd.SetComputeFloatParams(simulationCS, "_Gravity", 0, -9.8f, 0);
        
        _simulationCmd.DispatchCompute(simulationCS, _kernelSimulate,
            Mathf.CeilToInt(ParticleCount / 64f), 1, 1);
        
        // GPU 内存屏障（确保模拟写入完成后再读取）
        // Unity 在 DispatchCompute 之间自动插入 UAV 屏障，但显式声明更清晰
        
        // ── Stage 2: 生成深度排序键 ──────────────────────────────────────
        _simulationCmd.SetComputeBufferParam(simulationCS, 
            simulationCS.FindKernel("GenerateSortKeys"),
            "_Particles", _particleBuffer);
        _simulationCmd.SetComputeBufferParam(simulationCS,
            simulationCS.FindKernel("GenerateSortKeys"),
            "_SortKeys", _sortKeysBuffer);
        _simulationCmd.SetComputeMatrixParam(simulationCS, "_ViewMatrix",
            _mainCamera.worldToCameraMatrix);
        _simulationCmd.DispatchCompute(simulationCS,
            simulationCS.FindKernel("GenerateSortKeys"),
            Mathf.CeilToInt(ParticleCount / 64f), 1, 1);
        
        // ── Stage 3: Bitonic Sort（GPU 排序）────────────────────────────
        // Bitonic Sort 需要 log2(N)*(log2(N)+1)/2 次 Dispatch
        int n = ParticleCount;
        _simulationCmd.SetComputeBufferParam(bitonicSortCS, _kernelSort, 
            "_SortKeys", _sortKeysBuffer);
        
        for (int size = 2; size <= n; size <<= 1)
        {
            for (int stride = size >> 1; stride > 0; stride >>= 1)
            {
                _simulationCmd.SetComputeIntParam(bitonicSortCS, "_SortSize", size);
                _simulationCmd.SetComputeIntParam(bitonicSortCS, "_SortStride", stride);
                _simulationCmd.DispatchCompute(bitonicSortCS, _kernelSortStep,
                    Mathf.CeilToInt(n / 128f), 1, 1);
            }
        }
        
        // ── Stage 4: Indirect 绘制（无 CPU 回读）────────────────────────
        _simulationCmd.DrawProceduralIndirect(
            Matrix4x4.identity,
            particleRenderMat, 0,
            MeshTopology.Triangles,
            _indirectArgsBuffer,
            argsOffset: 0);
        
        _mainCamera.AddCommandBuffer(CameraEvent.AfterForwardAlpha, _simulationCmd);
    }
    
    [System.Runtime.InteropServices.StructLayout(
        System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct ParticleData
    {
        public Vector3 position;
        public Vector3 velocity;
        public float   lifetime;
        public float   size;
        public Vector4 color;
    }
    
    private void OnDestroy()
    {
        _particleBuffer?.Dispose();
        _sortKeysBuffer?.Dispose();
        _indirectArgsBuffer?.Dispose();
        
        if (_mainCamera != null && _simulationCmd != null)
            _mainCamera.RemoveCommandBuffer(CameraEvent.AfterForwardAlpha, _simulationCmd);
        
        _simulationCmd?.Release();
    }
}
```

---

## 六、Light CommandBuffer（光源级注入）

CommandBuffer 不仅可以注入到 Camera，还能注入到 Light：

```csharp
/// <summary>
/// 使用 Light.AddCommandBuffer 实现自定义阴影贴图注入
/// </summary>
public class CustomShadowInjector : MonoBehaviour
{
    public Light targetLight;
    public RenderTexture customShadowMap;
    public Material shadowReplaceMat;
    
    private CommandBuffer _shadowCmd;
    
    private void OnEnable()
    {
        if (targetLight == null) return;
        
        _shadowCmd = new CommandBuffer { name = "CustomShadowInjection" };
        
        // 在阴影贴图渲染前注入自定义阴影
        _shadowCmd.SetRenderTarget(customShadowMap);
        _shadowCmd.ClearRenderTarget(true, true, Color.white);
        
        // 渲染自定义阴影遮挡体
        // _shadowCmd.DrawMesh(shadowCasterMesh, matrix, shadowReplaceMat);
        
        // 将自定义阴影贴图传递给全局 Shader
        _shadowCmd.SetGlobalTexture("_CustomShadowMap", customShadowMap);
        
        // LightEvent.BeforeShadowMap  → 替换整个阴影贴图渲染
        // LightEvent.AfterShadowMap   → 修改已生成的阴影贴图
        // LightEvent.BeforeShadowMapPass → 单个阴影 Pass 之前
        targetLight.AddCommandBuffer(LightEvent.BeforeShadowMap, _shadowCmd);
    }
    
    private void OnDisable()
    {
        if (targetLight != null && _shadowCmd != null)
            targetLight.RemoveCommandBuffer(LightEvent.BeforeShadowMap, _shadowCmd);
        
        _shadowCmd?.Release();
        _shadowCmd = null;
    }
}
```

---

## 七、URP 中 CommandBuffer 与 ScriptableRenderPass 的协作

```csharp
/// <summary>
/// 在 URP ScriptableRenderPass 中优雅使用 CommandBuffer
/// （适合需要与 URP 集成但仍依赖 CommandBuffer API 的场景）
/// </summary>
public class URPCommandBufferBridge : ScriptableRenderPass
{
    private readonly string _profilerTag;
    private readonly Material _effectMaterial;
    
    // URP 中的临时 RT 使用 RenderTargetHandle
    private RenderTargetHandle _tempRT;
    
    public URPCommandBufferBridge(string tag, Material mat)
    {
        _profilerTag = tag;
        _effectMaterial = mat;
        _tempRT.Init("_URPBridgeTempRT");
        renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
    }
    
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        // 在这里申请 RT（生命周期与 Pass 相同）
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        cmd.GetTemporaryRT(_tempRT.id, desc, FilterMode.Bilinear);
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        // 从池中获取 CommandBuffer（URP 推荐方式）
        CommandBuffer cmd = CommandBufferPool.Get(_profilerTag);
        
        using (new ProfilingScope(cmd, new ProfilingSampler(_profilerTag)))
        {
            var cameraTarget = renderingData.cameraData.renderer.cameraColorTarget;
            
            // 将相机颜色复制到临时 RT
            cmd.Blit(cameraTarget, _tempRT.Identifier());
            
            // 执行后处理效果
            cmd.SetGlobalTexture("_MainTex", _tempRT.Identifier());
            cmd.Blit(_tempRT.Identifier(), cameraTarget, _effectMaterial);
        }
        
        // 提交 CommandBuffer 到渲染上下文
        context.ExecuteCommandBuffer(cmd);
        
        // 归还到池（不要 Release，Release 会销毁对象）
        CommandBufferPool.Release(cmd);
    }
    
    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 释放临时 RT
        cmd.ReleaseTemporaryRT(_tempRT.id);
    }
}
```

---

## 八、CommandBuffer 性能优化最佳实践

### 8.1 关键性能原则

```csharp
/// <summary>
/// CommandBuffer 性能优化代码示例
/// </summary>
public static class CommandBufferBestPractices
{
    // ✓ 最佳实践1: 缓存 Shader Property ID
    private static readonly int s_MainTexId = Shader.PropertyToID("_MainTex");
    private static readonly int s_IntensityId = Shader.PropertyToID("_Intensity");
    
    // ✗ 错误做法：每帧字符串查找
    // cmd.SetGlobalTexture("_MainTex", tex);  // 每次哈希计算
    
    // ✓ 正确做法：使用缓存的 int ID
    public static void SetTextureCorrectly(CommandBuffer cmd, Texture tex)
    {
        cmd.SetGlobalTexture(s_MainTexId, tex);  // O(1) 整数查找
    }
    
    // ✓ 最佳实践2: 避免每帧重建 CommandBuffer
    // 只在参数结构变化时重建（如分辨率变化、效果开关），
    // 参数更新通过 SetGlobalXxx 完成
    
    // ✓ 最佳实践3: 合理使用 ProfilingScope
    public static void ExecuteWithProfiling(ScriptableRenderContext context)
    {
        var cmd = CommandBufferPool.Get("MyPass");
        
        // ProfilingScope 会在 Frame Debugger 和 Profiler 中显示层级
        using (new ProfilingScope(cmd, new ProfilingSampler("MyEffect.Blur")))
        {
            // 模糊操作
        }
        
        using (new ProfilingScope(cmd, new ProfilingSampler("MyEffect.Composite")))
        {
            // 合成操作
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
    
    // ✓ 最佳实践4: 使用半精度 RT 节省带宽
    public static void AllocateOptimalRT(CommandBuffer cmd, Camera camera)
    {
        var desc = new RenderTextureDescriptor(
            camera.pixelWidth, camera.pixelHeight,
            RenderTextureFormat.RGB111110Float,  // 32-bit，比 RGBA32 少 25% 带宽
            depthBufferBits: 0)
        {
            useMipMap = false,
            autoGenerateMips = false,
            msaaSamples = 1,
            // 移动端优化：不需要随机读写时关闭 randomWrite
            // randomWrite = false,
        };
        
        cmd.GetTemporaryRT(Shader.PropertyToID("_OptimalRT"), desc, FilterMode.Bilinear);
    }
    
    // ✓ 最佳实践5: Blit 全屏三角形（比全屏 Quad 少一个顶点，避免对角线 overdraw）
    // Unity Blit 内部已使用全屏三角形，无需手动实现
    
    // ✓ 最佳实践6: SetRenderTarget 批量操作减少 API 调用
    public static void SetMRTOptimally(CommandBuffer cmd, 
        RenderTargetIdentifier[] colors, RenderTargetIdentifier depth,
        RenderBufferLoadAction loadAction = RenderBufferLoadAction.DontCare,
        RenderBufferStoreAction storeAction = RenderBufferStoreAction.Store)
    {
        // 一次调用设置所有 MRT（避免逐个设置）
        cmd.SetRenderTarget(colors, depth, 
            (int)loadAction, (int)storeAction);  // 重载版本
    }
}
```

### 8.2 常见错误与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| Blit 后画面为黑 | 源 RT 未填充或目标设置错误 | 检查 SetRenderTarget 顺序 |
| 后处理闪烁 | CommandBuffer 每帧重建但事件时机不对 | 在 OnPreRender 而非 Update 重建 |
| 内存持续增长 | ReleaseTemporaryRT 未调用 | 确保 GetTemporary 与 Release 配对 |
| Editor/Runtime 不一致 | 依赖 Camera.current 在 Editor 中为 null | 使用 renderingData.cameraData.camera |
| 移动端效果异常 | BuiltinRenderTextureType 在 TBDR 上行为不同 | 测试时开启 Frame Debugger 验证 |
| 多相机时重复执行 | 未在 OnDisable 移除 CommandBuffer | 严格对称 Add/Remove 操作 |

---

## 九、完整案例：动态遮罩溶解过渡

```csharp
/// <summary>
/// 使用 CommandBuffer 实现场景过渡溶解效果
/// 原理：生成溶解进度纹理 → 与场景颜色混合 → 平滑过渡
/// </summary>
public class SceneDissolveTransition : MonoBehaviour
{
    [Range(0f, 1f)]
    public float dissolveProgress = 0f;
    
    public Texture2D dissolvePattern;       // 溶解图案（噪声/自定义）
    public Color dissolveEdgeColor = Color.red;
    [Range(0f, 0.1f)]
    public float edgeWidth = 0.05f;
    
    private Camera _camera;
    private Material _dissolveMat;
    private CommandBuffer _dissolveCmd;
    private static readonly int s_ProgressId    = Shader.PropertyToID("_Progress");
    private static readonly int s_PatternId     = Shader.PropertyToID("_Pattern");
    private static readonly int s_EdgeColorId   = Shader.PropertyToID("_EdgeColor");
    private static readonly int s_EdgeWidthId   = Shader.PropertyToID("_EdgeWidth");
    
    private void Awake()
    {
        _camera = GetComponent<Camera>();
        _dissolveMat = new Material(Shader.Find("Custom/DissolveTransition"))
            { hideFlags = HideFlags.HideAndDontSave };
    }
    
    public System.Collections.IEnumerator PlayTransition(float duration)
    {
        // 建立 CommandBuffer
        SetupCommandBuffer();
        
        float elapsed = 0f;
        while (elapsed < duration)
        {
            dissolveProgress = elapsed / duration;
            _dissolveMat.SetFloat(s_ProgressId, dissolveProgress);
            elapsed += Time.deltaTime;
            yield return null;
        }
        
        dissolveProgress = 1f;
        _dissolveMat.SetFloat(s_ProgressId, 1f);
        
        // 完成后移除
        yield return new WaitForSeconds(0.1f);
        TeardownCommandBuffer();
    }
    
    private void SetupCommandBuffer()
    {
        _dissolveCmd = new CommandBuffer { name = "DissolveTransition" };
        
        _dissolveMat.SetTexture(s_PatternId, dissolvePattern);
        _dissolveMat.SetColor(s_EdgeColorId, dissolveEdgeColor);
        _dissolveMat.SetFloat(s_EdgeWidthId, edgeWidth);
        _dissolveMat.SetFloat(s_ProgressId, 0f);
        
        _dissolveCmd.Blit(BuiltinRenderTextureType.CameraTarget,
            BuiltinRenderTextureType.CameraTarget, _dissolveMat);
        
        _camera.AddCommandBuffer(CameraEvent.AfterEverything, _dissolveCmd);
    }
    
    private void TeardownCommandBuffer()
    {
        if (_dissolveCmd != null)
        {
            _camera.RemoveCommandBuffer(CameraEvent.AfterEverything, _dissolveCmd);
            _dissolveCmd.Release();
            _dissolveCmd = null;
        }
    }
    
    private void OnDestroy()
    {
        TeardownCommandBuffer();
        if (_dissolveMat != null) DestroyImmediate(_dissolveMat);
    }
}
```

---

## 十、最佳实践总结

### 10.1 使用决策树

```
是否选择 CommandBuffer？

使用 Built-in 管线？
    ├─ 是 → ✓ 使用 CommandBuffer + Camera/Light AddCommandBuffer
    └─ 否（URP）→
        ├─ 需要 RenderGraph 特性（自动资源管理、Pass 剔除）？
        │    ├─ 是 → ✓ 使用 ScriptableRenderPass + RecordRenderGraph
        │    └─ 否 → ✓ 使用 ScriptableRenderPass.Execute + CommandBufferPool
        │
        └─ 需要与 Legacy 插件兼容？
             ├─ 是 → ✓ 使用 CommandBuffer（注意 URP 限制）
             └─ 否 → ✓ 完全迁移到 ScriptableRenderPass
```

### 10.2 CheckList

```
CommandBuffer 开发 CheckList：
✓ Shader Property ID 全部静态缓存
✓ GetTemporaryRT / ReleaseTemporaryRT 严格配对
✓ OnEnable/OnDisable 中对称 Add/Remove CommandBuffer
✓ 使用 ProfilingScope 包裹关键路径（Frame Debugger 可见）
✓ 避免每帧重建 CommandBuffer（仅在结构变化时重建）
✓ 移动端测试 TBDR 兼容性（特别是 BuiltinRenderTextureType 读取）
✓ URP 下优先使用 CommandBufferPool 而非 new CommandBuffer
✓ 多相机场景下验证 CommandBuffer 不被重复执行
```

---

## 十一、总结

`CommandBuffer` 是 Unity 渲染管线的"脚手架"，提供了在渲染流水线任意注入点执行自定义 GPU 命令的能力。其核心价值在于：

1. **注入点灵活**：CameraEvent/LightEvent 覆盖渲染管线的每个阶段
2. **命令录制分离**：在 CPU 端录制命令列表，GPU 延迟执行，减少 CPU-GPU 同步开销
3. **丰富的 API**：Blit/DrawMesh/DrawRenderer/DispatchCompute 满足各类渲染需求
4. **兼容性强**：Built-in 与 URP 两种管线均可使用
5. **调试友好**：ProfilingScope + Frame Debugger 提供完整的渲染分析链路

随着 URP RenderGraph 的成熟，新项目推荐逐步迁移到 `ScriptableRenderPass.RecordRenderGraph`，但 CommandBuffer 在 Built-in 管线维护、插件兼容以及某些特殊渲染注入场景中依然不可替代。
