---
title: 我的游戏开发之路（四）：2021-2022，系统设计与源码级理解
published: 2021-07-01
description: "第四五年，从「用好工具」到「设计系统」的跨越：战斗系统架构、对象池深度设计、ILRuntime热更探索、UGUI源码阅读、静态分析工具实践。这一阶段最大的收获是学会了如何思考系统边界与扩展性。"
tags: [成长记录, 游戏开发, 架构设计, 战斗系统, Unity]
category: 成长记录
draft: false
---

> 系列第四篇。2021-2022年，开始承担更多系统设计工作。

## 职责的变化

2021 年，我开始负责完整模块的设计与实现，而不只是「完成需求」。

这两个描述听起来类似，但实际上差距很大：

- **完成需求**：策划说要一个功能，我把它实现出来，能用就行
- **系统设计**：考虑这个功能怎么和其他系统交互，如果需求变了怎么改，下一个类似功能能不能复用这套代码

这个转变让我开始真正思考「架构」是什么。

---

## 战斗系统：我第一次设计「三层架构」

项目里的战斗系统已经有雏形，但随着功能增多，代码开始变得混乱：技能逻辑、AI 逻辑、动画逻辑都搅在一起，改一个功能经常影响其他功能。

我试着整理出一套分层设计：

```
┌──────────────────────────────┐
│    操作决策层（Decision）      │  谁来决定做什么：玩家输入/网络/AI
├──────────────────────────────┤
│    行为策略层（Strategy）      │  具体怎么做：技能策略/追击策略
├──────────────────────────────┤
│    功能组件层（Component）     │  提供能力：移动/动画/碰撞/技能释放
└──────────────────────────────┘
```

**核心原则：下层只提供「机制」，不关心「策略」。**

以寻路组件为例：
- 功能组件层的寻路组件，只负责「按给定路径行走」，不关心「路径从哪里来」
- 行为策略层决定「什么时候寻路、寻什么路」
- 操作决策层决定「现在应该寻路还是攻击」

这样分层之后，当需求变化时（比如 AI 策略变了），只需要改策略层，不影响寻路组件本身。

**这是我第一次切实感受到「架构的价值」**。

---

## 对象池：从「会用」到「设计一个」

之前只是用过对象池，2021 年第一次从零设计一个支持 Unity GameObject 的对象池。

设计过程中遇到的核心问题：

**问题1：对象从哪里来？**

```csharp
// 方案A：提前预热，一次性创建固定数量
// 优：运行时无额外开销
// 缺：不知道需要多少，少了不够用，多了浪费内存

// 方案B：按需创建，用完回收
// 优：按需分配，不浪费
// 缺：第一次使用时有实例化开销（可能在战斗中突然卡一帧）

// 最终：支持「预热数量」配置，允许超出上限动态创建
```

**问题2：回收时对象状态怎么重置？**

```csharp
public interface IPoolable {
    void OnGet();      // 从池中取出时调用：初始化状态
    void OnRelease();  // 归还池时调用：清理状态，关闭子特效等
}
```

如果没有 `OnRelease`，归还的对象可能仍在播放音效、粒子还在发射，下次取出时状态混乱。

**问题3：池中对象无限堆积怎么办？**

```csharp
// 超过最大容量时，多余的对象直接销毁
// 或：定时清理长时间未使用的对象
public bool ShouldRelease(int currentFrame) {
    return currentFrame - lastUsedFrame > MAX_IDLE_FRAMES; // 约10分钟
}
```

这三个问题想清楚了，对象池就能用了。想不清楚，就会在边界情况踩坑。

---

## ILRuntime：探索热更新的另一条路

xLua 热更新的问题是：Lua 和 C# 之间的调用有性能开销，调试工具也不如 C# 方便。

2021 年研究了 ILRuntime，一种「在 C# 中运行 C#」的热更新方案。

优势：
- 热更新代码仍然是 C#，IDE 支持完整
- 不需要 Lua → C# 的绑定层
- 和宿主 C# 交互更顺畅

局限：
- 反射使用有限制，第三方库需要适配
- 性能不如直接运行的 C#（有解释执行开销）
- 项目迁移成本高

最终项目没有迁移到 ILRuntime，但这次研究让我更深入理解了 **CLR 的工作原理**：

- IL（中间语言）是什么
- JIT 和 AOT 的区别（这也是 iOS 不能用某些反射的原因）
- 为什么 IL2CPP 比 Mono 性能更好

这些知识虽然没有直接用到项目里，但让我在讨论技术方案时，能从更底层的角度思考。

---

## 读源码：UGUI 给我的启发

2022 年，项目 UI 性能出了问题，开始认真读 UGUI 源码。

读源码之前，我以为 UI 性能问题的解决方案是「查文档找最佳实践」。读了源码之后，我发现：

**最佳实践不是规则，是从代码逻辑里推导出来的结论。**

举例：「把频繁更新的 UI 放单独 Canvas」这条规则，读了源码之后才真正明白：

```
Graphic.SetDirty()
    → CanvasUpdateRegistry.RegisterForGraphicRebuild()
    → Canvas.willRenderCanvases 事件触发时，遍历所有 dirty 的 Graphic，执行 Rebuild()
    → Rebuild 后，Canvas 标记需要 Rebatch
    → Rebatch：遍历整个 Canvas 层级树，重新计算所有批次
```

Rebatch 遍历的是**整个 Canvas**，不是单个 UI 元素。所以一个 Canvas 里有频繁更新的元素，会导致整个 Canvas 频繁 Rebatch。

这个逻辑从源码里读出来，就永远不会忘，也不会在新项目里犯同样的错误。

**读源码的方法**：
1. 从最常用的入口（如 `Text.text = value`）开始，跟调用链
2. 在关键节点打断点验证自己的理解
3. 用 Frame Debugger 对照源码，理解渲染流程

---

## Roslyn 静态分析：工具思维的萌芽

2021 年做了一个小工具：用 Roslyn（C# 编译器 API）扫描项目代码，检测特定的不规范用法。

比如：
- 检测是否有没有取消注册的事件监听
- 检测 `Resources.Load` 的使用（项目规定不允许直接用 Resources 加载）
- 检测过长的函数（超过 100 行的函数提示重构）

```csharp
// Roslyn 分析示例：检测 Resources.Load 调用
public class ResourcesLoadAnalyzer : DiagnosticAnalyzer {
    public override void Initialize(AnalysisContext context) {
        context.RegisterSyntaxNodeAction(
            AnalyzeInvocation,
            SyntaxKind.InvocationExpression
        );
    }
    
    private void AnalyzeInvocation(SyntaxNodeAnalysisContext context) {
        var invocation = (InvocationExpressionSyntax)context.Node;
        var symbol = context.SemanticModel.GetSymbolInfo(invocation).Symbol;
        if (symbol?.ToString().StartsWith("UnityEngine.Resources.Load") == true) {
            context.ReportDiagnostic(Diagnostic.Create(Rule, invocation.GetLocation()));
        }
    }
}
```

这个工具本身的价值是帮助团队维持代码规范。但更大的收获是**「工具思维」**：

当发现一类问题反复出现时，不只是告诉人「别这样写」，而是做一个工具让这类问题在编译期就暴露出来。

---

## 这两年最重要的认知

**系统设计的本质，是管理「变化」。**

功能会变，需求会变，技术栈会变，团队成员会变。好的系统设计，是让这些变化的影响范围尽可能小。

具体到代码层面：

- 高内聚低耦合（不是口号，是减少影响范围的手段）
- 接口而非实现（依赖接口，不依赖具体类，方便替换）
- 单一职责（一个类只做一件事，改动时知道去哪里找）

这些原则，在前两年看起来像「书上的规范」。到了这个阶段，开始真正理解它们的价值。

---

*下一篇：[我的游戏开发之路（五）：2023-2025，从工程师到团队负责人](/posts/游戏开发成长记录-05/)*
