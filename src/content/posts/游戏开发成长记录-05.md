---
title: 我的游戏开发之路（五）：2023-2025，从工程师到团队负责人
published: 2023-09-01
description: "第六到九年：技术广度继续扩展（DOTS/Addressables/AI工具/静态代码分析），同时开始承担更大规模系统的架构（公会战/GVG联赛/聊天语音系统），并逐渐从「写代码」转向「让团队写好代码」。"
tags: [成长记录, 游戏开发, 架构设计, 团队管理, Unity]
category: 成长记录
draft: false
---

> 系列第五篇，也是目前为止的终章。2023-2025年，角色开始从纯技术执行者向团队技术负责人转变。

## 技术广度的扩展期

2023 年是我主动拓宽技术视野的一年。

不是因为项目强制要求，而是感受到了一种「天花板感」：熟悉的技术栈已经不给我带来学习的兴奋感了，需要主动找新的输入。

### DOTS：数据驱动的思维革命

Unity DOTS（Data-Oriented Technology Stack）让我第一次认真思考**数据布局对性能的影响**。

传统的面向对象：

```
Enemy 对象 1: [position][health][speed][animation][AI_state][...] // 数据分散
Enemy 对象 2: [position][health][speed][animation][AI_state][...]
...
Enemy 对象 N: [position][health][speed][animation][AI_state][...]
```

每次更新位置，CPU 需要跳跃式访问内存，缓存命中率极低。

ECS 的数据布局：

```
Positions:   [pos1][pos2][pos3]...[posN]  // 同类数据连续存储
Velocities:  [vel1][vel2][vel3]...[velN]
Health:      [hp1][hp2][hp3]...[hpN]
```

更新所有单位位置时，CPU 可以顺序读取 Positions 数组，缓存命中率极高，SIMD 指令可以批量处理。

**这个思维——「数据的内存布局影响程序性能」——即使不用 DOTS，也改变了我设计数据结构的方式。**

### Addressables：资源管理的「现代化」

和 AssetBundle 相比，Addressables 把大量工程化工作封装了：

```csharp
// 旧方式：手动管理 ab 路径、引用计数
AssetBundle ab = AssetBundle.LoadFromFile(path);
GameObject prefab = ab.LoadAsset<GameObject>("Player");
// 用完了？ab.Unload(false)？什么时候卸载？

// Addressables 方式
var handle = Addressables.LoadAssetAsync<GameObject>("Player");
await handle.Task;
GameObject prefab = handle.Result;
// 用完了：
Addressables.Release(handle); // 引用计数自动管理
```

更重要的是，Addressables 支持**远程加载**和**资源标签分组**，让热更新资源管理变得可配置而不是硬编码。

### AI 编程工具：效率的量级提升

2023 年开始认真用 AI 辅助编程（Codeium、GitHub Copilot 等）。

有些人担心 AI 会「替代程序员」。在我实际使用之后的感受是：

**AI 是一个极其优秀的「初稿生成器」，但决定代码质量的仍然是工程师的判断力。**

AI 适合：
- 快速生成样板代码（序列化、工具函数）
- 语法提示、自动补全
- 把思路转化为初版代码，再由自己优化

AI 不适合：
- 设计系统架构（它不知道你的项目上下文）
- 判断代码是否符合现有系统的规范
- 解决具体的、项目特有的 bug

用了 AI 工具之后，我的工作效率大约提升了 30-40%，主要体现在「不需要重复写样板代码」这件事上。

---

## 2024年：负责大型系统的架构与开发

2024 年是工作内容最复杂的一年。

### 公会战 / GVG 联赛系统

这是我负责过最复杂的一个系统：

- 跨服匹配（不同服务器的公会之间对战）
- 分组制（最多 8 个公会一组）
- 实时战报（比赛进行中展示各队积分、击杀数据）
- 历史记录（赛季结算、历史数据查询）

技术挑战：

**1. 协议版本对齐**

连接不同版本的测试服务器时，proto 文件中的版本号要手动对齐，否则握手失败：

```protobuf
enum MSG_Version_Type {
    MSG_VERSION_NONE  = 0;
    MSG_VERSION_PROTO = 20240909;  // 必须和服务器版本一致
}
```

**2. 数据同步与表现分离**

UI 数据更新是同步的，但 UI 资源加载是异步的。这两件事要在代码层面清晰分离：

```lua
-- 数据层：同步，即时处理
function GVG_DataManager:OnReceiveRankData(rankInfo)
    self.m_rankData = rankInfo  -- 立即更新数据
    LC_Event:DispatchEvent(GVG_EventId.RankDataUpdated)
end

-- 表现层：异步，按需加载
function GVG_RankUI:OnRankDataUpdated()
    -- 数据已经准备好了，但头像资源可能还没加载
    self:LoadAvatarsAsync(self.m_dataManager.m_rankData)
end
```

**3. 帧分割更新**

战斗中大量单位同时 Update 会导致单帧卡顿。用取模分帧：

```lua
local kMaxFrameSplitCount = 4
local kFrameCount = frameCount % kMaxFrameSplitCount

for uid, unit in pairs(m_unitMap) do
    if unit:IsLocalPlayer() or (uid % kMaxFrameSplitCount == kFrameCount) then
        unit:UpdateLogic(dt)
    end
end
-- 每帧只更新 1/4 的单位，但玩家自己的单位每帧都更新（保证手感）
```

### 聊天语音系统

集成第三方语音 SDK（YouMe）到游戏内聊天系统。

最难的部分不是 SDK 接入，而是**线程安全**：SDK 的回调在子线程，但 Unity 的 API 只能在主线程调用。

```csharp
// SDK 回调：子线程
void OnAudioMessageReceived(AudioMessage msg) {
    // ❌ 直接调用 Unity API 会崩溃
    // ShowAudioMessage(msg);
    
    // ✅ 派发到主线程
    UnityMainThreadDispatcher.Instance.Enqueue(() => {
        ShowAudioMessage(msg);
    });
}
```

`UnityMainThreadDispatcher` 是一个挂在场景中的 MonoBehaviour，用 `ConcurrentQueue` 收集跨线程任务，在 `Update()` 中逐个执行。

这个模式后来在很多需要多线程的场景里都用到了。

---

## 从「写代码」到「让团队写好代码」

这个转变是悄然发生的，有一天我意识到：**我花在「如何让团队更高效」上的时间，开始多于「自己写代码」的时间。**

### 代码评审

开始认真做 Code Review，发现了很多之前没意识到的问题：

- 同一个逻辑在三个地方各写了一遍（没有抽象）
- 一个函数做了五件不相关的事（违反单一职责）
- 异常处理完全缺失（任何地方出错整个系统崩溃）

Code Review 不只是找 bug，更是在团队里**传播「什么是好代码」的认知**。

### 技术决策

开始参与技术选型讨论。这时候积累的技术广度开始发挥作用：

- 讨论热更新方案时，能对比 xLua、ILRuntime、HybridCLR 的优劣
- 讨论网络架构时，能从帧同步/状态同步的底层逻辑出发分析利弊
- 讨论性能优化时，能从内存布局、缓存命中、GC 等角度分析根因

**技术广度不是为了炫耀，是为了在做决策时能从更多角度思考。**

### 新人培养

开始带新人。这是对自己技术理解的最好检验：

**能把一个技术点讲清楚，才证明真正理解了它。**

很多时候在给新人解释时，才发现自己某些「理解」其实是模糊的，逼自己把它想清楚。

---

## 回头看这九年

从大三到现在，如果让我总结最重要的几件事：

**1. 把每次踩坑都变成文档**

这个博客里的很多内容，都是踩坑之后记下来的。正是这些记录，让我不会在同一个地方踩两次坑，也帮助了后来遇到同样问题的人。

**2. 主动找难题，不要在舒适区待太久**

每次感觉「这个东西已经熟了」的时候，就该找新的挑战了。不是为了追求「大而全」，而是成长需要不适感。

**3. 技术是手段，不是目的**

游戏开发的目的是做出让玩家喜欢的游戏。技术是实现这个目的的手段。

这听起来是废话，但在实际工作中很容易忘记：花两周做一个「技术上很优雅」但没有解决实际问题的架构，不如花两天做一个「技术上凑合」但真正解决问题的方案。

**4. 把自己的经验写出来**

给新人、给同行，也给未来的自己。

写作是整理思路的过程，很多在脑子里模糊的认知，写出来才会变清晰。

---

## 如果你也在这条路上

这个博客里的内容，是我这些年学习和实践的记录。

有些文章写于刚毕业时，可能有错误或者不够深入；有些文章写于最近，代表了我现阶段的认知。

游戏开发是一个技术栈极宽的领域，没有人能精通所有方向。我能做的，是把自己走过的路记录下来，希望能让后来的人少走一些弯路。

**欢迎交流，无论是技术问题还是职业建议。**

---

*← 上一篇：[我的游戏开发之路（四）：2021-2022，系统设计与源码级理解](/posts/游戏开发成长记录-04/)*
