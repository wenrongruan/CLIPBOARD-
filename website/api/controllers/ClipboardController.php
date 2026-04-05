<?php
/**
 * 剪贴板控制器
 * 处理剪贴板条目的批量创建、同步、列表、删除、收藏、图片上传/获取
 */

class ClipboardController
{
    /**
     * POST /api/v1/clipboard/batch
     * Body: {items: [{content_type, text_content, content_hash, preview, device_id, device_name, created_at, is_starred, image_thumbnail?}]}
     */
    public static function batchCreate(): void
    {
        $user  = Auth::requireUser();
        $input = json_decode(file_get_contents('php://input'), true);

        if (!$input || !isset($input['items']) || !is_array($input['items'])) {
            Response::error('items array is required', 400);
        }

        $items = $input['items'];
        if (count($items) === 0) {
            Response::success(['items' => [], 'created_count' => 0]);
        }

        $db     = Database::getInstance();
        $userId = $user['id'];

        // 检查配额
        $stmt = $db->prepare(
            'SELECT us.item_count, s.max_items
             FROM usage_stats us
             JOIN subscriptions s ON s.user_id = us.user_id
             WHERE us.user_id = :user_id
             LIMIT 1'
        );
        $stmt->execute([':user_id' => $userId]);
        $quota = $stmt->fetch();

        if (!$quota) {
            Response::error('User subscription not found', 500);
        }

        $currentCount = (int)$quota['item_count'];
        $maxItems     = (int)$quota['max_items'];
        $remaining    = $maxItems - $currentCount;

        if ($remaining <= 0) {
            Response::error('Item quota exceeded. Please upgrade your plan.', 403, [
                'current_count' => $currentCount,
                'max_items'     => $maxItems,
            ]);
        }

        // 限制本次批量最多创建到配额上限
        $itemsToInsert = array_slice($items, 0, $remaining);

        $createdItems = [];
        $createdCount = 0;

        $stmtInsert = $db->prepare(
            'INSERT IGNORE INTO clipboard_items
             (user_id, content_type, text_content, content_hash, preview, device_id, device_name, created_at, is_starred, image_thumbnail)
             VALUES
             (:user_id, :content_type, :text_content, :content_hash, :preview, :device_id, :device_name, :created_at, :is_starred, :image_thumbnail)'
        );

        $db->beginTransaction();
        try {
            foreach ($itemsToInsert as $item) {
                $contentHash = $item['content_hash'] ?? '';
                if ($contentHash === '') {
                    continue;
                }

                $stmtInsert->execute([
                    ':user_id'         => $userId,
                    ':content_type'    => $item['content_type'] ?? 'text',
                    ':text_content'    => $item['text_content'] ?? null,
                    ':content_hash'    => $contentHash,
                    ':preview'         => $item['preview'] ?? null,
                    ':device_id'       => $item['device_id'] ?? '',
                    ':device_name'     => $item['device_name'] ?? '',
                    ':created_at'      => $item['created_at'] ?? date('Y-m-d H:i:s'),
                    ':is_starred'      => (int)($item['is_starred'] ?? 0),
                    ':image_thumbnail' => $item['image_thumbnail'] ?? null,
                ]);

                $rowCount = $stmtInsert->rowCount();
                if ($rowCount > 0) {
                    $insertedId = $db->lastInsertId();
                    $createdCount++;
                    $createdItems[] = [
                        'id'           => (int)$insertedId,
                        'content_type' => $item['content_type'] ?? 'text',
                        'content_hash' => $contentHash,
                        'device_id'    => $item['device_id'] ?? '',
                        'created_at'   => $item['created_at'] ?? date('Y-m-d H:i:s'),
                    ];
                }
            }

            // 更新 usage_stats
            if ($createdCount > 0) {
                $stmt = $db->prepare(
                    'UPDATE usage_stats SET item_count = item_count + :count, updated_at = NOW() WHERE user_id = :user_id'
                );
                $stmt->execute([':count' => $createdCount, ':user_id' => $userId]);
            }

            $db->commit();
        } catch (Exception $e) {
            $db->rollBack();
            Response::error('Batch create failed: ' . $e->getMessage(), 500);
        }

        Response::success([
            'items'         => $createdItems,
            'created_count' => $createdCount,
        ]);
    }

    /**
     * GET /api/v1/clipboard/sync
     * Query: since_id, device_id, limit(default 100)
     */
    public static function sync(): void
    {
        $user = Auth::requireUser();
        $userId = $user['id'];

        $sinceId  = (int)($_GET['since_id'] ?? 0);
        $deviceId = $_GET['device_id'] ?? '';
        $limit    = min((int)($_GET['limit'] ?? 100), 500);
        if ($limit <= 0) {
            $limit = 100;
        }

        $db = Database::getInstance();

        // 查询其他设备的新条目（不返回 image_data）
        $sql = 'SELECT id, content_type, text_content, content_hash, preview,
                       device_id, device_name, created_at, is_starred, image_thumbnail, image_storage_key
                FROM clipboard_items
                WHERE user_id = :user_id AND id > :since_id';
        $params = [
            ':user_id'  => $userId,
            ':since_id' => $sinceId,
        ];

        if ($deviceId !== '') {
            $sql .= ' AND device_id != :device_id';
            $params[':device_id'] = $deviceId;
        }

        $sql .= ' ORDER BY id ASC LIMIT :limit';

        $stmt = $db->prepare($sql);
        foreach ($params as $k => $v) {
            if ($k === ':since_id') {
                $stmt->bindValue($k, $v, PDO::PARAM_INT);
            } else {
                $stmt->bindValue($k, $v, PDO::PARAM_STR);
            }
        }
        $stmt->bindValue(':limit', $limit + 1, PDO::PARAM_INT);
        $stmt->execute();

        $rows = $stmt->fetchAll();
        $hasMore = count($rows) > $limit;
        if ($hasMore) {
            array_pop($rows);
        }

        self::formatRows($rows);

        Response::success([
            'items'    => $rows,
            'has_more' => $hasMore,
        ]);
    }

    /**
     * GET /api/v1/clipboard/items
     * Query: page, per_page, search
     */
    public static function list(): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];

        $page    = max(1, (int)($_GET['page'] ?? 1));
        $perPage = min(max(1, (int)($_GET['per_page'] ?? 20)), 100);
        $search  = trim($_GET['search'] ?? '');
        $offset  = ($page - 1) * $perPage;

        $db = Database::getInstance();

        $whereClause = 'WHERE user_id = :user_id';
        $params = [':user_id' => $userId];

        if ($search !== '') {
            $whereClause .= ' AND (text_content LIKE :search OR preview LIKE :search2)';
            $params[':search']  = '%' . $search . '%';
            $params[':search2'] = '%' . $search . '%';
        }

        // 计算总数
        $countSql = "SELECT COUNT(*) FROM clipboard_items $whereClause";
        $stmt = $db->prepare($countSql);
        $stmt->execute($params);
        $total = (int)$stmt->fetchColumn();

        // 查询数据
        $sql = "SELECT id, content_type, text_content, content_hash, preview,
                       device_id, device_name, created_at, is_starred, image_thumbnail, image_storage_key
                FROM clipboard_items
                $whereClause
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset";

        $stmt = $db->prepare($sql);
        foreach ($params as $k => $v) {
            $stmt->bindValue($k, $v, PDO::PARAM_STR);
        }
        $stmt->bindValue(':limit', $perPage, PDO::PARAM_INT);
        $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
        $stmt->execute();

        $rows = $stmt->fetchAll();
        self::formatRows($rows);

        Response::success([
            'items'    => $rows,
            'total'    => $total,
            'page'     => $page,
            'per_page' => $perPage,
        ]);
    }

    /**
     * DELETE /api/v1/clipboard/{id}
     */
    public static function delete(int $id): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        // 查询条目（确认归属）
        $stmt = $db->prepare(
            'SELECT id, image_storage_key FROM clipboard_items WHERE id = :id AND user_id = :user_id LIMIT 1'
        );
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $item = $stmt->fetch();

        if (!$item) {
            Response::error('Item not found', 404);
        }

        $db->beginTransaction();
        try {
            // 如果有 OSS 图片，删除
            if (!empty($item['image_storage_key'])) {
                OSS::delete($item['image_storage_key']);
            }

            // 删除条目
            $stmt = $db->prepare('DELETE FROM clipboard_items WHERE id = :id AND user_id = :user_id');
            $stmt->execute([':id' => $id, ':user_id' => $userId]);

            // 减少计数
            $stmt = $db->prepare(
                'UPDATE usage_stats SET item_count = GREATEST(item_count - 1, 0), updated_at = NOW() WHERE user_id = :user_id'
            );
            $stmt->execute([':user_id' => $userId]);

            $db->commit();
        } catch (Exception $e) {
            $db->rollBack();
            Response::error('Delete failed: ' . $e->getMessage(), 500);
        }

        Response::success(null, 'Item deleted');
    }

    /**
     * PUT /api/v1/clipboard/{id}/star
     */
    public static function toggleStar(int $id): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        // 翻转 is_starred
        $stmt = $db->prepare(
            'UPDATE clipboard_items SET is_starred = 1 - is_starred WHERE id = :id AND user_id = :user_id'
        );
        $stmt->execute([':id' => $id, ':user_id' => $userId]);

        if ($stmt->rowCount() === 0) {
            Response::error('Item not found', 404);
        }

        // 返回新状态
        $stmt = $db->prepare('SELECT is_starred FROM clipboard_items WHERE id = :id');
        $stmt->execute([':id' => $id]);
        $isStarred = (int)$stmt->fetchColumn();

        Response::success(['id' => $id, 'is_starred' => $isStarred]);
    }

    /**
     * POST /api/v1/clipboard/{id}/image
     * Body: 原始二进制图片数据
     */
    public static function uploadImage(int $id): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        // 查询条目
        $stmt = $db->prepare(
            'SELECT id, content_hash FROM clipboard_items WHERE id = :id AND user_id = :user_id LIMIT 1'
        );
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $item = $stmt->fetch();

        if (!$item) {
            Response::error('Item not found', 404);
        }

        // 读取图片数据
        $imageData = file_get_contents('php://input');
        if (empty($imageData)) {
            Response::error('No image data received', 400);
        }

        $contentType = $_SERVER['CONTENT_TYPE'] ?? 'image/jpeg';
        $extension = 'jpg';
        if (strpos($contentType, 'png') !== false) {
            $extension = 'png';
        } elseif (strpos($contentType, 'gif') !== false) {
            $extension = 'gif';
        } elseif (strpos($contentType, 'webp') !== false) {
            $extension = 'webp';
        }

        $objectKey = "users/{$userId}/images/{$item['content_hash']}.{$extension}";

        // 上传到 OSS
        $uploaded = OSS::upload($objectKey, $imageData, $contentType);
        if (!$uploaded) {
            Response::error('Failed to upload image to storage', 500);
        }

        // 更新数据库
        $imageSize = strlen($imageData);
        $db->beginTransaction();
        try {
            $stmt = $db->prepare(
                'UPDATE clipboard_items SET image_storage_key = :key WHERE id = :id AND user_id = :user_id'
            );
            $stmt->execute([':key' => $objectKey, ':id' => $id, ':user_id' => $userId]);

            $stmt = $db->prepare(
                'UPDATE usage_stats SET image_bytes_used = image_bytes_used + :size, updated_at = NOW() WHERE user_id = :user_id'
            );
            $stmt->execute([':size' => $imageSize, ':user_id' => $userId]);

            $db->commit();
        } catch (Exception $e) {
            $db->rollBack();
            Response::error('Failed to update image record: ' . $e->getMessage(), 500);
        }

        Response::success([
            'id'                => $id,
            'image_storage_key' => $objectKey,
            'image_size'        => $imageSize,
        ]);
    }

    /**
     * GET /api/v1/clipboard/{id}/image-url
     */
    public static function getImageUrl(int $id): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        $stmt = $db->prepare(
            'SELECT image_storage_key FROM clipboard_items WHERE id = :id AND user_id = :user_id LIMIT 1'
        );
        $stmt->execute([':id' => $id, ':user_id' => $userId]);
        $item = $stmt->fetch();

        if (!$item) {
            Response::error('Item not found', 404);
        }

        if (empty($item['image_storage_key'])) {
            Response::error('No image associated with this item', 404);
        }

        $config = require __DIR__ . '/../config.php';
        $expiry = $config['oss']['url_expiry'] ?? 3600;
        $url    = OSS::getPresignedUrl($item['image_storage_key'], $expiry);

        Response::success(['url' => $url]);
    }

    /**
     * 统一格式化行数据：类型转换、计算 has_image、移除内部字段
     */
    private static function formatRows(array &$rows): void
    {
        foreach ($rows as &$row) {
            $row['id']         = (int)$row['id'];
            $row['is_starred'] = (int)$row['is_starred'];
            $row['has_image']  = ($row['image_storage_key'] !== null && $row['image_storage_key'] !== '');
            unset($row['image_storage_key']);
        }
        unset($row);
    }
}
