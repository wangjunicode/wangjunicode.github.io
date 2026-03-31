---
title: Unity CI/CD构建流水线：自动化打包与多渠道发布
published: 2026-03-31
description: 全面解析Unity项目CI/CD流水线的工程实现，包含Jenkins/GitHub Actions构建脚本、Unity命令行构建参数（无头构建）、Android多渠道包生成（不同应用商店）、iOS自动化签名（Fastlane集成）、版本号自动递增、构建产物上传（蒲公英/内部平台）、崩溃符号表上传，以及构建通知（企业微信/邮件）。
tags: [Unity, CI/CD, 自动化构建, DevOps, 游戏开发]
category: 工程实践
draft: false
---

## 一、Unity命令行构建

```bash
#!/bin/bash
# unity_build.sh - Unity 无头构建脚本

UNITY_PATH="/Applications/Unity/Hub/Editor/2022.3.0f1/Unity.app/Contents/MacOS/Unity"
PROJECT_PATH="/path/to/your/project"
BUILD_OUTPUT="/path/to/builds"
LOG_FILE="/path/to/build.log"

# Android 构建
$UNITY_PATH \
  -batchmode \
  -nographics \
  -quit \
  -projectPath "$PROJECT_PATH" \
  -buildTarget Android \
  -executeMethod BuildScript.BuildAndroid \
  -customBuildPath "$BUILD_OUTPUT/android/game.apk" \
  -logFile "$LOG_FILE" \
  -BuildVersion "1.0.${BUILD_NUMBER}" \
  -Channel "GooglePlay"

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "Unity build failed with exit code $EXIT_CODE"
  cat "$LOG_FILE"
  exit $EXIT_CODE
fi

echo "Build completed successfully"
```

---

## 二、Unity构建脚本

```csharp
using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

/// <summary>
/// CI/CD 构建入口脚本
/// </summary>
public static class BuildScript
{
    public static void BuildAndroid()
    {
        string buildPath = GetArg("-customBuildPath") ?? "Builds/Android/game.apk";
        string version = GetArg("-BuildVersion") ?? Application.version;
        string channel = GetArg("-Channel") ?? "Default";

        // 设置版本号
        PlayerSettings.bundleVersion = version;
        PlayerSettings.Android.bundleVersionCode = GetBuildNumber();

        // 渠道配置
        ConfigureChannel(channel);

        var options = new BuildPlayerOptions
        {
            scenes = GetEnabledScenes(),
            locationPathName = buildPath,
            target = BuildTarget.Android,
            options = BuildOptions.None
        };

        // 确保输出目录存在
        Directory.CreateDirectory(Path.GetDirectoryName(buildPath));

        var report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;

        if (summary.result == BuildResult.Succeeded)
        {
            Debug.Log($"[Build] 构建成功: {buildPath} ({summary.totalSize / 1024 / 1024} MB)");
            EditorApplication.Exit(0);
        }
        else
        {
            Debug.LogError($"[Build] 构建失败: {summary.result}");
            EditorApplication.Exit(1);
        }
    }

    public static void BuildIOS()
    {
        string buildPath = GetArg("-customBuildPath") ?? "Builds/iOS";
        string version = GetArg("-BuildVersion") ?? Application.version;

        PlayerSettings.bundleVersion = version;
        PlayerSettings.iOS.buildNumber = GetBuildNumber().ToString();

        var options = new BuildPlayerOptions
        {
            scenes = GetEnabledScenes(),
            locationPathName = buildPath,
            target = BuildTarget.iOS,
            options = BuildOptions.None
        };

        Directory.CreateDirectory(buildPath);
        
        var report = BuildPipeline.BuildPlayer(options);
        EditorApplication.Exit(report.summary.result == BuildResult.Succeeded ? 0 : 1);
    }

    static void ConfigureChannel(string channel)
    {
        // 根据渠道设置不同配置
        switch (channel)
        {
            case "GooglePlay":
                PlayerSettings.Android.keystoreName = "/path/to/google.keystore";
                PlayerSettings.Android.keyaliasName = "google_alias";
                break;
            case "AppStore":
                PlayerSettings.Android.keystoreName = "/path/to/appstore.keystore";
                break;
        }
        
        // 写入渠道标识（运行时读取）
        File.WriteAllText("Assets/Resources/channel.txt", channel);
    }

    static string[] GetEnabledScenes()
    {
        var scenes = new System.Collections.Generic.List<string>();
        foreach (var scene in EditorBuildSettings.scenes)
            if (scene.enabled) scenes.Add(scene.path);
        return scenes.ToArray();
    }

    static int GetBuildNumber()
    {
        string buildNum = Environment.GetEnvironmentVariable("BUILD_NUMBER") ?? "1";
        return int.TryParse(buildNum, out int n) ? n : 1;
    }

    static string GetArg(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
            if (args[i] == name && i + 1 < args.Length) return args[i + 1];
        return null;
    }
}
```

---

## 三、GitHub Actions 工作流

```yaml
# .github/workflows/unity-build.yml
name: Unity Build

on:
  push:
    branches: [main, release/*]
  pull_request:
    branches: [main]

jobs:
  build-android:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          lfs: true

      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-Android-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}

      - name: Build Android
        uses: game-ci/unity-builder@v2
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
        with:
          targetPlatform: Android
          buildName: game
          buildMethod: BuildScript.BuildAndroid
          versioning: Semantic

      - name: Upload APK
        uses: actions/upload-artifact@v3
        with:
          name: android-build
          path: build/Android/
          retention-days: 7

      - name: Notify Wecom
        if: always()
        run: |
          STATUS="${{ job.status }}"
          curl -s -X POST "${{ secrets.WECOM_WEBHOOK }}" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"Android构建${STATUS}: ${{ github.ref_name }}\"}}"
```

---

## 四、版本管理规范

| 字段 | 说明 | 示例 |
|------|------|------|
| 版本号 | Major.Minor.Patch | 1.2.3 |
| Build Number | CI自增，每次构建+1 | 1234 |
| Git Commit | 短哈希，用于追溯 | abc1234 |
| 渠道标识 | 区分不同商店包 | GooglePlay/AppStore |
| 构建时间 | UTC时间戳 | 20260331_235900 |
