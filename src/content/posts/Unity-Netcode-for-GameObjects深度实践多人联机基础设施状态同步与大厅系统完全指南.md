---
title: Unity Netcode for GameObjects深度实践：多人联机基础设施、状态同步与大厅系统完全指南
published: 2026-04-14
description: 深度解析Unity官方多人联机解决方案 Netcode for GameObjects（NGO），涵盖NetworkObject生命周期、NetworkVariable状态同步、ServerRpc/ClientRpc、NetworkTransform、大厅房间系统设计及与Unity Gaming Services集成的完整工程方案。
tags: [Unity, 多人联机, Netcode, 网络编程, 游戏开发]
category: 网络编程
draft: false
---

# Unity Netcode for GameObjects深度实践：多人联机基础设施、状态同步与大厅系统完全指南

## 1. Netcode for GameObjects 概述

Unity Netcode for GameObjects（NGO）是 Unity 官方提供的多人游戏联机框架，相比社区方案（Mirror、FishNet）具有以下特点：

- **原生集成**：与 Unity Editor、GameObject 生命周期深度集成
- **UGS 生态**：无缝对接 Unity Relay、Unity Lobby、Unity Authentication
- **NetworkObject 模型**：基于 GameObject 的网络同步抽象
- **NetworkVariable**：自动序列化与差量同步的网络变量
- **双向 RPC**：ServerRpc 和 ClientRpc 实现可靠命令传输

### 与其他框架的对比

| 特性 | NGO | Mirror | FishNet |
|------|-----|--------|---------|
| 官方维护 | ✅ | ❌ | ❌ |
| UGS 集成 | ✅ 原生 | ❌ 需手动 | ❌ 需手动 |
| 性能 | 中等 | 较高 | 高 |
| 学习曲线 | 低 | 中 | 中 |
| 适用规模 | 小中型多人 | 中大型 | 中大型 |
| 开源 | ✅ | ✅ | ✅ |

## 2. 核心组件与生命周期

### 2.1 NetworkManager 配置

```csharp
// NetworkManager 是 NGO 的核心单例，负责管理网络连接状态
public class GameNetworkManager : MonoBehaviour
{
    [SerializeField] private NetworkManager networkManager;
    
    [Header("连接配置")]
    [SerializeField] private string serverAddress = "127.0.0.1";
    [SerializeField] private ushort serverPort = 7777;
    
    private void Start()
    {
        // 订阅网络事件
        networkManager.OnClientConnectedCallback += OnClientConnected;
        networkManager.OnClientDisconnectCallback += OnClientDisconnected;
        networkManager.OnServerStarted += OnServerStarted;
    }
    
    /// <summary>
    /// 作为 Host 启动（同时充当 Server 和 Client）
    /// </summary>
    public void StartHost()
    {
        // 配置传输层
        var transport = networkManager.GetComponent<UnityTransport>();
        transport.SetConnectionData(serverAddress, serverPort);
        
        networkManager.StartHost();
    }
    
    /// <summary>
    /// 作为纯 Server 启动（无客户端逻辑）
    /// </summary>
    public void StartServer()
    {
        var transport = networkManager.GetComponent<UnityTransport>();
        transport.SetConnectionData(serverAddress, serverPort);
        
        networkManager.StartServer();
    }
    
    /// <summary>
    /// 作为 Client 连接到 Server
    /// </summary>
    public void StartClient(string address = null, ushort port = 0)
    {
        var transport = networkManager.GetComponent<UnityTransport>();
        transport.SetConnectionData(
            address ?? serverAddress, 
            port > 0 ? port : serverPort
        );
        
        networkManager.StartClient();
    }
    
    /// <summary>
    /// 使用 Unity Relay 启动（用于 NAT 穿透）
    /// </summary>
    public async Task StartHostWithRelay(string relayJoinCode = null)
    {
        // 创建 Relay 分配
        var allocation = await RelayService.Instance.CreateAllocationAsync(maxConnections: 4);
        string joinCode = await RelayService.Instance.GetJoinCodeAsync(allocation.AllocationId);
        
        // 设置 Relay 传输数据
        var transport = networkManager.GetComponent<UnityTransport>();
        transport.SetRelayServerData(
            allocation.RelayServer.IpV4, 
            (ushort)allocation.RelayServer.Port,
            allocation.AllocationIdBytes,
            allocation.Key,
            allocation.ConnectionData
        );
        
        Debug.Log($"Relay JoinCode: {joinCode}");
        networkManager.StartHost();
    }
    
    public async Task JoinWithRelay(string joinCode)
    {
        var joinAlloc = await RelayService.Instance.JoinAllocationAsync(joinCode);
        
        var transport = networkManager.GetComponent<UnityTransport>();
        transport.SetRelayServerData(
            joinAlloc.RelayServer.IpV4,
            (ushort)joinAlloc.RelayServer.Port,
            joinAlloc.AllocationIdBytes,
            joinAlloc.Key,
            joinAlloc.ConnectionData,
            joinAlloc.HostConnectionData
        );
        
        networkManager.StartClient();
    }
    
    private void OnClientConnected(ulong clientId)
    {
        Debug.Log($"[Network] Client 连接: {clientId}");
    }
    
    private void OnClientDisconnected(ulong clientId)
    {
        Debug.Log($"[Network] Client 断开: {clientId}");
    }
    
    private void OnServerStarted()
    {
        Debug.Log("[Network] Server 已启动");
    }
}
```

### 2.2 NetworkObject 生命周期

```csharp
// 所有需要在网络中同步的 GameObject 必须挂载 NetworkObject 组件
// 继承 NetworkBehaviour 来编写网络同步逻辑
public class NetworkPlayer : NetworkBehaviour
{
    // NetworkVariable 自动在所有客户端同步
    // ReadPerm: 读取权限 (Everyone / Owner / Server)
    // WritePerm: 写入权限 (Server / Owner)
    private NetworkVariable<int> health = new(
        100,
        NetworkVariableReadPermission.Everyone,
        NetworkVariableWritePermission.Server
    );
    
    private NetworkVariable<Vector3> networkPosition = new(
        Vector3.zero,
        NetworkVariableReadPermission.Everyone,
        NetworkVariableWritePermission.Owner    // 只有拥有者可以写入位置
    );
    
    private NetworkVariable<NetworkString> playerName = new(
        default,
        NetworkVariableReadPermission.Everyone,
        NetworkVariableWritePermission.Owner
    );
    
    // NGO 生命周期回调
    public override void OnNetworkSpawn()
    {
        // 在网络上生成时调用（Server 和 Client 都会调用）
        health.OnValueChanged += OnHealthChanged;
        
        if (IsOwner)
        {
            // 仅在本地拥有者初始化输入、相机等
            InitializeLocalPlayer();
        }
        
        if (IsServer)
        {
            // 仅在服务器初始化权威逻辑
            health.Value = 100;
        }
    }
    
    public override void OnNetworkDespawn()
    {
        // 网络销毁时清理事件
        health.OnValueChanged -= OnHealthChanged;
    }
    
    private void OnHealthChanged(int previousValue, int newValue)
    {
        // 血量变化时更新 UI
        Debug.Log($"[{OwnerClientId}] 血量: {previousValue} -> {newValue}");
        UpdateHealthUI(newValue);
    }
    
    private void Update()
    {
        if (!IsOwner) return;  // 只有拥有者处理输入
        
        HandleMovement();
    }
    
    private void HandleMovement()
    {
        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        
        Vector3 move = new Vector3(h, 0, v) * 5f * Time.deltaTime;
        transform.position += move;
    }
    
    private void InitializeLocalPlayer()
    {
        Camera.main.GetComponent<CameraFollow>().SetTarget(transform);
        GetComponent<PlayerInput>().enabled = true;
    }
    
    private void UpdateHealthUI(int hp) { /* ... */ }
}

// NGO 不支持直接序列化 string 类型到 NetworkVariable，需要包装
public struct NetworkString : INetworkSerializable, IEquatable<NetworkString>
{
    private FixedString64Bytes value;
    
    public NetworkString(string str) => value = str;
    public override string ToString() => value.ToString();
    
    public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
    {
        serializer.SerializeValue(ref value);
    }
    
    public bool Equals(NetworkString other) => value.Equals(other.value);
}
```

## 3. RPC 机制详解

```csharp
public class NetworkCombat : NetworkBehaviour
{
    [Header("战斗参数")]
    [SerializeField] private float attackRange = 2f;
    [SerializeField] private int attackDamage = 20;
    
    // ======== ServerRpc：客户端 → 服务器 ========
    // 客户端调用，在服务器上执行
    [ServerRpc(RequireOwnership = true)]  // RequireOwnership: 只有拥有者才能调用
    public void RequestAttackServerRpc(ulong targetClientId, ServerRpcParams rpcParams = default)
    {
        // 此代码只在服务器上执行
        ulong senderId = rpcParams.Receive.SenderClientId;
        
        // 服务器验证攻击合法性
        if (!ValidateAttack(senderId, targetClientId))
        {
            Debug.Log($"[Server] 非法攻击请求，来自 {senderId}");
            return;
        }
        
        // 执行伤害逻辑
        var targetPlayer = GetPlayerByClientId(targetClientId);
        if (targetPlayer != null)
        {
            targetPlayer.TakeDamage(attackDamage);
            
            // 通知所有客户端播放攻击动画
            BroadcastAttackEffectClientRpc(senderId, targetClientId);
        }
    }
    
    private bool ValidateAttack(ulong attackerId, ulong targetId)
    {
        var attacker = GetPlayerByClientId(attackerId);
        var target = GetPlayerByClientId(targetId);
        
        if (attacker == null || target == null) return false;
        
        float dist = Vector3.Distance(attacker.transform.position, target.transform.position);
        return dist <= attackRange;
    }
    
    // ======== ClientRpc：服务器 → 所有/指定客户端 ========
    [ClientRpc]
    private void BroadcastAttackEffectClientRpc(ulong attackerId, ulong targetId)
    {
        // 此代码在所有客户端上执行
        Debug.Log($"[Client] 播放攻击特效: {attackerId} -> {targetId}");
        PlayAttackVFX(attackerId, targetId);
    }
    
    // 只发给指定客户端
    [ClientRpc]
    private void SendPrivateMessageClientRpc(string message, ClientRpcParams clientRpcParams = default)
    {
        // 只有被指定的客户端会执行
        Debug.Log($"[私信] {message}");
    }
    
    // 调用时指定目标客户端
    public void NotifySpecificClient(ulong targetClientId, string message)
    {
        if (!IsServer) return;
        
        var clientRpcParams = new ClientRpcParams
        {
            Send = new ClientRpcSendParams
            {
                TargetClientIds = new[] { targetClientId }
            }
        };
        
        SendPrivateMessageClientRpc(message, clientRpcParams);
    }
    
    private void PlayAttackVFX(ulong attackerId, ulong targetId) { /* ... */ }
    
    private NetworkPlayer GetPlayerByClientId(ulong clientId)
    {
        foreach (var client in NetworkManager.Singleton.ConnectedClientsList)
        {
            if (client.ClientId == clientId)
                return client.PlayerObject?.GetComponent<NetworkPlayer>();
        }
        return null;
    }
}
```

## 4. NetworkTransform 与自定义移动同步

```csharp
// NGO 内置 NetworkTransform，但对于格斗/竞速类游戏建议自定义同步
public class SmoothNetworkTransform : NetworkBehaviour
{
    [Header("同步配置")]
    [SerializeField] private float positionThreshold = 0.05f;  // 位置变化阈值
    [SerializeField] private float rotationThreshold = 1f;     // 旋转变化阈值（度）
    [SerializeField] private float interpolationSpeed = 15f;    // 插值速度
    
    // 服务器权威位置（所有客户端只读）
    private NetworkVariable<Vector3> networkPos = new(
        Vector3.zero,
        NetworkVariableReadPermission.Everyone,
        NetworkVariableWritePermission.Server
    );
    private NetworkVariable<float> networkYaw = new(
        0f,
        NetworkVariableReadPermission.Everyone,
        NetworkVariableWritePermission.Server
    );
    
    // 本地预测位置（拥有者客户端用）
    private Vector3 localPredictPos;
    private float localPredictYaw;
    
    // 上一次同步的位置（用于差量检测）
    private Vector3 lastSyncedPos;
    private float lastSyncedYaw;
    
    private void Update()
    {
        if (IsOwner)
        {
            // 本地物理直接移动（立即反馈）
            HandleLocalMovement();
            
            // 节流上报给服务器
            TrySyncToServer();
        }
        else
        {
            // 非拥有者：平滑插值到网络位置
            SmoothInterpolate();
        }
    }
    
    private void HandleLocalMovement()
    {
        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        
        Vector3 move = new Vector3(h, 0, v) * 5f * Time.deltaTime;
        transform.position += move;
        
        if (move.sqrMagnitude > 0.001f)
        {
            float targetYaw = Mathf.Atan2(move.x, move.z) * Mathf.Rad2Deg;
            transform.rotation = Quaternion.Slerp(transform.rotation,
                Quaternion.Euler(0, targetYaw, 0), Time.deltaTime * 10f);
        }
    }
    
    private void TrySyncToServer()
    {
        bool posChanged = Vector3.Distance(transform.position, lastSyncedPos) > positionThreshold;
        bool rotChanged = Mathf.Abs(transform.eulerAngles.y - lastSyncedYaw) > rotationThreshold;
        
        if (posChanged || rotChanged)
        {
            lastSyncedPos = transform.position;
            lastSyncedYaw = transform.eulerAngles.y;
            SyncMovementServerRpc(transform.position, transform.eulerAngles.y);
        }
    }
    
    [ServerRpc]
    private void SyncMovementServerRpc(Vector3 position, float yaw,
        ServerRpcParams rpcParams = default)
    {
        // 服务器验证移动合法性（防作弊）
        float maxMovePerFrame = 10f;
        if (Vector3.Distance(networkPos.Value, position) > maxMovePerFrame)
        {
            Debug.LogWarning($"[Server] 可疑移动速度，Client: {rpcParams.Receive.SenderClientId}");
            // 可以选择拒绝并将客户端位置重置
            RejectMovementClientRpc(networkPos.Value, 
                new ClientRpcParams 
                { 
                    Send = new ClientRpcSendParams 
                    { 
                        TargetClientIds = new[] { rpcParams.Receive.SenderClientId } 
                    } 
                });
            return;
        }
        
        networkPos.Value = position;
        networkYaw.Value = yaw;
    }
    
    [ClientRpc]
    private void RejectMovementClientRpc(Vector3 correctPos, ClientRpcParams rpcParams = default)
    {
        // 服务器拒绝移动，强制修正客户端位置
        transform.position = correctPos;
    }
    
    private void SmoothInterpolate()
    {
        transform.position = Vector3.Lerp(
            transform.position, 
            networkPos.Value, 
            Time.deltaTime * interpolationSpeed
        );
        
        transform.rotation = Quaternion.Slerp(
            transform.rotation,
            Quaternion.Euler(0, networkYaw.Value, 0),
            Time.deltaTime * interpolationSpeed
        );
    }
}
```

## 5. 大厅系统设计（Unity Lobby 集成）

```csharp
public class LobbyManager : MonoBehaviour
{
    public static LobbyManager Instance { get; private set; }
    
    private Lobby currentLobby;
    private string localPlayerId;
    private ILobbyEvents lobbyEvents;
    
    // 大厅轮询（Unity Lobby 目前不支持实时推送，需要轮询）
    private float pollInterval = 1.5f;
    private float pollTimer;
    
    // 事件
    public event Action<Lobby> OnLobbyUpdated;
    public event Action<string> OnPlayerJoined;
    public event Action<string> OnPlayerLeft;
    public event Action OnGameStarted;
    
    private async void Start()
    {
        Instance = this;
        
        // 初始化 Unity Services
        await UnityServices.InitializeAsync();
        
        // 匿名认证
        if (!AuthenticationService.Instance.IsSignedIn)
        {
            await AuthenticationService.Instance.SignInAnonymouslyAsync();
        }
        
        localPlayerId = AuthenticationService.Instance.PlayerId;
        Debug.Log($"[Lobby] 已认证，PlayerId: {localPlayerId}");
    }
    
    private void Update()
    {
        // 定期轮询大厅状态更新
        if (currentLobby != null)
        {
            pollTimer -= Time.deltaTime;
            if (pollTimer <= 0)
            {
                pollTimer = pollInterval;
                PollLobbyUpdates();
            }
        }
    }
    
    /// <summary>
    /// 创建大厅
    /// </summary>
    public async Task<string> CreateLobby(string lobbyName, int maxPlayers, bool isPrivate = false)
    {
        try
        {
            var options = new CreateLobbyOptions
            {
                IsPrivate = isPrivate,
                Player = CreatePlayerData(),
                Data = new Dictionary<string, DataObject>
                {
                    ["GameMode"] = new DataObject(DataObject.VisibilityOptions.Public, "Deathmatch"),
                    ["MapName"] = new DataObject(DataObject.VisibilityOptions.Public, "Forest"),
                    ["Status"] = new DataObject(DataObject.VisibilityOptions.Public, "Waiting"),
                    // Relay Join Code 在游戏开始后写入
                    ["RelayCode"] = new DataObject(DataObject.VisibilityOptions.Member, "")
                }
            };
            
            currentLobby = await LobbyService.Instance.CreateLobbyAsync(lobbyName, maxPlayers, options);
            
            Debug.Log($"[Lobby] 创建成功: {currentLobby.Name} (Code: {currentLobby.LobbyCode})");
            
            // 开始心跳（防止大厅因无活动被删除）
            StartCoroutine(LobbyHeartbeatCoroutine());
            
            return currentLobby.LobbyCode;
        }
        catch (LobbyServiceException e)
        {
            Debug.LogError($"[Lobby] 创建失败: {e.Message}");
            return null;
        }
    }
    
    /// <summary>
    /// 通过 Code 加入大厅
    /// </summary>
    public async Task<bool> JoinLobbyByCode(string lobbyCode)
    {
        try
        {
            var options = new JoinLobbyByCodeOptions
            {
                Player = CreatePlayerData()
            };
            
            currentLobby = await LobbyService.Instance.JoinLobbyByCodeAsync(lobbyCode, options);
            Debug.Log($"[Lobby] 加入成功: {currentLobby.Name}");
            return true;
        }
        catch (LobbyServiceException e)
        {
            Debug.LogError($"[Lobby] 加入失败: {e.Message} (Code: {e.Reason})");
            return false;
        }
    }
    
    /// <summary>
    /// 快速加入（匹配空余大厅）
    /// </summary>
    public async Task<bool> QuickJoin(string gameMode = "Deathmatch")
    {
        try
        {
            var options = new QuickJoinLobbyOptions
            {
                Player = CreatePlayerData(),
                Filter = new List<QueryFilter>
                {
                    new(QueryFilter.FieldOptions.AvailableSlots, "0", QueryFilter.OpOptions.GT),
                    new(QueryFilter.FieldOptions.S1, gameMode, QueryFilter.OpOptions.EQ)
                }
            };
            
            currentLobby = await LobbyService.Instance.QuickJoinLobbyAsync(options);
            Debug.Log($"[Lobby] 快速加入: {currentLobby.Name}");
            return true;
        }
        catch (LobbyServiceException e)
        {
            Debug.LogError($"[Lobby] 快速加入失败: {e.Message}");
            return false;
        }
    }
    
    /// <summary>
    /// 更新玩家准备状态
    /// </summary>
    public async Task SetReady(bool isReady)
    {
        if (currentLobby == null) return;
        
        try
        {
            var options = new UpdatePlayerOptions
            {
                Data = new Dictionary<string, PlayerDataObject>
                {
                    ["IsReady"] = new PlayerDataObject(
                        PlayerDataObject.VisibilityOptions.Member, 
                        isReady.ToString()
                    )
                }
            };
            
            currentLobby = await LobbyService.Instance.UpdatePlayerAsync(
                currentLobby.Id, localPlayerId, options);
        }
        catch (LobbyServiceException e)
        {
            Debug.LogError($"[Lobby] 更新玩家状态失败: {e.Message}");
        }
    }
    
    /// <summary>
    /// 房主开始游戏（写入 Relay Code）
    /// </summary>
    public async Task StartGame()
    {
        if (currentLobby == null || currentLobby.HostId != localPlayerId) return;
        
        // 1. 创建 Relay 分配
        var allocation = await RelayService.Instance.CreateAllocationAsync(currentLobby.MaxPlayers - 1);
        string relayCode = await RelayService.Instance.GetJoinCodeAsync(allocation.AllocationId);
        
        // 2. 将 Relay Code 写入大厅（供其他玩家连接）
        var options = new UpdateLobbyOptions
        {
            Data = new Dictionary<string, DataObject>
            {
                ["Status"] = new DataObject(DataObject.VisibilityOptions.Public, "InGame"),
                ["RelayCode"] = new DataObject(DataObject.VisibilityOptions.Member, relayCode)
            }
        };
        
        currentLobby = await LobbyService.Instance.UpdateLobbyAsync(currentLobby.Id, options);
        
        // 3. Host 以 Relay 方式启动
        var transport = NetworkManager.Singleton.GetComponent<UnityTransport>();
        transport.SetRelayServerData(
            allocation.RelayServer.IpV4,
            (ushort)allocation.RelayServer.Port,
            allocation.AllocationIdBytes,
            allocation.Key,
            allocation.ConnectionData
        );
        
        NetworkManager.Singleton.StartHost();
        Debug.Log($"[Lobby] 游戏已开始，RelayCode: {relayCode}");
    }
    
    private async void PollLobbyUpdates()
    {
        if (currentLobby == null) return;
        
        try
        {
            var updatedLobby = await LobbyService.Instance.GetLobbyAsync(currentLobby.Id);
            
            // 检测玩家变化
            DetectPlayerChanges(currentLobby, updatedLobby);
            
            currentLobby = updatedLobby;
            OnLobbyUpdated?.Invoke(currentLobby);
            
            // 检查游戏是否已开始（非房主自动加入）
            if (currentLobby.HostId != localPlayerId && 
                currentLobby.Data.TryGetValue("Status", out var status) &&
                status.Value == "InGame")
            {
                await JoinGameAsClient();
            }
        }
        catch (LobbyServiceException e)
        {
            Debug.LogWarning($"[Lobby] 轮询失败: {e.Message}");
        }
    }
    
    private async Task JoinGameAsClient()
    {
        if (!currentLobby.Data.TryGetValue("RelayCode", out var relayCodeData)) return;
        
        string relayCode = relayCodeData.Value;
        if (string.IsNullOrEmpty(relayCode)) return;
        
        var joinAlloc = await RelayService.Instance.JoinAllocationAsync(relayCode);
        
        var transport = NetworkManager.Singleton.GetComponent<UnityTransport>();
        transport.SetRelayServerData(
            joinAlloc.RelayServer.IpV4,
            (ushort)joinAlloc.RelayServer.Port,
            joinAlloc.AllocationIdBytes,
            joinAlloc.Key,
            joinAlloc.ConnectionData,
            joinAlloc.HostConnectionData
        );
        
        NetworkManager.Singleton.StartClient();
        OnGameStarted?.Invoke();
    }
    
    private void DetectPlayerChanges(Lobby oldLobby, Lobby newLobby)
    {
        var oldIds = new HashSet<string>(oldLobby.Players.Select(p => p.Id));
        var newIds = new HashSet<string>(newLobby.Players.Select(p => p.Id));
        
        foreach (var id in newIds.Except(oldIds))
            OnPlayerJoined?.Invoke(id);
        
        foreach (var id in oldIds.Except(newIds))
            OnPlayerLeft?.Invoke(id);
    }
    
    private IEnumerator LobbyHeartbeatCoroutine()
    {
        while (currentLobby != null)
        {
            yield return new WaitForSeconds(15f);
            
            if (currentLobby != null && currentLobby.HostId == localPlayerId)
            {
                LobbyService.Instance.SendHeartbeatPingAsync(currentLobby.Id)
                    .ContinueWith(t => {
                        if (t.IsFaulted)
                            Debug.LogWarning("[Lobby] 心跳失败");
                    });
            }
        }
    }
    
    private Player CreatePlayerData()
    {
        return new Player
        {
            Data = new Dictionary<string, PlayerDataObject>
            {
                ["PlayerName"] = new PlayerDataObject(
                    PlayerDataObject.VisibilityOptions.Member,
                    $"Player_{localPlayerId[..4]}"
                ),
                ["IsReady"] = new PlayerDataObject(
                    PlayerDataObject.VisibilityOptions.Member,
                    "False"
                ),
                ["AvatarIndex"] = new PlayerDataObject(
                    PlayerDataObject.VisibilityOptions.Member,
                    "0"
                )
            }
        };
    }
    
    public async Task LeaveLobby()
    {
        if (currentLobby == null) return;
        
        try
        {
            await LobbyService.Instance.RemovePlayerAsync(currentLobby.Id, localPlayerId);
            currentLobby = null;
        }
        catch (LobbyServiceException e)
        {
            Debug.LogError($"[Lobby] 离开失败: {e.Message}");
        }
    }
}
```

## 6. 自定义 NetworkObject 生成管理

```csharp
public class NetworkSpawnManager : NetworkBehaviour
{
    [Header("预制体配置")]
    [SerializeField] private NetworkObject playerPrefab;
    [SerializeField] private Transform[] spawnPoints;
    
    // 玩家实例映射表（服务器端维护）
    private Dictionary<ulong, NetworkObject> playerObjects = new();
    
    public override void OnNetworkSpawn()
    {
        if (!IsServer) return;
        
        NetworkManager.OnClientConnectedCallback += SpawnPlayerForClient;
        NetworkManager.OnClientDisconnectCallback += DespawnPlayerForClient;
    }
    
    private void SpawnPlayerForClient(ulong clientId)
    {
        // 分配出生点（循环使用）
        int spawnIndex = (int)(clientId % (ulong)spawnPoints.Length);
        Transform spawnPoint = spawnPoints[spawnIndex];
        
        // 生成玩家对象（服务器生成后自动同步到所有客户端）
        var playerObj = Instantiate(playerPrefab, spawnPoint.position, spawnPoint.rotation);
        playerObj.SpawnAsPlayerObject(clientId, destroyWithScene: true);
        
        playerObjects[clientId] = playerObj;
        
        Debug.Log($"[SpawnManager] 为 Client {clientId} 生成玩家对象");
    }
    
    private void DespawnPlayerForClient(ulong clientId)
    {
        if (playerObjects.TryGetValue(clientId, out var playerObj))
        {
            playerObj.Despawn(destroy: true);
            playerObjects.Remove(clientId);
        }
    }
    
    /// <summary>
    /// 在指定位置生成场景物体（如掉落道具）
    /// </summary>
    [ServerRpc(RequireOwnership = false)]
    public void SpawnItemServerRpc(Vector3 position, int itemId)
    {
        // 只有服务器才能调用 Spawn
        // 在此处做反作弊验证...
        var itemPrefab = GetItemPrefab(itemId);
        var item = Instantiate(itemPrefab, position, Quaternion.identity);
        item.Spawn(destroyWithScene: true);
    }
    
    private NetworkObject GetItemPrefab(int itemId)
    {
        // 从注册表获取预制体
        return null;
    }
}
```

## 7. 网络调试工具

```csharp
#if UNITY_EDITOR || DEVELOPMENT_BUILD
public class NetworkDebugHUD : MonoBehaviour
{
    private NetworkManager nm;
    private GUIStyle labelStyle;
    
    private void Start()
    {
        nm = NetworkManager.Singleton;
        labelStyle = new GUIStyle
        {
            fontSize = 14,
            normal = { textColor = Color.white }
        };
    }
    
    private void OnGUI()
    {
        if (nm == null) return;
        
        GUILayout.BeginArea(new Rect(10, 10, 300, 400));
        GUILayout.BeginVertical("box");
        
        GUILayout.Label($"== Network Debug ==", labelStyle);
        GUILayout.Label($"IsHost: {nm.IsHost}", labelStyle);
        GUILayout.Label($"IsServer: {nm.IsServer}", labelStyle);
        GUILayout.Label($"IsClient: {nm.IsClient}", labelStyle);
        GUILayout.Label($"LocalClientId: {nm.LocalClientId}", labelStyle);
        GUILayout.Label($"Connected Clients: {nm.ConnectedClients.Count}", labelStyle);
        GUILayout.Label($"Time: {nm.NetworkTickSystem?.LocalTime.Time:F2}s", labelStyle);
        GUILayout.Label($"Tick: {nm.NetworkTickSystem?.LocalTime.Tick}", labelStyle);
        
        if (nm.IsServer)
        {
            GUILayout.Label("--- 连接的客户端 ---", labelStyle);
            foreach (var client in nm.ConnectedClientsList)
            {
                GUILayout.Label($"  Client {client.ClientId}", labelStyle);
            }
        }
        
        GUILayout.EndVertical();
        GUILayout.EndArea();
    }
}
#endif
```

## 8. 性能优化与最佳实践

### 8.1 NetworkVariable 优化

```csharp
// ❌ 错误：高频变化的数据不应用 NetworkVariable
// NetworkVariable 每次变化都会触发网络消息
private NetworkVariable<float> playerPositionX = new NetworkVariable<float>();

// ✅ 正确：位置使用自定义 RPC 节流同步
// 或使用内置 NetworkTransform 并配置插值

// ✅ NetworkVariable 适合低频状态变化
private NetworkVariable<PlayerState> gameState = new NetworkVariable<PlayerState>();
private NetworkVariable<int> score = new NetworkVariable<int>();
private NetworkVariable<bool> isAlive = new NetworkVariable<bool>();

public enum PlayerState : byte
{
    Idle, Moving, Attacking, Dead
}
```

### 8.2 消息优化

```csharp
// 批量同步多个数值（减少 RPC 调用次数）
[System.Serializable]
public struct PlayerSnapshot : INetworkSerializable
{
    public Vector3 position;
    public float yaw;
    public byte health;        // 使用 byte 而非 int 节省带宽
    public byte state;
    
    public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
    {
        serializer.SerializeValue(ref position);
        serializer.SerializeValue(ref yaw);
        serializer.SerializeValue(ref health);
        serializer.SerializeValue(ref state);
    }
}

// 使用紧凑的量化压缩
public struct QuantizedPosition : INetworkSerializable
{
    // 将 float 坐标量化为 short（精度 0.01m，范围 ±320m）
    private short x, y, z;
    
    public Vector3 ToVector3() => new Vector3(x * 0.01f, y * 0.01f, z * 0.01f);
    
    public static QuantizedPosition FromVector3(Vector3 v) => new QuantizedPosition
    {
        x = (short)(v.x * 100),
        y = (short)(v.y * 100),
        z = (short)(v.z * 100)
    };
    
    public void NetworkSerialize<T>(BufferSerializer<T> serializer) where T : IReaderWriter
    {
        serializer.SerializeValue(ref x);
        serializer.SerializeValue(ref y);
        serializer.SerializeValue(ref z);
    }
}
```

## 9. 最佳实践总结

### 架构原则

1. **服务器权威**：所有游戏状态变更必须通过服务器验证，客户端只做预测和渲染
2. **最小化网络消息**：使用阈值过滤，只在状态真正改变时发送网络消息
3. **NetworkVariable vs RPC**：持久状态用 NetworkVariable（自动同步给新加入者），即时事件用 RPC

### 安全性

4. **服务器验证一切**：ServerRpc 中永远不相信客户端传入的数据，做距离/速度/合法性校验
5. **权限控制**：敏感数据设置合适的 ReadPermission/WritePermission，不需要所有人可读的数据不要设为 Everyone

### 性能

6. **节流 RPC**：高频操作（如移动）用节流或只在变化超过阈值时发送
7. **数据压缩**：自定义 INetworkSerializable 使用 short/byte 压缩坐标、方向等数值
8. **合批同步**：多个低频变化的字段合并为一个结构体一起同步

### UGS 集成

9. **Relay 用于 NAT 穿透**：不要依赖玩家开放端口，始终使用 Unity Relay 中继
10. **Lobby 心跳**：房主必须每 15-20 秒发送心跳，防止大厅因超时被删除
11. **大厅轮询优化**：轮询间隔不要太短（官方限制 1秒/次），合理使用 Lobby Events 替代轮询
12. **离开时清理**：玩家退出时调用 `LeaveLobby()` 和 `NetworkManager.Shutdown()`，避免僵尸连接
