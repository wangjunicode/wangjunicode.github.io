---
title: C#中常用容器的使用与底层数据结构
published: 2017-03-09
description: "深入理解 C# 泛型集合类：List<T>、Dictionary<TK,TV>、Queue<T>、Stack<T>、HashSet<T> 的底层原理、性能特点及游戏开发中的最佳实践。"
tags: [C#, .NET, 数据结构]
category: 编程语言
draft: false
---

C#中常用容器的使用与底层数据结构

### Array

数组在C#中最早出现的。在内存中是连续存储的，所以它的索引速度非常快，而且赋值与修改元素也很简单。

```csharp
string[] s=new string[2]; 

//赋值 
s[0]="a"; 
s[1]="b"; 
//修改 
s[1]="a1"; 
```



但是数组存在一些不足的地方。在数组的两个数据间插入数据是很麻烦的，而且在声明数组的时候必须指定数组的长度，数组的长度过长，会造成内存浪费，过短会造成数据溢出的错误。如果在声明数组时我们不清楚数组的长度，就会变得很麻烦。
针对数组的这些缺点，C#中最先提供了ArrayList对象来克服这些缺点。 

**Array底层数据结构就是数组。**



### ArrayList

ArrayList是命名空间System.Collections下的一部分，在使用该类时必须进行引用，同时继承了IList接口，提供了数据存储和检索。ArrayList对象的大小是按照其中存储的数据来动态扩充与收缩的。所以，在声明ArrayList对象时并不需要指定它的长度。



```csharp
ArrayList list1 = new ArrayList(); 
 
//新增数据 
list1.Add("cde"); 
list1.Add(5678); 
 
//修改数据 
list[2] = 34; 
 
//移除数据 
list.RemoveAt(0); 
 
//插入数据 
list.Insert(0, "qwe"); 
```



从上面例子看，ArrayList好像是解决了数组中所有的缺点，为什么又会有List？
我们从上面的例子看，在List中，我们不仅插入了字符串cde，而且插入了数字5678。这样在ArrayList中插入不同类型的数据是允许的。因为ArrayList会把所有插入其中的数据当作为object类型来处理，在我们使用ArrayList处理数据时，很可能会报类型不匹配的错误，也就是ArrayList不是类型安全的。在存储或检索值类型时通常发生装箱和取消装箱操作，带来很大的性能耗损。

**装箱与拆箱**

装箱：就是将值类型的数据打包到引用类型的实例中
比如将string类型的值abc赋给object对象obj
拆箱：就是从引用数据中提取值类型
比如将object对象obj的值赋给string类型的变量

装箱与拆箱的过程是很损耗性能的。 

**ArrayList底层数据结构就是数组。类似于C++里面没有泛型的Vector。**



### 泛型List
因为ArrayList存在不安全类型与装箱拆箱的缺点，所以出现了泛型的概念。List类是ArrayList类的泛型等效类，它的大部分用法都与ArrayList相似，因为List类也继承了IList接口。最关键的区别在于，在声明List集合时，我们同时需要为其声明List集合内数据的对象类型。

```csharp
List<string> list = new List<string>(); 
//新增数据 
list.Add(“abc”); 
//修改数据 
list[0] = “def”; 
//移除数据 
list.RemoveAt(0); 
```



**泛型List底层数据结构就是数组。类似于C++里面的Vector。**



### LinkedList

用双链表实现的List，特点是插入删除快，查找慢



### HashSet/HashTable/Dictionary

这三个容器的底层都是Hash表。



在单线程的时候使用Dictionary更好一些，多线程的时候使用HashTable更好。

因为HashTable可以通过Hashtable tab = Hashtable.Synchronized(new Hashtable());获得线程安全的对象。