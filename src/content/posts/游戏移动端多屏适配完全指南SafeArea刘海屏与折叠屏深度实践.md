---
title: 游戏移动端多屏适配完全指南：SafeArea、刘海屏与折叠屏深度实践
published: 2026-04-22
description: 深度解析移动游戏的屏幕适配体系，涵盖安全区域（SafeArea）处理、异形屏刘海/挖孔/水滴适配、折叠屏双屏响应式UI设计、多分辨率自适应布局与动态Canvas缩放策略，附完整Unity实现代码。
tags: [Unity, UI适配, SafeArea, 移动端, 刘海屏, 折叠屏]
category: UI开发
draft: false
---

# 游戏移动端多屏适配完全指南：SafeArea、刘海屏与折叠屏深度实践

## 一、移动端屏幕碎片化现状

现代移动端游戏需要适配的屏幕形态极为多样：

| 设备类型 | 代表机型 | 主要挑战 |
|----------|----------|----------|
| 传统全面屏 | iPhone SE、小米9 | 基础多分辨率适配 |
| 刘海屏 | iPhone X/12/14 | 顶部刘海遮挡UI |
| 挖孔屏 | 三星 S21/S23 | 圆形/椭圆摄像头遮挡 |
| 水滴屏 | OPPO Reno系列 | 小型水滴区域避让 |
| 折叠屏 | 三星 Z Fold 4/5 | 内外屏切换，展开/折叠响应 |
| 平板 | iPad Pro | 超大屏幕，16:9内容两侧留白 |
| 超宽屏 | Xperia 1系列 | 21:9极端宽高比 |

---

## 二、安全区域（Safe Area）基础原理

### 2.1 什么是Safe Area

**Safe Area** 是设备屏幕中可安全显示交互UI的矩形区域，排除了：
- 刘海/挖孔（顶部）
- 底部Home手势条（iOS）
- 系统状态栏（部分安卓）

Unity通过 `Screen.safeArea` 提供当前设备的安全区矩形（像素坐标系）。

```csharp
// Screen.safeArea 返回的是像素坐标系的 Rect
// x, y：左下角偏移
// width, height：安全区尺寸
Rect safeArea = Screen.safeArea;

// 示例（iPhone 14 Pro，2556x1179，刘海高度约59px）：
// safeArea = Rect(0, 34, 2556, 2454)  竖屏
// safeArea = Rect(59, 0, 2438, 1179)  横屏（左右各避开刘海）
```

### 2.2 Safe Area适配核心组件

```csharp
using UnityEngine;

/// <summary>
/// Safe Area适配器：自动将UI RectTransform适配到安全区域
/// 挂载到需要避开异形屏区域的UI根节点上
/// </summary>
[RequireComponent(typeof(RectTransform))]
public class SafeAreaAdapter : MonoBehaviour
{
    [Header("适配配置")]
    [Tooltip("是否适配左侧（横屏刘海侧）")]
    public bool AdaptLeft = true;
    [Tooltip("是否适配右侧")]
    public bool AdaptRight = true;
    [Tooltip("是否适配顶部（刘海/状态栏）")]
    public bool AdaptTop = true;
    [Tooltip("是否适配底部（Home条）")]
    public bool AdaptBottom = true;
    
    [Header("调试")]
    [Tooltip("强制模拟刘海屏（编辑器测试用）")]
    public bool SimulateNotch = false;
    public Vector4 SimulatedInsets = new Vector4(59, 34, 0, 34); // left, top, right, bottom
    
    private RectTransform _rectTransform;
    private Rect _lastSafeArea;
    private Vector2Int _lastScreenSize;
    private ScreenOrientation _lastOrientation;
    
    private void Awake()
    {
        _rectTransform = GetComponent<RectTransform>();
    }
    
    private void Start()
    {
        Apply();
    }
    
    private void Update()
    {
        // 检测屏幕变化（旋转、折叠屏展开/收起）
        if (HasScreenChanged())
        {
            Apply();
        }
    }
    
    private bool HasScreenChanged()
    {
        return Screen.safeArea != _lastSafeArea 
            || Screen.width != _lastScreenSize.x 
            || Screen.height != _lastScreenSize.y
            || Screen.orientation != _lastOrientation;
    }
    
    private void Apply()
    {
        _lastSafeArea = Screen.safeArea;
        _lastScreenSize = new Vector2Int(Screen.width, Screen.height);
        _lastOrientation = Screen.orientation;
        
        Rect safeArea = Screen.safeArea;
        
#if UNITY_EDITOR
        // 编辑器中模拟异形屏
        if (SimulateNotch)
        {
            safeArea = GetSimulatedSafeArea();
        }
#endif
        
        ApplySafeArea(safeArea);
    }
    
    private void ApplySafeArea(Rect safeArea)
    {
        float screenWidth = Screen.width;
        float screenHeight = Screen.height;
        
        // 计算归一化的anchorMin和anchorMax
        Vector2 anchorMin = safeArea.position;
        Vector2 anchorMax = safeArea.position + safeArea.size;
        
        anchorMin.x /= screenWidth;
        anchorMin.y /= screenHeight;
        anchorMax.x /= screenWidth;
        anchorMax.y /= screenHeight;
        
        // 根据配置选择性适配
        if (!AdaptLeft)  anchorMin.x = 0f;
        if (!AdaptBottom) anchorMin.y = 0f;
        if (!AdaptRight) anchorMax.x = 1f;
        if (!AdaptTop)   anchorMax.y = 1f;
        
        _rectTransform.anchorMin = anchorMin;
        _rectTransform.anchorMax = anchorMax;
        _rectTransform.offsetMin = Vector2.zero;
        _rectTransform.offsetMax = Vector2.zero;
        
        Debug.Log($"[SafeArea] 已适配 | 屏幕:{screenWidth}x{screenHeight} " +
                  $"| 安全区:{safeArea} | AnchorMin:{anchorMin} AnchorMax:{anchorMax}");
    }
    
    private Rect GetSimulatedSafeArea()
    {
        // SimulatedInsets: left, top, right, bottom (像素)
        float x = SimulatedInsets.x;
        float y = SimulatedInsets.w; // bottom
        float w = Screen.width - SimulatedInsets.x - SimulatedInsets.z;
        float h = Screen.height - SimulatedInsets.y - SimulatedInsets.w;
        return new Rect(x, y, w, h);
    }
}
```

---

## 三、UI层级架构设计

### 3.1 分层适配架构

```
Canvas (Screen Space - Camera)
├── FullScreenLayer          ← 全屏背景、过场动画（不适配SafeArea）
│   └── BackgroundImage
│
├── SafeAreaRoot             ← 挂载SafeAreaAdapter（所有可交互UI的根）
│   ├── HUDLayer             ← 游戏HUD（血条/技能栏）
│   │   ├── TopHUD           ← 头像/积分
│   │   └── BottomHUD        ← 技能按钮
│   ├── MenuLayer            ← 菜单界面
│   └── PopupLayer           ← 弹窗
│
└── SystemLayer              ← 系统UI（加载遮罩）（不适配SafeArea）
```

```csharp
// UI管理器中的SafeArea根节点管理
public class UIManager : MonoBehaviour
{
    [SerializeField] private Transform _fullScreenLayer;
    [SerializeField] private Transform _safeAreaRoot;   // 挂有SafeAreaAdapter
    [SerializeField] private Transform _systemLayer;
    
    // 根据UI类型决定挂载到哪一层
    public void OpenPanel(UIPanel panel)
    {
        Transform parent = panel.IgnoreSafeArea ? _fullScreenLayer : _safeAreaRoot;
        panel.transform.SetParent(parent, false);
        panel.gameObject.SetActive(true);
    }
}
```

### 3.2 多Canvas方案

```csharp
/// <summary>
/// 多Canvas方案：不同层使用不同Canvas的SafeArea适配
/// 适合UI层独立渲染需求（如HUD需要在3D物体之上渲染）
/// </summary>
public class MultiCanvasSafeAreaManager : MonoBehaviour
{
    [System.Serializable]
    public class CanvasLayer
    {
        public string LayerName;
        public Canvas Canvas;
        public bool UseSafeArea;
        public RectTransform SafeAreaRoot; // Canvas下的安全区根节点
    }
    
    [SerializeField] private List<CanvasLayer> _layers;
    private SafeAreaAdapter[] _adapters;
    
    private void Awake()
    {
        // 为所有需要SafeArea的层初始化适配器
        foreach (var layer in _layers)
        {
            if (layer.UseSafeArea && layer.SafeAreaRoot != null)
            {
                var adapter = layer.SafeAreaRoot.gameObject.AddComponent<SafeAreaAdapter>();
                adapter.AdaptTop = true;
                adapter.AdaptBottom = true;
                adapter.AdaptLeft = true;
                adapter.AdaptRight = true;
            }
        }
    }
}
```

---

## 四、折叠屏适配

### 4.1 折叠屏的UI挑战

折叠屏（如三星 Z Fold 系列）在展开/折叠时会发生：
- **屏幕尺寸突变**：从约 6.2 英寸(竖屏)到约 7.6 英寸(展开)
- **宽高比变化**：从 23.1:9 → 接近 4:3 的方形屏幕
- **中缝区域**：展开时中间有折痕区域，交互元素不应放置在此

```csharp
using UnityEngine;
using System.Collections;

/// <summary>
/// 折叠屏检测与适配管理器
/// 支持实时响应展开/折叠事件
/// </summary>
public class FoldableScreenAdapter : MonoBehaviour
{
    public static FoldableScreenAdapter Instance { get; private set; }
    
    // 折叠状态枚举
    public enum FoldState
    {
        Unknown,
        Folded,         // 折叠（使用外屏）
        HalfFolded,     // 半折叠（桌面模式）
        Unfolded        // 展开（使用内屏）
    }
    
    public FoldState CurrentFoldState { get; private set; } = FoldState.Unknown;
    
    // 折叠状态变化事件
    public System.Action<FoldState, FoldState> OnFoldStateChanged;
    
    // 折痕区域（归一化坐标）
    public Rect FoldCreaseArea { get; private set; }
    
    private Vector2Int _lastScreenSize;
    private float _checkInterval = 0.1f;
    
    private void Awake()
    {
        Instance = this;
        _lastScreenSize = new Vector2Int(Screen.width, Screen.height);
        DetectFoldState();
        StartCoroutine(PollFoldState());
    }
    
    private IEnumerator PollFoldState()
    {
        while (true)
        {
            yield return new WaitForSeconds(_checkInterval);
            
            Vector2Int currentSize = new Vector2Int(Screen.width, Screen.height);
            if (currentSize != _lastScreenSize)
            {
                _lastScreenSize = currentSize;
                DetectFoldState();
            }
        }
    }
    
    private void DetectFoldState()
    {
        FoldState newState = DetermineFoldState();
        
        if (newState != CurrentFoldState)
        {
            FoldState oldState = CurrentFoldState;
            CurrentFoldState = newState;
            
            // 更新折痕区域
            UpdateCreaseArea();
            
            OnFoldStateChanged?.Invoke(oldState, newState);
            Debug.Log($"[FoldableScreen] 状态变化: {oldState} → {newState} | " +
                      $"屏幕: {Screen.width}x{Screen.height} | 宽高比: {GetAspectRatio():F2}");
        }
    }
    
    private FoldState DetermineFoldState()
    {
        float aspectRatio = GetAspectRatio();
        int area = Screen.width * Screen.height;
        
        // 基于宽高比和屏幕面积推断折叠状态
        // 注意：精确检测需要 Android Jetpack WindowManager API（需要原生插件）
        if (aspectRatio >= 0.8f && aspectRatio <= 1.3f && area > 1500000)
        {
            // 接近方形且面积大 → 展开状态
            return FoldState.Unfolded;
        }
        else if (aspectRatio > 2.0f)
        {
            // 超宽 → 折叠状态（外屏通常是细长屏）
            return FoldState.Folded;
        }
        else
        {
            return FoldState.Unknown;
        }
    }
    
    private void UpdateCreaseArea()
    {
        if (CurrentFoldState == FoldState.Unfolded)
        {
            // 三星 Z Fold 系列折痕约在屏幕中央，宽度约1.5%
            FoldCreaseArea = new Rect(0.49f, 0f, 0.02f, 1f);
        }
        else
        {
            FoldCreaseArea = Rect.zero;
        }
    }
    
    private float GetAspectRatio()
    {
        return (float)Screen.width / Screen.height;
    }
    
    // 判断一个屏幕位置是否在折痕危险区域内
    public bool IsInCreaseArea(Vector2 normalizedPosition)
    {
        if (FoldCreaseArea == Rect.zero) return false;
        return FoldCreaseArea.Contains(normalizedPosition);
    }
}
```

### 4.2 响应折叠状态的UI布局系统

```csharp
/// <summary>
/// 折叠屏响应式布局组件
/// 根据设备展开/折叠状态切换不同的UI布局配置
/// </summary>
public class FoldableUILayout : MonoBehaviour
{
    [System.Serializable]
    public class LayoutConfig
    {
        public string Name;
        public FoldableScreenAdapter.FoldState TargetState;
        public Vector2 AnchorMin;
        public Vector2 AnchorMax;
        public Vector2 OffsetMin;
        public Vector2 OffsetMax;
        public float FontSizeMultiplier = 1f;
        public bool IsVisible = true;
    }
    
    [SerializeField] private List<LayoutConfig> _layoutConfigs;
    [SerializeField] private RectTransform _targetRect;
    [SerializeField] private TMPro.TextMeshProUGUI _targetText;
    
    private float _baseFontSize;
    
    private void Start()
    {
        if (_targetText != null)
            _baseFontSize = _targetText.fontSize;
            
        if (FoldableScreenAdapter.Instance != null)
        {
            FoldableScreenAdapter.Instance.OnFoldStateChanged += OnFoldStateChanged;
            ApplyLayout(FoldableScreenAdapter.Instance.CurrentFoldState);
        }
    }
    
    private void OnFoldStateChanged(FoldableScreenAdapter.FoldState oldState, 
                                    FoldableScreenAdapter.FoldState newState)
    {
        // 平滑过渡动画
        StartCoroutine(AnimateLayoutTransition(newState));
    }
    
    private System.Collections.IEnumerator AnimateLayoutTransition(
        FoldableScreenAdapter.FoldState targetState)
    {
        var config = _layoutConfigs.Find(c => c.TargetState == targetState);
        if (config == null) yield break;
        
        // 0.3秒过渡动画
        float duration = 0.3f;
        float elapsed = 0f;
        
        Vector2 startAnchorMin = _targetRect.anchorMin;
        Vector2 startAnchorMax = _targetRect.anchorMax;
        
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0, 1, elapsed / duration);
            
            _targetRect.anchorMin = Vector2.Lerp(startAnchorMin, config.AnchorMin, t);
            _targetRect.anchorMax = Vector2.Lerp(startAnchorMax, config.AnchorMax, t);
            
            yield return null;
        }
        
        ApplyLayout(targetState);
    }
    
    private void ApplyLayout(FoldableScreenAdapter.FoldState state)
    {
        var config = _layoutConfigs.Find(c => c.TargetState == state);
        if (config == null) return;
        
        if (_targetRect != null)
        {
            _targetRect.anchorMin = config.AnchorMin;
            _targetRect.anchorMax = config.AnchorMax;
            _targetRect.offsetMin = config.OffsetMin;
            _targetRect.offsetMax = config.OffsetMax;
        }
        
        if (_targetText != null)
            _targetText.fontSize = _baseFontSize * config.FontSizeMultiplier;
            
        gameObject.SetActive(config.IsVisible);
    }
}
```

---

## 五、Canvas Scaler 多分辨率策略

### 5.1 Reference Resolution 选择策略

```csharp
// Canvas Scaler 配置最佳实践
// Scale With Screen Size 模式参数选择

[RequireComponent(typeof(Canvas))]
public class AdaptiveCanvasScaler : MonoBehaviour
{
    private UnityEngine.UI.CanvasScaler _scaler;
    
    // 游戏类型推荐配置
    [System.Serializable]
    public class ScalerProfile
    {
        public string ProfileName;
        public Vector2 ReferenceResolution;
        public float MatchWidthOrHeight;  // 0=匹配宽度, 1=匹配高度
        public float ScreenMatchMode;
    }
    
    private static readonly ScalerProfile[] Profiles = {
        // 横版手游（竖屏显示横向内容）
        new ScalerProfile {
            ProfileName = "横版手游",
            ReferenceResolution = new Vector2(1920, 1080),
            MatchWidthOrHeight = 1f  // 匹配高度，宽度自适应（防止超宽手机两侧被裁）
        },
        // 竖版手游（类似二次元抽卡游戏）
        new ScalerProfile {
            ProfileName = "竖版手游",
            ReferenceResolution = new Vector2(1080, 1920),
            MatchWidthOrHeight = 0f  // 匹配宽度，高度自适应（防止长屏手机底部被裁）
        },
        // 平板/横竖均支持
        new ScalerProfile {
            ProfileName = "多方向适配",
            ReferenceResolution = new Vector2(1334, 750),  // 基于iPhone标准
            MatchWidthOrHeight = 0.5f  // 中间值，兼顾宽高变化
        }
    };
    
    [SerializeField] private string _profileName = "横版手游";
    
    private void Awake()
    {
        _scaler = GetComponent<UnityEngine.UI.CanvasScaler>();
        ApplyProfile(_profileName);
    }
    
    public void ApplyProfile(string profileName)
    {
        var profile = System.Array.Find(Profiles, p => p.ProfileName == profileName);
        if (profile == null) return;
        
        _scaler.uiScaleMode = UnityEngine.UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;
        _scaler.referenceResolution = profile.ReferenceResolution;
        _scaler.matchWidthOrHeight = profile.MatchWidthOrHeight;
        _scaler.screenMatchMode = UnityEngine.UI.CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
    }
}
```

### 5.2 极端宽高比的内容区域限制

```csharp
/// <summary>
/// 内容安全框：在超宽/超高屏幕上，将游戏内容限制在合理宽高比范围内
/// 类似 Letterbox / Pillarbox 效果
/// </summary>
public class ContentSafeFrame : MonoBehaviour
{
    [Header("内容区域宽高比限制")]
    [Tooltip("允许的最大宽高比（如 2.1 表示不超过 21:9）")]
    public float MaxAspectRatio = 2.1f;
    [Tooltip("允许的最小宽高比（如 1.33 表示不低于 4:3）")]
    public float MinAspectRatio = 1.33f;
    
    [Header("填充区域颜色（黑边）")]
    public Color LetterboxColor = Color.black;
    
    private Camera _camera;
    private float _lastAspect;
    
    private void Awake()
    {
        _camera = GetComponent<Camera>();
    }
    
    private void Update()
    {
        float currentAspect = (float)Screen.width / Screen.height;
        if (Mathf.Abs(currentAspect - _lastAspect) > 0.01f)
        {
            _lastAspect = currentAspect;
            ApplySafeFrame(currentAspect);
        }
    }
    
    private void ApplySafeFrame(float screenAspect)
    {
        float targetAspect = Mathf.Clamp(screenAspect, MinAspectRatio, MaxAspectRatio);
        
        if (Mathf.Abs(screenAspect - targetAspect) < 0.001f)
        {
            // 宽高比在合理范围内，全屏显示
            _camera.rect = new Rect(0, 0, 1, 1);
            return;
        }
        
        float scaleX = targetAspect / screenAspect;
        float scaleY = 1f;
        
        if (screenAspect > MaxAspectRatio)
        {
            // 超宽屏：左右加黑边（Pillarbox）
            scaleX = targetAspect / screenAspect;
            float offsetX = (1f - scaleX) / 2f;
            _camera.rect = new Rect(offsetX, 0, scaleX, 1);
        }
        else if (screenAspect < MinAspectRatio)
        {
            // 超高屏（如竖屏平板）：上下加黑边（Letterbox）
            scaleY = screenAspect / targetAspect;
            float offsetY = (1f - scaleY) / 2f;
            _camera.rect = new Rect(0, offsetY, 1, scaleY);
        }
        
        // 设置黑边背景色
        _camera.backgroundColor = LetterboxColor;
        
        Debug.Log($"[ContentFrame] 实际宽高比:{screenAspect:F2} → 目标:{targetAspect:F2} | " +
                  $"视口:{_camera.rect}");
    }
}
```

---

## 六、刘海屏/挖孔屏实战处理

### 6.1 顶部HUD避开刘海的精确计算

```csharp
/// <summary>
/// 专门处理状态栏/刘海区域的UI避让工具
/// 比通用SafeAreaAdapter更精细，支持单独控制顶部元素位置
/// </summary>
public static class NotchHelper
{
    /// <summary>
    /// 获取顶部安全距离（像素）
    /// </summary>
    public static float GetTopInset()
    {
        Rect safeArea = Screen.safeArea;
        float screenHeight = Screen.height;
        // safeArea.y 是底部inset（距底部像素），safeArea.height是安全区高度
        // 顶部inset = screenHeight - (safeArea.y + safeArea.height)
        return screenHeight - (safeArea.y + safeArea.height);
    }
    
    /// <summary>
    /// 获取底部安全距离（像素，Home条高度）
    /// </summary>
    public static float GetBottomInset()
    {
        return Screen.safeArea.y;
    }
    
    /// <summary>
    /// 获取左侧安全距离（横屏时刘海侧）
    /// </summary>
    public static float GetLeftInset()
    {
        return Screen.safeArea.x;
    }
    
    /// <summary>
    /// 获取右侧安全距离
    /// </summary>
    public static float GetRightInset()
    {
        return Screen.width - (Screen.safeArea.x + Screen.safeArea.width);
    }
    
    /// <summary>
    /// 将顶部元素（如积分栏）精确定位在刘海下方
    /// </summary>
    public static void PositionBelowNotch(RectTransform element, float extraPadding = 8f)
    {
        Canvas canvas = element.GetComponentInParent<Canvas>();
        if (canvas == null) return;
        
        // 将像素距离转换为Canvas空间
        float pixelsPerUnit = canvas.scaleFactor;
        float topInsetInCanvasSpace = GetTopInset() / pixelsPerUnit;
        
        // 设置element的top偏移，确保它在刘海下方
        Vector2 offsetMin = element.offsetMin;
        Vector2 offsetMax = element.offsetMax;
        offsetMax.y = -(topInsetInCanvasSpace + extraPadding);
        element.offsetMax = offsetMax;
    }
    
    /// <summary>
    /// 检测当前设备是否有刘海
    /// </summary>
    public static bool HasNotch()
    {
        return GetTopInset() > 20f; // 超过20像素认为有刘海/状态栏特殊区域
    }
    
    /// <summary>
    /// 检测是否有底部Home手势条
    /// </summary>
    public static bool HasHomeIndicator()
    {
        return GetBottomInset() > 10f;
    }
}
```

### 6.2 编辑器中模拟不同设备

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

/// <summary>
/// 编辑器工具：模拟各种异形屏设备的Safe Area
/// </summary>
public class SafeAreaSimulatorWindow : EditorWindow
{
    [MenuItem("Tools/UI适配/Safe Area模拟器")]
    public static void ShowWindow()
    {
        GetWindow<SafeAreaSimulatorWindow>("Safe Area 模拟器");
    }
    
    private static readonly DeviceProfile[] Devices = {
        new DeviceProfile { Name = "iPhone 14 Pro (2556x1179)", 
            Width=2556, Height=1179, 
            SafeArea=new Rect(0, 34, 2556, 2454) }, // 竖屏暂用假数据示意
        new DeviceProfile { Name = "iPhone 14 Pro 横屏", 
            Width=2556, Height=1179, 
            SafeArea=new Rect(59, 0, 2438, 1179) },
        new DeviceProfile { Name = "三星 S23 挖孔屏 (2340x1080)", 
            Width=2340, Height=1080, 
            SafeArea=new Rect(0, 48, 2340, 2256) },
        new DeviceProfile { Name = "Samsung Z Fold 5 展开 (2176x1812)", 
            Width=2176, Height=1812, 
            SafeArea=new Rect(0, 0, 2176, 1812) },
        new DeviceProfile { Name = "标准16:9 (1920x1080)", 
            Width=1920, Height=1080, 
            SafeArea=new Rect(0, 0, 1920, 1080) },
    };
    
    [System.Serializable]
    private class DeviceProfile
    {
        public string Name;
        public int Width, Height;
        public Rect SafeArea;
    }
    
    private int _selectedDevice = 0;
    
    private void OnGUI()
    {
        GUILayout.Label("选择模拟设备", EditorStyles.boldLabel);
        
        string[] names = System.Array.ConvertAll(Devices, d => d.Name);
        _selectedDevice = EditorGUILayout.Popup("设备", _selectedDevice, names);
        
        var device = Devices[_selectedDevice];
        
        EditorGUILayout.LabelField($"屏幕尺寸: {device.Width} x {device.Height}");
        EditorGUILayout.LabelField($"Safe Area: {device.SafeArea}");
        
        float topInset = device.Height - (device.SafeArea.y + device.SafeArea.height);
        float bottomInset = device.SafeArea.y;
        EditorGUILayout.LabelField($"顶部Inset: {topInset}px | 底部Inset: {bottomInset}px");
        
        EditorGUILayout.Space();
        
        if (GUILayout.Button("应用到场景中的SafeAreaAdapter"))
        {
            ApplySimulation(device);
        }
        
        if (GUILayout.Button("清除模拟"))
        {
            ClearSimulation();
        }
    }
    
    private void ApplySimulation(DeviceProfile device)
    {
        var adapters = FindObjectsOfType<SafeAreaAdapter>();
        foreach (var adapter in adapters)
        {
            adapter.SimulateNotch = true;
            // 设置模拟insets
            float left = device.SafeArea.x;
            float top = device.Height - (device.SafeArea.y + device.SafeArea.height);
            float right = device.Width - (device.SafeArea.x + device.SafeArea.width);
            float bottom = device.SafeArea.y;
            adapter.SimulatedInsets = new Vector4(left, top, right, bottom);
        }
        
        Debug.Log($"[SafeAreaSim] 已应用模拟设备: {device.Name}，影响 {adapters.Length} 个适配器");
    }
    
    private void ClearSimulation()
    {
        var adapters = FindObjectsOfType<SafeAreaAdapter>();
        foreach (var adapter in adapters)
        {
            adapter.SimulateNotch = false;
        }
    }
}
#endif
```

---

## 七、最佳实践总结

### 7.1 适配方案决策树

```
需要适配的UI元素
│
├── 是否为全屏背景/过场动画？
│   ├── 是 → 不需要SafeArea，全屏拉伸
│   └── 否 ↓
│
├── 是否为可交互UI（按钮/摇杆/技能）？
│   ├── 是 → 必须适配SafeArea + 考虑单手操作区域
│   └── 否 ↓
│
├── 是否为信息展示UI（HP/计分）？
│   ├── 是 → 适配SafeArea，确保在刘海外
│   └── 否 ↓
│
└── 是否为弹窗/菜单？
    └── 适配SafeArea，通常居中显示即可
```

### 7.2 多分辨率适配参数速查

| 游戏类型 | 参考分辨率 | Match值 | 说明 |
|----------|-----------|---------|------|
| 横版手游（固定横屏） | 1920×1080 | 1.0（高度） | 宽度自适应，防止超宽屏拉伸 |
| 竖版手游（固定竖屏） | 1080×1920 | 0.0（宽度） | 高度自适应，防止长屏裁切 |
| 支持旋转的游戏 | 1334×750 | 0.5 | 兼顾宽高变化 |
| 平板专项 | 2048×1536 | 0.5 | iPad Pro标准分辨率 |

### 7.3 测试矩阵建议

每次UI改动后，至少在以下设备/模拟配置上验证：
1. ✅ **标准16:9横屏**（如1920×1080）
2. ✅ **iPhone刘海竖屏**（如390×844，Safe Area顶部偏移）
3. ✅ **iPhone刘海横屏**（左侧/右侧刘海偏移）
4. ✅ **安卓挖孔屏**（顶部小圆形摄像头区域）
5. ✅ **超宽屏**（如21:9，宽高比2.33）
6. ✅ **折叠屏展开态**（接近1:1方形）
7. ✅ **平板横屏**（4:3比例，UI两侧延伸）

通过本文的系统性适配方案，游戏UI可以在市面上99%以上的移动设备上正确显示，为玩家提供一致的视觉体验。
