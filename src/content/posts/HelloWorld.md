---
title: 博客搭建指南：Fuwari + GitHub Pages + Cloudflare
published: 2017-08-02
description: "使用 Fuwari 主题搭建 Astro 静态博客，部署到 GitHub Pages，并通过 Cloudflare Pages 实现自动构建部署的完整教程。"
tags: [博客搭建, Fuwari, Cloudflare, GitHub]
category: 工具
draft: false
encryptedKey: henhaoji123
---

## 技术栈

本博客使用以下技术栈搭建：

| 组件 | 技术 | 说明 |
|------|------|------|
| 框架 | [Astro](https://astro.build/) | 静态站点生成器 |
| 主题 | [Fuwari](https://github.com/saicaca/fuwari) | 简洁美观的博客主题 |
| 托管 | GitHub Pages | 代码仓库 + 静态托管 |
| 部署 | Cloudflare Pages | 自动构建，全球 CDN |
| 包管理 | pnpm | 快速、节省磁盘空间 |

## 快速开始

### 1. 安装环境

```bash
# 检查 Node.js 版本（需要 >= 18）
node -v

# 安装 pnpm
npm install -g pnpm
```

### 2. 创建项目

```bash
# 使用 Fuwari 模板创建博客
pnpm create fuwari@latest my-blog
cd my-blog

# 安装依赖
pnpm install
```

### 3. 本地开发

```bash
# 启动开发服务器
pnpm run dev
# 访问 http://localhost:4321

# 构建生产版本
pnpm run build

# 预览生产版本
pnpm run preview
```

### 4. 配置博客信息

编辑 `src/config.ts`：

```typescript
export const siteConfig: SiteConfig = {
    title: '你的博客名称',
    subtitle: '副标题',
    lang: 'zh_CN',
    themeColor: {
        hue: 250,
        fixed: false,
    },
    banner: {
        enable: true,
        src: 'assets/images/banner.png',
    },
    // ...
}
```

## 部署到 GitHub Pages + Cloudflare

### 1. 推送到 GitHub

```bash
git init
git add .
git commit -m "Init: setup Fuwari blog"
git branch -M main
git remote add origin https://github.com/你的用户名/你的用户名.github.io.git
git push -u origin main
```

### 2. 配置 Cloudflare Pages

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 进入 **Pages** → **Create a project** → **Connect to Git**
3. 选择你的 GitHub 仓库
4. 构建配置：
   - **Build command**: `pnpm run build`
   - **Build output directory**: `dist`
   - **Node.js version**: `18` 或更高

5. 保存后，每次 `git push` 都会自动触发重新部署 🎉

### 3. 自定义域名（可选）

在 Cloudflare Pages 项目设置中，添加自定义域名并配置 DNS 记录。

## 写博客

所有博客文章放在 `src/content/posts/` 目录下，使用 Markdown 格式：

```markdown
---
title: 文章标题
published: 2024-01-01
description: "文章摘要，显示在文章列表中"
tags: [标签1, 标签2]
category: 分类名称
draft: false
---

## 正文内容

在这里写你的博客内容...
```

## 常见问题

**Q: 推送后 Cloudflare 没有自动部署？**  
A: 检查 Cloudflare Pages 中 GitHub 的 webhook 是否正常，或手动在 Dashboard 触发部署。

**Q: 本地构建报错？**  
A: 确保 Node.js 版本 >= 18，且使用 pnpm 而非 npm/yarn 安装依赖。
