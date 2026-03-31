---
title: Unity 编辑器扩展：自动化测试框架与持续集成实践
published: 2026-03-31
description: 深度解析 Unity 项目的自动化测试体系构建，涵盖 Unity Test Framework（EditMode/PlayMode测试）、测试用例设计模式（AAA原则）、Mock/Stub技术、性能基准测试、CI/CD流水线配置（GitHub Actions/Jenkins）、自动截图测试，以及回归测试策略与测试覆盖率要求。
tags: [Unity, 单元测试, CI/CD, 自动化测试, 工程实践]
category: 工程实践
draft: false
---

## 一、Unity Test Framework 基础

### EditMode 测试（不启动运行时）
```csharp
using NUnit.Framework;
using UnityEngine;
using UnityEditor;

/// <summary>
/// 数值系统单元测试（EditMode）
/// </summary>
public class DamageCalculatorTests
{
    private DamageCalculator calculator;

    [SetUp]
    public void Setup()
    {
        calculator = new DamageCalculator();
    }

    [TearDown]
    public void Teardown()
    {
        calculator = null;
    }

    // AAA 原则：Arrange / Act / Assert

    [Test]
    public void CalculateDamage_NormalHit_ReturnsExpectedDamage()
    {
        // Arrange
        float baseAttack = 100f;
        float defense = 50f;
        bool isCritical = false;

        // Act
        float result = calculator.Calculate(baseAttack, defense, isCritical);

        // Assert
        Assert.AreEqual(50f, result, 0.001f, "普通攻击伤害应为 ATK - DEF");
    }

    [Test]
    public void CalculateDamage_CriticalHit_DoublesDamage()
    {
        // Arrange
        float baseAttack = 100f;
        float defense = 50f;
        bool isCritical = true;

        // Act
        float result = calculator.Calculate(baseAttack, defense, isCritical);

        // Assert
        Assert.AreEqual(100f, result, 0.001f, "暴击伤害应为普通伤害的2倍");
    }

    [Test]
    public void CalculateDamage_HighDefense_MinimumOneDamage()
    {
        // Arrange（防御高于攻击的极端情况）
        float baseAttack = 10f;
        float defense = 1000f;

        // Act
        float result = calculator.Calculate(baseAttack, defense, false);

        // Assert
        Assert.GreaterOrEqual(result, 1f, "伤害最低应为1");
    }

    // 参数化测试（数据驱动）
    [TestCase(100, 0, false, 100f)]
    [TestCase(100, 50, false, 50f)]
    [TestCase(100, 100, false, 1f)]  // 最低1点
    [TestCase(100, 50, true, 100f)]  // 暴击
    public void CalculateDamage_ParameterizedCases(float atk, float def, bool crit, float expected)
    {
        float result = calculator.Calculate(atk, def, crit);
        Assert.AreEqual(expected, result, 0.001f);
    }
}
```

### PlayMode 测试（运行时场景中）

```csharp
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using System.Collections;

/// <summary>
/// 角色控制器集成测试（PlayMode）
/// 测试涉及物理/协程，需要在运行时执行
/// </summary>
public class CharacterControllerTests
{
    private GameObject testObject;
    private PlayerController playerController;

    [UnitySetUp]
    public IEnumerator Setup()
    {
        // 创建测试场景环境
        testObject = new GameObject("TestPlayer");
        testObject.AddComponent<CharacterController>();
        playerController = testObject.AddComponent<PlayerController>();
        
        // 创建地面
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.transform.position = new Vector3(0, -0.5f, 0);
        
        // 等待一帧初始化
        yield return null;
    }

    [UnityTearDown]
    public IEnumerator Teardown()
    {
        Object.Destroy(testObject);
        yield return null;
    }

    [UnityTest]
    public IEnumerator PlayerJump_WhenGrounded_IncreasesYVelocity()
    {
        // Arrange
        Assert.IsTrue(playerController.IsGrounded, "测试前角色应在地面");
        
        // Act
        playerController.Jump();
        
        // Assert（等待一帧检查状态）
        yield return null;
        Assert.Greater(playerController.Velocity.y, 0, "跳跃后Y速度应为正值");
    }

    [UnityTest]
    public IEnumerator PlayerMovement_LeftInput_MovesLeft()
    {
        // Arrange
        Vector3 startPos = testObject.transform.position;
        
        // Act：模拟输入
        playerController.SimulateInput(new Vector2(-1, 0));
        yield return new WaitForSeconds(0.5f);
        
        // Assert
        Assert.Less(testObject.transform.position.x, startPos.x, "左移后X应减小");
    }
}
```

---

## 二、Mock / Stub 技术

```csharp
/// <summary>
/// 接口定义（便于测试Mock）
/// </summary>
public interface INetworkService
{
    System.Threading.Tasks.Task<LoginResponse> Login(string userId);
    System.Threading.Tasks.Task<bool> SaveProgress(SaveData data);
}

/// <summary>
/// Mock 网络服务（测试中替换真实网络）
/// </summary>
public class MockNetworkService : INetworkService
{
    public bool ShouldFail;
    public int CallCount;
    public SaveData LastSavedData;
    
    public async System.Threading.Tasks.Task<LoginResponse> Login(string userId)
    {
        CallCount++;
        if (ShouldFail)
            throw new Exception("Mock: 网络连接失败");
        
        return new LoginResponse { Success = true, PlayerId = userId };
    }
    
    public async System.Threading.Tasks.Task<bool> SaveProgress(SaveData data)
    {
        CallCount++;
        LastSavedData = data;
        return !ShouldFail;
    }
}

/// <summary>
/// 使用 Mock 的测试
/// </summary>
public class LoginManagerTests
{
    private MockNetworkService mockNetwork;
    private LoginManager loginManager;

    [SetUp]
    public void Setup()
    {
        mockNetwork = new MockNetworkService();
        loginManager = new LoginManager(mockNetwork); // 依赖注入
    }

    [Test]
    public async System.Threading.Tasks.Task Login_Success_UpdatesPlayerData()
    {
        // Arrange
        string testUserId = "user_123";
        mockNetwork.ShouldFail = false;

        // Act
        bool success = await loginManager.Login(testUserId);

        // Assert
        Assert.IsTrue(success);
        Assert.AreEqual(1, mockNetwork.CallCount);
        Assert.IsNotNull(loginManager.CurrentPlayer);
    }

    [Test]
    public async System.Threading.Tasks.Task Login_NetworkFailure_RetrysTwice()
    {
        // Arrange
        mockNetwork.ShouldFail = true;

        // Act
        await loginManager.Login("user_123");

        // Assert
        Assert.AreEqual(3, mockNetwork.CallCount, "登录失败应重试2次（共3次调用）");
    }
}
```

---

## 三、性能基准测试

```csharp
using Unity.PerformanceTesting;
using NUnit.Framework;
using UnityEngine.TestTools;
using System.Collections;

/// <summary>
/// 性能基准测试
/// 需要安装 Unity Performance Testing 包
/// </summary>
public class PerformanceBenchmarks
{
    [Performance, UnityTest]
    public IEnumerator PathfindingPerformance_1000Agents()
    {
        // 使用 Measure 记录帧时间
        yield return Measure.Frames()
            .WarmupCount(10)    // 预热帧
            .MeasurementCount(50)  // 测量帧数
            .ProfilerMarkers(    // 监控特定 ProfilerMarker
                "NavMeshAgent.Update",
                "BehaviorTree.Update")
            .Run();
    }
    
    [Performance, Test]
    public void InventorySearch_1000Items_Under1ms()
    {
        var inventory = CreateInventoryWith1000Items();
        string searchTerm = "sword";
        
        Measure.Method(() =>
        {
            inventory.Search(searchTerm);
        })
        .WarmupCount(5)
        .MeasurementCount(100)
        .Run();
        
        // 结果通过 PerformanceTesting SDK 上报
        // 可设置性能回归告警阈值
    }
    
    InventorySystem CreateInventoryWith1000Items()
    {
        var inv = new InventorySystem();
        for (int i = 0; i < 1000; i++)
            inv.AddItem(new Item { Id = $"item_{i}", Name = $"Item {i}" });
        return inv;
    }
}
```

---

## 四、GitHub Actions CI/CD 配置

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
    name: Unity Tests (${{ matrix.unityVersion }})
    runs-on: ubuntu-latest
    
    strategy:
      matrix:
        unityVersion: ['2022.3.10f1']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
      
      - name: Run EditMode Tests
        uses: game-ci/unity-test-runner@v4
        with:
          unityVersion: ${{ matrix.unityVersion }}
          testMode: editmode
          artifactsPath: test-results/editmode
          customParameters: -enableCodeCoverage -coverageResultsPath coverage
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
      
      - name: Run PlayMode Tests
        uses: game-ci/unity-test-runner@v4
        with:
          unityVersion: ${{ matrix.unityVersion }}
          testMode: playmode
          artifactsPath: test-results/playmode
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
      
      - name: Publish Test Results
        uses: dorny/test-reporter@v1
        if: always()
        with:
          name: Unity Tests
          path: test-results/**/*.xml
          reporter: java-junit
      
      - name: Upload Coverage
        uses: codecov/codecov-action@v3
        with:
          files: coverage/**/*.xml
```

---

## 五、测试覆盖率目标

| 模块 | 推荐覆盖率 | 说明 |
|------|-----------|------|
| 核心数值计算 | ≥90% | 伤害/属性/概率等 |
| 存档序列化 | ≥85% | 版本迁移、加密解密 |
| 网络协议 | ≥80% | 编解码、粘包处理 |
| UI 逻辑 | ≥60% | 状态机、显隐逻辑 |
| 渲染/特效 | 无需 | 视觉效果难以自动化 |

**测试金字塔原则：**
```
         /E2E Tests\         ← 少量，端到端场景验证
        /  Integration \     ← 适量，模块间协作
       /    Unit Tests   \   ← 大量，单函数/类测试
```

**CI 要求：**
- 所有 PR 必须通过全部测试才能合并
- 性能回归超过 20% 自动 Block
- 每日夜间完整 PlayMode 测试套件
