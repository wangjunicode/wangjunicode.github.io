---
title: Lua的require机制
published: 2018-09-04
description: "Lua的require机制 Lua 是通过require 函数来加载模块的，只需提供模块的名字，即可通过require(modname)来加载模块"
tags: []
category: 编程语言
draft: false
---


Lua的require机制
Lua 是通过require 函数来加载模块的，只需提供模块的名字，即可通过require(modname)来加载模块

Lua 是如何通过modname 来载入.lua 或 .so的呢

默认加载过程

package.loaded[modname]中存了模块的数据，有则直接返回
顺序遍历package.searchers，获取loader
package.preload[modname]
Lua Loader, 通过package.searchpath搜索package.path
C Loader, 通过package.searchpath搜索package.cpath
All-In-One loader
调用loader载入模块
将载入结果保存至package.loaded[modname]并返回结果