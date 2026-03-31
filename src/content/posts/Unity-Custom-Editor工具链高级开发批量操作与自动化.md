---
title: Unity Custom Editor工具链高级开发：批量操作与自动化工具
published: 2026-03-31
description: 深度解析Unity自定义编辑器工具的高级开发，涵盖PropertyDrawer/CustomEditor/EditorWindow开发、批量资源处理工具、自动化场景检查器、AssetPostprocessor资产导入规范、Hierarchy与Project窗口扩展，以及提升团队工作流的实用工具套件。
tags: [Unity, 编辑器扩展, Editor工具, 工程实践, 工具链]
category: 工具链开发
draft: false
---

## 一、Custom Property Drawer

```csharp
using UnityEngine;
using UnityEditor;
using System.Collections.Generic;

/// <summary>
/// 标签属性（可视化显示枚举位标志）
/// </summary>
[System.AttributeUsage(System.AttributeTargets.Field)]
public class EnumFlagsAttribute : PropertyAttribute { }

#if UNITY_EDITOR
[CustomPropertyDrawer(typeof(EnumFlagsAttribute))]
public class EnumFlagsDrawer : PropertyDrawer
{
    public override void OnGUI(Rect position, SerializedProperty property, GUIContent label)
    {
        EditorGUI.BeginProperty(position, label, property);
        property.intValue = EditorGUI.MaskField(position, label, 
            property.intValue, property.enumNames);
        EditorGUI.EndProperty();
    }
}
#endif

/// <summary>
/// 只读字段属性（Inspector中显示但不可编辑）
/// </summary>
[System.AttributeUsage(System.AttributeTargets.Field)]
public class ReadOnlyAttribute : PropertyAttribute { }

#if UNITY_EDITOR
[CustomPropertyDrawer(typeof(ReadOnlyAttribute))]
public class ReadOnlyDrawer : PropertyDrawer
{
    public override void OnGUI(Rect position, SerializedProperty property, GUIContent label)
    {
        GUI.enabled = false;
        EditorGUI.PropertyField(position, property, label, true);
        GUI.enabled = true;
    }
}
#endif

/// <summary>
/// 带预览的纹理字段
/// </summary>
[System.AttributeUsage(System.AttributeTargets.Field)]
public class TexturePreviewAttribute : PropertyAttribute
{
    public int PreviewSize;
    public TexturePreviewAttribute(int previewSize = 64) { PreviewSize = previewSize; }
}

#if UNITY_EDITOR
[CustomPropertyDrawer(typeof(TexturePreviewAttribute))]
public class TexturePreviewDrawer : PropertyDrawer
{
    public override float GetPropertyHeight(SerializedProperty property, GUIContent label)
    {
        var attr = attribute as TexturePreviewAttribute;
        return property.objectReferenceValue != null ? 
            EditorGUIUtility.singleLineHeight + attr.PreviewSize + 4 :
            EditorGUIUtility.singleLineHeight;
    }

    public override void OnGUI(Rect position, SerializedProperty property, GUIContent label)
    {
        var attr = attribute as TexturePreviewAttribute;
        
        Rect fieldRect = new Rect(position.x, position.y, 
            position.width, EditorGUIUtility.singleLineHeight);
        
        EditorGUI.BeginProperty(fieldRect, label, property);
        EditorGUI.PropertyField(fieldRect, property, label);
        EditorGUI.EndProperty();
        
        if (property.objectReferenceValue is Texture2D texture)
        {
            Rect previewRect = new Rect(
                position.x + EditorGUIUtility.labelWidth + 2,
                position.y + EditorGUIUtility.singleLineHeight + 2,
                attr.PreviewSize, attr.PreviewSize);
            
            EditorGUI.DrawPreviewTexture(previewRect, texture);
        }
    }
}
#endif
```

---

## 二、批量资源处理工具窗口

```csharp
#if UNITY_EDITOR
/// <summary>
/// 批量纹理压缩设置工具
/// </summary>
public class BatchTextureProcessor : EditorWindow
{
    [MenuItem("Tools/Game/批量纹理压缩设置")]
    static void Open() => GetWindow<BatchTextureProcessor>("批量纹理工具");

    private Vector2 scrollPos;
    private List<TextureImporter> selectedTextures = new List<TextureImporter>();
    
    // 设置参数
    private TextureImporterFormat androidFormat = TextureImporterFormat.ETC2_RGBA8;
    private TextureImporterFormat iosFormat = TextureImporterFormat.ASTC_6x6;
    private int maxSize = 1024;
    private bool generateMipMaps = false;
    private bool compressionQuality = true;
    private TextureImporterType textureType = TextureImporterType.Sprite;

    void OnGUI()
    {
        GUILayout.Label("批量纹理压缩设置", EditorStyles.boldLabel);
        EditorGUILayout.Space();
        
        // 选择区域
        if (GUILayout.Button("从选择中加载纹理"))
            LoadSelectedTextures();
        
        if (GUILayout.Button("加载选中文件夹内所有纹理"))
            LoadTexturesFromFolder();
        
        EditorGUILayout.LabelField($"已加载: {selectedTextures.Count} 张纹理");
        
        EditorGUILayout.Space();
        GUILayout.Label("压缩设置", EditorStyles.boldLabel);
        
        androidFormat = (TextureImporterFormat)EditorGUILayout.EnumPopup("Android格式", androidFormat);
        iosFormat = (TextureImporterFormat)EditorGUILayout.EnumPopup("iOS格式", iosFormat);
        maxSize = EditorGUILayout.IntPopup("最大尺寸", maxSize, 
            new[] { "128", "256", "512", "1024", "2048", "4096" },
            new[] { 128, 256, 512, 1024, 2048, 4096 });
        generateMipMaps = EditorGUILayout.Toggle("生成MipMaps", generateMipMaps);
        textureType = (TextureImporterType)EditorGUILayout.EnumPopup("纹理类型", textureType);
        
        EditorGUILayout.Space();
        
        // 纹理列表预览
        if (selectedTextures.Count > 0)
        {
            scrollPos = EditorGUILayout.BeginScrollView(scrollPos, GUILayout.Height(200));
            foreach (var importer in selectedTextures)
            {
                EditorGUILayout.LabelField(
                    System.IO.Path.GetFileName(importer.assetPath), 
                    importer.GetPlatformTextureSettings("Android").format.ToString());
            }
            EditorGUILayout.EndScrollView();
        }
        
        EditorGUILayout.Space();
        
        using (new EditorGUI.DisabledScope(selectedTextures.Count == 0))
        {
            if (GUILayout.Button($"应用设置到 {selectedTextures.Count} 张纹理", 
                GUILayout.Height(40)))
            {
                ApplySettings();
            }
        }
    }

    void LoadSelectedTextures()
    {
        selectedTextures.Clear();
        foreach (var obj in Selection.objects)
        {
            string path = AssetDatabase.GetAssetPath(obj);
            if (AssetImporter.GetAtPath(path) is TextureImporter importer)
                selectedTextures.Add(importer);
        }
        Debug.Log($"[BatchTexture] Loaded {selectedTextures.Count} textures");
    }

    void LoadTexturesFromFolder()
    {
        selectedTextures.Clear();
        var guids = AssetDatabase.FindAssets("t:Texture2D", 
            Selection.activeObject != null ? 
            new[] { AssetDatabase.GetAssetPath(Selection.activeObject) } : 
            new[] { "Assets" });
        
        foreach (var guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            if (AssetImporter.GetAtPath(path) is TextureImporter importer)
                selectedTextures.Add(importer);
        }
    }

    void ApplySettings()
    {
        if (!EditorUtility.DisplayDialog("确认", 
            $"将修改 {selectedTextures.Count} 张纹理的压缩设置，确认继续？", 
            "确认", "取消"))
            return;
        
        int processed = 0;
        foreach (var importer in selectedTextures)
        {
            EditorUtility.DisplayProgressBar("处理中...", 
                $"处理 {importer.assetPath}", 
                (float)processed / selectedTextures.Count);
            
            // 基础设置
            importer.textureType = textureType;
            importer.mipmapEnabled = generateMipMaps;
            importer.maxTextureSize = maxSize;
            
            // Android 设置
            var androidSettings = new TextureImporterPlatformSettings
            {
                name = "Android",
                overridden = true,
                maxTextureSize = maxSize,
                format = androidFormat,
                compressionQuality = compressionQuality ? 100 : 50,
                allowsAlphaSplitting = false
            };
            importer.SetPlatformTextureSettings(androidSettings);
            
            // iOS 设置
            var iosSettings = new TextureImporterPlatformSettings
            {
                name = "iPhone",
                overridden = true,
                maxTextureSize = maxSize,
                format = iosFormat,
                compressionQuality = compressionQuality ? 100 : 50
            };
            importer.SetPlatformTextureSettings(iosSettings);
            
            AssetDatabase.ImportAsset(importer.assetPath);
            processed++;
        }
        
        EditorUtility.ClearProgressBar();
        EditorUtility.DisplayDialog("完成", 
            $"已处理 {processed} 张纹理", "确定");
        
        AssetDatabase.Refresh();
    }
}
#endif
```

---

## 三、场景自动检查器

```csharp
#if UNITY_EDITOR
/// <summary>
/// 场景问题检查器（提交前自动检查常见问题）
/// </summary>
public class SceneChecker : EditorWindow
{
    [MenuItem("Tools/Game/场景检查器")]
    static void Open() => GetWindow<SceneChecker>("场景检查");

    private List<CheckResult> results = new List<CheckResult>();
    private Vector2 scrollPos;

    public class CheckResult
    {
        public Severity Level;
        public string Message;
        public Object Target;
        
        public enum Severity { Info, Warning, Error }
    }

    void OnGUI()
    {
        GUILayout.Label("场景质量检查", EditorStyles.boldLabel);
        
        if (GUILayout.Button("开始检查", GUILayout.Height(30)))
            RunChecks();
        
        if (results.Count > 0)
        {
            int errors = results.FindAll(r => r.Level == CheckResult.Severity.Error).Count;
            int warnings = results.FindAll(r => r.Level == CheckResult.Severity.Warning).Count;
            
            EditorGUILayout.HelpBox(
                $"检查完成：{errors} 个错误，{warnings} 个警告", 
                errors > 0 ? MessageType.Error : 
                warnings > 0 ? MessageType.Warning : MessageType.Info);
            
            scrollPos = EditorGUILayout.BeginScrollView(scrollPos);
            foreach (var result in results)
            {
                var color = result.Level switch
                {
                    CheckResult.Severity.Error   => Color.red,
                    CheckResult.Severity.Warning => new Color(1f, 0.7f, 0f),
                    _ => GUI.color
                };
                
                var oldColor = GUI.color;
                GUI.color = color;
                
                EditorGUILayout.BeginHorizontal();
                GUILayout.Label(
                    result.Level == CheckResult.Severity.Error ? "❌" : 
                    result.Level == CheckResult.Severity.Warning ? "⚠️" : "ℹ️", 
                    GUILayout.Width(20));
                
                if (GUILayout.Button(result.Message, EditorStyles.label))
                {
                    if (result.Target != null)
                    {
                        Selection.activeObject = result.Target;
                        EditorGUIUtility.PingObject(result.Target);
                    }
                }
                EditorGUILayout.EndHorizontal();
                
                GUI.color = oldColor;
            }
            EditorGUILayout.EndScrollView();
        }
    }

    void RunChecks()
    {
        results.Clear();
        
        CheckMissingComponents();
        CheckLargeMeshes();
        CheckUnusedCameras();
        CheckLightingIssues();
        CheckMissingReferences();
        
        Debug.Log($"[SceneChecker] Found {results.Count} issues");
    }

    void CheckMissingComponents()
    {
        var allObjects = FindObjectsOfType<GameObject>();
        foreach (var go in allObjects)
        {
            var components = go.GetComponents<Component>();
            foreach (var comp in components)
            {
                if (comp == null)
                {
                    results.Add(new CheckResult
                    {
                        Level = CheckResult.Severity.Error,
                        Message = $"{go.name}: 包含 Missing Script 组件",
                        Target = go
                    });
                }
            }
        }
    }

    void CheckLargeMeshes()
    {
        var meshFilters = FindObjectsOfType<MeshFilter>();
        foreach (var mf in meshFilters)
        {
            if (mf.sharedMesh != null && mf.sharedMesh.vertexCount > 10000)
            {
                results.Add(new CheckResult
                {
                    Level = CheckResult.Severity.Warning,
                    Message = $"{mf.name}: 高多边形网格（{mf.sharedMesh.vertexCount:N0} vertices）",
                    Target = mf.gameObject
                });
            }
        }
    }

    void CheckUnusedCameras()
    {
        var cameras = FindObjectsOfType<Camera>();
        var activeCameras = System.Array.FindAll(cameras, c => c.enabled && c.gameObject.activeInHierarchy);
        
        if (activeCameras.Length > 2)
        {
            results.Add(new CheckResult
            {
                Level = CheckResult.Severity.Warning,
                Message = $"场景中有 {activeCameras.Length} 个激活的摄像机，请确认是否正确"
            });
        }
    }

    void CheckLightingIssues()
    {
        var lights = FindObjectsOfType<Light>();
        int realtimeLights = System.Array.FindAll(lights, 
            l => l.lightmapBakeType == LightmapBakeType.Realtime && 
                 l.enabled).Length;
        
        if (realtimeLights > 4)
        {
            results.Add(new CheckResult
            {
                Level = CheckResult.Severity.Warning,
                Message = $"场景中有 {realtimeLights} 个实时光源（建议 ≤4），会影响性能"
            });
        }
    }

    void CheckMissingReferences()
    {
        // 检查 MonoBehaviour 的 SerializeField 引用是否为空
        // 简化实现
        results.Add(new CheckResult
        {
            Level = CheckResult.Severity.Info,
            Message = "基础检查完成"
        });
    }
}
#endif
```

---

## 四、Hierarchy 窗口扩展

```csharp
#if UNITY_EDITOR
/// <summary>
/// Hierarchy 图标显示扩展
/// </summary>
[InitializeOnLoad]
public static class HierarchyIcons
{
    static Dictionary<System.Type, Texture2D> iconMap 
        = new Dictionary<System.Type, Texture2D>();
    
    static HierarchyIcons()
    {
        EditorApplication.hierarchyWindowItemOnGUI += DrawHierarchyIcons;
        
        // 注册图标
        iconMap[typeof(Camera)] = 
            EditorGUIUtility.IconContent("Camera Icon").image as Texture2D;
        iconMap[typeof(Light)] = 
            EditorGUIUtility.IconContent("Light Icon").image as Texture2D;
        iconMap[typeof(UnityEngine.AI.NavMeshAgent)] = 
            EditorGUIUtility.IconContent("NavMeshAgent Icon").image as Texture2D;
    }

    static void DrawHierarchyIcons(int instanceID, Rect selectionRect)
    {
        var go = EditorUtility.InstanceIDToObject(instanceID) as GameObject;
        if (go == null) return;
        
        float iconSize = 16f;
        Rect iconRect = new Rect(selectionRect.xMax - iconSize, selectionRect.y, 
            iconSize, iconSize);
        
        foreach (var kv in iconMap)
        {
            if (go.GetComponent(kv.Key) != null && kv.Value != null)
            {
                GUI.DrawTexture(iconRect, kv.Value, ScaleMode.ScaleToFit);
                iconRect.x -= iconSize + 2;
            }
        }
    }
}
#endif
```

---

## 五、工具箱收益对比

| 工具 | 手动时间 | 工具时间 | 节省时间/次 |
|------|----------|----------|------------|
| 批量纹理压缩 | 100张 * 2min | 3min | ~3小时 |
| 场景检查器 | 手动逐个排查 | 1分钟自动 | 1-2小时 |
| 批量命名规范 | 50个 * 30s | 10s | 25min |
| 缺失脚本检查 | 提交后发现 | 提交前发现 | 避免返工 |

**构建高质量工具链的原则：**
1. 工具本身要快（操作响应 < 1s）
2. 有撤销支持（Undo.RegisterCompleteObjectUndo）
3. 有进度条（超过1s的操作都要有进度）
4. 有安全确认（批量修改前确认框）
5. 记录日志（便于排查问题）
