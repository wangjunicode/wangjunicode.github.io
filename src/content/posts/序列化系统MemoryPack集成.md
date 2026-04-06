---
title: 10 序列化系统 MemoryPack 集成
published: 2024-01-01
description: "10 序列化系统 MemoryPack 集成 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 10 序列化系统 MemoryPack 集成

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

序列化（Serialization）是将内存中的对象转换为字节流（或字符串）以便存储/传输的过程，反序列化则是逆操作。在游戏开发中，序列化用于：

- **配置表加载**：将编辑器导出的二进制配置文件还原为 C# 对象
- **存档读写**：将游戏状态保存到磁盘或云端
- **网络通信**：将消息结构体序列化后通过网络传输
- **对象克隆**：序列化 + 反序列化实现深拷贝

本项目的序列化系统集成了 **MemoryPack**（高性能二进制序列化）和 **FullSerializer（JSON）** 两套方案，并在 ECS 框架层提供了 `IDeserialize` 接口和 `DeserializeSystem<T>` 用于 Entity 的反序列化后回调。

### 核心文件

| 文件 | 位置 | 职责 |
|---|---|---|
| `MemoryPackSerializeHelper.cs` | `Hotfix/Base/Module/Serialize/MemoryPack/` | MemoryPack 序列化入口（带压缩） |
| `MemoryPackInitializer.cs` | `Hotfix/Base/Module/Serialize/MemoryPack/` | 注册 TrueSync 自定义格式化器 |
| `SerializeHelper.cs` | `Hotfix/Base/Module/Serialize/` | 统一序列化门面（编辑器/运行时适配） |
| `SerializeDelegates.cs` | `Hotfix/Base/Module/Serialize/` | 资源加载解耦委托 |
| `IDeserializeSystem.cs` | `Core/EventSystem/` | ECS 框架的反序列化系统接口 |
| `ISerializeToEntity.cs` | `Core/EventSystem/` | 标记 Entity 子节点参与序列化 |

---

## 2. 架构设计

### 2.1 序列化系统层次

```
业务层（游戏配置/存档）
      ↓ 调用
SerializeHelper（统一门面）
  ├── 运行时：MemoryPack + Brotli 压缩    ← Release 模式（.bytes 文件）
  └── 编辑器：JSONSerializer（FullSerializer） ← 调试模式（.json 文件）
      ↓ 底层依赖
MemoryPackSerializeHelper（封装压缩/解压）
  ├── MemoryPackSerializer.Serialize()
  ├── BrotliCompressor（压缩）
  └── BrotliDecompressor（解压）

加载解耦层：
SerializeDelegates.LoadFunc
  → 由 ResourceManager 注入（资源加载策略与序列化解耦）
```

### 2.2 双模式设计

```
UNITY_EDITOR && 非 ONLY_CLIENT：
  UseBinary = false  → JSON 格式（可读，便于调试）
  UseRelease = false → 使用 debug 模式序列化（字段名可见）

Release 打包（ONLY_CLIENT）：
  UseBinary = true   → MemoryPack 二进制（高性能，体积小）
  UseRelease = true  → 字段名不写入序列化结果（对象池友好）
```

### 2.3 ECS 框架的序列化集成

```
Entity 树序列化设计：
  Entity
  ├── componentsDB: HashSet<Entity>   ← 标记了 ISerializeToEntity 的 Component
  └── childrenDB: HashSet<Entity>     ← 标记了 ISerializeToEntity 的 Child

Domain 首次设置时：
  if (!this.IsCreated)
  {
      this.IsCreated = true;
      EventSystem.Instance.Deserialize(this);  ← 触发 DeserializeSystem
  }
```

---

## 3. 核心代码展示

### 3.1 MemoryPackSerializeHelper —— 带压缩的序列化器

```csharp
// X:\UnityProj\Assets\Scripts\Hotfix\Base\Module\Serialize\MemoryPack\MemoryPackSerializeHelper.cs

public static class MemoryPackSerializeHelper
{
    // 序列化到字节数组（内置 Brotli 压缩）
    public static byte[] SerializeToBytes<T>(T obj, bool release = true)
    {
        var oldUseRelease = MemoryPackSerializer.release;
        using var compressor = new BrotliCompressor();   // Brotli 压缩器（高压缩比）
        MemoryPackSerializer.release = release;           // release=true 时不写字段名
        MemoryPackSerializer.Serialize(compressor, obj);  // 序列化到压缩流
        MemoryPackSerializer.release = oldUseRelease;     // 还原设置
        var bytes = compressor.ToArray();
        return bytes;
    }

    // 从字节数组反序列化（内置 Brotli 解压）
    public static T DeserializeFromBytes<T>(byte[] bytes, bool release = true)
    {
        var oldUseRelease = MemoryPackSerializer.release;
        using var decompressor = new BrotliDecompressor();
        var buffer = decompressor.Decompress(bytes);      // 先解压
        MemoryPackSerializer.release = release;
        var o = MemoryPackSerializer.Deserialize<T>(buffer);  // 再反序列化
        MemoryPackSerializer.release = oldUseRelease;
        return o;
    }

    // 反序列化到已有对象（避免分配新对象，对象池友好）
    public static void DeserializeFromBytesOverride<T>(byte[] bytes, T obj, bool release = true)
        where T : class
    {
        var oldUseRelease = MemoryPackSerializer.release;
        using var decompressor = new BrotliDecompressor();
        var buffer = decompressor.Decompress(bytes);
        MemoryPackSerializer.release = release;
        MemoryPackSerializer.Deserialize<T>(buffer, ref obj);  // ref 传入，在原对象上覆写
        MemoryPackSerializer.release = oldUseRelease;
    }

    // 深拷贝：序列化后反序列化到同一对象（就地覆写）
    public static void Clone<T>(T from, T to, bool release = true) where T : class
    {
        DeserializeFromBytesOverride(SerializeToBytes(from, release), to, release);
    }

    // 深拷贝：序列化后反序列化，返回新对象
    public static T Clone<T>(T obj, bool release = true)
    {
        return DeserializeFromBytes<T>(SerializeToBytes<T>(obj, release), release);
    }

    // 非泛型版本（仅知道 Type 时使用）
    public static byte[] SerializeToBytes(Type type, object obj, bool release = true) { ... }
    public static object DeserializeFromBytes(Type type, byte[] bytes, bool release = true) { ... }
}
```

### 3.2 MemoryPackInitializer —— 注册自定义格式化器

```csharp
// X:\UnityProj\Assets\Scripts\Hotfix\Base\Module\Serialize\MemoryPack\MemoryPackInitializer.cs

public class MemoryPackInitializer
{
    public static void RegisterInitialFormatters()
    {
        // 为 TrueSync 物理库的 unmanaged struct 注册 MemoryPack 格式化器
        Register<FP>();          // 定点数（Fixed Point，避免浮点不确定性）
        Register<TSVector2>();   // 2D 向量
        Register<TSVector>();    // 3D 向量
        Register<TSVector4>();   // 4D 向量
        Register<TSQuaternion>(); // 四元数
    }

    // 为 unmanaged struct 注册标准格式化器组合
    static void Register<T>() where T : unmanaged
    {
        MemoryPackFormatterProvider.Register(new UnmanagedFormatter<T>());       // T
        MemoryPackFormatterProvider.Register(new UnmanagedArrayFormatter<T>());   // T[]
        MemoryPackFormatterProvider.Register(new ListFormatter<T>());             // List<T>
        MemoryPackFormatterProvider.Register(new NullableFormatter<T>());         // T?
    }
}
```

### 3.3 SerializeHelper —— 统一序列化门面

```csharp
// X:\UnityProj\Assets\Scripts\Hotfix\Base\Module\Serialize\SerializeHelper.cs（节选）

public class SerializeHelper
{
    // 编译时决定使用的模式
#if UNITY_EDITOR || !ONLY_CLIENT
    public static bool UseBinary = false;  // 编辑器下默认使用 JSON
    public static bool UseRelease = false;
#else
    public static bool UseBinary = true;   // 发布包使用 MemoryPack 二进制
    public static bool UseRelease = true;
#endif

    // 运行时反序列化（兼容二进制和JSON）
    public static T Deserialize<T>(string path, bool release = true)
    {
        try
        {
            using var frame = SerializationContext.BeginFrame(false);

            if (UseBinary)
            {
                // 通过委托加载字节数组（资源管理系统决定如何加载）
                byte[] bytes = SerializeDelegates.Load<byte[]>(path);
                if (bytes == null)
                {
                    Log.Error($"资源未加载: {path}");
                    return default;
                }
                return MemoryPackSerializeHelper.DeserializeFromBytes<T>(bytes, release);
            }
            else
            {
                // JSON 模式（编辑器调试）
                string json = SerializeDelegates.Load<string>(path);
                return JSONSerializer.Deserialize<T>(json);
            }
        }
        catch (Exception e)
        {
            Log.Error(e);
            Log.Error($"反序列化失败: {path}");
            return default;
        }
    }
}
```

### 3.4 SerializeDelegates —— 资源加载解耦

```csharp
// X:\UnityProj\Assets\Scripts\Hotfix\Base\Module\Serialize\SerializeDelegates.cs

public class SerializeDelegates
{
    // 加载函数：由外部（ResourceManager）注入
    internal static Func<string, object> LoadFunc;

    public static T Load<T>(string path)
    {
        if (LoadFunc == null)
            throw new Exception("Serialize Module 未初始化，请查阅README.md");
        return (T)LoadFunc(path);
    }
}

// 初始化（在游戏启动时注入加载函数）
// X:\UnityProj\Assets\Scripts\Hotfix\Base\Module\Serialize\SerializeInitialization.cs
public class SerializeInitialization
{
    public static void Initialize(Func<string, object> func)
    {
        SerializeDelegates.LoadFunc = func;  // 注入资源加载策略
    }
}
```

### 3.5 ECS 层的 IDeserializeSystem

```csharp
// X:\UnityProj\Assets\Scripts\Core\EventSystem\IDeserializeSystem.cs

public interface IDeserialize { }  // 标记接口：表示此 Entity 需要反序列化后回调

[ObjectSystem]
[EntitySystem]
public abstract class DeserializeSystem<T> : IDeserializeSystem where T : Entity, IDeserialize
{
    void IDeserializeSystem.Run(Entity o)
    {
        this.Deserialize((T)o);
    }

    // 子类实现：在 Entity 首次挂到 ECS 树时（Domain 首次设置）调用
    protected abstract void Deserialize(T self);
}

// 触发时机（Entity.Domain 的 setter 中）：
if (!this.IsCreated)
{
    this.IsCreated = true;
    EventSystem.Instance.Deserialize(this);  // ← 调用 DeserializeSystem
}
```

### 3.6 ISerializeToEntity —— 控制子节点序列化

```csharp
// X:\UnityProj\Assets\Scripts\Core\EventSystem\ISerializeToEntity.cs
public interface ISerializeToEntity { }

// 作用：实现此接口的 Entity 子节点会被放入 childrenDB/componentsDB
// 这两个 HashSet 会被 MemoryPack 序列化，恢复时自动重建父子关系

// 示例：背包数据需要持久化，而特效 Entity 不需要
public class BagComponent : Entity, IAwake, ISerializeToEntity { } // ← 会被序列化
public class EffectEntity : Entity, IAwake { }                     // ← 不会被序列化
```

---

## 4. MemoryPack 基础知识

### 4.1 为什么选择 MemoryPack？

| 对比项 | JSON | BinaryFormatter | MemoryPack |
|---|---|---|---|
| 性能 | 慢 | 中 | **极快**（接近零分配） |
| 体积 | 大 | 中 | 小（+ Brotli 后更小） |
| 可读性 | 高 | 低 | 低 |
| 对象池支持 | 无 | 无 | **有**（`ref T` 覆写反序列化） |
| .NET 支持 | 所有版本 | 已废弃 | .NET 6+（Unity 2022+） |

### 4.2 如何标记可序列化类型

```csharp
// 方式1：标记 [MemoryPackable]（标准 MemoryPack 方式）
[MemoryPackable]
public partial class ItemConfig
{
    public int Id;
    public string Name;
    public float Damage;
}

// 方式2：框架中通过代码生成器（T4/Roslyn Source Generator）自动生成序列化代码
// 配置表类通常由工具自动生成，开发者无需手动标记

// 方式3：unmanaged struct 使用 UnmanagedFormatter（见 MemoryPackInitializer）
[StructLayout(LayoutKind.Sequential)]
public struct TSVector
{
    public FP x, y, z;  // 全部是 FP（unmanaged struct），可直接内存拷贝
}
```

### 4.3 release 参数的含义

```csharp
// release = false（Debug 模式）：
//   - 序列化时写入字段名（便于调试，可用工具查看内容）
//   - 序列化结果体积较大

// release = true（Release 模式）：
//   - 序列化时只写值，不写字段名
//   - 支持对象池（反序列化时可覆写已有对象）
//   - 序列化结果更紧凑

// ⚠️ 重要：用 release=false 序列化的数据，必须用 release=false 反序列化！
//    反之亦然。不匹配会导致数据损坏。
```

---

## 5. 配置表加载完整流程

以加载技能配置为例：

```
工具链（策划）：
  Excel 配置 → 导出工具 → 生成 C# 类 + 序列化 .bytes 文件
         ↓
构建流程（程序）：
  .bytes 文件 → 打包进 AssetBundle 或 StreamingAssets
         ↓
运行时（Unity）：
  ResourceManager.Load("skill_config") 
    → 返回 byte[]
    → SerializeDelegates.LoadFunc(path) 被调用
    → MemoryPackSerializeHelper.DeserializeFromBytes<SkillConfig>(bytes)
    → 返回 SkillConfig 对象
    → ConfigManager 缓存并提供查询接口
```

### 代码示例

```csharp
// 初始化（注入资源加载策略）
SerializeInitialization.Initialize(path =>
    ResourceManager.Instance.LoadBytes($"GameCfg/{path}"));

// MemoryPack 自定义类型注册（游戏启动时）
MemoryPackInitializer.RegisterInitialFormatters();

// 加载配置
SkillConfig config = SerializeHelper.Deserialize<SkillConfig>("skill_config");

// 或直接使用 MemoryPackSerializeHelper
byte[] bytes = File.ReadAllBytes("skill_config.bytes");
SkillConfig config = MemoryPackSerializeHelper.DeserializeFromBytes<SkillConfig>(bytes);
```

---

## 6. Entity 序列化与反序列化

ECS 框架提供了 Entity 树的序列化支持，主要用于战斗录像或存档：

### 6.1 标记需要序列化的节点

```csharp
// 背包组件需要持久化
[MemoryPackable]
public partial class BagComponent : Entity, IAwake, ISerializeToEntity
{
    // MemoryPack 会序列化这些字段
    public List<int> ItemIds = new();
    public List<int> ItemCounts = new();
}
```

### 6.2 反序列化后恢复运行时状态

```csharp
// 某些字段（如 Timer、委托）无法序列化，需要在 Deserialize 回调中恢复
[ObjectSystem]
public class BagComponentDeserializeSystem : DeserializeSystem<BagComponent>
{
    protected override void Deserialize(BagComponent self)
    {
        // 重建运行时索引（序列化时不存储，反序列化时从数据重建）
        self.RebuildIndex();

        // 重新注册定时任务等
        self.StartAutoSaveTimer();
    }
}
```

### 6.3 深拷贝 Entity 数据

```csharp
// 场景：战斗前保存玩家状态快照，战斗失败后恢复
BagComponent snapshot = MemoryPackSerializeHelper.Clone(playerBag);

// 或覆写到已有对象（避免 new，性能更好）
MemoryPackSerializeHelper.Clone(playerBag, backupBag);
```

---

## 7. Brotli 压缩集成

本框架在 MemoryPack 的基础上叠加了 Brotli 压缩，进一步减少磁盘和网络传输体积：

```
原始数据 → MemoryPack 序列化 → Brotli 压缩 → byte[]
byte[]   → Brotli 解压       → MemoryPack 反序列化 → 对象
```

**Brotli vs 其他压缩算法对比：**

| 算法 | 压缩比 | 速度 | 适用场景 |
|---|---|---|---|
| GZip | 中 | 中 | 通用压缩 |
| LZ4 | 低 | **极快** | 实时压缩（网络包） |
| **Brotli** | **高** | 中 | 静态资源（配置表、存档） |
| Zstd | 高 | 快 | 现代压缩场景 |

配置表一般在加载时才解压，对解压速度不敏感，Brotli 的高压缩比能显著减小包体大小。

---

## 8. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| 序列化格式 | MemoryPack（无压缩）| MemoryPack + **Brotli 压缩** |
| JSON 支持 | 有（MongoDB JSON） | 有（FullSerializer，支持编辑器调试） |
| `ISerializeToEntity` | 有 | 相同 |
| `DeserializeSystem` | 有 | 相同 |
| 资源加载解耦 | 直接文件IO | `SerializeDelegates` 委托注入，与资源管理系统解耦 |
| `release` 模式切换 | 手动传参 | `SerializeHelper.UseBinary/UseRelease` 自动根据编译宏切换 |
| TrueSync 类型支持 | 无 | **新增** `MemoryPackInitializer` 注册 FP/TSVector 等 |
| `Clone()` 方法 | 无 | **新增** 两种深拷贝重载 |

---

## 9. 常见问题与最佳实践

### Q1：为什么编辑器下要用 JSON，发布包用二进制？

1. **开发效率**：JSON 可以直接用文本编辑器查看，方便调试配置表内容
2. **性能**：二进制格式体积更小、加载更快，发布包优先
3. **一致性**：发布包的二进制文件在编辑器中也可以用 debug 模式（带字段名）读取，便于测试

### Q2：序列化数据升级（字段增删）怎么处理？

MemoryPack 支持字段的向后兼容，但需要遵循规则：
- 新增字段：放到末尾，旧格式读新版本时会用默认值填充
- 删除字段：用 `[MemoryPackIgnore]` 标记，不能直接删除（会破坏字段顺序）

### Q3：`ref T` 反序列化是什么意思？

```csharp
// MemoryPackSerializer.Deserialize<T>(buffer, ref obj)
// 不创建新对象，直接在 obj 上覆写字段值
// 这允许反序列化到对象池中取出的已有对象，避免 GC

BagComponent pooledBag = ObjectPool.Instance.Fetch<BagComponent>();
MemoryPackSerializeHelper.DeserializeFromBytesOverride(bytes, pooledBag);
// pooledBag 现在持有最新数据，但内存是复用的
```

### Q4：如何调试二进制序列化数据？

1. 编辑器模式下 `UseRelease=false`，生成的 `_d.bytes` 文件包含字段名
2. 可通过 `SerializeHelper.DeserializeInEditor<T>(path)` 加载查看
3. 也可以将数据序列化为 JSON 用于比对：`SerializeHelper.SerializeToJson(obj)`

---

## 10. 总结

本框架的序列化系统是一个**双模式 + 分层架构**的设计：

1. **底层**：MemoryPack + Brotli 提供高性能的二进制序列化
2. **中层**：`MemoryPackSerializeHelper` 封装压缩/解压细节
3. **上层**：`SerializeHelper` 根据编译宏自动选择 JSON（调试）或二进制（发布）
4. **解耦层**：`SerializeDelegates` 将资源加载与序列化分离

ECS 层面的 `ISerializeToEntity` + `DeserializeSystem<T>` 提供了 Entity 树序列化的钩子机制，让运行时状态（定时器、委托等不可序列化的字段）能在反序列化后安全恢复。

对于新手，最重要的实践：
1. **配置表加载**：统一使用 `SerializeHelper.Deserialize<T>()` 而不是直接调用 MemoryPack
2. **debug/release 模式匹配**：序列化和反序列化必须使用相同的 `release` 参数
3. **DeserializeSystem**：凡是有运行时状态（非纯数据字段）的 Entity，都应实现 `IDeserialize` 并编写 `DeserializeSystem`
