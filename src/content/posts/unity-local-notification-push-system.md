---
title: Unity移动端本地通知与推送系统完全指南：从本地通知到离线唤醒工程实践
published: 2026-05-09
description: 深度解析Unity移动端通知系统架构，涵盖Android/iOS本地通知、FCM/APNs远程推送、离线唤醒策略、通知优先级与分组管理，从Unity Mobile Notifications插件到原生桥接层，完整工程实践。
tags: [Unity, 移动端, 推送通知, Android, iOS, 游戏开发]
category: 移动端开发
draft: false
---

# Unity移动端本地通知与推送系统完全指南：从本地通知到离线唤醒工程实践

## 1. 通知系统架构概览

移动游戏的留存率在很大程度上依赖于通知系统的设计质量。本文聚焦游戏客户端侧的完整通知工程实践，涵盖本地通知调度、远程推送接入、通知数据携带、点击跳转处理以及权限适配全链路。

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                    Game Client                       │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │NotificationMgr│   │    NotificationScheduler  │   │
│  │  (Facade层)   │──▶│  (定时调度/取消/查询)      │   │
│  └──────────────┘   └──────────────────────────┘   │
│          │                       │                   │
│  ┌───────▼──────────────────────▼──────────────┐   │
│  │         PlatformNotificationBridge           │   │
│  │  ┌─────────────┐    ┌──────────────────────┐│   │
│  │  │ AndroidBridge│    │    iOSBridge          ││   │
│  │  │(JobIntentSvc)│    │ (UNUserNotification)  ││   │
│  │  └─────────────┘    └──────────────────────┘│   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
         ↓ FCM/APNs远程推送
┌─────────────────────────────────────────────────────┐
│               Game Server Push Service               │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │  FCM Gateway  │    │     APNs Gateway          │   │
│  └──────────────┘    └──────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 1.2 本地通知 vs 远程推送

| 特性 | 本地通知 | 远程推送 |
|------|----------|----------|
| 服务器依赖 | 无 | 需要后端推送服务 |
| 精准触发 | 客户端精确调度 | 服务端下发，网络延迟不可控 |
| 离线可用 | 完全离线 | 设备需网络连接 |
| 典型场景 | 体力恢复、建造完成 | 活动开始、好友消息 |
| 数量限制 | Android无限制；iOS 64条 | 无限制 |

## 2. Unity Mobile Notifications 插件

Unity 官方提供 `com.unity.mobile.notifications` 包，统一封装 Android/iOS 通知接口。

### 2.1 安装与初始化

```json
// Packages/manifest.json
{
  "dependencies": {
    "com.unity.mobile.notifications": "2.3.2"
  }
}
```

```csharp
// NotificationInitializer.cs
using Unity.Notifications.Android;
using Unity.Notifications.iOS;
using UnityEngine;

public static class NotificationInitializer
{
    public static async System.Threading.Tasks.Task InitializeAsync()
    {
#if UNITY_ANDROID
        await InitAndroidAsync();
#elif UNITY_IOS
        await InitiOSAsync();
#endif
    }

#if UNITY_ANDROID
    static System.Threading.Tasks.Task InitAndroidAsync()
    {
        // 创建通知渠道（Android 8.0+ 必须）
        var channel = new AndroidNotificationChannel
        {
            Id = "game_default",
            Name = "游戏通知",
            Description = "游戏系统通知",
            Importance = Importance.Default,
        };
        AndroidNotificationCenter.RegisterNotificationChannel(channel);

        // 高优先级渠道：活动/限时
        var urgentChannel = new AndroidNotificationChannel
        {
            Id = "game_urgent",
            Name = "紧急通知",
            Description = "限时活动与紧急系统通知",
            Importance = Importance.High,
            EnableVibration = true,
            LockScreenVisibility = LockScreenVisibility.Public,
        };
        AndroidNotificationCenter.RegisterNotificationChannel(urgentChannel);

        return System.Threading.Tasks.Task.CompletedTask;
    }
#endif

#if UNITY_IOS
    static async System.Threading.Tasks.Task InitiOSAsync()
    {
        var options = AuthorizationOption.Alert
                    | AuthorizationOption.Badge
                    | AuthorizationOption.Sound;

        using var req = new AuthorizationRequest(options, registerForRemoteNotifications: true);
        while (!req.IsFinished)
            await System.Threading.Tasks.Task.Yield();

        if (!req.Granted)
            Debug.LogWarning("[Notification] iOS通知权限被拒绝");
        else
            Debug.Log("[Notification] iOS通知权限已获得");
    }
#endif
}
```

## 3. 本地通知核心实现

### 3.1 通知管理器门面

```csharp
// NotificationManager.cs
using System;
using System.Collections.Generic;
using UnityEngine;

public class NotificationManager : MonoBehaviour
{
    private static NotificationManager _instance;
    public static NotificationManager Instance => _instance;

    // 已调度通知的ID注册表，用于去重/取消
    private readonly Dictionary<string, int> _scheduledIds = new();

    private void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }

    private async void Start()
    {
        await NotificationInitializer.InitializeAsync();
        ProcessPendingNotificationIntent(); // 处理点击通知启动的情况
    }

    /// <summary>
    /// 调度一条本地通知
    /// </summary>
    /// <param name="key">业务唯一键，用于去重</param>
    /// <param name="title">通知标题</param>
    /// <param name="body">通知内容</param>
    /// <param name="fireTime">触发绝对时间</param>
    /// <param name="data">携带的业务数据（JSON）</param>
    /// <param name="channel">渠道ID（Android）</param>
    public void Schedule(string key, string title, string body,
        DateTime fireTime, string data = null, string channel = "game_default")
    {
        // 先取消同key旧通知
        Cancel(key);

        int notifId;
#if UNITY_ANDROID
        notifId = ScheduleAndroid(title, body, fireTime, data, channel);
#elif UNITY_IOS
        notifId = ScheduleiOS(title, body, fireTime, data);
#else
        notifId = -1;
        Debug.Log($"[Notification] 编辑器模拟通知: {title} @ {fireTime}");
#endif
        if (notifId >= 0)
            _scheduledIds[key] = notifId;
    }

    public void Cancel(string key)
    {
        if (!_scheduledIds.TryGetValue(key, out int id)) return;
#if UNITY_ANDROID
        AndroidNotificationCenter.CancelNotification(id);
#elif UNITY_IOS
        iOSNotificationCenter.RemoveScheduledNotification(id.ToString());
#endif
        _scheduledIds.Remove(key);
    }

    public void CancelAll()
    {
#if UNITY_ANDROID
        AndroidNotificationCenter.CancelAllNotifications();
#elif UNITY_IOS
        iOSNotificationCenter.RemoveAllScheduledNotifications();
#endif
        _scheduledIds.Clear();
    }

    private void ProcessPendingNotificationIntent()
    {
#if UNITY_ANDROID
        var intent = AndroidNotificationCenter.GetLastNotificationIntent();
        if (intent != null)
        {
            Debug.Log($"[Notification] 从通知启动，数据: {intent.Notification.IntentData}");
            HandleNotificationClick(intent.Notification.IntentData);
        }
#elif UNITY_IOS
        var notif = iOSNotificationCenter.GetLastRespondedNotification();
        if (notif != null)
        {
            Debug.Log($"[Notification] 从通知启动，数据: {notif.Data}");
            HandleNotificationClick(notif.Data);
        }
#endif
    }

    private void HandleNotificationClick(string jsonData)
    {
        if (string.IsNullOrEmpty(jsonData)) return;
        try
        {
            var payload = JsonUtility.FromJson<NotificationPayload>(jsonData);
            NotificationRouter.Route(payload);
        }
        catch (Exception ex)
        {
            Debug.LogError($"[Notification] 解析通知数据失败: {ex.Message}");
        }
    }

#if UNITY_ANDROID
    private int ScheduleAndroid(string title, string body,
        DateTime fireTime, string data, string channel)
    {
        var notification = new AndroidNotification
        {
            Title = title,
            Text = body,
            FireTime = fireTime,
            IntentData = data,
            SmallIcon = "icon_small",   // res/drawable 中的图标名
            LargeIcon = "icon_large",
            ShouldAutoCancel = true,
            Style = NotificationStyle.BigTextStyle,
        };
        return AndroidNotificationCenter.SendNotification(notification, channel);
    }
#endif

#if UNITY_IOS
    private int ScheduleiOS(string title, string body,
        DateTime fireTime, string data)
    {
        var trigger = new iOSNotificationCalendarTrigger
        {
            Year  = fireTime.Year,
            Month = fireTime.Month,
            Day   = fireTime.Day,
            Hour  = fireTime.Hour,
            Minute= fireTime.Minute,
            Second= fireTime.Second,
            Repeats = false,
        };
        var notification = new iOSNotification
        {
            Title       = title,
            Body        = body,
            Data        = data,
            Badge       = 1,
            ShowInForeground = false,
            Trigger     = trigger,
        };
        iOSNotificationCenter.ScheduleNotification(notification);
        return notification.Identifier.GetHashCode();
    }
#endif
}
```

### 3.2 通知路由器

```csharp
// NotificationRouter.cs
[Serializable]
public class NotificationPayload
{
    public string type;   // "stamina" | "build" | "event" | "guild"
    public string sceneId;
    public string extraJson;
}

public static class NotificationRouter
{
    public static void Route(NotificationPayload payload)
    {
        switch (payload.type)
        {
            case "stamina":
                UIManager.OpenPanel<StaminaPanel>();
                break;
            case "build":
                UIManager.OpenPanel<BuildingPanel>(payload.sceneId);
                break;
            case "event":
                EventManager.OpenEventById(payload.sceneId);
                break;
            case "guild":
                UIManager.OpenPanel<GuildPanel>();
                break;
            default:
                Debug.LogWarning($"[NotificationRouter] 未知通知类型: {payload.type}");
                break;
        }
    }
}
```

## 4. 游戏业务通知调度策略

### 4.1 体力/能量恢复通知

```csharp
// StaminaNotificationScheduler.cs
public class StaminaNotificationScheduler
{
    private const string NotifKey = "stamina_full";
    private const int MaxStamina  = 120;
    private const int RegenPerMin = 1;  // 每分钟恢复1点

    /// <summary>
    /// 每次体力变化时重新调度通知
    /// </summary>
    public static void Reschedule(int currentStamina, DateTime lastRegenTime)
    {
        // 体力满不通知
        if (currentStamina >= MaxStamina)
        {
            NotificationManager.Instance.Cancel(NotifKey);
            return;
        }

        int needMinutes = (MaxStamina - currentStamina) * RegenPerMin;
        DateTime fullTime = lastRegenTime.AddMinutes(needMinutes);

        var payload = new NotificationPayload { type = "stamina" };
        string dataJson = JsonUtility.ToJson(payload);

        NotificationManager.Instance.Schedule(
            key:      NotifKey,
            title:    "体力已充满！",
            body:     $"你的体力已恢复至 {MaxStamina}，快来继续冒险吧！",
            fireTime: fullTime,
            data:     dataJson,
            channel:  "game_default"
        );
    }
}
```

### 4.2 建造/升级完成通知

```csharp
// BuildNotificationScheduler.cs
public class BuildNotificationScheduler
{
    public static void ScheduleBuildComplete(
        string buildingId, string buildingName, DateTime completeTime)
    {
        string key = $"build_{buildingId}";
        var payload = new NotificationPayload
        {
            type    = "build",
            sceneId = buildingId,
        };

        NotificationManager.Instance.Schedule(
            key:      key,
            title:    "建造完成",
            body:     $"【{buildingName}】已建造完成，点击领取奖励！",
            fireTime: completeTime,
            data:     JsonUtility.ToJson(payload),
            channel:  "game_default"
        );
    }

    public static void CancelBuildNotification(string buildingId)
    {
        NotificationManager.Instance.Cancel($"build_{buildingId}");
    }
}
```

### 4.3 限时活动提前提醒

```csharp
// EventNotificationScheduler.cs
public class EventNotificationScheduler
{
    // 活动开始前15分钟提醒
    private static readonly TimeSpan ReminderOffset = TimeSpan.FromMinutes(15);

    public static void ScheduleEventReminder(
        string eventId, string eventName, DateTime startTime)
    {
        DateTime remindTime = startTime - ReminderOffset;
        if (remindTime <= DateTime.Now) return; // 错过提醒窗口

        string key = $"event_{eventId}";
        var payload = new NotificationPayload
        {
            type    = "event",
            sceneId = eventId,
        };

        NotificationManager.Instance.Schedule(
            key:      key,
            title:    "限时活动即将开始",
            body:     $"【{eventName}】将在15分钟后开始，赶快准备！",
            fireTime: remindTime,
            data:     JsonUtility.ToJson(payload),
            channel:  "game_urgent"  // 使用高优先级渠道
        );
    }
}
```

## 5. 远程推送（FCM/APNs）接入

### 5.1 Firebase Cloud Messaging 接入

```csharp
// FirebasePushManager.cs
#if UNITY_ANDROID || UNITY_IOS
using Firebase;
using Firebase.Messaging;

public class FirebasePushManager : MonoBehaviour
{
    private static string _fcmToken;

    private async void Start()
    {
        var dependencyStatus = await FirebaseApp.CheckAndFixDependenciesAsync();
        if (dependencyStatus != DependencyStatus.Available)
        {
            Debug.LogError($"Firebase依赖异常: {dependencyStatus}");
            return;
        }

        FirebaseMessaging.TokenReceived  += OnTokenReceived;
        FirebaseMessaging.MessageReceived += OnMessageReceived;

        // 订阅全服广播主题
        await FirebaseMessaging.SubscribeAsync("all_players");

        // 获取当前Token
        string token = await FirebaseMessaging.GetTokenAsync();
        OnTokenReceived(null, new TokenReceivedEventArgs(token));
    }

    private void OnTokenReceived(object sender, TokenReceivedEventArgs e)
    {
        _fcmToken = e.Token;
        Debug.Log($"[FCM] Token: {e.Token[..20]}...");

        // 上报Token到游戏服务器
        NetworkManager.Instance.ReportPushToken("fcm", e.Token);
    }

    private void OnMessageReceived(object sender, MessageReceivedEventArgs e)
    {
        var msg = e.Message;
        Debug.Log($"[FCM] 收到推送: {msg.Notification?.Title}");

        // 前台收到推送：自定义UI展示，不弹系统通知
        if (Application.isFocused)
        {
            ShowInAppNotificationBanner(
                msg.Notification?.Title,
                msg.Notification?.Body,
                msg.Data);
        }
        // 后台收到推送：系统通知由FCM SDK自动展示
    }

    private void ShowInAppNotificationBanner(
        string title, string body, System.Collections.Generic.IDictionary<string, string> data)
    {
        // 显示游戏内横幅通知
        UIManager.ShowBanner(title, body, () =>
        {
            if (data.TryGetValue("type", out string type))
            {
                var payload = new NotificationPayload { type = type };
                if (data.TryGetValue("sceneId", out string sceneId))
                    payload.sceneId = sceneId;
                NotificationRouter.Route(payload);
            }
        });
    }

    private void OnDestroy()
    {
        FirebaseMessaging.TokenReceived   -= OnTokenReceived;
        FirebaseMessaging.MessageReceived -= OnMessageReceived;
    }
}
#endif
```

### 5.2 通知权限运行时请求（Android 13+）

```csharp
// NotificationPermissionHelper.cs
#if UNITY_ANDROID
using UnityEngine.Android;

public static class NotificationPermissionHelper
{
    private const string PostNotificationPermission =
        "android.permission.POST_NOTIFICATIONS";

    public static bool HasPermission()
    {
        // Android 13 (API 33) 以下不需要动态申请
        if (GetAndroidApiLevel() < 33) return true;
        return Permission.HasUserAuthorizedPermission(PostNotificationPermission);
    }

    public static void RequestPermission(System.Action<bool> callback)
    {
        if (HasPermission()) { callback?.Invoke(true); return; }

        var callbacks = new PermissionCallbacks();
        callbacks.PermissionGranted  += _ => callback?.Invoke(true);
        callbacks.PermissionDenied   += _ => callback?.Invoke(false);
        callbacks.PermissionDeniedAndDontAskAgain += _ => callback?.Invoke(false);
        Permission.RequestUserPermission(PostNotificationPermission, callbacks);
    }

    private static int GetAndroidApiLevel()
    {
        using var version = new AndroidJavaClass("android.os.Build$VERSION");
        return version.GetStatic<int>("SDK_INT");
    }
}
#endif
```

## 6. 通知徽标（Badge）管理

### 6.1 iOS徽标控制

```csharp
// BadgeManager.cs
public static class BadgeManager
{
    private static int _badgeCount;

    public static void SetBadge(int count)
    {
        _badgeCount = Mathf.Max(0, count);
#if UNITY_IOS
        iOSNotificationCenter.ApplicationBadge = _badgeCount;
#elif UNITY_ANDROID
        // Android需要ShortcutBadger等第三方库，或使用launcher-specific API
        SetAndroidBadge(_badgeCount);
#endif
    }

    public static void ClearBadge() => SetBadge(0);

    public static void IncrementBadge() => SetBadge(_badgeCount + 1);

#if UNITY_ANDROID
    private static void SetAndroidBadge(int count)
    {
        try
        {
            using var ctx = new AndroidJavaClass(
                "com.unity3d.player.UnityPlayer");
            using var activity = ctx.GetStatic<AndroidJavaObject>(
                "currentActivity");
            // 通知系统更新桌面角标（需各品牌厂商适配）
            using var intent = new AndroidJavaObject(
                "android.content.Intent", "android.intent.action.BADGE_COUNT_UPDATE");
            intent.Call<AndroidJavaObject>("putExtra", "badge_count", count);
            intent.Call<AndroidJavaObject>("putExtra", "badge_count_package_name",
                Application.identifier);
            activity.Call("sendBroadcast", intent);
        }
        catch (System.Exception ex)
        {
            Debug.LogWarning($"[Badge] Android角标设置失败: {ex.Message}");
        }
    }
#endif
}
```

## 7. 应用进入前后台通知生命周期

```csharp
// NotificationLifecycleHandler.cs
public class NotificationLifecycleHandler : MonoBehaviour
{
    private void OnApplicationPause(bool paused)
    {
        if (paused)
        {
            // 进入后台：刷新所有即将到期的通知
            RefreshScheduledNotifications();
        }
        else
        {
            // 回到前台：清除角标，取消已过期通知
            BadgeManager.ClearBadge();
            ClearExpiredNotifications();

            // 处理通知点击跳转（部分Android机型在此时回调）
            CheckPendingNotificationClick();
        }
    }

    private void RefreshScheduledNotifications()
    {
        // 重新调度体力、建造等时效性通知（防止设备时间漂移）
        var staminaData = PlayerDataManager.GetStaminaData();
        StaminaNotificationScheduler.Reschedule(
            staminaData.Current, staminaData.LastRegenTime);
    }

    private void ClearExpiredNotifications()
    {
#if UNITY_ANDROID
        AndroidNotificationCenter.CancelAllDisplayedNotifications();
#elif UNITY_IOS
        iOSNotificationCenter.RemoveAllDeliveredNotifications();
#endif
    }

    private void CheckPendingNotificationClick()
    {
#if UNITY_ANDROID
        var intent = AndroidNotificationCenter.GetLastNotificationIntent();
        if (intent != null && !string.IsNullOrEmpty(intent.Notification.IntentData))
        {
            var payload = JsonUtility.FromJson<NotificationPayload>(
                intent.Notification.IntentData);
            NotificationRouter.Route(payload);
            AndroidNotificationCenter.CancelNotification(intent.Id);
        }
#endif
    }
}
```

## 8. 通知静默时段与用户偏好

```csharp
// NotificationPreferenceManager.cs
[Serializable]
public class NotificationPreference
{
    public bool enabled        = true;
    public bool staminaNotif   = true;
    public bool buildNotif     = true;
    public bool eventNotif     = true;
    public bool guildNotif     = true;
    public int  quietHourStart = 23; // 静默开始时 (23:00)
    public int  quietHourEnd   = 8;  // 静默结束时 (08:00)
}

public static class NotificationPreferenceManager
{
    private const string PrefKey = "notification_pref";
    private static NotificationPreference _pref;

    public static NotificationPreference Get()
    {
        if (_pref != null) return _pref;
        string json = PlayerPrefs.GetString(PrefKey, "{}");
        _pref = JsonUtility.FromJson<NotificationPreference>(json)
             ?? new NotificationPreference();
        return _pref;
    }

    public static void Save(NotificationPreference pref)
    {
        _pref = pref;
        PlayerPrefs.SetString(PrefKey, JsonUtility.ToJson(pref));
        PlayerPrefs.Save();
    }

    /// <summary>检查当前是否在静默时段</summary>
    public static bool IsInQuietHours()
    {
        var pref = Get();
        int now = DateTime.Now.Hour;
        // 跨午夜静默段，如 23:00 ~ 08:00
        if (pref.quietHourStart > pref.quietHourEnd)
            return now >= pref.quietHourStart || now < pref.quietHourEnd;
        return now >= pref.quietHourStart && now < pref.quietHourEnd;
    }

    /// <summary>
    /// 考虑静默时段，将触发时间推迟到静默结束后
    /// </summary>
    public static DateTime AdjustForQuietHours(DateTime planned)
    {
        if (!IsInQuietHours()) return planned;
        var pref = Get();
        // 推至静默结束时刻
        var quietEnd = planned.Date.AddHours(pref.quietHourEnd);
        if (quietEnd < planned) quietEnd = quietEnd.AddDays(1);
        return quietEnd;
    }
}
```

## 9. 测试与调试工具

```csharp
// NotificationDebugger.cs (Editor Only)
#if UNITY_EDITOR
using UnityEditor;

public class NotificationDebugger : EditorWindow
{
    [MenuItem("Tools/通知调试器")]
    public static void ShowWindow()
    {
        GetWindow<NotificationDebugger>("通知调试器");
    }

    private string _title = "测试通知";
    private string _body  = "这是一条测试通知";
    private int    _delaySeconds = 5;

    private void OnGUI()
    {
        GUILayout.Label("本地通知调试", EditorStyles.boldLabel);
        _title        = EditorGUILayout.TextField("标题", _title);
        _body         = EditorGUILayout.TextField("内容", _body);
        _delaySeconds = EditorGUILayout.IntSlider("延迟(秒)", _delaySeconds, 1, 60);

        if (GUILayout.Button("发送测试通知"))
        {
            // 在Editor中仅打印日志模拟
            Debug.Log($"[NotifDebug] 模拟通知发送\n" +
                      $"标题: {_title}\n内容: {_body}\n" +
                      $"触发时间: {System.DateTime.Now.AddSeconds(_delaySeconds)}");
        }

        GUILayout.Space(10);
        GUILayout.Label("权限状态", EditorStyles.boldLabel);
        GUILayout.Label("当前平台: Unity Editor（通知功能在设备上生效）");
    }
}
#endif
```

## 10. 最佳实践总结

| 实践要点 | 说明 |
|----------|------|
| 通知渠道分级 | Android 8.0+ 必须分渠道，按重要性区分（默认/高优先级/静默） |
| Key去重调度 | 同一业务键重新调度前先取消旧通知，防止重复 |
| 静默时段适配 | 体力/建造通知应检测用户设置的免打扰时段并延后触发 |
| 前台拦截自绘 | 应用前台时系统通知体验差，改用游戏内横幅UI展示 |
| Token刷新上报 | FCM Token会更新，需监听回调并重新上报服务器 |
| iOS 64条限制 | iOS最多调度64条本地通知，超出需按优先级裁剪，优先保留最近的 |
| 角标及时清空 | 回到前台立即清零角标（badgeCount=0），避免用户困惑 |
| 权限前置引导 | 请求权限前展示说明弹窗，提升用户授权率 |
| 数据携带格式 | IntentData/Data 使用 JSON，保持结构扩展性 |
| 过期通知清理 | 回到前台时清除通知栏所有已展示通知，避免信息积压 |

---

> 本文代码基于 Unity 2022.3 LTS + com.unity.mobile.notifications 2.3.2，核心API在 Unity 2021+ 均可使用。FCM 部分需要 Firebase Unity SDK 11.x。
