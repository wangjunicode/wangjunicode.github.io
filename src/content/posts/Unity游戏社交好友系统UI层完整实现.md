---
title: Unity游戏社交好友系统UI层完整实现
published: 2026-03-31
description: 深入分析好友列表、好友申请、黑名单、私聊消息的完整UI数据层实现，包含网络协议封装、本地缓存、未读消息计数等核心机制。
tags: [Unity, UI系统, 社交系统, 好友系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏社交好友系统UI层完整实现

## 社交系统是游戏留存的核心抓手

社交好友系统在游戏中扮演着至关重要的角色——好友关系、私聊消息、黑名单管理，直接影响玩家的社交粘性和长期留存。从技术视角来看，社交UI的挑战在于：

1. **状态复杂**：好友列表、申请列表、黑名单三套并行的数据
2. **实时性要求**：对方发消息需要立即展示，还要计未读数
3. **本地持久化**：聊天记录需要在重启后仍然可见
4. **网络异常容错**：每个网络请求都可能失败，UI需要优雅降级

本文将通过 `YIUI_SocialContactComponentSystem.cs` 的源码，系统讲解这些问题的解决方案。

---

## 数据初始化

```csharp
[EntitySystem]
private static void Awake(this YIUI_SocialContactComponent self)
{
    self.FriendList = new List<ZoneFriendListItem>();       // 好友列表
    self.RequestList = new List<ZoneFriendListItem>();      // 好友申请列表
    self.BlackList = new List<ZoneFriendListItem>();        // 黑名单
    self.ChatMessages = new Dictionary<ulong, List<ZoneChatMsg>>();  // 聊天消息 (key=好友ID)
    self.UnreadMessageCount = new Dictionary<ulong, int>>();         // 未读消息计数
}
```

用 `[EntitySystem]` 标注的 `Awake` 方法是 ECS 框架的生命周期钩子，在组件挂载时自动调用。这里的初始化原则：**所有集合字段在 Awake 中就初始化为空集合，而不是 null**，后续代码可以直接使用而不需要空值检查。

---

## 网络协议层封装

### 搜索好友

```csharp
public static async ETTask<ZoneFriendListItem> SearchFriend(this YIUI_SocialContactComponent self, string searchText)
{
    if (string.IsNullOrEmpty(searchText))
    {
        Log.LogWarning("[SocialContact] 搜索关键字为空");
        return null;
    }
    
    var req = new ZoneFriendSearchReq();
    
    // 智能判断：纯数字→按GID搜索；有文字→按名称搜索
    if (ulong.TryParse(searchText, out ulong gid))
    {
        req.Type = (int)EnumFriendSearchType.EFriendSearchTypeGid;
        req.Gid = gid;
    }
    else
    {
        req.Type = (int)EnumFriendSearchType.EFriendSearchTypeName;
        req.Name = searchText;
    }
    
    var nr = await self.ClientScene().GetComponent<NetworkComponent>()
        .SendAsync<ZoneFriendSearchResp>((uint)ZoneClientCmd.ZoneCsFriendSearch, req);
    
    if (nr.IsCompleteSuccess && nr.Data.RetInfo?.RetCode == 0)
    {
        return nr.Data.ListItem;
    }
    
    Log.LogError("[SocialContact][Network] 协议 {0}({1}) 接收失败", 
        nameof(ZoneClientCmd.ZoneCsFriendSearch), (uint)ZoneClientCmd.ZoneCsFriendSearch);
    return null;
}
```

**设计亮点**：
- 输入智能路由：同一个搜索框，根据输入内容自动选择按ID还是按名称搜索，用户体验更流畅
- 失败返回 null：调用方通过判断返回值是否为 null 来确认成功/失败，不抛异常
- 日志带协议号：`nameof(ZoneClientCmd.ZoneCsFriendSearch)` + 数字ID，方便抓包对照

### 好友列表的分页加载

```csharp
public static async ETTask<(List<ZoneFriendListItem> items, uint totalCount)> GetFriendList(
    this YIUI_SocialContactComponent self, EnumFriendListType listType, 
    int offset = 0, int limit = YIUI_SocialContactComponent.PAGE_SIZE)
{
    var req = new ZoneFriendGetListReq
    {
        Type = (int)listType,
        Offset = offset,
        Limit = limit
    };
    
    var nr = await self.ClientScene().GetComponent<NetworkComponent>()
        .SendAsync<ZoneFriendGetListResp>((uint)ZoneClientCmd.ZoneCsFriendGetList, req);
    
    if (nr.IsCompleteSuccess && nr.Data.RetInfo?.RetCode == 0)
    {
        var items = new List<ZoneFriendListItem>();
        if (nr.Data.ListItem != null)
            items.AddRange(nr.Data.ListItem);
        return (items, nr.Data.TotalCnt);
    }
    
    return (new List<ZoneFriendListItem>(), 0);
}
```

返回 `(List, totalCount)` 的元组设计很实用——UI 层同时拿到当前页数据和总数，可以正确渲染"共X个好友"以及是否需要加载更多。`Offset + Limit` 的分页协议是行业标准，理解成"从第offset个开始取limit个"即可。

---

## 好友操作的统一入口

所有好友操作（添加、确认、拒绝、删除、拉黑、移黑名单）都通过一个统一的协议走：

```csharp
public static async ETTask<bool> FriendOperate(
    this YIUI_SocialContactComponent self, EnumFriendOperateType operateType, ulong targetGid)
{
    var req = new ZoneFriendOperateReq
    {
        OptType = (int)operateType,
        Gid = targetGid
    };
    
    var nr = await self.ClientScene().GetComponent<NetworkComponent>()
        .SendAsync<ZoneFriendOperateResp>((uint)ZoneClientCmd.ZoneCsFriendOperate, req);
    
    if (nr.IsCompleteSuccess && nr.Data.RetInfo?.RetCode == 0)
        return true;
    
    Log.LogError("[SocialContact][Network] 协议 {0}({1}) 接收失败, RetCode={2}", 
        nameof(ZoneClientCmd.ZoneCsFriendOperate), (uint)ZoneClientCmd.ZoneCsFriendOperate,
        nr.Data?.RetInfo?.RetCode ?? -1);
    return false;
}
```

**为什么用统一操作接口？** 

服务端通常为"好友操作"设计一个通用协议，通过 `OptType` 枚举区分具体操作，好处是减少协议数量、统一错误处理逻辑。客户端也配套用一个 `FriendOperate` 方法封装，上层只需关注"用什么操作类型"，不需要关心底层网络细节。

各个高层操作都建立在这个基础上：

```csharp
public static async ETTask<bool> AddFriend(this YIUI_SocialContactComponent self, ulong targetGid)
    => await self.FriendOperate(EnumFriendOperateType.EFriendOperateTypeAdd, targetGid);

public static async ETTask<bool> AcceptFriend(this YIUI_SocialContactComponent self, ulong targetGid)
{
    // 前置检查：好友数量上限
    if (self.TotalFriendCount >= YIUI_SocialContactComponent.MAX_FRIEND_COUNT)
    {
        Log.LogWarning("[SocialContact] 好友数量已达上限");
        return false;
    }
    
    bool success = await self.FriendOperate(EnumFriendOperateType.EFriendOperateTypeConfirm, targetGid);
    if (success)
    {
        // 操作成功后主动刷新受影响的列表
        await self.RefreshRequestList();
        await self.RefreshFriendList();
    }
    return success;
}
```

**注意 `AcceptFriend` 的细节**：
1. 先检查好友数量上限，在请求发出前就拦截
2. 操作成功后同时刷新申请列表和好友列表，保证数据一致性
3. `await` 两个刷新操作，确保UI更新前数据是最新的

---

## 私聊消息系统

### 发送消息

```csharp
public static async ETTask<ZoneChatMsg> SendChatMessage(
    this YIUI_SocialContactComponent self, ulong receiverId, string receiverName, string content)
{
    if (string.IsNullOrEmpty(content))
    {
        Log.LogWarning("[SocialContact] 消息内容为空");
        return null;
    }
    
    var req = new ZoneChatSendReq
    {
        ChatMsg = new ZoneChatMsg
        {
            Channel = (int)EnumChatChannel.EChatChannelFriend,  // 好友私聊频道
            MsgType = (int)EnumChatMsgType.EChatMsgTypeMsg,
            Receiver = new ZoneChatRoleInfo
            {
                PlayerId = receiverId,
                Name = receiverName
            },
            Content = content
        }
    };
    
    var nr = await self.ClientScene().GetComponent<NetworkComponent>()
        .SendAsync<ZoneChatSendResp>((uint)ZoneClientCmd.ZoneCsChatSend, req);
    
    if (nr.IsCompleteSuccess && nr.Data.RetInfo?.RetCode == 0)
    {
        // 关键：服务器回包中包含完整的消息对象（含服务器时间戳），要用这个
        if (nr.Data.ChatMsg != null)
            self.AddChatMessage(receiverId, nr.Data.ChatMsg);
        
        return nr.Data.ChatMsg;
    }
    return null;
}
```

**重要细节**：发送成功后，不是把本地构造的 `req.ChatMsg` 添加到列表，而是使用服务器返回的 `nr.Data.ChatMsg`。因为服务器会给消息打上权威时间戳和消息ID，用服务器数据保证时序的准确性。

### 接收消息推送

```csharp
public static void OnChatNotifyReceived(this YIUI_SocialContactComponent self, List<ZoneChatMsg> chatMsgs)
{
    if (chatMsgs == null || chatMsgs.Count == 0) return;
    
    foreach (var msg in chatMsgs)
    {
        // 只处理好友私聊频道（过滤掉世界频道等其他消息）
        if (msg.Channel == (int)EnumChatChannel.EChatChannelFriend)
        {
            ulong friendId = msg.Sender?.PlayerId ?? 0;
            if (friendId == 0) continue;
            
            self.AddChatMessage(friendId, msg);
            
            // 如果不是当前聊天窗口，增加未读计数
            if (self.CurrentChatFriend == null || self.CurrentChatFriend.Id != friendId)
            {
                self.IncrementUnreadCount(friendId);
            }
        }
    }
}
```

这里的 `Channel` 过滤很关键——服务器推送聊天通知可能把多个频道的消息合并发送，客户端必须根据 `Channel` 字段过滤，否则好友聊天窗会收到世界频道消息。

---

## 未读消息计数系统

```csharp
// 增加未读
public static void IncrementUnreadCount(this YIUI_SocialContactComponent self, ulong friendId)
{
    if (!self.UnreadMessageCount.ContainsKey(friendId))
        self.UnreadMessageCount[friendId] = 0;
    self.UnreadMessageCount[friendId]++;
}

// 清零未读（进入聊天窗时调用）
public static void ClearUnreadCount(this YIUI_SocialContactComponent self, ulong friendId)
{
    if (self.UnreadMessageCount.ContainsKey(friendId))
        self.UnreadMessageCount[friendId] = 0;
}

// 获取总未读数（用于主界面红点）
public static int GetTotalUnreadCount(this YIUI_SocialContactComponent self)
{
    int total = 0;
    foreach (var count in self.UnreadMessageCount.Values)
        total += count;
    return total;
}
```

未读计数的设计很简洁：
- `Dictionary<ulong, int>` 以好友ID为key存储每个人的未读数
- 进入聊天窗立即清零，而不是等"已读回执"
- `GetTotalUnreadCount` 汇总所有好友的未读数，供主界面红点使用

---

## 聊天记录的本地持久化

这是整个系统中工程量最大的部分，因为涉及 JSON 序列化和 PlayerPrefs 读写。

### 数据结构设计

```csharp
[Serializable]
public class LocalChatStorage
{
    public List<LocalChatMessage> Messages = new List<LocalChatMessage>();
}

[Serializable]
public class LocalChatMessage
{
    public string Content;
    public long SendTime;
    public ulong SenderId;
    public string SenderName;
    public ulong ReceiverId;
    public string ReceiverName;
}
```

注意 `LocalChatMessage` 是一个精简版的消息对象——只保存UI展示需要的字段，而不是完整的 `ZoneChatMsg` 协议对象。这减少了存储空间，也避免了协议字段变更导致本地存储格式失效。

### 保存逻辑

```csharp
public static void SaveChatToLocal(this YIUI_SocialContactComponent self, ulong friendId)
{
    if (!self.ChatMessages.TryGetValue(friendId, out var messages) || messages.Count == 0)
        return;
    
    try
    {
        // 只保存最近10条，避免PlayerPrefs爆炸
        int startIndex = Math.Max(0, messages.Count - YIUI_SocialContactComponent.MAX_LOCAL_CHAT_COUNT);
        var messagesToSave = new List<LocalChatMessage>();
        
        for (int i = startIndex; i < messages.Count; i++)
        {
            var msg = messages[i];
            messagesToSave.Add(new LocalChatMessage
            {
                Content = msg.Content,
                SendTime = msg.SendTime,
                SenderId = msg.Sender?.PlayerId ?? 0,
                SenderName = msg.Sender?.Name ?? string.Empty,
                ReceiverId = msg.Receiver?.PlayerId ?? 0,
                ReceiverName = msg.Receiver?.Name ?? string.Empty
            });
        }
        
        var storageData = new LocalChatStorage { Messages = messagesToSave };
        string json = JsonUtility.ToJson(storageData);
        PlayerPrefs.SetString(GetLocalChatKey(friendId), json);
        PlayerPrefs.Save();
    }
    catch (Exception e)
    {
        Log.Error(ZString.Format("[SocialContact] 保存聊天记录失败: {0}", e.Message));
    }
}
```

**MAX_LOCAL_CHAT_COUNT 的必要性**：PlayerPrefs 存储有大小限制（iOS约1MB，Android约无限但也不建议存太多），限制每个好友只保存最近10条是合理的工程取舍。

### 加载逻辑与防重复

```csharp
public static void LoadChatFromLocal(this YIUI_SocialContactComponent self, ulong friendId)
{
    try
    {
        string key = GetLocalChatKey(friendId);
        if (!PlayerPrefs.HasKey(key)) return;
        
        string json = PlayerPrefs.GetString(key);
        if (string.IsNullOrEmpty(json)) return;
        
        var storageData = JsonUtility.FromJson<LocalChatStorage>(json);
        if (storageData?.Messages == null || storageData.Messages.Count == 0) return;
        
        if (!self.ChatMessages.ContainsKey(friendId))
            self.ChatMessages[friendId] = new List<ZoneChatMsg>();
        
        // 内存中已有消息，不重复加载（防止和服务器拉取的消息重叠）
        if (self.ChatMessages[friendId].Count > 0) return;
        
        // 将本地精简格式还原为协议格式
        foreach (var localMsg in storageData.Messages)
        {
            var msg = new ZoneChatMsg
            {
                Content = localMsg.Content,
                SendTime = localMsg.SendTime,
                Channel = (int)EnumChatChannel.EChatChannelFriend,
                Sender = new ZoneChatRoleInfo { PlayerId = localMsg.SenderId, Name = localMsg.SenderName },
                Receiver = new ZoneChatRoleInfo { PlayerId = localMsg.ReceiverId, Name = localMsg.ReceiverName }
            };
            self.ChatMessages[friendId].Add(msg);
        }
    }
    catch (Exception e)
    {
        Log.Error(ZString.Format("[SocialContact] 加载聊天记录失败: {0}", e.Message));
    }
}
```

这里有个重要的判断：`if (self.ChatMessages[friendId].Count > 0) return;`

这个检查防止了一个典型的 Bug：玩家进入聊天窗 → 收到新消息 → 切换到其他界面 → 再次进入聊天窗 → `LoadChatFromLocal` 被再次调用 → 本地缓存的历史消息被重复加载，消息列表出现重复。

---

## Key 命名规范

```csharp
private static string GetLocalChatKey(ulong friendId)
{
    return ZString.Format("{0}{1}", YIUI_SocialContactComponent.CHAT_STORAGE_KEY_PREFIX, friendId);
}
```

PlayerPrefs 的 Key 使用前缀+ID的格式，例如 `"chat_123456789"`。统一前缀的好处：
- 可以批量枚举和清理（虽然 PlayerPrefs 本身不支持前缀匹配，但至少在代码层面有语义组织）
- 避免与游戏中其他模块的 PlayerPrefs Key 冲突

---

## 好友聊天的完整使用流

```
玩家点击好友 → StartChatWithFriend(friend)
    ↓
LoadChatFromLocal(friend.Id)   // 从本地加载历史消息
    ↓
ClearUnreadCount(friend.Id)    // 清零未读计数，触发主界面红点更新
    ↓
self.CurrentChatFriend = friend // 设置当前聊天对象（新消息不再计未读）
    ↓
玩家输入消息并发送
    ↓
SendMessageToCurrentFriend(content)
    ↓
服务器返回 → AddChatMessage() → SaveChatToLocal() // 自动持久化
    ↓
玩家关闭聊天窗 → EndCurrentChat()
    ↓
self.CurrentChatFriend = null  // 之后收到消息重新计未读
```

---

## 工程经验总结

1. **统一操作接口**：`FriendOperate` 统一封装所有好友操作，减少重复代码
2. **操作后刷新**：成功操作后主动刷新相关列表，不依赖服务器推送保证UI一致性
3. **防重复加载**：本地缓存加载前检查内存是否已有数据
4. **数据量控制**：本地持久化只存最近N条，避免存储溢出
5. **精简存储格式**：本地存储用轻量级结构，而不是完整协议对象
6. **异常全包裹**：所有涉及 PlayerPrefs 的操作用 try-catch 包裹，序列化失败不能让游戏崩溃

这些细节看起来繁琐，但每一个都对应真实发生过的线上问题。工程经验的积累，本质上就是踩坑→修坑→总结→形成规范的过程。
