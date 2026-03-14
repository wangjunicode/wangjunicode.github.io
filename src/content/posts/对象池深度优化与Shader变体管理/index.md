---
title: 对象池深度优化与Shader变体管理
published: 2024-11-01
description: "2024年11月工作记录：公会联赛收尾联调、聊天语音消息开发、对象池深度分析、Shader变体、Android真机调试"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 概述

11月主要完成公会联赛联调自测收尾，并推进聊天语音消息功能开发，同时深入研究了对象池管理、Shader变体、Android真机 Profiler 调试等技术点。

---

## 公会联赛收尾

### 协议版本号对齐

连接 cetest 服务器时需修改 proto 版本号：

```csharp
// proto 文件中修改为目标服务器版本号
enum MSG_Version_Type {
    MSG_VERSION_NONE = 0;
    MSG_VERSION_PROTO = 20240909; // 当前协议版本号
}
```

### VSCode 多工程联动

将不同文件夹添加到同一个 Workspace，可以互相访问和跳转。

### 同步与异步数据处理原则

- **代码侧/数据侧**：同步处理，做好数据缓存
- **表现侧/资源侧**：异步处理，处理表现逻辑

> Lua 脚本实例是同步返回的，prefab UI 虽然是异步的，但不影响在网络协议数据回调中同步处理数据，表现可以是异步的。

### Lua 模块热重载注意

```lua
lua package.loaded['xx.lua'] = nil
-- 重新 require 仍然是上一次的闭包函数，需注意
```

### PlantUML 格式化配置

```
@startuml
skinparam sequence {
    ArrowThickness 1
    ParticipantPadding 5
    MessageFontSize 10
}
@enduml
```

---

## 对象池（UT_PrefabPoolManager）深度解析

### 核心数据结构

- `m_kAllGameObjects`：包含所有资源对象（场景中的 + Pool 中的）
- `m_kPooledGameObjectMap`：Pool 缓存的 GameObject，key=资源名，value=对象列表
- `m_kCallback` / `m_kCallActions`：回调队列与对应 Action

### 核心流程

**获取对象（GetGameObjectInner）**
1. 检查 `m_kPooledGameObjectMap` 是否有空闲对象
2. 有 → 直接取出，调用 `SetParent` + `OnGetPooledGameObject`
3. 无 → 异步加载创建，加载完成后回调

**回收对象（RecycleGameObjectInner）**
```csharp
pooledGameObject.OnRecycle();
ReParentPoolNode(pooledGameObject);
pooledGameObjectList.Add(pooledGameObject);
```

**定时清理（ReleaseByTimeNew）**
```csharp
// 每 30 秒触发一次，每帧最多清理 32 个
if (updateCheck > 30.0f) {
    updateCheck = 0.0f;
    ReleaseByTimeNew();
}
// 超过 3600*10 帧未使用则释放
public bool ReleaseByTime(int frameCount, int maxSleepFrame = 3600*10)
{
    return frameCount - lastUseFrame > maxSleepFrame;
}
```

### 回调调度机制

每帧最多处理 `m_CallBackMax`(30) 个回调，防止单帧卡顿：

```csharp
private void UpdateInvokeCommonCallback()
{
    var maxCount = Math.Min(m_kCallback.Count, m_CallBackMax);
    while (maxCount-- > 0) {
        var pooledGameObject = m_kCallback.Dequeue();
        // 执行 OnGet + 回调
    }
}
```

---

## Android 真机调试

### Profiler 连接流程

```bash
# 安卓真机
adb devices                                              # 查看已连接设备
adb install -r <apk路径>                                  # 安装 apk
adb forward tcp:34999 localabstract:Unity-com.huanle.RoPrimeval  # 映射端口

# MuMu 模拟器
cd "C:\Program Files\MuMu\emulator\MuMuPlayer-12.0\shell"
adb.exe connect 127.0.0.1:7555
adb devices
adb install -r <apk路径>
adb forward tcp:34999 localabstract:Unity-com.huanle.RoPrimeval
```

**注意**：打包时需开启 Development Build + Script Debugging，才能连接 Profiler 和 Console 查日志。

### Loading 卡顿问题分析

- 忘记同时看 Lua Profiler，只看了 Unity Profiler
- 实际原因：SkillConfig（Lua配置）体积非常大，Loading 过程中同步加载导致卡顿
- 优化方向：改为异步/分帧加载配置

---

## Shader 变体（Shader Variants）

### 核心概念

Shader 变体是同一个 Shader 文件在不同渲染条件下生成的多个编译版本，通过条件编译实现功能的灵活组合。

### 两种关键词指令

| 指令 | 特点 |
|------|------|
| `#pragma multi_compile` | 为所有关键词组合生成变体，即使未使用也编译 |
| `#pragma shader_feature` | 只为实际使用的关键词组合生成变体，未使用的被剔除 |

```glsl
// 示例：基于关键词控制法线贴图
#pragma shader_feature _USE_NORMAL_MAP

void frag() {
    #ifdef _USE_NORMAL_MAP
        // 使用法线贴图
    #endif
}
```

### 变体优化策略

- **Shader Variant Collection**：手动指定需要预加载的变体集合
- **Shader Stripping**：构建时剔除不使用的变体，减小包体体积

---

## 技能目标筛选

```lua
function LC_Skill_ActionPreCheck.CheckPreTargetValidNew(kMyPlayer, kUnit, kNowPos, kSkillData, iSkillId)
    -- 1. 目标是否有效
    if IsNull(selectUnit) then return nil end
    -- 2. 技能是否可对当前目标释放
    local canSelect = LC_Skill_ActionPreCheck.CheckSkillCanInput(kUnit, iSkillId, kNowPos)
    if not canSelect then return nil end
    -- 3. 黑暗区域检测
    canSelect = LC_UnitManager:GetInstance():CheckUnitInDarkArea(selectUnit)
    if not canSelect then return nil end
    -- 4. 阵营判断 + 黑/白名单过滤
    -- 5. 施法范围/追击范围检测
    return selectUnit
end
```

---

## 聊天语音消息

### 线程安全回调（UnityMainThreadDispatcher）

Unity 只有主线程可以调用 Unity API，工作线程需通过 Dispatcher 调度：

```csharp
// 工作线程投递任务到主线程
UnityMainThreadDispatcher.Instance.Enqueue(() => {
    Debug.Log("Received on main thread: " + message);
});

// Dispatcher Update 每帧消费队列
private void Update() {
    while (_executionQueue.TryDequeue(out var action))
        action?.Invoke();
}
```

### Type.GetType 找不到类型

```csharp
// 需要指定程序集名称
Type type = Type.GetType("Romsg.xxxReq, Common");
```

原因：`Type.GetType()` 默认只在当前程序集和 mscorlib 中查找，需传入完整限定名（含程序集名）。

### C# 与 Lua 传递 JSON 数据

避免直接拼接 JSON 字符串到 Lua 代码（会有 `{` `}` 特殊字符问题），推荐通过函数参数传递：

```csharp
// 推荐方式
LA_LuaManager.Instance.CallFunction("ProcessMessage", message);
```

---

## 服务器工程调试

### dotnet 项目操作

```bash
dotnet build              # 编译
dotnet add package INIFileParser   # 添加 NuGet 包
```

### NuGet 本地缓存目录配置

在解决方案目录下创建 `NuGet.config`：

```xml
<configuration>
  <config>
    <add key="globalPackagesFolder" value=".\packages" />
  </config>
</configuration>
```

### 多 Console Application 依赖

同一 solution 下两个 Console Application 不能直接互相依赖，需通过中间 Class Library 项目实现。

---

## Texture2D vs Sprite

- **Texture2D**：原始图像资源，直接用于材质、3D 模型贴图
- **Sprite**：基于 Texture2D 的裁剪资源，专用于 2D 游戏/UI，可以是单张或图集切片
- 纹理压缩底层原理：**分块压缩 + 颜色量化 + 插值**，利用人眼感知差异降低精度，使 GPU 可并行解码

---

## 参考资料

- [Camera Culling](https://blog.csdn.net/qq_41807260/article/details/87343570)
- [技能BUFF设计](https://www.zhihu.com/question/29545727/answer/12202318426)
- [Redis 安装使用](https://blog.csdn.net/lancehao/article/details/133848789)
- [CommandLine Parser](https://github.com/commandlineparser/commandline)
