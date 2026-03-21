---
title: "Unity Shader高级编程：从基础语法到GPU优化"
description: "深度解析Unity Shader编程，从ShaderLab语法到HLSL高级技巧，包括顶点着色器、片元着色器、几何着色器、计算着色器，以及移动端GPU针对性优化策略"
pubDate: "2025-03-21"
tags: ["Shader", "HLSL", "ShaderLab", "GPU编程", "计算着色器", "渲染优化"]
---

# Unity Shader高级编程：从基础语法到GPU优化

> Shader是游戏渲染的灵魂。掌握Shader编程，意味着你能从根本上控制游戏的每一个像素。这是渲染工程师与其他程序员的核心分水岭。

---

## 一、Shader编程基础

### 1.1 ShaderLab结构

```hlsl
Shader "Custom/MyShader"
{
    // 材质属性（在Inspector中显示）
    Properties
    {
        _MainTex ("主贴图", 2D) = "white" {}
        _Color ("颜色", Color) = (1,1,1,1)
        _Metallic ("金属度", Range(0,1)) = 0
        _Roughness ("粗糙度", Range(0,1)) = 0.5
    }
    
    SubShader
    {
        // 渲染标签
        Tags 
        { 
            "RenderType" = "Opaque"           // 渲染类型（用于相机替换材质等）
            "RenderPipeline" = "UniversalPipeline"  // URP标志
            "Queue" = "Geometry"             // 渲染队列
        }
        
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" } // URP光照Pass
            
            // GPU状态设置
            Cull Back       // 背面剔除（Front/Back/Off）
            ZWrite On       // 写深度缓冲
            ZTest LEqual    // 深度测试
            Blend Off       // 混合模式（Off=不透明，SrcAlpha OneMinusSrcAlpha=Alpha混合）
            
            HLSLPROGRAM
            #pragma vertex vert   // 指定顶点着色器函数
            #pragma fragment frag // 指定片元着色器函数
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            // 着色器代码...
            
            ENDHLSL
        }
    }
    
    // 降级Shader（当主Shader不支持时使用）
    FallBack "Diffuse"
}
```

### 1.2 顶点和片元着色器

```hlsl
// 属性常量缓冲（SRP Batcher必需）
CBUFFER_START(UnityPerMaterial)
    float4 _MainTex_ST;  // 贴图的Tiling和Offset
    float4 _Color;
    float _Metallic;
    float _Roughness;
CBUFFER_END

// 贴图采样器
TEXTURE2D(_MainTex);
SAMPLER(sampler_MainTex);

// 输入结构（来自CPU，每个顶点一份）
struct Attributes
{
    float4 positionOS : POSITION;  // 对象空间位置
    float3 normalOS   : NORMAL;    // 法线
    float4 tangentOS  : TANGENT;   // 切线（法线贴图用）
    float2 uv         : TEXCOORD0; // 主UV
    float2 uv2        : TEXCOORD1; // 光照贴图UV（可选）
    UNITY_VERTEX_INPUT_INSTANCE_ID // GPU Instancing支持
};

// 输出结构（顶点→片元插值）
struct Varyings
{
    float4 positionCS : SV_POSITION; // 裁剪空间位置（必须）
    float2 uv         : TEXCOORD0;
    float3 positionWS : TEXCOORD1;  // 世界空间位置（光照计算用）
    float3 normalWS   : TEXCOORD2;  // 世界空间法线
    float3 tangentWS  : TEXCOORD3;
    float3 bitangentWS: TEXCOORD4;
    UNITY_VERTEX_OUTPUT_STEREO       // VR支持
};

// 顶点着色器：每个顶点执行一次
Varyings vert(Attributes input)
{
    Varyings output;
    UNITY_SETUP_INSTANCE_ID(input);
    UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
    
    // 使用URP工具函数（自动处理各种变换）
    VertexPositionInputs posInputs = GetVertexPositionInputs(input.positionOS.xyz);
    VertexNormalInputs normalInputs = GetVertexNormalInputs(input.normalOS, input.tangentOS);
    
    output.positionCS = posInputs.positionCS;
    output.positionWS = posInputs.positionWS;
    output.uv = TRANSFORM_TEX(input.uv, _MainTex); // Tiling/Offset变换
    output.normalWS = normalInputs.normalWS;
    output.tangentWS = normalInputs.tangentWS;
    output.bitangentWS = normalInputs.bitangentWS;
    
    return output;
}

// 片元着色器：每个像素执行一次
float4 frag(Varyings input) : SV_Target
{
    // 采样贴图
    float4 albedoAlpha = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, input.uv);
    float3 albedo = albedoAlpha.rgb * _Color.rgb;
    
    // 法线（世界空间，已归一化）
    float3 N = normalize(input.normalWS);
    
    // 主光源
    Light mainLight = GetMainLight();
    float3 L = normalize(mainLight.direction);
    float3 lightColor = mainLight.color;
    
    // 简单漫反射（Lambertian）
    float NdotL = max(dot(N, L), 0.0);
    float3 diffuse = albedo * lightColor * NdotL;
    
    // 环境光（简化）
    float3 ambient = albedo * 0.1;
    
    float3 finalColor = diffuse + ambient;
    
    return float4(finalColor, 1.0);
}
```

---

## 二、高级着色器技术

### 2.1 法线贴图完整实现

```hlsl
// 法线贴图：将贴图中存储的切线空间法线转换到世界空间

TEXTURE2D(_NormalMap);
SAMPLER(sampler_NormalMap);

CBUFFER_START(UnityPerMaterial)
    float _NormalStrength;
CBUFFER_END

float4 frag(Varyings input) : SV_Target
{
    // 采样并解码法线贴图
    float4 normalSample = SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, input.uv);
    
    // 解码法线（DXT5nm格式或普通格式）
    float3 normalTS = UnpackNormalScale(normalSample, _NormalStrength);
    // normalTS：切线空间法线，z轴朝上
    
    // 构建TBN矩阵（切线空间→世界空间）
    float3 T = normalize(input.tangentWS);
    float3 B = normalize(input.bitangentWS);
    float3 N = normalize(input.normalWS);
    float3x3 TBN = float3x3(T, B, N);
    
    // 将法线从切线空间变换到世界空间
    float3 worldNormal = normalize(mul(normalTS, TBN));
    
    // 使用worldNormal进行光照计算
    // ...
    
    return float4(worldNormal * 0.5 + 0.5, 1.0); // 可视化法线（调试）
}
```

### 2.2 溶解效果（Dissolve）

```hlsl
// 经典的溶解效果：配合dissolve贴图和cutoff值实现
TEXTURE2D(_DissolveTex);
SAMPLER(sampler_DissolveTex);
TEXTURE2D(_EdgeColorTex); // 溶解边缘颜色（可选）

CBUFFER_START(UnityPerMaterial)
    float _DissolveAmount;  // 0=完整, 1=完全溶解
    float _EdgeWidth;       // 边缘宽度
    float4 _EdgeColor;      // 边缘颜色（如火焰色）
CBUFFER_END

float4 frag(Varyings input) : SV_Target
{
    float4 mainColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, input.uv);
    float dissolveValue = SAMPLE_TEXTURE2D(_DissolveTex, sampler_DissolveTex, input.uv).r;
    
    // 溶解逻辑：dissolveValue < _DissolveAmount 的像素被裁剪
    float cutoff = dissolveValue - _DissolveAmount;
    clip(cutoff); // cutoff < 0 时，像素被丢弃（Alpha Clip）
    
    // 边缘发光：接近溶解边界的像素显示边缘颜色
    float edgeFactor = saturate(cutoff / _EdgeWidth);
    float3 finalColor = lerp(_EdgeColor.rgb, mainColor.rgb, edgeFactor);
    
    return float4(finalColor, 1.0);
}
```

### 2.3 计算着色器（Compute Shader）

```hlsl
// Compute Shader：在GPU上运行通用计算
// 适用：大量粒子更新、布料模拟、GPU拣选

// ComputeShader文件（.compute扩展名）
#pragma kernel CSMain

// 输入/输出缓冲
RWStructuredBuffer<float3> positions;
RWStructuredBuffer<float3> velocities;
float deltaTime;
float3 attractor; // 引力中心

// 每个线程组8x8x1 = 64个线程
[numthreads(64, 1, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    uint index = id.x;
    
    // 计算引力
    float3 dir = attractor - positions[index];
    float dist = length(dir);
    float3 force = normalize(dir) / (dist * dist) * 0.1;
    
    // 更新速度和位置
    velocities[index] += force * deltaTime;
    velocities[index] *= 0.99; // 阻尼
    positions[index] += velocities[index] * deltaTime;
}
```

```csharp
// C#调用Compute Shader
public class GPUParticleSystem : MonoBehaviour
{
    [SerializeField] private ComputeShader _computeShader;
    [SerializeField] private Material _particleMaterial;
    [SerializeField] private int _particleCount = 100000;
    
    private ComputeBuffer _positionBuffer;
    private ComputeBuffer _velocityBuffer;
    
    void Start()
    {
        // 创建GPU缓冲（不在托管堆，直接在显存）
        _positionBuffer = new ComputeBuffer(_particleCount, sizeof(float) * 3);
        _velocityBuffer = new ComputeBuffer(_particleCount, sizeof(float) * 3);
        
        // 初始化数据
        var initialPositions = new Vector3[_particleCount];
        var initialVelocities = new Vector3[_particleCount];
        for (int i = 0; i < _particleCount; i++)
        {
            initialPositions[i] = Random.insideUnitSphere * 5f;
            initialVelocities[i] = Random.insideUnitSphere * 0.1f;
        }
        
        _positionBuffer.SetData(initialPositions);
        _velocityBuffer.SetData(initialVelocities);
        
        // 绑定缓冲到Compute Shader
        int kernelIndex = _computeShader.FindKernel("CSMain");
        _computeShader.SetBuffer(kernelIndex, "positions", _positionBuffer);
        _computeShader.SetBuffer(kernelIndex, "velocities", _velocityBuffer);
        
        // 绑定缓冲到渲染Shader（直接在GPU内使用，无需回传CPU）
        _particleMaterial.SetBuffer("_Positions", _positionBuffer);
    }
    
    void Update()
    {
        // 每帧在GPU上运行粒子更新
        int kernelIndex = _computeShader.FindKernel("CSMain");
        _computeShader.SetFloat("deltaTime", Time.deltaTime);
        _computeShader.SetVector("attractor", transform.position);
        
        // Dispatch：启动 (_particleCount/64) 个线程组
        _computeShader.Dispatch(kernelIndex, _particleCount / 64, 1, 1);
        
        // 用GPU Instancing渲染（不需要CPU参与！）
        // Mesh的位置直接从GPU缓冲读取
        Graphics.DrawMeshInstancedProcedural(
            _particleMesh, 0, _particleMaterial, 
            new Bounds(Vector3.zero, Vector3.one * 100f), 
            _particleCount
        );
    }
    
    void OnDestroy()
    {
        _positionBuffer?.Release(); // 必须手动释放！
        _velocityBuffer?.Release();
    }
}
```

---

## 三、Shader变体管理

### 3.1 关键字与变体

```hlsl
// 编译时关键字（multi_compile 或 shader_feature）
// 每个组合生成一个Shader变体

// multi_compile：无论是否使用，都编译所有组合
#pragma multi_compile _ ENABLE_FOG         // 2个变体
#pragma multi_compile _ _SHADOWS_SOFT      // 2个变体
// 总共：2 × 2 = 4个变体

// shader_feature：只编译材质实际用到的组合（推荐！）
#pragma shader_feature _ _NORMALMAP        // 只编译用到的
#pragma shader_feature _ _SPECGLOSSMAP

// 在Shader中使用关键字
float4 frag(Varyings input) : SV_Target
{
    float3 N = input.normalWS;
    
    #ifdef _NORMALMAP
    // 如果开启了法线贴图
    float3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, input.uv));
    // ... TBN变换
    #endif
    
    // ...
}
```

---

## 四、Shader调试技术

```hlsl
// 可视化调试：将中间计算结果输出为颜色

float4 frag(Varyings input) : SV_Target
{
    // 可视化法线
    float3 N = normalize(input.normalWS);
    return float4(N * 0.5 + 0.5, 1.0); // 将[-1,1]映射到[0,1]

    // 可视化UV坐标
    return float4(input.uv, 0, 1);
    
    // 可视化深度
    float depth = input.positionCS.z / input.positionCS.w;
    return float4(depth, depth, depth, 1);
    
    // 可视化顶点颜色
    return input.color;
    
    // 可视化面向相机（正面=白，背面=黑）
    float3 viewDir = normalize(GetCameraPositionWS() - input.positionWS);
    return float4(max(dot(N, viewDir), 0).xxx, 1);
}
```

---

## 五、GPU性能优化

### 5.1 Shader性能分析

```
工具：
1. Unity Frame Debugger（查看Shader信息）
2. RenderDoc（Windows/Android）
3. Xcode GPU Frame Capture（iOS）
4. Mali GPU Analyzer（ARM GPU）
5. Snapdragon Profiler（高通GPU）

关键指标：
- GPU Time（总渲染时间）
- Vertex Shader Time
- Fragment Shader Time
- Texture Bandwidth（纹理带宽）
- Instruction Count（指令数）
```

### 5.2 优化技巧

```hlsl
// 1. 将逐像素计算移到逐顶点（当精度允许时）
// ❌ 逐像素计算太阳方向（实际上太阳方向是常量！）
float4 frag(Varyings input) : SV_Target
{
    float3 sunDir = normalize(_MainLightPosition.xyz); // 每像素重复计算
    // ...
}

// ✅ 在顶点着色器中传递（节省片元着色器计算）
struct Varyings
{
    float4 positionCS : SV_POSITION;
    float NdotL : TEXCOORD5; // 预计算的光照值
};

Varyings vert(Attributes input)
{
    Varyings output;
    float3 N = TransformObjectToWorldNormal(input.normalOS);
    float3 L = normalize(_MainLightPosition.xyz);
    output.NdotL = max(dot(N, L), 0); // 逐顶点计算，片元插值
    return output;
}

// 2. 使用低精度（移动端）
// half（16位）代替float（32位）
half3 CalculateDiffuse(half3 normal, half3 lightDir, half3 albedo)
{
    half NdotL = max(dot(normal, lightDir), 0.0h);
    return albedo * NdotL;
}

// 3. 避免动态分支（GPU所有分支都执行）
// ❌ 
if (NdotL > 0)
    color = NdotL * albedo;
else
    color = 0;

// ✅ 使用saturate/step/lerp代替分支
float4 color = saturate(NdotL) * float4(albedo, 1);

// 4. 贴图采样优化
// ❌ 多次采样同一贴图的不同通道（分开的4次采样）
float r = tex.r;
float g = tex.g;
float b = tex.b;
float a = tex.a;

// ✅ 一次采样获取所有通道
float4 texSample = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv);
float r = texSample.r;
float g = texSample.g;
// 等等
```

---

## 总结

Shader编程学习路径：

```
入门（1-2个月）：
→ 理解渲染管线（顶点→光栅化→片元→输出）
→ HLSL基础语法（向量、矩阵、内置函数）
→ Unity ShaderLab格式
→ 实现：Lambert漫反射、Specular高光

进阶（3-6个月）：
→ 法线贴图、高度贴图
→ PBR理论和实现（D/F/G函数）
→ URP自定义Pass
→ 后处理效果（Bloom、DOF）

高级（6个月+）：
→ 计算着色器（GPU计算）
→ 自定义SRP渲染管线
→ GPU Driven Rendering
→ 移动端特化优化（Tile-based GPU）

技术负责人的Shader责任：
→ 建立项目Shader基础库（避免重复开发）
→ 制定Shader性能规范（移动端ALU/带宽预算）
→ 建立Shader代码Review机制
→ 为美术同学提供可调整的Shader参数（不需要懂HLSL就能调效果）
```
