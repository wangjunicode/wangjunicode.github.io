---
title: 游戏输入系统高级设计：Input System与手势识别
published: 2026-03-31
description: 深度解析Unity New Input System的高级用法，包括InputActionAsset的配置最佳实践、多设备支持（键鼠/手柄/触屏自动切换）、复合输入（组合键/连招检测）、触屏手势识别（滑动/捏合/长按/双击）、输入缓冲（宽容窗口）、输入回放录制，以及移动端虚拟摇杆实现。
tags: [Unity, 输入系统, Input System, 手势识别, 移动端]
category: 游戏开发
draft: false
---

## 一、Input System 最佳配置实践

```csharp
using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// 输入管理器（基于 New Input System）
/// </summary>
public class InputManager : MonoBehaviour
{
    private static InputManager instance;
    public static InputManager Instance => instance;

    private PlayerControls controls; // 由 Input Action Asset 生成的代码
    
    // 输入状态
    public Vector2 MoveInput { get; private set; }
    public Vector2 LookInput { get; private set; }
    public bool JumpPressed { get; private set; }
    public bool AttackHeld { get; private set; }
    public bool SprintHeld { get; private set; }
    public bool AimHeld { get; private set; }
    
    // 设备类型检测
    public DeviceType CurrentDevice { get; private set; }
    public enum DeviceType { Keyboard, Gamepad, Touch }

    // 事件
    public event System.Action OnJumpPressed;
    public event System.Action OnInteractPressed;
    public event System.Action<int> OnSkillPressed; // skill slot index
    
    // 输入缓冲
    private float jumpBufferTime = 0.15f;
    private float jumpBufferTimer;
    public bool ConsumeJumpBuffer()
    {
        if (jumpBufferTimer > 0)
        {
            jumpBufferTimer = 0;
            return true;
        }
        return false;
    }

    void Awake()
    {
        instance = this;
        controls = new PlayerControls();
        
        SetupCallbacks();
        
        // 监听设备变化
        InputSystem.onActionChange += OnActionChange;
    }

    void SetupCallbacks()
    {
        // 移动
        controls.Gameplay.Move.performed += ctx => MoveInput = ctx.ReadValue<Vector2>();
        controls.Gameplay.Move.canceled += _ => MoveInput = Vector2.zero;
        
        // 视角
        controls.Gameplay.Look.performed += ctx => LookInput = ctx.ReadValue<Vector2>();
        controls.Gameplay.Look.canceled += _ => LookInput = Vector2.zero;
        
        // 跳跃（带输入缓冲）
        controls.Gameplay.Jump.performed += ctx =>
        {
            jumpBufferTimer = jumpBufferTime;
            OnJumpPressed?.Invoke();
        };
        
        // 攻击（持续检测）
        controls.Gameplay.Attack.performed += _ => AttackHeld = true;
        controls.Gameplay.Attack.canceled += _ => AttackHeld = false;
        
        // 技能（1-4）
        controls.Gameplay.Skill1.performed += _ => OnSkillPressed?.Invoke(0);
        controls.Gameplay.Skill2.performed += _ => OnSkillPressed?.Invoke(1);
        controls.Gameplay.Skill3.performed += _ => OnSkillPressed?.Invoke(2);
        controls.Gameplay.Skill4.performed += _ => OnSkillPressed?.Invoke(3);
        
        // 交互
        controls.Gameplay.Interact.performed += _ => OnInteractPressed?.Invoke();
        
        // 冲刺/瞄准
        controls.Gameplay.Sprint.performed += _ => SprintHeld = true;
        controls.Gameplay.Sprint.canceled += _ => SprintHeld = false;
        controls.Gameplay.Aim.performed += _ => AimHeld = true;
        controls.Gameplay.Aim.canceled += _ => AimHeld = false;
    }

    void OnEnable() => controls.Enable();
    void OnDisable() => controls.Disable();

    void Update()
    {
        if (jumpBufferTimer > 0)
            jumpBufferTimer -= Time.deltaTime;
        
        // 检测当前设备类型
        DetectDevice();
    }

    void DetectDevice()
    {
        var lastDevice = InputSystem.devices
            .Select(d => d)
            .LastOrDefault(d => d.lastUpdateTime > 0);
        
        if (lastDevice is Gamepad)
            CurrentDevice = DeviceType.Gamepad;
        else if (lastDevice is Touchscreen)
            CurrentDevice = DeviceType.Touch;
        else
            CurrentDevice = DeviceType.Keyboard;
    }

    void OnActionChange(object obj, InputActionChange change)
    {
        if (change == InputActionChange.ActionPerformed)
        {
            // 根据最新使用的设备更新UI提示
            var action = obj as InputAction;
            if (action?.activeControl?.device is Gamepad)
                UIManager.Instance?.ShowGamepadPrompts();
            else if (action?.activeControl?.device is Keyboard)
                UIManager.Instance?.ShowKeyboardPrompts();
        }
    }

    void OnDestroy()
    {
        InputSystem.onActionChange -= OnActionChange;
    }
}
```

---

## 二、触屏手势识别

```csharp
/// <summary>
/// 手势识别系统（移动端）
/// </summary>
public class GestureRecognizer : MonoBehaviour
{
    [Header("识别阈值")]
    [SerializeField] private float swipeMinDistance = 50f;   // 滑动最小距离（像素）
    [SerializeField] private float swipeMaxTime = 0.3f;      // 滑动最长时间
    [SerializeField] private float pinchThreshold = 0.1f;    // 捏合变化阈值
    [SerializeField] private float longPressTime = 0.5f;     // 长按触发时间
    [SerializeField] private float doubleTapMaxInterval = 0.3f; // 双击间隔

    public enum SwipeDirection { Up, Down, Left, Right }
    
    // 事件
    public event System.Action<SwipeDirection> OnSwipe;
    public event System.Action<float> OnPinch;  // delta > 0 = 张开（放大）
    public event System.Action<Vector2> OnLongPress;
    public event System.Action<Vector2> OnDoubleTap;
    public event System.Action<Vector2> OnTap;

    private Vector2 touchStartPos;
    private float touchStartTime;
    private bool isPinching;
    private float prevPinchDistance;
    private bool isLongPressing;
    private float longPressTimer;
    
    // 双击检测
    private float lastTapTime;
    private Vector2 lastTapPos;

    void Update()
    {
#if UNITY_EDITOR
        SimulateTouchWithMouse();
#endif
        
        if (Input.touchCount == 1)
            HandleSingleTouch(Input.GetTouch(0));
        else if (Input.touchCount == 2)
            HandlePinch(Input.GetTouch(0), Input.GetTouch(1));
    }

    void HandleSingleTouch(Touch touch)
    {
        switch (touch.phase)
        {
            case TouchPhase.Began:
                touchStartPos = touch.position;
                touchStartTime = Time.time;
                isLongPressing = true;
                longPressTimer = 0;
                break;
            
            case TouchPhase.Moved:
                // 移动超过阈值，取消长按
                if (Vector2.Distance(touch.position, touchStartPos) > 20f)
                    isLongPressing = false;
                break;
            
            case TouchPhase.Stationary:
                if (isLongPressing)
                {
                    longPressTimer += Time.deltaTime;
                    if (longPressTimer >= longPressTime)
                    {
                        isLongPressing = false;
                        OnLongPress?.Invoke(touch.position);
                    }
                }
                break;
            
            case TouchPhase.Ended:
                isLongPressing = false;
                float touchDuration = Time.time - touchStartTime;
                Vector2 delta = touch.position - touchStartPos;
                
                if (touchDuration < swipeMaxTime && delta.magnitude > swipeMinDistance)
                {
                    // 识别滑动方向
                    float angle = Mathf.Atan2(delta.y, delta.x) * Mathf.Rad2Deg;
                    SwipeDirection dir;
                    
                    if (angle >= -45 && angle < 45)      dir = SwipeDirection.Right;
                    else if (angle >= 45 && angle < 135) dir = SwipeDirection.Up;
                    else if (angle >= -135 && angle < -45) dir = SwipeDirection.Down;
                    else                                  dir = SwipeDirection.Left;
                    
                    OnSwipe?.Invoke(dir);
                }
                else if (delta.magnitude < 20f && touchDuration < 0.2f)
                {
                    // 检测双击
                    float timeSinceLastTap = Time.time - lastTapTime;
                    float distFromLastTap = Vector2.Distance(touch.position, lastTapPos);
                    
                    if (timeSinceLastTap < doubleTapMaxInterval && distFromLastTap < 50f)
                    {
                        OnDoubleTap?.Invoke(touch.position);
                        lastTapTime = 0; // 重置，防止三击
                    }
                    else
                    {
                        OnTap?.Invoke(touch.position);
                        lastTapTime = Time.time;
                        lastTapPos = touch.position;
                    }
                }
                break;
        }
    }

    void HandlePinch(Touch t1, Touch t2)
    {
        float currentDistance = Vector2.Distance(t1.position, t2.position);
        
        if (t1.phase == TouchPhase.Began || t2.phase == TouchPhase.Began)
        {
            isPinching = true;
            prevPinchDistance = currentDistance;
            return;
        }
        
        if (isPinching && (t1.phase == TouchPhase.Moved || t2.phase == TouchPhase.Moved))
        {
            float delta = currentDistance - prevPinchDistance;
            if (Mathf.Abs(delta) > pinchThreshold)
            {
                OnPinch?.Invoke(delta);
                prevPinchDistance = currentDistance;
            }
        }
        
        if (t1.phase == TouchPhase.Ended || t2.phase == TouchPhase.Ended)
            isPinching = false;
    }

#if UNITY_EDITOR
    void SimulateTouchWithMouse() { /* 编辑器下用鼠标模拟触摸 */ }
#endif
}
```

---

## 三、虚拟摇杆

```csharp
/// <summary>
/// 浮动虚拟摇杆（点击位置自动居中）
/// </summary>
public class FloatingJoystick : MonoBehaviour,
    UnityEngine.EventSystems.IPointerDownHandler,
    UnityEngine.EventSystems.IDragHandler,
    UnityEngine.EventSystems.IPointerUpHandler
{
    [SerializeField] private RectTransform background;
    [SerializeField] private RectTransform handle;
    [SerializeField] private float handleRange = 80f;  // 摇杆移动半径

    public Vector2 Direction { get; private set; }
    
    private Canvas canvas;
    private bool isDragging;

    void Awake()
    {
        canvas = GetComponentInParent<Canvas>();
        background.gameObject.SetActive(false);
    }

    public void OnPointerDown(UnityEngine.EventSystems.PointerEventData eventData)
    {
        // 摇杆出现在手指位置
        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            canvas.GetComponent<RectTransform>(),
            eventData.position, canvas.worldCamera,
            out Vector2 localPos);
        
        background.anchoredPosition = localPos;
        background.gameObject.SetActive(true);
        handle.anchoredPosition = Vector2.zero;
        isDragging = true;
    }

    public void OnDrag(UnityEngine.EventSystems.PointerEventData eventData)
    {
        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            background,
            eventData.position, canvas.worldCamera,
            out Vector2 localPos);
        
        Vector2 clamped = Vector2.ClampMagnitude(localPos, handleRange);
        handle.anchoredPosition = clamped;
        Direction = clamped / handleRange;
    }

    public void OnPointerUp(UnityEngine.EventSystems.PointerEventData eventData)
    {
        Direction = Vector2.zero;
        handle.anchoredPosition = Vector2.zero;
        background.gameObject.SetActive(false);
        isDragging = false;
    }
}
```

---

## 四、输入方案适配建议

| 平台 | 推荐方案 | 注意事项 |
|------|----------|----------|
| PC | New Input System 键鼠+手柄 | 支持自定义键位 |
| 主机 | New Input System 手柄 | 按键提示随手柄品牌变化 |
| 移动端 | 触屏 + 虚拟摇杆 | 操作区域不要太小 |
| 跨平台 | Input System + 设备检测 | 自动切换UI提示 |
