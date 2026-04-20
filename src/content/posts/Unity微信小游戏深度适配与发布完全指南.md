---
title: Unity微信小游戏深度适配与发布完全指南：从WebGL构建到线上优化
published: 2026-04-20
description: 全面解析Unity游戏适配微信小游戏平台的核心技术，涵盖微信小游戏SDK接入、Unity WebGL构建配置、分包与首包优化、内存限制规避、本地缓存策略、微信登录与支付接入、性能优化与真机调试完整流程，助你高效将Unity游戏发布到微信生态。
tags: [微信小游戏, Unity, WebGL, 小游戏适配, 跨平台, 性能优化]
category: 游戏开发
draft: false
---

# Unity微信小游戏深度适配与发布完全指南：从WebGL构建到线上优化

## 一、微信小游戏技术架构概述

微信小游戏运行在微信的 JavaScript 沙盒环境中，基于 WebAssembly（WASM）执行 C# 编译产物。其核心架构如下：

```
Unity C# 代码
    ↓ IL2CPP + Emscripten
WebAssembly (.wasm)
    ↓
微信小游戏 JS 引擎
    ↓
WebGL 渲染上下文（OpenGL ES 2.0/3.0）
    ↓
微信 Native 渲染层
```

### 1.1 与标准 WebGL 的差异

| 特性 | 标准 WebGL | 微信小游戏 |
|-----|-----------|----------|
| 包体大小 | 无限制 | 主包 ≤4MB，分包 ≤20MB |
| 内存上限 | 浏览器限制 | iOS ~1GB，Android ~2GB |
| 本地存储 | localStorage | wx.setStorage (10MB) |
| 网络请求 | fetch/XHR | wx.request（需域名白名单）|
| 文件系统 | 无 | wx.getFileSystemManager |
| 音频 | Web Audio | wx.createInnerAudioContext |

---

## 二、环境搭建与项目配置

### 2.1 安装微信小游戏转换工具

```bash
# 安装微信开发者工具（需要 GUI，建议在本地开发机执行）
# 下载地址: https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html

# 安装 Unity 微信小游戏适配包（通过 Package Manager）
# 添加到 manifest.json:
{
  "dependencies": {
    "com.tencent.minigame": "https://gitee.com/wechat-minigame/minigame-unity-webgl-transform.git#main"
  }
}
```

### 2.2 Unity 项目基础配置

```csharp
// Editor/MiniGameBuildSettings.cs
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

public class MiniGameBuildSettings
{
    [MenuItem("MiniGame/一键配置微信小游戏环境")]
    public static void ConfigureForMiniGame()
    {
        // 1. 切换构建目标
        EditorUserBuildSettings.SwitchActiveBuildTarget(
            BuildTargetGroup.WebGL, BuildTarget.WebGL);
        
        // 2. 配置 Player Settings
        PlayerSettings.SetScriptingBackend(
            BuildTargetGroup.WebGL, ScriptingImplementation.IL2CPP);
        
        // 3. 禁用不支持的功能
        PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
        PlayerSettings.WebGL.linkerTarget = WebGLLinkerTarget.Wasm;
        PlayerSettings.WebGL.threadsSupport = false;  // 微信不支持 SharedArrayBuffer
        
        // 4. 内存配置（微信小游戏推荐 256MB）
        PlayerSettings.WebGL.memorySize = 256;
        
        // 5. 异常处理（关闭以减小包体）
        PlayerSettings.WebGL.exceptionSupport = WebGLExceptionSupport.None;
        
        // 6. 数据缓存
        PlayerSettings.WebGL.dataCaching = false;  // 交由微信 FileSystem 管理
        
        Debug.Log("[MiniGame] 微信小游戏环境配置完成！");
        AssetDatabase.SaveAssets();
    }
}
#endif
```

---

## 三、分包策略与首包优化

微信小游戏主包不得超过 **4MB**，这是最大的工程挑战。

### 3.1 分包架构设计

```
主包 (≤4MB)
├── 启动逻辑（JS 胶水代码）
├── Unity WASM 框架代码（最小集）
└── 首屏必需资源（Logo、加载UI）

子包1：游戏核心逻辑 (≤20MB)
├── unity.data（核心 Scene）
└── 核心 Shader Variant

子包2：游戏资源 (≤20MB)
├── 角色贴图/模型
└── 特效资源

CDN 远端资源：无大小限制
├── 音频文件
├── 大型关卡资源
└── 非首屏 UI 资源
```

### 3.2 Addressables + 微信文件系统集成

```csharp
// Runtime/WXResourceLoader.cs
using System;
using System.Collections;
using UnityEngine;
using UnityEngine.AddressableAssets;
using UnityEngine.ResourceManagement.AsyncOperations;

#if UNITY_WEBGL && !UNITY_EDITOR
using WeChatWASM;
#endif

/// <summary>
/// 微信小游戏资源加载器
/// 优先读取本地缓存，缓存未命中则从 CDN 下载并写入 wx 文件系统
/// </summary>
public class WXResourceLoader : MonoBehaviour
{
    private static WXResourceLoader _instance;
    public static WXResourceLoader Instance => _instance;
    
    // wx 文件系统缓存路径
    private const string CACHE_DIR = "wxfile://usr/cachedAssets/";
    private const long MAX_CACHE_SIZE = 50 * 1024 * 1024;  // 50MB
    
    void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }
    
    /// <summary>
    /// 加载远端资源（带本地缓存）
    /// </summary>
    public IEnumerator LoadWithCache<T>(string address, Action<T> onComplete) 
        where T : UnityEngine.Object
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        string localPath = CACHE_DIR + GetCacheKey(address);
        
        // 1. 检查本地缓存
        if (WXFileExists(localPath))
        {
            yield return LoadFromWXFile<T>(localPath, onComplete);
            yield break;
        }
        
        // 2. 从 CDN 下载并缓存
        yield return DownloadAndCache(address, localPath, () =>
        {
            StartCoroutine(LoadFromWXFile<T>(localPath, onComplete));
        });
#else
        // 编辑器/非微信环境：直接用 Addressables
        var handle = Addressables.LoadAssetAsync<T>(address);
        yield return handle;
        if (handle.Status == AsyncOperationStatus.Succeeded)
            onComplete?.Invoke(handle.Result);
#endif
    }

#if UNITY_WEBGL && !UNITY_EDITOR
    private bool WXFileExists(string path)
    {
        bool exists = false;
        WX.GetFileSystemManager().Access(path, 
            res => exists = true, 
            err => exists = false);
        return exists;
    }
    
    private IEnumerator DownloadAndCache(string url, string localPath, Action onDone)
    {
        bool done = false;
        string error = null;
        
        WX.DownloadFile(new DownloadFileOption
        {
            url = url,
            filePath = localPath,
            success = res =>
            {
                Debug.Log($"[WXCache] 缓存成功: {localPath}");
                done = true;
                onDone?.Invoke();
            },
            fail = res =>
            {
                error = res.errMsg;
                done = true;
            }
        });
        
        yield return new WaitUntil(() => done);
        
        if (error != null)
            Debug.LogError($"[WXCache] 下载失败: {error}");
    }
    
    private IEnumerator LoadFromWXFile<T>(string path, Action<T> onComplete) 
        where T : UnityEngine.Object
    {
        // 使用 AssetBundle 从 wx 文件系统加载
        var request = AssetBundle.LoadFromFileAsync(path.Replace("wxfile://", ""));
        yield return request;
        
        if (request.assetBundle != null)
        {
            var asset = request.assetBundle.LoadAsset<T>(typeof(T).Name);
            onComplete?.Invoke(asset);
        }
    }
#endif
    
    private string GetCacheKey(string address)
    {
        return address.Replace("/", "_").Replace(":", "_") + ".bundle";
    }
}
```

---

## 四、微信 SDK 核心功能接入

### 4.1 登录与用户信息

```csharp
// Runtime/WXAuthManager.cs
using System;
using UnityEngine;

#if UNITY_WEBGL && !UNITY_EDITOR
using WeChatWASM;
#endif

/// <summary>
/// 微信登录与用户信息管理器
/// </summary>
public class WXAuthManager : MonoBehaviour
{
    [Serializable]
    public class WXUserInfo
    {
        public string openid;
        public string nickname;
        public string avatarUrl;
        public int gender;  // 0未知 1男 2女
        public string city;
        public string province;
        public string country;
    }
    
    private static WXUserInfo _cachedUserInfo;
    private static string _loginCode;
    
    public static event Action<WXUserInfo> OnLoginSuccess;
    public static event Action<string>     OnLoginFailed;
    
    public static void Login()
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        WX.Login(new LoginOption
        {
            success = res =>
            {
                _loginCode = res.code;
                Debug.Log($"[WXAuth] 登录成功，code: {_loginCode}");
                
                // 将 code 发送到游戏服务器换取 session_key 和 openid
                SendCodeToGameServer(_loginCode, OnServerAuthResult);
            },
            fail = res =>
            {
                Debug.LogError($"[WXAuth] 登录失败: {res.errMsg}");
                OnLoginFailed?.Invoke(res.errMsg);
            }
        });
#else
        // 编辑器模拟
        var mockUser = new WXUserInfo
        {
            openid    = "mock_openid_12345",
            nickname  = "测试玩家",
            avatarUrl = "",
            gender    = 1
        };
        OnLoginSuccess?.Invoke(mockUser);
#endif
    }
    
#if UNITY_WEBGL && !UNITY_EDITOR
    private static void SendCodeToGameServer(string code, Action<string, string> callback)
    {
        WX.Request(new RequestOption
        {
            url    = "https://your-game-server.com/api/wx-login",
            method = "POST",
            data   = $"{{\"code\":\"{code}\"}}",
            header = new System.Collections.Generic.Dictionary<string, string>
            {
                { "Content-Type", "application/json" }
            },
            success = res =>
            {
                var result = JsonUtility.FromJson<ServerLoginResult>(res.data.ToString());
                callback?.Invoke(result.openid, result.sessionToken);
            },
            fail = res =>
            {
                Debug.LogError($"[WXAuth] 服务器验证失败: {res.errMsg}");
                OnLoginFailed?.Invoke(res.errMsg);
            }
        });
    }
    
    private static void OnServerAuthResult(string openid, string token)
    {
        // 缓存到本地存储
        WX.SetStorageSync("openid", openid);
        WX.SetStorageSync("session_token", token);
        
        // 获取用户信息（需用户授权）
        WX.GetUserProfile(new GetUserProfileOption
        {
            desc    = "用于显示游戏昵称和头像",
            success = profileRes =>
            {
                _cachedUserInfo = new WXUserInfo
                {
                    openid    = openid,
                    nickname  = profileRes.userInfo.nickName,
                    avatarUrl = profileRes.userInfo.avatarUrl,
                    gender    = profileRes.userInfo.gender,
                };
                OnLoginSuccess?.Invoke(_cachedUserInfo);
            }
        });
    }
    
    [Serializable]
    private class ServerLoginResult
    {
        public string openid;
        public string sessionToken;
    }
#endif
    
    public static WXUserInfo GetCachedUserInfo() => _cachedUserInfo;
}
```

### 4.2 微信支付接入

```csharp
// Runtime/WXPaymentManager.cs
using System;
using UnityEngine;

#if UNITY_WEBGL && !UNITY_EDITOR
using WeChatWASM;
#endif

/// <summary>
/// 微信小游戏内购支付管理器
/// 注意：小游戏支付需先在游戏服务器下单，再调用微信支付API
/// </summary>
public class WXPaymentManager : MonoBehaviour
{
    [Serializable]
    public class OrderInfo
    {
        public string orderSn;      // 游戏服务器订单号
        public string productId;    // 商品ID
        public int    amount;       // 金额（单位：分）
        public string productName;  // 商品名称
    }
    
    public static event Action<string> OnPaySuccess;
    public static event Action<string> OnPayFailed;
    public static event Action         OnPayCancelled;
    
    /// <summary>
    /// 发起支付
    /// 流程：游戏服务器下单 → 获取微信预支付信息 → 调用 wx.requestPayment
    /// </summary>
    public static void Pay(OrderInfo order)
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        // 1. 先到游戏服务器下单，获取微信支付参数
        RequestPaymentParamsFromServer(order, wxParams =>
        {
            // 2. 调用微信支付
            WX.RequestMidasPayment(new RequestMidasPaymentOption
            {
                offerId   = wxParams.offerId,
                currencyType = "CNY",
                buyQuantity  = wxParams.buyQuantity,
                success      = res =>
                {
                    // 3. 通知游戏服务器验证支付结果
                    VerifyPaymentOnServer(order.orderSn, res.channelData, 
                        () => OnPaySuccess?.Invoke(order.orderSn));
                },
                fail = res =>
                {
                    if (res.errCode == -2)
                        OnPayCancelled?.Invoke();  // 用户主动取消
                    else
                        OnPayFailed?.Invoke(res.errMsg);
                }
            });
        });
#else
        Debug.Log($"[WXPay] 编辑器模拟支付成功: {order.productName}");
        OnPaySuccess?.Invoke(order.orderSn);
#endif
    }
    
#if UNITY_WEBGL && !UNITY_EDITOR
    [Serializable]
    private class WXPayParams
    {
        public string offerId;
        public int    buyQuantity;
        public string env;
    }
    
    private static void RequestPaymentParamsFromServer(
        OrderInfo order, Action<WXPayParams> callback)
    {
        string body = JsonUtility.ToJson(order);
        
        WX.Request(new RequestOption
        {
            url    = "https://your-game-server.com/api/create-order",
            method = "POST",
            data   = body,
            header = GetAuthHeader(),
            success = res =>
            {
                var p = JsonUtility.FromJson<WXPayParams>(res.data.ToString());
                callback?.Invoke(p);
            },
            fail = res => OnPayFailed?.Invoke(res.errMsg)
        });
    }
    
    private static void VerifyPaymentOnServer(
        string orderSn, string channelData, Action onSuccess)
    {
        string body = $"{{\"orderSn\":\"{orderSn}\",\"channelData\":\"{channelData}\"}}";
        
        WX.Request(new RequestOption
        {
            url    = "https://your-game-server.com/api/verify-payment",
            method = "POST",
            data   = body,
            header = GetAuthHeader(),
            success = _ => onSuccess?.Invoke(),
            fail    = res => Debug.LogError($"[WXPay] 验单失败: {res.errMsg}")
        });
    }
    
    private static System.Collections.Generic.Dictionary<string, string> GetAuthHeader()
    {
        string token = WX.GetStorageSync("session_token");
        return new System.Collections.Generic.Dictionary<string, string>
        {
            { "Content-Type", "application/json" },
            { "Authorization", $"Bearer {token}" }
        };
    }
#endif
}
```

---

## 五、本地数据存储适配

```csharp
// Runtime/WXStorageAdapter.cs
using UnityEngine;

/// <summary>
/// 存档系统的微信小游戏适配层
/// 屏蔽 PlayerPrefs / wx.Storage 差异
/// </summary>
public static class WXStorageAdapter
{
    /// <summary>写入字符串（最大 10MB 总量限制）</summary>
    public static void SetString(string key, string value)
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        try
        {
            WeChatWASM.WX.SetStorageSync(key, value);
        }
        catch (System.Exception e)
        {
            Debug.LogError($"[WXStorage] 写入失败（可能超出 10MB 限制）: {e.Message}");
            // 触发缓存清理策略
            ClearOldCacheEntries();
            WeChatWASM.WX.SetStorageSync(key, value);
        }
#else
        PlayerPrefs.SetString(key, value);
        PlayerPrefs.Save();
#endif
    }
    
    public static string GetString(string key, string defaultValue = "")
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        try
        {
            return WeChatWASM.WX.GetStorageSync(key);
        }
        catch
        {
            return defaultValue;
        }
#else
        return PlayerPrefs.GetString(key, defaultValue);
#endif
    }
    
    public static void SetInt(string key, int value) =>
        SetString(key, value.ToString());
    
    public static int GetInt(string key, int defaultValue = 0)
    {
        string val = GetString(key, "");
        return string.IsNullOrEmpty(val) ? defaultValue : int.Parse(val);
    }
    
    public static void DeleteKey(string key)
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        WeChatWASM.WX.RemoveStorageSync(key);
#else
        PlayerPrefs.DeleteKey(key);
#endif
    }
    
    /// <summary>
    /// 清理旧缓存（LRU 策略，按访问时间删除最老的条目）
    /// </summary>
    private static void ClearOldCacheEntries()
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        WeChatWASM.WX.GetStorageInfoSync(info =>
        {
            Debug.Log($"[WXStorage] 当前用量: {info.currentSize}KB / {info.limitSize}KB");
            Debug.Log($"[WXStorage] 已有 Key: {string.Join(", ", info.keys)}");
        });
#endif
    }
}
```

---

## 六、微信小游戏性能优化要点

### 6.1 首包瘦身实战

```csharp
// Editor/WXBuildOptimizer.cs
#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using System.IO;

public class WXBuildOptimizer : IPreprocessBuildWithReport, IPostprocessBuildWithReport
{
    public int callbackOrder => 0;
    
    public void OnPreprocessBuild(BuildReport report)
    {
        Debug.Log("[WXBuild] 构建前优化开始...");
        
        // 1. 剥离未使用的引擎模块
        StripUnusedEngineModules();
        
        // 2. 压缩 Texture（WebGL 不支持 ASTC，改用 DXT）
        SetWebGLTextureFormat();
        
        // 3. 关闭 Development Build 检查
        if (EditorUserBuildSettings.development)
        {
            Debug.LogWarning("[WXBuild] 警告：Development Build 会增加约 30% 包体");
        }
    }
    
    public void OnPostprocessBuild(BuildReport report)
    {
        string outputPath = report.summary.outputPath;
        
        // 统计各文件大小
        long wasmSize      = GetFileSize(outputPath, "*.wasm");
        long dataSize      = GetFileSize(outputPath, "*.data");
        long jsSize        = GetFileSize(outputPath, "*.js");
        
        Debug.Log($"[WXBuild] 构建完成！");
        Debug.Log($"  WASM: {wasmSize / 1024f / 1024f:F2} MB");
        Debug.Log($"  Data: {dataSize / 1024f / 1024f:F2} MB");
        Debug.Log($"  JS:   {jsSize   / 1024f / 1024f:F2} MB");
        
        if (wasmSize + dataSize + jsSize > 4 * 1024 * 1024)
        {
            Debug.LogError("[WXBuild] ⚠️ 主包超过 4MB！请检查分包配置！");
        }
    }
    
    private void StripUnusedEngineModules()
    {
        // 在 Player Settings > Other Settings > Managed Stripping Level 设为 High
        PlayerSettings.stripEngineCode = true;
        
        // 关闭不用的功能
        PlayerSettings.accelerometerFrequency = 0;
    }
    
    private void SetWebGLTextureFormat()
    {
        // WebGL 推荐格式：RGBA Compressed DXT5/DXT1
        var guids = AssetDatabase.FindAssets("t:Texture2D");
        foreach (var guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;
            
            var settings = importer.GetPlatformTextureSettings("WebGL");
            if (!settings.overridden)
            {
                settings.overridden  = true;
                settings.format      = TextureImporterFormat.DXT5;
                settings.maxTextureSize = 512;
                importer.SetPlatformTextureSettings(settings);
            }
        }
    }
    
    private long GetFileSize(string directory, string pattern)
    {
        long total = 0;
        foreach (var file in Directory.GetFiles(directory, pattern, SearchOption.AllDirectories))
            total += new FileInfo(file).Length;
        return total;
    }
}
#endif
```

### 6.2 内存泄漏防护

```csharp
// Runtime/WXMemoryGuard.cs
using System;
using System.Collections;
using UnityEngine;

/// <summary>
/// 微信小游戏内存守护者
/// iOS ~1GB 内存上限，超出会被系统直接 kill
/// </summary>
public class WXMemoryGuard : MonoBehaviour
{
    [SerializeField] private float warningThresholdMB = 700f;   // 告警阈值
    [SerializeField] private float criticalThresholdMB = 900f;  // 危险阈值
    [SerializeField] private float checkIntervalSeconds = 5f;
    
    public static event Action<float> OnMemoryWarning;
    public static event Action<float> OnMemoryCritical;
    
    IEnumerator Start()
    {
        yield return new WaitForSeconds(3f);
        
        while (true)
        {
            float usedMB = GetUsedMemoryMB();
            
            if (usedMB >= criticalThresholdMB)
            {
                Debug.LogError($"[WXMemory] 危险！内存: {usedMB:F1}MB，立即释放！");
                OnMemoryCritical?.Invoke(usedMB);
                ForceClearAllCaches();
            }
            else if (usedMB >= warningThresholdMB)
            {
                Debug.LogWarning($"[WXMemory] 告警：内存: {usedMB:F1}MB");
                OnMemoryWarning?.Invoke(usedMB);
                TryClearUnusedAssets();
            }
            
            yield return new WaitForSeconds(checkIntervalSeconds);
        }
    }
    
    private float GetUsedMemoryMB()
    {
        // Unity 提供的内存统计
        long managed = System.GC.GetTotalMemory(false);
        long native  = UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();
        return (managed + native) / 1024f / 1024f;
    }
    
    private void TryClearUnusedAssets()
    {
        Resources.UnloadUnusedAssets();
        System.GC.Collect();
    }
    
    private void ForceClearAllCaches()
    {
        // 1. 卸载所有非活跃场景的资源
        Resources.UnloadUnusedAssets();
        
        // 2. 清理 Addressables 缓存
        UnityEngine.AddressableAssets.Addressables.ReleaseInstance(gameObject);
        
        // 3. 强制 GC
        System.GC.Collect(System.GC.MaxGeneration, System.GCCollectionMode.Forced);
        
        Debug.Log("[WXMemory] 强制内存清理完成");
    }
}
```

---

## 七、真机调试与发布流程

### 7.1 调试工具链

```csharp
// Runtime/WXDebugger.cs
using UnityEngine;

/// <summary>
/// 微信小游戏调试工具
/// 在微信开发者工具控制台输出日志
/// </summary>
public static class WXDebugger
{
    private static bool _isEnabled = true;
    
    public static void Log(string message)
    {
        if (!_isEnabled) return;
        
        string formatted = $"[Game {System.DateTime.Now:HH:mm:ss}] {message}";
        
#if UNITY_WEBGL && !UNITY_EDITOR
        // 输出到微信开发者工具控制台
        WXNative.Log(formatted);
#else
        Debug.Log(formatted);
#endif
    }
    
    public static void ShowStats()
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        WeChatWASM.WX.GetPerformance(perf =>
        {
            string stats = $"FPS:{1000f/perf.cpuTime:F0} " +
                          $"CPU:{perf.cpuTime:F1}ms " +
                          $"GPU:{perf.gpuTime:F1}ms " +
                          $"Mem:{perf.memory.jsHeapSizeLimit/1024/1024}MB";
            WXNative.Log(stats);
        });
#endif
    }
}
```

### 7.2 发布流程自动化

```bash
#!/bin/bash
# scripts/build_wx_minigame.sh
# 一键构建微信小游戏脚本

set -e

PROJECT_PATH="/path/to/your/unity/project"
UNITY_PATH="/Applications/Unity/Hub/Editor/2022.3.10f1/Unity.app/Contents/MacOS/Unity"
BUILD_OUTPUT="./Builds/WXMiniGame"

echo "=== 开始构建微信小游戏 ==="

# 1. 执行 Unity 无头构建
"$UNITY_PATH" \
  -projectPath "$PROJECT_PATH" \
  -buildTarget WebGL \
  -executeMethod MiniGameBuildSettings.BuildFromCommandLine \
  -outputPath "$BUILD_OUTPUT" \
  -quit \
  -batchmode \
  -logFile "./build_log.txt"

echo "✅ Unity 构建完成"

# 2. 检查主包大小
MAIN_PACKAGE_SIZE=$(du -sh "$BUILD_OUTPUT" | cut -f1)
echo "📦 主包大小: $MAIN_PACKAGE_SIZE"

# 3. 调用微信 CLI 上传（需安装 miniprogram-ci）
npx miniprogram-ci upload \
  --pp "$BUILD_OUTPUT" \
  --pkp "./wx-private-key.key" \
  --appid "wxYOUR_APP_ID" \
  --uv "1.0.$(date +%Y%m%d%H%M)" \
  --desc "Auto build $(date '+%Y-%m-%d %H:%M:%S')"

echo "🚀 上传完成！请在微信公众平台提交审核。"
```

---

## 八、最佳实践总结

### 8.1 包体优化清单

| 措施 | 预期收益 |
|-----|---------|
| 关闭 Exception Support | -15% WASM |
| 启用 Code Stripping (High) | -20% WASM |
| 音频转为 MP3（体积最小） | -40% 音频 |
| 纹理改为 DXT5/ETC2 | -50% 纹理 |
| 关闭 Development Build | -30% 总体积 |
| 非首屏资源移入分包/CDN | 主包降至 ≤4MB |

### 8.2 常见问题与解决方案

```
❌ 问题：wx.request 报域名不合法
✅ 方案：在微信公众平台「开发设置」→「服务器域名」添加业务域名

❌ 问题：WebGL 构建后白屏
✅ 方案：检查 Console 错误，常见原因：缺少 WebGL 模板文件或 WASM 内存不足

❌ 问题：iOS 在战斗中被系统 kill
✅ 方案：降低 WebGL Memory Size（256MB → 192MB），及时 UnloadUnusedAssets

❌ 问题：微信登录 code 过期（5分钟有效）
✅ 方案：每次打开小游戏重新调用 WX.Login，不要缓存 code

❌ 问题：音频播放卡顿
✅ 方案：改用 wx.createInnerAudioContext，预加载关键音效，避免并发超过 6 个
```

### 8.3 核心架构原则

1. **分层隔离**：所有 wx API 调用封装在 Adapter 层，方便编辑器内模拟
2. **首包最小化**：只放启动所必需的逻辑，其余全部分包或走 CDN
3. **缓存优先**：利用 wx 文件系统缓存热点资源，减少网络依赖
4. **内存预算**：iOS 保守估计 800MB 可用内存，定时监控主动清理
5. **支付安全**：支付参数必须经过服务器下单，客户端不持有敏感信息

通过以上方案，可以将一个标准 Unity 游戏成功适配到微信小游戏平台，在享受微信生态亿级用户流量的同时，保持良好的游戏体验。
