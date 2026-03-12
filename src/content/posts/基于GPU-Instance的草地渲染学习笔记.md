---
title: 基于GPU Instance的草地渲染学习笔记
published: 2020-08-08
description: "简单概括一句话就是：传递一个对象的Mesh，指定其绘制次数和材质，Unity就会为我们在GPU的`统一/常量缓冲区`开辟好必要的缓冲区，然后以我们指定的材质对M"
tags: []
category: 图形渲染
draft: false
---

## GPU Instance的底层原理

简单概括一句话就是：传递一个对象的Mesh，指定其绘制次数和材质，Unity就会为我们在GPU的`统一/常量缓冲区`开辟好必要的缓冲区，然后以我们指定的材质对Mesh进行我们指定次数的渲染，这样就可以达成一次Drawcall绘制海量对象的目的。




好处在于：

- 传统渲染方式（无合批情形）：绘制多少个对象就要整理和传递多少次数据，其中整理和传递数据的过程消耗极大，多数为性能瓶颈
- GPU Instance：只用从CPU往GPU传递一次数据，大大提高了渲染效率。

对于Unity的GPU Instance来说，从数据处理的角度其实也可以分为两类：

- 第一种是使用了 `支持并启用了GPU Instance的Shader` 的材质的物体在进行渲染时（例如我们通过Gameobject.Instantiate实例化了100w个正方体），Unity会对所有渲染对象进行特殊处理，为所有的渲染目标在GPU的常量缓冲区（Constant Buffer中）准备各种缓冲区（顶点数据缓冲区，材质数据缓冲区，transform矩阵数据缓冲区等）
- 第二种是我们自己调用GPU Instance API进行实例绘制，那么Unity只会根据我们所传递的参数为其准备顶点缓冲区，材质数据缓冲区，对于矩阵数据缓冲区或者其他自定义数据是不提供的，也就需要我们自己通过ComputeBuffer来传递这些数据，然后在Shader中根据instanceId进行处理。例如我们使用GPU Instance API绘制100w个三角形，那么Unity会控制GPU后端为我们准备一个能容纳300w个顶点的缓冲区和一个材质数据缓冲区。



参考Colin大神的仓库，这次的效果最为震撼和炫酷——[基于GPU Instance的草地渲染](https://link.zhihu.com/?target=https%3A//github.com/ColinLeung-NiloCat/UnityURP-MobileDrawMeshInstancedIndirectExample)

![img](基于GPU-Instance的草地渲染学习笔记/v2-166969823d3999ab925c05c3bf53af46_b.jpg)