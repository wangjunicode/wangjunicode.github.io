---
title: 游戏世界BOSS系统：多阶段Boss与仇恨管理
published: 2026-03-31
description: 全面解析游戏世界BOSS的工程设计，包含多阶段BOSS（血量触发阶段切换+特殊演出）、仇恨表（Taunt/仇恨值动态计算）、BOSS技能模式（随机/阶段性/仇恨目标）、世界BOSS参与者管理（多人共同攻击）、BOSS濒死演出（慢动作/特写镜头）、BOSS击杀奖励分配（贡献度排名奖励），以及BOSS复活定时器。
tags: [游戏设计, Boss系统, 仇恨管理, RPG, 游戏开发]
category: 战斗系统
draft: false
---

## 一、多阶段Boss

```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Boss阶段配置
/// </summary>
[Serializable]
public class BossPhase
{
    public string PhaseName;
    [Range(0f, 1f)] public float EnterAtHP; // 血量比例触发（0.7=70%血量时）
    public string EnterAnimation;            // 进场演出动画
    public float EnterDuration;              // 进场演出时长（无敌期）
    
    // 该阶段的技能轮转
    public BossAbility[] Abilities;
    
    // 阶段特殊效果
    public GameObject PhaseVFX;
    public AudioClip PhaseMusic;
    public Color HpBarColor;
}

/// <summary>
/// Boss技能
/// </summary>
[Serializable]
public class BossAbility
{
    public string AbilityId;
    public string AbilityName;
    public float Cooldown;
    public float Weight;        // 随机权重（越高越常用）
    public float CastTime;      // 前摇时间
    public bool IsInterruptible; // 是否可以被打断
    
    // 技能目标
    public AbilityTargetType TargetType;
    
    [HideInInspector] public float LastUsedTime;
}

public enum AbilityTargetType { TopThreat, RandomPlayer, AllPlayers, LowestHP }

/// <summary>
/// 多阶段Boss控制器
/// </summary>
public class MultiphaseBoss : MonoBehaviour
{
    [Header("Boss基础")]
    [SerializeField] private string bossId;
    [SerializeField] private HealthComponent healthComponent;
    [SerializeField] private Animator bossAnimator;
    
    [Header("阶段配置")]
    [SerializeField] private BossPhase[] phases;
    
    [Header("仇恨系统")]
    [SerializeField] private float threatDecayRate = 0.95f; // 每秒仇恨衰减比例
    [SerializeField] private int maxTrackedTargets = 20;
    
    // 当前阶段
    private int currentPhaseIndex = -1;
    private bool isTransitioning;
    
    // 仇恨表
    private Dictionary<string, float> threatTable = new Dictionary<string, float>();
    
    // 参与者（用于击杀奖励分配）
    private Dictionary<string, float> participantDamage = new Dictionary<string, float>();
    
    // 事件
    public event Action<int, BossPhase> OnPhaseChanged;      // phaseIndex, phase
    public event Action<List<string>> OnBossDefeated;        // 参与者列表

    void Start()
    {
        healthComponent.OnDamaged += OnTakeDamage;
        healthComponent.OnDied += OnDied;
        
        // 开始第一阶段
        StartCoroutine(TransitionToPhase(0));
    }

    void Update()
    {
        if (isTransitioning) return;
        
        // 检查是否需要切换阶段
        float hpRatio = healthComponent.CurrentHP / healthComponent.MaxHP;
        CheckPhaseTransition(hpRatio);
        
        // 仇恨衰减
        DecayThreat();
        
        // 技能轮转
        UpdateAbilityRotation();
    }

    // ============ 阶段切换 ============

    void CheckPhaseTransition(float hpRatio)
    {
        int targetPhase = currentPhaseIndex;
        
        for (int i = 0; i < phases.Length; i++)
        {
            if (hpRatio <= phases[i].EnterAtHP && i > currentPhaseIndex)
                targetPhase = i;
        }
        
        if (targetPhase > currentPhaseIndex)
            StartCoroutine(TransitionToPhase(targetPhase));
    }

    IEnumerator TransitionToPhase(int phaseIndex)
    {
        isTransitioning = true;
        currentPhaseIndex = phaseIndex;
        var phase = phases[phaseIndex];
        
        // 进入无敌状态
        healthComponent.SetInvincible(true);
        
        // 播放阶段切换演出
        if (!string.IsNullOrEmpty(phase.EnterAnimation))
            bossAnimator.CrossFade(phase.EnterAnimation, 0.1f);
        
        // 播放阶段特效
        if (phase.PhaseVFX != null)
            Instantiate(phase.PhaseVFX, transform.position, Quaternion.identity);
        
        // 切换BGM
        if (phase.PhaseMusic != null)
            AudioManager.Instance?.PlayMusic(phase.PhaseMusic);
        
        // 更新血条颜色
        // UIManager.Instance?.SetBossHPBarColor(phase.HpBarColor);
        
        OnPhaseChanged?.Invoke(phaseIndex, phase);
        
        yield return new WaitForSeconds(phase.EnterDuration);
        
        // 结束无敌
        healthComponent.SetInvincible(false);
        isTransitioning = false;
    }

    // ============ 仇恨系统 ============

    public void AddThreat(string playerId, float amount)
    {
        if (!threatTable.ContainsKey(playerId))
            threatTable[playerId] = 0;
        
        threatTable[playerId] += amount;
        
        // 同时记录参与者伤害（用于击杀奖励）
        if (!participantDamage.ContainsKey(playerId))
            participantDamage[playerId] = 0;
        participantDamage[playerId] += amount;
    }

    void DecayThreat()
    {
        var keys = new List<string>(threatTable.Keys);
        foreach (var key in keys)
        {
            threatTable[key] *= threatDecayRate;
            if (threatTable[key] < 1f)
                threatTable.Remove(key);
        }
    }

    public string GetTopThreatTarget()
    {
        string top = null;
        float maxThreat = 0;
        
        foreach (var kv in threatTable)
        {
            if (kv.Value > maxThreat)
            {
                maxThreat = kv.Value;
                top = kv.Key;
            }
        }
        
        return top;
    }

    // ============ 技能使用 ============

    float abilityTimer;
    [SerializeField] private float abilityCastInterval = 3f;

    void UpdateAbilityRotation()
    {
        abilityTimer += Time.deltaTime;
        if (abilityTimer < abilityCastInterval) return;
        abilityTimer = 0;
        
        var phase = phases[currentPhaseIndex];
        
        // 加权随机选择技能
        var available = GetAvailableAbilities(phase.Abilities);
        if (available.Count == 0) return;
        
        var chosen = WeightedRandom(available);
        StartCoroutine(CastAbility(chosen));
    }

    List<BossAbility> GetAvailableAbilities(BossAbility[] abilities)
    {
        var available = new List<BossAbility>();
        foreach (var ability in abilities)
        {
            if (Time.time - ability.LastUsedTime >= ability.Cooldown)
                available.Add(ability);
        }
        return available;
    }

    BossAbility WeightedRandom(List<BossAbility> abilities)
    {
        float total = 0;
        foreach (var a in abilities) total += a.Weight;
        
        float random = UnityEngine.Random.Range(0, total);
        float current = 0;
        
        foreach (var a in abilities)
        {
            current += a.Weight;
            if (random <= current) return a;
        }
        
        return abilities[0];
    }

    IEnumerator CastAbility(BossAbility ability)
    {
        ability.LastUsedTime = Time.time;
        
        // 前摇
        bossAnimator?.CrossFade(ability.AbilityId + "_Cast", 0.1f);
        yield return new WaitForSeconds(ability.CastTime);
        
        // 执行技能效果
        ExecuteAbility(ability);
    }

    void ExecuteAbility(BossAbility ability)
    {
        string target = ability.TargetType switch
        {
            AbilityTargetType.TopThreat => GetTopThreatTarget(),
            AbilityTargetType.RandomPlayer => GetRandomPlayer(),
            _ => GetTopThreatTarget()
        };
        
        Debug.Log($"[Boss] 使用技能: {ability.AbilityName}，目标: {target}");
    }

    void OnTakeDamage(float damage, DamageType type, GameObject source)
    {
        if (source != null)
        {
            string attackerId = source.GetComponent<PlayerDataComponent>()?.PlayerId ?? source.name;
            AddThreat(attackerId, damage);
        }
    }

    void OnDied(GameObject killer)
    {
        // 计算参与者列表（按贡献度排序）
        var participants = new List<string>(participantDamage.Keys);
        participants.Sort((a, b) => participantDamage[b].CompareTo(participantDamage[a]));
        
        OnBossDefeated?.Invoke(participants);
        
        StartCoroutine(DeathSequence());
    }

    IEnumerator DeathSequence()
    {
        bossAnimator?.CrossFade("Death", 0.1f);
        
        // 慢动作演出
        Time.timeScale = 0.2f;
        yield return new WaitForSecondsRealtime(1.5f);
        Time.timeScale = 1f;
        
        // 消失
        yield return new WaitForSeconds(3f);
        Destroy(gameObject);
    }

    string GetRandomPlayer()
    {
        var players = new List<string>(threatTable.Keys);
        return players.Count > 0 ? players[UnityEngine.Random.Range(0, players.Count)] : null;
    }
}
```

---

## 二、Boss设计要点

| 要点 | 方案 |
|------|------|
| 阶段数量 | 2-4个阶段，每个阶段有明显视觉差异 |
| 无敌过渡期 | 阶段切换时短暂无敌，防止瞬间二连杀 |
| 仇恨管理 | 伤害越高仇恨越高，坦克通过Taunt拉回 |
| 技能加权随机 | 避免完全随机导致同一技能连续，也避免固定顺序被刷 |
| 参与者贡献 | 击杀奖励按伤害贡献分配，激励积极参与 |
| 复活定时器 | 世界BOSS定时刷新，形成活动期待感 |
