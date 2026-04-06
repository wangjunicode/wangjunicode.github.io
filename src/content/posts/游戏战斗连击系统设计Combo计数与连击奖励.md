---
title: 游戏战斗连击系统设计：Combo计数与连击奖励
published: 2026-03-31
description: 全面解析游戏战斗连击（Combo）系统的工程设计，涵盖连击计数器与重置时机、连击倍率加成（连击越多伤害越高）、目标连击锁定、连击视觉反馈（屏幕特效/音效节奏变化/UI弹动）、完美格挡连击加成、连击断裂惩罚，以及《鬼泣》/《忍者龙剑传》风格的连击评级系统。
tags: [Unity, 战斗系统, 连击系统, 动作游戏, 游戏设计]
category: 战斗系统
draft: false
---

## 一、连击计数器

```csharp
using System;
using UnityEngine;
using DG.Tweening;

/// <summary>
/// 战斗连击管理器
/// </summary>
public class ComboManager : MonoBehaviour
{
    private static ComboManager instance;
    public static ComboManager Instance => instance;

    [Header("连击配置")]
    [SerializeField] private float comboResetTime = 2f;      // 多久不攻击重置连击
    [SerializeField] private float maxComboMultiplier = 3f;   // 最大连击倍率
    [SerializeField] private int[] milestones = { 10, 25, 50, 100 }; // 里程碑连击数
    
    [Header("连击评级")]
    private static readonly (int threshold, string grade)[] grades = 
    {
        (100, "SSS"), (75, "SS"), (50, "S"), 
        (25, "A"), (15, "B"), (5, "C"), (1, "D")
    };

    private int comboCount;
    private float resetTimer;
    private float currentMultiplier = 1f;
    
    // 最高连击记录
    private int sessionMaxCombo;
    
    public event Action<int> OnComboChanged;         // 连击数变化
    public event Action<float> OnMultiplierChanged;  // 倍率变化
    public event Action<int> OnComboReset;            // 连击断了（传入最后的连击数）
    public event Action<int> OnMilestoneReached;      // 里程碑到达

    public int ComboCount => comboCount;
    public float Multiplier => currentMultiplier;
    public string Grade => GetComboGrade(comboCount);

    void Awake() { instance = this; }

    void Update()
    {
        if (comboCount > 0)
        {
            resetTimer += Time.deltaTime;
            if (resetTimer >= comboResetTime)
                ResetCombo();
        }
    }

    /// <summary>
    /// 注册一次命中（每次攻击命中时调用）
    /// </summary>
    public void RegisterHit()
    {
        comboCount++;
        resetTimer = 0f;
        
        // 更新倍率（对数增长，避免倍率过快增大）
        currentMultiplier = Mathf.Min(
            1f + Mathf.Log10(comboCount + 1) * 0.8f, 
            maxComboMultiplier);
        
        // 更新最高记录
        if (comboCount > sessionMaxCombo)
            sessionMaxCombo = comboCount;
        
        OnComboChanged?.Invoke(comboCount);
        OnMultiplierChanged?.Invoke(currentMultiplier);
        
        // 检查里程碑
        if (Array.IndexOf(milestones, comboCount) >= 0)
            OnMilestoneReached?.Invoke(comboCount);
    }

    /// <summary>
    /// 完美格挡奖励（增加额外连击）
    /// </summary>
    public void PerfectParryBonus(int bonus = 3)
    {
        for (int i = 0; i < bonus; i++)
            RegisterHit();
    }

    /// <summary>
    /// 受击断连（被打到时调用）
    /// </summary>
    public void BreakCombo()
    {
        if (comboCount <= 0) return;
        
        int lastCombo = comboCount;
        
        // 评分记录
        ScoreCombo(lastCombo);
        
        comboCount = 0;
        currentMultiplier = 1f;
        resetTimer = 0f;
        
        OnComboReset?.Invoke(lastCombo);
        OnComboChanged?.Invoke(0);
        OnMultiplierChanged?.Invoke(1f);
    }

    void ResetCombo()
    {
        if (comboCount <= 0) return;
        int lastCombo = comboCount;
        comboCount = 0;
        currentMultiplier = 1f;
        resetTimer = 0f;
        OnComboReset?.Invoke(lastCombo);
        OnComboChanged?.Invoke(0);
    }

    void ScoreCombo(int combo)
    {
        // 连击结束时计算分数并记录
        int score = CalculateComboScore(combo);
        Debug.Log($"[Combo] {combo} Hit! Grade: {GetComboGrade(combo)}, Score: {score}");
    }

    public int CalculateComboScore(int combo)
    {
        return combo * combo * 10; // 连击数的平方 × 10
    }

    public static string GetComboGrade(int combo)
    {
        foreach (var (threshold, grade) in grades)
            if (combo >= threshold) return grade;
        return "";
    }

    /// <summary>
    /// 计算当前连击的伤害倍率
    /// </summary>
    public float GetDamageMultiplier()
    {
        return currentMultiplier;
    }
}
```

---

## 二、连击视觉反馈

```csharp
/// <summary>
/// 连击 UI 显示
/// </summary>
public class ComboUI : MonoBehaviour
{
    [SerializeField] private UnityEngine.UI.Text comboCountText;
    [SerializeField] private UnityEngine.UI.Text comboGradeText;
    [SerializeField] private UnityEngine.UI.Text multiplierText;
    [SerializeField] private CanvasGroup comboGroup;
    [SerializeField] private UnityEngine.UI.Image fillBar;  // 连击时间条

    private ComboManager comboManager;
    private Tween fadeTween;

    void Start()
    {
        comboManager = ComboManager.Instance;
        comboManager.OnComboChanged += OnComboChanged;
        comboManager.OnMultiplierChanged += OnMultiplierChanged;
        comboManager.OnComboReset += OnComboReset;
        comboManager.OnMilestoneReached += OnMilestoneReached;
        
        comboGroup.alpha = 0f;
    }

    void Update()
    {
        // 更新连击倒计时条
        if (comboManager.ComboCount > 0 && fillBar != null)
        {
            // 倒计时进度可以从ComboManager获取
        }
    }

    void OnComboChanged(int count)
    {
        if (count <= 0) return;
        
        // 显示/更新连击数
        fadeTween?.Kill();
        comboGroup.alpha = 1f;
        
        comboCountText.text = $"{count}";
        comboGradeText.text = ComboManager.GetComboGrade(count);
        
        // 数字弹动
        comboCountText.transform.DOPunchScale(Vector3.one * 0.3f, 0.2f, 5, 0.5f);
        
        // 颜色根据连击数变化
        if (count >= 100)
            comboCountText.color = new Color(1f, 0.2f, 0.2f); // 红色
        else if (count >= 50)
            comboCountText.color = new Color(1f, 0.5f, 0f);   // 橙色
        else if (count >= 25)
            comboCountText.color = new Color(1f, 1f, 0f);      // 黄色
        else
            comboCountText.color = Color.white;
    }

    void OnMultiplierChanged(float multiplier)
    {
        multiplierText.text = $"×{multiplier:F1}";
    }

    void OnComboReset(int lastCombo)
    {
        // 显示连击总结
        comboGradeText.text = ComboManager.GetComboGrade(lastCombo);
        
        // 淡出
        fadeTween = comboGroup.DOFade(0f, 1f).SetDelay(0.5f);
    }

    void OnMilestoneReached(int count)
    {
        // 里程碑特效（全屏闪烁）
        ShowMilestoneEffect(count);
    }

    void ShowMilestoneEffect(int count)
    {
        // 屏幕闪白
        var screenFlash = UIManager.Instance?.GetScreenFlash();
        screenFlash?.Flash(Color.white, 0.3f);
        
        // 播放特殊音效
        AudioManager.Instance?.PlaySFX(GetMilestoneSFX(count));
        
        // 震动
        CameraShaker.Instance?.Shake(0.2f, 0.3f);
    }

    AudioClip GetMilestoneSFX(int combo)
    {
        // 根据连击里程碑返回不同音效
        return null; // 从资源加载
    }
}
```

---

## 三、连击音效节奏系统

```csharp
/// <summary>
/// 连击音效节奏（连击越高音效越激烈）
/// </summary>
public class ComboBGMReactor : MonoBehaviour
{
    [System.Serializable]
    public class ComboBGMLayer
    {
        public int MinCombo;         // 达到多少连击启用此层
        public AudioClip Layer;      // 音乐层
        public float FadeTime = 0.5f;
    }

    [SerializeField] private ComboBGMLayer[] layers;
    
    private AudioSource[] layerSources;

    void Start()
    {
        // 创建音乐层
        layerSources = new AudioSource[layers.Length];
        for (int i = 0; i < layers.Length; i++)
        {
            var source = gameObject.AddComponent<AudioSource>();
            source.clip = layers[i].Layer;
            source.loop = true;
            source.volume = 0f;
            source.Play();
            layerSources[i] = source;
        }
        
        ComboManager.Instance.OnComboChanged += OnComboChanged;
    }

    void OnComboChanged(int combo)
    {
        for (int i = 0; i < layers.Length; i++)
        {
            float targetVolume = combo >= layers[i].MinCombo ? 1f : 0f;
            layerSources[i].DOFade(targetVolume, layers[i].FadeTime);
        }
    }
    
    // DOTween AudioSource 扩展
    static class AudioSourceExtension
    {
        public static DG.Tweening.Tweener DOFade(
            this AudioSource source, float target, float duration)
            => DG.Tweening.DOTween.To(
                () => source.volume, 
                v => source.volume = v, 
                target, duration);
    }
}
```

---

## 四、连击评级系统（鬼泣风格）

| 等级 | 连击数 | 奖励 |
|------|--------|------|
| D   | 1+     | 1.0x 金币 |
| C   | 5+     | 1.1x 金币 |
| B   | 15+    | 1.2x 金币 |
| A   | 25+    | 1.5x 金币 + 特效 |
| S   | 50+    | 2.0x 金币 + 特效 |
| SS  | 75+    | 2.5x 金币 + 爆发特效 |
| SSS | 100+   | 3.0x 金币 + 全屏特效 |

**设计要点：**
1. 连击重置时间不宜太短（2-3秒让玩家有操作空间）
2. 连击倍率推荐对数增长（防止后期过强）
3. 受击必须断连（给连击以意义）
4. 视觉反馈随连击增强（颜色/大小/音效强度递进）
5. 记录本次游戏最高连击作为成就目标
