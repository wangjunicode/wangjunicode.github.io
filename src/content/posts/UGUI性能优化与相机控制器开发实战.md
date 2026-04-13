---
title: UGUI性能优化与相机控制器开发实战
published: 2024-07-01
description: "Loading加载优化统计，UGUI性能优化，UISelector工具开发，相机控制器优化，公会联赛需求开发"
tags: [Unity, 游戏开发, 技术实践]
category: 技术实践
draft: false
---

## 07/01 Timeline 加载接口优化

- Loading 时长优化分析
- Timeline 加载接口改进
- YouMe SDK 历史记录优化

## 07/02 场景加载时长统计

### 场景文件大小参考
```
sc_gve_village_001          约30MB
sc_cmd_fild01_001           12.3MB
sc_gve_monsterdragon01      10.7MB
sc_pay_fild09_001           11.1MB
sc_prontera_001             6.4MB
sc_prt_fild06_001（普隆德拉东门） 4.7MB
```

### 加载时长数据（各阶段差值，秒）

| 阶段 | 时间（秒） | 差值（秒） |
|------|---------|---------|
| 加载时间统计1_0 | 0.000004 | — |
| 加载时间统计1_1 | 0.001438 | 0.001434 |
| 加载时间统计1_2 | 0.002876 | 0.001438 |
| 加载时间统计1_3 | 0.004283 | 0.001407 |

数据可视化：南丁格尔玫瑰图展示各阶段耗时比例。

## 07/03 UGUI 性能知识

### UGUI 点击检测原理
UGUI 不使用 Collider，而是通过 **Graphic Raycaster** + **Event System** 处理点击：
- **Graphic Raycaster**：专门处理 UI 元素的射线投射，理解屏幕空间位置
- **Event System**：管理所有输入事件，传递给适当的 UI 元素

### Image 和 Text 的网格
- `Image`：一个长方形网格（2个三角形，4个顶点）
- `Text`：每个字符一个长方形网格（2个三角形，4个顶点）

## 07/04 Lua 资源加载 & UGUI 优化

### Lua require 文件加载机制
`require` 通过 `LuaEnv.AddLuaLoader` 接口重载加载逻辑，直接使用 `fsni` 库打开文件，避免了 Bundle 的解压和解析，相对更快。

### UGUI 点击检测自定义
重载 Image 的 `IsRaycastLocationValid`：
- 该方法只在鼠标光标落在 Image 的 `RectTransform` 内才触发检测
- 自定义检测区域至少要在这个基础之上
- 若用 Collider 形式，Collider 需要独立的 `RectTransform`

### UGUI 性能优化技巧
- 通过将 UI 元素坐标移到 Canvas 范围外来显示/隐藏，**避免 SetActive 的耗时**和 `SendWillRenderCanvases` 的耗时

## 07/05 Lua 访问 C# 属性的 GC 问题

### transform.position 的 GC 问题
```lua
-- ❌ 有 GC（getter 返回值类型需要装箱）
local pos = transform.position

-- ✅ 无 GC（使用 NoGC 方法）
local pos = transform:GetPositionNoGC()

-- ✅ 设置位置直接赋值没问题
transform.position = newPos
```

### UI 位置设置并限制在屏幕内

```lua
function Lua_UI_Helper.SetPositionAndClampToScreen(
        sourceRectTransform, targetRectTransform, rectSize)
    local uiCamera = Lua_UIManagerNew:GetInstance():GetUICamera()
    if uiCamera then
        local screenPos = uiCamera:WorldToScreenPoint(targetRectTransform.position)
        local size = rectSize or sourceRectTransform.rect.width / 2
        local fixWidth = 1920
        local fixHeight = 1080
        local scrHeight = CS.UnityEngine.Screen.height
        local scrWidth = CS.UnityEngine.Screen.width
        local scale = math.max(fixWidth / scrWidth, fixHeight / scrHeight)
        scrHeight = scrHeight * scale
        scrWidth = scrWidth * scale
        screenPos.x = Mathf.Clamp(screenPos.x, size, scrWidth - size)
        screenPos.y = Mathf.Clamp(screenPos.y, size, scrHeight - size)
        local uiPos = uiCamera:ScreenToWorldPoint(screenPos)
        sourceRectTransform.position = uiPos
    end
end
```

## 07/08 性能优化理论

### CPU 性能相关概念
- **主线程（Main Thread）**：处理游戏主要逻辑（输入、物理、Lua 逻辑等）
- **渲染线程（Render Thread）**：处理渲染相关任务（与主线程分离）
- **Draw Call（DC）**：CPU 向 GPU 发出的绘制命令，越少越好
- **SetPass Call**：更换 Shader 或渲染状态的次数，是性能瓶颈
- **Batching**：合并多个绘制命令为一个，减少 DC（静态/动态批处理）

### GPU 性能相关概念
- **Mipmap**：预计算不同分辨率纹理，按视距选择，减少显存占用和失真
- **GPU Fragment & Vertices**：顶点处理（几何变换/光照）+ 片段处理（像素着色）

### 内存相关概念
- **托管堆内存（Managed Heap）**：C# 对象，由 GC 管理
- **Unity Native 内存**：引擎内部纹理/网格等数据
- **PSS 内存**：进程实际占用的物理内存（含共享内存按比例分摊）
- **内存碎片**：频繁分配/释放导致不连续空闲块，影响性能

### CanvasScaler 屏幕适配策略
1. **Match Width or Height**：按宽或高缩放 Canvas
2. **Expand**：保证设计分辨率内容全部显示（可能有黑边），选最小缩放因子
3. **Shrink**：不留黑边但内容可能显示不完全，选最大缩放因子

## 07/11 UI 坐标系与屏幕适配

### 坐标变换原理（MVP 矩阵）
```
Model Matrix（模型矩阵）：本地坐标 → 世界坐标
View Matrix（视图矩阵）：世界坐标 → 相机坐标
Projection Matrix（投影矩阵）：相机坐标 → 裁剪空间/NDC
视口变换 → 屏幕坐标
```

### 获取 RectTransform 四个角的世界坐标
```lua
local worldCorners = CS.System.Array.CreateInstance(typeof(CS.UnityEngine.Vector3), 4)
targetRectTransform:GetWorldCorners(worldCorners)
-- worldCorners[0..3] 是四个角的世界坐标
```

### 最终屏幕限制函数（最优方案）

```lua
function Lua_UI_Helper.SetPositionAndClampToScreen(
        sourceRectTransform, targetRectTransform, parentCtrl, offsetX, offsetY)
    local kCamera = Lua_UIManagerNew:GetInstance():GetUICamera()
    local screenPos = kCamera:WorldToScreenPoint(targetRectTransform.position)
    local parentCtrlRect = Lua_UI_Helper.FindComponent(
        parentCtrl.transform, typeof(CS.UnityEngine.RectTransform))
    local sourceParentRect = Lua_UI_Helper.FindComponent(
        sourceRectTransform.parent.transform, typeof(CS.UnityEngine.RectTransform))

    local success, uiPos = UIHelper.ScreenPointToLocalPointInRectangle(
        parentCtrlRect, screenPos, kCamera)
    if success then
        local canvasWidth = parentCtrlRect.rect.width
        local canvasHeight = parentCtrlRect.rect.height
        local finalX = Mathf.Clamp(uiPos.x,
            -canvasWidth / 2 + offsetX, canvasWidth / 2 - offsetX)
        local finalY = Mathf.Clamp(uiPos.y,
            -canvasHeight / 2 + offsetY, canvasHeight / 2 - offsetY)
        local diffX = uiPos.x - finalX
        local diffY = uiPos.y - finalY

        local ok, uiNewPos = UIHelper.ScreenPointToLocalPointInRectangle(
            sourceParentRect, screenPos, kCamera)
        if ok then
            uiNewPos.x = uiNewPos.x - diffX
            uiNewPos.y = uiNewPos.y - diffY
            sourceRectTransform.anchoredPosition = uiNewPos
        end
    end
end
```

**思路**：转成 Canvas 局部坐标 → Clamp 限制 → 计算差值偏移 → 应用到目标 anchoredPosition。

## 07/15 相机控制器优化（惯性效果）

### 原始相机旋转插值（无惯性停止）
```lua
-- 定速插值（渐慢效果）
self.m_kCamera.RotationLerp(
    self.m_kNowRotation, self.m_kNowRotation,
    kTargetRotation, fDelta * self.m_kParam._fRotateSpeed)
```

### 修改后（支持惯性开关）
```lua
if self.m_fRotationDuration then  -- 定时插值
    self.m_kCamera.RotationLerp(
        self.m_kNowRotation, self.m_kNowRotation,
        kTargetRotation, fDelta / self.m_fRotationDuration)
    self.m_fRotationDuration = self.m_fRotationDuration - fDelta
    if self.m_fRotationDuration <= 0 then
        self.m_fRotationDuration = nil
    end
else  -- 定速插值
    if self.m_kParam._fInertia > 0 then
        self.m_kCamera.RotationLerp(
            self.m_kNowRotation, self.m_kNowRotation,
            kTargetRotation, fDelta * self.m_kParam._fRotateSpeed)
    else
        self.m_kNowRotation = kTargetRotation  -- 无惯性，直接到位
    end
end
```

### Lerp vs 直接赋值
| 方式 | 特点 |
|------|------|
| Lerp | 多帧逐渐逼近，平滑过渡效果 |
| 直接赋值 | 当帧立即到位，无过渡 |

### UISelector 编辑器工具
在 Scene 视图右键点击 UI，弹出菜单选择对应的 RectTransform 组件（支持嵌套选择）：

```csharp
#if ENABLE_UI_SELECTOR
[InitializeOnLoad]
public static class UISelector
{
    static UISelector() { SceneView.duringSceneGui += OnSceneGUI; }

    private static void OnSceneGUI(SceneView sceneView)
    {
        var ec = Event.current;
        if (ec != null && ec.button == 1 && ec.type == EventType.MouseUp)
        {
            var mousePosition = Event.current.mousePosition;
            float mult = EditorGUIUtility.pixelsPerPoint;
            mousePosition.y = sceneView.camera.pixelHeight - mousePosition.y * mult;
            mousePosition.x *= mult;

            // 找到鼠标下所有 RectTransform，弹出右键菜单供选择
            var groups = GetAllScenes()
                .Where(m => m.isLoaded)
                .SelectMany(m => m.GetRootGameObjects())
                .SelectMany(m => m.GetComponentsInChildren<RectTransform>())
                .Where(m => RectTransformUtility.RectangleContainsScreenPoint(
                    m, mousePosition, sceneView.camera))
                .GroupBy(m => m.gameObject.scene.name);
            // ... 构建右键菜单
        }
    }
}
#endif
```

## 07/19 DPad 优化

### 多点触控 pointerId 判断
```csharp
private void OnDrag(PointerEventData eventData)
{
    if (pointId == eventData.pointerId)
    {
        // 只处理与开始拖动相同的输入源
    }
}
```

### 箭头旋转跟随（Atan2）
```csharp
Vector2 direction = (thumb.position - bottomCircle.position).normalized;
float angle = Mathf.Atan2(direction.y, direction.x) * Mathf.Rad2Deg;
arrow.localEulerAngles = new Vector3(0, 0, angle);
```

## 07/22 Lua table 清理 & Buff 逻辑

### Lua table 清理方式
```lua
-- 方式1：简单置 nil（适合结构简单的表）
myTable = nil

-- 方式2：递归清理（适合深度嵌套，更快释放内存）
local function clearTable(t)
    for k, v in pairs(t) do
        if type(v) == "table" then clearTable(v) end
        t[k] = nil
    end
end
clearTable(myTable)
myTable = nil
```

**原理**：`table = nil` 只是解除引用，GC 会在下次回收周期中回收。嵌套 table 在外层不可达时也会被回收。

### Lua __call 元方法
```lua
local UpdateBeat = {}
setmetatable(UpdateBeat, {
    __call = function(tbl, ...)
        print("UpdateBeat called with:", ...)
    end
})
UpdateBeat(1, 2, 3)  -- 可以像函数一样调用 table
```

## 07/23-24 UGUI 点击 Bug 修复

### 按钮缩放导致点击失效
**问题**：缩放 UI 时，鼠标在按下后抬起时位置可能不在检测区域内，导致 click 事件失效。

**有效 click 的定义**：按下和抬起都在检测区域内才算有效点击。

**解决方案**：
1. 缩放只缩放 UI 显示，不缩放检测区域（`RectTransform` 不缩放）
2. 或记录按下位置，抬起时检查差值是否在有效范围内

### ISubmitHandler vs IPointerClickHandler
| 接口 | 触发方式 |
|------|---------|
| `ISubmitHandler` | 键盘回车/控制器确认键 |
| `IPointerClickHandler` | 鼠标点击/触摸点击 |

## 07/26 KCP 协议 & 相机控制

### KCP 协议
KCP 是一个快速可靠的 ARQ 协议，用于游戏实时通信，牺牲带宽换取延迟。

相关：[KCP GitHub](https://github.com/skywind3000/kcp)

### 相机控制最终架构
- 业务侧通过 `RD_CameraController_LockTr` 控制
- 核心变量：`m_kFinalRotation`、`m_kFinalLocation`
- FoV 通过虚拟相机控制

```lua
-- 设置位置（无 GC 接口）
CS.LA_LuaFunction.SetComponentLocalPosition(
    self:GetLuaVirtualCameraRT(),
    self.m_vNowPos.x, self.m_vNowPos.y, self.m_vNowPos.z)

-- 设置旋转
CS.LA_LuaFunction.SetComponentLocalEulerAngles(
    self:GetLuaVirtualCameraRT().parent,
    self.m_vNowRot.x, self.m_vNowRot.y, self.m_vNowRot.z)
```

## 07/29 公会联赛需求评估

| 模块 | 工时 |
|------|------|
| 本服联赛 | 3人日 |
| 公会赛程 | 2人日 |
| 历史战绩 | 2人日 |
| 战报详情 | 2人日 |
| 参赛资格 | 2人日 |
| 奖励预览 | 2人日 |
| DAL开发 | 3人日 |
| 联调自测 | 2人日 |

## 07/30 Deep Profiler 调试技巧

- **暂停模式搜索**：Deep Profiler 在暂停模式下可以搜索特定函数
- **不只看 GC 峰值**：帧率低的地方也要重点排查
- `ISubmitHandler`（键盘确认）和 `IPointerClickHandler`（鼠标点击）分工明确

## 07/31 异步加载优化 & 命名规范

### 大 Prefab 异步加载仍影响帧率的原因
1. 大量内存分配
2. 解压缩/反序列化（CPU 密集）
3. 某些步骤必须在主线程执行（实例化）
4. GC 压力增加

**优化方向**：分块加载、Addressables、预加载、控制并发数。

### Lua 命名规范
- 私有函数：`_funcName`（下划线前缀）
- 公有函数：`FuncName`（大写开头）
