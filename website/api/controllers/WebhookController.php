<?php
/**
 * Webhook 控制器
 * 处理 Lemon Squeezy 支付回调
 */

class WebhookController
{
    /**
     * POST /api/v1/webhooks/lemonsqueezy
     * 验证签名并处理订阅事件
     */
    public static function handleLemonSqueezy(): void
    {
        $config = require __DIR__ . '/../config.php';
        $webhookSecret = $config['lemonsqueezy']['webhook_secret'] ?? '';

        // 读取原始请求体
        $rawBody = file_get_contents('php://input');
        if (empty($rawBody)) {
            Response::error('Empty request body', 400);
        }

        // 验证 HMAC-SHA256 签名
        $signature = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
        if ($signature === '') {
            Response::error('Missing signature', 401);
        }

        $expectedSignature = hash_hmac('sha256', $rawBody, $webhookSecret);
        if (!hash_equals($expectedSignature, $signature)) {
            Response::error('Invalid signature', 401);
        }

        // 解析 payload
        $payload = json_decode($rawBody, true);
        if (!$payload) {
            Response::error('Invalid JSON payload', 400);
        }

        $eventName = $payload['meta']['event_name'] ?? '';
        $data      = $payload['data'] ?? [];
        $attrs     = $data['attributes'] ?? [];
        $meta      = $payload['meta'] ?? [];

        // 从 custom_data 或 meta 中提取 user_id
        $userId = $meta['custom_data']['user_id']
            ?? $attrs['custom_data']['user_id']
            ?? $attrs['first_order_item']['custom_data']['user_id']
            ?? null;

        // 如果没有 user_id，尝试通过邮箱查找
        if ($userId === null) {
            $userEmail = $attrs['user_email'] ?? null;
            if ($userEmail) {
                $db   = Database::getInstance();
                $stmt = $db->prepare('SELECT id FROM users WHERE email = :email LIMIT 1');
                $stmt->execute([':email' => $userEmail]);
                $userRow = $stmt->fetch();
                if ($userRow) {
                    $userId = $userRow['id'];
                }
            }
        }

        if ($userId === null) {
            // 无法确定用户，记录日志但返回 200 防止重试
            Response::success(null, 'User not found, event ignored');
        }

        switch ($eventName) {
            case 'subscription_created':
            case 'subscription_updated':
                self::handleSubscriptionUpdate($userId, $attrs, $config);
                break;

            case 'subscription_cancelled':
            case 'subscription_expired':
                self::handleSubscriptionCancel($userId);
                break;

            default:
                // 未处理的事件类型，返回 200
                break;
        }

        Response::success(null, 'Webhook processed');
    }

    /**
     * 处理订阅创建/更新
     */
    private static function handleSubscriptionUpdate(string $userId, array $attrs, array $config): void
    {
        $db = Database::getInstance();

        $lsSubscriptionId = (string)($attrs['id'] ?? $attrs['subscription_id'] ?? '');
        $variantId        = (string)($attrs['variant_id'] ?? '');
        $status           = $attrs['status'] ?? 'active';
        $currentPeriodEnd = $attrs['renews_at'] ?? $attrs['ends_at'] ?? null;
        $manageUrl        = $attrs['urls']['customer_portal'] ?? null;

        // 根据 variant_id 确定 plan
        $plan = 'free';
        $variants = $config['lemonsqueezy']['variants'] ?? [];
        foreach ($variants as $planName => $vid) {
            if ((string)$vid === $variantId) {
                $plan = $planName;
                break;
            }
        }

        $planConfig = $config['plans'][$plan] ?? $config['plans']['free'];

        $stmt = $db->prepare(
            'UPDATE subscriptions SET
                plan = :plan,
                status = :status,
                ls_subscription_id = :ls_sub_id,
                max_items = :max_items,
                max_devices = :max_devices,
                current_period_end = :period_end,
                manage_url = :manage_url,
                updated_at = NOW()
             WHERE user_id = :user_id'
        );
        $stmt->execute([
            ':plan'       => $plan,
            ':status'     => $status,
            ':ls_sub_id'  => $lsSubscriptionId,
            ':max_items'  => $planConfig['max_items'],
            ':max_devices'=> $planConfig['max_devices'],
            ':period_end' => $currentPeriodEnd,
            ':manage_url' => $manageUrl,
            ':user_id'    => $userId,
        ]);
    }

    /**
     * 处理订阅取消/过期 — 降级为 free
     */
    private static function handleSubscriptionCancel(string $userId): void
    {
        $config   = require __DIR__ . '/../config.php';
        $freePlan = $config['plans']['free'];
        $db       = Database::getInstance();

        $stmt = $db->prepare(
            'UPDATE subscriptions SET
                plan = :plan,
                status = :status,
                max_items = :max_items,
                max_devices = :max_devices,
                current_period_end = NULL,
                manage_url = NULL,
                updated_at = NOW()
             WHERE user_id = :user_id'
        );
        $stmt->execute([
            ':plan'       => 'free',
            ':status'     => 'active',
            ':max_items'  => $freePlan['max_items'],
            ':max_devices'=> $freePlan['max_devices'],
            ':user_id'    => $userId,
        ]);
    }
}
