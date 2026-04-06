---
title: 游戏寻路系统扩展：动态障碍与实时NavMesh重建
published: 2026-03-31
description: 深度解析游戏中动态障碍物对寻路系统的影响与解决方案，涵盖NavMeshObstacle动态遮挡、局部NavMesh实时重建（NavMeshSurface）、障碍变化事件驱动重规划、网格分区局部更新优化、可破坏地形与NavMesh同步，以及大世界流式NavMesh加载。
tags: [Unity, NavMesh, 动态寻路, AI, 游戏开发]
category: 游戏AI
draft: false
encryptedKey:henhaoji123
---

## 一、静态 vs 动态障碍

| 方案 | 适用场景 | 性能 | 实时性 |
|------|----------|------|--------|
| NavMeshObstacle（Carving）| 可移动但不频繁变化 | 好 | 秒级更新 |
| NavMeshSurface 局部重建 | 地形被破坏/创建 | 较差 | 帧级更新 |
| OffMeshLink 动态禁用 | 门/桥梁开关 | 极好 | 即时 |
| 自定义寻路网格 | 全定制需求 | 可控 | 完全可控 |

---

## 二、NavMeshObstacle 动态障碍

```csharp
using UnityEngine;
using UnityEngine.AI;
using System.Collections;

/// <summary>
/// 动态障碍物控制器（门/箱子/可移动障碍）
/// </summary>
[RequireComponent(typeof(NavMeshObstacle))]
public class DynamicObstacle : MonoBehaviour
{
    [Header("Carving 配置")]
    [SerializeField] private bool enableCarving = true;        // 是否在NavMesh上雕刻孔洞
    [SerializeField] private float carvingMoveThreshold = 0.1f; // 移动多少距离触发重新雕刻
    [SerializeField] private float carvingTimeToStationary = 0.5f; // 静止多久后开始雕刻
    
    private NavMeshObstacle obstacle;

    void Awake()
    {
        obstacle = GetComponent<NavMeshObstacle>();
        obstacle.carving = enableCarving;
        obstacle.carvingMoveThreshold = carvingMoveThreshold;
        obstacle.carvingTimeToStationary = carvingTimeToStationary;
    }

    /// <summary>
    /// 临时禁用障碍（如：门打开）
    /// </summary>
    public void OpenDoor()
    {
        // 方法1：禁用Carving（NavMesh恢复通行）
        obstacle.carving = false;
        obstacle.enabled = false;
        
        // 通知附近正在等待的AI重新规划
        NotifyNearbyAgents();
    }

    public void CloseDoor()
    {
        obstacle.enabled = true;
        obstacle.carving = enableCarving;
        NotifyNearbyAgents();
    }

    void NotifyNearbyAgents()
    {
        // 通知范围内的 NavMeshAgent 重新路径规划
        var colliders = Physics.OverlapSphere(transform.position, 20f);
        foreach (var col in colliders)
        {
            var agent = col.GetComponent<NavMeshAgent>();
            if (agent != null && agent.isOnNavMesh)
            {
                // 重新计算路径
                if (agent.hasPath)
                {
                    Vector3 destination = agent.destination;
                    agent.ResetPath();
                    agent.SetDestination(destination);
                }
            }
        }
    }
}
```

---

## 三、局部 NavMesh 实时重建

```csharp
using UnityEngine;
using UnityEngine.AI;
using System.Collections;

/// <summary>
/// 局部 NavMesh 动态重建（可破坏地形）
/// 需要安装 NavMeshComponents 包（NavMeshSurface）
/// </summary>
public class LocalNavMeshRebuilder : MonoBehaviour
{
    [Header("重建配置")]
    [SerializeField] private NavMeshSurface navMeshSurface;
    [SerializeField] private float rebuildRadius = 10f;          // 重建半径
    [SerializeField] private float rebuildDelay = 0.5f;          // 延迟重建（批量合并）
    [SerializeField] private bool asyncRebuild = true;           // 异步重建
    
    private bool rebuildPending;
    private float rebuildTimer;
    private Bounds pendingBounds;
    private bool boundsInitialized;

    void Update()
    {
        if (!rebuildPending) return;
        
        rebuildTimer += Time.deltaTime;
        if (rebuildTimer >= rebuildDelay)
        {
            rebuildPending = false;
            rebuildTimer = 0;
            
            if (asyncRebuild)
                StartCoroutine(RebuildAsync(pendingBounds));
            else
                RebuildSync(pendingBounds);
            
            boundsInitialized = false;
        }
    }

    /// <summary>
    /// 请求在指定位置重建 NavMesh
    /// （多次请求会合并到一次重建）
    /// </summary>
    public void RequestRebuild(Vector3 center, float radius)
    {
        Bounds bounds = new Bounds(center, Vector3.one * radius * 2);
        
        if (!boundsInitialized)
        {
            pendingBounds = bounds;
            boundsInitialized = true;
        }
        else
        {
            pendingBounds.Encapsulate(bounds);
        }
        
        rebuildPending = true;
        rebuildTimer = 0; // 重置延迟
    }

    IEnumerator RebuildAsync(Bounds bounds)
    {
        Debug.Log($"[NavMesh] 异步重建 NavMesh，区域: {bounds}");
        
        // Unity NavMesh Components 支持异步更新
        AsyncOperation op = navMeshSurface.UpdateNavMesh(navMeshSurface.navMeshData);
        
        while (!op.isDone)
            yield return null;
        
        Debug.Log("[NavMesh] NavMesh 重建完成");
        OnRebuildComplete(bounds);
    }

    void RebuildSync(Bounds bounds)
    {
        // 同步重建（会卡顿，小区域用）
        navMeshSurface.BuildNavMesh();
        OnRebuildComplete(bounds);
    }

    void OnRebuildComplete(Bounds bounds)
    {
        // 通知重建区域内的AI重新规划路径
        var agents = FindObjectsOfType<NavMeshAgent>();
        foreach (var agent in agents)
        {
            if (bounds.Contains(agent.transform.position) && agent.hasPath)
            {
                Vector3 dest = agent.destination;
                agent.ResetPath();
                agent.SetDestination(dest);
            }
        }
    }
}

/// <summary>
/// 可破坏障碍物（破坏后触发NavMesh重建）
/// </summary>
public class DestructibleObstacle : MonoBehaviour
{
    [SerializeField] private LocalNavMeshRebuilder rebuilder;
    [SerializeField] private float destroyEffect = 5f;

    public void Destroy()
    {
        // 破坏物体
        gameObject.SetActive(false);
        
        // 请求重建
        rebuilder.RequestRebuild(transform.position, destroyEffect);
        
        // 播放破坏特效
        VFXPool.Instance?.Play("destruction_fx", transform.position);
    }
}
```

---

## 四、大世界流式 NavMesh

```csharp
/// <summary>
/// 大世界流式 NavMesh 管理
/// 按区块加载/卸载 NavMesh 数据
/// </summary>
public class StreamingNavMeshManager : MonoBehaviour
{
    [System.Serializable]
    public class NavMeshChunk
    {
        public Vector2Int ChunkCoord;
        public NavMeshData Data;
        public NavMeshDataInstance Instance;
        public bool IsLoaded;
    }

    [SerializeField] private float chunkSize = 100f;
    [SerializeField] private int loadRadius = 3;         // 角色周围加载半径（以区块为单位）
    
    private Dictionary<Vector2Int, NavMeshChunk> chunks 
        = new Dictionary<Vector2Int, NavMeshChunk>();
    private Transform playerTransform;

    void Start()
    {
        playerTransform = GameObject.FindGameObjectWithTag("Player").transform;
        InvokeRepeating(nameof(UpdateChunks), 0f, 2f); // 每2秒更新一次
    }

    void UpdateChunks()
    {
        Vector2Int playerChunk = WorldToChunk(playerTransform.position);
        
        // 确定需要加载的区块
        var neededChunks = new HashSet<Vector2Int>();
        for (int x = -loadRadius; x <= loadRadius; x++)
        {
            for (int y = -loadRadius; y <= loadRadius; y++)
            {
                neededChunks.Add(playerChunk + new Vector2Int(x, y));
            }
        }
        
        // 加载新区块
        foreach (var coord in neededChunks)
        {
            if (!chunks.TryGetValue(coord, out var chunk) || !chunk.IsLoaded)
                LoadChunk(coord);
        }
        
        // 卸载远处区块
        foreach (var kv in chunks)
        {
            if (!neededChunks.Contains(kv.Key) && kv.Value.IsLoaded)
                UnloadChunk(kv.Key);
        }
    }

    Vector2Int WorldToChunk(Vector3 worldPos)
    {
        return new Vector2Int(
            Mathf.FloorToInt(worldPos.x / chunkSize),
            Mathf.FloorToInt(worldPos.z / chunkSize));
    }

    void LoadChunk(Vector2Int coord)
    {
        // 从 Addressables/Resources 加载 NavMesh 数据
        string path = $"NavMesh/Chunk_{coord.x}_{coord.y}";
        var data = Resources.Load<NavMeshData>(path);
        
        if (data == null) return;
        
        var chunk = new NavMeshChunk
        {
            ChunkCoord = coord,
            Data = data,
            Instance = NavMesh.AddNavMeshData(data),
            IsLoaded = true
        };
        
        chunks[coord] = chunk;
        Debug.Log($"[NavMesh] Loaded chunk {coord}");
    }

    void UnloadChunk(Vector2Int coord)
    {
        if (!chunks.TryGetValue(coord, out var chunk)) return;
        
        NavMesh.RemoveNavMeshData(chunk.Instance);
        chunk.IsLoaded = false;
        Debug.Log($"[NavMesh] Unloaded chunk {coord}");
    }
}
```

---

## 五、路径重规划事件系统

```csharp
/// <summary>
/// 全局 NavMesh 变更事件总线
/// </summary>
public static class NavMeshEvents
{
    public static event Action<Bounds> OnNavMeshChanged;
    
    public static void NotifyChanged(Bounds affectedArea)
    {
        OnNavMeshChanged?.Invoke(affectedArea);
    }
}

/// <summary>
/// AI 寻路代理（响应 NavMesh 变更）
/// </summary>
public class SmartNavAgent : MonoBehaviour
{
    private NavMeshAgent agent;
    private Vector3 currentDestination;

    void Start()
    {
        agent = GetComponent<NavMeshAgent>();
        NavMeshEvents.OnNavMeshChanged += OnNavMeshChanged;
    }

    void OnDestroy()
    {
        NavMeshEvents.OnNavMeshChanged -= OnNavMeshChanged;
    }

    void OnNavMeshChanged(Bounds changedArea)
    {
        // 如果路径经过变化区域，重新规划
        if (agent.hasPath && PathIntersectsBounds(agent.path, changedArea))
        {
            agent.SetDestination(currentDestination);
        }
    }

    bool PathIntersectsBounds(NavMeshPath path, Bounds bounds)
    {
        for (int i = 0; i < path.corners.Length - 1; i++)
        {
            if (bounds.Contains(path.corners[i]) || 
                bounds.Contains(path.corners[i + 1]))
                return true;
        }
        return false;
    }

    public void SetDestination(Vector3 dest)
    {
        currentDestination = dest;
        agent.SetDestination(dest);
    }
}
```
