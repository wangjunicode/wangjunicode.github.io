---
title: LockStep框架使用
published: 2017-07-25
description: "帧同步框架Demo 1、新建工程"
tags: []
category: 网络同步
draft: false
---



## LockStep框架使用
帧同步框架Demo

1、新建工程

2、导入相关文件

 - Morefunlockstep.dll（新建一个Plugins文件夹，.dll文件放进来）
 - NetPkg四个网络模块脚本（新建一个DemoNet文件夹）
  - NetPkg.cs、NetPkgManager、NetPkgSender（不用任何修改）
  - NetPkgHandle.cs（注意加入游戏的回应，设置随机数种子）：GameManager.Instance.SetRandom(rsp.randomSeed);


 - GameManager.cs（自己新建）


```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Morefun.LockStep;

public class GameManager : Singleton<GameManager> {

	public FRandom random { get; private set; }
    public void SetRandom(int seed)
    {
        random = new FRandom(seed);
    }
}
```

 - Editor文件夹（GameIdBuild.cs）
 - Resources文件夹（GameID文件夹/GameID文件）

3、LockStep 和 Game 启动、初始化 —— Main.cs

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Morefun.LockStep;
using Morefun.LockStep.Net;

public class Main : MonoBehaviour {

	private void Start()
    {
        LockstepDebug.RegisteLogCallback(Debug.Log, Debug.LogWarning, Debug.LogError, null);
        LockStepManager.Init(OnLockstepTick, OnLockstepFrameMiss);
        LockStepManager.maxTimesPerFrame = 10;

        LockStepManager.Play();
        Game.Start();

        RequestHandle.RegistMessages();

        NetPkgManager.ConnectToDemoServer();
    }

    private void OnLockstepTick()
    {

    }

    private void OnLockstepFrameMiss(LList<int> missedFrameList)
    {
        int frameCount = missedFrameList.Count;
        for (int i = 0; i < frameCount; i++)
        {
            NetPkgSender.SendGetLostFrame((uint)missedFrameList[i], 1);
        }
    }

    private void Update()
    {
        NetPkgManager.Update();
        LockStepManager.Update();
    }

    private void OnDestroy()
    {
        NetPkgManager.Close();
        LockStepManager.Stop();
    }
}

```


4、连接服务器创建房间（UI 和 脚本）

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Morefun.LockStep.Net;
using UnityEngine.UI;

public class LoginUI : MonoBehaviour {

    private static LoginUI _instance;
    public static LoginUI Instance { get { return _instance; } }

    private void Awake()
    {
        _instance = this;
    }

    public InputField roomField;
    public InputField nameField;

    public void SendJoin()
    {
        NetPkgManager.Join(nameField.text.ToCharArray(), (ushort)short.Parse(roomField.text));
    }
    public void SendReady()
    {
        NetPkgSender.SendGameReady(NetPkgManager.LocalUIN);
    }

}
```



![img](/images/posts/LockStep框架使用/SouthEast.png)
