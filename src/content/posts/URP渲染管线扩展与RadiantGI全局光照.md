---
title: 渲染管线扩展 —— URP 自定义 Renderer Feature
published: 2024-01-01
description: "渲染管线扩展 —— URP 自定义 Renderer Feature - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 渲染管线
draft: false
encryptedKey: henhaoji123
---

# 渲染管线扩展 —— URP 自定义 Renderer Feature

## 1. 系统概述

本项目基于 Unity **Universal Render Pipeline（URP）**，并通过第三方插件和自定义 `ScriptableRendererFeature` 对渲染管线进行扩展，主要包括：
- **RadiantGI**：基于光线投射的实时全局光照（GI），支持间接光/近场遮蔽/RSM（反射阴影贴图）
- **AraTrail**：高性能拖尾效果
- **AllIn1SpriteShader**：UI/2D 精灵着色器集合
- **Animancer**：动画系统扩展

本章重点解析 RadiantGI 的渲染管线集成，帮助新人理解 URP RenderFeature 的扩展机制。

---

## 2. URP RenderFeature 基础原理

```
UniversalRenderPipeline
    └── UniversalRenderer（主渲染器）
            ├── 内置渲染阶段（Depth/Opaque/Transparent/PostProcess等）
            └── ScriptableRendererFeature（用户自定义扩展点）← 这里扩展
                    └── ScriptableRenderPass（具体渲染Pass实现）
```

**关键生命周期：**
1. `Create()` —— 渲染器初始化时调用，分配资源、创建 Pass 实例
2. `AddRenderPasses(renderer, cameraData)` —— 每帧每个摄像机渲染前调用，向渲染器注入 Pass
3. `ScriptableRenderPass.Execute(context, renderingData)` —— Pass 实际执行渲染命令

---

## 3. RadiantGI 核心实现

### 3.1 VolumeComponent 参数配置

```csharp
// 位置：Assets/Plugins/RadiantGI/Runtime/Scripts/RadiantGlobalIllumination.cs
// 作为 URP Volume 组件，在相机 Volume Profile 中配置
[ExecuteInEditMode, VolumeComponentMenu("Kronnect/Radiant Global Illumination")]
public class RadiantGlobalIllumination : VolumeComponent, IPostProcessComponent
{
    // 间接光照强度（0=关闭 GI，1=全强度）
    public FloatParameter indirectIntensity = new FloatParameter(0);
    
    // 距离衰减（减少远处间接光影响，提升性能）
    public ClampedFloatParameter indirectDistanceAttenuation = 
        new ClampedFloatParameter(0, 0, 1);
    
    // 间接光源最大亮度限制（防止光照溢出）
    public FloatParameter indirectMaxSourceBrightness = new FloatParameter(8);
    
    // 法线贴图影响程度（法线贴图如何影响间接光接收）
    public ClampedFloatParameter normalMapInfluence = 
        new ClampedFloatParameter(1f, 0, 1);
    
    // 开启多次光线弹射（光照更真实，但性能开销翻倍）
    public BoolParameter rayBounce = new BoolParameter(false);
    
    // 近场遮蔽强度（接触阴影，使相邻物体更有立体感）
    public FloatParameter nearFieldObscurance = new FloatParameter(0);
    
    // 近场遮蔽扩散半径
    public ClampedFloatParameter nearFieldObscuranceSpread = 
        new ClampedFloatParameter(0.2f, 0.01f, 1f);
    
    // 有机光照（注入程序化光变异，让场景更自然）
    public ClampedFloatParameter organicLight = new ClampedFloatParameter(0, 0, 1);
    
    // IPostProcessComponent 接口：告诉 URP 何时激活此后处理
    public bool IsActive() => indirectIntensity.value > 0;
    public bool IsTileCompatible() => false;
}
```

### 3.2 RenderFeature 实现

```csharp
// 位置：Assets/Plugins/RadiantGI/Runtime/Scripts/RadiantRenderFeature.cs
public class RadiantRenderFeature : ScriptableRendererFeature
{
    // 渲染路径支持：Forward / Deferred / Both
    public enum RenderingPath { Forward, Deferred, Both }
    
    // Shader Property ID 缓存（避免每帧 string 查找，性能关键）
    static class ShaderParams
    {
        public static int MainTex = Shader.PropertyToID("_MainTex");
        public static int DownscaledColorAndDepthRT = 
            Shader.PropertyToID("_DownscaledColorAndDepthRT");
        public static int ResolveRT = Shader.PropertyToID("_ResolveRT");
        // GBuffer（延迟渲染用）
        public static int CameraGBuffer0 = Shader.PropertyToID("_GBuffer0");
        public static int CameraGBuffer1 = Shader.PropertyToID("_GBuffer1");
        // 运动向量（时序抗锯齿TAA用）
        public static int MotionVectorTexture = Shader.PropertyToID("_MotionVectorTexture");
        // 间接光照参数（传入 Shader 的向量，打包多个参数减少 Draw Call 开销）
        public static int IndirectData = Shader.PropertyToID("_IndirectData");
        // ...
    }
    
    // Pass 枚举（对应 Shader 的多个 Pass）
    enum Pass
    {
        CopyExact,       // 精确复制RT
        Raycast,         // 光线投射（GI核心计算）
        BlurHorizontal,  // 水平模糊（降噪）
        BlurVertical,    // 垂直模糊
        Upscale,         // 上采样（从1/4或1/2分辨率恢复全分辨率）
        TemporalAccum,   // 时序累积（TAA，利用前几帧结果降噪）
        Compose,         // 合成（将GI叠加到主RT）
        RSM,             // Reflective Shadow Map（用阴影贴图计算间接光）
        NFO,             // Near Field Obscurance（近场遮蔽）
        NFOBlur,         // 近场遮蔽模糊
        // ...
    }
    
    // 初始化：创建材质和RT句柄
    public override void Create()
    {
        if (mat == null)
        {
            mat = CoreUtils.CreateEngineMaterial(Resources.Load<Shader>(
                "Shaders/RadiantGI"));
        }
        pass = new RadiantRenderPass(mat);
    }
    
    // 每帧注入Pass到渲染器
    public override void AddRenderPasses(ScriptableRenderer renderer, 
        ref RenderingData renderingData)
    {
        // 只对游戏摄像机和场景摄像机生效
        var cameraType = renderingData.cameraData.camera.cameraType;
        if (cameraType != CameraType.Game && cameraType != CameraType.SceneView)
            return;
        
        // 检查 Volume 是否激活
        var gi = VolumeManager.instance.stack.GetComponent<RadiantGlobalIllumination>();
        if (gi == null || !gi.IsActive()) return;
        
        // 注入自定义 Pass（在 PostProcess 之后执行）
        renderer.EnqueuePass(pass);
    }
}
```

### 3.3 时序累积抗锯齿（Temporal Accumulation）

RadiantGI 使用时序累积来降低 GI 噪声：

```
当前帧 GI（有噪声）
    +
上一帧 GI 累积缓冲（_PrevResolve）
    ↓
历史混合（0.1 * 当前帧 + 0.9 * 历史）
    ↓
输出更平滑的 GI（利用多帧信息降噪）
    ↓
存储到 _TempAcum 作为下一帧的历史
```

**注意：** 时序累积在摄像机快速移动时会产生"鬼影"（ghosting），通过运动向量检测和历史权重调整来抑制。

---

## 4. 降分辨率 GI 策略

全分辨率计算 GI 太贵，RadiantGI 使用降分辨率策略：

```
原始分辨率 (1920x1080)
    ↓ 降采样
1/2分辨率 (_Downscaled1RT)
    ↓ 再降采样
1/4分辨率 (_Downscaled2RT)
    ↓ 光线投射计算（在低分辨率下）
1/4分辨率 GI 结果
    ↓ 双边上采样（边缘对齐）
1/2分辨率
    ↓ 再次上采样
全分辨率合成输出
```

**双边上采样**：普通 bilinear 上采样会模糊边缘，双边上采样使用深度/法线信息保护边缘锐度，避免 GI 溢到几何体外。

---

## 5. RSM（Reflective Shadow Map）

```
主光源渲染阴影贴图时，同时记录：
- 位置（遮挡物世界空间位置）
- 法线（遮挡物表面法线）
- 颜色（遮挡物反射颜色）

→ 用这些信息在实时计算中模拟间接光
→ 比光线追踪快得多，效果接近
→ 适合移动端性能预算
```

---

## 6. 项目使用建议

| 场景类型 | 推荐配置 | 说明 |
|---------|---------|------|
| 室内场景 | indirectIntensity=0.6, rayBounce=true | 间接光对室内影响大，可以开双弹射 |
| 室外场景 | indirectIntensity=0.3, rayBounce=false | 室外直射光强，单弹射够用 |
| 移动端 | indirectIntensity=0.2, 降低分辨率比例 | 性能优先，大幅降低分辨率 |
| 过场动画 | indirectIntensity=1.0, nearFieldObscurance=0.5 | 画质优先，全功能开启 |

---

## 7. 常见问题与最佳实践

**Q: GI 开启后帧率骤降？**  
A: 先检查降分辨率比例（建议不低于 1/4），关闭 rayBounce，降低 nearFieldObscurance 精度。在 Profile 工具中查看 RadiantGI Pass 的 GPU 耗时。

**Q: GI 在摄像机快速移动时出现鬼影？**  
A: 这是时序累积的正常副作用。可以降低历史混合权重（0.9 → 0.7），或在摄像机移动速度超过阈值时清空累积缓冲。

**Q: 延迟渲染（Deferred）下 GI 效果更好？**  
A: 是的，延迟渲染提供 GBuffer（含法线、反照率等），GI 计算更精确。Forward 渲染只能通过深度重建法线，信息量有限。

**Q: 如何让某些物体不参与 GI 计算？**  
A: 通过 Renderer Layer Mask 过滤，或在 Shader 中添加 `#pragma shader_feature` 宏关闭 GI 采样。
