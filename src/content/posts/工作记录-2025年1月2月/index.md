---
title: 工作记录 2025年1月-2月
published: 2025-02-18
description: "2025年1月至2月工作记录：酒馆需求开发、Lua技术笔记、红点系统接入、GC优化与性能调优"
tags: [工作记录, Lua, Unity, 性能优化]
category: 工作记录
draft: false
---

## 概述

2025 年 1 月到 2 月主要围绕**酒馆（Barroom）需求**持续迭代开发，涉及协议接入、聊天 SDK、红点系统、GC 优化等方向。

---

## 1月工作

### 酒馆需求持续开发（1/2 - 1/23）

整个 1 月基本围绕酒馆需求推进，主要工作节点如下：

- **协议接入排查**：排查 proto 消息名不一致问题。`MG_Define` 中定义的 `req_name` 为 `romsg.CreateRoomReq`，但实际 proto message 名为 `CreateBarroomReq`，导致 encode 时报错 `romsg.CreateRoomReq does not exist`。根因是导出 pb.byte 时字段名未对齐，排查时需开启大小写匹配。

- **聊天页签初始化**：实现聊天左侧页签按配置初始化，页签初始化后根据配置显示，点击绑定各自独立的回调。

- **拖动功能**：推进拖动设置，要求尽快 Ace。

- **DAL 层开发**（1/13 - 1/14）：推进酒馆相关 DAL（Data Access Layer）模块。

- **功能自测梳理**（1/20）：整体梳理酒馆功能，准备自测。

- **红点、赠礼超链、麦克风 icon**（1/22）：完成红点接入、赠礼超链以及麦克风图标相关功能。

#### Lua 技术笔记：table.clear 与引用

工作中遇到 Lua 表引用的细节问题，记录如下：

> **Q：将一个表置为 nil 或执行 `table.clear`，会清空表里所有内容吗？**

`table.clear(self.m_kCurLoopListData)` 只会清空 `self.m_kCurLoopListData` 本身，**不会影响** `self.m_kData.member_list` 中的原始数据。

原因：
1. `self.m_kCurLoopListData` 中存储的是 `self.m_kData.member_list` 的引用（表指针），而非独立拷贝。
2. `table.clear` 清除的是引用本身，不操作引用指向的对象。
3. 但如果通过引用修改某个 `data` 的字段（如 `data.itemType`），由于是引用操作，原表数据会同步变化。

---

### 红点系统接入（1/23）

基于项目的红点框架完成酒馆模块红点接入，流程如下：

1. **配置表**：在红点配置表中新增条目，配置红点 ID 与层级关系。
2. **注册红点**：调用框架注册接口绑定红点 ID。
3. **UI 绑定**：在 UI 组件上绑定对应红点节点。
4. **管道刷新**：触发红点管道刷新，保证显示同步。
5. **事件触发**：通过事件派发器更新红点数值，示例：

```lua
LC_Event:DispatchEvent(
    LC_ModuleId.Common,
    LC_NotifyId.Common.RedDotValueSet,
    { Lua_RedDotModule.BarRoom.IsHaveApplyReq, nil, #res.requestList }
)
```

---

## 2月工作

### ECS Room 研究（2/6）

研究 ECS 架构在 Room（房间）模块中的应用，参考资料：  
[守望先锋 GDC：Gameplay Architecture and Netcode](https://www.lfzxb.top/ow-gdc-gameplay-architecture-and-netcode/)

---

### Bug 修复与状态同步（2/7 - 2/12）

- **状态修复**：修复酒馆模块若干状态 Bug。
- **架构反思**：梳理发现项目中**服务器数据与 UI 显示数据之间缺乏严格的中间层**，导致数据库数据与临时变量耦合，后续需要规范分层：
  - 服务器数据 → 中间数据层 → UI 显示数据
  - 数据库数据 与 临时变量 严格分离
- **麦克风状态同步**（2/12）：实现麦克风状态的跨玩家同步逻辑，联调左右两侧玩家数据。

---

### GC 优化（2/17 - 2/18）

针对酒馆模块进行 GC 优化，方向：

- **字段多状态复用**：将单一字段拆分为二进制位标志（bit flags），一个字段承载多种状态，减少对象分配。
- **Overdraw 监控**：关注 UI Overdraw 的变化量，评估优化前后的渲染开销。

---

### 3D 管线制作调研（2/7）

参与 3D 管线资源规范讨论，涉及：

- 美术产出规范：模型、动作资源标准
- 资源规格：模型面数约 1000 面，贴图规范待定
- 程序侧如何接入使用 3D 资源管线

---

## 小结

| 方向 | 主要内容 |
|------|---------|
| 功能开发 | 酒馆需求全流程开发（协议、聊天、拖动、赠礼、麦克风） |
| 系统接入 | 红点系统完整接入（配表、注册、UI绑定、事件触发） |
| 技术研究 | ECS Room 架构、守望先锋 Netcode 参考 |
| 问题修复 | 协议名对齐、麦克风状态同步、多状态 Bug 修复 |
| 性能优化 | GC 优化、Overdraw 监控、bit flags 状态压缩 |
| 架构思考 | 服务器数据与 UI 数据分层、数据库与临时变量解耦 |
