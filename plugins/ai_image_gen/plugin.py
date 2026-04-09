"""
AI 图片生成插件
通过 CLIPBOARD- 云端代理调用 Gemini/万相 AI 生成图片
"""

import base64
import logging
import os
import subprocess
import sys
import tempfile
import uuid

logger = logging.getLogger(__name__)

from core.plugin_api import PluginBase, PluginAction, PluginResult, PluginResultAction
from core.models import ClipboardItem, ContentType

# chat_image_gen 项目默认路径
DEFAULT_CHAT_IMAGE_GEN_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "chat_image_gen"
))


class AIImageGenPlugin(PluginBase):

    def __init__(self):
        super().__init__()
        self._gen_client = None  # 缓存图片生成专用客户端

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

        # 使用框架提供的标准认证方法
        cloud_client = self.get_cloud_client()
        if not cloud_client:
            return PluginResult(success=False, error_message="未登录 CLIPBOARD- 账户，请在设置中登录")

        # 使用框架标准方法检查余额
        if progress_callback:
            progress_callback(10, "正在检查余额...")

        try:
            balance_data = self.get_balance()
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

        # 使用专用图片生成客户端（缓存复用）
        gen_client = self._get_gen_client()
        if not gen_client:
            return PluginResult(success=False, error_message="图片生成服务不可用")

        try:
            data = gen_client.generate(
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
            data = self._poll_wan_task(gen_client, task_uuid, progress_callback, cancel_check)
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
        """启动完整的 chat_image_gen 窗口（子进程方式），传递剪贴板内容。"""
        if not self.get_cloud_client():
            return PluginResult(success=False, error_message="未登录 CLIPBOARD- 账户，请在设置中登录")

        config = self.get_config()
        gen_path = config.get("chat_image_gen_path", "") or DEFAULT_CHAT_IMAGE_GEN_PATH
        script = os.path.join(gen_path, "chat_image_gen.py")

        if not os.path.exists(script):
            return PluginResult(
                success=False,
                error_message=f"找不到 chat_image_gen.py: {script}"
            )

        # 通过环境变量传递 token（比命令行参数更安全）
        from config import Config
        env = os.environ.copy()
        env["CLOUD_ACCESS_TOKEN"] = Config.get_cloud_access_token()
        env["CLOUD_REFRESH_TOKEN"] = Config.get_cloud_refresh_token()

        cmd = [
            sys.executable, script,
            "--cloud-url", Config.get_cloud_api_url(),
        ]

        # 传递剪贴板内容到工作台
        if item.content_type == ContentType.IMAGE and item.image_data:
            # 图片写入临时文件，子进程启动后加载为参考图
            try:
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="clipboard_studio_", delete=False
                )
                tmp.write(item.image_data)
                tmp.close()
                cmd.extend(["--init-image", tmp.name])
            except Exception:
                logger.warning("临时图片文件写入失败", exc_info=True)
        elif item.content_type == ContentType.TEXT and item.text_content:
            cmd.extend(["--init-prompt", item.text_content])

        subprocess.Popen(cmd, env=env, cwd=gen_path)

        return PluginResult(
            success=True,
            action=PluginResultAction.NONE,
        )

    def _get_gen_client(self):
        """获取图片生成专用客户端（缓存复用）。

        认证信息从框架注入的 cloud_client 获取，避免每次重新导入和创建。
        """
        # 检查缓存的客户端是否仍然有效
        if self._gen_client is not None:
            return self._gen_client

        try:
            from config import Config
            base_url = Config.get_cloud_api_url()
            access_token = Config.get_cloud_access_token()
            refresh_token = Config.get_cloud_refresh_token()

            if not access_token:
                return None

            # 动态导入 ImageGenCloudClient（仅首次）
            config = self.get_config()
            gen_path = config.get("chat_image_gen_path", "") or DEFAULT_CHAT_IMAGE_GEN_PATH
            if gen_path not in sys.path:
                sys.path.insert(0, gen_path)

            from lib.cloud_client import ImageGenCloudClient
            self._gen_client = ImageGenCloudClient(base_url)
            self._gen_client.set_tokens(access_token, refresh_token)
            return self._gen_client

        except ImportError:
            self.logger.warning("Failed to import ImageGenCloudClient")
            return None
        except Exception as e:
            self.logger.error("Failed to create gen client: %s", e)
            return None

    def on_config_changed(self, config: dict):
        """配置变更时清除缓存的客户端"""
        self._gen_client = None

    def _poll_wan_task(self, cloud_client, task_uuid, progress_callback, cancel_check,
                       max_wait=300):
        """轮询万相异步任务。"""
        import time
        elapsed = 0
        poll_interval = 3  # 轮询间隔秒数
        check_interval = 0.5  # 取消检查间隔秒数
        while elapsed < max_wait:
            # 分段 sleep 以快速响应取消
            waited = 0
            while waited < poll_interval:
                time.sleep(check_interval)
                waited += check_interval
                if cancel_check and cancel_check():
                    try:
                        cloud_client.cancel_task(task_uuid)
                    except Exception:
                        pass
                    return None
            elapsed += poll_interval

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
