---
title: 关于uLua
published: 2020-01-01
description: "uLua ulua/nlua 都是基于反射的解决方案，劣势是速度慢，gc alloc频繁,不直接支持代理，优势是不会产生静态代码，减少了app的尺寸。"
tags: []
category: 编程语言
draft: false
---

uLua

## 概述

ulua/nlua 都是基于反射的解决方案，劣势是速度慢，gc alloc频繁,不直接支持代理，优势是不会产生静态代码，减少了app的尺寸。



## uLua Unity工作机制

基于ulua 1.25版本,开启C#类型动态注册.

**步骤**

1. 注册需要Wrap的C#类型

    在WrapFile.cs类中,使用_GT(typeof(XXX)), 注册需要Wrap的C#类型。注册的C#类型被包装成BindType对象,在BindType构造函数里获取注册类型的类名,注册给Lua的名称,基类名称,Wrap的文件名称等信息,并保存在相应的BindType对象中.(这些是在WrapFile类创建时就生成的)　　

  2. 执行编辑器脚本,生成Wrap的C#类, LuaBinder类,以及Wrap.lua文件

    执行编辑器脚本SimulatorRunScript,调用LuaBinding里的相关接口,LuaBinding里遍历WrapFile中注册的需要Wrap的C#类型,根据BindType里的信息,自动生成cs代码文件,并且生成LuaBinder类和Wrap.lua文件.

　3.以上是运行前的准备工作.点击运行按钮,运行项目

　4.项目首先初始化LuaScriptMgr.cs类,该类初始化后会执行Global.lua代码.

​		Global.lua首先require Wrap.lua文件,执行Wrap.lua文件中的代码.

　　Wrap.lua是2步骤里生成的,其内容是import各种C#类型到Lua,由于ulua支持动态注册C#类型.该类默认状态下是import了所有的C#类型到Lua,可以根据性能需要,修改Wrap.lua的生成方式,减少其中不需要立刻import的类型,改为在首次使用时import.提高启动效率.

​		通过import ‘XXX’ 可以把XXX类型注册到Lua,其原理是在Lua.cs脚本里将import这一字段注册到Lua的全局表中,并且将import绑定到C#中的LuaStatic.importWrap函数,因此Lua端执行import ‘XXX’之后,调用了C#的LuaStatic.importWrap函数,该函数从Lua栈中取出栈顶的XXX类型名,并调用了LuaBinder的Bind函数

　　LuaBinder也是在第2步中生成的类,其作用是注册1步骤Wrap的类型到Lua,该类Bind函数,接收一个类型名,然后Switch该类型,得到该类型Wrap后的类,并调用Wrap类中的Register函数,将该类型的相关方法注册到Lua,以供Lua端调用.

　　各Wrap类的Register函数通过调用LuaScriptMgr.RegisterLib函数,注册到Lua,在RegisterLib函数里,为该类型的namespace的各级创建相应table并注册到Lua端,以免类型的namespace在Lua端无法找到.例如System.IO.File会创建System,IO的table,以及File类型的table

**需要注意的事情**

1. 有些类在Wrap后会导致编译错误,例如File类,因为ulua在Wrap时不支持泛型<T>,一些用到泛型的函数Wrap后会出错,还有其他一些方面会导致Wrap出的类型报错,或者有一些类是经过改造的,不能从原类型Wrap,这时,我们Wrap一次之后,修改Wrap后的文件以满足我们的需要,解决编译报错,然后将该类型从WrapFile中_GT(typeof(XXX))删除,不让ulua在Wrap阶段处理该类型,但是需要修改LuaBinder.cs和Wrap.lua的生成方式,保留该类型的相关代码,以免影响该类型注册到Lua的这一过程.
2. 有些类比如Image,其继承了Graphic类的color属性,如果Image是属于第1点中提到的Wrap一次的类,那么也必须要对其基类Graphic进行Wrap一次,否则Lua端会找不到Image继承的color属性.
3. 编译LuaJit – 同一台PC上如果安装了多个版本的VS,可能会出现找不到kernel32库的问题,尝试用各个版本的命令行工具编译.
4. 编译ulua库时,如果环境变量里有其他MinGW,有可能导致编译失败.需要先将环境变量include,lib,path改为ulua源码编译工具中带的MinGW
