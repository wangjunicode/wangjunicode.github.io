---
title: 关于CSharp-String究竟是个什么类型
published: 2019-05-06
description: "String类型对象直接派生自Object，所以String是引用类型"
tags: [C#, 字符串, 编程语言]
category: 编程语言
draft: false
---

String类型对象直接派生自Object，所以String是引用类型

> 面试官：c#中的String是什么类型呢？
> 我：应该是个值类型
> 面试官：感谢您参与本司面试

> 面试官：c#中的String是什么类型呢？
> 我：是个特殊的引用类型！
> 面试官：怎么个特殊法呢？
> 我：。。。

String类型对象直接派生自Object，所以String是引用类型，因此，String对象总是存在于堆上，永远不会跑到线程栈。
但String类型却又有值类型的特性，所以问到String究竟是值类型还是引用类型时，我们一般称为特殊的引用类型。
具体请看以下例子：

```csharp
string str1 = "str1";
string str2 = str1;
str1 = "str3";

Console.WriteLine(str1);//str3
Console.WriteLine(str2);//str1
```

按普通引用类型的特性来理解以上代码，str2应该指向str1的同一个内存地址，若此时修改str1的值，str2应该也会发生变化，但修改str1的值为“str3”后，str2的值仍然为“str1”，这就是上文所说的String类型具有值类型的特征。
出现上述情况其实是因为字符串是“不变的”这一特性。出于性能考虑，String类型与CLR紧密集成。具体地说，CLR知道String类型中定义的字段如何布局，会直接访问这些字段。但为了获得这种性能和直接访问的好处，String只能为密封类。即不可把String作为自定义类型的基类，以防破坏了CLR对String类型的预设。而String对象的“不可变”特性就是CLR对String对象的预设之一，是String对象最重要的一个特性，也是引起上文所说的“String类型具有值类型特征”的原因。下文来具体说一下String类型的几个重要特性。

### 字符串的不变性
String对象一旦创建，就不能再更改，包括不能变长、变短或修改其中任何字符。
上文代码中str1="str3"看似修改了字符串，但实际上是创建了一个新的String对象，并把原引用指向这个新对象，对于旧的“str1”是没有被改动的，所以最后str2仍然是指向这个旧的“str1”对象。
字符串的不可变简单地说有以下优点：

- 可以连续使用ToUpper、Substring等修改字符串的方法，但又不影响原本字符串

- 访问字符串不会发生线程同步问题

- CLR可优化多个值相同的String变量指向同一个String对象，从而减少内存中String数量（字符串留用） 


但需要注意的是，因为字符串的不变性，在进行字符串拼接、修改等操作时，实际上会产生大量的临时字符串对象，造成更频繁的垃圾回收，从而影响应用程序性能。若要高效执行大量字符串拼接操作，建议使用StringBuilder类。

### 字符串留用
因为字符串的“不可变”性，在内存中对同一个字符串复制多个实例是纯属浪费，在内存中只保留字符串的一个实例可以显着降低内存消耗，需要引用该字符串的所有变量都统一指向该字符串对象即可。
CLR初始化时，会在内部创建一个哈希表，这个表中，key是字符串，value则是托管堆中String对象的引用。String类型提供了静态方法Intern和IsInterned以便访问这个内部哈希表。

```csharp
public static String Intern(String str);
public static String IsInterned(String str);
```

Intern方法，它首先会获取参数String对象的哈希码，并在内部哈希表中检查是否有相匹配的，若存在，则返回对该String对象的引用，若不存在则创建该字符串副本，把副本添加到哈希表中，并返回该副本的引用。
IsInterned方法也是获取参数String对象的哈希码，并在内部哈希表中查找他，若存在，则返回该String对象的引用，若不存在则返回null，不会添加到哈希表中。

```csharp
string str1 = "Hello World";
string str2 = "Hello World";

bool equal = string.ReferenceEquals(str1, str2);//ReferenceEquals方法比较两者是否同一个引用

Console.WriteLine(equal);//True (CLR 4.5)

```

CLR会默认留用程序集的元数据中描述的所有字面值字符串，所以可能出现上面示例1代码情况，因为str1和str2是引用了堆中同一个字符串对象。但这不是必然的，考虑到性能问题，C#编译器会指定某个特性标记让CLR不对元数据中的字符串进行留用，但CLR可能会忽视这个标记。所以除非是显示调用Intern方法，否则永远不要以“字符串已留用”为前提来写代码。
另外要注意，垃圾回收器不能释放内部哈希表引用的字符串，因为哈希表正在容纳对它们的引用。除非卸载AppDomain或进程终止，否则内部哈希表引用的String对象不能被释放。

下面再抛出3个例子：

```csharp
string str1 = "Hello World";
string str2 = "Hello" + " " + "World";

bool equal = string.ReferenceEquals(str1, str2);

Console.WriteLine(equal);//True (CLR 4.5)

```


示例2结果与示例1相同，在特定CLR版本(4.5)都为True，对于字符串字面值的拼接，实际上都是编译时可确定的，编译时str2会自动拼接成"Hello World"这样的一个完整字符串，并适用了字符串留用，所以str1和str2都是引用同一个String对象。

```csharp
//示例3
string str1 = "Hello World";
string str2 = string.Format("{0} {1}", "Hello", "World");

bool equal = string.ReferenceEquals(str1, str2);

Console.WriteLine(equal);//False (CLR 4.5)
```

示例3结果与上面两个示例不一样，因为str2并不是字符串字面值的直接拼接，是要在运行时才能确定的，不会作为字面值自动启用字符串留用，与str1引用的是不同且独立的String对象，所以结果为False。

```csharp
//示例4
string str1 = "Hello World";
string str2 = string.Intern(string.Format("{0} {1}", "Hello", "World"));

bool equal = string.ReferenceEquals(str1, str2);

Console.WriteLine(equal);//True (CLR 4.5)
```

示例4与示例3大致相同，唯一不同的是str2是调用了string.Intern，str1为字面值字符串"Hello World"，并适用了字符串留用，进入了内部哈希表，而str2调用了string.Intern在内部哈希表中取了"Hello World"字符串对象的引用，所以str1和str2是同一个对象。
相信通过以上例子，大家都对字符串留用有了一定的理解，最后再强调一遍，以上结果是基于CLR留用了程序集元数据中所有字面值字符串的情况的，除非是显示调用Intern方法，否则永远不要以“字符串已留用”为前提来写代码。

### 字符串池
编译源代码时，编译器必须处理每个字面值字符串，并在托管模块的元数据中嵌入。同一个字符串在源码中多次出现，把它们都嵌入元数据会使生成的文件无谓地增大。
为解决这个问题，编译器会只在模块的元数据中只将字面值字符串写入一次。引用该字符串的所有代码都被修改成引用元数据的同一个字符串。编译器将单个字符串的多个实例合并成一个实例，能显着减少模块的大小。
这并不是一项新技术，但仍然是提升字符串性能的有效方式之一，开发者应该注意到这个优化方式的存在。

### 字符串的构造
C#把String视为基元类型，也就是说，编译器允许在源代码中直接使用字面值字符串。编译器会将这些字符串放到模块的元数据中，并在运行时加载和引用它们。

```csharp
string str1 = new string("Hello World");//error
string str2 = "Hello World";//right
```

C#不允许直接使用new操作符从字面值来构造String对象，相反必须用简化的语法直接赋值字面值。
如果用反编译软件查看直接用字面值构造的String对象的的IL代码，会发现IL代码中并没有出现newobj指令，而是使用了特殊的ldstr(load string)指令，它使用从元数据获得的字面值字符串去构造String对象。这证明CLR实际上是用一中特殊的方式去构造字面值String对象。猜测若在留用了字面值字符串情况下，构建过程中会在字符串留用的内部哈希表中查找是否已存在相同的字符串，若有则返回该引用，若没有则创建，并返回地址。

### 使用StringBuilder高效构建字符串
由于String类型代表不可变字符串，所以FCL提供了System.Text.StringBuilder类型对字符串和字符进行高效动态处理，并返回处理好的String对象。
可将StringBuilder想像成创建String对象的特殊构造器。方法一般应获取String参数而非StringBuilder参数。
StringBuilder 对象包含一个字段，该字段引用了由Char结构构成的数组。可利用StringBuilder的各个成员来操纵该字符数组，高效率地缩短字符串或更改字符串中的字符。如果字符串变大，超过了事先分配的字符数组大小，StringBuilder会自动分配一个新的、更大的数组，复制字符，并开始使用新数组。前一个数组被垃圾回收。
用StringBuilder对象构造好字符串后，调用StringBuilder的ToString方法即可将StringBuilder的字符数组“转换"成String。这样会在堆上新建String对象，其中包含调用ToString时存在于StringBuilder中的字符串。之后可继续处理StringBuilder中的字符串。以后可再次调用ToString把它转换成另个String对象。