---
title: Python抓取网页所有链接及标题
published: 2019-09-04
description: "抓取网页的链接及标题，学学[Python](https://chegva.com/tag/python/)爬虫"
tags: [Python, 爬虫, 计算机基础]
category: 基础知识
draft: false
---

抓取网页的链接及标题，学学[Python](https://chegva.com/tag/python/)爬虫

- 抓取网页链接

```python
import requests
import sys
import re
from bs4 import BeautifulSoup
import prettytable as pt

def getHTMLText(url):
    '''
    此函数用于获取网页的html文档
    '''
    try:
        #获取服务器的响应内容，并设置最大请求时间为6秒
        res = requests.get(url, timeout = 6)
        #判断返回状态码是否为200
        res.raise_for_status()
        #设置该html文档可能的编码
       # res.encoding = res.apparent_encoding
       # print(res.encoding)
        res.encoding = 'utf-8'
        #返回网页HTML代码
        return res.text
    except:
        return '产生异常'

def main():
    '''
    主函数
    '''

    #目标网页，这个可以换成一个你喜欢的网站
    #url = 'https://chegva.com'

    url = sys.argv[1]
    demo = getHTMLText(url)

    #解析HTML代码
    soup = BeautifulSoup(demo, 'html.parser')

    #模糊搜索HTML代码的所有包含href属性的<a>标签
    a_labels = soup.find_all('a', attrs={'href':True})

    #获取所有<a>标签中的href对应的值，即超链接
    for a in a_labels:
        if(a.get('href').startswith("/")):
           tb.add_row([str(a.string), url+a.get('href')])
        else:
           tb.add_row([str(a.string), a.get('href')])
    print(tb)

    # 过滤pdf文件以markdown格式显示链接
    for a in a_labels:
        if (a.get('href').startswith("/")):
            if str(a.string).endswith('.pdf'):
                print("- [{}]({})".format(str(a.string)[:-4], url+a.get('href')))
        else:
            if str(a.string).endswith('.pdf'):
               print("- [{}]({})".format(str(a.string)[:-4], a.get('href')))    
    
    
if __name__ == "__main__":
    tb = pt.PrettyTable()
    tb.field_names = ["标题", "链接地址"]
    tb.padding_width = 0
    tb.align = 'l'
    tb.left_padding_width = 1
    tb.right_padding_width = 0
    main()
```

- **抓取网页外部链接和内部链接**

```python
from urllib.request import urlopen
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import re
import datetime
import random
import io
import os
import sys
from urllib  import request

pages = set()
random.seed(datetime.datetime.now())
#sys.stdout = io.TextIOWrapper(sys.stdout.buffer,encoding='gb18030')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
headers = {'User-Agent':'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:23.0) Gecko/20100101 Firefox/23.0'}

#获取页面所有内链的列表
def getInternalLinks(bsObj, includeUrl):
    includeUrl = urlparse(includeUrl).scheme+"://"+urlparse(includeUrl).netloc
    internalLinks = []
    #找出所有以“/”开头的链接
    for link in bsObj.findAll("a", href=re.compile("^(/|.*"+includeUrl+")")):
        if link.attrs['href'] is not None:
            if link.attrs['href'] not in internalLinks:
                if(link.attrs['href'].startswith("/")):
                    url = "{} | {}".format(link.string, includeUrl+link.attrs['href'])
                    internalLinks.append(url)
                    #internalLinks.append(includeUrl+link.attrs['href'])
                else:
                    url = "{} | {}".format(link.string, link.attrs['href'])
                    internalLinks.append(url)
                    #internalLinks.append(link.attrs['href'])
    return internalLinks

#获取页面所有外链的列表
def getExternalLinks(bsObj, excludeUrl):
    externalLinks = []
    #找出所有以“http”或者“www”开头且不包含当前URL的链接
    for link in bsObj.findAll("a", href=re.compile("^(http|www)((?!"+excludeUrl+").)*$")):
        if link.attrs['href'] is not None:
            if link.attrs['href'] not in externalLinks:
                #print(link)
                #print(link.string)
                url = "{} | {} ".format(link.string, link.attrs['href'])
                externalLinks.append(url)
    return externalLinks

def getRandomExternalLink(startingPage):
    req=request.Request(startingPage,headers=headers)
    html=urlopen(req)
    bsObj=BeautifulSoup(html.read(),"html.parser")
    externalLinks = getExternalLinks(bsObj, urlparse(startingPage).netloc)
    if len(externalLinks) == 0:
        print("没有外部链接，准备遍历整个网站")
        domain = urlparse(startingPage).scheme+"://"+urlparse(startingPage).netloc
        internalLinks = getInternalLinks(bsObj, domain)
        return getRandomExternalLink(internalLinks[random.randint(0,len(internalLinks)-1)])
    else:
        return externalLinks[random.randint(0, len(externalLinks)-1)]
        
def followExternalOnly(startingSite):
    externalLink = getRandomExternalLink(startingSite)
    print("随机外链是: "+externalLink)
    followExternalOnly(externalLink)
    
#收集网站上发现的所有外链列表
allExtLinks = set()
allIntLinks = set()
def getAllExternalLinks(siteUrl):
    #设置代理IP访问
   # proxy_handler=urllib.request.ProxyHandler({'http':'127.0.0.1:8001'})
   # proxy_auth_handler=urllib.request.ProxyBasicAuthHandler()
    #proxy_auth_handler.add_password('realm', '123.123.2123.123', 'user', 'password')
   # opener = urllib.request.build_opener(urllib.request.HTTPHandler, proxy_handler)
  #  urllib.request.install_opener(opener)
    req=request.Request(siteUrl,headers=headers)
    html=urlopen(req)
    bsObj=BeautifulSoup(html.read(),"html.parser")
    domain = urlparse(siteUrl).scheme+"://"+urlparse(siteUrl).netloc
    internalLinks = getInternalLinks(bsObj,domain)
    externalLinks = getExternalLinks(bsObj,domain)
    #收集外链
    for link in externalLinks:
        if link not in allExtLinks:
            allExtLinks.add(link)
            print("外部链接 | "+link)
    #收集内链
    print('---'*40)
    for link in internalLinks:
        if link not in allIntLinks:
            print("内部链接 | "+link)
            allIntLinks.add(link)
            
#followExternalOnly("http://bbs.3s001.com/forum-36-1.html")
#allIntLinks.add("http://bbs.3s001.com/forum-36-1.html" 

if __name__ == '__main__':
    hf = sys.argv[1]
    getAllExternalLinks(hf)
```

