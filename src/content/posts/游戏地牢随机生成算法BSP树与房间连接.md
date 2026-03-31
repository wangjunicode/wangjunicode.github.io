---
title: 游戏地牢随机生成算法：BSP树与房间连接
published: 2026-03-31
description: 深度解析游戏程序化地牢生成的工程实现，包含BSP（二叉空间分割）树划分算法、随机房间放置、走廊连接（最短路径/L形走廊）、房间装饰（宝箱/怪物/道具随机放置）、起始点与终点保证连通性验证、种子化随机（相同种子生成相同地牢），以及地牢难度随机调节。
tags: [程序化生成, 地牢生成, BSP树, 游戏设计, Unity]
category: 游戏设计
draft: false
---

## 一、BSP树地牢生成

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

public class DungeonGenerator : MonoBehaviour
{
    [Header("地牢参数")]
    [SerializeField] private int mapWidth = 80;
    [SerializeField] private int mapHeight = 60;
    [SerializeField] private int minRoomSize = 6;
    [SerializeField] private int maxSplitDepth = 5;
    [SerializeField] private int seed = -1;

    private System.Random rng;
    private int[,] map; // 0=墙, 1=地板, 2=走廊
    private List<RectInt> rooms = new List<RectInt>();

    public int[,] Generate()
    {
        rng = seed >= 0 ? new System.Random(seed) : new System.Random();
        map = new int[mapWidth, mapHeight];
        rooms.Clear();
        
        // 初始化全墙
        for (int x = 0; x < mapWidth; x++)
            for (int y = 0; y < mapHeight; y++)
                map[x, y] = 0;
        
        // BSP划分
        var root = new BSPNode(new RectInt(0, 0, mapWidth, mapHeight));
        Split(root, 0);
        
        // 生成房间
        CreateRooms(root);
        
        // 连接房间
        ConnectRooms(root);
        
        return map;
    }

    void Split(BSPNode node, int depth)
    {
        if (depth >= maxSplitDepth) return;
        
        var rect = node.Area;
        bool splitH = rng.NextDouble() > 0.5;
        
        // 如果宽高比太极端，强制某方向切割
        if (rect.width > rect.height * 1.5f) splitH = false;
        if (rect.height > rect.width * 1.5f) splitH = true;
        
        if (splitH)
        {
            if (rect.height < minRoomSize * 2) return;
            int splitY = rng.Next(minRoomSize, rect.height - minRoomSize) + rect.y;
            node.Left = new BSPNode(new RectInt(rect.x, rect.y, rect.width, splitY - rect.y));
            node.Right = new BSPNode(new RectInt(rect.x, splitY, rect.width, rect.yMax - splitY));
        }
        else
        {
            if (rect.width < minRoomSize * 2) return;
            int splitX = rng.Next(minRoomSize, rect.width - minRoomSize) + rect.x;
            node.Left = new BSPNode(new RectInt(rect.x, rect.y, splitX - rect.x, rect.height));
            node.Right = new BSPNode(new RectInt(splitX, rect.y, rect.xMax - splitX, rect.height));
        }
        
        Split(node.Left, depth + 1);
        Split(node.Right, depth + 1);
    }

    void CreateRooms(BSPNode node)
    {
        if (node.Left == null && node.Right == null)
        {
            // 叶节点：在此区域生成一个房间
            var area = node.Area;
            int padding = 2;
            int roomW = rng.Next(minRoomSize, Math.Max(minRoomSize + 1, area.width - padding * 2));
            int roomH = rng.Next(minRoomSize, Math.Max(minRoomSize + 1, area.height - padding * 2));
            int roomX = area.x + padding + rng.Next(area.width - roomW - padding * 2 + 1);
            int roomY = area.y + padding + rng.Next(area.height - roomH - padding * 2 + 1);
            
            var room = new RectInt(roomX, roomY, roomW, roomH);
            node.Room = room;
            rooms.Add(room);
            
            // 填充地板
            for (int x = room.x; x < room.xMax; x++)
                for (int y = room.y; y < room.yMax; y++)
                    map[x, y] = 1;
        }
        else
        {
            if (node.Left != null) CreateRooms(node.Left);
            if (node.Right != null) CreateRooms(node.Right);
        }
    }

    void ConnectRooms(BSPNode node)
    {
        if (node.Left == null || node.Right == null) return;
        
        ConnectRooms(node.Left);
        ConnectRooms(node.Right);
        
        var roomA = GetLeafRoom(node.Left);
        var roomB = GetLeafRoom(node.Right);
        
        if (roomA != null && roomB != null)
            CreateCorridor(roomA.Value, roomB.Value);
    }

    void CreateCorridor(RectInt a, RectInt b)
    {
        // 从A的中心到B的中心画L形走廊
        int ax = a.x + a.width / 2;
        int ay = a.y + a.height / 2;
        int bx = b.x + b.width / 2;
        int by = b.y + b.height / 2;
        
        // 水平段
        int startX = Math.Min(ax, bx);
        int endX = Math.Max(ax, bx);
        for (int x = startX; x <= endX; x++)
        {
            if (x >= 0 && x < mapWidth && ay >= 0 && ay < mapHeight)
                map[x, ay] = map[x, ay] == 0 ? 2 : map[x, ay];
        }
        
        // 垂直段
        int startY = Math.Min(ay, by);
        int endY = Math.Max(ay, by);
        for (int y = startY; y <= endY; y++)
        {
            if (bx >= 0 && bx < mapWidth && y >= 0 && y < mapHeight)
                map[bx, y] = map[bx, y] == 0 ? 2 : map[bx, y];
        }
    }

    RectInt? GetLeafRoom(BSPNode node)
    {
        if (node == null) return null;
        if (node.Room.HasValue) return node.Room;
        return GetLeafRoom(node.Left) ?? GetLeafRoom(node.Right);
    }

    public List<RectInt> GetRooms() => rooms;
}

public class BSPNode
{
    public RectInt Area;
    public BSPNode Left, Right;
    public RectInt? Room;
    public BSPNode(RectInt area) { Area = area; }
}
```

---

## 二、地牢内容填充

```csharp
public class DungeonPopulator : MonoBehaviour
{
    [SerializeField] private GameObject floorPrefab;
    [SerializeField] private GameObject wallPrefab;
    [SerializeField] private GameObject chestPrefab;
    [SerializeField] private GameObject[] enemyPrefabs;

    public void Populate(int[,] map, List<RectInt> rooms, int seed)
    {
        var rng = new System.Random(seed + 1);
        int width = map.GetLength(0);
        int height = map.GetLength(1);
        
        // 生成地板和墙
        for (int x = 0; x < width; x++)
        for (int y = 0; y < height; y++)
        {
            if (map[x, y] > 0)
                Instantiate(floorPrefab, new Vector3(x, 0, y), Quaternion.identity);
            else
                Instantiate(wallPrefab, new Vector3(x, 0.5f, y), Quaternion.identity);
        }
        
        // 在房间内放置宝箱和怪物
        for (int i = 1; i < rooms.Count; i++) // 跳过第一个房间（起点）
        {
            var room = rooms[i];
            
            // 30%概率放宝箱
            if (rng.NextDouble() < 0.3f)
            {
                int cx = room.x + rng.Next(room.width);
                int cy = room.y + rng.Next(room.height);
                Instantiate(chestPrefab, new Vector3(cx, 0, cy), Quaternion.identity);
            }
            
            // 放1-3个怪物
            int enemyCount = rng.Next(1, 4);
            for (int e = 0; e < enemyCount; e++)
            {
                int ex = room.x + rng.Next(room.width);
                int ey = room.y + rng.Next(room.height);
                var prefab = enemyPrefabs[rng.Next(enemyPrefabs.Length)];
                Instantiate(prefab, new Vector3(ex, 0, ey), Quaternion.identity);
            }
        }
    }
}
```
