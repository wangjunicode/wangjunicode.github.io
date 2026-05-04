---
title: 游戏可破坏环境系统完全指南：运行时Mesh破碎、Voronoi分割与物理碎片管理
published: 2026-05-04
description: 深入讲解游戏中可破坏环境系统的工程实现，涵盖预计算Voronoi破碎、运行时Mesh切割、碎片物理模拟、LOD碎片管理、碎片对象池、碎片消融特效（Shader溶解），以及性能优化策略与URP集成方案。
tags: [Unity, 可破坏环境, Mesh破碎, Voronoi, 物理系统, 游戏开发]
category: 游戏开发
draft: false
---

# 游戏可破坏环境系统完全指南：运行时Mesh破碎、Voronoi分割与物理碎片管理

## 引言

可破坏环境是提升战斗沉浸感的重要元素。《战地》系列的楼体崩塌、《彩虹六号》的墙体破洞、《Control》的超能力破坏——都是这类系统的杰出应用。本文将系统讲解可破坏环境系统的完整工程实现，从预计算Voronoi破碎到运行时高性能碎片管理。

## 系统架构总览

```
DestructionSystem
├── VoronoiFracturePrecompute   // 预计算破碎（编辑器）
├── DestructibleObject          // 可破坏物体组件
├── FractureRuntime             // 运行时破碎触发
├── DebrisPool                  // 碎片对象池
├── DebrisLifecycleManager      // 碎片生命周期管理（自动清理）
├── DestructionShaderFX         // 破碎溶解Shader特效
└── DestructionEventSystem      // 破坏事件通知系统
```

## 一、Voronoi破碎预计算

### 1.1 原理说明

Voronoi图将空间分割为若干"胞腔"，每个胞腔对应一个种子点，腔内任意点到该种子点的距离最近。利用这个特性，我们可以将一个Mesh沿Voronoi边界切割成若干碎片，这正是游戏中破碎效果的数学基础。

```
预计算流程：
原始Mesh → 生成N个随机种子点 → Voronoi分割 → 
对每个胞腔：提取Mesh片段 → 生成内表面（切割面） → 
保存为碎片Prefab → 添加Rigidbody + Collider
```

### 1.2 编辑器预计算工具

```csharp
#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using System.Collections.Generic;
using System.Linq;

public class VoronoiFractureEditor : EditorWindow
{
    private GameObject _targetObject;
    private int _fragmentCount = 20;
    private float _innerTextureScale = 1f;
    private Material _innerMaterial;
    private string _outputPath = "Assets/Prefabs/Destructibles/";
    
    [MenuItem("Tools/Voronoi Fracture")]
    public static void ShowWindow() => GetWindow<VoronoiFractureEditor>("Voronoi Fracture");
    
    private void OnGUI()
    {
        GUILayout.Label("Voronoi破碎工具", EditorStyles.boldLabel);
        _targetObject = EditorGUILayout.ObjectField("目标物体", _targetObject, typeof(GameObject), true) as GameObject;
        _fragmentCount = EditorGUILayout.IntSlider("碎片数量", _fragmentCount, 5, 100);
        _innerTextureScale = EditorGUILayout.Slider("内表面纹理缩放", _innerTextureScale, 0.1f, 5f);
        _innerMaterial = EditorGUILayout.ObjectField("内表面材质", _innerMaterial, typeof(Material), false) as Material;
        _outputPath = EditorGUILayout.TextField("输出路径", _outputPath);
        
        EditorGUILayout.Space();
        if (GUILayout.Button("生成破碎预设体"))
        {
            GenerateFracture();
        }
    }
    
    private void GenerateFracture()
    {
        if (_targetObject == null) { Debug.LogError("请选择目标物体"); return; }
        
        var meshFilter = _targetObject.GetComponent<MeshFilter>();
        if (meshFilter == null || meshFilter.sharedMesh == null)
        {
            Debug.LogError("目标物体没有MeshFilter或Mesh"); return;
        }
        
        Mesh sourceMesh = meshFilter.sharedMesh;
        Bounds bounds = sourceMesh.bounds;
        
        // 生成随机种子点（在Mesh包围盒内）
        List<Vector3> seeds = GenerateSeeds(_fragmentCount, bounds, sourceMesh);
        
        // 创建根容器
        var rootGO = new GameObject($"{_targetObject.name}_Fractured");
        rootGO.transform.SetParent(_targetObject.transform.parent);
        rootGO.transform.localPosition = _targetObject.transform.localPosition;
        
        // 添加DestructibleObject组件
        var destructible = rootGO.AddComponent<DestructibleObject>();
        
        // 为每个Voronoi胞腔生成碎片
        var allFragments = new List<GameObject>();
        for (int i = 0; i < seeds.Count; i++)
        {
            EditorUtility.DisplayProgressBar("生成破碎", $"处理碎片 {i+1}/{seeds.Count}", (float)i / seeds.Count);
            
            Mesh fragmentMesh = ExtractVoronoiCell(sourceMesh, seeds, i);
            if (fragmentMesh == null || fragmentMesh.vertexCount == 0) continue;
            
            var fragmentGO = CreateFragmentPrefab(fragmentMesh, i, _targetObject);
            allFragments.Add(fragmentGO);
            fragmentGO.transform.SetParent(rootGO.transform, true);
        }
        
        EditorUtility.ClearProgressBar();
        
        // 保存为Prefab
        string prefabPath = $"{_outputPath}{_targetObject.name}_Destructible.prefab";
        AssetDatabase.CreateAsset(new Mesh(), prefabPath); // 确保目录存在
        PrefabUtility.SaveAsPrefabAsset(rootGO, prefabPath);
        
        Debug.Log($"破碎预设体已生成：{prefabPath}，共{allFragments.Count}个碎片");
        DestroyImmediate(rootGO);
    }
    
    private List<Vector3> GenerateSeeds(int count, Bounds bounds, Mesh mesh)
    {
        var seeds = new List<Vector3>();
        int attempts = 0;
        
        while (seeds.Count < count && attempts < count * 10)
        {
            attempts++;
            Vector3 candidate = new Vector3(
                UnityEngine.Random.Range(bounds.min.x, bounds.max.x),
                UnityEngine.Random.Range(bounds.min.y, bounds.max.y),
                UnityEngine.Random.Range(bounds.min.z, bounds.max.z)
            );
            
            // 过滤在Mesh外部的种子点（简化版：用包围盒检测）
            seeds.Add(candidate);
        }
        
        return seeds;
    }
    
    private Mesh ExtractVoronoiCell(Mesh sourceMesh, List<Vector3> seeds, int cellIndex)
    {
        // 使用Half-space intersection实现Voronoi Cell提取
        // 对于种子点i，保留满足 dist(v, seeds[i]) < dist(v, seeds[j]) 的顶点区域
        
        var vertices = sourceMesh.vertices;
        var triangles = sourceMesh.triangles;
        var normals = sourceMesh.normals;
        var uvs = sourceMesh.uv;
        
        Vector3 seed = seeds[cellIndex];
        var newVerts = new List<Vector3>();
        var newTris = new List<int>();
        var newNorms = new List<Vector3>();
        var newUVs = new List<Vector2>();
        
        // 遍历三角形，保留属于当前胞腔的三角形
        for (int t = 0; t < triangles.Length; t += 3)
        {
            int i0 = triangles[t], i1 = triangles[t + 1], i2 = triangles[t + 2];
            Vector3 v0 = vertices[i0], v1 = vertices[i1], v2 = vertices[i2];
            Vector3 center = (v0 + v1 + v2) / 3f;
            
            // 检查三角形中心是否属于当前Voronoi胞腔
            if (IsInVoronoiCell(center, seed, seeds))
            {
                int baseIdx = newVerts.Count;
                newVerts.Add(v0); newVerts.Add(v1); newVerts.Add(v2);
                newNorms.Add(normals[i0]); newNorms.Add(normals[i1]); newNorms.Add(normals[i2]);
                if (uvs.Length > 0)
                {
                    newUVs.Add(uvs[i0]); newUVs.Add(uvs[i1]); newUVs.Add(uvs[i2]);
                }
                newTris.Add(baseIdx); newTris.Add(baseIdx + 1); newTris.Add(baseIdx + 2);
            }
        }
        
        if (newVerts.Count == 0) return null;
        
        var mesh = new Mesh();
        mesh.name = $"Fragment_{cellIndex}";
        mesh.vertices = newVerts.ToArray();
        mesh.triangles = newTris.ToArray();
        mesh.normals = newNorms.ToArray();
        if (newUVs.Count > 0) mesh.uv = newUVs.ToArray();
        mesh.RecalculateBounds();
        
        return mesh;
    }
    
    private bool IsInVoronoiCell(Vector3 point, Vector3 seed, List<Vector3> allSeeds)
    {
        float minDist = Vector3.SqrMagnitude(point - seed);
        foreach (var otherSeed in allSeeds)
        {
            if (otherSeed == seed) continue;
            if (Vector3.SqrMagnitude(point - otherSeed) < minDist) return false;
        }
        return true;
    }
    
    private GameObject CreateFragmentPrefab(Mesh mesh, int index, GameObject original)
    {
        var go = new GameObject($"Fragment_{index}");
        
        // Mesh组件
        go.AddComponent<MeshFilter>().sharedMesh = mesh;
        var renderer = go.AddComponent<MeshRenderer>();
        renderer.sharedMaterial = original.GetComponent<MeshRenderer>()?.sharedMaterial;
        
        // 物理组件（初始禁用，破碎时启用）
        var rb = go.AddComponent<Rigidbody>();
        rb.isKinematic = true; // 未破碎时不参与物理
        
        var col = go.AddComponent<MeshCollider>();
        col.sharedMesh = mesh;
        col.convex = true; // Rigidbody要求凸包碰撞器
        
        // 碎片组件
        go.AddComponent<DestructionFragment>();
        
        return go;
    }
}
#endif
```

## 二、可破坏物体运行时组件

### 2.1 DestructibleObject

```csharp
public class DestructibleObject : MonoBehaviour
{
    [Header("破碎参数")]
    [SerializeField] private float _maxHealth = 100f;
    [SerializeField] private float _fractureThreshold = 30f; // 单次伤害超过此值才触发破碎
    [SerializeField] private bool _breakOnAnyDamage = false;
    
    [Header("碎片参数")]
    [SerializeField] private float _explosionForce = 500f;
    [SerializeField] private float _explosionRadius = 2f;
    [SerializeField] private float _upwardsModifier = 0.5f;
    [SerializeField] private float _fragmentLifetime = 10f;
    
    [Header("特效")]
    [SerializeField] private GameObject _breakVFX;
    [SerializeField] private AudioClip _breakSound;
    [SerializeField] private bool _useDissolveEffect = true;
    [SerializeField] private float _dissolveDelay = 5f;
    
    private float _currentHealth;
    private bool _isBroken;
    private List<DestructionFragment> _fragments;
    private Collider _intactCollider;
    private MeshRenderer _intactRenderer;
    
    // 事件
    public event Action<DestructibleObject> OnBroken;
    public event Action<float, float> OnDamaged; // current, max
    
    private void Awake()
    {
        _currentHealth = _maxHealth;
        _fragments = new List<DestructionFragment>(GetComponentsInChildren<DestructionFragment>());
        _intactCollider = GetComponent<Collider>();
        _intactRenderer = GetComponent<MeshRenderer>();
        
        // 初始状态：碎片隐藏，完整体显示
        SetFragmentsActive(false);
    }
    
    public void TakeDamage(float damage, Vector3 hitPoint, Vector3 hitForce)
    {
        if (_isBroken) return;
        
        _currentHealth -= damage;
        OnDamaged?.Invoke(_currentHealth, _maxHealth);
        
        bool shouldFracture = _breakOnAnyDamage || damage >= _fractureThreshold || _currentHealth <= 0;
        
        if (shouldFracture)
        {
            Fracture(hitPoint, hitForce);
        }
    }
    
    public void Fracture(Vector3 hitPoint, Vector3 hitForce)
    {
        if (_isBroken) return;
        _isBroken = true;
        
        // 隐藏完整体
        if (_intactCollider != null) _intactCollider.enabled = false;
        if (_intactRenderer != null) _intactRenderer.enabled = false;
        
        // 激活碎片
        SetFragmentsActive(true);
        
        // 对碎片施加爆炸力
        foreach (var fragment in _fragments)
        {
            fragment.ActivatePhysics(hitPoint, _explosionForce, _explosionRadius, _upwardsModifier);
            
            if (_useDissolveEffect)
            {
                fragment.StartDissolve(_dissolveDelay, _fragmentLifetime);
            }
            else
            {
                fragment.ScheduleDestroy(_fragmentLifetime);
            }
        }
        
        // 播放特效
        if (_breakVFX != null)
        {
            var vfx = Instantiate(_breakVFX, hitPoint, Quaternion.identity);
            Destroy(vfx, 5f);
        }
        
        if (_breakSound != null)
        {
            AudioSource.PlayClipAtPoint(_breakSound, transform.position, 0.8f);
        }
        
        OnBroken?.Invoke(this);
        
        // 通知事件系统
        DestructionEventSystem.Instance?.NotifyObjectBroken(this, hitPoint);
    }
    
    private void SetFragmentsActive(bool active)
    {
        foreach (var frag in _fragments)
        {
            frag.gameObject.SetActive(active);
        }
    }
    
    // 恢复物体（可选，用于关卡重置）
    public void Restore()
    {
        _isBroken = false;
        _currentHealth = _maxHealth;
        
        if (_intactCollider != null) _intactCollider.enabled = true;
        if (_intactRenderer != null) _intactRenderer.enabled = true;
        
        SetFragmentsActive(false);
        
        foreach (var frag in _fragments)
        {
            frag.ResetFragment();
        }
    }
}
```

### 2.2 碎片组件

```csharp
[RequireComponent(typeof(Rigidbody))]
public class DestructionFragment : MonoBehaviour
{
    private Rigidbody _rb;
    private MeshRenderer _renderer;
    private Vector3 _originalLocalPosition;
    private Quaternion _originalLocalRotation;
    
    // Shader溶解参数
    private static readonly int DissolveAmount = Shader.PropertyToID("_DissolveAmount");
    private Material _dissolveMaterial;
    private Coroutine _dissolveCoroutine;
    
    private void Awake()
    {
        _rb = GetComponent<Rigidbody>();
        _renderer = GetComponent<MeshRenderer>();
        _originalLocalPosition = transform.localPosition;
        _originalLocalRotation = transform.localRotation;
    }
    
    public void ActivatePhysics(Vector3 explosionCenter, float force, float radius, float upModifier)
    {
        _rb.isKinematic = false;
        _rb.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
        
        // 爆炸力
        _rb.AddExplosionForce(force, explosionCenter, radius, upModifier, ForceMode.Impulse);
        
        // 随机旋转扭力
        _rb.AddTorque(UnityEngine.Random.insideUnitSphere * force * 0.1f, ForceMode.Impulse);
    }
    
    public void StartDissolve(float delay, float totalLifetime)
    {
        if (_dissolveCoroutine != null) StopCoroutine(_dissolveCoroutine);
        _dissolveCoroutine = StartCoroutine(DissolveCoroutine(delay, totalLifetime - delay));
    }
    
    private IEnumerator DissolveCoroutine(float delay, float dissolveDuration)
    {
        yield return new WaitForSeconds(delay);
        
        // 创建材质实例（避免修改共享材质）
        if (_dissolveMaterial == null && _renderer != null)
        {
            _dissolveMaterial = new Material(_renderer.sharedMaterial);
            _renderer.sharedMaterial = _dissolveMaterial;
        }
        
        float elapsed = 0f;
        while (elapsed < dissolveDuration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / dissolveDuration;
            
            _dissolveMaterial?.SetFloat(DissolveAmount, t);
            
            yield return null;
        }
        
        ReturnToPool();
    }
    
    public void ScheduleDestroy(float lifetime)
    {
        StartCoroutine(DestroyAfterDelay(lifetime));
    }
    
    private IEnumerator DestroyAfterDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        ReturnToPool();
    }
    
    private void ReturnToPool()
    {
        // 如果使用对象池则归还，否则直接销毁
        DebrisPool.Instance?.Return(this);
        if (this != null && gameObject != null) gameObject.SetActive(false);
    }
    
    public void ResetFragment()
    {
        if (_dissolveCoroutine != null)
        {
            StopCoroutine(_dissolveCoroutine);
            _dissolveCoroutine = null;
        }
        
        _rb.isKinematic = true;
        _rb.linearVelocity = Vector3.zero;
        _rb.angularVelocity = Vector3.zero;
        
        transform.localPosition = _originalLocalPosition;
        transform.localRotation = _originalLocalRotation;
        
        if (_dissolveMaterial != null)
        {
            _dissolveMaterial.SetFloat(DissolveAmount, 0f);
        }
    }
}
```

## 三、碎片溶解Shader（URP）

```hlsl
// FragmentDissolve.shader
Shader "Custom/FragmentDissolve"
{
    Properties
    {
        _BaseMap ("Albedo", 2D) = "white" {}
        _NormalMap ("Normal Map", 2D) = "bump" {}
        _DissolveMap ("Dissolve Noise", 2D) = "white" {}
        _DissolveAmount ("Dissolve Amount", Range(0, 1)) = 0
        _DissolveEdgeWidth ("Edge Width", Range(0, 0.1)) = 0.02
        _DissolveEdgeColor ("Edge Color", Color) = (1, 0.5, 0, 1)
        _DissolveEdgeEmission ("Edge Emission", Float) = 3.0
    }
    
    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "RenderPipeline"="UniversalPipeline" "Queue"="AlphaTest" }
        
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode"="UniversalForward" }
            Cull Off // 双面渲染（碎片内表面可见）
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma shader_feature_local _NORMALMAP
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            TEXTURE2D(_BaseMap); SAMPLER(sampler_BaseMap);
            TEXTURE2D(_NormalMap); SAMPLER(sampler_NormalMap);
            TEXTURE2D(_DissolveMap); SAMPLER(sampler_DissolveMap);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float4 _DissolveMap_ST;
                float _DissolveAmount;
                float _DissolveEdgeWidth;
                float4 _DissolveEdgeColor;
                float _DissolveEdgeEmission;
            CBUFFER_END
            
            struct Attributes {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                float3 normalOS : NORMAL;
                float4 tangentOS : TANGENT;
            };
            
            struct Varyings {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 positionWS : TEXCOORD1;
                float3 normalWS : TEXCOORD2;
                float3 tangentWS : TEXCOORD3;
                float3 bitangentWS : TEXCOORD4;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.positionWS = TransformObjectToWorld(IN.positionOS.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _BaseMap);
                OUT.normalWS = TransformObjectToWorldNormal(IN.normalOS);
                float3 tangentWS = TransformObjectToWorldDir(IN.tangentOS.xyz);
                OUT.tangentWS = tangentWS;
                OUT.bitangentWS = cross(OUT.normalWS, tangentWS) * IN.tangentOS.w;
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                // 溶解噪声采样
                float2 dissolveUV = TRANSFORM_TEX(IN.uv, _DissolveMap);
                float noise = SAMPLE_TEXTURE2D(_DissolveMap, sampler_DissolveMap, dissolveUV).r;
                
                // 溶解裁剪（主体部分）
                float threshold = _DissolveAmount;
                clip(noise - threshold);
                
                // 边缘发光
                float edgeFactor = 1 - saturate((noise - threshold) / _DissolveEdgeWidth);
                
                // 采样颜色和法线
                half4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, IN.uv);
                half3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, IN.uv));
                
                float3x3 TBN = float3x3(IN.tangentWS, IN.bitangentWS, IN.normalWS);
                float3 normalWS = normalize(TransformTangentToWorld(normalTS, TBN));
                
                // PBR光照
                InputData inputData = (InputData)0;
                inputData.positionWS = IN.positionWS;
                inputData.normalWS = normalWS;
                inputData.viewDirectionWS = GetWorldSpaceNormalizeViewDir(IN.positionWS);
                
                SurfaceData surfaceData = (SurfaceData)0;
                surfaceData.albedo = baseColor.rgb;
                surfaceData.smoothness = 0.5;
                surfaceData.alpha = 1;
                // 边缘加入橙色自发光
                surfaceData.emission = _DissolveEdgeColor.rgb * edgeFactor * _DissolveEdgeEmission;
                
                return UniversalFragmentPBR(inputData, surfaceData);
            }
            ENDHLSL
        }
        
        // ShadowCaster Pass（带溶解裁剪）
        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode"="ShadowCaster" }
            
            HLSLPROGRAM
            #pragma vertex vertShadow
            #pragma fragment fragShadow
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"
            
            TEXTURE2D(_DissolveMap); SAMPLER(sampler_DissolveMap);
            CBUFFER_START(UnityPerMaterial)
                float4 _DissolveMap_ST;
                float _DissolveAmount;
            CBUFFER_END
            
            struct AttrShadow { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct VarShadow { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            
            VarShadow vertShadow(AttrShadow IN)
            {
                VarShadow OUT;
                OUT.pos = TransformObjectToHClip(IN.pos.xyz);
                OUT.uv = IN.uv;
                return OUT;
            }
            
            half4 fragShadow(VarShadow IN) : SV_Target
            {
                float noise = SAMPLE_TEXTURE2D(_DissolveMap, sampler_DissolveMap, IN.uv).r;
                clip(noise - _DissolveAmount);
                return 0;
            }
            ENDHLSL
        }
    }
}
```

## 四、碎片对象池

```csharp
public class DebrisPool : MonoBehaviour
{
    public static DebrisPool Instance { get; private set; }
    
    [System.Serializable]
    public class DebrisPoolEntry
    {
        public string Key;
        public DestructionFragment Prefab;
        public int InitialSize = 20;
        public int MaxSize = 100;
    }
    
    [SerializeField] private List<DebrisPoolEntry> _poolEntries;
    
    private Dictionary<string, Queue<DestructionFragment>> _pools;
    private Dictionary<string, DebrisPoolEntry> _configs;
    
    // 全局碎片数量限制（性能保护）
    [SerializeField] private int _globalMaxDebris = 200;
    private int _activeDebrisCount;
    
    private void Awake()
    {
        if (Instance == null) Instance = this;
        else { Destroy(gameObject); return; }
        
        InitializePools();
    }
    
    private void InitializePools()
    {
        _pools = new Dictionary<string, Queue<DestructionFragment>>();
        _configs = new Dictionary<string, DebrisPoolEntry>();
        
        foreach (var entry in _poolEntries)
        {
            var queue = new Queue<DestructionFragment>();
            for (int i = 0; i < entry.InitialSize; i++)
            {
                var instance = Instantiate(entry.Prefab, transform);
                instance.gameObject.SetActive(false);
                queue.Enqueue(instance);
            }
            _pools[entry.Key] = queue;
            _configs[entry.Key] = entry;
        }
    }
    
    public DestructionFragment Get(string key, Vector3 position, Quaternion rotation)
    {
        if (_activeDebrisCount >= _globalMaxDebris)
        {
            // 超出上限，强制回收最旧的碎片
            RecycleOldestDebris();
        }
        
        if (!_pools.TryGetValue(key, out var pool)) return null;
        
        DestructionFragment fragment;
        if (pool.Count > 0)
        {
            fragment = pool.Dequeue();
        }
        else if (_configs[key].MaxSize > CountActive(key))
        {
            fragment = Instantiate(_configs[key].Prefab, transform);
        }
        else
        {
            return null; // 达到上限
        }
        
        fragment.transform.SetPositionAndRotation(position, rotation);
        fragment.gameObject.SetActive(true);
        _activeDebrisCount++;
        
        return fragment;
    }
    
    public void Return(DestructionFragment fragment)
    {
        if (fragment == null) return;
        
        fragment.ResetFragment();
        fragment.gameObject.SetActive(false);
        fragment.transform.SetParent(transform);
        
        // 根据Prefab名找到对应的池
        string key = GetKeyForFragment(fragment);
        if (key != null && _pools.TryGetValue(key, out var pool))
        {
            pool.Enqueue(fragment);
        }
        
        _activeDebrisCount = Mathf.Max(0, _activeDebrisCount - 1);
    }
    
    private void RecycleOldestDebris()
    {
        // 找到最旧的活跃碎片并回收
        var activeFragments = FindObjectsByType<DestructionFragment>(FindObjectsSortMode.None);
        if (activeFragments.Length > 0)
        {
            Return(activeFragments[0]);
        }
    }
    
    private int CountActive(string key) =>
        FindObjectsByType<DestructionFragment>(FindObjectsSortMode.None).Length;
    
    private string GetKeyForFragment(DestructionFragment fragment) =>
        fragment.gameObject.name.Replace("(Clone)", "").Trim();
}
```

## 五、部分破坏系统（墙体打洞）

```csharp
// 墙体打洞：不完全破碎，只在命中点形成洞口
public class WallPenetrationSystem : MonoBehaviour
{
    [SerializeField] private GameObject _holeDecalPrefab; // 洞口贴花
    [SerializeField] private GameObject _debrisPrefab;    // 飞出的碎屑
    [SerializeField] private int _maxHolesPerWall = 5;
    [SerializeField] private LayerMask _wallLayer;
    
    private List<GameObject> _holes = new List<GameObject>();
    
    // 在墙体上形成弹孔/洞口
    public void CreateHole(Vector3 hitPoint, Vector3 hitNormal, float bulletPower)
    {
        if (_holes.Count >= _maxHolesPerWall)
        {
            // 删除最旧的洞
            var oldest = _holes[0];
            _holes.RemoveAt(0);
            Destroy(oldest);
        }
        
        // 根据子弹穿透力决定洞口大小
        float holeSize = Mathf.Lerp(0.05f, 0.3f, bulletPower / 100f);
        
        // 创建洞口贴花（正面+背面）
        var holeFront = Instantiate(_holeDecalPrefab, hitPoint + hitNormal * 0.01f, 
                                    Quaternion.LookRotation(-hitNormal));
        holeFront.transform.localScale = Vector3.one * holeSize;
        _holes.Add(holeFront);
        
        // 背面出口（稍大）
        if (bulletPower > 30f)
        {
            // Raycast找背面
            if (Physics.Raycast(hitPoint + hitNormal * 0.1f, -hitNormal, out RaycastHit backHit, 
                                  1f, _wallLayer))
            {
                var holeBack = Instantiate(_holeDecalPrefab, backHit.point - hitNormal * 0.01f,
                                           Quaternion.LookRotation(hitNormal));
                holeBack.transform.localScale = Vector3.one * holeSize * 1.5f;
                _holes.Add(holeBack);
            }
        }
        
        // 飞出碎屑
        SpawnWallDebris(hitPoint, hitNormal, bulletPower);
    }
    
    private void SpawnWallDebris(Vector3 hitPoint, Vector3 hitNormal, float power)
    {
        if (_debrisPrefab == null) return;
        
        int count = Mathf.RoundToInt(Mathf.Lerp(3, 15, power / 100f));
        for (int i = 0; i < count; i++)
        {
            var debris = Instantiate(_debrisPrefab, hitPoint, UnityEngine.Random.rotation);
            var rb = debris.GetComponent<Rigidbody>();
            if (rb != null)
            {
                // 向命中方向的反方向飞出
                Vector3 dir = -hitNormal + UnityEngine.Random.insideUnitSphere * 0.5f;
                rb.AddForce(dir * power * 3f, ForceMode.Impulse);
                rb.AddTorque(UnityEngine.Random.insideUnitSphere * 5f, ForceMode.Impulse);
            }
            Destroy(debris, 5f);
        }
    }
}
```

## 六、性能优化策略

### 6.1 LOD碎片系统

```csharp
public class DestructionLODManager : MonoBehaviour
{
    [Serializable]
    public class LODLevel
    {
        public float Distance;
        public int MaxFragments;
        public bool UsePhysics;
        public bool UseDissolve;
    }
    
    [SerializeField] private List<LODLevel> _lodLevels;
    
    private Camera _mainCamera;
    
    private void Start()
    {
        _mainCamera = Camera.main;
    }
    
    public LODLevel GetLODForDistance(float distance)
    {
        for (int i = 0; i < _lodLevels.Count; i++)
        {
            if (distance <= _lodLevels[i].Distance) return _lodLevels[i];
        }
        return _lodLevels[^1];
    }
    
    // 远处破碎：直接隐藏，不激活物理（节省性能）
    public void ApplyDistanceCulling(DestructibleObject destructible, float distance)
    {
        var lod = GetLODForDistance(distance);
        
        if (!lod.UsePhysics)
        {
            // 超过距离阈值：直接隐藏完整体，不启用碎片物理
            destructible.FractureWithoutPhysics();
        }
    }
}
```

### 6.2 破坏预算系统

```csharp
// 全局破坏预算：限制每帧激活的新碎片数量
public class DestructionBudget : MonoBehaviour
{
    public static DestructionBudget Instance { get; private set; }
    
    [SerializeField] private int _maxNewFragmentsPerFrame = 30;
    [SerializeField] private int _maxTotalActiveFragments = 300;
    
    private int _newFragmentsThisFrame;
    private int _totalActiveFragments;
    
    private void Awake()
    {
        if (Instance == null) Instance = this;
        else Destroy(gameObject);
    }
    
    private void LateUpdate()
    {
        _newFragmentsThisFrame = 0; // 每帧重置
    }
    
    public bool CanActivateFragment()
    {
        return _newFragmentsThisFrame < _maxNewFragmentsPerFrame
            && _totalActiveFragments < _maxTotalActiveFragments;
    }
    
    public void OnFragmentActivated() 
    { 
        _newFragmentsThisFrame++; 
        _totalActiveFragments++;
    }
    
    public void OnFragmentDeactivated() 
    { 
        _totalActiveFragments = Mathf.Max(0, _totalActiveFragments - 1);
    }
}
```

## 七、破坏事件系统

```csharp
public class DestructionEventSystem : MonoBehaviour
{
    public static DestructionEventSystem Instance { get; private set; }
    
    // 破坏事件（供AI、音频、成就等系统订阅）
    public event Action<DestructibleObject, Vector3> OnObjectBroken;
    public event Action<Vector3, float> OnExplosionEvent; // 中心点，力量
    
    private void Awake()
    {
        if (Instance == null) Instance = this;
        else Destroy(gameObject);
    }
    
    public void NotifyObjectBroken(DestructibleObject obj, Vector3 breakPoint)
    {
        OnObjectBroken?.Invoke(obj, breakPoint);
    }
    
    public void NotifyExplosion(Vector3 center, float force)
    {
        // 自动触发范围内所有可破坏物体
        Collider[] cols = Physics.OverlapSphere(center, force / 200f);
        foreach (var col in cols)
        {
            var destructible = col.GetComponentInParent<DestructibleObject>();
            destructible?.TakeDamage(force * 0.5f, center, (col.transform.position - center).normalized * force);
        }
        
        OnExplosionEvent?.Invoke(center, force);
    }
}
```

## 八、最佳实践总结

| 方面 | 建议 |
|------|------|
| **预计算 vs 运行时** | 优先预计算Voronoi破碎，运行时只需激活预制体，避免运行时Mesh切割的巨大开销 |
| **碎片数量** | 单次破碎碎片数控制在10-30个，超过30个对玩家视觉提升有限但性能开销倍增 |
| **物理碰撞器** | 碎片使用convex MeshCollider或简化为Box/Sphere，避免concave碰撞器 |
| **全局上限** | 设置全局碎片上限（如200个），超出时自动回收最旧的碎片 |
| **LOD策略** | 50m内完整物理+溶解，50-100m仅视觉动画，100m外直接隐藏 |
| **内表面材质** | 切割内表面要使用单独材质（石头内部、木材横截面等），增强真实感 |
| **远距破坏** | 远处的破坏可以不激活物理，只播放破碎特效，大幅节省CPU |
| **可恢复性** | 在多局游戏中设计破坏恢复机制，避免关卡越玩越残破 |

## 结语

可破坏环境系统的核心挑战在于**视觉效果与性能的权衡**。通过预计算Voronoi破碎消除运行时开销、碎片对象池避免频繁GC、全局破坏预算保护帧率，可以在保持出色破坏效果的同时，将运行时开销控制在可接受范围内。溶解Shader为碎片消失提供了电影级的视觉过渡，而事件总线则保证了整个系统与其他游戏逻辑的干净解耦。
