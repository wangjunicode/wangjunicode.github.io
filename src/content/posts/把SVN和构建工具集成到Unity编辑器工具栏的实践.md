---
title: 把 SVN 和构建工具集成到 Unity 编辑器工具栏的实践
published: 2026-03-31
description: 深入解析如何用 UnityToolbarExtender 在编辑器工具栏中集成 SVN 操作、导表按钮和运行时调试开关，打造团队专属的开发工作台。
tags: [Unity, 编辑器工具, 构建流水线, 开发效率]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么要扩展 Unity 工具栏？

Unity 默认工具栏只有播放/暂停/步进按钮。对于有几十人的开发团队，每个人每天都要重复做几十次的操作——SVN 提交、导表、打包——如果每次都要打开命令行或在菜单里找，积累起来是巨大的时间浪费。

`UnityToolbarExtender` 是一个开源插件，允许在 Unity 工具栏中添加自定义按钮。结合 `[InitializeOnLoad]`，我们可以在 Unity 启动时自动注册这些按钮。

---

## 核心架构

```csharp
[InitializeOnLoad]
public class ILRuntimeBuildGameClient : AssetPostprocessor
{
    static ILRuntimeBuildGameClient()
    {
        // 注册到工具栏右侧
        UnityToolbarExtender.ToolbarExtender.RightToolbarGUI.Add(OnToolbarGUI);
        // 注册到工具栏左侧
        UnityToolbarExtender.ToolbarExtender.LeftToolbarGUI.Add(OnLeftToolbarGUI);
    }
    
    static void OnToolbarGUI() { /* 右侧按钮 */ }
    static void OnLeftToolbarGUI() { /* 左侧控件 */ }
}
```

`[InitializeOnLoad]` 是 Unity 提供的特性，标记的类在 Unity 编辑器启动、代码重新编译时都会自动调用静态构造函数。

---

## 工具栏的实际功能

### SVN 集成按钮

```csharp
if (GUILayout.Button("提交"))
{
    SvnCommand(EngineDefine.SvnCommitCmd, "提交");
}

if (GUILayout.Button("更新"))
{
    if (EditorUtility.DisplayDialog("是否更新？", "是否更到最新版本？", "是", "否"))
    {
        Cmd.Run("TortoiseProc.exe", $"/command:update /path:\"{Root}\"");
        UpdateInit();  // 更新后重新初始化（重新导表等）
    }
}

if (GUILayout.Button("回退"))
{
    SvnCommand("revert", "回退");
}
```

这些按钮调用 TortoiseSVN 的命令行接口，弹出 SVN 操作窗口。对于版本控制操作，保留了"是否确认"对话框（`EditorUtility.DisplayDialog`），防止误操作。

### 导表功能

```csharp
if (GUILayout.Button("分组&导表"))
{
    UpdateInit();  // 分组 + 重新导出所有配置表
}
```

一键触发完整的数据生成流程：
1. 扫描 Design/Data 目录下的所有 Excel 文件
2. 按配置分组
3. 批量导出为 JSON/二进制格式
4. 刷新 Unity Asset Database

### 表格快速打开

```csharp
if (GUILayout.Button("开表"))
{
    string[] xlsFiles = Directory.GetFiles(Xls, "*.*", SearchOption.AllDirectories);
    var source = xlsFiles
        .Where(x => x.Contains(".xls") && !x.Contains("__") && !x.Contains("$"))
        .ToList();
    
    // 使用 Odin Inspector 的泛型选择器弹出
    var selector = new GenericSelector<string>(
        "选择表格", 
        false, 
        x => Path.GetFileName(x).Replace(".xlsx", ""),
        source);
    
    selector.SelectionConfirmed += OpenXls;
    selector.ShowInPopup(new Vector2(0, EditorStyles.toolbar.fixedHeight));
}
```

不是直接打开所有表格，而是弹出一个搜索选择器，输入关键字快速定位需要的表格。`!x.Contains("__") && !x.Contains("$")` 过滤掉临时文件（Excel 打开时会生成 `~$文件名.xlsx` 临时锁定文件）。

---

## 调试开关：PlayerPrefs 持久化运行时设置

工具栏还有大量调试开关，这些开关的状态通过 `PlayerPrefs` 持久化保存：

```csharp
var oldUseBinary = PlayerPrefs.GetInt("UseBinary", 0) == 1;
var useBinary = GUILayout.Toggle(oldUseBinary, "启用二进制");
if (oldUseBinary != useBinary)
{
    PlayerPrefs.SetInt("UseBinary", useBinary ? 1 : 0);
    SerializeHelper.UseBinary = useBinary;  // 立即生效
}
```

**只在状态改变时才写入 PlayerPrefs**（`if (oldUseBinary != useBinary)`），避免每帧都写，提升性能。

这套模式可以扩展到任何需要"在编辑器中快速切换"的配置：

| 开关名 | 作用 |
|--------|------|
| 启用二进制 | 切换配置表读取格式 |
| 启用 Release | 切换是否使用 Release 版配置 |
| 禁用预加载 | 跳过启动时的资源预加载（快速测试） |
| 关跳字 | 关闭飘字 UI（方便截图） |
| 禁用受击框 | 关闭碰撞盒可视化 |

---

## 左侧工具栏：时间缩放控制

```csharp
static void OnLeftToolbarGUI()
{
    ProcessTimeScaleGUI();
}

static void ProcessTimeScaleGUI()
{
    // 横向滑块，范围 0.1x ~ 9.9x，宽度 100 像素
    Time.timeScale = GUILayout.HorizontalSlider(
        Time.timeScale, 0.1f, 9.9f, GUILayout.Width(100));
    GUILayout.Label($"TimeScale:{Time.timeScale:0.0}");
}
```

这是一个非常实用的调试工具：
- 慢速（0.1x）：观察高速动作细节（攻击判定、粒子特效）
- 正常（1.0x）：正常游戏速度
- 快速（9.9x）：快速测试长时间流程（副本结算、故事演出）

---

## AssetPostprocessor：自动化资源处理

`ILRuntimeBuildGameClient` 还继承了 `AssetPostprocessor`，可以监听资源导入事件：

```csharp
public class ILRuntimeBuildGameClient : AssetPostprocessor
{
    // 当有资源被导入时自动调用
    static void OnPostprocessAllAssets(
        string[] importedAssets,
        string[] deletedAssets,
        string[] movedAssets,
        string[] movedFromAssetPaths)
    {
        // 检测到特定文件变化时自动触发构建步骤
        foreach (var path in importedAssets)
        {
            if (path.EndsWith(".cs") && path.Contains("Scripts/HotFix"))
            {
                // Hotfix 脚本变化，触发重新编译热更新 DLL
                BuildAssembliesHelper.BuildHotfix();
            }
        }
    }
}
```

通过 `AssetPostprocessor`，可以实现"保存代码自动触发构建"的自动化流程，减少手动操作。

---

## 路径管理：不硬编码的项目结构定义

```csharp
static string Path => Application.dataPath;                                // Assets 文件夹
static string Root => Directory.GetParent(Path).Parent.ToString();         // 项目根目录
static string Cfg  => System.IO.Path.Join(Root, "UnityProj/GameCfg");     // 配置文件目录
static string Xls  => System.IO.Path.Join(Root, "Design/Data");           // Excel 表格目录
```

所有路径都基于 `Application.dataPath`（Assets 目录）动态计算，不硬编码绝对路径。这意味着：
- 团队成员把项目放在不同磁盘都能正常工作
- CI 构建机器上路径不同也没问题

---

## 总结

这个工具文件体现了一个完整的编辑器工具开发视角：

| 层次 | 工具/技术 | 目的 |
|------|----------|------|
| 工具栏集成 | UnityToolbarExtender + [InitializeOnLoad] | 减少菜单导航 |
| SVN 集成 | TortoiseSVN 命令行接口 | 版本控制一键操作 |
| 调试开关 | PlayerPrefs 持久化 + Toggle | 快速切换开发模式 |
| 时间控制 | Time.timeScale 滑块 | 调试动作和流程 |
| 资源监听 | AssetPostprocessor | 自动化构建触发 |
| 路径规范 | 基于 Application.dataPath | 跨机器兼容 |

好的编辑器工具是团队生产力的乘数。投入在工具上的每一小时，往往能为整个团队节省数十倍的时间。
