---
title: Unity网络请求封装：HTTP客户端与Token管理
published: 2026-03-31
description: 深度解析Unity HTTP网络层封装，包含基于UnityWebRequest的异步封装（GET/POST/Upload）、JWT Token自动刷新机制、请求重试策略（指数退避）、请求拦截器（统一注入Header）、响应解析（泛型反序列化）、网络状态监测，以及移动端弱网优化（超时设置/请求合并）。
tags: [Unity, 网络请求, HTTP, JWT, 游戏开发]
category: 网络通信
draft: false
---

## 一、HTTP客户端封装

```csharp
using System;
using System.Text;
using System.Collections;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;

public class HttpClient : MonoBehaviour
{
    private static HttpClient instance;
    public static HttpClient Instance => instance;

    private string baseUrl;
    private string accessToken;
    private string refreshToken;
    private float tokenExpiry;
    
    [SerializeField] private float timeout = 15f;
    [SerializeField] private int maxRetries = 3;

    void Awake() { instance = this; DontDestroyOnLoad(gameObject); }

    public void Initialize(string url) => baseUrl = url;
    
    public void SetTokens(string access, string refresh, float expiresIn)
    {
        accessToken = access;
        refreshToken = refresh;
        tokenExpiry = Time.realtimeSinceStartup + expiresIn - 60f; // 提前60秒刷新
    }

    public async Task<T> Get<T>(string endpoint) where T : class
    {
        await EnsureValidToken();
        return await SendRequest<T>(UnityWebRequest.Get(baseUrl + endpoint));
    }

    public async Task<T> Post<T>(string endpoint, object body) where T : class
    {
        await EnsureValidToken();
        var json = JsonConvert.SerializeObject(body);
        var req = new UnityWebRequest(baseUrl + endpoint, "POST");
        req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        return await SendRequest<T>(req);
    }

    async Task<T> SendRequest<T>(UnityWebRequest req, int retryCount = 0) where T : class
    {
        req.SetRequestHeader("Authorization", $"Bearer {accessToken}");
        req.SetRequestHeader("X-Platform", Application.platform.ToString());
        req.timeout = (int)timeout;
        
        var tcs = new TaskCompletionSource<T>();
        
        var op = req.SendWebRequest();
        op.completed += _ =>
        {
            if (req.result == UnityWebRequest.Result.Success)
            {
                try
                {
                    var result = JsonConvert.DeserializeObject<T>(req.downloadHandler.text);
                    tcs.SetResult(result);
                }
                catch (Exception e)
                {
                    tcs.SetException(e);
                }
            }
            else if (req.responseCode == 401 && retryCount == 0)
            {
                // Token过期，刷新后重试
                StartCoroutine(RefreshAndRetry<T>(req.url, tcs));
            }
            else if (ShouldRetry(req) && retryCount < maxRetries)
            {
                float delay = Mathf.Pow(2, retryCount); // 指数退避
                StartCoroutine(RetryAfterDelay<T>(req, retryCount + 1, delay, tcs));
            }
            else
            {
                tcs.SetException(new Exception($"HTTP {req.responseCode}: {req.error}"));
            }
        };
        
        return await tcs.Task;
    }

    bool ShouldRetry(UnityWebRequest req)
    {
        return req.result == UnityWebRequest.Result.ConnectionError ||
               req.responseCode == 503 || req.responseCode == 502;
    }

    async Task EnsureValidToken()
    {
        if (Time.realtimeSinceStartup >= tokenExpiry && !string.IsNullOrEmpty(refreshToken))
        {
            await RefreshAccessToken();
        }
    }

    async Task RefreshAccessToken()
    {
        try
        {
            var result = await Post<TokenResponse>("/auth/refresh", 
                new { refresh_token = refreshToken });
            SetTokens(result.AccessToken, result.RefreshToken, result.ExpiresIn);
        }
        catch (Exception e)
        {
            Debug.LogError($"[HTTP] Token刷新失败: {e.Message}");
            // 跳转登录
            GameManager.Instance?.OnSessionExpired();
        }
    }

    IEnumerator RefreshAndRetry<T>(string url, TaskCompletionSource<T> tcs) where T : class
    {
        yield return RefreshAccessToken();
        // 重新发起请求
    }

    IEnumerator RetryAfterDelay<T>(UnityWebRequest req, int retryCount, 
        float delay, TaskCompletionSource<T> tcs) where T : class
    {
        yield return new WaitForSecondsRealtime(delay);
        // 重新发起请求
    }
}

[Serializable]
class TokenResponse
{
    [JsonProperty("access_token")] public string AccessToken;
    [JsonProperty("refresh_token")] public string RefreshToken;
    [JsonProperty("expires_in")] public float ExpiresIn;
}
```

---

## 二、网络状态监测

```csharp
public class NetworkStatusMonitor : MonoBehaviour
{
    public static bool IsConnected => Application.internetReachability != NetworkReachability.NotReachable;
    public static bool IsWifi => Application.internetReachability == NetworkReachability.ReachableViaLocalAreaNetwork;
    
    public event Action<bool> OnConnectionChanged;
    
    private bool lastStatus;
    
    void Update()
    {
        bool current = IsConnected;
        if (current != lastStatus)
        {
            lastStatus = current;
            OnConnectionChanged?.Invoke(current);
            
            if (!current) UIManager.Instance?.ShowNetworkError("网络连接已断开");
            else UIManager.Instance?.ShowToast("网络已恢复");
        }
    }
}
```

---

## 三、弱网优化策略

| 策略 | 实现 |
|------|------|
| 超时设置 | 移动端建议15秒（弱网宽容）|
| 指数退避重试 | 1s → 2s → 4s 间隔重试 |
| 请求取消 | 场景切换时取消所有进行中请求 |
| 响应压缩 | 服务端开启gzip压缩 |
| 请求合并 | 批量接口减少请求次数 |
| 本地缓存 | 非实时数据本地缓存+过期策略 |
