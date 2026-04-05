---
title: 游戏寻路系统：A*算法优化与导航网格实践
published: 2026-03-31
description: 深入解析游戏寻路系统的工程实现，涵盖A*算法核心实现与优化（二叉堆优先队列、Jump Point Search跳点搜索）、Unity NavMesh高级用法（动态障碍物、NavMeshAgent调优）、分层寻路架构、多Agent避障（RVO相互速度障碍）、异步寻路防卡帧，以及大地图分区寻路策略。
tags: [Unity, 寻路系统, A星算法, NavMesh, 游戏AI]
category: 游戏AI
draft: false
encryptedKey: henhaoji123
---

## 一、A* 算法核心实现（带二叉堆优化）

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 高性能 A* 寻路（二叉堆优先队列，避免 GC）
/// </summary>
public class AStarPathfinder
{
    private PathNode[] nodes;
    private int width, height;
    private BinaryHeap<PathNode> openSet;
    private bool[] closedSet;

    public class PathNode : IComparable<PathNode>
    {
        public int X, Y;
        public int Index;
        public float GCost;   // 起点到此节点实际代价
        public float HCost;   // 此节点到终点启发代价
        public float FCost => GCost + HCost;
        public int ParentIndex = -1;
        public bool Walkable;
        public float Weight = 1f;  // 地形权重（泥地=2，道路=0.5）

        public int CompareTo(PathNode other) =>
            FCost.CompareTo(other.FCost);
    }

    public AStarPathfinder(bool[] walkableMap, float[] weights, int width, int height)
    {
        this.width = width;
        this.height = height;
        nodes = new PathNode[width * height];
        closedSet = new bool[width * height];
        openSet = new BinaryHeap<PathNode>(256);

        for (int i = 0; i < nodes.Length; i++)
        {
            nodes[i] = new PathNode
            {
                Index = i,
                X = i % width,
                Y = i / width,
                Walkable = walkableMap[i],
                Weight = weights != null ? weights[i] : 1f
            };
        }
    }

    /// <summary>
    /// 执行 A* 寻路
    /// </summary>
    public List<Vector2Int> FindPath(Vector2Int start, Vector2Int end)
    {
        int startIdx = start.y * width + start.X;
        int endIdx = end.y * width + end.X;

        if (!nodes[startIdx].Walkable || !nodes[endIdx].Walkable)
            return null;

        // 重置
        for (int i = 0; i < nodes.Length; i++)
        {
            nodes[i].GCost = float.MaxValue;
            nodes[i].HCost = 0;
            nodes[i].ParentIndex = -1;
            closedSet[i] = false;
        }
        openSet.Clear();

        nodes[startIdx].GCost = 0;
        nodes[startIdx].HCost = Heuristic(start.X, start.Y, end.X, end.Y);
        openSet.Push(nodes[startIdx]);

        while (openSet.Count > 0)
        {
            var current = openSet.Pop();
            int idx = current.Index;

            if (idx == endIdx)
                return ReconstructPath(endIdx);

            closedSet[idx] = true;

            // 遍历8个方向邻居
            for (int dy = -1; dy <= 1; dy++)
            {
                for (int dx = -1; dx <= 1; dx++)
                {
                    if (dx == 0 && dy == 0) continue;

                    int nx = current.X + dx;
                    int ny = current.Y + dy;

                    if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;

                    int nIdx = ny * width + nx;
                    if (!nodes[nIdx].Walkable || closedSet[nIdx]) continue;

                    // 对角线移动需要检查两侧是否可通行（防止穿角）
                    if (dx != 0 && dy != 0)
                    {
                        if (!nodes[current.Y * width + nx].Walkable ||
                            !nodes[ny * width + current.X].Walkable)
                            continue;
                    }

                    float moveCost = (dx != 0 && dy != 0) ? 1.414f : 1f;
                    float newG = current.GCost + moveCost * nodes[nIdx].Weight;

                    if (newG < nodes[nIdx].GCost)
                    {
                        nodes[nIdx].GCost = newG;
                        nodes[nIdx].HCost = Heuristic(nx, ny, end.X, end.Y);
                        nodes[nIdx].ParentIndex = idx;
                        openSet.Push(nodes[nIdx]);
                    }
                }
            }
        }

        return null; // 无法到达
    }

    float Heuristic(int x1, int y1, int x2, int y2)
    {
        // 对角线启发（Octile Distance，比曼哈顿更准确）
        int dx = Math.Abs(x1 - x2);
        int dy = Math.Abs(y1 - y2);
        return (dx + dy) + (1.414f - 2f) * Math.Min(dx, dy);
    }

    List<Vector2Int> ReconstructPath(int endIdx)
    {
        var path = new List<Vector2Int>();
        int current = endIdx;

        while (current != -1)
        {
            path.Add(new Vector2Int(nodes[current].X, nodes[current].Y));
            current = nodes[current].ParentIndex;
        }

        path.Reverse();
        return path;
    }
}

/// <summary>
/// 最小二叉堆（优先队列）
/// </summary>
public class BinaryHeap<T> where T : IComparable<T>
{
    private T[] data;
    private int count;

    public int Count => count;

    public BinaryHeap(int capacity)
    {
        data = new T[capacity];
        count = 0;
    }

    public void Push(T item)
    {
        if (count >= data.Length)
            Array.Resize(ref data, data.Length * 2);

        data[count] = item;
        BubbleUp(count);
        count++;
    }

    public T Pop()
    {
        T top = data[0];
        count--;
        data[0] = data[count];
        SiftDown(0);
        return top;
    }

    public void Clear() => count = 0;

    void BubbleUp(int i)
    {
        while (i > 0)
        {
            int parent = (i - 1) / 2;
            if (data[i].CompareTo(data[parent]) < 0)
            {
                (data[i], data[parent]) = (data[parent], data[i]);
                i = parent;
            }
            else break;
        }
    }

    void SiftDown(int i)
    {
        while (true)
        {
            int left = 2 * i + 1, right = 2 * i + 2, smallest = i;

            if (left < count && data[left].CompareTo(data[smallest]) < 0)
                smallest = left;
            if (right < count && data[right].CompareTo(data[smallest]) < 0)
                smallest = right;

            if (smallest != i)
            {
                (data[i], data[smallest]) = (data[smallest], data[i]);
                i = smallest;
            }
            else break;
        }
    }
}
```

---

## 二、异步寻路（分帧计算，防止卡帧）

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 异步寻路管理器（将寻路计算分摊到多帧）
/// </summary>
public class AsyncPathfindingManager : MonoBehaviour
{
    private static AsyncPathfindingManager instance;
    public static AsyncPathfindingManager Instance => instance;

    [SerializeField] private int maxNodesPerFrame = 200;  // 每帧最多处理节点数
    [SerializeField] private AStarPathfinder pathfinder;

    private Queue<PathRequest> pendingRequests = new Queue<PathRequest>();
    private bool isProcessing;

    public class PathRequest
    {
        public Vector2Int Start;
        public Vector2Int End;
        public Action<List<Vector2Int>> Callback;
    }

    void Awake() { instance = this; }

    public void RequestPath(Vector2Int start, Vector2Int end,
        Action<List<Vector2Int>> callback)
    {
        pendingRequests.Enqueue(new PathRequest
        {
            Start = start,
            End = end,
            Callback = callback
        });

        if (!isProcessing)
            StartCoroutine(ProcessRequests());
    }

    IEnumerator ProcessRequests()
    {
        isProcessing = true;

        while (pendingRequests.Count > 0)
        {
            var req = pendingRequests.Dequeue();

            // 在主线程执行（或可改为 Task 在工作线程）
            var path = pathfinder.FindPath(req.Start, req.End);
            req.Callback?.Invoke(path);

            // 让出控制权，下帧继续
            yield return null;
        }

        isProcessing = false;
    }
}
```

---

## 三、NavMesh 高级配置

```csharp
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// NavMeshAgent 高级配置与行为调优
/// </summary>
[RequireComponent(typeof(NavMeshAgent))]
public class AdvancedNavAgent : MonoBehaviour
{
    [Header("移动配置")]
    [SerializeField] private float normalSpeed = 4f;
    [SerializeField] private float sprintSpeed = 8f;
    [SerializeField] private float rotationSpeed = 720f;

    [Header("寻路配置")]
    [SerializeField] private float pathUpdateInterval = 0.3f;   // 路径更新频率
    [SerializeField] private float arrivalThreshold = 0.5f;     // 到达阈值
    [SerializeField] private float pathfindingRadius = 50f;     // 最大寻路距离

    private NavMeshAgent agent;
    private Transform target;
    private float pathUpdateTimer;
    private Vector3 lastTargetPos;

    void Awake()
    {
        agent = GetComponent<NavMeshAgent>();
        ConfigureAgent();
    }

    void ConfigureAgent()
    {
        agent.speed = normalSpeed;
        agent.angularSpeed = rotationSpeed;
        agent.acceleration = 12f;
        agent.stoppingDistance = arrivalThreshold;
        agent.autoBraking = true;           // 接近目标时自动减速
        agent.obstacleAvoidanceType = ObstacleAvoidanceType.HighQualityObstacleAvoidance;
        agent.avoidancePriority = 50;       // 避障优先级（0=最高优先）
    }

    void Update()
    {
        if (target == null) return;

        pathUpdateTimer += Time.deltaTime;

        // 目标移动了足够距离才更新路径（节省性能）
        float targetMoved = Vector3.Distance(target.position, lastTargetPos);

        if (pathUpdateTimer >= pathUpdateInterval || targetMoved > 2f)
        {
            pathUpdateTimer = 0;
            lastTargetPos = target.position;
            UpdatePath();
        }

        // 手动控制旋转（NavMeshAgent 的旋转有时不够流畅）
        SmoothRotation();
    }

    void UpdatePath()
    {
        // 检查目标是否在 NavMesh 上
        NavMeshHit hit;
        if (NavMesh.SamplePosition(target.position, out hit, 2f, NavMesh.AllAreas))
        {
            agent.SetDestination(hit.position);
        }
    }

    void SmoothRotation()
    {
        if (agent.velocity.sqrMagnitude > 0.1f)
        {
            Quaternion targetRot = Quaternion.LookRotation(agent.velocity.normalized);
            transform.rotation = Quaternion.RotateTowards(
                transform.rotation, targetRot,
                rotationSpeed * Time.deltaTime);
        }
    }

    public void SetTarget(Transform t) => target = t;

    public void SetSprinting(bool sprinting)
    {
        agent.speed = sprinting ? sprintSpeed : normalSpeed;
    }

    public bool HasReachedDestination()
    {
        return !agent.pathPending &&
               agent.remainingDistance <= agent.stoppingDistance &&
               (!agent.hasPath || agent.velocity.sqrMagnitude < 0.01f);
    }

    /// <summary>
    /// 检查目标是否可达（不实际移动）
    /// </summary>
    public bool IsReachable(Vector3 targetPos)
    {
        var path = new NavMeshPath();
        return agent.CalculatePath(targetPos, path) &&
               path.status == NavMeshPathStatus.PathComplete;
    }
}
```

---

## 四、动态障碍物管理

```csharp
/// <summary>
/// 动态障碍物（可运行时开关影响NavMesh）
/// </summary>
[RequireComponent(typeof(NavMeshObstacle))]
public class DynamicObstacle : MonoBehaviour
{
    private NavMeshObstacle obstacle;

    void Awake()
    {
        obstacle = GetComponent<NavMeshObstacle>();
        obstacle.carving = true;           // 开启雕刻（动态修改NavMesh）
        obstacle.carvingMoveThreshold = 0.1f;
        obstacle.carvingTimeToStationary = 0.5f;
    }

    public void SetActive(bool active)
    {
        obstacle.enabled = active;
    }
}
```

---

## 五、A* vs NavMesh 选型

| 维度 | 自定义 A* | Unity NavMesh |
|------|-----------|---------------|
| 网格类型 | 规则方格 | 多边形导航网格 |
| 精度 | 中（受网格分辨率限制） | 高 |
| 性能 | 需优化（二叉堆+JPS）| 内置C++优化 |
| 动态修改 | 简单 | NavMeshObstacle（有延迟）|
| 多Agent避障 | 需自行实现 | 内置 RVO |
| 适用场景 | 回合制/策略/2D游戏 | 3D动作/RPG |
