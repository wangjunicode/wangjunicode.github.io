---
title: 游戏客户端Feature Flag动态功能开关系统完全指南
published: 2026-04-19
description: 深入讲解游戏客户端Feature Flag（功能开关）系统的设计与实现，涵盖灰度发布、A/B测试、功能降级、远程配置、运营活动控制等核心场景，提供完整的架构设计、代码实现与最佳实践
tags: [Unity, 功能开关, 灰度发布, AB测试, 运营系统, 架构设计, 游戏开发]
category: 系统架构
draft: false
---

# 游戏客户端Feature Flag动态功能开关系统完全指南

## 1. 为什么游戏需要Feature Flag？

大型游戏项目面临的核心挑战：

- **新功能风险控制**：新战斗系统上线可能引入严重Bug，需要能1分钟内全量关闭
- **灰度发布**：新英雄技能先对5%玩家开放，验证稳定后再全量
- **A/B测试**：对照组看商店布局A，实验组看布局B，比较转化率
- **差异化运营**：VIP用户提前体验新内容，特定地区关闭特定功能（合规）
- **紧急降级**：服务器压力过大时自动关闭高消耗功能（社交动态实时同步）
- **版本兼容**：旧客户端不展示新UI，等待玩家强制更新

Feature Flag系统正是解决这些问题的核心基础设施。

---

## 2. 系统架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Feature Flag 系统                         │
├─────────────────┬───────────────────┬───────────────────────┤
│   配置数据源层   │     评估引擎层     │      应用层            │
│                 │                   │                       │
│ ┌─────────────┐ │ ┌───────────────┐ │ ┌───────────────────┐ │
│ │ 远程配置服务 │ │ │ 规则评估引擎   │ │ │   游戏功能代码     │ │
│ │ (HTTP/CDN)  │ │ │               │ │ │                   │ │
│ └─────────────┘ │ │ · 用户分组     │ │ │ if(ff.IsEnabled  │ │
│ ┌─────────────┐ │ │ · 百分比灰度   │ │ │  ("new_skill"))  │ │
│ │ 本地覆盖文件 │ │ │ · 时间窗口     │ │ │ { ... }          │ │
│ │ (开发调试)  │ │ │ · 版本约束     │ │ └───────────────────┘ │
│ └─────────────┘ │ │ · 地区过滤     │ │ ┌───────────────────┐ │
│ ┌─────────────┐ │ └───────────────┘ │ │   Debug工具UI     │ │
│ │ 内置默认值  │ │ ┌───────────────┐ │ │   (编辑器面板)    │ │
│ │ (兜底保障)  │ │ │   缓存层      │ │ └───────────────────┘ │
│ └─────────────┘ │ │ (PlayerPrefs) │ │                       │
│                 │ └───────────────┘ │                       │
└─────────────────┴───────────────────┴───────────────────────┘
```

### 2.2 Feature Flag数据模型

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Feature Flag定义 - 支持布尔开关、数值配置、字符串变体
/// </summary>
[Serializable]
public class FeatureFlag
{
    /// <summary>唯一标识符（建议使用命名空间前缀，如 "combat.new_skill_system"）</summary>
    public string Key { get; set; }
    
    /// <summary>显示名称（便于运营理解）</summary>
    public string DisplayName { get; set; }
    
    /// <summary>功能描述</summary>
    public string Description { get; set; }
    
    /// <summary>Flag类型</summary>
    public FlagType Type { get; set; }
    
    /// <summary>默认值（当所有规则不匹配时使用）</summary>
    public FlagVariant DefaultVariant { get; set; }
    
    /// <summary>启用状态（全局总开关）</summary>
    public bool IsActive { get; set; } = true;
    
    /// <summary>规则列表（按优先级排序）</summary>
    public List<FlagRule> Rules { get; set; } = new();
    
    /// <summary>生效版本范围</summary>
    public VersionRange VersionRange { get; set; }
    
    /// <summary>标签（用于批量管理，如 "season_1", "emergency"）</summary>
    public List<string> Tags { get; set; } = new();
}

public enum FlagType
{
    Boolean,    // 开关类型：true/false
    String,     // 字符串变体：不同的UI文本、资源路径
    Number,     // 数值配置：经济系数、难度系数
    Json,       // JSON对象：复杂配置（技能参数表）
}

[Serializable]
public class FlagVariant
{
    public string VariantKey { get; set; }   // 变体标识，如 "control", "treatment_a"
    public bool   BoolValue  { get; set; }
    public string StringValue { get; set; }
    public double NumberValue { get; set; }
    public string JsonValue  { get; set; }
    
    /// <summary>曝光权重（用于A/B测试流量分配）</summary>
    public float Weight { get; set; } = 1.0f;
}

[Serializable]
public class FlagRule
{
    public int Priority { get; set; }            // 数字越小优先级越高
    public string VariantKey { get; set; }       // 命中此规则时返回的变体
    public List<FlagCondition> Conditions { get; set; } = new();
    public RuleOperator Operator { get; set; } = RuleOperator.And; // 条件组合方式
}

[Serializable]
public class FlagCondition
{
    public ConditionType Type { get; set; }
    public string Key { get; set; }             // 属性键（如 "user_level", "region"）
    public ConditionOperator Op { get; set; }
    public string Value { get; set; }           // 比较值
}

public enum ConditionType
{
    UserAttribute,    // 用户属性（等级、VIP等级、账龄）
    UserSegment,      // 用户分群（白名单、黑名单）
    PercentageRollout,// 百分比灰度
    AppVersion,       // 客户端版本
    Platform,         // 平台（iOS/Android/PC）
    Region,           // 地区/语言
    DateTimeRange,    // 时间窗口
    DeviceGrade,      // 设备性能等级
}

public enum ConditionOperator
{
    Equals, NotEquals, GreaterThan, LessThan, 
    Contains, StartsWith, In, NotIn, Between
}

public enum RuleOperator { And, Or }

[Serializable]
public class VersionRange
{
    public string MinVersion { get; set; }  // 最低版本，null表示无限制
    public string MaxVersion { get; set; }  // 最高版本，null表示无限制
}
```

---

## 3. 核心评估引擎实现

```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

/// <summary>
/// Feature Flag评估引擎 - 单例，负责所有Flag的评估逻辑
/// </summary>
public class FeatureFlagEngine : MonoBehaviour
{
    private static FeatureFlagEngine _instance;
    public static FeatureFlagEngine Instance => _instance;
    
    // Flag定义字典（Key -> FeatureFlag）
    private Dictionary<string, FeatureFlag> _flags = new();
    
    // 评估结果缓存（避免重复计算）
    private Dictionary<string, FlagVariant> _evaluationCache = new();
    private bool _cacheValid = false;
    
    // 当前用户上下文
    private EvaluationContext _userContext;
    
    // 事件：Flag值发生变化
    public event Action<string, FlagVariant> OnFlagChanged;
    
    private void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }
    
    /// <summary>
    /// 初始化 - 传入用户上下文和初始配置
    /// </summary>
    public void Initialize(EvaluationContext userContext, List<FeatureFlag> initialFlags)
    {
        _userContext = userContext;
        LoadFlags(initialFlags);
        Debug.Log($"[FeatureFlag] 初始化完成，加载 {_flags.Count} 个Flag");
    }
    
    /// <summary>
    /// 更新Flag配置（来自远程配置服务）
    /// </summary>
    public void UpdateFlags(List<FeatureFlag> newFlags)
    {
        var oldCache = new Dictionary<string, FlagVariant>(_evaluationCache);
        
        LoadFlags(newFlags);
        InvalidateCache();
        
        // 检测变更并触发事件
        foreach (var key in _flags.Keys)
        {
            var newVariant = EvaluateFlag(key);
            if (oldCache.TryGetValue(key, out var oldVariant))
            {
                if (newVariant?.VariantKey != oldVariant?.VariantKey)
                {
                    OnFlagChanged?.Invoke(key, newVariant);
                    Debug.Log($"[FeatureFlag] Flag变更: {key} -> {newVariant?.VariantKey}");
                }
            }
        }
    }
    
    private void LoadFlags(List<FeatureFlag> flags)
    {
        _flags.Clear();
        foreach (var flag in flags)
        {
            _flags[flag.Key] = flag;
        }
        InvalidateCache();
    }
    
    private void InvalidateCache()
    {
        _evaluationCache.Clear();
        _cacheValid = false;
    }
    
    // ============================================
    // 公共评估接口
    // ============================================
    
    /// <summary>
    /// 布尔Flag评估（最常用）
    /// </summary>
    public bool IsEnabled(string flagKey, bool defaultValue = false)
    {
        var variant = EvaluateFlag(flagKey);
        return variant?.BoolValue ?? defaultValue;
    }
    
    /// <summary>
    /// 字符串变体评估（A/B测试场景）
    /// </summary>
    public string GetVariant(string flagKey, string defaultVariant = "control")
    {
        var variant = EvaluateFlag(flagKey);
        return variant?.VariantKey ?? defaultVariant;
    }
    
    /// <summary>
    /// 数值配置获取
    /// </summary>
    public double GetNumber(string flagKey, double defaultValue = 0)
    {
        var variant = EvaluateFlag(flagKey);
        return variant?.NumberValue ?? defaultValue;
    }
    
    /// <summary>
    /// 字符串值获取
    /// </summary>
    public string GetString(string flagKey, string defaultValue = "")
    {
        var variant = EvaluateFlag(flagKey);
        return variant?.StringValue ?? defaultValue;
    }
    
    /// <summary>
    /// JSON配置获取并反序列化
    /// </summary>
    public T GetJson<T>(string flagKey, T defaultValue = default)
    {
        var variant = EvaluateFlag(flagKey);
        if (variant?.JsonValue == null) return defaultValue;
        
        try
        {
            return JsonUtility.FromJson<T>(variant.JsonValue);
        }
        catch (Exception e)
        {
            Debug.LogError($"[FeatureFlag] JSON解析失败 {flagKey}: {e.Message}");
            return defaultValue;
        }
    }
    
    // ============================================
    // 核心评估逻辑
    // ============================================
    
    private FlagVariant EvaluateFlag(string flagKey)
    {
        // 缓存命中
        if (_evaluationCache.TryGetValue(flagKey, out var cached))
            return cached;
        
        if (!_flags.TryGetValue(flagKey, out var flag))
        {
            Debug.LogWarning($"[FeatureFlag] 未知Flag: {flagKey}");
            return null;
        }
        
        // 全局禁用
        if (!flag.IsActive)
        {
            var result = flag.DefaultVariant;
            _evaluationCache[flagKey] = result;
            return result;
        }
        
        // 版本检查
        if (!CheckVersionRange(flag.VersionRange))
        {
            var result = flag.DefaultVariant;
            _evaluationCache[flagKey] = result;
            return result;
        }
        
        // 按优先级评估规则
        var sortedRules = flag.Rules.OrderBy(r => r.Priority).ToList();
        
        foreach (var rule in sortedRules)
        {
            if (EvaluateRule(rule))
            {
                var variant = flag.Rules
                    .SelectMany(r => new[] { flag.DefaultVariant })
                    .FirstOrDefault(v => v?.VariantKey == rule.VariantKey) 
                    ?? flag.DefaultVariant;
                
                _evaluationCache[flagKey] = variant;
                return variant;
            }
        }
        
        // 没有规则匹配，返回默认值
        _evaluationCache[flagKey] = flag.DefaultVariant;
        return flag.DefaultVariant;
    }
    
    private bool EvaluateRule(FlagRule rule)
    {
        if (rule.Conditions.Count == 0) return true;
        
        if (rule.Operator == RuleOperator.And)
            return rule.Conditions.All(c => EvaluateCondition(c));
        else
            return rule.Conditions.Any(c => EvaluateCondition(c));
    }
    
    private bool EvaluateCondition(FlagCondition condition)
    {
        return condition.Type switch
        {
            ConditionType.UserAttribute     => EvaluateUserAttribute(condition),
            ConditionType.PercentageRollout => EvaluatePercentage(condition),
            ConditionType.AppVersion        => EvaluateVersion(condition),
            ConditionType.Platform          => EvaluatePlatform(condition),
            ConditionType.Region            => EvaluateRegion(condition),
            ConditionType.DateTimeRange     => EvaluateDateTimeRange(condition),
            ConditionType.UserSegment       => EvaluateUserSegment(condition),
            ConditionType.DeviceGrade       => EvaluateDeviceGrade(condition),
            _ => false
        };
    }
    
    private bool EvaluateUserAttribute(FlagCondition condition)
    {
        if (_userContext?.Attributes == null) return false;
        if (!_userContext.Attributes.TryGetValue(condition.Key, out var value)) return false;
        
        return condition.Op switch
        {
            ConditionOperator.Equals      => value == condition.Value,
            ConditionOperator.NotEquals   => value != condition.Value,
            ConditionOperator.GreaterThan => CompareNumeric(value, condition.Value) > 0,
            ConditionOperator.LessThan    => CompareNumeric(value, condition.Value) < 0,
            ConditionOperator.Contains    => value.Contains(condition.Value),
            ConditionOperator.In          => condition.Value.Split(',').Contains(value),
            _ => false
        };
    }
    
    private bool EvaluatePercentage(FlagCondition condition)
    {
        // 基于用户ID的哈希值，确保同一用户每次得到相同结果（稳定性）
        string seed = $"{_userContext?.UserId}:{condition.Key}";
        float hash = (float)(GetStableHash(seed) % 10000) / 100f; // 0~100
        
        if (float.TryParse(condition.Value, out float percentage))
            return hash < percentage;
        
        return false;
    }
    
    private bool EvaluateVersion(FlagCondition condition)
    {
        string currentVersion = Application.version;
        return condition.Op switch
        {
            ConditionOperator.GreaterThan => CompareVersion(currentVersion, condition.Value) > 0,
            ConditionOperator.LessThan    => CompareVersion(currentVersion, condition.Value) < 0,
            ConditionOperator.Equals      => CompareVersion(currentVersion, condition.Value) == 0,
            _ => false
        };
    }
    
    private bool EvaluatePlatform(FlagCondition condition)
    {
        string platform = Application.platform switch
        {
            RuntimePlatform.IPhonePlayer  => "iOS",
            RuntimePlatform.Android       => "Android",
            RuntimePlatform.WindowsPlayer => "Windows",
            RuntimePlatform.OSXPlayer     => "macOS",
            _                             => "Unknown"
        };
        
        var platforms = condition.Value.Split(',').Select(p => p.Trim());
        return condition.Op switch
        {
            ConditionOperator.In    => platforms.Contains(platform),
            ConditionOperator.NotIn => !platforms.Contains(platform),
            ConditionOperator.Equals => platform == condition.Value,
            _ => false
        };
    }
    
    private bool EvaluateRegion(FlagCondition condition)
    {
        string region = _userContext?.Region ?? Application.systemLanguage.ToString();
        var regions = condition.Value.Split(',').Select(r => r.Trim());
        
        return condition.Op switch
        {
            ConditionOperator.In    => regions.Contains(region, StringComparer.OrdinalIgnoreCase),
            ConditionOperator.NotIn => !regions.Contains(region, StringComparer.OrdinalIgnoreCase),
            _ => false
        };
    }
    
    private bool EvaluateDateTimeRange(FlagCondition condition)
    {
        // 格式: "2026-04-01T00:00:00~2026-04-30T23:59:59"
        var parts = condition.Value.Split('~');
        if (parts.Length != 2) return false;
        
        if (DateTime.TryParse(parts[0], out var startTime) && 
            DateTime.TryParse(parts[1], out var endTime))
        {
            var now = DateTime.UtcNow;
            return now >= startTime && now <= endTime;
        }
        return false;
    }
    
    private bool EvaluateUserSegment(FlagCondition condition)
    {
        // 检查用户是否在特定分群中（白名单/黑名单）
        var segmentUsers = condition.Value.Split(',').Select(u => u.Trim());
        bool inSegment = segmentUsers.Contains(_userContext?.UserId);
        
        return condition.Op switch
        {
            ConditionOperator.In    => inSegment,
            ConditionOperator.NotIn => !inSegment,
            _ => false
        };
    }
    
    private bool EvaluateDeviceGrade(FlagCondition condition)
    {
        // 设备性能等级：Low/Medium/High/Ultra
        int gpuMem = SystemInfo.graphicsMemorySize;
        string grade = gpuMem switch
        {
            > 8000 => "Ultra",
            > 4000 => "High",
            > 2000 => "Medium",
            _      => "Low"
        };
        
        return condition.Value.Contains(grade);
    }
    
    private bool CheckVersionRange(VersionRange versionRange)
    {
        if (versionRange == null) return true;
        
        string current = Application.version;
        
        if (!string.IsNullOrEmpty(versionRange.MinVersion) &&
            CompareVersion(current, versionRange.MinVersion) < 0) return false;
        
        if (!string.IsNullOrEmpty(versionRange.MaxVersion) &&
            CompareVersion(current, versionRange.MaxVersion) > 0) return false;
        
        return true;
    }
    
    // 工具方法
    private int CompareNumeric(string a, string b)
    {
        if (double.TryParse(a, out var da) && double.TryParse(b, out var db))
            return da.CompareTo(db);
        return string.Compare(a, b, StringComparison.Ordinal);
    }
    
    private int CompareVersion(string a, string b)
    {
        var partsA = a.Split('.').Select(int.Parse).ToArray();
        var partsB = b.Split('.').Select(int.Parse).ToArray();
        int len = Math.Max(partsA.Length, partsB.Length);
        
        for (int i = 0; i < len; i++)
        {
            int va = i < partsA.Length ? partsA[i] : 0;
            int vb = i < partsB.Length ? partsB[i] : 0;
            if (va != vb) return va.CompareTo(vb);
        }
        return 0;
    }
    
    private uint GetStableHash(string input)
    {
        // FNV-1a哈希，稳定可预测
        uint hash = 2166136261u;
        foreach (char c in input)
        {
            hash ^= c;
            hash *= 16777619u;
        }
        return hash;
    }
}

/// <summary>
/// 用户评估上下文 - 描述当前用户的所有属性
/// </summary>
public class EvaluationContext
{
    public string UserId { get; set; }
    public string Region { get; set; }
    public Dictionary<string, string> Attributes { get; set; } = new();
    
    /// <summary>
    /// 快捷方法：设置常用游戏属性
    /// </summary>
    public static EvaluationContext Create(string userId)
    {
        return new EvaluationContext
        {
            UserId = userId,
            Region = Application.systemLanguage.ToString(),
            Attributes = new Dictionary<string, string>
            {
                ["platform"] = Application.platform.ToString(),
                ["app_version"] = Application.version,
                ["device_grade"] = GetDeviceGrade(),
            }
        };
    }
    
    public EvaluationContext WithAttribute(string key, string value)
    {
        Attributes[key] = value;
        return this;
    }
    
    public EvaluationContext WithPlayerLevel(int level) => WithAttribute("player_level", level.ToString());
    public EvaluationContext WithVIPGrade(int grade) => WithAttribute("vip_grade", grade.ToString());
    public EvaluationContext WithAccountAge(int days) => WithAttribute("account_age_days", days.ToString());
    
    private static string GetDeviceGrade()
    {
        int gpuMem = SystemInfo.graphicsMemorySize;
        return gpuMem switch { > 8000 => "Ultra", > 4000 => "High", > 2000 => "Medium", _ => "Low" };
    }
}
```

---

## 4. 远程配置服务集成

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// 远程Feature Flag配置服务 - 支持HTTP拉取、增量更新、本地缓存
/// </summary>
public class FeatureFlagRemoteService : MonoBehaviour
{
    [Header("服务配置")]
    [SerializeField] private string remoteConfigUrl = "https://config.yourgame.com/api/v1/flags";
    [SerializeField] private float refreshInterval = 300f;  // 5分钟刷新一次
    [SerializeField] private float retryDelay = 30f;
    [SerializeField] private int maxRetries = 3;
    
    [Header("本地缓存")]
    [SerializeField] private TextAsset defaultConfig;  // 内置默认配置（离线保底）
    
    private const string CacheKey = "ff_config_cache";
    private const string CacheVersionKey = "ff_config_version";
    private const string CacheTimestampKey = "ff_config_timestamp";
    
    private Coroutine refreshCoroutine;
    
    private void Start()
    {
        StartCoroutine(InitializeAndRefresh());
    }
    
    private IEnumerator InitializeAndRefresh()
    {
        // 1. 优先使用本地缓存（快速启动，避免白屏等待）
        if (TryLoadFromCache(out var cachedFlags))
        {
            FeatureFlagEngine.Instance.UpdateFlags(cachedFlags);
            Debug.Log($"[FeatureFlag] 从本地缓存加载 {cachedFlags.Count} 个Flag");
        }
        else if (defaultConfig != null)
        {
            // 2. 使用内置默认配置
            var defaultFlags = ParseFlagConfig(defaultConfig.text);
            FeatureFlagEngine.Instance.UpdateFlags(defaultFlags);
            Debug.Log($"[FeatureFlag] 使用内置默认配置 {defaultFlags.Count} 个Flag");
        }
        
        // 3. 异步拉取最新远程配置
        yield return FetchRemoteConfig();
        
        // 4. 定期刷新
        refreshCoroutine = StartCoroutine(PeriodicRefresh());
    }
    
    private IEnumerator FetchRemoteConfig(int retryCount = 0)
    {
        string etag = PlayerPrefs.GetString(CacheVersionKey, "");
        string url = $"{remoteConfigUrl}?platform={Application.platform}&version={Application.version}";
        
        using var request = UnityWebRequest.Get(url);
        request.SetRequestHeader("If-None-Match", etag);
        request.SetRequestHeader("X-App-Version", Application.version);
        request.SetRequestHeader("X-User-Id", GetUserId());
        request.timeout = 10;
        
        yield return request.SendWebRequest();
        
        if (request.result == UnityWebRequest.Result.Success)
        {
            if (request.responseCode == 304)
            {
                Debug.Log("[FeatureFlag] 配置未变更（304）");
                yield break;
            }
            
            string responseText = request.downloadHandler.text;
            string newEtag = request.GetResponseHeader("ETag");
            
            var newFlags = ParseFlagConfig(responseText);
            if (newFlags != null)
            {
                // 更新缓存
                PlayerPrefs.SetString(CacheKey, responseText);
                PlayerPrefs.SetString(CacheVersionKey, newEtag ?? "");
                PlayerPrefs.SetFloat(CacheTimestampKey, Time.realtimeSinceStartup);
                PlayerPrefs.Save();
                
                // 应用新配置
                FeatureFlagEngine.Instance.UpdateFlags(newFlags);
                Debug.Log($"[FeatureFlag] 远程配置更新成功，{newFlags.Count} 个Flag");
            }
        }
        else if (retryCount < maxRetries)
        {
            Debug.LogWarning($"[FeatureFlag] 拉取失败({request.error})，{retryDelay}秒后重试 ({retryCount + 1}/{maxRetries})");
            yield return new WaitForSeconds(retryDelay);
            yield return FetchRemoteConfig(retryCount + 1);
        }
        else
        {
            Debug.LogError($"[FeatureFlag] 远程配置拉取失败，使用缓存数据");
        }
    }
    
    private IEnumerator PeriodicRefresh()
    {
        while (true)
        {
            yield return new WaitForSeconds(refreshInterval);
            yield return FetchRemoteConfig();
        }
    }
    
    private bool TryLoadFromCache(out List<FeatureFlag> flags)
    {
        flags = null;
        
        string cachedJson = PlayerPrefs.GetString(CacheKey, "");
        if (string.IsNullOrEmpty(cachedJson)) return false;
        
        float cacheTimestamp = PlayerPrefs.GetFloat(CacheTimestampKey, 0);
        float cacheAge = Time.realtimeSinceStartup - cacheTimestamp;
        
        // 缓存超过24小时则强制刷新（但仍先使用旧缓存保证功能可用）
        if (cacheAge > 86400f)
            Debug.LogWarning("[FeatureFlag] 本地缓存已超过24小时，将从远端更新");
        
        flags = ParseFlagConfig(cachedJson);
        return flags != null && flags.Count > 0;
    }
    
    private List<FeatureFlag> ParseFlagConfig(string json)
    {
        try
        {
            var config = JsonUtility.FromJson<FeatureFlagConfig>(json);
            return config?.Flags ?? new List<FeatureFlag>();
        }
        catch (Exception e)
        {
            Debug.LogError($"[FeatureFlag] 配置解析失败: {e.Message}");
            return null;
        }
    }
    
    private string GetUserId()
    {
        string id = PlayerPrefs.GetString("anonymous_user_id", "");
        if (string.IsNullOrEmpty(id))
        {
            id = Guid.NewGuid().ToString("N");
            PlayerPrefs.SetString("anonymous_user_id", id);
        }
        return id;
    }
    
    private void OnDestroy()
    {
        if (refreshCoroutine != null)
            StopCoroutine(refreshCoroutine);
    }
}

[Serializable]
public class FeatureFlagConfig
{
    public List<FeatureFlag> Flags;
    public string ConfigVersion;
    public long UpdatedAt;
}
```

---

## 5. 实际业务场景应用

### 5.1 新英雄灰度上线

```csharp
/// <summary>
/// 英雄解锁系统 - 集成Feature Flag进行灰度控制
/// </summary>
public class HeroUnlockSystem : MonoBehaviour
{
    private FeatureFlagEngine ff;
    
    private void Start()
    {
        ff = FeatureFlagEngine.Instance;
        
        // 监听Flag变化（远程推送立即生效）
        ff.OnFlagChanged += OnFlagChanged;
    }
    
    private void OnFlagChanged(string flagKey, FlagVariant variant)
    {
        if (flagKey == "heroes.new_assassin_luna")
        {
            // Flag变化时更新英雄选择界面
            RefreshHeroSelectUI();
        }
    }
    
    /// <summary>
    /// 检查英雄是否在当前版本可用
    /// </summary>
    public bool IsHeroAvailable(string heroId)
    {
        // 方式一：简单布尔开关
        if (heroId == "luna_assassin")
        {
            return ff.IsEnabled("heroes.new_assassin_luna", defaultValue: false);
        }
        
        // 方式二：版本控制（新英雄仅在1.5.0+版本显示）
        if (heroId == "storm_mage")
        {
            return ff.IsEnabled("heroes.storm_mage", defaultValue: false);
        }
        
        return true;
    }
    
    /// <summary>
    /// 获取英雄价格（A/B测试不同定价策略）
    /// </summary>
    public int GetHeroPriceGems(string heroId)
    {
        string variant = ff.GetVariant($"pricing.hero_{heroId}", "control");
        
        return variant switch
        {
            "control"     => 980,   // 原价
            "discount_a"  => 780,   // 80折
            "discount_b"  => 680,   // 特惠价
            "free_trial"  => 0,     // 免费试玩（7天）
            _ => 980
        };
    }
    
    private void RefreshHeroSelectUI() { /* 刷新UI */ }
}
```

### 5.2 紧急功能降级

```csharp
/// <summary>
/// 功能降级控制器 - 服务器压力过大时自动关闭高消耗功能
/// </summary>
public static class FeatureDegradation
{
    private static readonly FeatureFlagEngine FF = FeatureFlagEngine.Instance;
    
    // 实时社交功能（高频网络请求）
    public static bool EnableRealtimeFriendActivity 
        => FF.IsEnabled("social.realtime_friend_activity", true);
    
    // 实时排行榜（数据库高并发）
    public static bool EnableRealtimeLeaderboard 
        => FF.IsEnabled("leaderboard.realtime_update", true);
    
    // 大厅动态特效（GPU密集型）
    public static bool EnableLobbyDynamicEffects 
        => FF.IsEnabled("ui.lobby_dynamic_effects", true);
    
    // 语音频道（带宽密集型）
    public static bool EnableVoiceChat 
        => FF.IsEnabled("social.voice_chat", true);
    
    /// <summary>
    /// 功能降级状态日志（运维监控用）
    /// </summary>
    public static string GetDegradationStatus()
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("=== 功能降级状态 ===");
        sb.AppendLine($"实时好友动态: {(EnableRealtimeFriendActivity ? "✅开启" : "❌关闭")}");
        sb.AppendLine($"实时排行榜:   {(EnableRealtimeLeaderboard ? "✅开启" : "❌关闭")}");
        sb.AppendLine($"大厅动态特效: {(EnableLobbyDynamicEffects ? "✅开启" : "❌关闭")}");
        sb.AppendLine($"语音聊天:     {(EnableVoiceChat ? "✅开启" : "❌关闭")}");
        return sb.ToString();
    }
}
```

### 5.3 新手引导A/B测试

```csharp
/// <summary>
/// 新手引导系统 - A/B测试不同引导流程的完成率
/// </summary>
public class TutorialABTest : MonoBehaviour
{
    private FeatureFlagEngine ff;
    private string tutorialVariant;
    
    private void Start()
    {
        ff = FeatureFlagEngine.Instance;
        tutorialVariant = ff.GetVariant("tutorial.onboarding_v2", "control");
        
        Debug.Log($"[Tutorial] 当前A/B变体: {tutorialVariant}");
        
        // 上报曝光事件（用于统计分析）
        Analytics.ReportEvent("tutorial_ab_exposure", new Dictionary<string, object>
        {
            ["variant"] = tutorialVariant,
            ["user_id"] = GetUserId()
        });
    }
    
    public void StartTutorial()
    {
        switch (tutorialVariant)
        {
            case "control":
                StartCoroutine(RunOriginalTutorial());
                break;
            case "streamlined":
                StartCoroutine(RunStreamlinedTutorial()); // 简化版，减少步骤
                break;
            case "interactive":
                StartCoroutine(RunInteractiveTutorial()); // 互动式，更多实操
                break;
            case "skip":
                SkipTutorial(); // 允许跳过（测试无引导完成率）
                break;
        }
    }
    
    private IEnumerator RunOriginalTutorial() { /* 原始引导流程 */ yield break; }
    private IEnumerator RunStreamlinedTutorial() { /* 简化引导 */ yield break; }
    private IEnumerator RunInteractiveTutorial() { /* 互动引导 */ yield break; }
    private void SkipTutorial() { /* 跳过引导 */ }
    private string GetUserId() => PlayerPrefs.GetString("user_id", "");
}
```

---

## 6. Editor工具：调试面板

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// Feature Flag调试窗口 - 开发时快速覆盖Flag值
/// </summary>
public class FeatureFlagDebugWindow : EditorWindow
{
    [MenuItem("Tools/Feature Flag Debugger")]
    public static void ShowWindow()
    {
        GetWindow<FeatureFlagDebugWindow>("Feature Flags");
    }
    
    private Dictionary<string, bool> localOverrides = new();
    private Vector2 scrollPos;
    private string searchFilter = "";
    
    // 开发环境本地覆盖（存储在EditorPrefs中）
    private const string OverridePrefix = "ff_override_";
    
    private void OnGUI()
    {
        EditorGUILayout.LabelField("Feature Flag 调试面板", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox("本地覆盖仅在编辑器中生效，不影响远程配置", MessageType.Info);
        
        EditorGUILayout.Space();
        searchFilter = EditorGUILayout.TextField("搜索:", searchFilter);
        
        EditorGUILayout.Space();
        
        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("需要在Play模式下使用", MessageType.Warning);
            return;
        }
        
        var engine = FeatureFlagEngine.Instance;
        if (engine == null)
        {
            EditorGUILayout.HelpBox("FeatureFlagEngine未初始化", MessageType.Error);
            return;
        }
        
        scrollPos = EditorGUILayout.BeginScrollView(scrollPos);
        
        // 预定义的调试Flag列表
        var debugFlags = new[]
        {
            ("heroes.new_assassin_luna",    "新英雄Luna"),
            ("social.realtime_friend_activity", "实时好友动态"),
            ("tutorial.onboarding_v2",      "新手引导V2"),
            ("ui.lobby_dynamic_effects",    "大厅动态特效"),
            ("social.voice_chat",           "语音聊天"),
            ("leaderboard.realtime_update", "实时排行榜"),
        };
        
        foreach (var (key, displayName) in debugFlags)
        {
            if (!string.IsNullOrEmpty(searchFilter) && 
                !key.Contains(searchFilter) && !displayName.Contains(searchFilter))
                continue;
            
            EditorGUILayout.BeginHorizontal("box");
            
            bool currentValue = engine.IsEnabled(key);
            bool hasOverride = EditorPrefs.HasKey(OverridePrefix + key);
            
            // 显示当前值和覆盖状态
            Color prevColor = GUI.color;
            if (hasOverride) GUI.color = Color.yellow;
            
            EditorGUILayout.LabelField($"{displayName} ({key})", GUILayout.Width(280));
            GUI.color = prevColor;
            
            // 强制开/关按钮
            if (GUILayout.Button(currentValue ? "✅ ON" : "❌ OFF", GUILayout.Width(70)))
            {
                bool newValue = !currentValue;
                EditorPrefs.SetBool(OverridePrefix + key, newValue);
                // 这里需要通知引擎覆盖值（实际实现需要引擎支持本地覆盖接口）
                Debug.Log($"[FF Debug] 覆盖 {key} = {newValue}");
            }
            
            if (hasOverride && GUILayout.Button("清除", GUILayout.Width(50)))
            {
                EditorPrefs.DeleteKey(OverridePrefix + key);
            }
            
            EditorGUILayout.EndHorizontal();
        }
        
        EditorGUILayout.EndScrollView();
        
        EditorGUILayout.Space();
        if (GUILayout.Button("清除所有本地覆盖"))
        {
            foreach (var (key, _) in debugFlags)
                EditorPrefs.DeleteKey(OverridePrefix + key);
        }
    }
}
#endif
```

---

## 7. 最佳实践总结

### 7.1 命名规范

```
格式: {模块}.{功能}[.{子功能}]

示例:
  heroes.new_assassin_luna          // 新英雄灰度
  combat.skill_combo_v2             // 战斗连招V2
  social.realtime_friend_activity   // 社交实时动态
  pricing.hero_bundle_discount      // 英雄套包折扣
  ui.lobby.dynamic_bg_effects       // 大厅动态背景
  experiment.tutorial.onboarding_v2 // 新手引导实验
```

### 7.2 设计原则

1. **每个Flag只控制一件事**：避免一个Flag控制多个独立功能，难以归因
2. **默认值为安全状态**：`IsEnabled("new_feature", false)` 默认关闭新功能
3. **Flag有生命周期**：设置过期时间，清理废弃Flag避免技术债
4. **避免Flag嵌套**：不要 `if(ff.A && ff.B)` 这种组合，改用独立的复合Flag
5. **UI与逻辑分离**：Flag控制是否展示按钮，服务端也要验证权限
6. **百分比灰度用用户ID哈希**：保证同一用户每次评估结果一致（稳定性）
7. **本地覆盖只用于调试**：生产环境不应有本地覆盖，容易遗忘

### 7.3 常见陷阱

```csharp
// ❌ 错误：每帧调用IsEnabled（高频调用，未缓存）
void Update()
{
    if (FeatureFlagEngine.Instance.IsEnabled("heavy_feature")) 
        RunHeavyFeature();
}

// ✅ 正确：缓存评估结果，Flag变化时更新
private bool heavyFeatureEnabled;

void Start()
{
    heavyFeatureEnabled = FeatureFlagEngine.Instance.IsEnabled("heavy_feature");
    FeatureFlagEngine.Instance.OnFlagChanged += (key, _) => 
    {
        if (key == "heavy_feature")
            heavyFeatureEnabled = FeatureFlagEngine.Instance.IsEnabled("heavy_feature");
    };
}

void Update()
{
    if (heavyFeatureEnabled) RunHeavyFeature();
}
```

### 7.4 技术选型参考

| 方案 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| 自研（本文） | 中大型游戏，需深度定制 | 完全可控，无依赖 | 开发维护成本 |
| Firebase Remote Config | 独立游戏/小团队 | 免费，集成简单 | 国内访问慢，功能有限 |
| LaunchDarkly | 企业级 | 功能完整，实时推送 | 收费，需联网 |
| 自建配置中心+Redis | 大型网游，实时性要求高 | 毫秒级推送，高并发 | 需要服务端支持 |
