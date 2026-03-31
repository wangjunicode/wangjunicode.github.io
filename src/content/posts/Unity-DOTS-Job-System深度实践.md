---
title: Unity DOTS Job System深度实践：数据导向多线程编程
published: 2026-03-31
description: 深入掌握 Unity DOTS Job System 的核心原理与实战应用，涵盖 IJob/IJobParallelFor/IJobParallelForTransform 的使用方式、NativeContainer 内存管理、Burst 编译优化、依赖链构建，以及在大规模粒子、物理检测、寻路等场景的实战案例。
tags: [Unity, DOTS, Job System, ECS, 性能优化, C#]
category: Unity进阶
draft: false
---

## 一、为什么需要 Job System？

传统 Unity 开发的主要性能瓶颈：

- **单线程渲染准备**：所有游戏逻辑在主线程执行
- **GC压力**：大量引用类型分配引发垃圾回收卡顿
- **CPU利用率低**：多核CPU大量空置

DOTS（Data-Oriented Technology Stack）的核心思想：
- **Job System**：将工作拆分到多个工作线程并行执行
- **Burst Compiler**：将 C# 编译为高度优化的原生代码
- **ECS**：数据紧凑排列，充分利用CPU缓存

---

## 二、Job System 核心接口

### 2.1 IJob：简单单次任务

```csharp
using Unity.Jobs;
using Unity.Collections;
using Unity.Burst;
using Unity.Mathematics;
using UnityEngine;

/// <summary>
/// IJob：在单个工作线程上执行一次性任务
/// </summary>
[BurstCompile] // 使用Burst编译，性能提升5-10倍
public struct PathfindingJob : IJob
{
    // NativeArray 是线程安全的非托管内存容器
    [ReadOnly] public NativeArray<float3> Waypoints;
    [WriteOnly] public NativeArray<float3> ResultPath;
    public float3 StartPosition;
    public float3 EndPosition;
    
    public void Execute()
    {
        // 在工作线程上执行寻路计算
        // 注意：不能访问 UnityEngine 对象（Transform、MonoBehaviour 等）
        int closestIdx = 0;
        float closestDist = float.MaxValue;
        
        for (int i = 0; i < Waypoints.Length; i++)
        {
            float dist = math.distance(Waypoints[i], StartPosition);
            if (dist < closestDist)
            {
                closestDist = dist;
                closestIdx = i;
            }
        }
        
        ResultPath[0] = Waypoints[closestIdx];
    }
}

// 使用示例
public class PathfindingSystem : MonoBehaviour
{
    private NativeArray<float3> waypoints;
    private NativeArray<float3> resultPath;
    private JobHandle pathJobHandle;

    void Start()
    {
        waypoints = new NativeArray<float3>(100, Allocator.Persistent);
        resultPath = new NativeArray<float3>(10, Allocator.Persistent);
        
        // 填充路点数据...
    }

    void Update()
    {
        // 调度Job（非阻塞）
        var job = new PathfindingJob
        {
            Waypoints = waypoints,
            ResultPath = resultPath,
            StartPosition = new float3(0, 0, 0),
            EndPosition = new float3(10, 0, 10)
        };
        
        pathJobHandle = job.Schedule();
        
        // 主线程继续执行其他工作...
    }

    void LateUpdate()
    {
        // 在 LateUpdate 中等待Job完成
        pathJobHandle.Complete();
        
        // 现在可以安全读取 resultPath
        Vector3 nextWaypoint = resultPath[0];
        transform.position = Vector3.MoveTowards(
            transform.position, nextWaypoint, 5f * Time.deltaTime);
    }

    void OnDestroy()
    {
        pathJobHandle.Complete(); // 必须先Complete再Dispose
        waypoints.Dispose();
        resultPath.Dispose();
    }
}
```

### 2.2 IJobParallelFor：数组并行处理

```csharp
/// <summary>
/// IJobParallelFor：并行处理数组中的每个元素
/// 自动将数组分段分配给多个工作线程
/// </summary>
[BurstCompile]
public struct BulletUpdateJob : IJobParallelFor
{
    public float DeltaTime;
    public float3 Gravity;
    
    // 注意：写操作使用 NativeArray，不能用 ReadOnly
    public NativeArray<float3> Positions;
    public NativeArray<float3> Velocities;
    
    [WriteOnly] public NativeArray<bool> IsAlive;
    
    // index 是当前处理的元素索引（线程安全）
    public void Execute(int index)
    {
        // 更新速度（重力）
        float3 vel = Velocities[index] + Gravity * DeltaTime;
        Velocities[index] = vel;
        
        // 更新位置
        float3 pos = Positions[index] + vel * DeltaTime;
        Positions[index] = pos;
        
        // 边界检测
        IsAlive[index] = pos.y > -50f;
    }
}

public class BulletSystem : MonoBehaviour
{
    private const int MaxBullets = 10000;
    private NativeArray<float3> positions;
    private NativeArray<float3> velocities;
    private NativeArray<bool> isAlive;
    private int activeBulletCount;
    private JobHandle bulletJobHandle;

    void Awake()
    {
        positions  = new NativeArray<float3>(MaxBullets, Allocator.Persistent);
        velocities = new NativeArray<float3>(MaxBullets, Allocator.Persistent);
        isAlive    = new NativeArray<bool>(MaxBullets, Allocator.Persistent);
    }

    public void SpawnBullet(Vector3 pos, Vector3 vel)
    {
        if (activeBulletCount >= MaxBullets) return;
        
        int idx = activeBulletCount++;
        positions[idx] = pos;
        velocities[idx] = vel;
        isAlive[idx] = true;
    }

    void Update()
    {
        if (activeBulletCount == 0) return;
        
        var job = new BulletUpdateJob
        {
            DeltaTime = Time.deltaTime,
            Gravity = new float3(0, -9.8f, 0),
            Positions = positions,
            Velocities = velocities,
            IsAlive = isAlive
        };
        
        // innerloopBatchCount：每批次处理多少个元素（推荐 32-128）
        bulletJobHandle = job.Schedule(activeBulletCount, 64);
    }

    void LateUpdate()
    {
        bulletJobHandle.Complete();
        
        // 清理死亡子弹（紧缩数组）
        int writeIdx = 0;
        for (int i = 0; i < activeBulletCount; i++)
        {
            if (isAlive[i])
            {
                positions[writeIdx] = positions[i];
                velocities[writeIdx] = velocities[i];
                isAlive[writeIdx] = true;
                writeIdx++;
            }
        }
        activeBulletCount = writeIdx;
    }

    void OnDestroy()
    {
        bulletJobHandle.Complete();
        positions.Dispose();
        velocities.Dispose();
        isAlive.Dispose();
    }
}
```

### 2.3 IJobParallelForTransform：Transform并行更新

```csharp
/// <summary>
/// IJobParallelForTransform：专为 Transform 数组并行更新设计
/// 效率远高于主线程逐个设置 Transform
/// </summary>
[BurstCompile]
public struct FlockingJob : IJobParallelForTransform
{
    [ReadOnly] public NativeArray<float3> AllPositions;
    [ReadOnly] public NativeArray<float3> AllVelocities;
    public float DeltaTime;
    public float SeparationRadius;
    public float AlignmentRadius;
    public float CohesionRadius;

    public void Execute(int index, TransformAccess transform)
    {
        float3 pos = AllPositions[index];
        float3 vel = AllVelocities[index];
        
        float3 separation = float3.zero;
        float3 alignment = float3.zero;
        float3 cohesion = float3.zero;
        int neighborCount = 0;
        
        for (int i = 0; i < AllPositions.Length; i++)
        {
            if (i == index) continue;
            
            float dist = math.distance(pos, AllPositions[i]);
            
            if (dist < SeparationRadius)
                separation += math.normalize(pos - AllPositions[i]) / dist;
            
            if (dist < AlignmentRadius)
            {
                alignment += AllVelocities[i];
                neighborCount++;
            }
            
            if (dist < CohesionRadius)
                cohesion += AllPositions[i];
        }
        
        if (neighborCount > 0)
        {
            alignment /= neighborCount;
            cohesion = cohesion / neighborCount - pos;
        }
        
        float3 steering = separation * 1.5f + alignment * 1.0f + cohesion * 1.0f;
        float3 newVel = math.normalize(vel + steering * DeltaTime) * 3f;
        
        // 直接更新 Transform（线程安全）
        transform.position = pos + newVel * DeltaTime;
        
        if (math.lengthsq(newVel) > 0.001f)
        {
            transform.rotation = quaternion.LookRotationSafe(newVel, math.up());
        }
    }
}
```

---

## 三、Job 依赖链管理

```csharp
/// <summary>
/// 构建 Job 依赖链，确保正确的执行顺序
/// </summary>
public class GameSimulation : MonoBehaviour
{
    private JobHandle simulationHandle;
    
    // 各 Job 的 NativeArray 数据...
    private NativeArray<float3> positions;
    private NativeArray<float3> velocities;
    private NativeArray<float> health;

    void Update()
    {
        // 第一步：物理更新（无依赖）
        var physicsJob = new PhysicsUpdateJob
        {
            Positions = positions,
            Velocities = velocities,
            DeltaTime = Time.deltaTime
        };
        JobHandle physicsHandle = physicsJob.Schedule(1000, 32);
        
        // 第二步：碰撞检测（依赖物理更新完成）
        var collisionJob = new CollisionDetectionJob
        {
            Positions = positions
        };
        JobHandle collisionHandle = collisionJob.Schedule(1000, 16, physicsHandle);
        
        // 第三步：伤害计算（依赖碰撞检测）
        var damageJob = new DamageCalculationJob
        {
            Health = health
        };
        JobHandle damageHandle = damageJob.Schedule(1000, 16, collisionHandle);
        
        // 第四步：死亡检查（依赖伤害计算）
        var deathJob = new DeathCheckJob { Health = health };
        JobHandle deathHandle = deathJob.Schedule(1000, 16, damageHandle);
        
        // 合并多个并行依赖
        NativeArray<JobHandle> deps = new NativeArray<JobHandle>(2, Allocator.Temp);
        deps[0] = damageHandle;
        deps[1] = deathHandle;
        simulationHandle = JobHandle.CombineDependencies(deps);
        deps.Dispose();
        
        // 告知 JobSystem 调度器，帮助其优化线程分配
        JobHandle.ScheduleBatchedJobs();
    }

    void LateUpdate()
    {
        simulationHandle.Complete();
        // 读取结果...
    }
}

// 示例 Job 结构（简化）
[BurstCompile]
public struct PhysicsUpdateJob : IJobParallelFor
{
    public NativeArray<float3> Positions;
    [ReadOnly] public NativeArray<float3> Velocities;
    public float DeltaTime;
    public void Execute(int i) => Positions[i] += Velocities[i] * DeltaTime;
}

[BurstCompile]
public struct CollisionDetectionJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> Positions;
    public void Execute(int i) { /* 碰撞检测逻辑 */ }
}

[BurstCompile]
public struct DamageCalculationJob : IJobParallelFor
{
    public NativeArray<float> Health;
    public void Execute(int i) { /* 伤害计算 */ }
}

[BurstCompile]
public struct DeathCheckJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float> Health;
    public void Execute(int i) { /* 死亡检查 */ }
}
```

---

## 四、NativeContainer 内存管理

```csharp
/// <summary>
/// NativeContainer 分配器选择指南
/// </summary>
public class NativeContainerGuide : MonoBehaviour
{
    void Awake()
    {
        // Allocator.Temp：单帧临时，最快，必须同帧释放
        var tempArray = new NativeArray<int>(100, Allocator.Temp);
        // ... 使用 tempArray
        tempArray.Dispose(); // 必须在同一帧Dispose
        
        // Allocator.TempJob：Job专用，最多存活4帧
        var tempJobArray = new NativeArray<float>(500, Allocator.TempJob);
        // Schedule job...
        // Complete() 后 Dispose
        
        // Allocator.Persistent：长期持有，需要手动Dispose
        var persistentArray = new NativeArray<float3>(10000, Allocator.Persistent);
        // 在 OnDestroy 中 Dispose
    }
    
    // 常用 NativeContainer 一览
    void ShowContainers()
    {
        // NativeArray：固定大小数组
        var arr = new NativeArray<float>(100, Allocator.TempJob);
        
        // NativeList：动态列表（需引用 Unity.Collections）
        // var list = new NativeList<float>(Allocator.TempJob);
        
        // NativeHashMap：字典
        var map = new NativeHashMap<int, float>(100, Allocator.TempJob);
        
        // NativeQueue：队列
        var queue = new NativeQueue<int>(Allocator.TempJob);
        
        // NativeSlice：数组切片（不分配内存）
        var slice = arr.Slice(10, 50);
        
        arr.Dispose();
        map.Dispose();
        queue.Dispose();
    }
}
```

---

## 五、Burst 编译优化

```csharp
/// <summary>
/// Burst 编译注意事项
/// </summary>
[BurstCompile(
    CompileSynchronously = false,  // 异步编译（不阻塞启动）
    FloatMode = FloatMode.Fast,    // 允许快速浮点（损失少量精度）
    FloatPrecision = FloatPrecision.Standard  // 标准精度
)]
public struct OptimizedSimulationJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> Input;
    [WriteOnly] public NativeArray<float3> Output;
    public float Scale;
    
    public void Execute(int index)
    {
        // math 库 > Mathf：Burst 对 Unity.Mathematics 优化更好
        float3 v = Input[index];
        float len = math.length(v);
        
        // 使用 math.select 替代条件分支（避免分支预测失败）
        float3 normalized = math.select(float3.zero, v / len, len > 0.0001f);
        
        Output[index] = normalized * Scale;
    }
}

// ❌ Burst 中不允许的操作：
// - 访问托管类型（class, string, array[]）
// - 调用虚函数
// - 异常处理
// - 使用 Debug.Log
// - 访问 Unity 对象（Transform, Rigidbody）

// ✅ Burst 中推荐的操作：
// - Unity.Mathematics 的所有函数
// - NativeContainer 的读写
// - 值类型 struct 操作
// - 固定大小缓冲区 unsafe
```

---

## 六、实战：1万 AI 视野检测并行化

```csharp
[BurstCompile]
public struct AIVisionCheckJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> AgentPositions;
    [ReadOnly] public NativeArray<float3> AgentForwards;
    [ReadOnly] public NativeArray<float3> TargetPositions;
    [WriteOnly] public NativeArray<int> VisibleTargetIndex; // -1 表示无可见目标
    
    public float VisionRange;
    public float VisionAngleCos; // cos(视野角/2)，避免反复计算cos

    public void Execute(int agentIndex)
    {
        float3 agentPos = AgentPositions[agentIndex];
        float3 agentFwd = AgentForwards[agentIndex];
        
        int closestVisible = -1;
        float closestDist = float.MaxValue;
        
        for (int t = 0; t < TargetPositions.Length; t++)
        {
            float3 toTarget = TargetPositions[t] - agentPos;
            float dist = math.length(toTarget);
            
            if (dist > VisionRange || dist > closestDist) continue;
            
            // 视野角检测（无需 sqrt）
            float3 toTargetNorm = toTarget / dist;
            float dot = math.dot(agentFwd, toTargetNorm);
            
            if (dot >= VisionAngleCos)
            {
                closestVisible = t;
                closestDist = dist;
            }
        }
        
        VisibleTargetIndex[agentIndex] = closestVisible;
    }
}

public class MassAISystem : MonoBehaviour
{
    private const int AgentCount = 10000;
    private const int TargetCount = 100;
    
    private NativeArray<float3> agentPositions;
    private NativeArray<float3> agentForwards;
    private NativeArray<float3> targetPositions;
    private NativeArray<int> visibleTargets;
    
    private JobHandle visionHandle;
    
    // 性能对比：主线程循环 10000*100 次需要 ~50ms
    // Job System + Burst：仅需 ~1ms
}
```

---

## 七、性能基准参考

| 场景 | 主线程 | Job System | Job+Burst | 提升比 |
|------|--------|------------|-----------|--------|
| 1万粒子更新 | 12ms | 2ms | 0.3ms | 40x |
| 10万个碰撞检测 | 180ms | 25ms | 4ms | 45x |
| 1万AI视野 | 50ms | 8ms | 1ms | 50x |
| Transform 批量更新 | 8ms | 1.5ms | 0.5ms | 16x |

Job System + Burst 的组合是 Unity 大规模模拟的终极武器，对于需要每帧处理大量同质化计算的系统，性能提升可达 20-50 倍。
