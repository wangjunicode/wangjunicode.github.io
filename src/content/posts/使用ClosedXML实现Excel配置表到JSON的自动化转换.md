---
title: 使用 ClosedXML 实现 Excel 配置表到 JSON 的自动化转换
published: 2026-03-31
description: 深入解析 Excel 配置表导出工具的实现原理，理解 ClosedXML 读取 xlsx 数据、Sheet 解析和 JSON 序列化的工程流程。
tags: [Unity, 编辑器工具, 配置表, 数据导出]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 策划表格与程序的鸿沟

游戏开发中，策划用 Excel 表格定义游戏数据：角色属性、技能配置、关卡设计……但程序读取的是 JSON 或二进制格式。

这中间需要一个"翻译"工具，把策划熟悉的表格格式转换成程序可以加载的数据格式，这就是**配置表导出工具**（打表工具）。

---

## ExcelTool 的完整实现

```csharp
public class ExcelTool
{
    // 配置：Excel 文件名 → Sheet 名称列表
    public static Dictionary<string, List<string>> excel_files = new()
    {
        { "VirtualSkeletonPoint.xlsx", new List<string>() { "CharacterEffectVP|特效挂点" } },
        { "StoryCharacter.xlsx", new List<string>() { "Character", "StoryItem" } },
        { "Character.xlsx", new List<string>() { "Character" } },
    };
    
    // 菜单入口：在 Unity 菜单栏添加工具
    [MenuItem("xgame/特效/TTB相关excel转Json")]
    public static void ParseExcelToJsonOnlyTTB()
    {
        var dataPath = Application.dataPath;
        var clientPath = Path.GetDirectoryName(Path.GetDirectoryName(dataPath));
        
        foreach (var excelFile in excel_files)
        {
            string excelFileName = excelFile.Key;
            List<string> sheetNames = excelFile.Value;
            
            string xlsxPath = Path.Combine(clientPath, "Design", "Data", excelFileName);
            
            if (!File.Exists(xlsxPath))
            {
                Debug.LogWarning($"Excel 文件不存在: {xlsxPath}");
                continue;
            }
            
            excelFileName = excelFileName.Replace(".xlsx", "");
            foreach (var sheetName in sheetNames)
            {
                string json = XlsxToJson(xlsxPath, sheetName);
                if (!string.IsNullOrEmpty(json))
                {
                    string jsonPath = BuildOutputPath(excelFileName, sheetName);
                    SaveJsonToFile(json, jsonPath);
                }
            }
        }
    }
}
```

### 配置表解析核心：XlsxToJson

```csharp
public static string XlsxToJson(string filePath, string sheetName)
{
    try
    {
        using (var workbook = new XLWorkbook(filePath))
        {
            var worksheet = workbook.Worksheet(sheetName);
            if (worksheet == null)
            {
                Debug.LogError($"未找到名为 {sheetName} 的工作表");
                return null;
            }

            var tableData = new List<Dictionary<string, string>>();

            // 读取第一行作为列名（表头）
            var firstRow = worksheet.FirstRowUsed();
            var header = new List<string>();
            foreach (var cell in firstRow.Cells())
            {
                header.Add(cell.Value.ToString());
            }

            // 从第二行开始读取数据
            var rowCount = worksheet.RowsUsed().Count();
            for (int i = 2; i <= rowCount; i++)
            {
                var row = worksheet.Row(i);
                var rowData = new Dictionary<string, string>();
                for (int j = 1; j <= header.Count; j++)
                {
                    rowData[header[j - 1]] = row.Cell(j).Value.ToString();
                }
                tableData.Add(rowData);
            }

            return JsonConvert.SerializeObject(tableData);
        }
    }
    catch (Exception e)
    {
        Debug.LogError($"转换XLSX到JSON时出错: {e.Message}");
        return null;
    }
}
```

这个实现对应了一个非常标准的表格数据约定：
- **第一行是列名（表头）**
- **后续行是数据行**

输出格式是一个 JSON 数组，每个元素是一行数据，键是列名：

```json
[
  {"id": "1001", "name": "火球", "damage": "150"},
  {"id": "1002", "name": "冰锥", "damage": "120"}
]
```

---

## Sheet 名称的特殊约定

注意这个 Sheet 名称：`"CharacterEffectVP|特效挂点"`

`|` 后面是注释（中文说明），代码处理时会截取 `|` 前面的部分：

```csharp
var lastIndex = sheetName.LastIndexOf('|');
if (lastIndex != -1)
{
    var newSheet = sheetName.Substring(0, lastIndex);  // "CharacterEffectVP"
    var jsonFileName = $"{excelFileName}_{newSheet}.json";
}
```

这是一个对**策划友好**的设计：Sheet 名称可以加中文备注，方便策划理解，同时程序逻辑只看 `|` 前面的英文名。

---

## 更完善的表格设计规范

工业级的打表工具通常会有更多约定，常见设计：

### 多行表头

```
行1：字段名称（如 id, name, hp）
行2：字段类型（如 int, string, float）
行3：中文注释（如 编号, 名称, 血量）
行4 开始：数据
```

```csharp
// 读取表头（第1行类型，第2行字段名）
var typeRow = worksheet.Row(1);
var nameRow = worksheet.Row(2);
// 数据从第3行开始
for (int i = 3; i <= rowCount; i++) { ... }
```

### 过滤注释行和空行

```csharp
// 跳过以 # 开头的注释行
if (row.Cell(1).Value.ToString().StartsWith("#")) continue;
// 跳过空行
if (row.IsEmpty()) continue;
```

### 多语言支持

```
A列：key（程序用）
B列：zh-CN（中文）
C列：en-US（英文）
D列：ja-JP（日文）
```

---

## 工具链集成：ILRuntimeBuildGameClient 的工具栏

`ILRuntimeBuildGameClient.cs` 展示了如何把常用操作集成到 Unity 工具栏：

```csharp
[InitializeOnLoad]
public class ILRuntimeBuildGameClient : AssetPostprocessor
{
    static ILRuntimeBuildGameClient()
    {
        UnityToolbarExtender.ToolbarExtender.RightToolbarGUI.Add(OnToolbarGUI);
        UnityToolbarExtender.ToolbarExtender.LeftToolbarGUI.Add(OnLeftToolbarGUI);
    }
    
    static void OnToolbarGUI()
    {
        if (GUILayout.Button("提交")) { SvnCommand("commit", "提交"); }
        if (GUILayout.Button("更新")) { /* SVN Update */ }
        if (GUILayout.Button("分组&导表")) { UpdateInit(); }
        if (GUILayout.Button("开表")) { /* 弹出表格选择器 */ }
    }
}
```

工具栏按钮让日常工作（SVN 提交/更新、导表、开表）只需一键，不需要打开命令行或记忆菜单路径。

---

## 路径规划：项目结构的重要性

工具代码中定义了大量路径常量：

```csharp
static string Root    => Directory.GetParent(Path).Parent.ToString();
static string Cfg     => Path.Join(Root, "UnityProj/GameCfg");
static string Design  => Path.Join(Root, "Design");
static string Xls     => Path.Join(Design, "Data");
```

这体现了一个重要原则：**工具代码要感知项目目录结构**。

好的目录结构设计：
```
项目根目录/
├── Design/
│   └── Data/          ← 策划 Excel 表格
├── UnityProj/
│   ├── Assets/
│   │   └── Scripts/   ← 程序代码
│   └── GameCfg/       ← 导出的配置文件
```

所有工具都基于这个约定，不需要用户输入路径，减少出错可能性。

---

## 总结

这套打表工具展示了编辑器工具开发的核心要素：

| 要素 | 实现 |
|------|------|
| 入口集成 | `[MenuItem]` + 工具栏按钮 |
| 配置驱动 | 字典配置表格→Sheet 映射 |
| 表格解析 | ClosedXML 读取 + 行列遍历 |
| 数据序列化 | Newtonsoft.Json 转 JSON |
| 错误处理 | try-catch + Debug.LogError |
| 路径管理 | 基于项目根目录的静态路径 |

打表工具是项目中最先写也是最常用的编辑器工具之一，一个设计良好的打表流程能显著提升策划和程序的协作效率。
