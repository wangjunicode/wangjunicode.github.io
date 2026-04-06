---
title: Unity网络游戏状态同步：预测-回滚与插值平滑
published: 2026-03-31
description: 深度解析网络游戏状态同步的核心技术，包含客户端预测（Client-Side Prediction）实现、服务端权威纠错（Reconciliation）、实体插值（其他玩家平滑移动）、命令队列与历史状态管理、网络延迟模拟工具（本地测试）、状态快照序列化优化，以及移动端网络波动的处理策略。
tags: [Unity, 网络同步, 客户端预测, 插值, 游戏开发]
category: 网络开发
draft: false
encryptedKey: henhaoji123
---

## 一、客户端预测

```csharp
using System.Collections.Generic;
using UnityEngine;

public class ClientPredictionController : MonoBehaviour
{
    [Header("预测配置")]
    [SerializeField] private float predictionThreshold = 0.3f;  // 纠错阈值（超过则拉回）

    private struct InputCommand
    {
        public int Tick;
        public Vector2 MoveInput;
        public bool Jump;
    }

    private struct StateSnapshot
    {
        public int Tick;
        public Vector3 Position;
        public Vector3 Velocity;
    }

    private Queue<InputCommand> pendingCommands = new Queue<InputCommand>();
    private List<StateSnapshot> stateHistory = new List<StateSnapshot>();
    private int currentTick;
    private CharacterController cc;

    void Awake() => cc = GetComponent<CharacterController>();

    void FixedUpdate()
    {
        var input = new InputCommand
        {
            Tick = currentTick,
            MoveInput = new Vector2(Input.GetAxis("Horizontal"), Input.GetAxis("Vertical")),
            Jump = Input.GetButton("Jump")
        };
        
        // 发送到服务端
        NetworkService.SendInput(input.Tick, input.MoveInput, input.Jump);
        
        // 本地预测执行
        var state = ExecuteInput(input, GetCurrentState());
        SaveStateSnapshot(currentTick, state);
        ApplyState(state);
        
        pendingCommands.Enqueue(input);
        currentTick++;
    }

    /// <summary>
    /// 服务端状态确认（Reconciliation）
    /// </summary>
    public void OnServerStateReceived(int serverTick, Vector3 serverPos, Vector3 serverVel)
    {
        // 找到对应Tick的本地快照
        var snapshot = stateHistory.Find(s => s.Tick == serverTick);
        
        float positionError = Vector3.Distance(snapshot.Position, serverPos);
        
        if (positionError > predictionThreshold)
        {
            // 误差过大，回滚到服务端状态并重新预测
            Debug.Log($"[Prediction] 纠错 tick={serverTick}, 误差={positionError:F2}m");
            
            // 重置到服务端状态
            transform.position = serverPos;
            
            // 移除serverTick之前的历史
            stateHistory.RemoveAll(s => s.Tick <= serverTick);
            pendingCommands = new Queue<InputCommand>(
                new List<InputCommand>(pendingCommands).FindAll(c => c.Tick > serverTick));
            
            // 重新执行未确认的命令
            var state = new StateSnapshot { Position = serverPos, Velocity = serverVel };
            foreach (var cmd in pendingCommands)
            {
                state = ExecuteInput(cmd, state);
            }
            
            ApplyState(state);
        }
        
        // 移除已确认的历史
        stateHistory.RemoveAll(s => s.Tick <= serverTick);
    }

    StateSnapshot ExecuteInput(InputCommand cmd, StateSnapshot current)
    {
        Vector3 moveDir = new Vector3(cmd.MoveInput.x, 0, cmd.MoveInput.y) * 5f * Time.fixedDeltaTime;
        return new StateSnapshot
        {
            Tick = cmd.Tick,
            Position = current.Position + moveDir,
            Velocity = moveDir / Time.fixedDeltaTime
        };
    }

    StateSnapshot GetCurrentState() => new StateSnapshot
    {
        Position = transform.position,
        Velocity = Vector3.zero
    };

    void SaveStateSnapshot(int tick, StateSnapshot state)
    {
        state.Tick = tick;
        stateHistory.Add(state);
        if (stateHistory.Count > 120) stateHistory.RemoveAt(0); // 保留2秒历史
    }

    void ApplyState(StateSnapshot state) => transform.position = state.Position;
}
```

---

## 二、其他玩家插值

```csharp
/// <summary>
/// 远端玩家插值平滑（避免网络抖动导致的跳跃移动）
/// </summary>
public class RemotePlayerInterpolator : MonoBehaviour
{
    [SerializeField] private float interpolationDelay = 0.1f;  // 100ms插值延迟

    private struct TimedState
    {
        public float Timestamp;
        public Vector3 Position;
        public Quaternion Rotation;
    }

    private List<TimedState> stateBuffer = new List<TimedState>();

    public void AddState(Vector3 pos, Quaternion rot)
    {
        stateBuffer.Add(new TimedState
        {
            Timestamp = Time.time,
            Position = pos,
            Rotation = rot
        });
        
        // 只保留最近2秒
        stateBuffer.RemoveAll(s => Time.time - s.Timestamp > 2f);
    }

    void Update()
    {
        if (stateBuffer.Count < 2) return;
        
        float renderTime = Time.time - interpolationDelay;
        
        // 找到renderTime前后的两个状态
        TimedState? prevState = null, nextState = null;
        
        for (int i = 0; i < stateBuffer.Count - 1; i++)
        {
            if (stateBuffer[i].Timestamp <= renderTime && 
                stateBuffer[i + 1].Timestamp >= renderTime)
            {
                prevState = stateBuffer[i];
                nextState = stateBuffer[i + 1];
                break;
            }
        }
        
        if (prevState.HasValue && nextState.HasValue)
        {
            float t = (renderTime - prevState.Value.Timestamp) / 
                (nextState.Value.Timestamp - prevState.Value.Timestamp);
            
            transform.position = Vector3.Lerp(prevState.Value.Position, nextState.Value.Position, t);
            transform.rotation = Quaternion.Slerp(prevState.Value.Rotation, nextState.Value.Rotation, t);
        }
    }
}
```

---

## 三、网络同步方案对比

| 方案 | 适用 | 延迟要求 | 实现复杂度 |
|------|------|---------|----------|
| 纯服务端权威 | 回合制/慢节奏 | 宽松 | 低 |
| 客户端预测 | FPS/MOBA | <100ms | 高 |
| 帧同步 | RTS/格斗 | <60ms | 很高 |
| 状态同步+插值 | RPG/MMO | <200ms | 中 |
