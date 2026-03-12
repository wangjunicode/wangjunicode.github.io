---
title: C#函数参数传递
published: 2017-03-02
description: "**C#中的数据类型**：分值类型和引用类型两大类."
tags: []
category: 编程语言
draft: false
---

## C# 函数参数传递(按值和引用)



**C#中的数据类型**：分值类型和引用类型两大类.

- 值类型: 直接存储数据的值,保存在内存中的stack(堆栈)中
- 引用类型: 存储对值的引用,实际上存储的就是一个内存的地址.引用类型的保存分成两块,实际值保存在托管堆(heap)中.实际值的内存地址保存在stack中

当使用引用类型时先找到stack中的地址,再找到heap中的实际值.也就是说保存引用类型时要用到stack和heap,但使用引用类型时我们实际上只用到stack中的值,然后通过这个值间接的访问heap中的值。C#预定义的简单类型,像int,float,bool,char都是值类型，另外enum(枚举),struct(结构)也是值类型 string,数组,自定义的class就都是引用类型了.其中的string是比较特殊的引用类型.C#给它增加个字符恒定的特性.



C#函数的参数如果不加ref,out这样的修饰符显式申明参数是通过引用传递外,默认都是值传递.

**按值传递参数**



```c#
public class temp
{
    //Create a main func
    static void Main()
    {
        // System.Console.WriteLine("Hello World!");
        int anum = 1;
        int[] aarray = { 1, 2, 3 };
        ChangeInt(anum);
        ChangeArray(aarray);
        Console.WriteLine("value of num: " + anum);
        Console.Write("value of aarray: ");
        foreach (int i in aarray)
            Console.Write(i + " ");
    }
    static void ChangeInt(int num)
    {
        num = 123;
    }
    static void ChangeArray(int[] array)
    {
        array[0] = 10;
    }
}
```

　　

```
[Running] echo= && csc /nologo /utf8output temp.cs && temp
 
value of num: 1
value of aarray: 10 2 3 
[Done] exited with code=0 in 1.978 seconds
```

　　



**按引用传递参数**



```c#
namespace NewBlog
{
    public class temp
    {
        //Create a main func
        static void Main()
        {
            // System.Console.WriteLine("Hello World!");
            int anum = 1;
            int[] array = { 1, 2, 3 };
            // ChangeInt(anum);
            // ChangeArray(aarray);

            ChangeInt(ref anum);
            ChangeArray(ref array);
            Console.WriteLine("value of num: " + anum);
            Console.Write("value of aarray: ");
            foreach (int i in array)
                Console.Write(i + " ");
        }

        static void ChangeInt(int num)
        {
            num = 123;
        }

        static void ChangeInt(ref int num)
        {
            num = 123;
        }

        static void ChangeArray(int[] array)
        {
            array[0] = 10;
        }

        static void ChangeArray(ref int[] array)
        {
            array[0] = 10;
            array = new int[]{6,7,8};
        }
    }
}
```


