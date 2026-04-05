---
title: 游戏AI导航系统深度解析：NavMesh与动态障碍
published: 2026-03-31
description: 深度解析Unity NavMesh导航系统的高级应用，包含NavMesh Agent配置（优先级/回避/爬坡）、运行时NavMesh动态修改（NavMeshSurface重烘焙）、动态障碍物（NavMeshObstacle雕刻模式）、多层NavMesh（飞行/游泳/地面多Agent类型）、路径预计算与分摊、大世界分区NavMesh加载，以及NavMesh调试与可视化工具。
tags: [Unity, NavMesh, 游戏AI, 寻路系统, 游戏开发]
category: 游戏AI
draft: false
encryptedKey: henhaoji123
---

## 一、NavMesh Agent 高级配置

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// 智能NavMesh Agent控制器
/// </summary>
public class SmartNavAgent : MonoBehaviour
{
    [Header("Agent配置")]
    [SerializeField] private NavMeshAgent agent;
    [SerializeField] private float stoppingDistance = 1.5f;
    [SerializeField] private float pathfindingUpdateInterval = 0.2f;
    
    [Header("行为配置")]
    [SerializeField] private float waypointReachThreshold = 0.5f;
    [SerializeField] private bool predictTargetPosition = true;
    [SerializeField] private float predictionTime = 0.5f;
    
    private Transform target;
    private float pathTimer;
    private Vector3 lastTargetPos;
    private NavMeshPath cachedPath;
    
    public bool IsReachedDestination => !agent.pathPending && 
        agent.remainingDistance <= stoppingDistance;

    void Awake()
    {
        agent = GetComponent<NavMeshAgent>();
        cachedPath = new NavMeshPath();
        
        ConfigureAgent();
    }

    void ConfigureAgent()
    {
        agent.stoppingDistance = stoppingDistance;
        agent.updateRotation = true;
        agent.angularSpeed = 300f;
        agent.acceleration = 8f;
        
        // 回避配置（多AI同时寻路时防止挤在一起）
        agent.obstacleAvoidanceType = ObstacleAvoidanceType.LowQualityObstacleAvoidance;
        agent.avoidancePriority = Random.Range(30, 70); // 随机优先级，防止所有AI同一优先级卡死
    }

    void Update()
    {
        if (target == null) return;
        
        pathTimer += Time.deltaTime;
        if (pathTimer >= pathfindingUpdateInterval)
        {
            pathTimer = 0;
            UpdatePath();
        }
    }

    void UpdatePath()
    {
        if (target == null) return;
        
        // 目标位置没变则跳过（减少不必要计算）
        if (Vector3.Distance(target.position, lastTargetPos) < 0.2f)
            return;
        
        lastTargetPos = target.position;
        
        // 预测目标未来位置（追击移动目标）
        Vector3 predictedPos = target.position;
        if (predictTargetPosition)
        {
            var targetRb = target.GetComponent<Rigidbody>();
            if (targetRb != null)
                predictedPos += targetRb.velocity * predictionTime;
        }
        
        // 检查目标位置是否在NavMesh上，如果不在则取最近点
        NavMeshHit hit;
        if (NavMesh.SamplePosition(predictedPos, out hit, 5f, NavMesh.AllAreas))
            agent.SetDestination(hit.position);
    }

    public void SetTarget(Transform newTarget)
    {
        target = newTarget;
        pathTimer = pathfindingUpdateInterval; // 立即更新
    }

    public void SetDestination(Vector3 pos)
    {
        target = null;
        agent.SetDestination(pos);
    }

    public void StopMoving()
    {
        target = null;
        agent.isStopped = true;
        agent.ResetPath();
    }

    public void ResumeMoving()
    {
        agent.isStopped = false;
    }

    /// <summary>
    /// 检查是否有路径可达指定位置（非阻塞）
    /// </summary>
    public bool CanReach(Vector3 position)
    {
        if (NavMesh.CalculatePath(transform.position, position, 
            NavMesh.AllAreas, cachedPath))
        {
            return cachedPath.status == NavMeshPathStatus.PathComplete;
        }
        return false;
    }

    /// <summary>
    /// 获取路径总长度
    /// </summary>
    public float GetPathLength(Vector3 destination)
    {
        if (!NavMesh.CalculatePath(transform.position, destination, 
            NavMesh.AllAreas, cachedPath))
            return float.MaxValue;
        
        float length = 0;
        Vector3[] corners = cachedPath.corners;
        for (int i = 0; i < corners.Length - 1; i++)
            length += Vector3.Distance(corners[i], corners[i + 1]);
        
        return length;
    }
}
```

---

## 二、动态NavMesh障碍物

```csharp
/// <summary>
/// 动态障碍物管理（开关门/移动平台等）
/// </summary>
public class DynamicNavObstacle : MonoBehaviour
{
    [SerializeField] private NavMeshObstacle obstacle;
    [SerializeField] private bool carvesNavMesh = true;   // 雕刻模式（性能消耗更大但更准确）
    [SerializeField] private float carveDelay = 0.5f;     // 延迟雕刻（防止频繁雕刻）

    void Awake()
    {
        obstacle = GetComponent<NavMeshObstacle>();
        obstacle.carving = carvesNavMesh;
        obstacle.carvingMoveThreshold = 0.1f;   // 移动超过0.1m才重新雕刻
        obstacle.carvingTimeToStationary = carveDelay;
    }

    /// <summary>
    /// 禁用障碍（如门打开了）
    /// </summary>
    public void DisableObstacle()
    {
        obstacle.enabled = false;
    }

    public void EnableObstacle()
    {
        obstacle.enabled = true;
    }
}

/// <summary>
/// NavMesh运行时重烘焙（动态地形变化时）
/// </summary>
public class NavMeshRebaker : MonoBehaviour
{
    [SerializeField] private NavMeshSurface surface;
    [SerializeField] private float rebakeDelay = 1f; // 防止频繁重烘焙
    
    private float lastChangeTime;
    private bool needsRebake;

    public void RequestRebake()
    {
        lastChangeTime = Time.time;
        needsRebake = true;
    }

    void Update()
    {
        if (needsRebake && Time.time - lastChangeTime >= rebakeDelay)
        {
            needsRebake = false;
            RebakeAsync();
        }
    }

    async void RebakeAsync()
    {
        // NavMeshSurface重烘焙（主线程，但可以通过AsyncOperation优化）
        surface.BuildNavMesh();
        Debug.Log("[NavMesh] 重新烘焙完成");
    }
}
```

---

## 三、多类型NavMesh（飞行/游泳）

```csharp
/// <summary>
/// 多Agent类型配置（地面/飞行/游泳）
/// </summary>
public class MultiLayerNavSetup : MonoBehaviour
{
    // NavMesh区域设置（在NavMesh Layer设置中配置）:
    // Area 0: Walkable（地面）
    // Area 3: Water（水面/游泳）
    // Area 4: Air（飞行区域）
    
    // NavMesh Agent类型（在Navigation窗口的Agents标签配置）：
    // Humanoid：地面行走（Radius=0.5, Height=1.8）
    // Flying：飞行单位（Radius=0.3, Height=0.3，勾选Air层）
    // Swimming：水中单位（Radius=0.4，勾选Water层）
    
    [Header("飞行AI配置")]
    [SerializeField] private NavMeshAgent flyingAgent;
    [SerializeField] private int flyingAgentTypeId; // 飞行Agent类型ID
    [SerializeField] private float flyingHeight = 5f;

    void Start()
    {
        if (flyingAgent != null)
        {
            flyingAgent.agentTypeID = flyingAgentTypeId;
            
            // 飞行单位需要设置飞行区域掩码
            flyingAgent.areaMask = 1 << NavMesh.GetAreaFromName("Air") | 
                                   1 << NavMesh.GetAreaFromName("Walkable");
        }
    }

    void Update()
    {
        if (flyingAgent == null) return;
        
        // 飞行单位保持高度
        Vector3 pos = transform.position;
        pos.y = GetDesiredHeight();
        transform.position = Vector3.Lerp(transform.position, pos, Time.deltaTime * 3f);
    }

    float GetDesiredHeight()
    {
        if (Physics.Raycast(transform.position, Vector3.down, out var hit, 100f))
            return hit.point.y + flyingHeight;
        return transform.position.y;
    }
}
```

---

## 四、巡逻路径系统

```csharp
/// <summary>
/// NavMesh巡逻系统
/// </summary>
public class PatrolSystem : MonoBehaviour
{
    [SerializeField] private Transform[] waypoints;
    [SerializeField] private PatrolMode mode;
    [SerializeField] private float waitTimeAtWaypoint = 2f;
    
    public enum PatrolMode { Sequential, Random, PingPong }
    
    private NavMeshAgent agent;
    private int currentWaypointIndex;
    private int pingPongDirection = 1;
    private bool isWaiting;

    void Awake() => agent = GetComponent<NavMeshAgent>();

    void Start() => MoveToNextWaypoint();

    void Update()
    {
        if (isWaiting) return;
        
        if (!agent.pathPending && agent.remainingDistance < 0.5f)
        {
            StartCoroutine(WaitAndMoveNext());
        }
    }

    System.Collections.IEnumerator WaitAndMoveNext()
    {
        isWaiting = true;
        yield return new WaitForSeconds(waitTimeAtWaypoint);
        isWaiting = false;
        MoveToNextWaypoint();
    }

    void MoveToNextWaypoint()
    {
        if (waypoints == null || waypoints.Length == 0) return;
        
        switch (mode)
        {
            case PatrolMode.Sequential:
                currentWaypointIndex = (currentWaypointIndex + 1) % waypoints.Length;
                break;
            case PatrolMode.Random:
                currentWaypointIndex = Random.Range(0, waypoints.Length);
                break;
            case PatrolMode.PingPong:
                currentWaypointIndex += pingPongDirection;
                if (currentWaypointIndex >= waypoints.Length - 1 || currentWaypointIndex <= 0)
                    pingPongDirection *= -1;
                break;
        }
        
        agent.SetDestination(waypoints[currentWaypointIndex].position);
    }
}
```

---

## 五、NavMesh优化要点

| 优化项 | 方案 |
|--------|------|
| 路径更新频率 | 不要每帧更新路径，0.1-0.2s间隔即可 |
| 回避优先级 | 随机化优先级，防止多AI同时同优先级卡死 |
| 动态障碍 | 设置合理的carving延迟，防止频繁重算 |
| 路径缓存 | 重用 NavMeshPath 对象，避免GC |
| 目标变化检测 | 目标位置变化不大时跳过路径更新 |
| 大世界分区 | 分区加载NavMesh，不加载全地图 |
