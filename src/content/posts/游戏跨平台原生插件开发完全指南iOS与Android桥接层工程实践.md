---
title: 游戏跨平台原生插件开发完全指南——iOS与Android桥接层工程实践
published: 2026-05-10
description: 深度讲解Unity游戏跨平台原生插件开发：P/Invoke底层原理、iOS Objective-C/Swift桥接、Android JNI与Kotlin FFI、移动端硬件能力调用（陀螺仪/人脸ID/触觉引擎）、自动化插件打包Pipeline，以及避坑指南。
tags: [原生插件, iOS, Android, JNI, P/Invoke, 跨平台, 插件开发]
category: 跨平台开发
draft: false
---

# 游戏跨平台原生插件开发完全指南——iOS与Android桥接层工程实践

## 前言

Unity 通过 C# 提供了强大的跨平台能力，但总有一些场景需要直接调用平台原生 API：

- **硬件功能**：Face ID 生物认证、Taptic Engine 精准触觉反馈、ARCore/ARKit 扩展功能
- **平台 SDK**：广告归因（AppsFlyer）、崩溃上报（Firebase Crashlytics）等不提供 Unity 版本的 SDK
- **性能敏感计算**：使用 NEON/SSE SIMD 指令集的底层算法，超出 Burst 编译器能覆盖的范围
- **OS 级安全能力**：iOS Secure Enclave、Android Keystore 硬件加密

本文将系统讲解从零开始构建一套生产级跨平台原生插件的完整方法论。

---

## 一、原生插件架构总览

### 1.1 Unity 原生插件调用链

```
C# 游戏逻辑
     ↓ [extern 声明]
P/Invoke（Platform Invocation Services）
     ↓ [dlopen / LoadLibrary]
     ├─── iOS：.a 静态库（Xcode 链接进 App Binary）
     └─── Android：.so 动态库（dlopen 运行时加载）
          ↓
     平台原生代码（C / C++ / Obj-C / Swift / Java / Kotlin）
          ↓
     系统 Framework / SDK
```

### 1.2 插件项目目录结构（推荐）

```
UnityProject/
├── Assets/
│   └── Plugins/
│       ├── NativeCore/           ← C# 封装层（对游戏侧暴露接口）
│       │   ├── IHapticFeedback.cs
│       │   ├── IBiometricAuth.cs
│       │   └── INativePlugin.cs
│       ├── iOS/
│       │   ├── libNativePlugin.a  ← 编译好的 iOS 静态库
│       │   ├── NativePlugin.mm    ← 也可直接放 .mm/.m 源码
│       │   └── NativePlugin.h
│       └── Android/
│           ├── libs/
│           │   ├── armeabi-v7a/libNativePlugin.so
│           │   └── arm64-v8a/libNativePlugin.so
│           └── NativePlugin.aar  ← Java/Kotlin 部分打包为 AAR
├── NativePluginProject/          ← 原生代码工程（Xcode / CMake）
│   ├── iOS/
│   │   ├── NativePlugin.mm
│   │   └── CMakeLists.txt
│   └── Android/
│       ├── src/
│       │   └── main/
│       │       ├── cpp/NativePlugin.cpp
│       │       └── java/com/yourcompany/NativePlugin.kt
│       └── CMakeLists.txt
└── build_plugins.sh              ← 自动化构建脚本
```

---

## 二、P/Invoke 深度解析

### 2.1 基础调用约定

```csharp
using System.Runtime.InteropServices;

/// <summary>
/// 原生插件 C# 桥接层基类
/// 负责 P/Invoke 声明与平台分发
/// </summary>
public static class NativePluginBridge
{
    // iOS 静态库链接进主 Binary，库名固定为 "__Internal"
    // Android 动态库名即 .so 文件名（去掉 lib 前缀和 .so 后缀）
    private const string IOS_LIB = "__Internal";
    private const string ANDROID_LIB = "NativePlugin";

#if UNITY_IOS && !UNITY_EDITOR
    [DllImport(IOS_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern int NativeInit(string configJson, int configLen);

    [DllImport(IOS_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern void NativeRelease();

    [DllImport(IOS_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern int NativeGetDeviceId(byte[] outBuffer, int bufferSize);

    [DllImport(IOS_LIB, CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Ansi)]
    private static extern bool NativeBiometricAuth(
        string reason, 
        NativeCallback onSuccess, 
        NativeCallback onFailed);

#elif UNITY_ANDROID && !UNITY_EDITOR
    [DllImport(ANDROID_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern int NativeInit(string configJson, int configLen);

    [DllImport(ANDROID_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern void NativeRelease();

    [DllImport(ANDROID_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern int NativeGetDeviceId(byte[] outBuffer, int bufferSize);

    [DllImport(ANDROID_LIB, CallingConvention = CallingConvention.Cdecl)]
    private static extern bool NativeBiometricAuth(
        string reason, 
        NativeCallback onSuccess, 
        NativeCallback onFailed);
#endif

    // 在编辑器中的 Mock 实现
    private static int EditorNativeInit(string config, int len) => 0;
    private static void EditorNativeRelease() { }
    private static int EditorNativeGetDeviceId(byte[] buf, int size) 
    {
        var id = System.Text.Encoding.UTF8.GetBytes("EDITOR_DEVICE_ID_12345");
        Array.Copy(id, buf, Math.Min(id.Length, size));
        return id.Length;
    }

    // 平台统一入口（自动分发）
    public static int Init(string configJson)
    {
#if (UNITY_IOS || UNITY_ANDROID) && !UNITY_EDITOR
        return NativeInit(configJson, configJson.Length);
#else
        return EditorNativeInit(configJson, configJson.Length);
#endif
    }

    public static string GetDeviceId()
    {
        byte[] buffer = new byte[256];
        int len;
#if (UNITY_IOS || UNITY_ANDROID) && !UNITY_EDITOR
        len = NativeGetDeviceId(buffer, buffer.Length);
#else
        len = EditorNativeGetDeviceId(buffer, buffer.Length);
#endif
        return len > 0 ? System.Text.Encoding.UTF8.GetString(buffer, 0, len) : string.Empty;
    }
}
```

### 2.2 结构体封送（Marshaling）精要

P/Invoke 中最容易出错的是结构体布局。C# 和 C 的默认对齐规则不同：

```csharp
/// <summary>
/// 与 C 端结构体精确对应的 C# 结构体
/// 必须使用 StructLayout 明确指定布局
/// </summary>

// C 端定义（native/haptic.h）：
// typedef struct {
//     float intensity;      // 4 bytes
//     float sharpness;      // 4 bytes  
//     double duration_ms;   // 8 bytes
//     int32_t pattern_id;   // 4 bytes
//     uint8_t reserved[4];  // 4 bytes 对齐填充
// } HapticConfig;           // 总计 24 bytes

// C# 对应：
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct HapticConfig
{
    public float Intensity;     // offset 0
    public float Sharpness;     // offset 4
    public double DurationMs;   // offset 8（double 8字节对齐）
    public int PatternId;       // offset 16
    [MarshalAs(UnmanagedType.ByValArray, SizeConst = 4)]
    public byte[] Reserved;     // offset 20
}

// ❌ 常见错误：字符串类型
[StructLayout(LayoutKind.Sequential)]
public struct WrongStruct
{
    public string Name;  // C# string 是引用类型，无法直接 marshal 为 char*
}

// ✅ 正确方式：使用固定长度字节数组 + 手动转换
[StructLayout(LayoutKind.Sequential)]
public struct CorrectStruct
{
    [MarshalAs(UnmanagedType.ByValArray, SizeConst = 64)]
    public byte[] NameBuffer;  // char name[64] 对应
    
    public string GetName() => 
        System.Text.Encoding.UTF8.GetString(NameBuffer)
            .TrimEnd('\0');
    
    public void SetName(string name)
    {
        NameBuffer = new byte[64];
        var bytes = System.Text.Encoding.UTF8.GetBytes(name);
        Array.Copy(bytes, NameBuffer, Math.Min(bytes.Length, 63));
    }
}
```

### 2.3 回调函数（函数指针）传递

```csharp
/// <summary>
/// 原生回调委托定义
/// 关键：必须加 [UnmanagedFunctionPointer] 并指定调用约定
/// 必须保证委托对象不被 GC 回收（用 GCHandle 固定）
/// </summary>
[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
public delegate void NativeCallback(int errorCode, IntPtr dataPtr, int dataLen);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
public delegate void NativeProgressCallback(float progress, IntPtr userContext);

public class NativeCallbackManager
{
    // 防止 GC 回收委托（P/Invoke 后 GC 不知道原生层持有引用）
    private static readonly Dictionary<int, GCHandle> _pinnedCallbacks 
        = new Dictionary<int, GCHandle>();
    private static int _nextCallbackId = 1;

    /// <summary>
    /// 注册并固定一个回调委托，返回 ID 用于后续释放
    /// </summary>
    public static int PinCallback(NativeCallback callback)
    {
        var handle = GCHandle.Alloc(callback);
        int id = _nextCallbackId++;
        _pinnedCallbacks[id] = handle;
        return id;
    }

    /// <summary>
    /// 原生层回调完成后释放固定（防止内存泄漏）
    /// </summary>
    public static void ReleaseCallback(int id)
    {
        if (_pinnedCallbacks.TryGetValue(id, out var handle))
        {
            handle.Free();
            _pinnedCallbacks.Remove(id);
        }
    }
}

// 使用示例
public class BiometricAuthService
{
    private NativeCallback _successCb;
    private NativeCallback _failCb;
    private int _successCbId, _failCbId;
    private TaskCompletionSource<bool> _tcs;

    public async System.Threading.Tasks.Task<bool> AuthenticateAsync(string reason)
    {
        _tcs = new TaskCompletionSource<bool>();

        // 创建委托并固定（防止 GC 回收）
        _successCb = OnSuccess;
        _failCb = OnFailed;
        _successCbId = NativeCallbackManager.PinCallback(_successCb);
        _failCbId = NativeCallbackManager.PinCallback(_failCb);

        NativePluginBridge.BiometricAuth(reason, _successCb, _failCb);
        
        return await _tcs.Task;
    }

    private void OnSuccess(int errorCode, IntPtr dataPtr, int dataLen)
    {
        NativeCallbackManager.ReleaseCallback(_successCbId);
        NativeCallbackManager.ReleaseCallback(_failCbId);
        
        // 注意：原生回调可能不在主线程！
        // 必须 dispatch 到主线程才能操作 Unity 对象
        UnityMainThreadDispatcher.Instance.Enqueue(() => _tcs.SetResult(true));
    }

    private void OnFailed(int errorCode, IntPtr dataPtr, int dataLen)
    {
        NativeCallbackManager.ReleaseCallback(_successCbId);
        NativeCallbackManager.ReleaseCallback(_failCbId);
        UnityMainThreadDispatcher.Instance.Enqueue(() => _tcs.SetResult(false));
    }
}
```

---

## 三、iOS 原生插件开发

### 3.1 Objective-C 插件实现

```objc
// NativePlugin.mm（注意是 .mm 后缀，支持 C++ 混编）
#import <Foundation/Foundation.h>
#import <LocalAuthentication/LocalAuthentication.h>
#import <UIKit/UIKit.h>
#import <CoreHaptics/CoreHaptics.h>

// 统一用 C 调用约定导出（Unity 的 P/Invoke 只认 C 符号）
extern "C" {

// ─── 初始化 ────────────────────────────────────────
int NativeInit(const char* configJson, int configLen) {
    NSString* config = [[NSString alloc] 
        initWithBytes:configJson 
        length:configLen 
        encoding:NSUTF8StringEncoding];
    NSLog(@"[NativePlugin] Init with config: %@", config);
    // 初始化全局状态...
    return 0;
}

void NativeRelease() {
    NSLog(@"[NativePlugin] Released");
}

// ─── 设备 ID ───────────────────────────────────────
int NativeGetDeviceId(uint8_t* outBuffer, int bufferSize) {
    NSUUID* uuid = [[UIDevice currentDevice] identifierForVendor];
    NSString* uuidStr = [uuid UUIDString];
    const char* cStr = [uuidStr UTF8String];
    int len = (int)strlen(cStr);
    int copyLen = MIN(len, bufferSize - 1);
    memcpy(outBuffer, cStr, copyLen);
    outBuffer[copyLen] = '\0';
    return copyLen;
}

// ─── 生物认证 ──────────────────────────────────────
typedef void (*NativeCallbackFn)(int errorCode, const void* data, int dataLen);

bool NativeBiometricAuth(
    const char* reason, 
    NativeCallbackFn onSuccess, 
    NativeCallbackFn onFailed)
{
    LAContext* context = [[LAContext alloc] init];
    NSError* error = nil;
    
    // 检查设备是否支持 Face ID / Touch ID
    if (![context canEvaluatePolicy:LAPolicyDeviceOwnerAuthenticationWithBiometrics 
                              error:&error]) {
        if (onFailed) onFailed((int)error.code, nullptr, 0);
        return false;
    }
    
    NSString* reasonStr = [NSString stringWithUTF8String:reason];
    
    [context evaluatePolicy:LAPolicyDeviceOwnerAuthenticationWithBiometrics
            localizedReason:reasonStr
                      reply:^(BOOL success, NSError* authError) {
        if (success) {
            if (onSuccess) onSuccess(0, nullptr, 0);
        } else {
            int code = authError ? (int)authError.code : -1;
            if (onFailed) onFailed(code, nullptr, 0);
        }
    }];
    
    return true;
}

// ─── Taptic Engine 精准触觉反馈 ────────────────────
static CHHapticEngine* _hapticEngine = nil;

bool NativeHapticInit() {
    if (@available(iOS 13.0, *)) {
        NSError* error = nil;
        _hapticEngine = [[CHHapticEngine alloc] initAndReturnError:&error];
        if (error) {
            NSLog(@"[Haptic] Engine init failed: %@", error);
            return false;
        }
        [_hapticEngine startAndReturnError:&error];
        return error == nil;
    }
    return false;
}

// 播放自定义触觉模式（强度 + 锐度 参数化）
void NativeHapticPlay(float intensity, float sharpness, float durationSec) {
    if (@available(iOS 13.0, *)) {
        if (!_hapticEngine) return;
        
        CHHapticEventParameter* intensityParam = 
            [[CHHapticEventParameter alloc] 
                initWithParameterID:CHHapticEventParameterIDHapticIntensity
                              value:intensity];
        CHHapticEventParameter* sharpnessParam = 
            [[CHHapticEventParameter alloc]
                initWithParameterID:CHHapticEventParameterIDHapticSharpness
                              value:sharpness];
        
        CHHapticEvent* event = [[CHHapticEvent alloc]
            initWithEventType:CHHapticEventTypeHapticContinuous
                   parameters:@[intensityParam, sharpnessParam]
               relativeTime:0
                     duration:durationSec];
        
        NSError* error = nil;
        CHHapticPattern* pattern = 
            [[CHHapticPattern alloc] initWithEvents:@[event] 
                                         parameters:@[]
                                              error:&error];
        if (error) return;
        
        id<CHHapticPatternPlayer> player = 
            [_hapticEngine createPlayerWithPattern:pattern error:&error];
        if (error) return;
        
        [player startAtTime:0 error:&error];
    }
}

} // extern "C"
```

### 3.2 Swift 插件（现代 iOS 开发方式）

Swift 需要通过 Objective-C 桥接才能被 C 调用：

```swift
// NativePluginSwift.swift
import Foundation
import StoreKit
import GameKit

// Swift 代码必须用 @_cdecl 修饰才能以 C 符号导出
@_cdecl("NativeGetAuthToken")
public func nativeGetAuthToken(
    _ playerIdBuffer: UnsafeMutablePointer<CChar>,
    _ bufferSize: Int32
) -> Int32 {
    var result: Int32 = -1
    let semaphore = DispatchSemaphore(value: 0)
    
    GKLocalPlayer.local.fetchItems(forIdentityVerificationSignature: { 
        (publicKeyURL, signature, salt, timestamp, error) in
        defer { semaphore.signal() }
        
        guard error == nil, let sig = signature else { return }
        
        let token = sig.base64EncodedString()
        let bytes = Array(token.utf8)
        let copyLen = min(bytes.count, Int(bufferSize) - 1)
        
        for i in 0..<copyLen {
            (playerIdBuffer + i).pointee = CChar(bitPattern: bytes[i])
        }
        (playerIdBuffer + copyLen).pointee = 0
        result = Int32(copyLen)
    })
    
    semaphore.wait()
    return result
}

@_cdecl("NativeOpenAppStoreReview")
public func nativeOpenAppStoreReview() {
    DispatchQueue.main.async {
        if #available(iOS 14.0, *) {
            if let scene = UIApplication.shared.connectedScenes
                .first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene {
                SKStoreReviewController.requestReview(in: scene)
            }
        } else {
            SKStoreReviewController.requestReview()
        }
    }
}
```

### 3.3 iOS 插件编译配置（Xcode Build Settings）

```bash
#!/bin/bash
# build_ios_plugin.sh：编译 iOS 静态库（支持 Simulator + Device 的 Fat Library）

PROJECT_DIR="NativePluginProject/iOS"
OUTPUT_DIR="Assets/Plugins/iOS"
LIB_NAME="NativePlugin"

# 编译 arm64 (真机)
xcodebuild archive \
    -project "${PROJECT_DIR}/${LIB_NAME}.xcodeproj" \
    -scheme "${LIB_NAME}" \
    -configuration Release \
    -destination "generic/platform=iOS" \
    -archivePath "/tmp/${LIB_NAME}_device.xcarchive" \
    SKIP_INSTALL=NO \
    BUILD_LIBRARY_FOR_DISTRIBUTION=YES

# 编译 x86_64 + arm64 (Simulator)
xcodebuild archive \
    -project "${PROJECT_DIR}/${LIB_NAME}.xcodeproj" \
    -scheme "${LIB_NAME}" \
    -configuration Release \
    -destination "generic/platform=iOS Simulator" \
    -archivePath "/tmp/${LIB_NAME}_sim.xcarchive" \
    SKIP_INSTALL=NO \
    BUILD_LIBRARY_FOR_DISTRIBUTION=YES

# 合并为 XCFramework（推荐，替代旧的 Fat Library lipo 方式）
xcodebuild -create-xcframework \
    -archive "/tmp/${LIB_NAME}_device.xcarchive" \
    -framework "${LIB_NAME}.framework" \
    -archive "/tmp/${LIB_NAME}_sim.xcarchive" \
    -framework "${LIB_NAME}.framework" \
    -output "${OUTPUT_DIR}/${LIB_NAME}.xcframework"

echo "iOS plugin built successfully → ${OUTPUT_DIR}/${LIB_NAME}.xcframework"
```

---

## 四、Android 原生插件开发

### 4.1 JNI 层 C++ 实现

```cpp
// android/src/main/cpp/NativePlugin.cpp
#include <jni.h>
#include <android/log.h>
#include <string>
#include <cstring>
#include <sys/system_properties.h>
#include <android/hardware_buffer.h>

#define TAG "NativePlugin"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

// 全局 JavaVM 引用（用于在非 JNI 线程中获取 JNIEnv）
static JavaVM* g_jvm = nullptr;

// ─── JNI_OnLoad：插件加载时自动调用 ──────────────────
extern "C" JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void* reserved) {
    g_jvm = vm;
    LOGI("NativePlugin loaded");
    return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT void JNI_OnUnload(JavaVM* vm, void* reserved) {
    g_jvm = nullptr;
    LOGI("NativePlugin unloaded");
}

// ─── Unity C# 直接调用的纯 C 导出函数 ─────────────────

extern "C" {

int NativeInit(const char* configJson, int configLen) {
    std::string config(configJson, configLen);
    LOGI("NativeInit: %s", config.c_str());
    return 0;
}

void NativeRelease() {
    LOGI("NativeRelease");
}

int NativeGetDeviceId(uint8_t* outBuffer, int bufferSize) {
    // 读取 Android Build.ID（系统属性）
    char buildId[PROP_VALUE_MAX] = {0};
    __system_property_get("ro.build.id", buildId);
    
    int len = strlen(buildId);
    int copyLen = std::min(len, bufferSize - 1);
    memcpy(outBuffer, buildId, copyLen);
    outBuffer[copyLen] = '\0';
    return copyLen;
}

// ─── Android 振动反馈（通过 JNI 调用 Java VibrationEffect API）──

typedef void (*NativeCallbackFn)(int errorCode, const void* data, int dataLen);

// 获取当前线程的 JNIEnv（支持非 JNI 创建的线程）
static JNIEnv* GetJNIEnv() {
    if (!g_jvm) return nullptr;
    
    JNIEnv* env = nullptr;
    jint result = g_jvm->GetEnv((void**)&env, JNI_VERSION_1_6);
    
    if (result == JNI_EDETACHED) {
        // 当前线程未附加到 JVM，需要手动 Attach
        JavaVMAttachArgs args{JNI_VERSION_1_6, "NativePluginThread", nullptr};
        g_jvm->AttachCurrentThread(&env, &args);
    }
    return env;
}

void NativeHapticVibrate(int milliseconds, int amplitude) {
    JNIEnv* env = GetJNIEnv();
    if (!env) return;
    
    // 获取 Unity 主 Activity
    jclass unityClass = env->FindClass("com/unity3d/player/UnityPlayer");
    jfieldID currentActivityField = env->GetStaticFieldID(
        unityClass, "currentActivity", "Landroid/app/Activity;");
    jobject activity = env->GetStaticObjectField(unityClass, currentActivityField);
    
    // 获取 Vibrator 服务
    jclass activityClass = env->GetObjectClass(activity);
    jmethodID getSystemService = env->GetMethodID(
        activityClass, "getSystemService", "(Ljava/lang/String;)Ljava/lang/Object;");
    
    jstring vibratorServiceName = env->NewStringUTF("vibrator");
    jobject vibrator = env->CallObjectMethod(activity, getSystemService, vibratorServiceName);
    env->DeleteLocalRef(vibratorServiceName);
    
    // Android 8.0+ 使用 VibrationEffect
    jclass vibratorClass = env->GetObjectClass(vibrator);
    
    // Build.VERSION.SDK_INT
    jclass buildVersionClass = env->FindClass("android/os/Build$VERSION");
    jfieldID sdkIntField = env->GetStaticFieldID(buildVersionClass, "SDK_INT", "I");
    jint sdkInt = env->GetStaticIntField(buildVersionClass, sdkIntField);
    
    if (sdkInt >= 26) {  // Android 8.0 Oreo
        jclass vibrationEffectClass = env->FindClass("android/os/VibrationEffect");
        jmethodID createOneShot = env->GetStaticMethodID(
            vibrationEffectClass, "createOneShot", "(JI)Landroid/os/VibrationEffect;");
        
        jobject effect = env->CallStaticObjectMethod(
            vibrationEffectClass, createOneShot, (jlong)milliseconds, (jint)amplitude);
        
        jmethodID vibrateWithEffect = env->GetMethodID(
            vibratorClass, "vibrate", "(Landroid/os/VibrationEffect;)V");
        env->CallVoidMethod(vibrator, vibrateWithEffect, effect);
        env->DeleteLocalRef(effect);
    } else {
        // 旧 API
        jmethodID vibrate = env->GetMethodID(vibratorClass, "vibrate", "(J)V");
        env->CallVoidMethod(vibrator, vibrate, (jlong)milliseconds);
    }
    
    // 清理本地引用
    env->DeleteLocalRef(activity);
    env->DeleteLocalRef(vibrator);
}

} // extern "C"
```

### 4.2 Kotlin 层实现（复杂 Android 功能）

对于需要大量 Android API 的功能（如 BiometricPrompt），用 Kotlin 更高效，通过 JNI 回调 C# 侧：

```kotlin
// android/src/main/java/com/yourcompany/NativePluginKt.kt
package com.yourcompany.nativeplugin

import android.app.Activity
import android.os.Handler
import android.os.Looper
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.unity3d.player.UnityPlayer

/**
 * Android 生物认证服务
 * 通过 JNI 被 C++ 层调用，结果通过 UnityPlayer.UnitySendMessage 回调到 Unity
 */
object BiometricAuthService {

    /**
     * 被 JNI 层调用的入口
     * @param reason 显示给用户的认证原因
     * @param callbackObjectName Unity 场景中接收回调的 GameObject 名称
     */
    @JvmStatic
    fun authenticate(reason: String, callbackObjectName: String) {
        val activity = UnityPlayer.currentActivity as? FragmentActivity ?: run {
            sendResult(callbackObjectName, false, -1, "Activity is not FragmentActivity")
            return
        }

        // BiometricPrompt 必须在主线程操作
        Handler(Looper.getMainLooper()).post {
            val biometricManager = BiometricManager.from(activity)
            val canAuth = biometricManager.canAuthenticate(
                BiometricManager.Authenticators.BIOMETRIC_STRONG
            )

            if (canAuth != BiometricManager.BIOMETRIC_SUCCESS) {
                sendResult(callbackObjectName, false, canAuth, "Biometric not available")
                return@post
            }

            val executor = ContextCompat.getMainExecutor(activity)
            val prompt = BiometricPrompt(activity, executor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(
                        result: BiometricPrompt.AuthenticationResult
                    ) {
                        sendResult(callbackObjectName, true, 0, "success")
                    }

                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                        sendResult(callbackObjectName, false, errorCode, errString.toString())
                    }

                    override fun onAuthenticationFailed() {
                        // 认证失败但还可以重试，不终止流程
                    }
                })

            val promptInfo = BiometricPrompt.PromptInfo.Builder()
                .setTitle("身份验证")
                .setSubtitle(reason)
                .setNegativeButtonText("取消")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .build()

            prompt.authenticate(promptInfo)
        }
    }

    private fun sendResult(
        objectName: String, 
        success: Boolean, 
        code: Int, 
        message: String
    ) {
        val data = """{"success":$success,"code":$code,"message":"$message"}"""
        UnityPlayer.UnitySendMessage(objectName, "OnBiometricResult", data)
    }
}
```

对应的 C++ JNI 桥接（让 C# 可以间接调用 Kotlin）：

```cpp
// 在 NativePlugin.cpp 中添加
extern "C" {

bool NativeBiometricAuth(
    const char* reason, 
    NativeCallbackFn onSuccess, 
    NativeCallbackFn onFailed)
{
    JNIEnv* env = GetJNIEnv();
    if (!env) {
        if (onFailed) onFailed(-1, nullptr, 0);
        return false;
    }
    
    // 查找 Kotlin 对象（Kotlin object 编译为带 INSTANCE 字段的 Java 类）
    jclass serviceClass = env->FindClass(
        "com/yourcompany/nativeplugin/BiometricAuthService");
    if (!serviceClass) {
        LOGE("BiometricAuthService class not found");
        if (onFailed) onFailed(-2, nullptr, 0);
        return false;
    }
    
    jmethodID method = env->GetStaticMethodID(
        serviceClass, 
        "authenticate", 
        "(Ljava/lang/String;Ljava/lang/String;)V"
    );
    
    jstring jReason = env->NewStringUTF(reason);
    // 固定回调对象名，结果通过 UnitySendMessage 返回
    jstring jCallbackObj = env->NewStringUTF("BiometricCallbackHandler");
    
    env->CallStaticVoidMethod(serviceClass, method, jReason, jCallbackObj);
    
    env->DeleteLocalRef(jReason);
    env->DeleteLocalRef(jCallbackObj);
    env->DeleteLocalRef(serviceClass);
    
    return true;
}

} // extern "C"
```

### 4.3 Android CMakeLists.txt

```cmake
# android/src/main/cpp/CMakeLists.txt
cmake_minimum_required(VERSION 3.22.1)
project("NativePlugin")

# 编译选项：针对游戏性能优化
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} \
    -O3 \
    -ffast-math \
    -march=armv8-a \
    -mfpu=neon \
    -fvisibility=hidden")

add_library(
    NativePlugin
    SHARED
    NativePlugin.cpp
    # 添加更多 .cpp 文件
)

# 链接 Android 系统库
target_link_libraries(
    NativePlugin
    android           # Android 系统 API（AAssetManager 等）
    log               # __android_log_print
    jnigraphics       # ANativeWindow
)
```

---

## 五、Unity Editor 侧的 Mock 框架

为了在编辑器中也能正常运行（不依赖真实设备），需要完整的 Mock 实现：

```csharp
/// <summary>
/// 原生功能 Mock 框架：在编辑器中模拟真实设备行为
/// </summary>
public interface INativeHapticService
{
    void Play(float intensity, float sharpness, float durationSec);
    Task<bool> AuthenticateAsync(string reason);
}

// ── 真实实现（移动端）──────────────────────────────────

[RuntimePlatform(RuntimePlatform.IPhonePlayer)]
public class iOSHapticService : INativeHapticService
{
    public void Play(float intensity, float sharpness, float durationSec)
        => NativePluginBridge.HapticPlay(intensity, sharpness, durationSec);
    
    public Task<bool> AuthenticateAsync(string reason)
        => new BiometricAuthService().AuthenticateAsync(reason);
}

[RuntimePlatform(RuntimePlatform.Android)]
public class AndroidHapticService : INativeHapticService
{
    public void Play(float intensity, float sharpness, float durationSec)
    {
        int amplitude = (int)(intensity * 255);
        int ms = (int)(durationSec * 1000);
        NativePluginBridge.HapticVibrate(ms, amplitude);
    }
    
    public Task<bool> AuthenticateAsync(string reason)
        => new BiometricAuthService().AuthenticateAsync(reason);
}

// ── Mock 实现（编辑器/不支持的平台）──────────────────────

public class MockHapticService : INativeHapticService
{
    public void Play(float intensity, float sharpness, float durationSec)
        => UnityEngine.Debug.Log($"[Mock Haptic] intensity={intensity:F2} sharp={sharpness:F2} dur={durationSec:F3}s");
    
    public Task<bool> AuthenticateAsync(string reason)
    {
        UnityEngine.Debug.Log($"[Mock Biometric] Simulating successful auth for: {reason}");
        return Task.FromResult(true);
    }
}

// ── 服务定位器（自动选择正确实现）──────────────────────

public static class NativeServiceLocator
{
    private static INativeHapticService _hapticService;

    public static INativeHapticService Haptic
    {
        get
        {
            if (_hapticService != null) return _hapticService;
            
            #if UNITY_EDITOR
            _hapticService = new MockHapticService();
            #elif UNITY_IOS
            _hapticService = new iOSHapticService();
            #elif UNITY_ANDROID
            _hapticService = new AndroidHapticService();
            #else
            _hapticService = new MockHapticService();
            #endif
            
            return _hapticService;
        }
    }

    // 允许测试时注入 Mock
    public static void OverrideForTesting(INativeHapticService mock)
        => _hapticService = mock;
}
```

---

## 六、自动化构建 Pipeline

```bash
#!/bin/bash
# build_all_plugins.sh：一键构建所有平台插件

set -e  # 出错立即退出
UNITY_PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
NATIVE_PROJECT="${UNITY_PROJECT_ROOT}/NativePluginProject"

echo "=== Building Native Plugins ==="

# ── iOS ────────────────────────────────────────────────
echo "Building iOS plugin..."
cd "${NATIVE_PROJECT}/iOS"

# 真机
xcodebuild \
    -project NativePlugin.xcodeproj \
    -scheme NativePlugin \
    -configuration Release \
    -sdk iphoneos \
    CONFIGURATION_BUILD_DIR="${NATIVE_PROJECT}/iOS/build/device" \
    build

# 模拟器
xcodebuild \
    -project NativePlugin.xcodeproj \
    -scheme NativePlugin \
    -configuration Release \
    -sdk iphonesimulator \
    CONFIGURATION_BUILD_DIR="${NATIVE_PROJECT}/iOS/build/simulator" \
    build

# 合并 Fat Library（同时支持 simulator 和 device）
lipo -create \
    "${NATIVE_PROJECT}/iOS/build/device/libNativePlugin.a" \
    "${NATIVE_PROJECT}/iOS/build/simulator/libNativePlugin.a" \
    -output "${UNITY_PROJECT_ROOT}/Assets/Plugins/iOS/libNativePlugin.a"

echo "iOS plugin: OK"

# ── Android ─────────────────────────────────────────────
echo "Building Android plugin..."
cd "${NATIVE_PROJECT}/Android"

# 通过 Gradle 编译 AAR（包含 Kotlin + native .so）
./gradlew :plugin:assembleRelease

# 复制产物到 Unity
cp "plugin/build/outputs/aar/plugin-release.aar" \
   "${UNITY_PROJECT_ROOT}/Assets/Plugins/Android/NativePlugin.aar"

echo "Android plugin: OK"
echo "=== All plugins built successfully ==="
```

---

## 七、常见问题与避坑指南

### 7.1 P/Invoke 崩溃排查清单

| 现象 | 根本原因 | 解决方案 |
|------|---------|---------|
| `EntryPointNotFoundException` | 函数名未正确导出或名称修饰 | 检查 `extern "C"` 声明，用 `nm -D libXXX.so` 验证符号 |
| `DllNotFoundException` | 库未找到或 ABI 不匹配 | 检查 .so 放置路径与 ABI 目录 (`arm64-v8a/`) |
| 随机崩溃 | 委托被 GC 回收 | 用 `GCHandle.Alloc` 固定委托直到回调完成 |
| 结构体数据错乱 | 内存布局不匹配 | 严格对齐 `StructLayout(Pack=N)` 与 C 端 `#pragma pack` |
| 线程崩溃 | 在非主线程操作 Unity 对象 | 使用 `UnityMainThreadDispatcher` 回主线程 |
| 内存泄漏 | JNI 本地引用未释放 | 每个 `FindClass`/`NewStringUTF` 后调用 `DeleteLocalRef` |

### 7.2 性能优化要点

```csharp
// ❌ 低效：频繁的字符串 Marshal（每次调用都分配非托管内存）
for (int i = 0; i < 1000; i++)
    NativeCall("same_string");

// ✅ 高效：缓存固定字符串的指针
private static readonly IntPtr _cachedStringPtr;
static MyPlugin() 
{
    _cachedStringPtr = Marshal.StringToHGlobalAnsi("same_string");
}

// ✅ 或者使用 fixed + stackalloc（避免堆分配）
unsafe void FastCall(string msg) 
{
    byte* ptr = stackalloc byte[msg.Length + 1];
    int len = System.Text.Encoding.UTF8.GetBytes(msg, new Span<byte>(ptr, msg.Length));
    ptr[len] = 0;
    NativeFastCall(ptr, len);
}
```

### 7.3 IL2CPP 特殊注意事项

IL2CPP 会对未使用的类型进行裁剪（Strip），可能导致某些 P/Invoke 相关类型被错误裁剪：

```xml
<!-- Assets/link.xml：防止 IL2CPP 裁剪关键类型 -->
<linker>
  <assembly fullname="System" preserve="all">
    <type fullname="System.Runtime.InteropServices.GCHandle" preserve="all"/>
    <type fullname="System.Runtime.InteropServices.Marshal" preserve="all"/>
  </assembly>
  <assembly fullname="Assembly-CSharp">
    <type fullname="NativePluginBridge" preserve="all"/>
    <type fullname="NativeCallbackManager" preserve="all"/>
  </assembly>
</linker>
```

---

## 八、最佳实践总结

1. **始终用 `extern "C"` 导出**：避免 C++ name mangling 导致 P/Invoke 找不到符号
2. **回调委托必须固定（GCHandle.Alloc）**：直到原生层确认不再调用才释放
3. **非 JNI 线程调用 Java 必须先 AttachCurrentThread**：否则 `GetEnv` 返回 `JNI_EDETACHED`
4. **结构体布局必须显式指定**：绝不依赖 C# 或 C 的默认对齐
5. **编辑器必须有完整 Mock**：保证无设备也能开发和测试
6. **使用 IL2CPP link.xml 防止裁剪**：避免发布包中 P/Invoke 类型被错误移除
7. **本地 JNI 引用及时 DeleteLocalRef**：JNI 本地引用有 512 个的上限，超出会崩溃
8. **构建 Pipeline 自动化**：用脚本统一管理 iOS/Android 双平台编译，避免手工操作引入不一致
