---
title: ACL 动画压缩库架构拆解
published: 2026-03-12
description: 面向 C++ 初学者的 ACL 架构全景图，涵盖压缩流程、解压原理、核心数据结构、量化算法、误差度量机制，以及如何在商业游戏项目中进行定制扩展。
tags: [C++, 游戏开发, 动画, 压缩, ACL, 架构]
category: 游戏引擎
draft: false
---

> **面向人群：** C++ 了解到面向对象阶段，有游戏开发基础  
> **目标：** 读完后能看懂 ACL 源码，独立扩展定制功能

---

## 一、读前必备：骨骼动画基础

### 数据长什么样

一个角色的动画，本质是这样的数据：

```
动画（1.85秒，60fps，112帧，229骨骼）
├── frame[0]
│     ├── Bone_Root:     { 旋转 Q, 位移 T, 缩放 S }
│     ├── Bone_Spine:    { 旋转 Q, 位移 T, 缩放 S }
│     └── ... 229根骨骼
├── frame[1]
│     └── ...
└── frame[111]
      └── ...
```

**旋转用四元数（Quaternion）表示**，4 个分量 X Y Z W，满足 X²+Y²+Z²+W²=1。W 可以从 XYZ 反算，所以存储时可以省掉 W（这正是 `quatf_drop_w` 的含义）。

### 未压缩有多大？

```
229骨骼 × 112帧 × (4+3+3) float × 4 bytes = ~1 MB

ACL 实际 raw_size ≈ 3 MB（内部用 16-byte 对齐的 vector4f 存每个通道）
ACL 压缩后 ≈ 165 KB，压缩比 18:1
```

---

## 二、整体架构思想

### 2.1 Header-Only 库

ACL 是纯头文件库，所有代码在 `includes/acl/` 下，没有需要链接的 `.lib`。

```
你的项目                                    ACL
┌────────────┐    #include "acl/..."    ┌───────────────────┐
│ game.cpp   │ ────────────────────>   │ compress.h        │
│            │                         │ decompress.h      │
│            │                         │ ... 全是 .h 文件   │
└────────────┘                         └───────────────────┘
```

### 2.2 三层目录，压缩与解压严格分离

```
includes/acl/
├── core/          ← 基础设施（allocator、数学、格式定义）
├── compression/   ← 压缩侧：离线工具/资产管线使用
├── decompression/ ← 解压侧：游戏运行时使用
├── io/            ← 文件读写（.acl.sjson）
└── math/          ← 量化打包工具函数
```

> **关键设计原则：`decompression/` 不依赖 `compression/`。**  
> 游戏 runtime 只打包 `core/` + `decompression/`，压缩代码完全不进包体。

---

## 三、核心数据结构

### 3.1 压缩前：`track_array_qvvf`

`qvvf` = Quaternion + Vector（位移）+ Vector（缩放）+ float（精度）

```
track_array_qvvf（整个动画）
└── track_qvvf [0..N-1]（一根骨骼）
        ├── track_desc_transformf（元数据）
        │       ├── default_value  ← 默认姿态（bind pose）
        │       ├── precision      ← 允许误差（默认 0.01 cm）
        │       ├── shell_distance ← 骨骼末端距离（影响误差计算）
        │       └── parent_index   ← 父骨骼索引
        └── 每帧数据：frame[0..N-1] 的 qvvf 采样值
```

访问骨骼名称：
```cpp
const char* name = track_list[bone_index].get_name().c_str();
```

### 3.2 压缩后：`compressed_tracks`

```
compressed_tracks（一块连续内存 blob）
├── tracks_header          ← 骨骼数/帧数/帧率/格式标志
├── sub_track_types bitset ← 每条子轨道的类型（default/constant/animated）
├── 常量轨道数据           ← 每个 constant 骨骼存 1 个样本
├── 每段 range 数据        ← 解量化用的 min/extent
└── 每段 bit-packed 数据   ← 动画帧的量化比特流
```

`compressed_tracks` **不含指针**，可以直接 memcpy 或写入文件，天然跨平台。

### 3.3 子轨道的三种状态

每条子轨道（rotation/translation/scale）有三种状态：

| 状态 | 含义 | 存储开销 |
|------|------|---------|
| `default` | 等于 `default_value` | **零开销**（不存储，直接用默认值） |
| `constant` | 所有帧相同，但不等于默认值 | **1 个样本** |
| `animated` | 帧间有变化 | **N 个量化样本** |

一个 bitset 记录每条子轨道的状态，解压时先查 bitset 再决定读哪路数据。

---

## 四、压缩流程逐步拆解

```
compress_track_list(allocator, track_list, settings)
         │
         ▼
 ① 参数校验 + 初始化 clip_context
         │
         ▼
 ② 预处理 pre_process_track_list()
    └─ 循环优化：首尾相同则删最后一帧，启用 wrap 策略
    └─ 旋转格式统一（四元数归一化）
         │
         ▼
 ③ 常量折叠 compact_constant_streams()        ★ 最重要的内存优化
    └─ 对每根骨骼检测 rotation/translation/scale 是否全帧相同
    └─ 是常量 → 折叠为 1 帧，标记 is_xxx_constant = true
         │
         ▼
 ④ 归一化 normalize_streams()
    └─ 计算每个 segment 内每根骨骼的 min/extent
    └─ 所有值映射到 [0, 1]（提高量化精度）
         │
         ▼
 ⑤ 量化搜索 quantize_streams()               ★ 最耗时的阶段
    └─ 对每条动画子轨道，枚举 bit-rate（1~22 bit）
    └─ 对每个候选，重建数据并用误差度量计算误差
    └─ 选出"误差 ≤ 阈值"的最小 bit-rate
         │
         ▼
 ⑥ 关键帧裁剪（可选，keyframe_stripping）
         │
         ▼
 ⑦ 序列化 write_compressed_clip()
    └─ 分配一块连续内存
    └─ 写入 header / bitset / 常量数据 / range / bit-packed 帧数据
         │
         ▼
  返回 compressed_tracks*
```

### 量化详解

```
原始值：v = 0.7351（float32，32 bit）
本段 min = -0.5，extent = 2.0

① 归一化：  normalized = (0.7351 - (-0.5)) / 2.0 = 0.6176
② 量化：    8 bit → quantized = round(0.6176 × 255) = 157
③ 存储：    写入 8 bit 整数 157

解压时逆推：
    normalized = 157 / 255.0 = 0.6157
    restored   = 0.6157 × 2.0 + (-0.5) = 0.7314
    误差       = |0.7351 - 0.7314| = 0.0037  ✓
```

variable bit-rate 就是：枚举 1, 2, 3, …, 22 bit，取误差刚好低于阈值的最小值。

### 误差度量的精妙之处

ACL 的"误差"不是数值差，而是**骨骼末端在世界空间的位置偏移**（单位 cm）：

```
world_error = |root × spine × arm × forearm × hand × finger × shell_distance|
              （原始值的世界位置） vs （压缩值的世界位置）
```

这意味着越靠近根骨骼的旋转误差，传播到末端后被放大越多，会被分配更多 bit 来保证精度。这比简单的数值误差智能得多。

---

## 五、解压流程

### 典型用法

```cpp
// 初始化一次
acl::decompression_context<acl::default_transform_decompression_settings> context;
context.initialize(*compressed_tracks_ptr);

// 每帧调用
context.seek(time_seconds, acl::sample_rounding_policy::nearest);
context.decompress_tracks(pose_writer);  // 输出到你的骨骼数组
```

### seek 做了什么

```
seek(t = 0.5s)：
    ① 计算帧索引：frame = floor(0.5 × 60) = 30
    ② 找到 frame 30 所在的 segment
    ③ 加载该 segment 的 range 数据（min/extent）到缓存
    ④ 计算插值权重 alpha（用于 frame 30 和 31 之间的线性插值）
```

### decompress_tracks 做了什么

```
for each bone:
    查 bitset → 子轨道类型？
    
    default  → pose[bone] = default_value（直接赋值，无内存读取）
    constant → pose[bone] = constant_data[bone]（读 1 个样本）
    animated → sample_A = unpack(frame)      ← 解量化
               sample_B = unpack(frame+1)
               pose[bone] = lerp(sample_A, sample_B, alpha)
               normalize(pose[bone].rotation) ← 四元数归一化
```

### 零开销模板技巧

```cpp
// 告诉编译器：我的项目只用变量旋转格式 + 不需要标量轨道
struct my_decompression_settings : public acl::decompression_settings
{
    static constexpr bool is_track_type_supported(acl::track_type8 type) {
        return type == acl::track_type8::qvvf;  // 编译器删掉 scalar 解压代码
    }
};

// 使用自定义 settings
acl::decompression_context<my_decompression_settings> context;
```

`static constexpr` 告诉编译器"这是编译期常量"，编译器会在生成机器码时直接删掉 `if (false)` 的分支，减少指令缓存占用。

---

## 六、关键文件速查

| 文件 | 你会在什么时候改它 |
|------|------------------|
| `compression/compression_settings.h` | 增加新的压缩参数 |
| `compression/impl/compact.transform.h` | 修改常量折叠逻辑 |
| `compression/impl/quantize.transform.h` | 修改量化/bit-rate 搜索 |
| `compression/transform_error_metrics.h` | 自定义误差计算 |
| `decompression/decompression_settings.h` | 裁剪运行时功能 |
| `core/iallocator.h` | 接入引擎内存管理 |
| `core/track_writer.h` | 自定义解压输出格式 |

---

## 七、引擎接入步骤

### Step 1：实现自己的 allocator

```cpp
class my_allocator : public acl::iallocator {
    void* allocate(size_t size, size_t alignment) override {
        return my_engine::alloc(size, alignment);
    }
    void deallocate(void* ptr, size_t size) override {
        my_engine::free(ptr);
    }
};
```

### Step 2：准备 track_array_qvvf

将引擎的动画数据（骨骼变换序列）填入 `track_array_qvvf`，设置好每根骨骼的 `precision`、`shell_distance`、`parent_index`。

### Step 3：压缩（离线/工具端）

```cpp
my_allocator allocator;
acl::compression_settings settings = acl::get_default_compression_settings();
acl::itransform_error_metric* error_metric = new acl::TransformErrorMetric();
settings.error_metric = error_metric;

acl::compressed_tracks* compressed = nullptr;
acl::output_stats stats;
acl::compress_track_list(allocator, track_list, settings, compressed, stats);

// 写入文件，发布资产
fwrite(compressed, 1, compressed->get_size(), file);
```

### Step 4：解压（运行时）

```cpp
// 从文件加载到内存
acl::compressed_tracks* data = (acl::compressed_tracks*)load_file("anim.acl");

// 创建 context（可复用，每个动画实例一个）
acl::decompression_context<acl::default_transform_decompression_settings> ctx;
ctx.initialize(*data);

// 每帧采样
ctx.seek(current_time, acl::sample_rounding_policy::nearest);
ctx.decompress_tracks(my_pose_writer);
```

---

## 八、常见踩坑

| 坑 | 解法 |
|----|------|
| `settings.error_metric` 忘了赋值 → 压缩 crash | `settings.error_metric = &your_metric` |
| 文件大，压缩比低 | 检查是否用了 `full` 而非 `variable` 格式 |
| 压缩时间很长 | level 调低：`compression_level8::medium` 或 `low` |
| 解压 crash | 检查 `compressed_tracks` 生命周期是否 ≥ context |
| 改了头文件没效果 | `cmake --build --clean-first` 全量重编 |
| seek 时间越界 | `sample_rounding_policy::nearest` 会自动 clamp，无需手动处理 |

---

## 参考资料

- [ACL GitHub](https://github.com/nfrechette/acl)
- [作者博客：Animation Compression 系列](https://nfrechette.github.io/2016/10/21/anim_compression_toc/)
- [Unreal Engine ACL 插件](https://github.com/nfrechette/acl-ue4-plugin)
