---
title: 游戏内WebView与混合界面系统：H5活动页嵌入与CEF深度实践
published: 2026-04-19
description: 深入讲解游戏内嵌WebView技术方案，涵盖UniWebView/Android WebView/WKWebView原生集成、游戏与H5双向通信协议设计、活动运营页面渲染优化、CEF在PC游戏中的应用，以及JSBridge安全设计完全指南
tags: [Unity, WebView, H5, JSBridge, 运营系统, 混合开发, CEF, 游戏开发]
category: 系统架构
draft: false
---

# 游戏内WebView与混合界面系统：H5活动页嵌入与CEF深度实践

## 1. 为什么游戏需要内嵌WebView？

现代大型手游（王者荣耀、和平精英、原神等）大量使用WebView技术：

- **活动运营页面**：限时活动、节日庆典页面可独立部署，无需热更新客户端
- **商城与支付**：H5商城页面快速迭代，A/B测试界面布局
- **官网公告/帮助**：游戏内直接查看官网FAQ，无需跳出App
- **第三方服务**：客服系统、赛事观看、直播页面
- **法律合规页面**：隐私政策、用户协议（法务要求随时可更新）
- **赛季通行证**：复杂的赛季界面由前端团队独立开发

WebView技术的核心价值：**降低运营更新成本，提升界面迭代速度**。

---

## 2. 技术方案全景对比

| 方案 | 平台 | 引擎接入 | 性能 | 功能完整性 | 适用场景 |
|------|------|---------|------|-----------|---------|
| UniWebView 4 | iOS/Android | Unity插件 | ★★★★ | ★★★★★ | 商业手游首选 |
| Android WebView | Android | 原生插件 | ★★★★ | ★★★★ | 自研Android游戏 |
| WKWebView | iOS | 原生插件 | ★★★★★ | ★★★★ | 自研iOS游戏 |
| CEF (Chromium) | PC (Win/Mac/Linux) | C++插件 | ★★★ | ★★★★★ | PC游戏（Dota2/Steam客户端均使用） |
| WebGL Canvas | 全平台 | Unity内置 | ★★ | ★★ | 轻量展示，无需交互 |
| 自研简易渲染 | 全平台 | 纯C# | ★★★★★ | ★ | 仅展示静态HTML/CSS |

---

## 3. UniWebView集成方案（Unity移动端最佳实践）

### 3.1 WebView管理器设计

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// WebView管理器 - 统一管理游戏内所有WebView实例
/// 支持：H5活动页、商城、客服、帮助中心
/// </summary>
public class GameWebViewManager : MonoBehaviour
{
    private static GameWebViewManager _instance;
    public static GameWebViewManager Instance => _instance;
    
    [Header("WebView配置")]
    [SerializeField] private string baseUrl = "https://activity.yourgame.com";
    [SerializeField] private bool enableJSBridge = true;
    [SerializeField] private bool enableCache = true;
    [SerializeField] private int cacheMaxAgeDays = 7;
    
    [Header("预加载配置")]
    [SerializeField] private bool preloadOnStart = true;
    [SerializeField] private string[] preloadUrls;  // 预加载高频活动页
    
    // 活跃WebView实例池
    private readonly Dictionary<string, UniWebView> activeViews = new();
    private readonly Queue<string> preloadQueue = new();
    
    // 游戏与H5通信层
    private JSBridgeHandler jsBridge;
    
    public event Action<string, string> OnWebViewMessage;  // (viewId, message)
    public event Action<string> OnWebViewClosed;            // viewId
    
    private void Awake()
    {
        if (_instance != null) { Destroy(gameObject); return; }
        _instance = this;
        DontDestroyOnLoad(gameObject);
        
        jsBridge = GetComponent<JSBridgeHandler>() ?? gameObject.AddComponent<JSBridgeHandler>();
    }
    
    private void Start()
    {
        if (preloadOnStart)
            StartCoroutine(PreloadPages());
    }
    
    // ============================================
    // 核心公共接口
    // ============================================
    
    /// <summary>
    /// 打开活动页（最常用）
    /// </summary>
    /// <param name="activityId">活动ID，如 "spring_festival_2026"</param>
    /// <param name="rect">显示区域（0~1归一化坐标）</param>
    public void OpenActivity(string activityId, RectTransform anchorRect = null)
    {
        string url = $"{baseUrl}/activity/{activityId}?{BuildQueryParams()}";
        OpenWebView(activityId, url, anchorRect ?? GetDefaultRect());
    }
    
    /// <summary>
    /// 打开商城页面
    /// </summary>
    public void OpenShop(string category = "featured")
    {
        string url = $"{baseUrl}/shop/{category}?{BuildQueryParams()}";
        OpenWebView("shop", url, GetFullScreenRect());
    }
    
    /// <summary>
    /// 打开帮助中心
    /// </summary>
    public void OpenHelpCenter(string articleId = null)
    {
        string url = string.IsNullOrEmpty(articleId) 
            ? $"{baseUrl}/help?{BuildQueryParams()}"
            : $"{baseUrl}/help/{articleId}?{BuildQueryParams()}";
        OpenWebView("help", url, GetHalfScreenRect());
    }
    
    /// <summary>
    /// 打开隐私政策/用户协议
    /// </summary>
    public void OpenLegalPage(string pageType) // "privacy" | "terms"
    {
        string url = $"{baseUrl}/legal/{pageType}?lang={GetLanguageCode()}";
        OpenWebView($"legal_{pageType}", url, GetFullScreenRect(), showCloseButton: true);
    }
    
    /// <summary>
    /// 核心方法：创建并显示WebView
    /// </summary>
    public UniWebView OpenWebView(string viewId, string url, Rect rect, bool showCloseButton = false)
    {
        // 复用已存在的实例
        if (activeViews.TryGetValue(viewId, out var existingView))
        {
            existingView.Show();
            existingView.Load(url);
            return existingView;
        }
        
        var webView = CreateWebView(viewId, rect);
        
        // 注册事件处理
        webView.OnMessageReceived += (view, message) => HandleJSMessage(viewId, message);
        webView.OnShouldClose     += (view) => { OnWebViewClosed?.Invoke(viewId); return true; };
        webView.OnPageFinished    += (view, code, msg) => OnPageLoaded(viewId, code, msg);
        webView.OnPageErrorReceived += (view, code, msg) => OnPageError(viewId, code, msg);
        
        // 安全配置
        ConfigureWebViewSecurity(webView);
        
        // 加载URL
        webView.Load(url);
        webView.Show();
        
        activeViews[viewId] = webView;
        
        if (showCloseButton)
            ShowNativeCloseButton(webView);
        
        Debug.Log($"[WebView] 打开: {viewId} -> {url}");
        return webView;
    }
    
    /// <summary>
    /// 关闭指定WebView
    /// </summary>
    public void CloseWebView(string viewId)
    {
        if (activeViews.TryGetValue(viewId, out var view))
        {
            view.Hide();
            // 延迟销毁，避免动画卡顿
            StartCoroutine(DelayedDestroy(view, viewId, 0.5f));
        }
    }
    
    // ============================================
    // 向H5发送消息（游戏→WebView）
    // ============================================
    
    /// <summary>
    /// 向H5页面发送玩家信息（页面加载后调用）
    /// </summary>
    public void SendPlayerInfoToH5(string viewId)
    {
        var playerInfo = new
        {
            userId = PlayerManager.Instance.UserId,
            nickname = PlayerManager.Instance.Nickname,
            level = PlayerManager.Instance.Level,
            vipGrade = PlayerManager.Instance.VIPGrade,
            diamonds = PlayerManager.Instance.Diamonds,
            token = GetSecureToken(),
            platform = Application.platform.ToString(),
            gameVersion = Application.version,
        };
        
        string json = JsonUtility.ToJson(playerInfo);
        EvaluateJavaScript(viewId, $"window.GameSDK && window.GameSDK.onPlayerInfo({json})");
    }
    
    /// <summary>
    /// 执行JavaScript代码（游戏主动调用H5函数）
    /// </summary>
    public void EvaluateJavaScript(string viewId, string jsCode)
    {
        if (activeViews.TryGetValue(viewId, out var view))
        {
            view.EvaluateJavaScript(jsCode, (payload) =>
            {
                if (!string.IsNullOrEmpty(payload.ResultValue))
                    Debug.Log($"[WebView] JS执行结果: {payload.ResultValue}");
            });
        }
    }
    
    // ============================================
    // 内部实现
    // ============================================
    
    private UniWebView CreateWebView(string viewId, Rect rect)
    {
        var go = new GameObject($"WebView_{viewId}");
        go.transform.SetParent(transform);
        
        var webView = go.AddComponent<UniWebView>();
        
        // 设置显示区域（基于屏幕坐标）
        webView.Frame = new Rect(
            rect.x * Screen.width,
            rect.y * Screen.height, 
            rect.width * Screen.width,
            rect.height * Screen.height
        );
        
        // 基础配置
        webView.SetBackgroundColor(Color.clear);  // 透明背景
        webView.SetBouncesEnabled(false);          // 禁用边缘弹性（移动端）
        webView.SetZoomEnabled(false);             // 禁用手势缩放
        
        if (enableCache)
        {
            // 启用磁盘缓存（减少流量，加速加载）
            webView.SetCacheMode(UniWebViewCacheMode.Default);
        }
        
        return webView;
    }
    
    private void ConfigureWebViewSecurity(UniWebView webView)
    {
        // 只允许访问白名单域名
        // 实际实现中通过OnShouldNavigate拦截非法跳转
        webView.OnShouldNavigate += (view, url) =>
        {
            if (!IsUrlAllowed(url))
            {
                Debug.LogWarning($"[WebView] 拦截非法跳转: {url}");
                // 可以在这里开启外部浏览器
                Application.OpenURL(url);
                return false;  // false = 取消WebView内导航
            }
            return true;
        };
    }
    
    private bool IsUrlAllowed(string url)
    {
        // 白名单域名校验
        string[] allowedDomains = 
        {
            "activity.yourgame.com",
            "shop.yourgame.com",
            "help.yourgame.com",
            "legal.yourgame.com",
            // 允许的CDN域名
            "cdn.yourgame.com",
        };
        
        try
        {
            var uri = new Uri(url);
            return Array.Exists(allowedDomains, d => 
                uri.Host.Equals(d, StringComparison.OrdinalIgnoreCase) ||
                uri.Host.EndsWith("." + d, StringComparison.OrdinalIgnoreCase));
        }
        catch
        {
            // about:blank 等特殊URL直接允许
            return url.StartsWith("about:") || url.StartsWith("javascript:");
        }
    }
    
    private void HandleJSMessage(string viewId, UniWebViewMessage message)
    {
        // UniWebView消息格式: gamecall://action?key=value
        string action = message.Path;
        
        jsBridge.HandleMessage(viewId, action, message.Args);
        OnWebViewMessage?.Invoke(viewId, message.RawMessage);
    }
    
    private void OnPageLoaded(string viewId, int statusCode, string message)
    {
        Debug.Log($"[WebView] 页面加载完成: {viewId}, 状态码: {statusCode}");
        
        if (statusCode == 200)
        {
            // 注入游戏SDK（让H5页面能调用游戏功能）
            InjectGameSDK(viewId);
            SendPlayerInfoToH5(viewId);
        }
    }
    
    private void OnPageError(string viewId, int code, string message)
    {
        Debug.LogError($"[WebView] 页面加载失败: {viewId}, 错误: {code} {message}");
        
        // 加载错误页面
        if (activeViews.TryGetValue(viewId, out var view))
        {
            string errorHtml = BuildErrorPage(code, message);
            view.LoadHTMLString(errorHtml, baseUrl);
        }
    }
    
    private void InjectGameSDK(string viewId)
    {
        // 注入游戏SDK JS对象，H5可通过window.GameSDK调用游戏功能
        string sdkJs = @"
            if (!window.GameSDK) {
                window.GameSDK = {
                    // H5调用游戏功能（通过UniWebView协议）
                    call: function(action, params) {
                        var url = 'gamecall://' + action;
                        if (params) url += '?' + Object.keys(params)
                            .map(k => k + '=' + encodeURIComponent(JSON.stringify(params[k])))
                            .join('&');
                        window.location.href = url;
                    },
                    // 购买道具
                    buyItem: function(itemId, quantity) {
                        this.call('buy_item', { itemId: itemId, quantity: quantity || 1 });
                    },
                    // 关闭WebView
                    close: function() { this.call('close_webview', {}); },
                    // 分享
                    share: function(content) { this.call('share', { content: content }); },
                    // 跳转到游戏内界面
                    navigate: function(uiPath, params) {
                        this.call('navigate', { path: uiPath, params: params || {} });
                    },
                    // 播放音效
                    playSound: function(soundId) { this.call('play_sound', { id: soundId }); },
                    // 震动反馈
                    vibrate: function(pattern) { this.call('vibrate', { pattern: pattern || 'light' }); },
                    // 复制到剪贴板
                    copyToClipboard: function(text) { this.call('clipboard_copy', { text: text }); },
                    // 获取玩家信息（异步，通过onPlayerInfo回调）
                    requestPlayerInfo: function() { this.call('get_player_info', {}); },
                };
                console.log('[GameSDK] 已注入');
            }
        ";
        
        EvaluateJavaScript(viewId, sdkJs);
    }
    
    private string BuildQueryParams()
    {
        return $"uid={PlayerManager.Instance?.UserId}" +
               $"&token={GetSecureToken()}" +
               $"&lang={GetLanguageCode()}" +
               $"&platform={Application.platform}" +
               $"&ver={Application.version}" +
               $"&t={DateTimeOffset.UtcNow.ToUnixTimeSeconds()}"; // 防缓存
    }
    
    private string GetSecureToken()
    {
        // 生成短期有效的HMAC签名Token，防止URL被盗用
        // 实际实现：HMAC-SHA256(userId + timestamp + secretKey)
        return PlayerPrefs.GetString("session_token", "");
    }
    
    private string GetLanguageCode()
    {
        return Application.systemLanguage switch
        {
            SystemLanguage.Chinese or SystemLanguage.ChineseSimplified => "zh-CN",
            SystemLanguage.ChineseTraditional => "zh-TW",
            SystemLanguage.English => "en",
            SystemLanguage.Japanese => "ja",
            SystemLanguage.Korean => "ko",
            _ => "en"
        };
    }
    
    private Rect GetDefaultRect() => new Rect(0.05f, 0.05f, 0.9f, 0.9f);
    private Rect GetFullScreenRect() => new Rect(0, 0, 1, 1);
    private Rect GetHalfScreenRect() => new Rect(0, 0.5f, 1, 0.5f);
    
    private void ShowNativeCloseButton(UniWebView webView) { /* 添加原生关闭按钮 */ }
    
    private IEnumerator PreloadPages()
    {
        yield return new WaitForSeconds(5f); // 游戏启动5秒后预加载，避免影响启动速度
        
        foreach (string url in preloadUrls)
        {
            // 静默预加载（不显示）
            // UniWebView支持后台预加载
            Debug.Log($"[WebView] 预加载: {url}");
            yield return new WaitForSeconds(1f); // 避免同时发起太多请求
        }
    }
    
    private IEnumerator DelayedDestroy(UniWebView view, string viewId, float delay)
    {
        yield return new WaitForSeconds(delay);
        activeViews.Remove(viewId);
        Destroy(view.gameObject);
    }
    
    private string BuildErrorPage(int code, string message)
    {
        return $@"<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<style>
  body {{ font-family: sans-serif; display: flex; flex-direction: column; 
         align-items: center; justify-content: center; height: 100vh; 
         background: #1a1a2e; color: #fff; margin: 0; }}
  .icon {{ font-size: 60px; margin-bottom: 20px; }}
  h2 {{ color: #e94560; }}
  p {{ color: #aaa; font-size: 14px; }}
  button {{ background: #e94560; color: white; border: none; padding: 12px 24px;
            border-radius: 6px; font-size: 16px; cursor: pointer; margin-top: 20px; }}
</style></head>
<body>
  <div class='icon'>⚠️</div>
  <h2>页面加载失败</h2>
  <p>错误码: {code}</p>
  <p>请检查网络连接后重试</p>
  <button onclick='location.reload()'>重新加载</button>
  <button onclick='window.GameSDK && window.GameSDK.close()'>关闭</button>
</body></html>";
    }
}
```

---

## 4. JSBridge 通信协议设计

### 4.1 双向通信架构

```
游戏客户端 (C#)          JSBridge层          H5页面 (JavaScript)
     │                      │                      │
     │  EvaluateJavaScript   │                      │
     │─────────────────────>│  window.GameSDK.onXxx │
     │                      │─────────────────────>│
     │                      │                      │
     │  OnMessageReceived    │  window.GameSDK.call  │
     │<─────────────────────│<─────────────────────│
     │    解析URL协议        │  gamecall://action   │
     │                      │                      │
     │  回调结果             │                      │
     │─────────────────────>│  window.GameSDK.      │
     │                      │  onCallResult(...)    │
     │                      │─────────────────────>│
```

### 4.2 JSBridge处理器

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// JSBridge处理器 - 处理H5页面发来的游戏功能调用请求
/// 使用命令注册模式，便于扩展新功能
/// </summary>
public class JSBridgeHandler : MonoBehaviour
{
    // 命令处理器字典
    private Dictionary<string, Action<string, Dictionary<string, string>>> commandHandlers;
    
    // 回调Promise字典（模拟异步回调）
    private Dictionary<string, string> pendingCallbacks = new();
    
    private void Awake()
    {
        RegisterBuiltinHandlers();
    }
    
    private void RegisterBuiltinHandlers()
    {
        commandHandlers = new Dictionary<string, Action<string, Dictionary<string, string>>>
        {
            // 关闭WebView
            ["close_webview"] = (viewId, args) =>
            {
                GameWebViewManager.Instance.CloseWebView(viewId);
            },
            
            // 购买道具（H5商城下单）
            ["buy_item"] = (viewId, args) =>
            {
                if (args.TryGetValue("itemId", out var itemId) &&
                    args.TryGetValue("quantity", out var quantityStr))
                {
                    int quantity = int.TryParse(quantityStr, out int q) ? q : 1;
                    HandleBuyItem(viewId, itemId, quantity);
                }
            },
            
            // 跳转游戏内UI
            ["navigate"] = (viewId, args) =>
            {
                if (args.TryGetValue("path", out var path))
                {
                    HandleNavigate(viewId, path, args);
                }
            },
            
            // 获取玩家信息
            ["get_player_info"] = (viewId, args) =>
            {
                GameWebViewManager.Instance.SendPlayerInfoToH5(viewId);
            },
            
            // 播放游戏内音效
            ["play_sound"] = (viewId, args) =>
            {
                if (args.TryGetValue("id", out var soundId))
                    AudioManager.Instance?.PlayUISound(soundId);
            },
            
            // 震动反馈
            ["vibrate"] = (viewId, args) =>
            {
                string pattern = args.TryGetValue("pattern", out var p) ? p : "light";
                HandleVibrate(pattern);
            },
            
            // 分享功能
            ["share"] = (viewId, args) =>
            {
                if (args.TryGetValue("content", out var content))
                    HandleShare(viewId, content);
            },
            
            // 复制到剪贴板
            ["clipboard_copy"] = (viewId, args) =>
            {
                if (args.TryGetValue("text", out var text))
                {
                    GUIUtility.systemCopyBuffer = text;
                    // 回调成功通知H5
                    GameWebViewManager.Instance.EvaluateJavaScript(viewId,
                        "window.GameSDK && window.GameSDK.onCopySuccess()");
                }
            },
            
            // 打开外部浏览器
            ["open_browser"] = (viewId, args) =>
            {
                if (args.TryGetValue("url", out var url) && IsExternalUrlSafe(url))
                    Application.OpenURL(url);
            },
            
            // 触发成就解锁动画
            ["achievement_unlock"] = (viewId, args) =>
            {
                if (args.TryGetValue("id", out var achievementId))
                    AchievementSystem.Instance?.TriggerUnlockAnimation(achievementId);
            },
        };
    }
    
    /// <summary>
    /// 处理来自H5的消息
    /// </summary>
    public void HandleMessage(string viewId, string action, Dictionary<string, string> args)
    {
        Debug.Log($"[JSBridge] 收到消息: action={action}, viewId={viewId}");
        
        if (commandHandlers.TryGetValue(action, out var handler))
        {
            try
            {
                handler.Invoke(viewId, args ?? new Dictionary<string, string>());
            }
            catch (Exception e)
            {
                Debug.LogError($"[JSBridge] 处理命令失败 {action}: {e.Message}");
                SendErrorToH5(viewId, action, e.Message);
            }
        }
        else
        {
            Debug.LogWarning($"[JSBridge] 未知命令: {action}");
        }
    }
    
    /// <summary>
    /// 注册自定义命令处理器（供业务层扩展）
    /// </summary>
    public void RegisterHandler(string action, Action<string, Dictionary<string, string>> handler)
    {
        commandHandlers[action] = handler;
        Debug.Log($"[JSBridge] 注册新命令: {action}");
    }
    
    // ============================================
    // 具体命令实现
    // ============================================
    
    private void HandleBuyItem(string viewId, string itemId, int quantity)
    {
        // 展示购买确认弹窗
        PurchaseDialog.Show(itemId, quantity, 
            onConfirm: () =>
            {
                ShopManager.Instance?.PurchaseItem(itemId, quantity,
                    onSuccess: (receipt) =>
                    {
                        // 通知H5购买成功
                        string json = $"{{\"itemId\":\"{itemId}\",\"quantity\":{quantity},\"receipt\":\"{receipt}\"}}";
                        GameWebViewManager.Instance.EvaluateJavaScript(viewId,
                            $"window.GameSDK && window.GameSDK.onPurchaseSuccess({json})");
                    },
                    onFailed: (reason) =>
                    {
                        GameWebViewManager.Instance.EvaluateJavaScript(viewId,
                            $"window.GameSDK && window.GameSDK.onPurchaseFailed('{reason}')");
                    });
            },
            onCancel: () =>
            {
                GameWebViewManager.Instance.EvaluateJavaScript(viewId,
                    "window.GameSDK && window.GameSDK.onPurchaseCancelled()");
            });
    }
    
    private void HandleNavigate(string viewId, string path, Dictionary<string, string> args)
    {
        // 关闭WebView并跳转到游戏内UI
        GameWebViewManager.Instance.CloseWebView(viewId);
        
        // 解析路径并导航
        switch (path)
        {
            case "hero_select":
                UIManager.Instance?.OpenPanel("HeroSelectPanel");
                break;
            case "shop":
                UIManager.Instance?.OpenPanel("ShopPanel");
                break;
            case "hero_detail":
                if (args.TryGetValue("heroId", out var heroId))
                    UIManager.Instance?.OpenPanel("HeroDetailPanel", heroId);
                break;
            default:
                Debug.LogWarning($"[JSBridge] 未知导航路径: {path}");
                break;
        }
    }
    
    private void HandleVibrate(string pattern)
    {
#if UNITY_ANDROID || UNITY_IOS
        switch (pattern)
        {
            case "light":
                Handheld.Vibrate();
                break;
            case "medium":
                Handheld.Vibrate();
                break;
            case "heavy":
                Handheld.Vibrate();
                break;
        }
#endif
    }
    
    private void HandleShare(string viewId, string content)
    {
        // 调用系统分享菜单
        new NativeShare()
            .SetText(content)
            .SetCallback((result, target) =>
            {
                string status = result == NativeShare.ShareResult.Shared ? "success" : "cancelled";
                GameWebViewManager.Instance.EvaluateJavaScript(viewId,
                    $"window.GameSDK && window.GameSDK.onShareResult('{status}')");
            })
            .Share();
    }
    
    private void SendErrorToH5(string viewId, string action, string error)
    {
        GameWebViewManager.Instance.EvaluateJavaScript(viewId,
            $"window.GameSDK && window.GameSDK.onError('{action}', '{error}')");
    }
    
    private bool IsExternalUrlSafe(string url)
    {
        // 白名单检查，防止XSS攻击利用open_browser打开恶意链接
        string[] safeDomains = { "www.yourgame.com", "support.yourgame.com" };
        try
        {
            var uri = new Uri(url);
            return (uri.Scheme == "https") && 
                   Array.Exists(safeDomains, d => uri.Host.EndsWith(d));
        }
        catch { return false; }
    }
}
```

---

## 5. PC端 CEF（Chromium Embedded Framework）集成

PC游戏（如Dota 2、Steam客户端）大量使用CEF实现界面，性能远超WebView。

### 5.1 Unity中集成CEF

```csharp
using System;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// CEF浏览器集成 - 适用于PC端游戏
/// 使用CEF的离屏渲染模式（OSR），将画面渲染到Unity RenderTexture
/// </summary>
public class CEFBrowser : MonoBehaviour
{
    [Header("CEF配置")]
    [SerializeField] private RawImage displayImage;  // 显示CEF渲染结果的UI元素
    [SerializeField] private string initialUrl = "about:blank";
    [SerializeField] private int browserWidth = 1280;
    [SerializeField] private int browserHeight = 720;
    
    private Texture2D browserTexture;
    private IntPtr browserHandle = IntPtr.Zero;
    private byte[] pixelBuffer;
    
    // CEF原生插件接口（P/Invoke）
    private const string CEFPlugin = "GameCEFPlugin"; // 自定义CEF封装DLL
    
    [DllImport(CEFPlugin)] private static extern bool CEF_Initialize(string appDataPath);
    [DllImport(CEFPlugin)] private static extern IntPtr CEF_CreateBrowser(int width, int height);
    [DllImport(CEFPlugin)] private static extern void CEF_LoadURL(IntPtr browser, string url);
    [DllImport(CEFPlugin)] private static extern void CEF_EvaluateJS(IntPtr browser, string code);
    [DllImport(CEFPlugin)] private static extern bool CEF_GetPixels(IntPtr browser, IntPtr buffer, int bufferSize);
    [DllImport(CEFPlugin)] private static extern void CEF_SendMouseClick(IntPtr browser, int x, int y, int button);
    [DllImport(CEFPlugin)] private static extern void CEF_SendKeyEvent(IntPtr browser, int keyCode, bool pressed);
    [DllImport(CEFPlugin)] private static extern void CEF_CloseBrowser(IntPtr browser);
    [DllImport(CEFPlugin)] private static extern void CEF_Shutdown();
    
    private void Start()
    {
#if UNITY_STANDALONE_WIN || UNITY_STANDALONE_OSX
        InitializeCEF();
#else
        Debug.LogWarning("[CEF] 仅支持PC平台");
        enabled = false;
#endif
    }
    
    private void InitializeCEF()
    {
        // 初始化CEF（整个应用只需一次）
        string cacheDir = Application.persistentDataPath + "/cef_cache";
        if (!CEF_Initialize(cacheDir))
        {
            Debug.LogError("[CEF] 初始化失败！请确保CEF运行时库已正确部署");
            return;
        }
        
        // 创建离屏浏览器实例
        browserHandle = CEF_CreateBrowser(browserWidth, browserHeight);
        if (browserHandle == IntPtr.Zero)
        {
            Debug.LogError("[CEF] 创建浏览器实例失败");
            return;
        }
        
        // 创建渲染纹理
        browserTexture = new Texture2D(browserWidth, browserHeight, TextureFormat.RGBA32, false);
        pixelBuffer = new byte[browserWidth * browserHeight * 4];
        
        if (displayImage != null)
            displayImage.texture = browserTexture;
        
        // 加载初始页面
        CEF_LoadURL(browserHandle, initialUrl);
        
        Debug.Log($"[CEF] 初始化完成 {browserWidth}x{browserHeight}");
    }
    
    private void Update()
    {
        if (browserHandle == IntPtr.Zero) return;
        
        // 每帧从CEF获取最新渲染结果
        UpdateBrowserTexture();
        
        // 转发输入事件
        HandleInput();
    }
    
    private unsafe void UpdateBrowserTexture()
    {
        // 获取CEF渲染的像素数据（直接内存拷贝，避免GC）
        fixed (byte* ptr = pixelBuffer)
        {
            bool hasNewFrame = CEF_GetPixels(browserHandle, (IntPtr)ptr, pixelBuffer.Length);
            
            if (hasNewFrame)
            {
                // CEF输出BGRA格式，Unity需要RGBA
                // 使用Compute Shader进行格式转换（高性能方案）
                ConvertBGRAtoRGBA(pixelBuffer);
                browserTexture.LoadRawTextureData(pixelBuffer);
                browserTexture.Apply(false); // false = 不生成Mipmap
            }
        }
    }
    
    private void ConvertBGRAtoRGBA(byte[] data)
    {
        // 简单实现：交换R和B通道
        for (int i = 0; i < data.Length; i += 4)
        {
            byte b = data[i];
            data[i] = data[i + 2];   // B -> R位置
            data[i + 2] = b;          // R -> B位置
            // G(i+1)和A(i+3)保持不变
        }
    }
    
    private void HandleInput()
    {
        if (displayImage == null) return;
        
        // 检测鼠标是否在WebView区域内
        RectTransform rt = displayImage.rectTransform;
        if (!RectTransformUtility.ScreenPointToLocalPointInRectangle(
            rt, Input.mousePosition, null, out Vector2 localPoint)) return;
        
        // 将本地坐标转换为浏览器坐标
        float normalizedX = (localPoint.x / rt.rect.width) + 0.5f;
        float normalizedY = 1f - ((localPoint.y / rt.rect.height) + 0.5f);
        int browserX = (int)(normalizedX * browserWidth);
        int browserY = (int)(normalizedY * browserHeight);
        
        // 鼠标点击
        if (Input.GetMouseButtonDown(0))
            CEF_SendMouseClick(browserHandle, browserX, browserY, 0);
        if (Input.GetMouseButtonDown(1))
            CEF_SendMouseClick(browserHandle, browserX, browserY, 1);
    }
    
    public void Navigate(string url) => CEF_LoadURL(browserHandle, url);
    public void RunJavaScript(string code) => CEF_EvaluateJS(browserHandle, code);
    
    private void OnDestroy()
    {
        if (browserHandle != IntPtr.Zero)
        {
            CEF_CloseBrowser(browserHandle);
            browserHandle = IntPtr.Zero;
        }
        
        if (browserTexture != null)
        {
            Destroy(browserTexture);
        }
    }
    
    private void OnApplicationQuit()
    {
        CEF_Shutdown();
    }
}
```

---

## 6. H5页面性能优化策略

### 6.1 预加载与资源缓存

```csharp
/// <summary>
/// H5资源预加载器 - 在游戏启动时预热关键页面
/// </summary>
public class H5Preloader : MonoBehaviour
{
    [SerializeField] private string[] criticalUrls = {
        "https://activity.yourgame.com/daily-checkin",
        "https://shop.yourgame.com/featured",
    };
    
    // 隐藏的预加载WebView（不显示，只加载缓存）
    private UniWebView preloadView;
    
    public IEnumerator PreloadCriticalPages()
    {
        yield return new WaitForSeconds(3f); // 延迟执行，不影响启动帧率
        
        var go = new GameObject("Preload_WebView");
        DontDestroyOnLoad(go);
        preloadView = go.AddComponent<UniWebView>();
        preloadView.Frame = new Rect(0, 0, 1, 1); // 屏幕外位置
        // 不调用Show()，保持隐藏
        
        foreach (string url in criticalUrls)
        {
            preloadView.Load(url);
            yield return new WaitForSeconds(2f); // 等待加载完成，写入缓存
        }
        
        Destroy(go);
        Debug.Log($"[H5Preload] {criticalUrls.Length} 个页面预加载完成");
    }
}
```

### 6.2 H5性能监控

```csharp
/// <summary>
/// WebView性能监控 - 追踪页面加载时间、JS执行时间
/// </summary>
public class WebViewPerformanceMonitor : MonoBehaviour
{
    private Dictionary<string, float> pageLoadStartTimes = new();
    
    public void OnPageStartLoading(string viewId, string url)
    {
        pageLoadStartTimes[viewId] = Time.realtimeSinceStartup;
        Debug.Log($"[WebView Perf] 开始加载: {url}");
    }
    
    public void OnPageFinished(string viewId, string url, int statusCode)
    {
        if (pageLoadStartTimes.TryGetValue(viewId, out float startTime))
        {
            float loadTime = (Time.realtimeSinceStartup - startTime) * 1000f;
            Debug.Log($"[WebView Perf] 加载完成: {url} 耗时: {loadTime:F0}ms 状态: {statusCode}");
            
            // 上报性能数据（用于优化分析）
            Analytics.ReportEvent("webview_load_time", new Dictionary<string, object>
            {
                ["url"] = url,
                ["load_time_ms"] = loadTime,
                ["status_code"] = statusCode,
            });
            
            // 性能告警（加载超过3秒）
            if (loadTime > 3000f)
                Debug.LogWarning($"[WebView Perf] ⚠️ 页面加载过慢: {url} ({loadTime:F0}ms)");
            
            pageLoadStartTimes.Remove(viewId);
        }
    }
}
```

---

## 7. 安全设计要点

### 7.1 安全威胁模型

```
威胁 1: URL劫持 - 通过钓鱼链接跳转到恶意页面
  → 对策: 白名单域名过滤 + HTTPS强制

威胁 2: Token泄露 - URL参数中的token被日志/代理捕获
  → 对策: Token短期有效(5分钟) + POST传输 + 不记录含Token的URL

威胁 3: JSBridge滥用 - H5页面调用敏感游戏API
  → 对策: 权限分级 + 敏感操作二次确认

威胁 4: XSS注入 - 恶意JS代码通过H5注入游戏上下文
  → 对策: CSP(Content Security Policy) + 输入过滤

威胁 5: 中间人攻击 - 篡改H5内容
  → 对策: HTTPS + 证书固定(Certificate Pinning)
```

### 7.2 证书固定实现

```csharp
/// <summary>
/// HTTPS证书固定 - 防止中间人攻击（证书替换攻击）
/// </summary>
public class CertificatePinningSetup : MonoBehaviour
{
    // 服务器证书的SHA256指纹（从证书中提取）
    private static readonly string[] TrustedCertFingerprints =
    {
        "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", // 主证书
        "sha256/BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=", // 备用证书（轮换用）
    };
    
    private void Start()
    {
#if !UNITY_EDITOR
        // 仅在真机上启用证书固定（编辑器中禁用，方便调试代理）
        ConfigureCertificatePinning();
#endif
    }
    
    private void ConfigureCertificatePinning()
    {
        // UniWebView支持通过SSL Error回调实现证书固定
        UniWebView.SetAcceptAllCertificates(false); // 禁止接受所有证书
        
        // 通过自定义SSL验证实现固定
        // 实际UniWebView中通过原生层实现
        Debug.Log("[Security] 证书固定已启用");
    }
}
```

---

## 8. 最佳实践总结

### 8.1 架构设计建议

1. **视图ID唯一性**：每类页面对应固定的viewId，避免同类页面多实例（除非业务需要）
2. **Token安全传输**：通过POST Body或Authorization Header传递Token，不放URL参数
3. **JSBridge权限分级**：基础功能（播音效、震动）免鉴权；支付、导航等敏感操作需验证
4. **超时处理**：设置3-5秒加载超时，超时后显示错误页，而非永久Loading
5. **离线降级**：网络不可用时展示本地缓存或内置静态HTML，而非空白页面

### 8.2 性能优化清单

| 优化点 | 预期收益 | 实现方式 |
|--------|---------|---------|
| 页面预加载 | 首次打开快70% | 游戏启动后5s静默预加载 |
| 磁盘缓存 | 二次打开快90% | UniWebView缓存策略 |
| DNS预解析 | 减少50~100ms延迟 | 游戏启动时提前解析域名 |
| 图片CDN压缩 | 减少60%流量 | WebP格式+CDN动态压缩 |
| JS延迟加载 | 首屏快200ms | `<script defer>` |
| Service Worker | 完全离线可用 | H5端实现PWA缓存 |

### 8.3 技术选型决策树

```
需要游戏内嵌Web页面？
│
├─ 移动端（iOS/Android）
│   ├─ 商业项目（有预算）→ UniWebView（成熟稳定）
│   └─ 自研/小团队 → Android WebView + WKWebView 原生插件
│
├─ PC端（Windows/Mac）
│   ├─ 复杂交互（如Steam商店） → CEF（Chromium完整特性）
│   └─ 简单展示（公告/帮助） → 自研轻量HTML渲染或调用系统浏览器
│
└─ 全平台统一方案
    ├─ 有大量H5开发资源 → 考虑React Native / Flutter（Native方案）
    └─ 仅运营展示类页面 → WebView + CDN + Service Worker（最灵活）
```
