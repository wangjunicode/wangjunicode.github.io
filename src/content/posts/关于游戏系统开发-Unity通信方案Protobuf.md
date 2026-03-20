---
title: Unity通信方案Protobuf
published: 2019-04-06
description: "Google Protobuf是一种轻量级、高效、易于使用的数据序列化协议。"
tags: [Unity, Protobuf, 网络编程]
category: Unity开发
draft: false
---

Google Protobuf是一种轻量级、高效、易于使用的数据序列化协议。

## 使用Google Protobuf



### 0.下载的Protobuf库，protobuf-net.dll -> Assets/Plugins;Protoc编译器

### 1. 编写消息格式定义文件

```protobuf
syntax = "proto3";

package chat;

message ChatMessage {
  string username = 1;
  string content = 2;
}

message LoginMessage {
  string username = 1;
}
```

### 2. 使用Protoc编译消息格式定义文件

```csharp
protoc --csharp_out=./ ./chat.proto
```

### 3. 使用Protobuf编解码消息

```csharp
using UnityEngine;
using UnityEngine.Networking;
using chat;

public class ChatClient : NetworkBehaviour {
    public string serverAddress = "localhost";
    public int serverPort = 7777;
    public string username = "Player";

    private int connectionId = -1;

    void Start () {
        // 连接服务器
        NetworkClient client = new NetworkClient();
        client.RegisterHandler(MsgType.Connect, OnConnected);
        client.RegisterHandler(MsgType.Disconnect, OnDisconnected);
        client.RegisterHandler(ChatMessage.MsgId, OnChatMessage);
        client.Connect(serverAddress, serverPort);
    }

    void OnConnected(NetworkMessage netMsg) {
        // 发送登录消息
        LoginMessage loginMessage = new LoginMessage { Username = username };
        byte[] data = ProtobufSerializer.Serialize(loginMessage);
        netMsg.conn.Send(LoginMessage.MsgId, new LoginMessageMsg(data));
    }

    void OnDisconnected(NetworkMessage netMsg) {
        // 连接断开，做相应处理
    }

    void OnChatMessage(NetworkMessage netMsg) {
        // 接收聊天消息
        byte[] data = netMsg.reader.ReadBytes();
        ChatMessage chatMessage = ProtobufSerializer.Deserialize<ChatMessage>(data);
        Debug.Log(chatMessage.Username + ": " + chatMessage.Content);
    }

    public void SendMessage(string content) {
        // 发送聊天消息
        ChatMessage chatMessage = new ChatMessage { Username = username, Content = content };
        byte[] data = ProtobufSerializer.Serialize(chatMessage);
        NetworkManager.singleton.client.Send(ChatMessage.MsgId, new ChatMessageMsg(data));
    }
}

public class LoginMessageMsg : MessageBase {
    public byte[] Data;

    public LoginMessageMsg() {}

    public LoginMessageMsg(byte[] data) {
        Data = data;
    }

    public override void Serialize(NetworkWriter writer) {
        writer.WriteBytesFull(Data);
    }

    public override void Deserialize(NetworkReader reader) {
        Data = reader.ReadBytes();
    }
}

public class ChatMessageMsg : MessageBase {
    public byte[] Data;

    public ChatMessageMsg() {}

    public ChatMessageMsg(byte[] data) {
        Data = data;
    }

    public override void Serialize(NetworkWriter writer) {
        writer.WriteBytesFull(Data);
    }

    public override void Deserialize(NetworkReader reader) {
        Data = reader.ReadBytes();
    }
}
```

