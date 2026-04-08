---
title: 游戏NavMesh动态修改与障碍物实时更新系统完全指南
published: 2026-04-08
description: 深度解析Unity NavMesh动态修改技术、NavMeshObstacle实时阻挡、NavMeshSurface局部重烘焙、多层NavMesh区域权重系统、以及大型开放世界中的分区NavMesh流式加载完整工程实践
tags: [Unity, 寻路系统, NavMesh, AI导航, 性能优化]
category: AI与游戏逻辑
draft: false
---

# 游戏NavMesh动态修改与障碍物实时更新系统完全指南

## 一、NavMesh动态修改的核心挑战

传统NavMesh（导航网格）是在编辑器中预先烘焙的静态数据，无法响应运行时的场景变化。然而现代游戏中存在大量需要动态修改寻路的场景：

- **塔防/城市建设**：玩家放置建筑物阻挡路径
- **可破坏场景**：门被炸开、墙壁被摧毁
- **动态障碍物**：移动的车辆、人群
- **区域效果**：毒雾区域（降低移速/权重）、传送门（快捷路径）
- **多层寻路**：陆地单位 vs 飞行单位 vs 水下单位

本文从4个层次完整解析动态NavMesh系统：
1. NavMeshObstacle雕刻实时阻挡
2. NavMeshSurface局部重烘焙
3. 自定义NavMesh区域权重系统
4. 开放世界分区流式NavMesh

---

## 二、NavMeshObstacle精细化控制

### 2.1 NavMeshObstacle工作原理与性能分析

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 动态障碍物控制器
/// 理解NavMeshObstacle的两种工作模式：
/// - Carve = false: 障碍物视为"推力"，Agent会绕开但不重新生成NavMesh
/// - Carve = true:  实时从NavMesh上"雕刻"掉该区域，较昂贵
/// </summary>
public class DynamicObstacleController : MonoBehaviour
{
    [Header("障碍物配置")]
    [SerializeField] private NavMeshObstacle _obstacle;
    [SerializeField] private bool _useCarving = true;
    
    [Header("雕刻优化配置")]
    [Tooltip("仅当移动超过此距离时才重新雕刻（减少频繁更新）")]
    [SerializeField] private float _carvingMoveThreshold = 0.1f;
    [Tooltip("障碍物停止移动后多久才开始雕刻（等待避免频繁重烘焙）")]
    [SerializeField] private float _carvingTimeToStationary = 0.5f;
    
    private Vector3 _lastCarvePosition;
    private bool _isStationary;
    private float _stationaryTimer;
    
    void Start()
    {
        if (_obstacle == null)
            _obstacle = GetComponent<NavMeshObstacle>();
        
        if (_useCarving)
        {
            // 优化雕刻参数
            _obstacle.carving = true;
            _obstacle.carvingMoveThreshold = _carvingMoveThreshold;
            _obstacle.carvingTimeToStationary = _carvingTimeToStationary;
        }
        
        _lastCarvePosition = transform.position;
    }
    
    /// <summary>
    /// 激活障碍物（放置建筑物时调用）
    /// </summary>
    public void Activate()
    {
        _obstacle.enabled = true;
        
        if (_useCarving)
        {
            // 强制立即雕刻
            _obstacle.carving = false;
            _obstacle.carving = true;
        }
    }
    
    /// <summary>
    /// 停用障碍物（建筑物被摧毁时调用）
    /// </summary>
    public void Deactivate()
    {
        _obstacle.enabled = false;
        // NavMesh会在下一帧自动填回被雕刻的区域
    }
    
    /// <summary>
    /// 临时暂停雕刻（障碍物移动中，避免频繁重烘焙）
    /// </summary>
    public void SetMoving(bool isMoving)
    {
        if (_useCarving)
            _obstacle.carving = !isMoving;
    }
}
```

### 2.2 障碍物管理池

```csharp
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 动态障碍物对象池管理器
/// 避免频繁创建/销毁NavMeshObstacle组件带来的性能开销
/// </summary>
public class NavObstaclePool : MonoBehaviour
{
    public static NavObstaclePool Instance { get; private set; }
    
    [System.Serializable]
    public class ObstacleTemplate
    {
        public string typeName;
        public GameObject prefab;
        public int initialPoolSize = 10;
    }
    
    [SerializeField] private List<ObstacleTemplate> _templates = new();
    
    private readonly Dictionary<string, Queue<NavMeshObstacle>> _pools = new();
    private readonly Dictionary<NavMeshObstacle, string> _activeObstacles = new();
    
    void Awake()
    {
        Instance = this;
        InitializePools();
    }
    
    private void InitializePools()
    {
        foreach (var template in _templates)
        {
            _pools[template.typeName] = new Queue<NavMeshObstacle>();
            
            for (int i = 0; i < template.initialPoolSize; i++)
            {
                var obstacle = CreateObstacle(template);
                obstacle.enabled = false;
                _pools[template.typeName].Enqueue(obstacle);
            }
        }
    }
    
    private NavMeshObstacle CreateObstacle(ObstacleTemplate template)
    {
        var go = Instantiate(template.prefab, transform);
        var obstacle = go.GetComponent<NavMeshObstacle>();
        if (obstacle == null)
            obstacle = go.AddComponent<NavMeshObstacle>();
        return obstacle;
    }
    
    /// <summary>
    /// 获取障碍物实例（从池中取或新建）
    /// </summary>
    public NavMeshObstacle Acquire(string typeName, Vector3 position, Quaternion rotation)
    {
        NavMeshObstacle obstacle = null;
        
        if (_pools.TryGetValue(typeName, out var pool) && pool.Count > 0)
        {
            obstacle = pool.Dequeue();
        }
        else
        {
            var template = _templates.Find(t => t.typeName == typeName);
            if (template != null)
                obstacle = CreateObstacle(template);
        }
        
        if (obstacle == null) return null;
        
        obstacle.transform.position = position;
        obstacle.transform.rotation = rotation;
        obstacle.enabled = true;
        obstacle.carving = true;
        
        _activeObstacles[obstacle] = typeName;
        return obstacle;
    }
    
    /// <summary>
    /// 归还障碍物到池
    /// </summary>
    public void Release(NavMeshObstacle obstacle)
    {
        if (!_activeObstacles.TryGetValue(obstacle, out var typeName)) return;
        
        obstacle.enabled = false;
        obstacle.carving = false;
        obstacle.transform.position = Vector3.zero; // 重置位置
        
        _activeObstacles.Remove(obstacle);
        
        if (!_pools.ContainsKey(typeName))
            _pools[typeName] = new Queue<NavMeshObstacle>();
        _pools[typeName].Enqueue(obstacle);
    }
}
```

---

## 三、NavMeshSurface局部动态重烘焙

### 3.1 分区NavMesh烘焙系统

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

#if UNITY_EDITOR || UNITY_2022_2_OR_NEWER
using Unity.AI.Navigation;
#endif

/// <summary>
/// 分区NavMesh局部重烘焙系统
/// 将大地图分割为网格区块，只重烘焙发生变化的区块
/// 使用NavMeshSurface组件（需要安装AI Navigation包）
/// </summary>
public class PartitionedNavMeshSystem : MonoBehaviour
{
    [System.Serializable]
    public class NavMeshChunk
    {
        public Vector2Int ChunkIndex;
        public Bounds ChunkBounds;
        public NavMeshSurface Surface;
        public bool IsDirty;
        public float LastBakeTime;
        
        // 异步烘焙状态
        public bool IsBaking;
        public AsyncOperation BakeOperation;
    }
    
    [Header("分区配置")]
    [SerializeField] private float _chunkSize = 50f;
    [SerializeField] private int _gridWidth = 10;
    [SerializeField] private int _gridHeight = 10;
    [SerializeField] private Vector3 _gridOrigin = Vector3.zero;
    
    [Header("重烘焙配置")]
    [SerializeField] private float _minRebakeInterval = 1.0f; // 最小重烘焙间隔（秒）
    [SerializeField] private int _maxConcurrentBakes = 2;     // 最大并发烘焙数
    [SerializeField] private bool _asyncBake = true;
    
    private NavMeshChunk[,] _chunks;
    private readonly Queue<NavMeshChunk> _bakeQueue = new();
    private int _activeBakeCount;
    
    void Start()
    {
        InitializeChunks();
    }
    
    void Update()
    {
        ProcessBakeQueue();
    }
    
    private void InitializeChunks()
    {
        _chunks = new NavMeshChunk[_gridWidth, _gridHeight];
        
        for (int x = 0; x < _gridWidth; x++)
        {
            for (int z = 0; z < _gridHeight; z++)
            {
                var center = _gridOrigin + new Vector3(
                    (x + 0.5f) * _chunkSize,
                    0,
                    (z + 0.5f) * _chunkSize
                );
                
                var chunkGO = new GameObject($"NavChunk_{x}_{z}");
                chunkGO.transform.SetParent(transform);
                chunkGO.transform.position = center;
                
                var surface = chunkGO.AddComponent<NavMeshSurface>();
                surface.collectObjects = CollectObjects.Volume;
                surface.size = new Vector3(_chunkSize, 20f, _chunkSize);
                surface.center = Vector3.zero;
                
                _chunks[x, z] = new NavMeshChunk
                {
                    ChunkIndex = new Vector2Int(x, z),
                    ChunkBounds = new Bounds(center, new Vector3(_chunkSize, 20f, _chunkSize)),
                    Surface = surface,
                    IsDirty = true // 初始需要烘焙
                };
            }
        }
        
        // 初始全量烘焙
        StartCoroutine(InitialBakeAll());
    }
    
    private IEnumerator InitialBakeAll()
    {
        Debug.Log("开始初始NavMesh全量烘焙...");
        
        for (int x = 0; x < _gridWidth; x++)
        {
            for (int z = 0; z < _gridHeight; z++)
            {
                var chunk = _chunks[x, z];
                chunk.Surface.BuildNavMesh();
                chunk.IsDirty = false;
                chunk.LastBakeTime = Time.time;
            }
            
            yield return null; // 每行烘焙后让出一帧
        }
        
        Debug.Log("NavMesh初始烘焙完成！");
    }
    
    /// <summary>
    /// 标记某个世界坐标范围内的区块为脏（需要重烘焙）
    /// </summary>
    public void MarkAreaDirty(Bounds worldBounds)
    {
        for (int x = 0; x < _gridWidth; x++)
        {
            for (int z = 0; z < _gridHeight; z++)
            {
                var chunk = _chunks[x, z];
                if (chunk.ChunkBounds.Intersects(worldBounds))
                {
                    if (!chunk.IsDirty && !chunk.IsBaking)
                    {
                        chunk.IsDirty = true;
                        // 检查距上次烘焙是否超过最小间隔
                        if (Time.time - chunk.LastBakeTime >= _minRebakeInterval)
                        {
                            _bakeQueue.Enqueue(chunk);
                        }
                    }
                }
            }
        }
    }
    
    /// <summary>
    /// 标记单个点周围的区块为脏
    /// </summary>
    public void MarkPointDirty(Vector3 worldPos, float radius = 5f)
    {
        var bounds = new Bounds(worldPos, Vector3.one * radius * 2);
        MarkAreaDirty(bounds);
    }
    
    private void ProcessBakeQueue()
    {
        while (_bakeQueue.Count > 0 && _activeBakeCount < _maxConcurrentBakes)
        {
            var chunk = _bakeQueue.Dequeue();
            if (!chunk.IsDirty || chunk.IsBaking) continue;
            
            if (_asyncBake)
                StartCoroutine(BakeChunkAsync(chunk));
            else
                BakeChunkSync(chunk);
        }
    }
    
    private void BakeChunkSync(NavMeshChunk chunk)
    {
        chunk.IsBaking = true;
        chunk.Surface.BuildNavMesh();
        chunk.IsDirty = false;
        chunk.IsBaking = false;
        chunk.LastBakeTime = Time.time;
        
        Debug.Log($"NavMesh区块 {chunk.ChunkIndex} 同步重烘焙完成");
    }
    
    private IEnumerator BakeChunkAsync(NavMeshChunk chunk)
    {
        chunk.IsBaking = true;
        _activeBakeCount++;
        
        // NavMesh异步烘焙（Unity 2022.2+支持）
        var asyncOp = chunk.Surface.UpdateNavMesh(chunk.Surface.navMeshData);
        
        while (!asyncOp.isDone)
        {
            yield return null;
        }
        
        chunk.IsDirty = false;
        chunk.IsBaking = false;
        chunk.LastBakeTime = Time.time;
        _activeBakeCount--;
        
        Debug.Log($"NavMesh区块 {chunk.ChunkIndex} 异步重烘焙完成");
    }
    
    /// <summary>
    /// 获取某世界坐标所在的区块索引
    /// </summary>
    public Vector2Int WorldToChunkIndex(Vector3 worldPos)
    {
        var localPos = worldPos - _gridOrigin;
        return new Vector2Int(
            Mathf.FloorToInt(localPos.x / _chunkSize),
            Mathf.FloorToInt(localPos.z / _chunkSize)
        );
    }
    
    void OnDrawGizmosSelected()
    {
        if (_chunks == null) return;
        
        for (int x = 0; x < _gridWidth; x++)
        {
            for (int z = 0; z < _gridHeight; z++)
            {
                var chunk = _chunks[x, z];
                Gizmos.color = chunk.IsDirty ? Color.red : 
                               chunk.IsBaking ? Color.yellow : 
                               new Color(0, 1, 0, 0.1f);
                Gizmos.DrawWireCube(chunk.ChunkBounds.center, chunk.ChunkBounds.size);
            }
        }
    }
}
```

---

## 四、NavMesh区域权重系统

### 4.1 自定义区域类型与代价

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// NavMesh区域权重动态管理器
/// Unity支持32种区域类型，每种有独立的移动代价（cost）
/// cost越高，Agent越不愿意经过该区域
/// </summary>
public class NavMeshAreaManager : MonoBehaviour
{
    public static NavMeshAreaManager Instance { get; private set; }
    
    // 区域类型枚举（对应Unity Project Settings中的NavMesh Area)
    public enum AreaType
    {
        Walkable = 0,        // 默认可行走区域，cost=1
        NotWalkable = 1,     // 不可行走
        Jump = 2,            // 跳跃区域
        Mud = 3,             // 泥地，cost高（移动慢）
        Water = 4,           // 水面（特殊单位可行走）
        Danger = 5,          // 危险区域（敌方阵地）
        Highway = 6,         // 高速路（cost低，AI优先走）
        Indoor = 7,          // 室内区域
    }
    
    // 各区域基础代价（可运行时动态修改）
    private readonly float[] _areaCosts = 
    {
        1f,    // Walkable
        float.MaxValue, // NotWalkable
        1.5f,  // Jump
        3f,    // Mud
        2f,    // Water
        5f,    // Danger
        0.5f,  // Highway（优先走）
        1.2f,  // Indoor
    };
    
    void Awake()
    {
        Instance = this;
        ApplyAllAreaCosts();
    }
    
    private void ApplyAllAreaCosts()
    {
        for (int i = 0; i < _areaCosts.Length; i++)
        {
            NavMesh.SetAreaCost(i, _areaCosts[i]);
        }
    }
    
    /// <summary>
    /// 动态修改区域代价（如游戏中出现毒雾，提高该区域cost）
    /// </summary>
    public void SetAreaCost(AreaType area, float cost)
    {
        int index = (int)area;
        _areaCosts[index] = cost;
        NavMesh.SetAreaCost(index, cost);
        Debug.Log($"NavMesh区域 {area} 代价设置为 {cost}");
    }
    
    /// <summary>
    /// 获取区域掩码（用于NavMeshAgent.areaMask）
    /// </summary>
    public static int GetAreaMask(params AreaType[] areas)
    {
        int mask = 0;
        foreach (var area in areas)
            mask |= 1 << (int)area;
        return mask;
    }
    
    /// <summary>
    /// 配置Agent可行走区域
    /// 示例：飞行单位可以走所有区域；地面单位不能走水面
    /// </summary>
    public void ConfigureAgentAreas(NavMeshAgent agent, bool isFlying, bool canSwim)
    {
        if (isFlying)
        {
            // 飞行单位可通行所有区域
            agent.areaMask = NavMesh.AllAreas;
        }
        else if (canSwim)
        {
            agent.areaMask = GetAreaMask(
                AreaType.Walkable, AreaType.Mud, 
                AreaType.Water, AreaType.Highway, AreaType.Indoor
            );
        }
        else
        {
            // 普通地面单位
            agent.areaMask = GetAreaMask(
                AreaType.Walkable, AreaType.Mud, 
                AreaType.Highway, AreaType.Indoor
            );
        }
    }
}
```

### 4.2 区域触发器（动态改变区域权重）

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 区域效果触发器
/// 物体进入/离开时动态修改NavMesh区域代价
/// 典型用途：毒雾、火区、减速陷阱
/// </summary>
public class NavMeshAreaEffect : MonoBehaviour
{
    [Header("效果配置")]
    [SerializeField] private NavMeshAreaManager.AreaType _targetArea;
    [SerializeField] private float _activeCost = 10f;   // 激活时的代价
    [SerializeField] private float _inactiveCost = 1f;  // 停用时的代价
    
    [Header("NavMesh修改器")]
    [SerializeField] private NavMeshModifierVolume _modifierVolume;
    
    private bool _isActive = false;
    
    /// <summary>
    /// 激活区域效果（如毒雾扩散）
    /// </summary>
    public void Activate()
    {
        if (_isActive) return;
        _isActive = true;
        
        // 方式1：通过代价系统（全局影响）
        NavMeshAreaManager.Instance?.SetAreaCost(_targetArea, _activeCost);
        
        // 方式2：通过NavMeshModifierVolume（局部影响，推荐）
        if (_modifierVolume != null)
        {
            _modifierVolume.area = (int)_targetArea;
            _modifierVolume.enabled = true;
        }
        
        Debug.Log($"NavMesh区域效果激活：{_targetArea}，代价={_activeCost}");
    }
    
    public void Deactivate()
    {
        if (!_isActive) return;
        _isActive = false;
        
        NavMeshAreaManager.Instance?.SetAreaCost(_targetArea, _inactiveCost);
        
        if (_modifierVolume != null)
            _modifierVolume.enabled = false;
    }
}
```

---

## 五、NavMeshPath查询与路径预测系统

### 5.1 高级路径分析工具

```csharp
using UnityEngine;
using UnityEngine.AI;
using System.Collections.Generic;

/// <summary>
/// 高级NavMesh路径分析工具
/// 提供路径存在性检测、路径代价预估、最优目标选择等功能
/// </summary>
public class NavMeshPathAnalyzer : MonoBehaviour
{
    private static NavMeshPath _sharedPath;
    
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
    static void Initialize()
    {
        _sharedPath = new NavMeshPath();
    }
    
    /// <summary>
    /// 检查两点之间是否有完整可达路径
    /// </summary>
    public static bool HasCompletePath(Vector3 from, Vector3 to, int areaMask = NavMesh.AllAreas)
    {
        NavMesh.CalculatePath(from, to, areaMask, _sharedPath);
        return _sharedPath.status == NavMeshPathStatus.PathComplete;
    }
    
    /// <summary>
    /// 计算路径总长度（用于代价评估）
    /// </summary>
    public static float CalculatePathLength(Vector3 from, Vector3 to, int areaMask = NavMesh.AllAreas)
    {
        NavMesh.CalculatePath(from, to, areaMask, _sharedPath);
        
        if (_sharedPath.status == NavMeshPathStatus.PathInvalid)
            return float.MaxValue;
        
        float length = 0f;
        var corners = _sharedPath.corners;
        
        for (int i = 1; i < corners.Length; i++)
            length += Vector3.Distance(corners[i - 1], corners[i]);
        
        return length;
    }
    
    /// <summary>
    /// 从候选目标列表中选择路径最短的目标
    /// 适用于：选择最近的资源点、最近的掩体等
    /// </summary>
    public static bool FindBestTarget(
        Vector3 from, 
        IEnumerable<Vector3> candidates,
        out Vector3 bestTarget,
        int areaMask = NavMesh.AllAreas)
    {
        bestTarget = Vector3.zero;
        float bestLength = float.MaxValue;
        bool found = false;
        
        foreach (var candidate in candidates)
        {
            float length = CalculatePathLength(from, candidate, areaMask);
            if (length < bestLength)
            {
                bestLength = length;
                bestTarget = candidate;
                found = true;
            }
        }
        
        return found;
    }
    
    /// <summary>
    /// 路径阻塞检测：判断路径上是否有障碍物
    /// 用于提前预警（如炸弹即将封路）
    /// </summary>
    public static bool IsPathBlocked(NavMeshPath path, float checkRadius = 0.5f)
    {
        var corners = path.corners;
        for (int i = 0; i < corners.Length - 1; i++)
        {
            var direction = corners[i + 1] - corners[i];
            float distance = direction.magnitude;
            
            if (Physics.SphereCast(corners[i], checkRadius, direction.normalized, 
                out _, distance, ~0, QueryTriggerInteraction.Ignore))
            {
                return true;
            }
        }
        return false;
    }
    
    /// <summary>
    /// 寻找NavMesh上距目标点最近的可达位置
    /// 当目标点在NavMesh之外时使用
    /// </summary>
    public static bool FindNearestNavMeshPosition(
        Vector3 targetPos, 
        out Vector3 navMeshPos, 
        float maxDistance = 10f,
        int areaMask = NavMesh.AllAreas)
    {
        if (NavMesh.SamplePosition(targetPos, out var hit, maxDistance, areaMask))
        {
            navMeshPos = hit.position;
            return true;
        }
        navMeshPos = targetPos;
        return false;
    }
}
```

---

## 六、多Agent协同寻路优化

### 6.1 分时查询调度器（避免单帧大量路径计算）

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// NavMesh路径查询分时调度器
/// 将大量Agent的路径查询分散到多帧执行，避免单帧卡顿
/// 配合优先级队列，确保重要Agent优先处理
/// </summary>
public class NavMeshQueryScheduler : MonoBehaviour
{
    public static NavMeshQueryScheduler Instance { get; private set; }
    
    [System.Serializable]
    public class PathRequest
    {
        public NavMeshAgent Agent;
        public Vector3 Destination;
        public int Priority; // 数值越高越优先
        public System.Action<bool> OnComplete;
    }
    
    [Header("调度配置")]
    [SerializeField] private int _maxQueriesPerFrame = 10;
    [SerializeField] private float _staggerInterval = 0.05f; // 跨帧间隔
    
    // 优先级队列（简化实现，实际项目可用SortedList）
    private readonly List<PathRequest> _pendingRequests = new();
    private readonly NavMeshPath _tempPath = new NavMeshPath();
    
    void Awake()
    {
        Instance = this;
        StartCoroutine(ProcessQueriesCoroutine());
    }
    
    /// <summary>
    /// 提交路径查询请求（异步，不阻塞调用帧）
    /// </summary>
    public void RequestPath(
        NavMeshAgent agent, 
        Vector3 destination, 
        System.Action<bool> onComplete = null,
        int priority = 0)
    {
        // 移除同一Agent的旧请求
        _pendingRequests.RemoveAll(r => r.Agent == agent);
        
        _pendingRequests.Add(new PathRequest
        {
            Agent = agent,
            Destination = destination,
            Priority = priority,
            OnComplete = onComplete
        });
        
        // 按优先级排序（降序）
        _pendingRequests.Sort((a, b) => b.Priority.CompareTo(a.Priority));
    }
    
    private IEnumerator ProcessQueriesCoroutine()
    {
        while (true)
        {
            int processed = 0;
            
            while (_pendingRequests.Count > 0 && processed < _maxQueriesPerFrame)
            {
                var request = _pendingRequests[0];
                _pendingRequests.RemoveAt(0);
                
                if (request.Agent == null || !request.Agent.enabled)
                {
                    request.OnComplete?.Invoke(false);
                    continue;
                }
                
                // 执行路径计算
                bool success = NavMesh.CalculatePath(
                    request.Agent.transform.position,
                    request.Destination,
                    request.Agent.areaMask,
                    _tempPath
                );
                
                bool complete = _tempPath.status == NavMeshPathStatus.PathComplete;
                
                if (complete && success)
                {
                    request.Agent.SetPath(_tempPath);
                }
                
                request.OnComplete?.Invoke(complete);
                processed++;
            }
            
            yield return new WaitForSeconds(_staggerInterval);
        }
    }
    
    /// <summary>
    /// 大量Agent批量更新目标（如战斗AI寻找攻击目标）
    /// </summary>
    public void BatchUpdateDestinations(
        List<NavMeshAgent> agents, 
        List<Vector3> destinations,
        int basePriority = 0)
    {
        for (int i = 0; i < agents.Count && i < destinations.Count; i++)
        {
            RequestPath(agents[i], destinations[i], null, basePriority);
        }
    }
}
```

### 6.2 Agent避让分组系统

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// NavMesh Agent避让优先级管理
/// 控制不同类型Unit的避让行为，实现合理的拥挤排队
/// </summary>
public class AgentAvoidanceConfig : MonoBehaviour
{
    public enum AgentType
    {
        Infantry,    // 步兵：互相避让
        Vehicle,     // 车辆：推开步兵，不让车辆
        VIP,         // VIP：所有人让开
        Crowd,       // 人群：低避让优先级，可被推开
    }
    
    [SerializeField] private AgentType _agentType;
    private NavMeshAgent _agent;
    
    void Start()
    {
        _agent = GetComponent<NavMeshAgent>();
        ConfigureAvoidance(_agentType);
    }
    
    private void ConfigureAvoidance(AgentType type)
    {
        switch (type)
        {
            case AgentType.Infantry:
                _agent.avoidancePriority = 50;    // 中等优先级
                _agent.obstacleAvoidanceType = ObstacleAvoidanceType.HighQualityObstacleAvoidance;
                _agent.radius = 0.5f;
                break;
                
            case AgentType.Vehicle:
                _agent.avoidancePriority = 20;    // 高优先级（数值越小越优先）
                _agent.obstacleAvoidanceType = ObstacleAvoidanceType.GoodQualityObstacleAvoidance;
                _agent.radius = 1.5f;
                break;
                
            case AgentType.VIP:
                _agent.avoidancePriority = 0;     // 最高优先级，所有人让开
                _agent.obstacleAvoidanceType = ObstacleAvoidanceType.HighQualityObstacleAvoidance;
                _agent.radius = 0.4f;
                break;
                
            case AgentType.Crowd:
                _agent.avoidancePriority = 99;    // 最低优先级，会被推开
                _agent.obstacleAvoidanceType = ObstacleAvoidanceType.NoObstacleAvoidance;
                _agent.radius = 0.3f;
                break;
        }
    }
}
```

---

## 七、开放世界NavMesh流式加载

### 7.1 基于摄像机距离的NavMesh数据流式管理

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 开放世界NavMesh流式加载管理器
/// 根据玩家位置动态加载/卸载NavMesh数据分片
/// 配合Addressables实现NavMeshData的异步加载
/// </summary>
public class NavMeshStreamingManager : MonoBehaviour
{
    [System.Serializable]
    public class NavMeshTile
    {
        public Vector2Int TileIndex;
        public string AddressableKey; // NavMeshData的Addressables地址
        public NavMeshDataInstance DataInstance;
        public bool IsLoaded;
        public float LoadDistance;   // 在此距离内加载
        public float UnloadDistance; // 超过此距离卸载
    }
    
    [Header("流式配置")]
    [SerializeField] private Transform _playerTransform;
    [SerializeField] private float _tileSize = 100f;
    [SerializeField] private float _loadRadius = 200f;
    [SerializeField] private float _unloadRadius = 300f;
    [SerializeField] private float _checkInterval = 2f;
    
    private readonly Dictionary<Vector2Int, NavMeshTile> _tiles = new();
    private readonly Dictionary<Vector2Int, Coroutine> _loadingCoroutines = new();
    
    void Start()
    {
        StartCoroutine(StreamingUpdateLoop());
    }
    
    private IEnumerator StreamingUpdateLoop()
    {
        while (true)
        {
            yield return new WaitForSeconds(_checkInterval);
            
            if (_playerTransform == null) continue;
            
            var playerPos = _playerTransform.position;
            var playerTile = WorldToTileIndex(playerPos);
            
            int tilesInRadius = Mathf.CeilToInt(_loadRadius / _tileSize);
            
            // 加载范围内的瓦片
            for (int x = playerTile.x - tilesInRadius; x <= playerTile.x + tilesInRadius; x++)
            {
                for (int z = playerTile.y - tilesInRadius; z <= playerTile.y + tilesInRadius; z++)
                {
                    var tileIdx = new Vector2Int(x, z);
                    var tileCenter = TileIndexToWorld(tileIdx);
                    float dist = Vector3.Distance(playerPos, tileCenter);
                    
                    if (dist <= _loadRadius)
                        RequestLoadTile(tileIdx);
                }
            }
            
            // 卸载范围外的瓦片
            var toUnload = new List<Vector2Int>();
            foreach (var kvp in _tiles)
            {
                var tileCenter = TileIndexToWorld(kvp.Key);
                float dist = Vector3.Distance(playerPos, tileCenter);
                
                if (dist > _unloadRadius && kvp.Value.IsLoaded)
                    toUnload.Add(kvp.Key);
            }
            
            foreach (var idx in toUnload)
                UnloadTile(idx);
        }
    }
    
    private void RequestLoadTile(Vector2Int tileIndex)
    {
        if (_tiles.ContainsKey(tileIndex) && _tiles[tileIndex].IsLoaded) return;
        if (_loadingCoroutines.ContainsKey(tileIndex)) return;
        
        var coroutine = StartCoroutine(LoadTileAsync(tileIndex));
        _loadingCoroutines[tileIndex] = coroutine;
    }
    
    private IEnumerator LoadTileAsync(Vector2Int tileIndex)
    {
        string key = $"NavMesh/Tile_{tileIndex.x}_{tileIndex.y}";
        
        // 使用Addressables异步加载NavMeshData
        var handle = UnityEngine.AddressableAssets.Addressables
            .LoadAssetAsync<NavMeshData>(key);
        
        yield return handle;
        
        if (handle.Status == UnityEngine.ResourceManagement.AsyncOperations.AsyncOperationStatus.Succeeded)
        {
            var data = handle.Result;
            var position = new NavMeshDataInstance();
            
            // 将NavMeshData实例添加到全局NavMesh
            var pose = new UnityEngine.AI.NavMeshBuildSettings();
            var instance = NavMesh.AddNavMeshData(data, 
                TileIndexToWorld(tileIndex), Quaternion.identity);
            
            _tiles[tileIndex] = new NavMeshTile
            {
                TileIndex = tileIndex,
                AddressableKey = key,
                DataInstance = instance,
                IsLoaded = true
            };
            
            Debug.Log($"NavMesh瓦片 {tileIndex} 加载完成");
        }
        else
        {
            Debug.LogWarning($"NavMesh瓦片 {tileIndex} 加载失败");
        }
        
        _loadingCoroutines.Remove(tileIndex);
    }
    
    private void UnloadTile(Vector2Int tileIndex)
    {
        if (!_tiles.TryGetValue(tileIndex, out var tile)) return;
        if (!tile.IsLoaded) return;
        
        // 从NavMesh中移除数据
        NavMesh.RemoveNavMeshData(tile.DataInstance);
        tile.IsLoaded = false;
        _tiles.Remove(tileIndex);
        
        Debug.Log($"NavMesh瓦片 {tileIndex} 已卸载");
    }
    
    private Vector2Int WorldToTileIndex(Vector3 worldPos)
    {
        return new Vector2Int(
            Mathf.FloorToInt(worldPos.x / _tileSize),
            Mathf.FloorToInt(worldPos.z / _tileSize)
        );
    }
    
    private Vector3 TileIndexToWorld(Vector2Int tileIndex)
    {
        return new Vector3(
            (tileIndex.x + 0.5f) * _tileSize,
            0,
            (tileIndex.y + 0.5f) * _tileSize
        );
    }
}
```

---

## 八、最佳实践总结

### 8.1 性能优化要点

```markdown
## NavMesh动态系统10大性能准则

1. **Carve优先于Rebuild**
   - NavMeshObstacle.carving=true 比重烘焙快10-100倍
   - 仅在场景结构发生根本改变时才触发Rebuild

2. **合并脏区域**
   - 多个相邻障碍物放置时，等待一小帧后批量重烘一个区域
   - 避免每次放置都立即触发重烘

3. **异步烘焙分帧**
   - 使用Surface.UpdateNavMesh()的异步接口
   - 绝不在主线程同步烘焙大型NavMesh

4. **路径查询分帧**
   - 使用QueryScheduler将大量路径查询分散到多帧
   - 单帧路径查询上限：50-100个（视CPU性能）

5. **缓存路径结果**
   - 路径不需要每帧重算
   - 只在目标点变化或Agent被阻挡时重新查询

6. **区域成本代替几何阻挡**
   - 软性障碍（减速区、危险区）用Area Cost
   - 硬性障碍（墙、建筑）才用几何NavMeshObstacle

7. **流式加载减少内存**
   - 大地图NavMeshData按区块存储并动态加载
   - 非活跃区域NavMesh可以卸载

8. **避让优先级合理设置**
   - 不要所有Agent都用HighQuality避让
   - 背景NPC用NoAvoidance，只有主要角色才用高质量

9. **Off-MeshLink谨慎使用**
   - Off-MeshLink（跳跃、传送门）有额外CPU开销
   - 高频寻路场景中Off-MeshLink数量控制在100以内

10. **NavMesh烘焙预热**
    - 游戏启动时在后台线程预烘焙玩家起始区域
    - 避免玩家第一次操作时遭遇卡顿
```

### 8.2 常见问题排查

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| Agent绕路很远 | Area Cost设置不合理 | 检查NavMesh Area窗口的Cost值 |
| Agent在障碍物边缘卡住 | Carve尺寸不够大 | 增大NavMeshObstacle的size |
| 放置建筑后路径不更新 | Carve延迟 | 降低carvingTimeToStationary |
| 大量Agent同帧寻路卡顿 | 路径查询集中 | 使用QueryScheduler分帧 |
| 跨区域寻路失败 | NavMesh分片间无连接 | 确保分片边界有重叠或Off-MeshLink |
| 重烘焙后Agent悬空 | NavMesh面偏低 | 调整NavMeshSurface的voxelSize |

---

## 总结

NavMesh动态修改系统是现代开放世界游戏的基础设施之一。通过**NavMeshObstacle雕刻**（毫秒级响应）、**局部区块重烘焙**（可接受延迟的精确修改）、**区域权重系统**（软性路径引导）和**流式NavMesh加载**（内存控制），可以构建一个既灵活又高性能的动态寻路系统。关键在于根据具体游戏类型选择合适的策略组合：建造类游戏依赖局部重烘焙，大规模RTS依赖批量查询调度，开放世界RPG则需要流式加载能力。
