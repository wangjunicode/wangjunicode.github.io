---
title: 工作记录 2024年3月
published: 2024-03-01
description: "新入职第一个月，熟悉项目环境和技术栈，完成GVE玩法炮台轮盘交互需求、Timeline过场动画需求、资源加载流程优化"
tags: [工作记录]
category: 工作记录
draft: false
---

## 03/04 新入职环境搭建

入职第一天，熟悉项目流程：

- **P4V（Perforce）**：项目版本控制工具，分支选 `RoPrimeval/Trunk`
- **DACS（DCubeSetup）**：安全沙箱技术，内部文件共享通过剪切板 Alt+V 操作
- **Unity 工程**：第一次打开可直接切换平台为安卓
- **IDEA + EmmyLua**：Lua 开发环境配置
- **TAPD**：项目管理工具

## 03/05 项目代码阅读

### 沙箱技术
DACS 是双桌面沙箱方案，在员工电脑上提供虚拟化的隔离工作空间，保护公司数据安全。需要访问内部文件的软件要先拖到沙箱中再运行。

### 工程目录结构
```
Dependency（第三方库）
├── Audio - Fmod
├── Camera
├── Component - Collider, Move
├── Event
├── Input - EasyTouch
├── Lua - xLua
├── Network - KCP
└── PathFinding - 寻路
```

### 入口代码
- `GameMain.cs` — 游戏主入口
- `LA_LuaComponent` — Lua 组件初始化
- `CoroutineManager` — 协程管理器

## 03/06 UI 流程学习

### UI 架构
- `Lua_UIViewBase/SetOwner` — 设置 UIContainer
- Timeline 学习：[Unity Timeline 概述](https://zhuanlan.zhihu.com/p/99999493)

## 03/07 Lua 框架与服务器

### Lua 面向对象设计
通过元表（metatable）实现面向对象，通过懒加载的方式访问 widget 和控件。

### 个人服务器启动
```
O:\RoMeta_Program_YDPC024-RO-JW_6155\Server\exe
stop.bat -> run_AllServer
```

### Lua 热重载调研
- [xlua reload 方案](https://zhuanlan.zhihu.com/p/139548726)
- Timeline 相关：自定义 Clip 需要继承 `PlayableBehaviour`（处理逻辑）和 `PlayableAsset`（存放数据）

### P4V 工作流
修改文件前先 Checkout 到修改列表，更新完有报错时按 F11 重新编译。

## 03/08 事件系统与轮盘需求

### 事件注册模式
```lua
function UI_Sys_MainPanelCtrl:_registerEvents()
    LC_Event:RegisterEvent(LC_ModuleId.Common, LC_NotifyId.Common.UpdateCannonNotify, self._changeSkillType, self)
end

function UI_Sys_MainPanelCtrl:_unRegisterEvents()
    LC_Event:UnregisterEvent(LC_ModuleId.Common, LC_NotifyId.Common.UpdateCannonNotify, self._changeSkillType, self)
end

function UI_Sys_MainPanelCtrl:_changeSkillType(skillType)
    if self.m_kJoyStickSkillWidget then
        Lua_UT_Helper.SetActive(self.m_kJoyStickSkillWidget.gameObject, false)
    end
end
```

### 资源路径说明
- PB 导出配置：`Client_Editor/Assets/Editor/Resources/ArtRes/Bundle/Bytes/proto.pb.bytes`
- PB 源文件：`tools/protocol`

### Lua 热重载实现原理
```csharp
#if UNITY_EDITOR
    LuaFileWatcher.CreateLuaFileWatcher(LA_LuaManager.Instance.GetLuaGlobalEnv());
#endif
```
C# 侧：通过 `FileSystemWatcher` 监听 `.lua` 文件变更，触发 `EditorApplication.update` 回调，调用 `luaEnv.DoString` 重新加载。

Lua 侧初始化：
```lua
function Init(testScence)
    local f = function()
        require "gamemain"
        _G.RoFix = require "luahotupdate"
        _G.RoFix.Init("hotupdatelist", {})
    end
end
```

## 03/11 GVE 玩法炮台需求

### 交互条件系统
- 新增 `LC_ConditionDefine`、`LC_InteractCondition`
- 协议事件 ID：`UpdateCannonNotify = 2701`
- `NW_GameServerHandler` — 协议统一处理位置，可断点调试各协议

### 文件提交清单
- `LC_Common_NotifyId`
- `LC_DunGeon_GVE`
- `UI_Sys_MainPanelCtrl`
- `UI_Sys_GVE_DownWidgetView`
- `NW_GameServerHandler`（注册协议回调）
- `UI_Sys_GVE_DownWidgetCtrl`

### 调试技巧
NPC ID（未完成炮台）：`23000004`，配置文件：`NPCConfig@Monster.xlsx`

## 03/12 Lua 热重载 + Timeline 研究

### Lua 热重载 FileSystemWatcher 实现
```csharp
using System.IO;
namespace LuaTool
{
    public class DirectoryWatcher
    {
        public DirectoryWatcher(string dirPath, FileSystemEventHandler handler)
        {
            CreateWatch(dirPath, handler);
        }

        void CreateWatch(string dirPath, FileSystemEventHandler handler)
        {
            if (!Directory.Exists(dirPath)) return;
            var watcher = new FileSystemWatcher();
            watcher.IncludeSubdirectories = true;
            watcher.Path = dirPath;
            watcher.Filter = "*.lua";
            watcher.Changed += handler;
            watcher.EnableRaisingEvents = true;
            watcher.InternalBufferSize = 10240;
        }
    }
}
```

### Timeline 工作流
- 时间轴资源保存到项目，时间轴实例保存到场景
- 项目动画工作流：UI 动画用自定义 UIAnimator + 部分 Spine；场景动画用 Spine 或 Timeline
- 整个 Panel 挂载 `UIAnimationCommonTrigger`、`UIAnimatorAlpha`

### 技能系统架构
- 技能发起流程：检查技能时间 → 处理用户输入 → 技能筛选器（目标是否满足条件）→ 是否在施法范围内 → 选择目标数据 → 发送服务器
- Buffer 逻辑：新增或移除 buff 后，调用 `RefreshRender` 处理数据
- `skill_runtimeContext`：主技能上下文（唯一）
- `perform_timeline_agent`：副技能（可多个），技能是多时间轴的

### 交互检测机制
场景里每个单位（Unit）在 tick 逻辑里通过数格子检测是否产生交互，再根据 `NPCInteractConfig.xlsx` 里的条件配置执行逻辑。

### Lua 运算符备注
`and` 运算符：A 为 true 返回 B，A 为 false 返回 A。

## 03/13 交互条件系统完成

### 条件系统设计
- `ConditongConfig`：条件类型定义表
- `NPCInteractConfig`：NPC 交互表
- 策划配置交互 ID 和检查条件，Lua 配置读取这些配置执行逻辑（配置 func 和参数）

### Lua Formatter 工具
- `LuaFormatter / Stanzilla`（vscode-luaformatter）可用

### 交互检查流程
交互 Manager 里 tick 检查，每帧检查场景所有 unit，距离靠近后检查交互条件，满足条件后刷新交互表现层。

## 03/14 Timeline 加载调试

Timeline 加载流程跑通（使用 `AssetDatabase.Load` 原始接口）。

### 关卡编辑器 API
关卡编辑器是纯后台逻辑实现，响应后台协议来触发客户端 API，在 `GVE_Actions` 里提供接口响应后台操作（如隐藏所有 UI 一定时间）。

## 03/15 资源加载流程

### 项目资源加载机制
- 需要打包的文件放在 `Resources/ArtRes` 下，F11 生成 `ResManifest` 文件
- 加载接口：
  - `LoadUObjectToID` + `GetIDObject`：先拿 ID，再获取对象
  - `LoadUObjectAsync`：一步到位

## 03/16 UI 制作工作流

### 创建 UI 界面流程
1. 用 tool 里 UI 工具创建 prefab
2. 点击 Code Generate 生成 MVC 脚本
3. 生成物：prefab + MVC 脚本 + uiprefabconfig 配置

### Camera 知识
- **Culling Mask**：相机针对不同层级物体进行渲染的操作
- **Cinemachine**：Unity 2017 推出的摄像机控制模块，结合 Timeline 实现过场动画

### VS 调试 Unity 卡死问题
**解决方案**：
1. 删除所有断点
2. 删除 `.vs` 文件夹，重新生成 sln
3. 重新 External Tool 生成后重启

## 03/17 Cinemachine 学习

Cinemachine 插件解决了摄像机间复杂控制、混合、切换等问题，能结合 Timeline 实现动画效果。支持人物对话镜头、移动跟随等多种游戏场景。

参考：[Cinemachine 介绍](https://zhuanlan.zhihu.com/p/516625841)

## 03/18 Timeline 导出/导入问题排查

### Unity 异步加载说明
加载仍然是 Unity 的硬伤：LoadAsync 异步只是硬盘读内存阶段异步，**Instantiate（实例化）才是消耗大户**，且无法真正异步执行。粒子系统的内置 Awake/Start 是主要耗时来源。

### Timeline Export 问题根因
Timeline 导入后无法导出的原因：**保存需要 prefab 引用**，直接 Load 实例化的对象没有 prefab 引用，所以无法导出保存。

### GM 系统
可查看项目 GM 系统设计，了解调试工具的设计思路。

## 03/19 资源加载系统深度分析

### 资源加载系统架构

```
ResourceManager
├── GetAssetLoadType()  → 根据文件扩展名决定加载类型
├── AsyncLoadAsset()    → 异步加载入口
└── Tick()              → 处理加载队列（分帧处理，同时处理10个）

ResourceLoader
└── LoadAsync()         → 最终执行加载（走 Resources.LoadAsync）

ResourceManifestSlot
└── GetLoadTypeByPath() → 从 ResManifest 获取资源路径类型
```

### 支持 Timeline（.playable）资源加载的修改点

**需要修改的文件：**
1. `LoadType`：新增枚举 `Playable`
2. `ResourceManager.GetAssetLoadType()`：新增对 `.playable` 扩展名的支持
3. `ResourceLoader.LoadAsync()`：新增 Playable 类型处理，使用 `Resources.LoadAsync<UnityEngine.Object>(pathNoExt)`
4. `EditorConst`：新增 Timeline 文件夹收集 AB 策略路径

## 03/20 资源加载流程收尾

### 异步加载实现
项目通过协程异步加载，同时只处理 10 个加载请求，入口：`Lua_UIPanelManager.AllocAsyncToID`。

### 相关概念
- **引用/指针/句柄区别**：[详细解析](https://zhuanlan.zhihu.com/p/627914974)
- **Unity fileID vs GUID**：[说明](https://zhuanlan.zhihu.com/p/654506392)

## 03/21 Timeline 需求提交

### 本次 Timeline 支持修改汇总
- `LoadType` 新增枚举 `Playable`
- `ResourceManager.GetAssetLoadType()` 新增 `.playable` 支持
- `ResourceLoader.LoadAsync()` 新增 Playable 类型处理
- `EditorConst` 新增 Timeline 文件夹收集资源列表

### Timeline Signal 信号系统
Timeline 可通过 Signal 信号系统触发游戏事件，参考：[Unity Timeline Signal Demo](https://blog.csdn.net/js0907/article/details/108480085)

### Lua 语法备注
Lua 冒号定义函数相当于第一个参数传入 `self`，点号调用需手动传 `self`。

## 03/22 技能系统文档阅读

### 技能生产流程
```
原画 → 模型（模型/材质/贴图）→ 动作（状态机配置/prefab）
→ 特效 → 触发器策划（技能触发器拼装）→ 触发器服务器（数值/功能实现）
→ 需求（表格配置/技能时间轴编辑/触发器参数配置）
→ 数值 → 服务器 → 客户端（技能表现编辑器）
```

### 技能范围类型
- 圆形
- 扇形  
- 矩形

### 技能目标系统
施法逻辑开始时包含"施法目标"（单位）和"施法目标点"（坐标）两个信息。

## 03/23 Timeline 过场设计研究

### 过场动画（Cutscene）设计
参考：[Unity 过场工具设计](https://zhuanlan.zhihu.com/p/599281690)

**过场内容类型：**
- **简单类型**：播完销毁，纯表现，无游戏逻辑关联
- **复杂类型**：播放时需与游戏逻辑和资源深度关联，需动态绑定（如 MMO 类使用游戏中实时角色/外观/道具）

**原神过场实现方式**：时间轴资源与时间轴实例分开保存，动态加载。

## 03/24 炮弹数量 UI 显示

### 新增 NPC Unit 组件的文件修改清单
- `Lua_GameDefine`：`enum_UnitComponent` 新增枚举
- `Lua_NpcComponentsConfig`：新增配置（用于创建实例）
- `LC_DAL_Buff`：新增事件通知
- `LC_Common_NotifyId`：新增事件 ID
- `LC_PerformState_Agent_ChangeStateByBuff`：新增文件（记得提交 meta）
- `GlobalRequire`：新增 require 引用

### AOI 算法
[Unity3D MMORPG 核心技术：AOI 算法源码分析](https://zhuanlan.zhihu.com/p/621090112)

## 03/25 调试与架构

### Lua 共享虚函数表
Lua 所有实例共用一个虚函数表（元表），这是 Lua 面向对象的核心设计。

## 03/26 技能 CD 与重要技能展示

### 重要技能展示开发流程
1. 创建脚本（~10min）
2. 处理展示数据，匹配数据（~15min）
3. 跑起来验证（~5min）

## 03/27 阵营系统与 HUD

### 阵营关系系统
- `UnitManager` 里有阵营关系
- HUD 读取 Map 表里的阵营关系，阵营配置是二维数组 `{1,2},{1,2}`
- 根据关系得到主动怪和被动怪，修改 HUD 显示

### 技术点备注
- 消息处理可分帧处理，避免帧率高时集中处理

## 03/28 Unity 编辑器技巧

> 在 Scene 场景窗口中，选中物体，按 **F 键**，即可将该物体设置在视图中心位置。

## 03/29 Timeline + Spine 集成

### Spine 动画在 Timeline 中播放
Timeline 支持接入 Spine 插件，实现 Spine 动画在 Timeline 里滑动播放。

参考：[spine 动画如何在 Unity 3D 的 Timeline 里播放](https://www.zhihu.com/question/461629282)

### 技能时间轴架构
- `skill_runtimeContext`：主技能上下文（只有一个）
- `perform_timeline_agent`：副技能（可能多个）
- **技能是多时间轴的**

### 服务器位置同步
`LC_Movement_NavMeshAgent` tick 每 0.1 秒同步 server 位置，客户端不会慢。

## 03/30 场景切换 Bug 修复

场景切换报错，通过查看提交记录定位问题，找到引入错误的提交后修复。

**调试技巧**：遇到场景切换类 bug，优先看最近的提交记录来定位问题。

## 03/31 系统设计思路

### Buff 展示方案
可用加 Buff 的方式配置展示，如果是特定表现，可加属性到配置，通过同步属性来处理。

### 重要技能展示优化思路
找到特定的 Unit，新增一个 Unit 类型，监听 AOI 时不用每个 Unit 都去计算，只处理指定类型的。

### 一个玩法对应的文件结构
每个玩法需要有完整的文件组织结构，包含：配置文件、交互条件、UI 表现、协议处理等。
