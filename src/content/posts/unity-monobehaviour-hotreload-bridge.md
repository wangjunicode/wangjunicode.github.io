---
title: Unity MonoBehaviour 桥接设计：热更新代码与引擎的优雅连接
published: 2026-03-31
description: 深入解析热更新架构中 MonoBehaviour 桥接层的设计原理，理解如何在保持 Unity 生命周期的同时让热更新代码控制所有逻辑。
tags: [Unity, 热更新, MonoBehaviour, 架构设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 热更新的根本限制

`HybridCLR`（原 huatuo）是目前主流的 Unity 热更新方案，允许在运行时加载 C# DLL。但它有一个根本限制：

**热更新的类不能继承 MonoBehaviour 后被 Unity 序列化/反序列化。**

具体来说：
- 热更新 DLL 中的类：可以在代码中创建、调用
- 热更新 DLL 中的 MonoBehaviour：不能通过 Unity Inspector 挂载到 GameObject
- 热更新 DLL 中的类：可以被原生代码持有和调用

这意味着**热更新代码无法直接作为 Unity 组件**，需要一个桥接层。

---

## 桥接模式设计

基本思路：原生 DLL 提供"空壳" MonoBehaviour，热更新 DLL 提供真正的逻辑：

```csharp
// 原生 DLL（不热更新）：空壳 MonoBehaviour
public class GameObjectBridge : MonoBehaviour
{
    // 持有热更新侧的逻辑处理器
    private IBridgeHandler _handler;
    
    // 游戏对象的唯一 ID（用于在 Entity 系统中查找对应的 Entity）
    public long EntityId;
    
    public void SetHandler(IBridgeHandler handler)
    {
        _handler = handler;
    }
    
    // 所有 Unity 生命周期转发给热更新侧
    private void Awake()     => _handler?.OnAwake(this);
    private void Start()     => _handler?.OnStart();
    private void Update()    => _handler?.OnUpdate();
    private void LateUpdate() => _handler?.OnLateUpdate();
    private void OnDestroy() => _handler?.OnDestroy();
    
    private void OnTriggerEnter(Collider other) 
        => _handler?.OnTriggerEnter(other);
    private void OnCollisionEnter(Collision collision)
        => _handler?.OnCollisionEnter(collision);
}

// 接口定义（原生 DLL）
public interface IBridgeHandler
{
    void OnAwake(MonoBehaviour mono);
    void OnStart();
    void OnUpdate();
    void OnLateUpdate();
    void OnDestroy();
    void OnTriggerEnter(Collider other);
    void OnCollisionEnter(Collision collision);
}
```

---

## 热更新侧的实现

```csharp
// 热更新 DLL 中的实现
public class CharacterBridgeHandler : IBridgeHandler
{
    private GameObjectBridge _bridge;
    private Entity _entity;
    private Animator _animator;
    private Rigidbody _rigidbody;
    
    public void OnAwake(MonoBehaviour mono)
    {
        _bridge = mono as GameObjectBridge;
        
        // 通过 Entity ID 获取对应的游戏实体
        _entity = EntityManager.Get(_bridge.EntityId);
        
        // 获取 Unity 组件（通过桥接对象）
        _animator = _bridge.GetComponent<Animator>();
        _rigidbody = _bridge.GetComponent<Rigidbody>();
    }
    
    public void OnStart()
    {
        // 初始化动画状态
        SceneLinkedSMB<CharacterBridgeHandler>.Initialise(_animator, this);
    }
    
    public void OnUpdate()
    {
        // 处理移动
        var moveInput = InputManager.Instance.GetMoveInput();
        _rigidbody.velocity = new Vector3(moveInput.x, 0, moveInput.y) * 5f;
        
        // 更新动画参数
        _animator.SetBool("IsMoving", moveInput.magnitude > 0.1f);
    }
    
    public void OnDestroy()
    {
        // 清理 Entity
        EntityManager.Destroy(_entity);
    }
    
    public void OnTriggerEnter(Collider other)
    {
        // 触发拾取道具等逻辑
        if (other.TryGetComponent<ItemPickup>(out var item))
        {
            item.Collect(_entity);
        }
    }
    
    // 未使用的接口方法
    public void OnLateUpdate() { }
    public void OnCollisionEnter(Collision collision) { }
}
```

---

## 组件绑定流程

```csharp
// 创建角色的完整流程
public async ETTask SpawnCharacter(string prefabPath, Vector3 position)
{
    // 1. 从 Addressables 加载 Prefab
    var prefab = await ResManager.LoadAsync<GameObject>(prefabPath);
    
    // 2. 实例化（包含桥接 MonoBehaviour）
    var go = await ResManager.InstantiatePrefabAsync(prefab);
    go.transform.position = position;
    
    // 3. 获取桥接组件
    var bridge = go.GetComponent<GameObjectBridge>();
    
    // 4. 创建热更新侧的 Entity
    var entity = EntityManager.Create<CharacterEntity>();
    bridge.EntityId = entity.Id;
    
    // 5. 创建热更新侧的 Handler 并绑定
    var handler = new CharacterBridgeHandler();
    bridge.SetHandler(handler);
    
    // 6. 手动触发 Awake（如果 GameObject 已经 Active）
    // handler.OnAwake(bridge) 会在 MonoBehaviour.Awake 中自动调用
}
```

---

## 物理回调桥接

对于物理相关的回调（碰撞、触发器），桥接模式允许在热更新代码中安全处理：

```csharp
// 原生 DLL：物理桥接
public class PhysicsBridge : MonoBehaviour
{
    public Action<Collider> OnTriggerEnterCallback;
    public Action<Collider> OnTriggerExitCallback;
    public Action<Collision> OnCollisionEnterCallback;
    
    private void OnTriggerEnter(Collider other)
        => OnTriggerEnterCallback?.Invoke(other);
    
    private void OnTriggerExit(Collider other)
        => OnTriggerExitCallback?.Invoke(other);
    
    private void OnCollisionEnter(Collision collision)
        => OnCollisionEnterCallback?.Invoke(collision);
}

// 热更新代码中使用
var physicsBridge = hitbox.GetComponent<PhysicsBridge>();
physicsBridge.OnTriggerEnterCallback = (other) =>
{
    if (other.TryGetComponent<IDamageable>(out var damageable))
    {
        damageable.TakeDamage(attackData.Damage);
    }
};
```

---

## 总结

MonoBehaviour 桥接设计的核心思想：

| 层次 | 代码位置 | 职责 |
|------|---------|------|
| 桥接层（空壳）| 原生 DLL | 接收 Unity 生命周期回调，转发给热更新 |
| 逻辑层（实现）| 热更新 DLL | 真正的游戏逻辑 |
| 数据层 | 热更新 DLL | Entity-Component 数据 |

这种设计让热更新覆盖了几乎所有的游戏逻辑，原生代码只保留了最薄的桥接层。当游戏需要修复 Bug 或添加新功能时，只需要下发新的热更新 DLL，玩家不需要重新下载整个游戏包。
