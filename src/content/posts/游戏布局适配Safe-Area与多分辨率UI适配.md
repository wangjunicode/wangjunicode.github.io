---
title: 游戏布局适配系统：Safe Area与多分辨率UI适配
published: 2026-03-31
description: 深度解析移动端游戏UI适配的完整方案，涵盖iPhone刘海/动态岛Safe Area适配、Android异形屏适配、Canvas Scaler多分辨率策略、世界空间UI位置适配、横竖屏切换布局重排、平板大屏适配，以及Runtime动态重布局最佳实践。
tags: [Unity, UI适配, Safe Area, 多分辨率, 移动端]
category: 游戏UI
draft: false
---

## 一、Safe Area 适配

### 问题背景
iPhone X/XS/11/12/13/14/15 系列的刘海/动态岛和底部 Home Indicator 会遮挡UI内容，需要将交互元素限制在 Safe Area 内。

```csharp
using UnityEngine;

/// <summary>
/// Safe Area 适配组件（挂在需要适配的根 RectTransform 上）
/// </summary>
[ExecuteAlways]
[RequireComponent(typeof(RectTransform))]
public class SafeAreaAdapter : MonoBehaviour
{
    [SerializeField] private bool adaptTop = true;
    [SerializeField] private bool adaptBottom = true;
    [SerializeField] private bool adaptLeft = true;
    [SerializeField] private bool adaptRight = true;

    private RectTransform rectTransform;
    private Rect lastSafeArea;
    private ScreenOrientation lastOrientation;

    void Awake() => rectTransform = GetComponent<RectTransform>();

    void OnEnable() => Apply();

    void LateUpdate()
    {
        // 旋转或分辨率变化时重新适配
        if (Screen.safeArea != lastSafeArea || 
            Screen.orientation != lastOrientation)
        {
            Apply();
        }
    }

    public void Apply()
    {
        lastSafeArea = Screen.safeArea;
        lastOrientation = Screen.orientation;

        Rect safeArea = Screen.safeArea;
        Vector2 screenSize = new Vector2(Screen.width, Screen.height);

        // 计算 AnchorMin 和 AnchorMax（归一化）
        Vector2 anchorMin = safeArea.position / screenSize;
        Vector2 anchorMax = (safeArea.position + safeArea.size) / screenSize;

        // 选择性适配（不需要适配的方向保持原值）
        if (!adaptLeft)  anchorMin.x = 0f;
        if (!adaptBottom) anchorMin.y = 0f;
        if (!adaptRight)  anchorMax.x = 1f;
        if (!adaptTop)    anchorMax.y = 1f;

        rectTransform.anchorMin = anchorMin;
        rectTransform.anchorMax = anchorMax;
        rectTransform.offsetMin = Vector2.zero;
        rectTransform.offsetMax = Vector2.zero;

        // Debug
        Debug.Log($"[SafeArea] Screen:{screenSize}, SafeArea:{safeArea}, " +
                  $"AnchorMin:{anchorMin}, AnchorMax:{anchorMax}");
    }

#if UNITY_EDITOR
    // 编辑器下模拟 iPhone 刘海 Safe Area
    [ContextMenu("Simulate iPhone 14 Pro Safe Area")]
    void SimulateiPhone14Pro()
    {
        Debug.Log("[SafeArea] Simulating iPhone 14 Pro");
        // 实际 Safe Area: 左右各 0px, 上 59px, 下 34px（375x812逻辑分辨率）
    }
#endif
}
```

---

## 二、Canvas Scaler 多分辨率策略

```csharp
/// <summary>
/// 运行时动态调整 Canvas Scaler
/// 根据设备宽高比选择匹配横屏/竖屏参考分辨率
/// </summary>
[RequireComponent(typeof(UnityEngine.UI.CanvasScaler))]
public class DynamicCanvasScaler : MonoBehaviour
{
    [Header("竖屏参考分辨率")]
    [SerializeField] private Vector2 portraitReference = new Vector2(750, 1334);
    
    [Header("横屏参考分辨率")]
    [SerializeField] private Vector2 landscapeReference = new Vector2(1334, 750);
    
    [Header("平板参考分辨率（宽高比 < 1.5）")]
    [SerializeField] private Vector2 tabletReference = new Vector2(1024, 768);
    
    private UnityEngine.UI.CanvasScaler scaler;
    private ScreenOrientation lastOrientation;

    void Awake()
    {
        scaler = GetComponent<UnityEngine.UI.CanvasScaler>();
        scaler.uiScaleMode = UnityEngine.UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.screenMatchMode = UnityEngine.UI.CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
        
        UpdateScaler();
    }

    void Update()
    {
        if (Screen.orientation != lastOrientation)
            UpdateScaler();
    }

    void UpdateScaler()
    {
        lastOrientation = Screen.orientation;
        float aspectRatio = (float)Screen.width / Screen.height;
        
        bool isTablet = aspectRatio < 1.5f && Screen.width >= 768;
        bool isLandscape = Screen.width > Screen.height;
        
        if (isTablet)
        {
            scaler.referenceResolution = tabletReference;
            scaler.matchWidthOrHeight = 0.5f; // 平衡宽高
        }
        else if (isLandscape)
        {
            scaler.referenceResolution = landscapeReference;
            scaler.matchWidthOrHeight = 1f; // 匹配高度
        }
        else
        {
            scaler.referenceResolution = portraitReference;
            scaler.matchWidthOrHeight = 0f; // 匹配宽度（竖屏常用）
        }
        
        Debug.Log($"[CanvasScaler] AspectRatio:{aspectRatio:F2}, " +
                  $"Ref:{scaler.referenceResolution}, Match:{scaler.matchWidthOrHeight}");
    }
}
```

---

## 三、横竖屏动态布局

```csharp
/// <summary>
/// 响应式布局：根据横竖屏切换 UI 布局
/// </summary>
public class ResponsiveLayout : MonoBehaviour
{
    [System.Serializable]
    public class OrientationLayout
    {
        public string GroupName;
        public RectTransform Target;
        
        [Header("横屏配置")]
        public Vector2 LandscapeAnchorMin;
        public Vector2 LandscapeAnchorMax;
        public Vector2 LandscapeAnchoredPos;
        public Vector2 LandscapeSizeDelta;
        
        [Header("竖屏配置")]
        public Vector2 PortraitAnchorMin;
        public Vector2 PortraitAnchorMax;
        public Vector2 PortraitAnchoredPos;
        public Vector2 PortraitSizeDelta;
    }

    [SerializeField] private OrientationLayout[] layouts;
    [SerializeField] private float transitionDuration = 0.3f;

    private bool isLandscape;

    void Start() => ApplyOrientation(Screen.width > Screen.height);

    void Update()
    {
        bool currentLandscape = Screen.width > Screen.height;
        if (currentLandscape != isLandscape)
        {
            isLandscape = currentLandscape;
            ApplyOrientation(isLandscape);
        }
    }

    void ApplyOrientation(bool landscape)
    {
        foreach (var layout in layouts)
        {
            if (layout.Target == null) continue;
            
            var target = layout.Target;
            
            if (transitionDuration > 0)
            {
                // 带动画的布局切换
                if (landscape)
                {
                    DG.Tweening.DOTween.To(
                        () => target.anchorMin,
                        v => target.anchorMin = v,
                        layout.LandscapeAnchorMin, transitionDuration);
                    DG.Tweening.DOTween.To(
                        () => target.anchorMax,
                        v => target.anchorMax = v,
                        layout.LandscapeAnchorMax, transitionDuration);
                    target.DOAnchorPos(layout.LandscapeAnchoredPos, transitionDuration);
                    target.DOSizeDelta(layout.LandscapeSizeDelta, transitionDuration);
                }
                else
                {
                    DG.Tweening.DOTween.To(
                        () => target.anchorMin,
                        v => target.anchorMin = v,
                        layout.PortraitAnchorMin, transitionDuration);
                    DG.Tweening.DOTween.To(
                        () => target.anchorMax,
                        v => target.anchorMax = v,
                        layout.PortraitAnchorMax, transitionDuration);
                    target.DOAnchorPos(layout.PortraitAnchoredPos, transitionDuration);
                    target.DOSizeDelta(layout.PortraitSizeDelta, transitionDuration);
                }
            }
            else
            {
                // 立即应用
                if (landscape)
                {
                    target.anchorMin = layout.LandscapeAnchorMin;
                    target.anchorMax = layout.LandscapeAnchorMax;
                    target.anchoredPosition = layout.LandscapeAnchoredPos;
                    target.sizeDelta = layout.LandscapeSizeDelta;
                }
                else
                {
                    target.anchorMin = layout.PortraitAnchorMin;
                    target.anchorMax = layout.PortraitAnchorMax;
                    target.anchoredPosition = layout.PortraitAnchoredPos;
                    target.sizeDelta = layout.PortraitSizeDelta;
                }
            }
        }
    }
    
    // 扩展方法
    static class RectTransformExtensions
    {
        public static DG.Tweening.Tweener DOAnchorPos(
            this RectTransform rect, Vector2 target, float duration)
            => DG.Tweening.DOTween.To(
                () => rect.anchoredPosition, 
                v => rect.anchoredPosition = v, 
                target, duration);
        
        public static DG.Tweening.Tweener DOSizeDelta(
            this RectTransform rect, Vector2 target, float duration)
            => DG.Tweening.DOTween.To(
                () => rect.sizeDelta, 
                v => rect.sizeDelta = v, 
                target, duration);
    }
}
```

---

## 四、世界空间UI跟随目标

```csharp
/// <summary>
/// 将世界空间UI锚定到游戏对象（血条/名字牌等跟随角色）
/// </summary>
public class WorldSpaceUIFollower : MonoBehaviour
{
    [SerializeField] private Transform target;          // 跟随的目标
    [SerializeField] private Vector3 worldOffset = new Vector3(0, 2f, 0);  // 世界空间偏移
    [SerializeField] private Canvas canvas;             // 所在的Canvas
    [SerializeField] private bool hideWhenBehindCamera = true;
    
    private RectTransform rectTransform;
    private Camera mainCamera;

    void Awake()
    {
        rectTransform = GetComponent<RectTransform>();
        mainCamera = Camera.main;
    }

    void LateUpdate()
    {
        if (target == null || mainCamera == null) return;
        
        Vector3 worldPos = target.position + worldOffset;
        
        // 检查是否在摄像机后面
        Vector3 viewportPos = mainCamera.WorldToViewportPoint(worldPos);
        
        if (hideWhenBehindCamera)
        {
            bool visible = viewportPos.z > 0 && 
                           viewportPos.x > 0 && viewportPos.x < 1 &&
                           viewportPos.y > 0 && viewportPos.y < 1;
            gameObject.SetActive(visible);
            if (!visible) return;
        }
        
        // 世界坐标 → 屏幕坐标 → Canvas局部坐标
        Vector2 screenPos = RectTransformUtility.WorldToScreenPoint(mainCamera, worldPos);
        
        if (canvas.renderMode == RenderMode.ScreenSpaceCamera ||
            canvas.renderMode == RenderMode.ScreenSpaceOverlay)
        {
            RectTransformUtility.ScreenPointToLocalPointInRectangle(
                canvas.GetComponent<RectTransform>(),
                screenPos,
                canvas.worldCamera,
                out Vector2 localPoint);
            
            rectTransform.anchoredPosition = localPoint;
        }
    }
}
```

---

## 五、适配问题诊断清单

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 刘海遮挡按钮 | 未使用 Safe Area 适配 | 添加 SafeAreaAdapter 组件 |
| 不同分辨率UI溢出 | Canvas Scaler 配置错误 | 使用 Scale with Screen Size |
| 横竖屏切换UI错位 | Anchor 设置不正确 | 使用相对锚点代替绝对像素 |
| 平板UI太小 | 未针对平板调整 matchWidthOrHeight | 平板使用 0.5 平衡匹配 |
| 世界UI穿模 | 未处理 Z 坐标判断 | 检查 viewportPos.z |
| 刘海区域背景色断裂 | 背景未延伸到屏幕边缘 | 背景图不加 Safe Area 适配 |

**黄金原则：**
- 交互元素（按钮/输入框）必须在 Safe Area 内
- 背景/装饰元素可以延伸到屏幕边缘（「全面屏沉浸感」）
- 横竖屏都要在真机测试，模拟器不够准确
