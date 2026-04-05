---
title: 特效数据模型设计：锁轴与时间轴驱动
published: 2026-03-31
description: 解析游戏特效数据模型的层次化设计，包含 LockMask 位域枚举的精细锁轴控制、EffectGroup 的动画-特效绑定机制，以及特效与角色骨骼的挂载方式。
tags: [Unity, 特效系统, 数据模型, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 特效数据模型设计：锁轴与时间轴驱动

## 前言

游戏特效看似只是"某个位置某个时刻播放粒子效果"，但在实际工程中，它的数据模型极其精细：特效何时出现、持续多久、跟不跟随骨骼移动、旋转方向是否锁定、位置是否在特定轴上固定……

本文通过分析 `EffectInfo` 及其相关数据结构，带你理解游戏特效数据模型的完整设计。

---

## 一、特效数据的层次结构

```
EffectInfo（总容器）
  └─ List<EffectGroup>（按动画分组）
        ├─ EffectAnimationClipData（触发条件：动画名）
        ├─ List<EffectClipData>（具体特效列表）
        └─ EffectSceneClipData（场景级 Timeline）
```

这个层次设计体现了特效与动画的**绑定关系**：一个 `EffectGroup` 对应一个动画片段（通过 `clipName` 标识），当该动画播放时，自动触发组内的所有特效。

**为什么要按动画分组？**

角色的特效通常与动画紧密耦合：
- 攻击动画 → 武器拖尾特效
- 受击动画 → 闪光特效
- 死亡动画 → 消散粒子

把特效和动画绑定在一起，使得策划可以在配置工具中直接对"攻击动画"添加特效，而不需要写代码逻辑。

---

## 二、LockMask：精细的轴锁控制

`LockMask` 是本文最值得深入讲解的设计：

```csharp
[Flags]
public enum LockMask : byte
{
    None     = 0,        // 完全跟随挂点
    Rotation = 1,        // 锁定旋转（不跟随旋转）
    Position = 2,        // 锁定位置（不跟随位移）
    Both     = 3,        // 同时锁定位置和旋转

    PositionX = 1 << 2,  // 仅锁定 X 轴位移
    PositionY = 1 << 3,  // 仅锁定 Y 轴位移
    PositionZ = 1 << 4,  // 仅锁定 Z 轴位移
    RotationX = 1 << 5,  // 仅锁定 X 轴旋转
    RotationY = 1 << 6,  // 仅锁定 Y 轴旋转
    RotationZ = 1 << 7,  // 仅锁定 Z 轴旋转

    PositionAll         = PositionX | PositionY | PositionZ,
    RotationAll         = RotationX | RotationY | RotationZ,
    BothAll             = PositionAll | RotationAll,
    PositionY_Rotation  = PositionY | Rotation,  // 常用组合
}
```

### 2.1 为什么需要锁轴？

想象一个挂在手掌骨骼上的剑气特效。正常情况下它跟随手掌移动和旋转，看起来很自然。但：

- **圆形的魔法阵**：应该始终水平（锁定 `RotationX` 和 `RotationZ`），不随手腕扭转而倾斜
- **头顶的血量条**：应该始终垂直往上（锁定所有旋转，锁定 X/Z 位移，只跟随 Y 方向）
- **落地的冲击波**：应该始终在地面高度（锁定 `PositionY`），不随角色跳跃而上升

### 2.2 位域枚举的组合使用

```csharp
// 在 HurtHitEvent 中看到的实际使用
FxInfo = new FxInfo
{
    lockMask = LockMask.Rotation  // 只锁旋转，位置跟随
}

FxInfo = new FxInfo
{
    lockMask = LockMask.None      // 完全跟随
}

FxInfo = new FxInfo
{
    lockMask = LockMask.PositionY_Rotation  // 锁定 Y 轴位移和旋转
}
```

位域枚举（`[Flags]`）允许任意组合：`LockMask.PositionX | LockMask.RotationZ` 表示同时锁定 X 轴位移和 Z 轴旋转。

---

## 三、EffectClipData：单个特效的完整描述

```csharp
public partial class EffectClipData
{
    public float  EnterTime;        // 在动画的第几秒触发
    public int    EnterFrame;       // 在动画的第几帧触发（优先级高于 EnterTime）
    public float  Duration;         // 持续时间（0 = 特效自然结束）
    public string addressablePath;  // Addressables 资源路径
    public EffectPosMode effectPosMode;  // 位置模式（世界坐标/挂点坐标）
    public string joint;            // 骨骼挂点名称（空=根节点）
    public LockMask lockMask;       // 锁轴配置
    public Vector3 birthPosition;  // 初始位置偏移
    public Vector3 birthRotation;  // 初始旋转偏移
    public Vector3 birthScale;     // 初始缩放
    public bool   cameraJointVfx;  // 是否相对相机坐标系
    public int    LeaveFrameWhenUnLockAxis; // 脱锁时机
    public bool   uiJointVfx;      // 是否 UI 坐标系
}
```

**`EnterFrame` 优先于 `EnterTime`：**

帧同步游戏的特效触发应该基于"帧"而非"时间"，这样在 TimeScale 变化（慢动作）时，特效时机依然正确。`EnterFrame` 是帧同步下的精确控制，`EnterTime` 是非帧同步场景的备用。

**`cameraJointVfx` 和 `uiJointVfx`：**

这两个标志处理特殊的坐标系场景：
- `cameraJointVfx = true`：特效相对于摄像机坐标系（用于贴近相机的全屏效果）
- `uiJointVfx = true`：特效挂载在 UI Canvas 坐标系中（用于 UI 上的粒子装饰）

---

## 四、EffectPosMode：位置模式

```csharp
public enum EffectPosMode : Int16
{
    None  = -1,  // 未指定（使用传入的绝对坐标）
    World = 0,   // 世界坐标系
    Point = 1,   // 相对挂点坐标系
}
```

| 模式 | 坐标基准 | 典型用途 |
|------|---------|---------|
| `None` | 事件传入的绝对坐标 | 受击特效（用碰撞点世界坐标） |
| `World` | 世界坐标系 | 场景级特效（爆炸、光柱） |
| `Point` | 骨骼挂点坐标系 | 跟随角色的特效（光环、拖尾）|

---

## 五、effectCache：动画名反查特效组

```csharp
[NonSerialized]
public Dictionary<string, List<EffectGroup>> effectCache;

public void OnAfterDeserialize()
{
    effectCache = new Dictionary<string, List<EffectGroup>>();
    foreach (var group in groups)
    {
        effectCache.TryAdd(group.animationClipData.clipName, new List<EffectGroup>());
        effectCache[group.animationClipData.clipName].Add(group);
    }
}
```

这是一个**反序列化后的索引缓存**：

`groups` 是按序列化顺序存储的列表（磁盘友好），但运行时需要"当前播放的动画叫什么名字，对应哪些特效组"的快速查询。

`effectCache` 在反序列化后立刻构建，之后的每次查询都是 O(1) 字典查找，而不是 O(N) 列表遍历。

`[NonSerialized]` 标记确保这个运行时缓存不会被序列化——它每次从 `groups` 重建，没有必要存储。

---

## 六、ActionType：动画驱动 vs Timeline 驱动

```csharp
public enum ActionType
{
    AnimationClip,  // 由 AnimationClip 播放时驱动
    Timeline,       // 由 Timeline 播放时驱动
}
```

特效的触发来源有两种：

- **AnimationClip**：通过 Animancer/Animator 的 State Machine 播放，适合逻辑驱动的动作
- **Timeline**：由 Unity Timeline 时间轴编辑器控制，适合有明确时间线的过场演出

两种方式各有优势，通过 `ActionType` 标志让特效系统知道应该如何解析 `clipName`。

---

## 七、数据设计的序列化一致性

注意代码中有大量的 `[FormerlySerializedAs]`：

```csharp
[FormerlySerializedAs("enterTime")]
[fsSerializeAs("EnterTime")]
[MemoryPackOrder(0)]
public float EnterTime;
```

这三个 Attribute 处理了字段重命名的向后兼容：
- `[FormerlySerializedAs("enterTime")]`：Unity 序列化（UnityJSON/AssetDatabase），旧存档叫 `enterTime` 的数据也能读取
- `[fsSerializeAs("EnterTime")]`：FullSerializer（JSON），映射到 `EnterTime`
- `[MemoryPackOrder(0)]`：MemoryPack 二进制序列化，按索引 0 标识

一份数据同时支持三套序列化系统，这是大型项目在多种序列化框架共存时的常见做法。

---

## 八、总结

| 设计要素 | 解决的问题 |
|---------|-----------|
| 动画-特效绑定 | 策划可视化配置"哪个动画触发哪个特效" |
| LockMask 位域 | 精细控制特效跟随骨骼的方式 |
| EnterFrame | 帧同步下精确触发时机 |
| effectCache 索引 | O(1) 反查，避免运行时遍历 |
| ActionType | 兼容动画系统和 Timeline 两种触发源 |
| 三套序列化兼容 | 历史数据迁移不丢失 |

特效数据模型的精细程度，直接决定了美术和策划能否独立配置出高质量的视觉效果。一套好的数据模型，能让非程序成员完成 80% 的特效工作，程序员只需要维护框架。
