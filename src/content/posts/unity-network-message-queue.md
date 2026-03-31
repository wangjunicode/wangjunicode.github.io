---
title: 客户端网络消息队列与路由系统设计
published: 2026-03-31
description: 深入解析游戏客户端网络消息队列的两阶段处理机制、消息路由调度与网络请求 Loading 状态的智能管理，带你理解如何构建稳健的网络通信层。
tags: [Unity, 网络系统, 消息队列, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 客户端网络消息队列与路由系统设计

## 前言

网络游戏的客户端每秒要处理来自服务端的数十条消息：玩家移动同步、技能结果、道具更新……如果直接在网络回调里处理这些消息，很容易引发线程安全问题。与此同时，网络请求等待时需要向玩家展示 Loading 提示，但又不能一有请求就立刻弹出（会导致界面频繁闪烁）。

本文通过分析 `MessageQueueSystem` 和 `MessageRouterSystem`，带你理解这些问题是如何被优雅解决的。

---

## 一、两阶段处理：先入队，后分发

网络消息处理分两个明确的阶段：

```
阶段1（网络线程）：消息到达 → AddMessage() → 存入队列
阶段2（主线程）：  每帧 Update → Distribute() → 逐条处理
```

这个设计的核心价值：**把跨线程的消息"转移"到主线程处理，避免并发问题**。

### 1.1 消息队列的对象池实现

```csharp
public static void AddMessage(this MessageQueue self, uint cmdId, uint serial, object message)
{
    self._msgSize++;  // 待处理消息计数

    UnroutedMessage routeMessage = null;

    if (self._messages.Count < self._msgSize)
    {
        // 列表容量不足，新建
        self._messages.Add(routeMessage = new UnroutedMessage());
    }
    else
    {
        // 复用已有槽位（列表容量充足）
        int index = self._msgSize - 1;
        routeMessage = self._messages[index];
    }

    routeMessage.cmdId  = cmdId;
    routeMessage.serial = serial;
    routeMessage.message = message;
}
```

**内嵌的对象池设计：**

`_messages` 是一个持续增长的 `List`，但从不收缩。新消息优先复用列表中已有的槽位（通过 `_msgSize` 追踪），只有在容量不足时才 `Add` 扩容。

这样既避免了每条消息 `new` 一个对象的 GC 压力，也不需要显式的 `Return` 操作——每次 `Distribute` 后重置 `_msgIndex` 和 `_msgSize` 相当于一次性"清空"，下次消息到来时从头覆写。

```
AddMessage(A) → _messages[0] = A, _msgSize=1
AddMessage(B) → _messages[1] = B, _msgSize=2
Distribute()  → 处理 [0][1], 重置 _msgIndex=0, _msgSize=0
AddMessage(C) → _messages[0] = C（复用！）, _msgSize=1
```

### 1.2 主线程分发

```csharp
public static void Distribute(this MessageQueue self)
{
    if (self._msgSize > self._msgIndex)
    {
        while (self._msgSize > self._msgIndex)
        {
            UnroutedMessage message = self._messages[self._msgIndex];
            self._msgIndex++;

            object msg = message.message;
            message.message = null;  // 清空引用，防止内存泄漏

            if (self._msgRouter != null)
            {
                self._msgRouter.Route(message.cmdId, message.serial, msg);
            }
        }

        self._msgIndex = 0;
        self._msgSize  = 0;
    }
}
```

`message.message = null` 这行看似不起眼，却非常重要：清空对消息对象的引用，让 GC 能够回收消息对象，防止队列持续持有已处理消息的引用造成内存泄漏。

---

## 二、消息路由系统

路由系统（`MessageRouter`）负责把消息分发给对应的处理器。这是"消息总线"设计模式的典型实现：

```
MessageRouter.Route(cmdId, serial, msg)
    ↓
查找注册的 Handler（按 cmdId）
    ↓
调用 Handler 处理消息
    ↓
触发等待该消息的异步回调（如果有）
```

### 2.1 序列号管理

```csharp
public static uint NextSerial(this MessageRouter self, uint cmdID)
{
    uint cmdserial = 0;
    CmdCacheInfo info = null;
    self.cmdSerialCache.TryGetValue(cmdID, out info);

    if (info != null && info.serial != 0)
    {
        cmdserial = info.serial;
    }
    return cmdserial;
}
```

序列号（Serial）用于匹配请求与响应——发送一条消息时生成序列号，服务端在响应中带回同一序列号，客户端用它找到对应的等待回调。

这是请求-响应模式在 UDP/TCP 网络中的经典实现，解决了消息乱序的问题：即使服务端响应乱序到达，也能通过序列号正确匹配。

---

## 三、网络请求 Loading 的智能显示

这部分是代码中最精妙的设计之一——"延迟 0.5 秒才显示 Loading"。

### 3.1 为什么要延迟？

如果每个网络请求都立刻显示 Loading，会导致：
- 快速完成的请求（<0.5s）会闪烁一下 Loading 就消失，视觉体验差
- 高频操作（如频繁点击）会不停地弹出/消失 Loading

解决方案：**只有当一个请求等待超过 0.5 秒时，才显示 Loading**。

### 3.2 实现机制

```csharp
private const float NetworkRequestLoadingDelaySeconds = 0.5f;

public static void OnNetworkRequestLoadingCheck(this MessageRouter self)
{
    // 有弹窗就不显示 loading（弹窗本身已经是用户反馈）
    if (self.networkComp != null && self.networkComp.IsPopNetError)
        return;

    // 正在网络重连时，不显示协议层的 loading（避免两个 loading 叠加）
    var zoneSession = self.networkComp.Root().GetComponent<ZoneSession>();
    if (zoneSession != null && zoneSession.IsConnectReconnecting())
    {
        if (self.networkRequestLoadingCode != -1)
            self.HideNetworkRequestLoading();
        return;
    }

    // 没有任何需要显示 loading 的请求
    if (!self.TryGetOldestDisplayTipStartTime(out var oldestStartTime))
    {
        if (self.networkRequestLoadingCode != -1)
            self.HideNetworkRequestLoading();
        return;
    }

    // Loading 已在显示，保持
    if (self.networkRequestLoadingCode != -1)
        return;

    // 超过阈值才显示
    float now = Game.realtimeSinceStartup;
    if (now - oldestStartTime >= NetworkRequestLoadingDelaySeconds)
        self.ShowNetworkRequestLoading();
}
```

### 3.3 最早等待时间的计算

```csharp
private static bool TryGetOldestDisplayTipStartTime(this MessageRouter self, out float oldestStartTime)
{
    oldestStartTime = 0f;
    bool has = false;
    foreach (var arg in self.argDicts.Values)
    {
        if (!arg.displayTip) continue;  // 只考虑标记了 displayTip 的请求

        if (!has || arg.starttime < oldestStartTime)
        {
            oldestStartTime = arg.starttime;
            has = true;
        }
    }
    return has;
}
```

当有多个并发请求时，取**最早发出的那个请求的开始时间**作为延迟计算的基准。这保证了只要任何一个慢请求超时，Loading 就会出现，而不需要所有请求都慢。

### 3.4 Loading 的唯一性控制

```csharp
private static readonly int NetworkRequestLoadingCode = "NetworkRequestLoading".GetHashCode();

private static void ShowNetworkRequestLoading(this MessageRouter self)
{
    if (self.networkRequestLoadingCode == -1)  // -1 表示当前没有 Loading 显示
    {
        self.networkRequestLoadingCode = NetworkRequestLoadingCode;
        EventSystem.Instance.Publish(self.ClientScene(), new Evt_ShowMiniLoading
        {
            Code = self.networkRequestLoadingCode,
            ShowMask = true,
            Content = "网络连接中...",
            ShowLoad = true
        });
    }
}

public static void HideNetworkRequestLoading(this MessageRouter self)
{
    if (self.networkRequestLoadingCode != -1)
    {
        EventSystem.Instance.Publish(self.ClientScene(),
            new Evt_HideMiniLoading { Code = self.networkRequestLoadingCode });
        self.networkRequestLoadingCode = -1;
    }
}
```

通过 `Code`（一个 int 值）来标识 Loading 的唯一实例，确保同一个 Loading 不会被重复创建，也不会在隐藏后用旧 Code 再次尝试隐藏。

`networkRequestLoadingCode = -1` 是"无效状态"的哨兵值，检查 `-1` 就能知道当前 Loading 的显示状态。

---

## 四、displayTip 标志：精细控制哪些请求显示 Loading

不是所有网络请求都需要 Loading 提示。`displayTip` 字段让调用方自己决定：

```csharp
// 示例：发送一个需要 Loading 的请求
router.SendRequest(msgId, data, displayTip: true);   // 会触发 Loading 逻辑

// 后台请求（如心跳、数据同步），不需要 Loading
router.SendRequest(msgId, data, displayTip: false);  // 不触发 Loading
```

这样的细粒度控制避免了后台请求（如定时心跳包）频繁触发 Loading，保持界面干净。

---

## 五、互斥设计：弹窗与 Loading 不共存

```csharp
if (self.networkComp != null && self.networkComp.IsPopNetError)
    return;
```

当网络错误弹窗出现时，Loading 自动隐藏（或不显示）。这是 UI 优先级管理的体现：**弹窗比 Loading 更重要，两者不应同时出现**。

类似地：

```csharp
if (zoneSession.IsConnectReconnecting())
{
    if (self.networkRequestLoadingCode != -1)
        self.HideNetworkRequestLoading();
    return;
}
```

正在重连时，由重连系统自己显示重连 Loading，不需要协议层的 Loading 叠加。

---

## 六、完整的请求-响应生命周期

```
发送请求
  → 生成序列号（NextSerial）
  → 记录到 argDicts（包含 starttime、displayTip 等）
  → 发送给服务端

每帧 Update
  → Distribute() 分发收到的消息
  → OnNetworkRequestLoadingCheck() 检查是否需要显示 Loading

收到响应
  → MessageRouter.Route(cmdId, serial, msg)
  → 找到对应的等待回调（通过 serial 匹配）
  → 调用回调，传入响应数据
  → 从 argDicts 移除该请求记录
  → 若 argDicts 中无 displayTip 请求，隐藏 Loading
```

---

## 七、给新手的实践建议

1. **永远不要在网络回调中直接修改 Unity 对象**：Unity API 不是线程安全的，消息队列就是为了解决这个问题

2. **延迟 Loading 是 UX 细节，但影响重大**：快速响应的请求不应打断用户流程，只有真正的慢请求才需要告知用户"正在等待"

3. **序列号是 RPC 的核心机制**：学会用序列号关联请求和响应，这是所有 C/S 架构游戏的基础

4. **用哨兵值（如 -1）表示"无效状态"**：比 `bool` + `int` 两个字段更简洁，但需要在代码中保持一致的约定

这套网络消息处理机制是游戏客户端架构中最基础也最重要的部分，值得深入理解和反复实践。
