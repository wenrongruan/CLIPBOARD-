"""ClipboardRepository: 历史外部 API 的 Facade。

实现已在 core/db/* 下拆为三层：
- ClipboardDAO     —— CRUD + tags + meta + cleanup
- ClipboardQuery   —— 列表 / 搜索 / 时间轴 / 按 tag 查询
- SyncStateDAO     —— cloud_id 状态管理

外部仍只引用本模块的 ClipboardRepository，签名保持与拆分前一致。
新代码建议直接使用 core.db 下的具体 DAO/Query。
"""

import logging
from typing import List, Optional, Tuple

from .base_database import AbstractDatabaseManager
from .db.clipboard_dao import ClipboardDAO, _INTEGRITY_ERRORS  # noqa: F401 — _INTEGRITY_ERRORS 保留以兼容历史外部 import
from .db.clipboard_query import ClipboardQuery
from .db.sync_state_dao import SyncStateDAO
from .models import ClipboardItem
from .query_parser import QuerySpec

logger = logging.getLogger(__name__)


class ClipboardRepository:
    """三层 DAO 的薄 Facade。保持原有 public 方法签名不变。"""

    # 兼容老代码：有外部模块可能通过 ClipboardRepository._SELECT_FIELDS 访问。
    _SELECT_FIELDS = ClipboardDAO._SELECT_FIELDS
    _SELECT_FIELDS_NO_IMAGE = ClipboardDAO._SELECT_FIELDS_NO_IMAGE

    def __init__(self, db_manager: AbstractDatabaseManager):
        self.db = db_manager
        self._dao = ClipboardDAO(db_manager)
        self._query = ClipboardQuery(db_manager, self._dao)
        self._sync = SyncStateDAO(db_manager)
        # 兼容字段：少量旧代码会读 repo._is_mysql / repo._has_fts
        self._is_mysql = self._dao._is_mysql
        self._has_fts = self._dao._has_fts

    # ------------------------------------------------------------------
    # CRUD / 单条访问  -> DAO
    # ------------------------------------------------------------------

    def add_item(self, item: ClipboardItem) -> int:
        return self._dao.add_item(item)

    def get_by_hash(self, content_hash: str) -> Optional[ClipboardItem]:
        return self._dao.get_by_hash(content_hash)

    def get_existing_hashes(self, hashes: list) -> dict:
        return self._dao.get_existing_hashes(hashes)

    def get_item_by_id(self, item_id: int) -> Optional[ClipboardItem]:
        # 保持旧行为：单条读取后回填 tag_ids。
        item = self._dao.get_item_by_id(item_id)
        if item is not None:
            self._query._fill_tag_ids([item])
        return item

    def delete_item(self, item_id: int) -> bool:
        return self._dao.delete_item(item_id)

    def toggle_star(self, item_id: int) -> bool:
        return self._dao.toggle_star(item_id)

    def update_item_content(
        self, item_id: int, text_content: Optional[str] = None,
        image_data: Optional[bytes] = None, content_type: Optional[str] = None,
    ) -> bool:
        return self._dao.update_item_content(
            item_id,
            text_content=text_content,
            image_data=image_data,
            content_type=content_type,
        )

    def touch_item(self, item_id: int, created_at: int) -> bool:
        return self._dao.touch_item(item_id, created_at)

    def get_new_items_since(
        self, since_id: int, exclude_device_id: str
    ) -> List[ClipboardItem]:
        return self._dao.get_new_items_since(since_id, exclude_device_id)

    def get_latest_id(self) -> int:
        return self._dao.get_latest_id()

    def cleanup_old_items(self, max_items: int = 10000) -> int:
        return self._dao.cleanup_old_items(max_items)

    def cleanup_expired_items(self, retention_days: int) -> int:
        return self._dao.cleanup_expired_items(retention_days)

    # ------------------------------------------------------------------
    # Tags / Meta -> DAO
    # ------------------------------------------------------------------

    def add_tags_to_item(self, item_id: int, tag_ids: List[str]) -> None:
        return self._dao.add_tags_to_item(item_id, tag_ids)

    def remove_tags_from_item(self, item_id: int, tag_ids: List[str]) -> None:
        return self._dao.remove_tags_from_item(item_id, tag_ids)

    def get_tags_for_item(self, item_id: int) -> List[str]:
        return self._dao.get_tags_for_item(item_id)

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._dao.get_meta(key, default)

    def set_meta(self, key: str, value: str) -> None:
        return self._dao.set_meta(key, value)

    # ------------------------------------------------------------------
    # 列表 / 搜索 / 时间轴 -> Query
    # ------------------------------------------------------------------

    def get_items(
        self, page: int = 0, page_size: int = 10, starred_only: bool = False
    ) -> Tuple[List[ClipboardItem], int]:
        return self._query.get_items(page, page_size, starred_only)

    def get_items_full(
        self, page: int = 0, page_size: int = 100
    ) -> Tuple[List[ClipboardItem], int]:
        return self._query.get_items_full(page, page_size)

    def search_by_keyword(
        self,
        keyword: str,
        page: int = 0,
        page_size: int = 10,
        starred_only: bool = False,
        space_id: Optional[str] = None,
    ) -> Tuple[List[ClipboardItem], int]:
        return self._query.search_by_keyword(
            keyword,
            page=page,
            page_size=page_size,
            starred_only=starred_only,
            space_id=space_id,
        )

    def search(
        self,
        query_spec: Optional[QuerySpec] = None,
        page: int = 1,
        page_size: int = 50,
        *,
        space_id: Optional[str] = None,
    ) -> List[ClipboardItem]:
        return self._query.search(
            query_spec, page=page, page_size=page_size, space_id=space_id
        )

    def get_timeline(
        self,
        start_ts: int,
        end_ts: int,
        granularity: str = "day",
        space_id: Optional[str] = None,
    ) -> List[dict]:
        return self._query.get_timeline(start_ts, end_ts, granularity, space_id)

    def get_items_by_tag(
        self, tag_id: str, page: int = 1, page_size: int = 50
    ) -> List[ClipboardItem]:
        return self._query.get_items_by_tag(tag_id, page=page, page_size=page_size)

    # ------------------------------------------------------------------
    # 云同步状态 -> SyncStateDAO
    # ------------------------------------------------------------------

    def set_cloud_id(self, item_id: int, cloud_id: int):
        return self._sync.set_cloud_id(item_id, cloud_id)

    def set_cloud_ids_bulk(self, pairs: list):
        return self._sync.set_cloud_ids_bulk(pairs)

    def update_cloud_sync_metadata(
        self,
        item_id: int,
        *,
        cloud_id: Optional[int] = None,
        is_starred: Optional[bool] = None,
    ) -> None:
        return self._sync.update_cloud_sync_metadata(
            item_id, cloud_id=cloud_id, is_starred=is_starred
        )

    def clear_cloud_id(self, item_id: int):
        return self._sync.clear_cloud_id(item_id)

    def get_by_cloud_id(self, cloud_id: int) -> Optional[ClipboardItem]:
        return self._sync.get_by_cloud_id(cloud_id)

    def get_starred_unsynced(self, limit: int = 100) -> List[ClipboardItem]:
        return self._sync.get_starred_unsynced(limit)

    def get_unsynced_items(self, limit: int = 20) -> List[ClipboardItem]:
        return self._sync.get_unsynced_items(limit)

    def get_unstarred_with_cloud_id(self, limit: int = 200) -> List[ClipboardItem]:
        return self._sync.get_unstarred_with_cloud_id(limit)

    def get_cloud_ids_for_ids(self, item_ids: List[int]) -> dict:
        return self._sync.get_cloud_ids_for_ids(item_ids)
