---
title: 游戏CI-CD工程化：自动化构建与发布流水线
published: 2026-03-31
description: 全面解析游戏项目CI/CD工程化的完整方案，包含Unity Cloud Build/Jenkins配置、自动化测试（单元测试/集成测试/UI自动测试）、构建版本号管理（Git Tag驱动）、多环境构建（测试/预发/正式包）、Keystore密钥管理、包体大小监控（大小超出阈值触发告警）、自动发布到测试平台（Appstore Connect/Google Play）。
tags: [Unity, CI-CD, 自动化构建, DevOps, 游戏工程化]
category: 工程实践
draft: false
---

## 一、Unity 自动化构建脚本

```csharp
using System;
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
using UnityEditor.Build.Reporting;

/// <summary>
/// Unity 自动化构建器（供命令行/CI调用）
/// </summary>
public static class AutoBuilder
{
    // 构建目标枚举
    private static BuildTarget GetBuildTarget()
    {
        string platform = GetArg("-platform", "Android");
        return platform switch
        {
            "Android" => BuildTarget.Android,
            "iOS"     => BuildTarget.iOS,
            "Windows" => BuildTarget.StandaloneWindows64,
            "WebGL"   => BuildTarget.WebGL,
            _ => BuildTarget.Android
        };
    }

    [MenuItem("Build/Android Debug")]
    public static void BuildAndroidDebug()
    {
        BuildGame(BuildTarget.Android, BuildOptions.Development | BuildOptions.AllowDebugging);
    }

    [MenuItem("Build/Android Release")]
    public static void BuildAndroidRelease()
    {
        BuildGame(BuildTarget.Android, BuildOptions.None);
    }

    /// <summary>
    /// CI/CD 调用入口（命令行参数驱动）
    /// Unity.exe -batchmode -executeMethod AutoBuilder.BuildFromCLI
    /// </summary>
    public static void BuildFromCLI()
    {
        BuildTarget target = GetBuildTarget();
        string buildNumber = GetArg("-buildNumber", "0");
        string outputPath = GetArg("-outputPath", $"Build/{target}");
        bool isDev = GetArg("-env", "debug") == "debug";
        
        // 设置版本号
        string baseVersion = Application.version;
        PlayerSettings.bundleVersion = $"{baseVersion}.{buildNumber}";
        
        BuildOptions options = isDev 
            ? BuildOptions.Development 
            : BuildOptions.None;
        
        var result = BuildGame(target, options, outputPath);
        
        // 退出码（CI判断是否成功）
        EditorApplication.Exit(result.summary.result == BuildResult.Succeeded ? 0 : 1);
    }

    static BuildReport BuildGame(BuildTarget target, BuildOptions options, 
        string outputPath = null)
    {
        // 应用构建前配置
        ApplyBuildConfig(target);
        
        string[] scenes = GetEnabledScenes();
        string output = outputPath ?? GetDefaultOutputPath(target);
        
        var buildPlayerOptions = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = output,
            target = target,
            options = options,
        };
        
        Debug.Log($"[Build] 开始构建 {target}，输出: {output}");
        
        var report = BuildPipeline.BuildPlayer(buildPlayerOptions);
        
        // 打印构建报告
        PrintBuildReport(report);
        
        return report;
    }

    static void ApplyBuildConfig(BuildTarget target)
    {
        if (target == BuildTarget.Android)
        {
            // Android签名配置（密钥从环境变量读取，不存储在代码库中）
            string keystorePath = Environment.GetEnvironmentVariable("KEYSTORE_PATH");
            string keystorePass = Environment.GetEnvironmentVariable("KEYSTORE_PASS");
            string keyAlias     = Environment.GetEnvironmentVariable("KEY_ALIAS");
            string keyPass      = Environment.GetEnvironmentVariable("KEY_PASS");
            
            if (!string.IsNullOrEmpty(keystorePath))
            {
                PlayerSettings.Android.keystoreName = keystorePath;
                PlayerSettings.Android.keystorePass = keystorePass;
                PlayerSettings.Android.keyaliasName = keyAlias;
                PlayerSettings.Android.keyaliasPass = keyPass;
            }
            
            // 构建AAB（上传Google Play用）
            EditorUserBuildSettings.buildAppBundle = 
                GetArg("-buildType", "apk") == "aab";
        }
    }

    static string[] GetEnabledScenes()
    {
        var scenes = new System.Collections.Generic.List<string>();
        foreach (var scene in EditorBuildSettings.scenes)
        {
            if (scene.enabled)
                scenes.Add(scene.path);
        }
        return scenes.ToArray();
    }

    static string GetDefaultOutputPath(BuildTarget target)
    {
        string ext = target switch
        {
            BuildTarget.Android => EditorUserBuildSettings.buildAppBundle ? ".aab" : ".apk",
            BuildTarget.iOS     => "",
            _                   => ".exe"
        };
        string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmm");
        return $"Builds/{target}/{timestamp}/game{ext}";
    }

    static void PrintBuildReport(BuildReport report)
    {
        var summary = report.summary;
        Debug.Log($"[Build] 结果: {summary.result}");
        Debug.Log($"[Build] 耗时: {summary.totalTime.TotalSeconds:F1}s");
        Debug.Log($"[Build] 包体大小: {summary.totalSize / 1024 / 1024:F1} MB");
        Debug.Log($"[Build] 错误: {summary.totalErrors}, 警告: {summary.totalWarnings}");
        
        // 包体大小告警
        float sizeMB = summary.totalSize / 1024f / 1024f;
        if (sizeMB > 150)
            Debug.LogWarning($"[Build] ⚠️ 包体超过150MB ({sizeMB:F1}MB)，需要检查！");
    }

    static string GetArg(string name, string defaultValue = "")
    {
        var args = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == name)
                return args[i + 1];
        return defaultValue;
    }
}
#endif
```

---

## 二、Jenkins Pipeline 示例

```groovy
// Jenkinsfile（Declarative Pipeline）
pipeline {
    agent any
    
    parameters {
        choice(name: 'PLATFORM', choices: ['Android', 'iOS'], description: '构建平台')
        choice(name: 'ENV', choices: ['debug', 'release'], description: '构建环境')
        booleanParam(name: 'RUN_TESTS', defaultValue: true, description: '是否运行测试')
    }
    
    environment {
        UNITY_PATH = '/Applications/Unity/Hub/Editor/2022.3.0f1/Unity.app/Contents/MacOS/Unity'
        KEYSTORE_PATH = credentials('android-keystore-path')
        KEYSTORE_PASS = credentials('android-keystore-pass')
        KEY_ALIAS     = credentials('android-key-alias')
        KEY_PASS      = credentials('android-key-pass')
    }
    
    stages {
        stage('Checkout') {
            steps {
                git branch: 'main', url: 'https://github.com/yourorg/yourgame.git'
                echo "当前Commit: ${env.GIT_COMMIT[0..7]}"
            }
        }
        
        stage('Run Tests') {
            when { params.RUN_TESTS }
            steps {
                sh '''
                ${UNITY_PATH} -batchmode -nographics \
                    -projectPath . \
                    -runTests \
                    -testPlatform EditMode \
                    -testResults test-results/editmode.xml \
                    -logFile logs/test.log
                '''
                junit 'test-results/*.xml'
            }
        }
        
        stage('Build') {
            steps {
                sh '''
                ${UNITY_PATH} -batchmode -nographics \
                    -projectPath . \
                    -executeMethod AutoBuilder.BuildFromCLI \
                    -platform ${PLATFORM} \
                    -buildNumber ${BUILD_NUMBER} \
                    -env ${ENV} \
                    -logFile logs/build.log
                '''
            }
        }
        
        stage('Archive') {
            steps {
                archiveArtifacts artifacts: 'Builds/**/*.apk,Builds/**/*.aab,Builds/**/*.ipa'
            }
        }
        
        stage('Notify') {
            steps {
                // 企业微信/钉钉通知
                sh 'curl -X POST https://your-notify-webhook ...'
            }
        }
    }
    
    post {
        failure {
            mail to: 'team@example.com', subject: '构建失败！', body: '请检查Jenkins'
        }
    }
}
```

---

## 三、版本号管理

```csharp
#if UNITY_EDITOR
/// <summary>
/// 版本号自动管理（基于Git Tag）
/// </summary>
public class VersionManager
{
    [MenuItem("Build/更新版本号")]
    static void UpdateVersion()
    {
        // 从Git获取最新Tag作为版本号
        string version = GetGitTag();
        PlayerSettings.bundleVersion = version;
        AssetDatabase.SaveAssets();
        Debug.Log($"[Version] 版本号更新为: {version}");
    }

    static string GetGitTag()
    {
        try
        {
            var proc = new System.Diagnostics.Process
            {
                StartInfo = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "git",
                    Arguments = "describe --tags --abbrev=0",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                }
            };
            proc.Start();
            string tag = proc.StandardOutput.ReadToEnd().Trim();
            proc.WaitForExit();
            return string.IsNullOrEmpty(tag) ? "0.1.0" : tag.TrimStart('v');
        }
        catch
        {
            return "0.1.0";
        }
    }
}
#endif
```

---

## 四、CI/CD 流水线设计要点

| 要点 | 方案 |
|------|------|
| 密钥安全 | 不存入代码库，用CI密钥管理（Credentials）|
| 测试先行 | 构建前运行单元测试，失败则不构建 |
| 版本号 | Git Tag + Build Number，唯一标识每次构建 |
| 包体监控 | 包体大小超阈值自动告警 |
| 构建缓存 | Library目录缓存，加速增量构建 |
| 失败通知 | 自动发送企业微信/邮件通知 |
