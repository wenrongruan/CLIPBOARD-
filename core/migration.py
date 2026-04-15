import logging
from typing import Callable, Optional

from .repository import ClipboardRepository

logger = logging.getLogger(__name__)


class DatabaseMigrator:
    """数据库迁移工具：从源库分页读取全量数据，按 content_hash 去重写入目标库"""

    def __init__(
        self,
        source: ClipboardRepository,
        target: ClipboardRepository,
        page_size: int = 100,
    ):
        self.source = source
        self.target = target
        self.page_size = page_size

    def migrate(
        self, progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> int:
        """
        执行迁移，返回实际写入的条数。

        Args:
            progress_callback: 可选回调 (migrated_so_far, total)
        """
        page = 0
        migrated = 0

        # 先获取总数
        _, total = self.source.get_items_full(0, 1)

        while True:
            items, _ = self.source.get_items_full(page, self.page_size)
            if not items:
                break

            for idx, item in enumerate(items):
                # 按 content_hash 去重
                existing = self.target.get_by_hash(item.content_hash)
                if existing is None:
                    # 清除 id 让目标库自动分配；None 与 ClipboardItem.id: Optional[int] 语义一致
                    item.id = None
                    try:
                        new_id = self.target.add_item(item)
                        if new_id:
                            item.id = new_id
                        migrated += 1
                    except Exception as e:
                        logger.warning(f"迁移条目失败 (hash={item.content_hash}): {e}")

                if progress_callback:
                    progress_callback(page * self.page_size + idx + 1, total)

            page += 1

        return migrated
