---
title: ECS房间架构与Overdraw优化实战
published: 2025-02-01
description: "ECS房间架构研究、Bug收敛、麦克风状态同步、GC优化、Overdraw分析、3D管线制作流程"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 02/06

### ECS Room 架构研究

研究 ECS 的 Room 模块实现。

参考资料：[Overwatch GDC - Gameplay Architecture and Netcode](https://www.lfzxb.top/ow-gdc-gameplay-architecture-and-netcode/)

---

## 02/07

### 数据分层架构思考

**问题**：没有严格的数据和显示处理中间层，导致状态修复困难。

**分层思路**：

- 服务器数据 ↔ UI 显示数据（需要中间转换层）
- 数据库数据 ↔ 临时变量（区分持久化与运行时数据）

---

## 02/12

### 麦克风状态同步调试

麦克风状态同步问题排查，涉及多玩家端同步。

---

## 02/17

### GC 优化

针对 GC 压力进行优化分析。

---

## 02/18

### 多状态字段设计

**问题**：怎么把一个字段变成多个状态去使用？

**方案**：拆成二进制形式（位掩码），用不同的 bit 位表示不同状态。

### Overdraw 分析

跟踪 Overdraw 变化量，评估优化效果。

---

## 专题：3D 管线制作流程

参考文档：
- [3D 管线制作 Wiki 1](https://huanle.feishu.cn/wiki/BBpmwZSA8iPOjkk2KWwciDqsnKA)
- [3D 管线制作 Wiki 2](https://huanle.feishu.cn/wiki/SaAuw6Y5Bi1VOUkLH3ycSccan2f)

**流程概览**：

- **美术产出**：模型、动作
- **资源规范**：模型面数约 1000，贴图标准（参见文档）
- **程序接入**：按规范导入并使用模型资源

---
