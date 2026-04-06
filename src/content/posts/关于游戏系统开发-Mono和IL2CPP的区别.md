---
title: Mono和IL2CPP的区别
published: 2022-05-25
description: "Unity跨平台得益于Mono虚拟机能将IL转成对应平台机器码在该平台执行"
tags: [Unity, Mono, IL2CPP]
category: 架构设计
draft: false
encryptedKey: henhaoji123
---

Unity跨平台得益于Mono虚拟机能将IL转成对应平台机器码在该平台执行

Mono选项的脚本后处理方式，对应的是JIT，运行时将IL转成本机机器代码（生成代码），然后执行编译后的代码

IL2CPP选项的脚本后处理方式，对应的是AOT，运行时先将IL转成CPP，再由对应平台编译执行CPP


## 一、Unity是如何实现跨平台的？

首先，什么是跨平台？

> 跨平台：一次编译，不需要任何代码修改，应用程序就可以运行在任意在平台上跑，即代码不依赖于操作系统，也不依赖硬件环境。

做游戏都知道，游戏肯定需要跨平台，不能只支持一种平台，不然每个对应的平台做出一种对应的编译器，那真的会累死。所以对于跨平台的需求，对于游戏开发而言，很重要。Unity的架构需求设计当然也需要这个特性。



至于Unity是如何实现跨平台的？这就得提到Unity脚本后处理(Scripting Backend)的两种方式**Mono和IL2CPP**。



## 二、Mono介绍

> **Mono**是一个由[Xamarin](https://link.zhihu.com/?target=https%3A//zh.wikipedia.org/wiki/Xamarin)公司所主持的自由开放源码项目。
> Mono的目标是在尽可能多的平台上使.net标准的东西能正常运行的一套工具，核心在于“跨平台的让.net代码能运行起来“。
> Mono组成组件：C# 编译器，CLI虚拟机，以及核心类别程序库。
> Mono的编译器**负责生成符合公共语言规范的映射代码**，即公共中间语言（Common Intermediate Language，**CIL**），我的理解就是工厂方法实现不同解析。
> **IL科普**
> IL的全称是 Intermediate Language，很多时候还会看到**CIL**（特指在.Net平台下的IL标准）。翻译过来就是中间语言。
> 它是一种属于通用语言架构和.NET框架的低阶的人类可读的编程语言。
> CIL类似一个面向对象的汇编语言，并且它是完全基于堆栈的，它运行在虚拟机上（.Net Framework, Mono VM）的语言。

### **2.1 工作流程**

1. 通过C#编译器mcs，将C#编译为IL（中间语言，byte code）
2. 通过Mono运行时中的编译器将IL编译成对应平台的原生码

### **2.2 知识点**

**2.2.1. 编译器**

> C#编译器mcs：将C#编译为**IL**
> Mono Runtime编译器：将IL转移为**原生码**。

**2.2.2. 三种转译方式**

> **即时编译（Just in time,JIT）**：程序运行过程中，将CIL的byte code转译为目标平台的原生码。
> **提前编译（Ahead of time,AOT）**：程序运行之前，将.exe或.dll文件中的CIL的byte code部分转译为目标平台的原生码并且存储，程序运行中仍有部分CIL的byte code需要JIT编译。
> **完全静态编译（Full ahead of time,Full-AOT）**：程序运行前，将所有源码编译成目标平台的原生码。

**2.2.3 Unity跨平台的原理**

> Mono运行时编译器支持将IL代码转为对应平台原生码
> IL可以在任何支持CLI,通用语言环境结构)中运行，IL的运行是依托于Mono运行时。

**2.2.4 IOS不支持jit编译原因**

> 机器码被禁止映射到内存，即封存了内存的可执行权限，变相的封锁了jit编译方式.[详情见](https://link.zhihu.com/?target=https%3A//www.cnblogs.com/murongxiaopifu/p/4278947.html)

**2.2.5 JIT编译**

> 将IL代码转为对应平台原生码并且将原生码映射到虚拟内存中执行。JIT编译的时候IL是在依托Mono运行时，转为对应的原生码后在依托本地运行。

### 2.3 优点

1. 构建应用非常快
2. 由于Mono的JIT(Just In Time compilation ) 机制, 所以支持更多托管类库
3. 支持运行时代码执行
4. 必须将代码发布成托管程序集(.dll 文件 , 由mono或者.net 生成 )
5. Mono VM在各个平台移植异常麻烦，有几个平台就得移植几个VM（WebGL和UWP这两个平台只支持 IL2CPP）
6. Mono版本授权受限，C#很多新特性无法使用
7. iOS仍然支持Mono , 但是不再允许Mono(32位)应用提交到Apple Store

**Unity 2018 mono版本仍然是mono2.0、unity2020的版本更新到了mono 5.11。**



### **3.1 AOT编译器**

> IL2CPP AOT编译器名为il2cpp.exe。
> 在Windows上，您可以在`Editor \ Data \ il2cpp`目录中找到它。
> 在OSX上，它位于Unity安装的`Contents / Frameworks / il2cpp / build`目录中
> il2cpp.exe 是由C#编写的受托管的可执行程序，它接受我们在Unity中通过Mono编译器生成的托管程序集，并生成指定平台下的C++代码。



### **3.2 运行时库**

> IL2CPP技术的另一部分是运行时库（libil2cpp），用于支持IL2CPP虚拟机的运行。
> 这个简单且可移植的运行时库是IL2CPP技术的主要优势之一！
> 通过查看我们随Unity一起提供的libil2cpp的头文件，您可以找到有关libil2cpp代码组织方式的一些线索
> 您可以在Windows的`Editor \ Data \ PlaybackEngines \ webglsupport \ BuildTools \ Libraries \ libil2cpp \ include`目录中找到它们
> 或OSX上的`Contents / Frameworks / il2cpp / libil2cpp`目录。



### **3.3 为啥要转成CPP呢？**

1. 运行效率快

> 根据官方的实验数据，换成IL2CPP以后，程序的运行效率有了1.5-2.0倍的提升。

2. Mono VM在各个平台移植，维护非常耗时，有时甚至不可能完成

> Mono的跨平台是通过Mono VM实现的，有几个平台，就要实现几个VM，像Unity这样支持多平台的引擎，Mono官方的VM肯定是不能满足需求的。所以针对不同的新平台，Unity的项目组就要把VM给移植一遍，同时解决VM里面发现的bug。这非常耗时耗力。这些能移植的平台还好说，还有比如WebGL这样基于浏览器的平台。要让WebGL支持Mono的VM几乎是不可能的。

3. 可以利用**现成的在各个平台的C++编译器**对代码执行**编译期优化**，这样可以进一步**减小最终游戏的尺寸并提高游戏运行速度**。

4. 由于动态语言的特性，他们多半无需程序员太多关心内存管理，所有的内存分配和回收都由一个叫做GC（Garbage Collector）的组件完成。

虽然通过IL2CPP以后代码变成了静态的C++，但是内存管理这块还是遵循C#的方式，这也是为什么最后还要有一个 **IL2CPP VM**的原因：**它负责提供诸如GC管理，线程创建这类的服务性工作。**

但是由于去除了**IL加载和动态解析**的工作，**使得IL2CPP VM可以做的很小**，**并且使得游戏载入时间缩短**。