---
title: 游戏版本管理系统：版本号设计、兼容检查与热更新控制
published: 2026-03-31
description: 系统解析游戏版本管理的设计策略，从语义化版本号到热更新包版本控制，理解版本兼容性检查如何保障游戏稳定运行。
tags: [Unity, 版本管理, 热更新, 工程实践]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么游戏版本管理比 App 更复杂？

普通 App 的版本管理相对简单：发一个新版本，用户升级就完了。

游戏的版本管理复杂得多：

1. **渠道包**：iOS、Android、PC、各渠道（华为、小米、官服）可能版本不同
2. **热更新包**：不改大包的情况下，代码和资源可以独立更新
3. **服务器版本**：服务器协议变更时，旧版本客户端能否继续使用？
4. **配置表版本**：游戏数据（道具、技能属性）的版本
5. **资源版本**：美术资源的版本（可以独立于代码更新）

---

## 语义化版本号

游戏通常采用三段式版本号：`Major.Minor.Patch`

```csharp
public class GameVersion
{
    public int Major;    // 主版本号：大版本更新（新资料片、系统重做）
    public int Minor;    // 次版本号：功能更新（新角色、新副本）
    public int Patch;    // 修订号：Bug 修复、平衡性调整
    
    public string HotfixVersion;  // 热更新版本（可以是 MD5 或时间戳）
    public string DataVersion;    // 数据版本（配置表版本）
    public string ResVersion;     // 资源版本
    
    public string Full => $"{Major}.{Minor}.{Patch}_{HotfixVersion}";
    
    // 检查是否需要强制更新（Major 或 Minor 变化）
    public bool RequireForceUpdate(GameVersion serverVersion)
    {
        return Major != serverVersion.Major || Minor != serverVersion.Minor;
    }
    
    // 检查是否可以热更新（只有 Patch 或热更新版本变化）
    public bool CanHotUpdate(GameVersion serverVersion)
    {
        return Major == serverVersion.Major && 
               Minor == serverVersion.Minor && 
               HotfixVersion != serverVersion.HotfixVersion;
    }
}
```

---

## 版本检查流程

游戏启动时的版本检查：

```csharp
public class VersionChecker
{
    public async ETTask<VersionCheckResult> CheckAsync()
    {
        // 读取本地版本
        var localVersion = LoadLocalVersion();
        
        // 向服务器请求最新版本信息
        var response = await networkComp.SendRequestAsync<VersionInfoResponse>(
            new VersionInfoRequest { Platform = GetCurrentPlatform() });
        
        if (response.ErrorCode != ErrorCode.Success)
        {
            return new VersionCheckResult { Status = VersionStatus.NetworkError };
        }
        
        var serverVersion = response.LatestVersion;
        
        // 判断需要什么级别的更新
        if (localVersion.RequireForceUpdate(serverVersion))
        {
            return new VersionCheckResult 
            { 
                Status = VersionStatus.ForceUpdate,
                UpdateUrl = response.AppStoreUrl   // 跳转到应用商店
            };
        }
        
        if (localVersion.CanHotUpdate(serverVersion))
        {
            return new VersionCheckResult 
            { 
                Status = VersionStatus.HotUpdate,
                HotUpdateInfo = response.HotUpdateInfo
            };
        }
        
        return new VersionCheckResult { Status = VersionStatus.UpToDate };
    }
}

public enum VersionStatus
{
    UpToDate,       // 最新版，无需更新
    HotUpdate,      // 需要热更新
    ForceUpdate,    // 需要强制更新（去应用商店）
    NetworkError    // 网络错误，无法检查
}
```

---

## 热更新版本控制

```csharp
// 热更新配置（从服务器下载的 JSON）
[Serializable]
public class HotUpdateConfig
{
    public string Version;         // 热更新版本号
    public string[] DllFiles;      // 需要下载的 DLL 文件列表
    public string[] AssetBundles;  // 需要更新的 AssetBundle 列表
    public long TotalSize;         // 总下载大小（字节）
    public string PatchNotes;      // 更新说明
}

// 热更新下载器
public class HotUpdateDownloader
{
    public async ETTask<bool> DownloadAsync(
        HotUpdateConfig config, 
        Action<float> onProgress,
        ETCancellationToken token)
    {
        long downloaded = 0;
        
        for (int i = 0; i < config.DllFiles.Length; i++)
        {
            if (token.IsCancel()) return false;
            
            string url = BuildDownloadUrl(config.DllFiles[i]);
            string localPath = BuildLocalPath(config.DllFiles[i]);
            
            bool success = await DownloadFileAsync(url, localPath, token);
            if (!success) return false;
            
            downloaded += GetFileSize(config.DllFiles[i]);
            onProgress?.Invoke((float)downloaded / config.TotalSize);
        }
        
        // 验证文件完整性（MD5 校验）
        foreach (var dll in config.DllFiles)
        {
            if (!VerifyFile(dll))
            {
                Log.Error($"File verification failed: {dll}");
                return false;
            }
        }
        
        // 写入本地版本记录
        SaveLocalVersion(config.Version);
        return true;
    }
}
```

---

## 版本号的存储与读取

```csharp
public static class VersionStorage
{
    private const string LOCAL_VERSION_KEY = "LocalGameVersion";
    
    public static void Save(GameVersion version)
    {
        // 存储到 PlayerPrefs（也可以写文件）
        PlayerPrefs.SetString(LOCAL_VERSION_KEY, JsonUtility.ToJson(version));
        PlayerPrefs.Save();
    }
    
    public static GameVersion Load()
    {
        string json = PlayerPrefs.GetString(LOCAL_VERSION_KEY, "");
        if (string.IsNullOrEmpty(json))
        {
            return GetBuiltinVersion();  // 返回打包时内置的初始版本
        }
        return JsonUtility.FromJson<GameVersion>(json);
    }
    
    private static GameVersion GetBuiltinVersion()
    {
        // 从 Resources 或 Addressables 读取打包时内置的版本文件
        var asset = Resources.Load<TextAsset>("version");
        return JsonUtility.FromJson<GameVersion>(asset.text);
    }
}
```

---

## 多渠道版本管理

```csharp
// 渠道信息（在打包时注入）
public static class ChannelInfo
{
    // 通过 Scripting Define Symbols 在打包时设置
    #if CHANNEL_HUAWEI
    public const string Channel = "huawei";
    #elif CHANNEL_XIAOMI
    public const string Channel = "xiaomi";
    #elif CHANNEL_OFFICIAL
    public const string Channel = "official";
    #else
    public const string Channel = "default";
    #endif
    
    public const string AppId = ApplicationInfo.APP_ID;  // 编译时注入
}

// 版本检查时携带渠道信息
var request = new VersionInfoRequest 
{
    Platform = GetCurrentPlatform(),
    Channel = ChannelInfo.Channel,
    AppVersion = GameVersion.Full
};
```

---

## 总结

游戏版本管理系统的关键组件：

| 组件 | 职责 |
|------|------|
| 语义化版本号 | 清晰表达更新级别 |
| 版本检查器 | 判断更新类型（强制/热更/最新） |
| 热更新下载器 | 下载并验证热更新文件 |
| 版本存储 | 持久化本地版本信息 |
| 多渠道支持 | 编译期注入渠道标识 |

版本管理系统看似枯燥，但它是游戏运营的基础设施。一套设计良好的版本管理，可以让你在不发整包的情况下修复 Bug、调整平衡，大幅降低玩家的等待成本。
