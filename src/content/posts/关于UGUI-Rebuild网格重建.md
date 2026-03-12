---
title: 关于UGUI-Rebuild网格重建
published: 2019-12-26
description: "关于Rebatch和Rebuild，其实它们之间虽然有关联但是本质上是两个过程。先理解网格重建(Rebuild)，要理解这一过程，就需要先明白为什么会有网格，然"
tags: []
category: 图形渲染
draft: false
---

关于Rebatch和Rebuild，其实它们之间虽然有关联但是本质上是两个过程。先理解网格重建(Rebuild)，要理解这一过程，就需要先明白为什么会有网格，然后再讨论为什么会重建。

## UI是怎样被绘制的

如果Unity要渲染一个Mesh，需要经历CPU阶段，把渲染需要的数据传给GPU，这些数据包括但不限于：顶点(来自Mesh文件)、UV(来自Mesh文件)、材质信息(来自材质文件)、贴图(来自贴图文件)、Shader(Unity运行时会编译)等等，这些信息传递给GPU之后，GPU经过自己的流水线，最终渲染出结果。

Unity在处理UI上依然用的是这一套流程，最大的区别在于UI没有自己的模型文件，那UGUI是如何获得顶点、UV等信息呢，答案是自己计算。单个UI元素需要的数据并不复杂，一个简单的Image需要的顶点只有四个就，所以对于一个UI元素来说，它自己维护了自己的Mesh信息。

## 什么是网格重建

上面我们说到每个UI元素会维护自己的Mesh信息，那么这个Mesh是每帧都会生成的吗，其实不是的，因为Mesh信息并不是一直会发生改变，每帧计算会浪费不必要的性能，UGUI的做法是在UI元素发生必须要重建Mesh的改变的时候才会去重建。这部分工作是在C#层去做的，由于UGUI的这部分代码是开源的，我们可以通过源码去大致了解这块逻辑。

下面这段代码摘自Graphic.cs，这就是所谓的网格重建(Rebuild)的本尊。从这个函数里我们可以看到，这里会执行两个函数：`UpdateGeometry`和`UpdateMaterial`，并且执行是有条件的，分别需要`m_VertsDirty`和`m_MaterialDirty`为true。也就是说，网格重建的执行是有条件的。

```c#
/// <summary>
/// Rebuilds the graphic geometry and its material on the PreRender cycle.
/// </summary>
/// <param name="update">The current step of the rendering CanvasUpdate cycle.</param>
/// <remarks>
/// See CanvasUpdateRegistry for more details on the canvas update cycle.
/// </remarks>
public virtual void Rebuild(CanvasUpdate update)
{
    if (canvasRenderer == null || canvasRenderer.cull)
        return;

    switch (update)
    {
        case CanvasUpdate.PreRender:
            if (m_VertsDirty)
            {
                UpdateGeometry();
                m_VertsDirty = false;
            }
            if (m_MaterialDirty)
            {
                UpdateMaterial();
                m_MaterialDirty = false;
            }
            break;
    }
}
```

继续搜索这两个变量，能找到它们分别在`SetVerticesDirty`和`SetMaterialDirty`方法中被写为true。也就是说，只有当UI元素被标记为Dirty之后，才会发生Rebuild。继续搜索这两个方法的引用，会发现搜索结果就比较多了，比如下面这个例子：

```c#
protected override void OnRectTransformDimensionsChange()
{
    if (gameObject.activeInHierarchy)
    {
        // prevent double dirtying...
        if (CanvasUpdateRegistry.IsRebuildingLayout())
            SetVerticesDirty();
        else
        {
            SetVerticesDirty();
            SetLayoutDirty();
        }
    }
}
```

这个当RectTransform发生变化时的回调，具体调用的地方不在C#层，所以看不到，不过可以在这里断点调试。从这里还可以看到一个方法`SetLayoutDirty`这是一些Layout组件相关的Rebuild，暂时不具体展开了。

总结一下简化版流程，当UI元素的RectTransform发生改变时，通过`SetVerticesDirty`方法将变量`m_VertsDirty`改为true，Rebuild的时候`UpdateGeometry`方法重新生成Mesh。至于何时会发生Rebuild，可以搜索`SetXXXDirty`方法。

## 如何减少网格重建

减少对元素的操作。