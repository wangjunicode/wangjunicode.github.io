---
title: 关于计算机网络-Protobuf
published: 2018-09-17
description: "深入介绍 Protocol Buffers（Protobuf）：序列化原理、.proto 文件语法、字段编码格式（Varint/Length-Delimited）、与 JSON 的对比，以及在 Unity + C# 游戏项目中的实践应用。"
tags: [游戏开发, 网络同步, C#]
category: 网络同步
draft: false
---

## 概述

Protocol Buffers（简称 Protobuf）是 Google 开源的一种高效、紧凑的结构化数据序列化格式，广泛用于游戏网络通信协议和配置数据存储。相比 JSON/XML，Protobuf 的序列化体积更小、解析速度更快，是网络游戏服务端通信的主流选择之一。

---

## 一、为什么选择 Protobuf

### 与 JSON 对比

| 维度 | JSON | Protobuf |
|------|------|---------|
| 格式 | 文本，人可读 | 二进制，不可直接读 |
| 包体大小 | 较大（字段名随数据传输） | 小（字段用数字 tag 标识）|
| 解析速度 | 慢（文本解析） | 快（二进制直接映射） |
| 强类型 | 弱（JS 无类型） | 强（.proto 定义类型） |
| 版本兼容 | 需手动处理 | 内置向前/向后兼容 |
| 调试 | 方便 | 需工具辅助 |

实际测试中，相同数据 Protobuf 包体约为 JSON 的 1/3 到 1/5，解析速度提升 3~10 倍。对于网络游戏而言，减少带宽消耗、降低网络延迟意义重大。

---

## 二、.proto 文件语法

### 基础结构

```protobuf
// 指定语法版本（推荐 proto3）
syntax = "proto3";

// 包名（用于 C# namespace）
package game.proto;

option csharp_namespace = "Game.Proto";

// 消息定义
message PlayerInfo {
    int32  player_id   = 1;   // 字段编号（Tag），1~15 用 1 字节编码，推荐给高频字段
    string player_name = 2;
    int32  level       = 3;
    float  hp          = 4;
    float  max_hp      = 5;
    repeated ItemInfo items = 6;  // 列表类型
}

message ItemInfo {
    int32 item_id  = 1;
    int32 count    = 2;
    ItemType type  = 3;
}

// 枚举
enum ItemType {
    ITEM_NONE     = 0;   // proto3 中第一个枚举值必须为 0
    ITEM_WEAPON   = 1;
    ITEM_ARMOR    = 2;
    ITEM_CONSUME  = 3;
}
```

### 常用数据类型

| .proto 类型 | C# 类型 | 说明 |
|------------|---------|------|
| `int32` | `int` | 小整数用 Varint 编码，负数效率低 |
| `sint32` | `int` | 有符号整数，负数用 ZigZag 编码，效率更高 |
| `int64` | `long` | 64 位整数 |
| `float` | `float` | 32 位浮点 |
| `double` | `double` | 64 位浮点 |
| `bool` | `bool` | 布尔值 |
| `string` | `string` | UTF-8 字符串 |
| `bytes` | `ByteString` | 任意字节流 |
| `repeated` | `List<T>` | 列表 |
| `map<K,V>` | `Dictionary<K,V>` | 键值对 |
| `oneof` | - | 多种类型中只有一个有值（Union） |

### 网络消息封装（常见游戏协议设计）

```protobuf
// 通用消息包装（外层协议头）
message NetMessage {
    int32  msg_id     = 1;  // 消息 ID，用于分发到对应处理器
    int32  seq        = 2;  // 序列号，用于请求/响应匹配
    bytes  payload    = 3;  // 实际消息体（对应各具体消息序列化后的字节）
    int32  error_code = 4;  // 错误码（响应时使用）
}

// 登录请求
message C2S_Login {
    string account  = 1;
    string token    = 2;
    string version  = 3;
    int32  platform = 4;
}

// 登录响应
message S2C_Login {
    int32      result      = 1;  // 0=成功
    PlayerInfo player_info = 2;
    string     server_time = 3;
}
```

---

## 三、字段编码原理

### Varint 编码

Protobuf 对整数使用 Variable-length Integer（可变长整型）编码：数字越小，占用字节越少。

编码规则：每个字节的最高位（MSB）是延续标志位：
- MSB = 1：后面还有字节
- MSB = 0：最后一个字节

```
数字 300 的 Varint 编码：
300 = 0b100101100
拆分为 7 位一组（从低到高）：
  低 7 位：0101100（44）  → 加上延续位：10101100 = 0xAC
  高 7 位：0000010（2）   → 最后一组：00000010 = 0x02
编码结果：AC 02（2 字节）
```

这就是为什么小数值占用字节少，而大数值（>2^28）才用 5 字节。

### Wire Type（线类型）

每个字段传输时携带 `Tag`，格式为 `(field_number << 3) | wire_type`：

| Wire Type | 值 | 类型 |
|-----------|---|------|
| Varint | 0 | int32/bool/enum |
| 64-bit | 1 | double/fixed64 |
| Length-delimited | 2 | string/bytes/message/repeated |
| 32-bit | 5 | float/fixed32 |

```
以 player_id = 1 的字段 Tag 计算：
field_number = 1，wire_type = 0（Varint）
Tag = (1 << 3) | 0 = 8 = 0x08
```

理解编码原理有助于：
- 合理分配字段编号（1~15 常用字段，16~2047 不常用字段）
- 理解为什么负数 `int32` 效率低（负数 Varint 占 10 字节，应用 `sint32`）

---

## 四、在 Unity C# 项目中使用 Protobuf

### 安装

推荐使用 `protobuf-net`（纯 C# 实现，Unity 兼容性好）或 `Google.Protobuf`（官方 C# 实现）。

NuGet / Package Manager 安装：
```
com.google.protobuf（官方）
或
protobuf-net（社区，支持标注方式）
```

### 代码生成

安装 `protoc` 编译器，生成 C# 代码：

```bash
# 生成 C# 代码
protoc --csharp_out=./Assets/Scripts/Proto --proto_path=./Proto *.proto
```

推荐将 protoc 生成步骤集成到 Editor 工具中，做到 .proto 文件改动后自动重新生成。

### 序列化与反序列化

```csharp
using Google.Protobuf;
using Game.Proto;

// 序列化（对象 → 字节数组）
PlayerInfo player = new PlayerInfo
{
    PlayerId   = 10001,
    PlayerName = "WangJun",
    Level      = 50,
    Hp         = 1000f,
    MaxHp      = 1000f
};

// 方式1：序列化到字节数组
byte[] data = player.ToByteArray();

// 方式2：序列化到 Stream（网络发送）
using var stream = new MemoryStream();
player.WriteTo(stream);
byte[] bytes = stream.ToArray();

// 反序列化（字节数组 → 对象）
PlayerInfo received = PlayerInfo.Parser.ParseFrom(data);
Debug.Log($"PlayerName: {received.PlayerName}, Level: {received.Level}");
```

### 网络消息分发（游戏常见模式）

```csharp
// 消息处理器注册
public class NetMessageDispatcher
{
    private Dictionary<int, Action<byte[]>> _handlers = new();
    
    public void Register<T>(int msgId, Action<T> handler) where T : IMessage<T>, new()
    {
        _handlers[msgId] = (bytes) =>
        {
            var msg = new MessageParser<T>(() => new T()).ParseFrom(bytes);
            handler(msg);
        };
    }
    
    public void Dispatch(int msgId, byte[] payload)
    {
        if (_handlers.TryGetValue(msgId, out var handler))
            handler(payload);
        else
            Debug.LogWarning($"No handler for msgId: {msgId}");
    }
}

// 注册和使用
var dispatcher = new NetMessageDispatcher();
dispatcher.Register<S2C_Login>(MsgId.LOGIN_RESPONSE, OnLoginResponse);

void OnLoginResponse(S2C_Login response)
{
    if (response.Result == 0)
        Debug.Log($"Login success: {response.PlayerInfo.PlayerName}");
}
```

---

## 五、向前/向后兼容性

Protobuf 的兼容性设计是其核心优势之一，在游戏热更新场景下非常重要：

**安全操作**（不破坏兼容性）：
- ✅ 新增字段（旧版本会忽略未知字段）
- ✅ 将 `optional` 字段变为 `repeated`
- ✅ 修改字段名（字段名不参与编码，只有 Tag 编号参与）

**危险操作**（会破坏兼容性）：
- ❌ 修改字段编号（Tag）
- ❌ 修改字段类型（可能导致解析错误）
- ❌ 删除字段后复用其编号（已废弃字段用 `reserved` 声明保留）

```protobuf
message PlayerInfo {
    int32  player_id   = 1;
    string player_name = 2;
    // 字段 3 已废弃，保留编号防止被复用
    reserved 3;
    reserved "old_field_name";
    
    int32  level = 4;  // 新增字段，旧版本客户端会忽略
}
```

---

## 总结

| 特性 | 说明 |
|------|------|
| 序列化格式 | 二进制，Varint + Length-Delimited |
| 包体大小 | 约为 JSON 的 1/3~1/5 |
| 兼容性 | 字段编号不变则向前/向后兼容 |
| 适用场景 | 网络通信协议、配置数据序列化 |
| Unity 支持 | Google.Protobuf 或 protobuf-net |

Protobuf 是游戏网络通信的利器，理解其编码原理有助于合理设计协议结构，在字段编号分配、类型选择（`int32` vs `sint32`）等细节上做出正确决策。
