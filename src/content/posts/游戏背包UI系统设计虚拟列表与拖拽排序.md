---
title: 游戏背包UI系统设计：虚拟列表与拖拽排序
published: 2026-03-31
description: 全面解析游戏背包UI系统的工程设计，涵盖虚拟列表（只渲染可见格子，支持千级物品无卡顿）、物品拖拽换位与装备栏交互、物品格子对象池、右键菜单系统、物品筛选/排序、物品合并与拆分，以及多分辨率的背包格子自适应布局。
tags: [Unity, 背包系统, 虚拟列表, UI设计, 游戏开发]
category: 游戏UI
draft: false
encryptedKey:henhaoji123
---

## 一、虚拟列表（Virtual Scroll）

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// 高性能虚拟滚动列表
/// 只渲染视口内可见的 Item，支持万级数据无卡顿
/// </summary>
public class VirtualScrollList : MonoBehaviour
{
    [Header("配置")]
    [SerializeField] private RectTransform viewport;       // 视口
    [SerializeField] private RectTransform content;        // 内容容器
    [SerializeField] private GameObject itemPrefab;        // Item 预制体
    [SerializeField] private float itemHeight = 100f;      // Item 高度（Grid用）
    [SerializeField] private float itemWidth = 100f;       // Item 宽度
    [SerializeField] private int columns = 5;              // 列数（背包格子）
    [SerializeField] private float spacing = 8f;           // 间距

    private ScrollRect scrollRect;
    private List<object> dataSource = new List<object>();
    private Queue<RectTransform> itemPool = new Queue<RectTransform>();
    private Dictionary<int, RectTransform> visibleItems = new Dictionary<int, RectTransform>();

    // 当前可见范围
    private int firstVisibleRow;
    private int lastVisibleRow;

    public Action<GameObject, object, int> OnItemRefresh; // go, data, index

    void Awake()
    {
        scrollRect = GetComponent<ScrollRect>();
        scrollRect.onValueChanged.AddListener(OnScrollValueChanged);
    }

    public void SetData(List<object> data)
    {
        dataSource = data;
        UpdateContentSize();
        RefreshVisible();
    }

    void UpdateContentSize()
    {
        int totalRows = Mathf.CeilToInt((float)dataSource.Count / columns);
        float totalHeight = totalRows * (itemHeight + spacing) + spacing;
        content.sizeDelta = new Vector2(content.sizeDelta.x, totalHeight);
    }

    void OnScrollValueChanged(Vector2 _) => RefreshVisible();

    void RefreshVisible()
    {
        float viewportHeight = viewport.rect.height;
        float scrollY = content.anchoredPosition.y;

        // 计算可见行范围（加1缓冲行）
        int newFirst = Mathf.Max(0, (int)(scrollY / (itemHeight + spacing)) - 1);
        int newLast = Mathf.Min(
            Mathf.CeilToInt((float)dataSource.Count / columns),
            newFirst + (int)(viewportHeight / (itemHeight + spacing)) + 2);

        // 回收不可见的行
        var toRemove = new List<int>();
        foreach (var kv in visibleItems)
        {
            int row = kv.Key;
            if (row < newFirst || row > newLast)
            {
                ReturnToPool(kv.Value);
                toRemove.Add(row);
            }
        }
        foreach (int r in toRemove)
            visibleItems.Remove(r);

        // 显示新进入视野的行
        for (int row = newFirst; row <= newLast; row++)
        {
            if (!visibleItems.ContainsKey(row))
            {
                for (int col = 0; col < columns; col++)
                {
                    int dataIndex = row * columns + col;
                    if (dataIndex >= dataSource.Count) break;

                    var itemGo = GetFromPool();
                    var itemRect = itemGo.GetComponent<RectTransform>();

                    // 设置位置
                    float x = spacing + col * (itemWidth + spacing) + itemWidth / 2f;
                    float y = -(spacing + row * (itemHeight + spacing) + itemHeight / 2f);
                    itemRect.anchoredPosition = new Vector2(x, y);
                    itemRect.sizeDelta = new Vector2(itemWidth, itemHeight);

                    OnItemRefresh?.Invoke(itemGo, dataSource[dataIndex], dataIndex);
                }

                visibleItems[row] = null; // 标记此行已显示
            }
        }

        firstVisibleRow = newFirst;
        lastVisibleRow = newLast;
    }

    RectTransform GetFromPool()
    {
        if (itemPool.Count > 0)
        {
            var item = itemPool.Dequeue();
            item.gameObject.SetActive(true);
            return item;
        }

        var go = Instantiate(itemPrefab, content);
        return go.GetComponent<RectTransform>();
    }

    void ReturnToPool(RectTransform item)
    {
        if (item == null) return;
        item.gameObject.SetActive(false);
        itemPool.Enqueue(item);
    }
}
```

---

## 二、物品拖拽系统

```csharp
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

/// <summary>
/// 物品格子拖拽组件
/// </summary>
public class InventorySlot : MonoBehaviour,
    IBeginDragHandler, IDragHandler, IEndDragHandler,
    IDropHandler, IPointerClickHandler
{
    [SerializeField] private Image iconImage;
    [SerializeField] private Text countText;
    [SerializeField] private GameObject selectedOverlay;
    [SerializeField] private GameObject emptySlot;

    public int SlotIndex { get; private set; }
    public ItemData Item { get; private set; }

    private static InventorySlot draggingSlot;
    private static GameObject dragGhost;        // 拖拽时的幽灵图标
    private Canvas rootCanvas;
    private RectTransform rectTransform;

    void Awake()
    {
        rectTransform = GetComponent<RectTransform>();
        rootCanvas = GetComponentInParent<Canvas>();
    }

    public void Setup(int index, ItemData item)
    {
        SlotIndex = index;
        Item = item;

        bool hasItem = item != null;
        iconImage.gameObject.SetActive(hasItem);
        emptySlot.SetActive(!hasItem);

        if (hasItem)
        {
            iconImage.sprite = item.Icon;
            countText.text = item.Count > 1 ? item.Count.ToString() : "";
            countText.gameObject.SetActive(item.Count > 1);
        }
    }

    public void OnBeginDrag(PointerEventData eventData)
    {
        if (Item == null) return;

        draggingSlot = this;

        // 创建拖拽幽灵图标
        dragGhost = new GameObject("DragGhost");
        dragGhost.transform.SetParent(rootCanvas.transform, false);
        dragGhost.transform.SetAsLastSibling(); // 显示在最前面

        var ghostImg = dragGhost.AddComponent<Image>();
        ghostImg.sprite = Item.Icon;
        ghostImg.raycastTarget = false; // 不阻挡射线

        var ghostRect = dragGhost.GetComponent<RectTransform>();
        ghostRect.sizeDelta = rectTransform.sizeDelta;

        // 半透明
        ghostImg.color = new Color(1, 1, 1, 0.7f);

        // 原格子图标变暗
        iconImage.color = new Color(1, 1, 1, 0.3f);
    }

    public void OnDrag(PointerEventData eventData)
    {
        if (dragGhost == null) return;

        // 幽灵图标跟随鼠标
        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            rootCanvas.GetComponent<RectTransform>(),
            eventData.position,
            rootCanvas.worldCamera,
            out Vector2 localPos);

        dragGhost.GetComponent<RectTransform>().anchoredPosition = localPos;
    }

    public void OnEndDrag(PointerEventData eventData)
    {
        if (dragGhost != null)
        {
            Destroy(dragGhost);
            dragGhost = null;
        }

        if (iconImage != null)
            iconImage.color = Color.white;

        draggingSlot = null;
    }

    public void OnDrop(PointerEventData eventData)
    {
        if (draggingSlot == null || draggingSlot == this) return;

        // 通知背包管理器交换物品
        InventoryManager.Instance?.SwapItems(draggingSlot.SlotIndex, SlotIndex);
    }

    public void OnPointerClick(PointerEventData eventData)
    {
        if (eventData.button == PointerEventData.InputButton.Right)
        {
            // 右键菜单
            if (Item != null)
                ContextMenuManager.Instance?.ShowItemMenu(Item, SlotIndex,
                    eventData.position);
        }
        else if (eventData.clickCount == 2)
        {
            // 双击使用/装备
            InventoryManager.Instance?.UseItem(SlotIndex);
        }
    }
}
```

---

## 三、右键上下文菜单

```csharp
/// <summary>
/// 物品右键菜单
/// </summary>
public class ItemContextMenu : MonoBehaviour
{
    [SerializeField] private GameObject menuRoot;
    [SerializeField] private Transform buttonContainer;
    [SerializeField] private GameObject buttonPrefab;

    private static ItemContextMenu instance;
    public static ItemContextMenu Instance => instance;

    void Awake()
    {
        instance = this;
        menuRoot.SetActive(false);
    }

    public void Show(ItemData item, int slotIndex, Vector2 screenPos)
    {
        // 清除旧按钮
        foreach (Transform child in buttonContainer)
            Destroy(child.gameObject);

        // 根据物品类型动态生成菜单项
        var menuItems = BuildMenuItems(item, slotIndex);

        foreach (var menuItem in menuItems)
        {
            var btn = Instantiate(buttonPrefab, buttonContainer);
            btn.GetComponentInChildren<Text>().text = menuItem.Label;
            btn.GetComponent<Button>().onClick.AddListener(() =>
            {
                menuItem.Action?.Invoke();
                Hide();
            });
        }

        // 定位菜单（确保不超出屏幕边界）
        menuRoot.SetActive(true);
        PositionMenu(screenPos);
    }

    List<(string Label, Action Action)> BuildMenuItems(ItemData item, int slotIndex)
    {
        var items = new List<(string, Action)>();

        if (item.CanEquip)
            items.Add(("装备", () => InventoryManager.Instance.EquipItem(slotIndex)));

        if (item.CanUse)
            items.Add(("使用", () => InventoryManager.Instance.UseItem(slotIndex)));

        if (item.CanSell)
            items.Add(($"出售 ({item.SellPrice}金)", () => InventoryManager.Instance.SellItem(slotIndex)));

        items.Add(("查看详情", () => ItemDetailPanel.Instance.Show(item)));

        if (item.Count > 1)
            items.Add(("拆分", () => ItemSplitDialog.Instance.Show(item, slotIndex)));

        items.Add(("丢弃", () => InventoryManager.Instance.DiscardItem(slotIndex)));

        return items;
    }

    void PositionMenu(Vector2 screenPos)
    {
        var rect = menuRoot.GetComponent<RectTransform>();
        var canvas = GetComponentInParent<Canvas>();

        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            canvas.GetComponent<RectTransform>(),
            screenPos, canvas.worldCamera,
            out Vector2 localPos);

        // 防止超出屏幕右边和下边
        float menuWidth = rect.sizeDelta.x;
        float menuHeight = rect.sizeDelta.y;
        float canvasWidth = canvas.GetComponent<RectTransform>().rect.width;
        float canvasHeight = canvas.GetComponent<RectTransform>().rect.height;

        if (localPos.x + menuWidth > canvasWidth / 2)
            localPos.x -= menuWidth;
        if (localPos.y - menuHeight < -canvasHeight / 2)
            localPos.y += menuHeight;

        rect.anchoredPosition = localPos;
    }

    public void Hide() => menuRoot.SetActive(false);

    void Update()
    {
        // 点击外部关闭菜单
        if (menuRoot.activeSelf && Input.GetMouseButtonDown(0))
        {
            if (!RectTransformUtility.RectangleContainsScreenPoint(
                menuRoot.GetComponent<RectTransform>(),
                Input.mousePosition,
                GetComponentInParent<Canvas>().worldCamera))
            {
                Hide();
            }
        }
    }
}
```

---

## 四、背包设计最佳实践

| 功能 | 实现方案 | 关键点 |
|------|----------|--------|
| 大量格子渲染 | 虚拟滚动列表 | 只渲染可见区域 |
| 物品拖拽 | IBeginDragHandler等接口 | 幽灵图标+原位半透明 |
| 格子交换 | 拖放+索引交换 | 支持跨背包拖拽 |
| 右键菜单 | 动态生成按钮 | 根据物品类型过滤菜单项 |
| 物品排序 | 多维度排序 | 品质→类型→名称 |
| 性能 | 对象池+VirtualList | 避免创建/销毁大量格子 |
