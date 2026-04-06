---
title: Unity游戏棋盘式技能布局系统设计与实现
published: 2026-03-31
description: 深度剖析基于棋盘格的角色技能放置系统，包含动态棋盘大小调整、棋子放置合法性验证、位置交换算法、连接关系可视化及对象池优化的完整实现。
tags: [Unity, UI系统, 技能布局, 棋盘系统]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏棋盘式技能布局系统设计与实现

## 背景：什么是棋盘式技能布局

在某些策略类游戏中，角色的技能不是固定的，而是可以通过在一个"棋盘"上放置"棋子"（技能模块）来自由搭配。每个棋子占据一定的格子，格子之间有连接关系（相邻的角色棋子和技能棋子会产生联动效果）。

这是游戏设计上的一个高级玩法——类似于《Slay the Spire》的卡组构建，但空间化、视觉化程度更高。

从技术角度，`SkillBoard.cs` 是这套系统的核心组件，它的挑战在于：

1. **动态棋盘**：棋盘大小可以在运行时调整（`Resize(Vector2_Int)`）
2. **多种棋子类型**：角色棋子（Character）和技能棋子（Feature/Tactic），放置规则不同
3. **连接关系可视化**：相邻的角色和技能棋子之间有连接线，连接处显示发挥度数值
4. **复杂放置逻辑**：放置时可能需要挤开现有棋子，或与另一个棋子交换位置
5. **对象池**：棋盘格子和棋子 GameObject 都用对象池管理

---

## 棋盘的核心数据结构

```csharp
[Serializable]
public class RowData { public List<CellData> elements; }

[SerializeField]
public List<RowData> Data = new List<RowData>();  // 棋盘格数据（二维展开为一维）

[SerializeField]
public List<SlotCell> Cells = new List<SlotCell>();   // 格子 UI 组件列表

[SerializeField]
public List<ChessBoardData> ChessData = new List<ChessBoardData>();  // 已放置的棋子数据

[SerializeField]
public List<ChessPiece> ChessList = new List<ChessPiece>();  // 已放置的棋子组件列表

[SerializeField]
public Vector2_Int _Size = Vector2_Int.zero;  // 棋盘大小（行数×列数）
```

棋盘采用**行优先**的一维展开方式存储二维数据：`Data[i].elements[j]` 是第i行第j列的格子。格子的 UI 组件在 `Cells[i * _Size.y + j]` 中。

**为什么不用二维数组？**

`List<RowData>` 而不是 `CellData[,]` 的原因：
1. Unity 的 `[SerializeField]` 不支持二维数组序列化
2. List 可以动态扩容/缩容（Resize时很方便）
3. Odin Inspector 等工具对 List 有更好的编辑器支持

---

## 动态棋盘大小调整

`Resize(Vector2_Int value)` 是最复杂的方法之一，它需要同时处理：
1. 格子数据（`Data`）
2. 格子 UI 组件（`Cells`）
3. 遮罩覆盖层（`Covers`）
4. 连接线（`LinkCore_X`、`LinkCore_Y`）
5. 连接线数值显示（`LinkCoreValue_X`、`LinkCoreValue_Y`）

```csharp
protected void Resize(Vector2_Int value)
{
    _Size = value;
    int count = _Size.x * _Size.y;  // 总格子数
    
    // 处理多余的格子：销毁多余的 UI 组件
    if (Covers.Count > count)
    {
        for (int i = count; i < Covers.Count; i++)
        {
            DestroyImmediate(Covers[i].gameObject);
        }
        Covers.RemoveRange(count, Covers.Count - count);
    }
    
    // 补充不足的格子：新建 UI 组件
    for (int i = 0; i < count; i++)
    {
        if (i >= Covers.Count || Covers[i] == null)
        {
            var go = new GameObject();
            go.transform.SetParent(this.transform);
            var cover = go.AddComponent<Image>();
            Covers.Insert(i, cover);
        }
    }
    
    // Data 的处理类似，但不销毁 GameObject，只调整 List 大小
    if (Data.Count > _Size.x)
        Data.RemoveRange(_Size.x, Data.Count - _Size.x);
    
    for (int i = 0; i < _Size.x; i++)
    {
        if (i >= Data.Count)
            Data.Add(new RowData() { elements = new List<CellData>() });
        
        // 每行的元素调整
        if (Data[i].elements.Count > _Size.y)
            Data[i].elements.RemoveRange(_Size.y, Data[i].elements.Count - _Size.y);
        
        for (int j = 0; j < _Size.y; j++)
        {
            if (j >= Data[i].elements.Count)
            {
                var cell = new CellData();
                cell.SetType((int)ECellType.Feature);
                Data[i].elements.Add(cell);
            }
        }
    }
    
    FreshSlot();  // 重排所有格子的位置
}
```

**关键设计思路**："先缩再扩"——先删除多余的，再补充不足的，避免中间状态的混乱。

连接线数量的计算：
- 横向连接线数量 = `_Size.x * (_Size.y - 1)` （每行之间的格子间）
- 纵向连接线数量 = `(_Size.x - 1) * _Size.y` （每列之间的格子间）

---

## 棋子放置的合法性验证

棋子放置是整个系统的核心，`TryHoldChessOnPos` 方法包含了完整的合法性验证逻辑：

```csharp
public bool TryHoldChessOnPos(ChessPiece chess, int x, int y, bool CanSwitch = true)
{
    // 边界检查：棋子不能超出棋盘边界
    if (x >= 0 && y >= 0 && x + chess.Size.x - 1 < Size.x && y + chess.Size.y - 1 < Size.y)
    {
        // 角色棋子：检查该角色是否有上场资格
        if (chess.CellType == ECellType.Character)
        {
            var chessConf = CfgManager.tables.TbChess.GetOrDefault(chess.confID);
            int IpId = chessConf.DefaultLevel.BaseInfo.PassiveId;
            if (!extraBuildData.IsCharacterCanOnStage(IpId))
            {
                UIHelper.ShowTips("当前角色不可上场");
                return false;
            }
        }

        // 检查目标区域内每个格子是否允许放置该类型的棋子
        int groupID = Data[x].elements[y].group;
        for (int i = x; i < x + chess.Size.x; i++)
        {
            for (int j = y; j < y + chess.Size.y; j++)
            {
                if (!BoardUtil.CanSetChess(Data, ReleaseList, i, j, chess.CellType, groupID))
                    return false;
            }
        }

        // 角色上场数量限制
        int characterChessCnt = 0;
        using var oldChessList = ListComponent<(ChessPiece, Vector2_Int, int)>.Create();
        
        foreach (var _chess in ChessList)
        {
            bool bHold = false;
            // 检查同一组（group）是否已有棋子，如果有需要移除
            var chessSlot = Data[_chess.Pos.x].elements[_chess.Pos.y];
            if (groupID != 0 && (groupID == chessSlot.group && chessSlot.type == Data[x].elements[y].type))
            {
                if (!CanSwitch) return false;  // 不允许切换则直接返回失败
                oldChessList.Add((_chess, _chess.Pos, _chess.idx));
                bHold = true;
            }
            
            // 检查目标区域是否有棋子占用
            if (!bHold)
            {
                for (int i = x; i < x + chess.Size.x; i++)
                {
                    for (int j = y; j < y + chess.Size.y; j++)
                    {
                        if (_chess.IsHoldOnCell(i, j))
                        {
                            if (!CanSwitch) return false;
                            oldChessList.Add((_chess, _chess.Pos, _chess.idx));
                            bHold = true;
                            break;
                        }
                    }
                    if (bHold) break;
                }
            }
            
            // 统计已在场的角色数量
            if (!bHold && TeamSaveData.GetBackUpSlotType(_chess.CellType) == ECellType.Character)
                characterChessCnt++;
        }
        
        // 角色上场数量上限检查
        if (TeamSaveData.GetBackUpSlotType(chess.CellType) == ECellType.Character 
            && characterChessCnt >= characterMaxNum)
        {
            UIHelper.ShowTips("当前芯盒已达最大可出战人数");
            return false;
        }
        
        // 所有检查通过，执行放置 + 处理被挤开的棋子
        ExecutePlaceChess(chess, x, y, oldChessList, CanSwitch);
        return true;
    }
    return false;
}
```

合法性验证链（每一步失败即返回 false）：
1. 边界检查
2. 角色资格检查
3. 每个目标格子的类型匹配检查
4. 上场角色数量检查

---

## 被挤棋子的处理：交换 vs 挤压

当新棋子放置位置有旧棋子时，有两种处理方案：

### 方案一：交换（Swap）

```csharp
// 如果尺寸相同且位置相同 → 完全交换
if (_chess.Size == chess.Size && data.Item2 == chess.Pos)
{
    if (holdInfoBackUp.slot)
    {
        // 旧棋子放到新棋子的来源槽位
        holdInfoBackUp.slot.AddChess(_chess);
        oldChessList.RemoveAt(idx);
    }
    else if (TryHoldChessOnPos(_chess, holdInfoBackUp.pos.x, holdInfoBackUp.pos.y, false))
    {
        // 旧棋子放到新棋子的原位置
        oldChessList.RemoveAt(idx);
    }
}
```

完全交换的条件：两个棋子尺寸相同，且目标位置完全重叠。这是最简单的情况。

### 方案二：挤压（Push）

```csharp
// 如果不能完全交换，尝试把被挤开的棋子放到邻近位置
for (int i = 1; i <= Mathf.Max(_chess.Size.x, _chess.Size.y); i++)
{
    if (i <= _chess.Size.y) { deltaList.Add(new Vector2_Int(0, i)); deltaList.Add(new Vector2_Int(0, -i)); }
    if (i <= _chess.Size.x) { deltaList.Add(new Vector2_Int(i, 0)); deltaList.Add(new Vector2_Int(-i, 0)); }
}

bool bHold = false;
foreach (var delta in deltaList)
{
    // 尝试以当前位置为起点，向4个方向逐步扩大搜索范围
    if (TryHoldChessOnPos(_chess, oldPos.x + delta.x, oldPos.y + delta.y, false))
    {
        oldChessList.RemoveAt(idx);
        bHold = true;
        break;
    }
}

if (!bHold)
    _chess.SetInBackUp();  // 如果棋盘上没有合适位置，退回备用区
```

挤压逻辑的搜索顺序是：
1. 右移1格 → 左移1格 → 上移1格 → 下移1格
2. 右移2格 → 左移2格 → ...

以"曼哈顿距离"递增的方式搜索，确保被挤开的棋子尽量移动最短距离。

---

## 连接关系可视化

`FreshLinkCore()` 是连接线可视化的核心方法：

```csharp
public void FreshLinkCore()
{
    // 先隐藏所有连接线
    foreach (var link in LinkCore_X) link.gameObject.SetActive(false);
    foreach (var link in LinkCore_Y) link.gameObject.SetActive(false);
    
    // 对每个角色棋子，找到相邻的技能棋子，显示连接线
    foreach (var chess in ChessList)
    {
        if (chess.CellType == ECellType.Character)
        {
            // 检查上下相邻格子（纵向连接）
            for (int x = chess.Pos.x; x < chess.Pos.x + chess.Size.x; x++)
            {
                Vector2_Int left = new Vector2_Int(x, chess.Pos.y - 1);   // 左侧相邻
                Vector2_Int right = new Vector2_Int(x, chess.Pos.y + chess.Size.y);  // 右侧相邻
                
                foreach (var testChess in ChessList)
                {
                    // 只有非角色棋子才会被连接
                    if (TeamSaveData.GetBackUpSlotType(testChess.CellType) != ECellType.Character)
                    {
                        if (IsInRange(testChess, left))
                        {
                            testChess.SetLinkState(true);
                            // 显示对应位置的连接线
                            LinkCore_X[x * (_Size.y - 1) + left.y].gameObject.SetActive(true);
                        }
                        // right 方向类似...
                    }
                }
            }
            // 水平相邻格子（横向连接）类似处理...
        }
    }
    
    FreshLinkCoreValue();  // 刷新连接处的数值显示
}
```

**`IsInRange(chess, pos)` 是邻接判断的核心**：

```csharp
public bool IsInRange(ChessPiece chess, Vector2_Int pos)
{
    return pos.x >= chess.Pos.x && pos.x < chess.Pos.x + chess.Size.x 
        && pos.y >= chess.Pos.y && pos.y < chess.Pos.y + chess.Size.y;
}
```

这个方法检查某个坐标点是否在某个棋子所占据的矩形范围内。通过遍历角色棋子边界上的每个格子，用 `IsInRange` 检查相邻格子是否有其他棋子，实现了任意尺寸棋子间的邻接检测。

---

## 连接数值（意志发挥度）的计算

角色与技能棋子的连接处显示"意志发挥度"——这是一个游戏特有的数值，影响连接技能的效果：

```csharp
public FP GetVolatility(ChessPiece chessA, ChessPiece chessB)
{
    // 确定哪个是角色棋子，哪个是技能棋子
    ChessPiece character = chessA;
    ChessPiece feature = chessB;
    if (chessB.CellType == ECellType.Character)
    {
        feature = chessA;
        character = chessB;
    }
    
    // 从角色的 IP ID 获取意志力属性值
    var characterChessConf = CfgManager.tables.TbChess.GetOrDefault(character.confInfo.id);
    int IpId = characterChessConf.DefaultLevel.BaseInfo.PassiveId;
    var willpower = extraBuildData.GetCharacterAttr(IpId, EAttributeType.Willpower);
    
    // 根据技能的基础发挥度 + 角色意志力，计算最终发挥度
    var chessConf = CfgManager.tables.TbChess.GetOrDefault(feature.confID);
    BattleAPI.意志发挥度(chessConf.BaseNumericPercent, willpower, out var percent, out var finalPercent);
    
    return finalPercent;
}
```

`BattleAPI.意志发挥度` 是一个中文命名的战斗公式方法（这在国内游戏项目中偶尔见到，因为策划文档用中文，直接对应到代码更易沟通）。发挥度的计算结果格式化为百分比显示在连接线旁边。

---

## 对象池在棋盘系统中的应用

```csharp
ChessPool = new ObjectPool<GameObject>(
    createFunc: () => Instantiate(_ChessTemplate, ChessRoot.transform),  // 创建
    actionOnGet: obj => {
        // 从池中取出时，重置棋子状态
        var chess = obj.GetAddComponent<ChessPiece>();
        chess.bInitSize = false;
        chess._confInfo = new ChessSaveInfo() { id = 0, level = 0 };
        chess.holdInfo.type = EChessHoldType.ENan;
        chess.board = this;
        chess.bCustom = true;
        chess.Pos = new Vector2_Int(-1, -1);
        chess.Size = Vector2_Int.zero;
        obj.SetActive(true);
    },
    actionOnRelease: obj => obj.SetActive(false),  // 归还：隐藏
    actionOnDestroy: obj => Destroy(obj)            // 销毁：释放内存
);
```

Unity 的 `ObjectPool<T>` 是 2021 版本新增的官方对象池实现。这里对应了对象池的四个关键操作：
- **创建**：从 Template Prefab 实例化
- **取出**：重置到初始状态（清除上次的数据残留）
- **归还**：SetActive(false)，不销毁但不可见
- **溢出销毁**：当池容量满时，多余的对象直接 Destroy

`actionOnGet` 中的状态重置非常关键——`chess.Pos = new Vector2_Int(-1, -1)` 明确设置为无效位置，防止刚取出的棋子被当成"在棋盘上"处理。

---

## 为什么这个系统值得深入学习

`SkillBoard.cs` 是一个**复杂数据结构管理 + UI 实时渲染**的综合案例：

| 技术点 | 实现方式 |
|--------|---------|
| 动态网格 | List 对应 GameObject 的增删同步 |
| 邻接检测 | AABB 矩形相邻判断 |
| 放置验证 | 多层条件检查链 |
| 位置交换 | 大小匹配 + 来源槽位归还 |
| 位置挤压 | 曼哈顿距离螺旋搜索 |
| 关系可视化 | 遍历边界 + 索引映射 |
| 性能管理 | ObjectPool + 锁定刷新（`bNotFreshChess`） |

`bNotFreshChess` 是一个"批量更新保护锁"的典型实现——在批量操作期间锁定 `FreshChessData()`，等所有变更完成后一次性刷新，避免每个小操作都触发一次全量刷新。

这种"更新批处理"技术在游戏中极其常见，本质上是一个 Dirty Flag 模式的应用。
