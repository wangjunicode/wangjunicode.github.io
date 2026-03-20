---
title: Shader 性能优化实战：移动端图形调优全指南
published: 2026-03-21
description: "深度讲解移动端 Shader 开发的性能优化实践，包括 GPU 数学指令优化、纹理采样优化、分支优化、半精度浮点使用、Shader 变体管理，以及使用 RenderDoc 进行 GPU 性能分析。"
tags: [Shader, 性能优化, Unity, 图形渲染, 移动端]
category: 图形渲染
draft: false
---

## 移动端 Shader 开发的特殊性

移动端 GPU 与桌面 GPU 有根本性的架构差异：

```
桌面 GPU（NVIDIA GeForce、AMD Radeon）：
  - 数千个着色器核心
  - 极高的并行计算能力
  - 大显存（8~24GB）
  - 散热条件好

移动端 GPU（Mali、Adreno、PowerVR）：
  - 数十到数百个着色器核心
  - TBDR 架构（前文讲过）
  - 统一内存（CPU/GPU 共享 RAM，通常 4~12GB）
  - 功耗和温度限制严格（降频保护）
```

移动端 Shader 优化的核心原则：
1. **减少 ALU 指令**：计算单元有限，每条指令都是代价
2. **减少纹理采样**：带宽是瓶颈
3. **使用半精度**：half 比 float 快 2 倍（部分 GPU）
4. **避免动态分支**：GPU 对分支的处理效率低

---

## 一、数学指令优化

### 1.1 替代昂贵的数学运算

```glsl
// GPU 指令成本大致排序（从快到慢）：
// add, mul, mad, saturate < dot, normalize < pow, exp, log < sin, cos, sqrt

// ❌ 使用 pow 计算高光（代价高）
float specular = pow(max(0.0, dot(N, H)), _Shininess);

// ✅ 方案1：使用 exp2 + log2 替代 pow（稍快，更稳定）
float specular = exp2(log2(max(0.001, dot(N, H))) * _Shininess);

// ✅ 方案2：预烘焙到 LUT 纹理（最快，但需要额外纹理）
float2 lutUV = float2(max(0.0, dot(N, H)), _Shininess / 256.0);
float specular = tex2D(_SpecularLUT, lutUV).r;

// ✅ 方案3：使用近似公式（视觉上差别不大）
// Blinn-Phong 的低成本近似
float NH = saturate(dot(N, H));
float specular = NH * NH; // 快速近似平方
```

### 1.2 向量化计算（SIMD 友好）

```glsl
// ❌ 逐分量计算
float r = diffuse.r * lightColor.r * attenuation;
float g = diffuse.g * lightColor.g * attenuation;
float b = diffuse.b * lightColor.b * attenuation;

// ✅ 向量化（GPU 可以一条指令完成）
float3 result = diffuse.rgb * lightColor.rgb * attenuation;

// ❌ 多次 dot 计算
float x = dot(normal, float3(1, 0, 0));
float y = dot(normal, float3(0, 1, 0));
float z = dot(normal, float3(0, 0, 1));

// ✅ 利用矩阵运算合并
// 如果方向是固定的轴，直接读取分量
float x = normal.x;
float y = normal.y;
float z = normal.z;
```

### 1.3 减少除法

```glsl
// ❌ 除法（慢）
float3 normalized = v / length(v);

// ✅ 使用 normalize（HLSL 内置，通常有硬件优化）
float3 normalized = normalize(v);

// ❌ 每像素做除法
float ratio = _Value1 / _Value2;

// ✅ 在 CPU 预计算，作为 uniform 传入
// C# 侧：_material.SetFloat("_ValueRatio", value1 / value2);
// Shader 侧：直接使用 _ValueRatio

// ❌ 光照计算中的除法
float3 lightDir = (_LightPos - worldPos) / distance(_LightPos, worldPos);

// ✅ 合并为 rsqrt（倒数平方根）
float3 toLight = _LightPos - worldPos;
float distSq = dot(toLight, toLight);
float invDist = rsqrt(distSq); // 1/sqrt(distSq)，通常是单条指令
float3 lightDir = toLight * invDist;
float attenuation = distSq * invDist; // 即 sqrt(distSq)
```

---

## 二、精度优化：half vs float

### 2.1 正确使用 half 精度

```glsl
// half = 16位浮点，范围约 ±65504，精度约 3位有效十进制数
// float = 32位浮点，范围约 ±3.4e38，精度约 7位有效十进制数

// ✅ 适合用 half 的场景
half4 color = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv);  // 颜色值 [0,1]
half3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, ...)); // 法线 [-1,1]
half metallic = SAMPLE_TEXTURE2D(_MaskMap, ...).r;               // 标量 [0,1]

// ❌ 不能用 half 的场景
float3 worldPos = TransformObjectToWorld(positionOS);  // 世界坐标，精度要求高
float4 clipPos = TransformWorldToHClip(worldPos);      // 裁剪空间坐标
float depth = clipPos.z / clipPos.w;                   // 深度值，需要高精度

// ✅ URP 中的标准用法
Varyings vert(Attributes input)
{
    Varyings output;
    
    // 坐标：必须 float
    float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);
    output.positionHCS = TransformWorldToHClip(positionWS);
    
    // UV：可以 half（如果不是大地形）
    output.uv = (half2)TRANSFORM_TEX(input.uv, _BaseMap);
    
    // 法线：可以 half
    output.normalWS = (half3)TransformObjectToWorldNormal(input.normalOS);
    
    return output;
}

half4 frag(Varyings input) : SV_Target
{
    // 所有颜色计算：用 half
    half4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv);
    half3 normal = normalize(input.normalWS); // normalize 后可以用 half
    
    // 光照系数：用 half
    half NdotL = saturate(dot(normal, (half3)_MainLightDirection.xyz));
    half3 diffuse = baseColor.rgb * NdotL * (half3)_MainLightColor.rgb;
    
    return half4(diffuse, baseColor.a);
}
```

### 2.2 Mali GPU 的 精度特别注意

```glsl
// Mali GPU 对 mediump（half）有特殊优化
// 在 GLSL 中需要显式声明精度（Unity 的 HLSL 会自动转换）

// 一些 Mali GPU 的 full precision（float）和 half 性能差距可达 4 倍
// 所以在 Mali 设备上，精度选择对性能影响更大

// 检查方法：使用 Mali Offline Compiler
// 或者使用 Perfetto/Snapdragon Profiler 实测
```

---

## 三、纹理采样优化

### 3.1 减少采样次数

```glsl
// 纹理采样原则：一次采样尽量利用所有 4 个通道

// ❌ 多张纹理存储可以合并的数据
sampler2D _MetallicMap;    // 只用 R 通道
sampler2D _RoughnessMap;   // 只用 R 通道
sampler2D _AOMap;          // 只用 R 通道
sampler2D _EmissionMask;   // 只用 R 通道

half metallic  = tex2D(_MetallicMap, uv).r;    // 4次采样
half roughness = tex2D(_RoughnessMap, uv).r;
half ao        = tex2D(_AOMap, uv).r;
half emission  = tex2D(_EmissionMask, uv).r;

// ✅ 打包到一张 Mask Map（URP 的标准做法）
// R=Metallic, G=AO, B=DetailMask, A=Smoothness
sampler2D _MaskMap;

half4 mask    = tex2D(_MaskMap, uv);           // 1次采样
half metallic  = mask.r;
half ao        = mask.g;
half smoothness = mask.a;
```

### 3.2 Mipmap 与 LOD 偏移

```glsl
// 显式控制 mip 级别（某些情况下有用）
half4 tex = SAMPLE_TEXTURE2D_LOD(_BaseMap, sampler_BaseMap, uv, 2); // 强制使用 mip 2

// 各向异性过滤（AnisotropicFiltering）
// 在 Texture Import 设置中调整 Aniso Level
// Level 1: 最低（性能最好）
// Level 16: 最高（最佳质量，主要对斜视角度的表面有帮助）
// 移动端：大多数情况 Level 1~2 足够

// 避免在片元着色器中计算动态 UV offset（会增加 anisotropic 消耗）
// ❌ 在 frag 中做 UV 动画
float2 animatedUV = uv + float2(_Time.y * 0.1, 0);

// ✅ 在 vert 中做（每顶点只算一次）
// 如果使用插值，效果基本一样但性能更好
Varyings vert(Attributes input)
{
    output.uv = input.uv + float2(_Time.y * 0.1, 0); // 在顶点着色器做
    return output;
}
```

---

## 四、Shader 变体管理

### 4.1 变体爆炸问题

```
Shader 变体（Shader Variant）：
  Shader 中每个 #pragma multi_compile 定义会导致变体数翻倍
  
例：
  #pragma multi_compile _ _RECEIVE_SHADOWS        // 2个变体
  #pragma multi_compile _ _MAIN_LIGHT_SHADOWS      // 2个变体  
  #pragma multi_compile _ _SHADOWS_SOFT            // 2个变体
  
  总变体数 = 2 × 2 × 2 = 8个变体
  
  如果有10个这样的关键字：2^10 = 1024个变体！
  
后果：
  - 打包时间暴增（每个变体都要编译）
  - 包体增大（每个变体都打进包）
  - 首次加载时间增加（编译所有变体）
```

### 4.2 精简变体

```glsl
// 策略1：用 shader_feature 替代 multi_compile
// multi_compile：所有关键字组合都会被打进包
// shader_feature：只打包实际使用的材质中用到的组合

#pragma shader_feature_local _NORMALMAP  // 推荐：本地关键字，减少变体传播
#pragma shader_feature_local _EMISSION

// ❌ 避免使用全局关键字（影响所有 Shader）
#pragma multi_compile _ GLOBAL_WEATHER_RAIN  // 全局影响

// ✅ 使用本地关键字
#pragma shader_feature_local _ _WEATHER_RAIN  // 只影响当前 Shader

// 策略2：使用 if 语句（某些情况下比多变体更好）
// 当分支条件是 uniform（材质参数），GPU 可以做到"统一流控"
// 如果渲染批次内的材质参数相同，这个分支对性能影响很小

half4 frag(Varyings input) : SV_Target
{
    half4 color = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv);
    
    // 用 _EnableEmission 代替变体（如果不需要极致性能）
    if (_EnableEmission > 0.5)
    {
        half4 emission = SAMPLE_TEXTURE2D(_EmissionMap, sampler_EmissionMap, input.uv);
        color.rgb += emission.rgb * _EmissionColor.rgb;
    }
    
    return color;
}
```

### 4.3 Shader 变体收集与预热

```csharp
// 预热 Shader（避免运行时编译卡顿）
// 方案1：ShaderVariantCollection
// 在 Editor 中录制实际使用的变体组合，打包时只包含这些变体

// 方案2：代码预热
public class ShaderWarmer : MonoBehaviour
{
    [SerializeField] private ShaderVariantCollection[] _collections;
    
    async void Start()
    {
        // 在加载界面期间预热 Shader
        foreach (var collection in _collections)
        {
            collection.WarmUp();
            await UniTask.NextFrame(); // 分帧执行，避免一帧卡死
        }
        
        Debug.Log("Shader 预热完成");
    }
}

// 方案3：URP 的 SRP 预热（Unity 2022+）
// ProjectSettings → Graphics → Shader Preloading
// 设置 Preloaded Shaders = 你的 ShaderVariantCollection
```

---

## 五、使用 RenderDoc 进行 GPU 性能分析

### 5.1 RenderDoc 基础工作流

```
安装与配置：
1. 下载 RenderDoc（renderdo c.org）
2. Unity 中：Window → Analysis → Frame Debugger → 
   在 RenderDoc 中打开（或直接通过 RenderDoc 注入 Unity）

截帧分析步骤：
1. 运行游戏到目标场景
2. F12 截取一帧
3. 在 Event Browser 中查看所有 DrawCall
4. 点击某个 DrawCall，查看：
   - Mesh Viewer（输入顶点数据）
   - Texture Viewer（使用的纹理）
   - Shader Viewer（编译后的着色器代码）
   - Pipeline State（渲染状态）
```

### 5.2 通过 RenderDoc 定位问题

```
常见问题定位：

1. 材质显示为粉红色
   → 在 Event Browser 找到这个 DrawCall
   → 查看 Shader Viewer → 通常是编译错误或纹理未绑定
   
2. DrawCall 过多
   → 观察 Event Browser 中相邻的 DrawCall
   → 如果相同 Shader 但没有合并 → 检查合批条件
   → 使用 RenderDoc 的 Statistics 功能统计 DrawCall 分布
   
3. 某个特效帧率骤降
   → 截取特效出现的帧
   → 在 Event Browser 中找到特效相关的 DrawCall
   → 查看 Shader 的指令数（Shader Viewer → 指令计数）
   → 查看 Overdraw（使用自定义的 Overdraw Debug Shader）

4. 纹理内存超标
   → Texture Viewer 中查看所有纹理
   → 按大小排序，找到最大的纹理
   → 确认是否有可以降低分辨率或更换压缩格式的纹理
```

---

## 六、自定义 Shader 调试技巧

### 6.1 可视化调试变量

```glsl
// 直接输出变量到颜色（最简单的调试方式）
half4 frag(Varyings input) : SV_Target
{
    // 调试法线方向（法线可视化）
    half3 normal = normalize(input.normalWS);
    return half4(normal * 0.5 + 0.5, 1); // 映射到 [0,1] 显示
    
    // 调试 UV
    // return half4(input.uv, 0, 1);
    
    // 调试 Mipmap 级别（不同级别显示不同颜色）
    // float mipLevel = abs(ddx(input.uv.x)) + abs(ddy(input.uv.y));
    // return mipLevel < 0.01 ? half4(0,1,0,1) : half4(1,0,0,1);
    
    // 调试光照计算
    // float NdotL = saturate(dot(normalize(input.normalWS), _MainLightDirection.xyz));
    // return half4(NdotL, NdotL, NdotL, 1);
}
```

### 6.2 Shader 热重载开发流程

```
高效 Shader 开发工作流：

1. 在 Unity Editor 中打开 Scene 视图
2. 打开 Shader 文件（VS Code + ShaderlabVS 插件）
3. 修改 Shader → Ctrl+S 保存
4. Unity 自动重新编译 Shader（通常 2~5 秒）
5. 立即在 Scene 视图中看到效果
6. 用 Frame Debugger 确认 Pass 数量和渲染状态

提高效率的技巧：
  - 准备一个 Shader Playground 场景（专门用于 Shader 开发）
  - 场景中放置各种测试网格（球、平面、角色模型）
  - 使用 ShaderGraph（可视化，更直观）原型设计，然后翻译为代码
```

---

## 总结

移动端 Shader 优化的优先级：

```
1. 减少纹理采样次数（带宽通常是最大瓶颈）
2. 使用 half 精度（显著降低 ALU 和带宽）
3. 减少动态分支（用数学运算替代）
4. 控制 Shader 变体数量（减少包体和加载时间）
5. 减少昂贵的数学运算（sin/cos/pow 等）
```

**评估工具**：
- **Mali GPU Analyzer**：离线分析 Shader 指令数
- **Snapdragon Profiler**：高通设备实时 GPU 分析
- **Unity Frame Debugger**：DrawCall 和渲染状态分析
- **RenderDoc**：深度帧分析

> **下一篇**：[ECS/DOTS 架构深度入门：数据导向设计在游戏中的应用]
