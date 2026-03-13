---
title: 工作记录 2024年8月
published: 2024-08-01
description: "2024年8月工作记录：公会联赛需求、位面副本开发、相机系统、场景切换流程梳理、性能优化"
tags: [工作记录]
category: 工作记录
draft: false
---

## 概述

8月主要推进公会联赛需求收尾、新副本/位面功能开发，同时深入研究了场景切换流程、相机系统（Cinemachine）、Lua性能优化。

---

## 公会联赛需求

### UI 与数据管道

- **点击穿透问题**：`raycastall` 收集鼠标位置的所有可交互组件，对比鼠标按下和抬起位置纠正。
- **LoopList 使用**：`setChildren` → `setRender` → `refresh`，close 时记得 `clear`。
- **MVC vs MVVM**：核心区别是数据绑定。之前用 MVC，现在是 MVVM——UI 注册数据绑定，数据变更触发 Model 的 data 刷新。
- **数据管道 bind_Property 大小写坑**：`UI_Sys_GuildLeague_ReportPanelCtrl.ExportConfigs` 里 `bind_Property` 写成了小写，绑定失败，数据管道逻辑没跑通。**字段名大小写必须严格匹配。**
- **GM 添加方式**：在 `gmconfig.json` 里新增一项即可。

### 战报数据设计讨论

按需加载 vs 统一加载：
- **统一加载**：历史战绩和战报信息一次性获取，减少二次请求，但数据量大。
- **按需加载**：点击战报按钮再请求，减小初次加载数据量，但增加单次延迟。
- **结论**：战报信息量大时优先按需加载；用户频繁查看时可统一加载。

---

## 相机系统（Cinemachine）

- Cinemachine 不会创建新相机，而是用**虚拟相机**（Virtual Camera）配合 `CinemachineBrain`（挂载在主相机上）工作。
- **角色移动抖动**：Debug 输出速度恒定，判断是渲染问题 → 调整相机 Update 方法与角色移动 Update 一致。若角色在 `FixedUpdate` 移动，相机也应在 `FixedUpdate` 或 `LateUpdate` 更新；使用 Cinemachine 可在 `CinemachineBrain` 的 `UpdateMethod` 改为 `FixedUpdate`。
- **镜头转向计算**：

```lua
local targetPos = Vector3.New(250, 0, 320)
local dir = targetPos - self.transform.position
local tempRot = Quaternion.LookRotation(dir)
self.m_vTargetRot.y = Quaternion.ToEulerAngles(tempRot).y
```

- **万向死锁（Gimbal Lock）**：动态坐标轴下，绕 Y 轴转 90° 后 X/Z 轴重合，失去一个旋转控制。Unity 内部用四元数表示旋转，Inspector 为编辑方便展示等价的欧拉角。

---

## 位面（副本）功能开发

### 整体流程

1. Task 任务追踪的 action 里配置区域 ID
2. 接取任务后根据配置区域 ID，客户端创建区域，配置了寻路 action 会寻路到区域
3. 客户端进入触发区域，上行服务器区域 ID
4. 服务器根据区域 ID 读取场景导出 JSON 配置，执行该区域 ID 绑定的触发行为
5. operate 表里 action 新增进入位面的行为

### 场景切换流程（详细梳理）

**加载流程：**
1. 收到 `SCEMGR_SCENE_SWITCHSCENELINE` 消息 → 执行 `LC_SceneManager:ShowScene`
2. ShowScene 打开 `UI_Sys_SceneLoaderPanel`
3. 阶段 0→1→3→4（开始异步加载场景）→异步加载完成，加载 luacomponent.prefab，创建 Lua 实例，执行 OnInit
4. 阶段 5（加载中）→ 6（加载完成）→ `LC_SceneManager:_callBack_LoadScene`
5. 执行 `LC_Scene_Sync:InitModules()`：InitAStar、InitAirWall、InitInteractManager、TriggerAreaManager、InitLocalNPC

**卸载流程：**
1. 打开 UI_Sys_SceneLoaderPanel 后，onOpen 里执行 `LC_SceneManager:DisposeActive`
2. 同场景：`m_bNotDestroy=true`，执行 `_onHideScene` → `LC_Scene_Sync:OnHide`
3. 不同场景：资源回收 + 执行 `LC_Scene_Sync:OnUnInit` → `UnInitAirWall`、`LC_UnitManager:DestroyAllUnit`

**场景 ID 区间：**
- 大世界：`1 ~ 99999`
- 副本：`1000001 ~ 9999999`

### 触发区域管理（LC_TriggerAreaManager）

每帧检测玩家是否进入/离开区域，支持：
- **圆形区域**：计算玩家与区域中心距离 vs 半径
- **矩形区域**：旋转坐标系后判断 x/z 是否在宽高范围内

进入/离开区域时发送 `POINT_IN_AREA` 协议通知服务器。

---

## Lua 性能优化

### Lua 访问 transform.position 的 NoGC 方案

```csharp
// C# 侧暴露无 GC 的位置获取方法
public static int GetTransformPositionNOGC(IntPtr L) {
    var gen_to_be_invoked = (Transform)translator.FastGetCSObj(L, 1);
    LuaAPI.lua_pushnumber(L, gen_to_be_invoked.position.x);
    LuaAPI.lua_pushnumber(L, gen_to_be_invoked.position.y);
    LuaAPI.lua_pushnumber(L, gen_to_be_invoked.position.z);
    return 3;
}
```

```lua
-- Lua 侧使用
function Vector3.GetTransformPositionNOGC(transform, kVec3)
    if kVec3 == nil then kVec3 = _new() end
    kVec3.x, kVec3.y, kVec3.z = GetTransformPosition(transform)
    return kVec3
end
```

**注意**：`Vector3.LerpNoGC` / `Quaternion.LerpNoGC` 实际是否有 GC 需要用 LuaProfiler 确认；如果已有报错继续跑，可能回退到了原生方式。

### LuaProfiler 使用注意

- 要**先开启 LuaProfiler，再运行 Unity**，顺序不能反。

---

## 纹理与渲染知识

- **NPOT（Non-Power of 2）**：纹理非 2 的幂时，推荐设为 `None`（保持原始尺寸），或 `ToNearest`（自动缩放到最近 2 的幂）。UI 纹理导入时默认 `ToNearest`，如需保持清晰度改为 `None`。
- **Mipmap**：适合地面、墙壁等远近不同的纹理；UI/HUD 不需要开启。Streaming Mipmaps 可按相机距离动态加载不同分辨率。
- **Wrap Mode**：UI/天空盒用 `Clamp`；需要平铺的地面、墙面用 `Repeat`；对称场景用 `Mirror`。
- **UGUI RenderOverlays**：Canvas 的 Overlay 渲染模式独立于 3D 场景，不受摄像机影响；在 Frame Debugger 中 `UGUI.Rendering.RenderOverlays` 可分析 UI 渲染开销。

---

## 工具与环境

- **VSCode 解析 Unity 工程失败**：将 `.sln` 文件路径移到最前面可修复加载问题。
- **IL2CPP 参考**：[IL2CPP All In One](https://www.lfzxb.top/il2cpp-all-in-one/)
- **OBS**：视频录制软件
- **Unity 场景快捷键**：`X` 切换世界/局部坐标；`Shift+F` 或双击左键使物体居中显示。
