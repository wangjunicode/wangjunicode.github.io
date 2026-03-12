---
title: 关于CSharp-Delegate和Event以及UnityEvent
published: 2017-07-10
description: "Event作为C#语言特性的一部分，在.Net开发中具有比较重要的作用。当我们使用C#作为脚本语言编写Unity游戏时，也经常会需要使用Event解决各种问题。"
tags: []
category: 编程语言
draft: false
---

Event作为C#语言特性的一部分，在.Net开发中具有比较重要的作用。当我们使用C#作为脚本语言编写Unity游戏时，也经常会需要使用Event解决各种问题。

## Event是什么

要理解Event是什么，首先必须得知道它们的前身——Delegate是啥，中文翻译即“委托”。用一句话让你理解Delegate的作用就是“Delegate是一个可以存放函数的容器”。众所周知，变量是程序在内存中为数据开辟的一块空间，面向对象语言中变量可以存放一个具体的数值，或者某个对象的引用。C#则在该基础上更进一步，使用Delegate的机制让存放“函数（Function）”成为可能。 使用Delegate一般分为三步：

1. 定义一种委托类型
2. 声明一个该类型的委托函数
3. 通过声明的委托调用函数执行相关操作

还是通过一个简单的例子来了解委托的用法。假设现在我们分别要对奇数和偶数做不同的处理方案：

```c#
using System;

class Program
{
    public delegate void PrintDelegate(int num);
    static void Main(string[] args)
    {
        PrintDelegate print1 = Print1;
        Print(1, Print1);
        Print(2, Print2);
    }

    static void Print(int num, PrintDelegate print)
    {
        print(num);
    }

    static void Print1(int num)
    {
        System.Console.WriteLine("Odd number:{0}", num);
    }

    static void Print2(int num)
    {
        System.Console.WriteLine("Even number:{0}", num);
    }
}
```

在PrintNum函数中如果不用委托去处理，就需要通过if-else来调用不同的函数



# 基于delegate实现的Event（C# Event）



```c#
public delegate void EventHandler(object sender, EventArgs e);
```



```c#
using System;

public class EventExample
{
    public event EventHandler MyEvent;

    public void TriggerEvent()
    {
        // Check if there are any subscribers to the event
        if (MyEvent != null)
        {
            // Create an event argument
            EventArgs args = EventArgs.Empty;

            // Raise the event
            MyEvent(this, args);
        }
    }
}

public class Program
{
    public static void Main(string[] args)
    {
        EventExample example = new EventExample();

        // Subscribe to the event
        example.MyEvent += ExampleEvent_Handler;

        // Trigger the event
        example.TriggerEvent();
    }

    // Event handler method
    private static void ExampleEvent_Handler(object sender, EventArgs e)
    {
        Console.WriteLine("Event triggered!");
    }
}
```





# UnityEvent

经过上面的解释，你应该对event有个大概的了解。那么接下来我们来看阿奎那Unity在Event的基础上进行的改良，即UnityEvent。Event设计之初并不会想到应用于Unity游戏开发，所以它的弊端就在于纯代码编程，没有通过使用Unity Editor提高工作效率。而UnityEvent就可以看做是发挥Editor作用的正确改良。还记得上一节中粉丝是怎么订阅的嘛？你必须在每个粉丝对象中访问Idol的IdolDoSomethingHandler，然后把自己将采取的行动添加上去。这样有两个坏处——其一就是你必须时刻提防订阅的时机，假如不小心在Idol发动态之后才订阅，那你就永远收不到那条动态了。其二就是不方便管理，想要查看订阅偶像的所有粉丝，我们就得查找项目中所有IdolDoSomethingHandler的引用，然后再把每个粉丝的文件打开，可以说是非常麻烦了。

为了避免上述的缺点，UnityEvent使用Serializable让用户可以在Editor中直接绑定所有粉丝的调用，即一目了然又不用担心把握不准订阅的时机。

话不多说，我们直接上代码：

```c#
//使用Serializable序列化IdolEvent,否则无法在Editor中显示
[System.Serializable]
public class IdolEvent : UnityEvent<string>
{

}
```

把上面三个脚本绑定到三个GameObject上，但是不要着急立刻运行游戏，因为我们还没有让两个粉丝实现订阅。和使用Event时不同，UnityEvent在序列化后可以在Editor上显示，并且可以让我们在Editor阶段就设置好需要执行的函数。选中Idol所在的GameObject，然后就可以在Inspector中设置IdolEvent可以引用的函数。设置完成后应该如图所示:

![image](/images/posts/关于CSharp-Delegate和Event以及UnityEvent/unityEvent-169435090228620.png)

此时再运行游戏，你会得到和使用基于delegate的Event时相同的效果。

除此之外，UnityEvent依然提供和C# Event 类似的运行时绑定的功能，不过不同的是，UnityEvent是一个对象，向其绑定函数是通过AddListener()方法实现的。

由于UnityEvent是一个对象，所以自然可以允许我们通过继承实现自己的Event，实际上Unity中包括Button在内的许多UI组件的点击事件都是通过继承自UnityEvent来复写的。

可访问性(public/private)决定了UnityEvent的默认值，当可访问性为public时，默认会为其分配空间(new UnityEvent())；当可访问性为private时，默认UnityEvent为null，需要在Start()中为其分配内存。