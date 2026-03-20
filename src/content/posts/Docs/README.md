---
title: VGame 项目技术文档中心
published: 2024-01-01
description: "VGame项目技术文档中心，覆盖框架底层、热更新、战斗系统、UI、网络等核心模块"
tags: [Unity, 游戏开发, 技术文档]
category: 技术文档
draft: false
---

# VGame 项目技术文档中心

> 本文档库由 AI 架构师基于项目完整脚本代码自动生成，面向刚入行的游戏开发毕业生，帮助其全面掌握本项目的技术架构与实现细节。

## 项目概述

本项目是一款基于 **ET框架（深度定制版）** + **帧同步战斗** + **热更新** 的手机 RPG 游戏，核心技术栈包括：

| 领域 | 技术方案 |
|------|---------|
| 框架底层 | ET ECS框架（VGame定制版） |
| 异步编程 | ETTask（类UniTask） |
| 热更新 | GCloud Dolphin + Addressables |
| 战斗同步 | 帧同步(FSP) + TrueSync定点数 |
| 技能系统 | UniScript可视化脚本 |
| UI框架 | YIUIFramework |
| 序列化 | MemoryPack |
| AI | 行为树(BehaviorTree) |
| 配置 | FlatBuffers/自定义cfg |
| 渲染 | URP + 自定义Shader |

---

## 文档目录

### 01_框架底层（10篇）
- ECS核心、Entity、EventSystem、ETTask、Singleton、ObjectPool、CoroutineLock、IdGenerator、Scene、序列化

### 02_热更新系统（10篇）
- 架构总览、Dolphin集成、Addressables、版本控制、补丁生成、HybridCLR、启动流程、分包策略、多平台、监控回滚

### 03_战斗系统（12篇）
- 整体架构、Unit实体、FSM、技能系统、Buff、UniScript、帧同步、物理碰撞、AI行为树、攻击判定、连击衔接、演出表现

### 04_游戏玩法系统（10篇）
- 玩法总览、角色队伍、任务、背包道具、社交、活动运营、商城经济、成就成长、地图场景、剧情对话

### 05_网络与SDK（10篇）
- 网络架构、消息协议、帧同步网络、断线重连、GCloud集成、MSDK登录、网络优化、WebSocket、CDN、安全反作弊

### 06_UI系统（10篇）
- YIUIFramework、面板生命周期、事件数据绑定、资源加载、PanelMgr、动画过渡、本地化、HUD战斗UI、弹窗引导、性能优化

### 07_工具与编辑器（10篇）
- 构建工具、资源分析、动画工具、Timeline、VFX编辑器、Addressables路径工具、代码生成、SVN工作流、调试工具、自动化CI

### 08_TA与渲染管线（10篇）
- URP渲染管线、角色Shader、特效系统、动态骨骼、动画系统Animancer、RootMotion、后处理、LOD优化、Shader预热、光照方案

### 09_配置与数据（8篇）
- 配置表系统、FlatBuffers、数据驱动设计、数值系统、客户端数据管理、PlayerPrefs策略、数据迁移、热配置更新

### 10_性能与优化（8篇）
- 性能分析工具、内存优化、CPU优化、GPU优化、对象池实践、资源加载优化、帧率稳定性、包体优化

---

## 阅读路线

**新人推荐学习顺序：**

1. 先读 `01_框架底层` 全部，理解ECS基础
2. 再读 `03_战斗系统` 前3篇（整体架构+Unit+FSM）
3. 然后 `02_热更新系统` 前3篇了解发布流程
4. 按兴趣方向深入其他模块

---

*文档持续更新中，当前状态见各目录下文件。*
