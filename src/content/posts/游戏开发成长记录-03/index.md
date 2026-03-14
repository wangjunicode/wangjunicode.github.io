---
title: 我的游戏开发之路（三）：2019-2020，技术深度的跨越
published: 2019-06-01
description: "职场第二三年，开始系统掌握游戏客户端核心技术：Shader 编写、Lua/xLua 性能优化、AssetBundle 资源管理体系、UGUI 渲染原理。从「能用」到「理解原理」是这两年最核心的成长。"
tags: [成长记录, 游戏开发, Shader, Lua, 资源管理, UGUI]
category: 成长记录
draft: false
---

> 系列第三篇。2019-2020年，开始系统深入游戏客户端核心技术模块。

## 这两年做了什么

2019 年开始，我进入了一个我认为对游戏客户端工程师来说最重要的阶段：**从「会用 Unity 提供的功能」到「理解底层原理」**。

这个转变不是主动计划的，是项目逼出来的。

---

## Shader：第一次「写出来的代码在 GPU 上跑」

写第一个 Shader 的时候，有一种奇怪的感觉：代码语法和 C# 像，但逻辑完全不同。

```glsl
// 顶点着色器：处理每个顶点的位置变换
v2f vert(appdata v) {
    v2f o;
    o.vertex = UnityObjectToClipPos(v.vertex);  // 模型空间 → 裁剪空间
    o.uv = TRANSFORM_TEX(v.uv, _MainTex);
    return o;
}

// 片元着色器：处理每个像素的颜色输出
fixed4 frag(v2f i) : SV_Target {
    fixed4 col = tex2D(_MainTex, i.uv);
    return col;
}
```

最难理解的不是语法，是**思维方式的切换**：

- C# 是串行的，一行接一行执行
- Shader 是并行的，成千上万个像素同时在 GPU 上运算
- 在 Shader 里不能「循环等待」，不能「如果是第一个像素就做特殊处理」

这个并行思维，是 Shader 开发的核心门槛。

### 真正有用的 Shader 知识

理论学了不少，但真正在项目里用到、学会后立刻提高效率的：

**1. UV 动画**：用 `_Time` 偏移 UV 实现流动水面、传送门效果

```glsl
float2 uv = i.uv + float2(_Time.y * _FlowSpeedX, _Time.y * _FlowSpeedY);
fixed4 col = tex2D(_MainTex, uv);
```

**2. 顶点动画**：在顶点着色器修改位置实现草地风动效果

```glsl
float wave = sin(_Time.y * _WaveSpeed + v.vertex.x * _WaveFreq) * _WaveAmp;
v.vertex.y += wave * v.color.r; // 顶点颜色R通道控制受风影响程度
```

**3. Stencil Buffer**：用于实现遮罩、轮廓描边等效果

这三个掌握之后，能实现游戏中 80% 的特效需求。

---

## Lua/xLua：第一次在真实项目里用脚本语言

项目使用 xLua 做热更新，游戏逻辑大部分写在 Lua 里。

Lua 和 C# 的思维差异比我预期的大：

### 面向对象：用元表模拟

```lua
-- Lua 没有 class 关键字，用元表实现
local Animal = {}
Animal.__index = Animal

function Animal.new(name)
    local self = setmetatable({}, Animal)
    self.name = name
    return self
end

function Animal:speak()
    print(self.name .. " speaks")
end

-- 继承
local Dog = setmetatable({}, { __index = Animal })
Dog.__index = Dog

function Dog:speak()
    print(self.name .. " barks!")
end
```

项目中封装了一套 `BaseClass` 函数，让 Lua 面向对象看起来像 C#，但理解了元表的本质才能真正用好它。

### 性能优化：Lua 的"坑"

在做性能分析时，发现了几个 Lua 代码的常见性能问题：

**1. 全局变量比局部变量慢**

```lua
-- ❌ 慢：每次访问都查全局表
for i = 1, 1000000 do
    math.sin(i)
end

-- ✅ 快：缓存到局部变量
local sin = math.sin
for i = 1, 1000000 do
    sin(i)
end
```

**2. 字符串拼接产生大量临时对象**

```lua
-- ❌ 产生 N 个临时字符串
local s = ""
for i = 1, 100 do
    s = s .. i
end

-- ✅ 用 table.concat
local t = {}
for i = 1, 100 do
    t[i] = tostring(i)
end
local s = table.concat(t)
```

**3. 频繁创建 table 触发 GC**

```lua
-- ❌ 每帧创建临时 table
function Update()
    local data = { x = pos.x, y = pos.y }  -- 每帧分配，每帧 GC
    ProcessData(data)
end

-- ✅ 复用 table
local _tempData = {}
function Update()
    _tempData.x = pos.x
    _tempData.y = pos.y
    ProcessData(_tempData)
end
```

这些优化看起来细微，但在一个有大量 UI 和频繁更新的游戏里，累积起来的 GC 压力非常明显。

---

## AssetBundle：资源管理的「第一性原理」

做资源管理之前，我的资源加载就是 `Resources.Load()`。

项目里真正遇到资源问题时，才明白为什么需要 AssetBundle 体系：

- 包体太大，用户不愿意下载
- 新内容上线要让用户重新下载整个 App？
- 不同平台的纹理格式不同，怎么处理？

AssetBundle 解决了这些问题，但也带来了新的复杂度：

```
打包 → 压缩 → 分发 → 下载 → 解压 → 加载 → 引用计数 → 卸载
```

每个环节都有坑。其中让我印象最深的是**引用计数**问题：

```csharp
// 没有正确维护引用计数时
AssetBundle ab = AssetBundle.LoadFromFile(path);
GameObject prefab = ab.LoadAsset<GameObject>("Player");
ab.Unload(false);  // 卸载 ab，但 prefab 还在内存

// 再次加载同名 ab...
// 如果这时 Instantiate(prefab)，会出现材质/贴图丢失！
// 因为 prefab 依赖的 ab 已经卸载了
```

理解了这个之后，开始认真设计引用计数系统：每个 ab 维护一个计数器，加载时 +1，释放时 -1，计数为 0 时才真正卸载。

---

## UGUI：渲染原理影响优化思路

做 UI 性能优化，如果不理解 UGUI 的渲染原理，就是瞎蒙。

**Rebuild 和 Rebatch 的区别**是关键：

- **Rebuild**：重新生成网格数据（顶点/UV/颜色）。单个 UI 元素的属性变化触发。
- **Rebatch**：重新将同一 Canvas 下的 UI 合并成批次。Canvas 下任何元素的 Rebuild 都会触发整个 Canvas 的 Rebatch。

这意味着：

```
Canvas（包含 100 个 UI 元素）
    其中一个文字每帧更新
    → 每帧触发整个 Canvas 的 Rebatch
    → 100 个元素重新遍历、排序、合并
    → 性能灾难
```

解决方案：**动静分离**——把频繁更新的元素放单独的 Canvas。

这个认知让我在后来的项目里养成了一个习惯：**设计 UI 层级时，先考虑更新频率，再考虑视觉层次**。

---

## 技术深度 vs 技术广度

2019-2020 年，我明显感受到一个问题：

学了很多技术点，但掌握的深度参差不齐。Shader 会写基础效果，但不懂 GPU 管线；AssetBundle 会用，但没有系统设计过完整的资源管理框架；UGUI 优化技巧知道几个，但不懂源码。

这让我开始思考一个问题：**技术深度和技术广度，哪个更重要？**

我后来的答案是：**在游戏开发这个领域，需要一个「T 型」的知识结构**。

- 横：对游戏开发的所有技术方向有基本了解（才能在技术讨论中不陌生）
- 纵：在自己主要负责的 2-3 个方向上有足够深度（才能真正解决问题）

2020 年底，我确定了自己主攻的方向：**客户端架构（资源管理+对象池+消息系统）+ 渲染（Shader+后处理）**。

有了这个方向，学习就变得有重点了。

---

*下一篇：[我的游戏开发之路（四）：2021-2022，系统设计与源码级理解](/posts/游戏开发成长记录-04/)*
