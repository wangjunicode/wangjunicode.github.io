---
title: 游戏多语言系统工程化：动态字体与RTL支持
published: 2026-03-31
description: 全面解析游戏多语言工程化的完整方案，包含本地化字符串管理（CSV/JSON驱动）、TextMeshPro动态字体加载（按需加载语言字体）、阿拉伯语/希伯来语RTL（从右到左）文本支持、格式化本地化（带数字/名称参数的字符串）、语言切换动画过渡、语言包Addressables按需下载，以及多语言UI适配（文本长度变化的UI弹性布局）。
tags: [Unity, 多语言, 本地化, RTL, TextMeshPro]
category: 游戏工程化
draft: false
---

## 一、本地化管理器

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 支持的语言
/// </summary>
public enum GameLanguage
{
    SimplifiedChinese,  // zh-CN
    English,            // en
    Japanese,           // ja
    Korean,             // ko
    Arabic,             // ar (RTL)
    Russian,            // ru
    German,             // de
    French,             // fr
    Spanish,            // es
}

/// <summary>
/// 本地化管理器
/// </summary>
public class LocalizationManager : MonoBehaviour
{
    private static LocalizationManager instance;
    public static LocalizationManager Instance => instance;

    [Header("默认语言")]
    [SerializeField] private GameLanguage defaultLanguage = GameLanguage.SimplifiedChinese;
    
    [Header("字体映射（各语言字体）")]
    [SerializeField] private LanguageFontMapping[] fontMappings;
    
    private Dictionary<string, string> strings = new Dictionary<string, string>();
    private GameLanguage currentLanguage;
    
    // 是否是从右到左的语言
    public bool IsRTL => currentLanguage == GameLanguage.Arabic;
    
    public event Action<GameLanguage> OnLanguageChanged;

    [Serializable]
    public class LanguageFontMapping
    {
        public GameLanguage Language;
        public TMPro.TMP_FontAsset Font;
    }

    void Awake()
    {
        instance = this;
        DontDestroyOnLoad(gameObject);
        
        // 读取玩家语言设置，如果没有则使用系统语言
        GameLanguage savedLang = GetSystemLanguage();
        string savedLangStr = PlayerPrefs.GetString("game_language", "");
        if (!string.IsNullOrEmpty(savedLangStr) && 
            Enum.TryParse(savedLangStr, out GameLanguage parsed))
            savedLang = parsed;
        
        LoadLanguage(savedLang);
    }

    GameLanguage GetSystemLanguage()
    {
        return Application.systemLanguage switch
        {
            SystemLanguage.Chinese or SystemLanguage.ChineseSimplified => GameLanguage.SimplifiedChinese,
            SystemLanguage.English   => GameLanguage.English,
            SystemLanguage.Japanese  => GameLanguage.Japanese,
            SystemLanguage.Korean    => GameLanguage.Korean,
            SystemLanguage.Arabic    => GameLanguage.Arabic,
            SystemLanguage.Russian   => GameLanguage.Russian,
            SystemLanguage.German    => GameLanguage.German,
            SystemLanguage.French    => GameLanguage.French,
            SystemLanguage.Spanish   => GameLanguage.Spanish,
            _ => defaultLanguage
        };
    }

    public void LoadLanguage(GameLanguage language)
    {
        currentLanguage = language;
        strings.Clear();
        
        string langCode = GetLanguageCode(language);
        
        // 从Resources加载语言包（或Addressables）
        var asset = Resources.Load<TextAsset>($"Localization/{langCode}");
        if (asset != null)
        {
            ParseCSV(asset.text);
        }
        else
        {
            Debug.LogWarning($"[Localization] 找不到语言包: {langCode}，回退到英文");
            var fallback = Resources.Load<TextAsset>("Localization/en");
            if (fallback != null) ParseCSV(fallback.text);
        }
        
        PlayerPrefs.SetString("game_language", language.ToString());
        
        // 通知所有本地化组件刷新
        OnLanguageChanged?.Invoke(language);
        RefreshAllLocalizationComponents();
    }

    void ParseCSV(string csv)
    {
        string[] lines = csv.Split('\n');
        foreach (var line in lines)
        {
            if (string.IsNullOrEmpty(line)) continue;
            int commaIndex = line.IndexOf(',');
            if (commaIndex < 0) continue;
            
            string key = line.Substring(0, commaIndex).Trim();
            string value = line.Substring(commaIndex + 1).Trim().Trim('"');
            // 处理转义的换行符
            value = value.Replace("\\n", "\n");
            
            strings[key] = value;
        }
    }

    /// <summary>
    /// 获取本地化字符串
    /// </summary>
    public string Get(string key)
    {
        if (strings.TryGetValue(key, out string value))
            return value;
        
        Debug.LogWarning($"[Localization] 找不到Key: {key}");
        return $"[{key}]"; // 显示Key本身，方便发现遗漏
    }

    /// <summary>
    /// 获取带参数的本地化字符串
    /// 示例：Get("quest_kill_n_enemies", ("count", 10)) → "击杀10个敌人"
    /// </summary>
    public string Get(string key, params (string name, object value)[] args)
    {
        string text = Get(key);
        foreach (var (name, value) in args)
            text = text.Replace($"{{{name}}}", value.ToString());
        return text;
    }

    /// <summary>
    /// 获取当前语言的字体
    /// </summary>
    public TMPro.TMP_FontAsset GetFont()
    {
        foreach (var mapping in fontMappings)
            if (mapping.Language == currentLanguage)
                return mapping.Font;
        return null;
    }

    void RefreshAllLocalizationComponents()
    {
        var components = FindObjectsOfType<LocalizedText>(true);
        foreach (var comp in components)
            comp.RefreshText();
    }

    string GetLanguageCode(GameLanguage lang)
    {
        return lang switch
        {
            GameLanguage.SimplifiedChinese => "zh-CN",
            GameLanguage.English   => "en",
            GameLanguage.Japanese  => "ja",
            GameLanguage.Korean    => "ko",
            GameLanguage.Arabic    => "ar",
            GameLanguage.Russian   => "ru",
            GameLanguage.German    => "de",
            GameLanguage.French    => "fr",
            GameLanguage.Spanish   => "es",
            _ => "en"
        };
    }

    public GameLanguage CurrentLanguage => currentLanguage;
}
```

---

## 二、本地化文本组件

```csharp
/// <summary>
/// 自动本地化的TextMeshPro组件
/// </summary>
[RequireComponent(typeof(TMPro.TextMeshProUGUI))]
public class LocalizedText : MonoBehaviour
{
    [SerializeField] private string localizationKey;
    [SerializeField] private bool autoUpdateFont = true; // 切换语言时自动更新字体
    
    private TMPro.TextMeshProUGUI textMesh;

    void Awake()
    {
        textMesh = GetComponent<TMPro.TextMeshProUGUI>();
    }

    void Start()
    {
        LocalizationManager.Instance?.OnLanguageChanged += OnLanguageChanged;
        RefreshText();
    }

    void OnDestroy()
    {
        if (LocalizationManager.Instance != null)
            LocalizationManager.Instance.OnLanguageChanged -= OnLanguageChanged;
    }

    void OnLanguageChanged(GameLanguage lang)
    {
        RefreshText();
    }

    public void RefreshText()
    {
        var locManager = LocalizationManager.Instance;
        if (locManager == null || textMesh == null) return;
        
        textMesh.text = locManager.Get(localizationKey);
        
        // 更新字体
        if (autoUpdateFont)
        {
            var font = locManager.GetFont();
            if (font != null) textMesh.font = font;
        }
        
        // RTL支持
        textMesh.isRightToLeftText = locManager.IsRTL;
    }

    public void SetKey(string key)
    {
        localizationKey = key;
        RefreshText();
    }
}
```

---

## 三、本地化CSV格式

```csv
# 本地化字符串文件（zh-CN.csv）
# 格式: key,value

# UI通用
btn_confirm,确认
btn_cancel,取消
btn_back,返回
btn_ok,好的

# 主菜单
menu_play,开始游戏
menu_settings,设置
menu_quit,退出

# 游戏内
hud_hp,生命值
hud_mp,魔法值
quest_kill_n_enemies,击杀{count}个敌人
quest_collect_items,收集{count}个{item_name}

# 带参数的多元化（英文区分单复数）
# 英文版本(en.csv):
# quest_kill_n_enemies,Kill {count} {count, plural, one{enemy} other{enemies}}
```

---

## 四、多语言UI适配

| 问题 | 解决方案 |
|------|----------|
| 文本过长 | Content Size Fitter + 弹性容器 |
| 文本过短 | Min Width约束 + 对齐方式 |
| RTL镜像 | 整个UI Canvas水平翻转（阿语/希语）|
| 字体缺字 | Fallback Font机制（找不到字符时用备用字体）|
| 字体大小 | 不同语言可配置字体缩放系数 |
| 数字格式 | 用NumberFormatInfo，不要硬编码逗号/小数点 |
