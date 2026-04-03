---
title: 游戏自动化UI测试框架：从Unity TestRunner到录制回放完整实战
published: 2026-04-03
description: 深度解析游戏客户端自动化UI测试体系构建，涵盖Unity Test Framework、PlayMode测试、UI测试录制回放、截图对比回归测试、CI集成与测试报告，帮助团队建立稳定的质量保障流程
tags: [自动化测试, Unity, TestRunner, UI测试, CI/CD, 质量保障]
category: 工程化
draft: false
---

# 游戏自动化UI测试框架：从Unity TestRunner到录制回放完整实战

## 1. 为什么游戏需要自动化UI测试

### 1.1 游戏测试的痛点

```
传统手工测试的问题：
  ❌ 每次版本迭代都需要重复执行相同的回归测试
  ❌ 人工测试遗漏率高，UI状态组合爆炸（10个开关 = 1024种状态）
  ❌ 测试反馈周期长，Bug发现太晚（开发→QA→修复→再测试）
  ❌ 多平台适配测试成本极高（iOS/Android/PC）

自动化测试解决的问题：
  ✓ 每次提交自动触发回归测试（CI集成）
  ✓ 截图对比发现像素级UI变化
  ✓ 7×24小时无人值守运行
  ✓ 测试报告自动生成，精确定位Bug
```

### 1.2 游戏自动化测试层次

```
测试金字塔（游戏版）：

    ┌──────────────────────┐
    │    端到端测试 (E2E)   │  少量：完整游戏流程（登录→主界面→游戏）
    ├──────────────────────┤
    │   集成测试 (PlayMode) │  中量：系统交互（战斗+UI+网络）
    ├──────────────────────┤
    │   单元测试 (EditMode) │  大量：独立逻辑（公式计算、状态机、数据解析）
    └──────────────────────┘
    
建议比例：
  单元测试 70%，集成测试 20%，E2E测试 10%
```

---

## 2. Unity Test Framework 基础

### 2.1 项目配置

```
安装步骤：
1. Package Manager → Unity Test Framework（已内置）
2. Window → General → Test Runner 打开测试窗口
3. 创建测试程序集：

   Assets/Tests/
   ├── EditMode/           ← EditMode测试（不运行场景）
   │   ├── EditModeTests.asmdef
   │   └── GameLogicTests.cs
   └── PlayMode/           ← PlayMode测试（在场景中运行）
       ├── PlayModeTests.asmdef
       └── UIFlowTests.cs

asmdef配置（PlayModeTests.asmdef）：
{
    "name": "PlayModeTests",
    "references": ["UnityEngine.TestRunner", "UnityEditor.TestRunner"],
    "includePlatforms": [],
    "excludePlatforms": [],
    "allowUnsafeCode": false,
    "autoReferenced": false,
    "defineConstraints": [],
    "versionDefines": [],
    "noEngineReferences": false
}
```

### 2.2 EditMode 单元测试

```csharp
// 测试游戏逻辑（不依赖场景）
using NUnit.Framework;
using UnityEngine;

[TestFixture]
public class GameLogicTests
{
    // ============ 伤害计算测试 ============
    
    [Test]
    public void DamageCalculator_BasicAttack_ReturnsCorrectDamage()
    {
        // Arrange
        var calculator = new DamageCalculator();
        int attack = 100;
        int defense = 30;
        
        // Act
        int damage = calculator.Calculate(attack, defense);
        
        // Assert
        Assert.AreEqual(70, damage, "基础伤害计算错误");
    }

    [Test]
    [TestCase(100, 0, 100)]    // 无防御
    [TestCase(100, 100, 1)]    // 满防御（最低1点伤害）
    [TestCase(50, 30, 20)]     // 普通情况
    public void DamageCalculator_VariousDefense_ReturnsExpected(
        int attack, int defense, int expected)
    {
        var calc = new DamageCalculator();
        Assert.AreEqual(expected, calc.Calculate(attack, defense));
    }

    // ============ 背包系统测试 ============
    
    [Test]
    public void Inventory_AddItem_IncreasesCount()
    {
        var inventory = new Inventory(capacity: 20);
        var item = new Item { id = 1001, name = "治疗药水", stackable = true };
        
        inventory.AddItem(item, 5);
        
        Assert.AreEqual(5, inventory.GetItemCount(1001));
    }

    [Test]
    public void Inventory_AddItem_ExceedsCapacity_ThrowsException()
    {
        var inventory = new Inventory(capacity: 1);
        inventory.AddItem(new Item { id = 1001, stackable = false }, 1);
        
        Assert.Throws<InventoryFullException>(() =>
        {
            inventory.AddItem(new Item { id = 1002, stackable = false }, 1);
        });
    }

    // ============ 状态机测试 ============
    
    [Test]
    public void CharacterStateMachine_Attack_TransitionsCorrectly()
    {
        var fsm = new CharacterStateMachine();
        fsm.Initialize(CharacterState.Idle);
        
        fsm.TriggerAttack();
        
        Assert.AreEqual(CharacterState.Attacking, fsm.CurrentState);
    }

    [Test]
    public void CharacterStateMachine_AttackWhileDead_StaysInDeadState()
    {
        var fsm = new CharacterStateMachine();
        fsm.Initialize(CharacterState.Dead);
        
        fsm.TriggerAttack(); // 死亡状态不应能攻击
        
        Assert.AreEqual(CharacterState.Dead, fsm.CurrentState, "死亡状态不应转移到攻击状态");
    }
}
```

### 2.3 PlayMode 集成测试

```csharp
// 测试UI交互流程（在场景中运行）
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using UnityEngine.UI;
using System.Collections;

[TestFixture]
public class MainMenuUITests
{
    private GameObject _mainMenuGO;
    private MainMenuController _mainMenu;
    private Canvas _canvas;

    [SetUp]
    public void SetUp()
    {
        // 创建测试场景
        _canvas = new GameObject("Canvas").AddComponent<Canvas>();
        _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        _canvas.gameObject.AddComponent<CanvasScaler>();
        _canvas.gameObject.AddComponent<GraphicRaycaster>();
        
        // 加载主界面预制体
        var prefab = Resources.Load<GameObject>("UI/MainMenu");
        _mainMenuGO = Object.Instantiate(prefab, _canvas.transform);
        _mainMenu = _mainMenuGO.GetComponent<MainMenuController>();
    }

    [TearDown]
    public void TearDown()
    {
        if (_canvas != null) Object.DestroyImmediate(_canvas.gameObject);
    }

    [UnityTest]
    public IEnumerator StartButton_Click_ShowsLoadingPanel()
    {
        // Arrange
        var startButton = _mainMenuGO.transform.Find("StartButton")?.GetComponent<Button>();
        Assert.IsNotNull(startButton, "找不到开始游戏按钮");

        var loadingPanel = _mainMenuGO.transform.Find("LoadingPanel")?.gameObject;
        Assert.IsNotNull(loadingPanel, "找不到加载面板");
        
        // 初始状态：加载面板隐藏
        Assert.IsFalse(loadingPanel.activeSelf, "初始状态加载面板应该是隐藏的");

        // Act - 点击开始按钮
        startButton.onClick.Invoke();
        
        // 等待一帧
        yield return null;
        
        // Assert - 加载面板应该显示
        Assert.IsTrue(loadingPanel.activeSelf, "点击开始按钮后加载面板应该显示");
    }

    [UnityTest]
    public IEnumerator SettingsButton_OpenClose_Works()
    {
        var settingsButton = _mainMenuGO.transform.Find("SettingsButton")?.GetComponent<Button>();
        var settingsPanel  = _mainMenuGO.transform.Find("SettingsPanel")?.gameObject;
        var closeButton    = settingsPanel?.transform.Find("CloseButton")?.GetComponent<Button>();
        
        Assert.IsNotNull(settingsButton, "找不到设置按钮");
        Assert.IsNotNull(settingsPanel, "找不到设置面板");

        // 打开设置
        settingsButton.onClick.Invoke();
        yield return null;
        Assert.IsTrue(settingsPanel.activeSelf, "设置面板应该已打开");

        // 关闭设置
        closeButton?.onClick.Invoke();
        yield return null;
        Assert.IsFalse(settingsPanel.activeSelf, "设置面板应该已关闭");
    }

    [UnityTest]
    public IEnumerator LoginFlow_ValidCredentials_EntersMainLobby()
    {
        // 模拟登录流程
        var loginPanel = _mainMenuGO.transform.Find("LoginPanel");
        var usernameInput = loginPanel?.Find("UsernameInput")?.GetComponent<InputField>();
        var passwordInput = loginPanel?.Find("PasswordInput")?.GetComponent<InputField>();
        var loginButton   = loginPanel?.Find("LoginButton")?.GetComponent<Button>();

        if (usernameInput == null || passwordInput == null || loginButton == null)
        {
            Assert.Inconclusive("登录界面组件未找到，跳过测试");
            yield break;
        }

        // 输入凭据
        usernameInput.text = "testuser";
        passwordInput.text = "testpass";
        loginButton.onClick.Invoke();

        // 等待异步登录（最多5秒）
        float timeout = 5f;
        while (timeout > 0 && !_mainMenu.IsInLobby)
        {
            yield return new WaitForSeconds(0.1f);
            timeout -= 0.1f;
        }

        Assert.IsTrue(_mainMenu.IsInLobby, "登录后应进入大厅");
    }
}
```

---

## 3. UI 自动化测试框架核心设计

### 3.1 UI 元素定位器

```csharp
/// <summary>
/// 统一的UI元素查找器
/// 支持路径、Tag、组件类型多种方式定位
/// </summary>
public static class UIFinder
{
    /// <summary>
    /// 通过路径查找UI元素（支持等待出现）
    /// </summary>
    public static IEnumerator FindElement(
        string path,
        System.Action<GameObject> onFound,
        float timeout = 5f)
    {
        float elapsed = 0;
        GameObject found = null;
        
        while (elapsed < timeout)
        {
            // 尝试通过路径查找
            found = GameObject.Find(path);
            
            if (found != null && found.activeInHierarchy)
            {
                onFound?.Invoke(found);
                yield break;
            }
            
            yield return new WaitForSeconds(0.1f);
            elapsed += 0.1f;
        }
        
        Debug.LogWarning($"[UIFinder] 超时：找不到元素 {path}");
    }

    /// <summary>
    /// 等待文本出现在UI中
    /// </summary>
    public static IEnumerator WaitForText(
        string expectedText,
        float timeout = 10f)
    {
        float elapsed = 0;
        
        while (elapsed < timeout)
        {
            // 查找所有Text组件
            var texts = Object.FindObjectsOfType<TMPro.TextMeshProUGUI>();
            foreach (var text in texts)
            {
                if (text.text.Contains(expectedText))
                    yield break;
            }
            
            var legacyTexts = Object.FindObjectsOfType<Text>();
            foreach (var text in legacyTexts)
            {
                if (text.text.Contains(expectedText))
                    yield break;
            }
            
            yield return new WaitForSeconds(0.1f);
            elapsed += 0.1f;
        }
        
        Assert.Fail($"超时：未找到包含文本 '{expectedText}' 的UI元素");
    }

    /// <summary>
    /// 模拟点击UI按钮
    /// </summary>
    public static void ClickButton(string path)
    {
        var go = GameObject.Find(path);
        Assert.IsNotNull(go, $"未找到按钮：{path}");
        
        var button = go.GetComponent<Button>();
        Assert.IsNotNull(button, $"对象没有Button组件：{path}");
        Assert.IsTrue(button.interactable, $"按钮不可交互：{path}");
        
        button.onClick.Invoke();
    }

    /// <summary>
    /// 输入文本到InputField
    /// </summary>
    public static void TypeText(string path, string text)
    {
        var go = GameObject.Find(path);
        Assert.IsNotNull(go, $"未找到InputField：{path}");
        
        var inputField = go.GetComponent<InputField>() as TMPro.TMP_InputField;
        if (inputField != null)
        {
            inputField.text = text;
        }
        else
        {
            var legacyInput = go.GetComponent<InputField>();
            Assert.IsNotNull(legacyInput, $"对象没有InputField组件：{path}");
            legacyInput.text = text;
        }
    }
}
```

### 3.2 截图对比回归测试

```csharp
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using System.Collections;
using System.IO;

/// <summary>
/// 截图对比回归测试
/// 对比当前截图与基准截图，检测UI变化
/// </summary>
public class UIScreenshotRegressionTests
{
    private const string BASELINE_PATH = "Assets/Tests/Screenshots/Baseline/";
    private const string ACTUAL_PATH   = "Assets/Tests/Screenshots/Actual/";
    private const float DIFF_THRESHOLD = 0.02f; // 允许2%的像素差异

    [UnityTest]
    public IEnumerator MainMenu_Layout_MatchesBaseline()
    {
        // 加载主界面场景
        yield return LoadScene("MainMenu");
        yield return new WaitForSeconds(1f); // 等待动画完成

        // 截图
        string screenshotName = "MainMenu_Layout";
        yield return CaptureAndCompare(screenshotName);
    }

    [UnityTest]
    public IEnumerator ShopPanel_OpenState_MatchesBaseline()
    {
        yield return LoadScene("MainMenu");
        
        // 点击商城按钮
        UIFinder.ClickButton("Canvas/BottomBar/ShopButton");
        yield return new WaitForSeconds(0.5f); // 等待打开动画
        
        yield return CaptureAndCompare("ShopPanel_Open");
    }

    private IEnumerator LoadScene(string sceneName)
    {
        yield return UnityEngine.SceneManagement.SceneManager.LoadSceneAsync(sceneName);
    }

    private IEnumerator CaptureAndCompare(string testName)
    {
        // 截图
        yield return new WaitForEndOfFrame();
        
        var screenshot = ScreenCapture.CaptureScreenshotAsTexture();
        string actualPath = $"{ACTUAL_PATH}{testName}.png";
        
        Directory.CreateDirectory(ACTUAL_PATH);
        File.WriteAllBytes(actualPath, screenshot.EncodeToPNG());

        // 比较
        string baselinePath = $"{BASELINE_PATH}{testName}.png";
        
        if (!File.Exists(baselinePath))
        {
            // 首次运行：保存为基准
            Directory.CreateDirectory(BASELINE_PATH);
            File.WriteAllBytes(baselinePath, screenshot.EncodeToPNG());
            Debug.Log($"[Screenshot] 已保存基准截图：{testName}");
            Object.Destroy(screenshot);
            yield break;
        }

        // 加载基准截图
        byte[] baselineBytes = File.ReadAllBytes(baselinePath);
        var baseline = new Texture2D(2, 2);
        baseline.LoadImage(baselineBytes);

        // 计算差异
        float diffRatio = CalculatePixelDiff(screenshot, baseline);
        
        Object.Destroy(screenshot);
        Object.Destroy(baseline);

        // 如果差异超过阈值，生成差异图并报告
        if (diffRatio > DIFF_THRESHOLD)
        {
            Assert.Fail($"[Screenshot] {testName} 与基准截图差异过大：{diffRatio:P2}（阈值：{DIFF_THRESHOLD:P0}）\n" +
                        $"实际截图：{Path.GetFullPath(actualPath)}");
        }
        else
        {
            Debug.Log($"[Screenshot] {testName} 截图对比通过（差异：{diffRatio:P2}）");
        }
    }

    private float CalculatePixelDiff(Texture2D actual, Texture2D baseline)
    {
        if (actual.width != baseline.width || actual.height != baseline.height)
        {
            Debug.LogWarning("[Screenshot] 尺寸不匹配，跳过像素对比");
            return 1f;
        }

        Color[] actualPixels   = actual.GetPixels();
        Color[] baselinePixels = baseline.GetPixels();
        
        int diffCount = 0;
        float colorThreshold = 0.05f; // 颜色差异容忍值

        for (int i = 0; i < actualPixels.Length; i++)
        {
            Color diff = actualPixels[i] - baselinePixels[i];
            float magnitude = Mathf.Abs(diff.r) + Mathf.Abs(diff.g) + Mathf.Abs(diff.b);
            
            if (magnitude > colorThreshold)
                diffCount++;
        }

        return (float)diffCount / actualPixels.Length;
    }
}
```

---

## 4. UI 测试录制与回放系统

### 4.1 测试录制器

```csharp
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;
using System.Text;
using System.IO;
using Newtonsoft.Json;

/// <summary>
/// UI操作录制器
/// 记录用户的点击、输入、滑动操作，生成可回放的测试脚本
/// </summary>
public class UITestRecorder : MonoBehaviour, IPointerClickHandler, IBeginDragHandler, IDragHandler
{
    [System.Serializable]
    public class UIAction
    {
        public string type;           // click, input, drag, wait
        public string targetPath;     // UI元素路径
        public string inputText;      // 输入内容（type=input时）
        public Vector2 position;      // 屏幕位置
        public float timestamp;       // 时间戳
        public string expectedText;   // 期望看到的文字（用于断言）
    }

    private readonly List<UIAction> _recordedActions = new();
    private float _startTime;
    private bool _isRecording = false;
    private string _outputPath = "Assets/Tests/Recorded/";

    [Header("录制控制")]
    [SerializeField] private KeyCode startRecordKey = KeyCode.F9;
    [SerializeField] private KeyCode stopRecordKey  = KeyCode.F10;
    [SerializeField] private KeyCode addAssertKey   = KeyCode.F11; // 添加文本断言

    private void Update()
    {
        if (Input.GetKeyDown(startRecordKey)) StartRecording();
        if (Input.GetKeyDown(stopRecordKey))  StopRecording();
        if (Input.GetKeyDown(addAssertKey))   AddTextAssertion();
    }

    public void StartRecording()
    {
        _recordedActions.Clear();
        _startTime = Time.realtimeSinceStartup;
        _isRecording = true;
        Debug.Log("[Recorder] 开始录制 UI 测试，按F10停止");
    }

    public void StopRecording()
    {
        if (!_isRecording) return;
        _isRecording = false;
        
        // 导出为JSON和C#测试代码
        ExportToJson();
        ExportToCSharp();
        Debug.Log($"[Recorder] 录制完成，共 {_recordedActions.Count} 个操作");
    }

    private void AddTextAssertion()
    {
        if (!_isRecording) return;
        
        // 自动捕获当前可见的重要文本
        var texts = FindObjectsOfType<TMPro.TextMeshProUGUI>();
        foreach (var text in texts)
        {
            if (!string.IsNullOrEmpty(text.text) && text.gameObject.activeInHierarchy)
            {
                _recordedActions.Add(new UIAction
                {
                    type = "assertText",
                    expectedText = text.text,
                    timestamp = Time.realtimeSinceStartup - _startTime
                });
                Debug.Log($"[Recorder] 已添加文本断言：'{text.text}'");
                break;
            }
        }
    }

    // 拦截所有UI点击事件
    public void OnPointerClick(PointerEventData eventData)
    {
        if (!_isRecording) return;

        string path = GetUIElementPath(eventData.pointerPress);
        
        _recordedActions.Add(new UIAction
        {
            type = "click",
            targetPath = path,
            position = eventData.position,
            timestamp = Time.realtimeSinceStartup - _startTime
        });
        
        Debug.Log($"[Recorder] Click: {path}");
    }

    public void OnBeginDrag(PointerEventData eventData) { }
    public void OnDrag(PointerEventData eventData) { }

    /// <summary>
    /// 外部调用：录制文本输入
    /// </summary>
    public void RecordInput(InputField inputField, string text)
    {
        if (!_isRecording) return;
        
        string path = GetUIElementPath(inputField.gameObject);
        _recordedActions.Add(new UIAction
        {
            type = "input",
            targetPath = path,
            inputText = text,
            timestamp = Time.realtimeSinceStartup - _startTime
        });
    }

    private string GetUIElementPath(GameObject go)
    {
        if (go == null) return "Unknown";
        
        var sb = new StringBuilder();
        var current = go.transform;
        
        while (current != null)
        {
            sb.Insert(0, current.name);
            if (current.parent != null)
                sb.Insert(0, "/");
            current = current.parent;
        }
        
        return sb.ToString();
    }

    private void ExportToJson()
    {
        Directory.CreateDirectory(_outputPath);
        string json = JsonConvert.SerializeObject(_recordedActions, Formatting.Indented);
        string path = $"{_outputPath}Recording_{System.DateTime.Now:yyyyMMdd_HHmm}.json";
        File.WriteAllText(path, json);
        Debug.Log($"[Recorder] JSON已保存：{path}");
    }

    private void ExportToCSharp()
    {
        var sb = new StringBuilder();
        sb.AppendLine("// 自动生成的UI测试代码");
        sb.AppendLine("// 由UITestRecorder录制生成");
        sb.AppendLine();
        sb.AppendLine("[UnityTest]");
        sb.AppendLine("public IEnumerator RecordedTest()");
        sb.AppendLine("{");

        float lastTime = 0;
        
        foreach (var action in _recordedActions)
        {
            // 添加等待
            float waitTime = action.timestamp - lastTime;
            if (waitTime > 0.2f)
                sb.AppendLine($"    yield return new WaitForSeconds({waitTime:F2}f);");

            switch (action.type)
            {
                case "click":
                    sb.AppendLine($"    UIFinder.ClickButton(\"{action.targetPath}\");");
                    break;
                case "input":
                    sb.AppendLine($"    UIFinder.TypeText(\"{action.targetPath}\", \"{action.inputText}\");");
                    break;
                case "assertText":
                    sb.AppendLine($"    yield return UIFinder.WaitForText(\"{action.expectedText}\");");
                    break;
            }

            lastTime = action.timestamp;
        }

        sb.AppendLine("}");
        
        string path = $"{_outputPath}RecordedTest_{System.DateTime.Now:yyyyMMdd_HHmm}.cs";
        File.WriteAllText(path, sb.ToString());
        Debug.Log($"[Recorder] C#测试代码已生成：{path}");
    }
}
```

### 4.2 测试回放执行器

```csharp
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;

/// <summary>
/// UI测试回放器
/// 回放录制的操作序列并验证结果
/// </summary>
public class UITestPlayback
{
    [UnityTest]
    public IEnumerator PlaybackRecordedTest_LoginFlow()
    {
        string recordingPath = "Assets/Tests/Recorded/LoginFlow.json";
        
        if (!File.Exists(recordingPath))
        {
            Assert.Inconclusive("录制文件不存在，请先录制");
            yield break;
        }

        string json = File.ReadAllText(recordingPath);
        var actions = JsonConvert.DeserializeObject<List<UITestRecorder.UIAction>>(json);

        yield return LoadScene("MainMenu");

        float playbackStart = Time.realtimeSinceStartup;

        foreach (var action in actions)
        {
            // 等待到操作时间点
            float elapsed = Time.realtimeSinceStartup - playbackStart;
            float waitTime = action.timestamp - elapsed;
            
            if (waitTime > 0)
                yield return new WaitForSeconds(waitTime);

            // 执行操作
            switch (action.type)
            {
                case "click":
                    Debug.Log($"[Playback] Click: {action.targetPath}");
                    UIFinder.ClickButton(action.targetPath);
                    break;

                case "input":
                    Debug.Log($"[Playback] Input: {action.targetPath} = {action.inputText}");
                    UIFinder.TypeText(action.targetPath, action.inputText);
                    break;

                case "assertText":
                    Debug.Log($"[Playback] Assert: '{action.expectedText}'");
                    yield return UIFinder.WaitForText(action.expectedText, timeout: 10f);
                    break;

                case "wait":
                    yield return new WaitForSeconds(0.5f);
                    break;
            }
        }

        Debug.Log("[Playback] 测试回放完成");
    }

    private IEnumerator LoadScene(string name)
    {
        yield return UnityEngine.SceneManagement.SceneManager.LoadSceneAsync(name);
        yield return new WaitForSeconds(0.5f);
    }
}
```

---

## 5. CI/CD 集成与测试报告

### 5.1 命令行运行测试

```bash
# Unity命令行运行测试（CI/CD脚本）
#!/bin/bash

UNITY_PATH="/Applications/Unity/Hub/Editor/2022.3.0f1/Unity.app/Contents/MacOS/Unity"
PROJECT_PATH="/workspace/game-project"
REPORT_PATH="/workspace/test-results"

# 运行EditMode测试
"$UNITY_PATH" \
  -batchmode \
  -runTests \
  -testPlatform editmode \
  -projectPath "$PROJECT_PATH" \
  -testResults "$REPORT_PATH/EditMode-Results.xml" \
  -logFile "$REPORT_PATH/EditMode-Log.txt" \
  -quit

# 运行PlayMode测试
"$UNITY_PATH" \
  -batchmode \
  -runTests \
  -testPlatform playmode \
  -projectPath "$PROJECT_PATH" \
  -testResults "$REPORT_PATH/PlayMode-Results.xml" \
  -logFile "$REPORT_PATH/PlayMode-Log.txt" \
  -quit

echo "测试完成，查看报告：$REPORT_PATH"
```

### 5.2 GitHub Actions CI 配置

```yaml
# .github/workflows/unity-tests.yml
name: Unity Auto Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    name: Unity Tests (${{ matrix.testMode }})
    runs-on: ubuntu-latest
    
    strategy:
      matrix:
        testMode:
          - editmode
          - playmode

    steps:
      - name: Checkout
        uses: actions/checkout@v3
        with:
          lfs: true

      - name: Cache Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}

      - name: Run Tests
        uses: game-ci/unity-test-runner@v3
        with:
          projectPath: .
          testMode: ${{ matrix.testMode }}
          artifactsPath: TestResults/${{ matrix.testMode }}
          githubToken: ${{ secrets.GITHUB_TOKEN }}
          checkName: ${{ matrix.testMode }} Test Results

      - name: Upload Artifacts
        uses: actions/upload-artifact@v3
        with:
          name: Test Results - ${{ matrix.testMode }}
          path: TestResults/${{ matrix.testMode }}

      - name: Publish Test Report
        uses: mikepenz/action-junit-report@v3
        if: always()
        with:
          report_paths: 'TestResults/**/*.xml'
          check_name: ${{ matrix.testMode }} Test Report
```

### 5.3 测试报告生成器

```csharp
// 自定义测试报告生成（HTML格式）
using NUnit.Framework.Interfaces;
using UnityEngine.TestRunner;
using System.Text;
using System.IO;

[assembly: TestRunCallback(typeof(HTMLTestReporter))]

public class HTMLTestReporter : ITestRunCallback
{
    private readonly List<ITestResult> _results = new();
    private System.Diagnostics.Stopwatch _stopwatch;

    public void RunStarted(ITest testsToRun)
    {
        _results.Clear();
        _stopwatch = System.Diagnostics.Stopwatch.StartNew();
        Debug.Log($"[TestReport] 开始测试：{testsToRun.Name}");
    }

    public void RunFinished(ITestResult testResults)
    {
        _stopwatch?.Stop();
        GenerateHTMLReport(testResults);
    }

    public void TestStarted(ITest test) { }

    public void TestFinished(ITestResult result)
    {
        if (!result.Test.IsSuite)
            _results.Add(result);
    }

    private void GenerateHTMLReport(ITestResult rootResult)
    {
        int passed  = _results.Count(r => r.ResultState.Status == TestStatus.Passed);
        int failed  = _results.Count(r => r.ResultState.Status == TestStatus.Failed);
        int skipped = _results.Count(r => r.ResultState.Status == TestStatus.Skipped);
        int total   = _results.Count;

        var sb = new StringBuilder();
        sb.AppendLine("<!DOCTYPE html><html><head>");
        sb.AppendLine("<meta charset='utf-8'><title>Unity测试报告</title>");
        sb.AppendLine("<style>");
        sb.AppendLine("body{font-family:Arial,sans-serif;padding:20px;background:#f5f5f5}");
        sb.AppendLine(".summary{background:white;padding:20px;border-radius:8px;margin-bottom:20px}");
        sb.AppendLine(".passed{color:#4CAF50}.failed{color:#f44336}.skipped{color:#FF9800}");
        sb.AppendLine(".test-item{background:white;padding:10px;margin:5px 0;border-radius:4px;border-left:4px solid #ccc}");
        sb.AppendLine(".test-item.pass{border-left-color:#4CAF50}.test-item.fail{border-left-color:#f44336}");
        sb.AppendLine("</style></head><body>");
        
        // 摘要
        sb.AppendLine("<div class='summary'>");
        sb.AppendLine($"<h1>Unity 自动化测试报告</h1>");
        sb.AppendLine($"<p>运行时间：{System.DateTime.Now:yyyy-MM-dd HH:mm:ss}</p>");
        sb.AppendLine($"<p>耗时：{_stopwatch?.Elapsed.TotalSeconds:F2}s</p>");
        sb.AppendLine($"<h2>");
        sb.AppendLine($"<span class='passed'>✓ 通过：{passed}</span> / ");
        sb.AppendLine($"<span class='failed'>✗ 失败：{failed}</span> / ");
        sb.AppendLine($"<span class='skipped'>⊘ 跳过：{skipped}</span> / ");
        sb.AppendLine($"总计：{total}");
        sb.AppendLine($"</h2></div>");

        // 测试详情
        sb.AppendLine("<h2>测试详情</h2>");
        foreach (var result in _results.OrderBy(r => r.ResultState.Status))
        {
            bool isPassed = result.ResultState.Status == TestStatus.Passed;
            string cssClass = isPassed ? "pass" : "fail";
            string icon = isPassed ? "✓" : "✗";
            
            sb.AppendLine($"<div class='test-item {cssClass}'>");
            sb.AppendLine($"<strong>{icon} {result.Test.FullName}</strong>");
            sb.AppendLine($"<span style='float:right'>{result.Duration:F3}s</span>");
            
            if (!isPassed && !string.IsNullOrEmpty(result.Message))
            {
                sb.AppendLine($"<pre style='color:red;margin-top:8px'>{result.Message}</pre>");
            }
            
            sb.AppendLine("</div>");
        }

        sb.AppendLine("</body></html>");

        string reportPath = $"TestResults/Report_{System.DateTime.Now:yyyyMMdd_HHmm}.html";
        Directory.CreateDirectory("TestResults");
        File.WriteAllText(reportPath, sb.ToString());
        
        Debug.Log($"[TestReport] HTML报告已生成：{Path.GetFullPath(reportPath)}");
        Debug.Log($"[TestReport] 结果：{passed}/{total} 通过，{failed} 失败");
    }
}
```

---

## 6. 最佳实践总结

### 6.1 测试设计原则

```
FIRST 原则（好测试的标准）：
  F - Fast（快速）    : 单个测试 < 100ms（EditMode），PlayMode < 5s
  I - Isolated（隔离）: 每个测试独立，不依赖其他测试的状态
  R - Repeatable（可重复）: 任何环境下结果一致
  S - Self-validating（自验证）: 有明确的Pass/Fail断言
  T - Timely（及时）  : 写代码的同时写测试，而非事后补充
```

### 6.2 Unity 测试注意事项

```
常见陷阱与解决方案：

1. 时序问题
   ❌ 问题：yield return null 等待帧不够
   ✓ 解决：使用 WaitUntil 或固定时间等待

2. 对象泄漏
   ❌ 问题：测试后GameObject未清理，影响下一个测试
   ✓ 解决：在 [TearDown] 中 DestroyImmediate 所有创建的对象

3. 静态状态污染
   ❌ 问题：单例类的静态状态在测试间共享
   ✓ 解决：测试前重置单例，或使用依赖注入

4. 截图对比抖动
   ❌ 问题：字体渲染/粒子系统导致每次截图略有不同
   ✓ 解决：设置固定随机种子，关闭粒子，提高差异阈值

5. CI环境缺少GPU
   ❌ 问题：PlayMode截图测试在无头服务器失败
   ✓ 解决：使用虚拟帧缓冲（Xvfb），或跳过截图测试
```

### 6.3 测试覆盖率目标

```
优先级建议：
  高优先级（必须测试）：
  ✓ 核心战斗公式
  ✓ 数据解析（配置表、存档）
  ✓ 状态机转换
  ✓ 关键UI流程（登录、支付、核心功能入口）

  中优先级：
  ✓ 网络消息处理
  ✓ 音频系统管理
  ✓ 资源加载/卸载

  低优先级（可选）：
  ○ 纯视觉表现
  ○ 动画细节
  ○ 粒子效果
```

---

## 总结

游戏自动化UI测试是保障快速迭代质量的核心工具。通过 Unity Test Framework 构建分层测试体系，结合截图回归测试和录制回放系统，可以大幅降低回归Bug率。关键是：**测试要快、要独立、要有明确断言**，并将其融入 CI/CD 流水线，让每次代码提交都自动接受质量验证。
