---
title: UI红点系统设计与实现
published: 2024-01-01
description: "UI红点系统设计与实现 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: UI系统
draft: false
---

# UI红点系统设计与实现

## 1. 系统概述

红点系统（Red Dot System）用于在 UI 按钮/图标上显示小红点或数字，提示玩家有未处理的事务（如未读邮件、可领取奖励、养成剧情更新等）。

本项目红点系统基于 **YIUI RedDotMgr**，采用观察者模式——业务层修改红点数量，UI 组件自动响应更新，两者完全解耦。

**设计特点：**
- 红点 Key 由工具自动生成（`ERedDotKeyType` 枚举），避免手写字符串 Key 出错
- `RedDotBind` 组件挂在 UI 节点上，自动订阅/取消订阅，零业务代码
- 数字红点（显示具体数量）和纯红点（只显示圆点）统一接口
- 父子层级联动：子红点有值 → 父红点自动亮起

---

## 2. 红点 Key 定义

```csharp
// 位置：Hotfix/UIModel/YIUIRedDot/Key/RedDotKeyRuntimeInt.cs
// 此文件由 YIUI 代码生成工具自动生成，勿手动修改
// 通过策划需求添加红点时，在工具中添加 Key 后重新生成即可

public static class IntRedDotKeyType
{
    public static int None = 0;    // 无效 Key
    public static int Key1 = 1;    // 养成系统红点
    public static int Key2 = 2;    // 成就系统红点
    public static int Key3 = 3;    // 成就总览
    public static int Key4 = 4;    // 成就剧情
    public static int Key5 = 5;    // 成就角色
    public static int Key6 = 6;    // 成就收集
    public static int Key7 = 7;    // 成就事件
    public static int Key8 = 8;    // 成就绝版
    // ... 更多 Key 自动生成
}

// 枚举版本（强类型，Inspector 可直接拖拽选择）
public enum ERedDotKeyType
{
    None = 0,
    Key1 = 1,   // [LabelText("养成")]
    Key2 = 2,   // [LabelText("成就")]
    // ...
}
```

---

## 3. RedDotBind 组件（UI 侧）

```csharp
// 位置：Hotfix/UIFunction/CommonUI/RedDotBind.cs
// 挂在 UI 节点（红点 GameObject）上，自动管理红点显示
public class RedDotBind : MonoBehaviour
{
    [SerializeField] private TextMeshProUGUI m_Text;  // 数量文本（可选，为 null 时只显示圆点）
    
    [SerializeField]
    [EnableIf("@UIOperationHelper.CommonShowIf()")]  // 仅在编辑器中显示（Odin 特性）
    private ERedDotKeyType m_Key;  // 绑定的红点 Key
    
    // 当前红点状态
    public bool Show { get; private set; }   // 是否显示
    public int Count { get; private set; }   // 当前数量
    
    private void Awake()
    {
        if (Key != ERedDotKeyType.None)
            SetKey(m_Key);  // 初始化时订阅
    }
    
    // 动态切换绑定的 Key（某些 UI 根据状态复用同一个节点）
    public void SetKey(ERedDotKeyType key)
    {
        // 先取消旧 Key 的订阅
        YIUIFramework.RedDotMgr.Inst?.RemoveChanged((int)m_Key, OnRedDotChangeHandler);
        m_Key = key;
        // 再订阅新 Key
        YIUIFramework.RedDotMgr.Inst?.AddChanged((int)m_Key, OnRedDotChangeHandler);
    }
    
    // 组件销毁时自动取消订阅（防止内存泄漏）
    private void OnDestroy()
    {
        if (YIUIFramework.SingletonMgr.Disposing) return;  // 游戏退出时跳过
        YIUIFramework.RedDotMgr.Inst?.RemoveChanged((int)Key, OnRedDotChangeHandler);
    }
    
    // 红点数量变化回调（由 RedDotMgr 主动推送）
    private void OnRedDotChangeHandler(int count)
    {
        if (this == null) return;  // 防止延迟回调时组件已销毁
        Show = count >= 1;
        Count = count;
        Refresh();
    }
    
    // 刷新 UI 显示
    private void Refresh()
    {
        if (this == null) return;
        gameObject.SetActive(Show);  // 显示/隐藏红点节点
        if (m_Text != null)
            m_Text.text = Count.ToString();  // 显示数量（如邮件 5 条）
    }
}
```

---

## 4. 业务层修改红点

```csharp
// 业务系统（邮件、成就等）在数据变化时主动更新红点数量

// 示例一：收到新邮件，更新邮件红点
public static void OnReceiveNewMail(int unreadCount)
{
    // 直接设置红点数量（0 = 隐藏，>0 = 显示）
    YIUIFramework.RedDotMgr.Inst?.ChangeValue(IntRedDotKeyType.Key_Mail, unreadCount);
}

// 示例二：成就系统更新，级联更新父子红点
public static void RefreshAchievementRedDot(AchievementData data)
{
    // 子分类红点（Story 类成就有 3 个未完成）
    int storyCount = data.GetCompletableCount(EAchievementType.Story);
    YIUIFramework.RedDotMgr.Inst?.ChangeValue(IntRedDotKeyType.Key4, storyCount);  // Key4 = 成就剧情
    
    int charCount = data.GetCompletableCount(EAchievementType.Character);
    YIUIFramework.RedDotMgr.Inst?.ChangeValue(IntRedDotKeyType.Key5, charCount);   // Key5 = 成就角色
    
    // 父级红点（Key3 = 成就总览）自动聚合子级（由 RedDotMgr 父子关系配置驱动）
    // 不需要手动算，RedDotMgr 会自动将 Key4+Key5+... 的和赋给 Key3
}

// 示例三：养成剧情完成，取消养成红点
public static void OnCultivationScriptCompleted()
{
    YIUIFramework.RedDotMgr.Inst?.ChangeValue(IntRedDotKeyType.Key1, 0);
}
```

---

## 5. ESystemType 到红点 Key 的映射

```csharp
// 位置：Hotfix/UIFunction/CommonUI/RedDotHelper.cs
// 服务器推送 ESystemType（系统类型枚举），客户端映射到对应红点 Key
public static class RedDotHelper
{
    public static ERedDotKeyType SysTypeToRedDotKeyType(ESystemType eSystemType)
    {
        return eSystemType switch
        {
            ESystemType.Cultivate   => ERedDotKeyType.Key1,   // 养成系统
            ESystemType.Achievement => ERedDotKeyType.Key2,   // 成就系统
            _                       => ERedDotKeyType.None    // 未知系统，不显示红点
        };
    }
}

// 使用场景：服务器主动推送某个系统有更新
[MessageHandler(SceneType.Client)]
public class SvrSystemUpdateHandler : AMHandler<ZoneSvrSystemUpdateNotify>
{
    protected override async ETTask Run(Entity entity, ZoneSvrSystemUpdateNotify args)
    {
        foreach (var sysType in args.UpdatedSystems)
        {
            var key = RedDotHelper.SysTypeToRedDotKeyType(sysType);
            if (key != ERedDotKeyType.None)
            {
                // 服务器通知系统有更新，显示红点（具体数量需要请求服务器才知道）
                YIUIFramework.RedDotMgr.Inst?.ChangeValue((int)key, 1);
            }
        }
    }
}
```

---

## 6. 父子红点层级联动

```csharp
// RedDotMgr 支持配置红点的父子关系
// 配置方式：在初始化时调用 SetParent
// 父红点的数量 = 所有子红点数量的和（自动计算）

// 成就系统红点层级配置（通常在 GameInit 中配置）
public static void InitRedDotHierarchy()
{
    var mgr = YIUIFramework.RedDotMgr.Inst;
    
    // Key2（成就系统）作为父，Key3（成就总览）作为子
    mgr.SetParent(IntRedDotKeyType.Key3, IntRedDotKeyType.Key2);
    mgr.SetParent(IntRedDotKeyType.Key4, IntRedDotKeyType.Key3);  // Key4(剧情) → Key3(总览)
    mgr.SetParent(IntRedDotKeyType.Key5, IntRedDotKeyType.Key3);  // Key5(角色) → Key3(总览)
    mgr.SetParent(IntRedDotKeyType.Key6, IntRedDotKeyType.Key3);  // Key6(收集) → Key3(总览)
    // 当 Key4/Key5/Key6 任意一个 >0 时，Key3 自动亮起
    // 当 Key3 >0 时，Key2 自动亮起
}
```

---

## 7. 常见问题与最佳实践

**Q: 红点 Key 数量很多，如何管理？**  
A: Key 由 YIUI 代码生成工具统一管理，在工具的 Excel 表里维护 Key 的名称和层级关系，生成代码后提交。不手写字符串 Key，避免 typo 导致红点不更新。

**Q: 进入游戏后红点状态如何初始化？**  
A: 登录成功后，服务器会推送各系统的未读/待处理数量（`ZoneLoginResp` 中包含）。客户端在 `SyncLoginData` 时统一初始化所有红点数量。

**Q: 红点在面板关闭时会不会继续响应更新？**  
A: `RedDotBind.OnDestroy()` 自动取消订阅，面板关闭时（GameObject 销毁）不会再收到回调。注意：只有 GameObject 真正销毁时才取消，如果面板用 `SetActive(false)` 隐藏，仍然会响应（可能导致不必要的调用）。推荐面板关闭用销毁而非隐藏。
