---
title: Unity动画系统进阶：AnimatorController与动画混合树
published: 2026-03-31
description: 深度解析Unity Animator的高级用法，包含动画状态机设计（状态/转换条件）、1D/2D混合树（运动混合）、动画层（叠加层/覆盖层）、Avatar遮罩（上下半身分离动画）、运行时动画覆盖（AnimatorOverrideController）、AnimationRigging程序化IK，以及动画事件系统。
tags: [Unity, Animator, 动画系统, 混合树, 游戏开发]
category: 游戏开发
draft: false
---

## 一、混合树设计

```csharp
using UnityEngine;

public class CharacterAnimationController : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private float speedDampTime = 0.1f;
    
    // Animator参数哈希（比字符串快）
    private static readonly int SpeedHash = Animator.StringToHash("Speed");
    private static readonly int DirectionXHash = Animator.StringToHash("DirectionX");
    private static readonly int DirectionYHash = Animator.StringToHash("DirectionY");
    private static readonly int IsGroundedHash = Animator.StringToHash("IsGrounded");
    private static readonly int AttackTrigger = Animator.StringToHash("Attack");
    private static readonly int HurtTrigger = Animator.StringToHash("Hurt");
    private static readonly int DieHash = Animator.StringToHash("Die");

    public void UpdateMovement(Vector2 moveDir, float speed, bool grounded)
    {
        // 使用 damping 平滑过渡（避免动画突变）
        animator.SetFloat(SpeedHash, speed, speedDampTime, Time.deltaTime);
        animator.SetFloat(DirectionXHash, moveDir.x, speedDampTime, Time.deltaTime);
        animator.SetFloat(DirectionYHash, moveDir.y, speedDampTime, Time.deltaTime);
        animator.SetBool(IsGroundedHash, grounded);
    }

    public void TriggerAttack() => animator.SetTrigger(AttackTrigger);
    public void TriggerHurt()   => animator.SetTrigger(HurtTrigger);
    public void TriggerDie()    => animator.SetBool(DieHash, true);

    /// <summary>
    /// 运行时替换动画（武器切换）
    /// </summary>
    public void OverrideAnimation(AnimationClip originalClip, AnimationClip newClip)
    {
        var overrideController = new AnimatorOverrideController(animator.runtimeAnimatorController);
        overrideController[originalClip] = newClip;
        animator.runtimeAnimatorController = overrideController;
    }

    /// <summary>
    /// 动画事件回调（在AnimationClip中添加Event，填写函数名）
    /// </summary>
    void OnAttackHit()
    {
        // 动画到打击帧时触发伤害判定
        Debug.Log("[Animation] 攻击打击帧！");
    }
    
    void OnFootstep()
    {
        // 脚步声
        AudioManager.Instance?.PlaySFX(null);
    }
}
```

---

## 二、动画层与Avatar遮罩

```
动画层配置示例（上下半身分离）：

Layer 0 - Base（权重1，全身）
├── Idle, Walk, Run, Jump 等移动动画
└── 影响全身骨骼

Layer 1 - UpperBody（权重1，叠加模式）
├── Avatar Mask：仅上半身（脊柱以上）
├── Attack_Light, Attack_Heavy, Block, Aim
└── 不影响腿部运动

Layer 2 - Face（权重1）
├── Avatar Mask：仅头部/面部骨骼
└── 表情动画
```

---

## 三、程序化IK

```csharp
/// <summary>
/// 脚部IK（确保脚踩在地面上）
/// </summary>
public class FootIKController : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private LayerMask groundMask;
    [SerializeField] [Range(0,1)] float ikWeight = 1f;

    void OnAnimatorIK(int layerIndex)
    {
        if (animator == null) return;
        
        SolveFootIK(AvatarIKGoal.LeftFoot);
        SolveFootIK(AvatarIKGoal.RightFoot);
    }

    void SolveFootIK(AvatarIKGoal foot)
    {
        animator.SetIKPositionWeight(foot, ikWeight);
        animator.SetIKRotationWeight(foot, ikWeight);
        
        Vector3 footPos = animator.GetIKPosition(foot);
        
        if (Physics.Raycast(footPos + Vector3.up, Vector3.down, 
            out RaycastHit hit, 2f, groundMask))
        {
            Vector3 targetPos = hit.point;
            targetPos.y += 0.1f; // 脚踝偏移
            animator.SetIKPosition(foot, targetPos);
            
            Quaternion footRot = Quaternion.FromToRotation(Vector3.up, hit.normal) 
                * transform.rotation;
            animator.SetIKRotation(foot, footRot);
        }
    }
}
```

---

## 四、性能优化

| 优化项 | 方案 |
|--------|------|
| 参数哈希 | Animator.StringToHash 替代字符串 |
| Culling Mode | 不可见时 Animate Physics 或 Cull |
| 减少状态机复杂度 | 超复杂用代码控制 |
| LOD动画 | 远处低频率更新Animator |
| Generic vs Humanoid | 非人形用Generic（性能更好）|
