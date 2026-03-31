---
title: 游戏关卡设计工具：Inspector扩展与可视化编辑器
published: 2026-03-31
description: 深度解析游戏关卡设计专用工具的开发，包括Unity Custom Inspector的高级扩展（嵌套属性/条件显示/按钮组）、Scene View交互工具（Handle拖拽/快捷操作）、批量摆放工具、关卡验证器（检测死路/可达性）、路径点可视化编辑，以及Gizmos绘制最佳实践。
tags: [Unity, 关卡设计, Editor扩展, Custom Inspector, 工具链]
category: 工具链开发
draft: false
---

## 一、高级 Custom Inspector

```csharp
using UnityEngine;
using UnityEditor;

/// <summary>
/// 关卡波次配置（Inspector 扩展示例）
/// </summary>
public class WaveConfig : MonoBehaviour
{
    [System.Serializable]
    public class EnemySpawnGroup
    {
        public GameObject EnemyPrefab;
        public int Count = 3;
        public float SpawnInterval = 0.5f;
        
        [Range(0, 100)]
        public int SpawnWeight = 50;      // 出现概率权重
        
        public bool HasSpecialBehavior;
        [HideInInspector] public string SpecialBehaviorNote;
    }

    [Header("波次基础")]
    public int WaveNumber;
    public float WaveDuration = 60f;      // 持续时间（秒）
    public float SpawnRadius = 10f;

    [Header("敌人配置")]
    public List<EnemySpawnGroup> SpawnGroups = new List<EnemySpawnGroup>();
    
    [Header("特殊事件")]
    public bool HasBossWave;
    [HideInInspector] public GameObject BossPrefab;
    [HideInInspector] public float BossSpawnDelay = 30f;
    
    [Header("奖励")]
    public int ExpReward;
    public List<string> DropItemIds = new List<string>();
}

#if UNITY_EDITOR
[CustomEditor(typeof(WaveConfig))]
public class WaveConfigEditor : Editor
{
    private bool showSpawnGroups = true;
    private bool showRewards = false;

    public override void OnInspectorGUI()
    {
        serializedObject.Update();
        
        var config = target as WaveConfig;
        
        // ============ 波次基础 ============
        EditorGUILayout.LabelField($"第 {config.WaveNumber} 波", EditorStyles.boldLabel);
        EditorGUILayout.Space(4);
        
        DrawPropertiesExcluding(serializedObject, 
            "m_Script", "SpawnGroups", "HasBossWave", "BossPrefab", 
            "BossSpawnDelay", "ExpReward", "DropItemIds");
        
        // ============ 敌人配置（可折叠）============
        EditorGUILayout.Space(4);
        showSpawnGroups = EditorGUILayout.BeginFoldoutHeaderGroup(showSpawnGroups, "敌人配置");
        
        if (showSpawnGroups)
        {
            var groups = serializedObject.FindProperty("SpawnGroups");
            
            for (int i = 0; i < groups.arraySize; i++)
            {
                var group = groups.GetArrayElementAtIndex(i);
                
                EditorGUILayout.BeginVertical(EditorStyles.helpBox);
                
                EditorGUILayout.BeginHorizontal();
                EditorGUILayout.LabelField($"敌人组 {i + 1}", EditorStyles.boldLabel);
                
                if (GUILayout.Button("✕", GUILayout.Width(25)))
                {
                    groups.DeleteArrayElementAtIndex(i);
                    break;
                }
                EditorGUILayout.EndHorizontal();
                
                // 自定义绘制各字段
                DrawGroupFields(group);
                
                // 条件显示：HasSpecialBehavior 为 true 时才显示 Note
                var hasSpecial = group.FindPropertyRelative("HasSpecialBehavior");
                EditorGUILayout.PropertyField(hasSpecial);
                
                if (hasSpecial.boolValue)
                {
                    var note = group.FindPropertyRelative("SpecialBehaviorNote");
                    EditorGUILayout.PropertyField(note, new GUIContent("特殊行为说明"));
                }
                
                EditorGUILayout.EndVertical();
                EditorGUILayout.Space(2);
            }
            
            if (GUILayout.Button("+ 添加敌人组", GUILayout.Height(30)))
                groups.InsertArrayElementAtIndex(groups.arraySize);
        }
        
        EditorGUILayout.EndFoldoutHeaderGroup();
        
        // ============ Boss 波次 ============
        EditorGUILayout.Space(4);
        var hasBoss = serializedObject.FindProperty("HasBossWave");
        EditorGUILayout.PropertyField(hasBoss, new GUIContent("包含Boss战"));
        
        if (hasBoss.boolValue)
        {
            EditorGUI.indentLevel++;
            EditorGUILayout.PropertyField(serializedObject.FindProperty("BossPrefab"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("BossSpawnDelay"));
            EditorGUI.indentLevel--;
        }
        
        // ============ 奖励（可折叠）============
        EditorGUILayout.Space(4);
        showRewards = EditorGUILayout.BeginFoldoutHeaderGroup(showRewards, "奖励配置");
        if (showRewards)
        {
            EditorGUILayout.PropertyField(serializedObject.FindProperty("ExpReward"));
            EditorGUILayout.PropertyField(serializedObject.FindProperty("DropItemIds"));
        }
        EditorGUILayout.EndFoldoutHeaderGroup();
        
        // ============ 操作按钮 ============
        EditorGUILayout.Space(8);
        
        using (new EditorGUILayout.HorizontalScope())
        {
            if (GUILayout.Button("验证配置", GUILayout.Height(30)))
                ValidateConfig(config);
            
            if (GUILayout.Button("复制到下一波", GUILayout.Height(30)))
                DuplicateToNextWave(config);
        }
        
        serializedObject.ApplyModifiedProperties();
    }

    void DrawGroupFields(SerializedProperty group)
    {
        EditorGUILayout.PropertyField(group.FindPropertyRelative("EnemyPrefab"), new GUIContent("预制体"));
        
        var count = group.FindPropertyRelative("Count");
        var interval = group.FindPropertyRelative("SpawnInterval");
        var weight = group.FindPropertyRelative("SpawnWeight");
        
        EditorGUILayout.BeginHorizontal();
        EditorGUILayout.PropertyField(count, new GUIContent("数量"), GUILayout.Width(120));
        EditorGUILayout.PropertyField(interval, new GUIContent("间隔(秒)"), GUILayout.Width(140));
        EditorGUILayout.PropertyField(weight, new GUIContent("权重"), GUILayout.Width(110));
        EditorGUILayout.EndHorizontal();
    }

    void ValidateConfig(WaveConfig config)
    {
        var issues = new System.Text.StringBuilder();
        
        if (config.SpawnGroups.Count == 0)
            issues.AppendLine("⚠️ 没有配置敌人组");
        
        foreach (var group in config.SpawnGroups)
        {
            if (group.EnemyPrefab == null)
                issues.AppendLine("❌ 有敌人组的预制体为空");
            
            if (group.Count <= 0)
                issues.AppendLine("⚠️ 有敌人组数量为0");
        }
        
        if (config.HasBossWave && config.BossPrefab == null)
            issues.AppendLine("❌ 设置了Boss波次但Boss预制体为空");
        
        if (issues.Length == 0)
            EditorUtility.DisplayDialog("验证通过", "配置看起来没问题！", "确定");
        else
            EditorUtility.DisplayDialog("发现问题", issues.ToString(), "确定");
    }

    void DuplicateToNextWave(WaveConfig config)
    {
        Debug.Log("[WaveEditor] 复制到下一波（待实现）");
    }
}
#endif
```

---

## 二、路径点可视化编辑器

```csharp
/// <summary>
/// 巡逻路径组件（Scene View 中可交互编辑）
/// </summary>
public class PatrolPath : MonoBehaviour
{
    [SerializeField] public List<Vector3> Waypoints = new List<Vector3>();
    [SerializeField] public bool IsLoop = true;
    [SerializeField] public Color PathColor = Color.cyan;

    void OnDrawGizmosSelected()
    {
        if (Waypoints == null || Waypoints.Count < 2) return;
        
        Gizmos.color = PathColor;
        
        for (int i = 0; i < Waypoints.Count; i++)
        {
            Vector3 worldPos = transform.TransformPoint(Waypoints[i]);
            
            // 绘制节点
            Gizmos.DrawWireSphere(worldPos, 0.3f);
            
            // 绘制连线
            int next = (i + 1) % Waypoints.Count;
            if (next < Waypoints.Count && (i + 1 < Waypoints.Count || IsLoop))
            {
                Vector3 nextPos = transform.TransformPoint(Waypoints[next]);
                Gizmos.DrawLine(worldPos, nextPos);
                
                // 绘制方向箭头
                Vector3 dir = (nextPos - worldPos).normalized;
                Vector3 mid = Vector3.Lerp(worldPos, nextPos, 0.5f);
                Gizmos.DrawLine(mid, mid + Quaternion.Euler(0, 30, 0) * dir * 0.5f);
                Gizmos.DrawLine(mid, mid + Quaternion.Euler(0, -30, 0) * dir * 0.5f);
            }
        }
    }
}

#if UNITY_EDITOR
[CustomEditor(typeof(PatrolPath))]
public class PatrolPathEditor : Editor
{
    private int selectedIndex = -1;

    void OnSceneGUI()
    {
        var path = target as PatrolPath;
        
        for (int i = 0; i < path.Waypoints.Count; i++)
        {
            Vector3 worldPos = path.transform.TransformPoint(path.Waypoints[i]);
            
            // 拖拽手柄
            EditorGUI.BeginChangeCheck();
            Vector3 newWorldPos = Handles.PositionHandle(worldPos, Quaternion.identity);
            if (EditorGUI.EndChangeCheck())
            {
                Undo.RecordObject(path, "Move Waypoint");
                path.Waypoints[i] = path.transform.InverseTransformPoint(newWorldPos);
                EditorUtility.SetDirty(path);
            }
            
            // 节点标签
            Handles.Label(worldPos + Vector3.up * 0.5f, $"P{i}");
        }
        
        // Shift+Click 添加新节点
        Event e = Event.current;
        if (e.type == EventType.MouseDown && e.button == 0 && e.shift)
        {
            Ray ray = HandleUtility.GUIPointToWorldRay(e.mousePosition);
            if (Physics.Raycast(ray, out RaycastHit hit))
            {
                Undo.RecordObject(path, "Add Waypoint");
                path.Waypoints.Add(path.transform.InverseTransformPoint(hit.point));
                EditorUtility.SetDirty(path);
                e.Use();
            }
        }
    }

    public override void OnInspectorGUI()
    {
        var path = target as PatrolPath;
        
        DrawDefaultInspector();
        
        EditorGUILayout.Space();
        if (GUILayout.Button("清空所有路径点"))
        {
            Undo.RecordObject(path, "Clear Waypoints");
            path.Waypoints.Clear();
            EditorUtility.SetDirty(path);
        }
        
        EditorGUILayout.HelpBox("Shift+Click 场景中添加路径点\n拖拽手柄移动路径点", MessageType.Info);
    }
}
#endif
```

---

## 三、关卡设计工具的价值

**节省的时间估算：**

| 操作 | 没有工具 | 有工具 | 节省/次 |
|------|----------|--------|---------|
| 配置波次敌人 | 5分钟 | 1分钟 | 4分钟 |
| 摆放路径点 | 10分钟 | 2分钟 | 8分钟 |
| 验证关卡配置 | 手动运行测试 | 一键验证 | 15分钟 |

100个关卡 × 平均节省30分钟 = **50小时**

**关卡设计师友好的工具特征：**
1. 所见即所得（Gizmos可视化）
2. 操作可撤销（Undo/Redo支持）
3. 一键验证（发现错误早）
4. 颜色区分状态（直观）
5. 快捷键支持（高效）
