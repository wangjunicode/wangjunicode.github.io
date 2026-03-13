---
title: 工作记录 2024年5月
published: 2024-05-01
description: "聊天系统开发（游密SDK接入、Proto网络层、消息列表），活动框架预研，C#无GC编程实践"
tags: [工作记录]
category: 工作记录
draft: false
---

## 05/01 Protobuf 原理深入

### Protobuf 序列化原理

**核心优势**：序列化后数据比 XML/JSON 小，网络 IO 更快，移动设备更省流量和电量。

**varint 编码**：用一个或多个字节表示数字，值越小使用越少字节。每个字节最高位作为标志位：
- 最高位为 `1`：后续还有字节表示同一数字
- 最高位为 `0`：这是最后一个字节

示例：两个字节 `1010 1100  0000 0010`，左边字节最高位为1，说明后续还有字节。

**Key-Value 结构**：消息序列化后为二进制流，每个字段对应一个 key-value 对：
```
key = (field_number << 3) | wire_type
```
不需要分隔符，可选字段未赋值则不出现在 buffer 中。

```protobuf
message helloworld {
    required int32  id  = 1;  // ID
    required string str = 2;  // str
    optional int32  opt = 3;  // 可选字段（未赋值则不序列化）
}
```

参考：[Protobuf 序列化算法分析](https://zhuanlan.zhihu.com/p/141415216)

## 05/04 聊天数据结构重设计

### EmmyLua 排除大目录配置
解决 VSCode 打开 LuaScript 加载 config 子目录耗时问题：在项目根目录创建 `emmy.config.json`：

```json
{
    "source": [
        {
            "dir": "./",
            "exclude": [
                "csv/**.lua"
            ]
        }
    ]
}
```

## 05/07 游密（YouMe）SDK 接入

### 聊天 SDK 功能
实现世界聊天、公会聊天、组队聊天、文字、表情、语音等多项功能。

官方文档：[YouMe IM SDK Unity 接入指南](https://www.youme.im/doc/IMGuideUnityC.php)

### C# `const` / `static` / `readonly` 对比

| 关键字 | 编译时/运行时 | 可修改性 | 访问方式 |
|--------|------------|---------|---------|
| `const` | 编译时常量 | 不可修改 | 类名直接访问（隐式 static） |
| `static` | 运行时 | 可修改 | 类名直接访问 |
| `readonly` | 运行时（构造函数初始化） | 仅构造函数可赋值 | 实例访问 |

```csharp
// const：编译时常量，基本类型或枚举
public const int MaxValue = 100;

// static：类级别共享数据
private static int count;

// readonly：只读字段，构造函数中赋值
private readonly double radius;
public Circle(double radius) { this.radius = radius; }
```

### C# async/await 多次调用线程安全
多次调用 `await DownloadDataAsync()` 时：
- 异步操作独立并行执行
- 事件处理程序 `OnDataDownloaded` 在主线程同步执行（按调用顺序逐个）
- 不会互斥，但需注意跨线程操作 UI 时使用 `Invoke`

## 05/08 聊天系统需求评估

| 模块 | 工时 |
|------|------|
| 插件导入，导出安卓/iOS工程 | 1人日 |
| SDK集成/初始化/IM登陆 | 2人日 |
| 网络层设计 | 3人日 |
| 自定义proto，C#与Lua数据交互 | 3人日 |
| 聊天DAL开发 | 2人日 |
| 主界面聊天适配新数据层 | 3人日 |
| 侧边聊天窗适配新数据层 | 3人日 |
| 滑动组件缓存池/动态扩容 | 3人日 |
| 联调 | 4人日 |

## 05/09 Proto 流程跑通

### 字符串编码大小参考

| 编码 | 每字符字节数 | 2KB 约含字符数 |
|------|-----------|-------------|
| ASCII | 1字节 | ~2048字符 |
| UTF-8（英文） | 1字节 | ~2048字符 |
| UTF-8（中文） | 3字节 | ~682字符 |
| UTF-16 | 2字节 | ~1024字符 |

### YouMe REST API 调试

```powershell
# Checksum 计算（SHA1(appsecret + curtime)）
function Calculate-Checksum {
    param ([string]$appsecret, [string]$curtime)
    $combinedStr = $appsecret + $curtime
    $sha1 = New-Object System.Security.Cryptography.SHA1Managed
    $hashBytes = $sha1.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($combinedStr))
    $checksum = [System.BitConverter]::ToString($hashBytes) -replace '-', ''
    return $checksum.ToLower()
}

$curtime = [int][double]::Parse((Get-Date -UFormat %s)) - 3600*8
$checksum = Calculate-Checksum -appsecret $appsecret -curtime $curtime

$requestBody = @{
    MsgSeq   = [string]$curtime
    ChatType = 2
    SendID   = $username
    RecvID   = "1"
    Content  = "Hello RoMeta"
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://sgapi.youme.im/v1/im/query_im_send_msg?appkey=$appkey&identifier=$username&curtime=$curtime&checksum=$checksum" `
    -Method Post -ContentType 'application/json' -Body $requestBody
```

## 05/11 减少 GC 实践

### Protobuf 序列化 GC 优化

**问题**：`ToByteArray` 每次调用都 `new byte[]`，产生 GC 压力。

**方案一：对象池**
```csharp
private static readonly ObjectPool<byte[]> byteArrayPool =
    new ObjectPool<byte[]>(() => new byte[4096], 1000);

public static byte[] ToByteArray(this IMessage message)
{
    byte[] array = byteArrayPool.Get();
    try
    {
        var codedOutputStream = new CodedOutputStream(array);
        message.WriteTo(codedOutputStream);
        codedOutputStream.CheckNoSpaceLeft();
        return array;
    }
    finally
    {
        byteArrayPool.Return(array);
    }
}
```

**方案二：MemoryStream（动态扩展）**
```csharp
public static byte[] ToByteArray(this IMessage message)
{
    using (var stream = new MemoryStream())
    {
        var codedOutputStream = new CodedOutputStream(stream);
        message.WriteTo(codedOutputStream);
        codedOutputStream.CheckNoSpaceLeft();
        return stream.ToArray();
    }
}
```

### 无 GC 编程技巧汇总
1. **对象池**：重用对象，避免频繁 new/GC
2. **使用 `struct` 值类型**：栈上分配，不产生 GC
3. **避免装箱**：不要将值类型赋给 `object`
4. **ArrayPool**：复用数组（`System.Buffers.ArrayPool<T>`）

参考：[XLua 源码学习](https://zhuanlan.zhihu.com/p/68406928)

## 05/13 YouMe 接入调试

### proto decode 错误排查
```
bad argument #2 to 'decode_unsafe' (userdata expected, got userdata)
```
**原因**：数据为空导致类型不匹配，先检查数据是否有效再 decode。

## 05/14 C# 无 GC 编程

### ObjectPool 实现

```csharp
public class ObjectPool<T> where T : new()
{
    private Stack<T> pool = new Stack<T>();

    public T GetObject()
    {
        return pool.Count > 0 ? pool.Pop() : new T();
    }

    public void ReturnObject(T obj)
    {
        pool.Push(obj);
    }
}
```

## 05/16 Buff Bug 修复 & 单例加锁

### 技能释放失败 Bug
**原因**：技能条件判断中 buff 层数检测不满足配置要求（某些技能需要特定 buff 及层数才能释放）。

### 单例模式加锁
多线程环境下不加锁会重复创建单例，需使用双重检测锁（DCL）：
```csharp
private static volatile T instance;
private static readonly object lockObject = new object();

if (instance == null)
{
    lock (lockObject)
    {
        if (instance == null)
            instance = new T();
    }
}
```

## 05/17 Unity 单例模式完整实现

```csharp
public class Singleton<T> : MonoBehaviour where T : MonoBehaviour
{
    private static T instance;
    private static bool isShuttingDown = false;
    private static readonly object lockObject = new object();

    public static T Instance
    {
        get
        {
            if (isShuttingDown)
            {
                Debug.LogWarning($"{typeof(T)} instance is already destroyed.");
                return null;
            }
            lock (lockObject)
            {
                if (instance == null)
                {
                    instance = FindObjectOfType<T>();
                    if (instance == null)
                    {
                        var go = new GameObject();
                        instance = go.AddComponent<T>();
                        go.name = typeof(T).ToString() + " (Singleton)";
                        DontDestroyOnLoad(go);
                    }
                }
                return instance;
            }
        }
    }

    protected virtual void OnDestroy() { isShuttingDown = true; }
    protected virtual void OnApplicationQuit() { isShuttingDown = true; }
}
```

**关键设计**：
- `isShuttingDown` 标志防止 `OnDestroy` 期间访问单例
- `lock` 确保多线程安全
- `DontDestroyOnLoad` 跨场景保持

## 05/18 Proto 序列化限制

Proto 序列化接口的 GC 无法完全避免，因为写入的字节流必须是消息的固定大小（需要提前分配）。

## 05/21 Proto 更新不一致 Bug

**现象**：proto 更新后解析失败。  
**原因**：客户端 proto 已更新，但**对应服务器没有更新**，下发的 byte 是旧 proto encode 的，客户端用新 proto 解析自然失败。  
**教训**：proto 更新需要客户端和服务器同步更新。

## 05/23 工具与调试

### FORCE_CRASH 宏定义
游戏异常时强制弹窗提示，便于调试：

```csharp
private static void OnLog(string condition, string stackTrace, LogType type)
{
#if FORCE_CRASH
    if (type == LogType.Exception)
        ForceCrash(kLog, type);
#endif
}

#if FORCE_CRASH
[DllImport("User32.dll")]
public static extern int MessageBox(IntPtr handle, String message, String title, int type);

public static void ForceCrash(string kLog, LogType type)
{
    int res = MessageBox(IntPtr.Zero, kLog, "Exception", 0);
    if (res == 1)
    {
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#else
        Application.Quit();
#endif
    }
}
#endif
```

### Clumsy — 网络延迟模拟工具
用于网络开发和测试，可模拟网络延迟、丢包等场景。

## 05/27 活动框架预研

### 活动系统架构设计
- 主界面入口 → 点击 → 打开框架 → 初始化子活动
- 活动类型：日常活动、节日活动、专属活动
- 左侧页签 + 右侧具体 prefab

### 任务拆分
| 模块 | 工时 |
|------|------|
| 主界面入口 | 1人日 |
| 定义活动类 | 1人日 |
| 活动管理器 | 2人日 |
| 日常活动框架界面 | 1人日 |
| 开服活动DAL | 1人日 |
| 开服活动界面 | 1人日 |
| 联调自测 | 3人日 |

## 05/29 LightMap & 定时器设计

### LightMap 光照烘焙
为节省运行时开销，将光照信息提前烘焙到纹理（LightMap），运行时直接取烘焙结果，不用动态计算。

### 定时器设计
```
Timer 类：
  - 初始化
  - Update（tick）
  - 开始/停止

TimerManager（管理器）：
  - 创建 Timer，返回给用户
  - 管理所有 Timer 的 Update
```

参考：[XLua 源码学习](https://zhuanlan.zhihu.com/p/68406928)

## 05/30 活动框架 & 配置表流程

### 配置表导出流程
```
Excel → CSV（Python/NPOI 处理）→ Lua（运行时使用）
```
本地调试直接改 Lua 文件即可。

### 项目 Lua 版本
项目使用 xLua，Lua 版本为 **Lua 5.3**。

查询方式：
```lua
print(_VERSION)  -- 输出: Lua 5.3
```

## 05/31 状态模式 & 正则过滤

### 炮台状态模式设计

```
StateMachine 设计：
- 定义 State 基类（onEnter/onExit/onUpdate，持有 Cannon 引用）
- Cannon 持有当前 State 实例，提供 setState(state) 接口
- Cannon 在 update 中调用 currentState.onUpdate()
- 扩展状态只需新增 State 子类，无需修改 Cannon
```

### Lua 富文本标签过滤（正则）

```lua
local function filterRichText(input)
    local filtered = input:gsub('<[^>]+>', function(tag)
        -- 只保留 <sprite name="..."> 和 <sprite="..." anim="..."> 格式
        local p1 = tag:match('<sprite%s+name="[^"]+"%s*>')
        local p2 = tag:match('<sprite="[^"]+"%s+anim="[^"]+"%s*>')
        if p1 or p2 then
            return tag
        else
            return ''  -- 移除其他富文本标签
        end
    end)
    return filtered
end
```
