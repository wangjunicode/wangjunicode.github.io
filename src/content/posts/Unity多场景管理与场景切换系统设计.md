---
title: Unity多场景管理与场景切换系统设计
published: 2026-03-31
description: 深度解析Unity多场景管理架构，涵盖场景叠加加载（Additive Loading）策略、Bootstrap持久场景模式、场景切换过渡效果（淡黑/Loading画面）、场景间数据传递、异步加载进度监控、大世界流式场景切换，以及场景管理器与Addressables的集成方案。
tags: [Unity, 场景管理, 多场景, 异步加载, 游戏开发]
category: 游戏开发
draft: false
---

## 一、场景架构设计

```
多场景叠加架构：

Bootstrap (永久场景，不卸载)
├── GameManager
├── AudioManager
├── InputManager
└── NetworkManager

↓ 叠加加载

GameScene (主游戏场景)
├── 地形/环境
├── NPC/怪物
└── 玩家对象

↓ 叠加加载

UIScene (UI专用场景)
├── HUD
├── 弹窗层
└── 过渡层
```

---

## 二、场景管理器

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// 场景配置
/// </summary>
[CreateAssetMenu(fileName = "SceneConfig", menuName = "Game/Scene Config")]
public class SceneConfig : ScriptableObject
{
    public string SceneName;
    public string DisplayName;           // 加载界面显示名称
    public Sprite LoadingBackground;     // 加载画面背景
    public string[] AdditiveScenes;      // 需要同时加载的附加场景
    public bool ShowLoadingScreen = true;
    public float MinLoadingTime = 1.5f;  // 最短加载时间（展示Loading画面用）
}

/// <summary>
/// 场景管理器（支持叠加加载、过渡效果、进度监控）
/// </summary>
public class SceneManager_ : MonoBehaviour
{
    private static SceneManager_ instance;
    public static SceneManager_ Instance => instance;

    [Header("场景配置")]
    [SerializeField] private SceneConfig[] sceneConfigs;
    [SerializeField] private string bootstrapSceneName = "Bootstrap";
    [SerializeField] private string uiSceneName = "UIScene";

    [Header("过渡配置")]
    [SerializeField] private float fadeInDuration = 0.5f;
    [SerializeField] private float fadeOutDuration = 0.5f;

    private Dictionary<string, SceneConfig> configMap 
        = new Dictionary<string, SceneConfig>();
    
    // 当前已加载的游戏场景（不含Bootstrap和UI）
    private string currentGameScene;
    
    // 事件
    public event Action<float> OnLoadingProgress;       // 0-1
    public event Action<string> OnSceneLoadStart;
    public event Action<string> OnSceneLoadComplete;

    void Awake()
    {
        instance = this;
        DontDestroyOnLoad(gameObject);
        
        foreach (var cfg in sceneConfigs)
            configMap[cfg.SceneName] = cfg;
    }

    /// <summary>
    /// 加载游戏场景（主接口）
    /// </summary>
    public void LoadScene(string sceneName, object transitionData = null)
    {
        if (!configMap.ContainsKey(sceneName))
        {
            Debug.LogError($"[SceneManager] Unknown scene: {sceneName}");
            return;
        }
        
        // 存储过渡数据（供新场景读取）
        if (transitionData != null)
            SceneTransitionData.Set(transitionData);
        
        StartCoroutine(LoadSceneCoroutine(sceneName));
    }

    IEnumerator LoadSceneCoroutine(string sceneName)
    {
        var config = configMap[sceneName];
        
        OnSceneLoadStart?.Invoke(sceneName);
        
        // 1. 淡出当前场景
        yield return StartCoroutine(FadeOut());
        
        // 2. 显示加载界面
        if (config.ShowLoadingScreen)
        {
            LoadingScreenManager.Instance?.Show(config.DisplayName, config.LoadingBackground);
        }
        
        float startTime = Time.realtimeSinceStartup;
        
        // 3. 卸载当前游戏场景
        if (!string.IsNullOrEmpty(currentGameScene))
        {
            var unloadOp = SceneManagement.SceneManager.UnloadSceneAsync(currentGameScene);
            yield return unloadOp;
            
            // 强制 GC
            System.GC.Collect();
            yield return Resources.UnloadUnusedAssets();
        }
        
        // 4. 加载新场景（异步，不激活）
        var ops = new List<AsyncOperation>();
        
        var mainOp = SceneManagement.SceneManager.LoadSceneAsync(
            sceneName, LoadSceneMode.Additive);
        mainOp.allowSceneActivation = false;
        ops.Add(mainOp);
        
        // 同时加载附加场景
        if (config.AdditiveScenes != null)
        {
            foreach (var addScene in config.AdditiveScenes)
            {
                var addOp = SceneManagement.SceneManager.LoadSceneAsync(
                    addScene, LoadSceneMode.Additive);
                addOp.allowSceneActivation = false;
                ops.Add(addOp);
            }
        }
        
        // 5. 等待加载（汇报进度）
        while (true)
        {
            float progress = 0;
            bool allDone = true;
            
            foreach (var op in ops)
            {
                progress += op.progress;
                if (op.progress < 0.9f) allDone = false;
            }
            
            progress /= ops.Count;
            OnLoadingProgress?.Invoke(progress / 0.9f);
            LoadingScreenManager.Instance?.SetProgress(progress / 0.9f);
            
            if (allDone) break;
            
            yield return null;
        }
        
        // 6. 确保最短加载时间
        float elapsed = Time.realtimeSinceStartup - startTime;
        if (elapsed < config.MinLoadingTime)
            yield return new WaitForSecondsRealtime(config.MinLoadingTime - elapsed);
        
        // 7. 激活场景
        foreach (var op in ops)
            op.allowSceneActivation = true;
        
        yield return null; // 等待一帧
        
        // 设置活动场景
        var newScene = SceneManagement.SceneManager.GetSceneByName(sceneName);
        SceneManagement.SceneManager.SetActiveScene(newScene);
        
        currentGameScene = sceneName;
        
        // 8. 隐藏加载界面 + 淡入
        if (config.ShowLoadingScreen)
        {
            LoadingScreenManager.Instance?.Hide();
            yield return new WaitForSeconds(0.3f);
        }
        
        yield return StartCoroutine(FadeIn());
        
        OnSceneLoadComplete?.Invoke(sceneName);
        OnLoadingProgress?.Invoke(1f);
        
        Debug.Log($"[SceneManager] Scene '{sceneName}' loaded successfully");
    }

    IEnumerator FadeOut()
    {
        yield return TransitionManager.Instance?.FadeOut(fadeOutDuration);
    }

    IEnumerator FadeIn()
    {
        yield return TransitionManager.Instance?.FadeIn(fadeInDuration);
    }
}

/// <summary>
/// 场景间数据传递（解耦场景依赖）
/// </summary>
public static class SceneTransitionData
{
    private static object data;
    
    public static void Set(object obj) => data = obj;
    
    public static T Get<T>()
    {
        if (data is T typedData)
        {
            data = null; // 一次性消费
            return typedData;
        }
        return default;
    }
    
    public static bool Has() => data != null;
    public static void Clear() => data = null;
}
```

---

## 三、过渡效果管理器

```csharp
/// <summary>
/// 场景过渡效果（全屏淡黑/淡白/圆形收缩）
/// </summary>
public class TransitionManager : MonoBehaviour
{
    private static TransitionManager instance;
    public static TransitionManager Instance => instance;

    [SerializeField] private CanvasGroup fadePanel;
    [SerializeField] private UnityEngine.UI.Image fadeImage;

    void Awake() { instance = this; DontDestroyOnLoad(gameObject); }

    public IEnumerator FadeOut(float duration)
    {
        fadePanel.gameObject.SetActive(true);
        float t = 0;
        while (t < duration)
        {
            t += Time.unscaledDeltaTime;
            fadePanel.alpha = Mathf.Lerp(0, 1, t / duration);
            yield return null;
        }
        fadePanel.alpha = 1f;
    }

    public IEnumerator FadeIn(float duration)
    {
        float t = 0;
        while (t < duration)
        {
            t += Time.unscaledDeltaTime;
            fadePanel.alpha = Mathf.Lerp(1, 0, t / duration);
            yield return null;
        }
        fadePanel.alpha = 0f;
        fadePanel.gameObject.SetActive(false);
    }
}
```

---

## 四、Bootstrap 场景模式

```csharp
/// <summary>
/// Bootstrap 入口（游戏首个加载的场景）
/// 负责初始化所有全局系统，然后进入主菜单
/// </summary>
public class BootstrapLoader : MonoBehaviour
{
    [SerializeField] private string firstScene = "MainMenu";
    [SerializeField] private float minBootTime = 2f; // 最短启动时间

    IEnumerator Start()
    {
        float startTime = Time.time;
        
        // 初始化各系统（可加进度反馈）
        yield return InitializeSystems();
        
        // 确保最短启动时间（用于显示品牌Logo）
        float elapsed = Time.time - startTime;
        if (elapsed < minBootTime)
            yield return new WaitForSeconds(minBootTime - elapsed);
        
        // 加载第一个游戏场景
        SceneManager_.Instance.LoadScene(firstScene);
    }

    IEnumerator InitializeSystems()
    {
        // 按顺序初始化（有依赖关系）
        yield return AudioManager.Instance?.Initialize();
        yield return NetworkManager.Instance?.Initialize();
        yield return PlayerDataService.LoadLocalData();
        
        Debug.Log("[Bootstrap] All systems initialized");
    }
}
```

---

## 五、场景管理最佳实践

| 原则 | 说明 |
|------|------|
| Bootstrap常驻 | 全局系统挂在Bootstrap场景，DontDestroyOnLoad |
| UI独立场景 | UI系统单独场景，便于维护和切换 |
| 异步不阻塞 | 所有场景加载使用 LoadSceneAsync |
| 最短加载时间 | 防止闪屏，加载太快不显示Loading画面 |
| 场景切换前GC | UnloadUnused + System.GC.Collect |
| 数据传递解耦 | 使用 SceneTransitionData 而非静态变量 |
