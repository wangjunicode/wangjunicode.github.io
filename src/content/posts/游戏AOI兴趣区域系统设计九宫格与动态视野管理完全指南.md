---
title: 游戏AOI兴趣区域系统设计：九宫格、灯塔算法与动态视野管理完全指南
published: 2026-04-12
description: 深度解析游戏AOI（Area of Interest）系统的设计与实现，涵盖九宫格算法、灯塔系统、十字链表法、动态视野管理、大规模MMO场景优化等核心技术，附完整C#代码实现。
tags: [AOI, 游戏服务器, 场景管理, 网络同步, MMO, 性能优化]
category: 游戏开发
draft: false
---

# 游戏AOI兴趣区域系统设计：九宫格、灯塔算法与动态视野管理完全指南

## 1. AOI系统概述

**AOI（Area of Interest，兴趣区域）** 系统是多人在线游戏中用于管理"哪些玩家需要感知到哪些实体"的核心技术。在大型MMO、MOBA、Battle Royale等游戏中，一个场景可能存在数千个玩家和NPC，如果让所有实体相互感知，网络带宽和CPU将被瞬间耗尽。

### 1.1 AOI系统的核心价值

```
┌─────────────────────────────────────────────────────────────┐
│                     AOI系统的作用                            │
│                                                             │
│  [玩家A]                                                    │
│     │                                                       │
│     └─ AOI系统 ──→ 只广播/接收视野范围内的实体状态           │
│                                                             │
│  无AOI：N个玩家 = O(N²) 消息广播                            │
│  有AOI：N个玩家 = O(N×K) 消息广播（K为平均视野内玩家数）     │
│                                                             │
│  当N=1000，K=50时：                                         │
│  无AOI：1,000,000 条消息/tick                               │
│  有AOI：50,000 条消息/tick  ← 性能提升20倍                  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 AOI系统的主要算法对比

| 算法 | 时间复杂度 | 空间复杂度 | 适用场景 | 优劣势 |
|------|-----------|-----------|---------|--------|
| 暴力遍历 | O(N²) | O(1) | 极小场景 | 简单但低效 |
| 九宫格 | O(K) | O(N) | 均匀分布场景 | 实现简单，效果好 |
| 灯塔系统 | O(K×log K) | O(N+M) | 大世界 | 视野灵活，适合不规则形状 |
| 十字链表 | O(K) | O(N) | 矩形视野 | 高效但实现复杂 |
| 四叉树 | O(log N) | O(N) | 稀疏场景 | 动态场景性能好 |

---

## 2. 九宫格AOI系统

### 2.1 原理

将地图划分为均等大小的格子，每个实体根据坐标归属到某个格子。当查询某个位置的视野范围时，只需检查以该格子为中心的9个格子（3×3）。

```
┌───┬───┬───┬───┬───┐
│   │   │   │   │   │
├───┼───┼───┼───┼───┤
│   │ ■ │ ■ │ ■ │   │
├───┼───┼───┼───┼───┤
│   │ ■ │ ★ │ ■ │   │  ★ = 玩家当前格子
├───┼───┼───┼───┼───┤       ■ = 视野格子
│   │ ■ │ ■ │ ■ │   │
├───┼───┼───┼───┼───┤
│   │   │   │   │   │
└───┴───┴───┴───┴───┘
```

### 2.2 完整实现

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 九宫格AOI管理器
/// 适用于均匀分布的大型多人场景
/// </summary>
public class AoiGrid
{
    // 格子边长（世界单位）
    private readonly float _cellSize;
    // 格子集合：Key=格子坐标, Value=该格子内的实体集合
    private readonly Dictionary<(int, int), HashSet<AoiEntity>> _cells;
    // 实体→格子的快速映射
    private readonly Dictionary<int, (int, int)> _entityCell;
    // 视野回调
    public event Action<AoiEntity, AoiEntity> OnEntityEnterView;
    public event Action<AoiEntity, AoiEntity> OnEntityLeaveView;

    public AoiGrid(float cellSize = 100f)
    {
        _cellSize = cellSize;
        _cells = new Dictionary<(int, int), HashSet<AoiEntity>>();
        _entityCell = new Dictionary<int, (int, int)>();
    }

    /// <summary>
    /// 将世界坐标转换为格子坐标
    /// </summary>
    private (int, int) WorldToCell(Vector2 pos)
    {
        int cx = Mathf.FloorToInt(pos.x / _cellSize);
        int cy = Mathf.FloorToInt(pos.y / _cellSize);
        return (cx, cy);
    }

    /// <summary>
    /// 获取格子，不存在则创建
    /// </summary>
    private HashSet<AoiEntity> GetOrCreateCell(int cx, int cy)
    {
        var key = (cx, cy);
        if (!_cells.TryGetValue(key, out var set))
        {
            set = new HashSet<AoiEntity>();
            _cells[key] = set;
        }
        return set;
    }

    /// <summary>
    /// 获取某个格子周围9宫格内的所有实体
    /// </summary>
    public List<AoiEntity> GetNearbyEntities(int cx, int cy, int range = 1)
    {
        var result = new List<AoiEntity>();
        for (int dx = -range; dx <= range; dx++)
        {
            for (int dy = -range; dy <= range; dy++)
            {
                if (_cells.TryGetValue((cx + dx, cy + dy), out var cell))
                {
                    result.AddRange(cell);
                }
            }
        }
        return result;
    }

    /// <summary>
    /// 实体进入场景
    /// </summary>
    public void Enter(AoiEntity entity)
    {
        var cell = WorldToCell(entity.Position);
        var (cx, cy) = cell;

        // 加入格子
        GetOrCreateCell(cx, cy).Add(entity);
        _entityCell[entity.EntityId] = cell;

        // 通知附近实体：有新人进入视野
        var nearby = GetNearbyEntities(cx, cy, entity.ViewRange);
        foreach (var other in nearby)
        {
            if (other.EntityId == entity.EntityId) continue;
            // 双向通知
            OnEntityEnterView?.Invoke(entity, other);
            OnEntityEnterView?.Invoke(other, entity);
        }
    }

    /// <summary>
    /// 实体离开场景
    /// </summary>
    public void Leave(AoiEntity entity)
    {
        if (!_entityCell.TryGetValue(entity.EntityId, out var cell)) return;
        var (cx, cy) = cell;

        // 通知附近实体：有人离开视野
        var nearby = GetNearbyEntities(cx, cy, entity.ViewRange);
        foreach (var other in nearby)
        {
            if (other.EntityId == entity.EntityId) continue;
            OnEntityLeaveView?.Invoke(entity, other);
            OnEntityLeaveView?.Invoke(other, entity);
        }

        // 从格子移除
        if (_cells.TryGetValue(cell, out var cellSet))
        {
            cellSet.Remove(entity);
            if (cellSet.Count == 0) _cells.Remove(cell);
        }
        _entityCell.Remove(entity.EntityId);
    }

    /// <summary>
    /// 实体移动（核心逻辑）
    /// </summary>
    public void Move(AoiEntity entity, Vector2 newPosition)
    {
        if (!_entityCell.TryGetValue(entity.EntityId, out var oldCell)) return;
        var newCell = WorldToCell(newPosition);

        entity.Position = newPosition;

        // 如果格子没变，直接返回
        if (oldCell == newCell) return;

        var (oldCx, oldCy) = oldCell;
        var (newCx, newCy) = newCell;
        int range = entity.ViewRange;

        // 计算旧视野格子集合
        var oldCells = GetCellsInRange(oldCx, oldCy, range);
        // 计算新视野格子集合
        var newCells = GetCellsInRange(newCx, newCy, range);

        // 进入新视野的格子
        var enterCells = new HashSet<(int, int)>(newCells);
        enterCells.ExceptWith(oldCells);

        // 离开旧视野的格子
        var leaveCells = new HashSet<(int, int)>(oldCells);
        leaveCells.ExceptWith(newCells);

        // 处理新进入视野的实体
        foreach (var cellKey in enterCells)
        {
            if (_cells.TryGetValue(cellKey, out var cellEntities))
            {
                foreach (var other in cellEntities)
                {
                    if (other.EntityId == entity.EntityId) continue;
                    OnEntityEnterView?.Invoke(entity, other);
                    OnEntityEnterView?.Invoke(other, entity);
                }
            }
        }

        // 处理离开视野的实体
        foreach (var cellKey in leaveCells)
        {
            if (_cells.TryGetValue(cellKey, out var cellEntities))
            {
                foreach (var other in cellEntities)
                {
                    if (other.EntityId == entity.EntityId) continue;
                    OnEntityLeaveView?.Invoke(entity, other);
                    OnEntityLeaveView?.Invoke(other, entity);
                }
            }
        }

        // 更新格子归属
        if (_cells.TryGetValue(oldCell, out var oldCellSet))
        {
            oldCellSet.Remove(entity);
            if (oldCellSet.Count == 0) _cells.Remove(oldCell);
        }
        GetOrCreateCell(newCx, newCy).Add(entity);
        _entityCell[entity.EntityId] = newCell;
    }

    private HashSet<(int, int)> GetCellsInRange(int cx, int cy, int range)
    {
        var result = new HashSet<(int, int)>();
        for (int dx = -range; dx <= range; dx++)
            for (int dy = -range; dy <= range; dy++)
                result.Add((cx + dx, cy + dy));
        return result;
    }

    /// <summary>
    /// 获取实体视野内的所有实体（用于进入场景时的全量同步）
    /// </summary>
    public List<AoiEntity> GetViewEntities(AoiEntity entity)
    {
        if (!_entityCell.TryGetValue(entity.EntityId, out var cell)) return new List<AoiEntity>();
        var (cx, cy) = cell;
        var result = GetNearbyEntities(cx, cy, entity.ViewRange);
        result.RemoveAll(e => e.EntityId == entity.EntityId);
        return result;
    }
}

/// <summary>
/// AOI实体基类
/// </summary>
public class AoiEntity
{
    public int EntityId { get; set; }
    public Vector2 Position { get; set; }
    /// <summary>
    /// 视野范围（格子数）
    /// </summary>
    public int ViewRange { get; set; } = 1;
    public EntityType Type { get; set; }
}

public enum EntityType { Player, Monster, NPC, Item }
```

---

## 3. 灯塔（Tower）AOI系统

灯塔系统将地图划分为若干"灯塔区域"，每个灯塔管理一定范围内的实体。实体订阅视野范围内的灯塔，当灯塔内有实体变化时广播给所有订阅者。

### 3.1 灯塔系统架构

```
           订阅            订阅
 [玩家A] ──────→ [灯塔1] ←────── [玩家B]
           订阅            广播↓
 [玩家A] ──────→ [灯塔2]
                    ↓ 广播
              [玩家A, 玩家B收到通知]

灯塔覆盖范围通常 = 玩家视野的1/3~1/4
确保视野内至少覆盖9个灯塔区域
```

### 3.2 灯塔系统实现

```csharp
/// <summary>
/// 灯塔AOI系统
/// 相比九宫格，灯塔系统支持不同大小的视野范围，更灵活
/// </summary>
public class TowerAoiSystem
{
    private readonly float _towerSize;   // 灯塔区域大小
    private readonly Dictionary<(int, int), Tower> _towers;
    private readonly Dictionary<int, TowerPlayer> _players;

    public TowerAoiSystem(float towerSize = 50f)
    {
        _towerSize = towerSize;
        _towers = new Dictionary<(int, int), Tower>();
        _players = new Dictionary<int, TowerPlayer>();
    }

    private (int, int) GetTowerKey(Vector2 pos)
    {
        return (Mathf.FloorToInt(pos.x / _towerSize),
                Mathf.FloorToInt(pos.y / _towerSize));
    }

    private Tower GetOrCreateTower(int tx, int ty)
    {
        var key = (tx, ty);
        if (!_towers.TryGetValue(key, out var tower))
        {
            tower = new Tower(tx, ty);
            _towers[key] = tower;
        }
        return tower;
    }

    /// <summary>
    /// 获取视野范围内的所有灯塔
    /// </summary>
    private List<Tower> GetSubscribeTowers(Vector2 pos, float viewRadius)
    {
        var towers = new List<Tower>();
        int minTx = Mathf.FloorToInt((pos.x - viewRadius) / _towerSize);
        int maxTx = Mathf.FloorToInt((pos.x + viewRadius) / _towerSize);
        int minTy = Mathf.FloorToInt((pos.y - viewRadius) / _towerSize);
        int maxTy = Mathf.FloorToInt((pos.y + viewRadius) / _towerSize);

        for (int tx = minTx; tx <= maxTx; tx++)
        {
            for (int ty = minTy; ty <= maxTy; ty++)
            {
                towers.Add(GetOrCreateTower(tx, ty));
            }
        }
        return towers;
    }

    public void PlayerEnter(int playerId, Vector2 pos, float viewRadius)
    {
        var player = new TowerPlayer
        {
            PlayerId = playerId,
            Position = pos,
            ViewRadius = viewRadius
        };
        _players[playerId] = player;

        // 订阅视野内的灯塔
        var towersToSubscribe = GetSubscribeTowers(pos, viewRadius);
        foreach (var tower in towersToSubscribe)
        {
            tower.Subscribe(player);
            player.SubscribedTowers.Add(tower);
        }

        // 站到当前灯塔格子中
        var currentTower = GetOrCreateTower(GetTowerKey(pos).Item1, GetTowerKey(pos).Item2);
        currentTower.Enter(player);
        player.CurrentTower = currentTower;
    }

    public void PlayerMove(int playerId, Vector2 newPos)
    {
        if (!_players.TryGetValue(playerId, out var player)) return;
        var oldPos = player.Position;
        player.Position = newPos;

        // 检查是否跨越灯塔
        var newTowerKey = GetTowerKey(newPos);
        var oldTowerKey = GetTowerKey(oldPos);

        if (newTowerKey != oldTowerKey)
        {
            // 离开旧灯塔
            player.CurrentTower.Leave(player);
            // 进入新灯塔
            var newTower = GetOrCreateTower(newTowerKey.Item1, newTowerKey.Item2);
            newTower.Enter(player);
            player.CurrentTower = newTower;
        }

        // 更新订阅的灯塔列表（视野内灯塔可能变化）
        var newTowers = new HashSet<Tower>(GetSubscribeTowers(newPos, player.ViewRadius));
        var oldTowers = new HashSet<Tower>(player.SubscribedTowers);

        // 取消不再需要的订阅
        foreach (var tower in oldTowers)
        {
            if (!newTowers.Contains(tower))
            {
                tower.Unsubscribe(player);
                player.SubscribedTowers.Remove(tower);
                // 通知玩家该灯塔内的实体离开视野
                tower.NotifyLeave(player);
            }
        }

        // 新增订阅
        foreach (var tower in newTowers)
        {
            if (!oldTowers.Contains(tower))
            {
                tower.Subscribe(player);
                player.SubscribedTowers.Add(tower);
                // 通知玩家该灯塔内的实体进入视野
                tower.NotifyEnter(player);
            }
        }

        // 广播玩家移动给订阅了当前灯塔的其他玩家
        player.CurrentTower.BroadcastMove(player, newPos);
    }

    public void PlayerLeave(int playerId)
    {
        if (!_players.TryGetValue(playerId, out var player)) return;

        player.CurrentTower.Leave(player);
        foreach (var tower in player.SubscribedTowers)
        {
            tower.Unsubscribe(player);
            tower.NotifyLeave(player);
        }
        player.SubscribedTowers.Clear();
        _players.Remove(playerId);
    }
}

/// <summary>
/// 灯塔：管理一个区域内的实体，以及订阅该区域的观察者
/// </summary>
public class Tower
{
    public int Tx { get; }
    public int Ty { get; }

    // 灯塔内的实体（站在这个区域中的实体）
    private readonly HashSet<TowerPlayer> _entities = new HashSet<TowerPlayer>();
    // 订阅该灯塔的玩家（视野覆盖到该区域的玩家）
    private readonly HashSet<TowerPlayer> _subscribers = new HashSet<TowerPlayer>();

    public Tower(int tx, int ty)
    {
        Tx = tx;
        Ty = ty;
    }

    public void Subscribe(TowerPlayer player) => _subscribers.Add(player);
    public void Unsubscribe(TowerPlayer player) => _subscribers.Remove(player);

    public void Enter(TowerPlayer player)
    {
        _entities.Add(player);
        // 通知所有订阅者：有新实体进入
        foreach (var subscriber in _subscribers)
        {
            if (subscriber.PlayerId != player.PlayerId)
                subscriber.OnEntityEnterView?.Invoke(player);
        }
    }

    public void Leave(TowerPlayer player)
    {
        _entities.Remove(player);
        // 通知所有订阅者：实体离开
        foreach (var subscriber in _subscribers)
        {
            if (subscriber.PlayerId != player.PlayerId)
                subscriber.OnEntityLeaveView?.Invoke(player);
        }
    }

    public void NotifyEnter(TowerPlayer newSubscriber)
    {
        // 告知新订阅者，该灯塔内已有哪些实体
        foreach (var entity in _entities)
        {
            if (entity.PlayerId != newSubscriber.PlayerId)
                newSubscriber.OnEntityEnterView?.Invoke(entity);
        }
    }

    public void NotifyLeave(TowerPlayer oldSubscriber)
    {
        // 告知取消订阅者，该灯塔内的实体离开视野
        foreach (var entity in _entities)
        {
            if (entity.PlayerId != oldSubscriber.PlayerId)
                oldSubscriber.OnEntityLeaveView?.Invoke(entity);
        }
    }

    public void BroadcastMove(TowerPlayer mover, Vector2 newPos)
    {
        foreach (var subscriber in _subscribers)
        {
            if (subscriber.PlayerId != mover.PlayerId)
                subscriber.OnEntityMove?.Invoke(mover, newPos);
        }
    }
}

public class TowerPlayer
{
    public int PlayerId { get; set; }
    public Vector2 Position { get; set; }
    public float ViewRadius { get; set; }
    public Tower CurrentTower { get; set; }
    public HashSet<Tower> SubscribedTowers { get; } = new HashSet<Tower>();

    // 视野回调
    public Action<TowerPlayer> OnEntityEnterView;
    public Action<TowerPlayer> OnEntityLeaveView;
    public Action<TowerPlayer, Vector2> OnEntityMove;
}
```

---

## 4. 十字链表AOI算法

十字链表是性能最高的AOI实现之一，被大量服务端引擎采用（如 Skynet）。

### 4.1 原理

将所有实体按X轴和Y轴坐标分别维护两个有序链表。查询视野范围时，只需在链表中进行范围扫描：

```
X轴链表: ... → [x=-50] → [x=0] → [x=30] → [x=80] → ...
                                      ↑
                                   玩家A(x=30)
                         ←── 视野半径100 ──→
                         扫描 x∈[-70, 130]
```

### 4.2 十字链表实现

```csharp
/// <summary>
/// 十字链表AOI（Cross Linked List AOI）
/// 时间复杂度：O(K + log N) K为视野内实体数
/// 最适合矩形视野的AOI查询
/// </summary>
public class CrossLinkAoi
{
    // X轴有序链表（双向）
    private AoiNode _xHead, _xTail;
    // Y轴有序链表（双向）
    private AoiNode _yHead, _yTail;

    private readonly Dictionary<int, AoiNode> _nodes = new Dictionary<int, AoiNode>();

    public CrossLinkAoi()
    {
        // 哨兵节点
        _xHead = new AoiNode(-1) { X = float.MinValue };
        _xTail = new AoiNode(-1) { X = float.MaxValue };
        _xHead.XNext = _xTail;
        _xTail.XPrev = _xHead;

        _yHead = new AoiNode(-1) { Y = float.MinValue };
        _yTail = new AoiNode(-1) { Y = float.MaxValue };
        _yHead.YNext = _yTail;
        _yTail.YPrev = _yHead;
    }

    public void Add(int entityId, float x, float y)
    {
        var node = new AoiNode(entityId) { X = x, Y = y };
        _nodes[entityId] = node;

        // 插入X轴链表（保持有序）
        InsertX(node);
        // 插入Y轴链表（保持有序）
        InsertY(node);
    }

    private void InsertX(AoiNode node)
    {
        var cur = _xTail.XPrev;
        while (cur != _xHead && cur.X > node.X) cur = cur.XPrev;
        // 插入到 cur 之后
        node.XPrev = cur;
        node.XNext = cur.XNext;
        cur.XNext.XPrev = node;
        cur.XNext = node;
    }

    private void InsertY(AoiNode node)
    {
        var cur = _yTail.YPrev;
        while (cur != _yHead && cur.Y > node.Y) cur = cur.YPrev;
        node.YPrev = cur;
        node.YNext = cur.YNext;
        cur.YNext.YPrev = node;
        cur.YNext = node;
    }

    public void Remove(int entityId)
    {
        if (!_nodes.TryGetValue(entityId, out var node)) return;

        // 从X链表移除
        node.XPrev.XNext = node.XNext;
        node.XNext.XPrev = node.XPrev;
        // 从Y链表移除
        node.YPrev.YNext = node.YNext;
        node.YNext.YPrev = node.YPrev;

        _nodes.Remove(entityId);
    }

    /// <summary>
    /// 查询矩形区域内的实体（核心接口）
    /// </summary>
    public List<int> Query(float centerX, float centerY, float halfWidth, float halfHeight)
    {
        // 先从X轴筛选候选集
        var candidates = new HashSet<int>();
        var node = _xHead.XNext;
        while (node != _xTail && node.X <= centerX + halfWidth)
        {
            if (node.X >= centerX - halfWidth && node.EntityId != -1)
                candidates.Add(node.EntityId);
            node = node.XNext;
        }

        // 再从Y轴过滤候选集
        var result = new List<int>();
        node = _yHead.YNext;
        while (node != _yTail && node.Y <= centerY + halfHeight)
        {
            if (node.Y >= centerY - halfHeight && node.EntityId != -1
                && candidates.Contains(node.EntityId))
                result.Add(node.EntityId);
            node = node.YNext;
        }

        return result;
    }

    /// <summary>
    /// 更新实体位置
    /// </summary>
    public void Update(int entityId, float newX, float newY)
    {
        if (!_nodes.TryGetValue(entityId, out var node)) return;

        // 更新X坐标并调整链表
        node.X = newX;
        FixPositionX(node);

        // 更新Y坐标并调整链表
        node.Y = newY;
        FixPositionY(node);
    }

    private void FixPositionX(AoiNode node)
    {
        // 向右移动
        while (node.XNext != _xTail && node.X > node.XNext.X)
        {
            var next = node.XNext;
            // 交换 node 和 next
            node.XPrev.XNext = next;
            next.XPrev = node.XPrev;
            node.XNext = next.XNext;
            next.XNext.XPrev = node;
            next.XNext = node;
            node.XPrev = next;
        }
        // 向左移动
        while (node.XPrev != _xHead && node.X < node.XPrev.X)
        {
            var prev = node.XPrev;
            prev.XNext = node.XNext;
            node.XNext.XPrev = prev;
            node.XPrev = prev.XPrev;
            prev.XPrev.XNext = node;
            prev.XPrev = node;
            node.XNext = prev;
        }
    }

    private void FixPositionY(AoiNode node)
    {
        while (node.YNext != _yTail && node.Y > node.YNext.Y)
        {
            var next = node.YNext;
            node.YPrev.YNext = next;
            next.YPrev = node.YPrev;
            node.YNext = next.YNext;
            next.YNext.YPrev = node;
            next.YNext = node;
            node.YPrev = next;
        }
        while (node.YPrev != _yHead && node.Y < node.YPrev.Y)
        {
            var prev = node.YPrev;
            prev.YNext = node.YNext;
            node.YNext.YPrev = prev;
            node.YPrev = prev.YPrev;
            prev.YPrev.YNext = node;
            prev.YPrev = node;
            node.YNext = prev;
        }
    }
}

public class AoiNode
{
    public int EntityId { get; }
    public float X, Y;
    public AoiNode XPrev, XNext;
    public AoiNode YPrev, YNext;

    public AoiNode(int entityId) { EntityId = entityId; }
}
```

---

## 5. 动态视野与优先级管理

### 5.1 基于距离的优先级更新

```csharp
/// <summary>
/// 带优先级的AOI管理器
/// 近处实体高频同步，远处实体低频同步
/// </summary>
public class PriorityAoiManager
{
    private const float HIGH_PRIORITY_DIST = 30f;   // 高优先级距离
    private const float MEDIUM_PRIORITY_DIST = 80f; // 中优先级距离
    private const int HIGH_PRIORITY_TICK = 1;       // 每帧同步
    private const int MEDIUM_PRIORITY_TICK = 3;     // 每3帧同步
    private const int LOW_PRIORITY_TICK = 10;       // 每10帧同步

    private readonly AoiGrid _aoiGrid;
    private int _currentTick;

    public PriorityAoiManager(AoiGrid aoiGrid)
    {
        _aoiGrid = aoiGrid;
    }

    public void Tick()
    {
        _currentTick++;
    }

    public bool ShouldSync(AoiEntity observer, AoiEntity target)
    {
        float dist = Vector2.Distance(observer.Position, target.Position);

        if (dist <= HIGH_PRIORITY_DIST)
            return _currentTick % HIGH_PRIORITY_TICK == 0;
        if (dist <= MEDIUM_PRIORITY_DIST)
            return _currentTick % MEDIUM_PRIORITY_TICK == 0;
        return _currentTick % LOW_PRIORITY_TICK == 0;
    }

    /// <summary>
    /// 获取需要同步的实体列表（按优先级过滤）
    /// </summary>
    public List<(AoiEntity entity, SyncPriority priority)> GetSyncList(
        AoiEntity observer, List<AoiEntity> viewEntities)
    {
        var result = new List<(AoiEntity, SyncPriority)>();
        foreach (var entity in viewEntities)
        {
            float dist = Vector2.Distance(observer.Position, entity.Position);
            SyncPriority priority;

            if (dist <= HIGH_PRIORITY_DIST) priority = SyncPriority.High;
            else if (dist <= MEDIUM_PRIORITY_DIST) priority = SyncPriority.Medium;
            else priority = SyncPriority.Low;

            if (ShouldSync(observer, entity))
                result.Add((entity, priority));
        }
        return result;
    }
}

public enum SyncPriority { High, Medium, Low }
```

### 5.2 视野遮挡剔除（与战场迷雾结合）

```csharp
/// <summary>
/// 结合视野遮挡的AOI过滤器
/// 用于RPG/战略游戏中的"战争迷雾"场景
/// </summary>
public class FogOfWarAoiFilter
{
    private readonly float[] _fogMap;     // 视野地图（每格的可见性）
    private readonly int _mapWidth;
    private readonly float _cellSize;

    public FogOfWarAoiFilter(int mapWidth, int mapHeight, float cellSize)
    {
        _mapWidth = mapWidth;
        _cellSize = cellSize;
        _fogMap = new float[mapWidth * mapHeight];
    }

    public bool IsVisible(Vector2 observerPos, Vector2 targetPos)
    {
        int tx = Mathf.FloorToInt(targetPos.x / _cellSize);
        int ty = Mathf.FloorToInt(targetPos.y / _cellSize);
        int idx = ty * _mapWidth + tx;
        if (idx < 0 || idx >= _fogMap.Length) return false;
        return _fogMap[idx] > 0.5f;
    }

    public List<AoiEntity> FilterVisible(AoiEntity observer, List<AoiEntity> candidates)
    {
        var result = new List<AoiEntity>(candidates.Count);
        foreach (var entity in candidates)
        {
            if (IsVisible(observer.Position, entity.Position))
                result.Add(entity);
        }
        return result;
    }
}
```

---

## 6. 性能对比测试

```csharp
[System.Diagnostics.Conditional("UNITY_EDITOR")]
public static class AoiBenchmark
{
    public static void Run()
    {
        const int ENTITY_COUNT = 5000;
        const int ITERATIONS = 1000;

        // 初始化实体
        var entities = new AoiEntity[ENTITY_COUNT];
        var rnd = new System.Random(42);
        for (int i = 0; i < ENTITY_COUNT; i++)
        {
            entities[i] = new AoiEntity
            {
                EntityId = i,
                Position = new Vector2(rnd.Next(0, 1000), rnd.Next(0, 1000)),
                ViewRange = 1
            };
        }

        // 测试九宫格
        var grid = new AoiGrid(100f);
        var sw = System.Diagnostics.Stopwatch.StartNew();

        foreach (var e in entities) grid.Enter(e);
        for (int i = 0; i < ITERATIONS; i++)
        {
            var e = entities[rnd.Next(ENTITY_COUNT)];
            grid.Move(e, new Vector2(
                e.Position.x + rnd.Next(-10, 10),
                e.Position.y + rnd.Next(-10, 10)
            ));
        }
        sw.Stop();
        Debug.Log($"九宫格AOI: {ENTITY_COUNT}实体 {ITERATIONS}次移动 耗时: {sw.ElapsedMilliseconds}ms");

        // 测试十字链表
        var crossLink = new CrossLinkAoi();
        sw.Restart();

        foreach (var e in entities) crossLink.Add(e.EntityId, e.Position.x, e.Position.y);
        for (int i = 0; i < ITERATIONS; i++)
        {
            var e = entities[rnd.Next(ENTITY_COUNT)];
            crossLink.Update(e.EntityId,
                e.Position.x + rnd.Next(-10, 10),
                e.Position.y + rnd.Next(-10, 10));
        }
        sw.Stop();
        Debug.Log($"十字链表AOI: {ENTITY_COUNT}实体 {ITERATIONS}次移动 耗时: {sw.ElapsedMilliseconds}ms");
    }
}
```

---

## 7. 工程化最佳实践

### 7.1 AOI系统选型指南

```
游戏类型判断树：
                        ┌─ 视野固定/方形？
                        │    ├─ 是 → 十字链表（最高效）
    ┌─ 大型MMO/开放世界─┤
    │                   │    └─ 否 → 九宫格（简单可靠）
    │
场景类型─┤
    │
    ├─ MOBA/竞技场 ──── 九宫格（小地图，均匀分布）
    │
    └─ 战略游戏/战争迷雾 → 九宫格 + 视野遮挡过滤
```

### 7.2 关键参数调优

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 格子大小 | 视野半径的1/2 ~ 2/3 | 太小格子数太多，太大效率差 |
| 视野范围 | 1~2格（九宫格） | 对应实际视野50~150米 |
| 灯塔大小 | 视野半径的1/4 | 确保视野内有9+个灯塔 |
| 同步频率 | 高优先10-20Hz | 低优先1-5Hz |
| 最大同步实体 | 50~100/人 | 超出则按优先级裁剪 |

### 7.3 常见陷阱与解决方案

```csharp
// ❌ 错误：频繁跨格子移动导致大量AOI事件
// 发生场景：玩家站在格子边界反复横跳
// 解决：添加迟滞阈值
public class HysteresisAoiMover
{
    private const float HYSTERESIS = 2f; // 迟滞距离（格子大小的2%）
    
    public bool ShouldUpdateCell(Vector2 oldPos, Vector2 newPos, float cellSize)
    {
        // 只有移动超过迟滞阈值才触发格子更新
        return Mathf.Abs(newPos.x - oldPos.x) > HYSTERESIS ||
               Mathf.Abs(newPos.y - oldPos.y) > HYSTERESIS;
    }
}

// ✅ 正确：批量处理AOI事件，避免每帧触发回调
public class BatchedAoiProcessor
{
    private readonly Queue<AoiEvent> _pendingEvents = new Queue<AoiEvent>();
    
    public void AddEvent(AoiEvent evt) => _pendingEvents.Enqueue(evt);
    
    public void ProcessBatch(int maxBatchSize = 100)
    {
        int processed = 0;
        while (_pendingEvents.Count > 0 && processed < maxBatchSize)
        {
            var evt = _pendingEvents.Dequeue();
            ProcessEvent(evt);
            processed++;
        }
    }
    
    private void ProcessEvent(AoiEvent evt) { /* ... */ }
}

public struct AoiEvent
{
    public AoiEventType Type;
    public int ObserverId;
    public int TargetId;
}

public enum AoiEventType { Enter, Leave, Move }
```

---

## 8. 总结

| 维度 | 九宫格 | 灯塔系统 | 十字链表 |
|------|--------|----------|---------|
| 实现难度 | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| 移动性能 | O(K) | O(K) | O(K+log N) |
| 视野灵活性 | 中 | 高 | 低（矩形）|
| 内存占用 | 中 | 高 | 低 |
| 适用规模 | 中大型 | 超大型 | 大型 |

**选型建议**：
- 中小型游戏（<500实体/场景）：九宫格 + 优先级同步
- 大型MMO（>2000实体/场景）：灯塔系统 + 动态视野
- 服务端专用高性能场景：十字链表

AOI系统是网络游戏服务端的基础设施，理解其原理并根据游戏特点选择合适算法，是构建高性能多人游戏的关键第一步。
