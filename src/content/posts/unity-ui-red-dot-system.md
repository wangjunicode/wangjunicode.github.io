---
title: Unity游戏红点系统设计与实现
published: 2026-03-31
description: 深度解析游戏UI红点（小红点/未读提示）系统的完整架构，从观察者模式到系统类型映射，再到组件自动注册与销毁的完整生命周期管理。
tags: [Unity, UI系统, 红点系统, 观察者模式]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏红点系统设计与实现

## 红点系统的本质

手游中的红点（小红点、未读提示）是驱动玩家点击探索的核心 UI 元素。当背包有新道具、任务有更新、邮件未读时，对应按钮上就会出现一个红色圆点或数字角标。

看似简单，但红点系统在工程实现上有几个挑战：

1. **多处复用**：同一个"背包有新道具"的信息，可能需要在主界面按钮、侧边栏、某个子菜单上同时显示
2. **跨层通信**：数据层（背包数量变化）需要通知 UI 层（红点显示/隐藏），但不能直接耦合
3. **自动管理**：红点组件挂在各种 GameObject 上，需要自动注册/注销，不能靠手动管理
4. **数量显示**：有时候红点只显示"有/无"，有时候需要显示具体数量（"3"、"99+"）

本文通过真实项目的 `RedDotBind.cs` 和 `RedDotHelper.cs` 源码，完整讲解这套系统。

---

## 核心组件：RedDotBind

```csharp
public class RedDotBind : MonoBehaviour
{
    [SerializeField]
    [LabelText("文本")]
    private TextMeshProUGUI m_Text;   // 可选：显示数量的文本组件

    [SerializeField]
    [LabelText("红点枚举")]
    private ERedDotKeyType m_Key;     // 这个红点绑定的是哪种类型的未读提示

    public ERedDotKeyType Key => m_Key;

    [ShowInInspector]
    [ReadOnly]
    public bool Show { get; private set; }  // 当前是否显示

    [ShowInInspector]
    [ReadOnly]
    public int Count { get; private set; }  // 当前数量
}
```

`ERedDotKeyType` 是一个枚举，枚举的每个值代表一种类型的未读提示（背包、任务、成就等）。设计师只需要在 Inspector 中选择这个枚举值，不需要写任何代码，红点就能自动工作。

---

## 自动注册与注销机制

```csharp
private void Awake()
{
    if(Key != ERedDotKeyType.None)
        SetKey(m_Key);
}

public void SetKey(ERedDotKeyType key)
{
    // 先注销旧的监听（防止重复注册）
    YIUIFramework.RedDotMgr.Inst?.RemoveChanged((int)m_Key, OnRedDotChangeHandler);
    m_Key = key;
    // 注册新的监听
    YIUIFramework.RedDotMgr.Inst?.AddChanged((int)m_Key, OnRedDotChangeHandler);
}

private void OnDestroy()
{
    // 销毁时必须注销，否则 RedDotMgr 持有死亡对象的引用会导致空引用异常
    if (YIUIFramework.SingletonMgr.Disposing)
        return;  // 框架正在关闭，跳过（避免在销毁顺序问题上崩溃）
    YIUIFramework.RedDotMgr.Inst?.RemoveChanged((int)Key, OnRedDotChangeHandler);
}
```

这套注册/注销逻辑遵循了观察者模式的标准生命周期：
1. `Awake` 注册监听
2. 运行时通过 `SetKey` 动态切换监听目标
3. `OnDestroy` 注销监听

注意 `OnDestroy` 中有一个关键判断：`if (YIUIFramework.SingletonMgr.Disposing) return;`

这处理了游戏退出时的特殊情况：当整个框架（SingletonMgr）都在销毁时，访问 `RedDotMgr.Inst` 可能返回 null 或已经销毁的对象。提前检测并跳过，避免了退出时的报错。

---

## 红点变化处理

```csharp
private void OnRedDotChangeHandler(int count)
{
    if (this == null) return;  // 组件已被销毁的安全检查
    Show = count >= 1;         // 有数量就显示
    Count = count;
    Refresh();
}

private void Refresh()
{
    if (this == null) return;
    gameObject.SetActive(Show);           // 控制红点对象的显隐
    if (m_Text != null)
        m_Text.text = Count.ToString();   // 如果有文本组件，显示数量
}
```

`if (this == null)` 这个检查在 C# 中很特殊——在 Unity 中，`this == null` 对于已销毁的 MonoBehaviour 会返回 `true`（Unity 重载了 `==` 运算符）。这是异步回调中防止空引用的常用技巧。

`gameObject.SetActive(Show)` 控制的是红点 GameObject 的显隐，而不是 RedDotBind 组件本身。通常的用法是：
- 把红点的视觉元素（红色圆圈图片）放在一个子 GameObject 上
- 把 `RedDotBind` 挂在这个子 GameObject 上
- `gameObject.SetActive(false)` 就隐藏了整个红点视觉

---

## 系统类型到红点类型的映射

```csharp
public static class RedDotHelper
{
    public static ERedDotKeyType SysTypeToRedDotKeyType(ESystemType eSystemType)
    {
        switch (eSystemType)
        {
            case ESystemType.Cultivate:
                return ERedDotKeyType.Key1;    // 培养系统
            case ESystemType.Achievement:
                return ERedDotKeyType.Key2;    // 成就系统
            default:
                return ERedDotKeyType.None;    // 未映射的系统，不显示红点
        }
    }
}
```

`RedDotHelper` 提供了从游戏系统枚举（`ESystemType`）到红点枚举（`ERedDotKeyType`）的映射。

这种设计的好处：
- **分离关注点**：游戏业务逻辑只关心"哪个系统有更新"，不关心红点的具体 Key
- **集中管理**：所有系统→红点的映射关系在一个地方，便于维护
- **可扩展**：新增系统时，只需要在这个 switch 里加一条 case，不需要修改其他代码

---

## RedDotMgr 的工作原理

虽然 `RedDotMgr` 的源码不在当前文件中，但从使用方式可以推断出它的设计：

```csharp
// 推断的 RedDotMgr 核心结构（伪代码）
public class RedDotMgr
{
    // Key: 红点类型(int), Value: 监听该类型的回调列表
    private Dictionary<int, List<Action<int>>> _listeners 
        = new Dictionary<int, List<Action<int>>>();
    
    // Key: 红点类型(int), Value: 当前数量
    private Dictionary<int, int> _counts = new Dictionary<int, int>();
    
    // 数据层调用这个方法更新红点数量
    public void SetCount(int key, int count)
    {
        _counts[key] = count;
        // 通知所有监听该 key 的组件
        if (_listeners.TryGetValue(key, out var callbacks))
        {
            foreach (var callback in callbacks)
                callback.Invoke(count);
        }
    }
    
    // RedDotBind 注册监听
    public void AddChanged(int key, Action<int> callback)
    {
        if (!_listeners.ContainsKey(key))
            _listeners[key] = new List<Action<int>>();
        _listeners[key].Add(callback);
        
        // 注册时立即回调一次当前值（初始化状态）
        if (_counts.TryGetValue(key, out int count))
            callback.Invoke(count);
    }
    
    // RedDotBind 注销监听
    public void RemoveChanged(int key, Action<int> callback)
    {
        if (_listeners.TryGetValue(key, out var callbacks))
            callbacks.Remove(callback);
    }
}
```

这是经典的**发布-订阅（Pub-Sub）**模式：
- 数据层（业务逻辑）调用 `SetCount(key, count)` 发布更新
- UI 层（RedDotBind）通过 `AddChanged` 订阅特定 key 的变化
- RedDotMgr 作为中间人，负责连接两端

---

## 红点数量更新的完整流程

```
后台数据变化（比如收到新邮件）
    ↓
业务逻辑层：
    int unreadCount = mailComp.GetTotalUnreadCount();
    RedDotMgr.Inst.SetCount((int)ERedDotKeyType.Mail, unreadCount);
    ↓
RedDotMgr 遍历所有订阅 ERedDotKeyType.Mail 的回调
    ↓
每个 RedDotBind.OnRedDotChangeHandler(count) 被调用
    ↓
Show = count >= 1; Count = count;
    ↓
gameObject.SetActive(Show)  ← 红点显示或隐藏
m_Text.text = count.ToString()  ← 数量文本更新
```

---

## 实践建议

### 红点枚举的设计
```csharp
public enum ERedDotKeyType
{
    None = 0,
    
    // 主界面导航按钮
    Key_Bag,       // 背包
    Key_Mail,      // 邮件
    Key_Task,      // 任务
    Key_Achievement, // 成就
    Key_Shop,      // 商店
    
    // 子界面红点
    Key_EquipUpgrade,  // 装备升级
    Key_SkillUnlock,   // 技能解锁
}
```

枚举设计建议：
1. `None = 0` 作为无效值，便于判空
2. 按业务模块组织，加注释
3. 主界面和子界面红点分开，便于维护层级关系

### 红点层级联动
如果"背包"子系统有未读，那"背包"按钮上的红点应该显示，但"主界面"上的"其他功能"入口也可能需要显示红点。这涉及红点层级联动，进阶实现会在 RedDotMgr 中维护父子关系，子节点有红点时自动更新父节点。

### Inspector 中的配置
```
[GameObject: 背包按钮]
    └── [GameObject: RedDot] 
            ├── Image (红色圆圈)
            └── TextMeshProUGUI (数量文本，可选)
            └── RedDotBind
                    ├── m_Text: [TextMeshProUGUI]
                    └── m_Key: Key_Bag
```

---

## 总结

红点系统的设计优雅地解决了"数据层驱动 UI 层"的通信问题：

- **观察者模式**：数据变化时，所有关注的红点自动更新
- **组件化**：`RedDotBind` 挂在哪里就在哪里显示，零配置
- **自动生命周期**：`Awake`/`OnDestroy` 自动注册/注销，不需要手动管理
- **映射辅助**：`RedDotHelper` 提供系统枚举到红点枚举的集中映射

对于初学者，这个系统是学习**观察者模式在游戏 UI 中应用**的绝佳案例。把它吃透，然后尝试自己实现一个类似的通知系统，你对设计模式的理解会上升一个台阶。
