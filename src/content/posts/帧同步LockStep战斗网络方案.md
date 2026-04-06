---
title: 帧同步战斗网络方案（FSP LockStep）
published: 2024-01-01
description: "帧同步战斗网络方案（FSP LockStep） - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 帧同步战斗网络方案（FSP LockStep）

## 1. 系统概述

本项目战斗采用**帧同步（Frame Synchronization / Lock-Step）**方案，而非状态同步。所有客户端运行完全相同的战斗逻辑，服务器只负责收集输入并广播，不做战斗计算。

**选择帧同步的原因：**
- 战斗逻辑复杂（技能、Buff、物理碰撞），状态同步数据量爆炸
- 支持战斗回放（保存帧输入序列即可还原）
- 保证多端完全一致，无作弊空间

**核心约束：**
- 所有战斗计算使用定点数（TrueSync FP），不用 float
- 所有随机数使用确定性随机（TSRandom，种子一致）
- 禁止在战斗逻辑中调用 `Time.time`，改用 `Game.FixedTime`（帧计数器）

---

## 2. 架构图

```
客户端A                 服务器（FSP Server）             客户端B
   │                           │                           │
   │─── InputFrame(帧N,输入) ──→│                           │
   │                           │─── Broadcast(帧N,A+B输入) →│
   │←── Broadcast(帧N,A+B输入) ─│                           │
   │                           │                           │
[ExecuteFrame(N)]                                    [ExecuteFrame(N)]
   ↓ 相同输入+相同逻辑 = 相同结果 ↓
[状态快照Hash]                                       [状态快照Hash]
   │───────── Hash一致性校验 ──────────────────────────────│
```

---

## 3. 核心组件

### 3.1 LockStepComponent —— 锁步主控

```csharp
// Hotfix/Function/Framework/LockStep/LockStepComponentSystem.cs
[FriendOf(typeof(LockStepComponent))]
public static partial class LockStepComponentSystem
{
    [EntitySystem]
    private static void Awake(this LockStepComponent self)
    {
        // 订阅固定帧更新事件（每帧战斗Tick）
        self.RootDispatcher().RegisterEvent<Evt_FixedUpdate>(self.EnterFrame);
        
        // 获取 FSP（Frame Synchronization Protocol）网络组件
        self.fspComp = self.Parent.GetComponent<FSPComponent>();
        
        // 获取战斗玩家组件
        self.battlePlayerComp = self.Parent.GetComponent<BattlePlayerComponent>();
        
        // 注册服务端命令回调
        self.battlePlayerComp.RegisterServerCommandCallback(
            VKeyDef.PVP_CONTROL_START, self.OnSyncControlStart);
        self.battlePlayerComp.RegisterServerCommandCallback(
            VKeyDef.PVP_ROUND_BEGIN, self.OnSyncRoundBegin2);
        self.battlePlayerComp.RegisterServerCommandCallback(
            VKeyDef.PVP_ROUND_END, self.OnSyncRoundEnd);
        self.battlePlayerComp.RegisterServerCommandCallback(
            VKeyDef.PVP_BATTLE_END, self.OnSyncBattleEnd);
        
        // 注册本地输入事件
        self.RootDispatcher().RegisterEvent<Evt_InputVKey>(self.OnInputVKey);
        self.RootDispatcher().RegisterEvent<Evt_PointEvent>(self.OnPointEvent);
        
        // 每10帧进行一次Hash校验（可配置）
        self._syncHashFrequency = 10 * LockStepDefine.FRAME_INTERVAL_DEFAULT;
        
        // 开启帧记录（用于战斗回放）
        self.battlePlayerComp.SetEnableRecordFrames(true);
    }
```

### 3.2 输入收集与发送

```csharp
    // 本地玩家操作输入 → 发送给服务器
    private static void OnInputVKey(this LockStepComponent self, Evt_InputVKey arg)
    {
        // 控制还未开始（等待服务器 PVP_CONTROL_START），先缓存输入
        if (!self.battlePlayerComp.ControlBegin) return;

        if (arg.key == EInputKey.Move)
        {
            // 移动输入：向量值需转换为整数（乘以10000），确保精度
            var v = arg.vector * 10000;
            v.x = v.x.AsInt();
            v.y = v.y.AsInt();
            v.z = v.z.AsInt();
            
            // SendFSP(key, frameIndex, params)
            self.fspComp.SendFSP(
                (short)arg.key, 
                self.battlePlayerComp.FrameIndex,  // 当前本地帧号
                new int[] { v.x.AsInt(), v.y.AsInt(), v.z.AsInt() });
        }
        else
        {
            // 普通按键输入（技能、普攻等）
            self.fspComp.SendFSP(
                (short)arg.key, 
                self.battlePlayerComp.FrameIndex, 
                0);
        }
    }

    private static void OnPointEvent(this LockStepComponent self, Evt_PointEvent arg)
    {
        if (arg.EventID == BPDef.BattleEnd || arg.EventID == BPDef.TimeOut)
        {
            self._isOver = true;
            self._battleEndFrame = self.battlePlayerComp.FrameIndex;
            self.battlePlayerComp.winGroup = arg.Team.TeamId;
        }
    }
```

### 3.3 执行帧逻辑

```csharp
    // 每个 FixedUpdate Tick 调用
    private static void EnterFrame(this LockStepComponent self, Evt_FixedUpdate _)
    {
        // 检查是否有待执行的帧数据
        while (self.battlePlayerComp.HasNextFrame())
        {
            var frameData = self.battlePlayerComp.GetNextFrame();
            
            // 执行当前帧所有玩家输入
            foreach (var input in frameData.Inputs)
            {
                self.ExecuteInput(input);
            }
            
            // 推进游戏逻辑帧
            self.battlePlayerComp.AdvanceFrame();
            
            // 每N帧上报状态Hash进行校验
            if (self.battlePlayerComp.FrameIndex % self._syncHashFrequency == 0)
            {
                var hash = self.CalculateStateHash();
                self.fspComp.ReportHash(self.battlePlayerComp.FrameIndex, hash);
            }
        }
    }
```

---

## 4. 定点数物理系统（TrueSync）

帧同步的关键：所有涉及位置、碰撞的计算必须使用定点数。

```csharp
// ThirdParty/TrueSync/TSVector.cs
public struct TSVector
{
    public FP x, y, z;  // 全部是定点数

    public static TSVector operator +(TSVector a, TSVector b)
    {
        return new TSVector(a.x + b.x, a.y + b.y, a.z + b.z);
    }
    
    // 向量长度（使用定点数开方，查表法）
    public FP magnitude => TSMath.Sqrt(x*x + y*y + z*z);
    
    // 点积
    public static FP Dot(TSVector a, TSVector b)
    {
        return a.x*b.x + a.y*b.y + a.z*b.z;
    }
}

// TSQuaternion.cs - 定点数四元数
public struct TSQuaternion
{
    public FP x, y, z, w;
    
    // LookRotation 使用定点数 Atan2，跨平台完全一致
    public static TSQuaternion LookRotation(TSVector forward, TSVector up)
    {
        // 全部走定点数矩阵运算
    }
}
```

---

## 5. OBB 碰撞检测

```csharp
// Hotfix/Battle/Function/GamePlay/Collider/Obb.cs
// 定向包围盒（OBB）碰撞检测，全部使用 FP 定点数
public struct Obb
{
    public TSVector Center;     // 中心点
    public TSVector Extents;    // 半轴长度
    public TSQuaternion Rotation; // 旋转
    
    // SAT（分离轴定理）碰撞检测
    public bool Intersects(Obb other)
    {
        // 15条分离轴（各3+3轴 + 9条叉积轴）
        // 全部使用 FP 运算，保证跨平台一致
    }
}
```

---

## 6. 战斗回放系统

帧同步的附赠能力：只需保存每帧的输入序列，即可完整还原任何一场战斗。

```csharp
// 录制：每帧输入自动记录
self.battlePlayerComp.SetEnableRecordFrames(true);

// 回放：读取录制数据，重新走一遍帧逻辑
public static async ETTask PlayReplay(ReplayData replay)
{
    foreach (var frameData in replay.Frames)
    {
        // 注入录制的输入数据（而非网络数据）
        foreach (var input in frameData.Inputs)
        {
            battleLogic.ApplyInput(input);
        }
        await TimerComponent.Instance.WaitFrameAsync();
    }
}
```

---

## 7. 常见问题

**Q: 帧同步延迟大怎么优化？**  
A: 使用"乐观帧锁定"（本地先执行预测帧，收到服务器确认后校对）。本项目实现在 FSPComponent 中。

**Q: 断线重连如何处理？**  
A: 服务器保留历史帧数据，客户端重连后快速追帧（加速模拟跑完所有帧，不渲染）。

**Q: Hash校验不一致怎么处理？**  
A: 触发 `PVPSyncErrorEvent`，记录分叉帧，上报服务器，通常需要关闭战斗或踢出作弊玩家。

**Q: float 偷偷用了会怎样？**  
A: 短期内可能不出问题（桌面端 x64 通常一致），但 iOS ARM64 与 Android 可能出现极小差异，随着帧数累积导致逻辑分叉。务必全部用 FP。
