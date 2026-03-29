---
title: GVG战报系统与MVVM数据绑定实践
published: 2024-09-01
description: "2024年9月工作记录：GVG联赛需求、战报系统设计、公会联赛UI开发、MVVM数据绑定、场景切换重构"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 概述

9月核心工作是继续完成 GVG 公会联赛系统开发，包括战报 UI、数据绑定管道调试，以及场景切换流程重构的核心设计。

---

## GVG 公会联赛系统

### MVVM 数据绑定管道

- **bind_Property 大小写问题**：`ExportConfigs` 里的 `bind_Property` 字段名大小写必须与服务器字段名严格一致，否则绑定失败，数据管道逻辑跑不通。
- **战报 UI 开发**：实现战报展示 Panel，按历史场次列表显示比赛结果。
- **按需加载 vs 统一加载**（战报数据设计讨论）：
  - 统一加载：历史战绩和战报信息一次性拉取，减少二次请求，但数据量大。
  - 按需加载：点击战报按钮再请求，减小初次加载数据量。
  - 结论：战报信息量大时优先按需加载。

### LoopList 使用规范

```lua
-- 初始化顺序
loopList:setChildren()
loopList:setRender()
loopList:refresh()
-- 关闭时
loopList:clear()
```

### GM 快速新增方式

在 `gmconfig.json` 里新增一条记录即可，无需修改代码逻辑。

---

## 公会活动系统

- 服务器推送 `DAILY_ACTIVITY_TASK_INFO`，服务器条件模块读配置表，判断时间后下发协议给客户端。
- 客户端公会系统读取公会活动表，先按类型筛选出有哪些活动，再通过服务器下发的开启活动列表进行组合整合。
- 活动页签点击后，右侧为 `UI_Sys_Guild_ActivityBigWidgetCtrl`，具体 item 为 `UI_Sys_GuildActivityFrameWidgetCtrl`。

---

## 技能系统梳理（服务器侧）

### 普攻/技能协议流程

1. 客户端发 `PLAYER_LOCK_ENEMY` → 锁敌信息存在 Player 身上
2. 客户端发 `USE_SKILL_REQ`，携带 skillId、targetId、targetPos、faceAngle
3. 服务器收到后 `StartMainSkillSession`，返回 sessionId

```lua
skillParam.skillId = iSkillId
skillParam.targetId = iEnemyId
skillParam.targetPos.x = kTempselfPos.x
skillParam.targetPos.y = kTempselfPos.y
skillParam.targetPos.z = kTempselfPos.z
skillParam.face = faceAngle
NW_Helper.SendMessage(ProtobufNameMap.USE_SKILL_REQ, skillParam)
```

### 技能流程阶段（SkillStep）

| 阶段 | 说明 |
|------|------|
| Chant（吟唱） | 读条阶段，可被打断（视配置） |
| Magic（施法） | 效果阶段，执行技能蓝图时间轴 |
| End（结束） | 清理上下文，释放禁止状态 |

### AOE vs 锁敌技能

- 锁敌技能：客户端传目标单位 ID，服务器直接处理
- AOE 技能：客户端传释放位置，服务器找附近九宫格点位上的怪进行处理

### 打断规则

- `ForbiddenInterrupt(0)`：禁止打断
- `AllowInterrupt(1)`：允许任意时刻打断（吟唱阶段例外；同技能不互打）
- `DecideByInterruptPoint(2)`：由打断点决定

---

## 场景切换重构（设计阶段）

### 状态机设计原则

1. 状态明确，每个状态独立描述当前流程阶段
2. 状态转移通过特定事件或条件触发
3. 灵活处理异步操作（回调/协程）
4. 可扩展：随时新增状态

### 状态划分

| 状态 | 职责 |
|------|------|
| PreLoadingState | 显示 Loading UI，初始化进度条 |
| UnloadCurrentSceneState | 卸载旧场景，释放资源 |
| LoadingState | 异步加载新场景，更新进度条 |
| PostLoadingState | 场景加载完成后初始化（网络请求、玩家初始化） |
| CompleteState | 关闭 Loading UI，进入游戏 |

```lua
StateMachine:AddState("PreLoading", PreLoadingState)
StateMachine:AddState("UnloadCurrentScene", UnloadCurrentSceneState)
StateMachine:AddState("Loading", LoadingState)
StateMachine:AddState("PostLoading", PostLoadingState)
StateMachine:AddState("Complete", CompleteState)
StateMachine:SetState("PreLoading")
```

**注意**：`require` 一个 Lua 脚本不会执行 `ctor`，必须调用 `.New()` 才会创建实例。

---

## 聊天系统学习笔记

### 系统架构

- **服务器侧**：消息转发服务器（独立聊天服务器或集成于游戏服务器），负载均衡，Redis 缓存短期消息，SQL 数据库存历史。
- **客户端侧**：通常用 WebSocket/TCP 长连接保持低延迟；消息包含消息 ID、时间戳、发送者、接收者、频道字段。

### 关键技术点

- **心跳包**：定时发送检测连接状态，断线自动重连（TCP keep-alive 或应用层心跳）
- **消息队列**（Redis/Kafka）：缓解高峰期消息压力，保证有序处理
- **ACK 确认机制**：每条消息有唯一 ID，收到后发 ACK，超时服务器重发
- **频道权限管理**：世界频道、区域频道、公会频道分别管理权限和黑名单
- **安全**：SSL/TLS 加密 + 限流 + 敏感词过滤

---

## 渲染与资源知识

### AssetBundle 依赖管理

当 A 依赖 B 时，打包后需要先加载 B 的 Bundle，再加载 A：

```csharp
AssetBundle manifestBundle = AssetBundle.LoadFromFile(manifestPath);
AssetBundleManifest manifest = manifestBundle.LoadAsset<AssetBundleManifest>("AssetBundleManifest");
string[] dependencies = manifest.GetAllDependencies("A.bundle");
foreach (string dep in dependencies)
    AssetBundle.LoadFromFile(Path.Combine(bundleFolder, dep));
AssetBundle assetBundleA = AssetBundle.LoadFromFile(Path.Combine(bundleFolder, "A.bundle"));
```

### Android 录音权限处理

1. `AndroidManifest.xml` 中声明：`<uses-permission android:name="android.permission.RECORD_AUDIO" />`
2. 运行时动态请求（Android 6.0+）：

```csharp
if (!Permission.HasUserAuthorizedPermission(Permission.Microphone))
    Permission.RequestUserPermission(Permission.Microphone);
```

---

## 参考资料

- TCP 详解：[一篇文章搞清楚 TCP](http://www.mfbz.cn/a/51798.html)
- TCP 滑动窗口：[TCP 滑动窗口](https://fasionchan.com/network/tcp/sliding-window/)
- 文字渲染原理：[文字渲染](https://blog.csdn.net/qq_33064771/article/details/114260579)
- Shader 变体管理：[USparkle](https://blog.uwa4d.com/archives/USparkle_SVMP.html)
- 0GC 实现：[知乎](https://zhuanlan.zhihu.com/p/703322658)
