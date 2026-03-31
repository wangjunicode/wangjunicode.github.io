---
title: Unity游戏聊天气泡组件的状态机设计
published: 2026-03-31
description: 深度解析聊天气泡组件如何用状态机实现左右气泡镜像布局、时间格式化显示、消息区分逻辑及循环列表中的高效复用机制。
tags: [Unity, UI系统, 聊天系统, 状态机组件]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏聊天气泡组件的状态机设计

## 聊天气泡 UI 的技术本质

私聊界面的聊天气泡是 UI 中"同一组件，双重外观"的经典案例：

- 自己发的消息：气泡在右，头像在右，蓝色背景
- 对方发的消息：气泡在左，头像在左，灰色背景

一个直观的实现是"左气泡 Prefab + 右气泡 Prefab"两套资源，但这意味着：
- 相同的功能（显示消息文字）要写两份代码
- 修改气泡圆角大小要改两个 Prefab
- 如果将来加入表情消息，要在两套 Prefab 上各改一次

更好的方案：**一个 Prefab + 状态机切换布局**。这就是 `Item_ChatBubble` 的设计思路。

---

## 状态机组件（UIStateBinder）

```csharp
public void SetData(ZoneChatMsg chatMsg, ulong selfPlayerId)
{
    _chatMsg = chatMsg;
    _selfPlayerId = selfPlayerId;
    _isSelfMessage = chatMsg?.Sender?.PlayerId == selfPlayerId;
    
    RefreshUI();
}

private void RefreshUI()
{
    if (_chatMsg == null) return;
    
    // 状态机切换：0=好友消息（左），1=自己消息（右）
    if (u_ComU_ChatBubbleUIStateBinder != null)
    {
        u_ComU_ChatBubbleUIStateBinder.ApplyState(_isSelfMessage ? 1 : 0);
    }
    
    // 根据状态更新对应的文本组件
    if (_isSelfMessage)
    {
        if (u_ComU_SelfChatItemMsg != null)
            u_ComU_SelfChatItemMsg.text = _chatMsg.Content ?? string.Empty;
        if (u_ComU_SelfChatItemMsg_TimeYear != null)
            u_ComU_SelfChatItemMsg_TimeYear.text = yearDate;
        if (u_ComU_SelfChatItemMsg_TimeHour != null)
            u_ComU_SelfChatItemMsg_TimeHour.text = hourTime;
    }
    else
    {
        if (u_ComU_FriendChatItemMsg != null)
            u_ComU_FriendChatItemMsg.text = _chatMsg.Content ?? string.Empty;
        // ...好友消息的时间同理
    }
}
```

**`UIStateBinder.ApplyState(int)` 的原理**：

`UIStateBinder`（或等价的 `UIStateSelector`）是一种在 Unity 中常见的状态管理组件。预先在 Inspector 中配置好每个状态下各子节点的属性（位置/大小/颜色/激活状态），运行时只需调用 `ApplyState(index)` 就能完整切换所有属性。

在聊天气泡中：
- 状态0（好友消息）：头像组件在左，气泡 Image 在右空间镜像，文字 TextMeshPro 用友的
- 状态1（自己消息）：头像组件在右，气泡 Image 正常，文字 TextMeshPro 用自己的

与 `SetActive` 控制多套子节点相比，状态机方式更清晰，美术可以在 Inspector 中直接调整每种状态的视觉效果，不需要程序介入。

---

## 时间格式化的设计考量

```csharp
var msgTime = DateTimeOffset.FromUnixTimeSeconds(_chatMsg.SendTime).LocalDateTime;
string yearDate = msgTime.ToString("yyyy年MM月dd日");  // "2026年03月31日"
string hourTime = msgTime.ToString("HH:mm");           // "14:30"
```

**为什么把时间拆成两个字段？**

日期（年月日）和时间（时分）显示在不同的位置和不同的字号——日期通常比较小（次要信息），而时分比较显眼（主要信息）。拆开后，美术可以独立控制两者的字体大小、颜色、位置。

**`DateTimeOffset.FromUnixTimeSeconds` vs `new DateTime`**：

服务器传来的是 Unix 时间戳（秒级），`DateTimeOffset.FromUnixTimeSeconds` 直接将其转换为本地时间，自动处理时区。如果用 `new DateTime(1970, 1, 1).AddSeconds(timestamp)`，需要手动处理时区偏移，容易出错。

---

## 在循环列表中的高效复用

聊天记录通常用循环列表展示（消息可能有数百条）。当循环列表复用一个 `Item_ChatBubble` 时，会调用 `SetData` 传入新消息：

```csharp
// 循环列表中的 ItemRenderer
private void RenderChatBubble(int index, ZoneChatMsg msg, Item_ChatBubble bubble, bool select)
{
    bubble.SetData(msg, _selfPlayerId);  // 复用的核心：重置整个状态
}
```

`SetData` 的设计保证了复用的安全性：
1. `_chatMsg = chatMsg;`：覆盖旧数据
2. `_isSelfMessage = chatMsg?.Sender?.PlayerId == selfPlayerId;`：重新计算消息方向
3. `RefreshUI();`：重置所有UI元素的状态

**关键：`u_ComU_SelfChatItemMsg != null` 的空值检查**

循环列表复用时，可能存在这样的情况：一个气泡刚刚从对象池取出，Unity 的序列化字段还没完全初始化。加上 `!= null` 检查，防止空引用异常。

---

## 状态组件的双向文本结构

```
[Item_ChatBubble GameObject]
├── UIStateBinder (状态控制)
│     状态0 → 显示 FriendGroup，隐藏 SelfGroup
│     状态1 → 显示 SelfGroup，隐藏 FriendGroup
│
├── [FriendGroup] (好友消息区域)
│     ├── 头像Image (在左)
│     ├── 气泡Image (在右，镜像)
│     ├── u_ComU_FriendChatItemMsg (TextMeshPro)
│     ├── u_ComU_FriendChatItemMsg_TimeYear
│     └── u_ComU_FriendChatItemMsg_TimeHour
│
└── [SelfGroup] (自己消息区域)
      ├── 头像Image (在右)
      ├── 气泡Image (在左，正向)
      ├── u_ComU_SelfChatItemMsg (TextMeshPro)
      ├── u_ComU_SelfChatItemMsg_TimeYear
      └── u_ComU_SelfChatItemMsg_TimeHour
```

两套文本组件（`FriendChatItemMsg` 和 `SelfChatItemMsg`）虽然显示的是相同的数据（消息内容），但属于不同的 GameObject 树，美术可以独立调整各自的样式（字体颜色、对齐方式、气泡内边距等）。

---

## 消息内容的安全处理

```csharp
u_ComU_SelfChatItemMsg.text = _chatMsg.Content ?? string.Empty;
```

`?? string.Empty` 是一个重要的安全检查。如果服务器发来的消息 `Content` 字段为 null（比如这是一条纯表情消息或附件消息），直接赋值会导致 TextMeshPro 文本为 "null"（TextMeshPro 会把 null 转换为字符串"null"）。

用 `?? string.Empty` 确保空内容时显示为空，而不是 "null" 字样。

---

## 消息气泡高度的动态计算

不同长度的消息，气泡的高度不同。通常用 `ContentSizeFitter` 组件配合 `VerticalLayoutGroup` 自动计算。但循环列表需要**事先知道每个 Item 的高度**，才能正确计算滚动范围。

这产生了一个矛盾：高度在 Layout 计算后才能确定，但循环列表需要在显示前就知道高度。

常见解决方案：
1. **固定高度**：所有气泡使用相同高度（截断过长文字）
2. **预计算高度**：在 `SetData` 中用 `TMP_Text.GetPreferredValues` 计算文字所需高度
3. **异步刷新**：先显示，一帧后回调通知循环列表更新高度

```csharp
// 方案2示例：预计算高度
public float CalculatePreferredHeight(float width)
{
    // 使用 TMP 的测量接口计算文字所需高度
    var textComponent = _isSelfMessage ? u_ComU_SelfChatItemMsg : u_ComU_FriendChatItemMsg;
    Vector2 preferredValues = textComponent.GetPreferredValues(_chatMsg.Content, width, 0);
    return preferredValues.y + BubblePadding * 2;  // 加上气泡内边距
}
```

---

## 进阶：消息状态（发送中/已发送/发送失败）

真实的聊天 UI 还需要处理消息发送状态：

```csharp
public enum MessageStatus
{
    Sending,  // 发送中（显示加载动画）
    Sent,     // 已发送（服务器确认）
    Failed    // 发送失败（显示重试按钮）
}
```

发送失败时的处理：

```csharp
// 在气泡旁显示"重试"图标
u_ComRetryButton.gameObject.SetActive(_currentStatus == MessageStatus.Failed);

// 点击重试
private void OnRetryClick()
{
    EventSystem.Instance.Publish(YIUIComponent.ClientScene,
        new Evt_Chat_RetryMessage { MessageId = _chatMsg.MsgId });
}
```

这套状态处理让聊天体验更接近微信/QQ，是商业游戏私聊功能的标配。

---

## 总结

`Item_ChatBubble` 虽然代码量不大，但展示了几个重要的 UI 工程实践：

1. **状态机切换布局**：一个 Prefab 处理两种外观，比两套 Prefab 维护成本低
2. **时间字段拆分**：年月日和时分分开，支持独立的样式控制
3. **`DateTimeOffset` 处理时区**：比手动加减时区更安全
4. **`?? string.Empty` 空值保护**：防止 null 内容被渲染为 "null" 字符串
5. **复用安全**：`SetData` 全量更新所有状态，保证复用时不遗留旧数据
6. **null 检查**：对象池复用时序列化字段可能尚未初始化，每次访问都要检查
