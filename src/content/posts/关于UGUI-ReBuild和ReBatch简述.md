---
title: 关于UGUI-ReBuild和ReBatch简述
published: 2019-12-11
description: "ReBuild和ReBatch简述"
tags: [Unity, UGUI, 性能优化]
category: 图形渲染
draft: false
---

ReBuild和ReBatch简述

## 是什么

ReBatch是什么？

先理解Batch是什么?

Batch: 是指Canvas把表示它UI元素的网格合并起来，并生成合适的渲染指令发送到图形管线中，这个过程的结果会被缓存起来复用，直到这个Canvas被标记为Dirty，当Canvas中任何一个网格发生变化时，就会被标记为Dirty。

Batch Build过程（Canvases）
Batch Build（Rebatch）：Canvas把表示它UI元素的网格合并起来，并生成合适的渲染命令发送到Unity的图形管线中。这个过程的结果会被缓存起来复用，直到这个Canvas被标记为Dirty，当Canvas中任何一个网格发生变化时，就会被标记成Dirty状态。
Canvas的网格是从从那些Canvas下的CanvasRenderer组件中获取的，但不包括子Canvas。
批处理计算需要对网格进行深度排序，并检查网格是否重叠，材质是否共享等。这种操作是多线程的，因此它的性能在不同的CPU架构中通常会有很大的不同，尤其是在移动soc（通常很少有CPU核心）和现代桌面CPU（通常有4个或更多核心）之间。

Rebuild过程（Graphics）
Rebuild：指重新计算Graphic的布局和网格的过程，这个过程在CanvasUpdateRegistry中执行（这是一个C#类，我们可以在Unity的Bitbucket上找到源码）。
在CanvasUpdateRegistry中，最重要的方法是PerformUpdate。每当Canvas组件调用WillRenderCanvases事件时，就会调用此方法。此事件每帧调用一次。



## 批注

渲染一个UI的流程，CPU将顶点，UV等信息传给GPU渲染管线，对于UI的网格信息，由自己维护构建。

Build就是网格构建，ReBuild就是重新构建UI元素的网格，当UI元素发生变化的时候（比如顶点，材质引起的变化）就会发生ReBuild

针对UGUI，将UI元素通过Canvas这个容器来管理，在输送UI元素网格信息之前，会对当前Canvas下的网格进行合并整理，并将结果缓存起来，知道这个Canvas被标记为Dirty。



**触发Rebatch的条件**
当Canvas下有Mesh发生改变时，如：

SetActive
Transform属性变化
Graphic的Color属性变化（改Mesh顶点色）
Text文本内容变化
Depth发生变化

**触发Rebuild的条件**
Layout修改RectTransform部分影响布局的属性
Graphic的Mesh或Material发生变化
Mask裁剪内容变化



**Rebuild通常引起Rebatch**