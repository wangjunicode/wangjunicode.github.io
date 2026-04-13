---
title: NGUI渲染原理
published: 2019-04-15
description: "NGUI的核心架构，主要是：UIPanel、UIWidget、UIDrawcall。"
tags: []
category: 图形渲染
draft: false
---

NGUI的核心架构，主要是：UIPanel、UIWidget、UIDrawcall。

### UIWidget、UIPanel

**Widget是NGUI中负责界面显示的基础单位。**

所有需要在屏幕上显示出来的2D UI本质上都是一个Widget——包括Label、Sprite、Texture。

**而Panel，就是一个用来管理Widget的控件。**

每一个Widget都必定从属于一个Panel，不可例外——NGUI的根节点Root本身也包含一个Panel，而你不可能在Root之外创建Widget。

需要注意的是，Hierarchy中的UI层级关系，与NGUI自己内部的层级关系，并不一致。

![img](/images/posts/关于NGUI-渲染原理/v2-4fece7d7e81b2d77cc0249073dfd363c_b.png)

比如这样一个结构。
Panel_D是Widget_2的儿子，是Panel_A的孙子。
但是对于NGUI内部来说：
Panel_A和Panel_D是平级的，Widget_2和Panel_D并没有父子关系。



### 基础结构

在NGUI的架构中，首先存在一个静态的static List<UIPanel>，这个List包含所有的Panel
而每个Panel有两个属于自己的List：一个List<UIWidget>，一个List< UIDrawcall >
每个Panel都会在自己的子节点中向下寻找，把找到的Widget丢进自己的List中。
这个行为在每一次走到叶节点，或者遇到Panel的时候就会中断当前分支，跳到下一个分支。

比如说上图中Panel_A在找孩子的时候，走到Panel_D的时候就会中断当前分支，然后继续到Widget_3中去寻找。如此循环直到所有可获取的Widget都被装进List。

而对于Panel_D，也是如此。

![img](/images/posts/关于NGUI-渲染原理/v2-2b7b55ed71778cac3d76038b858f8951_b.png)

static List<UIPanel>内部包含一个Sort排序方法，会基于Panel的Depth进行一次排序。
而Panel内部也包含一个Sort排序方法，会基于Widget的Depth进行一次排序。
所以，虽然Panel和Widget都有Depth这个参数，但是这两个参数的地位是不一样的。

只要一个Panel的depth比另一个Panel小，这个Panel内部的所有Widget都会被先处理。


### DrawCall

一次Drawcall，就是CPU对GPU的一次调用

Drawcall是衡量渲染负担的一个重要指标。而且通常情况下，主要就是衡量CPU的负担。

所以，优化Drawcall主要就是尽可能的合并指令，让一个指令包含尽可能多的内容，以此降低CPU的负担。

###  NGUI的Drawcall处理

当一个Panel的List<Widget>排序完成后，Panel就会根据List<Widget>来生成List<Drawcall>
List<Widget>中的第一个Widget必定会创建一个新的Drawcall
之后的每一个Widget都会拿出来和前一个进行对比
如果两者的material、texture、shader（下简称M/T/S）一致，则把后面这个Widget也丢给同一个Drawcall处理

如果两者的M/T/S有不一样的地方，就创建一个新的Drawcall
也就是说，相同M/T/S且下标连续的Widget会共用一个Drawcall
而如果相同M/T/S的Widget中间隔着一个或多个不同M/T/S的Widget，就会拆分出许多额外的Drawcall。



![image-20230905165859556](/images/posts/关于NGUI-渲染原理/image-20230905165859556.png)

如图，在Widget相同但深度排序不同的情况下，各自所产生的List<Drawcall>

各个Panel的List<Drawcall>最终会合并汇总一个静态的ActiveDrawcallList，最终供渲染时调用，不过这个不重要，反正也没有人会去动这里。

通常情况下，做好depth深度管理，尽可能的减少Drawcall就可以有效提高渲染效率。

但有一点需要特别注意的就是。对于CPU来说，调用Drawcall需要耗费时间，而构建Drawcall同样需要耗费时间。

NGUI在运行的过程中，如果某一个Panel下面有任意一个Widget进行了一点非常微小的变动：比如移动了一点点距离。那么这个Panel就会清空自己的List<Drawcall>，从头再遍历所有Widget，重新构建所有Drawcall。而这个过程显然是非常耗费性能的。

**所以，有时候可以根据Widget的用途，将动态Widget和静态Widget拆分到不同Panel，如此一来虽然增加了Drawcall的数量，但最终结果却反而能提升渲染效率。**



### 渲染序列

NGUI里的每一个Panel都有一个Render Q的设置选项。

RenderQ有两种主要模式：
Automatic —— 无参数
StartAt —— 需要设置一个整数参数

大多数时候我们不需要动这个东西。如果全部都默认的Automatic的话，NGUI会自己帮我们按照Panel的depth为第一优先级，Widget的depth为第二优先级来处理好渲染序列。



### UIDrawCall实现

UIDrawCall负责把顶点,UV,颜色等数据输入到网格和构建材质，最终绘制出我们看到的UI图形.

- UpdateGeometry() 最核心最重要的方法, 通过顶点,UV,颜色,贴图等信息绘制UI图形
- UpdateMaterials() 更新Material
- RebuildMaterial() 重新生成材质
- CreateMaterial() 创建新的材质
