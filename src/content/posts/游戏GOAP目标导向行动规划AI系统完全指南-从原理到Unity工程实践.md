---
title: 游戏GOAP目标导向行动规划AI系统完全指南：从原理到Unity工程实践
published: 2026-05-02
description: 深度解析GOAP（Goal-Oriented Action Planning）目标导向行动规划算法原理，涵盖世界状态建模、动作前提/效果定义、A*规划器实现、NPC行为智能化，以及与行为树、有限状态机的融合架构，附完整Unity C#代码实现。
tags: [AI, GOAP, 游戏AI, 行为规划, NPC, 寻路算法, A星, Unity]
category: 游戏AI
draft: false
---

# 游戏GOAP目标导向行动规划AI系统完全指南：从原理到Unity工程实践

## 概述

GOAP（Goal-Oriented Action Planning，目标导向行动规划）是由Jeff Orkin在《F.E.A.R.》中首次应用的AI技术，被誉为游戏AI领域的里程碑。相比行为树和有限状态机，GOAP的最大优势是**动作解耦、智能组合**——AI能根据当前世界状态和目标，自主规划出最优行动序列，而无需手动编写每种情况的逻辑。

本文将深度解析GOAP的工作原理，并给出完整的Unity C#工程实现。

## 一、GOAP核心概念

### 1.1 三大要素

```
世界状态（World State）
    ↓ 输入
目标（Goal）：期望达到的世界状态
    ↓ 驱动
行动（Action）：改变世界状态的操作，有前提条件（Preconditions）和效果（Effects）
    ↓ 组合
规划（Plan）：一系列Action的有序序列，使世界状态从当前变为目标状态
```

### 1.2 与其他AI技术对比

| 特性 | FSM有限状态机 | 行为树BT | GOAP |
|------|------------|---------|------|
| 扩展性 | 差（状态爆炸） | 中（需手写逻辑） | 好（动作自由组合） |
| 智能程度 | 低（固定转换） | 中（优先级选择） | 高（自主规划） |
| 调试难度 | 易 | 中 | 难（规划过程抽象） |
| 性能开销 | 低 | 低-中 | 中-高（规划计算） |
| 适用场景 | 简单NPC | 复杂行为树 | 战术AI、士兵AI |

## 二、世界状态与行动建模

### 2.1 世界状态表示

```csharp
using System;
using System.Collections.Generic;
using System.Text;

/// <summary>
/// 世界状态：键值对集合，表示AI所感知的世界快照
/// 值类型为object，支持bool、int、float、string、Enum等
/// </summary>
[Serializable]
public class WorldState
{
    private Dictionary<string, object> _states = new Dictionary<string, object>();

    public WorldState() { }

    /// <summary>
    /// 从已有状态拷贝构造
    /// </summary>
    public WorldState(WorldState other)
    {
        _states = new Dictionary<string, object>(other._states);
    }

    /// <summary>
    /// 设置状态值
    /// </summary>
    public void Set(string key, object value)
    {
        _states[key] = value;
    }

    /// <summary>
    /// 获取状态值
    /// </summary>
    public T Get<T>(string key, T defaultValue = default)
    {
        if (_states.TryGetValue(key, out object val) && val is T typedVal)
            return typedVal;
        return defaultValue;
    }

    /// <summary>
    /// 是否包含指定键
    /// </summary>
    public bool Has(string key) => _states.ContainsKey(key);

    /// <summary>
    /// 检查此状态是否满足目标状态的所有条件
    /// </summary>
    public bool Satisfies(WorldState goal)
    {
        foreach (var kvp in goal._states)
        {
            if (!_states.TryGetValue(kvp.Key, out object val))
                return false;
            if (!Equals(val, kvp.Value))
                return false;
        }
        return true;
    }

    /// <summary>
    /// 应用效果（返回新状态，不修改原状态）
    /// </summary>
    public WorldState ApplyEffects(WorldState effects)
    {
        WorldState newState = new WorldState(this);
        foreach (var kvp in effects._states)
        {
            newState._states[kvp.Key] = kvp.Value;
        }
        return newState;
    }

    /// <summary>
    /// 计算与目标状态的差异数量（用于启发式函数）
    /// </summary>
    public int GetUnsatisfiedCount(WorldState goal)
    {
        int count = 0;
        foreach (var kvp in goal._states)
        {
            if (!_states.TryGetValue(kvp.Key, out object val) || !Equals(val, kvp.Value))
                count++;
        }
        return count;
    }

    public Dictionary<string, object>.Enumerator GetEnumerator() => _states.GetEnumerator();

    public override string ToString()
    {
        var sb = new StringBuilder("{");
        foreach (var kvp in _states)
            sb.Append($" {kvp.Key}={kvp.Value},");
        sb.Append(" }");
        return sb.ToString();
    }

    public override bool Equals(object obj)
    {
        if (obj is WorldState other)
        {
            if (_states.Count != other._states.Count) return false;
            foreach (var kvp in _states)
            {
                if (!other._states.TryGetValue(kvp.Key, out object val) || !Equals(kvp.Value, val))
                    return false;
            }
            return true;
        }
        return false;
    }

    public override int GetHashCode()
    {
        int hash = 0;
        foreach (var kvp in _states)
            hash ^= kvp.Key.GetHashCode() ^ (kvp.Value?.GetHashCode() ?? 0);
        return hash;
    }
}
```

### 2.2 行动基类设计

```csharp
using UnityEngine;
using System.Collections;

/// <summary>
/// GOAP行动基类
/// 每个具体行动继承此类，定义前提条件、效果和执行逻辑
/// </summary>
public abstract class GOAPAction : MonoBehaviour
{
    [Header("行动基础配置")]
    [SerializeField] protected string _actionName = "UnnamedAction";
    [SerializeField] protected float _cost = 1f; // 行动代价（规划时选择最优路径）

    // 前提条件：执行此行动所需的世界状态
    protected WorldState _preconditions = new WorldState();

    // 效果：执行完此行动后世界状态的变化
    protected WorldState _effects = new WorldState();

    // 行动是否正在执行
    public bool IsRunning { get; protected set; }

    // 行动执行目标（运行时赋值）
    public GameObject Target { get; set; }

    public string ActionName => _actionName;
    public float Cost => _cost;
    public WorldState Preconditions => _preconditions;
    public WorldState Effects => _effects;

    protected virtual void Awake()
    {
        SetupConditions();
    }

    /// <summary>
    /// 子类重写此方法，初始化前提条件和效果
    /// </summary>
    protected abstract void SetupConditions();

    /// <summary>
    /// 检查行动是否可在当前上下文中执行（运行时动态检查，比静态前提条件更细粒度）
    /// 默认实现：检查Target是否存在（如果需要目标）
    /// </summary>
    public virtual bool CheckProceduralPrecondition(GameObject agent)
    {
        return true;
    }

    /// <summary>
    /// 执行行动（协程）
    /// </summary>
    public abstract IEnumerator Perform(GameObject agent);

    /// <summary>
    /// 重置行动状态（复用时调用）
    /// </summary>
    public virtual void Reset()
    {
        IsRunning = false;
        Target = null;
    }

    /// <summary>
    /// 行动是否需要移动到目标位置
    /// </summary>
    public virtual bool RequiresInRange() => Target != null;

    /// <summary>
    /// 判断agent是否在行动所需的范围内
    /// </summary>
    public virtual bool IsInRange(GameObject agent)
    {
        if (Target == null) return true;
        return Vector3.Distance(agent.transform.position, Target.transform.position) <= GetActionRange();
    }

    /// <summary>
    /// 行动执行所需的范围（米）
    /// </summary>
    protected virtual float GetActionRange() => 2.0f;

    public override string ToString() => _actionName;
}
```

## 三、A*规划器实现

### 3.1 规划节点

```csharp
using System.Collections.Generic;

/// <summary>
/// A*规划算法的搜索节点
/// </summary>
public class PlanNode
{
    public PlanNode Parent;
    public float Cost;          // 从起点到此节点的实际代价 g(n)
    public float Heuristic;     // 到目标的启发式估计代价 h(n)
    public float F => Cost + Heuristic; // f(n) = g(n) + h(n)
    public WorldState State;    // 此节点对应的世界状态
    public GOAPAction Action;   // 到达此节点所执行的行动（null表示起始节点）

    public PlanNode(PlanNode parent, float cost, WorldState state, GOAPAction action)
    {
        Parent = parent;
        Cost = cost;
        State = state;
        Action = action;
        Heuristic = 0;
    }
}
```

### 3.2 GOAP规划器核心

```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

/// <summary>
/// GOAP规划器：使用A*算法从当前状态规划到目标状态的行动序列
/// </summary>
public static class GOAPPlanner
{
    /// <summary>
    /// 规划行动序列
    /// </summary>
    /// <param name="agent">执行AI的游戏对象</param>
    /// <param name="availableActions">可用的行动列表</param>
    /// <param name="currentState">当前世界状态</param>
    /// <param name="goal">目标世界状态</param>
    /// <returns>行动序列（按执行顺序），规划失败返回null</returns>
    public static Queue<GOAPAction> Plan(
        GameObject agent,
        List<GOAPAction> availableActions,
        WorldState currentState,
        WorldState goal)
    {
        // 重置所有行动状态
        foreach (var action in availableActions)
            action.Reset();

        // 过滤：只保留满足程序性前提条件的行动
        var usableActions = availableActions
            .Where(a => a.CheckProceduralPrecondition(agent))
            .ToList();

        // A*搜索
        var openList = new List<PlanNode>();
        var closedList = new List<PlanNode>();

        // 起始节点（注意GOAP是反向规划：从目标往回推）
        // 也可以正向规划，这里用正向（更直观）
        PlanNode startNode = new PlanNode(null, 0, currentState, null);
        startNode.Heuristic = currentState.GetUnsatisfiedCount(goal);
        openList.Add(startNode);

        int maxIterations = 1000; // 防止无限循环
        int iterations = 0;

        while (openList.Count > 0 && iterations < maxIterations)
        {
            iterations++;

            // 取f值最小的节点
            PlanNode current = openList.OrderBy(n => n.F).First();
            openList.Remove(current);

            // 检查是否到达目标
            if (current.State.Satisfies(goal))
            {
                Debug.Log($"[GOAP] 规划成功！迭代次数：{iterations}");
                return ExtractPlan(current);
            }

            closedList.Add(current);

            // 扩展邻居节点
            foreach (var action in usableActions)
            {
                // 检查当前状态是否满足行动的前提条件
                if (!current.State.Satisfies(action.Preconditions))
                    continue;

                // 应用行动效果，得到新状态
                WorldState newState = current.State.ApplyEffects(action.Effects);
                float newCost = current.Cost + action.Cost;

                // 检查是否已在closed列表中
                bool inClosed = closedList.Any(n => n.State.Equals(newState));
                if (inClosed) continue;

                // 检查open列表中是否已有更优路径
                PlanNode existing = openList.FirstOrDefault(n => n.State.Equals(newState));
                if (existing != null)
                {
                    if (newCost < existing.Cost)
                    {
                        // 更新更优路径
                        existing.Cost = newCost;
                        existing.Parent = current;
                        existing.Action = action;
                    }
                }
                else
                {
                    // 添加新节点
                    PlanNode newNode = new PlanNode(current, newCost, newState, action);
                    newNode.Heuristic = newState.GetUnsatisfiedCount(goal);
                    openList.Add(newNode);
                }
            }
        }

        Debug.LogWarning($"[GOAP] 规划失败！无法找到从当前状态到目标状态的行动序列。迭代次数：{iterations}");
        return null;
    }

    /// <summary>
    /// 从目标节点反向提取行动序列
    /// </summary>
    private static Queue<GOAPAction> ExtractPlan(PlanNode goalNode)
    {
        var actionList = new List<GOAPAction>();
        PlanNode current = goalNode;

        while (current.Parent != null)
        {
            actionList.Add(current.Action);
            current = current.Parent;
        }

        actionList.Reverse();
        var plan = new Queue<GOAPAction>(actionList);

        // 打印规划结果
        var planNames = string.Join(" -> ", actionList.Select(a => a.ActionName));
        Debug.Log($"[GOAP] 规划结果：{planNames}");

        return plan;
    }
}
```

## 四、GOAP Agent执行器

### 4.1 Agent主控制器

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// GOAP Agent主控制器
/// 负责感知世界状态、选择目标、调用规划器、执行行动序列
/// </summary>
[RequireComponent(typeof(NavMeshAgent))]
public class GOAPAgent : MonoBehaviour
{
    [Header("感知配置")]
    [SerializeField] private float _perceptionRadius = 15f;
    [SerializeField] private LayerMask _perceptionLayers;

    private NavMeshAgent _navAgent;
    private List<GOAPAction> _availableActions;
    private Queue<GOAPAction> _currentPlan;
    private GOAPAction _currentAction;

    // 当前世界状态（由感知系统维护）
    private WorldState _worldState = new WorldState();

    // 当前目标（由决策系统选择）
    private WorldState _currentGoal;

    // 状态机
    private enum AgentState { Idle, Planning, Moving, Performing }
    private AgentState _state = AgentState.Idle;

    // 重规划计时器
    private float _replanTimer = 0;
    private const float REPLAN_INTERVAL = 0.5f; // 每0.5秒尝试重规划

    private void Awake()
    {
        _navAgent = GetComponent<NavMeshAgent>();
        _availableActions = new List<GOAPAction>(GetComponents<GOAPAction>());
        Debug.Log($"[GOAP Agent] {gameObject.name} 初始化，共{_availableActions.Count}个可用行动");
    }

    private void Start()
    {
        // 初始化世界状态
        InitWorldState();

        // 选择初始目标
        _currentGoal = SelectGoal();

        // 开始规划循环
        StartCoroutine(PlanningLoop());
    }

    private void Update()
    {
        UpdateWorldState();

        _replanTimer += Time.deltaTime;
        if (_replanTimer >= REPLAN_INTERVAL)
        {
            _replanTimer = 0;
            // 如果世界状态发生了关键变化，触发重规划
            if (ShouldReplan())
            {
                StopAllCoroutines();
                _state = AgentState.Idle;
                _currentPlan = null;
                _currentAction = null;
                StartCoroutine(PlanningLoop());
            }
        }
    }

    /// <summary>
    /// 规划执行主循环
    /// </summary>
    private IEnumerator PlanningLoop()
    {
        while (true)
        {
            // 重新选择目标
            _currentGoal = SelectGoal();

            // 检查目标是否已满足
            if (_worldState.Satisfies(_currentGoal))
            {
                _state = AgentState.Idle;
                yield return new WaitForSeconds(0.1f);
                continue;
            }

            // 执行规划
            _state = AgentState.Planning;
            _currentPlan = GOAPPlanner.Plan(gameObject, _availableActions, _worldState, _currentGoal);

            if (_currentPlan == null || _currentPlan.Count == 0)
            {
                Debug.LogWarning($"[GOAP Agent] {gameObject.name} 规划失败，等待重试");
                _state = AgentState.Idle;
                yield return new WaitForSeconds(1f);
                continue;
            }

            // 执行行动序列
            while (_currentPlan.Count > 0)
            {
                _currentAction = _currentPlan.Dequeue();

                // 如果行动需要移动到目标
                if (_currentAction.RequiresInRange())
                {
                    _state = AgentState.Moving;
                    while (!_currentAction.IsInRange(gameObject))
                    {
                        MoveToTarget(_currentAction.Target);
                        yield return null;

                        // 检查目标是否消失
                        if (_currentAction.Target == null)
                        {
                            Debug.LogWarning("[GOAP Agent] 行动目标消失，触发重规划");
                            goto BreakPlan;
                        }
                    }
                    _navAgent.isStopped = true;
                }

                // 执行行动
                _state = AgentState.Performing;
                bool actionSucceeded = false;

                yield return StartCoroutine(ExecuteActionWithResult(_currentAction, (result) =>
                {
                    actionSucceeded = result;
                }));

                if (!actionSucceeded)
                {
                    Debug.LogWarning($"[GOAP Agent] 行动失败：{_currentAction.ActionName}，触发重规划");
                    goto BreakPlan;
                }

                // 应用行动效果到世界状态
                _worldState = _worldState.ApplyEffects(_currentAction.Effects);
                Debug.Log($"[GOAP Agent] 行动完成：{_currentAction.ActionName}");
            }

            BreakPlan:
            _currentAction = null;
            yield return null;
        }
    }

    private IEnumerator ExecuteActionWithResult(GOAPAction action, System.Action<bool> callback)
    {
        bool succeeded = true;

        // 添加超时保护
        float timeout = 10f;
        float elapsed = 0f;

        IEnumerator routine = action.Perform(gameObject);
        while (true)
        {
            bool hasNext;
            try
            {
                hasNext = routine.MoveNext();
            }
            catch (Exception e)
            {
                Debug.LogError($"[GOAP Agent] 行动执行异常：{action.ActionName} - {e.Message}");
                succeeded = false;
                break;
            }

            if (!hasNext) break;

            elapsed += Time.deltaTime;
            if (elapsed > timeout)
            {
                Debug.LogWarning($"[GOAP Agent] 行动超时：{action.ActionName}");
                succeeded = false;
                break;
            }

            yield return routine.Current;
        }

        callback(succeeded);
    }

    private void MoveToTarget(GameObject target)
    {
        if (target == null) return;
        _navAgent.isStopped = false;
        _navAgent.SetDestination(target.transform.position);
    }

    /// <summary>
    /// 初始化世界状态（子类重写）
    /// </summary>
    protected virtual void InitWorldState()
    {
        _worldState.Set("isAlive", true);
        _worldState.Set("hasWeapon", false);
        _worldState.Set("weaponLoaded", false);
        _worldState.Set("enemyVisible", false);
        _worldState.Set("enemyDead", false);
        _worldState.Set("atCover", false);
        _worldState.Set("health", 100);
    }

    /// <summary>
    /// 每帧更新世界状态（子类重写）
    /// </summary>
    protected virtual void UpdateWorldState()
    {
        // 更新感知到的世界状态，如：
        // - 视野内是否有敌人
        // - 是否在掩体旁
        // - 是否持有武器
        // - 当前生命值
    }

    /// <summary>
    /// 选择当前最优目标（子类重写，实现目标优先级逻辑）
    /// </summary>
    protected virtual WorldState SelectGoal()
    {
        int health = _worldState.Get<int>("health", 100);
        bool enemyVisible = _worldState.Get<bool>("enemyVisible", false);
        bool isAlive = _worldState.Get<bool>("isAlive", true);

        // 目标优先级：生存 > 战斗 > 巡逻
        if (!isAlive)
        {
            // 无法执行（已死亡）
            return _worldState;
        }

        if (health < 30)
        {
            // 优先撤退/治疗
            var healGoal = new WorldState();
            healGoal.Set("health", 100);
            return healGoal;
        }

        if (enemyVisible)
        {
            // 消灭敌人
            var killGoal = new WorldState();
            killGoal.Set("enemyDead", true);
            return killGoal;
        }

        // 巡逻
        var patrolGoal = new WorldState();
        patrolGoal.Set("atPatrolPoint", true);
        return patrolGoal;
    }

    /// <summary>
    /// 判断是否需要重规划（子类重写）
    /// </summary>
    protected virtual bool ShouldReplan()
    {
        // 敌人出现/消失时触发重规划
        bool enemyVisible = _worldState.Get<bool>("enemyVisible", false);
        if (_currentGoal != null)
        {
            bool goalRequiresEnemy = _currentGoal.Has("enemyDead");
            if (goalRequiresEnemy && !enemyVisible) return true;
        }
        return false;
    }

    private void OnDrawGizmosSelected()
    {
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(transform.position, _perceptionRadius);

        if (_currentAction != null && _currentAction.Target != null)
        {
            Gizmos.color = Color.red;
            Gizmos.DrawLine(transform.position, _currentAction.Target.transform.position);
        }
    }
}
```

## 五、具体行动实现示例

### 5.1 寻找武器行动

```csharp
using System.Collections;
using UnityEngine;

/// <summary>
/// 行动：寻找并拾取武器
/// 前提条件：没有武器（hasWeapon=false）
/// 效果：持有武器（hasWeapon=true）
/// </summary>
public class FindWeaponAction : GOAPAction
{
    [SerializeField] private string _weaponTag = "Weapon";
    private GameObject _weapon;

    protected override void SetupConditions()
    {
        _actionName = "FindWeapon";
        _cost = 2f;

        // 前提条件：没有武器
        _preconditions.Set("hasWeapon", false);

        // 效果：获得武器
        _effects.Set("hasWeapon", true);
    }

    public override bool CheckProceduralPrecondition(GameObject agent)
    {
        // 运行时检查：附近是否存在武器
        _weapon = FindNearestWeapon(agent.transform.position);
        if (_weapon != null)
        {
            Target = _weapon;
            return true;
        }
        return false;
    }

    private GameObject FindNearestWeapon(Vector3 position)
    {
        GameObject[] weapons = GameObject.FindGameObjectsWithTag(_weaponTag);
        if (weapons.Length == 0) return null;

        GameObject nearest = null;
        float minDist = float.MaxValue;

        foreach (var w in weapons)
        {
            float dist = Vector3.Distance(position, w.transform.position);
            if (dist < minDist)
            {
                minDist = dist;
                nearest = w;
            }
        }

        return nearest;
    }

    public override IEnumerator Perform(GameObject agent)
    {
        IsRunning = true;

        if (_weapon == null || _weapon.activeSelf == false)
        {
            // 武器消失
            IsRunning = false;
            yield break;
        }

        // 拾取动画
        yield return new WaitForSeconds(0.5f);

        // 模拟拾取
        Debug.Log($"[{agent.name}] 拾取武器：{_weapon.name}");
        _weapon.SetActive(false); // 武器消失（被拾取）

        IsRunning = false;
    }
}
```

### 5.2 装弹行动

```csharp
using System.Collections;
using UnityEngine;

/// <summary>
/// 行动：装弹
/// 前提：hasWeapon=true, weaponLoaded=false
/// 效果：weaponLoaded=true
/// </summary>
public class LoadWeaponAction : GOAPAction
{
    [SerializeField] private float _reloadTime = 2f;

    protected override void SetupConditions()
    {
        _actionName = "LoadWeapon";
        _cost = 1f;

        _preconditions.Set("hasWeapon", true);
        _preconditions.Set("weaponLoaded", false);

        _effects.Set("weaponLoaded", true);
    }

    public override bool CheckProceduralPrecondition(GameObject agent) => true;

    public override IEnumerator Perform(GameObject agent)
    {
        IsRunning = true;

        Debug.Log($"[{agent.name}] 开始装弹...");

        // 播放装弹动画
        Animator animator = agent.GetComponent<Animator>();
        animator?.SetTrigger("Reload");

        yield return new WaitForSeconds(_reloadTime);

        Debug.Log($"[{agent.name}] 装弹完成");
        IsRunning = false;
    }
}
```

### 5.3 寻找掩体行动

```csharp
using System.Collections;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 行动：移动到掩体
/// 前提：（无特殊前提）
/// 效果：atCover=true
/// </summary>
public class FindCoverAction : GOAPAction
{
    [SerializeField] private string _coverTag = "Cover";
    [SerializeField] private float _coverRadius = 20f;

    protected override void SetupConditions()
    {
        _actionName = "FindCover";
        _cost = 1.5f;

        // 无特殊前提
        _effects.Set("atCover", true);
    }

    public override bool CheckProceduralPrecondition(GameObject agent)
    {
        // 寻找最近的、且能遮挡敌人的掩体
        Collider[] covers = Physics.OverlapSphere(agent.transform.position, _coverRadius);
        foreach (var col in covers)
        {
            if (col.CompareTag(_coverTag))
            {
                Target = col.gameObject;
                return true;
            }
        }
        return false;
    }

    public override IEnumerator Perform(GameObject agent)
    {
        IsRunning = true;

        // 已到达掩体（由Agent的移动系统保证）
        Debug.Log($"[{agent.name}] 已到达掩体：{Target?.name}");

        yield return new WaitForSeconds(0.2f);

        IsRunning = false;
    }
}
```

### 5.4 攻击敌人行动

```csharp
using System.Collections;
using UnityEngine;

/// <summary>
/// 行动：攻击敌人
/// 前提：weaponLoaded=true, enemyVisible=true
/// 效果：enemyDead=true, weaponLoaded=false（射击后需要装弹）
/// </summary>
public class AttackEnemyAction : GOAPAction
{
    [SerializeField] private float _attackRange = 10f;
    [SerializeField] private int _damage = 30;
    [SerializeField] private float _attackCooldown = 1f;
    [SerializeField] private string _enemyTag = "Enemy";

    private GameObject _enemy;

    protected override void SetupConditions()
    {
        _actionName = "AttackEnemy";
        _cost = 1f;

        _preconditions.Set("weaponLoaded", true);
        _preconditions.Set("enemyVisible", true);

        _effects.Set("enemyDead", true);
        _effects.Set("weaponLoaded", false); // 弹药消耗
    }

    protected override float GetActionRange() => _attackRange;

    public override bool CheckProceduralPrecondition(GameObject agent)
    {
        // 寻找视野内最近的敌人
        Collider[] colliders = Physics.OverlapSphere(agent.transform.position, _attackRange);
        foreach (var col in colliders)
        {
            if (col.CompareTag(_enemyTag))
            {
                _enemy = col.gameObject;
                Target = _enemy;
                return true;
            }
        }
        return false;
    }

    public override IEnumerator Perform(GameObject agent)
    {
        IsRunning = true;

        if (_enemy == null || !_enemy.activeInHierarchy)
        {
            IsRunning = false;
            yield break;
        }

        Debug.Log($"[{agent.name}] 攻击敌人：{_enemy.name}");

        // 播放攻击动画
        Animator animator = agent.GetComponent<Animator>();
        animator?.SetTrigger("Attack");

        // 攻击间隔
        yield return new WaitForSeconds(_attackCooldown);

        // 施加伤害
        var health = _enemy.GetComponent<HealthComponent>();
        if (health != null)
        {
            health.TakeDamage(_damage);
            if (health.IsDead)
            {
                Debug.Log($"[{agent.name}] 敌人已消灭：{_enemy.name}");
            }
        }

        IsRunning = false;
    }
}
```

## 六、高级扩展：GOAP + 行为树混合架构

### 6.1 混合架构设计

```csharp
/// <summary>
/// GOAP + 行为树混合架构
/// 行为树负责高层决策和紧急响应（如受击逃跑）
/// GOAP负责战术规划（如清除区域敌人）
/// </summary>
public class HybridGOAPBTAgent : GOAPAgent
{
    // 紧急响应优先级（行为树处理）
    private enum EmergencyState
    {
        None,
        UnderHeavyFire,  // 遭受密集火力
        Retreating,      // 撤退中
        CallForBackup    // 呼叫增援
    }

    private EmergencyState _emergencyState = EmergencyState.None;

    protected override void UpdateWorldState()
    {
        base.UpdateWorldState();

        // 紧急状态检测（高优先级，绕过GOAP规划）
        int health = _worldState.Get<int>("health", 100);
        bool underFire = _worldState.Get<bool>("underHeavyFire", false);

        if (health < 10 || underFire)
        {
            _emergencyState = EmergencyState.UnderHeavyFire;
        }
        else
        {
            _emergencyState = EmergencyState.None;
        }
    }

    protected override WorldState SelectGoal()
    {
        // 紧急状态下的目标覆盖GOAP规划
        if (_emergencyState == EmergencyState.UnderHeavyFire)
        {
            var retreatGoal = new WorldState();
            retreatGoal.Set("atSafeZone", true);
            return retreatGoal;
        }

        // 正常情况由GOAP决策
        return base.SelectGoal();
    }

    protected override bool ShouldReplan()
    {
        // 紧急状态变化时必须重规划
        if (_emergencyState != EmergencyState.None) return true;
        return base.ShouldReplan();
    }
}
```

## 七、GOAP调试可视化

### 7.1 编辑器调试工具

```csharp
#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using System.Collections.Generic;

/// <summary>
/// GOAP规划可视化调试器
/// 在Scene视图中显示当前规划路径
/// </summary>
[CustomEditor(typeof(GOAPAgent))]
public class GOAPAgentEditor : Editor
{
    private GOAPAgent _agent;

    private void OnEnable()
    {
        _agent = (GOAPAgent)target;
    }

    public override void OnInspectorGUI()
    {
        base.OnInspectorGUI();

        if (!Application.isPlaying) return;

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("=== GOAP运行时状态 ===", EditorStyles.boldLabel);

        // 显示当前世界状态
        EditorGUILayout.LabelField("当前世界状态：");
        // 通过反射或公开接口展示 _worldState

        // 显示当前目标
        EditorGUILayout.LabelField("当前目标：");

        // 显示当前规划
        EditorGUILayout.LabelField("当前行动：");

        // 强制重刷Inspector
        if (Application.isPlaying)
        {
            Repaint();
        }
    }
}
#endif
```

## 八、性能优化策略

### 8.1 规划频率控制

```csharp
public class OptimizedGOAPAgent : GOAPAgent
{
    // 只在状态发生变化时触发重规划，而非定时触发
    private WorldState _lastPlanWorldState;
    private WorldState _lastPlanGoal;

    protected override bool ShouldReplan()
    {
        // 世界状态或目标发生变化时才重规划
        WorldState newGoal = SelectGoal();
        bool stateChanged = !_worldState.Equals(_lastPlanWorldState);
        bool goalChanged = !newGoal.Equals(_lastPlanGoal);

        if (stateChanged || goalChanged)
        {
            _lastPlanWorldState = new WorldState(_worldState);
            _lastPlanGoal = new WorldState(newGoal);
            return true;
        }

        return false;
    }
}
```

### 8.2 行动图缓存

```csharp
/// <summary>
/// 行动图缓存：避免重复计算可能的行动组合
/// 对于相同的世界状态和目标，直接返回缓存的规划结果
/// </summary>
public class CachedGOAPPlanner
{
    private static Dictionary<(int stateHash, int goalHash), Queue<GOAPAction>> _cache
        = new Dictionary<(int, int), Queue<GOAPAction>>();

    private const int MAX_CACHE_SIZE = 100;

    public static Queue<GOAPAction> Plan(
        GameObject agent,
        List<GOAPAction> actions,
        WorldState state,
        WorldState goal)
    {
        int stateHash = state.GetHashCode();
        int goalHash = goal.GetHashCode();
        var key = (stateHash, goalHash);

        if (_cache.TryGetValue(key, out Queue<GOAPAction> cached))
        {
            // 返回缓存结果的副本
            return new Queue<GOAPAction>(cached);
        }

        Queue<GOAPAction> plan = GOAPPlanner.Plan(agent, actions, state, goal);

        if (plan != null)
        {
            // 缓存管理
            if (_cache.Count >= MAX_CACHE_SIZE)
            {
                // LRU淘汰（简化版：直接清空）
                _cache.Clear();
            }
            _cache[key] = new Queue<GOAPAction>(plan);
        }

        return plan;
    }

    public static void ClearCache() => _cache.Clear();
}
```

## 九、最佳实践总结

### 9.1 GOAP设计原则

```
✅ 行动设计原则
  □ 每个行动应尽量原子化（单一职责）
  □ 前提条件和效果要精确，避免过于宽泛
  □ 代价（Cost）要合理设置，反映行动的实际消耗
  □ CheckProceduralPrecondition 做运行时可行性检查

✅ 世界状态设计原则  
  □ 只包含AI决策所需的关键状态
  □ 避免过于细粒度（状态爆炸）
  □ 感知系统与世界状态更新解耦
  □ 注意状态同步（多Agent共享世界状态）

✅ 目标设计原则
  □ 目标要具体且可达
  □ 实现优先级机制（生存 > 战斗 > 任务）
  □ 支持紧急目标打断正常规划
  □ 目标不满足时提供回退目标

✅ 性能优化
  □ 限制规划频率（不要每帧规划）
  □ 控制A*搜索深度（maxIterations）
  □ 缓存相同状态的规划结果
  □ 多个Agent分帧规划，避免同帧计算峰值
```

### 9.2 GOAP适用场景

- **战术NPC**：士兵AI（F.E.A.R.的经典案例）
- **策略游戏**：单位AI自主决策
- **生存游戏**：AI动态适应环境变化
- **Boss AI**：多阶段复杂战斗模式
- **不适合**：简单NPC（成本过高）、实时性要求极高的场景

## 十、总结

GOAP通过将AI行为分解为独立的**行动（Action）**，并用**A*规划算法**在世界状态空间中搜索最优行动序列，实现了真正意义上的"智能NPC"。相比行为树需要手动编写每种场景的响应逻辑，GOAP让AI能够自主组合行动应对各种情况，极大提升了NPC的智能感和可扩展性。

**核心要点：**
1. **世界状态是GOAP的血液**，状态设计决定了AI的感知范围
2. **行动代价影响路径选择**，合理设置cost让AI做出更真实的决策
3. **程序性前提条件**弥补静态条件的不足，实现运行时动态检查
4. **目标优先级系统**让AI在多目标间做出正确选择
5. **重规划触发时机**是性能与响应性的平衡点
