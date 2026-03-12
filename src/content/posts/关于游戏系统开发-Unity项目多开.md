---
title: Unity项目多开
published: 2020-11-03
description: "很多时候，调试战斗房间匹配，需要多个客户端，这个时候就很需要了。"
tags: []
category: Unity开发
draft: false
---



很多时候，调试战斗房间匹配，需要多个客户端，这个时候就很需要了。




## 同一个工程，多开

很多时候，调试战斗房间匹配，需要多个客户端，这个时候就很需要了。



发现创建链接的方式，同一个工程，可以多开。

1.使用mklink /J

原目录是： project_unity

新建mklink.bat,如下。

```text
%cd%

rem 需要创建的目录
set dir=project_unity_copy

rem 如果没有则创建
if not exist %dir% ( md %dir%) 

rem 创建链接
mklink /J %dir%\Assets project_unity\Assets
mklink /J %dir%\ProjectSettings project_unity\ProjectSettings
mklink /J %dir%\AssetBundles project_unity\AssetBundles

pause
```

