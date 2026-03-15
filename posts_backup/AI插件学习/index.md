---
title: Behavior Designer 行为树实战：从零到 NPC AI
published: 2020-09-06
description: "系统讲解行为树核心概念与 Behavior Designer 实战：从 Selector/Sequence/Parallel 节点类型到完整的 NPC AI 实现（巡逻→发现敌人→追击→攻击→返回），提供自定义 Action 节点代码，并深入分析行为树与状态机的选型依据。"
tags: [Unity, 游戏AI, 行为树, 游戏开发]
category: 游戏开发
draft: false
---

接触 AI 编程的时候，我先学的是状态机（FSM）。状态机很直观，但做到后期，状态之间的跳转关系会变成一张复杂的蜘蛛网，新增一个"喝药"状态需要修改十几条跳转规则。后来转到行为树，发现在**复杂 AI 逻辑**方面它有着状态机无法比拟的优势。

这篇文章用 Behavior Designer 插件，从基础概念到完整的 NPC AI 实现全程演示。

官方文档：https://opsive.com/support/documentation/behavior-designer/overview/

---

## 行为树基本概念

### 核心思想

行为树把 AI 的行为逻辑组织成一棵树：
- **根节点**向下驱动，每帧（或按需）从根开始执行
- 每个节点执行完毕后返回 `Success`、`Failure` 或 `Running` 三种状态
- 父节点根据子节点的返回状态决定自己的下一步

```
根节点
  └─ Selector（选择器）
        ├─ Sequence（顺序）→ 巡逻逻辑
        └─ Sequence（顺序）→ 攻击逻辑
```

### 四种基础节点类型

#### Selector（选择器）

从左到右依次执行子节点，**遇到第一个 Success 就停止并返回 Success**；所有子节点都 Failure 时返回 Failure。

类比逻辑：`A || B || C`（短路 OR）

```
Selector
  ├─ 有弹药？→ 射击    // 如果有弹药，执行射击，Success，停止
  └─ 换弹         // 如果没弹药，执行换弹
```

#### Sequence（顺序）

从左到右依次执行子节点，**遇到第一个 Failure 就停止并返回 Failure**；所有子节点都 Success 时返回 Success。

类比逻辑：`A && B && C`（短路 AND）

```
Sequence
  ├─ 看到敌人？    // 如果没看到敌人，Failure，整个 Sequence 停止
  ├─ 在攻击范围？  // 如果不在范围，Failure，停止
  └─ 执行攻击     // 前两步都 Success，才执行攻击
```

#### Action（动作节点）

叶子节点，执行具体行为：移动到目标点、播放动画、造成伤害……返回 `Success`（执行完毕）或 `Running`（正在执行中）。

#### Condition（条件节点）

叶子节点，判断某个条件是否成立：看到敌人吗？血量低于 30%？距离小于 5 米？返回 `Success` 或 `Failure`。

---

## Behavior Designer 核心组件

### 组件结构

```
GameObject
  └─ BehaviorTree (组件)
        ├─ External Behavior (可选，引用外部行为树资产)
        └─ Variables (行为树内部变量，共享数据)
```

### 行为树变量系统

Behavior Designer 支持在行为树内定义变量，节点之间通过变量共享数据：

```csharp
// 在节点代码中访问行为树变量
public class CheckEnemyInRange : Conditional
{
    [SharedVariable] // 标记为共享变量
    public SharedFloat DetectRadius;
    
    [SharedVariable]
    public SharedTransform TargetEnemy; // 输出：检测到的敌人

    public override TaskStatus OnUpdate()
    {
        var colliders = Physics.OverlapSphere(
            transform.position, 
            DetectRadius.Value,
            LayerMask.GetMask("Enemy"));
        
        if (colliders.Length > 0)
        {
            TargetEnemy.Value = colliders[0].transform;
            return TaskStatus.Success;
        }
        return TaskStatus.Failure;
    }
}
```

---

## 实战案例：NPC AI（巡逻→发现敌人→追击→攻击→返回）

### 行为树结构设计

```
根节点（Selector）
  ├─ Sequence：攻击逻辑（优先级最高）
  │    ├─ Condition: 在攻击范围内？
  │    └─ Action: 执行攻击
  │
  ├─ Sequence：追击逻辑
  │    ├─ Condition: 看到目标？
  │    └─ Action: 移动到目标
  │
  └─ Sequence：巡逻逻辑（兜底）
       ├─ Action: 移动到巡逻点
       └─ Action: 等待
```

### 自定义 Condition 节点：检测敌人

```csharp
using BehaviorDesigner.Runtime;
using BehaviorDesigner.Runtime.Tasks;
using UnityEngine;

[TaskCategory("NPC/Conditions")]
[TaskDescription("检测指定半径内是否有敌人")]
public class DetectEnemy : Conditional
{
    [Tooltip("检测半径")]
    public SharedFloat DetectRadius = 10f;
    
    [Tooltip("敌人层级")]
    public LayerMask EnemyLayer;
    
    [Tooltip("输出：检测到的目标（用于其他节点引用）")]
    [SharedVariable]
    public SharedTransform DetectedTarget;

    private Transform _transform;

    public override void OnAwake()
    {
        _transform = GetComponent<Transform>();
    }

    public override TaskStatus OnUpdate()
    {
        var colliders = Physics.OverlapSphere(_transform.position, DetectRadius.Value, EnemyLayer);
        
        if (colliders.Length > 0)
        {
            // 取最近的敌人
            Transform nearest = null;
            float minDist = float.MaxValue;
            foreach (var col in colliders)
            {
                float d = Vector3.Distance(_transform.position, col.transform.position);
                if (d < minDist)
                {
                    minDist = d;
                    nearest = col.transform;
                }
            }
            DetectedTarget.Value = nearest;
            return TaskStatus.Success;
        }
        
        DetectedTarget.Value = null;
        return TaskStatus.Failure;
    }

    // 编辑器中显示检测范围 Gizmo
    public override void OnDrawGizmos()
    {
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(Owner.transform.position, DetectRadius.Value);
    }
}
```

### 自定义 Action 节点：移动到目标

```csharp
using BehaviorDesigner.Runtime;
using BehaviorDesigner.Runtime.Tasks;
using UnityEngine;
using UnityEngine.AI;

[TaskCategory("NPC/Actions")]
[TaskDescription("移动到目标位置，到达后返回 Success")]
public class MoveToTarget : Action
{
    [SharedVariable]
    public SharedTransform Target;
    
    public SharedFloat StoppingDistance = 1.5f;
    public SharedFloat MoveSpeed = 5f;

    private NavMeshAgent _agent;

    public override void OnAwake()
    {
        _agent = GetComponent<NavMeshAgent>();
        _agent.speed = MoveSpeed.Value;
    }

    public override void OnStart()
    {
        if (Target.Value != null)
        {
            _agent.SetDestination(Target.Value.position);
            _agent.isStopped = false;
        }
    }

    public override TaskStatus OnUpdate()
    {
        if (Target.Value == null) return TaskStatus.Failure;
        
        // 追击目标时，持续更新目标位置
        _agent.SetDestination(Target.Value.position);

        float dist = Vector3.Distance(transform.position, Target.Value.position);
        if (dist <= StoppingDistance.Value)
        {
            _agent.isStopped = true;
            return TaskStatus.Success; // 到达目标
        }
        
        return TaskStatus.Running; // 还在移动中
    }

    public override void OnEnd()
    {
        _agent.isStopped = true;
    }
}
```

### 自定义 Action 节点：执行攻击

```csharp
using BehaviorDesigner.Runtime;
using BehaviorDesigner.Runtime.Tasks;
using UnityEngine;

[TaskCategory("NPC/Actions")]
[TaskDescription("对目标执行一次攻击，播放动画，造成伤害")]
public class AttackTarget : Action
{
    [SharedVariable]
    public SharedTransform Target;
    
    public SharedFloat AttackDamage = 10f;
    public SharedFloat AttackCooldown = 1.5f;  // 攻击冷却时间

    private Animator _animator;
    private float _attackTimer;
    private bool _damageDealt;
    private static readonly int AttackHash = Animator.StringToHash("Attack");

    public override void OnAwake()
    {
        _animator = GetComponent<Animator>();
    }

    public override void OnStart()
    {
        _attackTimer = 0f;
        _damageDealt = false;
        _animator.SetTrigger(AttackHash);
        
        // 朝向目标
        if (Target.Value != null)
        {
            var dir = Target.Value.position - transform.position;
            dir.y = 0;
            transform.rotation = Quaternion.LookRotation(dir);
        }
    }

    public override TaskStatus OnUpdate()
    {
        _attackTimer += Time.deltaTime;
        
        // 动画中段造成伤害（比如攻击动画0.3秒时命中）
        if (!_damageDealt && _attackTimer >= 0.3f)
        {
            DealDamage();
            _damageDealt = true;
        }
        
        // 等待攻击冷却结束
        if (_attackTimer >= AttackCooldown.Value)
        {
            return TaskStatus.Success;
        }
        
        return TaskStatus.Running;
    }

    private void DealDamage()
    {
        if (Target.Value == null) return;
        
        float dist = Vector3.Distance(transform.position, Target.Value.position);
        if (dist <= 2f) // 实际攻击范围判定
        {
            var health = Target.Value.GetComponent<HealthComponent>();
            health?.TakeDamage((int)AttackDamage.Value);
        }
    }
}
```

### 自定义 Action 节点：巡逻

```csharp
using BehaviorDesigner.Runtime;
using BehaviorDesigner.Runtime.Tasks;
using UnityEngine;
using UnityEngine.AI;

[TaskCategory("NPC/Actions")]
[TaskDescription("在设定的巡逻点之间来回移动")]
public class Patrol : Action
{
    [Tooltip("巡逻路径点列表")]
    public SharedGameObjectList PatrolPoints;
    
    public SharedFloat StoppingDistance = 0.5f;
    public SharedFloat WaitTime = 2f; // 到达巡逻点后的等待时间

    private NavMeshAgent _agent;
    private int _currentIndex;
    private float _waitTimer;
    private bool _isWaiting;

    public override void OnAwake()
    {
        _agent = GetComponent<NavMeshAgent>();
    }

    public override void OnStart()
    {
        _isWaiting = false;
        _waitTimer = 0f;
        MoveToNextPoint();
    }

    public override TaskStatus OnUpdate()
    {
        if (PatrolPoints.Value == null || PatrolPoints.Value.Count == 0)
            return TaskStatus.Failure;

        if (_isWaiting)
        {
            _waitTimer += Time.deltaTime;
            if (_waitTimer >= WaitTime.Value)
            {
                _isWaiting = false;
                _currentIndex = (_currentIndex + 1) % PatrolPoints.Value.Count;
                MoveToNextPoint();
            }
            return TaskStatus.Running;
        }

        if (_agent.remainingDistance <= StoppingDistance.Value && !_agent.pathPending)
        {
            _isWaiting = true;
            _waitTimer = 0f;
            _agent.isStopped = true;
        }

        return TaskStatus.Running; // 巡逻是持续行为，永远 Running
    }

    private void MoveToNextPoint()
    {
        if (PatrolPoints.Value.Count == 0) return;
        _agent.isStopped = false;
        _agent.SetDestination(PatrolPoints.Value[_currentIndex].transform.position);
    }

    public override void OnEnd()
    {
        _agent.isStopped = true;
    }
}
```

---

## 中断机制（Abort Type）

行为树的强大之处在于**中断**：高优先级的分支可以打断正在运行的低优先级分支。

```
Selector
  ├─ Sequence [AbortType = LowerPriority]  ← 这个分支可以打断下面的分支
  │    ├─ Condition: 发现敌人？
  │    └─ Action: 追击
  │
  └─ Action: 巡逻    ← 正在巡逻时，如果发现敌人，上面的分支会立即打断这里
```

- `Self`：仅中断自己分支内的节点
- `Lower Priority`：中断优先级更低（排在右边/下面）的节点
- `Both`：两者都中断

---

## 行为树 vs 状态机选型建议

| 维度 | 行为树 | 状态机（FSM）|
|------|--------|------------|
| **复杂度** | 适合复杂 AI，层次清晰 | 简单状态逻辑更直观 |
| **可维护性** | 节点可复用，新增行为无需修改已有节点 | 状态多了跳转关系复杂，难维护 |
| **并行执行** | 原生支持（Parallel 节点） | 需要多个 FSM 并行 |
| **调试** | 可视化节点状态，实时观察 | 需要自己打 Log |
| **学习曲线** | 稍高，需要理解节点语义 | 较低，直观 |
| **性能** | 每帧遍历树有一定开销 | 单状态切换开销低 |

**我的建议**：
- NPC AI 逻辑超过 5 个状态 → 用行为树
- 角色自身状态管理（Idle/Move/Attack/Die）→ 用状态机
- 两者可以结合：状态机管理角色状态，行为树负责 AI 决策

行为树最大的优点是**可扩展性**：当策划说"加一个 NPC 会躲掩体"的需求时，你只需要写一个新的 `TakeCover` 节点插入行为树，不需要修改任何现有代码。这在项目后期非常宝贵。
