<?php
/**
 * 认证中间件
 * 从 Authorization Bearer token 解析用户
 */

class Auth
{
    /** @var array|null|false 缓存的用户数据，null=未查询，false=查询过但无效 */
    private static $cachedUser = null;

    /**
     * 从 Authorization Bearer token 解析用户
     * 查数据库确认用户存在，返回用户行
     *
     * @return array|null 用户数据或 null
     */
    public static function getUser(): ?array
    {
        // 使用缓存避免重复查库
        if (self::$cachedUser !== null) {
            return self::$cachedUser === false ? null : self::$cachedUser;
        }

        $token = self::extractBearerToken();
        if ($token === null) {
            self::$cachedUser = false;
            return null;
        }

        $payload = JWT::decode($token);
        if ($payload === null) {
            self::$cachedUser = false;
            return null;
        }

        $userId = $payload['sub'] ?? null;
        if ($userId === null) {
            self::$cachedUser = false;
            return null;
        }

        // 查数据库确认用户存在
        try {
            $pdo = Database::getInstance();
            $stmt = $pdo->prepare(
                'SELECT id, email, display_name, created_at FROM users WHERE id = ? LIMIT 1'
            );
            $stmt->execute([$userId]);
            $user = $stmt->fetch();

            if ($user === false) {
                self::$cachedUser = false;
                return null;
            }

            // 附加 token payload 中的额外信息
            $user['_token_payload'] = $payload;

            self::$cachedUser = $user;
            return $user;
        } catch (PDOException $e) {
            self::$cachedUser = false;
            return null;
        }
    }

    /**
     * 要求用户认证，失败直接返回 401 错误
     *
     * @return array 用户数据
     */
    public static function requireUser(): array
    {
        $user = self::getUser();
        if ($user === null) {
            Response::error('未认证或 token 无效', 401);
        }
        return $user;
    }

    /**
     * 重置缓存（用于测试或切换用户场景）
     */
    public static function resetCache(): void
    {
        self::$cachedUser = null;
    }

    /**
     * 从请求头中提取 Bearer token
     *
     * @return string|null
     */
    private static function extractBearerToken(): ?string
    {
        $header = null;

        // 尝试从 $_SERVER 获取 Authorization header
        if (isset($_SERVER['HTTP_AUTHORIZATION'])) {
            $header = $_SERVER['HTTP_AUTHORIZATION'];
        } elseif (isset($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
            $header = $_SERVER['REDIRECT_HTTP_AUTHORIZATION'];
        } elseif (function_exists('apache_request_headers')) {
            $headers = apache_request_headers();
            // 兼容大小写
            foreach ($headers as $key => $value) {
                if (strtolower($key) === 'authorization') {
                    $header = $value;
                    break;
                }
            }
        }

        if ($header === null) {
            return null;
        }

        // 检查是否是 Bearer 格式
        if (strpos($header, 'Bearer ') !== 0) {
            return null;
        }

        $token = substr($header, 7);
        return ($token !== '' && $token !== false) ? $token : null;
    }
}
