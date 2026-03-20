---
title: Lua 的 require 机制详解
published: 2018-09-04
description: "深入解析 Lua 的 require 函数加载模块的完整流程，包括 package.loaded 缓存、搜索路径配置、自定义 loader 等核心机制。"
tags: [Lua, 模块系统, 编程语言]
category: 编程语言
draft: false
---

## 什么是 require

Lua 通过 `require` 函数来加载模块，只需提供模块名即可通过 `require(modname)` 加载模块。

```lua
local json = require("cjson")
local Vector3 = require("Vector3")
```

## require 的完整加载流程

```
require("modname")
    │
    ▼
1. 检查 package.loaded[modname]（缓存）
    │ 已缓存 → 直接返回
    │ 未缓存 ↓
    ▼
2. 遍历 package.searchers 列表
    ├── searcher1: 检查 package.preload[modname]
    ├── searcher2: Lua Loader（搜索 package.path）
    ├── searcher3: C Loader（搜索 package.cpath）
    └── searcher4: All-In-One Loader
    │
    ▼
3. 调用找到的 loader 载入模块
    │
    ▼
4. 将结果保存至 package.loaded[modname]
    │
    ▼
5. 返回结果
```

## 关键机制详解

### 1. 缓存机制：package.loaded

`package.loaded` 是一个表，存储了所有已加载的模块：

```lua
-- 第一次加载，会执行模块文件
local A = require("MyModule")

-- 第二次加载，直接从缓存返回，不会重复执行
local B = require("MyModule")

print(A == B)  -- true，同一个对象
```

**强制重新加载**：

```lua
package.loaded["MyModule"] = nil  -- 清除缓存
local M = require("MyModule")     -- 重新加载
```

### 2. 搜索路径：package.path

Lua Loader 会根据 `package.path` 中的模式匹配文件：

```lua
-- 默认 package.path 示例
print(package.path)
-- ./?.lua;./?.lua;/usr/local/share/lua/5.4/?.lua;...

-- 添加自定义路径
package.path = package.path .. ";./scripts/?.lua"
```

`?` 会被替换为模块名（将 `.` 替换为路径分隔符）。

### 3. 预加载：package.preload

可以将 loader 函数预先注册，不需要对应文件：

```lua
package.preload["mylib"] = function()
    return { 
        hello = function() print("Hello!") end 
    }
end

local mylib = require("mylib")
mylib.hello()  -- Hello!
```

## 模块的标准写法

```lua
-- MyModule.lua
local M = {}  -- 模块表

M.VERSION = "1.0"

function M.doSomething()
    print("doing something")
end

-- 私有函数（不暴露给外部）
local function privateFunc()
    -- ...
end

function M.publicFunc()
    privateFunc()  -- 可以调用私有函数
end

return M  -- 必须 return
```

## 在 Unity Lua 中的应用

在 xlua/tolua 项目中，require 路径通常经过自定义：

```lua
-- 自定义 loader，从 AssetBundle 加载 Lua 文件
package.loaders[#package.loaders + 1] = function(modname)
    local path = modname:gsub("%.", "/") .. ".lua"
    local text = LuaLoader.LoadFromBundle(path)  -- 从 AB 包加载
    if text then
        return load(text, modname)
    end
end
```
