---
title: 游戏FPS/TPS射击系统深度设计：射线检测、命中判定与弹道系统完全指南
published: 2026-05-04
description: 深入讲解FPS/TPS游戏射击系统的完整工程实现，涵盖精准射线检测、分层命中判定（头部/胸部/腿部）、弹道物理模拟（重力/风力/穿透）、后坐力系统、枪械状态机、客户端预测与服务端验证架构。
tags: [Unity, FPS, TPS, 射击游戏, 弹道系统, 游戏开发]
category: 游戏开发
draft: false
---

# 游戏FPS/TPS射击系统深度设计：射线检测、命中判定与弹道系统完全指南

## 引言

射击系统是FPS/TPS游戏的核心玩法支柱。《CS:GO》的精准射线检测、《Apex英雄》的弹道物理模拟、《PUBG》的子弹飞行时间——每一个细节都直接影响游戏体验。本文将完整讲解一套生产级别射击系统的工程实现，从基础射线检测到客户端-服务端同步架构。

## 系统架构总览

```
ShootingSystem
├── WeaponController        // 枪械控制器（开枪/换弹/上膛）
├── BallisticSystem         // 弹道系统（射线/物理子弹/穿透）
├── HitDetectionSystem      // 命中判定（骨骼碰撞/伤害区域）
├── RecoilSystem            // 后坐力系统（垂直/水平/视觉后坐力）
├── SpreadSystem            // 散布系统（移动/蹲伏/连发散布）
├── WeaponStateMachine      // 枪械状态机（待机/瞄准/开枪/换弹）
├── BulletTrailSystem       // 弹痕/弹道轨迹效果
└── NetworkShootingSync     // 网络同步（客户端预测+服务端校验）
```

## 一、枪械状态机

### 1.1 枪械配置数据

```csharp
[CreateAssetMenu(menuName = "Weapon/WeaponConfig")]
public class WeaponConfig : ScriptableObject
{
    [Header("基础参数")]
    public string WeaponName;
    public WeaponType Type; // Pistol, Rifle, Shotgun, Sniper
    public int MagazineSize;
    public int ReserveAmmo;
    
    [Header("射击参数")]
    public float FireRate;          // 每分钟子弹数（RPM）
    public float MuzzleVelocity;    // 枪口初速（m/s）
    public FireMode FireMode;       // Auto, SemiAuto, Burst
    public int BurstCount;          // 点射发数
    
    [Header("伤害参数")]
    public float BaseDamage;
    public float HeadMultiplier = 2.5f;
    public float ChestMultiplier = 1.0f;
    public float LimbMultiplier = 0.75f;
    public float FalloffStartDistance;  // 开始衰减距离
    public float FalloffEndDistance;    // 最大衰减距离
    public float MinDamagePercent = 0.3f;
    
    [Header("弹道参数")]
    public bool UsePhysicsBullet;   // 是否使用物理弹道（狙击枪）
    public float BulletDrop;        // 弹道下坠系数
    public float BulletSpread;      // 基础散布（角度）
    public AnimationCurve SpreadOverShots; // 连发散布曲线
    public float PenetrationPower;  // 穿透力（穿透薄墙）
    
    [Header("操控参数")]
    public float ReloadTime;
    public float AimDownSightTime;
    public float RecoilVertical;
    public float RecoilHorizontal;
    public AnimationCurve RecoilPattern; // 后坐力图案
    
    // 计算实际伤害（含距离衰减）
    public float CalculateDamage(float distance, HitZone zone)
    {
        float baseDmg = BaseDamage * GetZoneMultiplier(zone);
        
        if (distance <= FalloffStartDistance) return baseDmg;
        if (distance >= FalloffEndDistance) return baseDmg * MinDamagePercent;
        
        float t = (distance - FalloffStartDistance) / 
                  (FalloffEndDistance - FalloffStartDistance);
        float falloff = Mathf.Lerp(1f, MinDamagePercent, t);
        return baseDmg * falloff;
    }
    
    private float GetZoneMultiplier(HitZone zone) => zone switch
    {
        HitZone.Head => HeadMultiplier,
        HitZone.Chest => ChestMultiplier,
        HitZone.Limb => LimbMultiplier,
        _ => 1f
    };
    
    public float FireInterval => 60f / FireRate; // 秒
}

public enum FireMode { Auto, SemiAuto, Burst }
public enum HitZone { Head, Neck, Chest, Abdomen, Limb, Hand }
public enum WeaponType { Pistol, SMG, Rifle, Shotgun, Sniper, Melee }
```

### 1.2 枪械状态机

```csharp
public class WeaponStateMachine : MonoBehaviour
{
    public enum State { Idle, Aiming, Firing, Reloading, DrawingWeapon, Inspecting }
    
    [SerializeField] private WeaponConfig _config;
    [SerializeField] private Transform _muzzlePoint;
    [SerializeField] private Animator _weaponAnimator;
    
    private State _currentState = State.Idle;
    private int _currentAmmo;
    private int _reserveAmmo;
    private float _nextFireTime;
    private bool _triggerHeld;
    private int _shotsInBurst;
    private int _continuousShotCount; // 连发计数，用于散布计算
    
    // 组件引用
    private BallisticSystem _ballisticSystem;
    private RecoilSystem _recoilSystem;
    private SpreadSystem _spreadSystem;
    
    // 事件
    public event Action<int, int> OnAmmoChanged; // currentAmmo, reserve
    public event Action<WeaponConfig> OnWeaponFired;
    public event Action OnReloadStart;
    public event Action OnReloadEnd;
    
    private static readonly int AnimFire = Animator.StringToHash("Fire");
    private static readonly int AnimReload = Animator.StringToHash("Reload");
    private static readonly int AnimADS = Animator.StringToHash("ADS");
    
    private void Awake()
    {
        _ballisticSystem = GetComponent<BallisticSystem>();
        _recoilSystem = GetComponent<RecoilSystem>();
        _spreadSystem = GetComponent<SpreadSystem>();
        
        _currentAmmo = _config.MagazineSize;
        _reserveAmmo = _config.ReserveAmmo;
    }
    
    private void Update()
    {
        HandleInput();
        UpdateState();
    }
    
    private void HandleInput()
    {
        _triggerHeld = Input.GetButton("Fire1");
        bool triggerPressed = Input.GetButtonDown("Fire1");
        bool reloadPressed = Input.GetKeyDown(KeyCode.R);
        bool adsHeld = Input.GetButton("Fire2");
        
        if (reloadPressed && CanReload()) StartReload();
        
        // 切换ADS状态
        if (_currentState == State.Idle || _currentState == State.Aiming)
        {
            _currentState = adsHeld ? State.Aiming : State.Idle;
            _weaponAnimator?.SetBool(AnimADS, adsHeld);
        }
        
        // 射击输入
        bool shouldFire = _config.FireMode == FireMode.Auto ? _triggerHeld :
                          _config.FireMode == FireMode.SemiAuto ? triggerPressed :
                          triggerPressed; // Burst模式
        
        if (shouldFire && CanFire())
        {
            ExecuteFire();
        }
    }
    
    private bool CanFire()
    {
        return _currentState != State.Reloading
            && _currentAmmo > 0
            && Time.time >= _nextFireTime;
    }
    
    private bool CanReload()
    {
        return _currentState != State.Reloading
            && _reserveAmmo > 0
            && _currentAmmo < _config.MagazineSize;
    }
    
    private void ExecuteFire()
    {
        _currentState = State.Firing;
        _currentAmmo--;
        _nextFireTime = Time.time + _config.FireInterval;
        
        // 计算散布
        float spread = _spreadSystem.GetCurrentSpread(_config, _continuousShotCount);
        _continuousShotCount++;
        
        // 发射
        Vector3 fireDir = CalculateFireDirection(spread);
        _ballisticSystem.Fire(_config, _muzzlePoint.position, fireDir);
        
        // 后坐力
        _recoilSystem.ApplyRecoil(_config, _continuousShotCount);
        
        // 动画/特效
        _weaponAnimator?.SetTrigger(AnimFire);
        
        OnAmmoChanged?.Invoke(_currentAmmo, _reserveAmmo);
        OnWeaponFired?.Invoke(_config);
        
        // 自动换弹
        if (_currentAmmo <= 0) StartReload();
        
        // 点射计数
        if (_config.FireMode == FireMode.Burst)
        {
            _shotsInBurst++;
            if (_shotsInBurst >= _config.BurstCount) _shotsInBurst = 0;
        }
    }
    
    private Vector3 CalculateFireDirection(float spreadDegrees)
    {
        Vector3 baseDir = _muzzlePoint.forward;
        
        if (spreadDegrees <= 0) return baseDir;
        
        // 在圆锥内随机偏转
        float spreadRad = spreadDegrees * Mathf.Deg2Rad;
        float angle = UnityEngine.Random.Range(0f, spreadRad);
        float rotation = UnityEngine.Random.Range(0f, 360f) * Mathf.Deg2Rad;
        
        // 球坐标转笛卡尔
        Vector3 offset = new Vector3(
            Mathf.Sin(angle) * Mathf.Cos(rotation),
            Mathf.Sin(angle) * Mathf.Sin(rotation),
            Mathf.Cos(angle)
        );
        
        return _muzzlePoint.TransformDirection(offset);
    }
    
    private void StartReload()
    {
        if (_currentState == State.Reloading) return;
        _currentState = State.Reloading;
        _continuousShotCount = 0; // 重置散布
        
        _weaponAnimator?.SetTrigger(AnimReload);
        OnReloadStart?.Invoke();
        StartCoroutine(ReloadCoroutine());
    }
    
    private IEnumerator ReloadCoroutine()
    {
        yield return new WaitForSeconds(_config.ReloadTime);
        
        int ammoNeeded = _config.MagazineSize - _currentAmmo;
        int ammoToAdd = Mathf.Min(ammoNeeded, _reserveAmmo);
        _currentAmmo += ammoToAdd;
        _reserveAmmo -= ammoToAdd;
        
        _currentState = State.Idle;
        OnReloadEnd?.Invoke();
        OnAmmoChanged?.Invoke(_currentAmmo, _reserveAmmo);
    }
}
```

## 二、弹道系统

### 2.1 射线弹道（Hitscan）

```csharp
public class BallisticSystem : MonoBehaviour
{
    [Header("射线设置")]
    [SerializeField] private LayerMask _hitLayers;
    [SerializeField] private LayerMask _penetrableLayers; // 可穿透层（薄墙/木板）
    [SerializeField] private float _maxRange = 500f;
    
    [Header("特效")]
    [SerializeField] private GameObject _bulletTrailPrefab;
    [SerializeField] private BulletImpactDatabase _impactDatabase;
    
    private HitDetectionSystem _hitDetection;
    
    private void Awake()
    {
        _hitDetection = GetComponent<HitDetectionSystem>();
    }
    
    public void Fire(WeaponConfig config, Vector3 origin, Vector3 direction)
    {
        if (config.UsePhysicsBullet)
        {
            StartCoroutine(PhysicsBullet(config, origin, direction));
        }
        else
        {
            HitscanFire(config, origin, direction);
        }
    }
    
    // Hitscan：瞬时射线（适合步枪/手枪）
    private void HitscanFire(WeaponConfig config, Vector3 origin, Vector3 direction)
    {
        RaycastHit[] hits = Physics.RaycastAll(origin, direction, _maxRange, _hitLayers);
        
        // 按距离排序
        System.Array.Sort(hits, (a, b) => a.distance.CompareTo(b.distance));
        
        float remainingPenetration = config.PenetrationPower;
        Vector3 lastHitPoint = origin + direction * _maxRange;
        
        foreach (var hit in hits)
        {
            lastHitPoint = hit.point;
            
            // 命中判定
            var hitResult = _hitDetection.ProcessHit(hit, config, origin);
            
            if (hitResult.HitEntity != null)
            {
                // 对目标造成伤害
                ApplyDamage(hitResult, config);
                break; // 命中活体目标后停止穿透
            }
            
            // 穿透处理
            bool isPenetrable = ((1 << hit.collider.gameObject.layer) & _penetrableLayers) != 0;
            if (!isPenetrable || remainingPenetration <= 0)
            {
                // 生成弹痕特效
                SpawnImpactEffect(hit, false);
                break;
            }
            
            remainingPenetration -= GetPenetrationCost(hit.collider.sharedMaterial);
            SpawnImpactEffect(hit, true); // 穿透特效（不同于普通弹痕）
        }
        
        // 生成弹道轨迹
        SpawnBulletTrail(origin, lastHitPoint);
    }
    
    private float GetPenetrationCost(PhysicMaterial material)
    {
        // 根据物理材质判断穿透消耗
        if (material == null) return 10f;
        // 可扩展：通过材质名称查表
        return material.name.Contains("Wood") ? 15f : 
               material.name.Contains("Glass") ? 5f : 50f;
    }
    
    // 物理弹道：抛物线子弹（适合狙击枪）
    private IEnumerator PhysicsBullet(WeaponConfig config, Vector3 origin, Vector3 direction)
    {
        Vector3 position = origin;
        Vector3 velocity = direction * config.MuzzleVelocity;
        float elapsed = 0f;
        float maxTime = _maxRange / config.MuzzleVelocity;
        
        Vector3 prevPosition = position;
        
        while (elapsed < maxTime)
        {
            elapsed += Time.deltaTime;
            
            // 施加重力（弹道下坠）
            velocity += Vector3.down * config.BulletDrop * Time.deltaTime;
            
            // TODO: 可以加风力影响
            // velocity += WeatherEventBus.CurrentWindVector * windInfluence * Time.deltaTime;
            
            prevPosition = position;
            position += velocity * Time.deltaTime;
            
            // 检测子弹路径上的碰撞
            Vector3 dir = (position - prevPosition).normalized;
            float dist = Vector3.Distance(prevPosition, position);
            
            if (Physics.Raycast(prevPosition, dir, out RaycastHit hit, dist, _hitLayers))
            {
                var hitResult = _hitDetection.ProcessHit(hit, config, origin);
                if (hitResult.HitEntity != null)
                {
                    ApplyDamage(hitResult, config);
                }
                SpawnImpactEffect(hit, false);
                SpawnBulletTrail(origin, hit.point);
                yield break;
            }
            
            yield return null;
        }
        
        SpawnBulletTrail(origin, position);
    }
    
    private void ApplyDamage(HitResult hitResult, WeaponConfig config)
    {
        float distance = hitResult.HitDistance;
        float damage = config.CalculateDamage(distance, hitResult.HitZone);
        
        hitResult.HitEntity.TakeDamage(new DamageInfo
        {
            Damage = damage,
            Zone = hitResult.HitZone,
            HitPoint = hitResult.HitPoint,
            HitNormal = hitResult.HitNormal,
            Instigator = gameObject,
        });
    }
    
    private void SpawnBulletTrail(Vector3 from, Vector3 to)
    {
        if (_bulletTrailPrefab == null) return;
        var trail = Instantiate(_bulletTrailPrefab);
        var lr = trail.GetComponent<LineRenderer>();
        lr.SetPosition(0, from);
        lr.SetPosition(1, to);
        Destroy(trail, 0.1f);
    }
    
    private void SpawnImpactEffect(RaycastHit hit, bool isPenetration)
    {
        var impactFX = _impactDatabase?.GetEffect(hit.collider.sharedMaterial, isPenetration);
        if (impactFX == null) return;
        
        var fx = Instantiate(impactFX, hit.point, Quaternion.LookRotation(hit.normal));
        Destroy(fx, 3f);
    }
}
```

## 三、命中判定系统

### 3.1 骨骼碰撞盒配置

```csharp
// 挂在角色Hitbox根节点上
public class CharacterHitboxSystem : MonoBehaviour
{
    [Serializable]
    public class HitboxConfig
    {
        public string BoneName;
        public HitZone Zone;
        public Collider Collider;
    }
    
    [SerializeField] private List<HitboxConfig> _hitboxes;
    
    // 碰撞器到HitZone的快速查找表
    private Dictionary<Collider, HitZone> _colliderZoneMap;
    
    private void Awake()
    {
        _colliderZoneMap = new Dictionary<Collider, HitZone>();
        foreach (var hb in _hitboxes)
        {
            if (hb.Collider != null)
                _colliderZoneMap[hb.Collider] = hb.Zone;
        }
    }
    
    public bool TryGetHitZone(Collider col, out HitZone zone)
    {
        return _colliderZoneMap.TryGetValue(col, out zone);
    }
    
    // 自动根据骨骼创建Hitbox（编辑器工具）
    [ContextMenu("Auto Setup Hitboxes")]
    private void AutoSetupHitboxes()
    {
        var animator = GetComponentInChildren<Animator>();
        if (animator == null) return;
        
        var boneZoneMap = new Dictionary<HumanBodyBones, HitZone>
        {
            { HumanBodyBones.Head, HitZone.Head },
            { HumanBodyBones.Neck, HitZone.Neck },
            { HumanBodyBones.Chest, HitZone.Chest },
            { HumanBodyBones.Spine, HitZone.Abdomen },
            { HumanBodyBones.LeftUpperLeg, HitZone.Limb },
            { HumanBodyBones.RightUpperLeg, HitZone.Limb },
            { HumanBodyBones.LeftUpperArm, HitZone.Limb },
            { HumanBodyBones.RightUpperArm, HitZone.Limb },
        };
        
        _hitboxes = new List<HitboxConfig>();
        foreach (var kvp in boneZoneMap)
        {
            Transform bone = animator.GetBoneTransform(kvp.Key);
            if (bone == null) continue;
            
            // 检查是否已有碰撞器
            var col = bone.GetComponent<CapsuleCollider>();
            if (col == null) col = bone.gameObject.AddComponent<CapsuleCollider>();
            
            _hitboxes.Add(new HitboxConfig
            {
                BoneName = kvp.Key.ToString(),
                Zone = kvp.Value,
                Collider = col
            });
        }
    }
}
```

### 3.2 命中处理系统

```csharp
public class HitResult
{
    public IDamageable HitEntity;
    public HitZone HitZone;
    public Vector3 HitPoint;
    public Vector3 HitNormal;
    public float HitDistance;
    public bool IsCritical;
}

public class HitDetectionSystem : MonoBehaviour
{
    public HitResult ProcessHit(RaycastHit hit, WeaponConfig config, Vector3 shooterPos)
    {
        var result = new HitResult
        {
            HitPoint = hit.point,
            HitNormal = hit.normal,
            HitDistance = Vector3.Distance(shooterPos, hit.point),
        };
        
        // 查找角色Hitbox系统
        var hitboxSystem = hit.collider.GetComponentInParent<CharacterHitboxSystem>();
        if (hitboxSystem != null && hitboxSystem.TryGetHitZone(hit.collider, out HitZone zone))
        {
            result.HitZone = zone;
            result.IsCritical = zone == HitZone.Head;
        }
        else
        {
            result.HitZone = HitZone.Chest; // 默认身体命中
        }
        
        // 查找IDamageable接口
        result.HitEntity = hit.collider.GetComponentInParent<IDamageable>();
        
        return result;
    }
}

// 可受伤接口
public interface IDamageable
{
    void TakeDamage(DamageInfo info);
    float CurrentHealth { get; }
    bool IsAlive { get; }
}

public struct DamageInfo
{
    public float Damage;
    public HitZone Zone;
    public Vector3 HitPoint;
    public Vector3 HitNormal;
    public GameObject Instigator;
    public bool IsCritical => Zone == HitZone.Head;
}
```

## 四、后坐力系统

```csharp
public class RecoilSystem : MonoBehaviour
{
    [Header("视觉后坐力")]
    [SerializeField] private Transform _cameraHolder;
    [SerializeField] private float _recoilReturnSpeed = 5f;
    
    [Header("枪械后坐力动画")]
    [SerializeField] private Transform _weaponHolder;
    [SerializeField] private float _weaponKickAmount = 0.05f;
    
    private Vector3 _targetRotation;
    private Vector3 _currentRotation;
    private Vector3 _weaponTargetPos;
    private Vector3 _weaponBasePos;
    
    private void Awake()
    {
        _weaponBasePos = _weaponHolder != null ? _weaponHolder.localPosition : Vector3.zero;
    }
    
    private void Update()
    {
        // 平滑恢复
        _targetRotation = Vector3.Lerp(_targetRotation, Vector3.zero, 
                                        _recoilReturnSpeed * Time.deltaTime);
        _currentRotation = Vector3.Lerp(_currentRotation, _targetRotation, 
                                         _recoilReturnSpeed * 0.8f * Time.deltaTime);
        
        if (_cameraHolder != null)
            _cameraHolder.localRotation = Quaternion.Euler(_currentRotation);
        
        // 枪械后坐力恢复
        _weaponTargetPos = Vector3.Lerp(_weaponTargetPos, _weaponBasePos, 
                                         _recoilReturnSpeed * Time.deltaTime);
        if (_weaponHolder != null)
            _weaponHolder.localPosition = _weaponTargetPos;
    }
    
    public void ApplyRecoil(WeaponConfig config, int shotCount)
    {
        // 使用后坐力图案（第N发的X/Y偏移从curve读取）
        float patternT = Mathf.Clamp01((float)shotCount / 30f);
        float patternX = config.RecoilPattern.Evaluate(patternT);
        
        // 垂直后坐力（上跳）
        float verticalRecoil = config.RecoilVertical * UnityEngine.Random.Range(0.8f, 1.2f);
        // 水平后坐力（图案驱动 + 随机）
        float horizontalRecoil = config.RecoilHorizontal * patternX + 
                                  UnityEngine.Random.Range(-0.3f, 0.3f) * config.RecoilHorizontal;
        
        _targetRotation += new Vector3(-verticalRecoil, horizontalRecoil, 0f);
        
        // 限制最大后坐力积累
        _targetRotation.x = Mathf.Clamp(_targetRotation.x, -15f, 0f);
        _targetRotation.y = Mathf.Clamp(_targetRotation.y, -10f, 10f);
        
        // 枪械物理kickback
        if (_weaponHolder != null)
        {
            _weaponTargetPos = _weaponBasePos - Vector3.forward * _weaponKickAmount;
        }
    }
}
```

## 五、散布系统

```csharp
public class SpreadSystem : MonoBehaviour
{
    private CharacterController _cc;
    private float _velocityMagnitude;
    
    // ADS状态缓存
    private bool _isAiming;
    private bool _isCrouching;
    
    private void Update()
    {
        if (_cc != null) _velocityMagnitude = _cc.velocity.magnitude;
    }
    
    public float GetCurrentSpread(WeaponConfig config, int continuousShotCount)
    {
        float baseSpread = config.BulletSpread;
        
        // 连发散布（从曲线读取）
        float shotSpread = config.SpreadOverShots.Evaluate(
            Mathf.Clamp01((float)continuousShotCount / 20f)) * baseSpread;
        
        // 移动散布增加
        float moveSpread = Mathf.Clamp01(_velocityMagnitude / 5f) * baseSpread * 2f;
        
        // ADS减少散布
        float adsMultiplier = _isAiming ? 0.4f : 1f;
        
        // 蹲姿减少散布
        float crouchMultiplier = _isCrouching ? 0.7f : 1f;
        
        return (baseSpread + shotSpread + moveSpread) * adsMultiplier * crouchMultiplier;
    }
    
    public void SetAiming(bool aiming) => _isAiming = aiming;
    public void SetCrouching(bool crouching) => _isCrouching = crouching;
}
```

## 六、网络同步架构

```csharp
// 客户端预测 + 服务端验证的射击同步
public class NetworkShootingSync : MonoBehaviour
{
    // 客户端射击请求
    [Serializable]
    public struct ShootRequest
    {
        public uint SequenceId;
        public Vector3 Origin;
        public Vector3 Direction;
        public float Timestamp;
        public string WeaponId;
    }
    
    // 服务端命中验证结果
    [Serializable]
    public struct HitValidation
    {
        public uint RequestId;
        public bool IsValid;
        public float ActualDamage;
        public ulong HitTargetId;
        public HitZone Zone;
    }
    
    private uint _sequenceCounter;
    private Queue<ShootRequest> _pendingRequests = new Queue<ShootRequest>();
    
    // 客户端：发送射击请求
    public void SendShootRequest(Vector3 origin, Vector3 direction, string weaponId)
    {
        var request = new ShootRequest
        {
            SequenceId = ++_sequenceCounter,
            Origin = origin,
            Direction = direction,
            Timestamp = Time.time,
            WeaponId = weaponId,
        };
        
        _pendingRequests.Enqueue(request);
        
        // 客户端先行预测（立即显示命中特效，但等待服务端确认伤害）
        ApplyClientPrediction(request);
        
        // 发送到服务端
        SendToServer(request);
    }
    
    // 服务端：验证射击合法性（防止作弊）
    public HitValidation ValidateShootOnServer(ShootRequest request, PlayerState playerState)
    {
        // 1. 时间戳检查（防止时间重播攻击）
        float latency = Time.time - request.Timestamp;
        if (latency > 0.5f) // 超过500ms的请求拒绝
        {
            return new HitValidation { RequestId = request.SequenceId, IsValid = false };
        }
        
        // 2. 位置合理性检查（防止传送作弊）
        float positionError = Vector3.Distance(request.Origin, playerState.LastKnownPosition);
        if (positionError > playerState.MaxMovementPerTick * latency + 1f)
        {
            return new HitValidation { RequestId = request.SequenceId, IsValid = false };
        }
        
        // 3. 回溯历史状态进行命中检测（Lag Compensation）
        var hitResult = PerformLagCompensatedRaycast(request, latency);
        
        return new HitValidation
        {
            RequestId = request.SequenceId,
            IsValid = true,
            ActualDamage = hitResult?.Damage ?? 0f,
            HitTargetId = hitResult?.TargetId ?? 0,
            Zone = hitResult?.Zone ?? HitZone.Chest,
        };
    }
    
    // Lag Compensation：回溯目标历史位置
    private ServerHitResult PerformLagCompensatedRaycast(ShootRequest request, float rewindTime)
    {
        // 将所有玩家位置回溯到 rewindTime 前的状态
        var rewoundPositions = LagCompensationManager.Instance.GetHistoricalPositions(rewindTime);
        
        foreach (var (playerId, historicalHitboxes) in rewoundPositions)
        {
            // 临时移动碰撞器到历史位置
            historicalHitboxes.ApplyToColliders();
            
            if (Physics.Raycast(request.Origin, request.Direction, out RaycastHit hit, 500f))
            {
                var hitbox = hit.collider.GetComponent<CharacterHitboxSystem>();
                if (hitbox != null && hitbox.TryGetHitZone(hit.collider, out HitZone zone))
                {
                    historicalHitboxes.RestoreColliders();
                    return new ServerHitResult
                    {
                        TargetId = playerId,
                        Damage = 50f, // 实际计算
                        Zone = zone,
                    };
                }
            }
            
            historicalHitboxes.RestoreColliders();
        }
        
        return null;
    }
    
    private void ApplyClientPrediction(ShootRequest request) { /* 显示命中特效 */ }
    private void SendToServer(ShootRequest request) { /* 网络发送 */ }
}
```

## 七、弹痕与冲击特效数据库

```csharp
[CreateAssetMenu(menuName = "Weapon/BulletImpactDatabase")]
public class BulletImpactDatabase : ScriptableObject
{
    [Serializable]
    public class ImpactEntry
    {
        public string MaterialName;     // 物理材质名
        public GameObject NormalImpact; // 普通弹痕
        public GameObject PenetrationImpact; // 穿透弹痕
        public AudioClip ImpactSound;
    }
    
    [SerializeField] private ImpactEntry _defaultEntry;
    [SerializeField] private List<ImpactEntry> _entries;
    
    private Dictionary<string, ImpactEntry> _cache;
    
    private void OnEnable()
    {
        _cache = new Dictionary<string, ImpactEntry>();
        foreach (var e in _entries)
            _cache[e.MaterialName] = e;
    }
    
    public GameObject GetEffect(PhysicMaterial material, bool isPenetration)
    {
        string matName = material?.name ?? "Default";
        var entry = _cache.TryGetValue(matName, out var e) ? e : _defaultEntry;
        return isPenetration ? entry.PenetrationImpact : entry.NormalImpact;
    }
}
```

## 八、最佳实践总结

| 方面 | 建议 |
|------|------|
| **Hitscan vs 物理弹道** | 手枪/步枪用Hitscan（瞬时），狙击枪用物理弹道（有下坠/飞行时间），提升真实感 |
| **Hitbox精度** | 使用独立的Hitbox层（不与玩家移动碰撞器混用），Head/Chest/Limb分开，精确控制伤害区域 |
| **Lag Compensation** | 服务端必须实现位置回溯，否则高延迟玩家永远打不中人 |
| **后坐力图案** | 设计固定的后坐力图案（非纯随机），玩家通过练习可以掌握压枪手法，增加技巧深度 |
| **散布** | 连发散布上限要合理，避免后期子弹完全失控，影响游戏体验 |
| **弹痕** | 弹痕数量上限管理（超出时删除最旧的），避免内存泄漏 |
| **穿透平衡** | 穿透力平衡要谨慎，避免破坏地图掩体设计；可按材质分类细化 |
| **客户端预测** | 客户端预测命中特效（反馈即时），但伤害数字等待服务端确认，防止作弊 |

## 结语

射击系统的核心挑战在于**精准感、公平性与反作弊的平衡**。Hitscan保证了即时反馈，物理弹道增加了战术深度，Lag Compensation确保了公平性，而后坐力/散布系统则提供了技巧分层空间。构建时应优先保证命中感受，再逐步完善网络同步与反作弊机制。
