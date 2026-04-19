---
title: CrashSight崩溃监控与数据上报系统
published: 2024-01-01
description: "CrashSight崩溃监控与数据上报系统 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 性能优化
draft: false
encryptedKey: henhaoji123
---

# CrashSight崩溃监控与数据上报系统

## 1. 系统概述

本项目集成了腾讯 **CrashSight**（原 Bugly）进行崩溃监控和异常上报，同时使用 **TDM**（腾讯数据分析 SDK）进行用户行为上报。两套系统共同保障游戏质量和运营数据的完整性。

**CrashSight 核心能力：**
- 自动捕获 C# 异常（`Application.logMessageReceived`）
- Native 崩溃堆栈符号化（Android .so / iOS dSYM）
- 卡顿检测（ANR 监控）
- 自定义 Key-Value 上报（玩家 ID、场景信息等）
- 远程日志（线上玩家实时日志捕获）

---

## 2. CrashSight 集成

### 2.1 初始化

```csharp
// 位置：SDK/GCloudSDK/Scripts/CrashSight/CrashSightAgent.cs
// 在游戏启动时（Index.cs / PatchManager.cs）调用
public sealed class CrashSightAgent
{
    private static bool _isInitialized = false;
    
    // 初始化（必须在主线程调用）
    public static void InitWithAppId(string appId)
    {
        if (IsInitialized) return;  // 防重复初始化
        
        // 注册 Unity 日志回调
        Application.logMessageReceived += HandleLog;
        Application.logMessageReceivedThreaded += HandleLogThreaded;
        
        // 初始化 Native 层（Android JNI / iOS OC 接口）
        UQM.InitWithAppId(appId);
        
        _isInitialized = true;
    }
    
    // 处理 Unity 日志回调（主线程）
    private static void HandleLog(string condition, string stackTrace, LogType type)
    {
        if (type == LogType.Error || type == LogType.Exception)
        {
            // 达到自动上报级别，立即上报
            if (IsAutoReportLevel(type))
            {
                ReportException(condition, stackTrace, true);
            }
        }
    }
```

### 2.2 自定义 Key-Value 上报

```csharp
    // 上报玩家信息（出现崩溃时可以快速定位是哪个玩家）
    public static void SetUserId(string userId)
    {
        UQM.SetUserId(userId);
    }
    
    // 附加自定义数据（崩溃时会一起上报，帮助定位问题）
    public static void SetCustomKey(string key, string value)
    {
        UQM.SetCustomKey(key, value);
    }
    
    // 典型使用：玩家登录后设置
    public static void OnPlayerLogin(string openId, string serverId)
    {
        SetUserId(openId);
        SetCustomKey("server_id", serverId);
        SetCustomKey("client_version", Application.version);
        SetCustomKey("device_model", SystemInfo.deviceModel);
    }
    
    // 典型使用：战斗开始时上报战斗信息（方便定位战斗内崩溃）
    public static void OnBattleStart(int battleId, int characterId)
    {
        SetCustomKey("current_battle_id", battleId.ToString());
        SetCustomKey("current_character_id", characterId.ToString());
    }
```

### 2.3 主动异常上报

```csharp
    // 主动上报（非崩溃场景：逻辑错误、数据异常）
    public static void ReportException(Exception e, string message)
    {
        ReportException(e.Message, e.StackTrace, false);
        
        // 也可以上报自定义异常（不需要真正的 Exception 对象）
        UQM.ReportException(1,   // 类型：1=自定义异常
            message,              // 异常名称
            e.StackTrace,         // 堆栈
            false);               // 是否立即上传（false=等下次启动批量上报）
    }
    
    // 使用示例
    public static async ETTask<bool> LoadSkillConfig(int skillId)
    {
        var cfg = CfgManager.tables.TbSkill.GetOrDefault(skillId);
        if (cfg == null)
        {
            // 配置缺失不是崩溃，但要上报给 CrashSight 方便策划修复
            CrashSightAgent.ReportException(
                new Exception($"技能配置不存在: {skillId}"),
                $"[LoadSkillConfig] 场景: {SceneManager.GetActiveScene().name}");
            return false;
        }
        return true;
    }
```

---

## 3. ANR（应用无响应）监控

```csharp
    // CrashSight 的 ANR 检测（Android 专属）
    // 当主线程超过 5 秒无响应时，自动触发 ANR 上报
    
    // 如何避免 ANR：
    // 1. 配置加载不能同步等待（用 LoadAll() 异步加载）
    // 2. 帧同步追帧不能锁死（追帧时每批次 yield 一帧）
    // 3. 资源解密不能在主线程（用 ThreadPool 或 ETTask.Run）
    
    // 帧同步追帧时的 ANR 防护示例
    private static async ETTask CatchUpFrames(this LockStepComponent self, int targetFrame)
    {
        const int BATCH_SIZE = 30;  // 每批次追 30 帧，然后 yield
        int processed = 0;
        
        while (self.battlePlayerComp.FrameIndex < targetFrame)
        {
            self.ProcessNextFrame();
            processed++;
            
            // 每 30 帧让出一次主线程（防止 ANR）
            if (processed % BATCH_SIZE == 0)
            {
                await TimerComponent.Instance.WaitFrameAsync();
            }
        }
    }
```

---

## 4. 远程日志（Remote Log）

```csharp
    // CrashSight 支持在后台控制台指定特定用户开启详细日志
    // 玩家无感知，日志实时上传到 CrashSight 后台
    
    public static void EnableRemoteLog(string userId)
    {
        CrashSightAgent.SetUserId(userId);
        // CrashSight 后台可以给特定 userId 发送"开启远程日志"指令
        // SDK 会自动处理指令响应，客户端无需额外代码
    }
    
    // 自定义日志级别（决定哪些日志会被 CrashSight 捕获）
    // 生产环境只捕获 Warning 以上（减少上报量）
    // 线上问题调查时可临时降到 Debug 级别
    private static CSLogSeverity _autoReportLogLevel = CSLogSeverity.LogWarning;
```

---

## 5. 数据分析与埋点（TDM/MSDK）

```csharp
// 用户行为上报（配合 GCloud TDM SDK）
public static class DataAnalytics
{
    // 战斗开始埋点
    public static void TrackBattleStart(int battleId, string matchType)
    {
        var props = new Dictionary<string, string>
        {
            { "battle_id", battleId.ToString() },
            { "match_type", matchType },          // pvp/pve/coop
            { "character_id", GetCharacterId() },
            { "server_time", GetServerTimestamp() }
        };
        TDM.TrackEvent("battle_start", props);
    }
    
    // 战斗结束埋点（结算数据）
    public static void TrackBattleEnd(BattleResult result)
    {
        TDM.TrackEvent("battle_end", new Dictionary<string, string>
        {
            { "result", result.IsWin ? "win" : "lose" },
            { "duration_seconds", result.Duration.ToString() },
            { "kill_count", result.KillCount.ToString() },
            { "damage_dealt", result.TotalDamage.ToString() }
        });
    }
    
    // 购买行为埋点（经济分析）
    public static void TrackPurchase(int itemId, int price, string currency)
    {
        TDM.TrackEvent("item_purchase", new Dictionary<string, string>
        {
            { "item_id", itemId.ToString() },
            { "price", price.ToString() },
            { "currency", currency }
        });
    }
}
```

---

## 6. 崩溃率监控 SLO

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 崩溃率 | < 0.1% | 100 次会话中崩溃不超过 1 次 |
| ANR率 | < 0.05% | Android 应用无响应率 |
| OOM率 | < 0.02% | Out of Memory 崩溃率 |
| 卡顿率 | < 5% | 帧率低于目标 80% 的帧数占比 |

---

## 7. 常见问题与最佳实践

**Q: 线上崩溃堆栈全是问号（符号化失败）怎么办？**  
A: 检查是否在构建时上传了对应版本的符号文件（Android .so、iOS dSYM）。CrashSight 后台有符号文件管理页面，确保版本号对应。

**Q: 热更新后崩溃堆栈还能符号化吗？**  
A: HybridCLR 热更新的 C# 代码在 IL2CPP 后是 Native 代码，需要专门的符号映射表。IL2CPP 构建时保留 `cpp/Il2CppOutputProject/Source` 目录，配合 CrashSight 的 IL2CPP 专项支持进行符号化。

**Q: 埋点数据量很大，会影响性能吗？**  
A: TDM SDK 内置批量上报（攒够 N 条或每隔 T 秒上报一次），不会每次事件都发网络请求。避免在 Update() 中埋点，只在关键状态变化时调用。
