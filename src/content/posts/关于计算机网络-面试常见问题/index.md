---
title: Protobuf 原理与 Unity 网络通信实践
published: 2018-09-17
description: "深入理解 Protobuf 的编码原理（Varint/TLV）、相比 JSON 的性能优势，以及在 Unity 客户端中集成 Protobuf 实现游戏网络通信的完整方案。"
tags: [游戏开发, 网络通信, Protobuf, Unity, C#]
category: 网络通信
draft: false
---

## 为什么选择 Protobuf

在游戏网络通信中，序列化格式的选择直接影响带宽消耗和解析性能。

| 格式 | 编码 | 典型大小 | 解析速度 | 可读性 |
|------|------|---------|---------|--------|
| JSON | 文本 | 大 | 慢 | 高 |
| XML  | 文本 | 最大 | 最慢 | 高 |
| **Protobuf** | 二进制 | 小（3-10x） | 快（5-10x） | 低 |
| MessagePack | 二进制 | 小 | 快 | 低 |

Protobuf 在游戏场景的优势：
- 二进制体积小，节省带宽（移动端尤为重要）
- 解析速度快，减少 CPU 开销
- 强类型 schema，接口契约清晰，减少字段误用
- 跨语言支持（C#客户端 / C++服务端 / Go服务端）

---

## Protobuf 编码原理

### 字段编码格式：TLV

每个字段由 `Tag + Length + Value` 组成（部分类型省略 Length）：

```
Tag = (field_number << 3) | wire_type

wire_type:
  0 = Varint        (int32, int64, bool, enum)
  1 = 64-bit        (fixed64, double)
  2 = Length-delimited (string, bytes, message, repeated)
  5 = 32-bit        (fixed32, float)
```

### Varint 变长整数编码

小数字用更少字节表示，节省空间：

```
数字 1    → 0x01         (1 字节)
数字 300  → 0xAC 0x02    (2 字节)
数字 1    不需要补零到 4 字节（不像 int32 固定 4 字节）
```

**每个字节最高位为延续标志位**（1=后面还有字节，0=结束）：

```
300 的二进制：100101100
分割成7位组：0000010  0101100
加延续位：   0000010  1 + 0101100
小端序：     10101100 00000010 = 0xAC 0x02
```

---

## .proto 文件定义

```protobuf
syntax = "proto3";
package Romsg;

// 登录请求
message LoginReq {
    string account  = 1;
    string password = 2;
    int32  platform = 3;  // 0=iOS 1=Android 2=PC
}

// 登录响应
message LoginRsp {
    int32  errorCode = 1;
    string token     = 2;
    int64  userId    = 3;
    PlayerInfo playerInfo = 4;  // 嵌套消息
}

message PlayerInfo {
    int64  uid      = 1;
    string name     = 2;
    int32  level    = 3;
    repeated int32 equips = 4;  // 数组
}
```

---

## Unity 集成 Protobuf-net

### 安装

推荐使用 `protobuf-net`（C# 友好）或官方 `Google.Protobuf`：

```bash
# NuGet 安装
dotnet add package Google.Protobuf
dotnet add package Grpc.Tools  # 用于生成 C# 代码
```

### 序列化与反序列化

```csharp
using Google.Protobuf;

// 序列化：Message → byte[]
LoginReq req = new LoginReq {
    Account  = "player001",
    Password = "hash_xxx",
    Platform = 1
};
byte[] bytes = req.ToByteArray();

// 反序列化：byte[] → Message
LoginRsp rsp = LoginRsp.Parser.ParseFrom(bytes);
Debug.Log($"UserId: {rsp.UserId}, Token: {rsp.Token}");
```

### 封装网络消息

```csharp
// 消息头 + 消息体的封包格式
// [4字节 总长度][2字节 消息ID][n字节 Protobuf正文]
public static byte[] Pack(ushort msgId, IMessage msg) {
    byte[] body = msg.ToByteArray();
    byte[] packet = new byte[6 + body.Length];
    // 写总长度
    BitConverter.GetBytes(packet.Length).CopyTo(packet, 0);
    // 写消息ID
    BitConverter.GetBytes(msgId).CopyTo(packet, 4);
    // 写正文
    body.CopyTo(packet, 6);
    return packet;
}

// 解包
public static (ushort msgId, byte[] body) Unpack(byte[] packet) {
    ushort msgId = BitConverter.ToUInt16(packet, 4);
    byte[] body  = new byte[packet.Length - 6];
    Array.Copy(packet, 6, body, 0, body.Length);
    return (msgId, body);
}
```

---

## 消息分发机制

```csharp
// 消息 ID → 对应 Parser 的注册表
private static Dictionary<ushort, MessageParser> s_parsers = new();

public static void Register<T>(ushort msgId, MessageParser<T> parser)
    where T : IMessage<T>
{
    s_parsers[msgId] = parser;
}

// 收到网络数据后分发
public static void Dispatch(ushort msgId, byte[] body) {
    if (!s_parsers.TryGetValue(msgId, out var parser)) {
        Debug.LogWarning($"Unknown msgId: {msgId}");
        return;
    }
    var msg = parser.ParseFrom(body);
    EventSystem.Emit(msgId, msg);
}

// 注册示例
Register(MsgId.LoginRsp, LoginRsp.Parser);
Register(MsgId.EnterSceneRsp, EnterSceneRsp.Parser);
```

---

## 常见问题

### Type.GetType 找不到类型

```csharp
// ❌ 错误：只在当前程序集查找，找不到
Type t = Type.GetType("Romsg.LoginReq");

// ✅ 正确：指定程序集名称
Type t = Type.GetType("Romsg.LoginReq, Common");
```

### Protobuf 与对象池

频繁创建 Protobuf 消息对象会产生 GC 压力，可以配合对象池复用：

```csharp
// proto3 支持 Clear() 重置对象状态
LoginReq req = pool.Get<LoginReq>();
req.Clear();
req.Account = account;
// 使用完后归还池
pool.Return(req);
```

### 向后兼容

- **新增字段**：老版本会忽略未知字段，向后兼容
- **删除字段**：用 `reserved` 标记字段号，防止复用
- **修改字段类型**：不可随意修改，会导致解析错误

```protobuf
message PlayerInfo {
    reserved 5, 6;         // 已删除的字段号，禁止复用
    reserved "old_name";   // 已删除的字段名
}
```

---

## TCP/IP 五层模型回顾

```
应用层    HTTP / WebSocket / 自定义协议（Protobuf）
传输层    TCP（可靠） / UDP（低延迟）
网络层    IP 路由寻址
链路层    MAC 地址，局域网通信
物理层    网线、光纤、无线电波
```

游戏通信通常选择：
- **TCP**：MMO、回合制（可靠性优先）
- **UDP / KCP**：动作、格斗（延迟优先，应用层保序）
- **WebSocket**：H5游戏、部分移动端（穿透防火墙）
