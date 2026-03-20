---
title: BlendTree 混合树详解
published: 2020-06-14
description: "Unity Animator 中 BlendTree 混合树的完整使用指南，包括 1D/2D 混合、参数配置、与 Transition 混合的区别，以及实战案例。"
tags: [Unity, 动画系统, 游戏开发]
category: 游戏开发
draft: false
---

## 什么是 BlendTree

BlendTree（混合树）是 Unity Animator 中用于**解决多个动画之间平滑混合**的功能，常用于移动动画的混合（站立、走路、跑步等中间状态）。

## BlendTree vs Transition 混合的区别

| 特性 | BlendTree | Transition 混合 |
|------|-----------|----------------|
| **触发时机** | 持续混合（实时） | 仅在状态转换期间 |
| **目的** | 生成中间动画状态 | 平滑过渡，避免突兀 |
| **参数驱动** | 是（浮点参数） | 否（时间驱动）|
| **典型场景** | 速度驱动的移动动画 | 攻击→待机 的切换 |

**示例**：角色速度从 0 到 5m/s 变化时：
- `Transition` 只能在 Walk 和 Run 之间切换，有突变感
- `BlendTree` 可以根据速度值平滑混合 Stand/Walk/Run，自然流畅

## 1D BlendTree

最常用的类型，通过**一个浮点参数**控制多个动画的混合：

**配置步骤**：
1. 在 Animator 中创建 float 参数（如 `Speed`）
2. 在 State 中选择 Motion 类型为 Blend Tree
3. 选择 Blend Type 为 `1D`
4. 设置 Parameter 为 `Speed`
5. 添加动画 Clip 并设置对应阈值

**参数配置示例**：
```
Speed = 0.0  →  Idle（待机）
Speed = 2.0  →  Walk（走路）
Speed = 5.0  →  Run（跑步）

当 Speed = 3.0 时：
  Walk 权重 = (5-3)/(5-2) = 0.67
  Run  权重 = (3-2)/(5-2) = 0.33
```

## 2D BlendTree

通过**两个浮点参数**控制动画混合，适合需要方向感的移动（八方向移动）：

**常见类型**：
- `2D Simple Directional`：方向不重叠，适合 4/8 方向移动
- `2D Freeform Directional`：允许多个方向，适合复杂情况
- `2D Freeform Cartesian`：笛卡尔坐标，X/Y 独立

**配置示例（8方向移动）**：
```
参数：VelocityX, VelocityZ
    
    (-1, 1)  前左   (0, 1)  前   (1, 1)  前右
    (-1, 0)  左     (0, 0)  待机  (1, 0)  右
    (-1,-1)  后左   (0,-1)  后   (1,-1)  后右
```

## 代码控制

```csharp
private Animator _animator;
private static readonly int SpeedHash = Animator.StringToHash("Speed");
private static readonly int VelocityXHash = Animator.StringToHash("VelocityX");
private static readonly int VelocityZHash = Animator.StringToHash("VelocityZ");

void Update()
{
    // 1D BlendTree：控制移动速度
    float speed = _rigidbody.velocity.magnitude;
    _animator.SetFloat(SpeedHash, speed, 0.1f, Time.deltaTime);  // 平滑插值
    
    // 2D BlendTree：控制方向
    Vector3 localVelocity = transform.InverseTransformDirection(_rigidbody.velocity);
    _animator.SetFloat(VelocityXHash, localVelocity.x, 0.1f, Time.deltaTime);
    _animator.SetFloat(VelocityZHash, localVelocity.z, 0.1f, Time.deltaTime);
}
```

> `SetFloat` 的第三个参数是**平滑时间**，可以让参数变化更平滑，避免动画抖动。

## 嵌套 BlendTree

BlendTree 可以嵌套使用，适合复杂的动画混合需求：

```
移动 BlendTree（1D, Speed 参数）
    ├── Idle
    ├── 地面移动 BlendTree（2D, VelX/VelZ 参数）
    │   ├── Walk_Forward
    │   ├── Walk_Back
    │   ├── Walk_Left
    │   └── Walk_Right
    └── Run
```

## 性能注意事项

- BlendTree 中的每个动画 Clip 都会参与采样，**动画数量越多性能越低**
- 建议使用 `Animator.StringToHash` 缓存参数 ID，避免每帧字符串查找
- 对于高频更新的参数，使用 `SetFloat` 的平滑版本避免 GC
