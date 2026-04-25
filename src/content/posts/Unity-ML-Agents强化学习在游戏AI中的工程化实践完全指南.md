---
title: Unity ML-Agents强化学习在游戏AI中的工程化实践完全指南
published: 2026-04-25
description: 深入解析Unity ML-Agents框架的核心架构，从强化学习基础理论（PPO/SAC算法）到游戏AI实战训练，涵盖观察空间设计、奖励函数工程、多智能体对抗训练、自我对弈（Self-Play）、模型部署与推理优化，以及课程学习（Curriculum Learning）等工程化实践。
tags: [ML-Agents, 强化学习, 游戏AI, Unity, 机器学习, PPO]
category: 游戏AI
draft: false
---

# Unity ML-Agents强化学习在游戏AI中的工程化实践完全指南

## 一、为什么用强化学习做游戏AI

传统游戏AI依赖手工设计的行为树、状态机或规则系统，存在以下局限：

| 问题 | 手工AI | 强化学习AI |
|-----|--------|-----------|
| 开发成本 | 高，每个行为都需手写 | 定义环境和奖励即可 |
| 适应性 | 差，固定规则易被玩家破解 | 强，从无数次对局中自我进化 |
| 涌现行为 | 无 | 可产生设计者未预期的创意策略 |
| 规模扩展 | 线性复杂度增长 | 通过并行环境加速训练 |
| 对抗性 | 难以持续更新 | 自我对弈(Self-Play)持续提升 |

**典型应用场景**：
- FPS游戏的高水平机器人对手
- RTS游戏的自适应难度AI
- 角色移动与导航的无监督训练
- NPC的涌现社交行为模拟

---

## 二、ML-Agents框架核心架构

### 2.1 组件关系图

```
┌─────────────────── Unity 环境 ───────────────────┐
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │           Agent（游戏对象）                  │ │
│  │  ├── BehaviorParameters（行为配置）          │ │
│  │  ├── DecisionRequester（决策频率）           │ │
│  │  └── 自定义Agent脚本（观察/动作/奖励）       │ │
│  └─────────────────────────────────────────────┘ │
│                        ↕ gRPC                    │
└─────────────────────────────────────────────────-┘
                         ↕
┌─────────────────── Python训练端 ─────────────────┐
│  mlagents-learn  →  PPO/SAC训练器               │
│                  →  神经网络（PyTorch）           │
│                  →  TensorBoard监控              │
└─────────────────────────────────────────────────-┘
```

### 2.2 ML-Agents核心类

```csharp
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

/// <summary>
/// ML-Agents Agent基类核心接口说明
/// 开发者需要重写这三个关键方法
/// </summary>
public abstract class BaseMLAgent : Agent
{
    // =========================================================
    // 1. 收集观察数据：告诉AI"它能看到什么"
    // =========================================================
    public override void CollectObservations(VectorSensor sensor)
    {
        // 将游戏状态编码为浮点数向量
        // 向量维度必须与BehaviorParameters中的ObservationSize一致
    }

    // =========================================================
    // 2. 执行动作：AI的输出如何影响游戏世界
    // =========================================================
    public override void OnActionReceived(ActionBuffers actions)
    {
        // actions.ContinuousActions：连续动作（-1~1的浮点数）
        // actions.DiscreteActions：离散动作（整数索引）
    }

    // =========================================================
    // 3. Episode开始时的初始化
    // =========================================================
    public override void OnEpisodeBegin()
    {
        // 重置环境状态，开始新一轮游戏
    }

    // =========================================================
    // 可选：手动控制（用于调试和行为克隆数据收集）
    // =========================================================
    public override void Heuristic(in ActionBuffers actionsOut)
    {
        // 用玩家输入控制Agent，用于录制示范数据
    }
}
```

---

## 三、实战案例：3D格斗AI训练

### 3.1 环境设计

```csharp
using UnityEngine;
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

/// <summary>
/// 格斗游戏AI Agent实现
/// 目标：学会击败对手的同时保护自己
/// </summary>
public class FighterAgent : Agent
{
    [Header("角色组件")]
    [SerializeField] private CharacterController _controller;
    [SerializeField] private Animator _animator;
    [SerializeField] private Transform _opponent;       // 对手Transform
    [SerializeField] private FighterStats _stats;       // 生命值、攻击力等

    [Header("训练配置")]
    [SerializeField] private float _moveSpeed = 5f;
    [SerializeField] private float _attackRange = 2f;
    [SerializeField] private float _episodeMaxTime = 30f;  // 最大回合时间

    private float _episodeTimer;
    private float _previousOpponentHP;
    private float _previousSelfHP;
    private Vector3 _startPosition;

    private void Start()
    {
        _startPosition = transform.position;
    }

    // =========================================================
    // 观察空间设计：共 22 个浮点观察值
    // =========================================================
    public override void CollectObservations(VectorSensor sensor)
    {
        // 1. 自身状态（6个观察值）
        sensor.AddObservation(transform.localPosition.x / 10f);     // 归一化位置X
        sensor.AddObservation(transform.localPosition.z / 10f);     // 归一化位置Z
        sensor.AddObservation(_stats.NormalizedHP);                  // 自身血量比例 [0,1]
        sensor.AddObservation(_stats.IsAttacking ? 1f : 0f);        // 是否在攻击
        sensor.AddObservation(_stats.IsStunned ? 1f : 0f);         // 是否被眩晕
        sensor.AddObservation(_stats.AttackCooldownNormalized);      // 攻击CD进度 [0,1]

        // 2. 对手状态（6个观察值）
        sensor.AddObservation(_opponent.localPosition.x / 10f);     // 对手位置X
        sensor.AddObservation(_opponent.localPosition.z / 10f);     // 对手位置Z
        var opponentStats = _opponent.GetComponent<FighterStats>();
        sensor.AddObservation(opponentStats.NormalizedHP);           // 对手血量比例
        sensor.AddObservation(opponentStats.IsAttacking ? 1f : 0f); // 对手是否在攻击
        sensor.AddObservation(opponentStats.IsStunned ? 1f : 0f);  // 对手是否被眩晕
        sensor.AddObservation(opponentStats.AttackCooldownNormalized);

        // 3. 相对关系（5个观察值）
        Vector3 relativePos = transform.InverseTransformPoint(_opponent.position);
        sensor.AddObservation(relativePos.x / 10f);                  // 相对位置X（局部坐标）
        sensor.AddObservation(relativePos.z / 10f);                  // 相对位置Z
        float distanceToOpponent = Vector3.Distance(transform.position, _opponent.position);
        sensor.AddObservation(distanceToOpponent / 15f);             // 与对手的距离（归一化）
        
        // 方向向量（对手相对自身的角度）
        Vector3 dirToOpponent = (_opponent.position - transform.position).normalized;
        sensor.AddObservation(Vector3.Dot(transform.forward, dirToOpponent)); // 是否面向对手
        sensor.AddObservation(Vector3.Dot(transform.right, dirToOpponent));   // 相对左右偏移

        // 4. 场地边界感知（3个观察值）
        sensor.AddObservation(Mathf.Clamp01((transform.position.x + 8f) / 16f));  // 距左边界
        sensor.AddObservation(Mathf.Clamp01((8f - transform.position.x) / 16f));  // 距右边界
        sensor.AddObservation(_episodeTimer / _episodeMaxTime);                    // 回合时间进度

        // 5. 历史动作记忆（2个观察值，实现简单的时序感知）
        sensor.AddObservation(_stats.LastActionType / 4f);   // 上一个动作类型（归一化）
        sensor.AddObservation(_stats.ComboCount / 5f);        // 当前连招数（归一化）
    }

    // =========================================================
    // 动作空间设计
    // =========================================================
    public override void OnActionReceived(ActionBuffers actions)
    {
        // 连续动作：移动方向 (2个连续值)
        float moveX = actions.ContinuousActions[0]; // [-1, 1]
        float moveZ = actions.ContinuousActions[1]; // [-1, 1]

        // 离散动作：战斗行为 (1个离散动作，5个选项)
        int combatAction = actions.DiscreteActions[0];
        // 0=无动作, 1=轻攻击, 2=重攻击, 3=防御, 4=技能

        // 执行移动
        if (!_stats.IsStunned)
        {
            Vector3 movement = new Vector3(moveX, 0, moveZ).normalized;
            _controller.Move(movement * _moveSpeed * Time.deltaTime);

            // 朝向对手
            if (movement.magnitude > 0.1f)
            {
                Vector3 faceDir = (_opponent.position - transform.position).normalized;
                faceDir.y = 0;
                transform.rotation = Quaternion.Slerp(
                    transform.rotation,
                    Quaternion.LookRotation(faceDir),
                    10f * Time.deltaTime
                );
            }
        }

        // 执行战斗动作
        ExecuteCombatAction(combatAction);

        // 回合超时处理
        _episodeTimer += Time.fixedDeltaTime;
        if (_episodeTimer >= _episodeMaxTime)
        {
            // 超时：双方按血量比例给予奖励
            float hpDiff = _stats.NormalizedHP - opponentStats.NormalizedHP;
            AddReward(hpDiff * 0.5f);
            EndEpisode();
        }
    }

    private FighterStats opponentStats => _opponent.GetComponent<FighterStats>();

    private void ExecuteCombatAction(int action)
    {
        float distance = Vector3.Distance(transform.position, _opponent.position);

        switch (action)
        {
            case 1: // 轻攻击
                if (distance <= _attackRange && !_stats.IsAttackOnCooldown)
                {
                    _stats.PerformLightAttack(_opponent.gameObject);
                    _animator.SetTrigger("LightAttack");
                }
                break;
            case 2: // 重攻击（高伤害，高CD，大后摇）
                if (distance <= _attackRange * 0.8f && !_stats.IsAttackOnCooldown)
                {
                    _stats.PerformHeavyAttack(_opponent.gameObject);
                    _animator.SetTrigger("HeavyAttack");
                }
                break;
            case 3: // 防御
                _stats.IsBlocking = true;
                _animator.SetBool("Blocking", true);
                break;
            default:
                _stats.IsBlocking = false;
                _animator.SetBool("Blocking", false);
                break;
        }
    }

    // =========================================================
    // 奖励函数设计：这是强化学习中最重要的部分
    // =========================================================
    private void FixedUpdate()
    {
        ComputeStepReward();
    }

    private void ComputeStepReward()
    {
        float reward = 0f;

        // === 正向奖励 ===

        // 1. 对对手造成伤害（最核心奖励）
        float opponentHPLoss = _previousOpponentHP - opponentStats.NormalizedHP;
        if (opponentHPLoss > 0)
            reward += opponentHPLoss * 5f;  // 权重5，重要

        // 2. 接近对手（但不过度，避免只靠近不攻击）
        float distance = Vector3.Distance(transform.position, _opponent.position);
        if (distance < _attackRange * 1.5f)
            reward += 0.001f;  // 小幅鼓励接近

        // 3. 连击奖励（激励连续进攻）
        if (_stats.ComboCount > 2)
            reward += _stats.ComboCount * 0.01f;

        // === 负向奖励 ===

        // 4. 受到伤害（惩罚）
        float selfHPLoss = _previousSelfHP - _stats.NormalizedHP;
        if (selfHPLoss > 0)
            reward -= selfHPLoss * 3f;  // 权重3，受伤惩罚

        // 5. 落出边界惩罚
        if (Mathf.Abs(transform.position.x) > 9f || Mathf.Abs(transform.position.z) > 9f)
            reward -= 0.5f;

        // 6. 时间惩罚（激励主动进攻，避免消极防守）
        reward -= 0.001f;

        AddReward(reward);

        // 更新历史状态
        _previousOpponentHP = opponentStats.NormalizedHP;
        _previousSelfHP = _stats.NormalizedHP;
    }

    public override void OnEpisodeBegin()
    {
        // 重置位置和状态
        transform.position = _startPosition;
        _stats.Reset();
        opponentStats.Reset();
        _episodeTimer = 0f;
        _previousOpponentHP = 1f;
        _previousSelfHP = 1f;
    }

    // =========================================================
    // 击败/死亡事件回调
    // =========================================================
    public void OnOpponentDefeated()
    {
        SetReward(1.0f);    // 胜利：满分奖励
        EndEpisode();
    }

    public void OnSelfDefeated()
    {
        SetReward(-1.0f);   // 失败：满分惩罚
        EndEpisode();
    }

    // =========================================================
    // Heuristic：人工控制，用于行为克隆数据收集
    // =========================================================
    public override void Heuristic(in ActionBuffers actionsOut)
    {
        var continuous = actionsOut.ContinuousActions;
        var discrete = actionsOut.DiscreteActions;

        continuous[0] = Input.GetAxis("Horizontal");
        continuous[1] = Input.GetAxis("Vertical");

        discrete[0] = 0;
        if (Input.GetKey(KeyCode.J)) discrete[0] = 1;      // 轻攻击
        else if (Input.GetKey(KeyCode.K)) discrete[0] = 2; // 重攻击
        else if (Input.GetKey(KeyCode.L)) discrete[0] = 3; // 防御
    }
}
```

---

## 四、训练配置与超参数调优

### 4.1 YAML训练配置文件

```yaml
# fighter_config.yaml
# 运行命令: mlagents-learn fighter_config.yaml --run-id=fighter_v1

behaviors:
  FighterAgent:
    trainer_type: ppo              # 使用PPO算法
    
    hyperparameters:
      batch_size: 2048             # 每次更新使用的样本数
      buffer_size: 20480           # 经验回放缓冲区大小
      learning_rate: 3.0e-4        # 学习率（Adam优化器）
      beta: 5.0e-3                 # 熵正则化系数（控制探索程度）
      epsilon: 0.2                 # PPO裁剪参数
      lambd: 0.95                  # GAE(λ)优势估计参数
      num_epoch: 3                 # 每批数据训练轮数
      learning_rate_schedule: linear  # 学习率随训练线性衰减
      
    network_settings:
      normalize: true              # 归一化观察输入（推荐）
      hidden_units: 256            # 隐藏层神经元数
      num_layers: 2                # 隐藏层层数
      # 对于复杂任务可增加到 512 × 3
      
    reward_signals:
      extrinsic:                   # 来自AddReward/SetReward的外部奖励
        gamma: 0.99                # 折扣因子（长期/短期平衡）
        strength: 1.0
      curiosity:                   # 好奇心内在奖励（鼓励探索）
        gamma: 0.99
        strength: 0.02             # 较小的内在奖励权重
        encoding_size: 256
        learning_rate: 3.0e-4
        
    max_steps: 10000000            # 总训练步数
    time_horizon: 128              # 截断时间步（每次更新前收集的步数）
    summary_freq: 10000            # 每N步记录一次TensorBoard数据
    
    # 自我对弈配置（让AI和自己的历史版本对战）
    self_play:
      save_steps: 20000            # 每N步保存一个对手快照
      team_change: 100000          # 每N步随机切换队伍
      swap_steps: 2000             # 每N步随机替换对手历史版本
      window: 10                   # 保留最近10个历史版本
      play_against_latest_model_ratio: 0.5  # 50%对战最新版本
      initial_elo: 1200            # ELO评分初始值
```

### 4.2 课程学习配置（Curriculum Learning）

课程学习让AI从简单任务开始，逐步挑战更难的任务：

```yaml
# 在fighter_config.yaml中添加
environment_parameters:
  opponent_strength:              # 对手强度（环境参数）
    curriculum:
      - name: EasyStart           # 阶段1：弱对手
        completion_criteria:
          measure: reward         # 基于奖励判断是否完成
          behavior: FighterAgent
          signal_smoothing: true
          min_lesson_length: 100  # 至少训练100次更新
          threshold: 0.5          # 平均奖励>0.5时进入下一阶段
        value: 0.2                # 对手强度=0.2
        
      - name: MediumChallenge    # 阶段2：中等对手
        completion_criteria:
          measure: reward
          behavior: FighterAgent
          signal_smoothing: true
          min_lesson_length: 200
          threshold: 0.6
        value: 0.5                # 对手强度=0.5
        
      - name: ExpertLevel        # 阶段3：强对手
        value: 1.0               # 对手强度=1.0
```

在Unity中读取课程学习参数：

```csharp
/// <summary>
/// 在Agent中读取课程学习动态参数，调整环境难度
/// </summary>
public class CurriculumAwareAgent : FighterAgent
{
    private EnvironmentParameters _envParams;

    public override void Initialize()
    {
        base.Initialize();
        _envParams = Academy.Instance.EnvironmentParameters;
    }

    public override void OnEpisodeBegin()
    {
        base.OnEpisodeBegin();
        
        // 从Python训练器读取当前难度参数
        float opponentStrength = _envParams.GetWithDefault("opponent_strength", 1.0f);
        
        // 根据难度设置对手AI
        var opponentAgent = _opponent.GetComponent<FighterStats>();
        opponentAgent.AttackMultiplier = opponentStrength;
        opponentAgent.MoveSpeedMultiplier = 0.5f + opponentStrength * 0.5f;
        
        Debug.Log($"[CurriculumAgent] 当前对手强度: {opponentStrength:F2}");
    }
}
```

---

## 五、多智能体训练与通信

### 5.1 团队协作场景（5v5）

```csharp
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

/// <summary>
/// 5v5团队协作Agent
/// 通过GroupReward实现团队协作训练
/// </summary>
public class TeamAgent : Agent
{
    [SerializeField] private int _teamId;   // 0=红队, 1=蓝队
    [SerializeField] private Transform[] _teammates;   // 4个队友
    [SerializeField] private Transform[] _enemies;     // 5个敌人
    
    private SimpleMultiAgentGroup _agentGroup;

    public override void Initialize()
    {
        // 注册到多智能体组（共享团队奖励）
        _agentGroup = new SimpleMultiAgentGroup();
        foreach (var teammate in _teammates)
        {
            var ta = teammate.GetComponent<TeamAgent>();
            if (ta != null) _agentGroup.RegisterAgent(ta);
        }
        _agentGroup.RegisterAgent(this);
    }

    public override void CollectObservations(VectorSensor sensor)
    {
        // 自身状态
        sensor.AddObservation(transform.localPosition / 20f);
        sensor.AddObservation(_teamId);

        // 队友状态（通信观察）
        foreach (var teammate in _teammates)
        {
            if (teammate == null) { sensor.AddObservation(Vector3.zero); continue; }
            sensor.AddObservation(teammate.localPosition / 20f);
            var ts = teammate.GetComponent<FighterStats>();
            sensor.AddObservation(ts != null ? ts.NormalizedHP : 0f);
        }

        // 敌人状态
        foreach (var enemy in _enemies)
        {
            if (enemy == null) { sensor.AddObservation(Vector3.zero); continue; }
            sensor.AddObservation(enemy.localPosition / 20f);
            var es = enemy.GetComponent<FighterStats>();
            sensor.AddObservation(es != null ? es.NormalizedHP : 0f);
        }
    }

    /// <summary>
    /// 团队层面的奖励：胜利时奖励整个团队
    /// 使用GroupEndEpisode代替单个EndEpisode
    /// </summary>
    public void OnTeamVictory()
    {
        _agentGroup.AddGroupReward(1.0f);
        _agentGroup.EndGroupEpisode();
    }

    public void OnTeamDefeat()
    {
        _agentGroup.AddGroupReward(-1.0f);
        _agentGroup.EndGroupEpisode();
    }
}
```

---

## 六、模型部署与推理优化

### 6.1 训练完成后的模型部署

```csharp
using Unity.MLAgents;
using Unity.MLAgents.Policies;
using Unity.Barracuda;

/// <summary>
/// AI对手切换控制器
/// 支持运行时动态加载不同强度的模型
/// </summary>
public class AIOpponentController : MonoBehaviour
{
    [System.Serializable]
    public class DifficultyModel
    {
        public string DifficultyName;        // "Easy", "Medium", "Hard", "Expert"
        public NNModel Model;                // Barracuda神经网络模型
        [Range(0.1f, 1f)]
        public float ReactionSpeed = 1f;     // 决策频率倍率
    }

    [SerializeField] private DifficultyModel[] _difficultyModels;
    [SerializeField] private Agent _aiAgent;
    [SerializeField] private DecisionRequester _decisionRequester;

    private BehaviorParameters _behaviorParams;

    private void Awake()
    {
        _behaviorParams = _aiAgent.GetComponent<BehaviorParameters>();
    }

    /// <summary>
    /// 切换AI难度模型
    /// </summary>
    public void SetDifficulty(string difficultyName)
    {
        var model = System.Array.Find(_difficultyModels, 
                                       d => d.DifficultyName == difficultyName);
        if (model == null)
        {
            Debug.LogWarning($"[AIOpponent] 未找到难度配置: {difficultyName}");
            return;
        }

        // 切换神经网络模型
        _behaviorParams.Model = model.Model;

        // 调整决策频率（简单AI决策慢，困难AI决策快）
        _decisionRequester.DecisionPeriod = Mathf.RoundToInt(5 / model.ReactionSpeed);

        Debug.Log($"[AIOpponent] 已切换到 {difficultyName} 难度");
    }

    /// <summary>
    /// 运行时从Resources动态加载模型
    /// 用于支持从服务器热更新AI模型
    /// </summary>
    public void LoadModelFromResources(string modelPath)
    {
        var nnModel = Resources.Load<NNModel>(modelPath);
        if (nnModel == null)
        {
            Debug.LogError($"[AIOpponent] 模型加载失败: {modelPath}");
            return;
        }
        _behaviorParams.Model = nnModel;
        Debug.Log($"[AIOpponent] 已加载模型: {modelPath}");
    }
}
```

### 6.2 推理性能优化

```csharp
/// <summary>
/// ML-Agents推理性能优化配置
/// 在不需要高频决策时降低推理频率，节省CPU/GPU
/// </summary>
[RequireComponent(typeof(DecisionRequester))]
public class AdaptiveDecisionRequester : MonoBehaviour
{
    [Header("动态决策频率")]
    [SerializeField] private int _normalDecisionPeriod = 5;     // 正常情况每5帧决策一次
    [SerializeField] private int _combatDecisionPeriod = 2;     // 战斗中每2帧决策一次
    [SerializeField] private int _idleDecisionPeriod  = 10;    // 空闲时每10帧决策一次

    private DecisionRequester _decisionRequester;
    private FighterStats _stats;

    private void Awake()
    {
        _decisionRequester = GetComponent<DecisionRequester>();
        _stats = GetComponent<FighterStats>();
    }

    private void Update()
    {
        // 根据游戏状态动态调整决策频率
        float distanceToOpponent = GetDistanceToNearestOpponent();

        if (distanceToOpponent < 5f) // 战斗范围内：高频决策
        {
            _decisionRequester.DecisionPeriod = _combatDecisionPeriod;
        }
        else if (distanceToOpponent > 20f) // 远离对手：低频决策
        {
            _decisionRequester.DecisionPeriod = _idleDecisionPeriod;
        }
        else
        {
            _decisionRequester.DecisionPeriod = _normalDecisionPeriod;
        }
    }

    private float GetDistanceToNearestOpponent()
    {
        // 查找最近对手距离（根据项目实际实现）
        return float.MaxValue;
    }
}
```

### 6.3 模型推理性能基准

```csharp
/// <summary>
/// ML推理性能分析工具
/// 测量每次推理的CPU耗时，帮助确定最优决策频率
/// </summary>
public class MLInferenceBenchmark : MonoBehaviour
{
    private Unity.Profiling.ProfilerMarker _inferenceMarker
        = new Unity.Profiling.ProfilerMarker("MLAgent.Inference");

    private float _totalInferenceTime = 0f;
    private int _inferenceCount = 0;
    private float _peakInferenceTime = 0f;

    public void RecordInference(System.Action inferenceAction)
    {
        using (_inferenceMarker.Auto())
        {
            float start = Time.realtimeSinceStartup;
            inferenceAction?.Invoke();
            float elapsed = (Time.realtimeSinceStartup - start) * 1000f;

            _totalInferenceTime += elapsed;
            _inferenceCount++;
            _peakInferenceTime = Mathf.Max(_peakInferenceTime, elapsed);
        }
    }

    public void PrintReport()
    {
        if (_inferenceCount == 0) return;
        float avg = _totalInferenceTime / _inferenceCount;
        Debug.Log($"[MLBenchmark] 推理统计:\n" +
                 $"  总次数: {_inferenceCount}\n" +
                 $"  平均耗时: {avg:F3}ms\n" +
                 $"  峰值耗时: {_peakInferenceTime:F3}ms\n" +
                 $"  推荐最低决策间隔: {Mathf.CeilToInt(avg * 3):D}帧（60FPS基准）");
    }
}
```

---

## 七、训练技巧与常见问题

### 7.1 奖励函数设计原则

```
奖励塑形(Reward Shaping)最佳实践：

✅ 正确做法：
  1. 主要奖励 → 最终目标（胜利/失败）：±1.0
  2. 辅助奖励 → 中间目标（造成伤害）：±0.1~0.5  
  3. 塑形奖励 → 行为引导（接近对手）：±0.001~0.01
  4. 负时间奖励 → 激励高效完成：-0.001/步

❌ 常见错误：
  1. 奖励值过大/过小（建议总episode奖励在[-1, +1]范围）
  2. 奖励相互矛盾（同时奖励进攻和防守）
  3. 稀疏奖励（只有最终结果有奖励，中间全0）
  4. 奖励欺骗（AI找到非预期的"作弊"路径得到奖励）
```

### 7.2 训练不收敛的排查清单

```csharp
/// <summary>
/// 训练诊断工具：检测常见训练问题
/// 在TensorBoard中监控这些指标
/// </summary>
public class TrainingDiagnostic : MonoBehaviour
{
    // 监控这些TensorBoard指标：
    
    // ✅ 正常训练特征：
    //   - cumulative_reward: 持续上升趋势
    //   - episode_length: 前期长后期稳定
    //   - policy_loss: 在0附近小幅波动
    //   - value_loss: 持续下降
    //   - entropy: 前期高（探索），后期适度下降
    
    // ⚠️ 异常特征及解决方案：
    //   - 奖励震荡不收敛 → 降低learning_rate（3e-4 → 1e-4）
    //   - entropy过早降为0 → 增加beta（探索系数）
    //   - policy_loss过大 → 减小epsilon（PPO裁剪参数）
    //   - 训练极慢 → 增加并行环境数量（--num-envs参数）
    //   - 过拟合单一策略 → 启用self_play
}
```

### 7.3 并行环境加速训练

```bash
# 启动并行训练（大幅加速）
# 20个并行环境，训练速度约提升15~18倍
mlagents-learn fighter_config.yaml \
  --run-id=fighter_v2_parallel \
  --num-envs=20 \
  --base-port=5005 \
  --time-scale=20      # 加速物理模拟（不影响AI决策质量）

# 从检查点继续训练
mlagents-learn fighter_config.yaml \
  --run-id=fighter_v2_parallel \
  --resume

# 查看TensorBoard
tensorboard --logdir=results/fighter_v2_parallel
```

---

## 八、最佳实践总结

### 8.1 项目落地路线图

```
Week 1: 环境搭建
  → 安装ML-Agents包（com.unity.ml-agents）
  → 实现简单的CollectObservations + OnActionReceived
  → 验证Heuristic（手控）正常工作

Week 2: 初步训练
  → 设计奖励函数（从简单目标开始）
  → 单机训练，观察TensorBoard
  → 调试观察空间（确保信息充分但不冗余）

Week 3: 课程优化
  → 加入Curriculum Learning渐进难度
  → 启用Self-Play（AI自我对弈）
  → 并行环境加速训练

Week 4: 部署集成
  → 导出ONNX模型（.onnx）
  → 在Unity中加载为NNModel资产
  → 集成难度切换系统
  → 性能优化（推理频率调整）
```

### 8.2 观察空间设计黄金原则

| 原则 | 说明 |
|-----|------|
| 归一化 | 所有观察值归一化到 [-1, 1] 或 [0, 1] |
| 充分性 | AI解决任务所需的所有信息都要包含 |
| 简洁性 | 避免冗余信息，减少维度加速训练 |
| 局部坐标 | 优先使用局部坐标（相对位置），提升泛化能力 |
| 历史信息 | 需要时序信息时，提供1~2步的历史状态 |

### 8.3 奖励函数权重参考

| 奖励类型 | 建议权重范围 | 说明 |
|---------|-----------|------|
| 胜利/完成任务 | ±1.0 | 最终目标，权重最高 |
| 对目标造成影响 | ±0.1~0.5 | 中间里程碑 |
| 方向性引导 | ±0.001~0.01 | 行为塑形，权重要小 |
| 时间惩罚 | -0.0001~-0.001 | 激励高效，权重极小 |
| 存活奖励 | +0.0001~+0.001 | 仅在必要时使用 |

---

## 总结

Unity ML-Agents为游戏AI开发提供了完整的强化学习工具链：

1. **环境设计**：合理设计观察空间（归一化、局部坐标、充分信息）是训练成功的基础
2. **奖励工程**：奖励函数决定AI学习什么，需要精心设计权重和防止奖励欺骗
3. **Self-Play**：让AI与历史版本对战，实现持续进化，避免过拟合固定策略
4. **课程学习**：从简单任务逐步挑战，大幅加快训练效率
5. **部署优化**：根据场景动态调整推理频率，在性能和智能之间取得平衡
6. **监控调优**：TensorBoard是训练过程的必备工具，及时发现并修正训练问题
