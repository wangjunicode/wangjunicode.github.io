---
title: "Unity Timeline深度解析：过场动画与运行时序列控制"
published: 2025-03-22
description: "全面解析Unity Timeline系统：从PlayableGraph底层原理到过场动画制作，从自定义Track/Clip开发到运行时动态控制，帮助你掌握Timeline在商业项目中的完整工程实践。"
tags: [Unity, Timeline, 动画, Cinemachine, 游戏开发]
category: Unity开发
draft: false
---

# Unity Timeline深度解析：过场动画与运行时序列控制

Timeline 是 Unity 自 2017 年引入的可视化序列编辑器，广泛用于过场动画、剧情演出、技能表演、UI 动效等场景。本文从底层 PlayableGraph 原理出发，系统讲解 Timeline 的开发与工程实践。

## 一、Timeline 核心架构

### 1.1 PlayableGraph 底层原理

Timeline 构建在 **Playables API** 之上，理解 PlayableGraph 是掌握 Timeline 的关键：

```
PlayableGraph
├── PlayableOutput（输出端，如 AnimationPlayableOutput）
└── PlayableMixer（混合器）
    ├── AnimationClipPlayable（具体动画片段）
    ├── AnimationClipPlayable
    └── ...
```

```csharp
// 手动创建 PlayableGraph 示例
void CreateManualGraph()
{
    var graph = PlayableGraph.Create("MyGraph");
    
    // 创建动画输出
    var output = AnimationPlayableOutput.Create(graph, "Animation", animator);
    
    // 创建混合树
    var mixer = AnimationMixerPlayable.Create(graph, 2);
    output.SetSourcePlayable(mixer);
    
    // 添加动画片段
    var clip1 = AnimationClipPlayable.Create(graph, idleClip);
    var clip2 = AnimationClipPlayable.Create(graph, walkClip);
    
    graph.Connect(clip1, 0, mixer, 0);
    graph.Connect(clip2, 0, mixer, 1);
    
    // 设置权重
    mixer.SetInputWeight(0, 0.5f);
    mixer.SetInputWeight(1, 0.5f);
    
    graph.Play();
}
```

### 1.2 Timeline 层级结构

```
TimelineAsset（时间线资产）
├── TrackAsset（轨道）
│   ├── TimelineClip（片段）
│   │   └── PlayableAsset（可播放资产）
│   └── TrackMixer（轨道混合器）
└── TimelineAsset（嵌套时间线）
```

### 1.3 PlayableDirector 组件

`PlayableDirector` 是 Timeline 的运行时控制入口：

```csharp
public class TimelineController : MonoBehaviour
{
    [SerializeField] private PlayableDirector director;
    
    void Start()
    {
        // 绑定时间线资产
        director.playableAsset = timelineAsset;
        
        // 配置播放模式
        director.extrapolationMode = DirectorWrapMode.None;
        
        // 监听事件
        director.played += OnPlayed;
        director.stopped += OnStopped;
        director.paused += OnPaused;
    }
    
    // 精确控制播放
    public void PlayFrom(double time)
    {
        director.time = time;
        director.Play();
    }
    
    // 跳转到指定时间（不触发播放）
    public void SeekTo(double time)
    {
        director.time = time;
        director.Evaluate(); // 强制更新一帧
    }
}
```

---

## 二、内置 Track 类型详解

### 2.1 Animation Track

用于控制 Animator 组件，是最常用的 Track 类型：

```csharp
// 运行时动态修改 Animation Track 绑定
void RebindAnimationTrack(PlayableDirector director, AnimationTrack track, Animator newAnimator)
{
    director.SetGenericBinding(track, newAnimator);
    director.RebindPlayableGraphOutputs();
}
```

**关键设置：**
- **Apply Avatar Mask**：应用 Avatar Mask 做局部动画
- **Track Offset**：偏移模式（Auto/Apply Transform Offsets/Apply Root Motion）
- **Infinite Clip**：适合单段长动画，无需分片段

### 2.2 Activation Track

控制 GameObject 的激活/隐藏：

```csharp
// 程序化创建 Activation Track
void AddActivationTrack(TimelineAsset timeline, GameObject target, double start, double duration)
{
    var track = timeline.CreateTrack<ActivationTrack>(null, "ShowTarget");
    var clip = track.CreateDefaultClip();
    clip.start = start;
    clip.duration = duration;
}
```

### 2.3 Control Track

嵌套 Timeline、控制粒子、激活 Prefab 的强力工具：

```csharp
// 通过代码向 Control Track 中添加粒子控制片段
void AddParticleClip(ControlTrack track, ParticleSystem ps, double start, double duration)
{
    var clip = track.CreateDefaultClip();
    clip.start = start;
    clip.duration = duration;
    
    var asset = clip.asset as ControlPlayableAsset;
    asset.sourceGameObject = new ExposedReference<GameObject> { defaultValue = ps.gameObject };
    asset.active = true;
    asset.particleRandomSeed = 0;
}
```

### 2.4 Signal Track（信号系统）

Timeline 与外部系统通信的桥梁：

```csharp
// 1. 创建 Signal Asset
// Assets > Create > Timeline > Signal

// 2. Signal Receiver 监听信号
public class TimelineSignalReceiver : MonoBehaviour, INotificationReceiver
{
    public void OnNotify(Playable origin, INotification notification, object context)
    {
        if (notification is SignalEmitter signal)
        {
            // 根据信号类型处理
            if (signal.asset == mySignalAsset)
            {
                TriggerGameEvent();
            }
        }
    }
    
    private void TriggerGameEvent()
    {
        Debug.Log("Timeline signal received!");
        GameEventSystem.Dispatch(EventType.CutsceneCheckpoint);
    }
}
```

---

## 三、自定义 Track 开发

自定义 Track 是 Timeline 高级用法的核心，可用于控制任意游戏对象行为。

### 3.1 完整自定义 Track 示例：相机抖动轨道

**Step 1：定义 Clip 数据**

```csharp
[Serializable]
public class CameraShakeClip : PlayableAsset, ITimelineClipAsset
{
    public float intensity = 1.0f;
    public float frequency = 10.0f;
    public AnimationCurve intensityCurve = AnimationCurve.EaseInOut(0, 1, 1, 0);
    
    // 声明 Clip 能力
    public ClipCaps clipCaps => ClipCaps.Blending | ClipCaps.Extrapolation;
    
    public override Playable CreatePlayable(PlayableGraph graph, GameObject owner)
    {
        var playable = ScriptPlayable<CameraShakeBehaviour>.Create(graph);
        var behaviour = playable.GetBehaviour();
        behaviour.intensity = intensity;
        behaviour.frequency = frequency;
        behaviour.intensityCurve = intensityCurve;
        return playable;
    }
}
```

**Step 2：定义 Behaviour 逻辑**

```csharp
public class CameraShakeBehaviour : PlayableBehaviour
{
    public float intensity;
    public float frequency;
    public AnimationCurve intensityCurve;
    
    private CameraShakeTrackMixer _mixer;
    
    // 每帧处理（由 Mixer 调用）
    public void ProcessFrame(float weight, double time, double duration)
    {
        float normalizedTime = (float)(time / duration);
        float curveValue = intensityCurve.Evaluate(normalizedTime);
        float currentIntensity = intensity * curveValue * weight;
        
        // 将抖动信息传递给相机
        float shakeX = Mathf.Sin((float)time * frequency * Mathf.PI * 2) * currentIntensity;
        float shakeY = Mathf.Cos((float)time * frequency * 1.3f * Mathf.PI * 2) * currentIntensity;
        
        CameraShakeManager.Instance.SetOffset(new Vector2(shakeX, shakeY));
    }
}
```

**Step 3：定义 Mixer（处理混合逻辑）**

```csharp
public class CameraShakeTrackMixer : PlayableBehaviour
{
    public override void ProcessFrame(Playable playable, FrameData info, object playerData)
    {
        // 重置
        CameraShakeManager.Instance.SetOffset(Vector2.zero);
        
        int inputCount = playable.GetInputCount();
        for (int i = 0; i < inputCount; i++)
        {
            float weight = playable.GetInputWeight(i);
            if (weight <= 0f) continue;
            
            var inputPlayable = (ScriptPlayable<CameraShakeBehaviour>)playable.GetInput(i);
            var behaviour = inputPlayable.GetBehaviour();
            double time = inputPlayable.GetTime();
            double duration = inputPlayable.GetDuration();
            
            behaviour.ProcessFrame(weight, time, duration);
        }
    }
}
```

**Step 4：定义 Track**

```csharp
[TrackColor(1f, 0.5f, 0f)]  // 轨道颜色
[TrackClipType(typeof(CameraShakeClip))]
[TrackBindingType(typeof(Camera))]  // 绑定类型（可选）
public class CameraShakeTrack : TrackAsset
{
    public override Playable CreateTrackMixer(PlayableGraph graph, GameObject go, int inputCount)
    {
        return ScriptPlayable<CameraShakeTrackMixer>.Create(graph, inputCount);
    }
}
```

### 3.2 自定义 Track 编辑器扩展

```csharp
#if UNITY_EDITOR
using UnityEditor.Timeline;

[CustomTimelineEditor(typeof(CameraShakeClip))]
public class CameraShakeClipEditor : ClipEditor
{
    // 自定义片段外观
    public override void DrawBackground(TimelineClip clip, ClipBackgroundRegion region)
    {
        var shakeClip = clip.asset as CameraShakeClip;
        if (shakeClip == null) return;
        
        // 绘制强度波形
        DrawWaveform(region.position, shakeClip.intensity, shakeClip.frequency);
    }
    
    private void DrawWaveform(Rect rect, float intensity, float frequency)
    {
        // 使用 GUI/Handles 绘制波形预览
        Handles.color = new Color(1, 0.5f, 0, 0.8f);
        int points = Mathf.RoundToInt(rect.width);
        Vector3[] positions = new Vector3[points];
        
        for (int i = 0; i < points; i++)
        {
            float t = i / (float)points;
            float y = Mathf.Sin(t * frequency * Mathf.PI * 2) * intensity;
            positions[i] = new Vector3(
                rect.x + rect.width * t,
                rect.y + rect.height * 0.5f + y * rect.height * 0.3f,
                0
            );
        }
        Handles.DrawAAPolyLine(2f, positions);
    }
}
#endif
```

---

## 四、过场动画工程实践

### 4.1 与 Cinemachine 结合

Timeline + Cinemachine 是制作过场动画的黄金搭档：

```csharp
// 运行时动态切换 Cinemachine 虚拟相机
public class CutsceneManager : MonoBehaviour
{
    [SerializeField] private PlayableDirector director;
    [SerializeField] private CinemachineVirtualCamera[] virtualCameras;
    
    // 动态换绑虚拟相机（多人游戏中角色不同）
    public void SetupCutsceneForPlayer(Transform playerTransform)
    {
        var timeline = director.playableAsset as TimelineAsset;
        foreach (var track in timeline.GetOutputTracks())
        {
            if (track is CinemachineTrack)
            {
                // 找到 LookAt 相机并重新绑定目标
                foreach (var cam in virtualCameras)
                {
                    cam.LookAt = playerTransform;
                    cam.Follow = playerTransform;
                }
            }
        }
    }
    
    // 过场动画播放完回调
    void OnCutsceneEnd(PlayableDirector d)
    {
        GameStateManager.Instance.OnCutsceneComplete();
        
        // 恢复玩家控制
        PlayerController.Instance.SetInputEnabled(true);
        
        // 恢复 UI
        UIManager.Instance.ShowHUD();
    }
}
```

### 4.2 可跳过的过场动画系统

```csharp
public class SkippableCutscene : MonoBehaviour
{
    [SerializeField] private PlayableDirector director;
    [SerializeField] private float skipHoldTime = 1.5f;
    
    private float _skipProgress = 0f;
    private bool _isSkipping = false;
    
    void Update()
    {
        if (director.state != PlayState.Playing) return;
        
        // 长按跳过
        if (Input.GetButton("Skip"))
        {
            _skipProgress += Time.deltaTime;
            UpdateSkipUI(_skipProgress / skipHoldTime);
            
            if (_skipProgress >= skipHoldTime)
                SkipCutscene();
        }
        else
        {
            _skipProgress = Mathf.Max(0, _skipProgress - Time.deltaTime * 2);
            UpdateSkipUI(_skipProgress / skipHoldTime);
        }
    }
    
    void SkipCutscene()
    {
        // 跳到最后一帧并触发所有 Signal
        director.time = director.duration;
        director.Evaluate();
        director.Stop();
        
        // 手动触发跳过事件
        GameEventSystem.Dispatch(EventType.CutsceneSkipped);
    }
    
    void UpdateSkipUI(float progress)
    {
        UIManager.Instance.SetSkipProgress(progress);
    }
}
```

### 4.3 多语言字幕系统

```csharp
// 自定义字幕 Track
[TrackColor(0.2f, 0.8f, 1f)]
[TrackClipType(typeof(SubtitleClip))]
public class SubtitleTrack : TrackAsset
{
    public override Playable CreateTrackMixer(PlayableGraph graph, GameObject go, int inputCount)
    {
        return ScriptPlayable<SubtitleMixer>.Create(graph, inputCount);
    }
}

[Serializable]
public class SubtitleClip : PlayableAsset
{
    [TextArea] public string subtitleKey;  // 本地化 Key
    public Color textColor = Color.white;
    public float fontSize = 36f;
    
    public override Playable CreatePlayable(PlayableGraph graph, GameObject owner)
    {
        var playable = ScriptPlayable<SubtitleBehaviour>.Create(graph);
        var b = playable.GetBehaviour();
        b.subtitleKey = subtitleKey;
        b.textColor = textColor;
        b.fontSize = fontSize;
        return playable;
    }
}

public class SubtitleBehaviour : PlayableBehaviour
{
    public string subtitleKey;
    public Color textColor;
    public float fontSize;
    
    public override void OnBehaviourPlay(Playable playable, FrameData info)
    {
        string text = LocalizationManager.Get(subtitleKey);
        SubtitleUI.Instance.Show(text, textColor, fontSize);
    }
    
    public override void OnBehaviourPause(Playable playable, FrameData info)
    {
        SubtitleUI.Instance.Hide();
    }
}
```

---

## 五、运行时动态控制

### 5.1 程序化创建 Timeline

```csharp
public class DynamicTimelineBuilder : MonoBehaviour
{
    public TimelineAsset BuildCombatSkillTimeline(SkillData skillData)
    {
        var timeline = ScriptableObject.CreateInstance<TimelineAsset>();
        timeline.editorSettings.fps = 30;
        
        // 添加动画轨道
        var animTrack = timeline.CreateTrack<AnimationTrack>(null, "SkillAnimation");
        var animClip = animTrack.CreateDefaultClip();
        animClip.asset = skillData.animationClip;
        animClip.start = 0;
        animClip.duration = skillData.animDuration;
        
        // 添加特效轨道
        var fxTrack = timeline.CreateTrack<ControlTrack>(null, "SkillEffect");
        var fxClip = fxTrack.CreateDefaultClip();
        fxClip.start = skillData.fxStartTime;
        fxClip.duration = skillData.fxDuration;
        
        // 添加音效信号
        var signalTrack = timeline.CreateTrack<SignalTrack>(null, "AudioSignals");
        foreach (var audioEvent in skillData.audioEvents)
        {
            var marker = signalTrack.CreateMarker<SignalEmitter>(audioEvent.time);
            marker.asset = audioEvent.signalAsset;
        }
        
        return timeline;
    }
}
```

### 5.2 Timeline 变量系统（Exposed References）

```csharp
// 在 PlayableAsset 中定义 Exposed Reference
[Serializable]
public class FollowTargetClip : PlayableAsset
{
    // ExposedReference 允许在 Director 上绑定具体对象
    public ExposedReference<Transform> targetTransform;
    public float followSpeed = 5f;
    
    public override Playable CreatePlayable(PlayableGraph graph, GameObject owner)
    {
        var playable = ScriptPlayable<FollowTargetBehaviour>.Create(graph);
        var b = playable.GetBehaviour();
        
        // 通过 ExposedPropertyTable 解析引用
        b.target = targetTransform.Resolve(graph.GetResolver());
        b.speed = followSpeed;
        return playable;
    }
}

// 运行时动态设置 Exposed Reference 值
public void SetTimelineTarget(PlayableDirector director, Transform target)
{
    // 找到所有使用 ExposedReference 的 Clip
    var timeline = director.playableAsset as TimelineAsset;
    foreach (var track in timeline.GetOutputTracks())
    {
        foreach (var clip in track.GetClips())
        {
            if (clip.asset is FollowTargetClip followClip)
            {
                // 通过 Director 设置绑定值
                director.SetReferenceValue(followClip.targetTransform.exposedName, target);
            }
        }
    }
}
```

---

## 六、性能优化

### 6.1 Timeline 性能注意事项

```csharp
// ❌ 错误：频繁在运行时创建/销毁 TimelineAsset
void BadPractice()
{
    var timeline = ScriptableObject.CreateInstance<TimelineAsset>(); // 每帧创建
    director.Play(timeline); // 每帧播放
}

// ✅ 正确：预先创建，运行时复用
public class TimelinePool : MonoBehaviour
{
    private Dictionary<string, TimelineAsset> _cache = new();
    
    public TimelineAsset Get(string key)
    {
        if (!_cache.TryGetValue(key, out var asset))
        {
            asset = Resources.Load<TimelineAsset>($"Timelines/{key}");
            _cache[key] = asset;
        }
        return asset;
    }
}
```

### 6.2 PreviewMode 关闭

Editor 模式下 Timeline 默认开启 Preview，会影响场景状态：

```csharp
#if UNITY_EDITOR
// 脚本执行完毕后关闭 Preview
[InitializeOnLoadMethod]
static void DisableAutoPreview()
{
    EditorApplication.playModeStateChanged += state =>
    {
        if (state == PlayModeStateChange.ExitingPlayMode)
        {
            // 确保 Preview 被正确关闭
            foreach (var director in FindObjectsOfType<PlayableDirector>())
                director.Stop();
        }
    };
}
#endif
```

### 6.3 分帧加载大型 Timeline

```csharp
public class LazyTimelineLoader : MonoBehaviour
{
    [SerializeField] private PlayableDirector director;
    [SerializeField] private string timelineAddress; // Addressables 地址
    
    private AsyncOperationHandle<TimelineAsset> _handle;
    
    public async Task PreloadTimeline()
    {
        _handle = Addressables.LoadAssetAsync<TimelineAsset>(timelineAddress);
        await _handle.Task;
        
        if (_handle.Status == AsyncOperationStatus.Succeeded)
        {
            director.playableAsset = _handle.Result;
            // 预热 PlayableGraph（不播放）
            director.time = 0;
            director.Evaluate();
        }
    }
    
    void OnDestroy()
    {
        if (_handle.IsValid())
            Addressables.Release(_handle);
    }
}
```

---

## 七、常见问题与解决方案

### 7.1 Timeline 动画与 Animator 冲突

**问题**：Timeline 播放结束后角色 Animator 状态异常。

**原因**：Timeline 播放期间会 override Animator 输出。

```csharp
// 解决方案：播放完毕后正确恢复 Animator 状态
director.stopped += (d) =>
{
    // 1. 恢复 Animator 到正确状态
    animator.Rebind();
    animator.Update(0);
    
    // 2. 或者手动重置 Transform
    transform.localPosition = originalPosition;
    transform.localRotation = originalRotation;
};
```

### 7.2 ExtrapolationMode 导致的状态异常

```csharp
// 根据需求选择合适的 ExtrapolationMode
director.extrapolationMode = DirectorWrapMode.None;    // 播完停止（最常用）
director.extrapolationMode = DirectorWrapMode.Hold;    // 保持最后一帧
director.extrapolationMode = DirectorWrapMode.Loop;    // 循环播放
```

### 7.3 多人游戏中 Timeline 绑定动态角色

```csharp
public class MultiplayerCutscene : MonoBehaviour
{
    public void PlayCutsceneForPlayer(PlayableDirector director, PlayerData player)
    {
        var timeline = director.playableAsset as TimelineAsset;
        
        // 遍历所有 Track，根据 Track 名称动态绑定
        foreach (var output in director.playableAsset.outputs)
        {
            if (output.streamName == "PlayerAnimation")
                director.SetGenericBinding(output.sourceObject, player.animator);
            else if (output.streamName == "PlayerTransform")
                director.SetGenericBinding(output.sourceObject, player.transform);
        }
        
        director.Play();
    }
}
```

---

## 总结

| 场景 | 推荐方案 |
|------|---------|
| 过场动画 | Timeline + Cinemachine + Signal |
| 技能演出 | 自定义 Track + 程序化构建 |
| UI 动效 | Timeline + Animation Track (UI) |
| 音频同步 | Signal Track + AudioSource |
| 多语言字幕 | 自定义 Subtitle Track |
| 运行时动态 | ExposedReference + SetGenericBinding |

Timeline 是 Unity 中连接「动画」与「游戏逻辑」的桥梁。掌握 PlayableGraph 原理 + 自定义 Track 开发，能让你构建出灵活、高效的演出系统，满足从 Demo 到 AAA 级商业项目的各种需求。
