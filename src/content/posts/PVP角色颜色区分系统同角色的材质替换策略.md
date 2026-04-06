---
title: PVP 角色颜色区分系统：同角色的材质替换策略
published: 2026-03-31
description: 解析 PVP 双方同角色时的材质替换系统，包含"2P颜色"的资源命名规范、Cutscene 等待 Actor 就绪的异步处理、以及标签驱动的材质替换定位机制。
tags: [Unity, 角色材质, PVP系统, 渲染系统]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# PVP 角色颜色区分系统：同角色的材质替换策略

## 前言

在 PVP 对战中，双方可能选择了同一个角色——"爱豆A" vs "爱豆A"。为了让玩家能区分己方和对方，对手的角色需要换成另一种颜色方案（通常称为"2P 颜色"，来源于街机游戏的双人模式惯例）。

本文通过分析 `ChangeEnemyMatEvent` 和 `MaterialUtil`，带你理解这套颜色区分系统的完整实现。

---

## 一、触发条件：同角色才需要换色

```csharp
public static bool CheckChangeMat(this ChangeMatComponent self, Unit unit, bool isEnemy)
{
    if (!self.CharacterCountDic.ContainsKey(unit.ConfigId))
        self.CharacterCountDic[unit.ConfigId] = new HashSet<Unit>();

    self.CharacterCountDic[unit.ConfigId].Add(unit);

    // 同一配置 ID 出现了 > 1 个，且当前是敌方 → 需要换色
    return self.CharacterCountDic[unit.ConfigId].Count > 1 && isEnemy;
}
```

注释 `"仅一个星瞳时，为红色；如果有两个，则我方红色，对方白色"` 描述了这个游戏的具体规则：
- 默认颜色（己方）：红色主题
- 2P 颜色（同角色对方）：白色主题

`HashSet<Unit>` 存储所有持有同一 `ConfigId` 的单位。当数量 > 1 且当前单位是敌方，就需要换色。

**`HashSet` 的选择：**

用 `HashSet` 而不是 `List` 是为了防止同一个 Unit 被重复添加（如角色上场后再次触发事件）。`HashSet.Add` 对已存在的元素静默失败，不会增加计数。

---

## 二、材质资源的命名规范

```csharp
string GetReplaceMatName(int configId, string suffix = "2P")
{
    var midName = GetPrefabMidName(configId);
    return ZString.Format("Mat/IMat_{0}_Body_{1}.mat", midName, suffix);
}

// 从 Prefab 路径提取角色名
// "Characters/Char_A.prefab" → "Char_A"
string ExtractName(string input)
{
    const string prefix = "Characters/";
    const string suffix = ".prefab";

    int startIndex = prefix.Length;
    int endIndex = input.Length - suffix.Length;
    return input.Substring(startIndex, endIndex - startIndex);
}
```

示例：
- 角色配置 Prefab 路径：`"Characters/CHAR_BaiShengYao.prefab"`
- 提取中间名：`"CHAR_BaiShengYao"`
- 生成材质路径：`"Mat/IMat_CHAR_BaiShengYao_Body_2P.mat"`

**命名规范的重要性：**

`"Mat/IMat_{角色名}_Body_{版本}.mat"` 是整个团队约定好的资源命名规则。只要美术按照这个规则命名，程序就能通过字符串拼接自动找到对应的材质。

这种"约定优于配置"的设计减少了大量的配置表维护工作——不需要在配置表里为每个角色手动填写 2P 材质路径。

---

## 三、资源存在性验证

```csharp
var isExist = ResManager.AssetExist(replaceMatName);
if (!isExist)
{
    Log.Info(ZString.Format("ChangeEnemyMatEvent: 材质不存在: {0}", replaceMatName));
    return;  // 不添加到 lstRes，不触发材质替换
}

lstRes.Add(replaceMatName);
```

并非所有角色都有 2P 材质（比如某些只在 PVE 出现的角色）。`AssetExist` 检查资源是否存在，不存在时 `Log.Info`（不是 Error，因为这是预期的情况）并跳过。

`GetDependentRes` 只有在确认资源存在时才把它添加到 `lstRes`，`EventWithRes` 框架随后只加载有效的资源。

---

## 四、Cutscene 中的材质替换：等待 Actor 就绪

Cutscene（过场动画）中的角色可能需要异步加载才就绪。材质替换需要等待角色加载完成：

```csharp
if (args.CutsceneGroup != null)
{
    var group = args.CutsceneGroup as CharacterActorGroup;
    if (group.actor == null)
    {
        // 轮询等待 actor 就绪（最长 10 秒）
        int timeOut  = 10 * 1000;
        int time     = 0;
        int interval = 10;  // 每 10ms 检查一次
        while (group.actor == null && time < timeOut)
        {
            await TimerComponent.Instance.WaitAsync(interval);
            time += interval;
        }
    }
    // actor 就绪后执行材质替换
    if (group.actor != null)
        matTransfer.ChangeCharMaterial(to2P);
}
```

**轮询等待的设计分析：**

这段代码用轮询（每 10ms 检查）而非事件回调，是因为 Cutscene 框架没有提供"Actor 加载完成"的回调接口。轮询是实际开发中常见的"次优方案"——当理想方案（事件回调）不可用时，轮询加超时是相对安全的替代。

**10ms 间隔 + 10 秒超时：**

- 10ms 间隔：足够频繁，不会让用户感知明显延迟
- 10 秒超时：防止死循环，超时后静默放弃（不崩溃）

---

## 五、标签驱动的过场材质替换

```csharp
public static async ETTask CutsceneChangeMaterial(Cutscene cutscene, Unit unit, bool is2P)
{
    CharacterActorGroup firstCharacterGroup = null;
    bool hasSelf = false;

    foreach (CutsceneGroup group in cutscene.groups)
    {
        var characterActorGroup = group as CharacterActorGroup;
        if (characterActorGroup == null) continue;

        if (firstCharacterGroup == null)
            firstCharacterGroup = characterActorGroup;  // 记录第一个角色轨道

        if (characterActorGroup.MaterialChangeTag == EMaterialChangeTag.Self)
        {
            await ChangeGroupMaterial(characterActorGroup, unit, is2P);  // 有 Self 标记，精确替换
            hasSelf = true;
        }
    }

    // 没有 Self 标记时，默认替换第一个角色轨道
    if (!hasSelf && firstCharacterGroup != null)
        await ChangeGroupMaterial(firstCharacterGroup, unit, is2P);
}
```

**`EMaterialChangeTag.Self` 的设计：**

Cutscene 可能包含多个角色轨道（CharacterActorGroup）。`EMaterialChangeTag.Self` 是美术在 Timeline 编辑器中打的标签，表示"这个轨道是施法者自身"。

当系统找到有 `Self` 标签的轨道时，精确地对该轨道的角色换色；没有标签时，回退到"默认换第一个轨道"的策略。

这种"标签 → 精确定位，无标签 → 智能推断"的模式是实用主义工程的体现：为简单情况提供自动推断，为复杂情况提供精确控制。

---

## 六、双重材质替换路径

```csharp
// 路径 1：战斗中的实时替换（通过 GameObjectComponent）
if (args.Unit != null)
{
    var goComp = args.Unit.GetComponent<GameObjectComponent>();
    goComp?.SetCharMaterial(to2P);
}

// 路径 2：Cutscene 中的替换（通过 CharMateialTransfer）
if (go != null)
{
    var matTransfer = CharMateialTransfer.GetMatTransferComponent(go);
    matTransfer?.ChangeCharMaterial(to2P);
}
```

**为什么有两条路径？**

- **战斗路径**：角色在 ECS 管理下，通过 `GameObjectComponent` 找到 `GameObject`，再通过挂在其上的 `CharMateialTransfer` 组件修改材质
- **Cutscene 路径**：Cutscene 中的角色可能是独立实例化的（`group.actor`），不在 ECS 管理范围内，直接从 `actor` 查找 `CharMateialTransfer` 组件

**`to2P` 变量的语义：**

```csharp
bool to2P = args.IsEnemy && isChange;
```

只有"是敌方" **且** "需要换色"（同角色出现两次）才换成 2P 颜色。否则即使是敌方，如果是唯一的该角色，也显示正常颜色。

---

## 七、颜色恢复

```csharp
/// <summary>
/// 改变 cutscene 中的 actor 的材质，在 cutscene 销毁时，会自动恢复到原来的材质(1p)
/// </summary>
```

注释说明了材质恢复机制：Cutscene 销毁时，`CharMateialTransfer` 自动恢复为 1P（默认）颜色。

这保证了过场动画中临时改变的颜色，不会"污染"战斗中的角色状态——Cutscene 前是什么颜色，Cutscene 结束后还是什么颜色。

---

## 八、总结

| 设计要点 | 解决的问题 |
|---------|-----------|
| HashSet 计数 | 精确检测"同一角色出现 > 1 次" |
| 命名规范生成路径 | 无需配置表，约定即文档 |
| 资源存在性验证 | 没有 2P 材质时优雅降级 |
| 轮询等待 Actor | Cutscene 异步加载期间的安全等待 |
| 标签精确定位 | Cutscene 中多轨道的精确材质控制 |
| 双路径替换 | 统一 ECS 单位和 Cutscene Actor 的处理 |

这套颜色区分系统是"约定优于配置"和"事件驱动资源加载"两种设计思想的综合体现。对于刚入行的同学，理解材质替换的资源路径命名规范，是工程化开发的第一课。
