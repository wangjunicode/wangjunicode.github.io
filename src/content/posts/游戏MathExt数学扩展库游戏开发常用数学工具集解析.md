---
title: 游戏 MathExt 数学扩展库：游戏开发常用数学工具集解析
published: 2026-03-31
description: 系统梳理游戏开发中超越 Unity Mathf 的常用数学扩展，包括插值、曲线、角度、随机数和空间计算等实用工具的实现原理。
tags: [Unity, 数学工具, 游戏数学, 扩展方法]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么需要自定义数学工具？

Unity 内置的 `Mathf` 提供了基础的数学函数（Lerp、Clamp、Sin 等），但在实际游戏开发中，我们需要更多的工具。

`MathExt.cs` 是项目积累的数学扩展库，收录了各种在游戏逻辑中反复使用的数学方法。

---

## 常用插值与曲线

### 弹性插值（Spring Lerp）

标准 `Lerp` 是线性的，但游戏中的运动往往需要"弹性感"——开始快、结束慢，或者超过目标后回弹：

```csharp
// 弹性阻尼（Critically Damped Spring）
public static float SpringLerp(float current, float target, ref float velocity, float smoothTime, float deltaTime)
{
    float omega = 2f / smoothTime;
    float x = omega * deltaTime;
    float exp = 1f / (1f + x + 0.48f * x * x + 0.235f * x * x * x);
    float change = current - target;
    float temp = (velocity + omega * change) * deltaTime;
    velocity = (velocity - omega * temp) * exp;
    return target + (change + temp) * exp;
}

// 使用：相机跟随
void Update()
{
    transform.position = new Vector3(
        MathExt.SpringLerp(transform.position.x, target.x, ref _velocityX, 0.3f, Time.deltaTime),
        transform.position.y,
        MathExt.SpringLerp(transform.position.z, target.z, ref _velocityZ, 0.3f, Time.deltaTime)
    );
}
```

这是**弹簧质量系统（Spring-Mass System）**的数值近似，比 `SmoothDamp` 更可控，是相机跟随、UI 动画的常用工具。

---

## 角度与旋转工具

### 角度标准化（归一化到 -180 ~ 180）

```csharp
public static float NormalizeAngle(float angle)
{
    angle = angle % 360f;
    if (angle > 180f) angle -= 360f;
    if (angle < -180f) angle += 360f;
    return angle;
}

// 使用场景：计算两个角度之间的最短旋转方向
float angleDiff = NormalizeAngle(targetAngle - currentAngle);
// 如果 angleDiff > 0，向右旋转；< 0，向左旋转
```

没有这个函数，直接相减可能得到 350 度而不是 -10 度，导致角色旋转时"绕远路"。

### 平面角度插值

```csharp
public static float LerpAngle(float a, float b, float t)
{
    float delta = NormalizeAngle(b - a);
    return a + delta * t;
}
```

---

## 空间判断工具

### 点在多边形内判断（射线法）

```csharp
public static bool PointInPolygon(Vector2 point, Vector2[] polygon)
{
    bool inside = false;
    int j = polygon.Length - 1;
    for (int i = 0; i < polygon.Length; j = i++)
    {
        if (((polygon[i].y > point.y) != (polygon[j].y > point.y)) &&
            (point.x < (polygon[j].x - polygon[i].x) * (point.y - polygon[i].y) 
                       / (polygon[j].y - polygon[i].y) + polygon[i].x))
        {
            inside = !inside;
        }
    }
    return inside;
}

// 使用：判断玩家是否在某个区域内
var regionPoints = new[] { new Vector2(0,0), new Vector2(10,0), new Vector2(10,10), new Vector2(0,10) };
if (MathExt.PointInPolygon(player.Position2D, regionPoints))
{
    TriggerAreaEffect();
}
```

### 直线与圆的交点

```csharp
public static bool LineCircleIntersect(Vector2 lineStart, Vector2 lineEnd, 
    Vector2 center, float radius, out Vector2[] points)
{
    Vector2 d = lineEnd - lineStart;
    Vector2 f = lineStart - center;
    
    float a = Vector2.Dot(d, d);
    float b = 2 * Vector2.Dot(f, d);
    float c = Vector2.Dot(f, f) - radius * radius;
    
    float discriminant = b * b - 4 * a * c;
    if (discriminant < 0)
    {
        points = null;
        return false;
    }
    
    // 计算交点...
}
```

---

## 随机数工具

### 带权重的随机选择

```csharp
public static int WeightedRandom(float[] weights)
{
    float total = 0f;
    foreach (var w in weights) total += w;
    
    float random = Random.Range(0f, total);
    float accumulated = 0f;
    
    for (int i = 0; i < weights.Length; i++)
    {
        accumulated += weights[i];
        if (random <= accumulated)
            return i;
    }
    return weights.Length - 1;
}

// 使用：掉落概率
float[] dropWeights = { 70f, 20f, 8f, 2f };  // 普通、优秀、稀有、史诗
int dropType = MathExt.WeightedRandom(dropWeights);
```

---

## 总结

数学工具库是游戏代码库中最有价值的积累之一。每个工具函数都来自实际需求的沉淀。

对于新手，建议养成习惯：遇到常见的数学计算模式，先看看项目的 MathExt 是否已有实现，而不是每次都从零开始写。这是团队代码复用的基础。
