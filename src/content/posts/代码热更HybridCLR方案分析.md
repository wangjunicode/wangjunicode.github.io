---
title: 06_代码热更HybridCLR方案分析
published: 2024-01-01
description: "06_代码热更HybridCLR方案分析 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 热更新
draft: false
encryptedKey: henhaoji123
---

# 06_代码热更HybridCLR方案分析

> 面向刚入行的毕业生 · 建议搭配 ClientBridge.cs 和 BuildAssetsCommand.cs 阅读

---

## 1. 系统概述

### 1.1 代码热更的挑战

Unity 默认使用 IL2CPP 将 C# 代码编译为 C++ 再编译为原生机器码（AOT，Ahead-Of-Time 编译）。这带来了性能优势，但也带来了一个致命问题：**AOT 编译的代码不能在运行时被修改或替换**。

传统解决方案（如 Lua、XLua、ILRuntime）都需要用其他脚本语言替代部分 C# 代码，存在以下问题：
- 需要学习新语言（Lua 等）
- 性能开销大（解释执行）
- 与 C# 生态的互操作复杂

### 1.2 HybridCLR 是什么？

**HybridCLR**（原名 huatuo）是腾讯互娱自研的 Unity 热更新解决方案（现已开源），其核心理念是：**让 IL2CPP 支持解释执行热更程序集**。

简单来说：
- **AOT 程序集**（不热更）：正常 IL2CPP 编译，完全原生性能
- **热更程序集**：运行时通过 `Assembly.Load(bytes)` 动态加载，由 HybridCLR 实现的解释器执行

这意味着**开发者继续写 C#，热更程序集依然是标准的 .NET Assembly，完全兼容 C# 生态**。

### 1.3 在本项目中的热更程序集列表

根据 `ClientBridge.cs` 中的代码，本项目的热更程序集包括：

| 程序集 | 说明 |
|--------|------|
| `Game.Model` | 游戏数据模型层（ECS 实体、组件定义） |
| `Game.Function` | 游戏功能逻辑层 |
| `Game.FunctionView` | 功能视图层 |
| `Game.Battle.Model` | 战斗数据模型 |
| `Game.Battle.Function` | 战斗逻辑 |
| `Game.UI.Model` | UI 数据模型 |
| `Game.UI.Function` | UI 逻辑 |

这些程序集的代码在游戏启动时通过热更下载，通过 `Assembly.Load` 动态加载后，游戏逻辑由这些热更程序集驱动。

---

## 2. 架构设计

### 2.1 HybridCLR 整体工作原理

```
┌─────────────────────────────────────────────────┐
│              App 安装包（AOT 部分）               │
│                                                   │
│  底层框架：                                        │
│  - Core（ECS 框架）                               │
│  - Index（游戏入口）                              │
│  - Patch（热更模块）                              │
│  - Unity 引擎 DLL（UnityEngine.*.dll）            │
│  - 第三方 SDK DLL（GCloud、MSDK 等）              │
│                                                   │
│  以上由 IL2CPP 编译为原生代码，100% 原生性能       │
└─────────────────────────┬───────────────────────┘
                           │ 启动时加载
┌─────────────────────────▼───────────────────────┐
│              热更程序集（HybridCLR 解释执行）      │
│                                                   │
│  Game.Model.dll.bytes                            │
│  Game.Function.dll.bytes                         │
│  Game.Battle.Model.dll.bytes                     │
│  ...                                             │
│                                                   │
│  由 HybridCLR 解释器执行                          │
│  可随时通过热更替换为新版本                        │
└─────────────────────────────────────────────────┘
                    ↑
           AOT 元数据补充（必须）
           
┌─────────────────────────────────────────────────┐
│              AOT 元数据（补充泛型支持）           │
│                                                   │
│  mscorlib.dll.bytes                              │
│  System.dll.bytes                                │
│  System.Core.dll.bytes                           │
│  ...                                             │
│                                                   │
│  用于补充热更代码中用到的 AOT 泛型函数元数据       │
└─────────────────────────────────────────────────┘
```

### 2.2 DLL 加载流程

```
ClientBridge.StartGame()
    │
    ▼
LoadHotUpdateDll()
    │
    ├─ [HybridCLR 模式] LoadMetadataForAOTAssemblies()
    │   └─ 补充 AOT 元数据（必须在加载热更 DLL 之前）
    │
    ├─ 读取 HotUpdateDllConfig.bytes → 获取 DLL 文件列表
    │
    └─ foreach dll in HotUpdateAssemblyFiles:
        │
        ├─ getAssembly(assemblyName)
        │   ├─ [HybridCLR 模式] ReadDllBytes() → Assembly.Load(bytes)
        │   └─ [非 HybridCLR 模式] AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault()
        │
        ├─ 记录特殊程序集：modelAssembly = assembly（Game.Model）
        │
        └─ EventSystem.Instance.Add(AssemblyHelper.GetAssemblyTypes(assemblies))
               ← 将热更类型注入 ECS 事件系统
    │
    ▼
modelAssembly.GetType("ClientEntry").GetMethod("DllPostLoad").Invoke(null, param)
    ← 通过反射调用热更程序集的入口函数
```

---

## 3. 核心代码展示

### 3.1 热更 DLL 加载主流程

```csharp
// ClientBridge.cs
public static void LoadHotUpdateDll()
{
    // Step 1: 补充 AOT 元数据（仅 HybridCLR 模式需要）
    if (EngineDefine.isHybridCLR)
    {
        LoadMetadataForAOTAssemblies();
    }

    // Step 2: 读取热更 DLL 列表配置
    var configBytes = ReadDllBytes("HotUpdateDllConfig.bytes", false);
    var HotUpdateAssemblyFiles = new List<string>();
    if (configBytes != null)
    {
        string hotUpdateConfig = Encoding.UTF8.GetString(configBytes);
        HotUpdateAssemblyFiles.AddRange(
            hotUpdateConfig.Split(",", StringSplitOptions.RemoveEmptyEntries));
    }

    // Step 3: 加载热更程序集
    List<Assembly> assemblies = new List<Assembly>() 
    { 
        typeof(Game).Assembly,   // Core 程序集（AOT）
        typeof(Index).Assembly   // Index 程序集（AOT）
    };
    
    foreach (var assemblyName in HotUpdateAssemblyFiles)
    {
        Assembly assembly = getAssembly(assemblyName);
        
        if (assembly == null)
        {
            Debug.LogError($"[ClientBridge] 程序集 {assemblyName} 加载失败！跳过");
            continue;
        }

        // 记录 Game.Model 程序集（后续反射调用需要用到）
        if (assemblyName == "Game.Model")
        {
            modelAssembly = assembly;
        }

        assemblies.Add(assembly);
        hotUpdateDllDict[assemblyName] = assembly; // 缓存供后续查询
    }

    // Step 4: 将所有热更类型注入 ECS 事件系统
    EventSystem.Instance.Add(AssemblyHelper.GetAssemblyTypes(assemblies.ToArray()));
    ReflectUtil.InitTypes();
    SRDebuggerBridge.Init();
    GMBridge.Init();
}
```

### 3.2 AOT 元数据补充

```csharp
// ClientBridge.cs
private static List<string> AOTMetaAssemblyFiles { get; } = new List<string>()
{
    "mscorlib",           // .NET 标准库
    "System",             // System 命名空间
    "System.Core",        // LINQ 等核心功能
    "Microsoft.Extensions.Logging",
    "Zlogger",
    "Unity.RemoteFileExplorer",
};

private static void LoadMetadataForAOTAssemblies()
{
    HomologousImageMode mode = HomologousImageMode.SuperSet;
    
    // 从 AOTConfig.bytes 读取额外需要补充的程序集（自动分析生成）
    var configBytes = ReadDllBytes("AOTConfig.bytes", false);
    if (configBytes != null)
    {
        string aotConfig = Encoding.UTF8.GetString(configBytes);
        AOTMetaAssemblyFiles.AddRange(
            aotConfig.Split(",", StringSplitOptions.RemoveEmptyEntries));
    }

    foreach (var aotDllName in AOTMetaAssemblyFiles)
    {
        string assName = ZString.Concat(aotDllName, ".dll.bytes");
        byte[] dllBytes = ReadDllBytes(assName);
        
        // 调用 HybridCLR API 补充元数据
        LoadImageErrorCode err = RuntimeApi.LoadMetadataForAOTAssembly(dllBytes, mode);
        Log.LogInfo($"LoadMetadataForAOTAssembly:{aotDllName}. mode:{mode} ret:{err}");
    }
}
```

**SuperSet 模式说明**：`HomologousImageMode.SuperSet` 表示"超集"模式，允许补充元数据的 DLL 版本高于主包中的版本（只要函数签名兼容）。这使得热更时可以更新 AOT 程序集的功能而不需要重新打包主包。

### 3.3 DLL 文件读取（多路径查找）

```csharp
// ClientBridge.cs
public static byte[] ReadDllBytes(string path, bool decrypt = true)
{
    // 优先从热更目录读取（有热更版本用热更版本）
    string fullPath = Path.Combine(GetHotUpdateDllPath(), path);
    
    if (!File.Exists(fullPath))
    {
        // 热更目录没有，回退到安装包 StreamingAssets
        fullPath = Path.Combine(Application.streamingAssetsPath, "HotUpdateDll", path);
    }
    else
    {
#if !UNITY_EDITOR && UNITY_ANDROID
        // Android 真机需要加 "file://" 前缀
        fullPath = ZString.Concat("file:///", fullPath);
#endif
    }

    return ReadAndDecryption(fullPath, decrypt);
}

// 热更 DLL 存放路径
public static string GetHotUpdateDllPath()
{
    // persistentDataPath/ResUpdate/Android(iOS/StandaloneWindows)/HotUpdateDll/
    return Path.Combine(
        Application.persistentDataPath, 
        HotUpdateRootDirName,  // "ResUpdate"
        platformDir,           // "Android" / "iOS" / "StandaloneWindows"
        "HotUpdateDll");
}
```

### 3.4 反射调用热更入口

```csharp
// ClientBridge.cs
private void StartGame(string token)
{
    LoadHotUpdateDll();
    
    // 从热更程序集中获取 ClientEntry 类型
    typ = modelAssembly.GetType("ClientEntry");
    
#if UNITY_EDITOR
    param1b[0] = UnityEditor.EditorPrefs.GetString("VGame_GAMEDATA_MODE", "") == "DEV";
#else
    param1b[0] = false;
#endif

    // 通过反射调用 ClientEntry.DllPostLoad(bool) 方法
    // 这是热更程序集的"正式入口"
    var method = typ.GetMethod("DllPostLoad");
    method.Invoke(null, param1b);  // null = 静态方法
    
    _inited = true;
    PostDLLLoad?.Invoke(); // 通知其他组件（如 SRDebugger）DLL 已加载
}
```

**为什么用反射？** AOT 代码（`ClientBridge`）不能直接引用热更代码（`ClientEntry`），因为热更 DLL 在 AOT 编译时还不存在。反射是唯一能在运行时动态调用热更代码的方式。

### 3.5 程序集存在性检查（调试工具）

```csharp
// ClientBridge.cs
private static void CheckDllLocation(string assemblyName)
{
    if (AppDomain.CurrentDomain.GetAssemblies().Any(a => a.GetName().Name == assemblyName))
    {
        Debug.LogError($"[ClientBridge] 程序集 {assemblyName} 已在底包中");
        // ← 危险！热更程序集被错误地打入了底包
    }
    else
    {
        // 检查热更目录是否有 DLL
        string fullPath = Path.Combine(GetHotUpdateDllPath(), assemblyName + ".dll.bytes");
        if (File.Exists(fullPath))
            Debug.LogError($"[ClientBridge] ResUpdate 中存在 {assemblyName}");
        else
            Debug.LogError($"[ClientBridge] 程序集 {assemblyName} 根本不存在");
    }
}
```

---

## 4. 设计亮点

### 4.1 双模式兼容（HybridCLR + 非 HybridCLR）

```csharp
static Assembly getAssembly(string name)
{
    if (!EngineDefine.isHybridCLR)
    {
        // 编辑器/非 HybridCLR 模式：从已加载程序集中查找
        assembly = AppDomain.CurrentDomain.GetAssemblies()
            .FirstOrDefault(a => a.GetName().Name == name);
    }
    else
    {
        // HybridCLR 模式：读取 .dll.bytes 文件，动态加载
        var bytes = ReadDllBytes(ZString.Concat(name, ".dll.bytes"));
        if (bytes != null && bytes.Length > 0)
            assembly = Assembly.Load(bytes);
    }
    return assembly;
}
```

编辑器中（`isHybridCLR = false`）直接从 Unity 编译的程序集中查找，避免了在开发时每次都要走热更 DLL 流程，大幅提升迭代效率。

### 4.2 热更类型自动注册到 ECS 事件系统

```csharp
// 将热更程序集中的所有类型（包括 ETSystem、Handler 等）
// 自动注册到 ECS 事件系统中
EventSystem.Instance.Add(AssemblyHelper.GetAssemblyTypes(assemblies.ToArray()));
```

这是 ET 框架的核心设计：所有带 `[EntitySystem]`、`[Invoke]` 等 Attribute 的热更类型会被自动发现并注册，无需手动维护注册列表。

### 4.3 HotUpdateDllConfig 动态配置

热更 DLL 列表通过 `HotUpdateDllConfig.bytes` 文件动态配置，而不是硬编码在底包中。这意味着：
- 可以通过热更**新增**一个热更程序集（只需更新 Config 文件和 DLL）
- 不需要重新打包安装包

### 4.4 缓存字典快速查找

```csharp
private static readonly Dictionary<string, Assembly> hotUpdateDllDict = new();

// 热更后可以通过程序集名称直接获取
public static Assembly GetHotUpdateDll(string assemblyName)
{
    if (hotUpdateDllDict.ContainsKey(assemblyName))
        return hotUpdateDllDict[assemblyName];
    return null;
}
```

---

## 5. HybridCLR 核心概念补充

### 5.1 AOT vs 解释执行

| 特性 | AOT（IL2CPP，底包） | 解释执行（HybridCLR，热更） |
|------|---------------------|----------------------------|
| 执行性能 | 100%（原生） | ~50-80%（视场景） |
| 可热更 | 否 | 是 |
| 泛型支持 | 需提前生成 | 通过 AOT 元数据补充 |
| 调试 | 需特殊配置 | 支持 VS 调试 |

### 5.2 SuperSet 模式

HybridCLR 的 `HomologousImageMode.SuperSet` 允许补充元数据的 DLL 版本高于安装包内的版本，只要函数签名兼容。这意味着可以通过热更更新部分 AOT 程序集的实现，扩展了热更能力。

### 5.3 常见错误及解决方案

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| `ExecutionEngineException: no AOT code` | AOT 泛型缺少元数据 | 重新生成 AOTConfig，补充元数据 |
| `TypeLoadException` | 类型未找到 | 检查 HotUpdateDllConfig，确认 DLL 正确加载 |
| `BadImageFormatException` | DLL 文件损坏 | 重新打包，检查下载完整性 |
| `MissingMethodException` | 底包有该程序集，热更也有 | 检查 HybridCLR 配置，防止底包打入热更程序集 |

---

## 6. 常见问题与最佳实践

### Q1：热更程序集中可以使用 Unity API 吗？
**A**：可以，HybridCLR 完全支持在热更代码中调用 Unity API（`UnityEngine.*`）。Unity DLL 是 AOT 编译的，热更代码通过正常的函数调用访问它们。

### Q2：热更代码中的 `new List<SomeType>()` 会有 AOT 泛型问题吗？
**A**：如果 `SomeType` 是热更代码中定义的类型，不会有问题（热更 DLL 自身的泛型由 HybridCLR 解释器直接处理）。如果 `SomeType` 在 AOT 程序集中，需要确认 AOT 代码中有对应的泛型实例化，或者通过 AOT 元数据补充。

### Q3：热更代码修改了底包的类（AOT 类）？
**A**：HybridCLR 不支持修改 AOT 类的逻辑。热更只能更新热更程序集中的类。架构上应将需要热更的逻辑放在热更程序集，稳定的框架代码放在底包。

### Q4：如何减少热更程序集的体积？
**A**：
1. 合理拆分程序集，只热更真正会变化的代码
2. 使用 Unity 的 Managed Stripping（代码裁剪），注意配置 `link.xml` 防止误裁
3. 对 DLL bytes 进行压缩（如 gzip），加载时解压

### Q5：Unity Editor 模式下如何正确调试热更代码？
**A**：在 `EngineDefine.isHybridCLR = false` 时（编辑器默认），`getAssembly` 会从 Unity 编译的程序集中查找，可以直接用 Visual Studio/Rider 断点调试。热更 DLL 调试建议在设备上使用 Unity 的 IL2CPP Debugger 或 HybridCLR 提供的调试工具。
