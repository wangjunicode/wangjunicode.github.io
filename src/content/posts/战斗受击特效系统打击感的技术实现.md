---
title: 战斗受击特效系统：打击感的技术实现
published: 2026-03-31
description: 深入解析战斗受击特效的完整实现链，从攻击框碰撞点到骨骼挂点定位、从普通受击到爆发点/暴击的差异化特效与材质动画触发。
tags: [Unity, 战斗系统, 特效系统, 打击感]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗受击特效系统：打击感的技术实现

## 前言

玩家在游戏中挥剑砍中敌人，如果没有任何视觉和听觉反馈，操作感会极差。"打击感"是动作游戏的生命线，而它的技术本质是：**在正确的位置、正确的时机播放正确的特效和音效**。

本文通过分析 `HurtHitEvent_PlayEffect`，带你理解一次受击特效是如何精确定位并分级播放的。

---

## 一、受击特效的触发入口

```csharp
[Event(SceneType.Current)]
public class HurtHitEvent_PlayEffect : AEvent<Evt_HurtHitEffect>
{
    protected override void Run(Scene scene, Evt_HurtHitEffect args)
    {
        var defender          = args.Defender;   // 被攻击者
        var attacker          = args.Attacker;   // 攻击者
        var hurtEffectPath    = args.EffectRes;  // 特效资源路径
        var hurtEffectSoundId = args.EffectSoundId; // 音效 ID
    }
}
```

`Evt_HurtHitEffect` 由逻辑层（帧同步战斗系统）在伤害计算完成后发出。视图层只负责"播放特效"，不参与任何伤害逻辑——这是逻辑/视图分离的重要体现。

---

## 二、特效位置的两种计算模式

### 2.1 忽略攻击框模式

```csharp
if (subskillConfig.EffectIgnoreHitbox)
{
    // 受击者位置 + 命中偏移
    vfxPoint = args.Defender.Position + defenderHurtComp.AttackInfo.DefenderHitOffset;
    // 朝向攻击者方向
    vfxAngle = attacker.Rotation.eulerAngles.ToVector3();
}
```

当技能配置了 `EffectIgnoreHitbox = true` 时，特效不使用碰撞体的实际接触点，而是用"受击者中心 + 策划配置的偏移量"。

**使用场景：** 范围技能（AOE）——所有被命中单位都显示同一位置的特效，而不是各自的碰撞点。

### 2.2 基于攻击框的精确模式

```csharp
else
{
    vfxPoint = defenderHurtComp.AttackInfo.DefenderHitPos;  // 实际碰撞点
    vfxAngle = defenderHurtComp.AttackInfo.DefenderHitRot.eulerAngles.ToVector3();
}
```

使用碰撞检测阶段记录的 `DefenderHitPos`（受击接触点）和 `DefenderHitRot`（接触时的角度）。这保证了特效在视觉上"贴合"角色被击中的那个部位。

---

## 三、特效偏移的最终调整

```csharp
// 基础位置后，还要加上技能配置的额外偏移
vfxPoint += args.Attacker.Rotation * new TSVector(
    subskillConfig.EffectOffsetX,
    subskillConfig.EffectOffsetY,
    subskillConfig.EffectOffsetZ);

// 角度也有对应调整
vfxAngle.x += subskillConfig.EffectAngleX;
vfxAngle.y += subskillConfig.EffectAngleY;
vfxAngle.z += subskillConfig.EffectAngleZ;
```

策划可以在配置表中精细调整特效的位置和角度偏移。`args.Attacker.Rotation *` 使偏移量随攻击者朝向旋转，保证特效在攻击者正面时向上，从背后攻击时向上也正确。

---

## 四、格挡受击的特殊骨骼定位

```csharp
if (args.HurtResult == EHurtResult.ParryHurt)
{
    var pointID = PointID_VFX_Spine2;  // = 4（胸椎骨骼点）
    var pointComp = unit.GetComponent<VirtualSkeletonPointComponent>();
    var pointTrans = pointComp.EffectVirtualPoints.GetValueOrDefault(pointID);
    vfxPoint = pointTrans.position.ToTSVector();

    // 计算朝向攻击者方向的旋转
    var _dir = (args.Attacker.Position - args.Defender.Position).normalized;
    var worldDirection = _dir.ToVector3();
    var localDirection = Quaternion.Inverse(args.Defender.Rotation.ToQuaternion()) * worldDirection;
    vfxAngle = Quaternion.LookRotation(localDirection).eulerAngles;
}
```

**格挡特效比普通受击更特殊：**

1. **位置**：固定在胸椎骨骼点（`PointID_VFX_Spine2 = 4`），不是碰撞点——格挡动作的核心是身体中心，不是受击局部
2. **角度**：朝向攻击者，用 `Quaternion.Inverse` 把世界方向转换为受击者的本地空间，再通过 `LookRotation` 得到朝向角

这里的四元数计算是关键：`Quaternion.Inverse(受击者旋转) * 世界方向向量 = 受击者本地方向向量`，确保特效的朝向在受击者转身时依然正确。

---

## 五、三档受击效果：普通 / 爆发点 / 暴击

```csharp
// 先播放通用受击特效...

// 然后根据攻击结果选择材质动画
if (GetAttackResult(attacker) == EAttackResult.Focus && defenderHurtComp.CacheFocus)
{
    // 爆发点（Focus）：播放高光特效 + 材质动画
    Publish(scene, new Evt_ShowFx { FxInfo = new FxInfo { path = TbEffect.FocusEffect } });
    Publish(new Evt_PlayUnityTimeline { AssetPath = TbEffect.FocusMaterialEffect });
    defenderHurtComp.CacheFocus = false;
}
else if (GetAttackResult(attacker) == EAttackResult.Critical && defenderHurtComp.CacheCritical)
{
    // 暴击（Critical）：播放暴击特效 + 材质动画
    Publish(scene, new Evt_ShowFx { FxInfo = new FxInfo { path = TbEffect.CriticalEffect } });
    Publish(new Evt_PlayUnityTimeline { AssetPath = TbEffect.CriticalMaterialEffect });
    defenderHurtComp.CacheCritical = false;
}
else
{
    // 普通受击：只播放材质动画
    Publish(new Evt_PlayUnityTimeline { AssetPath = TbEffect.HurtMaterialEffect });
}
```

三档特效的层次感：

| 受击类型 | 特效层 | 材质层 | 视觉强度 |
|---------|--------|--------|---------|
| 普通受击 | 受击粒子 | 受击材质闪光 | ★★ |
| 爆发点 | 受击粒子 + 爆发光圈 | 爆发材质效果 | ★★★★ |
| 暴击 | 受击粒子 + 暴击星效 | 暴击材质效果 | ★★★★★ |

**`CacheFocus / CacheCritical` 的一次性消费设计：**

这两个 Cache 标志确保特殊特效只播放一次（即使因为某些原因同一帧触发了多次受击事件）。播放后立刻设为 `false`，避免重复播放。

---

## 六、受击特效的相机感知

```csharp
var cameraTrans = scene.GetComponent<CameraComponent>().GetMainCamera().transform;

EventSystem.Instance.Publish(scene, new Evt_ShowFx()
{
    FxInfo = new FxInfo()
    {
        target      = defenderTrans,
        path        = hurtEffectPath,
        pos         = vfxPoint.ToVector3(),
        rot         = vfxRotation,
        isHurtEffect = true,
        cameraTrans  = cameraTrans,    // 传入相机 Transform
        unitFrom    = args.Attacker
    }
});
```

把 `cameraTrans` 传入 `FxInfo`，让特效系统知道相机位置。有些特效（如数字飘字）需要始终朝向相机；有些特效根据与相机夹角决定是否显示（背面的特效可能不需要显示，节省渲染开销）。

---

## 七、飘字触发

```csharp
void PublishJumpText(Unit attacker, Unit defender, JumpTextType jumpTextType)
{
    if (jumpTextType != JumpTextType.None)
    {
        YIUIComponent.ClientScene
            .GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_HurtHitJumpText()
            {
                jumpTextType = jumpTextType,
                Defender = defender,
                Attacker = attacker
            });
    }
}
```

飘字（伤害数字、状态提示）是独立的系统，通过事件解耦。`JumpTextType` 可能包含：
- `Damage`：伤害数字
- `Critical`：暴击文字
- `Miss`：闪避文字
- `Block`：格挡文字

把飘字从受击特效中分离出来，让飘字系统可以独立控制显示逻辑（比如隐藏伤害数字的设置）而不影响特效的播放。

---

## 八、逻辑/视图的时序保证

这套事件链确保了逻辑先于视图：

```
逻辑帧：
  战斗计算 → 伤害结算 → 发布 Evt_HurtHitEffect

视图帧：
  HurtHitEvent_PlayEffect 响应 → 播放特效/音效/飘字
```

视图层不需要知道"是否命中"、"伤害值多少"——这些由逻辑层计算好后通过事件参数传来。视图只负责"展示"，永远不参与"判断"。

---

## 九、总结

打击感的技术本质可以拆解为：

| 维度 | 技术实现 |
|-----|---------|
| 位置精度 | 碰撞点 + 骨骼点 + 偏移量三层定位 |
| 角度准确 | 基于攻击者方向 + 四元数本地化 |
| 特效分级 | 普通/爆发点/暴击三档递增效果 |
| 相机感知 | 传入相机 Transform 实现朝向感知 |
| 材质动画 | Timeline 驱动 Shader，全身高光配合 |
| 音效联动 | 同帧触发音效，视听同步 |

这六个维度协同工作，创造出玩家感受到的"真实打击感"。缺少任何一个维度，体验都会明显下降。
