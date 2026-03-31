---
title: 游戏NPC对话系统：对话树与条件分支
published: 2026-03-31
description: 深度解析游戏NPC对话系统的工程设计，包含对话树数据结构（节点/条件/分支）、对话状态机（显示/等待选择/执行效果）、对话条件检查（任务状态/物品/属性）、对话执行效果（给物品/触发任务/播放动画）、对话文本的变量插值、语音行对口型控制，以及对话编辑器工具的设计思路。
tags: [Unity, 对话系统, NPC, 游戏设计, 游戏开发]
category: 游戏系统设计
draft: false
---

## 一、对话数据结构

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 对话节点类型
/// </summary>
public enum DialogNodeType
{
    Text,       // 普通文本（NPC说话）
    Choice,     // 玩家选项
    Condition,  // 条件分支（根据条件跳转）
    Effect,     // 执行效果（给物品/触发任务）
    End,        // 对话结束
}

/// <summary>
/// 对话条件
/// </summary>
[Serializable]
public class DialogCondition
{
    public DialogConditionType Type;
    public string TargetId;   // 任务ID/物品ID/属性ID等
    public string Operator;   // "=", ">", "<", "has", "not_has"
    public string Value;
}

public enum DialogConditionType
{
    QuestComplete,   // 任务已完成
    QuestActive,     // 任务进行中
    HasItem,         // 持有物品
    PlayerLevel,     // 玩家等级
    WorldFlag,       // 世界标志位
    Custom           // 自定义
}

/// <summary>
/// 对话效果
/// </summary>
[Serializable]
public class DialogEffect
{
    public DialogEffectType Type;
    public string TargetId;
    public int Value;
}

public enum DialogEffectType
{
    StartQuest,     // 开始任务
    CompleteQuest,  // 完成任务
    GiveItem,       // 给予物品
    TakeItem,       // 取走物品
    GiveCurrency,   // 给予货币
    SetWorldFlag,   // 设置世界标志
    PlayAnimation,  // NPC播放动画
    OpenShop,       // 打开商店
    TeleportPlayer, // 传送玩家
}

/// <summary>
/// 对话节点
/// </summary>
[Serializable]
public class DialogNode
{
    public string NodeId;
    public DialogNodeType Type;
    
    // 文本节点
    [TextArea(2, 5)] public string Text;
    public string SpeakerName;        // 说话者名称（留空=NPC名）
    public string VoiceClipId;        // 语音剪辑ID
    public string AnimationId;        // NPC表情动画
    public float TextDisplayDelay;    // 逐字显示速度
    
    // 选项节点
    public List<DialogChoice> Choices;
    
    // 条件节点
    public List<DialogCondition> Conditions;
    public string TrueNodeId;         // 条件满足跳转
    public string FalseNodeId;        // 条件不满足跳转
    
    // 效果节点
    public List<DialogEffect> Effects;
    
    // 下一个节点（Text/Effect/非条件节点）
    public string NextNodeId;
}

[Serializable]
public class DialogChoice
{
    public string Text;               // 选项文本
    public string NextNodeId;         // 选择后跳转的节点
    public List<DialogCondition> ShowConditions; // 显示该选项的条件
    public bool IsExitOption;         // 是否是"离开"按钮
}

/// <summary>
/// 完整对话资产
/// </summary>
[CreateAssetMenu(fileName = "Dialog", menuName = "Game/Dialog")]
public class DialogData : ScriptableObject
{
    public string DialogId;
    public string NPCId;
    public string StartNodeId;
    public List<DialogNode> Nodes;
    
    public DialogNode GetNode(string nodeId) =>
        Nodes?.Find(n => n.NodeId == nodeId);
}
```

---

## 二、对话系统控制器

```csharp
/// <summary>
/// 对话系统控制器
/// </summary>
public class DialogSystem : MonoBehaviour
{
    private static DialogSystem instance;
    public static DialogSystem Instance => instance;

    [Header("UI引用")]
    [SerializeField] private DialogUI dialogUI;
    
    private DialogData currentDialog;
    private DialogNode currentNode;
    private bool isDialogActive;
    
    // 事件
    public event Action<string> OnDialogStarted;   // dialogId
    public event Action<string> OnDialogEnded;
    public event Action<DialogNode> OnNodeChanged;

    void Awake() { instance = this; }

    /// <summary>
    /// 开始对话
    /// </summary>
    public void StartDialog(DialogData dialog)
    {
        if (isDialogActive) return;
        
        isDialogActive = true;
        currentDialog = dialog;
        
        // 暂停玩家控制
        PlayerController.Instance?.SetInputEnabled(false);
        
        dialogUI?.Show();
        OnDialogStarted?.Invoke(dialog.DialogId);
        
        GotoNode(dialog.StartNodeId);
    }

    void GotoNode(string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId))
        {
            EndDialog();
            return;
        }
        
        var node = currentDialog.GetNode(nodeId);
        if (node == null)
        {
            Debug.LogError($"[Dialog] 找不到节点: {nodeId}");
            EndDialog();
            return;
        }
        
        currentNode = node;
        OnNodeChanged?.Invoke(node);
        
        ProcessNode(node);
    }

    void ProcessNode(DialogNode node)
    {
        switch (node.Type)
        {
            case DialogNodeType.Text:
                ShowTextNode(node);
                break;
                
            case DialogNodeType.Choice:
                ShowChoiceNode(node);
                break;
                
            case DialogNodeType.Condition:
                ProcessConditionNode(node);
                break;
                
            case DialogNodeType.Effect:
                ProcessEffectNode(node);
                GotoNode(node.NextNodeId);
                break;
                
            case DialogNodeType.End:
                EndDialog();
                break;
        }
    }

    void ShowTextNode(DialogNode node)
    {
        // 处理变量插值 {player_name} → 玩家名
        string text = ReplaceVariables(node.Text);
        
        dialogUI?.ShowText(node.SpeakerName, text, () =>
        {
            // 文字显示完毕，等待点击继续
            dialogUI?.ShowContinueButton(() => GotoNode(node.NextNodeId));
        });
        
        // 播放语音
        if (!string.IsNullOrEmpty(node.VoiceClipId))
            AudioManager.Instance?.PlaySFX(null); // 实际替换为按ID加载
    }

    void ShowChoiceNode(DialogNode node)
    {
        // 过滤掉条件不满足的选项
        var availableChoices = new List<DialogChoice>();
        
        foreach (var choice in node.Choices)
        {
            bool show = true;
            if (choice.ShowConditions != null)
            {
                foreach (var cond in choice.ShowConditions)
                    if (!EvaluateCondition(cond)) { show = false; break; }
            }
            if (show) availableChoices.Add(choice);
        }
        
        dialogUI?.ShowChoices(availableChoices, selectedChoice =>
        {
            GotoNode(selectedChoice.IsExitOption ? null : selectedChoice.NextNodeId);
        });
    }

    void ProcessConditionNode(DialogNode node)
    {
        bool conditionMet = true;
        
        foreach (var cond in node.Conditions)
        {
            if (!EvaluateCondition(cond))
            {
                conditionMet = false;
                break;
            }
        }
        
        GotoNode(conditionMet ? node.TrueNodeId : node.FalseNodeId);
    }

    void ProcessEffectNode(DialogNode node)
    {
        foreach (var effect in node.Effects)
            ExecuteEffect(effect);
    }

    void ExecuteEffect(DialogEffect effect)
    {
        switch (effect.Type)
        {
            case DialogEffectType.StartQuest:
                QuestManager.Instance?.AcceptQuest(effect.TargetId);
                break;
            case DialogEffectType.CompleteQuest:
                QuestManager.Instance?.CompleteQuest(effect.TargetId);
                break;
            case DialogEffectType.GiveItem:
                // InventorySystem.Instance?.AddItem(...)
                break;
            case DialogEffectType.GiveCurrency:
                // CurrencyManager.Instance?....
                break;
            case DialogEffectType.SetWorldFlag:
                // WorldStateManager.Instance?.SetFlag(effect.TargetId, true);
                break;
            case DialogEffectType.OpenShop:
                ShopSystem.Instance?.OpenShop(effect.TargetId);
                break;
        }
    }

    bool EvaluateCondition(DialogCondition cond)
    {
        switch (cond.Type)
        {
            case DialogConditionType.QuestComplete:
                return QuestManager.Instance?.IsQuestCompleted(cond.TargetId) ?? false;
            case DialogConditionType.HasItem:
                return FindObjectOfType<InventorySystem>()?.HasItem(cond.TargetId) ?? false;
            case DialogConditionType.PlayerLevel:
                int level = PlayerDataService.GetLocalPlayerData()?.Level ?? 0;
                int required = int.TryParse(cond.Value, out int v) ? v : 0;
                return cond.Operator == ">=" ? level >= required : level == required;
        }
        return true;
    }

    string ReplaceVariables(string text)
    {
        var data = PlayerDataService.GetLocalPlayerData();
        if (data != null)
        {
            text = text.Replace("{player_name}", data.Nickname);
            text = text.Replace("{player_level}", data.Level.ToString());
        }
        return text;
    }

    void EndDialog()
    {
        isDialogActive = false;
        dialogUI?.Hide();
        PlayerController.Instance?.SetInputEnabled(true);
        OnDialogEnded?.Invoke(currentDialog?.DialogId ?? "");
        currentDialog = null;
    }
}
```

---

## 三、对话系统设计要点

| 要点 | 方案 |
|------|------|
| 数据驱动 | ScriptableObject存储对话树，策划可编辑 |
| 条件分支 | 根据任务/物品/等级动态显示不同选项 |
| 效果节点 | 对话执行任务/给物品，不需要代码改动 |
| 变量插值 | {player_name}→实际名字，个性化体验 |
| 逐字显示 | 文字逐字出现，可跳过（点击立即显示）|
| 语音对口型 | 语音播放时NPC嘴型动画同步 |
