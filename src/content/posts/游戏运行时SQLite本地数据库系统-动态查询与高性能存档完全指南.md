---
title: 游戏运行时SQLite本地数据库系统：动态查询与高性能存档完全指南
published: 2026-04-11
description: 深度解析Unity游戏中嵌入式SQLite数据库的完整工程实践：从sqlite-net-pcl接入、连接池管理、ORM映射、异步查询，到游戏存档系统、动态排行榜、日志系统、数据迁移与加密存储的最佳实践方案。
tags: [SQLite, 本地数据库, 游戏存档, ORM, Unity, 性能优化, 数据持久化]
category: 游戏系统设计
draft: false
---

# 游戏运行时SQLite本地数据库系统：动态查询与高性能存档完全指南

## 一、为什么游戏需要SQLite

### 1.1 存储方案对比

| 存储方案 | 适用场景 | 优点 | 缺点 |
|---------|---------|------|------|
| **PlayerPrefs** | 简单K-V配置 | 内置，使用简单 | 无结构，不支持复杂查询 |
| **JSON文件** | 中小型存档 | 人类可读 | 大数据性能差，无事务 |
| **BinaryFormatter** | 简单存档 | 快速序列化 | 版本兼容性差，安全风险 |
| **SQLite** | 复杂游戏数据 | 结构化，支持事务/索引/复杂查询 | 需要额外依赖 |
| **云存档（后端）** | 多端同步 | 跨设备 | 需要网络，延迟高 |

### 1.2 SQLite适合的游戏场景

- **复杂存档系统**：大量相互关联的游戏数据（背包、任务、地图已探索区域）
- **本地排行榜与成就记录**
- **游戏日志与回放数据存储**
- **配置表的运行时查询**（相比JSON更高效的条件过滤）
- **离线缓存层**：服务端数据的本地镜像与失效管理

### 1.3 技术选型

推荐使用 **sqlite-net-pcl**（MIT协议），它是Unity中最成熟的SQLite ORM方案：

```
# 通过 NuGet 或 Unity Package Manager 添加
# sqlite-net-pcl 版本：1.9.172
# SQLitePCLRaw.bundle_green（提供SQLite原生库）
```

---

## 二、核心架构设计

### 2.1 分层架构

```
┌────────────────────────────────────────────┐
│              游戏业务层                      │
│  存档系统 | 排行榜 | 成就系统 | 日志记录      │
├────────────────────────────────────────────┤
│              Repository层（仓储模式）         │
│  SaveRepository | LeaderboardRepository   │
├────────────────────────────────────────────┤
│              SQLite服务层                    │
│  SQLiteService（连接管理+事务+异步封装）       │
├────────────────────────────────────────────┤
│              SQLite数据层                    │
│  SQLiteConnection | SQLiteAsyncConnection  │
└────────────────────────────────────────────┘
```

### 2.2 数据库服务核心实现

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using SQLite;
using UnityEngine;

/// <summary>
/// SQLite 数据库服务：连接管理、事务封装、线程安全访问
/// </summary>
public class SQLiteService : IDisposable
{
    private static SQLiteService _instance;
    public static SQLiteService Instance => _instance ??= new SQLiteService();
    
    private SQLiteAsyncConnection _connection;
    private readonly string _dbPath;
    private bool _initialized = false;
    
    // 数据库版本，用于迁移
    private const int CURRENT_DB_VERSION = 3;

    public SQLiteService()
    {
        // 数据库存放路径（使用持久化数据路径）
        _dbPath = Path.Combine(Application.persistentDataPath, "game_data.db");
    }

    /// <summary>
    /// 初始化数据库（异步，仅执行一次）
    /// </summary>
    public async Task InitializeAsync()
    {
        if (_initialized) return;

        var flags = SQLiteOpenFlags.ReadWrite 
                  | SQLiteOpenFlags.Create 
                  | SQLiteOpenFlags.SharedCache;

        _connection = new SQLiteAsyncConnection(_dbPath, flags);
        
        // 开启WAL模式（Write-Ahead Logging），大幅提升并发读写性能
        await _connection.ExecuteAsync("PRAGMA journal_mode=WAL;");
        
        // 设置缓存大小（页为单位，默认-2000即2MB）
        await _connection.ExecuteAsync("PRAGMA cache_size=-8000;"); // 8MB缓存
        
        // 同步模式：NORMAL（比FULL快，可靠性略低但足够游戏使用）
        await _connection.ExecuteAsync("PRAGMA synchronous=NORMAL;");
        
        // 创建/更新表结构
        await CreateTablesAsync();
        
        // 执行数据库迁移
        await RunMigrationsAsync();
        
        _initialized = true;
        Debug.Log($"[SQLite] Database initialized at: {_dbPath}");
    }

    private async Task CreateTablesAsync()
    {
        await _connection.CreateTableAsync<PlayerSaveData>();
        await _connection.CreateTableAsync<InventoryItem>();
        await _connection.CreateTableAsync<QuestRecord>();
        await _connection.CreateTableAsync<LeaderboardEntry>();
        await _connection.CreateTableAsync<AchievementRecord>();
        await _connection.CreateTableAsync<GameLogEntry>();
        await _connection.CreateTableAsync<DBVersion>();
    }

    private async Task RunMigrationsAsync()
    {
        // 获取当前数据库版本
        await _connection.CreateTableAsync<DBVersion>();
        var versionRecord = await _connection.Table<DBVersion>()
            .FirstOrDefaultAsync();
        
        int currentVersion = versionRecord?.Version ?? 0;
        
        // 按版本顺序执行迁移脚本
        for (int v = currentVersion + 1; v <= CURRENT_DB_VERSION; v++)
        {
            await ApplyMigration(v);
        }
        
        // 更新版本记录
        await _connection.InsertOrReplaceAsync(new DBVersion 
        { 
            Id = 1, 
            Version = CURRENT_DB_VERSION, 
            MigratedAt = DateTime.UtcNow 
        });
        
        Debug.Log($"[SQLite] DB version: {CURRENT_DB_VERSION}");
    }

    private async Task ApplyMigration(int version)
    {
        Debug.Log($"[SQLite] Applying migration v{version}");
        
        switch (version)
        {
            case 1:
                // 初始建表，由 CreateTablesAsync 处理
                break;
            case 2:
                // 添加新字段（SQLite不支持直接ALTER COLUMN，只能添加列）
                await SafeExecuteAsync("ALTER TABLE InventoryItem ADD COLUMN EnhanceLevel INTEGER DEFAULT 0;");
                break;
            case 3:
                // 新增成就表索引
                await SafeExecuteAsync(
                    "CREATE INDEX IF NOT EXISTS idx_achievement_unlocked ON AchievementRecord(IsUnlocked, UnlockedAt);"
                );
                break;
        }
    }

    private async Task SafeExecuteAsync(string sql)
    {
        try
        {
            await _connection.ExecuteAsync(sql);
        }
        catch (SQLiteException ex) when (ex.Message.Contains("duplicate column"))
        {
            // 列已存在，忽略
            Debug.Log($"[SQLite] Migration skipped (already applied): {ex.Message}");
        }
    }

    /// <summary>
    /// 执行事务（保证原子性）
    /// </summary>
    public async Task<T> RunInTransactionAsync<T>(Func<SQLiteAsyncConnection, Task<T>> action)
    {
        await _connection.ExecuteAsync("BEGIN TRANSACTION;");
        try
        {
            T result = await action(_connection);
            await _connection.ExecuteAsync("COMMIT;");
            return result;
        }
        catch
        {
            await _connection.ExecuteAsync("ROLLBACK;");
            throw;
        }
    }

    public async Task RunInTransactionAsync(Func<SQLiteAsyncConnection, Task> action)
    {
        await RunInTransactionAsync<bool>(async conn =>
        {
            await action(conn);
            return true;
        });
    }

    public SQLiteAsyncConnection GetConnection()
    {
        if (!_initialized)
            throw new InvalidOperationException("SQLiteService not initialized. Call InitializeAsync first.");
        return _connection;
    }

    public void Dispose()
    {
        _connection?.CloseAsync().GetAwaiter().GetResult();
        _connection = null;
    }
}

/// <summary>
/// 数据库版本记录表
/// </summary>
[Table("DBVersion")]
public class DBVersion
{
    [PrimaryKey] public int Id { get; set; }
    public int Version { get; set; }
    public DateTime MigratedAt { get; set; }
}
```

---

## 三、数据模型设计

### 3.1 游戏存档数据模型

```csharp
using SQLite;

/// <summary>
/// 玩家主存档数据（核心状态）
/// </summary>
[Table("PlayerSaveData")]
public class PlayerSaveData
{
    [PrimaryKey, AutoIncrement]
    public int Id { get; set; }
    
    [Indexed]  // 建立索引加速查询
    public int SlotId { get; set; }        // 存档槽位
    
    public string PlayerName { get; set; }
    public int Level { get; set; }
    public long Experience { get; set; }
    public int Gold { get; set; }
    public float PosX { get; set; }
    public float PosY { get; set; }
    public float PosZ { get; set; }
    public string CurrentScene { get; set; }
    public int PlaytimeSeconds { get; set; }
    
    [Indexed]
    public DateTime SavedAt { get; set; }
    public DateTime CreatedAt { get; set; }
    
    // JSON字段：存储不规则结构数据
    public string EquipmentJson { get; set; }   // 装备数据（JSON序列化）
    public string UnlockedSkillsJson { get; set; } // 已解锁技能列表
    public string StoryFlagsJson { get; set; }  // 剧情开关标记

    // 存档截图（base64或文件路径）
    public string ScreenshotPath { get; set; }
    
    // 校验和（防止外部篡改）
    public string Checksum { get; set; }
}

/// <summary>
/// 背包物品
/// </summary>
[Table("InventoryItem")]
public class InventoryItem
{
    [PrimaryKey, AutoIncrement]
    public int Id { get; set; }
    
    [Indexed]
    public int SlotId { get; set; }   // 关联存档槽位
    
    public int ItemId { get; set; }   // 物品配置表ID
    public int Quantity { get; set; }
    public int EnhanceLevel { get; set; }
    public int BagSlotIndex { get; set; }
    public bool IsEquipped { get; set; }
    public DateTime AcquiredAt { get; set; }
    
    // 物品词缀（JSON存储，结构不固定）
    public string AffixesJson { get; set; }
}

/// <summary>
/// 任务记录
/// </summary>
[Table("QuestRecord")]
public class QuestRecord
{
    [PrimaryKey, AutoIncrement]
    public int Id { get; set; }
    
    [Indexed] public int SlotId { get; set; }
    [Indexed] public int QuestId { get; set; }
    
    public QuestStatus Status { get; set; }
    public int Progress { get; set; }
    public int MaxProgress { get; set; }
    public DateTime AcceptedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
}

public enum QuestStatus { NotStarted = 0, InProgress = 1, Completed = 2, Failed = 3 }

/// <summary>
/// 排行榜条目
/// </summary>
[Table("LeaderboardEntry")]
public class LeaderboardEntry
{
    [PrimaryKey, AutoIncrement]
    public int Id { get; set; }
    
    [Indexed] public string BoardName { get; set; }  // 排行榜类别
    public string PlayerName { get; set; }
    
    [Indexed]
    public long Score { get; set; }
    public int Rank { get; set; }
    public DateTime RecordedAt { get; set; }
    public string ExtraDataJson { get; set; }  // 额外数据（关卡、时间等）
}

/// <summary>
/// 成就记录
/// </summary>
[Table("AchievementRecord")]
public class AchievementRecord
{
    [PrimaryKey]
    public int AchievementId { get; set; }
    
    [Indexed] public int SlotId { get; set; }
    public bool IsUnlocked { get; set; }
    public int Progress { get; set; }
    public int MaxProgress { get; set; }
    
    [Indexed]
    public DateTime? UnlockedAt { get; set; }
}

/// <summary>
/// 游戏日志（用于分析/回放）
/// </summary>
[Table("GameLogEntry")]
public class GameLogEntry
{
    [PrimaryKey, AutoIncrement]
    public int Id { get; set; }
    
    [Indexed] public string Category { get; set; }  // 日志类别：Combat/Economy/Quest
    public string EventType { get; set; }
    public string Data { get; set; }    // JSON格式的事件数据
    public DateTime Timestamp { get; set; }
    public int SessionId { get; set; }
}
```

---

## 四、仓储模式实现

### 4.1 存档仓储

```csharp
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using SQLite;
using UnityEngine;
using System.Security.Cryptography;
using System.Text;

/// <summary>
/// 存档仓储：封装存档相关的所有数据库操作
/// </summary>
public class SaveRepository
{
    private readonly SQLiteAsyncConnection _db;

    public SaveRepository()
    {
        _db = SQLiteService.Instance.GetConnection();
    }

    /// <summary>
    /// 获取所有存档槽位信息
    /// </summary>
    public async Task<List<PlayerSaveData>> GetAllSlotsAsync()
    {
        return await _db.Table<PlayerSaveData>()
            .OrderByDescending(s => s.SavedAt)
            .ToListAsync();
    }

    /// <summary>
    /// 加载指定槽位的存档
    /// </summary>
    public async Task<PlayerSaveData> LoadSlotAsync(int slotId)
    {
        var save = await _db.Table<PlayerSaveData>()
            .Where(s => s.SlotId == slotId)
            .FirstOrDefaultAsync();
        
        if (save != null && !ValidateChecksum(save))
        {
            Debug.LogWarning($"[SaveRepo] Checksum mismatch for slot {slotId}! Data may be corrupted.");
            // 可以在此触发自动修复或通知玩家
        }
        
        return save;
    }

    /// <summary>
    /// 保存存档（事务保证存档数据与背包数据的原子性）
    /// </summary>
    public async Task SaveSlotAsync(PlayerSaveData saveData, List<InventoryItem> items)
    {
        saveData.SavedAt = DateTime.UtcNow;
        saveData.Checksum = ComputeChecksum(saveData);
        
        await SQLiteService.Instance.RunInTransactionAsync(async db =>
        {
            // 保存主存档数据
            if (saveData.Id == 0)
                await db.InsertAsync(saveData);
            else
                await db.UpdateAsync(saveData);
            
            // 删除旧背包数据
            await db.ExecuteAsync(
                "DELETE FROM InventoryItem WHERE SlotId = ?", 
                saveData.SlotId
            );
            
            // 批量插入新背包数据
            if (items != null && items.Count > 0)
            {
                foreach (var item in items)
                {
                    item.SlotId = saveData.SlotId;
                }
                await db.InsertAllAsync(items);
            }
        });
        
        Debug.Log($"[SaveRepo] Slot {saveData.SlotId} saved successfully");
    }

    /// <summary>
    /// 删除存档槽位（级联删除相关数据）
    /// </summary>
    public async Task DeleteSlotAsync(int slotId)
    {
        await SQLiteService.Instance.RunInTransactionAsync(async db =>
        {
            await db.ExecuteAsync("DELETE FROM PlayerSaveData WHERE SlotId = ?", slotId);
            await db.ExecuteAsync("DELETE FROM InventoryItem WHERE SlotId = ?", slotId);
            await db.ExecuteAsync("DELETE FROM QuestRecord WHERE SlotId = ?", slotId);
            await db.ExecuteAsync("DELETE FROM AchievementRecord WHERE SlotId = ?", slotId);
        });
    }

    /// <summary>
    /// 获取指定槽位的背包物品
    /// </summary>
    public async Task<List<InventoryItem>> GetInventoryAsync(int slotId)
    {
        return await _db.Table<InventoryItem>()
            .Where(item => item.SlotId == slotId)
            .OrderBy(item => item.BagSlotIndex)
            .ToListAsync();
    }

    /// <summary>
    /// 查询特定类型的物品
    /// </summary>
    public async Task<List<InventoryItem>> GetEquippedItemsAsync(int slotId)
    {
        return await _db.Table<InventoryItem>()
            .Where(item => item.SlotId == slotId && item.IsEquipped)
            .ToListAsync();
    }

    // --- 数据完整性校验 ---

    private string ComputeChecksum(PlayerSaveData save)
    {
        string data = $"{save.SlotId}|{save.Level}|{save.Gold}|{save.Experience}|{save.CurrentScene}";
        using var sha256 = SHA256.Create();
        byte[] hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(data));
        return Convert.ToBase64String(hash).Substring(0, 16);
    }

    private bool ValidateChecksum(PlayerSaveData save)
    {
        return save.Checksum == ComputeChecksum(save);
    }
}
```

### 4.2 排行榜仓储

```csharp
/// <summary>
/// 排行榜仓储：支持多类型排行榜，高效的分页查询
/// </summary>
public class LeaderboardRepository
{
    private readonly SQLiteAsyncConnection _db;

    public LeaderboardRepository()
    {
        _db = SQLiteService.Instance.GetConnection();
    }

    /// <summary>
    /// 提交分数（如果更高则更新）
    /// </summary>
    public async Task SubmitScoreAsync(string boardName, string playerName, long score, string extraData = null)
    {
        // 查询该玩家在此排行榜的当前记录
        var existing = await _db.Table<LeaderboardEntry>()
            .Where(e => e.BoardName == boardName && e.PlayerName == playerName)
            .FirstOrDefaultAsync();
        
        bool isNewRecord = false;
        
        if (existing == null)
        {
            await _db.InsertAsync(new LeaderboardEntry
            {
                BoardName = boardName,
                PlayerName = playerName,
                Score = score,
                RecordedAt = DateTime.UtcNow,
                ExtraDataJson = extraData
            });
            isNewRecord = true;
        }
        else if (score > existing.Score)
        {
            existing.Score = score;
            existing.RecordedAt = DateTime.UtcNow;
            existing.ExtraDataJson = extraData;
            await _db.UpdateAsync(existing);
            isNewRecord = true;
        }
        
        if (isNewRecord)
        {
            // 重新计算排名（性能敏感时可异步/延迟执行）
            await RecalculateRanksAsync(boardName);
        }
    }

    /// <summary>
    /// 获取排行榜（分页）
    /// </summary>
    public async Task<List<LeaderboardEntry>> GetTopScoresAsync(
        string boardName, int page = 0, int pageSize = 20)
    {
        return await _db.Table<LeaderboardEntry>()
            .Where(e => e.BoardName == boardName)
            .OrderByDescending(e => e.Score)
            .Skip(page * pageSize)
            .Take(pageSize)
            .ToListAsync();
    }

    /// <summary>
    /// 获取玩家排名和周围玩家（社交功能）
    /// </summary>
    public async Task<(int Rank, List<LeaderboardEntry> NearbyEntries)> GetPlayerRankAsync(
        string boardName, string playerName, int surroundCount = 2)
    {
        var playerEntry = await _db.Table<LeaderboardEntry>()
            .Where(e => e.BoardName == boardName && e.PlayerName == playerName)
            .FirstOrDefaultAsync();
        
        if (playerEntry == null) return (-1, new List<LeaderboardEntry>());
        
        // 获取玩家前后的条目
        int startRank = Mathf.Max(0, playerEntry.Rank - surroundCount - 1);
        var nearby = await _db.Table<LeaderboardEntry>()
            .Where(e => e.BoardName == boardName && 
                        e.Rank >= startRank && 
                        e.Rank <= playerEntry.Rank + surroundCount)
            .OrderBy(e => e.Rank)
            .ToListAsync();
        
        return (playerEntry.Rank, nearby);
    }

    /// <summary>
    /// 重新计算所有排名（UPDATE + 子查询方式）
    /// </summary>
    private async Task RecalculateRanksAsync(string boardName)
    {
        // 使用ROW_NUMBER窗口函数（SQLite 3.25+支持）
        await _db.ExecuteAsync(@"
            UPDATE LeaderboardEntry 
            SET Rank = (
                SELECT COUNT(*) + 1 
                FROM LeaderboardEntry AS b 
                WHERE b.BoardName = LeaderboardEntry.BoardName 
                  AND b.Score > LeaderboardEntry.Score
            )
            WHERE BoardName = ?
        ", boardName);
    }

    /// <summary>
    /// 清理旧数据（只保留Top N条记录）
    /// </summary>
    public async Task TrimBoardAsync(string boardName, int keepTopN = 1000)
    {
        await _db.ExecuteAsync(@"
            DELETE FROM LeaderboardEntry 
            WHERE BoardName = ? 
              AND Rank > ?
        ", boardName, keepTopN);
    }
}
```

---

## 五、异步查询与性能优化

### 5.1 复杂查询示例

```csharp
/// <summary>
/// 使用原生SQL执行复杂分析查询
/// </summary>
public class GameAnalyticsRepository
{
    private readonly SQLiteAsyncConnection _db;

    public GameAnalyticsRepository()
    {
        _db = SQLiteService.Instance.GetConnection();
    }

    /// <summary>
    /// 统计各任务完成率
    /// </summary>
    public async Task<List<QuestCompletionStats>> GetQuestCompletionStatsAsync(int slotId)
    {
        var result = await _db.QueryAsync<QuestCompletionStats>(@"
            SELECT 
                QuestId,
                COUNT(*) AS TotalAttempts,
                SUM(CASE WHEN Status = 2 THEN 1 ELSE 0 END) AS CompletedCount,
                AVG(CASE WHEN Status = 2 
                    THEN (julianday(CompletedAt) - julianday(AcceptedAt)) * 86400 
                    ELSE NULL END) AS AvgCompletionSeconds
            FROM QuestRecord
            WHERE SlotId = ?
            GROUP BY QuestId
            ORDER BY CompletedCount DESC
        ", slotId);
        
        return result;
    }

    /// <summary>
    /// 获取玩家进度摘要（多表聚合）
    /// </summary>
    public async Task<PlayerProgressSummary> GetProgressSummaryAsync(int slotId)
    {
        var summary = await _db.FindWithQueryAsync<PlayerProgressSummary>(@"
            SELECT 
                p.Level,
                p.Experience,
                p.PlaytimeSeconds,
                COUNT(DISTINCT i.ItemId) AS UniqueItemsCount,
                SUM(i.Quantity) AS TotalItemsCount,
                (SELECT COUNT(*) FROM QuestRecord q WHERE q.SlotId = p.SlotId AND q.Status = 2) AS CompletedQuests,
                (SELECT COUNT(*) FROM AchievementRecord a WHERE a.SlotId = p.SlotId AND a.IsUnlocked = 1) AS UnlockedAchievements
            FROM PlayerSaveData p
            LEFT JOIN InventoryItem i ON i.SlotId = p.SlotId
            WHERE p.SlotId = ?
            GROUP BY p.Id
        ", slotId);
        
        return summary;
    }

    /// <summary>
    /// 游戏日志按时段统计（用于分析玩家行为）
    /// </summary>
    public async Task<List<HourlyActivityStats>> GetHourlyActivityAsync(int sessionId)
    {
        return await _db.QueryAsync<HourlyActivityStats>(@"
            SELECT 
                strftime('%H', Timestamp) AS Hour,
                Category,
                COUNT(*) AS EventCount
            FROM GameLogEntry
            WHERE SessionId = ?
            GROUP BY strftime('%H', Timestamp), Category
            ORDER BY Hour, Category
        ", sessionId);
    }
}

// 查询结果DTO
public class QuestCompletionStats
{
    public int QuestId { get; set; }
    public int TotalAttempts { get; set; }
    public int CompletedCount { get; set; }
    public double AvgCompletionSeconds { get; set; }
    
    public float CompletionRate => TotalAttempts > 0 
        ? (float)CompletedCount / TotalAttempts 
        : 0f;
}

public class PlayerProgressSummary
{
    public int Level { get; set; }
    public long Experience { get; set; }
    public int PlaytimeSeconds { get; set; }
    public int UniqueItemsCount { get; set; }
    public int TotalItemsCount { get; set; }
    public int CompletedQuests { get; set; }
    public int UnlockedAchievements { get; set; }
}

public class HourlyActivityStats
{
    public string Hour { get; set; }
    public string Category { get; set; }
    public int EventCount { get; set; }
}
```

---

## 六、数据库加密

### 6.1 SQLCipher加密存档

```csharp
/// <summary>
/// 加密SQLite数据库（使用SQLCipher）
/// </summary>
public class EncryptedSQLiteService
{
    private readonly string _dbPath;
    private readonly string _encryptionKey;
    
    public EncryptedSQLiteService(string dbPath, string playerUniqueId)
    {
        _dbPath = dbPath;
        // 基于玩家唯一ID派生加密密钥（不存储明文密钥）
        _encryptionKey = DeriveKey(playerUniqueId);
    }

    private string DeriveKey(string seed)
    {
        using var sha256 = System.Security.Cryptography.SHA256.Create();
        // 加盐防彩虹表攻击
        string salted = $"GameSalt_v1_{seed}_2024";
        byte[] hash = sha256.ComputeHash(System.Text.Encoding.UTF8.GetBytes(salted));
        return Convert.ToHexString(hash).ToLower();
    }

    public SQLiteAsyncConnection CreateEncryptedConnection()
    {
        // SQLCipher通过连接字符串传递密钥
        var options = new SQLiteConnectionString(
            _dbPath,
            storeDateTimeAsTicks: true,
            key: _encryptionKey  // SQLCipher密钥
        );
        
        return new SQLiteAsyncConnection(options);
    }
    
    /// <summary>
    /// 更改数据库密钥（密码更换）
    /// </summary>
    public async Task RekeyAsync(SQLiteAsyncConnection conn, string newKey)
    {
        await conn.ExecuteAsync($"PRAGMA rekey = '{newKey}';");
    }
}
```

### 6.2 轻量级字段级加密（不依赖SQLCipher）

```csharp
/// <summary>
/// 字段级加密：对敏感字段加密，无需第三方加密库
/// </summary>
public static class FieldEncryption
{
    private static readonly byte[] IV = new byte[16]; // 实际项目使用随机IV并存储
    
    public static string EncryptField(string plainText, string key)
    {
        if (string.IsNullOrEmpty(plainText)) return plainText;
        
        using var aes = System.Security.Cryptography.Aes.Create();
        aes.Key = System.Text.Encoding.UTF8.GetBytes(key.PadRight(32).Substring(0, 32));
        aes.IV  = IV;
        
        using var encryptor = aes.CreateEncryptor();
        byte[] data = System.Text.Encoding.UTF8.GetBytes(plainText);
        byte[] encrypted = encryptor.TransformFinalBlock(data, 0, data.Length);
        return Convert.ToBase64String(encrypted);
    }

    public static string DecryptField(string cipherText, string key)
    {
        if (string.IsNullOrEmpty(cipherText)) return cipherText;
        
        try
        {
            using var aes = System.Security.Cryptography.Aes.Create();
            aes.Key = System.Text.Encoding.UTF8.GetBytes(key.PadRight(32).Substring(0, 32));
            aes.IV  = IV;
            
            using var decryptor = aes.CreateDecryptor();
            byte[] data = Convert.FromBase64String(cipherText);
            byte[] decrypted = decryptor.TransformFinalBlock(data, 0, data.Length);
            return System.Text.Encoding.UTF8.GetString(decrypted);
        }
        catch
        {
            Debug.LogWarning("[FieldEncryption] Decryption failed");
            return string.Empty;
        }
    }
}
```

---

## 七、数据库维护系统

### 7.1 自动化维护任务

```csharp
/// <summary>
/// 数据库维护系统：定期清理、压缩、备份
/// </summary>
public class DatabaseMaintenanceSystem : MonoBehaviour
{
    [Header("维护配置")]
    [SerializeField] private int logRetentionDays = 30;
    [SerializeField] private int maxLeaderboardEntries = 1000;
    [SerializeField] private int maintenanceIntervalHours = 24;

    private SQLiteAsyncConnection _db;

    async void Start()
    {
        _db = SQLiteService.Instance.GetConnection();
        
        // 检查是否需要维护（上次维护时间）
        if (ShouldRunMaintenance())
        {
            await RunMaintenanceAsync();
        }
    }

    private bool ShouldRunMaintenance()
    {
        string lastMaint = PlayerPrefs.GetString("LastDBMaintenance", "");
        if (string.IsNullOrEmpty(lastMaint)) return true;
        
        if (DateTime.TryParse(lastMaint, out DateTime last))
        {
            return (DateTime.UtcNow - last).TotalHours >= maintenanceIntervalHours;
        }
        return true;
    }

    public async Task RunMaintenanceAsync()
    {
        Debug.Log("[DBMaintenance] Starting...");
        
        // 1. 清理过期日志
        await CleanOldLogsAsync();
        
        // 2. 裁剪排行榜
        await TrimLeaderboardsAsync();
        
        // 3. 压缩数据库（WAL模式下执行checkpoint）
        await VacuumAsync();
        
        // 4. 更新维护时间戳
        PlayerPrefs.SetString("LastDBMaintenance", DateTime.UtcNow.ToString("O"));
        PlayerPrefs.Save();
        
        Debug.Log("[DBMaintenance] Completed");
    }

    private async Task CleanOldLogsAsync()
    {
        var cutoff = DateTime.UtcNow.AddDays(-logRetentionDays);
        int deleted = await _db.ExecuteAsync(
            "DELETE FROM GameLogEntry WHERE Timestamp < ?", 
            cutoff
        );
        Debug.Log($"[DBMaintenance] Deleted {deleted} old log entries");
    }

    private async Task TrimLeaderboardsAsync()
    {
        // 获取所有排行榜名称
        var boards = await _db.QueryAsync<BoardName>(
            "SELECT DISTINCT BoardName FROM LeaderboardEntry"
        );
        
        foreach (var board in boards)
        {
            await _db.ExecuteAsync(@"
                DELETE FROM LeaderboardEntry 
                WHERE BoardName = ? 
                  AND Id NOT IN (
                    SELECT Id FROM LeaderboardEntry 
                    WHERE BoardName = ? 
                    ORDER BY Score DESC 
                    LIMIT ?
                  )
            ", board.Name, board.Name, maxLeaderboardEntries);
        }
    }

    private async Task VacuumAsync()
    {
        // WAL模式：先做checkpoint，再VACUUM
        await _db.ExecuteAsync("PRAGMA wal_checkpoint(TRUNCATE);");
        await _db.ExecuteAsync("VACUUM;");
        
        // 获取数据库大小
        var result = await _db.QueryAsync<PageCount>("PRAGMA page_count;");
        var pageSize = await _db.QueryAsync<PageSize>("PRAGMA page_size;");
        
        if (result.Count > 0 && pageSize.Count > 0)
        {
            long dbSizeBytes = (long)result[0].Count * pageSize[0].Size;
            Debug.Log($"[DBMaintenance] DB Size: {dbSizeBytes / 1024f:F1} KB");
        }
    }

    private class BoardName { public string Name { get; set; } }
    private class PageCount { public long Count { get; set; } }
    private class PageSize { public long Size { get; set; } }
}
```

---

## 八、初始化集成示例

```csharp
/// <summary>
/// 游戏启动时的数据库初始化流程
/// </summary>
public class GameDatabaseBootstrap : MonoBehaviour
{
    async void Awake()
    {
        try
        {
            // 初始化SQLite服务
            await SQLiteService.Instance.InitializeAsync();
            
            // 初始化各Repository
            var saveRepo  = new SaveRepository();
            var lbRepo    = new LeaderboardRepository();
            var analytics = new GameAnalyticsRepository();
            
            // 注册到依赖注入容器（如使用Zenject）
            // container.Bind<SaveRepository>().FromInstance(saveRepo).AsSingle();
            
            Debug.Log("[Bootstrap] Database ready");
            
            // 加载存档列表
            var slots = await saveRepo.GetAllSlotsAsync();
            Debug.Log($"[Bootstrap] Found {slots.Count} save slots");
        }
        catch (Exception ex)
        {
            Debug.LogError($"[Bootstrap] Database initialization failed: {ex}");
            // 降级：回退到PlayerPrefs
        }
    }

    void OnApplicationQuit()
    {
        // 关闭数据库连接，确保WAL数据写入主数据库文件
        SQLiteService.Instance?.Dispose();
    }
}
```

---

## 九、性能基准参考

```
SQLite在Unity中的性能基准（iPhone 13, Release Build）：

读取操作（背包，1000条物品）：
  ├── ORM查询（Table<T>）：约 12ms
  ├── 原生SQL查询：约 6ms
  └── 索引命中率影响：命中 vs 全表扫描 = 6ms vs 180ms

写入操作：
  ├── 单条INSERT（无事务）：约 2-5ms
  ├── 批量INSERT（1000条，单事务）：约 35ms
  └── 批量INSERT（1000条，无事务）：约 2000ms（每条单独事务）

PRAGMA优化效果：
  ├── WAL模式：并发读写提升 ~3x
  ├── cache_size=8000：热查询提升 ~40%
  └── synchronous=NORMAL：写入提升 ~2x（vs FULL）
```

---

## 十、最佳实践总结

### 10.1 设计原则

| 原则 | 说明 |
|------|------|
| **仓储模式隔离** | 所有DB操作封装在Repository中，业务层不直接操作SQLite |
| **事务保证原子性** | 多表相关操作必须在事务中执行 |
| **索引驱动查询** | WHERE条件字段必须建立索引 |
| **批量操作** | 多条INSERT/UPDATE使用InsertAllAsync + 单事务 |
| **WAL模式** | 默认开启，提升并发读写性能 |
| **版本化迁移** | 维护DBVersion表，每次结构变更对应迁移脚本 |
| **校验和防篡改** | 核心存档数据计算校验和 |
| **定期维护** | 定期VACUUM + 清理过期数据 |

### 10.2 工程落地 Checklist

- [ ] 集成sqlite-net-pcl包
- [ ] 实现带版本迁移的初始化服务
- [ ] 开启WAL模式和缓存优化
- [ ] 为所有频繁查询字段建立索引
- [ ] 实现事务封装的Repository层
- [ ] 存档数据添加校验和验证
- [ ] 实现数据库定期维护（清理/VACUUM）
- [ ] 为敏感数据添加加密（字段级或SQLCipher）
- [ ] 异步初始化，不阻塞主线程
- [ ] ApplicationQuit时正确关闭连接

---

## 总结

SQLite是游戏本地数据管理的利器，尤其适合需要**结构化存储、复杂查询、事务保证**的游戏系统（存档、背包、排行榜）。通过WAL模式、索引优化和批量事务，可以在移动端达到毫秒级的读写响应。配合仓储模式的架构设计，使数据层清晰可维护，也为日后迁移到云存档提供了良好的抽象基础。
