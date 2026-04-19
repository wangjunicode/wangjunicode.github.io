---
title: 特效系统设计与实现（EffectSystem + VFX Pool）
published: 2024-01-01
description: "特效系统设计与实现（EffectSystem + VFX Pool） - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 渲染管线
draft: false
encryptedKey: henhaoji123
---

# 特效系统设计与实现（EffectSystem + VFX Pool）

## 1. 系统概述

本项目特效系统（`EffectSystem`）统一管理战斗中所有粒子特效的生命周期，核心能力包括：

- **GameObject 对象池复用**：特效 Prefab 通过 `GameObjectPoolHelper` 复用，避免频繁实例化
- **挂点跟随**：特效可以挂在角色骨骼节点，跟随角色移动/旋转（带 LockMask 轴锁定）
- **Timeline 特效**：大招/过场使用 PlayableDirector + Timeline 驱动特效序列
- **后处理特效**：径向模糊（RadialBlur）、运动模糊（MotionBlur）、残影（Ghost）
- **生命周期管理**：基于帧数或时间的自动销毁

---

## 2. 核心数据结构

### 2.1 FxInfo（特效实例信息）

```csharp
// 每个运行中的特效实例对应一个 FxInfo
public class FxInfo
{
    public GameObject go;           // 特效 GameObject（从对象池取出）
    public Transform target;        // 跟随目标（角色挂点）
    public Unit unitFrom;           // 施法者 Unit（Unit 销毁后自动清理特效）
    
    public Vector3 pos;             // 相对偏移位置
    public Quaternion rot;          // 相对旋转
    public Vector3 scale;           // 缩放
    
    public LockMask lockMask;       // 轴锁定模式（位置锁/旋转锁/全锁/无锁）
    public Transform LookAtTarget;  // 朝向目标（自动 LookAt）
    
    public float expiredTime;       // 剩余寿命（秒，<=0 时销毁）
    public int playedFrames;        // 已播放帧数
    public int leaveFrameWhenUnLockAxis; // N 帧后解除轴锁定
    
    public bool isAllowInterrupt;   // 是否允许被打断（如被新技能打断）
    public bool isStartPlay;        // 是否已开始播放
    public bool removed;            // 标记删除（避免遍历中直接 RemoveAt）
    public bool isLightEffect;      // 是否为灯光特效（Update策略不同）
    
    // Timeline 驱动的特效
    public string timelineName;
    
    // 唯一 key（用于查重 / 强制单例特效）
    public string key;
    
    // 销毁回调
    public Action<FxInfo> onDestroy;
}
```

### 2.2 后处理特效任务结构

```csharp
// 位置：Hotfix/ModelView/GamePlay/Rendering/Effect/EffectTask.cs

// 径向模糊（大招释放时屏幕模糊向中心收缩效果）
public struct RadialBlurTask
{
    public bool radialBlurEnable;
    public float radialBlurIntensity;   // 模糊强度
    public Vector2 radialBlurCenter;    // 模糊中心点（屏幕坐标 0~1）
    public int radialBlurSampleCount;   // 采样数（越高越平滑，性能消耗越大）
    public bool radialBlurCharacterMaskEnable;  // 角色遮罩（避免人物被模糊）
    public Ease curve;     // DOTween 缓动曲线
    public float duration; // 持续时间
}

// 运动模糊（高速移动时的拖尾模糊）
public struct MotionBlurTask
{
    public bool motionBlurEnable;
    public int motionBlurQuality;    // 质量档（采样数）
    public float motionBlurIntensity; // 强度
    public float motionBlurClamp;    // 最大模糊角度限制
    public float duration;
}

// 残影（分身幻影效果）
public struct GhostTask
{
    public Color ghostColor;      // 残影颜色（通常为角色主题色半透明）
    public float initialAlpha;    // 初始透明度
    public float survivalTime;    // 每个残影存活时间
    public float intervalTime;    // 残影生成间隔
    public float duration;        // 总持续时间
}
```

---

## 3. EffectSystem 核心逻辑

### 3.1 初始化与播放

```csharp
// 位置：Hotfix/ModelView/GamePlay/Rendering/Effect/EffectSystem.cs
public class EffectSystem : Singleton<EffectSystem>
{
    // 运行中的特效列表
    private List<FxInfo> effectInstances = new();
    // 按 key 索引的特效字典（用于查找/替换单例特效）
    private Dictionary<string, HashSet<FxInfo>> effectInstDict = new();
    
    // 从对象池取出特效 Prefab
    private GameObject CreateFx(string path)
    {
        return GameObjectPoolHelper.GetObjectFromPool(path, autoCreate: 1);
    }
    
    // 归还到对象池（不销毁，可复用）
    private void DestroyFx(FxInfo fxInfo)
    {
        fxInfo.isStartPlay = false;
        fxInfo.onDestroy?.Invoke(fxInfo);
        
        if (fxInfo.go != null)
        {
            GameObjectPoolHelper.ReturnObjectToPool(fxInfo.go);
        }
        fxInfo.Clear();
    }
```

### 3.2 Update 每帧更新逻辑

```csharp
    // LateUpdate（在动画 Tick 之后执行，确保挂点位置准确）
    public void Update()
    {
        for (int i = effectInstances.Count - 1; i >= 0; i--)
        {
            var fxInfo = effectInstances[i];
            
            // 检查是否应该销毁
            bool shouldDestroy = fxInfo.removed          // 被标记删除
                || fxInfo.expiredTime <= 0               // 寿命耗尽
                || (fxInfo.unitFrom != null && fxInfo.unitFrom.IsDisposed);  // Unit 已销毁
            
            if (shouldDestroy)
            {
                DestroyFx(fxInfo);
                effectInstances.RemoveAt(i);
                // 从字典索引中移除
                if (!string.IsNullOrEmpty(fxInfo.key) && effectInstDict.ContainsKey(fxInfo.key))
                    effectInstDict[fxInfo.key].Remove(fxInfo);
                continue;
            }
            
            // Timeline 特效不走以下位置更新逻辑（由 PlayableDirector 控制）
            if (!string.IsNullOrEmpty(fxInfo.timelineName)) continue;
            
            // === 挂点跟随逻辑（按 LockMask 分类处理）===
            
            // 缩放跟随挂点（继承挂点的世界缩放）
            if (fxInfo.target != null && fxInfo.go != null)
            {
                var scale = fxInfo.scale;
                var lossyScale = fxInfo.target.lossyScale;
                fxInfo.go.transform.localScale = new Vector3(
                    scale.x * lossyScale.x, scale.y * lossyScale.y, lossyScale.z);
            }
            
            fxInfo.playedFrames++;
            
            // N 帧后解除轴锁定（特效离开挂点后自由飞行）
            bool isLocked = fxInfo.leaveFrameWhenUnLockAxis == 0 
                || fxInfo.playedFrames < fxInfo.leaveFrameWhenUnLockAxis;
            
            if (isLocked)
            {
                switch (fxInfo.lockMask)
                {
                    case LockMask.None:
                        // 完全跟随：位置 + 旋转都跟随挂点
                        if (fxInfo.target != null && fxInfo.go != null)
                        {
                            var targetRot = fxInfo.target.rotation;
                            var pos = fxInfo.target.position + targetRot * fxInfo.pos;
                            var rot = fxInfo.LookAtTarget == null 
                                ? targetRot * fxInfo.rot
                                : Quaternion.LookRotation(fxInfo.LookAtTarget.position - pos);
                            fxInfo.go.transform.SetPositionAndRotation(pos, rot);
                        }
                        break;
                    
                    case LockMask.Rotation:
                        // 只跟随位置，旋转锁定（如尘烟特效，位置跟随但不旋转）
                        if (fxInfo.target != null && fxInfo.go != null)
                        {
                            var pos = fxInfo.target.position + fxInfo.target.rotation * fxInfo.pos;
                            fxInfo.go.transform.position = pos;
                        }
                        break;
                    
                    case LockMask.Position:
                        // 只跟随旋转，位置锁定（如持续光环，位置固定但随角色旋转）
                        if (fxInfo.target != null && fxInfo.go != null)
                        {
                            var rot = fxInfo.LookAtTarget == null
                                ? fxInfo.target.rotation * fxInfo.rot
                                : Quaternion.LookRotation(fxInfo.LookAtTarget.position - fxInfo.go.transform.position);
                            fxInfo.go.transform.rotation = rot;
                        }
                        break;
                    
                    case LockMask.Both:
                        // 完全锁定：发射后不再跟随（如子弹、火球飞行）
                        break;
                }
            }
            
            // 减少寿命计时
            fxInfo.expiredTime -= Time.deltaTime;
        }
    }
```

---

## 4. 后处理特效驱动

```csharp
    // 触发径向模糊（大招前摇常用）
    public void PlayRadialBlur(RadialBlurTask task)
    {
        m_radialBlurTask = task;
        
        // 通过 DOTween 驱动模糊强度变化
        DOTween.To(
            () => 0f,
            v => {
                // 设置 URP 后处理参数
                var volume = PostProcessingManager.Instance.GetVolume("Battle");
                if (volume.profile.TryGet<RadialBlur>(out var rb))
                {
                    rb.intensity.value = v;
                    rb.center.value = task.radialBlurCenter;
                }
            },
            task.radialBlurIntensity,
            task.duration)
            .SetEase(task.curve)
            .OnComplete(() => {
                // 动画完成后关闭模糊
                DisableRadialBlur();
            });
    }
    
    // 触发残影效果（速移/位移技能常用）
    private Dictionary<GameObject, GhostTask> m_ghostTaskDict = new();
    
    public void PlayGhost(Unit unit, GhostTask task)
    {
        var go = unit.ViewEntity.GetComponent<Renderer>()?.gameObject;
        if (go == null) return;
        m_ghostTaskDict[go] = task;
    }
    
    // 强制打断指定 Unit 的所有可打断特效
    public void InterruptFx(Unit unit)
    {
        for (int i = effectInstances.Count - 1; i >= 0; i--)
        {
            if (effectInstances[i].unitFrom == unit && effectInstances[i].isAllowInterrupt)
            {
                effectInstances[i].removed = true;  // 标记删除，Update 中统一清理
            }
        }
    }
```

---

## 5. 常见问题与最佳实践

**Q: 特效 Prefab 对象池大小如何设定？**  
A: 根据战斗中同屏最大特效数预热（如同屏最多 8 个命中特效，则预热 10 个）。特效配置表 `TbEffect` 中可设置 `poolSize` 字段，GameObjectPoolHelper 读取后自动预热。

**Q: Timeline 特效如何与帧同步对齐？**  
A: Timeline 属于表现层，不参与帧同步逻辑。技能释放事件在逻辑层触发，通过 `EventSystem` 转发到表现层，由 `EffectSystem.PlayTimeline()` 播放。表现层可以自由使用 `Time.deltaTime`。

**Q: 特效在手机端帧率不稳时出现位置抖动怎么处理？**  
A: 使用 `LateUpdate` 而非 `Update` 更新特效位置（在动画系统更新完挂点位置后再更新特效位置）。对于高频更新的特效，可以开启 `interpolation` 使位置在物理帧之间插值。

**Q: 屏幕后处理特效（径向模糊等）如何做性能分级？**  
A: 在 `AdaptiveLodMgr` 中添加后处理特效的 LOD Feature（`LodFeaturePostProcessing`），低配设备自动跳过径向模糊等高开销效果，只保留基础粒子特效。
