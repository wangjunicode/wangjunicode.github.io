---
title: 战斗摄像机系统设计（Cinemachine + 自定义追踪）
published: 2024-01-01
description: "战斗摄像机系统设计（Cinemachine + 自定义追踪） - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 渲染管线
draft: false
encryptedKey: henhaoji123
---

# 战斗摄像机系统设计（Cinemachine + 自定义追踪）

## 1. 系统概述

战斗摄像机系统基于 Unity **Cinemachine** 虚拟摄像机框架构建，通过 `CameraComponent`（ET ECS 组件）统一管理摄像机的切换、跟踪、效果和录制功能。

**核心特性：**
- **虚拟摄像机切换**：通过 Cinemachine Brain 管理多个 VirtualCamera，平滑切换（Blend）
- **智能防遮挡**：根据角色与摄像机的角度自动调整视角，避免角色被建筑遮挡
- **动态阻尼（Dutch）**：角色切换时加入摄像机横滚效果，增强战斗临场感
- **战斗录制**：按帧记录摄像机位置/旋转/FOV，用于战斗回放和过场动画制作

---

## 2. 数据结构

### 2.1 帧录制数据结构

```csharp
// 位置：Hotfix/ModelView/GamePlay/Camera/CameraComponent.cs
// 战斗录制：每帧记录摄像机 + 所有角色的状态
[System.Serializable]
public struct FrameCharacterRecord
{
    public long id;          // Entity ID
    public int configID;     // 角色配置 ID
    public bool bActive;     // 是否激活
    public Vector3 pos;      // 世界位置
    public Quaternion rot;   // 旋转
    public string clip;      // 当前播放的动画 Clip 名称
    public float time;       // 动画时间
}

[System.Serializable]
public struct FrameRecord
{
    public float deltaTime;                          // 帧时长
    public Vector3 cameraPos;                        // 摄像机位置
    public Quaternion cameraRot;                     // 摄像机旋转
    public float cameraFov;                          // 视野角（FOV）
    public List<FrameCharacterRecord> characterData; // 所有角色数据
}

// 整场战斗录制结果
[System.Serializable]
public struct ViewRecord
{
    public List<FrameRecord> data;  // 所有帧数据列表
}
```

### 2.2 摄像机切换配置

```csharp
public struct CameraSwitchInfo
{
    public Unit owner;                      // 触发切换的 Unit
    public SwitchVCamDetailConf switchConf; // 切换配置（从 TbCamera 读取）
}
```

---

## 3. CameraComponent 核心字段

```csharp
public class CameraComponent : Entity, IAwake, IDestroy, ILateUpdate, IUpdate
{
    public Camera MainCamera;  // 场景主摄像机
    
    // Cinemachine 虚拟摄像机容器
    public GameObject VCamsRoot;          // 战斗中用的 VCam 容器
    public GameObject PreBattleVCamsRoot; // 战斗前（准备阶段）VCam 容器
    
    // VCam 组件缓存（避免每次 GetComponent）
    public Dictionary<CinemachineVirtualCamera, 
        Dictionary<Type, CinemachineComponentBase>> CameraCompCache;
    
    public ECameraTemplateType curCamPos;  // 当前摄像机模板类型（枚举）
    
    // 动态阻尼（Dutch Roll）—— 角色切换时的横滚效果
    public float dutchDeltaStep = 5;    // 每帧横滚增量
    public float dutchDeltaMax = 30;    // 最大横滚角度
    public float dutchDelta = 0;        // 当前横滚值
    public int lastDutchTeamIdx = -1;   // 上一次切换的队伍索引
    
    // 防遮挡参数
    public float angleThreshold = 30;       // 开始调整的角度阈值
    public float safeZone = 4.0f / 6.0f;   // 安全区比例（屏幕4/6以内不调整）
    public float commonLevel1Limit = 70;    // 一级调整极限角度
    public float commonLevel2Limit = 30;    // 二级调整极限角度
    
    // 延迟切换（某些切换需要等当前动画播完）
    public Unit delayTaskOwner = null;
    public int delayTime = 0;
    public SwitchVCamDetailConf delayChangeInfo;
    
    // 目标队伍列表（PVP中两队的 TeamEntity）
    public List<TeamEntity> targetTeam = new List<TeamEntity>();
}
```

---

## 4. 摄像机切换逻辑

```csharp
// CameraComponentSystem.cs - 摄像机切换系统
[FriendOf(typeof(CameraComponent))]
public static class CameraComponentSystem
{
    // 根据配置 ID 切换虚拟摄像机
    public static void SwitchVCam(this CameraComponent self, 
        int configId, Unit owner = null)
    {
        var conf = CfgManager.tables.TbCamera.GetOrDefault(configId);
        if (conf == null) return;
        
        // 查找对应的 VirtualCamera GameObject
        var vcam = self.FindVCam(conf.VCamName);
        if (vcam == null)
        {
            Log.Warning($"[Camera] 找不到VCam: {conf.VCamName}");
            return;
        }
        
        // 提高目标 VCam 优先级（Cinemachine 自动切换到最高优先级的 VCam）
        self.SetVCamPriority(vcam, 100);
        
        // 延迟切换处理（等当前动画完成后再切换）
        if (conf.DelayFrames > 0 && owner != null)
        {
            self.delayTaskOwner = owner;
            self.delayTime = conf.DelayFrames;
            self.delayChangeInfo = conf.SwitchDetail;
        }
    }
    
    // 每帧 LateUpdate 处理
    [EntitySystem]
    public static void LateUpdate(this CameraComponent self)
    {
        // 1. 处理延迟切换
        if (self.delayTime > 0)
        {
            self.delayTime--;
            if (self.delayTime == 0)
            {
                self.ExecuteSwitchVCam(self.delayChangeInfo, self.delayTaskOwner);
            }
        }
        
        // 2. 更新 Dutch Roll（摄像机横滚）
        self.UpdateDutch();
        
        // 3. 防遮挡调整
        self.UpdateAngleAdjust();
    }
}
```

---

## 5. 智能防遮挡算法

```csharp
    // 检测摄像机是否被建筑遮挡角色，自动调整角度
    private static void UpdateAngleAdjust(this CameraComponent self)
    {
        if (!self.changeWeight) return;
        
        // 获取当前摄像机到主角的向量
        var mainUnit = GetMainUnit(self);
        if (mainUnit == null) return;
        
        Vector3 camPos = self.MainCamera.transform.position;
        Vector3 unitPos = mainUnit.ViewEntity.transform.position;
        Vector3 toUnit = unitPos - camPos;
        
        float angle = Vector3.Angle(self.MainCamera.transform.forward, toUnit);
        
        // 根据角度大小分级处理
        if (angle > self.commonLevel1Limit)
        {
            // 超过一级限制：角色已严重出框，需要快速调整
            self.AdjustCameraAngle(mainUnit, AdjustLevel.High);
        }
        else if (angle > self.commonLevel2Limit)
        {
            // 超过二级限制：角色略微出框，平滑调整
            self.AdjustCameraAngle(mainUnit, AdjustLevel.Medium);
        }
    }
```

---

## 6. 与帧同步的关系

摄像机属于**表现层**，不参与帧同步逻辑：

```
帧同步层（定点数 FP）         表现层（float）
    Unit.Position（FP）  →→→  CameraComponent.FollowTarget（float）
    FSM状态变化          →→→  摄像机切换事件
    技能释放             →→→  摄像机 FOV 放大/震屏效果
```

摄像机永远跟随表现层的 `float` 坐标（不直接用定点数），避免量化误差导致摄像机抖动。

---

## 7. 常见问题与最佳实践

**Q: Cinemachine 和自定义摄像机代码如何共存？**  
A: Cinemachine Brain 负责 VCam 混合，`CameraComponent` 负责逻辑控制（何时切哪个 VCam、阻尼参数等）。不直接修改 MainCamera.transform，全部通过 VCam 优先级切换。

**Q: 摄像机切换时出现跳切（无过渡）怎么解决？**  
A: 检查 Cinemachine Brain 的 Default Blend 时间设置，确保不为 0。也可以在 `SwitchVCamDetailConf` 中为特定切换配置专属混合曲线（`CinemachineBlendDefinition`）。

**Q: 录制数据文件太大怎么办？**  
A: `FrameRecord` 中包含所有角色的位置，对于长战斗会很大。可以：①只记录关键帧（位移变化超过阈值才记录）；②压缩存储（`Brotli` 压缩）；③只录制摄像机数据，角色通过重放输入重建。
