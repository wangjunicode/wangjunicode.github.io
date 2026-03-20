---
title: 六边形地图的生成算法
published: 2019-04-05
description: "六边形地图系列的第一部分。许多游戏，尤其是战略游戏，都常使用六边形的网格地图。包括《奇迹时代3》，《文明5》和《无尽传奇》等等"
tags: []
category: 基础知识
draft: false
---

六边形地图系列的第一部分。许多游戏，尤其是战略游戏，都常使用六边形的网格地图。包括《奇迹时代3》，《文明5》和《无尽传奇》等等



## 六边形网格

#### 为什么用六边形

相比于正方形网格，六边形网格的相邻格由八个变成了六个，并且都是在边上相邻。也就是说每个相邻格对于中间的单元格距离是一致的，这无疑简化了很多事情。

在开始之间，我们先定义六边形的大小。如下图，以边长10作为基准，所以圆心到每个角的距离也是10，因为六边形是由六个等边三角形组成的。我们把圆心到角的距离称作六边形的外径。

![image-20230905122300643](/images/posts/六边形地图的生成算法/image-20230905122300643.png)



#### 网格构建

- 六边形坐标

  ```csharp
  
  using UnityEngine;
  
  [System.Serializable]
  public struct HexCoordinates
  {
      [SerializeField]
      private int x, z;
  
      public int X
      {
          get { return x; }
  
      }
      public int Z
      {
          get { return z; }
      }
     
  
      public int Y
      {
          get
          {
              return -X - Z;
          }
      }
  
    
  
      public HexCoordinates(int x, int z)
      {
          this.x = x;
          this.z= z;
      }
  
      public static HexCoordinates FromOffsetCoordinates(int x, int z)
      {
          return new HexCoordinates(x - z / 2, z);
      }
  
      public override string ToString()
      {
          return "(" + X.ToString() + "," + Y.ToString()+","+ Z.ToString() + ")";
      }
  
      public string ToStringOnSpearateLines()
      {
          return X.ToString() + "\n"+ Y.ToString() +"\n" + Z.ToString();
      }
  
      public static HexCoordinates FromPosition(Vector3  position)
      {
          float x = position.x / (HexMetrics.innerRadius * 2);
          float y = -x;
          float offset = position.z / (HexMetrics.outerRadius * 3f);
          x -= offset;
          y -= offset;
  
          int iX = Mathf.RoundToInt(x);
          int iY = Mathf.RoundToInt(y);
          int iZ = Mathf.RoundToInt(-x - y);
  
          if(iX+iY+iZ!=0)
          {
              float dX = Mathf.Abs(x - iX);
              float dY = Mathf.Abs(y - iY);
              float dZ = Mathf.Abs(-x - y - iZ);
  
              if (dX > dY && dX > dZ)
              {
                  iX = -iY - iZ;
              }
              else if (dZ > dY)
              {
                  iZ = -iX - iY;
              }
          }
  
          return new HexCoordinates(iX, iZ);
      }
  }
  ```

  



- 六边形单元格

  ```csharp
  using System.Collections;
  using System.Collections.Generic;
  using UnityEngine;
  
  
  public class HexCell : MonoBehaviour
  {
      public HexCoordinates coordinates;
      public Color color;
  }
  ```

  

- 网格创建

  ```csharp
  using System.Collections;
  using System.Collections.Generic;
  using UnityEngine;
  using UnityEngine.UI;
  
  public class HexGrid : MonoBehaviour
  {
      public int width = 6;
      public int height = 6;
  
      public HexCell cellPrefab;
  
      public Text cellLabelPrefab;
  
      Canvas gridCanvas;
  
      HexMesh hexMesh;
  
     
  
      HexCell[] cells;
  
      private void Awake()
      {
          gridCanvas = GetComponentInChildren<Canvas>();
          hexMesh = GetComponentInChildren<HexMesh>();
  
          cells = new HexCell[width*height];
  
          
          for(int z=0,i=0; z<height;z++)
          {
              for(int x=0;x<width;x++)
              {
                  CreateCell(x, z, i++);
              }
          }
      }
      private void Start()
      {
          hexMesh.TriangulateAll(cells);
      }
  
      void CreateCell(int x,int z,int i)
      {
          Vector3 position;
          position.x = (x+z*0.5f-z/2) * (HexMetrics.innerRadius * 2f);
          position.y = 0f;
          position.z = z * (HexMetrics.outerRadius * 1.5f);
  
  
  
          HexCell cell = cells[i] = Instantiate(cellPrefab);
  
          cell.transform.SetParent(transform, false);
          cell.transform.localPosition = position;
  
          cell.coordinates = HexCoordinates.FromOffsetCoordinates(x, z);
          cell.color = Color.white;
  
          Text label = Instantiate(cellLabelPrefab);
          label.rectTransform.SetParent(gridCanvas.transform, false);
          label.rectTransform.anchoredPosition = new Vector2(position.x, position.z);
  
          label.text = cell.coordinates.ToStringOnSpearateLines();
  
      }
  
      public void ColorCell(Vector3 position,Color color)
      {
          position = transform.InverseTransformPoint(position);
          HexCoordinates coordinates = HexCoordinates.FromPosition(position);
          int index = coordinates.X + coordinates.Z * width + coordinates.Z / 2;
          HexCell cell = cells[index];
          cell.color = color;
          hexMesh.TriangulateAll(cells);
  
          Debug.Log("touched at " + coordinates.ToString());
      }
  
  
  }
  ```

  

## A星寻路

### 需求

给定六边形网格的一个起点和一个终点，函数能够返回从起点到终点的通路经过哪些六边形。

### 实现

- 开启列表：需要考虑的节点都会被放到开启列表中，刚开始的时候开启列表只有起点一个节点，然后根据节点的相邻节点集，会逐渐把附近的节点都加到开启列表中。

- 关闭列表：所有不在考虑的节点的集合

- 估值：每个节点都做估值，估算值F = G + H:

  G： 从起点，沿着产生的路径，移动到网格上指定方格的移动耗费。在这里，我们认为相邻的六边形，移动消耗是1

  H：从网格上那个方格移动到终点B的预估移动耗费。这经常被称为启发式的，可因为它只是个猜测。这个H值的估算方式有很多种，我们暂时使用两个节点的直线距离



```csharp
public static List<Hexagon> searchRoute(Hexagon thisHexagon, Hexagon targetHexagon)
    {
        Hexagon nowHexagon = thisHexagon;
        nowHexagon.reset();

        openList.Add(nowHexagon);
        bool finded = false;
        while (!finded)
        {
            openList.Remove(nowHexagon);//将当前节点从openList中移除  
            closeList.Add(nowHexagon);//将当前节点添加到关闭列表中  
            Hexagon[] neighbors = nowHexagon.getNeighborList();//获取当前六边形的相邻六边形  
            //print("当前相邻节点数----" + neighbors.size());  
            foreach (Hexagon neighbor in neighbors)
            {
                if (neighbor == null) continue;

                if (neighbor == targetHexagon)
                {//找到目标节点  
                    //System.out.println("找到目标点");  
                    finded = true;
                    neighbor.setFatherHexagon(nowHexagon);
                }
                if (closeList.Contains(neighbor) || !neighbor.canPass())
                {//在关闭列表里  
                    //print("无法通过或者已在关闭列表");  
                    continue;
                }

                if (openList.Contains(neighbor))
                {//该节点已经在开启列表里  
                    //print("已在开启列表，判断是否更改父节点");  
                    float assueGValue = neighbor.computeGValue(nowHexagon) + nowHexagon.getgValue();//计算假设从当前节点进入，该节点的g估值  
                    if (assueGValue < neighbor.getgValue())
                    {//假设的g估值小于于原来的g估值  
                        openList.Remove(neighbor);//重新排序该节点在openList的位置  
                        neighbor.setgValue(assueGValue);//从新设置g估值  
                        openList.Add(neighbor);//从新排序openList。  
                    }
                }
                else
                {//没有在开启列表里  
                    //print("不在开启列表，添加");  
                    neighbor.sethValue(neighbor.computeHValue(targetHexagon));//计算好他的h估值  
                    neighbor.setgValue(neighbor.computeGValue(nowHexagon) + nowHexagon.getgValue());//计算该节点的g估值（到当前节点的g估值加上当前节点的g估值）  
                    openList.Add(neighbor);//添加到开启列表里  
                    neighbor.setFatherHexagon(nowHexagon);//将当前节点设置为该节点的父节点  
                }
            }

            if (openList.Count <= 0)
            {
                //print("无法到达该目标");  
                break;
            }
            else
            {
                nowHexagon = openList[0];//得到f估值最低的节点设置为当前节点  
            }
        }
        openList.Clear();
        closeList.Clear();

        List<Hexagon> route = new List<Hexagon>();
        if (finded)
        {//找到后将路线存入路线集合  
            Hexagon hex = targetHexagon;
            while (hex != thisHexagon)
            {
                route.Add(hex);//将节点添加到路径列表里  

                Hexagon fatherHex = hex.getFatherHexagon();//从目标节点开始搜寻父节点就是所要的路线  
                hex = fatherHex;
            }
            route.Add(hex);


        }
        route.Reverse();
        return route;
        //      resetMap();  
    }
```

