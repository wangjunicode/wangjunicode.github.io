---
title: 剧情对话系统：可视化节点图与手机消息的实现
published: 2026-03-31
description: 深入解析基于 NodeCanvas 的剧情对话系统设计，包含角色站位节点、手机聊天消息节点、群聊成员动态管理与剧情跳过机制的完整实现。
tags: [Unity, 剧情系统, NodeCanvas, 对话系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 剧情对话系统：可视化节点图与手机消息的实现

## 前言

现代手游的剧情不再是简单的文字对话框——玩家会收到 NPC 发来的"微信消息"、观看类似短视频的竖屏演出、甚至在游戏中接到电话……这些丰富的叙事形式，在技术上对剧情系统提出了全新挑战。

本文通过分析项目中的剧情节点系统，带你理解如何用 NodeCanvas 的流图（FlowGraph）驱动多种叙事形式，并深入剖析"手机消息节点"这个游戏独特玩法的实现细节。

---

## 一、节点图架构：为什么选 NodeCanvas

剧情对话的逻辑天然是有分支的：

```
角色A：你好吗？
  ├─ 选项1：我很好 → 触发好感+1
  ├─ 选项2：还好   → 继续下一句
  └─ 选项3：不好   → 触发特殊支线
```

这种有向图结构用代码硬写极难维护，NodeCanvas 提供了可视化的节点编辑器，让策划直接拖拽节点设计剧情流程，程序员只需要实现各类型节点。

---

## 二、CharacterSlot：角色站位的序列化设计

```csharp
[Serializable]
[MemoryPackable]
public partial class CharacterSlot
{
    [MemoryPackOrder(0)]
    public IPCharacterEnum CharacterEnum;  // IP 形象（优先判断）

    [MemoryPackOrder(3)]
    public NpcCharacterEnum NpcCharacterEnum;  // NPC 类型

    [MemoryPackOrder(1)]
    public AvatarType AvatarType;  // 头像类型

    [MemoryPackOrder(2)]
    public SpeakerPosition SpeakerPosition;  // 角色站位（左/中/右）
}
```

**`[MemoryPackOrder]` 的用途：**

`MemoryPack` 是一个高性能序列化库，通过索引而非字段名进行序列化，比 JSON 快 10 倍以上。`[MemoryPackOrder]` 确保字段顺序固定，即使将来重命名字段也不会破坏已存储的数据。

注意 `NpcCharacterEnum` 的索引是 3，跳过了 2——这意味着 2 曾经存在某个字段，后来被移除但保留了空位（删除 MemoryPack 字段的正确做法，不能用 `[MemoryPackAllowSerialize]` 直接删除否则会破坏序列化格式）。

**`SpeakerPosition`（说话者站位）：**

剧情对话中，说话角色在画面上有固定的位置（通常是左边/右边）。`SpeakerPosition` 枚举驱动角色在对话界面的位置，让策划配置时更直观。

---

## 三、手机消息节点：游戏内的"微信体验"

`SendPhoneMsgNode` 是整个对话系统中最有特色的节点——它模拟了真实手机聊天软件的体验：有发送方、接收方、消息延迟、已读状态，甚至支持群聊和成员进出。

### 3.1 核心字段设计

```csharp
public abstract class SendPhoneMsgNode : AGlobalScriptBase
{
    public int      senderID     = 0;        // 发送人（对应通讯录 ID）
    public int      friendID     = 0;        // 好友 ID（群聊中指具体发言成员）
    public int      toID         = 0;        // 发给谁
    public bool     reject       = false;    // 拒收（不显示消息）
    public bool     msgRead      = false;    // 消息是否已读
    public long     msgDelayMS   = 0;        // 消息发送延迟（毫秒）
    public long     msgOptionsDelayMS = 0;   // 选项出现延迟（毫秒）
    public bool     skipAsDefault = false;   // 跳过时作为默认选项
    public List<int> choiceIds   = new();    // 回复选项 ID 列表
}
```

**延迟字段（msgDelayMS）的设计动机：**

真实的聊天体验是"消息一条一条出现"，而不是瞬间全部出现。`msgDelayMS` 让策划可以精确控制每条消息的出现时机——比如设置 1500ms 的延迟，模拟 NPC "正在输入中……" 的等待感。

**`skipAsDefault` 的设计：**

玩家可能跳过某些手机剧情（不想看完整流程）。但游戏状态需要保持一致——即使跳过，手机通讯录里也要有这条消息的记录（否则后续剧情可能找不到这段历史）。`skipAsDefault = true` 的消息在跳过时会自动存入通讯录并标记已读。

---

### 3.2 群聊的动态成员管理

这是代码中最精妙的设计之一：

```csharp
private List<int> GetCurrentGroupMembers(int groupId)
{
    var groupCfg = CfgManager.tables.TbPhoneDirectory.GetOrDefault(groupId);
    if (groupCfg == null) return new List<int>();

    // 从配置表获取初始成员列表
    var members = new List<int>(groupCfg.Parameter);

    // 向前扫描整个节点图，模拟到本节点之前的群聊变化
    var allNodes = graph.allNodes;
    foreach (var node in allNodes)
    {
        if (node == this) break;  // 到达自身节点时停止

        if (node is SendPhoneJoinGroupNode joinNode && joinNode.GroupId == groupId)
        {
            if (!members.Contains(joinNode.JoinMemberId))
                members.Add(joinNode.JoinMemberId);  // 模拟加群
        }
        else if (node is SendPhoneLeaveGroupNode leaveNode && leaveNode.GroupId == groupId)
        {
            members.Remove(leaveNode.MemberId);  // 模拟退群
        }
    }

    return members;
}
```

**"时间旅行"式的成员状态计算：**

群聊成员是动态的——在剧情进行中，角色可能加入或退出群聊。为了在 Inspector 中正确显示"当前这个节点时，群里有哪些成员"，代码从头遍历节点图，重放所有加群/退群事件，最终得到"执行到当前节点时群聊的成员状态"。

这个设计的优雅之处：**编辑器和运行时使用完全相同的逻辑**，策划在编辑时看到的群成员列表，就是游戏运行时真实的状态。

---

### 3.3 MemoryPackOrder 的跳号设计

```csharp
[MemoryPackOrder(0)]   public List<int> choiceIds
[MemoryPackOrder(1)]   public List<string> choiceNames
[MemoryPackOrder(2)]   public int senderID = 0;
// ...
// senderID 后面定义的字段要从100开始
[MemoryPackOrder(101)] public bool msgRead;
[MemoryPackOrder(102)] public long msgDelayMS;
```

注释 "senderID 后面定义的字段要从100开始" 是一个非常重要的工程规范：

当 `senderID` 是后来加入的字段（排在 choiceIds 和 choiceNames 后面），会插入序号 2。为了防止未来新加字段与老字段的序号冲突，在 `senderID` 之后的新字段统一从 100 开始编号，留出足够的空间。

这是一种"区段式序号"设计——不同"时期"加入的字段使用不同的序号区段，避免重构时的序号冲突。

---

## 四、节点 UID 的设计

```csharp
public override string name
{
    get { return ZString.Concat(base.name, ZString.Format(" [{0}]", GetUID64())); }
}
```

每个节点有一个 64 位的 UID，显示在 Inspector 标题中。策划和程序员可以通过这个 UID 精确定位某个节点，用于：
- Bug 报告："第 34567891234 节点的消息没有显示"
- 版本对比：检查特定节点是否被修改
- 剧情管理系统：用 UID 索引特定的节点执行状态

---

## 五、对话系统的类型体系

从文件列表可以看出系统支持的所有叙事形式：

| 节点类型 | 文件 | 功能 |
|---------|------|------|
| 对话节点 | `DialogueNode.cs` | 标准对话气泡 |
| 手机短信 | `SendTextNode.cs` | 发送文字消息 |
| 手机图片 | `SendImageNode.cs` | 发送图片 |
| 手机表情 | `SendEmojiNode.cs` | 发送表情包 |
| 手机链接 | `SendLinkNode.cs` | 发送链接卡片 |
| 手机语音 | `SendSystemNode.cs` | 发送系统消息 |
| 打电话 | `CallPhoneNode.cs` | 触发来电界面 |
| 过场动画 | `PlayCutsceneNode.cs` | 播放 CG 动画 |
| 短视频 | `ShortVideoNode.cs` | 播放竖屏视频 |
| 加载场景 | `LoadSceneNode.cs` | 切换剧情场景 |
| 好感度变化 | `FavoChangeNode.cs` | 修改角色好感度 |
| 成就解锁 | `AchievementNode.cs` | 触发成就 |
| 战斗对话 | `InBattleDialogueNode.cs` | 战斗中的实时对话 |

这套类型体系覆盖了现代偶像养成类手游的几乎所有叙事场景。

---

## 六、`EDialogueStopType`：对话暂停的语义

```csharp
public enum EDialogueStopType
{
    None,             // 不暂停
    GuideInteraction, // 因引导交互暂停（等待玩家完成引导操作）
    SayAction,        // 因说话动作暂停（等待语音播放完成）
}
```

对话流程需要在特定时机暂停，等待玩家操作或媒体播放完成。这个枚举区分了暂停的原因，使得恢复逻辑可以针对性处理——引导完成后恢复对话；语音播完后恢复对话，而不是用同一套逻辑处理所有暂停情况。

---

## 七、总结

这套剧情对话系统展示了"数据驱动 + 可视化编辑"的强大之处：

1. **策划自主权**：用 NodeCanvas 可视化节点图，策划不需要懂代码就能设计复杂的分支剧情
2. **序列化安全**：`[MemoryPackOrder]` 保证数据格式向后兼容
3. **状态模拟**：编辑器中实时模拟运行时状态，所见即所得
4. **叙事多样性**：一套框架支持对话、短信、视频、电话等所有叙事形式

对于新手同学，建议先从实现一个简单的对话节点开始，理解 FlowInput/FlowOutput 的概念，再逐步添加分支选项和特殊节点类型。
