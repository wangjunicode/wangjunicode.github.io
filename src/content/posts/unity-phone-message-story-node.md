---
title: 手机短信剧情节点系统——图形化脚本驱动的角色消息对话
published: 2026-03-31
description: 深度解析游戏内手机短信剧情节点的设计，包括SendPhoneMsgNode基类、消息延迟、回复选项与跳过机制
tags: [Unity, 剧情系统, 节点系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 手机短信剧情节点系统——图形化脚本驱动的角色消息对话

现代手游中，越来越多的剧情通过"手机短信界面"来呈现——玩家打开游戏内的"手机"，就像真实使用聊天软件一样，与游戏角色进行文字对话。这种沉浸式的剧情表达方式需要专门的技术支撑。

VGame项目的`SendPhoneMsgNode`及其子类实现了一套完整的手机消息剧情节点系统，基于自研的图形化脚本框架（FlowCanvas风格）。

## 一、节点的设计哲学

```csharp
[UniScript.Design.Name("手机/文字信息")]
[UniScript.Design.Category("Functions/VGame")]
[Color("E79038")]  // 节点的颜色标识（橙色）
[MemoryPackable]
[ViewScript]
public partial class SendTextNode : SendPhoneMsgNode
{
    [fsSerializeAs("phoneTextID")]
    [UniScript.Design.Name("文字消息ID")]
    [MemoryPackOrder(3)]
    public int phoneTextID = 0;
}
```

**特性（Attribute）驱动的节点元数据**：
- `[UniScript.Design.Name]`：节点在编辑器中显示的名称
- `[UniScript.Design.Category]`：节点在菜单中的分类路径
- `[Color("E79038")]`：节点在图形编辑器里的颜色（橙色表示"手机类"节点）
- `[MemoryPackable]`：启用MemoryPack序列化（高性能二进制序列化）
- `[ViewScript]`：标记为视图层脚本（区别于逻辑层脚本）

这些特性让同一套代码框架可以被图形化编辑器识别和渲染，策划/剧情编辑者不需要写代码，只需要在节点图里连接节点。

## 二、SendPhoneMsgNode基类的字段设计

```csharp
public abstract class SendPhoneMsgNode : AGlobalScriptBase
{
    // 回复选项（多选时玩家要选一个）
    [UniScript.Design.Name("回复选项")]
    public List<int> choiceIds = new();     // 选项ID列表
    public List<string> choiceNames = new(); // 选项显示文本（缓存，Editor查看用）
    
    // 发送者
    public int senderID = 0; // 是谁发来的消息
    
    // 是否拒收（某些剧情状态下玩家不想回复）
    public bool reject;
    
    // 消息已读标志
    public bool msgRead;
    
    // 消息发送延迟（模拟真实聊天的"对方正在输入..."效果）
    public long msgDelayMS;  // 单位：毫秒
    
    // 好友ID（哪个联系人的对话框）
    public int friendID = 0;
    
    // 发给谁（群聊时有多个成员）
    public int toID = 0;
    
    // 跳过时的默认选项（跳过剧情时自动选这条路径）
    public bool skipAsDefault = false;
    
    // 选项出现延迟（选项不是立刻出现，而是延迟出现）
    public long msgOptionsDelayMS;
    
    // 图形连接点
    [NonSerialized]
    public FlowInput input;
    [NonSerialized]
    public FlowOutput output;
    [NonSerialized]
    public ListComponent<FlowOutput> outSelectionFlows; // 每个选项对应一个输出端口
}
```

**`msgDelayMS`的真实感设计**：

消息不会立刻出现，而是有延迟。策划可以设置不同长度的延迟来制造不同的节奏感：
- 短消息（"好"）：延迟200ms
- 长消息（一大段文字）：延迟1500ms
- 犹豫的消息：延迟3000ms

结合"正在输入..."动画，玩家会感受到好像真的有人在打字，极大增强代入感。

**`msgOptionsDelayMS`的设计意图**：

选项（玩家的回复）不和消息一起出现，而是额外延迟。这给玩家一点时间先看完消息，再做选择，符合真实的聊天节奏。

## 三、MemoryPackOrder与序列化稳定性

```csharp
[MemoryPackOrder(0)]  public List<int> choiceIds;
[MemoryPackOrder(1)]  public List<string> choiceNames;
[MemoryPackOrder(2)]  public int senderID;
[MemoryPackOrder(3)]  public bool reject;
// ...跳过一大段...
[MemoryPackOrder(101)] public bool msgRead;
[MemoryPackOrder(102)] public long msgDelayMS;
```

注意顺序号跳跃：从3直接跳到101。这是有意为之——中间的100个号码（4-100）是预留给`SendPhoneMsgNode`基类未来可能新增的字段。

子类`SendTextNode`使用了`[MemoryPackOrder(3)]`：
```csharp
// SendTextNode继承SendPhoneMsgNode，自己的字段从3开始
[MemoryPackOrder(3)] public int phoneTextID = 0;
```

这里有个设计考量：子类和基类使用相同的序号空间（MemoryPack的继承序列化）。基类预留了大量空间（3-100给基类，101+给基类扩展）确保子类不会与基类产生冲突。

**为什么要用MemoryPack而不是JSON？**

节点图数据可能非常大（一个剧情章节有几百个节点），MemoryPack的二进制格式比JSON：
- 序列化速度快10倍以上
- 存储空间小3-5倍
- 反序列化速度更快（不需要解析文本）

## 四、Editor预览功能

```csharp
#if UNITY_EDITOR
protected override void OnNodeGUI()
{
    base.OnNodeGUI();
    
    // 在节点编辑器中直接显示消息内容预览
    var phoneTextCfg = CfgManager.tables.TbPhoneText.GetOrDefault(phoneTextID);
    if (phoneTextCfg == null)
    {
        // 红色报错提示（phoneTextID为0时）
        EditorGUILayout.LabelField(
            "<color=#FF0000>文字消息不能为0啊啊啊啊啊啊啊啊啊啊啊</color>");
    }
    else
    {
        // 显示消息的中文文本内容
        EditorGUILayout.LabelField(phoneTextCfg.Zh);
    }
}
#endif
```

在Unity Editor的节点图里，每个`SendTextNode`节点会直接显示消息内容的中文文本。这样策划在编辑剧情时，不需要去查配置表，直接在节点上就能看到每条消息写的什么，极大提升了编辑效率。

红色报错提示（`color=#FF0000`）是对策划的友好警告：phoneTextID为0是无效状态，策划必须填一个有效的消息ID。

## 五、多媒体消息节点的扩展

从文件列表可以看到，项目支持多种手机消息类型：

```
SendTextNode        → 发送文字消息
SendImageNode       → 发送图片
SendLinkNode        → 发送链接（类似微信卡片消息）
SendEmojiNode       → 发送表情包
VideoUINode         → 发送视频
ShortVideoNode      → 发送短视频
BulletScreenCommentNode → 发送弹幕评论
```

所有这些都继承自`SendPhoneMsgNode`，共享相同的基础能力（延迟、回复选项、跳过处理），但每种类型有自己的特定数据字段（比如`SendImageNode`有图片路径，`SendLinkNode`有URL和标题）。

这是**模板方法+继承**的完美应用场景。

## 六、outSelectionFlows：选项输出端口

```csharp
public ListComponent<FlowOutput> outSelectionFlows = ListComponent<FlowOutput>.Create();
```

每个回复选项对应图中的一条输出连线（`FlowOutput`）。节点的"选项输出端口"数量等于`choiceIds.Count`。

当玩家选择了选项2，代码会激活`outSelectionFlows[2]`，图引擎沿着这条连线执行下一个节点。

这就是"分支对话"的实现原理：
```
消息节点 ──── 选项1（同意） ──── 下一段剧情A
          └── 选项2（拒绝） ──── 下一段剧情B
          └── 选项3（不回复） ── 下一段剧情C
```

## 七、跳过机制的设计

```csharp
public bool skipAsDefault = false;
```

手机剧情可能有大量对话，玩家可以选择"跳过"。跳过时：
1. 遍历所有手机消息节点
2. 有`skipAsDefault=true`的节点选择该路径（相当于自动选了最中性/默认的回复）
3. 把所有跳过的消息都标记为`msgRead=true`（已读，不显示未读消息数）
4. 存储到手机对话记录里（即使跳过，以后打开手机仍然能看到历史消息）

这保证了：跳过剧情不会导致游戏状态出错，只是不看剧情演出，功能依然正常推进。

## 八、音效联动

```csharp
public class PhoneConst
{
    // 界面外手机收到消息（震动提示音）
    public static int Play_ui_system_phone_message_receive_outside = 30118;
    
    // 手机界面收到消息（收到消息音效）
    public static int Play_ui_system_phone_message_receive_inside = 30119;
    
    // 手机界面发送消息（发送成功音效）
    public static int Play_ui_system_phone_message_send_inside = 30120;
    
    // 手机界面选择对话选项
    public static int Play_ui_system_phone_message_select_inside = 30121;
}
```

常量都是Wwise事件ID（30118等），不是字符串，避免硬编码字符串导致的拼写错误和重构困难。

## 九、总结

手机消息剧情节点系统展示了几个优秀的工程实践：

1. **节点特性驱动**：Color、Name、Category完全通过特性描述，节点编辑器根据特性渲染
2. **MemoryPack序列化**：高性能序列化，字段顺序稳定
3. **延迟机制**：消息延迟+选项延迟，用技术手段制造真实的聊天节奏感
4. **Editor预览**：OnNodeGUI在节点上直接显示内容，策划无需查配置表
5. **跳过兼容**：skipAsDefault设计让跳过剧情不影响游戏功能

对新手来说，"图形化节点编辑+代码实现"是现代游戏内容工具的标准模式，理解这套模式能大大提升团队内容生产效率。
