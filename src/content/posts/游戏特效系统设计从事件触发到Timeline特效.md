---
title: 游戏特效系统设计：从事件触发到 Timeline 特效
published: 2026-03-31
description: 解析基于事件驱动的特效管理系统设计，包含 FxInfo 数据模型、资源预加载依赖、Unity Timeline 多目标挂载与角色材质控制器的协作机制。
tags: [Unity, 特效系统, Timeline, 游戏开发]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# 游戏特效系统设计：从事件触发到 Timeline 特效

## 前言

战斗中的每一次技能释放、每一次受击，都伴随着视觉特效。特效系统是"无声英雄"——它不直接影响游戏逻辑，却构成了玩家对游戏"爽感"的最直观感受。

本文通过分析 `ShowFxEvent` 和 `ShowUnityTimelineEvent`，带你理解游戏特效系统的事件驱动设计，以及 Unity Timeline 如何在战斗中批量附着到多个角色身上。

---

## 一、事件驱动的特效触发

```csharp
[Event(SceneType.Current)]
public class ShowFxEvent : EventWithRes<Evt_ShowFx>
{
    protected override void GetDependentRes(Scene scene, Evt_ShowFx evt,
        List<string> lstRes, List<string> lstOther)
    {
        base.GetDependentRes(scene, evt, lstRes, lstOther);
        if (evt.LoadRes)
            lstRes.Add(evt.FxInfo.path);  // 声明需要预加载的资源
    }

    protected override async ETTask Run(Scene scene, Evt_ShowFx a)
    {
        EffectSystem.Instance.StartEffect(a.FxInfo);
        await ETTask.CompletedTask;
    }
}
```

**`EventWithRes` 的设计：**

注意这里继承的是 `EventWithRes` 而不是普通的 `AEvent`——`WithRes` 表示"带资源的事件"。这个基类在执行事件前，会先收集 `GetDependentRes` 中声明的所有资源，确保它们已经加载完成后才调用 `Run`。

这是一个非常优雅的"声明式资源管理"：特效的触发代码不需要手动写资源加载逻辑，只需要在 `GetDependentRes` 里声明"我需要这个资源路径"，框架会处理其余的事。

**`LoadRes` 标志：**

```csharp
if (evt.LoadRes)
    lstRes.Add(evt.FxInfo.path);
```

`LoadRes = true`：需要框架帮我加载资源（首次触发时）
`LoadRes = false`：资源已经预加载过了，直接播放

这个区分避免了为已加载资源重复发起加载请求，提高了高频率触发时的效率。

---

## 二、特效的隐藏与打断

```csharp
[Event(SceneType.Current)]
public class HideFxEvent : AEvent<Evt_HideFx>
{
    protected override void Run(Scene scene, Evt_HideFx a)
    {
        if (a.FxInfo != null)
        {
            a.FxInfo.removed = true;  // 标记为移除，而不是立刻销毁
        }
    }
}

[Event(SceneType.Current)]
public class InterruptFxEvent : AEvent<Evt_InterruptFx>
{
    protected override void Run(Scene scene, Evt_InterruptFx a)
    {
        var goComponent = a.Unit.GetComponent<GameObjectComponent>();
        if (goComponent.GameObject != null)
        {
            // 打断角色材质控制器的 Timeline 动画
            goComponent.GameObject
                .GetComponentInChildren<CharMaterialController>()
                ?.InterruptCharacterTimeline();
        }
        EffectSystem.Instance.InterruptFx(a.Unit);
    }
}
```

**隐藏 vs 打断的区别：**

| 操作 | 处理方式 | 场景 |
|------|---------|------|
| `HideFx`（隐藏）| 标记 `removed = true`，让 EffectSystem 在下次更新时回收 | 正常结束，等待自然回收 |
| `InterruptFx`（打断）| 立刻调用 `InterruptCharacterTimeline()` 并通知 EffectSystem | 技能被打断，需要立刻停止所有关联特效 |

`removed = true` 而不是直接调用 `Destroy`，体现了对象池设计：特效对象归还池子，而不是销毁，为下次复用做准备。

---

## 三、Unity Timeline 特效：多目标挂载

`ShowUnityTimelineEvent` 处理需要附着到角色身上的 Timeline 特效——比如技能命中时的全身高光、受到暴击时的屏幕后处理效果。

```csharp
[Event(SceneType.Current)]
public class ShowUnityTimelineEvent : EventWithRes<Evt_PlayUnityTimeline>
{
    protected override async ETTask Run(Scene scene, Evt_PlayUnityTimeline a)
    {
        if (!a.IsCharacter)
        {
            // 非角色 Timeline：挂载到全局后处理（如全屏闪光）
            var gvc = GlobalVolumeController.Instance;
            var timeline = AssetCache.GetCachedAssetAutoLoad<TimelineAsset>(a.AssetPath);
            gvc.PlayTimeline(timeline);
        }
        else
        {
            // 角色 Timeline：根据 AttachType 决定挂到哪些角色
            using var units = ListComponent<Unit>.Create();
            TeamComponent teamSys = scene.GetComponent<TeamComponent>();

            switch (a.AttachType)
            {
                case eTimelineAttachType.OwnerUnit:
                    units.Add(a.Unit);  // 只挂到触发者
                    break;

                case eTimelineAttachType.AllCurMain:
                    // 挂到所有队伍的当前主角
                    foreach (var team in teamSys.GetAllTeam())
                        units.Add(team.GetCurMainMember());
                    break;

                case eTimelineAttachType.AllActive:
                    // 挂到所有当前在场的活跃角色
                    foreach (var team in teamSys.GetAllTeam())
                        foreach (var unit in team.TeamMember)
                            if (unit.GetComponent<GameObjectComponent>().IsLogicActive(true))
                                units.Add(unit);
                    break;

                case eTimelineAttachType.AllUnit:
                    // 挂到所有角色
                    foreach (var team in teamSys.GetAllTeam())
                        foreach (var unit in team.TeamMember)
                            units.Add(unit);
                    break;
            }

            // 对每个目标角色挂载特效
            foreach (var unit in units)
            {
                if (unit != null)
                {
                    var goComp = unit.GetComponent<GameObjectComponent>();

                    FxInfo fxInfo = new FxInfo
                    {
                        path   = a.AssetPath,
                        target = goComp.GameObject.transform,
                    };
                    EffectSystem.Instance.StartEffect(fxInfo);

                    var charMatController = goComp.GameObject.GetComponentInChildren<CharMaterialController>();
                    charMatController?.PlayEffectWithTimeline(fxInfo.go, fxInfo.path);
                }
            }
        }
    }
}
```

### 3.1 `eTimelineAttachType` 枚举的设计

| 类型 | 含义 | 使用场景 |
|------|------|---------|
| `OwnerUnit` | 只挂到触发者 | 施法者自身特效（发动攻击的高光） |
| `AllCurMain` | 所有队伍的当前主角 | 所有角色同时获得的 Buff 视觉 |
| `AllActive` | 所有在场活跃角色 | 全体受到某种状态效果 |
| `AllUnit` | 所有角色（包括未上场的）| 极少使用，通常是特殊演出 |

这种枚举设计让策划可以通过配置决定特效的作用范围，而不需要每次都让程序员写代码。

### 3.2 `using var units = ListComponent<Unit>.Create()`

`ListComponent<T>.Create()` 创建一个来自对象池的列表，配合 `using` 关键字，在代码块结束时自动归还池子。这是对象池的"RAII"用法（资源获取即初始化），确保临时列表被及时回收。

---

## 四、CharMaterialController：角色材质的 Timeline 控制

```csharp
var charMatController = goComp.GameObject.GetComponentInChildren<CharMaterialController>();
charMatController?.PlayEffectWithTimeline(fxInfo.go, fxInfo.path);
```

`CharMaterialController` 是角色材质控制器，负责角色身上所有的材质动态变化：
- **溶解效果**（入场/退场）：控制溶解 Shader 参数
- **描边特效**（选中/高亮）：启用/禁用描边 Pass
- **全身发光**（技能高潮）：增加 Emission 强度

`PlayEffectWithTimeline` 将一个 Timeline 绑定到这个材质控制器，Timeline 中的 Track 直接驱动 Shader 参数的动画曲线。这比手写 `Lerp` 代码更直观，也让美术可以直接在 Timeline 编辑器中调整特效的节奏。

---

## 五、全局后处理特效

```csharp
var gvc = GlobalVolumeController.Instance;
var timeline = AssetCache.GetCachedAssetAutoLoad<TimelineAsset>(a.AssetPath);
gvc.PlayTimeline(timeline);
```

不附着到任何角色的 Timeline，由 `GlobalVolumeController` 播放——这是 URP/HDRP 的 Volume 系统入口。非角色 Timeline 通常用于：

- **全屏色彩分级**：技能暴击时画面变暖色调
- **景深变化**：过场动画的焦距切换
- **Bloom 增强**：高光特效期间的泛光增强

---

## 六、特效生命周期

```
发布 Evt_ShowFx 事件
  → ShowFxEvent.GetDependentRes() 声明资源
  → 框架加载资源（若 LoadRes=true）
  → ShowFxEvent.Run() 调用 EffectSystem.StartEffect()
  → EffectSystem 从对象池取出特效对象，设置位置/旋转
  → 特效自然播放结束 → 回归对象池

发布 Evt_HideFx 事件
  → FxInfo.removed = true
  → EffectSystem 下一帧检测到 removed，提前回收

发布 Evt_InterruptFx 事件
  → CharMaterialController.InterruptCharacterTimeline() 立刻停止
  → EffectSystem.InterruptFx() 强制回收所有关联特效
```

---

## 七、总结

| 设计要素 | 解决的问题 |
|---------|-----------|
| `EventWithRes` | 自动资源加载，触发代码无需手写异步加载 |
| `removed = true` 标记 | 软删除，配合对象池安全回收 |
| `eTimelineAttachType` 枚举 | 策划配置特效作用范围，无需程序介入 |
| `CharMaterialController` | 角色材质的统一管理，Timeline 驱动 Shader |
| `ListComponent<T>.Create()` | RAII 对象池，临时列表自动回收 |

特效系统的核心思想是"解耦触发与实现"——触发者只关心"我需要这个特效"，特效系统负责资源、对象池、挂载等所有细节。这让技能设计者可以自由调用特效而不用担心性能问题。
