---
title: 剧情触发器节点处理器——FlowCanvas图系统的延迟、定时器与战斗事件触发
published: 2026-03-31
description: 解析UniScript FlowCanvas框架中触发器节点处理器的设计，包括延迟节点、重复定时器与战斗关键点事件监听
tags: [Unity, 剧情系统, 节点系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 剧情触发器节点处理器——FlowCanvas图系统的延迟、定时器与战斗事件触发

在xgame的剧情系统中，"什么时候触发剧情"由触发器图（TriggerGraph）控制。触发器图是一个由节点连接而成的图，每个节点代表一种触发条件或等待行为。

本文分析三种最核心的触发器节点处理器：延迟（`TG_DelayHandler`）、定时器（`TG_TimerHandler`）和战斗事件（`TG_BattlePointEventHandler`）。

## 一、节点处理器的职责

```csharp
// 基类（推测）
public abstract class AFlowNodeHandler<T> where T : FlowNode
{
    // 图启动后（可重写：注册事件监听、启动计时器等）
    public virtual void OnPostGraphStarted(T flowNode) { }
    
    // 图停止后（可重写：注销监听、清理资源）
    public virtual void OnGraphStoped(T flowNode) { }
    
    // 注册端口（必须实现：定义节点的输入/输出连接点）
    public abstract void RegisterPorts(T flowNode);
}
```

**节点 vs 节点处理器**：

- **节点（Node）**：数据类，存储配置（如延迟时间、事件类型）。是可序列化的、由策划/编辑器配置的
- **节点处理器（NodeHandler）**：逻辑类，执行节点的运行时行为。是纯逻辑的、不可序列化的

这种分离让节点图可以保存（只序列化数据节点），而运行时行为在游戏启动时通过反射/注册表与节点关联。

## 二、延迟节点（TG_Delay）

```csharp
public class TG_DelayHandler : AFlowNodeHandler<TG_Delay>
{
    public override void OnPostGraphStarted(TG_Delay flowNode)
    {
        Delay(flowNode).Coroutine();
    }

    public override void RegisterPorts(TG_Delay flowNode)
    {
        flowNode.exec = flowNode.AddFlowOutput("Exec"); // 添加输出端口
    }

    public async ETTask Delay(TG_Delay flowNode)
    {
        // 等待指定时间（受取消令牌控制）
        await LogicTimerComponent.Instance.WaitAsync(
            flowNode.delayTime, 
            flowNode.graph.cancellationToken); // 如果图被停止，取消令牌触发，等待中断
        
        if (!flowNode.graph.cancellationToken.IsCancel())
        {
            flowNode.exec.Call(new Flow()); // 延迟结束，激活输出端口
        }
    }
}
```

**关键设计1：CancellationToken的使用**

`flowNode.graph.cancellationToken`是整个图的取消令牌。如果剧情图被中途停止（玩家跳过剧情、离开场景），令牌被取消，`WaitAsync`立刻返回，`IsCancel()`为true，`exec.Call`不会执行。

如果没有这个取消机制：玩家跳过剧情 → 图停止 → 但5秒后延迟节点仍然触发后续流程 → 剧情在已经停止的图上继续执行 → 空引用崩溃。

**关键设计2：`.Coroutine()`的作用**

`Delay(flowNode).Coroutine()`把异步任务放到"后台"运行（不等待其完成）。`OnPostGraphStarted`是同步函数，不能直接await，通过`.Coroutine()`启动异步任务但不阻塞当前线程。

## 三、定时器节点（TG_Timer）——Invoke模式

```csharp
// 定时回调的实现（ATimer模式）
[Invoke(TimerInvokeType.UniFlowNodeTimer)]
public class TG_TimerTimer : ATimer<TG_Timer>
{
    protected override void Run(TG_Timer self)
    {
        self.exec.Call(new Flow()); // 每次到期，激活输出端口
    }
}

// 定时器节点处理器
public class TG_TimerHandler : AFlowNodeHandler<TG_Timer>
{
    public override void OnPostGraphStarted(TG_Timer flowNode)
    {
        // 最小间隔检查（100ms，防止过于频繁的定时器）
        if (flowNode.intervalTime < 100)
        {
            Log.Error(ZString.Format("错误的intervalTime: {0}", flowNode.intervalTime));
            return;
        }
        
        // 创建重复定时器（每intervalTime毫秒触发一次）
        flowNode.Timer = LogicTimerComponent.Instance.NewRepeatedTimer(
            flowNode.intervalTime, 
            TimerInvokeType.UniFlowNodeTimer, 
            flowNode); // flowNode作为context传入
    }

    public override void OnGraphStoped(TG_Timer flowNode)
    {
        // 图停止时，必须移除定时器
        LogicTimerComponent.Instance?.Remove(ref flowNode.Timer);
    }

    public override void RegisterPorts(TG_Timer flowNode)
    {
        flowNode.exec = flowNode.AddFlowOutput("Exec");
    }
}
```

**TG_Timer vs TG_Delay的区别**：

- `TG_Delay`：一次性延迟（等一段时间，然后触发一次）
- `TG_Timer`：重复定时（每隔固定时间触发一次，直到图停止）

定时器用于周期性检查（比如"每5秒检查一次玩家的状态是否满足触发条件"）。

**`[Invoke(TimerInvokeType.UniFlowNodeTimer)]`特性**：

ET框架的定时器系统通过枚举类型来区分不同的定时器回调。`TG_TimerTimer`注册了`UniFlowNodeTimer`类型，`NewRepeatedTimer`创建定时器时传入同样的类型，到期时框架会找到对应的处理器（`TG_TimerTimer`）并调用`Run`。

**为什么`Remove(ref flowNode.Timer)`需要ref参数？**

`Remove`会把Timer的ID置为0（重置），`ref`确保修改直接反映到`flowNode.Timer`字段，防止已经移除的Timer ID被重复使用。

## 四、战斗关键点事件节点（TG_BattleEvent）

```csharp
public class TG_BattlePointEventHandler : AFlowNodeHandler<TG_BattleEvent>, IGenericEvtScriptHandler
{
    public override void OnPostGraphStarted(TG_BattleEvent flowNode)
    {
        // 找到拥有者技能实体
        var BuffGraph = flowNode.rootGraph as BuffGraph;
        Entity ownerPSkill = null;
        if (BuffGraph != null)
            ownerPSkill = BuffGraph.buff.ownerSkill;
        
        if (ownerPSkill != null)
        {
            // 监听战斗关键点事件（注册在技能实体上）
            ownerPSkill.GetComponent<EventDispatcherComponent>()
                .RegisterEvent<Evt_PointEvent>(flowNode.OnFireEvent);
        }
    }

    public override void OnGraphStoped(TG_BattleEvent flowNode)
    {
        // 图停止时，取消监听
        if (ownerPSkill != null)
        {
            ownerPSkill.GetComponent<EventDispatcherComponent>()
                .UnRegisterEvent<Evt_PointEvent>(flowNode.OnFireEvent);
        }
    }

    public override void RegisterPorts(TG_BattleEvent flowNodeBase)
    {
        var flowNode = flowNodeBase;
        
        // 输入端口（节点接受这些参数）
        flowNode.target = flowNode.AddValueInput<ETriggerTarget>("事件对象", "target");
        flowNode.tags = flowNode.AddValueInput<List<EBPTag>>("触发事件Tag", "tags");
        flowNode.bTriggerInBackUp = flowNode.AddValueInput<bool>("后排可触发", "bTriggerInBackUp");
        flowNode.bListenOtherMember = flowNode.AddValueInput<bool>("监听队友事件", "bListenOtherMember");
        
        // 次数限制（-1表示无限）
        flowNode.limitTime = flowNode.AddValueInput<int>("次数限制", "limitTime")
            .SetDefaultAndSerializedValue(-1); // 默认值-1（无限触发）
        
        // 输出端口
        flowNode.exec = flowNode.AddFlowOutput("Exec");
        flowNode.AddValueOutput("EventOwner", () => flowNode.EventOwner);
        flowNode.AddValueOutput("TriggerTime", () => flowNode.triggerTime);
        
        // 非起始节点时添加Start/Stop/Reset端口（可以从外部控制节点的开关）
        if (!flowNodeBase.asStartNode)
        {
            flowNode.bStart = false;
            flowNode.start = flowNode.AddFlowInput("Start", (f) => ((TG_BattleEvent)f.node).bStart = true);
            flowNode.reStart = flowNode.AddFlowInput("ReStart", (f) => { ... });
            flowNode.stop = flowNode.AddFlowInput("Stop", (f) => ((TG_BattleEvent)f.node).bStart = false);
            flowNode.reset = flowNode.AddFlowInput("Reset", (f) => ((TG_BattleEvent)f.node).triggerTime = 0);
        }
    }
}
```

**最丰富的端口设计**：

`TG_BattleEvent`是最复杂的触发器节点，它有8个端口：
- **输入端口（4个）**：配置参数（事件对象、Tag、是否后排触发、是否监听队友）
- **流程输入端口（4个）**：Start、Stop、ReStart、Reset（用于外部控制这个监听器的开关）
- **流程输出端口（1个）**：事件触发时激活的主输出
- **数据输出端口（2个）**：EventOwner（事件的触发者）、TriggerTime（已触发次数）

`asStartNode`区分"自动开始监听"（起始节点）和"需要外部激活才开始监听"（非起始节点）。

## 五、注册在技能实体上的事件监听

```csharp
ownerPSkill.GetComponent<EventDispatcherComponent>()
    .RegisterEvent<Evt_PointEvent>(flowNode.OnFireEvent);
```

注册在技能实体（`ownerPSkill`）的EventDispatcher上，而不是全局的EventDispatcher上。

**精确性的价值**：全局监听所有角色的战斗事件会产生大量的过滤逻辑（判断是不是我关心的角色的事件），而挂在技能实体上，只接收与该技能关联的事件，天然过滤了无关事件。

## 六、总结

触发器节点处理器展示了：

1. **数据/行为分离**：Node存数据，Handler实现运行时行为
2. **CancellationToken**：图停止时所有异步操作都要能被取消
3. **端口系统**：输入参数、流程控制、数据输出各种端口类型
4. **精确事件作用域**：在具体实体上注册，而不是全局注册
5. **最小间隔检查**：防止配置错误导致的性能问题

对新手来说，这套触发器系统最大的启发是：**可视化节点编辑和代码逻辑的桥梁是"端口（Port）"的概念**——节点的输入/输出端口让策划可以在图里"拖线连接"，而程序员只需要实现节点在运行时"如何通过端口交换数据和控制流"。
