---
title: 关于计算机网络-Protobuf
published: 2018-09-17
description: "Protocol Buffers（Protobuf）是 Google 开发的一种语言中立、平台中立的序列化数据格式，比 XML/JSON 更小、更快、更简单。"
tags: [网络编程, Protobuf, 序列化]
category: 网络编程
draft: false
encryptedKey:henhaoji123
---

## Protobuf 是什么

Protocol Buffers（Protobuf）是 Google 开发的一种 **语言中立、平台中立** 的序列化数据格式，广泛应用于网络通信和数据存储。

与 XML/JSON 相比，Protobuf 具有以下优势：
- **体积更小**：序列化后的二进制数据比 JSON 小 3~10 倍
- **速度更快**：序列化/反序列化速度比 JSON 快 20~100 倍
- **强类型**：通过 `.proto` 文件定义数据结构，代码生成工具自动生成强类型的序列化代码

## 核心原理

### varint 编码

Protobuf 使用 varint（可变长度整数编码）来压缩整数数据：

- 每个字节的最高位是标志位：`1` 表示后续还有字节，`0` 表示这是最后一个字节
- 值越小，使用的字节数越少（小于 128 的数字只占 1 个字节）

```text
示例：数字 300 的 varint 编码
300 = 0x012C
编码结果：10101100 00000010
```

### Key-Value 编码结构

消息序列化后为二进制流，每个字段对应一个 key-value 对：

```text
key = (field_number << 3) | wire_type
```

wire_type 类型：
| Wire Type | 含义 | 适用类型 |
|-----------|------|---------|
| 0 | Varint | int32, int64, bool, enum |
| 1 | 64-bit | fixed64, double |
| 2 | Length-delimited | string, bytes, message |
| 5 | 32-bit | fixed32, float |

### .proto 文件示例

```protobuf
syntax = "proto3";

message PlayerInfo {
    int32  player_id = 1;
    string name      = 2;
    int32  level     = 3;
    repeated string items = 4;  // 重复字段（数组）
}
```

## 在 Unity 中使用 Protobuf

Unity 项目中常用 `protobuf-net` 或 Google 官方的 `protoc` 生成 C# 代码：

```csharp
// 序列化
PlayerInfo player = new PlayerInfo { PlayerId = 1, Name = "张三", Level = 50 };
byte[] data = player.ToByteArray();

// 反序列化
PlayerInfo decoded = PlayerInfo.Parser.ParseFrom(data);
Debug.Log(decoded.Name);  // 张三
```

## 对比 JSON

| 特性 | Protobuf | JSON |
|------|---------|------|
| 数据格式 | 二进制 | 文本 |
| 可读性 | 差 | 好 |
| 数据大小 | 小 | 大 |
| 解析速度 | 快 | 慢 |
| 跨语言 | 是 | 是 |
| 需要 schema | 是 | 否 |

> 参考：[Protobuf 原理详解](https://zhuanlan.zhihu.com/p/561275099)
