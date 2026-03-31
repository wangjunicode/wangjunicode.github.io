---
title: 游戏 Loading 界面状态机设计
published: 2026-03-31
description: 深入解析游戏场景切换 Loading 界面的状态机设计，包含最小展示时间保证、取消令牌机制、以及 Loading 与业务逻辑之间的解耦方案。
tags: [Unity, Loading系统, 状态机, UI设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏 Loading 界面状态机设计

## 前言

切换场景时出现的 Loading 界面，看似简单，实则藏着不少设计挑战：
- 加载太快时 Loading 闪一下就消失，体验很差
- 加载很慢时需要显示进度条，不能卡死
- 多个异步操作同时完成时，Loading 的关闭时机如何确定？
- 如果用户在 Loading 期间点击了"返回"，如何安全取消？

本文通过 `UILoadingComponent` 的状态机设计，揭示这些问题的解决方案。

---

## 一、Loading 状态机

```csharp
public enum ELoadingState
{
    Idle,       // 空闲（未显示）
    Opening,    // 正在打开（入场动画）
    Looping,    // 循环中（正在加载）
    CanClose,   // 可以关闭（加载完成，等待动画）
    Closing,    // 正在关闭（出场动画）
}
```

这五个状态构成了一个单向状态机：

```
Idle → Opening → Looping → CanClose → Closing → Idle
```

### 1.1 为什么需要 `CanClose` 状态？

如果加载立刻完成（比如资源已缓存），可能仅仅几毫秒后 Loading 就应该关闭。但直接从 `Opening`（入场动画）跳到 `Closing`（出场动画）会导致视觉闪烁。

`CanClose` 是一个"待命"状态：加载完成后，进入 `CanClose`；当入场动画结束后，才真正切换到 `Closing`。这保证了最短展示时间。

---

## 二、最小展示时间保证

```csharp
public class UILoadingComponent : Entity, IAwake
{
    public bool ShouldWaitMinLoop;       // 是否需要等待最小循环时间
    public int  MinLoopWaitTime;         // 最小展示时间（毫秒）
    public ETCancellationToken MinLoopWaitToken;  // 取消令牌
}
```

### 2.1 ETCancellationToken 的使用

```csharp
// 启动 Loading 时设置最小展示时间
public static async ETTask StartLoading(this UILoadingComponent self)
{
    self.ShouldWaitMinLoop = true;
    self.MinLoopWaitToken  = new ETCancellationToken();

    // 等待最小时间（比如 500ms）
    await TimerComponent.Instance.WaitAsync(
        self.MinLoopWaitTime,
        self.MinLoopWaitToken);  // 支持取消

    // 时间到了，可以关闭
    self.ShouldWaitMinLoop = false;
}
```

`ETCancellationToken` 是 ET 框架的取消令牌，类似 C# 的 `CancellationToken`。当用户主动取消（比如强制退出 Loading）时，向 Token 传递取消信号，正在 `await` 的等待操作会提前返回，而不是继续傻等。

这避免了"用户已经取消了，Loading 还在傻等 500ms"的问题。

---

## 三、ShouldWaitHide 标志

```csharp
public bool ShouldWaitHide;  // 是否需要等待关闭的标志
```

这个标志表示"Loading 已经收到了关闭请求，但还在等待某个条件（比如最小展示时间）才能真正关闭"。

```
业务逻辑：加载完成 → HideLoading()
                            ↓
        ShouldWaitHide = true（记录"应该关闭"的意图）
                            ↓
                   检查 ShouldWaitMinLoop
                    ↙              ↘
              false                true
         直接关闭            等待 MinLoopWaitToken
                                    ↓
                         等待结束后，检查 ShouldWaitHide
                         → true → 执行关闭
```

`ShouldWaitHide` 是意图的保存：即使关闭请求来得早，意图也不会丢失。

---

## 四、LoadingUniqueID：防止错误关闭

```csharp
public int LoadingUniqueID;  // 唯一标识符
```

场景中可能同时有多个 Loading 请求。比如：

1. 系统 A 打开了 Loading（ID=1001）
2. 系统 B 也打开了 Loading（ID=1002）
3. 系统 A 完成，请求关闭 Loading（传入 ID=1001）

如果不做 ID 校验，系统 A 的关闭请求可能误关掉系统 B 的 Loading。

```csharp
public static void HideLoading(this UILoadingComponent self, int uniqueId)
{
    if (uniqueId != self.LoadingUniqueID)
    {
        // ID 不匹配，不关闭（这个关闭请求不属于当前 Loading）
        Log.Warning($"Loading UniqueID mismatch: expected {self.LoadingUniqueID}, got {uniqueId}");
        return;
    }
    // 执行关闭流程
}
```

每次 `ShowLoading()` 时生成一个新的 `LoadingUniqueID`（通常用自增计数器）。调用方持有这个 ID，关闭时带着 ID 来证明"我是打开它的那个人"。

---

## 五、DynamicCanvasComponent：Canvas 销毁时的 UI 清理

```csharp
public class DynamicCanvasComponent : MonoBehaviour
{
    public List<string> m_ShowPanels = new List<string>();

    public void OnDestroy()
    {
        if (EventSystem.Instance != null)
        {
            foreach (var panelName in m_ShowPanels)
            {
                // Canvas 销毁时，自动关闭依附在其上的所有 Panel
                EventSystem.Instance
                    .PublishAsync(YIUIComponent.ClientScene,
                        new Evt_CloseUIPanel() { PanelName = panelName })
                    .Coroutine();
            }
        }
    }
}
```

**这是 Unity 资源生命周期管理的关键技巧：**

当一个动态创建的 Canvas（比如战斗 HUD）被销毁时，原本显示在它上面的 UI 面板可能因为 Canvas 销毁而消失，但对应的 ECS Panel 组件还在内存中（认为面板还在）。

`DynamicCanvasComponent` 在 Canvas 销毁时（`OnDestroy`）自动发布"关闭面板"事件，通知 ECS 层同步清理状态，防止内存泄漏和状态不一致。

---

## 六、UITweenComponent：UI 动画的 ECS 桥接

```csharp
public class UITweenComponent : Entity, IAwake
{
    public IUIDOTween[] Tweens;    // DOTween 动画序列（入场/出场动画）
    public CanvasGroup CanvasGroup; // 控制整体透明度
}
```

这个简洁的组件是 DOTween 和 ECS 的桥接：
- `Tweens`：一个或多个 DOTween 动画序列，对应 UI 面板的入场/出场动画
- `CanvasGroup`：用于 Alpha 控制（淡入淡出），整个面板一次性控制透明度

**为什么用 CanvasGroup 而不是每个元素单独控制 Alpha？**

`CanvasGroup.alpha = 0.5f` 会同时让组下所有 UI 元素半透明，性能更好（只改一个 GPU 参数），效果统一（不会出现子元素透明度不一致的情况）。

---

## 七、LoadingOptions 的扩展设计

```csharp
public LoadingOptions LoadingOptions;
```

虽然代码中未展开 `LoadingOptions` 的定义，但从命名可以推断它包含：
- `ShowProgressBar`：是否显示进度条
- `ShowLoadingText`：是否显示文字提示
- `AllowSkip`：是否允许跳过
- `BackgroundImagePath`：Loading 背景图片

用一个 Options 对象而不是多个独立字段，有利于：
- 参数传递：`ShowLoading(options)` 比 `ShowLoading(bool, bool, string, ...)` 更清晰
- 扩展性：加新选项不改方法签名

---

## 八、完整 Loading 流程

```
调用 ShowLoading(options)
  → 生成 LoadingUniqueID（自增）
  → LoadingState = Opening
  → 播放入场动画（UITweenComponent）
  → 入场动画结束 → LoadingState = Looping
  → 启动 MinLoopWait 计时器

加载逻辑执行中...

调用 HideLoading(uniqueId)
  → 验证 uniqueId 匹配
  → ShouldWaitHide = true
  → 检查 ShouldWaitMinLoop？
    ├─ false → 直接关闭
    └─ true → 等待计时器（可被 MinLoopWaitToken 取消）

MinLoopWait 时间到
  → ShouldWaitMinLoop = false
  → 检查 ShouldWaitHide？
    ├─ true → LoadingState = CanClose
    └─ false → 继续等待真正的 HideLoading 调用

LoadingState = CanClose + 入场动画已完成
  → LoadingState = Closing
  → 播放出场动画
  → 动画结束 → LoadingState = Idle
```

---

## 九、总结

| 设计要素 | 作用 |
|---------|-----|
| 五状态 ELoadingState | 精确控制 Loading 的生命周期 |
| ETCancellationToken | 支持提前取消等待，防止傻等 |
| ShouldWaitHide | 保存"应关闭"意图，不丢失请求 |
| LoadingUniqueID | 防止多个 Loading 请求互相误关 |
| MinLoopWaitTime | 保证最小展示时间，避免闪烁 |
| DynamicCanvasComponent | Canvas 销毁时自动同步 ECS 状态 |

Loading 系统是 UI 开发中最考验状态管理能力的模块之一。理解它的设计，对于构建任何"有明确生命周期的异步 UI 操作"都有直接参考价值。
