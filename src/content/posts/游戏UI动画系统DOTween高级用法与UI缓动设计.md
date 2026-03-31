---
title: 游戏UI动画系统：DOTween高级用法与UI缓动设计
published: 2026-03-31
description: 全面解析Unity UI动画的专业设计，包括DOTween高级序列动画、UI弹窗进出场动效、血条/经验条缓动、数字滚动动画、跟随曲线运动（道具飞入背包）、粒子与UI结合，以及适配不同设备性能的动画降级策略。
tags: [Unity, DOTween, UI动画, 用户体验, 游戏开发]
category: 游戏UI
draft: false
---

## 一、弹窗动画系统

```csharp
using DG.Tweening;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// UI 弹窗基类（带标准进场/退场动画）
/// </summary>
public abstract class UIPanel : MonoBehaviour
{
    [Header("动画配置")]
    [SerializeField] protected float showDuration = 0.3f;
    [SerializeField] protected float hideDuration = 0.2f;
    [SerializeField] protected Ease showEase = Ease.OutBack;
    [SerializeField] protected Ease hideEase = Ease.InBack;
    [SerializeField] protected AnimationType animationType = AnimationType.ScaleFromCenter;
    
    [Header("遮罩")]
    [SerializeField] protected CanvasGroup maskBackground;
    
    protected RectTransform rectTransform;
    protected CanvasGroup canvasGroup;
    private Tween currentTween;

    public enum AnimationType
    {
        ScaleFromCenter,  // 从中心缩放弹出
        SlideFromBottom,  // 从底部滑入
        SlideFromTop,     // 从顶部滑入
        FadeIn,           // 淡入
        SlideFromRight    // 从右侧滑入
    }

    protected virtual void Awake()
    {
        rectTransform = GetComponent<RectTransform>();
        canvasGroup = GetOrAddComponent<CanvasGroup>();
    }

    public virtual void Show(System.Action onComplete = null)
    {
        gameObject.SetActive(true);
        
        // 终止已有动画
        currentTween?.Kill();
        
        // 显示遮罩
        if (maskBackground != null)
        {
            maskBackground.gameObject.SetActive(true);
            maskBackground.DOFade(0.5f, showDuration);
        }
        
        var sequence = DOTween.Sequence();
        
        switch (animationType)
        {
            case AnimationType.ScaleFromCenter:
                rectTransform.localScale = Vector3.zero;
                sequence.Append(rectTransform.DOScale(1f, showDuration).SetEase(showEase));
                break;
                
            case AnimationType.SlideFromBottom:
                float screenH = Screen.height;
                rectTransform.anchoredPosition = new Vector2(0, -screenH);
                sequence.Append(rectTransform.DOAnchorPosY(0, showDuration).SetEase(showEase));
                break;
                
            case AnimationType.SlideFromTop:
                rectTransform.anchoredPosition = new Vector2(0, Screen.height);
                sequence.Append(rectTransform.DOAnchorPosY(0, showDuration).SetEase(showEase));
                break;
                
            case AnimationType.FadeIn:
                canvasGroup.alpha = 0;
                sequence.Append(canvasGroup.DOFade(1f, showDuration).SetEase(Ease.InOutQuad));
                break;
                
            case AnimationType.SlideFromRight:
                rectTransform.anchoredPosition = new Vector2(Screen.width, 0);
                sequence.Append(rectTransform.DOAnchorPosX(0, showDuration).SetEase(showEase));
                break;
        }
        
        sequence.OnComplete(() => onComplete?.Invoke());
        currentTween = sequence;
        
        OnShow();
    }

    public virtual void Hide(System.Action onComplete = null)
    {
        currentTween?.Kill();
        
        if (maskBackground != null)
            maskBackground.DOFade(0, hideDuration);
        
        var sequence = DOTween.Sequence();
        
        switch (animationType)
        {
            case AnimationType.ScaleFromCenter:
                sequence.Append(rectTransform.DOScale(0f, hideDuration).SetEase(hideEase));
                break;
            case AnimationType.SlideFromBottom:
                sequence.Append(rectTransform.DOAnchorPosY(-Screen.height, hideDuration).SetEase(hideEase));
                break;
            case AnimationType.SlideFromTop:
                sequence.Append(rectTransform.DOAnchorPosY(Screen.height, hideDuration).SetEase(hideEase));
                break;
            case AnimationType.FadeIn:
                sequence.Append(canvasGroup.DOFade(0f, hideDuration).SetEase(Ease.InOutQuad));
                break;
            case AnimationType.SlideFromRight:
                sequence.Append(rectTransform.DOAnchorPosX(Screen.width, hideDuration).SetEase(hideEase));
                break;
        }
        
        sequence.OnComplete(() =>
        {
            gameObject.SetActive(false);
            if (maskBackground != null) maskBackground.gameObject.SetActive(false);
            onComplete?.Invoke();
        });
        currentTween = sequence;
        
        OnHide();
    }

    protected virtual void OnShow() { }
    protected virtual void OnHide() { }
    
    T GetOrAddComponent<T>() where T : Component
    {
        return GetComponent<T>() ?? gameObject.AddComponent<T>();
    }
}
```

---

## 二、血条/经验条缓动动画

```csharp
/// <summary>
/// 平滑血条（带延迟追踪效果，类似《黑魂》的红白双层血条）
/// </summary>
public class SmoothHealthBar : MonoBehaviour
{
    [Header("UI 引用")]
    [SerializeField] private Image currentBar;    // 当前血量（主条）
    [SerializeField] private Image delayedBar;    // 延迟变化血量（背景）
    [SerializeField] private Text hpText;
    
    [Header("动画配置")]
    [SerializeField] private float delayBeforeDecay = 0.5f;    // 延迟多久开始衰减
    [SerializeField] private float decayDuration = 1.5f;        // 衰减时间
    [SerializeField] private Ease decayEase = Ease.InOutQuad;
    [SerializeField] private Color damageColor = Color.red;     // 受伤时血条颜色
    [SerializeField] private Color healColor = Color.green;     // 回血时血条颜色
    [SerializeField] private Color normalColor = Color.white;   // 正常颜色
    
    private float maxHp;
    private float currentHp;
    private Tween delayedTween;

    public void Initialize(float maxHp)
    {
        this.maxHp = maxHp;
        currentHp = maxHp;
        currentBar.fillAmount = 1f;
        delayedBar.fillAmount = 1f;
    }

    public void SetHP(float newHp, bool animate = true)
    {
        float oldHp = currentHp;
        currentHp = Mathf.Clamp(newHp, 0, maxHp);
        float targetFill = currentHp / maxHp;
        
        if (!animate)
        {
            currentBar.fillAmount = targetFill;
            delayedBar.fillAmount = targetFill;
            UpdateText();
            return;
        }
        
        bool isDamage = newHp < oldHp;
        
        // 立即更新主血条
        currentBar.DOFillAmount(targetFill, 0.2f).SetEase(Ease.OutExpo);
        
        // 血条颜色反馈
        currentBar.DOColor(isDamage ? damageColor : healColor, 0.1f)
            .SetEase(Ease.OutQuad)
            .OnComplete(() => currentBar.DOColor(normalColor, 0.3f));
        
        if (isDamage)
        {
            // 延迟背景血条（红色部分），营造受伤感
            delayedTween?.Kill();
            delayedTween = DOVirtual.DelayedCall(delayBeforeDecay, () =>
            {
                delayedBar.DOFillAmount(targetFill, decayDuration).SetEase(decayEase);
            });
        }
        else
        {
            // 回血时背景血条立即跟上
            delayedBar.DOFillAmount(targetFill, 0.2f);
        }
        
        // 数字动画
        DOVirtual.Float(oldHp, currentHp, 0.3f, v =>
        {
            hpText.text = $"{Mathf.RoundToInt(v)}/{Mathf.RoundToInt(maxHp)}";
        });
    }

    public void TakeDamage(float damage) => SetHP(currentHp - damage);
    public void Heal(float amount) => SetHP(currentHp + amount);

    void UpdateText() => hpText.text = $"{Mathf.RoundToInt(currentHp)}/{Mathf.RoundToInt(maxHp)}";
}
```

---

## 三、数字滚动动画

```csharp
/// <summary>
/// 数字滚动动画（金币/分数等）
/// </summary>
public class NumberRollAnimation : MonoBehaviour
{
    [SerializeField] private Text displayText;
    [SerializeField] private float duration = 1f;
    [SerializeField] private Ease ease = Ease.OutExpo;
    [SerializeField] private string prefix = "";
    [SerializeField] private string suffix = "";
    [SerializeField] private bool useCommas = true;
    
    private float currentValue;
    private Tween rollTween;

    public void SetValue(float newValue, bool animate = true)
    {
        if (!animate)
        {
            currentValue = newValue;
            UpdateDisplay(newValue);
            return;
        }
        
        rollTween?.Kill();
        float startValue = currentValue;
        
        rollTween = DOVirtual.Float(startValue, newValue, duration, v =>
        {
            currentValue = v;
            UpdateDisplay(v);
        }).SetEase(ease);
    }

    void UpdateDisplay(float value)
    {
        string formatted = useCommas ? 
            ((int)value).ToString("N0") : 
            ((int)value).ToString();
        displayText.text = $"{prefix}{formatted}{suffix}";
    }
    
    public void AddValue(float amount) => SetValue(currentValue + amount);
}
```

---

## 四、道具飞入背包动画

```csharp
/// <summary>
/// 道具飞入效果（从世界坐标飞向UI图标）
/// </summary>
public class ItemFlyAnimation : MonoBehaviour
{
    [SerializeField] private RectTransform targetIcon;       // 目标UI图标（背包/金币栏）
    [SerializeField] private GameObject flyPrefab;           // 飞行的图标Prefab
    [SerializeField] private Canvas canvas;
    [SerializeField] private int flyCount = 5;               // 分裂成多少个飞行
    [SerializeField] private float flightDuration = 0.8f;
    [SerializeField] private float spreadRadius = 50f;       // 初始散开半径

    /// <summary>
    /// 从屏幕位置触发飞入动画
    /// </summary>
    public void FlyFrom(Vector3 worldPos, Sprite icon, System.Action onAllReached = null)
    {
        // 世界坐标转屏幕坐标转Canvas坐标
        Vector2 screenPos = Camera.main.WorldToScreenPoint(worldPos);
        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            canvas.GetComponent<RectTransform>(), screenPos, 
            canvas.worldCamera, out Vector2 canvasPos);
        
        int remaining = flyCount;
        
        for (int i = 0; i < flyCount; i++)
        {
            float delay = i * 0.05f; // 错开时间，产生连续飞入效果
            
            var flyObj = Instantiate(flyPrefab, canvas.transform);
            flyObj.GetComponent<Image>().sprite = icon;
            
            var flyRect = flyObj.GetComponent<RectTransform>();
            flyRect.anchoredPosition = canvasPos;
            flyRect.localScale = Vector3.one * 0.5f;
            
            // 随机散开方向
            Vector2 scatter = Random.insideUnitCircle * spreadRadius;
            
            var seq = DOTween.Sequence();
            seq.SetDelay(delay);
            seq.Append(flyRect.DOAnchoredPos(canvasPos + scatter, 0.2f).SetEase(Ease.OutQuad));
            seq.Append(flyRect.DOMove(targetIcon.position, flightDuration - 0.2f)
                .SetEase(Ease.InBack));
            seq.Join(flyRect.DOScale(0.8f, flightDuration - 0.2f).SetEase(Ease.InQuad));
            seq.OnComplete(() =>
            {
                // 目标图标弹动反馈
                targetIcon.DOPunchScale(Vector3.one * 0.2f, 0.3f, 8, 0.5f);
                
                Destroy(flyObj);
                remaining--;
                if (remaining <= 0) onAllReached?.Invoke();
            });
        }
    }
}
```

---

## 五、动画性能降级

```csharp
/// <summary>
/// 动画质量管理器（根据设备性能降级）
/// </summary>
public static class UIAnimationQuality
{
    public enum Level { Low, Normal, High }
    
    private static Level currentLevel = Level.Normal;
    
    public static float GetDuration(float baseDuration)
    {
        return currentLevel switch
        {
            Level.Low  => 0f,      // 低端设备：瞬间切换
            Level.Normal => baseDuration,
            Level.High => baseDuration * 1.2f, // 高端设备：稍慢更优雅
            _ => baseDuration
        };
    }
    
    public static bool ShouldAnimate => currentLevel != Level.Low;
    
    public static void AutoDetect()
    {
        int fps = (int)(1f / Time.smoothDeltaTime);
        if (fps < 40)
            currentLevel = Level.Low;
        else if (fps >= 55)
            currentLevel = Level.High;
        else
            currentLevel = Level.Normal;
    }
}
```

---

## 六、DOTween 性能最佳实践

| 操作 | 错误 | 正确 |
|------|------|------|
| 频繁创建 Tween | 每帧 `DOXxx()` | 使用 `SetAutoKill(false)` + 重用 |
| 动画结束时 | 不处理 | OnComplete 中 Destroy 飞行对象 |
| 停止动画 | `DOKill(true)` 跳到终点 | `Kill(false)` 停留在当前位置 |
| 序列中等待 | Thread.Sleep | `SetDelay()` 或 `AppendInterval()` |
| Update 中操作 | `transform.DOMove` 每帧 | 只在状态变化时触发 |

**核心原则：UI动画是体验的放大器，流畅但不过度——动画要服务于内容，而不是喧宾夺主。**
