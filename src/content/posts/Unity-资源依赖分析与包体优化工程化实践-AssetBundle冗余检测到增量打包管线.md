---
title: Unity 资源依赖分析与包体优化工程化实践——从AssetBundle冗余检测到增量打包管线
published: 2026-05-13
description: "深入讲解 Unity 游戏包体优化的完整工程化方案，覆盖 AssetBundle 依赖图分析与可视化、资源冗余自动检测与裁剪、增量打包管线搭建、材质变体缩减策略、纹理压缩与图集重组，以及 CI/CD 集成的最佳实践。"
tags: [包体优化, AssetBundle, 资源管理, CI/CD, 性能优化, Addressables]
category: 资源管理
draft: false
---

## 一、包体优化的工程化思维

### 1.1 为什么需要工程化

中小团队常陷入的包体优化误区：

```
❌ 误区 1：「上线前一周集中优化」
  → 发现冗余 → 人工排查 → 修改配置 → 重新打包
  → 反复 5-6 轮，每次 1-2 天
  → 上线前还在改资源

❌ 误区 2：「每人都手动检查」
  → A 导入的资源 B 不知道
  → 同一张贴图被 3 个人同时导入
  → 最终包体里出现 3 份相同的纹理

❌ 误区 3：「只看总包体积，不看增量」
  → 版本 1.0: 200MB
  → 版本 1.1: 280MB（新增 80MB 但其中 40MB 是冗余）
  → 版本 1.2: 350MB（用户每次更新都要下载大量重复内容）
```

工程化方案的核心目标：

```
✅ 自动化：每次构建自动检测包体变更，阈值超限即告警
✅ 可视化：依赖图 + 冗余报告，一眼看清问题
✅ 增量可控：每次发布生成 diff，确保用户下载量最小化
✅ 可度量：建立包体预算制度，每个模块负责自己的空间
```

### 1.2 包体组成分析

```
典型手游包体构成（以 200MB 为例）：
  ┌────────────────────────────────────────────────┐
  │  纹理 (Texture)         70MB  ──  35%          │
  ├────────────────────────────────────────────────┤
  │  模型网格 (Mesh)         30MB  ──  15%          │
  ├────────────────────────────────────────────────┤
  │  动画 (Animation)        20MB  ──  10%          │
  ├────────────────────────────────────────────────┤
  │  音频 (Audio)            25MB  ──  12.5%        │
  ├────────────────────────────────────────────────┤
  │  Lua/脚本 (Script)        5MB  ──  2.5%         │
  ├────────────────────────────────────────────────┤
  │  UI (图集)                20MB  ──  10%          │
  ├────────────────────────────────────────────────┤
  │  Shader                  10MB  ──  5%           │
  ├────────────────────────────────────────────────┤
  │  其他 (配置/场景等)       20MB  ──  10%          │
  ├────────────────────────────────────────────────┤
  │  冗余资源（重复）         20MB  ──  10% ❌      │
  └────────────────────────────────────────────────┘
```

## 二、AssetBundle 依赖图分析与可视化

### 2.1 依赖图数据结构

```csharp
/// <summary>依赖图节点——代表一个资源或 AssetBundle</summary>
public class DependencyNode
{
    public string AssetPath;          // 资源路径（如 Assets/Characters/Hero.fbx）
    public string BundleName;         // 所属 Bundle 名
    public long SizeBytes;            // 资源大小
    public string Type;               // 资源类型（Texture/Mesh/Material/Animation/...）
    public HashSet<string> References; // 被哪些上层资源引用
    public HashSet<string> Dependencies; // 依赖哪些下层资源
    public int ReferenceCount;        // 引用计数
}

/// <summary>依赖图——完整资源依赖关系</summary>
public class DependencyGraph
{
    public Dictionary<string, DependencyNode> Nodes = new();
    public List<string> RootNodes;    // 未被引用的独立资源

    /// <summary>计算每个资源被多少个不同 Bundle 引用</summary>
    public Dictionary<string, int> GetBundleCrossReferenceCounts()
    {
        var counts = new Dictionary<string, int>();
        foreach (var node in Nodes.Values)
        {
            if (node.References.Count <= 1) continue;

            // 统计引用该资源的 Bundle 数
            var bundleSet = new HashSet<string>();
            foreach (var refPath in node.References)
            {
                if (Nodes.TryGetValue(refPath, out var refNode))
                    bundleSet.Add(refNode.BundleName);
            }
            if (bundleSet.Count > 1)
                counts[node.AssetPath] = bundleSet.Count;
        }
        return counts;
    }

    /// <summary>找出冗余资源（多个 Bundle 包含相同资源）</summary>
    public List<RedundantResource> FindRedundantResources()
    {
        var redundants = new List<RedundantResource>();

        foreach (var (path, node) in Nodes)
        {
            if (node.References.Count <= 1) continue;

            var bundleSet = new HashSet<string>();
            foreach (var refPath in node.References)
            {
                if (Nodes.TryGetValue(refPath, out var refNode))
                    bundleSet.Add(refNode.BundleName);
            }

            if (bundleSet.Count > 1)
            {
                redundants.Add(new RedundantResource
                {
                    AssetPath = path,
                    AssetType = node.Type,
                    SizeBytes = node.SizeBytes,
                    ContainingBundles = bundleSet.ToList(),
                    BundleCrossCount = bundleSet.Count
                });
            }
        }

        return redundants.OrderByDescending(r => r.SizeBytes * (r.BundleCrossCount - 1)).ToList();
    }
}

public class RedundantResource
{
    public string AssetPath;
    public string AssetType;
    public long SizeBytes;
    public List<string> ContainingBundles;
    public int BundleCrossCount;

    public long WastedBytes => SizeBytes * (BundleCrossCount - 1);
    public string WastedSizeMB => $"{(double)WastedBytes / (1024 * 1024):F2} MB";
}
```

### 2.2 构建依赖图：编辑器工具

```csharp
using UnityEditor;
using System.IO;

/// <summary>依赖图构建器——Editor 工具</summary>
public static class DependencyGraphBuilder
{
    /// <summary>基于 AssetBundle 构建依赖图</summary>
    public static DependencyGraph BuildFromAssetBundles()
    {
        var graph = new DependencyGraph();

        // ── 获取所有 AssetBundle 名称 ──
        string[] bundleNames = AssetDatabase.GetAllAssetBundleNames();

        foreach (string bundleName in bundleNames)
        {
            // ── 获取该 Bundle 中的所有资源路径 ──
            string[] assetPaths = AssetDatabase.GetAssetPathsFromAssetBundle(bundleName);

            foreach (string assetPath in assetPaths)
            {
                var node = GetOrCreateNode(graph, assetPath);
                node.BundleName = bundleName;

                // ── 获取该资源的直接依赖 ──
                string[] deps = AssetDatabase.GetDependencies(assetPath, recursive: false);

                foreach (string depPath in deps)
                {
                    if (depPath == assetPath) continue;

                    var depNode = GetOrCreateNode(graph, depPath);
                    depNode.BundleName ??= GetImplicitBundle(depPath);

                    // 建立双向引用关系
                    node.Dependencies.Add(depPath);
                    depNode.References.Add(assetPath);
                }

                // ── 计算资源大小 ──
                node.SizeBytes = GetAssetSize(assetPath);
            }
        }

        return graph;
    }

    private static DependencyNode GetOrCreateNode(DependencyGraph graph, string path)
    {
        if (!graph.Nodes.TryGetValue(path, out var node))
        {
            node = new DependencyNode
            {
                AssetPath = path,
                Type = Path.GetExtension(path).ToLower() switch
                {
                    ".png" or ".jpg" or ".tga" or ".psd" or ".tif" => "Texture",
                    ".fbx" or ".obj" or ".blend" => "Mesh",
                    ".mat" => "Material",
                    ".anim" or ".controller" => "Animation",
                    ".shader" or ".shadergraph" => "Shader",
                    ".asset" => "ScriptableObject",
                    ".prefab" => "Prefab",
                    ".mp3" or ".wav" or ".ogg" => "Audio",
                    _ => "Other"
                }
            };
            graph.Nodes[path] = node;
        }
        return node;
    }

    private static string GetImplicitBundle(string assetPath)
    {
        // 未显式标记 Bundle 的资源会被 Unity 自动打入引用它的 Bundle
        // 如果有多个 Bundle 引用，会被自动复制
        return "[Implicit]";
    }

    private static long GetAssetSize(string assetPath)
    {
        // 使用 AssetDatabase 获取资源的原始大小
        var asset = AssetDatabase.LoadMainAssetAtPath(assetPath);
        if (asset == null) return 0;

        string localPath = Application.dataPath + assetPath.Substring("Assets".Length);
        if (File.Exists(localPath))
            return new FileInfo(localPath).Length;

        return 0;
    }
}
```

### 2.3 依赖图可视化

```csharp
/// <summary>依赖图可视化——生成 DOT 格式供 Graphviz 渲染</summary>
public static class DependencyGraphVisualizer
{
    /// <summary>生成 DOT 文件</summary>
    public static string GenerateDOT(DependencyGraph graph, string outputPath)
    {
        var sb = new StringBuilder();
        sb.AppendLine("digraph AssetBundleDependencies {");
        sb.AppendLine("    rankdir=LR;");
        sb.AppendLine("    node [shape=box, style=filled, fontname=\"Arial\", fontsize=10];");
        sb.AppendLine();

        // ── 按 Bundle 分组着色 ──
        var bundleColors = new Dictionary<string, string>();
        string[] colors = { "#FF9999", "#99FF99", "#9999FF", "#FFFF99", "#FF99FF",
                            "#99FFFF", "#FFCC99", "#CC99FF", "#99FFCC", "#FF99CC" };
        int colorIdx = 0;

        foreach (var node in graph.Nodes.Values)
        {
            string bundle = node.BundleName ?? "Unassigned";
            if (!bundleColors.ContainsKey(bundle))
            {
                bundleColors[bundle] = colors[colorIdx % colors.Length];
                colorIdx++;
            }
        }

        // ── 输出节点 ──
        foreach (var (path, node) in graph.Nodes)
        {
            string label = Path.GetFileName(path);
            string color = bundleColors[node.BundleName ?? "Unassigned"];
            string sizeMB = $"{(double)node.SizeBytes / (1024 * 1024):F2}MB";

            sb.AppendLine($"    \"{path}\" [label=\"{label}\\n{sizeMB}\\n{node.Type}\", fillcolor=\"{color}\"];");
        }

        sb.AppendLine();

        // ── 输出边 ──
        foreach (var (path, node) in graph.Nodes)
        {
            foreach (string dep in node.Dependencies)
            {
                if (graph.Nodes.ContainsKey(dep))
                    sb.AppendLine($"    \"{path}\" -> \"{dep}\";");
            }
        }

        sb.AppendLine("}");

        File.WriteAllText(outputPath, sb.ToString());

        // 如果有 Graphviz，可以直接渲染
        // Process.Start("dot", $"-Tpng {outputPath} -o {outputPath}.png");

        return outputPath;
    }
}
```

### 2.4 冗余检测报告生成

```csharp
/// <summary>冗余资源检测器——生成详细的优化建议报告</summary>
public static class RedundancyAnalyzer
{
    public static string GenerateReport(DependencyGraph graph)
    {
        var redundants = graph.FindRedundantResources();
        long totalWasted = redundants.Sum(r => r.WastedBytes);
        long totalSize = graph.Nodes.Values.Sum(n => n.SizeBytes);

        var sb = new StringBuilder();
        sb.AppendLine("══════════════════════════════════════════════");
        sb.AppendLine("       Unity 资源冗余检测报告");
        sb.AppendLine($"       生成时间: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine("══════════════════════════════════════════════");
        sb.AppendLine();
        sb.AppendLine($"总资源数: {graph.Nodes.Count}");
        sb.AppendLine($"总资源大小: {(double)totalSize / (1024 * 1024):F2} MB");
        sb.AppendLine($"冗余浪费: {(double)totalWasted / (1024 * 1024):F2} MB ({100.0 * totalWasted / totalSize:F1}%)");
        sb.AppendLine($"冗余资源数: {redundants.Count}");
        sb.AppendLine();

        // ── Top 20 冗余资源 ──
        sb.AppendLine("─── Top 20 冗余资源（按浪费量排序）───");
        sb.AppendLine($"{"资源路径",-60} {"类型",-12} {"大小",-8} {"跨Bundle数",-10} {"浪费",-8}");
        sb.AppendLine(new string('─', 110));

        foreach (var r in redundants.Take(20))
        {
            string shortPath = r.AssetPath.Length > 55
                ? "..." + r.AssetPath[^52..]
                : r.AssetPath;
            sb.AppendLine($"{shortPath,-60} {r.AssetType,-12} {r.SizeBytes / 1024,6}KB {r.BundleCrossCount,8}x  {r.WastedSizeMB,-8}");
        }

        sb.AppendLine();
        sb.AppendLine("─── 按 Bundle 分组冗余统计 ───");
        var bundleStats = redundants
            .SelectMany(r => r.ContainingBundles)
            .GroupBy(b => b)
            .Select(g => new { Bundle = g.Key, Count = g.Count() })
            .OrderByDescending(s => s.Count);

        foreach (var stat in bundleStats)
        {
            sb.AppendLine($"  {stat.Bundle,-40} {stat.Count,4} 个冗余引用");
        }

        sb.AppendLine();
        sb.AppendLine("─── 优化建议 ───");
        sb.AppendLine("1. 将高频共享资源提取到公共 Shared Bundle");
        sb.AppendLine("2. 对跨 Bundle 引用使用 Global Manifest 管理");
        sb.AppendLine("3. 大纹理检查是否可降分辨率或改用压缩格式");
        sb.AppendLine("4. 考虑将重复资源替换为 AssetReference 间接引用");
        sb.AppendLine();

        return sb.ToString();
    }
}
```

## 三、资源冗余自动检测与裁剪

### 3.1 资源依赖图分析工具窗口

```csharp
public class DependencyAnalysisWindow : EditorWindow
{
    private DependencyGraph _graph;
    private List<RedundantResource> _redundants;
    private Vector2 _scrollPos;
    private string _searchFilter = "";

    [MenuItem("Tools/资源依赖分析/打开分析工具")]
    public static void Open() => GetWindow<DependencyAnalysisWindow>("资源依赖分析");

    private void OnGUI()
    {
        if (GUILayout.Button("重新分析依赖图", GUILayout.Height(40)))
        {
            AnalyzeDependencies();
        }

        if (_graph == null) return;

        EditorGUILayout.Space();
        EditorGUILayout.LabelField($"总资源数: {_graph.Nodes.Count}", EditorStyles.boldLabel);
        EditorGUILayout.LabelField($"冗余资源: {_redundants?.Count ?? 0}");

        // ── 搜索过滤 ──
        _searchFilter = EditorGUILayout.TextField("搜索资源", _searchFilter);

        // ── 冗余资源列表 ──
        _scrollPos = EditorGUILayout.BeginScrollView(_scrollPos);

        foreach (var redundant in _redundants ?? new List<RedundantResource>())
        {
            if (!string.IsNullOrEmpty(_searchFilter) &&
                !redundant.AssetPath.Contains(_searchFilter, StringComparison.OrdinalIgnoreCase))
                continue;

            EditorGUILayout.BeginHorizontal("box");

            EditorGUILayout.LabelField(Path.GetFileName(redundant.AssetPath),
                                       GUILayout.Width(200));
            EditorGUILayout.LabelField(redundant.AssetType, GUILayout.Width(80));
            EditorGUILayout.LabelField(redundant.WastedSizeMB, GUILayout.Width(80));
            EditorGUILayout.LabelField($"跨 {redundant.BundleCrossCount} 个 Bundle",
                                       GUILayout.Width(100));

            if (GUILayout.Button("高亮", GUILayout.Width(50)))
            {
                var asset = AssetDatabase.LoadMainAssetAtPath(redundant.AssetPath);
                if (asset) EditorGUIUtility.PingObject(asset);
            }

            if (GUILayout.Button("查看依赖", GUILayout.Width(70)))
            {
                ShowDependencyTree(redundant.AssetPath);
            }

            EditorGUILayout.EndHorizontal();
        }

        EditorGUILayout.EndScrollView();
    }

    private void AnalyzeDependencies()
    {
        _graph = DependencyGraphBuilder.BuildFromAssetBundles();
        _redundants = _graph.FindRedundantResources();
        Debug.Log($"依赖分析完成，发现 {_redundants.Count} 个冗余资源，" +
                  $"预估可节省 {_redundants.Sum(r => r.WastedBytes) / (1024 * 1024):F2} MB");
    }
}
```

### 3.2 自动冗余修复脚本

```csharp
/// <summary>自动修复冗余——将跨 Bundle 引用的资源提取到公共 Shared Bundle</summary>
public static class RedundancyAutoFixer
{
    /// <summary>自动将高频冗余资源分配到 Shared Bundle</summary>
    public static void AutoAssignSharedBundles(
        DependencyGraph graph,
        long minWastedThreshold = 1024 * 1024, // 1MB 以上的才处理
        int minCrossCount = 2)
    {
        var redundants = graph.FindRedundantResources()
            .Where(r => r.BundleCrossCount >= minCrossCount)
            .Where(r => r.WastedBytes >= minWastedThreshold)
            .ToList();

        int assigned = 0;
        foreach (var r in redundants)
        {
            // 生成共享 Bundle 名称
            string sharedBundleName = $"shared/{r.AssetType.ToLower()}_shared";

            // 设置 AssetBundle 名称
            var importer = AssetImporter.GetAtPath(r.AssetPath);
            if (importer != null)
            {
                importer.assetBundleName = sharedBundleName;
                importer.SaveAndReimport();
                assigned++;
            }
        }

        Debug.Log($"已将 {assigned} 个冗余资源分配到共享 Bundle，" +
                  $"预计节省 {redundants.Sum(r => r.WastedBytes) / (1024 * 1024):F2} MB");
    }

    /// <summary>删除无引用的孤立资源</summary>
    public static void CleanupOrphanAssets(DependencyGraph graph)
    {
        int removed = 0;
        long freedBytes = 0;

        foreach (var (path, node) in graph.Nodes)
        {
            // 根节点 = 无引用
            if (node.References.Count == 0 && !path.Contains("/_shared/"))
            {
                // 不是手动标记的资源，确认无引用后删除
                if (EditorUtility.DisplayDialog("删除孤立资源",
                        $"是否删除无引用资源:\n{path}\n大小: {node.SizeBytes / 1024}KB", "删除", "跳过"))
                {
                    AssetDatabase.DeleteAsset(path);
                    removed++;
                    freedBytes += node.SizeBytes;
                }
            }
        }

        Debug.Log($"删除了 {removed} 个孤立资源，释放 {(double)freedBytes / (1024 * 1024):F2} MB");
    }
}
```

## 四、材质变体与 Shader 变体缩减

### 4.1 Shader 变体收集与分析

```csharp
public class ShaderVariantAnalyzer
{
    /// <summary>统计项目中的 Shader 变体数量</summary>
    public static ShaderVariantReport AnalyzeShaderVariants()
    {
        var report = new ShaderVariantReport();

        // ── 遍历所有 Shader ──
        var shaderGuids = AssetDatabase.FindAssets("t:Shader");
        foreach (var guid in shaderGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(path);

            if (shader == null) continue;

            // 获取 Shader 的关键词
            string[] keywords = ShaderUtil.GetShaderVariantEntriesFiltered(
                shader, ShaderUtil.GetAllShaderVariants(), out int totalVariants);

            report.ShaderEntries.Add(new ShaderEntry
            {
                ShaderPath = path,
                ShaderName = shader.name,
                KeywordCount = keywords.Length,
                TotalVariants = totalVariants,
                Keywords = keywords.ToList()
            });

            report.TotalVariants += totalVariants;
        }

        return report;
    }

    /// <summary>统计场景中用到的实际 Shader Variant</summary>
    public static HashSet<string> CollectUsedKeywords()
    {
        var usedKeywords = new HashSet<string>();

        // ── 遍历场景中的渲染器 ──
        var renderers = FindObjectsByType<Renderer>(FindObjectsSortMode.None);
        foreach (var renderer in renderers)
        {
            foreach (var mat in renderer.sharedMaterials)
            {
                if (mat == null || mat.shader == null) continue;

                // 获取该材质启用的关键词
                for (int i = 0; i < mat.enabledKeywords.Length; i++)
                {
                    usedKeywords.Add(mat.enabledKeywords[i].name);
                }
            }
        }

        return usedKeywords;
    }
}

public class ShaderVariantReport
{
    public List<ShaderEntry> ShaderEntries = new();
    public int TotalVariants;

    public string GenerateReport()
    {
        var sb = new StringBuilder();
        sb.AppendLine("─── Shader 变体分析报告 ───");
        sb.AppendLine($"总 Shader 数: {ShaderEntries.Count}");
        sb.AppendLine($"当前预编译总变体数: {TotalVariants}");
        sb.AppendLine();

        foreach (var entry in ShaderEntries.OrderByDescending(e => e.TotalVariants))
        {
            sb.AppendLine($"{entry.ShaderName,-40} {entry.TotalVariants,6} 变体  {entry.KeywordCount,3} 关键词");
        }

        return sb.ToString();
    }
}

public class ShaderEntry
{
    public string ShaderPath;
    public string ShaderName;
    public int KeywordCount;
    public int TotalVariants;
    public List<string> Keywords;
}
```

### 4.2 Shader 变体剥离策略

```csharp
/// <summary>Shader 变体剥离——自动移除未使用的变体</summary>
public static class ShaderVariantStripper
{
    /// <summary>基于场景使用情况，自动生成 ShaderVariantCollection</summary>
    [MenuItem("Tools/包体优化/自动生成 ShaderVariantCollection")]
    public static void AutoGenerateVariantCollection()
    {
        // ── 收集使用的关键词 ──
        var usedKeywords = ShaderVariantAnalyzer.CollectUsedKeywords();
        var unusedKeywords = GetAllKeywords()
            .Except(usedKeywords)
            .ToList();

        // ── 报告 ──
        Debug.Log($"使用的 Shader 关键词: {usedKeywords.Count}");
        Debug.Log($"未使用的 Shader 关键词: {unusedKeywords.Count}");

        if (unusedKeywords.Count > 0)
        {
            Debug.LogWarning($"以下关键词未在任何场景中使用:\n{string.Join(", ", unusedKeywords)}");
        }

        // ── 生成 Stripped Shader Variant Collection ──
        string outputPath = "Assets/Resources/ShaderVariants_Stripped.shadervariants";
        var collection = new ShaderVariantCollection();

        // 遍历所有 Shader，只包含使用到的变体
        var shaderGuids = AssetDatabase.FindAssets("t:Shader");
        foreach (var guid in shaderGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(path);
            if (shader == null) continue;

            // 获取 Shader 的所有 Pass
            for (int pass = 0; pass < shader.passCount; pass++)
            {
                var variants = ShaderUtil.GetShaderVariantEntries(shader, pass,
                    ShaderUtil.GetAllShaderVariants());

                foreach (var variant in variants)
                {
                    // 只包含使用时关键词的组合
                    if (variant.Keywords.All(k => usedKeywords.Contains(k)))
                    {
                        collection.Add(new ShaderVariantCollection.ShaderVariant(
                            shader, variant.PassType, variant.Keywords.ToArray()));
                    }
                }
            }
        }

        AssetDatabase.CreateAsset(collection, outputPath);
        AssetDatabase.SaveAssets();
        Debug.Log($"生成的 ShaderVariantCollection 包含 {collection.variantCount} 个变体");
    }

    /// <summary>获取项目中所有可能出现的 Shader 关键词</summary>
    private static HashSet<string> GetAllKeywords()
    {
        var all = new HashSet<string>();
        var shaderGuids = AssetDatabase.FindAssets("t:Shader");

        foreach (var guid in shaderGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string source = File.ReadAllText(path);

            // 提取 #pragma shader_feature / multi_compile 中的关键词
            var matches = System.Text.RegularExpressions.Regex.Matches(
                source, @"#pragma\s+(shader_feature|multi_compile)\s+(.+)");
            foreach (System.Text.RegularExpressions.Match m in matches)
            {
                var keywords = m.Groups[2].Value
                    .Replace("_", "")
                    .Split(' ', StringSplitOptions.RemoveEmptyEntries);
                foreach (var kw in keywords)
                {
                    if (!kw.StartsWith("multi_compile") && kw != "")
                        all.Add(kw);
                }
            }
        }

        return all;
    }
}
```

### 4.3 材质变体合并（Material Variant Reduction）

```csharp
/// <summary>材质变体分析——找出可通过属性参数化的冗余材质</summary>
public static class MaterialVariantAnalyzer
{
    /// <summary>分析项目中所有材质，按 Shader + 属性组合聚类</summary>
    public static MaterialClusterReport Analyze()
    {
        var report = new MaterialClusterReport();
        var materialPaths = AssetDatabase.FindAssets("t:Material")
            .Select(AssetDatabase.GUIDToAssetPath);

        // ── 按 Shader 聚类 ──
        var shaderGroups = new Dictionary<string, List<MaterialInfo>>();

        foreach (string path in materialPaths)
        {
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat == null || mat.shader == null) continue;

            string shaderName = mat.shader.name;

            // 提取材质的关键属性
            var info = new MaterialInfo
            {
                Path = path,
                ShaderName = shaderName,
                UsedProperties = ExtractMaterialProperties(mat),
                SizeBytes = GetTextureSize(mat),
            };

            if (!shaderGroups.ContainsKey(shaderName))
                shaderGroups[shaderName] = new List<MaterialInfo>();
            shaderGroups[shaderName].Add(info);
        }

        // ── 检测可合并的材质 ──
        foreach (var (shader, materials) in shaderGroups)
        {
            // 找出只有贴图引用不同的材质
            var textureDiffs = new Dictionary<string, List<MaterialInfo>>();
            foreach (var mat in materials)
            {
                string textureSig = string.Join("|",
                    mat.UsedProperties
                       .Where(p => p.StartsWith("_Tex") || p.Contains("Map"))
                       .Select(p =>
                       {
                           var tex = AssetDatabase.LoadAssetAtPath<Texture>(
                               mat.Path.Replace(".mat", ".png"));
                           return tex ? tex.name : "null";
                       }));

                if (!textureDiffs.ContainsKey(textureSig))
                    textureDiffs[textureSig] = new List<MaterialInfo>();
                textureDiffs[textureSig].Add(mat);
            }

            // 报告可合并的候选
            foreach (var (sig, mats) in textureDiffs)
            {
                if (mats.Count > 1)
                {
                    report.MergeCandidates.Add(new MaterialMergeCandidate
                    {
                        ShaderName = shader,
                        MaterialCount = mats.Count,
                        MergeKey = sig,
                        TotalSizeBytes = mats.Sum(m => m.SizeBytes),
                        Materials = mats.Select(m => m.Path).ToList()
                    });
                }
            }
        }

        return report;
    }
}

public class MaterialMergeCandidate
{
    public string ShaderName;
    public int MaterialCount;
    public string MergeKey;
    public long TotalSizeBytes;
    public List<string> Materials;
}

public class MaterialClusterReport
{
    public List<MaterialMergeCandidate> MergeCandidates = new();

    public string GenerateReport()
    {
        var sb = new StringBuilder();
        sb.AppendLine("─── 材质变体合并建议 ───");

        foreach (var candidate in MergeCandidates.OrderByDescending(c => c.TotalSizeBytes))
        {
            sb.AppendLine($"Shader: {candidate.ShaderName}");
            sb.AppendLine($"  可合并材质数: {candidate.MaterialCount}");
            sb.AppendLine($"  总大小: {(double)candidate.TotalSizeBytes / (1024 * 1024):F2} MB");
            sb.AppendLine($"  建议: 使用 MaterialPropertyBlock 统一控制");
            sb.AppendLine();
        }

        return sb.ToString();
    }
}
```

## 五、纹理压缩与图集优化

### 5.1 纹理压缩检测

```csharp
/// <summary>纹理压缩审计——自动检测可优化的纹理</summary>
public static class TextureAuditor
{
    public static TextureAuditReport AuditAllTextures()
    {
        var report = new TextureAuditReport();
        var textureGuids = AssetDatabase.FindAssets("t:Texture");

        foreach (var guid in textureGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;

            var info = new TextureInfo
            {
                Path = path,
                Format = importer.textureFormat.ToString(),
                MaxSize = importer.maxTextureSize,
                IsReadable = importer.isReadable,
                HasMipMaps = importer.mipmapEnabled,
                CompressionType = GetCompressionType(importer),
            };

            // 检查原始大小
            var asset = AssetDatabase.LoadAssetAtPath<Texture>(path);
            if (asset != null)
            {
                info.Width = asset.width;
                info.Height = asset.height;
                info.SizeBytes = TextureUtil.GetStorageMemorySize(asset);

                // 获取 DXT/ETC 压缩后的大小估算
                info.CompressedSizeBytes = EstimateCompressedSize(
                    info.Width, info.Height, info.CompressionType, info.HasMipMaps);
                info.PotentialSavings = info.SizeBytes - info.CompressedSizeBytes;

                report.TotalOriginalSize += info.SizeBytes;
                report.TotalCompressedSize += info.CompressedSizeBytes;
            }

            // ── 检测问题 ──
            if (importer.isReadable)
                report.ReadableTextures.Add(info);

            // 检测过大纹理
            if (info.MaxSize > 1024 && !path.Contains("_ui/"))
                report.OverSizedTextures.Add(info);

            // 检测 2 的幂次方
            if (!IsPowerOfTwo(info.Width) || !IsPowerOfTwo(info.Height))
                report.NonPowerOfTwo.Add(info);

            report.AllTextures.Add(info);
        }

        return report;
    }

    private static long EstimateCompressedSize(
        int width, int height, string format, bool hasMips)
    {
        int mipCount = hasMips ? (int)Mathf.Floor(Mathf.Log(Mathf.Max(width, height), 2)) + 1 : 1;
        long total = 0;

        for (int mip = 0; mip < mipCount; mip++)
        {
            int mipW = Mathf.Max(1, width >> mip);
            int mipH = Mathf.Max(1, height >> mip);

            // 不同格式的每像素位数
            float bpp = format switch
            {
                "DXT1" or "BC1" or "ETC_RGB4" => 4,
                "DXT5" or "BC3" or "ETC2_RGBA8" => 8,
                "ASTC_4x4" => 8,
                "ASTC_6x6" => 3.56f,
                "ASTC_8x8" => 2,
                "ASTC_12x12" => 0.89f,
                _ => 32 // fallback: RGBA32
            };

            total += (long)((mipW * mipH * bpp) / 8);
        }

        return total;
    }

    private static bool IsPowerOfTwo(int x) => (x & (x - 1)) == 0 && x > 0;
}
```

### 5.2 自动纹理格式推荐

```csharp
/// <summary>根据纹理用途自动推荐压缩格式</summary>
public static class TextureFormatRecommender
{
    public enum TextureUseCase
    {
        UI_Atlas,
        UI_Icon,
        Scene_Diffuse,
        Scene_Normal,
        Scene_Mask,
        Character_Diffuse,
        Character_Normal,
        Terrain_Albedo,
        Lightmap,
    }

    public struct FormatRecommendation
    {
        public TextureImporterFormat Android;
        public TextureImporterFormat iOS;
        public int MaxSize;
        public bool UseMipMaps;
        public string Reason;
    }

    public static FormatRecommendation Recommend(TextureUseCase useCase, int originalSize)
    {
        return useCase switch
        {
            TextureUseCase.UI_Atlas => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC2_RGBA8,
                iOS = TextureImporterFormat.ASTC_6x6,
                MaxSize = Mathf.Min(2048, originalSize),
                UseMipMaps = false,
                Reason = "UI 不需要 MipMap，ETC2/ASTC 提供良好质量"
            },
            TextureUseCase.UI_Icon => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC2_RGBA8,
                iOS = TextureImporterFormat.ASTC_8x8,
                MaxSize = Mathf.Min(256, originalSize),
                UseMipMaps = false,
                Reason = "图标尺寸小，ASTC_8x8 提供更好的压缩比"
            },
            TextureUseCase.Scene_Diffuse => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC_RGB4,
                iOS = TextureImporterFormat.ASTC_6x6,
                MaxSize = Mathf.Min(1024, originalSize),
                UseMipMaps = true,
                Reason = "场景漫反射不需要 Alpha，ETC_RGB4 效率最高"
            },
            TextureUseCase.Scene_Normal => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC2_RGBA8,
                iOS = TextureImporterFormat.ASTC_6x6,
                MaxSize = Mathf.Min(1024, originalSize),
                UseMipMaps = true,
                Reason = "法线贴图需要高质量压缩，避免视觉瑕疵"
            },
            TextureUseCase.Lightmap => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC_RGB4,
                iOS = TextureImporterFormat.ASTC_6x6,
                MaxSize = Mathf.Min(1024, originalSize),
                UseMipMaps = false,
                Reason = "Lightmap 不需要 MipMap"
            },
            _ => new FormatRecommendation
            {
                Android = TextureImporterFormat.ETC2_RGBA8,
                iOS = TextureImporterFormat.ASTC_6x6,
                MaxSize = Mathf.Min(1024, originalSize),
                UseMipMaps = true,
                Reason = "默认推荐，平衡质量与尺寸"
            }
        };
    }

    [MenuItem("Tools/包体优化/批量应用纹理推荐格式")]
    public static void ApplyRecommendedFormats()
    {
        int updated = 0;
        long estimatedSavings = 0;
        var textureGuids = AssetDatabase.FindAssets("t:Texture");

        foreach (var guid in textureGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;

            // 根据路径判断用途
            var useCase = DetectUseCase(path);
            var recommendation = Recommend(useCase, importer.maxTextureSize);

            bool changed = false;

            // Android 设置
            var androidSettings = importer.GetPlatformTextureSettings("Android");
            if (androidSettings.overridden == false ||
                androidSettings.format != recommendation.Android ||
                androidSettings.maxTextureSize != recommendation.MaxSize)
            {
                androidSettings.overridden = true;
                androidSettings.format = recommendation.Android;
                androidSettings.maxTextureSize = recommendation.MaxSize;
                importer.SetPlatformTextureSettings(androidSettings);
                changed = true;
            }

            // iOS 设置
            var iosSettings = importer.GetPlatformTextureSettings("iPhone");
            if (iosSettings.overridden == false ||
                iosSettings.format != recommendation.iOS ||
                iosSettings.maxTextureSize != recommendation.MaxSize)
            {
                iosSettings.overridden = true;
                iosSettings.format = recommendation.iOS;
                iosSettings.maxTextureSize = recommendation.MaxSize;
                importer.SetPlatformTextureSettings(iosSettings);
                changed = true;
            }

            if (changed)
            {
                importer.SaveAndReimport();
                updated++;
            }
        }

        Debug.Log($"已更新 {updated} 个纹理的压缩格式");
    }

    private static TextureUseCase DetectUseCase(string path)
    {
        if (path.Contains("/UI/") || path.Contains("/ui/"))
            return path.Contains("Icon") ? TextureUseCase.UI_Icon : TextureUseCase.UI_Atlas;
        if (path.Contains("/Characters/") || path.Contains("/character/"))
            return path.Contains("Normal") ? TextureUseCase.Character_Normal
                                           : TextureUseCase.Character_Diffuse;
        if (path.Contains("/Terrain/") || path.Contains("/terrain/"))
            return TextureUseCase.Terrain_Albedo;
        if (path.Contains("/Lightmap") || path.Contains("/lightmap"))
            return TextureUseCase.Lightmap;

        return TextureUseCase.Scene_Diffuse;
    }
}
```

## 六、增量打包管线

### 6.1 包体差异比较

```csharp
/// <summary>包体版本差异比较——追踪每次构建的包体变化</summary>
[Serializable]
public class BuildDiffReport
{
    public string PreviousBuildPath;
    public string CurrentBuildPath;
    public DateTime Timestamp;
    public long PreviousTotalSize;
    public long CurrentTotalSize;
    public List<BundleDiffEntry> Changes = new();
}

[Serializable]
public class BundleDiffEntry
{
    public string BundleName;
    public long PreviousSize;
    public long CurrentSize;
    public long Delta => CurrentSize - PreviousSize;
    public float DeltaPercent => PreviousSize > 0 ? (float)Delta / PreviousSize * 100 : 0;
    public string Status => Delta switch
    {
        > 0 => $"↑ +{Delta / 1024}KB ({DeltaPercent:F1}%)",
        < 0 => $"↓ {Delta / 1024}KB ({DeltaPercent:F1}%)",
        _ => "— 不变"
    };
}

/// <summary>构建差异分析器</summary>
public static class BuildDiffAnalyzer
{
    private const string DiffReportPath = "Library/BuildDiffHistory.json";

    public static BuildDiffReport CompareWithPrevious(string buildOutputPath)
    {
        var report = new BuildDiffReport
        {
            Timestamp = DateTime.Now,
            CurrentBuildPath = buildOutputPath
        };

        // ── 读取前次构建记录 ──
        BuildDiffReport previous = null;
        if (File.Exists(DiffReportPath))
        {
            previous = JsonUtility.FromJson<BuildDiffReport>(
                File.ReadAllText(DiffReportPath));
        }

        // ── 分析当前构建 ──
        string[] bundles = Directory.GetFiles(buildOutputPath, "*.bundle",
            SearchOption.AllDirectories);

        var currentSizes = new Dictionary<string, long>();
        foreach (var bundle in bundles)
        {
            var info = new FileInfo(bundle);
            string name = Path.GetFileName(bundle);
            currentSizes[name] = info.Length;
            report.CurrentTotalSize += info.Length;
        }

        // ── 与上次对比 ──
        if (previous != null)
        {
            // 解析上次构建的 Bundle 大小
            var previousSizes = new Dictionary<string, long>();
            // 从 previous 记录重建 ...

            foreach (var (name, size) in currentSizes)
            {
                previousSizes.TryGetValue(name, out long prevSize);
                report.Changes.Add(new BundleDiffEntry
                {
                    BundleName = name,
                    PreviousSize = prevSize,
                    CurrentSize = size
                });
            }

            report.PreviousTotalSize = previous.CurrentTotalSize;
        }
        else
        {
            // 首次构建
            foreach (var (name, size) in currentSizes)
            {
                report.Changes.Add(new BundleDiffEntry
                {
                    BundleName = name,
                    PreviousSize = 0,
                    CurrentSize = size
                });
            }
        }

        // ── 保存当前记录 ──
        File.WriteAllText(DiffReportPath, JsonUtility.ToJson(report, true));

        return report;
    }
}
```

### 6.2 CI/CD 集成——自动化检测与告警

```yaml
# .gitlab-ci.yml 中的包体检查任务示例
package-size-check:
  stage: quality
  script:
    # 1. 构建 AssetBundle
    - /opt/unity/Editor/Unity -quit -batchmode -executeMethod BuildPipeline.BuildAssetBundles
    
    # 2. 运行依赖分析
    - /opt/unity/Editor/Unity -quit -batchmode -executeMethod DependencyAnalysisWindow.AnalyzeDependencies
    
    # 3. 生成包体报告
    - /opt/unity/Editor/Unity -quit -batchmode -executeMethod BuildDiffAnalyzer.GenerateReport
    
    # 4. 阈值检查
    - python3 check_size_threshold.py --build-dir Build/Bundles --threshold 300MB
    
    # 5. 上传报告
    - upload_report Build/SizeReport.html
  only:
    - develop
    - release/*
```

```csharp
/// <summary>CI 模式下的包体检查</summary>
public static class CISizeChecker
{
    [MenuItem("Tools/CI/包体阈值检查")]
    public static void CheckSizeThreshold()
    {
        string buildDir = "Build/Bundles";
        string reportPath = "Build/SizeReport.json";

        // 比较差异
        var diff = BuildDiffAnalyzer.CompareWithPrevious(buildDir);

        // 阈值检测
        long thresholdMB = 300;
        long totalMB = diff.CurrentTotalSize / (1024 * 1024);

        if (totalMB > thresholdMB)
        {
            Debug.LogError($"❌ 包体超限！当前 {totalMB}MB > 阈值 {thresholdMB}MB");
            Environment.Exit(1);
        }

        // 检测是否有大增量
        foreach (var change in diff.Changes.OrderByDescending(c => c.Delta).Take(10))
        {
            if (change.Delta > 5 * 1024 * 1024) // 单个 Bundle 增加超过 5MB
            {
                Debug.LogWarning($"⚠️ {change.BundleName} 增加了 {change.Delta / 1024}KB");
            }
        }

        Debug.Log($"✅ 包体检查通过: 总大小 {totalMB}MB，较上次 {'+' if diff.CurrentTotalSize >= diff.PreviousTotalSize else '-'}{(diff.CurrentTotalSize - diff.PreviousTotalSize) / (1024 * 1024)}MB");

        // 保存报告
        File.WriteAllText(reportPath, JsonUtility.ToJson(diff, true));
    }
}
```

## 七、最佳实践总结

### 7.1 包体预算制度

```
✅ 推荐的分级预算管理：

  总包体预算: 300MB
  │
  ├─ 核心包（安装包）: 150MB
  │   ├─ 引擎/插件: 30MB
  │   ├─ 基础 UI: 20MB
  │   ├─ 核心角色: 40MB
  │   ├─ 公共场景: 30MB
  │   └─ 公共资源: 30MB
  │
  └─ 可下载资源包: 150MB
      ├─ 高清贴图: 50MB
      ├─ 过场动画: 30MB
      ├─ 高精度模型: 40MB
      └─ 音频包: 30MB
```

### 7.2 优化优先级金字塔

```
          ╱──────────────────────╲
         ╱   高收益 · 低成本     ╲       ← 先做
        ╱──────────────────────────╲
       ╱  Shader Variant 剥离       ╲   ← 1 行配置省 30MB
      ╱  Texture 压缩格式优化        ╲  ← 脚本批量执行省 50MB
     ╱────────────────────────────────╲
    ╱   中收益 · 中成本              ╲
   ╱  AssetBundle 冗余检测与合并      ╲ ← 工具分析，手动调整
  ╱  Material 变体合并               ╲  ← 自动检测，重构工作流
 ╱────────────────────────────────────╲
╱   低收益 · 高成本                  ╲   ← 后做
╱  图集重组（涉及美术工作流变更）      ╲
╱  模型 LOD 重新生成                 ╲
╱  音频重新编码                     ╲
```

### 7.3 工程化检查清单

```
□ 每次提交是否自动运行依赖分析？
□ 是否有包体阈值告警（CI 失败）？
□ 是否有 ShaderVariantCollection 且定期更新？
□ 纹理是否按平台设置了正确压缩格式？
□ 是否所有纹理都关闭了 Readable 标记？
□ 是否有冗余资源自动检测报表？
□ 是否建立了包体预算制度并落实到人？
□ 新增资源是否有 Review 流程？
□ 增量补丁包是否有大小跟踪？
```

### 7.4 常见问题 FAQ

```
Q: 如何找出哪些资源被多个 Bundle 引用？
A: 使用 DependencyGraph.GetBundleCrossReferenceCounts() 检测跨 Bundle 引用

Q: Shared Bundle 应该放什么？
A: 高频共用资源：通用纹理、公共材质、常用 Shader、通用网格

Q: Shader 变体太多怎么办？
A: 三步法：
   1. 收集场景实际使用的变体（AutoGenerateVariantCollection）
   2. 移除未使用的 multi_compile 关键词
   3. 将 shader_feature 改为 multi_compile_local 减少组合

Q: 纹理压缩后视觉效果变差如何检查？
A: 使用 Editor 的 Texture Inspector 在各平台预览模式查看

Q: 增量更新用户下载量如何最小化？
A: 
   1. 保持 Bundle 粒度适中（不宜过大也不宜过小）
   2. 避免公共资源频繁修改
   3. 使用 Chunk-Based 压缩（LZ4/LZ4HC）
   4. CDN 开启增量同步支持
```

---

**参考资源：**
- Unity Manual: AssetBundle 依赖管理
- 《Unity 游戏优化》第 3 版 - Chapter 6: 包体优化
- Unite 演讲: Large Scale Asset Management in Unity
- Addressables 源码分析：依赖图构建
- 腾讯游戏客户端包体优化白皮书