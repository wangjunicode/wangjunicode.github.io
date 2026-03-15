---
title: 关于游戏-敏感词的过滤之DFA算法
published: 2023-09-13
description: "对于一个游戏，如果有聊天功能，那么我们就会希望我们的聊天系统能够对玩家的输入进行判断，如果玩家的输入中含有一些敏感词汇，那么我们就禁止玩家发送聊天，或者把敏感词"
tags: []
category: 基础知识
draft: false
---

对于一个游戏，如果有聊天功能，那么我们就会希望我们的聊天系统能够对玩家的输入进行判断，如果玩家的输入中含有一些敏感词汇，那么我们就禁止玩家发送聊天，或者把敏感词转换为 * 来替换。


## 为什么要使用 DFA 算法

设我们已经有了一个敏感词词库(从相关部门获取到的，或者网上找来的)，那么我们最容易想到的过滤敏感词的方法就是：
遍历整个敏感词库，拿到敏感词，再判断玩家输入的字符串中是否有该敏感词，如果有就把敏感词字符替换为 *

但这样的方法，我们需要遍历整个敏感词库，并且对玩家输入的字符串进行替换。而整个敏感词库中一般会有上千个字符串。而玩家聊天输入的字符串一般也就 20~30 个字符。
因此，这种方法的效率是非常低的，无法应用到真实的开发中。

而使用 DFA 算法就可以实现高效的敏感词过滤。使用 DFA 算法，我们只需要遍历一遍玩家输入的字符串即可将所有存在的敏感词进行替换。

## DFA 算法原理

DFA 算法是通过提前构造出一个 树状查找结构(实际上应该说是一个 森林)，之后根据输入在该树状结构中就可以进行非常高效的查找。

设我们有一个敏感词库，词酷中的词汇为：
我爱你
我爱他
我爱她
我爱你呀
我爱他呀
我爱她呀
我爱她啊

那么就可以构造出这样的树状结构：

![image-20230913170556710](/images/posts/关于游戏-敏感词的过滤之DFA算法/image-20230913170556710.png)



设玩家输入的字符串为：白菊我爱你呀哈哈哈

我们遍历玩家输入的字符串 str，并设指针 i 指向树状结构的根节点，即最左边的空白节点：
str[0] = ‘白’ 时，此时 tree[i] 没有指向值为 ‘白’ 的节点，所以不满足匹配条件，继续往下遍历
str[1] = ‘菊’，同样不满足匹配条件，继续遍历
str[2] = ‘我’，此时 tree[i] 有一条路径连接着 ‘我’ 这个节点，满足匹配条件，i 指向 ‘我’ 这个节点，然后继续遍历
str[3] = ‘爱’，此时 tree[i] 有一条路径连着 ‘爱’ 这个节点，满足匹配条件，i 指向 ‘爱’，继续遍历
str[4] = ‘你’，同样有路径，i 指向 ‘你’，继续遍历
str[5] = ‘呀’，同样有路径，i 指向 ‘呀’
此时，我们的指针 i 已经指向了树状结构的末尾，即此时已经完成了一次敏感词判断。我们可以用变量来记录下这次敏感词匹配开始时玩家输入字符串的下标，和匹配结束时的下标，然后再遍历一次将字符替换为 * 即可。
结束一次匹配后，我们把指针 i 重新指向树状结构的根节点处。
此时我们玩家输入的字符串还没有遍历到头，所以继续遍历：
str[6] = ‘哈’，不满足匹配条件，继续遍历
str[7] = ‘哈’ …
str[8] = ‘哈’ …

可以看出我们遍历了一次玩家输入的字符串，就找到了其中的敏感词汇。

而在这一段标题的下面，我说 DFA 算法一开始构造的结构实际上算是一种森林，因为对于一个更完整的敏感词库而言，其构造出来的结构是这样的：

![image-20230913171231769](/images/posts/关于游戏-敏感词的过滤之DFA算法/image-20230913171231769.png)



如果不看该结构的根节点，即那个空白节点，那么就可以看作是由一个个树结构组成的森林。

理解了 DFA 算法是如何匹配过滤词的，接下来我们开始从代码层面来探讨如何根据敏感词库构造出这样的森林结构。

## DFA 算法 森林结构的构造

不论是树，还是森林，都是由一个个节点构成的，因此我们来探讨该结构中的节点应该存储哪些信息。

按照正常的树结构来说，节点结束存储自身的值，和 与其连接的子节点的指针。

但对于 DFA 算法的结构，子节点的数量一开始我们是不确定的。所以，我们可以用一个 List 来存储 所以子节点的指针，但是这样子的话，我们在匹配时进行查找路径就需要遍历整个 List，这样子效率是比较慢的。

为了达到 O(1) 的查找效率，我们可以使用哈希表来存储子节点的指针。

我们还可以直接用 哈希表来作为森林的入口节点：

该哈希表中存放着 一系列 Key 为 不同的敏感词开头字符 Value 为 表示该字符的节点 的键值对

并且因为哈希表可以存放不同类型对象的特点(只要继承自 object)，我们还可以存放可一个 Key 为 ‘IsEnd’ Value 为 0 的键值对。 Value 为 0 表示当前节点不为结构的末尾， Value 为 1 表示当前节点为结构的末尾。

那么对于结构中的其它节点，同样可以用哈希表来构造。 对于该节点表示的字符，我们在其父节点中包含的键值对中已经存储了(因为我们的结构最终有一个空白根节点，其里面的键值对，Key 存储了敏感词汇的开头字符， Value 就又是一个哈希表 即其子节点)

并且每个节点，也就是哈希表，里面也存储一个 Kye 为 “isEnd” Value 为 0/1 的键值对。 然后也存储了一系列的 Key 为其子节点表示的字符， Value 为其子节点(哈希表) 的键值对。

我们再来举个具体例子表述：

设有这样的结构：

![image-20230913171318154](/images/posts/关于游戏-敏感词的过滤之DFA算法/image-20230913171318154.png)



该结构最开始就是其空白根节点，即哈希表，我们设其为 map

那么，对于 “我爱你呀” 这个敏感词，其查找过程就为：
map[‘我’][‘爱’][‘你’][‘呀’][‘IsEnd’] == 1

经过以上分析，我们就可以得出大概地代码构造该结构的过程：

1、创建一个哈希表，作为该结构的空白根节点

2、遍历敏感词词库，得到一个敏感词字符串

3、遍历敏感词字符串，得到一个当前遍历字符

4、在树结构中查找是否已经包含了当前遍历字符，如果包含则直接走到树结构中已经存在的这个节点，然后继续向下遍历字符。

查找过程为：

对于敏感词的第一个字符串而言：

indexMap = map // 相当于指向树结构节点的指针

if(indexMap.ContainsKey(‘c’)) indexMap = indexMap[‘c’]

这样，我们的 indexMap 相当于一个指针，就指向了树结构中已经存在了的相同节点

对于后面的字符也是同样的：

if(indexMap.ContainsKye(‘c’)) indexMap = indexMap[‘c’]

如果树结构中不存在，或者是当前指针指向的节点，其所有子节点都没有表示当遍历到的字符，则我们就需要创建一个子节点，即添加一个键值对，其 Key 为当前遍历到的字符， Value 为新建一个哈希表。

5、判断当前遍历的字符，是否是当前字符串的最后一个。如果是 则添加键值对 Key 为 “IsEnd” Value 为 1。 如果不是，则添加键值对 Key 为 “IsEnd” Value 为 0。

对于 DFA 算法的结构构造论述到此完毕，接下来给出构造代码(使用 C# 实现)。

## DFA 算法结构初始化构造的代码

```csharp
private Hashtable map;
private void InitFilter(List<string> words)
{
    map = new Hashtable(words.Count);
    for (int i = 0; i < words.Count; i++)
    {
        string word = words[i];
        Hashtable indexMap = map;
        for (int j = 0; j < word.Length; j++)
        {
            char c = word[j];
            if (indexMap.ContainsKey(c))
            {
                indexMap = (Hashtable)indexMap[c];
            }
            else
            {
                Hashtable newMap = new Hashtable();
                newMap.Add("IsEnd", 0);
                indexMap.Add(c, newMap);
                indexMap = newMap;
            }
            if (j == word.Length - 1)
            {
                if (indexMap.ContainsKey("IsEnd")) indexMap["IsEnd"] = 1;
                else indexMap.Add("IsEnd", 1);
            }
        }
    }
}
```

## DFA 算法查找过程

DFA 算法查找过程的原理在上面其实已经讨论过，也举了例子，并且查找过程其实与初始化构造结构的过程有些相似之处。所以这里不做赘述，直接给出代码。

## DFA 算法查找过程的代码实现

```csharp
private int CheckFilterWord(string txt, int beginIndex)
{
    bool flag = false;
    int len = 0;
    Hashtable curMap = map;
    for (int i = beginIndex; i < txt.Length; i++)
    {
        char c = txt[i];
        Hashtable temp = (Hashtable)curMap[c];
        if (temp != null)
        {
            if ((int)temp["IsEnd"] == 1) flag = true;
            else curMap = temp;
            len++;
        }
        else break;
    }
    if (!flag) len = 0;
    return len;
}
public string SerachFilterWordAndReplace(string txt)
{
    int i = 0;
    StringBuilder sb = new StringBuilder(txt);
    while (i < txt.Length)
    {
        int len = CheckFilterWord(txt, i);
        if (len > 0)
        {
            for (int j = 0; j < len; j++)
            {
                sb[i + j] = '*';
            }
            i += len;
        }
        else ++i;
    }
    return sb.ToString();
}
```