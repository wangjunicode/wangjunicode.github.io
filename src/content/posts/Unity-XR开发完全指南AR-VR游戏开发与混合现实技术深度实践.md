---
title: Unity XR开发完全指南：AR/VR游戏开发与混合现实技术深度实践
published: 2026-04-09
description: 深入解析Unity XR Interaction Toolkit的完整工程实践，涵盖AR Foundation与ARCore/ARKit集成（平面检测、锚点、图像追踪）、VR场景优化（Single Pass Instanced、Foveated Rendering、异步时间扭曲）、XR交互系统（射线交互、直接抓取、UI交互）、空间UI设计、6DOF手柄输入统一抽象、XR性能分析与优化策略，以及XR多平台发布（Quest/HoloLens/iOS ARKit/Android ARCore）完整工程方案。
tags: [XR, AR, VR, Unity, ARCore, ARKit, XR Interaction Toolkit, 游戏开发]
category: XR开发
draft: false
---

## 一、XR 开发基础架构与工具链

### 1.1 XR Plugin Management 统一框架

Unity 通过 **XR Plugin Management** 实现多平台统一管理，一套代码可同时支持 Oculus/Meta Quest、OpenXR、ARCore（Android）、ARKit（iOS）等平台。

```
Unity XR Architecture:
┌─────────────────────────────────────────┐
│         Game Logic / XR Toolkit          │
├─────────────────────────────────────────┤
│       XR Interaction Toolkit (XRI)       │
├─────────────────────────────────────────┤
│           XR Plugin Management           │
├──────────┬──────────┬────────┬──────────┤
│  OpenXR  │ Oculus   │ ARCore │  ARKit   │
│  Plugin  │ Plugin   │ Plugin │  Plugin  │
├──────────┴──────────┴────────┴──────────┤
│         Hardware (Quest/HoloLens/Phone)  │
└─────────────────────────────────────────┘
```

```json
// Packages/manifest.json 核心依赖
{
  "com.unity.xr.management":           "4.4.0",
  "com.unity.xr.interaction.toolkit":  "2.5.2",
  "com.unity.xr.arfoundation":         "5.1.0",
  "com.unity.xr.arcore":               "5.1.0",
  "com.unity.xr.arkit":                "5.1.0",
  "com.unity.xr.openxr":              "1.9.1",
  "com.unity.render-pipelines.universal": "14.0.8"
}
```

### 1.2 XR 输入系统统一抽象

```csharp
using UnityEngine;
using UnityEngine.XR;
using UnityEngine.XR.Interaction.Toolkit;
using System.Collections.Generic;

/// <summary>
/// XR统一输入抽象层
/// 屏蔽OpenXR/Oculus/ARKit的差异，提供统一接口
/// </summary>
public class XRInputAbstraction : MonoBehaviour
{
    // XR输入设备引用
    private InputDevice leftController;
    private InputDevice rightController;
    private InputDevice headset;
    
    // 输入状态快照
    public struct XRInputState
    {
        // 手柄位置与旋转
        public Vector3  leftPosition,  rightPosition;
        public Quaternion leftRotation, rightRotation;
        public Vector3  headPosition;
        public Quaternion headRotation;
        
        // 按键状态
        public bool  triggerLeft,   triggerRight;
        public bool  gripLeft,      gripRight;
        public bool  primaryLeft,   primaryRight;   // A/X 按钮
        public bool  secondaryLeft, secondaryRight; // B/Y 按钮
        public bool  menuLeft,      menuRight;
        
        // 模拟量
        public float triggerLeftValue,  triggerRightValue;  // [0,1]
        public float gripLeftValue,     gripRightValue;
        public Vector2 joystickLeft,    joystickRight;      // [-1,1]x[-1,1]
    }
    
    public XRInputState InputState { get; private set; }
    
    void OnEnable()
    {
        InputDevices.deviceConnected    += OnDeviceConnected;
        InputDevices.deviceDisconnected += OnDeviceDisconnected;
        RefreshDevices();
    }
    
    void OnDisable()
    {
        InputDevices.deviceConnected    -= OnDeviceConnected;
        InputDevices.deviceDisconnected -= OnDeviceDisconnected;
    }
    
    private void RefreshDevices()
    {
        var devices = new List<InputDevice>();
        
        InputDevices.GetDevicesWithCharacteristics(
            InputDeviceCharacteristics.Left | InputDeviceCharacteristics.Controller, devices);
        if (devices.Count > 0) leftController = devices[0];
        devices.Clear();
        
        InputDevices.GetDevicesWithCharacteristics(
            InputDeviceCharacteristics.Right | InputDeviceCharacteristics.Controller, devices);
        if (devices.Count > 0) rightController = devices[0];
        devices.Clear();
        
        InputDevices.GetDevicesWithCharacteristics(
            InputDeviceCharacteristics.HeadMounted, devices);
        if (devices.Count > 0) headset = devices[0];
    }
    
    void Update()
    {
        var state = new XRInputState();
        
        // 采样左手控制器
        if (leftController.isValid)
        {
            leftController.TryGetFeatureValue(CommonUsages.devicePosition,  out state.leftPosition);
            leftController.TryGetFeatureValue(CommonUsages.deviceRotation,  out state.leftRotation);
            leftController.TryGetFeatureValue(CommonUsages.triggerButton,   out state.triggerLeft);
            leftController.TryGetFeatureValue(CommonUsages.gripButton,      out state.gripLeft);
            leftController.TryGetFeatureValue(CommonUsages.primaryButton,   out state.primaryLeft);
            leftController.TryGetFeatureValue(CommonUsages.secondaryButton, out state.secondaryLeft);
            leftController.TryGetFeatureValue(CommonUsages.trigger,         out state.triggerLeftValue);
            leftController.TryGetFeatureValue(CommonUsages.grip,            out state.gripLeftValue);
            leftController.TryGetFeatureValue(CommonUsages.primary2DAxis,   out state.joystickLeft);
        }
        
        // 采样右手控制器（对称逻辑）
        if (rightController.isValid)
        {
            rightController.TryGetFeatureValue(CommonUsages.devicePosition,  out state.rightPosition);
            rightController.TryGetFeatureValue(CommonUsages.deviceRotation,  out state.rightRotation);
            rightController.TryGetFeatureValue(CommonUsages.triggerButton,   out state.triggerRight);
            rightController.TryGetFeatureValue(CommonUsages.gripButton,      out state.gripRight);
            rightController.TryGetFeatureValue(CommonUsages.primaryButton,   out state.primaryRight);
            rightController.TryGetFeatureValue(CommonUsages.secondaryButton, out state.secondaryRight);
            rightController.TryGetFeatureValue(CommonUsages.trigger,         out state.triggerRightValue);
            rightController.TryGetFeatureValue(CommonUsages.grip,            out state.gripRightValue);
            rightController.TryGetFeatureValue(CommonUsages.primary2DAxis,   out state.joystickRight);
        }
        
        // 采样头显
        if (headset.isValid)
        {
            headset.TryGetFeatureValue(CommonUsages.devicePosition, out state.headPosition);
            headset.TryGetFeatureValue(CommonUsages.deviceRotation, out state.headRotation);
        }
        
        InputState = state;
    }
    
    private void OnDeviceConnected(InputDevice device) => RefreshDevices();
    private void OnDeviceDisconnected(InputDevice device) => RefreshDevices();
}
```

---

## 二、AR Foundation 实战

### 2.1 平面检测与 AR 对象放置

```csharp
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using System.Collections.Generic;

/// <summary>
/// AR平面检测与对象放置系统
/// 支持ARCore（Android）和ARKit（iOS）
/// </summary>
[RequireComponent(typeof(ARRaycastManager))]
[RequireComponent(typeof(ARPlaneManager))]
public class ARPlacementManager : MonoBehaviour
{
    [Header("AR组件")]
    [SerializeField] private ARRaycastManager   arRaycastManager;
    [SerializeField] private ARPlaneManager     arPlaneManager;
    [SerializeField] private ARAnchorManager    arAnchorManager;
    
    [Header("放置配置")]
    [SerializeField] private GameObject objectPrefab;
    [SerializeField] private bool       allowMultiplePlacements = false;
    [SerializeField] private float      minPlacementScale       = 0.01f; // 根据真实尺寸缩放
    
    private List<ARRaycastHit> raycastHits = new List<ARRaycastHit>();
    private GameObject        placedObject;
    private ARAnchor          anchor;
    
    // 平面类型过滤
    private const TrackableType PlaneFilter = 
        TrackableType.PlaneWithinPolygon | 
        TrackableType.PlaneWithinBounds;
    
    void Update()
    {
        // 移动端：单指触摸放置
        if (Input.touchCount > 0)
        {
            var touch = Input.GetTouch(0);
            if (touch.phase == TouchPhase.Began)
                TryPlaceObject(touch.position);
        }
        
        // 编辑器调试：鼠标点击
        #if UNITY_EDITOR
        if (Input.GetMouseButtonDown(0))
            TryPlaceObject(Input.mousePosition);
        #endif
    }
    
    private void TryPlaceObject(Vector2 screenPos)
    {
        if (!arRaycastManager.Raycast(screenPos, raycastHits, PlaneFilter))
            return;
        
        if (raycastHits.Count == 0) return;
        
        var hit  = raycastHits[0];
        var pose = hit.pose;
        
        if (!allowMultiplePlacements && placedObject != null)
        {
            // 移动已放置对象
            MoveObjectToHit(pose, hit.trackable);
        }
        else
        {
            // 放置新对象
            PlaceNewObject(pose, hit.trackable);
        }
    }
    
    private void PlaceNewObject(Pose pose, ARTrackable trackable)
    {
        // 创建AR锚点（锚点跟踪真实世界位置，确保对象不漂移）
        if (arAnchorManager != null)
        {
            anchor?.Destroy();
            anchor = arAnchorManager.AttachAnchor(trackable as ARPlane, pose);
            if (anchor != null)
            {
                placedObject = Instantiate(objectPrefab, anchor.transform);
                placedObject.transform.localPosition = Vector3.zero;
                placedObject.transform.localRotation = Quaternion.identity;
                return;
            }
        }
        
        // 降级方案：无锚点直接放置
        placedObject = Instantiate(objectPrefab, pose.position, pose.rotation);
    }
    
    private void MoveObjectToHit(Pose pose, ARTrackable trackable)
    {
        if (placedObject == null) return;
        placedObject.transform.position = pose.position;
        placedObject.transform.rotation = pose.rotation;
    }
    
    /// <summary>
    /// 切换平面可见性（调试时显示，正式体验时隐藏）
    /// </summary>
    public void SetPlanesVisible(bool visible)
    {
        foreach (var plane in arPlaneManager.trackables)
        {
            var renderer = plane.GetComponent<MeshRenderer>();
            if (renderer != null) renderer.enabled = visible;
        }
    }
}
```

### 2.2 AR 图像追踪（卡牌游戏、展品扫描）

```csharp
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using System.Collections.Generic;

/// <summary>
/// AR图像追踪系统
/// 应用：卡牌游戏（扫描卡牌显示3D角色）、博物馆导览、广告交互
/// </summary>
public class ARImageTracker : MonoBehaviour
{
    [SerializeField] private ARTrackedImageManager imageManager;
    
    [System.Serializable]
    public class TrackedImageBinding
    {
        public string imageName;         // 与 ReferenceImageLibrary 中的名称匹配
        public GameObject prefab;        // 识别到该图像时显示的3D内容
        public Vector3    positionOffset; // 3D内容相对于图像的偏移
        public bool       trackContinuously = true; // 是否持续跟踪（false=检测到后固定）
    }
    
    [SerializeField] private List<TrackedImageBinding> bindings;
    
    // 追踪中的图像实例
    private Dictionary<string, GameObject> activeInstances = new();
    private Dictionary<string, TrackedImageBinding> bindingMap = new();
    
    void Awake()
    {
        foreach (var b in bindings)
            bindingMap[b.imageName] = b;
    }
    
    void OnEnable()
    {
        imageManager.trackedImagesChanged += OnTrackedImagesChanged;
    }
    
    void OnDisable()
    {
        imageManager.trackedImagesChanged -= OnTrackedImagesChanged;
    }
    
    private void OnTrackedImagesChanged(ARTrackedImagesChangedEventArgs args)
    {
        // 新增追踪到的图像
        foreach (var image in args.added)
            HandleImageAdded(image);
        
        // 已追踪图像的状态更新（位置、旋转）
        foreach (var image in args.updated)
            HandleImageUpdated(image);
        
        // 图像离开视野
        foreach (var image in args.removed)
            HandleImageRemoved(image);
    }
    
    private void HandleImageAdded(ARTrackedImage image)
    {
        string name = image.referenceImage.name;
        if (!bindingMap.TryGetValue(name, out var binding)) return;
        
        var instance = Instantiate(binding.prefab);
        UpdateInstanceTransform(instance, image, binding);
        activeInstances[name] = instance;
        
        Debug.Log($"[AR] 识别到图像：{name}");
    }
    
    private void HandleImageUpdated(ARTrackedImage image)
    {
        string name = image.referenceImage.name;
        if (!activeInstances.TryGetValue(name, out var instance)) return;
        if (!bindingMap.TryGetValue(name, out var binding)) return;
        
        // 根据追踪质量决定是否更新位置
        bool shouldUpdate = image.trackingState == TrackingState.Tracking
                         || (image.trackingState == TrackingState.Limited && binding.trackContinuously);
        
        if (shouldUpdate)
            UpdateInstanceTransform(instance, image, binding);
        
        // 根据追踪状态控制显示/隐藏
        instance.SetActive(image.trackingState != TrackingState.None);
    }
    
    private void HandleImageRemoved(ARTrackedImage image)
    {
        string name = image.referenceImage.name;
        if (activeInstances.TryGetValue(name, out var instance))
        {
            Destroy(instance);
            activeInstances.Remove(name);
        }
    }
    
    private void UpdateInstanceTransform(GameObject instance, ARTrackedImage image, TrackedImageBinding binding)
    {
        instance.transform.position = image.transform.position 
            + image.transform.TransformDirection(binding.positionOffset);
        instance.transform.rotation = image.transform.rotation;
        
        // 根据图像物理尺寸自适应缩放
        float scale = image.size.x / image.referenceImage.size.x;
        instance.transform.localScale = Vector3.one * scale;
    }
}
```

---

## 三、VR 场景优化

### 3.1 VR 渲染优化核心策略

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Unity.XR.CoreUtils;

/// <summary>
/// VR渲染优化配置器
/// 针对单通道立体渲染（Single Pass Instanced）和注视点渲染优化
/// </summary>
public class VRRenderOptimizer : MonoBehaviour
{
    [Header("渲染质量")]
    [SerializeField] private float renderScale        = 1.1f; // 超采样（Quest2推荐1.0~1.3）
    [SerializeField] private bool  enableFFR          = true;  // Fixed Foveated Rendering
    [SerializeField] private bool  enableDynamicScale = false; // 动态分辨率
    
    [Header("性能目标")]
    [SerializeField] private int targetFrameRate = 90; // Quest2: 72/90/120 Hz
    [SerializeField] private float dynamicScaleMin = 0.7f;
    [SerializeField] private float dynamicScaleMax = 1.0f;
    
    void Awake()
    {
        ConfigureVRSettings();
    }
    
    private void ConfigureVRSettings()
    {
        // ── 1. 设置渲染分辨率 ───────────────────────────────────
        XRSettings.eyeTextureResolutionScale = renderScale;
        
        // ── 2. 目标帧率 ─────────────────────────────────────────
        Application.targetFrameRate = targetFrameRate;
        QualitySettings.vSyncCount  = 0; // VR禁用vSync，由XR SDK管理
        
        // ── 3. 关闭不适合VR的后处理效果 ────────────────────────
        // Motion Blur 在VR中会导致强烈眩晕感，必须关闭
        DisableVRUnfriendlyPostProcess();
        
        // ── 4. 优化阴影 ─────────────────────────────────────────
        QualitySettings.shadows              = ShadowQuality.HardOnly;
        QualitySettings.shadowDistance       = 20f; // VR阴影距离控制在20m以内
        QualitySettings.shadowCascades       = 2;   // 双联级阴影
        
        // ── 5. 减少 DrawCall ─────────────────────────────────────
        // VR每帧需渲染两次（双眼），DrawCall消耗翻倍
        // GPU Instancing + Static/Dynamic Batching 尤为重要
        
        Debug.Log($"[VR] 渲染配置完成 | Scale={renderScale} | FPS={targetFrameRate}");
    }
    
    private void DisableVRUnfriendlyPostProcess()
    {
        var volume = FindObjectOfType<Volume>();
        if (volume == null || !volume.profile) return;
        
        // 关闭Motion Blur（必须）
        if (volume.profile.TryGet<MotionBlur>(out var mb))
            mb.active = false;
        
        // 关闭Lens Distortion（在VR中双重扭曲）
        if (volume.profile.TryGet<LensDistortion>(out var ld))
            ld.active = false;
        
        // Bloom可保留（适度），DOF建议关闭
        if (volume.profile.TryGet<DepthOfField>(out var dof))
            dof.active = false;
    }
    
    // ─── 动态分辨率调整 ────────────────────────────────────────
    private float currentScale;
    private float lastFrameTime;
    private const float TARGET_FRAME_TIME_MS = 11.1f; // 90fps ≈ 11.1ms
    
    void Update()
    {
        if (!enableDynamicScale) return;
        
        float frameTimeMs = Time.unscaledDeltaTime * 1000f;
        
        if (frameTimeMs > TARGET_FRAME_TIME_MS * 1.1f)
        {
            // 帧时间超出预算，降低分辨率
            currentScale = Mathf.Max(dynamicScaleMin, currentScale - 0.05f);
        }
        else if (frameTimeMs < TARGET_FRAME_TIME_MS * 0.85f)
        {
            // 帧时间充裕，提升分辨率
            currentScale = Mathf.Min(dynamicScaleMax, currentScale + 0.02f);
        }
        
        XRSettings.eyeTextureResolutionScale = currentScale;
    }
}
```

### 3.2 XR Interaction Toolkit 交互系统

```csharp
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using System.Collections.Generic;

/// <summary>
/// 自定义XR抓取交互器
/// 扩展XRI基础功能：力反馈、物理抓取、多点接触
/// </summary>
public class AdvancedXRGrabInteractable : XRGrabInteractable
{
    [Header("高级抓取配置")]
    [SerializeField] private bool  enableHapticFeedback   = true;
    [SerializeField] private float hapticIntensity        = 0.3f;
    [SerializeField] private float hapticDuration         = 0.1f;
    [SerializeField] private bool  preserveKineticOnDrop  = true; // 丢出时保留速度
    [SerializeField] private float throwVelocityMultiplier = 1.5f;
    
    [Header("物理约束")]
    [SerializeField] private float maxGrabDistance    = 0.1f;  // 最大抓取距离（米）
    [SerializeField] private bool  magneticSnap       = true;   // 磁吸对齐
    [SerializeField] private List<Transform> snapPoints;        // 对齐点
    
    private Vector3    prevVelocity;
    private Vector3    prevAngularVelocity;
    private Rigidbody  rb;
    
    protected override void Awake()
    {
        base.Awake();
        rb = GetComponent<Rigidbody>();
    }
    
    // ─── 抓取回调 ───────────────────────────────────────────────
    protected override void OnSelectEntered(SelectEnterEventArgs args)
    {
        base.OnSelectEntered(args);
        
        // 触发手柄震动反馈
        if (enableHapticFeedback)
            SendHapticImpulse(args.interactorObject, hapticIntensity, hapticDuration);
        
        // 磁吸对齐：寻找最近的吸附点
        if (magneticSnap && snapPoints.Count > 0)
            TrySnapToClosestPoint(args.interactorObject.transform.position);
    }
    
    protected override void OnSelectExited(SelectExitEventArgs args)
    {
        base.OnSelectExited(args);
        
        // 离开时再次震动
        if (enableHapticFeedback)
            SendHapticImpulse(args.interactorObject, hapticIntensity * 0.5f, hapticDuration * 0.5f);
        
        // 投掷：放大速度系数
        if (preserveKineticOnDrop && rb != null)
        {
            rb.linearVelocity        = prevVelocity        * throwVelocityMultiplier;
            rb.angularVelocity = prevAngularVelocity * throwVelocityMultiplier;
        }
    }
    
    void FixedUpdate()
    {
        // 记录上一帧速度（用于投掷计算）
        if (rb != null && isSelected)
        {
            prevVelocity        = rb.linearVelocity;
            prevAngularVelocity = rb.angularVelocity;
        }
    }
    
    private void SendHapticImpulse(IXRInteractor interactor, float amplitude, float duration)
    {
        if (interactor is XRBaseControllerInteractor controllerInteractor)
            controllerInteractor.SendHapticImpulse(amplitude, duration);
    }
    
    private void TrySnapToClosestPoint(Vector3 grabPoint)
    {
        if (snapPoints.Count == 0) return;
        
        Transform closest      = null;
        float     minDistance  = float.MaxValue;
        
        foreach (var point in snapPoints)
        {
            float dist = Vector3.Distance(grabPoint, point.position);
            if (dist < minDistance)
            {
                minDistance = dist;
                closest     = point;
            }
        }
        
        if (closest != null && minDistance < maxGrabDistance)
        {
            // 吸附：移动物体使吸附点对准抓取位置
            Vector3 offset        = transform.position - closest.position;
            transform.position   += offset;
        }
    }
}
```

---

## 四、空间 UI 设计

### 4.1 World Space UI 最佳实践

```csharp
using UnityEngine;
using UnityEngine.UI;
using TMPro;

/// <summary>
/// VR/AR世界空间UI管理器
/// 处理UI跟随、注视、距离缩放等特有需求
/// </summary>
public class XRWorldSpaceUI : MonoBehaviour
{
    [Header("跟随配置")]
    [SerializeField] private Transform headTransform;         // XR Camera
    [SerializeField] private float     followDistance  = 2f;  // UI与头显的距离
    [SerializeField] private float     followSmoothness = 5f; // 跟随平滑度
    [SerializeField] private float     verticalOffset  = -0.2f; // 垂直偏移（轻微向下）
    [SerializeField] private bool      billboardMode   = true;  // 始终面向用户
    
    [Header("距离缩放")]
    [SerializeField] private bool  distanceScaling = true;
    [SerializeField] private float nearDistance    = 0.5f;
    [SerializeField] private float farDistance     = 5f;
    [SerializeField] private float minScale        = 0.5f;
    [SerializeField] private float maxScale        = 2.0f;
    
    [Header("可读性")]
    [SerializeField] private float minPixelPerUnit = 100f; // 确保文字清晰度
    
    private Vector3    targetPosition;
    private Quaternion targetRotation;
    
    void LateUpdate()
    {
        if (headTransform == null) return;
        
        UpdatePosition();
        UpdateRotation();
        UpdateScale();
    }
    
    private void UpdatePosition()
    {
        // 在头显前方固定距离，跟随头部水平朝向
        Vector3 forward = headTransform.forward;
        forward.y       = 0; // 忽略垂直朝向
        forward.Normalize();
        
        targetPosition = headTransform.position 
            + forward * followDistance 
            + Vector3.up * verticalOffset;
        
        transform.position = Vector3.Lerp(
            transform.position, 
            targetPosition, 
            Time.deltaTime * followSmoothness
        );
    }
    
    private void UpdateRotation()
    {
        if (!billboardMode) return;
        
        // 始终面向头显（Billboard）
        Vector3 lookDir = transform.position - headTransform.position;
        if (lookDir.sqrMagnitude > 0.001f)
        {
            targetRotation        = Quaternion.LookRotation(lookDir);
            transform.rotation    = Quaternion.Slerp(
                transform.rotation, 
                targetRotation, 
                Time.deltaTime * followSmoothness
            );
        }
    }
    
    private void UpdateScale()
    {
        if (!distanceScaling) return;
        
        float distance = Vector3.Distance(transform.position, headTransform.position);
        float t        = Mathf.InverseLerp(nearDistance, farDistance, distance);
        float scale    = Mathf.Lerp(minScale, maxScale, t);
        transform.localScale = Vector3.one * scale;
    }
    
    /// <summary>
    /// 设置UI内容（适配 VR 的大字体）
    /// </summary>
    public void SetText(TMP_Text label, string content, float fontSize = 24f)
    {
        label.text     = content;
        label.fontSize = fontSize; // VR中字体比普通UI大2-4倍
    }
}
```

---

## 五、XR 性能分析与调优

### 5.1 XR 专项性能指标

| 指标 | Quest 2 目标值 | PC VR 目标值 |
|------|--------------|-------------|
| GPU 帧时间 | < 8.3ms (120fps) / < 11.1ms (90fps) | < 11.1ms |
| CPU 帧时间 | < 8ms | < 8ms |
| DrawCall | < 100 per eye | < 300 per eye |
| 三角面数 | < 100K per eye | < 1M per eye |
| 纹理显存 | < 1.5 GB | < 4 GB |
| 眩晕风险因素 | Frame drop, reprojection | Frame drop |

```csharp
using UnityEngine;
using UnityEngine.XR;

/// <summary>
/// XR性能监控器（在HMD内置Overlay显示）
/// </summary>
public class XRPerformanceMonitor : MonoBehaviour
{
    private float gpuFrameTime;
    private float cpuFrameTime;
    private int   drawCalls;
    private bool  isReprojecting; // ASW/ATW触发时=掉帧
    
    [SerializeField] private TMPro.TMP_Text overlayText;
    [SerializeField] private float          updateInterval = 0.5f;
    
    private float timer;
    
    void Update()
    {
        timer += Time.unscaledDeltaTime;
        if (timer < updateInterval) return;
        timer = 0;
        
        CollectMetrics();
        DisplayMetrics();
    }
    
    private void CollectMetrics()
    {
        cpuFrameTime = Time.unscaledDeltaTime * 1000f;
        drawCalls    = UnityEngine.Rendering.RenderPipelineManager.currentPipeline != null
            ? 0 // URP中需要自定义RenderPass统计
            : 0;
        
        // Quest特有：通过OVR API获取GPU时间（需要Oculus SDK）
        // gpuFrameTime = OVRPlugin.GetGPUUtilLevel() * 11.1f;
        
        // 检测是否触发了异步时间扭曲（ATW/ASW）
        // 通过帧时间突变判断
        isReprojecting = cpuFrameTime > 15f;
    }
    
    private void DisplayMetrics()
    {
        if (overlayText == null) return;
        
        string color = cpuFrameTime > 11.1f ? "<color=red>" : "<color=green>";
        overlayText.text = 
            $"CPU: {color}{cpuFrameTime:F1}ms</color>\n" +
            $"DC: {drawCalls}\n" +
            $"{(isReprojecting ? "<color=yellow>ATW!</color>" : "OK")}";
    }
    
    // ─── VR 优化清单 ────────────────────────────────────────────
    /*
     * ✅ 使用 Single Pass Instanced 渲染（Player Settings > XR > Stereo Rendering Mode）
     * ✅ 开启 Fixed Foveated Rendering（Quest2）
     * ✅ 静态物体 Occlusion Culling + Static Batching
     * ✅ GPU Instancing（草、树木、粒子等重复物体）
     * ✅ 关闭 Motion Blur、Lens Distortion
     * ✅ 使用 URP 而非 Built-in RP（移动XR性能更优）
     * ✅ 纹理使用 ASTC 压缩（Quest）
     * ✅ 最大化 Baked 光照，减少动态光源
     * ✅ 半透明物体控制在最少（每个Alpha物体打断合批）
     * ✅ 使用 OVR Metrics Tool 进行性能分析
     */
}
```

---

## 六、AR 应用性能优化

### 6.1 AR 追踪稳定性优化

```csharp
using UnityEngine;
using UnityEngine.XR.ARFoundation;

/// <summary>
/// AR追踪质量管理器
/// 处理追踪丢失、低质量追踪等情况
/// </summary>
public class ARTrackingQualityManager : MonoBehaviour
{
    [SerializeField] private ARSession        arSession;
    [SerializeField] private ARCameraManager  arCameraManager;
    
    [SerializeField] private GameObject       lowLightWarning;    // 光线不足提示
    [SerializeField] private GameObject       motionBlurWarning;  // 移动过快提示
    [SerializeField] private TMPro.TMP_Text   trackingStateText;
    
    void OnEnable()
    {
        arCameraManager.frameReceived += OnCameraFrameReceived;
        ARSession.stateChanged        += OnARSessionStateChanged;
    }
    
    void OnDisable()
    {
        arCameraManager.frameReceived -= OnCameraFrameReceived;
        ARSession.stateChanged        -= OnARSessionStateChanged;
    }
    
    private void OnCameraFrameReceived(ARCameraFrameEventArgs args)
    {
        // 分析相机帧元数据（亮度、曝光等）
        if (args.lightEstimation.averageBrightness.HasValue)
        {
            float brightness = args.lightEstimation.averageBrightness.Value;
            lowLightWarning?.SetActive(brightness < 0.3f);
        }
    }
    
    private void OnARSessionStateChanged(ARSessionStateChangedEventArgs args)
    {
        UpdateTrackingUI(args.state);
    }
    
    private void UpdateTrackingUI(ARSessionState state)
    {
        string message = state switch
        {
            ARSessionState.SessionInitializing => "正在初始化AR...",
            ARSessionState.SessionTracking     => "追踪正常",
            ARSessionState.LimitedWithReasonInitializing => "正在搜索特征点...",
            ARSessionState.LimitedWithReasonExcessiveMotion => "移动过快，请放慢",
            ARSessionState.LimitedWithReasonInsufficientFeatures => "特征点不足，请对准有纹理的区域",
            ARSessionState.LimitedWithReasonRelocalizing => "重新定位中...",
            ARSessionState.CheckingAvailability => "检查AR可用性...",
            _ => state.ToString()
        };
        
        if (trackingStateText != null)
            trackingStateText.text = message;
    }
}
```

---

## 七、多平台发布配置

### 7.1 平台差异处理

```csharp
using UnityEngine;

/// <summary>
/// XR多平台运行时平台检测与配置适配
/// </summary>
public class XRPlatformAdapter : MonoBehaviour
{
    public enum XRPlatform
    {
        Unknown,
        MetaQuest,      // Oculus Quest 系列
        OpenXRPC,       // PC VR (SteamVR/WMR)
        ARCoreAndroid,  // Android AR
        ARKitiOS,       // iOS AR
    }
    
    public static XRPlatform CurrentPlatform { get; private set; }
    
    void Awake()
    {
        DetectPlatform();
        ApplyPlatformSettings();
    }
    
    private void DetectPlatform()
    {
        #if UNITY_ANDROID
        // 检测是否为Quest设备
        string deviceModel = SystemInfo.deviceModel.ToLower();
        if (deviceModel.Contains("quest") || deviceModel.Contains("oculus"))
            CurrentPlatform = XRPlatform.MetaQuest;
        else
            CurrentPlatform = XRPlatform.ARCoreAndroid;
        #elif UNITY_IOS
        CurrentPlatform = XRPlatform.ARKitiOS;
        #else
        CurrentPlatform = XRPlatform.OpenXRPC;
        #endif
        
        Debug.Log($"[XR] 平台检测：{CurrentPlatform} | 设备：{SystemInfo.deviceModel}");
    }
    
    private void ApplyPlatformSettings()
    {
        switch (CurrentPlatform)
        {
            case XRPlatform.MetaQuest:
                // Quest专项优化
                Application.targetFrameRate      = 90;
                QualitySettings.vSyncCount       = 0;
                QualitySettings.antiAliasing     = 4;   // MSAA 4x
                Screen.sleepTimeout              = SleepTimeout.NeverSleep;
                break;
                
            case XRPlatform.ARCoreAndroid:
            case XRPlatform.ARKitiOS:
                // 手机AR：省电优先
                Application.targetFrameRate      = 60;
                QualitySettings.antiAliasing     = 2;
                // AR不需要深度测试优化
                break;
                
            case XRPlatform.OpenXRPC:
                // PC VR：质量优先
                Application.targetFrameRate      = 90;
                QualitySettings.antiAliasing     = 8;
                break;
        }
    }
}
```

---

## 八、工程建议与总结

| 开发阶段 | 建议 |
|---------|------|
| **原型期** | 优先使用 AR Foundation + XRI 标准组件，降低定制成本 |
| **AR 开发** | 重点关注追踪稳定性、锚点管理和光线估计 |
| **VR 开发** | 帧率稳定 > 画质，永远不能掉帧（导致眩晕） |
| **交互设计** | 优先射线交互，近距离辅以直接抓取 |
| **UI 设计** | 世界空间 UI 字号加大 2~4 倍，避免 Screen Space |
| **性能测试** | 始终在目标设备（如 Quest2）测试，PC 上效果无参考意义 |
| **发布打包** | 注意各平台权限配置（摄像头、运动传感器） |

XR 开发是游戏客户端的前沿方向，掌握 AR Foundation + XR Interaction Toolkit 的完整工具链，能够快速将标准移动游戏开发能力迁移到 AR/VR 领域，是未来元宇宙与空间计算时代的核心竞争力。
