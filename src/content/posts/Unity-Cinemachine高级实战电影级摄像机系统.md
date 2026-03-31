---
title: Unity Cinemachine高级实战：电影级摄像机系统
published: 2026-03-31
description: 深入掌握Unity Cinemachine的高级用法，包括Virtual Camera配置、Follow与LookAt组合、Brain切换与混合、Impulse震屏系统、Timeline集成过场动画、自定义摄像机扩展，以及从第三人称到MOBA俯视角到FPS的完整摄像机方案。
tags: [Unity, Cinemachine, 摄像机系统, 游戏开发, 后处理]
category: 渲染技术
draft: false
---

## 一、Cinemachine 核心架构

```
CinemachineBrain（主摄像机上）
    ├── VirtualCamera_ThirdPerson（跟随玩家）
    ├── VirtualCamera_Dialogue（对话特写）
    ├── VirtualCamera_Boss（Boss战专用）
    └── VirtualCamera_Cutscene（过场动画）
                    ↑
           优先级 + 混合曲线控制切换
```

---

## 二、第三人称摄像机完整配置

```csharp
using Cinemachine;
using UnityEngine;

/// <summary>
/// 第三人称摄像机控制器
/// </summary>
[RequireComponent(typeof(CinemachineVirtualCamera))]
public class ThirdPersonCamera : MonoBehaviour
{
    [Header("摄像机组件")]
    private CinemachineVirtualCamera virtualCam;
    private CinemachineOrbitalTransposer transposer;
    private CinemachineComposer composer;

    [Header("输入配置")]
    [SerializeField] private float horizontalSensitivity = 300f;
    [SerializeField] private float verticalSensitivity = 2f;
    [SerializeField] private float verticalMinAngle = -30f;
    [SerializeField] private float verticalMaxAngle = 70f;
    
    [Header("距离配置")]
    [SerializeField] private float defaultDistance = 5f;
    [SerializeField] private float minDistance = 1f;
    [SerializeField] private float maxDistance = 15f;
    [SerializeField] private float zoomSensitivity = 3f;
    [SerializeField] private float zoomDamping = 5f;
    
    [Header("视角偏移")]
    [SerializeField] private float shoulderOffset = 0.5f; // 右肩偏移（更真实）
    
    private float currentDistance;
    private float targetDistance;
    private float currentVerticalAngle;
    private float currentHorizontalAngle;

    void Awake()
    {
        virtualCam = GetComponent<CinemachineVirtualCamera>();
        transposer = virtualCam.GetCinemachineComponent<CinemachineOrbitalTransposer>();
        composer = virtualCam.GetCinemachineComponent<CinemachineComposer>();
        
        currentDistance = targetDistance = defaultDistance;
    }

    void Update()
    {
        HandleOrbitInput();
        HandleZoomInput();
    }

    void HandleOrbitInput()
    {
        if (Input.GetMouseButton(1)) // 右键旋转
        {
            float horizontal = Input.GetAxis("Mouse X") * horizontalSensitivity * Time.deltaTime;
            float vertical = Input.GetAxis("Mouse Y") * verticalSensitivity;
            
            currentHorizontalAngle += horizontal;
            currentVerticalAngle = Mathf.Clamp(
                currentVerticalAngle - vertical, 
                verticalMinAngle, 
                verticalMaxAngle);
            
            // 应用到 Transposer
            if (transposer != null)
                transposer.m_XAxis.Value = currentHorizontalAngle;
        }
    }

    void HandleZoomInput()
    {
        float scroll = Input.GetAxis("Mouse ScrollWheel");
        if (Mathf.Abs(scroll) > 0.01f)
        {
            targetDistance = Mathf.Clamp(
                targetDistance - scroll * zoomSensitivity, 
                minDistance, 
                maxDistance);
        }
        
        currentDistance = Mathf.Lerp(currentDistance, targetDistance, 
            zoomDamping * Time.deltaTime);
        
        if (transposer != null)
            transposer.m_FollowOffset = new Vector3(
                shoulderOffset, 
                transposer.m_FollowOffset.y, 
                -currentDistance);
    }
}
```

---

## 三、摄像机切换系统

```csharp
/// <summary>
/// 游戏摄像机切换管理器
/// </summary>
public class CameraManager : MonoBehaviour
{
    private static CameraManager instance;
    public static CameraManager Instance => instance;

    [Header("摄像机配置")]
    [SerializeField] private CinemachineVirtualCamera thirdPersonCam;
    [SerializeField] private CinemachineVirtualCamera dialogueCam;
    [SerializeField] private CinemachineVirtualCamera bossCam;
    [SerializeField] private CinemachineVirtualCamera deathCam;

    [Header("默认优先级")]
    [SerializeField] private int defaultPriority = 10;
    [SerializeField] private int activePriority = 20;

    private CinemachineVirtualCamera currentCamera;
    private CinemachineBrain brain;

    void Awake()
    {
        instance = this;
        brain = Camera.main.GetComponent<CinemachineBrain>();
        
        // 设置所有相机为低优先级
        SetAllToDefault();
        
        // 默认激活第三人称
        ActivateCamera(thirdPersonCam);
    }

    /// <summary>
    /// 切换到指定摄像机
    /// </summary>
    public void ActivateCamera(CinemachineVirtualCamera newCam, 
        float blendTime = 0.5f, CinemachineBlendDefinition.Style blendStyle = 
        CinemachineBlendDefinition.Style.EaseInOut)
    {
        if (newCam == null || newCam == currentCamera) return;
        
        // 配置混合
        if (brain != null)
        {
            brain.m_DefaultBlend = new CinemachineBlendDefinition(blendStyle, blendTime);
        }
        
        // 降低当前摄像机优先级
        if (currentCamera != null)
            currentCamera.Priority = defaultPriority;
        
        // 提升新摄像机优先级
        newCam.Priority = activePriority;
        currentCamera = newCam;
        
        Debug.Log($"[Camera] Switched to {newCam.name}");
    }

    /// <summary>
    /// Boss 战摄像机（关注 Boss 和玩家的中点）
    /// </summary>
    public void ActivateBossCamera(Transform boss, Transform player)
    {
        if (bossCam == null) return;
        
        // 动态设置 LookAt 目标（LookAt 两个目标的中点）
        var middlePoint = bossCam.GetComponent<BossCameraMiddlePoint>();
        if (middlePoint == null)
            middlePoint = bossCam.gameObject.AddComponent<BossCameraMiddlePoint>();
        
        middlePoint.SetTargets(boss, player);
        bossCam.LookAt = middlePoint.transform;
        
        ActivateCamera(bossCam, 1.0f, CinemachineBlendDefinition.Style.EaseIn);
    }

    public void ReturnToThirdPerson()
    {
        ActivateCamera(thirdPersonCam, 0.5f);
    }

    public void ActivateDeathCam()
    {
        ActivateCamera(deathCam, 0.3f, CinemachineBlendDefinition.Style.EaseIn);
    }

    void SetAllToDefault()
    {
        if (thirdPersonCam) thirdPersonCam.Priority = defaultPriority;
        if (dialogueCam) dialogueCam.Priority = defaultPriority;
        if (bossCam) bossCam.Priority = defaultPriority;
        if (deathCam) deathCam.Priority = defaultPriority;
    }
}

/// <summary>
/// Boss 战摄像机中点组件
/// </summary>
public class BossCameraMiddlePoint : MonoBehaviour
{
    private Transform targetA, targetB;
    [SerializeField] private float heightOffset = 1.5f;

    public void SetTargets(Transform a, Transform b)
    {
        targetA = a;
        targetB = b;
    }

    void Update()
    {
        if (targetA == null || targetB == null) return;
        transform.position = (targetA.position + targetB.position) / 2f 
            + Vector3.up * heightOffset;
    }
}
```

---

## 四、震屏系统（Cinemachine Impulse）

```csharp
/// <summary>
/// 摄像机震屏控制器
/// </summary>
public class CameraShakeController : MonoBehaviour
{
    private static CameraShakeController instance;
    public static CameraShakeController Instance => instance;

    [Header("震屏配置")]
    [SerializeField] private CinemachineImpulseSource impulseSource;
    
    // 预设震屏强度
    [SerializeField] private float lightShake = 0.3f;    // 轻击（普通攻击）
    [SerializeField] private float mediumShake = 0.7f;   // 中等（技能命中）
    [SerializeField] private float heavyShake = 1.5f;    // 强烈（Boss攻击）
    [SerializeField] private float explosionShake = 3f;  // 爆炸

    void Awake()
    {
        instance = this;
        if (impulseSource == null)
            impulseSource = GetComponent<CinemachineImpulseSource>();
    }

    public void ShakeLight()   => Shake(lightShake);
    public void ShakeMedium()  => Shake(mediumShake);
    public void ShakeHeavy()   => Shake(heavyShake);
    public void ShakeExplosion() => Shake(explosionShake);

    public void Shake(float intensity, Vector3? direction = null)
    {
        if (impulseSource == null) return;
        
        Vector3 velocity = direction ?? Random.insideUnitSphere;
        velocity = velocity.normalized * intensity;
        
        impulseSource.GenerateImpulseWithVelocity(velocity);
    }
    
    /// <summary>
    /// 带衰减的持续震屏（爆炸余震效果）
    /// </summary>
    public System.Collections.IEnumerator ShakeWithDecay(float initialIntensity, 
        float duration)
    {
        float elapsed = 0;
        while (elapsed < duration)
        {
            float intensity = Mathf.Lerp(initialIntensity, 0, elapsed / duration);
            Shake(intensity);
            elapsed += Time.deltaTime;
            yield return null;
        }
    }
}
```

---

## 五、Timeline 过场动画集成

```csharp
/// <summary>
/// 过场动画管理器（配合 Timeline 使用）
/// </summary>
public class CutsceneManager : MonoBehaviour
{
    [SerializeField] private UnityEngine.Playables.PlayableDirector[] cutscenes;
    [SerializeField] private CinemachineVirtualCamera cutsceneCam;
    
    private int currentCutsceneIndex = -1;

    /// <summary>
    /// 播放指定过场动画
    /// </summary>
    public void PlayCutscene(int index, System.Action onComplete = null)
    {
        if (index < 0 || index >= cutscenes.Length) return;
        
        // 切换到过场摄像机
        CameraManager.Instance?.ActivateCamera(cutsceneCam, 0.5f);
        
        // 禁用玩家控制
        GameManager.Instance?.SetPlayerInputEnabled(false);
        
        currentCutsceneIndex = index;
        var director = cutscenes[index];
        
        director.stopped += OnCutsceneStopped;
        director.Play();
        
        void OnCutsceneStopped(UnityEngine.Playables.PlayableDirector d)
        {
            d.stopped -= OnCutsceneStopped;
            
            // 恢复游戏
            CameraManager.Instance?.ReturnToThirdPerson();
            GameManager.Instance?.SetPlayerInputEnabled(true);
            
            onComplete?.Invoke();
        }
    }

    public void SkipCurrentCutscene()
    {
        if (currentCutsceneIndex < 0) return;
        var director = cutscenes[currentCutsceneIndex];
        director.time = director.duration; // 跳到末尾
        director.Evaluate();
        director.Stop();
    }
}
```

---

## 六、各游戏类型摄像机方案

| 游戏类型 | 推荐配置 |
|----------|----------|
| 第三人称RPG | OrbitalTransposer + Composer + 弹簧臂防穿墙 |
| MOBA俯视角 | FramingTransposer（跟随选中目标）+ 锁定视角 |
| FPS | 跟随头部骨骼位置，LookAt为射线终点 |
| 2D横板 | CinemachineConfiner2D 限制边界 + Damping |
| 赛车 | 追踪车辆 + 速度感（FOV随速度变大）|
| 策略游戏 | 自由旋转 + 缩放 + 边缘滚动 |

**关键原则：摄像机是玩家感受游戏的窗口，好的摄像机设计让玩家几乎感受不到它的存在。**
