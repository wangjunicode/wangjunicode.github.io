---
title: 数据传输对象（DTO）模式：分离传输结构与领域模型的工程实践
published: 2026-03-31
description: 深入解析 DTO 在游戏开发中的应用场景，理解为什么要将网络传输数据与游戏领域对象分离，以及如何设计易于序列化的数据结构。
tags: [Unity, 设计模式, 网络编程, 数据设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## DTO 是什么？

**DTO（Data Transfer Object，数据传输对象）** 是一种用于在不同层之间传输数据的简单对象。它的特点是：

- 只有数据字段，没有业务方法
- 专门为数据传输（序列化）优化
- 不包含业务逻辑

在游戏开发中，DTO 主要用于：
1. **网络消息**：客户端与服务器之间的数据交换
2. **存档数据**：游戏进度序列化到磁盘
3. **配置数据**：从 JSON/二进制读取的配置表数据

---

## 为什么需要 DTO？直接用领域对象不行吗？

假设你的角色类（领域对象）是这样的：

```csharp
public class Character : Entity
{
    public int Id;
    public string Name;
    public int Hp;
    public int MaxHp;
    
    // 大量引用类型字段
    public List<Skill> Skills;         // 技能列表（技能对象很重）
    public Dictionary<int, Item> Items; // 背包（每个道具有 Sprite 等资源）
    public Animator Animator;          // Unity 组件（不可序列化）
    public Transform Transform;        // Unity 组件（不可序列化）
    
    // 大量业务方法
    public void Attack(Character target) { ... }
    public void TakeDamage(int damage) { ... }
    public void LevelUp() { ... }
}
```

如果直接序列化这个对象：
1. 无法序列化 `Animator`、`Transform`（Unity 组件）
2. 序列化整个 `Skill` 对象树太大了
3. 客户端不需要发送所有字段给服务器

---

## 定义角色 DTO

```csharp
// 网络传输用 DTO（精简、序列化友好）
[MemoryPackable]
public partial class CharacterDTO
{
    public int Id;
    public string Name;
    public int Hp;
    public int MaxHp;
    public int Level;
    public long UserId;
    
    // 技能只传 ID，不传完整对象
    public int[] SkillIds;
    
    // 装备只传 ID
    public int[] EquipItemIds;
    
    // 位置（帧同步用定点数）
    public long PositionX;
    public long PositionY;
    public long PositionZ;
}

// 存档 DTO（包含更多数据，但仍然精简）
[MemoryPackable]
public partial class CharacterSaveDTO
{
    public int Id;
    public int Level;
    public int Exp;
    public int Hp;
    
    // 背包（只存 ID 和数量）
    public ItemSaveDTO[] Items;
    
    // 任务进度
    public QuestProgressDTO[] Quests;
    
    // 最后登出时间
    public long LastLogoutTime;
}

[MemoryPackable]
public partial class ItemSaveDTO
{
    public int ItemId;
    public int Count;
    public int EquipSlot;  // -1 = 背包, 0-5 = 装备槽
}
```

---

## DTO 与领域对象的转换

DTO 只是数据容器，需要转换为领域对象才能使用：

```csharp
// 转换器（Mapper）
public static class CharacterMapper
{
    // DTO → 领域对象
    public static void Apply(Character character, CharacterDTO dto)
    {
        character.Name = dto.Name;
        character.Hp = dto.Hp;
        character.MaxHp = dto.MaxHp;
        character.Level = dto.Level;
        
        // 根据 SkillId 从配置表创建技能对象
        character.Skills.Clear();
        foreach (var skillId in dto.SkillIds)
        {
            var skillConfig = ConfigManager.GetSkill(skillId);
            character.Skills.Add(new Skill(skillConfig));
        }
    }
    
    // 领域对象 → DTO
    public static CharacterDTO ToDTO(Character character)
    {
        return new CharacterDTO
        {
            Id = character.Id,
            Name = character.Name,
            Hp = character.Hp,
            MaxHp = character.MaxHp,
            Level = character.Level,
            SkillIds = character.Skills.Select(s => s.SkillId).ToArray(),
            EquipItemIds = character.GetEquippedItemIds()
        };
    }
}
```

---

## 配置表 DTO

配置表数据通常是只读的，直接用 DTO 作为配置对象：

```csharp
// 技能配置（从 JSON/二进制读取）
[MemoryPackable]
public partial class SkillConfig
{
    public int Id;
    public string Name;
    public string Description;
    public int Damage;
    public int ManaCost;
    public float CooldownSeconds;
    public int[] EffectIds;     // 特效 ID 列表
    public int[] BuffIds;       // 施加的 Buff 列表
    public string IconPath;     // 图标资源路径
    public string AnimationName; // 动画状态名
}

// 配置管理器：加载并缓存
public class ConfigManager : Singleton<ConfigManager>
{
    private Dictionary<int, SkillConfig> _skillConfigs = new();
    
    public void LoadAll()
    {
        var configs = SerializeHelper.Deserialize<List<SkillConfig>>("Configs/Skills");
        foreach (var config in configs)
        {
            _skillConfigs[config.Id] = config;
        }
    }
    
    public SkillConfig GetSkill(int id)
    {
        return _skillConfigs.TryGetValue(id, out var config) ? config : null;
    }
}
```

---

## DTO 设计的核心原则

| 原则 | 说明 |
|------|------|
| 精简字段 | 只包含传输所需的字段 |
| 值类型优先 | int/float/string 比引用类型好序列化 |
| 用 ID 替代引用 | `int skillId` 而不是 `Skill skill` |
| 无业务方法 | DTO 不处理业务逻辑 |
| 序列化友好 | `[MemoryPackable]` 或 `[Serializable]` |

---

## 总结

DTO 模式在游戏中的价值：

1. **解耦**：网络结构变化不影响领域模型，反之亦然
2. **安全**：只传必要字段，不泄露服务器内部结构
3. **性能**：精简的 DTO 序列化更快，包更小
4. **清晰**：明确区分"传输数据"和"游戏数据"

DTO 看似简单，但在大型项目中是维护代码清洁度的重要工具。掌握 DTO 模式，是从"能跑起来"到"工程师代码"的重要一步。
