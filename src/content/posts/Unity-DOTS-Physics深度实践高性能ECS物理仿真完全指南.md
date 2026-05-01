---
title: Unity DOTS Physics深度实践：高性能ECS物理仿真完全指南
published: 2026-05-01
description: 深度解析Unity DOTS Physics（Unity Physics + Havok Physics）的完整工程实践，涵盖ECS物理体创建、碰撞检测查询、自定义物理步进、StatefulTrigger事件系统、与MonoBehaviour桥接等核心技术，附完整代码示例与移动端性能调优策略。
tags: [Unity, DOTS, ECS, Physics, 高性能, Job System, Burst]
category: 性能优化
draft: false
---

# Unity DOTS Physics深度实践：高性能ECS物理仿真完全指南

## 前言

Unity DOTS Physics 是 Unity 为 Data-Oriented Technology Stack（DOTS）生态系推出的高性能物理引擎，由两部分组成：

- **Unity Physics**：纯 C# 实现的确定性物理引擎，完全无托管堆分配，与 Burst/Job 深度集成
- **Havok Physics for Unity**：基于 Havok 引擎的高级物理后端，提供更丰富的物理特性

与传统 PhysX（`Rigidbody`/`Collider`）相比，DOTS Physics 的优势在于：

| 对比项 | PhysX（经典） | DOTS Physics |
|--------|--------------|-------------|
| 线程模型 | 单线程主线程 | 多线程 Job 并行 |
| 内存布局 | 分散对象堆 | 线性 Chunk 内存 |
| GC 压力 | 有 GC 分配 | 零 GC（值类型） |
| 确定性 | 不保证 | Unity Physics 保证确定性 |
| 适用场景 | 常规游戏逻辑 | 大量刚体、帧同步、高密度模拟 |

本文基于 **Unity 2022.3 LTS + com.unity.physics 1.2.x** 实践，覆盖从入门到高级优化的完整路径。

---

## 环境搭建

### 包依赖配置

```json
// Packages/manifest.json 关键依赖
{
  "dependencies": {
    "com.unity.entities": "1.2.0",
    "com.unity.physics": "1.2.0",
    "com.unity.burst": "1.8.12",
    "com.unity.collections": "2.2.1",
    "com.unity.mathematics": "1.3.1"
  }
}
```

### 项目设置

```
Edit → Project Settings → Physics → 建议关闭自动模拟（DOTS 接管后可能冲突）
Edit → Project Settings → Player → Scripting Backend: IL2CPP（Burst 需要）
```

---

## 核心概念：DOTS Physics 数据结构

### PhysicsWorld 与 PhysicsStep

```csharp
// DOTS Physics 核心调度流程（简化）
public partial class MyPhysicsSystem : SystemBase
{
    protected override void OnUpdate()
    {
        // 获取物理世界单例
        var physicsWorld = SystemAPI.GetSingleton<PhysicsWorldSingleton>();
        ref readonly var collisionWorld = ref physicsWorld.CollisionWorld;
        
        // 所有物理查询通过 CollisionWorld 进行
        var query = new ColliderCastInput
        {
            Start = float3.zero,
            End = new float3(0, -5, 0),
            Collider = /* ... */
        };
    }
}
```

### 物理体组件集

DOTS 中每个物理实体由以下组件构成：

```csharp
// 必需组件
PhysicsCollider       // 碰撞体形状（引用 BlobAsset）
PhysicsWorldIndex     // 所属物理世界索引

// 动态刚体额外需要
PhysicsVelocity       // 线速度 + 角速度
PhysicsMass           // 质量属性（惯性张量）
PhysicsDamping        // 阻尼
PhysicsGravityFactor  // 重力缩放（0=无重力）
PhysicsCustomTags     // 自定义标签（用于碰撞过滤）
```

---

## 创建物理实体

### Authoring 流程（推荐）

```csharp
// 通过 Authoring 组件在编辑器中配置物理体
// 使用 Unity Physics 内置的 PhysicsBodyAuthoring 和 PhysicsShapeAuthoring 即可
// 以下演示纯代码动态创建

public partial class PhysicsEntitySpawner : SystemBase
{
    protected override void OnUpdate()
    {
        if (!SystemAPI.TryGetSingleton<PhysicsSpawnRequest>(out var request)) return;
        
        // 移除请求，防止重复创建
        EntityManager.DestroyEntity(SystemAPI.GetSingletonEntity<PhysicsSpawnRequest>());
        
        SpawnRigidBody(request.Position, request.Radius);
    }

    private void SpawnRigidBody(float3 position, float radius)
    {
        var entity = EntityManager.CreateEntity();

        // 1. 创建球形碰撞体（BlobAsset，引用计数管理）
        var sphereGeometry = new SphereGeometry
        {
            Center = float3.zero,
            Radius = radius
        };
        var colliderBlob = SphereCollider.Create(sphereGeometry, CollisionFilter.Default,
            new Material { Friction = 0.5f, Restitution = 0.3f });

        // 2. 添加物理组件
        EntityManager.AddComponentData(entity, new PhysicsCollider { Value = colliderBlob });

        // 3. 设置质量（通过 MassProperties 从碰撞体计算）
        var massProperties = colliderBlob.Value.MassProperties;
        EntityManager.AddComponentData(entity, PhysicsMass.CreateDynamic(massProperties, 1.0f));

        // 4. 速度
        EntityManager.AddComponentData(entity, new PhysicsVelocity
        {
            Linear = new float3(0, -1, 0),
            Angular = float3.zero
        });

        // 5. 阻尼
        EntityManager.AddComponentData(entity, new PhysicsDamping
        {
            Linear = 0.01f,
            Angular = 0.05f
        });

        // 6. 重力
        EntityManager.AddComponentData(entity, new PhysicsGravityFactor { Value = 1f });

        // 7. 空间变换
        EntityManager.AddComponentData(entity, new LocalTransform
        {
            Position = position,
            Rotation = quaternion.identity,
            Scale = 1f
        });
    }
}
```

---

## 碰撞查询：OverlapSphere / Raycast / ColliderCast

DOTS Physics 提供三类查询，全部支持在 Burst Job 中调用：

### 1. 射线检测（RaycastInput）

```csharp
[BurstCompile]
public partial struct RaycastJob : IJobEntity
{
    [ReadOnly] public CollisionWorld CollisionWorld;
    public float3 RayOrigin;
    public float3 RayDirection;
    public float MaxDistance;

    public void Execute(ref PhysicsRaycastResult result, in LocalTransform transform)
    {
        var input = new RaycastInput
        {
            Start = RayOrigin,
            End = RayOrigin + RayDirection * MaxDistance,
            Filter = new CollisionFilter
            {
                BelongsTo = ~0u,       // 属于所有层
                CollidesWith = ~0u,    // 与所有层碰撞
                GroupIndex = 0
            }
        };

        if (CollisionWorld.CastRay(input, out RaycastHit hit))
        {
            result.Hit = true;
            result.HitPosition = hit.Position;
            result.HitNormal = hit.SurfaceNormal;
            result.HitEntity = CollisionWorld.Bodies[hit.RigidBodyIndex].Entity;
            result.HitDistance = hit.Fraction * MaxDistance;
        }
        else
        {
            result.Hit = false;
        }
    }
}

// 调用方式
public partial class RaycastSystem : SystemBase
{
    protected override void OnUpdate()
    {
        var physicsWorld = SystemAPI.GetSingleton<PhysicsWorldSingleton>();
        
        new RaycastJob
        {
            CollisionWorld = physicsWorld.CollisionWorld,
            RayOrigin = new float3(0, 10, 0),
            RayDirection = new float3(0, -1, 0),
            MaxDistance = 20f
        }.ScheduleParallel();
    }
}
```

### 2. 球形范围查询（OverlapAabb / OverlapCollider）

```csharp
[BurstCompile]
public struct OverlapSphereJob : IJob
{
    [ReadOnly] public CollisionWorld CollisionWorld;
    public float3 Center;
    public float Radius;
    public NativeList<DistanceHit> Results;

    public void Execute()
    {
        // 创建球形碰撞体用于查询
        var sphereGeometry = new SphereGeometry { Center = float3.zero, Radius = Radius };
        using var sphereCollider = SphereCollider.Create(sphereGeometry);

        var input = new ColliderDistanceInput
        {
            Collider = (Collider*)sphereCollider.GetUnsafePtr(),
            Transform = new RigidTransform(quaternion.identity, Center),
            MaxDistance = 0f // 0 = 范围内所有接触
        };

        CollisionWorld.CalculateDistance(input, ref Results);
    }
}

// 使用示例：查询爆炸范围内的实体
public void QueryExplosionRadius(float3 explosionCenter, float radius)
{
    var physicsWorld = SystemAPI.GetSingleton<PhysicsWorldSingleton>();
    var results = new NativeList<DistanceHit>(64, Allocator.TempJob);
    
    var job = new OverlapSphereJob
    {
        CollisionWorld = physicsWorld.CollisionWorld,
        Center = explosionCenter,
        Radius = radius,
        Results = results
    };
    job.Schedule().Complete();
    
    foreach (var hit in results)
    {
        var entity = physicsWorld.CollisionWorld.Bodies[hit.RigidBodyIndex].Entity;
        // 对命中实体施加爆炸力
        ApplyExplosionForce(entity, explosionCenter, radius);
    }
    
    results.Dispose();
}
```

### 3. 形状投射（ColliderCast）

```csharp
[BurstCompile]
public struct ColliderCastJob : IJob
{
    [ReadOnly] public CollisionWorld CollisionWorld;
    public float3 From;
    public float3 To;
    public BlobAssetReference<Collider> QueryCollider;
    public NativeList<ColliderCastHit> Hits;

    public void Execute()
    {
        var input = new ColliderCastInput
        {
            Collider = (Collider*)QueryCollider.GetUnsafePtr(),
            Orientation = quaternion.identity,
            Start = From,
            End = To
        };

        CollisionWorld.CastCollider(input, ref Hits);
    }
}
```

---

## 碰撞事件系统：ITriggerEventsJob / ICollisionEventsJob

### Trigger 事件（StatefulTriggerEvent）

DOTS Physics 的事件系统基于 Job 接口，天然多线程：

```csharp
// 需要在实体上添加 StatefulTriggerEvent Buffer
// 通过 PhysicsShapeAuthoring 勾选 "Is Trigger" 并添加 StatefulTriggerEvent

[UpdateInGroup(typeof(FixedStepSimulationSystemGroup))]
[UpdateAfter(typeof(PhysicsSystemGroup))]
public partial class TriggerEventSystem : SystemBase
{
    protected override void OnUpdate()
    {
        // 处理 StatefulTriggerEvent
        Entities
            .WithAll<TriggerZone>()
            .ForEach((Entity entity, DynamicBuffer<StatefulTriggerEvent> triggerEvents) =>
            {
                foreach (var triggerEvent in triggerEvents)
                {
                    switch (triggerEvent.State)
                    {
                        case StatefulEventState.Enter:
                            HandleTriggerEnter(entity, triggerEvent.EntityB);
                            break;
                        case StatefulEventState.Stay:
                            HandleTriggerStay(entity, triggerEvent.EntityB);
                            break;
                        case StatefulEventState.Exit:
                            HandleTriggerExit(entity, triggerEvent.EntityB);
                            break;
                    }
                }
            }).Run();
    }

    private void HandleTriggerEnter(Entity zone, Entity other)
    {
        Debug.Log($"Entity {other} entered trigger zone {zone}");
        // 添加标记组件触发游戏逻辑
        EntityManager.AddComponent<InTriggerZoneTag>(other);
    }

    private void HandleTriggerStay(Entity zone, Entity other) { }

    private void HandleTriggerExit(Entity zone, Entity other)
    {
        EntityManager.RemoveComponent<InTriggerZoneTag>(other);
    }
}
```

### 碰撞事件（ITriggerEventsJob）

```csharp
[BurstCompile]
public struct CollisionEventCountJob : ICollisionEventsJob
{
    public NativeReference<int> CollisionCount;

    public void Execute(CollisionEvent collisionEvent)
    {
        CollisionCount.Value++;

        // 获取碰撞信息
        // collisionEvent.EntityA / EntityB — 碰撞双方实体
        // collisionEvent.Normal — 碰撞法线
        // collisionEvent.CalculateDetails() — 计算碰撞接触点（更耗时）
    }
}

[UpdateInGroup(typeof(FixedStepSimulationSystemGroup))]
[UpdateAfter(typeof(PhysicsSystemGroup))]
public partial class CollisionCountSystem : SystemBase
{
    protected override void OnUpdate()
    {
        var simulationSingleton = SystemAPI.GetSingleton<SimulationSingleton>();
        var count = new NativeReference<int>(0, Allocator.TempJob);
        
        Dependency = new CollisionEventCountJob { CollisionCount = count }
            .Schedule(simulationSingleton, Dependency);
        
        Dependency.Complete();
        Debug.Log($"本帧碰撞次数: {count.Value}");
        count.Dispose();
    }
}
```

---

## 自定义物理材质与碰撞过滤

### CollisionFilter 层级过滤

```csharp
// 定义碰撞层（类比 LayerMask）
public static class PhysicsLayers
{
    public const uint Default    = 1u << 0;
    public const uint Player     = 1u << 1;
    public const uint Enemy      = 1u << 2;
    public const uint Projectile = 1u << 3;
    public const uint Trigger    = 1u << 4;
    public const uint Ground     = 1u << 5;

    // 子弹只与敌人和地面碰撞
    public static CollisionFilter ProjectileFilter => new CollisionFilter
    {
        BelongsTo = Projectile,
        CollidesWith = Enemy | Ground,
        GroupIndex = 0
    };

    // 触发器不与任何物理层碰撞（纯 Trigger）
    public static CollisionFilter TriggerOnlyFilter => new CollisionFilter
    {
        BelongsTo = Trigger,
        CollidesWith = Player | Enemy,
        GroupIndex = 0
    };
}

// 运行时修改碰撞过滤器
[BurstCompile]
public partial struct UpdateCollisionFilterJob : IJobEntity
{
    public CollisionFilter NewFilter;

    public void Execute(ref PhysicsCollider collider)
    {
        // 注意：修改 BlobAsset 需要先克隆
        unsafe
        {
            var colliderPtr = (Collider*)collider.ColliderPtr;
            colliderPtr->Filter = NewFilter;
        }
    }
}
```

### 物理材质：摩擦力与弹性

```csharp
// 通过 Material 结构体配置物理材质属性
unsafe void SetPhysicsMaterial(PhysicsCollider* collider, float friction, float restitution)
{
    var material = new Material
    {
        Friction = friction,                    // 摩擦系数 [0, 1]
        FrictionCombinePolicy = Material.CombinePolicy.Minimum,
        Restitution = restitution,              // 弹性系数 [0, 1]
        RestitutionCombinePolicy = Material.CombinePolicy.Maximum,
        CollisionResponsePolicy = CollisionResponsePolicy.Collide // 或 RaiseTriggerEvents
    };
    collider->Material = material;
}
```

---

## 施加力与冲量

```csharp
[BurstCompile]
public partial struct ApplyForceJob : IJobEntity
{
    public float3 ForceDirection;
    public float ForceMagnitude;
    public float DeltaTime;
    public float3 ExplosionCenter;
    public float ExplosionRadius;

    public void Execute(
        ref PhysicsVelocity velocity,
        in PhysicsMass mass,
        in LocalTransform transform)
    {
        if (mass.IsKinematic) return; // 运动学刚体不受力

        // 1. 施加持续力（F = ma → Δv = F/m * Δt）
        float3 acceleration = ForceDirection * ForceMagnitude * mass.InverseMass;
        velocity.Linear += acceleration * DeltaTime;

        // 2. 爆炸冲量（距离衰减）
        float3 toEntity = transform.Position - ExplosionCenter;
        float distance = math.length(toEntity);
        if (distance < ExplosionRadius && distance > 0.001f)
        {
            float falloff = 1f - distance / ExplosionRadius;
            float3 impulseDir = math.normalize(toEntity);
            float impulseMagnitude = 500f * falloff;
            
            // 直接修改线速度（冲量 = 质量 × 速度变化）
            velocity.Linear += impulseDir * impulseMagnitude * mass.InverseMass;
            
            // 也可以施加角冲量（Torque）
            float3 torqueAxis = math.cross(impulseDir, math.up());
            velocity.Angular += torqueAxis * impulseMagnitude * 0.5f;
        }
    }
}
```

---

## 运动学刚体（Kinematic Body）

运动学刚体不受物理引擎的力/重力影响，但会参与碰撞检测（类似 Rigidbody.isKinematic）：

```csharp
// 将刚体设为运动学模式
public static PhysicsMass CreateKinematicMass()
{
    return new PhysicsMass
    {
        Transform = RigidTransform.identity,
        InverseMass = 0f,           // 0 = 无限质量
        InverseInertia = float3.zero, // 无旋转惯量
        AngularExpansionFactor = 0f
    };
}

// 通过 PhysicsVelocity 驱动运动学刚体位移（而非直接改 LocalTransform）
[BurstCompile]
public partial struct DriveKinematicJob : IJobEntity
{
    public float3 TargetPosition;
    public float3 CurrentPosition;
    public float DeltaTime;

    public void Execute(
        ref PhysicsVelocity velocity,
        in PhysicsMass mass)
    {
        if (!mass.IsKinematic) return;
        
        // 计算到目标的速度
        float3 displacement = TargetPosition - CurrentPosition;
        velocity.Linear = displacement / DeltaTime; // 一帧内到达目标
    }
}
```

---

## 与 MonoBehaviour 桥接

DOTS Physics 纯 ECS 体系有时需要与传统 GameObject 系统交互：

```csharp
/// <summary>
/// 桥接组件：将 DOTS 物理事件传递到 MonoBehaviour
/// </summary>
public class PhysicsEventBridge : MonoBehaviour
{
    // 暴露给 MonoBehaviour 的事件
    public event Action<GameObject> OnTriggerEnterEvent;
    public event Action<GameObject> OnTriggerExitEvent;

    // 由 ECS System 写入
    internal ConcurrentQueue<(bool isEnter, Entity other)> EventQueue = new();

    private World _dotsWorld;
    private EntityManager _em;

    private void Start()
    {
        _dotsWorld = World.DefaultGameObjectInjectionWorld;
        _em = _dotsWorld.EntityManager;
    }

    private void Update()
    {
        // 在主线程中消费 ECS 事件
        while (EventQueue.TryDequeue(out var evt))
        {
            // 通过 Entity 查找对应的 Companion GameObject
            if (_em.HasComponent<CompanionLink>(evt.other))
            {
                var link = _em.GetComponentObject<CompanionLink>(evt.other);
                if (evt.isEnter)
                    OnTriggerEnterEvent?.Invoke(link.Companion);
                else
                    OnTriggerExitEvent?.Invoke(link.Companion);
            }
        }
    }
}

// ECS 侧将事件推入队列
[UpdateInGroup(typeof(FixedStepSimulationSystemGroup))]
[UpdateAfter(typeof(PhysicsSystemGroup))]
public partial class BridgeTriggerSystem : SystemBase
{
    protected override void OnUpdate()
    {
        // 找到有 Bridge 的触发器实体
        Entities
            .WithoutBurst() // 访问托管类型需关闭 Burst
            .ForEach((Entity entity,
                      PhysicsEventBridge bridge,
                      DynamicBuffer<StatefulTriggerEvent> events) =>
            {
                foreach (var evt in events)
                {
                    bridge.EventQueue.Enqueue((
                        evt.State == StatefulEventState.Enter,
                        evt.EntityB));
                }
            }).Run();
    }
}
```

---

## 自定义物理步进：SubStep 与精确度控制

```csharp
[UpdateInGroup(typeof(FixedStepSimulationSystemGroup))]
public partial class CustomPhysicsStep : SystemBase
{
    protected override void OnUpdate()
    {
        // 修改物理步进配置（每次物理帧可执行多个子步）
        if (SystemAPI.TryGetSingletonRW<PhysicsStep>(out var physicsStep))
        {
            ref var step = ref physicsStep.ValueRW;
            step.SimulationType = SimulationType.UnityPhysics;
            step.SolverIterationCount = 4;      // 约束求解迭代次数（默认4）
            step.SolverStabilizationHeuristicSettings = new Solver.StabilizationHeuristicSettings
            {
                EnableSolverStabilization = true,
                VelocityClippingFactor = 1f,
                InertiaScalingFactor = 1f
            };
            step.ThreadCountHint = 8;           // 建议使用的工作线程数
        }
    }
}
```

---

## 大量刚体场景的性能优化

### 1. BlobAsset 复用（最重要！）

```csharp
// 错误做法：每次创建新 Collider BlobAsset（内存泄漏）
var collider1 = SphereCollider.Create(sphereGeo); // BlobAsset，需要手动释放
var collider2 = SphereCollider.Create(sphereGeo); // 重复创建！

// 正确做法：预创建并缓存，通过引用计数共享
public class ColliderBlobCache : IDisposable
{
    private Dictionary<ColliderKey, BlobAssetReference<Collider>> _cache = new();
    
    public BlobAssetReference<Collider> GetSphere(float radius)
    {
        var key = new ColliderKey(ColliderType.Sphere, radius);
        if (!_cache.TryGetValue(key, out var blob))
        {
            blob = SphereCollider.Create(new SphereGeometry { Radius = radius });
            _cache[key] = blob;
        }
        return blob;
    }
    
    public void Dispose()
    {
        foreach (var blob in _cache.Values)
            blob.Dispose();
        _cache.Clear();
    }
}
```

### 2. 休眠机制（Sleep Threshold）

```csharp
// 配置休眠阈值，静止的刚体自动进入休眠，不参与物理计算
ref var physicsStep = ref SystemAPI.GetSingletonRW<PhysicsStep>().ValueRW;
// 通过提高休眠阈值让更多静止刚体休眠
// 在 PhysicsBodyAuthoring 中设置 "Sleep Threshold"
```

### 3. 分层碰撞过滤减少碰撞对数

```csharp
// 良好的碰撞过滤可以将碰撞对从 O(n²) 降到 O(n*k)
// 子弹只与敌人层碰撞，敌人之间不碰撞
public static CollisionFilter EnemyFilter => new CollisionFilter
{
    BelongsTo = PhysicsLayers.Enemy,
    CollidesWith = PhysicsLayers.Player | PhysicsLayers.Projectile | PhysicsLayers.Ground,
    // GroupIndex < 0: 同组永不碰撞（用于友军不互相碰撞）
    GroupIndex = -1
};
```

### 4. 使用 IJobParallelFor 批量处理查询

```csharp
[BurstCompile]
public struct BatchRaycastJob : IJobParallelFor
{
    [ReadOnly] public CollisionWorld CollisionWorld;
    [ReadOnly] public NativeArray<RaycastInput> Inputs;
    public NativeArray<RaycastHit> Results;
    public NativeArray<bool> HasHit;

    public void Execute(int index)
    {
        HasHit[index] = CollisionWorld.CastRay(Inputs[index], out Results[index]);
    }
}
```

---

## 调试与可视化

DOTS Physics 内置了物理调试绘制系统：

```csharp
// 在 Editor 中启用物理调试可视化
// Window → DOTS → Physics Debugger
// 或通过代码开启：

public partial class PhysicsDebugSystem : SystemBase
{
    protected override void OnUpdate()
    {
#if UNITY_EDITOR
        // 绘制所有碰撞体轮廓
        var debugDisplayData = SystemAPI.GetSingletonRW<PhysicsDebugDisplayData>();
        debugDisplayData.ValueRW.DrawColliders = 1;
        debugDisplayData.ValueRW.DrawColliderEdges = 1;
        debugDisplayData.ValueRW.DrawBroadphase = 1;
        debugDisplayData.ValueRW.DrawContacts = 1;
#endif
    }
}
```

---

## 常见陷阱与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| BlobAsset 内存泄漏 | 每次 `SphereCollider.Create()` 都分配新 BlobAsset，未 Dispose | 使用 BlobAsset 缓存，或依赖 Entity 生命周期自动管理 |
| Burst 报错 "managed object" | Job 中引用了 managed 类型 | 用 `[NativeDisableUnsafePtrRestriction]` 或重构为值类型 |
| 物理更新频率与渲染频率不同步 | FixedStepSimulation 默认 60Hz，渲染可能 120Hz | 使用 `PhysicsInterpolation` 组件做插值平滑 |
| 碰撞事件丢失 | 高速物体穿透（Tunneling） | 使用 `SpeculativeMargin` 或降低刚体速度，开启 CCD |
| 运动学刚体不触发事件 | 未添加 `StatefulCollisionEvent` Buffer | 确保触发器两端都有正确的 Material 和 Buffer 组件 |

---

## 与 Havok Physics 切换

```csharp
// 在 ISystem 中动态切换物理后端
public partial struct SwitchPhysicsBackend : ISystem
{
    public void OnCreate(ref SystemState state)
    {
        if (SystemAPI.TryGetSingletonRW<PhysicsStep>(out var step))
        {
            // 切换到 Havok（需要安装 Havok Physics for Unity 包）
            step.ValueRW.SimulationType = SimulationType.HavokPhysics;
        }
    }
}
```

Havok 相比 Unity Physics 的优势：更好的堆叠稳定性、更快的大场景性能，但**不保证确定性**，不适用于帧同步游戏。

---

## 完整案例：100,000 粒子碰撞模拟

```csharp
[BurstCompile]
public partial struct MassiveParticleSystem : ISystem
{
    private EntityQuery _particleQuery;

    [BurstCompile]
    public void OnCreate(ref SystemState state)
    {
        _particleQuery = state.GetEntityQuery(
            ComponentType.ReadWrite<PhysicsVelocity>(),
            ComponentType.ReadOnly<LocalTransform>(),
            ComponentType.ReadOnly<ParticleTag>());
    }

    [BurstCompile]
    public void OnUpdate(ref SystemState state)
    {
        float dt = SystemAPI.Time.DeltaTime;
        var physicsWorld = SystemAPI.GetSingleton<PhysicsWorldSingleton>();

        // 并行处理10万粒子，Burst 编译后性能极佳
        new UpdateParticleVelocityJob
        {
            CollisionWorld = physicsWorld.CollisionWorld,
            DeltaTime = dt,
            BoundaryRadius = 50f
        }.ScheduleParallel(_particleQuery, state.Dependency);
    }
}

[BurstCompile]
public partial struct UpdateParticleVelocityJob : IJobEntity
{
    [ReadOnly] public CollisionWorld CollisionWorld;
    public float DeltaTime;
    public float BoundaryRadius;

    public void Execute(ref PhysicsVelocity velocity, in LocalTransform transform)
    {
        // 边界反弹
        float3 pos = transform.Position;
        float dist = math.length(pos);
        if (dist > BoundaryRadius)
        {
            float3 inward = math.normalize(-pos);
            velocity.Linear = math.reflect(velocity.Linear, inward);
        }

        // 速度阻尼
        velocity.Linear *= 1f - DeltaTime * 0.5f;
    }
}
```

---

## 最佳实践总结

| 实践点 | 说明 |
|--------|------|
| **BlobAsset 缓存复用** | 相同形状的碰撞体务必共享 BlobAsset，避免内存泄漏 |
| **碰撞过滤优先** | 充分利用 CollisionFilter 减少不必要的碰撞对计算 |
| **FixedStep 隔离** | 物理逻辑放在 FixedStepSimulationSystemGroup，保持确定性 |
| **Burst + IJobEntity** | 所有物理 Job 启用 Burst 编译，性能提升 10-100 倍 |
| **运动学刚体驱动方式** | 用 PhysicsVelocity 而非直接修改 LocalTransform |
| **事件优先用 Stateful** | StatefulTriggerEvent 提供 Enter/Stay/Exit 状态，更易用 |
| **调试工具善用** | Physics Debugger 是排查碰撞问题的最佳工具 |
| **大场景启用休眠** | 合理配置 Sleep Threshold，静止刚体自动休眠节省 CPU |

---

## 总结

Unity DOTS Physics 是为性能密集型场景而生的物理系统，核心价值在于：

1. **零 GC + Burst 编译**：大量刚体模拟时性能是传统 PhysX 的数倍
2. **确定性保证**（Unity Physics）：适用于帧同步、回放等需要确定性的场景  
3. **深度 Job 集成**：物理查询/事件处理天然并行，充分利用多核 CPU
4. **与 ECS 无缝协作**：物理状态通过组件数据驱动，代码结构清晰

但 DOTS Physics 也有明确的适用边界：对于普通小型游戏，传统 PhysX 已经足够；当场景中存在**数千个以上刚体**，或需要**确定性物理**时，DOTS Physics 才是正确选择。
