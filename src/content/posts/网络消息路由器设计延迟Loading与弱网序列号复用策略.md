---
title: 网络消息路由器设计——0.5秒延迟Loading与弱网序列号复用策略
published: 2026-03-31
description: 深入解析MessageRouter的智能Loading显示机制，分析延迟0.5秒再显示、多请求并发时最旧请求计时、弱网序列号缓存复用的完整设计
tags: [Unity, 网络编程, 架构设计]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# 网络消息路由器设计——0.5秒延迟Loading与弱网序列号复用策略

一个常被忽视的用户体验问题：当玩家点击了某个按钮触发网络请求，如果立刻显示Loading界面，快速响应的请求（50ms返回）会让Loading一闪而过，视觉体验很差。但如果不显示Loading，慢速请求（2秒返回）又会让界面看起来"卡死"。

VGame项目的`MessageRouterSystem`用一个**0.5秒延迟显示**的策略完美解决了这个问题。

## 一、智能Loading显示策略

```csharp
private const float NetworkRequestLoadingDelaySeconds = 0.5f; // 延迟0.5秒

public static void OnNetworkRequestLoadingCheck(this MessageRouter self)
{
    // 条件1：有弹窗时不显示Loading（弹窗优先）
    if (self.networkComp != null && self.networkComp.IsPopNetError)
        return;
    
    // 条件2：正在重连时不显示请求Loading（重连Loading优先，避免双重Loading）
    var zoneSession = self.networkComp.Root().GetComponent<ZoneSession>();
    if (zoneSession != null && zoneSession.IsConnectReconnecting())
    {
        if (self.networkRequestLoadingCode != -1)
            self.HideNetworkRequestLoading(); // 重连时隐藏请求Loading
        return;
    }
    
    // 情况A：没有等待中的请求 → 确保Loading隐藏
    if (!self.TryGetOldestDisplayTipStartTime(out var oldestStartTime))
    {
        if (self.networkRequestLoadingCode != -1)
            self.HideNetworkRequestLoading();
        return;
    }
    
    // 情况B：Loading已显示 → 保持（不重复显示）
    if (self.networkRequestLoadingCode != -1)
        return;
    
    // 情况C：有等待中的请求，但还没到0.5秒 → 继续等待
    float now = Game.realtimeSinceStartup;
    if (now - oldestStartTime >= NetworkRequestLoadingDelaySeconds)
    {
        // 情况D：已等待超过0.5秒 → 显示Loading
        self.ShowNetworkRequestLoading();
    }
}
```

**0.5秒延迟的工作原理**：

1. 发起请求时，记录开始时间（`starttime`）
2. 每帧在`OnNetworkRequestLoadingCheck`里检查
3. 如果请求在0.5秒内返回了 → Loading从未显示，用户看到的是"瞬间完成"
4. 如果请求超过0.5秒还没返回 → 显示Loading，告知用户"正在处理中"
5. 请求返回后 → 如果Loading已显示则隐藏，否则什么都不做

**多请求并发时的"最老请求"策略**：

```csharp
private static bool TryGetOldestDisplayTipStartTime(
    this MessageRouter self, out float oldestStartTime)
{
    oldestStartTime = 0f;
    bool has = false;
    
    // 遍历所有等待中的请求，找到最早开始的
    foreach (var arg in self.argDicts.Values)
    {
        if (!arg.displayTip) continue; // 只关心需要显示Loading提示的请求
        
        if (!has || arg.starttime < oldestStartTime)
        {
            oldestStartTime = arg.starttime;
            has = true;
        }
    }
    return has;
}
```

为什么用"最老请求"的时间？

假设：请求A在t=0发出，请求B在t=0.4发出，t=0.5时检查：
- 如果用最老请求A的时间：`0.5 - 0 = 0.5s`，达到阈值，显示Loading
- 如果用最新请求B的时间：`0.5 - 0.4 = 0.1s`，还没到，不显示Loading

用最老请求确保：只要有任何一个请求等待超过0.5秒，就会显示Loading，防止"被新请求掩盖旧请求的延迟"。

## 二、Loading的显示与隐藏

```csharp
private static void ShowNetworkRequestLoading(this MessageRouter self)
{
    if (self.networkRequestLoadingCode == -1)
    {
        self.networkRequestLoadingCode = NetworkRequestLoadingCode;
        EventSystem.Instance.Publish(self.ClientScene(), new Evt_ShowMiniLoading
        {
            Code = self.networkRequestLoadingCode,
            ShowMask = true,    // 显示半透明遮罩（防止误操作）
            Content = "网络连接中...",
            ShowLoad = true     // 显示转圈动画
        });
    }
}

public static void HideNetworkRequestLoading(this MessageRouter self)
{
    if (self.networkRequestLoadingCode != -1)
    {
        EventSystem.Instance.Publish(self.ClientScene(), 
            new Evt_HideMiniLoading { Code = self.networkRequestLoadingCode });
        self.networkRequestLoadingCode = -1; // 重置为-1（表示未显示）
    }
}
```

`networkRequestLoadingCode = -1`是"未显示"状态，`!= -1`是"已显示"状态。用哈希码作为Loading的唯一标识，确保隐藏的是同一个Loading，不会误隐藏其他Loading。

**`ShowMask = true`**：显示半透明背景遮罩，防止用户在网络请求期间重复点击按钮，避免重复发送相同请求。

## 三、序列号缓存与弱网重试

```csharp
public static uint NextSerial(this MessageRouter self, uint cmdID)
{
    uint cmdserial = 0;
    
    CmdCacheInfo info = null;
    self.cmdSerialCache.TryGetValue(cmdID, out info);
    
    // 弱网优化：如果这个CMD已有缓存的序列号，复用它
    if (info != null && info.serial != 0)
    {
        cmdserial = info.serial; // 复用旧序列号
    }
    
    if (cmdserial == 0)
    {
        // 正常情况：分配新序列号
        self._serial++;
        cmdserial = self._serial;
    }
    
    return cmdserial;
}
```

**序列号（Serial）的作用**：

每个网络请求都有一个唯一的Serial号，服务端响应时带回这个Serial，客户端用它匹配"哪个响应对应哪个请求"（因为网络是异步的，响应可能乱序）。

**弱网复用序列号的场景**：

玩家在弱网环境下，发了一个请求（Serial=100），服务器可能处理了但响应丢失了。客户端超时后重发，如果用新的Serial（101），服务器收到后认为是新请求，可能重复执行（比如重复扣除物品）。

如果用原来的Serial（100）重发，服务器看到Serial=100，检查"我已经处理过100了吗？"，如果已处理，直接返回上次的结果，不重复执行。这是**幂等性（Idempotency）**的网络实现。

## 四、displayTip字段的语义

```csharp
foreach (var arg in self.argDicts.Values)
{
    if (!arg.displayTip) continue; // 只考虑需要显示提示的请求
}
```

不是所有网络请求都需要Loading提示：
- **displayTip=true**：影响玩家操作流程的请求，需要Loading告知玩家"正在处理"
- **displayTip=false**：后台静默请求（如埋点上报、定期同步），玩家感知不到，不需要Loading

这解决了"埋点请求不应该触发Loading界面"的问题。

## 五、弹窗与Loading的优先级管理

```csharp
// 条件1：有弹窗时不显示Loading
if (self.networkComp != null && self.networkComp.IsPopNetError)
    return;
```

当网络错误弹窗已经显示（`IsPopNetError=true`），不再显示Loading界面。

弹窗和Loading同时显示会让UI显得混乱。弹窗通常需要用户交互（点击确认/取消），而Loading是被动等待，语义冲突。

**三层优先级**：
1. 网络错误弹窗（最高，需要用户确认）
2. 重连Loading（正在自动重连）
3. 请求Loading（普通请求等待）

每次检查都按优先级从高到低处理，高优先级存在时忽略低优先级。

## 六、实战中的注意事项

**问题：快速连续点击触发多次请求**

玩家快速点了3次"确认"按钮，发出3个请求。`ShowMask=true`的遮罩应该在第一个请求发出时就出现，阻止后续点击。但遮罩有0.5秒延迟……

解决：按钮的点击事件在第一次点击后立刻设置`isProcessing=true`（不等Loading），`isProcessing`期间忽略重复点击。

**问题：Loading显示后请求立刻返回**

极小概率情况：正好在0.5秒时请求返回了，但Loading刚刚显示。玩家会看到Loading一瞬间。

接受：这种极端情况概率极低，不影响整体体验，不需要特殊处理。

## 七、总结

MessageRouter的Loading管理设计展示了：

1. **延迟显示**：0.5秒内完成的请求不显示Loading，消除"一闪而过"体验
2. **最老请求计时**：多请求并发时，以最早发出的为基准
3. **优先级管理**：弹窗 > 重连Loading > 请求Loading
4. **幂等重试**：弱网时复用序列号，服务端过滤重复请求
5. **displayTip白名单**：后台请求不触发Loading

对新手来说，"延迟显示Loading"是一个提升用户体验的小技巧，同时对网络延迟的正确判断也非常重要——不是"请求一发出就显示Loading"，而是"请求慢到影响用户体验时才显示"。
