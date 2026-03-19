# 08_WebSocket长连接管理

> WebSocket是游戏大厅和服务器保持实时通信的关键技术。本文讲解项目中两套WebSocket系统的设计与实现。

---

## 1. 系统概述

本项目有两处使用WebSocket：

1. **游戏大厅长连接**：玩家在大厅等待匹配、接收系统推送（好友上线、服务器通知等），通过WebSocket维持与服务器的实时连接。

2. **资源补充下载（`ResDownloadWsClient`）**：Patch完成后，通过WebSocket从内部Python服务器下载额外需要补充的资源文件（仅Debug/GM模式下需要）。

两套系统的使用场景不同，但核心技术完全相同：基于`.NET`的`System.Net.WebSockets.ClientWebSocket`，配合ET框架的`ETTask`异步系统实现非阻塞操作。

---

## 2. 架构设计

### 2.1 ResDownloadWsClient 架构

这是资源下载专用的WebSocket客户端，完整的数据流如下：

```
TryCreateAfterPatchAsync()
    │
    ├─ 检查是否需要下载 (IsNeedDownloadExcludeRes)
    │   └─ 条件：开启GM/SRDebugger 且 缓存目录不存在
    │
    ▼
ProcessResources()
    │
    ├─── Ready()
    │    └─ 构建wsUrl，清理旧临时文件夹
    │
    ├─── ConnectWebSocketAsync()
    │    └─ new ClientWebSocket() + ConnectAsync()
    │
    ├─── DownloadResources()
    │    ├─ 发送 download_exclude_zip JSON请求
    │    ├─ 接收 download_exclude_zip_begin 确认
    │    ├─ 接收 Binary数据流（实际zip文件字节）
    │    └─ 接收 download_exclude_zip_end 完成信号
    │
    ├─── UnzipDownloadedResourcesAsync()
    │    └─ 后台线程解压zip，带超时（120s）
    │
    ├─── CopySupplementResources()
    │    ├─ .dll.bytes → HotUpdateDllFolder
    │    └─ .bundle → ResUpdate/Platform/
    │
    └─── CloseWebSocketAsync()
         └─ 优雅关闭连接
```

### 2.2 WebSocket消息协议

资源下载使用了混合消息协议（文本+二进制）：

```
客户端 → 服务器（JSON文本）
{
  "cmd": "download_exclude_zip",
  "res_version": "1.2.3"
}

服务器 → 客户端（JSON文本）
{
  "cmd": "download_exclude_zip_begin",
  "ok": true,
  "file_name": "exclude_1.2.3.zip",
  "file_size": 1048576
}

服务器 → 客户端（Binary）
[chunk1 bytes...] [chunk2 bytes...] ...

服务器 → 客户端（JSON文本）
{
  "cmd": "download_exclude_zip_end",
  "ok": true
}
```

### 2.3 大厅WebSocket连接管理

游戏大厅的WebSocket连接管理遵循以下设计：

```
连接状态机：
Disconnected → Connecting → Connected → Disconnecting → Disconnected
                                │
                                │ 异常/超时
                                ▼
                          Reconnecting → Connected（成功）
                                      → Disconnected（失败，触发重登）
```

---

## 3. 核心代码展示

### 3.1 ResDownloadWsClient 完整实现（来自`ResDownloadWsClient.cs`）

```csharp
public static class ResDownloadWsClient
{
    private const string SERVER_IP   = "21.91.218.52";  // 内部服务器IP
    private const int    SERVER_PORT = 8084;
    private const string LOCAL_SAVE_FOLDER  = "exclude_temp";
    private const string DOWNLOAD_RES_PROTO_NAME = "download_exclude_zip";
    private const float  UNZIP_TIMEOUT_SECONDS = 120f;

    private static string localSavePath;
    private static string wsUrl;
    private static string version;
    private static ClientWebSocket webSocket;

    // 主入口：Patch完成后调用
    public static async ETTask TryCreateAfterPatchAsync()
    {
#if UNITY_EDITOR || DEBUG
        return;  // 编辑器/调试包自带资源，无需下载
#endif
        version = Application.version;
        localSavePath = Path.Combine(
            Application.persistentDataPath, LOCAL_SAVE_FOLDER, version);

        if (IsNeedDownloadExcludeRes())
        {
            await ProcessResources();
        }
    }

    // 判断是否需要下载
    private static bool IsNeedDownloadExcludeRes()
    {
        // 只有GM开关打开且缓存不存在时才下载
        if ((SRDebuggerBridge.EnableSRDebugger() || GMBridge.EnableGM()) 
            && !Directory.Exists(localSavePath))
        {
            return true;
        }
        return false;
    }
}
```

### 3.2 WebSocket连接建立

```csharp
private static async ETTask<bool> ConnectWebSocketAsync()
{
    // 如果已有连接且状态正常，直接复用
    if (webSocket != null && webSocket.State == WebSocketState.Open)
        return true;

    // 清理旧连接（避免"脏连接"残留）
    await CloseWebSocketAsync();
    
    webSocket = new ClientWebSocket();
    try
    {
        await webSocket.ConnectAsync(new Uri(wsUrl), CancellationToken.None);
        Debug.Log($"[WsClient] 已连接: {wsUrl}");
        return webSocket.State == WebSocketState.Open;
    }
    catch (Exception e)
    {
        Debug.LogError($"[WsClient] 连接失败: {e.Message}, url={wsUrl}");
        await CloseWebSocketAsync();
        return false;
    }
}
```

### 3.3 下载流程（文本+二进制混合接收）

```csharp
private static async ETTask<string> DownloadResources()
{
    Directory.CreateDirectory(localSavePath);

    // 发送下载请求（JSON文本）
    var request = new DownloadZipRequest 
    { 
        cmd = DOWNLOAD_RES_PROTO_NAME, 
        res_version = version 
    };
    bool sendOk = await SendWsTextAsync(JsonUtility.ToJson(request));
    if (!sendOk) return string.Empty;

    bool beginReceived = false;
    bool endReceived = false;
    string fullPath = string.Empty;
    FileStream writer = null;
    
    try
    {
        while (!endReceived)
        {
            WsMessage msg = await ReceiveNextMessageAsync();
            if (msg == null) 
            {
                Debug.LogError("[WsClient] 连接中断");
                return string.Empty;
            }

            if (msg.messageType == WebSocketMessageType.Binary)
            {
                // 收到二进制数据块，直接写入文件
                if (beginReceived && writer != null && msg.binary?.Length > 0)
                    writer.Write(msg.binary, 0, msg.binary.Length);
                continue;
            }

            // 处理文本控制消息
            TriggerResponse rsp = JsonUtility.FromJson<TriggerResponse>(msg.text);
            
            if (rsp.cmd == "download_exclude_zip_begin")
            {
                if (!rsp.ok) 
                {
                    Debug.LogError($"[WsClient] 下载失败: {rsp.error}");
                    return string.Empty;
                }
                // 创建文件，准备接收二进制数据
                fullPath = Path.Combine(localSavePath, rsp.file_name);
                writer?.Dispose();
                writer = File.Create(fullPath);
                beginReceived = true;
            }
            else if (rsp.cmd == "download_exclude_zip_end")
            {
                endReceived = rsp.ok;
                if (!endReceived)
                    Debug.LogError($"[WsClient] 下载结束异常: {rsp.error}");
            }
        }
    }
    finally
    {
        writer?.Dispose();  // 确保文件流被关闭
    }

    return (string.IsNullOrEmpty(fullPath) || !File.Exists(fullPath)) 
        ? string.Empty : fullPath;
}
```

### 3.4 消息分片接收

WebSocket消息可能被分成多个帧发送，需要循环接收直到`EndOfMessage`为真：

```csharp
private static async ETTask<WsMessage> ReceiveNextMessageAsync()
{
    byte[] buffer = new byte[8192];
    List<byte> allBytes = new List<byte>(8192);

    try
    {
        while (true)
        {
            WebSocketReceiveResult result = await webSocket.ReceiveAsync(
                new ArraySegment<byte>(buffer), CancellationToken.None);
            
            if (result.MessageType == WebSocketMessageType.Close)
                return null;  // 服务器主动关闭

            // 累积数据
            if (result.Count > 0)
                allBytes.AddRange(buffer.Take(result.Count));

            // 消息未结束，继续接收
            if (!result.EndOfMessage)
                continue;

            // 消息完整，返回
            return new WsMessage
            {
                messageType = result.MessageType,
                binary = allBytes.ToArray(),
                text = result.MessageType == WebSocketMessageType.Text
                    ? Encoding.UTF8.GetString(allBytes.ToArray())
                    : null
            };
        }
    }
    catch (Exception e)
    {
        Debug.LogError($"[WsClient] 接收失败: {e.Message}");
        return null;
    }
}
```

### 3.5 异步解压（后台线程+超时控制）

```csharp
private static async ETTask<string> UnzipDownloadedResourcesAsync(string zipFilePath)
{
    string dstDir = Path.Combine(
        Path.GetDirectoryName(zipFilePath),
        Path.GetFileNameWithoutExtension(zipFilePath)
    );

    bool finished = false;
    bool success = false;
    string failReason = string.Empty;
    int cancelFlag = 0;  // 取消标志（使用Interlocked保证线程安全）

    Thread unzipThread = new Thread(() =>
    {
        try
        {
            // 在后台线程执行解压，每次循环检查是否需要取消
            UnzipToDirectory(zipFilePath, dstDir, 
                () => Interlocked.CompareExchange(ref cancelFlag, 0, 0) == 1);
            success = true;
        }
        catch (Exception e)
        {
            failReason = e.Message;
        }
        finally
        {
            finished = true;
        }
    });
    unzipThread.IsBackground = true;
    unzipThread.Start();

    float startTime = Time.realtimeSinceStartup;
    while (!finished)
    {
        // 检查超时（120秒）
        if (Time.realtimeSinceStartup - startTime > UNZIP_TIMEOUT_SECONDS)
        {
            Interlocked.Exchange(ref cancelFlag, 1);  // 通知后台线程取消
            Debug.LogError($"[WsClient] 解压超时: {zipFilePath}");
            return null;
        }
        // 等待16ms（约60fps），不阻塞主线程
        await TimerComponent.Instance.WaitAsync(16);
    }

    return success ? dstDir : null;
}
```

### 3.6 优雅关闭WebSocket连接

```csharp
private static async ETTask CloseWebSocketAsync()
{
    if (webSocket == null) return;

    try
    {
        if (webSocket.State == WebSocketState.Open || 
            webSocket.State == WebSocketState.CloseReceived)
        {
            // 发送Close帧，等待服务器确认（优雅关闭）
            await webSocket.CloseAsync(
                WebSocketCloseStatus.NormalClosure, 
                "done", 
                CancellationToken.None);
        }
    }
    catch (Exception e)
    {
        Debug.LogError($"[WsClient] 关闭异常: {e.Message}");
    }
    finally
    {
        webSocket.Dispose();
        webSocket = null;  // 置空，防止悬空引用
    }
}
```

### 3.7 大厅WebSocket长连接（推荐实现模式）

```csharp
// 游戏大厅的WebSocket管理器（基于本项目的ETTask异步模式）
public class LobbyWebSocketManager : Singleton<LobbyWebSocketManager>
{
    private ClientWebSocket wsClient;
    private CancellationTokenSource cts;
    private const string SERVER_URL = "wss://lobby.game.com/ws";
    private const int HEARTBEAT_INTERVAL = 30000; // 30秒心跳
    private const int RECONNECT_DELAY = 3000;     // 重连间隔3秒
    private int reconnectCount = 0;

    public async ETTask ConnectAsync()
    {
        cts = new CancellationTokenSource();
        wsClient = new ClientWebSocket();
        
        try
        {
            await wsClient.ConnectAsync(new Uri(SERVER_URL), cts.Token);
            Debug.Log("[LobbyWS] 连接成功");
            reconnectCount = 0;
            
            // 启动心跳和接收循环
            _ = HeartbeatLoopAsync();
            _ = ReceiveLoopAsync();
        }
        catch (Exception e)
        {
            Debug.LogError($"[LobbyWS] 连接失败: {e.Message}");
            await TryReconnectAsync();
        }
    }

    private async ETTask HeartbeatLoopAsync()
    {
        while (wsClient?.State == WebSocketState.Open)
        {
            await TimerComponent.Instance.WaitAsync(HEARTBEAT_INTERVAL);
            
            if (wsClient?.State != WebSocketState.Open) break;
            
            // 发送心跳包（防止服务器超时断开）
            await SendTextAsync("""{"cmd":"ping"}""");
        }
    }

    private async ETTask ReceiveLoopAsync()
    {
        while (wsClient?.State == WebSocketState.Open)
        {
            byte[] buffer = new byte[4096];
            try
            {
                var result = await wsClient.ReceiveAsync(
                    new ArraySegment<byte>(buffer), cts.Token);
                
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    Debug.Log("[LobbyWS] 服务器主动关闭连接");
                    await TryReconnectAsync();
                    break;
                }
                
                string text = Encoding.UTF8.GetString(buffer, 0, result.Count);
                ProcessServerMessage(text);
            }
            catch (Exception e)
            {
                Debug.LogError($"[LobbyWS] 接收异常: {e.Message}");
                await TryReconnectAsync();
                break;
            }
        }
    }

    private async ETTask TryReconnectAsync()
    {
        reconnectCount++;
        if (reconnectCount > 5) 
        {
            Debug.LogError("[LobbyWS] 重连次数耗尽，需要重新登录");
            EventDispatcher.Send(EventId.NetworkError);
            return;
        }
        
        // 指数退避重连（3s, 6s, 12s...）
        int delay = RECONNECT_DELAY * (int)Mathf.Pow(2, reconnectCount - 1);
        Debug.Log($"[LobbyWS] {delay}ms后第{reconnectCount}次重连...");
        
        await TimerComponent.Instance.WaitAsync(delay);
        await ConnectAsync();
    }
}
```

---

## 4. 设计亮点

### 4.1 文本+二进制混合协议

资源下载采用"文本控制帧+二进制数据帧"的混合模式：
- 文本帧：传递控制信息（开始/结束信号、文件名）
- 二进制帧：传递实际文件数据，效率更高

这种设计让文件传输和控制信号分离，逻辑清晰，出错时也容易定位。

### 4.2 后台线程解压+主线程超时监控

解压操作在后台线程执行（避免阻塞主线程导致画面卡顿），但通过`cancelFlag`和`Interlocked`实现线程间通信，支持超时取消。主线程通过`WaitAsync(16)`每帧轮询结果，不占用主线程资源。

### 4.3 Finally保证资源释放

```csharp
try
{
    // 下载逻辑
}
finally
{
    await CloseWebSocketAsync();  // 无论成功失败都关闭WebSocket
}
```

和：

```csharp
finally
{
    writer?.Dispose();  // 无论成功失败都关闭文件流
}
```

这两处`finally`保证了即使发生异常，网络连接和文件句柄也会被正确释放，避免资源泄漏。

### 4.4 脏连接检测

```csharp
// 连接前先检查旧连接状态
await CloseWebSocketAsync();  // 先清理可能的脏连接
webSocket = new ClientWebSocket();
```

不直接复用旧的`ClientWebSocket`对象，而是先清理再重建，避免连接状态不一致的问题。

---

## 5. 常见问题与最佳实践

### Q1：WebSocket和HTTP有什么区别？

| 对比 | HTTP | WebSocket |
|------|------|-----------|
| 连接方式 | 每次请求建立新连接 | 一次握手，持久连接 |
| 通信方向 | 只有客户端发起 | 双向，服务器可主动推 |
| 适用场景 | 查询/提交 | 实时推送、聊天、游戏 |
| 开销 | 每次都有HTTP头 | 握手后只有少量帧头 |

### Q2：WebSocket连接断了会自动重连吗？

`ClientWebSocket`本身不自动重连。需要在业务层实现重连逻辑，如上文的`TryReconnectAsync()`示例，建议使用指数退避策略（延迟逐渐增大），避免服务器被大量重连请求冲击。

### Q3：`wss://`和`ws://`有什么区别？

`wss://`是加密的WebSocket（TLS加密），`ws://`是明文。正式环境**必须用`wss://`**，明文`ws://`在生产环境会被运营商中间件拦截或篡改数据，且有安全风险。本项目的`ResDownloadWsClient`使用`ws://`是因为连接的是内部服务器（内网IP），非公网场景。

### Q4：如何处理消息太大（超过`buffer`大小）的情况？

`ReceiveNextMessageAsync`中使用了分片接收循环：

```csharp
while (true)
{
    var result = await webSocket.ReceiveAsync(buffer, token);
    allBytes.AddRange(buffer.Take(result.Count));
    if (result.EndOfMessage) break;  // 所有分片都收到了
}
```

只要`EndOfMessage`不为true，就继续接收，支持任意大小的消息。

### Q5：开发期间如何模拟WebSocket服务器？

推荐使用以下工具：
1. **wscat**：命令行WebSocket客户端/服务端工具（`npm install -g wscat`）
2. **Postman**：支持WebSocket连接测试
3. **Python WebSocket服务器**：参考`ResDownloadWsClient`中的协议格式，用Python的`websockets`库快速搭建测试服务器

---

## 6. 总结

本项目的WebSocket系统展示了一个完整的"连接→请求→接收→解压→复制→关闭"的文件传输流程。关键技术点是：ETTask异步非阻塞处理、文本+二进制混合协议、后台线程解压+主线程监控、以及完善的资源释放机制。掌握这套实现模式，你可以在项目中自信地开发任何基于WebSocket的功能。
