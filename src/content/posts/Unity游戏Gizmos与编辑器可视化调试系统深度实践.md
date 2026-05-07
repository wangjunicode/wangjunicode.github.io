---
title: Unity游戏Gizmos与编辑器可视化调试系统深度实践
published: 2026-05-07
description: 深入解析Unity Gizmos与Handles系统的工作原理，涵盖自定义场景可视化工具、运行时调试绘制框架、编辑器空间标注系统设计、条件编译调试开关与真实项目中的调试可视化最佳实践。
tags: [Gizmos, 编辑器工具, 调试可视化, Unity, 工具开发, 开发效率]
category: 工具开发
draft: false
---

# Unity游戏Gizmos与编辑器可视化调试系统深度实践

## 一、Gizmos系统核心原理

### 1.1 Gizmos与Handles的区别

Unity提供两套场景可视化API，开发者需根据场景选择：

| 特性 | Gizmos | Handles |
|------|--------|---------|
| 调用位置 | `OnDrawGizmos` / `OnDrawGizmosSelected` | `OnSceneGUI`（Editor only）|
| 交互性 | 仅可视化，不可交互 | 支持拖拽、点击等交互操作 |
| 命名空间 | `UnityEngine.Gizmos` | `UnityEditor.Handles` |
| 运行时可用 | 编辑器下可见 | 仅Editor |
| 典型用途 | 碰撞体可视化、范围标注 | 自定义变换工具、参数调节手柄 |

### 1.2 Gizmos渲染管线位置

```
游戏渲染流程（编辑器模式）：
Scene Camera → Opaque Pass → Transparent Pass
    → [Gizmos Pass] → [Handle Pass] → [UI Overlay]

关键点：
• Gizmos绘制在所有场景物体之后
• 使用 Gizmos.matrix 可变换Gizmos坐标系  
• Gizmos颜色受Gizmos.color控制
• 部分Gizmos支持 matrix 变换（如DrawMesh）
```

---

## 二、基础Gizmos API深度应用

### 2.1 常用Gizmos方法完整参考

```csharp
using UnityEngine;

/// <summary>
/// Gizmos API完整示例组件
/// </summary>
public class GizmosReference : MonoBehaviour
{
    [Header("范围可视化")]
    [SerializeField] private float m_AttackRange    = 3f;
    [SerializeField] private float m_DetectRange    = 8f;
    [SerializeField] private float m_ChaseRange     = 12f;
    [SerializeField] private Color m_AttackColor    = new Color(1f, 0.2f, 0.2f, 0.3f);
    [SerializeField] private Color m_DetectColor    = new Color(1f, 1f, 0f, 0.15f);
    
    [Header("路径可视化")]
    [SerializeField] private Vector3[] m_Waypoints;
    
    [Header("调试开关")]
    [SerializeField] private bool m_ShowRanges = true;
    [SerializeField] private bool m_ShowPath   = true;
    [SerializeField] private bool m_ShowBounds = false;

    // 仅在对象被选中时绘制（推荐用于详细信息）
    void OnDrawGizmosSelected()
    {
        if (!m_ShowRanges) return;
        
        Vector3 pos = transform.position;
        
        // ---- 实心球体 ----
        Gizmos.color = m_AttackColor;
        Gizmos.DrawSphere(pos, m_AttackRange);
        
        // ---- 线框球体 ----
        Gizmos.color = Color.red;
        Gizmos.DrawWireSphere(pos, m_AttackRange);
        
        // ---- 检测范围（线框） ----
        Gizmos.color = m_DetectColor;
        Gizmos.DrawWireSphere(pos, m_DetectRange);
        
        // ---- 追击范围 ----
        Gizmos.color = new Color(0f, 1f, 0f, 0.3f);
        Gizmos.DrawWireSphere(pos, m_ChaseRange);
        
        // ---- 路径可视化 ----
        DrawWaypointPath();
        
        // ---- 包围盒 ----
        if (m_ShowBounds)
            DrawObjectBounds();
    }
    
    // 始终绘制（无论是否选中）——用于重要信息
    void OnDrawGizmos()
    {
        // 始终显示朝向箭头
        Gizmos.color = Color.blue;
        DrawArrow(transform.position, transform.forward * 1.5f);
        
        // 始终显示角色标识图标
        Gizmos.DrawIcon(transform.position + Vector3.up * 2f, 
            "enemy_icon.png", true, Color.red);
    }

    void DrawWaypointPath()
    {
        if (m_Waypoints == null || m_Waypoints.Length < 2) return;
        
        Gizmos.color = Color.cyan;
        
        // 绘制路径连线
        for (int i = 0; i < m_Waypoints.Length - 1; i++)
        {
            Gizmos.DrawLine(m_Waypoints[i], m_Waypoints[i + 1]);
        }
        
        // 绘制路径节点
        Gizmos.color = Color.yellow;
        foreach (var wp in m_Waypoints)
        {
            Gizmos.DrawSphere(wp, 0.15f);
        }
        
        // 起点和终点特殊标记
        if (m_Waypoints.Length > 0)
        {
            Gizmos.color = Color.green;
            Gizmos.DrawCube(m_Waypoints[0], Vector3.one * 0.3f);
            
            Gizmos.color = Color.red;
            Gizmos.DrawCube(m_Waypoints[m_Waypoints.Length - 1], Vector3.one * 0.3f);
        }
    }

    void DrawObjectBounds()
    {
        var renderers = GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0) return;
        
        Bounds totalBounds = renderers[0].bounds;
        foreach (var r in renderers)
            totalBounds.Encapsulate(r.bounds);
        
        // 保存当前matrix，切换到世界空间
        Matrix4x4 oldMatrix = Gizmos.matrix;
        Gizmos.matrix = Matrix4x4.identity;
        
        Gizmos.color = new Color(0.5f, 1f, 0.5f, 0.2f);
        Gizmos.DrawCube(totalBounds.center, totalBounds.size);
        Gizmos.color = Color.green;
        Gizmos.DrawWireCube(totalBounds.center, totalBounds.size);
        
        Gizmos.matrix = oldMatrix;
    }

    /// <summary>
    /// 绘制带箭头的方向线
    /// </summary>
    public static void DrawArrow(Vector3 origin, Vector3 direction, float arrowHeadSize = 0.3f)
    {
        Vector3 tip = origin + direction;
        Gizmos.DrawLine(origin, tip);
        
        // 箭头头部（三条短线）
        if (direction.sqrMagnitude < 0.001f) return;
        
        Vector3 right = Vector3.Cross(direction.normalized, Vector3.up);
        if (right.sqrMagnitude < 0.001f)
            right = Vector3.Cross(direction.normalized, Vector3.right);
        right.Normalize();
        Vector3 up = Vector3.Cross(direction.normalized, right);
        
        Gizmos.DrawLine(tip, tip - direction.normalized * arrowHeadSize + right * arrowHeadSize * 0.5f);
        Gizmos.DrawLine(tip, tip - direction.normalized * arrowHeadSize - right * arrowHeadSize * 0.5f);
        Gizmos.DrawLine(tip, tip - direction.normalized * arrowHeadSize + up    * arrowHeadSize * 0.5f);
    }
}
```

---

## 三、Handles系统：可交互编辑器工具

### 3.1 自定义Inspector交互Handles

```csharp
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif

/// <summary>
/// 视野锥角可视化与调节组件（配合自定义Editor）
/// </summary>
public class FieldOfViewVisualizer : MonoBehaviour
{
    [Range(10f, 360f)]
    public float ViewAngle = 90f;
    public float ViewRadius = 8f;
    public float HeightOffset = 1.5f;
    public LayerMask ObstacleMask;
    
    [HideInInspector] public Color GizmoColor = new Color(0f, 1f, 0f, 0.2f);
    
    /// <summary>
    /// 将角度转为视野方向
    /// </summary>
    public Vector3 AngleToDirection(float angleDeg, bool globalAngle)
    {
        if (!globalAngle)
            angleDeg += transform.eulerAngles.y;
        
        return new Vector3(
            Mathf.Sin(angleDeg * Mathf.Deg2Rad),
            0f,
            Mathf.Cos(angleDeg * Mathf.Deg2Rad)
        );
    }
}

#if UNITY_EDITOR
[CustomEditor(typeof(FieldOfViewVisualizer))]
public class FieldOfViewEditor : Editor
{
    private void OnSceneGUI()
    {
        var fov = (FieldOfViewVisualizer)target;
        
        Vector3 origin = fov.transform.position + Vector3.up * fov.HeightOffset;
        
        // ========== 使用Handles绘制视野扇形 ==========
        
        Handles.color = fov.GizmoColor;
        
        // 填充扇形
        float halfAngle = fov.ViewAngle * 0.5f;
        Vector3 leftDir  = fov.AngleToDirection(-halfAngle, false);
        Vector3 rightDir = fov.AngleToDirection( halfAngle, false);
        
        Handles.DrawSolidArc(
            origin,             // 圆弧中心
            Vector3.up,         // 法线
            leftDir,            // 起始方向
            fov.ViewAngle,      // 角度
            fov.ViewRadius      // 半径
        );
        
        // 边界线
        Handles.color = Color.green;
        Handles.DrawLine(origin, origin + leftDir  * fov.ViewRadius, 2f);
        Handles.DrawLine(origin, origin + rightDir * fov.ViewRadius, 2f);
        
        // 外弧线
        Handles.DrawWireArc(origin, Vector3.up, leftDir, fov.ViewAngle, fov.ViewRadius, 2f);
        
        // ========== 交互式半径调节手柄 ==========
        
        Handles.color = Color.yellow;
        
        EditorGUI.BeginChangeCheck();
        
        // 半径调节（FreeMoveHandle作为可拖动点）
        Vector3 radiusHandlePos = origin + fov.transform.forward * fov.ViewRadius;
        float newRadius = Handles.ScaleValueHandle(
            fov.ViewRadius,
            radiusHandlePos,
            Quaternion.identity,
            0.5f,
            Handles.DotHandleCap,
            0.1f
        );
        
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(fov, "Change FOV Radius");
            fov.ViewRadius = Mathf.Clamp(newRadius, 0.5f, 50f);
        }
        
        // ========== 角度调节弧形手柄 ==========
        
        Handles.color = Color.cyan;
        
        EditorGUI.BeginChangeCheck();
        
        // 左边界旋转手柄
        Quaternion leftRot = Quaternion.Euler(0f, -halfAngle, 0f) * fov.transform.rotation;
        Quaternion newLeftRot = Handles.Disc(
            leftRot,
            origin + leftDir * fov.ViewRadius * 0.7f,
            Vector3.up,
            0.4f,
            false,
            1f
        );
        
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(fov, "Change FOV Angle");
            float angleDiff = Quaternion.Angle(leftRot, newLeftRot);
            fov.ViewAngle = Mathf.Clamp(fov.ViewAngle + angleDiff * 2f, 5f, 360f);
        }
        
        // ========== 场景内文字标注 ==========
        
        GUIStyle labelStyle = new GUIStyle();
        labelStyle.normal.textColor = Color.white;
        labelStyle.fontSize = 12;
        labelStyle.fontStyle = FontStyle.Bold;
        
        Handles.Label(origin + Vector3.up * 0.3f + fov.transform.forward * fov.ViewRadius,
            $"R: {fov.ViewRadius:F1}m\n∠: {fov.ViewAngle:F0}°", labelStyle);
    }
}
#endif
```

---

## 四、运行时调试可视化框架

### 4.1 跨平台运行时Gizmos系统

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// 运行时可视化调试框架
/// 支持在运行时（非仅编辑器）绘制调试几何体
/// 使用GL API实现，编辑器和构建版本均可用
/// </summary>
public class RuntimeGizmos : MonoBehaviour
{
    private static RuntimeGizmos s_Instance;
    public static RuntimeGizmos Instance
    {
        get
        {
            if (s_Instance == null)
            {
                var go = new GameObject("[RuntimeGizmos]");
                DontDestroyOnLoad(go);
                s_Instance = go.AddComponent<RuntimeGizmos>();
            }
            return s_Instance;
        }
    }

    private Material m_LineMaterial;
    
    // 绘制命令列表（每帧末清除）
    private readonly List<DrawCommand> m_Commands = new List<DrawCommand>(256);

    private enum DrawType { Line, Sphere, Box, Arrow, Cross }

    private struct DrawCommand
    {
        public DrawType Type;
        public Vector3  Position;
        public Vector3  Direction;  // 用于Line终点 / Arrow方向
        public Vector3  Size;       // Box尺寸 / Sphere半径
        public Color    Color;
        public float    Duration;   // 显示时长（0=单帧）
        public float    CreateTime;
    }

    void Awake()
    {
        s_Instance = this;
        CreateLineMaterial();
    }

    void CreateLineMaterial()
    {
        Shader shader = Shader.Find("Hidden/Internal-Colored");
        m_LineMaterial = new Material(shader)
        {
            hideFlags = HideFlags.HideAndDontSave
        };
        m_LineMaterial.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
        m_LineMaterial.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        m_LineMaterial.SetInt("_Cull", (int)UnityEngine.Rendering.CullMode.Off);
        m_LineMaterial.SetInt("_ZWrite", 0);
    }

    // ==================== 静态API ====================

    public static void DrawLine(Vector3 from, Vector3 to, Color color, float duration = 0f)
    {
        Instance.m_Commands.Add(new DrawCommand
        {
            Type = DrawType.Line, Position = from, Direction = to,
            Color = color, Duration = duration, CreateTime = Time.time
        });
    }

    public static void DrawSphere(Vector3 center, float radius, Color color, float duration = 0f)
    {
        Instance.m_Commands.Add(new DrawCommand
        {
            Type = DrawType.Sphere, Position = center,
            Size = Vector3.one * radius, Color = color,
            Duration = duration, CreateTime = Time.time
        });
    }

    public static void DrawBox(Vector3 center, Vector3 size, Color color, float duration = 0f)
    {
        Instance.m_Commands.Add(new DrawCommand
        {
            Type = DrawType.Box, Position = center, Size = size,
            Color = color, Duration = duration, CreateTime = Time.time
        });
    }

    public static void DrawArrow(Vector3 origin, Vector3 direction, Color color, float duration = 0f)
    {
        Instance.m_Commands.Add(new DrawCommand
        {
            Type = DrawType.Arrow, Position = origin, Direction = direction,
            Color = color, Duration = duration, CreateTime = Time.time
        });
    }

    public static void DrawCross(Vector3 center, float size, Color color, float duration = 0f)
    {
        Instance.m_Commands.Add(new DrawCommand
        {
            Type = DrawType.Cross, Position = center,
            Size = Vector3.one * size, Color = color,
            Duration = duration, CreateTime = Time.time
        });
    }

    // ==================== 渲染 ====================

    void OnRenderObject()
    {
#if !RELEASE_BUILD  // 发布版本关闭
        if (m_LineMaterial == null) return;
        
        m_LineMaterial.SetPass(0);
        
        GL.PushMatrix();
        GL.MultMatrix(Matrix4x4.identity);
        
        float now = Time.time;
        
        for (int i = m_Commands.Count - 1; i >= 0; i--)
        {
            var cmd = m_Commands[i];
            
            // 过期命令移除
            if (cmd.Duration > 0f && now - cmd.CreateTime > cmd.Duration)
            {
                m_Commands.RemoveAt(i);
                continue;
            }
            
            GL.Begin(GL.LINES);
            GL.Color(cmd.Color);
            
            switch (cmd.Type)
            {
                case DrawType.Line:
                    GL.Vertex(cmd.Position);
                    GL.Vertex(cmd.Direction); // Direction存储终点
                    break;
                    
                case DrawType.Box:
                    DrawGLBox(cmd.Position, cmd.Size);
                    break;
                    
                case DrawType.Sphere:
                    DrawGLSphere(cmd.Position, cmd.Size.x, 16);
                    break;
                    
                case DrawType.Arrow:
                    DrawGLArrow(cmd.Position, cmd.Direction);
                    break;
                    
                case DrawType.Cross:
                    DrawGLCross(cmd.Position, cmd.Size.x);
                    break;
            }
            
            GL.End();
        }
        
        GL.PopMatrix();
        
        // 移除单帧命令（Duration == 0）
        m_Commands.RemoveAll(c => c.Duration <= 0f);
#endif
    }

    static void DrawGLBox(Vector3 center, Vector3 size)
    {
        Vector3 h = size * 0.5f;
        
        // 8个角点
        Vector3 v000 = center + new Vector3(-h.x, -h.y, -h.z);
        Vector3 v100 = center + new Vector3( h.x, -h.y, -h.z);
        Vector3 v010 = center + new Vector3(-h.x,  h.y, -h.z);
        Vector3 v110 = center + new Vector3( h.x,  h.y, -h.z);
        Vector3 v001 = center + new Vector3(-h.x, -h.y,  h.z);
        Vector3 v101 = center + new Vector3( h.x, -h.y,  h.z);
        Vector3 v011 = center + new Vector3(-h.x,  h.y,  h.z);
        Vector3 v111 = center + new Vector3( h.x,  h.y,  h.z);

        // 底面
        GL.Vertex(v000); GL.Vertex(v100);
        GL.Vertex(v100); GL.Vertex(v110);
        GL.Vertex(v110); GL.Vertex(v010);
        GL.Vertex(v010); GL.Vertex(v000);
        // 顶面
        GL.Vertex(v001); GL.Vertex(v101);
        GL.Vertex(v101); GL.Vertex(v111);
        GL.Vertex(v111); GL.Vertex(v011);
        GL.Vertex(v011); GL.Vertex(v001);
        // 竖边
        GL.Vertex(v000); GL.Vertex(v001);
        GL.Vertex(v100); GL.Vertex(v101);
        GL.Vertex(v010); GL.Vertex(v011);
        GL.Vertex(v110); GL.Vertex(v111);
    }

    static void DrawGLSphere(Vector3 center, float radius, int segments)
    {
        float step = 360f / segments * Mathf.Deg2Rad;
        
        for (int i = 0; i < segments; i++)
        {
            float a1 = i * step, a2 = (i + 1) * step;
            
            // XY平面圆
            GL.Vertex(center + new Vector3(Mathf.Cos(a1) * radius, Mathf.Sin(a1) * radius, 0));
            GL.Vertex(center + new Vector3(Mathf.Cos(a2) * radius, Mathf.Sin(a2) * radius, 0));
            
            // XZ平面圆
            GL.Vertex(center + new Vector3(Mathf.Cos(a1) * radius, 0, Mathf.Sin(a1) * radius));
            GL.Vertex(center + new Vector3(Mathf.Cos(a2) * radius, 0, Mathf.Sin(a2) * radius));
            
            // YZ平面圆
            GL.Vertex(center + new Vector3(0, Mathf.Cos(a1) * radius, Mathf.Sin(a1) * radius));
            GL.Vertex(center + new Vector3(0, Mathf.Cos(a2) * radius, Mathf.Sin(a2) * radius));
        }
    }

    static void DrawGLArrow(Vector3 origin, Vector3 direction)
    {
        Vector3 tip = origin + direction;
        GL.Vertex(origin); GL.Vertex(tip);
        
        if (direction.sqrMagnitude < 0.001f) return;
        
        float headLen = direction.magnitude * 0.2f;
        Vector3 dir = direction.normalized;
        
        Vector3 perp = Vector3.Cross(dir, 
            Mathf.Abs(dir.y) < 0.9f ? Vector3.up : Vector3.right).normalized;
        
        GL.Vertex(tip); GL.Vertex(tip - dir * headLen + perp * headLen * 0.5f);
        GL.Vertex(tip); GL.Vertex(tip - dir * headLen - perp * headLen * 0.5f);
    }

    static void DrawGLCross(Vector3 center, float size)
    {
        GL.Vertex(center - Vector3.right * size);   GL.Vertex(center + Vector3.right * size);
        GL.Vertex(center - Vector3.up    * size);   GL.Vertex(center + Vector3.up    * size);
        GL.Vertex(center - Vector3.forward * size); GL.Vertex(center + Vector3.forward * size);
    }
}
```

---

## 五、专项调试可视化组件库

### 5.1 AI状态可视化组件

```csharp
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif

/// <summary>
/// AI敌人调试可视化组件
/// 集成感知范围、路径、状态、视线检测等全套调试信息
/// </summary>
public class AIDebugVisualizer : MonoBehaviour
{
    [System.Flags]
    public enum DebugFlags
    {
        None         = 0,
        Detection    = 1 << 0,  // 感知范围
        Path         = 1 << 1,  // 行走路径
        State        = 1 << 2,  // AI状态
        LineOfSight  = 1 << 3,  // 视线检测
        Target       = 1 << 4,  // 目标信息
        All          = ~0
    }

    [Header("调试开关")]
    [SerializeField] private DebugFlags m_DebugFlags = DebugFlags.All;
    [SerializeField] private bool       m_ShowInGame = false; // 运行时显示

    // AI状态数据（由AI组件赋值）
    [HideInInspector] public string    CurrentState   = "Idle";
    [HideInInspector] public Transform CurrentTarget;
    [HideInInspector] public Vector3[] CurrentPath;
    [HideInInspector] public bool      HasLineOfSight;
    [HideInInspector] public float     DetectionLevel; // 0~1 警觉度

    void OnDrawGizmosSelected()
    {
        DrawAIGizmos();
    }

    void Update()
    {
        // 运行时调试绘制
        if (!m_ShowInGame) return;
        DrawRuntimeDebug();
    }

    void DrawAIGizmos()
    {
        if (m_DebugFlags.HasFlag(DebugFlags.Detection))
            DrawDetectionGizmos();
        if (m_DebugFlags.HasFlag(DebugFlags.Path))
            DrawPathGizmos();
        if (m_DebugFlags.HasFlag(DebugFlags.Target) && CurrentTarget != null)
            DrawTargetGizmos();
    }

    void DrawDetectionGizmos()
    {
        float detectRadius = 8f;
        float attackRadius = 2f;
        
        // 警觉度颜色渐变：绿→黄→红
        Color alertColor = Color.Lerp(
            Color.Lerp(Color.green, Color.yellow, DetectionLevel * 2f),
            Color.red,
            Mathf.Max(0f, DetectionLevel * 2f - 1f)
        );
        alertColor.a = 0.2f;
        
        Gizmos.color = alertColor;
        Gizmos.DrawSphere(transform.position, detectRadius);
        
        // 线框
        Gizmos.color = alertColor; Gizmos.color = new Color(alertColor.r, alertColor.g, alertColor.b, 1f);
        Gizmos.DrawWireSphere(transform.position, detectRadius);
        
        // 攻击范围（红色）
        Gizmos.color = new Color(1f, 0.2f, 0.2f, 0.15f);
        Gizmos.DrawSphere(transform.position, attackRadius);
        Gizmos.color = Color.red;
        Gizmos.DrawWireSphere(transform.position, attackRadius);
    }

    void DrawPathGizmos()
    {
        if (CurrentPath == null || CurrentPath.Length < 2) return;
        
        Gizmos.color = Color.cyan;
        for (int i = 0; i < CurrentPath.Length - 1; i++)
        {
            Gizmos.DrawLine(CurrentPath[i], CurrentPath[i + 1]);
            Gizmos.DrawSphere(CurrentPath[i], 0.1f);
        }
        // 终点
        Gizmos.color = Color.magenta;
        Gizmos.DrawSphere(CurrentPath[CurrentPath.Length - 1], 0.2f);
    }

    void DrawTargetGizmos()
    {
        // 视线连线
        Gizmos.color = HasLineOfSight ? Color.red : Color.yellow;
        Gizmos.DrawLine(
            transform.position + Vector3.up * 1.5f,
            CurrentTarget.position + Vector3.up * 1f
        );
        
        // 目标标记
        Gizmos.color = Color.red;
        Gizmos.DrawWireSphere(CurrentTarget.position, 0.5f);
    }

    void DrawRuntimeDebug()
    {
        if (m_DebugFlags.HasFlag(DebugFlags.Path) && CurrentPath != null)
        {
            for (int i = 0; i < CurrentPath.Length - 1; i++)
            {
                RuntimeGizmos.DrawLine(CurrentPath[i], CurrentPath[i + 1], Color.cyan);
                RuntimeGizmos.DrawCross(CurrentPath[i], 0.15f, Color.cyan);
            }
        }

        if (m_DebugFlags.HasFlag(DebugFlags.Target) && CurrentTarget != null)
        {
            Color lineColor = HasLineOfSight ? Color.red : Color.yellow;
            RuntimeGizmos.DrawLine(
                transform.position + Vector3.up * 1.5f,
                CurrentTarget.position,
                lineColor
            );
        }
    }

#if UNITY_EDITOR
    void OnDrawGizmos()
    {
        if (!m_DebugFlags.HasFlag(DebugFlags.State)) return;
        
        // 场景内状态标注
        Vector3 labelPos = transform.position + Vector3.up * 2.5f;
        
        GUIStyle style = new GUIStyle();
        style.normal.textColor = GetStateColor();
        style.fontSize = 11;
        style.alignment = TextAnchor.MiddleCenter;
        style.fontStyle = FontStyle.Bold;
        
        Handles.Label(labelPos, $"[{CurrentState}]\n警觉: {DetectionLevel:P0}", style);
    }

    Color GetStateColor()
    {
        return CurrentState switch
        {
            "Idle"    => Color.gray,
            "Patrol"  => Color.green,
            "Alert"   => Color.yellow,
            "Chase"   => new Color(1f, 0.5f, 0f),
            "Attack"  => Color.red,
            "Dead"    => new Color(0.4f, 0.4f, 0.4f),
            _         => Color.white
        };
    }
#endif
}
```

---

## 六、条件编译调试开关系统

### 6.1 全局调试编译符管理

```csharp
// 在 Player Settings > Scripting Define Symbols 中配置：
// DEBUG_GIZMOS     - 启用所有调试Gizmos
// DEBUG_AI         - 启用AI调试可视化
// DEBUG_PHYSICS    - 启用物理调试
// DEBUG_NETWORK    - 启用网络调试

using UnityEngine;

/// <summary>
/// 调试可视化系统的条件编译入口
/// 发布版本自动剥离，零性能开销
/// </summary>
public static class DebugDraw
{
    // 使用 Conditional Attribute 实现零成本条件编译
    // 相比 #if 宏，Conditional 更优雅，调用处不需要包裹 #if
    
    [System.Diagnostics.Conditional("DEBUG_GIZMOS")]
    public static void Line(Vector3 from, Vector3 to, Color color, float duration = 0f)
    {
        RuntimeGizmos.DrawLine(from, to, color, duration);
    }

    [System.Diagnostics.Conditional("DEBUG_GIZMOS")]
    public static void Sphere(Vector3 center, float radius, Color color, float duration = 0f)
    {
        RuntimeGizmos.DrawSphere(center, radius, color, duration);
    }

    [System.Diagnostics.Conditional("DEBUG_GIZMOS")]
    public static void Arrow(Vector3 origin, Vector3 direction, Color color, float duration = 0f)
    {
        RuntimeGizmos.DrawArrow(origin, direction, color, duration);
    }

    [System.Diagnostics.Conditional("DEBUG_AI")]
    public static void AIPath(Vector3[] path, Color color, float duration = 0f)
    {
        if (path == null) return;
        for (int i = 0; i < path.Length - 1; i++)
            RuntimeGizmos.DrawLine(path[i], path[i + 1], color, duration);
    }

    [System.Diagnostics.Conditional("DEBUG_PHYSICS")]
    public static void PhysicsRaycast(Vector3 origin, Vector3 direction, float distance, bool hit)
    {
        Color c = hit ? Color.red : Color.green;
        RuntimeGizmos.DrawArrow(origin, direction.normalized * distance, c, 0f);
        if (hit)
            RuntimeGizmos.DrawCross(origin + direction.normalized * distance, 0.2f, Color.red, 0f);
    }
    
    /// <summary>
    /// 在屏幕上打印调试信息（类似GUI.Label，不受3D坐标影响）
    /// </summary>
    [System.Diagnostics.Conditional("DEBUG_GIZMOS")]
    public static void ScreenLog(string message, int line = 0, Color? color = null)
    {
        // 需要配合OnGUI使用，这里提供接口定义
        DebugOverlayGUI.AddMessage(message, line, color ?? Color.white);
    }
}

/// <summary>
/// 屏幕叠层调试信息管理器
/// </summary>
public class DebugOverlayGUI : MonoBehaviour
{
    private static readonly Dictionary<int, (string msg, Color col, float time)> s_Messages
        = new Dictionary<int, (string, Color, float)>(16);
    
    public static void AddMessage(string msg, int line, Color color)
    {
        s_Messages[line] = (msg, color, Time.realtimeSinceStartup);
    }

#if DEBUG_GIZMOS
    void OnGUI()
    {
        float now = Time.realtimeSinceStartup;
        GUIStyle style = new GUIStyle(GUI.skin.label) { fontSize = 13 };
        
        foreach (var kv in s_Messages)
        {
            // 超过2秒过期
            if (now - kv.Value.time > 2f) continue;
            
            style.normal.textColor = kv.Value.col;
            GUI.Label(
                new Rect(10, 10 + kv.Key * 22, 600, 20),
                kv.Value.msg,
                style
            );
        }
    }
#endif
}

// Dictionary 扩展（DebugOverlayGUI需要）
using System.Collections.Generic;
```

---

## 七、ScriptableObject驱动的调试配置

### 7.1 全局调试配置资产

```csharp
using UnityEngine;

/// <summary>
/// 调试可视化全局配置ScriptableObject
/// 设计师和程序员可在不改代码的情况下调整调试显示
/// </summary>
[CreateAssetMenu(fileName = "DebugConfig", menuName = "Debug/Debug Visualization Config")]
public class DebugVisualizationConfig : ScriptableObject
{
    private static DebugVisualizationConfig s_Instance;
    public static DebugVisualizationConfig Instance
    {
        get
        {
            if (s_Instance == null)
                s_Instance = Resources.Load<DebugVisualizationConfig>("DebugConfig");
            return s_Instance;
        }
    }

    [Header("AI调试")]
    public bool  ShowAIRanges     = true;
    public bool  ShowAIPath       = true;
    public bool  ShowAIState      = true;
    public Color DetectionColor   = new Color(1f, 1f, 0f, 0.15f);
    public Color AttackColor      = new Color(1f, 0.2f, 0.2f, 0.2f);
    public Color PathColor        = Color.cyan;

    [Header("物理调试")]
    public bool  ShowColliders    = false;
    public bool  ShowRaycasts     = true;
    public Color ColliderColor    = new Color(0f, 1f, 0f, 0.1f);

    [Header("网络调试")]
    public bool  ShowPrediction   = false;
    public bool  ShowLatency      = false;
    public Color PredictionColor  = Color.magenta;

    [Header("相机调试")]
    public bool  ShowFrustum      = false;
    public bool  ShowOcclusionCull = false;

    [Header("性能配置")]
    public int   MaxDebugLines    = 1000; // 限制调试线段数量
    public float GizmoLineWidth   = 1f;
}
```

---

## 八、最佳实践总结

### 8.1 Gizmos设计原则

1. **分层显示**：用`OnDrawGizmos`显示始终重要的信息，`OnDrawGizmosSelected`显示详细信息，避免场景中信息密度过高
2. **颜色语义化**：建立全项目统一的Gizmos颜色约定（红=攻击/危险，黄=警戒，绿=正常/路径，蓝=朝向）
3. **尺寸适配**：Gizmos大小应与实际游戏单位匹配，球体半径等于实际感知半径

### 8.2 运行时调试框架要点

1. **Conditional Attribute优于#if宏**：`[System.Diagnostics.Conditional("SYMBOL")]`让调用处代码更整洁
2. **发布版本零开销**：运行时调试绘制必须通过编译符完全剥离，不允许有任何运行时检查开销
3. **调试命令生命周期管理**：持续显示的调试几何体必须设置Duration，防止内存无限增长
4. **批量提交GL命令**：将同类型绘制命令合并到同一个`GL.Begin/End`块，减少API调用开销

### 8.3 编辑器工具开发规范

1. **Undo支持**：所有通过Handles修改的数据必须包裹`Undo.RecordObject()`
2. **序列化感知**：Handles修改后调用`EditorUtility.SetDirty(target)`确保数据持久化
3. **多选支持**：自定义Inspector考虑`Selection.objects`多选场景，避免只处理单一对象
4. **编辑器代码隔离**：Editor类代码必须置于`#if UNITY_EDITOR`或`Editor/`文件夹，防止污染运行时

### 8.4 团队协作建议

| 调试信息类型 | 推荐方案 | 说明 |
|-------------|----------|------|
| AI感知范围 | OnDrawGizmosSelected | 选中时查看，不干扰整体场景 |
| 导航路径 | Runtime + 条件编译 | 需要运行时观察实际路径 |
| 碰撞体轮廓 | Scene视图的Physics Debug | Unity内置，无需额外代码 |
| 帧率/性能数字 | 独立DebugOverlayGUI | 屏幕叠层，不占用Scene空间 |
| 网络状态 | 专用调试Panel + Log | 频繁更新数据适合Panel展示 |
| 技能范围预览 | Handles（编辑器）+ 运行时粒子 | 策划需要可视化调节参数 |

---

> **总结**：完善的可视化调试系统是提升游戏开发效率的重要工具，它让程序员、策划、设计师都能直观地理解游戏逻辑的运行状态。好的Gizmos设计应该做到：编辑时辅助配置、运行时辅助诊断、发布时零开销。通过ScriptableObject驱动调试配置，结合条件编译精确控制构建产物，是大型项目中调试可视化系统工程化的最佳实践。
