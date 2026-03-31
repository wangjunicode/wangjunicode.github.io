---
title: 游戏匹配与房间系统设计：从Matchmaking原理到工程落地
published: 2026-03-31
description: 深入解析多人游戏匹配系统的完整技术体系，涵盖ELO/MMR评分算法、多维度匹配策略、房间管理状态机、弹性服务器分配、反女巫攻击机制，以及基于Mirror/Photon的Unity工程实践，适用于PVP竞技游戏与合作类游戏。
tags: [Unity, 匹配系统, Matchmaking, MMR, 房间系统, 多人游戏, 网络架构, PVP]
category: 网络与多人游戏
draft: false
---

# 游戏匹配与房间系统设计：从 Matchmaking 原理到工程落地

## 前言

多人游戏中，**匹配系统（Matchmaking）**是决定玩家体验的核心基础设施。一个优秀的匹配系统需要在三个维度取得平衡：

- **公平性**：让技术水平相近的玩家对战，避免碾压局
- **速度**：等待时间不超过玩家耐心上限（通常 30~60s）
- **质量**：低延迟、稳定的网络连接

本文将从 ELO/MMR 评分算法出发，到房间状态机设计、服务器弹性分配，完整呈现工业级匹配系统的构建方案。

---

## 一、评分系统：ELO 与 MMR 算法

### 1.1 经典 ELO 算法

ELO 是国际象棋界发明的评分系统，被广泛应用于游戏匹配：

**核心公式：**

```
期望胜率: E_A = 1 / (1 + 10^((R_B - R_A)/400))

分值更新:
R_A' = R_A + K × (S_A - E_A)

其中:
R_A, R_B = 玩家 A/B 当前评分
S_A      = 实际结果（赢=1, 平=0.5, 输=0）
K        = K因子（新手大，老手小）
```

```csharp
using System;

/// <summary>
/// ELO 评分系统实现
/// </summary>
public class EloRatingSystem
{
    // K因子：决定每局分值变动幅度
    // 低段位用大K（变化快），高段位用小K（变化慢，稳定性高）
    public static float GetKFactor(int currentRating, int gamesPlayed)
    {
        if (gamesPlayed < 30)  return 40f; // 新手：大K，快速定位
        if (currentRating >= 2400) return 10f; // 大师级：小K，稳定
        return 20f;                          // 普通：标准K
    }

    /// <summary>
    /// 计算期望胜率
    /// </summary>
    public static float ExpectedScore(float ratingA, float ratingB)
    {
        return 1f / (1f + MathF.Pow(10f, (ratingB - ratingA) / 400f));
    }

    /// <summary>
    /// 更新双方评分（1v1对局）
    /// </summary>
    public static (float newRatingA, float newRatingB) UpdateRatings(
        float ratingA, float ratingB,
        float kA, float kB,
        GameResult result)
    {
        float eA = ExpectedScore(ratingA, ratingB);
        float eB = 1f - eA;  // 期望胜率之和 = 1

        float sA, sB;
        switch (result)
        {
            case GameResult.WinA:  sA = 1f; sB = 0f; break;
            case GameResult.WinB:  sA = 0f; sB = 1f; break;
            default:               sA = 0.5f; sB = 0.5f; break; // 平局
        }

        float newRatingA = ratingA + kA * (sA - eA);
        float newRatingB = ratingB + kB * (sB - eB);

        return (newRatingA, newRatingB);
    }

    /// <summary>
    /// 多人匹配场景的 ELO（团队）：
    /// 将队伍平均分视为单一玩家
    /// </summary>
    public static float[] UpdateTeamRatings(float[] teamA, float[] teamB, GameResult result)
    {
        float avgA = Average(teamA);
        float avgB = Average(teamB);
        float eA   = ExpectedScore(avgA, avgB);

        float sA = result == GameResult.WinA ? 1f : 0f;
        float delta = 20f * (sA - eA); // 固定K=20用于团队场景

        float[] result_ratings = new float[teamA.Length + teamB.Length];
        for (int i = 0; i < teamA.Length; i++)
            result_ratings[i] = teamA[i] + delta;
        for (int i = 0; i < teamB.Length; i++)
            result_ratings[teamA.Length + i] = teamB[i] - delta;

        return result_ratings;
    }

    static float Average(float[] arr)
    {
        float sum = 0;
        foreach (var v in arr) sum += v;
        return sum / arr.Length;
    }
}

public enum GameResult { WinA, WinB, Draw }
```

### 1.2 TrueSkill：微软的多人匹配方案

TrueSkill 用高斯分布表示技能不确定性：每个玩家用 `(μ, σ)` 表示，其中 μ 是技能均值，σ 是不确定性。

```csharp
/// <summary>
/// TrueSkill 简化实现（Bayesian更新）
/// 完整实现参考微软 TrueSkill 论文
/// </summary>
public struct TrueSkillRating
{
    public float Mu;    // 技能均值（初始 25.0）
    public float Sigma; // 技能标准差（初始 8.33）

    // 保守分数：mu - 3*sigma（用于匹配显示）
    public float ConservativeScore => Mu - 3f * Sigma;

    // 初始默认值
    public static TrueSkillRating Default => new TrueSkillRating { Mu = 25f, Sigma = 8.333f };

    public override string ToString() => $"μ={Mu:F1}, σ={Sigma:F2}, Score={ConservativeScore:F1}";
}

public static class TrueSkill
{
    private const float BETA   = 4.1667f;  // 表现方差的一半
    private const float TAU    = 0.0833f;  // 动态因子（防止分数固化）
    private const float DRAW_P = 0.1f;     // 平局概率

    /// <summary>
    /// 更新两个玩家的 TrueSkill（简化版，不含完整的因子图推理）
    /// </summary>
    public static (TrueSkillRating, TrueSkillRating) Update(
        TrueSkillRating a, TrueSkillRating b, bool aWon)
    {
        // 1. 增加不确定性（时间衰减）
        float sigmaA = MathF.Sqrt(a.Sigma * a.Sigma + TAU * TAU);
        float sigmaB = MathF.Sqrt(b.Sigma * b.Sigma + TAU * TAU);

        // 2. 计算合并方差
        float c2 = 2f * BETA * BETA + sigmaA * sigmaA + sigmaB * sigmaB;
        float c  = MathF.Sqrt(c2);

        // 3. 计算更新量
        float muDiff   = aWon ? (a.Mu - b.Mu) / c : (b.Mu - a.Mu) / c;
        float v        = GaussianV(muDiff, DRAW_P / c);
        float w        = GaussianW(muDiff, DRAW_P / c);

        float multiplierA = aWon  ?  1f : -1f;
        float multiplierB = !aWon ?  1f : -1f;

        // 4. 更新均值和方差
        float newMuA    = a.Mu + multiplierA * sigmaA * sigmaA / c * v;
        float newMuB    = b.Mu + multiplierB * sigmaB * sigmaB / c * v;
        float newSigmaA = sigmaA * MathF.Sqrt(1f - sigmaA * sigmaA / c2 * w);
        float newSigmaB = sigmaB * MathF.Sqrt(1f - sigmaB * sigmaB / c2 * w);

        return (
            new TrueSkillRating { Mu = newMuA, Sigma = newSigmaA },
            new TrueSkillRating { Mu = newMuB, Sigma = newSigmaB }
        );
    }

    // 截断高斯函数 v(t,ε)
    static float GaussianV(float t, float epsilon)
    {
        float den = GaussianCDF(t - epsilon) - GaussianCDF(-t - epsilon);
        if (MathF.Abs(den) < 1e-9f) return -t;
        return GaussianPDF(t - epsilon) - GaussianPDF(-t - epsilon) / den;
    }

    // 截断高斯函数 w(t,ε)
    static float GaussianW(float t, float epsilon)
    {
        float v = GaussianV(t, epsilon);
        return v * (v + t - epsilon);
    }

    // 标准正态 PDF
    static float GaussianPDF(float x) =>
        MathF.Exp(-x * x / 2f) / MathF.Sqrt(2f * MathF.PI);

    // 标准正态 CDF（近似）
    static float GaussianCDF(float x)
    {
        const float a = 0.3275911f;
        float t = 1f / (1f + a * MathF.Abs(x));
        float poly = t * (0.254829592f + t * (-0.284496736f + t * (1.421413741f
            + t * (-1.453152027f + t * 1.061405429f))));
        float cdf = 1f - poly * MathF.Exp(-x * x / 2f) / MathF.Sqrt(2f * MathF.PI);
        return x >= 0 ? cdf : 1f - cdf;
    }
}
```

---

## 二、匹配队列系统架构

### 2.1 多维度匹配策略

```csharp
using System;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// 匹配票据：包含玩家信息和匹配条件
/// </summary>
public class MatchTicket
{
    public string   PlayerId      { get; set; }
    public float    MMR           { get; set; }       // 匹配分
    public int      Region        { get; set; }       // 地区（0=亚服, 1=欧服, 2=美服）
    public int      GameMode      { get; set; }       // 游戏模式（0=1v1, 1=5v5, 2=大乱斗）
    public float    Latency       { get; set; }       // 到服务器的延迟（ms）
    public DateTime EnqueueTime   { get; set; }       // 进入队列时间
    public string   SelectedServer { get; set; }      // 已选定的服务器

    // 允许的 MMR 范围（随等待时间扩大）
    public float MMRTolerance => ComputeTolerance();

    float ComputeTolerance()
    {
        // 初始容忍范围 ±100，每等30秒扩大50，最大 ±500
        float waited = (float)(DateTime.UtcNow - EnqueueTime).TotalSeconds;
        return Mathf.Min(100f + (waited / 30f) * 50f, 500f);
    }
}

/// <summary>
/// 匹配器：核心匹配逻辑
/// </summary>
public class MatchmakingService
{
    private readonly List<MatchTicket> _queue = new();
    private readonly object _lock = new object();

    // 配置
    public int PlayersPerMatch = 2;  // 1v1=2, 5v5=10
    public float TickIntervalMs = 500f; // 每500ms运行一次匹配

    public void Enqueue(MatchTicket ticket)
    {
        ticket.EnqueueTime = DateTime.UtcNow;
        lock (_lock)
        {
            _queue.Add(ticket);
        }
        Console.WriteLine($"[Matchmaking] {ticket.PlayerId} 加入队列, MMR={ticket.MMR}");
    }

    public void Dequeue(string playerId)
    {
        lock (_lock)
        {
            _queue.RemoveAll(t => t.PlayerId == playerId);
        }
    }

    /// <summary>
    /// 匹配 Tick：找到最优匹配组
    /// </summary>
    public List<MatchGroup> RunMatchingTick()
    {
        List<MatchGroup> matches = new List<MatchGroup>();

        lock (_lock)
        {
            if (_queue.Count < PlayersPerMatch) return matches;

            // 按 MMR 排序，相近的玩家靠在一起
            var sorted = _queue.OrderBy(t => t.MMR).ToList();

            HashSet<string> matched = new HashSet<string>();

            for (int i = 0; i < sorted.Count; i++)
            {
                if (matched.Contains(sorted[i].PlayerId)) continue;

                MatchTicket anchor = sorted[i];
                List<MatchTicket> group = new List<MatchTicket> { anchor };

                for (int j = i + 1; j < sorted.Count && group.Count < PlayersPerMatch; j++)
                {
                    MatchTicket candidate = sorted[j];
                    if (matched.Contains(candidate.PlayerId)) continue;

                    if (IsCompatible(anchor, candidate))
                    {
                        group.Add(candidate);
                    }
                }

                if (group.Count == PlayersPerMatch)
                {
                    // 找到一组匹配
                    var matchGroup = new MatchGroup
                    {
                        Players = group,
                        MatchId = Guid.NewGuid().ToString("N"),
                        ServerRegion = SelectBestServer(group)
                    };
                    matches.Add(matchGroup);

                    foreach (var t in group)
                    {
                        matched.Add(t.PlayerId);
                        _queue.Remove(t);
                    }
                }
            }
        }

        return matches;
    }

    bool IsCompatible(MatchTicket a, MatchTicket b)
    {
        // 1. 必须在同一地区
        if (a.Region != b.Region) return false;

        // 2. 必须是同一游戏模式
        if (a.GameMode != b.GameMode) return false;

        // 3. MMR 差距在双方容忍范围内
        float mmrDiff = MathF.Abs(a.MMR - b.MMR);
        float tolerance = MathF.Min(a.MMRTolerance, b.MMRTolerance);
        if (mmrDiff > tolerance) return false;

        // 4. 延迟检查（两人到同一服务器的延迟都不能超过150ms）
        if (a.Latency > 150f || b.Latency > 150f) return false;

        return true;
    }

    string SelectBestServer(List<MatchTicket> players)
    {
        // 选择对所有玩家平均延迟最低的服务器
        // 实际实现中会查询各 Region 的服务器列表
        int region = players[0].Region;
        return region switch
        {
            0 => "ap-guangzhou-01",
            1 => "eu-frankfurt-01",
            2 => "us-virginia-01",
            _ => "ap-guangzhou-01"
        };
    }
}

public class MatchGroup
{
    public string              MatchId;
    public List<MatchTicket>   Players;
    public string              ServerRegion;
    public DateTime            CreatedAt = DateTime.UtcNow;
}
```

---

## 三、房间状态机设计

### 3.1 房间生命周期

```
         ┌──────┐
         │ Idle │  未激活/空闲
         └──┬───┘
            │ 收到匹配组
            ▼
       ┌─────────┐
       │ Creating │ 正在申请服务器资源
       └────┬─────┘
            │ 服务器就绪
            ▼
      ┌───────────┐
      │ WaitingAll│ 等待所有玩家连接
      └─────┬─────┘
            │ 所有玩家已准备
            ▼
     ┌───────────────┐
     │   InProgress   │ 游戏进行中
     └───────┬────────┘
             │ 游戏结算
             ▼
      ┌────────────┐
      │ PostGame   │ 结算/上报数据
      └──────┬─────┘
             │ 完成
             ▼
        ┌──────────┐
        │ Destroyed│ 资源已释放
        └──────────┘

特殊状态:
  WaitingAll → PlayerLeft → 取消房间（玩家断线）
  InProgress → PlayerLeft → 重连等待 → InProgress（断线重连）
```

### 3.2 房间状态机实现

```csharp
using System;
using System.Collections.Generic;

public enum RoomState
{
    Idle,
    Creating,
    WaitingAll,
    Countdown,
    InProgress,
    PostGame,
    Destroyed
}

public class GameRoom
{
    public string   RoomId    { get; private set; }
    public RoomState State    { get; private set; }
    public string   ServerIp  { get; private set; }
    public int      ServerPort { get; private set; }

    private readonly Dictionary<string, PlayerSlot> _players = new();
    private readonly List<Action<RoomState, RoomState>> _stateListeners = new();

    private DateTime _stateEnterTime;
    private int  _requiredPlayerCount;
    private float _countdownSeconds = 5f;

    public struct PlayerSlot
    {
        public string PlayerId;
        public bool   IsConnected;
        public bool   IsReady;
        public float  LoadProgress;  // 0~1 加载进度
    }

    public GameRoom(string roomId, List<string> playerIds, string serverIp, int port)
    {
        RoomId      = roomId;
        ServerIp    = serverIp;
        ServerPort  = port;
        _requiredPlayerCount = playerIds.Count;

        foreach (var id in playerIds)
            _players[id] = new PlayerSlot { PlayerId = id };

        TransitionTo(RoomState.WaitingAll);
    }

    void TransitionTo(RoomState newState)
    {
        var oldState = State;
        State        = newState;
        _stateEnterTime = DateTime.UtcNow;

        Console.WriteLine($"[Room {RoomId}] {oldState} → {newState}");

        foreach (var listener in _stateListeners)
            listener(oldState, newState);

        OnEnterState(newState);
    }

    void OnEnterState(RoomState state)
    {
        switch (state)
        {
            case RoomState.WaitingAll:
                // 启动超时计时器（60s内必须全员到齐）
                StartTimeout(60f, () => TransitionTo(RoomState.Destroyed));
                break;

            case RoomState.Countdown:
                // 5秒倒计时
                StartTimeout(_countdownSeconds, () => TransitionTo(RoomState.InProgress));
                break;

            case RoomState.InProgress:
                // 通知游戏服务器正式开始
                NotifyGameStart();
                break;

            case RoomState.PostGame:
                // 上报战报、结算MMR
                ReportGameResult();
                break;
        }
    }

    // ---- 事件入口 ----

    public void OnPlayerConnected(string playerId)
    {
        if (!_players.ContainsKey(playerId)) return;

        var slot = _players[playerId];
        slot.IsConnected = true;
        _players[playerId] = slot;

        Console.WriteLine($"[Room {RoomId}] {playerId} 已连接 ({CountConnected()}/{_requiredPlayerCount})");
        CheckAllConnected();
    }

    public void OnPlayerReady(string playerId)
    {
        if (State != RoomState.WaitingAll && State != RoomState.Countdown) return;

        var slot = _players[playerId];
        slot.IsReady = true;
        _players[playerId] = slot;

        CheckAllReady();
    }

    public void OnPlayerDisconnected(string playerId)
    {
        if (!_players.ContainsKey(playerId)) return;

        var slot = _players[playerId];
        slot.IsConnected = false;
        _players[playerId] = slot;

        if (State == RoomState.WaitingAll || State == RoomState.Countdown)
        {
            // 等待阶段断线：取消倒计时回到等待
            if (State == RoomState.Countdown)
                TransitionTo(RoomState.WaitingAll);
        }
        else if (State == RoomState.InProgress)
        {
            // 游戏中断线：给60秒重连机会
            Console.WriteLine($"[Room {RoomId}] {playerId} 断线，等待重连...");
            StartTimeout(60f, () =>
            {
                // 超时未重连：判负/踢出
                if (!_players[playerId].IsConnected)
                {
                    Console.WriteLine($"[Room {RoomId}] {playerId} 重连超时，判负");
                    OnGameOver(loserPlayerId: playerId);
                }
            });
        }
    }

    public void OnGameOver(string loserPlayerId = null)
    {
        if (State != RoomState.InProgress) return;
        TransitionTo(RoomState.PostGame);
    }

    // ---- 内部逻辑 ----

    void CheckAllConnected()
    {
        if (CountConnected() == _requiredPlayerCount)
            TransitionTo(RoomState.Countdown);
    }

    void CheckAllReady()
    {
        if (_players.Values.Count(p => p.IsReady) == _requiredPlayerCount)
            if (State != RoomState.Countdown)
                TransitionTo(RoomState.Countdown);
    }

    int CountConnected() => _players.Values.Count(p => p.IsConnected);

    void StartTimeout(float seconds, Action callback)
    {
        // 实际项目中用 System.Threading.Timer 或游戏框架的协程
        Console.WriteLine($"[Room {RoomId}] 超时计时器 {seconds}s");
        // 省略具体实现...
    }

    void NotifyGameStart()
    {
        Console.WriteLine($"[Room {RoomId}] 游戏开始！服务器: {ServerIp}:{ServerPort}");
    }

    void ReportGameResult()
    {
        Console.WriteLine($"[Room {RoomId}] 上报战报...");
        // 更新 MMR，保存战绩到数据库
        TransitionTo(RoomState.Destroyed);
    }

    public void OnStateChanged(Action<RoomState, RoomState> listener)
        => _stateListeners.Add(listener);
}
```

---

## 四、Unity 客户端：Mirror 网络框架集成

### 4.1 完整的客户端匹配流程

```csharp
using UnityEngine;
using Mirror;
using System.Collections;

/// <summary>
/// 客户端匹配管理器
/// 负责：加入队列 → 等待匹配 → 连接服务器 → 进入游戏
/// </summary>
public class MatchmakingClient : MonoBehaviour
{
    [Header("服务器配置")]
    public string matchmakingServerUrl = "https://match.mygame.com/api";

    [Header("UI 引用")]
    public MatchmakingUI ui;

    // 状态机
    public enum ClientState
    {
        Idle, Searching, Found, Connecting, InGame
    }

    public ClientState State { get; private set; }

    private string _ticketId;
    private float  _searchStartTime;
    private Coroutine _pollCoroutine;

    // --- 公开接口 ---

    public void StartSearch(int gameMode)
    {
        if (State != ClientState.Idle) return;
        TransitionTo(ClientState.Searching);
        StartCoroutine(DoStartSearch(gameMode));
    }

    public void CancelSearch()
    {
        if (State != ClientState.Searching) return;
        StopCoroutine(_pollCoroutine);
        StartCoroutine(DoCancelSearch());
        TransitionTo(ClientState.Idle);
    }

    // --- 协程实现 ---

    IEnumerator DoStartSearch(int gameMode)
    {
        _searchStartTime = Time.time;
        ui.ShowSearching();

        // 1. 测量到各服务器的延迟
        float latency = 0f;
        yield return StartCoroutine(MeasureLatency("ap-guangzhou-01",
            result => latency = result));

        // 2. 向匹配服务器提交票据
        var request = new MatchRequest
        {
            PlayerId = PlayerProfile.LocalPlayerId,
            MMR      = PlayerProfile.MMR,
            GameMode = gameMode,
            Region   = DetectRegion(),
            Latency  = latency
        };

        string json = JsonUtility.ToJson(request);
        using var www = new UnityEngine.Networking.UnityWebRequest(
            $"{matchmakingServerUrl}/tickets", "POST");
        www.uploadHandler   = new UnityEngine.Networking.UploadHandlerRaw(
            System.Text.Encoding.UTF8.GetBytes(json));
        www.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
        www.SetRequestHeader("Content-Type", "application/json");
        www.SetRequestHeader("Authorization", $"Bearer {PlayerProfile.AuthToken}");

        yield return www.SendWebRequest();

        if (www.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
        {
            Debug.LogError($"匹配请求失败: {www.error}");
            TransitionTo(ClientState.Idle);
            ui.ShowError("网络错误，请重试");
            yield break;
        }

        var response = JsonUtility.FromJson<TicketResponse>(www.downloadHandler.text);
        _ticketId = response.ticketId;

        // 3. 开始轮询匹配结果
        _pollCoroutine = StartCoroutine(PollForMatch());
    }

    IEnumerator PollForMatch()
    {
        while (State == ClientState.Searching)
        {
            yield return new WaitForSeconds(2f);

            // 更新等待时间 UI
            float waited = Time.time - _searchStartTime;
            ui.UpdateWaitTime(waited);

            // 查询票据状态
            using var www = UnityEngine.Networking.UnityWebRequest.Get(
                $"{matchmakingServerUrl}/tickets/{_ticketId}");
            www.SetRequestHeader("Authorization", $"Bearer {PlayerProfile.AuthToken}");

            yield return www.SendWebRequest();

            if (www.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
                continue;

            var status = JsonUtility.FromJson<TicketStatus>(www.downloadHandler.text);

            if (status.state == "MATCHED")
            {
                TransitionTo(ClientState.Found);
                yield return StartCoroutine(ConnectToGameServer(status.serverIp, status.serverPort));
                yield break;
            }
        }
    }

    IEnumerator ConnectToGameServer(string ip, int port)
    {
        TransitionTo(ClientState.Connecting);
        ui.ShowConnecting(ip, port);

        // 通过 Mirror 连接游戏服务器
        NetworkManager.singleton.networkAddress = ip;
        Transport.active.port = (ushort)port;

        NetworkManager.singleton.StartClient();

        // 等待连接结果（最多10秒）
        float timeout = 10f;
        while (!NetworkClient.isConnected && timeout > 0f)
        {
            yield return null;
            timeout -= Time.deltaTime;
        }

        if (NetworkClient.isConnected)
        {
            TransitionTo(ClientState.InGame);
            ui.HideMatchmakingUI();
        }
        else
        {
            Debug.LogError("连接游戏服务器超时");
            NetworkManager.singleton.StopClient();
            TransitionTo(ClientState.Idle);
            ui.ShowError("连接服务器失败，请重试");
        }
    }

    IEnumerator MeasureLatency(string server, System.Action<float> callback)
    {
        // Ping 服务器3次取平均值
        float total = 0f;
        int count = 3;
        for (int i = 0; i < count; i++)
        {
            var ping = new Ping(server);
            yield return new WaitWhile(() => !ping.isDone);
            total += ping.time;
            ping.DestroyPing();
        }
        callback(total / count);
    }

    IEnumerator DoCancelSearch()
    {
        if (string.IsNullOrEmpty(_ticketId)) yield break;

        using var www = new UnityEngine.Networking.UnityWebRequest(
            $"{matchmakingServerUrl}/tickets/{_ticketId}", "DELETE");
        www.SetRequestHeader("Authorization", $"Bearer {PlayerProfile.AuthToken}");
        yield return www.SendWebRequest();

        _ticketId = null;
    }

    int DetectRegion()
    {
        // 根据玩家 IP 或时区猜测地区，实际项目可通过后台 GeoIP 确定
        return TimeZoneInfo.Local.BaseUtcOffset.Hours switch
        {
            >= 8 and <= 9   => 0,  // 亚服
            >= 0 and <= 2   => 1,  // 欧服
            <= -4 and >= -8 => 2,  // 美服
            _ => 0
        };
    }

    void TransitionTo(ClientState newState)
    {
        Debug.Log($"[Matchmaking] {State} → {newState}");
        State = newState;
    }
}

// ---- 数据结构 ----

[Serializable]
public class MatchRequest
{
    public string PlayerId;
    public float  MMR;
    public int    GameMode;
    public int    Region;
    public float  Latency;
}

[Serializable]
public class TicketResponse
{
    public string ticketId;
    public string state;
}

[Serializable]
public class TicketStatus
{
    public string ticketId;
    public string state;        // SEARCHING / MATCHED / CANCELLED
    public string serverIp;
    public int    serverPort;
    public string matchId;
}
```

---

## 五、服务端：弹性游戏服务器分配

### 5.1 基于 Agones（Kubernetes）的服务器管理

```yaml
# agones-gameserver.yaml
apiVersion: agones.dev/v1
kind: GameServer
metadata:
  name: game-server-template
spec:
  ports:
  - name: default
    portPolicy: Dynamic       # 动态分配端口（20000-25000）
    containerPort: 7777
    protocol: UDP

  health:
    initialDelaySeconds: 30
    periodSeconds: 5
    failureThreshold: 3

  template:
    spec:
      containers:
      - name: game-server
        image: myregistry/game-server:latest
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2"
            memory: "1Gi"
        env:
        - name: MAX_PLAYERS
          value: "10"
        - name: GAME_MODE
          value: "ranked_5v5"
```

```csharp
// 服务端：通知 Agones 游戏状态
using Agones;

public class GameServerController : MonoBehaviour
{
    private AgonesSDK _agones;

    async void Start()
    {
        _agones = new AgonesSDK();

        // 1. 通知 Agones 服务器已就绪接受玩家
        await _agones.Ready();
        Debug.Log("[Server] 已就绪，等待玩家连接");

        // 2. 启动健康心跳
        InvokeRepeating(nameof(SendHealthPing), 2f, 2f);
    }

    // 游戏开始时标记为"已分配"，防止被重复分配
    public async void OnGameStart()
    {
        await _agones.Allocate();
        Debug.Log("[Server] 游戏开始，服务器已标记为占用");
    }

    // 游戏结束后通知 Agones 关闭实例（Kubernetes 自动回收 Pod）
    public async void OnGameEnd()
    {
        await _agones.Shutdown();
        Debug.Log("[Server] 游戏结束，服务器正在关闭");
    }

    async void SendHealthPing()
    {
        await _agones.Health();
    }
}
```

---

## 六、反作弊与公平性保障

### 6.1 防止匹配刷分（女巫攻击）

```csharp
/// <summary>
/// 匹配反作弊：检测异常匹配行为
/// </summary>
public static class MatchAntiCheat
{
    // 连续放弃局数阈值（超过则临时封禁匹配）
    private const int ABANDON_THRESHOLD = 3;
    private const float ABANDON_WINDOW_HOURS = 1f;

    // 分享账号检测：同一设备频繁切换账号
    private const int MAX_ACCOUNTS_PER_DEVICE = 3;

    public static MatchValidationResult ValidateTicket(MatchTicket ticket, PlayerRecord record)
    {
        // 1. 检查是否在惩罚期内
        if (record.BannedUntil > DateTime.UtcNow)
        {
            return new MatchValidationResult
            {
                IsValid = false,
                Reason  = $"账号处于匹配惩罚中，解除时间: {record.BannedUntil:HH:mm}"
            };
        }

        // 2. 检测频繁放弃
        int recentAbandons = record.MatchHistory
            .Where(m => m.EndTime > DateTime.UtcNow.AddHours(-ABANDON_WINDOW_HOURS)
                     && m.Result == MatchResult.Abandoned)
            .Count();

        if (recentAbandons >= ABANDON_THRESHOLD)
        {
            // 自动触发惩罚
            record.BannedUntil = DateTime.UtcNow.AddMinutes(15 * recentAbandons);
            return new MatchValidationResult
            {
                IsValid = false,
                Reason  = $"频繁放弃，{record.BannedUntil:HH:mm} 后可重新匹配"
            };
        }

        // 3. MMR 异常检测（短时间内 MMR 变化过大）
        if (record.MatchHistory.Count >= 5)
        {
            var recent = record.MatchHistory.TakeLast(5).ToList();
            float mmrBefore = recent.First().MMRBefore;
            float mmrAfter  = record.CurrentMMR;
            float mmrDelta  = MathF.Abs(mmrAfter - mmrBefore);

            if (mmrDelta > 500f) // 5局内涨跌超过500分：可疑
            {
                // 触发人工审核，不直接封禁
                TriggerManualReview(ticket.PlayerId, "MMR异常波动");
            }
        }

        return new MatchValidationResult { IsValid = true };
    }

    static void TriggerManualReview(string playerId, string reason)
    {
        // 推送到后台审核队列
        Console.WriteLine($"[反作弊] {playerId} 触发人工审核: {reason}");
    }
}

public struct MatchValidationResult
{
    public bool   IsValid;
    public string Reason;
}

public class PlayerRecord
{
    public string         PlayerId;
    public float          CurrentMMR;
    public DateTime       BannedUntil;
    public List<MatchHistory> MatchHistory;
}

public struct MatchHistory
{
    public DateTime    EndTime;
    public MatchResult Result;
    public float       MMRBefore;
    public float       MMRAfter;
}

public enum MatchResult { Win, Loss, Draw, Abandoned }
```

---

## 七、性能与规模化设计

### 7.1 匹配系统架构图

```
玩家客户端
    │ HTTP/WebSocket
    ▼
[匹配网关 / Load Balancer]
    │
    ├── [匹配服务集群] ←→ [Redis 队列]
    │       │                   │
    │       ▼                   ▼
    │   [MMR 计算服务]    [在线玩家状态]
    │
    ├── [服务器分配服务] ←→ [Agones / K8s]
    │       │
    │       ▼
    │   [游戏服务器池]
    │
    └── [战报/结算服务] ←→ [MySQL / TiDB]
```

### 7.2 关键性能指标

| 指标 | 目标值 | 实现手段 |
|---|---|---|
| 匹配等待时间（热门时段） | < 15s | 扩大 MMR 容忍范围 + 扩容 |
| 匹配等待时间（非热门） | < 60s | 跨服匹配 + Bot 补位 |
| 服务器分配延迟 | < 3s | 预热服务器池 |
| 匹配系统可用性 | 99.9% | 多可用区部署 + 熔断降级 |
| 单匹配服务实例 QPS | 5000+/s | Redis Lua 原子操作 |

---

## 八、最佳实践总结

### ✅ 核心设计原则

1. **MMR 渐进宽松**：等待时间越长，MMR 容忍范围越大，平衡公平性与速度
2. **预热服务器池**：维持一定数量的热待机服务器，避免玩家等待服务器启动
3. **客户端乐观 UI**：匹配过程中显示动态进度动画，降低玩家主观等待感
4. **断线重连保护**：给游戏中断线的玩家 60s 重连窗口，不立即判负
5. **反作弊分层处理**：轻微违规（放弃）自动惩罚；严重异常（MMR 异常）人工审核

### ❌ 常见设计失误

1. **过于严格的 MMR 匹配**：在低峰时期会导致永久匹配不到对手
2. **服务器按需创建**：每次匹配都动态创建 Pod 会有 30~60s 延迟，用户无法接受
3. **客户端信任匹配结果**：服务端必须验证票据签名，防止伪造匹配结果跳过队列
4. **单点 Redis**：匹配队列的 Redis 必须做集群/哨兵，单点故障会影响全部玩家匹配
5. **不区分地区的匹配**：跨洲匹配延迟 200ms+ 会严重影响游戏体验

---

## 参考资料

- [Google Open Match - 开源匹配框架](https://open-match.dev/)
- [Agones - Kubernetes Game Server Hosting](https://agones.dev/)
- [TrueSkill: A Bayesian Skill Rating System - Microsoft Research](https://www.microsoft.com/en-us/research/publication/trueskilltm/)
- [Riot Games Matchmaking 深度解析](https://technology.riotgames.com/news/matchmaking-real-world)
- [Mirror Networking - Unity 多人网络框架](https://mirror-networking.gitbook.io/)
