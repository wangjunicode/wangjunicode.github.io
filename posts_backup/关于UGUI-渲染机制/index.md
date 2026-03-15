---
title: 关于UGUI-渲染机制
published: 2020-04-11
description: "浅谈一下UGUI的底层渲染结构以及Canvas渲染模式的概念"
tags: []
category: 图形渲染
draft: false
---

浅谈一下UGUI的底层渲染结构以及Canvas渲染模式的概念

# 底层结构

先看到UI渲染的底层结构，UI渲染主要由三个部分组成：CanvasUpdateRegistry, Graphic, CanvasRender

- CanvasUpdateRegistry负责通知需要渲染的UI组件
- Graphic负责组织mesh和material然后传给底层（CanvasRenderer类）
- CanvasRendere**r**负责连接canvas和render component，把mesh绘制到Canvas上，CR并不是直接渲染，而是交给Canvas，Canvas再要做合批等操作

**UI渲染结构图：**

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220412164109156-1883437172.jpg)](https://img2022.cnblogs.com/blog/2148166/202204/2148166-20220412164109156-1883437172.jpg)

关于里面的一些细节：

graphic什么时候会设成dirty？当一个canvas需要需要rebatch的时候。

那么什么时候需要rebatch呢？当一个canvas中包含的mesh发生改变时就触发，例如setActive、transform的改变、 颜色改变、文本内容改变等等。

什么时候会发生rebuild呢？当布局和网格被重新计算的时候就是rebuild，可以理解为rebatch的后续。

那么CanvasUpdateRegistry是怎么通知rebuild的呢？每一帧都会触发WillRenderCanvases注册事件，然后由CanvasUpdateRegistry响应并执行PerformUpdate（dirty layout rebuild, dirty graphic rebuild）

------

# 渲染层级

说完底层，我们再来看看UI渲染层级是怎么由哪些决定的。我们说的渲染层级高，意思就是会盖在物体上面，也是最后一个被渲染的那个。

渲染层级是由以下三个层级决定的，从高到低：

- **相机的layer和depth**：culling layer可以决定相机能看到什么layer，depth越高的相机，其视野内能看到的所有物体渲染层级越高

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220330080853033-636308638.png)](https://img2022.cnblogs.com/blog/2148166/202203/2148166-20220330080853033-636308638.png)

- **canvas的layer和order**
  - Screen Space - Overlay: UI元素置于屏幕上方，画布自动适应屏幕尺寸改变。sort order越大显示越前面

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220330081158164-1431179083.png)](https://img2022.cnblogs.com/blog/2148166/202203/2148166-20220330081158164-1431179083.png)

- - Screen Spacce - Camera: 画布自动适应屏幕尺寸改变，需要设置render camera。如果Scene中的GameObject比UI平面更靠近camera，就会遮挡到UI平面。
    - order layer越大显示越前面；sorting layer越在下方的层显示越前面。

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220412170108727-1412697371.png)](https://img2022.cnblogs.com/blog/2148166/202204/2148166-20220412170108727-1412697371.png)

- - World Space: 当UI为场景的一部分，即UI为场景的一部分，需要以3D形式展示。变量和camera screen space一样

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220412170211232-3001953.png)](https://img2022.cnblogs.com/blog/2148166/202204/2148166-20220412170211232-3001953.png)

- 物体的hierarchy关系

  ：物体越在下面，显示越在前面

  - 比如，image1会被image2给遮挡住

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220412170452060-1122576048.png)](https://img2022.cnblogs.com/blog/2148166/202204/2148166-20220412170452060-1122576048.png) 

------

# 渲染器的对比

UGUI的渲染器是Canvas Render, 同样渲染2D物体的是Sprite Render

相同点：

- 都有一个渲染队列来处理透明物体，从后往前渲染
- 都可以通过图集并合并渲染批次，减少drawcall

不同点

- Canvas Render要与Rect Transform配合，必须在Canvas里使用，常用于UI。Sprite Render与transform配合，常用于gameplay
- Canvas Render基于矩形分隔的三角形网络，一张网格里最少有两个三角形（不同的image type, 三角形的个数也会不同），透明部分也占空间。Sprite Render的三角网络较为复杂，能剔除透明部分

[![img](/images/posts/关于UGUI-渲染机制/2148166-20220330074450774-604588640.png)](https://img2022.cnblogs.com/blog/2148166/202203/2148166-20220330074450774-604588640.png) 

Sprite会根据显示内容，裁剪掉元素中的大部分透明区域，最终生成的几何体可能会有比较复杂的顶点结构

 [![img](/images/posts/关于UGUI-渲染机制/2148166-20220330074513766-1361268972.png)](https://img2022.cnblogs.com/blog/2148166/202203/2148166-20220330074513766-1361268972.png)

Image会老老实实地为一个矩形的Sprite生成两个三角形拼成的矩形几何体 

 

**一个DrawCall的渲染流程：**

1. CPU发送Draw Call指令给GPU；
2. GPU读取必要的数据到自己的显存；
3. GPU通过顶点着色器（vertex shader）等步骤将输入的几何体信息转化为像素点数据；
4. 每个像素都通过片段着色器（fragment shader）处理后写入帧缓存；
5. 当全部计算完成后，GPU将帧缓存内容显示在屏幕上。

从上面的步骤可知，因为sprite的顶点数据更复杂，在第一步和第二步的效率会比image低，image会有更多的fragment shader的计算因为是针对每个像素的计算，sprite会裁剪掉透明的部分，从而减少了大量的片段着色器运算，并降低了overdraw，sprite会有更多的vertex shader的计算