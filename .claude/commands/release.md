帮我把 `CLIPBOARD-` 主项目打一个新版本，并自动同步到 GitHub Release。

## 可选参数

- 无参数：当前 patch 号 +1（例如 `3.2.7` → `3.2.8`）
- `<X.Y.Z>`：直接指定版本号（例如 `/release 3.3.0`）
- `minor`：次版本号 +1，patch 归 0
- `major`：主版本号 +1，次版本号 / patch 归 0

## 前置条件（必须验证，失败即停）

1. 当前工作目录是 `E:/python/共享剪贴板/CLIPBOARD-`，`git remote get-url origin` 返回 `github.com:wenrongruan/CLIPBOARD-.git`
2. `gh auth status` 返回已登录
3. `git status` 中没有和本次发版无关的未提交改动——如果有，先 `/push` 把它们单独提上去再来打包
4. 目标 tag 不存在：`git tag -l v<new>` 为空；否则报错并停止

## 流程

### 1. 计算新版本号

- 读 `config.py` 的 `APP_VERSION`（形如 `"3.2.7"`）
- 根据用户参数（见上）算出 `<new>`，验证形如 `<int>.<int>.<int>`

### 2. 同步改 3 处版本号

- `config.py`：`APP_VERSION = "<new>"`
- `Info.plist`：两个 `<string>X.Y.Z</string>` 紧跟 `CFBundleVersion` / `CFBundleShortVersionString` 键（用 Edit 工具 `replace_all` 批量替换旧版本号即可）
- `build_macos.py`：`'CFBundleVersion': '<new>'` 和 `'CFBundleShortVersionString': '<new>'`

改完后 `git diff` 快速确认只这三个文件被动了。

### 3. 本地冒烟

- `python -m pytest tests/ -q -x` 跑快测，失败立即停下来把失败输出贴给用户，不要进行后续步骤
- `rm -rf dist/SharedClipboard.exe build/SharedClipboard`
- `python -m PyInstaller SharedClipboard.spec --noconfirm`——失败也停下来，贴出最后 40 行日志；缺依赖时提示用户 `pip install -r requirements.txt pynput`
- 成功后确认 `dist/SharedClipboard.exe` 存在且大小 > 50 MB

### 4. 提交并推 tag

- `git add config.py Info.plist build_macos.py`（精准 add，别用 `-A`）
- commit message：
  ```
  chore(release): v<new>

  Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
  ```
- 如果本次发版还带了别的改动（比如刚改完的 bug fix 还没提），建议改成：
  ```
  fix(xxx): <一句话说明>（v<new>）

  <正文>

  Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
  ```
  并把相关文件一起 add 进来
- `git push origin main`
- `git tag v<new>`
- `git push origin v<new>`——这一步会触发 `.github/workflows/build-macos.yml`，CI 会在 tag 上自动跑 `build-windows` / `build-macos` / `build-linux` 三个 job 再汇总成 `release` job 创建 GitHub Release 并上传产物

### 5. 即时补 Windows 产物到 Release

CI 跑完整流程要 8~15 分钟。为了让用户马上拿到 Windows 版本：

1. `gh release view v<new>` 检查 release 是否已被 CI 创建
   - 若返回 `release not found`：`gh release create v<new> --title "v<new>" --notes "<一句话发版说明>"` 先建一个
2. `gh release upload v<new> dist/SharedClipboard.exe --clobber` 把本地刚打的 Windows exe 传上去（`--clobber` 表示如果 CI 已经传过同名文件就覆盖）

### 6. 监控 CI 并汇报

- `gh run list --workflow "Build Apps" --branch v<new> --limit 1` 拿这次 tag 的 workflow run id
- 告诉用户：
  - release URL：`https://github.com/wenrongruan/CLIPBOARD-/releases/tag/v<new>`
  - Actions URL：`https://github.com/wenrongruan/CLIPBOARD-/actions/runs/<run_id>`
  - 本地 Windows exe 已即时补到 release 的消息
- **不要** `gh run watch` 去阻塞等它跑完，让用户自己看。如果用户要求等，再用 `gh run watch <run_id>`

## 失败回滚

- 如果 push main 成功但 push tag 失败：tag 还没发布，直接 `git tag -d v<new>` 删本地；提示用户说"版本号已 bump 并推 main，但 tag 未推，请手动复核"。
- 如果 tag 已推但 CI 失败：不要自动重试；通过 Actions 页面看失败原因，报告给用户让其决定是修问题再重打 tag 还是 `gh release delete v<new> --cleanup-tag`。
- 永远不要 `--force` push，永远不要自动删 tag（除非本地尚未 push）。

## 输出格式

完成后回一段包含以下字段的汇总：

- 旧版本号 → 新版本号
- commit hash
- tag 名
- release URL
- Actions URL
- 本地 exe 是否已即时上传
- 是否还有别的改动被一并带入本次 commit
