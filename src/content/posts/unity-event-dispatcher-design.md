---
title: 基于优先级与带结果的事件分发系统设计详解
published: 2026-03-31
description: 深入解析支持优先级排序、带结果返回和安全迭代的事件系统实现，理解如何设计一个生产级的游戏事件总线。
tags: [Unity, 事件系统, 设计模式, 组件设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 什么是事件系统，为什么需要它？

游戏中有大量的"通知"需求：

- 角色死亡 → 通知 UI 刷新、通知任务系统检查、通知成就系统记录
- 玩家购买道具 → 通知背包更新、通知商店刷新、通知服务器同步
- 关卡开始 → 通知音乐系统、通知摄像机、通知 NPC 行为

如果直接调用：

```csharp
// ❌ 直接耦合，每添加一个监听者就要修改这里
public void OnCharacterDied(Character character)
{
    UIManager.RefreshKillCount();
    QuestSystem.CheckQuestProgress();
    AchievementSystem.RecordKill(character.Type);
    AnalyticsManager.TrackEvent("character_died");
}
```

这样的代码违反了「开闭原则」——每次添加新功能都需要修改原有代码。

事件系统的核心价值是：**发布者不需要知道谁在监听，监听者不需要知道谁在发布**。通过事件类型作为"频道"，实现松耦合通信。

---

## EventDispatcher 架构

### 监听器信息包装

```csharp
public class EventListenerInfo
{
    public Delegate listener;   // 真正的回调委托
    public int priority;        // 优先级（越大越先执行）
    public bool invalid;        // 是否已失效（软删除标记）
}
```

`invalid` 字段是关键——它实现了"软删除"：在事件触发过程中，如果某个监听器被注销，不立即从列表删除（这会导致迭代器失效），而是标记为 `invalid`，在下次触发时跳过。

### 事件结果结构

```csharp
public struct EventDispatcherResult
{
    public bool BeProcessed;   // 事件是否被至少一个监听器处理
    public bool ThisIgnore;    // 当前监听器声明自己"忽略"此事件
    public bool Terminated;    // 事件处理链被终止（后续监听器不再触发）
    public bool Failed;        // 处理失败

    public bool Success => !Failed && BeProcessed;
}
```

这个结构体让事件系统不只是"通知"，还能作为**查询**使用——发布者可以知道事件是否被处理、是否成功。

---

## 注册机制：优先级排序插入

注册监听器时，会按优先级排序插入列表：

```csharp
private void InsertFront(List<EventListenerInfo> listeners, EventListenerInfo listener)
{
    var index = -1;
    for (int i = 0, iTotal = listeners.Count; i < iTotal; i++)
        if (listeners[i].priority <= listener.priority)
        {
            index = i;
            break;
        }

    if (index == -1)
        listeners.Add(listener);
    else
        listeners.Insert(index, listener);
}
```

列表按优先级降序排列（高优先级在前）。`InsertFront` 是"至少与同优先级中最前面那个对齐"，`InsertBack` 是"放到同优先级中最后面"。

**为什么不在触发时排序？**

在事件触发时排序，每次触发都是 O(n log n)；在插入时排序，每次插入是 O(n)，但触发时遍历是 O(n) 且顺序已确定。对于"插入少、触发多"的事件系统，插入时排序更高效。

---

## 防止重复注册

```csharp
EventListenerInfo existEventListenerInfo = null;
var index = 0;
for (int iTotal = listeners.Count; index < iTotal; index++)
    if (listeners[index].listener == listener)
    {
        existEventListenerInfo = listeners[index];
        break;
    }

if (existEventListenerInfo != null)
{
    if (existEventListenerInfo.priority == priority)
        return;  // 完全相同，直接跳过

    // 优先级不同，先移除旧的，再添加新的
    existEventListenerInfo.invalid = true;
    listeners.RemoveAt(index);
}
```

同一个监听器（委托对象）只能注册一次。如果用新优先级重新注册，会先移除旧的再插入新的，保证排序正确。

---

## 触发机制：安全迭代的关键技巧

```csharp
public void FireEvent<T>(T evt)
{
    var type = typeof(T);
    EventsMap.TryGetValue(type, out var listeners);
    if (listeners?.Count > 0)
    {
        // ❗ 关键：先复制一份列表，避免触发过程中修改原列表
        using var tmpList = ListComponent<EventListenerInfo>.Create();
        tmpList.Clear();
        tmpList.AddRange(listeners);
        
        for (int i = 0, count = tmpList.Count; i < count; i++)
        {
            EventListenerInfo listenerInfo = tmpList[i];
            
            // 跳过已失效的监听器
            if (listenerInfo.invalid) continue;

            if (listenerInfo.listener is Action<T> listener)
            {
                try
                {
                    listener(evt);  // 调用监听器
                }
                catch (Exception e)
                {
                    Log.Error(e);  // 单个监听器异常不影响其他监听器
                }
            }
            else if (listenerInfo.listener is Action cb)
            {
                cb();
            }
        }
    }
}
```

**三个安全保障**：

1. **复制列表（`tmpList.AddRange(listeners)`）**：在触发过程中，可能有监听器注销或注册新监听器，这会修改 `listeners`。如果直接遍历 `listeners`，会导致迭代器失效。复制后遍历副本，原始列表的修改不影响当前遍历。

2. **`invalid` 检查**：即使某个监听器在复制后被注销，它会被标记为 `invalid`，触发时跳过，不会执行已注销的逻辑。

3. **try-catch 包裹每个监听器**：单个监听器抛异常，不会阻断后续监听器的执行。

---

## 带结果的事件触发

```csharp
public void FireEventWithResult<T>(T evt, ref EventDispatcherResult result)
{
    // ...
    for (int i = 0, count = tmpList.Count; i < count; i++)
    {
        var listenerInfo = tmpList[i];
        if (listenerInfo.invalid) continue;

        if (listenerInfo.listener is EventDispatcherParamDelegate<T> cbParam)
        {
            result.ThisIgnore = false;
            cbParam.Invoke(evt, ref result);  // 传入 result，监听器可以修改它
            
            if (!result.ThisIgnore) 
                result.BeProcessed = true;   // 标记"已被处理"
            
            if (result.Terminated) 
                break;                        // 监听器要求终止，不再通知后续
        }
    }
}
```

`EventDispatcherParamDelegate<T>` 是带结果的委托类型：

```csharp
public delegate void EventDispatcherParamDelegate<T>(T param, ref EventDispatcherResult result);
```

**实战场景：技能释放的拦截**

```csharp
// 场景：检查技能是否可以释放（可能被多个系统拦截）
var result = new EventDispatcherResult();
var evt = new SkillCastEvent { SkillId = 1001, Caster = hero };

dispatcher.FireEventWithResult(evt, ref result);

if (result.Success)
{
    ActuallyCastSkill(evt.SkillId);
}
else if (!result.BeProcessed)
{
    // 没有任何系统处理这个事件（异常情况）
    Log.Warning("技能释放事件未被处理");
}

// 监听器示例：沉默状态拦截
dispatcher.RegisterEventWithResult<SkillCastEvent>((evt, ref result) =>
{
    if (hero.HasBuff(BuffType.Silence))
    {
        result.Failed = true;
        result.Terminated = true;  // 沉默！直接终止，不通知后续
    }
});
```

---

## 三层事件分发架构

框架设计了三个层次的事件分发：

```
全局事件（EventDispatcherSystem.Instance）
    └─ 游戏级别的事件，如全局暂停、场景切换
    
实体事件（Entity.GetComponent<EventDispatcherComponent>()）
    └─ 挂载在 Entity 上，与 Entity 生命周期绑定
    └─ Entity 销毁时，Dispatcher 自动 Dispose，所有监听器清空
    
根场景事件（entity.RootDispatcher()）
    └─ 场景级别的事件，场景切换时自动清理
```

```csharp
// 全局事件
EventDispatcherSystem.Instance.FireEventGlobal(new GamePausedEvent());

// 实体事件
hero.GetComponent<EventDispatcherComponent>().FireEvent(new HeroDiedEvent());

// 根场景事件
someEntity.RootDispatcher()?.FireEvent(new SceneReadyEvent());
```

---

## 内存管理：ListComponent 对象池

```csharp
using var tmpList = ListComponent<EventListenerInfo>.Create();
```

`ListComponent<T>.Create()` 从对象池获取一个 `List<T>` 包装对象，`using` 结束后自动回收。

这避免了在每次事件触发时都 `new List<>`，是一个小但重要的 GC 优化——对于每帧可能触发几十次的事件，这个优化能显著减少 GC 压力。

---

## 常见使用模式

### 模式一：组件通信

```csharp
// 注册
var dispComp = entity.GetComponent<EventDispatcherComponent>();
dispComp.RegisterEvent<HpChangedEvent>(OnHpChanged);

void OnHpChanged(HpChangedEvent evt)
{
    healthBar.SetValue(evt.CurrentHp, evt.MaxHp);
}

// 注销（在 Destroy 中调用）
dispComp.UnRegisterEvent<HpChangedEvent>(OnHpChanged);

// 触发
dispComp.FireEvent(new HpChangedEvent { CurrentHp = 80, MaxHp = 100 });
```

### 模式二：优先级插队

```csharp
// 普通监听器（默认优先级 int.MinValue）
dispatcher.RegisterEvent<AttackEvent>(HandleAttack);

// 高优先级：格挡系统先处理
dispatcher.RegisterEvent(typeof(AttackEvent), HandleBlock, 
    priority: 1000);  // 比默认优先级高，先执行

// 最高优先级：无敌状态直接拦截
dispatcher.RegisterEvent(typeof(AttackEvent), HandleInvincible, 
    priority: int.MaxValue, bInsertFront: true);
```

---

## 总结

这套事件系统的设计亮点：

| 特性 | 实现方式 |
|------|---------|
| 优先级支持 | 插入时维护有序列表 |
| 安全迭代 | 触发时复制列表副本 |
| 软删除 | invalid 标记避免迭代器失效 |
| 带结果通知 | ref EventDispatcherResult |
| 异常隔离 | 每个监听器单独 try-catch |
| 内存优化 | ListComponent 对象池 |
| 生命周期绑定 | Component 随 Entity 自动 Dispose |

这个设计比简单的 `event` 关键字强大得多，是生产级游戏开发的常见方案。掌握这套系统，你就能在大型项目中写出松耦合、高内聚的游戏代码。
