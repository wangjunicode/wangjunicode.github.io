---
title: 网络重连机制设计——指数退避策略与Token错误的终止逻辑
published: 2026-03-31
description: 深度解析游戏网络重连组件的设计，包括GCloud长连接断线回调、重试次数上限、延迟重连间隔与Token失效的特殊处理
tags: [Unity, 网络编程, 断线重连]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 网络重连机制设计——指数退避策略与Token错误的终止逻辑

手机游戏中，断线重连是用户体验的关键。用户信号短暂丢失后，游戏应该自动尝试重连，而不是直接弹出"连接失败"让用户手动操作。但重连不是无限重试，需要有退出条件。

VGame项目的`ReconnectorSystem`实现了一套完整的重连策略，本文分析其设计思路。

## 一、重连的三种结局

```csharp
private static void _OnConnected(this Reconnector self, GCloudConnection conn)
{
    // 结局1：连接成功，结束重连流程
    self._EndReconnect((int)ConnectorErrorCode.Success);
}

private static void _OnConnectTimeout(this Reconnector self)
{
    // 结局2：超时，继续尝试重连
    self._DelayReconnect((int)ConnectorErrorCode.InnerError);
}

private static void _OnConnectError(this Reconnector self, 
    GCloudConnection connection, int errorNum, NET_ERROR_TYPE errorType, OperationType operation)
{
    if (NetWorkUtils.IsTokenError((ConnectorErrorCode)errorNum))
    {
        // 结局3：Token失效，直接结束，不再重连
        self._EndReconnect(errorNum);
    }
    else
    {
        // 其他错误，继续尝试重连
        self._DelayReconnect(errorNum);
    }
}
```

**Token错误的特殊处理**：

Token失效（登录凭据过期）是一种特殊情况：重连100次也没用，因为Token已经无效了。必须让玩家重新登录获取新Token。

`NetWorkUtils.IsTokenError`检查是否是Token相关的错误码，是则立刻调用`_EndReconnect`（最终会触发返回登录界面），而不是无意义地重试。

## 二、延迟重连：每次等待1秒

```csharp
private const float RECONNECT_INTERVAL = 1.0f; // 1秒后重试

private static void _DelayReconnect(this Reconnector self, int errorCode)
{
    // 检查是否已达到最大重连次数
    if (self._retrytimes >= self._maxretrytimes)
    {
        Log.Warning(ZString.Concat(
            "[Reconnector] 重连次数已达上限(", self._maxretrytimes, "次)，结束重连"));
        self._EndReconnect((int)ConnectorErrorCode.InnerError);
    }
    else if (!self._isWaiting)
    {
        Debug.Log(ZString.Concat("[Reconnector] 重连", self._connName, "失败，等待 错误码 = ", errorCode));
        
        self._isWaiting = true;
        self._waitingtime = Game.realtimeSinceStartup; // 记录等待开始时间
        
        // 注册Update事件，等待1秒后触发重连
        self.RootDispatcher().RegisterEvent<Evt_UnityUpdate>(self._OnTimeupdate);
    }
}

private static void _OnTimeupdate(this Reconnector self, Evt_UnityUpdate e)
{
    if (Game.realtimeSinceStartup - self._waitingtime > RECONNECT_INTERVAL)
    {
        Log.Info(ZString.Concat("OnTimeUpdate in reconnecting:", 
            Game.realtimeSinceStartup, " _retryTimes", self._retrytimes));
        
        self._isWaiting = false;
        self.RootDispatcher().UnRegisterEvent<Evt_UnityUpdate>(self._OnTimeupdate);
        
        self.Reconnect(); // 发起实际的重连请求
    }
}
```

**用Update事件计时而不是协程**：

为什么用`Evt_UnityUpdate`（每帧事件）+ 时间差判断，而不是`await TimerComponent.Instance.WaitAsync(1000)`？

因为`Reconnector`可能不是MonoBehaviour，不能直接启动协程。同时，`Evt_UnityUpdate`是ET框架的统一Update事件，可以在任何Entity上使用，更通用。

**`!self._isWaiting`的防重入**：

如果`_DelayReconnect`被多次快速调用（比如同时收到多个连接错误回调），`_isWaiting`标志防止重复注册Update事件，避免同时进行多个"等待计时"。

## 三、结束重连的处理

```csharp
public static void _EndReconnect(this Reconnector self, int code)
{
    // 1. 隐藏重连中的Loading界面
    self.HideConnectReconnectingLoading();
    
    if (code != (int)ConnectorErrorCode.Success)
    {
        // 2. 失败：清理回调，弹出错误弹窗让用户手动处理
        if (self._conn != null)
        {
            self._conn.OnConnectedCallback -= self._OnConnected;
            self._conn.OnConnectTimeout -= self._OnConnectTimeout;
            self._conn.OnConnectError -= self._OnConnectError;
        }
        
        // 弹出"断线"弹窗（会有"重试"或"返回登录"按钮）
        self.ShowDisconnectDialog();
    }
    else
    {
        // 3. 成功：执行连接成功回调
        self._callBack?.Invoke((int)ConnectorErrorCode.Success);
        self._callBack = null;
    }
    
    self._retrytimes = 0; // 重置重试计数
}
```

**清理回调的重要性**：

注销`_conn`上的所有事件回调（`OnConnectedCallback`、`OnConnectTimeout`、`OnConnectError`），防止旧的`Reconnector`实例仍然接收新连接的回调。

如果不清理：重连失败后用户手动点了"重试"，新的连接成功了，但旧的Reconnector还在监听，会收到成功回调并执行一些已经不应该执行的逻辑。

## 四、重连中的Loading界面

```csharp
private static readonly int ConnectReconnectingLoadingCode = "ConnectReconnecting".GetHashCode();

public static void ShowConnectReconnectingLoading(this Reconnector self)
{
    var code = ConnectReconnectingLoadingCode;
    // 显示全局Loading（带文字"网络重连中..."）
    UILoadingMgr.Instance.ShowLoading(code, "网络重连中...");
}

public static void HideConnectReconnectingLoading(this Reconnector self)
{
    UILoadingMgr.Instance.HideLoading(ConnectReconnectingLoadingCode);
}
```

重连期间显示一个半透明的Loading遮罩，防止用户误操作，同时给用户反馈"系统正在自动重连"。

**哈希Code作为Loading标识**：`"ConnectReconnecting".GetHashCode()`生成一个固定的整数，用于精确控制这个Loading的显示/隐藏，不影响其他Loading。

## 五、消息队列的批量分发

```csharp
// MessageQueueSystem.cs
public static void AddMessage(this MessageQueue self, uint cmdId, uint serial, object message)
{
    self._msgSize++;
    
    // 对象重用：优先复用已有UnroutedMessage对象
    UnroutedMessage routeMessage = null;
    if (self._messages.Count < self._msgSize)
    {
        self._messages.Add(routeMessage = new UnroutedMessage());
    }
    else
    {
        int index = self._msgSize - 1;
        routeMessage = self._messages[index]; // 复用已有对象
    }
    
    routeMessage.cmdId = cmdId;
    routeMessage.serial = serial;
    routeMessage.message = message;
}

public static void Distribute(this MessageQueue self)
{
    if (self._msgSize > self._msgIndex)
    {
        while (self._msgSize > self._msgIndex)
        {
            UnroutedMessage message = self._messages[self._msgIndex];
            self._msgIndex++;
            
            object msg = message.message;
            message.message = null; // 清空对象（不持有引用，允许GC回收消息对象）
            
            if (self._msgRouter != null)
                self._msgRouter.Route(message.cmdId, message.serial, msg);
        }
        
        self._msgIndex = 0;
        self._msgSize = 0; // 批量分发完成，重置计数
    }
}
```

**`_messages`列表的对象重用**：

`_messages`列表只增不减：第一次收到5条消息，列表有5个UnroutedMessage。分发完后`_msgSize=0`，但列表对象还在。下次收到3条消息，直接复用前3个对象，不创建新的。

这消除了高频消息接收时反复创建/销毁`UnroutedMessage`对象的GC开销。

**`message.message = null`的GC友好处理**：

分发完后将引用置null，允许GC回收消息对象（如Proto消息）。如果不置null，`_messages`列表会持有所有已处理消息的引用，阻止GC。

## 六、敏感词过滤的自动重连

`TextUtils.SensitiveWordFilter`展示了另一种重连模式：

```csharp
public static async ETTask<string> SensitiveWordFilter(string text, bool connectFirst = false)
{
    var connector = SceneUtil.FirstClientScene().GetComponent<ConnectorComponent>();
    if (!connector.IsConnected())
        connectFirst = true; // 未连接时强制先连接
    
    if (connectFirst)
    {
        await ReConnect(null); // 先重连
        if (!connector.IsConnected())
            return null; // 重连失败，返回null（上层决定如何处理）
    }
    
    // ... 发送敏感词过滤请求
    
    if (!nr.IsCompleteSuccess)
    {
        if (connectFirst && connector.IsConnected())
            text = nr.Data.FilterText;
        else
            text = await SensitiveWordFilter(text, true); // 递归重试（最多一次）
    }
    
    return text;
}
```

**递归重试**：第一次失败时，`connectFirst=true`递归调用自身，尝试重连后再次发送请求。但只递归一次（第二次`connectFirst=true`且`IsConnected()`失败才彻底放弃），避免无限递归。

## 七、总结

重连机制的设计展示了：

1. **错误分类**：Token错误立刻停止（无意义重试），其他错误继续重试
2. **等待间隔**：1秒间隔避免频繁无效重连
3. **重连上限**：最大重试次数防止无限等待
4. **Loading反馈**：重连期间显示Loading，防止误操作
5. **回调清理**：结束时注销所有回调，防止状态泄露
6. **消息队列复用**：UnroutedMessage对象池消除GC压力

对新手来说，网络重连设计的核心思路：**把"连接状态"和"业务逻辑"分离**——Reconnector只管重连，不管重连成功后要做什么（那是回调的工作），职责单一，代码清晰。
