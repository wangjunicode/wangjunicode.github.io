---
title: 使用 C# 特性系统构建可扩展的游戏框架元数据体系
published: 2026-03-31
description: 深入解析游戏框架中自定义 Attribute 的设计模式，从执行优先级到编辑器暴露，理解特性如何驱动框架行为。
tags: [Unity, C#特性, 框架设计, 元数据]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## Attribute 是什么，为什么游戏框架大量使用它？

C# 特性（Attribute）是一种**元数据标注机制**：你可以在类、字段、方法上"贴标签"，框架代码通过反射读取这些标签，决定如何处理被标注的对象。

```csharp
// 普通类：没有任何框架感知
public class HeroAI { }

// 带特性的类：框架知道它的执行优先级
[ExecutionPriority(100)]
public class HeroAI { }

// 框架代码
var priority = typeof(HeroAI)
    .GetCustomAttribute<ExecutionPriorityAttribute>()?.priority ?? 0;
// 结果：100
```

游戏框架大量使用特性是因为它实现了**声明式编程**——你只需声明"这个类是什么"，框架自动处理"怎么做"，减少了大量样板代码。

---

## 框架中的核心特性分类

### 1. 执行控制类

```csharp
// 执行优先级：数字越大越先执行
[AttributeUsage(AttributeTargets.Class)]
public class ExecutionPriorityAttribute : Attribute
{
    readonly public int priority;
    public ExecutionPriorityAttribute(int priority) {
        this.priority = priority;
    }
}

// 使用示例：确保某些系统先于其他系统初始化
[ExecutionPriority(1000)]  // 最先执行
public class InputSystem { }

[ExecutionPriority(500)]
public class UISystem { }

[ExecutionPriority(100)]
public class GameLogicSystem { }
```

### 2. 编辑器暴露类

```csharp
// 即使字段是 private，也在 Inspector 中显示
[AttributeUsage(AttributeTargets.Field)]
public class ExposeFieldAttribute : Attribute { }

// 列表编辑器选项
[AttributeUsage(AttributeTargets.Field)]
public class ListInspectorOptionAttribute : Attribute
{
    readonly public bool allowAdd;
    readonly public bool allowRemove;
    readonly public bool showFoldout;
    
    public ListInspectorOptionAttribute(bool allowAdd, bool allowRemove, bool alwaysExpanded) {
        this.allowAdd = allowAdd;
        this.allowRemove = allowRemove;
        this.showFoldout = alwaysExpanded;
    }
}

// 使用示例
public class SkillConfig
{
    [ExposeField]
    private int _internalId;
    
    [ListInspectorOption(allowAdd: true, allowRemove: false, alwaysExpanded: true)]
    public List<int> RequiredItemIds;
}
```

### 3. 类型注册类

```csharp
// 排除某个类不被框架自动注册
[AttributeUsage(AttributeTargets.Class)]
public class DoNotListAttribute : Attribute { }

// 标记单例类型受保护
[AttributeUsage(AttributeTargets.Class)]
public class ProtectedSingletonAttribute : Attribute { }

// AOT 代码生成标记（热更新支持）
[AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct | AttributeTargets.Interface | AttributeTargets.Delegate)]
public class SpoofAOTAttribute : Attribute { }
```

---

## ReflectionTools：高性能反射缓存

框架中有大量反射操作，但反射本身很慢。`ReflectionTools.cs` 通过**缓存**解决这个问题：

```csharp
public static class ReflectionTools
{
    // 线程安全的缓存字典（使用 ConcurrentDictionary）
    private static ConcurrentDictionary<Type, FieldInfo[]> _typeFields;
    private static ConcurrentDictionary<Type, MethodInfo[]> _typeMethods;
    private static ConcurrentDictionary<MemberInfo, object[]> _memberAttributes;
    private static ConcurrentDictionary<Type, string> _typeFriendlyName;
    // ... 更多缓存
    
    public static FieldInfo[] GetFields(Type type)
    {
        return _typeFields.GetOrAdd(type, t => 
            t.GetFields(FLAGS_ALL));  // 首次调用时通过反射获取，结果缓存
    }
    
    public static T GetAttribute<T>(MemberInfo member) where T : Attribute
    {
        var attrs = _memberAttributes.GetOrAdd(member, m => 
            m.GetCustomAttributes(true));
        return attrs.OfType<T>().FirstOrDefault();
    }
}
```

**关键优化**：`ConcurrentDictionary.GetOrAdd` 是线程安全的，且第一次调用后，后续同类型查询都是 O(1) 的字典查找，不再有反射开销。

---

## 特性驱动的节点着色

在可视化节点图（CanvasCore）中，特性被用于声明节点颜色：

```csharp
[Color("ff6d53")]  // 橙红色
abstract public class FSMState : FSMNode, IState { }

[Color("4a90d9")]  // 蓝色
public class ActionNode : FlowNode { }
```

框架在渲染节点时读取 `ColorAttribute`，自动为不同类型的节点着不同颜色，无需在渲染代码中编写 if-else。

---

## [StaticField] 特性：对象池的元数据标记

在 ETTask 框架中，我们见过这个特性：

```csharp
[StaticField]
private static readonly Queue<ETTask> queue = new();
```

`[StaticField]` 是框架自定义的特性，用于标记"这个静态字段在 Domain Reload 时需要被重置"。

Unity 编辑器每次重新编译代码时会做 Domain Reload，静态字段会保留旧值。如果对象池的队列保留了旧的对象引用，可能导致 Bug。

框架通过扫描 `[StaticField]` 标注的字段，在 Domain Reload 时自动清空它们：

```csharp
// 框架启动时（简化版）
#if UNITY_EDITOR
[InitializeOnLoadMethod]
static void ResetStaticFields()
{
    var fields = GetAllStaticFields<StaticFieldAttribute>();
    foreach (var field in fields)
    {
        field.SetValue(null, null);  // 重置为 null
    }
}
#endif
```

---

## 特性的性能注意事项

### 问题：反射在热路径上很慢

```csharp
// ❌ 热路径上反复读取特性（每次都反射）
void Update()
{
    for (each entity)
    {
        var attr = entity.GetType().GetCustomAttribute<PriorityAttribute>();
        // ...
    }
}
```

### 解决方案：一次缓存，多次使用

```csharp
// ✅ 启动时缓存到字典
private static Dictionary<Type, int> _priorityCache = new();

void InitPriorities(IEnumerable<Type> types)
{
    foreach (var type in types)
    {
        var attr = type.GetCustomAttribute<ExecutionPriorityAttribute>();
        _priorityCache[type] = attr?.priority ?? 0;
    }
}

void Update()
{
    for (each entity)
    {
        int priority = _priorityCache[entity.GetType()];  // O(1) 字典查找
        // ...
    }
}
```

---

## 实战：自定义消息处理特性

下面是一个基于特性的消息处理系统示例：

```csharp
// 定义特性
[AttributeUsage(AttributeTargets.Method)]
public class MessageHandlerAttribute : Attribute
{
    public Type MessageType { get; }
    public MessageHandlerAttribute(Type messageType) 
    {
        MessageType = messageType;
    }
}

// 使用特性
public class UIManager
{
    [MessageHandler(typeof(PlayerDiedMessage))]
    private void OnPlayerDied(PlayerDiedMessage msg)
    {
        ShowGameOverScreen();
    }
    
    [MessageHandler(typeof(ScoreChangedMessage))]
    private void OnScoreChanged(ScoreChangedMessage msg)
    {
        UpdateScoreDisplay(msg.NewScore);
    }
}

// 框架自动注册（启动时扫描一次）
public class MessageSystem
{
    private Dictionary<Type, List<Action<object>>> _handlers = new();
    
    public void RegisterAllHandlers(object target)
    {
        var methods = target.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        
        foreach (var method in methods)
        {
            var attr = method.GetCustomAttribute<MessageHandlerAttribute>();
            if (attr == null) continue;
            
            var handler = (Action<object>)(msg => method.Invoke(target, new[] { msg }));
            
            if (!_handlers.TryGetValue(attr.MessageType, out var list))
                _handlers[attr.MessageType] = list = new List<Action<object>>();
            
            list.Add(handler);
        }
    }
}
```

---

## 总结

C# 特性系统在游戏框架中的价值：

| 应用场景 | 特性名称 | 作用 |
|---------|---------|------|
| 执行顺序控制 | ExecutionPriority | 声明系统初始化顺序 |
| 编辑器集成 | ExposeField, ListInspectorOption | 控制 Inspector 显示 |
| 类型注册 | DoNotList, ProtectedSingleton | 影响框架类型扫描 |
| 节点可视化 | Color | 声明节点颜色 |
| 热重载支持 | StaticField | 标记需要重置的静态字段 |
| AOT 支持 | SpoofAOT | 标记需要 AOT 代码生成的类型 |

特性是游戏框架"元编程"能力的核心工具。理解了特性驱动的设计，你就能看懂框架代码中大量"神奇"的自动行为背后的机制。
