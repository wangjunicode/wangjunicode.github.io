---
title: Unity战斗跳字系统设计与实现
published: 2026-03-31
description: 从数据结构到渲染策略，深度解析战斗伤害数字飘字（跳字）系统的完整设计，包含多类型跳字、位置计算、缩放策略和防重叠机制。
tags: [Unity, UI系统, 战斗HUD, 跳字系统]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity战斗跳字系统设计与实现

## 跳字系统的重要性

战斗跳字（Floating Combat Text，俗称"飘字"）是动作游戏和RPG游戏中最常见的战斗反馈元素。每次攻击命中、技能触发、Buff获得，都会在被打击单位头顶弹出数字或文字。

看起来简单，但实际上跳字系统需要解决几个复杂问题：

1. **多种类型的跳字**：普通伤害、暴击、格挡、闪避、Buff获得、积分变化……每种类型的视觉效果、动画参数都不同
2. **世界坐标到屏幕坐标的转换**：跳字要跟着3D角色走，需要实时将世界坐标投影到UI层
3. **防重叠**：同一时刻可能有几十个跳字，如何避免堆叠显示
4. **距离缩放**：摄像机拉近拉远，跳字大小应该相应变化
5. **事件驱动**：战斗逻辑和UI层完全解耦，通过事件通信

本文将深入分析真实项目的跳字系统实现。

---

## 跳字类型体系

首先看数据结构，了解系统支持哪些类型：

```csharp
public enum JumpTextType
{
    BlockDamage,      // 格挡伤害
    DirectDamage,     // 直接伤害
    CriticalDamage,   // 暴击伤害
    Dodged,           // 闪避
    PerfectBlocked,   // 完美格挡
    NumericalGainAP,  // 获得AP数值
    NumericalGainCRP, // 获得CRP数值
    NumericalGainHP,  // 获得HP数值
    BuffGain,         // 获得Buff
    UnAvoid,          // 不可闪避
}
```

每种类型对应不同的视觉参数，通过静态字典配置：

```csharp
public static Dictionary<JumpTextType, JumpTextSetting> JumpTextSettingDic =
    new Dictionary<JumpTextType, JumpTextSetting>()
    {
        { JumpTextType.BlockDamage,    JumpTextSetting.Create(1f,   0.5f, 50, 150, 60f) },
        { JumpTextType.DirectDamage,   JumpTextSetting.Create(1f,   0.5f, 50, 150, 60f) },
        { JumpTextType.CriticalDamage, JumpTextSetting.Create(1.2f, 1f,   50, 200, 60f) },
        { JumpTextType.Dodged,         JumpTextSetting.Create(1.4f, 1f,   50, 200, 120f) },
        { JumpTextType.PerfectBlocked, JumpTextSetting.Create(1.2f, 0.8f, 80, 250, 90f) },
        { JumpTextType.NumericalGainAP,JumpTextSetting.Create(1f,   1f,  100, 200, 120f) },
        { JumpTextType.BuffGain,       JumpTextSetting.Create(1f,   1f,  300, 400, 60f) },
    };
```

`JumpTextSetting.Create(baseScale, baseDuration, minRadius, radius, angleRange)` 参数含义：
- **baseScale**：基础缩放（暴击比普通大）
- **baseDuration**：动画持续时间（特殊效果持续更久）
- **minRadius/radius**：跳字生成的最小/最大半径范围（防止所有跳字叠在同一点）
- **angleRange**：生成方向的角度范围（例如120°表示跳字只往上方扇形区域散开）

**暴击跳字**（CriticalDamage）的 `BaseScale=1.2`，`BaseDuration=1f`，说明暴击数字比普通伤害更大、停留更久——这是专门为了让玩家爽感更强的设计。

---

## 跳字数据结构

```csharp
public class JumpTextData
{
    public int ID;                          // 唯一标识
    public JumpTextType Type;               // 跳字类型
    public JumpTextDurationType jumpTextDurationType;  // 持续时长类型

    public int Value;                       // 数值（伤害量/回复量等）
    public int ModificationIndicator = 0;  // 数值修正方向（>0=↑, <0=↓, =0=无修正）
    public List<PassiveSkill> ModificationSource;      // 修正来源（哪个被动技能改变了数值）

    // 伤害贡献分析
    public List<PassiveSkillDamageInfo> PassiveSkillDamageContributions;

    public string Icon;                     // 技能图标（显示在跳字旁边）
    public BuffSource BuffSource;           // Buff来源（我方技能/敌方技能/战术等）

    public float DurationModifier = 1f;    // 持续时间修正因子
    public float ScaleModifier = 1f;       // 缩放修正因子
    public float CalcDistanceScale = 1f;   // 基于距离计算的缩放

    public Vector2 SpawnReferencePosition; // 屏幕坐标生成参考点

    public Unit Owner;                     // 归属单位
    public Unit FollowTarget;              // 跟随目标（跳字跟随的角色）
    public float FollowTargetDuration;     // 跟随时长

    public bool IsMainMember = true;       // 是否主要成员（控制显示优先级）
}
```

`PassiveSkillDamageContributions` 是一个高级特性——记录每个被动技能对本次伤害的贡献比例。这样在跳字上可以显示"是哪个技能造成了最大伤害"的图标，给玩家丰富的战斗反馈。

---

## 世界坐标到屏幕坐标的转换

```csharp
private static void ShowHurtDamgeJumpText(YIUI_BattleJumpTextComponent self, Unit defender, Unit attacker, JumpTextType jumpTextType)
{
    // 获取虚拟挂点组件（角色身上特定骨骼点的世界坐标）
    var defenderVirtualSkeletonPoint = defender.GetComponent<VirtualSkeletonPointComponent>();
    if (defenderVirtualSkeletonPoint == null) return;

    Vector3 hitPos;
    Vector3 attackerPos;

    if (jumpTextType == JumpTextType.PerfectBlocked || jumpTextType == JumpTextType.Dodged)
    {
        // 完美格挡/闪避：显示在防御方头部上方（挂点3）
        hitPos = GetJumpVPPos(defenderVirtualSkeletonPoint, 3);
        attackerPos = attackerVirtualSkeletonPoint != null 
            ? GetJumpVPPos(attackerVirtualSkeletonPoint, 4) 
            : attacker.Position.ToVector3();
    }
    else
    {
        // 伤害类：显示在实际受击点
        var defenderHurt = defender.GetComponent<HurtComponent>();
        if (defenderHurt?.AttackInfo != null)
        {
            var defenderHitPos = defenderHurt.AttackInfo.DefenderHitPos;
            hitPos = new Vector3(defenderHitPos.x.AsFloat(), defenderHitPos.y.AsFloat(), defenderHitPos.z.AsFloat());
        }
        else
        {
            hitPos = GetJumpVPPos(defenderVirtualSkeletonPoint, 3);
        }
        // ...攻击方位置类似处理
    }

    // 转换到屏幕坐标
    var screenPos = self.CalculatePosition(hitPos, attackerPos, jumpTextType);
    
    // 基于摄像机距离计算缩放
    var mainCamera = UICameraMgr.Instance.GetMainCamera();
    var calcDistanceScale = 1f;
    if (mainCamera)
        calcDistanceScale = self.CalculateSize(hitPos, mainCamera.transform.position);
    
    // 构建跳字数据
    self.SetNewJumpTextDataProp(new JumpTextData
    {
        Type = jumpTextType,
        SpawnReferencePosition = screenPos,
        CalcDistanceScale = calcDistanceScale,
        // ...其他字段
    });
}
```

**虚拟挂点系统**是关键设计——角色有多个预定义的"虚拟骨骼点"（如头部、胸部、命中点等），根据不同的跳字类型选择不同的参考点：
- 格挡/闪避发生在防御方身上，用防御方挂点3（头部上方）
- 实际伤害用真实受击点（由物理碰撞计算出来）

这比简单地用角色根部坐标更精确，视觉上更舒适。

---

## 距离缩放：让远处的跳字也清晰可见

```csharp
public partial class YIUI_BattleJumpTextComponent
{
    public float MinScale = 0.8f;      // 最远距离时的最小缩放
    public float MaxScale = 1.2f;      // 最近距离时的最大缩放
    public float minScaleDistance = 1f; // 触发最大缩放的距离
    public float maxScaleDistance = 5f; // 触发最小缩放的距离
}
```

当摄像机距离角色很近时，跳字应该更大（`MaxScale=1.2`）；很远时更小（`MinScale=0.8`）。这个线性插值计算保证了不同视角下跳字的可读性。

同时还有全局的缩放限制：
```csharp
public static float FinalMinScale = 1f;   // 无论如何不小于1
public static float FinalMaxScale = 2.5f; // 无论如何不超过2.5
```

即使是暴击的巨大数字也不能无限放大，避免遮挡太多画面。

---

## 防重叠的偏移累积系统

当连续受到多次攻击时，跳字会叠加在同一位置显示，需要偏移机制：

```csharp
public int AddRoundOffsetCount;      // 当前偏移圆数
public int MaxAddOffsetCount = 7;    // 最多叠加7次偏移
public float SpreadRadius = 50;      // 散开半径
```

每次新跳字产生时，在生成半径 `SpreadRadius` 内随机偏移，同时追踪 `AddRoundOffsetCount`。当偏移次数超过 `MaxAddOffsetCount` 时重置，跳字从原点重新开始分布。

---

## 响应式属性与事件驱动

战斗逻辑（属于 Gameplay 层）和跳字 UI 完全解耦，通过一个多元响应式属性连接：

```csharp
public MultipleBindableProperty<Evt_HurtHitJumpText, Evt_BattlePointJumpText> JumpTextReactiveProperty =
    new MultipleBindableProperty<Evt_HurtHitJumpText, Evt_BattlePointJumpText>();
```

`MultipleBindableProperty<T, K>` 是一个自定义的响应式属性，需要**两个值同时更新**才会触发回调——这解决了一个经典问题：

战斗结算时，伤害信息（`Evt_HurtHitJumpText`）和积分信息（`Evt_BattlePointJumpText`）是从不同地方发出的。如果分开监听，UI 会先后收到两个事件，但跳字需要同时知道这两个信息才能完整显示。

`MultipleBindableProperty` 的实现原理：

```csharp
public class MultipleBindableProperty<T, K>
{
    bool hashValue1 = false;
    bool hashValue2 = false;
    BindableProperty<T> value1 = new BindableProperty<T>();
    BindableProperty<K> value2 = new BindableProperty<K>();

    void Dispatch()
    {
        // 两个值都收到了才触发
        if (hashValue1 && hashValue2)
        {
            mOnValueChanged.Invoke(value1.Value, value2.Value);
            hashValue1 = false;
            hashValue2 = false;
        }
    }

    void OnValue1Change(T value1) { hashValue1 = true; Dispatch(); }
    void OnValue2Change(K value2) { hashValue2 = true; Dispatch(); }
}
```

这是"AND门"逻辑的响应式实现：两个输入都到位，才触发输出。

---

## Buff来源的位置字典

```csharp
public Dictionary<BuffSource, Vector2> BuffSourcePosDic = new Dictionary<BuffSource, Vector2>();

public Dictionary<BuffSource, Vector2> BuffSourceOffsetDic = new Dictionary<BuffSource, Vector2>()
{
    { BuffSource.MyTactic,    new Vector2(0, 100) },   // 我方战术buff：向上偏移100
    { BuffSource.EnemyTactic, new Vector2(0, 100) },   // 敌方战术buff：向上偏移100
    { BuffSource.BoomPoint,   new Vector2(0, -100) },  // 爆点效果：向下偏移100（显示在角色脚下）
};
```

不同来源的 Buff 跳字有不同的显示位置偏移——战术 Buff 显示在角色头顶，爆点效果显示在角色脚下，从视觉上区分不同来源，帮助玩家理解战斗过程。

---

## 活跃跳字管理

```csharp
// 维护当前显示的跳字字典，Key为跳字ID，Value为跳字数据
public Dictionary<int, JumpTextData> ActiveJumpTextDictionary = new Dictionary<int, JumpTextData>();
```

用 Dictionary 而不是 List 管理活跃跳字，原因：
- 可以通过 ID 快速查找和删除特定跳字（O(1) vs O(n)）
- 跳字动画结束时需要精确删除对应项目，而不是遍历列表

---

## UI动画系统：YIUITweenComponent

除了跳字，游戏中还有大量UI出现/消失的过渡动画，通过 `YIUITweenComponent` 统一管理：

```csharp
public static async Task PlayOnShow(this YIUITweenComponent component)
{
    ResetAnim(component);
    await PlayOnShow(component.Tweens);
}

public static async Task PlayOnShow(IUIDOTween[] tweens)
{
    var taskList = ListPool<Task>.Get();
    foreach (var tween in tweens)
    {
        taskList.Add(tween.OnShow());  // 启动每个动画
    }
    await Task.WhenAll(taskList);     // 等待所有动画同时完成
    ListPool<Task>.Release(taskList);
}
```

`Task.WhenAll` 实现了所有动画并行播放并等待最慢的那个结束。`ListPool<Task>.Get()` 是对象池模式，避免频繁分配 `List<Task>` 造成 GC 压力。

---

## 架构总结

战斗跳字系统的架构体现了以下设计原则：

1. **数据驱动**：`JumpTextSettingDic` 配置驱动，策划可以独立调整每种跳字的视觉参数
2. **事件解耦**：战斗逻辑通过事件通知UI，UI层不引用战斗层
3. **防御性设计**：空值检查、无效状态检测贯穿始终
4. **响应式编程**：`BindableProperty` 和 `MultipleBindableProperty` 让数据变化自动驱动UI
5. **性能优化**：对象池（`ListPool`）、字典查找（`ActiveJumpTextDictionary`）

对于刚入行的同学：战斗 HUD 是最能体现"数据驱动"和"事件解耦"价值的模块之一。理解这部分代码，你对整个游戏架构的认知会有质的飞跃。
