/*
 Navicat Premium Data Transfer

 Source Server         : 共享(个人)
 Source Server Type    : MySQL
 Source Server Version : 80036
 Source Host           : rm-bp17sr7d7w77k5wf7no.mysql.rds.aliyuncs.com:3306
 Source Schema         : sharedclipboard

 Target Server Type    : MySQL
 Target Server Version : 80036
 File Encoding         : 65001

 Date: 20/04/2026 12:00:16
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for app_meta
-- ----------------------------
DROP TABLE IF EXISTS `app_meta`;
CREATE TABLE `app_meta`  (
  `key` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  PRIMARY KEY (`key`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for clipboard_items
-- ----------------------------
DROP TABLE IF EXISTS `clipboard_items`;
CREATE TABLE `clipboard_items`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `content_type` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `text_content` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `image_data` longblob NULL,
  `image_thumbnail` mediumblob NULL,
  `content_hash` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `preview` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `device_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `created_at` bigint NOT NULL,
  `is_starred` tinyint NULL DEFAULT 0,
  `cloud_id` bigint NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `content_hash`(`content_hash` ASC) USING BTREE,
  INDEX `idx_created_at`(`created_at` DESC) USING BTREE,
  INDEX `idx_content_type`(`content_type` ASC) USING BTREE,
  INDEX `idx_device_id`(`device_id` ASC) USING BTREE,
  INDEX `idx_content_hash`(`content_hash` ASC) USING BTREE,
  INDEX `idx_cloud_id`(`cloud_id` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 9425 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for cloud_file_upload_parts
-- ----------------------------
DROP TABLE IF EXISTS `cloud_file_upload_parts`;
CREATE TABLE `cloud_file_upload_parts`  (
  `file_id` bigint NOT NULL,
  `part_number` int NOT NULL,
  `etag` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `uploaded_at` bigint NULL DEFAULT NULL,
  PRIMARY KEY (`file_id`, `part_number`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for cloud_files
-- ----------------------------
DROP TABLE IF EXISTS `cloud_files`;
CREATE TABLE `cloud_files`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `cloud_id` bigint NULL DEFAULT NULL,
  `name` varchar(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `original_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `local_path` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `size_bytes` bigint NOT NULL DEFAULT 0,
  `mime_type` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `content_sha256` char(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `mtime` bigint NOT NULL,
  `device_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `created_at` bigint NOT NULL,
  `is_deleted` tinyint NOT NULL DEFAULT 0,
  `sync_state` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `last_error` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
  `bookmark` longblob NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `cloud_id`(`cloud_id` ASC) USING BTREE,
  INDEX `idx_files_sync_state`(`sync_state` ASC) USING BTREE,
  INDEX `idx_files_cloud_id`(`cloud_id` ASC) USING BTREE,
  INDEX `idx_files_sha`(`content_sha256` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 1 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- v3.4: spaces / tags / share_links
-- ----------------------------

-- Table structure for spaces
DROP TABLE IF EXISTS `spaces`;
CREATE TABLE `spaces` (
  `id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'personal',
  `owner_user_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `created_at` bigint NOT NULL,
  `updated_at` bigint NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_spaces_owner`(`owner_user_id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- Table structure for space_members
DROP TABLE IF EXISTS `space_members`;
CREATE TABLE `space_members` (
  `space_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'editor',
  `joined_at` bigint NOT NULL,
  `invited_by` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  PRIMARY KEY (`space_id`, `user_id`) USING BTREE,
  INDEX `idx_space_members_user`(`user_id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- Table structure for tag_definitions
DROP TABLE IF EXISTS `tag_definitions`;
CREATE TABLE `tag_definitions` (
  `id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `space_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `color` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL,
  `created_at` bigint NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uniq_tag_space_name`(`space_id` ASC, `name` ASC) USING BTREE,
  INDEX `idx_tags_space`(`space_id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- Table structure for clipboard_tags
DROP TABLE IF EXISTS `clipboard_tags`;
CREATE TABLE `clipboard_tags` (
  `item_id` bigint NOT NULL,
  `tag_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` bigint NOT NULL,
  PRIMARY KEY (`item_id`, `tag_id`) USING BTREE,
  INDEX `idx_clip_tags_tag`(`tag_id` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- Table structure for share_links
DROP TABLE IF EXISTS `share_links`;
CREATE TABLE `share_links` (
  `id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `token` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `space_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `creator_user_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `item_ids_json` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `expires_at` bigint NOT NULL,
  `created_at` bigint NOT NULL,
  `access_count` bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uniq_share_token`(`token` ASC) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- clipboard_items v3.4 扩展：直接 DROP+CREATE 脚本里已经重建过表，
-- 但该文件是参考 schema、不做增量升级，因此这里用 ALTER 表明新列。
-- 如果从零初始化请改为在 clipboard_items CREATE 语句中直接加列。
ALTER TABLE `clipboard_items` ADD COLUMN `space_id` varchar(64) NULL DEFAULT NULL;
ALTER TABLE `clipboard_items` ADD COLUMN `source_app` varchar(255) NULL DEFAULT NULL;
ALTER TABLE `clipboard_items` ADD COLUMN `source_title` varchar(512) NULL DEFAULT NULL;
ALTER TABLE `clipboard_items` ADD INDEX `idx_clipboard_items_space`(`space_id` ASC);

SET FOREIGN_KEY_CHECKS = 1;
