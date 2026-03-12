---
title: 游戏开发-Unity技术框架集合
published: 2021-05-10
description: "Unity技术框架（持续更新...）"
tags: []
category: Unity开发
draft: false
---

Unity技术框架（持续更新...）

## 引擎技术尝试

- [Animancer-Pro] ([https://assetstore.unity.com/packages/tools/animation/animancer-pro-116514](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fanimation%2Fanimancer-pro-116514)) （基于Playable的简单强大的动画解决方案）
- [ProBuilder/UModeler] ([https://assetstore.unity.com/packages/tools/modeling/umodeler-80868](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fmodeling%2Fumodeler-80868)) （快速关卡原型构建解决方案）
- [FGUI] ([https://github.com/fairygui/FairyGUI-unity](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Ffairygui%2FFairyGUI-unity)) （简单强大的UI解决方案）
- [URP] ([https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@7.5/manual/index.html](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fdocs.unity3d.com%2FPackages%2Fcom.unity.render-pipelines.universal%407.5%2Fmanual%2Findex.html)) （Unity官方可编程渲染管线-通用渲染管线）
- [ShaderGraph/AmplifyShaderEditor] ([https://assetstore.unity.com/packages/tools/visual-scripting/amplify-shader-editor-68570](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fvisual-scripting%2Famplify-shader-editor-68570)) （自定义Shader编辑器）
- [Bolt] ([https://assetstore.unity.com/packages/tools/visual-scripting/bolt-163802](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fvisual-scripting%2Fbolt-163802)) （可视化脚本）

------

## 资源管理方案

- [XAsset] ([https://github.com/xasset/xasset](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fxasset%2Fxasset)) （简单强大的资源管理插件，基于引擎自身的依赖关系实现，建议在项目中采用该方案）
- [GameFramework] ([https://github.com/EllanJiang/GameFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FEllanJiang%2FGameFramework)) （框架中的Resource模块，提供了一个自己维护引用的高度可定义资源管理框架，非常值得学习研究）

------

## 热更新方案

- [HybridCLR] ([https://github.com/focus-creative-games/hybridclr](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Ffocus-creative-games%2Fhybridclr)) （基于C#的热更新方案，目前效率最高的热更方案，单程序域运行）
- [tolua] ([https://github.com/topameng/tolua](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Ftopameng%2Ftolua)) (基于lua实现的嵌入虚拟机热更解决方案)
- [xlua] ([https://github.com/Tencent/xLua](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FTencent%2FxLua)) (基于lua实现的嵌入虚拟机热更解决方案，新加了动态修复C#函数功能)
- [ILRuntime] ([https://github.com/Ourpalm/ILRuntime](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FOurpalm%2FILRuntime)) (自己实现了一个IL运行时的解析器，以此来解决没有JIT环境下运行C#)

------

## 技能辅助开发工具

- [Slate] ([https://assetstore.unity.com/packages/tools/animation/slate-cinematic-sequencer-56558](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fanimation%2Fslate-cinematic-sequencer-56558)) (类似Timeline的时间线编辑工具,UI效果较好)
- [Flux] ([https://assetstore.unity.com/packages/tools/animation/flux-18440](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fanimation%2Fflux-18440)) (类似Timeline的时间线编辑工具，效果略差)
- [SuperCLine] ([https://assetstore.unity.com/packages/tools/game-toolkits/cline-action-editor-2-163343)(仿照Flux实现的可直接在项目使用的技能编辑器](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Fgame-toolkits%2Fcline-action-editor-2-163343%29%28%25E4%25BB%25BF%25E7%2585%25A7Flux%25E5%25AE%259E%25E7%258E%25B0%25E7%259A%2584%25E5%258F%25AF%25E7%259B%25B4%25E6%258E%25A5%25E5%259C%25A8%25E9%25A1%25B9%25E7%259B%25AE%25E4%25BD%25BF%25E7%2594%25A8%25E7%259A%2584%25E6%258A%2580%25E8%2583%25BD%25E7%25BC%2596%25E8%25BE%2591%25E5%2599%25A8))

------

## 编辑器扩展工具

- [Odin-Inspector] ([https://assetstore.unity.com/packages/tools/utilities/odin-inspector-and-serializer-89041](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fassetstore.unity.com%2Fpackages%2Ftools%2Futilities%2Fodin-inspector-and-serializer-89041)) （编辑器扩展、工作流改善）
- [NaughtyAttributes] ([https://github.com/dbrizov/NaughtyAttributes](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fdbrizov%2FNaughtyAttributes)) (实现基于属性的常用编辑器效果样式)
- [XiaoCaoTools] ([https://github.com/smartgrass/XiaoCaoTools](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fsmartgrass%2FXiaoCaoTools)) (基于上一个插件扩展的Window常用属性编辑器)
- [XCSkillEditor] ([https://github.com/smartgrass/XCSkillEditor_Unity](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fsmartgrass%2FXCSkillEditor_Unity)) (基于Lux开发的技能编辑器)
- [MDDSkillEngine] ([https://gitee.com/mtdmt/MDDSkillEngine](https://link.zhihu.com/?target=https%3A//gitee.com/mtdmt/MDDSkillEngine)) (基于UnityTimeline实现的技能编辑器)

------

## 前端开发框架

- [ET] ([https://github.com/egametang/ET](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fegametang%2FET)) (基于C#实现的双端共享的客户端和服务器框架)
- [GameFramework] ([https://github.com/EllanJiang/GameFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FEllanJiang%2FGameFramework)) （通用涵盖多模块客户端游戏开发框架）
- [KSFramework] ([https://github.com/mr-kelly/KSFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmr-kelly%2FKSFramework)) (通用的客户端框架)
- [BDFramework] ([https://github.com/yimengfan/BDFramework.Core](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyimengfan%2FBDFramework.Core)) (通用的客户端框架)
- [QFramework] ([https://github.com/liangxiegame/QFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fliangxiegame%2FQFramework)) (通用的客户端框架)
- [MyUnityFrameWork] ([https://github.com/GaoKaiHaHa/MyUnityFrameWork](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FGaoKaiHaHa%2FMyUnityFrameWork)) (通用的客户端框架)
- [loxodon-framework] ([https://github.com/vovgou/loxodon-framework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fvovgou%2Floxodon-framework)) (通用的客户端框架)
- [TinaX] ([https://github.com/yomunsam/TinaX](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyomunsam%2FTinaX)) (通用的客户端框架)
- [ColaFrameWork] ([https://github.com/XINCGer/ColaFrameWork](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FXINCGer%2FColaFrameWork)) (通用的客户端框架)
- [RPGCore] ([https://github.com/Fydar/RPGCore](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FFydar%2FRPGCore)) (通用的客户端框架)
- [MotionFramework] ([https://github.com/gmhevinci/MotionFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fgmhevinci%2FMotionFramework)) (通用的客户端框架)
- [HTFramework] ([https://github.com/SaiTingHu/HTFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSaiTingHu%2FHTFramework)) (通用的客户端框架)
- [HTFramework] ([https://github.com/mofr/Diablerie](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmofr%2FDiablerie)) (通用的客户端框架)

------

## 后端开发框架

- [ET] ([https://github.com/egametang/ET](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fegametang%2FET)) (基于C#实现的双端共享的客户端和服务器框架)
- [nakama] ([https://github.com/heroiclabs/nakama](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fheroiclabs%2Fnakama)) (通用的服务器框架)
- [NoahGameFrame] ([https://github.com/ketoo/NoahGameFrame](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fketoo%2FNoahGameFrame)) (通用的服务器框架)
- [GeekServer] ([https://github.com/leeveel/GeekServer](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fleeveel%2FGeekServer)) (通用的服务器框架)
- [kbengine] ([https://github.com/kbengine/kbengine](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fkbengine%2Fkbengine)) (通用的服务器框架)
- [leaf] ([https://github.com/name5566/leaf](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fname5566%2Fleaf)) (通用的服务器框架)

------

## Actor框架

- [https://github.com/akkadotnet/akka.net](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fakkadotnet%2Fakka.net)
- [https://github.com/AsynkronIT/protoactor-dotnet](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FAsynkronIT%2Fprotoactor-dotnet)
- [https://github.com/microsoft/service-fabric-services-and-actors-dotnet](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmicrosoft%2Fservice-fabric-services-and-actors-dotnet)

------

## DOTS面向数据技术栈

- [https://github.com/Leopotam/ecs](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FLeopotam%2Fecs)
- [https://github.com/sebas77/Svelto.ECS](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fsebas77%2FSvelto.ECS)
- [https://github.com/PixeyeHQ/actors.unity](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FPixeyeHQ%2Factors.unity)
- [https://github.com/EcsRx/ecsrx](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FEcsRx%2Fecsrx)
- [https://github.com/chromealex/ecs](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fchromealex%2Fecs)
- [https://github.com/scellecs/Morpeh](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fscellecs%2FMorpeh)

------

## IOC

- [https://github.com/strangeioc/strangeioc](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fstrangeioc%2Fstrangeioc)
- [https://github.com/modesttree/Zenject](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmodesttree%2FZenject)
- [https://github.com/CatLib/CatLib](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FCatLib%2FCatLib)

------

## 战斗、技能系统

- [https://github.com/m969/EGamePlay](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fm969%2FEGamePlay)
- [https://github.com/sjai013/UnityGameplayAbilitySystem](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fsjai013%2FUnityGameplayAbilitySystem)
- [https://github.com/tranek/GASDocumentation](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Ftranek%2FGASDocumentation) （虚幻引擎的GamePlay Ability System 文档）
- [https://github.com/dongweiPeng/SkillSystem](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FdongweiPeng%2FSkillSystem)
- [https://github.com/delmarle/RPG-Core](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fdelmarle%2FRPG-Core)
- [https://github.com/KrazyL/SkillSystem-3](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FKrazyL%2FSkillSystem-3) （Dota2 alike Skill System Implementation for KnightPhone）
- [https://github.com/dx50075/SkillSystem](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fdx50075%2FSkillSystem)
- [https://github.com/michaelday008/AnyRPGAlphaCode](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmichaelday008%2FAnyRPGAlphaCode)
- [https://github.com/weichx/AbilitySystem](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fweichx%2FAbilitySystem)
- [https://github.com/gucheng0712/CombatDesigner](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fgucheng0712%2FCombatDesigner) （A Frame Based Visual Combat System in Unity Game Engine.）
- [https://github.com/PxGame/XMLib.AM](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FPxGame%2FXMLib.AM)

------

## 帧同步框架

- [https://github.com/JiepengTan/LockstepEngine](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FJiepengTan%2FLockstepEngine)
- [https://github.com/proepkes/UnityLockstep](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fproepkes%2FUnityLockstep)
- [https://github.com/SnpM/LockstepFramework](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSnpM%2FLockstepFramework)

------

## 常用工具插件

## 黑客工具、网络异常模拟

- [https://github.com/Z4nzu/hackingtool](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FZ4nzu%2Fhackingtool)

## 资源检查

- [https://github.com/ZxIce/AssetCheck](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FZxIce%2FAssetCheck)
- [https://github.com/yasirkula/UnityAssetUsageDetector](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyasirkula%2FUnityAssetUsageDetector)

## Unity小工具

- [https://github.com/lujian101/UnityToolDist](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Flujian101%2FUnityToolDist) （动画压缩、矩阵调试等）
- [https://github.com/Unity-Technologies/VFXToolbox](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FUnity-Technologies%2FVFXToolbox)
- [https://github.com/Deadcows/MyBox](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FDeadcows%2FMyBox)
- [https://github.com/Ayfel/PrefabLightmapping](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FAyfel%2FPrefabLightmapping)
- [https://github.com/laurenth-personal/lightmap-switching-tool](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Flaurenth-personal%2Flightmap-switching-tool)
- [https://github.com/yasirkula/UnityRuntimeInspector](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyasirkula%2FUnityRuntimeInspector)

## 程序化工具

- [https://github.com/Syomus/ProceduralToolkit](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSyomus%2FProceduralToolkit)
- [https://github.com/mxgmn/WaveFunctionCollapse](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmxgmn%2FWaveFunctionCollapse)

------

## 图形渲染

## 水渲染

- [https://github.com/flamacore/UnityHDRPSimpleWater](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fflamacore%2FUnityHDRPSimpleWater)

## 镜面反射

- [https://github.com/Kink3d/kMirrors](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FKink3d%2FkMirrors) （URP）
- [https://github.com/ColinLeung-NiloCat/UnityURP-MobileScreenSpacePlanarReflection](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FColinLeung-NiloCat%2FUnityURP-MobileScreenSpacePlanarReflection)

## 卡通渲染

- [https://github.com/ColinLeung-NiloCat/UnityURPToonLitShaderExample](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FColinLeung-NiloCat%2FUnityURPToonLitShaderExample)
- [https://github.com/unity3d-jp/UnityChanToonShaderVer2_Project](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Funity3d-jp%2FUnityChanToonShaderVer2_Project)
- [https://github.com/Kink3d/kShading](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FKink3d%2FkShading)
- [https://github.com/SnutiHQ/Toon-Shader](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSnutiHQ%2FToon-Shader)
- [https://github.com/IronWarrior/UnityToonShader](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FIronWarrior%2FUnityToonShader)
- [https://github.com/Jason-Ma-233/JasonMaToonRenderPipeline](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FJason-Ma-233%2FJasonMaToonRenderPipeline)
- [https://github.com/ronja-tutorials/ShaderTutorials](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fronja-tutorials%2FShaderTutorials)
- [https://github.com/you-ri/LiliumToonGraph](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyou-ri%2FLiliumToonGraph)
- [https://github.com/madumpa/URP_StylizedLitShader](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmadumpa%2FURP_StylizedLitShader)
- [https://github.com/Sorumi/UnityToonShader](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSorumi%2FUnityToonShader)
- [https://github.com/ChiliMilk/URP_Toon](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FChiliMilk%2FURP_Toon)

## 草渲染

- [https://github.com/ColinLeung-NiloCat/UnityURP-MobileDrawMeshInstancedIndirectExample](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FColinLeung-NiloCat%2FUnityURP-MobileDrawMeshInstancedIndirectExample)

## Decals

- [https://github.com/Kink3d/kDecals](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FKink3d%2FkDecals)

## 体素

- [https://github.com/mattatz/unity-voxel](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmattatz%2Funity-voxel)

## 体积雾

- [https://github.com/ArthurBrussee/Vapor](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FArthurBrussee%2FVapor)

------

## 其他相关库

## 网络库

- [https://github.com/RevenantX/LiteNetLib](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FRevenantX%2FLiteNetLib)
- [https://github.com/BeardedManStudios/ForgeNetworkingRemastered](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FBeardedManStudios%2FForgeNetworkingRemastered)
- [https://github.com/Yinmany/NetCode-FPS](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FYinmany%2FNetCode-FPS)

## 序列化

- [https://github.com/google/flatbuffers](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fgoogle%2Fflatbuffers) (据说序列化快，占内存大，相比于pb，适合游戏开发)
- [https://github.com/jamescourtney/FlatSharp](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fjamescourtney%2FFlatSharp)

## 动态表达式解析库

- [https://github.com/davideicardi/DynamicExpresso](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fdavideicardi%2FDynamicExpresso)
- [https://github.com/zzzprojects/Eval-Expression.NET](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fzzzprojects%2FEval-Expression.NET)
- [https://github.com/mparlak/Flee](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmparlak%2FFlee)
- [https://github.com/codingseb/ExpressionEvaluator](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fcodingseb%2FExpressionEvaluator)
- [http://wiki.unity3d.com/index.php/ExpressionParser](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttp%3A%2F%2Fwiki.unity3d.com%2Findex.php%2FExpressionParser)

## 物理碰撞

- [https://github.com/AndresTraks/BulletSharp](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FAndresTraks%2FBulletSharp)
- [https://github.com/Zonciu/Box2DSharp](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FZonciu%2FBox2DSharp)
- [https://github.com/JiepengTan/LockstepCollision](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FJiepengTan%2FLockstepCollision)
- [https://github.com/Prince-Ling/LogicPhysics](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FPrince-Ling%2FLogicPhysics)
- [https://github.com/aaa719717747/TrueSyncExample](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Faaa719717747%2FTrueSyncExample)
- [https://github.com/dotnet-ad/Humper](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fdotnet-ad%2FHumper)

## 动态骨骼

- [https://github.com/OneYoungMean/Automatic-DynamicBone](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FOneYoungMean%2FAutomatic-DynamicBone)

## 图节点式编辑器（Graph Editor）

- [https://github.com/alelievr/NodeGraphProcessor](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Falelievr%2FNodeGraphProcessor)
- [https://github.com/Siccity/xNode](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FSiccity%2FxNode)
- [https://github.com/nicloay/Node-Inspector](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fnicloay%2FNode-Inspector)

## 行为树

- [https://github.com/meniku/NPBehave](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fmeniku%2FNPBehave)
- [https://github.com/ashblue/fluid-behavior-tree](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fashblue%2Ffluid-behavior-tree)
- [https://github.com/luis-l/BonsaiBehaviourTree](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fluis-l%2FBonsaiBehaviourTree)

## 笔刷绘图

- [https://github.com/EsProgram/InkPainter](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FEsProgram%2FInkPainter)

## ScrollRect

- [https://github.com/qiankanglai/LoopScrollRect](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fqiankanglai%2FLoopScrollRect)

## SRP项目

- [https://github.com/keijiro/TestbedHDRP](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fkeijiro%2FTestbedHDRP)

## 敏感词库

- [https://github.com/toolgood/ToolGood.Words](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Ftoolgood%2FToolGood.Words)

## 算法

- [https://github.com/labuladong/fucking-algorithm](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Flabuladong%2Ffucking-algorithm)
- [https://github.com/azl397985856/leetcode](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fazl397985856%2Fleetcode)
- [https://github.com/halfrost/LeetCode-Go](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fhalfrost%2FLeetCode-Go)

## 原生平台交互

- [https://github.com/yasirkula/UnityNativeShare](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fyasirkula%2FUnityNativeShare)
- [https://github.com/hellowod/u3d-plugins-development](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fhellowod%2Fu3d-plugins-development)

## GPU蒙皮动画

- [https://github.com/chenjd/Render-Crowd-Of-Animated-Characters](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fchenjd%2FRender-Crowd-Of-Animated-Characters)

------

## 优秀引用库

- [https://github.com/utilForever/game-developer-roadmap](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FutilForever%2Fgame-developer-roadmap) (游戏开发者路线图)
- [https://github.com/RyanNielson/awesome-unity](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FRyanNielson%2Fawesome-unity)
- [https://github.com/MFatihMAR/Game-Networking-Resources](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FMFatihMAR%2FGame-Networking-Resources)
- [https://github.com/Gforcex/OpenGraphic](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2FGforcex%2FOpenGraphic)
- [https://github.com/insthync/awesome-unity3d](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Finsthync%2Fawesome-unity3d)
- [https://github.com/killop/anything_about_game](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fkillop%2Fanything_about_game)
- [https://github.com/uhub/awesome-c-sharp](https://link.zhihu.com/?target=https%3A//gitee.com/link%3Ftarget%3Dhttps%3A%2F%2Fgithub.com%2Fuhub%2Fawesome-c-sharp)