---
title: Unity多场景异步加载与无缝过渡系统完全指南：Scene管理、加载进度与过渡动画深度实践
published: 2026-05-09
description: 深入解析Unity多场景异步加载系统架构，涵盖SceneManager异步API、加载进度管理、过渡动画（黑屏淡入淡出、Loading界面）、Additive加载策略、场景预加载与卸载优化，完整工程实践。
tags: [Unity, 场景管理, 异步加载, 性能优化, 游戏开发, UI系统]
category: Unity核心系统
draft: false
---

# Unity多场景异步加载与无缝过渡系统完全指南：Scene管理、加载进度与过渡动画深度实践

## 1. 多场景架构设计

现代游戏通常采用多场景叠加架构（Additive Scenes），将游戏内容分散到多个场景单元，实现流式加载与按需卸载。

### 1.1 场景分层架构

```
┌─────────────────────────────────────────────────────┐
│                  Persistent Scene                    │
│  （常驻：GameManager/AudioManager/UIManager等）        │
└──────────────────────┬──────────────────────────────┘
                       │ 叠加加载(Additive)
          ┌────────────┴───────────────────┐
          │                                │
┌─────────▼──────────┐       ┌─────────────▼──────────┐
│   Gameplay Scene    │       │    UI Scene             │
│ （地图、角色、光照） │       │  （HUD、背包、技能栏）   │
└────────────────────┘       └────────────────────────┘
          │ 子区块流式加载
┌─────────▼──────────────────────────────────────────┐
│  Chunk_0_0  Chunk_0_1  Chunk_1_0 ... (按需加载/卸载)  │
└────────────────────────────────────────────────────┘
```

### 1.2 场景类型定义

```csharp
// SceneDefinitions.cs
public enum SceneType
{
    Persistent,   // 常驻场景，生命周期=整个游戏
    Main,         // 主场景（同时只存在一个）
    Additive,     // 叠加场景（可多个同时存在）
    Chunk,        // 流式区块场景
    Preloaded,    // 预加载场景（后台加载，暂不激活）
}

[System.Serializable]
public class SceneConfig
{
    public string SceneName;
    public string ScenePath;        // Build Settings中的路径
    public SceneType Type;
    public bool   UnloadOnLeave;    // 离开时是否卸载
    public float  PreloadDistance;  // 预加载触发距离（Chunk类型）
}
```

## 2. 场景管理器核心

```csharp
// SceneTransitionManager.cs
using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;

public class SceneTransitionManager : MonoBehaviour
{
    private static SceneTransitionManager _instance;
    public static SceneTransitionManager Instance => _instance;

    [Header("过渡配置")]
    [SerializeField] private SceneTransitionUI _transitionUI;
    [SerializeField] private float _minLoadingTime = 0.5f; // 最短加载时间（避免闪烁）

    // 当前已加载的场景集合
    private readonly HashSet<string> _loadedScenes = new();
    private bool _isTransitioning;

    public bool IsTransitioning => _isTransitioning;

    // 加载进度事件
    public event Action<string, float> OnSceneLoadProgress;
    public event Action<string>        OnSceneLoaded;
    public event Action<string>        OnSceneUnloaded;

    private void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);

        // 记录初始已加载场景
        for (int i = 0; i < SceneManager.sceneCount; i++)
            _loadedScenes.Add(SceneManager.GetSceneAt(i).name);
    }

    /// <summary>
    /// 主场景切换（带过渡动画，会卸载当前主场景）
    /// </summary>
    public async Task TransitionToAsync(
        string sceneName,
        SceneTransitionType transitionType = SceneTransitionType.Fade,
        Action onMidpoint = null)
    {
        if (_isTransitioning)
        {
            Debug.LogWarning("[SceneManager] 场景过渡进行中，忽略新请求");
            return;
        }
        _isTransitioning = true;

        try
        {
            // 1. 播放过渡动画（淡出）
            await _transitionUI.PlayOutAsync(transitionType);

            // 2. 并行：卸载旧主场景 + 加载新场景
            string oldMain = GetCurrentMainScene();
            var loadTask  = LoadSceneAsync(sceneName, LoadSceneMode.Additive);
            var unloadTask = oldMain != null
                ? UnloadSceneAsync(oldMain)
                : Task.CompletedTask;

            // 确保最短加载时间（防止Loading界面闪烁）
            var minTimeTask = Task.Delay((int)(_minLoadingTime * 1000));
            await Task.WhenAll(loadTask, unloadTask, minTimeTask);

            // 3. 中途回调（可用于初始化新场景的数据）
            onMidpoint?.Invoke();

            // 4. 激活新场景
            ActivateScene(sceneName);

            // 5. 播放过渡动画（淡入）
            await _transitionUI.PlayInAsync(transitionType);
        }
        finally
        {
            _isTransitioning = false;
        }
    }

    /// <summary>
    /// 叠加加载场景（不影响当前场景，不播放过渡动画）
    /// </summary>
    public async Task LoadAdditiveAsync(string sceneName)
    {
        if (_loadedScenes.Contains(sceneName)) return;
        await LoadSceneAsync(sceneName, LoadSceneMode.Additive);
    }

    /// <summary>
    /// 卸载叠加场景
    /// </summary>
    public async Task UnloadAdditiveAsync(string sceneName)
    {
        if (!_loadedScenes.Contains(sceneName)) return;
        await UnloadSceneAsync(sceneName);
    }

    private async Task LoadSceneAsync(string sceneName, LoadSceneMode mode)
    {
        if (_loadedScenes.Contains(sceneName)) return;

        var op = SceneManager.LoadSceneAsync(sceneName, mode);
        op.allowSceneActivation = false; // 先不激活，等加载完成后手动激活

        while (op.progress < 0.9f) // Unity异步加载在0.9时暂停等待allowSceneActivation
        {
            OnSceneLoadProgress?.Invoke(sceneName, op.progress / 0.9f);
            await Task.Yield();
        }

        OnSceneLoadProgress?.Invoke(sceneName, 1f);
        op.allowSceneActivation = true;

        // 等待激活完成
        while (!op.isDone) await Task.Yield();

        _loadedScenes.Add(sceneName);
        OnSceneLoaded?.Invoke(sceneName);
    }

    private async Task UnloadSceneAsync(string sceneName)
    {
        if (!_loadedScenes.Contains(sceneName)) return;

        var op = SceneManager.UnloadSceneAsync(sceneName);
        while (!op.isDone) await Task.Yield();

        _loadedScenes.Remove(sceneName);
        OnSceneUnloaded?.Invoke(sceneName);

        // 卸载后触发GC（可选，大场景卸载时释放内存）
        await Resources.UnloadUnusedAssets().ToTask();
        GC.Collect();
    }

    private void ActivateScene(string sceneName)
    {
        var scene = SceneManager.GetSceneByName(sceneName);
        if (scene.IsValid()) SceneManager.SetActiveScene(scene);
    }

    private string GetCurrentMainScene()
    {
        for (int i = 0; i < SceneManager.sceneCount; i++)
        {
            var scene = SceneManager.GetSceneAt(i);
            // 排除常驻场景（通常名为"Persistent"）
            if (scene.name != "Persistent" && _loadedScenes.Contains(scene.name))
                return scene.name;
        }
        return null;
    }
}
```

## 3. 场景过渡UI系统

```csharp
// SceneTransitionUI.cs
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using DG.Tweening; // DOTween

public enum SceneTransitionType
{
    Fade,         // 黑屏淡入淡出
    Loading,      // Loading进度条界面
    Wipe,         // 遮罩擦除效果
    CircleClose,  // 圆形收缩（游戏风格）
}

public class SceneTransitionUI : MonoBehaviour
{
    [Header("Fade组件")]
    [SerializeField] private CanvasGroup _fadeOverlay;
    [SerializeField] private float _fadeDuration = 0.4f;

    [Header("Loading界面")]
    [SerializeField] private GameObject  _loadingPanel;
    [SerializeField] private Slider      _progressBar;
    [SerializeField] private Text        _progressText;
    [SerializeField] private Text        _tipsText;
    [SerializeField] private string[]    _loadingTips;

    [Header("圆形收缩")]
    [SerializeField] private Material    _circleMaterial;
    [SerializeField] private Image       _circleImage;

    private static readonly int ShaderRadiusProp = Shader.PropertyToID("_Radius");

    private void Awake()
    {
        // 确保初始状态完全透明
        if (_fadeOverlay != null) _fadeOverlay.alpha = 0f;
        if (_loadingPanel != null) _loadingPanel.SetActive(false);
    }

    public async Task PlayOutAsync(SceneTransitionType type)
    {
        switch (type)
        {
            case SceneTransitionType.Fade:
                await FadeOutAsync();
                break;
            case SceneTransitionType.Loading:
                await FadeOutAsync();
                ShowLoadingPanel(true);
                break;
            case SceneTransitionType.CircleClose:
                await CircleCloseAsync();
                break;
        }
    }

    public async Task PlayInAsync(SceneTransitionType type)
    {
        switch (type)
        {
            case SceneTransitionType.Fade:
                await FadeInAsync();
                break;
            case SceneTransitionType.Loading:
                ShowLoadingPanel(false);
                await FadeInAsync();
                break;
            case SceneTransitionType.CircleClose:
                await CircleOpenAsync();
                break;
        }
    }

    // ─── 进度条更新（由SceneTransitionManager回调）─────────────────────
    public void UpdateProgress(float progress)
    {
        if (_progressBar  != null) _progressBar.value = progress;
        if (_progressText != null) _progressText.text = $"{(int)(progress * 100)}%";
    }

    // ─── 淡入淡出 ────────────────────────────────────────────────────────
    private Task FadeOutAsync()
    {
        var tcs = new TaskCompletionSource<bool>();
        _fadeOverlay.gameObject.SetActive(true);
        _fadeOverlay
            .DOFade(1f, _fadeDuration)
            .OnComplete(() => tcs.SetResult(true));
        return tcs.Task;
    }

    private Task FadeInAsync()
    {
        var tcs = new TaskCompletionSource<bool>();
        _fadeOverlay
            .DOFade(0f, _fadeDuration)
            .OnComplete(() =>
            {
                _fadeOverlay.gameObject.SetActive(false);
                tcs.SetResult(true);
            });
        return tcs.Task;
    }

    // ─── 圆形收缩 ────────────────────────────────────────────────────────
    private Task CircleCloseAsync()
    {
        var tcs = new TaskCompletionSource<bool>();
        _circleImage.gameObject.SetActive(true);
        DOTween.To(
            () => _circleMaterial.GetFloat(ShaderRadiusProp),
            v  => _circleMaterial.SetFloat(ShaderRadiusProp, v),
            0f, _fadeDuration)
            .OnComplete(() => tcs.SetResult(true));
        return tcs.Task;
    }

    private Task CircleOpenAsync()
    {
        var tcs = new TaskCompletionSource<bool>();
        DOTween.To(
            () => _circleMaterial.GetFloat(ShaderRadiusProp),
            v  => _circleMaterial.SetFloat(ShaderRadiusProp, v),
            1f, _fadeDuration)
            .OnComplete(() =>
            {
                _circleImage.gameObject.SetActive(false);
                tcs.SetResult(true);
            });
        return tcs.Task;
    }

    private void ShowLoadingPanel(bool show)
    {
        if (_loadingPanel == null) return;
        _loadingPanel.SetActive(show);
        if (show && _tipsText != null && _loadingTips?.Length > 0)
        {
            _tipsText.text = _loadingTips[
                UnityEngine.Random.Range(0, _loadingTips.Length)];
        }
    }
}
```

## 4. 场景预加载系统

```csharp
// ScenePreloader.cs
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;

public class ScenePreloader : MonoBehaviour
{
    private readonly Dictionary<string, AsyncOperation> _preloadOps = new();
    private readonly Dictionary<string, CancellationTokenSource> _cancelTokens = new();

    public SceneTransitionManager TransitionManager { get; set; }

    /// <summary>
    /// 后台预加载场景（不激活）
    /// </summary>
    public void Preload(string sceneName, Action<float> onProgress = null)
    {
        if (_preloadOps.ContainsKey(sceneName)) return;

        var cts = new CancellationTokenSource();
        _cancelTokens[sceneName] = cts;

        _ = PreloadAsync(sceneName, onProgress, cts.Token);
    }

    private async Task PreloadAsync(
        string sceneName, Action<float> onProgress, CancellationToken ct)
    {
        var op = SceneManager.LoadSceneAsync(sceneName, LoadSceneMode.Additive);
        op.allowSceneActivation = false;
        _preloadOps[sceneName] = op;

        while (op.progress < 0.9f && !ct.IsCancellationRequested)
        {
            onProgress?.Invoke(op.progress / 0.9f);
            await Task.Yield();
        }

        if (ct.IsCancellationRequested)
        {
            // 取消预加载：激活后立即卸载
            op.allowSceneActivation = true;
            while (!op.isDone) await Task.Yield();
            await SceneManager.UnloadSceneAsync(sceneName).ToTask();
            _preloadOps.Remove(sceneName);
            return;
        }

        onProgress?.Invoke(1f);
        Debug.Log($"[ScenePreloader] {sceneName} 预加载完成（未激活）");
    }

    /// <summary>
    /// 激活已预加载的场景（快速切换，无需重新加载）
    /// </summary>
    public async Task ActivatePreloadedAsync(string sceneName)
    {
        if (!_preloadOps.TryGetValue(sceneName, out var op))
        {
            Debug.LogWarning($"[ScenePreloader] {sceneName} 未预加载，执行普通加载");
            await TransitionManager.LoadAdditiveAsync(sceneName);
            return;
        }

        // 激活预加载场景
        op.allowSceneActivation = true;
        while (!op.isDone) await Task.Yield();

        _preloadOps.Remove(sceneName);
        _cancelTokens.Remove(sceneName);
        Debug.Log($"[ScenePreloader] {sceneName} 预加载场景已激活");
    }

    /// <summary>
    /// 取消预加载
    /// </summary>
    public void CancelPreload(string sceneName)
    {
        if (!_cancelTokens.TryGetValue(sceneName, out var cts)) return;
        cts.Cancel();
        _cancelTokens.Remove(sceneName);
    }
}
```

## 5. 流式区块场景管理

```csharp
// ChunkSceneStreamingManager.cs
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine;

public class ChunkSceneStreamingManager : MonoBehaviour
{
    [SerializeField] private float _loadDistance   = 100f;
    [SerializeField] private float _unloadDistance = 150f;
    [SerializeField] private int   _chunkSize      = 50;
    [SerializeField] private Transform _playerTransform;

    private readonly HashSet<Vector2Int> _loadedChunks   = new();
    private readonly HashSet<Vector2Int> _loadingChunks  = new();
    private readonly HashSet<Vector2Int> _unloadingChunks = new();

    private void Update()
    {
        if (_playerTransform == null) return;
        UpdateChunkStreaming();
    }

    private async void UpdateChunkStreaming()
    {
        Vector3 playerPos = _playerTransform.position;
        int loadRadius   = Mathf.CeilToInt(_loadDistance   / _chunkSize);
        int unloadRadius = Mathf.CeilToInt(_unloadDistance / _chunkSize);

        Vector2Int playerChunk = WorldToChunkCoord(playerPos);

        // 查找需要加载的区块
        for (int x = -loadRadius; x <= loadRadius; x++)
        {
            for (int z = -loadRadius; z <= loadRadius; z++)
            {
                var chunkCoord = new Vector2Int(playerChunk.x + x, playerChunk.y + z);
                float dist = Vector2.Distance(
                    new Vector2(playerPos.x, playerPos.z),
                    new Vector2(chunkCoord.x * _chunkSize, chunkCoord.y * _chunkSize));

                if (dist <= _loadDistance
                    && !_loadedChunks.Contains(chunkCoord)
                    && !_loadingChunks.Contains(chunkCoord))
                {
                    await LoadChunkAsync(chunkCoord);
                }
            }
        }

        // 查找需要卸载的区块
        var toUnload = new List<Vector2Int>();
        foreach (var chunk in _loadedChunks)
        {
            float dist = Vector2.Distance(
                new Vector2(playerPos.x, playerPos.z),
                new Vector2(chunk.x * _chunkSize, chunk.y * _chunkSize));

            if (dist > _unloadDistance && !_unloadingChunks.Contains(chunk))
                toUnload.Add(chunk);
        }

        foreach (var chunk in toUnload)
            await UnloadChunkAsync(chunk);
    }

    private async Task LoadChunkAsync(Vector2Int chunkCoord)
    {
        string sceneName = GetChunkSceneName(chunkCoord);
        _loadingChunks.Add(chunkCoord);

        try
        {
            await SceneTransitionManager.Instance.LoadAdditiveAsync(sceneName);
            _loadedChunks.Add(chunkCoord);
        }
        catch (System.Exception ex)
        {
            Debug.LogWarning($"[ChunkStreaming] 加载 {sceneName} 失败: {ex.Message}");
        }
        finally
        {
            _loadingChunks.Remove(chunkCoord);
        }
    }

    private async Task UnloadChunkAsync(Vector2Int chunkCoord)
    {
        string sceneName = GetChunkSceneName(chunkCoord);
        _unloadingChunks.Add(chunkCoord);

        try
        {
            await SceneTransitionManager.Instance.UnloadAdditiveAsync(sceneName);
            _loadedChunks.Remove(chunkCoord);
        }
        finally
        {
            _unloadingChunks.Remove(chunkCoord);
        }
    }

    private Vector2Int WorldToChunkCoord(Vector3 worldPos)
        => new Vector2Int(
            Mathf.FloorToInt(worldPos.x / _chunkSize),
            Mathf.FloorToInt(worldPos.z / _chunkSize));

    private string GetChunkSceneName(Vector2Int coord)
        => $"Chunk_{coord.x}_{coord.y}";
}
```

## 6. 场景间数据传递

```csharp
// SceneDataBus.cs
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 场景间数据传递总线（替代DontDestroyOnLoad传值）
/// </summary>
public static class SceneDataBus
{
    private static readonly Dictionary<string, object> _data = new();

    public static void Set<T>(string key, T value) where T : class
        => _data[key] = value;

    public static T Get<T>(string key) where T : class
    {
        if (_data.TryGetValue(key, out var val) && val is T typed)
            return typed;
        return null;
    }

    public static bool TryGet<T>(string key, out T value) where T : class
    {
        if (_data.TryGetValue(key, out var val) && val is T typed)
        {
            value = typed;
            return true;
        }
        value = null;
        return false;
    }

    public static void Remove(string key) => _data.Remove(key);

    /// <summary>场景加载完成后清除临时数据（保留持久数据）</summary>
    public static void ClearTransient()
    {
        var transientKeys = new List<string>();
        foreach (var kv in _data)
            if (kv.Key.StartsWith("transient_"))
                transientKeys.Add(kv.Key);
        foreach (var k in transientKeys) _data.Remove(k);
    }
}

// 使用示例：主城传送到副本
// 发送方（主城场景）：
// SceneDataBus.Set("transient_dungeonParam", new DungeonParam { DungeonId = 101, Difficulty = 3 });
// await SceneTransitionManager.Instance.TransitionToAsync("Dungeon_101");
//
// 接收方（副本场景Awake/Start中）：
// var param = SceneDataBus.Get<DungeonParam>("transient_dungeonParam");
// SceneDataBus.Remove("transient_dungeonParam");
```

## 7. 场景加载异常处理与回退

```csharp
// SceneLoadingErrorHandler.cs
using System;
using System.Threading.Tasks;
using UnityEngine;

public static class SceneLoadingErrorHandler
{
    private const string FallbackScene = "MainMenu";
    private const int MaxRetries = 2;

    /// <summary>
    /// 带重试与回退的安全场景切换
    /// </summary>
    public static async Task SafeTransitionAsync(
        string targetScene,
        SceneTransitionType transitionType = SceneTransitionType.Fade)
    {
        int attempts = 0;
        while (attempts < MaxRetries)
        {
            try
            {
                await SceneTransitionManager.Instance
                    .TransitionToAsync(targetScene, transitionType);
                return; // 成功
            }
            catch (Exception ex)
            {
                attempts++;
                Debug.LogError(
                    $"[SceneLoader] 加载 {targetScene} 失败 " +
                    $"(第{attempts}次): {ex.Message}");

                if (attempts < MaxRetries)
                {
                    await Task.Delay(500); // 等待500ms再重试
                }
            }
        }

        // 多次重试失败：回退到主菜单
        Debug.LogError($"[SceneLoader] {targetScene} 加载失败超过{MaxRetries}次，回退到{FallbackScene}");
        try
        {
            await SceneTransitionManager.Instance
                .TransitionToAsync(FallbackScene, SceneTransitionType.Fade);
        }
        catch (Exception ex)
        {
            Debug.LogError($"[SceneLoader] 回退场景也失败: {ex.Message}");
            // 最后手段：强制同步加载
            UnityEngine.SceneManagement.SceneManager.LoadScene(FallbackScene);
        }
    }
}
```

## 8. AsyncOperation扩展：Task桥接

```csharp
// AsyncOperationExtensions.cs
using System.Threading.Tasks;
using UnityEngine;

public static class AsyncOperationExtensions
{
    /// <summary>将AsyncOperation转换为Task</summary>
    public static Task ToTask(this AsyncOperation op)
    {
        var tcs = new TaskCompletionSource<bool>();
        op.completed += _ => tcs.TrySetResult(true);
        if (op.isDone) tcs.TrySetResult(true);
        return tcs.Task;
    }
}
```

## 9. 场景加载性能分析

```csharp
// SceneLoadProfiler.cs
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public class SceneLoadProfiler : MonoBehaviour
{
    [Serializable]
    public struct LoadRecord
    {
        public string SceneName;
        public float  LoadTimeMs;
        public int    ObjectCount;
        public long   MemoryDeltaBytes;
        public DateTime LoadedAt;
    }

    private readonly List<LoadRecord> _records = new();
    private long _memBefore;

    private void OnEnable()
    {
        SceneManager.sceneLoaded   += OnSceneLoaded;
        SceneManager.sceneUnloaded += OnSceneUnloaded;
    }

    private void OnDisable()
    {
        SceneManager.sceneLoaded   -= OnSceneLoaded;
        SceneManager.sceneUnloaded -= OnSceneUnloaded;
    }

    private float _loadStartTime;

    public void RecordLoadStart()
    {
        _loadStartTime = Time.realtimeSinceStartup;
        _memBefore     = GC.GetTotalMemory(false);
    }

    private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
    {
        float elapsed = (Time.realtimeSinceStartup - _loadStartTime) * 1000f;
        long  memAfter = GC.GetTotalMemory(false);

        var record = new LoadRecord
        {
            SceneName      = scene.name,
            LoadTimeMs     = elapsed,
            ObjectCount    = scene.rootCount,
            MemoryDeltaBytes = memAfter - _memBefore,
            LoadedAt       = DateTime.Now,
        };
        _records.Add(record);

        Debug.Log($"[SceneProfiler] {scene.name} 加载耗时: {elapsed:F1}ms, " +
                  $"根对象数: {scene.rootCount}, " +
                  $"内存变化: {(memAfter - _memBefore) / 1024f:F1}KB");
    }

    private void OnSceneUnloaded(Scene scene)
    {
        Debug.Log($"[SceneProfiler] {scene.name} 已卸载");
    }

    public void PrintSummary()
    {
        Debug.Log("=== 场景加载汇总 ===");
        foreach (var r in _records)
        {
            Debug.Log($"  {r.SceneName}: {r.LoadTimeMs:F1}ms, " +
                      $"{r.MemoryDeltaBytes / 1024f:F1}KB");
        }
    }
}
```

## 10. 圆形收缩过渡Shader

```glsl
// CircleTransition.shader
Shader "Game/UI/CircleTransition"
{
    Properties
    {
        _Color    ("Color", Color) = (0,0,0,1)
        _Radius   ("Radius", Range(0, 1.5)) = 1.0
        _Softness ("Softness", Range(0, 0.1)) = 0.02
    }
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Overlay+100" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZWrite Off ZTest Always

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f    { float4 pos : SV_POSITION;  float2 uv : TEXCOORD0; };

            float4 _Color;
            float  _Radius;
            float  _Softness;

            v2f vert(appdata v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv  = v.uv - 0.5; // 中心化UV：[-0.5, 0.5]
                return o;
            }

            fixed4 frag(v2f i) : SV_Target
            {
                float dist = length(i.uv);
                float alpha = 1.0 - smoothstep(_Radius - _Softness, _Radius + _Softness, dist);
                return fixed4(_Color.rgb, alpha * _Color.a);
            }
            ENDCG
        }
    }
}
```

## 11. 最佳实践总结

| 实践要点 | 说明 |
|----------|------|
| 常驻场景分离 | 始终保留Persistent Scene存放全局Manager，避免DontDestroyOnLoad滥用 |
| allowSceneActivation控制 | 设为false可先加载到内存但不激活，配合预加载策略实现快速切换 |
| 最短加载时间 | 设置0.3~0.5s的最短显示时间，防止Loading界面一闪而过 |
| 弧长参数化进度 | AsyncOperation.progress值0~0.9对应真实加载，0.9~1.0是激活过程，注意换算 |
| 资源卸载时机 | 卸载场景后调用Resources.UnloadUnusedAssets()，但避免频繁调用（耗时高） |
| 预加载触发距离 | 流式区块应在进入距离外1.5~2x处开始预加载，保留缓冲时间 |
| 数据传递用总线 | 场景间传值用SceneDataBus，避免单例或PlayerPrefs临时存值 |
| 错误回退机制 | 场景加载失败必须有回退到主菜单的保险逻辑 |
| 加载进度可视化 | Loading界面展示实际进度（0~100%），避免假进度条影响体验 |
| Task异步统一 | 统一用async/await取代Coroutine，SceneManager.LoadSceneAsync封装成Task桥接 |

---

> 本文代码基于 Unity 2022.3 LTS，使用 DOTween 做 Tween 动画，Unity.SceneManagement 异步加载在 Unity 2021+ 行为一致。流式区块方案需配合 World Composition 或自定义场景注册表，在 Build Settings 中预先添加所有区块场景。
