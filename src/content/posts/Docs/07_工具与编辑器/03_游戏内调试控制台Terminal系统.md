# 游戏内调试控制台 Terminal 系统设计

## 1. 系统概述

本项目内置了一套完整的**游戏内调试控制台（Terminal）**，可在运行时输入命令调用游戏内的函数、修改属性值，方便 QA 测试和开发调试，无需重新编译或连接 IDE。

**系统层次：**

```
用户输入
    ↓
GameConsoleInput（UI 输入框，历史记录、Tab补全）
    ↓
Lexer（词法分析：切词）
    ↓
SyntaxAnalyzer（语法分析：构建语法树）
    ↓
VirtualMachine（执行器：反射调用方法/属性）
    ↓
CommandSystem（命令注册与发现：[GameCommand] 特性）
    ↑
ConsoleSystem（输出管理：日志、颜色、过滤）
    ↑
GameConsoleRenderer（UI 渲染：输出列表虚拟滚动）
```

---

## 2. 命令注册（CommandSystem）

### 2.1 `[GameCommand]` 特性标注

```csharp
// 任何静态方法都可以通过 [GameCommand] 变成控制台命令
// 无需手动注册，CommandSystem 在初始化时自动扫描所有程序集

[GameCommand("give_item", "给予玩家道具", tag: "debug")]
private static void GiveItem(int itemId, int count)
{
    var backpack = SceneUtil.FirstClientScene().Backpack();
    backpack.AddItem(itemId, count);
    Debug.Log($"[CMD] 给予道具 {itemId} x {count}");
}

[GameCommand("set_hp", "设置角色血量", tag: "battle")]
private static void SetHp(long unitId, int hp)
{
    var unit = UnitComponent.Instance.Get(unitId);
    if (unit == null) { Debug.LogWarning("Unit not found"); return; }
    NumericSystem.SetHp(unit, hp);
}

// 也支持无参数命令
[GameCommand("clear_log", "清除控制台日志")]
private static void ClearLog()
{
    ConsoleSystem.Instance.Clear();
}
```

### 2.2 命令自动发现

```csharp
// 位置：Terminal/Console/CommandSystem.cs
// CommandCreator 通过反射扫描所有类型，找到标注了 [CommandAttribute] 的静态方法
public static class CommandCreator
{
    public static IEnumerable<Command> CollectCommands<T>(Type[] types) where T : CommandAttribute
    {
        foreach (var type in types)
        {
            // 扫描所有静态方法（public/private/internal 都支持）
            foreach (var methodInfo in type.GetMethods(
                BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public))
            {
                var attribute = methodInfo.GetCustomAttribute<T>();
                if (attribute == null) continue;
                
                yield return new Command(
                    name: attribute.Name,
                    description: attribute.Description,
                    tag: attribute.Tag,
                    method: methodInfo,
                    configGroup: attribute.ConfigGroup);
            }
        }
    }
}

// Command 类封装了静态方法调用
public class Command : StackMethod
{
    public readonly string name;
    public readonly string description;
    public readonly string tag;
    
    // 检查是否有指定 tag（用于过滤显示）
    public bool CompareTag(string tag)
    {
        if (string.IsNullOrEmpty(tag)) return true;  // 空 tag 匹配所有
        return this.tag == tag;
    }
    
    public override string ToString() => $"{name} : {description}";
}
```

---

## 3. 语法分析（Lexer + SyntaxAnalyzer）

### 3.1 词法分析（Lexer）

```csharp
// 位置：Terminal/Core/Lexer.cs
// 将用户输入字符串切分为 Token 列表

// 输入："give_item 1001 5"
// → Token: [Identifier("give_item"), Int(1001), Int(5)]

// 输入："player.hp = 100"
// → Token: [Identifier("player"), Dot, Identifier("hp"), Assign, Int(100)]

// 输入："skills[2].damage"
// → Token: [Identifier("skills"), LBracket, Int(2), RBracket, Dot, Identifier("damage")]

// Lexer 支持的 Token 类型：
// - Identifier：字母数字下划线构成的标识符（命令名、变量名）
// - Int / Float / Bool / String：字面量
// - Dot / Assign / LBracket / RBracket：操作符
```

### 3.2 语法分析与 VirtualMachine 执行

```csharp
// 位置：Terminal/Core/VirtualMachine.cs
// 通过 C# 反射执行语法树节点

// IValueGetter：只读属性（get）
// IValueSetter：只写属性（set）
// IValueProperty：可读写属性（get + set）
// ICallable：可调用方法

public interface IValueGetter
{
    Type ValueType { get; }
    object GetValue();
}

public interface IValueSetter
{
    string Name { get; }
    Type ValueType { get; }
    void SetValue(object value);
}

// VirtualMachine 示例：执行 "player.hp = 100"
// 1. 在已注册对象中找到 "player" 对象（类型反射）
// 2. 找到 "hp" 属性（PropertyInfo）
// 3. 将 "100"（Int Token）类型转换为属性的实际类型
// 4. 调用 PropertyInfo.SetValue(player, 100)
```

---

## 4. UI 层（GameConsole）

### 4.1 输入框功能

```csharp
// 位置：Terminal/UnityImpl/GameConsoleInput.cs
public class GameConsoleInput : MonoBehaviour
{
    // 命令历史记录（上/下方向键翻历史）
    private readonly List<string> _inputHistory = new();
    private int _historyIndex = -1;
    
    void Update()
    {
        if (!_inputField.isFocused) return;
        
        // Tab 键触发自动补全
        if (Input.GetKeyDown(KeyCode.Tab))
        {
            var suggestions = SuggestionQuery.GetSuggestions(_inputField.text);
            if (suggestions.Count == 1)
            {
                // 唯一匹配：直接补全
                _inputField.text = suggestions[0].TransInputTxt(_inputField.text);
                _inputField.caretPosition = _inputField.text.Length;
            }
            else if (suggestions.Count > 1)
            {
                // 多个匹配：显示候选列表
                ShowSuggestionPanel(suggestions);
            }
        }
        
        // 上方向键：翻出历史命令
        if (Input.GetKeyDown(KeyCode.UpArrow) && _inputHistory.Count > 0)
        {
            _historyIndex = Mathf.Clamp(_historyIndex + 1, 0, _inputHistory.Count - 1);
            _inputField.text = _inputHistory[_historyIndex];
        }
        
        // 回车键：执行命令
        if (Input.GetKeyDown(KeyCode.Return))
        {
            ExecuteCommand(_inputField.text);
            _inputHistory.Insert(0, _inputField.text);  // 最新命令插入到列表头
            _inputField.text = string.Empty;
            _historyIndex = -1;
        }
    }
}
```

### 4.2 输出渲染（虚拟滚动）

```csharp
// 位置：Terminal/UnityImpl/GameConsoleRenderer.cs
// 大量日志时使用虚拟滚动（只渲染可见区域的文本，避免 UI 性能问题）
public class GameConsoleRenderer : MonoBehaviour
{
    [SerializeField] private int _maxVisibleLines = 30;
    [SerializeField] private ScrollRect _scrollRect;
    
    private List<ConsoleLog> _allLogs = new();  // 全量日志
    private List<TMP_Text> _visibleTexts = new();  // 只创建可见数量的 Text 组件
    
    // 更新显示（只更新可见区域）
    private void RefreshDisplay()
    {
        int startIndex = CalculateStartIndex();  // 根据滚动位置计算起始 log 索引
        
        for (int i = 0; i < _maxVisibleLines; i++)
        {
            int logIndex = startIndex + i;
            if (logIndex >= _allLogs.Count)
            {
                _visibleTexts[i].gameObject.SetActive(false);
                continue;
            }
            
            var log = _allLogs[logIndex];
            _visibleTexts[i].text = log.message;
            _visibleTexts[i].color = log.color;
            _visibleTexts[i].gameObject.SetActive(true);
        }
    }
}
```

---

## 5. 调试辅助命令示例

```csharp
// DebugHelper.cs - 常用调试命令集合
public static class DebugHelper
{
    // 战斗相关
    [GameCommand("battle_win", "立即获胜", tag: "battle")]
    private static void ForceBattleWin() => BattleManager.Instance.ForceWin();
    
    [GameCommand("battle_lose", "立即失败", tag: "battle")]
    private static void ForceBattleLose() => BattleManager.Instance.ForceLose();
    
    [GameCommand("godmode", "无敌模式 0/1", tag: "battle")]
    private static void SetGodMode(int enable)
    {
        BattleDebugConfig.GodMode = enable == 1;
        Debug.Log($"[CMD] 无敌模式: {BattleDebugConfig.GodMode}");
    }
    
    // 网络调试
    [GameCommand("lag_simulate", "模拟网络延迟(ms)", tag: "network")]
    private static void SimulateLag(int delayMs)
    {
        NetworkSimulator.Instance.SetDelay(delayMs);
    }
    
    // UI 调试
    [GameCommand("open_panel", "打开指定面板", tag: "ui")]
    private static async void OpenPanel(string panelName)
    {
        await YIUIPanelMgr.Instance.OpenAsync(panelName);
    }
}
```

---

## 6. 常见问题与最佳实践

**Q: 控制台在正式版（Release）包里会不会造成安全问题？**  
A: 通过编译宏控制：`#if DEBUG || UNITY_EDITOR` 包裹 `[GameCommand]` 方法，正式包不编译这些代码。同时控制台 UI 默认隐藏，只能通过特定手势（如五指同时触屏）激活。

**Q: VirtualMachine 用反射性能如何？**  
A: 调试控制台是低频操作（手动输入命令），反射开销完全可接受。注意不要将 VirtualMachine 用于游戏逻辑热路径（如每帧调用）。

**Q: 如何给命令添加权限管控（防止玩家乱用）？**  
A: 通过 `configGroup` 字段分组：`configGroup=1` 为 QA 用命令，`configGroup=2` 为开发命令，`configGroup=3` 为管理员命令。游戏版本通过配置控制开放的 group 级别。
