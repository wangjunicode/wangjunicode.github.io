---
title: Unity DOTS 深度学习笔记：ECS + Burst + Job System
published: 2023-09-12
description: "系统梳理 Unity DOTS 技术栈：在完整 ECS 架构介绍基础上，深入讲解 Burst Compiler 的编译原理与使用方式、Job System 的多线程安全并行模型，通过1万个单位移动的性能对比数据说明 DOTS 的实际收益，并分析 DOTS 适用场景、不适用场景以及与传统 MonoBehaviour 的混合使用方案。"
tags: [Unity, DOTS, ECS, 性能优化]
category: Unity开发
draft: false
---

最早接触 ECS 思想是从 Unity 的宣传视频开始的——一万个僵尸在屏幕上流畅跑动，对比传统方案的几十个僵尸卡成 PPT，震撼程度不亚于第一次看到 GPU Instancing。这几年我系统学习了 DOTS 技术栈，有很多实践感悟，整理成这篇文章。

---

## 前言

近期想从更深层次上学习 ECS，之前一直停留在浅层次的编码模式（即"ECS 意识流"），没有真正了解 ECS 的内部原理。Unity 目前在维护一套以 ECS 为架构开发的 DOTS 技术栈，非常值得深入学习。

---

## ECS 架构详解

### 什么是 ECS

ECS 即实体（Entity）、组件（Component）、系统（System）：

- **Entity**：游戏中的事物，但在 ECS 中它只是一个 ID（一个整数），本身不携带数据
- **Component**：与 Entity 相关联的纯数据（struct），不包含任何逻辑
- **System**：处理特定 Component 组合的无状态逻辑，负责把 Component 数据从当前帧状态转换到下一帧状态

这种数据与逻辑分离的设计，是面向数据设计（DOD）与传统面向对象（OOP）的核心区别之一。

```csharp
// ECS 数据定义示例
using Unity.Entities;
using Unity.Mathematics;

// Component：纯数据
public struct Position : IComponentData
{
    public float3 Value;
}

public struct Velocity : IComponentData
{
    public float3 Value;
}

public struct Health : IComponentData
{
    public float Current;
    public float Max;
}

// System：处理具有 Position 和 Velocity 的所有 Entity
public partial class MoveSystem : SystemBase
{
    protected override void OnUpdate()
    {
        float deltaTime = SystemAPI.Time.DeltaTime;

        // Entities.ForEach 会自动并行处理所有匹配的 Entity
        Entities
            .WithAll<Position, Velocity>()
            .ForEach((ref Position pos, in Velocity vel) =>
            {
                pos.Value += vel.Value * deltaTime;
            })
            .ScheduleParallel(); // 多线程并行执行
    }
}
```

### ECS 为什么快：CPU 缓存的秘密

#### 前置知识：缓存命中率

- CPU 处理数据的速度极快，但从内存（RAM）读取数据相对很慢（约 200-300 个时钟周期）
- 为此 CPU 有 L1/L2/L3 三级高速缓存（纳秒级延迟）
- **Cache Miss**：CPU 请求的数据不在缓存中，需要从内存加载，这是主要的性能瓶颈

#### OOP 的缓存问题

```csharp
// 传统 OOP：GameObject + MonoBehaviour
public class Enemy : MonoBehaviour
{
    public Vector3 position;      // 12字节，用于移动
    public float health;          // 4字节，用于扣血
    public Sprite sprite;         // 8字节（引用），渲染用
    public AudioClip hitSound;    // 8字节（引用），音效用
    public string displayName;    // 8字节（引用），UI 用
    public List<Skill> skills;    // 8字节（引用），技能系统用
    // ... 大量其他字段
}
```

当 `MoveSystem` 只需要更新 `position` 时，CPU 却不得不把整个 `Enemy` 对象（可能 200+ 字节）加载进缓存。1万个敌人 = 200万字节需要从内存加载，Cache Miss 极高。

#### ECS 的缓存优化

ECS 中，相同类型的 Component 在内存中是**连续存储**的（通过 Archetype Chunk 机制）：

```
传统 OOP 内存布局：
[Enemy0_全部字段] [Enemy1_全部字段] [Enemy2_全部字段] ...
  (200字节)         (200字节)         (200字节)

ECS Position 组件内存布局：
[pos0][pos1][pos2][pos3][pos4]...[pos9999]
  (12B)  (12B)  (12B)  ...
```

`MoveSystem` 运行时，CPU 一次性把连续的 Position 数据块加载进缓存，几乎不会 Cache Miss。SIMD（单指令多数据）优化也能在这种连续数据上发挥最大效果。

### Archetype 和 Chunk：ECS 内存管理

Unity DOTS 用 **Archetype** 来管理具有相同 Component 组合的 Entity：

```
Archetype A：[Position + Velocity]          → Chunk（16KB）存放 N 个 Entity
Archetype B：[Position + Velocity + Health] → Chunk（16KB）存放 M 个 Entity
Archetype C：[Position + RenderMesh]        → Chunk（16KB）存放 K 个 Entity
```

当 Entity 添加/移除 Component 时（如从 Archetype A 变为 B），该 Entity 会从一个 Chunk 移动到另一个 Chunk。这是 DOTS 编程中需要特别注意的"结构性改变"（Structural Change）。

---

## Burst Compiler：让 C# 跑出 C++ 的速度

### 为什么需要 Burst

Unity 的传统 C# 代码运行在 Mono 或 IL2CPP 上，虽然 IL2CPP 已经比 Mono 快很多，但对 SIMD 等现代 CPU 特性的利用率不高。

Burst 的解法：**把 IL/.NET 字节码用 LLVM 直接编译成高度优化的原生机器码**，同时利用 CPU 的 SIMD 指令进行向量化。

### 性能对比

同样的数学计算（100万次 float4x4 矩阵乘法）：

| 运行方式 | 耗时 |
|---------|------|
| Mono | ~180ms |
| IL2CPP | ~45ms |
| Burst (单线程) | ~8ms |
| Burst + Jobs (多线程) | ~1.5ms |

Burst 单线程就能比 IL2CPP 快 5 倍以上，配合 Job System 多线程还能再乘以 CPU 核心数。

### 如何使用 Burst

```csharp
using Unity.Burst;
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;

// ✅ 用 [BurstCompile] 标记 struct Job，Burst 会自动编译它
[BurstCompile]
public struct MoveJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> Velocities;
    [ReadOnly] public float DeltaTime;
    
    public NativeArray<float3> Positions; // 读写

    public void Execute(int index)
    {
        // 这段代码会被 Burst 编译为 SIMD 优化的机器码
        Positions[index] += Velocities[index] * DeltaTime;
    }
}
```

#### Burst 的限制（重要！）

Burst 只能编译**受限的 C# 子集**：
- ❌ 不支持引用类型（class）——只能用 struct
- ❌ 不支持托管内存（new 关键字分配对象）——只能用 NativeContainer
- ❌ 不支持虚函数调用
- ❌ 不支持 try/catch/finally
- ✅ 支持 `Unity.Mathematics` 数学库（SIMD 友好）
- ✅ 支持 `NativeArray`、`NativeList` 等非托管集合

---

## Job System：安全的多线程并行

### 为什么需要 Job System

直接用 C# `Thread` 或 `Task` 在 Unity 里写多线程很危险：Unity API 不是线程安全的，访问 `GameObject`、`Transform` 等从非主线程崩溃。

Job System 提供了一套**安全的多线程框架**：
- 通过 `NativeContainer`（NativeArray 等）在线程间共享数据，并自动检测竞争条件
- Job 之间通过 `JobHandle` 声明依赖关系，系统自动调度执行顺序
- 和 Unity 的 Native Job System 共享线程池，避免创建多于 CPU 核心数的线程

### 三种 Job 类型

```csharp
// 1. IJob：单次执行
[BurstCompile]
public struct SingleJob : IJob
{
    public NativeArray<int> Data;
    
    public void Execute()
    {
        // 在子线程执行一次
        for (int i = 0; i < Data.Length; i++)
            Data[i] *= 2;
    }
}

// 2. IJobParallelFor：并行处理数组，每个元素独立
[BurstCompile]
public struct ParallelJob : IJobParallelFor
{
    public NativeArray<float3> Positions;
    [ReadOnly] public float DeltaTime;
    
    public void Execute(int index)
    {
        // 每个 index 在独立线程上并行执行
        Positions[index] += new float3(1f, 0f, 0f) * DeltaTime;
    }
}

// 3. IJobParallelForTransform：并行处理 Transform（特殊优化）
[BurstCompile]
public struct MoveTransformJob : IJobParallelForTransform
{
    [ReadOnly] public NativeArray<float3> Velocities;
    public float DeltaTime;
    
    public void Execute(int index, TransformAccess transform)
    {
        transform.position += (Vector3)(Velocities[index] * DeltaTime);
    }
}
```

### Job 调度示例

```csharp
public class MoveController : MonoBehaviour
{
    private NativeArray<float3> _positions;
    private NativeArray<float3> _velocities;
    private JobHandle _jobHandle;

    private void Start()
    {
        int count = 10000;
        _positions = new NativeArray<float3>(count, Allocator.Persistent);
        _velocities = new NativeArray<float3>(count, Allocator.Persistent);
        
        // 初始化数据
        for (int i = 0; i < count; i++)
        {
            _positions[i] = new float3(i * 0.1f, 0, 0);
            _velocities[i] = new float3(1f, 0, 0);
        }
    }

    private void Update()
    {
        // 1. 配置 Job
        var job = new ParallelJob
        {
            Positions = _positions,
            DeltaTime = Time.deltaTime
        };

        // 2. 调度 Job（异步，返回 JobHandle）
        // innerloopBatchCount：每个线程批量处理的元素数，建议 32-128
        _jobHandle = job.Schedule(_positions.Length, 64);
        
        // ⚠️ 这里 Job 已经在子线程开始运行了！
        // 主线程可以继续做其他事情...
    }

    private void LateUpdate()
    {
        // 3. 等待 Job 完成（确保本帧使用结果时已经计算完毕）
        _jobHandle.Complete();
        
        // 4. 使用 Job 计算的结果
        // _positions 现在已经更新完毕
    }

    private void OnDestroy()
    {
        _jobHandle.Complete(); // 确保 Job 不再运行后再释放
        _positions.Dispose();
        _velocities.Dispose();
    }
}
```

---

## 性能对比：1万个单位移动

在 Unity 2022，PC（8核 i7，16GB），1万个单位做简单的位置更新测试：

| 方案 | Update 耗时 | GC Alloc/帧 | 备注 |
|------|-----------|------------|------|
| MonoBehaviour（脚本各自更新）| ~8ms | ~0 | 单线程，无 GC |
| Job System（单线程）| ~1.2ms | 0 | Burst 加速 |
| Job System（多线程）| ~0.3ms | 0 | 8核并行 |
| ECS + Burst + Jobs | ~0.15ms | 0 | 最优，缓存+SIMD+并行 |

**结论**：ECS + DOTS 在大量同类型单位的场景下，比传统方案快 **50倍以上**。

---

## DOTS 适用 vs 不适用场景

### ✅ 适用场景

- **大量同类型单位**：1000+ 敌人/子弹/粒子，同类型操作
- **纯数值计算密集**：物理模拟、路径规划（大规模寻路）、流体模拟
- **渲染优化**：配合 Entities Graphics（原 Hybrid Renderer）批量渲染
- **弱耦合模块**：几乎不需要和其他系统交互的独立模块

### ❌ 不适用场景

- **复杂的引用关系网**：技能系统、剧情系统，大量对象相互引用
- **频繁的结构性改变**：每帧大量 Entity 添加/移除 Component（破坏 Chunk 连续性）
- **UI 系统**：UGUI 不支持 ECS，Structural Change 开销抵消性能收益
- **网络同步**：帧同步/状态同步的复杂逻辑，不适合 ECS 数据无引用的限制

### ECS 在实践中真有那么神吗？

说实话，我的实践结论是：**理想很美好，现实需要取舍**。

真正启用 DOTS 面临的挑战：
1. **内存管理**：必须手动管理 NativeContainer 的生命周期，Allocator 选择错误直接崩溃
2. **编码规范**：Component 不能有引用类型，写法和传统 OOP 完全不同，团队学习曲线陡
3. **调试困难**：ECS 调试体验比传统 MonoBehaviour 差很多，Entity Debugger 还不够成熟
4. **生态尚未完善**：很多插件不支持 DOTS，物理系统（Havok）、动画系统（仍在发展）

我的建议是**按守望先锋团队的思路**：大架构用 ECS（寻路、渲染批次、碰撞检测），业务逻辑（技能、剧情、UI）用传统 OOP，两套系统通过桥接层通信。不要追求"纯 ECS"，那会让项目陷入过度设计。

---

## 与传统 Unity 混用（Hybrid ECS）

```csharp
// 在传统 MonoBehaviour 中使用 Job System（不需要完整 ECS）
public class BulletManager : MonoBehaviour
{
    [SerializeField] private int BulletCount = 5000;

    private TransformAccessArray _transformArray;
    private NativeArray<float3> _velocities;
    private JobHandle _moveJobHandle;

    private void Start()
    {
        var bullets = new Transform[BulletCount];
        _velocities = new NativeArray<float3>(BulletCount, Allocator.Persistent);

        for (int i = 0; i < BulletCount; i++)
        {
            bullets[i] = CreateBullet(i);
            _velocities[i] = new float3(0, 0, 10f);
        }

        _transformArray = new TransformAccessArray(bullets);
    }

    private void Update()
    {
        var job = new MoveTransformJob
        {
            Velocities = _velocities,
            DeltaTime = Time.deltaTime
        };
        _moveJobHandle = job.Schedule(_transformArray);
    }

    private void LateUpdate()
    {
        _moveJobHandle.Complete();
    }

    private void OnDestroy()
    {
        _moveJobHandle.Complete();
        _transformArray.Dispose();
        _velocities.Dispose();
    }

    private Transform CreateBullet(int index)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        go.transform.position = new Vector3(index * 0.2f, 0, 0);
        go.transform.localScale = Vector3.one * 0.1f;
        return go.transform;
    }
}
```

这种 **Hybrid 方案**是最务实的选择：用 `IJobParallelForTransform` 把位置更新并行化，保留传统 GameObject/Transform，不需要完全迁移到 ECS。团队上手成本低，收益也很可观（3-8倍性能提升）。

---

## 总结

Unity DOTS 是一套非常先进的技术体系，代表了游戏引擎性能优化的方向：

| 技术 | 解决什么问题 | 核心收益 |
|------|------------|---------|
| **ECS** | 数据连续存储，提高缓存命中率 | 减少 Cache Miss，SIMD 友好 |
| **Burst** | 把 C# 编译成 SIMD 优化的机器码 | 单线程 5-20x 性能提升 |
| **Job System** | 安全的多线程并行，充分利用多核 | 多核并行，帧时间大幅降低 |

不过正如前面分析的，完整 DOTS 的学习曲线和迁移成本很高。我的推荐学习路径是：

1. 先掌握 **Job System + Burst**（无需 ECS，可以在现有项目里局部使用）
2. 对于新模块（寻路、大规模单位移动），尝试用 **Entities + ECS**
3. 积累经验后，评估是否值得全面迁移

可以期待。Unity 的 DOTS 技术栈还在快速成熟，Unity 6 版本已经把很多 Preview 包转为正式版，生态会越来越完善。
