---
title: 游戏Debug工具链：运行时控制台与作弊菜单
published: 2026-03-31
description: 深度解析游戏内Debug工具链的工程实现，包括运行时悬浮控制台（日志捕获与显示）、作弊指令系统（命令注册与解析）、性能监控HUD（FPS/内存/DrawCall）、远程日志上报（开发阶段实时查看设备日志）、条件编译确保发布包干净，以及开发者菜单的UI设计。
tags: [Unity, Debug工具, 开发工具, 作弊菜单, 工程实践]
category: 工具链开发
draft: false
---

## 一、运行时日志控制台

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 运行时控制台（真机调试必备）
/// </summary>
public class RuntimeConsole : MonoBehaviour
{
    [Header("激活方式")]
    [SerializeField] private KeyCode toggleKey = KeyCode.BackQuote; // `键
    [SerializeField] private int tapCountToShow = 5;                // 触摸次数激活
    [SerializeField] private float tapInterval = 2f;                // 连续点击时间窗口

    [Header("样式")]
    [SerializeField] private int maxLogCount = 200;
    [SerializeField] private bool showOnError = true;

    private struct LogEntry
    {
        public string Message;
        public LogType Type;
        public DateTime Time;
    }

    private List<LogEntry> logs = new List<LogEntry>();
    private bool isVisible;
    private Vector2 scrollPos;
    private string filterText = "";
    
    // 触摸激活
    private int tapCount;
    private float tapTimer;

    void OnEnable()
    {
        Application.logMessageReceived += HandleLog;
    }

    void OnDisable()
    {
        Application.logMessageReceived -= HandleLog;
    }

    void HandleLog(string message, string stackTrace, LogType type)
    {
        logs.Add(new LogEntry
        {
            Message = message,
            Type = type,
            Time = DateTime.Now
        });
        
        // 超出上限时移除最旧的
        while (logs.Count > maxLogCount)
            logs.RemoveAt(0);
        
        // 错误自动显示控制台
        if (showOnError && (type == LogType.Error || type == LogType.Exception))
            isVisible = true;
    }

    void Update()
    {
        // 键盘切换
        if (Input.GetKeyDown(toggleKey))
            isVisible = !isVisible;
        
        // 触摸激活（适用于移动端）
        if (Input.touchCount > 0 && Input.GetTouch(0).phase == TouchPhase.Began)
        {
            tapTimer = tapInterval;
            tapCount++;
            if (tapCount >= tapCountToShow)
            {
                tapCount = 0;
                isVisible = !isVisible;
            }
        }
        
        if (tapTimer > 0) tapTimer -= Time.unscaledDeltaTime;
        else tapCount = 0;
    }

    void OnGUI()
    {
        if (!isVisible) return;
        
        // 半透明背景
        GUI.Box(new Rect(0, 0, Screen.width * 0.6f, Screen.height * 0.7f), "Runtime Console");
        
        float y = 30;
        float w = Screen.width * 0.6f - 20;
        
        // 过滤输入
        filterText = GUI.TextField(new Rect(10, y, w - 70, 25), filterText);
        if (GUI.Button(new Rect(w - 55, y, 50, 25), "Clear"))
            logs.Clear();
        
        y += 30;
        
        // 日志列表
        Rect viewRect = new Rect(10, y, w, Screen.height * 0.7f - y - 10);
        float contentHeight = Mathf.Max(logs.Count * 22, viewRect.height);
        Rect contentRect = new Rect(0, 0, viewRect.width - 20, contentHeight);
        
        scrollPos = GUI.BeginScrollView(viewRect, scrollPos, contentRect);
        
        float itemY = 0;
        foreach (var log in logs)
        {
            if (!string.IsNullOrEmpty(filterText) && 
                !log.Message.Contains(filterText, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            
            // 根据日志类型设置颜色
            string colorHex = log.Type switch
            {
                LogType.Error     => "ff4444",
                LogType.Exception => "ff4444",
                LogType.Warning   => "ffaa00",
                LogType.Log       => "ffffff",
                _ => "aaaaaa"
            };
            
            GUI.Label(
                new Rect(0, itemY, contentRect.width, 22),
                $"<color=#{colorHex}>[{log.Time:HH:mm:ss}] {log.Message}</color>");
            
            itemY += 22;
        }
        
        GUI.EndScrollView();
        
        // 关闭按钮
        if (GUI.Button(new Rect(Screen.width * 0.6f - 60, 0, 60, 25), "✕"))
            isVisible = false;
    }
}
```

---

## 二、作弊指令系统

```csharp
/// <summary>
/// 作弊指令管理器（开发构建专用）
/// </summary>
public class CheatCommandSystem : MonoBehaviour
{
    private static CheatCommandSystem instance;
    public static CheatCommandSystem Instance => instance;

    private Dictionary<string, CheatCommand> commands 
        = new Dictionary<string, CheatCommand>(StringComparer.OrdinalIgnoreCase);
    
    private string inputBuffer = "";
    private List<string> commandHistory = new List<string>();
    private int historyIndex = -1;

    public class CheatCommand
    {
        public string Name;
        public string Description;
        public string Usage;
        public Action<string[]> Execute;
        public bool RequiresDevBuild = true; // 仅开发构建可用
    }

    void Awake()
    {
        instance = this;
        RegisterBuiltinCommands();
    }

    void RegisterBuiltinCommands()
    {
        Register("gold", "add_gold <amount>", "给予金币", args =>
        {
            int amount = args.Length > 0 && int.TryParse(args[0], out int n) ? n : 10000;
            CurrencyManager.Instance?.AddGold(amount);
            Debug.Log($"[Cheat] Added {amount} gold");
        });

        Register("level", "set_level <level>", "设置玩家等级", args =>
        {
            int level = args.Length > 0 && int.TryParse(args[0], out int n) ? n : 10;
            PlayerDataService.GetLocalPlayerData().Level = level;
            Debug.Log($"[Cheat] Set level to {level}");
        });

        Register("god", "god [0/1]", "无敌模式开关", args =>
        {
            bool enable = args.Length == 0 || args[0] != "0";
            FindObjectOfType<PlayerController>()?.SetGodMode(enable);
            Debug.Log($"[Cheat] God mode: {enable}");
        });

        Register("kill_all", "", "消灭所有敌人", _ =>
        {
            foreach (var enemy in FindObjectsOfType<EnemyController>())
                enemy.Die();
            Debug.Log("[Cheat] Killed all enemies");
        });

        Register("fps", "fps <target>", "设置目标帧率", args =>
        {
            int fps = args.Length > 0 && int.TryParse(args[0], out int n) ? n : 60;
            Application.targetFrameRate = fps;
            Debug.Log($"[Cheat] Target FPS: {fps}");
        });

        Register("timescale", "timescale <scale>", "设置时间缩放", args =>
        {
            float scale = args.Length > 0 && float.TryParse(args[0], out float f) ? f : 1f;
            Time.timeScale = Mathf.Clamp(scale, 0.1f, 10f);
            Debug.Log($"[Cheat] Time scale: {Time.timeScale}");
        });

        Register("teleport", "teleport <x> <y> <z>", "传送到坐标", args =>
        {
            if (args.Length >= 3 && 
                float.TryParse(args[0], out float x) &&
                float.TryParse(args[1], out float y) &&
                float.TryParse(args[2], out float z))
            {
                var player = FindObjectOfType<PlayerController>();
                if (player != null)
                    player.transform.position = new Vector3(x, y, z);
            }
        });

        Register("help", "", "显示所有命令", _ =>
        {
            foreach (var cmd in commands.Values)
                Debug.Log($"[Help] {cmd.Name}: {cmd.Description} | {cmd.Usage}");
        });
    }

    public void Register(string name, string usage, string description, Action<string[]> execute)
    {
        commands[name] = new CheatCommand
        {
            Name = name,
            Description = description,
            Usage = usage,
            Execute = execute
        };
    }

    public void Execute(string input)
    {
        input = input.Trim();
        if (string.IsNullOrEmpty(input)) return;
        
        commandHistory.Insert(0, input);
        if (commandHistory.Count > 50) commandHistory.RemoveAt(50);
        historyIndex = -1;
        
        string[] parts = input.Split(' ');
        string cmdName = parts[0];
        string[] args = parts.Length > 1 ? 
            parts[1..] : Array.Empty<string>();
        
        if (commands.TryGetValue(cmdName, out var cmd))
        {
            // 发布版本禁止作弊
            #if !UNITY_EDITOR && !DEVELOPMENT_BUILD
            if (cmd.RequiresDevBuild)
            {
                Debug.LogWarning("[Cheat] Dev build only command");
                return;
            }
            #endif
            
            try { cmd.Execute(args); }
            catch (Exception e) { Debug.LogError($"[Cheat] Command error: {e.Message}"); }
        }
        else
        {
            Debug.LogWarning($"[Cheat] Unknown command: {cmdName}. Type 'help' for list.");
        }
    }
}
```

---

## 三、性能监控 HUD

```csharp
/// <summary>
/// 性能监控 HUD（开发期常驻）
/// </summary>
public class PerformanceHUD : MonoBehaviour
{
    [SerializeField] private bool showInRelease;    // 是否在发布版显示
    [SerializeField] private KeyCode toggleKey = KeyCode.F1;

    private bool isVisible = true;
    
    // FPS 计算
    private float fps;
    private float fpsTimer;
    private int frameCount;
    private float minFps = float.MaxValue;
    private float maxFps = float.MinValue;

    void Update()
    {
        if (Input.GetKeyDown(toggleKey)) isVisible = !isVisible;
        
        frameCount++;
        fpsTimer += Time.unscaledDeltaTime;
        
        if (fpsTimer >= 0.5f)
        {
            fps = frameCount / fpsTimer;
            minFps = Mathf.Min(minFps, fps);
            maxFps = Mathf.Max(maxFps, fps);
            frameCount = 0;
            fpsTimer = 0;
        }
    }

    void OnGUI()
    {
        #if !UNITY_EDITOR && !DEVELOPMENT_BUILD
        if (!showInRelease) return;
        #endif
        
        if (!isVisible) return;
        
        int x = 10, y = 10, lineH = 20, w = 200;
        
        Color fpsColor = fps >= 55 ? Color.green : fps >= 30 ? Color.yellow : Color.red;
        DrawLabel(x, y, w, lineH, $"FPS: {fps:F0} (min:{minFps:F0} max:{maxFps:F0})", fpsColor);
        y += lineH;
        
        long totalMem = GC.GetTotalMemory(false) / 1024 / 1024;
        DrawLabel(x, y, w, lineH, $"GC Memory: {totalMem} MB", Color.white);
        y += lineH;
        
        DrawLabel(x, y, w, lineH, $"Time: {Time.time:F1}s x{Time.timeScale:F1}", Color.white);
    }

    void DrawLabel(int x, int y, int w, int h, string text, Color color)
    {
        GUI.color = new Color(0, 0, 0, 0.6f);
        GUI.Box(new Rect(x - 2, y - 2, w + 4, h + 4), "");
        GUI.color = color;
        GUI.Label(new Rect(x, y, w, h), text);
        GUI.color = Color.white;
    }
}
```

---

## 四、工具可用性矩阵

| 工具 | Editor | Dev Build | Release |
|------|--------|-----------|---------|
| 运行时控制台 | ✓ | ✓ | ✗ |
| 作弊菜单 | ✓ | ✓ | ✗ |
| 性能HUD | ✓ | ✓ | 可选 |
| 远程日志 | ✓ | ✓ | ✗ |
| Gizmos调试 | ✓ | ✗ | ✗ |

**条件编译宏：**
- `UNITY_EDITOR`：仅 Unity Editor 中可用
- `DEVELOPMENT_BUILD`：开发构建可用（Build Settings 中勾选）
- 自定义：`DEBUG_TOOLS`（在 Player Settings 中添加 Define Symbols）
