---
title: ECS/DOTS 架构深度入门：数据导向设计在游戏中的应用
published: 2026-03-21
description: "深入讲解 Unity DOTS（Data-Oriented Technology Stack）和 ECS（Entity Component System）的核心原理，包括 Archetype、Chunk 内存布局、System 设计、Job System 并行计算，以及在大型商业项目中的实践经验。"
tags: [ECS, DOTS, Unity, 性能优化, 架构设计]
category: 架构设计
draft: false
encryptedKey: henhaoji123
---

## 为什么要学 ECS/DOTS

传统 OOP 游戏开发的性能瓶颈：

```
传统 MonoBehaviour 场景（1000个敌人）：

内存中的样子：
Enemy_0 [HP, Attack, Position, Sprite, ...] ← 对象0
Enemy_1 [HP, Attack, Position, Sprite, ...] ← 对象1
Enemy_2 [HP, Attack, Position, Sprite, ...] ← 对象2
...
Enemy_999 [HP, Attack, Position, Sprite, ...] ← 对象999

更新逻辑时：
  for each enemy: enemy.Update()
  每次 Update 随机访问内存 → 大量 Cache Miss → 性能差

Cache Miss 的代价：
  L1 Cache 命中：约 1ns
  RAM 访问：约 100ns
  Cache Miss 导致等待：比命中慢 100 倍
```

ECS 解决了什么：
```
ECS 场景（1000个敌人）：

内存中的样子（Archetype: [HP, Attack, Position] 的实体）：
Chunk_0: [HP0, HP1, ... HP64][Attack0, Attack1, ... Attack64][Pos0, Pos1, ... Pos64]
Chunk_1: [HP65, HP66, ... HP128][...]...

更新位置时（ForEach(Position, Velocity)）：
  顺序访问 Pos0, Pos1, Pos2, Pos3... → 完美 Cache 友好
  顺序访问 Vel0, Vel1, Vel2, Vel3...
  CPU 预取机制可以提前加载下一段数据
```

---

## 一、核心概念

### 1.1 Entity、Component、System

```
Entity：实体
  - 只是一个 ID（64位整数）
  - 没有数据，没有行为
  - 本身几乎不占内存

Component：组件（纯数据，必须是 struct）
  - 只有数据，没有方法
  - 必须是 IComponentData 的实现
  - 存储在连续内存中（Cache 友好）

System：系统（纯逻辑）
  - 没有数据，只有行为
  - 通过查询（EntityQuery）找到符合条件的实体
  - 对查询到的实体批量处理

World：世界
  - 包含一个 EntityManager 和多个 System
  - 可以有多个 World（如：Client World, Server World）
```

### 1.2 Archetype 和 Chunk

```
Archetype = 特定 Component 组合的模板
  例：{ Position, Velocity, Health } 是一种 Archetype
      { Position, Velocity } 是另一种 Archetype

Chunk = 同一 Archetype 的实体的存储单元
  - 固定大小：16KB
  - 同一 Chunk 内的实体拥有完全相同的 Component 类型
  - Component 数据列式存储（SOA：Structure of Arrays）

内存布局：
  Chunk: [Position×N][Velocity×N][Health×N]
          ←──────── 16KB ──────────→
  N = 16KB / (sizeof(Position) + sizeof(Velocity) + sizeof(Health))

添加/移除 Component 时：
  实体从一个 Chunk 移动到另一个 Chunk（因为 Archetype 变了）
  这是一个昂贵的操作，要尽量避免频繁做
```

---

## 二、编写 ECS 代码

### 2.1 定义 Component

```csharp
using Unity.Entities;
using Unity.Mathematics;

// 位置组件
public struct LocalTransform : IComponentData
{
    public float3 Position;
    public quaternion Rotation;
    public float Scale;
}

// 移动速度组件
public struct MoveSpeed : IComponentData
{
    public float Value;
}

// 生命值组件
public struct Health : IComponentData
{
    public int Current;
    public int Max;
    
    public float Percentage => (float)Current / Max;
    public bool IsDead => Current <= 0;
}

// 标签组件（零大小，只用于查询标记）
public struct EnemyTag : IComponentData { }
public struct PlayerTag : IComponentData { }

// 共享组件（同 Archetype 内的实体共享同一值）
// 适合用于：渲染材质、团队阵营等相同值多实体共享的场景
public struct Team : ISharedComponentData
{
    public int TeamId;
}
```

### 2.2 编写 System

```csharp
using Unity.Entities;
using Unity.Transforms;
using Unity.Mathematics;
using Unity.Burst;
using Unity.Collections;

// BurstCompile 编译为高效的原生代码
[BurstCompile]
public partial struct MoveSystem : ISystem
{
    [BurstCompile]
    public void OnCreate(ref SystemState state)
    {
        // 可以在这里创建查询或申请资源
        // 如果 state 没有 MoveSpeed 组件，就不需要运行这个 System
        state.RequireForUpdate<MoveSpeed>();
    }
    
    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        float deltaTime = SystemAPI.Time.DeltaTime;
        
        // 方式1：ForEach（简单易用）
        foreach (var (transform, speed) 
                 in SystemAPI.Query<RefRW<LocalTransform>, RefRO<MoveSpeed>>())
        {
            transform.ValueRW.Position += math.forward(transform.ValueRO.Rotation) 
                                        * speed.ValueRO.Value 
                                        * deltaTime;
        }
    }
}

// 更高性能：使用 IJobEntity（并行化）
[BurstCompile]
public partial struct MoveParallelSystem : ISystem
{
    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        float deltaTime = SystemAPI.Time.DeltaTime;
        
        // 调度并行 Job
        new MoveJob { DeltaTime = deltaTime }
            .ScheduleParallel(); // 并行执行，充分利用多核 CPU
    }
}

[BurstCompile]
partial struct MoveJob : IJobEntity
{
    public float DeltaTime;
    
    // 自动查询所有拥有 LocalTransform 和 MoveSpeed 的实体
    public void Execute(ref LocalTransform transform, in MoveSpeed speed)
    {
        transform.Position += math.forward(transform.Rotation) 
                            * speed.Value 
                            * DeltaTime;
    }
}
```

### 2.3 EntityQuery：精确控制查询范围

```csharp
[BurstCompile]
public partial struct DamageSystem : ISystem
{
    private EntityQuery _enemyQuery;
    
    [BurstCompile]
    public void OnCreate(ref SystemState state)
    {
        // 构建精确的查询
        _enemyQuery = new EntityQueryBuilder(Allocator.Temp)
            .WithAll<EnemyTag, Health, LocalTransform>()     // 必须有这些
            .WithNone<DeadTag>()                              // 必须没有这个
            .WithAny<BurnEffect, PoisonEffect>()              // 至少有一个
            .Build(ref state);
    }
    
    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        // 获取查询结果（只读）
        var positions = _enemyQuery.ToComponentDataArray<LocalTransform>(Allocator.TempJob);
        
        // 处理后释放（NativeArray 需要手动释放）
        positions.Dispose();
        
        // 或者用 Job 批量处理
        new ApplyBurnDamageJob
        {
            DeltaTime = SystemAPI.Time.DeltaTime
        }.ScheduleParallel(_enemyQuery);
    }
}

[BurstCompile]
partial struct ApplyBurnDamageJob : IJobEntity
{
    public float DeltaTime;
    
    [WithAll(typeof(EnemyTag))]           // 只处理有 EnemyTag 的
    [WithNone(typeof(DeadTag))]           // 排除已死亡的
    public void Execute(ref Health health, in BurnEffect burn)
    {
        health.Current -= (int)(burn.DamagePerSecond * DeltaTime);
        
        if (health.Current < 0) health.Current = 0;
    }
}
```

---

## 三、Burst Compiler 与 Job System

### 3.1 Burst 的作用

```
Burst Compiler 的优化：
  1. SIMD 向量化：将标量循环转换为 SIMD 指令
     4个 float 加法 → 1条 AVX 指令（4倍加速）
     
  2. 循环展开：减少循环控制开销
  
  3. 内联：消除函数调用开销
  
  4. 消除边界检查：NativeArray 的边界检查在 Burst 中可以省略
  
  5. 利用 CPU 特性：针对 SSE4.2/AVX2 等指令集优化

性能对比（1000个实体，位置更新）：
  C# Mono：1.0x（基准）
  C# IL2CPP：2~3x
  Burst：10~30x（视算法和数据布局）
```

### 3.2 Job System 多线程

```csharp
// Unity Job System 提供安全的多线程 API
// 编译器自动检测数据竞争（通过 [ReadOnly] 等特性）

[BurstCompile]
struct ProcessEntitiesJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> Positions;     // 只读，可并行
    [WriteOnly] public NativeArray<float3> Results;      // 只写，需要保证不同 index 写入
    
    public void Execute(int index)
    {
        // 每个线程处理一个 index，完全并行，无同步开销
        Results[index] = math.normalize(Positions[index]);
    }
}

// 调度 Job
void Update()
{
    var positions = new NativeArray<float3>(1000, Allocator.TempJob);
    var results = new NativeArray<float3>(1000, Allocator.TempJob);
    
    // 填充 positions...
    
    var job = new ProcessEntitiesJob
    {
        Positions = positions,
        Results = results
    };
    
    // ScheduleParallel：将工作分配给所有可用的工作线程
    JobHandle handle = job.Schedule(positions.Length, 64); // 批次大小 64
    
    // 等待所有 Job 完成（在需要结果之前）
    handle.Complete();
    
    // 使用结果...
    
    // 释放 NativeArray
    positions.Dispose();
    results.Dispose();
}
```

---

## 四、ECS 常见模式

### 4.1 Command Buffer：延迟结构性变更

```csharp
// 在 Job 中不能直接修改实体结构（添加/删除 Component）
// 需要使用 EntityCommandBuffer 记录变更，在主线程执行

[BurstCompile]
public partial struct DamageApplySystem : ISystem
{
    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        // 使用 BeginSimulationEntityCommandBufferSystem 的 Singleton
        var ecbSingleton = SystemAPI.GetSingleton<BeginSimulationEntityCommandBufferSystem.Singleton>();
        var ecb = ecbSingleton.CreateCommandBuffer(state.WorldUnmanaged);
        
        new MarkDeadJob
        {
            ECB = ecb.AsParallelWriter() // 并行写入的 ECB
        }.ScheduleParallel();
    }
}

[BurstCompile]
partial struct MarkDeadJob : IJobEntity
{
    public EntityCommandBuffer.ParallelWriter ECB;
    
    public void Execute([EntityIndexInChunk] int sortKey, Entity entity, in Health health)
    {
        if (health.IsDead)
        {
            // 记录变更：添加 DeadTag 组件
            // sortKey 确保并行写入的确定性
            ECB.AddComponent<DeadTag>(sortKey, entity);
            ECB.RemoveComponent<EnemyTag>(sortKey, entity);
        }
    }
}
```

### 4.2 Blob Asset：共享只读数据

```csharp
// BlobAsset：在 Job 中安全访问的共享只读数据
// 适合：技能配置、AI 决策树、动画曲线等

// 定义 Blob 数据结构
public struct SkillDataBlob
{
    public int SkillId;
    public float Cooldown;
    public float Range;
    public BlobArray<int> EffectIds;       // Blob 内的数组
    public BlobString SkillName;           // Blob 内的字符串
}

// 创建 BlobAsset
public static BlobAssetReference<SkillDataBlob> CreateSkillBlob(SkillConfig config)
{
    var builder = new BlobBuilder(Allocator.Temp);
    ref var blob = ref builder.ConstructRoot<SkillDataBlob>();
    
    blob.SkillId = config.SkillId;
    blob.Cooldown = config.Cooldown;
    blob.Range = config.Range;
    
    // 创建数组
    var effectArray = builder.Allocate(ref blob.EffectIds, config.Effects.Length);
    for (int i = 0; i < config.Effects.Length; i++)
        effectArray[i] = config.Effects[i].EffectId;
    
    var reference = builder.CreateBlobAssetReference<SkillDataBlob>(Allocator.Persistent);
    builder.Dispose();
    return reference;
}

// 在 Component 中持有 BlobAsset 引用
public struct SkillData : IComponentData
{
    public BlobAssetReference<SkillDataBlob> Data;
}

// 在 Job 中使用（Burst 兼容）
[BurstCompile]
partial struct SkillCooldownJob : IJobEntity
{
    public float DeltaTime;
    
    public void Execute(ref SkillCooldown cooldown, in SkillData skillData)
    {
        ref var blob = ref skillData.Data.Value; // 访问 Blob 数据
        
        if (cooldown.Remaining > 0)
            cooldown.Remaining -= DeltaTime;
    }
}
```

---

## 五、ECS 与 MonoBehaviour 的混合

大多数项目不会全部迁移到 ECS，而是选择性地在性能敏感部分使用：

```csharp
/// <summary>
/// 将 ECS 实体的数据"呈现"到 MonoBehaviour（用于 UI、特效等）
/// </summary>
[UpdateInGroup(typeof(PresentationSystemGroup))]
public partial class EntityPresentationSystem : SystemBase
{
    protected override void OnUpdate()
    {
        // 这里可以访问托管对象（因为不是 BurstCompile）
        foreach (var (transform, healthData, presenter) 
                 in SystemAPI.Query<RefRO<LocalTransform>, RefRO<Health>, 
                                    ManagedComponentRef<EntityPresenter>>())
        {
            var go = presenter.Value.GameObject;
            if (go == null) continue;
            
            // 将 ECS 数据同步到 Unity 对象
            go.transform.position = transform.ValueRO.Position;
            presenter.Value.HealthBar.value = healthData.ValueRO.Percentage;
        }
    }
}

/// <summary>
/// 托管 Component（可以持有 Class 对象，但不能在 Burst Job 中使用）
/// </summary>
public class EntityPresenter : IComponentData
{
    public GameObject GameObject;
    public UnityEngine.UI.Slider HealthBar;
}
```

---

## 六、何时使用 ECS

### 适合 ECS 的场景

```
✅ 大量相同类型实体的批量处理：
  - RTS 游戏：数千个单位同时移动
  - 粒子系统（高度自定义的）
  - 弹幕游戏：数百发子弹
  - 草地/树木渲染

✅ 性能敏感的并行计算：
  - AI 路径寻找（批量）
  - 碰撞检测（自定义）
  - 物理模拟

✅ 数据密集型系统：
  - 配置数据处理
  - 大规模 AOI（Area of Interest）计算
```

### 不适合 ECS 的场景

```
❌ 少量复杂对象（玩家角色、Boss）
  → MonoBehaviour 更直观，ECS 的收益不值开发成本

❌ 需要 Unity 生态系统（动画、物理、UI）
  → 这些系统目前还是 MonoBehaviour 体系，混用复杂

❌ 团队不熟悉 ECS
  → 学习成本高，不建议在 deadline 紧张的项目中引入
  
❌ 频繁添加/删除 Component
  → Archetype 变化代价高，会破坏 ECS 的性能优势
```

---

## 总结

ECS/DOTS 代表了游戏引擎的未来方向，但不是所有项目都需要：

**学习 ECS 的价值**：
1. 理解缓存友好的数据布局，这个思想在任何架构中都有价值
2. 掌握多线程并行计算（Job System）
3. 了解未来 Unity 的方向，为大型高性能游戏做准备

**务实的建议**：
- 中小型项目：继续用 MonoBehaviour，不要为了 ECS 而 ECS
- 有性能瓶颈的特定模块：引入 ECS 优化（如大量敌人 AI）
- 新项目大量同类实体：从设计阶段就考虑 ECS

> **下一篇**：[游戏数学基础：向量、矩阵、四元数在实战中的应用]
