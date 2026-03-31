---
title: Unity PostProcessing后处理：自定义特效实现
published: 2026-03-31
description: 深度解析Unity URP中自定义后处理特效的完整实现，包括ScriptableRendererFeature创建自定义Pass、基于Render Feature的像素化效果、扫描线/老电视效果、屏幕空间UI血迹/受伤特效、自定义Bloom增强、VignettePulse心跳效果，以及Volume Profile的Runtime动态控制。
tags: [Unity, 后处理, Post Processing, URP, Shader]
category: 渲染与特效
draft: false
---

## 一、自定义 URP 后处理 Render Feature

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using System;

/// <summary>
/// 扫描线/老电视后处理效果（ScriptableRendererFeature）
/// </summary>
public class ScanlineRenderFeature : ScriptableRendererFeature
{
    [Serializable]
    public class Settings
    {
        public RenderPassEvent PassEvent = RenderPassEvent.AfterRenderingPostProcessing;
        [Range(0, 1)] public float Intensity = 0.3f;
        [Range(50, 300)] public float ScanlineCount = 150f;
        [Range(0, 1)] public float NoiseIntensity = 0.05f;
        public bool EnableVignette = true;
    }

    public Settings settings = new Settings();
    private ScanlinePass scanlinePass;

    public override void Create()
    {
        scanlinePass = new ScanlinePass("Scanline Effect", settings);
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData data)
    {
        // 编辑器/构建 都启用
        scanlinePass.renderPassEvent = settings.PassEvent;
        renderer.EnqueuePass(scanlinePass);
    }
}

/// <summary>
/// 扫描线 Pass 实现
/// </summary>
public class ScanlinePass : ScriptableRenderPass
{
    private Material material;
    private ScanlineRenderFeature.Settings settings;
    private RenderTextureDescriptor descriptor;
    private RTHandle tempHandle;
    private static readonly int IntensityProp = Shader.PropertyToID("_Intensity");
    private static readonly int ScanlineCountProp = Shader.PropertyToID("_ScanlineCount");
    private static readonly int NoiseProp = Shader.PropertyToID("_NoiseIntensity");
    private static readonly int TimeProp = Shader.PropertyToID("_Time");

    public ScanlinePass(string name, ScanlineRenderFeature.Settings settings)
    {
        profilingSampler = new ProfilingSampler(name);
        this.settings = settings;
        
        // 加载 Shader
        var shader = Shader.Find("Hidden/Custom/Scanline");
        if (shader != null) material = new Material(shader);
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        descriptor = renderingData.cameraData.cameraTargetDescriptor;
        descriptor.depthBufferBits = 0;
        RenderingUtils.ReAllocateIfNeeded(ref tempHandle, descriptor, name: "_TempTex");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        if (material == null) return;
        
        var cameraData = renderingData.cameraData;
        if (cameraData.isSceneViewCamera) return; // 编辑器Scene视图不应用
        
        var cmd = CommandBufferPool.Get("Scanline Effect");
        
        using (new ProfilingScope(cmd, profilingSampler))
        {
            // 更新材质参数
            material.SetFloat(IntensityProp, settings.Intensity);
            material.SetFloat(ScanlineCountProp, settings.ScanlineCount);
            material.SetFloat(NoiseProp, settings.NoiseIntensity);
            material.SetFloat(TimeProp, Time.time);
            
            // 获取当前颜色目标
            var source = renderingData.cameraData.renderer.cameraColorTargetHandle;
            
            // Blit：source → temp → source（双缓冲）
            Blitter.BlitCameraTexture(cmd, source, tempHandle, material, 0);
            Blitter.BlitCameraTexture(cmd, tempHandle, source);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        RTHandles.Release(tempHandle);
        tempHandle = null;
    }
}
```

---

## 二、扫描线 Shader

```hlsl
Shader "Hidden/Custom/Scanline"
{
    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }
        
        Pass
        {
            Name "Scanline"
            ZTest Always ZWrite Off Cull Off
            
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"
            
            float _Intensity;
            float _ScanlineCount;
            float _NoiseIntensity;
            float _Time;
            
            // 伪随机噪声
            float random(float2 uv)
            {
                return frac(sin(dot(uv, float2(12.9898, 78.233))) * 43758.5453);
            }
            
            float4 Frag(Varyings input) : SV_Target
            {
                float2 uv = input.texcoord;
                float4 color = SAMPLE_TEXTURE2D_X(_BlitTexture, sampler_LinearClamp, uv);
                
                // 扫描线（水平条纹）
                float scanline = sin(uv.y * _ScanlineCount * 3.14159) * 0.5 + 0.5;
                scanline = lerp(1.0, scanline, _Intensity * 0.5);
                color.rgb *= scanline;
                
                // 滚动扫描线
                float scanlineMove = frac(uv.y - _Time * 0.1);
                float movingLine = step(0.99, scanlineMove);
                color.rgb = lerp(color.rgb, float3(0.8, 0.8, 0.8), movingLine * _Intensity * 0.3);
                
                // 噪声扰动
                float noise = random(uv + float2(_Time * 0.01, 0));
                color.rgb = lerp(color.rgb, color.rgb + noise - 0.5, _NoiseIntensity);
                
                // 边缘暗角（Vignette）
                float2 vigUV = uv * 2.0 - 1.0;
                float vignette = 1.0 - dot(vigUV, vigUV) * 0.3;
                color.rgb *= vignette;
                
                return color;
            }
            ENDHLSL
        }
    }
}
```

---

## 三、Runtime 动态控制 Volume

```csharp
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 运行时动态控制后处理参数（受伤/死亡效果）
/// </summary>
public class PostProcessController : MonoBehaviour
{
    private Volume globalVolume;
    private Vignette vignette;
    private ColorAdjustments colorAdj;
    private ChromaticAberration chromatic;
    private LensDistortion lensDistortion;

    void Start()
    {
        globalVolume = FindObjectOfType<Volume>();
        
        if (globalVolume != null)
        {
            globalVolume.profile.TryGet(out vignette);
            globalVolume.profile.TryGet(out colorAdj);
            globalVolume.profile.TryGet(out chromatic);
            globalVolume.profile.TryGet(out lensDistortion);
        }
    }

    /// <summary>
    /// 受伤效果（短暂红色屏幕效果）
    /// </summary>
    public void PlayHitEffect(float intensity = 1f)
    {
        StopAllCoroutines();
        StartCoroutine(HitEffectCoroutine(intensity));
    }

    System.Collections.IEnumerator HitEffectCoroutine(float intensity)
    {
        float duration = 0.3f;
        float elapsed = 0;
        
        while (elapsed < duration)
        {
            float t = elapsed / duration;
            float effectStrength = Mathf.Lerp(intensity, 0, t * t); // 快速衰减
            
            // 红色晕圈
            if (vignette != null)
            {
                vignette.color.Override(Color.Lerp(Color.black, Color.red, effectStrength));
                vignette.intensity.Override(0.3f + effectStrength * 0.4f);
            }
            
            // 色差（受到重击时）
            if (chromatic != null && intensity > 0.5f)
                chromatic.intensity.Override(effectStrength * 0.5f);
            
            elapsed += Time.deltaTime;
            yield return null;
        }
        
        // 恢复
        if (vignette != null)
        {
            vignette.color.Override(Color.black);
            vignette.intensity.Override(0.3f);
        }
        if (chromatic != null) chromatic.intensity.Override(0f);
    }

    /// <summary>
    /// 低血量效果（持续心跳暗角）
    /// </summary>
    public void SetLowHealthEffect(float healthPercent)
    {
        if (vignette == null) return;
        
        if (healthPercent < 0.3f)
        {
            float intensity = (0.3f - healthPercent) / 0.3f; // 0~1
            float pulse = Mathf.Sin(Time.time * 2f) * 0.1f + 0.1f; // 心跳节奏
            vignette.intensity.Override(0.3f + intensity * 0.4f + pulse * intensity);
            
            if (colorAdj != null)
                colorAdj.saturation.Override(-30f * intensity); // 低饱和度
        }
        else
        {
            vignette.intensity.Override(0.3f);
            if (colorAdj != null) colorAdj.saturation.Override(0f);
        }
    }
}
```

---

## 四、常用后处理参数速查

| 效果 | 参数 | 典型值 |
|------|------|--------|
| 受伤红晕 | Vignette Color=Red, Intensity=0.6 | 短暂0.3s |
| 死亡效果 | Saturation=-100, Contrast=+30 | 灰度画面 |
| 子弹时间 | Chromatic Aberration 0.3, Motion Blur | 慢动作感 |
| 剧情高光 | Bloom Intensity 3.0, Vignette | 电影感 |
| 水下效果 | LensDistortion + Color Tint=蓝绿 | 折射感 |
| 闪光弹 | WhiteBalance Temp=-100 + Exposure高 | 致盲感 |
