---
title: "游戏AI系统设计：从行为树到机器学习"
description: "系统解析游戏AI的完整技术栈，包括有限状态机、行为树、GOAP目标导向规划、寻路导航、群体AI，以及如何利用机器学习打造更智能的NPC"
published: 2025-03-21
tags: ["游戏AI", "行为树", "状态机", "寻路", "NavMesh", "机器学习"]
---

# 游戏AI系统设计：从行为树到机器学习

> 好的游戏AI不是"最强的AI"，而是"最让玩家有乐趣的AI"。理解这个本质，才能设计出既智能又有趣的NPC。

---

## 一、游戏AI的设计哲学

### 1.1 游戏AI与通用AI的根本区别

```
通用AI目标：解决问题，越准确越好
游戏AI目标：创造好的游戏体验

游戏AI的独特要求：
1. 可预测性：玩家能够理解AI行为规律
   （完全随机的AI让玩家感到无聊和沮丧）
   
2. 犯错是必要的：
   - 如果AI永远不犯错，玩家永远赢不了 → 挫败
   - AI要犯"恰到好处"的错误

3. 性能约束：
   - 100个AI × 60fps = 每帧6000次决策
   - 每个AI的决策时间必须 < 0.5ms
   
4. 可调整性：
   - 策划需要通过配置调整AI难度
   - 不能全部硬编码在代码里
```

---

## 二、有限状态机（FSM）

### 2.1 基础FSM实现

```csharp
// 简单但实用的FSM实现
public abstract class AIState
{
    protected AIController _owner;
    
    public AIState(AIController owner) => _owner = owner;
    
    public abstract void OnEnter();
    public abstract void OnUpdate(float deltaTime);
    public abstract void OnExit();
}

public class AIController : MonoBehaviour
{
    private AIState _currentState;
    private Dictionary<System.Type, AIState> _states = new();
    
    protected void RegisterState(AIState state)
    {
        _states[state.GetType()] = state;
    }
    
    public void ChangeState<T>() where T : AIState
    {
        if (_currentState != null)
        {
            _currentState.OnExit();
        }
        
        _currentState = _states[typeof(T)];
        _currentState.OnEnter();
    }
    
    void Update()
    {
        _currentState?.OnUpdate(Time.deltaTime);
    }
}

// 敌人AI的具体状态
public class EnemyAI : AIController
{
    public Transform player;
    public float detectionRange = 8f;
    public float attackRange = 2f;
    
    void Awake()
    {
        RegisterState(new IdleState(this));
        RegisterState(new ChaseState(this));
        RegisterState(new AttackState(this));
        RegisterState(new FleeState(this));
    }
    
    void Start() => ChangeState<IdleState>();
}

// 巡逻状态
public class IdleState : AIState
{
    public IdleState(AIController owner) : base(owner) { }
    
    public override void OnEnter()
    {
        var enemy = (EnemyAI)_owner;
        // 开始播放Idle动画
        enemy.GetComponent<Animator>().SetBool("IsMoving", false);
    }
    
    public override void OnUpdate(float deltaTime)
    {
        var enemy = (EnemyAI)_owner;
        float dist = Vector3.Distance(enemy.transform.position, enemy.player.position);
        
        if (dist < enemy.detectionRange)
        {
            enemy.ChangeState<ChaseState>(); // 发现玩家，切换到追击状态
        }
    }
    
    public override void OnExit() { }
}

// 追击状态
public class ChaseState : AIState
{
    private NavMeshAgent _agent;
    
    public ChaseState(AIController owner) : base(owner)
    {
        _agent = owner.GetComponent<NavMeshAgent>();
    }
    
    public override void OnEnter()
    {
        _agent.isStopped = false;
        _owner.GetComponent<Animator>().SetBool("IsMoving", true);
    }
    
    public override void OnUpdate(float deltaTime)
    {
        var enemy = (EnemyAI)_owner;
        float dist = Vector3.Distance(enemy.transform.position, enemy.player.position);
        
        if (dist <= enemy.attackRange)
        {
            enemy.ChangeState<AttackState>(); // 进入攻击范围
        }
        else if (dist > enemy.detectionRange * 1.5f)
        {
            enemy.ChangeState<IdleState>(); // 跟丢了
        }
        else
        {
            _agent.SetDestination(enemy.player.position); // 持续追击
        }
    }
    
    public override void OnExit()
    {
        _agent.isStopped = true;
    }
}
```

### 2.2 FSM的局限性

```
FSM的问题（状态爆炸）：
- 5个状态 → 5×4=20个可能的状态转换
- 10个状态 → 10×9=90个可能的状态转换
- 状态越多，转换逻辑越复杂，越难维护

解决方案：层次状态机（HFSM）
将相关状态组合成子状态机
例如：
- 战斗状态（子状态：轻攻击、重攻击、防御）
- 非战斗状态（子状态：巡逻、休息、对话）
```

---

## 三、行为树（Behavior Tree）

### 3.1 行为树核心概念

```
行为树节点类型：

控制节点：
Sequence（序列）：子节点依次执行，全部成功才返回成功
                 有一个失败就返回失败并停止
Selector（选择）：子节点依次尝试，第一个成功的返回成功
                 全部失败才返回失败
Parallel（并行）：同时执行所有子节点

叶子节点：
Action（动作）：执行具体动作（移动、攻击）
Condition（条件）：检查条件（是否看到玩家）

修饰节点：
Inverter（取反）：反转子节点的结果
Repeater（重复）：重复执行子节点N次
Succeeder：无论子节点结果，都返回成功

节点返回值：
Success（成功）
Failure（失败）
Running（运行中，本帧未完成）
```

### 3.2 行为树实现

```csharp
// 行为树框架实现
public enum NodeStatus { Success, Failure, Running }

public abstract class BehaviorNode
{
    public abstract NodeStatus Evaluate(AIBlackboard blackboard);
}

// Sequence节点
public class SequenceNode : BehaviorNode
{
    private List<BehaviorNode> _children;
    private int _currentChild = 0;
    
    public SequenceNode(params BehaviorNode[] children)
    {
        _children = new List<BehaviorNode>(children);
    }
    
    public override NodeStatus Evaluate(AIBlackboard blackboard)
    {
        while (_currentChild < _children.Count)
        {
            var status = _children[_currentChild].Evaluate(blackboard);
            
            if (status == NodeStatus.Running) return NodeStatus.Running;
            if (status == NodeStatus.Failure)
            {
                _currentChild = 0; // 重置
                return NodeStatus.Failure;
            }
            
            _currentChild++;
        }
        
        _currentChild = 0;
        return NodeStatus.Success;
    }
}

// Selector节点
public class SelectorNode : BehaviorNode
{
    private List<BehaviorNode> _children;
    
    public SelectorNode(params BehaviorNode[] children)
    {
        _children = new List<BehaviorNode>(children);
    }
    
    public override NodeStatus Evaluate(AIBlackboard blackboard)
    {
        foreach (var child in _children)
        {
            var status = child.Evaluate(blackboard);
            if (status != NodeStatus.Failure) return status;
        }
        return NodeStatus.Failure;
    }
}

// Condition节点
public class ConditionNode : BehaviorNode
{
    private Func<AIBlackboard, bool> _condition;
    
    public ConditionNode(Func<AIBlackboard, bool> condition)
    {
        _condition = condition;
    }
    
    public override NodeStatus Evaluate(AIBlackboard blackboard)
    {
        return _condition(blackboard) ? NodeStatus.Success : NodeStatus.Failure;
    }
}

// Action节点（异步动作）
public class ActionNode : BehaviorNode
{
    private Func<AIBlackboard, NodeStatus> _action;
    
    public ActionNode(Func<AIBlackboard, NodeStatus> action)
    {
        _action = action;
    }
    
    public override NodeStatus Evaluate(AIBlackboard blackboard)
    {
        return _action(blackboard);
    }
}

// 黑板：AI状态共享数据（不同节点之间通信）
public class AIBlackboard
{
    private Dictionary<string, object> _data = new();
    
    public void Set<T>(string key, T value) => _data[key] = value;
    
    public T Get<T>(string key)
    {
        if (_data.TryGetValue(key, out var value)) return (T)value;
        return default;
    }
    
    public bool Has(string key) => _data.ContainsKey(key);
}

// 构建BOSS行为树
public class BossBehaviorTree : MonoBehaviour
{
    private BehaviorNode _rootNode;
    private AIBlackboard _blackboard;
    
    void Start()
    {
        _blackboard = new AIBlackboard();
        _rootNode = BuildBehaviorTree();
    }
    
    BehaviorNode BuildBehaviorTree()
    {
        return new SelectorNode(
            
            // 优先：血量低于30%时逃跑
            new SequenceNode(
                new ConditionNode(bb => GetHPPercent() < 0.3f),
                new ActionNode(bb => FleeAction(bb))
            ),
            
            // 其次：玩家在攻击范围内则攻击
            new SequenceNode(
                new ConditionNode(bb => IsPlayerInAttackRange()),
                new SelectorNode(
                    // 优先使用技能
                    new SequenceNode(
                        new ConditionNode(bb => IsSkillReady("skill_1")),
                        new ActionNode(bb => CastSkill("skill_1"))
                    ),
                    // 普通攻击
                    new ActionNode(bb => BasicAttack(bb))
                )
            ),
            
            // 然后：追击玩家
            new SequenceNode(
                new ConditionNode(bb => CanSeePlayer()),
                new ActionNode(bb => ChasePlayer(bb))
            ),
            
            // 最后：巡逻
            new ActionNode(bb => Patrol(bb))
        );
    }
    
    void Update()
    {
        _rootNode.Evaluate(_blackboard);
    }
    
    // 具体行为实现
    NodeStatus FleeAction(AIBlackboard bb) { /* 逃跑逻辑 */ return NodeStatus.Running; }
    NodeStatus CastSkill(string skillId) { /* 施放技能 */ return NodeStatus.Running; }
    NodeStatus BasicAttack(AIBlackboard bb) { /* 普通攻击 */ return NodeStatus.Running; }
    NodeStatus ChasePlayer(AIBlackboard bb) { /* 追击 */ return NodeStatus.Running; }
    NodeStatus Patrol(AIBlackboard bb) { /* 巡逻 */ return NodeStatus.Running; }
    
    float GetHPPercent() => GetComponent<Health>().CurrentHP / GetComponent<Health>().MaxHP;
    bool IsPlayerInAttackRange() => Vector3.Distance(transform.position, FindPlayer().position) < 2f;
    bool IsSkillReady(string id) => true; // 检查技能CD
    bool CanSeePlayer() => true; // 视线检测
    Transform FindPlayer() => GameObject.FindGameObjectWithTag("Player").transform;
}
```

---

## 四、NavMesh导航系统

### 4.1 NavMesh高级用法

```csharp
// NavMesh动态障碍物处理
public class DynamicObstacle : MonoBehaviour
{
    private NavMeshObstacle _obstacle;
    
    void Start()
    {
        _obstacle = GetComponent<NavMeshObstacle>();
        _obstacle.carving = true; // 开启雕刻：障碍物会在NavMesh上切出洞
        _obstacle.carvingMoveThreshold = 0.1f; // 移动超过0.1m才重新雕刻
    }
}

// 多层级NavMesh（用于跳跃/飞行单位）
public class FlyingAI : MonoBehaviour
{
    private NavMeshAgent _agent;
    
    void Start()
    {
        _agent = GetComponent<NavMeshAgent>();
        
        // 设置Agent到飞行层（需要提前烘焙飞行层NavMesh）
        int flyingAreaMask = 1 << NavMesh.GetAreaFromName("Flying");
        _agent.areaMask = flyingAreaMask;
    }
}

// 自定义寻路：分层A*（适合大地图）
public class HierarchicalPathfinder
{
    // 粗粒度寻路（Chunk级别）
    private List<Vector2Int> GetChunkPath(Vector2Int from, Vector2Int to)
    {
        // 在Chunk级别运行A*（节点少，速度快）
        return AStarOnChunks(from, to);
    }
    
    // 精细寻路（Tile级别，仅在当前Chunk内）
    private List<Vector3> GetTilePath(Vector3 from, Vector3 to)
    {
        return AStarOnTiles(from, to);
    }
    
    // 组合：先粗粒度找到大方向，再精细找具体路径
    public List<Vector3> FindPath(Vector3 start, Vector3 end)
    {
        var chunkPath = GetChunkPath(WorldToChunk(start), WorldToChunk(end));
        var result = new List<Vector3>();
        
        for (int i = 0; i < chunkPath.Count - 1; i++)
        {
            var localPath = GetTilePath(ChunkCenter(chunkPath[i]), ChunkCenter(chunkPath[i+1]));
            result.AddRange(localPath);
        }
        
        return result;
    }
    
    Vector2Int WorldToChunk(Vector3 pos) => new Vector2Int((int)(pos.x / 128), (int)(pos.z / 128));
    Vector3 ChunkCenter(Vector2Int chunk) => new Vector3(chunk.x * 128 + 64, 0, chunk.y * 128 + 64);
    List<Vector2Int> AStarOnChunks(Vector2Int a, Vector2Int b) { return new List<Vector2Int>(); }
    List<Vector3> AStarOnTiles(Vector3 a, Vector3 b) { return new List<Vector3>(); }
}
```

---

## 五、群体AI（Flocking）

### 5.1 Boids算法

```csharp
// Boids算法：模拟鸟群/鱼群/兵群的自然涌现行为
// 三条规则：分离 + 对齐 + 聚合

[BurstCompile] // 使用Burst加速大量计算
public struct BoidsUpdateJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> positions;
    [ReadOnly] public NativeArray<float3> velocities;
    [WriteOnly] public NativeArray<float3> newVelocities;
    
    public float separationRadius;   // 分离半径
    public float alignmentRadius;    // 对齐半径
    public float cohesionRadius;     // 聚合半径
    public float separationWeight;
    public float alignmentWeight;
    public float cohesionWeight;
    public float maxSpeed;
    
    public void Execute(int i)
    {
        float3 pos = positions[i];
        float3 vel = velocities[i];
        
        float3 separation = float3.zero;
        float3 alignment = float3.zero;
        float3 cohesion = float3.zero;
        int neighborCount = 0;
        
        for (int j = 0; j < positions.Length; j++)
        {
            if (i == j) continue;
            
            float3 diff = pos - positions[j];
            float dist = math.length(diff);
            
            // 分离：远离太近的邻居
            if (dist < separationRadius && dist > 0.001f)
                separation += math.normalize(diff) / dist;
            
            // 对齐：与邻居速度对齐
            if (dist < alignmentRadius)
            {
                alignment += velocities[j];
                neighborCount++;
            }
            
            // 聚合：向邻居中心移动
            if (dist < cohesionRadius)
                cohesion += positions[j];
        }
        
        float3 newVel = vel;
        newVel += separation * separationWeight;
        
        if (neighborCount > 0)
        {
            alignment /= neighborCount;
            newVel += math.normalize(alignment) * alignmentWeight;
            
            cohesion /= neighborCount;
            newVel += (cohesion - pos) * cohesionWeight;
        }
        
        // 限速
        float speed = math.length(newVel);
        if (speed > maxSpeed)
            newVel = math.normalize(newVel) * maxSpeed;
        
        newVelocities[i] = newVel;
    }
}

// 使用Boids系统
public class BoidsSystem : MonoBehaviour
{
    public int boidCount = 500;
    private NativeArray<float3> _positions;
    private NativeArray<float3> _velocities;
    private NativeArray<float3> _newVelocities;
    private GameObject[] _boidObjects;
    
    void Start()
    {
        _positions = new NativeArray<float3>(boidCount, Allocator.Persistent);
        _velocities = new NativeArray<float3>(boidCount, Allocator.Persistent);
        _newVelocities = new NativeArray<float3>(boidCount, Allocator.Persistent);
        _boidObjects = new GameObject[boidCount];
        
        // 初始化
        for (int i = 0; i < boidCount; i++)
        {
            _positions[i] = UnityEngine.Random.insideUnitSphere * 10;
            _velocities[i] = UnityEngine.Random.insideUnitSphere;
        }
    }
    
    void Update()
    {
        // 用Job并行计算所有Boid的新速度
        var job = new BoidsUpdateJob
        {
            positions = _positions,
            velocities = _velocities,
            newVelocities = _newVelocities,
            separationRadius = 1.5f,
            alignmentRadius = 3f,
            cohesionRadius = 5f,
            separationWeight = 1.5f,
            alignmentWeight = 1f,
            cohesionWeight = 0.5f,
            maxSpeed = 5f
        };
        
        var handle = job.Schedule(boidCount, 64); // 64个一组并行
        handle.Complete();
        
        // 更新位置
        for (int i = 0; i < boidCount; i++)
        {
            _velocities[i] = _newVelocities[i];
            _positions[i] += _velocities[i] * Time.deltaTime;
            
            if (_boidObjects[i] != null)
            {
                _boidObjects[i].transform.position = _positions[i];
                if (math.lengthsq(_velocities[i]) > 0.001f)
                    _boidObjects[i].transform.rotation = Quaternion.LookRotation(_velocities[i]);
            }
        }
    }
    
    void OnDestroy()
    {
        _positions.Dispose();
        _velocities.Dispose();
        _newVelocities.Dispose();
    }
}
```

---

## 六、机器学习在游戏AI中的应用

### 6.1 ML-Agents基础

```csharp
// Unity ML-Agents：用强化学习训练游戏AI

using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

// 让AI学习如何瞄准和射击目标
public class ShooterAgent : Agent
{
    private Transform _target;
    private Rigidbody _rb;
    
    // 初始化：每个Episode开始时重置
    public override void OnEpisodeBegin()
    {
        // 随机位置
        transform.position = Vector3.zero + UnityEngine.Random.insideUnitSphere * 5f;
        _target.position = Vector3.zero + UnityEngine.Random.insideUnitSphere * 8f;
        _rb.velocity = Vector3.zero;
    }
    
    // 观察：AI看到什么（输入）
    public override void CollectObservations(VectorSensor sensor)
    {
        // 自身位置（3）
        sensor.AddObservation(transform.position);
        // 目标相对位置（3）
        sensor.AddObservation(_target.position - transform.position);
        // 自身速度（3）
        sensor.AddObservation(_rb.velocity);
        // 朝向（3）
        sensor.AddObservation(transform.forward);
        // 总共12个观察值
    }
    
    // 动作：AI能做什么（输出）
    public override void OnActionReceived(ActionBuffers actions)
    {
        // 连续动作：旋转和移动
        float rotateY = actions.ContinuousActions[0]; // [-1, 1]
        float moveForward = actions.ContinuousActions[1]; // [-1, 1]
        
        transform.Rotate(0, rotateY * 90f * Time.deltaTime, 0);
        _rb.AddForce(transform.forward * moveForward * 5f);
        
        // 离散动作：是否射击
        if (actions.DiscreteActions[0] == 1)
        {
            if (IsAimingAtTarget())
            {
                Shoot();
                // 击中目标：正奖励
                AddReward(1.0f);
                EndEpisode();
            }
            else
            {
                // 射击但没打中：小负奖励
                AddReward(-0.1f);
            }
        }
        
        // 时间惩罚：鼓励AI快速完成任务
        AddReward(-0.001f);
        
        // 越界惩罚
        if (transform.position.magnitude > 20f)
        {
            AddReward(-1.0f);
            EndEpisode();
        }
    }
    
    // 人类控制（调试用）
    public override void Heuristic(in ActionBuffers actionsOut)
    {
        var continuousActions = actionsOut.ContinuousActions;
        continuousActions[0] = Input.GetAxis("Horizontal");
        continuousActions[1] = Input.GetAxis("Vertical");
        
        var discreteActions = actionsOut.DiscreteActions;
        discreteActions[0] = Input.GetKeyDown(KeyCode.Space) ? 1 : 0;
    }
    
    bool IsAimingAtTarget() => Vector3.Angle(transform.forward, _target.position - transform.position) < 10f;
    void Shoot() { /* 发射子弹 */ }
}
```

---

## 总结：游戏AI技术选型

```
简单AI（FSM）：
适合：小游戏、原型、简单NPC
优点：直观、易调试、性能好
缺点：状态多时维护困难

中等复杂AI（行为树）：
适合：大多数商业游戏（MOBA、RPG、FPS的敌人）
优点：模块化、可视化调试（使用编辑器工具）
缺点：行为树大时性能开销明显

复杂AI（GOAP + 行为树）：
适合：需要智能规划的复杂NPC
优点：AI行为更自然、能处理复杂目标
缺点：调试困难、计算开销大

学习型AI（ML-Agents）：
适合：需要超人类表现的AI（棋类、竞技游戏）
优点：能发现人类设计师想不到的策略
缺点：训练时间长、不可预测、调试困难

技术负责人建议：
→ 90%的游戏用行为树就够了
→ 投资在AI编辑器工具上（让策划能调AI，而不是改代码）
→ 把ML-Agents作为辅助手段，不要作为主要AI框架
```
