---
title: Unity网络同步预测回滚与延迟补偿机制深度实践
published: 2026-10-11
description: 深入剖析多人游戏网络同步中的客户端预测、服务器回滚与延迟补偿三大核心机制，结合Unity ECS与C#实现完整的状态同步框架
tags: [Unity, 网络同步, 预测回滚, 延迟补偿, ECS, 多人游戏]
category: 网络同步
draft: false
---

## 引言

在多人实时对战游戏中，网络延迟是影响玩家体验的核心痛点。当玩家按下移动键到服务器确认位置之间存在网络往返延迟（RTT），如果采用"等待服务器确认再更新"的朴素方案，玩家会感受到明显的操作延迟。为了解决这个问题，现代游戏网络同步方案通常采用三大核心技术：

1. **客户端预测（Client-Side Prediction）**：客户端立即执行操作，不等待服务器确认
2. **服务器回滚（Server Reconciliation / Rollback）**：服务器收到客户端指令后，回滚到正确状态并重新模拟
3. **延迟补偿（Lag Compensation）**：服务器在处理命中检测时，将玩家"回退"到过去的位置

本文将深入剖析这三项技术的原理，并基于Unity C#提供完整的工程化实现。

## 一、核心问题：为什么需要预测回滚？

### 1.1 网络延迟的困境

假设玩家A按下W键向前移动，传统同步流程如下：

```
客户端发送移动指令 → [网络传输] → 服务器接收 → 服务器计算新位置 → [网络传输] → 客户端更新
```

如果RTT为100ms，玩家从按下按键到看到角色移动，需要等待至少100ms。对于FPS或格斗游戏，这种延迟是毁灭性的。

### 1.2 三种同步架构对比

| 架构 | 延迟体验 | 防作弊 | 实现复杂度 | 适用场景 |
|------|---------|--------|-----------|---------|
|  authoritative server + 无预测 | 差（等待RTT） | 强 | 低 | 回合制、慢速游戏 |
| authoritative server + 客户端预测 | 好（零延迟） | 强 | 中 | FPS、动作游戏 |
| P2P + 帧同步 | 好 | 弱 | 高 | 格斗游戏 |

本文聚焦于**authoritative server + 客户端预测**架构，这是当前商业游戏最广泛采用的方案。

## 二、客户端预测（Client-Side Prediction）

### 2.1 基本原理

客户端预测的核心思想是：**客户端假设服务器会接受自己的操作，立即在本地执行并展示结果**。当服务器返回权威状态时，客户端再与本地状态进行校正。

```
时间轴：
T0: 客户端发送Move指令，同时本地执行 → 玩家看到角色移动
T0+RTT/2: 服务器收到指令，更新权威状态
T0+RTT: 客户端收到服务器确认，校正本地状态
```

### 2.2 预测状态管理

我们需要维护三个关键状态：

```csharp
/// <summary>
/// 客户端预测状态管理器
/// </summary>
public class PredictionStateManager
{
    // 服务器最新确认的状态（权威状态）
    public ServerState LastConfirmedState { get; private set; }
    
    // 客户端当前预测状态（本地展示用）
    public PlayerState CurrentPredictedState { get; private set; }
    
    // 未确认的输入历史（用于重预测）
    public readonly List<InputSnapshot> PendingInputs = new();
    
    // 状态历史快照（用于回滚）
    public readonly List<StateSnapshot> StateHistory = new();
    
    private const int MaxHistoryFrames = 120; // 最多保留2秒历史（60FPS）
    
    /// <summary>
    /// 应用客户端输入，立即预测
    /// </summary>
    public void ApplyInput(InputSnapshot input, float deltaTime)
    {
        // 1. 记录当前状态快照
        RecordStateSnapshot(CurrentPredictedState, Time.frameCount);
        
        // 2. 将输入加入待确认队列
        PendingInputs.Add(input);
        
        // 3. 在本地模拟该输入
        CurrentPredictedState = SimulateMovement(CurrentPredictedState, input, deltaTime);
    }
    
    /// <summary>
    /// 收到服务器权威状态后校正
    /// </summary>
    public void OnServerStateReceived(ServerState serverState)
    {
        // 1. 更新最后确认的权威状态
        LastConfirmedState = serverState;
        
        // 2. 移除已被服务器确认的输入
        int confirmedCount = 0;
        foreach (var input in PendingInputs)
        {
            if (input.InputId <= serverState.LastProcessedInputId)
                confirmedCount++;
            else
                break;
        }
        PendingInputs.RemoveRange(0, confirmedCount);
        
        // 3. 从服务器状态开始重新预测
        CurrentPredictedState = PlayerState.FromServerState(serverState);
        foreach (var pendingInput in PendingInputs)
        {
            CurrentPredictedState = SimulateMovement(
                CurrentPredictedState, 
                pendingInput, 
                pendingInput.DeltaTime
            );
        }
        
        // 4. 清理过期的状态历史
        TrimStateHistory();
    }
    
    private void RecordStateSnapshot(PlayerState state, int frame)
    {
        StateHistory.Add(new StateSnapshot
        {
            Frame = frame,
            Position = state.Position,
            Rotation = state.Rotation,
            Velocity = state.Velocity
        });
        
        if (StateHistory.Count > MaxHistoryFrames)
            StateHistory.RemoveAt(0);
    }
    
    private void TrimStateHistory()
    {
        while (StateHistory.Count > 0 && 
               StateHistory[0].Frame < LastConfirmedState.Frame)
        {
            StateHistory.RemoveAt(0);
        }
    }
}
```

### 2.3 输入快照与序列化

每个输入都需要携带唯一ID，以便服务器确认：

```csharp
/// <summary>
/// 输入快照——客户端发送给服务器的每个操作
/// </summary>
public struct InputSnapshot
{
    public uint InputId;            // 递增的输入ID
    public float Timestamp;         // 客户端时间戳
    public float DeltaTime;         // 本帧模拟的deltaTime
    public Vector2 MoveDirection;   // 移动方向
    public bool JumpPressed;        // 跳跃
    public bool AttackPressed;      // 攻击
    public Vector2 LookDirection;   // 视角方向
    
    /// <summary>
    /// 序列化为字节数组（用于网络传输）
    /// </summary>
    public byte[] Serialize()
    {
        var writer = new BinaryWriter(new MemoryStream());
        writer.Write(InputId);
        writer.Write(Timestamp);
        writer.Write(DeltaTime);
        writer.Write(MoveDirection.x);
        writer.Write(MoveDirection.y);
        writer.Write(JumpPressed);
        writer.Write(AttackPressed);
        writer.Write(LookDirection.x);
        writer.Write(LookDirection.y);
        return ((MemoryStream)writer.BaseStream).ToArray();
    }
    
    public static InputSnapshot Deserialize(byte[] data)
    {
        var reader = new BinaryReader(new MemoryStream(data));
        return new InputSnapshot
        {
            InputId = reader.ReadUInt32(),
            Timestamp = reader.ReadSingle(),
            DeltaTime = reader.ReadSingle(),
            MoveDirection = new Vector2(reader.ReadSingle(), reader.ReadSingle()),
            JumpPressed = reader.ReadBoolean(),
            AttackPressed = reader.ReadBoolean(),
            LookDirection = new Vector2(reader.ReadSingle(), reader.ReadSingle())
        };
    }
}
```

### 2.4 状态快照结构

```csharp
/// <summary>
/// 状态快照——用于回滚和插值
/// </summary>
public struct StateSnapshot
{
    public int Frame;
    public Vector3 Position;
    public Quaternion Rotation;
    public Vector3 Velocity;
    public bool IsGrounded;
    public float Health;
}

/// <summary>
/// 玩家状态——客户端预测和服务器权威的通用表示
/// </summary>
public class PlayerState
{
    public Vector3 Position;
    public Quaternion Rotation;
    public Vector3 Velocity;
    public bool IsGrounded;
    public float Health;
    public uint LastProcessedInputId;
    
    public static PlayerState FromServerState(ServerState serverState)
    {
        return new PlayerState
        {
            Position = serverState.Position,
            Rotation = serverState.Rotation,
            Velocity = serverState.Velocity,
            IsGrounded = serverState.IsGrounded,
            Health = serverState.Health,
            LastProcessedInputId = serverState.LastProcessedInputId
        };
    }
}

/// <summary>
/// 服务器权威状态
/// </summary>
public struct ServerState
{
    public int Frame;
    public Vector3 Position;
    public Quaternion Rotation;
    public Vector3 Velocity;
    public bool IsGrounded;
    public float Health;
    public uint LastProcessedInputId;
}
```

## 三、服务器回滚（Server Reconciliation / Rollback）

### 3.1 为什么需要回滚？

客户端预测假设服务器会接受所有输入，但现实中有多种情况会导致预测错误：

- **服务器拒绝输入**（如移动速度异常、穿墙检测）
- **物理模拟差异**（浮点精度、帧率波动）
- **状态冲突**（两个玩家同时拾取同一物品）

当服务器发现状态不一致时，会发送权威状态给客户端，客户端需要**从权威状态重新模拟所有未确认的输入**。

### 3.2 回滚与重预测算法

```csharp
/// <summary>
/// 客户端预测校正器——处理服务器回滚
/// </summary>
public class PredictionCorrector
{
    private readonly PredictionStateManager _stateManager;
    
    /// <summary>
    /// 处理服务器返回的权威状态
    /// </summary>
    public void ReconcileWithServer(ServerState serverState)
    {
        // 1. 检查是否需要校正
        float deviation = Vector3.Distance(
            _stateManager.CurrentPredictedState.Position, 
            serverState.Position
        );
        
        // 如果偏差小于阈值，微调即可
        if (deviation < 0.01f)
        {
            ApplySoftCorrection(serverState);
            return;
        }
        
        // 如果偏差较大，执行完整回滚重预测
        if (deviation > 0.5f)
        {
            PerformHardRollback(serverState);
            return;
        }
        
        // 中等偏差：混合校正
        PerformBlendedCorrection(serverState, deviation);
    }
    
    /// <summary>
    /// 软校正——平滑过渡到服务器状态
    /// </summary>
    private void ApplySoftCorrection(ServerState serverState)
    {
        var current = _stateManager.CurrentPredictedState;
        float lerpFactor = Time.deltaTime * 5f; // 快速插值
        
        current.Position = Vector3.Lerp(
            current.Position, 
            serverState.Position, 
            lerpFactor
        );
        current.Velocity = serverState.Velocity;
    }
    
    /// <summary>
    /// 硬回滚——完全重置并从服务器状态重预测
    /// </summary>
    private void PerformHardRollback(ServerState serverState)
    {
        // 从服务器权威状态开始
        var baseState = PlayerState.FromServerState(serverState);
        
        // 重新模拟所有未确认的输入
        var pendingInputs = _stateManager.PendingInputs;
        for (int i = 0; i < pendingInputs.Count; i++)
        {
            baseState = SimulateMovement(baseState, pendingInputs[i], pendingInputs[i].DeltaTime);
        }
        
        _stateManager.CurrentPredictedState = baseState;
    }
    
    /// <summary>
    /// 混合校正——部分回滚+部分保留预测
    /// </summary>
    private void PerformBlendedCorrection(ServerState serverState, float deviation)
    {
        // 回滚到服务器状态
        var baseState = PlayerState.FromServerState(serverState);
        
        // 只重预测最近的输入（保留部分预测结果）
        int recentCount = Mathf.Min(3, _stateManager.PendingInputs.Count);
        int startIndex = _stateManager.PendingInputs.Count - recentCount;
        
        for (int i = startIndex; i < _stateManager.PendingInputs.Count; i++)
        {
            baseState = SimulateMovement(
                baseState, 
                _stateManager.PendingInputs[i], 
                _stateManager.PendingInputs[i].DeltaTime
            );
        }
        
        // 与当前预测状态混合
        float blendWeight = Mathf.Clamp01(1f - deviation / 2f);
        _stateManager.CurrentPredictedState.Position = Vector3.Lerp(
            baseState.Position,
            _stateManager.CurrentPredictedState.Position,
            blendWeight
        );
        _stateManager.CurrentPredictedState.Velocity = baseState.Velocity;
    }
    
    private PlayerState SimulateMovement(PlayerState state, InputSnapshot input, float deltaTime)
    {
        // 物理模拟逻辑（与服务器完全一致）
        var result = new PlayerState
        {
            Position = state.Position + new Vector3(
                input.MoveDirection.x * 5f * deltaTime,
                0,
                input.MoveDirection.y * 5f * deltaTime
            ),
            Rotation = state.Rotation,
            Velocity = new Vector3(
                input.MoveDirection.x * 5f,
                0,
                input.MoveDirection.y * 5f
            ),
            LastProcessedInputId = input.InputId
        };
        
        // 跳跃处理
        if (input.JumpPressed && state.IsGrounded)
        {
            result.Velocity.y = 8f;
            result.IsGrounded = false;
        }
        
        // 重力模拟
        if (!result.IsGrounded)
        {
            result.Velocity.y -= 9.8f * deltaTime;
            result.Position.y += result.Velocity.y * deltaTime;
            
            if (result.Position.y <= 0f)
            {
                result.Position.y = 0f;
                result.Velocity.y = 0f;
                result.IsGrounded = true;
            }
        }
        
        return result;
    }
}
```

### 3.3 服务器端权威模拟

```csharp
/// <summary>
/// 服务器端玩家模拟器（权威）
/// </summary>
public class ServerPlayerSimulator
{
    private readonly Dictionary<uint, PlayerState> _playerStates = new();
    private readonly Dictionary<uint, Queue<InputSnapshot>> _inputQueues = new();
    
    private const float MaxMoveSpeed = 6f;      // 速度上限（防作弊）
    private const float MaxAcceleration = 20f;   // 加速度上限
    private const float PositionErrorThreshold = 2f; // 位置偏差阈值
    
    /// <summary>
    /// 服务器每帧更新——处理所有玩家的输入
    /// </summary>
    public void Tick(float deltaTime)
    {
        foreach (var kvp in _inputQueues)
        {
            uint playerId = kvp.Key;
            var inputQueue = kvp.Value;
            
            while (inputQueue.Count > 0)
            {
                var input = inputQueue.Dequeue();
                ProcessInput(playerId, input, deltaTime);
            }
        }
    }
    
    /// <summary>
    /// 处理单个玩家输入（含防作弊检测）
    /// </summary>
    private void ProcessInput(uint playerId, InputSnapshot input, float deltaTime)
    {
        var state = _playerStates[playerId];
        
        // === 防作弊检测 ===
        
        // 1. 速度检测
        float inputSpeed = input.MoveDirection.magnitude * 5f;
        if (inputSpeed > MaxMoveSpeed)
        {
            // 速度异常，拒绝输入
            Debug.LogWarning($"Player {playerId} speed anomaly: {inputSpeed}");
            return;
        }
        
        // 2. 位置突变检测
        Vector3 expectedPosition = SimulateExpectedPosition(state, input, deltaTime);
        float positionDelta = Vector3.Distance(expectedPosition, state.Position);
        if (positionDelta > PositionErrorThreshold)
        {
            // 位置跳变异常
            Debug.LogWarning($"Player {playerId} position jump: {positionDelta}");
            return;
        }
        
        // === 权威模拟 ===
        state.Position = expectedPosition;
        state.LastProcessedInputId = input.InputId;
        state.Velocity = new Vector3(
            input.MoveDirection.x * 5f,
            state.Velocity.y,
            input.MoveDirection.y * 5f
        );
        
        // 跳跃等逻辑...
    }
    
    private Vector3 SimulateExpectedPosition(PlayerState state, InputSnapshot input, float deltaTime)
    {
        return state.Position + new Vector3(
            input.MoveDirection.x * 5f * deltaTime,
            0,
            input.MoveDirection.y * 5f * deltaTime
        );
    }
    
    /// <summary>
    /// 构建服务器权威状态包（发送给客户端）
    /// </summary>
    public ServerState BuildServerState(uint playerId)
    {
        var state = _playerStates[playerId];
        return new ServerState
        {
            Frame = Time.frameCount,
            Position = state.Position,
            Rotation = state.Rotation,
            Velocity = state.Velocity,
            IsGrounded = state.IsGrounded,
            Health = state.Health,
            LastProcessedInputId = state.LastProcessedInputId
        };
    }
}
```

## 四、延迟补偿（Lag Compensation）

### 4.1 问题描述

在FPS游戏中，当玩家A开枪射击玩家B时，由于网络延迟，服务器看到的玩家B位置可能已经和玩家A看到的不同。如果服务器直接用"当前"位置做命中检测，会导致玩家A明明瞄准了却打不中的糟糕体验。

### 4.2 延迟补偿原理

延迟补偿的核心思想是：**服务器在处理命中检测时，将受击玩家回滚到射击发生时的时间点**。

```
玩家A视角：瞄准B在T0时刻的位置 → 开枪（T0）
服务器视角：收到射击指令在T1时刻 → 将B回滚到T0位置 → 做命中检测
```

### 4.3 完整实现

```csharp
/// <summary>
/// 延迟补偿系统
/// </summary>
public class LagCompensationSystem
{
    // 存储所有玩家的位置历史（环形缓冲区）
    private readonly Dictionary<uint, CircularBuffer<PositionRecord>> _positionHistory = new();
    
    private const int HistoryDurationMs = 500;  // 保留500ms历史
    private const int HistorySampleRate = 3;    // 每3帧采样一次
    
    /// <summary>
    /// 位置记录
    /// </summary>
    public struct PositionRecord
    {
        public float Timestamp;      // 服务器时间戳（秒）
        public Vector3 Position;
        public Quaternion Rotation;
        public ColliderSnapshot[] ColliderData; // 碰撞体快照
    }
    
    /// <summary>
    /// 碰撞体快照（用于精确回滚检测）
    /// </summary>
    public struct ColliderSnapshot
    {
        public Vector3 Center;
        public Vector3 Extents;
        public Quaternion Rotation;
        public ColliderType Type;
    }
    
    public enum ColliderType { Box, Sphere, Capsule }
    
    /// <summary>
    /// 每帧记录所有玩家的位置
    /// </summary>
    public void RecordFrame(Dictionary<uint, PlayerState> allPlayers, float serverTime)
    {
        if (Time.frameCount % HistorySampleRate != 0)
            return;
            
        foreach (var kvp in allPlayers)
        {
            uint playerId = kvp.Key;
            var state = kvp.Value;
            
            if (!_positionHistory.ContainsKey(playerId))
                _positionHistory[playerId] = new CircularBuffer<PositionRecord>(200);
            
            var history = _positionHistory[playerId];
            
            // 记录位置快照
            history.Add(new PositionRecord
            {
                Timestamp = serverTime,
                Position = state.Position,
                Rotation = state.Rotation,
                ColliderData = CaptureColliderSnapshot(state)
            });
            
            // 清理过期记录
            CleanupExpiredRecords(history, serverTime);
        }
    }
    
    /// <summary>
    /// 执行延迟补偿命中检测
    /// </summary>
    public bool PerformLagCompensatedHitTest(
        uint shooterId,
        uint targetId,
        float shotTimestamp,        // 开枪时的客户端时间戳
        float serverTimeAtShot,     // 服务器对应时间
        Ray shotRay,
        out HitResult hitResult)
    {
        hitResult = default;
        
        // 1. 获取目标在射击时刻的位置历史
        if (!_positionHistory.TryGetValue(targetId, out var history))
            return false;
            
        // 2. 找到射击时刻对应的位置记录
        var record = FindPositionAtTime(history, serverTimeAtShot);
        if (record == null)
            return false;
        
        // 3. 临时回滚目标到射击时刻的位置
        var originalPosition = GetCurrentPosition(targetId);
        TemporarilyMoveTo(targetId, record.Value.Position, record.Value.Rotation);
        
        // 4. 在回滚后的位置做碰撞检测
        bool hit = PerformRaycast(targetId, shotRay, out hitResult);
        
        // 5. 恢复目标到当前位置
        RestorePosition(targetId, originalPosition);
        
        return hit;
    }
    
    /// <summary>
    /// 在时间线上找到最接近的位置记录
    /// </summary>
    private PositionRecord? FindPositionAtTime(
        CircularBuffer<PositionRecord> history, 
        float targetTime)
    {
        if (history.Count == 0)
            return null;
        
        // 二分查找最接近的时间点
        int low = 0;
        int high = history.Count - 1;
        
        while (low <= high)
        {
            int mid = (low + high) / 2;
            float diff = history[mid].Timestamp - targetTime;
            
            if (Mathf.Abs(diff) < 0.005f) // 5ms精度
                return history[mid];
            
            if (diff < 0)
                low = mid + 1;
            else
                high = mid - 1;
        }
        
        // 返回最接近的记录
        int closestIndex = Mathf.Clamp(low, 0, history.Count - 1);
        return history[closestIndex];
    }
    
    /// <summary>
    /// 插值获取精确位置（比二分查找更精确）
    /// </summary>
    public Vector3 InterpolatePositionAtTime(
        uint playerId, 
        float targetTime)
    {
        if (!_positionHistory.TryGetValue(playerId, out var history))
            return Vector3.zero;
        
        // 找到targetTime前后的两个记录
        PositionRecord? before = null;
        PositionRecord? after = null;
        
        for (int i = 0; i < history.Count - 1; i++)
        {
            if (history[i].Timestamp <= targetTime && 
                history[i + 1].Timestamp >= targetTime)
            {
                before = history[i];
                after = history[i + 1];
                break;
            }
        }
        
        if (before == null || after == null)
            return FindPositionAtTime(history, targetTime)?.Position ?? Vector3.zero;
        
        // 线性插值
        float t = (targetTime - before.Value.Timestamp) / 
                  (after.Value.Timestamp - before.Value.Timestamp);
        
        return Vector3.Lerp(before.Value.Position, after.Value.Position, t);
    }
    
    private void CleanupExpiredRecords(
        CircularBuffer<PositionRecord> history, 
        float currentTime)
    {
        while (history.Count > 0 && 
               (currentTime - history[0].Timestamp) * 1000f > HistoryDurationMs)
        {
            history.RemoveFirst();
        }
    }
}
```

### 4.4 命中检测与伤害判定流程

```csharp
/// <summary>
/// 完整的射击命中处理流程（服务器端）
/// </summary>
public class ShootingHandler
{
    private readonly LagCompensationSystem _lagComp;
    private readonly ServerPlayerSimulator _simulator;
    
    /// <summary>
    /// 处理玩家射击请求
    /// </summary>
    public void HandleShoot(uint shooterId, ShootRequest request, float serverTime)
    {
        // 1. 计算射击时刻的服务器时间
        //    客户端时间戳 - 客户端RTT/2 ≈ 服务器时间
        float shotServerTime = serverTime - (request.ClientTimestamp - serverTime);
        
        // 2. 对每个潜在目标执行延迟补偿检测
        foreach (var targetId in GetPotentialTargets(shooterId))
        {
            var shotRay = new Ray(request.Origin, request.Direction);
            
            if (_lagComp.PerformLagCompensatedHitTest(
                    shooterId, 
                    targetId, 
                    request.ClientTimestamp,
                    shotServerTime,
                    shotRay,
                    out var hitResult))
            {
                // 3. 计算伤害
                float damage = CalculateDamage(request.WeaponType, hitResult.Distance);
                
                // 4. 应用伤害（在权威状态上）
                ApplyDamage(targetId, damage, shooterId);
                
                // 5. 广播命中事件
                BroadcastHitEvent(shooterId, targetId, hitResult, damage);
            }
        }
    }
    
    private void ApplyDamage(uint targetId, float damage, uint attackerId)
    {
        // 在服务器权威状态上应用伤害
        // 同时触发伤害数字、击退效果等
    }
}
```

## 五、插值与渲染平滑

### 5.1 状态插值

对于非本地玩家（其他玩家），我们不需要预测，而是使用插值来平滑显示他们的位置：

```csharp
/// <summary>
/// 其他玩家状态插值器
/// </summary>
public class InterpolatedTransform
{
    private readonly Queue<StateSnapshot> _stateBuffer = new();
    private float _interpolationDelay = 0.1f; // 100ms插值延迟
    
    public Vector3 CurrentPosition { get; private set; }
    public Quaternion CurrentRotation { get; private set; }
    
    /// <summary>
    /// 每帧更新插值位置
    /// </summary>
    public void Update(float clientTime)
    {
        // 目标渲染时间 = 当前时间 - 插值延迟
        float renderTime = clientTime - _interpolationDelay;
        
        // 移除过旧的状态
        while (_stateBuffer.Count >= 2 && 
               _stateBuffer.Peek().Timestamp < renderTime)
        {
            _stateBuffer.Dequeue();
        }
        
        if (_stateBuffer.Count < 2)
            return;
        
        // 获取前后两个状态进行插值
        var prev = _stateBuffer.Peek();
        var next = _stateBuffer.Skip(1).First();
        
        float t = (renderTime - prev.Timestamp) / 
                  (next.Timestamp - prev.Timestamp);
        t = Mathf.Clamp01(t);
        
        CurrentPosition = Vector3.Lerp(prev.Position, next.Position, t);
        CurrentRotation = Quaternion.Slerp(prev.Rotation, next.Rotation, t);
    }
    
    /// <summary>
    /// 添加新的状态快照
    /// </summary>
    public void AddState(StateSnapshot snapshot)
    {
        _stateBuffer.Enqueue(snapshot);
        
        // 限制缓冲区大小
        while (_stateBuffer.Count > 30)
            _stateBuffer.Dequeue();
    }
}
```

### 5.2 外推（Extrapolation）

当网络丢包导致状态更新中断时，可以使用外推来预测其他玩家的位置：

```csharp
/// <summary>
/// 位置外推器——处理丢包情况
/// </summary>
public class ExtrapolationPredictor
{
    private StateSnapshot _lastKnownState;
    private float _timeSinceLastUpdate;
    private const float MaxExtrapolationTime = 0.5f; // 最多外推500ms
    
    /// <summary>
    /// 获取外推位置
    /// </summary>
    public Vector3 GetExtrapolatedPosition(float deltaTime)
    {
        _timeSinceLastUpdate += deltaTime;
        
        if (_timeSinceLastUpdate > MaxExtrapolationTime)
        {
            // 超过外推上限，停止移动
            return _lastKnownState.Position;
        }
        
        // 根据最后已知速度外推
        return _lastKnownState.Position + 
               _lastKnownState.Velocity * _timeSinceLastUpdate;
    }
    
    /// <summary>
    /// 收到新状态时重置
    /// </summary>
    public void OnNewStateReceived(StateSnapshot newState)
    {
        _lastKnownState = newState;
        _timeSinceLastUpdate = 0f;
    }
}
```

## 六、工程化最佳实践

### 6.1 网络同步架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     客户端 (Client)                       │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │ 输入收集  │ → │ 预测状态管理器 │ → │ 渲染/表现层      │  │
│  └──────────┘   └──────┬───────┘   └──────────────────┘  │
│                        │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │              网络层 (Network Layer)                   │  │
│  │  发送: InputSnapshot + 时间戳                        │  │
│  │  接收: ServerState (权威状态 + LastProcessedInputId) │  │
│  └──────────────────────┬──────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────┘
                          │
                    网络传输 (UDP / KCP / WebSocket)
                          │
┌─────────────────────────┼────────────────────────────────┐
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │              网络层 (Network Layer)                   │  │
│  │  接收: InputSnapshot                                │  │
│  │  发送: ServerState                                  │  │
│  └──────────────────────┬──────────────────────────────┘  │
│                        │                                  │
│  ┌──────────┐   ┌──────▼───────────┐   ┌──────────────┐  │
│  │ 输入队列  │ → │ 权威模拟器       │ → │ 状态广播器    │  │
│  └──────────┘   └──────────────────┘   └──────────────┘  │
│                        │                                  │
│  ┌──────────────────────▼──────────────────────────────┐  │
│  │          延迟补偿系统 (Lag Compensation)              │  │
│  │          位置历史记录 + 回滚命中检测                  │  │
│  └─────────────────────────────────────────────────────┘  │
│                     服务器 (Server)                       │
└─────────────────────────────────────────────────────────┘
```

### 6.2 关键参数调优指南

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 输入发送频率 | 每帧或10-20ms | 越高响应越快，但带宽消耗大 |
| 服务器Tick率 | 20-60Hz | FPS游戏建议30Hz以上 |
| 插值延迟 | 50-150ms | 取决于网络质量，越大越平滑但延迟越高 |
| 回滚阈值 | 0.01-0.5单位 | 根据游戏尺度调整 |
| 位置历史保留 | 300-500ms | 确保覆盖最大RTT |
| 外推上限 | 200-500ms | 超过后应停止或减速 |

### 6.3 常见问题与解决方案

**问题1：预测抖动（Prediction Jitter）**

当服务器状态与预测状态频繁不一致时，角色会出现抖动。

解决方案：使用**指数移动平均**进行软校正：

```csharp
public class SmoothCorrection
{
    private float _smoothingFactor = 0.1f;
    
    public Vector3 ApplySmoothCorrection(Vector3 current, Vector3 target)
    {
        return Vector3.Lerp(current, target, _smoothingFactor);
    }
}
```

**问题2：带宽优化**

每帧发送完整状态会消耗大量带宽。

解决方案：使用**增量更新**和**输入合并**：

```csharp
/// <summary>
/// 增量状态更新——只发送变化的部分
/// </summary>
public struct DeltaState
{
    public bool HasPositionChanged;
    public Vector3 PositionDelta;  // 相对变化
    public bool HasRotationChanged;
    public Quaternion RotationDelta;
    public bool HasVelocityChanged;
    public Vector3 VelocityDelta;
    
    /// <summary>
    /// 计算两个状态的差异
    /// </summary>
    public static DeltaState Compute(PlayerState from, PlayerState to)
    {
        var delta = new DeltaState();
        
        float posDiff = Vector3.Distance(from.Position, to.Position);
        delta.HasPositionChanged = posDiff > 0.001f;
        delta.PositionDelta = to.Position - from.Position;
        
        float rotDiff = Quaternion.Angle(from.Rotation, to.Rotation);
        delta.HasRotationChanged = rotDiff > 0.1f;
        delta.RotationDelta = to.Rotation * Quaternion.Inverse(from.Rotation);
        
        return delta;
    }
}
```

**问题3：时间同步**

客户端和服务器的时间基准不同，需要统一时间轴。

```csharp
/// <summary>
/// 客户端-服务器时间同步（基于NTP思想）
/// </summary>
public class TimeSynchronizer
{
    private float _serverTimeOffset;  // 服务器时间 - 客户端时间
    private float _rtt;               // 往返延迟
    
    /// <summary>
    /// 处理时间同步响应
    /// </summary>
    public void OnTimeSyncResponse(float clientSendTime, float serverTime)
    {
        float now = Time.realtimeSinceStartup;
        _rtt = now - clientSendTime;
        
        // 假设延迟对称，估算服务器时间偏移
        float estimatedServerNow = serverTime + _rtt / 2f;
        _serverTimeOffset = estimatedServerNow - now;
    }
    
    /// <summary>
    /// 获取当前服务器时间（估算）
    /// </summary>
    public float GetEstimatedServerTime()
    {
        return Time.realtimeSinceStartup + _serverTimeOffset;
    }
    
    public float GetRTT() => _rtt;
}
```

## 七、总结与最佳实践

### 核心技术要点

1. **客户端预测**：立即执行输入，维护未确认输入队列，从服务器权威状态重预测
2. **服务器回滚**：权威模拟 + 防作弊检测，发送带LastProcessedInputId的状态包
3. **延迟补偿**：记录位置历史，在射击时刻回滚目标位置做命中检测
4. **状态插值**：对其他玩家使用延迟插值，对本地玩家使用预测

### 工程化建议

1. **代码一致性**：客户端预测逻辑和服务器模拟逻辑必须使用**完全相同的代码**，避免浮点精度差异
2. **确定性模拟**：使用固定时间步长（FixedUpdate），确保模拟结果可复现
3. **防作弊策略**：服务器始终是权威，客户端预测仅用于表现层
4. **带宽控制**：使用增量更新、输入合并、状态压缩
5. **平滑过渡**：回滚时使用软校正而非硬跳转，减少视觉突兀
6. **监控与调试**：记录预测偏差、回滚频率、RTT等指标，便于调优

### 进阶方向

- **帧同步 + 确定性锁步**：适用于格斗游戏，所有客户端运行完全相同的模拟
- **状态同步 + 增量快照**：适用于大型多人游戏，只同步变化的状态
- **兴趣管理（AOI）**：只同步玩家附近实体的状态，减少带宽消耗
- **网络编码（FEC/ARQ）**：结合前向纠错和自动重传，提高弱网环境下的表现

---

> **参考资源**
> - Valve: Source Multiplayer Networking (Source引擎网络同步)
> - Gaffer On Games: Networked Physics (Glenn Fiedler系列文章)
> - Unity: Netcode for GameObjects 官方文档
> - 《Game Networking: An In-Depth Guide》
