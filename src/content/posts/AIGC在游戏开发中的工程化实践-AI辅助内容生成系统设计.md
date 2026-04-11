---
title: AIGC在游戏开发中的工程化实践：AI辅助内容生成系统设计
published: 2026-04-11
description: 深度探讨AIGC（AI生成内容）在游戏客户端工程中的实际应用：运行时LLM集成、AI对话NPC系统、程序化纹理生成、AI辅助关卡叙事，以及本地大模型推断与云端API的架构选型与工程落地。
tags: [AIGC, LLM, AI生成内容, NPC对话, 程序化生成, Unity, 游戏开发]
category: 游戏AI
draft: false
---

# AIGC在游戏开发中的工程化实践：AI辅助内容生成系统设计

## 一、AIGC与游戏开发的结合点

### 1.1 AIGC在游戏中的应用分层

AIGC（AI Generated Content）在游戏中的应用可以分为三层：

```
┌─────────────────────────────────────────────────────┐
│                    创作工具层                          │
│  Midjourney/SD生成概念图 | Copilot辅助编码 | 剧情撰写  │
├─────────────────────────────────────────────────────┤
│                    编辑器工具层                        │
│  AI关卡布局建议 | 自动化测试生成 | 资产批量处理         │
├─────────────────────────────────────────────────────┤
│                    运行时内容层                        │
│  动态NPC对话 | 程序化任务生成 | 个性化叙事 | 自适应AI  │
└─────────────────────────────────────────────────────┘
```

### 1.2 当前主流技术路线

| 技术方向 | 代表方案 | 适用场景 |
|---------|---------|---------|
| 云端LLM API | OpenAI GPT-4o, Claude | 联网游戏NPC对话 |
| 本地小模型 | Llama 3.1 8B, Gemma 2B | 离线游戏, 隐私敏感 |
| 稳定扩散 | Stable Diffusion, SDXL | 运行时纹理/贴图生成 |
| 专用模型 | Inworld AI, Convai | 游戏NPC专用 |
| 混合方案 | 本地意图 + 云端生成 | 控制成本与质量 |

---

## 二、运行时LLM集成架构

### 2.1 系统架构设计

```
游戏客户端 AIGC 架构：

┌─────────────────────────────────────────────────┐
│                  游戏逻辑层                        │
│  玩家输入 → 意图识别 → NPC对话管理器 → 对话系统    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              AIGC服务层                           │
│  ┌──────────────┐  ┌─────────────────────────┐   │
│  │  本地意图分类  │  │    LLM请求队列管理器     │   │
│  │  (ONNX模型)  │  │  限流/重试/缓存/降级      │   │
│  └──────────────┘  └────────────┬────────────┘   │
└───────────────────────────────┬─┴────────────────┘
                                │
           ┌────────────────────┼──────────────────┐
           │                    │                  │
    ┌──────▼──────┐    ┌────────▼──────┐   ┌──────▼──────┐
    │ OpenAI API  │    │  本地Ollama   │   │  Inworld AI │
    │  (云端)     │    │  (离线备用)   │   │  (专用NPC)  │
    └─────────────┘    └───────────────┘   └─────────────┘
```

### 2.2 LLM请求管理器实现

```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// LLM请求管理器：处理队列、限流、重试、缓存
/// </summary>
public class LLMRequestManager : MonoBehaviour
{
    private static LLMRequestManager _instance;
    public static LLMRequestManager Instance => _instance;

    [Header("API配置")]
    [SerializeField] private string apiEndpoint = "https://api.openai.com/v1/chat/completions";
    [SerializeField] private string apiKey;
    [SerializeField] private string modelName = "gpt-4o-mini";
    
    [Header("限流配置")]
    [SerializeField] private int maxRequestsPerMinute = 60;
    [SerializeField] private int maxConcurrentRequests = 5;
    [SerializeField] private int maxRetries = 3;
    [SerializeField] private float retryDelaySeconds = 1f;
    
    [Header("缓存配置")]
    [SerializeField] private int maxCacheSize = 200;
    [SerializeField] private float cacheExpirySeconds = 300f;

    // 请求队列
    private Queue<LLMRequest> requestQueue = new Queue<LLMRequest>();
    private SemaphoreSlim concurrencyLimiter;
    
    // 简单LRU缓存
    private Dictionary<string, CacheEntry> responseCache = new Dictionary<string, CacheEntry>();
    
    // 限流
    private Queue<float> requestTimestamps = new Queue<float>();

    void Awake()
    {
        if (_instance != null && _instance != this)
        {
            Destroy(gameObject);
            return;
        }
        _instance = this;
        DontDestroyOnLoad(gameObject);
        
        concurrencyLimiter = new SemaphoreSlim(maxConcurrentRequests, maxConcurrentRequests);
    }

    /// <summary>
    /// 发送LLM请求（带缓存、限流、重试）
    /// </summary>
    public async Task<string> SendAsync(
        string systemPrompt, 
        string userMessage,
        float temperature = 0.7f,
        int maxTokens = 200,
        CancellationToken ct = default)
    {
        // 1. 检查缓存
        string cacheKey = GenerateCacheKey(systemPrompt, userMessage);
        if (TryGetFromCache(cacheKey, out string cachedResponse))
        {
            Debug.Log("[LLM] Cache hit");
            return cachedResponse;
        }

        // 2. 等待并发限制
        await concurrencyLimiter.WaitAsync(ct);
        
        try
        {
            // 3. 检查限流
            await WaitForRateLimit(ct);
            
            // 4. 执行请求（带重试）
            string response = await ExecuteWithRetry(
                systemPrompt, userMessage, temperature, maxTokens, ct
            );
            
            // 5. 写入缓存
            SetCache(cacheKey, response);
            
            return response;
        }
        finally
        {
            concurrencyLimiter.Release();
        }
    }

    private async Task WaitForRateLimit(CancellationToken ct)
    {
        while (true)
        {
            float now = Time.realtimeSinceStartup;
            
            // 清除60秒前的记录
            while (requestTimestamps.Count > 0 && 
                   now - requestTimestamps.Peek() > 60f)
            {
                requestTimestamps.Dequeue();
            }
            
            if (requestTimestamps.Count < maxRequestsPerMinute)
            {
                requestTimestamps.Enqueue(now);
                break;
            }
            
            // 等待最早的请求过期
            float waitTime = 60f - (now - requestTimestamps.Peek());
            await Task.Delay(TimeSpan.FromSeconds(waitTime + 0.1f), ct);
        }
    }

    private async Task<string> ExecuteWithRetry(
        string systemPrompt, string userMessage,
        float temperature, int maxTokens, CancellationToken ct)
    {
        Exception lastException = null;
        
        for (int attempt = 0; attempt < maxRetries; attempt++)
        {
            try
            {
                return await CallLLMAPI(systemPrompt, userMessage, temperature, maxTokens, ct);
            }
            catch (OperationCanceledException)
            {
                throw; // 不重试取消操作
            }
            catch (Exception ex)
            {
                lastException = ex;
                Debug.LogWarning($"[LLM] Attempt {attempt + 1} failed: {ex.Message}");
                
                if (attempt < maxRetries - 1)
                {
                    float delay = retryDelaySeconds * Mathf.Pow(2, attempt); // 指数退避
                    await Task.Delay(TimeSpan.FromSeconds(delay), ct);
                }
            }
        }
        
        throw new Exception($"LLM request failed after {maxRetries} retries", lastException);
    }

    private async Task<string> CallLLMAPI(
        string systemPrompt, string userMessage,
        float temperature, int maxTokens, CancellationToken ct)
    {
        var requestBody = new
        {
            model = modelName,
            messages = new[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user",   content = userMessage  }
            },
            temperature,
            max_tokens = maxTokens
        };
        
        string json = JsonUtility.ToJson(requestBody);
        // 注：实际项目推荐使用Newtonsoft.Json
        
        using var request = new UnityWebRequest(apiEndpoint, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(json);
        request.uploadHandler   = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {apiKey}");
        
        var operation = request.SendWebRequest();
        while (!operation.isDone && !ct.IsCancellationRequested)
        {
            await Task.Yield();
        }
        
        ct.ThrowIfCancellationRequested();
        
        if (request.result != UnityWebRequest.Result.Success)
        {
            throw new Exception($"HTTP {request.responseCode}: {request.error}");
        }
        
        return ParseResponse(request.downloadHandler.text);
    }

    private string ParseResponse(string jsonResponse)
    {
        // 解析OpenAI格式的响应
        // 实际项目中使用JsonConvert.DeserializeObject
        int start = jsonResponse.IndexOf("\"content\":\"") + 11;
        int end   = jsonResponse.IndexOf("\"", start);
        return start > 10 ? jsonResponse.Substring(start, end - start) : string.Empty;
    }

    // 缓存相关
    private string GenerateCacheKey(string system, string user)
    {
        int hash = HashCode.Combine(system, user);
        return hash.ToString();
    }

    private bool TryGetFromCache(string key, out string value)
    {
        if (responseCache.TryGetValue(key, out var entry))
        {
            if (Time.realtimeSinceStartup - entry.Timestamp < cacheExpirySeconds)
            {
                value = entry.Value;
                return true;
            }
            responseCache.Remove(key);
        }
        value = null;
        return false;
    }

    private void SetCache(string key, string value)
    {
        if (responseCache.Count >= maxCacheSize)
        {
            // 简单淘汰：删除最旧的条目
            string oldest = null;
            float oldestTime = float.MaxValue;
            foreach (var kv in responseCache)
            {
                if (kv.Value.Timestamp < oldestTime)
                {
                    oldest = kv.Key;
                    oldestTime = kv.Value.Timestamp;
                }
            }
            if (oldest != null) responseCache.Remove(oldest);
        }
        
        responseCache[key] = new CacheEntry
        {
            Value = value,
            Timestamp = Time.realtimeSinceStartup
        };
    }

    private struct CacheEntry
    {
        public string Value;
        public float  Timestamp;
    }
}

public class LLMRequest
{
    public string SystemPrompt;
    public string UserMessage;
    public Action<string> OnComplete;
    public Action<Exception> OnError;
}
```

---

## 三、AI驱动的NPC对话系统

### 3.1 NPC角色档案系统

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// NPC AI档案：定义NPC的性格、背景、对话风格
/// </summary>
[CreateAssetMenu(menuName = "AIGC/NPC Profile")]
public class NPCProfile : ScriptableObject
{
    [Header("角色基本信息")]
    public string npcName;
    [TextArea(3, 5)]
    public string personality;   // 性格描述
    [TextArea(3, 5)]
    public string background;    // 背景故事
    [TextArea(2, 3)]
    public string speechStyle;   // 说话风格
    
    [Header("知识边界")]
    [TextArea(2, 4)]
    public string knownFacts;    // NPC已知的游戏世界信息
    [TextArea(1, 2)]
    public string secretInfo;    // 不应透露的秘密
    
    [Header("情感状态")]
    [Range(0, 1)] public float friendliness = 0.5f;  // 对玩家的好感度
    [Range(0, 1)] public float tension = 0f;          // 当前紧张程度
    
    [Header("对话约束")]
    public int maxResponseTokens = 150;
    [Range(0.3f, 1.0f)] public float temperature = 0.8f;
    public List<string> forbiddenTopics = new List<string>();

    /// <summary>
    /// 生成系统提示词
    /// </summary>
    public string BuildSystemPrompt(GameContext context)
    {
        return $@"你是{npcName}，{personality}
背景：{background}
说话风格：{speechStyle}
当前世界状态：{context.WorldState}
你知道的信息：{knownFacts}
你对玩家的态度：{'友好' if friendliness > 0.6f else (friendliness > 0.3f ? '中立' : '警惕')}

规则：
- 始终以第一人称角色扮演，不要跳出角色
- 回复不超过3句话，简洁自然
- 不要透露：{secretInfo}
- 禁止讨论的话题：{string.Join(", ", forbiddenTopics)}
- 当前对话情绪：{(tension > 0.5f ? "紧张" : "平静")}";
    }
}

[System.Serializable]
public class GameContext
{
    public string WorldState;      // 当前世界状态（战争/和平/危机）
    public string PlayerReputation; // 玩家声望
    public string Location;         // 当前地点
    public string TimeOfDay;        // 游戏内时间
}
```

### 3.2 NPC对话控制器

```csharp
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

/// <summary>
/// NPC对话控制器：管理与玩家的实时AI对话
/// </summary>
public class AINPCDialogueController : MonoBehaviour
{
    [Header("NPC配置")]
    [SerializeField] private NPCProfile profile;
    [SerializeField] private GameContext gameContext;

    [Header("对话历史")]
    [SerializeField] private int maxHistoryTurns = 5;
    
    [Header("降级策略")]
    [SerializeField] private List<string> fallbackResponses = new List<string>
    {
        "（若有所思地沉默着）",
        "让我想想……",
        "这个问题很有趣。",
        "你问的这个，我需要好好考虑。"
    };

    private List<(string Role, string Content)> conversationHistory 
        = new List<(string, string)>();
    
    private CancellationTokenSource cts;
    private bool isGenerating = false;
    
    // 流式输出事件
    public event Action<string> OnResponseChunk;
    public event Action<string> OnResponseComplete;
    public event Action<string> OnResponseError;

    /// <summary>
    /// 玩家说话，触发NPC的AI回复
    /// </summary>
    public async Task<string> PlayerSpeakAsync(string playerInput)
    {
        if (isGenerating)
        {
            CancelCurrentGeneration();
        }
        
        isGenerating = true;
        cts = new CancellationTokenSource();
        
        // 添加玩家消息到历史
        conversationHistory.Add(("user", playerInput));
        
        // 保持历史长度
        while (conversationHistory.Count > maxHistoryTurns * 2)
        {
            conversationHistory.RemoveAt(0);
        }
        
        try
        {
            // 构建包含对话历史的提示
            string contextualPrompt = BuildContextualPrompt(playerInput);
            string systemPrompt     = profile.BuildSystemPrompt(gameContext);
            
            string response = await LLMRequestManager.Instance.SendAsync(
                systemPrompt,
                contextualPrompt,
                profile.temperature,
                profile.maxResponseTokens,
                cts.Token
            );
            
            // 后处理：过滤不当内容
            response = PostProcessResponse(response);
            
            // 添加NPC回复到历史
            conversationHistory.Add(("assistant", response));
            
            // 更新情感状态
            UpdateEmotionalState(playerInput, response);
            
            OnResponseComplete?.Invoke(response);
            return response;
        }
        catch (OperationCanceledException)
        {
            Debug.Log("[NPC] Response generation cancelled");
            return string.Empty;
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[NPC] AI response failed: {ex.Message}, using fallback");
            
            string fallback = GetFallbackResponse();
            OnResponseError?.Invoke(fallback);
            return fallback;
        }
        finally
        {
            isGenerating = false;
        }
    }

    private string BuildContextualPrompt(string currentInput)
    {
        if (conversationHistory.Count <= 1)
            return currentInput;
        
        // 简单地将最近几轮对话附加到当前输入作为上下文
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("之前的对话：");
        
        int start = Mathf.Max(0, conversationHistory.Count - maxHistoryTurns * 2 - 1);
        for (int i = start; i < conversationHistory.Count - 1; i++)
        {
            var (role, content) = conversationHistory[i];
            string speaker = role == "user" ? "玩家" : profile.npcName;
            sb.AppendLine($"{speaker}: {content}");
        }
        
        sb.AppendLine($"\n玩家现在说：{currentInput}");
        return sb.ToString();
    }

    private string PostProcessResponse(string response)
    {
        if (string.IsNullOrEmpty(response)) return GetFallbackResponse();
        
        // 移除可能的roleplay越界标记
        response = response.Replace("[作为AI]", "")
                           .Replace("[OOC]", "")
                           .Replace("作为一个AI，", "")
                           .Trim();
        
        // 限制最大长度
        if (response.Length > 500)
            response = response.Substring(0, 500) + "……";
        
        return response;
    }

    private void UpdateEmotionalState(string playerInput, string npcResponse)
    {
        // 简单情感分析（实际项目可用专门的情感分析模型）
        bool isPositive = playerInput.Contains("谢谢") || playerInput.Contains("帮助");
        bool isNegative = playerInput.Contains("蠢") || playerInput.Contains("废物");
        
        if (isPositive)
            profile.friendliness = Mathf.Clamp01(profile.friendliness + 0.05f);
        else if (isNegative)
            profile.friendliness = Mathf.Clamp01(profile.friendliness - 0.1f);
    }

    private string GetFallbackResponse()
    {
        return fallbackResponses[Random.Range(0, fallbackResponses.Count)];
    }

    private void CancelCurrentGeneration()
    {
        cts?.Cancel();
        cts?.Dispose();
        isGenerating = false;
    }

    void OnDestroy()
    {
        CancelCurrentGeneration();
    }
}
```

---

## 四、AI辅助程序化任务生成

### 4.1 任务生成架构

```csharp
/// <summary>
/// AI程序化任务生成器：基于玩家状态生成个性化任务
/// </summary>
public class AIQuestGenerator : MonoBehaviour
{
    [Header("生成配置")]
    [SerializeField] private int questPoolSize = 20;
    [SerializeField] private bool preGenerate = true;

    // 预生成的任务池，避免玩家等待
    private Queue<GeneratedQuest> questPool = new Queue<GeneratedQuest>();
    private bool isGenerating = false;

    [System.Serializable]
    public class GeneratedQuest
    {
        public string Title;
        public string Description;
        public string Objective;
        public string RewardDescription;
        public QuestDifficulty Difficulty;
        public QuestType Type;
    }

    public enum QuestDifficulty { Easy, Normal, Hard, Epic }
    public enum QuestType { Fetch, Kill, Explore, Escort, Craft }

    void Start()
    {
        if (preGenerate)
        {
            _ = PreGenerateQuestPool();
        }
    }

    public async Task PreGenerateQuestPool()
    {
        if (isGenerating) return;
        isGenerating = true;
        
        // 获取当前游戏状态
        var playerState = GetPlayerState();
        
        int batchSize = questPoolSize - questPool.Count;
        var tasks = new List<Task<GeneratedQuest>>();
        
        for (int i = 0; i < batchSize; i++)
        {
            tasks.Add(GenerateSingleQuestAsync(playerState));
        }
        
        var results = await Task.WhenAll(tasks);
        foreach (var quest in results)
        {
            if (quest != null)
                questPool.Enqueue(quest);
        }
        
        Debug.Log($"[QuestGen] Generated {questPool.Count} quests");
        isGenerating = false;
    }

    public async Task<GeneratedQuest> GetNextQuestAsync()
    {
        if (questPool.Count > 0)
        {
            var quest = questPool.Dequeue();
            
            // 异步补充池子
            if (questPool.Count < questPoolSize / 2)
            {
                _ = PreGenerateQuestPool();
            }
            
            return quest;
        }
        
        // 池子为空，实时生成
        return await GenerateSingleQuestAsync(GetPlayerState());
    }

    private async Task<GeneratedQuest> GenerateSingleQuestAsync(PlayerState state)
    {
        string prompt = $@"为等级{state.Level}的玩家在{state.CurrentRegion}地区生成一个游戏任务。
玩家职业：{state.Class}
玩家当前目标：{state.CurrentGoal}
世界事件：{state.WorldEvent}

以JSON格式输出，字段：title, description, objective, reward, difficulty(easy/normal/hard/epic), type(fetch/kill/explore/escort/craft)
只输出JSON，不要其他内容。";

        try
        {
            string response = await LLMRequestManager.Instance.SendAsync(
                "你是一个游戏任务设计师，专门设计有趣的RPG任务。回复只包含JSON。",
                prompt,
                temperature: 1.0f,
                maxTokens: 300
            );
            
            return ParseQuestFromJson(response);
        }
        catch
        {
            return GenerateFallbackQuest(state);
        }
    }

    private GeneratedQuest ParseQuestFromJson(string json)
    {
        // 实际项目使用 JsonConvert.DeserializeObject<GeneratedQuest>
        // 此处简化处理
        try
        {
            return new GeneratedQuest
            {
                Title = ExtractJsonField(json, "title"),
                Description = ExtractJsonField(json, "description"),
                Objective = ExtractJsonField(json, "objective"),
                RewardDescription = ExtractJsonField(json, "reward"),
                Difficulty = QuestDifficulty.Normal,
                Type = QuestType.Kill
            };
        }
        catch
        {
            return null;
        }
    }

    private string ExtractJsonField(string json, string field)
    {
        string key = $"\"{field}\":\"";
        int start = json.IndexOf(key);
        if (start < 0) return "未知";
        start += key.Length;
        int end = json.IndexOf("\"", start);
        return end > start ? json.Substring(start, end - start) : "未知";
    }

    private GeneratedQuest GenerateFallbackQuest(PlayerState state)
    {
        // 降级：使用模板生成
        string[] targets = { "哥布林", "亡灵骑士", "巨龙" };
        string target = targets[Random.Range(0, targets.Length)];
        
        return new GeneratedQuest
        {
            Title = $"消灭{target}的威胁",
            Description = $"在{state.CurrentRegion}，{target}开始骚扰村民。",
            Objective = $"击败5只{target}",
            RewardDescription = "经验值 + 金币",
            Difficulty = QuestDifficulty.Normal,
            Type = QuestType.Kill
        };
    }

    private PlayerState GetPlayerState()
    {
        // 实际从游戏状态系统获取
        return new PlayerState
        {
            Level = 15,
            Class = "法师",
            CurrentRegion = "幽暗森林",
            CurrentGoal = "寻找失落的遗迹",
            WorldEvent = "黑暗军团正在集结"
        };
    }
}

[System.Serializable]
public class PlayerState
{
    public int Level;
    public string Class;
    public string CurrentRegion;
    public string CurrentGoal;
    public string WorldEvent;
}
```

---

## 五、本地轻量模型推断

### 5.1 使用 Ollama 本地部署

对于不适合云端API的场景（隐私、离线、成本控制），可以本地部署小参数量模型：

```csharp
/// <summary>
/// Ollama本地LLM适配器：离线模式的AI能力提供者
/// </summary>
public class OllamaLLMAdapter : MonoBehaviour
{
    [Header("Ollama 配置")]
    [SerializeField] private string ollamaEndpoint = "http://localhost:11434/api/generate";
    [SerializeField] private string modelName = "llama3.1:8b"; // 或 gemma2:2b（更轻量）
    [SerializeField] private bool streamResponse = true;

    /// <summary>
    /// 调用本地Ollama模型（流式输出）
    /// </summary>
    public async IAsyncEnumerable<string> GenerateStreamAsync(
        string prompt,
        float temperature = 0.7f,
        [System.Runtime.CompilerServices.EnumeratorCancellation] 
        CancellationToken ct = default)
    {
        var requestBody = new OllamaRequest
        {
            model = modelName,
            prompt = prompt,
            stream = true,
            options = new OllamaOptions { temperature = temperature }
        };
        
        string json = JsonUtility.ToJson(requestBody);
        
        using var request = new UnityWebRequest(ollamaEndpoint, "POST");
        request.uploadHandler   = new UploadHandlerRaw(
            System.Text.Encoding.UTF8.GetBytes(json)
        );
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        
        var op = request.SendWebRequest();
        
        int lastProcessed = 0;
        
        while (!op.isDone && !ct.IsCancellationRequested)
        {
            await Task.Yield();
            
            // 处理流式响应（每行是一个JSON对象）
            string currentData = request.downloadHandler.text;
            
            while (lastProcessed < currentData.Length)
            {
                int newlineIdx = currentData.IndexOf('\n', lastProcessed);
                if (newlineIdx < 0) break;
                
                string line = currentData.Substring(lastProcessed, newlineIdx - lastProcessed);
                lastProcessed = newlineIdx + 1;
                
                if (string.IsNullOrEmpty(line)) continue;
                
                // 解析流式token
                string token = ParseOllamaChunk(line);
                if (!string.IsNullOrEmpty(token))
                    yield return token;
            }
        }
        
        ct.ThrowIfCancellationRequested();
    }

    private string ParseOllamaChunk(string line)
    {
        try
        {
            // Ollama流式响应格式：{"model":"...","response":"token","done":false}
            int start = line.IndexOf("\"response\":\"") + 12;
            int end   = line.IndexOf("\"", start);
            if (start > 11 && end > start)
            {
                string token = line.Substring(start, end - start);
                return token.Replace("\\n", "\n").Replace("\\t", "\t");
            }
        }
        catch { }
        return string.Empty;
    }

    [System.Serializable]
    private class OllamaRequest
    {
        public string model;
        public string prompt;
        public bool stream;
        public OllamaOptions options;
    }

    [System.Serializable]
    private class OllamaOptions
    {
        public float temperature;
    }
}
```

---

## 六、AI内容安全过滤

### 6.1 内容审核系统

```csharp
/// <summary>
/// AI内容安全过滤器：防止有害内容出现在游戏中
/// </summary>
public class AIContentFilter
{
    // 敏感词表（实际项目从配置文件加载）
    private static readonly HashSet<string> BlockedKeywords = new HashSet<string>
    {
        // 在此列出需要过滤的词汇
    };

    // 主题类别黑名单
    private static readonly List<string> BlockedTopics = new List<string>
    {
        "现实世界的政治人物",
        "真实地名的军事冲突",
        "个人隐私信息"
    };

    /// <summary>
    /// 过滤用户输入：防止提示词注入攻击
    /// </summary>
    public static string FilterPlayerInput(string input)
    {
        if (string.IsNullOrEmpty(input)) return input;
        
        // 1. 长度限制
        if (input.Length > 500)
            input = input.Substring(0, 500);
        
        // 2. 防注入：移除可能破坏系统提示的特殊标记
        input = input.Replace("[SYSTEM]", "")
                     .Replace("Ignore previous instructions", "")
                     .Replace("忽略之前的指令", "")
                     .Replace("###", "");
        
        // 3. 关键词过滤
        foreach (var keyword in BlockedKeywords)
        {
            input = input.Replace(keyword, "***");
        }
        
        return input.Trim();
    }

    /// <summary>
    /// 过滤AI输出：确保响应内容安全
    /// </summary>
    public static (bool IsClean, string FilteredContent) FilterAIOutput(string output)
    {
        if (string.IsNullOrEmpty(output))
            return (true, string.Empty);
        
        // 1. 检查是否试图跳出角色
        if (output.Contains("作为一个AI") || 
            output.Contains("I'm an AI") ||
            output.Contains("语言模型"))
        {
            return (false, string.Empty); // 返回空，触发fallback
        }
        
        // 2. 关键词过滤
        bool hasBlocked = false;
        foreach (var keyword in BlockedKeywords)
        {
            if (output.Contains(keyword))
            {
                output = output.Replace(keyword, "***");
                hasBlocked = true;
            }
        }
        
        return (!hasBlocked, output);
    }
}
```

---

## 七、性能优化策略

### 7.1 请求批处理

```csharp
/// <summary>
/// NPC批量对话优化器：在NPC密集场景中批量处理对话请求
/// </summary>
public class NPCBatchDialogueOptimizer : MonoBehaviour
{
    [SerializeField] private float batchWindowMs = 50f; // 50ms内的请求合并处理
    
    private List<(string npcId, string input, TaskCompletionSource<string> tcs)> pendingRequests
        = new List<(string, string, TaskCompletionSource<string>)>();
    
    private bool isProcessing = false;

    public async Task<string> EnqueueDialogueRequest(string npcId, string playerInput)
    {
        var tcs = new TaskCompletionSource<string>();
        pendingRequests.Add((npcId, playerInput, tcs));
        
        if (!isProcessing)
        {
            // 等待批处理窗口
            _ = ProcessBatchAfterDelay();
        }
        
        return await tcs.Task;
    }

    private async Task ProcessBatchAfterDelay()
    {
        isProcessing = true;
        await Task.Delay(TimeSpan.FromMilliseconds(batchWindowMs));
        
        var batch = new List<(string npcId, string input, TaskCompletionSource<string> tcs)>(pendingRequests);
        pendingRequests.Clear();
        isProcessing = false;
        
        // 并发处理批次中的所有请求
        var tasks = batch.Select(async item =>
        {
            try
            {
                // 这里可以使用更短的maxTokens来提升批处理吞吐
                string response = await LLMRequestManager.Instance.SendAsync(
                    "简短回复", item.input, maxTokens: 80
                );
                item.tcs.SetResult(response);
            }
            catch (Exception ex)
            {
                item.tcs.SetException(ex);
            }
        });
        
        await Task.WhenAll(tasks);
    }
}
```

---

## 八、最佳实践总结

### 8.1 架构原则

| 原则 | 说明 |
|------|------|
| **先本地后云端** | 意图分类等简单任务用本地ONNX模型，复杂生成才调用云端API |
| **预生成池化** | 对任务/对话等提前生成并缓存，避免玩家感知延迟 |
| **优雅降级** | API故障时有完善的模板回退方案，不影响核心游戏体验 |
| **严格过滤** | 玩家输入和AI输出都必须经过安全过滤 |
| **成本控制** | 限流 + 缓存 + 本地模型三管齐下控制API费用 |
| **隐私合规** | 不将玩家个人信息发送给第三方API |

### 8.2 技术选型决策树

```
是否需要联网？
├── 否 → 本地ONNX/Ollama小模型
└── 是 → 是否对话质量要求极高？
         ├── 是 → GPT-4o / Claude (成本高)
         └── 否 → GPT-4o-mini / Gemini Flash (经济方案)
                   └── 对话频繁？→ 使用Inworld AI NPC专用方案
```

### 8.3 工程落地 Checklist

- [ ] 实现带限流、重试、缓存的LLM请求管理器
- [ ] 为每个NPC设计独立的角色档案（ScriptableObject）
- [ ] 实现输入/输出双向内容安全过滤
- [ ] 预生成任务/对话内容池，避免实时等待
- [ ] 本地模型降级方案（Ollama/ONNX Runtime）
- [ ] 对话历史管理（长度限制 + 摘要压缩）
- [ ] API费用监控与告警
- [ ] 玩家差评收集反馈系统（改进Prompt）
- [ ] 法务合规审查（数据处理协议）

---

## 总结

AIGC在游戏中的工程化落地，核心挑战不在于AI能力本身，而在于**如何将不确定的AI输出变成可控的游戏体验**。关键是建立完善的降级策略、内容过滤、性能管理，让AI成为锦上添花的工具，而不是脆弱的依赖项。随着本地小模型性能的快速提升（Llama 3、Gemma系列），越来越多的游戏将实现无需联网、低延迟的运行时AI内容生成能力。
