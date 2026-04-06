---
title: Token代币系统与技能资源管理
published: 2026-03-31
description: 深入解析战斗中的 Token 资源系统，理解碰撞触发的代币消耗、Buff 视图管理与技能资源的精确控制
tags: [Unity, 战斗系统, Token系统, 资源管理]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Token代币系统与技能资源管理

在许多动作游戏中，技能的使用需要消耗特殊的"资源"（不仅仅是 MP）。比如剑士每次普通攻击积累"剑气"，积累到3个剑气才能释放大招；或者每次成功格挡获得"格挡Token"，消耗 Token 才能触发反击。

这套"Token"（代币）系统是技能深度的关键，本文深入解析其技术实现。

---

## 第一性原理：为什么需要 Token 系统？

最简单的资源系统是 MP（魔法值）：所有技能共用一个资源池，消耗多少就减多少。

但 Token 系统提供了更丰富的可能：
- **独立资源池**：每种 Token 是独立的，剑气和怒气可以同时存在
- **条件获取**：通过特定操作（格挡、击杀）获得 Token
- **碰撞绑定**：攻击命中时自动消耗对方 Token
- **队伍共享**：某些 Token 是整个队伍共享的，不只是单个角色

---

## Token 的数据表示

Token 本质上是存在 `NumericComponent` 中的数值：

```csharp
// TbToken 配置表中的 Token 配置
public class CToken
{
    public ETokenType Type;  // Token 类型
    public ENumericId HoldNum;  // 当前持有数量（NumericId）
    public ENumericId CostNum;  // 消耗数量（NumericId）
    public ENumericId ActiveNum; // 激活数量（NumericId）
    public bool IsTeamToken;    // 是否是队伍共享 Token
    public bool BInherit;       // 角色切换时是否继承 Token（不清零）
}
```

通过将 Token 绑定到 `NumericId`，Token 数量自动受益于数值系统的所有能力：
- 数值监听器可以响应 Token 变化
- Buff 可以修改 Token 上限
- Token 变化会触发 NumericWatcher

---

## BuffViewComponent：Buff 视图与 Token 管理器

`BuffViewComponent` 不只是 Buff 的视图，它还承担了 Token 的管理职责：

```csharp
public class BuffViewComponent : Entity, IAwake, IDestroy, IReset
{
    public Dictionary<long, BuffViewInfo> allBuffs;  // 所有 Buff 的视图信息
    
    // Token 预修改缓存（Pre/Post 钩子机制）
    public ETokenType PreModifyType;
    public int PreModifyNum;
    
    public static long curHandlerMax = 0;  // 句柄生成器（自增ID）
}
```

### Buff 视图管理

```csharp
// 添加 Buff 视图（UI 上显示 Buff 图标）
public static long AddBuff(this BuffViewComponent self, int id, int level, FP value,
    EBuffViewState newState, EBuffValueState newValueState, PassiveSkillInstance pSkill)
{
    long handler = ++BuffViewComponent.curHandlerMax;  // 生成唯一句柄
    BuffViewInfo newInfo = new BuffViewInfo(id, level, value, newState, newValueState, pSkill);
    self.allBuffs.Add(handler, newInfo);
    
    // 通知 UI：有新 Buff 需要显示
    self.ClientScene().GetComponent<EventDispatcherComponent>()
        .FireEvent(new Evt_AddBuffItem() { owner = self.Parent, handler = handler });
    
    return handler;  // 返回句柄，调用方用于后续操作
}

// 移除 Buff 视图
public static void RemoveBuff(this BuffViewComponent self, long handler)
{
    self.allBuffs.Remove(handler);
    
    // 通知 UI：Buff 消失
    self.ClientScene().GetComponent<EventDispatcherComponent>()
        .FireEvent(new Evt_RemoveBuffItem() { owner = self.Parent, handler = handler });
}
```

Buff 视图与逻辑 Buff 分离：
- **逻辑 Buff**（`SimpleBuff`）：负责实际效果（修改数值、事件监听）
- **视图 Buff**（`BuffViewInfo`）：负责 UI 显示（图标、数值、状态）

分离的好处：UI 层可以用不同方式展示同一个逻辑 Buff（如隐藏某些内部 Buff、合并显示叠加 Buff）。

---

## Token 的增减操作

### 增加 Token

```csharp
public static int ModifyToken(this BuffViewComponent self, ETokenType type, int num, PassiveSkillInstance pSkill)
{
    var conf = CfgManager.tables.TbToken.Get(type);
    NumericComponent numericComp;
    
    // 队伍 Token vs 个人 Token
    if (conf.IsTeamToken)
    {
        var team = teamSys.GetTeamByUnit(self.GetParent<Unit>());
        numericComp = team.GetOrAddComponent<NumericComponent>();
    }
    else
    {
        numericComp = self.GetParent<Unit>().GetOrAddComponent<NumericComponent>();
    }

    if (numericComp != null)
    {
        // Pre 事件：允许 Buff 修改即将增加的数量
        self.ResetPreModifyToken(type, num);
        self.ClientScene().GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_PreTokenModify() { Owner = unit, Type = type, Num = num });
        
        // 实际修改（防止超过上限，取最大值保证不低于0）
        var realModify = TSMath.Max(-numericComp.GetFinalValue(conf.HoldNum), self.PreModifyNum).AsInt();
        numericComp.ModifyPart(conf.HoldNum, ENumericPart.Base, realModify);
        
        // Post 事件：通知 Token 修改完成
        self.ClientScene().GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_OnTokenModify() { Owner = unit, Type = type, Num = realModify, pSkill = pSkill });
        
        // 通知 UI 更新
        self.ClientScene().GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_TokenNumChange() { owner = numericComp.Parent, type = type });

        return realModify;
    }
    return 0;
}
```

`Pre/Post` 钩子设计允许其他 Buff 修改 Token 的实际获取量：

- `Evt_PreTokenModify`：某个 Buff 可以订阅此事件，在 Token 增加前修改 `PreModifyNum`（如"格挡获得2倍Token"的 Buff）
- `Evt_OnTokenModify`：通知所有系统（成就、特效、被动技能）Token 已经修改

### 消耗 Token

```csharp
public static int UseToken(this BuffViewComponent self, ETokenType type, int cost, PassiveSkillInstance pSkill = null)
{
    if (cost <= 0) return 0;
    
    var unit = self.GetParent<Unit>();
    var conf = CfgManager.tables.TbToken.Get(type);
    var numericComp = conf.IsTeamToken 
        ? team.GetOrAddComponent<NumericComponent>() 
        : unit.GetOrAddComponent<NumericComponent>();
    
    // 当前持有量
    int num = numericComp.GetFinalValue(conf.HoldNum).AsInt();
    
    // 实际消耗量（不能超过持有量）
    int activeNum = TSMath.Min(cost, num);
    
    // Pre 事件（可以修改消耗量）
    self.ResetPreModifyToken(type, -activeNum);
    self.ClientScene().GetComponent<EventDispatcherComponent>()
        .FireEvent(new Evt_PreTokenModify() { Owner = unit, Type = type, Num = self.PreModifyNum });
    
    // 实际减少（取最大值防止减为负数）
    var realModify = TSMath.Max(-numericComp.GetFinalValue(conf.HoldNum), self.PreModifyNum).AsInt();
    numericComp.ModifyPart(conf.HoldNum, ENumericPart.Base, realModify);
    
    // 更新激活数量（用于显示"本次消耗了多少"）
    self.ChangeActiveTokenNum(type, -realModify);
    
    // 通知 UI
    self.ClientScene().GetComponent<EventDispatcherComponent>()
        .FireEvent(new Evt_TokenNumChange() { owner = unit, type = type });
    
    return -realModify;  // 返回实际消耗量（正数）
}
```

---

## 碰撞命中时的 Token 消耗

`BuffViewComponent` 监听碰撞命中事件，自动处理 Token 消耗：

```csharp
[EntitySystem]
private static void Awake(this BuffViewComponent self)
{
    // 监听碰撞命中开始事件
    self.GetParent<Unit>().GetComponent<EventDispatcherComponent>()
        .RegisterEvent<Evt_ColliderHitStart>(self.OnColliderHit);
}

public static void OnColliderHit(this BuffViewComponent self, Evt_ColliderHitStart argv)
{
    var colliderComp = argv.Attacker.GetComponent<ColliderComponent>();
    CTokenTemplete tokenDetail = null;
    
    // 根据碰撞类型获取 Token 模板
    switch (argv.ColliderCheckType)
    {
        case EColliderCheckType.Attack:
            if (!colliderComp.AtkTokenInfo.bUsed)
            {
                colliderComp.AtkTokenInfo.bUsed = true;  // 标记为已使用（防止同一次命中消耗多次）
                tokenDetail = self.GetTokenDetail(colliderComp.AtkTokenInfo, EBoxType.Atk);
            }
            break;
        case EColliderCheckType.Doge:
            if (!colliderComp.DodgeTokenInfo.bUsed)
            {
                colliderComp.DodgeTokenInfo.bUsed = true;
                tokenDetail = self.GetTokenDetail(colliderComp.DodgeTokenInfo, EBoxType.Dodge);
            }
            break;
        case EColliderCheckType.Parry:
            if (!colliderComp.ParryTokenInfo.bUsed)
            {
                colliderComp.ParryTokenInfo.bUsed = true;
                tokenDetail = self.GetTokenDetail(colliderComp.ParryTokenInfo, EBoxType.Parry);
            }
            break;
    }
    
    if (tokenDetail == null) return;
    
    // 消耗对方（防御方）的 Token（如攻击命中消耗防御方的护盾Token）
    var defenderBuffViewComp = argv.Defender.GetComponent<BuffViewComponent>();
    foreach (var cost in tokenDetail.CostTokens)
    {
        if (cost.BEnemy)  // BEnemy=true 表示消耗的是对方的 Token
        {
            defenderBuffViewComp.ColliderUseToken(cost.Type);
        }
    }
}
```

`ColliderTokenInfo.bUsed` 防止同一次命中消耗 Token 多次——一次攻击命中多个受击盒时，只消耗一次 Token。

---

## Token 模板系统（TokenTemplete）

```csharp
public class CTokenTemplete
{
    public int ID;
    public EBoxType DefaultBoxType;    // 适用的碰撞盒类型（攻击/格挡/闪避）
    public List<CTokenCost> CostTokens; // 需要消耗的 Token 列表
}

public class CTokenCost
{
    public ETokenType Type;  // Token 类型
    public int Num;          // 消耗数量
    public bool BEnemy;      // true=消耗对方的Token，false=消耗自己的Token
}
```

Token 模板定义了碰撞发生时的 Token 消耗规则。一个模板可以同时定义：
- 消耗自己的 Token（如主动攻击消耗"怒气"）
- 消耗对方的 Token（如命中消耗对方"护盾Token"）

---

## Token 的继承与清零

角色切换时，Token 是否保留由配置决定：

```csharp
public static void TryInhertTokens(this BuffViewComponent self, ColliderTokenInfo info, EBoxType type)
{
    var tokenDetail = self.GetTokenDetail(info, type);
    if (tokenDetail == null) return;
    
    foreach (var cost in tokenDetail.CostTokens)
    {
        var conf = CfgManager.tables.TbToken.Get(cost.Type);
        if (!cost.BEnemy)
        {
            if (!conf.BInherit)
            {
                self.ClearToken(cost.Type);  // 不继承：切换角色时清零
            }
            // 继承：保留给新角色使用
        }
    }
}
```

`BInherit` 配置决定了 Token 的"跨角色性"：
- `BInherit = false`：角色专属 Token，切换后归零（如角色A的"剑气"）
- `BInherit = true`：队伍共享 Token，切换角色后保留（如全队共享的"怒气"）

---

## 设计总结

Token 系统的精妙之处在于：它不是一个独立的新系统，而是**复用现有的数值系统 + 事件系统**：

| 特性 | 实现方式 |
|------|---------|
| Token 存储 | NumericComponent 中的数值 |
| Token 上限 | NumericPart.Max |
| Pre/Post 钩子 | EventDispatcherComponent 事件 |
| 碰撞绑定 | OnColliderHit 事件监听 |
| 队伍/个人 | IsTeamToken 配置区分 |
| 继承/清零 | BInherit 配置 |
| UI 通知 | Evt_TokenNumChange 事件 |

```
碰撞命中发生
    ↓
Evt_ColliderHitStart
    ↓
BuffViewComponent.OnColliderHit
    ↓
读取 TokenTemplete 配置
    ↓
foreach CostToken:
    ├── BEnemy=false → UseToken(自身)
    └── BEnemy=true  → Defender.UseToken(敌方)
         ↓
         Pre事件 → 修改 → Post事件 → UI通知
```

Token 系统让技能资源不再只是 MP，而是根据玩家的战斗行为动态积累和消耗，极大地丰富了战斗策略层次。
