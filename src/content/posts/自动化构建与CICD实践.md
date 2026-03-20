---
title: 自动化构建与 CI/CD 实践：游戏工程效能全攻略
published: 2026-03-21
description: "系统讲解游戏项目的自动化构建体系设计，包括 Unity 命令行构建、Jenkins/GitHub Actions 流水线搭建、自动化测试接入、多渠道打包管理、构建缓存优化等工程效能核心实践。"
tags: [CI/CD, 自动化构建, Unity, 工程效能, Jenkins]
category: 工程效能
draft: false
---

## 工程效能的价值

一个 10 人团队，如果每天打包需要 30 分钟：

```
30分钟 × 10次/天 × 240个工作日 = 1200小时/年 ≈ 150个工作日

这相当于 1 个工程师全年什么都不做，只负责打包。
```

自动化构建解决的不只是时间问题，更解决了：
- **一致性**：手动操作容易出错，自动化保证每次相同
- **可见性**：代码提交 → 构建状态 → 测试结果，全程可见
- **信心**：每次代码变更都有验证，而不是等到提测才发现问题

---

## 一、Unity 命令行构建

### 1.1 基础命令行构建

```bash
# Unity 命令行构建基本格式
/path/to/Unity -batchmode -quit \
  -projectPath /path/to/project \
  -executeMethod BuildScript.BuildAndroid \
  -logFile /path/to/build.log
```

### 1.2 构建脚本设计

```csharp
using UnityEditor;
using UnityEditor.Build.Reporting;
using System;
using System.IO;

/// <summary>
/// 命令行构建入口
/// 通过 -executeMethod BuildScript.Build 调用
/// </summary>
public static class BuildScript
{
    // 构建参数（从命令行参数或环境变量读取）
    private static BuildConfig _config;
    
    [MenuItem("Build/Build Android Debug")]
    public static void BuildAndroidDebug()
    {
        Build(new BuildConfig
        {
            Target = BuildTarget.Android,
            IsDebug = true,
            OutputPath = "Builds/Android/debug.apk"
        });
    }
    
    // 命令行调用入口（从环境变量读取配置）
    public static void BuildFromCommandLine()
    {
        var config = ReadConfigFromEnvironment();
        int result = Build(config);
        
        // 返回非零退出码表示失败（CI 系统会检测这个）
        EditorApplication.Exit(result);
    }
    
    private static int Build(BuildConfig config)
    {
        Console.WriteLine($"[Build] Starting build: {config.Target}, Debug={config.IsDebug}");
        Console.WriteLine($"[Build] Output: {config.OutputPath}");
        Console.WriteLine($"[Build] Version: {config.AppVersion}");
        
        // 配置 PlayerSettings
        ApplyPlayerSettings(config);
        
        // 获取所有场景
        string[] scenes = GetBuildScenes();
        
        // 构建配置
        var buildOptions = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = config.OutputPath,
            target = config.Target,
            options = config.IsDebug 
                ? BuildOptions.Development | BuildOptions.AllowDebugging 
                : BuildOptions.None
        };
        
        // 执行构建
        var report = BuildPipeline.BuildPlayer(buildOptions);
        var summary = report.summary;
        
        Console.WriteLine($"[Build] Result: {summary.result}");
        Console.WriteLine($"[Build] Duration: {summary.totalTime}");
        Console.WriteLine($"[Build] Size: {summary.totalSize / 1024 / 1024}MB");
        
        if (summary.result == BuildResult.Succeeded)
        {
            Console.WriteLine("[Build] ✅ Build succeeded");
            return 0;
        }
        else
        {
            Console.WriteLine($"[Build] ❌ Build failed: {summary.totalErrors} errors");
            return 1;
        }
    }
    
    private static void ApplyPlayerSettings(BuildConfig config)
    {
        // 设置版本号
        PlayerSettings.bundleVersion = config.AppVersion;
        
        if (config.Target == BuildTarget.Android)
        {
            PlayerSettings.Android.bundleVersionCode = config.BuildNumber;
            
            // 签名配置
            if (!config.IsDebug)
            {
                PlayerSettings.Android.keystoreName = config.KeystorePath;
                PlayerSettings.Android.keystorePass = config.KeystorePassword;
                PlayerSettings.Android.keyaliasName = config.KeyAlias;
                PlayerSettings.Android.keyaliasPass = config.KeyAliasPassword;
            }
            
            // 构建类型
            PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, 
                ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = 
                AndroidArchitecture.ARMv7 | AndroidArchitecture.ARM64;
        }
        else if (config.Target == BuildTarget.iOS)
        {
            PlayerSettings.iOS.buildNumber = config.BuildNumber.ToString();
        }
    }
    
    private static string[] GetBuildScenes()
    {
        return EditorBuildSettings.scenes
            .Where(s => s.enabled)
            .Select(s => s.path)
            .ToArray();
    }
    
    private static BuildConfig ReadConfigFromEnvironment()
    {
        return new BuildConfig
        {
            Target = Enum.Parse<BuildTarget>(
                GetEnvOrDefault("BUILD_TARGET", "Android")),
            IsDebug = GetEnvOrDefault("BUILD_DEBUG", "false") == "true",
            AppVersion = GetEnvOrDefault("APP_VERSION", "1.0.0"),
            BuildNumber = int.Parse(GetEnvOrDefault("BUILD_NUMBER", "1")),
            OutputPath = GetEnvOrDefault("OUTPUT_PATH", "Builds/output"),
            KeystorePath = GetEnvOrDefault("KEYSTORE_PATH", ""),
            KeystorePassword = GetEnvOrDefault("KEYSTORE_PASSWORD", ""),
            KeyAlias = GetEnvOrDefault("KEY_ALIAS", ""),
            KeyAliasPassword = GetEnvOrDefault("KEY_ALIAS_PASSWORD", ""),
        };
    }
    
    private static string GetEnvOrDefault(string key, string defaultValue)
        => Environment.GetEnvironmentVariable(key) ?? defaultValue;
}

public class BuildConfig
{
    public BuildTarget Target;
    public bool IsDebug;
    public string AppVersion;
    public int BuildNumber;
    public string OutputPath;
    public string KeystorePath;
    public string KeystorePassword;
    public string KeyAlias;
    public string KeyAliasPassword;
}
```

---

## 二、GitHub Actions 流水线

### 2.1 基础 CI 配置

```yaml
# .github/workflows/build.yml
name: Unity Build

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  # 代码质量检查（快速，先跑）
  lint:
    name: Code Quality Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Check for TODO/FIXME in production code
        run: |
          # 检查生产代码中是否有未处理的 TODO
          if grep -r "TODO\|FIXME" Assets/Scripts/GameLogic/ --include="*.cs"; then
            echo "Found TODO/FIXME in production code"
            exit 1
          fi
      
      - name: Check file encoding
        run: |
          # 确保所有 C# 文件是 UTF-8 编码
          find Assets/Scripts -name "*.cs" -exec file {} \; | grep -v "UTF-8" && exit 1 || true

  # 单元测试
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true  # 如果使用 Git LFS
      
      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-test-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
          restore-keys: Library-
      
      - name: Run Unity Tests
        uses: game-ci/unity-test-runner@v4
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
          UNITY_EMAIL: ${{ secrets.UNITY_EMAIL }}
          UNITY_PASSWORD: ${{ secrets.UNITY_PASSWORD }}
        with:
          projectPath: .
          testMode: EditMode
          coverageOptions: generateAdditionalMetrics;generateHtmlReport
          
      - name: Upload Test Results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: Test Results
          path: artifacts/
  
  # Android 构建
  build-android:
    name: Build Android
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/develop'
    
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true
      
      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-android-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
          restore-keys: Library-
      
      - name: Build Android APK
        uses: game-ci/unity-builder@v4
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
          UNITY_EMAIL: ${{ secrets.UNITY_EMAIL }}
          UNITY_PASSWORD: ${{ secrets.UNITY_PASSWORD }}
        with:
          targetPlatform: Android
          buildMethod: BuildScript.BuildFromCommandLine
          versioning: Semantic
          androidExportType: androidPackage
          androidKeystoreName: game.keystore
          androidKeystoreBase64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
          androidKeystorePass: ${{ secrets.ANDROID_KEYSTORE_PASS }}
          androidKeyaliasName: ${{ secrets.ANDROID_KEYALIAS_NAME }}
          androidKeyaliasPass: ${{ secrets.ANDROID_KEYALIAS_PASS }}
      
      - name: Upload APK
        uses: actions/upload-artifact@v3
        with:
          name: android-apk
          path: build/Android/*.apk
          
      - name: Notify Success
        if: success()
        uses: 8398a7/action-slack@v3
        with:
          status: success
          text: "✅ Android 构建成功！APK 已上传到 Artifacts"
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}
```

### 2.2 多环境配置管理

```yaml
# 环境矩阵构建（一次构建多个环境）
build:
  strategy:
    matrix:
      environment: [dev, staging, production]
      platform: [Android, iOS]
  
  steps:
    - name: Set environment variables
      run: |
        case "${{ matrix.environment }}" in
          dev)
            echo "SERVER_URL=https://dev-api.game.com" >> $GITHUB_ENV
            echo "IS_DEBUG=true" >> $GITHUB_ENV
            ;;
          staging)
            echo "SERVER_URL=https://staging-api.game.com" >> $GITHUB_ENV
            echo "IS_DEBUG=false" >> $GITHUB_ENV
            ;;
          production)
            echo "SERVER_URL=https://api.game.com" >> $GITHUB_ENV
            echo "IS_DEBUG=false" >> $GITHUB_ENV
            ;;
        esac
```

---

## 三、构建缓存优化

### 3.1 Unity Library 缓存

```yaml
# Unity Library 目录包含编译结果，缓存后可大幅减少构建时间
# 未缓存：15~30 分钟（冷启动）
# 已缓存：3~5 分钟

- name: Cache Unity Library
  uses: actions/cache@v3
  with:
    path: Library
    # 缓存 key：当资源变化时失效，重新构建缓存
    key: Library-${{ matrix.targetPlatform }}-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
    restore-keys: |
      Library-${{ matrix.targetPlatform }}-
      Library-
```

### 3.2 增量 AssetBundle 构建

```csharp
/// <summary>
/// 增量 AB 构建：只重新构建发生变化的 Bundle
/// </summary>
public static class IncrementalBundleBuilder
{
    private const string MANIFEST_PATH = "Builds/ABManifest.json";
    
    public static void BuildIncrementally()
    {
        // 读取上次构建的 Manifest
        var lastManifest = LoadLastManifest();
        
        // 计算哪些资源发生了变化
        var changedAssets = GetChangedAssets(lastManifest);
        
        if (changedAssets.Count == 0)
        {
            Debug.Log("[Build] 没有资源变化，跳过 AB 构建");
            return;
        }
        
        Debug.Log($"[Build] {changedAssets.Count} 个资源发生变化，重新构建相关 Bundle");
        
        // 只重建包含了变化资源的 Bundle
        var bundlesToRebuild = GetAffectedBundles(changedAssets);
        BuildSpecificBundles(bundlesToRebuild);
        
        // 更新 Manifest
        SaveManifest(CalculateCurrentManifest());
    }
    
    private static Dictionary<string, string> GetChangedAssets(Dictionary<string, string> lastManifest)
    {
        var changed = new Dictionary<string, string>();
        
        // 计算所有资源的 MD5，与上次对比
        foreach (var assetPath in GetAllAddressableAssets())
        {
            string currentHash = CalculateFileHash(assetPath);
            
            if (!lastManifest.TryGetValue(assetPath, out string lastHash) || 
                lastHash != currentHash)
            {
                changed[assetPath] = currentHash;
            }
        }
        
        return changed;
    }
    
    private static string CalculateFileHash(string path)
    {
        using var md5 = System.Security.Cryptography.MD5.Create();
        using var stream = File.OpenRead(path);
        var hash = md5.ComputeHash(stream);
        return BitConverter.ToString(hash).Replace("-", "").ToLower();
    }
}
```

---

## 四、自动化测试

### 4.1 Unity Test Framework 使用

```csharp
// Edit Mode Test（不需要 Unity 运行时）
using NUnit.Framework;

[TestFixture]
public class DamageCalculatorTests
{
    private DamageCalculator _calculator;
    private MockBuffSystem _mockBuff;
    private MockEquipmentSystem _mockEquip;
    
    [SetUp]
    public void Setup()
    {
        _mockBuff = new MockBuffSystem();
        _mockEquip = new MockEquipmentSystem();
        _calculator = new DamageCalculator(_mockBuff, _mockEquip);
    }
    
    [Test]
    public void Calculate_NoBuff_ReturnsBaseMinusDefense()
    {
        // Arrange
        _mockBuff.AttackMultiplier = 1f;
        _mockEquip.WeaponBonus = 0;
        
        // Act
        int damage = _calculator.Calculate(baseAttack: 100, targetDefense: 20);
        
        // Assert
        Assert.AreEqual(80, damage);
    }
    
    [Test]
    public void Calculate_WithAttackBuff_IncreasedDamage()
    {
        _mockBuff.AttackMultiplier = 1.5f;
        
        int damage = _calculator.Calculate(100, 20);
        
        // (100 * 1.5) - 20 = 130
        Assert.AreEqual(130, damage);
    }
    
    [Test]
    public void Calculate_HighDefense_MinimumOneDamage()
    {
        // 高防御不应导致伤害为 0 或负数
        int damage = _calculator.Calculate(baseAttack: 10, targetDefense: 1000);
        
        Assert.GreaterOrEqual(damage, 1);
    }
    
    // 参数化测试
    [TestCase(100, 0, 100)]
    [TestCase(100, 50, 50)]
    [TestCase(100, 100, 1)] // 最低 1 点伤害
    [TestCase(50, 20, 30)]
    public void Calculate_ParameterizedCases(int attack, int defense, int expectedMin)
    {
        _mockBuff.AttackMultiplier = 1f;
        int damage = _calculator.Calculate(attack, defense);
        Assert.GreaterOrEqual(damage, expectedMin);
    }
}

// Play Mode Test（需要 Unity 运行时，测试 MonoBehaviour 等）
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using System.Collections;

[TestFixture]
public class ObjectPoolTests
{
    private ObjectPool<TestPoolObject> _pool;
    private TestPoolObject _prefab;
    
    [SetUp]
    public void Setup()
    {
        var go = new GameObject("TestPrefab");
        _prefab = go.AddComponent<TestPoolObject>();
        _pool = new ObjectPool<TestPoolObject>(_prefab, initialSize: 5);
    }
    
    [TearDown]
    public void TearDown()
    {
        // 清理
    }
    
    [UnityTest]
    public IEnumerator Pool_GetAndReturn_ReusesSameObject()
    {
        var obj1 = _pool.Get();
        _pool.Return(obj1);
        
        yield return null; // 等一帧
        
        var obj2 = _pool.Get();
        
        Assert.AreSame(obj1, obj2, "对象池应该复用对象");
    }
    
    [UnityTest]
    public IEnumerator Pool_GetBeyondInitialSize_CreatesNew()
    {
        var objects = new TestPoolObject[10];
        for (int i = 0; i < 10; i++)
        {
            objects[i] = _pool.Get();
            Assert.NotNull(objects[i]);
        }
        
        yield return null;
        
        Assert.AreEqual(10, _pool.ActiveCount);
    }
}
```

### 4.2 构建后自动化测试

```yaml
# 构建完成后，在真机或模拟器上运行冒烟测试
smoke-test:
  needs: build-android
  runs-on: macos-latest
  
  steps:
    - name: Download APK
      uses: actions/download-artifact@v3
      with:
        name: android-apk
    
    - name: Setup Android Emulator
      run: |
        # 创建 Android 模拟器
        echo y | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
          "system-images;android-31;google_apis;x86_64"
        echo no | $ANDROID_HOME/tools/bin/avdmanager \
          create avd -n test_avd -k "system-images;android-31;google_apis;x86_64"
        $ANDROID_HOME/emulator/emulator -avd test_avd -no-audio -no-window &
        adb wait-for-device
    
    - name: Install APK
      run: adb install -r *.apk
    
    - name: Run Smoke Tests
      run: |
        # 启动游戏
        adb shell am start -n com.yourgame.app/.MainActivity
        sleep 5
        
        # 检查是否崩溃
        CRASHES=$(adb logcat -d | grep "FATAL EXCEPTION" | wc -l)
        if [ "$CRASHES" -gt "0" ]; then
          echo "❌ 游戏启动时发生崩溃"
          adb logcat -d > crash.log
          exit 1
        fi
        
        echo "✅ 冒烟测试通过"
    
    - name: Upload Crash Log
      if: failure()
      uses: actions/upload-artifact@v3
      with:
        name: crash-log
        path: crash.log
```

---

## 五、多渠道打包

### 5.1 渠道化配置管理

```csharp
/// <summary>
/// 渠道配置（每个渠道有不同的参数）
/// </summary>
[Serializable]
public class ChannelConfig
{
    public string ChannelId;
    public string ChannelName;
    public string PackageName;      // 包名（部分渠道要求不同包名）
    public string PaymentSdkKey;    // 支付 SDK 密钥
    public string AnalyticsId;      // 统计 ID
    public bool EnableDebugLog;     // 是否开启调试日志
    public BuildTarget Target;
}

/// <summary>
/// 渠道构建器：根据渠道配置生成对应的安装包
/// </summary>
public static class ChannelBuilder
{
    private static readonly ChannelConfig[] CHANNELS = new[]
    {
        new ChannelConfig
        {
            ChannelId = "official",
            PackageName = "com.yourstudio.yourgame",
            Target = BuildTarget.Android
        },
        new ChannelConfig
        {
            ChannelId = "xiaomi",
            PackageName = "com.yourstudio.yourgame.xiaomi",
            Target = BuildTarget.Android
        },
        new ChannelConfig
        {
            ChannelId = "ios_appstore",
            PackageName = "com.yourstudio.yourgame",
            Target = BuildTarget.iOS
        }
    };
    
    public static void BuildAllChannels()
    {
        foreach (var channel in CHANNELS)
            BuildChannel(channel);
    }
    
    public static void BuildChannel(ChannelConfig channel)
    {
        Console.WriteLine($"[Build] 开始构建渠道: {channel.ChannelId}");
        
        // 应用渠道特定配置
        PlayerSettings.applicationIdentifier = channel.PackageName;
        
        // 生成渠道配置文件（游戏运行时读取）
        GenerateChannelConfigFile(channel);
        
        // 构建
        string outputPath = $"Builds/{channel.Target}/{channel.ChannelId}";
        BuildScript.Build(new BuildConfig
        {
            Target = channel.Target,
            OutputPath = outputPath,
            IsDebug = false
        });
        
        Console.WriteLine($"[Build] 渠道 {channel.ChannelId} 构建完成: {outputPath}");
    }
    
    private static void GenerateChannelConfigFile(ChannelConfig channel)
    {
        // 生成运行时读取的渠道配置
        var configJson = JsonUtility.ToJson(channel);
        File.WriteAllText(
            "Assets/Resources/ChannelConfig.json",
            configJson);
        AssetDatabase.Refresh();
    }
}
```

---

## 六、构建监控与通知

### 6.1 构建质量指标

```csharp
/// <summary>
/// 构建报告：收集并汇报构建关键指标
/// </summary>
public static class BuildReporter
{
    [PostProcessBuild(int.MaxValue)] // 构建完成后调用
    public static void OnPostProcessBuild(BuildTarget target, string pathToBuiltProject)
    {
        var report = new BuildReport
        {
            BuildTime = DateTime.Now,
            Target = target.ToString(),
            AppVersion = PlayerSettings.bundleVersion,
        };
        
        // 收集构建大小信息
        if (File.Exists(pathToBuiltProject))
        {
            var info = new FileInfo(pathToBuiltProject);
            report.ApkSizeMB = info.Length / (1024f * 1024f);
        }
        
        // 收集 Shader 变体信息
        // (需要在 ShaderVariantCollection 中统计)
        
        // 输出报告
        Console.WriteLine($"[Build Report]");
        Console.WriteLine($"  Version: {report.AppVersion}");
        Console.WriteLine($"  Target: {report.Target}");
        Console.WriteLine($"  APK Size: {report.ApkSizeMB:F1}MB");
        
        // 检查包体大小阈值
        if (report.ApkSizeMB > 200f)
        {
            Console.WriteLine("⚠️ WARNING: APK 超过 200MB，可能影响下载转化率");
        }
        
        // 发送到监控系统
        SendToMonitoring(report);
    }
    
    private static void SendToMonitoring(BuildReport report)
    {
        // 发送到内部监控系统（如飞书/企业微信 webhook）
        var json = JsonUtility.ToJson(report);
        
        // 使用 WebRequest 发送
        var client = new System.Net.WebClient();
        client.Headers.Add("Content-Type", "application/json");
        
        try
        {
            client.UploadString(
                Environment.GetEnvironmentVariable("BUILD_WEBHOOK_URL") ?? "",
                json);
        }
        catch (Exception e)
        {
            Console.WriteLine($"Failed to send build report: {e.Message}");
        }
    }
}

[Serializable]
public class BuildReport
{
    public DateTime BuildTime;
    public string Target;
    public string AppVersion;
    public float ApkSizeMB;
    public int ShaderVariantCount;
    public float BuildDurationMinutes;
}
```

---

## 总结

一套完整的游戏 CI/CD 体系应该包含：

```
代码提交
  → 静态检查（代码规范、潜在 Bug）
  → 单元测试（确保核心逻辑正确）
  → 构建（生成安装包）
  → 冒烟测试（确保基本功能可用）
  → 上传 QA（QA 团队验收）
  → 发布（内测/公测/正式）
```

**技术 Leader 的任务**：设计并维护这套流水线，让团队的每次代码提交都能快速得到反馈。

> "如果你怕提交代码，说明你没有足够的自动化测试。"

> **下一篇**：[Shader 性能优化实战：移动端图形调优全指南]
