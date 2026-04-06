---
title: 递归修复 Prefab 中丢失脚本的编辑器工具实现解析
published: 2026-03-31
description: 深入解析自动查找并移除 Prefab 中丢失脚本的编辑器工具，理解 Prefab 嵌套结构遍历和 Undo 操作的工程实践。
tags: [Unity, 编辑器工具, Prefab, 资源维护]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

## Missing Script 是什么？为什么让人头疼？

在 Unity 项目中，当你删除或重命名一个 MonoBehaviour 脚本时，所有挂载了该脚本的 Prefab 或 GameObject 上会出现一个 "Missing (Mono Script)" 组件。

这带来的问题：
1. **黄色警告**：每次打开该 Prefab 都会看到警告信息
2. **运行时错误**：Missing Script 会在 Awake/Start 时触发 NullReferenceException
3. **难以定位**：项目大了后 Prefab 嵌套复杂，手动找出所有 Missing Script 是噩梦

`FindMissingScriptsRecursivelyAndRemove` 就是解决这个问题的自动化工具。

---

## 完整实现解析

```csharp
[MenuItem("Tools/Remove Missing Scripts Recursively Visit Prefabs")]
private static void FindAndRemoveMissingInSelected()
{
    // 1. 收集选中 GameObject 的所有后代（包括 inactive 对象）
    var deeperSelection = Selection.gameObjects
        .SelectMany(go => go.GetComponentsInChildren<Transform>(true))
        .Select(t => t.gameObject);
    
    var prefabs = new HashSet<Object>();  // 已处理的 Prefab 集合（去重）
    int compCount = 0;   // 移除的组件数量
    int goCount = 0;     // 处理的 GameObject 数量
    
    foreach (var go in deeperSelection)
    {
        int count = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go);
        if (count > 0)
        {
            if (PrefabUtility.IsPartOfAnyPrefab(go))
            {
                // 如果是 Prefab 的一部分，先处理 Prefab 源
                RecursivePrefabSource(go, prefabs, ref compCount, ref goCount);
                count = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go);
                
                // 重新检查：如果源 Prefab 已处理，实例上可能就没有 Missing 了
                if (count == 0) continue;
                
                // 还有 Missing → 是 Prefab Override（实例覆盖），在实例上处理
            }

            // 注册 Undo（支持 Ctrl+Z 撤销）
            Undo.RegisterCompleteObjectUndo(go, "Remove missing scripts");
            GameObjectUtility.RemoveMonoBehavioursWithMissingScript(go);
            compCount += count;
            goCount++;
        }
    }

    Debug.Log($"Found and removed {compCount} missing scripts from {goCount} GameObjects");
}
```

### 递归处理 Prefab 源

```csharp
private static void RecursivePrefabSource(
    GameObject instance, 
    HashSet<Object> prefabs, 
    ref int compCount, 
    ref int goCount)
{
    // 获取实例对应的 Prefab 源
    var source = PrefabUtility.GetCorrespondingObjectFromSource(instance);
    
    // 防止重复处理同一个 Prefab（HashSet.Add 返回 false 说明已存在）
    if (source == null || !prefabs.Add(source))
        return;

    // 先递归处理更深层的 Prefab（嵌套 Prefab 场景）
    RecursivePrefabSource(source, prefabs, ref compCount, ref goCount);

    // 再处理当前 Prefab 源上的 Missing Scripts
    int count = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(source);
    if (count > 0)
    {
        Undo.RegisterCompleteObjectUndo(source, "Remove missing scripts");
        GameObjectUtility.RemoveMonoBehavioursWithMissingScript(source);
        compCount += count;
        goCount++;
    }
}
```

---

## 处理嵌套 Prefab 的关键设计

现代 Unity（2018.3+）支持嵌套 Prefab（Nested Prefab）：

```
PrefabA
  └─ PrefabB (Nested)
       └─ PrefabC (Nested)
```

如果 PrefabB 中有 Missing Script，在 PrefabA 的实例上看起来也会显示 Missing，但实际上需要修改的是 PrefabB 本身。

`RecursivePrefabSource` 通过递归深入到最原始的 Prefab Source 来处理：

```
处理 PrefabA 的实例
  → 找到 PrefabA（Source）
  → 递归找 PrefabB（PrefabA 中嵌套的 Prefab）
  → 递归找 PrefabC（PrefabB 中嵌套的 Prefab）
  → 从 PrefabC 开始处理，然后向上
```

注释中也说明了这一点：`"Prefabs can both be nested or variants, so best way to clean all is to go through them all rather than jumping straight to the original prefab source."`

---

## `HashSet<Object> prefabs` 的去重作用

假设场景中有两个 PrefabA 的实例，都嵌套了同一个 PrefabB：

```
实例1（PrefabA）→ PrefabB
实例2（PrefabA）→ PrefabB（同一个）
```

如果不做去重，PrefabB 会被处理两次，第二次处理时 Missing Scripts 已经没有了，但会触发无效的 Undo 记录。

`HashSet.Add` 的特性：已存在的元素返回 `false`，用 `if (!prefabs.Add(source)) return;` 实现了优雅的去重。

---

## Undo 系统：让操作可撤销

```csharp
Undo.RegisterCompleteObjectUndo(go, "Remove missing scripts");
GameObjectUtility.RemoveMonoBehavioursWithMissingScript(go);
```

**为什么先注册 Undo 再操作？**

`Undo.RegisterCompleteObjectUndo` 会记录对象操作前的完整状态（"快照"）。之后如果用户按 Ctrl+Z，Unity 会恢复到这个快照状态。

**注意顺序**：必须先注册 Undo，再执行操作。反过来就无法撤销了。

---

## `GetComponentsInChildren<Transform>(true)` 的妙用

```csharp
var deeperSelection = Selection.gameObjects
    .SelectMany(go => go.GetComponentsInChildren<Transform>(true))
    .Select(t => t.gameObject);
```

`GetComponentsInChildren<Transform>(true)` 中 `true` 参数表示"包含 inactive（未激活）的子对象"。

为什么用 `Transform` 而不是直接用 `GameObject`？因为 `GetComponentsInChildren<Transform>` 会获取每个 GameObject 上的 Transform 组件，而每个 GameObject 有且仅有一个 Transform，所以这等价于获取所有后代 GameObject。

---

## 使用建议

```
何时使用这个工具？

1. 删除/重命名脚本后
2. 合并其他分支后（可能包含已删除的脚本）
3. 项目清理时
4. CI/CD 构建前检查

使用步骤：
1. 在 Project 窗口选中需要检查的 Prefab（可多选）
2. 菜单 Tools → Remove Missing Scripts Recursively Visit Prefabs
3. 查看 Console 输出：找到并移除了多少个 Missing Scripts
4. 如果结果不符合预期，Ctrl+Z 撤销
```

---

## 扩展：查找而不删除

有时只想查看哪些 Prefab 有 Missing Scripts，不立即删除：

```csharp
[MenuItem("Tools/Find Missing Scripts (Report Only)")]
private static void FindMissingScriptsReport()
{
    var allPrefabs = AssetDatabase.FindAssets("t:Prefab")
        .Select(guid => AssetDatabase.GUIDToAssetPath(guid))
        .Select(path => AssetDatabase.LoadAssetAtPath<GameObject>(path));
    
    int totalMissing = 0;
    foreach (var prefab in allPrefabs)
    {
        var transforms = prefab.GetComponentsInChildren<Transform>(true);
        foreach (var t in transforms)
        {
            int count = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(t.gameObject);
            if (count > 0)
            {
                Debug.LogWarning($"Missing {count} scripts in: {t.gameObject.name}", prefab);
                totalMissing += count;
            }
        }
    }
    
    Debug.Log($"Total missing scripts found: {totalMissing}");
}
```

---

## 总结

这个工具虽然代码不多，但展示了几个重要的编辑器工具开发技巧：

| 技巧 | 应用 |
|------|------|
| 递归 Prefab 处理 | GetCorrespondingObjectFromSource |
| 嵌套 Prefab 深度遍历 | 递归函数 |
| 去重防重复处理 | HashSet<Object> |
| 支持撤销 | Undo.RegisterCompleteObjectUndo |
| 包含 inactive 对象 | GetComponentsInChildren(true) |

掌握这些技巧，你就能写出健壮的编辑器工具，大幅提升团队的工作效率。
