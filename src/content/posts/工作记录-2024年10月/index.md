---
title: 工作记录 2024年10月
published: 2024-10-01
description: "2024年10月工作记录：场景切换状态机重构完成、GVG需求评估、新手引导系统、Perforce 配置、技能流程服务器代码梳理"
tags: [工作记录]
category: 工作记录
draft: false
---

## 概述

10月完成了场景切换状态机重构，同时深入研究了技能流程服务器代码（`Battle_SessionComponent`）、新手引导系统架构，并了解了 SDK 接入、安卓权限、URP 自定义渲染等知识点。

---

## 场景切换状态机重构（完成）

### 重构目标

将原来耦合严重的 `LC_SceneManager` 重构为基于状态机 + Transition 的分层架构：
- 每个状态自己有 handler/action，**不再回调 SceneManager**
- 中间加一层 Transition 定义状态切换顺序
- 通过 `LC_SceneTransitionContext` 传递上下文数据

### 架构层次

```
LC_SceneManager
  └─ ShowScene() → 选择 Transition 类型
       ├─ LC_Transition_Normal（普通场景切换）
       ├─ LC_Transition_Login（登录场景）
       └─ LC_Transition_Plane（位面/副本）
            └─ LC_SceneStateMachine（状态机）
                 ├─ PreLoading → UnloadCurScene → LoadNewScene
                 └─ PostLoading → WaitForPlayerInfo → Completed
```

### 核心类

**LC_SceneStateMachine**
- `AddState(name, stateObj)`：注册状态
- `ChangeState(name, transition)`：切换状态（调用 Exit/Enter）
- `MoveNextState()`：根据 Transition 配置的 transitions 表跳到下一个状态
- `Update()`：每帧 tick 当前状态

**LC_TransitionBase**
- `Init(lastSceneInfo, sceneInfo, context)`：初始化上下文
- `AddTransition(from, to)`：注册状态流转关系
- `UnloadCurScene()`：释放旧场景（脚本/LuaComponent/资源/Unit）
- `LoadNewSceneAsync(callback)`：异步加载新 Unity 场景
- `CreateSceneLogicInstance(callback)`：加载 luacomponent.prefab，创建场景 Lua 逻辑实例

**状态流转（Normal Transition）**
```
PreLoading → UnloadCurScene → LoadNewScene → PostLoading → WaitForPlayerInfo → Completed
```

---

## 技能流程服务器代码梳理（Battle_SessionComponent）

### 核心字段

- `m_kNowSessionSkillCtx`：当前主技能上下文（互斥，同时只有一个）
- `m_hExtraSessionSkillCtx`：额外技能集合（可同时多个）

### 技能阶段

| 阶段 | 说明 |
|------|------|
| Chant | 吟唱读条阶段，超时自动进入 Magic |
| Magic | 效果阶段，执行蓝图时间轴 |
| End | 结束，清理禁止状态和上下文 |

### 打断规则

```csharp
// ForbiddenInterrupt(0)：禁止打断
// AllowInterrupt(1)：吟唱阶段不可被打断，施法阶段可被打断（相同技能不互打）
// DecideByInterruptPoint(2)：由打断点决定
```

### 时间轴驱动

`_updateTimeline` 每帧遍历时间轴节点，按 `expireTime = startTime + chantMs + triggerTime / timeRatio` 触发对应蓝图节点。

---

## 新手引导系统

### 设计思路

- `LC_GuideManager` 管理所有引导数据：等待引导列表、可执行引导列表、正在运行引导列表
- 事件驱动：通过 `LC_Event` 订阅各种触发事件（打开 UI、关闭 UI、点击控件等）
- 引导分类：
  - `Once`：只触发一次
  - `repeated`：可重复触发
  - `DayOnce`：每天触发一次

### 核心流程

1. `_onInitGuideConfigs()`：启动时加载所有待触发引导配置
2. 事件触发 → `_onTryAddGuide()` → 条件检查 → 加入 `m_kWaitingStepGuideDataList`
3. UI 打开时 → `_onTriggerGuide()` → 匹配引导步骤 → 加入 `m_kRunGuide`
4. 打开 `UI_Sys_GuidePanel`，展示引导遮罩和高亮区域
5. 完成 → `_onFinishRunStepGuide()` → 进入下一步或结束

### GuideMaskRaycastFilter（C# 侧）

```csharp
// 透明遮罩：控制哪个区域可以点击穿透
public void InitGuideView(RectTransform rt, float offsetW, float offsetH, float radius, bool useCircle)
{
    m_kMaskMaterial.SetFloat("_Silder", baseR / 2.0f + radius);
    m_kMaskMaterial.SetFloat("_SliderX", (rectWidth + offsetW) / 2.0f);
    m_kMaskMaterial.SetFloat("_SliderY", (rectHeight + offsetH) / 2.0f);
    if (useCircle)
        m_kMaskMaterial.EnableKeyword("USE_CIRCLE_MASK");
}
```

---

## GVG 需求评估

- 3场比赛，按段位分组，每组最多8人，保证3场比赛能排出1-8名次
- 服务器 GM 模块：`MG_Common.GmOpEnum` 枚举了所有已定义 GM 指令

---

## Perforce 配置

- **allwrite**：开启文件读写权限
- **clobber**：不在 pending 里的文件更新后可覆盖

---

## 渲染与 URP

### 自定义 ScriptableRenderFeature

实现了 `LightDepthTextureRenderFeature`，用于在编辑器中渲染场景深度纹理（地面 Ground 层 + 场景 MeshRenderer），支持 AlphaCut 材质替换：

- `FilteringSettings` 按 Layer 筛选地面渲染
- 遍历 `FindObjectsOfType<MeshRenderer>()` 处理带 AlphaCut 的材质
- 仅支持编辑器模式（运行时直接报错返回）

### NPOT 纹理导入

- 默认：`ToNearest`（缩放到最近 2 的幂）
- 保持原始清晰度：改为 `None`
- UI/HUD 不需要 Mipmap；地面墙面等远近变化的物体需要开启

### UGUI Overlay 渲染

- Canvas 的 `Overlay` 模式独立于 3D 场景，不受摄像机影响
- `UGUI.Rendering.RenderOverlays` 在 Frame Debugger 中可分析 UI 渲染开销
- 一次 `RenderOverlays` 包含：清除 Stencil Buffer + `Canvas.RenderOverlays` (DrawMesh)

---

## 参考资料

- IL2CPP：[IL2CPP All In One](https://www.lfzxb.top/il2cpp-all-in-one/)
- 渲染：[渲染篇](https://zhuanlan.zhihu.com/p/40900056)
- AssetBundle：[msxh 博客](https://www.cnblogs.com/msxh/p/8506274.html)
- 场景切换管理：[bchobby](https://bchobby.github.io/posts/6429cd5373b204af0f5ccab4c1eed0f5/)
- 安卓录音权限：[51cto](https://blog.51cto.com/u_16213309/7845063)
