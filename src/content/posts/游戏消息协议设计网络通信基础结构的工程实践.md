---
title: 游戏消息协议设计：网络通信基础结构的工程实践
published: 2026-03-31
description: 解析游戏网络消息基类的设计原则，理解消息 ID 分配、协议版本管理和序列化格式选择对游戏网络架构的影响。
tags: [Unity, 网络编程, 消息协议, 游戏架构]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 游戏网络消息的核心需求

游戏客户端和服务器之间需要通过网络传递大量消息：

- **登录认证**：用户名密码 → 认证令牌
- **角色同步**：移动位置、攻击指令、技能释放
- **游戏状态**：血量变化、道具掉落、场景加载
- **聊天系统**：文字、表情、语音

这些消息需要一套统一的**消息协议**来管理，类似于 HTTP 的请求/响应模型，但针对实时游戏优化。

---

## 消息基类设计原则

### 最小化基类

```csharp
// 所有消息的基类
public abstract class AMessage
{
    // 消息 ID（唯一标识消息类型）
    public abstract int MessageId { get; }
    
    // 时间戳（服务器时间，用于排序和超时检测）
    public long Timestamp;
}

// 请求消息基类（客户端 → 服务器）
public abstract class ARequest : AMessage
{
    public long RequestId;    // 请求唯一 ID，用于匹配响应
    public string SessionId;  // 会话 ID
}

// 响应消息基类（服务器 → 客户端）
public abstract class AResponse : AMessage
{
    public long RequestId;   // 对应请求的 ID
    public int ErrorCode;    // 0 = 成功，其他值 = 错误码
    public string ErrorMsg;  // 错误信息
}

// 通知消息基类（服务器 → 客户端，无需响应）
public abstract class ANotify : AMessage { }
```

### 消息 ID 分配策略

```csharp
// 枚举方式：类型安全，但扩展麻烦
public enum MessageIds
{
    LoginRequest    = 1001,
    LoginResponse   = 1002,
    MoveRequest     = 2001,
    AttackRequest   = 2002,
}

// 常量方式：更灵活
public static class MessageIds
{
    // 账号系统：1000 ~ 1999
    public const int LoginRequest   = 1001;
    public const int LoginResponse  = 1002;
    
    // 战斗系统：2000 ~ 2999
    public const int MoveRequest    = 2001;
    public const int AttackRequest  = 2002;
    public const int DamageNotify   = 2003;
    
    // 聊天系统：3000 ~ 3999
    public const int ChatSend       = 3001;
    public const int ChatReceive    = 3002;
}
```

分范围分配 ID 的好处：
- 一眼看出消息属于哪个系统
- 各系统可以独立扩展 ID，不冲突
- 调试时看到消息 ID 就能定位到系统

---

## 具体消息定义示例

```csharp
// 登录请求
[MemoryPackable]
public partial class LoginRequest : ARequest
{
    public override int MessageId => MessageIds.LoginRequest;
    
    public string Username;
    public string PasswordHash;  // 客户端做一次 MD5，不发明文密码
    public string DeviceId;      // 设备指纹（防多开检测）
    public string Version;       // 客户端版本号
}

// 登录响应
[MemoryPackable]
public partial class LoginResponse : AResponse
{
    public override int MessageId => MessageIds.LoginResponse;
    
    public long UserId;
    public string Token;
    public string NickName;
    public int VipLevel;
    public long LastLoginTime;
}

// 位置同步通知（服务器广播）
[MemoryPackable]
public partial class PositionNotify : ANotify
{
    public override int MessageId => MessageIds.PositionNotify;
    
    public long EntityId;
    public FixedPoint X;  // 定点数，帧同步用
    public FixedPoint Y;
    public FixedPoint Z;
    public int Frame;     // 帧号
}
```

---

## 请求-响应的异步封装

```csharp
// 网络组件：发送请求并等待响应
public class NetworkComponent : Entity
{
    private Dictionary<long, ETTask<AResponse>> _pendingRequests = new();
    private long _requestIdCounter = 0;
    
    public async ETTask<TResponse> SendRequestAsync<TResponse>(ARequest request)
        where TResponse : AResponse
    {
        request.RequestId = ++_requestIdCounter;
        
        // 注册等待
        var tcs = ETTask<AResponse>.Create(true);
        _pendingRequests[request.RequestId] = tcs;
        
        // 发送
        SendBytes(Serialize(request));
        
        // 等待响应（带超时）
        using var cancelToken = new ETCancellationToken();
        var timeoutTask = TimerComponent.Instance.WaitAsync(5000, cancelToken);
        var responseTask = tcs;
        
        await ETTaskHelper.WaitAny(new ETTask[] { timeoutTask, (ETTask)responseTask });
        cancelToken.Cancel();
        
        if (timeoutTask.IsCompleted)
        {
            _pendingRequests.Remove(request.RequestId);
            throw new TimeoutException($"Request {request.MessageId} timeout");
        }
        
        return responseTask.GetResult() as TResponse;
    }
    
    // 收到服务器消息时调用
    public void OnReceiveMessage(AMessage msg)
    {
        if (msg is AResponse response)
        {
            if (_pendingRequests.TryGetValue(response.RequestId, out var tcs))
            {
                _pendingRequests.Remove(response.RequestId);
                tcs.SetResult(response);
            }
        }
    }
}

// 使用
var response = await networkComp.SendRequestAsync<LoginResponse>(new LoginRequest
{
    Username = "player1",
    PasswordHash = MD5("password123")
});

if (response.ErrorCode == 0)
{
    Debug.Log($"登录成功！用户：{response.NickName}");
}
```

---

## 协议版本管理

```csharp
public class AMessage
{
    // 协议版本，用于兼容性检查
    public static readonly string ProtocolVersion = "1.2.0";
    
    // 服务器检查版本
    public bool IsVersionCompatible(string serverVersion)
    {
        var client = Version.Parse(ProtocolVersion);
        var server = Version.Parse(serverVersion);
        
        // 主版本号必须一致，次版本号服务端可以更高
        return client.Major == server.Major && client.Minor <= server.Minor;
    }
}
```

---

## 总结

网络消息基类设计的核心原则：

| 原则 | 实践 |
|------|------|
| 最小化基类 | 只放所有消息共有的字段 |
| ID 分区管理 | 按系统划分 ID 范围 |
| 请求/响应分离 | ARequest 和 AResponse 各自扩展 |
| 版本管理 | 明确的版本号字段 |
| 序列化友好 | MemoryPackable 特性标记 |

设计好消息协议，是后续网络功能开发的基础。一个清晰的协议设计可以让客户端、服务器和 QA 团队的沟通成本大幅降低。
