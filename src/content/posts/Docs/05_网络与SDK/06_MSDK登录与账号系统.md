# 06_MSDK登录与账号系统

> MSDK是腾讯游戏的统一登录SDK，支持微信、QQ、游客等多种登录方式。本文讲解如何接入MSDK并实现完整的账号功能。

---

## 1. 系统概述

**MSDK（Mobile SDK）**是腾讯游戏对外提供的移动端统一接入SDK，整合了：

- **登录体系**：微信（WXG）、QQ、游客、手机号等多种登录渠道
- **账号管理**：Token刷新、账号绑定/解绑、切换账号
- **防沉迷**：实名认证、青少年模式
- **用户信息**：头像、昵称、性别等基本信息

本项目通过GCloud SDK中集成的MSDK模块（`SDK/GCloudSDK/Scripts/MSDKCore/`）来实现玩家的登录和账号管理功能。

---

## 2. 架构设计

### 2.1 MSDK模块结构

```
GCloud.MSDK 命名空间
├── MSDK.cs            → 核心入口，初始化和全局事件
├── MSDKLogin.cs       → 登录/登出/账号绑定API
├── MSDKLoginRet.cs    → 登录结果数据结构（含Token、OpenID等）
├── MSDKBaseRet.cs     → 所有回调的基类返回值
├── MSDKUser.cs        → 用户信息查询
├── MSDKNotice.cs      → 公告系统
└── MSDKMessageCenter.cs → 消息中心（分发各类回调）
```

### 2.2 登录流程

```
游戏启动
  │
  ▼
MSDK.Init()  ← 初始化消息中心、日志等
  │
  ▼
MSDKLogin.GetLoginRet()  ← 检查本地是否有有效Token
  │
  ├─ Token有效 → 直接进入游戏
  └─ Token无效/不存在
      │
      ▼
  MSDKLogin.AutoLogin()  ← 尝试静默自动登录
      │
      ├─ 成功 → 进入游戏
      └─ 失败
          │
          ▼
      显示登录界面
          │
          ├─ 用户点击"微信登录"→ MSDKLogin.Login("WXG")
          └─ 用户点击"QQ登录" → MSDKLogin.Login("QQ")
              │
              ▼
          LoginRetEvent 回调
              │
              ├─ 成功 → 保存Token，进入游戏
              └─ 失败 → 显示错误信息
```

### 2.3 MSDKLoginRet 数据结构

登录成功后，`MSDKLoginRet`包含了后续所有操作需要的信息：

```
MSDKLoginRet
├── openID         → 玩家唯一标识（不同渠道不同）
├── token          → 登录凭证（向游戏服务器验证身份）
├── tokenExpire    → Token过期时间（Unix时间戳）
├── firstLogin     → 是否首次登录（-1未知, 0否, 1是）
├── userName       → 玩家昵称
├── gender         → 性别（0未定义, 1男, 2女）
├── pictureUrl     → 头像URL
├── pf             → 平台标识（用于支付）
├── pfKey          → 平台密钥（用于支付验证）
├── realNameAuth   → 是否需要实名认证
├── channelID      → 登录渠道ID
└── channel        → 登录渠道名（"WXG"/"QQ"等）
```

---

## 3. 核心代码展示

### 3.1 MSDK初始化（来自`MSDK.cs`和`PatchManager.cs`）

```csharp
// PatchManager.Start() 中
void Start()
{
    // ... GCloud初始化 ...
    
    // 初始化MSDK（必须在GCloud初始化之后）
    GCloud.MSDK.MSDK.isDebug = true;  // 开发阶段开启调试日志
    GCloud.MSDK.MSDK.Init();
}

// MSDK.cs 的 Init() 实现
public static void Init()
{
    if (initialized) return;
    initialized = true;

    // 设置日志级别
    if (isDebug)
        MSDKLog.SetLevel(MSDKLog.Level.Log);
    else
        MSDKLog.SetLevel(MSDKLog.Level.Error);
    
    // 初始化消息中心（负责分发Native回调到C#事件）
    MSDKMessageCenter.Instance.Init();
    
    // 非Editor环境下初始化崩溃上报
#if !UNITY_EDITOR && !UNITY_STANDALONE_WIN
    MSDKCrash.InitCrash();
#endif
    
    MSDKLog.Log("MSDK initialized!");
}
```

### 3.2 登录API（来自`MSDKLogin.cs`）

```csharp
// 发起登录请求
public static void Login(string channel, 
                         string permissions = "", 
                         string subChannel = "", 
                         string extraJson = "")
{
    try
    {
        MSDKLog.Log($"Login channel={channel} permissions={permissions}");
        
#if GCLOUD_MSDK_WINDOWS || GCLOUD_MSDK_MAC
        loginAdapter(channel, permissions, subChannel, extraJson);
#elif UNITY_EDITOR || UNITY_STANDALONE_WIN
        // 编辑器下使用模拟登录
        UnityEditorLogin(MSDKMethodNameID.MSDK_LOGIN_LOGIN, channel, subChannel);
#else
        // 真机调用Native层
        loginAdapter(channel, permissions, subChannel, extraJson);
#endif
    }
    catch (Exception ex)
    {
        MSDKLog.LogError($"Login error: {ex.Message}\n{ex.StackTrace}");
    }
}

// 登录结果回调事件
public static event OnMSDKRetEventHandler<MSDKLoginRet> LoginRetEvent;

// 登出
public static void Logout(string channel = "", string extraJson = "")
{
    try
    {
#if UNITY_EDITOR || UNITY_STANDALONE_WIN
        UnityEditorLogin(MSDKMethodNameID.MSDK_LOGIN_LOGOUT, channel, "");
#else
        logoutAdapter(channel, extraJson);
#endif
    }
    catch (Exception ex)
    {
        MSDKLog.LogError($"Logout error: {ex.Message}");
    }
}
```

### 3.3 获取本地登录态

```csharp
// 同步获取本地缓存的登录信息（不发网络请求）
public static MSDKLoginRet GetLoginRet()
{
    try
    {
#if UNITY_EDITOR || UNITY_STANDALONE_WIN
        string retJson = UnityEditorData.GetLoginData(
            (int)MSDKMethodNameID.MSDK_LOGIN_GETLOGINRESULT);
#else
        string retJson = getLoginRetAdapter();
#endif
        MSDKLog.Log($"GetLoginRet retJson={retJson}");
        if (!string.IsNullOrEmpty(retJson))
            return new MSDKLoginRet(retJson);
    }
    catch (Exception ex)
    {
        MSDKLog.LogError($"GetLoginRet error: {ex.Message}");
    }
    return null;
}
```

### 3.4 完整的业务登录流程（推荐实现）

```csharp
// 游戏登录管理器示例
public class LoginManager : MonoBehaviour
{
    private void Start()
    {
        // 订阅MSDK登录回调
        MSDKLogin.LoginRetEvent += OnLoginRet;
        MSDKLogin.LoginBaseRetEvent += OnLoginBaseRet; // 登出/唤醒回调

        // 启动时检查登录态
        CheckLoginStatus();
    }

    private void CheckLoginStatus()
    {
        // 1. 先检查本地是否有有效Token
        MSDKLoginRet localRet = MSDKLogin.GetLoginRet();
        
        if (localRet != null && !string.IsNullOrEmpty(localRet.Token))
        {
            // 检查Token是否过期（留30分钟余量）
            long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            if (localRet.TokenExpire - now > 1800)
            {
                Debug.Log($"[Login] Token有效，直接进入游戏，OpenID: {localRet.OpenId}");
                EnterGame(localRet);
                return;
            }
        }
        
        // 2. 尝试自动登录（刷新Token）
        MSDKLogin.AutoLogin("", "", "");
        // 等待 LoginRetEvent 回调
    }

    private void OnLoginRet(MSDKLoginRet ret)
    {
        if (ret.RetCode == 0) // 0表示成功
        {
            Debug.Log($"[Login] 登录成功! 渠道:{ret.Channel} OpenID:{ret.OpenId}");
            Debug.Log($"[Login] 首次登录:{ret.FirstLogin == 1} 实名认证:{ret.RealNameAuth}");
            
            // 如果需要实名认证（未成年人保护）
            if (ret.RealNameAuth)
            {
                ShowRealNameAuthUI();
                return;
            }
            
            EnterGame(ret);
        }
        else
        {
            Debug.LogWarning($"[Login] 登录失败: Code={ret.RetCode} Msg={ret.RetMsg}");
            
            // 自动登录失败，显示登录界面
            ShowLoginUI();
        }
    }

    private void OnLoginBaseRet(MSDKBaseRet ret)
    {
        // 处理登出、被踢下线等事件
        if (ret.MethodNameID == (int)MSDKMethodNameID.MSDK_LOGIN_LOGOUT)
        {
            Debug.Log("[Login] 玩家已登出");
            ShowLoginUI();
        }
    }

    // 微信登录按钮点击
    public void OnClickWeChatLogin()
    {
        // 申请基本权限：用户信息 + 好友列表
        MSDKLogin.Login("WXG", "user_info,inapp_friends", "", "");
    }

    // QQ登录按钮点击
    public void OnClickQQLogin()
    {
        MSDKLogin.Login("QQ", "user_info", "", "");
    }

    private void EnterGame(MSDKLoginRet loginRet)
    {
        // 将Token发给游戏服务器验证
        GameServer.VerifyLogin(loginRet.OpenId, loginRet.Token, loginRet.Channel,
            (success) => {
                if (success)
                    SceneManager.LoadScene("LobbyScene");
                else
                    ShowLoginUI();
            });
    }

    void OnDestroy()
    {
        MSDKLogin.LoginRetEvent -= OnLoginRet;
        MSDKLogin.LoginBaseRetEvent -= OnLoginBaseRet;
    }
}
```

### 3.5 账号绑定功能

```csharp
// 将当前账号绑定到另一个渠道（如游客账号绑定到微信）
public void BindToWeChat()
{
    MSDKLogin.Bind("WXG", "user_info", "", "");
    MSDKLogin.LoginRetEvent += OnBindRet;
}

private void OnBindRet(MSDKLoginRet ret)
{
    if (ret.RetCode == 0)
    {
        Debug.Log("[Login] 账号绑定成功！");
        // 保存绑定信息
    }
    else if (ret.RetCode == 2) // 该渠道账号已被其他用户绑定
    {
        ShowDialog("该微信账号已绑定其他游戏账号，请使用其他账号");
    }
    MSDKLogin.LoginRetEvent -= OnBindRet;
}

// 切换账号
public void SwitchAccount()
{
    // switchUser可以在多个登录账号之间切换
    MSDKLogin.SwitchUser(false); // false=切换到非启动账号
}
```

### 3.6 Connect关联功能（快手等渠道）

```csharp
// 关联到第三方渠道（如快手），用于内容创作者认证
public void ConnectToKwai()
{
    MSDKLogin.Connect("Kwai", "user_info", "", "");
    MSDKLogin.ConnectRetEvent += OnConnectRet;
}

// 获取关联状态
MSDKLoginRet connectRet = MSDKLogin.GetConnectRet();
if (connectRet != null)
{
    Debug.Log($"[Login] 已关联渠道: {connectRet.Channel} ID: {connectRet.OpenId}");
}
```

---

## 4. 设计亮点

### 4.1 Token本地缓存+有效期检测

MSDK会将登录Token持久化存储在设备上。游戏每次启动时先检查本地Token是否有效（`GetLoginRet()`），有效则直接跳过登录界面，提升玩家体验。

建议检查时留30分钟余量（`TokenExpire - now > 1800`），避免刚进游戏Token就过期。

### 4.2 多渠道统一接口

无论是微信、QQ还是其他渠道，都通过`MSDKLogin.Login(channel)`统一调用，回调统一是`LoginRetEvent`，大大降低了多渠道接入的复杂度。

### 4.3 编辑器模拟登录

```csharp
#elif UNITY_EDITOR || UNITY_STANDALONE_WIN
    UnityEditorLogin(MSDKMethodNameID.MSDK_LOGIN_LOGIN, channel, subChannel);
```

在编辑器环境下，MSDK自动切换到模拟登录模式，不需要真实的微信/QQ授权，开发调试非常方便。

### 4.4 实名认证流程内置

通过`MSDKLoginRet.RealNameAuth`字段，游戏可以得知当前玩家是否需要实名认证（未成年人保护），并在游戏层面拦截登录，引导完成认证。

### 4.5 pfKey用于支付安全

`pf`和`pfKey`是MSDK为支付场景提供的凭证，游戏在发起支付时需要携带这两个参数，后端用于验证支付来源的合法性，防止伪造支付请求。

---

## 5. 常见问题与最佳实践

### Q1：Token过期了怎么办？

当游戏服务器返回Token过期错误时：
1. 调用`MSDKLogin.AutoLogin()`尝试静默刷新Token
2. 如果自动刷新失败，跳回登录界面重新登录
3. 不要直接退出游戏，给玩家续Token的机会

### Q2：iOS上微信登录为什么有时失败？

1. 检查是否正确配置了Universal Link（在Xcode中配置）
2. 检查`Info.plist`中是否添加了微信的URL Scheme（`wx<AppID>`）
3. 调用`MSDKLogin.CheckUniversalLink("WXG")`进行自检诊断

### Q3：如何处理"账号被顶号"（被踢下线）的情况？

被踢下线时会触发`LoginBaseRetEvent`，`MethodNameID`对应强制登出事件：

```csharp
MSDKLogin.LoginBaseRetEvent += (ret) => {
    if (ret.MethodNameID == (int)MSDKMethodNameID.MSDK_LOGIN_KICKOUT)
    {
        ShowDialog("您的账号在另一台设备登录，已被强制下线");
        BackToLoginScene();
    }
};
```

### Q4：openID在不同渠道是相同的吗？

不同渠道的openID完全不同（微信的openID和QQ的openID是两套独立体系）。游戏服务器应该用`channel + openID`的组合来唯一标识一个玩家，而不是单独用openID。

### Q5：防沉迷系统如何接入？

当`MSDKLoginRet.RealNameAuth == true`时，说明该账号需要实名认证（通常是未成年人账号）。游戏层需要：
1. 拦截登录，不进入游戏
2. 打开实名认证页面（调用MSDK提供的实名认证UI）
3. 认证完成后重新检查登录态

---

## 6. 总结

MSDK通过统一的`Login(channel)`接口屏蔽了微信、QQ等不同登录渠道的实现细节，通过`LoginRetEvent`统一回调，提供了Token管理、账号绑定、防沉迷等完整的账号体系。结合本地Token缓存和自动登录机制，能给玩家提供流畅的无感登录体验。

对于新入职同学，最重要的是记住：**先订阅`LoginRetEvent`，再调用`Login()`**，顺序不能搞反，否则登录结果来了却没人处理。
