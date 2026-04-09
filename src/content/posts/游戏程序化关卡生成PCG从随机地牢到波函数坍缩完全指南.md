---
title: 游戏程序化关卡生成PCG：从随机地牢到波函数坍缩完全指南
published: 2026-04-09
description: 深度解析程序化内容生成（PCG）核心算法，涵盖BSP二叉空间分割地牢生成、房间连接算法、波函数坍缩（WFC）约束传播、Perlin噪声地形生成、种子复现、编辑器工具集成，打造可无限复玩的游戏关卡系统。
tags: [Unity, PCG, 程序化生成, 关卡设计, 算法, 游戏开发]
category: 关卡设计
draft: false
---

# 游戏程序化关卡生成PCG：从随机地牢到波函数坍缩完全指南

## 一、PCG 技术概览

**程序化内容生成（Procedural Content Generation，PCG）** 是指通过算法自动创造游戏内容，而非完全依赖人工设计。

### 1.1 PCG 的核心价值

| 维度 | 传统手工设计 | PCG |
|------|------------|-----|
| 重玩性 | 低（内容固定） | 高（每次不同） |
| 开发成本 | 高（线性增长） | 低（算法一次性投入） |
| 内容规模 | 受人力限制 | 近乎无限 |
| 品质可控性 | 高 | 需要精心约束 |

代表作：《以撒的结合》（地牢PCG）、《Minecraft》（地形PCG）、《无人深空》（星球PCG）、《矮人要塞》（综合PCG）

### 1.2 本文涵盖算法

1. **BSP 二叉空间分割** - 经典地牢生成
2. **房间优先算法** - 散点式布局
3. **波函数坍缩（WFC）** - 约束驱动的图案生成
4. **Perlin/Simplex 噪声** - 连续地形高度图
5. **Delaunay 三角化** - 最小生成树道路网络

---

## 二、BSP 二叉空间分割地牢生成

### 2.1 算法原理

```
初始矩形空间
    ↓ 随机切割（水平或垂直）
  左子区 | 右子区
    ↓ 递归切割直到达到最小尺寸
  叶子节点 = 最终房间候选区
    ↓ 在每个叶子节点内放置房间
    ↓ 自底向上连接兄弟节点（走廊）
  完整地牢
```

### 2.2 完整实现

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// BSP 地牢生成器
/// </summary>
public class BSPDungeonGenerator : MonoBehaviour
{
    [Header("地牢参数")]
    public int dungeonWidth = 80;
    public int dungeonHeight = 60;
    public int minRoomSize = 8;
    public int maxSplitDepth = 5;
    
    [Header("房间参数")]
    [Range(0.4f, 0.8f)] public float roomFillRatio = 0.6f;
    
    [Header("种子")]
    public int seed = 12345;
    public bool useRandomSeed = false;

    [Header("可视化")]
    public Tilemap floorTilemap;
    public Tilemap wallTilemap;
    public TileBase floorTile;
    public TileBase wallTile;

    private System.Random _rng;
    private List<RectInt> _rooms = new();
    private List<(Vector2Int from, Vector2Int to)> _corridors = new();
    private int[,] _grid;  // 0=空, 1=地板, 2=墙

    [ContextMenu("Generate Dungeon")]
    public void Generate()
    {
        if (useRandomSeed) seed = Environment.TickCount;
        _rng = new System.Random(seed);
        _rooms.Clear();
        _corridors.Clear();
        _grid = new int[dungeonWidth, dungeonHeight];

        // BSP 分割
        var root = new BSPNode(new RectInt(0, 0, dungeonWidth, dungeonHeight));
        SplitNode(root, 0);

        // 生成房间
        GenerateRooms(root);

        // 生成走廊
        ConnectRooms(root);

        // 绘制到 Tilemap
        RenderToTilemap();

        Debug.Log($"[BSP] 生成地牢：{_rooms.Count} 个房间，seed={seed}");
    }

    #region BSP 分割

    class BSPNode
    {
        public RectInt rect;
        public BSPNode left, right;
        public RectInt room;  // 叶子节点的房间
        public bool hasRoom;

        public BSPNode(RectInt r) { rect = r; }
        public bool IsLeaf => left == null && right == null;
    }

    void SplitNode(BSPNode node, int depth)
    {
        if (depth >= maxSplitDepth) return;
        
        bool canSplitH = node.rect.height >= minRoomSize * 2;
        bool canSplitV = node.rect.width  >= minRoomSize * 2;
        
        if (!canSplitH && !canSplitV) return;

        bool splitHorizontal;
        if (canSplitH && canSplitV)
            splitHorizontal = _rng.NextDouble() < 0.5;
        else
            splitHorizontal = canSplitH;

        if (splitHorizontal)
        {
            int splitY = _rng.Next(node.rect.yMin + minRoomSize, node.rect.yMax - minRoomSize);
            node.left  = new BSPNode(new RectInt(node.rect.xMin, node.rect.yMin, node.rect.width, splitY - node.rect.yMin));
            node.right = new BSPNode(new RectInt(node.rect.xMin, splitY, node.rect.width, node.rect.yMax - splitY));
        }
        else
        {
            int splitX = _rng.Next(node.rect.xMin + minRoomSize, node.rect.xMax - minRoomSize);
            node.left  = new BSPNode(new RectInt(node.rect.xMin, node.rect.yMin, splitX - node.rect.xMin, node.rect.height));
            node.right = new BSPNode(new RectInt(splitX, node.rect.yMin, node.rect.xMax - splitX, node.rect.height));
        }

        SplitNode(node.left,  depth + 1);
        SplitNode(node.right, depth + 1);
    }

    #endregion

    #region 房间生成

    void GenerateRooms(BSPNode node)
    {
        if (node == null) return;

        if (node.IsLeaf)
        {
            // 在叶节点内随机放置房间
            int margin = 1;
            int maxW = Mathf.Max(minRoomSize, (int)(node.rect.width * roomFillRatio));
            int maxH = Mathf.Max(minRoomSize, (int)(node.rect.height * roomFillRatio));

            int roomW = _rng.Next(minRoomSize, Mathf.Min(maxW, node.rect.width - margin * 2) + 1);
            int roomH = _rng.Next(minRoomSize, Mathf.Min(maxH, node.rect.height - margin * 2) + 1);
            int roomX = _rng.Next(node.rect.xMin + margin, node.rect.xMax - roomW - margin + 1);
            int roomY = _rng.Next(node.rect.yMin + margin, node.rect.yMax - roomH - margin + 1);

            node.room = new RectInt(roomX, roomY, roomW, roomH);
            node.hasRoom = true;
            _rooms.Add(node.room);

            // 填充地板
            for (int x = roomX; x < roomX + roomW; x++)
                for (int y = roomY; y < roomY + roomH; y++)
                    _grid[x, y] = 1;
        }
        else
        {
            GenerateRooms(node.left);
            GenerateRooms(node.right);
        }
    }

    #endregion

    #region 走廊连接

    void ConnectRooms(BSPNode node)
    {
        if (node == null || node.IsLeaf) return;

        ConnectRooms(node.left);
        ConnectRooms(node.right);

        // 获取左右子树中各一个代表性房间中心
        Vector2Int leftCenter = GetRoomCenter(node.left);
        Vector2Int rightCenter = GetRoomCenter(node.right);

        // 生成 L 形走廊（先横后竖）
        CarveHorizontalCorridor(leftCenter.x, rightCenter.x, leftCenter.y);
        CarveVerticalCorridor(leftCenter.y, rightCenter.y, rightCenter.x);
        _corridors.Add((leftCenter, rightCenter));
    }

    Vector2Int GetRoomCenter(BSPNode node)
    {
        if (node.IsLeaf && node.hasRoom)
            return new Vector2Int(node.room.xMin + node.room.width / 2, node.room.yMin + node.room.height / 2);

        if (node.left != null) return GetRoomCenter(node.left);
        if (node.right != null) return GetRoomCenter(node.right);
        return new Vector2Int(node.rect.xMin + node.rect.width / 2, node.rect.yMin + node.rect.height / 2);
    }

    void CarveHorizontalCorridor(int x1, int x2, int y)
    {
        int minX = Mathf.Min(x1, x2);
        int maxX = Mathf.Max(x1, x2);
        for (int x = minX; x <= maxX; x++)
        {
            if (IsInBounds(x, y)) _grid[x, y] = 1;
            // 加宽走廊（2格宽）
            if (IsInBounds(x, y + 1)) _grid[x, y + 1] = 1;
        }
    }

    void CarveVerticalCorridor(int y1, int y2, int x)
    {
        int minY = Mathf.Min(y1, y2);
        int maxY = Mathf.Max(y1, y2);
        for (int y = minY; y <= maxY; y++)
        {
            if (IsInBounds(x, y)) _grid[x, y] = 1;
            if (IsInBounds(x + 1, y)) _grid[x + 1, y] = 1;
        }
    }

    bool IsInBounds(int x, int y) => x >= 0 && x < dungeonWidth && y >= 0 && y < dungeonHeight;

    #endregion

    #region 渲染

    void RenderToTilemap()
    {
        if (floorTilemap == null || wallTilemap == null) return;

        floorTilemap.ClearAllTiles();
        wallTilemap.ClearAllTiles();

        for (int x = 0; x < dungeonWidth; x++)
        {
            for (int y = 0; y < dungeonHeight; y++)
            {
                var pos = new Vector3Int(x, y, 0);
                if (_grid[x, y] == 1)
                {
                    floorTilemap.SetTile(pos, floorTile);
                    // 检查是否需要生成墙壁（地板边缘的空格）
                    if (IsWallNeeded(x, y))
                        wallTilemap.SetTile(pos, wallTile);
                }
            }
        }

        // 生成外围墙壁
        for (int x = 0; x < dungeonWidth; x++)
            for (int y = 0; y < dungeonHeight; y++)
                if (_grid[x, y] == 0 && HasAdjacentFloor(x, y))
                    wallTilemap.SetTile(new Vector3Int(x, y, 0), wallTile);
    }

    bool IsWallNeeded(int x, int y) => false; // 简化

    bool HasAdjacentFloor(int x, int y)
    {
        int[] dx = { -1, 1, 0, 0, -1, -1, 1, 1 };
        int[] dy = { 0, 0, -1, 1, -1, 1, -1, 1 };
        for (int i = 0; i < 8; i++)
        {
            int nx = x + dx[i], ny = y + dy[i];
            if (IsInBounds(nx, ny) && _grid[nx, ny] == 1) return true;
        }
        return false;
    }

    #endregion

    // Gizmos 可视化
    void OnDrawGizmosSelected()
    {
        if (_rooms == null) return;
        Gizmos.color = Color.green;
        foreach (var room in _rooms)
            Gizmos.DrawWireCube(new Vector3(room.xMin + room.width/2f, room.yMin + room.height/2f, 0),
                                new Vector3(room.width, room.height, 0));
    }
}
```

---

## 三、波函数坍缩（WFC）算法

WFC（Wave Function Collapse）是近年来最受关注的 PCG 算法，由 Maxim Gumin 提出，能生成符合复杂约束的图案。

### 3.1 算法核心思想

```
1. 初始化：每个格子可以是任意 tile（叠加态）
2. 观察：选择熵最小（可能性最少）的格子
3. 坍缩：随机选择一个可能的 tile
4. 传播：根据约束规则更新邻居格子的可能性
5. 重复 2-4 直到所有格子确定，或发生矛盾（回溯）
```

### 3.2 核心实现

```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

/// <summary>
/// 简化版波函数坍缩（WFC）地图生成器
/// </summary>
public class WaveFunctionCollapse : MonoBehaviour
{
    [Header("地图尺寸")]
    public int width = 20;
    public int height = 20;

    [Header("Tile 定义")]
    public TileDefinition[] tiles;

    public int seed = 42;

    private System.Random _rng;

    // 每个格子的可能 tile 集合（位集合）
    private HashSet<int>[,] _wave;

    // 邻接规则：rules[tileA][方向] = 允许的 tileB 集合
    private HashSet<int>[][] _adjacencyRules;

    // 方向：0=上, 1=右, 2=下, 3=左
    private static readonly Vector2Int[] Directions = {
        Vector2Int.up, Vector2Int.right, Vector2Int.down, Vector2Int.left
    };

    [Serializable]
    public class TileDefinition
    {
        public string name;
        public GameObject prefab;
        public float weight = 1.0f;
        // 每个方向允许相邻的 tile ID 列表
        public int[] upNeighbors;
        public int[] rightNeighbors;
        public int[] downNeighbors;
        public int[] leftNeighbors;
    }

    [ContextMenu("Generate WFC Map")]
    public void Generate()
    {
        _rng = new System.Random(seed);
        InitializeWave();
        BuildAdjacencyRules();
        
        if (Run())
            Render();
        else
            Debug.LogWarning("[WFC] 生成失败，尝试更换 seed 或放松约束");
    }

    void InitializeWave()
    {
        _wave = new HashSet<int>[width, height];
        for (int x = 0; x < width; x++)
            for (int y = 0; y < height; y++)
            {
                _wave[x, y] = new HashSet<int>();
                for (int t = 0; t < tiles.Length; t++)
                    _wave[x, y].Add(t);
            }
    }

    void BuildAdjacencyRules()
    {
        _adjacencyRules = new HashSet<int>[tiles.Length][];
        for (int t = 0; t < tiles.Length; t++)
        {
            _adjacencyRules[t] = new HashSet<int>[4];
            _adjacencyRules[t][0] = new HashSet<int>(tiles[t].upNeighbors ?? Array.Empty<int>());
            _adjacencyRules[t][1] = new HashSet<int>(tiles[t].rightNeighbors ?? Array.Empty<int>());
            _adjacencyRules[t][2] = new HashSet<int>(tiles[t].downNeighbors ?? Array.Empty<int>());
            _adjacencyRules[t][3] = new HashSet<int>(tiles[t].leftNeighbors ?? Array.Empty<int>());
        }
    }

    bool Run()
    {
        int maxIterations = width * height * 10;
        for (int iter = 0; iter < maxIterations; iter++)
        {
            // 1. 找熵最小的格子
            var cell = FindMinEntropyCell();
            if (cell == null) return true; // 全部坍缩完成

            // 2. 坍缩
            if (!Collapse(cell.Value.x, cell.Value.y)) return false;

            // 3. 传播约束
            if (!Propagate(cell.Value.x, cell.Value.y)) return false;
        }
        return true;
    }

    /// <summary>
    /// 找到可能性最少（但未坍缩）的格子，加入噪声打破平局
    /// </summary>
    Vector2Int? FindMinEntropyCell()
    {
        int minEntropy = int.MaxValue;
        Vector2Int? result = null;

        for (int x = 0; x < width; x++)
        {
            for (int y = 0; y < height; y++)
            {
                int count = _wave[x, y].Count;
                if (count <= 1) continue; // 已坍缩或矛盾

                // 香农熵加噪声
                float entropy = Mathf.Log(count) + (float)(_rng.NextDouble() * 0.001);
                int entropyInt = (int)(entropy * 1000);
                if (entropyInt < minEntropy)
                {
                    minEntropy = entropyInt;
                    result = new Vector2Int(x, y);
                }
            }
        }
        return result;
    }

    bool Collapse(int x, int y)
    {
        var possible = _wave[x, y];
        if (possible.Count == 0) return false;

        // 按权重随机选择一个 tile
        float totalWeight = possible.Sum(t => tiles[t].weight);
        float pick = (float)(_rng.NextDouble() * totalWeight);
        float acc = 0;

        foreach (int tileId in possible)
        {
            acc += tiles[tileId].weight;
            if (acc >= pick)
            {
                _wave[x, y] = new HashSet<int> { tileId };
                return true;
            }
        }

        _wave[x, y] = new HashSet<int> { possible.First() };
        return true;
    }

    bool Propagate(int startX, int startY)
    {
        // BFS 传播约束
        var queue = new Queue<Vector2Int>();
        queue.Enqueue(new Vector2Int(startX, startY));
        var visited = new HashSet<Vector2Int>();

        while (queue.Count > 0)
        {
            var current = queue.Dequeue();
            if (!visited.Add(current)) continue;

            for (int dir = 0; dir < 4; dir++)
            {
                var neighbor = current + Directions[dir];
                if (neighbor.x < 0 || neighbor.x >= width || neighbor.y < 0 || neighbor.y >= height)
                    continue;

                // 计算当前格子在 dir 方向允许的邻居集合
                var allowedNeighbors = new HashSet<int>();
                foreach (int tileId in _wave[current.x, current.y])
                    allowedNeighbors.UnionWith(_adjacencyRules[tileId][dir]);

                // 从邻居的可能集合中移除不允许的
                int before = _wave[neighbor.x, neighbor.y].Count;
                _wave[neighbor.x, neighbor.y].IntersectWith(allowedNeighbors);
                int after = _wave[neighbor.x, neighbor.y].Count;

                if (after == 0)
                {
                    Debug.LogWarning($"[WFC] 矛盾发生在 ({neighbor.x}, {neighbor.y})");
                    return false;
                }

                if (after < before)
                    queue.Enqueue(neighbor);
            }
        }
        return true;
    }

    void Render()
    {
        // 清理已有物体
        foreach (Transform child in transform)
            Destroy(child.gameObject);

        for (int x = 0; x < width; x++)
        {
            for (int y = 0; y < height; y++)
            {
                if (_wave[x, y].Count != 1) continue;
                int tileId = _wave[x, y].First();
                var tile = tiles[tileId];
                if (tile.prefab != null)
                {
                    var go = Instantiate(tile.prefab, new Vector3(x, 0, y), Quaternion.identity, transform);
                    go.name = $"{tile.name}_{x}_{y}";
                }
            }
        }
    }
}
```

---

## 四、Perlin 噪声地形生成

### 4.1 多倍频叠加（分形噪声）

```csharp
using UnityEngine;

public class ProceduralTerrainGenerator : MonoBehaviour
{
    [Header("地形尺寸")]
    public int width = 256;
    public int height = 256;
    public float scale = 50f;

    [Header("分形参数")]
    public int octaves = 6;
    [Range(0, 1)] public float persistence = 0.5f;    // 振幅衰减
    public float lacunarity = 2.0f;                    // 频率增长

    public int seed = 42;
    public Vector2 offset;

    [Header("地形组件")]
    public Terrain terrain;

    [ContextMenu("Generate Terrain")]
    public void Generate()
    {
        var terrainData = terrain.terrainData;
        terrainData.heightmapResolution = width + 1;
        terrainData.size = new Vector3(width, 60, height);
        terrainData.SetHeights(0, 0, GenerateHeightMap());
    }

    float[,] GenerateHeightMap()
    {
        var heights = new float[height, width];
        var rng = new System.Random(seed);

        // 每个倍频的随机偏移
        var octaveOffsets = new Vector2[octaves];
        for (int i = 0; i < octaves; i++)
            octaveOffsets[i] = new Vector2(rng.Next(-100000, 100000) + offset.x,
                                            rng.Next(-100000, 100000) + offset.y);

        float maxNoiseHeight = float.MinValue;
        float minNoiseHeight = float.MaxValue;
        float halfWidth  = width / 2f;
        float halfHeight = height / 2f;

        for (int y = 0; y < height; y++)
        {
            for (int x = 0; x < width; x++)
            {
                float amplitude = 1f;
                float frequency = 1f;
                float noiseHeight = 0f;

                for (int o = 0; o < octaves; o++)
                {
                    float sampleX = (x - halfWidth + octaveOffsets[o].x) / scale * frequency;
                    float sampleY = (y - halfHeight + octaveOffsets[o].y) / scale * frequency;

                    // 使用 Unity 内置 Perlin Noise（范围 0-1，映射到 -1~1）
                    float perlinValue = Mathf.PerlinNoise(sampleX, sampleY) * 2 - 1;
                    noiseHeight += perlinValue * amplitude;

                    amplitude *= persistence;
                    frequency *= lacunarity;
                }

                if (noiseHeight > maxNoiseHeight) maxNoiseHeight = noiseHeight;
                if (noiseHeight < minNoiseHeight) minNoiseHeight = noiseHeight;

                heights[y, x] = noiseHeight;
            }
        }

        // 归一化到 0-1
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
                heights[y, x] = Mathf.InverseLerp(minNoiseHeight, maxNoiseHeight, heights[y, x]);

        return heights;
    }

    /// <summary>
    /// 生成高度图纹理（用于预览）
    /// </summary>
    public Texture2D GenerateHeightTexture()
    {
        var heights = GenerateHeightMap();
        var tex = new Texture2D(width, height);
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                float h = heights[y, x];
                tex.SetPixel(x, y, new Color(h, h, h));
            }
        tex.Apply();
        return tex;
    }
}
```

### 4.2 基于高度的地形分层着色

```csharp
using UnityEngine;

[CreateAssetMenu(menuName = "PCG/Terrain Color Scheme")]
public class TerrainColorScheme : ScriptableObject
{
    [Serializable]
    public struct BiomeLayer
    {
        public string name;
        public float height;  // 0-1 高度阈值
        public Color color;
        public Texture2D texture;
    }

    public BiomeLayer[] layers;

    public Color GetColorAtHeight(float normalizedHeight)
    {
        for (int i = layers.Length - 1; i >= 0; i--)
            if (normalizedHeight >= layers[i].height)
                return layers[i].color;
        return Color.black;
    }
}

public class TerrainColorizer : MonoBehaviour
{
    public ProceduralTerrainGenerator generator;
    public TerrainColorScheme colorScheme;
    public MeshRenderer previewRenderer;

    [ContextMenu("Colorize Terrain")]
    public void Colorize()
    {
        var tex = generator.GenerateHeightTexture();
        var colorTex = new Texture2D(tex.width, tex.height);

        for (int y = 0; y < tex.height; y++)
            for (int x = 0; x < tex.width; x++)
            {
                float h = tex.GetPixel(x, y).r;
                colorTex.SetPixel(x, y, colorScheme.GetColorAtHeight(h));
            }

        colorTex.Apply();
        if (previewRenderer != null)
            previewRenderer.sharedMaterial.mainTexture = colorTex;
    }
}
```

---

## 五、Delaunay 三角化与最小生成树道路

### 5.1 Bowyer-Watson 算法（Delaunay 三角剖分）

```csharp
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class DelaunayTriangulation
{
    public struct Triangle
    {
        public Vector2 a, b, c;

        public bool ContainsPoint(Vector2 p, float epsilon = 1e-6f)
        {
            // 检查点是否在外接圆内
            float ax = a.x - p.x, ay = a.y - p.y;
            float bx = b.x - p.x, by = b.y - p.y;
            float cx = c.x - p.x, cy = c.y - p.y;
            float det = ax * (by * (cx * cx + cy * cy) - cy * (bx * bx + by * by))
                      - ay * (bx * (cx * cx + cy * cy) - cx * (bx * bx + by * by))
                      + (ax * ax + ay * ay) * (bx * cy - by * cx);
            return det > epsilon;
        }

        public bool SharesEdge(Triangle other)
        {
            int shared = 0;
            Vector2[] edges = { a, b, c };
            Vector2[] otherEdges = { other.a, other.b, other.c };
            foreach (var v in edges)
                foreach (var ov in otherEdges)
                    if (Vector2.Distance(v, ov) < 0.001f) shared++;
            return shared >= 2;
        }
    }

    public static List<Triangle> Triangulate(List<Vector2> points)
    {
        // 超级三角形（包含所有点）
        float maxCoord = points.Max(p => Mathf.Max(Mathf.Abs(p.x), Mathf.Abs(p.y))) * 3;
        var super = new Triangle
        {
            a = new Vector2(-maxCoord * 3, -maxCoord),
            b = new Vector2(0,  maxCoord * 3),
            c = new Vector2(maxCoord * 3, -maxCoord)
        };

        var triangles = new List<Triangle> { super };

        foreach (var point in points)
        {
            // 找到外接圆包含该点的三角形
            var badTriangles = triangles.Where(t => t.ContainsPoint(point)).ToList();

            // 找到多边形边界（bad triangles 的非共享边）
            var polygon = new List<(Vector2, Vector2)>();
            foreach (var tri in badTriangles)
            {
                (Vector2, Vector2)[] edges = {
                    (tri.a, tri.b), (tri.b, tri.c), (tri.c, tri.a)
                };
                foreach (var edge in edges)
                {
                    bool shared = badTriangles.Any(other => other.SharesEdge(tri) &&
                        ((Vector2.Distance(other.a, edge.Item1) < 0.001f || Vector2.Distance(other.b, edge.Item1) < 0.001f || Vector2.Distance(other.c, edge.Item1) < 0.001f) &&
                         (Vector2.Distance(other.a, edge.Item2) < 0.001f || Vector2.Distance(other.b, edge.Item2) < 0.001f || Vector2.Distance(other.c, edge.Item2) < 0.001f)));
                    if (!shared) polygon.Add(edge);
                }
            }

            // 移除坏三角形
            foreach (var bad in badTriangles) triangles.Remove(bad);

            // 用多边形顶点和新点构建新三角形
            foreach (var (e1, e2) in polygon)
                triangles.Add(new Triangle { a = e1, b = e2, c = point });
        }

        // 移除包含超级三角形顶点的三角形
        triangles.RemoveAll(t =>
            Vector2.Distance(t.a, super.a) < 0.001f || Vector2.Distance(t.a, super.b) < 0.001f || Vector2.Distance(t.a, super.c) < 0.001f ||
            Vector2.Distance(t.b, super.a) < 0.001f || Vector2.Distance(t.b, super.b) < 0.001f || Vector2.Distance(t.b, super.c) < 0.001f ||
            Vector2.Distance(t.c, super.a) < 0.001f || Vector2.Distance(t.c, super.b) < 0.001f || Vector2.Distance(t.c, super.c) < 0.001f);

        return triangles;
    }
}
```

### 5.2 Prim 最小生成树 - 房间道路网络

```csharp
using System.Collections.Generic;
using UnityEngine;

public class RoomRoadNetwork : MonoBehaviour
{
    /// <summary>
    /// 使用 Prim 算法从房间中心点构建最小生成树（最短连通道路网络）
    /// </summary>
    public static List<(Vector2Int, Vector2Int)> BuildMST(List<RectInt> rooms)
    {
        if (rooms.Count <= 1) return new List<(Vector2Int, Vector2Int)>();

        var centers = rooms.ConvertAll(r => new Vector2Int(r.xMin + r.width / 2, r.yMin + r.height / 2));
        var inMST = new bool[centers.Count];
        var result = new List<(Vector2Int, Vector2Int)>();

        inMST[0] = true;
        int added = 1;

        while (added < centers.Count)
        {
            float minDist = float.MaxValue;
            int fromIdx = -1, toIdx = -1;

            for (int i = 0; i < centers.Count; i++)
            {
                if (!inMST[i]) continue;
                for (int j = 0; j < centers.Count; j++)
                {
                    if (inMST[j]) continue;
                    float dist = Vector2Int.Distance(centers[i], centers[j]);
                    if (dist < minDist)
                    {
                        minDist = dist;
                        fromIdx = i;
                        toIdx = j;
                    }
                }
            }

            if (toIdx >= 0)
            {
                result.Add((centers[fromIdx], centers[toIdx]));
                inMST[toIdx] = true;
                added++;
            }
            else break;
        }

        return result;
    }
}
```

---

## 六、种子管理与复现系统

```csharp
using System;
using UnityEngine;

/// <summary>
/// 全局种子管理器，支持分层级独立随机流
/// </summary>
public class SeedManager : MonoBehaviour
{
    public static SeedManager Instance { get; private set; }

    [Header("主种子")]
    public int masterSeed = 0;
    public bool useRandomMasterSeed = false;

    // 不同系统的独立随机流
    private System.Random _terrainRng;
    private System.Random _dungeonRng;
    private System.Random _itemRng;
    private System.Random _enemyRng;

    void Awake()
    {
        Instance = this;
        if (useRandomMasterSeed)
            masterSeed = Environment.TickCount;
        
        InitializeRngs();
    }

    void InitializeRngs()
    {
        // 用主种子派生各子系统种子（保证相同主种子永远生成相同世界）
        var masterRng = new System.Random(masterSeed);
        _terrainRng = new System.Random(masterRng.Next());
        _dungeonRng = new System.Random(masterRng.Next());
        _itemRng    = new System.Random(masterRng.Next());
        _enemyRng   = new System.Random(masterRng.Next());

        Debug.Log($"[SeedManager] 主种子: {masterSeed}");
    }

    public System.Random GetTerrainRng() => _terrainRng;
    public System.Random GetDungeonRng() => _dungeonRng;
    public System.Random GetItemRng()    => _itemRng;
    public System.Random GetEnemyRng()   => _enemyRng;

    /// <summary>
    /// 将种子编码为可分享的字符串（Base62）
    /// </summary>
    public string EncodeSeed()
    {
        const string chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
        long seed = (long)masterSeed + int.MaxValue;
        string result = "";
        while (seed > 0) { result = chars[(int)(seed % 62)] + result; seed /= 62; }
        return result.PadLeft(6, '0');
    }

    public void DecodeSeed(string encoded)
    {
        const string chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
        long seed = 0;
        foreach (char c in encoded) { seed = seed * 62 + chars.IndexOf(c); }
        masterSeed = (int)(seed - int.MaxValue);
        InitializeRngs();
    }
}
```

---

## 七、Editor 工具集成

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

[CustomEditor(typeof(BSPDungeonGenerator))]
public class BSPDungeonGeneratorEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();

        var gen = (BSPDungeonGenerator)target;

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("快捷操作", EditorStyles.boldLabel);

        using (new EditorGUILayout.HorizontalScope())
        {
            if (GUILayout.Button("🎲 随机种子生成", GUILayout.Height(30)))
            {
                gen.seed = UnityEngine.Random.Range(0, 99999);
                gen.Generate();
            }
            if (GUILayout.Button("🔄 当前种子重生", GUILayout.Height(30)))
                gen.Generate();
        }

        if (GUILayout.Button("📋 复制种子到剪贴板"))
            EditorGUIUtility.systemCopyBuffer = gen.seed.ToString();

        // 显示统计信息
        EditorGUILayout.Space();
        EditorGUILayout.HelpBox($"当前种子: {gen.seed}", MessageType.Info);
    }
}
#endif
```

---

## 八、最佳实践总结

### 算法选型指南

| 场景 | 推荐算法 | 理由 |
|------|---------|------|
| 2D Roguelike 地牢 | BSP + MST 走廊 | 房间密度可控，走廊必然连通 |
| 瓷砖地图图案 | WFC | 自然的局部连贯性 |
| 开放世界地形 | Perlin 噪声分形 | 无限扩展、性能好 |
| 城市/建筑布局 | Grammar/L-System | 规则清晰可读 |
| 关卡难度渐进 | 遗传算法 | 可量化评估函数 |

### 工程最佳实践

1. **种子优先**：所有随机操作必须使用可记录的种子，支持复现和分享
2. **分层生成**：地形→房间→道路→物品→敌人，每层独立可单独重生成
3. **约束驱动**：定义规则（不允许两房间重叠、出入口必须有路），生成后校验
4. **渐进式生成**：玩家移动时异步生成远处内容，避免卡顿（使用 Coroutine/UniTask）
5. **可玩性保障**：纯随机可能生成"死局"，需要后处理保证：至少一条通路、关键道具可达、难度曲线合理

### 性能注意事项

- WFC 大地图时使用 **分块生成** + **边界约束传播**
- BSP 生成为纯 CPU 操作，可在 **子线程（Task.Run）** 完成后 dispatch 到主线程渲染
- Perlin 噪声可以 **Burst Job 并行** 计算每个格子的高度值
- 地形网格建议使用 **无缝流式加载**，而非一次性生成整个世界

---

## 九、延伸阅读

- [WFC 原始论文 - Maxim Gumin](https://github.com/mxgmn/WaveFunctionCollapse)
- [Procedural Content Generation in Games（免费电子书）](http://pcgbook.com/)
- Unity ProBuilder + PCG 结合实践
- GDC "Dungeon Generation in Diablo" 经典演讲
