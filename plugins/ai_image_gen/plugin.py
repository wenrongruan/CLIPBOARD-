"""
AI 图片生成插件
启动外部 chat_image_gen 应用，文字内容作为提示词，图片内容作为附件
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ContentType, TextClipboardItem, ImageClipboardItem


# chat_image_gen 定位顺序：
#   1. 环境变量 CHAT_IMAGE_GEN_DIR（用户/管理员显式覆盖）
#   2. 应用配置目录下 plugin 专属 config.json (由 UI 设置)
#   3. 相邻目录候选：仓库同级 ../chat_image_gen、父级 E:/python/chat_image_gen（开发机兜底）
# Why: 旧版本硬编码 "E:\\python\\chat_image_gen" 分发给任何其他用户均 100% 不可用。
def _candidate_dirs():
    env = os.environ.get("CHAT_IMAGE_GEN_DIR")
    if env:
        yield Path(env)

    # 插件 config.json
    try:
        from config import get_config_dir
        cfg_path = Path(get_config_dir()) / "plugins" / "ai_image_gen.json"
        if cfg_path.exists():
            import json
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            custom = data.get("chat_image_gen_dir")
            if custom:
                yield Path(custom)
    except Exception:
        logger.debug("读取 ai_image_gen 插件配置失败", exc_info=True)

    here = Path(__file__).resolve()
    # plugins/ai_image_gen/plugin.py -> 仓库根 == here.parents[2]
    repo_root = here.parents[2]
    yield repo_root.parent / "chat_image_gen"
    yield repo_root.parent.parent / "chat_image_gen"


def _locate_chat_image_gen():
    """返回 (目录, 入口脚本)；定位失败返回 (None, None)。"""
    for cand in _candidate_dirs():
        try:
            script = cand / "chat_image_gen.py"
            if script.exists():
                return cand, script
        except OSError:
            continue
    return None, None


def _schedule_temp_cleanup(paths: list[str], delay_seconds: int = 60) -> None:
    """启动 daemon 线程，在 delay 后删除临时文件。
    Why: subprocess.Popen 不等待，子进程读完临时文件就不再需要；不清理则
    每次 AI 生图都会在系统 temp 目录留一份副本（含完整剪贴板内容），
    长期运行会泄漏隐私。daemon 线程随主进程退出而终止。
    """
    if not paths:
        return

    def _cleanup() -> None:
        time.sleep(delay_seconds)
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    threading.Thread(target=_cleanup, daemon=True, name="ai_temp_cleanup").start()


def _get_temp_dir() -> str:
    """返回本插件写临时文件使用的目录。
    Why: Windows 下系统 %TEMP%（通常 C:\\Users\\...\\AppData\\Local\\Temp）对同
    机本用户所有进程可读；落在这里的剪贴板副本可能被同账户其他进程枚举读取。
    改用应用私有目录 %LOCALAPPDATA%\\SharedClipboard\\Temp，由 Windows NTFS
    默认 ACL 仅授权当前用户与 SYSTEM。非 Windows 平台保持 tempfile 默认行为
    （后续仍显式 chmod 0600 保证私密）。
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        priv_dir = os.path.join(base, "SharedClipboard", "Temp")
        try:
            os.makedirs(priv_dir, exist_ok=True)
        except OSError:
            return tempfile.gettempdir()
        return priv_dir
    return tempfile.gettempdir()


def _find_python() -> str:
    """找到系统 Python 解释器路径（兼容 PyInstaller 打包环境）"""
    # 非打包环境直接用 sys.executable
    if not getattr(sys, 'frozen', False):
        return sys.executable
    # 打包环境：从 PATH 中找 python
    python = shutil.which("python") or shutil.which("python3")
    if python:
        return python
    # 兜底：按平台给出常见安装路径
    import platform
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/opt/homebrew/bin/python3",
            "/opt/homebrew/bin/python3.12",
            "/opt/homebrew/bin/python3.11",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
    elif system == "Linux":
        candidates = ["/usr/bin/python3"]
    else:
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
        ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return "python"


class AIImageGenPlugin(PluginBase):

    def get_id(self):
        return "ai_image_gen"

    def get_name(self):
        return "AI 图片生成"

    def get_description(self):
        return "打开 AI 图片生成工具，文字作为提示词，图片作为附件"

    def get_actions(self):
        return [
            PluginAction(
                action_id="open_app",
                label="AI 生图",
                icon="🎨",
                supported_types=[ContentType.TEXT, ContentType.IMAGE],
            ),
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id == "open_app":
            return self._open_app(item, progress_callback)
        return PluginResult(success=False, error_message="未知操作")

    def _open_app(self, item, progress_callback):
        """启动 chat_image_gen 应用"""
        chat_dir, chat_script = _locate_chat_image_gen()
        if chat_script is None:
            return PluginResult(
                success=False,
                error_message=(
                    "找不到 AI 图片工具（chat_image_gen）。"
                    "请设置环境变量 CHAT_IMAGE_GEN_DIR 或在插件配置 "
                    "ai_image_gen.json 中指定 chat_image_gen_dir。"
                ),
            )

        if progress_callback:
            progress_callback(50, "正在启动 AI 图片工具...")

        # 构建启动参数
        python = _find_python()
        cmd = [python, str(chat_script)]

        # 通过 auth.json 传递登录态，避免 token 出现在命令行中被同机进程窥探
        child_env = os.environ.copy()
        cloud_client = self.get_cloud_client()
        if cloud_client:
            base_url = getattr(cloud_client, "base_url", None)
            if base_url:
                cmd += ["--cloud-url", base_url]
            auth_path = Path.home() / ".shared_clipboard" / "auth.json"
            if auth_path.exists():
                child_env["SHARED_CLIPBOARD_AUTH_FILE"] = str(auth_path)
                logger.info("使用 auth.json 传递登录态: %s", auth_path)
            else:
                logger.warning("未找到 auth.json，子进程可能无法识别登录态: %s", auth_path)

        temp_files = []
        temp_dir = _get_temp_dir()  # Windows 下走 %LOCALAPPDATA% 私有子目录
        try:
            if isinstance(item, TextClipboardItem) and item.text_content:
                # 文字内容 → 写入临时文件后以 --init-prompt-file 传递。
                # Why: 直接 --init-prompt <text> 会使剪贴板内容（可能含密码、token）
                # 出现在同机可枚举的进程参数列表中。
                tf = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="clipboard_prompt_",
                    encoding="utf-8", delete=False, dir=temp_dir,
                )
                tf.write(item.text_content)
                tf.close()
                temp_files.append(tf.name)
                try:
                    if os.name == "posix":
                        os.chmod(tf.name, 0o600)
                except OSError:
                    pass
                cmd += ["--init-prompt-file", tf.name]

            elif isinstance(item, ImageClipboardItem) and item.image_data:
                # 图片内容 → 保存临时文件，作为附件
                temp_file = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="clipboard_img_", delete=False,
                    dir=temp_dir,
                )
                temp_file.write(item.image_data)
                temp_file.close()
                temp_files.append(temp_file.name)
                try:
                    if os.name == "posix":
                        os.chmod(temp_file.name, 0o600)
                except OSError:
                    pass
                cmd += ["--init-image", temp_file.name]

            else:
                return PluginResult(success=False, error_message="无可用内容")

            # 启动外部进程（不等待）
            subprocess.Popen(
                cmd,
                cwd=str(chat_dir),
                env=child_env,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )

            # 子进程已开始读取临时文件；5 分钟后清理足够覆盖启动+读取窗口
            _schedule_temp_cleanup(list(temp_files))

            # Why: action=NONE 表示不触碰剪贴板/UI，text_content 不会被消费；
            # 传提示串会让调用方误以为应当回填剪贴板，导致语义不一致。
            return PluginResult(
                success=True,
                action=PluginResultAction.NONE,
                text_content="",
            )

        except Exception as e:
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return PluginResult(success=False, error_message=f"启动失败: {e}")
