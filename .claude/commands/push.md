帮我提交并推送代码。请按以下流程操作两个项目：

## 项目列表

1. **主项目**：`E:/python/共享剪贴板/CLIPBOARD-`（remote: github.com:wenrongruan/CLIPBOARD-.git）
2. **website 子项目**：`E:/python/共享剪贴板/CLIPBOARD-/website`（remote: github.com:wenrongruan/jlike.git，独立 Git 仓库）
3. **ai图片插件**: 'E:\python\chat_image_gen' (remote: git@github.com:wenrongruan/aladdinpic-app.git，独立 Git 仓库)

## 操作流程

对每个项目依次执行：

### 1. 检查状态
- 运行 `git status` 查看是否有未提交的修改（包括未跟踪的文件）
- 如果没有任何修改，跳过该项目

### 2. 提交
- 运行 `git diff` 和 `git diff --cached` 查看所有改动
- 根据改动内容生成中文 commit message（遵循 conventional commits 格式，如 `feat:`, `fix:`, `refactor:` 等）
- 将相关文件添加到暂存区（不要用 `git add -A`，按文件名添加）
- 每次修改代码后，同步更新相关文档和注释，特别是 CLAUDE.md
- 注意：不要提交 `.env`、credentials 等敏感文件
- 创建 commit，message 末尾附加 `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

### 3. 推送
- 提交成功后执行 `git push`
- 报告推送结果

### 4. 部署（仅 website 子项目）
- 如果 website 子项目本次有推送，SSH 到正式环境执行 `git pull`：
  - `ssh vps-90 "cd /www/wwwroot/www.jlike.com/jlike.com && git pull"`
- 报告 pull 结果

## 输出格式

完成后汇总报告每个项目的操作结果：
- 项目名称
- 是否有改动
- commit hash 和 message（如有提交）
- push 结果
