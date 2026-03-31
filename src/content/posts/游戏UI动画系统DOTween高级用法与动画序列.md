---
title: 游戏UI动画系统：DOTween高级用法与动画序列
published: 2026-03-31
description: 深度解析DOTween在游戏UI动画中的高级应用，包含Tween序列（Sequence链式动画）、重复/循环动画、弹性/回弹Ease曲线、DOTween Animator替代方案、UI弹窗出场/入场动画封装、血条/经验条动画、数字滚动效果、并行动画组合，以及DOTween性能注意事项（避免频繁创建/使用SetAutoKill）。
tags: [Unity, DOTween, UI动画, 游戏UI, 游戏开发]
category: 游戏UI
draft: false
---

## 一、DOTween 基础到进阶

```csharp
using DG.Tweening;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// DOTween UI动画工具箱
/// </summary>
public class UIAnimationToolbox : MonoBehaviour
{
    // ============ 基础动画 ============
    
    /// <summary>
    /// 弹性出现动画（常用于弹窗）
    /// </summary>
    public static Tween BounceIn(Transform target, float duration = 0.4f)
    {
        target.localScale = Vector3.zero;
        return target.DOScale(Vector3.one, duration)
            .SetEase(Ease.OutBack, overshoot: 1.5f); // 超出1再弹回
    }

    /// <summary>
    /// 淡入动画
    /// </summary>
    public static Tween FadeIn(CanvasGroup cg, float duration = 0.3f)
    {
        cg.alpha = 0;
        return cg.DOFade(1f, duration).SetEase(Ease.OutCubic);
    }

    /// <summary>
    /// 从下滑入
    /// </summary>
    public static Tween SlideInFromBottom(RectTransform rt, float duration = 0.4f,
        float distance = 200f)
    {
        Vector2 startPos = rt.anchoredPosition + Vector2.down * distance;
        rt.anchoredPosition = startPos;
        return rt.DOAnchorPos(rt.anchoredPosition + Vector2.up * distance, duration)
            .SetEase(Ease.OutCubic);
    }

    // ============ 序列动画 ============
    
    /// <summary>
    /// 弹窗出场序列（淡入 + 弹性放大 + 子元素逐个出现）
    /// </summary>
    public static Sequence ShowPanel(GameObject panel, RectTransform[] children = null)
    {
        var cg = panel.GetComponent<CanvasGroup>();
        var rt = panel.GetComponent<RectTransform>();
        
        panel.SetActive(true);
        
        var sequence = DOTween.Sequence();
        
        // 同时执行：淡入 + 弹性放大
        if (cg != null) sequence.Join(FadeIn(cg, 0.3f));
        if (rt != null) sequence.Join(BounceIn(rt, 0.35f));
        
        // 子元素逐个出现（瀑布式）
        if (children != null)
        {
            for (int i = 0; i < children.Length; i++)
            {
                var child = children[i];
                float delay = 0.1f + i * 0.05f;
                sequence.Insert(delay, BounceIn(child, 0.25f));
            }
        }
        
        return sequence;
    }

    /// <summary>
    /// 弹窗关闭序列
    /// </summary>
    public static Sequence HidePanel(GameObject panel, System.Action onComplete = null)
    {
        var cg = panel.GetComponent<CanvasGroup>();
        var rt = panel.GetComponent<RectTransform>();
        
        var sequence = DOTween.Sequence();
        
        if (cg != null)
            sequence.Join(cg.DOFade(0f, 0.2f).SetEase(Ease.InCubic));
        if (rt != null)
            sequence.Join(rt.DOScale(0.8f, 0.2f).SetEase(Ease.InBack));
        
        sequence.OnComplete(() =>
        {
            panel.SetActive(false);
            onComplete?.Invoke();
        });
        
        return sequence;
    }
}
```

---

## 二、血条动画组件

```csharp
/// <summary>
/// 血条动画（支持延迟跟随 + 数字变化）
/// </summary>
public class HealthBarUI : MonoBehaviour
{
    [Header("UI引用")]
    [SerializeField] private Slider mainBar;       // 主血条（立即变化）
    [SerializeField] private Slider delayBar;      // 延迟跟随血条（白色/红色）
    [SerializeField] private TMPro.TextMeshProUGUI hpText;
    
    [Header("动画配置")]
    [SerializeField] private float delayBeforeFollow = 0.5f;  // 延迟多久才开始跟随
    [SerializeField] private float followDuration = 0.6f;     // 跟随动画时长
    [SerializeField] private Color healColor = new Color(0f, 1f, 0.3f);
    [SerializeField] private Color damageColor = new Color(1f, 0.3f, 0.3f);

    private float currentHP;
    private float maxHP;
    private Tween delayBarTween;
    private Tween hpTextTween;

    public void Initialize(float hp, float max)
    {
        currentHP = hp;
        maxHP = max;
        
        float ratio = maxHP > 0 ? hp / max : 0;
        mainBar.value = ratio;
        delayBar.value = ratio;
        
        if (hpText != null) hpText.text = $"{(int)hp}/{(int)max}";
    }

    public void SetHP(float newHP, float max)
    {
        float oldHP = currentHP;
        currentHP = Mathf.Clamp(newHP, 0, max);
        maxHP = max;
        
        float targetRatio = max > 0 ? currentHP / max : 0;
        bool isDamage = newHP < oldHP;
        
        // 主血条立即变化
        mainBar.DOValue(targetRatio, 0.15f).SetEase(Ease.OutCubic);
        
        // 延迟血条：等待后慢慢跟上
        delayBarTween?.Kill();
        
        if (isDamage)
        {
            // 受伤：主条立即降，延迟条慢慢跟
            delayBarTween = DOVirtual.DelayedCall(delayBeforeFollow, () =>
            {
                delayBar.DOValue(targetRatio, followDuration).SetEase(Ease.OutCubic);
            });
        }
        else
        {
            // 回血：延迟条立即拉到最高，主条慢慢涨
            delayBar.value = delayBar.value; // 保持
            mainBar.DOValue(targetRatio, 0.5f).SetEase(Ease.OutCubic);
        }
        
        // 数字滚动效果
        hpTextTween?.Kill();
        float displayHP = oldHP;
        hpTextTween = DOTween.To(() => displayHP, x =>
        {
            displayHP = x;
            if (hpText != null) hpText.text = $"{(int)x}/{(int)max}";
        }, currentHP, 0.3f).SetEase(Ease.OutCubic);
    }
}
```

---

## 三、数字滚动效果

```csharp
/// <summary>
/// 数字滚动组件（积分变化/金币增减展示）
/// </summary>
public class NumberRollText : MonoBehaviour
{
    [SerializeField] private TMPro.TextMeshProUGUI text;
    [SerializeField] private float rollDuration = 1f;
    [SerializeField] private string format = "{0:N0}"; // 千分位格式
    
    private Tween rollTween;
    private long currentValue;

    public void SetValue(long newValue, bool animate = true)
    {
        rollTween?.Kill();
        
        if (!animate)
        {
            currentValue = newValue;
            UpdateText(currentValue);
            return;
        }
        
        long startValue = currentValue;
        rollTween = DOTween.To(
            () => (float)startValue,
            x =>
            {
                currentValue = (long)x;
                UpdateText(currentValue);
            },
            (float)newValue,
            rollDuration)
            .SetEase(Ease.OutCubic);
    }

    void UpdateText(long value)
    {
        if (text != null)
            text.text = string.Format(format, value);
    }
}
```

---

## 四、循环/心跳动画

```csharp
/// <summary>
/// 常用循环动画（心跳/飘动/闪烁）
/// </summary>
public class LoopAnimations : MonoBehaviour
{
    void Start()
    {
        // 心跳动画（反复弹性缩放）
        transform.DOScale(1.1f, 0.5f)
            .SetEase(Ease.InOutSine)
            .SetLoops(-1, LoopType.Yoyo); // -1=无限循环，Yoyo=来回
        
        // 上下飘动（图标/BUFF图标）
        GetComponent<RectTransform>()
            .DOAnchorPosY(10f, 1f)
            .SetRelative()
            .SetEase(Ease.InOutSine)
            .SetLoops(-1, LoopType.Yoyo);
        
        // 颜色闪烁（提示性闪烁）
        GetComponent<Image>()
            .DOFade(0.3f, 0.5f)
            .SetLoops(-1, LoopType.Yoyo)
            .SetEase(Ease.InOutSine);
    }

    void OnDestroy()
    {
        // 销毁时杀死所有Tween（防止泄漏）
        transform.DOKill();
        GetComponent<RectTransform>()?.DOKill();
        GetComponent<Image>()?.DOKill();
    }
}
```

---

## 五、DOTween 性能要点

| 注意事项 | 说明 |
|----------|------|
| SetAutoKill(false) | 重复使用的Tween关闭自动销毁，手动Restart复用 |
| DOKill | 销毁前杀死Tween，防止空引用 |
| 避免每帧创建 | 初始化时创建Tween，不要每帧new |
| Sequence.Append vs Join | Append=串行，Join=并行 |
| SetUpdate(true) | 暂停游戏时UI动画继续（使用unscaledTime）|
| Restart | 已有Tween直接Restart，比重新创建便宜 |
