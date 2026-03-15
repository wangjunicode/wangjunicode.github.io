---
title: 聊天系统架构设计与游密SDK接入全流程
published: 2024-04-01
description: "阵营系统功能交付，完成GVE玩法各项bug修复，启动聊天系统开发，接入CBB中台聊天SDK"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 04/01 月初规划 & 聊天系统评估

### 聊天系统开发评估（25人日）

| 模块 | 工时 |
|------|------|
| 聊天系统主体框架 | 2人日 |
| 消息输入/发送（文本/表情/道具/历史记录/CD/敏感词） | 4人日 |
| 消息表现（基础消息/交互） | 4人日 |
| 主界面聊天框 | 2人日 |
| 聊天频道（世界/公会/附近/密聊/流派/树洞/招募/系统/弹幕） | 3人日 |
| 聊天设置 | 1人日 |
| 中台聊天SDK接入 | 2人日 |
| 传音功能 | 2人日 |
| 场景消息气泡 | 2人日 |
| 小窗模式 | 2人日 |
| 添加/编辑/设置密聊 | 2人日 |

## 04/02 阵营功能代码

### GVE 副本玩法阵营实现

阵营相关核心代码片段（`LC_DunGeon_GVE`）：

```lua
---@class LC_DunGeon_GVE:LC_DunGeon_Base
local LC_DunGeon_GVE = BaseClass("LC_DunGeon_GVE", LC_DunGeon_Base)

function LC_DunGeon_GVE:ctor()
    -- GVG事件定义
    table.merge(self.KVMsgFunc, {
        ["GVG_ENTER_NTF_ALL"] = self.GVG_ENTER_NTF_ALL,
        ["GVG_CALL_NOTIFY"] = self.GVG_CALL_NOTIFY,
        ["GVE_SCENE_NOTIFY"] = self.GVE_SCENE_NOTIFY,
        ["DUNGEON_BASEINFO_NOTIFY"] = self.DUNGEON_BASEINFO_NOTIFY,
        ["NPC_UPDATE_CANNON"] = self.NPC_UPDATE_CANNON,
    })
    CS.TL_EventToLua.m_kLuaCallback = Bind(self, LC_DunGeon_GVE.OnTimelineEvent)
end
```

### 服务器变量解析工具函数

```lua
local function decodeServerVar(varx)
    if varx.vi64 and #varx.vi64 > 0 then return varx.vi64[1] end
    if varx.vstr and #varx.vstr > 0 then return varx.vstr[1] end
    if varx.vd64 and #varx.vd64 > 0 then return varx.vd64[1] end
    Debug.LogError("服务器变量错误")
end

local paramsCache = {}
local function decodeServerParams(params)
    table.clear(paramsCache)
    if params == nil then return paramsCache end
    for k, v in ipairs(params) do
        if v.strParams and #v.strParams > 0 then
            paramsCache[#paramsCache+1] = v.strParams[1]
        elseif v.intParams and #v.intParams > 0 then
            paramsCache[#paramsCache+1] = v.intParams[1]
        end
    end
    return paramsCache
end
```

## 04/03 资源加载 & Lua 知识

### Unit 类型遮罩

```lua
enum_UnitTypeMask = {
    UT_NONE        = 1,
    UT_Monster     = 2,    -- 怪物
    UT_Npc         = 4,    -- Npc
    UT_Player      = 8,    -- 玩家
    UT_Trigger     = 16,   -- 陷阱/法阵
    UT_DroppedItem = 256,  -- 掉落物
}
```

位运算遮罩用于过滤特定类型的 Unit。

### AOI 格子算法
一个格子 size：30×30 单位（m）。

### Lua 弱引用
```lua
-- __mode = "v" 弱值引用，__mode = "k" 弱键引用
local t = setmetatable({}, {__mode = "v"})
```
弱引用表中的对象不会阻止 GC 回收。

### Unity JobSystem
[Unity JobSystem 学习](https://zhuanlan.zhihu.com/p/148160780)

## 04/07 Lua `next` 函数

```lua
-- next(table, index=0)：遍历 index 下一位元素
-- 遇到非nil则返回下标和值，否则返回nil
for k, v in next, myTable do
    print(k, v)
end
```

### P4V 删除文件
删除文件要到 depot 里去删除，不能只在本地删除。

### Unity GUID 问题
`Could not extract GUID in text file *.unity` — 通常是场景文件损坏或 GUID 冲突导致。

## 04/08 阵营功能交付 & CBB 网络管理器

### CBB 网络管理器重构

`NW_CBBNetworkManager` 核心设计：

```csharp
public class NW_CBBNetworkManager : Singleton<NW_CBBNetworkManager>
{
    // 用于收发协议
    public CClientSession Session { get; private set; }
    // 用于提供一些业务接口
    public CEZClient EZClient { get; private set; }

    // 消息缓存队列（无锁并发）
    private ConcurrentQueue<MessageInfoCache> kTopLevelQueue
        = new ConcurrentQueue<MessageInfoCache>(new Queue<MessageInfoCache>(32));
    private ConcurrentQueue<MessageInfoCache> kCacheCircularQueue
        = new ConcurrentQueue<MessageInfoCache>(new Queue<MessageInfoCache>(1024));

    // 消息优先级策略
    private Dictionary<ulong, PrioritySetting> kPrioritySettings;
    // 消息合批数组（减少GC）
    private const int iMessageCacheArrayDefine = 20;
    private ulong[] kMessageIdList = new ulong[iMessageCacheArrayDefine];
    private int[] kMessageSizeList = new int[iMessageCacheArrayDefine];
    private IntPtr[] kMessageSizePtr = new IntPtr[iMessageCacheArrayDefine];
}
```

### 消息优先级枚举

```csharp
public enum PrioritySetting
{
    NonReplaceable = 0,  // 不可替换
    Replaceable = 1,     // 可替换（新消息覆盖旧消息）
    Discardable = 2      // 可丢弃
}
```

### PB 协议解析 GC 优化
**思路**：不把 `buffer[]` 传给 Lua 使用，而是传**指针（IntPtr）**，避免在托管堆上创建大数组，减少 GC 压力。

### 连接服务器（异步）

```csharp
public async Task Connect()
{
    CClientRpcRet<CGatewayConnectResponse> oRpcRet =
        await EZClient.ConnectToGateway(ServerAddress, ConnnectRequest);
    Session = oRpcRet.GetSession();
    if (Session != null)
    {
        Session.SetUnhandledRequestCallback(_OnRecivePublish);
    }
    ConnectLuaCallback?.Invoke((int)oRpcRet.GetData().ErrorCode);
}
```

## 04/10 Bug 修复

### AB 资源加载逻辑
先根据**依赖关系**将 AB 从硬盘加载到内存，然后从 AB 中解出需要的文件。

### 修复的 Bug
- 冰炮/火炮数量显示 bug
- 阵营问题——中立怪处理
- 龙脱战逻辑
- 技能选中自己时移除处理

## 04/11 聊天 SDK 接入

### C# `fixed` 关键字
在 `unsafe` 上下文中使用，**固定托管内存防止 GC 移动**：

```csharp
unsafe
{
    fixed (byte* ptr = buffer)
    {
        // ptr 在此作用域内不会被GC移动
    }
}
```
用于需要传指针给 native 代码或进行底层内存操作的场景。

## 04/12 CBB 管理器重构完成

### 接收广播回调（`_OnRecivePublish`）

```csharp
private void _OnRecivePublish(CClientRpcContext oProtocolContext)
{
    // 清理引用计数为0的缓存
    for (int i = 0; i < kCacheMessageRefList.Count; ++i)
    {
        if (kCacheMessageRefList[i].m_kCacheRefCount <= 0)
        {
            kCacheMessageRefList[i].m_kOProtocolContext.ReleaseRequestBuffer();
            kCacheMessageRefList.RemoveAt(i);
            i--;
        }
    }

    var kCacheRef = new CacheRef();
    // 处理合包消息（MulitMessage）
    uint uiMsgTypeID = oProtocolContext.MsgID;
    if (uiMsgTypeID == EnprotoType.MulitMessage)
    {
        var kContextSpan = oProtocolContext.Request.AsSpan();
        for (int i = 0; i < oProtocolContext.Request.Count; ++i)
        {
            var kSize = BinaryPrimitives.ReadInt32BigEndian(kContextSpan.Slice(i, 4));
            i += 4;
            // 处理每个子消息...
        }
    }
}
```

## 04/15 CBB 网络跑通

### C# 使用 Protobuf 的步骤
1. 安装 proto 编译器，确保 `protoc` 命令可用
2. 编写/修改 `.proto` 文件
3. 生成 C# 代码：`protoc --csharp_out=<输出目录> <你的.proto文件>`
4. 将代码集成到项目
5. 使用生成的类进行消息序列化/反序列化

## 04/16-17 C#/Lua 侧对接完成

### 修改文件列表
- `LC_AssetDatasetDefine.lua`
- `LC_DAL_Chat.lua`
- `proto.pb.bytes`
- `NW_Helper_PBDefine.lua`
- `im_DEF.lua`（及 meta 文件）

## 04/18 网络库封装设计

### 适配器模式封装网络库

```csharp
// 通用网络库接口
public interface INetworkLibrary
{
    void Connect(string serverAddress, int port);
    void SendMessage(string message);
    string ReceiveMessage();
    void Disconnect();
}

// TcpClient 适配器
public class TcpClientAdapter : INetworkLibrary
{
    private TcpClient tcpClient;
    public void Connect(string serverAddress, int port)
    {
        tcpClient = new TcpClient();
        tcpClient.Connect(serverAddress, port);
    }
    public void Disconnect() { tcpClient.Close(); }
    // ...
}

// 使用方
ChatClient chatClient = new ChatClient(new TcpClientAdapter());
chatClient.ConnectToServer("serverAddress", port);
```

### Lua Protobuf 使用流程
1. 编写 `.proto` 文件
2. 用 proto 库导出成 `.bytes`
3. 全量加载 `.bytes`
4. 用 `pb` 接口进行解析

## 04/21 CBB 联调测试

### cURL 测试登录接口

```bash
# Linux
curl --location 'cbb-common.huanle.com/account/login' \
  --header 'Content-Type: application/json' \
  --data '{"appid": "ROmeta", "account": "test1"}'
```

```powershell
# Windows PowerShell
$requestBody = @{ appid = "ROmeta"; account = "test1" } | ConvertTo-Json
Invoke-RestMethod -Uri 'https://cbb-common.huanle.com/account/login' \
  -Method Post -ContentType 'application/json' -Body $requestBody
```

## 04/24 聊天系统进展

- 优化了 PB 指针传 Lua 的方式（替代 buffer 数组）
- 跑通了 token 联调
- 查看新的滑动列表组件

## 04/26 主界面聊天栏跑通

主界面聊天栏跑通，完成了基础消息显示。后续计划：
- CD（消息冷却）处理
- 附近频道
- 消息对象池

## 04/27 多线程与消息缓存

### 消息引用计数设计
为了安全释放 buffer，使用引用计数管理消息缓存的生命周期。

### 多线程问题分析
- **上行请求**：`await` 等异步线程回来后，回到主线程上下文进行回调处理
- **广播请求**：注册的委托回调不能直接放在异步线程中执行，需要回到主线程

### 线程安全的消息缓存操作

```csharp
private readonly object messageCacheRefLock = new object();

private void ReceiveMessage(Message message)
{
    lock (messageCacheRefLock)
    {
        // 清理引用计数为0的缓存
        for (int i = 0; i < messageCacheRefList.Count; i++)
        {
            if (messageCacheRefList[i].m_kCahceRefCount <= 0)
            {
                messageCacheRefList[i].Dispose();
                messageCacheRefList.RemoveAt(i);
                i--; // 防止跳过下一个元素
            }
        }
        var messageCacheRef = new MessageCacheRef { m_kCahceRefCount = 0 };
        messageCacheRef.AddReference();
        messageCacheRefList.Add(messageCacheRef);
        messageQueue.Enqueue(new MessageCacheInfo { m_kMessageCacheRef = messageCacheRef });
    }
}
```

### P4V + VSCode 工作流
- VSCode 安装 P4 插件，代码修改可自动同步到 P4
- Unity 工程目录配置 P4 配置文件（账号/密码/工作空间），命令行操作

## 04/30 雪花算法 & Lua select

### 雪花算法（Snowflake）
用于聊天频道 ID 生成的分布式唯一 ID 方案：

| 部分 | 位数 | 说明 |
|------|------|------|
| 时间戳 | 41位 | 距起始时间点的毫秒数 |
| 数据中心ID | 5位 | 支持32个数据中心 |
| 机器ID | 5位 | 每中心支持32台机器 |
| 序列号 | 12位 | 同毫秒内同机器的序列 |

特点：趋势递增、全局唯一、高性能。

### Lua `select` 函数

```lua
-- 获取变长参数个数
function countArgs(...)
    return select("#", ...)
end
print(countArgs(1, 2, 3))  -- 输出：3

-- 获取指定位置参数
function printSecondArg(...)
    return select(2, ...)
end
print(printSecondArg("a", "b"))  -- 输出："b"
```

### 设置功能协议
- `TT_SETTING_SAVE_SETTING_INFO = 39000`：存储 setting
- `TT_SYNC_ALL_SETTING = 39001`：通知所有设置（进游戏广播）

**设计思路**：关闭界面时发送保存请求，服务器作存储以支持重启后还原配置。
