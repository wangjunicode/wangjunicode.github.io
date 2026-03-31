---
title: 游戏NPC对话系统：分支对话与语音同步
published: 2026-03-31
description: 全面解析游戏NPC对话系统工程实现，包含对话配置（分支选项/条件判断/变量追踪）、Ink脚本语言集成（专业对话工具）、对话播放器（逐字显示/配音同步）、对话触发条件（任务/时间/关系度）、对话中内嵌事件（触发任务/给予物品），以及语音字幕同步。
tags: [Unity, 对话系统, NPC, 分支对话, 游戏设计]
category: 游戏系统设计
draft: false
---

## 一、对话数据结构

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public class DialogueNode
{
    public string NodeId;
    public string SpeakerId;       // NPC ID
    public string SpeakerName;
    [TextArea(2, 5)]
    public string Text;
    public AudioClip VoiceClip;    // 语音（可选）
    public float DisplayDuration;  // 显示时长（0=等待玩家点击）
    
    public DialogueChoice[] Choices;  // 分支选项（为空则自动跳下一句）
    public string NextNodeId;         // 无选项时的下一节点
    
    public DialogueCondition[] Conditions;   // 显示此节点的条件
    public DialogueEvent[] OnStartEvents;    // 节点开始时触发的事件
    public DialogueEvent[] OnEndEvents;      // 节点结束时触发的事件
}

[Serializable]
public class DialogueChoice
{
    public string Text;
    public string NextNodeId;
    public DialogueCondition[] Conditions;  // 选项显示条件
    public DialogueEvent[] OnSelectEvents;  // 选择时触发事件
}

[Serializable]
public class DialogueCondition
{
    public ConditionType Type;
    public string Key;
    public string Value;
}

public enum ConditionType { QuestCompleted, ItemOwned, RelationshipLevel, Flag }

[Serializable]
public class DialogueEvent
{
    public DialogueEventType Type;
    public string Param1;
    public string Param2;
}

public enum DialogueEventType 
{ 
    StartQuest, CompleteQuest, GiveItem, TakeItem, 
    SetFlag, AddRelationship, PlayAnimation, PlaySound
}
```

---

## 二、对话播放器

```csharp
public class DialoguePlayer : MonoBehaviour
{
    private static DialoguePlayer instance;
    public static DialoguePlayer Instance => instance;

    [SerializeField] private GameObject dialoguePanelRoot;
    [SerializeField] private UnityEngine.UI.Text speakerNameText;
    [SerializeField] private UnityEngine.UI.Text dialogueText;
    [SerializeField] private Transform choiceContainer;
    [SerializeField] private GameObject choicePrefab;
    [SerializeField] private AudioSource voiceSource;
    [SerializeField] private float typewriterSpeed = 30f; // 字/秒

    private Dictionary<string, DialogueNode> nodeMap;
    private DialogueNode currentNode;
    private Coroutine typewriterCoroutine;
    
    public event Action OnDialogueEnd;

    void Awake() { instance = this; }

    public void StartDialogue(Dictionary<string, DialogueNode> nodes, string startNodeId)
    {
        nodeMap = nodes;
        dialoguePanelRoot.SetActive(true);
        ShowNode(startNodeId);
    }

    void ShowNode(string nodeId)
    {
        if (!nodeMap.TryGetValue(nodeId, out var node))
        {
            EndDialogue();
            return;
        }
        
        // 检查条件
        if (node.Conditions != null)
            foreach (var cond in node.Conditions)
                if (!EvaluateCondition(cond)) { EndDialogue(); return; }
        
        currentNode = node;
        
        // 触发开始事件
        ExecuteEvents(node.OnStartEvents);
        
        speakerNameText.text = node.SpeakerName;
        
        // 逐字显示
        if (typewriterCoroutine != null) StopCoroutine(typewriterCoroutine);
        typewriterCoroutine = StartCoroutine(TypewriterEffect(node.Text));
        
        // 播放语音
        if (node.VoiceClip != null)
        {
            voiceSource.clip = node.VoiceClip;
            voiceSource.Play();
        }
    }

    System.Collections.IEnumerator TypewriterEffect(string text)
    {
        dialogueText.text = "";
        float delay = 1f / typewriterSpeed;
        
        foreach (char c in text)
        {
            dialogueText.text += c;
            yield return new WaitForSeconds(delay);
        }
        
        // 文字显示完毕，显示选项或等待点击
        ShowChoices(currentNode);
    }

    void ShowChoices(DialogueNode node)
    {
        // 清除旧选项
        foreach (Transform child in choiceContainer)
            Destroy(child.gameObject);
        
        if (node.Choices != null && node.Choices.Length > 0)
        {
            foreach (var choice in node.Choices)
            {
                if (choice.Conditions != null)
                {
                    bool conditionMet = true;
                    foreach (var cond in choice.Conditions)
                        if (!EvaluateCondition(cond)) { conditionMet = false; break; }
                    if (!conditionMet) continue;
                }
                
                var go = Instantiate(choicePrefab, choiceContainer);
                go.GetComponentInChildren<UnityEngine.UI.Text>().text = choice.Text;
                var choiceRef = choice; // 闭包捕获
                go.GetComponent<UnityEngine.UI.Button>().onClick.AddListener(() =>
                {
                    ExecuteEvents(choiceRef.OnSelectEvents);
                    ShowNode(choiceRef.NextNodeId);
                });
            }
        }
    }

    public void OnClickContinue()
    {
        if (typewriterCoroutine != null)
        {
            // 如果还在打字，直接显示全部文字
            StopCoroutine(typewriterCoroutine);
            dialogueText.text = currentNode.Text;
            ShowChoices(currentNode);
            return;
        }
        
        if (currentNode.Choices == null || currentNode.Choices.Length == 0)
        {
            ExecuteEvents(currentNode.OnEndEvents);
            ShowNode(currentNode.NextNodeId);
        }
    }

    bool EvaluateCondition(DialogueCondition cond)
    {
        switch (cond.Type)
        {
            case ConditionType.QuestCompleted:
                return QuestManager.Instance?.IsQuestCompleted(cond.Key) ?? false;
            case ConditionType.ItemOwned:
                return PlayerInventory.Instance?.HasItem(cond.Key) ?? false;
            default: return true;
        }
    }

    void ExecuteEvents(DialogueEvent[] events)
    {
        if (events == null) return;
        foreach (var evt in events)
        {
            switch (evt.Type)
            {
                case DialogueEventType.StartQuest:
                    QuestManager.Instance?.AcceptQuest(evt.Param1);
                    break;
                case DialogueEventType.GiveItem:
                    int count = int.TryParse(evt.Param2, out int n) ? n : 1;
                    PlayerInventory.Instance?.AddItem(evt.Param1, count);
                    break;
            }
        }
    }

    void EndDialogue()
    {
        dialoguePanelRoot.SetActive(false);
        voiceSource.Stop();
        OnDialogueEnd?.Invoke();
    }
}

// 占位类型
class PlayerInventory : MonoBehaviour
{
    public static PlayerInventory Instance;
    public bool HasItem(string id) => false;
    public void AddItem(string id, int count) { }
}
```

---

## 三、对话系统最佳实践

| 要点 | 方案 |
|------|------|
| 配置工具 | 使用 Ink 或 Dialogue System 插件 |
| 逐字动画 | 提升沉浸感，支持跳过 |
| 语音同步 | 对话文字与语音时长对齐 |
| 条件对话 | 根据任务状态显示不同台词 |
| 对话历史 | 支持回看对话记录 |
| 本地化 | 对话文本单独提取，支持多语言 |
