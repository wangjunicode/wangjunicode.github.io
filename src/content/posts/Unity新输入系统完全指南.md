---
title: Unity新输入系统完全指南
description: 全面解析Unity New Input System（InputSystem Package）的架构设计与实践，包括Action Map配置、设备热插拔、多玩家支持、移动端触控处理与主机手柄适配。
pubDate: 2026-03-21
category: 技术基础
tags: [Unity, InputSystem, 输入系统, 手柄, 移动端, 多平台]
---

# Unity新输入系统完全指南

Unity 旧输入系统（`Input.GetKey`）在多平台适配、多玩家支持上存在明显缺陷。New Input System（2019.1+引入）彻底重构了输入处理方式，本文系统讲解其架构与最佳实践。

## 一、新旧输入系统对比

| 特性 | 旧系统（Input class） | 新系统（Input System Package）|
|------|----------------------|-------------------------------|
| 多设备支持 | 弱，需手动区分 | 原生支持，设备抽象层 |
| 多玩家输入 | 困难 | 内置 PlayerInputManager |
| 输入重映射 | 需自己实现 | 内置支持 |
| 触控/手势 | 基础 | 丰富的触摸 API |
| 性能 | 轮询（每帧查询） | 事件驱动（有变化才触发）|
| 测试友好 | 差，依赖硬件 | 可以模拟输入（单元测试）|

## 二、核心概念

```
Input System 架构：

物理设备（Keyboard/Gamepad/Touchscreen）
         ↓
    Input Device（设备抽象）
         ↓
    Input Action（动作定义：移动/跳跃/射击）
         ↓
    Input Action Map（动作集合：游戏中/UI中/载具中）
         ↓
    Input Action Asset（.inputactions 文件）
         ↓
    PlayerInput 组件（连接游戏对象与输入）
         ↓
    游戏逻辑处理
```

## 三、Action Asset 配置

### 3.1 创建 Input Actions

通过 `Project → Create → Input Actions` 创建 `.inputactions` 文件，在编辑器中配置：

```
GameControls.inputactions:

Action Map: Player（游戏中）
├── Move（Value, Vector2）
│   ├── Binding: WASD（Keyboard）
│   ├── Binding: Left Stick（Gamepad）
│   └── Binding: Touchscreen（左虚拟摇杆）
├── Jump（Button）
│   ├── Binding: Space（Keyboard）
│   └── Binding: South Button / A（Gamepad）
├── Fire（Button）
│   ├── Binding: Left Mouse Button（Mouse）
│   └── Binding: Right Trigger（Gamepad）
└── Look（Value, Vector2）
    ├── Binding: Mouse Delta（Mouse）
    └── Binding: Right Stick（Gamepad）

Action Map: UI（菜单中）
├── Navigate（Value, Vector2）
├── Submit（Button）
└── Cancel（Button）
```

### 3.2 代码生成（推荐）

勾选 `Generate C# Class` 后自动生成强类型代码：

```csharp
// 自动生成的代码使用示例
public class PlayerController : MonoBehaviour, GameControls.IPlayerActions
{
    private GameControls _controls;
    
    private void Awake()
    {
        _controls = new GameControls();
        _controls.Player.SetCallbacks(this); // 注册回调
    }
    
    private void OnEnable()
    {
        _controls.Player.Enable();  // 启用玩家输入
        _controls.UI.Disable();     // 禁用 UI 输入
    }
    
    private void OnDisable()
    {
        _controls.Player.Disable();
    }
    
    // 实现接口方法（自动映射）
    public void OnMove(InputAction.CallbackContext context)
    {
        _moveInput = context.ReadValue<Vector2>();
    }
    
    public void OnJump(InputAction.CallbackContext context)
    {
        // 只在按下时触发（避免 performed + canceled 都触发）
        if (context.phase == InputActionPhase.Started)
        {
            Jump();
        }
    }
    
    public void OnFire(InputAction.CallbackContext context)
    {
        switch (context.phase)
        {
            case InputActionPhase.Started:
                StartFiring(); // 开始持续射击
                break;
            case InputActionPhase.Canceled:
                StopFiring();  // 松开停止射击
                break;
        }
    }
    
    public void OnLook(InputAction.CallbackContext context)
    {
        _lookInput = context.ReadValue<Vector2>();
    }
}
```

## 四、不同输入设备处理

### 4.1 键鼠与手柄差异处理

```csharp
public class InputDeviceHandler : MonoBehaviour
{
    private bool _isUsingGamepad;
    
    private void OnEnable()
    {
        // 监听设备变化
        InputSystem.onActionChange += OnActionChange;
    }
    
    private void OnActionChange(object obj, InputActionChange change)
    {
        if (change == InputActionChange.ActionPerformed)
        {
            var action = obj as InputAction;
            var device = action?.activeControl?.device;
            
            bool wasGamepad = _isUsingGamepad;
            _isUsingGamepad = device is Gamepad;
            
            // 设备切换时更新 UI 提示
            if (wasGamepad != _isUsingGamepad)
            {
                UIManager.Instance.SwitchControlPrompts(_isUsingGamepad);
            }
        }
    }
    
    // 根据当前设备返回对应的按键提示图标
    public Sprite GetActionIcon(string actionName)
    {
        return _isUsingGamepad 
            ? _gamepadIcons[actionName] 
            : _keyboardIcons[actionName];
    }
}
```

### 4.2 移动端触控虚拟摇杆

```csharp
using UnityEngine.InputSystem.OnScreen;

// 使用 Input System 内置的 On-Screen Controls
// 在 Canvas 上放置 On Screen Stick 和 On Screen Button 组件

// 自定义虚拟摇杆实现（更灵活）
public class VirtualJoystick : MonoBehaviour, IPointerDownHandler, IDragHandler, IPointerUpHandler
{
    [SerializeField] private RectTransform _background;
    [SerializeField] private RectTransform _handle;
    [SerializeField] private float _maxRadius = 60f;
    
    public Vector2 Direction { get; private set; }
    
    // 连接到 Input System Action（通过 On-Screen Stick 的路径）
    private string _actionPath = "<VirtualJoystick>/position";
    
    public void OnPointerDown(PointerEventData data)
    {
        // 移动背景到触摸点（浮动摇杆）
        _background.position = data.position;
        OnDrag(data);
    }
    
    public void OnDrag(PointerEventData data)
    {
        Vector2 offset = data.position - (Vector2)_background.position;
        float distance = Mathf.Min(offset.magnitude, _maxRadius);
        Direction = offset.normalized * (distance / _maxRadius);
        
        _handle.anchoredPosition = offset.normalized * distance;
    }
    
    public void OnPointerUp(PointerEventData data)
    {
        Direction = Vector2.zero;
        _handle.anchoredPosition = Vector2.zero;
    }
}
```

## 五、多玩家输入（本地多人游戏）

```csharp
// 使用 PlayerInputManager 管理多玩家
public class LocalMultiplayerManager : MonoBehaviour
{
    [SerializeField] private PlayerInputManager _inputManager;
    
    private List<PlayerController> _players = new();
    
    private void Start()
    {
        // 配置玩家加入模式
        _inputManager.notificationBehavior = PlayerNotifications.InvokeUnityEvents;
        _inputManager.onPlayerJoined += OnPlayerJoined;
        _inputManager.onPlayerLeft += OnPlayerLeft;
        
        // 开启等待玩家加入（按任意键加入）
        _inputManager.EnableJoining();
    }
    
    private void OnPlayerJoined(PlayerInput playerInput)
    {
        var player = playerInput.GetComponent<PlayerController>();
        _players.Add(player);
        
        // 分配玩家颜色/初始位置
        int playerIndex = playerInput.playerIndex;
        player.Initialize(playerIndex, _spawnPoints[playerIndex]);
        
        Debug.Log($"玩家 {playerIndex + 1} 加入，使用设备: {playerInput.devices[0].displayName}");
        
        // 4人全部加入后关闭加入通道
        if (_players.Count >= 4)
            _inputManager.DisableJoining();
    }
    
    private void OnPlayerLeft(PlayerInput playerInput)
    {
        var player = playerInput.GetComponent<PlayerController>();
        _players.Remove(player);
        _inputManager.EnableJoining(); // 重新开放加入
    }
}
```

## 六、输入重映射

```csharp
// 允许玩家自定义按键绑定
public class InputRemappingUI : MonoBehaviour
{
    private GameControls _controls;
    private InputActionRebindingExtensions.RebindingOperation _rebindOperation;
    
    // 开始重映射
    public void StartRebinding(string actionName, int bindingIndex)
    {
        var action = _controls.asset.FindAction(actionName);
        
        // 禁用该 Action 的其他绑定（避免冲突）
        action.Disable();
        
        _rebindOperation = action
            .PerformInteractiveRebinding(bindingIndex)
            .WithControlsExcluding("<Mouse>/position")  // 排除鼠标位置
            .WithControlsExcluding("<Mouse>/delta")
            .OnMatchWaitForAnother(0.1f) // 短暂延迟避免误触
            .OnComplete(operation =>
            {
                action.Enable();
                operation.Dispose();
                
                // 保存自定义绑定
                string rebinds = _controls.asset.SaveBindingOverridesAsJson();
                PlayerPrefs.SetString("InputRebindings", rebinds);
                
                UpdateButtonUI(actionName, bindingIndex);
            })
            .OnCancel(operation =>
            {
                action.Enable();
                operation.Dispose();
            })
            .Start();
        
        // 显示"请按任意键..."提示
        ShowWaitingForInputUI(actionName);
    }
    
    // 加载自定义绑定
    public void LoadSavedBindings()
    {
        string rebinds = PlayerPrefs.GetString("InputRebindings", "");
        if (!string.IsNullOrEmpty(rebinds))
        {
            _controls.asset.LoadBindingOverridesFromJson(rebinds);
        }
    }
    
    // 重置为默认
    public void ResetToDefaults()
    {
        _controls.asset.RemoveAllBindingOverrides();
        PlayerPrefs.DeleteKey("InputRebindings");
    }
}
```

## 七、输入测试（单元测试）

```csharp
// New Input System 支持模拟输入，便于自动化测试
using UnityEngine.InputSystem;

public class PlayerInputTests : InputTestFixture
{
    private Gamepad _gamepad;
    private PlayerController _player;
    
    [SetUp]
    public override void Setup()
    {
        base.Setup();
        
        // 注册虚拟手柄设备
        _gamepad = InputSystem.AddDevice<Gamepad>();
        
        // 创建测试场景
        var playerGO = new GameObject("Player");
        _player = playerGO.AddComponent<PlayerController>();
    }
    
    [Test]
    public void Player_JumpsWhenAButtonPressed()
    {
        // 模拟按下 A 键
        Press(_gamepad.buttonSouth);
        
        Assert.IsTrue(_player.IsJumping, "按下A键后玩家应该在跳跃状态");
    }
    
    [Test]
    public void Player_MovesCorrectly()
    {
        // 模拟左摇杆向右
        Set(_gamepad.leftStick, new Vector2(1, 0));
        
        // 等待一帧处理
        InputSystem.Update();
        
        Assert.AreEqual(Vector2.right, _player.MoveDirection);
    }
    
    [TearDown]
    public override void TearDown()
    {
        InputSystem.RemoveDevice(_gamepad);
        base.TearDown();
    }
}
```

## 八、常见问题解决

### 8.1 输入事件丢失

```csharp
// 问题：快速点击时 started 和 canceled 在同一帧内，导致事件丢失
// 解决：使用 Fixed Update 处理输入（适合物理相关输入）

public class RobustInputHandler : MonoBehaviour
{
    private bool _jumpPressedThisFrame;
    
    private void OnJump(InputAction.CallbackContext ctx)
    {
        if (ctx.started)
            _jumpPressedThisFrame = true;
    }
    
    // 在 FixedUpdate 中消费输入（确保物理帧都能响应）
    private void FixedUpdate()
    {
        if (_jumpPressedThisFrame)
        {
            PerformJump();
            _jumpPressedThisFrame = false;
        }
    }
}
```

### 8.2 UI 与游戏输入切换

```csharp
// 打开背包/菜单时切换输入模式
public class InputModeManager : MonoBehaviour
{
    private PlayerInput _playerInput;
    
    public void OpenInventory()
    {
        // 切换到 UI 模式，游戏输入自动禁用
        _playerInput.SwitchCurrentActionMap("UI");
        
        // 显示鼠标光标
        Cursor.lockState = CursorLockMode.None;
        Cursor.visible = true;
    }
    
    public void CloseInventory()
    {
        // 切回游戏模式
        _playerInput.SwitchCurrentActionMap("Player");
        
        // 锁定鼠标光标（第一人称视角）
        Cursor.lockState = CursorLockMode.Locked;
        Cursor.visible = false;
    }
}
```

> 💡 **迁移建议**：如果你的项目还在用旧 Input 系统，不需要立即重构。旧系统对于简单的单平台项目完全够用。当你面临：多平台适配、多玩家支持、自定义按键绑定需求时，再迁移到新系统，这样迁移成本最低、收益最高。
