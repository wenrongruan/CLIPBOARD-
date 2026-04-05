<?php
/**
 * 设备控制器
 * 处理设备列表、注册、删除
 */

class DeviceController
{
    /**
     * GET /api/v1/devices
     */
    public static function listDevices(): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        $stmt = $db->prepare(
            'SELECT device_id, device_name, platform, last_seen_at, created_at
             FROM devices
             WHERE user_id = :user_id
             ORDER BY last_seen_at DESC'
        );
        $stmt->execute([':user_id' => $userId]);
        $devices = $stmt->fetchAll();

        Response::success(['devices' => $devices]);
    }

    /**
     * POST /api/v1/devices
     * Body: {device_id, device_name, platform}
     */
    public static function register(): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $input  = json_decode(file_get_contents('php://input'), true);

        if (!$input) {
            Response::error('Invalid JSON body', 400);
        }

        $deviceId   = trim($input['device_id'] ?? '');
        $deviceName = trim($input['device_name'] ?? '');
        $platform   = trim($input['platform'] ?? '');

        if ($deviceId === '') {
            Response::error('device_id is required', 400);
        }

        $db = Database::getInstance();

        // 检查设备数限制（排除已有的同一 device_id）
        $stmt = $db->prepare(
            'SELECT max_devices FROM subscriptions WHERE user_id = :user_id LIMIT 1'
        );
        $stmt->execute([':user_id' => $userId]);
        $sub = $stmt->fetch();

        if (!$sub) {
            Response::error('Subscription not found', 500);
        }

        $maxDevices = (int)$sub['max_devices'];

        // 当前设备数（排除即将 upsert 的那个）
        $stmt = $db->prepare(
            'SELECT COUNT(*) FROM devices WHERE user_id = :user_id AND device_id != :device_id'
        );
        $stmt->execute([':user_id' => $userId, ':device_id' => $deviceId]);
        $existingCount = (int)$stmt->fetchColumn();

        if ($existingCount >= $maxDevices) {
            Response::error('Device limit reached. Please upgrade your plan.', 403, [
                'max_devices' => $maxDevices,
                'current'     => $existingCount,
            ]);
        }

        // INSERT ... ON DUPLICATE KEY UPDATE
        $now = date('Y-m-d H:i:s');
        $stmt = $db->prepare(
            'INSERT INTO devices (user_id, device_id, device_name, platform, last_seen_at, created_at)
             VALUES (:user_id, :device_id, :device_name, :platform, :last_seen_at, :created_at)
             ON DUPLICATE KEY UPDATE
                device_name = VALUES(device_name),
                platform = VALUES(platform),
                last_seen_at = VALUES(last_seen_at)'
        );
        $stmt->execute([
            ':user_id'      => $userId,
            ':device_id'    => $deviceId,
            ':device_name'  => $deviceName,
            ':platform'     => $platform,
            ':last_seen_at' => $now,
            ':created_at'   => $now,
        ]);

        // 查询完整设备信息
        $stmt = $db->prepare(
            'SELECT device_id, device_name, platform, last_seen_at, created_at
             FROM devices
             WHERE user_id = :user_id AND device_id = :device_id
             LIMIT 1'
        );
        $stmt->execute([':user_id' => $userId, ':device_id' => $deviceId]);
        $device = $stmt->fetch();

        Response::success(['device' => $device]);
    }

    /**
     * DELETE /api/v1/devices/{device_id}
     */
    public static function delete(string $deviceId): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        $stmt = $db->prepare(
            'DELETE FROM devices WHERE user_id = :user_id AND device_id = :device_id'
        );
        $stmt->execute([':user_id' => $userId, ':device_id' => $deviceId]);

        if ($stmt->rowCount() === 0) {
            Response::error('Device not found', 404);
        }

        Response::success(null, 'Device deleted');
    }
}
