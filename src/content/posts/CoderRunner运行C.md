---
title: 游戏开发者的 C# 工具链配置指南（VS Code + Rider）
published: 2019-08-19
description: "面向 Unity 游戏开发者的 C# 开发环境完整配置指南：VS Code + C# 扩展的完整安装步骤、Code Runner 快速调试单文件、.NET SDK 与 Unity 版本对应关系、推荐扩展列表，以及 JetBrains Rider 作为专业 Unity IDE 的核心优势对比。"
tags: [工具, C#, Unity, 开发环境]
category: 开发工具
draft: false
---

刚开始学 C# 的时候，我用 VS Code 加了个 Code Runner，能直接运行单个 `.cs` 文件，做算法练习很方便。工作之后主力编辑器换到了 Rider，感受是质的飞跃——专门为 Unity 打造的 IDE，很多功能 VS Code 插件堆了也比不上。这篇文章把两种方案都介绍一下，按需选择。

---

## 方案一：VS Code + C# 扩展

VS Code 轻量、免费、启动快，适合学习阶段或者写一些独立脚本。

### 环境准备

**1. 安装 .NET SDK**

访问 [https://dotnet.microsoft.com/download](https://dotnet.microsoft.com/download) 下载安装。

验证安装：
```bash
dotnet --version
# 输出：8.0.xxx
```

**2. 安装 VS Code**

官网下载：[https://code.visualstudio.com](https://code.visualstudio.com)

### 必装扩展列表

| 扩展名 | 功能 |
|--------|------|
| **C# (Microsoft)** | C# 语言支持，智能补全、转到定义、错误提示 |
| **C# Dev Kit** | 更强的 C# 项目管理、测试、调试能力 |
| **Code Runner** | 一键运行单个文件（不需要建项目）|
| **Unity (Unity Technologies)** | Unity 专用：调试、UnityMessage 提示、Shader 着色 |
| **Shader languages support** | HLSL/GLSL Shader 语法高亮 |
| **GitLens** | Git 增强，查看每行代码的提交记录 |
| **Bracket Pair Colorizer 2** | 括号彩色配对，深层嵌套必备 |

### Code Runner 配置：运行单个 C# 文件

Code Runner 默认不支持直接运行 `.cs` 文件，需要手动配置。

**步骤1**：配置 .NET Framework 环境变量（Windows）

将以下路径加入系统 `Path` 变量：
```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319
```

或者更推荐用 .NET SDK 的 `csc`：
```
C:\Program Files\dotnet\
```

**步骤2**：在 VS Code 的 `settings.json` 中添加配置

```json
{
    "code-runner.executorMap": {
        // 方式一：使用 .NET Framework 的 csc 编译器
        "csharp": "echo= && csc /nologo /utf8output $fileName && $fileNameWithoutExt",
        
        // 方式二（推荐）：使用 dotnet-script（更现代，支持 NuGet 包）
        // 需要先安装：dotnet tool install -g dotnet-script
        // "csharp": "dotnet script $fullFileName"
    },
    "code-runner.runInTerminal": true,   // 在终端运行，支持输入
    "code-runner.saveFileBeforeRun": true // 运行前自动保存
}
```

**使用**：在 `.cs` 文件中右键 → "Run Code"，或 `Ctrl+Alt+N`。

### 更推荐的方式：dotnet-script

`dotnet-script` 支持直接运行 C# 脚本，还能用 NuGet 包：

```bash
# 安装
dotnet tool install -g dotnet-script

# 运行
dotnet script hello.cs
```

脚本文件示例（`hello.cs`）：
```csharp
#!/usr/bin/env dotnet-script
// 可以直接 #r 引用 NuGet 包
// #r "nuget: Newtonsoft.Json, 13.0.1"

using System;

var message = "Hello from C# script!";
Console.WriteLine(message);

// 支持顶层语句（Top-level statements），不需要 class/Main
for (int i = 0; i < 5; i++)
{
    Console.WriteLine($"  第 {i + 1} 次");
}
```

### VS Code 调试 Unity 项目

安装 Unity 扩展后，调试配置（`.vscode/launch.json`）：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Attach to Unity",
            "type": "unity",
            "request": "attach"
        }
    ]
}
```

Unity Editor 里：**Edit → Preferences → External Tools** 选择 VS Code 作为外部编辑器，点 "Regenerate project files"。

---

## .NET SDK 与 Unity 版本对应关系

这是新手经常搞混的地方——Unity 使用的 .NET 运行时版本和系统安装的 .NET SDK 是两回事。

| Unity 版本 | .NET 运行时 | C# 版本 | 说明 |
|-----------|------------|---------|------|
| 2018.x | .NET 3.5 / 4.x | C# 6 | 旧版本 |
| 2019.x | .NET 4.x | C# 7.3 | 基础现代特性 |
| 2020.x | .NET 4.x | C# 8 | `?? =`、`switch` 表达式 |
| 2021.x | .NET Standard 2.1 | C# 9 | Records、Init-only |
| 2022.x / 6.0 | .NET 6 | C# 10 | File-scoped namespaces |
| Unity 6 (2023.x+) | .NET 7+ | C# 11 | 持续更新 |

**实际建议**：
- 本地安装最新的 .NET SDK（.NET 8），用于 VS Code / Rider 的 Language Server
- Unity 的运行时版本在 **Project Settings → Player → Other Settings → Scripting Backend** 里看
- 如果 Unity 是 2021+，可以放心使用 C# 8/9 大部分特性

---

## 方案二：JetBrains Rider（Unity 推荐方案）

如果你是全职 Unity 开发，强烈推荐 Rider。虽然需要付费（腾讯员工可以申请 JetBrains 企业授权），但提升的效率完全值回票价。

### Rider 相比 VS Code 的核心优势

**1. Unity 深度集成**

Rider 有专门的 Unity 插件（内置），能做到：
- 在 Rider 里看 Unity 的 Console Log，双击直接跳到对应代码行
- 检测 `Update()` 里的空操作（比如空的 `Update` 方法也会消耗性能，Rider 会警告）
- 识别 Unity 序列化字段，知道哪些字段在 Inspector 里可见
- 直接查看 UnityEvent 的所有订阅者

**2. 更强的代码分析**

Rider 的静态分析比 VS Code + C# 扩展强得多：

```csharp
// Rider 会提示：这个 MonoBehaviour 的 Update 方法是空的，浪费性能
public class EmptyUpdate : MonoBehaviour
{
    private void Update() { } // ⚠️ Rider 警告：空 Update
}

// Rider 会提示：Camera.main 在 Update 里调用，每次都会做场景查找，建议缓存
void Update()
{
    Camera.main.transform.position; // ⚠️ 建议缓存 Camera.main
}
```

**3. 超强重构支持**

- 重命名方法/变量时，自动更新所有引用（包括 Unity 序列化数据里的字符串引用！）
- 提取方法、内联变量、移动到另一个类——这些操作一键完成
- 转到实现（`Ctrl+Alt+B`），直接跳到接口的具体实现

**4. 数据库查询写法支持**

对 LINQ、EF 等有专门的提示和格式化，写 LINQ 查询体验好很多。

### Rider 配置 Unity

1. 打开 Unity → **Edit → Preferences → External Tools**
2. External Script Editor 选择 **Rider**
3. 点击 **Regenerate project files**

在 Rider 打开项目后，右下角会自动检测 Unity 并提示连接。

---

## 两种方案总结对比

| 维度 | VS Code + 插件 | Rider |
|------|--------------|-------|
| **价格** | 免费 | 付费（约 249$/年，或企业授权）|
| **启动速度** | 快 | 慢（JVM 启动）|
| **Unity 集成** | 基本可用 | 深度集成，体验更好 |
| **代码分析** | 较弱 | 业界最强 |
| **重构能力** | 基础 | 强大 |
| **内存占用** | 低 | 较高 |
| **适合场景** | 学习、轻量脚本 | 专业 Unity 开发 |

**我的推荐路径**：
- 初学阶段：VS Code + Code Runner，轻量入门
- 开始做 Unity 项目：VS Code + Unity 扩展
- 进入工作/严肃项目：切换到 Rider，效率翻倍
