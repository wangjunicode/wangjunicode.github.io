---
title: 工作记录 2024年3月
published: 2024-03-01
description: "新入职第一个月，熟悉 Unity + Lua 项目技术栈，完成 GVE 玩法炮台轮盘交互需求、Timeline 过场动画资源加载支持、资源加载流程优化，整理 Lua 热重载、技能系统、交互条件系统等技术笔记。"
tags: [工作记录, Unity, Lua, 游戏开发, 架构设计]
category: 工作记录
draft: false
---

## 项目技术栈概览

入职第一个月，快速熟悉项目环境和核心技术栈：

- **版本控制**：P4V（Perforce），主分支 `RoPrimeval/Trunk`
- **安全沙箱**：DACS（DCubeSetup）双桌面隔离方案，内外网文件共享通过剪切板 Alt+V
- **Lua 开发**：IDEA + EmmyLua，项目使用 xLua 框架，Lua 5.3 版本
- **项目管理**：TAPD

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

核心入口：
- `GameMain.cs`：游戏主入口
- `LA_LuaComponent`：Lua 组件初始化
- `CoroutineManager`：协程管理器

---

## Lua 面向对象设计

项目 Lua 采用元表（metatable）实现面向对象，通过**懒加载**方式访问 widget 和控件：

```lua
-- Lua 面向对象：元表实现
local MyClass = BaseClass("MyClass", ParentClass)

function MyClass:ctor()
    -- 初始化
end

-- 冒号 `:` 定义方法，第一个参数为隐式 self
function MyClass:doSomething()
    self.m_someWidget:SetActive(true)
end

-- 点号 `.` 调用需手动传 self
MyClass.doSomething(instance)
```

**Lua 运算符注意**：
- `and`：A 为 true 返回 B，A 为 false 返回 A
- `or`：A 为 true 返回 A，A 为 false 返回 B
- Lua 所有实例共用一个虚函数表（元表），是 Lua 面向对象的核心设计

---

## 事件系统（发布-订阅模式）

项目事件系统采用模块 ID + 通知 ID 的二级分发机制：

```lua
-- 注册事件
function UI_Sys_MainPanelCtrl:_registerEvents()
    LC_Event:RegisterEvent(
        LC_ModuleId.Common,
        LC_NotifyId.Common.UpdateCannonNotify,
        self._changeSkillType,
        self
    )
end

-- 注销事件（防止内存泄漏）
function UI_Sys_MainPanelCtrl:_unRegisterEvents()
    LC_Event:UnregisterEvent(
        LC_ModuleId.Common,
        LC_NotifyId.Common.UpdateCannonNotify,
        self._changeSkillType,
        self
    )
end

function UI_Sys_MainPanelCtrl:_changeSkillType(skillType)
    if self.m_kJoyStickSkillWidget then
        Lua_UT_Helper.SetActive(self.m_kJoyStickSkillWidget.gameObject, false)
    end
end
```

---

## Lua 热重载实现原理

Editor 模式下通过 `FileSystemWatcher` 监听 `.lua` 文件变化，自动重载：

### C# 侧：文件监听器

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
            var watcher = new FileSystemWatcher
            {
                IncludeSubdirectories = true,
                Path = dirPath,
                Filter = "*.lua",
                InternalBufferSize = 10240,
                EnableRaisingEvents = true
            };
            watcher.Changed += handler;
        }
    }
}
```

### C# 侧：触发热重载

```csharp
#if UNITY_EDITOR
    LuaFileWatcher.CreateLuaFileWatcher(LA_LuaManager.Instance.GetLuaGlobalEnv());
#endif
```

文件变化后通过 `EditorApplication.update` 回调，调用 `luaEnv.DoString` 重新加载对应模块。

### Lua 侧：热更新初始化

```lua
function Init(testScence)
    local f = function()
        require "gamemain"
        _G.RoFix = require "luahotupdate"
        _G.RoFix.Init("hotupdatelist", {})
    end
end
```

---

## 资源加载系统架构

项目资源加载系统分层设计：

```
ResourceManager（顶层入口）
├── GetAssetLoadType()   → 根据文件扩展名决定加载类型（枚举）
├── AsyncLoadAsset()     → 异步加载入口
└── Tick()               → 分帧处理加载队列（同时处理 10 个请求）

ResourceLoader
└── LoadAsync()          → 执行实际加载（Resources.LoadAsync）

ResourceManifestSlot
└── GetLoadTypeByPath()  → 从 ResManifest 获取资源路径类型
```

### 加载接口使用

```lua
-- 方式1：分步加载（先拿 ID，再获取对象）
local id = ResourceManager:LoadUObjectToID(path)
local obj = ResourceManager:GetIDObject(id)

-- 方式2：一步到位
ResourceManager:LoadUObjectAsync(path, callback)
```

**关键限制**：`Resources.LoadAsync` 的异步只是磁盘→内存阶段，**Instantiate（实例化）是同步操作，无法真正异步**，是帧率波动的主要来源之一。

### 支持 Timeline 资源加载的修改点

为支持 `.playable` 格式的 Timeline 资源，需在加载系统中新增支持：

1. `LoadType` 枚举新增 `Playable`
2. `ResourceManager.GetAssetLoadType()` 新增 `.playable` 扩展名识别
3. `ResourceLoader.LoadAsync()` 新增 Playable 类型处理：`Resources.LoadAsync<UnityEngine.Object>(pathNoExt)`
4. `EditorConst` 新增 Timeline 文件夹的 AB 包收集路径

---

## Timeline 过场动画

### 工作原理

Timeline 是 Unity 的序列化时间轴系统：
- **时间轴资源**（`.playable`）：保存到项目中，描述时间轴的轨道和 Clip 配置
- **时间轴实例**（Playable Director）：保存到场景，绑定实际对象引用

### 自定义 Track/Clip

自定义 Timeline Clip 需要两个类：
- `PlayableAsset`：数据存储（序列化到 `.playable` 资源中）
- `PlayableBehaviour`：逻辑执行（每帧 ProcessFrame 被调用）

### Timeline 保存 prefab 引用问题

**问题**：Timeline 导入后无法导出保存。  
**原因**：保存需要 prefab 引用，直接 `Load` + `Instantiate` 的对象不持有 prefab 引用，无法写回资源文件。  
**解决**：通过 `AssetDatabase.LoadAsset` 加载原始资源，而非 `Instantiate` 实例。

### Spine 动画在 Timeline 中播放

Timeline 支持通过 Spine 插件扩展，实现 Spine 动画在时间轴上的时间控制和混合。

### Signal 信号系统

Timeline 可通过 Signal 触发游戏逻辑事件，适合在过场动画特定时刻触发音效、对话、特效等。

---

## 技能系统架构

### 技能生产流程

```
原画 → 模型（模型/材质/贴图）→ 动作（状态机/prefab）
→ 特效 → 触发器策划（技能触发器拼装）→ 触发器服务器（数值/功能）
→ 需求（配表/技能时间轴编辑）→ 数值 → 服务器 → 客户端
```

### 技能发起流程

```
检查技能 CD → 处理用户输入 
→ 技能筛选器（条件检查）→ 施法范围检查 
→ 选择目标数据 → 发送服务器
```

### 技能时间轴架构

- `skill_runtimeContext`：主技能上下文，唯一实例
- `perform_timeline_agent`：副技能执行器，可以有多个（技能是**多时间轴**的）

### 技能范围类型

- 圆形（AOE Circle）
- 扇形（AOE Sector）
- 矩形（AOE Rect）

施法开始时包含两个关键信息：
- **施法目标**（Unit）：目标单位引用
- **施法目标点**（Vector3）：目标坐标

---

## 交互条件系统

### 设计思路

策划通过配表定义交互条件，程序只提供执行框架：

- `ConditionConfig`：条件类型定义表
- `NPCInteractConfig`：NPC 交互表（包含交互 ID、检查条件、执行 func 及参数）

### 交互检测流程

```
每帧 Tick（InteractManager）
    ↓
遍历场景所有 Unit
    ↓
距离检测（AOI 格子，size: 30×30）
    ↓
满足距离 → 读取 NPCInteractConfig 检查条件
    ↓
条件满足 → 刷新交互表现层（高亮提示等）
```

AOI 格子算法：场景划分为 30×30 单位大小的格子，每帧只检测玩家周围相邻格子内的 Unit，大幅减少检测量。

---

## UI 制作工作流

### 创建界面标准流程

1. 用 UI 工具创建 prefab
2. 点击 Code Generate 生成 MVC 脚本
3. 生成物：prefab + MVC 脚本 + uiprefabconfig 配置

### Cinemachine

Cinemachine 是 Unity 2017 推出的摄像机控制模块，解决多摄像机混合、切换的复杂问题，配合 Timeline 实现过场镜头效果，支持：人物对话镜头、移动跟随、摄像机抖动等。

### Camera Culling Mask

Culling Mask 控制相机渲染哪些 Layer 的物体，常用于战斗中分离 3D 场景层和 UI 层，或隐藏某些调试物体。

---

## 调试技巧

- **P4V 文件修改**：改文件前先 Checkout，更新有报错按 F11 重新编译
- **P4V 删除文件**：要在 depot 里删除，不能只删本地文件
- **VS 调试 Unity 卡死**：删除所有断点 → 删除 `.vs` 文件夹 → 重新生成 sln → 重启
- **Scene 视图定位**：选中物体按 **F 键**，快速将物体置于视图中心
- **协议调试**：`NW_GameServerHandler` 是协议统一处理位置，可断点跟踪所有协议
- **场景切换 Bug**：优先查最近提交记录定位问题引入时间点
