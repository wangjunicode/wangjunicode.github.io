---
title: 关于图形学-顶点和UV
published: 2023-09-16
description: "图形学基础：深入讲解顶点属性（position/normal/tangent/uv/color）、UV 坐标系统与纹理采样原理、UV 展开技巧，以及在 Unity 中操作 Mesh 顶点数据的实践方法。"
tags: [渲染, Unity, C#, 游戏开发]
category: 游戏开发
draft: false
---

## 概述

顶点（Vertex）和 UV 是图形学的基础概念，理解它们是掌握 Shader 编写、Mesh 操作和渲染优化的前提。本文从概念出发，结合 Unity 实践，系统梳理顶点属性和 UV 坐标系统。

---

## 一、顶点属性详解

一个顶点不只有位置信息，它携带多种属性，共同决定该点的渲染表现：

| 属性 | 类型 | 说明 |
|------|------|------|
| Position | Vector3 | 顶点在模型空间中的位置 |
| Normal | Vector3 | 法线方向，用于光照计算 |
| Tangent | Vector4 | 切线方向，用于法线贴图（TBN 矩阵） |
| UV（texcoord0） | Vector2 | 第一组纹理坐标（主贴图） |
| UV2（texcoord1） | Vector2 | 第二组纹理坐标（光照贴图 Lightmap） |
| Color | Color | 顶点颜色，可传递自定义数据给 Shader |

### Position（顶点位置）

顶点位置定义了网格的几何形状。坐标空间变换流程：

```
模型空间（Object Space）
    ↓ × Model Matrix（物体的 TRS 变换）
世界空间（World Space）
    ↓ × View Matrix（摄像机变换）
观察空间（View Space / Camera Space）
    ↓ × Projection Matrix（透视/正交投影）
裁剪空间（Clip Space）
    ↓ 齐次除法（÷w）
NDC 空间（标准化设备坐标，[-1,1]³）
    ↓ Viewport Transform
屏幕空间（Screen Space，像素坐标）
```

Shader 中的变换：
```hlsl
// Vertex Shader
v2f vert(appdata v)
{
    v2f o;
    // UnityObjectToClipPos 等价于 mul(UNITY_MATRIX_MVP, v.vertex)
    o.pos = UnityObjectToClipPos(v.vertex);
    return o;
}
```

### Normal（法线）

法线是垂直于顶点所在面的单位向量，用于光照计算（漫反射、高光）。

**注意**：法线不能用 Model Matrix 直接变换（非均匀缩放会导致法线不再垂直于面），需使用**法线矩阵**（Model Matrix 逆转置）：

```hlsl
// 正确的法线变换
float3 worldNormal = UnityObjectToWorldNormal(v.normal);
// 等价于：
// float3x3 normalMatrix = transpose(inverse((float3x3)unity_ObjectToWorld));
// float3 worldNormal = normalize(mul(normalMatrix, v.normal));
```

### Tangent（切线）与 TBN 矩阵

切线用于法线贴图（Normal Map）：法线贴图存储的是切线空间下的法线偏移，需要 TBN 矩阵将其转换到世界空间。

TBN = Tangent（切线）、Bitangent（副切线，也叫 Binormal）、Normal（法线）组成的正交基：

```hlsl
// 构建 TBN 矩阵
float3 worldNormal  = UnityObjectToWorldNormal(v.normal);
float3 worldTangent = UnityObjectToWorldDir(v.tangent.xyz);
// v.tangent.w 存储副切线方向（+1 或 -1，处理 UV 镜像）
float3 worldBinormal = cross(worldNormal, worldTangent) * v.tangent.w;

float3x3 TBN = float3x3(worldTangent, worldBinormal, worldNormal);

// 从法线贴图采样后变换到世界空间
float3 tangentNormal = UnpackNormal(tex2D(_NormalMap, i.uv));
float3 worldNormalFinal = normalize(mul(tangentNormal, TBN));
```

### Vertex Color（顶点颜色）

顶点颜色可以用来在 Shader 中传递自定义参数，常见用途：
- 控制特效的透明度（粒子系统自动写入 Alpha）
- 地形混合权重（R/G/B/A 分别对应四种地形纹理的混合比例）
- 顶点动画遮罩（某些顶点不参与动画）

```hlsl
// 利用顶点颜色控制混合
fixed4 frag(v2f i) : SV_Target
{
    fixed4 tex1 = tex2D(_Tex1, i.uv) * i.color.r;
    fixed4 tex2 = tex2D(_Tex2, i.uv) * i.color.g;
    fixed4 tex3 = tex2D(_Tex3, i.uv) * i.color.b;
    return tex1 + tex2 + tex3;
}
```

---

## 二、UV 坐标系统与纹理采样原理

### UV 坐标定义

UV 坐标是二维纹理坐标，用于将 3D 网格的顶点"映射"到 2D 纹理图像上：

- **U** 对应纹理的水平方向（X 轴）
- **V** 对应纹理的垂直方向（Y 轴）
- 取值范围通常是 `[0, 1]`，超出范围后按 Wrap Mode 处理

UV 坐标系的原点位置因平台/工具不同：
- **Unity（OpenGL 规范）**：原点在左下角，V 向上
- **DirectX / Maya**：原点在左上角，V 向下（导出时可能需要翻转 V）

### 纹理采样原理

片元着色器（Fragment Shader）通过 UV 坐标对纹理采样，GPU 根据 UV 值找到对应纹素（texel）并插值：

```hlsl
// 基础纹理采样
fixed4 frag(v2f i) : SV_Target
{
    // tex2D：二维纹理采样，i.uv 是插值后的 UV 坐标
    fixed4 col = tex2D(_MainTex, i.uv);
    return col;
}
```

**UV 超出 [0,1] 时的 Wrap Mode**：

| 模式 | 效果 |
|------|------|
| Repeat | 纹理平铺重复 |
| Clamp | 超出部分取边缘像素颜色 |
| Mirror | 镜像平铺 |
| Mirror Once | 只镜像一次，之后 Clamp |

**过滤模式（Filter Mode）**影响放大/缩小时的采样质量：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| Point | 最近邻插值，无模糊 | 像素风游戏 |
| Bilinear | 双线性插值，平滑过渡 | 通用 |
| Trilinear | 三线性插值（含 Mipmap 层间插值） | 3D 场景贴图 |

---

## 三、UV 展开与贴图技巧

### UV 展开（Unwrapping）

UV 展开是将 3D 网格"剪开展平"成 2D 的过程，类似把礼盒展开成纸板：

- **缝合线（Seam）**：展开时的切割边，尽量放在不显眼处（角色背面、关节处）
- **UV 利用率**：UV 岛（UV Island）应尽量铺满 [0,1] 空间，减少空白浪费
- **UV 扭曲（Distortion）**：UV 展开后网格变形会导致贴图拉伸，应尽量保持等比

### 常见 UV 布局技巧

1. **多个 UV 通道**：
   - UV0（texcoord0）：漫反射/法线贴图，可以 UV Tile（重复）
   - UV1（texcoord1）：Lightmap 烘焙，必须保证 [0,1] 内无重叠

2. **UV 动画（滚动贴图）**：
```hlsl
// Shader 中实现 UV 流动（水面、传送带等）
v2f vert(appdata v)
{
    v2f o;
    o.pos = UnityObjectToClipPos(v.vertex);
    // _Time.y 是从游戏开始的秒数，_Speed 控制速度
    o.uv = v.uv + float2(_SpeedX, _SpeedY) * _Time.y;
    return o;
}
```

3. **UV 裁剪（图集采样）**：
```hlsl
// 从图集（Sprite Atlas）中采样某个子图
// _AtlasRect: (x_offset, y_offset, width, height)
float2 atlasUV = i.uv * _AtlasRect.zw + _AtlasRect.xy;
fixed4 col = tex2D(_Atlas, atlasUV);
```

---

## 四、Mesh 顶点数据在 Unity 中的使用

### 读取和修改 Mesh 顶点数据

```csharp
// 获取 Mesh
Mesh mesh = GetComponent<MeshFilter>().mesh;

// 读取顶点数据
Vector3[] vertices  = mesh.vertices;   // 顶点位置
Vector3[] normals   = mesh.normals;    // 法线
Vector4[] tangents  = mesh.tangents;   // 切线（w 分量存方向）
Vector2[] uv        = mesh.uv;         // 第一组 UV
Vector2[] uv2       = mesh.uv2;        // 第二组 UV（Lightmap）
Color[]   colors    = mesh.colors;     // 顶点颜色
int[]     triangles = mesh.triangles;  // 三角形索引

// 修改顶点位置（例如：顶点动画波浪效果）
void UpdateVertices()
{
    var verts = mesh.vertices;
    for (int i = 0; i < verts.Length; i++)
    {
        float wave = Mathf.Sin(Time.time * 2f + verts[i].x * 0.5f) * 0.2f;
        verts[i].y = wave;
    }
    mesh.vertices = verts;
    mesh.RecalculateNormals(); // 修改顶点后重新计算法线
}
```

### 程序化生成 Mesh

```csharp
// 创建一个平面 Quad
Mesh CreateQuad(float width, float height)
{
    var mesh = new Mesh();
    
    // 4 个顶点
    mesh.vertices = new Vector3[]
    {
        new Vector3(-width/2, -height/2, 0),  // 左下
        new Vector3( width/2, -height/2, 0),  // 右下
        new Vector3(-width/2,  height/2, 0),  // 左上
        new Vector3( width/2,  height/2, 0),  // 右上
    };
    
    // UV（与顶点一一对应）
    mesh.uv = new Vector2[]
    {
        new Vector2(0, 0),  // 左下
        new Vector2(1, 0),  // 右下
        new Vector2(0, 1),  // 左上
        new Vector2(1, 1),  // 右上
    };
    
    // 三角形（两个三角形组成一个矩形，注意顶点顺序影响法线朝向）
    mesh.triangles = new int[] { 0, 2, 1,  1, 2, 3 };
    
    mesh.RecalculateNormals();
    mesh.RecalculateBounds();
    
    return mesh;
}
```

### 使用 Mesh API 的注意事项

- **修改顶点后必须重新赋值**：`mesh.vertices = verts`（直接修改数组元素无效）
- **频繁修改用 MeshDataArray**（Unity 2020.1+）：避免频繁 GC
- **SkinnedMeshRenderer 的 Mesh**：骨骼蒙皮后的 Mesh 在 CPU 侧是原始网格，实际渲染是 GPU 计算蒙皮后的结果

---

## 总结

| 概念 | 核心要点 |
|------|---------|
| 顶点位置 | 模型空间 → 世界 → 观察 → 裁剪 → NDC → 屏幕 |
| 法线 | 用法线矩阵变换（逆转置），不能用 Model Matrix |
| 切线 | 构建 TBN 矩阵，用于法线贴图空间变换 |
| UV 坐标 | [0,1] 范围映射纹理，注意平台坐标原点差异 |
| UV 展开 | 缝合线放不显眼处，UV 利用率尽量高 |
| Mesh API | vertices/uv/normals/tangents，修改后要重新赋值 |

理解顶点和 UV 是深入学习 Shader、自定义渲染效果和 Mesh 生成的基础，在实际项目中（地形混合、UI 特效、顶点动画）都有直接应用。
