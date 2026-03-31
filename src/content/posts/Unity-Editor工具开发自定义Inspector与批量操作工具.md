---
title: Unity Editor工具开发：自定义Inspector与批量操作工具
published: 2026-03-31
description: 全面解析Unity Editor工具开发的工程实践，包含自定义Inspector（CustomEditor/PropertyDrawer）、EditorWindow工具窗口、批量场景物体处理工具、ScriptableObject可视化编辑器、Gizmos调试可视化、OnValidate验证逻辑，以及常用Editor扩展模式（菜单项/上下文菜单/快捷键）。
tags: [Unity, Editor工具, CustomEditor, EditorWindow, 游戏开发]
category: 工程实践
draft: false
---

## 一、自定义Inspector

```csharp
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;

/// <summary>
/// 要显示自定义Inspector的组件
/// </summary>
public class EnemyConfig : MonoBehaviour
{
    [Header("基础属性")]
    public string EnemyName;
    public int Level;
    public float HP;
    public float MoveSpeed;
    
    [Header("战斗属性")]
    public float AttackDamage;
    public float AttackRange;
    public float AttackInterval;
    
    [Header("掉落")]
    public ItemDrop[] Drops;
    
    [Header("巡逻")]
    public bool HasPatrol;
    public Transform[] PatrolWaypoints;
    
    [System.Serializable]
    public class ItemDrop
    {
        public string ItemId;
        [Range(0f, 1f)] public float DropRate;
        public int MinCount;
        public int MaxCount;
    }
}

/// <summary>
/// EnemyConfig 的自定义Inspector
/// </summary>
[CustomEditor(typeof(EnemyConfig))]
public class EnemyConfigEditor : Editor
{
    private bool showDropsFoldout = true;
    private bool showPatrolFoldout;
    private SerializedProperty dropsProperty;

    void OnEnable()
    {
        dropsProperty = serializedObject.FindProperty("Drops");
    }

    public override void OnInspectorGUI()
    {
        serializedObject.Update();
        
        var config = (EnemyConfig)target;
        
        // ============ 基础信息 ============
        EditorGUILayout.LabelField("基础属性", EditorStyles.boldLabel);
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        
        config.EnemyName = EditorGUILayout.TextField("名称", config.EnemyName);
        config.Level = EditorGUILayout.IntSlider("等级", config.Level, 1, 100);
        config.HP = EditorGUILayout.FloatField("血量", config.HP);
        
        // 根据等级自动估算血量
        if (GUILayout.Button("自动计算血量（基于等级）"))
        {
            config.HP = 100 + config.Level * 50;
            EditorUtility.SetDirty(config);
        }
        
        EditorGUILayout.EndVertical();
        EditorGUILayout.Space();
        
        // ============ 战斗属性 ============
        EditorGUILayout.LabelField("战斗属性", EditorStyles.boldLabel);
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        
        config.AttackDamage = EditorGUILayout.FloatField("攻击伤害", config.AttackDamage);
        config.AttackRange = EditorGUILayout.Slider("攻击范围", config.AttackRange, 0.5f, 20f);
        config.AttackInterval = EditorGUILayout.Slider("攻击间隔(s)", config.AttackInterval, 0.1f, 5f);
        
        // DPS预估
        if (config.AttackInterval > 0)
        {
            float dps = config.AttackDamage / config.AttackInterval;
            EditorGUI.BeginDisabledGroup(true);
            EditorGUILayout.FloatField("DPS预估", dps);
            EditorGUI.EndDisabledGroup();
        }
        
        EditorGUILayout.EndVertical();
        EditorGUILayout.Space();
        
        // ============ 掉落表 ============
        showDropsFoldout = EditorGUILayout.Foldout(showDropsFoldout, 
            $"掉落表 ({dropsProperty.arraySize}项)", true);
        
        if (showDropsFoldout)
        {
            EditorGUILayout.BeginVertical(EditorStyles.helpBox);
            
            for (int i = 0; i < dropsProperty.arraySize; i++)
            {
                var dropProp = dropsProperty.GetArrayElementAtIndex(i);
                
                EditorGUILayout.BeginHorizontal();
                EditorGUILayout.PropertyField(
                    dropProp.FindPropertyRelative("ItemId"), GUIContent.none, 
                    GUILayout.Width(120));
                EditorGUILayout.PropertyField(
                    dropProp.FindPropertyRelative("DropRate"), GUIContent.none, 
                    GUILayout.Width(80));
                
                if (GUILayout.Button("×", GUILayout.Width(25)))
                    dropsProperty.DeleteArrayElementAtIndex(i);
                
                EditorGUILayout.EndHorizontal();
            }
            
            if (GUILayout.Button("+ 添加掉落项"))
                dropsProperty.InsertArrayElementAtIndex(dropsProperty.arraySize);
            
            EditorGUILayout.EndVertical();
        }
        
        serializedObject.ApplyModifiedProperties();
        
        // 标记为已修改
        if (GUI.changed)
            EditorUtility.SetDirty(target);
    }

    // Gizmos 可视化攻击范围
    void OnSceneGUI()
    {
        var config = (EnemyConfig)target;
        
        Handles.color = new Color(1f, 0, 0, 0.3f);
        Handles.DrawWireDisc(config.transform.position, Vector3.up, config.AttackRange);
        
        // 可拖动手柄
        EditorGUI.BeginChangeCheck();
        float newRange = Handles.RadiusHandle(
            Quaternion.identity, config.transform.position, config.AttackRange);
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(config, "Change Attack Range");
            config.AttackRange = newRange;
        }
    }
}
#endif
```

---

## 二、批量操作EditorWindow

```csharp
#if UNITY_EDITOR
/// <summary>
/// 批量场景物体处理工具
/// </summary>
public class BatchOperationWindow : EditorWindow
{
    [MenuItem("Tools/Game/批量操作工具")]
    static void Open() => GetWindow<BatchOperationWindow>("批量操作");

    private string searchTag = "";
    private string searchLayer = "";
    private Vector3 offsetPosition;
    private bool setStatic;
    private float uniformScale = 1f;
    private List<GameObject> foundObjects = new List<GameObject>();

    void OnGUI()
    {
        GUILayout.Label("批量查找物体", EditorStyles.boldLabel);
        
        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Tag:", GUILayout.Width(50));
        searchTag = EditorGUILayout.TextField(searchTag);
        EditorGUILayout.EndHorizontal();
        
        if (GUILayout.Button("查找所有匹配物体"))
        {
            foundObjects.Clear();
            var all = FindObjectsOfType<GameObject>();
            
            foreach (var go in all)
            {
                bool match = true;
                if (!string.IsNullOrEmpty(searchTag) && go.tag != searchTag)
                    match = false;
                if (match) foundObjects.Add(go);
            }
            
            Debug.Log($"找到 {foundObjects.Count} 个物体");
        }
        
        EditorGUILayout.Space();
        GUILayout.Label($"已找到: {foundObjects.Count} 个物体", EditorStyles.boldLabel);
        
        EditorGUILayout.Space();
        GUILayout.Label("批量操作", EditorStyles.boldLabel);
        
        offsetPosition = EditorGUILayout.Vector3Field("位置偏移", offsetPosition);
        if (GUILayout.Button("应用位置偏移"))
        {
            Undo.RecordObjects(foundObjects.ToArray(), "Batch Move");
            foreach (var go in foundObjects)
                go.transform.position += offsetPosition;
        }
        
        uniformScale = EditorGUILayout.FloatField("统一缩放", uniformScale);
        if (GUILayout.Button("应用缩放"))
        {
            Undo.RecordObjects(foundObjects.ToArray(), "Batch Scale");
            foreach (var go in foundObjects)
                go.transform.localScale = Vector3.one * uniformScale;
        }
        
        setStatic = EditorGUILayout.Toggle("设为Static", setStatic);
        if (GUILayout.Button("应用Static设置"))
        {
            Undo.RecordObjects(foundObjects.ToArray(), "Batch Static");
            foreach (var go in foundObjects)
                GameObjectUtility.SetStaticEditorFlags(go, 
                    setStatic ? StaticEditorFlags.BatchingStatic : 0);
        }
        
        EditorGUILayout.Space();
        if (GUILayout.Button("选中所有找到的物体"))
        {
            Selection.objects = foundObjects.ToArray();
        }
    }
}

/// <summary>
/// 自定义PropertyDrawer（绘制单个序列化字段）
/// </summary>
[CustomPropertyDrawer(typeof(EnemyConfig.ItemDrop))]
public class ItemDropDrawer : PropertyDrawer
{
    public override void OnGUI(Rect position, SerializedProperty property, GUIContent label)
    {
        EditorGUI.BeginProperty(position, label, property);
        
        float w = position.width;
        float h = position.height;
        
        var itemIdRect  = new Rect(position.x, position.y, w * 0.4f, h);
        var dropRateRect = new Rect(position.x + w * 0.42f, position.y, w * 0.25f, h);
        var countRect   = new Rect(position.x + w * 0.69f, position.y, w * 0.3f, h);
        
        EditorGUI.PropertyField(itemIdRect, property.FindPropertyRelative("ItemId"), GUIContent.none);
        
        var rateProp = property.FindPropertyRelative("DropRate");
        rateProp.floatValue = EditorGUI.Slider(dropRateRect, rateProp.floatValue, 0f, 1f);
        
        // Min/Max Count（双字段内联）
        var minProp = property.FindPropertyRelative("MinCount");
        var maxProp = property.FindPropertyRelative("MaxCount");
        
        float halfCount = countRect.width / 2f - 5f;
        EditorGUI.PropertyField(
            new Rect(countRect.x, countRect.y, halfCount, countRect.height), 
            minProp, GUIContent.none);
        EditorGUI.PropertyField(
            new Rect(countRect.x + halfCount + 5f, countRect.y, halfCount, countRect.height), 
            maxProp, GUIContent.none);
        
        EditorGUI.EndProperty();
    }
}
#endif
```

---

## 三、常用Editor快捷模式

| 模式 | 用法 | 示例 |
|------|------|------|
| ContextMenu | 在Inspector右键菜单添加命令 | `[ContextMenu("Reset Stats")]` |
| MenuItem | 在Unity菜单栏添加 | `[MenuItem("Tools/My Tool")]` |
| OnValidate | 字段修改时自动验证 | 防止负数HP |
| Gizmos | Scene视图绘制辅助图形 | 攻击范围圆 |
| Handles | Scene视图可拖动控制柄 | 调整范围半径 |
| EditorPrefs | 持久化Editor设置 | 记录工具窗口状态 |
