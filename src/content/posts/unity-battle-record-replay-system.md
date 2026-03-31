---
title: 战斗录像与回放系统设计
published: 2026-03-31
description: 深入解析帧同步战斗录像的序列化方案，包含原子写入防止数据损坏、定时保存策略、哈希校验完整性与录像上传的工程实现。
tags: [Unity, 帧同步, 录像系统, 数据持久化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗录像与回放系统设计

## 前言

战斗录像有两个用途：**回放精彩时刻**和**辅助 Bug 复现**。前者是玩家体验，后者是开发效率——当线上出现玄学 Bug 时，一份完整的战斗录像能让开发者精确还原 Bug 发生时的游戏状态，而不是依赖模糊的用户描述。

本文通过分析 `RecordSafeSaveSystem`，深入解析帧同步录像的序列化方案和工程实现细节。

---

## 一、什么是帧同步录像？

帧同步（Lockstep）战斗的特性：只要初始状态相同、随机种子相同、操作输入序列相同，战斗结果**完全可以复现**。

因此，录像只需要记录：

```csharp
DungeonRecord record = new DungeonRecord()
{
    app_ver      = 当前应用版本,    // 保证用同版本复现
    res_ver      = 资源版本,        // 保证资源一致
    seed         = 随机种子,        // 保证随机数序列一致
    teamDatas    = 双方队伍数据,    // 初始状态
    framelst     = 每帧的输入指令,  // 操作序列
    hash_code    = 状态哈希校验,    // 完整性保证
    currentFrame = 录像结束帧,      // 回放时的结束点
    winGroup     = 胜利方,          // 结果记录
};
```

**不需要记录每帧的游戏状态**——这正是帧同步录像比状态快照录像小得多的原因。

---

## 二、定时保存：SAVE_INTERVAL_FRAMES

```csharp
const int SAVE_INTERVAL_FRAMES = 20 * 60;  // 每 20*60 帧保存一次（约1分钟）

static int _lastSavedFrame = -1;

public static void TrySave(Scene clientScene, int currentFrame, Evt_SaveBattleRecord evt)
{
    // 未到保存间隔且不是强制保存，跳过
    if ((_lastSavedFrame >= 0 && currentFrame - _lastSavedFrame < SAVE_INTERVAL_FRAMES)
        && !evt.force)
        return;

    _lastSavedFrame = currentFrame;
    // 执行保存...
}
```

**为什么是 `20 * 60`？**

假设战斗逻辑以 20 FPS（逻辑帧率）运行，`20 * 60 = 1200` 帧 = 60 秒 = 1 分钟。每分钟保存一次，在战斗断线崩溃时最多丢失 1 分钟的录像数据。

`evt.force = true` 是强制保存开关，用于：
- 战斗正常结束时
- 玩家主动触发保存（如分享功能）
- 开发者调试时

---

## 三、原子写入：防止数据损坏

```csharp
static void WriteAtomically(string path, byte[] data)
{
    // 1. 先写入临时文件
    var tmp = ZString.Concat(path, ".tmp");
    using (var fs = new FileStream(tmp, FileMode.Create, FileAccess.Write, FileShare.None))
    {
        fs.Write(data, 0, data.Length);
        fs.Flush();  // 强制刷新到磁盘（不依赖 OS 缓冲）
    }

    // 2. 原子替换
    if (File.Exists(path))
        File.Replace(tmp, path, null);  // 原子替换：先备份 path，再把 tmp 重命名为 path
    else
        File.Move(tmp, path);           // 不存在时直接移动（也是原子操作）
}
```

**为什么需要原子写入？**

如果直接 `File.WriteAllBytes(path, data)`，在写入过程中：
- 程序崩溃
- 磁盘空间不足
- 突然断电

会导致文件**部分写入**——文件存在但内容损坏。下次启动时读取这个损坏文件会直接崩溃或产生不可预期的行为。

原子写入的策略：**先写临时文件，成功后再替换**。这样：
- 旧文件在替换完成前一直完整有效
- 新文件写入失败时（`.tmp` 损坏），旧文件不受影响
- `File.Replace` 在大多数文件系统上是原子操作（要么全成功，要么全失败）

---

## 四、录像文件命名策略

```csharp
var name = !string.IsNullOrEmpty(evt.name)
    ? evt.name  // 调用方指定名称（用于特殊场景）
    : ZString.Format("{0}_{1}_{2}_{3}_{4}.rd",
        fix,                              // 前缀标识（默认 "record"）
        clientScene.Player().GID,         // 玩家 GID
        battleStateComp.BattleId,         // 对局 ID
        battleStateComp.gameSid,          // 游戏服务器 ID
        DateTime.Now.ToString("yyyyMMdd_HHmmss"));  // 时间戳
```

命名示例：`record_10086_20241001123456_svr01_20241001_143022.rd`

**命名设计的要点：**

1. **GID 标识玩家**：便于按玩家筛选录像文件
2. **BattleId 唯一性**：避免同一玩家的多场战斗录像互相覆盖
3. **时间戳**：支持按时间排序查找
4. **`.rd` 扩展名**：自定义格式，避免与系统文件混淆

---

## 五、队伍数据的序列化

```csharp
foreach (var teamData in battleStateComp.TeamDatas)
{
    // 将 TeamSaveData 和 TeamExtraBuildData 序列化为字节数组
    var item3 = MemoryPackSerializeHelper.SerializeToBytes(
        typeof(TeamSaveData), teamData.Item3, true);
    var item4 = MemoryPackSerializeHelper.SerializeToBytes(
        typeof(TeamExtraBuildData), teamData.Item4, true);

    record.teamDatas.Add((teamData.Item1, teamData.Item2, item3, item4));
}
```

队伍数据（`TeamSaveData`、`TeamExtraBuildData`）是复杂对象，需要序列化为字节数组后存入录像。选用 `MemoryPack` 序列化的原因：

| 序列化方案 | 速度 | 大小 | 说明 |
|----------|------|------|-----|
| JSON | 慢 | 大 | 人类可读，但录像不需要可读性 |
| Protobuf | 快 | 小 | 需要 .proto 定义，有维护成本 |
| MemoryPack | 最快 | 小 | 零复制设计，适合高频序列化 |

---

## 六、哈希校验：完整性验证

```csharp
var hash = BattleUtil.GenerateBattleHash(battlePlayerComp);
record.hash_code = hash;
```

哈希码是战斗状态的"指纹"——回放时，每帧计算一次哈希并与录像中的哈希对比：

```
正常情况：录像哈希 == 回放哈希 → 一致，继续回放
异常情况：录像哈希 != 回放哈希 → 不一致，版本变化导致复现失败
```

这个机制非常重要：**如果游戏逻辑代码变化了（比如某个技能数值调整），旧录像可能无法正确回放**。哈希不匹配时，系统可以提示"该录像因版本更新无法回放"，而不是默默地播放错误的结果。

---

## 七、录像上传

```csharp
if (evt.upload)
{
    HttpUploadHelper.UploadFile(path);
}

Log.Info(ZString.Format("SaveBattleRecord, path:{0}", path));
```

`evt.upload = true` 时，录像文件会被上传到服务器。这个特性主要用于：
- **Bug 复现**：玩家报告 Bug 时，客户端自动上传对应的录像
- **精彩时刻分享**：玩家主动分享战斗录像
- **数据分析**：服务端分析录像中的战术模式

---

## 八、帧输入数据的精简

```csharp
foreach (var item in frames)
{
    var d = new DungeonSyncFrame();
    record.framelst.Add(d);
    d.frameId = item.frameId;

    foreach (var fcmd in item.cmdList)
    {
        var ncmd = new DungeonSyncCmd();
        d.cmdlst.Add(ncmd);
        ncmd.vkey     = fcmd.vkey;      // 虚拟按键 ID
        ncmd.playerId = fcmd.playerId;  // 操作的玩家 ID
        ncmd.clientFrameId = fcmd.clientFrameId; // 客户端帧 ID（用于延迟修正）
        if (fcmd.args != null && fcmd.args.Length > 0)
            ncmd.args.AddRange(fcmd.args);
    }
}
```

每帧只记录**玩家的操作输入**（按键 ID、玩家 ID、帧 ID），而不是游戏状态。这使得录像文件极其紧凑：

- 一场 3 分钟的战斗，约 3600 逻辑帧
- 假设每帧平均 2 条指令，每条指令约 16 字节
- 总大小约：3600 × 2 × 16 = 115KB（加上队伍初始数据约 200KB）

对比视频录像（30fps 720p 约 100MB/分钟），帧同步录像轻了 1500 倍以上。

---

## 九、总结

| 技术要点 | 作用 |
|---------|-----|
| 只记录输入不记录状态 | 录像体积极小（KB 级） |
| 定时保存 | 限制数据丢失上限 |
| 原子写入 | 防止崩溃导致数据损坏 |
| MemoryPack 序列化 | 极速序列化，减少 GC |
| 哈希校验 | 检测版本变化导致的复现失败 |
| 可选上传 | 支持 Bug 复现和分享功能 |

帧同步录像系统是帧同步战斗架构的天然附赠——只要帧同步设计正确，录像系统的实现成本极低，但带来的调试价值和用户体验价值巨大。
