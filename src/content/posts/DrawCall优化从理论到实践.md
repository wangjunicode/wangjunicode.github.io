---
title: DrawCall 优化从理论到实践：移动端批处理全攻略
published: 2026-03-21
description: "深入讲解 DrawCall 的产生原理、Unity 的三种批处理技术（Static Batching、Dynamic Batching、GPU Instancing），以及移动端实战中的 DrawCall 优化策略，包含完整代码示例和性能数据对比。"
tags: [DrawCall, 渲染优化, Unity, 移动端, 性能优化]
category: 图形渲染
draft: false
---

## DrawCall 的本质

```
DrawCall = CPU 向 GPU 发出的一条绘制指令

每次 DrawCall 的 CPU 开销：
  设置渲染状态（材质/纹理/Shader）
  提交顶点数据
  提交常量数据（MVP 矩阵等）
  
一帧中 DrawCall 过多 → CPU 忙于提交指令 → CPU 瓶颈

移动端的问题：
  移动端 CPU 性能弱（约桌面端 1/5~1/10）
  一帧 DrawCall 超过 100 就可能造成性能问题
  桌面端可以轻松处理 1000+ DrawCall
```

---

## 一、Static Batching（静态合批）

### 1.1 原理

```
Static Batching：
  将标记为 Static 的 GameObject 的网格数据
  在构建时合并成一个大网格
  相同材质的对象在一次 DrawCall 中绘制
  
条件：
  - 勾选了 "Static" 的 GameObject
  - 使用相同的材质（Material）
  
代价：
  - 内存增加（合并后的网格数据需要存储）
  - 无法在运行时移动（Static 对象）
  
适用场景：
  - 场景中不动的环境物件（地形、建筑、道具）
  - 大量相同材质的静态装饰物
```

### 1.2 代码层面的静态合批

```csharp
// 在 Inspector 中设置 Static
// 或者在代码中（需要在 Awake 之前，通常不建议代码中设置）

// 运行时手动触发合批（不常用）
void Start()
{
    // 仅适用于动态创建的 Static 对象
    StaticBatchingUtility.Combine(gameObjectsToMerge, rootObject);
}

// 检查合批是否生效（调试用）
void CheckBatching()
{
    // 使用 Stats 面板观察 Batches 数量
    // 或者 Frame Debugger 查看 DrawCall 是否被合并
}
```

---

## 二、Dynamic Batching（动态合批）

### 2.1 原理与限制

```
Dynamic Batching：
  运行时，Unity 自动将符合条件的小网格合并
  每帧重新合并（有 CPU 开销）
  
条件（全部满足才能合批）：
  ✅ 相同材质（Material instance）
  ✅ 顶点数 ≤ 300
  ✅ 不使用多个纹理阶段
  ✅ 不使用 MultiPass Shader
  
URP 中默认情况：
  URP 对动态合批有 SRP Batcher 替代方案
  
SRP Batcher 的优势（Unity 2019+）：
  不合并网格，而是优化 CPU 提交数据的方式
  减少每次 DrawCall 的 CPU 状态变更
  支持任意网格大小
  效果通常优于传统动态合批
```

### 2.2 开启 SRP Batcher

```csharp
// URP 中默认开启 SRP Batcher
// 检查：Project Settings → Graphics → URP Asset → Advanced → SRP Batcher (默认开启)

// 确认 Shader 兼容 SRP Batcher 的条件：
// - 使用 UnityPerMaterial CBUFFER（将材质属性放入常量缓冲区）
// - Shader 的所有 Pass 都兼容

// 自定义 Shader 要支持 SRP Batcher，需要使用以下结构：

Shader "MyShader"
{
    Properties { ... }
    SubShader
    {
        Tags { "RenderType" = "Opaque" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            // 兼容 SRP Batcher 必须：将材质属性放入 CBUFFER
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float _Metallic;
                float _Smoothness;
            CBUFFER_END
            
            // ... Shader 代码
            
            ENDHLSL
        }
    }
}
```

---

## 三、GPU Instancing（GPU 实例化）

### 3.1 原理

```
GPU Instancing：
  一次 DrawCall，GPU 内部并行绘制同一网格的多个实例
  每个实例可以有不同的变换矩阵（位置/旋转/缩放）
  
与 Static/Dynamic Batching 的区别：
  Static Batching：合并网格数据（内存代价）
  Dynamic Batching：每帧合并（CPU代价）
  GPU Instancing：不合并，GPU 内部处理（几乎无 CPU 代价）
  
最适合场景：
  大量相同网格、相同材质、需要独立变换的对象
  树木、草地、石头、弹壳、敌人等
  
条件：
  材质开启 Enable GPU Instancing
  相同 Mesh + 相同 Material
```

### 3.2 手动 GPU Instancing

```csharp
/// <summary>
/// 使用 Graphics.DrawMeshInstanced 手动绘制大量实例
/// 适合：弹幕、粒子系统、大量装饰物
/// </summary>
public class GrassRenderer : MonoBehaviour
{
    [SerializeField] private Mesh _grassMesh;
    [SerializeField] private Material _grassMaterial;
    [SerializeField] private int _grassCount = 10000;
    
    private Matrix4x4[] _matrices;
    private MaterialPropertyBlock _propertyBlock;
    
    private const int MAX_BATCH = 1023; // DrawMeshInstanced 每批最大 1023
    
    void Start()
    {
        _grassMaterial.enableInstancing = true;
        _matrices = new Matrix4x4[_grassCount];
        _propertyBlock = new MaterialPropertyBlock();
        
        // 随机分布草地
        for (int i = 0; i < _grassCount; i++)
        {
            Vector3 pos = new(
                Random.Range(-50f, 50f),
                0f,
                Random.Range(-50f, 50f)
            );
            float scale = Random.Range(0.8f, 1.2f);
            float rot = Random.Range(0f, 360f);
            
            _matrices[i] = Matrix4x4.TRS(
                pos,
                Quaternion.Euler(0, rot, 0),
                Vector3.one * scale
            );
        }
    }
    
    void Update()
    {
        // 分批绘制（每批最多 1023 个）
        for (int i = 0; i < _grassCount; i += MAX_BATCH)
        {
            int batchCount = Mathf.Min(MAX_BATCH, _grassCount - i);
            
            Graphics.DrawMeshInstanced(
                _grassMesh,
                submeshIndex: 0,
                _grassMaterial,
                _matrices,
                count: batchCount,
                _propertyBlock,
                castShadows: UnityEngine.Rendering.ShadowCastingMode.Off,
                receiveShadows: false
            );
            // 注意：DrawMeshInstanced 第 5 个参数是 Matrix4x4[] 的偏移
        }
    }
}
```

### 3.3 每实例不同属性

```csharp
/// <summary>
/// GPU Instancing 中每个实例使用不同颜色
/// </summary>
public class ColoredInstanceRenderer : MonoBehaviour
{
    [SerializeField] private Mesh _mesh;
    [SerializeField] private Material _material;
    
    private Matrix4x4[] _matrices;
    private Vector4[] _colors;  // 每实例颜色
    private MaterialPropertyBlock _propertyBlock;
    
    private static readonly int ColorProperty = Shader.PropertyToID("_Color");
    
    void Start()
    {
        int count = 100;
        _matrices = new Matrix4x4[count];
        _colors = new Vector4[count];
        _propertyBlock = new MaterialPropertyBlock();
        
        for (int i = 0; i < count; i++)
        {
            _matrices[i] = Matrix4x4.TRS(
                new Vector3(i * 1.5f, 0, 0), 
                Quaternion.identity, 
                Vector3.one
            );
            _colors[i] = new Vector4(
                Random.value, Random.value, Random.value, 1
            );
        }
    }
    
    void Update()
    {
        // 通过 MaterialPropertyBlock 设置每实例属性
        _propertyBlock.SetVectorArray(ColorProperty, _colors);
        
        Graphics.DrawMeshInstanced(
            _mesh, 0, _material, _matrices, _matrices.Length, _propertyBlock
        );
    }
}
```

---

## 四、Atlas（图集）与材质合并

### 4.1 Sprite Atlas

```csharp
// UI 中的 DrawCall 优化：将多个小 Sprite 打包到一张 Atlas
// 相同 Atlas 的 UI 元素可以合批

// 在 Unity Editor 中创建 Sprite Atlas：
// Assets → Create → 2D → Sprite Atlas
// 将 Sprite 拖入 Sprite Atlas 的 Objects 列表

// 代码获取 Atlas 中的 Sprite
[SerializeField] private SpriteAtlas _atlas;

Sprite GetSprite(string spriteName)
{
    return _atlas.GetSprite(spriteName);
}

// 注意：
// 1. 同一个 Atlas 的所有 Sprite 是同一张纹理
// 2. UGUI 中，同 Atlas 的 UI 元素在没有跨越 Material 时可以合批
// 3. 中间夹了一个不同 Atlas 的元素会打断合批
```

### 4.2 合批的打断因素

```
会打断合批的情况：

UGUI：
  1. 不同材质（包括不同 Atlas）
  2. 中间有 3D 对象穿插
  3. 不同 Mask 层级
  4. 使用了 Effect（Shadow、Outline）

World Space：
  1. 不同材质
  2. 不同 Shader
  3. 不同纹理（即使是同一 Shader）
  4. 对象之间有其他材质的对象（渲染顺序中断）

诊断工具：
  Unity Frame Debugger：显示每个 DrawCall 的详细信息
  → 观察为什么某个 DrawCall 没有被合批
  → Frame Debugger 会显示 "Cannot batch: ..."
```

---

## 五、优化实战案例

### 5.1 场景中 1000 棵树的优化

```
初始状态：
  1000 棵独立的树木 GameObject
  每棵树：3 个 Mesh（树干+树叶+树枝）
  3000 个 DrawCall → 卡成 PPT

优化方案：

Step 1：将树合并为单个 LOD 网格
  树干+树叶+树枝 → 1个合并网格
  3000 DrawCall → 1000 DrawCall（减少 2/3）

Step 2：合并所有树木使用的纹理到一张 Atlas
  原来：3张不同纹理的材质（打断合批）
  优化后：1张 Atlas，所有树使用同一材质

Step 3：使用 GPU Instancing
  1000 DrawCall → 1~2 DrawCall（划分批次）

Step 4：增加 LOD（Level of Detail）
  近处：高精度网格
  远处：低精度网格（顶点数少）
  超远处：Billboard（公告板，只有4个顶点的面片）

最终结果：
  1000 棵树 → 10~20 DrawCall（根据距离分组）
  帧率从 15fps → 60fps
```

---

## 六、DrawCall 预算

### 6.1 设定 DrawCall 预算

```
移动端 DrawCall 参考预算（以 30fps 为目标）：

低端设备（入门机）：
  场景 DrawCall：< 80
  UI DrawCall：< 20
  总计：< 100

中端设备：
  场景 DrawCall：< 150
  UI DrawCall：< 30
  总计：< 180

高端设备：
  场景 DrawCall：< 250
  UI DrawCall：< 50
  总计：< 300

监控方式：
  在 CI/CD 中加入 DrawCall 统计
  超过预算 → 构建报警
  每个版本的 DrawCall 趋势图
```

---

## 总结

DrawCall 优化的优先级：

1. **SRP Batcher**（默认开启）：确保自定义 Shader 兼容
2. **Static Batching**：场景中不动的物体全部标记 Static
3. **GPU Instancing**：大量相同对象（草、树、弹壳等）
4. **Sprite Atlas**：UI 中的 Sprite 合并到 Atlas
5. **Dynamic Batching**：小网格的补充优化

**工具**：
- Frame Debugger：找出 DrawCall 过多的原因
- Stats 面板：实时观察 DrawCall 数量
- Profiler：分析 CPU 时间的分布

> **下一篇**：[Unity Addressables 高级应用：热更资源的加载优化]
