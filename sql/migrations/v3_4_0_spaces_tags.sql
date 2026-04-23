-- v3.4.0: spaces / tags / share_links / clipboard_items 扩展
-- SQLite 方言。由 core/db_migrations.py 执行；ALTER TABLE ADD COLUMN 的
-- "duplicate column name" 错误会被迁移器静默忽略，保证幂等。

CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'personal',
    owner_user_id TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spaces_owner ON spaces(owner_user_id);

CREATE TABLE IF NOT EXISTS space_members (
    space_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'editor',
    joined_at INTEGER NOT NULL,
    invited_by TEXT DEFAULT NULL,
    PRIMARY KEY (space_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_space_members_user ON space_members(user_id);

CREATE TABLE IF NOT EXISTS tag_definitions (
    id TEXT PRIMARY KEY,
    space_id TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT DEFAULT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (space_id, name)
);
CREATE INDEX IF NOT EXISTS idx_tags_space ON tag_definitions(space_id);

CREATE TABLE IF NOT EXISTS clipboard_tags (
    item_id INTEGER NOT NULL,
    tag_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (item_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_clip_tags_tag ON clipboard_tags(tag_id);

CREATE TABLE IF NOT EXISTS share_links (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    space_id TEXT NOT NULL,
    creator_user_id TEXT NOT NULL,
    item_ids_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE clipboard_items ADD COLUMN space_id TEXT DEFAULT NULL;
ALTER TABLE clipboard_items ADD COLUMN source_app TEXT DEFAULT NULL;
ALTER TABLE clipboard_items ADD COLUMN source_title TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_clipboard_items_space ON clipboard_items(space_id);
