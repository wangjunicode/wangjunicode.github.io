---
title: 游戏宠物系统设计：AI跟随与互动行为
published: 2026-03-31
description: 全面解析游戏宠物系统工程实现，包含宠物AI跟随（NavMesh跟随/弹簧骨骼路径跟随）、宠物状态机（跟随/玩耍/休息/战斗辅助）、宠物情感系统（好感度/饥饿度）、宠物技能（被动加成/主动辅助）、宠物外观定制（颜色/配件）、宠物进化系统，以及宠物战斗AI（协助攻击/治疗）。
tags: [游戏宠物, AI跟随, 宠物系统, 游戏设计, Unity]
category: 游戏系统设计
draft: false
---

## 一、宠物跟随AI

```csharp
using UnityEngine;
using UnityEngine.AI;

public class PetFollowAI : MonoBehaviour
{
    [Header("跟随配置")]
    [SerializeField] private Transform followTarget;
    [SerializeField] private float followDistance = 2f;     // 开始跟随的距离
    [SerializeField] private float stopDistance = 1.5f;     // 停止跟随的距离
    [SerializeField] private float runThreshold = 5f;       // 超过此距离跑步追
    [SerializeField] private float teleportDistance = 20f;  // 超过此距离直接传送
    
    [Header("动画")]
    [SerializeField] private Animator animator;
    [SerializeField] private string walkAnimKey = "IsWalking";
    [SerializeField] private string runAnimKey = "IsRunning";

    private NavMeshAgent navAgent;
    private PetStateManager stateManager;

    void Awake()
    {
        navAgent = GetComponent<NavMeshAgent>();
        stateManager = GetComponent<PetStateManager>();
    }

    void Update()
    {
        if (followTarget == null || !stateManager.IsInFollowMode) return;
        
        float dist = Vector3.Distance(transform.position, followTarget.position);
        
        // 超出传送距离直接传送
        if (dist > teleportDistance)
        {
            TeleportToTarget();
            return;
        }
        
        if (dist > followDistance)
        {
            navAgent.SetDestination(followTarget.position);
            navAgent.stoppingDistance = stopDistance;
            
            bool isRunning = dist > runThreshold;
            navAgent.speed = isRunning ? 8f : 4f;
            
            animator?.SetBool(walkAnimKey, !isRunning);
            animator?.SetBool(runAnimKey, isRunning);
        }
        else
        {
            navAgent.ResetPath();
            animator?.SetBool(walkAnimKey, false);
            animator?.SetBool(runAnimKey, false);
            
            // 空闲时随机朝向玩家
            if (Random.value < 0.01f)
                transform.LookAt(followTarget.position);
        }
    }

    void TeleportToTarget()
    {
        Vector3 targetPos = followTarget.position + followTarget.right * 1.5f;
        if (NavMesh.SamplePosition(targetPos, out var hit, 3f, NavMesh.AllAreas))
            transform.position = hit.position;
    }
}

public class PetStateManager : MonoBehaviour
{
    public bool IsInFollowMode { get; set; } = true;
    public PetState CurrentState { get; private set; }
    
    public enum PetState { Following, Playing, Resting, Fighting, Interacting }
}
```

---

## 二、宠物情感系统

```csharp
[Serializable]
public class PetEmotionData
{
    public float Happiness;      // 快乐度 0-100
    public float Hunger;         // 饥饿度 0-100（越高越饿）
    public float Affection;      // 好感度（累计，影响进化）
    public long LastFeedTime;
    public long LastPlayTime;
}

public class PetEmotionSystem : MonoBehaviour
{
    private PetEmotionData emotionData;
    
    void Update()
    {
        // 随时间增加饥饿
        if (emotionData != null)
        {
            emotionData.Hunger = Mathf.Min(100, emotionData.Hunger + Time.deltaTime * 0.01f);
            
            // 饥饿影响快乐
            if (emotionData.Hunger > 80)
                emotionData.Happiness = Mathf.Max(0, emotionData.Happiness - Time.deltaTime * 0.1f);
        }
    }
    
    public void Feed(string foodId)
    {
        emotionData.Hunger -= 30f;
        emotionData.Happiness = Mathf.Min(100, emotionData.Happiness + 10f);
        emotionData.Affection += 5;
        emotionData.LastFeedTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        
        // 播放进食动画
        GetComponent<Animator>()?.SetTrigger("Eat");
    }

    public void Play()
    {
        emotionData.Happiness = Mathf.Min(100, emotionData.Happiness + 20f);
        emotionData.Affection += 10;
        emotionData.LastPlayTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        GetComponent<Animator>()?.SetTrigger("Play");
    }
    
    public string GetMoodExpression()
    {
        if (emotionData.Happiness > 80) return "😊";
        if (emotionData.Happiness > 50) return "😐";
        if (emotionData.Hunger > 80) return "😢";
        return "😞";
    }
}
```

---

## 三、宠物被动技能加成

```csharp
public class PetPassiveBonus : MonoBehaviour
{
    [SerializeField] private PetData petData;
    
    public void ApplyBonuses(CharacterAttributes playerAttributes)
    {
        if (petData?.Skills == null) return;
        
        foreach (var skill in petData.Skills)
        {
            if (!skill.IsPassive || !skill.IsUnlocked) continue;
            
            playerAttributes.Get(skill.BonusStatId)?.AddModifier(
                new AttributeModifier(
                    $"pet_{petData.PetId}_{skill.SkillId}",
                    StatModifierOrder.FlatBonus,
                    skill.BonusValue));
        }
    }

    public void RemoveBonuses(CharacterAttributes playerAttributes)
    {
        if (petData == null) return;
        
        foreach (var attr in new[] 
        { 
            StatId.AttackDamage, StatId.MaxHP, StatId.MoveSpeed 
        })
            playerAttributes.Get(attr)?.RemoveModifier($"pet_{petData.PetId}");
    }
}

[CreateAssetMenu(menuName = "Game/Pet")]
public class PetData : ScriptableObject
{
    public string PetId;
    public string Name;
    public PetSkill[] Skills;
}

[Serializable]
public class PetSkill
{
    public string SkillId;
    public bool IsPassive;
    public bool IsUnlocked;
    public string BonusStatId;
    public float BonusValue;
}
```
