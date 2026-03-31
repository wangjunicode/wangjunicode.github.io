---
title: 游戏UI框架设计：MVVM模式与数据绑定
published: 2026-03-31
description: 深度解析游戏UI系统的MVVM架构设计，涵盖ViewModel数据绑定机制（属性通知/命令绑定）、View层与Model层完全解耦、Observable属性系统、UI面板生命周期管理、数据驱动的列表刷新，以及结合Unity UI Toolkit和传统UGUI的混合实现方案。
tags: [Unity, UI框架, MVVM, 数据绑定, 架构设计]
category: 游戏UI
draft: false
---

## 一、MVVM架构概念

```
MVVM（Model-View-ViewModel）:

Model（数据层）
  ↕ 双向绑定
ViewModel（展示逻辑层）
  ↕ 数据绑定/命令
View（UI显示层）

优点：
- View 只负责显示，不包含业务逻辑
- ViewModel 可单独进行单元测试
- 数据变化自动更新UI，无需手动调用 UpdateUI()
```

---

## 二、Observable 属性系统

```csharp
using System;
using System.ComponentModel;
using UnityEngine;

/// <summary>
/// 可观察属性（属性变化时自动通知）
/// </summary>
public class ObservableProperty<T> : INotifyPropertyChanged
{
    private T _value;
    
    public event PropertyChangedEventHandler PropertyChanged;
    public event Action<T, T> OnValueChanged; // oldValue, newValue

    public T Value
    {
        get => _value;
        set
        {
            if (EqualityComparer<T>.Default.Equals(_value, value)) return;
            T old = _value;
            _value = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Value)));
            OnValueChanged?.Invoke(old, value);
        }
    }

    public ObservableProperty(T initialValue = default)
    {
        _value = initialValue;
    }

    public static implicit operator T(ObservableProperty<T> prop) => prop.Value;
    public override string ToString() => _value?.ToString() ?? "null";
}

/// <summary>
/// 可观察集合
/// </summary>
public class ObservableList<T> : System.Collections.ObjectModel.ObservableCollection<T>
{
    // 基于 ObservableCollection 实现，CollectionChanged 事件会在增删时触发
}
```

---

## 三、ViewModel 基类

```csharp
/// <summary>
/// ViewModel 基类
/// </summary>
public abstract class ViewModelBase : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler PropertyChanged;

    protected void NotifyPropertyChanged(string propertyName)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }

    protected bool SetProperty<T>(ref T field, T value, string propertyName)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        NotifyPropertyChanged(propertyName);
        return true;
    }
}

/// <summary>
/// 玩家信息 ViewModel
/// </summary>
public class PlayerInfoViewModel : ViewModelBase
{
    private string _nickname;
    private int _level;
    private float _currentHp;
    private float _maxHp;
    private long _gold;
    private int _expProgress;   // 0-100
    
    public string Nickname
    {
        get => _nickname;
        set => SetProperty(ref _nickname, value, nameof(Nickname));
    }
    
    public int Level
    {
        get => _level;
        set
        {
            if (SetProperty(ref _level, value, nameof(Level)))
                NotifyPropertyChanged(nameof(LevelDisplay));
        }
    }
    
    public string LevelDisplay => $"Lv.{_level}";
    
    public float CurrentHp
    {
        get => _currentHp;
        set
        {
            if (SetProperty(ref _currentHp, value, nameof(CurrentHp)))
            {
                NotifyPropertyChanged(nameof(HpRatio));
                NotifyPropertyChanged(nameof(HpDisplay));
            }
        }
    }
    
    public float MaxHp
    {
        get => _maxHp;
        set
        {
            if (SetProperty(ref _maxHp, value, nameof(MaxHp)))
                NotifyPropertyChanged(nameof(HpRatio));
        }
    }
    
    public float HpRatio => _maxHp > 0 ? _currentHp / _maxHp : 0f;
    public string HpDisplay => $"{Mathf.RoundToInt(_currentHp)}/{Mathf.RoundToInt(_maxHp)}";
    
    public long Gold
    {
        get => _gold;
        set => SetProperty(ref _gold, value, nameof(Gold));
    }
    
    public int ExpProgress
    {
        get => _expProgress;
        set => SetProperty(ref _expProgress, value, nameof(ExpProgress));
    }

    // ============ 从 Model 同步 ============

    public void SyncFromModel(PlayerData data)
    {
        Nickname = data.Nickname;
        Level = data.Level;
        MaxHp = data.MaxHp;
        CurrentHp = data.CurrentHp;
        Gold = data.Gold;
        ExpProgress = Mathf.RoundToInt((float)data.Exp / data.ExpToNextLevel * 100);
    }
}
```

---

## 四、View 数据绑定组件

```csharp
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// UI 绑定组件基类
/// </summary>
public abstract class UIBinding<TViewModel> : MonoBehaviour 
    where TViewModel : ViewModelBase
{
    protected TViewModel ViewModel { get; private set; }
    
    public void Bind(TViewModel vm)
    {
        if (ViewModel != null)
            ViewModel.PropertyChanged -= OnPropertyChanged;
        
        ViewModel = vm;
        vm.PropertyChanged += OnPropertyChanged;
        
        // 立即刷新所有绑定
        RefreshAll();
    }

    void OnDestroy()
    {
        if (ViewModel != null)
            ViewModel.PropertyChanged -= OnPropertyChanged;
    }

    protected abstract void OnPropertyChanged(object sender, 
        System.ComponentModel.PropertyChangedEventArgs e);
    protected abstract void RefreshAll();
}

/// <summary>
/// 玩家信息 View（自动绑定）
/// </summary>
public class PlayerInfoView : UIBinding<PlayerInfoViewModel>
{
    [Header("UI 组件")]
    [SerializeField] private Text nicknameText;
    [SerializeField] private Text levelText;
    [SerializeField] private Slider hpBar;
    [SerializeField] private Text hpText;
    [SerializeField] private Text goldText;
    [SerializeField] private Slider expBar;

    protected override void OnPropertyChanged(object sender, 
        System.ComponentModel.PropertyChangedEventArgs e)
    {
        // 在主线程更新 UI
        switch (e.PropertyName)
        {
            case nameof(PlayerInfoViewModel.Nickname):
                UpdateNickname();
                break;
            case nameof(PlayerInfoViewModel.LevelDisplay):
                UpdateLevel();
                break;
            case nameof(PlayerInfoViewModel.HpRatio):
                UpdateHpBar();
                break;
            case nameof(PlayerInfoViewModel.HpDisplay):
                UpdateHpText();
                break;
            case nameof(PlayerInfoViewModel.Gold):
                UpdateGold();
                break;
            case nameof(PlayerInfoViewModel.ExpProgress):
                UpdateExpBar();
                break;
        }
    }

    protected override void RefreshAll()
    {
        UpdateNickname();
        UpdateLevel();
        UpdateHpBar();
        UpdateHpText();
        UpdateGold();
        UpdateExpBar();
    }

    void UpdateNickname() => nicknameText.text = ViewModel.Nickname;
    void UpdateLevel() => levelText.text = ViewModel.LevelDisplay;
    
    void UpdateHpBar()
    {
        // 使用 DOTween 平滑过渡（更好的体验）
        DG.Tweening.DOTween.To(
            () => hpBar.value,
            v => hpBar.value = v,
            ViewModel.HpRatio, 0.3f);
    }
    
    void UpdateHpText() => hpText.text = ViewModel.HpDisplay;
    
    void UpdateGold() 
    {
        // 数字滚动动画
        long target = ViewModel.Gold;
        DG.Tweening.DOVirtual.Float(
            (float)long.Parse(goldText.text.Replace(",", "")),
            target, 0.5f,
            v => goldText.text = ((long)v).ToString("N0"));
    }
    
    void UpdateExpBar() 
    {
        expBar.DOValue(ViewModel.ExpProgress / 100f, 0.4f);
    }
    
    // DOTween extension
    static class SliderExtension
    {
        public static DG.Tweening.Tweener DOValue(this Slider slider, float target, float duration)
            => DG.Tweening.DOTween.To(() => slider.value, v => slider.value = v, target, duration);
    }
}
```

---

## 五、命令绑定（Button → ViewModel）

```csharp
/// <summary>
/// MVVM 命令（将 Button 点击绑定到 ViewModel 方法）
/// </summary>
public class RelayCommand
{
    private readonly Action _execute;
    private readonly Func<bool> _canExecute;
    
    public event Action CanExecuteChanged;

    public RelayCommand(Action execute, Func<bool> canExecute = null)
    {
        _execute = execute;
        _canExecute = canExecute;
    }

    public bool CanExecute() => _canExecute?.Invoke() ?? true;
    public void Execute() => _execute?.Invoke();

    public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke();
}

/// <summary>
/// Button 命令绑定组件
/// </summary>
[RequireComponent(typeof(Button))]
public class ButtonCommandBinding : MonoBehaviour
{
    private Button button;
    private RelayCommand command;

    void Awake() => button = GetComponent<Button>();

    public void Bind(RelayCommand cmd)
    {
        command = cmd;
        
        button.onClick.RemoveAllListeners();
        button.onClick.AddListener(() =>
        {
            if (command.CanExecute())
                command.Execute();
        });
        
        command.CanExecuteChanged += UpdateInteractable;
        UpdateInteractable();
    }

    void OnDestroy()
    {
        if (command != null)
            command.CanExecuteChanged -= UpdateInteractable;
    }

    void UpdateInteractable()
    {
        button.interactable = command.CanExecute();
    }
}

/// <summary>
/// 商店 ViewModel（含命令绑定示例）
/// </summary>
public class ShopViewModel : ViewModelBase
{
    private int _playerGold;
    private int _selectedItemPrice;
    
    public int PlayerGold
    {
        get => _playerGold;
        set
        {
            if (SetProperty(ref _playerGold, value, nameof(PlayerGold)))
                BuyCommand.RaiseCanExecuteChanged(); // 余额变化时刷新按钮状态
        }
    }

    public RelayCommand BuyCommand { get; }
    public RelayCommand SellCommand { get; }

    public ShopViewModel()
    {
        BuyCommand = new RelayCommand(
            execute: () => ExecuteBuy(),
            canExecute: () => _playerGold >= _selectedItemPrice);
        
        SellCommand = new RelayCommand(
            execute: () => ExecuteSell());
    }

    void ExecuteBuy()
    {
        // 购买逻辑
        PlayerGold -= _selectedItemPrice;
    }

    void ExecuteSell()
    {
        // 出售逻辑
    }
}
```

---

## 六、MVVM 与传统 Unity UI 的选择

| 场景 | 建议方案 |
|------|----------|
| 简单面板（2-3个字段）| 传统直接引用（省事）|
| 复杂面板（10+字段）| MVVM（维护性好）|
| 列表/表格 | MVVM + ObservableList |
| 表单/多步骤 | MVVM + Command |
| 游戏内HUD（高频更新）| 直接引用（性能更好）|

**核心价值：MVVM 让 UI 逻辑可测试，减少 View 与业务代码的耦合。但切勿过度设计——小面板直接写即可。**
