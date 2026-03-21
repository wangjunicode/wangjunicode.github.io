---
title: "Unity URP渲染管线深度定制：从原理到大厂实践"
description: "深入解析Unity URP（通用渲染管线）的底层架构，掌握Renderer Feature、Pass定制、Shader扩展，以及米哈游/鹰角等一线大厂的URP定制案例"
pubDate: "2025-03-21"
tags: ["URP", "渲染管线", "Renderer Feature", "Shader", "SRP", "Unity"]
---

# Unity URP渲染管线深度定制：从原理到大厂实践

> URP不只是"Built-in的替代品"，它是一个可以深度定制的渲染框架。掌握URP定制，是游戏渲染工程师进阶的必经之路。

---

## 一、URP架构全景

### 1.1 SRP（Scriptable Render Pipeline）基础

Unity的渲染管线是完全可编程的，URP和HDRP都基于SRP框架：

```
SRP框架结构：

RenderPipeline（抽象基类）
    └── UniversalRenderPipeline（URP实现）
        ├── UniversalRenderer（主渲染器）
        │   ├── DepthPrepass
        │   ├── MainLightShadowCasterPass
        │   ├── DrawOpaqueObjectsPass
        │   ├── SkyboxPass
        │   ├── DrawTransparentObjectsPass
        │   ├── PostProcessPass
        │   └── [你的自定义Pass] ← Renderer Feature挂载点
        └── 2DRenderer（2D游戏专用）
```

### 1.2 渲染循环原理

```csharp
// URP每帧渲染流程（简化版）
public class UniversalRenderPipeline : RenderPipeline
{
    protected override void Render(ScriptableRenderContext context, Camera[] cameras)
    {
        // 对每个相机执行渲染
        foreach (var camera in cameras)
        {
            // 1. 剔除（Culling）
            camera.TryGetCullingParameters(out var cullingParameters);
            var cullingResults = context.Cull(ref cullingParameters);
            
            // 2. 设置渲染状态
            context.SetupCameraProperties(camera);
            
            // 3. 执行所有渲染Pass（按顺序）
            foreach (var pass in _activePasses)
            {
                pass.Execute(context, ref renderingData);
            }
            
            // 4. 提交命令
            context.Submit();
        }
    }
}
```

---

## 二、Renderer Feature：自定义渲染的入口

### 2.1 Renderer Feature 基础结构

```csharp
// 自定义Renderer Feature：添加一个描边效果Pass
public class OutlineRendererFeature : ScriptableRendererFeature
{
    // 在Inspector中可配置的参数
    [System.Serializable]
    public class OutlineSettings
    {
        public Material outlineMaterial;
        public Color outlineColor = Color.black;
        [Range(0.001f, 0.01f)] public float outlineWidth = 0.003f;
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
    }
    
    public OutlineSettings settings = new OutlineSettings();
    private OutlinePass _outlinePass;
    
    // 初始化：创建Pass实例
    public override void Create()
    {
        _outlinePass = new OutlinePass(settings);
    }
    
    // 每帧：将Pass加入渲染队列
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // 只在Game视图和Scene视图渲染（不在Preview中渲染）
        if (renderingData.cameraData.cameraType == CameraType.Preview) return;
        
        renderer.EnqueuePass(_outlinePass);
    }
}
```

### 2.2 自定义渲染Pass实现

```csharp
public class OutlinePass : ScriptableRenderPass
{
    private OutlineRendererFeature.OutlineSettings _settings;
    private RTHandle _outlineRT; // 渲染目标
    
    // 过滤设置：只渲染有Outline层的对象
    private FilteringSettings _filteringSettings;
    private ShaderTagId _shaderTagId = new ShaderTagId("OutlinePass");
    
    public OutlinePass(OutlineRendererFeature.OutlineSettings settings)
    {
        _settings = settings;
        renderPassEvent = settings.renderPassEvent;
        
        // 只渲染Outline层的透明对象
        _filteringSettings = new FilteringSettings(
            RenderQueueRange.opaque, 
            LayerMask.GetMask("Outline")
        );
    }
    
    // 分配RenderTexture资源
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var descriptor = renderingData.cameraData.cameraTargetDescriptor;
        descriptor.colorFormat = RenderTextureFormat.ARGB32;
        
        RenderingUtils.ReAllocateIfNeeded(
            ref _outlineRT, 
            descriptor, 
            name: "_OutlineTexture"
        );
    }
    
    // 核心渲染逻辑
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("OutlinePass");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("Outline")))
        {
            // Step 1: 渲染轮廓对象到RT（只写深度或颜色标记）
            cmd.SetRenderTarget(_outlineRT);
            cmd.ClearRenderTarget(true, true, Color.clear);
            
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
            
            var sortingCriteria = renderingData.cameraData.defaultOpaqueSortFlags;
            var drawSettings = CreateDrawingSettings(_shaderTagId, ref renderingData, sortingCriteria);
            drawSettings.overrideMaterial = _settings.outlineMaterial;
            
            context.DrawRenderers(renderingData.cullResults, ref drawSettings, ref _filteringSettings);
            
            // Step 2: 对RT做描边处理（后处理Pass）
            _settings.outlineMaterial.SetColor("_OutlineColor", _settings.outlineColor);
            _settings.outlineMaterial.SetFloat("_OutlineWidth", _settings.outlineWidth);
            
            // Blit到摄像机目标
            Blitter.BlitCameraTexture(cmd, _outlineRT, renderingData.cameraData.renderer.cameraColorTargetHandle);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
    
    // 释放RenderTexture资源
    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 不需要手动释放，ReAllocateIfNeeded会管理
    }
    
    public void Dispose()
    {
        _outlineRT?.Release();
    }
}
```

---

## 三、深度定制案例：卡通渲染实现

### 3.1 卡通渲染架构（仿原神风格）

```
卡通渲染核心技术：
1. 离散化光照（Ramp Texture/Step光照）
2. 描边（Outline Pass 或 法线外扩）
3. 面部特殊阴影（SDF阴影贴图）
4. 高光处理（各向异性/硬边高光）
5. 边缘光（菲涅尔Rim Light）
```

### 3.2 ToonLit Shader完整实现

```hlsl
Shader "Custom/ToonLit"
{
    Properties
    {
        _BaseMap ("Base Texture", 2D) = "white" {}
        _BaseColor ("Base Color", Color) = (1,1,1,1)
        
        // 卡通光照
        _RampMap ("Ramp Map (光照渐变)", 2D) = "white" {}
        _ShadowColor ("Shadow Color", Color) = (0.7, 0.7, 0.9, 1)
        
        // 高光
        _SpecularColor ("Specular Color", Color) = (1,1,1,1)
        _SpecularThreshold ("Specular Threshold", Range(0,1)) = 0.9
        _SpecularSmoothness ("Specular Smoothness", Range(0,0.1)) = 0.01
        
        // 边缘光
        _RimColor ("Rim Light Color", Color) = (0.5, 0.8, 1, 1)
        _RimThreshold ("Rim Threshold", Range(0,1)) = 0.6
        _RimSmoothness ("Rim Smoothness", Range(0,0.1)) = 0.01
        
        // 描边
        [Toggle] _OutlineEnabled ("Enable Outline", Float) = 1
        _OutlineWidth ("Outline Width", Range(0, 0.01)) = 0.003
        _OutlineColor ("Outline Color", Color) = (0,0,0,1)
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        // ===== Pass 1: 描边 Pass（法线外扩方式）=====
        Pass
        {
            Name "Outline"
            Cull Front // 只渲染背面！
            
            HLSLPROGRAM
            #pragma vertex OutlineVert
            #pragma fragment OutlineFrag
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            CBUFFER_START(UnityPerMaterial)
                float _OutlineWidth;
                float4 _OutlineColor;
            CBUFFER_END
            
            struct Attributes { float4 pos : POSITION; float3 normal : NORMAL; };
            struct Varyings { float4 posCS : SV_POSITION; };
            
            Varyings OutlineVert(Attributes input)
            {
                Varyings output;
                // 沿法线方向外扩顶点（在裁剪空间中）
                float4 posCS = TransformObjectToHClip(input.positionOS.xyz);
                float3 normalCS = TransformWorldToHClipDir(
                    TransformObjectToWorldNormal(input.normal));
                
                // 根据距离缩放描边宽度（保持屏幕空间一致）
                float2 outlineOffset = normalize(normalCS.xy) * _OutlineWidth / posCS.w;
                posCS.xy += outlineOffset;
                output.posCS = posCS;
                return output;
            }
            
            float4 OutlineFrag(Varyings input) : SV_Target
            {
                return _OutlineColor;
            }
            ENDHLSL
        }
        
        // ===== Pass 2: 主光照 Pass =====
        Pass
        {
            Name "ToonForward"
            Tags { "LightMode"="UniversalForward" }
            
            HLSLPROGRAM
            #pragma vertex ToonVert
            #pragma fragment ToonFrag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            TEXTURE2D(_BaseMap); SAMPLER(sampler_BaseMap);
            TEXTURE2D(_RampMap); SAMPLER(sampler_RampMap);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float4 _BaseColor;
                float4 _ShadowColor;
                float4 _SpecularColor;
                float _SpecularThreshold;
                float _SpecularSmoothness;
                float4 _RimColor;
                float _RimThreshold;
                float _RimSmoothness;
            CBUFFER_END
            
            struct Attributes
            {
                float4 posOS : POSITION;
                float3 normalOS : NORMAL;
                float2 uv : TEXCOORD0;
            };
            
            struct Varyings
            {
                float4 posCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
                float3 posWS : TEXCOORD2;
            };
            
            Varyings ToonVert(Attributes input)
            {
                Varyings output;
                output.posCS = TransformObjectToHClip(input.posOS.xyz);
                output.posWS = TransformObjectToWorld(input.posOS.xyz);
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.uv = TRANSFORM_TEX(input.uv, _BaseMap);
                return output;
            }
            
            float4 ToonFrag(Varyings input) : SV_Target
            {
                float3 N = normalize(input.normalWS);
                float3 V = normalize(GetCameraPositionWS() - input.posWS);
                
                Light mainLight = GetMainLight(TransformWorldToShadowCoord(input.posWS));
                float3 L = normalize(mainLight.direction);
                float3 H = normalize(V + L);
                
                float4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv) * _BaseColor;
                
                // ===== 1. 卡通漫反射 =====
                float NdotL = dot(N, L) * 0.5 + 0.5; // Half-Lambert
                NdotL *= mainLight.shadowAttenuation;
                
                // 使用Ramp贴图离散化光照（策划可控制色阶分布）
                float3 rampColor = SAMPLE_TEXTURE2D(_RampMap, sampler_RampMap, 
                                                     float2(NdotL, 0.5)).rgb;
                
                // 暗部混色（阴影颜色叠加）
                float shadowFactor = smoothstep(0.45, 0.55, NdotL);
                float3 diffuse = lerp(_ShadowColor.rgb, float3(1,1,1), shadowFactor) * rampColor;
                
                // ===== 2. 硬边高光 =====
                float NdotH = dot(N, H);
                float specularFactor = smoothstep(
                    _SpecularThreshold - _SpecularSmoothness, 
                    _SpecularThreshold + _SpecularSmoothness, 
                    NdotH);
                float3 specular = specularFactor * _SpecularColor.rgb;
                
                // ===== 3. 边缘光（菲涅尔Rim）=====
                float NdotV = dot(N, V);
                float rimFactor = smoothstep(
                    _RimThreshold - _RimSmoothness, 
                    _RimThreshold + _RimSmoothness, 
                    1.0 - NdotV);
                float3 rim = rimFactor * _RimColor.rgb;
                
                // ===== 合并 =====
                float3 finalColor = baseColor.rgb * (diffuse + specular) + rim;
                finalColor *= mainLight.color;
                
                return float4(finalColor, baseColor.a);
            }
            ENDHLSL
        }
    }
}
```

---

## 四、URP深度Buffer访问与SSAO实现

### 4.1 深度Buffer读取

```hlsl
// 在Shader中读取场景深度（用于软粒子、焦散等效果）
TEXTURE2D_X(_CameraDepthTexture);
SAMPLER(sampler_CameraDepthTexture);

float4 frag(Varyings input) : SV_Target
{
    // 读取深度值（0-1范围）
    float depth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, input.screenPos.xy);
    
    // 转换为线性深度（世界空间距离）
    float linearDepth = LinearEyeDepth(depth, _ZBufferParams);
    
    // 软粒子：粒子边缘与场景几何体混合
    float particleDepth = input.screenPos.z / input.screenPos.w; // 粒子自身深度
    float fade = saturate((linearDepth - LinearEyeDepth(particleDepth, _ZBufferParams)) * 2.0);
    
    return float4(color.rgb, color.a * fade);
}
```

### 4.2 自定义SSAO（屏幕空间环境光遮蔽）

```csharp
// SSAO Renderer Feature
public class SSAORendererFeature : ScriptableRendererFeature
{
    public SSAOSettings settings;
    private SSAOPass _ssaoPass;
    private SSAOBlurPass _blurPass;
    private SSAOCompositePass _compositePass;
    
    public override void Create()
    {
        _ssaoPass = new SSAOPass(settings);
        _blurPass = new SSAOBlurPass(settings);
        _compositePass = new SSAOCompositePass(settings);
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // SSAO计算在透明物体渲染前完成
        _ssaoPass.renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
        _blurPass.renderPassEvent = RenderPassEvent.AfterRenderingOpaques + 1;
        _compositePass.renderPassEvent = RenderPassEvent.AfterRenderingOpaques + 2;
        
        renderer.EnqueuePass(_ssaoPass);
        renderer.EnqueuePass(_blurPass);
        renderer.EnqueuePass(_compositePass);
    }
}
```

```hlsl
// SSAO 核心Shader
// 采样半球方向，检查是否被场景遮挡
float4 SSAOFrag(Varyings input) : SV_Target
{
    float2 uv = input.uv;
    
    // 从深度重建世界位置
    float depth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, uv);
    float3 worldPos = ReconstructWorldPos(uv, depth);
    
    // 读取法线
    float3 normal = DecodeNormal(SAMPLE_TEXTURE2D(_CameraGBufferTexture2, sampler_CameraGBufferTexture2, uv));
    
    // 创建TBN矩阵（以法线为Z轴的切线空间）
    float3 randomVec = normalize(SAMPLE_TEXTURE2D(_NoiseTexture, sampler_NoiseTexture, uv * _NoiseScale).xyz * 2.0 - 1.0);
    float3 tangent = normalize(randomVec - normal * dot(randomVec, normal));
    float3 bitangent = cross(normal, tangent);
    float3x3 TBN = float3x3(tangent, bitangent, normal);
    
    // 在法线半球上采样
    float occlusion = 0.0;
    for (int i = 0; i < NUM_SAMPLES; i++)
    {
        // 获取预计算的半球采样方向
        float3 sampleDir = mul(TBN, _Samples[i].xyz);
        float3 samplePos = worldPos + sampleDir * _Radius;
        
        // 投影采样点到屏幕空间
        float4 samplePosCS = mul(UNITY_MATRIX_VP, float4(samplePos, 1.0));
        float2 sampleUV = samplePosCS.xy / samplePosCS.w * 0.5 + 0.5;
        
        // 比较深度：如果场景深度比采样点更近，说明被遮挡
        float sampleDepth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, sampleUV);
        float sampleLinearDepth = LinearEyeDepth(sampleDepth, _ZBufferParams);
        float samplePointDepth = -samplePosCS.z;
        
        // 范围检查（避免远处物体错误遮挡）
        float rangeCheck = smoothstep(0.0, 1.0, _Radius / abs(LinearEyeDepth(depth, _ZBufferParams) - sampleLinearDepth));
        occlusion += (sampleLinearDepth < samplePointDepth ? 1.0 : 0.0) * rangeCheck;
    }
    
    occlusion = 1.0 - (occlusion / NUM_SAMPLES);
    return float4(occlusion, occlusion, occlusion, 1.0);
}
```

---

## 五、大厂URP定制案例分析

### 5.1 米哈游《原神》渲染技术分析

```
原神渲染技术栈（公开资料整理）：

基础架构：
- Unity + 深度定制SRP（接近HDRP特性集）
- 自定义Forward Rendering Path
- 延迟贴花系统（Deferred Decal）

角色渲染：
- PBR + NPR混合材质（每个部位不同着色策略）
- SDF面部阴影（前面有提到）
- 自定义头发高光（各向异性Kajiya-Kay模型）
- 精细的表情系统（驱动BlendShape）

场景渲染：
- GPU Driven植被（GPU Instancing + Compute Shader）
- 实时GI（Lumen类似的探针方案）
- 体积云（Ray Marching）
- 水体渲染（FFT波浪 + 折射）

性能优化：
- 多级LOD系统
- 动态分辨率（移动端关键）
- 自适应质量（根据温度降配）
```

### 5.2 鹰角《明日方舟：终末地》DOTS应用

```csharp
// 鹰角使用Unity ECS处理大规模单位场景
// 参考其技术分享，核心架构如下：

// ECS组件（数据）
public struct EnemyMovementData : IComponentData
{
    public float3 Position;
    public float3 Velocity;
    public float Speed;
    public float3 TargetPosition;
}

public struct EnemyHealthData : IComponentData
{
    public float CurrentHP;
    public float MaxHP;
}

// 移动系统（Burst编译，运行在多线程Job中）
[BurstCompile]
public partial struct EnemyMovementSystem : ISystem
{
    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        float dt = SystemAPI.Time.DeltaTime;
        
        // 并行处理所有敌人的移动（IJobEntity）
        new EnemyMoveJob { DeltaTime = dt }.ScheduleParallel();
    }
}

[BurstCompile]
public partial struct EnemyMoveJob : IJobEntity
{
    public float DeltaTime;
    
    public void Execute(ref EnemyMovementData movement)
    {
        float3 direction = math.normalize(movement.TargetPosition - movement.Position);
        movement.Velocity = direction * movement.Speed;
        movement.Position += movement.Velocity * DeltaTime;
    }
}

// 性能对比：
// 传统MonoBehaviour：10000个单位 → 15fps
// ECS + Burst + Jobs：10000个单位 → 60fps+
```

---

## 六、后处理系统扩展

### 6.1 自定义Volume组件

```csharp
// 创建自定义后处理效果（URP Volume框架）

// 1. 定义Volume组件（参数）
[Serializable, VolumeComponentMenu("Custom/Glitch Effect")]
public class GlitchEffect : VolumeComponent, IPostProcessComponent
{
    [Tooltip("故障效果强度")]
    public ClampedFloatParameter intensity = new ClampedFloatParameter(0f, 0f, 1f);
    
    [Tooltip("故障行高度")]
    public ClampedFloatParameter blockSize = new ClampedFloatParameter(0.05f, 0.01f, 0.2f);
    
    [Tooltip("颜色偏移强度")]
    public ClampedFloatParameter colorShift = new ClampedFloatParameter(0.02f, 0f, 0.1f);
    
    public bool IsActive() => intensity.value > 0f;
    public bool IsTileCompatible() => false;
}

// 2. 创建Renderer Feature来处理这个Volume组件
public class GlitchEffectFeature : ScriptableRendererFeature
{
    private GlitchEffectPass _pass;
    
    public override void Create() => _pass = new GlitchEffectPass();
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // 检查Volume设置是否激活
        var stack = VolumeManager.instance.stack;
        var effect = stack.GetComponent<GlitchEffect>();
        
        if (effect.IsActive())
        {
            _pass.Setup(effect);
            _pass.renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
            renderer.EnqueuePass(_pass);
        }
    }
}

// 3. 实现渲染Pass
public class GlitchEffectPass : ScriptableRenderPass
{
    private GlitchEffect _effect;
    private Material _material;
    private RTHandle _tempRT;
    
    public void Setup(GlitchEffect effect)
    {
        _effect = effect;
        if (_material == null)
            _material = CoreUtils.CreateEngineMaterial("Hidden/GlitchEffect");
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        if (_material == null) return;
        
        var cmd = CommandBufferPool.Get("GlitchEffect");
        
        _material.SetFloat("_Intensity", _effect.intensity.value);
        _material.SetFloat("_BlockSize", _effect.blockSize.value);
        _material.SetFloat("_ColorShift", _effect.colorShift.value);
        _material.SetFloat("_Time", Time.time);
        
        // 将当前帧缓冲通过Glitch Shader处理
        var source = renderingData.cameraData.renderer.cameraColorTargetHandle;
        Blitter.BlitCameraTexture(cmd, source, _tempRT, _material, 0);
        Blitter.BlitCameraTexture(cmd, _tempRT, source);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

---

## 七、URP性能调优

### 7.1 URP渲染统计分析

```
URP关键性能指标：

1. SRP Batcher兼容性（Frame Debugger查看）
   目标：尽可能多的DC被SRP Batcher合并
   
2. Shader变体数量（Edit → Project Settings → Player → Shader Variant Collection）
   问题：变体过多导致加载时间长
   解决：Shader关键字精细控制，使用Multi_compile_local代替multi_compile

3. 渲染目标切换次数（RT Switch）
   每次SetRenderTarget都有开销
   目标：减少RT切换，合并渲染Pass

4. 后处理分辨率（Rendering Scale）
   移动端可以用0.75 Rendering Scale + FSR超采样
   性能提升25%，画质基本无损
```

### 7.2 移动端URP配置最佳实践

```yaml
# URP Asset 移动端推荐配置

Rendering:
  Depth Texture: Enable  # 用于软粒子等效果
  Opaque Texture: Disable  # 除非需要折射，否则关闭（省带宽）
  
Shadows:
  Max Distance: 30  # 根据场景调整，越小越快
  Cascade Count: 2  # PC用4级，移动端用2级
  
Post Processing:
  Grading Mode: LDR  # 移动端用LDR（HDR带宽消耗大）

Quality:
  Anti Aliasing: FXAA  # 移动端首选（MSAA开销更大）
  Render Scale: 0.75   # 高端机用1.0，中端机用0.75
```

---

## 总结

URP定制能力是游戏渲染工程师的核心竞争力：

1. **理解架构**：Renderer Feature → Pass → CommandBuffer的完整链路
2. **动手实践**：从简单的描边效果开始，逐步实现复杂的卡通渲染
3. **性能意识**：每个自定义Pass都有成本，需要Profile验证
4. **学习一线案例**：GDC、SIGGRAPH的技术分享是最好的学习材料

作为技术负责人，你需要：建立项目的渲染技术标准，评估新渲染效果的性能代价，指导渲染工程师在质量和性能之间做出正确取舍。
