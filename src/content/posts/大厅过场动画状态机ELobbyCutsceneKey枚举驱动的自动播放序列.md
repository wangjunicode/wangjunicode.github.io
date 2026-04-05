---
title: 大厅过场动画状态机——ELobbyCutsceneKey枚举驱动的自动播放序列
published: 2026-03-31
description: 解析游戏大厅过场动画FSM的设计，包括枚举驱动的状态自动注册、预加载资源与角色交互事件的串联
tags: [Unity, 过场动画, 状态机]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 大厅过场动画状态机——ELobbyCutsceneKey枚举驱动的自动播放序列

游戏大厅里经常有这样的设计：玩家进入大厅后，角色会播放一段"入场动画"；点击某个角色，它会向玩家打招呼；进入日常活动后，场景氛围切换……这些过场动画（Cutscene）的播放顺序需要精确控制。

VGame项目的`LobbyCutsceneFSM`用枚举+状态机的设计，优雅地管理了大厅的所有过场动画序列。

## 一、枚举定义所有大厅动画状态

```csharp
public enum ELobbyCutsceneKey
{
    None = 0,
    QiHai_Intro,      // 绮海：入场介绍动画
    DailyLoop,        // 日常循环（玩家日常活动中）
    // ... 更多状态
    Max               // 枚举上界
}
```

**`None`和`Max`的用途**：
- `None = 0`：初始状态，还没有播放任何动画
- `Max`：枚举的最大值，用于循环遍历所有有效状态（`i < (int)ELobbyCutsceneKey.Max`）

## 二、枚举驱动的自动状态注册

```csharp
private async ETTask InitAsync()
{
    await PanelMgr.Inst.OpenPanelAsync("MapLoadingPanel"); // 显示Loading
    
    // 注册全局事件
    EventDispatcherSystem.Instance.RegisterEventGlobal<InteractEvent>(OnCharacterInteract);
    EventDispatcherSystem.Instance.RegisterEventGlobal<GEvt_SceneChangeFinish>(OnSceneChangeFinish);
    
    // 关键：通过枚举自动注册所有状态
    for (int i = (int)ELobbyCutsceneKey.None + 1; i < (int)ELobbyCutsceneKey.Max; i++)
    {
        ELobbyCutsceneKey key = (ELobbyCutsceneKey)i;
        var stateGoPath = key.ToString(); // 枚举名称 = GameObject路径
        
        // 在场景层级中找到对应的GameObject
        var stateGo = transform.Find(stateGoPath).gameObject;
        var cutsceneState = stateGo.GetComponent<LobbyCutsceneFSMState>();
        
        cutsceneState.OnInitialize(this, key); // 初始化状态，注入FSM引用
        StateMachine.Add(key, cutsceneState);  // 注册到状态机
    }
    
    // 预加载所有过场动画资源
    await this.PreLoadAllCutsceneRes();
    
    // 进入初始状态
    StateMachine.TrySetState(ELobbyCutsceneKey.QiHai_Intro);
    
    await PanelMgr.Inst.ClosePanelAsync("MapLoadingPanel"); // 关闭Loading
}
```

**最精妙的设计：`key.ToString() = GameObject路径`**

枚举名称（比如`QiHai_Intro`）直接对应场景中GameObject的名称。这意味着：
1. 新增一个动画状态时，在枚举里加一行，在场景里建一个同名GameObject
2. 系统在初始化时自动发现所有状态，不需要手动注册
3. 枚举值与场景结构保持强约束——如果场景里少了某个GameObject，会报错而不是静默失败

这是命名约定（Convention over Configuration）思想的体现。

## 三、角色交互事件的精确分发

```csharp
void OnCharacterInteract(InteractEvent evt)
{
    var evtCharacterAnimator = evt.characterAnimator;
    
    // 遍历所有状态，找到与被点击角色对应的状态
    foreach (var fsmState in StateMachine.Values)
    {
        var characterAnimator = fsmState.GetCharacterAnimator();
        
        // 只处理：持有该角色动画器、有事件名称、有过场动画的状态
        if (characterAnimator == evtCharacterAnimator 
            && fsmState.EventName != null 
            && fsmState.GetCutscene() != null)
        {
            fsmState.OnCharacterInteract(); // 触发该角色的交互过场动画
        }
    }
}
```

玩家点击某个角色（`InteractEvent`），系统通过`characterAnimator`识别是哪个角色，然后找到对应的状态并触发。

**为什么遍历所有状态而不是直接映射？**

一个角色在不同的日程阶段可能对应不同的状态（比如绮海在"日常"状态的反应和在"特别活动"状态的反应不同）。遍历确保找到当前活跃的状态。

## 四、大厅↔日常的切换接口

```csharp
// 从大厅切换到日常活动状态
public void PlayLobbyToDaily()
{
    StateMachine.TrySetState(ELobbyCutsceneKey.DailyLoop);
}

// 从日常活动返回大厅（重播入场动画）
public void PlayDailyToLobby()
{
    PlayFromStart(); // 等同于重新播放入场动画
}

// 重置到初始状态
public void PlayFromStart()
{
    StateMachine.TrySetState(ELobbyCutsceneKey.QiHai_Intro);
}
```

这三个公开接口对应UI层的三种触发场景：
1. 玩家点击"开始日常活动" → `PlayLobbyToDaily()`
2. 日常活动结束返回大厅 → `PlayDailyToLobby()`
3. 某些情况需要重播欢迎动画 → `PlayFromStart()`

**`TrySetState`（尝试切换）vs 强制切换**：

使用`Try`前缀的版本，如果目标状态不允许切换（比如当前状态正在播放不可中断的动画），会返回false而不是强制切换，保证动画的完整性。

## 五、CutsceneCache的资源管理

```csharp
public async ETTask PreLoadAllCutsceneRes()
{
    // 遍历所有状态，预加载过场动画资源
    foreach (var fsmState in StateMachine.Values)
    {
        await fsmState.PreloadResAsync();
    }
}
```

初始化时预加载所有过场动画的资源（动画数据、特效资源），避免在切换状态时临时加载导致的卡顿。这与之前分析的"战前备战资源预加载"是相同的思路。

## 六、EnableCutscene与EnableScene的分离

```csharp
public void EnableCutscene(bool enable)
{
    if (_cutscene.gameObject.activeSelf == enable) return;
    _cutscene.gameObject.Active(enable);
    EnableScene(enable); // 同时控制场景显示
}

void OnSceneChangeFinish(GEvt_SceneChangeFinish evt)
{
    EnableScene(true); // 场景切换完成后重新开启场景
    // UICameraMgr.Instance.ReloadMainCamera(_cutscene.camera); 注释掉的旧逻辑
}
```

`EnableCutscene`是高层接口，控制整个"大厅场景+过场动画"的显示；`EnableScene`控制场景背景是否渲染；`_cutscene`对象控制过场动画的Slate Cutscene组件。

场景切换完成事件（`GEvt_SceneChangeFinish`）触发时重启场景显示——切换过程中可能暂时禁用了场景渲染，切换完成后重新开启。

## 七、Slate过场动画框架的集成

从import的命名空间可以看到：
```csharp
using Slate;
using Slate.ActionClips;
```

项目使用Slate过场动画框架（Unity Asset Store上的商业插件）。Slate提供类似Unity Timeline的过场动画编辑能力，但有更多针对游戏的特性（如角色姿势、镜头控制）。

`LobbyCutsceneFSMState`的`GetCutscene()`返回Slate的Cutscene对象，状态切换时播放对应的Slate过场动画。

## 八、总结

大厅过场动画FSM的设计亮点：

1. **枚举即路径**：枚举名称直接对应场景GameObject名称，约定减少配置
2. **自动注册**：遍历枚举自动发现所有状态，不需要手动维护注册表
3. **事件分发**：通过CharacterAnimator识别交互目标，精确触发对应动画
4. **预加载**：进入大厅时预加载所有过场资源，运行时无卡顿
5. **TrySetState**：安全的状态切换，不打断不可中断的动画

对新手来说，"枚举名称=GameObject路径"的约定设计是一个很有启发性的工程技巧——用代码约定来替代繁琐的配置，既提高了开发效率，又建立了易于理解的规范。
