---
title: 游戏AI感知系统：视觉、听觉与触觉感知完全指南
published: 2026-03-31
description: 深入解析游戏AI感知系统的完整设计，涵盖视野锥体检测（FOV + 遮挡判断）、听觉范围感知、嗅觉足迹追踪、记忆系统（最后目击位置）、感知事件优先级，以及与行为树/状态机的整合方案。
tags: [Unity, AI系统, 感知系统, 视野检测, 游戏AI]
category: 游戏AI
draft: false
encryptedKey: henhaoji123
---

## 一、感知系统架构

```
AI 感知系统
├── 视觉感知（Vision）
│   ├── 锥形视野范围
│   ├── 遮挡射线检测
│   └── 光照强度影响
├── 听觉感知（Hearing）
│   ├── 球形范围内声音检测
│   └── 声音类型过滤
├── 触觉感知（Touch）
│   ├── 碰撞触发
│   └── 接近警报
└── 记忆系统（Memory）
    ├── 最后目击位置
    └── 感知刺激历史
```

---

## 二、视野感知系统

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 感知信息（AI 关注的目标）
/// </summary>
public class PerceptionStimulus
{
    public string SourceId;            // 来源 ID
    public GameObject Source;         // 来源 GameObject
    public StimulusType Type;         // 刺激类型
    public float Intensity;           // 感知强度（0-1）
    public Vector3 Location;          // 位置
    public float DetectedTime;        // 探测到的时间
    
    public float Age => Time.time - DetectedTime;
}

public enum StimulusType { Sight, Sound, Touch, Smell, Custom }

/// <summary>
/// AI 视觉感知组件
/// </summary>
public class AISightSensor : MonoBehaviour
{
    [Header("视野参数")]
    [SerializeField] private float sightRange = 15f;              // 视野范围
    [SerializeField, Range(0, 180)] private float fovAngle = 90f; // 视野角度（半角）
    [SerializeField] private float peripheralAngle = 150f;        // 外围视野（更小感知强度）
    [SerializeField] private LayerMask sightBlockMask;            // 遮挡层（墙壁等）
    [SerializeField] private LayerMask targetMask;                 // 可感知目标层
    
    [Header("高度感知")]
    [SerializeField] private Vector3 eyeOffset = new Vector3(0, 1.6f, 0); // 眼部偏移
    
    [Header("更新频率")]
    [SerializeField] private float updateInterval = 0.1f;          // 感知更新间隔
    
    // 感知到的目标列表
    private List<PerceptionStimulus> perceivedTargets = new List<PerceptionStimulus>();
    private float updateTimer;
    
    // 事件
    public event Action<PerceptionStimulus> OnTargetDetected;
    public event Action<string> OnTargetLost;

    public IReadOnlyList<PerceptionStimulus> PerceivedTargets => perceivedTargets;
    
    private Vector3 EyePosition => transform.position + eyeOffset;

    void Update()
    {
        updateTimer += Time.deltaTime;
        if (updateTimer >= updateInterval)
        {
            updateTimer = 0;
            UpdateSightSensor();
        }
    }

    void UpdateSightSensor()
    {
        // 获取视野范围内所有潜在目标
        var colliders = Physics.OverlapSphere(EyePosition, sightRange, targetMask);
        
        var currentDetected = new HashSet<string>();
        
        foreach (var col in colliders)
        {
            var target = col.gameObject;
            if (target == gameObject) continue;
            
            string targetId = target.GetInstanceID().ToString();
            
            float intensity = CalculateSightIntensity(target);
            if (intensity <= 0) continue;
            
            currentDetected.Add(targetId);
            
            // 更新或添加感知记录
            var existing = perceivedTargets.Find(p => p.SourceId == targetId);
            if (existing == null)
            {
                var stimulus = new PerceptionStimulus
                {
                    SourceId = targetId,
                    Source = target,
                    Type = StimulusType.Sight,
                    Intensity = intensity,
                    Location = target.transform.position,
                    DetectedTime = Time.time
                };
                perceivedTargets.Add(stimulus);
                OnTargetDetected?.Invoke(stimulus);
            }
            else
            {
                existing.Intensity = intensity;
                existing.Location = target.transform.position;
            }
        }
        
        // 移除不再感知到的目标
        for (int i = perceivedTargets.Count - 1; i >= 0; i--)
        {
            var p = perceivedTargets[i];
            if (p.Type != StimulusType.Sight) continue;
            
            if (!currentDetected.Contains(p.SourceId))
            {
                perceivedTargets.RemoveAt(i);
                OnTargetLost?.Invoke(p.SourceId);
            }
        }
    }

    float CalculateSightIntensity(GameObject target)
    {
        Vector3 dirToTarget = target.transform.position - EyePosition;
        float distance = dirToTarget.magnitude;
        
        if (distance > sightRange) return 0f;
        
        float angleToTarget = Vector3.Angle(transform.forward, dirToTarget.normalized);
        
        float intensityFromAngle;
        if (angleToTarget <= fovAngle / 2f)
        {
            // 主视野：完整感知强度
            intensityFromAngle = 1f;
        }
        else if (angleToTarget <= peripheralAngle / 2f)
        {
            // 外围视野：部分感知
            float t = (angleToTarget - fovAngle / 2f) / (peripheralAngle / 2f - fovAngle / 2f);
            intensityFromAngle = Mathf.Lerp(1f, 0.3f, t);
        }
        else
        {
            return 0f; // 不在视野内
        }
        
        // 遮挡检测（射线投射）
        Vector3 checkDir = (target.transform.position + Vector3.up * 0.8f - EyePosition).normalized;
        
        if (Physics.Raycast(EyePosition, checkDir, distance - 0.1f, sightBlockMask))
        {
            return 0f; // 被遮挡
        }
        
        // 距离衰减
        float intensityFromDistance = 1f - (distance / sightRange);
        
        return intensityFromAngle * intensityFromDistance;
    }

    // 在 Scene 视图中显示感知范围（调试用）
    void OnDrawGizmosSelected()
    {
        Vector3 eyePos = transform.position + eyeOffset;
        
        // 主视野（绿色）
        Gizmos.color = new Color(0, 1, 0, 0.3f);
        DrawFOVCone(eyePos, fovAngle, sightRange);
        
        // 外围视野（黄色）
        Gizmos.color = new Color(1, 1, 0, 0.15f);
        DrawFOVCone(eyePos, peripheralAngle, sightRange * 0.7f);
        
        // 感知到的目标（红线）
        Gizmos.color = Color.red;
        foreach (var p in perceivedTargets)
        {
            if (p.Source != null)
                Gizmos.DrawLine(eyePos, p.Source.transform.position);
        }
    }

    void DrawFOVCone(Vector3 origin, float angle, float range)
    {
        int segments = 20;
        float halfAngle = angle / 2f;
        
        for (int i = 0; i <= segments; i++)
        {
            float t = (float)i / segments;
            float currentAngle = Mathf.Lerp(-halfAngle, halfAngle, t);
            Vector3 dir = Quaternion.Euler(0, currentAngle, 0) * transform.forward;
            
            if (i > 0)
            {
                float prevAngle = Mathf.Lerp(-halfAngle, halfAngle, (float)(i - 1) / segments);
                Vector3 prevDir = Quaternion.Euler(0, prevAngle, 0) * transform.forward;
                Gizmos.DrawLine(origin + prevDir * range, origin + dir * range);
            }
            Gizmos.DrawLine(origin, origin + dir * range);
        }
    }
}
```

---

## 三、听觉感知系统

```csharp
/// <summary>
/// AI 听觉感知组件
/// </summary>
public class AIHearingSensor : MonoBehaviour
{
    [Header("听觉参数")]
    [SerializeField] private float baseHearingRange = 10f;
    [SerializeField] private LayerMask soundBlockMask;
    
    private List<PerceptionStimulus> heardSounds = new List<PerceptionStimulus>();

    /// <summary>
    /// 处理来自 SoundEmitter 的声音刺激
    /// </summary>
    public void OnSoundReceived(SoundStimulus sound)
    {
        float distance = Vector3.Distance(transform.position, sound.Origin);
        float effectiveRange = baseHearingRange * sound.Loudness;
        
        if (distance > effectiveRange) return;
        
        // 检测声音是否被遮挡（穿过墙壁会衰减）
        float obstruction = CalculateSoundObstruction(sound.Origin);
        float hearingIntensity = (1f - distance / effectiveRange) * (1f - obstruction);
        
        if (hearingIntensity <= 0.1f) return;
        
        var stimulus = new PerceptionStimulus
        {
            SourceId = sound.SourceId,
            Source = sound.Source,
            Type = StimulusType.Sound,
            Intensity = hearingIntensity,
            Location = sound.Origin,
            DetectedTime = Time.time
        };
        
        heardSounds.Add(stimulus);
        
        // 通知感知系统
        GetComponent<AIPerceptionSystem>()?.ReceiveStimulus(stimulus);
    }

    float CalculateSoundObstruction(Vector3 origin)
    {
        // 射线检测声音遮挡（每面墙衰减 0.3）
        var hits = Physics.RaycastAll(transform.position, 
            (origin - transform.position).normalized, 
            Vector3.Distance(transform.position, origin), 
            soundBlockMask);
        
        float obstruction = Mathf.Min(hits.Length * 0.3f, 0.9f);
        return obstruction;
    }
}

/// <summary>
/// 声音发射器（挂在能产生声音的对象上）
/// </summary>
public class SoundEmitter : MonoBehaviour
{
    [SerializeField] private float emitRadius = 15f;
    [SerializeField] private LayerMask aiLayer;
    
    public void EmitSound(float loudness = 1f, SoundType soundType = SoundType.Footstep)
    {
        var sound = new SoundStimulus
        {
            SourceId = gameObject.GetInstanceID().ToString(),
            Source = gameObject,
            Origin = transform.position,
            Loudness = loudness,
            SoundType = soundType
        };
        
        // 广播给范围内的 AI
        var colliders = Physics.OverlapSphere(transform.position, emitRadius, aiLayer);
        foreach (var col in colliders)
        {
            col.GetComponent<AIHearingSensor>()?.OnSoundReceived(sound);
        }
    }
}

public class SoundStimulus
{
    public string SourceId;
    public GameObject Source;
    public Vector3 Origin;
    public float Loudness;         // 响度（0-1+，超过1会传得更远）
    public SoundType SoundType;
}

public enum SoundType { Footstep, Gunshot, Explosion, Voice, Ambient }
```

---

## 四、记忆系统

```csharp
/// <summary>
/// AI 记忆系统（记录最后目击位置等历史信息）
/// </summary>
public class AIMemorySystem : MonoBehaviour
{
    [SerializeField] private float memoryDuration = 15f;  // 记忆持续时间（秒）
    [SerializeField] private int maxMemoryCount = 10;     // 最大记忆条数

    private List<MemoryRecord> memories = new List<MemoryRecord>();

    public class MemoryRecord
    {
        public string TargetId;
        public StimulusType StimulusType;
        public Vector3 LastKnownPosition;
        public float ConfidenceLevel;   // 置信度（衰减）
        public float LastUpdateTime;
        
        public float Age => Time.time - LastUpdateTime;
        public bool IsExpired(float duration) => Age > duration;
    }

    void Update()
    {
        // 清除过期记忆
        memories.RemoveAll(m => m.IsExpired(memoryDuration));
        
        // 置信度随时间衰减
        foreach (var memory in memories)
        {
            memory.ConfidenceLevel = Mathf.Max(0, 
                1f - memory.Age / memoryDuration);
        }
    }

    public void UpdateMemory(PerceptionStimulus stimulus)
    {
        var existing = memories.Find(m => m.TargetId == stimulus.SourceId);
        
        if (existing != null)
        {
            existing.LastKnownPosition = stimulus.Location;
            existing.ConfidenceLevel = 1f;
            existing.LastUpdateTime = Time.time;
        }
        else
        {
            if (memories.Count >= maxMemoryCount)
            {
                // 移除最旧的记忆
                memories.Sort((a, b) => a.LastUpdateTime.CompareTo(b.LastUpdateTime));
                memories.RemoveAt(0);
            }
            
            memories.Add(new MemoryRecord
            {
                TargetId = stimulus.SourceId,
                StimulusType = stimulus.Type,
                LastKnownPosition = stimulus.Location,
                ConfidenceLevel = 1f,
                LastUpdateTime = Time.time
            });
        }
    }

    public MemoryRecord GetBestTarget()
    {
        MemoryRecord best = null;
        float bestScore = -1;
        
        foreach (var m in memories)
        {
            float score = m.ConfidenceLevel;
            // 优先视觉记忆（比声音记忆更可靠）
            if (m.StimulusType == StimulusType.Sight) score *= 1.5f;
            
            if (score > bestScore)
            {
                bestScore = score;
                best = m;
            }
        }
        
        return best;
    }

    public Vector3? GetLastKnownPosition(string targetId)
    {
        var memory = memories.Find(m => m.TargetId == targetId);
        return memory?.LastKnownPosition;
    }
}
```

---

## 五、感知优先级系统

| 感知类型 | 响应时间 | 置信度 | 追踪精度 |
|----------|----------|--------|----------|
| 直接视觉（主视野）| 立即 | 高 | 精确 |
| 外围视觉 | 0.5s延迟 | 中 | 模糊 |
| 近距离枪声 | 立即 | 高 | 方向精确 |
| 远距离脚步 | 0.2s | 低 | 大致方向 |
| 触碰/碰撞 | 立即 | 最高 | 精确 |
| 记忆（目标消失）| N/A | 衰减 | 衰减 |

**设计建议：**
1. 感知系统与 AI 决策系统解耦（感知产生刺激事件，决策响应事件）
2. 异步更新（不要每帧检测，0.1-0.2s间隔足够）
3. 视野调试 Gizmos 在开发期必须可见
4. 记忆系统让 AI 在失去目标后有合理行为（搜查最后位置）
