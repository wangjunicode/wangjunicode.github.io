---
title: Unity 场景烘焙自动化工具：批量烘焙与烘焙质量控制
published: 2026-03-31
description: 深入解析场景烘焙自动化工具的设计，理解如何通过代码控制 Unity 的 Lightmapping API 实现批量烘焙、烘焙验证和数据管理。
tags: [Unity, 场景烘焙, 编辑器工具, 光照系统]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

## 手动烘焙的效率问题

Unity 的光照烘焙（Lightmapping）是游戏视觉质量的重要环节。但手动烘焙有以下问题：

1. **重复操作**：每次修改场景都需要手动点击"Bake"按钮
2. **烘焙参数不统一**：不同成员可能使用不同的烘焙设置，结果不一致
3. **批量烘焙效率低**：40个场景逐个烘焙，烘焙一次需要整整一天
4. **烘焙结果验证**：烘焙完成后需要人工检查是否有问题

编辑器工具可以解决这些问题。

---

## 批量烘焙工具实现

```csharp
public class SceneBakeTool
{
    // 预设的烘焙配置
    [Serializable]
    public class BakeSettings
    {
        public float IndirectIntensity = 1.0f;
        public float BounceBoost = 1.0f;
        public int MaxBounces = 2;
        public float LightmapResolution = 40f;  // texels per unit
        public LightmapsMode LightmapsMode = LightmapsMode.CombinedDirectional;
        public string Name;  // 预设名称（如 "高质量"、"快速预览"）
    }
    
    // 内置预设
    public static BakeSettings HighQualitySettings = new BakeSettings
    {
        IndirectIntensity = 1.2f,
        BounceBoost = 1.0f,
        MaxBounces = 3,
        LightmapResolution = 80f,
        Name = "高质量"
    };
    
    public static BakeSettings FastPreviewSettings = new BakeSettings
    {
        IndirectIntensity = 1.0f,
        BounceBoost = 1.0f,
        MaxBounces = 1,
        LightmapResolution = 20f,
        Name = "快速预览"
    };
    
    // 应用烘焙设置
    public static void ApplySettings(BakeSettings settings)
    {
        LightmapEditorSettings.lightmapper = LightmapEditorSettings.Lightmapper.ProgressiveCPU;
        Lightmapping.indirectOutputScale = settings.IndirectIntensity;
        Lightmapping.bounceBoost = settings.BounceBoost;
        LightmapEditorSettings.maxBounces = settings.MaxBounces;
        LightmapEditorSettings.bakeResolution = settings.LightmapResolution;
        LightmapEditorSettings.lightmapsMode = settings.LightmapsMode;
        
        Debug.Log($"已应用烘焙预设：{settings.Name}");
    }
    
    // 批量烘焙多个场景
    [MenuItem("Tools/场景烘焙/批量烘焙所有场景")]
    public static void BakeAllScenes()
    {
        string[] scenePaths = GetAllGameScenePaths();
        BakeScenesAsync(scenePaths).Coroutine();
    }
    
    private static async ETTask BakeScenesAsync(string[] scenePaths)
    {
        int total = scenePaths.Length;
        int success = 0;
        int failed = 0;
        
        for (int i = 0; i < total; i++)
        {
            string scenePath = scenePaths[i];
            EditorUtility.DisplayProgressBar(
                "批量烘焙", 
                $"正在烘焙: {Path.GetFileNameWithoutExtension(scenePath)} ({i+1}/{total})",
                (float)i / total);
            
            bool result = await BakeSingleSceneAsync(scenePath);
            if (result) success++;
            else failed++;
        }
        
        EditorUtility.ClearProgressBar();
        Debug.Log($"批量烘焙完成！成功：{success}，失败：{failed}，共 {total} 个场景");
    }
    
    private static async ETTask<bool> BakeSingleSceneAsync(string scenePath)
    {
        // 打开场景
        var scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
        
        // 应用统一烘焙设置
        ApplySettings(HighQualitySettings);
        
        // 开始异步烘焙
        bool completed = false;
        bool success = false;
        
        Lightmapping.bakeCompleted += () =>
        {
            completed = true;
            success = true;
        };
        
        Lightmapping.bakeStarted += () =>
        {
            Debug.Log($"开始烘焙: {scenePath}");
        };
        
        Lightmapping.BakeAsync();  // 异步烘焙
        
        // 等待烘焙完成
        while (!completed)
        {
            await TimerComponent.Instance.WaitFrameAsync();  // 每帧检查
        }
        
        if (success)
        {
            // 保存场景
            EditorSceneManager.SaveScene(scene);
            Debug.Log($"烘焙完成: {scenePath}");
        }
        
        return success;
    }
    
    private static string[] GetAllGameScenePaths()
    {
        return EditorBuildSettings.scenes
            .Where(s => s.enabled)
            .Select(s => s.path)
            .ToArray();
    }
}
```

---

## 烘焙前检查工具

烘焙之前，先做检查能避免很多问题：

```csharp
[MenuItem("Tools/场景烘焙/烘焙前检查")]
public static void PreBakeCheck()
{
    var issues = new List<string>();
    
    // 检查1：所有应该是 Static 的物体是否设置了 Contribute GI
    foreach (var renderer in Object.FindObjectsOfType<MeshRenderer>())
    {
        var go = renderer.gameObject;
        if (go.isStatic && !GameObjectUtility.GetStaticEditorFlags(go)
            .HasFlag(StaticEditorFlags.ContributeGI))
        {
            issues.Add($"[{go.name}] 是 Static 但没有启用 Contribute GI");
        }
    }
    
    // 检查2：光贴图分辨率是否异常
    foreach (var renderer in Object.FindObjectsOfType<MeshRenderer>())
    {
        if (renderer.scaleInLightmap <= 0)
        {
            issues.Add($"[{renderer.gameObject.name}] scaleInLightmap 为 {renderer.scaleInLightmap}");
        }
    }
    
    // 检查3：Realtime 灯光是否过多（移动端）
    var realtimeLights = Object.FindObjectsOfType<Light>()
        .Where(l => l.lightmapBakeType == LightmapBakeType.Realtime);
    
    if (realtimeLights.Count() > 3)
    {
        issues.Add($"实时灯光数量过多 ({realtimeLights.Count()} 个)，考虑烘焙部分灯光");
    }
    
    if (issues.Count == 0)
    {
        Debug.Log("✓ 烘焙前检查通过！");
    }
    else
    {
        Debug.LogWarning($"发现 {issues.Count} 个潜在问题：\n" + 
            string.Join("\n", issues.Select(i => "  • " + i)));
    }
}
```

---

## 烘焙结果验证

```csharp
[MenuItem("Tools/场景烘焙/验证烘焙结果")]
public static void ValidateBakeResult()
{
    var issues = new List<string>();
    
    // 检查是否有未烘焙的静态物体
    foreach (var renderer in Object.FindObjectsOfType<MeshRenderer>())
    {
        if (renderer.gameObject.isStatic && renderer.lightmapIndex < 0)
        {
            issues.Add($"[{renderer.gameObject.name}] 是 Static 但没有光贴图数据");
        }
    }
    
    // 检查光贴图纹理大小
    foreach (var lm in LightmapSettings.lightmaps)
    {
        if (lm.lightmapColor != null)
        {
            int size = lm.lightmapColor.width;
            if (size > 2048)
            {
                issues.Add($"光贴图分辨率过高 ({size}×{size})，可能影响内存");
            }
        }
    }
    
    Debug.Log(issues.Count == 0 
        ? "✓ 烘焙结果验证通过！" 
        : $"验证发现 {issues.Count} 个问题");
}
```

---

## 光照贴图数据管理

```csharp
// 保存/恢复烘焙数据（用于快速切换不同时间段的光照）
public class LightmapDataManager
{
    public static void SaveLightmapData(string saveName)
    {
        string folder = $"Assets/Lightmaps/{saveName}";
        if (!AssetDatabase.IsValidFolder(folder))
            AssetDatabase.CreateFolder("Assets/Lightmaps", saveName);
        
        // 复制光贴图文件
        foreach (var lm in LightmapSettings.lightmaps)
        {
            if (lm.lightmapColor != null)
            {
                string srcPath = AssetDatabase.GetAssetPath(lm.lightmapColor);
                string destPath = srcPath.Replace("Assets/", $"Assets/Lightmaps/{saveName}/");
                AssetDatabase.CopyAsset(srcPath, destPath);
            }
        }
        
        Debug.Log($"光照数据已保存到: {folder}");
    }
}
```

---

## 总结

场景烘焙自动化工具的核心价值：

| 功能 | 效率提升 |
|------|---------|
| 统一烘焙设置 | 消灭"手感不一致"问题 |
| 批量烘焙 | 40 个场景自动烘焙，无需人工等待 |
| 烘焙前检查 | 避免因配置错误浪费烘焙时间 |
| 结果验证 | 快速确认烘焙质量 |

对于有 40+ 个场景的项目，烘焙自动化工具可以把"每周花一整天烘焙"变成"按一个按钮，然后去吃饭"。这种投入是非常值得的。
