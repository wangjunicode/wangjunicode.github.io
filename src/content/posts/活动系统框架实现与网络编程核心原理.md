---
title: 活动系统框架实现与网络编程核心原理
published: 2024-06-01
description: "活动系统框架开发完成，网络编程原理学习，Loading加载时长统计优化，Lua GC分析"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 06/01 Lua 传递方式 & 网络编程

### Lua 引用传递 vs 值传递
- **引用传递**：`function`、`table`、`userdata`、`thread（协程）`
- **值传递**：`number`、`string`、`boolean`、`nil`

### 网络编程两大核心问题
1. **定位主机**：IP 层负责，通过 IP 地址唯一确定 Internet 上一台主机
2. **可靠传输**：TCP 层负责，提供面向应用的可靠（TCP）或非可靠（UDP）数据传输

**网络协议分层的意义**：
- 简化问题复杂度，各层独立
- 灵活性好，一层技术变化不影响其他层
- 易于实现和维护，促进标准化

### TCP 粘包和拆包

**发生原因**：TCP 是面向流的协议，操作系统通过缓冲区优化发送：
- **粘包**：多次 send 间隔很短，缓冲区将多条消息合并发出（`hello` + `world` → `helloworld`）
- **拆包**：单次 send 数据量超过缓冲区，TCP 拆分成多次发送

**解决方案**：
1. **固定长度**：每个包封装成固定长度，不足补零
2. **分隔符**：包末尾用固定分隔符（如 `\r\n`），需处理跨包情况
3. **头部长度**：消息分头部（含总长度）+消息体，读够长度才算完整
4. **自定义协议**：通过自定义协议处理粘包/拆包

## 06/06 LOD & 游戏存档

### LOD（Level of Detail）网格细节级别
当游戏对象距摄像机较远时，可见细节减少，使用 LOD 对远处对象用低精度网格渲染，节省 GPU 资源。

### 坐标系转换
- **世界坐标**（World Space）
- **屏幕坐标**（Screen Space）
- **局部坐标**（Local Space）

### 游戏存档设计
- 实现抽象类，加上可序列化标签
- 接口：获取存档进度、保存存档数据、删除存档数据
- 存储方式：JSON + 密钥（本地加密）

## 06/11 活动框架开发

### GM 命令调试
```lua
-- 通过 ServerLocation 发送 GM 命令（注意参数空格）
ServerLocation:GetServer("GMServer")("SendGM", {10000, "act,10000001,taskrm"})
```

### 管道刷新机制
- Panel `open` 时调用基类 `open`，同时会刷新管道
- Widget 使用 `self:AssetDataRefresh()` 刷新

### 活动框架文件结构
```
活动系统：
  - Logic 代码（处理数据和逻辑）
  - System 代码（活动管理器）
  - UI 代码（界面展示）
  - DAL 代码（数据访问层）
```

### createWidget vs createWidgetInstance
- `createWidget`：创建并缓存 widget 实例
- `createWidgetInstance`：每次创建新实例，不缓存

## 06/12 性能分析 & Lua GC

### 帧时间预算
- 30帧游戏：每帧 **33.33ms**
- 一段程序消耗 < 0.3ms → 约 1%，可接受
- GC：不是每帧多次触发就还行

### Profiler 打点
```csharp
UnityEngine.Profiling.Profiler.BeginSample("---YouMeClientAdapter.Poll");
// 要分析的代码
UnityEngine.Profiling.Profiler.EndSample();
```

### Lua 事件 Bug 排查
事件相关 Bug，**第一直觉**：
1. 注册是否成功（Register 是否调用）
2. 监听移除是否成对（Unregister 是否在 OnDestroy 调用）

## 06/13 活动框架 UI 开发

### LoopGridLayoutGroup 组件使用规范
- 初始化时必须调用；关闭界面时要调 `clear` 清理
- 传入的 list 下标必须从 **1** 开始（Lua 数组潜规则）

### 数据结构从需求文档中提取
标准流程：
1. 理解业务需求和流程
2. 标识实体（User、Product、Order...）和属性
3. 建立实体关系（一对多、多对多）
4. 抽取数据结构（Lua table 格式）
5. 与业务分析师复查验证

## 06/14 Lua rawset/rawget

```lua
-- rawget/rawset：直接操作原始 table，忽略 metatable
local t = setmetatable({}, {
    __index = function(t, k) return "default" end
})

print(t.x)           -- "default"（走 __index）
print(rawget(t, "x")) -- nil（绕过 metatable，直接读原始表）
rawset(t, "x", 100)  -- 直接写原始表，不触发 __newindex
```

## 06/17 多语言实现原理

### 项目多语言方案
1. 游戏内所有文本全部用 **ID** 表示
2. Excel 配置 ID → 文本映射（各语言版本）
3. Excel → CSV（Python/NPOI 处理）→ Lua 配置
4. 运行时：Android 通过 Java 类、iOS 通过 OC 类监听输入法当前语言
5. 通知游戏加载对应语言包（ID → 文本的映射）

### EmmyLua 大目录过滤（逐个配置）
```json
{
    "source": [
        {
            "dir": "./",
            "exclude": ["csv/**.lua", "Config/**.lua"]
        }
    ]
}
```

### DBManager 配置绑定
`CFG` 目录下新建 config 文件，F11 后 DBManager 会自动添加绑定。

## 06/18 字库与字体

### 文字丢失不显示
**检查字库**：文本不显示时，先检查 TMP 字库是否包含对应字符。

## 06/19 Lua GC 深入 & 闭包

### 闭包与 GC
闭包是一个函数，引用了函数外定义的变量（upvalue）。闭包持有外部变量的引用，会阻止 GC 回收。

**避免内存泄漏**：
```lua
-- 不再使用时将引用设为 nil
myClosure = nil
collectgarbage()

-- 弱引用表：不阻止 GC
local weakTable = setmetatable({}, {__mode = "v"})
weakTable[key] = closure  -- 弱引用，可被 GC 回收
```

### Lua Hook 模式
```lua
function original()
end

function hook()
    return function(...)
        -- do something before
        original(...)
        -- do something after
    end
end
```

### 滑动列表规则
**滑动列表的 list 数据必须是下标从 1 开始的数组**，否则渲染不生效。

## 06/20 活动代码整理

### PB 字段判空
处理 proto 反序列化时，需要考虑哪些字段可能为空：
- proto3 中所有字段都有默认值，数值型默认 `0`，字符串默认空字符串
- Lua 侧收到后要做存在性判断，避免 `nil` 访问报错

### Lua ipairs vs pairs

| 函数 | 遍历范围 | 顺序 | 适用场景 |
|------|---------|------|---------|
| `ipairs` | 从索引1开始的数组部分，遇nil停止 | 有序（1,2,3...） | 严格顺序数组 |
| `pairs` | 所有键值对（数组+哈希） | 无序 | 遍历所有字段 |

## 06/21 活动系统提交 & 音频

### 活动系统文档整理

**LoopGridLayout 动态滑动列表设计**：
- 依赖数据去处理 item 表现
- 数据驱动 UI 渲染

### Wwise 音频系统
Wwise 是目前性能先进、功能丰富的互动音频解决方案，广泛用于游戏开发。

**音频数字化流程**：
- **采样**：按时间间隔对模拟信号快照（44.1kHz = CD音质）
- **量化**：将采样值转为数字（16/24/32位）
- **编码**：PCM（无压缩）或 MP3/AAC（有损压缩）

## 06/24 Lua table.unpack

```lua
local tab = {1001, 1002, 1003}
local a, b, c = table.unpack(tab)
print(a, b, c)  -- 1001  1002  1003

-- 常用场景：将 table 元素展开为函数参数
func(table.unpack(params))
```

## 06/26 Loading 时长统计启动

### Loading 优化思路
**确定加载阶段**：资源加载 → 场景初始化 → UI 初始化

**统计方案**：使用 `Stopwatch` 在各阶段打点记录时间并写日志。

## 06/27 Loading 时间数据

PC 加载时间测量（毫秒）：
- `sc_denglu_001` 场景加载约 **1.3 秒**
- 各阶段时间区间：487-556ms、854-923ms、225-301ms、202-294ms

## 06/28 Loading 优化策略

### 加载时长优化方向
1. **资源优化**：纹理压缩（DXT/ETC2/ASTC）、模型减面、音频压缩
2. **异步加载**：按需加载（Addressables），避免一次性全量加载
3. **对象池**：预加载并缓存常用资源
4. **分帧初始化**：将 `Start/Awake` 中耗时操作延迟到运行后执行
5. **场景分割**：大场景拆成多个小场景，`LoadSceneAsync` 渐进加载
6. **Profiler 定位瓶颈**：用 Unity Profiler 找到具体耗时点，针对性优化
