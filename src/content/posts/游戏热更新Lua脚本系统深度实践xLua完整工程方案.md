---
title: 游戏热更新Lua脚本系统深度实践：xLua完整工程方案
published: 2026-05-01
description: 深度解析 xLua 热更新框架的完整工程实践，涵盖 xLua 架构原理、C#/Lua 双向调用、Hotfix 热补丁机制、LuaBehaviour 设计模式、资源热更新联动、Lua 协程与 UniTask 桥接、性能优化与内存管理，附完整项目级代码示例与最佳实践总结。
tags: [Unity, xLua, 热更新, Lua, 游戏架构, 脚本系统]
category: 热更新与脚本
draft: false
---

# 游戏热更新Lua脚本系统深度实践：xLua完整工程方案

## 前言

热更新是移动端游戏的核心需求。App Store / Google Play 的审核周期往往需要 1~2 周，而游戏运营过程中需要频繁修复 Bug、上线活动、调整数值——这就要求游戏客户端能够绕过应用商店，**在运行时动态更新代码逻辑**。

目前主流的 Unity 热更新方案：

| 方案 | 原理 | 优势 | 局限 |
|------|------|------|------|
| **xLua** | Lua 脚本解释执行 | 成熟稳定，性能好，腾讯维护 | 需要学习 Lua，调试不便 |
| **HybridCLR（ILRuntime2）** | IL 解释执行 | 完整 C# 支持，无需重写 | 性能略低，内存占用高 |
| **Lua（tolua/ulua）** | Lua 脚本解释执行 | 社区成熟 | 封装较旧，功能略弱 |

本文深度聚焦 **xLua**，这是腾讯开源、经过大量商业项目验证的方案。

---

## xLua 架构原理

```
┌─────────────────────────────────────┐
│           Unity C# 层               │
│  LuaEnv → LuaTable → LuaFunction   │
├─────────────────────────────────────┤
│         xLua 绑定层（生成代码）       │
│  GenCode → Wrap 函数 → 类型映射      │
├─────────────────────────────────────┤
│           Lua 虚拟机（LuaJIT）       │
│  .lua 脚本文件 → 字节码 → 执行       │
└─────────────────────────────────────┘
```

xLua 的核心机制：
1. **代码生成（GenCode）**：通过反射扫描标记了 `[LuaCallCSharp]` 的类型，生成高效的 Wrap 函数，避免反射开销
2. **LuaEnv**：Lua 虚拟机封装，全局唯一，负责 Lua 脚本加载与执行
3. **Hotfix**：通过 IL 注入将 C# 方法替换为 Lua 函数调用，实现对 C# 代码的热补丁

---

## 环境搭建与项目结构

### 安装 xLua

```
1. 从 https://github.com/Tencent/xLua/releases 下载最新 Release
2. 解压后将 Assets/XLua 目录复制到项目中
3. 菜单 XLua → Generate Code 生成绑定代码
```

### 推荐项目目录结构

```
Assets/
├── XLua/                   # xLua 核心库（不修改）
├── Scripts/
│   ├── Framework/
│   │   ├── LuaManager.cs   # Lua 虚拟机管理器
│   │   ├── LuaBehaviour.cs # Lua 驱动的 MonoBehaviour 基类
│   │   └── LuaHotfix.cs    # Hotfix 管理
│   └── Game/
│       └── ...
├── Lua/                    # Lua 脚本（打包到 StreamingAssets 或 Addressables）
│   ├── Common/
│   │   ├── class.lua       # 面向对象封装
│   │   ├── event.lua       # 事件系统
│   │   └── timer.lua       # 定时器
│   ├── UI/
│   │   └── MainUI.lua
│   └── Game/
│       └── GameLogic.lua
└── HotfixScripts/          # Hotfix 专用 C# 脚本（标记 [Hotfix]）
```

---

## LuaManager：核心虚拟机管理

```csharp
using XLua;
using System;
using UnityEngine;

/// <summary>
/// Lua 虚拟机全局管理器
/// 负责 LuaEnv 生命周期、脚本加载、全局 API 注入
/// </summary>
public class LuaManager : MonoBehaviour
{
    private static LuaManager _instance;
    public static LuaManager Instance => _instance;

    private LuaEnv _luaEnv;
    private float _gcTimer;
    private const float GcInterval = 1f; // 每秒执行一次 Lua GC

    // 全局 Lua 表，各模块通过此表获取 API
    public LuaTable GlobalTable => _luaEnv?.Global;

    private void Awake()
    {
        if (_instance != null)
        {
            Destroy(gameObject);
            return;
        }
        _instance = this;
        DontDestroyOnLoad(gameObject);
        InitLuaEnv();
    }

    private void InitLuaEnv()
    {
        _luaEnv = new LuaEnv();

        // 注册自定义 Loader，支持从 Addressables / StreamingAssets 加载 Lua 文件
        _luaEnv.AddLoader(CustomLuaLoader);

        // 注入 C# 全局 API 到 Lua 环境
        InjectGlobalAPIs();

        // 加载启动入口
        _luaEnv.DoString("require('Main')");

        Debug.Log("[LuaManager] Lua 环境初始化完成");
    }

    private byte[] CustomLuaLoader(ref string filePath)
    {
        // 将 Lua require 路径转换为资源路径
        // 例：require('UI.MainUI') → Assets/Lua/UI/MainUI.lua.bytes
        string normalizedPath = filePath.Replace('.', '/');
        
        // 优先从热更新目录加载（已下载的更新包）
        string hotfixPath = System.IO.Path.Combine(
            Application.persistentDataPath, "HotfixLua", normalizedPath + ".lua");
        if (System.IO.File.Exists(hotfixPath))
        {
            return System.IO.File.ReadAllBytes(hotfixPath);
        }

        // 其次从 StreamingAssets 加载（首包内置）
        var asset = Resources.Load<TextAsset>($"Lua/{normalizedPath}");
        if (asset != null) return asset.bytes;

        Debug.LogWarning($"[LuaManager] Lua 文件未找到: {filePath}");
        return null;
    }

    private void InjectGlobalAPIs()
    {
        // 将常用 C# 对象注入到 Lua 全局命名空间
        var global = _luaEnv.Global;

        // 注入 CS 命名空间（访问 C# 类型）
        // Lua 中可直接用：CS.UnityEngine.Debug.Log("hello")
        // xLua 默认已支持 CS 命名空间

        // 注入自定义辅助函数
        global.Set<string, Action<string>>("CSharpLog",
            msg => Debug.Log($"[Lua] {msg}"));
        global.Set<string, Func<string, string>>("GetConfig",
            key => GameConfig.Get(key));
    }

    private void Update()
    {
        // 定期触发 Lua GC，避免 Lua 堆积大量垃圾
        _gcTimer += Time.deltaTime;
        if (_gcTimer >= GcInterval)
        {
            _luaEnv.Tick();
            _gcTimer = 0f;
        }
    }

    /// <summary>
    /// 执行 Lua 代码字符串（调试用）
    /// </summary>
    public object[] DoString(string code, string chunkName = "chunk")
    {
        try
        {
            return _luaEnv.DoString(code, chunkName);
        }
        catch (Exception e)
        {
            Debug.LogError($"[LuaManager] DoString 错误: {e.Message}");
            return null;
        }
    }

    /// <summary>
    /// 加载并执行 Lua 模块，返回模块表
    /// </summary>
    public LuaTable Require(string moduleName)
    {
        _luaEnv.DoString($"require('{moduleName}')");
        return _luaEnv.Global.Get<LuaTable>(moduleName.Split('.')[^1]);
    }

    /// <summary>
    /// 获取 Lua 全局函数
    /// </summary>
    public T GetGlobalFunction<T>(string funcName) where T : class
    {
        return _luaEnv.Global.Get<T>(funcName);
    }

    private void OnDestroy()
    {
        _luaEnv?.Dispose();
        _luaEnv = null;
    }
}
```

---

## C# 调用 Lua

### 调用 Lua 函数

```csharp
public class LuaCallDemo : MonoBehaviour
{
    private LuaEnv _luaEnv;

    private void Start()
    {
        _luaEnv = LuaManager.Instance.LuaEnv;

        // 方式1：通过委托接口调用（高性能，推荐）
        // 先定义接口
        var calculator = _luaEnv.Global.Get<ILuaCalculator>("Calculator");
        int result = calculator.Add(10, 20);
        Debug.Log($"Lua计算结果: {result}"); // 输出: 30

        // 方式2：通过 LuaFunction 对象调用（灵活但略慢）
        var greet = _luaEnv.Global.Get<LuaFunction>("Greet");
        var returns = greet.Call("Unity");
        Debug.Log(returns[0]); // Hello, Unity!
        greet.Dispose();

        // 方式3：通过 Action/Func 委托（推荐，类型安全）
        var addFunc = _luaEnv.Global.Get<Func<int, int, int>>("Add");
        int sum = addFunc(5, 3); // 8
    }

    // 定义与 Lua 交互的接口
    [CSharpCallLua]
    public interface ILuaCalculator
    {
        int Add(int a, int b);
        float Mul(float a, float b);
        string Format(int value, string template);
    }
}
```

对应的 Lua 代码 (`Main.lua`)：

```lua
-- Main.lua
Calculator = {
    Add = function(a, b)
        return a + b
    end,
    
    Mul = function(a, b)
        return a * b
    end,
    
    Format = function(value, template)
        return string.format(template, value)
    end
}

function Greet(name)
    return "Hello, " .. name .. "!"
end

function Add(a, b)
    return a + b
end
```

### 获取/设置 Lua Table 中的字段

```csharp
// 获取 Lua 表
LuaTable configTable = _luaEnv.Global.Get<LuaTable>("GameConfig");

// 读取字段
int level = configTable.Get<int>("maxLevel");           // 整数
string name = configTable.Get<string>("gameName");       // 字符串
float rate = configTable.Get<float>("dropRate");         // 浮点数

// 写入字段
configTable.Set("maxLevel", 100);
configTable.Set("gameName", "MyGame");

// 嵌套表
LuaTable nestedTable = configTable.Get<LuaTable>("settings");

// 映射到 C# 类（需要 [CSharpCallLua]）
[CSharpCallLua]
public class GameConfigData
{
    public int maxLevel;
    public string gameName;
    public float dropRate;
}

var config = configTable.Cast<GameConfigData>();
```

---

## Lua 调用 C#

### 标记可被 Lua 调用的 C# 类

```csharp
// 方式1：[LuaCallCSharp] 标记（生成静态绑定代码，高性能）
[LuaCallCSharp]
public class PlayerManager : MonoBehaviour
{
    private static PlayerManager _instance;
    public static PlayerManager Instance => _instance;

    public int Level { get; set; } = 1;
    public float HP { get; set; } = 100f;

    public void AddExp(int amount)
    {
        Debug.Log($"获得经验: {amount}");
    }

    public static PlayerManager GetInstance() => _instance;
}

// 方式2：通过 LuaCallCSharp 配置列表批量指定
// 在 Editor 脚本中配置（推荐用于第三方库）
public static class LuaCallConfig
{
    [LuaCallCSharp]
    public static List<Type> LuaCallCSharpList = new List<Type>()
    {
        typeof(GameObject),
        typeof(Transform),
        typeof(Vector3),
        typeof(Quaternion),
        typeof(PlayerManager),
        typeof(UIManager),
    };
}
```

Lua 调用 C# 示例：

```lua
-- 通过 CS 命名空间访问 C# 类型
local PlayerManager = CS.PlayerManager

-- 调用静态方法
local player = PlayerManager.GetInstance()

-- 访问属性
print("当前等级:", player.Level)
print("当前HP:", player.HP)

-- 调用实例方法
player:AddExp(100)

-- 修改属性
player.Level = 5

-- 实例化 GameObject
local go = CS.UnityEngine.GameObject("MyLuaObject")
go.transform.position = CS.UnityEngine.Vector3(1, 2, 3)

-- 使用 UnityEngine.Debug
CS.UnityEngine.Debug.Log("从Lua输出日志")
```

---

## LuaBehaviour：Lua 驱动的 MonoBehaviour

这是将 Lua 脚本与 Unity 组件系统整合的关键设计：

```csharp
/// <summary>
/// LuaBehaviour：将 Unity 生命周期方法桥接到 Lua 脚本
/// 所有需要 Lua 逻辑的 GameObject 均挂载此组件
/// </summary>
public class LuaBehaviour : MonoBehaviour
{
    [SerializeField] private string _luaScriptPath; // 例: "UI.MainUI"

    private LuaTable _scriptEnv;    // 此组件的 Lua 脚本表
    private LuaUpdater _luaUpdate;  // Lua Update 函数（委托，避免每帧 Get）
    private LuaUpdater _luaFixedUpdate;
    private LuaAction _luaOnDestroy;

    [CSharpCallLua]
    private delegate void LuaUpdater(float deltaTime);
    [CSharpCallLua]
    private delegate void LuaAction();

    private void Awake()
    {
        _scriptEnv = LuaManager.Instance.LuaEnv.NewTable();

        // 为每个 LuaBehaviour 创建独立的 Lua 执行环境，避免全局污染
        // 通过元表继承 _G（访问全局变量）
        LuaTable meta = LuaManager.Instance.LuaEnv.NewTable();
        meta.Set("__index", LuaManager.Instance.LuaEnv.Global);
        _scriptEnv.SetMetaTable(meta);
        meta.Dispose();

        // 注入 self（C# 端的 LuaBehaviour 引用）
        _scriptEnv.Set("self", this);
        _scriptEnv.Set("gameObject", gameObject);
        _scriptEnv.Set("transform", transform);

        // 加载并执行 Lua 脚本
        LuaManager.Instance.LuaEnv.DoString(
            $"require('{_luaScriptPath}')", _luaScriptPath, _scriptEnv);

        // 缓存生命周期函数
        _scriptEnv.Get("Update", out _luaUpdate);
        _scriptEnv.Get("FixedUpdate", out _luaFixedUpdate);
        _scriptEnv.Get("OnDestroy", out _luaOnDestroy);

        // 调用 Lua Awake
        LuaAction awake;
        _scriptEnv.Get("Awake", out awake);
        awake?.Invoke();
        awake = null;
    }

    private void Start()
    {
        LuaAction start;
        _scriptEnv.Get("Start", out start);
        start?.Invoke();
        start = null;
    }

    private void Update()
    {
        _luaUpdate?.Invoke(Time.deltaTime);
    }

    private void FixedUpdate()
    {
        _luaFixedUpdate?.Invoke(Time.fixedDeltaTime);
    }

    private void OnDestroy()
    {
        _luaOnDestroy?.Invoke();
        
        // 释放 Lua 委托引用（防内存泄漏！）
        _luaUpdate = null;
        _luaFixedUpdate = null;
        _luaOnDestroy = null;
        
        _scriptEnv?.Dispose();
        _scriptEnv = null;
    }

    /// <summary>
    /// 外部调用 Lua 脚本中的指定函数
    /// </summary>
    public void CallLuaFunction(string funcName, params object[] args)
    {
        _scriptEnv.Get<string, LuaFunction>(funcName)?.Call(args);
    }
}
```

对应的 Lua 脚本示例 (`UI/MainUI.lua`)：

```lua
-- UI/MainUI.lua
-- self 由 LuaBehaviour 注入，指向 C# 端的 LuaBehaviour 实例

local _timer = 0
local _clickCount = 0

function Awake()
    print("[MainUI] Awake, gameObject:", self.gameObject.name)
    
    -- 通过 C# 方法查找 UI 组件
    local btn = self.gameObject.transform:Find("BtnStart")
    if btn then
        -- 添加点击监听（需要 C# 端封装事件绑定）
        UIHelper.AddClickListener(btn.gameObject, OnBtnStartClick)
    end
end

function Start()
    print("[MainUI] Start")
    RefreshUI()
end

function Update(deltaTime)
    _timer = _timer + deltaTime
    if _timer >= 1.0 then
        _timer = 0
        -- 每秒更新一次
        OnTimerTick()
    end
end

function OnBtnStartClick()
    _clickCount = _clickCount + 1
    print("[MainUI] 按钮点击次数:", _clickCount)
    
    -- 调用 C# 接口
    CS.GameManager.Instance:StartGame()
end

function OnTimerTick()
    -- 更新 UI 上的时间显示
end

function RefreshUI()
    -- 刷新界面
end

function OnDestroy()
    print("[MainUI] OnDestroy")
    -- 清理资源
end
```

---

## xLua Hotfix：C# 代码热补丁

Hotfix 是 xLua 最强大的特性之一，允许在不重启 App 的情况下**用 Lua 替换 C# 方法实现**：

### 准备步骤

```csharp
// 1. 标记需要热修复的 C# 类（必须在打包前确定）
[Hotfix]
public class BattleSystem : MonoBehaviour
{
    public int CalculateDamage(int attack, int defense)
    {
        // 原始实现（可能有 Bug）
        return attack - defense;
    }

    public void OnPlayerDead()
    {
        // 可能需要热修复的逻辑
        Debug.Log("玩家死亡");
    }
}

// 2. 菜单: XLua → Hotfix Inject In Editor（注入 IL 代码）
// 3. 打包时：Hotfix Inject（构建后处理器自动注入）
```

### Lua 端实施热修复

```lua
-- hotfix/BattleSystemFix.lua
-- 用 Lua 覆盖 C# 方法实现

-- 修复 CalculateDamage 方法（Bug: 未考虑最小伤害值）
xlua.hotfix(CS.BattleSystem, 'CalculateDamage', function(self, attack, defense)
    local damage = attack - defense
    -- 修复：最低造成1点伤害
    return math.max(1, damage)
end)

-- 修复 OnPlayerDead 方法
xlua.hotfix(CS.BattleSystem, 'OnPlayerDead', function(self)
    print("[Hotfix] 玩家死亡（已修复逻辑）")
    -- 新的死亡处理逻辑
    CS.UIManager.Instance:ShowDeadPanel()
    CS.AudioManager.Instance:PlayDeathSound()
end)

-- 修复静态方法
xlua.hotfix(CS.MathHelper, 'CalcExpToNextLevel', function(level)
    -- 新的经验公式
    return math.floor(100 * math.pow(level, 1.5))
end)

-- 修复属性（getter/setter）
xlua.hotfix(CS.PlayerData, {
    get_MaxHP = function(self)
        -- 修复 MaxHP 计算逻辑
        return self._baseHP + self.Level * 50
    end,
    set_MaxHP = function(self, value)
        self._baseHP = value
    end
})
```

### 加载热修复脚本

```csharp
public class HotfixManager : MonoBehaviour
{
    private const string HotfixManifestUrl = "https://cdn.yourgame.com/hotfix/manifest.json";

    public async UniTask ApplyHotfixes()
    {
        // 1. 下载热修复清单
        var manifest = await DownloadHotfixManifest();
        if (manifest == null) return;

        // 2. 下载需要更新的 Lua 脚本
        foreach (var file in manifest.Files)
        {
            string localPath = Path.Combine(Application.persistentDataPath, "HotfixLua", file.Path);
            if (!File.Exists(localPath) || GetFileMD5(localPath) != file.MD5)
            {
                byte[] data = await DownloadFile(file.Url);
                Directory.CreateDirectory(Path.GetDirectoryName(localPath)!);
                await File.WriteAllBytesAsync(localPath, data);
                Debug.Log($"[HotfixManager] 已更新: {file.Path}");
            }
        }

        // 3. 执行热修复脚本
        foreach (var entry in manifest.HotfixEntries)
        {
            try
            {
                LuaManager.Instance.DoString($"require('{entry}')");
                Debug.Log($"[HotfixManager] 已应用热修复: {entry}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[HotfixManager] 热修复失败 {entry}: {e.Message}");
            }
        }
    }

    private async UniTask<HotfixManifest> DownloadHotfixManifest()
    {
        using var request = UnityWebRequest.Get(HotfixManifestUrl);
        await request.SendWebRequest();
        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogWarning("[HotfixManager] 热修复清单下载失败");
            return null;
        }
        return JsonUtility.FromJson<HotfixManifest>(request.downloadHandler.text);
    }
}

[Serializable]
public class HotfixManifest
{
    public int Version;
    public List<HotfixFile> Files;
    public List<string> HotfixEntries; // 需要 require 的 Lua 入口
}

[Serializable]
public class HotfixFile
{
    public string Path;
    public string Url;
    public string MD5;
    public long Size;
}
```

---

## Lua 面向对象封装

xLua 项目中通常需要一套 Lua OOP 基础库：

```lua
-- Common/class.lua
-- 轻量级 Lua OOP 实现

local function class(base)
    local cls = {}
    cls.__index = cls
    
    if base then
        setmetatable(cls, { __index = base })
    end
    
    cls.new = function(...)
        local instance = setmetatable({}, cls)
        if instance.init then
            instance:init(...)
        end
        return instance
    end
    
    cls.super = base
    return cls
end

_G.class = class

-- 使用示例
local BaseUnit = class()

function BaseUnit:init(name, hp)
    self.name = name
    self.hp = hp
    self.maxHp = hp
end

function BaseUnit:takeDamage(amount)
    self.hp = math.max(0, self.hp - amount)
    print(self.name .. " 受到 " .. amount .. " 点伤害，剩余HP: " .. self.hp)
    if self.hp <= 0 then
        self:onDead()
    end
end

function BaseUnit:onDead()
    print(self.name .. " 已死亡")
end

-- 继承
local HeroUnit = class(BaseUnit)

function HeroUnit:init(name, hp, mana)
    HeroUnit.super.init(self, name, hp)
    self.mana = mana
    self.skills = {}
end

function HeroUnit:castSkill(skillId)
    local skill = self.skills[skillId]
    if skill and self.mana >= skill.cost then
        self.mana = self.mana - skill.cost
        skill:execute(self)
    end
end
```

---

## Lua 协程与 UniTask 桥接

```lua
-- Common/async.lua
-- Lua 协程异步封装

local M = {}

-- 等待秒数（通过 C# coroutine yield）
function M.waitSeconds(seconds)
    -- 通过注入的 C# 等待函数实现
    coroutine.yield(CS.UnityEngine.WaitForSeconds(seconds))
end

-- 等待帧
function M.waitFrame(count)
    count = count or 1
    for i = 1, count do
        coroutine.yield()
    end
end

-- 异步加载资源
function M.loadAsset(path)
    local handle = CS.UnityEngine.AddressableAssets.Addressables.LoadAssetAsync(path)
    while not handle.IsDone do
        coroutine.yield()
    end
    return handle.Result
end

-- 启动 Lua 协程
function M.startCoroutine(func)
    local co = coroutine.create(func)
    local function step(...)
        local ok, yielded = coroutine.resume(co, ...)
        if not ok then
            print("[Async Error]", yielded)
            return
        end
        if coroutine.status(co) ~= 'dead' then
            -- 将控制权交回 C#（通过 LuaCoroutineRunner）
            CS.LuaCoroutineRunner.Instance:RunCoroutineStep(step, yielded)
        end
    end
    step()
end

return M
```

C# 端 `LuaCoroutineRunner`：

```csharp
[LuaCallCSharp]
public class LuaCoroutineRunner : MonoBehaviour
{
    private static LuaCoroutineRunner _instance;
    public static LuaCoroutineRunner Instance => _instance;

    private void Awake()
    {
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }

    [CSharpCallLua]
    public delegate void LuaStepCallback(object yieldedValue);

    public void RunCoroutineStep(LuaStepCallback step, object yieldedValue)
    {
        StartCoroutine(WaitAndResume(step, yieldedValue));
    }

    private IEnumerator WaitAndResume(LuaStepCallback step, object yieldedValue)
    {
        if (yieldedValue is YieldInstruction yi)
            yield return yi;
        else
            yield return null;
        
        step?.Invoke(null);
    }
}
```

---

## Lua 事件系统

```lua
-- Common/event.lua
-- 轻量级 Lua 事件总线

local EventBus = {}
local _listeners = {}  -- { eventName = { {handler, once} } }

-- 订阅事件
function EventBus.on(eventName, handler)
    if not _listeners[eventName] then
        _listeners[eventName] = {}
    end
    table.insert(_listeners[eventName], { handler = handler, once = false })
end

-- 订阅一次性事件
function EventBus.once(eventName, handler)
    if not _listeners[eventName] then
        _listeners[eventName] = {}
    end
    table.insert(_listeners[eventName], { handler = handler, once = true })
end

-- 取消订阅
function EventBus.off(eventName, handler)
    if not _listeners[eventName] then return end
    for i = #_listeners[eventName], 1, -1 do
        if _listeners[eventName][i].handler == handler then
            table.remove(_listeners[eventName], i)
        end
    end
end

-- 发送事件
function EventBus.emit(eventName, ...)
    if not _listeners[eventName] then return end
    local toRemove = {}
    for i, entry in ipairs(_listeners[eventName]) do
        local ok, err = pcall(entry.handler, ...)
        if not ok then
            print("[EventBus Error]", eventName, err)
        end
        if entry.once then
            table.insert(toRemove, i)
        end
    end
    -- 移除 once 回调（倒序删除）
    for i = #toRemove, 1, -1 do
        table.remove(_listeners[eventName], toRemove[i])
    end
end

-- 清理所有监听
function EventBus.clear(eventName)
    if eventName then
        _listeners[eventName] = nil
    else
        _listeners = {}
    end
end

return EventBus

-- 使用示例
-- local EventBus = require('Common.event')
-- EventBus.on('PlayerLevelUp', function(level) print('升级到', level) end)
-- EventBus.emit('PlayerLevelUp', 10)
```

---

## 性能优化

### 1. 避免每帧 Get Lua 函数

```csharp
// 错误：每帧通过字符串查找函数
void Update()
{
    var luaUpdate = _scriptEnv.Get<LuaFunction>("Update"); // 每帧 GC
    luaUpdate?.Call(Time.deltaTime);
    luaUpdate?.Dispose();
}

// 正确：Awake 时缓存委托
private LuaUpdater _cachedUpdate;

void Awake()
{
    _scriptEnv.Get("Update", out _cachedUpdate); // 只执行一次
}

void Update()
{
    _cachedUpdate?.Invoke(Time.deltaTime); // 无 GC
}
```

### 2. 减少 C#/Lua 跨界调用

```lua
-- 错误：在 Lua 中频繁调用 C# 小函数
for i = 1, 10000 do
    CS.UnityEngine.Mathf.Sin(i)  -- 每次都有跨界开销
end

-- 正确：在 Lua 中用内置数学库
local sin = math.sin
for i = 1, 10000 do
    sin(i)  -- 纯 Lua，无跨界开销
end
```

### 3. 定期 Lua GC + 避免全局变量

```lua
-- 错误：大量全局变量
someTable = {}  -- 全局，GC 压力大

-- 正确：局部变量
local someTable = {}

-- 模块内共享数据用 upvalue
local _moduleData = {}  -- 只在模块内可见的 "全局"

-- C# 侧定期触发 Lua GC
// _luaEnv.Tick(); // 定期调用（见 LuaManager.Update）
```

### 4. Lua Profiler 集成

```lua
-- 简单的 Lua 性能采样
local function profile(name, func, ...)
    local t0 = os.clock()
    local result = {func(...)}
    local elapsed = (os.clock() - t0) * 1000
    if elapsed > 1 then  -- 超过 1ms 才记录
        print(string.format("[Profile] %s: %.2fms", name, elapsed))
    end
    return table.unpack(result)
end
```

---

## 调试技巧

### 使用 EmmyLua 插件（VSCode/IntelliJ）

```lua
--- @class PlayerData
--- @field level number 当前等级
--- @field hp number 当前血量
--- @field name string 玩家名称
local PlayerData = {}

--- 增加经验值
--- @param amount number 经验量
--- @return boolean 是否升级
function PlayerData:addExp(amount)
    -- ...
end
```

### 错误堆栈追踪

```csharp
// 捕获 Lua 错误并获取完整堆栈
try
{
    _luaEnv.DoString("require('BuggyScript')");
}
catch (LuaException e)
{
    Debug.LogError($"Lua错误:\n{e.Message}\n堆栈:\n{e.StackTrace}");
}
```

---

## 最佳实践总结

| 实践点 | 说明 |
|--------|------|
| **LuaEnv 全局唯一** | 整个游戏只创建一个 LuaEnv，避免多虚拟机内存浪费 |
| **定期调用 Tick** | 每秒调用 `LuaEnv.Tick()` 触发 Lua GC，防止内存积累 |
| **缓存 Lua 函数委托** | Awake 时缓存 Update/FixedUpdate 等高频函数，避免每帧 GC |
| **独立 Lua 环境** | 每个 LuaBehaviour 使用独立的 LuaTable 作为执行环境，防止脚本相互污染 |
| **按需加载** | 使用 `require` 懒加载模块，而非启动时加载所有脚本 |
| **Hotfix 谨慎使用** | Hotfix 只用于修复 Bug，不要用于大规模新功能开发 |
| **资源热更先于脚本热更** | 先下载最新 Lua 字节码到持久化目录，再用自定义 Loader 优先加载 |
| **Lua bytecode 编译** | 生产包使用 `luac` 编译为字节码，提升加载速度且无法反编译 |
| **错误保护** | 所有 Lua 调用入口用 `pcall` 包裹，防止 Lua 异常崩溃 C# |
| **类型安全接口** | 优先用 `[CSharpCallLua]` 接口而非 `LuaFunction.Call`，性能更好且类型安全 |

---

## 总结

xLua 是目前 Unity 生态中最成熟的 Lua 热更新方案，其核心价值在于：

1. **Hotfix 机制**：可以在不重启应用的情况下修复任意 C# 方法，是线上紧急 Bug 修复的利器
2. **高性能绑定**：通过代码生成避免反射，C#/Lua 跨界调用开销极低
3. **零侵入性**：不改变现有 C# 架构，通过 `[LuaCallCSharp]`/`[Hotfix]` 标记按需集成
4. **成熟的生态**：腾讯内部多款亿级 DAU 游戏验证，稳定性可靠

选择 xLua 需要权衡的主要成本是：团队需要同时掌握 C# 和 Lua 两套语言，调试工具链相比纯 C# 略弱。对于需要热更新能力且愿意投入 Lua 技术栈的团队，xLua 是目前最值得推荐的方案。
