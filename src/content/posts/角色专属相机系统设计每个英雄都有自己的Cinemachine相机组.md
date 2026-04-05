---
title: 角色专属相机系统设计——每个英雄都有自己的Cinemachine相机组
published: 2026-03-31
description: 深度解析游戏中角色与相机的绑定机制，从CinemachineTargetGroup到CharacterCameraComponent的完整实现
tags: [Unity, 相机系统, Cinemachine]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 角色专属相机系统设计——每个英雄都有自己的Cinemachine相机组

在战斗游戏中，不同的英雄角色往往有截然不同的技能表现——有的技能需要俯视全场，有的需要追踪快速移动的投射物，有的需要在角色发动大招时切换到特殊镜头。

如果让所有角色共用一组相机参数，要么无法照顾每个角色的最佳表现，要么相机逻辑里充斥大量`if (character == "英雄A")`的特殊分支。

VGame项目采用了**"每个角色有自己的虚拟相机组"**的设计，本文详细剖析这套机制。

## 一、设计理念：相机跟着角色走

```
场景相机管理器（CameraComponent）
    └── 虚拟相机注册表
          ├── 角色A的虚拟相机组（CharacterCameraComponent）
          │     ├── 普通镜头VCam
          │     ├── 技能镜头VCam
          │     └── 大招镜头VCam
          ├── 角色B的虚拟相机组
          └── 角色C的虚拟相机组
```

**核心思路**：场景里存在一个物理相机（`Camera`），由`CameraComponent`管理。每个角色实体附带一个`CharacterCameraComponent`，持有该角色专属的一组`CinemachineVirtualCamera`。

当某个角色的技能被激活时，角色系统通知`CameraComponent`激活该角色的某个虚拟相机；Cinemachine会自动计算真实相机的过渡动画，从当前位置平滑移动到新的虚拟相机位置。

## 二、CharacterCameraComponent的生命周期

```csharp
[EntitySystem]
private static void Awake(this CharacterCameraComponent self)
{
    var owner = self.GetParent<Unit>();
    
    // 从配置表读取该角色的相机预制体路径
    var characterConf = CfgManager.tables.TbCharacter.GetCharacterById(owner.ConfigId);
    
    // 加载（可能从缓存）相机预制体
    var vCamsPrefab = AssetCache.GetCachedAssetAutoLoad<GameObject>(characterConf.Camera);
    
    // 实例化相机组游戏对象
    self.VCamsRoot = Object.Instantiate(vCamsPrefab);
    
    // 关键：DontDestroyOnLoad！相机不随场景销毁
    Object.DontDestroyOnLoad(self.VCamsRoot);
    
    // 确保相机根节点在场景顶层（不受角色Transform影响）
    var vcanTrans = self.VCamsRoot.transform;
    if (vcanTrans.parent != null) vcanTrans.parent = null;
    
    // 初始化虚拟相机字典
    self.InitVCam(self.VCamsRoot);
}
```

几个关键设计决策：

**1. DontDestroyOnLoad**：相机预制体不随场景切换销毁。为什么？因为战斗场景切换（比如PVP不同地图）时，如果相机对象被销毁再重建，会有短暂的黑屏。保持相机对象存活可以让切换更流畅。

**2. 相机根节点与角色分离**：`vcanTrans.parent = null`确保相机游戏对象不是角色的子节点。这样相机的世界位置不会随角色移动，而是由Cinemachine的跟随逻辑控制——这是使用Cinemachine的标准做法。

**3. 配置驱动**：`characterConf.Camera`是配置表字段，策划可以为每个角色指定不同的相机预制体，不需要改代码。

## 三、CinemachineTargetGroup的LateUpdate维护

```csharp
[EntitySystem]
private static void LateUpdate(this CharacterCameraComponent self)
{
    var targetGroups = self.VCamsRoot
        .GetComponentsInChildren<CinemachineTargetGroup>();
    
    foreach (var targetGroup in targetGroups)
    {
        if (targetGroup.m_Targets[0].target != null 
            && targetGroup.m_Targets[1].target != null)
        {
            // 让相机朝向：从目标0看向目标1的方向
            Vector3 forward = targetGroup.m_Targets[1].target.position 
                            - targetGroup.m_Targets[0].target.position;
            targetGroup.transform.rotation = Quaternion.LookRotation(forward);
        }
    }
}
```

`CinemachineTargetGroup`是Cinemachine中用来"让相机同时关注多个目标"的组件，常用于格斗游戏（让相机同时看到我方角色和敌方角色）。

这里的逻辑是：每帧LateUpdate时，用两个目标点（通常是我方角色和敌方角色）计算朝向，并更新TargetGroup的旋转。为什么是LateUpdate？因为角色位置在Update里更新，LateUpdate确保读到的是本帧最新位置。

**`FreashTargetGroup`方法**：

```csharp
public static void FreashTargetGroup(this CharacterCameraComponent self)
{
    var targetGroups = self.VCamsRoot.GetComponentsInChildren<CinemachineTargetGroup>();
    foreach (var targetGroup in targetGroups)
    {
        targetGroup.DoUpdate(); // 强制Cinemachine重新计算包围盒
        // ... 同样的方向计算逻辑
    }
}
```

`DoUpdate()`是手动触发Cinemachine更新，用于需要立即获得最新相机状态的场合（比如战斗开始时，要立刻定位相机，不等下一帧）。

## 四、SetLookAtTarget：动态切换相机焦点

```csharp
public static void SetLookAtTarget(
    this CharacterCameraComponent self, 
    GameObject target1, 
    GameObject target2)
{            
    var targetGroups = self.VCamsRoot.GetComponentsInChildren<CinemachineTargetGroup>();
    foreach (var targetGroup in targetGroups)
    {
        // 修改TargetGroup的两个目标点
        // target1通常是我方角色，target2是敌方或技能目标
    }
}
```

战斗中场景会动态变化：技能对准了一个新目标、锁定的敌人切换了……`SetLookAtTarget`允许运行时动态替换相机的关注目标，Cinemachine会自动处理平滑过渡。

## 五、Destroy时的清理逻辑

```csharp
[EntitySystem]
private static void Destroy(this CharacterCameraComponent self)
{
    try
    {
        var owner = self.GetParent<Unit>();
        var cameraComp = self.CurrentScene().GetComponent<CameraComponent>();
        if (cameraComp != null)
        {
            // 从全局相机管理器中注销该角色的相机
            cameraComp.UnRegisterCharacterCamera(owner.Id);
        }
    }
    catch (Exception e)
    {
        Debug.LogException(e);
    }
    
    if (self.VCamsRoot != null)
    {
        // 直接销毁（不是标记销毁），因为已经DontDestroyOnLoad了
        GameObject.DestroyImmediate(self.VCamsRoot);   
    }   
}
```

注意用`DestroyImmediate`而非`Destroy`。因为`VCamsRoot`是`DontDestroyOnLoad`对象，在某些销毁顺序下`Destroy`（延迟一帧销毁）可能来不及执行，改用`DestroyImmediate`确保立刻清理。

同时要从`CameraComponent`的注册表中注销，防止全局相机管理器持有已销毁角色的相机引用。

## 六、事件驱动的相机切换

`CameraComponentSystem`中大量使用了事件监听来驱动相机切换：

```csharp
// 监听"摄像机Brain更新"事件
[Event(SceneType.Current)]
public class EffectUpdateEvent : AEvent<Evt_CameraBrainUpdate>
{
    protected override void Run(Scene scene, Evt_CameraBrainUpdate argv)
    {
        var cameraSys = scene.GetComponent<CameraComponent>();
        cameraSys?.UpdateCameraBrain();
    }
}

// 监听"设置相机目标"事件
[Event(SceneType.Current)]
public class SetCameraTargetEvent : AEvent<Evt_SetCameraTarget>
{
    protected override void Run(Scene scene, Evt_SetCameraTarget argv)
    {
        var cameraSys = scene.GetComponent<CameraComponent>();
        cameraSys?.SetCameraTarget();
        if (argv.bResetToNormal)
            cameraSys?.InitCamState();
    }
}

// 监听PVP开场镜头切换
[Event(SceneType.Current)]
public class SwitchPVPOpeningCameraEvent : AEvent<Evt_SwitchPVPOpeningCamera>
{
    protected override void Run(Scene scene, Evt_SwitchPVPOpeningCamera evt)
    {
        var cameraSys = scene.GetComponent<CameraComponent>();
        if (evt.Enable)
            cameraSys?.SwitchToPvpOpeningMode(); // PVP开场特效镜头
        else
            cameraSys?.SwitchToDefaultMode();    // 恢复默认战斗镜头
    }
}
```

每种相机切换需求都有独立的事件类型（`Evt_SetCameraTarget`、`Evt_SwitchPVPOpeningCamera`等）。技能系统、剧情系统、UI系统只需发布事件，不需要直接持有`CameraComponent`的引用。

## 七、"初始化相机状态"与场景重置

```csharp
[Event(SceneType.Current)]
public class InitCameraEvent : AEvent<Evt_InitCameraState>
{
    protected override void Run(Scene scene, Evt_InitCameraState argv)
    {
        // 初始化相机状态（位置、焦距等恢复默认）
        scene.GetComponent<CameraComponent>()?.InitCamState();
        
        // 同时重置地形位置（相机初始化和地形位置是联动的）
        var terrainViewComp = scene.GetComponent<TerrainViewComponent>();
        if (terrainViewComp.TerrainRoot != null)
        {
            terrainViewComp.TerrainRoot.transform.position = terrainViewComp.InitPos;
            StaticInstanceManager.instance?.ResetAllInstancePos();
        }
    }
}
```

这里揭示了一个有意思的依赖：初始化相机时，同时要重置地形位置（`TerrainRoot.transform.position = InitPos`）。这是因为项目为了实现"战斗场景以战斗中心点为原点"，会在战斗开始时移动地形。相机初始化时需要同步将地形移回初始位置。

## 八、实战经验

**问题：角色切换时相机抖动**

症状：切换到新角色时，相机会在当前位置和新角色相机目标位置之间快速跳变。

原因：旧角色的虚拟相机还在优先级列表里，新角色的虚拟相机激活时，Cinemachine需要从"旧相机位置"过渡，过渡时间太短就会产生抖动。

解决：在`UnRegisterCharacterCamera`时，先禁用该角色的所有虚拟相机，再注销，给Cinemachine一帧时间更新混合优先级。

**问题：Editor预览相机和游戏内相机状态不同步**

在Editor里调整了虚拟相机参数但没有应用到预制体，运行时相机行为与预期不符。

规范化：所有虚拟相机参数必须保存到角色相机预制体，不允许在代码中覆盖（只有位置/朝向逻辑在代码里）。

## 九、架构总结

| 组件 | 职责 |
|------|------|
| `CameraComponent` | 全局相机管理，注册表维护，事件响应 |
| `CharacterCameraComponent` | 单个角色的虚拟相机组，生命周期同步 |
| `CinemachineTargetGroup` | 多目标跟随，方向计算 |
| 配置表 | 角色与相机预制体的映射 |

这套设计实现了"数据驱动+组件化"：策划通过配置表控制每个角色的相机行为，程序员只维护通用的相机切换逻辑，不需要为每个角色写特殊case。
