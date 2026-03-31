---
title: 游戏匹配系统设计：ELO评分与天梯匹配
published: 2026-03-31
description: 全面解析游戏竞技匹配系统工程设计，包含ELO/MMR评分算法（胜负积分增减）、匹配扩圈机制（等待时间越长接受更大段位差）、房间创建与销毁流程、段位系统（青铜→钻石→王者）、赛季段位重置、防作弊（异常匹配检测）、匹配服务架构（Dedicated Server/P2P选型）。
tags: [游戏匹配, ELO评分, 天梯系统, PVP, 游戏设计]
category: 游戏设计
draft: false
---

## 一、ELO评分实现

```csharp
using System;
using UnityEngine;

public static class ELOCalculator
{
    private const float K_FACTOR_HIGH = 32f;  // 低段位/新玩家K值（变化快）
    private const float K_FACTOR_LOW  = 16f;  // 高段位K值（变化慢）
    
    /// <summary>
    /// 计算ELO变化
    /// </summary>
    public static (int playerA_delta, int playerB_delta) Calculate(
        int ratingA, int ratingB, float resultA)
    {
        float expectedA = ExpectedScore(ratingA, ratingB);
        float expectedB = 1f - expectedA;
        float resultB = 1f - resultA;
        
        float kA = GetKFactor(ratingA);
        float kB = GetKFactor(ratingB);
        
        int deltaA = Mathf.RoundToInt(kA * (resultA - expectedA));
        int deltaB = Mathf.RoundToInt(kB * (resultB - expectedB));
        
        return (deltaA, deltaB);
    }
    
    static float ExpectedScore(int ratingA, int ratingB)
    {
        return 1f / (1f + Mathf.Pow(10f, (ratingB - ratingA) / 400f));
    }
    
    static float GetKFactor(int rating)
    {
        return rating < 1600 ? K_FACTOR_HIGH : K_FACTOR_LOW;
    }
}

// 使用示例
// 玩家A(1500) 赢了玩家B(1400)
// var (da, db) = ELOCalculator.Calculate(1500, 1400, 1.0f); // 胜=1.0, 负=0.0, 平=0.5
// da ≈ +11, db ≈ -11
```

---

## 二、段位系统

```csharp
[Serializable]
public class RankTier
{
    public string TierName;       // 青铜/白银/黄金/铂金/钻石/大师/王者
    public int MinMMR;
    public int MaxMMR;
    public Sprite TierIcon;
    public Color TierColor;
}

public class RankSystem : MonoBehaviour
{
    [SerializeField] private RankTier[] tiers;

    public RankTier GetTier(int mmr)
    {
        foreach (var tier in tiers)
            if (mmr >= tier.MinMMR && mmr <= tier.MaxMMR) return tier;
        return tiers[tiers.Length - 1]; // 王者
    }

    public string GetRankDisplay(int mmr)
    {
        var tier = GetTier(mmr);
        if (tier == null) return "未排名";
        
        // 段位内的小分段（I/II/III）
        int relativeMMR = mmr - tier.MinMMR;
        int subDivRange = (tier.MaxMMR - tier.MinMMR) / 3;
        int subDiv = Mathf.Min(2, relativeMMR / subDivRange);
        string[] subLabels = { "III", "II", "I" };
        
        return $"{tier.TierName} {subLabels[subDiv]}";
    }
    
    public float GetProgressInTier(int mmr)
    {
        var tier = GetTier(mmr);
        if (tier == null) return 1f;
        return (float)(mmr - tier.MinMMR) / (tier.MaxMMR - tier.MinMMR);
    }
}
```

---

## 三、匹配扩圈机制

```csharp
public class MatchmakingClient : MonoBehaviour
{
    private float waitTime;
    private int baseMMR;
    
    // 随等待时间扩大匹配范围
    int GetMatchRange()
    {
        if (waitTime < 10f) return 50;   // 10秒内：±50 MMR
        if (waitTime < 30f) return 100;  // 30秒内：±100 MMR
        if (waitTime < 60f) return 200;  // 60秒内：±200 MMR
        return 500; // 超过60秒：±500 MMR（宁愿不平衡也要快速匹配）
    }

    public MatchRequest BuildRequest()
    {
        int range = GetMatchRange();
        return new MatchRequest
        {
            PlayerId = AccountManager.Instance.GetPlayerId(),
            MMR = baseMMR,
            MinMMR = baseMMR - range,
            MaxMMR = baseMMR + range,
            WaitTime = waitTime
        };
    }
}

[Serializable]
public class MatchRequest
{
    public string PlayerId;
    public int MMR;
    public int MinMMR;
    public int MaxMMR;
    public float WaitTime;
}
```

---

## 四、段位设计规范

| 段位 | MMR范围 | 玩家比例 |
|------|---------|---------|
| 青铜 | 0-999 | 25% |
| 白银 | 1000-1199 | 30% |
| 黄金 | 1200-1399 | 25% |
| 铂金 | 1400-1599 | 12% |
| 钻石 | 1600-1799 | 6% |
| 大师 | 1800-1999 | 1.5% |
| 王者 | 2000+ | 0.5% |

**赛季重置**：赛季末将所有玩家MMR×0.7（向中间压缩），防止顶部拥堵。
