---
title: 游戏框架网络工具集NetworkHelper与KHEncoding的XOR加密设计解析
published: 2026-04-06
description: 深入解析ET游戏框架中NetworkHelper网络地址工具与KHEncoding编解码工具类的完整实现，包括多网卡IP枚举、IPEndPoint解析、XOR流式加密原理、CheckSum校验算法，以及如何在游戏网络通信中构建轻量级安全防护层。
image: ''
tags: [Unity, 游戏框架, 网络编程, 加密, CSharp]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

游戏客户端网络编程往往面临两个基础需求：**网络地址的解析与管理**，以及**通信数据的基础安全防护**。ET 框架通过 `NetworkHelper` 和 `KHEncoding` 两个工具类，提供了轻量但实用的解决方案。

本文将完整解析这两个类的实现细节，重点剖析 XOR 加密的工程实践与适用边界。

---

## 一、NetworkHelper：网络地址工具集

### 1.1 多网卡 IP 枚举

```csharp
public static string[] GetAddressIPs()
{
    List<string> list = new List<string>();
    foreach (NetworkInterface networkInterface in NetworkInterface.GetAllNetworkInterfaces())
    {
        if (networkInterface.NetworkInterfaceType != NetworkInterfaceType.Ethernet)
        {
            continue;
        }
        foreach (UnicastIPAddressInformation add in networkInterface.GetIPProperties().UnicastAddresses)
        {
            list.Add(add.Address.ToString());
        }
    }
    return list.ToArray();
}
```

这个方法只枚举 `Ethernet` 类型的网卡，过滤掉了：
- 回环接口（Loopback，127.0.0.1）
- WiFi 无线网卡（Wireless80211）
- 虚拟网卡（如 VPN、Docker 网桥）
- PPP 拨号连接

这在游戏服务器端监听绑定时很常见：需要拿到物理以太网接口的 IP，避免意外绑定到虚拟接口。

**实际使用场景**：

```csharp
// 服务器启动时，打印所有可用的以太网 IP
string[] ips = NetworkHelper.GetAddressIPs();
foreach (string ip in ips)
{
    Log.Info($"可用监听地址: {ip}");
}
```

### 1.2 智能 DNS 解析（优先 IPv4）

```csharp
public static IPAddress GetHostAddress(string hostName)
{
    IPAddress[] ipAddresses = Dns.GetHostAddresses(hostName);
    IPAddress returnIpAddress = null;
    foreach (IPAddress ipAddress in ipAddresses)
    {
        returnIpAddress = ipAddress;
        if (ipAddress.AddressFamily == AddressFamily.InterNetwork)
        {
            return ipAddress; // 优先返回 IPv4
        }
    }
    return returnIpAddress; // 没有 IPv4 则返回最后一个（可能是 IPv6）
}
```

`Dns.GetHostAddresses` 可能返回 IPv4 和 IPv6 混合结果（如 `::1` 和 `127.0.0.1`）。这里的策略是**优先 IPv4**，只有当没有 IPv4 时才 fallback 到其他地址族。

对于游戏来说，IPv4 的兼容性更广（部分运营商 NAT 对 IPv6 支持不稳定），这个优先策略合理。

### 1.3 IPEndPoint 解析

```csharp
// 从 host + port 创建
public static IPEndPoint ToIPEndPoint(string host, int port)
{
    return new IPEndPoint(IPAddress.Parse(host), port);
}

// 从 "ip:port" 格式字符串解析
public static IPEndPoint ToIPEndPoint(string address)
{
    int index = address.LastIndexOf(':');
    string host = address.Substring(0, index);
    string p = address.Substring(index + 1);
    int port = int.Parse(p);
    return ToIPEndPoint(host, port);
}
```

注意使用 `LastIndexOf(':')` 而不是 `IndexOf(':')`，这是为了正确处理 **IPv6 地址**。IPv6 地址本身包含多个冒号（如 `[2001:db8::1]:8080`），用 `LastIndexOf` 才能正确分割最后的端口号。

### 1.4 UDP CONNRESET 修复（Windows 专属）

```csharp
public static void SetSioUdpConnReset(Socket socket)
{
    if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
    {
        return;
    }

    const uint IOC_IN = 0x80000000;
    const uint IOC_VENDOR = 0x18000000;
    const int SIO_UDP_CONNRESET = unchecked((int)(IOC_IN | IOC_VENDOR | 12));

    socket.IOControl(SIO_UDP_CONNRESET, new[] { Convert.ToByte(false) }, null);
}
```

这是一个针对 **Windows UDP Socket 已知 Bug** 的修复。

**问题描述**：在 Windows 上，当 UDP Socket 向一个不存在的端口发送数据时，系统会收到一个 ICMP Port Unreachable 消息，Windows 会将这个 ICMP 错误转换成 Socket 错误（`WSAECONNRESET`），导致后续的 `ReceiveFrom` 调用抛出异常，中断 UDP 接收循环。

**修复原理**：通过 `IOControl` 调用 `SIO_UDP_CONNRESET` 控制码，将 `false` 传入，告诉 Windows 内核不要把 ICMP Unreachable 转换为 Socket 异常。

**平台限制**：这是 Windows 特有的行为，Linux/macOS 不存在这个问题，所以需要 `IsOSPlatform` 判断。

```csharp
// 创建 UDP Socket 时标准流程
Socket udpSocket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
NetworkHelper.SetSioUdpConnReset(udpSocket); // 必须调用，否则 Windows 下容易崩
udpSocket.Bind(new IPEndPoint(IPAddress.Any, port));
```

---

## 二、KHEncoding：轻量级编解码工具

### 2.1 Hex 编解码

```csharp
public static String BytesToHex(byte[] bytes, int size = 0)
{
    char[] buf = new char[2 * size];
    for (int i = 0; i < size; i++)
    {
        byte b = bytes[i];
        buf[2 * i + 1] = digits[b & 0xF];      // 低 4 位
        b = (byte)(b >> 4);
        buf[2 * i + 0] = digits[b & 0xF];      // 高 4 位
    }
    return new String(buf);
}
```

手写 Hex 编码比 `BitConverter.ToString()` 快（省去了 `-` 分隔符处理），比 `StringBuilder` 快（直接操作 char 数组）。`size` 参数支持只编码前 N 个字节，用于调试输出网络包头。

### 2.2 XOR 流式加密

这是 `KHEncoding` 最核心的功能：

```csharp
// 原地加密（修改 buffer 本身）
public static int XORCodec(byte[] buffer, int begin, int len, byte[] key)
{
    if (buffer == null || key == null || key.Length == 0)
        return -1;
    if (begin + len >= buffer.Length)
        return -1;

    int blockSize = key.Length;
    int j = 0;
    for (j = begin; j < begin + len; j++)
    {
        buffer[j] = (byte)(buffer[j] ^ key[(j - begin) % blockSize]);
    }
    return j;
}

// 拷贝加密（输出到新 buffer）
public static int XORCodec(byte[] inBytes, byte[] outBytes, byte[] keyBytes)
{
    int blockSize = keyBytes.Length;
    for (int j = 0; j < inBytes.Length; j++)
    {
        outBytes[j] = (byte)(inBytes[j] ^ keyBytes[j % blockSize]);
    }
    return inBytes.Length;
}
```

#### XOR 加密的原理

XOR（异或）加密是最简单的对称加密形式：

```
加密：明文 XOR 密钥 = 密文
解密：密文 XOR 密钥 = 明文（异或的自逆性）
```

当密钥长度小于数据长度时，密钥循环重复（`key[j % blockSize]`），形成**周期性密钥流**，这称为 Vigenère 式流加密。

#### 工程实践中的使用方式

```csharp
// 定义密钥（通常硬编码或从配置加载）
byte[] key = new byte[] { 0x4F, 0x2A, 0x73, 0x1C, 0x88 };

// 发送数据前加密
byte[] sendBuffer = GetMessageBytes();
KHEncoding.XORCodec(sendBuffer, 0, sendBuffer.Length, key);
socket.Send(sendBuffer);

// 接收数据后解密（XOR 解密 = 再次 XOR）
byte[] recvBuffer = new byte[4096];
int len = socket.Receive(recvBuffer);
KHEncoding.XORCodec(recvBuffer, 0, len, key);
ProcessMessage(recvBuffer, len);
```

#### XOR 加密的局限性

XOR 加密在游戏中主要用于**防止简单抓包**，而非真正的安全加密：

| 能力 | XOR 加密 | AES/ChaCha20 |
|------|----------|--------------|
| 防止明文抓包 | ✅ | ✅ |
| 防止密文分析 | ❌ | ✅ |
| 抵抗已知明文攻击 | ❌ | ✅ |
| 性能 | 极高 | 中（硬件加速后也很高）|
| 实现复杂度 | 极低 | 中 |

对于手游的网络通信，XOR 通常作为第一层"混淆"使用，配合 TLS/WSS 才能提供真正的安全保障。

### 2.3 CheckSum 校验

```csharp
public static ushort CheckSum(byte[] buffer, int size)
{
    ulong sum = 0;
    int i = 0;
    while (size > 1)
    {
        sum = sum + BitConverter.ToUInt16(buffer, i);
        size -= 2;
        i += 2;
    }
    if (size > 0)
    {
        sum += buffer[i]; // 奇数字节单独处理
    }

    while ((sum >> 16) != 0)
    {
        sum = (sum >> 16) + (sum & 0xffff); // 进位折叠
    }

    return (ushort)(~sum); // 取反
}
```

这是标准的 **Internet Checksum**（RFC 1071），也叫 IP/TCP/UDP 校验和算法：

1. 将数据按 16 位分组累加
2. 处理奇数字节（补零对齐）
3. 进位折叠（超过 16 位的进位加回低 16 位）
4. 取反得到校验和

**验证方式**：将数据（含校验和字段）再次计算，结果应为 `0xFFFF`，或者对接收方：原始数据 + 校验和计算结果为 0。

```csharp
// 发送：计算并附加校验和
ushort cs = KHEncoding.CheckSum(payload, payload.Length);
// 将 cs 写入消息头

// 接收：验证
ushort received = ReadCheckSumFromHeader();
ushort computed = KHEncoding.CheckSum(receivedData, receivedData.Length);
if (received != computed)
{
    Log.Error("数据包校验失败，可能发生了篡改或传输错误");
    return;
}
```

---

## 三、完整的消息收发流程

结合两个工具类，一个典型的游戏消息处理流程如下：

```
【发送侧】
原始消息 (Protobuf 序列化字节)
    ↓ KHEncoding.CheckSum → 计算校验和，写入消息头
    ↓ KHEncoding.XORCodec → XOR 加密整个包
    ↓ Socket.Send → 发出
    
【接收侧】
    ↓ Socket.Receive → 接收原始字节
    ↓ KHEncoding.XORCodec → XOR 解密（密钥相同，操作幂等）
    ↓ KHEncoding.CheckSum → 验证校验和
    ↓ Protobuf 反序列化 → 得到消息对象
```

---

## 四、总结

`NetworkHelper` 和 `KHEncoding` 是 ET 框架网络层的两块基石：

**NetworkHelper** 处理了几个容易踩坑的细节：
- 只枚举物理以太网接口，避免虚拟网卡干扰
- `LastIndexOf(':')` 正确支持 IPv6 地址解析
- Windows UDP CONNRESET Bug 的专项修复

**KHEncoding** 提供了轻量级的安全防护组件：
- 手写 Hex 编码，性能优先
- XOR 双 Buffer 设计（原地/拷贝），适配不同场景
- 标准 Internet Checksum，用于数据完整性验证

这套组合拳能有效防御"脚本小子"级别的抓包攻击，但对于需要真正安全防护的支付、账号等接口，仍需升级到 TLS + 完整加密方案。

> 安全是一个分层的工程问题，XOR 加密只是第一层皮，架构设计时要清楚每一层防护的边界和能力范围。
