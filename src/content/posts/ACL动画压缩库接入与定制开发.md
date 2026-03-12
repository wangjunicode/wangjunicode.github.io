---
title: ACL 动画压缩库接入与定制开发
published: 2026-03-10
description: 深入理解 Animation Compression Library（ACL）的架构原理，完成构建工具链、压缩参数实验，并实现"禁止常量折叠"自定义功能，满足大型商业游戏动画管线需求。
tags: [C++, 游戏开发, 动画, 压缩, ACL]
category: 游戏引擎
draft: false
---

## 一、项目背景

ACL（Animation Compression Library）是一个开源的游戏动画压缩库，主要用于对骨骼动画数据进行高效压缩存储，被 Unreal Engine 等商业引擎采用。本次工作目标：

1. 完整构建 `acl_compressor.exe` 工具链
2. 在真实动画文件上实验不同压缩参数的效果
3. 实现自定义功能：允许指定骨骼名称，禁止其被常量折叠，强制保留为完整动画轨道

---

## 二、环境搭建

### 工具链

| 工具 | 版本 |
|------|------|
| CMake | 4.2.3 |
| Visual Studio Build Tools | 2022 (MSBuild 17.14) |
| Python | 3.x + numpy 2.4.3 + sjson 2.1.1 |

### CMakeLists 兼容性修复

ACL 仓库的 CMakeLists 使用旧语法 `cmake_minimum_required(VERSION 3.2)`，在 CMake 4.x 下触发策略错误。需将所有 CMake 文件（共 22 个）改为版本范围语法：

```cmake
# 修改前
cmake_minimum_required(VERSION 3.2)

# 修改后（兼容 CMake 3.x 和 4.x）
cmake_minimum_required(VERSION 3.2...4.0)
```

`3.2...4.0` 的含义：告诉 CMake "我知道 3.2 到 4.0 之间的所有策略变化，我已经处理好了"，从而让 4.x 不报 policy 警告。

### 构建

```bash
# 初始化子模块（rtm、sjson-cpp、catch2、benchmark）
git submodule update --init --recursive

# CMake 配置
cmake -S . -B build_out

# 只构建压缩工具，不构建单元测试
cmake --build build_out --config Release --target acl_compressor
```

输出路径：`build_out/tools/acl_compressor/main_generic/Release/acl_compressor.exe`（约 1.08 MB）

---

## 三、压缩参数实验

### 输入格式

ACL 压缩工具支持两种输入：
- `.acl`：二进制格式
- `.acl.sjson`：SJSON 文本格式（人类可读，包含骨骼定义和关键帧数据）

> **踩坑**：`.acl.sjson` 文件内部的 `settings {}` 块会被忽略，格式覆盖必须通过 `-config=<file.config.sjson>` 外部配置文件传入。

### 测试文件：BaiShenYao_11000000_GameReady0_01

- 动画时长：5.58 秒 @ 60fps，336 帧，229 根骨骼
- 原始大小：约 3 MB

### 对比结果

| 配置 | 旋转格式 | 压缩后大小 | 压缩比 | 压缩耗时 |
|------|----------|-----------|--------|---------|
| 默认（variable） | `quatf_drop_w_variable` | 164.91 KB | 18.23:1 | 0.72s |
| 全精度（full） | `quatf_drop_w_full` | ~220 KB | ~4.7:1 | ~0.03s |

### 两种模式核心权衡

**`quatf_drop_w_variable`（推荐用于发布）**
- 逐骨骼搜索最优 bit-rate（1~22 bit）
- 通过误差度量评估每个候选精度
- 输出最小，但压缩耗时较长
- 适合资产管线离线打包

**`quatf_drop_w_full`**
- 固定 96-bit 全精度（XYZ 各 32bit，丢弃可还原的 W 分量）
- 跳过搜索，速度快 10x
- 文件大 3x，适合开发调试阶段

---

## 四、ACL 压缩流程原理

ACL 的压缩分 7 个步骤：

```
compress_track_list(track_list, settings)
    │
    ├─ Step 1: 参数校验 + 初始化 clip_context
    ├─ Step 2: 预处理（循环优化、旋转格式统一）
    ├─ Step 3: 常量折叠 compact_constant_streams()  ← 最重要的优化
    ├─ Step 4: 范围归一化 normalize_streams()
    ├─ Step 5: 量化搜索 quantize_streams()           ← 最耗时的阶段
    ├─ Step 6: 关键帧裁剪（可选）
    └─ Step 7: 序列化 write_compressed_clip()
```

### 常量折叠

对每根骨骼的旋转、位移、缩放三条子轨道分别检测：如果所有帧的值相同（在精度阈值内），则折叠为 1 个样本。折叠后解压时任何时间点都返回这个固定值，占存储极小。

### 量化

将 32-bit float 用更少的 bit 近似表示。核心流程：

```
原始值 v = 0.7351（float）
本 segment 的 min = -0.5, extent = 2.0

归一化：normalized = (v - min) / extent = 0.6176
量化：  quantized  = round(normalized × (2^bits - 1))
       8 bit → quantized = round(0.6176 × 255) = 157

解压：  normalized = 157 / 255.0 = 0.6157
       restored   = normalized × extent + min = 0.7314
误差：  |0.7351 - 0.7314| = 0.0037  ✓ 在阈值内
```

variable 模式的"慢"就在于：对每条子轨道枚举所有 bit-rate，选出误差刚好低于阈值的最小值。

---

## 五、自定义功能：禁止常量折叠（Force Animated Bone Names）

### 需求

`Bip004` 骨骼的所有帧数据完全相同（纯常量），ACL 默认将其折叠为单帧存储。但引擎运行时的骨骼遮罩（bone mask）、动画混合等需要该骨骼保留完整轨道。

### 实现方案

**最小侵入式修改，共 3 个文件：**

#### 1. `compression_settings.h` — 新增字段

```cpp
// 新增 include
#include <vector>
#include <string>

// 在 compression_settings struct 内新增
std::vector<std::string> force_animated_bone_names;

bool is_bone_force_animated(const char* bone_name) const
{
    if (bone_name == nullptr) return false;
    for (const std::string& name : force_animated_bone_names)
        if (name == bone_name) return true;
    return false;
}
```

#### 2. `compact.transform.h` — 常量折叠时跳过指定骨骼

```cpp
// 在循环内，原有 assertions 之后插入：
const bool is_force_animated =
    settings.is_bone_force_animated(
        track_list[transform_index].get_name().c_str());

// 三处判断均加入 !is_force_animated 前置条件
if (!is_force_animated && are_rotations_constant(...))    { /* 折叠 */ }
if (!is_force_animated && are_translations_constant(...)) { /* 折叠 */ }
if (!is_force_animated && are_scales_constant(...))       { /* 折叠 */ }
```

#### 3. `acl_compressor.cpp` — 新增命令行参数

```bash
# 单骨骼
acl_compressor.exe -acl=input.acl.sjson -out=output.acl -force_animated=Root

# 多骨骼（逗号分隔）
acl_compressor.exe -acl=input.acl.sjson -out=output.acl -force_animated=Root,Bip004,Bip01_Pelvis
```

### 测试结果

| 配置 | 文件大小 | 差异 |
|------|---------|------|
| 正常压缩（Bip004 被折叠） | 164.91 KB | — |
| `-force_animated=Bip004` | 165.04 KB | +140 bytes |

**+140 bytes** 正好是 Bip004 三条子轨道从"1个常量样本"变为"336个完整样本"的 variable 量化存储增量，数据非常干净。

### C++ API 使用方式

```cpp
acl::compression_settings settings = acl::get_default_compression_settings();
settings.error_metric = &error_metric;

// 指定不允许被常量折叠的骨骼
settings.force_animated_bone_names = { "Root", "Bip004" };

acl::compressed_tracks* compressed = nullptr;
acl::compress_track_list(allocator, track_list, settings, compressed, stats);
```

---

## 六、设计决策复盘

### 为什么不用 `unordered_set` 而用线性查找？

骨骼排除列表通常只有几个到十几个名称，线性查找在短列表上与哈希表性能相当（避免哈希函数和桶分配开销），且代码更简洁，不需要额外引入 `<unordered_set>`。

### 为什么只修改 ORIGINAL 算法，不修改 PRECISE 算法？

宏 `ACL_IMPL_CONSTANT_FOLDING_ALGO` 当前值为 `0`（ORIGINAL），PRECISE 变体代码虽然存在但未激活。修改 ORIGINAL 已满足需求，PRECISE 留待后续按需扩展，避免过度工程。

### 为什么加在 `compression_settings` 而不是函数参数？

`compression_settings` 本就是所有压缩选项的聚合结构，语义上最合适；`compact_constant_streams` 已经接收 `settings` 参数，无需修改函数签名，对现有 API 零破坏（新字段默认为空 vector，行为与之前完全一致）。

---

## 七、后续优化方向

| 方向 | 说明 |
|------|------|
| Config 文件支持 | 在 `.config.sjson` 里增加 `force_animated_bone_names` 数组字段 |
| 通配符匹配 | 支持 `Bip004_*` 模式，批量排除某条骨骼链 |
| PRECISE 算法 | 在另一个常量折叠变体中做相同修改 |
| 大小写不敏感 | 增加 ignore-case 匹配选项 |

---

## 参考

- [ACL GitHub 仓库](https://github.com/nfrechette/acl)
- [nfrechette 博客：动画压缩系列文章](https://nfrechette.github.io/)
- [RTM（Realtime Math）库](https://github.com/nfrechette/rtm)
