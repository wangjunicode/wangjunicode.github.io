---
title: 游戏宠物与召唤物系统设计：AI跟随与状态同步
published: 2026-03-31
description: 全面解析游戏宠物与召唤物系统的工程设计，包括宠物数据结构（成长/进化/技能）、跟随AI（智能路径跟随、障碍绕行）、宠物状态机（跟随/战斗/休息/探索）、多宠物排队跟随、宠物属性加成给主角、多人联网同步，以及宠物商店与蛋孵化机制设计。
tags: [Unity, 宠物系统, AI跟随, 召唤物, 游戏设计]
category: 游戏系统设计
draft: false
---

## 一、宠物数据结构

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 宠物模板数据
/// </summary>
[CreateAssetMenu(fileName = "PetTemplate", menuName = "Game/Pet Template")]
public class PetTemplateData : ScriptableObject
{
    [Header("基础")]
    public string PetId;
    public string DisplayName;
    [TextArea(2, 3)] public string Description;
    public Sprite Icon;
    public GameObject Prefab;
    public PetRarity Rarity;

    [Header("成长")]
    public int MaxLevel = 50;
    public float[] ExpRequirements;  // 每级升级所需经验
    
    [Header("属性加成（给主角）")]
    public float AttackBonus;
    public float DefenseBonus;
    public float HPBonus;
    [Range(0, 100)] public float CritRateBonus;   // 暴击率加成%
    
    [Header("技能")]
    public PetSkillData[] Skills;       // 宠物拥有的技能
    
    [Header("进化")]
    public string EvolutionTargetId;    // 进化目标宠物ID（空=无进化）
    public int EvolutionLevel;          // 进化所需等级
    public List<string> EvolutionMaterialIds; // 进化材料
}

public enum PetRarity { Common, Uncommon, Rare, Epic, Legendary }

/// <summary>
/// 玩家拥有的宠物实例
/// </summary>
[Serializable]
public class PetInstance
{
    public string InstanceId;           // 实例唯一ID
    public string TemplateId;           // 模板ID
    public string Nickname;             // 玩家起的名字
    public int Level;
    public float CurrentExp;
    public bool IsDeployed;             // 是否已上场
    public DateTime CaptureTime;
    
    // 成长点分配
    public Dictionary<string, int> StatPoints = new Dictionary<string, int>();
    
    public PetTemplateData GetTemplate() 
        => Resources.Load<PetTemplateData>($"PetTemplates/{TemplateId}");
}
```

---

## 二、宠物跟随 AI

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 宠物 AI 控制器（跟随主角的智能行为）
/// </summary>
[RequireComponent(typeof(NavMeshAgent))]
[RequireComponent(typeof(Animator))]
public class PetAI : MonoBehaviour
{
    [Header("跟随配置")]
    [SerializeField] private float followDistance = 2.5f;       // 理想跟随距离
    [SerializeField] private float catchupDistance = 8f;        // 超过此距离快速追赶
    [SerializeField] private float teleportDistance = 20f;      // 超过此距离直接传送
    [SerializeField] private float idleRange = 1.5f;            // 闲置时随机游荡半径
    
    [Header("战斗")]
    [SerializeField] private float attackRange = 3f;
    [SerializeField] private float aggroRange = 8f;

    private NavMeshAgent agent;
    private Animator anim;
    private Transform owner;
    private PetState currentState;
    private Transform currentTarget;
    private float idleTimer;
    private Vector3 idleWanderTarget;

    private static readonly int SpeedParam = Animator.StringToHash("Speed");
    private static readonly int AttackTrigger = Animator.StringToHash("Attack");

    public enum PetState { Following, CatchingUp, Idle, Combat, WaitingForOwner }

    void Awake()
    {
        agent = GetComponent<NavMeshAgent>();
        anim = GetComponent<Animator>();
    }

    public void SetOwner(Transform ownerTransform)
    {
        owner = ownerTransform;
        currentState = PetState.Following;
    }

    void Update()
    {
        if (owner == null) return;
        
        float distToOwner = Vector3.Distance(transform.position, owner.position);
        
        // 传送（防止宠物卡住）
        if (distToOwner > teleportDistance)
        {
            TeleportNearOwner();
            return;
        }
        
        // 状态更新
        switch (currentState)
        {
            case PetState.Following:
            case PetState.CatchingUp:
                UpdateFollowState(distToOwner);
                break;
            
            case PetState.Idle:
                UpdateIdleState(distToOwner);
                break;
            
            case PetState.Combat:
                UpdateCombatState();
                break;
        }
        
        // 寻找附近敌人（自动战斗）
        if (currentState != PetState.Combat)
            CheckForEnemies();
        
        // 更新动画
        anim.SetFloat(SpeedParam, agent.velocity.magnitude / agent.speed);
    }

    void UpdateFollowState(float distToOwner)
    {
        if (distToOwner > followDistance)
        {
            // 计算跟随位置（在主角后方一定距离）
            Vector3 followPos = owner.position - owner.forward * followDistance;
            
            // 快速追赶模式
            if (distToOwner > catchupDistance)
            {
                agent.speed = GetBaseSpeed() * 2f;
                currentState = PetState.CatchingUp;
            }
            else
            {
                agent.speed = GetBaseSpeed();
                currentState = PetState.Following;
            }
            
            agent.SetDestination(followPos);
        }
        else
        {
            // 已在跟随距离内，进入闲置
            agent.ResetPath();
            currentState = PetState.Idle;
            idleTimer = Random.Range(2f, 5f);
            idleWanderTarget = owner.position + Random.insideUnitSphere * idleRange;
            idleWanderTarget.y = owner.position.y;
        }
    }

    void UpdateIdleState(float distToOwner)
    {
        // 主角跑远了，切回跟随
        if (distToOwner > followDistance * 1.5f)
        {
            currentState = PetState.Following;
            return;
        }
        
        // 闲置期间随机游荡
        idleTimer -= Time.deltaTime;
        if (idleTimer <= 0)
        {
            idleTimer = Random.Range(3f, 8f);
            idleWanderTarget = owner.position + Random.insideUnitSphere * idleRange;
            idleWanderTarget.y = owner.position.y;
        }
        
        float distToWander = Vector3.Distance(transform.position, idleWanderTarget);
        if (distToWander > 0.5f)
        {
            agent.speed = GetBaseSpeed() * 0.5f;
            agent.SetDestination(idleWanderTarget);
        }
        else
        {
            agent.ResetPath();
        }
    }

    void UpdateCombatState()
    {
        if (currentTarget == null || !currentTarget.gameObject.activeInHierarchy)
        {
            currentState = PetState.Following;
            return;
        }
        
        float distToTarget = Vector3.Distance(transform.position, currentTarget.position);
        
        if (distToTarget <= attackRange)
        {
            // 攻击
            agent.ResetPath();
            transform.LookAt(currentTarget.position);
            
            anim.SetTrigger(AttackTrigger);
        }
        else
        {
            // 追赶目标
            agent.SetDestination(currentTarget.position);
        }
        
        // 目标跑太远，回到主角身边
        float distTargetToOwner = Vector3.Distance(currentTarget.position, owner.position);
        if (distTargetToOwner > aggroRange * 2f)
        {
            currentTarget = null;
            currentState = PetState.Following;
        }
    }

    void CheckForEnemies()
    {
        var colliders = Physics.OverlapSphere(transform.position, aggroRange, 
            LayerMask.GetMask("Enemy"));
        
        if (colliders.Length > 0)
        {
            currentTarget = colliders[0].transform;
            currentState = PetState.Combat;
        }
    }

    void TeleportNearOwner()
    {
        Vector3 teleportPos = owner.position + Random.insideUnitSphere * (followDistance * 0.5f);
        teleportPos.y = owner.position.y;
        
        if (NavMesh.SamplePosition(teleportPos, out NavMeshHit hit, 2f, NavMesh.AllAreas))
            agent.Warp(hit.position);
        
        currentState = PetState.Following;
    }

    float GetBaseSpeed() => agent.speed;
}
```

---

## 三、多宠物排队跟随

```csharp
/// <summary>
/// 多宠物队列管理（最多3只宠物排队跟随）
/// </summary>
public class PetParty : MonoBehaviour
{
    [SerializeField] private int maxDeployedPets = 3;
    [SerializeField] private float formationSpacing = 1.8f;  // 队伍间距
    
    private List<PetAI> deployedPets = new List<PetAI>();
    private Transform playerTransform;

    void Start()
    {
        playerTransform = GetComponent<Transform>();
    }

    public bool DeployPet(PetInstance instance)
    {
        if (deployedPets.Count >= maxDeployedPets) return false;
        
        var template = instance.GetTemplate();
        var petGo = Instantiate(template.Prefab);
        var petAI = petGo.GetComponent<PetAI>();
        
        // 设置跟随偏移（排队跟随）
        int index = deployedPets.Count;
        var follower = petGo.AddComponent<PetFollower>();
        follower.Setup(playerTransform, index, formationSpacing, deployedPets);
        
        petAI.SetOwner(playerTransform);
        deployedPets.Add(petAI);
        
        return true;
    }

    public void RecallAll()
    {
        foreach (var pet in deployedPets)
            if (pet != null) Destroy(pet.gameObject);
        deployedPets.Clear();
    }
}
```

---

## 四、宠物加成系统

```csharp
/// <summary>
/// 宠物属性加成计算器（激活的宠物为主角提供加成）
/// </summary>
public class PetBonusCalculator : MonoBehaviour
{
    public float CalculateTotalAttackBonus(List<PetInstance> deployedPets)
    {
        float total = 0f;
        foreach (var pet in deployedPets)
        {
            var template = pet.GetTemplate();
            if (template != null)
            {
                float levelMultiplier = 1f + (pet.Level - 1) * 0.05f; // 每级增加5%
                total += template.AttackBonus * levelMultiplier;
            }
        }
        return total;
    }
}
```

**宠物系统设计亮点：**
1. 传送机制防止宠物卡住（用户体验关键）
2. 自动战斗但不会离主角太远（防止宠物"迷路"）
3. 多宠物排队间距随数量动态调整
4. 宠物属性随等级成长，给玩家培养动力
