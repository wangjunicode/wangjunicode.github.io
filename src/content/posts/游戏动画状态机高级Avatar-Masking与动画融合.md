---
title: 游戏动画状态机高级：Avatar Masking与动画融合
published: 2026-03-31
description: 深度解析Unity Animator高级特性，包含Avatar Mask（上半身独立动画层/武器持握覆盖）、动画融合树（1D/2D混合树实现8方向移动）、IK约束（看向目标/脚部IK地形适应）、动画事件（挂帧事件驱动特效/音效/碰撞）、Animator Override Controller（子类复用动画树）、运行时切换动画控制器，以及Animator性能优化。
tags: [Unity, Animator, 动画状态机, Avatar Mask, 游戏开发]
category: 游戏开发
draft: false
---

## 一、Avatar Mask 多层动画

```csharp
using UnityEngine;

/// <summary>
/// 角色动画控制器（分层动画 + IK）
/// </summary>
public class CharacterAnimationController : MonoBehaviour
{
    [Header("Animator")]
    [SerializeField] private Animator animator;
    
    [Header("IK配置")]
    [SerializeField] private bool enableFootIK = true;
    [SerializeField] private float footIKWeight = 1f;
    [SerializeField] private float footRayLength = 0.5f;
    [SerializeField] private LayerMask groundMask;
    
    [Header("看向IK")]
    [SerializeField] private Transform lookTarget;
    [SerializeField] private float lookIKWeight = 0.8f;
    [SerializeField] private float lookIKSmooth = 5f;
    
    // Animator参数哈希（比字符串高效）
    private static readonly int SpeedX = Animator.StringToHash("SpeedX");
    private static readonly int SpeedY = Animator.StringToHash("SpeedY");
    private static readonly int IsGrounded = Animator.StringToHash("IsGrounded");
    private static readonly int IsAiming = Animator.StringToHash("IsAiming");
    private static readonly int AttackTrigger = Animator.StringToHash("Attack");

    // 当前IK状态
    private Vector3 leftFootPos, rightFootPos;
    private Quaternion leftFootRot, rightFootRot;
    private Vector3 currentLookPos;
    
    // 层索引
    private int baseLayerIndex = 0;
    private int upperBodyLayerIndex = 1;  // 上半身独立层（需要在Animator中设置）
    private int aimLayerIndex = 2;        // 瞄准层

    void Update()
    {
        UpdateLocomotionBlend();
    }

    /// <summary>
    /// 更新移动融合树（8方向移动）
    /// </summary>
    void UpdateLocomotionBlend()
    {
        Vector3 localVelocity = transform.InverseTransformDirection(
            GetComponent<Rigidbody>()?.velocity ?? Vector3.zero);
        
        float maxSpeed = 5f;
        animator.SetFloat(SpeedX, localVelocity.x / maxSpeed, 0.1f, Time.deltaTime);
        animator.SetFloat(SpeedY, localVelocity.z / maxSpeed, 0.1f, Time.deltaTime);
    }

    public void SetAiming(bool isAiming)
    {
        animator.SetBool(IsAiming, isAiming);
        
        // 调整上半身层权重（瞄准时上半身动画权重拉满）
        float targetWeight = isAiming ? 1f : 0f;
        animator.SetLayerWeight(aimLayerIndex, 
            Mathf.MoveTowards(
                animator.GetLayerWeight(aimLayerIndex), 
                targetWeight, Time.deltaTime * 5f));
    }

    public void TriggerAttack() => animator.SetTrigger(AttackTrigger);

    // ============ IK 系统 ============

    /// <summary>
    /// OnAnimatorIK - Unity IK回调（Animator设置Apply Root Motion时调用）
    /// </summary>
    void OnAnimatorIK(int layerIndex)
    {
        if (animator == null) return;
        
        // 脚部IK
        if (enableFootIK && layerIndex == baseLayerIndex)
        {
            UpdateFootIK();
        }
        
        // 看向IK（所有层都执行）
        UpdateLookAtIK();
    }

    void UpdateFootIK()
    {
        // 左脚
        animator.SetIKPositionWeight(AvatarIKGoal.LeftFoot, footIKWeight);
        animator.SetIKRotationWeight(AvatarIKGoal.LeftFoot, footIKWeight);
        
        // 右脚
        animator.SetIKPositionWeight(AvatarIKGoal.RightFoot, footIKWeight);
        animator.SetIKRotationWeight(AvatarIKGoal.RightFoot, footIKWeight);
        
        // 左脚射线检测
        Vector3 leftFootBonePos = animator.GetIKPosition(AvatarIKGoal.LeftFoot);
        if (Physics.Raycast(leftFootBonePos + Vector3.up, Vector3.down, 
            out var leftHit, 1f + footRayLength, groundMask))
        {
            animator.SetIKPosition(AvatarIKGoal.LeftFoot, leftHit.point);
            animator.SetIKRotation(AvatarIKGoal.LeftFoot, 
                Quaternion.LookRotation(transform.forward, leftHit.normal));
        }
        
        // 右脚射线检测
        Vector3 rightFootBonePos = animator.GetIKPosition(AvatarIKGoal.RightFoot);
        if (Physics.Raycast(rightFootBonePos + Vector3.up, Vector3.down,
            out var rightHit, 1f + footRayLength, groundMask))
        {
            animator.SetIKPosition(AvatarIKGoal.RightFoot, rightHit.point);
            animator.SetIKRotation(AvatarIKGoal.RightFoot,
                Quaternion.LookRotation(transform.forward, rightHit.normal));
        }
    }

    void UpdateLookAtIK()
    {
        if (lookTarget == null) return;
        
        // 平滑插值看向目标
        currentLookPos = Vector3.Lerp(currentLookPos, lookTarget.position, 
            lookIKSmooth * Time.deltaTime);
        
        animator.SetLookAtWeight(lookIKWeight, 0.3f, 0.6f, 1f, 0.5f);
        animator.SetLookAtPosition(currentLookPos);
    }

    public void SetLookTarget(Transform target) => lookTarget = target;
}
```

---

## 二、动画事件系统

```csharp
/// <summary>
/// 动画事件接收器（挂在角色上，接收Animator挂帧事件）
/// </summary>
public class AnimationEventReceiver : MonoBehaviour
{
    [Header("组件引用")]
    [SerializeField] private VFXAttachmentPoints vfxPoints;
    [SerializeField] private WeaponCollider weaponCollider;
    
    // ============ 动画事件回调（方法名要和Animator中一致）============
    
    /// <summary>
    /// 攻击命中检测开始（动画事件）
    /// </summary>
    void OnAttackHitStart()
    {
        weaponCollider?.EnableCollider();
        vfxPoints?.PlayVFX("VFX_SwingTrail", VFXAttachmentPoints.AttachPoint.WeaponTip, 
            attachToPoint: true);
    }

    /// <summary>
    /// 攻击命中检测结束
    /// </summary>
    void OnAttackHitEnd()
    {
        weaponCollider?.DisableCollider();
    }

    /// <summary>
    /// 脚步声（动画事件）
    /// </summary>
    void OnFootstep()
    {
        // 根据地面材质播放不同音效
        string sfxKey = GetFootstepSFX();
        AudioManager.Instance?.PlaySFX3D(null, transform.position);
    }

    /// <summary>
    /// 技能释放时刻（动画事件，此刻才实际创建子弹/范围）
    /// </summary>
    void OnSkillCast()
    {
        // 通知技能系统实际执行效果
        GetComponent<SkillCaster>()?.ExecutePendingSkill();
    }

    string GetFootstepSFX()
    {
        // 检测脚下地面类型
        if (Physics.Raycast(transform.position + Vector3.up * 0.1f, Vector3.down, 
            out var hit, 0.3f))
        {
            string tag = hit.collider.tag;
            if (tag == "Stone") return "footstep_stone";
            if (tag == "Wood")  return "footstep_wood";
            if (tag == "Grass") return "footstep_grass";
        }
        return "footstep_default";
    }
}

/// <summary>
/// 武器碰撞体（攻击检测）
/// </summary>
public class WeaponCollider : MonoBehaviour
{
    [SerializeField] private Collider weaponCol;
    [SerializeField] private int damage = 20;
    [SerializeField] private LayerMask targetMask;
    
    private HashSet<GameObject> hitTargets = new HashSet<GameObject>(); // 防止同次攻击重复伤害

    public void EnableCollider()
    {
        hitTargets.Clear();
        weaponCol.enabled = true;
    }

    public void DisableCollider()
    {
        weaponCol.enabled = false;
    }

    void OnTriggerEnter(Collider other)
    {
        if (!weaponCol.enabled) return;
        if (!IsInLayerMask(other.gameObject.layer, targetMask)) return;
        if (hitTargets.Contains(other.gameObject)) return; // 防止重复伤害
        
        hitTargets.Add(other.gameObject);
        
        var health = other.GetComponent<HealthComponent>();
        health?.TakeDamage(damage, DamageType.Physical, transform.root.gameObject);
    }

    bool IsInLayerMask(int layer, LayerMask mask) => ((1 << layer) & mask) != 0;
}
```

---

## 三、Animator Override Controller

```csharp
/// <summary>
/// 角色换装系统（不同角色复用同一动画树，覆盖具体动画Clip）
/// </summary>
public class CharacterAnimationOverride : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private AnimatorOverrideController overrideController;
    
    [System.Serializable]
    public class AnimationOverrideSet
    {
        public string SetName;
        public AnimationClipOverride[] Overrides;
    }
    
    [System.Serializable]
    public class AnimationClipOverride
    {
        public string OriginalClipName; // Animator树中原始Clip名
        public AnimationClip NewClip;   // 替换的新Clip
    }

    [SerializeField] private AnimationOverrideSet[] overrideSets;

    void Start()
    {
        // 克隆并应用Override Controller
        if (overrideController != null)
        {
            var runtimeOverride = new AnimatorOverrideController(overrideController);
            animator.runtimeAnimatorController = runtimeOverride;
        }
    }

    /// <summary>
    /// 切换动画集（换武器/换皮肤时调用）
    /// </summary>
    public void SwitchAnimationSet(string setName)
    {
        var set = System.Array.Find(overrideSets, s => s.SetName == setName);
        if (set == null) return;
        
        var overrides = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        
        foreach (var clip in set.Overrides)
        {
            // 找到原始Clip
            var originalClip = GetOriginalClip(clip.OriginalClipName);
            if (originalClip != null)
                overrides.Add(new KeyValuePair<AnimationClip, AnimationClip>(
                    originalClip, clip.NewClip));
        }
        
        var controller = animator.runtimeAnimatorController as AnimatorOverrideController;
        controller?.ApplyOverrides(overrides);
    }

    AnimationClip GetOriginalClip(string name)
    {
        var controller = animator.runtimeAnimatorController as AnimatorOverrideController;
        if (controller == null) return null;
        
        var clips = new List<KeyValuePair<AnimationClip, AnimationClip>>();
        controller.GetOverrides(clips);
        
        foreach (var pair in clips)
            if (pair.Key?.name == name)
                return pair.Key;
        
        return null;
    }
}
```

---

## 四、动画系统设计要点

| 要点 | 方案 |
|------|------|
| 参数哈希 | Animator.StringToHash缓存，比直接传字符串快 |
| 平滑阻尼 | SetFloat第3/4参数设置过渡阻尼，防止抖动 |
| IK权重 | 根据地形/状态动态调整IK权重（如跳跃时IK=0）|
| 动画事件 | 比代码计时更精确，与动画强耦合 |
| Override Controller | 同树复用，只换Clip，适合换武器/换皮 |
| 多层动画 | 上半身层+下半身层分离，实现边跑边射 |
