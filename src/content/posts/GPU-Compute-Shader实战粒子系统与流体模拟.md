---
title: GPU Compute Shader实战：粒子系统与流体模拟
published: 2026-03-26
description: 深入讲解Unity Compute Shader的工作原理与编程模型，通过百万级GPU粒子系统、SPH流体模拟、GPU布料模拟三大实战案例，系统掌握ComputeBuffer、线程组调度、数据回读、GPU排序等核心技术，附完整HLSL代码与移动端适配策略。
tags: [Unity, Compute Shader, GPU, 粒子系统, 流体模拟, 图形编程]
category: 渲染与图形
draft: false
encryptedKey:henhaoji123
---

# GPU Compute Shader实战：粒子系统与流体模拟

## 前言

Compute Shader 是现代GPU编程的核心利器。相比传统顶点/片元着色器，Compute Shader 能够直接访问GPU通用计算能力，不受渲染管线束缚。在游戏中，它被用于百万级粒子模拟、流体物理、布料模拟、GPU蒙皮、剔除加速等高性能场景。本文通过三个完整实战案例，带你掌握 Compute Shader 的工程化运用。

---

## 一、Compute Shader 基础原理

### 1.1 GPU 线程层次结构

```
GPU执行层次：
┌─────────────────────────────────────┐
│  Dispatch(groupX, groupY, groupZ)   │ ← CPU发起分派
├─────────────────────────────────────┤
│  Thread Group (numthreads 定义大小) │ ← 共享LDS内存
│  ┌────────────────────────────┐     │
│  │  Thread(x, y, z)           │     │
│  │  SV_GroupThreadID          │     │
│  │  SV_GroupID                │     │
│  │  SV_DispatchThreadID       │     │
│  └────────────────────────────┘     │
└─────────────────────────────────────┘

关键内置语义：
SV_DispatchThreadID = SV_GroupID * numthreads + SV_GroupThreadID
                    = 全局线程ID（最常用）
```

### 1.2 线程组大小选择策略

```hlsl
// 移动端（Mali/Adreno）推荐：64线程
[numthreads(64, 1, 1)]

// PC端通用推荐：256线程
[numthreads(256, 1, 1)]

// 2D图像处理推荐：8x8
[numthreads(8, 8, 1)]

// 3D体积处理推荐：4x4x4
[numthreads(4, 4, 4)]

// 原则：总线程数为warp/wavefront倍数（NVIDIA:32, AMD:64, Mali:4-16）
```

### 1.3 ComputeBuffer 类型对比

| Buffer类型 | HLSL声明 | 适用场景 | 备注 |
|-----------|---------|---------|------|
| Default | `RWStructuredBuffer<T>` | 通用读写 | 最常用 |
| Raw | `RWByteAddressBuffer` | 字节级操作 | 灵活但危险 |
| Append/Consume | `AppendStructuredBuffer<T>` | 动态追加元素 | 需配合Counter |
| Indirect | 用于 DrawMeshInstancedIndirect | 间接绘制参数 | GPU Driven渲染 |

---

## 二、实战一：百万级 GPU 粒子系统

### 2.1 粒子数据结构

```csharp
// C# 端粒子结构体（必须与HLSL完全匹配）
[System.Runtime.InteropServices.StructLayout(
    System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct GPUParticle
{
    public Vector3 position;    // 12 bytes
    public Vector3 velocity;    // 12 bytes
    public Vector4 color;       // 16 bytes
    public float life;          // 4 bytes  当前生命值
    public float maxLife;       // 4 bytes  最大生命值
    public float size;          // 4 bytes
    public uint isAlive;        // 4 bytes  0=dead, 1=alive
    // Total: 56 bytes（需对齐到16字节，padding到64 bytes）
    public Vector3 _padding;    // 12 bytes padding
}
// 结构体大小 = 68 bytes, 建议手动确保16字节对齐
```

### 2.2 Compute Shader 核心逻辑

```hlsl
// ParticleSystem.compute

#pragma kernel CS_Update
#pragma kernel CS_Emit

#include "UnityCG.cginc"

struct Particle
{
    float3 position;
    float3 velocity;
    float4 color;
    float  life;
    float  maxLife;
    float  size;
    uint   isAlive;
    float3 padding;
};

RWStructuredBuffer<Particle> _Particles;
AppendStructuredBuffer<uint> _DeadList;      // 死亡粒子索引池
ConsumeStructuredBuffer<uint> _EmitList;     // 待发射索引池

// 全局参数
float  _DeltaTime;
float3 _Gravity;
float3 _EmitPosition;
float3 _EmitVelocityMin;
float3 _EmitVelocityMax;
float  _LifeMin;
float  _LifeMax;
float4 _ColorStart;
float4 _ColorEnd;
float  _SizeStart;
float  _SizeEnd;
uint   _EmitCount;
float  _Time;

// 简易伪随机
float Rand(float2 seed)
{
    return frac(sin(dot(seed, float2(12.9898, 78.233))) * 43758.5453);
}

float3 RandInRange(float3 minV, float3 maxV, float2 seed)
{
    return float3(
        lerp(minV.x, maxV.x, Rand(seed + float2(0.1, 0.2))),
        lerp(minV.y, maxV.y, Rand(seed + float2(0.3, 0.4))),
        lerp(minV.z, maxV.z, Rand(seed + float2(0.5, 0.6)))
    );
}

// Kernel 1：更新存活粒子
[numthreads(256, 1, 1)]
void CS_Update(uint3 id : SV_DispatchThreadID)
{
    uint index = id.x;
    Particle p = _Particles[index];
    
    if (p.isAlive == 0) return;
    
    // 更新生命值
    p.life -= _DeltaTime;
    
    if (p.life <= 0)
    {
        p.isAlive = 0;
        _DeadList.Append(index); // 回收到死亡池
        _Particles[index] = p;
        return;
    }
    
    // 物理更新
    p.velocity += _Gravity * _DeltaTime;
    p.position += p.velocity * _DeltaTime;
    
    // 生命比例插值颜色和大小
    float t = 1.0 - (p.life / p.maxLife);
    p.color = lerp(_ColorStart, _ColorEnd, t);
    p.size  = lerp(_SizeStart, _SizeEnd, t);
    
    // 简单地面碰撞
    if (p.position.y < 0.0)
    {
        p.position.y = 0.0;
        p.velocity.y = -p.velocity.y * 0.5; // 弹跳衰减
        p.velocity.xz *= 0.85;              // 地面摩擦
    }
    
    _Particles[index] = p;
}

// Kernel 2：发射新粒子
[numthreads(64, 1, 1)]
void CS_Emit(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= _EmitCount) return;
    
    // 从死亡池取出一个索引
    uint index = _EmitList.Consume();
    
    float2 seed = float2((float)index / 1000000.0, _Time + id.x * 0.01);
    
    Particle p;
    p.position = _EmitPosition + RandInRange(float3(-0.5, 0, -0.5), float3(0.5, 0, 0.5), seed);
    p.velocity = RandInRange(_EmitVelocityMin, _EmitVelocityMax, seed + float2(1.0, 2.0));
    p.maxLife  = lerp(_LifeMin, _LifeMax, Rand(seed + float2(3.0, 4.0)));
    p.life     = p.maxLife;
    p.color    = _ColorStart;
    p.size     = _SizeStart;
    p.isAlive  = 1;
    p.padding  = float3(0, 0, 0);
    
    _Particles[index] = p;
}
```

### 2.3 C# 管理器

```csharp
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(MeshRenderer))]
public class GPUParticleSystem : MonoBehaviour
{
    [Header("粒子配置")]
    [SerializeField] private ComputeShader _computeShader;
    [SerializeField] private Shader _renderShader;
    [SerializeField] private int _maxParticles = 1_000_000;
    [SerializeField] private int _emitPerSecond = 50000;
    
    [Header("物理")]
    [SerializeField] private Vector3 _gravity = new Vector3(0, -9.8f, 0);
    [SerializeField] private Vector3 _emitVelocityMin = new Vector3(-2, 5, -2);
    [SerializeField] private Vector3 _emitVelocityMax = new Vector3(2, 15, 2);
    
    [Header("外观")]
    [SerializeField] private float _lifeMin = 1f;
    [SerializeField] private float _lifeMax = 5f;
    [SerializeField] private Color _colorStart = Color.yellow;
    [SerializeField] private Color _colorEnd = Color.red;
    [SerializeField] [Range(0.01f, 0.5f)] private float _sizeStart = 0.1f;
    [SerializeField] [Range(0.01f, 0.5f)] private float _sizeEnd = 0.02f;
    
    // GPU资源
    private ComputeBuffer _particleBuffer;
    private ComputeBuffer _deadListBuffer;
    private ComputeBuffer _aliveCountBuffer;  // 用于间接绘制
    private ComputeBuffer _drawArgsBuffer;
    
    // Kernel索引
    private int _kernelUpdate;
    private int _kernelEmit;
    
    // 渲染材质
    private Material _renderMaterial;
    private Mesh _particleMesh;
    
    // 状态
    private float _emitAccumulator;
    private uint _aliveCount;
    
    private void Start()
    {
        InitializeBuffers();
        InitializeShaders();
        InitializeParticlePool();
    }
    
    private void InitializeBuffers()
    {
        int stride = System.Runtime.InteropServices.Marshal.SizeOf(typeof(GPUParticle));
        _particleBuffer = new ComputeBuffer(_maxParticles, stride);
        
        // 死亡列表：AppendBuffer 需要额外stride=4，count用Counter
        _deadListBuffer = new ComputeBuffer(_maxParticles, sizeof(uint),
            ComputeBufferType.Append);
        _deadListBuffer.SetCounterValue(0);
        
        // 间接绘制参数：[indexCount, instanceCount, startIndex, baseVertex, startInstance]
        _drawArgsBuffer = new ComputeBuffer(5, sizeof(uint), ComputeBufferType.IndirectArguments);
        _drawArgsBuffer.SetData(new uint[] { 6, 0, 0, 0, 0 }); // 6个索引（2三角形=1面片）
    }
    
    private void InitializeShaders()
    {
        _kernelUpdate = _computeShader.FindKernel("CS_Update");
        _kernelEmit = _computeShader.FindKernel("CS_Emit");
        
        _computeShader.SetBuffer(_kernelUpdate, "_Particles", _particleBuffer);
        _computeShader.SetBuffer(_kernelUpdate, "_DeadList", _deadListBuffer);
        
        _renderMaterial = new Material(_renderShader);
        _renderMaterial.SetBuffer("_Particles", _particleBuffer);
        
        _particleMesh = CreateQuadMesh();
    }
    
    private void InitializeParticlePool()
    {
        // 初始化：所有粒子入死亡池
        var initParticles = new GPUParticle[_maxParticles];
        _particleBuffer.SetData(initParticles);
        
        // 向死亡列表填充所有索引
        var allIndices = new uint[_maxParticles];
        for (uint i = 0; i < _maxParticles; i++) allIndices[i] = i;
        _deadListBuffer.SetData(allIndices);
        _deadListBuffer.SetCounterValue((uint)_maxParticles);
    }
    
    private void Update()
    {
        float dt = Time.deltaTime;
        
        // 1. 更新所有粒子
        _computeShader.SetFloat("_DeltaTime", dt);
        _computeShader.SetFloat("_Time", Time.time);
        _computeShader.SetVector("_Gravity", _gravity);
        _computeShader.SetVector("_ColorStart", (Vector4)_colorStart);
        _computeShader.SetVector("_ColorEnd", (Vector4)_colorEnd);
        _computeShader.SetFloat("_SizeStart", _sizeStart);
        _computeShader.SetFloat("_SizeEnd", _sizeEnd);
        
        int updateGroups = Mathf.CeilToInt((float)_maxParticles / 256);
        _computeShader.Dispatch(_kernelUpdate, updateGroups, 1, 1);
        
        // 2. 发射新粒子
        _emitAccumulator += _emitPerSecond * dt;
        int emitCount = Mathf.FloorToInt(_emitAccumulator);
        _emitAccumulator -= emitCount;
        
        if (emitCount > 0)
        {
            // 不超过死亡池剩余数量
            ComputeBuffer.CopyCount(_deadListBuffer, _aliveCountBuffer, 0);
            // 实际项目中通过 GetData 或 AsyncGPUReadback 获取死亡数量来限制 emitCount
            
            _computeShader.SetBuffer(_kernelEmit, "_Particles", _particleBuffer);
            _computeShader.SetBuffer(_kernelEmit, "_EmitList", _deadListBuffer);
            _computeShader.SetVector("_EmitPosition", transform.position);
            _computeShader.SetVector("_EmitVelocityMin", _emitVelocityMin);
            _computeShader.SetVector("_EmitVelocityMax", _emitVelocityMax);
            _computeShader.SetFloat("_LifeMin", _lifeMin);
            _computeShader.SetFloat("_LifeMax", _lifeMax);
            _computeShader.SetInt("_EmitCount", emitCount);
            
            int emitGroups = Mathf.CeilToInt((float)emitCount / 64);
            _computeShader.Dispatch(_kernelEmit, emitGroups, 1, 1);
        }
        
        // 3. 间接绘制（GPU Driven，不回读数据到CPU）
        DrawParticles();
    }
    
    private void DrawParticles()
    {
        // 更新间接绘制参数中的 instanceCount
        // 实际中使用 Alive Counter Buffer 作为参数
        _renderMaterial.SetBuffer("_Particles", _particleBuffer);
        
        // 使用 DrawMeshInstancedIndirect 避免 CPU/GPU 同步
        Graphics.DrawMeshInstancedIndirect(
            _particleMesh,
            0,
            _renderMaterial,
            new Bounds(Vector3.zero, Vector3.one * 1000f),
            _drawArgsBuffer
        );
    }
    
    private Mesh CreateQuadMesh()
    {
        var mesh = new Mesh();
        mesh.vertices = new Vector3[]
        {
            new Vector3(-0.5f, -0.5f, 0),
            new Vector3( 0.5f, -0.5f, 0),
            new Vector3( 0.5f,  0.5f, 0),
            new Vector3(-0.5f,  0.5f, 0)
        };
        mesh.uv = new Vector2[]
        {
            new Vector2(0, 0), new Vector2(1, 0),
            new Vector2(1, 1), new Vector2(0, 1)
        };
        mesh.triangles = new int[] { 0, 1, 2, 0, 2, 3 };
        return mesh;
    }
    
    private void OnDestroy()
    {
        _particleBuffer?.Release();
        _deadListBuffer?.Release();
        _aliveCountBuffer?.Release();
        _drawArgsBuffer?.Release();
    }
}
```

---

## 三、实战二：SPH 流体模拟

### 3.1 SPH算法原理简述

SPH（Smoothed Particle Hydrodynamics，光滑粒子流体动力学）通过离散粒子来近似连续流体：

- **密度估计**：ρᵢ = Σⱼ mⱼ · W(rᵢⱼ, h)
- **压力计算**：P = k(ρ - ρ₀)
- **压力梯度**：∇P = Σⱼ mⱼ(Pᵢ/ρᵢ² + Pⱼ/ρⱼ²)∇W
- **粘性力**：μ·Σⱼ mⱼ/ρⱼ · (vⱼ-vᵢ) · ∇²W

### 3.2 SPH Compute Shader

```hlsl
// SPH.compute

#pragma kernel CS_ComputeDensityPressure
#pragma kernel CS_ComputeForces
#pragma kernel CS_Integrate

struct SPHParticle
{
    float3 position;
    float3 velocity;
    float3 force;
    float  density;
    float  pressure;
    float3 _pad;
};

RWStructuredBuffer<SPHParticle> _Particles;
uint   _ParticleCount;
float  _DeltaTime;
float  _H;          // 光滑核半径
float  _H2;         // H^2
float  _Mass;       // 粒子质量
float  _RestDensity;
float  _GasConstant;
float  _Viscosity;
float3 _Gravity;
float3 _BoundsMin;
float3 _BoundsMax;

// Poly6 核函数（密度估计）
float W_Poly6(float r2, float h)
{
    if (r2 >= h * h) return 0;
    float c = h * h - r2;
    return (315.0 / (64.0 * 3.14159265 * pow(h, 9.0))) * c * c * c;
}

// Spiky 核函数梯度（压力）
float3 W_SpikyGrad(float3 r, float rLen, float h)
{
    if (rLen >= h || rLen < 0.0001) return float3(0,0,0);
    float c = h - rLen;
    return (-45.0 / (3.14159265 * pow(h, 6.0))) * c * c * (r / rLen);
}

// Viscosity 核函数拉普拉斯（粘性）
float W_ViscosityLap(float rLen, float h)
{
    if (rLen >= h) return 0;
    return (45.0 / (3.14159265 * pow(h, 6.0))) * (h - rLen);
}

// Kernel 1：计算密度和压力
[numthreads(256, 1, 1)]
void CS_ComputeDensityPressure(uint3 id : SV_DispatchThreadID)
{
    uint i = id.x;
    if (i >= _ParticleCount) return;
    
    float3 pi = _Particles[i].position;
    float density = 0.0;
    
    // 暴力O(N²)邻域搜索（小规模可用，大规模需空间哈希）
    for (uint j = 0; j < _ParticleCount; j++)
    {
        float3 rij = pi - _Particles[j].position;
        float r2 = dot(rij, rij);
        density += _Mass * W_Poly6(r2, _H);
    }
    
    _Particles[i].density  = density;
    _Particles[i].pressure = max(0.0, _GasConstant * (density - _RestDensity));
}

// Kernel 2：计算受力
[numthreads(256, 1, 1)]
void CS_ComputeForces(uint3 id : SV_DispatchThreadID)
{
    uint i = id.x;
    if (i >= _ParticleCount) return;
    
    SPHParticle pi = _Particles[i];
    float3 pressureForce  = float3(0, 0, 0);
    float3 viscosityForce = float3(0, 0, 0);
    
    for (uint j = 0; j < _ParticleCount; j++)
    {
        if (i == j) continue;
        
        SPHParticle pj = _Particles[j];
        float3 rij = pi.position - pj.position;
        float r = length(rij);
        
        if (r >= _H) continue;
        
        // 压力梯度力
        float pressureTerm = (pi.pressure / (pi.density * pi.density)) +
                             (pj.pressure / (pj.density * pj.density));
        pressureForce += -_Mass * pressureTerm * W_SpikyGrad(rij, r, _H);
        
        // 粘性力
        viscosityForce += _Viscosity * _Mass *
                          ((pj.velocity - pi.velocity) / pj.density) *
                          W_ViscosityLap(r, _H);
    }
    
    _Particles[i].force = pressureForce + viscosityForce + _Gravity * pi.density;
}

// Kernel 3：积分位置速度
[numthreads(256, 1, 1)]
void CS_Integrate(uint3 id : SV_DispatchThreadID)
{
    uint i = id.x;
    if (i >= _ParticleCount) return;
    
    SPHParticle p = _Particles[i];
    
    // 半隐式Euler积分（更稳定）
    float3 acc = p.force / p.density;
    p.velocity += acc * _DeltaTime;
    p.position += p.velocity * _DeltaTime;
    
    // 边界碰撞（软边界，避免粒子穿透）
    float damping = 0.5;
    if (p.position.x < _BoundsMin.x) { p.position.x = _BoundsMin.x; p.velocity.x *= -damping; }
    if (p.position.x > _BoundsMax.x) { p.position.x = _BoundsMax.x; p.velocity.x *= -damping; }
    if (p.position.y < _BoundsMin.y) { p.position.y = _BoundsMin.y; p.velocity.y *= -damping; }
    if (p.position.y > _BoundsMax.y) { p.position.y = _BoundsMax.y; p.velocity.y *= -damping; }
    if (p.position.z < _BoundsMin.z) { p.position.z = _BoundsMin.z; p.velocity.z *= -damping; }
    if (p.position.z > _BoundsMax.z) { p.position.z = _BoundsMax.z; p.velocity.z *= -damping; }
    
    _Particles[i] = p;
}
```

### 3.3 空间哈希优化邻域搜索

```hlsl
// SpatialHash.compute - O(N²) → O(N) 优化

RWStructuredBuffer<uint2> _HashTable;   // [hash, particleIndex]
RWStructuredBuffer<uint>  _CellStart;   // 每个Cell起始索引
uint _TableSize;
float _CellSize;

uint HashCell(int3 cell)
{
    // 位运算哈希，避免除法
    return ((uint)(cell.x * 92837111) ^
            (uint)(cell.y * 689287499) ^
            (uint)(cell.z * 283923481)) % _TableSize;
}

int3 WorldToCell(float3 pos)
{
    return int3(floor(pos / _CellSize));
}

// 查找邻居时只搜索 27 个相邻Cell
void ForEachNeighbor(uint i, float3 pos, inout float density)
{
    int3 baseCell = WorldToCell(pos);
    
    for (int dx = -1; dx <= 1; dx++)
    for (int dy = -1; dy <= 1; dy++)
    for (int dz = -1; dz <= 1; dz++)
    {
        int3 cell = baseCell + int3(dx, dy, dz);
        uint hash = HashCell(cell);
        
        uint start = _CellStart[hash];
        uint end   = _CellStart[hash + 1];
        
        for (uint k = start; k < end; k++)
        {
            uint j = _HashTable[k].y;
            float3 rij = pos - _Particles[j].position;
            float r2 = dot(rij, rij);
            density += _Mass * W_Poly6(r2, _H);
        }
    }
}
```

---

## 四、实战三：GPU 布料模拟

```hlsl
// ClothSimulation.compute

#pragma kernel CS_PBD_Predict
#pragma kernel CS_PBD_SolveStretch
#pragma kernel CS_PBD_SolveBend
#pragma kernel CS_PBD_Finalize

struct ClothVertex
{
    float3 position;
    float3 prevPosition;
    float3 velocity;
    float  invMass;     // 0 = 固定点
    float3 _pad;
};

struct StretchConstraint
{
    uint   i, j;        // 两端粒子索引
    float  restLength;
    float  stiffness;
};

RWStructuredBuffer<ClothVertex>     _Vertices;
StructuredBuffer<StretchConstraint> _StretchConstraints;
uint  _VertexCount;
uint  _ConstraintCount;
float _DeltaTime;
float3 _Gravity;
float _Damping;         // 0.98

// PBD 步骤1：预测位置
[numthreads(256, 1, 1)]
void CS_PBD_Predict(uint3 id : SV_DispatchThreadID)
{
    uint i = id.x;
    if (i >= _VertexCount) return;
    
    ClothVertex v = _Vertices[i];
    if (v.invMass == 0) return; // 固定点不移动
    
    // 保存上一帧位置
    v.prevPosition = v.position;
    
    // 外力（重力）
    float3 acc = _Gravity;
    v.velocity += acc * _DeltaTime;
    v.velocity *= _Damping;
    
    // 预测新位置
    v.position += v.velocity * _DeltaTime;
    
    _Vertices[i] = v;
}

// PBD 步骤2：解算伸缩约束（多次迭代）
[numthreads(256, 1, 1)]
void CS_PBD_SolveStretch(uint3 id : SV_DispatchThreadID)
{
    uint ci = id.x;
    if (ci >= _ConstraintCount) return;
    
    StretchConstraint c = _StretchConstraints[ci];
    
    ClothVertex vi = _Vertices[c.i];
    ClothVertex vj = _Vertices[c.j];
    
    float3 delta = vi.position - vj.position;
    float dist = length(delta);
    
    if (dist < 0.0001) return;
    
    float constraint = (dist - c.restLength) / dist;
    float3 correction = c.stiffness * constraint * delta;
    
    float wSum = vi.invMass + vj.invMass;
    if (wSum == 0) return;
    
    // 根据质量分配修正量（原子操作在HLSL中需谨慎）
    // 注意：直接写可能有竞争，实际需按颜色图着色并行解算
    if (vi.invMass > 0)
    {
        vi.position -= (vi.invMass / wSum) * correction;
        _Vertices[c.i] = vi;
    }
    if (vj.invMass > 0)
    {
        vj.position += (vj.invMass / wSum) * correction;
        _Vertices[c.j] = vj;
    }
}

// PBD 步骤3：最终化速度
[numthreads(256, 1, 1)]
void CS_PBD_Finalize(uint3 id : SV_DispatchThreadID)
{
    uint i = id.x;
    if (i >= _VertexCount) return;
    
    ClothVertex v = _Vertices[i];
    if (v.invMass == 0) return;
    
    // 由位置差更新速度
    v.velocity = (v.position - v.prevPosition) / _DeltaTime;
    _Vertices[i] = v;
}
```

---

## 五、异步 GPU 数据回读

```csharp
// 避免 GetData() 阻塞 GPU-CPU 同步
using UnityEngine.Rendering;

public class AsyncGPUReadbackExample : MonoBehaviour
{
    private ComputeBuffer _buffer;
    private GPUParticle[] _cpuData;
    private bool _readbackPending;
    
    private void RequestReadback()
    {
        if (_readbackPending) return;
        _readbackPending = true;
        
        // 异步请求，不阻塞主线程
        AsyncGPUReadback.Request(_buffer, OnReadbackComplete);
    }
    
    private void OnReadbackComplete(AsyncGPUReadbackRequest request)
    {
        _readbackPending = false;
        
        if (request.hasError)
        {
            Debug.LogError("GPU Readback Error!");
            return;
        }
        
        // 数据已准备好，在主线程安全访问
        _cpuData = request.GetData<GPUParticle>().ToArray();
        ProcessCPUData(_cpuData);
    }
    
    private void ProcessCPUData(GPUParticle[] data)
    {
        int aliveCount = 0;
        foreach (var p in data)
            if (p.isAlive > 0) aliveCount++;
        
        Debug.Log($"存活粒子: {aliveCount}");
    }
}
```

---

## 六、移动端适配策略

### 6.1 平台支持检测

```csharp
public static class ComputeShaderSupport
{
    public static bool IsSupported()
    {
        return SystemInfo.supportsComputeShaders;
    }
    
    public static bool SupportsFloatTexture()
    {
        return SystemInfo.SupportsTextureFormat(TextureFormat.RGBAFloat);
    }
    
    public static int GetRecommendedThreadGroupSize()
    {
        // 根据GPU类型调整
        string gpuVendor = SystemInfo.graphicsDeviceName.ToLower();
        if (gpuVendor.Contains("mali"))
            return 64;   // Mali 推荐64
        if (gpuVendor.Contains("adreno"))
            return 128;  // Adreno 推荐128
        if (gpuVendor.Contains("apple"))
            return 64;   // Apple GPU 推荐64
        return 256;      // PC默认256
    }
    
    // 降级回退策略
    public static bool ShouldUseCPUFallback()
    {
        // OpenGL ES 3.1+ 才支持 Compute Shader
        return !SystemInfo.supportsComputeShaders ||
               SystemInfo.graphicsShaderLevel < 45;
    }
}
```

### 6.2 移动端性能Tips

| 场景 | PC策略 | 移动端策略 |
|-----|--------|-----------|
| 粒子数量 | 100万+ | 1-5万（开启LOD） |
| 线程组大小 | 256 | 64 |
| Buffer读写 | 随意 | 减少随机访问，提高内存局部性 |
| SPH邻域 | 空间哈希 | 网格限制粒子数 |
| Buffer精度 | float | half（注意精度损失） |
| 帧率保障 | 60fps | 使用 TemporalAA + 降频模拟（2帧更新1次） |

---

## 七、最佳实践总结

```
Compute Shader 工程规范：

✅ 正确做法：
  - 使用 DrawMeshInstancedIndirect 避免 CPU-GPU 同步
  - 用 AsyncGPUReadback 代替 GetData()
  - 线程组大小选 32/64/128/256 的倍数
  - 减少 UAV 写入冲突（颜色图着色 / 无冲突算法）
  - StructuredBuffer 用于结构体，RawBuffer 用于字节流
  - 在 OnDestroy 中释放所有 ComputeBuffer

❌ 常见错误：
  - GetData() 导致 CPU/GPU 强制同步，造成卡帧
  - 线程组太小（1-8）导致 GPU 利用率低
  - 忘记对 AppendBuffer 调用 SetCounterValue(0) 重置计数
  - 结构体未对齐到16字节导致数据错乱
  - 在 Mobile 平台未检测 Compute Shader 支持就使用
```

Compute Shader 打开了 GPU 通用计算的大门。随着移动端 GPU 的不断进化，越来越多的游戏效果和物理模拟正在从 CPU 迁移到 GPU 端，这是每一位游戏图形工程师都应深入掌握的核心技能。
