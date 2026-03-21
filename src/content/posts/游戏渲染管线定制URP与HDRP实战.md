---
title: 游戏渲染管线定制：URP与HDRP实战
description: 深入解析Unity可编程渲染管线（SRP）架构，掌握URP自定义Pass、Renderer Feature开发、后处理效果扩展，以及从内置管线迁移到URP的完整指南。
pubDate: 2026-03-21
category: 图形渲染
tags: [URP, HDRP, SRP, 渲染管线, 后处理, Unity]
---

# 游戏渲染管线定制：URP与HDRP实战

Unity 的可编程渲染管线（SRP）让开发者可以完全掌控渲染流程。URP（Universal Render Pipeline）是移动端和中低端项目的首选，HDRP（High Definition Render Pipeline）则用于追求极致画质的 PC/主机项目。

## 一、SRP 架构概览

```
Unity SRP 体系：

ScriptableRenderPipeline（SRP 基类）
├── UniversalRenderPipeline（URP）
│   ├── 适合：移动端、中低端PC、2D项目
│   ├── 特点：性能优先，单次Pass渲染
│   └── 场景：手游、独立游戏、移动AR/VR
│
└── HighDefinitionRenderPipeline（HDRP）
    ├── 适合：高端PC、主机
    ├── 特点：物理精确、极致画质
    └── 场景：3A游戏、建筑可视化、影视级渲染

自定义SRP（Core RP Library）
    └── 从零构建自己的渲染管线（游戏引擎级工作）
```

## 二、URP 核心架构

### 2.1 URP 渲染流程

```
每帧渲染流程（URP）：

1. BeginFrameRendering
2. SetupCullingParameters（视锥体剔除参数）
3. Cull（剔除不可见对象）
4. SetupRenderPasses（配置渲染Pass序列）
5. Execute Passes：
   ├── DepthPrepass（深度预通道，可选）
   ├── ShadowCaster Pass（阴影贴图）
   ├── Opaque Forward Pass（不透明物体）
   ├── Skybox Pass（天空盒）
   ├── Transparent Pass（透明物体）
   └── Post Processing（后处理）
6. EndFrameRendering
```

### 2.2 Renderer Feature（自定义渲染特性）

```csharp
// 自定义渲染特性：为所有不透明物体添加轮廓描边效果
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class OutlineRendererFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class OutlineSettings
    {
        public Material outlineMaterial;
        public float outlineWidth = 2f;
        public Color outlineColor = Color.white;
        public LayerMask outlineLayer;
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
    }
    
    public OutlineSettings settings = new OutlineSettings();
    private OutlineRenderPass _outlinePass;
    
    // 初始化（每次序列化变化时调用）
    public override void Create()
    {
        _outlinePass = new OutlineRenderPass(settings);
        _outlinePass.renderPassEvent = settings.renderPassEvent;
    }
    
    // 将 Pass 添加到渲染队列
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (settings.outlineMaterial == null) return;
        
        // 只在游戏视图和场景视图中渲染
        if (renderingData.cameraData.cameraType == CameraType.Preview) return;
        
        renderer.EnqueuePass(_outlinePass);
    }
}

// 自定义 Render Pass 实现
public class OutlineRenderPass : ScriptableRenderPass
{
    private OutlineRendererFeature.OutlineSettings _settings;
    private RTHandle _outlineTexture;
    private FilteringSettings _filteringSettings;
    private List<ShaderTagId> _shaderTagIds;
    
    public OutlineRenderPass(OutlineRendererFeature.OutlineSettings settings)
    {
        _settings = settings;
        _filteringSettings = new FilteringSettings(RenderQueueRange.opaque, settings.outlineLayer);
        _shaderTagIds = new List<ShaderTagId>
        {
            new ShaderTagId("UniversalForward"),
            new ShaderTagId("UniversalForwardOnly"),
        };
    }
    
    // 声明临时渲染纹理
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var descriptor = renderingData.cameraData.cameraTargetDescriptor;
        descriptor.depthBufferBits = 0;
        
        RenderingUtils.ReAllocateIfNeeded(
            ref _outlineTexture, 
            descriptor, 
            name: "_OutlineTexture"
        );
    }
    
    // 执行渲染
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get("Outline Pass");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("Outline Pass")))
        {
            // 1. 设置描边材质参数
            _settings.outlineMaterial.SetColor("_OutlineColor", _settings.outlineColor);
            _settings.outlineMaterial.SetFloat("_OutlineWidth", _settings.outlineWidth);
            
            // 2. 渲染描边层的物体到临时纹理
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
            
            var drawSettings = CreateDrawingSettings(_shaderTagIds, ref renderingData, 
                SortingCriteria.CommonOpaque);
            drawSettings.overrideMaterial = _settings.outlineMaterial;
            
            CoreUtils.SetRenderTarget(cmd, _outlineTexture);
            CoreUtils.ClearRenderTarget(cmd, ClearFlag.All, Color.clear);
            
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
            
            context.DrawRenderers(renderingData.cullResults, ref drawSettings, ref _filteringSettings);
            
            // 3. 将描边纹理合并到相机目标
            // ...混合操作
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
    
    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 释放临时纹理
    }
}
```

## 三、自定义后处理效果

### 3.1 Volume 组件扩展

```csharp
// 创建自定义后处理效果：像素化效果
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

// 1. 定义后处理组件
[Serializable, VolumeComponentMenu("Custom/Pixelate")]
public class PixelateEffect : VolumeComponent, IPostProcessComponent
{
    [Tooltip("像素大小（值越大越像素化）")]
    public ClampedIntParameter pixelSize = new ClampedIntParameter(1, 1, 32);
    
    public bool IsActive() => pixelSize.value > 1;
    public bool IsTileCompatible() => false;
}

// 2. 创建对应的 Renderer Feature
public class PixelateRendererFeature : ScriptableRendererFeature
{
    private PixelateRenderPass _pass;
    private Material _material;
    
    public override void Create()
    {
        _material = CoreUtils.CreateEngineMaterial("Hidden/Custom/Pixelate");
        _pass = new PixelateRenderPass(_material);
        _pass.renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData data)
    {
        // 检查后处理组件是否激活
        var stack = VolumeManager.instance.stack;
        var pixelate = stack.GetComponent<PixelateEffect>();
        
        if (pixelate != null && pixelate.IsActive())
        {
            _pass.Setup(pixelate);
            renderer.EnqueuePass(_pass);
        }
    }
}

// 3. 实现渲染 Pass
public class PixelateRenderPass : ScriptableRenderPass
{
    private Material _material;
    private PixelateEffect _pixelate;
    private RTHandle _tempRT;
    
    public PixelateRenderPass(Material material)
    {
        _material = material;
    }
    
    public void Setup(PixelateEffect effect) => _pixelate = effect;
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("Pixelate Post Process");
        
        var cameraData = renderingData.cameraData;
        var source = cameraData.renderer.cameraColorTargetHandle;
        
        int pixelSize = _pixelate.pixelSize.value;
        int width = cameraData.cameraTargetDescriptor.width / pixelSize;
        int height = cameraData.cameraTargetDescriptor.height / pixelSize;
        
        // 降采样到小分辨率
        cmd.GetTemporaryRT(Shader.PropertyToID("_LowResTarget"), width, height, 0, 
            FilterMode.Point, RenderTextureFormat.Default);
        
        // Blit: 源 → 低分辨率（像素化）→ 源
        Blitter.BlitCameraTexture(cmd, source, _tempRT, _material, 0);
        Blitter.BlitCameraTexture(cmd, _tempRT, source);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

## 四、从内置管线迁移到 URP

### 4.1 迁移清单

```
迁移前评估：

Shader 迁移
├── Standard Shader → Lit（URP）
├── 自定义 Shader → 手动改写（最耗时）
│   ├── Lighting 函数调用不同
│   ├── 宏定义不同（UNITY_MATRIX_MVP → 用 TransformObjectToHClip）
│   └── 包含文件不同（URP CoreLibrary）
└── 使用 Edit → Rendering → Materials → Convert 批量转换

渲染特性迁移
├── GrabPass → Renderer Feature（需自行实现）
├── OnRenderImage → Volume/Renderer Feature
├── Camera.RenderWithShader → Renderer Feature
└── CommandBuffer → Renderer Feature/Pass

不支持特性
├── ❌ OnPreRender/OnPostRender（用 RenderPipelineManager 回调替代）
├── ❌ 多Pass Shader（URP 单Pass，用多 Renderer Feature）
└── ❌ 顶点光照 Shader（移除顶点光照模式）
```

### 4.2 URP Shader 迁移示例

```hlsl
// === 旧版内置管线 Shader ===
Shader "Legacy/DiffuseToon"
{
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"        // 旧版包含
            #include "Lighting.cginc"
            
            struct v2f
            {
                float4 pos : SV_POSITION;
                float3 normal : TEXCOORD0;
            };
            
            v2f vert(appdata_base v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex); // 旧版函数
                o.normal = UnityObjectToWorldNormal(v.normal);
                return o;
            }
            
            fixed4 frag(v2f i) : SV_Target
            {
                float3 lightDir = normalize(_WorldSpaceLightPos0.xyz);
                float NdotL = max(0, dot(i.normal, lightDir));
                float toon = step(0.5, NdotL); // 卡通阶梯光照
                return fixed4(toon, toon, toon, 1);
            }
            ENDCG
        }
    }
}

// === 迁移后 URP Shader ===
Shader "Custom/DiffuseToon_URP"
{
    SubShader
    {
        Tags 
        { 
            "RenderType"="Opaque" 
            "RenderPipeline"="UniversalPipeline" // 必须声明
        }
        
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode"="UniversalForward" }
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"     // 新版包含
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 normalWS   : TEXCOORD0;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz); // 新版函数
                OUT.normalWS = TransformObjectToWorldNormal(IN.normalOS);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                Light mainLight = GetMainLight(); // URP 获取主光源
                float NdotL = max(0, dot(normalize(IN.normalWS), mainLight.direction));
                float toon = step(0.5, NdotL);
                return half4(toon * mainLight.color, 1);
            }
            ENDHLSL
        }
    }
}
```

## 五、URP 性能优化

### 5.1 批处理优化

```csharp
// 检查 URP 批处理状态
// Frame Debugger 中查看 SRPBatcher / GPU Instancing / Dynamic Batching

// 确保 SRP Batcher 生效的条件：
// 1. Shader 使用 CBUFFER 包裹 Per-Material 属性
CBUFFER_START(UnityPerMaterial)
    float4 _BaseColor;
    float _Roughness;
    float _Metallic;
CBUFFER_END

// 2. 不同材质使用相同 Shader 变体
// 3. 不使用 MaterialPropertyBlock（会打破 SRP Batcher）
```

### 5.2 移动端 URP 配置建议

```
URP Asset 配置（移动端优化）：

Quality Settings:
├── Anti Aliasing: 2x MSAA（4x 移动端性能差）
├── Render Scale: 0.9（轻微降采样，感知不明显）
└── Max Additional Lights: 4（减少动态光照数量）

Renderer Settings:
├── Depth Priming: 禁用（移动端无益）
├── Copy Depth: 仅需要时开启
├── Copy Color: 仅特效需要时开启
└── Intermediate Texture: Never（减少带宽）

后处理（移动端谨慎使用）：
├── Bloom: 使用 Uber Pass 模式
├── Tonemapping: ACES 开销大，考虑 Neutral
├── SSAO: 移动端通常禁用
└── Depth of Field: 仅高端机型开启
```

## 六、调试与性能分析工具

```csharp
// URP 渲染调试
// 1. Frame Debugger（Window → Analysis → Frame Debugger）
//    查看每个 Draw Call 的具体渲染状态

// 2. Rendering Debugger（Window → Analysis → Rendering Debugger）
//    专为 URP/HDRP 设计，可视化 GBuffer/Light Map/Overdraw

// 3. 自定义 GPU 计时器
public class GPUTimingSystem : MonoBehaviour
{
    private RTHandle _dummyRT;
    
    void OnEnable()
    {
        RenderPipelineManager.beginCameraRendering += OnBeginCamera;
        RenderPipelineManager.endCameraRendering += OnEndCamera;
    }
    
    void OnDisable()
    {
        RenderPipelineManager.beginCameraRendering -= OnBeginCamera;
        RenderPipelineManager.endCameraRendering -= OnEndCamera;
    }
    
    private void OnBeginCamera(ScriptableRenderContext context, Camera camera)
    {
        // 每帧开始时记录时间戳
    }
    
    private void OnEndCamera(ScriptableRenderContext context, Camera camera)
    {
        // 每帧结束时计算耗时
    }
}
```

> 💡 **选型建议**：
> - 手游/独立游戏：**URP**（性能好，社区资源丰富）
> - PC 高画质：**HDRP**（PBR/光线追踪/体积光 全套支持）
> - 自研引擎：**Core RP Library** 从零搭建
>
> 千万不要中途切换渲染管线，这会造成所有 Shader 和后处理效果都要重做，是极高的技术债务。在项目立项阶段就确定渲染管线！
