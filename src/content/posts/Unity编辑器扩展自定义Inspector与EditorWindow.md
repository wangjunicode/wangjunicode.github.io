---
title: Unity编辑器扩展：自定义Inspector与EditorWindow
published: 2026-03-31
description: 全面解析Unity编辑器工具开发，包含CustomEditor（自定义Inspector面板）、PropertyDrawer（自定义属性绘制）、EditorWindow（独立工具窗口）、编辑器菜单项、ScriptableObject编辑器、自动化工具（一键优化/批量处理），以及编辑器GUILayout最佳实践。
tags: [Unity, Editor扩展, 工具开发, CustomEditor, 游戏开发]
category: 工程实践
draft: false
---

## 一、CustomEditor

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(EnemyController))]
public class EnemyControllerEditor : Editor
{
    private SerializedProperty healthProp;
    private SerializedProperty speedProp;
    private SerializedProperty patrolPointsProp;

    void OnEnable()
    {
        healthProp = serializedObject.FindProperty("maxHealth");
        speedProp = serializedObject.FindProperty("moveSpeed");
        patrolPointsProp = serializedObject.FindProperty("patrolPoints");
    }

    public override void OnInspectorGUI()
    {
        serializedObject.Update();
        
        EditorGUILayout.LabelField("基础配置", EditorStyles.boldLabel);
        EditorGUILayout.PropertyField(healthProp, new GUIContent("最大血量"));
        EditorGUILayout.PropertyField(speedProp, new GUIContent("移动速度"));
        
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("巡逻配置", EditorStyles.boldLabel);
        EditorGUILayout.PropertyField(patrolPointsProp, true);
        
        EditorGUILayout.Space();
        
        // 调试按钮（仅运行时可用）
        GUI.enabled = Application.isPlaying;
        if (GUILayout.Button("触发攻击"))
        {
            var enemy = (EnemyController)target;
            // enemy.ForceAttack();
        }
        GUI.enabled = true;
        
        if (GUILayout.Button("定位到场景视图"))
        {
            SceneView.lastActiveSceneView?.LookAt(((Component)target).transform.position);
        }
        
        serializedObject.ApplyModifiedProperties();
    }

    void OnSceneGUI()
    {
        var enemy = (EnemyController)target;
        
        // 在Scene视图绘制检测范围
        Handles.color = new Color(1, 0, 0, 0.1f);
        Handles.DrawSolidDisc(enemy.transform.position, Vector3.up, 5f);
        Handles.color = Color.red;
        Handles.DrawWireDisc(enemy.transform.position, Vector3.up, 5f);
        
        Handles.Label(enemy.transform.position + Vector3.up * 2, "检测范围: 5m");
    }
}
#endif
```

---

## 二、EditorWindow 工具窗口

```csharp
#if UNITY_EDITOR
public class GameUtilityWindow : EditorWindow
{
    [MenuItem("Tools/Game/综合工具箱 %#g")]
    static void Open() => GetWindow<GameUtilityWindow>("游戏工具箱");

    private int selectedTab;
    private string[] tabNames = { "场景工具", "资源分析", "批量处理" };

    void OnGUI()
    {
        selectedTab = GUILayout.Toolbar(selectedTab, tabNames);
        EditorGUILayout.Space();
        
        switch (selectedTab)
        {
            case 0: DrawSceneTools(); break;
            case 1: DrawAssetAnalysis(); break;
            case 2: DrawBatchTools(); break;
        }
    }

    void DrawSceneTools()
    {
        EditorGUILayout.LabelField("场景工具", EditorStyles.boldLabel);
        
        if (GUILayout.Button("清理空的GameObject"))
        {
            int count = 0;
            foreach (var go in FindObjectsOfType<GameObject>())
            {
                if (go.transform.childCount == 0 && go.GetComponents<Component>().Length == 1)
                {
                    DestroyImmediate(go);
                    count++;
                }
            }
            Debug.Log($"清理了 {count} 个空对象");
        }
        
        if (GUILayout.Button("对齐所有选中对象到地面"))
        {
            foreach (var go in Selection.gameObjects)
            {
                if (Physics.Raycast(go.transform.position + Vector3.up * 10, 
                    Vector3.down, out RaycastHit hit, 20f))
                {
                    Undo.RecordObject(go.transform, "Align to Ground");
                    go.transform.position = hit.point;
                }
            }
        }
    }

    void DrawAssetAnalysis()
    {
        EditorGUILayout.LabelField("资源分析", EditorStyles.boldLabel);
        
        if (GUILayout.Button("查找超大纹理（>2048）"))
        {
            string[] guids = AssetDatabase.FindAssets("t:Texture2D");
            int found = 0;
            foreach (var guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                if (tex != null && (tex.width > 2048 || tex.height > 2048))
                {
                    Debug.LogWarning($"超大纹理: {path} ({tex.width}x{tex.height})", tex);
                    found++;
                }
            }
            Debug.Log($"发现 {found} 个超大纹理");
        }
    }

    void DrawBatchTools()
    {
        EditorGUILayout.LabelField("批量处理", EditorStyles.boldLabel);
        
        if (GUILayout.Button("批量重置选中对象Transform"))
        {
            foreach (var go in Selection.gameObjects)
            {
                Undo.RecordObject(go.transform, "Reset Transform");
                go.transform.localPosition = Vector3.zero;
                go.transform.localRotation = Quaternion.identity;
                go.transform.localScale = Vector3.one;
            }
        }
    }
}
#endif
```

---

## 三、PropertyDrawer

```csharp
[System.AttributeUsage(System.AttributeTargets.Field)]
public class MinMaxRangeAttribute : PropertyAttribute
{
    public float Min, Max;
    public MinMaxRangeAttribute(float min, float max) { Min = min; Max = max; }
}

#if UNITY_EDITOR
[CustomPropertyDrawer(typeof(MinMaxRangeAttribute))]
public class MinMaxRangeDrawer : PropertyDrawer
{
    public override void OnGUI(Rect position, SerializedProperty property, GUIContent label)
    {
        var attr = (MinMaxRangeAttribute)attribute;
        
        EditorGUI.BeginProperty(position, label, property);
        
        float value = property.floatValue;
        float newValue = EditorGUI.Slider(position, label, value, attr.Min, attr.Max);
        
        if (!Mathf.Approximately(value, newValue))
            property.floatValue = newValue;
        
        EditorGUI.EndProperty();
    }
}
#endif

// 使用
public class SpawnConfig : MonoBehaviour
{
    [MinMaxRange(0f, 10f)] public float SpawnDelay;
    [MinMaxRange(1f, 100f)] public float SpawnRadius;
}
```
