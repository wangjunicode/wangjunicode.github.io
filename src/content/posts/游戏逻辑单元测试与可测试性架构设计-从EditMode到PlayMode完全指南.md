---
title: 游戏逻辑单元测试与可测试性架构设计：从EditMode到PlayMode完全指南
published: 2026-04-15
description: 深入讲解Unity游戏客户端单元测试体系，覆盖EditMode/PlayMode测试、NUnit框架应用、Mock对象设计、可测试性架构重构，以及CI集成自动化测试的完整工程实践。
tags: [Unity, 单元测试, NUnit, TDD, 测试架构, CI/CD]
category: 工程实践
draft: false
---

# 游戏逻辑单元测试与可测试性架构设计：从EditMode到PlayMode完全指南

## 引言：为什么游戏项目需要单元测试

在游戏行业，"游戏代码不需要写测试"的误区根深蒂固，但随着项目规模扩大，未经测试的代码库成为技术债的温床。一个中型手游项目若没有测试保障，每次版本迭代都需要大量人工回归，线上Bug修复成本极高。

**单元测试在游戏开发中的核心价值**：
- **战斗公式验证**：伤害计算、暴击率、抗性减免等数值公式必须精确
- **状态机逻辑验证**：角色状态转换、Buff叠加逻辑的边界情况
- **网络协议解析**：消息序列化/反序列化的正确性
- **工具链稳定性**：Editor工具、配置解析器的健壮性
- **回归保护**：重构时防止引入新Bug

## Unity测试框架体系概览

```
Unity Test Framework
├── EditMode Tests (编辑器模式测试)
│   ├── 不需要Unity运行时 (无场景加载)
│   ├── 适合：纯逻辑、工具链、数据处理
│   └── 执行速度：极快 (<100ms/用例)
└── PlayMode Tests (运行模式测试)
    ├── 需要完整Unity运行时
    ├── 适合：协程、物理、异步操作、场景逻辑
    └── 执行速度：较慢 (需启动场景)
```

## 一、项目结构与测试目录规范

### 1.1 推荐的测试目录结构

```
Assets/
├── Scripts/
│   ├── Runtime/          # 运行时代码
│   │   ├── Battle/
│   │   ├── Network/
│   │   └── UI/
│   └── Editor/           # 编辑器工具代码
├── Tests/
│   ├── EditMode/         # 编辑器模式测试
│   │   ├── Battle/
│   │   │   └── DamageCalculatorTests.cs
│   │   ├── Network/
│   │   │   └── ProtocolParserTests.cs
│   │   └── EditMode.asmdef
│   └── PlayMode/         # 运行模式测试
│       ├── Character/
│       │   └── CharacterControllerTests.cs
│       ├── Scene/
│       │   └── SceneLoadTests.cs
│       └── PlayMode.asmdef
```

### 1.2 Assembly Definition 配置

```json
// EditMode.asmdef
{
    "name": "Game.Tests.EditMode",
    "references": [
        "Game.Runtime",
        "Game.Editor",
        "UnityEngine.TestRunner",
        "UnityEditor.TestRunner"
    ],
    "includePlatforms": ["Editor"],
    "excludePlatforms": [],
    "allowUnsafeCode": false,
    "overrideReferences": true,
    "precompiledReferences": [
        "nunit.framework.dll"
    ],
    "autoReferenced": false,
    "defineConstraints": [],
    "versionDefines": [],
    "noEngineReferences": false
}
```

## 二、EditMode 测试实战

### 2.1 战斗伤害计算测试

```csharp
using NUnit.Framework;
using Game.Battle;

namespace Game.Tests.EditMode.Battle
{
    [TestFixture]
    public class DamageCalculatorTests
    {
        private DamageCalculator _calculator;

        [SetUp]
        public void SetUp()
        {
            _calculator = new DamageCalculator();
        }

        // ===== 基础伤害计算 =====
        [Test]
        public void Calculate_BasicDamage_ReturnsCorrectValue()
        {
            // Arrange
            var attacker = new BattleUnit { Attack = 100 };
            var defender = new BattleUnit { Defense = 20 };

            // Act
            int damage = _calculator.Calculate(attacker, defender);

            // Assert
            Assert.AreEqual(80, damage, "基础伤害 = 攻击 - 防御");
        }

        // ===== 参数化测试：覆盖多种边界值 =====
        [TestCase(100, 0,   100, Description = "零防御")]
        [TestCase(100, 100, 1,   Description = "防御等于攻击时最低伤害1")]
        [TestCase(50,  200, 1,   Description = "防御远超攻击时最低伤害1")]
        [TestCase(0,   50,  1,   Description = "攻击力为零")]
        public void Calculate_VariousDefense_ClampedToMinimum(
            int attack, int defense, int expectedDamage)
        {
            var attacker = new BattleUnit { Attack = attack };
            var defender = new BattleUnit { Defense = defense };

            int damage = _calculator.Calculate(attacker, defender);

            Assert.AreEqual(expectedDamage, damage);
        }

        // ===== 暴击测试 =====
        [Test]
        public void Calculate_WithCritical_DamageDoubled()
        {
            var attacker = new BattleUnit { Attack = 100, CritMultiplier = 2.0f };
            var defender = new BattleUnit { Defense = 0 };

            // 强制暴击
            int normalDamage = _calculator.Calculate(attacker, defender, isCritical: false);
            int critDamage = _calculator.Calculate(attacker, defender, isCritical: true);

            Assert.AreEqual(normalDamage * 2, critDamage, "暴击伤害应为普通伤害的两倍");
        }

        // ===== Buff加成测试 =====
        [Test]
        public void Calculate_WithAttackBuff_IncreasesOutputDamage()
        {
            var attacker = new BattleUnit { Attack = 100 };
            var defender = new BattleUnit { Defense = 0 };
            var buff = new AttackBuff { Percentage = 0.5f }; // 50%攻击加成
            attacker.AddBuff(buff);

            int damage = _calculator.Calculate(attacker, defender);

            Assert.AreEqual(150, damage, "50%攻击Buff应使伤害变为150");
        }

        [TearDown]
        public void TearDown()
        {
            _calculator = null;
        }
    }
}
```

### 2.2 协议解析器测试

```csharp
using NUnit.Framework;
using System.IO;
using Game.Network;

namespace Game.Tests.EditMode.Network
{
    [TestFixture]
    public class ProtocolParserTests
    {
        // ===== 序列化往返测试 =====
        [Test]
        public void Serialize_ThenDeserialize_ReturnsSameData()
        {
            var original = new LoginRequest
            {
                UserId = "player_12345",
                Token = "abc123xyz",
                Platform = PlatformType.Android,
                ClientVersion = "2.3.1"
            };

            byte[] data = ProtocolSerializer.Serialize(original);
            var restored = ProtocolSerializer.Deserialize<LoginRequest>(data);

            Assert.AreEqual(original.UserId, restored.UserId);
            Assert.AreEqual(original.Token, restored.Token);
            Assert.AreEqual(original.Platform, restored.Platform);
            Assert.AreEqual(original.ClientVersion, restored.ClientVersion);
        }

        // ===== 边界值：空字段测试 =====
        [Test]
        public void Serialize_WithNullFields_HandledGracefully()
        {
            var request = new LoginRequest { UserId = null };

            Assert.DoesNotThrow(() =>
            {
                byte[] data = ProtocolSerializer.Serialize(request);
                var restored = ProtocolSerializer.Deserialize<LoginRequest>(data);
                Assert.IsNull(restored.UserId);
            });
        }

        // ===== 数据完整性校验 =====
        [Test]
        public void Deserialize_CorruptedData_ThrowsException()
        {
            byte[] corruptedData = new byte[] { 0xFF, 0xFE, 0x00, 0x01 };

            Assert.Throws<ProtocolException>(() =>
            {
                ProtocolSerializer.Deserialize<LoginRequest>(corruptedData);
            }, "损坏数据应抛出ProtocolException");
        }

        // ===== 性能测试：BenchmarkDotNet风格 =====
        [Test]
        [Performance]
        public void Serialize_Performance_Under1Ms()
        {
            var request = CreateTestLoginRequest();
            var sw = System.Diagnostics.Stopwatch.StartNew();

            for (int i = 0; i < 10000; i++)
            {
                ProtocolSerializer.Serialize(request);
            }

            sw.Stop();
            float avgMs = sw.ElapsedMilliseconds / 10000f;

            Assert.Less(avgMs, 1.0f, $"序列化均值 {avgMs}ms 超过1ms阈值");
        }

        private LoginRequest CreateTestLoginRequest()
        {
            return new LoginRequest
            {
                UserId = "test_user",
                Token = "test_token_xyz",
                Platform = PlatformType.iOS
            };
        }
    }
}
```

### 2.3 状态机逻辑测试

```csharp
using NUnit.Framework;
using Game.StateMachine;

namespace Game.Tests.EditMode.StateMachine
{
    [TestFixture]
    public class CharacterFSMTests
    {
        private CharacterStateMachine _fsm;

        [SetUp]
        public void SetUp()
        {
            _fsm = new CharacterStateMachine();
            _fsm.Initialize(CharacterState.Idle);
        }

        [Test]
        public void InitialState_IsIdle()
        {
            Assert.AreEqual(CharacterState.Idle, _fsm.CurrentState);
        }

        [Test]
        public void TransitionTo_Run_FromIdle_Succeeds()
        {
            _fsm.TriggerTransition(CharacterTrigger.MoveInput);

            Assert.AreEqual(CharacterState.Running, _fsm.CurrentState);
        }

        [Test]
        public void TransitionTo_Attack_FromIdle_Succeeds()
        {
            _fsm.TriggerTransition(CharacterTrigger.AttackInput);

            Assert.AreEqual(CharacterState.Attacking, _fsm.CurrentState);
        }

        [Test]
        public void TransitionTo_Run_FromDead_Fails()
        {
            // 死亡状态不能切换到跑步
            _fsm.ForceState(CharacterState.Dead);
            _fsm.TriggerTransition(CharacterTrigger.MoveInput);

            Assert.AreEqual(CharacterState.Dead, _fsm.CurrentState, "死亡状态不应响应移动输入");
        }

        // ===== 状态转换历史记录测试 =====
        [Test]
        public void TransitionHistory_RecordsAllTransitions()
        {
            _fsm.TriggerTransition(CharacterTrigger.MoveInput);   // Idle -> Running
            _fsm.TriggerTransition(CharacterTrigger.AttackInput); // Running -> Attacking
            _fsm.TriggerTransition(CharacterTrigger.AnimEnd);     // Attacking -> Idle

            var history = _fsm.GetTransitionHistory();

            Assert.AreEqual(3, history.Count);
            Assert.AreEqual(CharacterState.Idle, history[0].From);
            Assert.AreEqual(CharacterState.Running, history[0].To);
        }

        // ===== 并发触发安全性测试 =====
        [Test]
        public void TriggerMultiple_SameFrame_OnlyOneTransitionOccurs()
        {
            // 同一帧多次触发，只应执行一次
            _fsm.TriggerTransition(CharacterTrigger.AttackInput);
            _fsm.TriggerTransition(CharacterTrigger.AttackInput);
            _fsm.TriggerTransition(CharacterTrigger.AttackInput);

            Assert.AreEqual(1, _fsm.GetTransitionHistory().Count, "同帧重复触发只应执行一次");
        }
    }
}
```

## 三、PlayMode 测试实战

### 3.1 异步资源加载测试

```csharp
using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using UnityEngine.AddressableAssets;

namespace Game.Tests.PlayMode
{
    [TestFixture]
    public class ResourceLoadTests
    {
        [UnityTest]
        public IEnumerator LoadAsset_ValidAddress_ReturnsValidObject()
        {
            // Arrange
            const string address = "Characters/Hero_Warrior";
            GameObject loadedObj = null;

            // Act - 使用协程等待异步加载
            var handle = Addressables.LoadAssetAsync<GameObject>(address);
            yield return handle;

            // Assert
            Assert.IsNotNull(handle.Result, $"地址 {address} 加载结果为空");
            Assert.IsInstanceOf<GameObject>(handle.Result);

            // Cleanup
            Addressables.Release(handle);
        }

        [UnityTest]
        public IEnumerator LoadScene_WithTimeout_CompletesWithin5Seconds()
        {
            float startTime = Time.realtimeSinceStartup;
            bool loaded = false;

            // 异步加载场景
            var op = UnityEngine.SceneManagement.SceneManager
                .LoadSceneAsync("BattleScene", 
                    UnityEngine.SceneManagement.LoadSceneMode.Additive);

            while (!op.isDone)
            {
                if (Time.realtimeSinceStartup - startTime > 5f)
                {
                    Assert.Fail("场景加载超时（>5秒）");
                    yield break;
                }
                yield return null;
            }

            loaded = op.isDone;
            Assert.IsTrue(loaded, "场景应在5秒内加载完成");

            // Cleanup
            yield return UnityEngine.SceneManagement.SceneManager
                .UnloadSceneAsync("BattleScene");
        }

        [UnityTest]
        public IEnumerator ObjectPool_PrewarmThenGet_ReturnsPrewarmedObject()
        {
            var pool = new GameObject("TestPool").AddComponent<GameObjectPool>();
            pool.Initialize("Effects/Hit_Effect", prewarmCount: 5);

            // 等待预热完成
            yield return new WaitForSeconds(0.1f);

            // 获取对象应从池中取出
            var obj1 = pool.Get();
            var obj2 = pool.Get();

            Assert.IsNotNull(obj1);
            Assert.IsNotNull(obj2);
            Assert.AreNotSame(obj1, obj2, "每次Get应返回不同对象");

            // Cleanup
            Object.Destroy(pool.gameObject);
        }
    }
}
```

### 3.2 网络模拟器集成测试

```csharp
using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Game.Network;

namespace Game.Tests.PlayMode.Network
{
    /// <summary>
    /// 网络消息收发集成测试（使用本地回环模拟）
    /// </summary>
    [TestFixture]
    public class NetworkIntegrationTests
    {
        private MockNetworkSession _session;

        [SetUp]
        public void SetUp()
        {
            _session = new MockNetworkSession();
            _session.Connect("127.0.0.1", 8888);
        }

        [UnityTest]
        public IEnumerator SendMessage_EchoServer_ReceivesSameMessage()
        {
            bool received = false;
            string receivedContent = null;

            _session.OnMessageReceived += (msg) =>
            {
                received = true;
                receivedContent = msg.Content;
            };

            // 发送消息
            _session.Send(new ChatMessage { Content = "Hello Server" });

            // 等待最多2秒收到回执
            float timeout = 2f;
            while (!received && timeout > 0)
            {
                timeout -= Time.deltaTime;
                yield return null;
            }

            Assert.IsTrue(received, "未在2秒内收到服务器回执");
            Assert.AreEqual("Hello Server", receivedContent);
        }

        [UnityTest]
        public IEnumerator NetworkDisconnect_ReconnectMechanism_WorksCorrectly()
        {
            // 模拟断开连接
            _session.SimulateDisconnect();
            yield return new WaitForSeconds(0.1f);

            Assert.AreEqual(ConnectionState.Disconnected, _session.State);

            // 触发重连
            _session.Reconnect();
            yield return new WaitForSeconds(1.0f);

            Assert.AreEqual(ConnectionState.Connected, _session.State, "重连后应恢复Connected状态");
        }

        [TearDown]
        public void TearDown()
        {
            _session?.Disconnect();
            _session = null;
        }
    }
}
```

## 四、Mock对象设计：解耦外部依赖

### 4.1 服务接口抽象与Mock实现

可测试性架构的核心是**依赖倒置**——业务逻辑依赖接口而非具体实现，测试时注入Mock对象。

```csharp
// ===== 接口定义 =====
public interface INetworkService
{
    Task<LoginResponse> LoginAsync(string userId, string token);
    Task<PlayerData> GetPlayerDataAsync(string userId);
    void Disconnect();
}

public interface IStorageService
{
    T Load<T>(string key) where T : class;
    void Save<T>(string key, T data) where T : class;
    bool Exists(string key);
}

// ===== Mock实现 =====
public class MockNetworkService : INetworkService
{
    // 可配置的预设响应
    public LoginResponse LoginResponseOverride { get; set; }
    public bool ShouldSimulateTimeout { get; set; }
    public int SimulatedLatencyMs { get; set; } = 0;

    // 调用记录，用于验证
    public List<string> CallLog { get; } = new List<string>();

    public async Task<LoginResponse> LoginAsync(string userId, string token)
    {
        CallLog.Add($"LoginAsync({userId}, {token})");

        if (ShouldSimulateTimeout)
        {
            await Task.Delay(30000); // 30秒超时
            throw new TimeoutException("Mock: 模拟网络超时");
        }

        if (SimulatedLatencyMs > 0)
            await Task.Delay(SimulatedLatencyMs);

        return LoginResponseOverride ?? new LoginResponse
        {
            Success = true,
            SessionId = "mock_session_001",
            PlayerId = userId
        };
    }

    public async Task<PlayerData> GetPlayerDataAsync(string userId)
    {
        CallLog.Add($"GetPlayerDataAsync({userId})");
        await Task.Delay(SimulatedLatencyMs);

        return new PlayerData
        {
            UserId = userId,
            Level = 10,
            Gold = 9999
        };
    }

    public void Disconnect()
    {
        CallLog.Add("Disconnect()");
    }
}

// ===== 内存存储Mock =====
public class MockStorageService : IStorageService
{
    private readonly Dictionary<string, object> _storage = new Dictionary<string, object>();

    public T Load<T>(string key) where T : class
    {
        return _storage.TryGetValue(key, out var value) ? value as T : null;
    }

    public void Save<T>(string key, T data) where T : class
    {
        _storage[key] = data;
    }

    public bool Exists(string key) => _storage.ContainsKey(key);

    public void Clear() => _storage.Clear();
}
```

### 4.2 被测系统使用依赖注入

```csharp
// ===== 可测试的登录管理器 =====
public class LoginManager
{
    private readonly INetworkService _network;
    private readonly IStorageService _storage;

    // 通过构造函数注入依赖（便于测试替换）
    public LoginManager(INetworkService network, IStorageService storage)
    {
        _network = network;
        _storage = storage;
    }

    public async Task<LoginResult> LoginAsync(string userId, string token)
    {
        try
        {
            var response = await _network.LoginAsync(userId, token);

            if (response.Success)
            {
                // 缓存Session
                _storage.Save("session", response.SessionId);
                _storage.Save("userId", userId);

                return LoginResult.Success(response.SessionId);
            }

            return LoginResult.Failed(response.ErrorMessage);
        }
        catch (TimeoutException)
        {
            return LoginResult.Failed("网络超时，请重试");
        }
        catch (Exception ex)
        {
            return LoginResult.Failed($"登录异常: {ex.Message}");
        }
    }

    public bool IsLoggedIn()
    {
        return _storage.Exists("session");
    }
}

// ===== 对应测试 =====
[TestFixture]
public class LoginManagerTests
{
    private MockNetworkService _mockNetwork;
    private MockStorageService _mockStorage;
    private LoginManager _loginManager;

    [SetUp]
    public void SetUp()
    {
        _mockNetwork = new MockNetworkService();
        _mockStorage = new MockStorageService();
        _loginManager = new LoginManager(_mockNetwork, _mockStorage);
    }

    [Test]
    public async Task Login_Success_StoresSessionToken()
    {
        // Arrange: 配置Mock返回成功
        _mockNetwork.LoginResponseOverride = new LoginResponse
        {
            Success = true,
            SessionId = "session_abc123"
        };

        // Act
        var result = await _loginManager.LoginAsync("user_001", "token_xyz");

        // Assert
        Assert.IsTrue(result.IsSuccess);
        Assert.AreEqual("session_abc123", _mockStorage.Load<string>("session"));
        Assert.IsTrue(_loginManager.IsLoggedIn());
    }

    [Test]
    public async Task Login_NetworkTimeout_ReturnsFailedResult()
    {
        // Arrange: 配置Mock模拟超时
        _mockNetwork.ShouldSimulateTimeout = true;

        // Act
        var result = await _loginManager.LoginAsync("user_001", "token");

        // Assert
        Assert.IsFalse(result.IsSuccess);
        StringAssert.Contains("超时", result.ErrorMessage);
        Assert.IsFalse(_loginManager.IsLoggedIn(), "超时后不应处于登录状态");
    }

    [Test]
    public async Task Login_CallsNetworkService_OnlyOnce()
    {
        await _loginManager.LoginAsync("user_001", "token");

        // 验证网络请求只调用了一次
        Assert.AreEqual(1, _mockNetwork.CallLog.Count(c => c.StartsWith("LoginAsync")));
    }
}
```

## 五、可测试性架构重构指南

### 5.1 识别不可测试代码的特征

```csharp
// ❌ 难以测试的代码：直接依赖静态类和单例
public class BattleSystem
{
    public void StartBattle()
    {
        // 问题1: 直接访问全局单例
        var player = GameManager.Instance.CurrentPlayer;

        // 问题2: 直接调用Unity API
        Time.timeScale = 0.5f;

        // 问题3: 直接实例化依赖
        var network = new NetworkClient("server.example.com", 8888);

        // 问题4: 硬编码文件路径
        var config = File.ReadAllText("/data/configs/battle.json");

        network.SendBattleStart(player.Id);
    }
}
```

```csharp
// ✅ 可测试的重构版本
public class BattleSystem
{
    private readonly IPlayerProvider _playerProvider;
    private readonly ITimeController _timeController;
    private readonly INetworkService _network;
    private readonly IConfigLoader _configLoader;

    public BattleSystem(
        IPlayerProvider playerProvider,
        ITimeController timeController,
        INetworkService network,
        IConfigLoader configLoader)
    {
        _playerProvider = playerProvider;
        _timeController = timeController;
        _network = network;
        _configLoader = configLoader;
    }

    public async Task StartBattle()
    {
        var player = _playerProvider.GetCurrentPlayer();
        _timeController.SetTimeScale(0.5f);
        var config = await _configLoader.LoadAsync<BattleConfig>("battle");
        await _network.SendBattleStartAsync(player.Id);
    }
}

// ===== 对应测试 =====
[TestFixture]
public class BattleSystemTests
{
    [Test]
    public async Task StartBattle_ValidPlayer_SendsNetworkRequest()
    {
        var mockPlayer = new MockPlayerProvider { CurrentPlayer = new Player { Id = "p001" } };
        var mockTime = new MockTimeController();
        var mockNetwork = new MockNetworkService();
        var mockConfig = new MockConfigLoader();

        var battleSystem = new BattleSystem(mockPlayer, mockTime, mockNetwork, mockConfig);
        await battleSystem.StartBattle();

        // 验证行为
        Assert.AreEqual(0.5f, mockTime.LastSetTimeScale);
        Assert.IsTrue(mockNetwork.CallLog.Any(c => c.Contains("SendBattleStart")));
    }
}
```

### 5.2 静态类与全局状态的处理策略

```csharp
// ===== 包装器模式：封装Unity静态API =====
public interface ITimeController
{
    float TimeScale { get; set; }
    float DeltaTime { get; }
    float RealtimeSinceStartup { get; }
    void SetTimeScale(float scale);
}

// 真实实现（生产用）
public class UnityTimeController : ITimeController
{
    public float TimeScale
    {
        get => Time.timeScale;
        set => Time.timeScale = value;
    }
    public float DeltaTime => Time.deltaTime;
    public float RealtimeSinceStartup => Time.realtimeSinceStartup;
    public void SetTimeScale(float scale) => Time.timeScale = scale;
}

// Mock实现（测试用）
public class MockTimeController : ITimeController
{
    public float TimeScale { get; set; } = 1.0f;
    public float DeltaTime { get; set; } = 0.016f; // 60fps
    public float RealtimeSinceStartup { get; set; } = 0f;
    public float LastSetTimeScale { get; private set; }

    public void SetTimeScale(float scale)
    {
        TimeScale = scale;
        LastSetTimeScale = scale;
    }

    // 测试工具：手动推进时间
    public void AdvanceTime(float seconds)
    {
        RealtimeSinceStartup += seconds;
    }
}
```

## 六、测试覆盖率与质量指标

### 6.1 在Editor中查看覆盖率

```csharp
// 在 Edit → Preferences → Testing 中开启 Code Coverage
// 或通过命令行运行：
// Unity -runTests -testPlatform EditMode -enableCodeCoverage -coverageResultsPath ./coverage
```

### 6.2 测试质量度量维度

| 指标 | 说明 | 目标值 |
|------|------|--------|
| 行覆盖率 | 代码行被测试执行的比例 | >70% (核心逻辑>90%) |
| 分支覆盖率 | if/else分支全部走到 | >60% |
| 测试通过率 | CI中测试全部Green | 100% |
| 测试执行时间 | EditMode测试总耗时 | <30秒 |
| 测试稳定性 | Flaky Test（偶发失败）占比 | <1% |

### 6.3 CI集成配置（GitHub Actions示例）

```yaml
# .github/workflows/unity-tests.yml
name: Unity Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}

      - name: Run EditMode Tests
        uses: game-ci/unity-test-runner@v3
        with:
          unityVersion: 2022.3.21f1
          testMode: editmode
          coverageOptions: 'generateAdditionalMetrics;generateHtmlReport'

      - name: Run PlayMode Tests
        uses: game-ci/unity-test-runner@v3
        with:
          unityVersion: 2022.3.21f1
          testMode: playmode

      - name: Upload Coverage Report
        uses: actions/upload-artifact@v3
        with:
          name: coverage-report
          path: CodeCoverage/
```

## 七、高级技巧：测试辅助工具

### 7.1 自定义断言扩展

```csharp
public static class GameAssert
{
    /// <summary>
    /// 断言两个Vector3在误差范围内相等
    /// </summary>
    public static void AreApproximatelyEqual(
        Vector3 expected, Vector3 actual, float tolerance = 0.001f,
        string message = null)
    {
        float distance = Vector3.Distance(expected, actual);
        if (distance > tolerance)
        {
            string msg = message ?? $"Vector3 差距 {distance} 超过容差 {tolerance}";
            Assert.Fail($"{msg}\n  Expected: {expected}\n  Actual:   {actual}");
        }
    }

    /// <summary>
    /// 断言浮点数在百分比误差内
    /// </summary>
    public static void AreApproximatelyEqualPercent(
        float expected, float actual, float percentTolerance = 0.01f)
    {
        float relativeError = Mathf.Abs((actual - expected) / expected);
        Assert.LessOrEqual(relativeError, percentTolerance,
            $"相对误差 {relativeError:P2} 超过 {percentTolerance:P2}");
    }

    /// <summary>
    /// 断言集合包含满足条件的元素
    /// </summary>
    public static void ContainsMatching<T>(
        IEnumerable<T> collection,
        System.Predicate<T> predicate,
        string message = null)
    {
        bool found = collection.Any(item => predicate(item));
        Assert.IsTrue(found, message ?? "集合中未找到满足条件的元素");
    }
}

// 使用示例：
[Test]
public void CharacterMovement_AfterMoveRight_PositionUpdated()
{
    var character = CreateTestCharacter(Vector3.zero);
    character.Move(Vector3.right * 5f);

    GameAssert.AreApproximatelyEqual(
        new Vector3(5f, 0f, 0f),
        character.Position,
        tolerance: 0.01f
    );
}
```

### 7.2 测试数据构建器（Builder Pattern）

```csharp
// 复杂测试数据的流式构建
public class BattleUnitBuilder
{
    private BattleUnit _unit = new BattleUnit();

    public static BattleUnitBuilder Default() => new BattleUnitBuilder();

    public BattleUnitBuilder WithAttack(int attack)
    {
        _unit.Attack = attack;
        return this;
    }

    public BattleUnitBuilder WithDefense(int defense)
    {
        _unit.Defense = defense;
        return this;
    }

    public BattleUnitBuilder WithLevel(int level)
    {
        _unit.Level = level;
        _unit.Attack = level * 10;
        _unit.MaxHp = level * 100;
        return this;
    }

    public BattleUnitBuilder AsBoss()
    {
        _unit.IsBoss = true;
        _unit.Attack *= 3;
        _unit.Defense *= 3;
        _unit.MaxHp *= 5;
        return this;
    }

    public BattleUnitBuilder WithBuff(IBuff buff)
    {
        _unit.AddBuff(buff);
        return this;
    }

    public BattleUnit Build() => _unit;
}

// 测试中使用：
[Test]
public void BossUnit_WithDefeatBuff_CorrectDamageCalculation()
{
    var boss = BattleUnitBuilder.Default()
        .WithLevel(50)
        .AsBoss()
        .WithBuff(new DefenseReductionBuff { Amount = 100 })
        .Build();

    var player = BattleUnitBuilder.Default()
        .WithAttack(500)
        .Build();

    int damage = _calculator.Calculate(player, boss);

    Assert.Greater(damage, 0, "减防Buff后玩家应能造成伤害");
}
```

## 八、最佳实践总结

### 8.1 FIRST原则

| 原则 | 英文 | 含义 |
|------|------|------|
| **F**ast | Fast | 单个测试执行时间<100ms |
| **I**ndependent | Independent | 测试间无依赖，顺序无关 |
| **R**epeatable | Repeatable | 任意环境下结果一致 |
| **S**elf-validating | Self-Validating | 自动判定Pass/Fail |
| **T**imely | Timely | 与功能代码同步编写 |

### 8.2 测试命名规范

```csharp
// 推荐格式：[方法名]_[测试场景]_[期望结果]
[Test] public void Calculate_ZeroDefense_ReturnFullAttackDamage() {}
[Test] public void Login_ExpiredToken_ThrowsAuthException() {}
[Test] public void LoadScene_InvalidName_ReturnsNull() {}

// 避免：
[Test] public void TestDamage() {}    // ❌ 不清楚测什么
[Test] public void Test1() {}          // ❌ 无意义命名
```

### 8.3 测试分层策略

```
测试金字塔：
        ╱╲
       ╱  ╲          E2E测试（少量）
      ╱────╲         → 完整游戏流程
     ╱      ╲
    ╱        ╲       集成测试（适量）
   ╱──────────╲     → PlayMode、网络、场景
  ╱            ╲
 ╱              ╲   单元测试（大量）
╱────────────────╲  → EditMode、纯逻辑、算法
```

### 8.4 常见陷阱与规避

```csharp
// ❌ 陷阱1: 测试依赖执行顺序
public static int _counter = 0;
[Test] public void Test_A() { _counter++; }
[Test] public void Test_B() { Assert.AreEqual(1, _counter); } // 可能失败！

// ✅ 正确: 每个测试独立初始化
[SetUp] public void SetUp() { _counter = 0; }

// ❌ 陷阱2: 使用Random导致不确定性
[Test]
public void Test_RandomDrop()
{
    var item = ItemDrop.GetRandom(); // 每次结果不同！
    Assert.IsNotNull(item);
}

// ✅ 正确: 使用固定种子
[Test]
public void Test_RandomDrop_WithSeed()
{
    var rng = new System.Random(seed: 42);
    var item = ItemDrop.GetRandom(rng);
    Assert.AreEqual("SwordOfFire", item.Name); // 固定种子，结果可预测
}

// ❌ 陷阱3: 测试代码中有复杂逻辑
[Test]
public void Test_ComplexLogicInTest()
{
    int expected = 0;
    for (int i = 0; i < 100; i++) expected += i; // 复杂计算可能本身有Bug！
    Assert.AreEqual(expected, Sum(0, 100));
}

// ✅ 正确: 使用硬编码期望值
[Test]
public void Test_Sum_0To100_Returns4950()
{
    Assert.AreEqual(4950, Sum(0, 100)); // 直接写出正确答案
}
```

## 结语

游戏逻辑单元测试的建立是一个循序渐进的过程。建议从以下路径入手：

1. **第一步**：为现有战斗公式、数值计算补写EditMode测试
2. **第二步**：将核心系统重构为可注入接口的架构
3. **第三步**：为关键流程编写PlayMode集成测试
4. **第四步**：接入CI，确保每次提交自动跑测试

投入测试基础设施的时间，会在项目后期通过大幅减少的回归Bug和重构信心倍速偿还。测试不是负担，而是让你敢于重构的勇气来源。
