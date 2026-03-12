---
title: Unity拓展SVN工具
published: 2019-04-03
description: "public static void ProcessCommand(string command,string argument){ System.Diagno"
tags: []
category: Unity开发
draft: false
---



## 封装调用命令行


```c#
public static void ProcessCommand(string command,string argument){
		System.Diagnostics.ProcessStartInfo info = new System.Diagnostics.ProcessStartInfo(command);
		info.Arguments = argument;
		info.CreateNoWindow = false;
		info.ErrorDialog = true;
		info.UseShellExecute = true;
		
		if(info.UseShellExecute){
			info.RedirectStandardOutput = false;
			info.RedirectStandardError = false;
			info.RedirectStandardInput = false;
		} else{
			info.RedirectStandardOutput = true;
			info.RedirectStandardError = true;
			info.RedirectStandardInput = true;
			info.StandardOutputEncoding = System.Text.UTF8Encoding.UTF8;
			info.StandardErrorEncoding = System.Text.UTF8Encoding.UTF8;
		}
		
		System.Diagnostics.Process process = System.Diagnostics.Process.Start(info);
		
		if(!info.UseShellExecute){
			Debug.Log(process.StandardOutput);
			Debug.Log(process.StandardError);
		}
		
		process.WaitForExit();
		process.Close();
	}
```





## 封装操作



```c#
[MenuItem("SVN/Commit",false,1)]
	static void SVNCommit(){
		List<string> pathList = new List<string> ();
		string basePath = SVNProjectPath + "/Assets";
		pathList.Add (basePath);
		pathList.Add (SVNProjectPath+"/ProjectSettings");
		
		string commitPath = string.Join ("*", pathList.ToArray ());
		ProcessCommand ("TortoiseProc.exe", "/command:commit /path:"+ commitPath);
	}
	
	[MenuItem("SVN/Update",false,2)]
	static void SVNUpdate(){
		ProcessCommand ("TortoiseProc.exe", "/command:update /path:" + SVNProjectPath + " /closeonend:0");
	}
	
	[MenuItem("SVN/", false, 3)]
	static void Breaker () { }
	
	[MenuItem("SVN/CleanUp",false,4)]
	static void SVNCleanUp(){
		ProcessCommand ("TortoiseProc.exe", "/command:cleanup /path:" + SVNProjectPath);
	}
	
	[MenuItem("SVN/Log",false,5)]
	static void SVNLog(){
		ProcessCommand ("TortoiseProc.exe", "/command:log /path:" + SVNProjectPath);
	}
 
	static string SVNProjectPath{
		get{
			System.IO.DirectoryInfo parent = System.IO.Directory.GetParent(Application.dataPath);
			return parent.ToString();
		}
	}
```

