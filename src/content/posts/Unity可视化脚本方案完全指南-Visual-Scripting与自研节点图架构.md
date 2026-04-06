---
title: Unity 可视化脚本方案完全指南：Visual Scripting 与自研节点图架构
published: 2026-04-06
description: "深入剖析 Unity 可视化脚本的多种方案：从官方 Visual Scripting（Bolt）到自研节点图框架，涵盖节点系统设计、类型安全连线、图序列化、运行时执行引擎与编辑器 UI Toolkit 实现，帮你为项目选择最适合的可视化脚本架构。"
tags: ['Unity', '可视化脚本', 'Visual Scripting', '节点图', '游戏开发', '工具链']
category: 工具链与编辑器
draft: false
encryptedKey: henhaoji123
---

# Unity 可视化脚本方案完全指南：Visual Scripting 与自研节点图架构

> 可视化脚本（Visual Scripting）让策划、技术美术甚至非程序员也能直接编辑游戏逻辑。本文系统梳理 Unity 生态中的主流可视化脚本方案，并深入讲解如何自研一套生产级节点图框架。

---

## 1. 为什么需要可视化脚本？

在大型游戏项目中，纯代码驱动的游戏逻辑面临以下痛点：

| 痛点 | 具体表现 |
|------|---------|
| **迭代周期长** | 策划改一个技能参数需要等程序修改、编译、发包 |
| **协作壁垒高** | 非程序员无法参与逻辑开发，策划只能写文档等待 |
| **热更新受限** | C# 代码改动需要重新打包，Lua/JSON 配置热更灵活性差 |
| **调试困难** | 文本代码难以直观展示运行时状态和数据流向 |

可视化脚本通过**节点图（Node Graph）**将逻辑转化为可视化的数据流/控制流，解决了以上问题。

### 1.1 适用场景

| 场景 | 推荐方案 |
|------|---------|
| 技能逻辑 / 特效触发时序 | 流程图（FlowGraph）+ Timeline |
| AI 决策 | 行为树（BehaviorTree）|
| 角色状态管理 | 有限状态机（FSM）|
| 材质 / 着色逻辑 | Shader Graph |
| 过场动画编排 | Unity Timeline |
| 通用游戏逻辑 | Unity Visual Scripting（Bolt）|

---

## 2. Unity 官方方案：Visual Scripting（原 Bolt）

Unity 2021.1 起内置 Visual Scripting，前身是第三方插件 Bolt。

### 2.1 核心概念

```
Visual Scripting
├── Script Graph（脚本图）     ← 流程控制 + 变量操作
│   ├── Flow Graph            ← 面向过程的事件流
│   └── State Graph           ← 有限状态机
├── Script Machine            ← 挂载到 GameObject 的运行组件
├── Variables（变量层级）
│   ├── Graph Variables       ← 图内部变量
│   ├── Object Variables      ← 挂载对象变量
│   ├── Scene Variables       ← 场景级变量
│   ├── App Variables         ← 应用级（跨场景）变量
│   └── Saved Variables       ← 持久化变量（PlayerPrefs）
└── Units（节点类型）
    ├── Events                ← 事件入口（Start/Update/碰撞等）
    ├── Control Flow          ← 流程控制（If/While/For等）
    ├── Variables             ← 变量读写
    ├── Math / Logic          ← 数学与逻辑运算
    ├── GameObject / Component ← Unity API 调用
    └── Custom C# Units       ← 自定义节点
```

### 2.2 自定义节点（Custom Unit）

通过继承 `Unit` 类可以创建自定义节点，接入 Visual Scripting 图：

```csharp
using Unity.VisualScripting;
using UnityEngine;

/// <summary>
/// 自定义节点：对目标施加爆炸力
/// 在 Visual Scripting 编辑器中显示为 "Apply Explosion Force"
/// </summary>
[UnitTitle("Apply Explosion Force")]
[UnitCategory("Physics/Custom")]
[UnitShortTitle("ExplosionForce")]
public class ApplyExplosionForceUnit : Unit
{
    // ── 输入端口 ──────────────────────────────────────────────
    [DoNotSerialize]
    [PortLabelHidden]
    public ControlInput inputTrigger { get; private set; }

    [DoNotSerialize]
    public ValueInput rigidbody { get; private set; }

    [DoNotSerialize]
    public ValueInput force { get; private set; }

    [DoNotSerialize]
    public ValueInput radius { get; private set; }

    [DoNotSerialize]
    public ValueInput position { get; private set; }

    // ── 输出端口 ──────────────────────────────────────────────
    [DoNotSerialize]
    [PortLabelHidden]
    public ControlOutput outputTrigger { get; private set; }

    [DoNotSerialize]
    public ValueOutput resultForce { get; private set; }

    private float _appliedForce;

    // ── 初始化端口 ─────────────────────────────────────────────
    protected override void Definition()
    {
        // 控制流入口
        inputTrigger = ControlInput(nameof(inputTrigger), Execute);

        // 值输入（支持默认值）
        rigidbody = ValueInput<Rigidbody>(nameof(rigidbody));
        force     = ValueInput<float>(nameof(force), 500f);
        radius    = ValueInput<float>(nameof(radius), 5f);
        position  = ValueInput<Vector3>(nameof(position), Vector3.zero);

        // 控制流出口
        outputTrigger = ControlOutput(nameof(outputTrigger));

        // 值输出
        resultForce = ValueOutput<float>(nameof(resultForce), _ => _appliedForce);

        // 声明依赖关系（outputTrigger 在 inputTrigger 后执行）
        Succession(inputTrigger, outputTrigger);
        // 声明 resultForce 依赖 rigidbody、force
        Assignment(inputTrigger, resultForce);
    }

    // ── 执行逻辑 ───────────────────────────────────────────────
    private ControlOutput Execute(Flow flow)
    {
        var rb  = flow.GetValue<Rigidbody>(rigidbody);
        var f   = flow.GetValue<float>(force);
        var r   = flow.GetValue<float>(radius);
        var pos = flow.GetValue<Vector3>(position);

        if (rb != null)
        {
            rb.AddExplosionForce(f, pos, r);
            _appliedForce = f;
        }

        return outputTrigger; // 返回下一个要执行的控制流
    }
}
```

### 2.3 Visual Scripting 的局限性

| 限制项 | 说明 |
|--------|------|
| **性能开销** | 反射调用 + 装箱，不适合高频执行（如每帧大量节点）|
| **包体增大** | 需要预生成类型存根（Type Stubs）|
| **定制化差** | 编辑器 UI 不可深度定制 |
| **不支持确定性** | 使用浮点数，不适合帧同步战斗 |
| **协作冲突多** | 图的序列化为 Unity Asset，多人协作 Git 冲突严重 |

---

## 3. 主流第三方方案对比

| 方案 | 特点 | 适用场景 |
|------|------|---------|
| **Bolt / Visual Scripting** | Unity 官方内置，生态好 | 原型 / 小团队通用逻辑 |
| **NodeCanvas** | 行为树 + FSM + 对话树，成熟稳定 | AI / 对话系统 |
| **PlayMaker** | 老牌 FSM，非程序员友好 | 状态机驱动的交互逻辑 |
| **xNode** | 轻量开源节点图框架 | 二次开发基础 |
| **FlowCanvas** | 流程图，性能好 | 游戏逻辑 / 技能系统 |
| **Shader Graph** | Unity 官方着色器节点图 | 材质可视化编辑 |
| **自研节点图** | 完全可控，可深度定制 | 大型商业项目 |

---

## 4. 自研节点图框架设计

对于大型商业项目，自研节点图框架往往是必要选择。以下是完整的架构设计。

### 4.1 整体架构

```
自研节点图框架
├── 核心层（Runtime Core）
│   ├── GraphDefinition       ← 图的数据定义（节点 + 连线）
│   ├── NodeBase              ← 节点基类
│   ├── PortSystem            ← 端口系统（ValuePort / FlowPort）
│   ├── ConnectionManager     ← 连线管理
│   ├── GraphExecutor         ← 运行时执行引擎
│   └── BlackboardSystem      ← 黑板变量系统
│
├── 序列化层（Serialization）
│   ├── JsonSerializer        ← JSON 序列化（配置存储 / 热更新）
│   ├── BinarySerializer      ← 二进制序列化（快照 / 网络同步）
│   └── MigrationSystem       ← 版本迁移（节点字段重命名容错）
│
├── 编辑器层（Editor）
│   ├── GraphEditorWindow     ← 主编辑器窗口（UI Toolkit）
│   ├── GraphView             ← 节点画布（继承 UnityEditor.Experimental.GraphView）
│   ├── NodeView              ← 节点视图
│   ├── PortView              ← 端口视图
│   ├── EdgeView              ← 连线视图
│   ├── MiniMap               ← 小地图导航
│   └── NodeSearchWindow      ← 节点搜索弹窗
│
└── 扩展层（Extensions）
    ├── FlowGraph             ← 流程图扩展
    ├── StateMachineGraph     ← 状态机扩展
    ├── BehaviorTreeGraph     ← 行为树扩展
    └── TimelineGraph         ← 时间轴扩展
```

### 4.2 节点基类设计

```csharp
/// <summary>
/// 节点基类：所有自定义节点均继承此类
/// </summary>
[Serializable]
public abstract class NodeBase
{
    // ── 节点元数据（序列化存储）──────────────────────────────
    [SerializeField] public string guid = Guid.NewGuid().ToString();
    [SerializeField] public Rect position;          // 编辑器中的位置
    [SerializeField] public string title;           // 节点标题
    [SerializeField] public bool isExpanded = true; // 是否展开

    // ── 端口集合 ──────────────────────────────────────────────
    [NonSerialized] public List<ValuePort> inputPorts  = new();
    [NonSerialized] public List<ValuePort> outputPorts = new();
    [NonSerialized] public FlowPort       flowIn;
    [NonSerialized] public FlowPort       flowOut;

    // ── 所属图的引用 ───────────────────────────────────────────
    [NonSerialized] public GraphDefinition ownerGraph;

    // ── 生命周期 ───────────────────────────────────────────────
    
    /// <summary>初始化端口（子类必须重写）</summary>
    public abstract void Initialize();

    /// <summary>节点执行（流程节点重写此方法）</summary>
    public virtual FlowPort Execute(GraphExecutor executor)
    {
        OnExecute(executor);
        return flowOut; // 默认连接到下一个节点
    }

    protected virtual void OnExecute(GraphExecutor executor) { }

    /// <summary>图启动时调用</summary>
    public virtual void OnGraphStart()  { }

    /// <summary>图停止时调用</summary>
    public virtual void OnGraphStop()   { }

    /// <summary>图每帧更新（需要实现 IUpdatable 才会被调用）</summary>
    public virtual void OnUpdate(float deltaTime) { }

    // ── 端口工厂方法 ───────────────────────────────────────────
    
    protected ValuePort<T> AddInputPort<T>(string name, T defaultValue = default)
    {
        var port = new ValuePort<T>(name, PortDirection.Input, defaultValue);
        port.ownerNode = this;
        inputPorts.Add(port);
        return port;
    }

    protected ValuePort<T> AddOutputPort<T>(string name, Func<T> getter = null)
    {
        var port = new ValuePort<T>(name, PortDirection.Output);
        port.ownerNode = this;
        if (getter != null) port.SetGetter(getter);
        outputPorts.Add(port);
        return port;
    }

    protected void AddFlowPorts(bool hasInput = true, bool hasOutput = true)
    {
        if (hasInput)  flowIn  = new FlowPort("In",  PortDirection.Input,  this);
        if (hasOutput) flowOut = new FlowPort("Out", PortDirection.Output, this);
    }
}
```

### 4.3 类型安全端口系统

```csharp
public enum PortDirection { Input, Output }

/// <summary>
/// 类型化值端口：实现类型安全的节点间数据传递
/// </summary>
[Serializable]
public class ValuePort<T> : ValuePort
{
    private T _cachedValue;
    private Func<T> _getter;           // 输出端口的值获取函数
    private bool _isDirty = true;      // 脏标记，避免重复计算

    public ValuePort(string name, PortDirection direction, T defaultValue = default)
        : base(name, direction, typeof(T))
    {
        _cachedValue = defaultValue;
    }

    public void SetGetter(Func<T> getter)
    {
        _getter = getter;
    }

    /// <summary>获取端口当前值（自动从连接的输出端口拉取）</summary>
    public T GetValue()
    {
        if (direction == PortDirection.Input && connectedPort != null)
        {
            // 从连接的输出端口获取值（类型自动转换）
            if (connectedPort is ValuePort<T> typedPort)
                return typedPort.GetValue();
            
            // 支持隐式类型转换（如 int → float）
            return TypeConverter.Convert<T>(connectedPort.GetRawValue());
        }

        // 输出端口：通过 getter 计算
        if (_getter != null && _isDirty)
        {
            _cachedValue = _getter();
            _isDirty = false;
        }

        return _cachedValue;
    }

    public override object GetRawValue() => GetValue();

    public void SetValue(T value)
    {
        _cachedValue = value;
        _isDirty = false;
        // 通知下游端口失效
        NotifyDownstreamDirty();
    }
}

/// <summary>
/// 端口基类（非泛型，用于编辑器和连线管理）
/// </summary>
[Serializable]
public abstract class ValuePort
{
    public string        name;
    public PortDirection direction;
    public Type          portType;
    public NodeBase      ownerNode;
    public ValuePort     connectedPort;    // 当前连接（简化：每个端口只有一条连线）

    protected ValuePort(string name, PortDirection direction, Type type)
    {
        this.name      = name;
        this.direction = direction;
        this.portType  = type;
    }

    public abstract object GetRawValue();

    /// <summary>判断两个端口类型是否可连接（包含继承/接口关系）</summary>
    public static bool CanConnect(ValuePort from, ValuePort to)
    {
        if (from.direction != PortDirection.Output) return false;
        if (to.direction   != PortDirection.Input)  return false;

        var fromType = from.portType;
        var toType   = to.portType;

        // 精确匹配 或 继承关系
        if (toType.IsAssignableFrom(fromType)) return true;

        // 注册的隐式转换（如 int → float）
        if (TypeConverter.HasConverter(fromType, toType)) return true;

        return false;
    }

    protected void NotifyDownstreamDirty()
    {
        // 通知所有连接到此输出端口的输入端口缓存失效
        // 实现省略（遍历 ownerGraph.connections 过滤即可）
    }
}
```

### 4.4 图执行引擎

```csharp
/// <summary>
/// 图执行引擎：负责按流程驱动节点执行
/// 支持同步执行 / 异步协程 / 条件分支
/// </summary>
public class GraphExecutor
{
    private GraphDefinition _graph;
    private Blackboard       _blackboard;
    private bool             _isRunning;

    // 异步节点等待队列
    private readonly Queue<(AsyncNodeBase node, IEnumerator coroutine)> _asyncQueue = new();

    public GraphExecutor(GraphDefinition graph)
    {
        _graph      = graph;
        _blackboard = new Blackboard();
    }

    /// <summary>
    /// 从入口节点开始执行图（同步深度优先）
    /// </summary>
    public void Execute(NodeBase entryNode)
    {
        _isRunning = true;
        ExecuteNode(entryNode);
    }

    private void ExecuteNode(NodeBase node)
    {
        if (node == null || !_isRunning) return;

        // 执行节点逻辑，获取下一个节点的流出端口
        FlowPort nextPort = node.Execute(this);

        if (nextPort == null) return;

        // 找到连接的下一个节点
        var nextNode = _graph.GetConnectedNode(nextPort);
        ExecuteNode(nextNode);
    }

    /// <summary>
    /// 处理异步节点（每帧推进）
    /// </summary>
    public bool UpdateAsync()
    {
        if (_asyncQueue.Count == 0) return false;

        var (node, coroutine) = _asyncQueue.Peek();
        bool moveNext = coroutine.MoveNext();

        if (!moveNext)
        {
            _asyncQueue.Dequeue();
            // 异步节点完成，继续执行后续流程
            var nextNode = _graph.GetConnectedNode(node.flowOut);
            if (nextNode != null) ExecuteNode(nextNode);
        }

        return _asyncQueue.Count > 0;
    }

    /// <summary>注册异步节点（由 AsyncNodeBase 调用）</summary>
    public void EnqueueAsync(AsyncNodeBase node, IEnumerator coroutine)
    {
        _asyncQueue.Enqueue((node, coroutine));
    }

    /// <summary>从黑板读取变量</summary>
    public T GetBlackboardValue<T>(string key) => _blackboard.Get<T>(key);

    /// <summary>向黑板写入变量</summary>
    public void SetBlackboardValue<T>(string key, T value) => _blackboard.Set(key, value);

    public void Stop()
    {
        _isRunning = false;
        _asyncQueue.Clear();
    }
}
```

### 4.5 图的 JSON 序列化设计

序列化设计是节点图系统最复杂的部分，需要支持版本迁移和节点类型查找：

```csharp
[Serializable]
public class GraphDefinition
{
    public string              graphId;
    public string              graphType;     // "FlowGraph" / "StateMachine" / "BehaviorTree"
    public List<NodeData>      nodes      = new();
    public List<ConnectionData> connections = new();
    public string              entryNodeGuid;

    // ── 运行时缓存（不序列化）───────────────────────────────────
    [NonSerialized] private Dictionary<string, NodeBase> _nodeCache = new();

    public NodeBase GetNode(string guid)
    {
        if (_nodeCache.TryGetValue(guid, out var node)) return node;
        return null;
    }

    public NodeBase GetConnectedNode(FlowPort port)
    {
        var connection = connections.Find(c => c.fromGuid == port.ownerNode.guid
                                            && c.fromPortName == port.name);
        if (connection == null) return null;
        return GetNode(connection.toGuid);
    }

    /// <summary>从 JSON 反序列化，支持多态节点类型</summary>
    public static GraphDefinition FromJson(string json)
    {
        var wrapper = JsonUtility.FromJson<GraphJsonWrapper>(json);
        var graph   = new GraphDefinition();

        graph.graphId      = wrapper.graphId;
        graph.graphType    = wrapper.graphType;
        graph.entryNodeGuid = wrapper.entryNodeGuid;
        graph.connections  = wrapper.connections;

        // 多态节点反序列化：通过 typeName 查找对应 C# 类型
        foreach (var nodeData in wrapper.nodes)
        {
            var type = NodeTypeRegistry.GetType(nodeData.typeName);
            if (type == null)
            {
                Debug.LogWarning($"[Graph] 未找到节点类型: {nodeData.typeName}，跳过");
                continue;
            }

            var node = (NodeBase)JsonUtility.FromJson(nodeData.dataJson, type);
            node.Initialize();
            graph.nodes.Add(nodeData);
            graph._nodeCache[node.guid] = node;
        }

        return graph;
    }
}

[Serializable]
public class NodeData
{
    public string typeName;   // C# 类型名（用于反序列化多态）
    public string dataJson;   // 节点字段的 JSON 数据
}

[Serializable]
public class ConnectionData
{
    public string fromGuid;
    public string fromPortName;
    public string toGuid;
    public string toPortName;
}

/// <summary>节点类型注册表（支持别名，用于版本迁移）</summary>
public static class NodeTypeRegistry
{
    private static readonly Dictionary<string, Type> _registry = new();

    static NodeTypeRegistry()
    {
        // 自动扫描所有继承 NodeBase 的类型
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            foreach (var type in asm.GetTypes())
            {
                if (!type.IsAbstract && typeof(NodeBase).IsAssignableFrom(type))
                {
                    _registry[type.Name] = type;

                    // 支持 [NodeAlias] 属性定义旧名称（版本迁移）
                    var alias = type.GetCustomAttribute<NodeAliasAttribute>();
                    if (alias != null)
                        _registry[alias.OldName] = type;
                }
            }
        }
    }

    public static Type GetType(string typeName)
    {
        _registry.TryGetValue(typeName, out var type);
        return type;
    }
}
```

---

## 5. 编辑器实现：UI Toolkit GraphView

Unity 提供了 `GraphView` API（基于 UI Toolkit），是构建节点编辑器的官方推荐方式。

### 5.1 主编辑器窗口

```csharp
using UnityEditor;
using UnityEditor.Experimental.GraphView;
using UnityEngine.UIElements;

public class NodeGraphEditorWindow : EditorWindow
{
    private NodeGraphView _graphView;
    private GraphDefinition _currentGraph;

    [MenuItem("Tools/Node Graph Editor")]
    public static void OpenWindow()
    {
        var window = GetWindow<NodeGraphEditorWindow>("节点图编辑器");
        window.minSize = new Vector2(800, 600);
    }

    private void CreateGUI()
    {
        // 创建工具栏
        var toolbar = new UnityEditor.UIElements.Toolbar();
        toolbar.Add(new Button(OnSaveClicked)   { text = "保存" });
        toolbar.Add(new Button(OnLoadClicked)   { text = "加载" });
        toolbar.Add(new Button(OnClearClicked)  { text = "清空" });
        toolbar.Add(new ToolbarSpacer());
        toolbar.Add(new Label("当前图：") { style = { alignSelf = Align.Center } });
        rootVisualElement.Add(toolbar);

        // 创建节点图视图
        _graphView = new NodeGraphView(this);
        _graphView.StretchToParentSize();
        rootVisualElement.Add(_graphView);
    }

    public void LoadGraph(GraphDefinition graph)
    {
        _currentGraph = graph;
        _graphView.PopulateView(graph);
    }

    private void OnSaveClicked()
    {
        if (_currentGraph == null) return;
        var json = _graphView.SerializeToJson();
        // 保存到文件
        var path = EditorUtility.SaveFilePanel("保存节点图", "Assets", "NewGraph", "json");
        if (!string.IsNullOrEmpty(path))
            System.IO.File.WriteAllText(path, json);
    }

    private void OnLoadClicked()
    {
        var path = EditorUtility.OpenFilePanel("加载节点图", "Assets", "json");
        if (string.IsNullOrEmpty(path)) return;
        var json  = System.IO.File.ReadAllText(path);
        var graph = GraphDefinition.FromJson(json);
        LoadGraph(graph);
    }

    private void OnClearClicked() => _graphView.ClearGraph();
}
```

### 5.2 节点图视图

```csharp
public class NodeGraphView : GraphView
{
    private NodeGraphEditorWindow _window;
    private MiniMap                _miniMap;

    public NodeGraphView(NodeGraphEditorWindow window)
    {
        _window = window;

        // 样式
        style.flexGrow = 1;
        var styleSheet = Resources.Load<StyleSheet>("NodeGraphStyle");
        if (styleSheet != null) styleSheets.Add(styleSheet);

        // 基础操作：缩放 / 拖拽 / 框选
        SetupZoom(ContentZoomer.DefaultMinScale, ContentZoomer.DefaultMaxScale);
        this.AddManipulator(new ContentDragger());
        this.AddManipulator(new SelectionDragger());
        this.AddManipulator(new RectangleSelector());

        // 网格背景
        var grid = new GridBackground();
        Insert(0, grid);

        // 小地图
        _miniMap = new MiniMap { anchored = true };
        _miniMap.SetPosition(new Rect(10, 30, 200, 140));
        Add(_miniMap);

        // 右键菜单：搜索并添加节点
        nodeCreationRequest = ctx =>
        {
            SearchWindow.Open(new SearchWindowContext(ctx.screenMousePosition),
                              NodeSearchProvider.Create(this));
        };

        // 监听连线变化
        graphViewChanged = OnGraphViewChanged;
    }

    /// <summary>从图定义填充编辑器视图</summary>
    public void PopulateView(GraphDefinition graph)
    {
        ClearGraph();

        // 创建节点视图
        var nodeViews = new Dictionary<string, NodeView>();
        foreach (var nodeData in graph.nodes)
        {
            var type = NodeTypeRegistry.GetType(nodeData.typeName);
            if (type == null) continue;

            var node = (NodeBase)JsonUtility.FromJson(nodeData.dataJson, type);
            node.Initialize();

            var view = CreateNodeView(node);
            nodeViews[node.guid] = view;
        }

        // 创建连线
        foreach (var conn in graph.connections)
        {
            if (!nodeViews.TryGetValue(conn.fromGuid, out var fromView)) continue;
            if (!nodeViews.TryGetValue(conn.toGuid,   out var toView))   continue;

            var fromPort = fromView.GetOutputPort(conn.fromPortName);
            var toPort   = toView.GetInputPort(conn.toPortName);
            if (fromPort == null || toPort == null) continue;

            var edge = fromPort.ConnectTo(toPort);
            AddElement(edge);
        }
    }

    private NodeView CreateNodeView(NodeBase node)
    {
        var view = new NodeView(node);
        view.SetPosition(node.position);
        AddElement(view);
        return view;
    }

    /// <summary>序列化当前图为 JSON</summary>
    public string SerializeToJson()
    {
        var graph = new GraphDefinition();

        foreach (var element in graphElements)
        {
            if (element is NodeView nodeView)
            {
                var node     = nodeView.GetNode();
                node.position = nodeView.GetPosition();
                graph.nodes.Add(new NodeData
                {
                    typeName = node.GetType().Name,
                    dataJson = JsonUtility.ToJson(node)
                });
            }
            else if (element is Edge edge)
            {
                var fromNode = (edge.output.node as NodeView)?.GetNode();
                var toNode   = (edge.input.node as NodeView)?.GetNode();
                if (fromNode == null || toNode == null) continue;

                graph.connections.Add(new ConnectionData
                {
                    fromGuid     = fromNode.guid,
                    fromPortName = edge.output.portName,
                    toGuid       = toNode.guid,
                    toPortName   = edge.input.portName
                });
            }
        }

        return JsonUtility.ToJson(new GraphJsonWrapper(graph), prettyPrint: true);
    }

    /// <summary>验证连线：类型不兼容的端口不允许连接</summary>
    public override List<Port> GetCompatiblePorts(Port startPort, NodeAdapter nodeAdapter)
    {
        return ports.Where(port =>
            port.direction != startPort.direction &&    // 方向相反
            port.node      != startPort.node      &&    // 不是同一节点
            ValuePort.CanConnect(                        // 类型兼容
                startPort.direction == Direction.Output
                    ? (startPort.userData as ValuePort)
                    : (port.userData     as ValuePort),
                startPort.direction == Direction.Input
                    ? (startPort.userData as ValuePort)
                    : (port.userData     as ValuePort))
        ).ToList();
    }

    private GraphViewChange OnGraphViewChanged(GraphViewChange change)
    {
        // 处理删除操作（删除节点时同时删除连线）
        change.elementsToRemove?.ForEach(elem =>
        {
            if (elem is NodeView nodeView)
            {
                // 删除关联连线
                var edges = nodeView.Query<Port>().ToList()
                    .SelectMany(p => p.connections).ToList();
                edges.ForEach(RemoveElement);
            }
        });
        return change;
    }

    public void ClearGraph()
    {
        graphElements.ForEach(RemoveElement);
    }
}
```

### 5.3 节点视图

```csharp
public class NodeView : UnityEditor.Experimental.GraphView.Node
{
    private NodeBase _node;
    private readonly Dictionary<string, Port> _inputPorts  = new();
    private readonly Dictionary<string, Port> _outputPorts = new();

    public NodeView(NodeBase node)
    {
        _node = node;
        title = node.title ?? node.GetType().Name;

        // 设置节点颜色（根据类型）
        var attr = node.GetType().GetCustomAttribute<NodeColorAttribute>();
        if (attr != null)
            titleContainer.style.backgroundColor = attr.Color;

        // 创建端口
        foreach (var port in node.inputPorts)
            AddPort(port, Direction.Input);

        foreach (var port in node.outputPorts)
            AddPort(port, Direction.Output);

        if (node.flowIn  != null) AddFlowPort(node.flowIn,  Direction.Input);
        if (node.flowOut != null) AddFlowPort(node.flowOut, Direction.Output);

        // 创建自定义属性 Inspector（可选）
        var customUI = CreatePropertyFields(node);
        if (customUI != null) extensionContainer.Add(customUI);
        RefreshExpandedState();
    }

    private void AddPort(ValuePort portData, Direction direction)
    {
        var capacity = direction == Direction.Input
            ? Port.Capacity.Single
            : Port.Capacity.Multi;

        var port = InstantiatePort(Orientation.Horizontal, direction, capacity, portData.portType);
        port.portName   = portData.name;
        port.userData   = portData;  // 存储原始端口数据用于类型校验

        if (direction == Direction.Input)
        {
            inputContainer.Add(port);
            _inputPorts[portData.name] = port;
        }
        else
        {
            outputContainer.Add(port);
            _outputPorts[portData.name] = port;
        }
    }

    private void AddFlowPort(FlowPort portData, Direction direction)
    {
        var port = InstantiatePort(Orientation.Horizontal, direction,
                                   Port.Capacity.Single, typeof(FlowPort));
        port.portName = portData.name;
        port.portColor = new Color(0.6f, 0.9f, 0.6f); // 流程端口显示为绿色

        if (direction == Direction.Input) inputContainer.Insert(0, port);
        else                             outputContainer.Add(port);
    }

    private VisualElement CreatePropertyFields(NodeBase node)
    {
        // 使用反射自动生成可编辑字段（标注 [Expose] 的字段）
        var container = new VisualElement();
        bool hasFields = false;

        foreach (var field in node.GetType()
                               .GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        {
            if (field.GetCustomAttribute<ExposeAttribute>() == null) continue;

            var fieldView = NodeFieldFactory.CreateField(field, node);
            if (fieldView != null)
            {
                container.Add(fieldView);
                hasFields = true;
            }
        }

        return hasFields ? container : null;
    }

    public NodeBase GetNode()                    => _node;
    public Port GetInputPort(string name)        => _inputPorts.GetValueOrDefault(name);
    public Port GetOutputPort(string name)       => _outputPorts.GetValueOrDefault(name);
}
```

---

## 6. 实战节点实现：技能释放流程图

以一个完整的技能释放流程图为例，展示如何用自研框架实现：

```csharp
// ── 入口节点 ──────────────────────────────────────────────────
[NodeTitle("Enter")]
[NodeColor(r: 0.2f, g: 0.7f, b: 0.2f)]
public class EntryNode : NodeBase
{
    public override void Initialize()
    {
        title = "Enter";
        AddFlowPorts(hasInput: false, hasOutput: true);
    }

    public override FlowPort Execute(GraphExecutor executor) => flowOut;
}

// ── CD 检查节点 ────────────────────────────────────────────────
[NodeTitle("检查技能 CD")]
[NodeCategory("条件/技能")]
public class CheckSkillCooldownNode : NodeBase
{
    [Expose] public int skillId = 1001;

    private ValuePort<int>    _unitIdPort;
    private FlowPort          _flowSuccess;
    private FlowPort          _flowFailed;

    public override void Initialize()
    {
        title           = "检查技能 CD";
        _unitIdPort     = AddInputPort<int>("施法单位ID", 0);
        flowIn          = new FlowPort("In",      PortDirection.Input,  this);
        _flowSuccess    = new FlowPort("成功",    PortDirection.Output, this);
        _flowFailed     = new FlowPort("CD未完", PortDirection.Output, this);
    }

    public override FlowPort Execute(GraphExecutor executor)
    {
        int unitId = _unitIdPort.GetValue();
        var unit   = UnitManager.GetUnit(unitId);

        if (unit == null) return _flowFailed;

        bool cdReady = unit.SkillComponent.IsCooldownReady(skillId);
        return cdReady ? _flowSuccess : _flowFailed;
    }
}

// ── 播放动画节点 ────────────────────────────────────────────────
[NodeTitle("播放动画")]
[NodeCategory("动画")]
public class PlayAnimationNode : NodeBase
{
    [Expose] public string animationName = "Attack";
    [Expose] public float  crossFadeTime = 0.1f;

    private ValuePort<int> _unitIdPort;

    public override void Initialize()
    {
        title       = "播放动画";
        _unitIdPort = AddInputPort<int>("单位ID", 0);
        AddFlowPorts();
    }

    public override FlowPort Execute(GraphExecutor executor)
    {
        int unitId = _unitIdPort.GetValue();
        var unit   = UnitManager.GetUnit(unitId);
        unit?.AnimationComponent.CrossFade(animationName, crossFadeTime);
        return flowOut;
    }
}

// ── 等待节点（异步）──────────────────────────────────────────
[NodeTitle("等待帧数")]
[NodeCategory("流程控制")]
public class WaitFramesNode : AsyncNodeBase
{
    [Expose] public int frameCount = 10;

    public override void Initialize()
    {
        title = $"等待 {frameCount} 帧";
        AddFlowPorts();
    }

    protected override IEnumerator ExecuteAsync(GraphExecutor executor)
    {
        int remaining = frameCount;
        while (remaining-- > 0)
            yield return null; // 等待一帧
    }
}

// ── 添加 Buff 节点 ─────────────────────────────────────────────
[NodeTitle("添加 Buff")]
[NodeCategory("战斗/Buff")]
public class AddBuffNode : NodeBase
{
    [Expose] public int buffId = 2001;
    [Expose] public int duration = 3;  // 帧数

    private ValuePort<int> _targetIdPort;
    private ValuePort<int> _casterIdPort;

    public override void Initialize()
    {
        title        = "添加 Buff";
        _targetIdPort = AddInputPort<int>("目标单位ID", 0);
        _casterIdPort = AddInputPort<int>("施法单位ID", 0);
        AddFlowPorts();
    }

    public override FlowPort Execute(GraphExecutor executor)
    {
        int targetId = _targetIdPort.GetValue();
        int casterId = _casterIdPort.GetValue();
        var target   = UnitManager.GetUnit(targetId);
        target?.BuffComponent.AddBuff(buffId, casterId, duration);
        return flowOut;
    }
}
```

---

## 7. 黑板变量系统（Blackboard）

黑板是跨节点的临时变量容器，是节点图系统的标配：

```csharp
/// <summary>
/// 黑板：节点图运行时的共享变量容器
/// 支持任意类型的命名变量
/// </summary>
public class Blackboard
{
    private readonly Dictionary<string, object> _store = new();

    public void Set<T>(string key, T value)     => _store[key] = value;
    public T    Get<T>(string key)
    {
        if (_store.TryGetValue(key, out var obj) && obj is T typed)
            return typed;
        return default;
    }

    public bool Has(string key) => _store.ContainsKey(key);

    public void Clear() => _store.Clear();

    // ── 快捷节点：读/写黑板变量 ───────────────────────────────

    public static float GetFloat(Blackboard bb, string key)   => bb.Get<float>(key);
    public static int   GetInt  (Blackboard bb, string key)   => bb.Get<int>(key);
    public static bool  GetBool (Blackboard bb, string key)   => bb.Get<bool>(key);
}

// ── 写黑板节点 ─────────────────────────────────────────────────
[NodeTitle("写入黑板（Float）")]
[NodeCategory("黑板")]
public class SetBlackboardFloatNode : NodeBase
{
    [Expose] public string key = "myVar";

    private ValuePort<float> _valuePort;

    public override void Initialize()
    {
        title       = "写入黑板";
        _valuePort  = AddInputPort<float>("值", 0f);
        AddFlowPorts();
    }

    public override FlowPort Execute(GraphExecutor executor)
    {
        executor.SetBlackboardValue(key, _valuePort.GetValue());
        return flowOut;
    }
}

// ── 读黑板节点 ─────────────────────────────────────────────────
[NodeTitle("读取黑板（Float）")]
[NodeCategory("黑板")]
public class GetBlackboardFloatNode : NodeBase
{
    [Expose] public string key = "myVar";

    private ValuePort<float> _resultPort;

    public override void Initialize()
    {
        title       = "读取黑板";
        _resultPort = AddOutputPort<float>("值");
    }

    public override void Initialize()
    {
        title       = "读取黑板";
        _resultPort = AddOutputPort<float>("值", () =>
        {
            // 注意：getter 需要能访问到 executor，可通过闭包或注入解决
            return _cachedExecutor?.GetBlackboardValue<float>(key) ?? 0f;
        });
    }
}
```

---

## 8. 性能优化策略

### 8.1 图对象池

```csharp
/// <summary>
/// 节点图对象池：避免频繁的 JSON 反序列化
/// 同一个图定义（相同 graphId）只反序列化一次
/// </summary>
public static class GraphPool
{
    private static readonly Dictionary<string, Queue<GraphExecutor>> _pools = new();
    private static readonly Dictionary<string, GraphDefinition>      _defs  = new();

    public static GraphExecutor Rent(string graphId, string jsonIfMissing = null)
    {
        if (!_pools.TryGetValue(graphId, out var pool) || pool.Count == 0)
        {
            // 确保图定义已加载
            if (!_defs.ContainsKey(graphId))
            {
                if (jsonIfMissing == null)
                    throw new InvalidOperationException($"Graph {graphId} not registered");
                _defs[graphId] = GraphDefinition.FromJson(jsonIfMissing);
            }

            // 深拷贝图定义（避免运行时状态污染）
            var graphCopy = _defs[graphId].DeepCopy();
            return new GraphExecutor(graphCopy);
        }

        return pool.Dequeue();
    }

    public static void Return(string graphId, GraphExecutor executor)
    {
        executor.Stop();

        if (!_pools.ContainsKey(graphId))
            _pools[graphId] = new Queue<GraphExecutor>();

        _pools[graphId].Enqueue(executor);
    }
}
```

### 8.2 节点查找加速

```csharp
// 使用预构建的连线索引替代每次线性搜索
public class GraphDefinition
{
    // 预构建：输出端口 GUID+PortName → 目标节点
    private Dictionary<string, NodeBase> _connectionIndex = new();

    public void BuildConnectionIndex()
    {
        _connectionIndex.Clear();
        foreach (var conn in connections)
        {
            string key = $"{conn.fromGuid}:{conn.fromPortName}";
            if (_nodeCache.TryGetValue(conn.toGuid, out var toNode))
                _connectionIndex[key] = toNode;
        }
    }

    public NodeBase GetConnectedNode(FlowPort port)
    {
        string key = $"{port.ownerNode.guid}:{port.name}";
        _connectionIndex.TryGetValue(key, out var node);
        return node;
    }
}
```

---

## 9. 方案选型建议

| 项目规模 | 团队构成 | 推荐方案 |
|---------|---------|---------|
| **独立游戏 / 小型项目** | 程序员主导 | Unity Visual Scripting（Bolt）|
| **中型项目** | 含策划协作 | NodeCanvas / PlayMaker |
| **大型商业项目** | 大团队，有自定义需求 | **自研节点图框架** |
| **纯技能/特效** | 美术主导 | Shader Graph + Unity Timeline |
| **帧同步战斗** | 强确定性要求 | 自研 + 定点数（FP 数值类型）|

### 核心决策维度

1. **性能要求**：高频执行（每帧大量节点）→ 自研，避免反射开销
2. **确定性要求**：帧同步 → 必须自研 + 定点数
3. **热更新需求**：JSON/AssetBundle 热更 → 自研序列化方案
4. **编辑器定制**：需要特殊 UI（时间轴、曲线等）→ 自研 + UI Toolkit
5. **迭代速度**：快速原型 → Bolt / NodeCanvas 开箱即用

---

## 总结

| 维度 | Unity Visual Scripting | 自研节点图 |
|------|----------------------|-----------|
| 上手成本 | ⭐ 低 | ⭐⭐⭐⭐ 高 |
| 性能 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 定制性 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 热更新支持 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 团队协作 | ⭐⭐⭐ | ⭐⭐⭐⭐（自行设计合并策略）|
| 维护成本 | ⭐⭐⭐⭐（官方维护）| ⭐⭐（自行维护）|

自研节点图框架的投入是巨大的，但对于追求极致性能、强定制化和热更新能力的大型商业游戏项目，它往往是唯一合理的选择。建议以 `xNode` 或 `GraphView` 为起点，逐步构建符合项目需求的专属可视化脚本系统。
