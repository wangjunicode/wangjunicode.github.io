---
title: 网络消息系统：Protobuf协议与消息分发
published: 2024-01-01
description: "网络消息系统：Protobuf协议与消息分发 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 配置与数据
draft: false
---

# 网络消息系统：Protobuf协议与消息分发

## 1. 系统概述

本项目网络层基于腾讯 **GCloud SDK** 封装，底层使用 TCP 长连接，协议格式采用 **Protobuf**（Google Protocol Buffers）。消息分发通过**反射+特性注解**自动注册，开发者只需添加 `[MessageHandler]` 标注类即可处理对应协议。

**核心组件：**
- `ConnectorComponent`：管理 TCP 连接生命周期（连接/断开/重连）
- `ZoneSession`：代表一个与游戏服（Zone Server）的会话，含心跳/重连逻辑
- `NetworkComponent`：单例，保存账号信息、连接状态等全局网络状态
- `MessageDispatcher`：消息分发中心，基于反射自动发现所有 `IMHandler` 处理器
- `MessageRouter`：消息路由，根据协议 ID 找到对应 Handler 并调度

---

## 2. ZoneSession 会话管理

```csharp
// 位置：Hotfix/Model/GamePlay/Network/ZoneSession.cs
// 游戏服会话（一个玩家对应一个 ZoneSession）
public class ZoneSession : Entity, IAwake
{
    public NetworkComponent networkManager;  // 全局网络管理器引用
    public GCloudConnection zoneConn;        // GCloud 底层连接对象
    
    // 心跳管理
    private float _BeatInterval = 60.0f;     // 心跳间隔（秒）
    private float _lastBeatTime = 0;
    private ZoneHeartBeatReq _beatReq;       // 心跳协议包（复用，避免 GC）
    
    public bool isLogin 
    { 
        get => _islogin;
        set
        {
            _islogin = value;
            if (value)
            {
                // 登录成功后立即发一次心跳（确保连接活跃）
                _lastBeatTime = Game.realtimeSinceStartup - _BeatInterval;
            }
        }
    }
    
    // 心跳包（懒加载 + 复用，避免每次 new）
    public ZoneHeartBeatReq beatReq
    {
        get
        {
            if (_beatReq == null)
            {
                _beatReq = new ZoneHeartBeatReq
                {
                    ClientVersion = new ClientVersionMsg
                    {
                        AppVersion = VersionUtil.toSimpleVersion(Application.version),
                        ResVersion = VersionUtil.toSimpleVersion(VersionManager.Instance.ResVersion),
                        ApkVersion = VersionUtil.toSimpleVersion(VersionPath.ApkVersion)
                    }
                };
            }
            return _beatReq;
        }
    }
}
```

---

## 3. 消息分发系统（MessageDispatcher）

### 3.1 设计思路

```
启动时（Awake）
    → 扫描所有带 [MessageHandler] 特性的类
    → 创建 IMHandler 实例
    → 注册到 messageHandlers 字典（消息类型 → Handler 列表）

收到服务器推送时
    → MessageDispatcher.Handle(entity, msg)
    → 根据 msg.GetType() 找到 Handler 列表
    → 按 SceneType 过滤（只处理当前 Scene 类型匹配的 Handler）
    → 逐一调用 IMHandler.Handle(entity, msg)
```

### 3.2 核心实现

```csharp
// 位置：Hotfix/Model/GamePlay/Network/Notify/MessageDispatcher.cs
public class MessageDispatcher : Singleton<MessageDispatcher>, ISingletonAwake
{
    // 消息类型 → Handler 列表（一种消息可以有多个 Handler）
    private readonly Dictionary<Type, List<MessageDispatcherInfo>> messageHandlers = new();
    
    // 启动时自动发现所有 Handler
    public void Awake()
    {
        // 通过 EventSystem 扫描所有带 [MessageHandlerAttribute] 的类型
        HashSet<Type> types = EventSystem.Instance.GetTypes(typeof(MessageHandlerAttribute));
        
        foreach (Type type in types)
        {
            Register(type);
        }
    }
    
    private void Register(Type type)
    {
        // 创建 Handler 实例
        IMHandler imHandler = Activator.CreateInstance(type) as IMHandler;
        if (imHandler == null)
            throw new Exception($"消息处理器未实现 IMHandler: {type.FullName}");
        
        // 读取 [MessageHandler] 特性（可能有多个，如同时处理 Client 和 Server 场景）
        object[] attrs = type.GetCustomAttributes(typeof(MessageHandlerAttribute), true);
        foreach (object attr in attrs)
        {
            var msgAttr = (MessageHandlerAttribute)attr;
            Type messageType = imHandler.GetRequestType();  // Handler 处理的消息类型
            
            RegisterHandler(messageType, new MessageDispatcherInfo(msgAttr.SceneType, imHandler));
        }
    }
    
    // 分发消息（收到服务器推送时调用）
    public async ETTask Handle(Entity entity, IMsg msg)
    {
        if (!messageHandlers.TryGetValue(msg.GetType(), out var list))
        {
            Log.Warning($"[MessageDispatcher] 收到未注册消息: {msg.GetType()}");
            return;
        }
        
        SceneType sceneType = entity.Root().SceneType;
        foreach (var info in list)
        {
            // 检查场景类型是否匹配（比如登录 Handler 只在 Client 场景处理）
            if (!info.SceneType.HasSameFlag(sceneType)) continue;
            
            await info.IMHandler.Handle(entity, msg);
        }
    }
}
```

---

## 4. 编写自定义消息处理器

```csharp
// 步骤一：定义 Handler 类，继承 AMHandler 基类（或 IMHandler 接口）
// 步骤二：添加 [MessageHandler] 特性，指定 SceneType
// 步骤三：实现 Run 方法（async ETTask）

[MessageHandler(SceneType.Client)]
public class ZoneMail_ListNotifyHandler : AMHandler<ZoneMailListNotify>
{
    // 收到服务器推送"邮件列表更新"消息时自动触发
    protected override async ETTask Run(Entity entity, ZoneMailListNotify args)
    {
        // entity 是挂载 NetworkComponent 的 Scene
        var zoneSession = entity.Root().GetComponent<ZoneSession>();
        
        // 处理邮件列表
        await MailSystemHelper.SyncMailList(zoneSession, args);
        
        // 发布 UI 更新事件
        EventSystem.Instance.Publish(entity.Root(), new Evt_MailListUpdated());
    }
}

// 服务器推送入侵告警通知
[MessageHandler(SceneType.Client)]
public class ZoneSvrInformNotifyHandler : AMHandler<ZoneSvrInformNotify>
{
    protected override async ETTask Run(Entity entity, ZoneSvrInformNotify args)
    {
        switch (args.InformType)
        {
            case SvrInformType.Kick:
                // 被踢下线（账号在其他设备登录）
                await UIHelper.ShowAlertAsync("账号在其他设备登录，请重新登录");
                SDKUtil.LogoutGame(false);
                break;
            case SvrInformType.Maintenance:
                // 服务器维护公告
                await UIHelper.ShowAlertAsync(args.Message);
                break;
        }
    }
}
```

---

## 5. Request-Response 模式

```csharp
// 网络请求使用 async/await，底层通过序列号匹配请求和响应
public static class NetworkExtension
{
    // 发送请求并等待响应（泛型版本）
    public static async ETTask<NetworkResult<TResp>> SendAsync<TResp>(
        this ZoneSession self, uint cmdId, IMessage req,
        NetworkErrorHandle errorHandle = null,
        NetworkReceiveErrorHandle receiveErrorHandle = null)
        where TResp : IMessage, new()
    {
        // 生成序列号（递增，用于匹配响应）
        uint serial = self.GetNextSerial();
        
        // 序列化 Protobuf 消息
        var head = new ClientHead { CmdId = cmdId, Serial = serial };
        byte[] data = ProtoHelper.Serialize(req);
        
        // 创建 TaskCompletionSource，等待服务器响应
        var tcs = ETTask<NetworkResult<TResp>>.Create(fromPool: true);
        self.RegisterPendingRequest(serial, tcs);
        
        // 发送
        self.zoneConn.SendMessage(head, data);
        
        // await 等待响应（内部设置超时，超时触发 receiveErrorHandle）
        return await tcs;
    }
}
```

---

## 6. Protobuf 协议约定

```protobuf
// 协议文件约定（以登录为例）
// 文件：vcm_protocol/zone_login.proto

message ZoneLoginReq {
    ClientVersionMsg client_version = 1;   // 版本信息
    ClientPayMsg pay_msg = 2;              // 支付 Token
    int32 login_type = 3;                  // 登录类型（qq/wx/guest）
    int32 client_type = 4;                 // 客户端类型（android/ios/pc）
    string reg_name = 5;                   // 注册昵称（首次登录时）
    int32 gender = 6;                      // 性别
    OssInfo oss_msg = 7;                   // CDN 配置
    uint64 login_uniq_id = 8;             // 登录唯一 ID（断线重连用）
}

message ZoneLoginResp {
    int32 err_code = 1;                    // 错误码（0=成功）
    string err_msg = 2;                    // 错误描述
    ZoneRoleInfo role_info = 3;            // 玩家角色数据（背包/角色/剧情等）
    ServerConf server_conf = 4;            // 服务器配置（心跳间隔/超时时间等）
}
```

---

## 7. 常见问题与最佳实践

**Q: 消息分发用反射注册，启动时会很慢吗？**  
A: 只在 `MessageDispatcher.Awake()` 时扫描一次，运行时查字典是 O(1)。通过 `EventSystem.GetTypes()` 缓存类型列表，避免重复反射。

**Q: 同一条消息可以有多个处理器吗？**  
A: 可以。`messageHandlers[msgType]` 是 `List<MessageDispatcherInfo>`，所有匹配 SceneType 的 Handler 都会顺序执行（await 串行）。

**Q: 断网重连后，pending 的请求（已发送未收到响应）怎么处理？**  
A: 重连后所有 pending 请求的 TCS（TaskCompletionSource）会被 `Reconnector` 统一触发超时错误（`NetworkResult.ErrorCode = Timeout`），业务层在 `receiveErrorHandle` 中处理（通常显示"网络超时，请重试"）。
