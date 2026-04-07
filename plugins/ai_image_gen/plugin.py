"""
AI 图片生成插件
通过 CLIPBOARD- 云端代理调用 Gemini/万相 AI 生成图片
"""

import base64
import os
import subprocess
import sys
import uuid

from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, ContentType

# chat_image_gen 项目默认路径
DEFAULT_CHAT_IMAGE_GEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "..", "chat_image_gen"
)


class AIImageGenPlugin(PluginBase):

    def get_id(self):
        return "ai_image_gen"

    def get_name(self):
        return "AI 图片生成"

    def get_description(self):
        return "使用 Gemini / 万相 AI 从文本生成图片"

    def get_actions(self):
        return [
            PluginAction(
                action_id="quick_generate",
                label="AI 生图",
                icon="🎨",
                supported_types=[ContentType.TEXT],
            ),
            PluginAction(
                action_id="open_studio",
                label="打开生图工作台",
                icon="🖼️",
                supported_types=[ContentType.TEXT, ContentType.IMAGE],
            ),
        ]

    def execute(self, action_id, item, progress_callback=None, cancel_check=None):
        if action_id == "quick_generate":
            return self._quick_generate(item, progress_callback, cancel_check)
        elif action_id == "open_studio":
            return self._open_studio(item)
        return PluginResult(success=False, error_message="未知操作")

    def _quick_generate(self, item, progress_callback, cancel_check):
        """快速生图：取剪贴板文本作为 prompt，调用云端 API 生成一张图。"""
        if not item.text_content:
            return PluginResult(success=False, error_message="无文本内容")

        cloud_client = self._get_cloud_client()
        if not cloud_client:
            return PluginResult(success=False, error_message="未登录 CLIPBOARD- 账户")

        # 检查余额
        if progress_callback:
            progress_callback(10, "正在检查余额...")

        try:
            balance_data = cloud_client.get_balance()
            available = balance_data.get("balance", 0) - balance_data.get("frozen", 0)
            if available < 0.05:
                return PluginResult(success=False, error_message=f"积分余额不足 (${available:.4f})，请先充值")
        except Exception as e:
            return PluginResult(success=False, error_message=f"余额查询失败: {e}")

        if cancel_check and cancel_check():
            return PluginResult(success=False, cancelled=True, error_message="已取消")

        # 生成
        if progress_callback:
            progress_callback(30, "正在生成图片...")

        config = self.get_config()
        provider = config.get("default_provider", "gemini")
        task_uuid = str(uuid.uuid4())

        model = ("gemini-3.1-flash-image-preview" if provider == "gemini"
                 else "wan2.7-image-pro")

        try:
            data = cloud_client.generate(
                provider=provider,
                model=model,
                prompt=item.text_content,
                task_uuid=task_uuid,
                size="2K",
                aspect_ratio="1:1",
                n=1,
            )
        except Exception as e:
            return PluginResult(success=False, error_message=f"生成失败: {e}")

        # 万相异步模式需要轮询
        if data.get("status") == "processing":
            if progress_callback:
                progress_callback(50, "等待万相生成结果...")
            data = self._poll_wan_task(cloud_client, task_uuid, progress_callback, cancel_check)
            if not data:
                return PluginResult(success=False, error_message="生成超时或失败")

        if cancel_check and cancel_check():
            return PluginResult(success=False, cancelled=True, error_message="已取消")

        if progress_callback:
            progress_callback(90, "正在处理结果...")

        images = data.get("images", [])
        if not images:
            return PluginResult(success=False, error_message="未返回图片")

        image_data = base64.b64decode(images[0])

        return PluginResult(
            success=True,
            content_type=ContentType.IMAGE,
            image_data=image_data,
            action=PluginResultAction.SAVE,
        )

    def _open_studio(self, item):
        """启动完整的 chat_image_gen 窗口（子进程方式）。"""
        cloud_client = self._get_cloud_client()
        if not cloud_client:
            return PluginResult(success=False, error_message="未登录 CLIPBOARD- 账户")

        config = self.get_config()
        gen_path = config.get("chat_image_gen_path", "") or DEFAULT_CHAT_IMAGE_GEN_PATH
        script = os.path.join(gen_path, "chat_image_gen.py")

        if not os.path.exists(script):
            return PluginResult(
                success=False,
                error_message=f"找不到 chat_image_gen.py: {script}"
            )

        # 通过环境变量传递 token（比命令行参数更安全）
        env = os.environ.copy()
        env["CLOUD_ACCESS_TOKEN"] = cloud_client._access_token
        env["CLOUD_REFRESH_TOKEN"] = cloud_client._refresh_token_str

        cmd = [
            sys.executable, script,
            "--cloud-url", cloud_client._base_url,
        ]

        subprocess.Popen(cmd, env=env, cwd=gen_path)

        return PluginResult(
            success=True,
            content_type=ContentType.TEXT,
            text_content="已打开 AI 生图工作台",
            action=PluginResultAction.COPY,
        )

    def _get_cloud_client(self):
        """从 CLIPBOARD- 框架获取已认证的 cloud client。"""
        try:
            # 动态导入，避免硬依赖
            sys.path.insert(0, os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))))

            # 尝试从 CLIPBOARD- 的 config 系统获取 token
            from config import Config
            base_url = Config.get("cloud_api_url", "https://api.jlike.com")
            access_token = Config.get("cloud_access_token", "")
            refresh_token = Config.get("cloud_refresh_token", "")

            if not access_token:
                return None

            # 使用 chat_image_gen 的 cloud_client（动态导入）
            config = self.get_config()
            gen_path = config.get("chat_image_gen_path", "") or DEFAULT_CHAT_IMAGE_GEN_PATH
            if gen_path not in sys.path:
                sys.path.insert(0, gen_path)

            from lib.cloud_client import ImageGenCloudClient
            client = ImageGenCloudClient(base_url)
            client.set_tokens(access_token, refresh_token)
            return client

        except ImportError:
            self.logger.warning("Failed to import Config or ImageGenCloudClient")
            return None
        except Exception as e:
            self.logger.error("Failed to get cloud client: %s", e)
            return None

    def _poll_wan_task(self, cloud_client, task_uuid, progress_callback, cancel_check,
                       max_wait=300):
        """轮询万相异步任务。"""
        import time
        elapsed = 0
        while elapsed < max_wait:
            if cancel_check and cancel_check():
                try:
                    cloud_client.cancel_task(task_uuid)
                except Exception:
                    pass
                return None

            time.sleep(3)
            elapsed += 3

            if progress_callback:
                pct = min(80, 50 + int(elapsed / max_wait * 30))
                progress_callback(pct, f"等待生成结果... ({elapsed}s)")

            try:
                data = cloud_client.poll_task(task_uuid)
                status = data.get("status", "")
                if status == "succeeded":
                    return data
                elif status == "failed":
                    return None
            except Exception:
                continue

        return None
