---
title: 战斗输入系统设计——虚拟按键、相机转向与长按检测的完整实现
published: 2026-03-31
description: 深度解析手游战斗输入管理器的架构，包括InputSystem动作绑定、VKey事件转发、相机相对移动方向计算与长按计时器
tags: [Unity, 输入系统, 战斗系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗输入系统设计——虚拟按键、相机转向与长按检测的完整实现

手游的输入系统不只是"检测触摸"，它需要把物理输入（触摸、摇杆）转换成游戏语义（移动方向、技能释放），同时处理相机朝向的影响、长按判断、帧同步约束等复杂问题。

VGame项目的`InputComponentSystem`实现了一套完整的战斗输入管理系统，本文深入分析这套设计。

## 一、InputComponent的架构层级

```
InputComponent（ET组件，逻辑驱动）
    ├── PlayerInput（Unity New Input System）
    ├── InputSystem（自定义输入映射系统）
    │     └── LongPressInfos（长按状态字典）
    └── CombineButtons（组合按键配置）
```

`InputComponent`作为输入系统的核心，桥接了Unity的`PlayerInput`（物理输入）和游戏的`TeamInputComponent`（帧同步输入）。

## 二、初始化流程

```csharp
[EntitySystem]
private static void Awake(this InputComponent self)
{
    InputComponent.Instance = self; // 单例，方便全局访问
    
    // 1. 绑定Unity New Input System的PlayerInput组件
    self._playerInput = GlobalComponent.Instance.Global.GetComponent<PlayerInput>();
    self._playerInput.onActionTriggered += self.PlayerInputOnActionTriggered;
    self._playerInput.onControlsChanged += self.HandleControlChange;
    
    // 2. 初始化手柄震动组件
    var rumbler = self._playerInput.GetComponent<Rumbler>();
    if (rumbler == null) self._playerInput.gameObject.AddComponent<Rumbler>();
    
    // 3. 禁用UI导航（防止游戏手柄的方向键意外操作UI）
    UnityEngine.EventSystems.EventSystem.current.sendNavigationEvents = false;
    
    // 4. 初始化自定义输入映射系统
    self.InputSystem = new(self.ClientScene());
    self.InputSystem.Create(self.CombineButtons);
    
    // 5. 注册UI控制器
    UIController.RegistEvent(self);
    self.DeactivateUI(true); // 初始激活游戏输入（不激活UI输入）
    
    // 6. 设置默认操作类型处理器
    self.OperateTypeHandler[(int)EPlayerInputOperateType.Default] = self.OnDefaultInputUpdate;
    
    // 7. Editor环境下加载技能输入配置
    if (Define.IsEditor)
    {
        var path = "GameCfg/Input/SkillInput.json";
        // ...从JSON文件加载技能输入调试配置
    }
}
```

**`EventSystem.sendNavigationEvents = false`的用途**：

手柄/键盘的方向键在Unity中默认会导航UI（选中按钮、在输入框中移动光标）。在战斗游戏中，方向键用于控制角色移动，不希望同时影响UI。关闭后，WASD/方向键只会触发游戏输入，不会触发UI导航。

## 三、Update：操作目标分发

```csharp
[EntitySystem]
private static void Update(this InputComponent self)
{
    // 保存原始输入值（在相机转换前）
    self.RawMove = self.move;
    self.RawJump = self.jump;
    self.RawSprint = self.sprint;
    
    // 分发到当前操作目标（当前控制的队伍实体）
    if (self.CurrentOperateInfo.OperateTarget != null)
    {
        if (self.OperateTypeHandler.ContainsKey((int)self.CurrentOperateInfo.OperateType))
        {
            self.OperateTypeHandler[(int)self.CurrentOperateInfo.OperateType]
                .Invoke(self.CurrentOperateInfo.OperateTarget);
        }
    }
    
    // 处理长按计时器
    foreach (var kv in self.InputSystem.LongPressInfos)
    {
        var lst = kv.Value;
        for (int i = 0; i < lst.Count; i++)
        {
            if (!lst[i].press) continue;
            
            lst[i].time += Time.deltaTime;
            if (lst[i].time >= lst[i].totalTime)
            {
                lst[i].press = false;
                lst[i].time = 0;
                lst[i].callback?.Invoke(kv.Key); // 触发长按回调
            }
        }
    }
}
```

`OperateTypeHandler`是一个字典，`EPlayerInputOperateType → Action<TeamEntity>`，不同的操作类型有不同的处理方式：
- `Default`：标准战斗操作（移动+技能）
- 可能还有`FreeLook`（自由镜头模式）、`Dialogue`（对话状态，输入屏蔽）等

通过字典分发，切换操作类型只需要修改`CurrentOperateInfo.OperateType`，不需要大量if-else。

## 四、长按检测系统

```csharp
// LongPressInfo结构（推测）
class LongPressInfo
{
    public bool press;        // 当前是否按下
    public float time;        // 已按下的时间
    public float totalTime;   // 触发长按所需的时间
    public Action<EInputKey> callback; // 长按触发的回调
}
```

长按检测用简单的累计时间实现：
1. 按键按下时设置`press=true`，重置`time=0`
2. 每帧在Update里累加`Time.deltaTime`
3. 达到`totalTime`时触发`callback`，设置`press=false`防止重复触发
4. 按键释放时设置`press=false`（取消长按计时）

这比Unity的`InputAction.performed`（LongPress Interaction）更灵活：游戏可以动态设置每个技能的长按时间阈值，而Unity的LongPress Interaction是静态的。

## 五、移动方向的相机转换

这是输入系统最关键的逻辑——把"玩家向前推摇杆"转换成"相对于相机朝向的世界坐标移动方向"：

```csharp
public static void OnDefaultInputUpdate(this InputComponent self, TeamEntity target)
{
    var camera = self.DomainScene().CurrentScene().GetComponent<CameraComponent>();
    if (camera != null)
    {
        camera.UpdateInput(self);   // 相机处理输入（如摄像机旋转）
        camera.UpdateCamera();      // 更新相机位置
    }
    
    // 把2D摇杆输入转换为3D方向（XZ平面，Y轴始终为0）
    Vector3 inputDirection = new Vector3(self.move.x, 0.0f, self.move.y).normalized;
    
    // 计算相对于相机Y轴旋转的目标朝向角度
    var _targetRotation = Mathf.Atan2(inputDirection.x, inputDirection.z) * Mathf.Rad2Deg
                        + camera.GetCameraTrans().eulerAngles.y;
    
    // 根据角度和摇杆力度计算世界坐标移动方向
    Vector3 targetDirection = Quaternion.Euler(0.0f, _targetRotation, 0.0f) * Vector3.forward;
    
    // 发布移动输入事件（乘以摇杆力度magnitude，允许慢走）
    self.RootDispatcher().FireEvent(new Evt_InputVKey() 
    { 
        team = target, 
        key = EInputKey.Move, 
        vector = (targetDirection * self.move.magnitude).ToTSVector() 
    });
}
```

**`Atan2(x, z) + camera.Y`的数学解释**：

1. `Atan2(move.x, move.z)`：把摇杆方向（屏幕空间）转换为角度（0°=上方，90°=右方）
2. `+ camera.Y`：加上相机Y轴旋转，把"屏幕空间的上方"对齐到"相机面朝方向"
3. `Quaternion.Euler(0, angle, 0) * Vector3.forward`：把角度转回3D方向向量

结果：玩家向上推摇杆时，角色朝相机面向方向（也就是玩家视角的"前方"）移动，而不是世界坐标的North方向。这是所有TPS游戏的标准操作感。

## 六、输入事件→帧同步输入

```csharp
private static void OnInputVKey(this InputComponent self, Evt_InputVKey evt)
{
    var teamInput = evt.team.GetComponent<TeamInputComponent>();
    if (teamInput != null)
    {
        if (evt.key == EInputKey.Move)
        {
            // 移动：连续值（Vector，保留大小表示速度）
            teamInput.SetInputValue(EInputKey.Move, evt.vector);
        }
        else
        {
            // 技能/动作：离散值（bool，按了就是true）
            if (evt.key == EInputKey.BonusScene && evt.extraInfo != 0)
                evt.team.BonusSceneId = evt.extraInfo; // 携带额外参数
            
            teamInput.SetInputValue(evt.key, true, true);
        }
    }
}
```

`TeamInputComponent`是帧同步输入缓冲区，存储"本物理帧的所有输入"，TrueSync在下一物理帧读取这些输入并执行。

**为什么要分移动和技能两种处理？**

- **移动**：连续输入，需要精确的方向和大小（Vector），小幅推摇杆应该慢走
- **技能**：离散输入，只关心"按了没有"，方向从角色朝向或目标方向计算

## 七、Editor中的技能输入调试

```csharp
if (Define.IsEditor)
{
    var path = "GameCfg/Input/SkillInput.json";
    var json = File.Exists(path) ? File.ReadAllText(path) : null;
    self.skillInputConf = new SkillInputConf();
    if (!string.IsNullOrEmpty(json))
        self.skillInputConf = JSONSerializer.Deserialize<SkillInputConf>(json);
}
```

Editor环境下，从JSON文件读取技能键位配置。这允许在不修改代码的情况下调整键盘→技能的映射（比如把Q键映射到1号技能）。对于没有触摸屏的PC开发环境，这让测试人员可以用键盘操控技能。

`SkillInputConf`包含`vkeyDic`（虚拟按键配置）和`camDic`（相机输入配置），覆盖了战斗中所有需要键盘模拟的输入场景。

## 八、总结

战斗输入系统的设计精华：

| 设计点 | 价值 |
|--------|------|
| 操作类型字典 | 切换操作模式不需要if-else，扩展方便 |
| 相机转向转换 | 玩家操作感相对于视角，符合直觉 |
| 长按计时器 | 精细控制长按触发阈值 |
| InputVKey事件 | 输入系统和帧同步系统解耦 |
| Editor JSON配置 | 无触摸屏的PC开发环境可测试 |

对新手来说，"把物理输入→语义输入→帧同步输入"这三层转换的清晰分离，是可维护的输入系统的基础。每层只关心自己的转换工作，不直接跨层调用。
