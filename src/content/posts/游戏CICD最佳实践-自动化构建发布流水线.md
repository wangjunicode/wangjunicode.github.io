---
title: "游戏CI/CD最佳实践：自动化构建发布流水线"
description: "系统讲解游戏项目CI/CD体系建设，包括自动化构建、多平台打包、自动化测试、热更新发布流水线，以及Jenkins/GitHub Actions的实战配置"
published: 2025-03-21
tags: ["CI/CD", "DevOps", "自动化构建", "Jenkins", "游戏工程效能"]
encryptedKey: henhaoji123
---

# 游戏CI/CD最佳实践：自动化构建发布流水线

> 每次提交都需要手动构建？每次发版都是通宵大战？这是工程效能问题，也是技术负责人的职责范围。建立完善的CI/CD体系，是团队长期高效的基础。

---

## 一、游戏CI/CD的特殊挑战

### 1.1 游戏项目与普通软件的差异

```
普通软件CI/CD的挑战：
- 代码编译和测试（标准流程）
- 镜像构建和部署（通用工具）

游戏项目额外挑战：
1. 超大仓库：游戏资源可能有几十GB（美术资源、音频等）
   → Git LFS或SVN大文件处理

2. 多平台构建：iOS/Android/PC/主机
   → 需要多个不同系统的构建机

3. 引擎特殊性：Unity需要License，构建时间长
   → 离线License管理，并行构建

4. 资源打包：AssetBundle打包耗时
   → 增量打包，缓存优化

5. 包体测试：真机测试、性能回归测试
   → 真机农场，自动化测试平台
```

### 1.2 CI/CD带来的价值

```
投入前：
- 手动构建：30分钟/次 × 10次/天 × 10人 = 500人时/天
- 发版流程：需要专人值守4-8小时
- Bug发现时机：QA测试（延迟几天）

投入后：
- 每次提交自动构建：无需人工干预
- 发版流程：一键发布，15分钟自动完成
- Bug发现时机：代码提交后5分钟（快速反馈）

ROI计算：
CI/CD系统建设时间：2-4周（一次性投入）
节省时间：每天数小时（持续收益）
```

---

## 二、构建流水线设计

### 2.1 完整流水线架构

```
代码提交触发
    │
    ▼
Stage 1: 代码检查（5分钟）
├── 代码风格检查（StyleCop）
├── 静态分析（Roslyn Analyzer）
└── 单元测试（NUnit）

Stage 2: 资源检查（10分钟）
├── 资源规格检查（贴图压缩、文件大小）
├── 依赖关系检查
└── Shader编译验证

Stage 3: 构建（20-40分钟）
├── Android构建（AAB/APK）
├── iOS构建（xcarchive）
└── PC构建（exe/exe64）

Stage 4: 自动化测试（30分钟）
├── 冒烟测试（核心流程）
├── 性能测试（帧率、内存）
└── 兼容性测试（目标机型）

Stage 5: 打包分发（10分钟）
├── 生成热更新补丁
├── 上传到测试分发平台（pgyer/蒲公英）
└── 通知相关人员
```

### 2.2 Unity命令行构建

```csharp
// BuildScript.cs（Editor专用，放在Editor文件夹）
using UnityEditor;
using UnityEditor.Build.Reporting;
using System;

public static class BuildScript
{
    // Android构建
    [MenuItem("Build/Build Android")]
    public static void BuildAndroid()
    {
        // 从命令行参数读取配置
        string version = GetArg("-version") ?? Application.version;
        string bundleId = GetArg("-bundleId") ?? Application.identifier;
        bool isDevelopment = GetArg("-development") == "true";
        
        // 配置PlayerSettings
        PlayerSettings.bundleVersion = version;
        PlayerSettings.applicationIdentifier = bundleId;
        
        // 设置Android特定配置
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        PlayerSettings.Android.useCustomKeystore = true;
        PlayerSettings.Android.keystoreName = GetArg("-keystorePath");
        PlayerSettings.Android.keystorePass = GetArg("-keystorePass");
        PlayerSettings.Android.keyaliasName = GetArg("-keyaliasName");
        PlayerSettings.Android.keyaliasPass = GetArg("-keyaliasPass");
        
        var buildOptions = new BuildPlayerOptions
        {
            scenes = GetScenePaths(),
            locationPathName = $"Build/Android/{Application.productName}.aab",
            target = BuildTarget.Android,
            subtarget = (int)AndroidBuildSubtarget.Generic,
            options = isDevelopment 
                ? BuildOptions.Development | BuildOptions.AllowDebugging 
                : BuildOptions.None
        };
        
        // 执行构建
        var report = BuildPipeline.BuildPlayer(buildOptions);
        
        // 检查构建结果
        if (report.summary.result == BuildResult.Succeeded)
        {
            Console.WriteLine($"✅ Android构建成功: {report.summary.totalSize / 1024 / 1024}MB");
            Environment.Exit(0);
        }
        else
        {
            Console.WriteLine($"❌ Android构建失败: {report.summary.totalErrors}个错误");
            foreach (var step in report.steps)
            {
                foreach (var message in step.messages)
                {
                    if (message.type == LogType.Error)
                        Console.WriteLine($"  Error: {message.content}");
                }
            }
            Environment.Exit(1);
        }
    }
    
    // iOS构建
    public static void BuildIOS()
    {
        var buildOptions = new BuildPlayerOptions
        {
            scenes = GetScenePaths(),
            locationPathName = "Build/iOS",
            target = BuildTarget.iOS,
            options = BuildOptions.None
        };
        
        var report = BuildPipeline.BuildPlayer(buildOptions);
        
        if (report.summary.result != BuildResult.Succeeded)
            Environment.Exit(1);
        
        // iOS需要Xcode继续编译，这里生成的是Xcode工程
        Console.WriteLine("✅ iOS Xcode工程生成成功，继续使用xcodebuild编译...");
        Environment.Exit(0);
    }
    
    // AssetBundle打包
    public static void BuildAssetBundles()
    {
        string platform = GetArg("-platform") ?? "Android";
        BuildTarget target = platform == "iOS" ? BuildTarget.iOS : BuildTarget.Android;
        
        string outputPath = $"Bundles/{platform}";
        System.IO.Directory.CreateDirectory(outputPath);
        
        var manifest = BuildPipeline.BuildAssetBundles(
            outputPath,
            BuildAssetBundleOptions.ChunkBasedCompression,
            target
        );
        
        if (manifest == null)
        {
            Console.WriteLine("❌ AssetBundle打包失败");
            Environment.Exit(1);
        }
        
        Console.WriteLine($"✅ AssetBundle打包成功: {manifest.GetAllAssetBundles().Length}个Bundle");
        Environment.Exit(0);
    }
    
    private static string[] GetScenePaths()
    {
        return EditorBuildSettings.scenes
            .Where(s => s.enabled)
            .Select(s => s.path)
            .ToArray();
    }
    
    private static string GetArg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == name && i + 1 < args.Length)
                return args[i + 1];
        }
        return null;
    }
}
```

---

## 三、Jenkins流水线配置

### 3.1 Jenkinsfile（声明式流水线）

```groovy
// Jenkinsfile（放在项目根目录）
pipeline {
    agent none // 不指定全局agent，各Stage单独指定
    
    environment {
        UNITY_PATH = '/Applications/Unity/Hub/Editor/2022.3.10f1/Unity.app/Contents/MacOS/Unity'
        UNITY_PROJECT = "${WORKSPACE}"
        BUILD_NUMBER_STR = "${env.BUILD_NUMBER}"
    }
    
    stages {
        // Stage 1: 代码检查
        stage('Code Check') {
            agent { label 'mac-build-01' }
            steps {
                checkout scm
                sh """
                    # 运行Unity测试（代码质量检查）
                    "${UNITY_PATH}" \
                        -batchmode \
                        -nographics \
                        -projectPath "${UNITY_PROJECT}" \
                        -runTests \
                        -testPlatform EditMode \
                        -testResults test-results.xml \
                        -logFile unity-test.log
                """
                junit 'test-results.xml' // 发布测试报告
            }
            post {
                always {
                    archiveArtifacts artifacts: 'unity-test.log', allowEmptyArchive: true
                }
            }
        }
        
        // Stage 2: 并行构建（Android + iOS同时进行）
        stage('Build') {
            parallel {
                stage('Build Android') {
                    agent { label 'mac-build-01' }
                    steps {
                        withCredentials([
                            string(credentialsId: 'android-keystore-pass', variable: 'KEYSTORE_PASS'),
                            string(credentialsId: 'android-key-pass', variable: 'KEY_PASS')
                        ]) {
                            sh """
                                "${UNITY_PATH}" \
                                    -batchmode \
                                    -nographics \
                                    -quit \
                                    -projectPath "${UNITY_PROJECT}" \
                                    -executeMethod BuildScript.BuildAndroid \
                                    -version "1.0.${BUILD_NUMBER_STR}" \
                                    -keystorePath "Assets/Plugins/Android/release.keystore" \
                                    -keystorePass "${KEYSTORE_PASS}" \
                                    -keyaliasName "release" \
                                    -keyaliasPass "${KEY_PASS}" \
                                    -logFile unity-android.log
                            """
                        }
                    }
                    post {
                        success {
                            archiveArtifacts artifacts: 'Build/Android/*.aab'
                        }
                        always {
                            archiveArtifacts artifacts: 'unity-android.log', allowEmptyArchive: true
                        }
                    }
                }
                
                stage('Build iOS') {
                    agent { label 'mac-build-01' }
                    steps {
                        sh """
                            # Step 1: Unity生成Xcode工程
                            "${UNITY_PATH}" \
                                -batchmode \
                                -nographics \
                                -quit \
                                -projectPath "${UNITY_PROJECT}" \
                                -executeMethod BuildScript.BuildIOS \
                                -version "1.0.${BUILD_NUMBER_STR}" \
                                -logFile unity-ios.log
                            
                            # Step 2: xcodebuild编译打包
                            xcodebuild \
                                -project "Build/iOS/Unity-iPhone.xcodeproj" \
                                -scheme "Unity-iPhone" \
                                -archivePath "Build/iOS/MyGame.xcarchive" \
                                archive \
                                CODE_SIGN_IDENTITY="iPhone Distribution" \
                                DEVELOPMENT_TEAM="YOUR_TEAM_ID"
                            
                            # Step 3: 导出IPA
                            xcodebuild -exportArchive \
                                -archivePath "Build/iOS/MyGame.xcarchive" \
                                -exportPath "Build/iOS/IPA" \
                                -exportOptionsPlist "ExportOptions.plist"
                        """
                    }
                    post {
                        success {
                            archiveArtifacts artifacts: 'Build/iOS/IPA/*.ipa'
                        }
                    }
                }
            }
        }
        
        // Stage 3: 性能测试
        stage('Performance Test') {
            agent { label 'test-device-android' } // 真机测试设备
            when {
                branch 'main' // 只在主分支执行性能测试
            }
            steps {
                sh """
                    # 安装APK到测试设备
                    adb install -r "Build/Android/*.apk"
                    
                    # 运行性能测试（自动化脚本）
                    python3 run_perf_test.py \
                        --test-case "main_battle" \
                        --duration 60 \
                        --output "perf-report.json"
                """
            }
            post {
                always {
                    // 发布性能报告
                    publishHTML([
                        reportDir: '.',
                        reportFiles: 'perf-report.html',
                        reportName: '性能测试报告'
                    ])
                }
            }
        }
        
        // Stage 4: 发布（只在tag时执行）
        stage('Publish') {
            agent { label 'mac-build-01' }
            when {
                tag 'v*' // 只在v开头的tag时发布
            }
            steps {
                withCredentials([string(credentialsId: 'pgyer-api-key', variable: 'PGYER_KEY')]) {
                    sh """
                        # 上传到蒲公英（内部测试分发）
                        curl -F "file=@Build/Android/MyGame.aab" \
                             -F "_api_key=${PGYER_KEY}" \
                             -F "buildInstallType=1" \
                             https://www.pgyer.com/apiv2/app/upload
                    """
                }
                
                // 钉钉/企业微信通知
                dingtalk(
                    robot: 'game-dev-robot',
                    type: 'TEXT',
                    text: ["✅ 新版本 ${TAG_NAME} 构建完成，已上传测试包，请下载测试！"]
                )
            }
        }
    }
    
    post {
        failure {
            // 构建失败时通知
            dingtalk(
                robot: 'game-dev-robot',
                type: 'TEXT',
                text: ["❌ 构建失败！分支: ${env.BRANCH_NAME}, 构建: #${env.BUILD_NUMBER}"]
            )
        }
    }
}
```

---

## 四、GitHub Actions配置（适合中小团队）

```yaml
# .github/workflows/build.yml
name: Unity Build

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  # 代码质量检查
  test:
    name: Unity Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          lfs: true  # 支持Git LFS
      
      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
          restore-keys: Library-
      
      - name: Run Unity Tests
        uses: game-ci/unity-test-runner@v2
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
        with:
          projectPath: .
          testMode: editmode
          artifactsPath: test-results
      
      - uses: actions/upload-artifact@v3
        with:
          name: Test Results
          path: test-results

  # Android构建
  build-android:
    name: Build Android
    runs-on: ubuntu-latest
    needs: test  # 依赖test job
    steps:
      - uses: actions/checkout@v3
        with:
          lfs: true
      
      - name: Cache Unity Library
        uses: actions/cache@v3
        with:
          path: Library
          key: Library-${{ hashFiles('Assets/**', 'Packages/**', 'ProjectSettings/**') }}
      
      - name: Build Android
        uses: game-ci/unity-builder@v2
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
          UNITY_EMAIL: ${{ secrets.UNITY_EMAIL }}
          UNITY_PASSWORD: ${{ secrets.UNITY_PASSWORD }}
        with:
          targetPlatform: Android
          androidExportType: androidAppBundle
          androidKeystoreName: release.keystore
          androidKeystoreBase64: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
          androidKeystorePass: ${{ secrets.ANDROID_KEYSTORE_PASS }}
          androidKeyaliasName: release
          androidKeyaliasPass: ${{ secrets.ANDROID_KEY_PASS }}
      
      - uses: actions/upload-artifact@v3
        with:
          name: Android Build
          path: build/Android
```

---

## 五、资源自动化检查工具

### 5.1 在提交前自动检查资源规格

```csharp
// 资源规格检查（Editor自动化）
public class AssetAuditSystem
{
    [InitializeOnLoadMethod]
    static void RegisterProcessor()
    {
        // 资源导入时自动检查
        // Unity 2021+ 使用 AssetPostprocessor
    }
    
    // 检查所有Texture规格
    [MenuItem("Tools/Audit/Check All Textures")]
    static void AuditTextures()
    {
        var issues = new List<string>();
        string[] guids = AssetDatabase.FindAssets("t:Texture2D", new[] { "Assets" });
        
        foreach (var guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) continue;
            
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            
            // 规则1：非2的幂次方（影响压缩效率）
            if (!IsPowerOfTwo(tex.width) || !IsPowerOfTwo(tex.height))
                issues.Add($"[非POT] {path} ({tex.width}x{tex.height})");
            
            // 规则2：超大贴图（> 2048 × 2048 且不是背景图）
            if (tex.width > 2048 && tex.height > 2048 && !path.Contains("Background"))
                issues.Add($"[超大贴图] {path} ({tex.width}x{tex.height})");
            
            // 规则3：未开启压缩（移动端）
            var androidSettings = importer.GetPlatformTextureSettings("Android");
            if (!androidSettings.overridden || androidSettings.format == TextureImporterFormat.Automatic)
                issues.Add($"[未配置Android压缩] {path}");
            
            // 规则4：Read/Write Enabled（占用双倍内存）
            if (importer.isReadable)
                issues.Add($"[Read/Write Enabled] {path} (如非必要请关闭)");
        }
        
        if (issues.Count > 0)
        {
            Debug.LogWarning($"发现 {issues.Count} 个资源规格问题：\n" + string.Join("\n", issues));
        }
        else
        {
            Debug.Log("✅ 所有Texture规格检查通过");
        }
        
        // 生成报告文件
        File.WriteAllLines("AssetAuditReport.txt", issues);
        AssetDatabase.Refresh();
    }
    
    static bool IsPowerOfTwo(int n) => n > 0 && (n & (n - 1)) == 0;
}
```

---

## 六、热更新CI/CD流水线

### 6.1 热更新发布自动化

```python
# release_hotupdate.py
# 热更新发布脚本（Python）

import hashlib
import json
import os
import shutil
import subprocess
import boto3  # AWS S3上传

def build_asset_bundles(platform):
    """触发Unity打包AssetBundle"""
    cmd = [
        UNITY_PATH,
        '-batchmode', '-nographics', '-quit',
        '-projectPath', PROJECT_PATH,
        '-executeMethod', 'BuildScript.BuildAssetBundles',
        '-platform', platform,
        '-logFile', f'build_{platform}.log'
    ]
    result = subprocess.run(cmd, timeout=3600)
    if result.returncode != 0:
        raise Exception(f"AssetBundle打包失败，请检查 build_{platform}.log")
    print(f"✅ {platform} AssetBundle打包完成")

def compute_md5(filepath):
    """计算文件MD5"""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def generate_catalog(bundle_dir, version):
    """生成资源目录（包含每个Bundle的MD5和大小）"""
    catalog = {
        'version': version,
        'bundles': {}
    }
    
    for filename in os.listdir(bundle_dir):
        if filename.endswith('.bundle'):
            filepath = os.path.join(bundle_dir, filename)
            catalog['bundles'][filename] = {
                'md5': compute_md5(filepath),
                'size': os.path.getsize(filepath),
                'url': f'https://cdn.example.com/bundles/{version}/{filename}'
            }
    
    return catalog

def upload_to_cdn(bundle_dir, version):
    """上传到CDN（AWS S3示例）"""
    s3 = boto3.client('s3')
    bucket = 'game-hotupdate-bucket'
    
    for filename in os.listdir(bundle_dir):
        filepath = os.path.join(bundle_dir, filename)
        s3_key = f'bundles/{version}/{filename}'
        
        print(f"上传 {filename} → s3://{bucket}/{s3_key}")
        s3.upload_file(filepath, bucket, s3_key, 
                       ExtraArgs={'CacheControl': 'max-age=31536000'})  # 1年缓存
    
    print(f"✅ 所有Bundle上传完成")

def update_version_api(catalog, version):
    """更新版本API（通知客户端有新版本）"""
    import requests
    
    response = requests.post(
        'https://api.example.com/game/version',
        json={
            'version': version,
            'catalog': catalog,
            'force_update': False,
            'update_desc': f'Version {version} hotfix'
        },
        headers={'Authorization': f'Bearer {os.environ["API_TOKEN"]}'}
    )
    
    if response.status_code == 200:
        print(f"✅ 版本API更新成功，版本号: {version}")
    else:
        raise Exception(f"版本API更新失败: {response.text}")

def main():
    version = os.environ.get('BUILD_VERSION', '1.0.0')
    platform = os.environ.get('TARGET_PLATFORM', 'Android')
    
    print(f"🚀 开始热更新发布流程 v{version} for {platform}")
    
    # 1. 打包AssetBundle
    build_asset_bundles(platform)
    
    # 2. 生成资源目录
    bundle_dir = f'Bundles/{platform}'
    catalog = generate_catalog(bundle_dir, version)
    
    # 3. 上传到CDN
    upload_to_cdn(bundle_dir, version)
    
    # 4. 更新版本API
    update_version_api(catalog, version)
    
    print(f"✅ 热更新发布完成！版本: {version}")

if __name__ == '__main__':
    main()
```

---

## 七、灰度发布实现

```csharp
// 客户端：灰度发布配置检查
public class GrayReleaseManager
{
    // 判断当前用户是否在灰度范围内
    public static bool IsInGrayGroup(string userId, int grayPercent)
    {
        // 用用户ID的Hash值决定是否在灰度范围
        int hash = Mathf.Abs(userId.GetHashCode());
        int bucket = hash % 100; // 映射到0-99
        return bucket < grayPercent; // grayPercent = 10 表示10%的用户
    }
    
    // 获取应该下载的版本
    public async Task<string> GetTargetVersion(string userId)
    {
        var versionInfo = await FetchVersionInfo();
        
        if (versionInfo.grayVersion != null && IsInGrayGroup(userId, versionInfo.grayPercent))
        {
            Debug.Log($"用户 {userId} 进入灰度版本: {versionInfo.grayVersion}");
            return versionInfo.grayVersion;
        }
        
        return versionInfo.stableVersion;
    }
}
```

---

## 总结

游戏CI/CD的建设路径：

```
阶段一（1-2周）：基础自动化
→ 代码提交触发自动构建
→ 构建失败自动通知
→ 测试包自动上传分发平台

阶段二（2-4周）：质量保障
→ 自动化单元测试集成
→ 资源规格自动检查
→ 静态代码分析

阶段三（1-2月）：高级能力
→ 自动化集成/冒烟测试
→ 性能回归测试
→ 热更新自动化发布
→ 灰度发布系统

价值：
技术负责人花1个月建设CI/CD
换来的是之后每天节省数小时人力
这是最高ROI的工程基础设施投资
```
