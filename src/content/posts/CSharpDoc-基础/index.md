---
title: CSharpDoc-基础
published: 2017-03-09
description: "CSharpDoc-基础"
tags: []
category: 编程语言
draft: false
---

CSharpDoc-基础

[TOC]



# 程序结构

## 概述

C#程序由一个或多个文件组成。每个文件均包含零个或多个命名空间。一个命名空间包含类、结构、接口、枚举、委托等类型或其他命名空间。

# 类型系统

## 概述

### 在变量声明中指定类型

### 内置类型

### 自定义类型

### 通用类型系统

对于 .NET 中的类型系统，请务必了解以下两个基本要点：

- 它支持继承原则。 类型可以派生自其他类型（称为*基类型*）。 派生类型继承（有一些限制）基类型的方法、属性和其他成员。 基类型可以继而从某种其他类型派生，在这种情况下，派生类型继承其继承层次结构中的两种基类型的成员。 所有类型（包括 [System.Int32](https://learn.microsoft.com/zh-cn/dotnet/api/system.int32) (C# keyword: `int`) 等内置数值类型）最终都派生自单个基类型，即 [System.Object](https://learn.microsoft.com/zh-cn/dotnet/api/system.object) (C# keyword: [`object`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/builtin-types/reference-types))。 这样的统一类型层次结构称为[通用类型系统](https://learn.microsoft.com/zh-cn/dotnet/standard/base-types/common-type-system) (CTS)。 若要详细了解 C# 中的继承，请参阅[继承](https://learn.microsoft.com/zh-cn/dotnet/csharp/fundamentals/object-oriented/inheritance)。
- CTS 中的每种类型被定义为值类型或引用类型。 这些类型包括 .NET 类库中的所有自定义类型以及你自己的用户定义类型。 使用 `struct` 关键字定义的类型是值类型；所有内置数值类型都是 `structs`。 使用 `class` 或 `record` 关键字定义的类型是引用类型。 引用类型和值类型遵循不同的编译时规则和运行时行为。

下图展示了 CTS 中值类型和引用类型之间的关系。

![屏幕截图显示了 CTS 值类型和引用类型。](https://learn.microsoft.com/zh-cn/dotnet/csharp/programming-guide/types/media/index/value-reference-types-common-type-system.png)



### 值类型

值类型派生自System.ValueType（派生自System.Object)。派生自System.VlaueType的类型在CLR中具有特殊行为。值类型变量直接包含其值。结构的内存在声明变量的任何上下文中进行内联分配。对于值类型变量，没有单独的堆分配或垃圾回收开销。

值类型分为两类：struct和enum。内置的数据类型是结构，它们具有可访问的字段和方法。

### 引用类型

定义为 `class`、`record`、[`delegate`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/builtin-types/reference-types)、数组或 [`interface`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/interface) 的类型是 [`reference type`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/reference-types)。在声明变量 [`reference type`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/reference-types) 时，它将包含值 [`null`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/null)，直到你将其分配给该类型的实例，或者使用 [`new`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/new-operator) 运算符创建一个。

创建对象时，会在托管堆上分配内存。变量只保留对对象位置的引用。对于托管堆上的类型，在分配内存和回收内存时都会产生开销。

所有数组都是引用类型，即使元素是值类型，也不例外。 数组隐式派生自 [System.Array](https://learn.microsoft.com/zh-cn/dotnet/api/system.array) 类。 

引用类型完全支持继承。 创建类时，可以从其他任何未定义为[密封](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/sealed)的接口或类继承。 其他类可以从你的类继承并替代虚拟方法。

### 泛型类型

可使用一个或多个类型参数声明的类型，用作实际类型（具体类型）的占位符 。 客户端代码在创建类型实例时提供具体类型。 这种类型称为泛型类型

### 隐式类型、匿名类型和可以为null的值类型

### 编译时类型和运行时类型

变量可以具有不同的编译时和运行时类型。 编译时类型是源代码中变量的声明或推断类型。 运行时类型是该变量所引用的实例的类型。 这两种类型通常是相同的，如以下示例中所示：

```csharp
string message = "This is a string of characters";
```

在其他情况下，编译时类型是不同的，如以下两个示例所示：

```csharp
object anotherMessage = "This is another string of characters";
IEnumerable<char> someCharacters = "abcdefghijklmnopqrstuvwxyz";
```

在上述两个示例中，运行时类型为 `string`。 编译时类型在第一行中为 `object`，在第二行中为 `IEnumerable<char>`。

## 命名空间

命名空间具有以下属性：

- 它们组织大型代码项目。
- 通过使用 `.` 运算符分隔它们。
- `using` 指令可免去为每个类指定命名空间的名称。
- `global` 命名空间是“根”命名空间：`global::System` 始终引用 .NET [System](https://learn.microsoft.com/zh-cn/dotnet/api/system) 命名空间。

## 类

### 引用类型

定义为class的类型是引用类型。创建对象时，在该托管堆上为该特定对象分足够的内存，并且该变量仅保存对所述对象位置的引用。对象使用的内存由CLR的自动内存管理功能（垃圾回收）回收。

### 声明类

### 创建对象

### 构造函数和初始化

创建类型的实例时，需要确保其字段和属性已初始化为有用的值。 可通过多种方式初始化值：

- 接受默认值
- 字段初始化表达式
- 构造函数参数
- 对象初始值设定项

每个 .NET 类型都有一个默认值。 通常，对于数字类型，该值为 0，对于所有引用类型，该值为 `null`。 如果默认值在应用中是合理的，则可以依赖于该默认值。

### 类继承

类声明包括基类时，它会继承基类除构造函数外的所有成员。

## 接口

接口包含非抽象 [`class`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/class) 或 [`struct`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/builtin-types/struct) 必须实现的一组相关功能的定义。 接口可以定义 `static` 方法，此类方法必须具有实现。 接口可为成员定义默认实现。 接口不能声明实例数据，如字段、自动实现的属性或类似属性的事件。

## 泛型类和方法

泛型类和泛型方法兼具可重用性、类型安全性和效率，这是非泛型类和非泛型方法无法实现的。

## 匿名类型

匿名类型提供了一种方便的方法，可用来将一组只读属性封装到单个对象中，而无需首先显式定义一个类型。 类型名由编译器生成，并且不能在源代码级使用。 每个属性的类型由编译器推断。

# 面向对象的编程

## 类、结构和记录

在 C# 中，某个类型（类、结构或记录）的定义的作用类似于蓝图，指定该类型可以进行哪些操作。 从本质上说，对象是按照此蓝图分配和配置的内存块。

### 封装

### 成员

### 可访问性

### 继承

类（而非结构）支持继承的概念。 派生自另一个类（称为基类）的类自动包含基类的所有公共、受保护和内部成员（其构造函数和终结器除外）。

### 接口

类、结构和记录可以实现多个接口。 从接口实现意味着类型实现接口中定义的所有方法。

### 泛型类型

### 静态类型

类（而非结构或记录）可以声明为`static`。 静态类只能包含静态成员，不能使用 `new` 关键字进行实例化。 在程序加载时，类的一个副本会加载到内存中，而其成员则可通过类名进行访问。 类、结构和记录可以包含静态成员。

### 嵌套类型

### 分部类型

### 对象初始值设定项

### 匿名类型

### 扩展方法

### 隐式类型的局部变量

### 记录

## 对象

**创建类型的实例**

类或结构定义的作用类似于蓝图，指定该类型可以进行哪些操作。 从本质上说，对象是按照此蓝图分配和配置的内存块。 程序可以创建同一个类的多个对象。 对象也称为实例，可以存储在命名变量中，也可以存储在数组或集合中。 使用这些变量来调用对象方法及访问对象公共属性的代码称为客户端代码。 在 C# 等面向对象的语言中，典型的程序由动态交互的多个对象组成。

### 结构实例与类实例

由于类是引用类型，因此类对象的变量引用该对象在托管堆上的地址。 如果将同一类型的第二个变量分配给第一个变量，则两个变量都引用该地址的对象。

由于结构是值类型，因此结构对象的变量具有整个对象的副本。 结构的实例也可使用 `new` 运算符来创建，但这不是必需的，

### 对象标识与值相等性

在比较两个对象是否相等时，首先必须明确是想知道两个变量是否表示内存中的同一对象，还是想知道这两个对象的一个或多个字段的值是否相等。 如果要对值进行比较，则必须考虑这两个对象是值类型（结构）的实例，还是引用类型（类、委托、数组）的实例。

- 若要确定两个类实例是否引用内存中的同一位置（这意味着它们具有相同的标识），可使用静态 [Object.Equals](https://learn.microsoft.com/zh-cn/dotnet/api/system.object.equals) 方法。 （[System.Object](https://learn.microsoft.com/zh-cn/dotnet/api/system.object) 是所有值类型和引用类型的隐式基类，其中包括用户定义的结构和类。）
- 若要确定两个结构实例中的实例字段是否具有相同的值，可使用 [ValueType.Equals](https://learn.microsoft.com/zh-cn/dotnet/api/system.valuetype.equals) 方法。 由于所有结构都隐式继承自 [System.ValueType](https://learn.microsoft.com/zh-cn/dotnet/api/system.valuetype)，因此可以直接在对象上调用该方法，如以下示例所示：

## 继承

**派生用于创建更具体的行为的类型**

继承（以及封装和多态性）是面向对象的编程的三个主要特征之一。 通过继承，可以创建新类，以便重用、扩展和修改在其他类中定义的行为。 其成员被继承的类称为“基类”，继承这些成员的类称为“派生类”。 派生类只能有一个直接基类。 但是，继承是可传递的。 如果 `ClassC` 派生自 `ClassB`，并且 `ClassB` 派生自 `ClassA`，则 `ClassC` 将继承在 `ClassB` 和 `ClassA` 中声明的成员。

```
结构不支持继承，但它们可以实现接口。
```

从概念上讲，派生类是基类的专门化。

### 抽象方法和虚方法

基类将方法声明为 [`virtual`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/virtual) 时，派生类可以使用其自己的实现[`override`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/override)该方法。 如果基类将成员声明为 [`abstract`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/abstract)，则必须在直接继承自该类的任何非抽象类中重写该方法。 如果派生类本身是抽象的，则它会继承抽象成员而不会实现它们。

### 抽象基类

如果要通过使用 [new](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/new-operator) 运算符来防止直接实例化，则可以将类声明为[抽象](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/abstract)。 只有当一个新类派生自该类时，才能使用抽象类。 抽象类可以包含一个或多个本身声明为抽象的方法签名。 这些签名指定参数和返回值，但没有任何实现（方法体）。 抽象类不必包含抽象成员；但是，如果类包含抽象成员，则类本身必须声明为抽象。 本身不抽象的派生类必须为来自抽象基类的任何抽象方法提供实现。

### 接口

接口是定义一组成员的引用类型。 实现该接口的所有类和结构都必须实现这组成员。 接口可以为其中任何成员或全部成员定义默认实现。 类可以实现多个接口，即使它只能派生自单个直接基类。

### 防止进一步派生

类可以通过将自己或成员声明为 [`sealed`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/sealed)，来防止其他类继承自它或继承自其任何成员。

### 基类成员的派生类隐藏

派生类可以通过使用相同名称和签名声明成员来隐藏基类成员。 [`new`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/new-modifier) 修饰符可以用于显式指示成员不应作为基类成员的重写。 使用 [`new`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/new-modifier) 不是必需的，但如果未使用 [`new`](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/new-modifier)，则会产生编译器警告。

## 多态性

多态性具有两个截然不同的方面：

- 在运行时，在方法参数和集合或数组等位置，派生类的对象可以作为基类的对象处理。 在出现此多形性时，该对象的声明类型不再与运行时类型相同。
- 基类可以定义并实现[虚](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/virtual)方法，派生类可以[重写](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/override)这些方法，即派生类提供自己的定义和实现。 在运行时，客户端代码调用该方法，CLR 查找对象的运行时类型，并调用虚方法的重写方法。 你可以在源代码中调用基类的方法，执行该方法的派生类版本。

**虚方法允许你以统一方式处理多组相关的对象。** 例如，假定你有一个绘图应用程序，允许用户在绘图图面上创建各种形状。 你在编译时不知道用户将创建哪些特定类型的形状。 但应用程序必须跟踪创建的所有类型的形状，并且必须更新这些形状以响应用户鼠标操作。 你可以使用多态性通过两个基本步骤解决这一问题：

1. 创建一个类层次结构，其中每个特定形状类均派生自一个公共基类。
2. 使用虚方法通过对基类方法的单个调用来调用任何派生类上的相应方法。

首先，创建一个名为 `Rectangle``Shape` 的基类，并创建一些派生类，例如 `Triangle``Circle`、 和 。 为 `Shape` 类提供一个名为 `Draw` 的虚拟方法，并在每个派生类中重写该方法以绘制该类表示的特定形状。 创建 `List<Shape>` 对象，并向其添加 `Circle`、`Triangle` 和 `Rectangle`。

```csharp
public class Shape
{
    // A few example members
    public int X { get; private set; }
    public int Y { get; private set; }
    public int Height { get; set; }
    public int Width { get; set; }

    // Virtual method
    public virtual void Draw()
    {
        Console.WriteLine("Performing base class drawing tasks");
    }
}

public class Circle : Shape
{
    public override void Draw()
    {
        // Code to draw a circle...
        Console.WriteLine("Drawing a circle");
        base.Draw();
    }
}
public class Rectangle : Shape
{
    public override void Draw()
    {
        // Code to draw a rectangle...
        Console.WriteLine("Drawing a rectangle");
        base.Draw();
    }
}
public class Triangle : Shape
{
    public override void Draw()
    {
        // Code to draw a triangle...
        Console.WriteLine("Drawing a triangle");
        base.Draw();
    }
}
```

若要更新绘图图面，请使用 [foreach](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/statements/iteration-statements#the-foreach-statement) 循环对该列表进行循环访问，并对其中的每个 `Shape` 对象调用 `Draw` 方法。 虽然列表中的每个对象都具有声明类型 `Shape`，但调用的将是运行时类型（该方法在每个派生类中的重写版本）。

```csharp
// Polymorphism at work #1: a Rectangle, Triangle and Circle
// can all be used wherever a Shape is expected. No cast is
// required because an implicit conversion exists from a derived
// class to its base class.
var shapes = new List<Shape>
{
    new Rectangle(),
    new Triangle(),
    new Circle()
};

// Polymorphism at work #2: the virtual method Draw is
// invoked on each of the derived classes, not the base class.
foreach (var shape in shapes)
{
    shape.Draw();
}
/* Output:
    Drawing a rectangle
    Performing base class drawing tasks
    Drawing a triangle
    Performing base class drawing tasks
    Drawing a circle
    Performing base class drawing tasks
*/
```

在 C# 中，每个类型都是多态的，因为包括用户定义类型在内的所有类型都继承自 [Object](https://learn.microsoft.com/zh-cn/dotnet/api/system.object)。

### 虚拟成员

仅当基类成员声明为 [virtual](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/virtual) 或 [abstract](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/abstract) 时，派生类才能重写基类成员。 派生成员必须使用 [override](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/override) 关键字显式指示该方法将参与虚调用。

### 使用新成员隐藏基类成员

如果希望派生类具有与基类中的成员同名的成员，则可以使用 [new](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/new-modifier) 关键字隐藏基类成员。 `new` 关键字放置在要替换的类成员的返回类型之前。 

### 从派生类访问基类虚拟成员

已替换或重写某个方法或属性的派生类仍然可以使用 `base` 关键字访问基类的该方法或属性。

```
建议虚拟成员在它们自己的实现中使用 base 来调用该成员的基类实现。 允许基类行为发生使得派生类能够集中精力实现特定于派生类的行为。 未调用基类实现时，由派生类负责使它们的行为与基类的行为兼容。
```

# 功能技术

## 模式匹配

### Null检查

模式匹配最常见的方案之一是确保值不是 `null`。 使用以下示例进行 `null` 测试时，可以测试可为 null 的值类型并将其转换为其基础类型：

```csharp
int? maybe = 12;

if (maybe is int number)
{
    Console.WriteLine($"The nullable int 'maybe' has the value {number}");
}
else
{
    Console.WriteLine("The nullable int 'maybe' doesn't hold a value");
}
```

上述代码是[声明模式](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/patterns#declaration-and-type-patterns)，用于测试变量类型并将其分配给新变量。 语言规则使此方法比其他方法更安全。 变量 `number` 仅在 `if` 子句的 true 部分可供访问和分配。 如果尝试在 `else` 子句或 `if` 程序块后等其他位置访问，编译器将出错。 其次，由于不使用 `==` 运算符，因此当类型重载 `==` 运算符时，此模式有效。 **这使该方法成为检查空引用值的理想方法**，可以添加 `not` 模式：

```csharp
string? message = "This is not the null string";

if (message is not null)
{
    Console.WriteLine(message);
}
```

前面的示例使用[常数模式](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/patterns#constant-pattern)将变量与 `null` 进行比较。 `not` 为一种[逻辑模式](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/patterns#logical-patterns)，在否定模式不匹配时与该模式匹配。

### 类型测试

模式匹配的另一种常见用途是测试变量是否与给定类型匹配。 例如，以下代码测试变量是否为非 null 并实现 [System.Collections.Generic.IList](https://learn.microsoft.com/zh-cn/dotnet/api/system.collections.generic.ilist-1) 接口。 如果是，它将使用该列表中的 [ICollection.Count](https://learn.microsoft.com/zh-cn/dotnet/api/system.collections.generic.icollection-1.count#system-collections-generic-icollection-1-count) 属性来查找中间索引。 不管变量的编译时类型如何，声明模式均与 `null` 值不匹配。 除了防范未实现 `IList` 的类型之外，以下代码还可防范 `null`。

```csharp
public static T MidPoint<T>(IEnumerable<T> sequence)
{
    if (sequence is IList<T> list)
    {
        return list[list.Count / 2];
    }
    else if (sequence is null)
    {
        throw new ArgumentNullException(nameof(sequence), "Sequence can't be null.");
    }
    else
    {
        int halfLength = sequence.Count() / 2 - 1;
        if (halfLength < 0) halfLength = 0;
        return sequence.Skip(halfLength).First();
    }
}
```

可在 `switch` 表达式中应用相同测试，用以测试多种不同类型的变量。 你可以根据特定运行时类型使用这些信息创建更好的算法。

### 比较离散值

### 关系模式

### 多个输入

### 列表模式

## 弃元

弃元是一种在应用程序代码中人为取消使用的占位符变量。 弃元相当于未赋值的变量；它们没有值。

### 元组和对象析构

### 利用switch的模式匹配

### 对具有out参数的方法的调用

### 独立弃元

# 异常与错误

## 概述

C# 语言的异常处理功能有助于处理在程序运行期间发生的任何意外或异常情况。 异常处理功能使用 `try`、`catch` 和 `finally` 关键字来尝试执行可能失败的操作、在你确定合理的情况下处理故障，以及在事后清除资源。 公共语言运行时 (CLR)、.NET/第三方库或应用程序代码都可生成异常。 异常是使用 `throw` 关键字创建而成。

## 使用异常

## 异常处理

## 创建和引发异常

异常用于指示在运行程序时发生了错误。 此时将创建一个描述错误的异常对象，然后使用 [`throw` 语句或表达式](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/statements/exception-handling-statements#the-throw-statement)*引发*。

### 引发异常时应避免的情况

### 任务返回方法中的异常

### 定义异常的类别

## 编译器生成的异常

当基本操作失败时，.NET 运行时会自动引发一些异常。 这些异常及其错误条件在下表中列出。

| 例外                                                         | 描述                                                         |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| [ArithmeticException](https://learn.microsoft.com/zh-cn/dotnet/api/system.arithmeticexception) | 算术运算期间出现的异常的基类，例如 [DivideByZeroException](https://learn.microsoft.com/zh-cn/dotnet/api/system.dividebyzeroexception) 和 [OverflowException](https://learn.microsoft.com/zh-cn/dotnet/api/system.overflowexception)。 |
| [ArrayTypeMismatchException](https://learn.microsoft.com/zh-cn/dotnet/api/system.arraytypemismatchexception) | 由于元素的实际类型与数组的实际类型不兼容而导致数组无法存储给定元素时引发。 |
| [DivideByZeroException](https://learn.microsoft.com/zh-cn/dotnet/api/system.dividebyzeroexception) | 尝试将整数值除以零时引发。                                   |
| [IndexOutOfRangeException](https://learn.microsoft.com/zh-cn/dotnet/api/system.indexoutofrangeexception) | 索引小于零或超出数组边界时，尝试对数组编制索引时引发。       |
| [InvalidCastException](https://learn.microsoft.com/zh-cn/dotnet/api/system.invalidcastexception) | 从基类型显式转换为接口或派生类型在运行时失败时引发。         |
| [NullReferenceException](https://learn.microsoft.com/zh-cn/dotnet/api/system.nullreferenceexception) | 尝试引用值为 [null](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/keywords/null) 的对象时引发。 |
| [OutOfMemoryException](https://learn.microsoft.com/zh-cn/dotnet/api/system.outofmemoryexception) | 尝试使用[新](https://learn.microsoft.com/zh-cn/dotnet/csharp/language-reference/operators/new-operator)运算符分配内存失败时引发。 此异常表示可用于公共语言运行时的内存已用尽。 |
| [OverflowException](https://learn.microsoft.com/zh-cn/dotnet/api/system.overflowexception) | `checked` 上下文中的算术运算溢出时引发。                     |
| [StackOverflowException](https://learn.microsoft.com/zh-cn/dotnet/api/system.stackoverflowexception) | 执行堆栈由于有过多挂起的方法调用而用尽时引发；通常表示非常深的递归或无限递归。 |
| [TypeInitializationException](https://learn.microsoft.com/zh-cn/dotnet/api/system.typeinitializationexception) | 静态构造函数引发异常并且没有兼容的 `catch` 子句来捕获异常时引发。 |

# 编码样式

## C#标识符命名规则和约定

### 命名规则

### 命名约定

## C# 编码约定