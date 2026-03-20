---
title: Unity 性能优化完全手册：CPU、GPU、内存全覆盖
published: 2026-03-21
description: "系统讲解 Unity 游戏性能优化的完整方法论，从性能分析到具体优化手段，覆盖 CPU 优化、GPU 优化、内存优化、资源优化四大方向，适合中高级工程师。"
tags: [Unity, 性能优化, Profiler, 游戏开发]
category: 性能优化
draft: false
---

## 优化的正确姿势

> **不要优化你认为慢的地方，要优化 Profiler 告诉你慢的地方。**

许多工程师凭直觉优化，花了大量时间优化了一个只占 2% 耗时的地方，而真正的瓶颈却没有处理。

**性能优化流程**：
```
测量 → 定位瓶颈 → 分析原因 → 实施优化 → 验证效果 → 循环
```

永远从测量开始，而不是从感觉开始。

---

## 一、性能分析工具

### 1.1 Unity Profiler 核心用法

```
打开方式：Window → Analysis → Profiler

关键模块：
- CPU Usage：主线程、渲染线程各自的耗时
- Memory：堆内存分配，GC Alloc 分布
- Rendering：DrawCalls、Batches、SetPass 数量
- Physics：碰撞检测耗时

重要快捷键：
- 点击某帧 → 暂停并展开该帧的调用堆栈
- 右键 → "Show in Hierarchy" → 查看调用链
- 上方搜索框 → 快速找到特定方法
```

**关键指标速查**：

| 平台 | 目标帧率 | 允许总帧时间 | CPU 预算 | GPU 预算 |
|------|----------|-------------|---------|---------|
| 移动端高端 | 60fps | 16.7ms | 8ms | 8ms |
| 移动端中端 | 30fps | 33.3ms | 15ms | 15ms |
| PC | 60fps | 16.7ms | 6ms | 8ms |
| 主机 | 60fps | 16.7ms | 6ms | 8ms |

### 1.2 Memory Profiler（深度内存分析）

```
安装：Package Manager → Memory Profiler

功能：
- 拍摄内存快照（Snapshot）
- 查看所有对象的内存占用
- 对比两个快照找出内存泄漏
- 查看纹理/Mesh 的具体占用

典型工作流：
1. 进入游戏，拍摄快照 A
2. 操作一段时间（如打开关闭界面10次）
3. 拍摄快照 B
4. 对比 A、B，查看新增对象
5. 如果关闭界面后内存没有下降，说明有泄漏
```

### 1.3 Frame Debugger

```
打开：Window → Analysis → Frame Debugger → Enable

用途：
- 逐步查看每个 DrawCall 的渲染状态
- 确认合批是否生效（连续的 DrawCall 是否被合并）
- 查看阴影渲染开销
- 分析后处理效果的 Pass 数量

定位合批问题：
- 相邻 DrawCall 使用不同材质 → 无法合批
- Dynamic Batching：< 900 个顶点属性，相同材质
- Static Batching：需要勾选 Static
- GPU Instancing：相同网格+相同材质，开启 Instancing
```

---

## 二、CPU 优化

### 2.1 减少 DrawCall

DrawCall 是 CPU 向 GPU 发送的绘制命令，每次 DrawCall 前 CPU 需要做状态切换。

**静态合批（Static Batching）**：
```
适用：不动的场景物体（地形、建筑、障碍物）
设置：Inspector → Static → Batching Static
原理：在构建时合并成一个大 Mesh
代价：增加内存（合并后的 Mesh 单独存储）

优化建议：
- 场景中大量重复使用同一个 Mesh 时，请用 GPU Instancing 而非 Static Batching
- Static Batching 适合不重复的复杂场景物件
```

**GPU Instancing**：
```csharp
// 适用：大量相同 Mesh + 相同材质（草地、树木、士兵群）
// 设置：Material 面板 → Enable GPU Instancing

// 在 Shader 中支持 Instancing
Shader "Game/Grass"
{
    SubShader
    {
        Pass
        {
            HLSLPROGRAM
            #pragma instancing_options assumeuniformscaling
            
            UNITY_INSTANCING_BUFFER_START(Props)
                UNITY_DEFINE_INSTANCED_PROP(float4, _Color)
                UNITY_DEFINE_INSTANCED_PROP(float, _WindStrength)
            UNITY_INSTANCING_BUFFER_END(Props)
            
            Varyings vert(Attributes input)
            {
                UNITY_SETUP_INSTANCE_ID(input);
                float4 color = UNITY_ACCESS_INSTANCED_PROP(Props, _Color);
                // ...
            }
            ENDHLSL
        }
    }
}

// C# 侧使用 DrawMeshInstanced
public class GrassRenderer : MonoBehaviour
{
    private Matrix4x4[] _matrices;
    private MaterialPropertyBlock _propertyBlock;
    
    void Update()
    {
        // 每帧更新颜色（风吹效果）
        _propertyBlock.SetFloatArray("_WindStrength", _windValues);
        
        // 一次 DrawCall 绘制 1000 棵草
        Graphics.DrawMeshInstanced(
            grassMesh, 0, grassMaterial, 
            _matrices, _matrices.Length,
            _propertyBlock
        );
    }
}
```

**SRP Batcher**（URP 专属）：
```
条件：相同的 Shader Variant
效果：大幅减少 CPU 的 SetPass 调用
验证：Profiler → Rendering → Batches vs SetPass Calls
      SetPass Calls 应该远少于 Batches
```

### 2.2 减少 Update 调用

```csharp
// ❌ 错误：每个组件都有 Update
public class EnemyAI : MonoBehaviour
{
    void Update() // Unity 每帧通过反射调用，每个 MonoBehaviour 都有开销
    {
        Think();
        Move();
    }
}

// ✅ 正确：统一管理 Update
public class EnemyManager : MonoBehaviour
{
    private static readonly List<EnemyAI> _enemies = new(256);
    
    public static void Register(EnemyAI enemy) => _enemies.Add(enemy);
    public static void Unregister(EnemyAI enemy) => _enemies.Remove(enemy);
    
    void Update()
    {
        // 一次 Update 处理所有敌人
        float dt = Time.deltaTime;
        for (int i = 0; i < _enemies.Count; i++)
            _enemies[i].ManualUpdate(dt);
    }
}

public class EnemyAI : MonoBehaviour
{
    // 不再有 Unity Update
    void OnEnable() => EnemyManager.Register(this);
    void OnDisable() => EnemyManager.Unregister(this);
    
    public void ManualUpdate(float dt)
    {
        Think();
        Move();
    }
}
```

### 2.3 对象池：消除运行时分配

```csharp
/// <summary>
/// 泛型对象池，支持预热和容量上限
/// </summary>
public class ObjectPool<T> where T : Component
{
    private readonly Stack<T> _pool;
    private readonly Transform _parent;
    private readonly T _prefab;
    private readonly int _maxSize;
    
    public int ActiveCount { get; private set; }
    
    public ObjectPool(T prefab, int initialSize = 10, int maxSize = 100)
    {
        _prefab = prefab;
        _maxSize = maxSize;
        _pool = new Stack<T>(initialSize);
        
        // 创建专属父节点（隐藏池中对象）
        var go = new GameObject($"Pool_{typeof(T).Name}");
        _parent = go.transform;
        
        // 预热
        for (int i = 0; i < initialSize; i++)
        {
            var obj = CreateNew();
            obj.gameObject.SetActive(false);
            _pool.Push(obj);
        }
    }
    
    public T Get(Vector3 position = default, Quaternion rotation = default)
    {
        T obj;
        if (_pool.Count > 0)
        {
            obj = _pool.Pop();
        }
        else
        {
            obj = CreateNew();
        }
        
        obj.transform.SetPositionAndRotation(position, rotation);
        obj.transform.SetParent(null); // 脱离池的父节点
        obj.gameObject.SetActive(true);
        ActiveCount++;
        return obj;
    }
    
    public void Return(T obj)
    {
        if (_pool.Count >= _maxSize)
        {
            Object.Destroy(obj.gameObject); // 超过上限直接销毁
            return;
        }
        
        obj.gameObject.SetActive(false);
        obj.transform.SetParent(_parent);
        _pool.Push(obj);
        ActiveCount--;
    }
    
    private T CreateNew()
    {
        var obj = Object.Instantiate(_prefab, _parent);
        return obj;
    }
}

// 特效系统使用对象池
public class EffectManager : MonoBehaviour
{
    private readonly Dictionary<string, ObjectPool<ParticleSystem>> _pools = new();
    
    public ParticleSystem PlayEffect(string effectName, Vector3 position)
    {
        if (!_pools.TryGetValue(effectName, out var pool))
        {
            var prefab = Resources.Load<ParticleSystem>($"Effects/{effectName}");
            pool = new ObjectPool<ParticleSystem>(prefab, initialSize: 5);
            _pools[effectName] = pool;
        }
        
        var ps = pool.Get(position);
        ps.Play();
        
        // 特效播放完后自动回收
        StartCoroutine(ReturnAfterPlay(ps, pool));
        return ps;
    }
    
    private IEnumerator ReturnAfterPlay(ParticleSystem ps, ObjectPool<ParticleSystem> pool)
    {
        yield return new WaitUntil(() => !ps.IsAlive(true));
        pool.Return(ps);
    }
}
```

### 2.4 Physics 优化

```csharp
// ❌ 每帧 Raycast（对简单检测来说过于昂贵）
void Update()
{
    if (Physics.Raycast(transform.position, transform.forward, out hit, 10f))
        HandleHit(hit);
}

// ✅ 降频检测
private float _checkInterval = 0.1f; // 10次/秒
private float _nextCheckTime;

void Update()
{
    if (Time.time < _nextCheckTime) return;
    _nextCheckTime = Time.time + _checkInterval;
    
    if (Physics.Raycast(transform.position, transform.forward, out hit, 10f))
        HandleHit(hit);
}

// ✅ 使用非分配版本（避免 GC）
private readonly RaycastHit[] _hitBuffer = new RaycastHit[10];

void CheckNearbyEnemies()
{
    // NonAlloc 版本：结果写入预分配的数组
    int count = Physics.OverlapSphereNonAlloc(transform.position, 5f, 
        _hitBuffer.Select(h => h.collider).ToArray()); // 还是有问题...
    
    // 更好的方式：使用 Collider 数组
}

private readonly Collider[] _colliderBuffer = new Collider[32];

void CheckNearbyEnemiesOptimized()
{
    int count = Physics.OverlapSphereNonAlloc(transform.position, 5f, _colliderBuffer);
    for (int i = 0; i < count; i++)
    {
        var enemy = _colliderBuffer[i].GetComponent<Enemy>();
        if (enemy != null) ProcessEnemy(enemy);
    }
}
```

---

## 三、GPU 优化

### 3.1 减少过度绘制（Overdraw）

```
检测方式：
- Unity Scene 视图 → Overdraw 模式
- RenderDoc 截帧分析
- 部分手机厂商的 GPU 分析工具（Mali GPU Analyzer）

优化策略：

1. 不透明物体排序
   Unity 自动从前到后排序，启用 Early-Z 剔除
   确认：Depth Priming（URP 设置中）已开启

2. 透明物体
   - 尽量减少透明面积
   - 用 Alpha Test 代替 Alpha Blend（一般来说）
   - 控制粒子数量和尺寸

3. UI 层叠
   - 减少不可见 UI 仍在渲染的情况
   - 关闭界面时 SetActive(false) 而非移出屏幕
```

### 3.2 LOD（Level of Detail）

```csharp
// 手动为复杂模型设置 LOD
// 在 Prefab 上添加 LODGroup 组件

// 代码控制 LOD 质量
QualitySettings.lodBias = 1.0f; // 1.0 = 默认，> 1 使用更高质量 LOD

// 动态 LOD：根据性能动态调整
public class DynamicLODManager : MonoBehaviour
{
    private float _targetFrameRate = 60f;
    private float _currentLODBias = 1f;
    
    void Update()
    {
        float fps = 1f / Time.smoothDeltaTime;
        
        if (fps < _targetFrameRate * 0.8f) // 性能不足
        {
            _currentLODBias = Mathf.Max(0.3f, _currentLODBias - 0.1f);
        }
        else if (fps > _targetFrameRate * 0.95f) // 性能充足
        {
            _currentLODBias = Mathf.Min(1.5f, _currentLODBias + 0.05f);
        }
        
        QualitySettings.lodBias = _currentLODBias;
    }
}
```

### 3.3 Shader 优化实战

```glsl
// 1. 避免动态分支（GPU 不擅长条件分支）
// ❌ 动态分支
if (isWet)
    color = WetColor(color);
else
    color = DryColor(color);

// ✅ 数学替代（分支预测友好）
float wetFactor = saturate(wetness);
color = lerp(DryColor(color), WetColor(color), wetFactor);

// 2. 精度优化（移动端）
// 颜色计算使用 half 精度（16位浮点）
half4 color = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv); // 使用 half4
float3 worldPos = ...; // 位置计算必须用 float

// 3. 减少纹理采样次数
// ❌ 多次采样同一纹理
float4 c1 = tex2D(_MainTex, uv + offset1);
float4 c2 = tex2D(_MainTex, uv + offset2);
float4 c3 = tex2D(_MainTex, uv + offset3);

// ✅ 在一张纹理中打包多个通道
// R=Metallic, G=AO, B=Roughness, A=Height
float4 maskMap = tex2D(_MaskMap, uv);
float metallic = maskMap.r;
float ao = maskMap.g;
float roughness = maskMap.b;

// 4. 预计算到顶点着色器（减少片元着色器工作）
Varyings vert(Attributes input)
{
    Varyings output;
    // 在顶点着色器中计算（每顶点一次）
    output.shadowCoord = TransformWorldToShadowCoord(worldPos);
    // 然后在片元着色器中插值使用
    return output;
}
```

---

## 四、内存优化

### 4.1 纹理内存优化

```
纹理内存占用计算：
  宽 × 高 × 通道数 × 位深度 × Mipmap系数(约1.33)

例：2048×2048 RGBA32：
  2048 × 2048 × 4 字节 × 1.33 ≈ 22MB

压缩格式对比（2048×2048）：
  RGBA32:    22MB  （无压缩）
  RGBA16:    11MB  （半精度）
  ETC2 RGB:  2.7MB（Android，有损）
  ASTC 6x6:  2.4MB（iOS+Android，推荐）
  ASTC 4x4:  5.5MB（更高质量）

最佳实践：
- UI 纹理：Alpha8 或 RGBA16（不需要高精度颜色）
- 角色/场景：ASTC 6x6（平衡质量和大小）
- 法线贴图：EAC/ASTC（专门的法线压缩）
- 不需要 Alpha 通道的贴图：RGB 格式（少一个通道）
```

### 4.2 Mesh 内存优化

```csharp
// 检查 Mesh 内存占用
long GetMeshMemory(Mesh mesh)
{
    // 顶点数 × 每顶点大小
    int vertexSize = 0;
    foreach (var attr in mesh.GetVertexAttributes())
    {
        vertexSize += GetAttributeSize(attr.format, attr.dimension);
    }
    
    long vertexMemory = (long)mesh.vertexCount * vertexSize;
    long indexMemory = mesh.GetIndexCount(0) * (mesh.indexFormat == IndexFormat.UInt16 ? 2 : 4);
    
    return vertexMemory + indexMemory;
}

// 优化技巧
// 1. 使用 UInt16 索引（顶点数 < 65535 时）
mesh.indexFormat = IndexFormat.UInt16;

// 2. 去掉不需要的顶点属性
// 如果 Shader 不使用法线贴图，可以不导入切线（Tangent）
// 在 Model Import 设置中：Normals = None / Tangents = None

// 3. 网格简化 LOD
// 使用 Unity 的 LOD 系统，远距离用低精度 Mesh
```

### 4.3 GC 优化：减少托管堆分配

```csharp
// 常见的 GC 分配陷阱

// 1. 字符串拼接（每次都创建新字符串）
// ❌
void Update()
{
    label.text = "Score: " + score; // 每帧分配新字符串
}

// ✅ 使用 StringBuilder 或数字格式化
private readonly System.Text.StringBuilder _sb = new(32);

void Update()
{
    _sb.Clear();
    _sb.Append("Score: ");
    _sb.Append(score);
    label.text = _sb.ToString(); // 仍有一次分配，但比拼接少
}

// 更好：只在数值变化时更新
private int _lastScore = -1;

void Update()
{
    if (score != _lastScore)
    {
        _lastScore = score;
        label.text = $"Score: {score}"; // 只在变化时更新
    }
}

// 2. foreach 与装箱
// ❌ 对非泛型集合 foreach 会装箱
IEnumerable enemies = GetEnemies(); // 非泛型
foreach (var enemy in enemies) // 每次迭代都装箱
    Process(enemy);

// ✅ 使用泛型集合
List<Enemy> enemies = GetEnemies();
foreach (var enemy in enemies) // 无装箱
    Process(enemy);

// 3. Lambda 和闭包
// ❌ 高频调用中的 lambda 闭包
void Update()
{
    enemies.Sort((a, b) => a.Distance.CompareTo(b.Distance)); // 每帧分配 lambda
}

// ✅ 预创建 Comparer
private readonly EnemyDistanceComparer _distanceComparer = new();

void Update()
{
    enemies.Sort(_distanceComparer); // 零分配
}

private class EnemyDistanceComparer : IComparer<Enemy>
{
    public int Compare(Enemy a, Enemy b) => a.Distance.CompareTo(b.Distance);
}
```

### 4.4 内存泄漏的排查

```csharp
// 常见内存泄漏原因

// 1. 事件未取消注册
// 已在架构设计文章中讨论，这里不重复

// 2. 协程未停止
public class BadCoroutineExample : MonoBehaviour
{
    void Start()
    {
        StartCoroutine(NeverEndingCoroutine()); // 开始后忘记停止
    }
    
    IEnumerator NeverEndingCoroutine()
    {
        while (true)
        {
            // 如果这个 MonoBehaviour 被销毁，协程仍在运行
            // 引用的对象无法被 GC
            yield return null;
        }
    }
}

// ✅ 使用 CancellationToken
public class GoodCoroutineExample : MonoBehaviour
{
    private CancellationTokenSource _cts;
    
    void Start()
    {
        _cts = new CancellationTokenSource();
        RunLoopAsync(_cts.Token).Forget();
    }
    
    async UniTaskVoid RunLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            DoSomething();
            await UniTask.NextFrame(ct);
        }
    }
    
    void OnDestroy()
    {
        _cts?.Cancel();
        _cts?.Dispose();
    }
}

// 3. 静态引用
// static 变量存活于整个程序生命周期
// 如果静态集合持有对象引用，这些对象永远不会被 GC
public static class BadRegistry
{
    public static List<Character> AllCharacters = new(); // 静态集合
    // 如果没有显式 Remove，角色销毁后仍被持有 → 内存泄漏
}
```

---

## 五、资源优化

### 5.1 AssetBundle / Addressables 资源管理

```csharp
// 资源加载的完整生命周期管理
public class ResourceHandle<T> : IDisposable where T : Object
{
    private AsyncOperationHandle<T> _handle;
    private bool _disposed;
    
    public T Asset => _handle.Result;
    public bool IsLoaded => _handle.Status == AsyncOperationStatus.Succeeded;
    
    public async UniTask LoadAsync(string address, CancellationToken ct)
    {
        _handle = Addressables.LoadAssetAsync<T>(address);
        await _handle.WithCancellation(ct);
        
        if (_handle.Status != AsyncOperationStatus.Succeeded)
            throw new Exception($"Failed to load: {address}");
    }
    
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        
        if (_handle.IsValid())
            Addressables.Release(_handle); // 必须显式释放！
    }
}

// 使用示例（using 确保释放）
async UniTask LoadAndShow(string textureName, CancellationToken ct)
{
    using var handle = new ResourceHandle<Texture2D>();
    await handle.LoadAsync($"Textures/{textureName}", ct);
    
    // 使用资源
    image.texture = handle.Asset;
    
    // 等待界面关闭
    await waitForClose;
    
    // 退出 using 块自动释放资源
}
```

### 5.2 音频优化

```
音频内存对比（1分钟立体声）：
  PCM（未压缩）：  ~10MB
  Vorbis（OGG）:   ~1MB（压缩比 10:1）
  ADPCM：          ~2.5MB（低 CPU 解压开销）

最佳实践：
- 背景音乐：Streaming（不加载到内存，按需从磁盘读取）
- 高频短音效：Decompress on Load（内存中保持解压状态，低延迟）
- 低频音效：Compressed in Memory（平衡内存和延迟）

在 AudioClip 导入设置中：
  Load Type: 
    - Decompress on Load（音效 < 200KB）
    - Compressed in Memory（音效 200KB ~ 2MB）
    - Streaming（背景音乐 > 2MB）
```

---

## 六、建立性能监控体系

### 6.1 运行时性能监控

```csharp
/// <summary>
/// 轻量级性能监控，在游戏内实时显示关键指标
/// </summary>
public class PerformanceMonitor : MonoBehaviour
{
    private float _fpsTimer;
    private int _frameCount;
    private float _fps;
    private float _minFps = float.MaxValue;
    private float _maxMemoryMB;
    
    [SerializeField] private float _updateInterval = 0.5f;
    
    void Update()
    {
        _frameCount++;
        _fpsTimer += Time.unscaledDeltaTime;
        
        if (_fpsTimer >= _updateInterval)
        {
            _fps = _frameCount / _fpsTimer;
            _frameCount = 0;
            _fpsTimer = 0;
            _minFps = Mathf.Min(_minFps, _fps);
        }
        
        float memoryMB = (float)System.GC.GetTotalMemory(false) / (1024 * 1024);
        _maxMemoryMB = Mathf.Max(_maxMemoryMB, memoryMB);
    }
    
    void OnGUI()
    {
        GUILayout.Label($"FPS: {_fps:F1} (Min: {_minFps:F1})");
        GUILayout.Label($"Memory: {_maxMemoryMB:F1}MB peak");
        GUILayout.Label($"DrawCalls: {UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline}");
    }
}
```

### 6.2 性能基线与报警

```csharp
/// <summary>
/// 自动化性能测试：在关键场景建立性能基线，超出阈值自动报警
/// </summary>
[CreateAssetMenu(fileName = "PerformanceBaseline", menuName = "Game/Performance Baseline")]
public class PerformanceBaseline : ScriptableObject
{
    [Header("FPS")]
    public float minFPS = 55f;      // 低于此值报警
    public float targetFPS = 60f;
    
    [Header("Memory")]
    public float maxHeapMB = 300f;
    public float maxTextureMB = 200f;
    
    [Header("Rendering")]
    public int maxDrawCalls = 200;
    public int maxBatches = 100;
    
    // 验证当前帧是否符合基线
    public List<string> Validate()
    {
        var violations = new List<string>();
        
        float fps = 1f / Time.smoothDeltaTime;
        if (fps < minFPS)
            violations.Add($"FPS {fps:F1} 低于基线 {minFPS}");
        
        float heapMB = GC.GetTotalMemory(false) / (1024f * 1024f);
        if (heapMB > maxHeapMB)
            violations.Add($"堆内存 {heapMB:F1}MB 超出基线 {maxHeapMB}MB");
        
        return violations;
    }
}
```

---

## 总结

性能优化是一门需要**数据驱动**的工程技能：

1. **先测量，后优化**：用 Profiler 定位真正的瓶颈
2. **理解平台差异**：移动端和 PC 的优化重点完全不同
3. **建立基线**：有基线才能知道优化是否有效
4. **平衡三要素**：性能、可读性、开发效率，不要过度优化

**优化优先级**：
```
DrawCall 优化 > 内存优化 > Shader 复杂度 > 物理开销 > 脚本逻辑
（大多数项目的通用顺序，具体以 Profiler 数据为准）
```

> **下一篇**：[帧同步 vs 状态同步：网络同步方案深度对比]
