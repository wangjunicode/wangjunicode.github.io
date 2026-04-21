---
title: 游戏客户端AB测试与灰度发布系统完全指南：从实验分流到用户分群工程实践
published: 2026-04-21
description: 深度剖析游戏客户端AB测试框架的完整设计：实验分流算法、用户分群策略、指标采集上报、灰度发布控制台与流量回滚机制，涵盖Unity客户端集成、实验SDK封装与多变量测试最佳实践。
tags: [AB测试, 灰度发布, 实验框架, 用户分群, 游戏运营, Unity, 性能优化]
category: 工具链与工程化
draft: false
---

# 游戏客户端AB测试与灰度发布系统完全指南

## 一、为什么游戏需要AB测试系统

游戏行业的AB测试与互联网产品有本质区别：

- **留存敏感性极高**：新手引导、核心玩法的微小改动可能影响5%~30%的次日留存
- **长生命周期验证**：战斗数值、关卡难度需要7天/14天甚至更长周期的对比验证
- **多维指标冲突**：付费率↑但留存率↓的实验如何决策？
- **平台差异巨大**：同一实验在iOS/Android/PC上可能得出完全相反的结论

```
传统发版模式（高风险）：
策划改数值 → 开发实现 → 测试 → 全量发布 → 观察7天 → 发现问题 → 紧急回滚
                                                                  ↑ 代价极高

AB测试模式（低风险）：
策划改数值 → 开发实现 → 分流5%用户 → 实时观察 → 数据显著性检验 → 
  ├→ 效果正向 → 逐步扩量至10%→25%→50%→100%
  └→ 效果负向 → 立即关闭，100%用户不受影响
```

## 二、系统整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    AB测试平台（服务端）                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  实验管理台   │  │  分流引擎    │  │  指标分析    │   │
│  │  - 创建实验  │  │  - 哈希分桶  │  │  - 置信度    │   │
│  │  - 配置变量  │  │  - 流量控制  │  │  - 显著性    │   │
│  │  - 启停实验  │  │  - 互斥分组  │  │  - 效果归因  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/gRPC
┌────────────────────────▼────────────────────────────────┐
│                    游戏客户端SDK                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  配置拉取    │  │  分桶决策    │  │  事件上报    │   │
│  │  - 启动预取  │  │  - 本地计算  │  │  - 曝光事件  │   │
│  │  - 增量更新  │  │  - 缓存结果  │  │  - 转化事件  │   │
│  │  - 容灾降级  │  │  - 实时刷新  │  │  - 批量发送  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## 三、核心数据结构设计

### 3.1 实验配置数据模型

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

namespace GameABTest
{
    /// <summary>
    /// 实验状态
    /// </summary>
    public enum ExperimentStatus
    {
        Draft = 0,      // 草稿
        Running = 1,    // 运行中
        Paused = 2,     // 暂停
        Finished = 3,   // 已结束
        Archived = 4    // 已归档
    }

    /// <summary>
    /// 分流策略
    /// </summary>
    public enum BucketingStrategy
    {
        UserId = 0,      // 按用户ID分桶（同一用户跨Session保持一致）
        DeviceId = 1,    // 按设备ID分桶（同一设备行为一致）
        SessionId = 2,   // 按Session分桶（每次启动随机）
        Random = 3       // 完全随机（用于无状态实验）
    }

    /// <summary>
    /// 单个实验变量
    /// </summary>
    [Serializable]
    public class ExperimentVariable
    {
        public string Key;          // 变量键名，如 "newbie_guide_skip"
        public string Type;         // 类型："bool" | "int" | "float" | "string" | "json"
        public string DefaultValue; // 默认值（控制组）
        public string Description;  // 描述
    }

    /// <summary>
    /// 实验分组（桶）
    /// </summary>
    [Serializable]
    public class ExperimentBucket
    {
        public string BucketId;     // 分组ID，如 "control", "treatment_a", "treatment_b"
        public string Name;         // 显示名称
        public float TrafficRatio;  // 流量占比，0.0~1.0，所有分组之和 <= 1.0
        public bool IsControl;      // 是否为控制组

        // 该分组的变量覆盖值
        public Dictionary<string, string> VariableOverrides = new Dictionary<string, string>();
    }

    /// <summary>
    /// 实验互斥组（同一用户不能同时参与互斥组内的多个实验）
    /// </summary>
    [Serializable]
    public class ExperimentMutexGroup
    {
        public string GroupId;
        public List<string> ExperimentIds;
    }

    /// <summary>
    /// 完整的实验定义
    /// </summary>
    [Serializable]
    public class ExperimentDefinition
    {
        public string ExperimentId;             // 唯一ID，如 "exp_20240421_newbie"
        public string Name;                      // 实验名称
        public ExperimentStatus Status;
        public BucketingStrategy Bucketing;
        public string MutexGroupId;             // 互斥组ID（可为空）

        // 白名单：强制指定用户进入特定分组（QA测试用）
        public Dictionary<string, string> Whitelist = new Dictionary<string, string>();

        // 目标受众过滤条件（如只对新用户生效）
        public List<ExperimentFilter> Filters = new List<ExperimentFilter>();

        public List<ExperimentVariable> Variables = new List<ExperimentVariable>();
        public List<ExperimentBucket> Buckets = new List<ExperimentBucket>();

        public long StartTime;  // Unix时间戳（毫秒）
        public long EndTime;    // 0表示无限期
        public int Version;     // 配置版本号，用于增量更新
    }

    /// <summary>
    /// 受众过滤条件
    /// </summary>
    [Serializable]
    public class ExperimentFilter
    {
        public string Attribute;   // 属性名，如 "register_days", "platform", "vip_level"
        public string Operator;    // 操作符："eq" | "neq" | "gt" | "lt" | "gte" | "lte" | "in" | "not_in"
        public string Value;       // 期望值
    }
}
```

### 3.2 用户分桶决策引擎

```csharp
using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace GameABTest
{
    /// <summary>
    /// 分桶决策引擎 - 核心逻辑
    /// 使用 MurmurHash3 实现低碰撞率的一致性哈希分桶
    /// </summary>
    public static class BucketingEngine
    {
        // 哈希空间大小（10000桶，精度0.01%）
        private const int BUCKET_SPACE = 10000;

        /// <summary>
        /// 为指定用户计算分桶结果
        /// </summary>
        /// <param name="experiment">实验定义</param>
        /// <param name="bucketingKey">分桶键值（用户ID/设备ID等）</param>
        /// <param name="userAttributes">用户属性（用于过滤条件判断）</param>
        /// <returns>分配到的桶ID，null表示用户不参与该实验</returns>
        public static string AssignBucket(
            ExperimentDefinition experiment,
            string bucketingKey,
            Dictionary<string, string> userAttributes)
        {
            // 1. 检查实验状态
            if (experiment.Status != ExperimentStatus.Running)
                return null;

            // 2. 检查实验时间窗口
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (now < experiment.StartTime) return null;
            if (experiment.EndTime > 0 && now > experiment.EndTime) return null;

            // 3. 白名单检查（QA强制入组）
            if (experiment.Whitelist.TryGetValue(bucketingKey, out string whitelistBucket))
            {
                return whitelistBucket;
            }

            // 4. 受众过滤（不满足条件的用户不参与实验）
            if (!PassesFilters(experiment.Filters, userAttributes))
                return null;

            // 5. 一致性哈希分桶
            // 将实验ID与用户Key拼接后哈希，保证：
            // - 同一用户在同一实验中始终落入同一分组
            // - 不同实验的分桶相互独立（避免流量相关性）
            string hashInput = $"{experiment.ExperimentId}:{bucketingKey}";
            int bucketIndex = MurmurHash3(hashInput) % BUCKET_SPACE;

            // 6. 按流量比例分配分组
            float cumulative = 0f;
            float normalizedIndex = bucketIndex / (float)BUCKET_SPACE;

            foreach (var bucket in experiment.Buckets)
            {
                cumulative += bucket.TrafficRatio;
                if (normalizedIndex < cumulative)
                {
                    return bucket.BucketId;
                }
            }

            // 超出所有分组流量总和 → 不参与实验（holdout流量）
            return null;
        }

        /// <summary>
        /// 判断用户是否满足实验过滤条件
        /// </summary>
        private static bool PassesFilters(
            List<ExperimentFilter> filters,
            Dictionary<string, string> attributes)
        {
            if (filters == null || filters.Count == 0) return true;

            foreach (var filter in filters)
            {
                if (!attributes.TryGetValue(filter.Attribute, out string attrValue))
                    return false; // 属性不存在 → 不满足

                if (!EvaluateFilter(filter, attrValue))
                    return false;
            }
            return true;
        }

        private static bool EvaluateFilter(ExperimentFilter filter, string attrValue)
        {
            switch (filter.Operator)
            {
                case "eq":  return attrValue == filter.Value;
                case "neq": return attrValue != filter.Value;
                case "gt":
                    return float.TryParse(attrValue, out float fA) &&
                           float.TryParse(filter.Value, out float fB) && fA > fB;
                case "gte":
                    return float.TryParse(attrValue, out float gA) &&
                           float.TryParse(filter.Value, out float gB) && gA >= gB;
                case "lt":
                    return float.TryParse(attrValue, out float lA) &&
                           float.TryParse(filter.Value, out float lB) && lA < lB;
                case "lte":
                    return float.TryParse(attrValue, out float leA) &&
                           float.TryParse(filter.Value, out float leB) && leA <= leB;
                case "in":
                    var inValues = filter.Value.Split(',');
                    foreach (var v in inValues)
                        if (v.Trim() == attrValue) return true;
                    return false;
                case "not_in":
                    var notInValues = filter.Value.Split(',');
                    foreach (var v in notInValues)
                        if (v.Trim() == attrValue) return false;
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>
        /// MurmurHash3 32位实现
        /// 特点：高速、低碰撞、均匀分布
        /// </summary>
        private static int MurmurHash3(string input)
        {
            byte[] data = Encoding.UTF8.GetBytes(input);
            int length = data.Length;
            uint seed = 0x9747b28c;
            uint h1 = seed;
            uint c1 = 0xcc9e2d51;
            uint c2 = 0x1b873593;
            int i = 0;

            while (i + 4 <= length)
            {
                uint k1 = (uint)(data[i] | data[i + 1] << 8 | data[i + 2] << 16 | data[i + 3] << 24);
                k1 *= c1;
                k1 = RotateLeft(k1, 15);
                k1 *= c2;
                h1 ^= k1;
                h1 = RotateLeft(h1, 13);
                h1 = h1 * 5 + 0xe6546b64;
                i += 4;
            }

            // 处理剩余字节
            uint tail = 0;
            switch (length & 3)
            {
                case 3: tail ^= (uint)data[i + 2] << 16; goto case 2;
                case 2: tail ^= (uint)data[i + 1] << 8;  goto case 1;
                case 1:
                    tail ^= data[i];
                    tail *= c1;
                    tail = RotateLeft(tail, 15);
                    tail *= c2;
                    h1 ^= tail;
                    break;
            }

            h1 ^= (uint)length;
            h1 = FMix(h1);

            return (int)(h1 & 0x7FFFFFFF); // 确保非负
        }

        private static uint RotateLeft(uint value, int shift) =>
            (value << shift) | (value >> (32 - shift));

        private static uint FMix(uint h)
        {
            h ^= h >> 16;
            h *= 0x85ebca6b;
            h ^= h >> 13;
            h *= 0xc2b2ae35;
            h ^= h >> 16;
            return h;
        }
    }
}
```

## 四、客户端SDK核心实现

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;

namespace GameABTest
{
    /// <summary>
    /// AB测试SDK核心管理器
    /// 职责：配置拉取、分桶缓存、变量读取、事件上报
    /// </summary>
    public class ABTestManager : MonoBehaviour
    {
        public static ABTestManager Instance { get; private set; }

        [Header("SDK配置")]
        [SerializeField] private string _apiEndpoint = "https://abtest.game.com/api/v2";
        [SerializeField] private int _fetchTimeoutSeconds = 5;
        [SerializeField] private int _cacheExpireSeconds = 3600; // 1小时本地缓存
        [SerializeField] private bool _enableReportEvents = true;

        // 实验配置缓存
        private Dictionary<string, ExperimentDefinition> _experiments =
            new Dictionary<string, ExperimentDefinition>();

        // 用户分桶结果缓存（key: experimentId, value: bucketId）
        private Dictionary<string, string> _assignmentCache =
            new Dictionary<string, string>();

        // 当前用户属性
        private Dictionary<string, string> _userAttributes =
            new Dictionary<string, string>();

        // 事件上报缓冲区
        private List<ABTestEvent> _eventBuffer = new List<ABTestEvent>();
        private const int EVENT_FLUSH_BATCH_SIZE = 50;
        private const float EVENT_FLUSH_INTERVAL = 10f;

        private string _userId;
        private string _deviceId;
        private bool _isInitialized = false;

        // 配置版本（用于增量更新）
        private int _configVersion = 0;

        void Awake()
        {
            if (Instance == null)
            {
                Instance = this;
                DontDestroyOnLoad(gameObject);
            }
            else
            {
                Destroy(gameObject);
            }
        }

        /// <summary>
        /// 初始化SDK（游戏启动时调用）
        /// </summary>
        public IEnumerator InitializeAsync(string userId, Dictionary<string, string> attributes = null)
        {
            _userId = userId;
            _deviceId = SystemInfo.deviceUniqueIdentifier;

            // 设置基础用户属性
            _userAttributes["user_id"] = userId;
            _userAttributes["device_id"] = _deviceId;
            _userAttributes["platform"] = Application.platform.ToString().ToLower();
            _userAttributes["app_version"] = Application.version;
            _userAttributes["os_version"] = SystemInfo.operatingSystem;

            // 合并业务属性（如注册天数、等级、VIP等级等）
            if (attributes != null)
            {
                foreach (var kv in attributes)
                    _userAttributes[kv.Key] = kv.Value;
            }

            // 先从本地缓存恢复（保证离线可用）
            LoadFromCache();

            // 再从服务器拉取最新配置（异步，失败不阻断）
            yield return FetchConfigFromServer();

            // 启动定期事件上报
            if (_enableReportEvents)
                StartCoroutine(FlushEventsPeriodically());

            _isInitialized = true;
            Debug.Log($"[ABTest] SDK初始化完成，加载了 {_experiments.Count} 个实验");
        }

        /// <summary>
        /// 获取实验分组变量值
        /// </summary>
        /// <typeparam name="T">值类型：bool, int, float, string</typeparam>
        /// <param name="experimentId">实验ID</param>
        /// <param name="variableKey">变量键名</param>
        /// <param name="defaultValue">降级默认值</param>
        public T GetVariable<T>(string experimentId, string variableKey, T defaultValue)
        {
            if (!_isInitialized)
            {
                Debug.LogWarning($"[ABTest] SDK未初始化，返回默认值");
                return defaultValue;
            }

            if (!_experiments.TryGetValue(experimentId, out var experiment))
                return defaultValue;

            // 获取用户分组
            string bucketId = GetOrAssignBucket(experiment);
            if (bucketId == null) return defaultValue;

            // 找到对应分组的变量值
            var bucket = experiment.Buckets.Find(b => b.BucketId == bucketId);
            if (bucket == null) return defaultValue;

            string rawValue;
            if (!bucket.VariableOverrides.TryGetValue(variableKey, out rawValue))
            {
                // 分组没有覆盖该变量 → 使用默认值（控制组值）
                var variable = experiment.Variables.Find(v => v.Key == variableKey);
                if (variable == null) return defaultValue;
                rawValue = variable.DefaultValue;
            }

            // 上报曝光事件（懒曝光：只在真正读取变量时上报）
            ReportExposure(experimentId, bucketId, variableKey);

            try
            {
                return (T)Convert.ChangeType(rawValue, typeof(T));
            }
            catch
            {
                return defaultValue;
            }
        }

        /// <summary>
        /// 获取用户在指定实验的分组（带缓存）
        /// </summary>
        private string GetOrAssignBucket(ExperimentDefinition experiment)
        {
            if (_assignmentCache.TryGetValue(experiment.ExperimentId, out string cached))
                return cached;

            // 根据分桶策略选择键值
            string bucketingKey = experiment.Bucketing switch
            {
                BucketingStrategy.UserId => _userId,
                BucketingStrategy.DeviceId => _deviceId,
                BucketingStrategy.SessionId => Guid.NewGuid().ToString(),
                BucketingStrategy.Random => Guid.NewGuid().ToString(),
                _ => _userId
            };

            string bucketId = BucketingEngine.AssignBucket(experiment, bucketingKey, _userAttributes);
            _assignmentCache[experiment.ExperimentId] = bucketId;

            if (bucketId != null)
                Debug.Log($"[ABTest] 用户({_userId}) 实验({experiment.ExperimentId}) → 分组({bucketId})");

            return bucketId;
        }

        #region 事件上报

        /// <summary>
        /// 上报业务转化事件（如关卡通关、首充等）
        /// </summary>
        public void TrackConversion(string eventName, Dictionary<string, string> properties = null)
        {
            // 自动关联用户当前参与的所有实验分组
            foreach (var kv in _assignmentCache)
            {
                if (kv.Value == null) continue;

                var evt = new ABTestEvent
                {
                    EventType = "conversion",
                    EventName = eventName,
                    ExperimentId = kv.Key,
                    BucketId = kv.Value,
                    UserId = _userId,
                    Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    Properties = properties ?? new Dictionary<string, string>()
                };
                _eventBuffer.Add(evt);
            }

            if (_eventBuffer.Count >= EVENT_FLUSH_BATCH_SIZE)
                StartCoroutine(FlushEvents());
        }

        private void ReportExposure(string experimentId, string bucketId, string variableKey)
        {
            // 防重复上报：同一实验同一Session只上报一次曝光
            string dedupeKey = $"exp_{experimentId}_exposed";
            if (PlayerPrefs.HasKey(dedupeKey)) return;
            PlayerPrefs.SetString(dedupeKey, "1");

            _eventBuffer.Add(new ABTestEvent
            {
                EventType = "exposure",
                EventName = "ab_exposure",
                ExperimentId = experimentId,
                BucketId = bucketId,
                UserId = _userId,
                Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                Properties = new Dictionary<string, string> { ["variable_key"] = variableKey }
            });
        }

        private IEnumerator FlushEventsPeriodically()
        {
            while (true)
            {
                yield return new WaitForSeconds(EVENT_FLUSH_INTERVAL);
                if (_eventBuffer.Count > 0)
                    yield return FlushEvents();
            }
        }

        private IEnumerator FlushEvents()
        {
            if (_eventBuffer.Count == 0) yield break;

            var batch = new List<ABTestEvent>(_eventBuffer);
            _eventBuffer.Clear();

            string json = JsonUtility.ToJson(new ABTestEventBatch { Events = batch });
            byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(json);

            using var request = new UnityWebRequest($"{_apiEndpoint}/events", "POST");
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 10;

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[ABTest] 事件上报失败: {request.error}，数据将在下次重试");
                _eventBuffer.InsertRange(0, batch); // 放回缓冲区重试
            }
        }

        #endregion

        #region 配置拉取与缓存

        private IEnumerator FetchConfigFromServer()
        {
            string url = $"{_apiEndpoint}/config?user_id={_userId}&version={_configVersion}";
            using var request = UnityWebRequest.Get(url);
            request.timeout = _fetchTimeoutSeconds;
            request.SetRequestHeader("X-Device-Id", _deviceId);

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                var response = JsonUtility.FromJson<ABTestConfigResponse>(request.downloadHandler.text);
                if (response != null && response.Experiments != null)
                {
                    foreach (var exp in response.Experiments)
                    {
                        _experiments[exp.ExperimentId] = exp;
                        // 配置更新后清除该实验的分桶缓存（重新分桶）
                        _assignmentCache.Remove(exp.ExperimentId);
                    }
                    _configVersion = response.Version;
                    SaveToCache();
                    Debug.Log($"[ABTest] 配置更新成功，版本: {_configVersion}");
                }
            }
            else
            {
                Debug.LogWarning($"[ABTest] 配置拉取失败: {request.error}，使用本地缓存");
            }
        }

        private const string CACHE_KEY = "ABTest_Config_Cache";
        private const string CACHE_TIME_KEY = "ABTest_Config_CacheTime";

        private void SaveToCache()
        {
            var cacheData = new ABTestCacheData
            {
                Version = _configVersion,
                Experiments = new List<ExperimentDefinition>(_experiments.Values)
            };
            PlayerPrefs.SetString(CACHE_KEY, JsonUtility.ToJson(cacheData));
            PlayerPrefs.SetString(CACHE_TIME_KEY, DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString());
            PlayerPrefs.Save();
        }

        private void LoadFromCache()
        {
            if (!PlayerPrefs.HasKey(CACHE_KEY)) return;

            // 检查缓存是否过期
            if (long.TryParse(PlayerPrefs.GetString(CACHE_TIME_KEY, "0"), out long cacheTime))
            {
                long age = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - cacheTime;
                if (age > _cacheExpireSeconds)
                {
                    Debug.Log("[ABTest] 本地缓存已过期");
                    return;
                }
            }

            try
            {
                var cacheData = JsonUtility.FromJson<ABTestCacheData>(PlayerPrefs.GetString(CACHE_KEY));
                if (cacheData?.Experiments != null)
                {
                    foreach (var exp in cacheData.Experiments)
                        _experiments[exp.ExperimentId] = exp;
                    _configVersion = cacheData.Version;
                    Debug.Log($"[ABTest] 从本地缓存加载 {_experiments.Count} 个实验");
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ABTest] 本地缓存解析失败: {ex.Message}");
            }
        }

        #endregion

        void OnApplicationPause(bool paused)
        {
            if (paused && _eventBuffer.Count > 0)
                StartCoroutine(FlushEvents()); // App切后台时立即上报
        }
    }

    // 辅助数据结构
    [Serializable]
    public class ABTestEvent
    {
        public string EventType;
        public string EventName;
        public string ExperimentId;
        public string BucketId;
        public string UserId;
        public long Timestamp;
        public Dictionary<string, string> Properties;
    }

    [Serializable]
    public class ABTestEventBatch { public List<ABTestEvent> Events; }

    [Serializable]
    public class ABTestConfigResponse
    {
        public int Version;
        public List<ExperimentDefinition> Experiments;
    }

    [Serializable]
    public class ABTestCacheData
    {
        public int Version;
        public List<ExperimentDefinition> Experiments;
    }
}
```

## 五、业务层集成示例

```csharp
using UnityEngine;
using GameABTest;

/// <summary>
/// 新手引导AB测试 - 实际业务集成示例
/// 实验目标：比较"跳过引导"vs"强制引导"对7日留存的影响
/// </summary>
public class NewbieGuideABTest : MonoBehaviour
{
    private const string EXP_ID = "exp_20240421_newbie_guide";
    private const string VAR_SKIP_ENABLED = "skip_guide_enabled";
    private const string VAR_GUIDE_STYLE = "guide_style";
    private const string VAR_REWARD_MULTIPLIER = "first_clear_reward_multiplier";

    void Start()
    {
        // 读取实验变量（SDK内部处理分组逻辑）
        bool skipEnabled = ABTestManager.Instance.GetVariable<bool>(
            EXP_ID, VAR_SKIP_ENABLED, false);

        string guideStyle = ABTestManager.Instance.GetVariable<string>(
            EXP_ID, VAR_GUIDE_STYLE, "classic");

        float rewardMultiplier = ABTestManager.Instance.GetVariable<float>(
            EXP_ID, VAR_REWARD_MULTIPLIER, 1.0f);

        Debug.Log($"[NewbieGuide] 跳过={skipEnabled}, 风格={guideStyle}, 奖励倍数={rewardMultiplier}");

        // 根据实验配置初始化UI
        InitializeGuideUI(skipEnabled, guideStyle, rewardMultiplier);
    }

    private void InitializeGuideUI(bool canSkip, string style, float rewardMult)
    {
        // ... UI初始化逻辑
    }

    // 玩家完成引导时上报转化事件
    public void OnGuideCompleted(float completionTimeSeconds)
    {
        ABTestManager.Instance.TrackConversion("guide_completed", new System.Collections.Generic.Dictionary<string, string>
        {
            ["completion_time"] = completionTimeSeconds.ToString("F1"),
            ["skipped"] = "false"
        });
    }

    // 玩家跳过引导时上报
    public void OnGuideSkipped(int stageReached)
    {
        ABTestManager.Instance.TrackConversion("guide_skipped", new System.Collections.Generic.Dictionary<string, string>
        {
            ["stage_reached"] = stageReached.ToString()
        });
    }
}
```

## 六、多变量实验（MVT）设计

```csharp
/// <summary>
/// 多变量测试（MVT）辅助工具
/// 场景：同时测试多个UI元素的不同组合
/// </summary>
public static class MVTHelper
{
    /// <summary>
    /// 获取某个实验维度下的完整变量集合
    /// 适用于一次性读取多个相关变量的场景
    /// </summary>
    public static ExperimentVariableSet GetVariableSet(string experimentId)
    {
        var manager = ABTestManager.Instance;
        return new ExperimentVariableSet
        {
            SkipGuideEnabled = manager.GetVariable<bool>(experimentId, "skip_guide_enabled", false),
            GuideStyle = manager.GetVariable<string>(experimentId, "guide_style", "classic"),
            RewardMultiplier = manager.GetVariable<float>(experimentId, "first_clear_reward_multiplier", 1.0f),
            ShowHintAfterSeconds = manager.GetVariable<int>(experimentId, "show_hint_delay_seconds", 10),
            EnableVoiceOver = manager.GetVariable<bool>(experimentId, "enable_voice_over", true)
        };
    }
}

public class ExperimentVariableSet
{
    public bool SkipGuideEnabled;
    public string GuideStyle;
    public float RewardMultiplier;
    public int ShowHintAfterSeconds;
    public bool EnableVoiceOver;
}
```

## 七、灰度发布流量控制策略

```csharp
/// <summary>
/// 灰度发布阶段控制器
/// 支持按比例逐步扩量，并在检测到异常时自动回滚
/// </summary>
public class GradualRolloutController
{
    // 标准灰度扩量阶段
    public static readonly float[] RolloutStages = { 0.01f, 0.05f, 0.10f, 0.25f, 0.50f, 1.0f };

    // 每个阶段最少观察时间（小时）
    public static readonly int[] MinObservationHours = { 1, 2, 4, 8, 24, 0 };

    /// <summary>
    /// 自动扩量决策：基于关键指标判断是否可以扩量
    /// </summary>
    public static GradualRolloutDecision EvaluateRollout(
        float currentTraffic,
        ExperimentMetrics treatmentMetrics,
        ExperimentMetrics controlMetrics,
        RolloutConfig config)
    {
        // 1. 崩溃率检查（一票否决）
        if (treatmentMetrics.CrashRate > controlMetrics.CrashRate * config.MaxCrashRateRatio)
        {
            return new GradualRolloutDecision
            {
                Action = RolloutAction.Rollback,
                Reason = $"崩溃率超标: 实验组{treatmentMetrics.CrashRate:P2} vs 对照组{controlMetrics.CrashRate:P2}"
            };
        }

        // 2. 核心指标显著性检验
        double pValue = StatisticsHelper.TwoProportionZTest(
            treatmentMetrics.RetentionD1,
            treatmentMetrics.SampleSize,
            controlMetrics.RetentionD1,
            controlMetrics.SampleSize);

        bool isSignificant = pValue < config.SignificanceLevel && treatmentMetrics.SampleSize >= config.MinSampleSize;

        if (isSignificant)
        {
            float improvement = (treatmentMetrics.RetentionD1 - controlMetrics.RetentionD1)
                               / controlMetrics.RetentionD1;

            if (improvement >= config.MinPositiveEffect)
            {
                // 正向显著 → 继续扩量
                float nextStage = GetNextStage(currentTraffic);
                return new GradualRolloutDecision
                {
                    Action = nextStage >= 1.0f ? RolloutAction.FullRollout : RolloutAction.ExpandTraffic,
                    TargetTraffic = nextStage,
                    Reason = $"次留提升 {improvement:P2}，p值={pValue:F4}，扩量至 {nextStage:P0}"
                };
            }
            else if (improvement < config.MaxNegativeEffect)
            {
                // 负向显著 → 回滚
                return new GradualRolloutDecision
                {
                    Action = RolloutAction.Rollback,
                    Reason = $"次留下降 {-improvement:P2}（超过阈值 {-config.MaxNegativeEffect:P2}）"
                };
            }
        }

        return new GradualRolloutDecision
        {
            Action = RolloutAction.Wait,
            Reason = $"样本量不足或未达显著性（n={treatmentMetrics.SampleSize}, p={pValue:F4}）"
        };
    }

    private static float GetNextStage(float current)
    {
        foreach (var stage in RolloutStages)
            if (stage > current) return stage;
        return 1.0f;
    }
}

public class ExperimentMetrics
{
    public float RetentionD1;    // 次日留存率
    public float RetentionD7;    // 7日留存率
    public float CrashRate;      // 崩溃率
    public float AvgSessionTime; // 平均会话时长（秒）
    public int SampleSize;       // 样本量
}

public class RolloutConfig
{
    public double SignificanceLevel = 0.05;   // 显著性水平 α=5%
    public int MinSampleSize = 1000;          // 最小样本量
    public float MinPositiveEffect = 0.01f;   // 最小正向效果阈值（1%）
    public float MaxNegativeEffect = -0.02f;  // 最大允许负向效果（-2%）
    public float MaxCrashRateRatio = 1.5f;    // 最大允许崩溃率倍数
}

public enum RolloutAction { Wait, ExpandTraffic, FullRollout, Rollback }

public class GradualRolloutDecision
{
    public RolloutAction Action;
    public float TargetTraffic;
    public string Reason;
}

/// <summary>
/// 简单双比例Z检验（用于计算p值）
/// </summary>
public static class StatisticsHelper
{
    public static double TwoProportionZTest(float p1, int n1, float p2, int n2)
    {
        double pooledP = (p1 * n1 + p2 * n2) / (n1 + n2);
        double se = Math.Sqrt(pooledP * (1 - pooledP) * (1.0 / n1 + 1.0 / n2));
        if (se < 1e-10) return 1.0;
        double z = Math.Abs((p1 - p2) / se);
        // 近似p值（正态分布双尾）
        return 2.0 * (1.0 - NormalCDF(z));
    }

    private static double NormalCDF(double z)
    {
        // Abramowitz & Stegun 近似（精度 1.5e-7）
        double t = 1.0 / (1.0 + 0.2316419 * z);
        double poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
        return 1.0 - (1.0 / Math.Sqrt(2 * Math.PI)) * Math.Exp(-z * z / 2) * poly;
    }
}
```

## 八、最佳实践总结

### 8.1 实验设计原则

| 原则 | 说明 | 反例 |
|------|------|------|
| **单因子原则** | 每个实验只改变一个变量 | 同时改UI布局+按钮颜色+文案 |
| **充足样本量** | 提前用功效分析计算所需n | 看了100个样本就下结论 |
| **互斥实验** | 互斥组内用户不能同时进多个实验 | 用户同时参与两个影响留存的实验 |
| **最小暴露原则** | 只在真正使用变量时上报曝光 | 在用户进入实验分组时立即上报 |
| **避免碰撞** | 实验哈希加入实验ID前缀 | 多个实验共用相同哈希导致分桶相关 |

### 8.2 常见陷阱

```
❌ 陷阱1：新奇效应（Novelty Effect）
   用户对新东西天然好奇，短期数据虚高
   → 解决方案：实验周期≥7天，老用户与新用户分开分析

❌ 陷阱2：辛普森悖论
   整体数据好，但细分用户群反向
   → 解决方案：始终做分层分析（设备、注册天数、付费状态）

❌ 陷阱3：多次窥视问题（Peeking Problem）
   反复查看数据直到p<0.05就停止
   → 解决方案：提前设定样本量和停止规则，使用序贯检验

❌ 陷阱4：网络效应污染
   社交游戏中，对照组用户被实验组用户影响
   → 解决方案：按服务器分桶而非按用户分桶
```

### 8.3 指标优先级框架

```
北极星指标（唯一）：
  └── 长期留存（30日）

一级指标（实验主要KPI）：
  ├── 次日留存 / 7日留存
  └── 付费转化率

二级指标（安全护栏，任何一个恶化则停止实验）：
  ├── 崩溃率（不得增加超过10%）
  ├── 客诉率（不得增加超过20%）
  └── 会话时长（不得减少超过5%）

三级指标（诊断用，不作为决策依据）：
  ├── 关卡通过率
  ├── 功能使用率
  └── ANR率
```

> **关键提醒**：AB测试是工具，不是目的。对于体验严重降级的变更，应在设计阶段就否决，而不是依赖实验数据。数据驱动的前提是每个实验变量都经过了合理的产品思考。
