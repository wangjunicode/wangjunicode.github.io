---
title: 我的游戏开发之路（二）：初入职场，从「会用」到「理解」
published: 2018-09-01
description: "2018年毕业，进入第一家游戏公司。技术环境：Unity + C# + Protobuf + TCP 网络通信。这篇记录初入职场的一年：如何快速适应真实项目、理解网络通信全链路、在 Code Review 中被击碎又重建的过程。"
tags: [成长记录, 游戏开发, Unity, 网络通信, Protobuf]
category: 成长记录
draft: false
---

> 系列第二篇。2018年，毕业，入职第一家游戏公司。

## 真实项目和自己练手完全不一样

入职第一周，我打开项目工程，看到几十万行代码、几千个文件，有一种强烈的感觉：

**我之前学的东西，在这里完全找不到。**

自己写过的小游戏：一个 `GameManager`，几百行。  
真实项目：十几个子系统，每个子系统独立的数据层/逻辑层/表现层，模块间通过消息总线通信，Lua 脚本热更新，协议用 Protobuf 定义……

第一个月，我基本是在「读代码」。不敢改，怕改坏。

后来组长告诉我一句话，让我转变了思路：

> "不用怕改坏，有版本控制。你不去改代码，就永远搞不懂代码。"

---

## Protobuf：我第一次认真学「序列化」

项目使用 Protobuf 作为网络协议的序列化格式。在这之前，我对序列化的理解仅限于 `JsonUtility.ToJson()`。

### 为什么不用 JSON？

```
相同数据：{ "userId": 12345, "name": "PlayerA", "level": 10 }

JSON  编码：{"userId":12345,"name":"PlayerA","level":10}  → 约 47 字节
Protobuf  → 约 18 字节，且解析速度快 5-10 倍
```

游戏服务器每秒处理几千个玩家的消息，这个差距就变得非常显著。

### Protobuf 的编码原理

学 Protobuf 的时候，我第一次认真看了二进制编码：

```
// .proto 定义
message PlayerInfo {
    int32 userId = 1;    // 字段编号 1
    string name  = 2;    // 字段编号 2
    int32 level  = 3;    // 字段编号 3
}

// 实际编码（Varint）：
// 小数字用更少字节。数字 1 只需 1 字节，而不是固定 4 字节
```

这让我第一次理解了「二进制协议的设计哲学」：**不存储字段名，只存字段编号；数字尽量压缩**。

### Unity 中集成

```csharp
// 序列化：对象 → 字节流
PlayerInfo info = new PlayerInfo { UserId = 12345, Name = "PlayerA", Level = 10 };
byte[] bytes = info.ToByteArray();

// 反序列化：字节流 → 对象
PlayerInfo parsed = PlayerInfo.Parser.ParseFrom(bytes);

// 关键注意：Type.GetType 需要带程序集名
Type t = Type.GetType("Romsg.PlayerInfo, Common"); // ✅
Type t = Type.GetType("Romsg.PlayerInfo");          // ❌ 找不到
```

最后一个坑踩了很久——在不同程序集之间用 `Type.GetType` 反射获取类型时，必须带上程序集名称。这是后来在实际项目中踩到的。

---

## 网络通信：从「发消息」到理解全链路

项目里发一条消息给服务器，表面上只是一行代码：

```csharp
NetworkManager.Send(new LoginReq { Account = account });
```

但背后的完整链路，我花了将近三个月才真正搞清楚：

```
应用层：构造 Protobuf 消息对象
    ↓
序列化层：ToByteArray() → byte[]
    ↓
封包层：[4字节长度][2字节消息ID][n字节正文]
    ↓
TCP 发送：Socket.Send()
    ↓ ← 网络传输
TCP 接收：粘包/拆包处理（按长度字段拆分完整消息）
    ↓
反序列化：按消息 ID 找对应 Parser，ParseFrom()
    ↓
消息分发：EventSystem.Emit(msgId, msgObject)
    ↓
业务逻辑：处理 LoginRsp，跳转场景
```

**粘包/拆包**是当时觉得最难理解的地方：

TCP 是流式协议，不保证消息边界。你发了两条 100 字节的消息，对方可能收到：一次 200 字节（粘包），也可能收到一次 50 字节和一次 150 字节（拆包）。

解决方案：**消息头携带长度字段**，接收方按长度拆分。

```csharp
// 接收缓冲区处理（简化版）
void ProcessBuffer(byte[] buffer, int length) {
    while (bufferOffset + 4 <= length) {
        int msgLen = BitConverter.ToInt32(buffer, bufferOffset);
        if (bufferOffset + msgLen > length) break; // 不够一条完整消息，等下次
        ProcessMessage(buffer, bufferOffset, msgLen);
        bufferOffset += msgLen;
    }
}
```

这个逻辑后来在项目里写过好几个版本，每次都会有新的边界情况要处理。

---

## 第一次参与「上线」

工作第四个月，参与了一个小功能的上线：排行榜 UI。

功能本身不复杂，但上线流程让我第一次感受到「生产环境」和「开发环境」的区别：

- 本地测试通过了，真机上会有 UI 适配问题
- 功能 A 改了，功能 B 莫名其妙挂了（依赖没梳理清楚）
- 合并代码时冲突，解决完发现逻辑被覆盖了一半

每一个问题都让我更理解「为什么项目要有规范」。

代码规范、分支管理、测试用例……这些在学校看起来像「形式主义」的东西，在多人协作的真实项目里，是保命的基础设施。

---

## 这一年最重要的认知转变

从学生到职场，最大的变化不是技术，而是**对「完成」的定义变了**：

- **学生时期**：代码能跑 = 完成
- **职场第一年**：代码能跑、别人能读懂、改动不破坏其他功能 = 完成

这个标准提高了三倍，但也让代码质量提高了三倍。

---

## 给同样在起点的人

如果你刚毕业准备入职游戏公司，几个实际的建议：

1. **先读懂现有代码，再写新代码**。不要上来就想「重构」，先搞懂为什么这样写。
2. **遇到不懂的，不要只靠搜索**。找组里的人聊，10 分钟能解决搜索 2 小时解决不了的问题。
3. **把每天遇到的问题记录下来**。一个月后回头看，你会发现自己进步了多少。
4. **不要害怕改坏代码**。有版本控制，改错了回滚。不去改，就永远不会真正理解。

---

*下一篇：[我的游戏开发之路（三）：初级到中级，技术深度的跨越](/posts/游戏开发成长记录-03/)*
