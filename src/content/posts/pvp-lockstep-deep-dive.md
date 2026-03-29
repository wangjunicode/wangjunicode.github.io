---
title: PVP帧同步技术完全指南 - 从第一性原理到工程落地
published: 2026-03-24
description: 从"为什么要帧同步"出发，逐步推导帧同步的完整原理，涵盖确定性计算、输入收集、追帧、断线重连、回放、反作弊等全链路工程实现，并配以可运行代码示例，真正教会你如何在Unity中实现一套生产级帧同步系统。
tags: ['Unity', '游戏开发', '帧同步', 'PVP', '网络同步', '定点数', 'LockStep']
category: 战斗系统
draft: false
---

# PVP帧同步技术完全指南 - 从第一性原理到工程落地

> **阅读提示**：本文从"为什么"出发，逐步推导帧同步每一个设计决策背后的根本原因，而不是直接告诉你"应该怎么做"。理解了第一性原理，你就能自己推导出所有的工程细节。

---

## 第一章：从一个问题出发

**问题**：两个玩家同时在线打架，怎么保证他们看到的是同一个世界？

这个问题听起来简单，实际上是网络游戏中最难的工程问题之一。我们先列举几种朴素方案，看看它们为什么不够好，从而推导出帧同步的必然性。

### 方案一：由服务器做所有计算（权威服务器）

```
客户端A → [输入] → 服务器 → [计算状态] → 广播 → 客户端A、B
                                                    客户端B
```

**优点**：逻辑在服务器，绝对可信，反作弊简单。  
**致命缺陷**：延迟体验极差。玩家按下攻击键，需要等待：
- 输入上行延迟（50ms）
- 服务器处理时间（10ms）
- 状态下行延迟（50ms）

**总感知延迟 = 110ms+**，格斗游戏、MOBA这类对操作响应极敏感的游戏完全无法接受。

### 方案二：客户端预测 + 服务器校正（状态同步）

```
客户端A：本地先执行 → 发送输入 → 收到校正 → 回滚重播
服务端：收集输入 → 权威计算 → 下发状态
```

这是 FPS 游戏（如 CS、Overwatch）的主流方案，对单个玩家体验很好，但在复杂战斗中有致命问题：

- 每帧需要同步的状态量巨大（100个单位 × 每单位20个属性 = 2000个数据/帧）
- 复杂的技能/Buff/物理系统很难精确"回滚"
- 战斗回放需要存储完整状态快照，体积庞大

### 方案三：帧同步（Frame Synchronization / LockStep）

**核心思想**：

> 与其同步"结果"，不如同步"原因"。

所有客户端运行**完全相同**的战斗逻辑，服务器只负责收集并广播每一帧的**输入操作**。只要输入相同、初始状态相同、逻辑相同，每个客户端的计算结果必然相同。

```
客户端A → [第N帧输入] ↗
                        服务器 → 广播第N帧所有输入 → 客户端A执行第N帧
客户端B → [第N帧输入] ↗                           → 客户端B执行第N帧
```

**本质优势**：
- 带宽极小（只传输入，不传状态）
- 天然支持战斗回放（录制输入序列即可）
- 多端完全一致，无需对账

**代价**：必须保证所有客户端的计算结果**按位完全一致（Determinism）**。

---

## 第二章：确定性计算 - 帧同步的地基

这是帧同步中最容易出错、也最难彻底解决的问题。

### 2.1 为什么浮点数是魔鬼

IEEE 754 浮点数在不同平台、不同编译优化级别下，同一个运算可能产生不同的结果：

```csharp
// 危险！在不同平台/编译器下结果可能不同
float a = 0.1f;
float b = 0.2f;
float c = a + b; // 可能是 0.30000001 或 0.3000000119...

// 更危险！FPU寄存器精度问题
float x = Mathf.Sqrt(2.0f); // x86 80位精度 vs ARM 64位精度 → 不同！
```

**根本原因**：
1. x86 浮点单元（FPU）内部使用 80 位扩展精度，而 ARM 使用 64 位，最终舍入结果不同
2. 编译器可能重排浮点运算顺序，导致精度差异
3. `Mathf.Sin`、`Mathf.Cos` 等超越函数在不同实现库中结果不同

**结论**：战斗逻辑中禁止使用 `float`。

### 2.2 定点数（Fixed-Point Number）原理推导

定点数的核心思想：**用整数模拟小数**。

```
定点数 = 整数 × 缩放因子(Scale)

例如，Scale = 1000：
1.5   → 存储为整数 1500
-2.3  → 存储为整数 -2300
```

**工程实现**：通常选 Scale = 2^n（位移操作比乘除更快）

```csharp
/// <summary>
/// 定点数实现（Q16.16格式：高16位整数部分，低16位小数部分）
/// Scale = 65536 (2^16)，精度约为 0.0000153
/// </summary>
public struct FP
{
    // 内部用long存储，避免乘法溢出
    public long RawValue;
    
    private const int SHIFT = 16;
    private const long ONE = 1L << SHIFT; // = 65536
    
    // 构造
    public static FP FromInt(int value) => new FP { RawValue = (long)value << SHIFT };
    public static FP FromFloat(float value) => new FP { RawValue = (long)(value * ONE) };
    
    // 转回float（仅用于渲染，不参与战斗逻辑！）
    public float ToFloat() => (float)RawValue / ONE;
    public int ToInt() => (int)(RawValue >> SHIFT);
    
    // 常量
    public static readonly FP Zero = FromInt(0);
    public static readonly FP One = FromInt(1);
    public static readonly FP Half = new FP { RawValue = ONE >> 1 };
    
    // 四则运算
    public static FP operator +(FP a, FP b) => new FP { RawValue = a.RawValue + b.RawValue };
    public static FP operator -(FP a, FP b) => new FP { RawValue = a.RawValue - b.RawValue };
    
    // 乘法：需要先移位避免溢出
    public static FP operator *(FP a, FP b)
    {
        // (a.Raw * b.Raw) 可能溢出long，需要用128位中间值或提前右移
        long result = (a.RawValue * b.RawValue) >> SHIFT;
        return new FP { RawValue = result };
    }
    
    // 除法
    public static FP operator /(FP a, FP b)
    {
        long result = (a.RawValue << SHIFT) / b.RawValue;
        return new FP { RawValue = result };
    }
    
    // 比较
    public static bool operator >(FP a, FP b) => a.RawValue > b.RawValue;
    public static bool operator <(FP a, FP b) => a.RawValue < b.RawValue;
    public static bool operator ==(FP a, FP b) => a.RawValue == b.RawValue;
    
    public override string ToString() => ToFloat().ToString("F6");
}

/// <summary>
/// 定点数向量（替代Vector3）
/// </summary>
public struct FPVector3
{
    public FP x, y, z;
    
    public static FPVector3 operator +(FPVector3 a, FPVector3 b)
        => new FPVector3 { x = a.x + b.x, y = a.y + b.y, z = a.z + b.z };
    
    public FP SqrMagnitude => x * x + y * y + z * z;
    
    public FP Magnitude => FPMath.Sqrt(SqrMagnitude);
    
    public FPVector3 Normalized
    {
        get
        {
            var mag = Magnitude;
            if (mag == FP.Zero) return default;
            return new FPVector3 { x = x / mag, y = y / mag, z = z / mag };
        }
    }
}
```

### 2.3 定点数数学库（关键函数）

三角函数、开方等运算也必须用确定性实现：

```csharp
public static class FPMath
{
    // 牛顿迭代法开方（确定性）
    public static FP Sqrt(FP value)
    {
        if (value.RawValue <= 0) return FP.Zero;
        
        // 初始猜测值
        long x = value.RawValue;
        long result = x;
        long last;
        do
        {
            last = result;
            result = (result + x / result) >> 1;
        } while (result != last && result != last - 1);
        
        // 调整回定点数格式（乘以sqrt(ONE)）
        return new FP { RawValue = result << (FP.SHIFT / 2) };
    }
    
    // 查表法实现Sin（建立256/512精度查找表）
    private static readonly FP[] SinTable = BuildSinTable(256);
    
    private static FP[] BuildSinTable(int precision)
    {
        var table = new FP[precision];
        for (int i = 0; i < precision; i++)
        {
            double angle = (double)i / precision * Math.PI * 2;
            table[i] = FP.FromFloat((float)Math.Sin(angle));
        }
        return table;
    }
    
    public static FP Sin(FP angle) // angle in radians (FP)
    {
        // 将角度映射到[0, 2π]
        // ... 查表插值
        int idx = (int)((angle.ToFloat() / (2 * Math.PI)) * SinTable.Length) % SinTable.Length;
        if (idx < 0) idx += SinTable.Length;
        return SinTable[idx];
    }
    
    public static FP Abs(FP value)
        => new FP { RawValue = value.RawValue < 0 ? -value.RawValue : value.RawValue };
    
    public static FP Min(FP a, FP b) => a < b ? a : b;
    public static FP Max(FP a, FP b) => a > b ? a : b;
    
    public static FP Clamp(FP value, FP min, FP max)
        => Min(Max(value, min), max);
}
```

### 2.4 确定性随机数

```csharp
/// <summary>
/// 线性同余随机数生成器（LCG），所有客户端使用相同seed
/// </summary>
public class FPRandom
{
    private uint _seed;
    
    public FPRandom(uint seed) { _seed = seed; }
    
    // 经典LCG算法，结果跨平台100%一致
    public uint NextUInt()
    {
        _seed = _seed * 1664525u + 1013904223u;
        return _seed;
    }
    
    public FP NextFP() // [0, 1)
    {
        return new FP { RawValue = (long)(NextUInt() >> 16) };
    }
    
    public FP Range(FP min, FP max)
    {
        return min + (max - min) * NextFP();
    }
    
    public int Range(int min, int max)
    {
        return min + (int)(NextUInt() % (uint)(max - min));
    }
}
```

> **关键原则**：所有战斗逻辑中凡是用到随机数的地方，全部通过 `FPRandom` 获取，绝不调用 `UnityEngine.Random`。

---

## 第三章：帧同步架构设计

### 3.1 逻辑帧 vs 渲染帧分离

这是帧同步的核心架构原则：

```
逻辑帧（Logic Frame / LockStep Frame）
  - 固定频率：通常 15fps 或 20fps（每帧 50ms 或 66ms）
  - 确定性计算，使用 FP 定点数
  - 每帧等待所有玩家输入到达才推进
  - 与 Unity 的 Update 解耦

渲染帧（Render Frame）
  - 跟随设备性能，60fps/120fps
  - 将逻辑状态插值到渲染表现（float，仅用于展示）
  - 不参与任何战斗逻辑计算
```

```csharp
/// <summary>
/// 帧同步驱动器 - 核心调度类
/// </summary>
public class LockStepDriver : MonoBehaviour
{
    [Header("逻辑帧配置")]
    public int logicFPS = 20;          // 逻辑帧率
    public int maxCatchUpFrames = 10;  // 每个渲染帧最多追几个逻辑帧
    
    private int _logicFrameIndex = 0;          // 当前已执行的逻辑帧
    private int _confirmedFrameIndex = -1;     // 服务器已确认的帧
    private float _logicFrameAccumulator = 0f;
    private float _logicFrameDuration;
    
    // 输入缓冲区：[帧号] → 所有玩家的输入
    private Dictionary<int, FrameInput> _frameInputBuffer = new();
    
    private BattleLogic _battleLogic; // 不含任何Unity API的纯战斗逻辑
    
    void Awake()
    {
        _logicFrameDuration = 1f / logicFPS;
    }
    
    void Update()
    {
        // 收集本帧玩家输入，发送给服务器
        CollectAndSendInput();
        
        // 尝试推进逻辑帧
        _logicFrameAccumulator += Time.deltaTime;
        int catchUpCount = 0;
        
        while (_logicFrameAccumulator >= _logicFrameDuration 
               && catchUpCount < maxCatchUpFrames)
        {
            int nextFrame = _logicFrameIndex + 1;
            
            // 检查是否有该帧的输入
            if (_frameInputBuffer.TryGetValue(nextFrame, out var input))
            {
                // 执行逻辑帧
                _battleLogic.Tick(nextFrame, input);
                _logicFrameIndex = nextFrame;
                _logicFrameAccumulator -= _logicFrameDuration;
                catchUpCount++;
            }
            else
            {
                // 输入还没到，等待（卡帧）
                break;
            }
        }
        
        // 渲染插值：根据逻辑状态更新渲染表现
        float interpolation = _logicFrameAccumulator / _logicFrameDuration;
        RenderSystem.Interpolate(_battleLogic.GetState(), interpolation);
    }
    
    // 收到服务器广播的帧输入
    public void OnReceiveFrameInput(int frameIndex, FrameInput input)
    {
        _frameInputBuffer[frameIndex] = input;
    }
}
```

### 3.2 输入系统设计

```csharp
/// <summary>
/// 单个玩家的输入快照（每逻辑帧一个）
/// 注意：使用位域压缩，减小带宽
/// </summary>
[Serializable]
public struct PlayerInput
{
    public byte playerId;
    public short moveX;      // 移动方向X，[-100, 100]映射到short
    public short moveY;      // 移动方向Y，[-100, 100]
    public uint  buttons;    // 位域：攻击/技能1/技能2/技能3/闪避...（32个按键）
    public short aimX;       // 瞄准方向X
    public short aimY;       // 瞄准方向Y
    
    // 帧序号（用于服务器排序和去重）
    public int frameIndex;
    
    // 是否有意义（区分"没有输入"和"输入丢失"）
    public bool hasInput;
    
    // 按钮辅助方法
    public bool IsButtonDown(int buttonId) => (buttons & (1u << buttonId)) != 0;
    
    public void SetButton(int buttonId, bool down)
    {
        if (down) buttons |= (1u << buttonId);
        else buttons &= ~(1u << buttonId);
    }
    
    // 序列化（网络传输）
    public byte[] Serialize()
    {
        // 总大小：1+2+2+4+2+2+4 = 17 bytes/玩家/帧
        // 8人局 = 136 bytes/帧，20fps = 2720 bytes/s ≈ 2.7KB/s，极小！
        var buf = new byte[17];
        buf[0] = playerId;
        BitConverter.GetBytes(moveX).CopyTo(buf, 1);
        BitConverter.GetBytes(moveY).CopyTo(buf, 3);
        BitConverter.GetBytes(buttons).CopyTo(buf, 5);
        BitConverter.GetBytes(aimX).CopyTo(buf, 9);
        BitConverter.GetBytes(aimY).CopyTo(buf, 11);
        BitConverter.GetBytes(frameIndex).CopyTo(buf, 13);
        return buf;
    }
}

/// <summary>
/// 一帧中所有玩家的输入集合
/// </summary>
[Serializable]
public struct FrameInput
{
    public int frameIndex;
    public PlayerInput[] playerInputs; // 长度 = 房间玩家数
    
    // 服务器校验哈希（可选，用于反作弊）
    public uint serverHash;
}
```

### 3.3 战斗逻辑核心（纯逻辑，无Unity依赖）

```csharp
/// <summary>
/// 纯逻辑战斗系统 - 不能有任何 MonoBehaviour、UnityEngine API
/// 这样才能在服务器、回放播放器、单元测试中复用
/// </summary>
public class BattleLogic
{
    private int _currentFrame = 0;
    private FPRandom _random;
    
    // 所有战斗实体（使用FP定点数）
    private List<BattleUnit> _units = new();
    
    // 战斗事件队列（由渲染层消费，显示特效/音效等）
    public Queue<BattleEvent> PendingEvents { get; } = new();
    
    public void Initialize(BattleInitData initData)
    {
        _random = new FPRandom(initData.randomSeed);
        
        foreach (var unitData in initData.units)
        {
            _units.Add(new BattleUnit
            {
                Id = unitData.id,
                PlayerId = unitData.playerId,
                Position = unitData.startPosition,
                Hp = FP.FromInt(unitData.maxHp),
                MaxHp = FP.FromInt(unitData.maxHp),
                MoveSpeed = FP.FromFloat(unitData.moveSpeed)
            });
        }
    }
    
    /// <summary>
    /// 推进一个逻辑帧
    /// </summary>
    public void Tick(int frameIndex, FrameInput input)
    {
        _currentFrame = frameIndex;
        
        // 1. 处理玩家输入
        foreach (var pi in input.playerInputs)
        {
            ApplyPlayerInput(pi);
        }
        
        // 2. 更新所有单位状态
        foreach (var unit in _units)
        {
            UpdateUnit(unit);
        }
        
        // 3. 处理碰撞检测（使用FP碰撞，不用PhysX）
        ProcessCollisions();
        
        // 4. 处理技能效果
        ProcessSkillEffects();
        
        // 5. 检查胜负条件
        CheckVictoryCondition();
        
        // 6. 生成本帧校验哈希（用于一致性检测）
        var checksum = CalculateChecksum();
        PendingEvents.Enqueue(new BattleEvent
        {
            Type = BattleEventType.FrameChecksum,
            Frame = frameIndex,
            Data = checksum
        });
    }
    
    private void ApplyPlayerInput(PlayerInput input)
    {
        var unit = _units.Find(u => u.PlayerId == input.playerId);
        if (unit == null) return;
        
        // 移动方向（使用FP，不用float）
        if (input.moveX != 0 || input.moveY != 0)
        {
            var dir = new FPVector3
            {
                x = FP.FromFloat(input.moveX / 100f),
                y = FP.Zero,
                z = FP.FromFloat(input.moveY / 100f)
            };
            unit.MoveDirection = dir.Normalized;
            unit.IsMoving = true;
        }
        else
        {
            unit.IsMoving = false;
        }
        
        // 技能释放
        if (input.IsButtonDown(0)) // 普通攻击
            unit.RequestSkill(0, _currentFrame);
        if (input.IsButtonDown(1))
            unit.RequestSkill(1, _currentFrame);
    }
    
    private void UpdateUnit(BattleUnit unit)
    {
        // 移动（FP计算）
        if (unit.IsMoving && unit.CanMove)
        {
            FP delta = unit.MoveSpeed / FP.FromInt(20); // 除以帧率
            unit.Position += unit.MoveDirection * delta;
        }
        
        // Buff Tick
        unit.UpdateBuffs(_currentFrame);
        
        // 技能CD
        unit.UpdateSkillCooldowns(_currentFrame);
    }
    
    /// <summary>
    /// 计算当前帧的状态校验和（用于检测各客户端是否出现分叉）
    /// </summary>
    public uint CalculateChecksum()
    {
        uint hash = (uint)_currentFrame;
        foreach (var unit in _units)
        {
            // 使用FP的RawValue，确保完全一致
            hash = HashCombine(hash, (uint)unit.Position.x.RawValue);
            hash = HashCombine(hash, (uint)unit.Position.z.RawValue);
            hash = HashCombine(hash, (uint)unit.Hp.RawValue);
        }
        return hash;
    }
    
    private static uint HashCombine(uint seed, uint value)
    {
        // FNV-1a 哈希
        return seed ^ (value + 0x9e3779b9 + (seed << 6) + (seed >> 2));
    }
    
    public BattleSnapshot GetState() => new BattleSnapshot
    {
        Frame = _currentFrame,
        Units = _units.Select(u => u.ToSnapshot()).ToList()
    };
}
```

---

## 第四章：追帧与断线重连

这是帧同步中最考验工程能力的部分。

### 4.1 追帧（Fast-Forward）

当玩家网络卡顿恢复后，需要快速执行多帧逻辑赶上当前进度：

```csharp
public class LockStepDriver : MonoBehaviour
{
    // ... 前面的代码 ...
    
    /// <summary>
    /// 追帧模式：不显示渲染，全速执行逻辑帧
    /// </summary>
    private IEnumerator CatchUpCoroutine(int targetFrame)
    {
        isCatchingUp = true;
        ShowCatchUpUI(true); // 显示"正在同步..."
        
        int batchSize = 50; // 每批执行50帧，然后yield让出一帧避免卡死
        
        while (_logicFrameIndex < targetFrame)
        {
            int endFrame = Mathf.Min(_logicFrameIndex + batchSize, targetFrame);
            
            for (int f = _logicFrameIndex + 1; f <= endFrame; f++)
            {
                if (_frameInputBuffer.TryGetValue(f, out var input))
                {
                    _battleLogic.Tick(f, input);
                    _logicFrameIndex = f;
                    
                    // 消耗事件队列但不触发渲染（追帧期间不播特效）
                    _battleLogic.PendingEvents.Clear();
                }
            }
            
            // 更新进度条
            float progress = (float)(_logicFrameIndex) / targetFrame;
            UpdateCatchUpProgress(progress);
            
            yield return null; // 每批yield一次，避免主线程卡死
        }
        
        isCatchingUp = false;
        ShowCatchUpUI(false);
    }
}
```

### 4.2 断线重连

断线重连是帧同步中最复杂的场景：

```csharp
/// <summary>
/// 断线重连流程
/// </summary>
public class ReconnectManager
{
    private LockStepDriver _driver;
    private NetworkClient _network;
    
    public async Task Reconnect()
    {
        // 1. 重新连接服务器
        await _network.Reconnect();
        
        // 2. 请求当前战斗快照（服务器提供某个关键帧的完整状态）
        var snapshot = await _network.RequestBattleSnapshot();
        
        // 3. 重置战斗逻辑到快照帧
        RestoreFromSnapshot(snapshot);
        
        // 4. 请求快照帧之后的所有帧输入
        var missedInputs = await _network.RequestFrameInputs(
            fromFrame: snapshot.frameIndex, 
            toFrame: _network.CurrentConfirmedFrame
        );
        
        // 5. 追帧
        foreach (var input in missedInputs)
        {
            _driver.OnReceiveFrameInput(input.frameIndex, input);
        }
        
        // 6. 启动追帧协程
        _driver.StartCatchUp(target: _network.CurrentConfirmedFrame);
    }
    
    private void RestoreFromSnapshot(BattleSnapshot snapshot)
    {
        // 从快照恢复所有战斗状态
        _driver.BattleLogic.RestoreFromSnapshot(snapshot);
        _driver.LogicFrameIndex = snapshot.frameIndex;
        
        // 恢复随机数状态（关键！）
        _driver.BattleLogic.Random.SetSeed(snapshot.randomSeed);
    }
}
```

### 4.3 乐观帧 vs 严格帧

**严格帧（Strict LockStep）**：必须等所有玩家的输入都到达才推进下一帧。
- 优点：绝对一致
- 缺点：最慢的玩家拖累所有人（卡帧）

**乐观帧（Optimistic LockStep）**：超时后使用上一帧的输入代替（预测输入）

```csharp
public class OptimisticLockStep
{
    private const int INPUT_TIMEOUT_MS = 100; // 超过100ms没收到则使用上次输入
    
    private Dictionary<int, Dictionary<byte, PlayerInput>> _inputBuffer = new();
    private Dictionary<byte, PlayerInput> _lastInputs = new(); // 各玩家上次输入
    
    public FrameInput GetOrPredictFrameInput(int frameIndex, byte[] playerIds)
    {
        var inputs = new List<PlayerInput>();
        
        foreach (var pid in playerIds)
        {
            if (_inputBuffer.TryGetValue(frameIndex, out var frameInputs)
                && frameInputs.TryGetValue(pid, out var input))
            {
                // 真实输入已到达
                inputs.Add(input);
                _lastInputs[pid] = input;
            }
            else
            {
                // 使用上一帧输入作为预测（通常玩家不会每帧都改变操作）
                if (_lastInputs.TryGetValue(pid, out var lastInput))
                {
                    var predicted = lastInput;
                    predicted.frameIndex = frameIndex;
                    inputs.Add(predicted);
                }
                else
                {
                    // 完全没有历史，使用空输入
                    inputs.Add(new PlayerInput { playerId = pid, frameIndex = frameIndex });
                }
            }
        }
        
        return new FrameInput { frameIndex = frameIndex, playerInputs = inputs.ToArray() };
    }
}
```

---

## 第五章：一致性检测与反作弊

### 5.1 帧校验和上报

```csharp
/// <summary>
/// 每隔N帧上报校验和给服务器
/// </summary>
public class ChecksumReporter
{
    private const int REPORT_INTERVAL = 10; // 每10帧上报一次
    private NetworkClient _network;
    private BattleLogic _logic;
    
    public void OnFrameTick(int frameIndex)
    {
        if (frameIndex % REPORT_INTERVAL == 0)
        {
            uint checksum = _logic.CalculateChecksum();
            _network.SendChecksum(new ChecksumReport
            {
                frameIndex = frameIndex,
                checksum = checksum,
                playerId = LocalPlayer.Id
            });
        }
    }
    
    // 服务器收到所有玩家的校验和后对比，如果不一致则触发Desync处理
    public void OnServerChecksumMismatch(int frameIndex)
    {
        Debug.LogError($"[帧同步] 第{frameIndex}帧状态出现分叉（Desync）！");
        
        // 可选方案：
        // 1. 强制断开，重新断线重连（保守）
        // 2. 请求该帧完整快照，强制对齐（激进）
        HandleDesync(frameIndex);
    }
}
```

### 5.2 回放系统

帧同步的一大优势就是天然支持精确回放：

```csharp
/// <summary>
/// 战斗回放录制与播放
/// </summary>
public class BattleReplay
{
    // 只需录制初始数据 + 所有帧的输入
    [Serializable]
    public class ReplayData
    {
        public BattleInitData initData;
        public List<FrameInput> frames = new();
        public int totalFrames;
        
        // 存储体积极小：1小时战斗(72000帧 × 8人 × 17字节) ≈ 9.8MB
    }
    
    private ReplayData _replayData;
    private BattleLogic _replayLogic;
    private int _playbackFrame = 0;
    
    public void StartPlayback(ReplayData data)
    {
        _replayData = data;
        _replayLogic = new BattleLogic();
        _replayLogic.Initialize(data.initData);
        _playbackFrame = 0;
    }
    
    // 支持任意倍速播放（快进：多执行几帧；慢放：降低逻辑帧率）
    public void TickPlayback(float speed = 1.0f)
    {
        int framesToAdvance = Mathf.RoundToInt(speed);
        
        for (int i = 0; i < framesToAdvance && _playbackFrame < _replayData.totalFrames; i++)
        {
            var input = _replayData.frames[_playbackFrame];
            _replayLogic.Tick(_playbackFrame, input);
            _playbackFrame++;
        }
    }
    
    // 跳转到指定帧（需要从头重播或从最近快照点追帧）
    public void SeekToFrame(int targetFrame)
    {
        // 从头开始（简单但慢）
        _replayLogic.Initialize(_replayData.initData);
        for (int f = 0; f < targetFrame; f++)
        {
            _replayLogic.Tick(f, _replayData.frames[f]);
        }
        _playbackFrame = targetFrame;
    }
}
```

---

## 第六章：渲染表现层（插值与分离）

逻辑和渲染分离后，需要优雅地将逻辑状态"翻译"为视觉表现：

```csharp
/// <summary>
/// 渲染表现层 - 消费逻辑状态，驱动Unity展示
/// 注意：这里全部使用float，不影响逻辑
/// </summary>
public class UnitRenderer : MonoBehaviour
{
    private BattleUnit _logicUnit; // 对逻辑单位的引用
    
    // 用于插值的上一帧和当前帧位置（float，仅渲染用）
    private Vector3 _prevRenderPos;
    private Vector3 _currRenderPos;
    
    void Update()
    {
        // 渲染插值，让表现层在逻辑帧之间平滑
        float t = LockStepDriver.Instance.RenderInterpolation; // [0,1]
        transform.position = Vector3.Lerp(_prevRenderPos, _currRenderPos, t);
    }
    
    // 由 LockStepDriver 在每个逻辑帧结束后调用
    public void OnLogicFrameEnd(BattleUnit unit)
    {
        _prevRenderPos = _currRenderPos;
        // 将FP定点数转为float，只在此处进行转换
        _currRenderPos = new Vector3(
            unit.Position.x.ToFloat(),
            unit.Position.y.ToFloat(),
            unit.Position.z.ToFloat()
        );
        _logicUnit = unit;
    }
    
    // 处理战斗事件（特效/音效/UI），不影响逻辑
    public void ConsumeEvents(Queue<BattleEvent> events)
    {
        while (events.Count > 0)
        {
            var evt = events.Dequeue();
            switch (evt.Type)
            {
                case BattleEventType.Hit:
                    PlayHitEffect(evt);
                    break;
                case BattleEventType.UnitDead:
                    PlayDeathAnimation(evt);
                    break;
                case BattleEventType.SkillCast:
                    PlaySkillEffect(evt);
                    break;
            }
        }
    }
}
```

---

## 第七章：常见踩坑与解决方案

### 坑1：Unity 物理引擎（PhysX）不可用

PhysX 内部使用浮点数，无法保证确定性。

**解决方案**：实现自己的 2D/3D 定点数碰撞检测

```csharp
/// <summary>
/// 定点数圆形碰撞检测（适合大部分MOBA/格斗游戏）
/// </summary>
public static class FPCollision
{
    public static bool CircleCircle(FPVector3 posA, FP radiusA, FPVector3 posB, FP radiusB)
    {
        var dx = posA.x - posB.x;
        var dz = posA.z - posB.z;
        var distSqr = dx * dx + dz * dz;
        var sumRadius = radiusA + radiusB;
        return distSqr <= sumRadius * sumRadius; // 不开方，避免精度损失
    }
    
    public static bool PointInRect(FPVector3 point, FPVector3 center, FP width, FP height, FP rotation)
    {
        // 将点变换到矩形局部坐标系
        var local = RotatePoint(point - center, -rotation);
        return FPMath.Abs(local.x) <= width / FP.FromInt(2)
            && FPMath.Abs(local.z) <= height / FP.FromInt(2);
    }
    
    private static FPVector3 RotatePoint(FPVector3 p, FP angle)
    {
        var cos = FPMath.Cos(angle);
        var sin = FPMath.Sin(angle);
        return new FPVector3
        {
            x = p.x * cos - p.z * sin,
            y = p.y,
            z = p.x * sin + p.z * cos
        };
    }
}
```

### 坑2：`Mathf.Approximately` 不能用于逻辑层

```csharp
// ❌ 错误：Mathf.Approximately 内部用 float 比较
if (Mathf.Approximately(unit.Hp.ToFloat(), 0f)) { ... }

// ✅ 正确：直接比较定点数
if (unit.Hp <= FP.Zero) { ... }
```

### 坑3：字典/集合遍历顺序不确定

```csharp
// ❌ 危险：Dictionary遍历顺序在不同.NET版本/平台可能不同
foreach (var unit in _unitDict.Values) { ... }

// ✅ 安全：使用有序集合或排序后遍历
foreach (var unit in _units) { ... } // List，顺序确定
// 或
foreach (var kvp in _unitDict.OrderBy(x => x.Key)) { ... }
```

### 坑4：协程 yield 时机引入不确定性

```csharp
// ❌ 在逻辑层使用协程（yield时机取决于帧率，不确定）
IEnumerator SkillEffect()
{
    yield return new WaitForSeconds(1f); // 依赖 Time.time，不确定！
    ApplyDamage(); // 这会在不同帧执行！
}

// ✅ 正确：用帧计数器替代时间
public class SkillEffect
{
    private int _startFrame;
    private int _durationFrames;
    
    public void Tick(int currentFrame)
    {
        if (currentFrame == _startFrame + _durationFrames)
        {
            ApplyDamage(); // 确定在第 startFrame + durationFrames 帧执行
        }
    }
}
```

### 坑5：`string.GetHashCode()` 平台不一致

```csharp
// ❌ 危险：.NET Core 中 GetHashCode 每次运行都不同（随机盐）
int hash = "skill_fire".GetHashCode();

// ✅ 使用确定性哈希
int hash = FNV1aHash("skill_fire");

public static int FNV1aHash(string s)
{
    uint hash = 2166136261;
    foreach (char c in s)
    {
        hash ^= c;
        hash *= 16777619;
    }
    return (int)hash;
}
```

---

## 第八章：性能优化

### 8.1 逻辑帧计算预算

以 20fps 逻辑帧为例，每帧计算预算为 50ms。通常实际逻辑计算只需 1-5ms，剩余时间用于：
- 等待网络输入
- 渲染
- 其他游戏系统

### 8.2 减小网络带宽

```csharp
// 差量压缩输入（只发生变化的部分）
public struct DeltaInput
{
    public byte changedMask; // 哪些字段发生了变化
    // 只发送 changedMask 中标记的字段
}

// 输入合批（将多帧输入一起发送，减少网络包数量）
public class InputBatcher
{
    private List<PlayerInput> _pendingInputs = new();
    private const int BATCH_SIZE = 3; // 攒3帧一起发
    
    public bool TryFlush(out PlayerInput[] batch)
    {
        if (_pendingInputs.Count >= BATCH_SIZE)
        {
            batch = _pendingInputs.Take(BATCH_SIZE).ToArray();
            _pendingInputs.RemoveRange(0, BATCH_SIZE);
            return true;
        }
        batch = null;
        return false;
    }
}
```

---

## 第九章：完整架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        客户端架构                            │
│                                                             │
│  ┌──────────────┐    ┌───────────────┐    ┌─────────────┐  │
│  │  输入收集层   │    │  网络通信层    │    │  UI/HUD层   │  │
│  │  InputSystem │    │ NetworkClient │    │  UIManager  │  │
│  └──────┬───────┘    └──────┬────────┘    └──────┬──────┘  │
│         │                  │                     │         │
│  ┌──────▼───────────────────▼─────────────────────▼──────┐  │
│  │                  LockStep驱动器                         │  │
│  │              LockStepDriver                            │  │
│  │   - 帧推进控制  - 追帧管理  - 输入缓冲  - 校验和上报    │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         │                                   │
│  ┌──────────────────────▼────────────────────────────────┐  │
│  │              战斗逻辑层（确定性，无Unity依赖）           │  │
│  │                  BattleLogic                           │  │
│  │   BattleUnit  |  SkillSystem  |  BuffSystem           │  │
│  │   FPCollision |  FPRandom     |  FPMath               │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         │ BattleEvent队列                    │
│  ┌──────────────────────▼────────────────────────────────┐  │
│  │                  渲染表现层                             │  │
│  │              RenderSystem                              │  │
│  │   UnitRenderer | EffectPlayer | CameraController      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                        服务器职责                            │
│                                                             │
│  ✅  收集所有玩家输入                                        │
│  ✅  广播帧输入（不做战斗计算）                              │
│  ✅  校验和比对（反作弊）                                    │
│  ✅  提供快照（断线重连）                                    │
│  ✅  管理房间生命周期                                        │
│  ❌  不计算战斗逻辑                                         │
│  ❌  不维护战斗状态                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 第十章：技术选型建议

| 场景 | 推荐方案 |
|------|---------|
| MOBA/RTS（复杂战斗）| 帧同步 ✅ |
| FPS（操作优先）| 状态同步 + 客户端预测 ✅ |
| 格斗游戏（2P）| 帧同步（Delay-based 或 Rollback） ✅ |
| MMO（海量玩家）| 状态同步 ✅ |
| 卡牌/回合制 | 简单状态同步 ✅ |

**帧同步适合的条件**：
1. 玩家数量有限（≤ 16人）
2. 战斗逻辑复杂、状态同步代价高
3. 需要完美的战斗回放
4. 对带宽敏感

---

## 总结

从第一性原理出发，帧同步的核心逻辑是：

> **用同样的"因"（输入），在同样的"规则"（代码）下，得到同样的"果"（状态）**

这个看似简单的原则，衍生出了所有工程细节：
- 定点数 → 消除浮点不确定性
- 确定性随机 → 消除随机不确定性
- 逻辑/渲染分离 → 保持逻辑纯粹
- 追帧/断线重连 → 保证最终一致
- 校验和 → 及早发现分叉

掌握了第一性原理，这些设计都是**必然推导**，而非凭空记忆的"规范"。

---

> 作者注：本文所有代码均经过简化以突出核心原理，生产环境中还需要考虑：服务器心跳、玩家超时踢出、网络抖动缓冲、输入预测回滚（Rollback Netcode）等更复杂的场景。
