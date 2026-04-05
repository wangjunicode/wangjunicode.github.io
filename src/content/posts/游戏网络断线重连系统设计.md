---
title: 游戏网络断线重连系统设计
published: 2026-03-31
description: 从重连状态机到 Loading 显示管理，全面解析游戏客户端断线重连系统的设计，包含指数退避策略、Token 失效处理与重连失败降级方案。
tags: [Unity, 网络系统, 断线重连, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏网络断线重连系统设计

## 前言

网络游戏中，断线是不可避免的——手机信号弱、切换 WiFi、手机息屏……玩家期望游戏能自动重连，而不是直接踢回登录界面。

一套优秀的重连系统需要：在后台静默重试、显示清晰的进度提示、超时后优雅降级、区分"网络故障"和"认证失效"两种场景。本文通过 `ReconnectorSystem` 的分析，带你理解重连系统的完整设计。

---

## 一、重连系统的状态机

重连过程是一个典型的状态机：

```
待机
  │
  ├─[网络断开]
  ↓
重连中（Reconnecting）
  │
  ├─[连接成功] → 恢复游戏 → 待机
  │
  ├─[连接失败 & 未超最大次数] → 等待 1 秒 → 重连中
  │
  ├─[Token 失效] → 结束重连（显示"请重新登录"弹窗）
  │
  └─[超过最大次数] → 结束重连（显示"连接失败"弹窗）
```

---

## 二、重连的启动

```csharp
public static void StartReconnect(this Reconnector self,
    GCloudConnection conn,
    Action<int> callback,
    bool showTip = true)
{
    // 清除旧的连接监听（防止重复注册）
    if (self._conn != null)
    {
        self._conn.OnConnectedCallback -= self._OnConnected;
        self._conn.OnConnectTimeout   -= self._OnConnectTimeout;
        self._conn.OnErrorCallback    -= self._OnConnectError;
        self._conn = null;
    }

    // 注册新连接的回调
    self._conn = conn;
    self._conn.OnConnectedCallback += self._OnConnected;
    self._conn.OnConnectTimeout   += self._OnConnectTimeout;
    self._conn.OnErrorCallback    += self._OnConnectError;

    // 初始化重连状态
    self._callBack       = callback;    // 重连结束后的回调（成功或失败）
    self._retrytimes     = 0;           // 重置重试计数
    self._reconnStartTime = Game.realtimeSinceStartup;

    if (showTip)
        self.ShowConnectReconnectingLoading();

    self.Reconnect(); // 立刻发起第一次重连
}
```

**关键细节：先清除旧监听**

```csharp
self._conn.OnConnectedCallback -= self._OnConnected;
```

这行代码防止了一个常见 Bug：如果不清除旧监听，重连时旧的回调和新的回调都会触发，导致回调执行两次。这是 C# 事件处理中的经典陷阱。

---

## 三、错误分类处理

```csharp
private static void _OnConnectError(this Reconnector self,
    GCloudConnection connection, int errorNum,
    NET_ERROR_TYPE errorType, OperationType operation)
{
    if (NetWorkUtils.IsTokenError((ConnectorErrorCode)errorNum))
    {
        // Token 失效：立刻结束重连，不再重试
        self._EndReconnect(errorNum);
    }
    else
    {
        // 网络错误：延迟后重试
        self._DelayReconnect(errorNum);
    }
}
```

**为什么要区分 Token 错误？**

| 错误类型 | 原因 | 处理策略 |
|---------|------|---------|
| 网络错误 | 信号差、路由抖动 | 等待后重试，通常能恢复 |
| Token 失效 | 账号在别处登录、Session 过期 | 不能重试，必须重新登录 |

对 Token 失效继续重试是无意义的——服务端会拒绝所有请求，无论重试多少次。立刻结束并提示玩家重新登录，是正确的用户体验。

---

## 四、延迟重试机制

```csharp
private static void _DelayReconnect(this Reconnector self, int errorCode)
{
    if (self._retrytimes >= self._maxretrytimes)
    {
        // 超过最大重试次数，放弃
        Log.Warning($"[Reconnector] 重连次数已达上限({self._maxretrytimes}次)，结束重连");
        self._EndReconnect((int)ConnectorErrorCode.InnerError);
        return;
    }

    if (!self._isWaiting)
    {
        self._isWaiting    = true;
        self._waitingtime  = Game.realtimeSinceStartup;
        // 注册到每帧更新，等待 1 秒后再重试
        self.RootDispatcher().RegisterEvent<Evt_UnityUpdate>(self._OnTimeupdate);
    }
}

private const float RECONNECT_INTERVAL = 1.0f;  // 重连间隔：1 秒

private static void _OnTimeupdate(this Reconnector self, Evt_UnityUpdate e)
{
    if (Game.realtimeSinceStartup - self._waitingtime > RECONNECT_INTERVAL)
    {
        self._isWaiting = false;
        // 注销帧更新监听
        self.RootDispatcher().UnRegisterEvent<Evt_UnityUpdate>(self._OnTimeupdate);
        self.Reconnect(); // 再次尝试
    }
}
```

**设计亮点：利用事件系统实现非阻塞等待**

重连等待不使用 `Thread.Sleep` 或协程，而是注册帧更新事件，在满足等待时间后自动触发。这样做的好处：

1. 等待期间游戏主线程不被阻塞
2. 可以随时取消（注销事件即可）
3. 与游戏的 ECS 事件系统统一

**`_isWaiting` 的防重复设计：**

`if (!self._isWaiting)` 确保不会重复注册帧更新监听。如果没有这个检查，快速的多次失败回调可能导致注册多个监听，每隔 1 秒触发多次重连。

---

## 五、重连成功的处理

```csharp
private static void _OnConnected(this Reconnector self, GCloudConnection conn)
{
    self._EndReconnect((int)ConnectorErrorCode.Success);
}

public static void _EndReconnect(this Reconnector self, int code)
{
    self.HideConnectReconnectingLoading();

    if (code != (int)ConnectorErrorCode.Success)
    {
        // 失败处理：清理回调，显示弹窗
        // ...
        self.ShowReconnectFailedPopup();
    }
    else
    {
        // 成功处理：执行回调
        var callback = self._callBack;
        self.StopReconnect();    // 先清理状态
        if (callback != null)
            callback(code);      // 再执行回调（避免清理过程中触发副作用）
    }
}
```

**先清理后回调的重要性：**

```csharp
var callback = self._callBack;
self.StopReconnect();   // 先清理，_callBack 置空
callback(code);          // 再执行已暂存的回调
```

如果顺序反过来（先执行回调再清理），回调中的代码可能再次触发重连相关逻辑，与正在进行的清理操作产生冲突。这是"先保存状态，再执行副作用"的防御性编程技巧。

---

## 六、重连 Loading 的唯一性管理

```csharp
private static readonly int ConnectReconnectingLoadingCode =
    "ConnectReconnecting".GetHashCode();

private static void ShowConnectReconnectingLoading(this Reconnector self)
{
    if (self._connectReconnectingLoadingCode == -1)
    {
        self._connectReconnectingLoadingCode = ConnectReconnectingLoadingCode;
        EventSystem.Publish(new Evt_ShowMiniLoading
        {
            Code     = self._connectReconnectingLoadingCode,
            Content  = "重新连接中...",
            ShowLoad = true
        });
    }
}

public static void HideConnectReconnectingLoading(this Reconnector self)
{
    if (self._connectReconnectingLoadingCode != -1)
    {
        EventSystem.Publish(new Evt_HideMiniLoading
        {
            Code = self._connectReconnectingLoadingCode
        });
        self._connectReconnectingLoadingCode = -1;
    }
}
```

与网络请求 Loading 系统一样，重连 Loading 通过 Code 唯一标识，通过 `-1` 哨兵值追踪是否已显示。两套 Loading 相互独立，不会互相干扰（详见之前关于 `MessageRouterSystem` 的文章）。

---

## 七、超时判断与最大重试次数

```csharp
// 方案一：基于最大次数
private static void _DelayReconnect(this Reconnector self, int errorCode)
{
    if (self._retrytimes >= self._maxretrytimes)
    {
        self._EndReconnect((int)ConnectorErrorCode.InnerError);
    }
}

// 方案二（注释中提到）：基于时间
// "每3秒重试连接，如果60秒后还连不上则弹窗返回登录"
```

项目同时维护两套超时判断逻辑的注释，说明这个参数经历了调整。最终选择"最大次数"而非"时间"作为主控制，可能是因为次数更直观，便于策划和运营调整（`_maxretrytimes = 20` 比 `timeout = 60s` 更易理解）。

---

## 八、重连失败的降级方案

```csharp
private static void ShowReconnectFailedPopup(this Reconnector self)
{
    EventSystem.Publish(new Evt_ShowMessageBox
    {
        Title   = "连接失败",
        Content = "网络连接出现问题，请检查网络后重试",
        Confirm = "返回登录",
        OnConfirm = () => {
            EventSystem.Publish(new Evt_LogoutGame());
        }
    });
}
```

重连彻底失败时的降级是"返回登录界面"。这是最保守的安全策略：
- 不尝试继续游戏（数据可能已不一致）
- 明确告知用户发生了什么
- 给用户主动权（确认按钮）

---

## 九、完整重连流程时序

```
T=0    网络断开
       StartReconnect() → 注册回调 → Reconnect()

T=0s   第1次连接尝试 → 失败
       _retrytimes++ = 1
       等待 1s

T=1s   第2次连接尝试 → 失败
       _retrytimes++ = 2
       等待 1s
       ...

T=15s  第16次连接尝试 → 失败
       _retrytimes++ = 16

T=16s  第17次连接尝试 → 成功
       _EndReconnect(Success)
       HideLoading
       callback(Success) → 恢复战斗 / 返回主城
```

---

## 十、总结

| 设计要素 | 具体实现 |
|---------|---------|
| 错误分类 | Token 错误立刻放弃，网络错误延迟重试 |
| 非阻塞等待 | 事件系统定时触发，不阻塞主线程 |
| 防重复注册 | `_isWaiting` 标志保证监听只注册一次 |
| 先清理后回调 | 保存回调引用 → 清理状态 → 执行回调 |
| Loading 唯一性 | Code + 哨兵值管理显示/隐藏 |
| 降级策略 | 放弃重连后返回登录界面 |

对于刚入行的同学，重连系统是理解"网络容错"的最佳入口。建议自己实现一个简化版本：只有"成功/失败"两种回调 + 固定间隔重试 + 最大次数限制。在这个基础上再逐步加入 Token 检测、Loading 管理等细节。
