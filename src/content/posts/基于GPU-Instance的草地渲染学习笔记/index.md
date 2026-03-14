---
title: 基于 GPU Instancing 的草地渲染实战笔记
published: 2020-08-08
description: "从 GPU Instancing 底层原理出发，深入讲解大规模草地渲染的完整实现方案：DrawMeshInstanced vs DrawMeshInstancedIndirect 的选择依据，Shader 中基于 sin 波的风动画实现，LOD 与视锥剔除优化，以及实际性能数据对比。包含完整的 C# 和 HLSL 代码示例。"
tags: [Unity, 渲染, 图形渲染, 性能优化, Shader]
category: 图形渲染
draft: false
---

做草地渲染这个技术调研时，我被 Colin 大神的效果震撼到了——几十万根草，在手机上也能流畅运行。研究完他的方案之后，我把整个技术链路整理成这篇笔记。

参考仓库：[UnityURP-MobileDrawMeshInstancedIndirectExample](https://github.com/ColinLeung-NiloCat/UnityURP-MobileDrawMeshInstancedIndirectExample)

---

## GPU Instancing 底层原理

### 传统渲染的瓶颈

传统渲染方式（无合批）：绘制 N 个对象就需要向 GPU 发送 N 次 Draw Call。每次 Draw Call 前，CPU 需要整理数据、调用 API、等待 GPU 响应，这个 CPU-GPU 通信过程是主要瓶颈。

渲染 10 万根草 = 10 万次 Draw Call → CPU 完全跑满，GPU 却在等待。

### GPU Instancing 的核心思想

**一次 Draw Call，绘制 N 个实例。**

GPU Instancing 把所有实例的变换矩阵（位置/旋转/缩放）一次性传给 GPU，GPU 自己负责绘制每一个实例，CPU 只需要提交一次命令。

```
传统方式：
CPU → [SetTransform] → GPU → Render Instance 1
CPU → [SetTransform] → GPU → Render Instance 2
... (重复 100000 次)

GPU Instancing：
CPU → [所有变换矩阵] → GPU → Render All 100000 Instances
                               (GPU 内部并行处理)
```

### Unity 中的两种 GPU Instancing 方式

**方式一：自动合批（材质启用 GPU Instancing）**

在材质 Inspector 中勾选 "Enable GPU Instancing"。Unity 自动收集使用相同材质的 GameObject，将它们合批处理。

适合：普通场景中的重复物体（树木、石头等数量不太多的情况）。

**方式二：手动调用 API**

通过代码直接调用 `DrawMeshInstanced` 或 `DrawMeshInstancedIndirect`，完全控制 GPU Instancing 的数据传递。

适合：需要极致性能优化的场景，比如草地、粒子。

---

## 草地渲染的技术挑战

单纯的 GPU Instancing 只是第一步，真正的草地渲染还要面对：

1. **数量极多**：一片草地可能有 100 万根草，一次 `DrawMeshInstanced` 最多支持 1023 个实例，需要多次调用或用 `Indirect` 版本
2. **视锥剔除**：摄像机看不到的草不应该渲染（但 CPU 侧剔除 100 万根草本身就很慢）
3. **LOD（细节层次）**：远处的草可以用更简单的 Mesh，甚至用 Billboard 贴片
4. **风动画**：草需要随风摆动，每根草的摆动方向和幅度要有差异，不能千篇一律
5. **遮挡剔除**：被地形或建筑挡住的草也不用渲染

---

## DrawMeshInstanced vs DrawMeshInstancedIndirect

| 维度 | DrawMeshInstanced | DrawMeshInstancedIndirect |
|------|-------------------|--------------------------|
| **最大实例数** | 1023 | 几乎无限（受显存限制）|
| **数据传递** | C# 数组，每帧从 CPU 传 | ComputeBuffer，GPU 侧存储 |
| **GPU 侧剔除** | ❌ 不支持（CPU 剔除） | ✅ 支持（Compute Shader 剔除）|
| **参数更新** | 每帧 CPU 更新数组 | 可以完全 GPU 驱动 |
| **使用复杂度** | 低 | 高 |
| **适用场景** | 数量 < 1000，动态变化 | 数量 > 1000，高性能要求 |

**结论**：做草地必须用 `DrawMeshInstancedIndirect`，因为数量级和 GPU 侧剔除都是刚需。

---

## 完整实现：DrawMeshInstancedIndirect 草地渲染

### C# 管理脚本

```csharp
using System;
using UnityEngine;

public class GrassRenderer : MonoBehaviour
{
    [Header("草地配置")]
    public Mesh GrassMesh;
    public Material GrassMaterial;
    public int GrassCount = 100000;
    public Vector2 AreaSize = new Vector2(100f, 100f); // 草地覆盖范围
    
    [Header("风动画")]
    public float WindStrength = 1f;
    public float WindFrequency = 0.5f;
    public Vector2 WindDirection = new Vector2(1f, 0f);

    private ComputeBuffer _positionBuffer;     // 每根草的位置数据
    private ComputeBuffer _argsBuffer;         // Indirect Draw 参数
    private MaterialPropertyBlock _propBlock;
    
    // Indirect Draw 参数格式（5个 uint）
    private readonly uint[] _args = new uint[5] { 0, 0, 0, 0, 0 };

    private void Start()
    {
        InitBuffers();
        GenerateGrassPositions();
    }

    private void InitBuffers()
    {
        // 初始化 Indirect Draw 参数缓冲区
        _argsBuffer = new ComputeBuffer(1, _args.Length * sizeof(uint), 
            ComputeBufferType.IndirectArguments);
        
        // 设置参数：index count, instance count, start index, base vertex, start instance
        _args[0] = GrassMesh.GetIndexCount(0);   // Mesh 的索引数量
        _args[1] = (uint)GrassCount;              // 实例数量
        _args[2] = GrassMesh.GetIndexStart(0);    // 索引起始位置
        _args[3] = GrassMesh.GetBaseVertex(0);    // 基础顶点偏移
        _args[4] = 0;
        _argsBuffer.SetData(_args);
        
        _propBlock = new MaterialPropertyBlock();
    }

    private void GenerateGrassPositions()
    {
        // 生成草的位置数据（每根草：position.xyz + randomSeed）
        var positions = new Vector4[GrassCount];
        for (int i = 0; i < GrassCount; i++)
        {
            float x = UnityEngine.Random.Range(-AreaSize.x / 2, AreaSize.x / 2);
            float z = UnityEngine.Random.Range(-AreaSize.y / 2, AreaSize.y / 2);
            float y = SampleTerrainHeight(x, z); // 采样地形高度
            float randomSeed = UnityEngine.Random.Range(0f, 1f); // 用于风动画差异化
            
            positions[i] = new Vector4(x, y, z, randomSeed);
        }
        
        // 上传到 GPU ComputeBuffer（stride = Vector4 大小 = 16字节）
        _positionBuffer = new ComputeBuffer(GrassCount, sizeof(float) * 4);
        _positionBuffer.SetData(positions);
        
        // 将 buffer 传给 Shader
        GrassMaterial.SetBuffer("_PositionBuffer", _positionBuffer);
    }

    private void Update()
    {
        // 更新风动画参数（每帧变化）
        _propBlock.SetFloat("_WindStrength", WindStrength);
        _propBlock.SetFloat("_WindFrequency", WindFrequency);
        _propBlock.SetVector("_WindDirection", new Vector4(WindDirection.x, 0, WindDirection.y, 0));
        _propBlock.SetFloat("_Time", Time.time);

        // 提交渲染指令
        Graphics.DrawMeshInstancedIndirect(
            GrassMesh,
            0,                          // submesh index
            GrassMaterial,
            new Bounds(Vector3.zero, new Vector3(AreaSize.x, 50f, AreaSize.y)),
            _argsBuffer,
            0,                          // args buffer offset
            _propBlock,
            UnityEngine.Rendering.ShadowCastingMode.Off, // 草地通常不投影
            false                       // 不接收阴影（可按需开启）
        );
    }

    private float SampleTerrainHeight(float x, float z)
    {
        // 简单实现：用 Physics.Raycast 采样地形高度
        // 实际项目可以预先采样地形数据，避免每次 Raycast
        if (Physics.Raycast(new Vector3(x, 100f, z), Vector3.down, out var hit, 200f, 
            LayerMask.GetMask("Terrain")))
        {
            return hit.point.y;
        }
        return 0f;
    }

    private void OnDestroy()
    {
        // ⚠️ 必须手动释放 ComputeBuffer，否则显存泄漏
        _positionBuffer?.Release();
        _argsBuffer?.Release();
    }
}
```

### 草地 Shader（含风动画）

```hlsl
Shader "Custom/GrassInstanced"
{
    Properties
    {
        _BaseColor ("Base Color", Color) = (0.3, 0.8, 0.2, 1)
        _TipColor ("Tip Color", Color) = (0.8, 0.9, 0.3, 1)
        _GrassHeight ("Grass Height", Range(0.1, 2)) = 0.8
        _WindStrength ("Wind Strength", Float) = 1.0
        _WindFrequency ("Wind Frequency", Float) = 0.5
        _WindDirection ("Wind Direction", Vector) = (1, 0, 0, 0)
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }
        Cull Off // 草地双面显示

        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing  // 启用 GPU Instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            // 从 C# 传入的位置缓冲区
            StructuredBuffer<float4> _PositionBuffer;

            CBUFFER_START(UnityPerMaterial)
                half4 _BaseColor;
                half4 _TipColor;
                float _GrassHeight;
                float _WindStrength;
                float _WindFrequency;
                float4 _WindDirection;
                float _Time;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                uint instanceID : SV_InstanceID;  // 实例 ID，用于访问 PositionBuffer
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                half3 color : TEXCOORD1;
            };

            Varyings vert(Attributes v)
            {
                Varyings o;
                
                // 1. 从缓冲区读取当前实例的位置和随机种子
                float4 grassData = _PositionBuffer[v.instanceID];
                float3 worldPos = grassData.xyz;
                float randomSeed = grassData.w;

                // 2. 计算风动画偏移（只作用于草的顶部，底部固定）
                float verticalFactor = v.uv.y; // uv.y 从底部(0)到顶部(1)
                
                // 基于位置和时间的 sin 波，加入随机种子避免同步摆动
                float windPhase = dot(worldPos.xz, _WindDirection.xz) * _WindFrequency 
                                + _Time * 2.0 
                                + randomSeed * 6.28; // 随机相位偏移
                
                float windOffset = sin(windPhase) * _WindStrength * verticalFactor;
                float3 windDisplacement = _WindDirection.xyz * windOffset;
                
                // 3. 将本地空间顶点变换到世界空间
                // 草的模型默认高度设计为 1，这里缩放到 _GrassHeight
                float3 localPos = v.positionOS.xyz;
                localPos.y *= _GrassHeight;
                
                // 加上世界坐标和风力偏移
                float3 finalWorldPos = worldPos + localPos + windDisplacement;
                
                o.positionCS = TransformWorldToHClip(finalWorldPos);
                o.uv = v.uv;
                
                // 4. 根据高度混合颜色（底部深绿，顶部嫩黄）
                o.color = lerp(_BaseColor.rgb, _TipColor.rgb, v.uv.y);
                
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                return half4(i.color, 1.0);
            }
            ENDHLSL
        }
    }
}
```

---

## GPU 侧视锥剔除（进阶优化）

CPU 遍历 10 万根草做视锥剔除本身就是性能瓶颈。更好的方案是用 **Compute Shader** 在 GPU 上做剔除：

```hlsl
// GrassCulling.compute
#pragma kernel CullGrass

struct GrassData
{
    float3 position;
    float randomSeed;
};

StructuredBuffer<GrassData> _InputBuffer;       // 所有草的数据
AppendStructuredBuffer<GrassData> _VisibleBuffer; // 可见草的输出

float4 _FrustumPlanes[6]; // 6个视锥面（法线+距离）
float3 _CameraPosition;
float _MaxDrawDistance;

bool IsInFrustum(float3 pos)
{
    for (int i = 0; i < 6; i++)
    {
        // 点在平面正侧才可见
        if (dot(_FrustumPlanes[i].xyz, pos) + _FrustumPlanes[i].w < 0)
            return false;
    }
    return true;
}

[numthreads(64, 1, 1)]
void CullGrass(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= (uint)_GrassCount) return;
    
    GrassData grass = _InputBuffer[id.x];
    
    // 距离剔除
    float dist = distance(grass.position, _CameraPosition);
    if (dist > _MaxDrawDistance) return;
    
    // 视锥剔除
    if (!IsInFrustum(grass.position)) return;
    
    // 通过剔除，加入可见列表
    _VisibleBuffer.Append(grass);
}
```

C# 每帧调用：
```csharp
// 重置可见计数
_visibleBuffer.SetCounterValue(0);

// 执行剔除 Compute Shader
_cullingShader.SetBuffer(0, "_InputBuffer", _allGrassBuffer);
_cullingShader.SetBuffer(0, "_VisibleBuffer", _visibleBuffer);
_cullingShader.SetVectorArray("_FrustumPlanes", GetFrustumPlanes(Camera.main));
_cullingShader.Dispatch(0, Mathf.CeilToInt(GrassCount / 64f), 1, 1);

// 把可见草的数量写入 _argsBuffer[1]
ComputeBuffer.CopyCount(_visibleBuffer, _argsBuffer, sizeof(uint));
```

---

## 性能数据对比

以下数据在 PC (GTX 1060) 环境下测试，草地范围 100x100m：

| 方案 | 草地数量 | FPS | Draw Call | CPU耗时/帧 |
|------|---------|-----|----------|-----------|
| 传统 Instantiate | 1,000 | 60 | 1000 | ~8ms |
| DrawMeshInstanced | 10,000 | 60 | ~10 | ~1ms |
| DrawMeshInstancedIndirect | 100,000 | 60 | 1 | ~0.2ms |
| Indirect + GPU剔除 | 500,000 | 60 | 1 | ~0.1ms |

**结论**：Indirect + GPU 剔除是处理大规模草地的唯一可行方案，CPU 耗时几乎为零。

---

## 踩坑记录

1. **ComputeBuffer 必须手动 Release**：MonoBehaviour 销毁时忘记释放会显存泄漏，在编辑器里反复进退 Play 模式会越来越卡

2. **草地 Mesh 要特殊制作**：草的 Mesh 底部顶点 uv.y = 0，顶部 uv.y = 1，这样风动画才能正确只摆动顶部

3. **法线朝向问题**：开 `Cull Off` 双面显示的时候，背面的光照会反向，需要在 Shader 里用 `VFACE` 语义处理背面法线

4. **Shadow 开销**：草地开启投影会使渲染负担翻倍（阴影 Pass + 正常 Pass），移动端通常关闭草地投影

5. **SRP Batcher 兼容**：使用 `DrawMeshInstancedIndirect` 时，材质属性需要通过 `MaterialPropertyBlock` 或 `StructuredBuffer` 传递，普通 `SetFloat` 会破坏合批
