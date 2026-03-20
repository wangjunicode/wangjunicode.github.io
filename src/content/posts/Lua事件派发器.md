---
title: Lua事件派发器
published: 2019-09-10
description: "Lua事件派发器 **简易实现**"
tags: [Lua, 事件系统, 游戏开发]
category: 编程语言
draft: false
---

Lua事件派发器

**简易实现**

```lua
-- EventDispatcher class
EventDispatcher = {}
EventDispatcher.__index = EventDispatcher

function EventDispatcher.new()
    local self = setmetatable({}, EventDispatcher)
    self.listeners = {}
    return self
end

function EventDispatcher:addEventListener(eventName, callback)
    if not self.listeners[eventName] then
        self.listeners[eventName] = {}
    end
    table.insert(self.listeners[eventName], callback)
end

function EventDispatcher:removeEventListener(eventName, callback)
    local eventListeners = self.listeners[eventName]
    if eventListeners then
        for i = #eventListeners, 1, -1 do
            if eventListeners[i] == callback then
                table.remove(eventListeners, i)
                break
            end
        end
    end
end

function EventDispatcher:dispatchEvent(eventName, ...)
    local eventListeners = self.listeners[eventName]
    if eventListeners then
        for i = 1, #eventListeners do
            eventListeners[i](...)
        end
    end
end

local dispatcher = EventDispatcher.new()

local callbackFunction = function(param1, param2)
    print(param1, param2)
end

dispatcher:removeEventListener("eventName", callbackFunction)
dispatcher:addEventListener("eventName", callbackFunction)


dispatcher:dispatchEvent("eventName", "hello1", "world")
dispatcher:removeEventListener("eventName", callbackFunction)
dispatcher:dispatchEvent("eventName", "wang2", "world")
```

