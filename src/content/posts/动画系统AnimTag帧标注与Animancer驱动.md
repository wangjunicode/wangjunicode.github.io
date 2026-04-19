---
title: 动画系统设计：AnimTag帧标注与Animancer驱动
published: 2024-01-01
description: "动画系统设计：AnimTag帧标注与Animancer驱动 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 渲染管线
draft: false
encryptedKey: henhaoji123
---

# 动画系统设计：AnimTag帧标注与Animancer驱动

## 1. 系统概述

本项目动画系统采用 **Animancer**（Unity 高性能动画插件）作为底层驱动，结合自研的 **AnimTag（动画帧标注）** 系统，实现精确的帧级别状态判断（如是否处于受击无敌帧、技能释放区间等）。

**系统架构：**

```
配置层                        运行时
TbAnimation（动画ID→Clip路径）
TbAnimationOverride（角色覆盖） → CAnimationPrefix（动画路径解析）
AnimationMeta（JSON帧标注）    → AnimTag（Tag激活判断）
                                    ↓
                              Animancer 播放
                                    ↓
                          每帧查询当前时间的 AnimTag
                                    ↓
                          FSM/Skill/Hurt系统使用 Tag 判断逻辑
```

---

## 2. AnimTag 帧标注系统

### 2.1 AnimTag 数据结构

```csharp
// 位置：Hotfix/Battle/Model/GamePlay/Luban/Ext/CAnimationEx.cs

// 动画片段内的一段时间区间，对应某个语义标签
[Serializable]
public class AnimTag
{
    public FP StartTime;    // 区间开始时间（定点数，单位：秒）
    public FP EndTime;      // 区间结束时间
    public EAnimTag Tag;    // 语义标签（枚举）
    public FP AnimLength;   // 整个动画片段的总时长
    
    // 帧数属性（方便编辑器显示/编辑）
    public int StartFrame
    {
        get => (StartTime / EngineDefine.fixedDeltaTime_Orignal).AsInt();
        set => StartTime = (value * EngineDefine.fixedDeltaTime_Orignal).AsInt();
    }
    
    public int EndFrame
    {
        get => (EndTime / EngineDefine.fixedDeltaTime_Orignal).AsInt();
        set => EndTime = (value * EngineDefine.fixedDeltaTime_Orignal).AsInt();
    }
    
    // 判断当前时间是否处于此区间内（含首尾帧的特殊处理）
    public bool IsActive(FP time)
    {
        // 正常区间检测
        bool inRange = StartTime <= time && time <= EndTime;
        // 第一帧（StartTime <= 0）特殊：任何 time <= 0 都激活
        bool isFirst = StartTime <= 0 && time <= 0;
        // 最后帧（EndTime >= AnimLength）特殊：到达动画末尾都激活
        bool isLast = EndTime >= AnimLength && time >= AnimLength;
        
        return inRange || isFirst || isLast;
    }
}
```

### 2.2 EAnimTag 枚举语义

```csharp
// 动画帧标注的语义枚举
// 按 EAnimTagType 分段（TagMod = 100，State类型为 0-99，Pose类型为 100-199）
public enum EAnimTag
{
    None = -1,
    
    // State 类（EAnimTagType.State）：当前处于什么状态
    S_Idle = 0,          // 待机
    S_Run = 1,           // 跑步
    S_Attack = 2,        // 普攻
    S_Skill = 3,         // 技能
    S_Hit = 4,           // 受击
    S_Invincible = 5,    // 无敌帧（闪避/受击无敌）
    S_Break = 6,         // 破防
    S_Dead = 7,          // 死亡
    
    // Pose 类（EAnimTagType.Pose）：当前姿势方向
    P_Left = 100,        // 向左姿势
    P_Right = 101,       // 向右姿势
    P_Forward = 102,     // 向前姿势
}

public enum EAnimTagType
{
    State = 0,    // 状态类
    Pose  = 1,    // 姿势类
    TagMod = 100, // 分段间距
}
```

### 2.3 AnimationMeta：一个动画片段的所有 Tag

```csharp
// 一个动画片段（AnimId）对应的所有帧标注
[Serializable]
public class AnimationMeta
{
    [LabelText("动画Tag")] 
    public List<AnimTag> Tags = new();
    
    [LabelText("技能Pose区间")]
    public List<AnimSkillPoseRange> skillPoseRangeClips = new();  // 技能前摇/后摇姿势区间
    
    [LabelText("设置WarpTargetOffset")]
    public List<AnimSetWarpTargetOffset> motionWarpOffsetClips = new();  // 位移扭曲偏移
    
    // 查询指定时间点的所有激活 Tag
    public void GetActiveList(FP time, ref ListComponent<EAnimTag> result)
    {
        result.Clear();
        foreach (var tag in Tags)
        {
            if (tag.IsActive(time)) result.Add(tag.Tag);
        }
    }
    
    // 检查指定时间点是否有某个 Tag
    public AnimTag HasTagAtTime(FP time, EAnimTag tag)
    {
        foreach (var animTag in Tags)
        {
            if (animTag.Tag == tag && animTag.IsActive(time)) return animTag;
        }
        return null;
    }
}
```

---

## 3. 动画路径解析（CAnimationPrefix）

```csharp
// 动画资源路径解析（支持角色覆盖、Avatar 动画共用）
public sealed partial class CAnimationPrefix
{
    // 获取指定动画的 Addressable 资源路径
    public string GetAnimPath(int charID, int animId, AnimPathType type = AnimPathType.Character)
    {
        // 先查 TbAnimation 获取默认路径后缀
        string postfix = CfgManager.tables.TbAnimation.GetOrDefault(animId).AddressableKey;
        
        // 检查角色是否有覆盖配置（TbAnimationOverride 允许特定角色使用不同动画）
        var overrideConf = CfgManager.tables.TbAnimationOverride.Get(charID, animId);
        if (overrideConf != null)
        {
            postfix = overrideConf.AddressableKey;  // 使用覆盖路径
        }
        
        // 按路径类型拼接前缀
        string prefix = type switch
        {
            AnimPathType.Common    => CommonPrefix,   // 通用动画（共享）
            AnimPathType.Character => AddrPrefix,     // 角色专属动画
            AnimPathType.Avatar    => AvatarPrefix,   // Avatar 换装动画
            _ => AddrPrefix
        };
        
        // 结果："{prefix}_{postfix}" 即 Addressable Bundle 路径
        return $"{prefix}_{postfix}";
    }
    
    // 从 JSON 文件加载动画帧标注数据
    public void TryLoadMeta()
    {
        if (AnimMeta != null) return;
        
        AnimTagUtils.TryInit();
        try
        {
            // 路径：GameCfg/AnimMeta/{AddrPrefix}.json
            AnimMeta = JSONDataManager.LoadJsonData<Dictionary<int, AnimationMeta>>(
                PathUtil.GetAnimMetaPath(AddrPrefix));
            if (AnimMeta == null) AnimMeta = new();
        }
        catch
        {
            AnimMeta = new();
        }
    }
}
```

---

## 4. 在技能系统中的实际使用

```csharp
// 技能命中判断：检查当前帧是否处于"攻击帧"区间
public static void CheckHitFrame(this SkillComponent skill, FP currentTime)
{
    var animPrefix = skill.Owner.AnimPrefix;
    int animId = skill.CurrentAnimId;
    
    // 查询当前时间是否有 Attack Tag
    var attackTag = animPrefix.HasTagAtTime(animId, currentTime, EAnimTag.S_Attack);
    if (attackTag != null)
    {
        // 在攻击帧区间内 → 检测命中
        skill.DoHitDetect();
    }
}

// 受击无敌帧判断
public static bool IsInvincible(this Unit unit)
{
    var animPrefix = unit.AnimPrefix;
    int curAnimId = unit.CurrentAnimId;
    FP curTime = unit.CurrentAnimTime;
    
    return animPrefix.HasTagAtTime(curAnimId, curTime, EAnimTag.S_Invincible) != null;
}

// Dodge（闪避）时的无敌帧
[MessageHandler(SceneType.Client)]
public class SkillDodgeHandler : AMHandler<SkillDodgeMsg>
{
    protected override async ETTask Run(Entity entity, SkillDodgeMsg args)
    {
        var unit = args.Unit;
        // 闪避期间角色进入无敌帧（在动画配置中标注 S_Invincible Tag）
        // 无敌帧检测统一走 AnimTag 查询，无需在代码中硬编码帧数
    }
}
```

---

## 5. 动画元数据存储格式（JSON）

```json
// GameCfg/AnimMeta/Char001.json
// 每个角色有一个 AnimMeta JSON，记录所有动画的帧标注
{
  "1001": {           // AnimId = 1001（普通攻击动画）
    "Tags": [
      {
        "StartTime": "0.1",   // 定点数（FP），单位：秒
        "EndTime": "0.4",
        "Tag": 2,             // EAnimTag.S_Attack = 2
        "AnimLength": "0.8"
      },
      {
        "StartTime": "0.2",
        "EndTime": "0.35",
        "Tag": 5,             // EAnimTag.S_Invincible = 5（短暂无敌帧）
        "AnimLength": "0.8"
      }
    ],
    "skillPoseRanges": [],
    "motionWarpOffset": [
      {
        "StartFrame": 5,
        "EndFrame": 12,
        "MotionWarpOffset": { "x": "0", "y": "0", "z": "1.5" }  // 技能期间向前位移 1.5 米
      }
    ]
  }
}
```

---

## 6. 常见问题与最佳实践

**Q: AnimTag 为什么用定点数 FP 而不是 float？**  
A: 动画帧判断逻辑在帧同步层运行，所有逻辑必须使用定点数确保多端一致。浮点精度差异可能导致同样的攻击帧在不同设备上判定不同（一端命中，另一端未命中）。

**Q: AnimationMeta 的 JSON 是手动编辑还是工具生成？**  
A: 通过编辑器工具（使用 Odin Inspector `[ListDrawerSettings]`）在 Unity Editor 中可视化编辑，编辑后调用 `SaveMeta()` 序列化为 JSON，随资源包热更新到客户端。

**Q: Avatar 换装动画共享如何实现？**  
A: `AnimPathType.Avatar` 路径前缀使用 `AvatarPrefix`（角色共用的骨骼前缀），多个皮肤角色共用同一套 Avatar 骨架上的动画，避免重复制作相同的动画资源。

**Q: 技能的 MotionWarp（位移扭曲）如何利用 AnimTag 数据？**  
A: `AnimSetWarpTargetOffset` 记录位移区间和偏移量，技能系统在每帧更新时查询 `motionWarpOffsetClips`，根据当前时间在区间内则应用 TSVector 偏移（帧同步安全的位移）。
