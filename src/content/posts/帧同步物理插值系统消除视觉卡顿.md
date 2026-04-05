---
title: 帧同步物理插值系统：消除视觉卡顿
published: 2026-03-31
description: 深入解析帧同步游戏中物理模拟与渲染之间的位置插值机制，理解如何用 Lerp/Slerp 消除逻辑帧步进导致的视觉抖动，以及 FakeView 模式的应用。
tags: [Unity, 帧同步, 物理系统, 渲染优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 帧同步物理插值系统：消除视觉卡顿

## 前言

帧同步游戏有一个固有矛盾：**逻辑帧是固定步长的**（比如 20FPS），但**渲染帧是可变的**（手机可能跑到 60FPS 甚至 120FPS）。

如果角色的 `transform.position` 直接等于逻辑帧的离散位置，30FPS 的逻辑帧在 60FPS 的显示器上每隔一帧才有新位置——角色会明显"跳着走"，视觉体验极差。

解决方案是**渲染插值（Interpolation）**：在两个逻辑帧之间，根据当前渲染时刻在前后两个逻辑位置之间插值，让角色运动丝滑连续。

---

## 一、位置数据的两份拷贝

插值需要知道"从哪里到哪里"，因此 `PhysicsComponent` 存储了两个时刻的位置：

```csharp
public TSVector InitialTickPosition;  // 上一逻辑帧结束时的位置
public TSVector TransientPosition;    // 当前逻辑帧计算出的新位置

public TSQuaternion InitialTickRotation;  // 上一帧的旋转
public TSQuaternion TransientRotation;    // 当前帧的旋转
```

`TS` 前缀表示这是**定点数（TrueSync）**类型——用于帧同步中的确定性计算，不会因为浮点精度不同导致各客户端计算结果不一致。

---

## 二、渲染插值的核心代码

```csharp
public static void InterpolationUpdate(this PhysicsComponent self, FP interpolationFactor)
{
    // 暂停/冻结状态下不插值
    if (self.GetParent<Unit>().PauseOrFreeze && !self.bInterpolationFactor)
        return;

    // FakeView 模式下不更新视图
    if (GameObjectComponent.bFakeView)
        return;

    self.bInterpolationFactor = false;

    var ga = self.Parent.GetComponent<GameObjectComponent>();
    if (ga != null && ga.GameObject != null)
    {
        ga.GameObject.transform.SetPositionAndRotation(
            // 位置插值
            Vector3.Lerp(
                self.InitialTickPosition.ToVector3(),
                self.TransientPosition.ToVector3(),
                interpolationFactor.AsFloat()),
            // 旋转插值
            Quaternion.Slerp(
                self.InitialTickRotation.ToQuaternion(),
                self.TransientRotation.ToQuaternion(),
                interpolationFactor.AsFloat())
        );
    }
}
```

### 2.1 `interpolationFactor`：插值系数

`interpolationFactor` ∈ [0, 1]，由外部每帧计算传入：

```
factor = (当前渲染时间 - 上一逻辑帧时间) / 逻辑帧步长
```

例如：
- 逻辑帧步长 = 50ms（20FPS）
- 当前渲染帧在两个逻辑帧之间，已过 20ms
- `factor = 20 / 50 = 0.4`

用 `factor = 0.4` 插值，物体显示在从 `Initial` 到 `Transient` 20% 的位置。

### 2.2 Lerp vs Slerp

| 方法 | 全称 | 用于 | 特点 |
|-----|------|-----|------|
| `Lerp` | Linear Interpolation | 位置 | 线性插值，计算简单 |
| `Slerp` | Spherical Linear Interpolation | 旋转 | 球面线性插值，旋转平滑 |

旋转必须用 `Slerp` 而不是 `Lerp`——四元数的线性插值（nlerp）在角度变化大时会出现非均匀速度的问题（旋转越慢越快），`Slerp` 保证角速度恒定。

`SetPositionAndRotation` 合并了两次 Transform 写入，比 `position = ...` + `rotation = ...` 减少了一次 native 调用。

---

## 三、暂停/冻结时的处理

```csharp
if (self.GetParent<Unit>().PauseOrFreeze && !self.bInterpolationFactor)
    return;
```

当单位处于冻结状态（被 CC 控制、战斗暂停等），不应该插值移动——冻结就是"静止"的视觉表现。

`bInterpolationFactor` 是一个例外标志：即使在暂停/冻结状态，如果逻辑上需要强制插值一次（比如冻结前最后一帧的对齐），也可以通过设置这个标志跳过检查。

---

## 四、FakeView 模式的作用

```csharp
if (GameObjectComponent.bFakeView)
    return;
```

当 `bFakeView = true` 时，整个视图更新被跳过。这在以下场景使用：

1. **服务端模拟**：纯逻辑运行，不需要渲染任何东西
2. **战斗回放验证**：快速回放录像验证哈希一致性
3. **性能分析**：隔离渲染开销，单独测试逻辑性能

---

## 五、调试用的轨迹绘制

```csharp
#if UNITY_EDITOR
public static int DebugCount = (int)(5f / Time.fixedDeltaTime);
public static Color DebugColor = Color.cyan;

public static void PostSimulationInterpolationUpdateView(this PhysicsComponent self, FP deltaTime)
{
    var newPos = self.TransientPosition;
    self.DebugPoses.Add(newPos);
    if (self.DebugPoses.Count > DebugCount)
        self.DebugPoses.RemoveAt(0);  // 保留最近 5 秒的位置
}

// 在 InterpolationUpdate 中绘制
for (int i = 0; i < self.DebugPoses.Count - 1; i++)
{
    Debug.DrawLine(self.DebugPoses[i].ToVector3(), self.DebugPoses[i + 1].ToVector3(), DebugColor);
}
#endif
```

`#if UNITY_EDITOR` 宏保证这段代码**只在编辑器中存在**，不会影响发布版本的性能。

`DebugCount = 5f / Time.fixedDeltaTime`：保留最近 5 秒的位置历史，用 `DrawLine` 连成轨迹线。

这个功能在调试物理同步问题时极其有用：如果多个客户端的轨迹线不一致，说明存在帧同步确定性 Bug。

---

## 六、插值触发时机

```csharp
[Event(SceneType.Current)]
public class PostSimulationInterpolationUpdateEvent : AEvent<Evt_PostSimulationInterpolationUpdate>
{
    protected override void Run(Scene scene, Evt_PostSimulationInterpolationUpdate args)
    {
        var worldComp = scene.GetComponent<WorldComponent>();
        worldComp._lastCustomInterpolationStartTime = Time.time;
        worldComp._lastCustomInterpolationDeltaTime = args.deltaTime;

#if UNITY_EDITOR
        args.unit.GetComponent<PhysicsComponent>()
            ?.PostSimulationInterpolationUpdateView(args.deltaTime);
#endif
    }
}
```

这个事件在**每次物理模拟步骤之后**发出，用于记录插值的时间基准。`WorldComponent` 缓存了最后一次插值的开始时间和 deltaTime，供渲染帧计算 `interpolationFactor` 时使用。

---

## 七、插值系统的完整时序

```
逻辑帧（固定 50ms 一次）：
  t=0ms   保存 InitialTickPosition = 上一帧结束位置
           运行物理模拟
           更新 TransientPosition = 新位置
           发布 PostSimulationInterpolationUpdateEvent

渲染帧（可变，例如 16.7ms 一次 = 60fps）：
  t=10ms  factor = 10/50 = 0.2
           InterpolationUpdate(0.2)
           GameObject.position = Lerp(Initial, Transient, 0.2)

  t=16.7ms factor = 16.7/50 ≈ 0.33
            InterpolationUpdate(0.33)
            GameObject.position = Lerp(Initial, Transient, 0.33)

  t=33.4ms factor = 33.4/50 ≈ 0.67
            InterpolationUpdate(0.67)
            ...

  t=50ms  下一逻辑帧开始
           保存 InitialTickPosition = TransientPosition
           ...
```

---

## 八、总结

| 设计要素 | 作用 |
|---------|-----|
| 双重位置存储（Initial + Transient）| 插值所需的两个端点 |
| 定点数（TSVector）| 帧同步确定性，各端相同 |
| Lerp（位置）+ Slerp（旋转）| 线性插值位置，球面插值旋转，两者最优算法 |
| 暂停/冻结检查 | 静止状态不插值，保持逻辑语义 |
| FakeView 开关 | 无渲染模式，用于服务端或性能测试 |
| `#if UNITY_EDITOR` 调试轨迹 | 零运行时开销的调试工具 |

渲染插值是帧同步游戏"看起来流畅"的关键技术。理解它不仅对帧同步游戏有用，对任何"逻辑帧率低于渲染帧率"的系统（如网络同步角色）都有直接参考价值。
