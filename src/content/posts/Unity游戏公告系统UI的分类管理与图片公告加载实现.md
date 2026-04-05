---
title: Unity游戏公告系统UI的分类管理与图片公告加载实现
published: 2026-03-31
description: 深入解析游戏公告界面的活动/游戏公告分类管理、SDK数据拉取、循环列表单选、带版本控制的异步图片加载、本地缓存与空状态处理的完整实现。
tags: [Unity, UI系统, 公告系统, SDK集成]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏公告系统UI的分类管理与图片公告加载实现

## 公告系统的产品价值

公告系统（Announcement）是游戏与玩家沟通的重要渠道：
- **活动公告**：限时活动入口、活动说明
- **游戏公告**：版本更新说明、维护通知

从技术角度，公告系统有几个有趣的工程问题：
1. 数据来源是 SDK（第三方通知系统），不是游戏服务器
2. 公告内容可能是纯文字，也可能是带图片的富媒体（需要从URL加载图片）
3. 同时加载多条公告时，可能存在竞态问题（新公告的图片还没加载完，用户已经点击了其他公告）

---

## SDK 数据拉取

```csharp
private NoticeSDKModule _noticeModule;

private NoticeSDKModule EnsureNoticeModule()
{
    if (_noticeModule == null)
        _noticeModule = SDKManager.Instance.GetModule<NoticeSDKModule>();
    return _noticeModule;
}

private void RefreshNoticeData()
{
    var module = EnsureNoticeModule();
    _activityNoticeData.Clear();
    _gameNoticeData.Clear();

    if (module != null)
    {
        var notices = module.GetPostLoginNotices();  // 获取登录后的公告列表
        if (notices != null && notices.Count > 0)
        {
            foreach (var notice in notices)
            {
                if (notice == null) continue;
                
                if (notice.NoticeType == ActivityNoticeType)        // 1=活动
                    _activityNoticeData.Add(notice);
                else if (notice.NoticeType == GameNoticeType)       // 2=游戏
                    _gameNoticeData.Add(notice);
            }
        }
    }
    
    // 智能Tab切换：如果活动公告为空，自动切换到游戏公告Tab
    if (_currentFilter == NoticeCategoryFilter.Activity 
        && _activityNoticeData.Count == 0 
        && _gameNoticeData.Count > 0)
    {
        SetNoticeCategory(NoticeCategoryFilter.Game, true);
        return;
    }
    
    ApplyFilter(_currentFilter);
}
```

**`EnsureNoticeModule` 懒加载**：`NoticeSDKModule` 只在第一次使用时获取，而不是在 `Initialize` 里就获取。这是懒初始化模式——如果玩家从不打开公告，就不会初始化这个 SDK 模块。

**智能Tab自动切换**：如果活动公告列表为空（本次版本没有活动），但有游戏公告，自动切换到游戏公告 Tab。这比"打开面板显示空的活动列表"的体验好得多，减少了"打开了什么都没有"的尴尬。

---

## Tab 切换的双状态机

```csharp
private void UpdateTabState()
{
    bool isActivity = _currentFilter == NoticeCategoryFilter.Activity;
    
    // 1. 按钮可交互性：当前选中的 Tab 不可点击（避免重复点击）
    u_ComActivityAncButton.interactable = !isActivity;
    u_ComGameAncButton.interactable = isActivity;
    
    // 2. 每个 Tab 有两个状态选择器（选中态/未选中态的图标切换）
    u_ComSelectstateswitch.ApplyState(isActivity ? 1 : 0);    // 活动Tab的图标
    u_ComSelectstateswitch_1.ApplyState(isActivity ? 0 : 1);  // 游戏Tab的图标
    
    // 3. 右侧内容区的标题
    u_ComTxt_TipsTextMeshProUGUI.text = isActivity ? "活动公告" : "游戏公告";
}
```

**双状态选择器**：

注意 `u_ComSelectstateswitch` 和 `u_ComSelectstateswitch_1` 的状态是相反的：
- 活动Tab选中：`stateswitch=1`（选中图标），`stateswitch_1=0`（未选中图标）
- 游戏Tab选中：`stateswitch=0`（未选中图标），`stateswitch_1=1`（选中图标）

这意味着两个 Tab 按钮各自有一个状态组件，当一个处于"选中状态"，另一个自动处于"未选中状态"。通过对称赋值（`isActivity ? 1 : 0` 和 `isActivity ? 0 : 1`），一行代码同时更新两个 Tab 的视觉状态。

---

## 循环列表的选中追踪

```csharp
private int _selectedIndex = -1;

private void ApplyFilter(NoticeCategoryFilter filter)
{
    // 获取过滤后的数据
    List<NoticeData> source = filter == NoticeCategoryFilter.Activity 
        ? _activityNoticeData 
        : _gameNoticeData;
    _filteredNoticeData.Clear();
    _filteredNoticeData.AddRange(source);
    
    // 刷新循环列表
    _noticeItemScroll.SetDataRefresh(_filteredNoticeData);
    UpdateEmptyState(_filteredNoticeData.Count > 0);
    
    if (_filteredNoticeData.Count == 0)
    {
        _selectedIndex = -1;
        ShowNoticeDetail(null);  // 清空详情区
        return;
    }
    
    // 恢复选中状态（保持上次选中的索引，如果超出范围则选第一条）
    _selectedIndex = Mathf.Clamp(_selectedIndex, 0, _filteredNoticeData.Count - 1);
    _noticeItemScroll.OnClickItem(_selectedIndex);       // 触发选中
    _noticeItemScroll.ScrollToCellImmediately(_selectedIndex);  // 滚动到选中位置
}
```

`_selectedIndex = -1` 是"无选中"的初始值。切换 Tab 时，`Mathf.Clamp` 确保 `_selectedIndex` 在有效范围内：
- 如果原来是第3条（索引2），新 Tab 只有2条（索引0-1），Clamp 后变为1（最后一条）
- 如果原来是 -1（无选中），Clamp(−1, 0, n) = 0，自动选第一条

`ScrollToCellImmediately` 将循环列表立即滚动到选中条目（无动画）。"Immediately"表示瞬间跳转，区别于 `ScrollToCell`（带滚动动画）。切换 Tab 时用立即跳转更自然。

---

## 图片公告的版本控制异步加载

```csharp
private int _noticeDetailVersion;

private void ShowNoticeDetail(NoticeData data)
{
    string picUrl = data?.NoticePicUrl;
    
    // 递增版本号（每次点击新公告版本+1）
    int renderVersion = ++_noticeDetailVersion;
    
    if (string.IsNullOrWhiteSpace(picUrl))
    {
        ShowNoticeTextDetail(data?.Content ?? "");  // 纯文字公告
        return;
    }
    
    ShowPictureLayout();  // 显示图片布局（先占位）
    ShowPictureNoticeAsync(picUrl, renderVersion, data.Content).Coroutine();
}

private async ETTask ShowPictureNoticeAsync(string picUrl, int renderVersion, string fallbackContent)
{
    // 优先查本地缓存
    if (_noticeSpriteCache.TryGetValue(picUrl, out Sprite cachedSprite) && cachedSprite != null)
    {
        if (renderVersion == _noticeDetailVersion)  // 版本一致才显示
            ApplyNoticeSprite(cachedSprite);
        return;
    }
    
    // 从网络下载图片
    using var request = UnityWebRequestTexture.GetTexture(picUrl);
    await request.SendWebRequest();
    
    // 版本检查：下载期间可能点击了其他公告
    if (renderVersion != _noticeDetailVersion)
    {
        // 版本不一致，这次加载的图片已过期，丢弃
        return;
    }
    
    if (request.result == UnityWebRequest.Result.Success)
    {
        var texture = DownloadHandlerTexture.GetContent(request);
        var sprite = Sprite.Create(texture, new Rect(0, 0, texture.width, texture.height), new Vector2(0.5f, 0.5f));
        
        // 缓存（避免重复下载）
        _noticeSpriteCache[picUrl] = sprite;
        ApplyNoticeSprite(sprite);
    }
    else
    {
        // 下载失败，降级显示文字内容
        ShowNoticeTextDetail(fallbackContent);
    }
}
```

**版本控制的重要性**：

场景：玩家依次点击了公告A（有图片，需要3秒加载）和公告B（纯文字，立即显示），然后等待。

如果没有版本控制：
1. 公告A的图片3秒后加载完，覆盖了当前显示的公告B内容，显示错误图片

有版本控制：
1. 点击A：`renderVersion = 1`，开始加载A的图片
2. 点击B：`renderVersion = 2`，立即显示B的文字（版本已变为2）
3. A的图片加载完：检查 `renderVersion(1) != _noticeDetailVersion(2)`，丢弃，不显示

这是异步 UI 编程中"过时请求处理"的标准模式。

---

## 图片缓存的键：忽略大小写

```csharp
private readonly Dictionary<string, Sprite> _noticeSpriteCache 
    = new(StringComparer.OrdinalIgnoreCase);  // 忽略大小写的 URL 键
```

URL 可能在不同情况下大小写不一致（`https://example.com/Img.png` vs `https://example.com/img.png`），使用大小写不敏感的字典比较器，避免同一张图片被下载两次。

---

## 空状态处理

```csharp
private void UpdateEmptyState(bool hasNotice)
{
    u_ComPanel_AnnouncementRectTransform.gameObject.Active(hasNotice);   // 有公告
    u_ComPanel_EmptyRectTransform.gameObject.Active(!hasNotice);         // 无公告
}
```

设计规范：有内容和无内容两种状态，用两个不同的节点展示，而不是在同一个节点里修改文字。

无公告时显示"暂无公告"的插图和文字（`EmptyRectTransform`），有公告时显示列表（`AnnouncementRectTransform`）。两个状态相互排斥（`Active(true)` 和 `Active(false)` 同时设置）。

---

## 关闭时的资源清理

```csharp
protected override void OnDestroy()
{
    DisposeNoticeSpriteCache();
    base.OnDestroy();
}

private void DisposeNoticeSpriteCache()
{
    foreach (var sprite in _noticeSpriteCache.Values)
    {
        if (sprite != null)
            Destroy(sprite.texture);  // 销毁纹理（Sprite.Create 创建的需要手动销毁）
    }
    _noticeSpriteCache.Clear();
}
```

`Sprite.Create(texture, ...)` 创建的 Sprite 不会被 GC 自动回收（因为 Unity 的 Texture 是非托管资源）。必须手动 `Destroy(sprite.texture)` 才能释放显存。

**注意**：只需要 Destroy `texture`（非托管资源），不需要 Destroy `sprite`（Unity 会自动清理）。弄反了可能导致内存泄漏或 NullReferenceException。

---

## 总结

公告系统展示了企业级应用开发的几个关键实践：

1. **懒加载 SDK 模块**：首次使用时才获取，避免不必要的初始化
2. **智能 Tab 切换**：空列表时自动切换到有内容的 Tab
3. **双状态对称更新**：两个互斥状态用 `isActive ? 1 : 0` 和 `isActive ? 0 : 1` 同步更新
4. **版本控制异步加载**：递增版本号，过期的图片加载结果直接丢弃
5. **图片缓存**：URL 为键（大小写不敏感），避免重复下载
6. **降级处理**：图片加载失败，显示文字内容作为兜底
7. **资源清理**：`OnDestroy` 中手动销毁 Texture，防止显存泄漏
