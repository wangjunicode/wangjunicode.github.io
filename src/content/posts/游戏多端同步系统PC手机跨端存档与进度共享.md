---
title: 游戏多端同步系统：PC/手机跨端存档与进度共享
published: 2026-03-31
description: 全面解析游戏多平台多端同步系统的工程设计，包括设备注册与账号绑定、多端存档版本冲突解决策略、增量同步（只同步变化的数据）、离线期间的数据合并算法、断网后恢复同步、实时在线状态跨端同步，以及iOS/Android/PC多平台存档统一架构。
tags: [Unity, 多端同步, 跨平台, 云存档, 账号系统]
category: 工程实践
draft: false
---

## 一、多端同步架构

```
多端存档同步：

手机端 ──┐                          ┌── 手机端
平板端 ──┤── 同步服务器 ──→ 主存档 ──┤── 平板端
PC端  ──┘                          └── PC端

冲突场景：
- 手机离线玩了2小时，PC也在线进行了游戏
- 两端都有进度，以哪个为准？

解决策略（三选一）：
1. Last Writer Wins：最新时间戳覆盖（简单，可能丢失进度）
2. Highest Progress：保留进度更高的存档（复杂比较）
3. Merge：智能合并（最理想，实现复杂）
```

---

## 二、增量同步设计

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 可同步字段标记（只有被标记的字段才同步）
/// </summary>
[AttributeUsage(AttributeTargets.Field | AttributeTargets.Property)]
public class SyncFieldAttribute : Attribute
{
    public SyncPriority Priority;
    public bool IsConflictKey; // 是否是冲突比较的关键字段
    
    public SyncFieldAttribute(SyncPriority priority = SyncPriority.Normal, 
        bool isConflictKey = false)
    {
        Priority = priority;
        IsConflictKey = isConflictKey;
    }
}

public enum SyncPriority { Low, Normal, High, Critical }

/// <summary>
/// 玩家存档数据（支持增量同步）
/// </summary>
[Serializable]
public class PlayerSaveData
{
    [SyncField(SyncPriority.Critical, isConflictKey: true)]
    public int PlayerLevel;
    
    [SyncField(SyncPriority.Critical, isConflictKey: true)]
    public float TotalPlayTime;  // 总游戏时间（秒）
    
    [SyncField(SyncPriority.High)]
    public int Gold;
    
    [SyncField(SyncPriority.High)]
    public List<string> CompletedQuestIds;
    
    [SyncField(SyncPriority.Normal)]
    public Dictionary<string, int> InventoryItems; // itemId → count
    
    [SyncField(SyncPriority.Normal)]
    public Dictionary<string, int> TalentPoints;   // nodeId → level
    
    [SyncField(SyncPriority.Low)]
    public PlayerSettings Settings;
    
    // 同步元数据（不算游戏数据）
    public long LastSaveTime;       // 最后保存时间（Unix毫秒）
    public string DeviceId;         // 最后保存的设备ID
    public int SaveVersion;         // 存档版本号（每次保存+1）
    public string DeviceName;       // 设备名称（显示用）
}

/// <summary>
/// 增量变更记录
/// </summary>
[Serializable]
public class SyncPatch
{
    public string DeviceId;
    public long BaseVersion;        // 基于哪个版本的变更
    public long PatchTime;
    public List<FieldChange> Changes;
}

[Serializable]
public class FieldChange
{
    public string FieldPath;        // 字段路径（"Gold" / "InventoryItems.sword_01"）
    public string OldValue;         // 旧值（JSON）
    public string NewValue;         // 新值（JSON）
    public ChangeType Type;
}

public enum ChangeType { Set, Add, Remove, Increment }

/// <summary>
/// 多端同步管理器
/// </summary>
public class MultiDeviceSyncManager : MonoBehaviour
{
    private static MultiDeviceSyncManager instance;
    public static MultiDeviceSyncManager Instance => instance;
    
    [SerializeField] private string syncApiUrl;
    
    private string deviceId;
    private PlayerSaveData localData;
    private long lastSyncVersion;
    
    public event Action<SyncConflictInfo> OnSyncConflict;   // 需要用户选择时触发
    public event Action<string> OnSyncSuccess;               // 同步成功的消息
    public event Action<string> OnSyncFailed;

    void Awake()
    {
        instance = this;
        deviceId = SystemInfo.deviceUniqueIdentifier;
    }

    /// <summary>
    /// 主动同步（登录/切换场景时触发）
    /// </summary>
    public async System.Threading.Tasks.Task<bool> SyncAsync()
    {
        try
        {
            // 1. 获取服务端版本
            var serverData = await FetchServerSaveData();
            
            if (serverData == null)
            {
                // 服务端没有存档，上传本地
                await UploadSave(localData);
                return true;
            }
            
            // 2. 比较版本
            if (serverData.SaveVersion == lastSyncVersion)
            {
                // 版本一致，只上传本地变更
                await UploadDelta();
                return true;
            }
            
            // 3. 版本不一致，需要合并
            return await MergeSaves(localData, serverData);
        }
        catch (Exception e)
        {
            Debug.LogError($"[Sync] Failed: {e.Message}");
            OnSyncFailed?.Invoke("同步失败，将在下次尝试");
            return false;
        }
    }

    async System.Threading.Tasks.Task<bool> MergeSaves(
        PlayerSaveData local, PlayerSaveData server)
    {
        // 基础判断
        bool serverNewer = server.LastSaveTime > local.LastSaveTime;
        bool serverHigherLevel = server.PlayerLevel > local.PlayerLevel;
        bool serverMoreTime = server.TotalPlayTime > local.TotalPlayTime;
        
        int serverScore = (serverNewer ? 1 : 0) + (serverHigherLevel ? 2 : 0) + 
                          (serverMoreTime ? 1 : 0);
        int localScore = (!serverNewer ? 1 : 0) + (!serverHigherLevel ? 2 : 0) + 
                          (!serverMoreTime ? 1 : 0);
        
        if (serverScore == localScore)
        {
            // 分数相同，需要用户选择
            var choice = await AskUserForConflictResolution(local, server);
            if (choice == ConflictChoice.UseServer)
                await ApplyServerSave(server);
            else
                await UploadSave(local);
        }
        else if (serverScore > localScore)
        {
            // 服务端存档更好，提示用户
            UIManager.Instance?.ShowMessage(
                $"发现更新的存档（设备: {server.DeviceName}），已自动同步");
            await ApplyServerSave(server);
        }
        else
        {
            // 本地存档更好，上传
            await UploadSave(local);
        }
        
        return true;
    }

    async System.Threading.Tasks.Task<ConflictChoice> AskUserForConflictResolution(
        PlayerSaveData local, PlayerSaveData server)
    {
        return await UIManager.Instance.ShowSyncConflictDialog(
            $"本地: Lv.{local.PlayerLevel} | 游戏 {local.TotalPlayTime / 3600f:F1}h",
            $"云端 ({server.DeviceName}): Lv.{server.PlayerLevel} | 游戏 {server.TotalPlayTime / 3600f:F1}h");
    }

    async System.Threading.Tasks.Task ApplyServerSave(PlayerSaveData serverData)
    {
        localData = serverData;
        lastSyncVersion = serverData.SaveVersion;
        LocalSaveManager.Save(localData);
        // 通知游戏系统刷新数据
    }

    async System.Threading.Tasks.Task UploadSave(PlayerSaveData data)
    {
        data.DeviceId = deviceId;
        data.DeviceName = GetDeviceName();
        data.LastSaveTime = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        data.SaveVersion++;
        
        // 上传到服务端
        await CloudStorageService.Upload(data);
        lastSyncVersion = data.SaveVersion;
    }

    async System.Threading.Tasks.Task UploadDelta()
    {
        // 只上传自上次同步以来变化的字段
        var patch = DeltaTracker.GetPendingChanges();
        if (patch != null && patch.Changes?.Count > 0)
            await CloudStorageService.UploadDelta(patch);
    }

    async System.Threading.Tasks.Task<PlayerSaveData> FetchServerSaveData()
    {
        return await CloudStorageService.Download();
    }

    string GetDeviceName()
    {
        #if UNITY_IOS
        return SystemInfo.deviceModel + " (iOS)";
        #elif UNITY_ANDROID
        return SystemInfo.deviceModel + " (Android)";
        #else
        return System.Environment.MachineName + " (PC)";
        #endif
    }
}

public enum ConflictChoice { UseLocal, UseServer }
```

---

## 三、跨端同步时序图

```
设备A (手机)          同步服务器            设备B (PC)
    │                      │                    │
    │── 登录 ──────────────→│                    │
    │← 下载最新存档 ─────────│                    │
    │                      │                    │
    │ [玩游戏3小时]         │  [PC也在玩2小时]   │
    │                      │                    │
    │── 上传存档 v5 ────────→│                    │
    │                      │── 检测到冲突（v5≠v3）→│
    │                      │                    │── 弹窗询问用户
    │                      │                    │   哪个存档更好？
    │                      │← 用户选择手机存档 ──│
    │                      │── 推送手机v5存档 ────→│
    │                      │                    │← 应用并确认
```

---

## 四、同步优化策略

| 策略 | 效果 |
|------|------|
| 增量同步（Delta Sync）| 减少传输数据量（只传变化）|
| 压缩传输 | 存档数据 gzip 后通常缩小60-80% |
| 后台静默同步 | 用户无感知，每5分钟自动同步 |
| 冲突检测优先 | 发现冲突立即通知，不拖延 |
| 本地优先 | 网络不可用时仍可游戏，连网后补同步 |
