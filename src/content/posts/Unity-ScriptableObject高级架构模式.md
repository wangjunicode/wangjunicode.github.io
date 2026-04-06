---
title: Unity脚本化对象（ScriptableObject）高级架构模式
published: 2026-03-31
description: 深入掌握 Unity ScriptableObject 在大型项目中的高级用法，包括事件系统、状态机、配置数据库、运行时集合、游戏架构层解耦，以及 ScriptableObject 驱动的插件化 AI 行为、技能系统等工程级设计模式。
tags: [Unity, ScriptableObject, 架构设计, 游戏开发, C#]
category: 游戏架构
draft: false
encryptedKey:henhaoji123
---

## 一、为什么用 ScriptableObject

ScriptableObject 是 Unity 的数据容器，与普通 MonoBehaviour 相比：

| 特性 | MonoBehaviour | ScriptableObject |
|------|--------------|------------------|
| 依赖场景 | ✅ 必须挂载到 GameObject | ❌ 独立的资产文件 |
| 数据复用 | ❌ 每个实例独立 | ✅ 多个对象引用同一份数据 |
| 运行时修改 | 频繁 GC | 轻量 |
| Inspector 编辑 | ✅ | ✅ |
| 序列化 | 场景文件 | Asset 文件（.asset） |

---

## 二、事件系统（GameEvent）

一种极简的事件系统：所有监听者只需要持有对 SO 的引用，无需知道触发者：

```csharp
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 无参数游戏事件（ScriptableObject）
/// </summary>
[CreateAssetMenu(menuName = "Game/Events/GameEvent")]
public class GameEvent : ScriptableObject
{
    private List<GameEventListener> listeners = new List<GameEventListener>();

    public void Raise()
    {
        // 倒序遍历，防止监听器在回调中取消注册
        for (int i = listeners.Count - 1; i >= 0; i--)
            listeners[i].OnEventRaised();
    }

    public void RegisterListener(GameEventListener listener)
    {
        if (!listeners.Contains(listener))
            listeners.Add(listener);
    }

    public void UnregisterListener(GameEventListener listener)
    {
        listeners.Remove(listener);
    }
}

/// <summary>
/// 带参数的游戏事件（泛型）
/// </summary>
[CreateAssetMenu(menuName = "Game/Events/GameEventInt")]
public class GameEventInt : ScriptableObject
{
    private List<System.Action<int>> listeners = new List<System.Action<int>>();

    public void Raise(int value)
    {
        foreach (var l in listeners.ToArray())
            l?.Invoke(value);
    }

    public void Register(System.Action<int> listener) => listeners.Add(listener);
    public void Unregister(System.Action<int> listener) => listeners.Remove(listener);
}

/// <summary>
/// 游戏事件监听器（挂载到 GameObject）
/// </summary>
public class GameEventListener : MonoBehaviour
{
    [SerializeField] private GameEvent gameEvent;
    [SerializeField] private UnityEvent response;

    void OnEnable()  => gameEvent?.RegisterListener(this);
    void OnDisable() => gameEvent?.UnregisterListener(this);
    public void OnEventRaised() => response?.Invoke();
}
```

**使用方式：**
```csharp
// 玩家死亡时触发事件
[SerializeField] private GameEvent onPlayerDied; // 拖入 Asset

void Die() 
{
    // ... 死亡逻辑
    onPlayerDied.Raise(); // UI、敌人、音效等都能响应，互不知晓
}
```

---

## 三、运行时数据集合（RuntimeSet）

```csharp
/// <summary>
/// 运行时集合（场景中特定类型的对象列表）
/// </summary>
[CreateAssetMenu(menuName = "Game/RuntimeSet/TransformSet")]
public class RuntimeTransformSet : ScriptableObject
{
    private List<Transform> items = new List<Transform>();

    public IReadOnlyList<Transform> Items => items;

    public void Add(Transform item)
    {
        if (!items.Contains(item))
            items.Add(item);
    }

    public void Remove(Transform item) => items.Remove(item);
    
    public Transform GetRandom()
    {
        if (items.Count == 0) return null;
        return items[Random.Range(0, items.Count)];
    }
    
    // 重要：应用退出时清理（ScriptableObject 在编辑器中持久）
    void OnDisable() => items.Clear();
}

/// <summary>
/// 自动注册到 RuntimeSet 的组件
/// </summary>
public class RuntimeSetMember : MonoBehaviour
{
    [SerializeField] private RuntimeTransformSet set;
    
    void OnEnable()  => set?.Add(transform);
    void OnDisable() => set?.Remove(transform);
}

// 使用示例：敌人 AI 寻找最近的玩家
public class EnemySeeker : MonoBehaviour
{
    [SerializeField] private RuntimeTransformSet players; // 所有玩家的集合
    
    Transform FindNearestPlayer()
    {
        Transform nearest = null;
        float minDist = float.MaxValue;
        
        foreach (var p in players.Items)
        {
            float d = Vector3.SqrMagnitude(p.position - transform.position);
            if (d < minDist)
            {
                minDist = d;
                nearest = p;
            }
        }
        return nearest;
    }
}
```

---

## 四、状态机（ScriptableObject 状态）

```csharp
/// <summary>
/// 基于 ScriptableObject 的状态
/// </summary>
public abstract class State : ScriptableObject
{
    public abstract void OnEnter(StateMachine machine);
    public abstract void OnUpdate(StateMachine machine);
    public abstract void OnExit(StateMachine machine);
}

[CreateAssetMenu(menuName = "Game/States/PatrolState")]
public class PatrolState : State
{
    [SerializeField] private float speed = 3f;
    [SerializeField] private float waypointReachDistance = 0.5f;

    public override void OnEnter(StateMachine machine)
    {
        Debug.Log($"[State] {machine.name}: Enter Patrol");
        machine.GetComponent<Animator>()?.SetTrigger("Patrol");
    }

    public override void OnUpdate(StateMachine machine)
    {
        var agent = machine.GetComponent<UnityEngine.AI.NavMeshAgent>();
        if (agent == null) return;
        
        if (!agent.hasPath || agent.remainingDistance < waypointReachDistance)
        {
            // 设置下一个巡逻点
            var waypoints = machine.GetComponent<WaypointPath>();
            if (waypoints != null)
                agent.SetDestination(waypoints.NextWaypoint());
        }
        
        // 检测玩家进入视野 → 切换到追击状态
        if (machine.CanSeePlayer())
            machine.ChangeState(machine.ChaseState);
    }

    public override void OnExit(StateMachine machine)
    {
        Debug.Log($"[State] {machine.name}: Exit Patrol");
    }
}

[CreateAssetMenu(menuName = "Game/States/ChaseState")]
public class ChaseState : State
{
    [SerializeField] private float chaseSpeed = 5f;
    [SerializeField] private float attackRange = 2f;

    public override void OnEnter(StateMachine machine)
    {
        machine.GetComponent<UnityEngine.AI.NavMeshAgent>().speed = chaseSpeed;
    }

    public override void OnUpdate(StateMachine machine)
    {
        var target = machine.CurrentTarget;
        if (target == null)
        {
            machine.ChangeState(machine.PatrolState);
            return;
        }
        
        float dist = Vector3.Distance(machine.transform.position, target.position);
        
        if (dist <= attackRange)
        {
            machine.ChangeState(machine.AttackState);
        }
        else
        {
            machine.GetComponent<UnityEngine.AI.NavMeshAgent>()
                ?.SetDestination(target.position);
        }
    }

    public override void OnExit(StateMachine machine) { }
}

/// <summary>
/// 状态机组件
/// </summary>
public class StateMachine : MonoBehaviour
{
    [Header("状态（ScriptableObject 资产）")]
    public PatrolState PatrolState;
    public ChaseState ChaseState;
    public State AttackState;
    
    [Header("检测")]
    [SerializeField] private float visionRange = 10f;
    [SerializeField] private LayerMask playerLayer;
    
    private State currentState;
    public Transform CurrentTarget { get; private set; }

    void Start() => ChangeState(PatrolState);

    void Update() => currentState?.OnUpdate(this);

    public void ChangeState(State newState)
    {
        currentState?.OnExit(this);
        currentState = newState;
        currentState?.OnEnter(this);
    }

    public bool CanSeePlayer()
    {
        var cols = Physics.OverlapSphere(transform.position, visionRange, playerLayer);
        if (cols.Length > 0)
        {
            CurrentTarget = cols[0].transform;
            return true;
        }
        CurrentTarget = null;
        return false;
    }
}
```

---

## 五、可插拔技能系统

```csharp
/// <summary>
/// 技能基类（ScriptableObject）
/// </summary>
public abstract class SkillSO : ScriptableObject
{
    [Header("基础属性")]
    public string SkillId;
    public string DisplayName;
    public Sprite Icon;
    public float Cooldown;
    public float MpCost;
    [TextArea] public string Description;

    /// <summary>
    /// 技能执行（可被 MonoBehaviour 调用）
    /// </summary>
    public abstract void Execute(SkillContext context);
    
    /// <summary>
    /// 判断是否可以施放
    /// </summary>
    public virtual bool CanExecute(SkillContext context) => true;
}

public class SkillContext
{
    public GameObject Caster;
    public Transform CastTransform;
    public Vector3 TargetPosition;
    public GameObject TargetObject;
    public float DamageMul = 1f;
}

[CreateAssetMenu(menuName = "Game/Skills/FireballSkill")]
public class FireballSkill : SkillSO
{
    [SerializeField] private GameObject projectilePrefab;
    [SerializeField] private float damage = 100f;
    [SerializeField] private float speed = 15f;
    [SerializeField] private float explosionRadius = 3f;

    public override void Execute(SkillContext context)
    {
        if (projectilePrefab == null) return;
        
        Vector3 dir = (context.TargetPosition - context.CastTransform.position).normalized;
        var proj = GameObject.Instantiate(projectilePrefab, 
            context.CastTransform.position + dir * 1f, 
            Quaternion.LookRotation(dir));
        
        var rb = proj.GetComponent<Rigidbody>();
        if (rb != null) rb.linearVelocity = dir * speed;
        
        var projectile = proj.GetComponent<ProjectileBase>();
        if (projectile != null)
        {
            projectile.SetDamage(damage * context.DamageMul);
            projectile.SetExplosionRadius(explosionRadius);
        }
    }
}

/// <summary>
/// 玩家技能栏（引用 SkillSO 资产）
/// </summary>
public class PlayerSkillBar : MonoBehaviour
{
    [SerializeField] private SkillSO[] skills; // Inspector 中拖入 SO 资产
    private float[] cooldownTimers;
    
    void Start()
    {
        cooldownTimers = new float[skills.Length];
    }

    public void UseSkill(int slotIndex)
    {
        if (slotIndex >= skills.Length) return;
        
        var skill = skills[slotIndex];
        if (skill == null) return;
        
        if (cooldownTimers[slotIndex] > 0)
        {
            UIManager.Instance?.ShowMessage("技能冷却中");
            return;
        }
        
        var context = new SkillContext
        {
            Caster = gameObject,
            CastTransform = transform,
            TargetPosition = GetAimPosition()
        };
        
        if (skill.CanExecute(context))
        {
            skill.Execute(context);
            cooldownTimers[slotIndex] = skill.Cooldown;
        }
    }

    void Update()
    {
        for (int i = 0; i < cooldownTimers.Length; i++)
            if (cooldownTimers[i] > 0)
                cooldownTimers[i] -= Time.deltaTime;
    }

    Vector3 GetAimPosition()
    {
        Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
        return Physics.Raycast(ray, out RaycastHit hit) ? hit.point : transform.position + transform.forward * 10f;
    }
}
```

---

## 六、ScriptableObject 使用规范

| 使用场景 | 模式 | 注意事项 |
|----------|------|----------|
| 配置数据 | 只读 SO | 运行时不修改，防止数据污染 |
| 事件总线 | GameEvent SO | OnDisable 取消注册 |
| 全局状态 | 变量容器 SO | 退出时 OnDisable 重置初始值 |
| 运行时集合 | RuntimeSet SO | OnDisable 清空，防止跨场景残留 |
| 状态机 | State SO | 状态为无状态设计，数据存在宿主 |
| 技能系统 | Skill SO | 执行方法接收 Context，支持多实体复用 |

**核心原则：ScriptableObject 本身不保存运行时可变状态，只保存配置和逻辑。**
