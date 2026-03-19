# 09_资源下载与CDN管理

> 游戏资源（美术素材、配置表、代码DLL）的分发是手游运营的重要基础设施。本文讲解本项目的资源下载架构，包括热更新、COS对象存储和CDN加速。

---

## 1. 系统概述

本项目的资源下载体系分为三个层次：

| 层次 | 技术方案 | 用途 |
|------|---------|------|
| **程序更新** | GCloud Dolphin | 整包更新（APK/IPA强制更新） |
| **资源热更新** | GCloud Dolphin + Addressables | 增量资源更新（AB包、配置） |
| **补充资源下载** | WebSocket + COS | 特殊模式下的额外资源补充 |

资源最终存储在**腾讯云COS（Cloud Object Storage）**上，通过**CDN**加速分发给全球玩家。版本信息由`VersionManager`统一管理。

---

## 2. 架构设计

### 2.1 资源版本体系

```
程序版本（APK/IPA）：如 2.1.0
资源版本（AB包）：  如 2.1.0.5
                  │   │   │  └─ 小版本号（每次资源更新+1）
                  │   │   └─── patch号
                  │   └─────── 次版本号
                  └─────────── 主版本号

关键规则：
- 主版本号不同 → 需要强制更新APP（大版本）
- 主版本号相同 → 只需资源热更新（小版本）
```

### 2.2 资源分发架构

```
开发团队
   │ 打包资源（AB Bundle）
   ▼
打包机（CI/CD）
   │ 上传到COS Bucket
   ▼
腾讯云COS（持久化存储）
   │ CDN回源
   ▼
腾讯云CDN（就近缓存）
   │ 
   ▼
全球节点（用户下载最近的CDN节点）

玩家设备
   │ Dolphin检测版本差异
   ▼
GCloud Dolphin服务器（版本控制）
   │ 返回需要更新的文件列表
   ▼
玩家设备从CDN下载差异包
   │
   ▼
Application.persistentDataPath/ResUpdate/ 
（本地热更新存储目录）
```

### 2.3 版本管理类结构

```
VersionManager
├── ResVersion        → 完整资源版本号（如 "2.1.0.5"）
├── SourceVersion     → 三段版本号（如 "2.1.0"，去掉小版本）
├── MajorNum          → 主版本号（"2"）
├── MinorNum          → 次版本号（"1"）
├── UpdateSize        → 允许的最大更新包大小
└── AppConfig         → 从服务器下载的配置（Android/iOS分版本）
      ├── AndroidSourceVersion
      ├── iOSSourceVersion
      └── UpdateSize
```

---

## 3. 核心代码展示

### 3.1 版本管理（来自`VersionManager.cs`）

```csharp
public class VersionManager
{
    public static VersionManager Instance = new VersionManager();
    public static AppConfig AppConfig = new AppConfig();
    
    // 资源版本号（带小版本，如"2.1.0.5"）
    public string ResVersion
    {
        get
        {
            if (!initialized)
            {
                initialized = true;
                LoadAppConfig();
            }
#if UNITY_ANDROID
            return AppConfig.AndroidSourceVersion;
#elif UNITY_IOS
            return AppConfig.iOSSourceVersion;
#else
            return Application.version + ".1";
#endif
        }
    }
    
    // 三段版本号（"2.1.0"，用于资源目录路径）
    public string SourceVersion
    {
        get
        {
            string[] parts = ResVersion.Split('.');
            return $"{parts[0]}.{parts[1]}.{parts[2]}";
        }
    }
    
    // 主版本号
    public string MajorNum => ResVersion.Split('.')[0];
    
    // 次版本号
    public string MinorNum => ResVersion.Split('.')[1];

    // 获取游戏逻辑版本（直接用Unity的Application.version）
    public string GetGameLogicVersion()
    {
        PatchLog.Info("[VGameDolphin] GetGameLogicVersion=" + Application.version);
        return Application.version;
    }
}
```

### 3.2 版本一致性检查（来自`PatchManager.cs`）

```csharp
// 大版本更新时清理旧资源
private void ClearOldPatch()
{
    string programVersion = GetCurrentProgramVersion(); // APK版本，如"2.0.0"
    string sourceVersion  = GetCurrentSourceVersion();  // 资源版本，如"1.9.0.5"

    // 主版本号不一致 → 这是大版本更新，旧资源不兼容，必须清除
    if (programVersion.Split(".")[0] != sourceVersion.Split(".")[0])
    {
        PatchLog.Info($"版本不一致: 程序={programVersion} 资源={sourceVersion}，清理旧补丁");
        
        string resUpdateDir = Path.Combine(Application.persistentDataPath, "ResUpdate");
        if (Directory.Exists(resUpdateDir))
        {
            Directory.Delete(resUpdateDir, true);
            PatchLog.Info("旧补丁清理完毕");
        }
    }
}
```

### 3.3 GCloud Dolphin热更新初始化（来自`PatchManager.cs`）

```csharp
// 热更新服务器地址（通过CDN加速分发）
// 正式服：download.714456880-1-1.gcloudsvcs.com
// 预发布：pre-download.714456880-1-2.gcloudsvcs.com
private const string DOPHIN_UPDATEURL     = "download.714456880-1-1.gcloudsvcs.com";
private const string DOPHIN_PRE_UPDATEURL = "pre-download.714456880-1-2.gcloudsvcs.com";

private void AppUpdate()
{
    factory = new DolphinFactory();
    mgr = factory.CreateDolphinMgr(this, this);

    UpdateInitInfo info = new UpdateInitInfo();
    info.connectorType  = 2;  // HTTPS协议
    
    // 只更新程序包（APP的二进制更新）
    info.updateInitType = UpdateInitType.UpdateInitType_OnlyProgram;

    // 根据环境选择服务器
    info.gameUpdateUrl = GetUpdateServerUrl();
    info.updateChannelId = GetUpdateChannelId();
    
    // 设置最大更新包大小（超出则提示玩家WiFi下载）
    info.maxUpdateSize = VersionManager.Instance.UpdateSize; // 默认300MB
    
    mgr.InitUpdateMgr(info, false);
    mgr.StartUpdateService();  // 开始检测更新
}

// 资源热更新（AB包更新，在程序更新后执行）
private void SourceUpdate()
{
    UpdateInitInfo sourceInfo = new UpdateInitInfo();
    sourceInfo.connectorType  = 2;
    
    // 资源更新（AB Bundle）
    sourceInfo.updateInitType = UpdateInitType.UpdateInitType_OnlySource;
    sourceInfo.gameUpdateUrl  = GetUpdateServerUrl();
    sourceInfo.updateChannelId = GetUpdateChannelId();
    
    mgr.InitUpdateMgr(sourceInfo, false);
    mgr.StartUpdateService();
}
```

### 3.4 Addressables路径重定向（热更新覆盖机制）

```csharp
// 注册路径转换函数（在PatchManager.Start中）
Addressables.InternalIdTransformFunc += TransformResourcePath;

// 路径转换：优先使用热更新目录的资源
private string TransformResourcePath(IResourceLocation location)
{
    string hotUpdatePath;
    if (!hotUpdatePathMap.TryGetValue(location.InternalId, out hotUpdatePath))
    {
        // 原始路径：Addressables.RuntimePath/StandaloneWindows/xxxxx.bundle
        // 转换为：persistentDataPath/ResUpdate/StandaloneWindows/xxxxx.bundle
        var key = location.InternalId.Replace(aaPrefix, "");
        hotUpdatePath = Path.Combine(
            Application.persistentDataPath,
            HotUpdateRootDir,   // "ResUpdate"
            key
        );
        hotUpdatePathMap[location.InternalId] = hotUpdatePath;
    }
    
    // 热更新文件存在 → 用新版本
    // 热更新文件不存在 → 用原始版本（包内资源）
    return File.Exists(hotUpdatePath) ? hotUpdatePath : location.InternalId;
}
```

### 3.5 COS SDK初始化与配置（来自`CosXmlConfig.cs`）

```csharp
// COS SDK 使用Builder模式构建配置
CosXmlConfig config = new CosXmlConfig.Builder()
    .SetRegion("ap-guangzhou")          // COS存储区域（广州）
    .SetAppid("1234567890")             // 腾讯云AppID
    .IsHttps(true)                      // 强制HTTPS
    .SetDebugLog(false)                 // 生产环境关闭调试日志
    .SetConnectionTimeoutMs(15000)      // 连接超时15秒
    .SetReadWriteTimeoutMs(45000)       // 读写超时45秒
    .SetMaxErrorRetry(3)                // 最大重试次数
    .Build();

// 凭证提供者（实际项目中用临时密钥）
QCloudCredentialProvider credProvider = 
    new DefaultSessionQCloudCredentialProvider(
        secretId:     "YOUR_SECRET_ID",
        secretKey:    "YOUR_SECRET_KEY",
        keyDuration:  600,                // 临时密钥有效期600秒
        token:        "TEMP_TOKEN"        // 临时密钥Token
    );

// 创建COS服务实例
CosXml cosXml = new CosXmlServer(config, credProvider);
```

### 3.6 TransferManager - 高级上传/下载

```csharp
// 使用TransferManager进行高级传输
var transferConfig = new TransferConfig()
{
    DivisionForUpload  = 5 * 1024 * 1024,  // 文件超过5MB使用分片上传
    SliceSizeForUpload = 2 * 1024 * 1024,  // 分片大小2MB
    DivisionForDownload = 5 * 1024 * 1024, // 文件超过5MB使用多段下载
    SliceSizeForDownload = 2 * 1024 * 1024
};

TransferManager transferManager = new TransferManager(cosXml, transferConfig);

// === 异步上传（游戏回放录像等）===
async Task UploadReplayAsync(string localFilePath, string cosKey)
{
    var uploader = new COSXMLUploadTask(
        bucket:    "game-replay-1234567890",
        cosPath:   cosKey
    );
    uploader.SetSrcPath(localFilePath);
    
    // 进度回调
    uploader.progressCallback = (completed, total) =>
    {
        Debug.Log($"[COS] 上传进度: {completed}/{total} ({100f*completed/total:F1}%)");
    };
    
    // 成功回调
    uploader.successCallback = (request, result) =>
    {
        Debug.Log($"[COS] 上传成功: {result.eTag}");
    };
    
    // 失败回调
    uploader.failCallback = (request, clientException, serverException) =>
    {
        if (clientException != null)
            Debug.LogError($"[COS] 上传客户端错误: {clientException.errorCode}");
        if (serverException != null)
            Debug.LogError($"[COS] 上传服务端错误: {serverException.statusCode}");
    };
    
    await transferManager.UploadAsync(uploader);
}

// === 异步下载 ===
async Task DownloadResourceAsync(string cosKey, string localSavePath)
{
    var downloader = new COSXMLDownloadTask(
        bucket:    "game-resource-1234567890",
        cosPath:   cosKey,
        localDir:  Path.GetDirectoryName(localSavePath),
        localFileName: Path.GetFileName(localSavePath)
    );
    
    downloader.progressCallback = (completed, total) =>
    {
        Debug.Log($"[COS] 下载进度: {100f*completed/total:F1}%");
    };
    
    await transferManager.DownloadAsync(downloader);
}
```

### 3.7 预签名URL（安全的临时访问）

```csharp
// 生成预签名URL（用于用户头像上传等场景）
// 服务端生成，客户端直接上传到COS，不经过游戏服务器中转
string GeneratePresignedUploadUrl(string cosKey)
{
    PreSignatureStruct preSignature = new PreSignatureStruct()
    {
        appid    = "1234567890",
        region   = "ap-guangzhou",
        bucket   = "user-avatar-1234567890",
        cosPath  = cosKey,
        isHttps  = true,
        httpMethod = "PUT",                  // 上传用PUT
        signDurationSecond = 300            // 链接有效期5分钟
    };
    
    try
    {
        string url = cosXml.GenerateSignURL(preSignature);
        Debug.Log($"[COS] 预签名URL生成成功，有效期5分钟");
        return url;
    }
    catch (CosClientException ex)
    {
        Debug.LogError($"[COS] 预签名生成失败: {ex.errorCode}");
        return null;
    }
}
```

---

## 4. 设计亮点

### 4.1 双版本号分离管理

程序版本（APK/IPA）和资源版本（AB Bundle）分离管理，允许：
- **只更资源不更包**：大多数更新只需要下载几MB的差异包，玩家无感知
- **强制更包**：主版本号变化时（重大架构调整），必须下载新APP

### 4.2 Addressables路径重定向零侵入

通过注册`InternalIdTransformFunc`，实现了对Addressables加载系统的无侵入式热更新支持：
- 游戏业务代码无需任何修改
- 热更新资源自动优先加载
- 回退到包内资源完全透明

### 4.3 TransferManager自动分片

`TransferManager`封装了分片上传/下载逻辑：
- 小文件（<5MB）：直接传输
- 大文件（≥5MB）：自动分片，每片2MB，支持断点续传
- 失败自动重试（最大3次）

### 4.4 临时密钥安全体系

COS操作不使用固定的SecretId/SecretKey（容易泄漏），而是通过游戏服务器下发临时密钥（有效期600秒）。即使客户端被逆向工程，泄漏的密钥也很快过期，大幅降低安全风险。

### 4.5 审核环境CDN分离

AppStore审核时使用`DOPHIN_PRE_UPDATEURL`（预发布CDN），正式玩家使用`DOPHIN_UPDATEURL`（正式CDN），避免审核期间的异常更新包流向正式用户。

---

## 5. 常见问题与最佳实践

### Q1：热更新资源存在哪里？玩家重装会丢失吗？

热更新资源存在`Application.persistentDataPath/ResUpdate/`目录，这是应用的持久化存储目录。重装APP会清空该目录，下次启动时会重新检测并下载。但如果只是更新APP（保留数据），热更新资源会保留。

### Q2：更新包太大，玩家在流量环境下不愿意下载怎么办？

```csharp
// Dolphin支持设置流量提示阈值
info.maxUpdateSize = 50 * 1024 * 1024; // 50MB以上提示用WiFi下载

// DolphinCallBackInterface中处理超大包提示
void OnNeedUpdateUnderFlow(UpdateType type, NewVersionInfo info)
{
    // 提示玩家："当前更新包较大(XXX MB)，建议WiFi环境下载"
    ShowWifiRecommendDialog(info.fileSize / 1024 / 1024);
}
```

### Q3：如何在本地测试热更新流程？

1. 修改`isSkipPatch = false`
2. 将本地打好的AB包放到Dolphin本地测试服务器
3. 更改`gameUpdateUrl`指向本地服务器地址
4. 运行游戏，观察下载和路径重定向是否生效

### Q4：AB Bundle和DLL的热更新目录不同，为什么？

```csharp
// DLL放到专门的HotUpdateDll目录（被HybridCLR加载）
string targetDllPath = Path.Combine(hotUpdateDllFolder, fileName);

// Bundle放到ResUpdate/Platform/目录（被Addressables加载）
string targetBundlePath = Path.Combine(resUpdatePath, relativePath);
```

DLL是HybridCLR热更新的代码，需要放到HybridCLR指定的目录才能被加载。Bundle则通过Addressables的路径重定向机制加载，路径体系不同。

### Q5：COS下载失败如何重试？

`COSXMLDownloadTask`内置了重试机制（`CosXmlConfig.SetMaxErrorRetry(3)`），但业务层也应该有自己的重试逻辑：

```csharp
async Task DownloadWithRetryAsync(string cosKey, string savePath, int maxRetry = 3)
{
    for (int i = 0; i < maxRetry; i++)
    {
        try
        {
            await DownloadResourceAsync(cosKey, savePath);
            return; // 成功
        }
        catch (CosServerException ex) when (ex.statusCode == 503)
        {
            // 503服务不可用，等待后重试
            await Task.Delay(1000 * (i + 1));
        }
    }
    throw new Exception($"下载失败，重试{maxRetry}次后放弃: {cosKey}");
}
```

---

## 6. 总结

本项目的资源下载体系以**GCloud Dolphin**为热更新引擎，以**腾讯云COS+CDN**为存储和分发基础设施，通过**Addressables路径重定向**实现无侵入式资源替换。**VersionManager**统一管理版本号逻辑，保证了大版本升级时的资源一致性。

对于新同学，理解这套系统最关键的一点是：**游戏包内的资源是"基底"，热更新目录的资源是"补丁"，Addressables会优先用"补丁"，没有则用"基底"**。
