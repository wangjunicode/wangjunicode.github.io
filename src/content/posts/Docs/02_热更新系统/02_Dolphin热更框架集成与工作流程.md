# 02_Dolphin热更框架集成与工作流程

> 面向刚入行的毕业生 · 建议搭配 PatchManager.cs 阅读

---

## 1. 系统概述

### 1.1 什么是 GCloud Dolphin？

GCloud Dolphin 是腾讯 GCloud 团队提供的**移动游戏热更新 SDK**，专门解决手游在不重新安装 App 的前提下完成程序包（APK/IPA）和资源包（AssetBundle/DLL）的版本更新问题。

它与 Unity 官方的 Addressables 是**互补关系**：
- **Dolphin** 负责：从 CDN 下载文件、断点续传、校验、安装 APK/解压资源
- **Addressables** 负责：运行时资源的寻址、加载、内存管理

Dolphin 在本项目中对应的是 `GCloud.Dolphin` 命名空间下的接口，主要类有：
- `DolphinFactory`：工厂类，用于创建管理器
- `DolphinMgrInterface`：热更管理器接口
- `DolphinCallBackInterface`：回调接口（`PatchManager` 实现了它）
- `DolphinDateInterface`：数据接口（`PatchManager` 也实现了它）

### 1.2 更新渠道配置

```csharp
// 两个 CDN 域名对应两套环境
private const string DOPHIN_UPDATEURL     = "download.714456880-1-1.gcloudsvcs.com";  // 正式服
private const string DOPHIN_PRE_UPDATEURL = "pre-download.714456880-1-2.gcloudsvcs.com"; // 预发布/审核服

// 对应的渠道 ID（控制灰度分组）
private const uint UPDATECHANNELID_DEV = 1879060255;
private const uint UPDATECHANNELID_PUB = 1879060255;
```

**通俗理解**：把 `DOPHIN_UPDATEURL` 想象成"正式服 CDN 地址"，`DOPHIN_PRE_UPDATEURL` 想象成"测试服 CDN 地址"。游戏会根据安装包内的 `DeploymentEnvironment` 文本资源来自动切换连接哪套 CDN。

---

## 2. 架构设计

### 2.1 Dolphin 接入架构图

```
                    ┌──────────────────────────────────┐
                    │          GCloud 控制台            │
                    │  （上传安装包/资源包，配置版本）   │
                    └──────────────┬───────────────────┘
                                   │ CDN 分发
                    ┌──────────────▼───────────────────┐
                    │    Dolphin CDN 服务器              │
                    │  DOPHIN_UPDATEURL (正式)           │
                    │  DOPHIN_PRE_UPDATEURL (预发布)     │
                    └──────────────┬───────────────────┘
                                   │ HTTP 下载
┌──────────────────────────────────▼───────────────────────────────┐
│                          客户端 App                               │
│                                                                   │
│  PatchManager (MonoBehaviour)                                     │
│  ├─ implements DolphinCallBackInterface                           │
│  │   ├─ OnNoticeNewVersionInfo(NewVersionInfo)  // 版本信息回调   │
│  │   ├─ OnUpdateProgressInfo(...)               // 下载进度回调   │
│  │   ├─ OnUpdateMessageBoxInfo(...)             // 错误消息回调   │
│  │   ├─ OnNoticeInstallApk(apkPath)             // APK 安装回调  │
│  │   ├─ OnNoticeChangeSourceVersion(newVer)     // 资源版本变更   │
│  │   └─ OnNoticeUpdateSuccess()                 // 更新成功回调   │
│  │                                                                │
│  └─ implements DolphinDateInterface                               │
│      ├─ GetCurrentProgramVersion()              // 返回当前版本   │
│      ├─ GetCurrentSourceVersion()               // 返回资源版本   │
│      ├─ GetUpdateSourceSavePath()               // 资源保存路径   │
│      └─ GetUpdateTempPath()                     // 临时路径       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 Dolphin 两阶段更新状态机

```
[启动]
  │
  ▼
AppUpdate()                    ← UpdateInitType_OnlyProgram
  │
  ├─[mgr.DriveUpdateService() 主线程驱动回调]
  │
  ▼
OnNoticeNewVersionInfo(UpdateType_Program)
  │
  ├─ isCurrentNewest=true
  │     └─ appReadyBeginRes=true → SourceUpdate()  ← UpdateInitType_OnlySource
  │
  ├─ isForce=true（强制大版本更新）
  │     └─ ShowAppStroeUpdateTip() → 引导去商店下载
  │
  └─ isForce=false（可选更新）
        └─ ShowSelectiveUpdateTip() → 用户选择是否更新
              ├─ 确认 → mgr.Continue() → 下载 APK
              └─ 取消 → appReadyBeginRes=true（直接进游戏）
  │
  ▼
SourceUpdate()
  │
  ▼
OnNoticeNewVersionInfo(UpdateType_Source)
  │
  ├─ isCurrentNewest=true → BeginAdressableCatalogUpdate()
  │
  ├─ needDownloadSize > 3MB && 非 WiFi
  │     └─ 询问用户是否在非 WiFi 下下载
  │
  ├─ needDownloadSize ∈ (0, 3MB]（静默更新）
  │     └─ mgr.Continue() 静默下载
  │
  └─ needDownloadSize = 0（无需更新）
        └─ BeginAdressableCatalogUpdate()
```

---

## 3. 核心代码展示

### 3.1 Dolphin SDK 初始化

```csharp
private void AppUpdate()
{
    // 1. 创建 Dolphin 工厂和管理器
    factory = new DolphinFactory();
    mgr = factory.CreateDolphinMgr(this, this); // this 同时实现了两个接口
    
    // 2. 配置更新参数
    UpdateInitInfo info = new UpdateInitInfo();
    info.connectorType = 2;                                    // 连接器类型
    info.updateInitType = UpdateInitType.UpdateInitType_OnlyProgram; // 第一阶段：仅程序包

    // 3. 根据环境选择 CDN 地址（生产环境/开发环境 + 审核服/正式服）
#if PRODUCTION_ENVIRONMENT
    #if UNITY_IOS
        info.gameUpdateUrl = IsReviewEnvironment() ? DOPHIN_PRE_UPDATEURL : DOPHIN_UPDATEURL;
    #elif UNITY_ANDROID
        // 支持通过本地文件切换到预发布环境（方便测试人员）
        var predownloadPath = Path.Combine(Application.persistentDataPath, "predownloadtest.txt");
        info.gameUpdateUrl = File.Exists(predownloadPath) ? DOPHIN_PRE_UPDATEURL 
            : (IsReviewEnvironment() ? DOPHIN_PRE_UPDATEURL : DOPHIN_UPDATEURL);
    #endif
    info.updateChannelId = UPDATECHANNELID_PUB;
#else
    info.gameUpdateUrl = IsReviewEnvironment() ? DOPHIN_PRE_UPDATEURL : DOPHIN_UPDATEURL;
    info.updateChannelId = UPDATECHANNELID_DEV;
#endif

    // 4. 启动更新服务
    mgr.InitUpdateMgr(info, false);
    mgr.StartUpdateService();
    isUpdating = true;
}
```

### 3.2 主线程驱动（重要！）

```csharp
void Update()
{
    if (hadInit)
    {
        if (isUpdating && mgr != null)
        {
            mgr.DriveUpdateService(); // ← 必须在主线程每帧调用！
        }
        
        if (exitUpdate)
        {
            if (isUpdating && mgr != null)
            {
                mgr.StopUpdateService();
                ResetParam();
            }
        }
        // ...
    }
}
```

**这是新手最容易踩的坑**：Dolphin SDK 的回调不是线程安全的，必须在 `Update()` 中每帧调用 `DriveUpdateService()` 来"驱动"回调触发。如果忘记调用，`OnNoticeNewVersionInfo` 等回调将永远不会触发。

### 3.3 版本信息处理回调

```csharp
public void OnNoticeNewVersionInfo(NewVersionInfo info)
{
    PatchLog.Info($"[VGameDolphin] NewVersionInfo, updateType:{info.updateType}");

    if (info.isCurrentNewest) // 当前已是最新
    {
        exitUpdate = true;
        if (info.updateType == UpdateType.UpdateType_Program)
        {
            appReadyBeginRes = true; // 触发 SourceUpdate
        }
        else if (info.updateType == UpdateType.UpdateType_Source)
        {
            BeginAdressableCatalogUpdate(); // 进入 Addressables Catalog 更新
        }
    }
    else // 有新版本
    {
        if (info.updateType == UpdateType.UpdateType_Source)
        {
            // 大于 3MB 且非 WiFi → 询问用户
            if (info.needDownloadSize > 3 * 1024 * 1024ul &&
                Application.internetReachability != NetworkReachability.ReachableViaLocalAreaNetwork)
            {
                uiInstance.ShowTipMessage("提示", $"需下载{info.needDownloadSize/1024f/1024f:F1}M，当前非WiFi，是否继续？",
                    () => mgr.Continue(),
                    () => Application.Quit());
            }
            else
            {
                mgr.Continue(); // 静默更新
            }
        }
    }
}
```

### 3.4 下载进度回调

```csharp
public void OnUpdateProgressInfo(
    IIPSMobileVersionCallBack.VERSIONSTAGE curVersionStage,
    string msg, ulong nowSize, ulong totalSize, bool isDownloading)
{
    if (isDownloading)
    {
        if (totalSize > 0)
        {
            // 更新进度条（0-1）
            onUpdateBar((float)nowSize / totalSize, true);
            
            // 显示下载速度
            string strSpeed = $"{msg}, 正在下载，当前速度: {mgr.GetCurrentDownSpeed() / 1024}KB/s";
            uiInstance.setTips(strSpeed);
        }
        
        // 利用下载等待时间预热 Shader
        ShaderPreloader_OnStart.Instance.PreloadCommonShader();
    }
    else
    {
        onUpdateBar(1, false);
    }
}
```

**设计细节**：在等待 Dolphin 下载资源时，同步触发 Shader 预热（`PreloadCommonShader`），利用加载时间做前置优化，缩短进入游戏后的首帧卡顿。

### 3.5 资源版本变更回调（热更完成）

```csharp
public void OnNoticeChangeSourceVersion(string newVersionStr)
{
    PatchLog.Info($"[VGameDolphin] OnNoticeChangeSourceVersion: {newVersionStr}");
    
    // 停止 Shader 预热（资源已就绪，无需继续预热）
    ShaderPreloader_OnStart.Instance?.PauseShaderWarmup();
    ShaderPreloader_OnStart.Instance?.DoDestroy();
    
    exitUpdate = true;
    
    // 持久化新版本号到 AppConfig
    VersionManager.AppConfig.AndroidSourceVersion = newVersionStr;
    VersionManager.AppConfig.iOSSourceVersion = newVersionStr;
    VersionManager.Instance.SaveAppConfig();
    
    // 更新 Addressables Catalog
    BeginAdressableCatalogUpdate();
}
```

### 3.6 Android APK 安装

```csharp
public void OnNoticeInstallApk(string apkPath)
{
    PlayerPrefs.DeleteAll(); // 清除本地存档，防止旧数据污染新版本
    exitUpdate = true;
    m_ApkPath = apkPath;
    bool success = InstallApk(apkPath);
    // ...
}

private bool InstallApk(string path)
{
    // 调用腾讯 Dolphin 的 Java 层安装接口
    AndroidJavaClass clazz = new AndroidJavaClass("com.tencent.gcloud.dolphin.CuIIPSMobile");
    int result = clazz.CallStatic<int>("installAPK", path, m_jo);
    return result == 0;
}
```

---

## 4. 设计亮点

### 4.1 环境自适应切换机制

通过在 `Application.persistentDataPath` 下放置一个特殊文件 `predownloadtest.txt`，测试人员可以让线上正式包自动连接到预发布 CDN 环境，而**无需重新打包**。这是一个非常实用的"后门"机制：

```csharp
var predownloadPath = Path.Combine(Application.persistentDataPath, "predownloadtest.txt");
if (File.Exists(predownloadPath))
    info.gameUpdateUrl = DOPHIN_PRE_UPDATEURL; // 切换到预发布
```

### 4.2 用户体验优化：静默更新阈值

资源更新大小在 0-3MB 之间时，系统会静默下载，用户不会看到确认弹窗。超过 3MB 时才会提示用户，体现了"小更新无感更新，大更新告知用户"的用户体验设计原则。

### 4.3 APK 安装后的恢复机制

```csharp
void OnApplicationPause(bool pause)
{
    // App 从后台恢复时，如果有等待安装的 APK，再次触发安装
    if (!pause && !string.IsNullOrEmpty(m_ApkPath))
    {
        OnNoticeInstallApk(m_ApkPath);
    }
}
```

用户从其他应用切回游戏时，如果之前的 APK 安装流程被中断，会自动重试安装。

---

## 5. 常见问题与最佳实践

### Q1：Dolphin 回调没有触发是什么原因？
**A**：最常见的原因是忘记在 `Update()` 中调用 `mgr.DriveUpdateService()`。Dolphin 的内部网络请求是异步的，但回调必须由主线程主动"取回"，这是 Dolphin 的设计约定。

### Q2：如何区分当前是审核包还是正式包？
**A**：通过 `Resources/DeploymentEnvironment.txt` 文件内容判断。打包时将该文件内容设置为 `"Review"` 或 `"Production"`，运行时 `IsReviewEnvironment()` 方法读取该值。

### Q3：`UpdateChannelId` 有什么作用？
**A**：这是 GCloud 控制台上配置的渠道 ID，不同 ChannelId 对应不同的更新包版本配置。可以利用它实现按渠道分发不同热更内容（例如不同应用商店的包走不同更新策略）。

### Q4：如何处理更新失败（网络断开等）？
**A**：Dolphin 通过 `OnUpdateMessageBoxInfo` 回调通知错误信息，`PatchManager` 中的处理是显示弹窗询问用户是否重试（调用 `mgr.Continue()`）或退出游戏（`Application.Quit()`）。

```csharp
public void OnUpdateMessageBoxInfo(string msg, MessageBoxType msgBoxType, bool isError, uint errorCode)
{
    if (isError)
    {
        string message = msg + ", 错误码：" + errorCode + ", 是否重试？";
        uiInstance.ShowTipMessage("提示", message, 
            () => mgr.Continue(),  // 重试
            () => Application.Quit()); // 退出
    }
    else
    {
        mgr.Continue(); // 非错误类消息，直接继续
    }
}
```

### Q5：新手注意事项
1. **不要在 Awake 初始化 Dolphin**，Dolphin SDK 需要 GCloud 完成初始化后才能使用，应在 `Start` 中操作
2. **确保 `mgr.DriveUpdateService()` 每帧都被调用**，否则所有回调都不会触发
3. **`mgr.Continue()` 是流程推进的关键**，Dolphin 的很多步骤都需要主动调用 Continue 才会继续，而不是自动进行
4. **线程安全**：不要在子线程中访问 `mgr`，所有 Dolphin 操作必须在主线程
