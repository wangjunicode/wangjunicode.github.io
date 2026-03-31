---
title: 游戏网络协议设计：Protobuf与自定义二进制协议对比
published: 2026-03-31
description: 深度解析游戏客户端网络协议的设计选型，涵盖 Protobuf 3.0 协议设计规范、自定义二进制协议编解码实现、消息帧格式设计、协议版本管理与兼容性、TCP/KCP/WebSocket 的适用场景，以及游戏协议性能基准测试。
tags: [Unity, 网络协议, Protobuf, TCP, 游戏开发]
category: 网络同步
draft: false
---

## 一、协议选型对比

| 协议方案 | 编解码速度 | 消息大小 | 易用性 | 版本兼容 | 适用场景 |
|----------|-----------|----------|--------|----------|----------|
| JSON | 慢 | 大 | 最好 | 好 | 配置/调试API |
| MessagePack | 快 | 小 | 好 | 好 | 通用数据传输 |
| Protobuf 3 | 很快 | 很小 | 中 | 极好 | 高性能游戏通信 |
| FlatBuffers | 极快（零拷贝）| 最小 | 差 | 中 | 极高性能场景 |
| 自定义二进制 | 最快 | 最小 | 最差 | 需手动管理 | 帧同步/实时战斗 |

---

## 二、游戏消息帧格式设计

```
自定义消息帧格式（固定头 + 变长消息体）：

+--------+--------+--------+--------+----------+----------+
| Length |  MsgId | SeqNum | Flags  | Checksum | Payload  |
|  4字节  |  2字节  |  4字节  |  1字节  |   2字节   |  变长    |
+--------+--------+--------+--------+----------+----------+

Length:   消息体长度（不含帧头）
MsgId:    消息类型ID（0-65535）
SeqNum:   序列号（请求/响应配对）
Flags:    压缩标志(bit0)、加密标志(bit1)、是否需要ACK(bit2)
Checksum: CRC16校验（Header + Payload）
Payload:  实际消息数据
```

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

/// <summary>
/// 自定义游戏网络协议编解码器
/// </summary>
public class GameProtocolCodec
{
    // 帧头大小：4(length) + 2(msgId) + 4(seqNum) + 1(flags) + 2(checksum) = 13字节
    private const int HEADER_SIZE = 13;
    private const int MAX_PAYLOAD_SIZE = 65535;

    public class MessageFrame
    {
        public ushort MsgId;
        public uint SeqNum;
        public byte Flags;
        public byte[] Payload;
        
        public bool IsCompressed  => (Flags & 0x01) != 0;
        public bool IsEncrypted   => (Flags & 0x02) != 0;
        public bool RequiresAck   => (Flags & 0x04) != 0;
    }

    [Flags]
    public enum FrameFlags : byte
    {
        None       = 0,
        Compressed = 1 << 0,
        Encrypted  = 1 << 1,
        RequireAck = 1 << 2,
    }

    private uint nextSeqNum = 1;

    /// <summary>
    /// 编码消息为字节数组
    /// </summary>
    public byte[] Encode(ushort msgId, byte[] payload, FrameFlags flags = FrameFlags.None)
    {
        if (payload == null) payload = Array.Empty<byte>();
        if (payload.Length > MAX_PAYLOAD_SIZE)
            throw new InvalidOperationException($"Payload too large: {payload.Length}");
        
        byte[] processedPayload = payload;
        
        // 压缩（超过阈值才压缩）
        if ((flags & FrameFlags.Compressed) != 0 && payload.Length > 512)
        {
            processedPayload = Compress(payload);
            // 如果压缩后更大，取消压缩标志
            if (processedPayload.Length >= payload.Length)
            {
                processedPayload = payload;
                flags &= ~FrameFlags.Compressed;
            }
        }
        
        // 加密
        if ((flags & FrameFlags.Encrypted) != 0)
        {
            processedPayload = Encrypt(processedPayload);
        }
        
        uint seqNum = nextSeqNum++;
        int totalSize = HEADER_SIZE + processedPayload.Length;
        byte[] frame = new byte[totalSize];
        
        using var writer = new BinaryWriter(new MemoryStream(frame));
        
        // Length（不含帧头本身的Length字段，但含其他头字段）
        writer.Write((uint)(processedPayload.Length + HEADER_SIZE - 4));
        writer.Write(msgId);
        writer.Write(seqNum);
        writer.Write((byte)flags);
        
        // Checksum（先写0，计算后填入）
        int checksumOffset = (int)writer.BaseStream.Position;
        writer.Write((ushort)0);
        
        writer.Write(processedPayload);
        
        // 计算并写入 CRC16
        ushort checksum = Crc16(frame, 0, totalSize);
        BitConverter.GetBytes(checksum).CopyTo(frame, checksumOffset);
        
        return frame;
    }

    /// <summary>
    /// 解码接收到的字节流（处理粘包/拆包）
    /// </summary>
    public List<MessageFrame> Decode(byte[] buffer, int offset, int length, 
        out int consumedBytes)
    {
        var frames = new List<MessageFrame>();
        consumedBytes = 0;
        int pos = offset;
        
        while (pos + HEADER_SIZE <= offset + length)
        {
            // 读取 Length
            uint frameBodyLen = BitConverter.ToUInt32(buffer, pos);
            int fullFrameSize = (int)frameBodyLen + 4; // +4 for Length field itself
            
            // 检查是否有完整的帧数据
            if (pos + fullFrameSize > offset + length)
                break; // 数据不完整，等下次
            
            // 验证 CRC16
            ushort storedChecksum = BitConverter.ToUInt16(buffer, pos + 11);
            // 将校验和字段暂时设为0再计算
            buffer[pos + 11] = buffer[pos + 12] = 0;
            ushort calculatedChecksum = Crc16(buffer, pos, fullFrameSize);
            buffer[pos + 11] = (byte)(storedChecksum & 0xFF);
            buffer[pos + 12] = (byte)(storedChecksum >> 8);
            
            if (calculatedChecksum != storedChecksum)
            {
                Debug.LogError($"[Codec] Checksum mismatch! Discarding frame.");
                pos += fullFrameSize;
                consumedBytes += fullFrameSize;
                continue;
            }
            
            // 解析帧头
            ushort msgId = BitConverter.ToUInt16(buffer, pos + 4);
            uint seqNum = BitConverter.ToUInt32(buffer, pos + 6);
            byte flags = buffer[pos + 10];
            
            int payloadSize = (int)frameBodyLen - HEADER_SIZE + 4;
            byte[] payload = new byte[payloadSize];
            Buffer.BlockCopy(buffer, pos + HEADER_SIZE, payload, 0, payloadSize);
            
            // 解密
            if ((flags & 0x02) != 0)
                payload = Decrypt(payload);
            
            // 解压
            if ((flags & 0x01) != 0)
                payload = Decompress(payload);
            
            frames.Add(new MessageFrame
            {
                MsgId = msgId,
                SeqNum = seqNum,
                Flags = flags,
                Payload = payload
            });
            
            pos += fullFrameSize;
            consumedBytes += fullFrameSize;
        }
        
        return frames;
    }

    // CRC16 实现（MODBUS CRC）
    ushort Crc16(byte[] data, int offset, int length)
    {
        ushort crc = 0xFFFF;
        for (int i = offset; i < offset + length; i++)
        {
            crc ^= data[i];
            for (int j = 0; j < 8; j++)
            {
                if ((crc & 0x0001) != 0)
                    crc = (ushort)((crc >> 1) ^ 0xA001);
                else
                    crc >>= 1;
            }
        }
        return crc;
    }

    byte[] Compress(byte[] data)
    {
        using var ms = new MemoryStream();
        using var gz = new System.IO.Compression.GZipStream(ms, 
            System.IO.Compression.CompressionMode.Compress);
        gz.Write(data, 0, data.Length);
        gz.Close();
        return ms.ToArray();
    }

    byte[] Decompress(byte[] data)
    {
        using var ms = new MemoryStream(data);
        using var gz = new System.IO.Compression.GZipStream(ms, 
            System.IO.Compression.CompressionMode.Decompress);
        using var result = new MemoryStream();
        gz.CopyTo(result);
        return result.ToArray();
    }

    // 简化的加密（实际项目使用 AES-GCM）
    byte[] Encrypt(byte[] data) => data;
    byte[] Decrypt(byte[] data) => data;
}
```

---

## 三、消息派发系统

```csharp
/// <summary>
/// 网络消息派发器
/// </summary>
public class NetworkMessageDispatcher
{
    private Dictionary<ushort, List<Action<byte[]>>> handlers 
        = new Dictionary<ushort, List<Action<byte[]>>>();
    
    // 待处理的消息队列（工作线程 → 主线程）
    private Queue<(ushort, byte[])> pendingMessages = new Queue<(ushort, byte[])>();
    private readonly object queueLock = new object();

    /// <summary>
    /// 注册消息处理器
    /// </summary>
    public void Register<T>(ushort msgId, Action<T> handler) where T : class, new()
    {
        if (!handlers.ContainsKey(msgId))
            handlers[msgId] = new List<Action<byte[]>>();
        
        handlers[msgId].Add(payload =>
        {
            // 反序列化消息
            T msg = DeserializeMessage<T>(payload);
            handler?.Invoke(msg);
        });
    }

    /// <summary>
    /// 接收来自工作线程的消息（入队）
    /// </summary>
    public void EnqueueMessage(ushort msgId, byte[] payload)
    {
        lock (queueLock)
            pendingMessages.Enqueue((msgId, payload));
    }

    /// <summary>
    /// 主线程处理消息（在 Update 中调用）
    /// </summary>
    public void ProcessPending()
    {
        while (true)
        {
            (ushort msgId, byte[] payload) msg;
            lock (queueLock)
            {
                if (pendingMessages.Count == 0) break;
                msg = pendingMessages.Dequeue();
            }
            
            if (handlers.TryGetValue(msg.msgId, out var handlerList))
            {
                foreach (var handler in handlerList)
                {
                    try { handler(msg.payload); }
                    catch (Exception e) { Debug.LogError($"Handler error: {e.Message}"); }
                }
            }
        }
    }

    T DeserializeMessage<T>(byte[] payload) where T : class, new()
    {
        // 使用 Protobuf 或 MessagePack 反序列化
        // Google.Protobuf.MessageParser<T>.ParseFrom(payload);
        return new T(); // 简化
    }
}

/// <summary>
/// 消息 ID 定义（避免魔法数字）
/// </summary>
public static class MessageId
{
    // 基础
    public const ushort Ping              = 0x0001;
    public const ushort Pong              = 0x0002;
    public const ushort Heartbeat         = 0x0003;
    
    // 认证
    public const ushort LoginRequest      = 0x0101;
    public const ushort LoginResponse     = 0x0102;
    
    // 游戏
    public const ushort PlayerMoveInput   = 0x0201;
    public const ushort PlayerStateSync   = 0x0202;
    public const ushort SkillCast         = 0x0203;
    public const ushort DamageNotify      = 0x0204;
    public const ushort ChatMessage       = 0x0301;
}
```

---

## 四、协议版本管理

```csharp
/// <summary>
/// 协议版本握手
/// </summary>
public class ProtocolVersionNegotiator
{
    private const int CURRENT_PROTOCOL_VERSION = 3;
    private const int MIN_SUPPORTED_VERSION = 2;
    
    public bool IsVersionCompatible(int serverVersion)
    {
        // 客户端支持服务端版本范围
        return serverVersion >= MIN_SUPPORTED_VERSION && 
               serverVersion <= CURRENT_PROTOCOL_VERSION;
    }
    
    public void HandleVersionMismatch(int serverVersion)
    {
        if (serverVersion > CURRENT_PROTOCOL_VERSION)
        {
            // 服务器版本更新，客户端需要更新
            UIManager.Instance?.ShowUpdateRequiredDialog();
        }
        else if (serverVersion < MIN_SUPPORTED_VERSION)
        {
            // 服务器版本太旧
            UIManager.Instance?.ShowMessage("服务器维护中，请稍后再试");
        }
    }
}
```

---

## 五、KCP vs TCP 选型指南

| 场景 | 推荐协议 | 原因 |
|------|----------|------|
| 实时对战（帧同步） | KCP（UDP Based） | 低延迟，可控重传 |
| 聊天/普通逻辑 | TCP | 可靠，有序 |
| 视频/语音 | WebRTC | 专为多媒体设计 |
| Web客户端 | WebSocket | 浏览器兼容 |
| 局域网游戏 | UDP Raw | 极低开销 |

**KCP 配置参数：**
```
// KCP 激进模式（低延迟）
kcp.NoDelay(1, 10, 2, 1)
// nodelay=1: 启用无延迟模式
// interval=10: 内部时钟间隔 10ms
// resend=2: 快速重传
// nc=1: 关闭流控
```
