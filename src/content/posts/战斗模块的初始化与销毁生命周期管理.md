---
title: 战斗模块的初始化与销毁生命周期管理
published: 2026-03-31
description: 解析 BattleModule 的初始化流程，包含 BattleContext 的统一建立、场景与 Loading 状态的联动、各功能子组件的有序创建，以及战斗退出时的资源清理。
tags: [Unity, 战斗系统, 生命周期, 系统架构]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗模块的初始化与销毁生命周期管理

## 前言

进入战斗是游戏中最复杂的状态转换之一：需要加载战斗场景、创建所有战斗相关组件、配置帧同步环境、初始化 UI……退出战斗时又需要按相反顺序逐一清理。

本文通过分析 `BattleModule`，带你理解一套完整的战斗生命周期管理方案，以及如何保证复杂初始化流程的有序性。

---

## 一、BattleContext：战斗上下文的建立

```csharp
[Event(SceneType.Client)]
public class BattleEnterEvent : AAsyncEvent<Evt_EnterBattle>
{
    protected override async ETTask Run(Scene scene, Evt_EnterBattle evt)
    {
        // 1. 创建并填充 BattleContext
        BattleContext context = await BattleContextBuilder.Build(evt, scene);

        // 2. 切换到战斗场景（会触发 Loading）
        await SceneController.SwitchToBattleScene(context);

        // 3. 初始化战斗模块
        await BattleModule.Init(context);

        // 4. 隐藏 Loading，战斗开始
        await UIController.HideLoading();
    }
}
```

**`BattleContext` 是什么？**

```csharp
public class BattleContext
{
    public int DungeonId         { get; set; }
    public EDungeonType Type     { get; set; }
    public List<DungeonTeamData> TeamDatas { get; set; }
    public int RandSeed          { get; set; }
    public int FrameRate         { get; set; }  // 战斗帧率
    public bool IsPVP            { get; set; }
    // ... 更多参数
}
```

`BattleContext` 是一次战斗所需的全部参数的容器，从匹配数据、服务端返回的对战信息中组装而来。

**为什么要抽象 BattleContext？**

如果各初始化步骤直接传递多个参数，函数签名会越来越臃肿（`InitBattle(dungeonId, type, teamDatas, seed, frameRate, isPVP...)`）。封装成 Context 对象：
- 签名稳定：新增参数不改方法签名
- 类型安全：不会传错位置
- 可序列化：便于战斗重放时还原初始状态

---

## 二、有序初始化的关键

```csharp
public static async ETTask Init(BattleContext context, Scene battleScene)
{
    // === 第一阶段：基础设施 ===
    battleScene.AddComponent<DungeonComponent>().Setup(context);        // 副本数据
    battleScene.AddComponent<TeamComponent>().Setup(context.TeamDatas);  // 队伍数据
    battleScene.AddComponent<RandSeedComponent>().Init(context.RandSeed); // 随机种子

    // === 第二阶段：视图层 ===
    await battleScene.AddComponent<BattleSceneViewComponent>().InitAsync(); // 加载场景 Prefab

    // === 第三阶段：战斗系统 ===
    battleScene.AddComponent<BattleScriptComponent>().Init(context);    // 帧同步核心
    battleScene.AddComponent<SkillSystemComponent>().Init();            // 技能系统
    battleScene.AddComponent<BattleStatisticComponent>().Init();        // 战斗统计

    // === 第四阶段：UI ===
    await battleScene.AddComponent<BattleHudComponent>().OpenAsync();   // HUD 界面

    // === 第五阶段：就绪通知 ===
    EventSystem.Publish(new Evt_BattleReady());
}
```

**初始化顺序的约束：**

| 阶段 | 依赖关系 |
|-----|---------|
| 基础设施 | 无依赖 |
| 视图层 | 依赖场景基础设施 |
| 战斗系统 | 依赖 `TeamComponent`（查队伍数据）|
| UI | 依赖战斗系统（显示技能按钮等）|
| 就绪通知 | 所有前序步骤完成后 |

---

## 三、战斗场景切换的 Loading 状态机联动

```csharp
// 进入战斗时
await UIController.ShowLoading(ELoadingType.BattleEnter, context.DungeonId);

// 场景加载完成（某个异步步骤中）
UIController.UpdateLoadingProgress(0.5f);

// 战斗完全初始化后
await UIController.HideLoading();
```

战斗加载的 Loading 进度分多阶段更新：
- 0%~30%：场景资源加载
- 30%~60%：角色模型加载
- 60%~90%：技能特效预加载
- 90%~100%：帧同步初始化

这种分段进度给玩家反馈"正在做什么"，比一条空的 Loading 条体验好得多。

---

## 四、战斗退出的反向清理

```csharp
public static async ETTask Dispose(Scene battleScene)
{
    // 1. 先停止战斗逻辑
    battleScene.GetComponent<BattleScriptComponent>()?.Stop();

    // 2. 关闭 HUD
    await battleScene.GetComponent<BattleHudComponent>()?.CloseAsync();

    // 3. 清理视图（特效、角色模型）
    await battleScene.GetComponent<BattleSceneViewComponent>()?.CleanupAsync();

    // 4. 释放战斗系统
    battleScene.GetComponent<SkillSystemComponent>()?.Dispose();

    // 5. 清除所有 ECS 组件
    battleScene.RemoveComponent<DungeonComponent>();
    battleScene.RemoveComponent<TeamComponent>();
    // ... 移除其他组件

    // 6. 卸载战斗场景资源
    SceneLoaderComponent.Instance.UnloadBattleScene();
}
```

**"先停逻辑，再清视图，最后释放数据"的原则：**

停止逻辑确保不会在清理过程中产生新的事件；关闭 UI 避免残留的 UI 引用悬空；清理视图释放 GameObject；最后才释放 ECS 数据，因为整个过程视图层可能还需要查询数据。

---

## 五、战斗组件的分组管理

`BattleModule` 将战斗相关组件分为几类：

### 5.1 逻辑组件

```
DungeonComponent    — 副本参数
TeamComponent       — 队伍管理
BattleScriptComponent — 帧同步主循环
SkillSystemComponent — 技能执行
BuffComponent        — Buff 管理
NumericComponent     — 数值计算
```

这些组件处理纯逻辑，不包含任何 Unity GameObject 引用。

### 5.2 视图组件

```
BattleSceneViewComponent  — 场景渲染
BattleHudComponent        — 战斗 HUD
BattleSettleComponent     — 结算界面
ChangeMatComponent        — 材质切换
```

这些组件持有或管理 Unity 对象，负责把逻辑状态渲染出来。

### 5.3 统计组件

```
BattleStatisticComponent  — 实时战斗统计
DataAnalysisComponent     — 数据上报
RecordSafeSaveSystem      — 录像保存
```

独立于战斗逻辑，只做观察和记录。

---

## 六、战斗场景 ID 的幂等性

```csharp
public static readonly int LoadingUniqueID = "BattleEnterLoading".GetHashCode();
```

战斗 Loading 有固定的唯一 ID（而非自增ID）。这保证了：

如果因为网络问题，战斗入口被触发两次（如按钮连点），第二次 `ShowLoading(LoadingUniqueID)` 会发现该 ID 的 Loading 已存在，直接返回，不创建第二个 Loading。

幂等性（Idempotence）——同一个操作执行多次与执行一次的效果相同——是游戏客户端健壮性的重要保证。

---

## 七、组件的有序 Remove

```csharp
// 移除顺序也有讲究
battleScene.RemoveComponent<SkillSystemComponent>();    // 先移除依赖方
battleScene.RemoveComponent<TeamComponent>();           // 再移除被依赖方
// 不按顺序移除可能在 Destroy 生命周期中引发空引用
```

`RemoveComponent` 会触发组件的 `Destroy` 生命周期。如果 `SkillSystem.Destroy` 中仍然引用 `TeamComponent`，那么必须先移除 SkillSystem，确保 Destroy 执行完毕后，再移除 TeamComponent。

---

## 八、总结

| 设计模式 | 实现 |
|---------|-----|
| Context 对象 | 封装所有战斗初始化参数 |
| 分阶段初始化 | 按依赖关系有序创建组件 |
| 反向清理 | 与初始化顺序相反地销毁组件 |
| 幂等 Loading | 固定 ID 防止重复创建 |
| 分组组件 | 逻辑/视图/统计三类职责分离 |

战斗生命周期管理是游戏客户端架构设计中最需要"全局观"的部分。每个组件、每个资源、每个 UI 面板都有其创建和销毁的时机，设计得好则流畅无感，设计得差则内存泄漏、空引用崩溃层出不穷。
