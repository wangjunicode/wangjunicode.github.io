---
title: Shader
published: 2021-09-05
description: "Shader又称着色器，是一段跑在GPU上的程序，在旧的图形渲染管线中，图形开发者对显卡渲染流程的控制很有限，随着着色器的程序的出现，开发者可以在着色器程序中执"
tags: []
category: 图形渲染
draft: false
---



## Shader简介

Shader又称着色器，是一段跑在GPU上的程序，在旧的图形渲染管线中，图形开发者对显卡渲染流程的控制很有限，随着着色器的程序的出现，开发者可以在着色器程序中执行几何变换、光照模型、纹理贴图等复杂的计算，极大地提高了灵活性和效率，因而可以完成一些更复杂的渲染任务，实现更加炫酷的特效。不同的显卡厂商提供的图形接口有不同的着色器语言（Shader Language）语法，比如微软Direct3D的HLSL，Nvidia的Cg，以及OpenGL的GLSL等，本文讨论的就是GLSL的简单语法入门和应用。


OpenGL中的着色器程序主要包含两部分，一部分是Vertex Shader(顶点着色器)，一部分是Fragment Shader（片元着色器，或称像素着色器），顶点着色器的主要任务包括对传到GPU中的顶点数据进行处理，比如进行适当的矩阵变换以及进行光照的计算、生成变换纹理坐标等等，**顶点着色器针对每一个顶点都会执行一次**。片元着色器则是对最终会绘制到屏幕上的每个像素点进行着色，计算相应的颜色值，**片元着色器针对屏幕上每一个位置的像素都会执行一次**，即每段Fragment Shader针对屏幕上每个像素点都会运行一次，且每个像素点之间的处理相互并行，互不干扰，理解这一点对我们后面用shader来绘图十分重要。正因为如此在高分辨率的渲染任务中只有图形显卡才能支持这种大规模的逐像素并行处理。





## GLSL基础语法

OpenGL（包括OpenGL ES，移动平台专用）经过很多版本的迭代，GLSL也发生了很大改变，比如从2.0到3.0的接口就有了很大的丰富，其中比较重要的一个就是现代OpenGL（Core Profile）中如果设置了非Compatibility即非向后兼容的模式，则一些旧的标记废弃的API则无法在新版本的OpenGL环境中生效。

下面我们先来看一段OpenGL 2.0版本的Fragement Shader（OpenGL 2.0版本对应的GLSL版本是110），了解一下最基本的一些语法概念。

```c
#version 110
attribute vec3 aPosition ;
attribute vec4 aTextureColor;
uniform mat4 uMVPMatrix;
varying vec4 vTextureColor ;

void main(){
   gl_Position= uMVPMatrix * vec4(aPosition, 1);
   vTextureColor = aTextureColor; 
}
```

首先第一行，声明了GLSL的版本，其次是两个attribute变量，attribute是顶点着色器的输入变量，只能在vertex shader中使用，来表示一些顶点的数据，如：顶点坐标，法线，纹理坐标，顶点颜色等，可以通过以下方法来从程序中将值传给attribute变量

```c
GLint glGetAttribLocation(GLuint program, const GLchar *name); //根据变量名name获取该attribute变量在shader程序中的位置
void glVertexAttrib4f(GLuint index, GLfloat x, GLfloat y, GLfloat z, GLfloat w); //给该attribute变量代表的顶点赋值四个浮点数
void glVertexAttrib4fv(GLuint index, const GLfloat *v); //给该attribute变量代表的顶点赋值含有四个浮点数的数组
void glVertexAttribPointer (GLuint index, GLint size, GLenum type, GLboolean normalized, GLsizei stride, const void *pointer); //根据顶点数组和索引传值
```

vec3就是指三维向量，在shader中我们用三维向量来代表一个基本的RGB颜色，vec3三个分量可以通过xyz，也可以通过rgb来分别访问，如果是vec4的话，第四个分量一般就代表的是alpha值，如下的操作在shader中都是合法的

```c
vec3 a;
vec4 = vec4( a.xyz, 1.0 );
vec3 b = a.rgb;
```

需要注意的是一般这里的数字尽量用带小字母的浮点数，否则的话在某些GPU上可能会出现问题



## uniform

第三行的uniform变量，传入了一个MVP变换矩阵，其实是包含Model模型变换、View视图变换、Projection投影变换三个阶段的变换的总称，这里合并成了一个矩阵，关于OpenGL几种变换关系大家还不清楚的可以移步OpenGL的官方示例[OpenGL-Tutotial矩阵]([﻿第三课：矩阵](https://link.zhihu.com/?target=http%3A//www.opengl-tutorial.org/cn/beginners-tutorials/tutorial-3-matrices/%23%E6%A8%A1%E5%9E%8Bmodel%E8%A7%82%E5%AF%9Fview%E5%92%8C%E6%8A%95%E5%BD%B1projection%E7%9F%A9%E9%98%B5))，里面有形象的图片例子。uniform是CPU往GPU传值的重要途径，因为GPU渲染屏幕中每个像素的过程都是互相并行且互不干扰的，所以传到shader里里面的uniform变量的值都是常量，只读且不能被shader程序修改

## varing

第五行varing变量则是指顶点着色器用来传给片元着色器的变量，在这段代码里就是将CPU传过来的纹理坐标从顶点着色器传递到片元着色器中

## 内置变量

**gl_Position**就是顶点着色器的一个内置变量，代表该顶点的位置，又如一些片元着色器的内置变量，**gl_FragColor**和**gl_FragCoord**分别代表该像素点的颜色和位置，除了内置变量以外，GLSL还有丰富的内置数学函数，诸如**smoothstep**，**clamp**等，后续的文章会详细介绍



## 绘制彩虹

好了，有了上面基本的一些概念，我们来探讨一下如何进行彩虹的绘制，需要注意到一个片元着色器的内置变量，gl_FragCoord，代表你即将要上色的顶点在屏幕中的位置，最终的原理也很简单，拿屏幕上点的位置除以当前屏幕的分辨率得到归一化后的坐标，然后绘制几个不同半径的半圆，然后根据顶点的位置，如果在几个半圆内的弧形中的话，我们就给他指定颜色

```c
#version 110
#ifdef GL_ES
precision highp float;
#endif
    
//将屏幕上的点的位置除以屏幕分辨率归一化，0.0～1.0之间
vec2 st = gl_FragCoord.xy / u_resolution;

//高中数学，三个不同半径的半圆方程
float y1 = sqrt(0.25 - (st.x-0.5) * (st.x - 0.5));
float y2 = sqrt(0.16 - (st.x-0.5) * (st.x - 0.5));
float y3 = sqrt(0.09 - (st.x-0.5) * (st.x - 0.5));

// 如果点位位于某两个圆中间，则指定颜色形成色带
if ((st.y >= y2 && st.y <= y1) || (st.y <= y1 && st.x >0.0 && st.x < 0.1) || (st.y <= y1 && st.x > 0.9)) {
    gl_FragColor = vec4(1.0,0.0,0.0,1.0);
} else if ((st.y > y3 && st.y < y2) || (st.y < y2 && st.x >= 0.1 && st.x < 0.2) ||  ) {
    gl_FragColor = vec4(1.0,1.0,0.0,1.0);
}
```



## Unity Shader



![image-20230903125300066](/images/posts/关于Unity-Shader/image-20230903125300066.png)

```
Shader "Unlit/NewUnlitShader"
{
   Properties
    {
         _Offset("彩虹显示偏移量",Range(0,1))=0
    }
    SubShader
    {
        Pass
        {
            CGPROGRAM  //CG语言开头

            //编译指令  着色器名称 着色器函数名称
            #pragma vertex vert  //顶点着色器
            #pragma fragment frag //片元着色器

            //声明外部属性
            fixed4 _MainColor;
            fixed _Offset;

            struct v2f
            {
            //投影空间坐标
               half4 clipPos:SV_POSITION ;
               //模型空间下的坐标
               half4 modelPos:TEXCOORD0;

            };
            //顶点函数：参数语义绑定模型空间坐标，返回值对应屏幕空间坐标
            v2f vert(half4 vertexPos:POSITION)
            {
            //返回的结构体对象
              v2f o;
             // 将顶点从模型空间转换为投影空间坐标
              o.clipPos=UnityObjectToClipPos(vertexPos);
              //将模型空间坐标暂存
              o.modelPos=vertexPos+fixed4(_Offset,_Offset,_Offset,0) ;
            //返回结果
               return o; 
            }
            fixed4 frag (v2f o):SV_TARGET
            {
                //return fixed4(1,0,0,1)  ; 
                return o.modelPos;
            }
            ENDCG   //---Cg语言结尾  
        }
    }
}
```

