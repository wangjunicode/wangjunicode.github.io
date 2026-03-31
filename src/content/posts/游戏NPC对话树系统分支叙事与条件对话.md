---
title: 游戏NPC对话树系统：分支叙事与条件对话
published: 2026-03-31
description: 全面解析游戏NPC对话树系统的工程设计，包括对话树数据结构（节点/选项/条件/动作）、基于ScriptableObject的对话配置、运行时对话执行引擎、变量条件系统（根据剧情进度解锁不同对话）、对话动作触发（给予物品/触发任务/改变关系度）、语音与字幕同步，以及本地化多语言对话支持。
tags: [Unity, NPC对话, 叙事系统, 对话树, RPG游戏]
category: 游戏系统设计
draft: false
---

## 一、对话树数据结构

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 对话节点类型
/// </summary>
public enum DialogueNodeType
{
    Start,          // 入口节点
    NPC,            // NPC说话
    Player,         // 玩家选项节点（显示选择列表）
    Condition,      // 条件分支节点
    Action,         // 执行动作节点（给物品/触发任务等）
    End             // 结束对话
}

/// <summary>
/// 对话节点
/// </summary>
[Serializable]
public class DialogueNode
{
    public string NodeId;
    public DialogueNodeType Type;
    
    // NPC/Player 文本
    public string SpeakerName;          // 说话者（NPC名字或"玩家"）
    public string SpeakerPortraitId;    // 说话者肖像ID
    [TextArea(2, 5)]
    public string Text;                 // 对话文本（支持本地化Key）
    public AudioClip VoiceClip;         // 配音（可选）
    
    // 子节点连接
    public List<DialogueEdge> Edges;    // 出边（跳转到哪些节点）
    
    // 条件节点
    public List<DialogueCondition> Conditions; // 进入此节点的前置条件
    
    // 动作节点
    public List<DialogueAction> Actions;       // 进入此节点时执行的动作
    
    // 位置（编辑器用）
    public Vector2 EditorPosition;
}

/// <summary>
/// 对话边（节点间的连接）
/// </summary>
[Serializable]
public class DialogueEdge
{
    public string TargetNodeId;
    public string ChoiceText;           // 玩家选项文本（仅Player节点有意义）
    public List<DialogueCondition> Conditions; // 此选项的前置条件
}

/// <summary>
/// 对话条件
/// </summary>
[Serializable]
public class DialogueCondition
{
    public string VariableName;         // 变量名（如 "quest_01_state"）
    public ConditionOperator Operator;
    public string Value;                // 比较值
    
    public enum ConditionOperator { Equals, NotEquals, GreaterThan, LessThan, HasItem, CompletedQuest }
    
    public bool Evaluate(DialogueVariableStore store)
    {
        return Operator switch
        {
            ConditionOperator.Equals => store.Get(VariableName) == Value,
            ConditionOperator.NotEquals => store.Get(VariableName) != Value,
            ConditionOperator.GreaterThan => 
                float.TryParse(store.Get(VariableName), out float v) && v > float.Parse(Value),
            ConditionOperator.HasItem => 
                InventoryManager.Instance?.HasItem(VariableName) ?? false,
            ConditionOperator.CompletedQuest => 
                QuestManager.Instance?.IsCompleted(VariableName) ?? false,
            _ => false
        };
    }
}

/// <summary>
/// 对话动作（对话中触发的效果）
/// </summary>
[Serializable]
public class DialogueAction
{
    public DialogueActionType Type;
    public string Parameter1;
    public string Parameter2;
    
    public enum DialogueActionType
    {
        GiveItem,           // 给予物品（Parameter1=物品ID, Parameter2=数量）
        TakeItem,           // 取走物品
        StartQuest,         // 开始任务
        CompleteQuest,      // 完成任务目标
        SetVariable,        // 设置变量（P1=变量名, P2=值）
        ChangeRelation,     // 改变NPC关系度（P1=NPCID, P2=变化量）
        PlayAnimation,      // 播放NPC动画
        TriggerEvent        // 触发游戏事件
    }

    public void Execute()
    {
        switch (Type)
        {
            case DialogueActionType.GiveItem:
                if (int.TryParse(Parameter2, out int count))
                    InventoryManager.Instance?.AddItem(Parameter1, count);
                break;
            
            case DialogueActionType.StartQuest:
                QuestManager.Instance?.StartQuest(Parameter1);
                break;
            
            case DialogueActionType.SetVariable:
                DialogueVariableStore.Global.Set(Parameter1, Parameter2);
                break;
            
            case DialogueActionType.ChangeRelation:
                if (float.TryParse(Parameter2, out float delta))
                    RelationshipManager.Instance?.ChangeRelation(Parameter1, delta);
                break;
        }
    }
}
```

---

## 二、对话资源（ScriptableObject）

```csharp
/// <summary>
/// 对话资源（存储完整对话树数据）
/// </summary>
[CreateAssetMenu(fileName = "Dialogue", menuName = "Game/Dialogue Asset")]
public class DialogueAsset : ScriptableObject
{
    public string DialogueId;           // 唯一ID
    public string NPCName;              // 关联NPC名称
    public List<DialogueNode> Nodes;
    public string StartNodeId;          // 入口节点ID
    
    // 触发条件（什么情况下可以触发此对话）
    public List<DialogueCondition> TriggerConditions;
    
    public DialogueNode GetNode(string nodeId)
    {
        return Nodes.Find(n => n.NodeId == nodeId);
    }
    
    public DialogueNode GetStartNode()
    {
        return GetNode(StartNodeId);
    }
}
```

---

## 三、对话引擎

```csharp
/// <summary>
/// 对话变量存储（全局剧情变量）
/// </summary>
public class DialogueVariableStore
{
    private static DialogueVariableStore global = new DialogueVariableStore();
    public static DialogueVariableStore Global => global;
    
    private Dictionary<string, string> variables = new Dictionary<string, string>();
    
    public void Set(string key, string value) => variables[key] = value;
    
    public string Get(string key) => 
        variables.TryGetValue(key, out string v) ? v : "";
    
    public bool GetBool(string key) => 
        bool.TryParse(Get(key), out bool b) && b;
    
    public int GetInt(string key) => 
        int.TryParse(Get(key), out int i) ? i : 0;
}

/// <summary>
/// 对话执行引擎
/// </summary>
public class DialogueRunner : MonoBehaviour
{
    private static DialogueRunner instance;
    public static DialogueRunner Instance => instance;

    private DialogueAsset currentDialogue;
    private DialogueNode currentNode;
    private bool isRunning;
    
    public event Action<DialogueNode> OnNodeEntered;              // 进入新节点
    public event Action<List<DialogueEdge>> OnChoicesPresented;  // 出现玩家选项
    public event Action OnDialogueEnded;                          // 对话结束

    void Awake() { instance = this; }

    /// <summary>
    /// 开始对话
    /// </summary>
    public void StartDialogue(DialogueAsset dialogue)
    {
        if (isRunning)
        {
            Debug.LogWarning("[Dialogue] Already in dialogue!");
            return;
        }
        
        currentDialogue = dialogue;
        isRunning = true;
        
        // 暂停游戏输入
        GameInputManager.Instance?.SetDialogueMode(true);
        
        // 进入起始节点
        EnterNode(dialogue.GetStartNode());
    }

    void EnterNode(DialogueNode node)
    {
        if (node == null)
        {
            EndDialogue();
            return;
        }
        
        currentNode = node;
        
        // 执行进入动作
        if (node.Actions != null)
            foreach (var action in node.Actions)
                action.Execute();
        
        switch (node.Type)
        {
            case DialogueNodeType.Start:
                // 自动跳转到第一个满足条件的子节点
                AdvanceToNext();
                break;
            
            case DialogueNodeType.NPC:
                // 显示NPC对话文本，等待玩家点击继续
                OnNodeEntered?.Invoke(node);
                // UI 显示完毕后调用 AdvanceToNext()
                break;
            
            case DialogueNodeType.Player:
                // 显示玩家选项列表
                var validChoices = GetValidEdges(node);
                if (validChoices.Count == 0)
                {
                    EndDialogue();
                    return;
                }
                OnChoicesPresented?.Invoke(validChoices);
                break;
            
            case DialogueNodeType.Condition:
                // 自动根据条件跳转
                AdvanceByCondition();
                break;
            
            case DialogueNodeType.Action:
                // 执行完动作后自动跳转
                AdvanceToNext();
                break;
            
            case DialogueNodeType.End:
                EndDialogue();
                break;
        }
    }

    public void AdvanceToNext()
    {
        if (currentNode.Edges == null || currentNode.Edges.Count == 0)
        {
            EndDialogue();
            return;
        }
        
        var edge = GetValidEdges(currentNode).Find(_ => true); // 取第一个满足条件的
        if (edge != null)
            EnterNode(currentDialogue.GetNode(edge.TargetNodeId));
        else
            EndDialogue();
    }

    public void SelectChoice(int choiceIndex)
    {
        var choices = GetValidEdges(currentNode);
        if (choiceIndex < 0 || choiceIndex >= choices.Count) return;
        
        EnterNode(currentDialogue.GetNode(choices[choiceIndex].TargetNodeId));
    }

    void AdvanceByCondition()
    {
        var validEdge = GetValidEdges(currentNode).Find(_ => true);
        if (validEdge != null)
            EnterNode(currentDialogue.GetNode(validEdge.TargetNodeId));
        else
            EndDialogue();
    }

    List<DialogueEdge> GetValidEdges(DialogueNode node)
    {
        var result = new List<DialogueEdge>();
        if (node.Edges == null) return result;
        
        foreach (var edge in node.Edges)
        {
            bool conditionsMet = true;
            
            if (edge.Conditions != null)
                foreach (var cond in edge.Conditions)
                    if (!cond.Evaluate(DialogueVariableStore.Global))
                    {
                        conditionsMet = false;
                        break;
                    }
            
            if (conditionsMet)
                result.Add(edge);
        }
        
        return result;
    }

    void EndDialogue()
    {
        isRunning = false;
        currentDialogue = null;
        currentNode = null;
        
        GameInputManager.Instance?.SetDialogueMode(false);
        OnDialogueEnded?.Invoke();
    }
}
```

---

## 四、推荐工具链

| 工具 | 特点 | 适用场景 |
|------|------|----------|
| Ink（Inkle）| 专业叙事脚本语言，Unity插件完善 | 复杂分支叙事，编剧友好 |
| Yarn Spinner | 开源，类似Ink，Unity深度整合 | 中等规模RPG |
| 自定义ScriptableObject | 完全可控，可扩展 | 需要深度定制的项目 |
| Dialogue System（付费）| 功能完整的商业插件 | 快速接入，减少自研 |

**叙事设计原则：**
1. 变量系统是核心，让玩家的选择真正影响世界
2. 重要剧情分支要有收束点（防止内容爆炸）
3. 对话要支持跳过（不强迫重复看过的内容）
4. 配音与字幕同步需要精确控制时序
