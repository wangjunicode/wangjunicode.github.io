---
title: 行为树与 AI 系统设计：从 FSM 到复杂 NPC 行为
published: 2026-03-21
description: "深入讲解游戏 AI 系统的实现方案，从简单有限状态机（FSM）到行为树（Behavior Tree），再到实用工具节点的设计，帮助你为商业项目构建灵活可扩展的 AI 框架。"
tags: [游戏AI, 行为树, 状态机, Unity, 架构设计]
category: 架构设计
draft: false
encryptedKey:henhaoji123
---

## AI 系统的本质需求

游戏 AI 需要解决的核心问题：

```
1. 在当前状态下，AI 应该做什么？（决策）
2. 如何在不同行为之间切换？（状态管理）
3. 如何让 AI 看起来"智能"但开销可控？（性能）
4. 如何让策划方便地配置 AI 行为？（可调性）
```

---

## 一、有限状态机（FSM）

### 1.1 FSM 的适用场景

```
适合 FSM 的场景：
  ✅ 状态数量少（< 10个）
  ✅ 状态转换关系简单
  ✅ 快速实现、容易理解

不适合 FSM 的场景：
  ❌ 状态数量多（增加一个状态需要修改很多转换逻辑）
  ❌ 行为需要频繁复用（每个状态机要重新实现相同行为）
  ❌ 策划需要频繁调整（代码和数据耦合）
```

### 1.2 通用 FSM 实现

```csharp
// 定义在前面的战斗系统章节已经实现了状态机基础
// 这里补充一个更完整的 AI 状态机

public enum AIState
{
    Idle,
    Patrol,
    Alert,       // 听到声音，进入警觉
    Chase,       // 发现目标，追击
    Attack,      // 在攻击范围内，攻击
    Flee,        // 血量低，逃跑
    Dead
}

public class EnemyAI : MonoBehaviour
{
    [Header("AI参数")]
    [SerializeField] private float _detectRange = 15f;    // 探测范围
    [SerializeField] private float _attackRange = 2f;     // 攻击范围
    [SerializeField] private float _fleeHPThreshold = 0.2f; // 逃跑血量阈值
    
    private AIState _currentState = AIState.Idle;
    private Transform _target;
    private float _stateTimer;
    
    void Update()
    {
        _stateTimer += Time.deltaTime;
        
        switch (_currentState)
        {
            case AIState.Idle:
                UpdateIdle();
                break;
            case AIState.Patrol:
                UpdatePatrol();
                break;
            case AIState.Chase:
                UpdateChase();
                break;
            case AIState.Attack:
                UpdateAttack();
                break;
            case AIState.Flee:
                UpdateFlee();
                break;
        }
    }
    
    void UpdateIdle()
    {
        // 检测玩家
        _target = FindPlayerInRange(_detectRange);
        if (_target != null)
        {
            TransitionTo(AIState.Chase);
            return;
        }
        
        // 一段时间后开始巡逻
        if (_stateTimer > 3f)
            TransitionTo(AIState.Patrol);
    }
    
    void UpdateChase()
    {
        if (_target == null || !_target.gameObject.activeInHierarchy)
        {
            TransitionTo(AIState.Idle);
            return;
        }
        
        float distance = Vector3.Distance(transform.position, _target.position);
        
        // 进入攻击范围
        if (distance <= _attackRange)
        {
            TransitionTo(AIState.Attack);
            return;
        }
        
        // 血量低，逃跑
        if (GetHPPercent() < _fleeHPThreshold)
        {
            TransitionTo(AIState.Flee);
            return;
        }
        
        // 移向目标
        MoveTowards(_target.position);
    }
    
    void UpdateAttack()
    {
        if (_target == null) { TransitionTo(AIState.Idle); return; }
        
        float distance = Vector3.Distance(transform.position, _target.position);
        
        // 目标跑远了，重新追击
        if (distance > _attackRange * 1.5f)
        {
            TransitionTo(AIState.Chase);
            return;
        }
        
        // 执行攻击（使用计时器控制攻击频率）
        if (_stateTimer >= _attackCooldown)
        {
            PerformAttack();
            _stateTimer = 0;
        }
    }
    
    void TransitionTo(AIState newState)
    {
        OnStateExit(_currentState);
        _currentState = newState;
        _stateTimer = 0;
        OnStateEnter(newState);
    }
    
    private float _attackCooldown = 1.5f;
    void OnStateEnter(AIState state) { /* 进入状态时的初始化 */ }
    void OnStateExit(AIState state) { /* 退出状态时的清理 */ }
    void MoveTowards(Vector3 pos) { /* 移动逻辑 */ }
    void PerformAttack() { /* 攻击逻辑 */ }
    Transform FindPlayerInRange(float range) => null; // 查找范围内的玩家
    float GetHPPercent() => 1f;
}
```

---

## 二、行为树（Behavior Tree）

### 2.1 行为树的基本节点类型

```
行为树的节点分类：

叶节点（Leaf）：实际执行的行为
  - Action（行为）：执行某个操作，返回 Success/Failure/Running
  - Condition（条件）：检查条件是否满足

组合节点（Composite）：控制子节点的执行顺序和逻辑
  - Sequence（序列）：依次执行子节点，全部成功才成功（AND 逻辑）
  - Selector（选择）：依次尝试子节点，找到第一个成功就返回（OR 逻辑）
  - Parallel（并行）：同时执行所有子节点

装饰节点（Decorator）：包装一个子节点，修改其行为
  - Inverter（反转）：将结果取反
  - Repeater（重复）：重复执行子节点 N 次
  - Timeout（超时）：超时后强制返回 Failure
  - Cooldown（冷却）：冷却时间内跳过执行

节点返回值：
  Success（成功）：任务完成
  Failure（失败）：任务失败
  Running（运行中）：任务还在执行（需要下帧继续）
```

### 2.2 行为树核心实现

```csharp
/// <summary>
/// 行为树节点基类
/// </summary>
public abstract class BTNode
{
    public enum Status { Success, Failure, Running }
    
    protected BTAgent Agent;
    private Status _lastStatus = Status.Failure;
    
    public void SetAgent(BTAgent agent) => Agent = agent;
    
    // 节点开始执行
    protected virtual void OnStart() { }
    
    // 节点执行逻辑（每帧调用，直到返回 Success 或 Failure）
    protected abstract Status OnUpdate();
    
    // 节点结束（无论成功失败）
    protected virtual void OnStop() { }
    
    public Status Update()
    {
        if (_lastStatus != Status.Running)
            OnStart();
        
        _lastStatus = OnUpdate();
        
        if (_lastStatus != Status.Running)
            OnStop();
        
        return _lastStatus;
    }
    
    public void Reset() => _lastStatus = Status.Failure;
}

/// <summary>
/// 序列节点（Sequence）：所有子节点都成功才成功
/// </summary>
public class SequenceNode : BTNode
{
    private readonly List<BTNode> _children;
    private int _currentIndex;
    
    public SequenceNode(params BTNode[] children)
    {
        _children = new List<BTNode>(children);
    }
    
    protected override void OnStart() => _currentIndex = 0;
    
    protected override Status OnUpdate()
    {
        while (_currentIndex < _children.Count)
        {
            var child = _children[_currentIndex];
            var status = child.Update();
            
            switch (status)
            {
                case Status.Running:
                    return Status.Running; // 等待子节点完成
                case Status.Failure:
                    return Status.Failure; // 任意子节点失败 → 整体失败
                case Status.Success:
                    _currentIndex++;       // 成功 → 执行下一个
                    break;
            }
        }
        return Status.Success; // 所有子节点成功
    }
}

/// <summary>
/// 选择节点（Selector）：找到第一个成功的子节点就返回
/// </summary>
public class SelectorNode : BTNode
{
    private readonly List<BTNode> _children;
    private int _currentIndex;
    
    public SelectorNode(params BTNode[] children)
    {
        _children = new List<BTNode>(children);
    }
    
    protected override void OnStart() => _currentIndex = 0;
    
    protected override Status OnUpdate()
    {
        while (_currentIndex < _children.Count)
        {
            var child = _children[_currentIndex];
            var status = child.Update();
            
            switch (status)
            {
                case Status.Running:
                    return Status.Running;
                case Status.Success:
                    return Status.Success; // 找到成功的 → 返回
                case Status.Failure:
                    _currentIndex++;       // 这个失败 → 尝试下一个
                    break;
            }
        }
        return Status.Failure; // 所有子节点都失败
    }
}

/// <summary>
/// 反转装饰节点
/// </summary>
public class InverterNode : BTNode
{
    private readonly BTNode _child;
    
    public InverterNode(BTNode child) => _child = child;
    
    protected override Status OnUpdate()
    {
        var status = _child.Update();
        return status switch
        {
            Status.Success => Status.Failure,
            Status.Failure => Status.Success,
            _ => Status.Running
        };
    }
}

/// <summary>
/// 冷却装饰节点
/// </summary>
public class CooldownNode : BTNode
{
    private readonly BTNode _child;
    private readonly float _cooldownTime;
    private float _lastExecuteTime = float.MinValue;
    
    public CooldownNode(BTNode child, float cooldownTime)
    {
        _child = child;
        _cooldownTime = cooldownTime;
    }
    
    protected override Status OnUpdate()
    {
        if (Time.time - _lastExecuteTime < _cooldownTime)
            return Status.Failure; // 还在冷却中
        
        var status = _child.Update();
        if (status == Status.Success)
            _lastExecuteTime = Time.time;
        return status;
    }
}
```

### 2.3 行为节点实现

```csharp
/// <summary>
/// 条件：目标在范围内
/// </summary>
public class IsTargetInRange : BTNode
{
    private readonly float _range;
    private readonly string _targetKey;
    
    public IsTargetInRange(float range, string targetKey = "Target")
    {
        _range = range;
        _targetKey = targetKey;
    }
    
    protected override Status OnUpdate()
    {
        var target = Agent.Blackboard.Get<Transform>(_targetKey);
        if (target == null) return Status.Failure;
        
        float distance = Vector3.Distance(Agent.transform.position, target.position);
        return distance <= _range ? Status.Success : Status.Failure;
    }
}

/// <summary>
/// 行为：移动到目标
/// </summary>
public class MoveToTarget : BTNode
{
    private readonly float _stoppingDistance;
    private readonly string _targetKey;
    
    public MoveToTarget(float stoppingDistance = 0.5f, string targetKey = "Target")
    {
        _stoppingDistance = stoppingDistance;
        _targetKey = targetKey;
    }
    
    protected override Status OnUpdate()
    {
        var target = Agent.Blackboard.Get<Transform>(_targetKey);
        if (target == null) return Status.Failure;
        
        float distance = Vector3.Distance(Agent.transform.position, target.position);
        
        if (distance <= _stoppingDistance)
            return Status.Success; // 已到达
        
        // 朝目标移动
        Vector3 direction = (target.position - Agent.transform.position).normalized;
        Agent.NavAgent.SetDestination(target.position);
        
        return Status.Running; // 还在路上
    }
    
    protected override void OnStop()
    {
        Agent.NavAgent.ResetPath();
    }
}

/// <summary>
/// 行为：攻击目标
/// </summary>
public class AttackTarget : BTNode
{
    private readonly float _attackInterval;
    private float _nextAttackTime;
    
    public AttackTarget(float attackInterval = 1f) => _attackInterval = attackInterval;
    
    protected override void OnStart() => _nextAttackTime = Time.time;
    
    protected override Status OnUpdate()
    {
        var target = Agent.Blackboard.Get<Transform>("Target");
        if (target == null) return Status.Failure;
        
        if (Time.time >= _nextAttackTime)
        {
            Agent.PerformAttack(target);
            _nextAttackTime = Time.time + _attackInterval;
        }
        
        return Status.Running; // 持续攻击，直到外部条件变化
    }
}
```

### 2.4 黑板（Blackboard）：AI 的共享数据

```csharp
/// <summary>
/// 黑板：行为树各节点共享的数据容器
/// </summary>
public class Blackboard
{
    private readonly Dictionary<string, object> _data = new();
    
    public void Set<T>(string key, T value) => _data[key] = value;
    
    public T Get<T>(string key)
    {
        if (_data.TryGetValue(key, out var value) && value is T result)
            return result;
        return default;
    }
    
    public bool Has(string key) => _data.ContainsKey(key);
    
    public void Remove(string key) => _data.Remove(key);
}

/// <summary>
/// 行为树 Agent：行为树的执行者
/// </summary>
public class BTAgent : MonoBehaviour
{
    public Blackboard Blackboard { get; private set; } = new();
    public UnityEngine.AI.NavMeshAgent NavAgent { get; private set; }
    
    private BTNode _rootNode;
    
    void Awake()
    {
        NavAgent = GetComponent<UnityEngine.AI.NavMeshAgent>();
        _rootNode = BuildBehaviorTree();
        
        // 递归设置 Agent 引用
        SetAgentRecursive(_rootNode);
    }
    
    void Update()
    {
        _rootNode.Update();
    }
    
    private BTNode BuildBehaviorTree()
    {
        // 构建行为树：可以在代码中构建，也可以从 JSON/ScriptableObject 反序列化
        return new SelectorNode(
            // 优先级1：如果血量低，逃跑
            new SequenceNode(
                new IsLowHP(0.2f),
                new FleeFromTarget()
            ),
            // 优先级2：如果看到目标，追击并攻击
            new SequenceNode(
                new FindTarget(_detectRange: 15f),
                new SelectorNode(
                    // 在攻击范围内：攻击
                    new SequenceNode(
                        new IsTargetInRange(2f),
                        new CooldownNode(new AttackTarget(), 1.5f)
                    ),
                    // 不在攻击范围：追击
                    new MoveToTarget(stoppingDistance: 1.5f)
                )
            ),
            // 优先级3：巡逻
            new PatrolAction()
        );
    }
    
    private void SetAgentRecursive(BTNode node)
    {
        node.SetAgent(this);
        // 递归设置子节点（需要访问子节点列表，这里简化处理）
    }
    
    public void PerformAttack(Transform target)
    {
        Debug.Log($"{name} 攻击了 {target.name}");
        // 实际攻击逻辑
    }
}
```

---

## 三、行为树 vs 状态机 vs 决策树

### 3.1 对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| **FSM** | 简单直观，容易调试 | 状态多时维护困难 | 简单 NPC，状态 < 10 |
| **行为树** | 可视化，易于复用，策划友好 | 实现复杂，调试需工具 | 复杂 NPC，需要策划配置 |
| **决策树** | 适合基于数据的决策 | 不适合描述序列行为 | 技能选择，策略决策 |
| **GOAP** | 目标导向，最灵活 | 计算开销大，调试困难 | 高端 AI，如 F.E.A.R. |
| **效用 AI** | 自然的行为优先级 | 需要大量调参 | 模拟类游戏 |

### 3.2 实际选型建议

```
刚毕业 / 小项目：
  → FSM（够用，容易上手）

中型项目 / 有策划需求：
  → 行为树（可视化编辑器，Unity 有 BehaviorDesigner 插件）
  → 推荐使用 Behavior Designer 或自研简单行为树

大型 MMORPG：
  → 分层 AI（大范围决策用行为树，细节行为用 FSM）
  → 服务器跑大 AI，客户端只做表现

MOBA/RTS 的 AI：
  → 专门的 AI 策略系统（往往是高度定制化的）
```

---

## 四、AI 性能优化

### 4.1 分帧更新 AI

```csharp
/// <summary>
/// AI 管理器：分帧更新，避免所有 AI 同帧计算
/// </summary>
public class AIManager : MonoBehaviour
{
    private static readonly List<BTAgent> _agents = new(256);
    private int _updateIndex;
    
    // 每帧最多更新的 AI 数量
    [SerializeField] private int _maxUpdatePerFrame = 20;
    
    public static void Register(BTAgent agent) => _agents.Add(agent);
    public static void Unregister(BTAgent agent) => _agents.Remove(agent);
    
    void Update()
    {
        // 分帧更新（时间分片）
        int count = Mathf.Min(_maxUpdatePerFrame, _agents.Count);
        
        for (int i = 0; i < count; i++)
        {
            int index = (_updateIndex + i) % _agents.Count;
            if (_agents[index] != null && _agents[index].isActiveAndEnabled)
                _agents[index].ManualUpdate();
        }
        
        _updateIndex = (_updateIndex + count) % Mathf.Max(1, _agents.Count);
    }
}
```

### 4.2 LOD AI（根据距离降低更新频率）

```csharp
public class LODAIAgent : MonoBehaviour
{
    private float _updateInterval;
    private float _nextUpdateTime;
    
    void Update()
    {
        // 根据与玩家的距离决定 AI 更新频率
        float distance = Vector3.Distance(transform.position, PlayerPosition);
        
        _updateInterval = distance switch
        {
            < 10f => 0.1f,   // 近距离：每 0.1 秒更新（10fps AI）
            < 30f => 0.3f,   // 中距离：每 0.3 秒更新
            < 60f => 1f,     // 远距离：每 1 秒更新
            _ => 3f          // 很远：每 3 秒更新（几乎不动）
        };
        
        if (Time.time >= _nextUpdateTime)
        {
            _nextUpdateTime = Time.time + _updateInterval;
            RunAIUpdate();
        }
    }
    
    static Vector3 PlayerPosition => Player.Instance?.transform.position ?? Vector3.zero;
    void RunAIUpdate() { /* 实际 AI 逻辑 */ }
}
```

---

## 总结

游戏 AI 系统的选型建议：

1. **简单就是美**：能用 FSM 解决的，不要过度设计行为树
2. **策划友好优先**：AI 的最大价值在于可配置，而非技术复杂度
3. **性能意识**：用分帧更新和 LOD AI 控制性能开销
4. **调试工具**：好的 AI 必须有好的可视化调试工具

> **下一篇**：[代码质量工程：静态分析、单元测试与代码审查体系]
