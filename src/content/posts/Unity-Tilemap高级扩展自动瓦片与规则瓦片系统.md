---
title: 游戏地图编辑器高级扩展：自动瓦片与规则瓦片系统
published: 2026-03-31
description: 深入解析 Unity Tilemap 高级特性与自定义规则瓦片（Rule Tile）系统，涵盖 AutoTile 邻接规则、自定义 Tile Palette 工具、动态 Tilemap 生成、瓦片动画、地形混合、以及适用于 2D RPG 地图编辑器的完整扩展方案。
tags: [Unity, Tilemap, Rule Tile, 地图编辑器, 2D游戏]
category: 工具链开发
draft: false
---

## 一、Rule Tile 系统概述

Rule Tile（规则瓦片）基于邻接关系自动选择合适的瓦片：

```
[上][左上][上右]    →   根据周围是否有相同类型的瓦片
[左][中心][右  ]    →   自动选择对应的图块（边角、边缘、内部）
[左下][下][右下]    →   大幅减少手动铺设工作量
```

**标准 AutoTile 图集（47 格）：** 覆盖所有可能的邻接组合

---

## 二、自定义 Rule Tile

```csharp
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Tilemaps;

#if UNITY_EDITOR
using UnityEditor;
#endif

/// <summary>
/// 自定义地形 Rule Tile（继承自 Unity 的 RuleTile）
/// </summary>
[CreateAssetMenu(menuName = "Tiles/TerrainRuleTile")]
public class TerrainRuleTile : RuleTile<TerrainRuleTile.Neighbor>
{
    public enum TerrainType
    {
        Grass, Water, Sand, Rock, Snow
    }

    [Header("地形配置")]
    public TerrainType terrainType;
    public Sprite[] randomVariants;  // 中心瓦片的随机变体（多样性）
    [Range(0, 1)] public float randomVariantChance = 0.1f;

    /// <summary>
    /// 邻居规则类型
    /// </summary>
    public class Neighbor : RuleTile.TilingRule.Neighbor
    {
        public const int SameType = 1;        // 同类型地形
        public const int DifferentType = 2;   // 不同类型地形
        public const int Empty = 3;           // 空瓦片
    }

    /// <summary>
    /// 核心：判断某个位置的瓦片是否满足规则
    /// </summary>
    public override bool RuleMatch(int neighbor, TileBase tile)
    {
        switch (neighbor)
        {
            case Neighbor.SameType:
                // 相邻位置是相同类型的地形
                return tile is TerrainRuleTile other && 
                    other.terrainType == this.terrainType;
            
            case Neighbor.DifferentType:
                // 相邻位置是不同类型的地形
                return !(tile is TerrainRuleTile sameType && 
                    sameType.terrainType == this.terrainType);
            
            case Neighbor.Empty:
                return tile == null;
            
            default:
                return base.RuleMatch(neighbor, tile);
        }
    }

    public override void GetTileData(Vector3Int position, ITilemap tilemap, 
        ref TileData tileData)
    {
        base.GetTileData(position, tilemap, ref tileData);
        
        // 在中心瓦片上随机使用变体精灵
        if (randomVariants != null && randomVariants.Length > 0 && 
            Random.value < randomVariantChance)
        {
            // 使用确定性随机（基于位置），防止每帧刷新
            Random.State oldState = Random.state;
            Random.InitState(position.x * 10000 + position.y);
            
            tileData.sprite = randomVariants[Random.Range(0, randomVariants.Length)];
            
            Random.state = oldState;
        }
    }
}
```

---

## 三、动态 Tilemap 生成

```csharp
/// <summary>
/// 运行时动态生成 Tilemap 内容
/// </summary>
public class DynamicTilemapBuilder : MonoBehaviour
{
    [Header("Tilemap 引用")]
    [SerializeField] private Tilemap groundLayer;
    [SerializeField] private Tilemap decorLayer;
    [SerializeField] private Tilemap collisionLayer;

    [Header("地形瓦片")]
    [SerializeField] private TileBase grassTile;
    [SerializeField] private TileBase waterTile;
    [SerializeField] private TileBase wallTile;
    [SerializeField] private TileBase[] decorTiles;

    [Header("生成参数")]
    [SerializeField] private int width = 50, height = 50;
    [SerializeField] private float noiseScale = 0.1f;
    [SerializeField] private float waterThreshold = 0.35f;
    [SerializeField] private float decorDensity = 0.05f;

    void Start()
    {
        GenerateMap(42);
    }

    public void GenerateMap(int seed)
    {
        // 清空已有内容
        groundLayer.ClearAllTiles();
        decorLayer.ClearAllTiles();
        collisionLayer.ClearAllTiles();

        float offsetX = seed * 1000f;
        float offsetY = seed * 1000f;

        // 预备批量设置（比逐个 SetTile 快得多）
        var groundPositions = new List<Vector3Int>();
        var groundTiles = new List<TileBase>();
        var collisionPositions = new List<Vector3Int>();
        var collisionTiles = new List<TileBase>();

        for (int y = 0; y < height; y++)
        for (int x = 0; x < width; x++)
        {
            float noise = Mathf.PerlinNoise(
                (x + offsetX) * noiseScale, 
                (y + offsetY) * noiseScale);

            var pos = new Vector3Int(x, y, 0);

            if (noise < waterThreshold)
            {
                groundPositions.Add(pos);
                groundTiles.Add(waterTile);
                // 水域作为碰撞层
                collisionPositions.Add(pos);
                collisionTiles.Add(wallTile);
            }
            else
            {
                groundPositions.Add(pos);
                groundTiles.Add(grassTile);
            }
        }

        // 批量设置（一次性调用，性能极优）
        groundLayer.SetTiles(groundPositions.ToArray(), groundTiles.ToArray());
        collisionLayer.SetTiles(collisionPositions.ToArray(), collisionTiles.ToArray());

        // 装饰层
        PlaceDecorations(seed);

        // 压缩 Tilemap 边界（优化）
        groundLayer.CompressBounds();
        collisionLayer.CompressBounds();
    }

    void PlaceDecorations(int seed)
    {
        if (decorTiles == null || decorTiles.Length == 0) return;
        
        var rng = new System.Random(seed);
        
        foreach (var pos in groundLayer.cellBounds.allPositionsWithin)
        {
            if (groundLayer.GetTile(pos) != grassTile) continue;
            if (rng.NextDouble() > decorDensity) continue;
            
            decorLayer.SetTile(pos, decorTiles[rng.Next(0, decorTiles.Length)]);
        }
    }

    /// <summary>
    /// 运行时修改单个瓦片（例如：挖矿、铺路）
    /// </summary>
    public void SetTileAt(Vector3Int worldPos, TileBase newTile, TilemapLayer layer)
    {
        var tilemap = layer switch
        {
            TilemapLayer.Ground => groundLayer,
            TilemapLayer.Decor => decorLayer,
            TilemapLayer.Collision => collisionLayer,
            _ => groundLayer
        };
        
        tilemap.SetTile(worldPos, newTile);
    }

    /// <summary>
    /// 世界坐标转瓦片坐标
    /// </summary>
    public Vector3Int WorldToCell(Vector3 worldPos) => 
        groundLayer.WorldToCell(worldPos);

    /// <summary>
    /// 检查某位置是否可通行
    /// </summary>
    public bool IsWalkable(Vector3 worldPos)
    {
        var cell = groundLayer.WorldToCell(worldPos);
        return collisionLayer.GetTile(cell) == null;
    }

    public enum TilemapLayer { Ground, Decor, Collision }
}
```

---

## 四、瓦片动画系统

```csharp
/// <summary>
/// 动态动画瓦片（水波纹、火焰等）
/// </summary>
[CreateAssetMenu(menuName = "Tiles/AnimatedTile")]
public class CustomAnimatedTile : TileBase
{
    [Header("动画帧")]
    public Sprite[] frames;
    public float fps = 6f;
    
    [Header("随机起始帧（瓦片多样性）")]
    public bool randomizeStartFrame = true;

    public override void GetTileData(Vector3Int position, ITilemap tilemap, 
        ref TileData tileData)
    {
        if (frames == null || frames.Length == 0) return;
        
        // 计算当前帧
        float time = Application.isPlaying ? Time.time : 0f;
        
        // 随机偏移（不同位置的水面不同步）
        float offset = randomizeStartFrame ? 
            (position.x * 3.7f + position.y * 7.3f) % 1f : 0f;
        
        int frameIndex = Mathf.FloorToInt((time * fps + offset * frames.Length)) % frames.Length;
        tileData.sprite = frames[frameIndex];
        tileData.flags = TileFlags.None;
        tileData.colliderType = Tile.ColliderType.None;
    }

    public override bool GetTileAnimationData(Vector3Int position, ITilemap tilemap, 
        ref TileAnimationData tileAnimationData)
    {
        if (frames == null || frames.Length == 0) return false;
        
        tileAnimationData.animatedSprites = frames;
        tileAnimationData.animationSpeed = fps;
        
        if (randomizeStartFrame)
        {
            // 随机起始时间（基于位置）
            tileAnimationData.animationStartTime = 
                (position.x * 3.7f + position.y * 7.3f) % (frames.Length / fps);
        }
        
        return true;
    }
}
```

---

## 五、Tilemap 性能优化

```csharp
/// <summary>
/// Tilemap 性能优化工具类
/// </summary>
public static class TilemapOptimizer
{
    /// <summary>
    /// 将多个 Tilemap 合并为静态网格（大幅提升渲染性能）
    /// </summary>
    public static void BakeStaticTilemap(Tilemap tilemap, MeshFilter meshFilter)
    {
        // 收集所有瓦片的顶点、UV、三角形
        var vertices = new List<Vector3>();
        var triangles = new List<int>();
        var uvs = new List<Vector2>();

        foreach (var pos in tilemap.cellBounds.allPositionsWithin)
        {
            if (!tilemap.HasTile(pos)) continue;
            
            var worldPos = tilemap.CellToWorld(pos);
            var sprite = tilemap.GetSprite(pos);
            if (sprite == null) continue;
            
            // 添加四边形顶点
            int baseIdx = vertices.Count;
            vertices.Add(worldPos + new Vector3(0, 0));
            vertices.Add(worldPos + new Vector3(1, 0));
            vertices.Add(worldPos + new Vector3(1, 1));
            vertices.Add(worldPos + new Vector3(0, 1));
            
            // 三角形
            triangles.Add(baseIdx);
            triangles.Add(baseIdx + 2);
            triangles.Add(baseIdx + 1);
            triangles.Add(baseIdx);
            triangles.Add(baseIdx + 3);
            triangles.Add(baseIdx + 2);
            
            // UV
            var rect = sprite.rect;
            var texSize = new Vector2(sprite.texture.width, sprite.texture.height);
            uvs.Add(new Vector2(rect.xMin, rect.yMin) / texSize);
            uvs.Add(new Vector2(rect.xMax, rect.yMin) / texSize);
            uvs.Add(new Vector2(rect.xMax, rect.yMax) / texSize);
            uvs.Add(new Vector2(rect.xMin, rect.yMax) / texSize);
        }

        var mesh = new Mesh
        {
            name = "BakedTilemap",
            vertices = vertices.ToArray(),
            triangles = triangles.ToArray(),
            uv = uvs.ToArray()
        };
        mesh.RecalculateNormals();
        mesh.UploadMeshData(true); // 上传后释放 CPU 内存
        
        meshFilter.mesh = mesh;
        
        Debug.Log($"[TilemapBake] Baked {vertices.Count / 4} tiles into single mesh");
    }
}
```

---

## 六、实践建议

| 场景 | 推荐方案 |
|------|----------|
| 手工制作关卡 | Rule Tile + Tile Palette |
| 程序化生成地图 | 批量 SetTiles + Perlin Noise |
| 大型静态场景 | 烘焙成静态网格 |
| 水面/火焰 | Animated Tile |
| 地形过渡 | 自定义 Rule Tile 邻接规则 |
| 碰撞检测 | 独立 Collision Tilemap + Composite Collider 2D |

**关键性能优化：**
1. 使用 `SetTiles(Vector3Int[], TileBase[])` 批量设置，而非循环 `SetTile`
2. 对静态区域使用 `CompressBounds()` 减少空白遍历
3. 大型场景将远处 Tilemap 对象禁用（基于摄像机距离）
4. 使用 Composite Collider 2D 合并碰撞体，减少物理碰撞体数量
