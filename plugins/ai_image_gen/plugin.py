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

        # 传递云端认证信息（同时传 refresh_token，子进程可自行刷新）
        cloud_client = self.get_cloud_client()
        if cloud_client:
            access_token, refresh_token = cloud_client.get_tokens()
            base_url = cloud_client._base_url
            if base_url and access_token:
                cmd += ["--cloud-url", base_url, "--cloud-token", access_token]
                if refresh_token:
                    cmd += ["--cloud-refresh", refresh_token]

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
