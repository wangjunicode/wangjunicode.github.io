---
title: 游戏广告系统集成：从SDK接入到变现策略优化
published: 2026-03-31
description: 全面解析手游广告变现的工程实现，涵盖 AdMob/Unity Ads/IronSource 聚合接入、激励视频/插屏/横幅广告的生命周期管理、广告填充率优化、eCPM 瀑布流配置、广告频控与用户体验平衡，以及 A/B 测试驱动的广告策略调优。
tags: [Unity, 广告系统, 移动游戏, 变现, AdMob]
category: 游戏商业化
draft: false
---

## 一、广告类型与适用场景

| 广告类型 | 适用场景 | eCPM范围 | 用户体验影响 |
|----------|----------|----------|------------|
| 激励视频 | 获得额外生命/道具/货币 | $10-50 | 低（主动观看）|
| 插屏全屏 | 关卡间隔/自然停顿点 | $3-15 | 中（被动触发）|
| 横幅广告 | 常驻展示（大厅界面） | $0.5-2 | 低（非侵入）|
| 原生广告 | 融入游戏内容的广告 | $5-20 | 最低 |
| App Open | APP 启动/前后台切换 | $5-20 | 中 |

---

## 二、广告 SDK 抽象层设计

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 广告加载状态
/// </summary>
public enum AdLoadState
{
    Idle,       // 未加载
    Loading,    // 加载中
    Ready,      // 已加载，可以展示
    Showing,    // 展示中
    Failed      // 加载/展示失败
}

/// <summary>
/// 广告接口（适配器模式）
/// </summary>
public interface IAdProvider
{
    string ProviderName { get; }
    bool IsInitialized { get; }
    
    void Initialize(string appId, Action onSuccess, Action<string> onFailed);
    
    void LoadRewardedAd(string adUnitId, Action onLoaded, Action<string> onFailed);
    bool IsRewardedAdReady(string adUnitId);
    void ShowRewardedAd(string adUnitId, Action<RewardResult> onRewardEarned, 
        Action onClosed, Action<string> onFailed);
    
    void LoadInterstitialAd(string adUnitId, Action onLoaded, Action<string> onFailed);
    bool IsInterstitialAdReady(string adUnitId);
    void ShowInterstitialAd(string adUnitId, Action onClosed, Action<string> onFailed);
    
    void LoadBannerAd(string adUnitId, BannerPosition position);
    void ShowBanner(string adUnitId);
    void HideBanner(string adUnitId);
    void DestroyBanner(string adUnitId);
}

public class RewardResult
{
    public bool Earned;
    public string RewardType;
    public int RewardAmount;
}

public enum BannerPosition { Top, Bottom, TopLeft, TopRight, BottomLeft, BottomRight }
```

---

## 三、广告管理器（核心实现）

```csharp
/// <summary>
/// 游戏广告管理器（聚合多个广告平台）
/// </summary>
public class AdManager : MonoBehaviour
{
    private static AdManager instance;
    public static AdManager Instance => instance;

    [Header("广告配置")]
    [SerializeField] private AdConfig config;
    
    [Header("频控配置")]
    [SerializeField] private float minInterstitialInterval = 60f; // 插屏最小间隔（秒）
    [SerializeField] private int maxRewardedPerDay = 20;           // 每日激励视频上限

    // 广告提供商（按优先级排序，高 eCPM 的在前）
    private List<IAdProvider> providers = new List<IAdProvider>();
    private IAdProvider primaryProvider;
    
    // 频控记录
    private float lastInterstitialTime;
    private int todayRewardedCount;
    private long lastRewardedCountDate;
    
    // 加载状态
    private Dictionary<string, AdLoadState> adStates 
        = new Dictionary<string, AdLoadState>();
    
    // 事件
    public event Action<string, RewardResult> OnRewardEarned;
    public event Action<string> OnAdFailed;

    void Awake()
    {
        instance = this;
        InitProviders();
    }

    void InitProviders()
    {
        // 根据配置初始化广告提供商
        // 实际项目中根据 #if 宏区分
        
        // AdMob 提供商
        #if UNITY_ADMOB
        var admob = new AdMobProvider();
        admob.Initialize(config.AdMobAppId, 
            () => Debug.Log("[Ad] AdMob initialized"),
            err => Debug.LogError($"[Ad] AdMob init failed: {err}"));
        providers.Add(admob);
        #endif
        
        // Unity Ads 提供商
        #if UNITY_ADS
        var unityAds = new UnityAdsProvider();
        unityAds.Initialize(config.UnityAdsGameId, 
            () => Debug.Log("[Ad] Unity Ads initialized"), null);
        providers.Add(unityAds);
        #endif
        
        primaryProvider = providers.Count > 0 ? providers[0] : null;
        
        // 开始预加载
        PreloadAllAds();
    }

    void PreloadAllAds()
    {
        // 预加载激励视频（确保需要时立即可用）
        LoadRewardedAd(config.RewardedAdUnitId);
        
        // 预加载插屏
        LoadInterstitialAd(config.InterstitialAdUnitId);
    }

    // ============ 激励视频 ============

    public void LoadRewardedAd(string adUnitId)
    {
        var provider = GetBestProvider();
        if (provider == null) return;
        
        adStates[adUnitId] = AdLoadState.Loading;
        
        provider.LoadRewardedAd(adUnitId, 
            () =>
            {
                adStates[adUnitId] = AdLoadState.Ready;
                Debug.Log($"[Ad] Rewarded loaded: {adUnitId}");
            },
            err =>
            {
                adStates[adUnitId] = AdLoadState.Failed;
                Debug.LogWarning($"[Ad] Rewarded load failed: {err}");
                // 5秒后重试
                Invoke(nameof(RetryLoadRewarded), 5f);
            });
    }

    void RetryLoadRewarded() => LoadRewardedAd(config.RewardedAdUnitId);

    /// <summary>
    /// 展示激励视频（核心接口）
    /// </summary>
    public bool ShowRewardedAd(string placement, Action<RewardResult> onRewardEarned,
        Action onClosed = null, Action<string> onFailed = null)
    {
        // 频控检查
        if (!CheckRewardedFrequency())
        {
            onFailed?.Invoke("daily_limit_reached");
            UIManager.Instance?.ShowMessage("今日广告次数已达上限");
            return false;
        }
        
        var provider = GetBestProvider();
        if (provider == null || !provider.IsRewardedAdReady(config.RewardedAdUnitId))
        {
            // 广告未就绪，尝试加载
            LoadRewardedAd(config.RewardedAdUnitId);
            onFailed?.Invoke("ad_not_ready");
            UIManager.Instance?.ShowMessage("广告加载中，请稍后再试");
            return false;
        }
        
        adStates[config.RewardedAdUnitId] = AdLoadState.Showing;
        
        provider.ShowRewardedAd(config.RewardedAdUnitId,
            reward =>
            {
                // 记录频控
                todayRewardedCount++;
                
                // 分析埋点
                AnalyticsManager.Instance?.Track("ad_reward_earned", 
                    new Dictionary<string, object>
                    {
                        ["placement"] = placement,
                        ["reward_type"] = reward.RewardType,
                        ["reward_amount"] = reward.RewardAmount
                    });
                
                onRewardEarned?.Invoke(reward);
                OnRewardEarned?.Invoke(placement, reward);
            },
            () =>
            {
                adStates[config.RewardedAdUnitId] = AdLoadState.Idle;
                onClosed?.Invoke();
                
                // 预加载下一个
                LoadRewardedAd(config.RewardedAdUnitId);
            },
            err =>
            {
                adStates[config.RewardedAdUnitId] = AdLoadState.Failed;
                Debug.LogError($"[Ad] Rewarded show failed: {err}");
                onFailed?.Invoke(err);
                OnAdFailed?.Invoke(placement);
                
                LoadRewardedAd(config.RewardedAdUnitId);
            });
        
        return true;
    }

    // ============ 插屏广告 ============

    public void LoadInterstitialAd(string adUnitId)
    {
        var provider = GetBestProvider();
        if (provider == null) return;
        
        provider.LoadInterstitialAd(adUnitId,
            () => adStates[adUnitId] = AdLoadState.Ready,
            err =>
            {
                adStates[adUnitId] = AdLoadState.Failed;
                Invoke(nameof(RetryLoadInterstitial), 10f);
            });
    }

    void RetryLoadInterstitial() => LoadInterstitialAd(config.InterstitialAdUnitId);

    /// <summary>
    /// 展示插屏广告（需要传入场景/上下文）
    /// </summary>
    public bool TryShowInterstitialAd(string placement, Action onClosed = null)
    {
        // 频控：上次展示时间
        if (Time.realtimeSinceStartup - lastInterstitialTime < minInterstitialInterval)
        {
            Debug.Log($"[Ad] Interstitial frequency limit, skip");
            return false;
        }
        
        var provider = GetBestProvider();
        if (provider == null || !provider.IsInterstitialAdReady(config.InterstitialAdUnitId))
        {
            LoadInterstitialAd(config.InterstitialAdUnitId);
            return false;
        }
        
        lastInterstitialTime = Time.realtimeSinceStartup;
        
        provider.ShowInterstitialAd(config.InterstitialAdUnitId,
            () =>
            {
                onClosed?.Invoke();
                LoadInterstitialAd(config.InterstitialAdUnitId);
                
                AnalyticsManager.Instance?.Track("ad_interstitial_closed",
                    new Dictionary<string, object> { ["placement"] = placement });
            },
            err => Debug.LogError($"[Ad] Interstitial failed: {err}"));
        
        return true;
    }

    // ============ 辅助方法 ============

    bool CheckRewardedFrequency()
    {
        long today = DateTimeOffset.UtcNow.ToUnixTimeSeconds() / 86400; // 今天的天索引
        
        if (today != lastRewardedCountDate)
        {
            todayRewardedCount = 0;
            lastRewardedCountDate = today;
        }
        
        return todayRewardedCount < maxRewardedPerDay;
    }

    IAdProvider GetBestProvider()
    {
        // 简单策略：返回第一个已初始化的提供商
        // 进阶策略：基于实时 eCPM 选择（瀑布流/并行竞价）
        foreach (var p in providers)
            if (p.IsInitialized) return p;
        return null;
    }

    public bool IsRewardedAdReady() =>
        primaryProvider?.IsRewardedAdReady(config.RewardedAdUnitId) ?? false;
}

[CreateAssetMenu(menuName = "Game/AdConfig")]
public class AdConfig : ScriptableObject
{
    [Header("AdMob")]
    public string AdMobAppId;
    public string RewardedAdUnitId;
    public string InterstitialAdUnitId;
    public string BannerAdUnitId;
    
    [Header("Unity Ads")]
    public string UnityAdsGameId;
    public string UnityRewardedPlacement = "rewardedVideo";
    public string UnityInterstitialPlacement = "interstitial";
}
```

---

## 四、广告按钮 UI 封装

```csharp
/// <summary>
/// 激励视频广告按钮（自动管理状态）
/// </summary>
[RequireComponent(typeof(UnityEngine.UI.Button))]
public class RewardedAdButton : MonoBehaviour
{
    [SerializeField] private string placement;
    [SerializeField] private string rewardType;
    [SerializeField] private int rewardAmount = 1;
    
    [SerializeField] private UnityEngine.UI.Image adIcon;
    [SerializeField] private UnityEngine.UI.Text buttonText;
    [SerializeField] private GameObject loadingIndicator;
    
    public event Action<RewardResult> OnRewardEarned;
    
    private UnityEngine.UI.Button button;
    private float checkInterval = 1f;
    private float checkTimer;

    void Awake()
    {
        button = GetComponent<UnityEngine.UI.Button>();
        button.onClick.AddListener(OnButtonClick);
    }

    void Update()
    {
        checkTimer += Time.deltaTime;
        if (checkTimer >= checkInterval)
        {
            checkTimer = 0;
            UpdateButtonState();
        }
    }

    void UpdateButtonState()
    {
        bool adReady = AdManager.Instance?.IsRewardedAdReady() ?? false;
        
        button.interactable = adReady;
        
        if (loadingIndicator != null)
            loadingIndicator.SetActive(!adReady);
        
        if (buttonText != null)
            buttonText.text = adReady ? $"看广告 获得 x{rewardAmount}" : "广告加载中...";
    }

    void OnButtonClick()
    {
        AdManager.Instance?.ShowRewardedAd(placement,
            reward =>
            {
                // 发放奖励
                var grantedReward = new RewardResult
                {
                    Earned = true,
                    RewardType = rewardType,
                    RewardAmount = rewardAmount
                };
                OnRewardEarned?.Invoke(grantedReward);
            });
    }
}
```

---

## 五、广告策略最佳实践

| 策略 | 效果 |
|------|------|
| 激励视频 + 有价值奖励 | 最高 CTR，用户接受度高 |
| 关卡失败后展示复活广告 | 高 CVR，玩家主动选择 |
| 自然停顿点才展示插屏 | 降低用户流失 |
| 每日限制次数 | 防止广告疲劳 |
| A/B 测试不同频率 | 找到收益与留存的平衡点 |
| VIP用户禁止广告 | 付费用户体验保护 |
| 儿童游戏用 COPPA 广告 | 合规要求 |
