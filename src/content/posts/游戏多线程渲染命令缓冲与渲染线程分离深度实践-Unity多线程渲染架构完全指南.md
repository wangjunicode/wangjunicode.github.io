---
title: 游戏多线程渲染命令缓冲与渲染线程分离深度实践：Unity多线程渲染架构完全指南
published: 2026-04-24
description: 深度解析Unity多线程渲染架构，涵盖Render Thread分离机制、CommandBuffer跨线程调度、Graphics Jobs优化、Job System与渲染管线集成，含工程实现与性能调优最佳实践。
tags: [渲染线程, 多线程渲染, Unity, CommandBuffer, Graphics Jobs, 渲染优化, 游戏开发]
category: 游戏开发
draft: false
---

# 游戏多线程渲染命令缓冲与渲染线程分离深度实践

## 一、Unity 多线程渲染架构总览

在 Unity 的默认架构中，游戏逻辑与渲染提交高度耦合：主线程执行游戏逻辑、物理模拟，同时驱动 Unity 的渲染循环。这导致 CPU 侧的渲染开销直接占用游戏逻辑的帧预算。

### 1.1 Unity 渲染线程模型演进

```
Unity 渲染模型演进史

Unity 2017 及以前（单线程渲染）：
  Main Thread: [Game Logic] → [Culling] → [CommandBuffer Build] → [GPU Submit]
  缺点：渲染 API 调用阻塞游戏逻辑

Unity 2018+ （Render Thread 分离）：
  Main Thread:   [Game Logic] → [Culling] → [CommandBuffer Build]
                                                          ↓ 提交到渲染队列
  Render Thread:                              [GPU Submit] → [Present]
  收益：游戏逻辑与 GPU 提交解耦，CPU 利用率提升

Unity 2019+ （Graphics Jobs / Render Jobs）：
  Main Thread:   [Game Logic]
  Worker Threads: [Culling] [Shadow] [CommandBuffer Build] (并行)
  Render Thread:  [GPU Submit]
  收益：剔除/阴影等渲染准备工作并行化，充分利用多核

Unity 6+ （Render Graph + Sub-passes）：
  进一步优化移动端 On-Chip Memory 带宽
```

### 1.2 多线程渲染开关与验证

```csharp
// PlayerSettings 中启用多线程渲染（Build Settings）
// Android: PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
// iOS: 默认 Metal，自动启用

// 运行时检查是否在渲染线程
public static class RenderThreadChecker
{
    /// <summary>
    /// 检查当前是否支持多线程渲染
    /// </summary>
    public static bool IsMultithreadedRenderingEnabled()
    {
#if UNITY_ANDROID
        return SystemInfo.graphicsMultiThreaded;
#elif UNITY_IOS
        return true; // Metal 默认多线程
#else
        return SystemInfo.graphicsMultiThreaded;
#endif
    }

    /// <summary>
    /// 获取渲染线程信息
    /// </summary>
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void PrintRenderInfo()
    {
        Debug.Log($"[RenderThread] 多线程渲染: {SystemInfo.graphicsMultiThreaded}");
        Debug.Log($"[RenderThread] 图形API: {SystemInfo.graphicsDeviceType}");
        Debug.Log($"[RenderThread] Graphics Jobs: {PlayerSettings.graphicsJobs}");
    }
}
```

---

## 二、CommandBuffer 跨线程调度机制

### 2.1 CommandBuffer 的本质

`CommandBuffer` 是 Unity 渲染管线的"命令录制本"。主线程将渲染指令录制到 CommandBuffer 中，渲染线程在合适的时机消费这些命令并提交给 GPU。

```
CommandBuffer 工作流

主线程（录制阶段）：
  CommandBuffer cmd = new CommandBuffer();
  cmd.SetRenderTarget(rt);
  cmd.DrawRenderer(renderer, material);
  cmd.BlitNamedRenderTextureToRenderTexture(...)
                    ↓ 这些调用仅是"录制"，不立即执行
渲染线程（执行阶段）：
  Graphics.ExecuteCommandBuffer(cmd);  // 真正向 GPU 提交
  或由 Camera Event 自动触发执行
```

### 2.2 多相机 CommandBuffer 注入

```csharp
/// <summary>
/// 多线程安全的 CommandBuffer 管理器
/// 负责各相机的 CommandBuffer 注册、执行与生命周期管理
/// </summary>
public class CameraCommandBufferManager : MonoBehaviour
{
    [Header("渲染注入点配置")]
    [SerializeField] private Camera _targetCamera;
    
    // 按 CameraEvent 分类存储 CommandBuffer
    private readonly Dictionary<CameraEvent, List<CommandBuffer>> _buffers 
        = new Dictionary<CameraEvent, List<CommandBuffer>>();
    
    // 线程安全的待注入队列（来自 Worker Thread 的请求）
    private readonly ConcurrentQueue<(CameraEvent evt, CommandBuffer buf, string name)> 
        _pendingAdds = new ConcurrentQueue<(CameraEvent, CommandBuffer, string)>();
    
    private readonly ConcurrentQueue<(CameraEvent evt, CommandBuffer buf)> 
        _pendingRemoves = new ConcurrentQueue<(CameraEvent, CommandBuffer)>();

    private void OnEnable()
    {
        Camera.onPreRender += OnCameraPreRender;
        RenderPipelineManager.beginCameraRendering += OnBeginCameraRendering;
    }

    private void OnDisable()
    {
        Camera.onPreRender -= OnCameraPreRender;
        RenderPipelineManager.beginCameraRendering -= OnBeginCameraRendering;
        RemoveAllBuffers();
    }

    private void Update()
    {
        // 在主线程处理来自其他线程的注入请求
        ProcessPendingOperations();
    }

    private void ProcessPendingOperations()
    {
        // 处理添加请求
        while (_pendingAdds.TryDequeue(out var add))
        {
            AddBufferInternal(add.evt, add.buf, add.name);
        }
        
        // 处理移除请求
        while (_pendingRemoves.TryDequeue(out var remove))
        {
            RemoveBufferInternal(remove.evt, remove.buf);
        }
    }

    /// <summary>
    /// 线程安全的 CommandBuffer 注入（可从 Job 线程调用）
    /// </summary>
    public void AddBuffer(CameraEvent cameraEvent, CommandBuffer buffer, string bufferName)
    {
        if (Thread.CurrentThread.ManagedThreadId == 1) // 主线程直接操作
        {
            AddBufferInternal(cameraEvent, buffer, bufferName);
        }
        else // 非主线程：放入队列，等待主线程处理
        {
            _pendingAdds.Enqueue((cameraEvent, buffer, bufferName));
        }
    }

    private void AddBufferInternal(CameraEvent cameraEvent, CommandBuffer buffer, string name)
    {
        if (!_buffers.ContainsKey(cameraEvent))
            _buffers[cameraEvent] = new List<CommandBuffer>();
        
        buffer.name = name;
        _buffers[cameraEvent].Add(buffer);
        _targetCamera.AddCommandBuffer(cameraEvent, buffer);
        
        Debug.Log($"[CmdBufMgr] 注入 CommandBuffer: [{cameraEvent}] {name}");
    }

    private void RemoveBufferInternal(CameraEvent cameraEvent, CommandBuffer buffer)
    {
        if (_buffers.TryGetValue(cameraEvent, out var list))
        {
            list.Remove(buffer);
            _targetCamera.RemoveCommandBuffer(cameraEvent, buffer);
        }
    }

    private void RemoveAllBuffers()
    {
        foreach (var (evt, list) in _buffers)
        {
            foreach (var buf in list)
            {
                _targetCamera.RemoveCommandBuffer(evt, buf);
                buf.Dispose();
            }
        }
        _buffers.Clear();
    }

    private void OnCameraPreRender(Camera cam)
    {
        if (cam != _targetCamera) return;
        // 内置渲染管线：相机开始渲染前触发
    }

    private void OnBeginCameraRendering(ScriptableRenderContext ctx, Camera cam)
    {
        if (cam != _targetCamera) return;
        // URP/HDRP：相机开始渲染前触发
    }
}
```

### 2.3 自定义渲染命令的并行构建

```csharp
/// <summary>
/// 并行构建 CommandBuffer：利用 Job System 在 Worker Thread 中准备渲染数据，
/// 主线程汇总并构建最终 CommandBuffer
/// </summary>
public class ParallelCommandBufferBuilder : MonoBehaviour
{
    [SerializeField] private Camera _camera;
    [SerializeField] private Material _debugMaterial;
    
    private CommandBuffer _renderCmd;
    private NativeArray<Matrix4x4> _objectMatrices;
    private NativeArray<Vector4> _objectColors;
    private int _objectCount = 1000;

    private void OnEnable()
    {
        _renderCmd = new CommandBuffer { name = "ParallelBuiltCommands" };
        _camera.AddCommandBuffer(CameraEvent.AfterForwardOpaque, _renderCmd);
        
        _objectMatrices = new NativeArray<Matrix4x4>(_objectCount, Allocator.Persistent);
        _objectColors = new NativeArray<Vector4>(_objectCount, Allocator.Persistent);
    }

    private void OnDisable()
    {
        _camera.RemoveCommandBuffer(CameraEvent.AfterForwardOpaque, _renderCmd);
        _renderCmd.Dispose();
        
        if (_objectMatrices.IsCreated) _objectMatrices.Dispose();
        if (_objectColors.IsCreated) _objectColors.Dispose();
    }

    private void Update()
    {
        // Step 1: Job System 并行计算变换矩阵（Worker Thread）
        var updateJob = new UpdateObjectTransformsJob
        {
            Matrices = _objectMatrices,
            Colors = _objectColors,
            Time = Time.time,
            ObjectCount = _objectCount
        };
        
        JobHandle jobHandle = updateJob.Schedule(_objectCount, 64);
        
        // 其他游戏逻辑可以在 Job 运行期间执行
        // ...
        
        // Step 2: 等待 Job 完成
        jobHandle.Complete();
        
        // Step 3: 主线程用计算结果构建 CommandBuffer
        BuildCommandBuffer();
    }

    private void BuildCommandBuffer()
    {
        _renderCmd.Clear();
        
        // 设置渲染目标（使用当前相机的渲染目标）
        _renderCmd.SetRenderTarget(BuiltinRenderTextureType.CurrentActive);
        
        // 根据 Job 计算的结果批量设置 Shader 属性并绘制
        for (int i = 0; i < _objectCount; i++)
        {
            _renderCmd.SetGlobalVector("_InstanceColor", _objectColors[i]);
            _renderCmd.DrawMesh(
                GetInstanceMesh(), 
                _objectMatrices[i], 
                _debugMaterial, 
                0, 
                0
            );
        }
    }

    private Mesh GetInstanceMesh()
    {
        // 返回共享网格，避免重复创建
        return PrimitiveMeshCache.Get(PrimitiveType.Cube);
    }

    [BurstCompile]
    private struct UpdateObjectTransformsJob : IJobParallelFor
    {
        [WriteOnly] public NativeArray<Matrix4x4> Matrices;
        [WriteOnly] public NativeArray<Vector4> Colors;
        [ReadOnly] public float Time;
        [ReadOnly] public int ObjectCount;

        public void Execute(int index)
        {
            // 并行计算每个对象的变换矩阵（Burst 编译加速）
            float angle = (index / (float)ObjectCount) * 360f * Mathf.Deg2Rad;
            float radius = 10f + (index % 10) * 2f;
            
            Vector3 position = new Vector3(
                Mathf.Cos(angle + Time * 0.5f) * radius,
                Mathf.Sin(index * 0.1f + Time) * 2f,
                Mathf.Sin(angle + Time * 0.5f) * radius
            );
            
            Matrices[index] = Matrix4x4.TRS(
                position, 
                Quaternion.Euler(0, angle * Mathf.Rad2Deg + Time * 30f, 0), 
                Vector3.one * 0.3f
            );
            
            // 颜色根据位置动态变化
            Colors[index] = new Vector4(
                (Mathf.Sin(Time + index * 0.1f) + 1f) * 0.5f,
                (Mathf.Cos(Time * 0.7f + index * 0.15f) + 1f) * 0.5f,
                (Mathf.Sin(Time * 1.3f + index * 0.05f) + 1f) * 0.5f,
                1f
            );
        }
    }
}
```

---

## 三、Graphics Jobs 深度调优

### 3.1 Graphics Jobs 的类型与适用场景

```csharp
// Project Settings > Player > Other Settings > Graphics Jobs
// 三种模式：
// - Legacy: 单线程渲染（兼容模式）
// - Native: Graphics Jobs（推荐，Unity 2022+）
// - Scripting: 自定义 Job System 控制（实验性）

/// <summary>
/// 运行时动态检测最优 Graphics Jobs 配置
/// </summary>
public static class GraphicsJobsOptimizer
{
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
    public static void OptimizeGraphicsJobs()
    {
        int cpuCores = SystemInfo.processorCount;
        GraphicsDeviceType gfxApi = SystemInfo.graphicsDeviceType;
        
        bool supportsGraphicsJobs = 
            gfxApi == GraphicsDeviceType.Vulkan ||
            gfxApi == GraphicsDeviceType.Metal ||
            gfxApi == GraphicsDeviceType.Direct3D12;
        
        if (supportsGraphicsJobs && cpuCores >= 4)
        {
            Debug.Log($"[GraphicsJobs] 启用 Graphics Jobs - CPU核心数:{cpuCores}, API:{gfxApi}");
        }
        else
        {
            Debug.Log($"[GraphicsJobs] 不满足条件，使用传统渲染 - CPU核心数:{cpuCores}, API:{gfxApi}");
        }
    }
}
```

### 3.2 Render Batching 与 Draw Call 合并的多线程优化

```csharp
/// <summary>
/// 多线程 GPU Instancing 批次构建器
/// 利用 Job System 并行计算实例数据，减少主线程 Draw Call 构建开销
/// </summary>
public class MultiThreadedInstanceBatcher : MonoBehaviour
{
    [SerializeField] private Mesh _instanceMesh;
    [SerializeField] private Material _instanceMaterial;
    [SerializeField] private int _instanceCount = 10000;

    private ComputeBuffer _positionBuffer;
    private ComputeBuffer _colorBuffer;
    private ComputeBuffer _argsBuffer;
    private uint[] _args = new uint[5];
    
    private NativeArray<Vector3> _positions;
    private NativeArray<Vector4> _colors;
    private MaterialPropertyBlock _propertyBlock;
    private Bounds _renderBounds;
    
    private JobHandle _updateJobHandle;
    private bool _jobScheduled;

    private static readonly int _positionBufferId = Shader.PropertyToID("_Positions");
    private static readonly int _colorBufferId = Shader.PropertyToID("_Colors");

    private void Awake()
    {
        _propertyBlock = new MaterialPropertyBlock();
        _renderBounds = new Bounds(Vector3.zero, Vector3.one * 1000f);
        
        InitBuffers();
    }

    private void InitBuffers()
    {
        _positions = new NativeArray<Vector3>(_instanceCount, Allocator.Persistent);
        _colors = new NativeArray<Vector4>(_instanceCount, Allocator.Persistent);
        
        // GPU 缓冲区
        _positionBuffer = new ComputeBuffer(_instanceCount, sizeof(float) * 3);
        _colorBuffer = new ComputeBuffer(_instanceCount, sizeof(float) * 4);
        
        // DrawMeshInstancedIndirect 的参数缓冲区
        _argsBuffer = new ComputeBuffer(1, _args.Length * sizeof(uint), 
            ComputeBufferType.IndirectArguments);
        
        _args[0] = (uint)_instanceMesh.GetIndexCount(0);
        _args[1] = (uint)_instanceCount;
        _args[2] = (uint)_instanceMesh.GetIndexStart(0);
        _args[3] = (uint)_instanceMesh.GetBaseVertex(0);
        _args[4] = 0;
        _argsBuffer.SetData(_args);
    }

    private void Update()
    {
        // 调度 Job（不等待，让 Worker Thread 并行执行）
        ScheduleUpdateJob();
    }

    private void LateUpdate()
    {
        // LateUpdate 时等待 Job 完成，确保数据准备好
        if (_jobScheduled)
        {
            _updateJobHandle.Complete();
            _jobScheduled = false;
            
            // 上传到 GPU
            UploadToGPU();
        }
        
        // Indirect Draw Call（仅一次 Draw Call 绘制所有实例）
        _instanceMaterial.SetBuffer(_positionBufferId, _positionBuffer);
        _instanceMaterial.SetBuffer(_colorBufferId, _colorBuffer);
        
        Graphics.DrawMeshInstancedIndirect(
            _instanceMesh,
            0,
            _instanceMaterial,
            _renderBounds,
            _argsBuffer,
            0,
            _propertyBlock,
            ShadowCastingMode.On,
            true
        );
    }

    private void ScheduleUpdateJob()
    {
        var job = new UpdateInstanceDataJob
        {
            Positions = _positions,
            Colors = _colors,
            InstanceCount = _instanceCount,
            Time = Time.time,
            DeltaTime = Time.deltaTime
        };
        
        // 分批并行处理（每批 128 个实例）
        _updateJobHandle = job.Schedule(_instanceCount, 128);
        _jobScheduled = true;
    }

    private void UploadToGPU()
    {
        _positionBuffer.SetData(_positions);
        _colorBuffer.SetData(_colors);
    }

    private void OnDestroy()
    {
        if (_jobScheduled) _updateJobHandle.Complete();
        
        _positions.Dispose();
        _colors.Dispose();
        _positionBuffer?.Release();
        _colorBuffer?.Release();
        _argsBuffer?.Release();
    }

    [BurstCompile]
    private struct UpdateInstanceDataJob : IJobParallelFor
    {
        [WriteOnly] public NativeArray<Vector3> Positions;
        [WriteOnly] public NativeArray<Vector4> Colors;
        [ReadOnly] public int InstanceCount;
        [ReadOnly] public float Time;
        [ReadOnly] public float DeltaTime;

        public void Execute(int index)
        {
            float t = (float)index / InstanceCount;
            float angle = t * math.PI * 2f;
            
            // 螺旋分布
            float radius = 5f + t * 50f;
            float height = math.sin(Time * 0.5f + t * math.PI * 4f) * 5f;
            
            Positions[index] = new Vector3(
                math.cos(angle + Time * 0.3f) * radius,
                height + index * 0.01f,
                math.sin(angle + Time * 0.3f) * radius
            );
            
            Colors[index] = new Vector4(
                math.abs(math.sin(Time + t)),
                math.abs(math.cos(Time * 0.7f + t)),
                t,
                1f
            );
        }
    }
}
```

---

## 四、渲染线程与主线程的数据同步

### 4.1 双缓冲渲染数据模式

```csharp
/// <summary>
/// 渲染数据双缓冲：主线程写入当前帧数据，渲染线程读取上一帧数据
/// 避免数据竞争，消除主线程等待渲染线程完成的阻塞
/// </summary>
public class DoubleBufferedRenderData<T> where T : struct
{
    private T[] _buffers;
    private volatile int _writeIndex = 0;
    private volatile int _readIndex = 1;
    private readonly object _swapLock = new object();

    public DoubleBufferedRenderData()
    {
        _buffers = new T[2];
    }

    /// <summary>
    /// 主线程：获取写入缓冲区的引用
    /// </summary>
    public ref T GetWriteBuffer()
    {
        return ref _buffers[_writeIndex];
    }

    /// <summary>
    /// 渲染线程：获取读取缓冲区（上一帧提交的数据）
    /// </summary>
    public ref T GetReadBuffer()
    {
        return ref _buffers[_readIndex];
    }

    /// <summary>
    /// 主线程：帧结束时交换缓冲区
    /// </summary>
    public void SwapBuffers()
    {
        lock (_swapLock)
        {
            int temp = _writeIndex;
            _writeIndex = _readIndex;
            _readIndex = temp;
        }
    }
}

/// <summary>
/// 使用双缓冲的粒子系统渲染数据管理
/// </summary>
[Serializable]
public struct ParticleRenderData
{
    public Matrix4x4[] Matrices;
    public Vector4[] Colors;
    public int ActiveCount;
}

public class DoubleBufferedParticleSystem : MonoBehaviour
{
    private DoubleBufferedRenderData<ParticleRenderData> _renderData;
    private ComputeBuffer _matrixBuffer;
    private ComputeBuffer _colorBuffer;
    private int _maxParticles = 5000;

    private void Awake()
    {
        _renderData = new DoubleBufferedRenderData<ParticleRenderData>();
        ref var bufA = ref _renderData.GetWriteBuffer();
        bufA.Matrices = new Matrix4x4[_maxParticles];
        bufA.Colors = new Vector4[_maxParticles];
        ref var bufB = ref _renderData.GetReadBuffer();
        bufB.Matrices = new Matrix4x4[_maxParticles];
        bufB.Colors = new Vector4[_maxParticles];
        
        _matrixBuffer = new ComputeBuffer(_maxParticles, sizeof(float) * 16);
        _colorBuffer = new ComputeBuffer(_maxParticles, sizeof(float) * 4);
    }

    private void Update()
    {
        // 主线程：更新粒子状态，写入写缓冲区
        UpdateParticles();
        
        // 帧结束：交换缓冲区
        _renderData.SwapBuffers();
    }

    private void OnRenderObject()
    {
        // 渲染线程（通过 OnRenderObject 回调在渲染时机执行）
        // 读取读缓冲区（上一帧的稳定数据）
        ref var readData = ref _renderData.GetReadBuffer();
        
        if (readData.ActiveCount > 0)
        {
            _matrixBuffer.SetData(readData.Matrices, 0, 0, readData.ActiveCount);
            _colorBuffer.SetData(readData.Colors, 0, 0, readData.ActiveCount);
        }
    }

    private void UpdateParticles()
    {
        ref var writeData = ref _renderData.GetWriteBuffer();
        // 模拟粒子更新逻辑
        writeData.ActiveCount = Mathf.Min(_maxParticles, 1000);
        for (int i = 0; i < writeData.ActiveCount; i++)
        {
            writeData.Matrices[i] = Matrix4x4.TRS(
                new Vector3(i * 0.1f, 0, 0),
                Quaternion.identity,
                Vector3.one * 0.5f
            );
            writeData.Colors[i] = Color.white;
        }
    }

    private void OnDestroy()
    {
        _matrixBuffer?.Release();
        _colorBuffer?.Release();
    }
}
```

---

## 五、URP 中的多线程渲染优化

### 5.1 ScriptableRenderPass 中的 Job System 集成

```csharp
/// <summary>
/// 自定义 URP RenderPass：使用 Job System 并行准备渲染数据
/// </summary>
public class JobAcceleratedRenderPass : ScriptableRenderPass
{
    private readonly string _profilerTag = "JobAcceleratedPass";
    private readonly ProfilingSampler _profilingSampler;
    
    private NativeArray<VisibleLight> _visibleLights;
    private NativeArray<LightData> _processedLightData;
    private JobHandle _lightProcessingJob;
    private bool _jobScheduled;
    
    [StructLayout(LayoutKind.Sequential)]
    private struct LightData
    {
        public Vector3 Position;
        public Vector3 Color;
        public float Range;
        public float Intensity;
        public float AttenuationFactor;
    }

    public JobAcceleratedRenderPass()
    {
        renderPassEvent = RenderPassEvent.BeforeRenderingOpaques;
        _profilingSampler = new ProfilingSampler(_profilerTag);
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        // 在相机设置阶段，提前调度光源处理 Job
        ref var lightData = ref renderingData.lightData;
        int lightCount = lightData.visibleLights.Length;
        
        if (lightCount > 0)
        {
            _visibleLights = new NativeArray<VisibleLight>(
                lightData.visibleLights.ToArray(), Allocator.TempJob);
            _processedLightData = new NativeArray<LightData>(lightCount, Allocator.TempJob);
            
            var processJob = new ProcessLightsJob
            {
                VisibleLights = _visibleLights,
                OutputLightData = _processedLightData,
                CameraPosition = renderingData.cameraData.camera.transform.position
            };
            
            // 调度 Job，让其在 Execute 之前完成
            _lightProcessingJob = processJob.Schedule(lightCount, 4);
            _jobScheduled = true;
        }
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get(_profilerTag);
        
        using (new ProfilingScope(cmd, _profilingSampler))
        {
            // 等待光源处理 Job 完成
            if (_jobScheduled)
            {
                _lightProcessingJob.Complete();
                _jobScheduled = false;
                
                // 将处理后的光源数据上传到 GPU
                UploadLightDataToShader(cmd, _processedLightData);
            }
            
            // 执行渲染命令
            context.ExecuteCommandBuffer(cmd);
        }
        
        CommandBufferPool.Release(cmd);
    }

    private void UploadLightDataToShader(CommandBuffer cmd, NativeArray<LightData> lightData)
    {
        // 将 NativeArray 数据转换为 Shader 可用的格式
        var lightPositions = new Vector4[lightData.Length];
        var lightColors = new Vector4[lightData.Length];
        
        for (int i = 0; i < lightData.Length; i++)
        {
            var ld = lightData[i];
            lightPositions[i] = new Vector4(ld.Position.x, ld.Position.y, ld.Position.z, ld.Range);
            lightColors[i] = new Vector4(ld.Color.x, ld.Color.y, ld.Color.z, ld.Intensity);
        }
        
        cmd.SetGlobalVectorArray("_CustomLightPositions", lightPositions);
        cmd.SetGlobalVectorArray("_CustomLightColors", lightColors);
        cmd.SetGlobalInt("_CustomLightCount", lightData.Length);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 确保 Job 完成并释放 NativeArray
        if (_jobScheduled)
        {
            _lightProcessingJob.Complete();
            _jobScheduled = false;
        }
        
        if (_visibleLights.IsCreated) _visibleLights.Dispose();
        if (_processedLightData.IsCreated) _processedLightData.Dispose();
    }

    [BurstCompile]
    private struct ProcessLightsJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<VisibleLight> VisibleLights;
        [ReadOnly] public Vector3 CameraPosition;
        [WriteOnly] public NativeArray<LightData> OutputLightData;

        public void Execute(int index)
        {
            var light = VisibleLights[index];
            Vector3 lightPos = light.localToWorldMatrix.GetColumn(3);
            float distance = math.distance(lightPos, CameraPosition);
            
            // 计算基于距离的衰减系数
            float attenuation = math.saturate(1f - distance / (light.range * 2f));
            
            OutputLightData[index] = new LightData
            {
                Position = lightPos,
                Color = new Vector3(light.finalColor.r, light.finalColor.g, light.finalColor.b),
                Range = light.range,
                Intensity = light.light != null ? light.light.intensity : 1f,
                AttenuationFactor = attenuation
            };
        }
    }
}
```

---

## 六、性能分析与调优工具

### 6.1 渲染线程性能监控

```csharp
/// <summary>
/// 渲染线程性能监控器：追踪 Main Thread / Render Thread 耗时分布
/// </summary>
public class RenderThreadProfiler : MonoBehaviour
{
    [Header("监控配置")]
    [SerializeField] private bool _enableProfiling = true;
    [SerializeField] private int _sampleCount = 60;
    
    // 性能数据缓冲
    private Queue<float> _mainThreadTimes = new Queue<float>();
    private Queue<float> _renderThreadTimes = new Queue<float>();
    private Queue<float> _gpuTimes = new Queue<float>();

    // Unity Profiler Recorder
    private ProfilerRecorder _mainThreadRecorder;
    private ProfilerRecorder _renderThreadRecorder;
    private ProfilerRecorder _gpuFrameRecorder;

    private void OnEnable()
    {
        if (!_enableProfiling) return;
        
        // 录制关键指标
        _mainThreadRecorder = ProfilerRecorder.StartNew(
            ProfilerCategory.Internal, "Main Thread", _sampleCount);
        _renderThreadRecorder = ProfilerRecorder.StartNew(
            ProfilerCategory.Internal, "Render Thread", _sampleCount);
        _gpuFrameRecorder = ProfilerRecorder.StartNew(
            ProfilerCategory.Internal, "GPU Frame Time", _sampleCount);
    }

    private void OnDisable()
    {
        _mainThreadRecorder.Dispose();
        _renderThreadRecorder.Dispose();
        _gpuFrameRecorder.Dispose();
    }

    private void Update()
    {
        if (!_enableProfiling) return;
        
        // 收集当前帧数据
        if (_mainThreadRecorder.Valid)
        {
            double mainMs = _mainThreadRecorder.LastValue * 1e-6; // ns -> ms
            TrackSample(_mainThreadTimes, (float)mainMs);
        }
        
        if (_renderThreadRecorder.Valid)
        {
            double renderMs = _renderThreadRecorder.LastValue * 1e-6;
            TrackSample(_renderThreadTimes, (float)renderMs);
        }
        
        if (_gpuFrameRecorder.Valid)
        {
            double gpuMs = _gpuFrameRecorder.LastValue * 1e-6;
            TrackSample(_gpuTimes, (float)gpuMs);
        }
    }

    private void TrackSample(Queue<float> queue, float value)
    {
        queue.Enqueue(value);
        if (queue.Count > _sampleCount) queue.Dequeue();
    }

    /// <summary>
    /// 获取性能报告（可用于 HUD 显示）
    /// </summary>
    public string GetPerformanceReport()
    {
        float mainAvg = GetAverage(_mainThreadTimes);
        float renderAvg = GetAverage(_renderThreadTimes);
        float gpuAvg = GetAverage(_gpuTimes);
        float bottleneck = Mathf.Max(mainAvg, renderAvg, gpuAvg);
        
        string bottleneckLabel = bottleneck == mainAvg ? "CPU主线程" : 
                                 bottleneck == renderAvg ? "渲染线程" : "GPU";
        
        return $"[渲染性能]\n" +
               $"主线程: {mainAvg:F1}ms\n" +
               $"渲染线程: {renderAvg:F1}ms\n" +
               $"GPU帧时间: {gpuAvg:F1}ms\n" +
               $"瓶颈: {bottleneckLabel}";
    }

    private float GetAverage(Queue<float> queue)
    {
        if (queue.Count == 0) return 0f;
        return queue.Sum() / queue.Count;
    }
    
    private void OnGUI()
    {
        if (!_enableProfiling) return;
        GUI.Label(new Rect(10, 10, 300, 120), GetPerformanceReport());
    }
}
```

---

## 七、最佳实践总结

### 7.1 多线程渲染配置清单

| 配置项 | 推荐设置 | 说明 |
|--------|---------|------|
| 渲染线程 | 开启 | Android Vulkan / iOS Metal 必须开启 |
| Graphics Jobs | 开启（Native） | 4核以上 CPU 明显收益 |
| Dynamic Batching | 视情况 | Draw Call 多时开启，Batch 对象少时关闭 |
| GPU Instancing | 强烈推荐 | 相同 Mesh + Material 的大量对象 |
| SRP Batcher | 推荐开启 | URP/HDRP 下大幅减少 CPU 渲染开销 |

### 7.2 Job System 与渲染集成规范

```
渲染帧时序规范：
  Update()        → 调度计算 Job（非阻塞）
  LateUpdate()    → Complete Job，准备渲染数据
  OnPreRender()   → 设置 CommandBuffer（主线程）
  Render Thread   → 执行 CommandBuffer，提交 GPU 命令
  GPU             → 执行渲染
  OnPostRender()  → 后处理（主线程）
```

### 7.3 常见陷阱与解决方案

| 问题 | 现象 | 解决方案 |
|------|------|---------|
| 渲染线程数据竞争 | 帧间撕裂、随机崩溃 | 双缓冲渲染数据，主线程写/渲染线程读严格分离 |
| Job 完成前读取数据 | 数据错误或崩溃 | 在使用前调用 JobHandle.Complete() |
| CommandBuffer 内存泄漏 | 内存持续增长 | 使用 CommandBufferPool，及时 Release |
| NativeArray 未释放 | 内存泄漏 | 在 OnDisable/OnDestroy 中 Dispose |
| Burst Job 引用托管对象 | 编译错误 | Job 结构体只能包含 blittable 类型 |

多线程渲染是现代 Unity 游戏性能优化的核心战场。通过合理使用 CommandBuffer、Job System、Graphics Jobs 以及双缓冲数据同步模式，可以在不牺牲代码可维护性的前提下，将 CPU 侧渲染性能提升 30%~200%，充分释放多核处理器的计算潜力。
