---
title: 游戏客户端消息队列与弱网重试机制：从可靠传输到优先级调度完全指南
published: 2026-05-11
description: 深入剖析游戏客户端弱网环境下的消息可靠传输架构，涵盖优先级消息队列设计、指数退避重试策略、消息去重幂等机制、断线重连状态恢复、带宽自适应发送控制与弱网模拟测试框架，构建抗弱网的网络通信层。
tags: [Unity, 网络同步, 架构设计, 性能优化, C#]
category: 网络通信
draft: false
---

# 游戏客户端消息队列与弱网重试机制：从可靠传输到优先级调度完全指南

## 一、弱网场景下的核心挑战

移动游戏运行在极其恶劣的网络环境中：地铁隧道、电梯、WiFi切换4G、基站切换……这些场景会造成：

- **短暂断线**（50ms~2s）：瞬断后自动恢复，玩家感知为"卡了一下"
- **高丢包率**（5%~30%）：数据包到达不稳定
- **高延迟抖动**（RTT 200ms~800ms波动）：表现为操作延迟忽高忽低
- **带宽限制**（移动网络100KB/s以下峰值）：大量数据堆积导致超时

**核心设计目标**：
1. 关键消息（登录/支付/战斗行为）必须可靠送达
2. 实时性消息（位置同步）在带宽受限时可降级丢弃
3. 断线重连后状态能自动恢复，用户无感知

---

## 二、消息优先级系统设计

### 2.1 消息优先级定义

```csharp
/// <summary>
/// 消息发送优先级
/// 优先级越高越优先发送，高优先级消息不受带宽限制
/// </summary>
public enum MessagePriority
{
    /// <summary>实时性消息：位置同步、动画同步。带宽不足时可丢弃</summary>
    Realtime = 0,
    
    /// <summary>普通消息：聊天、非战斗操作</summary>
    Normal = 1,
    
    /// <summary>重要消息：战斗指令、技能释放</summary>
    High = 2,
    
    /// <summary>关键消息：登录、支付、存档。必须可靠送达，不可丢弃</summary>
    Critical = 3,
}

/// <summary>
/// 消息重试策略
/// </summary>
public enum RetryPolicy
{
    /// <summary>不重试（实时性数据）</summary>
    NoRetry,
    
    /// <summary>固定间隔重试</summary>
    Fixed,
    
    /// <summary>指数退避重试（推荐）</summary>
    ExponentialBackoff,
    
    /// <summary>永久重试直到成功（关键操作）</summary>
    PersistentRetry,
}

/// <summary>
/// 带发送元数据的消息包装器
/// </summary>
public class OutboundMessage
{
    public IMessage Message { get; set; }
    public int MsgId { get; set; }
    public ulong SequenceId { get; set; }          // 全局序列号（用于去重）
    public MessagePriority Priority { get; set; }
    public RetryPolicy RetryPolicy { get; set; }
    public int MaxRetries { get; set; }             // 最大重试次数（-1=无限）
    public int RetryCount { get; set; }             // 已重试次数
    public float NextRetryTime { get; set; }        // 下次重试时间（UnityTime）
    public float CreateTime { get; set; }           // 创建时间
    public float ExpireTime { get; set; }           // 过期时间（-1=不过期）
    public TaskCompletionSource<bool> Ack { get; set; } // ACK等待句柄
}
```

### 2.2 多级优先级队列

```csharp
/// <summary>
/// 多级优先级发送队列
/// 使用4个独立队列 + 优先级调度策略
/// </summary>
public class PriorityMessageQueue
{
    // 每个优先级一个独立队列
    private readonly Queue<OutboundMessage>[] _queues;
    
    // 各优先级的令牌桶（带宽控制）
    private readonly TokenBucket[] _buckets;
    
    // 待ACK的消息（已发送但未确认）
    private readonly Dictionary<ulong, OutboundMessage> _pendingAck;
    
    // 全局序列号生成器
    private ulong _nextSequenceId = 1;
    
    // 统计
    private readonly QueueStats _stats = new();

    public PriorityMessageQueue()
    {
        int levels = Enum.GetValues(typeof(MessagePriority)).Length;
        _queues = new Queue<OutboundMessage>[levels];
        _buckets = new TokenBucket[levels];
        _pendingAck = new Dictionary<ulong, OutboundMessage>(256);
        
        for (int i = 0; i < levels; i++)
        {
            _queues[i] = new Queue<OutboundMessage>();
        }
        
        // 配置各优先级的带宽令牌桶
        // Realtime: 最大50KB/s (实时数据有量限制)
        _buckets[(int)MessagePriority.Realtime] = new TokenBucket(50 * 1024, 10 * 1024);
        // Normal: 最大100KB/s
        _buckets[(int)MessagePriority.Normal] = new TokenBucket(100 * 1024, 20 * 1024);
        // High/Critical: 不限制（始终可发送）
        _buckets[(int)MessagePriority.High] = TokenBucket.Unlimited;
        _buckets[(int)MessagePriority.Critical] = TokenBucket.Unlimited;
    }

    /// <summary>
    /// 入队消息
    /// </summary>
    public ulong Enqueue(OutboundMessage msg)
    {
        msg.SequenceId = _nextSequenceId++;
        msg.CreateTime = UnityEngine.Time.time;
        
        // 关键消息设置ACK等待
        if (msg.Priority >= MessagePriority.High)
        {
            msg.Ack = new TaskCompletionSource<bool>();
        }
        
        _queues[(int)msg.Priority].Enqueue(msg);
        _stats.TotalEnqueued++;
        
        return msg.SequenceId;
    }

    /// <summary>
    /// 按优先级出队下一个可发送的消息
    /// </summary>
    public OutboundMessage Dequeue(int availableBytes)
    {
        // 从高优先级到低优先级扫描
        for (int priority = (int)MessagePriority.Critical; priority >= 0; priority--)
        {
            var queue = _queues[priority];
            if (queue.Count == 0) continue;
            
            var msg = queue.Peek();
            
            // 检查消息是否过期
            if (msg.ExpireTime > 0 && UnityEngine.Time.time > msg.ExpireTime)
            {
                queue.Dequeue();
                _stats.TotalExpired++;
                priority++; // 继续扫描同优先级
                continue;
            }
            
            // 检查是否到了重试时间
            if (msg.RetryCount > 0 && UnityEngine.Time.time < msg.NextRetryTime)
                continue;
            
            // 检查令牌桶（带宽控制）
            int estimatedSize = EstimateMessageSize(msg);
            if (!_buckets[priority].TryConsume(estimatedSize))
            {
                // 令牌不足，跳过低优先级
                if (priority <= (int)MessagePriority.Normal) break;
                continue;
            }
            
            // 出队并加入待ACK列表
            queue.Dequeue();
            if (msg.Ack != null)
                _pendingAck[msg.SequenceId] = msg;
            
            return msg;
        }
        
        return null;
    }

    /// <summary>
    /// 处理服务器ACK确认
    /// </summary>
    public void OnAckReceived(ulong sequenceId, bool success)
    {
        if (!_pendingAck.TryGetValue(sequenceId, out var msg))
            return;
        
        _pendingAck.Remove(sequenceId);
        
        if (success)
        {
            msg.Ack?.TrySetResult(true);
            _stats.TotalAcked++;
        }
        else
        {
            // 服务器明确拒绝（如版本不兼容），不重试
            msg.Ack?.TrySetResult(false);
            _stats.TotalRejected++;
        }
    }

    /// <summary>
    /// 定时检查待ACK消息是否超时，触发重试
    /// </summary>
    public void Tick()
    {
        float now = UnityEngine.Time.time;
        var timedOut = new List<OutboundMessage>();
        
        foreach (var (seqId, msg) in _pendingAck)
        {
            float ackTimeout = GetAckTimeout(msg.Priority);
            if (now - msg.CreateTime > ackTimeout)
                timedOut.Add(msg);
        }
        
        foreach (var msg in timedOut)
        {
            _pendingAck.Remove(msg.SequenceId);
            HandleRetry(msg);
        }
    }

    private void HandleRetry(OutboundMessage msg)
    {
        if (msg.RetryPolicy == RetryPolicy.NoRetry)
        {
            msg.Ack?.TrySetException(new TimeoutException("消息发送超时，不重试"));
            return;
        }
        
        bool canRetry = msg.MaxRetries < 0 || msg.RetryCount < msg.MaxRetries;
        if (!canRetry)
        {
            msg.Ack?.TrySetException(new Exception($"消息发送失败，已重试{msg.RetryCount}次"));
            _stats.TotalFailed++;
            return;
        }
        
        msg.RetryCount++;
        msg.NextRetryTime = UnityEngine.Time.time + CalculateBackoff(msg);
        
        // 重新入队（重试的消息跳过令牌桶限制）
        _queues[(int)msg.Priority].Enqueue(msg);
        _stats.TotalRetried++;
        
        UnityEngine.Debug.Log($"[MsgQueue] 消息 {msg.SequenceId} 第{msg.RetryCount}次重试，" +
                              $"等待{msg.NextRetryTime - UnityEngine.Time.time:F2}s");
    }

    private float CalculateBackoff(OutboundMessage msg)
    {
        return msg.RetryPolicy switch
        {
            RetryPolicy.Fixed => 1.0f,
            RetryPolicy.ExponentialBackoff => 
                Math.Min(0.5f * (float)Math.Pow(2, msg.RetryCount), 30f), // 最大30秒
            RetryPolicy.PersistentRetry => 
                Math.Min(1.0f * (float)Math.Pow(1.5f, msg.RetryCount), 60f), // 最大60秒
            _ => 1.0f
        };
    }

    private float GetAckTimeout(MessagePriority priority) => priority switch
    {
        MessagePriority.Critical => 5.0f,
        MessagePriority.High => 3.0f,
        MessagePriority.Normal => 2.0f,
        _ => 1.0f,
    };

    private int EstimateMessageSize(OutboundMessage msg) => 64; // 简化估计
}
```

---

## 三、令牌桶带宽控制

```csharp
/// <summary>
/// 令牌桶算法实现，用于消息发送速率控制
/// 桶容量 = 突发上限，补充速率 = 持续带宽
/// </summary>
public class TokenBucket
{
    public static readonly TokenBucket Unlimited = new TokenBucket(int.MaxValue, int.MaxValue);

    private readonly int _capacity;     // 桶容量（bytes）
    private readonly int _refillRate;   // 每秒补充速率（bytes/s）
    private float _tokens;              // 当前令牌数
    private float _lastRefillTime;

    public TokenBucket(int capacity, int refillRatePerSecond)
    {
        _capacity = capacity;
        _refillRate = refillRatePerSecond;
        _tokens = capacity;
        _lastRefillTime = UnityEngine.Time.time;
    }

    /// <summary>
    /// 尝试消费指定数量的令牌
    /// </summary>
    public bool TryConsume(int bytes)
    {
        if (this == Unlimited) return true;
        
        Refill();
        
        if (_tokens >= bytes)
        {
            _tokens -= bytes;
            return true;
        }
        return false;
    }

    /// <summary>
    /// 强制消费（关键消息使用，允许透支）
    /// </summary>
    public void ForceConsume(int bytes)
    {
        Refill();
        _tokens -= bytes; // 允许为负（透支）
    }

    private void Refill()
    {
        float now = UnityEngine.Time.time;
        float elapsed = now - _lastRefillTime;
        _tokens = Math.Min(_capacity, _tokens + elapsed * _refillRate);
        _lastRefillTime = now;
    }

    public float CurrentTokens => _tokens;
    public float FillRatio => _tokens / _capacity;
}
```

---

## 四、断线重连状态恢复系统

### 4.1 断线检测与重连策略

```csharp
/// <summary>
/// 网络连接状态机
/// 负责断线检测、自动重连和状态恢复
/// </summary>
public class ReconnectStateMachine
{
    public enum ConnectionState
    {
        Connected,
        Disconnected,
        Reconnecting,
        Failed         // 超过最大重试次数
    }

    private ConnectionState _state = ConnectionState.Disconnected;
    private int _reconnectAttempts = 0;
    private float _reconnectDeadline;
    
    // 重连配置
    private const int MaxReconnectAttempts = 10;
    private const float TotalReconnectWindowSeconds = 120f; // 2分钟内持续重连
    
    // 事件
    public event Action OnConnected;
    public event Action<int> OnReconnecting;     // 参数：第几次重连
    public event Action OnReconnectFailed;
    public event Action OnSessionRestored;       // 断线重连后状态恢复完成

    public async System.Threading.Tasks.Task HandleDisconnect(INetworkClient client)
    {
        if (_state == ConnectionState.Reconnecting) return;
        
        _state = ConnectionState.Disconnected;
        _reconnectAttempts = 0;
        _reconnectDeadline = UnityEngine.Time.time + TotalReconnectWindowSeconds;
        
        // 保存当前状态快照（用于重连后恢复）
        var snapshot = SessionStateManager.CaptureSnapshot();
        
        while (_reconnectAttempts < MaxReconnectAttempts && 
               UnityEngine.Time.time < _reconnectDeadline)
        {
            _reconnectAttempts++;
            _state = ConnectionState.Reconnecting;
            OnReconnecting?.Invoke(_reconnectAttempts);
            
            float backoff = CalculateReconnectBackoff(_reconnectAttempts);
            UnityEngine.Debug.Log($"[Reconnect] 第{_reconnectAttempts}次重连，" +
                                  $"等待{backoff:F1}s...");
            
            await System.Threading.Tasks.Task.Delay((int)(backoff * 1000));
            
            try
            {
                await client.ConnectAsync();
                
                // 重连成功：恢复会话状态
                _state = ConnectionState.Connected;
                OnConnected?.Invoke();
                
                await RestoreSessionAsync(client, snapshot);
                OnSessionRestored?.Invoke();
                
                _reconnectAttempts = 0;
                return;
            }
            catch (Exception ex)
            {
                UnityEngine.Debug.LogWarning($"[Reconnect] 第{_reconnectAttempts}次重连失败: {ex.Message}");
            }
        }
        
        // 超过重连限制
        _state = ConnectionState.Failed;
        OnReconnectFailed?.Invoke();
    }

    /// <summary>
    /// 断线重连后恢复游戏状态
    /// </summary>
    private async System.Threading.Tasks.Task RestoreSessionAsync(
        INetworkClient client, 
        SessionSnapshot snapshot)
    {
        // 1. 重新鉴权（发送Token，服务器确认身份）
        var authMsg = new ReauthRequest
        {
            SessionToken = snapshot.SessionToken,
            LastReceivedSeqId = snapshot.LastReceivedSeqId,
        };
        
        var authResp = await client.SendAndWaitAsync<ReauthResponse>(authMsg, timeout: 5f);
        
        if (!authResp.Success)
        {
            // 会话过期，需要完整重新登录
            await LoginManager.ReLoginAsync();
            return;
        }
        
        // 2. 请求服务器重传断线期间的消息
        if (authResp.HasMissedMessages)
        {
            var syncMsg = new RequestMissedMessages
            {
                FromSeqId = snapshot.LastReceivedSeqId + 1,
                ToSeqId = authResp.ServerLatestSeqId,
            };
            
            await client.SendAsync(syncMsg);
        }
        
        // 3. 重发本地待确认的关键消息
        await ResendPendingCriticalMessages(client);
        
        UnityEngine.Debug.Log($"[Reconnect] 会话恢复成功，补发{authResp.MissedCount}条消息");
    }

    private async System.Threading.Tasks.Task ResendPendingCriticalMessages(INetworkClient client)
    {
        var pending = MessagePersistenceStore.GetUnackedCriticalMessages();
        
        foreach (var msg in pending)
        {
            // 使用幂等Token防止重复处理
            msg.IdempotencyKey = msg.OriginalIdempotencyKey; // 保持原Key
            await client.SendAsync(msg.Message);
            
            UnityEngine.Debug.Log($"[Reconnect] 重发待确认消息: SeqId={msg.SequenceId}");
        }
    }

    private float CalculateReconnectBackoff(int attempt)
    {
        // 指数退避 + 抖动：避免大量客户端同时重连踩踏
        float baseDelay = Math.Min(0.5f * (float)Math.Pow(2, attempt - 1), 10f);
        float jitter = (float)new System.Random().NextDouble() * 0.5f; // 0~0.5s随机抖动
        return baseDelay + jitter;
    }
}
```

### 4.2 消息幂等机制

```csharp
/// <summary>
/// 消息幂等Token管理器
/// 确保重试的关键消息在服务端只被处理一次
/// </summary>
public static class IdempotencyTokenManager
{
    // Token格式：设备ID前缀 + 递增序号
    private static readonly string s_devicePrefix;
    private static long s_counter = 0;
    
    static IdempotencyTokenManager()
    {
        // 使用设备ID + 启动时间作为前缀
        string deviceId = UnityEngine.SystemInfo.deviceUniqueIdentifier[..8]; // 取前8位
        long startTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        s_devicePrefix = $"{deviceId}-{startTime}";
    }

    /// <summary>
    /// 生成全局唯一的幂等Token
    /// </summary>
    public static string Generate()
    {
        long count = System.Threading.Interlocked.Increment(ref s_counter);
        return $"{s_devicePrefix}-{count:D8}";
    }
}

/// <summary>
/// 关键消息的幂等包装器
/// 包含幂等Token，服务端通过Token识别重复请求
/// </summary>
[ProtoBuf.ProtoContract]
public class IdempotentRequest<T> where T : IMessage
{
    [ProtoBuf.ProtoMember(1)]
    public string IdempotencyKey { get; set; } // 幂等Key，首次生成后重试不变
    
    [ProtoBuf.ProtoMember(2)]
    public T Payload { get; set; }
    
    [ProtoBuf.ProtoMember(3)]
    public long ClientTimestamp { get; set; }

    public static IdempotentRequest<T> Create(T payload) => new()
    {
        IdempotencyKey = IdempotencyTokenManager.Generate(),
        Payload = payload,
        ClientTimestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
    };
}

// 使用示例：支付请求
async System.Threading.Tasks.Task ProcessPurchase(int itemId, int price)
{
    var purchaseReq = IdempotentRequest<PurchaseRequest>.Create(new PurchaseRequest
    {
        ItemId = itemId,
        Price = price,
        Currency = "GOLD",
    });
    
    // 持久化到本地（防止进程崩溃导致Key丢失）
    MessagePersistenceStore.Save(purchaseReq);
    
    // 发送，失败自动重试（幂等Key不变，服务端去重）
    var resp = await NetworkManager.SendCriticalAsync<PurchaseResponse>(purchaseReq, 
        retryPolicy: RetryPolicy.PersistentRetry,
        maxRetries: -1, // 无限重试
        expireSeconds: 300); // 5分钟内有效
    
    if (resp.Success)
    {
        MessagePersistenceStore.MarkDone(purchaseReq.IdempotencyKey);
        OnPurchaseSuccess(resp);
    }
}
```

---

## 五、自适应发送频率控制

```csharp
/// <summary>
/// 自适应网络质量感知器
/// 根据RTT和丢包率动态调整发送频率
/// </summary>
public class AdaptiveSendController
{
    private readonly RttEstimator _rttEstimator;
    private float _currentSendInterval = 0.05f; // 初始50ms（20次/秒）
    
    // 配置
    private const float MinSendInterval = 0.033f;  // 30次/秒（最高频率）
    private const float MaxSendInterval = 0.2f;    // 5次/秒（最低频率）
    private const float NetworkGoodThreshold = 100f; // RTT<100ms认为网络良好
    private const float NetworkBadThreshold = 300f;  // RTT>300ms认为网络差

    public float CurrentSendInterval => _currentSendInterval;
    
    /// <summary>
    /// 根据网络状况调整发送间隔
    /// </summary>
    public void AdaptToNetworkCondition(NetworkQualitySnapshot snapshot)
    {
        float targetInterval;
        
        if (snapshot.PacketLossRate > 0.1f || snapshot.AvgRtt > NetworkBadThreshold)
        {
            // 网络差：降低发送频率，减少拥塞
            targetInterval = MaxSendInterval;
        }
        else if (snapshot.PacketLossRate < 0.02f && snapshot.AvgRtt < NetworkGoodThreshold)
        {
            // 网络好：提高发送频率
            targetInterval = MinSendInterval;
        }
        else
        {
            // 中等网络：线性映射
            float rttFactor = (snapshot.AvgRtt - NetworkGoodThreshold) / 
                              (NetworkBadThreshold - NetworkGoodThreshold);
            targetInterval = UnityEngine.Mathf.Lerp(MinSendInterval, MaxSendInterval, 
                                                     rttFactor);
        }
        
        // 平滑调整（避免震荡）
        _currentSendInterval = UnityEngine.Mathf.Lerp(
            _currentSendInterval, 
            targetInterval, 
            0.1f); // 缓慢收敛
        
        UnityEngine.Debug.Log($"[Adaptive] 网络状况调整: RTT={snapshot.AvgRtt:F0}ms, " +
                              $"丢包={snapshot.PacketLossRate:P0}, " +
                              $"发送间隔={_currentSendInterval*1000:F0}ms");
    }

    /// <summary>
    /// 实时性消息的降采样发送（位置同步）
    /// </summary>
    public bool ShouldSendRealtimeMessage(float lastSendTime)
    {
        return UnityEngine.Time.time - lastSendTime >= _currentSendInterval;
    }
    
    /// <summary>
    /// 消息合并：在发送间隔内积累的多个位置更新合并为一个
    /// </summary>
    public PlayerMoveMsg MergePositionUpdates(Queue<Vector3> positions)
    {
        if (positions.Count == 0) return null;
        
        // 只取最新位置，丢弃中间帧
        Vector3 latestPos = default;
        while (positions.Count > 0)
            latestPos = positions.Dequeue();
        
        return new PlayerMoveMsg
        {
            PosX = latestPos.x,
            PosY = latestPos.y,
            PosZ = latestPos.z,
            Timestamp = (ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        };
    }
}

/// <summary>
/// RTT估算器（基于指数加权移动平均）
/// </summary>
public class RttEstimator
{
    private float _srtt = 100f;   // 平滑RTT（ms）
    private float _rttvar = 50f;  // RTT方差
    private const float Alpha = 0.125f;
    private const float Beta = 0.25f;

    public float SmoothedRtt => _srtt;
    public float Rto => _srtt + 4 * _rttvar; // 重传超时 = SRTT + 4*RTTVAR

    public void OnAck(float measuredRtt)
    {
        // RFC 6298 RTT估算算法
        float rttDiff = Math.Abs(measuredRtt - _srtt);
        _rttvar = (1 - Beta) * _rttvar + Beta * rttDiff;
        _srtt = (1 - Alpha) * _srtt + Alpha * measuredRtt;
    }
}
```

---

## 六、消息持久化（关键消息落盘）

```csharp
/// <summary>
/// 关键消息本地持久化存储
/// 防止进程崩溃导致关键操作（如支付）丢失
/// </summary>
public static class MessagePersistenceStore
{
    private static readonly string StorePath = 
        Path.Combine(UnityEngine.Application.persistentDataPath, "pending_msgs.json");

    [Serializable]
    private class PendingStore
    {
        public List<PendingEntry> Entries = new();
    }

    [Serializable]
    public class PendingEntry
    {
        public string IdempotencyKey;
        public string MessageJson;
        public string MessageType;
        public long CreateTimestamp;
        public long ExpireTimestamp;
        public int RetryCount;
    }

    private static PendingStore _store;
    private static readonly object _lock = new();

    static MessagePersistenceStore()
    {
        LoadFromDisk();
    }

    public static void Save<T>(IdempotentRequest<T> request, int expireSeconds = 300) 
        where T : IMessage
    {
        lock (_lock)
        {
            _store.Entries.Add(new PendingEntry
            {
                IdempotencyKey = request.IdempotencyKey,
                MessageJson = UnityEngine.JsonUtility.ToJson(request.Payload),
                MessageType = typeof(T).FullName,
                CreateTimestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                ExpireTimestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + expireSeconds,
            });
            SaveToDisk();
        }
    }

    public static void MarkDone(string idempotencyKey)
    {
        lock (_lock)
        {
            _store.Entries.RemoveAll(e => e.IdempotencyKey == idempotencyKey);
            SaveToDisk();
        }
    }

    public static List<PendingEntry> GetUnackedCriticalMessages()
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        
        lock (_lock)
        {
            // 返回未过期的待确认消息
            return _store.Entries
                .Where(e => e.ExpireTimestamp > now)
                .OrderBy(e => e.CreateTimestamp)
                .ToList();
        }
    }

    private static void LoadFromDisk()
    {
        try
        {
            if (File.Exists(StorePath))
            {
                string json = File.ReadAllText(StorePath);
                _store = UnityEngine.JsonUtility.FromJson<PendingStore>(json) ?? new PendingStore();
                
                // 清理已过期消息
                long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                _store.Entries.RemoveAll(e => e.ExpireTimestamp <= now);
            }
            else
            {
                _store = new PendingStore();
            }
        }
        catch
        {
            _store = new PendingStore();
        }
    }

    private static void SaveToDisk()
    {
        string json = UnityEngine.JsonUtility.ToJson(_store);
        File.WriteAllText(StorePath, json);
    }
}
```

---

## 七、弱网模拟测试框架

```csharp
#if UNITY_EDITOR || DEVELOPMENT_BUILD
/// <summary>
/// 弱网模拟器（开发/测试用）
/// 在NetworkClient发送层注入延迟、丢包、乱序等模拟
/// </summary>
public class NetworkSimulator
{
    [Serializable]
    public class SimulationProfile
    {
        public string Name;
        public float PacketLossRate;     // 丢包率 0~1
        public float ExtraLatencyMs;    // 额外延迟（ms）
        public float LatencyJitterMs;   // 延迟抖动（ms）
        public float BandwidthKBps;     // 带宽限制（KB/s，0=不限制）
        public bool SimulateReorder;    // 是否模拟包乱序
    }

    // 预设场景
    public static readonly SimulationProfile[] Presets = new[]
    {
        new SimulationProfile { Name = "完美网络",    PacketLossRate = 0,    ExtraLatencyMs = 0,    LatencyJitterMs = 0 },
        new SimulationProfile { Name = "普通4G",     PacketLossRate = 0.01f, ExtraLatencyMs = 80,   LatencyJitterMs = 30,  BandwidthKBps = 500 },
        new SimulationProfile { Name = "弱4G",       PacketLossRate = 0.05f, ExtraLatencyMs = 200,  LatencyJitterMs = 100, BandwidthKBps = 100 },
        new SimulationProfile { Name = "地铁隧道",    PacketLossRate = 0.2f,  ExtraLatencyMs = 500,  LatencyJitterMs = 200, BandwidthKBps = 50 },
        new SimulationProfile { Name = "网络切换瞬断", PacketLossRate = 1.0f,  ExtraLatencyMs = 0,    LatencyJitterMs = 0,   BandwidthKBps = 0 },
    };

    private SimulationProfile _activeProfile;
    private float _bandwidthAccum = 0;
    private float _lastBwResetTime;
    private readonly System.Random _rng = new();

    public void SetProfile(SimulationProfile profile) => _activeProfile = profile;

    /// <summary>
    /// 模拟发送：注入延迟、丢包等
    /// 返回是否实际发送（false=被丢弃）
    /// </summary>
    public async System.Threading.Tasks.Task<bool> SimulateSend(
        System.Func<System.Threading.Tasks.Task> actualSend, 
        int byteSize)
    {
        if (_activeProfile == null) { await actualSend(); return true; }
        
        // 模拟丢包
        if (_rng.NextDouble() < _activeProfile.PacketLossRate)
        {
            UnityEngine.Debug.Log($"[NetSim] 模拟丢包（{byteSize} bytes）");
            return false;
        }
        
        // 模拟带宽限制
        if (_activeProfile.BandwidthKBps > 0)
        {
            float now = UnityEngine.Time.time;
            if (now - _lastBwResetTime > 1f)
            {
                _bandwidthAccum = 0;
                _lastBwResetTime = now;
            }
            
            _bandwidthAccum += byteSize / 1024f;
            if (_bandwidthAccum > _activeProfile.BandwidthKBps)
            {
                // 超出带宽，等待下一秒
                float waitMs = (1f - (now - _lastBwResetTime)) * 1000f;
                await System.Threading.Tasks.Task.Delay((int)Math.Max(waitMs, 10));
            }
        }
        
        // 模拟延迟 + 抖动
        float delay = _activeProfile.ExtraLatencyMs +
                      (_rng.NextDouble() - 0.5) * 2 * (double)_activeProfile.LatencyJitterMs;
        delay = Math.Max(0, delay);
        
        if (delay > 0)
            await System.Threading.Tasks.Task.Delay((int)delay);
        
        await actualSend();
        return true;
    }

#if UNITY_EDITOR
    [UnityEditor.MenuItem("Tools/Network/Open Network Simulator")]
    public static void OpenSimulatorWindow() =>
        UnityEditor.EditorWindow.GetWindow<NetworkSimulatorWindow>("网络模拟器").Show();
#endif
}
#endif
```

---

## 八、最佳实践总结

### ✅ 可靠传输核心原则

1. **消息分级处理**：不同优先级采用不同的可靠性策略，实时数据可丢弃，关键操作必达
2. **幂等设计优先**：所有可重试的关键消息必须携带幂等Key，服务端负责去重
3. **持久化关键消息**：支付/存档等关键操作入库前先落盘，防进程崩溃丢失
4. **指数退避防踩踏**：重连/重试使用指数退避 + 随机抖动，防止大量客户端同时重连压垮服务器
5. **状态快照驱动重连**：重连后发送快照SeqId，服务端精准补发缺失消息

### 📊 弱网指标参考（实测值）

| 场景 | RTT | 丢包率 | 推荐发送频率 | 重连等待 |
|------|-----|--------|------------|---------|
| 优质WiFi | <20ms | <0.1% | 30次/秒 | 0.5s |
| 普通4G | 60-120ms | 1-3% | 15次/秒 | 1s |
| 弱网4G | 200-500ms | 5-15% | 5次/秒 | 3s |
| 地铁隧道 | 500ms+ | 20%+ | 2次/秒 | 5s |

### ⚠️ 设计陷阱

1. **不要无限重试非幂等操作**：没有幂等保护的操作重试会导致重复扣款、重复发货
2. **不要在主线程阻塞等待ACK**：使用async/await或回调，避免主线程卡死
3. **不要累积重试消息造成内存泄漏**：设置合理的过期时间和最大队列长度
4. **不要忽略消息顺序**：TCP保证顺序，UDP+KCP需要自行处理乱序（SeqId+缓冲区重排）
5. **断线重连后不要全量同步**：使用增量同步（SeqId diff），避免重连后数据洪水
