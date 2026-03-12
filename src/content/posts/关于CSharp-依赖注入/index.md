---
title: 关于CSharp-依赖注入
published: 2023-09-18
description: "依赖注入 .NET 支持依赖关系注入 (DI) 软件设计模式，这是一种在类及其依赖项之间实现[控制反转 (IoC)](https://learn.microso"
tags: []
category: 编程语言
draft: false
---

依赖注入

# 依赖关系注入

.NET 支持依赖关系注入 (DI) 软件设计模式，这是一种在类及其依赖项之间实现[控制反转 (IoC)](https://learn.microsoft.com/zh-cn/dotnet/architecture/modern-web-apps-azure/architectural-principles#dependency-inversion) 的技术。

CSharpDoc>.Net基础知识文档>运行时库>依赖关系注入



# 依赖注入与依赖注入容器

依赖注入是一种解耦代码的软件设计原则和模式，作用就是开发解耦合的代码

## 为什么要解耦？

开发过程可以更加独立模块，便于开发，便于扩展，便于单元测试，便于维护

# 实例讲解

对于一个游戏系统来说，通常分为以下几层

- 视图层：就是界面，通常由一些控件和列表组成
- 表现层：处理UI的逻辑部分，包含一些按钮事件调用函数，一些列表存储数据的对象
- 数据访问层：负责与数据仓库的交互代码。比如向数据仓库请求获取数据，将数据存储到对象中，以便应用的其他模块调用
- 数据仓库：获取实际数据的地方

对应的代码结构可能是：

- PersonViewWindow
- PersonViewModel
- ServiceReader
- Person

## 什么是紧耦合

![image-20240102112816032](/images/posts/关于CSharp-依赖注入/image-20240102112816032.png)

耦合：当我们在代码里实例化一个对象的时候，耦合就产生了。比如在PeopleViewWindow的构造函数里实例化了一个PeopleViewModel。另外我们实例化一个对象，就得负责这个对象的生命周期。当我们想在多个模块共享这个对象的时候，也会出现问题。

## 紧耦合是如何影响我们的代码的

当希望程序连接不同数据源的时候，比如懒惰的处理就是价格switch case：

![img](https://img2020.cnblogs.com/blog/711185/202007/711185-20200702135350275-1976313031.png)

代码比较挫，但姑且满足功能；但现在又有了新需求，希望支持缓存数据，那应该怎么做呢？同时还要求缓存时可选的。于是我们继续switch

![img](https://img2020.cnblogs.com/blog/711185/202007/711185-20200702135433000-1153200777.png)

到这里，应该感觉到代码有些问题了，问题出在哪呢？我们来看。
问题在于，这部分代码违反了 SOLID 原则中的 S，也就是单一职责原则（Single Responsibility Principle）。

单一职责原则告诉我们，对象应当只有一个原因去作出变更。但是我们的 PeopleViewModel 有多个职责。主要的职责是表现层逻辑，但是它还负责为应用程序选择数据源，以及负责这些数据源的生命周期。现在，它还要决定我们是否使用缓存。毫无疑问，这肯定包含了太多的职责，这也是为什么代码会变得越来越难维护。

不仅如此，客户还要求有单元测试。

单元测试能够帮助我们节约很多编码时间。如果我们尝试为表现层的 PeopleViewModel 写单元测试，就需要实例化 PeopleViewModel 对象。但是在 PeopleViewModel 的构造函数中，我们实例化了 ServiceReader，而 ServiceReader 实例化了连接 Web 服务的 WebClient 对象。意味着测试想要正常工作，Web 服务就需要保持运行。

## 使用依赖注入解耦合应用

下面，我们就使用依赖注入进行代码解耦合。

首先，我们给代码添加一层抽象。然后，我们会使用依赖注入中的一种模式——构造函数注入，来创建解耦合的代码。
在之前我们设想的方案中，问题主要出在类 PeopleViewModel 上，也就是应用的表现层，尤其是类 PeopleViewModel 的构造函数，实例化类 ServiceReader 的地方。

因此，我们将关注于类 PeopleViewModel 和 ServiceReader 的解耦。如果我们解耦成功，我们就能够更容易地满足用户的需求。

所以，总体来讲，解耦可以分为三步：

- 添加一个接口，一个抽象层，增加代码灵活性
- 在应用程序代码中加入构造函数注入
- 将解耦的各个模块组合到一起

首先第一步，我们需要思考下如何才能够让我们的应用程序连接不同的数据源。

这里直接引入 Repository 模式。

Repository 模式作为应用程序对象和数据获取模块的媒介，使用类似集合的接口来获取应用程序对象。它将应用程序从特定的数据存储技术分割了出来。

Repository 的思想是知道如何和数据源沟通，不管是 HTTP，文件系统上的文档，还是数据库访问。在获得这些数据之后，将其转换成应用程序其他模块可以使用的 C# 对象。

emm，这不就是 ServiceReader 现在干的事情嘛。它对 Web 服务发起了一个 HTTP 请求，然后将 JSON 格式的结果转换成应用程序可以理解的 People 类对象。但是问题在于表现层的 PeopleViewModel 与数据访问层的 ServiceReader 直接进行了交互。

为了我们的应用更加地灵活，我们给 Repository 加上接口，所有在表现层的通信都将通过这个接口实现。

这符合 SOLID 原则中的 D，也就是依赖倒置原则（Dependency Inversion Principle）。依赖倒置原则中的一点是，上层的模块不应该依赖于下层的模块，应该都依赖于接口。

有了抽象，表现层就可以很容易的与 CSV 或者 SQL Repository 通信了。

![img](https://img2020.cnblogs.com/blog/711185/202007/711185-20200702135630529-447378243.png)

基于此，我们将创建一个数据读取接口，IPersonReader。接口包含了一个 GetPeople 函数，返回所有的 Person 对象，还有一个 GetPerson 方法检索单个人的信息。

我们回到表现层的 PeopleViewModel，将成员变量 ServiceReader 改为 IPersonReader。这只是解耦的一小部分，我们需要的是避免在构造函数中实例化 ServiceReader。

所以，下面我们准备解耦表现层的 PeopleViewModel 和 数据访问层的 ServiceReader。
解耦的方式是，通过构造函数，注入 ServiceReader 到 PeopleViewModel， 注入 PeopleViewModel 到 PeopleViewerWindow，然后再将这些对象组合在一起。

我们来看下，在 PeopleViewModel 中的构造函数中，我们不希望实例化 ServiceReader。因为选取数据源不是 PeopleViewModel 的职责。
所以我们给构造函数添加一个参数，通过这个参数我们将 ServiceReader 对象传递给 PeopleViewModel 的成员变量 IPersonReader。

这个添加构造函数参数的简单操作，其实就实现了依赖注入。

我们没有消除依赖，PeopleViewModel 仍然依赖于 IPersonReader，我们通过这个接口调用 GetPeople。
但是 PeopleViewModel 不再需要管理依赖对象，我们通过构造函数注入依赖，这就是为什么这个模式叫做构造函数注入。

这个时候如果我们编译程序会发现，PeopleViewerWindow 的代码出错了，因为它想要实例化一个无参的 PeopleViewModel 构造函数。我们可以在 PeopleViewerWindow 中实例化 ServiceReader，但是实例化 ServiceReader 不是 PeopleViewModel 的职责，所以更加不是 PeopleViewerWindow 的职责。

那么怎么解决呢？
我们把这个问题丢出去，不管谁创建了 PeopleViewModel，都应该负责创建一个 ServiceReader。所以我们仍然用构造函数将 PeopleViewModel 注入到 PeopleViewerWindow。

有件事注意一下，这里我们没有给 PeopleViewModel 创建接口，通常我们只在需要的时候添加接口，因为接口增加了一层复杂性以及对代码进行了重定向。以我们一贯的经验来看，View 和 ViewModel 之间的关系大多是一对一或者多对一的，因此我们不介意在这有具体类的耦合。
如果我确实需要将多个 PeopleViewModel 绑定到同一个 PeopleViewerWindow，那么我会先添加一个接口。

接下来，我们需要将各个解耦合的模块组合起来，我们打开 App.xaml.cs 文件，在 OnSratup 方法中实例化 PeopleViewerWindow，由于 PeopleViewerWindow 的构造函数需要一个 PeopleViewModel 的对象，所以我们需要首先实例化 PeopleViewModel，而 PeopleViewModel 的构造函数需要一个 IPersonReader 类型的对象，所以我们还得先实例化一个 ServiceReader 对象并注入到 PeopleViewModel 的构造函数。

我们来回顾下这部分内容，我们对 PeopleViewModel 和 ServiceReader 通过构造函数注入进行解耦。

![img](https://img2020.cnblogs.com/blog/711185/202007/711185-20200702135722648-1443119832.png)

我们给构造函数增加了一个参数，同时增加了依赖注入，而不是在内部处理依赖。类 PeopleViewModel 依赖 IPersonReader，因为需要调用接口 IPersonReader 的 GetPeople 方法。
我们没有消除依赖，我们只是控制了怎么处理依赖，通过添加构造函数注入，我们把处理依赖的部分丢给了 Bootstrapper 模块，这就是依赖注入实现的方式。

参考：https://www.cnblogs.com/Steven-HU/p/13224340.html