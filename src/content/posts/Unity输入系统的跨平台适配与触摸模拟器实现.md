---
title: Unity 输入系统的跨平台适配与触摸模拟器实现
published: 2026-03-31
description: 从第一性原理出发，解析游戏输入系统如何屏蔽平台差异，实现鼠标/触摸/手柄的统一输入接口，以及编辑器中的触摸模拟器设计。
tags: [Unity, 输入系统, 跨平台, Mono设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 输入系统的跨平台挑战

同一款游戏可能运行在：
- PC：鼠标 + 键盘
- 手机/平板：触摸屏（多点触控）
- 游戏主机：手柄
- 编辑器：鼠标模拟触摸

每种输入方式的 API 完全不同：

```csharp
// PC 鼠标
Input.GetMouseButtonDown(0)
Input.mousePosition

// 触摸屏
Input.touchCount
Input.GetTouch(0).phase
Input.GetTouch(0).position

// 新版 Input System（Unity 包）
Touchscreen.current.primaryTouch.press.isPressed
```

如果业务代码直接调用这些 API，每次支持新平台都需要大规模修改。

**解决方案：抽象层 + 适配器模式。**

---

## 统一输入接口设计

```csharp
// 触摸点数据（统一格式）
public struct TouchData
{
    public int FingerId;
    public Vector2 Position;
    public TouchPhase Phase;    // Began/Moved/Stationary/Ended/Canceled
    public float DeltaTime;
}

// 统一输入接口
public interface IInputAdapter
{
    int TouchCount { get; }
    TouchData GetTouch(int index);
    bool IsTouching { get; }
    Vector2 TouchPosition { get; }  // 单点触摸/鼠标位置
}
```

---

## 适配器实现

### 移动端真实触摸

```csharp
public class MobileTouchAdapter : IInputAdapter
{
    public int TouchCount => Input.touchCount;
    
    public TouchData GetTouch(int index)
    {
        var touch = Input.GetTouch(index);
        return new TouchData
        {
            FingerId = touch.fingerId,
            Position = touch.position,
            Phase = touch.phase,
            DeltaTime = touch.deltaTime
        };
    }
    
    public bool IsTouching => Input.touchCount > 0;
    public Vector2 TouchPosition => Input.touchCount > 0 
        ? Input.GetTouch(0).position 
        : Vector2.zero;
}
```

### 编辑器鼠标模拟触摸

```csharp
public class MouseSimulateTouchAdapter : IInputAdapter
{
    private TouchData _simulatedTouch;
    private Vector2 _lastPosition;
    
    public int TouchCount => Input.GetMouseButton(0) ? 1 : 0;
    
    public TouchData GetTouch(int index)
    {
        if (index != 0) return default;
        
        Vector2 pos = Input.mousePosition;
        TouchPhase phase;
        
        if (Input.GetMouseButtonDown(0))
            phase = TouchPhase.Began;
        else if (Input.GetMouseButtonUp(0))
            phase = TouchPhase.Ended;
        else if (pos != _lastPosition)
            phase = TouchPhase.Moved;
        else
            phase = TouchPhase.Stationary;
        
        _lastPosition = pos;
        
        return new TouchData
        {
            FingerId = 0,
            Position = pos,
            Phase = phase,
            DeltaTime = Time.deltaTime
        };
    }
    
    public bool IsTouching => Input.GetMouseButton(0);
    public Vector2 TouchPosition => Input.mousePosition;
}
```

---

## 输入管理器：工厂 + 单例

```csharp
public class InputManager : Singleton<InputManager>
{
    private IInputAdapter _adapter;
    
    public void Init()
    {
        #if UNITY_EDITOR
        _adapter = new MouseSimulateTouchAdapter();
        #elif UNITY_ANDROID || UNITY_IOS
        _adapter = new MobileTouchAdapter();
        #else
        _adapter = new MouseSimulateTouchAdapter();
        #endif
    }
    
    // 统一接口，业务代码只调用这个
    public int TouchCount => _adapter.TouchCount;
    public TouchData GetTouch(int index) => _adapter.GetTouch(index);
    public bool IsTouching => _adapter.IsTouching;
    public Vector2 TouchPosition => _adapter.TouchPosition;
}

// 业务代码（不感知平台差异）
if (InputManager.Instance.IsTouching)
{
    var pos = InputManager.Instance.TouchPosition;
    HandleTouchAt(pos);
}
```

---

## 手势识别：在统一接口上构建

有了统一输入层，手势识别可以在上层统一实现：

```csharp
public class GestureDetector
{
    private Dictionary<int, TouchData> _activeTouches = new();
    private Vector2 _startPosition;
    private float _startTime;
    
    // 事件：点击、长按、滑动、捏合
    public event Action<Vector2> OnTap;
    public event Action<Vector2> OnSwipe;
    public event Action<float> OnPinch;  // 缩放比例
    
    public void Update()
    {
        var input = InputManager.Instance;
        
        // 更新触摸状态
        for (int i = 0; i < input.TouchCount; i++)
        {
            var touch = input.GetTouch(i);
            
            switch (touch.Phase)
            {
                case TouchPhase.Began:
                    _activeTouches[touch.FingerId] = touch;
                    _startPosition = touch.Position;
                    _startTime = Time.time;
                    break;
                    
                case TouchPhase.Ended:
                    if (IsQuickTap(touch))
                        OnTap?.Invoke(touch.Position);
                    else if (IsSwipe(touch))
                        OnSwipe?.Invoke(GetSwipeDirection(touch));
                    _activeTouches.Remove(touch.FingerId);
                    break;
            }
        }
        
        // 检测双指捏合
        if (_activeTouches.Count == 2)
        {
            DetectPinch();
        }
    }
}
```

---

## 总结

输入系统的跨平台适配展示了经典的**适配器模式（Adapter Pattern）**应用：

| 层次 | 职责 |
|------|------|
| IInputAdapter 接口 | 定义统一输入契约 |
| MobileTouchAdapter | 真实触摸输入适配 |
| MouseSimulateTouchAdapter | 编辑器鼠标模拟 |
| InputManager | 工厂创建 + 单例访问 |
| GestureDetector | 在统一接口上构建高级手势 |

掌握这套架构，无论将来需要支持手柄、VR 手柄还是体感控制器，只需实现新的 `IInputAdapter`，上层逻辑完全不需要修改。这就是**面向接口编程**带来的扩展性优势。
