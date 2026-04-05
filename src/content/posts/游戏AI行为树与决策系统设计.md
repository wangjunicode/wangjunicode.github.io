---
title: 游戏AI行为树与决策系统设计
description: 全面解析游戏AI核心技术：行为树（Behavior Tree）、有限状态机（FSM）、效用AI（Utility AI）的原理与实现，从NPC行为设计到商业级AI框架。
published: 2026-03-21
category: 技术基础
tags: [游戏AI, 行为树, 状态机, FSM, NPC设计, 人工智能]
encryptedKey: henhaoji123
---

# 游戏AI行为树与决策系统设计

游戏 AI 是让虚拟世界"活起来"的核心。从简单的 NPC 巡逻到复杂的 Boss 战术决策，背后都有一套精心设计的决策系统。本文系统介绍从 FSM 到行为树再到效用 AI 的完整技术体系。

## 一、有限状态机（FSM）

### 1.1 基本实现

FSM 是最直观的 AI 设计方式，每个 AI 处于一种状态，并在特定条件下转换。

```csharp
// 状态枚举
public enum EnemyState
{
    Idle,
    Patrol,
    Chase,
    Attack,
    Flee,
    Dead
}

// 状态机基类
public abstract class State
{
    protected EnemyController enemy;
    
    public State(EnemyController enemy) => this.enemy = enemy;
    
    public abstract void OnEnter();
    public abstract void OnUpdate(float deltaTime);
    public abstract void OnExit();
}

// 巡逻状态
public class PatrolState : State
{
    private List<Vector3> _waypoints;
    private int _currentWaypointIndex;
    private float _waitTimer;
    
    public PatrolState(EnemyController enemy, List<Vector3> waypoints) 
        : base(enemy)
    {
        _waypoints = waypoints;
    }
    
    public override void OnEnter()
    {
        Debug.Log("进入巡逻状态");
        enemy.SetDestination(_waypoints[_currentWaypointIndex]);
    }
    
    public override void OnUpdate(float deltaTime)
    {
        // 检测玩家
        if (enemy.CanSeePlayer())
        {
            enemy.ChangeState(new ChaseState(enemy));
            return;
        }
        
        // 到达路点
        if (enemy.HasReachedDestination())
        {
            _waitTimer += deltaTime;
            if (_waitTimer >= 2f)
            {
                _waitTimer = 0;
                _currentWaypointIndex = (_currentWaypointIndex + 1) % _waypoints.Count;
                enemy.SetDestination(_waypoints[_currentWaypointIndex]);
            }
        }
    }
    
    public override void OnExit()
    {
        enemy.StopMoving();
    }
}

// 状态机控制器
public class EnemyController : MonoBehaviour
{
    private State _currentState;
    
    public void ChangeState(State newState)
    {
        _currentState?.OnExit();
        _currentState = newState;
        _currentState.OnEnter();
    }
    
    void Update()
    {
        _currentState?.OnUpdate(Time.deltaTime);
    }
}
```

### 1.2 FSM 的局限性

```
问题：状态爆炸

简单敌人：Idle → Patrol → Chase → Attack（4个状态，12条转换线）

复杂敌人：
  + 受伤状态
  + 掩护状态  
  + 召唤状态
  + 特殊技能状态
  → 很快变成意大利面条式的复杂图
```

## 二、行为树（Behavior Tree）

行为树是目前商业游戏 AI 最主流的方案（UE5、Unity等引擎原生支持）。

### 2.1 节点类型

```
控制节点（Control Nodes）：
├── Sequence（序列）：子节点按顺序执行，全部成功才成功（AND逻辑）
├── Selector（选择）：子节点按顺序执行，第一个成功就成功（OR逻辑）
└── Parallel（并行）：所有子节点同时执行

叶子节点（Leaf Nodes）：
├── Action（动作）：执行具体行为（移动、攻击、播放动画）
└── Condition（条件）：检查条件（是否看到玩家、HP是否低于50%）

装饰节点（Decorator Nodes）：
├── Inverter（反转）：将子节点结果取反
├── Repeater（重复）：重复执行子节点N次
└── Timeout（超时）：超过时间限制则失败
```

### 2.2 节点返回值

```csharp
public enum NodeStatus
{
    Success,  // 任务完成
    Failure,  // 任务失败
    Running   // 任务进行中（异步操作）
}
```

### 2.3 完整行为树实现

```csharp
// 节点基类
public abstract class BTNode
{
    public abstract NodeStatus Evaluate(BTContext context);
}

// Sequence：所有子节点成功才成功
public class SequenceNode : BTNode
{
    private List<BTNode> _children;
    private int _currentIndex;
    
    public SequenceNode(params BTNode[] children)
    {
        _children = new List<BTNode>(children);
    }
    
    public override NodeStatus Evaluate(BTContext context)
    {
        // 从上次暂停的位置继续（支持 Running 状态）
        for (int i = _currentIndex; i < _children.Count; i++)
        {
            var status = _children[i].Evaluate(context);
            
            switch (status)
            {
                case NodeStatus.Running:
                    _currentIndex = i; // 记录暂停位置
                    return NodeStatus.Running;
                    
                case NodeStatus.Failure:
                    _currentIndex = 0;
                    return NodeStatus.Failure;
            }
        }
        
        _currentIndex = 0;
        return NodeStatus.Success;
    }
}

// Selector：第一个成功就返回成功
public class SelectorNode : BTNode
{
    private List<BTNode> _children;
    
    public SelectorNode(params BTNode[] children)
    {
        _children = new List<BTNode>(children);
    }
    
    public override NodeStatus Evaluate(BTContext context)
    {
        foreach (var child in _children)
        {
            var status = child.Evaluate(context);
            if (status != NodeStatus.Failure)
                return status;
        }
        return NodeStatus.Failure;
    }
}

// 条件节点
public class CheckCanSeePlayer : BTNode
{
    public override NodeStatus Evaluate(BTContext context)
    {
        return context.Enemy.CanSeePlayer() 
            ? NodeStatus.Success 
            : NodeStatus.Failure;
    }
}

// 动作节点
public class MoveToPlayer : BTNode
{
    public override NodeStatus Evaluate(BTContext context)
    {
        var enemy = context.Enemy;
        
        if (Vector3.Distance(enemy.Position, enemy.PlayerPosition) < 0.5f)
            return NodeStatus.Success;
        
        enemy.MoveTowards(enemy.PlayerPosition);
        return NodeStatus.Running;
    }
}

// 组装行为树（描述敌人 AI 逻辑）
public class EnemyBTBuilder
{
    public static BTNode BuildEnemyTree()
    {
        return new SelectorNode(
            // 分支1：如果快死了就逃跑
            new SequenceNode(
                new CheckHPBelow(0.2f),
                new FleeFromPlayer()
            ),
            
            // 分支2：如果看到玩家就追击并攻击
            new SequenceNode(
                new CheckCanSeePlayer(),
                new SelectorNode(
                    // 近了就攻击
                    new SequenceNode(
                        new CheckInAttackRange(),
                        new AttackPlayer()
                    ),
                    // 不在攻击范围就追击
                    new MoveToPlayer()
                )
            ),
            
            // 分支3：默认巡逻
            new PatrolWaypoints()
        );
    }
}
```

### 2.4 黑板系统（Blackboard）

行为树各节点通过黑板共享数据：

```csharp
// 黑板：AI 的"工作记忆"
public class Blackboard
{
    private Dictionary<string, object> _data = new();
    
    public void Set<T>(string key, T value) => _data[key] = value;
    
    public T Get<T>(string key)
    {
        if (_data.TryGetValue(key, out var val) && val is T typed)
            return typed;
        return default;
    }
    
    public bool Has(string key) => _data.ContainsKey(key);
}

// 上下文包含黑板
public class BTContext
{
    public EnemyController Enemy;
    public Blackboard Blackboard = new();
}

// 节点通过黑板通信
public class FindCoverPosition : BTNode
{
    public override NodeStatus Evaluate(BTContext context)
    {
        var coverPos = FindNearestCover(context.Enemy.Position);
        if (coverPos == null) return NodeStatus.Failure;
        
        // 写入黑板，供后续节点使用
        context.Blackboard.Set("CoverPosition", coverPos.Value);
        return NodeStatus.Success;
    }
}

public class MoveToCover : BTNode
{
    public override NodeStatus Evaluate(BTContext context)
    {
        // 读取黑板数据
        if (!context.Blackboard.Has("CoverPosition"))
            return NodeStatus.Failure;
        
        var coverPos = context.Blackboard.Get<Vector3>("CoverPosition");
        context.Enemy.MoveTowards(coverPos);
        return NodeStatus.Running;
    }
}
```

## 三、效用 AI（Utility AI）

效用 AI 更适合"有人情味"的 NPC（RPG 角色、模拟类游戏）。

```csharp
// 每个行为有一个效用值（0~1），AI 选择效用最高的行为
public class UtilityAI
{
    private List<IAction> _actions;
    
    public IAction SelectBestAction(AIContext context)
    {
        IAction bestAction = null;
        float bestScore = float.MinValue;
        
        foreach (var action in _actions)
        {
            float score = action.CalculateUtility(context);
            
            // 加入随机扰动，避免 AI 行为过于机械
            score += UnityEngine.Random.Range(-0.05f, 0.05f);
            
            if (score > bestScore)
            {
                bestScore = score;
                bestAction = action;
            }
        }
        
        return bestAction;
    }
}

// 效用计算示例：攻击玩家的效用
public class AttackPlayerAction : IAction
{
    public float CalculateUtility(AIContext context)
    {
        float score = 0;
        
        // 距离越近，效用越高
        float distScore = 1f - Mathf.Clamp01(context.DistanceToPlayer / 20f);
        score += distScore * 0.4f;
        
        // 生命值越高，战斗意愿越强
        float hpScore = context.HPPercent;
        score += hpScore * 0.3f;
        
        // 处于愤怒状态，加权
        if (context.IsAngered) score += 0.3f;
        
        return Mathf.Clamp01(score);
    }
}
```

## 四、寻路系统（NavMesh + A*）

```csharp
// Unity NavMesh 使用
public class SmartEnemy : MonoBehaviour
{
    private NavMeshAgent _agent;
    private Transform _player;
    
    private void Start()
    {
        _agent = GetComponent<NavMeshAgent>();
        
        // 配置导航参数
        _agent.speed = 3.5f;
        _agent.stoppingDistance = 1.5f;
        _agent.angularSpeed = 120f;
        
        // 开启 NavMesh Obstacle Avoidance
        _agent.obstacleAvoidanceType = ObstacleAvoidanceType.HighQualityObstacleAvoidance;
    }
    
    // 动态障碍物规避
    public void ChasePlayer()
    {
        // 预测玩家位置（考虑延迟）
        Vector3 predictedPos = _player.position + 
                               _player.GetComponent<Rigidbody>().velocity * 0.5f;
        
        // 判断是否可到达
        NavMeshPath path = new NavMeshPath();
        if (_agent.CalculatePath(predictedPos, path))
        {
            if (path.status == NavMeshPathStatus.PathComplete)
                _agent.SetDestination(predictedPos);
            else
                _agent.SetDestination(_player.position); // 直接追击
        }
    }
    
    // 战术撤退（找最近的掩体）
    public void TacticalRetreat()
    {
        Collider[] covers = Physics.OverlapSphere(transform.position, 15f, 
                                                    LayerMask.GetMask("Cover"));
        
        Vector3 bestCover = Vector3.zero;
        float bestScore = float.MinValue;
        
        foreach (var cover in covers)
        {
            // 评分：距离玩家越远越好，距离自己越近越好
            float distToPlayer = Vector3.Distance(cover.transform.position, _player.position);
            float distToSelf = Vector3.Distance(cover.transform.position, transform.position);
            float score = distToPlayer / 20f - distToSelf / 10f;
            
            if (score > bestScore)
            {
                bestScore = score;
                bestCover = cover.transform.position;
            }
        }
        
        if (bestCover != Vector3.zero)
            _agent.SetDestination(bestCover);
    }
}
```

## 五、大规模 AI 优化

```csharp
// LOD AI：根据距离降低 AI 更新频率
public class AILODManager : MonoBehaviour
{
    private Transform _player;
    private List<AIAgent> _agents = new();
    
    void Update()
    {
        int frameCount = Time.frameCount;
        
        foreach (var agent in _agents)
        {
            float dist = Vector3.Distance(agent.transform.position, _player.position);
            
            // 近距离：每帧更新
            if (dist < 30f)
            {
                agent.UpdateAI();
            }
            // 中距离：每5帧更新
            else if (dist < 100f && frameCount % 5 == agent.AgentId % 5)
            {
                agent.UpdateAI();
            }
            // 远距离：每30帧更新（基本静止）
            else if (dist < 300f && frameCount % 30 == agent.AgentId % 30)
            {
                agent.UpdateAI();
            }
            // 超远：停止更新
        }
    }
}
```

## 六、选型建议

| AI 系统 | 适合场景 | 优势 | 劣势 |
|---------|----------|------|------|
| FSM | 简单 NPC、小游戏 | 实现简单、直观 | 状态爆炸、难维护 |
| 行为树 | 动作游戏、FPS、MOBA | 结构清晰、可视化编辑 | 有一定学习成本 |
| 效用 AI | RPG、模拟经营、沙盒 | 行为自然、权重调节灵活 | 调参复杂 |
| GOAP | 高智能敌人（如仿真类） | 目标导向、高智能感 | 计算开销大 |
| ML-Agent | 竞技游戏、赛车 | 自主学习、超高水平 | 训练成本极高 |

> 💡 **实用建议**：90% 的商业游戏用行为树就够了。UE5 内置 AI 行为树，Unity 可用 Behavior Designer（付费）或 NPBehave（免费）。真正能拉开差距的不是技术方案，而是**行为数据的精细调调**——一个行为树里三个节点精心设计的 Boss，比一个 100 个节点但未经测试的 Boss 好玩得多。
