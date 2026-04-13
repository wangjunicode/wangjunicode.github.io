---
title: 关于Lua-面向对象的实现
published: 2023-09-15
description: "Lua是一门面向过程(procedure-oriented)与函数式编程(functional programming)的语言，因为Lua它是定位于开发中小型程"
tags: []
category: 编程语言
draft: false
---

Lua是一门面向过程(procedure-oriented)与函数式编程(functional programming)的语言，因为Lua它是定位于开发中小型程序，往往不会用于编写大型程序；所以它并没有提供面向对象思想的，很多都是通过模拟出来的；这里的关键就是元表和元方法，通过元表以及元方法就可以模拟出一些面向对象语言中的行为或者思想

#一、Lua的类
一个类就是创建对象的模具，对象又是某个特定类的实例；在Lua中table可以有属性（成员变量），也可以有成员方法（通过table+function实现）；因此可以通过table来描述对象的属性
首先这里讲一下关于Lua中定义函数时“.”和“:”的区别，在Lua中也有类似于C++中的this指针，在Lua中是self，当我们定义函数时使用的是冒号，就相当于隐式传递了一个当前调用者过去

-- 把tb表中的a和b相加程序

```lua
local tb = {a=0,b=1}
function tb.add(a,b)
	return a+b
end

print(tb.add(tb.a,tb.b))
```


也可以换一种写法，只需要传递一个参数就可以

```lua
-- 传递一个参数实现tb表中两数相加
local tb = {a=0,b=1}
function tb.add(self)
	return self.a+self.b
end

print(tb.add(tb))
```


当我们不想传递参数时可以通过冒号来定义和调用函数，这种就和上面把tb传递过去的做法类似了，但是这里时通过定义函数时隐式把自身传递过去的，当然也可以点与冒号搭配使用，进行指定传递过去的表

```lua
local tb = {a=0,b=1}
function tb:add()
	return self.a+self.b
end

print(tb:add())			--需要使用冒号进行调用
--print(tb.add(tb))		--一样可行，冒号定义函数其实就是隐式通过第一个参数把自身传递过去
print(tb.add(tb1))		-- 也可以不通过冒号进行调用，使用点进行调用可指定传过去的表
```


当基本了解table的一些操作后，下面这是一个Lua中的一个简单的类的实现；下面定义了一个名为a的table，然后再通过创建一个对象tb,再使用tb去调用类中的方法MyPrint

```lua
local a = {name="lisi"}		--->name属于a表中的一个成员变量

function a:new( o )			----类似于构造函数，用于创建一个类对象的
	o = o or {}
	setmetatable(o,self)
	self.__index = self

	return o

end

function a:MyPrint(  )		---->new属于a表中的一个成员方法
	print(self.name)
end


local tb = a:new(nil)		-----实例化对象
tb:MyPrint()
```




二、lua的单继承

在Lua中是通过table以及元表进行实现面向对象思想中的继承，主要通过setmetatable以及__index两个字段进行实现的，因为当我们为一个表使用setmetatable设置了元表后，如果在当前表中找不到该变量或者函数时就会根据__index这个字段所包含的地方去找（若__index包含的是一个表就会去所包含的表中遍历是否存在该变量，如果__index包含的是一个函数则会调用该函数）；这就与我们面向对象思想中的基类与派生类的关系相似了，在面向对象语言像C++中若在派生类找不到的变量或函数就会去到基类中去查找。

但是与C++这些面向对象语言相比较而言；就没有那么好用；并且在使用时需要注意基类与派生类之间的关系，有时候会因为不注意而导致内存访问时出现混乱；一般在使用时尽量不同的操作要独立为一个函数，否则有可能会出现派生类操作的都是基类的变量的情况，例如在下面程序中把self.name = newname放到了new函数内，就导致了每次重新创建一个对象后对它的name进行初始值后，之前创建的对象cat中的name的值也会随之改变；实际这里操作的一直都是基类中的变量，而非自身的变量

```lua
animal = {name="default"}

function animal:new(tb,newname)
	tb = tb or {}		----->若tb为nil将赋值一个空表 
	setmetatable(tb,self)		--->设置为元表
	self.__index = self
	

	self.name = newname
	
	return tb

end

function animal:myprint()
	print(self.name)
end

cat = animal:new(nil,"cat")
cat:myprint()				----->打印cat

dog = animal:new(nil,"dog")	----->这里修改的其实是基类的变量
dog:myprint()				---->打印dog

cat:myprint()				---->打印dog
```


在上述程序中，这种继承将会导致多个派生类访问的都是基类中的变量；导致这种情况的原因是因为在new一个对象时，每次的self指针都是animal这个table里面的变量；我们想要解决这种情况需要重新定义一个函数专门用于初始化name这个变量的，这样每次调用时因为时冒号调用的就会把自身传递过去，当设置名字时如果自己没有name这个变量就会重新分配内存进行赋值操作了；这样就能解决多个派生类共用基类内存中的变量了（如果不理解这段话的可以直接看代码）

```lua
animal = {name="default"}

function animal:new(tb)
	tb = tb or {}		----->若tb为nil将赋值一个空表 
	setmetatable(tb,self)		--->设置为元表
	self.__index = self

	-- self.name = newname		--这里相当于是animal.name = newname
	
	return tb

end

function animal:myprint()
	print(self.name)
end


function animal:setname( name )
	self.name = name
end

cat = animal:new(nil)
cat:setname("cat")	---这里cat调用setname函数后，函数内相当于是cat.name = name
cat:myprint()

dog = animal:new(nil)
dog:setname("dog")	---这里dog调用setname函数后，函数内相当于是dog.name = name
dog:myprint()

mouse = animal:new(nil)
mouse:myprint()

dog:myprint()		---此时再打印dog的name不会出现因为前面的修改了
```


在这个程序中，将变量单独出来了；每次操作时需要调用函数，此时调用函数后当前的self就变成了当前调用的对象了；这样的话在操作时若name这个变量不存在将会在当前对象里创建一个再进行赋值；若该变量存在将会直接进行操作



三、lua的多继承

在lua的单继承中是通过setmetatable以及__index字段包含一个table表格来实现的；多继承中与单继承类似但不一样的是多继承中的__index字段包含一个函数时；当为一个table设置了元表以后，那么在执行时如果在原表table中找不到key的值，将会调用这个函数在其他地方进行查找key；因此我们就可以通过这一特点来在Lua中实现多继承

首先看一下如何在多个table表中查找某一字段

```lua
function seach( tb,key)
	for i=1,#tb do
		if tb[i][key] then		--只要所找的字段key的值不为nil就返回
			return tb[i][key]
		end
	end
end

local t1 = {name="lisi"}
local t2 = {age=18}

print(seach({t1,t2},"age"))	--把t1、t2都放入一个表中，相当于表套表，再遍历每个表里面的字段
```


这里简述一下执行流程：

1、首先使用一个表进行接收t1、t2两个表，然后与需要查找的key一并通过调用传递到search函数中
2、然后从第一个表开始逐一遍历，直到遍历到表的末尾
3、如果第i个表中存在key且不为nil，就返回key的值（key为nil时为false，将不返回）


由于在多继承中search函数是关键，当了解了如何在多个表中进行查找某个key以后就可以开始进入主题：Lua如何实现多继承的。首先由于多继承意味着一个派生类拥有着多个基类，所以我们无法通过一个类中的方法进行创建，这个时候就需要单独定义一个特殊的函数来实现创建一个新派生类的功能，下面的AnimalClass函数就是用于实现一个新的派生类的

```lua
function search( tb,key )		--遍历多个基类中是否存在该方法或变量，存在且不为nil就返回
	for i=1,#tb do
		if tb[i][key] then
			return tb[i][key]
		end
	end
end


function AnimalClass( ... )
	local TbColletion = {...}		--用于接收传递进来的多个表
	local o = {}					--这是每次new创建的一个空表

	setmetatable(o,{__index = function (table,key )		--设置元表，每次查找一个字段时若当前表不存在将会调用这个函数，然后再调用search函数在多个基类中去遍历
		return search(TbColletion,key)
	end}) 
	
	function o:new(  )				--为返回的o表写一个new方法，若派生类没有重写new方法将会调用这个方法进行new
		NewTable = {}
		setmetatable(NewTable,self)
		self.__index = self			
		return NewTable
	end
	
	return o

end


CatTb = {name="加菲猫"}			
function CatTb:NamePrint()
	print(self.name)
end

function CatTb:new( )
	o = {}
	setmetatable(o,self)
	self.__index = self		

	return o

end


DogTb = {behavior="吃饭"}

function DogTb:BehPrint( )
	print(self.behavior)
end

function DogTb:new(  )
	o = {}
	setmetatable(o,self)
	self.__index = self

	return o

end

-------创建对象-----------------
local MulTb = AnimalClass(CatTb,DogTb)
local MyTb  = MulTb:new()

MyTb:NamePrint()
MyTb:BehPrint()
```


执行结果：


该程序的执行流程可以分成：

1、调用AnimalClass函数并传递两个表用于创建对象，新对象将继承于这两个表
2、为新创建的对象设置元表并且设置__index字段为一个函数，该函数主要作用为调用search函数
3、返回新创建的表o
4、使用新创建返回的对象调用new函数，因为返回的对象没有new函数就会根据调用__index所包含的函数
5、然后就调用search函数进行查找new函数；search函数就负责遍历创建对象时传递过来的所有表（TbColletion 是用于接受保存创建对象时传递过来的所有表）
6、其他函数就会根据这个规律进行调用

注意在多继承中每个被创建以及实例出来的类都是单个的并能够调用该类中继承的所有基类的函数或者变量；但是由于search函数的复杂性所以导致了多继承的性能不及单一继承



四、Lua的私密性

lua的私密性实现思想实质是通过两个表来表示一个对象的，两个表中一个表用与表示状态（这是存放不被外部访问的变量以及函数等），一个是保存对象的操作（即相当于留给对象可访问的变量或函数）；当我们使用下面程序中的AnimalClass创建对象后，这个对象其实返回的是一个装有指定函数接口的表，并且我们想要访问或者修改self表的数据就只能通过我们返回的表里面的接口去访问；因此在我们是程序最后面调用未返回的函数cat.think()时就会报错提示think是一个nil值，因为在我们返回的表中并没有这个函数，因此在访问时就会创建一个think，但是这个think是没有任何东西的所以这个时候就是一个nil

```lua
function AnimalClass(  )
	local self = {name="default",behavior="default"}		---->保存对象变量状态的表

	function SetBehavior( NewBehavior )
		self.behavior = NewBehavior
	end
	function BehaviorPrint( )
		print(self.behavior)
	end
	
	function SetName( NewName )
		self.name = NewName
	end
	function NamePrint(  )
		print(self.name)
	end


	function think(  )
		print("i am thinking...")
	end
	
	return {
		SetBehavior=SetBehavior,		----->使用一个表返回可供外部访问的接口，前面的key可以自定义；但是为了方便辨认一般名称一致
		BehaviorPrint=BehaviorPrint,
		SetName=SetName,
		NamePrint=NamePrint
	}

end


cat = AnimalClass()
cat.SetBehavior("吃饭")
cat.BehaviorPrint()

cat.SetName("加菲猫")
cat.NamePrint()

 -- cat.think()		---->这里会报错，因为该函数并未返回接口 
```



也可以使用下面这种方法进行实现面向对象的私密性，这种相比较上面的代码而言可以比较清晰的看出两个表的关系，obj表是用于存放对象状态的，也可以说是存放不想被外部访问的变量或数据的。然后option表是用于返回提供给外部调用的函数接口

```lua
function createClass( InitName , InitId )
	local obj = {name =InitName,id=InitId }
	local option = {}

	function option.SetInfo( NewName,NewId )
		if NewName==nil or NewId==nil then
			if NewId~=nil then
				obj.id = NewId 
				print("已成功修改ID")
				-- return "已成功修改ID"
			elseif NewName~=nil then
				obj.name = NewName
				print("已成功修改姓名")
				-- return "已成功修改姓名"
			else
				error("未能成功赋值")				----若两个参数都为nil的话就error报错，后续程序不在运行
				-- return "未能成功赋值"
			end
		end
	
		obj.name = NewName
		obj.id 	 = NewId
		return "已成功修改姓名、ID"
	end
	local function MyPrint(  )
		print(obj.name,"====>",obj.id)
	end
	
	function option.InfoPrint(  )
		MyPrint()
	end

    return option
end


local obj1 = createClass("lisi",21)
obj1.InfoPrint()
obj1.SetInfo("qiqi",nil)
obj1.InfoPrint()
print(obj1.name)		------>打印nil，外部不能访问，这里的name相当于option表中的name

-- obj1.MyPrint()		----->这里会报错，因为该函数不在返回的表中
```




五、单一方法（single-method）做法
当上面的面向对象编程私密性中出现一种情况：若当前一个对象只存在一个方法时可以不用创建一个返回外部访问接口的表，从而直接返回该函数即可；这种情况虽无法保证继承，但是也拥有了完全私密性的控制

```lua
function AnimalClass( value )

	return function ( action,v )		---->直接返回该函数
		if action == "get" then return value 
		elseif action == "set" then value = v
		else error("invaild action")
		end
	end

end

d = AnimalClass(0)
print(d("get"))
d("set",10)
print(d("get"))
--print(d.value)		---->会报错
```




六、多态的实现

由于在Lua中并不能像C++一样直接进行函数重载，因为无论如何前面的函数都会被最后一个同名函数所覆盖；同理派生类的同名函数也会覆盖基类中的同名函数（所以派生类中重载了基类中的同名函数后调用时就会调用派生类中的函数），但是可以通过指定名称的方式进行调用基类的函数，如果我们想要实现重载就只能写一个函数，虽然Lua中没有那么灵活的语法，但是我们可以通过一个函数接受多个参数，然后判断对应参数是否为nil再进行对应的操作；类似于下面程序中的tb:GetAreatb:GetArea函数

```lua
tb = {area = 0}

 function tb:new( o )
	o = o or {}
	setmetatable(o,tb)
	self.__index = self

 function tb:GetArea(side,len )
	if len==nil or side==nil then	--只要side或len存在一个为nil就进入
		if len~=nil then			--如果len不为nil就是side为nil，不对side进行操作
			self.area = len*len
		elseif side~=nil then		--如果side不为nil就是len为nil，不对len进行操作
			self.area = side*side
		else
			self.area = 0
		end
		return 
	end
	self.area = len*side
end

function tb:PrintArea(  )
	print(self.area)
end

---------创建对象----------
NewTb = tb:new(nil)
NewTb:GetArea(3,5)
NewTb:PrintArea()

-------派生类重载基类函数-------
function NewTb:GetArea( len )
	self.area = len*len
end

NewTb:GetArea(5)	--重载后默认调用派生类中的函数
NewTb:PrintArea()	--这个函数没有重载调用的依旧是基类的函数


--指定名称方式调用基类函数
tb1:GetArea(5,3)
tb1:PrintArea()
```

