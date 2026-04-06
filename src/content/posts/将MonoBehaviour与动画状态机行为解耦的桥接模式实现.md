---
title: 将 MonoBehaviour 与动画状态机行为解耦的桥接模式实现
published: 2026-03-31
description: 深入解析 SceneLinkedSMB 如何通过泛型桥接类优雅地解决 StateMachineBehaviour 无法直接访问 MonoBehaviour 的架构难题。
tags: [Unity, 动画系统, 状态机, 设计模式]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

## Unity Animator 的痛点

Unity 的 `Animator` 控制器支持在动画状态上挂载 `StateMachineBehaviour` 脚本，可以监听动画状态的进入、更新、退出事件：

```csharp
// 普通 StateMachineBehaviour
public class AttackBehaviour : StateMachineBehaviour
{
    public override void OnStateEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
        // 攻击动画开始！
        // 问题：怎么访问角色的其他组件？
        var character = animator.GetComponent<Character>(); // ← 每次进入都 GetComponent！
        character.StartAttack();
    }
}
```

每次 `OnStateEnter` 都调用 `GetComponent`，这有性能开销。而且 `StateMachineBehaviour` 被多个 GameObject 共享（它挂在 AnimatorController 上，不是单个对象上），用静态字段存数据也不行。

**根本问题**：`StateMachineBehaviour` 没有直接引用"使用它的那个 MonoBehaviour"。

---

## SceneLinkedSMB 的解决方案

`SceneLinkedSMB<TMonoBehaviour>` 是一个泛型桥接类：

```csharp
public class SceneLinkedSMB<TMonoBehaviour> : SealedSMB 
    where TMonoBehaviour : MonoBehaviour
{
    protected TMonoBehaviour m_MonoBehaviour;  // 持有对 MonoBehaviour 的引用
    bool m_FirstFrameHappened;
    bool m_LastFrameHappened;
    
    // 初始化：建立 SMB 与 MonoBehaviour 的连接
    public static void Initialise(Animator animator, TMonoBehaviour monoBehaviour)
    {
        var sceneLinkedSMBs = animator.GetBehaviours<SceneLinkedSMB<TMonoBehaviour>>();
        for (int i = 0; i < sceneLinkedSMBs.Length; i++)
        {
            sceneLinkedSMBs[i].InternalInitialise(animator, monoBehaviour);
        }
    }
    
    protected void InternalInitialise(Animator animator, TMonoBehaviour monoBehaviour)
    {
        m_MonoBehaviour = monoBehaviour;  // 保存引用（后续不再需要 GetComponent）
        OnStart(animator);
    }
}
```

**关键思路**：在 MonoBehaviour 的 Start/Awake 中调用 `Initialise`，把 `this` 传给所有的 `SceneLinkedSMB`，建立引用。之后 SMB 就可以直接用 `m_MonoBehaviour`，不再需要 `GetComponent`。

---

## 更丰富的生命周期回调

`SealedSMB` 封住了 Unity 原始的 `OnStateEnter/OnStateUpdate/OnStateExit`，取而代之以更精细的生命周期方法：

```csharp
sealed public override void OnStateUpdate(...)
{
    if (!animator.gameObject.activeSelf) return;

    // 进入过渡阶段（淡入）
    if (animator.IsInTransition(layerIndex) && 
        animator.GetNextAnimatorStateInfo(layerIndex).fullPathHash == stateInfo.fullPathHash)
    {
        OnSLTransitionToStateUpdate(...);
    }

    // 状态稳定运行阶段
    if (!animator.IsInTransition(layerIndex) && m_FirstFrameHappened)
    {
        OnSLStateNoTransitionUpdate(...);
    }

    // 准备离开阶段（即将淡出）
    if (animator.IsInTransition(layerIndex) && !m_LastFrameHappened && m_FirstFrameHappened)
    {
        m_LastFrameHappened = true;
        OnSLStatePreExit(...);
    }

    // 第一帧完全进入（过渡结束）
    if (!animator.IsInTransition(layerIndex) && !m_FirstFrameHappened)
    {
        m_FirstFrameHappened = true;
        OnSLStatePostEnter(...);
    }

    // 从当前状态过渡出去
    if (animator.IsInTransition(layerIndex) && 
        animator.GetCurrentAnimatorStateInfo(layerIndex).fullPathHash == stateInfo.fullPathHash)
    {
        OnSLTransitionFromStateUpdate(...);
    }
}
```

额外的生命周期回调：

| 回调方法 | 触发时机 |
|---------|---------|
| `OnSLStateEnter` | 进入状态（包括过渡中） |
| `OnSLStatePostEnter` | 完全进入状态（过渡结束后第一帧） |
| `OnSLStateNoTransitionUpdate` | 状态稳定运行中（无过渡） |
| `OnSLTransitionToStateUpdate` | 过渡进入状态期间 |
| `OnSLTransitionFromStateUpdate` | 过渡离开状态期间 |
| `OnSLStatePreExit` | 即将离开状态（过渡开始后第一帧） |
| `OnSLStateExit` | 完全离开状态 |

相比原始的三个回调，这七个回调让你精确控制过渡动画的每个阶段。

---

## 实战使用

```csharp
// 步骤1：定义 SMB 子类
public class AttackSMB : SceneLinkedSMB<CharacterController>
{
    protected override void OnSLStatePostEnter(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
        // 完全进入攻击状态：生成攻击判定框
        m_MonoBehaviour.SpawnAttackHitbox();
    }
    
    protected override void OnSLStateNoTransitionUpdate(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
        // 攻击动画稳定运行：更新判定框位置
        m_MonoBehaviour.UpdateHitboxPosition();
    }
    
    protected override void OnSLStatePreExit(Animator animator, AnimatorStateInfo stateInfo, int layerIndex)
    {
        // 即将结束：销毁判定框
        m_MonoBehaviour.DestroyAttackHitbox();
    }
}

// 步骤2：在 CharacterController 中初始化
public class CharacterController : MonoBehaviour
{
    [SerializeField] private Animator _animator;
    
    private void Start()
    {
        // 建立连接：所有挂在 Animator 上的 AttackSMB 都会获得 this 的引用
        SceneLinkedSMB<CharacterController>.Initialise(_animator, this);
    }
    
    public void SpawnAttackHitbox() { /* ... */ }
    public void UpdateHitboxPosition() { /* ... */ }
    public void DestroyAttackHitbox() { /* ... */ }
}
```

---

## inactive 检查的重要性

```csharp
public sealed override void OnStateUpdate(...)
{
    if (!animator.gameObject.activeSelf) return;  // ← 这行很重要！
    // ...
}
```

当 GameObject 被禁用（`SetActive(false)`）时，Unity 仍然可能调用 `OnStateUpdate`（取决于 Animator 的 `cullingMode` 设置）。

添加 `activeSelf` 检查确保：禁用的对象不会执行 SMB 逻辑，避免操作空引用或无效对象。

---

## m_FirstFrameHappened 和 m_LastFrameHappened 的设计

这两个标志解决了一个微妙问题：

**问题**：`OnStateUpdate` 在动画完全进入和开始离开的帧都会被调用，但我们需要区分"刚进入完成的第一帧"和"普通运行帧"。

**解决**：
- `m_FirstFrameHappened = false`：每次 `OnStateEnter` 时重置
- 检测到"不在过渡中"且 `m_FirstFrameHappened == false`：说明是"完全进入后的第一帧"，触发 `OnSLStatePostEnter`，然后设为 `true`
- `m_LastFrameHappened = false`：每次 `OnStateEnter` 时重置
- 检测到"在过渡中（离开）"且 `m_LastFrameHappened == false`：说明是"开始离开的第一帧"，触发 `OnSLStatePreExit`，设为 `true`

---

## 与 AnimationEvent 对比

Unity 还有另一种方式在动画事件时执行代码：`AnimationEvent`（在动画剪辑上打标记）。

| 特性 | SceneLinkedSMB | AnimationEvent |
|------|---------------|---------------|
| 时机精度 | 以帧为单位，基于过渡状态 | 可以精确到动画时间点 |
| 访问 MonoBehaviour | 通过初始化建立引用 | 通过 SendMessage（字符串方法名） |
| 性能 | 好（直接引用） | 较差（SendMessage 反射） |
| 编辑器友好性 | 需要代码 | 可视化拖拽 |
| 适用场景 | 状态级别的逻辑 | 特定时间点触发（如打击帧） |

两者互补：SceneLinkedSMB 管理状态级别的逻辑（攻击框的生成和销毁），AnimationEvent 管理特定时间点触发（攻击音效、粒子特效）。

---

## 总结

`SceneLinkedSMB` 展示了一个精妙的设计模式：

1. **泛型桥接**：`SceneLinkedSMB<T>` 让 SMB 类型安全地持有任意 MonoBehaviour 引用
2. **初始化分离**：`Initialise` 在 MonoBehaviour.Start 中调用，建立引用而不是每帧 GetComponent
3. **精细生命周期**：通过过渡状态检测，提供比 Unity 原始 API 更精细的 7 个生命周期回调

对于任何需要在动画状态中执行游戏逻辑的场景（攻击判定、动作特效、音效触发），`SceneLinkedSMB` 都是比直接用 `StateMachineBehaviour` 更优雅的选择。
