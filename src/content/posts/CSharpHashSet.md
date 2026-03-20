---
title: 如何使用 C# 中的 HashSet
published: 2020-03-03
description: "所谓的HashSet，指的就是 `System.Collections.Generic` 命名空间下的 `HashSet<T>` 类，它是一个高性能，无序的集合"
tags: [C#, .NET, 数据结构]
category: 编程语言
draft: false
---



## HashSet 到底是什么



所谓的HashSet，指的就是 `System.Collections.Generic` 命名空间下的 `HashSet<T>` 类，它是一个高性能，无序的集合，因此HashSet它并不能做排序操作，也不能包含任何重复的元素，Hashset 也不能像数组那样使用索引，所以在 HashSet 上你无法使用 for 循环，只能使用 foreach 进行迭代，HashSet 通常用在处理元素的唯一性上有着超高的性能。


```csharp
using System;
using System.Collections.Generic;
//Create a C# program to print a message
class Program
{
    static void Main(string[] args)
    {
        HashSet<string> set = new HashSet<string>();
        set.Add("Hello");
        set.Add("World");
        set.Add("World");
        set.Add("!");
        foreach (string s in set)
        {
            Console.WriteLine(s);
        }
    }
}
```

