---
title: 配置表系统设计与实现（LuBan + CfgManager）
published: 2024-01-01
description: "配置表系统设计与实现（LuBan + CfgManager） - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 配置与数据
draft: false
encryptedKey: henhaoji123
---

# 配置表系统设计与实现（LuBan + CfgManager）

## 1. 系统概述

本项目配置表系统基于 **LuBan**（鲁班）——一款开源的游戏配置工具，支持从 Excel/JSON 等多种数据源生成强类型 C# 代码和二进制数据文件。相比传统 CSV + 反射解析，LuBan 方案的优势：
- **零反射开销**：生成的代码直接访问字段，运行时无反射
- **多格式输出**：同一数据源可输出 bytes（运行时）+ json（调试）
- **类型安全**：编译期检查所有字段引用，配置改动第一时间发现错误
- **热更新支持**：配置数据作为 .bytes 文件可以随热更新包推送，不需要重新发包

---

## 2. 配置加载架构

```
Excel/JSON（策划填写）
    ↓ LuBan 工具生成
cfg.Tables（C# 入口类）
    ├── TbNumeric（数值配置表）
    ├── TbItem（道具配置表）
    ├── TbSkill（技能配置表）
    ├── TbBuff（Buff配置表）
    ├── TbStory（剧情配置表）
    └── ... (100+ 张表)

CfgManager（配置管理器）
    ├── 静态 tables 属性（懒加载 + 线程安全）
    ├── Reload() （热更后刷新）
    └── LoadByteBuf() （多平台加载逻辑）
```

---

## 3. CfgManager 核心实现

```csharp
// 位置：Hotfix/Battle/Model/GamePlay/Config/CfgManager.cs
public sealed class CfgManager
{
    private static Tables _cache;
    private static readonly object ReloadLock = new object();

    // 静态访问入口（懒加载，线程安全）
    public static Tables tables
    {
        get
        {
            lock (ReloadLock)
            {
                if (_cache == null) new CfgManager();
                return _cache;
            }
        }
    }

    // 热更新后重新加载所有配置
    // 调用时机：HybridCLR 热更新 DLL 加载完成后
    public static void Reload()
    {
        lock (ReloadLock)
        {
            _cache = null;
            new CfgManager();
        }
    }

    public CfgManager()
    {
        try
        {
            Tables = new Tables(LoadByteBuf);  // 传入加载函数，Table 按需读取
        }
        catch (Exception e)
        {
            Log.Error(e);
            Tables = new Tables(FailSafeBytesLoader);  // 出错时用空数据，防止崩溃
        }

        _cache = Tables;

#if UNITY_EDITOR
        OdinHelper.Reload();  // 编辑器下刷新 Odin Inspector 缓存
#endif
    }
```

### 3.1 多平台加载逻辑

```csharp
    private static ByteBuf LoadByteBuf(string file)
    {
        // 优先级 1：热更新目录（ResUpdate）
        // 热更新后的配置文件会放在 persistentDataPath 下
#if !UNITY_EDITOR
        string hotUpdatePath = Path.Combine(
            Application.persistentDataPath, 
            "ResUpdate", "Android", "HotUpdateDll", 
            ZString.Concat(file, ".bytes"));
        if (File.Exists(hotUpdatePath))
        {
            return new ByteBuf(File.ReadAllBytes(hotUpdatePath));
        }
#endif

        // 优先级 2：Addressables 加载（正式包 Runtime）
#if !UNITY_EDITOR && (UNITY_ANDROID || UNITY_IOS) && ONLY_CLIENT
        var result = AssetCache.GetCachedAsset<TextAsset>(
            ZString.Format("GameCfg/Data/{0}.bytes", file));
        if (result != null)
        {
            return new ByteBuf(result.bytes);
        }
        return null;

        // 优先级 3：编辑器下直接读文件
#elif UNITY_EDITOR
        string editorPath = ZString.Format(
            "{0}/../GameCfg/Data/{1}.bytes", 
            Application.dataPath, file);
        return new ByteBuf(File.ReadAllBytes(editorPath));

        // 优先级 4：PC 包（绝对路径）
#else
        return new ByteBuf(File.ReadAllBytes(
            ZString.Format("./GameCfg/Data/{0}.bytes", file)));
#endif
    }
```

### 3.2 预加载所有配置

```csharp
    // 在游戏启动时统一预加载（避免战斗中首次访问导致卡顿）
    public static async ETTask LoadAll()
    {
#if !UNITY_EDITOR
        var loader = LoaderComponent.Instance.Get("data");
        foreach (var path in Tables.GetConfigTablePaths())
        {
            // 将所有 .bytes 文件加入批量加载队列
            loader.AddLoadTask(ZString.Format("GameCfg/Data/{0}.bytes", path));
        }
        // 批量异步加载（带进度回调）
        await loader.StartLoadTaskAsync(null);
#endif
    }
```

---

## 4. LuBan 生成代码结构

LuBan 会根据 Excel/JSON 源文件自动生成以下代码：

```csharp
// 生成示例：技能配置表 TbSkill（简化）
namespace cfg.skill
{
    // 单条技能配置（对应 Excel 中的一行）
    public partial class Skill
    {
        // 字段直接对应表列，无需反射
        public int Id { get; init; }
        public string Name { get; init; }
        public int Damage { get; init; }
        public float CoolDown { get; init; }
        public List<int> BuffIds { get; init; }       // 关联 Buff 列表
        public ESkillType SkillType { get; init; }   // 枚举类型
        
        // 关联表引用（LuBan 可配置自动解析 ref）
        // public Buff[] Buffs { get; init; }  // 自动从 TbBuff 解引用
    }
    
    // 表对象（持有所有行）
    public partial class TbSkill
    {
        private readonly Dictionary<int, Skill> _dataMap;
        
        // 精确查找
        public Skill GetOrDefault(int id)
        {
            return _dataMap.TryGetValue(id, out var v) ? v : null;
        }
        
        // 枚举查找（枚举 ID 对应值的配置）
        public Skill GetOrDefault(ESkillId id)
        {
            return GetOrDefault((int)id);
        }
    }
}
```

---

## 5. 运行时查询示例

```csharp
// 以下是项目中实际使用配置表的方式

// 1. 查询技能配置
var skillCfg = CfgManager.tables.TbSkill.GetOrDefault(skillId);
if (skillCfg == null)
{
    Log.Error($"技能配置不存在: {skillId}");
    return;
}
int damage = skillCfg.Damage;
float cooldown = skillCfg.CoolDown;

// 2. 查询数值配置（ENumericId 枚举）
var numericCfg = CfgManager.tables.TbNumeric.GetOrDefault(ENumericId.Atk);

// 3. 查询剧情配置
var storyCfg = CfgManager.tables.TbStory.GetOrDefault(storyId);
var dialogList = storyCfg?.Dialogs;  // 对话列表

// 4. 带条件筛选
var availableItems = CfgManager.tables.TbItem.DataList
    .Where(item => item.ItemType == EItemType.Consumable)
    .OrderBy(item => item.Id)
    .ToList();
```

---

## 6. 配置热更新流程

配置数据可以作为热更包的一部分，不需要发新版本：

```
策划修改 Excel 配置
    ↓
LuBan 重新生成 .bytes 文件
    ↓
打包进热更资源包
    ↓ 玩家启动游戏
Dolphin 检测到新版本，下载热更包
    ↓ 写入 persistentDataPath/ResUpdate/
CfgManager.Reload()
    ↓
LoadByteBuf 优先从热更目录读取新配置
    ↓
新配置立即生效（无需重启）
```

---

## 7. OdinHelper —— 编辑器配置预览

```csharp
// 编辑器下，通过 Odin Inspector 在 Inspector 面板中直接预览配置
public static class OdinHelper
{
    // 配置刷新后，通知 Odin 刷新所有使用了配置的 Inspector 面板
    public static void Reload()
    {
        // OdinInspector 的特殊刷新 API
        UnityEditor.EditorApplication.delayCall += () =>
        {
            // 刷新所有已打开的 Inspector
        };
    }
}
```

---

## 8. 常见问题与最佳实践

**Q: 配置表字段改了，旧的热更包里的数据会崩溃吗？**  
A: 字段改名/删除可能导致兼容性问题。建议只新增字段，标记旧字段为 Deprecated 而非删除。LuBan 支持字段有默认值的向后兼容模式。

**Q: GetOrDefault 返回 null 时如何处理？**  
A: 配置缺失通常是策划填表错误，应 `Log.Error` 记录并使用安全默认值继续运行。战斗逻辑不能因为配置缺失直接抛异常崩溃。

**Q: 配置文件很大，启动加载慢怎么办？**  
A: 使用 `LoadAll` 的进度回调显示加载进度条，让玩家感知到进度。可以拆分为必要配置（首次进入前加载）和延迟配置（进游戏后后台加载）两类。

**Q: 多线程并发访问 CfgManager.tables 安全吗？**  
A: `lock(ReloadLock)` 保证了初始化的线程安全。但 `Tables` 对象本身是不可变的（字段全部 `init`），读操作天然线程安全，无需额外锁。

**Q: 编辑器模式下如何快速验证配置修改？**  
A: 调用 `CfgManager.Reload()` 即可，无需重启 Unity。可以在编辑器菜单中添加快捷按钮。
