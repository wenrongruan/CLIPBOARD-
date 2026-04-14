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
from pathlib import Path

logger = logging.getLogger(__name__)

from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ContentType

# chat_image_gen.py 的路径
CHAT_IMAGE_GEN_DIR = r"E:\python\chat_image_gen"
CHAT_IMAGE_GEN_SCRIPT = os.path.join(CHAT_IMAGE_GEN_DIR, "chat_image_gen.py")


def _find_python() -> str:
    """找到系统 Python 解释器路径（兼容 PyInstaller 打包环境）"""
    # 非打包环境直接用 sys.executable
    if not getattr(sys, 'frozen', False):
        return sys.executable
    # 打包环境：从 PATH 中找 python
    python = shutil.which("python") or shutil.which("python3")
    if python:
        return python
    # 兜底：常见安装路径
    for candidate in [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
    ]:
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
        if not os.path.exists(CHAT_IMAGE_GEN_SCRIPT):
            return PluginResult(
                success=False,
                error_message=f"找不到 AI 图片工具: {CHAT_IMAGE_GEN_SCRIPT}",
            )

        if progress_callback:
            progress_callback(50, "正在启动 AI 图片工具...")

        # 构建启动参数
        python = _find_python()
        cmd = [python, CHAT_IMAGE_GEN_SCRIPT]

        # 通过 auth.json 传递登录态，避免 token 出现在命令行中被同机进程窥探
        child_env = os.environ.copy()
        cloud_client = self.get_cloud_client()
        if cloud_client:
            base_url = getattr(cloud_client, "_base_url", None)
            if base_url:
                cmd += ["--cloud-url", base_url]
            auth_path = Path.home() / ".shared_clipboard" / "auth.json"
            if auth_path.exists():
                child_env["SHARED_CLIPBOARD_AUTH_FILE"] = str(auth_path)
                logger.info("使用 auth.json 传递登录态: %s", auth_path)
            else:
                logger.warning("未找到 auth.json，子进程可能无法识别登录态: %s", auth_path)

        temp_file = None
        try:
            if item.content_type == ContentType.TEXT and item.text_content:
                # 文字内容 → 作为提示词
                cmd += ["--init-prompt", item.text_content]

            elif item.content_type == ContentType.IMAGE and item.image_data:
                # 图片内容 → 保存临时文件，作为附件
                temp_file = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="clipboard_img_", delete=False
                )
                temp_file.write(item.image_data)
                temp_file.close()
                cmd += ["--init-image", temp_file.name]

            else:
                return PluginResult(success=False, error_message="无可用内容")

            # 启动外部进程（不等待）
            subprocess.Popen(
                cmd,
                cwd=CHAT_IMAGE_GEN_DIR,
                env=child_env,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )

            return PluginResult(
                success=True,
                action=PluginResultAction.NONE,
                text_content="已启动 AI 图片工具",
            )

        except Exception as e:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except OSError:
                    pass
            return PluginResult(success=False, error_message=f"启动失败: {e}")
