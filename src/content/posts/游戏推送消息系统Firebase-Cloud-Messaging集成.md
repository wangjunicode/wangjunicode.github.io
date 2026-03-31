---
title: 游戏推送消息系统：Firebase Cloud Messaging集成
published: 2026-03-31
description: 全面解析游戏推送消息系统工程实现，包含FCM（Firebase Cloud Messaging）Unity SDK集成、推送Token管理（获取/刷新/服务端同步）、推送消息数据结构、前台/后台消息处理分离、深度链接（点击通知跳转到游戏内指定页面）、推送A/B测试，以及iOS APNs证书配置。
tags: [Unity, FCM, 推送通知, Firebase, 移动端]
category: 游戏商业化
draft: false
---

## 一、FCM集成

```csharp
using System;
using UnityEngine;
#if UNITY_IOS || UNITY_ANDROID
using Firebase.Messaging;
using Firebase;
#endif

public class PushNotificationManager : MonoBehaviour
{
    private static PushNotificationManager instance;
    public static PushNotificationManager Instance => instance;
    
    public event Action<string> OnNotificationReceived;  // 前台收到通知
    public event Action<string> OnNotificationTapped;    // 点击通知打开

    void Awake()
    {
        instance = this;
        DontDestroyOnLoad(gameObject);
    }

    public async void Initialize()
    {
#if UNITY_IOS || UNITY_ANDROID
        try
        {
            // 检查Firebase依赖
            var dependencyStatus = await FirebaseApp.CheckAndFixDependenciesAsync();
            if (dependencyStatus != DependencyStatus.Available)
            {
                Debug.LogError($"[Push] Firebase依赖问题: {dependencyStatus}");
                return;
            }
            
            // 监听Token更新
            FirebaseMessaging.TokenReceived += OnTokenReceived;
            // 监听消息
            FirebaseMessaging.MessageReceived += OnMessageReceived;
            
            // 获取当前Token
            string token = await FirebaseMessaging.GetTokenAsync();
            OnTokenReceived(null, new TokenReceivedEventArgs(token));
        }
        catch (Exception e)
        {
            Debug.LogError($"[Push] 初始化失败: {e.Message}");
        }
#endif
    }

#if UNITY_IOS || UNITY_ANDROID
    void OnTokenReceived(object sender, TokenReceivedEventArgs e)
    {
        Debug.Log($"[Push] Token: {e.Token?.Substring(0, 20)}...");
        
        // 同步到服务端
        NetworkService.UpdatePushToken(e.Token, GetPlatform());
        PlayerPrefs.SetString("push_token", e.Token);
    }

    void OnMessageReceived(object sender, MessageReceivedEventArgs e)
    {
        var msg = e.Message;
        
        if (msg.Data.TryGetValue("type", out string type))
        {
            switch (type)
            {
                case "friend_request":
                    FriendManager.Instance?.OnFriendRequest?.Invoke(null);
                    break;
                case "activity_start":
                    ActivityManager.Instance?.LoadActivities();
                    break;
                case "reward":
                    MailManager.Instance?.LoadMails();
                    break;
            }
        }
        
        string deepLink = msg.Data.TryGetValue("deep_link", out var link) ? link : null;
        OnNotificationReceived?.Invoke(deepLink);
    }
#endif

    string GetPlatform()
    {
#if UNITY_IOS
        return "ios";
#elif UNITY_ANDROID
        return "android";
#else
        return "unknown";
#endif
    }

    public void HandleDeepLink(string deepLink)
    {
        if (string.IsNullOrEmpty(deepLink)) return;
        
        // 解析深度链接格式：game://activity/act_001
        var uri = new Uri(deepLink);
        switch (uri.Host)
        {
            case "activity":
                string actId = uri.AbsolutePath.TrimStart('/');
                UIManager.Instance?.OpenActivity(actId);
                break;
            case "mail":
                UIManager.Instance?.OpenMailSystem();
                break;
            case "store":
                UIManager.Instance?.OpenStore();
                break;
        }
    }
}
```

---

## 二、推送策略

| 推送类型 | 触发条件 | 目标 |
|----------|----------|------|
| 活动开始 | 新活动上线 | 拉回流失用户 |
| 好友上线 | 好友登录游戏 | 社交召回 |
| 体力满 | 体力恢复到上限 | 促进登录消耗 |
| 赛季结束 | 赛季剩余48小时 | 冲级/付费 |
| 限时礼包 | 运营推送折扣 | 促进付费 |
| 战令提醒 | 战令到期提前7天 | 续费提醒 |

---

## 三、推送注意事项

| 注意点 | 说明 |
|--------|------|
| 推送频率 | 每天不超过2条，高频会导致取消订阅 |
| 权限请求 | iOS需主动申请，Android 13+也需要 |
| 个性化 | 推送内容包含玩家名/具体奖励 |
| 时间控制 | 避免凌晨推送（按玩家时区发送）|
| A/B测试 | 测试不同文案点击率 |
| 静默推送 | 数据同步用静默推送（不弹通知）|
