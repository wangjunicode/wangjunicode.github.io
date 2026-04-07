---
title: 游戏Decal贴花系统深度实践：屏幕空间贴花、投影贴花与URP深度重建完全指南
published: 2026-04-07
description: 深度解析游戏Decal贴花系统的多种实现方案，包括传统Projector投影贴花、屏幕空间Decal（SSD）、延迟贴花与URP DBuffer Decal，涵盖弹孔、血迹、路面标记等实战场景的工程优化方案。
tags: [Decal, 贴花系统, 屏幕空间, URP, 投影渲染, 深度重建, 弹孔效果, 游戏特效]
category: 图形渲染
draft: false
---

# 游戏 Decal 贴花系统深度实践

## 前言

Decal（贴花）系统是游戏中不可缺少的视觉增强技术：弹孔、血迹、脚印、路面标记、魔法阵……这些动态添加到世界表面的效果都依赖 Decal 系统。与普通贴图不同，Decal 能"贴合"任意形状的表面，无需修改原始几何体。

本文深度覆盖：
- Decal 系统的核心原理与分类
- 传统 Projector 投影贴花（兼容性最广）
- 屏幕空间 Decal（SSD）原理与实现
- URP DBuffer Decal 系统
- 延迟贴花（Deferred Decal）
- 弹孔、血迹等高频 Decal 的性能优化
- Decal 池与生命周期管理

---

## 一、Decal 系统分类与对比

### 1.1 四种主流方案对比

| 方案 | 原理 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| Projector 投影 | 正交投影纹理叠加 | 兼容性好，简单 | 需额外Pass，泄漏 | 简单场景、移动端 |
| Mesh Decal | 手动创建贴合网格 | 完全精确 | 需要运行时生成Mesh | 静态大型贴花 |
| **屏幕空间 Decal** | **深度重建位置** | **零Mesh开销** | **需要深度纹理** | **动态弹孔血迹** |
| **URP DBuffer** | **延迟属性修改** | **支持PBR属性** | **需要额外GBuffer** | **PBR场景大型贴花** |

### 1.2 屏幕空间 Decal 核心原理

```
1. 在世界空间放置一个AABB盒（Decal Volume）
2. 渲染该AABB盒（通常是1×1×1的正方体）
3. 片元着色器：读取当前像素的深度 → 重建世界空间位置
4. 判断重建位置是否在Decal Volume内
5. 计算Decal Volume的局部UV → 采样贴花纹理
6. 将颜色/法线/金属度等属性混合到表面
```

---

## 二、传统 Projector 贴花实现

### 2.1 Unity Projector 替代方案（URP兼容）

Unity 内置的 Projector 组件在 URP 中不工作，需要自行实现：

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// URP兼容的Projector贴花渲染器
/// 原理：将贴花纹理通过正交投影矩阵映射到世界表面
/// </summary>
[RequireComponent(typeof(Camera))]
public class URPProjectorDecal : MonoBehaviour
{
    [Header("贴花参数")]
    [SerializeField] private Texture2D _decalTexture;
    [SerializeField] private Material  _projectorMaterial;
    [SerializeField] private float     _size = 1f;
    [SerializeField] private float     _farClipPlane = 5f;
    
    [Header("混合")]
    [SerializeField, Range(0, 1)] private float _opacity = 1f;
    [SerializeField] private LayerMask _receiverLayers = -1;
    
    // 正交投影矩阵（用于将世界坐标映射到贴花UV）
    private Matrix4x4 _projectionMatrix;
    
    void Start()
    {
        BuildProjectionMatrix();
    }
    
    void BuildProjectionMatrix()
    {
        // 正交投影：将 [-size/2, size/2] 范围映射到 [0, 1] UV
        _projectionMatrix = Matrix4x4.Ortho(
            -_size / 2f,  _size / 2f,
            -_size / 2f,  _size / 2f,
            0f, _farClipPlane
        );
        
        // 将世界空间坐标变换到贴花本地空间
        // 乘以世界到本地矩阵（即相机View矩阵）
    }
    
    void OnRenderObject()
    {
        if (_projectorMaterial == null || _decalTexture == null) return;
        
        // 构建 Projector 矩阵：世界 → 贴花本地 → 正交投影 → UV
        Matrix4x4 worldToDecal = transform.worldToLocalMatrix;
        
        // 将 [-0.5, 0.5] 的本地坐标映射到 [0, 1] UV
        Matrix4x4 biasMatrix = Matrix4x4.identity;
        biasMatrix.m00 = 0.5f; biasMatrix.m03 = 0.5f;
        biasMatrix.m11 = 0.5f; biasMatrix.m13 = 0.5f;
        biasMatrix.m22 = 0.5f; biasMatrix.m23 = 0.5f;
        
        Matrix4x4 projectorMatrix = biasMatrix * _projectionMatrix * worldToDecal;
        
        _projectorMaterial.SetMatrix("_ProjectorMatrix", projectorMatrix);
        _projectorMaterial.SetTexture("_DecalTex", _decalTexture);
        _projectorMaterial.SetFloat("_Opacity", _opacity);
        _projectorMaterial.SetVector("_ProjectorForward", transform.forward);
        _projectorMaterial.SetFloat("_FarClip", _farClipPlane);
    }
    
    #if UNITY_EDITOR
    void OnDrawGizmosSelected()
    {
        Gizmos.color = Color.cyan;
        Gizmos.matrix = transform.localToWorldMatrix;
        Gizmos.DrawWireCube(
            new Vector3(0, 0, _farClipPlane / 2f), 
            new Vector3(_size, _size, _farClipPlane));
    }
    #endif
}
```

对应的 Projector Shader：

```hlsl
// URPProjector.shader
Shader "Custom/URPProjector"
{
    Properties
    {
        _DecalTex ("Decal Texture", 2D) = "white" {}
        _Opacity ("Opacity", Range(0,1)) = 1.0
    }
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Transparent-1" }
        
        Pass
        {
            // 混合模式：Alpha混合
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            // 避免贴花画在自身上（Z-fighting）
            Offset -1, -1
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_DecalTex);
            SAMPLER(sampler_DecalTex);
            
            float4x4 _ProjectorMatrix;
            float3   _ProjectorForward;
            float    _FarClip;
            float    _Opacity;
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionCS    : SV_POSITION;
                float4 projectorCoord : TEXCOORD0; // 投影坐标
                float3 normalWS      : TEXCOORD1;
                float3 positionWS    : TEXCOORD2;
            };
            
            Varyings vert(Attributes input)
            {
                Varyings output;
                VertexPositionInputs posInputs = GetVertexPositionInputs(input.positionOS.xyz);
                VertexNormalInputs   normInputs = GetVertexNormalInputs(input.normalOS);
                
                output.positionCS    = posInputs.positionCS;
                output.positionWS    = posInputs.positionWS;
                output.normalWS      = normInputs.normalWS;
                
                // 投影坐标计算
                output.projectorCoord = mul(_ProjectorMatrix, float4(output.positionWS, 1.0));
                
                return output;
            }
            
            half4 frag(Varyings input) : SV_Target
            {
                // 投影坐标归一化
                float2 projUV = input.projectorCoord.xy / input.projectorCoord.w;
                
                // 超出[0,1]范围的丢弃（避免泄漏到盒子外面）
                if (any(projUV < 0) || any(projUV > 1)) discard;
                if (input.projectorCoord.w < 0) discard; // 背面剔除
                
                // 背面法线测试（不贴到背对投影仪的面）
                float NdotProj = dot(normalize(input.normalWS), -_ProjectorForward);
                if (NdotProj < 0.1) discard; // 接近平行或背面
                
                half4 decalColor = SAMPLE_TEXTURE2D(_DecalTex, sampler_DecalTex, projUV);
                decalColor.a *= _Opacity;
                
                return decalColor;
            }
            ENDHLSL
        }
    }
}
```

---

## 三、屏幕空间 Decal（SSD）实现

### 3.1 深度重建世界位置

屏幕空间 Decal 的核心是从深度缓冲重建像素的世界空间坐标：

```hlsl
// DecalDepthReconstruct.hlsl
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"

/// <summary>
/// 从深度纹理重建世界空间位置
/// </summary>
float3 ReconstructWorldPosition(float2 screenUV, float depth)
{
    #if defined(UNITY_REVERSED_Z)
        depth = 1.0 - depth; // DirectX/Metal 深度反转
    #endif
    
    // NDC坐标（-1到1）
    float3 ndcPos = float3(screenUV * 2.0 - 1.0, depth * 2.0 - 1.0);
    
    // 逆投影：NDC → 裁剪空间 → 视图空间
    float4 clipSpacePos = float4(ndcPos, 1.0);
    float4 viewSpacePos = mul(UNITY_MATRIX_I_P, clipSpacePos);
    viewSpacePos /= viewSpacePos.w;
    
    // 视图空间 → 世界空间
    float3 worldPos = mul(UNITY_MATRIX_I_V, float4(viewSpacePos.xyz, 1.0)).xyz;
    return worldPos;
}

/// <summary>
/// 优化版本：使用Ray方向插值（减少矩阵乘法）
/// 在顶点着色器中计算Ray方向，片元中线性插值
/// </summary>
float3 ReconstructWorldPositionFast(float3 rayWS, float2 screenUV)
{
    float depth = SampleSceneDepth(screenUV);
    
    #if defined(UNITY_REVERSED_Z)
        depth = 1.0 - depth;
    #endif
    
    // linearDepth：将深度值转换为相机到像素的距离
    float linearDepth = LinearEyeDepth(depth, _ZBufferParams);
    
    // rayWS 是从相机到远平面角落的插值方向（已归一化）
    // 乘以线性深度 / 相机到远平面的距离得到世界位置
    float3 cameraPos = _WorldSpaceCameraPos;
    return cameraPos + rayWS * linearDepth;
}
```

### 3.2 URP 屏幕空间 Decal Shader

```hlsl
// ScreenSpaceDecal.shader
Shader "Custom/ScreenSpaceDecal"
{
    Properties
    {
        _DecalAlbedo   ("Albedo (RGBA)", 2D) = "white" {}
        _DecalNormal   ("Normal Map",    2D) = "bump"  {}
        _DecalMask     ("Mask (R=roughness, G=metallic)", 2D) = "white" {}
        _Opacity       ("Opacity", Range(0,1)) = 1.0
        _NormalStrength("Normal Strength", Range(0,2)) = 1.0
        _AngleFade     ("Angle Fade Threshold", Range(0,1)) = 0.3
    }
    SubShader
    {
        Tags 
        { 
            "RenderType" = "Transparent"
            "Queue" = "Geometry+1"
            "RenderPipeline" = "UniversalPipeline"
        }
        
        Pass
        {
            Name "ScreenSpaceDecal"
            
            Blend SrcAlpha OneMinusSrcAlpha, Zero One
            ZWrite Off
            ZTest Always // 总是通过深度测试（因为我们从深度纹理重建）
            Cull Front   // 正面剔除（相机在盒子内部时渲染背面）
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareNormalsTexture.hlsl"
            
            TEXTURE2D(_DecalAlbedo);  SAMPLER(sampler_DecalAlbedo);
            TEXTURE2D(_DecalNormal);  SAMPLER(sampler_DecalNormal);
            TEXTURE2D(_DecalMask);    SAMPLER(sampler_DecalMask);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _DecalAlbedo_ST;
                float  _Opacity;
                float  _NormalStrength;
                float  _AngleFade;
            CBUFFER_END
            
            // Decal Volume 的世界→本地变换矩阵（由C#传入）
            float4x4 _WorldToDecal;
            float4x4 _DecalToWorld;
            float3   _DecalForward; // Decal朝向（用于法线剔除）
            
            struct Attributes
            {
                float4 positionOS : POSITION;
            };
            
            struct Varyings
            {
                float4 positionCS  : SV_POSITION;
                float4 screenPos   : TEXCOORD0;
                float3 rayWS       : TEXCOORD1; // 从相机出发的世界空间射线
            };
            
            Varyings vert(Attributes input)
            {
                Varyings output;
                
                float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);
                output.positionCS = TransformWorldToHClip(positionWS);
                output.screenPos  = ComputeScreenPos(output.positionCS);
                
                // 计算从相机到顶点的射线（用于片元中插值重建位置）
                output.rayWS = positionWS - _WorldSpaceCameraPos;
                
                return output;
            }
            
            // 计算法线空间的贴花UV，处理贴花角度淡出
            struct DecalSurface
            {
                float2 uv;
                float  alpha; // 基于角度的衰减
                bool   valid; // 是否在Decal Volume内
            };
            
            DecalSurface GetDecalSurface(float3 worldPos, float3 worldNormal)
            {
                DecalSurface result;
                result.valid = false;
                result.alpha = 0;
                result.uv = 0;
                
                // 将世界坐标变换到Decal本地空间（-0.5 ~ 0.5 范围）
                float3 localPos = mul(_WorldToDecal, float4(worldPos, 1.0)).xyz;
                
                // 检查是否在Decal Volume内
                if (any(abs(localPos) > 0.5)) return result;
                
                result.valid = true;
                
                // XZ平面投影（Decal默认向下投影）
                result.uv = TRANSFORM_TEX(localPos.xz + 0.5, _DecalAlbedo);
                
                // 法线角度淡出（防止在陡峭侧面产生拉伸）
                float NdotUp = dot(worldNormal, _DecalForward);
                result.alpha = saturate((NdotUp - _AngleFade) / (1.0 - _AngleFade));
                
                return result;
            }
            
            half4 frag(Varyings input) : SV_Target
            {
                // 1. 从深度纹理重建世界位置
                float2 screenUV = input.screenPos.xy / input.screenPos.w;
                float  depth    = SampleSceneDepth(screenUV);
                
                #if UNITY_REVERSED_Z
                    depth = 1.0 - depth;
                #endif
                
                float linearDepth = LinearEyeDepth(depth, _ZBufferParams);
                
                // 利用顶点插值的Ray方向重建（高效）
                float3 worldPos = _WorldSpaceCameraPos + 
                                  normalize(input.rayWS) * linearDepth;
                
                // 2. 从场景法线纹理获取表面法线
                float3 worldNormal = SampleSceneNormals(screenUV);
                
                // 3. 计算Decal UV和角度淡出
                DecalSurface ds = GetDecalSurface(worldPos, worldNormal);
                if (!ds.valid || ds.alpha < 0.001) discard;
                
                // 4. 采样Decal纹理
                half4 albedo = SAMPLE_TEXTURE2D(_DecalAlbedo, sampler_DecalAlbedo, ds.uv);
                albedo.a *= _Opacity * ds.alpha;
                
                if (albedo.a < 0.001) discard;
                
                return albedo;
            }
            ENDHLSL
        }
    }
}
```

---

## 四、URP DBuffer Decal 系统

### 4.1 DBuffer Decal 原理

DBuffer 将 Decal 属性（颜色、法线、金属度等）写入专用缓冲区，在 Opaque 渲染前与 GBuffer/Surface 合并，支持 PBR 属性修改：

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 配置 URP DBuffer Decal（Unity 2021.2+ 支持）
/// </summary>
public class URPDecalSystemSetup : MonoBehaviour
{
    void Start()
    {
        // 确保 URP Asset 启用了 Decal 功能
        // 在 URP Asset Inspector 中：
        // Renderer Features → Add → Decal
        // 设置 Technique = DBuffer（需要Depth Priming）
        
        // 代码方式动态创建Decal投影体
        SpawnBulletHoleDecal(transform.position, transform.forward);
    }
    
    /// <summary>
    /// 在指定位置生成弹孔贴花（使用Unity内置Decal组件）
    /// </summary>
    public static GameObject SpawnBulletHoleDecal(
        Vector3 hitPosition, 
        Vector3 hitNormal,
        float size = 0.3f,
        float lifetime = 10f)
    {
        // 创建Decal Projector
        var go = new GameObject("BulletHoleDecal");
        go.transform.position = hitPosition + hitNormal * 0.02f; // 略微偏移防止Z-fighting
        go.transform.rotation = Quaternion.LookRotation(-hitNormal); // 朝向表面
        go.transform.localScale = new Vector3(size, size, 0.5f); // Z是投影深度
        
        // 添加 URP DecalProjector 组件
        var projector = go.AddComponent<DecalProjector>();
        projector.size = new Vector3(size, size, 0.5f);
        projector.pivot = new Vector3(0, 0, 0.25f);
        projector.fadeFactor = 1f;
        projector.startAngleFade = 45f;
        projector.endAngleFade = 90f;
        
        // 生命周期管理（淡出销毁）
        if (lifetime > 0)
        {
            go.AddComponent<DecalLifetime>().Init(projector, lifetime);
        }
        
        return go;
    }
}

/// <summary>
/// Decal生命周期与淡出
/// </summary>
public class DecalLifetime : MonoBehaviour
{
    private DecalProjector _projector;
    private float _lifetime;
    private float _elapsed;
    private float _fadeStartRatio = 0.7f; // 最后30%时间淡出
    
    public void Init(DecalProjector projector, float lifetime)
    {
        _projector = projector;
        _lifetime = lifetime;
        _elapsed = 0f;
    }
    
    void Update()
    {
        _elapsed += Time.deltaTime;
        float t = _elapsed / _lifetime;
        
        if (t > _fadeStartRatio)
        {
            float fadeFactor = 1f - (t - _fadeStartRatio) / (1f - _fadeStartRatio);
            _projector.fadeFactor = fadeFactor;
        }
        
        if (_elapsed >= _lifetime)
        {
            Destroy(gameObject);
        }
    }
}
```

---

## 五、高性能 Decal 池系统

弹孔、脚印等高频生成的 Decal 必须使用对象池管理：

```csharp
using UnityEngine;
using UnityEngine.Pool;
using System.Collections.Generic;

/// <summary>
/// Decal对象池管理器
/// 支持多种Decal类型（弹孔、血迹、脚印、爆炸焦痕等）
/// </summary>
public class DecalPoolManager : MonoBehaviour
{
    [System.Serializable]
    public class DecalTypeConfig
    {
        public string typeId;               // 类型ID（如"bullet_hole_metal"）
        public GameObject prefab;           // Decal预制体
        public int poolCapacity = 50;       // 池容量（最多同时存在）
        public float lifetime = 30f;        // 生命周期（秒）
        [Range(0, 1)] public float fadeDuration = 0.3f; // 淡出时长占比
    }
    
    [SerializeField] private List<DecalTypeConfig> _decalTypes = new();
    
    // 每种类型的对象池
    private Dictionary<string, ObjectPool<GameObject>> _pools = new();
    // 活跃的Decal列表（用于LRU淘汰）
    private Dictionary<string, Queue<GameObject>> _activeDecals = new();
    
    private static DecalPoolManager _instance;
    public static DecalPoolManager Instance => _instance;
    
    void Awake()
    {
        _instance = this;
        InitPools();
    }
    
    void InitPools()
    {
        foreach (var config in _decalTypes)
        {
            var cfg = config; // 闭包捕获
            
            var pool = new ObjectPool<GameObject>(
                createFunc: () => 
                {
                    var go = Instantiate(cfg.prefab, transform);
                    go.SetActive(false);
                    return go;
                },
                actionOnGet: (go) => go.SetActive(true),
                actionOnRelease: (go) => 
                {
                    go.SetActive(false);
                    go.transform.SetParent(transform);
                },
                actionOnDestroy: (go) => Destroy(go),
                collectionCheck: false,
                defaultCapacity: cfg.poolCapacity,
                maxSize: cfg.poolCapacity
            );
            
            _pools[cfg.typeId] = pool;
            _activeDecals[cfg.typeId] = new Queue<GameObject>();
        }
    }
    
    /// <summary>
    /// 生成一个Decal
    /// </summary>
    /// <param name="typeId">Decal类型</param>
    /// <param name="position">世界坐标</param>
    /// <param name="normal">表面法线</param>
    /// <param name="size">贴花尺寸</param>
    /// <param name="rotation">额外旋转角（绕法线轴）</param>
    public GameObject SpawnDecal(string typeId, Vector3 position, Vector3 normal,
                                  float size = 0.3f, float rotation = 0f)
    {
        if (!_pools.TryGetValue(typeId, out var pool))
        {
            Debug.LogWarning($"[DecalPool] 未注册的Decal类型: {typeId}");
            return null;
        }
        
        var activeQueue = _activeDecals[typeId];
        var config = _decalTypes.Find(c => c.typeId == typeId);
        
        // 如果池已满，强制回收最旧的Decal（LRU）
        if (activeQueue.Count >= config.poolCapacity)
        {
            var oldest = activeQueue.Dequeue();
            if (oldest != null)
                pool.Release(oldest);
        }
        
        // 从池中获取Decal
        var decal = pool.Get();
        
        // 设置位置和朝向
        decal.transform.position = position + normal * 0.01f;
        
        // 朝向：Y轴（向上）对齐法线，Z轴随机旋转
        Quaternion rot = Quaternion.FromToRotation(Vector3.up, normal);
        rot *= Quaternion.AngleAxis(rotation, Vector3.up);
        decal.transform.rotation = rot;
        decal.transform.localScale = Vector3.one * size;
        
        // 设置父节点为击中物体（Decal跟随物体移动）
        // decal.transform.SetParent(hitObject.transform, true); // 可选
        
        // 启动生命周期倒计时
        var lifetime = decal.GetComponent<DecalLifetime>();
        if (lifetime == null)
            lifetime = decal.AddComponent<DecalLifetime>();
        
        var projector = decal.GetComponent<DecalProjector>();
        if (projector != null)
            lifetime.Init(projector, config.lifetime);
        
        // 记录到活跃队列
        activeQueue.Enqueue(decal);
        
        // 生命周期结束时回调（将Decal还回池中）
        StartCoroutine(ReturnToPool(decal, pool, config.lifetime + 0.1f));
        
        return decal;
    }
    
    private System.Collections.IEnumerator ReturnToPool(
        GameObject decal, ObjectPool<GameObject> pool, float delay)
    {
        yield return new WaitForSeconds(delay);
        if (decal != null && decal.activeInHierarchy)
        {
            pool.Release(decal);
        }
    }
    
    /// <summary>
    /// 清除所有活跃Decal（场景切换时调用）
    /// </summary>
    public void ClearAllDecals()
    {
        foreach (var kv in _activeDecals)
        {
            while (kv.Value.Count > 0)
            {
                var decal = kv.Value.Dequeue();
                if (decal != null && _pools.TryGetValue(kv.Key, out var pool))
                    pool.Release(decal);
            }
        }
    }
}
```

---

## 六、Decal 法线混合与细节增强

### 6.1 法线混合算法

在 Decal 与底层表面法线混合时，简单覆盖会导致光照不连续，需要使用正确的法线混合方法：

```hlsl
// DecalNormalBlend.hlsl

/// <summary>
/// Reoriented Normal Mapping（RNM）混合
/// 保留底层表面法线细节，将Decal法线正确叠加
/// </summary>
float3 BlendNormalsRNM(float3 baseNormal, float3 decalNormal)
{
    // baseNormal 是底层表面法线（切线空间，已解码）
    // decalNormal 是Decal法线（切线空间）
    
    // 将两个法线变换到一个对齐的切线空间后混合
    float3 t = baseNormal + float3(0, 0, 1);
    float3 u = decalNormal * float3(-1, -1, 1);
    
    return normalize(t * dot(t, u) - u * t.z);
}

/// <summary>
/// 简单覆盖（效果差但性能好）
/// </summary>
float3 BlendNormalsOverlay(float3 baseNormal, float3 decalNormal, float alpha)
{
    return normalize(lerp(baseNormal, decalNormal, alpha));
}

/// <summary>
/// 使用权重的法线混合（URP DBuffer方案）
/// baseNormal从GBuffer读取，已是世界空间
/// </summary>
float3 ApplyDecalNormal(float3 worldNormal, float3 decalNormalTS, 
                         float3x3 tangentToWorld, float normalAlpha)
{
    if (normalAlpha < 0.001) return worldNormal;
    
    // 将Decal法线从切线空间变换到世界空间
    float3 decalNormalWS = mul(tangentToWorld, decalNormalTS);
    
    return normalize(lerp(worldNormal, decalNormalWS, normalAlpha));
}
```

### 6.2 Decal 阴影接收

```csharp
/// <summary>
/// 确保Decal正确接收阴影
/// URP DBuffer Decal自动接收阴影（通过修改Surface属性）
/// 屏幕空间Decal需要在着色器中手动采样阴影
/// </summary>
public class DecalShadowReceiver : MonoBehaviour
{
    // 在Material Property Block中设置投影矩阵
    // 使SSD Shader能正确采样阴影贴图
    
    private MaterialPropertyBlock _mpb;
    private DecalProjector _projector;
    
    void Awake()
    {
        _mpb = new MaterialPropertyBlock();
        _projector = GetComponent<DecalProjector>();
    }
    
    void Update()
    {
        // 每帧更新变换矩阵（如果Decal会移动）
        Matrix4x4 worldToLocal = transform.worldToLocalMatrix;
        // 将矩阵传入Shader
        // _mpb.SetMatrix("_WorldToDecal", worldToLocal);
        // GetComponent<MeshRenderer>()?.SetPropertyBlock(_mpb);
    }
}
```

---

## 七、弹孔、血迹、脚印实战配置

### 7.1 弹孔系统（射击游戏标配）

```csharp
/// <summary>
/// 射击游戏弹孔生成器
/// 根据命中材质类型选择不同弹孔贴花
/// </summary>
public class BulletHoleSystem : MonoBehaviour
{
    [System.Serializable]
    public class SurfaceDecalMapping
    {
        public PhysicMaterial physicsMaterial; // 物理材质
        public string decalTypeId;             // 对应的弹孔类型
        public string hitEffectPrefab;         // 命中特效（火花/血液等）
        public AudioClip hitSound;             // 命中音效
    }
    
    [SerializeField] private List<SurfaceDecalMapping> _surfaceMappings = new();
    [SerializeField] private string _defaultDecalType = "bullet_hole_default";
    
    // 弹孔随机旋转范围（让每个弹孔有轻微旋转变化）
    [SerializeField, Range(0, 360)] private float _randomRotationRange = 180f;
    
    /// <summary>
    /// 处理射线命中，生成弹孔贴花
    /// </summary>
    public void ProcessHit(RaycastHit hit)
    {
        // 确定使用哪种弹孔类型
        string decalType = _defaultDecalType;
        
        // 根据命中物体的物理材质选择贴花
        var hitCollider = hit.collider;
        if (hitCollider.sharedMaterial != null)
        {
            var mapping = _surfaceMappings.Find(
                m => m.physicsMaterial == hitCollider.sharedMaterial);
            if (mapping != null)
                decalType = mapping.decalTypeId;
        }
        
        // 随机旋转（避免所有弹孔朝向相同）
        float randomRot = Random.Range(-_randomRotationRange / 2f, 
                                        _randomRotationRange / 2f);
        
        // 生成弹孔贴花
        float decalSize = Random.Range(0.08f, 0.12f); // 轻微尺寸随机化
        DecalPoolManager.Instance?.SpawnDecal(
            decalType, hit.point, hit.normal, decalSize, randomRot);
        
        // 生成命中特效
        // ParticleEffectManager.Instance?.PlayEffect("bullet_impact", hit.point, hit.normal);
    }
}
```

### 7.2 角色脚印系统

```csharp
/// <summary>
/// 角色脚印系统：根据角色移动速度动态生成脚印Decal
/// </summary>
public class FootprintSystem : MonoBehaviour
{
    [SerializeField] private string _leftFootprintDecalType  = "footprint_left";
    [SerializeField] private string _rightFootprintDecalType = "footprint_right";
    [SerializeField] private float  _footprintSize = 0.2f;
    [SerializeField] private float  _minStepDistance = 0.5f; // 最小步距（防止过密）
    
    [Header("地面检测")]
    [SerializeField] private float _groundCheckDistance = 0.2f;
    [SerializeField] private LayerMask _groundLayers;
    
    private Transform _leftFoot;
    private Transform _rightFoot;
    private Vector3 _lastLeftPos;
    private Vector3 _lastRightPos;
    
    private Animator _animator;
    
    void Start()
    {
        _animator = GetComponent<Animator>();
        // IK回调会在这里获取脚部骨骼位置
    }
    
    // Animator IK回调（每帧在IK更新后调用）
    void OnAnimatorIK(int layerIndex)
    {
        // 在IK更新时检查脚部位置，决定是否生成脚印
        CheckFootprint(_animator.GetIKPosition(AvatarIKGoal.LeftFoot), 
                       ref _lastLeftPos, _leftFootprintDecalType);
        CheckFootprint(_animator.GetIKPosition(AvatarIKGoal.RightFoot), 
                       ref _lastRightPos, _rightFootprintDecalType);
    }
    
    void CheckFootprint(Vector3 footPos, ref Vector3 lastPos, string decalType)
    {
        // 步距检测：只有移动足够距离才生成新脚印
        if (Vector3.Distance(footPos, lastPos) < _minStepDistance) return;
        
        // 地面射线检测
        if (Physics.Raycast(footPos + Vector3.up * 0.1f, Vector3.down, 
                             out RaycastHit hit, _groundCheckDistance + 0.1f,
                             _groundLayers))
        {
            // 仅在特定地面材质生成脚印（如雪地、泥地）
            if (ShouldLeaveFootprint(hit.collider))
            {
                float yAngle = transform.eulerAngles.y; // 角色朝向
                DecalPoolManager.Instance?.SpawnDecal(
                    decalType, hit.point, hit.normal, _footprintSize, yAngle);
                
                lastPos = footPos;
            }
        }
    }
    
    bool ShouldLeaveFootprint(Collider surface)
    {
        // 检查地面是否支持脚印（可通过Tag/Component判断）
        return surface.CompareTag("SoftGround") || 
               surface.GetComponent<FootprintReceiver>() != null;
    }
}
```

---

## 八、Decal LOD 与性能优化

### 8.1 距离淡出与 LOD

```csharp
/// <summary>
/// Decal LOD管理：根据与相机距离动态调整渲染精度
/// </summary>
public class DecalLODController : MonoBehaviour
{
    [Header("LOD距离")]
    [SerializeField] private float _lodFadeStart = 10f; // 开始淡出
    [SerializeField] private float _lodFadeEnd   = 20f; // 完全不可见
    
    private DecalProjector _projector;
    private Transform _cameraTransform;
    
    void Start()
    {
        _projector = GetComponent<DecalProjector>();
        _cameraTransform = Camera.main?.transform;
    }
    
    void Update()
    {
        if (_projector == null || _cameraTransform == null) return;
        
        float dist = Vector3.Distance(transform.position, _cameraTransform.position);
        
        if (dist <= _lodFadeStart)
        {
            _projector.fadeFactor = 1f;
            _projector.enabled = true;
        }
        else if (dist >= _lodFadeEnd)
        {
            _projector.enabled = false; // 完全剔除，节省DrawCall
        }
        else
        {
            float t = (dist - _lodFadeStart) / (_lodFadeEnd - _lodFadeStart);
            _projector.fadeFactor = 1f - t;
            _projector.enabled = true;
        }
    }
}

/// <summary>
/// 批量Decal剔除（每帧统一更新所有活跃Decal的可见性）
/// 比为每个Decal单独挂Update更高效
/// </summary>
public class DecalCullingSystem : MonoBehaviour
{
    private List<DecalProjector> _activeProjectors = new();
    private Camera _mainCamera;
    
    [SerializeField] private float _maxRenderDistance = 25f;
    
    void Update()
    {
        if (_mainCamera == null) { _mainCamera = Camera.main; return; }
        
        Vector3 camPos = _mainCamera.transform.position;
        
        // 批量更新所有Decal的渲染状态
        for (int i = _activeProjectors.Count - 1; i >= 0; i--)
        {
            var proj = _activeProjectors[i];
            if (proj == null) 
            { 
                _activeProjectors.RemoveAt(i); 
                continue; 
            }
            
            float sqrDist = (proj.transform.position - camPos).sqrMagnitude;
            proj.enabled = sqrDist <= _maxRenderDistance * _maxRenderDistance;
        }
    }
    
    public void RegisterDecal(DecalProjector projector)
    {
        _activeProjectors.Add(projector);
    }
    
    public void UnregisterDecal(DecalProjector projector)
    {
        _activeProjectors.Remove(projector);
    }
}
```

### 8.2 Decal Atlas 合批

```csharp
/// <summary>
/// Decal图集（Atlas）管理
/// 将多种Decal类型合并到一张Atlas纹理，减少材质切换
/// </summary>
[CreateAssetMenu(fileName = "DecalAtlas", menuName = "Game/Decal/DecalAtlas")]
public class DecalAtlasConfig : ScriptableObject
{
    [System.Serializable]
    public class DecalAtlasEntry
    {
        public string decalId;
        // UV偏移（在Atlas中的位置）
        public Vector4 uvRect; // x=u_start, y=v_start, z=u_size, w=v_size
    }
    
    public Texture2D atlasTexture;
    public List<DecalAtlasEntry> entries = new();
    
    private Dictionary<string, Vector4> _uvCache;
    
    public Vector4 GetUVRect(string decalId)
    {
        if (_uvCache == null)
        {
            _uvCache = new Dictionary<string, Vector4>();
            foreach (var e in entries)
                _uvCache[e.decalId] = e.uvRect;
        }
        
        return _uvCache.TryGetValue(decalId, out var uv) 
               ? uv 
               : new Vector4(0, 0, 1, 1);
    }
}
```

---

## 九、最佳实践总结

### 9.1 方案选型建议

```
目标平台 / 需求
├── 移动端低配：Projector投影（无额外Pass，但有泄漏）
├── 移动端中高配：屏幕空间Decal（需Depth Texture，URP默认开启）
├── PC/主机（写实PBR）：URP DBuffer Decal（修改金属度/粗糙度/法线）
└── PC主机（自定义管线）：Deferred Decal（灵活性最高）
```

### 9.2 性能优化要点

| 优化项 | 说明 | 收益 |
|-------|------|------|
| 对象池 | 避免频繁Instantiate/Destroy | 消除GC Spike |
| LRU淘汰 | 超出池容量时回收最旧Decal | 控制内存上限 |
| 距离剔除 | >25m的Decal禁用渲染 | 减少DrawCall |
| Atlas合批 | 同材质Decal合并为1个DrawCall | 减少50-80% DrawCall |
| Depth Prepass | 屏幕空间Decal依赖深度，确保先渲染 | 避免Decal错位 |
| 角度淡出 | 法线与Decal方向夹角>75°时淡出 | 消除表面拉伸 |

### 9.3 常见问题排查

1. **Decal 出现在错误位置**
   - 检查深度纹理是否正确启用（URP Renderer → Depth Texture = On）
   - 确认 ReversedZ 平台（DX/Metal）的深度处理

2. **Decal 边缘有锯齿/闪烁**
   - 启用 Z Offset（`Offset -1, -1`）
   - 使用 FadeFactor 做边缘衰减

3. **Decal 穿透薄物体（地板/墙壁）**
   - 减小 Projector 深度值（Projection Depth）
   - 使用 Stencil Buffer 标记不应接收贴花的物体

4. **大量弹孔导致帧率下降**
   - 检查池容量是否合理（建议50-100个/类型）
   - 确认 DrawCall 合批是否生效（同种Decal用相同Material Instance）

Decal系统看似简单，实则是连接游戏逻辑与渲染管线的重要桥梁，合理设计可在几乎零性能代价的前提下大幅提升场景真实感。
