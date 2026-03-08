---
title: Hello World
published: 2017-08-02
description: 部署框架（持续迭代...）
tags: [Markdown, Blogging, Demo]
category: Examples
draft: false
---

# Fuwari & Cloudflare

```bath
node -v
git -v
pnpm create fuwari@latest my-blog
cd my-blog
npm install
git add .
git commit -m "Init"
git branch -M main
git remote add origin https://github.com/wangjunicode/wangjunicode.github.io.git
git push -u origin main
pnpm run dev
pnpm run build
git push -u origin main
```