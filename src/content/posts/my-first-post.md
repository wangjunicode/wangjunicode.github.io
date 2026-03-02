---
title: my first post
published: 2026-03-02
description: 博客搭建
tags: [Markdown, Blogging, Demo]
category: Examples
draft: false
---

# 2024-2026年个人博客搭建完整指南

## 1. 方案选型概览

### 1.1 技术背景与趋势

2024至2026年，个人博客技术方案经历了重大变革。传统的静态站点生成器（SSG）依然是主流选择，但新兴的"孤岛架构"和"无头CMS"方案正在快速崛起。对于曾经使用Hexo的用户而言，现代方案在构建速度、内容管理便捷性以及性能优化方面有了显著提升 [1]。

Astro凭借其革命性的"孤岛架构"成为2025年最受关注的框架，它允许在静态页面中按需注入交互组件，极大减少了客户端JavaScript负载 [6]。Hugo则以毫秒级的构建速度稳居高位，适合文章量大的技术博客 [2]。NotionNext作为"零代码"方案，让创作者可以直接在Notion中写作并自动发布，彻底摆脱了Git命令的束缚 [10]。

### 1.2 三大推荐方案对比

|对比维度|方案A：Astro+Cloudflare|方案B：NotionNext+Vercel|方案C：Hugo+GitHub Pages|
|:---|:---|:---|:---|
|技术栈|Astro+Tailwind CSS|Next.js+Notion API|Hugo(Go语言)|
|部署平台|Cloudflare Pages|Vercel|GitHub Pages|
|学习曲线|中等|极低|中等|
|构建速度|快|依赖API|极快(ms级)|
|年成本|0元(完全免费)|50-100元(域名费)|0元(完全免费)|
|适合人群|追求现代感的开发者|不想碰代码的创作者|追求极致稳定的技术博主|
|预计搭建时间|30-60分钟|15-30分钟|20-40分钟|

### 1.3 如何选择适合你的方案

根据你的具体需求，建议按以下原则选择：

- **选择方案A（Astro）**：如果你希望博客具有现代感的设计、优秀的性能评分，并且不介意学习一点新技术。这是原Hexo用户的最佳升级路径。
- **选择方案B（NotionNext）**：如果你讨厌折腾代码，希望随时随地用手机或电脑在Notion中写完即发布。写作体验是三个方案中最好的 [15]。
- **选择方案C（Hugo）**：如果你追求极致的构建速度和稳定性，或者已有大量Markdown格式的文章需要迁移。万级文章的博客，Hugo构建仅需数秒 [2]。

## 2. 方案A：Astro + Cloudflare Pages 完整教程（推荐）

本方案是2025-2026年最推荐的个人博客搭建方案，Astro的孤岛架构配合Cloudflare的全球CDN和无限免费带宽，能够打造性能接近满分的现代博客 [1][9]。预计完成时间：30-60分钟。

### 2.1 环境准备

在开始之前，需要安装以下开发环境：

**第一步：安装Node.js（18.x或20.x LTS版本）**

访问 https://nodejs.org 下载并安装LTS版本。安装完成后验证：

```bash
node -v    # 应显示 v18.x.x 或 v20.x.x
npm -v     # 应显示 9.x.x 或更高
```

**第二步：安装Git**

访问 https://git-scm.com 下载并安装。安装完成后配置用户信息：

```bash
git config --global user.name "你的GitHub用户名"
git config --global user.email "你的邮箱地址"
```

**第三步：安装VS Code（推荐）**

访问 https://code.visualstudio.com 下载安装，并安装以下扩展：
- Astro（官方扩展，语法高亮和智能提示）
- Tailwind CSS IntelliSense（样式提示）

### 2.2 创建Astro项目

打开终端，执行以下命令创建新项目：

```bash
# 创建Astro项目（推荐使用blog模板）
npm create astro@latest my-blog

# 交互式配置选项建议：
# - How would you like to start? → Use blog template
# - Do you plan to write TypeScript? → Yes (推荐)
# - Install dependencies? → Yes
# - Initialize a git repository? → Yes
```

创建完成后进入项目目录：

```bash
cd my-blog
npm run dev
```

此时访问 http://localhost:4321 即可看到博客预览。

### 2.3 安装推荐主题（Fuwari主题）

Fuwari是2025年最受欢迎的Astro博客主题，设计现代、动效精美。如果你更喜欢直接使用主题而非默认模板，可以按以下方式操作：

```bash
# 方式一：直接克隆Fuwari主题（推荐新手）https://github.com/saicaca/fuwari
# git clone https://github.com/saicaca/fuwari.git my-blog

npm create fuwari@latest
cd my-blog
npm install
npm run dev
```

```bash
# 方式二：使用AstroPaper主题（更简洁）
git clone https://github.com/satnaing/astro-paper.git my-blog
cd my-blog
npm install
npm run dev
```

**主题配置文件修改**（以Fuwari为例）：

编辑 `src/config.ts` 文件，修改以下关键配置：

```typescript
export const siteConfig = {
  title: '你的博客名称',
  subtitle: '你的博客副标题',
  lang: 'zh_CN',
  profile: {
    author: '你的名字',
    description: '一句话介绍自己',
    avatar: '/avatar.png'  // 将头像放到public目录
  }
}
```

### 2.4 本地开发与文章编写

Astro使用Markdown/MDX格式编写文章。文章存放在 `src/content/posts/` 目录下。

**创建新文章**：

在 `src/content/posts/` 目录下创建新的 `.md` 文件，例如 `my-first-post.md`：

```markdown
---
title: 我的第一篇博客
published: 2026-03-02
description: '这是文章描述'
tags: ['博客', '教程']
category: '技术'
draft: false
---

## 正文内容

这里写你的文章正文，支持标准Markdown语法。

### 代码高亮示例

\`\`\`javascript
console.log('Hello Astro!');
\`\`\`

### 图片引用

![图片描述](/images/example.png)
```

**本地预览命令**：

```bash
npm run dev      # 开发模式，支持热更新
npm run build    # 构建生产版本
npm run preview  # 预览构建结果
```

### 2.5 GitHub仓库创建与推送

**第一步：在GitHub创建新仓库**

1. 登录 https://github.com
2. 点击右上角 "+" → "New repository"
3. 仓库名建议：`my-blog` 或 `你的用户名.github.io`
4. 选择 Public，不要勾选初始化README
5. 点击 "Create repository"

**第二步：配置SSH密钥（如果尚未配置）**

```bash
# 生成SSH密钥
ssh-keygen -t ed25519 -C "你的邮箱地址"

# 查看公钥
cat ~/.ssh/id_ed25519.pub
```

将显示的公钥内容复制，然后：
1. 打开 GitHub → Settings → SSH and GPG keys
2. 点击 "New SSH key"
3. 粘贴公钥并保存

**第三步：推送代码到GitHub**

```bash
# 在项目目录下执行
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:你的用户名/my-blog.git
git push -u origin main
```

### 2.6 Cloudflare Pages部署

Cloudflare Pages提供无限免费带宽和自动SSL证书，是2025年最推荐的静态站点部署平台 [4][9]。

**第一步：注册Cloudflare账号**

访问 https://dash.cloudflare.com/sign-up 注册账号（免费）。

**第二步：创建Pages项目**

1. 登录Cloudflare Dashboard
2. 左侧菜单选择 "Workers & Pages"
3. 点击 "Create application" → "Pages" → "Connect to Git"
4. 授权并选择你的GitHub仓库
5. 配置构建设置：

|配置项|值|
|:---|:---|
|Framework preset|Astro|
|Build command|npm run build|
|Build output directory|dist|

6. 点击 "Save and Deploy"

等待2-3分钟，部署完成后会获得一个 `xxx.pages.dev` 的域名，即可访问你的博客。

**第三步：配置环境变量（如需要）**

在 Settings → Environment variables 中添加：
- `NODE_VERSION`：`18`（确保构建环境Node版本）

### 2.7 腾讯云域名绑定

如果你在腾讯云已有域名，按以下步骤绑定到Cloudflare Pages：

**第一步：在Cloudflare添加自定义域名**

1. 进入你的Pages项目 → Custom domains
2. 点击 "Set up a custom domain"
3. 输入你的域名（如 `blog.yourdomain.com`）
4. Cloudflare会显示需要配置的CNAME记录

**第二步：在腾讯云配置DNS解析**

1. 登录腾讯云控制台 → 云解析DNS
2. 选择你的域名 → 添加记录
3. 配置如下：

|主机记录|记录类型|记录值|TTL|
|:---|:---|:---|:---|
|blog|CNAME|xxx.pages.dev|600|
|@（根域名）|CNAME|xxx.pages.dev|600|

4. 等待DNS生效（通常5-10分钟）

**第三步：验证域名**

回到Cloudflare Pages的Custom domains页面，点击 "Activate domain"。Cloudflare会自动为你配置SSL证书。

### 2.8 常见问题与解决方案

|问题|原因|解决方案|
|:---|:---|:---|
|构建失败显示Node版本错误|Cloudflare默认Node版本过低|添加环境变量`NODE_VERSION=18`|
|样式丢失或页面空白|构建输出目录配置错误|确认Build output为`dist`|
|图片无法显示|路径错误|图片放在`public`目录，引用时使用`/images/xxx.png`|
|自定义域名无法访问|DNS未生效|等待10分钟，使用`nslookup 域名`检查解析|
|推送代码后未自动部署|Webhook未触发|在Cloudflare手动点击"Retry deployment"|

## 3. 方案B：NotionNext + Vercel 教程（零代码方案）

NotionNext是目前最流行的"无代码"博客方案，它利用Notion作为后台数据库，通过Next.js进行前端渲染。你只需要在Notion中写作，博客就会自动更新 [10][15]。预计完成时间：15-30分钟。

### 3.1 Notion账号准备与数据库模板复制

**第一步：注册Notion账号**

访问 https://www.notion.so 注册账号（免费版即可）。

**第二步：复制博客数据库模板**

1. 访问NotionNext官方模板：https://tanghh.notion.site/02ab3b8678004aa69e9e415905ef32a5
2. 点击右上角 "Duplicate"（复制）将模板复制到你的Notion空间
3. 复制后你会得到一个包含示例文章的数据库

**第三步：获取Notion页面ID**

1. 在浏览器中打开你复制的数据库页面
2. 复制URL中的页面ID，格式如下：
```
https://www.notion.so/你的空间/02ab3b8678004aa69e9e415905ef32a5
                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                              这部分就是PAGE_ID
```

**第四步：创建Notion Integration**

1. 访问 https://www.notion.so/my-integrations
2. 点击 "New integration"
3. 命名为 "NotionNext"，选择关联的空间
4. 创建后复制 "Internal Integration Token"（以`secret_`开头）

**第五步：授权Integration访问数据库**

1. 回到你的博客数据库页面
2. 点击右上角 "..." → "Add connections"
3. 选择刚创建的 "NotionNext" Integration

### 3.2 Fork NotionNext项目到GitHub

1. 访问 https://github.com/tangly1024/NotionNext
2. 点击右上角 "Fork" 按钮
3. Fork到你自己的GitHub账号下

### 3.3 配置环境变量

在部署前，你需要准备以下环境变量：

|变量名|值|说明|
|:---|:---|:---|
|NOTION_PAGE_ID|你的数据库页面ID|32位字符串|
|NOTION_ACCESS_TOKEN|secret_xxx...|Integration Token|

### 3.4 Vercel一键部署

**第一步：注册Vercel账号**

访问 https://vercel.com 使用GitHub账号登录（推荐）。

**第二步：导入项目**

1. 点击 "Add New..." → "Project"
2. 选择 "Import Git Repository"
3. 找到你Fork的NotionNext仓库，点击 "Import"

**第三步：配置环境变量**

在部署配置页面的 "Environment Variables" 部分添加：
- `NOTION_PAGE_ID`：你的页面ID
- `NOTION_ACCESS_TOKEN`：你的Integration Token

**第四步：部署**

点击 "Deploy"，等待2-3分钟即可完成部署。部署成功后会获得一个 `xxx.vercel.app` 域名。

### 3.5 腾讯云域名绑定到Vercel

**第一步：在Vercel添加域名**

1. 进入项目 → Settings → Domains
2. 输入你的域名（如 `blog.yourdomain.com`）
3. 点击 "Add"

**第二步：在腾讯云配置DNS**

Vercel会提供需要配置的记录，通常为：

|主机记录|记录类型|记录值|
|:---|:---|:---|
|blog|CNAME|cname.vercel-dns.com|

在腾讯云云解析中添加此记录即可。

### 3.6 日常写作流程

NotionNext的日常写作流程极其简单：

1. **打开Notion**（手机/电脑/网页均可）
2. **在数据库中新建页面**
3. **填写文章属性**：
   - title：文章标题
   - status：设为 "Published" 发布
   - type：设为 "Post"
   - date：发布日期
   - tags：文章标签
4. **编写正文内容**
5. **保存即发布**（Vercel会自动重新构建，通常1-2分钟生效）

> **提示**：如果更新不及时，可在Vercel项目中手动点击 "Redeploy" 触发更新。

## 4. 方案C：Hugo + GitHub Pages 教程（极简稳定方案）

Hugo是目前构建速度最快的静态站点生成器，单二进制文件执行，无需复杂的依赖环境。对于文章数量极多的技术博客，Hugo是最稳定可靠的选择 [2]。预计完成时间：20-40分钟。

### 4.1 Hugo安装

**Windows安装**：

```bash
# 方式一：使用winget（推荐）
winget install Hugo.Hugo.Extended

# 方式二：使用Scoop
scoop install hugo-extended

# 方式三：手动下载
# 访问 https://github.com/gohugoio/hugo/releases
# 下载 hugo_extended_xxx_windows-amd64.zip
# 解压后将hugo.exe所在目录添加到系统PATH
```

**macOS安装**：

```bash
brew install hugo
```

**Linux安装**：

```bash
# Debian/Ubuntu
sudo apt install hugo

# 或使用Snap
sudo snap install hugo --channel=extended
```

**验证安装**：

```bash
hugo version
# 应显示 hugo v0.xxx.x+extended ...
```

### 4.2 创建站点与主题安装

**第一步：创建Hugo站点**

```bash
hugo new site my-blog
cd my-blog
git init
```

**第二步：安装PaperMod主题（推荐）**

```bash
git submodule add https://github.com/adityatelange/hugo-PaperMod.git themes/PaperMod
```

**第三步：配置站点**

编辑项目根目录的 `hugo.toml`（或 `config.toml`）：

```toml
baseURL = 'https://你的用户名.github.io/'
languageCode = 'zh-cn'
title = '你的博客名称'
theme = 'PaperMod'

[params]
  author = '你的名字'
  description = '博客描述'
  defaultTheme = 'auto'
  ShowReadingTime = true
  ShowShareButtons = true
  ShowPostNavLinks = true
  ShowBreadCrumbs = true
  ShowCodeCopyButtons = true

[params.homeInfoParams]
  Title = '欢迎来到我的博客'
  Content = '一句话介绍'

[[params.socialIcons]]
  name = 'github'
  url = 'https://github.com/你的用户名'

[menu]
[[menu.main]]
  identifier = 'archives'
  name = '归档'
  url = '/archives/'
  weight = 10

[[menu.main]]
  identifier = 'tags'
  name = '标签'
  url = '/tags/'
  weight = 20
```

### 4.3 本地预览与文章编写

**创建新文章**：

```bash
hugo new posts/my-first-post.md
```

编辑 `content/posts/my-first-post.md`：

```markdown
---
title: "我的第一篇博客"
date: 2026-03-02
draft: false
tags: ["博客", "Hugo"]
categories: ["技术"]
---

## 正文内容

这里写你的文章正文...
```

**本地预览**：

```bash
hugo server -D
# 访问 http://localhost:1313
```

### 4.4 GitHub Actions自动部署配置

**第一步：创建GitHub仓库**

创建名为 `你的用户名.github.io` 的仓库（必须是这个格式）。

**第二步：创建GitHub Actions配置**

在项目中创建 `.github/workflows/deploy.yml`：

```yaml
name: Deploy Hugo site to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

defaults:
  run:
    shell: bash

jobs:
  build:
    runs-on: ubuntu-latest
    env:
      HUGO_VERSION: 0.124.0
    steps:
      - name: Install Hugo CLI
        run: |
          wget -O ${{ runner.temp }}/hugo.deb https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.deb \
          && sudo dpkg -i ${{ runner.temp }}/hugo.deb
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: recursive
      - name: Setup Pages
        id: pages
        uses: actions/configure-pages@v4
      - name: Build with Hugo
        env:
          HUGO_ENVIRONMENT: production
        run: hugo --minify --baseURL "${{ steps.pages.outputs.base_url }}/"
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./public

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

**第三步：启用GitHub Pages**

1. 进入仓库 Settings → Pages
2. Source选择 "GitHub Actions"

**第四步：推送代码**

```bash
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:你的用户名/你的用户名.github.io.git
git push -u origin main
```

推送后GitHub Actions会自动构建并部署，几分钟后即可通过 `https://你的用户名.github.io` 访问。

### 4.5 腾讯云域名绑定到GitHub Pages

**第一步：在腾讯云添加DNS解析**

|主机记录|记录类型|记录值|
|:---|:---|:---|
|blog|CNAME|你的用户名.github.io|
|@|CNAME|你的用户名.github.io|

**第二步：在GitHub配置自定义域名**

1. 仓库 Settings → Pages → Custom domain
2. 输入你的域名，点击Save
3. 勾选 "Enforce HTTPS"

### 4.6 CNAME文件配置避免被覆盖

为防止每次部署后CNAME配置丢失，需要在源码中创建CNAME文件：

```bash
# 在static目录下创建CNAME文件
echo "blog.yourdomain.com" > static/CNAME
```

Hugo构建时会自动将 `static` 目录的内容复制到 `public` 目录 [16]。

## 5. 腾讯云域名通用配置指南

无论选择哪个部署方案，腾讯云域名的配置流程都是类似的。本章提供通用的配置指南。

### 5.1 登录腾讯云控制台

1. 访问 https://console.cloud.tencent.com
2. 登录你的腾讯云账号
3. 在控制台搜索"云解析 DNS"或直接访问域名管理页面

### 5.2 DNS解析记录添加

**CNAME记录配置方法**：

1. 选择你要配置的域名
2. 点击"添加记录"
3. 填写以下信息：

|字段|说明|示例|
|:---|:---|:---|
|主机记录|子域名前缀，@表示根域名|blog / www / @|
|记录类型|选择CNAME|CNAME|
|记录值|目标地址|xxx.pages.dev / xxx.vercel.app / xxx.github.io|
|TTL|缓存时间|600（10分钟）|

**各平台对应记录值**：

|部署平台|CNAME记录值|
|:---|:---|
|Cloudflare Pages|你的项目名.pages.dev|
|Vercel|cname.vercel-dns.com|
|GitHub Pages|你的用户名.github.io|
|Netlify|你的项目名.netlify.app|

### 5.3 SSL证书说明

好消息是，以上三个部署平台都会**自动处理SSL证书**：

- **Cloudflare Pages**：自动签发并续签免费SSL证书
- **Vercel**：自动签发Let's Encrypt证书
- **GitHub Pages**：自动签发免费证书（需勾选Enforce HTTPS）

你无需手动申请或配置SSL证书。

### 5.4 生效时间与验证方法

DNS记录添加后，通常需要5-30分钟生效（取决于TTL设置和DNS缓存）。

**验证方法**：

```bash
# 方法一：使用nslookup检查解析
nslookup blog.yourdomain.com

# 方法二：使用dig命令（Linux/Mac）
dig blog.yourdomain.com CNAME

# 方法三：直接在浏览器访问域名
```

如果DNS已生效但仍无法访问，请检查部署平台的自定义域名配置是否完成。

## 6. 迁移建议与常见问题FAQ

### 6.1 原Hexo文章迁移方法

好消息是，Hexo、Hugo、Astro都使用Markdown格式的文章，迁移成本极低。

**迁移步骤**：

1. **复制文章文件**：将Hexo的 `source/_posts/` 目录下的所有 `.md` 文件复制到新框架的文章目录
   - Astro：`src/content/posts/`
   - Hugo：`content/posts/`
   - NotionNext：需要手动复制到Notion

2. **调整Front Matter**：不同框架的文章元数据格式略有差异

|Hexo|Astro|Hugo|
|:---|:---|:---|
|title|title|title|
|date|published/pubDate|date|
|categories|category|categories|
|tags|tags|tags|

3. **检查图片路径**：确保图片路径正确
   - 建议将图片统一放到 `public/images/` 或 `static/images/` 目录
   - 文章中使用 `/images/xxx.png` 格式引用

### 6.2 图片资源迁移建议

|方案|图片存放建议|优点|缺点|
|:---|:---|:---|:---|
|本地存储|项目的public/images目录|版本控制，永不丢失|仓库体积变大|
|图床服务|SM.MS、imgur等|仓库轻量|依赖第三方|
|对象存储|腾讯云COS、阿里云OSS|稳定可靠，CDN加速|有一定成本|

**推荐做法**：
- 个人博客图片不多时，直接放在项目 `public/images` 目录
- 图片较多时，使用对象存储配合CDN

### 6.3 各方案优缺点总结

|方案|优点|缺点|最适合|
|:---|:---|:---|:---|
|Astro+Cloudflare|性能极致、设计现代、免费无限流量|需要学习新语法|追求技术先进性的开发者|
|NotionNext+Vercel|零代码、写作体验好、随时随地发布|依赖Notion稳定性、国内访问偶有波动|不想折腾代码的内容创作者|
|Hugo+GitHub Pages|构建速度最快、极度稳定、完全免费|GitHub Pages国内访问可能较慢|文章量大、追求稳定的技术博主|

### 6.4 推荐的写作工具

|工具|特点|推荐场景|
|:---|:---|:---|
|Typora|所见即所得，体验最好|Windows/Mac本地写作|
|Obsidian|双链笔记，知识管理|构建个人知识体系|
|VS Code|程序员首选，Git集成|开发者日常写作|
|Notion|多端同步，协作方便|NotionNext方案专用|

### 6.5 常见问题FAQ

**Q1：部署后样式丢失怎么办？**
A：检查构建输出目录配置是否正确。Astro是 `dist`，Hugo是 `public`。

**Q2：自定义域名配置后显示证书错误？**
A：等待10-30分钟让平台自动签发SSL证书。如果长时间未解决，检查DNS解析是否正确。

**Q3：文章更新后网站没有变化？**
A：
- Cloudflare/Vercel/GitHub：推送代码后会自动触发重新部署
- NotionNext：可能需要等待缓存刷新或手动Redeploy

**Q4：GitHub Pages被墙无法访问怎么办？**
A：建议迁移到Cloudflare Pages或Vercel，两者国内访问相对稳定。

**Q5：如何提升博客SEO？**
A：
- 确保每篇文章有完整的title、description
- 配置站点地图（sitemap）
- 向Google Search Console提交站点

**Q6：Node.js版本错误导致构建失败？**
A：在部署平台添加环境变量 `NODE_VERSION=18` 或 `NODE_VERSION=20`。

## 参考文献

[1] 稀土掘金, 2025-12-01. 2025博客框架选择指南：Hugo、Astro、Hexo该选哪个？. https://juejin.cn/post/7578714735307849754

[2] 稀土掘金, 2025-12-14. 2025博客框架选择指南：Hugo、Astro、Hexo该选哪个？. https://imgeek.net/article/825369560

[4] 腾讯云, 2025-08-28. 静态网站托管哪家强？腾讯云CloudBase一键上线、全球加速. https://cloud.tencent.com/developer/article/2561128

[6] GitHub, 2026-01-07. 2025 年最火的前端项目出炉，No.1 易主！ #391. https://github.com/mqyqingfeng/Blog/issues/391

[9] 零基础AI编程指南, 2025-03-24. Cloudflare 部署指南. https://aimaker.dev/guide/getting-started/cloudflare

[10] Schemer.top, 2025-10-11. notion和建立网站. https://schemer.top/article/example-1

[15] 知乎专栏, 2025-06-27. 如何用Notion搭建个人博客网站？. https://zhuanlan.zhihu.com/p/1921844392844568499

[16] reuixiy, 2025-05-01. GitHub Pages 绑定个人域名，免Cloudflare 支持HTTPS. https://io-oi.me/tech/custom-domains-on-github-pages