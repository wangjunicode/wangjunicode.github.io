---
title: 养成日程阶段系统设计——游戏内时间驱动的内容推进机制
published: 2026-03-31
description: 深入解析养成类游戏的日程阶段系统，用反射注册绑定、阶段切换上下文与资源预加载实现可扩展的内容推进
tags: [Unity, 养成系统, 状态机]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 养成日程阶段系统设计——游戏内时间驱动的内容推进机制

养成类游戏（Cultivation Game）有一个独特的设计挑战：游戏内容随"日程"推进，每一天/每个阶段都有不同的事件和互动。如何设计一套可扩展、易维护的日程阶段系统？

VGame项目的`CultivationComponentSystem`给出了一套优雅的解决方案：**基于反射的阶段绑定 + 可组合的阶段切换上下文**。

## 一、什么是养成日程系统

想象这样的游戏玩法：
- 玩家带着角色进行为期90天的养成训练
- 第1-10天是"初期训练阶段"，主要是刷好感度
- 第11-30天是"校园生活阶段"，解锁更多活动
- 第31天是"比赛日"，进行关键战斗
- 最后是"毕业结算"

每个阶段有不同的UI界面、可用活动、剧情触发……如果用if-else硬编码，代码会很快失控。

## 二、日程阶段的抽象基类

```csharp
/// <summary>
/// 养成日程阶段基类
/// </summary>
public abstract class CultivationScheduleStage : ICultivationScheduleStage
{
    public EScheduleStageType StageType { get; set; }
    public CultivationComponent Owner { get; set; }
    
    // 是否可重入（默认可重入，即同一阶段可以多次进入）
    public virtual bool IsReentrant => true;
    
    // 子类必须实现：告诉系统下一个阶段是什么
    public abstract EScheduleStageType GetNextScheduleStage();
    
    // 收集本阶段需要的资源列表（预加载用）
    public virtual void GatherResources(List<string> lstRes, List<string> lstOther) { }
    
    // 异步预加载额外资源
    public virtual async ETTask PreloadExtraResources()
    {
        await ETTask.CompletedTask;
    }
    
    // 阶段是否有内容要做（如果没有则自动跳过）
    public virtual bool HasAnythingToDo() => true;
    
    // 获取切换时的Loading界面配置
    public virtual LoadingConfig GetLoadingName(CultivationStageSwitchContext context)
    {
        return LoadingUtil.GetCultivateLoadingName(
            Owner.GetScriptID(), Owner.GetScheduleID(), 
            context.PrevStageType, context.NextStageType);
    }
    
    // === 阶段切换的生命周期方法（可重写） ===
    
    public virtual async ETTask<bool> Prepare(CultivationStageSwitchContext context)
    {
        await ETTask.CompletedTask;
        return true; // 返回false可取消切换
    }
    
    public virtual async ETTask ExitPreprocess(CultivationStageSwitchContext context)
    {
        await ETTask.CompletedTask;
    }
    
    public virtual async ETTask ExitPostprocess(CultivationStageSwitchContext context)
    {
        await ETTask.CompletedTask;
    }
    
    public virtual async ETTask EnterPreprocess(CultivationStageSwitchContext context)
    {
        await ETTask.CompletedTask;
        // 默认行为：进入新阶段时，释放所有前一阶段的剧情
        DisposeAllStory();
    }
    
    public virtual async ETTask EnterPostprocess(CultivationStageSwitchContext context)
    {
        await ETTask.CompletedTask;
    }
    
    protected void DisposeAllStory(EStoryDisposeMode disposeMode = EStoryDisposeMode.All)
    {
        EventSystem.Instance.Publish(Owner.ClientScene(), 
            new Evt_DisposeAllLogicStories { DisposeMode = disposeMode });
    }
}
```

这个抽象基类定义了阶段切换的完整生命周期：

```
前一阶段 ExitPreprocess → ExitPostprocess 
→ Loading界面显示
→ 预加载资源
→ 新阶段 EnterPreprocess → EnterPostprocess
```

每个方法都是可选重写（`virtual`，基类有默认空实现），子类只需要重写自己关心的方法。

## 三、反射自动注册阶段绑定

这是整个系统最精妙的设计：

```csharp
[FriendOf(typeof(CultivationComponent))]
public static partial class CultivationComponentSystem
{
    internal static void RegisterScheduleStageBindings(this CultivationComponent self)
    {
        if (self.StageBindings == null)
            self.StageBindings = new Dictionary<int, Type>();
        else
            self.StageBindings.Clear();
        
        // 遍历项目中所有类型
        foreach (var type in ReflectUtil.GetTypes())
        {
            // 筛选条件1：必须实现ICultivationScheduleStage接口，且是具体类
            if (type.IsInterface || type.IsAbstract || 
                !typeof(ICultivationScheduleStage).IsAssignableFrom(type))
                continue;
            
            // 筛选条件2：必须有[CultivationStageBinding]特性标注
            var attribute = type.GetAttribute<CultivationStageBindingAttribute>();
            if (attribute == null) continue;
            
            // 重复绑定检测
            var stageType = (int)attribute.StageType;
            if (self.StageBindings.TryGetValue(stageType, out var bindingType))
                Log.LogError("[Cultivation][Stage] 日程阶段 {0} 已绑定 {1}，将重新绑定 {2}", 
                    attribute.StageType, bindingType, type);
            
            self.StageBindings[stageType] = type;
        }
    }
    
    public class CultivationComponentAwakeSystem : AwakeSystem<CultivationComponent>
    {
        protected override void Awake(CultivationComponent self)
        {
            self.RegisterScheduleStageBindings(); // 初始化时自动收集所有阶段绑定
        }
    }
}
```

使用方式：策划新增一个"假期阶段"时，程序员只需要：

```csharp
// 新建一个类，加上特性标注
[CultivationStageBinding(EScheduleStageType.Holiday)]
public class HolidayScheduleStage : CultivationScheduleStage
{
    public override EScheduleStageType GetNextScheduleStage()
    {
        return EScheduleStageType.TrainingResume; // 假期后继续训练
    }
    
    public override async ETTask EnterPreprocess(CultivationStageSwitchContext context)
    {
        await base.EnterPreprocess(context);
        // 假期阶段特有逻辑：开放特殊活动
        Owner.UnlockHolidayActivities();
    }
}
```

**不需要修改任何现有代码**，系统会自动通过反射发现这个新类并注册。这是**开闭原则（OCP）**的完美体现：对扩展开放，对修改关闭。

## 四、日程数据的便捷查询

```csharp
public static partial class CultivationComponentSystem
{
    // 是否为第一个日程（用于首次进入的特殊逻辑）
    public static bool IsFirstSchedule(this CultivationComponent self)
    {
        var data = self.GetScheduleData();
        return self.GetScheduleID() == data?.StartScheduleID;
    }
    
    // 是否为最后一个比赛日程（触发最终赛前准备逻辑）
    public static bool IsLastMatchSchedule(this CultivationComponent self)
    {
        var data = self.GetScheduleData();
        return self.GetScheduleID() == data?.LastMatchScheduleID;
    }
    
    // 是否为最后一个日程（触发养成结束逻辑）
    public static bool IsLastSchedule(this CultivationComponent self)
    {
        var data = self.GetScheduleData();
        return self.GetScheduleID() == data?.EndScheduleID;
    }
    
    // 获取已经过的日程天数
    public static int GetScheduleDay(this CultivationComponent self)
    {
        var data = self.GetScheduleData();
        return data?.ScheduleDay ?? 0;
    }
    
    // 私有：获取日程数据（从脚本数据中取）
    private static CultivationScheduleData GetScheduleData(this CultivationComponent self)
    {
        var data = self.GetScriptData();
        return data?.ScheduleData;
    }
}
```

这些扩展方法让业务代码变得非常可读：

```csharp
// 在某个事件处理器里
if (cultivationComp.IsLastSchedule())
{
    // 触发养成结局剧情
    await TriggerEndingStory();
}
else if (cultivationComp.IsLastMatchSchedule())
{
    // 触发赛前动员剧情
    await TriggerPreFinalMatchStory();
}
```

## 五、阶段切换上下文（Context）的设计

```csharp
public class CultivationStageSwitchContext
{
    public EScheduleStageType PrevStageType { get; set; }
    public EScheduleStageType NextStageType { get; set; }
    // 可能还有其他上下文数据...
}
```

Context对象贯穿整个阶段切换的生命周期，每个生命周期方法都能访问：
- `PrevStageType`：从哪个阶段来的
- `NextStageType`：要去哪个阶段

**实际应用**：不同的"来源阶段"可能需要不同的Loading画面。比如从"训练阶段"切换到"比赛阶段"，显示"准备战斗！"；从"休息阶段"切换到"训练阶段"，显示"开始训练…"。

```csharp
public virtual LoadingConfig GetLoadingName(CultivationStageSwitchContext context)
{
    // 根据上下文中的来源和目标阶段，选择合适的Loading界面
    return LoadingUtil.GetCultivateLoadingName(
        Owner.GetScriptID(), Owner.GetScheduleID(),
        context.PrevStageType,  // 上一个阶段
        context.NextStageType   // 下一个阶段
    );
}
```

## 六、HasAnythingToDo：自动跳过空阶段

```csharp
public virtual bool HasAnythingToDo() => true;
```

某些阶段在特定条件下可能"没有内容"——比如"好感度剧情阶段"，如果角色好感度条件未达到，这个阶段没有剧情可播。

子类重写这个方法：

```csharp
[CultivationStageBinding(EScheduleStageType.RelationStory)]
public class RelationStoryScheduleStage : CultivationScheduleStage
{
    public override bool HasAnythingToDo()
    {
        // 检查是否有可触发的剧情
        return Owner.HasTriggableRelationStory();
    }
    
    public override EScheduleStageType GetNextScheduleStage()
    {
        return EScheduleStageType.DailyActivity; // 没有剧情时直接跳到日常活动
    }
}
```

系统在切换到这个阶段时，如果`HasAnythingToDo()`返回false，会自动调用`GetNextScheduleStage()`并切换到下一个阶段。玩家不会看到任何空白界面。

## 七、IsReentrant：可重入性控制

```csharp
public virtual bool IsReentrant => true;
```

`IsReentrant`控制阶段是否可以被重复进入：
- **可重入（true）**：玩家可以多次进入这个阶段（比如日常训练，每天都要重复）
- **不可重入（false）**：只能进入一次（比如"初次觉醒"剧情，看过就不能再看）

```csharp
[CultivationStageBinding(EScheduleStageType.FirstAwakening)]
public class FirstAwakeningStage : CultivationScheduleStage
{
    public override bool IsReentrant => false; // 觉醒剧情只能触发一次
    
    public override EScheduleStageType GetNextScheduleStage()
    {
        return EScheduleStageType.PostAwakening;
    }
}
```

## 八、资源预加载的设计

```csharp
public virtual void GatherResources(List<string> lstRes, List<string> lstOther)
{
    // 收集本阶段需要的资源路径
}

public virtual async ETTask PreloadExtraResources()
{
    await ETTask.CompletedTask;
}
```

阶段切换时，系统先调用`GatherResources`收集新阶段需要的资源列表，在Loading界面显示的同时，后台异步预加载这些资源。当Loading完成时，资源已经在内存里，新阶段的界面可以立刻打开。

## 九、总结

这套养成日程阶段系统的设计精华：

| 设计点 | 价值 |
|--------|------|
| 反射自动注册 | 新增阶段零改动现有代码 |
| 生命周期方法 | 进入/退出的逻辑清晰分层 |
| Context传递 | 切换双方的信息可在整个流程中访问 |
| HasAnythingToDo | 自动跳过无内容阶段，流程自愈 |
| IsReentrant | 精确控制重复进入行为 |
| 资源预加载 | Loading期间后台准备，无缝切换 |

对新手来说，这套系统最大的启发是：**`[Attribute]+反射`的模式可以彻底解决"需要手动注册"的问题**。每次新增一个实现类，系统自动发现，完全不需要维护任何注册表。这是可扩展性设计的最高境界之一。
