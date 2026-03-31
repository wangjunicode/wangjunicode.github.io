---
title: 游戏多人语音聊天系统：VOIP集成实战
published: 2026-03-31
description: 全面解析游戏内多人语音聊天（VOIP）系统的工程集成，涵盖Vivox/Agora/腾讯TRTC SDK接入、麦克风权限处理与回声消除、语音频道管理（队伍频道/全体频道）、推送到说/持续发送模式切换、语音检测可视化（说话指示器）、音量控制，以及低延迟语音编码选择。
tags: [Unity, 语音聊天, VOIP, 多人游戏, SDK集成]
category: 网络同步
draft: false
---

## 一、VOIP 系统架构

```
语音聊天系统架构：

Client A ──┐
Client B ──┼──→ VOIP 服务器 (Vivox/Agora/TRTC) ──→ 分发给房间内其他成员
Client C ──┘

语音频道：
├── 队伍频道（只有队友能听到）
├── 全体频道（所有人）
├── 指挥频道（仅队长/指挥）
└── 私聊频道（点对点）

模式：
├── PTT（Push to Talk）：按住按钮才发送
└── 持续发送（Voice Activated）：检测声音自动发送
```

---

## 二、VOIP 管理器接口抽象

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// VOIP 管理器接口（便于替换不同SDK）
/// </summary>
public interface IVoipManager
{
    bool IsConnected { get; }
    bool IsMuted { get; }
    float OutputVolume { get; set; }
    
    void Initialize(string userId, string displayName);
    void JoinChannel(string channelId, VoipChannelType channelType);
    void LeaveChannel(string channelId);
    void SetMuted(bool muted);
    void SetPushToTalk(bool isPTT);
    void SetOutputVolume(string userId, float volume);
    
    event Action<string> OnUserSpeaking;
    event Action<string> OnUserStoppedSpeaking;
    event Action OnConnected;
    event Action<string> OnDisconnected;
    event Action<string> OnError;
}

public enum VoipChannelType { Team, World, Command, Private }

/// <summary>
/// 通用 VOIP 管理器（包装 SDK 调用）
/// </summary>
public class VoipManager : MonoBehaviour, IVoipManager
{
    private static VoipManager instance;
    public static VoipManager Instance => instance;

    [Header("配置")]
    [SerializeField] private string appId;              // VOIP SDK App ID
    [SerializeField] private bool enableEchoCancellation = true;
    [SerializeField] private bool enableNoiseSuppression = true;
    [SerializeField] private float voiceActivationThreshold = 0.02f; // 声音激活阈值
    
    // 状态
    private bool isConnected;
    private bool isMuted;
    private float outputVolume = 1f;
    private bool isPTTMode = true;       // 默认PTT模式
    private bool isPTTPressed;
    
    private Dictionary<string, bool> speakingUsers = new Dictionary<string, bool>();
    private HashSet<string> joinedChannels = new HashSet<string>();
    
    // 麦克风音量检测
    private AudioClip microphoneClip;
    private float[] micBuffer = new float[1024];
    private bool wasAboveThreshold;

    public bool IsConnected => isConnected;
    public bool IsMuted => isMuted || (isPTTMode && !isPTTPressed);
    
    public float OutputVolume
    {
        get => outputVolume;
        set
        {
            outputVolume = Mathf.Clamp01(value);
            SetGlobalOutputVolume(outputVolume);
        }
    }

    public event Action<string> OnUserSpeaking;
    public event Action<string> OnUserStoppedSpeaking;
    public event Action OnConnected;
    public event Action<string> OnDisconnected;
    public event Action<string> OnError;

    void Awake() { instance = this; }

    public void Initialize(string userId, string displayName)
    {
        // 请求麦克风权限
        if (Application.HasUserAuthorization(UserAuthorization.Microphone))
        {
            StartMicrophoneCapture();
        }
        else
        {
            Application.RequestUserAuthorization(UserAuthorization.Microphone)
                .completed += op =>
                {
                    if (Application.HasUserAuthorization(UserAuthorization.Microphone))
                        StartMicrophoneCapture();
                };
        }
        
        // 初始化 SDK（以 Agora 为例，实际替换对应SDK调用）
        InitSDK(userId, displayName);
    }

    void InitSDK(string userId, string displayName)
    {
        // Agora SDK 初始化示例（需安装Agora SDK）
        // var engine = Agora.Rtc.RtcEngine.CreateAgoraRtcEngine();
        // engine.Initialize(new Agora.Rtc.RtcEngineContext(appId));
        
        // 腾讯 TRTC 示例
        // var trtcCloud = TRTCCloud.getTRTCShareInstance();
        // trtcCloud.setDefaultStreamRecvMode(false, true); // 只接收音频
        
        Debug.Log($"[VOIP] Initialized for user: {userId}");
        isConnected = true;
        OnConnected?.Invoke();
    }

    void StartMicrophoneCapture()
    {
        if (Microphone.devices.Length == 0)
        {
            Debug.LogWarning("[VOIP] No microphone found");
            return;
        }
        
        string micDevice = Microphone.devices[0];
        microphoneClip = Microphone.Start(micDevice, true, 1, 44100);
        
        Debug.Log($"[VOIP] Microphone started: {micDevice}");
    }

    public void JoinChannel(string channelId, VoipChannelType channelType)
    {
        if (joinedChannels.Contains(channelId)) return;
        
        joinedChannels.Add(channelId);
        
        // 加入语音频道（SDK调用）
        Debug.Log($"[VOIP] Joined channel: {channelId} ({channelType})");
    }

    public void LeaveChannel(string channelId)
    {
        joinedChannels.Remove(channelId);
        Debug.Log($"[VOIP] Left channel: {channelId}");
    }

    public void SetMuted(bool muted)
    {
        isMuted = muted;
        UpdateMicrophoneTransmission();
    }

    public void SetPushToTalk(bool ptt)
    {
        isPTTMode = ptt;
    }

    // PTT 按钮事件
    public void OnPTTButtonDown() 
    { 
        isPTTPressed = true; 
        UpdateMicrophoneTransmission();
    }
    
    public void OnPTTButtonUp() 
    { 
        isPTTPressed = false;
        UpdateMicrophoneTransmission();
    }

    public void SetOutputVolume(string userId, float volume)
    {
        // 设置特定用户的音量
    }

    void UpdateMicrophoneTransmission()
    {
        bool shouldTransmit = !isMuted && (!isPTTMode || isPTTPressed);
        // 启用/禁用麦克风发送
    }

    void SetGlobalOutputVolume(float volume)
    {
        // 设置所有语音输出音量
    }

    void Update()
    {
        if (!isPTTMode) CheckVoiceActivation();
    }

    void CheckVoiceActivation()
    {
        if (microphoneClip == null) return;
        
        int pos = Microphone.GetPosition(null);
        microphoneClip.GetData(micBuffer, pos - micBuffer.Length < 0 ? 0 : pos - micBuffer.Length);
        
        float volume = 0f;
        foreach (float sample in micBuffer)
            volume += Mathf.Abs(sample);
        volume /= micBuffer.Length;
        
        bool aboveThreshold = volume > voiceActivationThreshold;
        
        if (aboveThreshold != wasAboveThreshold)
        {
            wasAboveThreshold = aboveThreshold;
            UpdateMicrophoneTransmission();
        }
    }
}
```

---

## 三、语音说话指示器 UI

```csharp
/// <summary>
/// 语音说话状态显示（玩家头顶显示麦克风图标）
/// </summary>
public class VoiceSpeakingIndicator : MonoBehaviour
{
    [SerializeField] private GameObject speakingIcon;  // 麦克风图标
    [SerializeField] private UnityEngine.UI.Image volumeBar;   // 音量波形
    [SerializeField] private string playerId;

    void Start()
    {
        speakingIcon.SetActive(false);
        
        VoipManager.Instance.OnUserSpeaking += OnUserSpeaking;
        VoipManager.Instance.OnUserStoppedSpeaking += OnUserStopped;
    }

    void OnDestroy()
    {
        if (VoipManager.Instance != null)
        {
            VoipManager.Instance.OnUserSpeaking -= OnUserSpeaking;
            VoipManager.Instance.OnUserStoppedSpeaking -= OnUserStopped;
        }
    }

    void OnUserSpeaking(string userId)
    {
        if (userId == playerId)
        {
            speakingIcon.SetActive(true);
            speakingIcon.transform.DOPunchScale(Vector3.one * 0.2f, 0.1f);
        }
    }

    void OnUserStopped(string userId)
    {
        if (userId == playerId)
            speakingIcon.SetActive(false);
    }
}
```

---

## 四、语音质量设置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 编码格式 | Opus | 低延迟，高质量，主流选择 |
| 采样率 | 16000 Hz | 语音用16K足够 |
| 比特率 | 32-64 Kbps | 平衡音质与流量 |
| 延迟目标 | < 200ms | 超过会明显感受到卡顿 |
| 回声消除 | 开启 | 防止扬声器声音反馈 |
| 降噪 | 开启 | 减少环境噪音 |
| AGC自动增益 | 开启 | 平衡不同麦克风音量 |

**SDK 选型参考：**
- Vivox：专为游戏设计，Epic/Ubisoft使用，Unity官方支持
- Agora：国内常用，集成简单，音视频俱全
- 腾讯TRTC：国内游戏首选，与腾讯游戏生态整合好
- WebRTC：开源方案，适合H5/Web游戏
