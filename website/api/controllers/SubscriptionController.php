<?php
/**
 * 订阅控制器
 * 处理订阅状态查询和创建支付会话
 */

class SubscriptionController
{
    /**
     * GET /api/v1/subscription
     */
    public static function status(): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $db     = Database::getInstance();

        // 查询订阅和用量
        $stmt = $db->prepare(
            'SELECT s.plan, s.status, s.max_items, s.max_devices,
                    s.current_period_end, s.ls_subscription_id, s.manage_url,
                    us.item_count, us.image_bytes_used
             FROM subscriptions s
             LEFT JOIN usage_stats us ON us.user_id = s.user_id
             WHERE s.user_id = :user_id
             LIMIT 1'
        );
        $stmt->execute([':user_id' => $userId]);
        $row = $stmt->fetch();

        if (!$row) {
            Response::error('Subscription not found', 404);
        }

        // 查询已用设备数
        $stmt = $db->prepare('SELECT COUNT(*) FROM devices WHERE user_id = :user_id');
        $stmt->execute([':user_id' => $userId]);
        $usedDevices = (int)$stmt->fetchColumn();

        Response::success([
            'plan'         => $row['plan'],
            'status'       => $row['status'],
            'max_records'  => (int)$row['max_items'],
            'used_records' => (int)$row['item_count'],
            'max_devices'  => (int)$row['max_devices'],
            'used_devices' => $usedDevices,
            'expires_at'   => $row['current_period_end'],
            'manage_url'   => $row['manage_url'],
        ]);
    }

    /**
     * POST /api/v1/subscription/checkout
     * Body: {plan: "basic"|"super"|"ultimate"}
     */
    public static function checkout(): void
    {
        $user   = Auth::requireUser();
        $userId = $user['id'];
        $input  = json_decode(file_get_contents('php://input'), true);

        $plan = $input['plan'] ?? '';
        $validPlans = ['basic', 'super', 'ultimate'];

        if (!in_array($plan, $validPlans, true)) {
            Response::error('Invalid plan. Must be one of: basic, super, ultimate', 400);
        }

        $config = require __DIR__ . '/../config.php';
        $lsConfig = $config['lemonsqueezy'];

        $variantId = $lsConfig['variants'][$plan] ?? '';
        if ($variantId === '') {
            Response::error('Plan variant not configured', 500);
        }

        // 获取用户邮箱
        $db = Database::getInstance();
        $stmt = $db->prepare('SELECT email FROM users WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $userId]);
        $userRow = $stmt->fetch();

        if (!$userRow) {
            Response::error('User not found', 404);
        }

        // 调用 Lemon Squeezy API 创建 checkout
        $payload = [
            'data' => [
                'type' => 'checkouts',
                'attributes' => [
                    'checkout_data' => [
                        'email' => $userRow['email'],
                        'custom' => [
                            'user_id' => $userId,
                        ],
                    ],
                ],
                'relationships' => [
                    'store' => [
                        'data' => [
                            'type' => 'stores',
                            'id'   => $lsConfig['store_id'],
                        ],
                    ],
                    'variant' => [
                        'data' => [
                            'type' => 'variants',
                            'id'   => $variantId,
                        ],
                    ],
                ],
            ],
        ];

        $ch = curl_init('https://api.lemonsqueezy.com/v1/checkouts');
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST           => true,
            CURLOPT_HTTPHEADER     => [
                'Accept: application/vnd.api+json',
                'Content-Type: application/vnd.api+json',
                'Authorization: Bearer ' . $lsConfig['api_key'],
            ],
            CURLOPT_POSTFIELDS => json_encode($payload),
            CURLOPT_TIMEOUT    => 30,
        ]);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curlError = curl_error($ch);
        curl_close($ch);

        if ($curlError) {
            Response::error('Payment service error: ' . $curlError, 502);
        }

        if ($httpCode >= 400) {
            Response::error('Payment service returned error', 502, [
                'http_code' => $httpCode,
                'response'  => json_decode($response, true),
            ]);
        }

        $result = json_decode($response, true);
        $checkoutUrl = $result['data']['attributes']['url'] ?? null;

        if (!$checkoutUrl) {
            Response::error('Failed to create checkout session', 500);
        }

        Response::success(['checkout_url' => $checkoutUrl]);
    }
}
