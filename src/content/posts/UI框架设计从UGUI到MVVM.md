---
title: UI 框架设计：从 UGUI 基础到 MVC/MVVM 架构
published: 2026-03-21
description: "系统讲解大型游戏项目 UI 框架的设计方法，从 UGUI 渲染原理到 UI 分层管理、面板生命周期、数据绑定、MVC/MVVM 实践，帮助你设计出可扩展的 UI 框架。"
tags: [UGUI, UI框架, Unity, 架构设计, MVVM]
category: 架构设计
draft: false
---

## 为什么需要 UI 框架

直接用 UGUI 开发 UI 的问题：
- 代码和界面强耦合，策划改一个按钮位置，程序必须改代码
- 不同界面之间互相持有引用，形成网状依赖
- UI 的显示/隐藏逻辑分散各处，无法统一管理
- 数据变化时需要手动更新 UI，容易遗漏

UI 框架要解决的核心问题：
1. **界面管理**：统一的界面打开/关闭/层级管理
2. **数据同步**：数据变化自动反映到 UI
3. **解耦**：UI 层和逻辑层互不依赖

---

## 一、UGUI 渲染原理回顾

### 1.1 Canvas 与 DrawCall

```
UGUI 渲染流程：
  Canvas 收集所有 UI 元素 → 合批（Batching）→ 提交 DrawCall

合批条件（必须同时满足）：
  1. 同一个 Canvas
  2. 相同的材质（相同纹理图集）
  3. 相同的渲染状态
  4. 没有被其他图层的元素打断

常见合批失败原因：
  - 不同图集的图片交替出现
  - Text 和 Image 层叠（Text 默认用不同材质）
  - Mask 会强制打断合批
```

### 1.2 Rebuild 与 Reatch 的触发

```
每次 UI 发生变化：
  几何变化（位移/缩放/顶点变化）→ Rebuild（重新构建网格）
  材质/纹理变化 → Rebatch（重新合批）
  
Rebuild 代价 >> Rebatch 代价

优化原则：
  - 动态 UI（频繁移动的）和静态 UI 分开 Canvas
  - 更新频繁的文字（如血条数字）单独一个 Canvas
  - 不要在动画中频繁改变 rectTransform（触发 Rebuild）
```

### 1.3 图集（Sprite Atlas）的使用

```csharp
// 正确使用 Sprite Atlas
// 1. 创建 Sprite Atlas（Assets → Create → 2D → Sprite Atlas）
// 2. 将同一界面的图片放入同一 Atlas
// 3. 代码加载

// 使用 Addressables 加载图集
public async UniTask<Sprite> LoadSpriteAsync(string atlasName, string spriteName)
{
    var atlas = await Addressables.LoadAssetAsync<SpriteAtlas>(atlasName).Task;
    return atlas.GetSprite(spriteName);
}

// 图集分组建议：
// - 主界面图集：main_ui_atlas
// - 战斗界面图集：battle_ui_atlas
// - 公共图标图集：common_icon_atlas
// - 同一界面的图片尽量放一个图集（减少 DrawCall）
```

---

## 二、UI 面板管理系统

### 2.1 面板的层级设计

```csharp
public enum UILayer
{
    Background  = 0,    // 背景（地图、场景遮罩）
    GameHUD     = 100,  // 游戏内 HUD（血条、技能栏）
    Normal      = 200,  // 普通面板（背包、商店）
    PopUp       = 300,  // 弹窗（确认框、奖励）
    Loading     = 400,  // 加载界面
    TopBar      = 500,  // 顶部常驻 UI
    System      = 600,  // 系统级（网络断开、强更提示）
    Debug       = 700,  // 调试 UI
}
```

### 2.2 UI 面板基类

```csharp
/// <summary>
/// 所有 UI 面板的基类
/// </summary>
public abstract class UIPanel : MonoBehaviour
{
    public UILayer Layer { get; protected set; }
    public bool IsVisible { get; private set; }
    
    // 面板打开时的参数
    private object _openArgs;
    
    /// <summary>
    /// 面板被创建时调用（只调用一次）
    /// </summary>
    protected virtual void OnInit() { }
    
    /// <summary>
    /// 面板打开时调用（每次显示都调用）
    /// </summary>
    protected virtual void OnOpen(object args) { }
    
    /// <summary>
    /// 面板关闭时调用
    /// </summary>
    protected virtual void OnClose() { }
    
    /// <summary>
    /// 面板被销毁时调用（清理资源）
    /// </summary>
    protected virtual void OnDestroyed() { }
    
    // 由 UIManager 调用
    internal void Init() { OnInit(); }
    
    internal void Open(object args)
    {
        _openArgs = args;
        gameObject.SetActive(true);
        IsVisible = true;
        OnOpen(args);
    }
    
    internal void Close()
    {
        OnClose();
        IsVisible = false;
        gameObject.SetActive(false);
    }
    
    internal void Destroy()
    {
        OnDestroyed();
        Destroy(gameObject);
    }
    
    // 便捷方法：子类调用关闭自身
    protected void CloseSelf() => UIManager.Instance.Close(GetType());
    
    // 便捷方法：子类打开其他面板
    protected void OpenPanel<T>(object args = null) where T : UIPanel
        => UIManager.Instance.Open<T>(args);
}
```

### 2.3 UI 管理器

```csharp
/// <summary>
/// UI 管理器：统一管理所有面板的生命周期和层级
/// </summary>
public class UIManager : Singleton<UIManager>
{
    // 已创建的面板缓存
    private readonly Dictionary<Type, UIPanel> _panels = new();
    
    // 每个层级的 Canvas
    private readonly Dictionary<UILayer, Canvas> _layerCanvases = new();
    
    // 面板显示栈（用于回退）
    private readonly Stack<UIPanel> _panelStack = new();
    
    protected override void Init()
    {
        // 创建各层级的 Canvas
        foreach (UILayer layer in Enum.GetValues(typeof(UILayer)))
        {
            var canvas = CreateLayerCanvas(layer);
            _layerCanvases[layer] = canvas;
        }
    }
    
    /// <summary>
    /// 打开面板
    /// </summary>
    public T Open<T>(object args = null) where T : UIPanel
    {
        var type = typeof(T);
        
        if (!_panels.TryGetValue(type, out var panel))
        {
            // 第一次打开：从 Addressables 加载 Prefab 并实例化
            panel = CreatePanel<T>();
            _panels[type] = panel;
        }
        
        if (!panel.IsVisible)
        {
            panel.Open(args);
            _panelStack.Push(panel);
        }
        
        return (T)panel;
    }
    
    /// <summary>
    /// 关闭面板
    /// </summary>
    public void Close<T>() where T : UIPanel => Close(typeof(T));
    
    public void Close(Type type)
    {
        if (_panels.TryGetValue(type, out var panel))
            panel.Close();
    }
    
    /// <summary>
    /// 关闭最顶层面板（Back 键）
    /// </summary>
    public void CloseTop()
    {
        while (_panelStack.Count > 0)
        {
            var top = _panelStack.Pop();
            if (top.IsVisible)
            {
                top.Close();
                return;
            }
        }
    }
    
    /// <summary>
    /// 异步打开面板（等待资源加载）
    /// </summary>
    public async UniTask<T> OpenAsync<T>(object args = null, CancellationToken ct = default) 
        where T : UIPanel
    {
        var type = typeof(T);
        
        if (!_panels.TryGetValue(type, out var panel))
        {
            panel = await CreatePanelAsync<T>(ct);
            _panels[type] = panel;
        }
        
        panel.Open(args);
        _panelStack.Push(panel);
        return (T)panel;
    }
    
    private T CreatePanel<T>() where T : UIPanel
    {
        // 同步加载（用于非异步场景）
        var prefab = Resources.Load<GameObject>($"UI/{typeof(T).Name}");
        var go = Instantiate(prefab, _layerCanvases[UILayer.Normal].transform);
        var panel = go.GetComponent<T>();
        panel.Init();
        return panel;
    }
    
    private async UniTask<T> CreatePanelAsync<T>(CancellationToken ct) where T : UIPanel
    {
        var handle = Addressables.LoadAssetAsync<GameObject>($"UI/{typeof(T).Name}");
        var prefab = await handle.WithCancellation(ct);
        
        var layerCanvas = _layerCanvases[UILayer.Normal]; // 默认层
        var go = Instantiate(prefab, layerCanvas.transform);
        Addressables.Release(handle); // 释放 handle，保留实例
        
        var panel = go.GetComponent<T>();
        panel.Init();
        return panel;
    }
    
    private Canvas CreateLayerCanvas(UILayer layer)
    {
        var go = new GameObject($"Canvas_{layer}");
        go.transform.SetParent(transform);
        
        var canvas = go.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = (int)layer;
        
        go.AddComponent<GraphicRaycaster>();
        
        var scaler = go.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);
        scaler.matchWidthOrHeight = 0.5f;
        
        return canvas;
    }
}
```

---

## 三、数据绑定：MVVM 模式

### 3.1 响应式属性（Reactive Property）

```csharp
/// <summary>
/// 响应式属性：值变化时自动通知订阅者
/// </summary>
public class ReactiveProperty<T>
{
    private T _value;
    private readonly List<Action<T>> _observers = new();
    
    public T Value
    {
        get => _value;
        set
        {
            if (EqualityComparer<T>.Default.Equals(_value, value)) return;
            _value = value;
            NotifyObservers(value);
        }
    }
    
    public void Subscribe(Action<T> observer)
    {
        _observers.Add(observer);
        observer(_value); // 立即触发一次（同步当前值）
    }
    
    public void Unsubscribe(Action<T> observer) => _observers.Remove(observer);
    
    private void NotifyObservers(T value)
    {
        for (int i = _observers.Count - 1; i >= 0; i--)
            _observers[i](value);
    }
    
    public static implicit operator T(ReactiveProperty<T> prop) => prop._value;
}

// 游戏数据 ViewModel
public class PlayerViewModel
{
    public ReactiveProperty<int> HP = new();
    public ReactiveProperty<int> MaxHP = new();
    public ReactiveProperty<int> MP = new();
    public ReactiveProperty<int> Level = new();
    public ReactiveProperty<string> PlayerName = new();
    public ReactiveProperty<float> HPPercent = new();
    
    // 从游戏数据同步到 ViewModel
    public void SyncFrom(PlayerData data)
    {
        HP.Value = data.CurrentHP;
        MaxHP.Value = data.MaxHP;
        MP.Value = data.CurrentMP;
        Level.Value = data.Level;
        PlayerName.Value = data.Name;
        HPPercent.Value = data.MaxHP > 0 ? (float)data.CurrentHP / data.MaxHP : 0f;
    }
}
```

### 3.2 UI 自动绑定

```csharp
/// <summary>
/// HP 血条组件：自动绑定到 PlayerViewModel
/// </summary>
public class HPBarView : UIPanel
{
    [SerializeField] private Slider _hpSlider;
    [SerializeField] private Text _hpText;
    [SerializeField] private Text _playerNameText;
    
    private PlayerViewModel _viewModel;
    private readonly List<Action> _unbindActions = new();
    
    protected override void OnOpen(object args)
    {
        _viewModel = args as PlayerViewModel ?? ServiceLocator.Get<PlayerViewModel>();
        
        // 绑定：ViewModel 变化 → 自动更新 UI
        Bind(_viewModel.HP, hp => _hpText.text = $"{hp}/{_viewModel.MaxHP.Value}");
        Bind(_viewModel.HPPercent, percent => _hpSlider.value = percent);
        Bind(_viewModel.PlayerName, name => _playerNameText.text = name);
    }
    
    protected override void OnClose()
    {
        // 取消所有绑定
        foreach (var unbind in _unbindActions) unbind();
        _unbindActions.Clear();
    }
    
    /// <summary>
    /// 绑定帮助方法：自动管理订阅/取消订阅
    /// </summary>
    private void Bind<T>(ReactiveProperty<T> property, Action<T> updateUI)
    {
        property.Subscribe(updateUI);
        _unbindActions.Add(() => property.Unsubscribe(updateUI));
    }
}
```

### 3.3 列表绑定（背包/技能列表）

```csharp
/// <summary>
/// 响应式列表
/// </summary>
public class ReactiveList<T>
{
    private readonly List<T> _list = new();
    
    public event Action<int, T> OnItemAdded;
    public event Action<int, T> OnItemRemoved;
    public event Action<int, T, T> OnItemChanged;
    public event Action OnReset;
    
    public int Count => _list.Count;
    public T this[int index] => _list[index];
    
    public void Add(T item)
    {
        _list.Add(item);
        OnItemAdded?.Invoke(_list.Count - 1, item);
    }
    
    public void RemoveAt(int index)
    {
        var item = _list[index];
        _list.RemoveAt(index);
        OnItemRemoved?.Invoke(index, item);
    }
    
    public void Set(int index, T item)
    {
        var old = _list[index];
        _list[index] = item;
        OnItemChanged?.Invoke(index, old, item);
    }
    
    public void Reset(IEnumerable<T> items)
    {
        _list.Clear();
        _list.AddRange(items);
        OnReset?.Invoke();
    }
}

/// <summary>
/// 使用对象池的高效列表视图（适用于背包、技能列表等）
/// </summary>
public class RecyclingListView<TItem, TData> : MonoBehaviour 
    where TItem : MonoBehaviour
{
    [SerializeField] private ScrollRect _scrollRect;
    [SerializeField] private TItem _itemPrefab;
    [SerializeField] private float _itemHeight = 100f;
    
    private readonly List<TItem> _visibleItems = new();
    private readonly Stack<TItem> _pool = new();
    private ReactiveList<TData> _dataList;
    private Action<TItem, TData> _bindItem;
    
    private int _firstVisibleIndex;
    private int _lastVisibleIndex;
    
    public void Initialize(ReactiveList<TData> dataList, Action<TItem, TData> bindItem)
    {
        _dataList = dataList;
        _bindItem = bindItem;
        
        _dataList.OnReset += Refresh;
        _dataList.OnItemAdded += (_, _) => Refresh();
        _dataList.OnItemRemoved += (_, _) => Refresh();
        
        _scrollRect.onValueChanged.AddListener(_ => UpdateVisibleItems());
        
        Refresh();
    }
    
    private void Refresh()
    {
        // 更新 Content 高度
        var contentHeight = _dataList.Count * _itemHeight;
        ((RectTransform)_scrollRect.content).sizeDelta = new Vector2(0, contentHeight);
        
        // 回收所有可见项
        foreach (var item in _visibleItems)
            ReturnToPool(item);
        _visibleItems.Clear();
        
        UpdateVisibleItems();
    }
    
    private void UpdateVisibleItems()
    {
        float scrollPos = _scrollRect.content.anchoredPosition.y;
        float viewportHeight = ((RectTransform)_scrollRect.viewport).rect.height;
        
        int newFirst = Mathf.Max(0, (int)(scrollPos / _itemHeight));
        int newLast = Mathf.Min(_dataList.Count - 1, 
                                (int)((scrollPos + viewportHeight) / _itemHeight));
        
        // 回收超出视野的项
        for (int i = _visibleItems.Count - 1; i >= 0; i--)
        {
            int dataIndex = GetDataIndex(_visibleItems[i]);
            if (dataIndex < newFirst || dataIndex > newLast)
            {
                ReturnToPool(_visibleItems[i]);
                _visibleItems.RemoveAt(i);
            }
        }
        
        // 创建新进入视野的项
        for (int i = newFirst; i <= newLast; i++)
        {
            if (!HasVisibleItemAt(i))
            {
                var item = GetFromPool();
                PositionItem(item, i);
                _bindItem(item, _dataList[i]);
                _visibleItems.Add(item);
            }
        }
        
        _firstVisibleIndex = newFirst;
        _lastVisibleIndex = newLast;
    }
    
    private TItem GetFromPool()
    {
        if (_pool.Count > 0)
        {
            var item = _pool.Pop();
            item.gameObject.SetActive(true);
            return item;
        }
        return Instantiate(_itemPrefab, _scrollRect.content);
    }
    
    private void ReturnToPool(TItem item)
    {
        item.gameObject.SetActive(false);
        _pool.Push(item);
    }
    
    private void PositionItem(TItem item, int index)
    {
        var rt = (RectTransform)item.transform;
        rt.anchoredPosition = new Vector2(0, -index * _itemHeight);
    }
    
    private bool HasVisibleItemAt(int index)
    {
        foreach (var item in _visibleItems)
            if (GetDataIndex(item) == index) return true;
        return false;
    }
    
    private int GetDataIndex(TItem item)
    {
        var rt = (RectTransform)item.transform;
        return (int)(-rt.anchoredPosition.y / _itemHeight);
    }
}
```

---

## 四、UI 动画与过渡

### 4.1 面板打开/关闭动画

```csharp
/// <summary>
/// 带动画的 UI 面板基类
/// </summary>
public abstract class AnimatedUIPanel : UIPanel
{
    [SerializeField] private float _openDuration = 0.3f;
    [SerializeField] private float _closeDuration = 0.2f;
    
    private CanvasGroup _canvasGroup;
    private RectTransform _rectTransform;
    
    protected override void OnInit()
    {
        _canvasGroup = GetComponent<CanvasGroup>() ?? gameObject.AddComponent<CanvasGroup>();
        _rectTransform = GetComponent<RectTransform>();
    }
    
    protected override void OnOpen(object args)
    {
        // 播放打开动画
        gameObject.SetActive(true);
        PlayOpenAnimation().Forget();
    }
    
    protected override void OnClose()
    {
        // 播放关闭动画，然后隐藏
        PlayCloseAnimation().Forget();
    }
    
    private async UniTaskVoid PlayOpenAnimation()
    {
        _canvasGroup.alpha = 0f;
        _rectTransform.localScale = Vector3.one * 0.8f;
        
        float elapsed = 0f;
        while (elapsed < _openDuration)
        {
            elapsed += Time.unscaledDeltaTime;
            float t = Mathf.Clamp01(elapsed / _openDuration);
            float eased = EaseOutBack(t);
            
            _canvasGroup.alpha = Mathf.Lerp(0f, 1f, t);
            _rectTransform.localScale = Vector3.Lerp(
                Vector3.one * 0.8f, Vector3.one, eased);
            
            await UniTask.NextFrame();
        }
        
        _canvasGroup.alpha = 1f;
        _rectTransform.localScale = Vector3.one;
    }
    
    private async UniTaskVoid PlayCloseAnimation()
    {
        float elapsed = 0f;
        float startAlpha = _canvasGroup.alpha;
        
        while (elapsed < _closeDuration)
        {
            elapsed += Time.unscaledDeltaTime;
            float t = Mathf.Clamp01(elapsed / _closeDuration);
            
            _canvasGroup.alpha = Mathf.Lerp(startAlpha, 0f, t);
            _rectTransform.localScale = Vector3.Lerp(
                Vector3.one, Vector3.one * 0.9f, t);
            
            await UniTask.NextFrame();
        }
        
        gameObject.SetActive(false);
    }
    
    // 缓动函数：弹簧效果
    private static float EaseOutBack(float t)
    {
        const float c1 = 1.70158f;
        const float c3 = c1 + 1f;
        return 1f + c3 * Mathf.Pow(t - 1f, 3f) + c1 * Mathf.Pow(t - 1f, 2f);
    }
}
```

---

## 五、常见 UI 性能问题解决方案

### 5.1 文字频繁更新导致的 Rebuild

```csharp
// ❌ 每帧更新时间导致大量 Rebuild
void Update()
{
    timerText.text = GetTimeString(); // 即使值没变，text 赋值也会触发 Rebuild
}

// ✅ 只在值变化时更新
private int _lastDisplayedSeconds = -1;

void Update()
{
    int currentSeconds = (int)remainingTime;
    if (currentSeconds != _lastDisplayedSeconds)
    {
        _lastDisplayedSeconds = currentSeconds;
        timerText.text = GetTimeString(currentSeconds);
    }
}

// ✅ 使用 TMP 的高效数字格式化
[SerializeField] private TextMeshProUGUI _scoreText;
private int _lastScore = -1;

void UpdateScore(int score)
{
    if (score == _lastScore) return;
    _lastScore = score;
    // TMP 对数字更新有优化
    _scoreText.SetText("{0}", score);
}
```

### 5.2 ScrollRect 性能优化

```csharp
// 关闭不必要的 Pixel Perfect（开启后每帧强制 Rebuild）
canvas.pixelPerfect = false;

// 对于长列表，启用虚拟化（上面的 RecyclingListView 已实现）

// 禁用 ScrollRect 的惯性（如果不需要）
scrollRect.inertia = false;

// 关闭 Scroll Rect 的 Elastic 模式（如果不需要弹性）
scrollRect.movementType = ScrollRect.MovementType.Clamped;
```

---

## 总结

设计 UI 框架的核心原则：

1. **分离关注点**：数据（ViewModel）、显示（View）、逻辑（Controller）各司其职
2. **统一生命周期**：所有面板通过 UIManager 统一管理，避免自行 SetActive
3. **响应式数据**：数据变化自动同步到 UI，减少手动更新代码
4. **性能意识**：图集合批、避免不必要的 Rebuild、长列表虚拟化

> **下一篇**：[资源管理系统设计：从 AssetBundle 到 Addressables 全解析]
