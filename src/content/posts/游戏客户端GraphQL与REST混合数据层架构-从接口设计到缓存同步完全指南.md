---
title: 游戏客户端GraphQL与REST混合数据层架构-从接口设计到缓存同步完全指南
published: 2026-05-05
description: 深度解析游戏客户端如何结合GraphQL灵活查询与REST高效批处理的优势，构建混合数据层架构。涵盖客户端缓存策略、离线优先设计、数据订阅推送与冲突解决机制，以Unity C#为主要实现语言，提供完整的工程化方案。
tags: [网络架构, GraphQL, REST, 客户端缓存, 数据同步, Unity]
category: 网络与通信
draft: false
---

# 游戏客户端GraphQL与REST混合数据层架构：从接口设计到缓存同步完全指南

## 前言：游戏客户端网络层的演进困境

游戏客户端的网络数据层，长期面临以下矛盾：

**REST API的痛点：**
- 过度获取（Over-fetching）：一个"角色信息"接口返回200个字段，但UI只需要5个
- 获取不足（Under-fetching）：展示"背包"页面需要串行发起3个请求：背包列表→装备详情→属性加成
- 接口爆炸：每个UI页面的需求变化都可能导致新接口或接口改版

**纯GraphQL的痛点：**
- 实时战斗同步不适合查询语言（帧同步/状态同步是push模型）
- 文件下载、CDN资源获取必须走REST/HTTP
- 历史REST接口迁移成本极高

**混合架构的价值：**
用GraphQL处理复杂的数据查询与聚合（角色信息、背包、商城等），用REST处理批量下载与流式传输，用WebSocket处理实时推送。三者各司其职，形成互补。

本文将以Unity C#为主要实现环境，构建一套完整的游戏客户端混合数据层架构。

---

## 一、架构总览：分层设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         UI / ViewModel 层                        │
│         (只与 DataRepository 交互，不关心底层网络协议)             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                      DataRepository 层                           │
│          统一数据访问接口，屏蔽GraphQL/REST/WebSocket差异          │
└──────┬─────────────────┬────────────────────┬────────────────────┘
       │                 │                    │
┌──────▼──────┐  ┌───────▼──────┐  ┌─────────▼────────┐
│  GraphQL    │  │  REST Client  │  │  WebSocket/SSE   │
│  Client     │  │  (资源/文件)  │  │  (实时推送)      │
│ (数据查询)  │  └───────┬──────┘  └─────────┬────────┘
└──────┬──────┘          │                   │
       │         ┌───────▼──────┐  ┌─────────▼────────┐
┌──────▼──────┐  │  CDN/Asset   │  │  战斗同步通道     │
│  本地缓存   │  │  Downloader  │  │  (UDP/KCP)       │
│  (SQLite/   │  └──────────────┘  └──────────────────┘
│  Memory)   │
└─────────────┘
```

---

## 二、GraphQL客户端实现

### 2.1 轻量级C# GraphQL客户端

Unity项目中没有成熟的GraphQL客户端库，需要自行实现一个轻量版本：

```csharp
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

/// <summary>
/// GraphQL请求封装
/// </summary>
public class GraphQLRequest
{
    [JsonProperty("query")]
    public string Query { get; set; }
    
    [JsonProperty("variables", NullValueHandling = NullValueHandling.Ignore)]
    public Dictionary<string, object> Variables { get; set; }
    
    [JsonProperty("operationName", NullValueHandling = NullValueHandling.Ignore)]
    public string OperationName { get; set; }
}

/// <summary>
/// GraphQL响应封装
/// </summary>
public class GraphQLResponse<T>
{
    [JsonProperty("data")]
    public T Data { get; set; }
    
    [JsonProperty("errors")]
    public List<GraphQLError> Errors { get; set; }
    
    public bool HasErrors => Errors != null && Errors.Count > 0;
}

public class GraphQLError
{
    [JsonProperty("message")]
    public string Message { get; set; }
    
    [JsonProperty("locations")]
    public List<ErrorLocation> Locations { get; set; }
    
    [JsonProperty("path")]
    public List<object> Path { get; set; }
    
    [JsonProperty("extensions")]
    public Dictionary<string, object> Extensions { get; set; }
}

public class ErrorLocation
{
    [JsonProperty("line")] public int Line { get; set; }
    [JsonProperty("column")] public int Column { get; set; }
}

/// <summary>
/// GraphQL HTTP客户端
/// </summary>
public class GraphQLHttpClient
{
    private readonly string _endpoint;
    private readonly Dictionary<string, string> _defaultHeaders;
    private readonly int _timeoutSeconds;
    
    // 请求统计（用于监控）
    private int _totalRequests;
    private int _failedRequests;
    private double _totalLatencyMs;
    
    public GraphQLHttpClient(string endpoint, int timeoutSeconds = 10)
    {
        _endpoint = endpoint;
        _timeoutSeconds = timeoutSeconds;
        _defaultHeaders = new Dictionary<string, string>
        {
            ["Content-Type"] = "application/json",
            ["Accept"] = "application/json"
        };
    }
    
    public void SetAuthToken(string token)
    {
        _defaultHeaders["Authorization"] = $"Bearer {token}";
    }
    
    /// <summary>
    /// 执行GraphQL查询
    /// </summary>
    public async Task<GraphQLResponse<T>> QueryAsync<T>(
        GraphQLRequest request,
        CancellationToken cancellationToken = default)
    {
        string json = JsonConvert.SerializeObject(request);
        byte[] bodyBytes = Encoding.UTF8.GetBytes(json);
        
        var startTime = DateTimeOffset.UtcNow;
        _totalRequests++;
        
        try
        {
            using var webRequest = new UnityWebRequest(_endpoint, "POST");
            webRequest.uploadHandler = new UploadHandlerRaw(bodyBytes);
            webRequest.downloadHandler = new DownloadHandlerBuffer();
            webRequest.timeout = _timeoutSeconds;
            
            foreach (var header in _defaultHeaders)
            {
                webRequest.SetRequestHeader(header.Key, header.Value);
            }
            
            // 等待请求完成（兼容async/await）
            var operation = webRequest.SendWebRequest();
            while (!operation.isDone)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    webRequest.Abort();
                    throw new OperationCanceledException(cancellationToken);
                }
                await Task.Yield();
            }
            
            _totalLatencyMs += (DateTimeOffset.UtcNow - startTime).TotalMilliseconds;
            
            if (webRequest.result != UnityWebRequest.Result.Success)
            {
                _failedRequests++;
                throw new GraphQLNetworkException(
                    $"网络错误: {webRequest.error}, URL: {_endpoint}");
            }
            
            string responseText = webRequest.downloadHandler.text;
            var response = JsonConvert.DeserializeObject<GraphQLResponse<T>>(responseText);
            
            if (response.HasErrors)
            {
                // 将GraphQL错误记录到监控系统
                foreach (var error in response.Errors)
                {
                    Debug.LogWarning($"[GraphQL] {error.Message} at {string.Join(".", error.Path ?? new List<object>())}");
                }
            }
            
            return response;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception e)
        {
            _failedRequests++;
            throw new GraphQLException($"GraphQL请求失败: {e.Message}", e);
        }
    }
    
    /// <summary>
    /// 批量请求合并（Batching）：将多个查询合并为单次HTTP请求
    /// </summary>
    public async Task<List<GraphQLResponse<JObject>>> BatchQueryAsync(
        List<GraphQLRequest> requests,
        CancellationToken cancellationToken = default)
    {
        string json = JsonConvert.SerializeObject(requests);
        byte[] bodyBytes = Encoding.UTF8.GetBytes(json);
        
        using var webRequest = new UnityWebRequest(_endpoint, "POST");
        webRequest.uploadHandler = new UploadHandlerRaw(bodyBytes);
        webRequest.downloadHandler = new DownloadHandlerBuffer();
        webRequest.timeout = _timeoutSeconds * 2; // 批量请求允许更长超时
        
        foreach (var header in _defaultHeaders)
            webRequest.SetRequestHeader(header.Key, header.Value);
        
        var operation = webRequest.SendWebRequest();
        while (!operation.isDone)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                webRequest.Abort();
                throw new OperationCanceledException(cancellationToken);
            }
            await Task.Yield();
        }
        
        if (webRequest.result != UnityWebRequest.Result.Success)
            throw new GraphQLNetworkException(webRequest.error);
            
        return JsonConvert.DeserializeObject<List<GraphQLResponse<JObject>>>(
            webRequest.downloadHandler.text);
    }
    
    public NetworkStats GetStats() => new NetworkStats(
        _totalRequests, _failedRequests, 
        _totalRequests > 0 ? _totalLatencyMs / _totalRequests : 0);
}

public record NetworkStats(int TotalRequests, int FailedRequests, double AvgLatencyMs);
public class GraphQLException : Exception { public GraphQLException(string msg, Exception inner = null) : base(msg, inner) { } }
public class GraphQLNetworkException : GraphQLException { public GraphQLNetworkException(string msg) : base(msg) { } }
```

### 2.2 查询文件管理系统

在大型项目中，将GraphQL查询字符串硬编码在C#代码中难以维护。推荐将查询存储为独立文件：

```csharp
/// <summary>
/// GraphQL查询文件加载器
/// 查询文件放在 Resources/GraphQL/*.graphql
/// </summary>
public static class GraphQLQueryLoader
{
    private static readonly Dictionary<string, string> _queryCache = new();
    
    /// <summary>
    /// 加载查询文件，支持片段（Fragment）包含
    /// </summary>
    public static string Load(string queryName)
    {
        if (_queryCache.TryGetValue(queryName, out string cached))
            return cached;
        
        // 从Resources加载
        var asset = Resources.Load<TextAsset>($"GraphQL/{queryName}");
        if (asset == null)
            throw new InvalidOperationException($"GraphQL查询文件不存在: GraphQL/{queryName}.graphql");
        
        string query = ResolveFragments(asset.text);
        _queryCache[queryName] = query;
        return query;
    }
    
    /// <summary>
    /// 解析 #import 指令，合并片段文件
    /// </summary>
    private static string ResolveFragments(string query)
    {
        var lines = query.Split('\n');
        var result = new StringBuilder();
        var importedFragments = new HashSet<string>();
        
        foreach (var line in lines)
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("#import "))
            {
                string fragmentName = trimmed.Substring(8).Trim().Trim('"');
                if (!importedFragments.Contains(fragmentName))
                {
                    importedFragments.Add(fragmentName);
                    var fragmentAsset = Resources.Load<TextAsset>($"GraphQL/fragments/{fragmentName}");
                    if (fragmentAsset != null)
                        result.AppendLine(fragmentAsset.text);
                }
            }
            else
            {
                result.AppendLine(line);
            }
        }
        
        return result.ToString();
    }
    
    public static void ClearCache() => _queryCache.Clear();
}
```

**查询文件示例（Resources/GraphQL/GetPlayerInfo.graphql）：**

```graphql
#import "PlayerFragment"
#import "InventoryFragment"

query GetPlayerInfo($playerId: ID!) {
  player(id: $playerId) {
    ...PlayerFields
    inventory {
      ...InventoryFields
    }
    statistics {
      totalBattles
      winRate
      highestScore
    }
  }
}
```

```graphql
# Resources/GraphQL/fragments/PlayerFragment.graphql
fragment PlayerFields on Player {
  id
  name
  level
  experience
  avatar
  title
  vipLevel
}
```

---

## 三、多级缓存架构设计

游戏客户端需要一套完善的缓存系统来减少不必要的网络请求，尤其是在弱网环境和切场景时：

### 3.1 三级缓存架构

```csharp
/// <summary>
/// 三级缓存系统：
/// L1 - 内存缓存（最快，容量小，进程生命周期）
/// L2 - SQLite持久化缓存（中速，容量大，跨会话）
/// L3 - 网络请求（最慢，最新数据）
/// </summary>
public class GraphQLCacheLayer
{
    // L1: 内存缓存
    private readonly LRUCache<string, CacheEntry> _memoryCache;
    
    // L2: 持久化缓存（SQLite）
    private readonly IPersistentCache _persistentCache;
    
    private readonly GraphQLHttpClient _httpClient;
    
    public GraphQLCacheLayer(
        GraphQLHttpClient httpClient,
        IPersistentCache persistentCache,
        int memoryCacheCapacity = 200)
    {
        _httpClient = httpClient;
        _persistentCache = persistentCache;
        _memoryCache = new LRUCache<string, CacheEntry>(memoryCacheCapacity);
    }
    
    /// <summary>
    /// 带缓存的查询方法
    /// </summary>
    /// <param name="request">GraphQL请求</param>
    /// <param name="cachePolicy">缓存策略</param>
    /// <param name="ttlSeconds">缓存有效期（秒）</param>
    public async Task<T> QueryWithCacheAsync<T>(
        GraphQLRequest request,
        CachePolicy cachePolicy = CachePolicy.CacheFirst,
        int ttlSeconds = 300,
        CancellationToken cancellationToken = default)
    {
        string cacheKey = ComputeCacheKey(request);
        
        switch (cachePolicy)
        {
            case CachePolicy.CacheFirst:
                return await CacheFirstStrategy<T>(request, cacheKey, ttlSeconds, cancellationToken);
            
            case CachePolicy.NetworkFirst:
                return await NetworkFirstStrategy<T>(request, cacheKey, ttlSeconds, cancellationToken);
            
            case CachePolicy.CacheOnly:
                return await CacheOnlyStrategy<T>(cacheKey);
            
            case CachePolicy.NetworkOnly:
                return await NetworkOnlyStrategy<T>(request, cancellationToken);
            
            case CachePolicy.StaleWhileRevalidate:
                return await StaleWhileRevalidateStrategy<T>(request, cacheKey, ttlSeconds, cancellationToken);
            
            default:
                throw new ArgumentOutOfRangeException(nameof(cachePolicy));
        }
    }
    
    private async Task<T> CacheFirstStrategy<T>(
        GraphQLRequest request, string cacheKey, int ttlSeconds,
        CancellationToken cancellationToken)
    {
        // 1. 查L1内存缓存
        if (_memoryCache.TryGet(cacheKey, out var memEntry) && !memEntry.IsExpired)
        {
            return memEntry.Deserialize<T>();
        }
        
        // 2. 查L2持久化缓存
        var persistedEntry = await _persistentCache.GetAsync(cacheKey);
        if (persistedEntry != null && !persistedEntry.IsExpired)
        {
            // 回填L1
            _memoryCache.Set(cacheKey, persistedEntry);
            return persistedEntry.Deserialize<T>();
        }
        
        // 3. 发起网络请求
        var response = await _httpClient.QueryAsync<T>(request, cancellationToken);
        
        if (!response.HasErrors)
        {
            var entry = CacheEntry.Create(response.Data, ttlSeconds);
            _memoryCache.Set(cacheKey, entry);
            await _persistentCache.SetAsync(cacheKey, entry);
        }
        
        return response.Data;
    }
    
    private async Task<T> StaleWhileRevalidateStrategy<T>(
        GraphQLRequest request, string cacheKey, int ttlSeconds,
        CancellationToken cancellationToken)
    {
        T cachedData = default;
        bool hasCachedData = false;
        
        // 尝试获取缓存数据（即使已过期也返回）
        if (_memoryCache.TryGet(cacheKey, out var memEntry))
        {
            cachedData = memEntry.Deserialize<T>();
            hasCachedData = true;
        }
        
        if (hasCachedData)
        {
            // 在后台异步刷新缓存
            _ = Task.Run(async () =>
            {
                try
                {
                    var freshResponse = await _httpClient.QueryAsync<T>(request, CancellationToken.None);
                    if (!freshResponse.HasErrors)
                    {
                        var newEntry = CacheEntry.Create(freshResponse.Data, ttlSeconds);
                        _memoryCache.Set(cacheKey, newEntry);
                        await _persistentCache.SetAsync(cacheKey, newEntry);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning($"[GraphQL] StaleWhileRevalidate后台刷新失败: {e.Message}");
                }
            }, CancellationToken.None);
            
            // 立即返回缓存数据（不等待刷新完成）
            return cachedData;
        }
        
        // 没有缓存，必须等待网络
        return await NetworkOnlyStrategy<T>(request, cancellationToken);
    }
    
    private async Task<T> NetworkFirstStrategy<T>(
        GraphQLRequest request, string cacheKey, int ttlSeconds,
        CancellationToken cancellationToken)
    {
        try
        {
            var response = await _httpClient.QueryAsync<T>(request, cancellationToken);
            if (!response.HasErrors)
            {
                var entry = CacheEntry.Create(response.Data, ttlSeconds);
                _memoryCache.Set(cacheKey, entry);
                await _persistentCache.SetAsync(cacheKey, entry);
                return response.Data;
            }
        }
        catch (GraphQLNetworkException)
        {
            // 网络失败时降级到缓存
            Debug.LogWarning("[GraphQL] 网络请求失败，降级使用缓存数据");
        }
        
        // 降级：使用缓存（即使过期）
        if (_memoryCache.TryGet(cacheKey, out var fallbackEntry))
            return fallbackEntry.Deserialize<T>();
        
        var persistedFallback = await _persistentCache.GetAsync(cacheKey);
        if (persistedFallback != null)
            return persistedFallback.Deserialize<T>();
        
        throw new GraphQLException("网络请求失败且无缓存数据可用");
    }
    
    private Task<T> CacheOnlyStrategy<T>(string cacheKey)
    {
        if (_memoryCache.TryGet(cacheKey, out var entry))
            return Task.FromResult(entry.Deserialize<T>());
        throw new GraphQLException($"缓存中没有数据: {cacheKey}");
    }
    
    private async Task<T> NetworkOnlyStrategy<T>(
        GraphQLRequest request, CancellationToken cancellationToken)
    {
        var response = await _httpClient.QueryAsync<T>(request, cancellationToken);
        if (response.HasErrors)
            throw new GraphQLException(string.Join("; ", response.Errors.ConvertAll(e => e.Message)));
        return response.Data;
    }
    
    /// <summary>
    /// 缓存失效：当写操作（Mutation）后需要清除相关缓存
    /// </summary>
    public void Invalidate(string cacheKeyPattern)
    {
        _memoryCache.RemoveByPattern(cacheKeyPattern);
        _ = _persistentCache.RemoveByPatternAsync(cacheKeyPattern);
    }
    
    private static string ComputeCacheKey(GraphQLRequest request)
    {
        string queryHash = ComputeHash(request.Query);
        string varHash = request.Variables != null 
            ? ComputeHash(JsonConvert.SerializeObject(request.Variables, Formatting.None))
            : "null";
        return $"gql:{queryHash}:{varHash}";
    }
    
    private static string ComputeHash(string input)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        byte[] bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToBase64String(bytes)[..16]; // 取前16字符
    }
}

public enum CachePolicy
{
    CacheFirst,            // 优先缓存，缓存失效才走网络
    NetworkFirst,          // 优先网络，网络失败降级到缓存
    CacheOnly,             // 只用缓存，缓存缺失直接报错
    NetworkOnly,           // 只用网络，不缓存
    StaleWhileRevalidate   // 立即返回缓存，后台刷新
}
```

### 3.2 LRU缓存实现

```csharp
/// <summary>
/// 线程安全的LRU（Least Recently Used）缓存
/// </summary>
public class LRUCache<TKey, TValue>
{
    private readonly int _capacity;
    private readonly Dictionary<TKey, LinkedListNode<(TKey Key, TValue Value)>> _map;
    private readonly LinkedList<(TKey Key, TValue Value)> _list;
    private readonly object _lock = new();
    
    public LRUCache(int capacity)
    {
        _capacity = capacity;
        _map = new Dictionary<TKey, LinkedListNode<(TKey, TValue)>>(capacity);
        _list = new LinkedList<(TKey, TValue)>();
    }
    
    public bool TryGet(TKey key, out TValue value)
    {
        lock (_lock)
        {
            if (!_map.TryGetValue(key, out var node))
            {
                value = default;
                return false;
            }
            
            // 移到队头（最近使用）
            _list.Remove(node);
            _list.AddFirst(node);
            
            value = node.Value.Value;
            return true;
        }
    }
    
    public void Set(TKey key, TValue value)
    {
        lock (_lock)
        {
            if (_map.TryGetValue(key, out var existingNode))
            {
                _list.Remove(existingNode);
                _map.Remove(key);
            }
            else if (_map.Count >= _capacity)
            {
                // 移除最久未使用的（队尾）
                var lru = _list.Last;
                _list.RemoveLast();
                _map.Remove(lru.Value.Key);
            }
            
            var newNode = _list.AddFirst((key, value));
            _map[key] = newNode;
        }
    }
    
    public void RemoveByPattern(string pattern)
    {
        lock (_lock)
        {
            var keysToRemove = new List<TKey>();
            
            foreach (var key in _map.Keys)
            {
                string keyStr = key.ToString();
                if (keyStr != null && WildcardMatch(keyStr, pattern))
                    keysToRemove.Add(key);
            }
            
            foreach (var key in keysToRemove)
            {
                if (_map.TryGetValue(key, out var node))
                {
                    _list.Remove(node);
                    _map.Remove(key);
                }
            }
        }
    }
    
    private static bool WildcardMatch(string text, string pattern)
    {
        // 简单通配符匹配：支持 * 和前缀匹配
        if (pattern.EndsWith("*"))
            return text.StartsWith(pattern[..^1]);
        if (pattern.StartsWith("*"))
            return text.EndsWith(pattern[1..]);
        return text == pattern;
    }
}
```

---

## 四、REST与GraphQL的协作边界

### 4.1 统一数据仓库（Repository模式）

UI层不应该知道数据来自GraphQL还是REST，通过Repository模式统一封装：

```csharp
/// <summary>
/// 玩家数据仓库：统一GraphQL查询与REST调用
/// </summary>
public class PlayerRepository
{
    private readonly GraphQLCacheLayer _graphqlCache;
    private readonly RestApiClient _restClient;
    private readonly GraphQLHttpClient _graphqlClient;
    
    // 定义GraphQL查询
    private const string GetPlayerInfoQuery = @"
        query GetPlayerInfo($id: ID!) {
            player(id: $id) {
                id name level experience
                avatar title vipLevel
                statistics { totalBattles winRate }
            }
        }";
    
    private const string UpdatePlayerTitleMutation = @"
        mutation UpdateTitle($playerId: ID!, $titleId: String!) {
            updatePlayerTitle(playerId: $playerId, titleId: $titleId) {
                success
                player { id title }
            }
        }";
    
    public PlayerRepository(
        GraphQLCacheLayer graphqlCache,
        RestApiClient restClient,
        GraphQLHttpClient graphqlClient)
    {
        _graphqlCache = graphqlCache;
        _restClient = restClient;
        _graphqlClient = graphqlClient;
    }
    
    /// <summary>
    /// 获取玩家信息（带缓存）
    /// </summary>
    public async Task<PlayerInfo> GetPlayerInfoAsync(
        string playerId,
        CachePolicy policy = CachePolicy.CacheFirst,
        CancellationToken ct = default)
    {
        var request = new GraphQLRequest
        {
            Query = GetPlayerInfoQuery,
            Variables = new Dictionary<string, object> { ["id"] = playerId }
        };
        
        var result = await _graphqlCache.QueryWithCacheAsync<GetPlayerInfoResponse>(
            request, policy, ttlSeconds: 300, ct);
        
        return result.Player;
    }
    
    /// <summary>
    /// 更新玩家称号（Mutation，同时失效相关缓存）
    /// </summary>
    public async Task<bool> UpdatePlayerTitleAsync(
        string playerId, string titleId, CancellationToken ct = default)
    {
        var request = new GraphQLRequest
        {
            Query = UpdatePlayerTitleMutation,
            Variables = new Dictionary<string, object>
            {
                ["playerId"] = playerId,
                ["titleId"] = titleId
            }
        };
        
        var response = await _graphqlClient.QueryAsync<UpdateTitleResponse>(request, ct);
        
        if (!response.HasErrors && response.Data.UpdatePlayerTitle.Success)
        {
            // 失效该玩家的所有相关缓存
            _graphqlCache.Invalidate($"gql:*{playerId}*");
        }
        
        return response.Data?.UpdatePlayerTitle?.Success ?? false;
    }
    
    /// <summary>
    /// 下载头像文件（REST，GraphQL不适合二进制文件）
    /// </summary>
    public async Task<Texture2D> GetPlayerAvatarTextureAsync(
        string avatarUrl, CancellationToken ct = default)
    {
        // 大文件走REST/CDN，不经过GraphQL
        return await _restClient.DownloadTextureAsync(avatarUrl, ct);
    }
    
    /// <summary>
    /// 批量获取多个玩家信息（利用GraphQL批量请求）
    /// </summary>
    public async Task<Dictionary<string, PlayerInfo>> GetMultiplePlayersAsync(
        List<string> playerIds, CancellationToken ct = default)
    {
        // 构建批量查询（GraphQL别名技术）
        var sb = new StringBuilder("query BatchGetPlayers {");
        for (int i = 0; i < playerIds.Count; i++)
        {
            sb.AppendLine($@"
                p{i}: player(id: ""{playerIds[i]}"") {{
                    id name level avatar
                }}");
        }
        sb.Append('}');
        
        var request = new GraphQLRequest { Query = sb.ToString() };
        var response = await _graphqlClient.QueryAsync<JObject>(request, ct);
        
        var result = new Dictionary<string, PlayerInfo>();
        for (int i = 0; i < playerIds.Count; i++)
        {
            var playerData = response.Data[$"p{i}"];
            if (playerData != null)
            {
                var info = playerData.ToObject<PlayerInfo>();
                result[playerIds[i]] = info;
            }
        }
        return result;
    }
}

// 数据模型
public class PlayerInfo
{
    [JsonProperty("id")] public string Id { get; set; }
    [JsonProperty("name")] public string Name { get; set; }
    [JsonProperty("level")] public int Level { get; set; }
    [JsonProperty("experience")] public long Experience { get; set; }
    [JsonProperty("avatar")] public string Avatar { get; set; }
    [JsonProperty("title")] public string Title { get; set; }
    [JsonProperty("vipLevel")] public int VipLevel { get; set; }
    [JsonProperty("statistics")] public PlayerStatistics Statistics { get; set; }
}

public class PlayerStatistics
{
    [JsonProperty("totalBattles")] public int TotalBattles { get; set; }
    [JsonProperty("winRate")] public float WinRate { get; set; }
}

public class GetPlayerInfoResponse
{
    [JsonProperty("player")] public PlayerInfo Player { get; set; }
}

public class UpdateTitleResponse
{
    [JsonProperty("updatePlayerTitle")] public UpdateTitleResult UpdatePlayerTitle { get; set; }
}

public class UpdateTitleResult
{
    [JsonProperty("success")] public bool Success { get; set; }
    [JsonProperty("player")] public PlayerInfo Player { get; set; }
}
```

---

## 五、WebSocket订阅：GraphQL Subscription实现

对于实时数据（好友在线状态、公会消息、活动倒计时），GraphQL Subscription提供了优雅的推送机制：

```csharp
/// <summary>
/// GraphQL Subscription WebSocket客户端
/// 遵循 graphql-ws 协议（2021年标准）
/// </summary>
public class GraphQLSubscriptionClient : IDisposable
{
    private WebSocket _webSocket;
    private CancellationTokenSource _cts;
    private readonly string _wsEndpoint;
    private readonly Dictionary<string, Action<JObject>> _subscriptions;
    private int _subscriptionIdCounter;
    
    public GraphQLSubscriptionClient(string wsEndpoint)
    {
        _wsEndpoint = wsEndpoint;
        _subscriptions = new Dictionary<string, Action<JObject>>();
        _cts = new CancellationTokenSource();
    }
    
    public async Task ConnectAsync()
    {
        _webSocket = new ClientWebSocket();
        _webSocket.Options.AddSubProtocol("graphql-transport-ws");
        
        await _webSocket.ConnectAsync(new Uri(_wsEndpoint), _cts.Token);
        
        // 发送连接初始化消息
        await SendMessageAsync(new { type = "connection_init", payload = new { } });
        
        // 启动消息接收循环
        _ = ReceiveLoopAsync();
    }
    
    /// <summary>
    /// 订阅实时数据
    /// </summary>
    public async Task<string> SubscribeAsync(
        string query, 
        Dictionary<string, object> variables,
        Action<JObject> onData)
    {
        string subscriptionId = $"sub_{++_subscriptionIdCounter}";
        _subscriptions[subscriptionId] = onData;
        
        await SendMessageAsync(new
        {
            id = subscriptionId,
            type = "subscribe",
            payload = new
            {
                query = query,
                variables = variables
            }
        });
        
        return subscriptionId;
    }
    
    public async Task UnsubscribeAsync(string subscriptionId)
    {
        _subscriptions.Remove(subscriptionId);
        await SendMessageAsync(new { id = subscriptionId, type = "complete" });
    }
    
    private async Task ReceiveLoopAsync()
    {
        var buffer = new byte[4096];
        var messageBuffer = new StringBuilder();
        
        try
        {
            while (_webSocket.State == WebSocketState.Open && !_cts.Token.IsCancellationRequested)
            {
                var result = await _webSocket.ReceiveAsync(
                    new ArraySegment<byte>(buffer), _cts.Token);
                
                messageBuffer.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                
                if (result.EndOfMessage)
                {
                    HandleMessage(messageBuffer.ToString());
                    messageBuffer.Clear();
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception e)
        {
            Debug.LogError($"[GraphQL Subscription] 接收错误: {e.Message}");
            // 触发重连逻辑
            _ = ReconnectAsync();
        }
    }
    
    private void HandleMessage(string messageJson)
    {
        var message = JObject.Parse(messageJson);
        string type = message["type"]?.ToString();
        
        switch (type)
        {
            case "next":
                string subId = message["id"]?.ToString();
                if (subId != null && _subscriptions.TryGetValue(subId, out var handler))
                {
                    var data = message["payload"]?["data"] as JObject;
                    if (data != null)
                    {
                        // 在主线程执行回调（Unity要求UI操作在主线程）
                        UnityMainThread.Enqueue(() => handler(data));
                    }
                }
                break;
                
            case "error":
                Debug.LogError($"[GraphQL Subscription] 错误: {message["payload"]}");
                break;
                
            case "connection_ack":
                Debug.Log("[GraphQL Subscription] 连接建立");
                break;
        }
    }
    
    private async Task SendMessageAsync(object message)
    {
        string json = JsonConvert.SerializeObject(message);
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        await _webSocket.SendAsync(
            new ArraySegment<byte>(bytes), 
            WebSocketMessageType.Text, 
            true, 
            _cts.Token);
    }
    
    private async Task ReconnectAsync()
    {
        // 指数退避重连
        int delay = 1000;
        while (!_cts.Token.IsCancellationRequested)
        {
            await Task.Delay(delay, _cts.Token);
            try
            {
                await ConnectAsync();
                
                // 重新建立所有订阅
                // ...
                return;
            }
            catch
            {
                delay = Math.Min(delay * 2, 30000); // 最大30秒
            }
        }
    }
    
    public void Dispose()
    {
        _cts.Cancel();
        _webSocket?.Dispose();
    }
}
```

**使用示例：订阅好友在线状态**

```csharp
public class FriendStatusService : IDisposable
{
    private readonly GraphQLSubscriptionClient _subscriptionClient;
    private string _subscriptionId;
    
    private const string FriendStatusSubscription = @"
        subscription OnFriendStatusChanged($playerId: ID!) {
            friendStatusChanged(playerId: $playerId) {
                friendId
                status
                lastSeen
                currentScene
            }
        }";
    
    public event Action<string, FriendStatus> OnFriendStatusChanged;
    
    public async Task StartWatchingFriendsAsync(string playerId)
    {
        _subscriptionId = await _subscriptionClient.SubscribeAsync(
            FriendStatusSubscription,
            new Dictionary<string, object> { ["playerId"] = playerId },
            data =>
            {
                var statusChange = data["friendStatusChanged"]?.ToObject<FriendStatusChange>();
                if (statusChange != null)
                {
                    OnFriendStatusChanged?.Invoke(statusChange.FriendId, statusChange.Status);
                }
            });
    }
    
    public void Dispose()
    {
        if (_subscriptionId != null)
            _ = _subscriptionClient.UnsubscribeAsync(_subscriptionId);
    }
}
```

---

## 六、最佳实践总结

### 架构决策树

```
需要的数据来自哪里？
    │
    ├─→ 需要复杂聚合/灵活字段选择 → GraphQL Query
    │       │
    │       ├─→ 数据更新频率低（角色信息、商城商品）→ CacheFirst
    │       ├─→ 数据需要实时性（排行榜）→ StaleWhileRevalidate
    │       └─→ 实时推送（好友状态）→ GraphQL Subscription
    │
    ├─→ 简单CRUD / 文件下载 → REST
    │       │
    │       ├─→ 静态资源（图片、音效、配置）→ CDN + REST
    │       └─→ 简单数据操作 → REST API
    │
    └─→ 实时战斗数据 → UDP/KCP（不走GraphQL/REST）
```

### 性能优化要点

1. **查询字段精简**：永远只查询当前页面需要的字段，杜绝过度获取
2. **批量请求合并**：对同一帧内的多个查询使用Batching合并为单个HTTP请求
3. **持久化查询（Persisted Queries）**：将查询字符串替换为Hash，减少请求体积50%以上
4. **缓存策略按场景选择**：
   - 登录场景：CacheFirst（优先本地数据，加快启动）
   - 游戏大厅：StaleWhileRevalidate（快速显示+后台更新）
   - 重要操作前（支付等）：NetworkOnly（确保数据最新）
5. **乐观更新**：Mutation发起后立即更新本地缓存，提升UI响应速度

### 常见陷阱与规避

```csharp
// ❌ 问题：N+1查询（在循环中发起查询）
foreach (var friendId in friendIds)
{
    var friend = await playerRepo.GetPlayerInfoAsync(friendId); // N次请求！
    friendList.Add(friend);
}

// ✅ 解决：批量查询
var friends = await playerRepo.GetMultiplePlayersAsync(friendIds);

// ❌ 问题：忘记在Mutation后失效缓存
await playerRepo.UpdatePlayerTitleAsync(playerId, newTitle);
// 此后读取的是旧缓存！

// ✅ 解决：Repository中统一管理缓存失效
// （已在上述 UpdatePlayerTitleAsync 实现中处理）

// ❌ 问题：Subscription连接泄漏
var subId = await subscriptionClient.SubscribeAsync(query, vars, handler);
// 场景切换时忘记取消订阅，导致内存泄漏和多余回调

// ✅ 解决：绑定到MonoBehaviour生命周期
public class MyUI : MonoBehaviour, IDisposable
{
    private string _subId;
    
    async void Start() 
    { 
        _subId = await subscriptionClient.SubscribeAsync(...); 
    }
    
    void OnDestroy() 
    { 
        if (_subId != null) 
            _ = subscriptionClient.UnsubscribeAsync(_subId); 
    }
}
```

---

## 结语

GraphQL与REST的混合架构并非"最新技术的堆砌"，而是针对游戏客户端特定需求的务实选择：用正确的工具处理正确的问题。

GraphQL的灵活查询解决了游戏UI多样化数据需求的痛点；REST的简单高效保障了资源文件的高速下载；WebSocket Subscription提供了优雅的实时数据推送机制。三者有机结合，配以完善的缓存策略，能显著提升游戏客户端的网络层质量和开发效率。

真正的工程价值不在于引入了多少新技术，而在于以合理的复杂度解决了实际问题。

---

*参考资料：*
- *GraphQL规范：https://spec.graphql.org/*
- *graphql-ws协议：https://github.com/enisdenjo/graphql-ws*
- *Apollo Client缓存设计：https://www.apollographql.com/docs/react/caching/overview*
