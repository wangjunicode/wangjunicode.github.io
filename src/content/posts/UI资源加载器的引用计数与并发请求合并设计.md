---
title: UI资源加载器的引用计数与并发请求合并设计
published: 2026-03-31
description: 深入分析UI框架中资源加载器的引用计数机制与并发请求防重设计，解决UI资源的加载与卸载时机问题
tags: [Unity, UI框架, 资源管理]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# UI资源加载器的引用计数与并发请求合并设计

UI资源管理是Unity项目中最容易踩坑的领域之一。常见的问题包括：
- 同一个UI面板被加载了两次，内存双份
- 面板打开时资源还没加载完就尝试访问，空引用崩溃
- 面板关闭后资源立刻卸载，但还有其他UI在用，导致材质丢失

xgame项目的`xgameUILoader`用引用计数+并发合并机制优雅地解决了这些问题。本文深入剖析这套设计。

## 一、核心数据结构：xgameUILoadHandle

```csharp
public class xgameUILoadHandle : IRefPool
{
    internal string ResloadPath { get; private set; }  // 资源路径
    internal int RefCount { get; private set; }         // 引用计数
    internal Object Object { get; private set; }        // 已加载的资源对象
    internal bool WaitAsync { get; private set; }       // 是否正在异步加载中
    
    internal void AddRefCount() { RefCount++; }
    
    internal void RemoveRefCount()
    {
        RefCount--;
        if (RefCount <= 0)
        {
            Release(); // 引用归零，自动卸载
        }
    }
    
    private void Release()
    {
        // 通知LoadHandleHelper注销并释放资源
        xgameLoadHandleHelper.PutLoad(ResloadPath);
    }
    
    // IRefPool接口：归还到对象池时重置状态
    public void Recycle()
    {
        ResloadPath = string.Empty;
        RefCount = 0;
        Object = null;
    }
}
```

`xgameUILoadHandle`是资源加载的句柄，与资源路径1对1绑定。它通过引用计数管理资源的生命周期：
- 每次有UI引用该资源 → `AddRefCount()`
- 每次UI关闭/不再使用 → `RemoveRefCount()`
- 引用数归零 → 自动卸载资源

`WaitAsync`是一个关键的状态标志，下面会详细解释。

## 二、两级索引：路径→Handle，对象→Handle

```csharp
public static class xgameLoadHandleHelper
{
    // 路径 → Handle（用于查找"这个资源已经在加载/加载完了吗"）
    private static Dictionary<string, xgameUILoadHandle> m_AllLoad = new();
    
    // 对象 → Handle（用于通过资源对象反查Handle，进行引用计数管理）
    private static Dictionary<Object, xgameUILoadHandle> m_ObjLoadHandle = new();
}
```

为什么需要两个字典？

- 通过**路径**查询：加载开始时，用路径查找是否已有Handle在处理这个资源（防重复加载）
- 通过**对象**查询：资源卸载时，通过资源对象找到Handle，调用`RemoveRefCount()`

## 三、并发请求合并——最精妙的设计

假设同时有3个UI需要同一个资源，怎么处理？

**朴素做法**：3个UI各自发起一次异步加载，加载完成后谁用谁的。问题：同一资源被加载了3次，内存占用3倍。

**xgameUILoader的做法**：

```csharp
public override async ETTask<T> LoadAssetAsync<T>(string resLoadPath, string loaderName)
{
    // 显示Mini Loading指示器
    var code = YIUIMiniLoadingHelper.Instance.Show();
    var result = await DoLoadAssetAsync<T>(resLoadPath, loaderName);
    YIUIMiniLoadingHelper.Instance.Hide(code);
    return result;
}

protected async ETTask<T> DoLoadAssetAsync<T>(string resLoadPath, string loaderName) 
    where T : UnityEngine.Object
{
    var load = xgameLoadHandleHelper.GetLoad(resLoadPath); // 获取或创建Handle
    load.AddRefCount(); // 先加引用计数（即使还没加载完）
    
    var loadObj = load.Object;
    
    // 情况1：资源已经在内存里了，直接返回
    if (loadObj != null) return (T)loadObj;
    
    // 情况2：资源正在加载中（另一个协程先发起了加载）
    if (load.WaitAsync)
    {
        // 等待直到加载完成（WaitAsync变为false）
        await ETTaskWaitUntil.WaitUntil(() => !load.WaitAsync);
        
        loadObj = load.Object;
        if (loadObj != null) return (T)loadObj;
        
        // 加载失败
        load.RemoveRefCount();
        return null;
    }
    
    // 情况3：第一个请求，开始加载
    load.SetWaitAsync(true); // 标记：正在加载中
    
    // 先检查缓存
    var obj = AssetCache.GetCachedAsset<T>(resLoadPath);
    if (obj == null)
    {
        // 从Addressables/AB加载
        await LoadCommonDependentAsync(loaderName, resPaths: resLoadPath);
        obj = AssetCache.GetCachedAsset<T>(resLoadPath);
    }
    
    if (obj == null)
    {
        load.SetWaitAsync(false);
        load.RemoveRefCount();
        return null;
    }
    
    // 注册对象→Handle的映射
    xgameLoadHandleHelper.AddLoadHandle(obj, load);
    load.ResetHandle(obj);
    load.SetWaitAsync(false); // 加载完成，唤醒等待的协程
    return obj;
}
```

关键流程：

1. **第一个请求**（`WaitAsync=false`且`Object=null`）：标记`WaitAsync=true`，开始实际加载，加载完设置`Object`，然后`WaitAsync=false`
2. **后续并发请求**（`WaitAsync=true`）：进入等待，通过`ETTaskWaitUntil`轮询直到`WaitAsync=false`，然后直接使用第一个请求加载好的`Object`
3. **资源已在内存**（`Object!=null`）：直接返回，不产生任何IO

这样无论有多少并发请求，**同一资源只会被加载一次**。

## 四、MiniLoading指示器的联动

```csharp
public override async ETTask<T> LoadAssetAsync<T>(string resLoadPath, string loaderName)
{
    var code = YIUIMiniLoadingHelper.Instance.Show(); // 显示小转圈
    var result = await DoLoadAssetAsync<T>(resLoadPath, loaderName);
    YIUIMiniLoadingHelper.Instance.Hide(code);        // 隐藏小转圈
    return result;
}
```

每次异步加载都会触发MiniLoading（屏幕角落的小转圈加载指示器）。注意用`code`而不是直接Hide，因为可能多个加载并发进行，需要等所有加载都完成了才隐藏（最后一个Hide才真正消失）。

## 五、同步加载的前提条件

```csharp
/// <summary>
/// 同步方法调用前需要确保资源已经加载
/// </summary>
public override T LoadAsset<T>(string resLoadPath)
{
    var load = xgameLoadHandleHelper.GetLoad(resLoadPath);
    load.AddRefCount();
    var loadObj = load.Object;
    if (loadObj != null)
    {
        return (T)loadObj;
    }
    // 从缓存直接取（不触发IO）
    var obj = AssetCache.GetCachedAsset<T>(resLoadPath);
    // ...
}
```

同步加载方法的注释非常重要：`同步方法调用前需要确保资源已经加载`。

这意味着同步加载**不是真的同步加载**，它只是从内存缓存里取资源。如果资源不在内存里，它不会阻塞等待加载（没有IO操作），而是返回null。

使用场景：某些UI打开时，资源肯定已经在内存里（比如已经异步预加载过了），这时用同步加载省去await的开销。

## 六、UIObjectPoolManager：被注释掉的优化

```csharp
public static class UIObjectPoolManager
{
    private static Dictionary<string, Queue<IRecycleUI>> dict = new();

    public static T Get<T>(string key) where T : UIBase
    {
        // 【注释掉的对象池逻辑】
        // if (!dict.ContainsKey(key)) { ... }
        // else { if (dict[key].Count > 0) { /* 从池里取 */ } }
        
        // 目前：直接创建
        return CreateItem<T>(key);
    }
    
    public static void Push(string key, IRecycleUI ui)
    {
        // 【注释掉的回收逻辑】
        // ui.Recycle();
        // dict[key].Enqueue(ui);
    }
}
```

这里有一段被注释掉的UI对象池代码，非常值得研究。代码是写好的，但被注释了，说明项目经历了这样的决策过程：

**为什么实现了对象池然后注释掉？**

可能的原因：
1. UI对象池的回收需要处理"脏数据"——比如上次使用时绑定的数据需要清空，实现`Recycle()`复杂
2. UI对象重用时，动画状态需要重置，否则会出现"上次的动画状态还在"的问题
3. 调试时发现对象池引入了更多bug，暂时禁用，直接创建更稳定

这段注释掉的代码是**技术债务的痕迹**——团队知道对象池更优，但目前的实现不稳定，所以折中先用创建的方式。

## 七、接口设计：IRecycleUI

```csharp
public interface IRecycleUI
{
    void Recycle(); // 归还时重置状态
}
```

虽然对象池暂时被注释掉了，但接口保留了。这体现了"面向接口设计"：即使实现还没完善，接口契约已经定义好，未来恢复对象池时，只需要取消注释，实现了`IRecycleUI`的UI类可以直接复用。

## 八、实战中的注意事项

**1. 加引用计数要在等待前**

```csharp
load.AddRefCount(); // 必须在await之前加！

var loadObj = load.Object;
if (loadObj != null) return (T)loadObj;

if (load.WaitAsync)
{
    await ETTaskWaitUntil.WaitUntil(() => !load.WaitAsync);
    // ...
}
```

如果在await之后才加引用计数，那么在等待期间，第一个加载完成并减了引用计数，引用可能归零触发卸载，等待结束后拿到的是已卸载的资源。

**2. 加载失败时要记得RemoveRefCount**

每个提前return的失败路径都有`load.RemoveRefCount()`，确保计数对称。如果遗漏，引用计数会比实际使用者多，资源永远不会被卸载（内存泄漏）。

## 九、总结

这套UI加载器解决了三个核心问题：

| 问题 | 解决方案 |
|------|---------|
| 并发重复加载 | WaitAsync标志，后续请求等待第一个加载完成 |
| 资源过早卸载 | 引用计数，归零才卸载 |
| 资源残留不释放 | 显式RemoveRefCount，计数对称 |

对新手来说，这套设计最大的价值是：**在UI框架层统一处理资源管理，业务代码不需要关心何时加载、何时卸载，只需要用就好**。
