---
title: "Unity物理系统深度解析：PhysX原理与高性能物理优化"
description: "深度解析Unity物理引擎（PhysX）的工作原理，包括碰撞检测算法、约束求解器、刚体动力学，以及如何在复杂场景中实现高性能物理模拟"
published: 2025-03-21
tags: ["物理引擎", "PhysX", "碰撞检测", "刚体动力学", "性能优化", "Unity"]
---

# Unity物理系统深度解析：PhysX原理与高性能物理优化

> 物理系统是游戏真实感的重要来源，但也是性能消耗的大户。理解PhysX原理，才能在品质与性能之间做出正确取舍。

---

## 一、PhysX物理引擎架构

### 1.1 物理模拟流程

```
Unity物理更新流程（每个FixedUpdate）：

Step 1: 同步（Sync）
  将Unity Transform数据同步到PhysX场景
  
Step 2: 宽相检测（Broad Phase Collision Detection）
  快速排除不可能相交的物体对
  使用AABB包围盒进行初步筛选
  算法：SAP（Sweep and Prune）或 BVH
  
Step 3: 窄相检测（Narrow Phase Collision Detection）
  对宽相通过的物体对，进行精确碰撞检测
  算法：GJK + EPA（凸多面体）
  
Step 4: 约束求解（Constraint Solver）
  计算碰撞响应力
  求解关节约束
  
Step 5: 积分（Integration）
  根据力/速度/加速度更新位置
  
Step 6: 回调（Callbacks）
  触发OnCollisionEnter/Stay/Exit
  触发OnTriggerEnter/Stay/Exit
  
Step 7: 同步回来（FetchResults）
  将PhysX计算结果写回Unity Transform
```

### 1.2 Rigidbody工作原理

```csharp
// Rigidbody的内部工作机制

// 运动方程：
// F = m × a  （牛顿第二定律）
// v = v₀ + a × Δt  （速度积分）
// x = x₀ + v × Δt  （位置积分）

// Unity的半隐式欧拉积分（默认）
// velocity += acceleration * fixedDeltaTime
// position += velocity * fixedDeltaTime
// 特点：简单，计算快，但对大时间步长不稳定

// 为什么需要FixedUpdate？
// - 物理需要固定时间步长才能稳定
// - 帧率波动（60fps→20fps）会导致物理不稳定
// - fixedDeltaTime = 0.02（默认50fps物理更新）

// 物理更新优先级
// FixedUpdate执行时机：
// 实际帧时间 = 0.033s（30fps）
// fixedDeltaTime = 0.016s（60fps物理）
// 那一帧会执行 0.033/0.016 ≈ 2次 FixedUpdate

public class VehiclePhysics : MonoBehaviour
{
    private Rigidbody _rb;
    
    void Awake()
    {
        _rb = GetComponent<Rigidbody>();
        
        // 重要配置
        _rb.mass = 1500f;             // 质量（kg）
        _rb.drag = 0.05f;             // 线性阻力
        _rb.angularDrag = 0.1f;       // 角阻力
        _rb.interpolation = RigidbodyInterpolation.Interpolate; // 视觉插值（防止抖动）
        _rb.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic; // 连续碰撞（高速物体）
    }
    
    void FixedUpdate()
    {
        // 物理操作必须在FixedUpdate中！
        Vector3 engineForce = transform.forward * _throttle * _engineForce;
        _rb.AddForce(engineForce, ForceMode.Force);
        
        // 轮子悬挂力（向上的弹力）
        for (int i = 0; i < 4; i++)
        {
            ApplySuspensionForce(_wheelTransforms[i]);
        }
    }
    
    void ApplySuspensionForce(Transform wheel)
    {
        Ray ray = new Ray(wheel.position, -wheel.up);
        if (Physics.Raycast(ray, out var hit, _suspensionRestLength))
        {
            float compression = _suspensionRestLength - hit.distance;
            float springForce = compression * _springStrength;
            float damperForce = Vector3.Dot(_rb.GetPointVelocity(wheel.position), wheel.up) * _damperStrength;
            
            _rb.AddForceAtPosition(
                wheel.up * (springForce - damperForce), 
                wheel.position, 
                ForceMode.Force
            );
        }
    }
    
    [SerializeField] private Transform[] _wheelTransforms;
    private float _throttle, _engineForce = 5000f;
    private float _suspensionRestLength = 0.5f;
    private float _springStrength = 30000f, _damperStrength = 3000f;
}
```

---

## 二、碰撞检测优化

### 2.1 碰撞层级矩阵（Layer Matrix）

```
// 最重要的物理优化：减少不必要的碰撞检测

// Project Settings → Physics → Layer Collision Matrix
// 配置哪些层之间需要检测碰撞

// 示例：
// Player vs Enemy：需要（攻击碰撞）
// Player vs Player：不需要（穿透）
// UI vs 任何物理层：不需要

// 代码中指定碰撞层
private int _layerMask;

void Start()
{
    // 射线只检测Enemy层
    _layerMask = LayerMask.GetMask("Enemy", "Obstacle");
}

void Update()
{
    // 使用LayerMask限制射线检测范围（性能提升5-10倍！）
    if (Physics.Raycast(transform.position, transform.forward, out var hit, 100f, _layerMask))
    {
        // 处理碰撞
    }
}
```

### 2.2 碰撞体形状优化

```
碰撞体性能从低到高（开销从小到大）：

球形（Sphere Collider）：
  检测最快（O(1)球-球相交测试）
  适用：子弹、抛射物、飞行物

胶囊体（Capsule Collider）：
  很快（圆柱+两个半球）
  适用：角色控制器（人形）

盒体（Box Collider）：
  较快（AABB检测）
  适用：方形物体、墙壁、箱子

凸多面体（Mesh Collider with Convex）：
  较慢（GJK算法）
  适用：不规则形状
  注意：顶点数不超过255！

凹多面体（Mesh Collider）：
  最慢（只能作为静态碰撞体！）
  不能用于移动的Rigidbody
  适用：地形、复杂静态场景
```

```csharp
// 角色碰撞体优化：用基础形状代替Mesh Collider
void SetupCharacterColliders()
{
    // ❌ 用精确模型碰撞（性能极差）
    // var meshCollider = gameObject.AddComponent<MeshCollider>();
    // meshCollider.sharedMesh = characterMesh;
    
    // ✅ 用组合基础形状近似（性能好，效果够用）
    // 躯干：胶囊体
    var capsule = gameObject.AddComponent<CapsuleCollider>();
    capsule.center = new Vector3(0, 0.9f, 0);
    capsule.radius = 0.3f;
    capsule.height = 1.8f;
    
    // 头部：球形（额外精度）
    var head = new GameObject("HeadCollider").AddComponent<SphereCollider>();
    head.transform.SetParent(transform);
    head.transform.localPosition = new Vector3(0, 1.7f, 0);
    head.radius = 0.2f;
}
```

---

## 三、触发器 vs 碰撞体

```csharp
// 触发器（IsTrigger = true）：
// - 不产生物理响应（不会推开物体）
// - 触发 OnTriggerEnter/Stay/Exit
// - 性能比碰撞体略好（不需要碰撞响应计算）

// 碰撞体：
// - 产生物理响应（推开、反弹）
// - 触发 OnCollisionEnter/Stay/Exit
// - 包含接触点信息（法线、冲量等）

// 什么时候用触发器：
// - 范围检测（加血、拾取道具、区域进入）
// - 伤害区域（AOE范围）
// - 场景交互区域（NPC对话范围）

// 什么时候用碰撞体：
// - 角色控制器（不穿墙）
// - 弹道物理（子弹反弹）
// - 车辆物理（车轮碰地）

public class LootZone : MonoBehaviour
{
    // ✅ 拾取区域用触发器
    void OnTriggerEnter(Collider other)
    {
        if (other.CompareTag("Player"))
        {
            // 玩家进入拾取范围
            GetComponent<Loot>().Collect(other.GetComponent<PlayerInventory>());
        }
    }
}
```

---

## 四、高性能物理场景设计

### 4.1 静态碰撞体优化

```csharp
// 静态碰撞体（没有Rigidbody的Collider）：
// Unity会为所有静态碰撞体构建加速结构（BVH）
// 移动静态碰撞体非常昂贵！（重建BVH）

// ❌ 错误：在Update中移动没有Rigidbody的碰撞体
void Update()
{
    transform.position += Vector3.right * Time.deltaTime; // 重建BVH！
}

// ✅ 如果物体需要移动，添加Rigidbody（设为Kinematic）
void Start()
{
    var rb = gameObject.AddComponent<Rigidbody>();
    rb.isKinematic = true; // 运动学刚体：可以移动，但不受物理力影响
}

void Update()
{
    _rigidbody.MovePosition(transform.position + Vector3.right * Time.deltaTime); // 正确
}
```

### 4.2 PhysX场景设置优化

```csharp
// Project Settings → Physics 关键设置

// Default Solver Iterations（默认6）：
// - 更高值：碰撞更稳定，更贵
// - 建议：4-6（普通游戏），8-12（布娃娃/精确关节）

// Fixed Timestep（默认0.02）：
// - 更小值：物理更稳定，每帧更多物理步骤
// - 建议：0.02（50fps物理，标准），0.016（60fps物理，竞技）

// Broadphase Type：
// - Sweep and Prune：适合大场景（对象数量>500）
// - Multibox Pruning：适合中等场景
// - AutomaticBoxPruning：自动（推荐默认）

// 代码中调整物理频率（针对特定场景）
void AdjustPhysicsForCombat(bool isCombat)
{
    if (isCombat)
    {
        Time.fixedDeltaTime = 0.016f; // 60fps物理（战斗精度更高）
        Physics.defaultSolverIterations = 8;
    }
    else
    {
        Time.fixedDeltaTime = 0.033f; // 30fps物理（省性能）
        Physics.defaultSolverIterations = 4;
    }
}
```

---

## 五、自定义物理行为

### 5.1 不用PhysX实现的轻量物理

```csharp
// 大量简单物理对象（如弹幕），自己写比PhysX更快
// 因为PhysX的调度开销 > 简单运动计算

[BurstCompile]
public struct BulletMoveJob : IJobParallelFor
{
    public NativeArray<float3> positions;
    public NativeArray<float3> velocities;
    [ReadOnly] public float deltaTime;
    [ReadOnly] public float gravity;
    
    public void Execute(int i)
    {
        // 简单抛体运动（比PhysX快10倍以上，因为没有调度开销）
        velocities[i] += new float3(0, -gravity * deltaTime, 0);
        positions[i] += velocities[i] * deltaTime;
    }
}

public class BulletSystem : MonoBehaviour
{
    private NativeArray<float3> _positions;
    private NativeArray<float3> _velocities;
    private const int MAX_BULLETS = 10000;
    
    void Update()
    {
        var job = new BulletMoveJob
        {
            positions = _positions,
            velocities = _velocities,
            deltaTime = Time.deltaTime,
            gravity = 9.8f
        };
        
        job.Schedule(MAX_BULLETS, 128).Complete();
        
        // 碰撞检测（自定义，只检测必要的）
        DetectBulletHits();
    }
    
    void DetectBulletHits()
    {
        // 对大量子弹使用批量射线检测
        var commands = new NativeArray<RaycastCommand>(MAX_BULLETS, Allocator.TempJob);
        var results = new NativeArray<RaycastHit>(MAX_BULLETS, Allocator.TempJob);
        
        for (int i = 0; i < MAX_BULLETS; i++)
        {
            commands[i] = new RaycastCommand(
                _positions[i], 
                math.normalize(_velocities[i]),
                QueryParameters.Default,
                math.length(_velocities[i]) * Time.deltaTime // 这一帧移动距离
            );
        }
        
        // 批量射线检测（并行，比循环调用Physics.Raycast快得多）
        RaycastCommand.ScheduleBatch(commands, results, 128).Complete();
        
        for (int i = 0; i < MAX_BULLETS; i++)
        {
            if (results[i].colliderInstanceID != 0)
            {
                // 命中！
                HandleBulletHit(i, results[i]);
            }
        }
        
        commands.Dispose();
        results.Dispose();
    }
    
    void HandleBulletHit(int bulletIndex, RaycastHit hit) { }
}
```

---

## 六、布娃娃系统（Ragdoll）

```csharp
// 布娃娃：角色死亡时切换到物理驱动的骨骼
public class RagdollSystem : MonoBehaviour
{
    private Animator _animator;
    private Rigidbody[] _ragdollBodies;
    private Collider[] _ragdollColliders;
    private CharacterController _controller;
    
    void Awake()
    {
        _animator = GetComponent<Animator>();
        _controller = GetComponent<CharacterController>();
        
        // 获取所有布娃娃刚体和碰撞体（子节点）
        _ragdollBodies = GetComponentsInChildren<Rigidbody>();
        _ragdollColliders = GetComponentsInChildren<Collider>();
    }
    
    // 开启布娃娃
    public void EnableRagdoll(Vector3 deathForce = default)
    {
        // 禁用动画控制
        _animator.enabled = false;
        _controller.enabled = false;
        
        // 启用所有刚体
        foreach (var rb in _ragdollBodies)
        {
            rb.isKinematic = false;
            rb.useGravity = true;
        }
        
        // 施加死亡冲力（让布娃娃按受击方向飞出）
        if (deathForce != Vector3.zero)
        {
            foreach (var rb in _ragdollBodies)
            {
                rb.AddForce(deathForce, ForceMode.Impulse);
            }
        }
    }
    
    // 关闭布娃娃（角色复活时）
    public void DisableRagdoll()
    {
        foreach (var rb in _ragdollBodies)
        {
            rb.isKinematic = true;
            rb.useGravity = false;
        }
        
        _animator.enabled = true;
        _controller.enabled = true;
    }
    
    // 优化：布娃娃静止后关闭物理更新
    IEnumerator CheckRagdollSleep()
    {
        yield return new WaitForSeconds(3f); // 等待3秒
        
        bool allSleeping = _ragdollBodies.All(rb => rb.IsSleeping());
        if (allSleeping)
        {
            // 所有刚体静止，关闭物理（省性能）
            foreach (var rb in _ragdollBodies)
                rb.isKinematic = true;
        }
    }
}
```

---

## 总结

物理系统优化核心原则：

```
性能排序（从便宜到昂贵）：
球形/胶囊体碰撞 < 盒体碰撞 < 凸体碰撞 < 凹体Mesh碰撞

关键优化手段：
1. Layer Collision Matrix：减少不必要的碰撞对检测
2. 使用Trigger代替碰撞体（范围检测场景）
3. 静态碰撞体不移动
4. 大量简单物体用Jobs自定义物理
5. 合理设置Solver Iterations
6. 高速物体用Continuous碰撞检测

技术负责人职责：
→ 制定物理使用规范（哪些情况用哪种碰撞体）
→ 建立物理性能监控（每帧物理耗时）
→ 合理规划物理层级（减少检测对数）
```
