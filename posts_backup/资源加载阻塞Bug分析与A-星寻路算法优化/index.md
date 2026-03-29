---
title: 资源加载阻塞Bug分析与A*寻路算法优化
published: 2024-12-01
description: "2024年12月工作记录：酒馆功能开发、副本蓝图调试、资源加载 Bug 修复、A*寻路优化、服务器 RPC 架构梳理"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 概述

12月主要工作是酒馆功能（邀请、房间、权限）持续开发，同时完成公会联赛副本蓝图调试，深入梳理了服务器 RPC 架构（NetAPI），以及修复资源加载阻塞 Bug。

---

## 资源加载阻塞 Bug（12/10）

**现象**：资源加载没有反应，队列卡死。

**根因**：

```csharp
// asyncNum 无法重置：前面10个资源加载失败后 asyncNum 一直累加不回退
// 导致 asyncNum >= asyncMax，后续资源全部跳过
if (asyncNum >= asyncMax)
    return;
```

**修复思路**：
1. 检查资源是否正确生成 info 并添加到加载队列
2. 检查队列 tick 逻辑是否正常执行原始 Load 接口
3. 临时将 asyncMax 改大验证问题（如改为 100）
4. 根因：加载失败时 asyncNum 没有回退，需在失败路径上减少计数

---

## 副本蓝图调试（12/5 - 12/16）

### 蓝图热重载流程

```bash
1. 编译 dungeonblueprintProject
2. 执行 GM 指令 127 → 热重载蓝图
```

### 副本架构梳理

- **创建**：服务器在 `scene_mgr_module` 初始化时创建副本实例，同时创建导出蓝图的实例
- **蓝图职责**：蓝图 context 带 API，脚本作为事件处理器，策划编辑的是事件处理逻辑
- **副本调试 GM**：`DungeonGVEActionsTest("Shouting", 108)`、`DungeonGVEActionsTest("ShowkillStreakMsg", 1, 22, 3000)`

---

## 服务器 RPC 架构梳理（NetAPI）

### 游戏服务器 → 中台服务器（发送）

| 接口 | 用途 |
|------|------|
| `CallMsServerRpc<T>` | 向中台服务器发起 RPC 请求，返回泛型响应 |
| `HttpConvertRpc<T>` | HTTP 协议请求转 RPC 请求 |
| `BroadcastProcessMsg` | 向区域内所有中台服务器广播消息 |

### 中台服务器 → 游戏服务器（接收）

| 接口 | 用途 |
|------|------|
| `RegisterProcessMsg` | 注册接收回调（绑定 `OnProcessMsg`） |
| `OnProcessMsg` | 解析 `ProcessMsg`，交给 `ProcessMsgBase.ProcessMsgHandler` 处理 |

### RPC 注册机制

```csharp
// 自动注册（AutoRegisterRpc）：通过反射扫描 DLL 中带 [RpcHandler] 特性的类
// 手动注册（ManualRegisterRpc）：指定 entityType 和 DLL 路径
ms_initializers[entityType] = service.CreateMicroEntityInitializer(entityType, uint.MaxValue, entityOp);
ms_initializers[entityType].RegisterHandler(type, NetAPI.RpcMiddleWare);
```

---

## A* 寻路优化（12/20）

**问题**：目标点是不可行走的点时，A* 会遍历大量节点，引起性能问题。

**原因**：
- 目标不可达时搜索范围急剧扩大，直到遍历完整地图
- 启发式函数（曼哈顿距离）在目标不可达时无法准确指导搜索

**优化方案**：

```csharp
// 方案1：调用前提前检测目标点
if (!IsWalkable(targetPoint))
    targetPoint = FindNearestWalkablePoint(targetPoint); // BFS找最近可行走点

// 方案2：限制最大搜索深度，超出直接返回失败
// 方案3：导航网格或分层地图减少计算范围
```

---

## ToggleGroup 注意事项（12/20）

- `ToggleGroup` 会向组内所有 Toggle 广播值变化事件
- 注意避免循环触发：监听回调中不要再次修改 Toggle 状态

---

## 聊天系统 SDK 接入（12/4）

**chatRoomID 长度问题**：

`JoinChatRoom` 参数 `strChatRoomID` 限制 255 字节：
- ASCII 数字字符串在 UTF-8 下每字符 1 字节
- `"26030067209574809625"`（20 字符）= 20 字节，远低于 255 限制

---

## 文件占用报错（12/20）

```
System.IO.IOException: Sharing violation on path
```

原因：同一文件被多个进程同时写入。排查是否有多个 Unity 实例或编辑器工具同时占用同一资源文件。

---

## 调试技巧

### pb.decode 失败排查

1. 检查 pb 库是否正确加载
2. 检查对应 proto 的 bytes 是否已加载
3. 检查 msg_name 大小写是否与 proto 定义一致

### UI 点击无反应

- 检查是否有其他界面（透明度为 0 但未关闭）遮挡在上方
- 使用 `raycastall` 确认点击位置的 UI 层级

### 技能与受击调试 GM

```lua
-- 触发技能
LC_UnitManager:GetLocalPlayer().m_kSkillContext:UseServerSkill({
    skillID = 11000001, targetId = 10003789,
    targetPos = {x = 149.14, y = 0, z = 361.93}
})

-- 触发受击
NW_NetworkManager:GetInstance():GetGameServerHandler():ReceiveMessageHandler(31101, "SKILLHIT", {
    srcID = 261241905472339968, skillId = 110000,
    dsts = {{ damage = 40, dstID = 10003779 }}
})
```

---

## 参考资料

- [Newtonsoft.Json](https://www.newtonsoft.com/json)
- [Json 使用教程](https://blog.csdn.net/FransicZhang/article/details/87934022)
