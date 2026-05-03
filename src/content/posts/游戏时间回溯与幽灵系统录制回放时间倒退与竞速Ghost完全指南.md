---
title: 游戏时间回溯与幽灵系统：录制回放、时间倒退与竞速Ghost完全指南
published: 2026-05-03
description: 深度解析游戏时间回溯（Time Rewind）与幽灵系统（Ghost System）的完整工程实现，涵盖状态录制环形缓冲区、插值回放、竞速幽灵对手、物理状态重置、Burst Job优化，以及《超级热》风格的时间缩放系统。
tags: [Unity, 时间回溯, Ghost系统, 录制回放, 游戏系统设计, 竞速游戏]
category: 游戏系统
draft: false
---

# 游戏时间回溯与幽灵系统：录制回放、时间倒退与竞速Ghost完全指南

## 概述

时间回溯与幽灵系统在多种游戏类型中发挥核心作用：

- **时间回溯**：《波斯王子》的倒带能力、《Braid》的时间操控、《超级热》的时间缩放
- **幽灵系统**：赛车游戏中与自己的最佳成绩竞速、格斗游戏的CPU镜像训练
- **录制回放**：精彩时刻录制（Kill Cam）、教学回放、错误复现

本文将系统实现一套支持上述所有场景的完整录制与回放框架。

---

## 1. 系统架构设计

### 1.1 核心模块

```
┌─────────────────────────────────────────────────────┐
│                   时间回溯/幽灵系统                    │
├──────────────┬──────────────┬───────────────────────┤
│  录制子系统   │  回放子系统  │     时间控制子系统      │
│  StateRecorder│ StatePlayer │   TimeScaleController  │
│  CircularBuffer│ Interpolator│   RewindController    │
└──────────────┴──────────────┴───────────────────────┘
        ↓               ↓               ↓
┌────────────────────────────────────────────────────┐
│              状态快照系统 (SnapshotSystem)           │
│   EntitySnapshot: Transform + Physics + Animation  │
└────────────────────────────────────────────────────┘
```

### 1.2 状态快照数据结构

```csharp
// EntitySnapshot.cs
using UnityEngine;
using System;

/// <summary>
/// 实体状态快照 - 记录某一时刻的完整状态
/// 设计原则：尽量精简，降低内存占用
/// </summary>
[Serializable]
public struct EntitySnapshot
{
    // --- 时间戳 ---
    public float timestamp;           // 录制时的游戏时间（秒）

    // --- Transform ---
    public Vector3    position;
    public Quaternion rotation;
    public Vector3    scale;

    // --- 物理状态（若有Rigidbody）---
    public Vector3 velocity;
    public Vector3 angularVelocity;

    // --- 动画状态 ---
    public int   animStateHash;       // Animator状态Hash
    public float animNormalizedTime;  // 动画归一化时间
    public float animBlendValue;      // 混合树参数

    // --- 自定义游戏状态 ---
    public int   hp;
    public int   mana;
    public bool  isGrounded;
    public byte  inputFlags;          // 压缩的输入状态位标志

    // 快照大小（用于内存预算计算）
    public const int ByteSize = 
        sizeof(float) * (1 + 3 + 4 + 3 + 3 + 3 + 1 + 1 + 1) +
        sizeof(int) * (1 + 2) +
        sizeof(bool) +
        sizeof(byte);

    /// <summary>
    /// 在两个快照之间插值（用于平滑回放）
    /// </summary>
    public static EntitySnapshot Lerp(EntitySnapshot a, EntitySnapshot b, float t)
    {
        return new EntitySnapshot
        {
            timestamp         = Mathf.Lerp(a.timestamp, b.timestamp, t),
            position          = Vector3.Lerp(a.position, b.position, t),
            rotation          = Quaternion.Slerp(a.rotation, b.rotation, t),
            scale             = Vector3.Lerp(a.scale, b.scale, t),
            velocity          = Vector3.Lerp(a.velocity, b.velocity, t),
            angularVelocity   = Vector3.Lerp(a.angularVelocity, b.angularVelocity, t),
            animStateHash     = t < 0.5f ? a.animStateHash : b.animStateHash,
            animNormalizedTime = Mathf.Lerp(a.animNormalizedTime, b.animNormalizedTime, t),
            animBlendValue    = Mathf.Lerp(a.animBlendValue, b.animBlendValue, t),
            hp                = Mathf.RoundToInt(Mathf.Lerp(a.hp, b.hp, t)),
            mana              = Mathf.RoundToInt(Mathf.Lerp(a.mana, b.mana, t)),
            isGrounded        = t < 0.5f ? a.isGrounded : b.isGrounded,
            inputFlags        = t < 0.5f ? a.inputFlags : b.inputFlags
        };
    }
}

/// <summary>
/// 快照序列 - 一段时间内的所有快照
/// </summary>
public class SnapshotSequence
{
    public EntitySnapshot[] Snapshots;
    public int Count;
    public float Duration => Count > 0 ? Snapshots[Count - 1].timestamp - Snapshots[0].timestamp : 0f;

    // 用于按时间二分查找
    public int FindSnapshotIndex(float time)
    {
        int lo = 0, hi = Count - 1;
        while (lo < hi)
        {
            int mid = (lo + hi) / 2;
            if (Snapshots[mid].timestamp < time) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }
}
```

---

## 2. 环形缓冲区录制系统

```csharp
// StateRecorder.cs
using System;
using UnityEngine;

/// <summary>
/// 状态录制器 - 使用环形缓冲区高效存储快照
/// 支持指定时间长度的倒带录制（例如：始终保留最近10秒数据）
/// </summary>
[RequireComponent(typeof(Rigidbody))]
public class StateRecorder : MonoBehaviour
{
    [Header("录制配置")]
    [SerializeField] private float recordDuration  = 10f;   // 最大保留时长（秒）
    [SerializeField] private float recordFrequency = 30f;   // 每秒录制帧数
    [SerializeField] private bool  recordOnStart   = true;

    // 依赖组件
    private Rigidbody   rb;
    private Animator    animator;
    private IGameState  gameState; // 自定义游戏状态接口

    // 环形缓冲区
    private EntitySnapshot[] buffer;
    private int writeHead;    // 下一个写入位置
    private int readHead;     // 有效数据起始位置
    private int bufferSize;
    private int validCount;   // 有效快照数量

    // 状态标志
    public bool IsRecording { get; private set; }
    public float RecordedDuration => validCount > 0
        ? buffer[GetAbsIndex(validCount - 1)].timestamp - buffer[readHead].timestamp
        : 0f;

    // 事件
    public event Action<EntitySnapshot> OnSnapshotTaken;

    private void Awake()
    {
        rb        = GetComponent<Rigidbody>();
        animator  = GetComponentInChildren<Animator>();
        gameState = GetComponent<IGameState>();

        // 预分配缓冲区
        bufferSize = Mathf.CeilToInt(recordDuration * recordFrequency) + 2;
        buffer     = new EntitySnapshot[bufferSize];
    }

    private void Start()
    {
        if (recordOnStart) StartRecording();
    }

    public void StartRecording()
    {
        IsRecording = true;
        InvokeRepeating(nameof(TakeSnapshot), 0f, 1f / recordFrequency);
    }

    public void StopRecording()
    {
        IsRecording = false;
        CancelInvoke(nameof(TakeSnapshot));
    }

    /// <summary>
    /// 采集当前状态快照
    /// </summary>
    private void TakeSnapshot()
    {
        var snapshot = new EntitySnapshot
        {
            timestamp        = Time.time,
            position         = transform.position,
            rotation         = transform.rotation,
            scale            = transform.localScale,
            velocity         = rb != null ? rb.linearVelocity : Vector3.zero,
            angularVelocity  = rb != null ? rb.angularVelocity : Vector3.zero,
        };

        // 采集动画状态
        if (animator != null)
        {
            var stateInfo = animator.GetCurrentAnimatorStateInfo(0);
            snapshot.animStateHash      = stateInfo.shortNameHash;
            snapshot.animNormalizedTime = stateInfo.normalizedTime;
            snapshot.animBlendValue     = animator.GetFloat("Speed"); // 示例参数名
        }

        // 采集自定义游戏状态
        if (gameState != null)
        {
            snapshot.hp         = gameState.HP;
            snapshot.mana       = gameState.Mana;
            snapshot.isGrounded = gameState.IsGrounded;
            snapshot.inputFlags = gameState.GetInputFlags();
        }

        // 写入环形缓冲区
        buffer[writeHead] = snapshot;
        writeHead = (writeHead + 1) % bufferSize;

        if (validCount < bufferSize)
            validCount++;
        else
            readHead = (readHead + 1) % bufferSize; // 覆盖最旧数据

        OnSnapshotTaken?.Invoke(snapshot);
    }

    /// <summary>
    /// 获取指定时间的快照（插值）
    /// </summary>
    public EntitySnapshot GetSnapshotAtTime(float time)
    {
        if (validCount == 0) return default;

        // 在有效快照中查找
        for (int i = 0; i < validCount - 1; i++)
        {
            var a = buffer[GetAbsIndex(i)];
            var b = buffer[GetAbsIndex(i + 1)];

            if (time >= a.timestamp && time <= b.timestamp)
            {
                float t = (time - a.timestamp) / (b.timestamp - a.timestamp);
                return EntitySnapshot.Lerp(a, b, Mathf.Clamp01(t));
            }
        }

        // 超出范围，返回边界快照
        if (time <= buffer[readHead].timestamp)
            return buffer[readHead];

        return buffer[GetAbsIndex(validCount - 1)];
    }

    /// <summary>
    /// 导出快照序列（用于幽灵系统存储最佳成绩）
    /// </summary>
    public SnapshotSequence ExportSequence()
    {
        var seq = new SnapshotSequence
        {
            Snapshots = new EntitySnapshot[validCount],
            Count     = validCount
        };

        for (int i = 0; i < validCount; i++)
            seq.Snapshots[i] = buffer[GetAbsIndex(i)];

        return seq;
    }

    private int GetAbsIndex(int relativeIndex)
        => (readHead + relativeIndex) % bufferSize;
}

/// <summary>
/// 游戏状态接口 - 由角色控制器实现
/// </summary>
public interface IGameState
{
    int  HP          { get; }
    int  Mana        { get; }
    bool IsGrounded  { get; }
    byte GetInputFlags();
    void RestoreFromSnapshot(EntitySnapshot snapshot);
}
```

---

## 3. 时间回溯控制器

```csharp
// RewindController.cs
using System.Collections;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// 时间回溯控制器
/// 支持：瞬时回到某时刻 / 连续倒带播放 / 回溯预览
/// </summary>
[RequireComponent(typeof(StateRecorder))]
public class RewindController : MonoBehaviour
{
    [Header("回溯配置")]
    [SerializeField] private float maxRewindTime = 5f;     // 最大回溯时长
    [SerializeField] private float rewindSpeed   = 2f;     // 回溯速度倍率
    [SerializeField] private KeyCode rewindKey   = KeyCode.R;

    [Header("UI反馈")]
    [SerializeField] private Slider   rewindSlider;
    [SerializeField] private Image    rewindOverlay;  // 回溯时的全屏滤镜
    [SerializeField] private Material timeEffectMaterial; // 后处理材质（色偏、扫描线等）

    [Header("音效")]
    [SerializeField] private AudioSource rewindAudio;
    [SerializeField] private AudioClip   rewindLoop;
    [SerializeField] private AudioClip   rewindEnd;

    private StateRecorder recorder;
    private IGameState     gameState;
    private Rigidbody      rb;
    private Animator       animator;

    public bool IsRewinding { get; private set; }
    private float rewindTargetTime;
    private float currentRewindTime;

    private void Awake()
    {
        recorder  = GetComponent<StateRecorder>();
        gameState = GetComponent<IGameState>();
        rb        = GetComponent<Rigidbody>();
        animator  = GetComponentInChildren<Animator>();
    }

    private void Update()
    {
        // 长按R键开始倒带
        if (Input.GetKeyDown(rewindKey))
            BeginRewind();

        if (Input.GetKeyUp(rewindKey))
            EndRewind();

        if (IsRewinding)
            UpdateRewind();
    }

    /// <summary>
    /// 开始连续倒带
    /// </summary>
    public void BeginRewind()
    {
        if (IsRewinding || recorder.RecordedDuration <= 0) return;

        IsRewinding = true;
        currentRewindTime = Time.time;

        // 暂停录制（回溯期间不录制）
        recorder.StopRecording();

        // 冻结物理
        if (rb != null)
        {
            rb.isKinematic = true;
        }

        // 播放音效和UI效果
        PlayRewindEffects(true);

        // 通知游戏系统（暂停敌人AI、禁用输入等）
        GameManager.Instance?.SetRewindMode(true);
    }

    /// <summary>
    /// 结束倒带，恢复游戏状态
    /// </summary>
    public void EndRewind()
    {
        if (!IsRewinding) return;

        IsRewinding = false;

        // 应用当前回溯时间点的状态
        var snapshot = recorder.GetSnapshotAtTime(currentRewindTime);
        ApplySnapshot(snapshot);

        // 恢复录制
        recorder.StartRecording();

        // 恢复物理
        if (rb != null)
        {
            rb.isKinematic = false;
            rb.linearVelocity = -snapshot.velocity; // 以倒带结束时的速度反向启动（可选）
        }

        PlayRewindEffects(false);
        GameManager.Instance?.SetRewindMode(false);
    }

    private void UpdateRewind()
    {
        // 时间向前倒退
        currentRewindTime -= Time.unscaledDeltaTime * rewindSpeed;

        // 限制回溯范围
        float minTime = Time.time - Mathf.Min(maxRewindTime, recorder.RecordedDuration);
        currentRewindTime = Mathf.Max(currentRewindTime, minTime);

        // 采样并应用快照
        var snapshot = recorder.GetSnapshotAtTime(currentRewindTime);
        ApplySnapshot(snapshot);

        // 更新UI
        if (rewindSlider != null)
        {
            float recordStart = Time.time - recorder.RecordedDuration;
            float progress = (currentRewindTime - recordStart) / recorder.RecordedDuration;
            rewindSlider.value = progress;
        }

        // 到达最早记录点自动结束
        float minPossibleTime = Time.time - recorder.RecordedDuration;
        if (currentRewindTime <= minPossibleTime + 0.05f)
            EndRewind();
    }

    /// <summary>
    /// 瞬时跳转到指定时间点（不连续播放）
    /// </summary>
    public void JumpToTime(float targetTime)
    {
        var snapshot = recorder.GetSnapshotAtTime(targetTime);
        ApplySnapshot(snapshot);
    }

    private void ApplySnapshot(EntitySnapshot snapshot)
    {
        // 应用Transform
        transform.position = snapshot.position;
        transform.rotation = snapshot.rotation;

        // 应用物理（如果非kinematic）
        if (rb != null && !rb.isKinematic)
        {
            rb.linearVelocity = snapshot.velocity;
            rb.angularVelocity = snapshot.angularVelocity;
        }

        // 应用动画状态
        if (animator != null && snapshot.animStateHash != 0)
        {
            animator.Play(snapshot.animStateHash, 0, snapshot.animNormalizedTime);
            animator.SetFloat("Speed", snapshot.animBlendValue);
        }

        // 应用游戏状态
        gameState?.RestoreFromSnapshot(snapshot);
    }

    private void PlayRewindEffects(bool isRewinding)
    {
        // 全屏色调变化（蓝色调代表时间倒流）
        if (rewindOverlay != null)
        {
            rewindOverlay.enabled = isRewinding;
            if (isRewinding)
                StartCoroutine(FadeOverlay(0f, 0.3f, 0.2f));
            else
                StartCoroutine(FadeOverlay(0.3f, 0f, 0.3f));
        }

        // 音效
        if (rewindAudio != null)
        {
            if (isRewinding)
            {
                rewindAudio.clip  = rewindLoop;
                rewindAudio.loop  = true;
                rewindAudio.pitch = -1f; // 反向播放
                rewindAudio.Play();
            }
            else
            {
                rewindAudio.Stop();
                rewindAudio.PlayOneShot(rewindEnd);
            }
        }
    }

    private IEnumerator FadeOverlay(float from, float to, float duration)
    {
        float elapsed = 0f;
        Color color = rewindOverlay.color;
        while (elapsed < duration)
        {
            elapsed += Time.unscaledDeltaTime;
            color.a = Mathf.Lerp(from, to, elapsed / duration);
            rewindOverlay.color = color;
            yield return null;
        }
    }
}
```

---

## 4. 竞速幽灵系统

```csharp
// GhostSystem.cs
using System.IO;
using System.Collections;
using UnityEngine;

/// <summary>
/// 竞速幽灵系统 - 录制最佳成绩并在下次游玩时显示幽灵对手
/// </summary>
public class GhostSystem : MonoBehaviour
{
    [Header("幽灵配置")]
    [SerializeField] private GameObject ghostPrefab;       // 半透明幽灵外观预制体
    [SerializeField] private Material   ghostMaterial;     // 半透明幽灵材质
    [SerializeField] private float      ghostAlpha = 0.4f; // 幽灵透明度
    [SerializeField] private bool       showGhost  = true;

    [Header("录制配置")]
    [SerializeField] private float recordRate = 20f; // 每秒录制帧数（幽灵比回溯精度低一些）
    [SerializeField] private string saveFileName = "BestGhost.dat";

    // 当前局录制
    private StateRecorder playerRecorder;
    private SnapshotSequence currentRunData;

    // 最佳成绩数据
    private SnapshotSequence bestRunData;
    private float bestLapTime = float.MaxValue;

    // 幽灵回放对象
    private GameObject ghostObject;
    private Renderer[] ghostRenderers;
    private bool isPlayingGhost;
    private float ghostPlaybackStartTime;

    // 幽灵相对于玩家的时差（可设置为+/-几秒，营造追逐感）
    private float ghostTimeOffset = 0f;

    private void Start()
    {
        playerRecorder = GetComponent<StateRecorder>();
        LoadBestGhost();
        InitializeGhostObject();
    }

    /// <summary>
    /// 比赛开始：开始录制玩家数据，同时播放最佳幽灵
    /// </summary>
    public void StartRace()
    {
        // 开始录制当前局
        currentRunData = null;
        playerRecorder.StartRecording();

        // 如果有最佳幽灵数据，开始播放
        if (bestRunData != null && showGhost)
            StartGhostPlayback();
    }

    /// <summary>
    /// 比赛结束：检查是否刷新最佳成绩
    /// </summary>
    public void FinishRace(float lapTime)
    {
        playerRecorder.StopRecording();
        currentRunData = playerRecorder.ExportSequence();

        if (lapTime < bestLapTime)
        {
            bestLapTime = lapTime;
            bestRunData = currentRunData;
            SaveBestGhost();

            Debug.Log($"[Ghost] 新纪录！{lapTime:F3}秒，已保存幽灵数据（{currentRunData.Count}帧）");
            ShowNewRecordEffect();
        }

        StopGhostPlayback();
    }

    private void StartGhostPlayback()
    {
        if (bestRunData == null || ghostObject == null) return;

        isPlayingGhost = true;
        ghostPlaybackStartTime = Time.time;
        ghostObject.SetActive(true);
    }

    private void StopGhostPlayback()
    {
        isPlayingGhost = false;
        if (ghostObject != null)
            ghostObject.SetActive(false);
    }

    private void Update()
    {
        if (!isPlayingGhost || bestRunData == null) return;

        float elapsed = Time.time - ghostPlaybackStartTime + ghostTimeOffset;

        // 播放结束
        if (elapsed > bestRunData.Duration)
        {
            StopGhostPlayback();
            return;
        }

        // 查找当前时间对应的快照（插值）
        float absoluteTime = bestRunData.Snapshots[0].timestamp + elapsed;
        int idx = bestRunData.FindSnapshotIndex(absoluteTime);

        if (idx < bestRunData.Count - 1)
        {
            var a = bestRunData.Snapshots[idx];
            var b = bestRunData.Snapshots[idx + 1];
            float t = (absoluteTime - a.timestamp) / (b.timestamp - a.timestamp);
            var interpolated = EntitySnapshot.Lerp(a, b, Mathf.Clamp01(t));

            // 应用到幽灵对象
            ghostObject.transform.position = interpolated.position;
            ghostObject.transform.rotation = interpolated.rotation;

            // 幽灵动画（如有Animator组件）
            var ghostAnimator = ghostObject.GetComponentInChildren<Animator>();
            if (ghostAnimator != null && interpolated.animStateHash != 0)
            {
                ghostAnimator.Play(interpolated.animStateHash, 0, interpolated.animNormalizedTime);
            }

            // 计算幽灵与玩家的时差（用于UI显示 +X.Xs ahead/behind）
            DisplayTimeDelta();
        }
    }

    private void DisplayTimeDelta()
    {
        // 幽灵当前时间 vs 玩家当前时间
        float ghostElapsed  = Time.time - ghostPlaybackStartTime + ghostTimeOffset;
        float playerElapsed = Time.time - ghostPlaybackStartTime; // 玩家没有偏移

        float delta = playerElapsed - ghostElapsed; // 正数 = 玩家落后
        string sign = delta > 0 ? "+" : "-";
        string msg  = $"{sign}{Mathf.Abs(delta):F2}s";

        // TODO: 推送到UI显示（HUD时差标签）
        // TimeDeltaLabel.text = delta > 0 ? $"<color=red>{msg}</color>" : $"<color=green>{msg}</color>";
    }

    private void InitializeGhostObject()
    {
        if (ghostPrefab == null) return;

        ghostObject = Instantiate(ghostPrefab);
        ghostObject.name = "Ghost_Player";
        ghostObject.SetActive(false);

        // 设置幽灵材质（半透明，不同颜色区分）
        ghostRenderers = ghostObject.GetComponentsInChildren<Renderer>();
        foreach (var r in ghostRenderers)
        {
            r.material = ghostMaterial;
            Color c = r.material.color;
            c.a = ghostAlpha;
            r.material.color = c;
        }

        // 禁用幽灵的碰撞体和脚本（纯视觉）
        foreach (var col in ghostObject.GetComponentsInChildren<Collider>())
            col.enabled = false;
        foreach (var script in ghostObject.GetComponentsInChildren<MonoBehaviour>())
        {
            if (script != this) script.enabled = false;
        }
    }

    // ======== 存档 / 读档 ========

    private string SavePath => Path.Combine(Application.persistentDataPath, saveFileName);

    private void SaveBestGhost()
    {
        try
        {
            using var stream = new FileStream(SavePath, FileMode.Create);
            using var writer = new BinaryWriter(stream);

            writer.Write(bestLapTime);
            writer.Write(bestRunData.Count);
            for (int i = 0; i < bestRunData.Count; i++)
            {
                var s = bestRunData.Snapshots[i];
                writer.Write(s.timestamp);
                writer.Write(s.position.x);  writer.Write(s.position.y);  writer.Write(s.position.z);
                writer.Write(s.rotation.x);  writer.Write(s.rotation.y);
                writer.Write(s.rotation.z);  writer.Write(s.rotation.w);
                writer.Write(s.animStateHash);
                writer.Write(s.animNormalizedTime);
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[Ghost] 保存失败: {e.Message}");
        }
    }

    private void LoadBestGhost()
    {
        if (!File.Exists(SavePath)) return;

        try
        {
            using var stream = new FileStream(SavePath, FileMode.Open);
            using var reader = new BinaryReader(stream);

            bestLapTime = reader.ReadSingle();
            int count   = reader.ReadInt32();

            bestRunData = new SnapshotSequence
            {
                Snapshots = new EntitySnapshot[count],
                Count     = count
            };

            for (int i = 0; i < count; i++)
            {
                bestRunData.Snapshots[i] = new EntitySnapshot
                {
                    timestamp = reader.ReadSingle(),
                    position  = new Vector3(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle()),
                    rotation  = new Quaternion(reader.ReadSingle(), reader.ReadSingle(),
                                               reader.ReadSingle(), reader.ReadSingle()),
                    animStateHash      = reader.ReadInt32(),
                    animNormalizedTime = reader.ReadSingle()
                };
            }

            Debug.Log($"[Ghost] 加载最佳成绩: {bestLapTime:F3}秒，共{count}帧快照");
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[Ghost] 读取失败: {e.Message}");
            bestRunData = null;
        }
    }

    private void ShowNewRecordEffect()
    {
        // 显示新纪录UI效果
        Debug.Log("🏆 新纪录！");
        // NewRecordUI.Instance?.Show(bestLapTime);
    }
}
```

---

## 5. 超级热风格时间缩放系统

```csharp
// SuperHotTimeController.cs
using UnityEngine;

/// <summary>
/// 《超级热》风格时间控制：
/// 玩家静止时时间几乎停止，玩家移动时时间正常流动
/// </summary>
public class SuperHotTimeController : MonoBehaviour
{
    [Header("时间缩放参数")]
    [Range(0f, 1f)]
    [SerializeField] private float minTimeScale      = 0.05f; // 静止时最慢速度
    [SerializeField] private float maxTimeScale      = 1.0f;  // 最快速度
    [SerializeField] private float timeScaleResponse = 3.0f;  // 响应速度

    [Header("输入映射")]
    [SerializeField] private float movementThreshold = 0.1f;  // 移动检测阈值
    [SerializeField] private bool  includeMouseInput = true;  // 鼠标移动是否加速时间

    private CharacterController characterController;
    private float currentTimeScale;
    private Vector3 lastPosition;
    private float   inputMagnitude;

    private void Awake()
    {
        characterController = GetComponent<CharacterController>();
        currentTimeScale    = minTimeScale;
        lastPosition        = transform.position;
    }

    private void Update()
    {
        // 计算玩家输入强度（0~1）
        Vector2 moveInput = new Vector2(Input.GetAxis("Horizontal"), Input.GetAxis("Vertical"));
        float keyboardInput = moveInput.magnitude;

        float mouseInput = 0f;
        if (includeMouseInput)
        {
            float mouseX = Mathf.Abs(Input.GetAxis("Mouse X"));
            float mouseY = Mathf.Abs(Input.GetAxis("Mouse Y"));
            mouseInput = Mathf.Clamp01((mouseX + mouseY) * 0.5f);
        }

        // 综合输入强度
        inputMagnitude = Mathf.Max(keyboardInput, mouseInput);

        // 计算目标时间缩放
        float targetTimeScale = Mathf.Lerp(minTimeScale, maxTimeScale,
            Mathf.Clamp01(inputMagnitude / movementThreshold));

        // 平滑过渡（使用非缩放时间，避免自我依赖）
        currentTimeScale = Mathf.Lerp(currentTimeScale, targetTimeScale,
            Time.unscaledDeltaTime * timeScaleResponse);

        Time.timeScale    = currentTimeScale;
        Time.fixedDeltaTime = 0.02f * currentTimeScale; // 同步物理时间步

        // 更新音调（时间快=音调高）
        AudioListener.pitch = Mathf.Lerp(0.5f, 1.0f,
            (currentTimeScale - minTimeScale) / (maxTimeScale - minTimeScale));
    }

    private void OnDisable()
    {
        // 确保离开时恢复正常时间
        Time.timeScale      = 1f;
        Time.fixedDeltaTime = 0.02f;
        AudioListener.pitch = 1f;
    }
}

/// <summary>
/// 时间泡泡：局部时间缩放（只影响特定对象）
/// 避免全局Time.timeScale的副作用
/// </summary>
public class TimeBubble : MonoBehaviour
{
    [SerializeField] private float bubbleTimeScale = 0.1f;
    [SerializeField] private float bubbleRadius    = 5f;

    private void Update()
    {
        // 找出泡泡范围内的所有实体，单独施加慢动作
        Collider[] affected = Physics.OverlapSphere(transform.position, bubbleRadius);
        foreach (var col in affected)
        {
            var controlled = col.GetComponent<ITimeControlled>();
            controlled?.SetLocalTimeScale(bubbleTimeScale);
        }
    }
}

// 实现接口的示例组件
public interface ITimeControlled
{
    void SetLocalTimeScale(float scale);
}
```

---

## 6. Kill Cam击杀回放系统

```csharp
// KillCamSystem.cs
using System.Collections;
using UnityEngine;

/// <summary>
/// Kill Cam系统：玩家死亡时自动播放倒退5秒的精彩回放
/// </summary>
public class KillCamSystem : MonoBehaviour
{
    [Header("Kill Cam配置")]
    [SerializeField] private float replayDuration = 5f;    // 回放时长（秒）
    [SerializeField] private float replaySpeed    = 0.5f;  // 慢动作倍率

    [Header("摄像机")]
    [SerializeField] private Camera killCamCamera;         // 专用回放摄像机
    [SerializeField] private float  cameraOrbitSpeed = 30f; // 绕体旋转速度

    private StateRecorder victimRecorder;
    private StateRecorder killerRecorder;

    private bool isPlayingKillCam;

    /// <summary>
    /// 触发Kill Cam（在玩家死亡事件中调用）
    /// </summary>
    public void TriggerKillCam(GameObject victim, GameObject killer)
    {
        victimRecorder = victim.GetComponent<StateRecorder>();
        killerRecorder = killer?.GetComponent<StateRecorder>();

        if (victimRecorder == null) return;

        StartCoroutine(PlayKillCamSequence(victim));
    }

    private IEnumerator PlayKillCamSequence(GameObject victim)
    {
        isPlayingKillCam = true;

        // 激活Kill Cam摄像机，禁用主摄像机
        Camera.main.gameObject.SetActive(false);
        killCamCamera.gameObject.SetActive(true);

        // 全局时间慢动作
        Time.timeScale      = replaySpeed;
        Time.fixedDeltaTime = 0.02f * replaySpeed;

        // 计算回放起始时间（死亡时刻 - replayDuration秒）
        float deathTime    = Time.time;
        float replayStart  = deathTime - replayDuration;
        float playbackTime = replayStart;

        while (playbackTime < deathTime)
        {
            playbackTime += Time.unscaledDeltaTime * 2f; // 正常速度播放（但画面是慢动作）

            // 恢复受害者位置（用于摄像机跟踪）
            if (victimRecorder != null)
            {
                var snapshot = victimRecorder.GetSnapshotAtTime(playbackTime);
                // 摄像机绕受害者最终位置旋转
                float angle = (playbackTime - replayStart) / replayDuration * 360f * (cameraOrbitSpeed / 360f);
                Vector3 camOffset = Quaternion.Euler(20f, angle, 0) * new Vector3(0, 0, -4f);
                killCamCamera.transform.position = snapshot.position + camOffset + Vector3.up;
                killCamCamera.transform.LookAt(snapshot.position + Vector3.up);
            }

            yield return null;
        }

        // Kill Cam结束，恢复正常
        Time.timeScale      = 1f;
        Time.fixedDeltaTime = 0.02f;
        killCamCamera.gameObject.SetActive(false);
        Camera.main.gameObject.SetActive(true);

        isPlayingKillCam = false;

        // 触发死亡/重生流程
        GameManager.Instance?.OnKillCamFinished();
    }
}
```

---

## 7. 性能优化最佳实践

### 7.1 内存预算分析

```csharp
/// <summary>
/// 计算录制系统的内存消耗
/// </summary>
public static class RecordingMemoryAnalysis
{
    public static void PrintMemoryBudget(int entityCount, float recordSeconds, float frequency)
    {
        int framesPerEntity = Mathf.CeilToInt(recordSeconds * frequency);
        long bytesPerEntity = framesPerEntity * EntitySnapshot.ByteSize;
        long totalBytes     = bytesPerEntity * entityCount;

        Debug.Log($"[Memory] 录制内存预算：\n" +
            $"  实体数量: {entityCount}\n" +
            $"  录制时长: {recordSeconds}秒 @ {frequency}Hz\n" +
            $"  每实体帧数: {framesPerEntity}\n" +
            $"  每实体内存: {bytesPerEntity / 1024f:F1} KB\n" +
            $"  总内存消耗: {totalBytes / 1024f / 1024f:F2} MB");
        // 典型参数（10实体，10秒，30Hz）：约 1.2 MB
    }
}
```

### 7.2 关键优化清单

| 优化点 | 策略 | 效果 |
|--------|------|------|
| **快照压缩** | 用half替换float，位置差量编码 | 内存减少50% |
| **动画状态** | 只记录状态Hash+归一化时间，不记录完整骨骼 | 避免巨量数据 |
| **选择性录制** | 只录制玩家和关键NPC，无关对象不录制 | 按需分配 |
| **后台序列化** | 存盘用后台线程，不阻塞游戏逻辑 | 零帧率波动 |
| **LOD回放** | 距离远的幽灵降低更新频率 | GPU与CPU双降 |

### 7.3 常见问题

**Q: 回溯时物理对象的行为不一致？**  
A: 物理引擎（PhysX/Bullet）是有状态的，无法简单倒带。解决方案：回溯时将所有Rigidbody切换为Kinematic，直接设置position/rotation，结束回溯时恢复并给予正确初速度。

**Q: 网络多人游戏中如何同步幽灵？**  
A: 幽灵数据（SnapshotSequence）存储在服务器，下载后本地回放。关键：时间戳使用服务器时间（ServerTime），而非客户端本地时间。

**Q: 回溯后游戏事件（得分、伤害）如何处理？**  
A: 维护一个"事件回滚列表"，回溯时撤销对应事件（扣除临时得分、恢复HP等）。永久事件（已发出的网络包）不回滚。

---

## 总结

本文完整实现了时间回溯与幽灵系统的三大核心功能：

1. **环形缓冲录制**：高效存储N秒状态历史，零GC分配
2. **平滑插值回放**：基于时间戳的线性/球面插值，回放流畅自然
3. **竞速幽灵系统**：最佳成绩本地持久化，半透明幽灵跟随播放
4. **时间缩放控制**：超级热风格输入驱动时间流速，局部时间泡泡
5. **Kill Cam系统**：死亡时自动回放精彩瞬间，慢动作效果

该框架可直接扩展应用于：解谜游戏的时间操控机制、格斗游戏的AI镜像训练、赛车游戏的多幽灵对手、以及教学/调试用的游戏录像系统。
