---
title: Unity Shader Graph深度实践：视差贴图、法线混合与PBR材质节点图完全指南
published: 2026-04-23
description: 深入剖析Unity Shader Graph的核心节点体系，从视差贴图（Parallax Occlusion Mapping）、法线贴图混合到完整PBR材质图的构建，掌握无代码可视化着色器开发的工业级技巧。
tags: [Unity, Shader Graph, PBR, 视差贴图, 法线贴图, 渲染]
category: 渲染技术
draft: false
---

# Unity Shader Graph深度实践：视差贴图、法线混合与PBR材质节点图完全指南

## 一、Shader Graph核心架构与节点体系

### 1.1 Shader Graph工作流概述

Unity Shader Graph 是 URP/HDRP 管线下的可视化着色器编辑系统，其背后的编译链将节点图翻译为 HLSL 代码，最终编译成 GPU 可执行的 Shader Program。

```
[节点图 .shadergraph] 
     ↓  ShaderGraphImporter
[生成的 HLSL 代码]
     ↓  Shader Compiler
[平台 Shader Variant（SPIRV/MSL/DXBC）]
     ↓  Material Property Block
[Runtime GPU 执行]
```

理解这套编译链对性能优化至关重要：节点越多 → 生成指令越多 → GPU ALU 压力越大。

### 1.2 关键数据类型与精度

Shader Graph 中每条边（连线）都携带精度信息：

| 精度类型 | HLSL 对应 | 移动端成本 | 适用场景 |
|---------|-----------|-----------|---------|
| `half` (16位) | `half` / `mediump` | 低 | 颜色、法线、非高精度坐标 |
| `float` (32位) | `float` / `highp` | 高 | 世界坐标、深度、精确UV |
| `int` | `int` | 中 | 索引、计数 |

**最佳实践**：在 Graph Settings 中将 Precision 设为 `Half`，对坐标计算节点局部升级为 `Float`，可节省 30%~50% 移动端 GPU 寄存器压力。

### 1.3 坐标空间变换节点

```
Transform Node 配置路径：
  Object Space → World Space（顶点位移、描边）
  World Space → View Space（深度效果）
  Tangent Space → World Space（法线贴图解码）
  Screen Space（UV 屏幕采样）
```

---

## 二、视差贴图（Parallax Occlusion Mapping）完整实现

### 2.1 视差效果原理

普通法线贴图只影响光照计算，不改变实际 UV 采样位置。视差贴图通过沿视线方向偏移 UV，模拟表面的真实凹凸深度：

```
// 视差公式（基础版 Parallax Mapping）
float height = heightMap.Sample(UV);
float2 parallaxOffset = viewDirTS.xy / viewDirTS.z * height * _ParallaxScale;
float2 newUV = UV - parallaxOffset;
```

**POM（Parallax Occlusion Mapping）** 则通过光线步进（Ray Marching）找到精确交点，效果更真实但代价更高。

### 2.2 Shader Graph节点图：基础视差贴图

```
[UV] ──────────────────────────────────────────→ [Sample Texture 2D: Albedo]
                                                          ↓
[UV] → [Sample Texture 2D: HeightMap] → [R通道]          ↓
              ↓                                    [Base Color] → Fragment
[View Direction (Tangent)] → [Normalize]
              ↓
        [XY Components] ÷ [Z Component] → [Multiply: _ParallaxScale]
              ↓
        [Subtract from UV] → [修正后UV] ─────────→ [Sample Texture 2D: Albedo]
```

对应关键节点配置：
- `View Direction` 节点：Space 设为 **Tangent**
- `Normalize` → `Split` 取 XY 分量
- 用 `Divide` 做透视矫正：`xy / z`

### 2.3 Shader Graph节点图：POM（光线步进版）

POM 需要在 Custom Function 节点中实现循环，因为 Shader Graph 本身不支持 for 循环节点：

```hlsl
// POM_CustomFunction.hlsl
void ParallaxOcclusionMapping_float(
    float2 UV, 
    float3 ViewDirTS, 
    UnityTexture2D HeightMap, 
    UnitySamplerState Sampler,
    float ParallaxScale, 
    int NumSteps,
    out float2 OutUV,
    out float OutShadow)
{
    float numLayers = (float)NumSteps;
    float layerDepth = 1.0 / numLayers;
    float currentLayerDepth = 0.0;
    
    float2 deltaUV = (ViewDirTS.xy / ViewDirTS.z) * ParallaxScale / numLayers;
    float2 currentUV = UV;
    
    float heightFromTexture = SAMPLE_TEXTURE2D(HeightMap, Sampler, currentUV).r;
    
    // 步进循环
    [loop]
    for (int i = 0; i < NumSteps; i++)
    {
        if (currentLayerDepth >= heightFromTexture)
            break;
        currentUV -= deltaUV;
        heightFromTexture = SAMPLE_TEXTURE2D(HeightMap, Sampler, currentUV).r;
        currentLayerDepth += layerDepth;
    }
    
    // 线性插值细化（减少台阶感）
    float2 prevUV = currentUV + deltaUV;
    float afterDepth  = heightFromTexture - currentLayerDepth;
    float beforeDepth = SAMPLE_TEXTURE2D(HeightMap, Sampler, prevUV).r 
                        - currentLayerDepth + layerDepth;
    float weight = afterDepth / (afterDepth - beforeDepth);
    OutUV = lerp(currentUV, prevUV, weight);
    
    // 自阴影计算（POM Self-Shadow）
    float3 lightDirTS = normalize(ViewDirTS); // 实际应传入光照方向
    OutShadow = 1.0;
}
```

在 Shader Graph 中添加 **Custom Function** 节点并引用此文件：
- Source：File
- File：`POM_CustomFunction.hlsl`
- Function Name：`ParallaxOcclusionMapping`

### 2.4 性能分级方案

| 方案 | 步进次数 | 适用平台 | 视觉质量 |
|-----|---------|---------|---------|
| Parallax Mapping | 1步（线性） | 移动端高配 | ★★☆ |
| Steep PM | 8~16步 | PC/主机 | ★★★ |
| POM（带插值） | 16~32步 | PC/主机高配 | ★★★★ |
| Relief Mapping | 32步+二分 | PC旗舰 | ★★★★★ |

---

## 三、法线贴图的叠加与混合

### 3.1 法线混合的数学本质

法线贴图存储的是切线空间下的扰动向量（范围 [0,1] 映射到 [-1,1]），直接线性叠加（Linear Blend）会导致法线不再单位化，产生错误光照。

正确的方法有两种：

#### 方法一：Reoriented Normal Mapping（RNM）

适合两层法线方向差异较大的场景（如石块裂缝叠加苔藓细节）：

```hlsl
// RNM混合（保持两层法线的几何意义）
float3 BlendNormals_RNM(float3 n1, float3 n2)
{
    // 将n1从切线空间视为旋转框架，用它重新定向n2
    n1 = n1 * float3(2, 2, 2) - float3(1, 1, 1); // decode
    n2 = n2 * float3(2, 2, 2) - float3(1, 1, 1);
    
    float3 t = n1 + float3(0, 0, 1);
    float3 u = n2 * float3(-1, -1, 1);
    return normalize(t * dot(t, u) - u * t.z);
}
```

#### 方法二：Whiteout混合

适合细节法线与主法线方向接近的场景（如皮肤毛孔叠加大褶皱）：

```hlsl
float3 BlendNormals_Whiteout(float3 n1, float3 n2)
{
    n1 = n1 * float3(2, 2, 2) - float3(1, 1, 1);
    n2 = n2 * float3(2, 2, 2) - float3(1, 1, 1);
    return normalize(float3(n1.xy + n2.xy, n1.z * n2.z));
}
```

### 3.2 Shader Graph法线混合节点图

Shader Graph 内置了 `Normal Blend` 节点，模式选择：
- **Default**：Whiteout 混合
- **Reoriented**：RNM 混合

```
[Sample Texture 2D: DetailNormal] ──(RGBA)──→ [Normal Unpack] ─→ [Normal Blend B]
                                                                         ↓
[Sample Texture 2D: BaseNormal] ──(RGBA)──→ [Normal Unpack] ──→ [Normal Blend A] → [Normal (Fragment)]
                                                        ↑
                                              Mode: Reoriented
```

### 3.3 多层法线：地形着色器实战

地形材质通常需要混合 4 层不同材质的法线，结合 splat map 权重：

```hlsl
// 4层法线加权混合（基于 splatmap 控制权重）
float3 BlendNormalLayers(
    float3 n0, float3 n1, float3 n2, float3 n3,
    float4 weights)
{
    // 先Whiteout混合相邻层
    float3 blend01 = BlendNormals_Whiteout(n0, n1);
    float3 blend23 = BlendNormals_Whiteout(n2, n3);
    
    // 按splat权重线性混合（注意要重新normalize）
    float3 result = blend01 * (weights.r + weights.g) 
                  + blend23 * (weights.b + weights.a);
    return normalize(result);
}
```

---

## 四、完整PBR材质节点图构建

### 4.1 PBR材质的五大输入通道

| 通道 | 范围 | 物理意义 |
|-----|-----|---------|
| Albedo（基础色） | [0,1] RGB | 漫反射颜色，无高光信息 |
| Metallic（金属度） | [0,1] | 0=非金属，1=纯金属 |
| Roughness（粗糙度） | [0,1] | 微表面粗糙程度 |
| Normal（法线） | 切线空间 | 法线扰动向量 |
| AO（环境遮蔽） | [0,1] | 间接光遮蔽，1=完全暴露 |

### 4.2 高效纹理打包策略（减少Texture Fetch次数）

**MRAO 打包方案**（工业标准）：
```
R通道 → Metallic
G通道 → Roughness  
B通道 → AO (Ambient Occlusion)
A通道 → 空置 or Height Map（用于视差）
```

```hlsl
// 解包MRAO贴图
float4 mrao = SAMPLE_TEXTURE2D(_MRAOMap, sampler_MRAOMap, uv);
float metallic    = mrao.r;
float roughness   = mrao.g;
float ao          = mrao.b;
float heightValue = mrao.a; // 可选：视差高度
```

### 4.3 完整PBR Shader Graph节点图（URP版）

```
── 纹理采样层 ──────────────────────────────────────────────────
[UV] ─→ [Tiling & Offset] ─→ [POM修正UV] ─→ [Sample: Albedo]  →  [Albedo×Color Tint]
                                        ↓         [Sample: MRAO]
                                        ├─────→ [Split: R=Metallic, G=Roughness, B=AO]
                                        └─────→ [Sample: Normal] → [Normal Unpack]
                                                                         ↓
                                                               [Normal Blend(Detail)]
── 光照计算层 ──────────────────────────────────────────────────
[Albedo×Color]       → PBR Master Stack: Base Color
[Metallic(R)]        → PBR Master Stack: Metallic
[Roughness(G)]       → PBR Master Stack: Smoothness（需 1-Roughness 转换）
[Normal Blend]       → PBR Master Stack: Normal (Tangent)
[AO(B)]              → PBR Master Stack: Ambient Occlusion
[Emission Texture]   → PBR Master Stack: Emission
[Alpha]              → PBR Master Stack: Alpha
```

### 4.4 Smoothness与Roughness的互转

Unity PBR 使用 Smoothness（光滑度），而美术工具（Substance Painter等）输出 Roughness（粗糙度），需转换：

```
Shader Graph中：[Roughness] → [One Minus] → [Smoothness Input]
```

这个细节经常被遗忘，导致材质视觉效果与 Substance 预览不一致。

### 4.5 自发光（Emission）的HDR处理

```
[Sample Texture 2D: Emission] 
    ↓ (RGB)
[Multiply: EmissionColor(HDR)]   ← 使用 HDRColor 属性，可在材质面板设置亮度超过1的值
    ↓
[Emission Input]
```

在材质面板中启用 `Bloom` 效果时，HDR Emission 的亮度值（Intensity）决定了泛光强度，常见设置：
- 弱自发光：Intensity = 1~2
- 霓虹/UI发光：Intensity = 3~8  
- 超亮爆炸：Intensity = 10~20

---

## 五、Shader Graph高级技巧

### 5.1 Keyword与静态分支优化

通过 Shader Keyword 在编译期分离功能路径，避免动态分支带来的 GPU Warp 分歧：

```
// 在Graph Settings → Shader Keywords中添加：
// Keyword: _USE_POM (Boolean)
// Keyword: _USE_DETAIL_NORMAL (Boolean)

[Keyword Node: _USE_POM]
  ├─ True：  [POM修正UV] → 采样
  └─ False： [原始UV] → 采样（移动端低配路径）
```

每个 Keyword 组合会生成一个 Shader Variant，需在 `ShaderVariantCollection` 中预热：

```csharp
// 预热所有Shader Variant（避免运行时卡顿）
[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
static void WarmupShaderVariants()
{
    var svc = Resources.Load<ShaderVariantCollection>("ShaderVariants/PBRMaterial");
    svc.WarmUp();
}
```

### 5.2 Sub Graph封装复用

将常用节点组合封装为 Sub Graph（类似函数），提升节点图可读性：

常见封装组合：
- `NormalMapDecode.shadersubgraph`：解码 + 强度控制
- `PBRTextureUnpack.shadersubgraph`：MRAO贴图解包
- `SimpleParallax.shadersubgraph`：基础视差偏移
- `TriplanarProjection.shadersubgraph`：三平面投影采样

```
创建 Sub Graph：
  右键 → Create → Shader Graph → Sub Graph
  在 Sub Graph 中定义 Input Port 和 Output Port
  其他 Graph 中通过 Sub Graph Node 引用
```

### 5.3 Custom Function节点最佳实践

当 Shader Graph 内置节点无法满足需求时，使用 Custom Function：

```hlsl
// 文件：Assets/Shaders/Functions/FresnelEffect.hlsl
void FresnelEffect_float(
    float3 Normal,        // World Normal
    float3 ViewDir,       // View Direction (World)
    float Power,          // 菲涅尔指数（通常1~5）
    out float FresnelFactor)
{
    FresnelFactor = pow(1.0 - saturate(dot(normalize(Normal), normalize(ViewDir))), Power);
}
```

**注意事项**：
1. 函数名必须以 `_float` 或 `_half` 结尾（精度后缀）
2. 输出参数必须用 `out` 关键字
3. 使用 `SAMPLE_TEXTURE2D` 而非 `tex2D`（兼容所有平台）

---

## 六、移动端优化检查清单

### 6.1 Shader Graph性能分析

在 Frame Debugger 中查看 Shader Stats：
```
Window → Analysis → Frame Debugger
选中 Draw Call → 查看右侧 Shader 的：
  - ALU Instructions（算术运算指令数）
  - Texture Fetch Count（纹理采样次数）
  - Interpolator Count（差值寄存器数，移动端通常上限8个）
```

### 6.2 移动端优化清单

```
✅ 精度设置：Graph Settings → Precision = Half
✅ 纹理通道打包：将 Metallic/Roughness/AO 合并为 MRAO 贴图（减少2次 Texture Fetch）
✅ POM 降级：移动端使用 Keyword 关闭 POM，退化为普通 Normal Map
✅ 法线贴图：使用 BC5/EAC 压缩格式（RG双通道，Z分量重建）
✅ mipmap：所有贴图开启 mipmap，避免高频采样产生摩尔纹
✅ 避免透明材质：尽量使用 Alpha Clip 替代 Alpha Blend（避免 Over Draw）
✅ Variant 数量控制：每个Keyword关键字的组合数 = 2^n，超过32个Variant要合并关键字
```

### 6.3 URP批处理兼容性

```csharp
// 确保材质支持GPU Instancing（大批量相同材质渲染）
// 在 Shader Graph 中：Graph Settings → Enable GPU Instancing ✅

// 动态合批需要满足：
// 1. 顶点数 < 300
// 2. 使用相同材质
// 3. 不能有自定义顶点着色器偏移
// 4. Shader Graph 中不使用 Object Space 坐标（会破坏合批）
```

---

## 七、完整案例：石墙PBR材质

### 7.1 美术资源准备

```
stone_wall_albedo.png   → 漫反射色（sRGB）
stone_wall_normal.png   → 法线贴图（Linear）
stone_wall_mrao.png     → Metallic(R) + Roughness(G) + AO(B)（Linear）
stone_wall_height.png   → 高度贴图（Linear，R通道）
stone_wall_detail.png   → 细节法线（Linear，高频凹凸细节）
```

### 7.2 节点图核心路径

```
[Tiling&Offset(UV, 2x2)] ──────────────────────────────────────────────────────┐
                    ↓                                                             │
[Sample Height Map] → [POM Offset] → [POM UV] ──────────────────────────────→  │
                                          ↓                                      │
                                   [Sample Albedo]  → [×TintColor] → BaseColor  │
                                   [Sample MRAO]    → Metallic/Smoothness/AO    │
                                   [Sample Normal]  ─┐                          │
                                                     ├→ [NormalBlend] → Normal  │
                                   [Sample Detail]  ─┘  (Reoriented Mode)       │
                                                                                 │
[DetailTiling&Offset(UV, 8x8)] ─────────────────────────────────────────────────┘
```

### 7.3 C#材质管理代码

```csharp
using UnityEngine;

/// <summary>
/// 石墙PBR材质运行时管理器
/// 支持动态调整视差强度、细节法线权重等参数
/// </summary>
[ExecuteAlways]
public class StoneWallMaterialController : MonoBehaviour
{
    [Header("材质引用")]
    [SerializeField] private Material _wallMaterial;
    
    [Header("视差设置")]
    [SerializeField, Range(0f, 0.1f)] private float _parallaxScale = 0.04f;
    [SerializeField, Range(4, 32)] private int _parallaxSteps = 16;
    
    [Header("法线设置")]
    [SerializeField, Range(0f, 2f)] private float _normalIntensity = 1f;
    [SerializeField, Range(0f, 1f)] private float _detailNormalBlend = 0.5f;
    
    [Header("PBR微调")]
    [SerializeField, Range(0f, 1f)] private float _roughnessOffset = 0f;
    [SerializeField] private Color _tintColor = Color.white;
    
    // Shader Property IDs（预缓存，避免字符串查找）
    private static readonly int ID_ParallaxScale    = Shader.PropertyToID("_ParallaxScale");
    private static readonly int ID_ParallaxSteps    = Shader.PropertyToID("_ParallaxSteps");
    private static readonly int ID_NormalIntensity  = Shader.PropertyToID("_NormalIntensity");
    private static readonly int ID_DetailBlend      = Shader.PropertyToID("_DetailNormalBlend");
    private static readonly int ID_RoughnessOffset  = Shader.PropertyToID("_RoughnessOffset");
    private static readonly int ID_TintColor        = Shader.PropertyToID("_TintColor");
    
    private void OnValidate() => ApplyToMaterial();
    private void Start()      => ApplyToMaterial();
    
    private void ApplyToMaterial()
    {
        if (_wallMaterial == null) return;
        
        _wallMaterial.SetFloat(ID_ParallaxScale,   _parallaxScale);
        _wallMaterial.SetInt  (ID_ParallaxSteps,   _parallaxSteps);
        _wallMaterial.SetFloat(ID_NormalIntensity, _normalIntensity);
        _wallMaterial.SetFloat(ID_DetailBlend,     _detailNormalBlend);
        _wallMaterial.SetFloat(ID_RoughnessOffset, _roughnessOffset);
        _wallMaterial.SetColor(ID_TintColor,       _tintColor);
        
        // 根据步进次数动态切换Keyword
        if (_parallaxSteps <= 1)
            _wallMaterial.EnableKeyword("_USE_PARALLAX_SIMPLE");
        else
            _wallMaterial.EnableKeyword("_USE_PARALLAX_POM");
    }
    
    /// <summary>
    /// 根据相机距离动态调整POM步进次数（LOD优化）
    /// </summary>
    public void UpdateLOD(float distanceToCamera)
    {
        if (_wallMaterial == null) return;
        
        int steps = distanceToCamera switch
        {
            < 5f   => 32,  // 近距离：高质量
            < 15f  => 16,  // 中距离：标准
            < 30f  => 8,   // 远距离：低质量
            _      => 0    // 超远：关闭POM
        };
        
        _parallaxSteps = steps;
        _wallMaterial.SetInt(ID_ParallaxSteps, steps);
    }
}
```

---

## 八、最佳实践总结

### 8.1 Shader Graph开发规范

| 规范项 | 推荐做法 |
|-------|---------|
| 节点命名 | 对关键节点右键 → Rename，避免节点图可读性差 |
| Sub Graph粒度 | 单一功能封装，控制在10~20个节点以内 |
| 精度管理 | 以Half为默认，坐标/深度升级Float |
| Keyword数量 | 单个Graph不超过5个Boolean Keyword |
| 注释 | 使用 Sticky Note 节点（右键 → Create → Sticky Note）说明模块用途 |
| 版本控制 | .shadergraph 是 JSON 格式，可被 Git 追踪和 diff |

### 8.2 PBR材质物理准确性检查

```
物理准确性自查清单：
✅ Albedo 范围：纯黑 > 0.02（无物理纯黑表面），纯白 < 0.9
✅ Metallic 非金属 = 0，金属 = 1，避免使用中间值（宝石等特殊材质除外）
✅ Roughness 0 = 镜面，1 = 完全漫反射，陶瓷约0.3，石头约0.7~0.9
✅ 法线贴图 Linear 空间导入（取消 sRGB 勾选）
✅ Albedo 不包含任何光影信息（烘焙阴影会破坏PBR准确性）
✅ Metallic 贴图 Linear 空间导入
```

### 8.3 常见错误与修复

| 错误现象 | 根本原因 | 修复方法 |
|---------|---------|---------|
| 法线贴图颠倒 | OpenGL/DX法线格式不同（G通道翻转） | 勾选 Texture Import → Flip Green Channel |
| 材质看起来太塑料 | Roughness值偏低，Metallic=0时高光过强 | 调整Roughness至0.4~0.6 |
| POM产生明显锯齿台阶 | 步进次数不足 | 增加步进次数或开启线性插值细化 |
| 视差边缘异常 | 边缘视差超出UV范围 | 在边缘区域使用Clamp UV或降低视差强度 |
| Shader Variant过多 | Keyword组合爆炸 | 合并相关Keyword或使用ShaderFeature替代MultiCompile |

---

Unity Shader Graph 通过节点化的 PBR 着色器开发，让技术美术和程序员都能高效协作。掌握视差贴图、法线混合和完整 PBR 流程，是打造高质量游戏视觉效果的核心技能。在实际项目中，应始终将**物理准确性**与**移动端性能**放在同等重要的位置来权衡取舍。
