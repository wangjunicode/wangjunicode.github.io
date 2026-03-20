---
title: Lua 虚拟机原理详解
published: 2019-11-05
description: "深入解析 Lua 虚拟机的内部工作原理，从词法分析、语法分析到字节码生成与执行，以及寄存器式虚拟机的设计思想。"
tags: [Lua, 虚拟机, 编译原理]
category: 编程语言
draft: false
---

## 虚拟机概述

Lua 虚拟机是一个**寄存器式（Register-based）** 虚拟机，不同于 JVM 和 CPython 的栈式虚拟机。寄存器式虚拟机的指令通常更少，执行效率更高。

**虚拟机的输入**：源码文件  
**虚拟机的输出**：代码执行结果

## 执行流程

```
源码文件
    │
    ▼
[词法分析] Lexer
    │ 生成 Token 流
    ▼
[语法分析] Parser
    │ 生成 AST（抽象语法树）
    ▼
[代码生成] Code Generator
    │ 生成字节码（Bytecode）
    ▼
[虚拟机执行] VM
    │
    ▼
执行结果
```

## 各阶段详解

### 1. 词法分析（Lexer）

将源码字符串分割为一个个 **Token（词法单元）**：

```lua
local a = 18
```

分析结果：
| Token | 类型 |
|-------|------|
| `local` | 保留字 |
| `a` | 标识符 |
| `=` | 等号 |
| `18` | 数字 |

### 2. 语法分析（Parser）

检查 Token 流是否符合 Lua 语法规则，若有语法错误则立即报错停止执行。

例如 `function` 必须以 `end` 结束：
```lua
-- 正确
function foo()
    print("hello")
end

-- 语法错误：缺少 end
function bar()
    print("world")
-- 这里会报错：'end' expected
```

### 3. 字节码生成

满足语法规则后，生成对应的**字节码指令**：

```lua
local a = 18
-- 对应字节码：LOADK 0 0
-- 第一个 0: 变量 a 所在的寄存器位置
-- 第二个 0: 常量 18 在常量表中的索引
```

查看字节码可以用 `luac` 工具：

```bash
luac -l -l test.lua
```

输出示例：
```
main <test.lua:0,0> (4 instructions at 0x...)
0+ params, 2 slots, 1 upvalue, 1 local, 1 constant, 0 functions
	1	[1]	VARARGPREP	0
	2	[1]	LOADI    	0 18       ; a = 18
	3	[1]	RETURN1  	0 1 1
```

### 4. 指令执行

虚拟机从第一条字节码指令开始逐行执行，根据 **opcode** 执行对应逻辑：

```
Lua 5.4 的主要 Opcode 类型：
- MOVE      寄存器间赋值
- LOADI     加载整数常量
- LOADF     加载浮点常量
- LOADK     加载常量
- CALL      函数调用
- RETURN    函数返回
- ADD/SUB   算术运算
- JMP       无条件跳转
- EQ/LT/LE  比较跳转
- FORLOOP   数值型 for 循环
```

## 寄存器式 vs 栈式虚拟机

Lua 使用寄存器式虚拟机，相比 JVM 等栈式虚拟机：

| 对比 | 寄存器式（Lua） | 栈式（JVM） |
|------|--------------|------------|
| 指令数量 | 少 | 多 |
| 单条指令复杂度 | 高（含操作数）| 低（无操作数）|
| 解码开销 | 稍大 | 小 |
| 整体性能 | 通常更快 | 优化潜力大 |

## 函数与闭包

Lua 函数是**一等公民**，函数本身也是一个值（Closure）：

```lua
function makeCounter()
    local count = 0
    return function()      -- 返回一个闭包
        count = count + 1  -- 捕获 upvalue: count
        return count
    end
end

local counter = makeCounter()
print(counter())  -- 1
print(counter())  -- 2
```

闭包捕获的外部变量称为 **UpValue**，虚拟机通过 UpValue 机制实现闭包。

## GC 机制

Lua 使用**增量标记清除（Incremental Mark and Sweep）** 垃圾回收：

- 每次 GC 只执行一小步，避免长时间停顿
- 通过 `collectgarbage` 可以手动控制 GC
- 在游戏开发中，可以在场景切换时触发完整 GC：

```lua
collectgarbage("collect")  -- 触发完整 GC
collectgarbage("count")    -- 查看内存使用量（KB）
```
