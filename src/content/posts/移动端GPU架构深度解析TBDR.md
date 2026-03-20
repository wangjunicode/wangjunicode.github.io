---
title: 移动端 GPU 架构深度解析：TBDR 与带宽优化
published: 2026-03-21
description: "深入讲解移动端 GPU 的 Tile-Based Deferred Rendering（TBDR）架构原理，与桌面 IMR 的核心差异，以及如何利用 TBDR 特性进行渲染优化，包括 On-chip Memory 利用、Load/Store Action 优化、Overdraw 控制和带宽节省策略。"
tags: [移动端GPU, TBDR, 渲染优化, Unity, 图形渲染]
category: 图形渲染
draft: false
---

## 为什么移动端 GPU 与桌面 GPU 不同

```
手机的物理限制：
  散热面积：约 10cm²（桌面 GPU：数百 cm²）
  电池容量：5000mAh（桌面 GPU：功耗 300W）
  内存带宽：CPU/GPU 共享系统内存（桌面 GPU：专用 GDDR6，带宽超高）

设计目标：
  功耗优先（延长电池寿命）
  散热优先（避免降频保护）
  带宽优先（减少内存访问）

移动端 GPU 的核心创新：
  TBDR（Tile-Based Deferred Rendering）
  = 将帧缓冲分成小块（Tile），每块只在 On-chip Memory 中处理
  = 大幅减少对系统内存的读写（节省带宽 → 节省功耗）
```

---

## 一、TBDR vs IMR 架构对比

### 1.1 IMR（Immediate Mode Rendering）- 桌面 GPU

```
桌面 GPU 的渲染流程：
  
  对象1 → 顶点着色器 → 光栅化 → 深度测试 → 片元着色器 → 写入 Framebuffer
  对象2 → 顶点着色器 → 光栅化 → 深度测试 → 片元着色器 → 写入 Framebuffer
  ...（每个对象立即处理）

特点：
  - 对象按提交顺序立即渲染
  - Framebuffer 在系统内存（GDDR）中
  - 每次读写 Framebuffer 都要访问内存
  - 依赖大量高速缓存（L3 Cache）和高带宽内存

问题：
  - 带宽消耗高（适合有专用显存的桌面 GPU）
  - Overdraw（重复渲染同一像素）代价高
```

### 1.2 TBDR - 移动端 GPU

```
移动端 GPU 的渲染流程：

阶段一：Binning（分箱）
  遍历所有三角形，记录每个三角形影响哪些 Tile
  生成每个 Tile 的绘制列表
  
阶段二：Rendering（渲染）
  逐 Tile 处理（通常 Tile 大小：16×16 或 32×32 像素）
  
  对于每个 Tile：
    1. 从系统内存加载 Tile 的颜色/深度数据到 On-chip Memory（仅此一次！）
    2. 对该 Tile 中的所有三角形执行完整着色
    3. 将 On-chip Memory 中的结果写回系统内存（仅此一次！）

On-chip Memory（片上内存）：
  在 GPU 芯片内部
  速度极快（比 LPDDR 快 100~1000 倍）
  容量小（仅能容纳几个 Tile 的数据）
  
核心优势：
  每个 Tile 只需要一次内存读、一次内存写
  比 IMR 减少 90%+ 的内存带宽
```

---

## 二、基于 TBDR 的优化策略

### 2.1 正确使用 Load/Store Action

```csharp
// TBDR 的关键优化：避免不必要的 Load/Store

// ❌ 错误：使用 Load Action（从内存加载旧数据）
// 如果你的渲染会覆盖整个屏幕，不需要加载旧数据
var renderPassDesc = new RenderPassDescriptor
{
    colorAttachments = new[]
    {
        new RenderPassColorAttachment
        {
            loadAction = MTLLoadAction.Load,  // ❌ 不必要的内存加载！
            storeAction = MTLStoreAction.Store
        }
    }
};

// ✅ 正确：使用 Clear（直接清除，不从内存加载）
var renderPassDesc = new RenderPassDescriptor
{
    colorAttachments = new[]
    {
        new RenderPassColorAttachment
        {
            loadAction = MTLLoadAction.Clear,  // ✅ 直接清除，节省带宽
            storeAction = MTLStoreAction.Store
        }
    }
};

// 在 Unity URP 中的对应设置：
// Camera → Clear Flags：
//   Skybox：Clear（好）
//   Solid Color：Clear（好）
//   Don't Clear：Load（差！只有特殊场景才用）
```

### 2.2 避免 Render Texture 的读写来回切换

```
TBDR 的杀手：频繁在多个 Render Target 之间切换

❌ 不好的做法（会导致多次 Flush/Load）：
  RenderTarget A → 渲染场景
  RenderTarget B → 后处理1 (从A读，写到B)
  RenderTarget A → 后处理2 (从B读，写到A)
  RenderTarget B → 后处理3 (从A读，写到B)
  最终屏幕   → (从B读，写到屏幕)
  
  每次切换都要：把当前 Tile 写回内存，从内存加载新 Tile
  
✅ 优化后的做法（利用 TBDR 的 Merge Pass）：
  RenderTarget A → 渲染场景 + 后处理1 + 后处理2 合并在一个 Pass 中
  最终屏幕   → 从A直接输出
  
  利用 On-chip Memory：中间结果不写回内存，在片上直接传递

在 Unity URP 中：
  设置 → Post-processing 使用 "Render Feature" 合并 Pass
  Blit 操作尽量减少
  使用 Scriptable Renderer 合并多个后处理
```

### 2.3 Early-Z 和 Overdraw 控制

```
TBDR 的另一个特性：Tile 内部的 HSR（Hidden Surface Removal）

Mali GPU（Bifrost/Valhall 架构）的 FPK（Forward Pixel Kill）：
  在片元着色器执行之前，GPU 可以判断某个像素被后续像素覆盖
  直接跳过被遮挡像素的着色器执行

条件：
  - 从前到后绘制（From Front to Back）
  - 不使用 Alpha Test（discard 指令）
  - 不修改深度值

优化策略：
  1. 不透明物体：按照从前到后的顺序绘制（Unity 自动做这个）
  2. 避免不必要的 Alpha Test（用 Alpha Blend 的半透明物体是杀手）
  3. 对于半透明物体，尽量减少层数
  4. 大地形/大建筑：先绘制，作为后续绘制的遮挡
```

---

## 三、带宽优化策略

### 3.1 纹理压缩格式的选择

```
移动端推荐的纹理压缩格式：

Android（Adreno GPU，高通芯片）：
  推荐：ETC2（免费）或 ASTC（需要 Android 4.3+）
  
Android（Mali GPU，联发科/三星芯片）：
  推荐：ETC2 或 ASTC
  
iOS（PowerVR / Apple GPU）：
  推荐：ASTC（Apple A8+ 支持）或 PVRTC（老设备）

ASTC 的优势：
  - 可调压缩率（4x4 到 12x12 block，质量/大小自由平衡）
  - 支持 HDR 格式
  - 比 ETC2 质量更好

在 Unity 中设置：
  Texture Import Settings → Format：
  Android：ETC2 RGBA8 / ASTC 6x6
  iOS：ASTC 6x6
  
  压缩率参考：
  ASTC 4x4：8bpp（高质量，接近原图）
  ASTC 8x8：2bpp（适合大面积、不仔细看的纹理）
  ASTC 12x12：0.89bpp（极限压缩）
```

### 3.2 带宽计算

```
帧带宽计算公式：
  带宽 = 分辨率 × 帧率 × 每像素字节数 × 读写次数

例（1080p 60fps）：
  每帧颜色缓冲：1920 × 1080 × 4字节(RGBA) = 8.1MB
  每帧深度缓冲：1920 × 1080 × 4字节(Depth32) = 8.1MB
  
  每帧：读一次颜色 + 写一次颜色 + 深度读写 ≈ 32MB
  60fps：32MB × 60 = 1920MB/s ≈ 2GB/s
  
移动端 LPDDR5 带宽：约 50~100 GB/s
仅帧缓冲就消耗约 2~4%，看起来不多
但加上纹理采样，实际可能用到 20~60%！

优化方向：
  1. 降低分辨率（RenderScale < 1.0）
  2. 减少后处理 Pass 数量（减少 RT 读写）
  3. 使用压缩纹理格式（减少纹理采样带宽）
  4. 关闭不需要的附件（如不需要深度写回）
```

---

## 四、性能分析工具

### 4.1 厂商专属工具

```
Snapdragon Profiler（高通 Adreno GPU）：
  适用：搭载高通芯片的 Android 设备
  功能：实时 GPU 性能计数器、帧分析、着色器分析
  下载：qualcomm.com
  
Mali Graphics Debugger（ARM Mali GPU）：
  适用：搭载 ARM Mali 的 Android 设备
  功能：类似 Snapdragon Profiler
  
Instruments（Apple GPU）：
  适用：iOS 设备
  功能：GPU 性能分析，在 Xcode 中使用
  
GPU 性能计数器关注点：
  GPU Cycles：每帧总 GPU 时钟周期
  Bandwidth：内存带宽利用率
  Vertex/Fragment Utilization：顶点/片元着色器忙碌率
  Cache Hit Rate：缓存命中率（低 = 带宽浪费）
  Overdraw：重复绘制比率
```

### 4.2 Unity GPU 分析技巧

```
方法1：RenderDoc（在设备上截帧）
  通过 USB 连接设备
  在 RenderDoc 中触发截帧
  分析每个 DrawCall 的 Shader 和状态

方法2：Unity Frame Debugger（简单快速）
  Window → Analysis → Frame Debugger
  查看每个 DrawCall 的纹理、Shader、合批情况

方法3：GPU Profiler（实时监控）
  在 Profiler 中切换到 GPU 模块
  查看每帧的 GPU 时间分布
  找出最耗时的渲染阶段
```

---

## 总结

移动端 GPU 优化的关键认知：

```
TBDR 的机会：
  ✅ 使用 Clear 而非 Load（节省内存加载）
  ✅ 合并多个 Pass（利用 On-chip Memory 传递中间结果）
  ✅ 减少 RT 切换（每次切换都要 Flush/Load）
  ✅ 从前到后绘制不透明物体（HSR 优化）

带宽节省：
  ✅ 使用 ASTC 等高效纹理压缩
  ✅ 适当降低 RenderScale（尤其是后处理量大时）
  ✅ 关闭不需要的深度写回（DontCare StoreAction）

分析工具：
  Snapdragon Profiler / ARM Mobile Studio / Xcode Instruments
  → 找到实际的带宽和 GPU 周期瓶颈
  → 针对性优化，而不是盲目猜测
```

---

*本文是「游戏客户端开发进阶路线」系列的图形渲染篇。*
