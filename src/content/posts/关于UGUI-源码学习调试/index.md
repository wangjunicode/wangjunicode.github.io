---
title: 关于UGUI-源码学习调试
published: 2022-09-16
description: "UGUI 源码学习指南：如何搭建源码调试环境、Canvas 渲染流程（Rebuild/Rebatch）详解、CanvasRenderer 与 Graphic 的关系、源码关键类职责梳理，帮助深入理解 Unity UI 渲染机制。"
tags: [UI, Unity, C#, 渲染]
category: 图形渲染
draft: false
---

## 概述

UGUI 是 Unity 的内置 UI 系统，理解其内部实现对优化 UI 性能、排查渲染问题有极大帮助。本文记录如何搭建 UGUI 源码调试环境，并深入分析其核心渲染流程。

---

## 一、搭建 UGUI 源码调试环境

### 下载源码

UGUI 源码由 Unity 官方开源，地址：https://github.com/Unity-Technologies/uGUI

选择与当前 Unity 版本匹配的 Tag/Branch 下载。

### 导入到工程

1. **删除内置 UGUI 扩展**：  
   打开 Unity Package Manager，找到 `Unity UI` 包，移除（Uninstall）或标记为 Override。

2. **新建测试工程**（推荐用独立工程避免污染项目）：
   - 新建 URP 或 Built-in Render Pipeline 工程
   - 将下载的 UGUI 源码目录放入 `Assets/` 下
   - Unity 会自动编译，若有命名空间冲突按提示解决

3. **配置 IDE（Rider / VS）支持调试**：
   - 确保 IDE 已关联 Unity 工程
   - 在 UGUI 源码的关键方法打断点（如 `Canvas.SendWillRenderCanvases`）
   - 运行时附加调试器即可命中断点

---

## 二、Canvas 渲染流程

Canvas 是 UGUI 的根节点，所有 UI 元素都依附于 Canvas，其渲染流程分为两个关键阶段：**Rebuild（重建）** 和 **Rebatch（重新合批）**。

### 渲染流程总览

```
每帧 Canvas.SendWillRenderCanvases()
    ↓
CanvasUpdateRegistry.PerformUpdate()
    ├── Layout Rebuild（布局重建）
    │   ├── 计算 LayoutGroup 子元素的大小和位置
    │   └── 更新 RectTransform
    └── Graphic Rebuild（图形重建）
        ├── 重新生成顶点数据（Mesh）
        └── 更新材质引用
    ↓
Canvas 内部 Rebatch
    ├── 合并相同材质/图集的 Drawcall
    └── 生成最终渲染 Mesh
    ↓
提交给 Render Thread 渲染
```

### Rebuild（重建）

Rebuild 是 CPU 上的操作，发生在 `Graphic` 组件脏标记（dirty）被设置之后。触发 Rebuild 的原因：

- 修改 UI 组件属性（文字内容、颜色、Image Sprite、RectTransform 大小）
- 调用 `SetDirty()`
- 动态启用/禁用 UI 元素

**源码关键路径**：`Graphic.SetVerticesDirty()` → 注册到 `CanvasUpdateRegistry` → 下一帧 `PerformUpdate()` 中执行 `Rebuild()`

```csharp
// Graphic.cs（简化）
public virtual void SetVerticesDirty()
{
    if (!IsActive()) return;
    m_VertsDirty = true;
    // 注册到更新队列
    CanvasUpdateRegistry.RegisterCanvasElementForGraphicRebuild(this);
}

public virtual void Rebuild(CanvasUpdate update)
{
    if (update == CanvasUpdate.PreRender)
    {
        if (m_VertsDirty)
        {
            UpdateGeometry();   // 重新生成顶点
            m_VertsDirty = false;
        }
        if (m_MaterialDirty)
        {
            UpdateMaterial();   // 更新材质
            m_MaterialDirty = false;
        }
    }
}
```

### Rebatch（重新合批）

Rebatch 是将 Canvas 下所有 UI 元素的 Mesh 合并为尽可能少的 DrawCall 的过程（类似 Static Batching）。

**合批条件**：
- 相同材质（同一个图集的 Sprite 共享材质）
- 相同 Canvas（跨 Canvas 不合批）
- 相同渲染层级（Sorting Layer/Order in Layer）
- 无穿插的 Depth 顺序（有重叠且材质不同时会打断合批）

**Rebatch 触发时机**：
- Canvas 下任意 UI 元素的变换（移动、缩放、旋转）
- UI 元素 Enable/Disable
- Z 轴深度变化

**优化建议**：将静态 UI 和动态 UI 分离到不同 Canvas，避免动态元素的变化触发整个 Canvas 的 Rebatch。

---

## 三、CanvasRenderer 与 Graphic 的关系

### CanvasRenderer

`CanvasRenderer` 是 UGUI 的渲染底层，负责持有最终要提交给 Canvas 的顶点数据和材质引用。每个可渲染的 UI 元素都有一个 `CanvasRenderer` 组件。

主要职责：
- 持有渲染用的 Mesh 数据（顶点、UV、颜色）
- 持有材质引用
- 提供 `SetMesh()`、`SetMaterial()` 等接口供上层调用
- 将数据提交给底层 Canvas 合批系统

### Graphic

`Graphic` 是所有可视 UI 组件的基类（`Image`、`Text`、`RawImage` 均继承自它），负责：
- 生成顶点数据（`OnPopulateMesh()`）
- 管理脏标记（`SetVerticesDirty()`、`SetMaterialDirty()`）
- 将生成的 Mesh 数据推送给 `CanvasRenderer`

两者关系：

```
Graphic（逻辑层，生成数据）
    │ 调用 SetMesh / SetMaterial
    ▼
CanvasRenderer（渲染层，持有数据）
    │ 提交给
    ▼
Canvas（合批 & 渲染）
```

### Image 的顶点生成（源码分析）

```csharp
// Image.cs 继承 Graphic，重写顶点生成方法
protected override void OnPopulateMesh(VertexHelper vh)
{
    // 根据 ImageType（Simple/Sliced/Tiled/Filled）生成不同顶点数据
    switch (type)
    {
        case Type.Simple:
            GenerateSimpleSprite(vh, m_PreserveAspect);
            break;
        case Type.Sliced:
            GenerateSlicedSprite(vh);
            break;
        case Type.Tiled:
            GenerateTiledSprite(vh);
            break;
        case Type.Filled:
            GenerateFilledSprite(vh, m_PreserveAspect);
            break;
    }
}
```

---

## 四、源码关键类职责

| 类 | 所在文件 | 核心职责 |
|----|---------|---------|
| `Canvas` | Unity 内置（非开源） | 根节点，触发渲染流程，管理合批 |
| `CanvasUpdateRegistry` | CanvasUpdateRegistry.cs | 管理 Rebuild 队列，每帧执行 PerformUpdate |
| `Graphic` | Core/Graphic.cs | 所有可视 UI 的基类，生成顶点数据 |
| `CanvasRenderer` | Unity 内置 | 持有顶点/材质，提交给 Canvas |
| `MaskableGraphic` | Core/MaskableGraphic.cs | 支持 Mask 裁剪的 Graphic 子类 |
| `Image` | UI/Image.cs | 图片显示，继承 MaskableGraphic |
| `Text` | UI/Text.cs | 文本显示（旧版，推荐用 TextMeshPro） |
| `LayoutGroup` | Layout/LayoutGroup.cs | 布局基类（HorizontalLayoutGroup 等） |
| `GraphicRaycaster` | EventSystem/GraphicRaycaster.cs | UI 射线检测，处理点击事件 |
| `EventSystem` | EventSystem/EventSystem.cs | 事件系统入口，派发输入事件 |

---

## 五、常见性能问题与调试技巧

### 使用 Frame Debugger 分析 DrawCall

Window → Analysis → Frame Debugger：可以看到每个 DrawCall 渲染了哪些 UI 元素，帮助定位合批问题。

### 使用 Profiler 定位 Rebuild 开销

Profiler → CPU Usage → 搜索 `Canvas.SendWillRenderCanvases`，展开可以看到哪些 Graphic 触发了 Rebuild 以及耗时。

### 常见性能陷阱

1. **频繁修改 Text 文字**（如伤害数字）：每次修改都触发 Rebuild，改用对象池 + 预生成
2. **ScrollView 内容过多**：使用虚拟列表（只渲染可见区域的 Item）
3. **动态 UI 与静态 UI 同一 Canvas**：动态元素移动触发整个 Canvas Rebatch

```csharp
// 禁用/启用 Image 颜色修改（不触发 Rebuild）
// 修改 CanvasRenderer 的颜色不会触发完整 Rebuild
image.canvasRenderer.SetColor(Color.red);   // ✅ 轻量
image.color = Color.red;                    // ⚠️ 触发 SetVerticesDirty
```

---

## 总结

| 阶段 | 触发条件 | 开销 |
|------|---------|------|
| Graphic Rebuild | UI 属性修改、SetDirty | CPU，遍历 dirty 元素重新生成顶点 |
| Canvas Rebatch | UI 元素变换、层级变化 | CPU，重新合并 DrawCall |
| GPU 渲染 | 每帧 | GPU，执行最终合批后的 DrawCall |

理解 UGUI 渲染流程的核心是：**Graphic 负责生成数据，CanvasRenderer 持有数据，Canvas 负责合批渲染**。优化 UI 性能的核心是**减少 Rebuild 和 Rebatch 的触发频率**，通过合理拆分 Canvas、使用静态图集、避免频繁修改 UI 属性来实现。
