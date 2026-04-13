---
title: ILRuntime使用
published: 2020-11-05
description: "**使用ILRuntime，你可能需要了解这些**"
tags: []
category: 编程语言
draft: false
---

**使用ILRuntime，你可能需要了解这些**


# ILRuntime实战开发

参考：https://www.bilibili.com/video/BV1GA411P7Xs?p=2&vd_source=f137f521f120be6bdf374850a92855ec

## 搭建环境输出HelloWorld

包管理安装ilruntime, 修改设置允许unsafe，切换到dotnet 4.x

热更工程新增一个类

![image-20240123004316450](/images/posts/ILRuntime使用/image-20240123004316450.png)

主工程新建一个hotfixmanager类，加载热更程序集，再通过appdomain，load进来

再在主工程新建一个测试代码

![image-20240123004701895](/images/posts/ILRuntime使用/image-20240123004701895.png)

## 实现热更MonoBehaviour

![image-20240123004807802](/images/posts/ILRuntime使用/image-20240123004807802.png)

主工程创建一个适配器类

```csharp
public class HotfixMonoBehaviourAdapter:MonoBehaviour
{
    public string bindClass = "HotFix_Project.HotFixMonoBehaviour";
	private void Awake()
	{
		//根据字符串获取类型
		classType = HotfixMgr.instance.appdomain.LoadedTypes[bindClass];
		//再创建对应的实例
		instance = (classType as ILType).Instantiate();
		//然后再反射调用
		IMethod awake_method = classType.GetMethod("Awake", 0);
		if(awake_method != null)
		{
			HotfixMgr.instance.appdomain.Invoke(awake_method, instance);
		}
	}
}
```

热更工程创建一个HotFixMono

```csharp
public class HotFixMonoBehaviour
{
	void Awake()
	{
	
	}
}
```

## 热更类型可视化编辑

![image-20240123110229663](/images/posts/ILRuntime使用/image-20240123110229663.png)



## **IL2CPP/Mono**

**Mono**
Mono虚拟机保证跨平台，C#这样遵循CLI（Common Language Infrastructure）规范的高级语言，被先被各自的编译器编译成中间语言：IL（中间语言） ，等到需要真正执行的时候，这些IL会被加载到运行时库，由Mono虚拟机动态的编译成汇编代码（JIT）然后在执行。
**IL2CPP**
现在出现了IL2CPP，顾名思义，就是把IL中间语言转换成CPP文件，这么做的原因有很多，比如说Mono的各个移植很费劲，Mono的版权等等，现在可以在得到中间语言IL后，使用IL2CPP将他们重新变回C++代码，然后再由各个平台的C++编译器直接编译成能执行的原生汇编代码。

- ios
  目前unity只有il2cpp模式的编译才支持64位系统，mono是不支持的。
  苹果在2016年1月就要求所有新上架游戏必须支持64位架构，所以必须要选il2cpp。

- android
  从2019年8月1日起，在Google Play上发布app必须支持64位体系。从021年8月1日起，Google Play将停掉尚未支持64位体系的APP。
  在国内上架应该 32 64 都可以



## 为何Ios热更困难
因为 iOS平台禁止JIT编译

AOT（Ahead Of Time）、JIT（Just In Time）、Full AOT

- JIT即时编译：
  从名字就能看的出来，即时编译，或者称之为动态编译，是在程序执行时才编译代码，解释一条语句执行一条语句
- AOT静态编译：
  其实Mono的AOT静态编译和JIT并非对立的。AOT同样使用了JIT来进行编译，只不过是被AOT编译的代码在程序运行之前就已经编译好了。当然还有一部分代码会通过JIT来进行动态编译。
- Full AOT
  默认情况下AOT并不编译所有IL代码，而是在优化和JIT之间取得一个平衡。由于iOS平台禁止JIT编译，于是Mono在iOS上需要Full AOT编译和运行。即预先对程序集中的所有IL代码进行AOT编译生成一个本地代码映像，然后在运行时直接加载这个映像而不再使用JIT引擎
- IL2CPP
  由于C++是一门静态语言，这就意味着我们不能使用动态语言的那些酷炫特性。运行时生成代码并执行肯定是不可能了，使用了IL2CPP，就完全是AOT方式了



## ILRuntime原理

**官网**
https://ourpalm.github.io/ILRuntime/public/v1/guide/principle.html
**更直观的解释：**





![在这里插入图片描述](/images/posts/ILRuntime使用/watermark,type_ZmFuZ3poZW5naGVpdGk,shadow_10,text_aHR0cHM6Ly9ibG9nLmNzZG4ubmV0L3FpYW9rZWx6,size_16,color_FFFFFF,t_70#pic_center.png)



补充：



```csharp
public class Example
{
    static void Main()
    {
        Console.WriteLine("Hey IL!!!");
    }
}
```



最初，CLR知道有关类型的所有详细信息以及由于元数据而从该类型中调用什么方法。

当CLR开始在本地CPU指令中执行IL时，CLR会为Main的代码所引用的每种类型分配内部数据结构。

在我们的例子中，我们只有一个类型的Console，因此CLR将通过该内部结构分配一个内部数据结构，我们将管理对引用类型的访问

在该数据结构内部，CLR包含该类型定义的所有方法的条目。每个条目都包含可在其中找到该方法的实现的地址。

初始化此结构时，CLR会将每个条目设置在CLR本身内部包含的未记录的FUNCTION中。您可以猜测到，此FUNCTION是我们所谓的JIT编译器。

总的来说，您可以将JIT编译器视为CLR函数，它将IL编译为本地CPU指令。让我详细向您展示此过程在我们的示例中将如何进行。

1.Main首次调用WriteLine时，将调用JITCompiler函数。

2.JIT编译器函数知道正在调用什么方法以及定义此方法的类型。

3.然后，Jit编译器在定义了该类型的程序集中进行搜索，并在我们的WriteLine方法的IL代码中获取由该类型定义的方法的IL代码。

4.JIT编译器分配DYNAMIC内存块，然后JIT验证并将IL代码编译为本地CPU代码并将该CPU代码保存在该内存块中。

5.然后，JIT编译器返回内部数据结构条目，并将地址(主要参考WriteLine的IL代码实现)替换为地址新动态创建的内存块，其中包含WriteLine的本机CPU指令。

6.最后，JIT编译器功能跳转到内存块中的代码。
这段代码是WriteLine方法的实现。

### Unity中文课堂中的ILRuntime学习

![img](https://pic4.zhimg.com/80/v2-59d4ae375aa1642e01512e3f3d7e49f3_720w.webp)

![img](https://pic2.zhimg.com/80/v2-560f0ddd8b12512584f1b580f8f18c81_720w.webp)

参考：https://zhuanlan.zhihu.com/p/444589931
