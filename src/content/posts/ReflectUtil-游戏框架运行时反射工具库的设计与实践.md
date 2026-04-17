---
title: ReflectUtil：游戏框架运行时反射工具库的设计与实践
published: 2026-04-17
description: 深入解析游戏框架 ReflectUtil 的设计，涵盖类型查找、成员读写、方法调用、泛型约束校验等反射操作的封装，以及如何在游戏中安全、高效地使用反射。
tags: [CSharp, 游戏框架, 反射, Reflection, 工具类, 元编程]
category: Unity游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

# ReflectUtil：游戏框架运行时反射工具库的设计与实践

## 为什么游戏框架需要反射工具类？

C# 反射功能强大，但原生 API 繁琐：

```csharp
// 原生反射读取字段
var field = type.GetField("_health",
    BindingFlags.Public | BindingFlags.NonPublic |
    BindingFlags.Static | BindingFlags.Instance);
var value = field?.GetValue(instance);
```

每次都要写 `BindingFlags`，还要处理 null，还要跨基类继承链查找——重复代码太多。`ReflectUtil` 就是为了消除这些噪音，把"读字段""写属性""调方法"这些高频操作变成一行调用。

---

## 类型查找：跨程序集的健壮获取

```csharp
private static List<Type> types;

public static List<Type> GetTypes()
{
    if (types == null)
    {
        InitTypes();
    }
    return types;
}

public static void InitTypes()
{
    types = AppDomain.CurrentDomain.GetAssemblies()
        .SelectMany(a => a.GetTypes())
        .ToList();
}
```

`GetTypes()` 收集当前 AppDomain 中**所有程序集**的所有类型，是很多反射操作的前置步骤。缓存在静态字段里，只初始化一次。

**注意注释掉的代码**：

```csharp
/*types = new();
var allTypes = EventSystem.Instance.GetTypes();
types.AddRange(allTypes.Values);*/
```

这里原本尝试从 ET 框架的 `EventSystem` 获取类型（ET 框架维护了自己的类型注册表），后来改成直接扫描程序集。两种方案各有取舍：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 扫描程序集 | 无需注册，自动发现所有类型 | 包含框架内部类型，列表较大 |
| EventSystem 注册表 | 只含业务类型，精确 | 必须先注册才能找到 |

### GetType：跨程序集类型名查找

```csharp
public static Type GetType(string typeName)
{
    var type = Type.GetType(typeName);
    if (type != null) return type;

    foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
    {
        type = a.GetType(typeName);
        if (type != null) return type;
    }
    return null;
}
```

`Type.GetType(name)` 只能找到当前程序集和 mscorlib 中的类型，游戏项目通常有多个程序集（HotFix.dll、Game.dll 等），所以需要遍历所有程序集。

这在热更新场景下特别重要：HybridCLR 加载的热更程序集里的类型，`Type.GetType` 是找不到的，必须遍历。

---

## 类型转换：ChangeType 的工程级实现

标准的 `Convert.ChangeType` 在处理 Nullable、Enum、Guid 时会抛异常或转换失败。`ReflectUtil` 的 `ChangeType` 做了大量修补：

```csharp
public static object ChangeType(object value, Type type)
{
    if (value == null) return null;
    if (type == value.GetType()) return value;  // 类型已匹配，直接返回

    // Enum 特殊处理
    if (type.IsEnum)
    {
        if (value is string)
            return Enum.Parse(type, value as string);
        return Enum.ToObject(type, value);
    }

    // Nullable<T> 特殊处理
    if (!type.IsInterface && type.IsGenericType)
    {
        var innerType = type.GetGenericArguments()[0];
        var innerValue = ChangeType(value, innerType);
        return Activator.CreateInstance(type, innerValue);
    }

    // Guid / Version 特殊处理
    if (value is string && type == typeof(Guid))
        return new Guid(value as string);
    if (value is string && type == typeof(Version))
        return new Version(value as string);

    // 兜底：标准 Convert.ChangeType
    if (!(value is IConvertible)) return value;
    return Convert.ChangeType(value, type);
}
```

处理顺序很讲究：
1. 先快速路径（类型已匹配）
2. 再特殊类型（Enum、Nullable、Guid、Version）
3. 最后兜底（标准转换）

这在反序列化、配置表读取、Lua 与 C# 类型转换等场景下非常实用。

---

## 泛型约束校验：AreTypeArgumentsValid

这是 `ReflectUtil` 中最复杂的一个方法，负责在运行时检查一个类型是否满足泛型参数的约束：

```csharp
public static bool AreTypeArgumentsValid(Type genericTypeDefinition, Type typeArgument)
{
    // 1. 检查特殊约束（class / struct / new()）
    var attributes = genericArgument.GenericParameterAttributes;

    if (attributes.HasFlag(GenericParameterAttributes.ReferenceTypeConstraint)
        && typeArgument.IsValueType)
        return false;  // 要求 class，但传入了 struct

    if (attributes.HasFlag(GenericParameterAttributes.NotNullableValueTypeConstraint)
        && !typeArgument.IsValueType)
        return false;  // 要求 struct，但传入了 class

    if (attributes.HasFlag(GenericParameterAttributes.DefaultConstructorConstraint)
        && typeArgument.GetConstructor(Type.EmptyTypes) == null)
        return false;  // 要求 new()，但没有无参构造函数

    // 2. 检查接口和基类约束
    var constraints = genericArgument.GetGenericParameterConstraints();
    foreach (var constraint in constraints)
    {
        if (constraint.IsGenericType && constraint.ContainsGenericParameters)
        {
            // 开放泛型约束，如 IEquatable<T>，需要具体化
            var concreteConstraint = constraint.GetGenericTypeDefinition()
                .MakeGenericType(typeArgument);
            if (!concreteConstraint.IsAssignableFrom(typeArgument))
                return false;
        }
        else
        {
            // 普通约束，如基类约束
            if (!constraint.IsAssignableFrom(typeArgument))
                return false;
        }
    }
    return true;
}
```

**什么时候需要这个？**

在框架自动注册系统或插件系统中，运行时动态实例化泛型类型时，编译器无法帮你检查约束，只能在运行时校验：

```csharp
// 运行时动态构造 Handler<T>
foreach (var type in allTypes)
{
    if (ReflectUtil.AreTypeArgumentsValid(typeof(Handler<>), type))
    {
        var handlerType = typeof(Handler<>).MakeGenericType(type);
        RegisterHandler(handlerType);
    }
}
```

---

## 成员读写：统一的字段/属性访问

反射读写字段的核心逻辑：

```csharp
private static bool GetMemberInfo(Type type, string memberName,
    out FieldInfo fieldInfo, out PropertyInfo propertyInfo)
{
    fieldInfo = null;
    propertyInfo = null;

    // 先找字段
    fieldInfo = type.GetField(memberName,
        BindingFlags.Public | BindingFlags.NonPublic |
        BindingFlags.Static | BindingFlags.Instance);
    if (fieldInfo != null) return true;

    // 再找属性
    propertyInfo = type.GetProperty(memberName,
        BindingFlags.Public | BindingFlags.NonPublic |
        BindingFlags.Static | BindingFlags.Instance);
    if (propertyInfo != null) return true;

    // 递归查找基类
    if (type.BaseType != null)
        return GetMemberInfo(type.BaseType, memberName, out fieldInfo, out propertyInfo);

    return false;
}
```

三个关键设计：

1. **字段优先**：先找字段，没有才找属性。这是因为字段访问更直接，且框架内部大量使用字段而非属性。

2. **BindingFlags 全覆盖**：`Public | NonPublic | Static | Instance` 确保能访问私有字段——这在序列化和调试工具中非常必要。

3. **递归遍历继承链**：如果当前类找不到，递归到基类查找。解决了"访问父类私有字段"的问题，这是原生 API 需要手动循环处理的。

### 简洁的公开 API

```csharp
// 读取成员（统一处理字段和属性）
public static T GetMember<T>(object instance, string memberName);
public static object GetMember(object instance, string memberName);

// 写入成员
public static void SetMember(object instance, string memberName, object value);

// 调用方法
public static T Invoke<T>(object instance, string methodName, params object[] parameters);
```

调用方无需关心底层是字段还是属性，无需写 `BindingFlags`，无需处理继承链——一行搞定。

---

## 对象创建工具

```csharp
// 创建指定类型的数组，并初始化每个元素
public static T[] CreateArray<T>(int len)
{
    var array = Array.CreateInstance(typeof(T), len) as T[];
    for (var i = 0; i < array.Length; i++)
        array[i] = (T)Activator.CreateInstance(typeof(T));
    return array;
}

// 创建 List<T>（T 在运行时确定）
public static object CreateList(Type itemType)
{
    var collectionType = typeof(List<>);
    return Activator.CreateInstance(collectionType.MakeGenericType(itemType));
}
```

`CreateList` 在配置表反序列化、动态创建集合类型时特别有用：

```csharp
// 运行时根据字段类型创建集合
var fieldType = field.FieldType; // 比如 List<SkillConfig>
if (fieldType.IsGenericType && fieldType.GetGenericTypeDefinition() == typeof(List<>))
{
    var elementType = fieldType.GetGenericArguments()[0];
    var list = ReflectUtil.CreateList(elementType);
    // 往 list 里填数据...
}
```

---

## 性能注意事项

反射有性能开销，在游戏中使用时需要注意：

### 1. 缓存 FieldInfo / MethodInfo

每次 `GetField` / `GetMethod` 都有开销，应该缓存结果：

```csharp
// ❌ 每帧调用
void Update()
{
    var value = ReflectUtil.GetMember<float>(unit, "_health");
}

// ✅ 启动时缓存 FieldInfo，后续直接用
private FieldInfo _healthField;
void Awake()
{
    _healthField = typeof(Unit).GetField("_health",
        BindingFlags.NonPublic | BindingFlags.Instance);
}
void Update()
{
    var value = (float)_healthField.GetValue(unit);
}
```

### 2. 反射只在初始化阶段使用

框架中反射的最佳实践是：**启动时扫描，运行时用结果**。`InitTypes()` 只调用一次，收集到的类型列表用于注册 Handler、构建分发表等，之后运行时走的是直接调用，不再反射。

### 3. IL2CPP 下的反射限制

发布到 iOS / 主机平台时使用 IL2CPP，反射能力受限（AOT 裁剪）。`link.xml` 中需要保留需要反射访问的类型，否则字段会被裁剪掉。

---

## 小结

`ReflectUtil` 是一个典型的"粘合层"工具类，它不创造新能力，而是把原生反射 API 的摩擦降到最低：

- **`GetType`** — 跨程序集类型查找，热更友好
- **`ChangeType`** — 处理 Enum/Nullable/Guid 的健壮类型转换
- **`AreTypeArgumentsValid`** — 运行时泛型约束校验
- **`GetMember / SetMember`** — 统一字段/属性访问，自动遍历继承链
- **`Invoke`** — 简洁的方法反射调用
- **`CreateArray / CreateList`** — 运行时动态创建集合

在游戏框架的"元编程"层（自动注册、动态分发、序列化、调试工具）中，这些工具是不可或缺的基础设施。用对了，能让框架层的代码极大简化；用错了（比如在高频 Update 里反射），则会成为性能瓶颈。**了解它能做什么，更重要的是知道什么时候不该用它**。
