---
title: 游戏数据序列化的多格式适配与上下文驱动设计
published: 2026-03-31
description: 深入解析支持 JSON 和二进制格式的序列化工具实现，理解序列化上下文栈与编辑器/运行时双模式的工程设计。
tags: [Unity, 序列化, 数据持久化, 工程设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 游戏中的序列化需求

游戏开发中，序列化无处不在：

- **配置表**：策划填写 Excel，导出为游戏可读的数据格式
- **存档系统**：保存玩家进度到磁盘
- **网络通信**：把游戏状态转换成字节流发送给服务器
- **编辑器工具**：序列化场景数据、节点图数据

每种场景对格式的要求不同：调试时希望可读（JSON），发布时希望紧凑（二进制），热更新时需要兼容旧版数据。

---

## SerializeHelper 的设计概览

`SerializeHelper.cs` 是框架的序列化工具类，特点是：

1. **双格式支持**：JSON（FullSerializer）和二进制（MemoryPack）
2. **运行时/编辑器模式自动切换**
3. **序列化上下文（SerializationContext）**：通过 using 语句管理序列化帧

### 模式控制

```csharp
public class SerializeHelper
{
#if UNITY_EDITOR || !ONLY_CLIENT
    public static bool UseBinary = false;   // 编辑器/服务端：JSON
    public static bool UseRelease = false;
#else
    public static bool UseBinary = true;    // 发布版：二进制
    public static bool UseRelease = true;
#endif
```

通过编译宏实现：
- **编辑器/服务端**：JSON 格式，人类可读，方便调试
- **发布客户端**：二进制格式（MemoryPack），体积小，反序列化快

---

## 反序列化：从文件到对象

```csharp
public static T Deserialize<T>(string path, bool release = true)
{
#if UNITY_EDITOR
    if (!Threader.applicationIsPlaying)
    {
        // 编辑器非运行时：直接从文件系统读取
        return DeserializeInEditor<T>(ZString.Format("GameCfg/{0}", path));
    }
#endif
    try
    {
        using var frame = SerializationContext.BeginFrame(false);  // 开始序列化帧
        if (UseBinary)
        {
            // 二进制模式
            byte[] bytes = SerializeDelegates.Load<byte[]>(path);
            if (bytes == null)
            {
                Log.Error(ZString.Format("资源未加载: {0}", path));
                return default;
            }
            return MemoryPackSerializeHelper.DeserializeFromBytes<T>(bytes, release);
        }
        else
        {
            // JSON 模式
            string json = SerializeDelegates.Load<string>(path);
            return JSONSerializer.Deserialize<T>(json);
        }
    }
    catch (Exception e)
    {
        Log.Error(e);
        Log.Error(ZString.Format("反序列化失败: {0}", path));
        return default;
    }
}
```

注意 `using var frame = SerializationContext.BeginFrame(false)` 这行——它使用了 C# 的 `using` 语句来自动管理序列化帧的生命周期。`SerializationFrame` 实现了 `IDisposable`，当 `using` 块结束时，自动出栈。

---

## SerializationContext：序列化帧栈

这是一个精妙的设计，用于解决**嵌套序列化**的问题：

```csharp
public static class SerializationContext
{
    [ThreadStatic]  // 线程本地存储，每个线程独立的帧栈
    private static Stack<SerializationFrame> _frameStack;
    
    // 当前帧
    public static SerializationFrame Current => 
        _frameStack == null || _frameStack.Count == 0 ? null : _frameStack?.Peek();
    
    public class SerializationFrame : IDisposable
    {
        public List<object> allTasks = new();
        public List<object> allParameters = new();
        public bool IsOffline;          // 是否离线模式
        public bool noInterSerialize;   // 是否禁止嵌套序列化
        
        void IDisposable.Dispose()
        {
            // using 结束时自动出栈
            if (_frameStack != null && _frameStack.Count > 0)
            {
                _frameStack.Pop();
            }
        }
    }
    
    public static SerializationFrame BeginFrame(bool isOffline)
    {
        EnsureStackInitialized();
        var frame = new SerializationFrame { IsOffline = isOffline };
        _frameStack.Push(frame);  // 入栈
        return frame;
    }
    
    // 全局查询：当前是否是离线模式
    public static bool IsOffline => Current?.IsOffline ?? false;
}
```

**为什么需要帧栈？**

想象这样一个场景：序列化一个 `Quest`（任务）对象，`Quest` 内部有一个 `Reward`（奖励）对象，序列化 `Reward` 时需要知道"当前是否在保存到文件"（`IsOffline`）。

没有帧栈，这个信息需要作为参数层层传递。有了帧栈，任何层级的代码都可以通过 `SerializationContext.IsOffline` 直接获取，就像全局变量，但是**线程安全（ThreadStatic）且作用域受控（using 语句）**。

---

## 序列化的双格式路径

在编辑器中，框架会同时保存两种格式：

```csharp
public static bool SerializeToFile<T>(string path, T instance, bool withDebug, bool saveJson = true)
{
    try
    {
        using var frame = SerializationContext.BeginFrame(true);
        
        // 保存 JSON（可读格式，用于调试）
        if (saveJson)
        {
            var json = JSONSerializer.Serialize(typeof(T), instance, true);
            var debugJsonPath = FormatFSDebugJsonPath(path);
            File.WriteAllText(debugJsonPath, json, Encoding.UTF8);
        }

        // 保存二进制 debug 版本（含调试信息）
        if (withDebug)
        {
            var bytes = MemoryPackSerializeHelper.SerializeToBytes(typeof(T), instance, false);
            var debugPath = FormatDebugPath(path);
            File.WriteAllBytes(debugPath, bytes);
        }
        
        // 保存二进制 release 版本（最终发布用）
        {
            using var frame1 = SerializationContext.BeginFrame(true);
            var releasePath = FormatReleasePath(path);
            File.WriteAllBytes(releasePath, 
                MemoryPackSerializeHelper.SerializeToBytes(typeof(T), instance, true));
        }
    }
    catch (Exception e)
    {
        Log.Error(ZString.Format("保存失败: {0}", path));
        Log.Error(e);
        return false;
    }
    return true;
}
```

文件命名规则：

| 文件格式 | 文件名规则 | 用途 |
|----------|-----------|------|
| JSON | `config.json` | 调试可读 |
| 二进制（调试版）| `config_d.bytes` | 含字段名，较大 |
| 二进制（发布版）| `config.bytes` | 无字段名，最小 |

---

## 路径格式化工具方法

```csharp
public static string FormatReleasePath(string path)
{
    var directory = Path.GetDirectoryName(path);
    var fileNameWithoutExt = RemoveExt(path);
    return ZString.Format("{0}/{1}.bytes", directory, fileNameWithoutExt);
}

public static string FormatDebugPath(string path)
{
    var directory = Path.GetDirectoryName(path);
    var fileNameWithoutExt = RemoveExt(path);
    return ZString.Format("{0}/{1}_d.bytes", directory, fileNameWithoutExt);
}

private static string RemoveExt(string path)
{
    var fileNameWithoutExt = Path.GetFileNameWithoutExtension(path);
    // 如果文件名以 "_d" 结尾，去掉这个后缀（debug 转 release 时使用）
    if (fileNameWithoutExt.EndsWith("_d"))
        fileNameWithoutExt = fileNameWithoutExt.Substring(0, fileNameWithoutExt.Length - 2);
    return fileNameWithoutExt;
}
```

注意 `RemoveExt` 会移除 `_d` 后缀——这意味着 debug 文件和 release 文件之间可以互相转换路径，构建工具可以自动化地处理这两种格式。

---

## ZString：零分配字符串格式化

代码中大量使用了 `ZString.Format` 而不是 `string.Format`：

```csharp
Log.Error(ZString.Format("资源未加载: {0}", path));
return ZString.Format("{0}/{1}.bytes", directory, fileNameWithoutExt);
```

`ZString` 是一个开源库（Cysharp/ZString），提供零 GC 的字符串格式化：

- `string.Format`：每次格式化创建新字符串对象，GC 分配
- `ZString.Format`：使用 Span<T> 和 ArrayPool，在大多数情况下零分配

在序列化路径（`Log.Error`、路径拼接）这类高频操作中，`ZString` 能显著减少 GC 压力。

---

## 实战：游戏配置系统集成

```csharp
// 策划配置定义
[Serializable]
public class HeroConfig
{
    public int id;
    public string name;
    public int maxHp;
    public int baseDamage;
    public List<int> skillIds;
}

// 加载配置（运行时）
public class ConfigManager
{
    private Dictionary<int, HeroConfig> _heroConfigs = new();
    
    public void LoadHeroConfigs()
    {
        // Deserialize 会根据运行环境自动选择格式
        var heroes = SerializeHelper.Deserialize<List<HeroConfig>>("HeroConfig");
        foreach (var hero in heroes)
        {
            _heroConfigs[hero.id] = hero;
        }
    }
    
    public HeroConfig GetHero(int id)
    {
        return _heroConfigs.TryGetValue(id, out var cfg) ? cfg : null;
    }
}

// 编辑器工具：保存配置
public class ConfigEditor
{
    public static void SaveHeroConfigs(List<HeroConfig> heroes)
    {
        string path = "Assets/GameCfg/HeroConfig";
        SerializeHelper.SerializeToFile(path, heroes, withDebug: true, saveJson: true);
        // 同时生成 .json（调试用）、_d.bytes（调试二进制）、.bytes（发布）三个文件
    }
}
```

---

## 总结

`SerializeHelper` 展示了一个实用的工程设计模式：

| 设计点 | 实现方式 |
|--------|---------|
| 多格式支持 | 编译宏控制 + 策略模式 |
| 嵌套上下文 | 帧栈（SerializationContext） |
| 生命周期管理 | IDisposable + using 语句 |
| 零 GC 日志 | ZString.Format |
| 调试/发布双版本 | 文件命名约定 |

对于新手，最重要的收获是：**序列化不只是"存数据读数据"这么简单**，还需要考虑格式选择、上下文管理、错误处理、调试便利性和发布优化等多个维度。

在实际项目中，一个设计良好的序列化工具可以为整个团队节省大量调试时间，也是游戏稳定上线的重要保障。
