---
title: 03_Addressables资源管理系统
published: 2024-01-01
description: "03_Addressables资源管理系统 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 热更新
draft: false
---

# 03_Addressables资源管理系统

> 面向刚入行的毕业生 · 建议搭配 PatchManager.cs 和 VersionManager.cs 阅读

---

## 1. 系统概述

### 1.1 什么是 Addressables？

Unity Addressables（可寻址资源系统）是 Unity 官方推出的资源管理解决方案，用于替代传统的 `AssetBundle` 手动管理。它的核心思想是：**给每个资源起一个"地址"（Address/Key），运行时通过地址加载，而不关心资源具体在哪个 Bundle 里、Bundle 在哪台服务器上。**

**传统 AssetBundle 方式**（痛苦）：
```
1. 手动管理 Bundle 依赖关系
2. 手动管理 Bundle 的引用计数
3. 手动写下载逻辑（断点续传、校验）
4. 手动维护版本映射表
```

**Addressables 方式**（轻松）：
```
1. 给资源设置 Address（如 "Patch/PatchUI_New.prefab"）
2. 调用 Addressables.LoadAssetAsync<T>("地址")
3. 系统自动处理：依赖加载、缓存、引用计数、下载
```

### 1.2 在热更新中的角色

在本项目中，Addressables 承担以下职责：

| 职责 | 说明 |
|------|------|
| 资源寻址 | 通过 Key/Address 找到资源（Bundle文件） |
| 热更路径重定向 | `InternalIdTransformFunc` 将请求重定向到热更目录 |
| Catalog 更新 | 加载热更后的 `catalog.json` 替换旧的资源映射 |
| 运行时加载 | `LoadAssetAsync`、`LoadSceneAsync` 等异步加载接口 |

---

## 2. 架构设计

### 2.1 Addressables 文件结构

```
App 安装包内（StreamingAssets/aa/）：
├── catalog.json          ← 资源映射表（地址 → Bundle文件）
├── catalog.hash          ← catalog 哈希校验
├── Android/              ← Android 平台 Bundle 目录
│   ├── game.bundle       ← 游戏资源包
│   ├── ui.bundle         ← UI 资源包
│   └── ...
└── ...

热更目录（persistentDataPath/ResUpdate/）：
├── catalog.json          ← 新版本的资源映射表（覆盖安装包内的）
├── Android/
│   ├── game.bundle       ← 更新的 Bundle（覆盖安装包内的）
│   └── ...
└── UpdateVersion/
    └── AAVersionNumber.txt ← 当前 AA 版本号
```

### 2.2 热更路径重定向原理

```
Addressables.LoadAssetAsync("角色/英雄甲.prefab")
         │
         ▼
  [InternalIdTransformFunc 回调]
         │
         ├─ 计算热更路径：persistentDataPath/ResUpdate/Android/角色/英雄甲.bundle
         │
         ├─ File.Exists(热更路径)? ──── YES ──→ 返回热更路径（使用新版本）
         │
         └─ NO → 返回原始路径（使用安装包内资源）
```

### 2.3 Catalog 更新流程

```
游戏启动
  │
  ▼
BeginAdressableCatalogUpdate()
  │
  ▼
检查 persistentDataPath/ResUpdate/catalog.json 是否存在？
  │
  ├─ 存在 → LoadContentCatalogAsync(catalogPath) 加载自定义 Catalog
  │           ├─ 成功 → Addressables.AddResourceLocator(handle.Result)
  │           │         Addressables.InitializeAsync()
  │           │         ↓
  │           │         InitGame()  ← 进入游戏
  │           └─ 失败 → InitGame()（降级处理）
  │
  └─ 不存在 → 跳过，直接 InitGame()（使用安装包内资源）
```

---

## 3. 核心代码展示

### 3.1 路径转换函数注册（热更核心）

```csharp
// PatchManager.Start() 中注册路径转换回调
aaPrefix = Addressables.RuntimePath + "/";
Addressables.InternalIdTransformFunc += TransformResourcePath;
```

```csharp
private const string HotUpdateRootDir = "ResUpdate";

#if UNITY_ANDROID
private string platformDir = "Android";
#elif UNITY_IOS
private string platformDir = "iOS";
#else
private string platformDir = "StandaloneWindows";
#endif

// 缓存字典，避免重复计算路径
private Dictionary<string, string> hotUpdatePathMap = new Dictionary<string, string>();

private string TransformResourcePath(IResourceLocation location)
{
    string hotUpdatePath;
    if (!hotUpdatePathMap.TryGetValue(location.InternalId, out hotUpdatePath))
    {
        // 去掉 Addressables 内置的 RuntimePath 前缀，得到相对路径
        var key = location.InternalId.Replace(aaPrefix, "");
        
        // 拼接热更目录路径
        hotUpdatePath = Path.Combine(
            Application.persistentDataPath,
            HotUpdateRootDir,
            key
        );
        hotUpdatePathMap[location.InternalId] = hotUpdatePath;
    }
    
    // 热更目录有该文件 → 使用热更版本
    if (File.Exists(hotUpdatePath))
        return hotUpdatePath;
    
    // 否则使用原始路径（安装包内资源）
    return location.InternalId;
}
```

**为什么需要路径转换？**

Addressables 默认只知道安装包内资源的路径（StreamingAssets 或远程 URL）。通过 `InternalIdTransformFunc`，我们告诉 Addressables："如果热更目录里有这个文件，就去热更目录找，别去安装包里找"。这样就实现了热更文件"覆盖"安装包文件的效果。

### 3.2 Catalog 加载（热更后更新资源映射）

```csharp
public void BeginAdressableCatalogUpdate()
{
    StartCoroutine(LoadCustomCatalog());
}

IEnumerator LoadCustomCatalog()
{
    // Dolphin 下载完成后，新的 catalog.json 已存放在热更目录
    string catalogPath = System.IO.Path.Combine(
        Application.persistentDataPath, "ResUpdate", "catalog.json");
    
    PatchLog.Info(catalogPath);
    
    if (File.Exists(catalogPath))
    {
        // 加载自定义 Catalog（替换旧的资源映射）
        var handle = Addressables.LoadContentCatalogAsync(catalogPath);
        yield return handle;

        if (handle.Status == AsyncOperationStatus.Succeeded)
        {
            // 将新的资源定位器添加到 Addressables（新 catalog 优先级更高）
            Addressables.AddResourceLocator(handle.Result);
            PatchLog.Info("Catalog更新成功");
            
            // 重新初始化 Addressables（应用新 Catalog）
            AsyncOperationHandle<IResourceLocator> initOperationHandle = 
                Addressables.InitializeAsync(true);
            yield return initOperationHandle;
            yield return null;
        }
        else
        {
            PatchLog.Info("Catalog加载失败");
            // 失败时降级处理：使用安装包内的原始 Catalog
        }
    }
    
    // 无论成功失败，都进入游戏
    InitGame(true); // hasAAInitialized = true
}
```

### 3.3 Addressables 初始化（进入游戏前）

```csharp
IEnumerator InitEnterLoginGame(bool hasAAInitialized)
{
    if (!hasAAInitialized)
    {
        // 如果 Catalog 更新流程没有初始化 AA，在这里初始化
        AsyncOperationHandle<IResourceLocator> initOperationHandle = 
            Addressables.InitializeAsync(true);
        yield return initOperationHandle;
        yield return null;
    }

    // 触发热更完成回调，通知 ClientBridge 加载热更 DLL
    if (onAfterPatch != null)
    {
        onAfterPatch(String.Empty);
    }
}
```

### 3.4 资源加载的封装方法

```csharp
// PatchManager 内部封装的加载方法，追踪所有 AA 句柄以便统一释放
private AsyncOperationHandle<T> loadAA<T>(string path)
{
    var aa = Addressables.LoadAssetAsync<T>(path);
    AAhandlerList.Add(aa);  // 记录所有已加载句柄
    return aa;
}

// 释放所有已加载的资源（PatchUI 销毁时调用）
private void releaseAllAssets()
{
    for (int i = 0; i < AAhandlerList.Count; i++)
    {
        Addressables.Release(AAhandlerList[i]);
    }
    Resources.UnloadUnusedAssets();
}
```

**新手注意**：Addressables 加载的资源**必须手动释放**（`Addressables.Release(handle)`），否则会造成内存泄漏。这里的 `AAhandlerList` 列表统一管理了热更阶段加载的所有资源，在 `PatchUI` 销毁时一次性释放。

### 3.5 同步加载（用于必须立即获得资源的场景）

```csharp
// Index.cs 中的同步加载示例
var handle = Addressables.LoadAssetAsync<GameObject>("Patch/SplashUI.prefab");
var prefab = handle.WaitForCompletion(); // 同步等待，不推荐大资源使用

// PatchManager.cs 中加载 PatchUI
var handler = loadAA<GameObject>("Patch/PatchUI_New.prefab");
handler.WaitForCompletion(); // 首帧必须显示 UI，所以同步加载
GameObject ui = GameObject.Instantiate(handler.Result);
```

**注意**：`WaitForCompletion()` 是同步加载，会阻塞主线程。只用于启动阶段的小资源（如 UI 预制体），游戏运行中大资源必须使用异步加载。

### 3.6 Resource Locator 操作（高级 Catalog 管理）

```csharp
// VersionManager.cs - 替换第一个 Resource Locator
static public void ChangeFirstResourceLocators(IResourceLocator replaceCatalog)
{
    List<ResourceLocatorInfo> resourceLocators = new List<ResourceLocatorInfo>();
    List<string> locatorIds = new List<string>();

    IResourceLocator oldCatalog = null;
    locatorIds.Add(replaceCatalog.LocatorId); // 新 catalog 放在最前面（最高优先级）
    
    // 遍历现有的 ResourceLocators
    IEnumerator<IResourceLocator> it = Addressables.ResourceLocators.GetEnumerator();
    while (it.MoveNext())
    {
        if (replaceCatalog.LocatorId != it.Current.LocatorId)
        {
            locatorIds.Add(it.Current.LocatorId);
            if (oldCatalog == null) oldCatalog = it.Current;
        }
    }
    
    locatorIds.RemoveAt(1); // 移除旧的第一个 Locator
    
    // 重新注册，确保新 catalog 排第一
    foreach (string locatorId in locatorIds)
        resourceLocators.Add(Addressables.GetLocatorInfo(locatorId));
    
    Addressables.ClearResourceLocators();
    
    for (int i = 0; i < resourceLocators.Count; ++i)
    {
        Addressables.AddResourceLocator(
            resourceLocators[i].Locator,
            resourceLocators[i].LocalHash,
            resourceLocators[i].CatalogLocation);
    }
}
```

---

## 4. 设计亮点

### 4.1 双重保险机制

本项目使用了两个相互补充的热更机制：

1. **Catalog 替换**：更新资源的"目录"（告诉 Addressables 资源地址变了）
2. **路径重定向**：更新资源的"文件"（让 Addressables 从热更目录读取新文件）

即使 Catalog 更新失败，路径重定向机制仍然能使新下载的 Bundle 文件被优先加载（只要文件名与旧版一致）。

### 4.2 延迟释放设计

`PatchManager.DestroyPatchUI()` 方法在 MapLoadingPanel 打开**之后**才被调用（由 `ClientBridge.NotifyMapLoadingPanelOpened()` 触发），确保热更 UI 的资源不会在游戏 UI 完全就绪之前被释放：

```csharp
// PatchManager.cs
public void DestroyPatchUI()
{
    if (!isSkipPatch && uiInstance != null)
    {
        GameObject.Destroy(uiInstance.gameObject);
        uiInstance = null;
    }
    releaseAllAssets(); // 热更阶段所有加载的资源一次性释放
    GameObject.Destroy(gameObject);
}
```

### 4.3 路径转换缓存

`hotUpdatePathMap` 字典缓存了所有已计算的热更路径，避免每次资源请求都做字符串操作，在资源密集加载时能显著减少 GC 压力。

---

## 5. 常见问题与最佳实践

### Q1：Addressables.InitializeAsync 需要调用几次？
**A**：整个游戏生命周期调用一次即可（幂等的）。如果在 LoadCustomCatalog 中已经调用过，则 `InitEnterLoginGame` 的参数 `hasAAInitialized=true` 会跳过重复调用。

### Q2：`AddResourceLocator` 和 `ChangeFirstResourceLocators` 的区别？
**A**：
- `AddResourceLocator`：将新 Catalog 追加到 Locators 列表末尾，优先级最低
- `ChangeFirstResourceLocators`：将新 Catalog 插入到 Locators 列表第一位，**优先级最高**

本项目的 `LoadCustomCatalog` 使用的是 `AddResourceLocator`（追加），而 `VersionManager.ChangeFirstResourceLocators` 使用的是替换第一位的方式（更高优先级）。前者适合大多数情况，后者适合需要强制覆盖所有旧资源的场景。

### Q3：热更后资源没有更新怎么排查？
**A**：按以下步骤排查：
1. 确认 `persistentDataPath/ResUpdate/catalog.json` 文件存在且是最新版
2. 确认对应的 Bundle 文件在 `ResUpdate/` 目录下存在
3. 确认 `TransformResourcePath` 函数中的路径拼接正确（打日志 `PatchLog.Info(hotUpdatePath)`）
4. 确认 `File.Exists(hotUpdatePath)` 返回 `true`
5. 检查大小写：Android/iOS 文件系统区分大小写！

### Q4：Addressables 加载失败如何处理？
**A**：检查 `handle.Status == AsyncOperationStatus.Failed`，并访问 `handle.OperationException` 获取详细错误。常见原因：
- 地址/Key 拼写错误
- Bundle 文件损坏（MD5 校验失败）
- Bundle 文件不存在（热更下载失败）
- 依赖 Bundle 缺失

### Q5：如何在编辑器中验证热更路径重定向？
**A**：Addressables 的 `InternalIdTransformFunc` 在编辑器中同样生效。可以在 `TransformResourcePath` 函数中添加日志：
```csharp
PatchLog.Info($"请求: {location.InternalId} → 热更路径: {hotUpdatePath} 存在: {File.Exists(hotUpdatePath)}");
```
然后在编辑器的 `persistentDataPath/ResUpdate/` 目录下手动放入测试文件，验证重定向是否生效。
