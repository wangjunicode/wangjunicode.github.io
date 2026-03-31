---
title: Unity资源管理进阶：引用计数与循环依赖检测
published: 2026-03-31
description: 深度解析Unity资源管理的工程实践，包含基于引用计数的资源生命周期管理（引用为0自动卸载）、资源依赖图构建（Addressables依赖链）、循环依赖检测算法（DFS拓扑排序）、资源热引用检测（哪些资源始终被持有不释放）、资源内存占用分析，以及大型项目资源管理规范。
tags: [Unity, 资源管理, 引用计数, Addressables, 内存优化]
category: 性能优化
draft: false
---

## 一、引用计数资源管理器

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.ResourceManagement.AsyncOperations;
using UnityEngine.AddressableAssets;

public class RefCountedAssetManager : MonoBehaviour
{
    private static RefCountedAssetManager instance;
    public static RefCountedAssetManager Instance => instance;
    
    private class AssetEntry
    {
        public string Key;
        public UnityEngine.Object Asset;
        public int RefCount;
        public AsyncOperationHandle Handle;
        public float LastAccessTime;
    }
    
    private Dictionary<string, AssetEntry> assetCache 
        = new Dictionary<string, AssetEntry>();
    
    // 空闲超时（引用为0后多久卸载）
    private const float IDLE_UNLOAD_DELAY = 30f;

    void Awake() { instance = this; DontDestroyOnLoad(gameObject); }
    
    void Update()
    {
        // 定期检查空闲资源
        CheckIdleAssets();
    }

    /// <summary>
    /// 加载资源（自动增加引用计数）
    /// </summary>
    public async System.Threading.Tasks.Task<T> LoadAsync<T>(string key) 
        where T : UnityEngine.Object
    {
        if (assetCache.TryGetValue(key, out var entry))
        {
            entry.RefCount++;
            entry.LastAccessTime = Time.time;
            return entry.Asset as T;
        }
        
        var handle = Addressables.LoadAssetAsync<T>(key);
        await handle.Task;
        
        if (handle.Status != AsyncOperationStatus.Succeeded)
        {
            Debug.LogError($"[AssetMgr] 加载失败: {key}");
            return null;
        }
        
        var newEntry = new AssetEntry
        {
            Key = key,
            Asset = handle.Result,
            RefCount = 1,
            Handle = handle,
            LastAccessTime = Time.time
        };
        
        assetCache[key] = newEntry;
        return handle.Result;
    }

    /// <summary>
    /// 释放资源引用
    /// </summary>
    public void Release(string key)
    {
        if (!assetCache.TryGetValue(key, out var entry)) return;
        
        entry.RefCount = Math.Max(0, entry.RefCount - 1);
        entry.LastAccessTime = Time.time;
        
        if (entry.RefCount <= 0)
            Debug.Log($"[AssetMgr] 资源引用归零: {key}（将在{IDLE_UNLOAD_DELAY}秒后卸载）");
    }

    void CheckIdleAssets()
    {
        var toUnload = new List<string>();
        float now = Time.time;
        
        foreach (var kv in assetCache)
        {
            if (kv.Value.RefCount <= 0 && 
                now - kv.Value.LastAccessTime > IDLE_UNLOAD_DELAY)
            {
                toUnload.Add(kv.Key);
            }
        }
        
        foreach (var key in toUnload)
        {
            var entry = assetCache[key];
            Addressables.Release(entry.Handle);
            assetCache.Remove(key);
            Debug.Log($"[AssetMgr] 已卸载资源: {key}");
        }
    }

    public int GetRefCount(string key) => 
        assetCache.TryGetValue(key, out var e) ? e.RefCount : 0;
    
    public int GetCachedCount() => assetCache.Count;
    
    [ContextMenu("Print Asset Cache")]
    public void PrintCache()
    {
        foreach (var kv in assetCache)
            Debug.Log($"  {kv.Key}: refs={kv.Value.RefCount}, idle={(Time.time - kv.Value.LastAccessTime):F0}s");
    }
}
```

---

## 二、循环依赖检测

```csharp
#if UNITY_EDITOR
/// <summary>
/// 编辑器工具：检测Addressables包之间的循环依赖
/// </summary>
public class CircularDependencyDetector : UnityEditor.EditorWindow
{
    [UnityEditor.MenuItem("Tools/Game/检测循环依赖")]
    static void Open() => GetWindow<CircularDependencyDetector>("循环依赖检测");

    void OnGUI()
    {
        if (GUILayout.Button("开始检测")) Detect();
    }

    void Detect()
    {
        var settings = UnityEditor.AddressableAssets.AddressableAssetSettingsDefaultObject.Settings;
        if (settings == null) { Debug.LogError("找不到Addressables设置"); return; }
        
        // 构建依赖图
        var graph = new Dictionary<string, HashSet<string>>();
        foreach (var group in settings.groups)
        {
            foreach (var entry in group.entries)
            {
                graph[entry.address] = new HashSet<string>();
                var deps = UnityEditor.AssetDatabase.GetDependencies(entry.AssetPath);
                foreach (var dep in deps)
                {
                    var depEntry = settings.FindAssetEntry(dep);
                    if (depEntry != null) graph[entry.address].Add(depEntry.address);
                }
            }
        }
        
        // DFS检测循环
        var visited = new HashSet<string>();
        var stack = new HashSet<string>();
        
        foreach (var node in graph.Keys)
        {
            if (!visited.Contains(node))
                DFSCheck(node, graph, visited, stack);
        }
        
        Debug.Log("[CircularDep] 检测完成");
    }

    void DFSCheck(string node, Dictionary<string, HashSet<string>> graph,
        HashSet<string> visited, HashSet<string> stack)
    {
        visited.Add(node);
        stack.Add(node);
        
        if (graph.ContainsKey(node))
        {
            foreach (var neighbor in graph[node])
            {
                if (!visited.Contains(neighbor))
                    DFSCheck(neighbor, graph, visited, stack);
                else if (stack.Contains(neighbor))
                    Debug.LogWarning($"[CircularDep] 发现循环依赖: {node} -> {neighbor}");
            }
        }
        
        stack.Remove(node);
    }
}
#endif
```

---

## 三、资源管理规范

| 规范 | 说明 |
|------|------|
| 加载必须配对释放 | 每个LoadAsync对应一个Release |
| 场景退出时释放 | OnDestroy中释放所有持有资源 |
| 避免重复加载 | 使用引用计数缓存 |
| 循环依赖检查 | CI流程中自动检测 |
| 包划分原则 | 按场景/功能分包，避免跨包依赖 |
| 资源预热 | 高频使用资源提前加载 |
