---
title: AssetBundle加载技术
published: 2020-09-05
description: "AssetBundle加载有三套接口，`WWW`，`UnityWebRequest`和`AssetBundle`，推荐`AssetBundle`"
tags: []
category: Unity开发
draft: false
---

### AssetBundle加载技术选型

AssetBundle加载有三套接口，`WWW`，`UnityWebRequest`和`AssetBundle`，推荐`AssetBundle`


前两者都要经历将整个文件的二进制流下载或读取到内存中，然后对这段内存文件进行ab资源的读取解析操作，而`AssetBundle`可以只读取存储于本地的ab文件的头部部分，在需要的情况下，读取ab中的数据段部分（Asset资源）。



所以AssetBundle相对的优势是

- 不进行下载(不占用下载缓存区内存)

- 不读取整个文件到内存（不占用原始文件二进制内存）

- 读取非压缩或LZ4的ab，只读取ab的文件头（约5kb/个）

- 同步异步加载并行可用



所以，从内存和效率方面，AssetBundle会是目前最优解，而使用非压缩或LZ4读者自己评断（推荐LZ4）



**AssetBundle加载方式最重要的接口**

- AssetBundle.LoadFromFile 从本地文件同步加载ab
- AssetBundle.LoadFromFileAsync 从本地文件异步加载ab
- AssetBundle.Unload 卸载，注意true和false区别
- AssetBundle.LoadAsset 从ab同步加载Asset
- AssetBundle.LoadAssetAsync 从ab异步加载Asset



**使用异步`AssetBundle`加载的时候**

可以考虑用update每帧访问的方式替代协程的方式



```csharp
AssetBundleCreateRequest request = AssetBundle.LoadFromFileAsync(path);

IEnumerator LoadAssetBundle()
{
	yield return request;
	//do something
}

转变为

void Update（）
{
	if（request.isDone）
	{
		//do something
	}
}
```

### 设计

#### 加载队列

```csharp
private Dictionary<string, AssetBundleObject> _readyABList; //预备加载的列表
private Dictionary<string, AssetBundleObject> _loadingABList; //正在加载的列表
private Dictionary<string, AssetBundleObject> _loadedABList; //加载完成的列表
private Dictionary<string, AssetBundleObject> _unloadABList; //准备卸载的列表
```

![image-20230905113200042](/images/posts/AssetBundle加载技术/image-20230905113200042.png)

#### 外部接口

![image-20230905113413606](/images/posts/AssetBundle加载技术/image-20230905113413606.png)



### 实现

#### 加载依赖关系配置

一般在热更流程之后，游戏初始化前，进行游戏初始化的时候，加载的配置是unity导出AssetBundle时候生成的主Mainfest文件

```csharp
_dependsDataList.Clear();
AssetBundle ab = AssetBundle.LoadFromFile(path);
AssetBundleManifest mainfest = ab.LoadAsset("AssetBundleManifest") as AssetBundleManifest;

foreach(string assetName in mainfest.GetAllAssetBundles())
{
    string hashName = assetName.Replace(".ab", "");
    string[] dps = mainfest.GetAllDependencies(assetName);
    for (int i = 0; i < dps.Length; i++)
        dps[i] = dps[i].Replace(".ab", "");
    _dependsDataList.Add(hashName, dps);
}

ab.Unload(true); //用完要卸载
ab = null;
```



#### 加载节点数据结构

```csharp
public delegate void AssetBundleLoadCallBack(AssetBundle ab);

private class AssetBundleObject
{
    public string _hashName; //hash标识符

    public int _refCount; //引用计数
    public List<AssetBundleLoadCallBack> _callFunList = new List<AssetBundleLoadCallBack>(); //回调函数

    public AssetBundleCreateRequest _request; //异步加载请求
    public AssetBundle _ab; //加载到的ab

    public int _dependLoadingCount; //依赖计数
    public List<AssetBundleObject> _depends = new List<AssetBundleObject>(); //依赖项
}
```



#### 依赖加载——递归&引用计数&队列&回调(重难点)



#### 同步加载



#### 实现Demo

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

public class AssetBundleLoadMgr
{
    public delegate void AssetBundleLoadCallBack(AssetBundle ab);

    private class AssetBundleObject
    {
        public string _hashName;

        public int _refCount;
        public List<AssetBundleLoadCallBack> _callFunList = new List<AssetBundleLoadCallBack>();

        public AssetBundleCreateRequest _request;
        public AssetBundle _ab;

        public int _dependLoadingCount;
        public List<AssetBundleObject> _depends = new List<AssetBundleObject>();
    }

    private static AssetBundleLoadMgr _Instance = null;

    public static AssetBundleLoadMgr I
    {
        get {
            if (_Instance == null) _Instance = new AssetBundleLoadMgr();
            return _Instance;
        }
    }

    private const int MAX_LOADING_COUNT = 10; //同时加载的最大数量

    private List<AssetBundleObject> tempLoadeds = new List<AssetBundleObject>(); //创建临时存储变量，用于提升性能

    private Dictionary<string, string[]> _dependsDataList;

    private Dictionary<string, AssetBundleObject> _readyABList; //预备加载的列表
    private Dictionary<string, AssetBundleObject> _loadingABList; //正在加载的列表
    private Dictionary<string, AssetBundleObject> _loadedABList; //加载完成的列表
    private Dictionary<string, AssetBundleObject> _unloadABList; //准备卸载的列表

    private AssetBundleLoadMgr()
    {
        _dependsDataList = new Dictionary<string, string[]>();

        _readyABList = new Dictionary<string, AssetBundleObject>();
        _loadingABList = new Dictionary<string, AssetBundleObject>();
        _loadedABList = new Dictionary<string, AssetBundleObject>();
        _unloadABList = new Dictionary<string, AssetBundleObject>();
        
    }

    public void LoadMainfest()
    {
        string path = FileVersionMgr.I.GetFilePathByExist("Assets");
        if (string.IsNullOrEmpty(path)) return;

        _dependsDataList.Clear();
        AssetBundle ab = AssetBundle.LoadFromFile(path);

        if(ab == null)
        {
            string errormsg = string.Format("LoadMainfest ab NULL error !");
            Debug.LogError(errormsg);
            return;
        }

        AssetBundleManifest mainfest = ab.LoadAsset("AssetBundleManifest") as AssetBundleManifest;
        if (mainfest == null)
        {
            string errormsg = string.Format("LoadMainfest NULL error !");
            Debug.LogError(errormsg);
            return;
        }

        foreach(string assetName in mainfest.GetAllAssetBundles())
        {
            string hashName = assetName.Replace(".ab", "");
            string[] dps = mainfest.GetAllDependencies(assetName);
            for (int i = 0; i < dps.Length; i++)
                dps[i] = dps[i].Replace(".ab", "");
            _dependsDataList.Add(hashName, dps);
        }

        ab.Unload(true);
        ab = null;

        Debug.Log("AssetBundleLoadMgr dependsCount=" + _dependsDataList.Count);
    }

    private string GetHashName(string _assetName)
    {//读者可以自己定义hash方式，对内存有要求的话，可以hash成uint（或uint64）节省内存
        return _assetName.ToLower();
    }

    private string GetFileName(string _hashName)
    {//读者可以自己实现自己的对应关系
        return _hashName + ".ab";
    }
    
    // 获取一个资源的路径
    private string GetAssetBundlePath(string _hashName)
    {//读者可以自己实现的对应关系，笔者这里有多语言和文件版本的处理
        string lngHashName = GetHashName(LocalizationMgr.I.GetAssetPrefix() + _hashName);
        if (_dependsDataList.ContainsKey(lngHashName))
            _hashName = lngHashName;

        return FileVersionMgr.I.GetFilePath(GetFileName(_hashName));
    }

    public bool IsABExist(string _assetName)
    {
        string hashName = GetHashName(_assetName);
        return _dependsDataList.ContainsKey(hashName);
    }

    //同步加载
    public AssetBundle LoadSync(string _assetName)
    {
        string hashName = GetHashName(_assetName);
        var abObj = LoadAssetBundleSync(hashName);
        return abObj._ab;
    }

    //异步加载（已经加载直接回调），每次加载引用计数+1
    public void LoadAsync(string _assetName, AssetBundleLoadCallBack callFun)
    {
        string hashName = GetHashName(_assetName);
        LoadAssetBundleAsync(hashName, callFun);
    }
    //卸载（异步），每次卸载引用计数-1
    public void Unload(string _assetName)
    {
        string hashName = GetHashName(_assetName);
        UnloadAssetBundleAsync(hashName);
    }

    private AssetBundleObject LoadAssetBundleSync(string _hashName)
    {
        AssetBundleObject abObj = null;
        if (_loadedABList.ContainsKey(_hashName)) //已经加载
        {
            abObj = _loadedABList[_hashName];
            abObj._refCount++;

            foreach (var dpObj in abObj._depends)
            {
                LoadAssetBundleSync(dpObj._hashName); //递归依赖项，附加引用计数
            }

            return abObj;
        }
        else if (_loadingABList.ContainsKey(_hashName)) //在加载中,异步改同步
        {
            abObj = _loadingABList[_hashName];
            abObj._refCount++;

            foreach(var dpObj in abObj._depends)
            {
                LoadAssetBundleSync(dpObj._hashName); //递归依赖项，加载完
            }

            DoLoadedCallFun(abObj, false); //强制完成，回调

            return abObj;
        }
        else if (_readyABList.ContainsKey(_hashName)) //在准备加载中
        {
            abObj = _readyABList[_hashName];
            abObj._refCount++;

            foreach (var dpObj in abObj._depends)
            {
                LoadAssetBundleSync(dpObj._hashName); //递归依赖项，加载完
            }

            string path1 = GetAssetBundlePath(_hashName);
            abObj._ab = AssetBundle.LoadFromFile(path1);

            _readyABList.Remove(abObj._hashName);
            _loadedABList.Add(abObj._hashName, abObj);

            DoLoadedCallFun(abObj, false); //强制完成，回调

            return abObj;
        }

        //创建一个加载
        abObj = new AssetBundleObject();
        abObj._hashName = _hashName;

        abObj._refCount = 1;

        string path = GetAssetBundlePath(_hashName);
        abObj._ab = AssetBundle.LoadFromFile(path);

        if(abObj._ab == null)
        {
            try
            {
                //同步下载解决
                byte[] bytes = AssetsDownloadMgr.I.DownloadSync(GetFileName(abObj._hashName));
                if (bytes != null && bytes.Length != 0)
                    abObj._ab = AssetBundle.LoadFromMemory(bytes);
            }
            catch (Exception ex)
            {
                Debug.LogError("LoadAssetBundleSync DownloadSync" + ex.Message);
            }
        }
        
        //加载依赖项
        string[] dependsData = null;
        if (_dependsDataList.ContainsKey(_hashName))
        {
            dependsData = _dependsDataList[_hashName];
        }

        if (dependsData != null && dependsData.Length > 0)
        {
            abObj._dependLoadingCount = 0;

            foreach (var dpAssetName in dependsData)
            {
                var dpObj = LoadAssetBundleSync(dpAssetName);

                abObj._depends.Add(dpObj);
            }

        }

        _loadedABList.Add(abObj._hashName, abObj);

        return abObj;
    }

    private void UnloadAssetBundleAsync(string _hashName)
    {
        AssetBundleObject abObj = null;
        if (_loadedABList.ContainsKey(_hashName))
            abObj = _loadedABList[_hashName];
        else if (_loadingABList.ContainsKey(_hashName))
            abObj = _loadingABList[_hashName];
        else if (_readyABList.ContainsKey(_hashName))
            abObj = _readyABList[_hashName];

        if (abObj == null)
        {
            string errormsg = string.Format("UnLoadAssetbundle error ! assetName:{0}",_hashName);
            Debug.LogError(errormsg);
            return;
        }

        if (abObj._refCount == 0)
        {
            string errormsg = string.Format("UnLoadAssetbundle refCount error ! assetName:{0}", _hashName);
            Debug.LogError(errormsg);
            return;
        }

        abObj._refCount--;

        foreach (var dpObj in abObj._depends)
        {
            UnloadAssetBundleAsync(dpObj._hashName);
        }

        if (abObj._refCount == 0)
        {
            _unloadABList.Add(abObj._hashName, abObj);
        }
    }


    private AssetBundleObject LoadAssetBundleAsync(string _hashName, AssetBundleLoadCallBack _callFun)
    {
        AssetBundleObject abObj = null;
        if (_loadedABList.ContainsKey(_hashName)) //已经加载
        {
            abObj = _loadedABList[_hashName];
            DoDependsRef(abObj);
            _callFun(abObj._ab);
            return abObj;
        }
        else if(_loadingABList.ContainsKey(_hashName)) //在加载中
        {
            abObj = _loadingABList[_hashName];
            DoDependsRef(abObj);
            abObj._callFunList.Add(_callFun);
            return abObj;
        }
        else if (_readyABList.ContainsKey(_hashName)) //在准备加载中
        {
            abObj = _readyABList[_hashName];
            DoDependsRef(abObj);
            abObj._callFunList.Add(_callFun);
            return abObj;
        }

        //创建一个加载
        abObj = new AssetBundleObject();
        abObj._hashName = _hashName;

        abObj._refCount = 1;
        abObj._callFunList.Add(_callFun);

        //加载依赖项
        string[] dependsData = null;
        if (_dependsDataList.ContainsKey(_hashName))
        {
            dependsData = _dependsDataList[_hashName];
        }

        if (dependsData != null && dependsData.Length > 0)
        {
            abObj._dependLoadingCount = dependsData.Length;

            foreach(var dpAssetName in dependsData)
            {
                var dpObj = LoadAssetBundleAsync(dpAssetName,
                    (AssetBundle _ab) =>
                    {
                        if(abObj._dependLoadingCount <= 0)
                        {
                            string errormsg = string.Format("LoadAssetbundle depend error ! assetName:{0}", _hashName);
                            Debug.LogError(errormsg);
                            return;
                        }

                        abObj._dependLoadingCount--;
                        
                        //依赖加载完
                        if (abObj._dependLoadingCount == 0 && abObj._request != null && abObj._request.isDone)
                        {
                            DoLoadedCallFun(abObj);
                        }
                    }
                );

                abObj._depends.Add(dpObj);
            }

        }

        if (_loadingABList.Count < MAX_LOADING_COUNT) //正在加载的数量不能超过上限
        {
            DoLoad(abObj);

            _loadingABList.Add(_hashName, abObj);
        }
        else _readyABList.Add(_hashName, abObj);

        return abObj;
    }

    private void DoDependsRef(AssetBundleObject abObj)
    {
        abObj._refCount++;

        if (abObj._depends.Count == 0) return;
        foreach (var dpObj in abObj._depends)
        {
            DoDependsRef(dpObj); //递归依赖项，加载完
        }
    }

    private void DoLoad(AssetBundleObject abObj)
    {
        if (AssetsDownloadMgr.I.IsNeedDownload(GetFileName(abObj._hashName)))
        {//这里是关联下载逻辑，可以实现异步下载再异步加载
            AssetsDownloadMgr.I.DownloadAsync(GetFileName(abObj._hashName), 
                () =>
                {
                    string path = GetAssetBundlePath(abObj._hashName);
                    abObj._request = AssetBundle.LoadFromFileAsync(path);

                    if (abObj._request == null)
                    {
                        string errormsg = string.Format("LoadAssetbundle path error ! assetName:{0}", abObj._hashName);
                        Debug.LogError(errormsg);
                    }
                }
            );
        }
        else
        {
            string path = GetAssetBundlePath(abObj._hashName);
            abObj._request = AssetBundle.LoadFromFileAsync(path);

            if (abObj._request == null)
            {
                string errormsg = string.Format("LoadAssetbundle path error ! assetName:{0}", abObj._hashName);
                Debug.LogError(errormsg);
            }
        }

    }

    private void DoLoadedCallFun(AssetBundleObject abObj, bool isAsync = true)
    {
        //提取ab
        if(abObj._request != null)
        {
            abObj._ab = abObj._request.assetBundle; //如果没加载完，会异步转同步
            abObj._request = null;
            _loadingABList.Remove(abObj._hashName);
            _loadedABList.Add(abObj._hashName, abObj);
        }

        if (abObj._ab == null)
        {
            string errormsg = string.Format("LoadAssetbundle _ab null error ! assetName:{0}", abObj._hashName);
            string path = GetAssetBundlePath(abObj._hashName);
            errormsg += "\n File " + File.Exists(path) + " Exists " + path;

            try
            {//尝试读取二进制解决
                if(File.Exists(path))
                {
                    byte[] bytes = File.ReadAllBytes(path);
                    if (bytes != null && bytes.Length != 0)
                        abObj._ab = AssetBundle.LoadFromMemory(bytes);
                }
            }
            catch (Exception ex)
            {
                Debug.LogError("LoadAssetbundle ReadAllBytes Error " + ex.Message);
            }

            if (abObj._ab == null)
            {
                //同步下载解决
                byte[] bytes = AssetsDownloadMgr.I.DownloadSync(GetFileName(abObj._hashName));
                if (bytes != null && bytes.Length != 0)
                    abObj._ab = AssetBundle.LoadFromMemory(bytes);

                if (abObj._ab == null)
                {//同步下载还不能解决，移除
                    if (_loadedABList.ContainsKey(abObj._hashName)) _loadedABList.Remove(abObj._hashName);
                    else if (_loadingABList.ContainsKey(abObj._hashName)) _loadingABList.Remove(abObj._hashName);

                    Debug.LogError(errormsg);

                    if (isAsync)
                    {//异步下载解决
                        AssetsDownloadMgr.I.AddDownloadSetFlag(GetFileName(abObj._hashName));
                    }
                }
            }
        }

        //运行回调
        foreach (var callback in abObj._callFunList)
        {
            callback(abObj._ab);
        }
        abObj._callFunList.Clear();
    }

    private void UpdateLoad()
    {
        if (_loadingABList.Count == 0) return;
        //检测加载完的
        tempLoadeds.Clear();
        foreach (var abObj in _loadingABList.Values)
        {
            if (abObj._dependLoadingCount == 0 && abObj._request != null && abObj._request.isDone)
            {
                tempLoadeds.Add(abObj);
            }
        }
        //回调中有可能对_loadingABList进行操作，提取后回调
        foreach (var abObj in tempLoadeds)
        {
            //加载完进行回调
            DoLoadedCallFun(abObj);
        }
        
    }

    private void DoUnload(AssetBundleObject abObj)
    {
        //这里用true，卸载Asset内存，实现指定卸载
        if(abObj._ab == null)
        {
            string errormsg = string.Format("LoadAssetbundle DoUnload error ! assetName:{0}", abObj._hashName);
            Debug.LogError(errormsg);
            return;
        }

        abObj._ab.Unload(true);
        abObj._ab = null;
    }

    private void UpdateUnLoad()
    {
        if (_unloadABList.Count == 0) return;

        tempLoadeds.Clear();
        foreach (var abObj in _unloadABList.Values)
        {
            if (abObj._refCount == 0 && abObj._ab != null)
            {//引用计数为0并且已经加载完，没加载完等加载完销毁
                DoUnload(abObj);
                _loadedABList.Remove(abObj._hashName);

                tempLoadeds.Add(abObj);
            }

            if (abObj._refCount > 0)
            {//引用计数加回来（销毁又瞬间重新加载，不销毁，从销毁列表移除）
                tempLoadeds.Add(abObj);
            }
        }

        foreach(var abObj in tempLoadeds)
        {
            _unloadABList.Remove(abObj._hashName);
        }
    }

    private void UpdateReady()
    {
        if (_readyABList.Count == 0) return;
        if (_loadingABList.Count >= MAX_LOADING_COUNT) return;
        
        tempLoadeds.Clear();
        foreach (var abObj in _readyABList.Values)
        {
            DoLoad(abObj);

            tempLoadeds.Add(abObj);
            _loadingABList.Add(abObj._hashName, abObj);

            if (_loadingABList.Count >= MAX_LOADING_COUNT) break;
        }

        foreach (var abObj in tempLoadeds)
        {
            _readyABList.Remove(abObj._hashName);
        }
    }

    public void Update()
    {
        UpdateLoad();
        UpdateReady();
        UpdateUnLoad();
    }
}


```

