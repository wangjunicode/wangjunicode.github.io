---
title: 05_GCloud_SDK集成指南
published: 2024-01-01
description: "05_GCloud_SDK集成指南 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 网络与SDK
draft: false
encryptedKey: henhaoji123
---

# 05_GCloud_SDK集成指南

> GCloud是腾讯游戏专用的云服务SDK，提供了帧同步、热更新、网络优化、语音等一系列能力。本文是从零开始接入GCloud的完整指南。

---

## 1. 系统概述

**GCloud SDK**（腾讯游戏云SDK）是本项目的网络基础设施层，为游戏提供以下核心能力：

| 模块 | 功能 |
|------|------|
| **GCloudCore** | SDK初始化、全局生命周期管理、日志系统 |
| **LockStep** | 帧同步网络，支持UDP/可靠UDP混合传输 |
| **Dolphin（IIPS）** | 热更新/资源更新管理 |
| **Connector** | 通用网络连接器（TCP/UDP） |
| **NetworkService** | 网络状态监控（WiFi/4G切换检测） |
| **HttpDns** | HttpDNS防域名劫持 |
| **MSDK** | 登录、账号、支付等平台服务 |

本项目使用的GCloud版本可在`SDK/GCloudSDK/`目录下查看，SDK本体为`.a`（iOS）和`.so`（Android）原生库，C#层提供统一的封装接口。

---

## 2. 架构设计

### 2.1 GCloud SDK分层架构

```
┌──────────────────────────────────────────────────┐
│                   游戏业务代码                      │
├──────────────────────────────────────────────────┤
│              GCloud C# 封装层                      │
│  IGCloud / LockSteper / NetworkService / MSDK    │
├──────────────────────────────────────────────────┤
│           GCloud C++ Native库                    │
│  libGCloudLockStep.a / libGCloud.so / MSDK.so   │
├─────────────────────┬────────────────────────────┤
│    iOS 平台          │    Android 平台              │
│  __Internal调用      │  MSDKUnityAdapter.so        │
└─────────────────────┴────────────────────────────┘
```

### 2.2 SDK初始化流程

```
GCloudCore.Initialize()         ← 最先初始化，建立GCloud运行环境
      │
      ▼
IGCloud.Initialize(gameId, key)  ← 注册游戏凭证（GameID + GameKey）
      │
      ▼
设置日志级别（Debug / Error）
      │
      ▼
MSDK.Init()                     ← 初始化登录模块
      │
      ▼
DolphinMgr初始化                ← 初始化热更新模块
      │
      ▼
其他模块（LockStep等）按需初始化
```

### 2.3 多渠道平台支持

GCloud SDK通过`#if`预编译指令适配多平台：

```csharp
// MSDK.cs中的平台宏
#if GCLOUD_MSDK_WINDOWS
    // Windows/PC编辑器版
#elif GCLOUD_MSDK_MAC
    // macOS版
#elif UNITY_ANDROID
    // Android版（libMSDKUnityAdapter.so）
#else
    // iOS版（__Internal，链接到.a静态库）
#endif
```

---

## 3. 核心代码展示

### 3.1 GCloud SDK完整初始化（来自`PatchManager.cs`）

```csharp
void Start()
{
    // === 第一步：初始化日志系统 ===
    PatchLog.Initialize(LogLevel.Info, true);
    
    // === 第二步：初始化GCloud核心 ===
    GCloud.GCloudCore.Instance.Initialize();
    
    // === 第三步：注册游戏信息 ===
    // GameID和GameKey在GCloud平台注册游戏时获得
    var GCLOUD_GAME_ID  = 714456880;
    var GCLOUD_GAME_KEY = "6d6fd55bd75e661d9aa8ac7fc6f72ab7";
    GCloud.InitializeInfo gInitInfo = 
        new GCloud.InitializeInfo(GCLOUD_GAME_ID, GCLOUD_GAME_KEY);
    GCloud.IGCloud.Instance.Initialize(gInitInfo);
    
    // === 第四步：配置日志级别 ===
    var isDebug = true;  // 发布时改为false
    if (isDebug)
        GCloud.IGCloud.Instance.SetLogger(GCloud.LogPriority.Debug, null);
    else
        GCloud.IGCloud.Instance.SetLogger(GCloud.LogPriority.Error, null);
    
    // === 第五步：初始化MSDK ===
    GCloud.MSDK.MSDK.isDebug = true;
    GCloud.MSDK.MSDK.Init();
}
```

### 3.2 Dolphin热更新配置（来自`PatchManager.cs`）

```csharp
// Dolphin更新服务器地址
// 正式服：download.714456880-1-1.gcloudsvcs.com
// 预发布服：pre-download.714456880-1-2.gcloudsvcs.com
private const string DOPHIN_UPDATEURL     = "download.714456880-1-1.gcloudsvcs.com";
private const string DOPHIN_PRE_UPDATEURL = "pre-download.714456880-1-2.gcloudsvcs.com";

// 渠道ID（Android release版本使用）
#if UNITY_ANDROID && !DEBUG 
    private const uint UPDATECHANNELID_DEV = 1879060255;
    private const uint UPDATECHANNELID_PUB = 1879060255;
#endif

private void AppUpdate()
{
    // 创建Dolphin工厂和管理器
    factory = new DolphinFactory();
    mgr = factory.CreateDolphinMgr(this, this);  // 传入回调接口

    // 配置更新信息
    UpdateInitInfo info = new UpdateInitInfo();
    info.connectorType  = 2;  // 2=HTTPS
    info.updateInitType = UpdateInitType.UpdateInitType_OnlyProgram;
    
    // 根据环境选择服务器（审核服/正式服）
#if PRODUCTION_ENVIRONMENT
    #if UNITY_IOS
        // iOS：审核期间用pre-download，避免触发AppStore政策
        info.gameUpdateUrl = IsReviewEnvironment() ? 
            DOPHIN_PRE_UPDATEURL : DOPHIN_UPDATEURL;
    #elif UNITY_ANDROID
        // Android：支持通过本地文件切换到预发布环境（测试用）
        var predownloadPath = Path.Combine(
            Application.persistentDataPath, "predownloadtest.txt");
        info.gameUpdateUrl = File.Exists(predownloadPath) ? 
            DOPHIN_PRE_UPDATEURL : DOPHIN_UPDATEURL;
    #endif
#else
    // 开发环境
    info.gameUpdateUrl = DOPHIN_UPDATEURL;
#endif

    info.updateChannelId = IsReviewEnvironment() ? 
        UPDATECHANNELID_DEV : UPDATECHANNELID_PUB;
    
    // 启动更新服务
    mgr.InitUpdateMgr(info, false);
    mgr.StartUpdateService();
}
```

### 3.3 Dolphin进度回调处理

```csharp
// PatchManager 实现 DolphinCallBackInterface
// Dolphin下载进度回调（需在主线程驱动：mgr.DriveUpdateService()）

// 当有新版本需要下载时
void OnNeedUpdate(UpdateType type, NewVersionInfo newVerInfo)
{
    // 显示"发现新版本，是否更新？"弹框
    ShowUpdateDialog(newVerInfo.newVersion, newVerInfo.fileSize);
}

// 下载进度更新
void OnUpdateProgress(UpdateType type, ulong progress, uint speed)
{
    float percent = progress / 100f;
    onUpdateBar?.Invoke(percent, false);
    onUpdateTip?.Invoke($"下载中... {speed/1024} KB/s");
}

// 更新完成
void OnUpdateFinish(UpdateType type)
{
    if (type == UpdateType.UpdateType_Program)
    {
        // 程序包更新完成，需要重启
        RestartApp();
    }
    else
    {
        // 资源更新完成，继续进入游戏
        BeginAdressableCatalogUpdate();
    }
}
```

### 3.4 主线程驱动GCloud回调

```csharp
// PatchManager.Update() - GCloud必须在主线程驱动
void Update()
{
    if (isSkipPatch) return;
    
    if (hadInit)
    {
        // 驱动Dolphin更新回调（必须每帧调用）
        if (isUpdating && mgr != null)
        {
            mgr.DriveUpdateService();
        }
    }
}
```

### 3.5 热更新版本冲突处理

当程序版本和资源版本的主版本号不一致时（说明安装了新包但残留旧资源），需要清理旧补丁：

```csharp
private void ClearOldPatch()
{
    string currentProgramVersion = GetCurrentProgramVersion();  // 程序版本
    string currentSourceVersion  = GetCurrentSourceVersion();   // 资源版本

    // 比较主版本号（如 "2.1.0" vs "1.9.5"，主版本号 2 != 1）
    if (currentProgramVersion.Split(".")[0] != currentSourceVersion.Split(".")[0])
    {
        PatchLog.Info($"版本不一致，程序:{currentProgramVersion}，资源:{currentSourceVersion}，清理旧补丁");
        
        string resUpdateDir = Path.Combine(
            Application.persistentDataPath, "ResUpdate");
        
        if (Directory.Exists(resUpdateDir))
        {
            try
            {
                Directory.Delete(resUpdateDir, true);
                PatchLog.Info("旧补丁目录已清理");
            }
            catch (Exception ex)
            {
                PatchLog.Error($"清理失败: {ex.Message}");
            }
        }
    }
}
```

### 3.6 Addressables路径重定向

热更新下载的资源需要覆盖原始资源。通过注册路径转换函数实现：

```csharp
// 注册路径转换（在Start中）
Addressables.InternalIdTransformFunc += TransformResourcePath;

// 路径转换函数：优先使用热更新目录中的文件
private string TransformResourcePath(IResourceLocation location)
{
    string hotUpdatePath;
    if (!hotUpdatePathMap.TryGetValue(location.InternalId, out hotUpdatePath))
    {
        // 将原始路径转为热更新目录路径
        var key = location.InternalId.Replace(aaPrefix, "");
        hotUpdatePath = Path.Combine(
            Application.persistentDataPath,
            HotUpdateRootDir,   // "ResUpdate"
            key
        );
        hotUpdatePathMap[location.InternalId] = hotUpdatePath;
    }
    
    // 如果热更新文件存在，用热更新版本；否则用原包内资源
    return File.Exists(hotUpdatePath) ? hotUpdatePath : location.InternalId;
}
```

---

## 4. 设计亮点

### 4.1 审核服/正式服双通道

iOS上架AppStore时，审核团队会检查游戏，此时如果拉到正式服的更新包可能触发政策问题。通过读取`DeploymentEnvironment`配置文件，自动区分审核环境和正式环境，使用不同的Dolphin服务器地址：

```csharp
private bool IsReviewEnvironment()
{
    // 从Resources中读取环境标记
    TextAsset envFile = Resources.Load<TextAsset>("DeploymentEnvironment");
    if (envFile != null)
        DeploymentEnvironment = envFile.text;
    return DeploymentEnvironment.Equals("Review");
}
```

### 4.2 Android预发布测试机制

Android包无需重新打包即可切换到预发布环境：在设备的`persistentDataPath`下创建`predownloadtest.txt`文件，下次启动时会自动连接预发布服务器。这对QA测试非常方便。

### 4.3 Addressables热更新无缝集成

通过`InternalIdTransformFunc`拦截所有Addressables资源请求，将路径重定向到热更新目录。业务代码无需任何修改，加载资源时自动获取最新版本。

### 4.4 版本一致性检查

程序版本（APK/IPA）和资源版本（AB包）分开管理，启动时检查主版本号一致性，防止"新包+旧资源"的不兼容问题导致游戏异常。

---

## 5. 常见问题与最佳实践

### Q1：GCloud SDK接入需要哪些前置条件？

1. 在GCloud平台（cloud.tencent.com）注册游戏，获取GameID和GameKey
2. 下载对应版本的GCloud SDK（本项目在`Assets/Scripts/SDK/GCloudSDK/`）
3. 在Unity中配置`GCLOUD_MSDK_WINDOWS`等平台宏
4. iOS需要在Xcode中链接对应的`.a`静态库

### Q2：`DriveUpdateService()`必须每帧调用吗？

是的，Dolphin的回调（进度更新、完成通知等）不会在后台线程自动触发，而是在你调用`DriveUpdateService()`时被触发。如果忘记调用，更新进度不会更新，玩家界面会卡住。

### Q3：热更新文件存储在哪里？

热更新文件存储在`Application.persistentDataPath/ResUpdate/`目录下，按平台（Android/iOS）和资源路径组织。这个目录不会被应用更新清除，但卸载重装会清除。

### Q4：如果下载过程中断电/断网，下次会重新下载吗？

Dolphin支持断点续传，会记录已下载的部分，下次从中断位置继续。但如果校验失败（文件损坏），会重新下载该文件。

### Q5：如何在编辑器中跳过热更新？

代码中已有`isSkipPatch`标志：

```csharp
#if !UNITY_EDITOR && UNITY_ANDROID
    public bool isSkipPatch = false;  // Android真机默认不跳过
#else
    public bool isSkipPatch = true;   // 编辑器/iOS模拟器默认跳过
#endif
```

在编辑器中`isSkipPatch = true`，会跳过Dolphin更新，直接进入游戏。需要测试更新流程时，手动将此值改为`false`。

---

## 6. 总结

GCloud SDK是本项目网络能力的核心底座。通过`GCloudCore + IGCloud`的初始化体系，`Dolphin`热更新框架，以及`Addressables`路径重定向机制，实现了"无感更新+无缝加载"的玩家体验。掌握GCloud SDK的集成方式，是理解整个网络系统的基础。
