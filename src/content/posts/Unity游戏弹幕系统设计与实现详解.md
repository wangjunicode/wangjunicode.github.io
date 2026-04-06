---
title: Unity游戏弹幕系统设计与实现详解
published: 2026-03-31
description: 从弹幕数据结构到行分配算法、对象池管理、配置表驱动的固定弹幕序列及普通/填充/特殊三类弹幕的调度策略，完整解析一套工业级弹幕系统。
tags: [Unity, UI系统, 弹幕系统, 对象池]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏弹幕系统设计与实现详解

## 弹幕系统的工程挑战

弹幕（Bullet Screen / Danmaku）是现代游戏直播互动和社区氛围营造的重要工具。一个工业级弹幕系统需要解决：

1. **大量弹幕的性能管理**：可能每秒有几十条弹幕，不能每条都 `Instantiate/Destroy`
2. **多行布局**：弹幕需要分配到不同行，避免重叠
3. **配置表驱动**：策划配置固定的弹幕内容和出现时机，不需要代码支持
4. **三类弹幕调度**：普通弹幕（时序播放）、填充弹幕（间隙补充）、特殊弹幕（高亮显示）
5. **开关控制**：玩家可以随时关闭弹幕，不影响系统状态

---

## 数据结构：弹幕数据池化

```csharp
public class BulletCommentData
{
    public string Content;      // 弹幕文本内容
    public float ShootTime;     // 预设的发送时间（秒，从开始算起）
}

// 类级别的对象池（所有 DanmakuPanel 实例共享一个池）
public static Framework.ObjectPool<BulletCommentData> BulletDataPool;
```

`BulletCommentData` 是一个简单的数据类，但通过**静态对象池**管理。静态池的好处：
- 所有场景/关卡共用同一个池，不需要每个场景单独初始化
- 弹幕数据对象的创建销毁完全走对象池，零 GC

对象池回调的实现：
```csharp
// 归还时清空数据
public static void OnReleaseBulletCommentData(BulletCommentData data)
{
    data.Content = "";
    data.ShootTime = 0;
}
```

清空是防止归还后的数据被意外使用（比如某个还持有引用的代码读到了旧数据）。

---

## 三类弹幕的队列管理

```csharp
private readonly Queue<BulletCommentData> _fixedNormalComment = new();  // 固定普通弹幕（按时间顺序）
private readonly Queue<BulletCommentData> _fixedFillComment = new();    // 填充弹幕（间隙时填充）
private readonly Queue<BulletCommentData> _specialComment = new();      // 特殊弹幕（带特效）
```

三个队列对应三种不同的弹幕出现策略：

| 类型 | 策略 | 用途 |
|------|------|------|
| Normal | 按 `ShootTime` 时序发射 | 剧情台词、活动倒计时等 |
| Fill | 间隙时自动补充 | 保持弹幕密度，避免屏幕空旷 |
| Special | 独立渲染，带方框高亮 | VIP 消息、系统公告 |

---

## 配置表加载固定弹幕

```csharp
public void LoadFixedComment(int _case = 0, float elapseTime = 0)
{
    var dm = CfgManager.tables.TbDanmaku.GetOrDefault(_bulletID);
    if (dm == null) return;
    
    foreach (var item in dm.Items)
    {
        var b1 = BulletDataPool.Get();  // 从池中获取数据对象
        b1.Content = item.Text;
        
        if (item.Type == EType.NORMAL)
        {
            b1.ShootTime = item.Time / 1000f + elapseTime;  // 毫秒→秒
            _fixedNormalComment.Enqueue(b1);
        }
        else if (item.Type == EType.FILLING && _case == 0)
        {
            _fixedFillComment.Enqueue(b1);  // 填充弹幕不需要时间
        }
    }
}
```

`_bulletID` 对应配置表 `TbDanmaku` 的一行，每行包含一组预设弹幕（这场关卡/活动的专属弹幕内容）。`elapseTime` 允许在弹幕系统中途接入时，偏移所有弹幕的触发时间（比如从中途开始播放弹幕时，不显示已过期的弹幕）。

---

## 弹幕行分配算法

弹幕的行分配是防止重叠的关键算法：

```csharp
private readonly Dictionary<int, Danmaku> _lastText = new()
{
    {0, null}, {1, null}, {2, null}
};  // 记录每行的最近一条弹幕
```

行分配逻辑（伪代码，从完整源码推断）：

```csharp
private int AllocateLine()
{
    // 遍历每行，找到最后一条弹幕的右边界位置
    for (int line = 0; line < MaxLine; line++)
    {
        var lastDanmaku = _lastText[line];
        if (lastDanmaku == null)
            return line;  // 该行为空，直接用
        
        // 计算最后一条弹幕的右边界
        float rightEdge = lastDanmaku.palTsf.anchoredPosition.x 
                        + lastDanmaku.palTsf.rect.width;
        
        // 如果右边界 + 间隔 < 屏幕右边界，该行可用
        if (rightEdge + BulletInterval < screenWidth)
            return line;
    }
    
    // 所有行都不可用，找"最空闲"的行（右边界最左的行）
    return FindLeastBusyLine();
}
```

`BulletInterval = 60`（像素）确保同一行相邻弹幕之间有足够间隔。`BulletLineInterval = 36` 是行间距。

---

## 滚动动画：每帧移动

```csharp
public static int BulletSpeed = 7;  // 7像素/帧
public static float _deltaTime = 1f/60;  // 固定时间步长

// 每帧更新（简化）
private void UpdateBullets()
{
    _removeCache.Clear();
    
    foreach (var danmaku in _allTexts)
    {
        var pos = danmaku.palTsf.anchoredPosition;
        pos.x -= BulletSpeed;  // 向左移动
        danmaku.palTsf.anchoredPosition = pos;
        
        // 移出屏幕左边界则归还到对象池
        if (pos.x + danmaku.palTsf.rect.width < 0)
        {
            _removeCache.Add(danmaku);
        }
    }
    
    // 批量移除（避免迭代中修改集合）
    foreach (var danmaku in _removeCache)
    {
        _allTexts.Remove(danmaku);
        
        // 更新行记录
        for (int i = 0; i < MaxLine; i++)
        {
            if (_lastText[i] == danmaku)
                _lastText[i] = null;
        }
        
        _textPool.Release(danmaku.gameObject);  // 归还到 GameObject 池
    }
}
```

`_removeCache` 避免了在遍历 `_allTexts` 时修改集合（`InvalidOperationException`）。先收集到 `_removeCache`，遍历结束后再批量移除。

---

## 定时发射逻辑

```csharp
const int TickMaxTime = 600;  // 每600ms触发一次弹幕发射检查
```

弹幕不是每帧都检查，而是每 600ms 检查一次是否需要发射新弹幕。发射逻辑：

1. 检查 `_fixedNormalComment` 队头的 `ShootTime` 是否到了，是则发射
2. 如果 Normal 队列空了，`_normalCommentFinishTimes++`
3. 当 Normal 播完一轮（`_normalCommentFinishTimes >= normalCommentRepeatCount`），开始从 Fill 队列补充
4. Fill 队列也空了，什么都不发（屏幕上依然有正在滚动的弹幕）

这个策略确保了：
- 在内容充足时，配置的剧情弹幕按时序播放
- 间隙时用填充弹幕维持密度
- 不强行在屏幕已经很满时再发射新弹幕

---

## 开关控制的设计

```csharp
public bool BulletOn
{
    get => _bulletOn;
    set
    {
        bool changed = _bulletOn != value;
        _bulletOn = value;
        u_ComDanmakuStateBinder.ApplyState(_bulletOn ? 0 : 1);  // 切换图标状态
        OnBulletOn(changed);
    }
}

private void OnBulletOn(bool changed)
{
    if (!changed) return;
    
    if (_bulletOn)
    {
        StartScroll(true);   // 开启：重新开始滚动
        LoadFixedComment(1); // 重新加载普通弹幕（只加载Normal，不加载Fill）
    }
    else
    {
        ClearScreen();      // 关闭：清空当前屏幕上所有弹幕
        StartScroll(false); // 停止弹幕发射
    }
}
```

`BulletOn` 属性使用 C# 的 property setter，在值改变时自动触发副作用（图标状态切换 + 滚动开关）。

**关闭时 `ClearScreen`** 的实现：

```csharp
public void ClearScreen()
{
    var screenw = PanelMgr.Inst.UICanvas.GetComponent<RectTransform>().sizeDelta.x;
    foreach (var obj in _allTexts)
    {
        // 把弹幕瞬间移到屏幕左边界外
        var v2 = obj.palTsf.anchoredPosition;
        v2.x = -screenw;
        obj.palTsf.anchoredPosition = v2;
        _textPool.Release(obj.gameObject);  // 归还对象池
    }
    _allTexts.Clear();
    for (int i = 0; i < MaxLine; i++)
        _lastText[i] = null;
}
```

不是 `SetActive(false)`，而是把弹幕**瞬间移到屏幕外**再归还池——这样不会触发 `OnDisable` 导致的额外逻辑，且视觉上弹幕"消失"更快。

---

## 发送弹幕的事件处理

```csharp
public void OnEventSendAction()
{
    YIUIComponent.ClientScene.GetComponent<EventDispatcherComponent>()
        .FireEvent(new Evt_SendBulletComment()
        {
            Content = u_ComInputFieldTMP_InputField.text
        });
    
    EvtOnSend?.Invoke();
    u_ComInputFieldTMP_InputField.text = "";  // 清空输入框
}

private void OnSendBulletEvt(Evt_SendBulletComment evt)
{
    // 把自己发的弹幕也加入队列
    var b1 = BulletDataPool.Get();
    b1.Content = evt.Content;
    b1.ShootTime = 0;  // 立即发射
    _specialComment.Enqueue(b1);  // 自己发的弹幕作为"特殊弹幕"处理（带高亮）
}
```

玩家发送弹幕通过事件系统（`FireEvent`）而不是直接调用，这允许：
1. 服务器转发后再展示（防刷）
2. 其他系统监听并做处理（敏感词过滤、冷却时间检查）

---

## 弹幕 GameObject 的对象池

```csharp
private UnityEngine.Pool.ObjectPool<GameObject> _textPool;

_textPool = new UnityEngine.Pool.ObjectPool<GameObject>(
    OnCreateFunc,    // 创建：实例化 Danmaku Prefab
    OnGet,           // 取出：设置父节点
    OnRelease,       // 归还：暂时什么都不做
    OnDestroy1,      // 溢出销毁：SafeDestroySelf
    true,            // 收集检查：是否检测归还重复的对象
    1,               // 默认容量
    100              // 最大容量（超出则直接销毁不入池）
);
```

**容量设置（1, 100）的考量**：

- 默认容量1：绝大多数情况下屏幕上弹幕不多，不预先创建太多
- 最大容量100：同屏最多100个弹幕，超出的销毁（高并发情况下的安全阀）

---

## 总结

弹幕系统是 UI 层少有的"高频更新 + 大量对象管理"的场景，它展示了：

1. **双层对象池**：`BulletDataPool`（数据对象）+ `_textPool`（GameObject），全链路无 GC
2. **三队列调度**：Normal（时序）→ Fill（间隙补充）→ Special（特殊高亮）的优先级
3. **行分配算法**：基于最后一条弹幕右边界的轻量级防重叠算法
4. **批量移除**：`_removeCache` 集合避免迭代时修改
5. **属性 setter 副作用**：`BulletOn` 的 set 在值改变时自动触发 UI 和逻辑更新
6. **ClearScreen 瞬移**：清空弹幕用"移出屏幕外+归池"，比 SetActive 更高效
