# UI 动效系统（YIUITween + DOTween）

## 1. 系统概述

本项目 UI 动效系统基于 **DOTween**（热门 Unity Tween 库）封装，通过 `YIUITweenComponent` + `IUIDOTween` 接口，实现面板打开/关闭动画的统一管理，支持并行播放多个动效，并通过 `async/await` 等待动效完成。

另外，项目还实现了完整的**弹幕系统（DanmakuPanel）**，用于战斗中实时显示弹幕评论，通过多轨道管理避免弹幕重叠。

---

## 2. YIUITweenComponent 架构

```
BasePanel（面板基类）
    └── YIUITweenComponent（Tween 组件）
            └── IUIDOTween[]（具体动效数组）
                    ├── FadeInTween（淡入效果）
                    ├── SlideInTween（滑动进入）
                    ├── ScaleTween（缩放动效）
                    └── 自定义动效...
```

---

## 3. 核心代码解析

### 3.1 YIUITweenComponentSystem

```csharp
// 位置：Hotfix/UIFunction/VGameUI/YIUITweenComponentSystem.cs
public static class YIUITweenComponentSystem
{
    // 面板打开时播放所有入场动效（并行执行，等所有完成）
    public static async Task PlayOnShow(this YIUITweenComponent component)
    {
        ResetAnim(component);  // 先重置到初始状态
        await PlayOnShow(component.Tweens);
    }
    
    public static async Task PlayOnShow(IUIDOTween[] tweens)
    {
        // 使用 ListPool 避免 List<Task> 的 GC 分配
        var taskList = ListPool<Task>.Get();
        
        foreach (var tween in tweens)
        {
            taskList.Add(tween.OnShow());  // 各动效并行启动
        }
        
        await Task.WhenAll(taskList);  // 等待所有动效完成
        ListPool<Task>.Release(taskList);
    }
    
    // 面板关闭时播放所有退场动效
    public static async Task PlayOnHide(this YIUITweenComponent component)
    {
        await PlayOnHide(component.Tweens);
    }
    
    public static async Task PlayOnHide(IUIDOTween[] tweens)
    {
        var taskList = ListPool<Task>.Get();
        foreach (var tween in tweens)
        {
            taskList.Add(tween.OnHide());
        }
        await Task.WhenAll(taskList);
        ListPool<Task>.Release(taskList);
    }
    
    // 初始化：从 RectTransform 下查找所有实现了 IUIDOTween 接口的组件
    public static YIUITweenComponent InitializeTweenComponent(this RectTransform rectTransform)
    {
        var component = new YIUITweenComponent();
        var tweens = rectTransform.GetComponentsInChildren<IUIDOTween>();
        foreach (var tween in tweens)
        {
            tween.InitAnim();  // 初始化每个动效（设置初始状态）
        }
        component.Tweens = tweens;
        return component;
    }
}
```

### 3.2 IUIDOTween 接口

```csharp
// 所有 UI 动效都实现此接口
public interface IUIDOTween
{
    void InitAnim();     // 初始化（设置起始状态）
    Task OnShow();       // 入场动效（async，可 await）
    Task OnHide();       // 退场动效（async，可 await）
    void ResetAnim();    // 重置到初始状态（Show前调用）
}

// 示例：淡入淡出动效实现
public class FadeInOutTween : MonoBehaviour, IUIDOTween
{
    [SerializeField] private CanvasGroup _canvasGroup;
    [SerializeField] private float _showDuration = 0.3f;
    [SerializeField] private float _hideDuration = 0.2f;
    
    public void InitAnim()
    {
        _canvasGroup.alpha = 0;  // 初始透明
    }
    
    public async Task OnShow()
    {
        // DOTween 淡入动效，await 等待完成
        await _canvasGroup.DOFade(1, _showDuration).AsyncWaitForCompletion();
    }
    
    public async Task OnHide()
    {
        await _canvasGroup.DOFade(0, _hideDuration).AsyncWaitForCompletion();
    }
    
    public void ResetAnim()
    {
        _canvasGroup.alpha = 0;
        DOTween.Kill(_canvasGroup);  // 杀掉可能存在的旧 Tween，避免冲突
    }
}
```

---

## 4. 在 BasePanel 中的使用

```csharp
// 典型面板 OnCreate 时初始化 Tween，OnOpen/OnClose 时播放
public abstract partial class BasePanel
{
    private YIUITweenComponent _tweenComp;
    
    protected override void OnCreate()
    {
        // 扫描面板根节点下所有 IUIDOTween 组件
        _tweenComp = GetComponent<RectTransform>()
            .InitializeTweenComponent();
    }
    
    protected override async void OnOpen()
    {
        // 播放入场动效，await 使面板在动效结束后才进入交互状态
        await _tweenComp.PlayOnShow();
    }
    
    // 关闭前播放退场动效
    public async ETTask CloseWithAnim()
    {
        await _tweenComp.PlayOnHide();
        YIUIPanelMgr.Instance.Close(this);
    }
}
```

---

## 5. 弹幕系统（DanmakuPanel）

战斗弹幕系统是一个有趣的 UI 功能，展示了复杂滚动 UI 的多轨道管理方案：

```csharp
// 位置：Hotfix/UIFunction/CommonUI/DanmakuPanel.cs
public class DanmakuPanel : MonoBehaviour
{
    // 弹幕参数（策划可调）
    public static int BulletSpeed = 7;          // 弹幕速度（像素/帧）
    public static int BulletInterval = 60;      // 同行两弹幕的最小像素间距
    public static int BulletLineInterval = 36;  // 两行之间的最小像素间距
    public static int MaxLine = 3;              // 最大轨道数（3行弹幕）
    public static float FillBulletTimeInterval = 1f; // 填充弹幕的时间间隔
    
    // 弹幕数据结构
    public class BulletCommentData
    {
        public string Content;       // 弹幕文本
        public float ShootTime = 0;  // 发送时间（用于排序）
    }
    
    // 三种弹幕队列
    private readonly Queue<BulletCommentData> _fixedNormalComment = new(); // 普通弹幕
    private readonly Queue<BulletCommentData> _fixedFillComment = new();   // 填充弹幕
    private readonly Queue<BulletCommentData> _specialComment = new();     // 特殊弹幕（带方框）
```

### 5.1 弹幕多轨道碰撞检测

```csharp
    // 判断某行是否可以发射新弹幕（检测是否有足够间距）
    private bool CanFireBullet(int lineIndex)
    {
        var activeBulletsInLine = _activeBullets
            .Where(b => b.lineIndex == lineIndex)
            .ToList();
        
        if (activeBulletsInLine.Count == 0) return true;
        
        // 检查最后一个弹幕是否已经离开右边界足够距离
        var lastBullet = activeBulletsInLine.OrderBy(b => b.shootTime).Last();
        float rightEdge = lastBullet.textTsf.anchoredPosition.x + lastBullet.textTsf.rect.width;
        float containerRight = _containerRect.rect.width;
        
        // 弹幕还没滚出足够距离（BulletInterval 像素），不能发新弹幕
        return (containerRight - rightEdge) >= BulletInterval;
    }
    
    // 每帧更新所有弹幕位置
    private void UpdateBullets()
    {
        for (int i = _activeBullets.Count - 1; i >= 0; i--)
        {
            var bullet = _activeBullets[i];
            // 弹幕向左移动
            var pos = bullet.textTsf.anchoredPosition;
            pos.x -= BulletSpeed * Time.deltaTime * 60;  // 帧率无关
            bullet.textTsf.anchoredPosition = pos;
            
            // 完全移出左边界，回收到对象池
            if (pos.x + bullet.textTsf.rect.width < 0)
            {
                RecycleBullet(bullet);
                _activeBullets.RemoveAt(i);
            }
        }
    }
```

---

## 6. 数字动画系统（NumberAnimationManager）

```csharp
// Hotfix/UIFunction/VGameUI/NumberAnimationManager.cs
// 数字从旧值滚动到新值的动画（常用于分数/金币变化）
public class NumberAnimationManager : MonoBehaviour
{
    private float _currentDisplayValue;
    private float _targetValue;
    private float _animDuration = 0.5f;
    
    // 设置目标值，自动动画
    public void SetValue(float newValue)
    {
        DOTween.Kill(this);
        DOTween.To(
            () => _currentDisplayValue, 
            v => {
                _currentDisplayValue = v;
                UpdateDisplay(v);
            },
            newValue, 
            _animDuration)
            .SetTarget(this)
            .SetEase(Ease.OutCubic);
        _targetValue = newValue;
    }
    
    private void UpdateDisplay(float value)
    {
        // 使用 ZString 格式化，避免 GC
        _text.text = ZString.Format("{0:N0}", (int)value);
    }
}
```

---

## 7. 常见问题与最佳实践

**Q: 动效播放中途面板被关闭，DOTween 还在跑怎么办？**  
A: 在 `OnClose` 时调用 `DOTween.Kill(transform, complete: true)` 停止所有与该 RectTransform 绑定的 Tween，并将其完成到终点状态（避免残留中间状态）。

**Q: 多个面板同时打开动效，性能会有问题吗？**  
A: `Task.WhenAll` 是并行的，所有动效在同一帧内启动，不会串行等待。注意 DOTween 有全局 Tween 数量限制（默认 200），大量面板同时动效时可能超限。

**Q: 弹幕系统如何处理大量弹幕？**  
A: 弹幕对象走对象池复用，`Queue<BulletCommentData>` 缓存待发弹幕，每帧按轨道间距检测按序发射，保证不超过 `MaxLine * 2` 个同屏弹幕。

**Q: DOTween 的 `Kill` 和 `Complete` 有什么区别？**  
A: `Kill` 直接停止，停在当前状态；`Kill(complete: true)` 停止并跳到动画终点。面板关闭时推荐用 `complete: true`，避免 UI 残留中间状态造成视觉异常。
