---
title: Unity游戏打字机效果与文字渐入动画深度实现
published: 2026-03-31
description: 完整解析基于TextMeshPro顶点操作的打字机效果实现，包括逐字渐入、下划线同步动画、性能优化策略及异步状态机设计。
tags: [Unity, UI系统, 文字动画, TextMeshPro]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏打字机效果与文字渐入动画深度实现

## 为什么打字机效果这么难做好

在剧情对话、新手引导、NPC 对话等场景中，文字逐字出现的"打字机效果"几乎是所有游戏的标配。但想把它做得真正好看，远比你想象的复杂：

- 不只是逐字显示，还需要**渐入效果**（每个字从透明淡入）
- 文字有**下划线**时，下划线也要跟着字的进度同步显示
- 需要支持**跳过**（玩家按下跳过键立即显示全部文字）
- 需要支持**提前显示一部分**（比如某个历史片段已经被读过）
- 异步播放时需要**可靠的取消机制**（切换对话时旧的播放不能继续）

本文基于真实项目的 `TypeWriter.cs` 源码，带你走通这套复杂系统的完整实现。

---

## 整体架构

```
TypeWriter (MonoBehaviour)
│
├── PlayStatus        — 播放状态（是否在播、进度、flag等）
├── _charOriAlpha     — 每个字符的原始 Alpha 值（List<byte>）
├── _charAlphaPercent — 每个字符的当前透明度百分比（List<float>）
├── _charIdxAdd       — 可见字符到真实字符的索引偏移（处理空格等不可见字符）
├── _underlineSegments — 下划线分段信息
└── _charUnderlineSegmentIdx — 每个可见字符所属的下划线分段
```

核心思路：**直接操作 TextMeshPro 的顶点颜色数据**，而不是用 Animator 或 DOTween——因为 TMP 的顶点操作是逐字精确控制的，比整组动画更灵活。

---

## 关键数据结构

### PlayStatus — 播放状态

```csharp
public class PlayStatus
{
    public bool Playing = false;
    public float StartTime = 0;        // 开始时间（用于计算经过时间）
    public float LastUpdateTime = 0;   // 上次刷新时间（用于控制刷新频率）
    public float UpdateInterval = 1f/30; // 30fps 刷新频率
    public bool TypeWriterFinished = false;
    public int TxtFadeCount = 0;       // 已触发渐入的字符数（包括提前显示的）
    public int VisibleChar = 0;        // 当前已进入渐入流程的字符数
}
```

`UpdateInterval = 1f/30` 是一个性能优化：文字渐入不需要每帧都运行，30fps 完全够用，减少了 GC 压力和 CPU 开销。

### 空格问题：_charIdxAdd

TMP 的 `textInfo.characterInfo` 包含**所有字符**（包括空格、换行等不可见字符），但我们的渐入只需要处理**可见字符**。两个索引系统需要映射：

```csharp
// 可见字符索引 → 真实字符索引
private int Visible2RealCharinfoIdx(int idx)
{
    return idx + _charIdxAdd[idx];
}

// 真实字符索引 → 可见字符索引
private int Real2VisibleCharinfoIdx(int idx)
{
    for (int i = 0; i < _charIdxAdd.Count; i++)
    {
        if (i + _charIdxAdd[i] == idx)
            return i;
    }
    return _charIdxAdd.Count - 1;
}
```

`_charIdxAdd[i]` 存储的是"第i个可见字符前面有多少个不可见字符"。例如 "A B C"（A空格B空格C），`_charIdxAdd = [0, 1, 2]`，表示：
- 可见字符0（A）：真实index = 0+0 = 0
- 可见字符1（B）：真实index = 1+1 = 2（跳过index=1的空格）
- 可见字符2（C）：真实index = 2+2 = 4（跳过两个空格）

---

## 初始化流程

```csharp
private void BeforeTypewriter()
{
    _unVisibleChar = 0;
    _charUnderlineSegmentIdx.Clear();
    _underlineSegments.Clear();
    _charIdxAdd.Clear();
    
    // 遍历所有字符，建立可见字符的索引映射
    for (int i = 0; i < _tmpInfo.characterCount; i++)
    {
        if (!_tmpInfo.characterInfo[i].isVisible)
        {
            _unVisibleChar++;
            continue;
        }
        
        int visibleIdx = i - _unVisibleChar;
        if (visibleIdx >= _charIdxAdd.Count)
            _charIdxAdd.Add(_unVisibleChar);
        else
            _charIdxAdd[visibleIdx] = _unVisibleChar;
        
        // 记录每个可见字符的原始 Alpha（用于后续渐入计算）
        RecordCharAlpha(_tmpInfo, visibleIdx);
    }

    BuildUnderlineSegments();  // 构建下划线分段信息
    InitializeAllVerticesAlpha();  // 将所有顶点 Alpha 设为 0（全透明）
    InitializeUnderlineSegments();

    // 处理"提前显示"的字符
    int totalVisibleChar = _tmpInfo.characterCount - _unVisibleChar;
    _effectiveShowOnStartLength = Mathf.Clamp(showOnStartLength, 0, Mathf.Max(0, totalVisibleChar));
    for (int i = 0; i < _effectiveShowOnStartLength; i++)
    {
        SetCharAlphaPercent(i, 1);  // 立即设为完全不透明
    }

    _playStatus.VisibleChar = _effectiveShowOnStartLength;
    _playStatus.TxtFadeCount = _effectiveShowOnStartLength;
    
    _textTMP.UpdateVertexData(TMP_VertexDataUpdateFlags.Colors32 | TMP_VertexDataUpdateFlags.Vertices | TMP_VertexDataUpdateFlags.Uv0);
    _onTypeWriterStart?.Invoke();
}
```

`InitializeAllVerticesAlpha()` 将所有顶点 Alpha 设为 0 是关键的初始化操作——确保动画开始前文字完全透明，然后逐字从 0 渐入到原始 Alpha 值。

---

## 异步播放与取消机制

```csharp
public async ETTask Play()
{
    _playStatus.Playing = true;
    _playStatus.TypeWriterFinished = false;
    
    var curFlag = ++_playingFlag;  // 每次播放递增一个唯一标志
    
    _textTMPCanvasGroup.alpha = 1;
    _textTMP.ForceMeshUpdate();
    _tmpInfo = _textTMP.textInfo;
    BeforeTypewriter();
    
    _playStatus.StartTime = Time.time;
    _playStatus.LastUpdateTime = 0;
    
    while (!CheckCurTimelineStop(curFlag))
    {
        // 节流：30fps 刷新
        if (Time.time - _playStatus.LastUpdateTime < _playStatus.UpdateInterval)
        {
            if (TimerComponent.Instance != null)
                await TimerComponent.Instance.WaitFrameAsync();
            else
                await Task.Yield();
            continue;
        }
        
        TypewriterTick();
        _playStatus.LastUpdateTime = Time.time;
        if (_playStatus.TypeWriterFinished) break;
    }
    
    _playStatus.Playing = false;
    _playStatus.TypeWriterFinished = true;
    _onTypeWriterEnd?.Invoke();
}

private bool CheckCurTimelineStop(int curFlag)
{
    // flag 不一致（有新的Play()调用）或 Playing 为 false（外部调用了Stop()）
    return curFlag != _playingFlag || !IsPlaying();
}
```

**flag 机制是异步取消的核心**：

假设正在播放 A 对话（curFlag=1），玩家点击跳过触发了新的 `Play()`（curFlag=2），那么 A 的 while 循环在下次检查时发现 `curFlag(1) != _playingFlag(2)` 就会退出，不会继续执行。

这比 `CancellationToken` 更简洁，在游戏场景中非常实用。

---

## 每帧刷新逻辑：TypewriterTick

```csharp
private void TypewriterTick()
{
    var curTime = Time.time - _playStatus.StartTime;
    
    // 1. 对当前正在渐入的字符继续渐变（增加透明度）
    int curIdx = _playStatus.VisibleChar - 1;
    float percentAdd = 1;
    if (txtFadeIn > 0)
        percentAdd = (Time.time - _playStatus.LastUpdateTime) / txtFadeIn;
    
    while (curIdx >= 0)
    {
        var curPercent = GetCharAlphaPercent(curIdx);
        if (curPercent >= 1) break;  // 已完全不透明，停止
        SetCharAlphaPercent(curIdx, curPercent + percentAdd);
        curIdx--;
    }

    // 2. 检查是否需要显示下一个字符
    if (curTime < (_playStatus.TxtFadeCount - _effectiveShowOnStartLength) * txtFadeInNextDelay)
    {
        // 还没到显示下一个字的时间
        RefreshUnderlineSegments();
        _textTMP.UpdateVertexData(/* ... */);
        return;
    }
    
    if (_playStatus.VisibleChar >= _tmpInfo.characterCount - _unVisibleChar)
    {
        // 所有字符都进入渐入流程，等待最后一个渐入完成
        if (GetCharAlphaPercent(_playStatus.VisibleChar - 1) >= 1)
            _playStatus.TypeWriterFinished = true;
        RefreshUnderlineSegments();
        _textTMP.UpdateVertexData(/* ... */);
        return;
    }

    // 3. 根据出现样式处理新字符
    switch (txtAppearStyle)
    {
        case TypeWriterData.EAppearStyle.PerChar:
            _playStatus.VisibleChar++;
            _playStatus.TxtFadeCount++;
            SetCharAlphaPercent(_playStatus.VisibleChar - 1, percent);
            break;
        
        case TypeWriterData.EAppearStyle.PerEnter:
            // 每次显示一整行
            // ... 找到下一个换行符，整行一起进入渐入
            break;
    }
    
    RefreshUnderlineSegments();
    _textTMP.UpdateVertexData(TMP_VertexDataUpdateFlags.Colors32 | TMP_VertexDataUpdateFlags.Vertices | TMP_VertexDataUpdateFlags.Uv0);
}
```

`txtFadeInNextDelay` 控制相邻字符之间的时间间隔，`txtFadeIn` 控制每个字从透明到完全不透明的时长。两个参数组合起来可以实现：
- 快速打字（小 delay，无 fade）
- 缓慢浮现（大 delay，长 fade）
- 整行淡入（PerEnter 模式 + fade）

---

## 顶点颜色操作的核心方法

```csharp
private void SetCharAlphaPercent(int idx, float alphaPercent)
{
    if (idx >= _charAlphaPercent.Count) return;
    
    alphaPercent = Mathf.Clamp01(alphaPercent);
    _charAlphaPercent[idx] = alphaPercent;
    
    // 根据百分比计算实际 Alpha 值（保留原始 Alpha 作为上限）
    byte targetAlpha = (byte)(_charOriAlpha[idx] * alphaPercent);
    
    var charInfo = _tmpInfo.characterInfo[Visible2RealCharinfoIdx(idx)];
    var materialIdx = charInfo.materialReferenceIndex;
    var vertexColor = _tmpInfo.meshInfo[materialIdx].colors32;

    // 设置该字符的 4 个顶点颜色（每个字符是一个矩形，4个顶点）
    for (int i = 0; i < 4; i++)
    {
        if (charInfo.vertexIndex + i < vertexColor.Length)
            vertexColor[charInfo.vertexIndex + i].a = targetAlpha;
    }
    
    _tmpInfo.meshInfo[materialIdx].mesh.colors32 = vertexColor;
}
```

**为什么乘以 `_charOriAlpha`？**

文字本身可能不是完全不透明的（比如故意设置了半透明文字），如果直接用百分比当 Alpha 值，最终效果是错的。乘以原始 Alpha 保证了"渐入是相对于原始透明度的渐入"，而不是强制变成完全不透明。

---

## 下划线的同步动画

下划线是 TMP 中一个独立的网格段（underline mesh），它的动画需要跟字符同步，但实现起来复杂得多——因为一条下划线可能覆盖多个字符：

```csharp
private struct UnderlineSegmentInfo
{
    public int MaterialIdx;
    public int VertexIndex;    // 下划线在 meshInfo 中的起始顶点index
    public int StartVisibleIdx; // 该下划线覆盖的第一个可见字符index
    public int EndVisibleIdx;   // 该下划线覆盖的最后一个可见字符index
    public float StartX;       // 下划线左边界 X 坐标
    public float EndX;         // 下划线右边界 X 坐标
    // ... 其他几何信息
}
```

每帧更新时，根据当前已渐入的字符进度，动态调整下划线的"可见宽度"：

```csharp
private void RefreshUnderlineSegments()
{
    for (int i = 0; i < _underlineSegments.Count; i++)
    {
        var segment = _underlineSegments[i];
        float fullRevealEndX = segment.StartX;    // 完全显示部分的右边界
        float partialRevealEndX = segment.StartX; // 部分显示（渐入中）部分的右边界
        float partialAlphaPercent = 0;
        
        int lastVisibleIdx = Mathf.Min(_playStatus.VisibleChar - 1, segment.EndVisibleIdx);
        
        for (int visibleIdx = segment.StartVisibleIdx; visibleIdx <= lastVisibleIdx; visibleIdx++)
        {
            float charAlphaPercent = GetCharAlphaPercent(visibleIdx);
            if (charAlphaPercent <= 0) continue;
            
            var charInfo = _tmpInfo.characterInfo[Visible2RealCharinfoIdx(visibleIdx)];
            float charEndX = Mathf.Min(charInfo.topRight.x, segment.EndX);
            
            if (charAlphaPercent >= 0.999f)
            {
                fullRevealEndX = charEndX;  // 这个字完全显示了，延伸完全区域
            }
            else
            {
                partialAlphaPercent = Mathf.Max(partialAlphaPercent, charAlphaPercent);
            }
        }
        
        // 计算下划线的渐入位置（用 SmoothStep 平滑）
        if (partialTargetEndX > fullRevealEndX + 0.001f && partialAlphaPercent > 0.001f)
        {
            float revealPercent = Mathf.SmoothStep(0f, 1f, partialAlphaPercent);
            float underlineFadeSource = Mathf.Clamp01(partialAlphaPercent * underlineFadeSpeedMultiplier);
            float fadePercent = 1f - Mathf.Pow(1f - underlineFadeSource, 3f);
            partialRevealEndX = Mathf.Lerp(fullRevealEndX, partialTargetEndX, revealPercent);
            partialAlphaPercent = fadePercent;
        }
        
        ApplyUnderlineSegmentReveal(segment, fullRevealEndX, partialRevealEndX, partialAlphaPercent);
    }
}
```

下划线用三段式顶点表示来实现"从左到右逐渐显示"：
- **第一段**：完全显示部分（不透明）
- **第二段**：全显示到部分显示的过渡
- **第三段**：部分显示（渐入中，Alpha 从左向右衰减）

---

## 跳过功能

```csharp
public void Stop()
{
    _playingFlag++;  // 使正在运行的 Play() 异步循环退出
    _playStatus.Playing = false;
    _playStatus.TypeWriterFinished = true;
    SetTxtAlphaPercent(1);  // 所有字符立即设为完全不透明
    _textTMP.UpdateVertexData(/* ... */);
}
```

Stop 的逻辑非常简洁：递增 `_playingFlag` 取消正在进行的异步播放，然后强制所有顶点变为完全不透明。

---

## 性能考虑

| 操作 | 频率 | 优化方式 |
|------|------|--------|
| `TypewriterTick` | 每帧 | `UpdateInterval` 节流到30fps |
| `UpdateVertexData` | 每 tick | 只在数据有变化时调用 |
| `ForceMeshUpdate` | 播放开始时 | 只调用一次 |
| List 扩容 | 初始化时 | 构造函数预分配容量：`new List<byte>(200)` |

预分配容量 `new List<byte>(200)` 避免了逐步扩容时的内存复制，对于文字数量确定的对话场景非常有效。

---

## 给初学者的总结

打字机效果是一个很好的学习案例，因为它涉及了多个重要知识点：

1. **TMP 顶点操作**：直接修改 mesh 的 colors32 数组，比 `SetAlpha()` 接口更高效
2. **异步状态机**：用 flag 机制实现可靠的异步取消
3. **索引映射**：可见字符和真实字符的双索引体系
4. **性能节流**：30fps 刷新而不是每帧刷新
5. **几何图形构造**：下划线的三段式顶点表示

这套代码放在实际项目中大约有500行，但每一行都有其存在的意义。阅读这样的代码，比看教程更能提升你对 Unity UI 底层的理解。
