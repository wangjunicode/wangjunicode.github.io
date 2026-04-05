---
title: 基于节点图的有限状态机设计原理与实现解析
published: 2026-03-31
description: 深入解析节点驱动的有限状态机框架，理解状态进入/更新/退出的生命周期、转换条件评估机制和编辑器可视化设计。
tags: [Unity, 状态机, AI设计, 游戏架构]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么游戏需要状态机？

游戏中的实体（角色、NPC、UI 界面）都有明确的"状态"：

- **角色状态**：待机、移动、攻击、受击、死亡
- **UI 状态**：关闭、打开、过渡中、最小化
- **NPC AI**：巡逻、警觉、追逐、攻击、逃跑

状态机（FSM：Finite State Machine）是管理这类状态的经典方法。

---

## IState 接口：状态的最小契约

```csharp
public interface IState
{
    string name { get; }          // 状态名称
    string tag { get; }           // 状态标签（用于分类）
    FP elapsedTime { get; }       // 在当前状态已持续的时间（FP = 定点数，帧同步用）
    FSM FSM { get; }              // 所属的状态机
    
    FSMConnection[] GetTransitions();  // 获取所有转换连接
    bool CheckTransitions();           // 检查并执行转换
    void Finish(bool success);         // 标记状态完成
}
```

注意 `elapsedTime` 的类型是 `FP`（Fixed Point），这是帧同步游戏中用定点数替代浮点数的典型做法——定点数运算在所有平台上结果完全一致，避免浮点数精度差异导致的帧同步问题。

---

## FSMState：状态基类的生命周期

```csharp
abstract public class FSMState : FSMNode, IState
{
    // 五个生命周期回调（子类重写）
    virtual protected void OnInit()   { }  // 第一次进入时调用（仅一次）
    virtual protected void OnEnter()  { }  // 每次进入状态时调用
    virtual protected void OnUpdate() { }  // 状态运行期间每帧调用
    virtual protected void OnExit()   { }  // 离开状态时调用
    virtual protected void OnPause()  { }  // 状态暂停时调用
}
```

这五个生命周期对应了一个状态的完整生存过程：

```
首次进入 → OnInit() → OnEnter()
每帧      → OnUpdate()（同时检查转换条件）
转换发生  → OnExit()
再次进入  → OnEnter()（不再调用 OnInit）
图暂停    → OnPause()
```

---

## 执行引擎：OnExecute 的状态驱动

`OnExecute` 是每帧被框架调用的核心方法：

```csharp
sealed protected override Status OnExecute(IUniAgent agent, IBlackboard bb) 
{
    // 首次初始化
    if (!_hasInit) {
        _hasInit = true;
        OnInit();
    }

    if (status == Status.Resting)  // 刚进入状态
    {
        status = Status.Running;
        
        // 启用所有出边的转换条件
        for (int i = 0; i < outConnections.Count; i++) {
            ((FSMConnection)outConnections[i]).EnableCondition(agent, bb);
        }
        
        // 通知 FSM 状态已进入
        if (graph is FSM fsm) {
            fsm.OnStateEnter();
        }
        
        OnEnter();  // 调用子类 OnEnter
    }
    else  // 状态运行中
    {
        CheckTransitions();  // 检查是否需要转换
        
        if (status == Status.Running) {
            OnUpdate();  // 没有发生转换，继续执行
        }
    }

    return status;
}
```

状态机的运行逻辑清晰可见：
1. 进入状态时初始化转换条件
2. 每帧先检查转换，没有转换才执行 Update
3. 发生转换后停止当前状态的 Update

---

## 转换条件评估：CheckTransitions

```csharp
public bool CheckTransitions() 
{
    for (var i = 0; i < outConnections.Count; i++) 
    {
        var connection = (FSMConnection)outConnections[i];
        var condition = connection.condition;

        // 跳过非激活的连接
        if (!connection.isActive) continue;
        
        // 跳过未运行时启用的条件
        if (condition != null && !condition.IsRuntimeEnabled) continue;
        
        // 两种评估模式
        var case1 = connection.transitionEvaluation == 
            FSMConnection.TransitionEvaluationMode.CheckContinuously;          // 持续检查
        var case2 = connection.transitionEvaluation == 
            FSMConnection.TransitionEvaluationMode.CheckAfterStateFinished     // 状态完成后检查
            && status != Status.Running;
            
        if (!case1 && !case2) continue;

        // 条件满足（或无条件 + 状态非 Running）
        if ((condition != null && condition.Check(graphAgent, graphBlackboard)) 
            || (condition == null && status != Status.Running))
        {
            FSM.EnterState((FSMState)connection.targetNode, connection.transitionCallMode);
            connection.status = Status.Success;
            condition?.OnCheckTrue();
            return true;  // 发生转换，返回
        }

        connection.status = Status.Failure;
    }

    return false;
}
```

**两种评估模式**：
- **持续检查（CheckContinuously）**：每帧都评估条件，条件满足立即转换
- **完成后检查（CheckAfterStateFinished）**：等状态调用 `Finish()` 后才检查

这两种模式覆盖了大多数状态转换场景：

```
攻击状态转死亡 → 持续检查（HP 降到零随时转换）
攻击动画结束转待机 → 完成后检查（动画完整播放后才转换）
```

---

## 转换连接的优先级

注意 `CheckTransitions` 是**按连接顺序遍历**的，遇到第一个满足条件的转换立即执行并返回。

这意味着：**连接的顺序决定了转换的优先级**。这是很多状态机 Bug 的来源——策划在节点图里添加了新的转换，但没有注意到顺序，导致优先级错误。

最佳实践：
- 高优先级转换（如死亡条件）应放在连接列表最前面
- 使用 `bInsertFront = true` 可以确保某个连接排在最前面

---

## 嵌套状态机：FSMStateNested

游戏中常见"层级状态机"需求：

```
战斗状态
  └─ 攻击状态
       └─ 普通攻击 / 技能攻击 / 连击
```

`FSMStateNested` 继承自 `FSMState`，允许一个状态内部包含另一个 FSM：

```csharp
public class FSMStateNested : FSMState
{
    [SerializeField]
    private FSM subFSM;  // 内嵌的子状态机
    
    protected override void OnEnter()
    {
        subFSM.StartGraph(graphAgent, graphBlackboard, false);
    }
    
    protected override void OnUpdate()
    {
        subFSM.UpdateGraph();
    }
    
    protected override void OnExit()
    {
        subFSM.StopGraph();
    }
}
```

这种设计允许无限层级的状态机嵌套，是处理复杂 AI 行为的有力工具。

---

## 实战：角色战斗状态机

```csharp
// 待机状态
public class IdleState : FSMState
{
    protected override void OnEnter()
    {
        animator.Play("Idle");
    }
    
    protected override void OnUpdate()
    {
        // 检查输入，如果按了攻击键就 Finish
        if (Input.GetButtonDown("Attack"))
        {
            Finish(true);  // 成功完成，触发"完成后检查"类型的转换
        }
    }
}

// 攻击状态
public class AttackState : FSMState
{
    private float _attackDuration = 0.5f;
    
    protected override void OnInit()
    {
        // 只初始化一次
        LoadAttackEffect();
    }
    
    protected override void OnEnter()
    {
        animator.Play("Attack");
        SpawnHitbox();
    }
    
    protected override void OnUpdate()
    {
        // 攻击动画播放完毕
        if (elapsedTime >= _attackDuration)
        {
            Finish(true);
        }
    }
    
    protected override void OnExit()
    {
        DestroyHitbox();
    }
}
```

---

## 编辑器可视化支持

`FSMState` 的 `#if UNITY_EDITOR` 块提供了丰富的编辑器支持：

```csharp
#if UNITY_EDITOR
protected override void OnNodeInspectorGUI()
{
    ShowTransitionsInspector();  // 在 Inspector 中显示转换列表
    DrawDefaultInspector();
}

protected override void OnNodeExternalGUI()
{
    // 运行时在节点图上绘制状态回退路径
    var peek = FSM.PeekStack();
    if (peek != null && FSM.currentState == this)
    {
        Handles.DrawAAPolyLine(rect.center, peek.rect.center);
    }
}
#endif
```

这让策划和程序都能通过可视化节点图直观地设计和调试状态机，而不需要在代码中理解状态转换关系。

---

## 总结

这套 FSM 框架的核心设计亮点：

| 设计点 | 实现 |
|--------|------|
| 状态生命周期 | OnInit/OnEnter/OnUpdate/OnExit/OnPause |
| 转换模式 | 持续检查 / 完成后检查 |
| 嵌套支持 | FSMStateNested |
| 帧同步兼容 | FP 定点数时间 |
| 可视化编辑 | 编辑器 GUI 代码内置 |
| 安全连接 | 防止循环连接检查 |

理解状态机是游戏 AI、角色控制、UI 流程管理的基础。掌握这套带节点图的可视化状态机，你就能在复杂的游戏逻辑中保持清晰的结构。
