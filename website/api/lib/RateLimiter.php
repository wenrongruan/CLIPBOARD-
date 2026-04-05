<?php
/**
 * 基于数据库的令牌桶限速器
 * 使用 rate_limits 表存储令牌状态
 * PHP 7.4 兼容
 */

class RateLimiter
{
    /**
     * 检查是否允许请求（消耗一个令牌）
     *
     * @param string $userId       用户 ID
     * @param int    $maxPerMinute 每分钟最大请求数
     * @return bool 是否允许
     */
    public static function check(string $userId, int $maxPerMinute): bool
    {
        $config = require __DIR__ . '/../config.php';

        // 如果限速未启用，直接放行
        if (!($config['rate_limit']['enabled'] ?? true)) {
            return true;
        }

        $pdo = Database::getInstance();
        $now = intval(microtime(true) * 1000); // 毫秒时间戳
        $refillRate = $maxPerMinute / 60000.0; // 每毫秒补充的令牌数

        // 使用事务保证原子性
        $pdo->beginTransaction();

        try {
            // 查询当前令牌状态（加行锁）
            $stmt = $pdo->prepare(
                'SELECT tokens, last_refill FROM rate_limits WHERE user_id = ? FOR UPDATE'
            );
            $stmt->execute([$userId]);
            $row = $stmt->fetch();

            if ($row === false) {
                // 首次请求，初始化记录（消耗 1 个令牌）
                $stmt = $pdo->prepare(
                    'INSERT INTO rate_limits (user_id, tokens, last_refill) VALUES (?, ?, ?)'
                );
                $stmt->execute([$userId, $maxPerMinute - 1, $now]);
                $pdo->commit();
                return true;
            }

            $tokens = (float)$row['tokens'];
            $lastRefill = (int)$row['last_refill'];

            // 计算补充的令牌数
            $elapsed = $now - $lastRefill;
            $tokens = min($maxPerMinute, $tokens + $elapsed * $refillRate);

            if ($tokens < 1.0) {
                // 令牌不足，拒绝请求
                $pdo->commit();

                // 计算需要等待的时间
                $waitMs = (1.0 - $tokens) / $refillRate;
                $waitSeconds = intval(ceil($waitMs / 1000));
                header('Retry-After: ' . $waitSeconds);

                return false;
            }

            // 消耗一个令牌
            $tokens -= 1.0;
            $stmt = $pdo->prepare(
                'UPDATE rate_limits SET tokens = ?, last_refill = ? WHERE user_id = ?'
            );
            $stmt->execute([$tokens, $now, $userId]);
            $pdo->commit();

            return true;
        } catch (PDOException $e) {
            $pdo->rollBack();
            // 出错时放行，避免阻塞正常请求
            return true;
        }
    }
}
