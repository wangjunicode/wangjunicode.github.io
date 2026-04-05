---
title: 游戏AI行为树高级设计：条件装饰器与服务节点
published: 2026-03-31
description: 深度解析游戏AI行为树的高级组件，涵盖条件装饰器（Blackboard比较/距离检测/概率触发）、服务节点（定期更新Blackboard数据）、并行节点（同时追踪与攻击）、中断优先级（高优先级子树随时打断当前执行）、行为树调试可视化，以及与感知系统/动画系统的整合方案。
tags: [Unity, 行为树, 游戏AI, AI设计, 游戏开发]
category: 游戏AI
draft: false
encryptedKey: henhaoji123
---

## 一、行为树核心节点类型

```
行为树节点类型：

复合节点（Composite）：
├── Sequence（顺序）：子节点依次执行，一个失败则失败
├── Selector（选择）：子节点依次执行，一个成功则成功
├── Parallel（并行）：同时执行多个子节点
└── RandomSelector：随机顺序执行选择器

装饰器（Decorator）：
├── Inverter：取反子节点结果
├── Repeater：重复执行N次或无限
├── Cooldown：冷却时间限制
├── BlackboardCondition：Blackboard值条件检查
└── TimeLimit：超时失败

叶节点（Leaf/Task）：
├── MoveTo：移动到目标位置
├── PlayAnimation：播放动画
├── AttackTarget：攻击目标
├── Wait：等待
└── SetBlackboard：设置Blackboard值

服务节点（Service）：（附加在节点上，定期执行）
├── FindNearestEnemy：定期查找最近敌人
├── UpdatePatrolPoint：更新巡逻点
└── CheckSightLine：视线检测
```

---

## 二、行为树实现框架

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 节点状态
/// </summary>
public enum NodeStatus { Running, Success, Failure }

/// <summary>
/// Blackboard（行为树的共享数据存储）
/// </summary>
public class Blackboard
{
    private Dictionary<string, object> data = new Dictionary<string, object>();

    public void Set<T>(string key, T value) => data[key] = value;
    
    public T Get<T>(string key, T defaultValue = default)
    {
        if (data.TryGetValue(key, out var val) && val is T typed)
            return typed;
        return defaultValue;
    }
    
    public bool Has(string key) => data.ContainsKey(key);
    
    public void Remove(string key) => data.Remove(key);
    
    public bool TryGet<T>(string key, out T value)
    {
        if (data.TryGetValue(key, out var val) && val is T typed)
        {
            value = typed;
            return true;
        }
        value = default;
        return false;
    }
}

/// <summary>
/// 行为树节点基类
/// </summary>
public abstract class BTNode
{
    public string Name;
    protected Blackboard blackboard;
    protected GameObject owner;
    
    protected List<BTService> services = new List<BTService>();
    protected NodeStatus lastStatus;

    public virtual void Initialize(Blackboard bb, GameObject agent)
    {
        blackboard = bb;
        owner = agent;
    }

    public NodeStatus Tick()
    {
        // 执行服务节点
        foreach (var service in services)
            service.OnTick(blackboard, owner);
        
        lastStatus = Execute();
        return lastStatus;
    }

    protected abstract NodeStatus Execute();
    
    public virtual void OnAbort() { }
    
    public BTNode AddService(BTService service)
    {
        services.Add(service);
        return this;
    }
}

/// <summary>
/// Sequence 顺序节点
/// </summary>
public class SequenceNode : BTNode
{
    private List<BTNode> children = new List<BTNode>();
    private int currentIndex;

    public SequenceNode(string name, params BTNode[] children)
    {
        Name = name;
        this.children.AddRange(children);
    }

    public override void Initialize(Blackboard bb, GameObject agent)
    {
        base.Initialize(bb, agent);
        foreach (var child in children)
            child.Initialize(bb, agent);
    }

    protected override NodeStatus Execute()
    {
        while (currentIndex < children.Count)
        {
            var status = children[currentIndex].Tick();
            
            if (status == NodeStatus.Running)
                return NodeStatus.Running;
            
            if (status == NodeStatus.Failure)
            {
                currentIndex = 0; // 重置
                return NodeStatus.Failure;
            }
            
            currentIndex++;
        }
        
        currentIndex = 0;
        return NodeStatus.Success;
    }
}

/// <summary>
/// Selector 选择节点
/// </summary>
public class SelectorNode : BTNode
{
    private List<BTNode> children = new List<BTNode>();

    public SelectorNode(string name, params BTNode[] children)
    {
        Name = name;
        this.children.AddRange(children);
    }

    public override void Initialize(Blackboard bb, GameObject agent)
    {
        base.Initialize(bb, agent);
        foreach (var child in children) child.Initialize(bb, agent);
    }

    protected override NodeStatus Execute()
    {
        foreach (var child in children)
        {
            var status = child.Tick();
            if (status != NodeStatus.Failure)
                return status;
        }
        return NodeStatus.Failure;
    }
}

/// <summary>
/// Blackboard 条件装饰器
/// </summary>
public class BlackboardConditionDecorator : BTNode
{
    private BTNode child;
    private string key;
    private object expectedValue;
    private CompareOp op;
    
    public enum CompareOp { Equals, NotEquals, IsSet, IsNotSet, Greater, Less }

    public BlackboardConditionDecorator(string key, CompareOp op, 
        object value, BTNode child)
    {
        this.key = key;
        this.op = op;
        this.expectedValue = value;
        this.child = child;
        Name = $"Check[{key}]";
    }

    public override void Initialize(Blackboard bb, GameObject agent)
    {
        base.Initialize(bb, agent);
        child.Initialize(bb, agent);
    }

    protected override NodeStatus Execute()
    {
        if (!CheckCondition())
            return NodeStatus.Failure;
        
        return child.Tick();
    }

    bool CheckCondition()
    {
        switch (op)
        {
            case CompareOp.IsSet:
                return blackboard.Has(key);
            case CompareOp.IsNotSet:
                return !blackboard.Has(key);
            case CompareOp.Equals:
                return Equals(blackboard.Get<object>(key), expectedValue);
            case CompareOp.NotEquals:
                return !Equals(blackboard.Get<object>(key), expectedValue);
            case CompareOp.Greater:
                if (blackboard.TryGet<float>(key, out float fVal))
                    return fVal > (float)expectedValue;
                return false;
            case CompareOp.Less:
                if (blackboard.TryGet<float>(key, out float fVal2))
                    return fVal2 < (float)expectedValue;
                return false;
        }
        return false;
    }
}

/// <summary>
/// 服务节点（定期更新Blackboard）
/// </summary>
public abstract class BTService
{
    public float Interval;
    protected float timer;
    
    public BTService(float interval)
    {
        Interval = interval;
    }

    public void OnTick(Blackboard bb, GameObject owner)
    {
        timer += Time.deltaTime;
        if (timer >= Interval)
        {
            timer = 0;
            Execute(bb, owner);
        }
    }

    protected abstract void Execute(Blackboard bb, GameObject owner);
}

/// <summary>
/// 查找最近敌人服务
/// </summary>
public class FindNearestEnemyService : BTService
{
    private float searchRadius;
    private LayerMask enemyMask;
    private Collider[] buffer = new Collider[10];

    public FindNearestEnemyService(float interval, float radius, LayerMask mask) 
        : base(interval)
    {
        searchRadius = radius;
        enemyMask = mask;
    }

    protected override void Execute(Blackboard bb, GameObject owner)
    {
        int count = Physics.OverlapSphereNonAlloc(
            owner.transform.position, searchRadius, buffer, enemyMask);
        
        GameObject nearest = null;
        float minDist = float.MaxValue;
        
        for (int i = 0; i < count; i++)
        {
            if (buffer[i].gameObject == owner) continue;
            float dist = Vector3.Distance(owner.transform.position, 
                buffer[i].transform.position);
            if (dist < minDist)
            {
                minDist = dist;
                nearest = buffer[i].gameObject;
            }
        }
        
        if (nearest != null)
        {
            bb.Set("target", nearest);
            bb.Set("targetDistance", minDist);
        }
        else
        {
            bb.Remove("target");
        }
    }
}
```

---

## 三、AI 行为树示例

```csharp
/// <summary>
/// 构建巡逻→追击→攻击的完整行为树
/// </summary>
public class EnemyAI : MonoBehaviour
{
    private Blackboard blackboard;
    private BTNode rootNode;

    void Start()
    {
        blackboard = new Blackboard();
        blackboard.Set("patrolRadius", 10f);
        blackboard.Set("attackRange", 2f);
        blackboard.Set("chaseRange", 15f);
        
        BuildBehaviorTree();
    }

    void BuildBehaviorTree()
    {
        // 选择：攻击 | 追击 | 巡逻
        rootNode = new SelectorNode("Root",
            // 优先级1：如果目标在攻击范围内→攻击
            new BlackboardConditionDecorator(
                "targetDistance", BlackboardConditionDecorator.CompareOp.Less, 2f,
                new AttackTargetNode()
            ),
            // 优先级2：如果有目标→追击
            new BlackboardConditionDecorator(
                "target", BlackboardConditionDecorator.CompareOp.IsSet,
                null,
                new ChaseTargetNode()
            ),
            // 优先级3：巡逻
            new PatrolNode()
        );
        
        // 在 Root 节点上添加 FindNearestEnemy 服务（每0.2秒更新一次）
        rootNode.AddService(new FindNearestEnemyService(
            0.2f, 15f, LayerMask.GetMask("Player")));
        
        rootNode.Initialize(blackboard, gameObject);
    }

    void Update()
    {
        rootNode.Tick();
    }
}

// 具体任务节点（示意）
class AttackTargetNode : BTNode { protected override NodeStatus Execute() => NodeStatus.Success; }
class ChaseTargetNode : BTNode { protected override NodeStatus Execute() => NodeStatus.Running; }
class PatrolNode : BTNode { protected override NodeStatus Execute() => NodeStatus.Running; }
```

---

## 四、行为树调试工具

```csharp
/// <summary>
/// 行为树运行时可视化（调试）
/// </summary>
public class BehaviorTreeDebugger : MonoBehaviour
{
    void OnGUI()
    {
        if (!Application.isEditor) return;
        
        GUILayout.BeginArea(new Rect(10, 10, 300, 500));
        GUILayout.Label("== 行为树状态 ==", GUI.skin.box);
        
        // 显示 Blackboard 数据
        // 实际实现需要遍历所有节点状态
        
        GUILayout.EndArea();
    }
}
```

---

## 五、行为树 vs 状态机对比

| 维度 | 行为树 | 状态机 |
|------|--------|--------|
| 复杂度 | 高（层次化）| 低（扁平）|
| 可扩展性 | 强（新增节点即可）| 中（状态爆炸）|
| 调试 | 可视化工具丰富 | 相对简单 |
| 适用场景 | 复杂AI（多状态/多目标）| 简单AI/角色状态 |
| 性能 | 较高（需要优化）| 低 |
