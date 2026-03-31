---
title: 属性变更检查器模式——用Scope和Checker批量处理养成数据更新
published: 2026-03-31
description: 深入解析养成系统中角色属性变更的检查器模式，用IDisposable Scope实现原子性的批量属性更新与事件通知
tags: [Unity, 设计模式, 养成系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 属性变更检查器模式——用Scope和Checker批量处理养成数据更新

养成游戏中，服务器会频繁推送角色属性更新通知：角色的位置变了、压力值变了、队长状态变了……如果每个变化都单独处理，会导致大量零散的事件发布，UI频繁刷新，性能差且代码难以维护。

VGame项目用**Checker + Scope**的模式解决这个问题：所有属性变更先收集到Checker里，批量处理完后，用一次Notify统一发出所有变更事件。

## 一、核心设计：Checker负责单项属性的变更检测

每种属性变更都有独立的Checker类：

```csharp
// 角色队长变更检查器
public class CultivationCharacterLeaderChecker : 
    CultivationCharacterPropertyChecker<CultivationCharacterLeaderChangeInfo, Evt_CultivationCharacterLeaderChanged>
{
    public override void CheckAndApply(
        CultivationCharacterData prevCharacter, 
        ZoneCultivateNotifyCharacterInfoDetailInfo nextCharacter)
    {
        // 判断服务器推送数据里是否包含队长字段
        if (!nextCharacter.HasIsLeader) return;
        
        var nextIsLeader = nextCharacter.IsLeader != 0;
        
        // 记录变更信息（变更前后的数据）
        ChangeInfos.Add(new CultivationCharacterLeaderChangeInfo
        {
            CharacterIP = prevCharacter.IP,
            StoryCharacterID = prevCharacter.StoryCharacterID,
            Position = prevCharacter.Position,
            PrevLeaderFlag = prevCharacter.IsLeader,  // 变更前
            NextLeaderFlag = nextIsLeader,             // 变更后
        });
        
        // 立即应用到本地数据
        prevCharacter.IsLeader = nextIsLeader;
        // 同步到战斗数据层
        Comp.Dungeon().SetLeaderFlag(prevCharacter.IP, nextIsLeader, true);
    }
}

// 角色压力变更检查器
public class CultivationCharacterPressureChecker :
    CultivationCharacterPropertyChecker<CultivationCharacterPressureChangeInfo, Evt_CultivationCharacterPressureChanged>
{
    public override void CheckAndApply(
        CultivationCharacterData prevCharacter,
        ZoneCultivateNotifyCharacterInfoDetailInfo nextCharacter)
    {
        if (!nextCharacter.HasPressure) return;
        
        ChangeInfos.Add(new CultivationCharacterPressureChangeInfo
        {
            PrevPressure = prevCharacter.Pressure,
            NextPressure = nextCharacter.Pressure,
            // ... 其他上下文信息
        });
        
        prevCharacter.Pressure = nextCharacter.Pressure;
    }
}

// 角色属性（战斗属性：攻击力、防御力等）变更检查器
public class CultivationCharacterAttributeChecker :
    CultivationCharacterPropertyChecker<CultivationCharacterAttributeChangeInfo, Evt_CultivationCharacterAttributesChanged>
{
    public override void CheckAndApply(
        CultivationCharacterData prevCharacter,
        ZoneCultivateNotifyCharacterInfoDetailInfo nextCharacter)
    {
        if (!nextCharacter.HasAttr || nextCharacter.AttrList == null) return;
        
        var nextAttributes = ServerDataConverter.ToMap(nextCharacter.AttrList);
        ChangeInfos.Add(new CultivationCharacterAttributeChangeInfo
        {
            PrevAttributes = prevCharacter.Attributes,
            NextAttributes = nextAttributes,
        });
        
        prevCharacter.Attributes = nextAttributes;
        Comp.Dungeon().SetAttributes(prevCharacter.IP, nextAttributes, true);
    }
}
```

所有Checker都继承自同一个泛型基类：
- `TChangeInfo`：记录变更前后数据的DTO（Data Transfer Object）
- `TEvent`：变更完成后要发布的事件类型

## 二、形态变更检查器——最复杂的案例

角色形态变更（正常/离队）有特殊的副作用：

```csharp
public class CultivationCharacterFormChecker : 
    CultivationCharacterPropertyChecker<CultivationCharacterFormChangeInfo, Evt_CultivationCharacterFormChanged>,
    ICultivationEffectInspectorBinder // 需要校验状态效果
{
    public ICultivationEffectInspector EffectInspector { get; set; }
    
    public override void CheckAndApply(
        CultivationCharacterData prevCharacter,
        ZoneCultivateNotifyCharacterInfoDetailInfo nextCharacter)
    {
        if (!nextCharacter.HasFormInTeam) return;
        
        var nextFormInTeam = (EFormInTeam)nextCharacter.FormInTeam;
        ChangeInfos.Add(new CultivationCharacterFormChangeInfo
        {
            PrevForm = prevCharacter.FormInTeam,
            NextForm = nextFormInTeam,
        });
        
        // 特殊逻辑：角色离队或归队时，需要重新校验状态加成
        if (EffectInspector != null && ShouldValidateScheduleBonusStatus(prevCharacter.FormInTeam, nextFormInTeam))
        {
            foreach (var status in prevCharacter.Statuses)
                EffectInspector.Validate(CultivationEffectSourceType.CharacterStatus, prevCharacter.IP, status.EffectList);
        }
        
        prevCharacter.FormInTeam = nextFormInTeam;
        Comp.Dungeon().SetForm(prevCharacter.IP, nextFormInTeam, true);
    }
    
    private bool ShouldValidateScheduleBonusStatus(EFormInTeam prevForm, EFormInTeam nextForm)
    {
        // 只有"正常→离队"或"离队→正常"时才需要校验
        return (prevForm == EFormInTeam.Normal && nextForm == EFormInTeam.Exit) ||
               (prevForm == EFormInTeam.Exit && nextForm == EFormInTeam.Normal);
    }
}
```

**ICultivationEffectInspectorBinder接口的妙用**：

形态变更时需要一个`EffectInspector`来校验状态效果。但不是所有Checker都需要这个对象——只有FormChecker需要。

通过`ICultivationEffectInspectorBinder`接口标识"我需要EffectInspector"，Scope在初始化时自动识别并注入：

```csharp
// 在Scope.Prepare()里
if (checker is ICultivationEffectInspectorBinder binder)
    binder.EffectInspector = _effectInspector;
```

这是依赖注入的一种变体：通过接口标记来实现可选的依赖注入，不需要每个Checker都有一个EffectInspector字段。

## 三、Scope模式：IDisposable包裹的原子操作

```csharp
public class CultivationCharacterPropertyChangeCheckScope : IDisposable
{
    private readonly CultivationComponent _comp;
    private readonly ECultivationCharacterPropertyType _properties;
    private readonly CultivationEffectInspector _effectInspector;
    
    // 缓存操作前正在编辑的角色（用于操作后恢复）
    private IPCharacterEnum _cacheEditingIP;
    private int _cacheEditingPosition;
    
    public CultivationCharacterPropertyChangeCheckScope(
        CultivationComponent comp, 
        CultivationEffectInspector effectInspector,
        ECultivationCharacterPropertyType properties = ECultivationCharacterPropertyType.All)
    {
        _comp = comp;
        _properties = properties;
        _effectInspector = effectInspector;
        Prepare();
    }
    
    public void Prepare()
    {
        // 1. 缓存当前聚焦角色（批量更新后可能需要重新定位）
        _cacheEditingIP = _comp.GetEditingCharacter()?.IP ?? IPCharacterEnum.None;
        _cacheEditingPosition = _comp.GetEditingCharacterPosition();
        
        // 2. 对所有匹配的Checker执行Prepare（清空上次缓存的变更）
        foreach (var (type, checker) in _comp.GetCharacterCheckers())
        {
            if (!_properties.HasFlag((ECultivationCharacterPropertyType)type)) continue;
            
            checker.Prepare();
            
            // 3. 注入EffectInspector（只给需要的Checker）
            if (checker is ICultivationEffectInspectorBinder binder)
                binder.EffectInspector = _effectInspector;
        }
    }
    
    public void CheckAndApply(
        CultivationCharacterData prevCharacter, 
        ZoneCultivateNotifyCharacterInfoDetailInfo nextCharacter)
    {
        // 遍历所有Checker，逐一检查这个角色的每项属性变化
        foreach (var (type, checker) in _comp.GetCharacterCheckers())
        {
            if (_properties.HasFlag((ECultivationCharacterPropertyType)type))
                checker.CheckAndApply(prevCharacter, nextCharacter);
        }
    }
    
    public void Notify()
    {
        // 批量发出所有Checker收集到的变更事件
        foreach (var (type, checker) in _comp.GetCharacterCheckers())
        {
            if (_properties.HasFlag((ECultivationCharacterPropertyType)type))
                checker.Notify();
        }
    }
    
    public void Dispose()
    {
        Notify(); // Dispose时自动发出所有变更通知
        
        // 校验批量更新后聚焦角色的有效性
        _comp.ValidateEditingCharacter(_cacheEditingIP, _cacheEditingPosition);
    }
}
```

使用方式：

```csharp
// 收到服务器推送的角色更新
void OnServerNotify(ZoneCultivateNotifyInfo notify)
{
    // using语句：Scope构造时Prepare，析构时自动Notify
    using var scope = new CultivationCharacterPropertyChangeCheckScope(
        cultivationComp, effectInspector);
    
    // 批量检查所有角色的所有属性变化
    foreach (var character in notify.Characters)
    {
        var prevCharacter = cultivationComp.GetCharacterByIP(character.IP);
        scope.CheckAndApply(prevCharacter, character);
    }
    
    // using块结束时自动调用Dispose → Notify
    // 所有变更事件集中发出一次，UI只刷新一次
}
```

## 四、ECultivationCharacterPropertyType枚举标志

```csharp
[Flags]
public enum ECultivationCharacterPropertyType
{
    Leader     = 1 << 0,  // 队长状态
    Position   = 1 << 1,  // 站位
    Form       = 1 << 2,  // 形态
    Pressure   = 1 << 3,  // 压力值
    Attributes = 1 << 4,  // 战斗属性
    Speciality = 1 << 5,  // 专长
    // ...
    All = ~0,             // 所有属性
}
```

使用`[Flags]`特性，可以用位运算组合检查范围：

```csharp
// 只检查位置和形态的变化，不检查其他属性
var scope = new CultivationCharacterPropertyChangeCheckScope(
    comp, effectInspector, 
    ECultivationCharacterPropertyType.Position | ECultivationCharacterPropertyType.Form);
```

这允许在不同的业务场景下，精确控制需要检查哪些属性，避免不必要的计算。

## 五、变更DTO的设计价值

每个Checker的`ChangeInfos`列表里存储的是完整的DTO（同时包含变更前和变更后的数据）：

```csharp
public class CultivationCharacterLeaderChangeInfo
{
    public IPCharacterEnum CharacterIP { get; set; }
    public int StoryCharacterID { get; set; }
    public int Position { get; set; }
    public bool PrevLeaderFlag { get; set; }  // ← 变更前
    public bool NextLeaderFlag { get; set; }  // ← 变更后
}
```

保存变更前的数据有重要价值：
1. **Undo/Redo**：如果需要撤销操作，知道"之前是什么"
2. **动画决策**：UI看到"队长从位置2变成了位置1"，可以播放一个从2到1移动的动画
3. **埋点上报**：事件发生时记录完整的上下文，便于数据分析

## 六、总结

这套Checker + Scope模式解决了"批量属性更新"场景下的三个核心问题：

| 问题 | 解决方案 |
|------|---------|
| 频繁刷新UI | Scope延迟到Dispose时批量发出事件 |
| 特殊属性有副作用 | Checker实现自定义接口来接收额外依赖 |
| 部分更新 | 位运算Flags控制需要检查的属性子集 |

对新手来说，`IDisposable + using`的**RAII（资源获取即初始化）**模式在游戏开发中非常有用：任何需要"成对操作"（准备-清理、开始-结束、锁定-解锁）的场景，都可以用IDisposable来保证配对，即使发生异常也能正确清理。
