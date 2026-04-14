---
title: Unity模板缓冲深度实践：Stencil Buffer、描边轮廓、Portal传送门与平面反射完全指南
published: 2026-04-14
description: 深度解析Unity中模板缓冲（Stencil Buffer）的工作原理与高级应用，涵盖角色选中描边、室内场景Portal传送门渲染、平面镜反射、X-Ray透视效果及URP中自定义模板通道的完整实现方案。
tags: [Unity, Shader, 渲染, Stencil, 图形编程]
category: 渲染技术
draft: false
---

# Unity模板缓冲深度实践：Stencil Buffer、描边轮廓、Portal传送门与平面反射完全指南

## 1. 模板缓冲原理

模板缓冲（Stencil Buffer）是与深度缓冲（Depth Buffer）并列的逐像素缓冲区，每个像素存储一个 8-bit 无符号整数（0~255）。通过对模板值的读取和写入操作，可以精确控制哪些像素参与后续渲染，实现传统方法难以实现的效果。

### 模板测试流程

```
像素着色器输出
      ↓
模板测试 (Stencil Test)
  参考值 (Ref) 与缓冲中的存储值 (stencilBuffer) 比较
  比较方式 (Comp): Always / Equal / NotEqual / Less / ...
      ↓
[通过]              [失败]
  继续深度测试          执行 Fail 操作后丢弃
      ↓
深度测试
  [通过]          [深度失败]
  执行 Pass 操作    执行 ZFail 操作
      ↓
写入帧缓冲
```

### Stencil 操作类型

| 操作名 | 说明 |
|--------|------|
| Keep   | 保持当前值不变 |
| Zero   | 置为 0 |
| Replace| 替换为 Ref 值 |
| IncrSat| 加 1，饱和到 255 |
| DecrSat| 减 1，饱和到 0 |
| Invert | 按位取反 |
| IncrWrap| 加 1，超出 255 回绕到 0 |
| DecrWrap| 减 1，低于 0 回绕到 255 |

## 2. 基础描边效果（Stencil 版）

与传统后处理描边不同，基于模板缓冲的描边效果精确、无锯齿，且不受遮挡影响。

### Shader 实现

```hlsl
// 第一个 Pass：将选中物体写入模板缓冲（不渲染颜色）
Shader "Custom/OutlineStencil"
{
    Properties
    {
        _OutlineColor ("Outline Color", Color) = (1, 0.5, 0, 1)
        _OutlineWidth ("Outline Width", Range(0, 10)) = 3
    }
    
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" }
        
        // Pass 1: 写入模板标记（渲染物体本身）
        Pass
        {
            Name "StencilMask"
            
            Stencil
            {
                Ref 1            // 参考值
                Comp Always      // 始终通过模板测试
                Pass Replace     // 通过后写入 Ref 值（1）到模板缓冲
                ZFail Keep       // 深度测试失败时保持模板值
            }
            
            ColorMask 0          // 不写入颜色（只更新模板）
            ZWrite On
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            struct Attributes { float4 positionOS : POSITION; };
            struct Varyings { float4 positionCS : SV_POSITION; };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target { return 0; }
            ENDHLSL
        }
        
        // Pass 2: 膨胀的轮廓（在模板值为0的区域渲染）
        Pass
        {
            Name "OutlinePass"
            
            Stencil
            {
                Ref 1
                Comp NotEqual    // 只在模板值不等于1的像素（即轮廓区域）渲染
                Pass Keep
            }
            
            Cull Front           // 渲染背面实现膨胀效果
            ZWrite Off
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            CBUFFER_START(UnityPerMaterial)
                half4 _OutlineColor;
                float _OutlineWidth;
            CBUFFER_END
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                // 沿法线方向膨胀顶点
                float3 expandedPos = IN.positionOS.xyz + IN.normalOS * _OutlineWidth * 0.01;
                OUT.positionCS = TransformObjectToHClip(expandedPos);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                return _OutlineColor;
            }
            ENDHLSL
        }
    }
}
```

### C# 控制选中高亮

```csharp
public class SelectionOutline : MonoBehaviour
{
    private static readonly int StencilRefProperty = Shader.PropertyToID("_StencilRef");
    
    private Renderer[] renderers;
    private bool isSelected;
    
    [SerializeField] private Material outlineMaterial;
    
    private void Awake()
    {
        renderers = GetComponentsInChildren<Renderer>();
    }
    
    public void SetSelected(bool selected)
    {
        if (isSelected == selected) return;
        isSelected = selected;
        
        foreach (var r in renderers)
        {
            var mats = r.sharedMaterials.ToList();
            if (selected)
            {
                if (!mats.Contains(outlineMaterial))
                    mats.Add(outlineMaterial);
            }
            else
            {
                mats.Remove(outlineMaterial);
            }
            r.materials = mats.ToArray();
        }
    }
}
```

## 3. X-Ray 透视效果

透过墙壁看到隐藏角色，常见于 MOBA、战术射击游戏的敌人标记。

```hlsl
Shader "Custom/XRay"
{
    Properties
    {
        _XRayColor ("X-Ray Color", Color) = (0, 1, 1, 0.5)
    }
    
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent+100" }
        
        // Pass 1: 正常渲染（深度测试通过时不显示 X-Ray）
        Pass
        {
            Name "NormalPass"
            
            Stencil
            {
                Ref 2
                Comp Always
                Pass Replace
            }
            
            ZTest Less
            ZWrite On
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            struct Attributes { float4 positionOS : POSITION; };
            struct Varyings { float4 positionCS : SV_POSITION; };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target { return 0; } // 正常渲染由其他 Pass 处理
            ENDHLSL
        }
        
        // Pass 2: 深度测试失败时显示 X-Ray 颜色
        Pass
        {
            Name "XRayPass"
            
            Stencil
            {
                Ref 2
                Comp NotEqual    // 没有被正常 Pass 覆盖的像素
            }
            
            ZTest Greater        // 被遮挡的部分
            ZWrite Off
            Blend SrcAlpha OneMinusSrcAlpha
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            CBUFFER_START(UnityPerMaterial)
                half4 _XRayColor;
            CBUFFER_END
            
            struct Attributes { float4 positionOS : POSITION; };
            struct Varyings { float4 positionCS : SV_POSITION; };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                return _XRayColor;
            }
            ENDHLSL
        }
    }
}
```

## 4. Portal 传送门渲染

Portal 效果需要在传送门开口处渲染出另一个位置的画面，是模板缓冲最经典的高级用法。

### 实现原理

```
1. 用模板缓冲标记传送门轮廓（标记为 1）
2. 在标记区域内，从目标位置的虚拟相机渲染场景
3. 实现"从A看到B"的视觉效果
```

### PortalRenderer.cs

```csharp
public class PortalRenderer : MonoBehaviour
{
    [Header("Portal 配置")]
    [SerializeField] private Transform linkedPortal;     // 目标传送门
    [SerializeField] private Camera portalCamera;        // 用于渲染目标视角的相机
    [SerializeField] private RenderTexture portalRT;
    [SerializeField] private MeshRenderer portalSurface; // 传送门表面
    [SerializeField] private int stencilId = 1;
    
    private Camera mainCamera;
    
    private void Start()
    {
        mainCamera = Camera.main;
        
        // 创建 RenderTexture
        portalRT = new RenderTexture(Screen.width, Screen.height, 24);
        portalRT.name = $"PortalRT_{name}";
        portalCamera.targetTexture = portalRT;
        
        // 将 RT 赋给传送门表面的材质
        portalSurface.material.SetTexture("_MainTex", portalRT);
        portalSurface.material.SetInt("_StencilRef", stencilId);
    }
    
    private void OnRenderObject()
    {
        RenderPortal();
    }
    
    private void RenderPortal()
    {
        // 根据玩家相对于此传送门的姿态，计算 portalCamera 应处于目标传送门的哪个位置
        // 1. 玩家到此传送门的相对变换
        Matrix4x4 relativeMatrix = linkedPortal.worldToLocalMatrix * mainCamera.transform.localToWorldMatrix;
        // 旋转 180° 以修正出口方向
        Matrix4x4 rotationFix = Matrix4x4.TRS(Vector3.zero, Quaternion.Euler(0, 180, 0), Vector3.one);
        Matrix4x4 portalCameraMatrix = transform.localToWorldMatrix * rotationFix * relativeMatrix;
        
        portalCamera.transform.SetPositionAndRotation(
            portalCameraMatrix.GetColumn(3),
            portalCameraMatrix.rotation
        );
        
        // 设置斜截面裁切（只渲染传送门后面的内容，避免出现在传送门前面的物体被渲染）
        SetObliqueProjection(portalCamera, linkedPortal);
        
        portalCamera.Render();
    }
    
    /// <summary>
    /// 设置斜截面矩阵，确保传送门相机只渲染传送门后方的内容
    /// </summary>
    private void SetObliqueProjection(Camera cam, Transform portal)
    {
        Vector4 clipPlane = CameraSpacePlane(cam, portal.position, portal.forward);
        cam.projectionMatrix = cam.CalculateObliqueMatrix(clipPlane);
    }
    
    private Vector4 CameraSpacePlane(Camera cam, Vector3 pos, Vector3 normal)
    {
        // 平面法向量（世界空间）朝向相机空间转换
        Matrix4x4 worldToCamera = cam.worldToCameraMatrix;
        Vector3 cameraPos = worldToCamera.MultiplyPoint(pos);
        Vector3 cameraNormal = worldToCamera.MultiplyVector(normal).normalized;
        return new Vector4(cameraNormal.x, cameraNormal.y, cameraNormal.z,
            -Vector3.Dot(cameraPos, cameraNormal));
    }
    
    private void OnDestroy()
    {
        if (portalRT != null)
            portalRT.Release();
    }
}
```

### Portal Surface Shader

```hlsl
Shader "Custom/PortalSurface"
{
    Properties
    {
        _MainTex ("Portal View", 2D) = "black" {}
    }
    
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry+1" }
        
        Pass
        {
            Name "PortalSurface"
            
            // 第一步：在传送门表面区域写入模板值
            Stencil
            {
                Ref 1
                Comp Always
                Pass Replace
            }
            
            ZWrite On
            ZTest LEqual
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);
            
            struct Attributes
            {
                float4 positionOS : POSITION;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float4 screenPos  : TEXCOORD0;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.screenPos = ComputeScreenPos(OUT.positionCS);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                // 使用屏幕空间UV采样 RenderTexture（实现透视投影校正）
                float2 screenUV = IN.screenPos.xy / IN.screenPos.w;
                return SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, screenUV);
            }
            ENDHLSL
        }
    }
}
```

## 5. 平面镜反射

利用模板缓冲只在镜子范围内渲染反射场景，避免反射图像溢出到镜子外。

```csharp
public class PlanarMirror : MonoBehaviour
{
    [SerializeField] private Camera reflectionCamera;
    [SerializeField] private RenderTexture reflectionRT;
    [SerializeField] private MeshRenderer mirrorSurface;
    [SerializeField] private LayerMask reflectionLayers = -1;
    
    private Camera mainCamera;
    private static readonly int ReflectionTex = Shader.PropertyToID("_ReflectionTex");
    
    private void Start()
    {
        mainCamera = Camera.main;
        reflectionRT = new RenderTexture(1024, 1024, 24)
        {
            name = "MirrorReflection",
            antiAliasing = 2
        };
        reflectionCamera.targetTexture = reflectionRT;
        mirrorSurface.material.SetTexture(ReflectionTex, reflectionRT);
    }
    
    private void LateUpdate()
    {
        RenderReflection();
    }
    
    private void RenderReflection()
    {
        // 获取镜面平面（法线方向朝向相机的面）
        Vector3 mirrorNormal = transform.up;
        Vector3 mirrorPos = transform.position;
        
        // 计算镜像相机的位置（主相机关于镜面的对称点）
        Vector3 camPos = mainCamera.transform.position;
        float dist = Vector3.Dot(mirrorNormal, camPos - mirrorPos);
        Vector3 reflectedCamPos = camPos - 2 * dist * mirrorNormal;
        
        // 计算镜像后的视方向
        Vector3 camDir = mainCamera.transform.forward;
        Vector3 reflectedDir = Vector3.Reflect(camDir, mirrorNormal);
        
        reflectionCamera.transform.position = reflectedCamPos;
        reflectionCamera.transform.forward = reflectedDir;
        reflectionCamera.projectionMatrix = mainCamera.projectionMatrix;
        reflectionCamera.cullingMask = reflectionLayers;
        
        // 翻转渲染（反射图像是左右镜像的）
        GL.invertCulling = true;
        reflectionCamera.Render();
        GL.invertCulling = false;
    }
}
```

### Mirror Surface Shader

```hlsl
Shader "Custom/MirrorSurface"
{
    Properties
    {
        _ReflectionTex ("Reflection", 2D) = "white" {}
        _Smoothness ("Smoothness", Range(0, 1)) = 0.95
        _Metallic ("Metallic", Range(0, 1)) = 0.9
        _Tint ("Mirror Tint", Color) = (0.9, 0.9, 0.9, 1)
    }
    
    SubShader
    {
        Tags { "RenderType" = "Opaque" }
        
        Pass
        {
            Name "MirrorPass"
            
            Stencil
            {
                Ref 2
                Comp Always
                Pass Replace
            }
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            TEXTURE2D(_ReflectionTex);
            SAMPLER(sampler_ReflectionTex);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _ReflectionTex_ST;
                half _Smoothness;
                half _Metallic;
                half4 _Tint;
            CBUFFER_END
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float4 screenPos  : TEXCOORD0;
                float3 normalWS   : TEXCOORD1;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.screenPos = ComputeScreenPos(OUT.positionCS);
                OUT.normalWS = TransformObjectToWorldNormal(IN.normalOS);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                float2 uv = IN.screenPos.xy / IN.screenPos.w;
                // 水平翻转（反射是左右对称的）
                uv.x = 1.0 - uv.x;
                
                half4 reflection = SAMPLE_TEXTURE2D(_ReflectionTex, sampler_ReflectionTex, uv);
                return reflection * _Tint;
            }
            ENDHLSL
        }
    }
}
```

## 6. URP 中的自定义 ScriptableRenderPass（模板通道）

```csharp
public class StencilOutlineFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
        public Material outlineMaterial;
        public int stencilRef = 1;
        public string outlineLayerName = "Outline";
    }
    
    [SerializeField] private Settings settings = new();
    private StencilOutlinePass outlinePass;
    
    public override void Create()
    {
        outlinePass = new StencilOutlinePass(settings)
        {
            renderPassEvent = settings.renderPassEvent
        };
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        renderer.EnqueuePass(outlinePass);
    }
}

public class StencilOutlinePass : ScriptableRenderPass
{
    private readonly StencilOutlineFeature.Settings settings;
    private readonly ProfilingSampler sampler = new("StencilOutline");
    private readonly List<ShaderTagId> shaderTagIds = new()
    {
        new ShaderTagId("UniversalForward"),
        new ShaderTagId("LightweightForward"),
        new ShaderTagId("SRPDefaultUnlit")
    };
    
    public StencilOutlinePass(StencilOutlineFeature.Settings settings)
    {
        this.settings = settings;
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("StencilOutline");
        
        using (new ProfilingScope(cmd, sampler))
        {
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
            
            // 获取需要描边的物体列表（特定 Layer）
            int outlineLayer = LayerMask.NameToLayer(settings.outlineLayerName);
            if (outlineLayer < 0) return;
            
            var drawSettings = CreateDrawingSettings(shaderTagIds, ref renderingData,
                SortingCriteria.CommonOpaque);
            
            var filterSettings = new FilteringSettings(RenderQueueRange.all, 1 << outlineLayer);
            
            // Step 1: 写入模板
            cmd.SetRenderTarget(renderingData.cameraData.renderer.cameraColorTarget,
                renderingData.cameraData.renderer.cameraDepthTarget);
            
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

## 7. 模板缓冲值分配规范

在复杂项目中，多个系统都会用到模板缓冲，需要统一规划模板值分配：

```csharp
public static class StencilValues
{
    // 每个系统占用不同的模板值范围
    public const int None = 0;
    
    // 选中描边系统 (1~15)
    public const int SelectedUnit = 1;
    public const int SelectedBuilding = 2;
    public const int SelectedItem = 3;
    
    // 特殊渲染区域 (16~31)
    public const int PortalA = 16;
    public const int PortalB = 17;
    public const int Mirror = 18;
    public const int WaterSurface = 19;
    
    // X-Ray 系统 (32~47)
    public const int XRayEnemy = 32;
    public const int XRayAlly = 33;
    
    // UI 遮罩 (64~79)
    public const int UIScissor = 64;
    public const int UIRoundedCorner = 65;
    
    // 后处理区域 (128~255)
    public const int PostProcessRegion1 = 128;
    public const int PostProcessRegion2 = 129;
}
```

## 8. 常见问题与调试

### 问题1：描边不显示

```
原因：
- 第一个 Pass 没有成功写入模板值
- 两个 Pass 的 Queue 顺序不正确
- Stencil Ref 值不匹配

调试方法：
- 在 Frame Debugger 中查看每个 DrawCall 后模板缓冲的状态
- 使用 RenderDoc 捕获帧后查看 Stencil Attachment
```

### 问题2：反射溢出镜子边界

```
原因：
- 没有使用模板缓冲限定渲染区域
- 镜子表面 Pass 和反射内容 Pass 的模板配置冲突

解决：
1. 先用一个 Pass 在镜子区域写入模板值 2
2. 渲染反射场景时 Comp Equal Ref 2，只在镜子区域渲染
```

### 问题3：Portal 穿帮（前方物体出现在画面中）

```
原因：
- 没有设置斜截面投影矩阵

解决：
- 使用 Camera.CalculateObliqueMatrix 设置近裁面
- 确保近裁面恰好在传送门平面处
```

## 9. 最佳实践总结

1. **统一分配模板值**：项目初期规划好各系统的模板值范围，避免冲突
2. **最小化模板写入**：只在真正需要的区域写入模板，避免全屏写入
3. **队列顺序关键**：模板写入 Pass 必须在读取 Pass 之前渲染，严格控制 Queue 值
4. **Portal 性能**：Portal 相机每帧都会完整渲染一次场景，注意 Portal 数量不能过多
5. **反射精度权衡**：平面反射 RT 分辨率影响性能，根据目标设备调整（移动端 512/PC 端 1024）
6. **Frame Debugger 调试**：开发时一定要用 Frame Debugger 逐 Pass 检查渲染结果
7. **URP 集成**：在 URP 中通过 `ScriptableRendererFeature` 注入模板操作，保持与渲染管线的解耦
8. **多系统兼容**：使用位掩码（BitMask）让多个系统在不同 bit 位上写入，互不干扰
