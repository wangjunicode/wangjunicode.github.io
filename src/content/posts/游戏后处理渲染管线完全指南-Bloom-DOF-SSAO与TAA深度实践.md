---
title: 游戏后处理渲染管线完全指南：Bloom、DOF、SSAO与TAA深度实践
published: 2026-03-29
description: 系统讲解游戏后处理渲染的完整技术体系，深入剖析Bloom泛光、景深DOF、屏幕空间环境光遮蔽SSAO、时间性抗锯齿TAA等核心后处理效果的实现原理与优化策略，提供Unity URP/HDRP下的完整工程实践代码。
tags: [Unity, 后处理, Bloom, SSAO, TAA, 渲染优化, URP]
category: 渲染技术
draft: false
---

# 游戏后处理渲染管线完全指南：Bloom、DOF、SSAO与TAA深度实践

后处理（Post-Processing）是在 3D 场景渲染完成后，对最终图像进行的一系列屏幕空间图像处理操作。一个精心设计的后处理管线，能以相对较低的美术成本大幅提升画面质感，是当代游戏视觉风格塑造的关键武器。

本文将深入剖析主流后处理技术的数学原理与工程实现，重点聚焦于移动端可用方案的性能权衡。

---

## 一、后处理管线架构

### 1.1 渲染流程中的位置

```
场景渲染（Opaque → Skybox → Transparent）
        ↓
深度/法线缓冲（已可用）
        ↓
HDR Backbuffer（RGBA16F）
        ↓
[后处理Pass 1] SSAO（屏幕空间遮蔽）
        ↓
[后处理Pass 2] DOF（景深）
        ↓
[后处理Pass 3] Bloom（泛光）
        ↓
[后处理Pass 4] TAA（时间性抗锯齿）
        ↓
[后处理Pass 5] Color Grading + Tonemapping
        ↓
[后处理Pass 6] FXAA / 最终抗锯齿
        ↓
最终输出到 Swapchain
```

### 1.2 Unity URP 后处理扩展架构

```csharp
// URP 自定义后处理效果的标准结构
// 1. Volume Component（参数定义）
[Serializable, VolumeComponentMenu("Custom/MyEffect")]
public class MyPostEffect : VolumeComponent, IPostProcessComponent
{
    public ClampedFloatParameter intensity = new ClampedFloatParameter(0f, 0f, 1f);
    public BoolParameter enabled = new BoolParameter(false);
    
    public bool IsActive() => enabled.value && intensity.value > 0f;
    public bool IsTileCompatible() => false; // 是否兼容 Tile-based 渲染
}

// 2. Renderer Feature（注入渲染管线）
public class MyPostEffectFeature : ScriptableRendererFeature
{
    private MyPostEffectPass pass;
    
    public override void Create()
    {
        pass = new MyPostEffectPass();
        pass.renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        var stack = VolumeManager.instance.stack;
        var effect = stack.GetComponent<MyPostEffect>();
        if(effect.IsActive())
            renderer.EnqueuePass(pass);
    }
}

// 3. Render Pass（实际渲染逻辑）
public class MyPostEffectPass : ScriptableRenderPass
{
    private RenderTargetIdentifier source;
    private RenderTargetHandle tempRT;
    private Material material;
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get("MyPostEffect");
        
        // 分配临时 RT
        var descriptor = renderingData.cameraData.cameraTargetDescriptor;
        cmd.GetTemporaryRT(tempRT.id, descriptor, FilterMode.Bilinear);
        
        // 执行后处理 Blit
        Blit(cmd, source, tempRT.Identifier(), material, 0);
        Blit(cmd, tempRT.Identifier(), source);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
        cmd.ReleaseTemporaryRT(tempRT.id);
    }
}
```

---

## 二、Bloom：泛光效果

### 2.1 Bloom 的物理原理

真实相机的镜头中存在轻微的光线散射，导致极亮的光源周围会产生"光晕"。Bloom 模拟这一物理现象。

**Kawase Blur Bloom（卡哇伊模糊）** 是移动端最常用的 Bloom 实现，相比高斯模糊性能更好：

### 2.2 经典 Dual Kawase Bloom 实现

```hlsl
// ==========================================
// Dual Kawase Bloom - 高效移动端 Bloom
// ==========================================

// Pass 0: 提取高亮区域（Prefilter）
half4 PrefilterPass(float2 uv) : SV_Target
{
    half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv);
    
    // 软阈值提取高亮（Quadratic Curve Knee）
    half brightness = max(color.r, max(color.g, color.b));
    half rq = clamp(brightness - _Threshold.y, 0.0, _Threshold.z);
    rq = (_Threshold.w * rq * rq);
    color *= max(rq, brightness - _Threshold.x) / max(brightness, 0.00001);
    
    return color;
}

// Pass 1: Dual Kawase Downsample（降采样）
// 每次降到一半分辨率，采样5个点
half4 DualKawaseDownsample(float2 uv, float2 texelSize, float offset)
{
    half4 sum = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv) * 4.0;
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2(-1, -1) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2(-1,  1) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 1, -1) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 1,  1) * texelSize * offset);
    return sum / 8.0;
}

// Pass 2: Dual Kawase Upsample（升采样）
// 升采样时采样4个偏移点
half4 DualKawaseUpsample(float2 uv, float2 texelSize, float offset)
{
    half4 sum = 0;
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2(-0.5,  0.5) * texelSize * offset * 2);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 0.5,  0.5) * texelSize * offset * 2);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 0.5, -0.5) * texelSize * offset * 2);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2(-0.5, -0.5) * texelSize * offset * 2);
    
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2(-1, 0) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 1, 0) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 0, 1) * texelSize * offset);
    sum += SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv + float2( 0,-1) * texelSize * offset);
    return sum / 8.0;
}

// Pass 3: 最终合并（Combine）
half4 BloomCombinePass(float2 uv) : SV_Target
{
    half4 hdrColor   = SAMPLE_TEXTURE2D(_MainTex,   sampler_MainTex,   uv);
    half4 bloomColor = SAMPLE_TEXTURE2D(_BloomTex, sampler_BloomTex, uv);
    
    // 叠加 Bloom（加法混合，保留 HDR 信息供后续 Tonemapping 处理）
    return hdrColor + bloomColor * _BloomIntensity;
}
```

### 2.3 C# 侧多 Pass 管理

```csharp
public class DualKawaseBloomPass : ScriptableRenderPass
{
    private const int MAX_ITERATIONS = 6;
    private Material bloomMaterial;
    private int[] downSampleRT, upSampleRT;
    private BloomSettings settings;
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("DualKawaseBloom");
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        
        // 计算迭代层数
        int iterations = Mathf.Clamp(settings.iterations, 1, MAX_ITERATIONS);
        
        // Step1: Prefilter
        int width = desc.width / 2, height = desc.height / 2;
        cmd.GetTemporaryRT(downSampleRT[0], width, height, 0, FilterMode.Bilinear, RenderTextureFormat.DefaultHDR);
        Blit(cmd, colorAttachment, downSampleRT[0], bloomMaterial, 0); // Pass 0: Prefilter
        
        // Step2: 逐步降采样
        for(int i = 1; i < iterations; i++)
        {
            width  = Mathf.Max(1, width / 2);
            height = Mathf.Max(1, height / 2);
            cmd.GetTemporaryRT(downSampleRT[i], width, height, 0, FilterMode.Bilinear, RenderTextureFormat.DefaultHDR);
            bloomMaterial.SetVector("_TexelSize", new Vector4(1f/width, 1f/height, width, height));
            bloomMaterial.SetFloat("_Offset", settings.blurRadius);
            Blit(cmd, downSampleRT[i-1], downSampleRT[i], bloomMaterial, 1); // Pass 1: Downsample
        }
        
        // Step3: 逐步升采样
        for(int i = iterations - 2; i >= 0; i--)
        {
            cmd.GetTemporaryRT(upSampleRT[i], /* width at level i */, FilterMode.Bilinear);
            Blit(cmd, downSampleRT[i+1], upSampleRT[i], bloomMaterial, 2); // Pass 2: Upsample
        }
        
        // Step4: 与原图合并
        bloomMaterial.SetTexture("_BloomTex", upSampleRT[0]);
        bloomMaterial.SetFloat("_BloomIntensity", settings.intensity);
        Blit(cmd, colorAttachment, tempRT, bloomMaterial, 3); // Pass 3: Combine
        Blit(cmd, tempRT, colorAttachment);
        
        // 释放临时 RT
        for(int i = 0; i < iterations; i++)
        {
            cmd.ReleaseTemporaryRT(downSampleRT[i]);
            if(i < iterations - 1) cmd.ReleaseTemporaryRT(upSampleRT[i]);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

---

## 三、景深（Depth of Field）

### 3.1 DOF 原理：弥散圆（Circle of Confusion）

景深模拟相机镜头的对焦特性：只有焦平面上的物体清晰，焦平面前后的物体会产生模糊（Bokeh）。

**弥散圆半径（CoC）**：

```
CoC = |f² * (focusDist - d)| / (N * d * (focusDist - f))

其中：
  f           = 焦距（focal length）
  N           = 光圈 F-number
  focusDist   = 对焦距离
  d           = 当前像素的世界深度
```

### 3.2 Bokeh DOF HLSL 实现

```hlsl
// ==========================================
// 散景景深实现（Hexagonal Bokeh）
// ==========================================

// CoC 计算 Pass
half ComputeCoC(float depth, float focusDistance, float focusRange, float maxRadius)
{
    // 将深度转换到线性相机空间
    float linearDepth = LinearEyeDepth(depth, _ZBufferParams);
    
    // 计算 CoC（归一化到 -1 ~ 1，负值=前景，正值=背景）
    float coc = (linearDepth - focusDistance) / focusRange;
    
    return clamp(coc, -1.0, 1.0) * maxRadius;
}

// 六边形 Bokeh 采样（更美观的散景形状）
static const int BOKEH_SAMPLE_COUNT = 22;
static const float2 BOKEH_KERNEL[22] =
{
    // 六边形采样点（三组同心六边形）
    float2( 0.000000,  0.000000),  // 中心
    float2( 1.000000,  0.000000),  // 第一圈
    float2( 0.500000,  0.866025),
    float2(-0.500000,  0.866025),
    float2(-1.000000,  0.000000),
    float2(-0.500000, -0.866025),
    float2( 0.500000, -0.866025),
    float2( 2.000000,  0.000000),  // 第二圈
    float2( 1.000000,  1.732051),
    float2(-1.000000,  1.732051),
    float2(-2.000000,  0.000000),
    float2(-1.000000, -1.732051),
    float2( 1.000000, -1.732051),
    float2( 1.500000,  0.866025),
    float2( 0.000000,  1.732051),
    float2(-1.500000,  0.866025),
    float2(-1.500000, -0.866025),
    float2( 0.000000, -1.732051),
    float2( 1.500000, -0.866025),
    float2( 2.000000,  1.154701),  // 第三圈
    float2(-2.000000,  1.154701),
    float2( 0.000000, -2.309401),
};

half4 BokehDOFPass(float2 uv) : SV_Target
{
    float depth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, uv);
    float coc = ComputeCoC(depth, _FocusDistance, _FocusRange, _MaxBlurRadius);
    float cocAbs = abs(coc);
    
    half4 color = 0;
    float totalWeight = 0;
    
    float2 texelSize = _MainTex_TexelSize.xy;
    
    [unroll(22)]
    for(int i = 0; i < BOKEH_SAMPLE_COUNT; i++)
    {
        float2 offset = BOKEH_KERNEL[i] * cocAbs * texelSize * _BokehScale;
        float2 sampleUV = uv + offset;
        
        half4 sampleColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, sampleUV);
        
        // 采样点的 CoC
        float sampleDepth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, sampleUV);
        float sampleCoc = ComputeCoC(sampleDepth, _FocusDistance, _FocusRange, _MaxBlurRadius);
        
        // 权重：避免前景模糊"渗出"到后景清晰区域
        float weight = 1.0;
        // 如果采样点在焦内（CoC 很小）且当前像素在焦外，降低权重
        if(abs(sampleCoc) < cocAbs * 0.5)
            weight = abs(sampleCoc) / (cocAbs * 0.5 + 0.001);
        
        color += sampleColor * weight;
        totalWeight += weight;
    }
    
    return color / totalWeight;
}
```

### 3.3 两遍景深分离前后景

```csharp
// 前后景分离处理（更准确的景深）
// Pass 1: 只模糊背景（depth > focusDistance）
// Pass 2: 只模糊前景（depth < focusDistance）
// Pass 3: 合并，用 CoC mask 混合

public class SeparatedDOFPass : ScriptableRenderPass
{
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("SeparatedDOF");
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        
        // 半分辨率处理（DOF 对分辨率不敏感，半分辨率节省50%带宽）
        int halfWidth  = desc.width  / 2;
        int halfHeight = desc.height / 2;
        
        // 降采样 + CoC 编码
        int cocRT = Shader.PropertyToID("_COC_RT");
        cmd.GetTemporaryRT(cocRT, halfWidth, halfHeight, 0, FilterMode.Bilinear, RenderTextureFormat.RGHalf);
        Blit(cmd, colorAttachment, cocRT, dofMaterial, 0); // Pass 0: Downsample + CoC
        
        // 背景模糊
        int bgBlurRT = Shader.PropertyToID("_BG_BLUR_RT");
        cmd.GetTemporaryRT(bgBlurRT, halfWidth, halfHeight, 0, FilterMode.Bilinear, RenderTextureFormat.DefaultHDR);
        dofMaterial.SetTexture("_COCTex", cocRT);
        Blit(cmd, colorAttachment, bgBlurRT, dofMaterial, 1); // Pass 1: BG Blur
        
        // 前景模糊
        int fgBlurRT = Shader.PropertyToID("_FG_BLUR_RT");
        cmd.GetTemporaryRT(fgBlurRT, halfWidth, halfHeight, 0, FilterMode.Bilinear, RenderTextureFormat.DefaultHDR);
        Blit(cmd, colorAttachment, fgBlurRT, dofMaterial, 2); // Pass 2: FG Blur
        
        // 合并
        dofMaterial.SetTexture("_BGBlurTex", bgBlurRT);
        dofMaterial.SetTexture("_FGBlurTex", fgBlurRT);
        Blit(cmd, colorAttachment, tempRT, dofMaterial, 3); // Pass 3: Combine
        Blit(cmd, tempRT, colorAttachment);
        
        cmd.ReleaseTemporaryRT(cocRT);
        cmd.ReleaseTemporaryRT(bgBlurRT);
        cmd.ReleaseTemporaryRT(fgBlurRT);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

---

## 四、SSAO：屏幕空间环境光遮蔽

### 4.1 SSAO 原理

**Screen Space Ambient Occlusion（SSAO）** 模拟物体相互遮挡时，环境光无法到达的暗部区域（角落、缝隙等处更暗）。

算法步骤：
1. 在屏幕空间，围绕每个像素的法线半球内随机采样若干点
2. 将采样点变换到相机空间，查询深度缓冲
3. 如果采样点的深度大于深度缓冲中的值（即被遮挡），计入遮蔽
4. 遮蔽率 = 被遮挡采样点数 / 总采样数

### 4.2 SSAO HLSL 完整实现

```hlsl
// ==========================================
// SSAO 实现（含 Blur 降噪）
// ==========================================

// 在半球内均匀分布的采样核（64个点，预计算好）
static const float3 SSAO_KERNEL[64] = { /* 预计算的半球采样点... */ };

// 随机法线纹理（4x4 Tiling，用于随机旋转采样核，降低噪声）
TEXTURE2D(_SSAONoiseTex);
SAMPLER(sampler_SSAONoiseTex);

float SSAO_Pass(float2 uv)
{
    // 获取当前像素的深度和法线（来自 G-Buffer 或 DepthNormals Pass）
    float depth = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, uv);
    float linearDepth = LinearEyeDepth(depth, _ZBufferParams);
    
    // 重建世界/相机空间位置
    float3 positionVS = ReconstructPositionVS(uv, linearDepth);
    
    // 采样法线（来自 _CameraDepthNormalsTexture）
    float3 normalVS = SampleNormalVS(uv);
    
    // 从噪声纹理获取随机旋转向量
    float2 noiseScale = _ScreenSize.xy / 4.0; // 4x4 噪声贴图，Tiling
    float3 randomVec = SAMPLE_TEXTURE2D(_SSAONoiseTex, sampler_SSAONoiseTex, uv * noiseScale).xyz * 2.0 - 1.0;
    
    // 用 Gram-Schmidt 过程构建 TBN 矩阵，将采样核对齐到法线方向
    float3 tangent   = normalize(randomVec - normalVS * dot(randomVec, normalVS));
    float3 bitangent = cross(normalVS, tangent);
    float3x3 TBN = float3x3(tangent, bitangent, normalVS);
    
    // 采样遮蔽
    float occlusion = 0.0;
    
    [unroll(16)]
    for(int i = 0; i < 16; i++) // 移动端用16次，PC端用64次
    {
        // 将采样点转到相机空间
        float3 samplePos = mul(TBN, SSAO_KERNEL[i]);
        samplePos = positionVS + samplePos * _SSAORadius;
        
        // 将采样位置投影到屏幕空间，采样深度
        float4 offset = float4(samplePos, 1.0);
        offset = mul(unity_CameraProjection, offset); // 投影
        offset.xyz /= offset.w;
        offset.xy = offset.xy * 0.5 + 0.5; // NDC → UV
        
        // 采样深度缓冲
        float sampleDepth = LinearEyeDepth(
            SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, offset.xy),
            _ZBufferParams
        );
        
        // 范围检查：避免超出半径的远处物体也计入遮蔽
        float rangeCheck = smoothstep(0.0, 1.0, _SSAORadius / abs(positionVS.z - sampleDepth));
        
        // 如果采样点深度大于实际深度，则被遮蔽
        occlusion += (sampleDepth >= samplePos.z + _SSAOBias ? 1.0 : 0.0) * rangeCheck;
    }
    
    return 1.0 - (occlusion / 16.0);
}

// SSAO Blur（横向 + 纵向分离高斯模糊，保持边缘）
float SSAO_Blur(float2 uv, float2 blurDir)
{
    float result = 0.0;
    float2 texelSize = blurDir / _ScreenSize.xy;
    
    float centerDepth = LinearEyeDepth(
        SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, uv),
        _ZBufferParams
    );
    
    float totalWeight = 0.0;
    
    for(int i = -2; i <= 2; i++)
    {
        float2 sampleUV = uv + texelSize * i;
        float sampleDepth = LinearEyeDepth(
            SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, sampleUV),
            _ZBufferParams
        );
        
        // 深度感知权重：深度差异大的点减少权重（保留遮蔽边界）
        float depthDiff = abs(centerDepth - sampleDepth);
        float weight = exp(-depthDiff * 10.0); // 高斯形式的深度权重
        
        result += SAMPLE_TEXTURE2D(_SSAOTex, sampler_SSAOTex, sampleUV).r * weight;
        totalWeight += weight;
    }
    
    return result / totalWeight;
}
```

### 4.3 GTAO：游戏中的改进版 SSAO

**Ground Truth Ambient Occlusion（GTAO）** 是 SSAO 的改进版，在 Horizon Search 的基础上增加了弯曲法线计算，得到更准确的 AO 和间接光方向，现已广泛用于 AAA 游戏（如 Control、Cyberpunk 2077）：

```hlsl
// GTAO 核心：水平角遍历（Horizon Search）
float GTAO_HorizonSearch(float2 uv, float3 positionVS, float3 normalVS, float2 direction)
{
    float maxHorizon = -1.0; // cos(最大水平角)
    float stepSize = _GTAORadius / _GTAOSteps;
    
    for(int step = 0; step < _GTAOSteps; step++)
    {
        float2 sampleOffset = direction * (step + 1) * stepSize / float2(_ScreenSize.xy);
        float2 sampleUV = uv + sampleOffset;
        
        // 重建采样点的相机空间位置
        float sampleDepth = LinearEyeDepth(
            SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, sampler_CameraDepthTexture, sampleUV),
            _ZBufferParams
        );
        float3 samplePosVS = ReconstructPositionVS(sampleUV, sampleDepth);
        
        // 计算水平角
        float3 horizonDir = normalize(samplePosVS - positionVS);
        float cosHorizon = dot(horizonDir, normalVS);
        
        // 取最大水平角（遮蔽最强的方向）
        maxHorizon = max(maxHorizon, cosHorizon);
    }
    
    // 遮蔽因子 = 1 - sin(水平角) ≈ 1 - sqrt(1 - cos²(水平角))
    return sqrt(max(0.0, 1.0 - maxHorizon * maxHorizon));
}
```

---

## 五、TAA：时间性抗锯齿

### 5.1 为什么需要 TAA

传统抗锯齿（MSAA/FXAA）的局限：
- **MSAA**：无法处理 Shader 内的锯齿（如高光、法线贴图），在延迟渲染下开销极大
- **FXAA**：纯图像处理，会模糊细节，高频信息损失严重

**TAA（Temporal Anti-Aliasing）** 利用时间维度积累多帧信息，实现高质量抗锯齿：
- 每帧对 Jitter 抖动采样点（亚像素偏移）
- 将当前帧与历史帧混合
- 有效利用运动向量（Motion Vectors）处理移动物体

### 5.2 TAA 核心算法

```hlsl
// ==========================================
// TAA 完整实现
// ==========================================

// 当前帧 Jitter 偏移（Halton 序列，更均匀的低差异序列）
float2 HaltonSequence(int index, int baseX, int baseY)
{
    float resultX = 0, resultY = 0;
    float fX = 1.0 / baseX, fY = 1.0 / baseY;
    int i = index;
    while(i > 0) {
        resultX += fX * (i % baseX);
        i /= baseX;
        fX /= baseX;
    }
    i = index;
    while(i > 0) {
        resultY += fY * (i % baseY);
        i /= baseY;
        fY /= baseY;
    }
    return float2(resultX, resultY) - 0.5;
}

// TAA 主 Pass
half4 TAA_Pass(float2 uv) : SV_Target
{
    // 当前帧颜色
    half4 currentColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv);
    
    // 运动向量（物体/相机运动产生的屏幕空间位移）
    float2 motionVector = SAMPLE_TEXTURE2D(_MotionVectorTexture, sampler_MotionVectorTexture, uv).xy;
    
    // 历史帧 UV（当前 UV - 运动向量 = 上一帧对应位置）
    float2 historyUV = uv - motionVector;
    
    // 采样历史帧
    half4 historyColor = SAMPLE_TEXTURE2D(_HistoryTexture, sampler_HistoryTexture, historyUV);
    
    // ============================================
    // 邻域裁剪（Neighborhood Clipping / Clamping）
    // 防止历史帧颜色"鬼影"：将历史帧颜色裁剪到当前帧邻域颜色的范围内
    // ============================================
    
    // 采样 3x3 邻域，计算颜色 AABB（RGB 空间）
    half3 colorMin = 1e10, colorMax = -1e10;
    half3 colorAvg = 0;
    
    [unroll(9)]
    for(int i = 0; i < 9; i++)
    {
        static const float2 offsets[9] = {
            float2(-1,-1), float2(0,-1), float2(1,-1),
            float2(-1, 0), float2(0, 0), float2(1, 0),
            float2(-1, 1), float2(0, 1), float2(1, 1)
        };
        float2 neighborUV = uv + offsets[i] * _MainTex_TexelSize.xy;
        half3 neighborColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, neighborUV).rgb;
        
        // 转换到 YCoCg 颜色空间（更适合做 AABB 裁剪，减少色彩偏差）
        neighborColor = RGBToYCoCg(neighborColor);
        colorMin = min(colorMin, neighborColor);
        colorMax = max(colorMax, neighborColor);
        colorAvg += neighborColor;
    }
    colorAvg /= 9.0;
    
    // 将历史帧颜色裁剪到邻域 AABB 内
    half3 historyYCoCg = RGBToYCoCg(historyColor.rgb);
    historyYCoCg = clamp(historyYCoCg, colorMin, colorMax);
    historyColor.rgb = YCoCgToRGB(historyYCoCg);
    
    // ============================================
    // 混合权重：控制历史帧占比
    // 检测是否是新出现的像素（historyUV 超出屏幕范围）
    // ============================================
    float blendFactor = 0.1; // 当前帧占 10%，历史帧占 90%（越小越稳定，但响应越慢）
    
    // 超出屏幕边界时不使用历史帧
    bool isOutOfBounds = historyUV.x < 0 || historyUV.x > 1 || historyUV.y < 0 || historyUV.y > 1;
    if(isOutOfBounds) blendFactor = 1.0;
    
    // 速度自适应：快速移动时加大当前帧权重，减少拖影
    float velocity = length(motionVector);
    blendFactor = lerp(blendFactor, lerp(blendFactor, 0.5, velocity * 20.0), saturate(velocity * 10.0));
    
    // 最终混合
    half4 result = lerp(historyColor, currentColor, blendFactor);
    return result;
}

// RGB <-> YCoCg 颜色空间转换
half3 RGBToYCoCg(half3 rgb)
{
    half Y  =  0.25 * rgb.r + 0.5 * rgb.g + 0.25 * rgb.b;
    half Co =  0.5  * rgb.r               - 0.5  * rgb.b;
    half Cg = -0.25 * rgb.r + 0.5 * rgb.g - 0.25 * rgb.b;
    return half3(Y, Co, Cg);
}

half3 YCoCgToRGB(half3 yCoCg)
{
    float r = yCoCg.x + yCoCg.y - yCoCg.z;
    float g = yCoCg.x             + yCoCg.z;
    float b = yCoCg.x - yCoCg.y - yCoCg.z;
    return half3(r, g, b);
}
```

### 5.3 Jitter 矩阵注入

```csharp
// 在 C# 侧注入 Jitter 到投影矩阵
public class TAAJitterInjector : MonoBehaviour
{
    private Camera cam;
    private int frameIndex = 0;
    private Matrix4x4 originalProjection;
    
    // Halton(2,3) 序列生成
    float Halton(int index, int base)
    {
        float result = 0f;
        float f = 1f / base;
        int i = index;
        while(i > 0)
        {
            result += f * (i % base);
            i /= base;
            f /= base;
        }
        return result;
    }
    
    void OnPreRender()
    {
        originalProjection = cam.projectionMatrix;
        frameIndex = (frameIndex + 1) % 8; // 8帧序列
        
        float jitterX = (Halton(frameIndex, 2) - 0.5f) / cam.pixelWidth;
        float jitterY = (Halton(frameIndex, 3) - 0.5f) / cam.pixelHeight;
        
        // 注入 Jitter 偏移到投影矩阵
        Matrix4x4 jitteredProjection = originalProjection;
        jitteredProjection[0, 2] += jitterX * 2f;
        jitteredProjection[1, 2] += jitterY * 2f;
        
        cam.projectionMatrix = jitteredProjection;
        Shader.SetGlobalVector("_TAAJitter", new Vector4(jitterX, jitterY, 0, 0));
    }
    
    void OnPostRender()
    {
        // 恢复原始投影矩阵（避免影响其他系统）
        cam.ResetProjectionMatrix();
    }
}
```

---

## 六、Color Grading 与 Tonemapping

### 6.1 ACES Tonemapping

HDR 渲染管线中，场景亮度范围可能从 0 到数千，需要 Tonemapping 压缩到 [0,1]：

```hlsl
// ACES Filmic Tonemapping（电影级别，URP/HDRP 内置方案）
half3 ACESFilm(half3 x)
{
    // ACES 拟合曲线系数
    float a = 2.51f;
    float b = 0.03f;
    float c = 2.43f;
    float d = 0.59f;
    float e = 0.14f;
    return saturate((x * (a * x + b)) / (x * (c * x + d) + e));
}

// Reinhard Tonemapping（简单版）
half3 ReinhardTonemap(half3 hdr)
{
    return hdr / (hdr + 1.0);
}

// Uncharted 2 Tonemapping（神秘海域2方案，过渡自然）
half3 Uncharted2Tonemap(half3 x)
{
    float A = 0.15, B = 0.50, C = 0.10, D = 0.20, E = 0.02, F = 0.30;
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
}
```

### 6.2 LUT Color Grading

```hlsl
// 3D LUT Color Grading
// LUT 是一个 32x32x32 的 3D 纹理
// R/G/B 各作为三个轴的坐标，输出调色后的颜色

TEXTURE3D(_LUTTexture);
SAMPLER(sampler_LUTTexture);

half3 ApplyLUT(half3 color, float lutSize, float lutContribution)
{
    // 将颜色映射到 LUT 坐标（考虑 texel 对齐）
    float3 lutCoord = color * (lutSize - 1) / lutSize + 0.5 / lutSize;
    
    half3 lutColor = SAMPLE_TEXTURE3D(_LUTTexture, sampler_LUTTexture, lutCoord).rgb;
    
    // 混合强度（0=原色，1=完全应用LUT）
    return lerp(color, lutColor, lutContribution);
}
```

---

## 七、性能优化策略

### 7.1 半分辨率后处理

```csharp
// 大多数后处理效果在半分辨率下效果几乎无损，但性能节省75%
public class HalfResolutionPostProcess : ScriptableRenderPass
{
    private int halfResRT;
    
    public override void Configure(CommandBuffer cmd, RenderTextureDescriptor cameraTextureDescriptor)
    {
        // 降采样到半分辨率
        var halfDesc = cameraTextureDescriptor;
        halfDesc.width  /= 2;
        halfDesc.height /= 2;
        halfDesc.depthBufferBits = 0;
        
        cmd.GetTemporaryRT(halfResRT, halfDesc, FilterMode.Bilinear);
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("HalfRes PostProcess");
        
        // 降采样
        Blit(cmd, colorAttachment, halfResRT);
        
        // 在半分辨率RT上做效果
        // DoEffect(cmd, halfResRT, ...)
        
        // 升采样回全分辨率（使用双线性插值，几乎看不出差异）
        Blit(cmd, halfResRT, colorAttachment);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

### 7.2 后处理合并（Pass Merging）

避免多个后处理效果各自读写一遍 RT，合并到单个 Pass：

```hlsl
// 合并 Pass：将 SSAO + Color Grading + Tonemapping 合并到一个 Pass
half4 CombinedPostPass(float2 uv) : SV_Target
{
    half4 hdrColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv);
    
    // 1. 应用 SSAO（已预计算好）
    float ao = SAMPLE_TEXTURE2D(_SSAOTex, sampler_SSAOTex, uv).r;
    hdrColor.rgb *= ao;
    
    // 2. Vignette（暗角）
    float2 vignetteUV = uv * (1.0 - uv.yx);
    float vignette = pow(vignetteUV.x * vignetteUV.y * 15.0, _VignetteIntensity);
    hdrColor.rgb *= vignette;
    
    // 3. Exposure + Tonemapping
    hdrColor.rgb *= _Exposure;
    hdrColor.rgb = ACESFilm(hdrColor.rgb);
    
    // 4. Color Grading（LUT）
    hdrColor.rgb = ApplyLUT(hdrColor.rgb, 32.0, _ColorGradingIntensity);
    
    // 5. Gamma Correction
    hdrColor.rgb = pow(hdrColor.rgb, 1.0 / 2.2);
    
    return hdrColor;
}
```

### 7.3 移动端后处理优先级

| 效果 | 视觉收益 | 性能开销 | 移动端推荐 |
|------|---------|---------|----------|
| Bloom | 高 | 低(Dual Kawase) | ✅ 推荐 |
| Color Grading(LUT) | 高 | 极低 | ✅ 强烈推荐 |
| FXAA | 中 | 低 | ✅ 推荐 |
| Vignette | 低 | 极低 | ✅ 可用 |
| SSAO | 中 | 中 | ⚠️ 低端机禁用 |
| DOF | 中 | 中 | ⚠️ 可选 |
| TAA | 高 | 中 | ⚠️ 中高端 |
| Motion Blur | 低 | 中 | ❌ 慎用 |
| GTAO | 高 | 高 | ❌ PC/主机 |
| PCSS | 高 | 高 | ❌ PC/主机 |

---

## 八、最佳实践总结

1. **优先使用 Volume System 管理后处理参数**：Unity Volume 系统支持区域混合，可实现游戏内不同区域的视觉风格切换（室内/室外、战斗/平和）。

2. **Bloom 阈值比强度更重要**：错误的阈值会让不该发光的物体泛光，破坏视觉风格。建议从高阈值（0.9+）开始调整。

3. **TAA 需要所有运动物体提交 Motion Vector**：蒙皮动画、粒子系统等需要正确的 Motion Vector Pass，否则会产生鬼影。

4. **SSAO 采样噪声用 Temporal 降噪**：与 TAA 结合使用，每帧使用不同的随机旋转，利用 TAA 的时间积累消除噪点，可以用 8 次采样达到 64 次采样的质量。

5. **HDR 管线贯穿始终**：后处理必须在 HDR 色彩空间中进行，最后才做 Tonemapping + Gamma Correction，否则 Bloom 等效果会出现颜色饱和度偏差。

6. **后处理 Profile 要做质量分档**：根据设备性能级别，动态启用/禁用各效果，并调整分辨率和采样数。一套好的质量分档系统是移动端后处理的核心工程投入。

7. **Blit 操作尽量减少 RT 切换**：每次 RT 切换在移动端 TBDR GPU 上都有 Tile Flush 的代价，尽可能合并后处理 Pass。

---

> **作者注**：后处理是"投入产出比最高"的视觉提升手段。一套精心设计的后处理管线，可以让一个技术中等的场景呈现出大厂品质的视觉感受。但也要谨记：过度的后处理（尤其是滥用 Bloom）往往会造成视觉疲劳，克制而精准的使用才是关键。
