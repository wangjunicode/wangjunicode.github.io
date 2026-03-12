---
title: 关于uLua-性能优化
published: 2019-06-04
description: "从最早的lua纯反射调用c#，以及云风团队尝试的纯c#实现的lua虚拟机，一直发展到现在的各种luajit+c#静态lua导出方案，lua+unity才算达到了"
tags: []
category: 编程语言
draft: false
---

从最早的lua纯反射调用c#，以及云风团队尝试的纯c#实现的lua虚拟机，一直发展到现在的各种luajit+c#静态lua导出方案，lua+unity才算达到了性能上实用的级别。

既然是lua+unity，那性能好不好，基本上要看两大点：lua跟c#交互时的性能如何；纯lua代码本身的性能如何

简单举例

从致命的gameobj.transform.position = pos开始说起

这个过程交互非常复杂，需要优化

在C# 写一个Util类比如，SetPos(), 这lua侧调用，传参就简单的x,y,z这些




---

### **lua与c#交互篇**

### **1.从致命的gameobj.transform.position = pos开始说起**

像gameobj.transform.position = pos这样的写法，在unity中是再常见不过的事情

但是在ulua中，大量使用这种写法是非常糟糕的。为什么呢？

因为短短一行代码，却发生了非常非常多的事情，为了更直观一点，我们把这行代码调用过的关键luaapi以及ulua相关的关键步骤列出来（以ulua+cstolua导出为准，gameobj是GameObject类型，pos是Vector3）：
**第一步：**
GameObjectWrap.get_transform lua想从gameobj拿到transform，对应gameobj.transform
LuaDLL.luanet_rawnetobj 把lua中的gameobj变成c#可以辨认的id
ObjectTranslator.TryGetValue 用这个id，从ObjectTranslator中获取c#的gameobject对象
gameobject.transform 准备这么多，这里终于真正执行c#获取gameobject.transform了
ObjectTranslator.AddObject 给transform分配一个id，这个id会在lua中用来代表这个transform，transform要保存到ObjectTranslator供未来查找
LuaDLL.luanet_newudata 在lua分配一个userdata，把id存进去，用来表示即将返回给lua的transform
LuaDLL.lua_setmetatable 给这个userdata附上metatable，让你可以transform.position这样使用它
LuaDLL.lua_pushvalue 返回transform，后面做些收尾
LuaDLL.lua_rawseti
LuaDLL.lua_remove
**第二步：**
TransformWrap.set_position lua想把pos设置到transform.position
LuaDLL.luanet_rawnetobj 把lua中的transform变成c#可以辨认的id
ObjectTranslator.TryGetValue 用这个id，从ObjectTranslator中获取c#的transform对象
LuaDLL.tolua_getfloat3 从lua中拿到Vector3的3个float值返回给c#
lua_getfield + lua_tonumber 3次 拿xyz的值，退栈
lua_pop
transform.position = new Vector3(x,y,z) 准备了这么多，终于执行transform.position = pos赋值了
就这么一行代码，竟然做了这么一大堆的事情！如果是c++，a.b.c = x这样经过优化后无非就是拿地址然后内存赋值的事。但是在这里，频繁的取值、入栈、c#到lua的类型转换，每一步都是满满的cpu时间，还不考虑中间产生了各种内存分配和后面的GC！
下面我们会逐步说明，其中有一些东西其实是不必要的，可以省略的。我们可以最终把他优化成：
lua_isnumber + lua_tonumber 4次，全部完成


**2.在lua中引用c#的object，代价昂贵**
从上面的例子可以看到，仅仅想从gameobj拿到一个transform，就已经有很昂贵的代价
c#的object，不能作为指针直接供c操作（其实可以通过GCHandle进行pinning来做到，不过性能如何未测试，而且被pinning的对象无法用gc管理），因此主流的lua+unity都是用一个id表示c#的对象，在c#中通过dictionary来对应id和object。同时因为有了这个dictionary的引用，也保证了c#的object在lua有引用的情况下不会被垃圾回收掉。
因此，每次参数中带有object，要从lua中的id表示转换回c#的object，就要做一次dictionary查找；每次调用一个object的成员方法，也要先找到这个object，也就要做dictionary查找。
如果之前这个对象在lua中有用过而且没被gc，那还就是查下dictionary的事情。但如果发现是一个新的在lua中没用过的对象，那就是上面例子中那一大串的准备工作了。
如果你返回的对象只是临时在lua中用一下，情况更糟糕！刚分配的userdata和dictionary索引可能会因为lua的引用被gc而删除掉，然后下次你用到这个对象又得再次做各种准备工作，导致反复的分配和gc，性能很差。
例子中的gameobj.transform就是一个巨大的陷阱，因为.transform只是临时返回一下，但是你后面根本没引用，又会很快被lua释放掉，导致你后面每次.transform一次，都可能意味着一次分配和gc。


**3.在lua和c#间传递unity独有的值类型（Vector3/Quaternion等）更加昂贵**
既然前面说了lua调用c#对象缓慢，如果每次vector3.x都要经过c#，那性能基本上就处于崩溃了，所以主流的方案都将Vector3等类型实现为纯lua代码，Vector3就是一个{x,y,z}的table，这样在lua中使用就快了。
但是这样做之后，c#和lua中对Vector3的表示就完全是两个东西了，所以传参就涉及到lua类型和c#类型的转换，例如c#将Vector3传给lua，整个流程如下：
1.c#中拿到Vector3的x,y,z三个值
2.push这3个float给lua栈
3.然后构造一个表，将表的x,y,z赋值
4.将这个表push到返回值里
一个简单的传参就要完成3次push参数、表内存分配、3次表插入，性能可想而知。
那么如何优化呢？我们的测试表明，直接在函数中传递三个float，要比传递Vector3要更快。
例如void SetPos(GameObject obj, Vector3 pos)改为void SetPos(GameObject obj, float x, float y, float z)
具体效果可以看后面的测试数据，提升十分明显。



### **4.lua和c#之间传参、返回时，尽可能不要传递以下类型：**

严重类： Vector3/Quaternion等unity值类型，数组

次严重类：bool string 各种object

建议传递：int float double

虽然是lua和c#的传参，但是从传参这个角度讲，lua和c#中间其实还夹着一层c（毕竟lua本身也是c实现的），lua、c、c#由于在很多数据类型的表示以及内存分配策略都不同，因此这些数据在三者间传递，往往需要进行转换（术语parameter mashalling），这个转换消耗根据不同的类型会有很大的不同。

先说次严重类中的bool string类型，涉及到c和c#的交互性能消耗，根据微软官方文档，在数据类型的处理上，c#定义了Blittable Types和Non-Blittable Types，其中bool和string属于Non-Blittable Types，意思是他们在c和c#中的内存表示不一样，意味着从c传递到c#时需要进行类型转换，降低性能，而string还要考虑内存分配（将string的内存复制到托管堆，以及utf8和utf16互转）。

可以参考[https://msdn.microsoft.com/zh-cn/library/ms998551.aspx](https://link.zhihu.com/?target=https%3A//msdn.microsoft.com/zh-cn/library/ms998551.aspx)，这里有更详细的关于c和c#交互的性能优化指引。

而严重类，基本上是ulua等方案在尝试lua对象与c#对象对应时的瓶颈所致。

Vector3等值类型的消耗，前面已经有所提及。

而数组则更甚，因为lua中的数组只能以table表示，这和c#下完全是两码事，没有直接的对应关系，因此从c#的数组转换为lua table只能逐个复制，如果涉及object/string等，更是要逐个转换。

### **5.频繁调用的函数，参数的数量要控制**

无论是lua的pushint/checkint，还是c到c#的参数传递，参数转换都是最主要的消耗，而且是逐个参数进行的，因此，lua调用c#的性能，除了跟参数类型相关外，也跟参数个数有很大关系。一般而言，频繁调用的函数不要超过4个参数，而动辄十几个参数的函数如果频繁调用，你会看到很明显的性能下降，手机上可能一帧调用数百次就可以看到10ms级别的时间。

### **6.优先使用static函数导出，减少使用成员方法导出**

前面提到，一个object要访问成员方法或者成员变量，都需要查找lua userdata和c#对象的引用，或者查找metatable，耗时甚多。直接导出static函数，可以减少这样的消耗。

像obj.transform.position = pos。

我们建议的方法是，写成静态导出函数，类似

class LuaUtil{

static void SetPos(GameObject obj, float x, float y, float z){obj.transform.position = new Vector3(x, y, z); }

}

然后在lua中LuaUtil.SetPos(obj, pos.x, pos.y, pos.z)，这样的性能会好非常多，因为省掉了transform的频繁返回，而且还避免了transform经常临时返回引起lua的gc。

**7.注意lua拿着c#对象的引用时会造成c#对象无法释放，这是内存泄漏常见的起因**
前面说到，c# object返回给lua，是通过dictionary将lua的userdata和c# object关联起来，只要lua中的userdata没回收，c# object也就会被这个dictionary拿着引用，导致无法回收。
最常见的就是gameobject和component，如果lua里头引用了他们，即使你进行了Destroy，也会发现他们还残留在mono堆里。
不过，因为这个dictionary是lua跟c#的唯一关联，所以要发现这个问题也并不难，遍历一下这个dictionary就很容易发现。ulua下这个dictionary在ObjectTranslator类、slua则在ObjectCache类

### **8.考虑在lua中只使用自己管理的id，而不直接引用c#的object**

想避免lua引用c# object带来的各种性能问题的其中一个方法就是自己分配id去索引object，同时相关c#导出函数不再传递object做参数，而是传递int。

这带来几个好处：

1.函数调用的性能更好；

2.明确地管理这些object的生命周期，避免让ulua自动管理这些对象的引用，如果在lua中错误地引用了这些对象会导致对象无法释放，从而内存泄露

3.c#object返回到lua中，如果lua没有引用，又会很容易马上gc，并且删除ObjectTranslator对object的引用。自行管理这个引用关系，就不会频繁发生这样的gc行为和分配行为。

例如，上面的LuaUtil.SetPos(GameObject obj, float x, float y, float z)可以进一步优化为LuaUtil.SetPos(int objID, float x, float y, float z)。然后我们在自己的代码里头记录objID跟GameObject的对应关系，如果可以，用数组来记录而不是dictionary，则会有更快的查找效率。如此下来可以进一步省掉lua调用c#的时间，并且对象的管理也会更高效。

### **9.合理利用out关键字返回复杂的返回值**

在c#向lua返回各种类型的东西跟传参类似，也是有各种消耗的。

比如

Vector3 GetPos(GameObject obj)

可以写成

void GetPos(GameObject obj, out float x, out float y, out float z)

表面上参数个数增多了，但是根据生成出来的导出代码（我们以ulua为准），会从：

LuaDLL.tolua_getfloat3（内含get_field + tonumber 3次）

变成

isnumber + tonumber 3次

get_field本质上是表查找，肯定比isnumber访问栈更慢，因此这样做会有更好的性能。

### **实测**

好了，说了这么多，不拿点数据来看还是太晦涩

为了更真实地看到纯语言本身的消耗，我们直接没有使用例子中的gameobj.transform.position，因为这里头有一部分时间是浪费在unity内部的。

我们重写了一个简化版的GameObject2和Transform2。

class Transform2{

public Vector3 position = new Vector3();

}

class GameObject2{

public Transform2 transform = new Transform2();

}

然后我们用几个不同的调用方式来设置transform的position

方式1：gameobject.transform.position = Vector3.New(1,2,3)

方式2：gameobject:SetPos(Vector3.New(1,2,3))

方式3：gameobject:SetPos2(1,2,3)

方式4：GOUtil.SetPos(gameobject, Vector3.New(1,2,3))

方式5：GOUtil.SetPos2(gameobjectid, Vector3.New(1,2,3))

方式6：GOUtil.SetPos3(gameobjectid, 1,2,3)

分别进行1000000次，结果如下（测试环境是windows版本，cpu是i7-4770，luajit的jit模式关闭，手机上会因为luajit架构、il2cpp等因素干扰有所不同，但这点我们会在下一篇进一步阐述）：

![image-20230910201710315](关于uLua-性能优化/image-20230910201710315.png)



方式1：903ms

方式2：539ms

方式3：343ms

方式4：559ms

方式5：470ms

方式6：304ms

可以看到，每一步优化，都是提升明显的，尤其是移除.transform获取以及Vector3转换提升更是巨大，我们仅仅只是改变了对外导出的方式，并不需要付出很高成本，就已经可以节省66%的时间。

实际上能不能再进一步呢？还能！在方式6的基础上，我们可以再做到只有200ms！

这里卖个关子，下一篇luajit集成中我们进一步讲解。一般来说，我们推荐做到方式6的水平已经足够。

这只是一个最简单的案例，有很多各种各样的常用导出（例如GetComponentsInChildren这种性能大坑，或者一个函数传递十几个参数的情况）都需要大家根据自己使用的情况来进行优化，有了我们提供的lua集成方案背后的性能原理分析，应该就很容易去考虑怎么做了。

下一篇将会写lua+unity性能优化的第二部分，luajit集成的性能坑

相比起第一部分这种看导出代码就能大概知道性能消耗的问题，luajit集成的问题要复杂晦涩得多。

附测试用例的c#代码：

```csharp
public class Transform2
{
    public Vector3 position = new Vector3();
}

public class GameObject2
{
    public Transform2 transform = new Transform2();
    public void SetPos(Vector3 pos)
    {
        transform.position = pos;
    }

    public void SetPos2(float x, float y, float z)
    {
        transform.position.x = x;
        transform.position.y = y;
        transform.position.z = z;
    }
}

 
public class GOUtil
{
    private static List<GameObject2> mObjs = new List<GameObject2>();
    public static GameObject2 GetByID(int id)
    {
        if(mObjs.Count == 0)
        {
            for (int i = 0; i < 1000; i++ )
            {
                mObjs.Add(new GameObject2());
            }
        }

        return mObjs[id];
    }

    public static void SetPos(GameObject2 go, Vector3 pos)
    {
        go.transform.position = pos;
    }

    public static void SetPos2(int id, Vector3 pos)
    {
        mObjs[id].transform.position = pos;
    }

    public static void SetPos3(int id, float x, float y ,float z)
    {
        var t = mObjs[id].transform;
        t.position.x = x;
        t.position.y = y;
        t.position.z = z;
    }
}
```



### luajit集成篇

大家都知道luajit比原生lua快，快在jit这三个字上。

但实际情况是，luajit的行为十分复杂。尤其jit并不是一个简单的把代码翻译成机器码的机制，背后有很多会影响性能的因素存在。

1.luajit分为jit模式和interpreter模式，先要弄清楚你到底在哪种模式下

同样的代码，在pc下可能以不足1ms的速度完成，而到了ios却需要几十ms，是因为pc的cpu更好？是，但要知道顶级ios设备的cpu单核性能已经是pc级，几十甚至百倍的差距显然不在这里。

这里要了解luajit的两种运行模式：jit、interpreter

jit模式：这是luajit高效所在，简单地说就是直接将代码编译成机器码级别执行，效率大大提升（事实上这个机制没有说的那么简单，下面会提到）。然而不幸的是这个模式在ios下是无法开启的，因为ios为了安全，从系统设计上禁止了用户进程自行申请有执行权限的内存空间，因此你没有办法在运行时编译出一段代码到内存然后执行，所以jit模式在ios以及其他有权限管制的平台（例如ps4，xbox）都不能使用。

interpreter模式：那么没有jit的时候怎么办呢？还有一个interpreter模式。事实上这个模式跟原生lua的原理是一样的，就是并不直接编译成机器码，而是编译成中间态的字节码（bytecode），然后每执行下一条字节码指令，都相当于swtich到一个对应的function中执行，相比之下当然比jit慢。但好处是这个模式不需要运行时生成可执行机器码（字节码是不需要申请可执行内存空间的），所以任何平台任何时候都能用，跟原生lua一样。这个模式可以运行在任何luajit已经支持的平台，而且你可以手动关闭jit，强制运行在interpreter模式下。

我们经常说的将lua编译成bytecode可以防止破解，这个bytecode是interpreter模式的bytecode，并不是jit编译出的机器码（事实上还有一个在bytecode向机器码转换过程中的中间码SSA IR，有兴趣可以看luajit官方wiki），比较坑的是可供32位版本和64位版本执行的bytecode还不一样，这样才有了著名的2.0.x版本在ios加密不能的坑。

2.jit模式一定更快？不一定！

ios不能用jit，那么安卓下应该就可以飞起来用了吧？用脚本语言获得飞一般的性能，让我大红米也能对杠iphone！

你开心的太早了。

并不是安卓不能开启jit，而是jit的行为极其复杂，对平台高度依赖，导致它在以arm为主的安卓平台下，未必能发挥出在pc上的威力，要知道luajit最初只是考虑pc平台的。

首先我们要知道，jit到底怎么运作的。

luajit使用了一个很特殊的机制（也是其大坑），叫做trace compiler的方式，来将代码进行jit编译的。

什么意思呢？它不是简单的像c++编译器那样直接把整套代码翻译成机器码就完事了，因为这么做有两个问题：1.编译时间长，这点比较好理解；2.更关键的是，作为动态语言，难以优化，例如对于一个function foo(a)，这个a到底是什么类型，并不知道，对这个a的任何操作，都要检查类型，然后根据类型做相应处理，哪怕就是一个简单的a+b都必须这样（a和b完全有可能是两个表，实现的__add元方法），实际上跟interpreter模式就没什么区别了，根本起不到高效运行的作用；3.很多动态类型无法提前知道类型信息，也就很难做链接（知道某个function的地址、知道某个成员变量的地址）

那怎么办呢？这个解决方案可以另写一篇文章了。这里只是简单说一下luajit采用的trace compiler方案：首先所有的lua都会被编译成bytecode，在interpreter模式下执行，当interpreter发现某段代码经常被执行，比如for循环代码（是的，大部分性能瓶颈其实都跟循环有关），那么luajit会开启一个记录模式，记录这段代码实际运行每一步的细节（比如里头的变量是什么类型，猜测是数值还是table）。有了这些信息，luajit就可以做优化了：如果a+b发现就是两个数字相加，那就可以优化成数值相加；如果[http://a.xxx](https://link.zhihu.com/?target=http%3A//a.xxx)就是访问a下面某个固定的字段，那就可以优化成固定的内存访问，不用再走表查询。最后就可以将这段经常执行的代码jit化。

这里可以看到，第一，interpreter模式是必须的，无论平台是否允许jit，都必须先使用interpreter执行；第二，并非所有代码都会jit执行，仅仅是部分代码会这样，并且是运行过程中决定的。

3.要在安卓下发挥jit的威力，必须要解决掉jit模式下的坑：jit失败

那么说了jit怎么运作的，看起来没什么问题呀，为何说不一定更快呢？

这里就有另一个大坑：luajit无法保证所有代码都可以jit化，并且这点只能在尝试编译的过程中才知道。

听起来好像没什么概念。事实上，这种情况的出现，有时是毁灭性的，可以让你的运行速度下降百倍。

对，你没看错，是百倍，几ms的代码突然飙到几百ms。

具体的感受，可以看看uwa那篇《Unity项目常见Lua解决方案性能比较》中S3的测试数据，一个纯lua代码的用例（Vector3.Normalize没有经过c#），却出现了巨大的性能差异。

而jit失败的原因非常多，而当你理解背后的原理后会知道，在安卓下jit失败的可能要比pc上高得多。

根据我们在安卓下的使用来看，最常见的有以下几种，并且后面写上了应对方案。

3.1可供代码执行的内存空间被耗尽->要么放弃jit，要么修改luajit的代码

要jit，就要编译出机器码，放到特定的内存空间。但是arm有一个限制，就是跳转指令只能跳转前后32MB的空间，这导致了一个巨大的问题：luajit生成的代码要保证在一个连续的64MB空间内，如果这个空间被其他东西占用了，luajit就会分配不出用于jit的内存，而目前luajit会疯狂重复尝试编译，最后导致性能处于瘫痪的状态。

虽然网上有一些不修改luajit的方案（[http://www.freelists.org/post/luajit/Performance-degraded-significantly-when-enabling-JIT,9](https://link.zhihu.com/?target=http%3A//www.freelists.org/post/luajit/Performance-degraded-significantly-when-enabling-JIT%2C9)），在lua中调用luajit的jit.opt的api尝试将内存空间分配给luajit，但根据我们的测试，在unity上这样做仍然无法保证所有机器上能够不出问题，因为这些方案的原理要抢在这些内存空间被用于其他用途前全部先分配给luajit，但是ulua可以运行的时候已经是程序初始化非常后期的阶段，这个时候众多的unity初始化流程可能早已耗光了这块内存空间。相反cocos2dx这个问题并不多见，因为luajit运行早，有很大的机会提前抢占内存空间。

无论从代码看还是根据我们的测试以及luajit maillist的反馈来看，这个问题早在2.0.x就存在，更换2.1.0依然无法解决，我们建议，如果项目想要使用jit模式，需要在android工程的Activity入口中就加载luajit，做好内存分配，然后将这个luasate传递给unity使用。如果不愿意趟这个麻烦，那可以根据项目实际测试的情况，考虑禁用jit模式（见文章第9点）。一般来说，lua代码越少，遇到这个问题的可能性越低。

3.2寄存器分配失败->减少local变量、避免过深的调用层次

很不幸的一点是，arm中可用的寄存器比x86少。luajit为了速度，会尽可能用寄存器存储local变量，但是如果local变量太多，寄存器不够用，目前jit的做法是：放弃治疗（有兴趣可以看看源码中asm_head_side函数的注释）。因此，我们能做的，只有按照官方优化指引说的，避免过多的local变量，或者通过do end来限制local变量的生命周期。

3.3调用c函数的代码无法jit->使用ffi，或者使用2.1.0beta2

这里要提醒一点，调用c#，本质也是调用c，所以只要调用c#导出，都是一样的。而这些代码是无法jit化的，但是luajit有一个利器，叫ffi，使用了ffi导出的c函数在调用的时候是可以jit化的。

另外，2.1.0beta2开始正式引入了trace stitch，可以将调用c的lua代码独立起来，将其他可以jit的代码jit掉，不过根据作者的说法，这个优化效果依然有限。

3.4jit遇到不支持的字节码->少用for in pairs，少用字符串连接

有非常多bytecode或者内部库调用是无法jit化的，最典型就是for in pairs，以及字符串连接符（2.1.0开始支持jit）。

具体可以看[http://wiki.luajit.org/NYI](https://link.zhihu.com/?target=http%3A//wiki.luajit.org/NYI)，只要不是标记yes或者2.1的代码，就不要过多使用。

4.怎么知道自己的代码有没有jit失败？使用v.lua

完整的luajit的exe版本都会带一个jit目录，下面有大量luajit的工具，其中有一个v.lua，这是luajit verbose mode（另外还有一个很重要的叫p.lua，luajit profiler，后面会提到），可以追踪luajit运行过程中的一些细节，其中就可以帮你追踪jit失败的情况。

local verbo = require("jit.v")

verbo.start()

当你看到以下错误的时候，说明你遇到了jit失败

failed to allocate mcode memory，对应错误3.1

NYI: register coalescing too complex，对应错误3.2

NYI: C function，对应错误3.3（这个错误在2.1.0beta2中已经移除，因为有trace stitch）

NYI: bytecode，对应错误3.4

这在luajit.exe下使用会很正常，但要在unity下用上需要修改v.lua的代码，把所有out:write输出导向到Debug.Log里头。

5.照着luajit的偏好来写lua代码

最后，趟完luajit本身的深坑，还有一些相对轻松的坑，也就是你如何在写lua的时候，根据luajit的特性，按照其喜好的方式来写，获得更好的性能

这里可以看我们的另一篇文章《luajit官方性能优化指南和注解》，里头比较详细的说明如何写出适合luajit的lua代码。

6.如果可以，用传统的local function而非class的方式来写代码

由于cocos2dx时代的推广，目前主流的lua面向对象实现（例如cocos2dx以及ulua的simpleframework集成的）都依赖metatable来调用成员函数，深入读过luajit后就会知道，在interpreter模式下，查找metatable会产生多一次表查找，而且self:Func()这种写法的性能也远不如先cache再调用的写法：local f = Class.Func; f(self)，因为local cache可以省去表查找的流程，根据我们的测试，interpreter模式下，结合local cache和移除metatable流程，可以有2~3倍的性能差。

而luajit官方也建议尽可能只调用local function，省去全局查找的时间。

比较典型的就是Vector3的主流lua实现都是基于metatable做的，虽然代码更优雅，更接近面向对象的风格（va:Add(vb)对比Vector3.Add(va, vb)）但是性能会差一些

当然，这点可以根据项目的实际情况来定，不必强求，毕竟要在代码可读性和性能间权衡。我们建议在高频使用的对象中（例如Vector3）使用function风格的写法，而主要的代码可以继续保持class风格的写法。

7.不要过度使用c#回调lua，这非常慢

目前luajit官方文档（ffi的文档）中建议优先进行lua调用c，而尽可能避免c回调lua。当然常用的ui回调因为频次不高所以一般可以放心使用，但是如果是每帧触发的逻辑，那么直接在lua中完成，比反复从lua->c->lua的调用要更快。这里有一篇blog分析，可以参考：

[http://www.cppblog.com/tdzl2003/archive/2013/02/24/198045.html](https://link.zhihu.com/?target=http%3A//www.cppblog.com/tdzl2003/archive/2013/02/24/198045.html)

8.借助ffi，进一步提升luajit与c/c#交互的性能

ffi是luajit独有的一个神器，用于进行高效的luajit与c交互。其原理是向luajit提供c代码的原型声明，这样luajit就可以直接生成机器码级别的优化代码来与c交互，不再需要传统的lua api来做交互。

我们进行过简单的测试，利用ffi的交互效率可以有数倍甚至10倍级别的提升（当然具体要视乎参数列表而定），真可谓飞翔的速度。

而借助ffi也是可以提高luajit与c#交互的性能。原理是利用ffi调用自己定义的c函数，再从c函数调用c#，从而优化掉luajit到c这一层的性能消耗，而主要留下c到c#的交互消耗。在上一篇中我们提到的300ms优化到200ms，就是利用这个技巧达到的。

必须要注意的是，ffi只有在jit开启下才能发挥其性能，如果是在ios下，ffi反而会拖慢性能。所以使用的时候必须要做好快关。

首先，我们在c中定义一个方法，用于将c#的函数注册到c中，以便在c中可以直接调用c#的函数，这样只要luajit可以ffi调用c，也就自然可以调用c#的函数了

```cpp
void gse_ffi_register_csharp(int id, void* func)
{
  s_reg_funcs[id] = func;
}
```

这里，id是一个你自由分配给c#函数的id，lua通过这个id来决定调用哪个函数。

然后在c#中将c#函数注册到c中

```csharp
[DllImport(LUADLL, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
public static extern void gse_ffi_register_csharp(int funcid, IntPtr func);
public static void gse_ffi_register_v_i1f3(int funcid, f_v_i1f3 func)
{
  gse_ffi_register_csharp(funcid, Marshal.GetFunctionPointerForDelegate(func));
}
```

gse_ffi_register_v_i1f3(1, GObjSetPositionAddTerrainHeight);//将GObjSetPositionAddTerrainHeight注册为id1的函数

然后lua中使用的时候，这么调用

```text
local ffi = require("ffi")
ffi.cdef[[
int gse_ffi_i_f3(int funcid, float f1, float f2, float f3);
]]
local funcid = 1
ffi.C.gse_ffi_i_f3(funcid, objID, posx, posy, posz)
```

就可以从lua中利用ffi调用c#的函数了

可以类似tolua，将这个注册流程的代码自动生成。

9.既然luajit坑那么多那么复杂，为什么不用原生lua？

无法否认，luajit的jit模式非常难以驾驭，尤其是其在移动平台上的性能表现不稳定导致在大型工程中很难保证其性能可靠。那是不是干脆转用原生lua呢？

我们的建议是，继续使用luajit，但是对于一般的团队而言，使用interpreter模式。

目前根据我们的测试情况来看，luajit的interpreter模式夸平台稳定性足够，性能行为也基本接近原生lua（不会像jit模式有各种trace compiler带来的坑），但是性能依然比原生lua有绝对优势（平均可以快3~8倍，虽然不及jit模式极限几十倍的提升），所以在游戏这种性能敏感的场合下面，我们依然推荐使用luajit，至少使用interpreter模式。这样项目既可以享受一个相对ok的语言性能，同时又不需要过度投入精力进行lua语言的优化。

此外，luajit原生提供的profiler也非常有用，更复杂的字节码也更有利于反破解。如果团队有能力解决好luajit的编译以及代码修改维护，luajit还是非常值得推荐的。

不过，luajit目前的更新频率确实在减缓，最新的luajit2.1.0 beta2已经有一年没有新的beta更新（但这个版本目前看也足够稳定），在标准上也基本停留在lua5.1上，没有5.3里int64/utf8的原生支持，此外由于luajit的平台相关性极强，一旦希望支持的平台存在兼容性问题的话，很可能需要自行解决甚至只能转用原生lua。所以开发团队需要自己权衡。但从我们的实践情况来看，luajit使用5.1的标准再集成一些外部的int64/utf解决方法就能很好地适应跨平台、国际化的需求，并没有实质的障碍，同时继续享受这个版本的性能优势。

我们的项目，在战斗时同屏规模可达100+角色，在这样的情况下interpreter的性能依然有相当的压力。所以团队如果决定使用lua开发，仍然要注意lua和c#代码的合理分配，高频率的代码尽量由c#完成，lua负责组装这些功能模块以及编写经常需要热更的代码。

最后，怎么打开interpreter模式？非常简单，最你执行第一行lua前面加上。

```text
if jit then
  jit.off();jit.flush()
end
```

### 平台相关篇

1.精简你的lua导出，否则IL2CPP会是你的噩梦

网上已经有非常多IL2CPP导致包体积激增的抱怨，而基于lua静态导出后，由于生成了大量的导出代码。这个问题又更加严重

鉴于目前ios必须使用IL2CPP发布64bit版本，所以这个问题必须要重视，否则不但你的包体积会激增，binary是要加载到内存的，你的内存也会因为大量可能用不上的lua导出而变得吃紧。

移除你不必要的导出，尤其是unityengine的导出。

如果只是为了导出整个类的一两个函数或者字段，重新写一个util类来导出这些函数，而不是整个类进行导出。

如果有把握，可以修改自动导出的实现，自动或者手动过滤掉不必要导出的东西。

2.ios在没有jit的加持下，luajit的性能特性与原生lua基本一致

注意，这里说的不是“性能”一致，是“性能特性”一致。luajit不开启jit依然是要比原生lua快很多的。这里说的性能特性一致是指你可以按照原生lua的优化思路来优化luajit的非jit环境。

因为ios下无法开启jit，只能使用interpreter，因为原生lua的优化方案基本都适用于ios下使用。这时，每一个a.b都意味着一次表查找，写代码的时候一定要考虑清楚，该cache的cache，该省的省。

3.luajit在没有开启GC64宏的情况下，不能使用超过1G的内存空间

随着现在游戏越来越大，对内存的消耗也越来越高。但是luajit有一个坑也是很多人并不知道的，就是luajit的gc不支持使用1G以上的内存空间。如果你的游戏使用了1G以上的内存，luajit很可能就会分配不出内存然后crash掉。

有没有解呢？目前有一个折中解，就是开启LUAJIT_ENABLE_GC64宏再编译luajit（这也是目前支持arm64 bytecode必须的），但是这个方法有一个大问题，就是开了这个宏就不能开启jit，目前官方并没有给出解决这个问题的时间表，所以可以认为很长一段时间内这个问题都会存在（除非哪位大牛出来拯救一下）。

当然考虑到现在ios的游戏都普遍要压在300M以下的内存占用，这点并不用太担心，除非你有很大的跨平台打算，或者面向未来两年后的主流手机设备开发。