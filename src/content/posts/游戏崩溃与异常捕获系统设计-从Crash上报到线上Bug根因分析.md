---
title: 游戏崩溃与异常捕获系统设计：从Crash上报到线上Bug根因分析
published: 2026-03-30
description: 系统讲解游戏客户端崩溃捕获与异常监控体系的设计与实现，涵盖C#异常捕获、原生Crash（IL2CPP/Native层）、日志系统分级架构、崩溃堆栈符号化、线上Bug聚合分析、热修复机制以及完整的监控告警闭环，助力游戏线上质量体系建设。
tags: [游戏开发, 崩溃分析, 异常捕获, 日志系统, 线上监控, Unity]
category: 工程实践
draft: false
---

# 游戏崩溃与异常捕获系统设计：从Crash上报到线上Bug根因分析

## 前言

线上崩溃是游戏团队最头疼的问题之一。玩家一崩溃就流失，而复现崩溃往往比修复它更难。一套完善的崩溃与异常捕获体系，能将"用户反馈崩了"转变为"收到完整堆栈+现场日志+设备信息"，让每一个崩溃都有迹可循。

本文将系统讲解游戏崩溃监控体系的完整设计：

- C# 托管层异常捕获
- IL2CPP/Native 层崩溃捕获
- 分级日志系统设计
- 崩溃上报与堆栈符号化
- 线上异常聚合与根因分析
- 热修复与容灾降级机制

---

## 一、异常捕获层次架构

### 1.1 Unity 中的异常层次

```
┌─────────────────────────────────────────────────────────┐
│              C# 托管层（Mono / IL2CPP）                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  try-catch 业务层捕获（最精确）                    │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Application.logMessageReceived（全局托管异常兜底）│   │
│  └──────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│              Native 层（C++/IL2CPP Runtime）              │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Signal Handler（SIGSEGV/SIGABRT等）              │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  ANR 检测（Android Activity Not Responding）      │   │
│  └──────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│              设备/OS 层                                   │
│  Android: Tombstone / iOS: Crashlog                     │
└─────────────────────────────────────────────────────────┘
```

### 1.2 异常捕获管理器

```csharp
using UnityEngine;
using System;
using System.Threading;
using System.Collections.Generic;

/// <summary>
/// 游戏崩溃与异常捕获管理器
/// 负责收集、处理、上报所有类型的异常
/// </summary>
public class CrashReportManager : MonoBehaviour
{
    public static CrashReportManager Instance { get; private set; }

    [Header("配置")]
    [SerializeField] private bool enableCrashReport = true;
    [SerializeField] private string reportEndpoint = "https://your-report-server.com/api/crash";
    [SerializeField] private int maxLocalCrashLogs = 10;
    [SerializeField] private bool captureScreenshotOnCrash = true;

    // 崩溃上下文信息
    private readonly Dictionary<string, string> _extraContext = new();
    private string _lastScene;
    private string _lastOperation;

    // 延迟上报队列（崩溃后下次启动上报）
    private const string PENDING_REPORTS_KEY = "PendingCrashReports";

    void Awake()
    {
        if (Instance != null) { Destroy(gameObject); return; }
        Instance = this;
        DontDestroyOnLoad(gameObject);

        InitializeCrashCapture();
        // 上报上次遗留的崩溃报告
        StartCoroutine(ReportPendingCrashes());
    }

    void InitializeCrashCapture()
    {
        if (!enableCrashReport) return;

        // 1. 捕获C#托管异常（包括Unity内部log error）
        Application.logMessageReceived += OnLogMessageReceived;

        // 2. 捕获多线程异常（子线程的未处理异常）
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;

        // 3. 捕获任务异常（Task/async未观察的异常）
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;

        // 4. iOS平台崩溃配置
        #if UNITY_IOS && !UNITY_EDITOR
        IOSCrashCapture.Initialize();
        #endif

        // 5. Android ANR检测
        #if UNITY_ANDROID && !UNITY_EDITOR
        AndroidANRDetector.StartMonitoring(5f); // 超过5秒主线程无响应则报警
        #endif

        Debug.Log("[CrashReport] 崩溃捕获系统已初始化");
    }

    /// <summary>Unity log回调 - 捕获Error和Exception类型</summary>
    private void OnLogMessageReceived(string condition, string stackTrace, LogType type)
    {
        if (type != LogType.Error && type != LogType.Exception) return;

        var report = BuildCrashReport(
            crashType: type == LogType.Exception ? "Exception" : "Error",
            message: condition,
            stackTrace: stackTrace
        );

        // Exception级别立即截图（如果可能）
        if (type == LogType.Exception && captureScreenshotOnCrash)
        {
            StartCoroutine(CaptureScreenshotAndReport(report));
        }
        else
        {
            EnqueueReport(report);
        }
    }

    /// <summary>非托管线程异常（通常是致命崩溃）</summary>
    private void OnUnhandledException(object sender, UnhandledExceptionEventArgs args)
    {
        var ex = args.ExceptionObject as Exception;
        string msg = ex?.Message ?? args.ExceptionObject?.ToString() ?? "Unknown";
        string stack = ex?.StackTrace ?? "";

        var report = BuildCrashReport("UnhandledException", msg, stack);
        // 同步保存（因为进程可能马上退出）
        SaveReportToLocalSync(report);
    }

    private void OnUnobservedTaskException(object sender, UnobservedTaskExceptionEventArgs args)
    {
        args.SetObserved(); // 防止进程崩溃
        var ex = args.Exception?.InnerException ?? args.Exception;
        var report = BuildCrashReport("UnobservedTaskException",
            ex?.Message ?? "Task failed", ex?.StackTrace ?? "");
        EnqueueReport(report);
    }

    /// <summary>构建崩溃报告数据</summary>
    private CrashReport BuildCrashReport(string crashType, string message, string stackTrace)
    {
        return new CrashReport
        {
            // 基础信息
            CrashType = crashType,
            Message = message,
            StackTrace = stackTrace,
            Timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),

            // 设备信息
            DeviceModel = SystemInfo.deviceModel,
            OS = SystemInfo.operatingSystem,
            Platform = Application.platform.ToString(),
            Memory = SystemInfo.systemMemorySize,
            GPU = SystemInfo.graphicsDeviceName,
            GPUDriver = SystemInfo.graphicsDeviceVersion,

            // 应用信息
            AppVersion = Application.version,
            UnityVersion = Application.unityVersion,
            BuildGUID = Application.buildGUID,

            // 游戏运行上下文
            CurrentScene = _lastScene,
            LastOperation = _lastOperation,
            PlayTime = (long)Time.realtimeSinceStartup,

            // 自定义扩展字段
            ExtraContext = new Dictionary<string, string>(_extraContext)
        };
    }

    /// <summary>设置当前操作上下文（帮助定位崩溃发生时的游戏状态）</summary>
    public void SetContext(string key, string value)
    {
        _extraContext[key] = value;
    }

    public void SetCurrentScene(string sceneName) => _lastScene = sceneName;
    public void SetLastOperation(string operation) => _lastOperation = operation;

    private void EnqueueReport(CrashReport report)
    {
        // 优先尝试实时上报
        StartCoroutine(TryReportImmediate(report));
    }

    private System.Collections.IEnumerator TryReportImmediate(CrashReport report)
    {
        // 实时上报
        yield return StartCoroutine(SendReport(report));
    }

    private void SaveReportToLocalSync(CrashReport report)
    {
        // 同步写入本地文件（崩溃时不能用协程）
        string json = JsonUtility.ToJson(report);
        string path = Application.persistentDataPath + $"/crash_{report.Timestamp}.json";
        System.IO.File.WriteAllText(path, json);
    }

    private System.Collections.IEnumerator ReportPendingCrashes()
    {
        // 启动时检查是否有上次遗留的崩溃报告
        yield return new WaitForSeconds(5f); // 等待游戏初始化完成

        string crashDir = Application.persistentDataPath;
        var crashFiles = System.IO.Directory.GetFiles(crashDir, "crash_*.json");

        foreach (var file in crashFiles)
        {
            try
            {
                string json = System.IO.File.ReadAllText(file);
                var report = JsonUtility.FromJson<CrashReport>(json);
                report.IsDelayedReport = true;

                yield return StartCoroutine(SendReport(report));
                System.IO.File.Delete(file);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[CrashReport] 补报失败: {e.Message}");
            }
        }
    }

    private System.Collections.IEnumerator SendReport(CrashReport report)
    {
        string json = JsonUtility.ToJson(report);
        byte[] bodyData = System.Text.Encoding.UTF8.GetBytes(json);

        using var www = new UnityEngine.Networking.UnityWebRequest(
            reportEndpoint, "POST");
        www.uploadHandler = new UnityEngine.Networking.UploadHandlerRaw(bodyData);
        www.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
        www.SetRequestHeader("Content-Type", "application/json");

        yield return www.SendWebRequest();

        if (www.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
        {
            // 上报失败，保存到本地等待下次
            SaveReportToLocalSync(report);
        }
    }

    private System.Collections.IEnumerator CaptureScreenshotAndReport(CrashReport report)
    {
        yield return new WaitForEndOfFrame();

        // 截取当前帧
        Texture2D screenshot = ScreenCapture.CaptureScreenshotAsTexture();
        report.ScreenshotBase64 = Convert.ToBase64String(
            screenshot.EncodeToJPG(50)); // 50%质量，减小体积
        Destroy(screenshot);

        yield return StartCoroutine(SendReport(report));
    }

    void OnDestroy()
    {
        Application.logMessageReceived -= OnLogMessageReceived;
        AppDomain.CurrentDomain.UnhandledException -= OnUnhandledException;
        TaskScheduler.UnobservedTaskException -= OnUnobservedTaskException;
    }
}

/// <summary>崩溃报告数据结构</summary>
[Serializable]
public class CrashReport
{
    public string CrashType;
    public string Message;
    public string StackTrace;
    public long Timestamp;
    public bool IsDelayedReport;

    // 设备信息
    public string DeviceModel;
    public string OS;
    public string Platform;
    public int Memory;
    public string GPU;
    public string GPUDriver;

    // 应用信息
    public string AppVersion;
    public string UnityVersion;
    public string BuildGUID;

    // 游戏上下文
    public string CurrentScene;
    public string LastOperation;
    public long PlayTime;

    public string ScreenshotBase64;
    public Dictionary<string, string> ExtraContext;
}
```

---

## 二、分级日志系统

### 2.1 日志系统架构设计

```csharp
using System;
using System.IO;
using System.Text;

/// <summary>
/// 游戏分级日志系统
/// 特性：
///   - 5个日志级别（Verbose/Debug/Info/Warning/Error）
///   - 分模块日志开关（生产环境关闭Debug级别）
///   - 环形缓冲区（崩溃时可获取最近N条日志）
///   - 异步写入文件（不阻塞主线程）
///   - 支持日志压缩上传
/// </summary>
public static class GameLogger
{
    public enum LogLevel { Verbose = 0, Debug = 1, Info = 2, Warning = 3, Error = 4 }

    // 全局日志级别过滤
    public static LogLevel GlobalLevel { get; set; } = LogLevel.Info;

    // 模块级别开关
    private static readonly Dictionary<string, LogLevel> _moduleLevel = new();

    // 环形缓冲区（崩溃时获取最近日志）
    private const int RING_BUFFER_SIZE = 500;
    private static readonly string[] _ringBuffer = new string[RING_BUFFER_SIZE];
    private static int _ringIndex = 0;
    private static readonly object _ringLock = new object();

    // 异步写入队列
    private static readonly System.Collections.Concurrent.ConcurrentQueue<string> _writeQueue
        = new();
    private static System.Threading.Thread _writeThread;
    private static FileStream _logFile;
    private static StreamWriter _logWriter;
    private static bool _isRunning = false;

    // 日志文件路径
    private static string _logFilePath;

    /// <summary>初始化日志系统</summary>
    public static void Initialize(string persistentPath, bool enableFileLog = true)
    {
        // 设置日志文件路径（按日期滚动）
        string date = DateTime.Now.ToString("yyyyMMdd");
        _logFilePath = Path.Combine(persistentPath, $"game_log_{date}.txt");

        if (enableFileLog)
        {
            // 启动异步写入线程
            _isRunning = true;
            _logFile = new FileStream(_logFilePath, FileMode.Append, FileAccess.Write,
                FileShare.Read, 4096, true);
            _logWriter = new StreamWriter(_logFile, Encoding.UTF8);

            _writeThread = new System.Threading.Thread(WriteThreadLoop)
            {
                IsBackground = true,
                Name = "LogWriteThread"
            };
            _writeThread.Start();
        }

        // 接管Unity的日志输出
        Application.logMessageReceivedThreaded += OnUnityLog;

        Info("System", $"日志系统初始化完成，日志文件：{_logFilePath}");
    }

    /// <summary>Verbose：详细调试信息（仅开发版本）</summary>
    public static void Verbose(string module, string message)
        => Log(LogLevel.Verbose, module, message);

    /// <summary>Debug：调试信息</summary>
    public static void Debug(string module, string message)
        => Log(LogLevel.Debug, module, message);

    /// <summary>Info：常规信息</summary>
    public static void Info(string module, string message)
        => Log(LogLevel.Info, module, message);

    /// <summary>Warning：警告</summary>
    public static void Warning(string module, string message)
        => Log(LogLevel.Warning, module, message);

    /// <summary>Error：错误（会触发崩溃上报）</summary>
    public static void Error(string module, string message, Exception ex = null)
    {
        string fullMsg = ex != null
            ? $"{message}\n{ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}"
            : message;
        Log(LogLevel.Error, module, fullMsg);
    }

    private static void Log(LogLevel level, string module, string message)
    {
        // 级别过滤
        LogLevel moduleLevel = _moduleLevel.TryGetValue(module, out var ml)
            ? ml : GlobalLevel;
        if (level < moduleLevel) return;

        string timestamp = DateTime.Now.ToString("HH:mm:ss.fff");
        string levelStr = level.ToString().ToUpper().PadRight(7);
        string logEntry = $"[{timestamp}][{levelStr}][{module}] {message}";

        // 写入环形缓冲区（用于崩溃时获取上下文）
        lock (_ringLock)
        {
            _ringBuffer[_ringIndex % RING_BUFFER_SIZE] = logEntry;
            _ringIndex++;
        }

        // 异步写入文件
        _writeQueue.Enqueue(logEntry);

        // Error级别同步到Unity Console（方便开发调试）
        #if UNITY_EDITOR
        switch (level)
        {
            case LogLevel.Warning: UnityEngine.Debug.LogWarning($"[{module}] {message}"); break;
            case LogLevel.Error:   UnityEngine.Debug.LogError($"[{module}] {message}"); break;
            default:               UnityEngine.Debug.Log($"[{module}] {message}"); break;
        }
        #endif
    }

    /// <summary>获取最近N条日志（崩溃时调用）</summary>
    public static string[] GetRecentLogs(int count = 100)
    {
        lock (_ringLock)
        {
            count = Math.Min(count, RING_BUFFER_SIZE);
            var result = new string[count];
            int total = Math.Min(_ringIndex, RING_BUFFER_SIZE);
            int start = _ringIndex - count;

            for (int i = 0; i < count; i++)
            {
                int idx = (start + i + RING_BUFFER_SIZE) % RING_BUFFER_SIZE;
                result[i] = _ringBuffer[idx] ?? "";
            }
            return result;
        }
    }

    /// <summary>设置模块级别</summary>
    public static void SetModuleLevel(string module, LogLevel level)
        => _moduleLevel[module] = level;

    private static void WriteThreadLoop()
    {
        while (_isRunning || !_writeQueue.IsEmpty)
        {
            while (_writeQueue.TryDequeue(out string line))
            {
                try
                {
                    _logWriter?.WriteLine(line);
                }
                catch { /* 写入失败静默处理 */ }
            }

            try { _logWriter?.Flush(); } catch { }
            System.Threading.Thread.Sleep(100); // 每100ms刷一次
        }
    }

    private static void OnUnityLog(string condition, string stackTrace, UnityEngine.LogType type)
    {
        // 将Unity内部日志也接入我们的日志系统
        if (type == UnityEngine.LogType.Exception)
        {
            Error("Unity", $"{condition}\n{stackTrace}");
        }
    }

    /// <summary>关闭日志系统（应用退出时调用）</summary>
    public static void Shutdown()
    {
        _isRunning = false;
        Application.logMessageReceivedThreaded -= OnUnityLog;
        _writeThread?.Join(2000);
        _logWriter?.Flush();
        _logWriter?.Close();
        _logFile?.Close();
    }
}
```

### 2.2 上下文感知日志（Scope日志）

```csharp
/// <summary>
/// 作用域日志 - 自动记录操作的开始/结束/耗时
/// 使用 using 语法，代码干净整洁
/// </summary>
public class LogScope : IDisposable
{
    private readonly string _module;
    private readonly string _operation;
    private readonly long _startMs;
    private bool _failed;
    private string _failReason;

    public LogScope(string module, string operation)
    {
        _module = module;
        _operation = operation;
        _startMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        GameLogger.Info(_module, $"开始 [{_operation}]");

        // 设置崩溃上下文（如果这个操作崩了，报告里会有）
        CrashReportManager.Instance?.SetLastOperation($"{_module}.{_operation}");
    }

    public void Fail(string reason)
    {
        _failed = true;
        _failReason = reason;
    }

    public void Dispose()
    {
        long elapsed = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _startMs;

        if (_failed)
        {
            GameLogger.Error(_module,
                $"失败 [{_operation}] 耗时:{elapsed}ms 原因:{_failReason}");
        }
        else
        {
            GameLogger.Info(_module, $"完成 [{_operation}] 耗时:{elapsed}ms");
        }
    }
}

// 使用示例
public class ResourceLoader
{
    public async System.Threading.Tasks.Task LoadBundle(string bundleName)
    {
        using var scope = new LogScope("ResourceLoader", $"加载Bundle:{bundleName}");
        try
        {
            // ... 加载逻辑
            await System.Threading.Tasks.Task.Delay(100);
        }
        catch (Exception ex)
        {
            scope.Fail(ex.Message);
            throw;
        }
    }
}
```

---

## 三、堆栈符号化

### 3.1 Android（IL2CPP）堆栈符号化

IL2CPP 崩溃后的堆栈是地址，需要用 addr2line 或 ndk-stack 工具转换：

```bash
#!/bin/bash
# symbolize_crash.sh - Android IL2CPP 堆栈符号化脚本

CRASH_LOG=$1          # 崩溃日志文件
SYMBOLS_DIR=$2        # 包含 libil2cpp.so 的 symbols 目录
NDK_PATH=${ANDROID_NDK_HOME:-~/android-ndk}

# 从崩溃日志中提取堆栈帧
# 格式: #00 pc 000abc12  /data/app/.../libil2cpp.so
while IFS= read -r line; do
    if [[ $line =~ "#"[0-9]+" pc "([0-9a-f]+)" " ]]; then
        addr="${BASH_REMATCH[1]}"
        
        # 使用 addr2line 符号化
        symbol=$($NDK_PATH/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-addr2line \
            -f -C -e "$SYMBOLS_DIR/libil2cpp.so" "0x$addr" 2>/dev/null)
        
        echo "$line"
        echo "    -> $symbol"
    else
        echo "$line"
    fi
done < "$CRASH_LOG"
```

### 3.2 C# 层符号化映射

```csharp
/// <summary>
/// IL2CPP 方法地址与C#方法名映射
/// 用于在运行时将崩溃地址转换为可读的方法名
/// </summary>
public class StackSymbolizer
{
    // IL2CPP 会生成 Il2CppOutputProject/il2cpp_data/Metadata/global-metadata.dat
    // 以及对应的符号文件，这里演示如何在C#层做简单的映射

    private static Dictionary<string, string> _methodNameMap;

    /// <summary>
    /// 美化Unity托管异常的堆栈（移除多余的IL2CPP包装层）
    /// </summary>
    public static string BeautifyStackTrace(string rawStackTrace)
    {
        if (string.IsNullOrEmpty(rawStackTrace)) return rawStackTrace;

        var lines = rawStackTrace.Split('\n');
        var sb = new StringBuilder();

        foreach (var line in lines)
        {
            string cleaned = line.Trim();
            // 过滤 IL2CPP 内部包装函数
            if (cleaned.Contains("IL2CPP_MANAGED_FORCE_INLINE")) continue;
            if (cleaned.Contains("il2cpp::vm::")) continue;
            if (cleaned.StartsWith("0x") && !cleaned.Contains(".cs:")) continue;

            sb.AppendLine(cleaned);
        }

        return sb.ToString();
    }

    /// <summary>
    /// 从堆栈字符串中提取关键信息（文件名、行号、方法名）
    /// </summary>
    public static StackFrame ParseFrame(string frameLine)
    {
        // Unity 托管堆栈格式:
        // "at ClassName.MethodName (Type arg) [0x00000] in /path/to/File.cs:42"
        var match = System.Text.RegularExpressions.Regex.Match(frameLine,
            @"at (.+?)\s*\[.+?\]\s*in\s*(.+?):(\d+)");

        if (!match.Success)
        {
            return new StackFrame { RawLine = frameLine };
        }

        return new StackFrame
        {
            MethodName = match.Groups[1].Value,
            FilePath = match.Groups[2].Value,
            LineNumber = int.Parse(match.Groups[3].Value),
            RawLine = frameLine
        };
    }
}

public class StackFrame
{
    public string MethodName;
    public string FilePath;
    public int LineNumber;
    public string RawLine;

    // 获取简短文件名（隐去完整路径保护版权信息）
    public string ShortFileName =>
        FilePath != null ? System.IO.Path.GetFileName(FilePath) : "";

    public override string ToString() =>
        $"{MethodName} ({ShortFileName}:{LineNumber})";
}
```

---

## 四、ANR检测与主线程监控

### 4.1 主线程卡顿检测

```csharp
/// <summary>
/// 主线程卡顿（ANR）检测器
/// 原理：子线程定时 "喂狗"，如果超时未收到心跳则判定为卡顿
/// </summary>
public class MainThreadANRDetector : MonoBehaviour
{
    [Header("ANR阈值（秒）")]
    public float anrThreshold = 5f;
    [Header("采样间隔（秒）")]
    public float sampleInterval = 0.5f;

    private volatile long _lastHeartbeat;
    private System.Threading.Thread _watchdogThread;
    private bool _isRunning;

    void Start()
    {
        _isRunning = true;
        _lastHeartbeat = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        // 启动看门狗线程
        _watchdogThread = new System.Threading.Thread(WatchdogLoop)
        {
            IsBackground = true,
            Name = "ANR-Watchdog"
        };
        _watchdogThread.Start();
    }

    void Update()
    {
        // 主线程每帧更新心跳时间
        _lastHeartbeat = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    }

    private void WatchdogLoop()
    {
        while (_isRunning)
        {
            System.Threading.Thread.Sleep((int)(sampleInterval * 1000));

            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            long elapsed = now - _lastHeartbeat;

            if (elapsed > anrThreshold * 1000)
            {
                // 主线程卡顿！收集现场信息
                OnANRDetected(elapsed);
            }
        }
    }

    private void OnANRDetected(long frozenMs)
    {
        // 注意：此时在子线程，不能调用Unity API
        string report = $"[ANR] 主线程卡顿 {frozenMs}ms\n"
            + $"设备: {SystemInfo.deviceModel}\n"
            + $"时间: {DateTime.Now}\n"
            + "最近日志:\n"
            + string.Join("\n", GameLogger.GetRecentLogs(50));

        // 写入文件（不用Unity API）
        string path = Application.persistentDataPath + "/anr_report.txt";
        File.WriteAllText(path, report);

        // 触发告警（通过HTTP等方式上报，不依赖Unity主线程）
        ReportANRAsync(report);
    }

    private async void ReportANRAsync(string report)
    {
        try
        {
            using var client = new System.Net.Http.HttpClient();
            var content = new System.Net.Http.StringContent(
                report, Encoding.UTF8, "text/plain");
            await client.PostAsync("https://your-server.com/api/anr", content);
        }
        catch { /* 上报失败静默处理 */ }
    }

    void OnDestroy()
    {
        _isRunning = false;
        _watchdogThread?.Join(1000);
    }
}
```

---

## 五、线上异常聚合分析

### 5.1 异常指纹生成

相同的崩溃可能来自不同设备，需要对崩溃进行去重聚合：

```csharp
/// <summary>
/// 崩溃指纹生成器
/// 相同原因的崩溃应聚合为同一个Issue，便于统计和排优先级
/// </summary>
public static class CrashFingerprint
{
    /// <summary>
    /// 生成崩溃指纹
    /// 策略：取堆栈顶部3帧的方法名哈希（忽略行号、忽略地址）
    /// </summary>
    public static string Generate(string message, string stackTrace)
    {
        // 1. 提取异常类型（忽略具体消息，同类型崩溃归一组）
        string exceptionType = ExtractExceptionType(message);

        // 2. 提取栈顶3帧的方法签名（忽略行号变化）
        var frames = ExtractTopFrames(stackTrace, 3);
        string frameSignature = string.Join("|", frames);

        // 3. 组合哈希
        string raw = $"{exceptionType}#{frameSignature}";
        return ComputeMD5(raw)[..12]; // 取前12位作为指纹
    }

    private static string ExtractExceptionType(string message)
    {
        // 提取 "NullReferenceException: xxx" 中的 "NullReferenceException"
        int colonIdx = message.IndexOf(':');
        if (colonIdx > 0) return message[..colonIdx].Trim();
        return message.Split('\n')[0].Trim();
    }

    private static List<string> ExtractTopFrames(string stackTrace, int count)
    {
        var result = new List<string>();
        var lines = stackTrace.Split('\n');

        foreach (var line in lines)
        {
            if (result.Count >= count) break;
            var frame = StackSymbolizer.ParseFrame(line);
            if (!string.IsNullOrEmpty(frame.MethodName))
            {
                // 只取方法名，忽略行号（行号会随代码修改而变化）
                result.Add(frame.MethodName);
            }
        }

        return result;
    }

    private static string ComputeMD5(string input)
    {
        using var md5 = System.Security.Cryptography.MD5.Create();
        byte[] hash = md5.ComputeHash(Encoding.UTF8.GetBytes(input));
        return BitConverter.ToString(hash).Replace("-", "").ToLower();
    }
}
```

### 5.2 崩溃率监控告警

```csharp
/// <summary>
/// 崩溃率实时监控
/// 如果短时间内崩溃率突然升高，自动触发告警（如发钉钉/企微通知）
/// </summary>
public class CrashRateMonitor
{
    private readonly Queue<long> _recentCrashes = new();
    private const int WINDOW_SECONDS = 300;   // 5分钟滑动窗口
    private const int ALERT_THRESHOLD = 50;    // 5分钟内超过50次崩溃则告警
    private const int CRITICAL_THRESHOLD = 200; // 200次则紧急告警

    private bool _alertSent = false;
    private DateTime _alertCooldown = DateTime.MinValue;

    public void RecordCrash()
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        _recentCrashes.Enqueue(now);

        // 清理窗口外的记录
        while (_recentCrashes.Count > 0 &&
               now - _recentCrashes.Peek() > WINDOW_SECONDS)
        {
            _recentCrashes.Dequeue();
        }

        int count = _recentCrashes.Count;
        CheckAlert(count);
    }

    private void CheckAlert(int count)
    {
        // 冷却期内不重复告警
        if (DateTime.Now < _alertCooldown) return;

        if (count >= CRITICAL_THRESHOLD)
        {
            SendAlert($"🚨 [紧急] 崩溃率异常！5分钟内崩溃{count}次！请立即处理！",
                AlertLevel.Critical);
            _alertCooldown = DateTime.Now.AddMinutes(10);
        }
        else if (count >= ALERT_THRESHOLD)
        {
            SendAlert($"⚠️ [警告] 崩溃率升高，5分钟内崩溃{count}次", AlertLevel.Warning);
            _alertCooldown = DateTime.Now.AddMinutes(30);
        }
    }

    enum AlertLevel { Warning, Critical }

    private async void SendAlert(string message, AlertLevel level)
    {
        // 发送到企业微信/钉钉机器人 Webhook
        var payload = new { msgtype = "text", text = new { content = message } };
        string json = Newtonsoft.Json.JsonConvert.SerializeObject(payload);

        using var client = new System.Net.Http.HttpClient();
        await client.PostAsync(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY",
            new System.Net.Http.StringContent(json, Encoding.UTF8, "application/json"));
    }
}
```

---

## 六、热修复与容灾降级

### 6.1 功能开关（Feature Flag）

崩溃不一定要立即发版修复，很多时候可以通过远程开关紧急降级：

```csharp
/// <summary>
/// 远程功能开关系统
/// 崩溃时可通过后台动态关闭有问题的功能，无需发版
/// </summary>
public class FeatureFlagManager : MonoBehaviour
{
    public static FeatureFlagManager Instance { get; private set; }

    // 本地缓存的开关配置
    private Dictionary<string, bool> _flags = new();
    private Dictionary<string, bool> _defaultFlags = new()
    {
        { "new_battle_system", true },
        { "new_shop_ui", true },
        { "experimental_ai", false },
    };

    private const string CONFIG_URL = "https://your-server.com/api/feature-flags";
    private const string LOCAL_CACHE_KEY = "FeatureFlags";

    void Awake()
    {
        Instance = this;
        LoadLocalCache();
        FetchRemoteFlags();
    }

    /// <summary>检查功能是否开启（带容灾：远程失败时使用默认值）</summary>
    public bool IsEnabled(string featureKey)
    {
        if (_flags.TryGetValue(featureKey, out bool flag)) return flag;
        if (_defaultFlags.TryGetValue(featureKey, out bool def)) return def;
        return true; // 未知开关默认开启
    }

    private void LoadLocalCache()
    {
        string cached = PlayerPrefs.GetString(LOCAL_CACHE_KEY, "");
        if (!string.IsNullOrEmpty(cached))
        {
            try
            {
                _flags = JsonUtility.FromJson<SerializableFlags>(cached).ToDictionary();
            }
            catch { }
        }
    }

    private async void FetchRemoteFlags()
    {
        try
        {
            using var client = new System.Net.Http.HttpClient();
            client.Timeout = TimeSpan.FromSeconds(5);
            string json = await client.GetStringAsync(CONFIG_URL);

            // 更新内存缓存
            _flags = Newtonsoft.Json.JsonConvert.DeserializeObject<Dictionary<string, bool>>(json);

            // 持久化到本地
            PlayerPrefs.SetString(LOCAL_CACHE_KEY, json);
        }
        catch (Exception e)
        {
            GameLogger.Warning("FeatureFlag", $"获取远程开关失败，使用本地缓存: {e.Message}");
        }
    }
}

// 使用示例：在可能崩溃的功能入口添加开关检查
public class NewBattleSystem : MonoBehaviour
{
    void Start()
    {
        if (!FeatureFlagManager.Instance.IsEnabled("new_battle_system"))
        {
            // 降级到旧版战斗系统
            GetComponent<OldBattleSystem>().enabled = true;
            enabled = false;
            return;
        }
        // 初始化新战斗系统...
    }
}
```

### 6.2 异常熔断器

```csharp
/// <summary>
/// 熔断器模式 - 某个系统频繁异常时自动熔断，防止雪崩
/// </summary>
public class CircuitBreaker
{
    private int _failCount = 0;
    private DateTime _lastFailTime = DateTime.MinValue;
    private bool _isOpen = false; // 熔断状态

    private readonly int _failThreshold;
    private readonly TimeSpan _resetTimeout;
    private readonly string _name;

    public CircuitBreaker(string name, int failThreshold = 5,
        float resetTimeoutSeconds = 60f)
    {
        _name = name;
        _failThreshold = failThreshold;
        _resetTimeout = TimeSpan.FromSeconds(resetTimeoutSeconds);
    }

    /// <summary>尝试执行操作，如果熔断则跳过</summary>
    public bool TryExecute(Action action, Action fallback = null)
    {
        if (_isOpen)
        {
            // 检查是否可以半开（尝试恢复）
            if (DateTime.Now - _lastFailTime > _resetTimeout)
            {
                _isOpen = false;
                _failCount = 0;
                GameLogger.Info("CircuitBreaker", $"[{_name}] 半开状态，尝试恢复");
            }
            else
            {
                // 熔断中，执行降级逻辑
                fallback?.Invoke();
                return false;
            }
        }

        try
        {
            action();
            _failCount = 0; // 成功则重置计数
            return true;
        }
        catch (Exception ex)
        {
            _failCount++;
            _lastFailTime = DateTime.Now;

            GameLogger.Warning("CircuitBreaker",
                $"[{_name}] 失败({_failCount}/{_failThreshold}): {ex.Message}");

            if (_failCount >= _failThreshold)
            {
                _isOpen = true;
                GameLogger.Error("CircuitBreaker",
                    $"[{_name}] 熔断！系统将自动在{_resetTimeout.TotalSeconds}秒后尝试恢复");
            }

            fallback?.Invoke();
            return false;
        }
    }
}

// 使用示例
public class NetworkManager
{
    private readonly CircuitBreaker _apiBreaker =
        new CircuitBreaker("API请求", failThreshold: 3, resetTimeoutSeconds: 30f);

    public void SendBattleResult(BattleResultData data)
    {
        _apiBreaker.TryExecute(
            action: () =>
            {
                // 真实API调用
                var response = Http.Post("/api/battle/result", data);
                if (!response.success) throw new Exception(response.error);
            },
            fallback: () =>
            {
                // 降级：存入本地，稍后重试
                LocalPendingQueue.Enqueue("battle_result", data);
                GameLogger.Warning("Network", "API熔断，战斗结果已存入本地队列");
            }
        );
    }
}
```

---

## 七、最佳实践总结

### 7.1 崩溃治理体系完整清单

| 阶段 | 措施 | 工具/方案 |
|------|------|---------|
| **预防** | 代码规范、静态分析 | Roslyn分析器、ReSharper |
| **预防** | 空引用防护 | Nullable引用类型注解 |
| **预防** | 功能开关 | FeatureFlag远程配置 |
| **捕获** | 托管异常全局兜底 | Application.logMessageReceived |
| **捕获** | Native崩溃 | 第三方SDK（Bugly/Firebase Crashlytics）|
| **捕获** | ANR检测 | 看门狗线程 |
| **分析** | 堆栈符号化 | addr2line/ndk-stack |
| **分析** | 崩溃聚合 | 指纹哈希去重 |
| **响应** | 崩溃率告警 | 企微机器人/钉钉Webhook |
| **响应** | 热降级 | FeatureFlag + 熔断器 |
| **复盘** | 崩溃归因 | 日志上下文 + 截图 |

### 7.2 工程落地建议

1. **第三方SDK优先**：Bugly（国内）/ Firebase Crashlytics（海外）覆盖Native崩溃，自研专注业务层
2. **日志分级严格执行**：线上包只开 Info+ 级别，避免日志写入成为性能瓶颈
3. **隐私合规**：上报数据不含个人信息（用户ID脱敏、截图不含聊天内容）
4. **崩溃率KPI**：建立崩溃率基线（如崩溃率<0.1%），版本发布把关指标
5. **一键复现**：崩溃报告中包含的游戏上下文（场景、操作序列）应支持本地重放

### 7.3 常见崩溃类型及预防

```
1. NullReferenceException（最常见）
   预防：启用 C# 8.0 Nullable Reference Types
         代码规范要求所有引用访问前判空

2. IndexOutOfRangeException
   预防：数组/List访问前检查边界
         优先使用 TryGetValue / ElementAtOrDefault

3. Out of Memory（内存OOM）
   预防：对象池复用大对象
         纹理及时Unload，监控内存水位

4. StackOverflowException（递归溢出）
   预防：递归深度限制，用迭代替代深度递归

5. Unity主线程访问非法（跨线程访问UnityAPI）
   预防：子线程操作通过 UnityMainThreadDispatcher 派发回主线程
```

---

## 总结

崩溃与异常捕获体系是游戏质量体系的基础设施。从异常捕获到符号化分析，从告警到熔断降级，每个环节紧密配合，才能形成完整的闭环。

核心心法：
- **快速感知**：崩溃发生→5分钟内告警到达负责人
- **精准定位**：完整堆栈 + 游戏上下文 = 快速复现
- **优雅降级**：出问题时不崩整个游戏，而是优雅降级关闭该功能
- **持续改进**：每次重大崩溃都做RCA（根因分析），避免同类问题复发

建立这套体系，让"线上玩家崩溃"从噩梦变成可控的工程问题。
