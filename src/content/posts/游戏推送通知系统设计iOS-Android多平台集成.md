---
title: 游戏推送通知系统设计：iOS/Android多平台集成方案
published: 2026-03-31
description: 全面解析手游推送通知系统的工程实现，涵盖本地通知（体力恢复/事件提醒）、远程推送（Firebase FCM/APNs）、通知权限请求策略、个性化推送内容生成、推送效果分析，以及在Unity中的多平台集成最佳实践。
tags: [Unity, 推送通知, Firebase, 移动游戏, iOS, Android]
category: 工程实践
draft: false
---

## 一、推送类型与使用场景

| 推送类型 | 触发时机 | 典型内容 |
|----------|----------|----------|
| 本地通知 | 客户端定时 | "体力已恢复满！" |
| 远程推送 | 服务端触发 | "你的好友在线！" |
| 交互推送 | 带行动按钮 | "领取/忽略/查看" |
| 静默推送 | 无UI，后台同步 | 更新数据 |

---

## 二、本地通知系统

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;
#if UNITY_IOS
using Unity.Notifications.iOS;
#endif
#if UNITY_ANDROID
using Unity.Notifications.Android;
#endif

/// <summary>
/// 跨平台本地通知管理器
/// </summary>
public class LocalNotificationManager : MonoBehaviour
{
    private static LocalNotificationManager instance;
    public static LocalNotificationManager Instance => instance;

    [Header("通知渠道（Android）")]
    [SerializeField] private string defaultChannelId = "game_default";
    [SerializeField] private string defaultChannelName = "游戏通知";

    void Awake()
    {
        instance = this;
        InitializeNotifications();
    }

    void InitializeNotifications()
    {
        #if UNITY_ANDROID
        // 创建通知渠道（Android 8.0+ 必需）
        var channel = new AndroidNotificationChannel
        {
            Id = defaultChannelId,
            Name = defaultChannelName,
            Importance = Importance.Default,
            Description = "游戏事件提醒",
            CanShowBadge = true,
            EnableLights = true,
            LightColor = new Color(0.2f, 0.7f, 1f),
            EnableVibration = true
        };
        AndroidNotificationCenter.RegisterNotificationChannel(channel);
        #endif
    }

    /// <summary>
    /// 请求通知权限（iOS 必须，Android 13+ 必须）
    /// </summary>
    public void RequestPermission(Action<bool> onResult)
    {
        #if UNITY_IOS
        StartCoroutine(RequestiOSPermission(onResult));
        #elif UNITY_ANDROID && UNITY_2022_2_OR_NEWER
        StartCoroutine(RequestAndroidPermission(onResult));
        #else
        onResult?.Invoke(true); // 旧版 Android 默认有权限
        #endif
    }

    #if UNITY_IOS
    System.Collections.IEnumerator RequestiOSPermission(Action<bool> onResult)
    {
        var authorizationOption = AuthorizationOption.Alert | 
            AuthorizationOption.Badge | 
            AuthorizationOption.Sound;
        
        using (var req = new AuthorizationRequest(authorizationOption, true))
        {
            while (!req.IsFinished)
                yield return null;
            
            onResult?.Invoke(req.Granted);
            Debug.Log($"[Push] iOS permission: {req.Granted}");
        }
    }
    #endif

    System.Collections.IEnumerator RequestAndroidPermission(Action<bool> onResult)
    {
        yield return null;
        // Android 13+ 需要 POST_NOTIFICATIONS 权限
        // 使用 Unity 的 Permission API
        var permission = "android.permission.POST_NOTIFICATIONS";
        
        if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(permission))
        {
            UnityEngine.Android.Permission.RequestUserPermission(permission);
            yield return new WaitForSeconds(0.5f);
        }
        
        bool granted = UnityEngine.Android.Permission.HasUserAuthorizedPermission(permission);
        onResult?.Invoke(granted);
    }

    /// <summary>
    /// 安排一个本地通知
    /// </summary>
    public int ScheduleNotification(string title, string body, 
        DateTime fireTime, string data = null, bool repeating = false)
    {
        TimeSpan delay = fireTime - DateTime.Now;
        if (delay.TotalSeconds <= 0) return -1;
        
        #if UNITY_ANDROID
        return ScheduleAndroidNotification(title, body, delay, data, repeating);
        #elif UNITY_IOS
        return ScheduleIOSNotification(title, body, delay, data, repeating);
        #else
        Debug.Log($"[Push] Would schedule: '{title}' in {delay.TotalMinutes:F1} minutes");
        return -1;
        #endif
    }

    #if UNITY_ANDROID
    int ScheduleAndroidNotification(string title, string body, TimeSpan delay, 
        string data, bool repeating)
    {
        var notification = new AndroidNotification
        {
            Title = title,
            Text = body,
            FireTime = DateTime.Now + delay,
            SmallIcon = "icon_small",
            LargeIcon = "icon_large",
            IntentData = data ?? "",
            Style = NotificationStyle.BigTextStyle,
            Color = new Color(0.2f, 0.7f, 1f)
        };
        
        if (repeating)
            notification.RepeatInterval = TimeSpan.FromDays(1);
        
        int id = AndroidNotificationCenter.SendNotification(notification, defaultChannelId);
        Debug.Log($"[Push] Android notification scheduled: id={id}, '{title}' in {delay.TotalMinutes:F1}min");
        return id;
    }
    #endif

    #if UNITY_IOS
    int ScheduleIOSNotification(string title, string body, TimeSpan delay, 
        string data, bool repeating)
    {
        var timeTrigger = new iOSNotificationTimeIntervalTrigger
        {
            TimeInterval = delay,
            Repeats = repeating
        };
        
        var notification = new iOSNotification
        {
            Title = title,
            Body = body,
            Data = data ?? "",
            Badge = 1,
            Trigger = timeTrigger,
            ShowInForeground = false
        };
        
        iOSNotificationCenter.ScheduleNotification(notification);
        Debug.Log($"[Push] iOS notification scheduled: '{title}'");
        return 0;
    }
    #endif

    /// <summary>
    /// 取消指定通知
    /// </summary>
    public void CancelNotification(int id)
    {
        #if UNITY_ANDROID
        AndroidNotificationCenter.CancelNotification(id);
        #elif UNITY_IOS
        iOSNotificationCenter.RemoveScheduledNotification(id.ToString());
        #endif
    }

    /// <summary>
    /// 取消所有通知
    /// </summary>
    public void CancelAllNotifications()
    {
        #if UNITY_ANDROID
        AndroidNotificationCenter.CancelAllNotifications();
        #elif UNITY_IOS
        iOSNotificationCenter.RemoveAllScheduledNotifications();
        #endif
    }
}

/// <summary>
/// 游戏内常用通知预设
/// </summary>
public class GameNotificationPresets : MonoBehaviour
{
    [SerializeField] private LocalNotificationManager notificationManager;
    
    // 通知 ID 缓存（用于取消）
    private Dictionary<string, int> scheduledIds = new Dictionary<string, int>();

    /// <summary>
    /// 安排体力恢复通知
    /// </summary>
    public void ScheduleEnergyFullNotification(DateTime fullTime)
    {
        CancelNotificationById("energy");
        
        int id = notificationManager.ScheduleNotification(
            "体力已恢复！",
            "你的体力已满，快来继续冒险吧！",
            fullTime,
            "action:energy_full");
        
        scheduledIds["energy"] = id;
    }

    /// <summary>
    /// 安排每日登录提醒
    /// </summary>
    public void ScheduleDailyLoginReminder(TimeSpan timeOfDay)
    {
        DateTime nextFire = DateTime.Today + timeOfDay;
        if (nextFire < DateTime.Now)
            nextFire = nextFire.AddDays(1);
        
        CancelNotificationById("daily");
        
        int id = notificationManager.ScheduleNotification(
            "今日任务等你完成！",
            "完成每日任务获得丰厚奖励，快来签到吧！",
            nextFire,
            "action:daily_login",
            repeating: true);
        
        scheduledIds["daily"] = id;
    }

    /// <summary>
    /// 安排限时活动提醒
    /// </summary>
    public void ScheduleEventReminder(string eventName, DateTime startTime)
    {
        var remindTime = startTime - TimeSpan.FromHours(1);
        
        int id = notificationManager.ScheduleNotification(
            $"活动即将开始！",
            $"{eventName}将在1小时后开始，做好准备了吗？",
            remindTime,
            $"action:event:{eventName}");
        
        scheduledIds[$"event_{eventName}"] = id;
    }

    void CancelNotificationById(string key)
    {
        if (scheduledIds.TryGetValue(key, out int id))
        {
            notificationManager.CancelNotification(id);
            scheduledIds.Remove(key);
        }
    }
}
```

---

## 三、Firebase 远程推送集成

```csharp
/// <summary>
/// Firebase Cloud Messaging（FCM）集成
/// </summary>
public class FCMPushManager : MonoBehaviour
{
    private static FCMPushManager instance;
    public static FCMPushManager Instance => instance;

    public event Action<PushMessage> OnPushReceived;
    public event Action<PushMessage> OnPushClicked;
    
    public string FCMToken { get; private set; }

    void Awake()
    {
        instance = this;
        InitFCM();
    }

    async void InitFCM()
    {
        #if FIREBASE_MESSAGING
        await Firebase.FirebaseApp.CheckAndFixDependenciesAsync();
        
        Firebase.Messaging.FirebaseMessaging.TokenReceived += OnTokenReceived;
        Firebase.Messaging.FirebaseMessaging.MessageReceived += OnMessageReceived;
        
        // 订阅话题（用于广播推送）
        Firebase.Messaging.FirebaseMessaging.SubscribeAsync("all_users");
        
        // 获取当前 Token
        string token = await Firebase.Messaging.FirebaseMessaging.GetTokenAsync();
        OnTokenReceived(null, new Firebase.Messaging.TokenReceivedEventArgs(token));
        #endif
    }

    #if FIREBASE_MESSAGING
    void OnTokenReceived(object sender, Firebase.Messaging.TokenReceivedEventArgs e)
    {
        FCMToken = e.Token;
        Debug.Log($"[FCM] Token: {FCMToken}");
        
        // 将 Token 上报给游戏服务端（用于定向推送）
        _ = RegisterTokenToServer(FCMToken);
    }

    void OnMessageReceived(object sender, Firebase.Messaging.MessageReceivedEventArgs e)
    {
        var msg = new PushMessage
        {
            Title = e.Message.Notification?.Title,
            Body = e.Message.Notification?.Body,
            Data = new Dictionary<string, string>(e.Message.Data),
            ClickAction = e.Message.Notification?.ClickAction
        };
        
        if (Application.isFocused)
        {
            // APP 在前台：显示应用内弹窗
            OnPushReceived?.Invoke(msg);
            ShowInAppNotification(msg);
        }
        else
        {
            // APP 在后台：系统通知栏处理（自动）
            // 当用户点击通知进入游戏时会触发 OnPushClicked
        }
    }
    #endif

    async System.Threading.Tasks.Task RegisterTokenToServer(string token)
    {
        // 将 FCM Token 上报给游戏服务端，服务端用于定向推送
        var request = new
        {
            player_id = PlayerDataService.GetLocalPlayerData()?.PlayerId,
            fcm_token = token,
            platform = Application.platform.ToString(),
            device_id = SystemInfo.deviceUniqueIdentifier
        };
        
        // await NetworkService.RegisterPushToken(request);
        Debug.Log($"[FCM] Token registered to server");
    }

    void ShowInAppNotification(PushMessage msg)
    {
        // 显示应用内通知（例如屏幕顶部弹出的Toast）
        UIManager.Instance?.ShowToast(msg.Title, msg.Body, 5f);
    }

    /// <summary>
    /// 处理从推送通知打开游戏的情况
    /// </summary>
    public void HandleNotificationLaunch()
    {
        #if UNITY_ANDROID
        var intent = new AndroidJavaObject("android.content.Intent");
        var unityPlayer = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
        var activity = unityPlayer.GetStatic<AndroidJavaObject>("currentActivity");
        var launchIntent = activity.Call<AndroidJavaObject>("getIntent");
        
        string action = launchIntent?.Call<string>("getAction");
        if (action != null)
        {
            Debug.Log($"[Push] Launched from notification, action: {action}");
            HandlePushAction(action);
        }
        #endif
    }

    void HandlePushAction(string action)
    {
        if (action.StartsWith("action:"))
        {
            string actionType = action.Substring(7);
            
            switch (actionType)
            {
                case "energy_full":
                    GameManager.Instance?.GoToMainMenu();
                    break;
                case "daily_login":
                    GameManager.Instance?.ShowDailyRewardUI();
                    break;
                default:
                    if (actionType.StartsWith("event:"))
                    {
                        string eventName = actionType.Substring(6);
                        GameManager.Instance?.OpenEvent(eventName);
                    }
                    break;
            }
        }
    }
}

public class PushMessage
{
    public string Title;
    public string Body;
    public Dictionary<string, string> Data;
    public string ClickAction;
}
```

---

## 四、推送权限请求时机策略

```csharp
/// <summary>
/// 智能推送权限请求（在合适时机请求，提高接受率）
/// </summary>
public class SmartPermissionRequest : MonoBehaviour
{
    [SerializeField] private LocalNotificationManager notificationManager;
    
    void Start()
    {
        // 策略：在玩家完成第一关、有正向情绪时请求
        // 而不是APP一启动就请求（会降低接受率）
        GameManager.Instance.OnLevelComplete += OnFirstLevelComplete;
    }

    void OnFirstLevelComplete(int levelIndex)
    {
        if (levelIndex != 1) return;
        
        // 等待结算界面显示后再请求
        Invoke(nameof(RequestPermissionWithContext), 2f);
    }

    void RequestPermissionWithContext()
    {
        // 先显示自定义的权限说明弹窗（解释通知的价值）
        UIManager.Instance?.ShowDialog(
            "开启通知获得更好体验",
            "开启通知后，体力恢复、限时活动等重要信息将第一时间提醒您，不错过任何奖励！",
            "开启通知",
            "暂不",
            onConfirm: () =>
            {
                notificationManager.RequestPermission(granted =>
                {
                    if (granted)
                    {
                        Debug.Log("[Push] Permission granted");
                        SetupDefaultNotifications();
                    }
                });
            }
        );
    }

    void SetupDefaultNotifications()
    {
        var presets = GetComponent<GameNotificationPresets>();
        presets?.ScheduleDailyLoginReminder(TimeSpan.FromHours(20)); // 每天20:00提醒
    }
}
```

---

## 五、推送最佳实践

| 原则 | 实施方式 |
|------|----------|
| 时机选择 | 用户情绪最佳时（通关、获得奖励后）请求权限 |
| 内容个性化 | 根据玩家行为定制推送内容（不同阶段不同推送）|
| 频率控制 | 每天不超过2条推送，避免被卸载 |
| 深度链接 | 点击直达相关功能页面，减少操作步骤 |
| 效果分析 | 统计推送打开率、转化率，持续优化 |
| 退出机制 | 提供关闭特定类型通知的设置 |
