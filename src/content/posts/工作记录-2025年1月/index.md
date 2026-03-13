---
title: 工作记录 2025年1月
published: 2025-01-01
description: "酒馆需求开发、协议处理调试、聊天页签架构、红点系统使用笔记"
tags: [工作记录]
category: 工作记录
draft: false
---

## 01/07

### Lua 表引用与 table.clear 的行为

**问题**：`table.clear(self.m_kCurLoopListData)` 会清空表里所有内容吗？会影响到 `self.m_kData.member_list` 吗？

**结论**：`table.clear(self.m_kCurLoopListData)` 只会清空 `self.m_kCurLoopListData`，**不会直接修改 `self.m_kData.member_list` 的数据**。

**原因**：

1. **引用关系**：`self.m_kCurLoopListData` 中存储的是从 `self.m_kData.member_list` 中获取的引用（即表的指针），而不是独立的拷贝。清空 `self.m_kCurLoopListData` 只会清除引用本身，不会对 `self.m_kData.member_list` 中的表数据产生任何影响。
2. **修改引用指向的对象**：如果在 `self.m_kCurLoopListData` 中修改某个 `data` 的字段（例如 `data.itemType`），由于这是对引用操作，`self.m_kData.member_list` 中对应的数据会同步改变。
3. **`table.clear` 的作用域**：`table.clear(self.m_kCurLoopListData)` 是直接操作 `self.m_kCurLoopListData` 表的内容本身，而不是操作引用所指向的对象。

---

## 01/09

### 协议调试：encode_unsafe 报错

**问题**：`encode_unsafe: romsg.CreateRoomReq does not exist`

**原因**：加载的 pb 里找不到该消息名，说明导出成 pb.byte 过程中出现了错误。

**根因**：`MG_Define` 里定义的名字与实际 proto message 名字不一致：

- `MG_Define` 中：`req_name = "romsg.CreateBarRoomReq"`
- 实际 proto 中：

```proto
message CreateBarroomReq {
    int32 barroomType = 1;    // 房间类型，策划配表
    int32 languageType = 2;   // 语言类型，策划配表
    int32 barroomName = 3;    // 房间名
    bool isAcceptAgreement = 4; // 是否接受协议
}
```

**教训**：查找字符串时一定要**开启大小写匹配**，避免大小写拼写错误导致的查找遗漏。

### 聊天左侧页签架构

- 初始化时读配置
- 页签初始化后根据配置显示
- 点击绑定回调各自独立

---

## 01/22

### 功能点梳理

- 赠礼超链接
- 红点系统
- 麦克风 icon

---

## 01/23

### 红点系统使用笔记

红点系统基于配置表驱动，整体使用流程如下：

**1. 注册红点**

在配置表中定义红点信息，覆盖使用基础配置。

**2. UI 绑定**

UI 组件绑定对应红点 Key，响应红点状态变化。

**3. 管道刷新**

通过管道机制刷新红点状态。

**4. 事件触发**

```lua
LC_Event:DispatchEvent(
    LC_ModuleId.Common,
    LC_NotifyId.Common.RedDotValueSet,
    { Lua_RedDotModule.BarRoom.IsHaveApplyReq, nil, #res.requestList }
)
```

---