---
title: 设计模式的征途——游戏开发实战指南
published: 2019-01-31
description: "从游戏开发角度深度解析6个最常用设计模式：单例、观察者、命令、状态机、对象池、策略。每个模式结合真实游戏场景，给出可运行的C#代码示例，并重点剖析单例滥用、事件内存泄漏等常见踩坑点，帮助游戏开发者建立正确的架构设计思维。"
tags: [架构设计, C#, 游戏开发, 设计模式]
category: 架构设计
draft: false
---

刚入行的时候，我也背过那本《设计模式》，把23个模式名称默得滚瓜烂熟。但真正做项目之后才发现，能背出名字没用，关键是要知道**什么时候用、怎么用、哪些坑别踩**。

这篇文章是我这些年游戏开发的总结，选了6个在游戏项目中最高频的模式，每个都结合真实的游戏场景来讲。

---

## UML 速查

在正式开始之前，先回顾一下 UML 关系图的基本符号，后面看架构图用得上：

- 虚线箭头 → 依赖关系
- 实线箭头 → 关联关系
- 虚线三角 → 实现接口
- 实线三角 → 继承父类
- 空心菱形 → 聚合（可独立存在）
- 实心菱形 → 组合（强依赖，不可分离）

---

## 1. 单例模式（Singleton）

### 问题场景

游戏里有一个 `GameManager`，负责管理全局游戏状态。各个系统都需要访问它，于是大家开始在代码里到处 `FindObjectOfType<GameManager>()`，或者把它拖到每个预制体的引用槽里。这很快就变成噩梦。

### 模式解法

单例保证一个类只有一个实例，并提供全局访问点。

```csharp
public class GameManager : MonoBehaviour
{
    public static GameManager Instance { get; private set; }

    [Header("游戏状态")]
    public int Score;
    public int Level;
    public bool IsGameOver;

    private void Awake()
    {
        // 防止重复创建
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject); // 跨场景保留
    }

    public void AddScore(int value)
    {
        Score += value;
        UIManager.Instance.UpdateScoreUI(Score);
    }
}
```

### ⚠️ 重要：游戏中单例的滥用问题

这是我见过的新人最容易犯的错误。入行不久，我们项目里有 `GameManager`、`UIManager`、`AudioManager`、`ResourceManager`、`NetworkManager`……几乎所有系统都是单例。

**问题在哪里？**

1. **隐式依赖**：`PlayerController` 里写了 `AudioManager.Instance.Play()`，这个依赖在代码里完全看不出来，重构时很难发现
2. **测试困难**：单元测试无法独立测试，因为单例是全局状态
3. **初始化顺序**：`Awake` 的执行顺序不确定，`A.Instance` 访问时 `B.Instance` 可能还是 null
4. **场景切换问题**：`DontDestroyOnLoad` 的单例在重新加载场景时可能出现重复实例

**正确的态度**：单例不是不能用，但要**克制**。真正需要全局唯一且频繁访问的系统才用单例（比如 `EventSystem`、`ResourceManager`）。业务逻辑不要用单例，改用依赖注入或服务定位器。

```csharp
// ❌ 滥用单例的写法
public class PlayerAttack : MonoBehaviour
{
    void Attack()
    {
        AudioManager.Instance.Play("attack");
        EffectManager.Instance.Spawn("slash", transform.position);
        ScoreManager.Instance.AddKillScore();
        UIManager.Instance.ShowDamageText(100);
        NetworkManager.Instance.SyncAttack();
    }
}

// ✅ 更好的做法：通过接口/事件解耦
public class PlayerAttack : MonoBehaviour
{
    void Attack()
    {
        // 只做攻击计算，结果通过事件广播
        var damage = CalculateDamage();
        EventBus.Emit(new AttackEvent { Damage = damage, Position = transform.position });
    }
}
```

---

## 2. 观察者模式（Observer）

### 问题场景

玩家血量变化时，需要更新血条 UI、触发受伤特效、通知 Boss AI、记录统计数据……如果在 `PlayerHealth` 里直接调用所有这些系统，耦合度极高，每次新增功能都要改 `PlayerHealth`。

### 模式解法

观察者模式定义对象间的一对多依赖，当一个对象状态改变，所有依赖它的对象都会自动收到通知。

**方案一：使用 C# 委托/事件**

```csharp
public class PlayerHealth : MonoBehaviour
{
    public static event Action<int, int> OnHealthChanged; // (current, max)
    public static event Action OnPlayerDied;

    private int _currentHp;
    private int _maxHp = 100;

    public void TakeDamage(int damage)
    {
        _currentHp = Mathf.Max(0, _currentHp - damage);
        OnHealthChanged?.Invoke(_currentHp, _maxHp);

        if (_currentHp <= 0)
        {
            OnPlayerDied?.Invoke();
        }
    }
}

// UI 订阅
public class HealthBarUI : MonoBehaviour
{
    private void OnEnable()
    {
        PlayerHealth.OnHealthChanged += UpdateHealthBar;
    }

    private void OnDisable()
    {
        // ⚠️ 必须在 OnDisable 里取消订阅，否则对象销毁后仍会收到回调，导致 NullReferenceException
        PlayerHealth.OnHealthChanged -= UpdateHealthBar;
    }

    private void UpdateHealthBar(int current, int max)
    {
        slider.value = (float)current / max;
    }
}
```

**方案二：消息总线（EventBus）**

大型项目里，我更推荐封装一个 EventBus，支持按事件类型分发：

```csharp
// 事件定义
public struct PlayerDamagedEvent
{
    public int Damage;
    public Vector3 HitPosition;
    public GameObject Attacker;
}

// 简单的 EventBus 实现
public static class EventBus
{
    private static readonly Dictionary<Type, List<Delegate>> _handlers = new();

    public static void Subscribe<T>(Action<T> handler)
    {
        var type = typeof(T);
        if (!_handlers.ContainsKey(type))
            _handlers[type] = new List<Delegate>();
        _handlers[type].Add(handler);
    }

    public static void Unsubscribe<T>(Action<T> handler)
    {
        var type = typeof(T);
        if (_handlers.TryGetValue(type, out var list))
            list.Remove(handler);
    }

    public static void Emit<T>(T evt)
    {
        var type = typeof(T);
        if (_handlers.TryGetValue(type, out var list))
        {
            foreach (var handler in list)
                ((Action<T>)handler)?.Invoke(evt);
        }
    }
}

// 使用
public class PlayerHealth : MonoBehaviour
{
    public void TakeDamage(int damage, Vector3 hitPos, GameObject attacker)
    {
        _currentHp -= damage;
        EventBus.Emit(new PlayerDamagedEvent
        {
            Damage = damage,
            HitPosition = hitPos,
            Attacker = attacker
        });
    }
}

public class HitEffect : MonoBehaviour
{
    private void OnEnable() => EventBus.Subscribe<PlayerDamagedEvent>(OnPlayerDamaged);
    private void OnDisable() => EventBus.Unsubscribe<PlayerDamagedEvent>(OnPlayerDamaged);

    private void OnPlayerDamaged(PlayerDamagedEvent evt)
    {
        SpawnEffect(evt.HitPosition);
    }
}
```

### 注意事项

- **取消订阅是必须的**：忘记 `Unsubscribe` 是内存泄漏的高发区，我项目里就曾经因为这个导致战斗场景越玩越卡
- **事件执行顺序不保证**：多个订阅者的执行顺序不确定，不要在两个订阅者之间建立依赖
- **避免事件链**：A 事件触发 B 事件触发 C 事件，调试起来非常痛苦

---

## 3. 命令模式（Command）

### 问题场景

游戏里需要实现**撤销/重做**功能（比如建造类游戏），或者需要把玩家操作**录制回放**，或者需要实现**技能队列**（技能 A 执行完毕后自动执行技能 B）。

### 模式解法

把操作封装成对象，支持参数化、队列、撤销等操作。

```csharp
// 命令接口
public interface ICommand
{
    void Execute();
    void Undo(); // 支持撤销
}

// 移动命令
public class MoveCommand : ICommand
{
    private readonly Transform _target;
    private readonly Vector3 _delta;
    private Vector3 _prevPosition;

    public MoveCommand(Transform target, Vector3 delta)
    {
        _target = target;
        _delta = delta;
    }

    public void Execute()
    {
        _prevPosition = _target.position;
        _target.position += _delta;
    }

    public void Undo()
    {
        _target.position = _prevPosition;
    }
}

// 攻击命令
public class AttackCommand : ICommand
{
    private readonly Character _attacker;
    private readonly Character _target;
    private int _damageDealt;

    public AttackCommand(Character attacker, Character target)
    {
        _attacker = attacker;
        _target = target;
    }

    public void Execute()
    {
        _damageDealt = _attacker.CalculateDamage();
        _target.TakeDamage(_damageDealt);
    }

    public void Undo()
    {
        _target.RestoreHp(_damageDealt); // 回合制游戏撤销攻击
    }
}

// 命令管理器（支持撤销/重做）
public class CommandManager
{
    private readonly Stack<ICommand> _undoStack = new();
    private readonly Stack<ICommand> _redoStack = new();

    public void Execute(ICommand command)
    {
        command.Execute();
        _undoStack.Push(command);
        _redoStack.Clear(); // 新操作后清空重做栈
    }

    public void Undo()
    {
        if (_undoStack.Count == 0) return;
        var command = _undoStack.Pop();
        command.Undo();
        _redoStack.Push(command);
    }

    public void Redo()
    {
        if (_redoStack.Count == 0) return;
        var command = _redoStack.Pop();
        command.Execute();
        _undoStack.Push(command);
    }
}
```

### 技能队列实现

```csharp
// 技能队列（命令队列）
public class SkillQueue : MonoBehaviour
{
    private readonly Queue<ICommand> _skillQueue = new();
    private bool _isExecuting;

    public void EnqueueSkill(ICommand skill)
    {
        _skillQueue.Enqueue(skill);
        if (!_isExecuting)
            StartCoroutine(ProcessQueue());
    }

    private IEnumerator ProcessQueue()
    {
        _isExecuting = true;
        while (_skillQueue.Count > 0)
        {
            var skill = _skillQueue.Dequeue();
            skill.Execute();
            yield return new WaitUntil(() => /* 技能动画播放完毕 */ true);
        }
        _isExecuting = false;
    }
}
```

---

## 4. 状态机（State Machine）

### 问题场景

角色有 Idle/Move/Attack/Die 等多个状态，如果用 `if-else` 或 `switch` 来管理，代码会越来越混乱：

```csharp
// ❌ 反例：用 if-else 管理状态，维护灾难
void Update()
{
    if (state == "Idle")
    {
        if (Input.anyKey) state = "Move";
        if (enemyNearby) state = "Attack";
    }
    else if (state == "Move")
    {
        // ...
    }
    // 越写越多，越来越乱
}
```

### 模式解法

状态机把每个状态封装成独立类，状态自己知道如何进入、执行和退出。

```csharp
// 状态接口
public interface ICharacterState
{
    void Enter(CharacterController controller);
    void Update(CharacterController controller);
    void Exit(CharacterController controller);
}

// Idle 状态
public class IdleState : ICharacterState
{
    public void Enter(CharacterController ctrl)
    {
        ctrl.Animator.Play("Idle");
    }

    public void Update(CharacterController ctrl)
    {
        // 检测是否有移动输入
        if (ctrl.MoveInput.magnitude > 0.1f)
        {
            ctrl.ChangeState(new MoveState());
            return;
        }
        // 检测是否有敌人进入攻击范围
        if (ctrl.HasEnemyInRange())
        {
            ctrl.ChangeState(new AttackState());
        }
    }

    public void Exit(CharacterController ctrl) { }
}

// Move 状态
public class MoveState : ICharacterState
{
    public void Enter(CharacterController ctrl)
    {
        ctrl.Animator.Play("Run");
    }

    public void Update(CharacterController ctrl)
    {
        ctrl.Move(ctrl.MoveInput);

        if (ctrl.MoveInput.magnitude < 0.1f)
        {
            ctrl.ChangeState(new IdleState());
            return;
        }
        if (ctrl.HasEnemyInRange())
        {
            ctrl.ChangeState(new AttackState());
        }
    }

    public void Exit(CharacterController ctrl) { }
}

// Attack 状态
public class AttackState : ICharacterState
{
    private float _attackTimer;
    private const float AttackDuration = 0.8f;

    public void Enter(CharacterController ctrl)
    {
        ctrl.Animator.Play("Attack");
        ctrl.DealDamage();
        _attackTimer = 0f;
    }

    public void Update(CharacterController ctrl)
    {
        _attackTimer += Time.deltaTime;
        if (_attackTimer >= AttackDuration)
        {
            // 攻击结束，回到 Idle 或继续追击
            ctrl.ChangeState(ctrl.HasEnemyInRange() ? new AttackState() : (ICharacterState)new IdleState());
        }
    }

    public void Exit(CharacterController ctrl) { }
}

// Die 状态
public class DieState : ICharacterState
{
    public void Enter(CharacterController ctrl)
    {
        ctrl.Animator.Play("Die");
        ctrl.enabled = false; // 禁用输入
    }

    public void Update(CharacterController ctrl) { } // 死亡后不再更新

    public void Exit(CharacterController ctrl) { }
}

// 角色控制器（状态机宿主）
public class CharacterController : MonoBehaviour
{
    public Animator Animator { get; private set; }
    public Vector2 MoveInput { get; private set; }

    private ICharacterState _currentState;

    private void Awake()
    {
        Animator = GetComponent<Animator>();
    }

    private void Start()
    {
        ChangeState(new IdleState());
    }

    private void Update()
    {
        MoveInput = new Vector2(Input.GetAxis("Horizontal"), Input.GetAxis("Vertical"));
        _currentState?.Update(this);
    }

    public void ChangeState(ICharacterState newState)
    {
        _currentState?.Exit(this);
        _currentState = newState;
        _currentState.Enter(this);
    }

    public void Move(Vector2 input)
    {
        transform.Translate(new Vector3(input.x, 0, input.y) * Time.deltaTime * 5f);
    }

    public bool HasEnemyInRange()
    {
        return Physics.CheckSphere(transform.position, 2f, LayerMask.GetMask("Enemy"));
    }

    public void DealDamage()
    {
        var hits = Physics.OverlapSphere(transform.position, 2f, LayerMask.GetMask("Enemy"));
        foreach (var hit in hits)
        {
            hit.GetComponent<EnemyHealth>()?.TakeDamage(10);
        }
    }

    public void Die()
    {
        ChangeState(new DieState());
    }
}
```

### 注意事项

- **状态切换要在 Update 末尾处理**，避免在 Update 中途切换状态导致当帧逻辑混乱
- **状态对象可以重用**：`new IdleState()` 每次都分配内存，可以用对象池缓存常用状态对象
- **对于非常复杂的状态机**，考虑使用 Unity 的 Animator 状态机（配合代码驱动参数），视觉上更直观

---

## 5. 对象池（Object Pool）

### 问题场景

射击游戏里每秒钟可能发射十几颗子弹，每颗子弹用 `Instantiate` 创建，用 `Destroy` 销毁。高频的内存分配与 GC 回收会导致帧率抖动。

> 详细的对象池实现请参考我的另一篇文章：[对象池系统设计与实现](/posts/系统架构-对象池)

这里给出核心思路：

```csharp
// 对象池核心：Get() 取出，Release() 归还
var bullet = BulletPool.Instance.Get();
bullet.transform.position = firePoint.position;
bullet.gameObject.SetActive(true);

// 子弹到达目标或超时后归还
BulletPool.Instance.Release(bullet);
```

---

## 6. 策略模式（Strategy）

### 问题场景

不同的敌人有不同的 AI 行为：小怪直接冲向玩家，远程怪保持距离，Boss 会根据血量切换策略。如果用继承来实现，每种敌人都要写子类，类爆炸。

### 模式解法

把"行为算法"抽象成接口，运行时可以动态替换。

```csharp
// 移动策略接口
public interface IMoveStrategy
{
    void Move(Enemy enemy, Transform target);
}

// 直线冲刺策略
public class ChargeStrategy : IMoveStrategy
{
    private float _speed;
    public ChargeStrategy(float speed) => _speed = speed;

    public void Move(Enemy enemy, Transform target)
    {
        var dir = (target.position - enemy.transform.position).normalized;
        enemy.transform.position += dir * _speed * Time.deltaTime;
    }
}

// 保持距离策略（远程单位）
public class KeepDistanceStrategy : IMoveStrategy
{
    private float _preferredDistance;
    private float _speed;

    public KeepDistanceStrategy(float distance, float speed)
    {
        _preferredDistance = distance;
        _speed = speed;
    }

    public void Move(Enemy enemy, Transform target)
    {
        float dist = Vector3.Distance(enemy.transform.position, target.position);
        Vector3 dir;

        if (dist < _preferredDistance)
            dir = (enemy.transform.position - target.position).normalized; // 后退
        else if (dist > _preferredDistance + 1f)
            dir = (target.position - enemy.transform.position).normalized; // 前进
        else
            dir = Vector3.zero; // 保持

        enemy.transform.position += dir * _speed * Time.deltaTime;
    }
}

// 包围策略（多人围攻玩家）
public class FlankStrategy : IMoveStrategy
{
    private float _angle;
    private float _speed;

    public FlankStrategy(float angle, float speed)
    {
        _angle = angle;
        _speed = speed;
    }

    public void Move(Enemy enemy, Transform target)
    {
        // 在目标周围以固定角度环绕
        var offset = Quaternion.Euler(0, _angle, 0) * Vector3.forward * 3f;
        var targetPos = target.position + offset;
        enemy.transform.position = Vector3.MoveTowards(
            enemy.transform.position, targetPos, _speed * Time.deltaTime);
    }
}

// 敌人类：持有策略引用，运行时可切换
public class Enemy : MonoBehaviour
{
    private IMoveStrategy _moveStrategy;
    private Transform _playerTransform;
    private int _maxHp = 100;
    private int _currentHp;

    private void Start()
    {
        _currentHp = _maxHp;
        _playerTransform = GameObject.FindGameObjectWithTag("Player").transform;
        // 初始策略：冲刺
        _moveStrategy = new ChargeStrategy(5f);
    }

    private void Update()
    {
        _moveStrategy?.Move(this, _playerTransform);

        // Boss 换相：血量低于 30% 切换为保持距离+远程攻击
        if (_currentHp < _maxHp * 0.3f)
        {
            _moveStrategy = new KeepDistanceStrategy(8f, 4f);
        }
    }

    public void TakeDamage(int damage)
    {
        _currentHp -= damage;
    }
}
```

### 注意事项

- **策略对象尽量无状态**，这样可以在多个敌人之间共享同一个策略实例，减少内存分配
- **策略切换时机**要谨慎，频繁切换策略会导致行为抖动（比如每帧根据距离切换来切换去）

---

## 总结

| 模式 | 核心解决的问题 | 游戏中典型应用 |
|------|--------------|--------------|
| 单例 | 全局唯一访问点 | GameManager、ResourceManager（克制使用！）|
| 观察者 | 解耦事件发送方和接收方 | 血量变化、游戏事件广播 |
| 命令 | 操作对象化，支持撤销/队列 | 技能队列、回合制撤销、操作回放 |
| 状态机 | 管理复杂状态转移逻辑 | 角色状态、游戏流程管理 |
| 对象池 | 避免频繁 GC 导致帧率抖动 | 子弹、特效、敌人实例 |
| 策略 | 运行时动态切换行为算法 | 敌人 AI、技能算法、寻路算法 |

设计模式不是银弹，过度设计和不设计一样糟糕。我的经验是：**先让代码跑起来，再在痛点出现时引入对应的模式**。不要为了用模式而用模式。
