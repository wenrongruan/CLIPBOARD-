<?php
/**
 * 认证控制器
 * 处理注册、登录、token 刷新、登出、获取当前用户
 */

class AuthController
{
    /**
     * POST /api/v1/auth/register
     * Body: {email, password, name?}
     */
    public static function register(): void
    {
        $input = json_decode(file_get_contents('php://input'), true);
        if (!$input) {
            Response::error('Invalid JSON body', 400);
        }

        $email    = trim($input['email'] ?? '');
        $password = $input['password'] ?? '';
        $name     = trim($input['name'] ?? '');

        // 验证邮箱
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            Response::error('Invalid email format', 400);
        }

        // 验证密码长度
        if (strlen($password) < 6) {
            Response::error('Password must be at least 6 characters', 400);
        }

        $db = Database::getInstance();

        // 检查邮箱是否已注册
        $stmt = $db->prepare('SELECT id FROM users WHERE email = :email LIMIT 1');
        $stmt->execute([':email' => $email]);
        if ($stmt->fetch()) {
            Response::error('Email already registered', 409);
        }

        $userId      = self::generateUUID();
        $passwordHash = password_hash($password, PASSWORD_BCRYPT);
        $displayName  = $name ?: explode('@', $email)[0];
        $now          = date('Y-m-d H:i:s');

        $config = require __DIR__ . '/../config.php';
        $freePlan = $config['plans']['free'];

        $db->beginTransaction();
        try {
            // 创建用户
            $stmt = $db->prepare(
                'INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
                 VALUES (:id, :email, :password_hash, :display_name, :created_at, :updated_at)'
            );
            $stmt->execute([
                ':id'            => $userId,
                ':email'         => $email,
                ':password_hash' => $passwordHash,
                ':display_name'  => $displayName,
                ':created_at'    => $now,
                ':updated_at'    => $now,
            ]);

            // 创建订阅记录（free 计划）
            $stmt = $db->prepare(
                'INSERT INTO subscriptions (user_id, plan, status, max_items, max_devices)
                 VALUES (:user_id, :plan, :status, :max_items, :max_devices)'
            );
            $stmt->execute([
                ':user_id'    => $userId,
                ':plan'       => 'free',
                ':status'     => 'active',
                ':max_items'  => $freePlan['max_items'],
                ':max_devices'=> $freePlan['max_devices'],
            ]);

            // 创建用量统计记录
            $stmt = $db->prepare(
                'INSERT INTO usage_stats (user_id, item_count, image_bytes_used)
                 VALUES (:user_id, 0, 0)'
            );
            $stmt->execute([':user_id' => $userId]);

            $db->commit();
        } catch (Exception $e) {
            $db->rollBack();
            Response::error('Registration failed: ' . $e->getMessage(), 500);
        }

        // 生成 tokens
        $accessToken  = self::createAccessToken($userId, $email);
        $refreshToken = self::createRefreshToken($db, $userId);

        Response::success([
            'token'         => $accessToken,
            'refresh_token' => $refreshToken,
            'user'          => [
                'id'           => $userId,
                'email'        => $email,
                'display_name' => $displayName,
                'created_at'   => $now,
            ],
        ]);
    }

    /**
     * POST /api/v1/auth/login
     * Body: {email, password}
     */
    public static function login(): void
    {
        $input = json_decode(file_get_contents('php://input'), true);
        if (!$input) {
            Response::error('Invalid JSON body', 400);
        }

        $email    = trim($input['email'] ?? '');
        $password = $input['password'] ?? '';

        if ($email === '' || $password === '') {
            Response::error('Email and password are required', 400);
        }

        $db = Database::getInstance();

        // 暴力破解保护：检查最近15分钟内失败次数
        $stmt = $db->prepare(
            'SELECT COUNT(*) as cnt FROM login_attempts
             WHERE email = :email AND success = 0 AND attempted_at > DATE_SUB(NOW(), INTERVAL 15 MINUTE)'
        );
        $stmt->execute([':email' => $email]);
        $attempts = (int)$stmt->fetchColumn();

        if ($attempts >= 5) {
            Response::error('Too many failed login attempts. Please try again in 15 minutes.', 429);
        }

        // 查找用户
        $stmt = $db->prepare('SELECT id, email, password_hash, display_name, created_at FROM users WHERE email = :email LIMIT 1');
        $stmt->execute([':email' => $email]);
        $user = $stmt->fetch();

        if (!$user || !password_verify($password, $user['password_hash'])) {
            self::recordLoginAttempt($db, $email, false);
            Response::error('Invalid email or password', 401);
        }

        self::recordLoginAttempt($db, $email, true);

        // 生成 tokens
        $accessToken  = self::createAccessToken($user['id'], $user['email']);
        $refreshToken = self::createRefreshToken($db, $user['id']);

        Response::success([
            'token'         => $accessToken,
            'refresh_token' => $refreshToken,
            'user'          => [
                'id'           => $user['id'],
                'email'        => $user['email'],
                'display_name' => $user['display_name'],
                'created_at'   => $user['created_at'],
            ],
        ]);
    }

    /**
     * POST /api/v1/auth/refresh
     * Body: {refresh_token}
     */
    public static function refresh(): void
    {
        $input = json_decode(file_get_contents('php://input'), true);
        $token = $input['refresh_token'] ?? '';

        if ($token === '') {
            Response::error('refresh_token is required', 400);
        }

        $db = Database::getInstance();
        $tokenHash = hash('sha256', $token);

        // 查找有效的 refresh token
        $stmt = $db->prepare(
            'SELECT rt.id, rt.user_id, u.email
             FROM refresh_tokens rt
             JOIN users u ON u.id = rt.user_id
             WHERE rt.token_hash = :hash AND rt.expires_at > NOW()
             LIMIT 1'
        );
        $stmt->execute([':hash' => $tokenHash]);
        $row = $stmt->fetch();

        if (!$row) {
            Response::error('Invalid or expired refresh token', 401);
        }

        // 轮换：删除旧 token
        $stmt = $db->prepare('DELETE FROM refresh_tokens WHERE id = :id');
        $stmt->execute([':id' => $row['id']]);

        // 创建新 tokens
        $accessToken     = self::createAccessToken($row['user_id'], $row['email']);
        $newRefreshToken = self::createRefreshToken($db, $row['user_id']);

        Response::success([
            'token'         => $accessToken,
            'refresh_token' => $newRefreshToken,
        ]);
    }

    /**
     * POST /api/v1/auth/logout
     * 需认证
     */
    public static function logout(): void
    {
        $user = Auth::requireUser();
        $db   = Database::getInstance();

        // 删除该用户的所有 refresh tokens（完整登出）
        $stmt = $db->prepare('DELETE FROM refresh_tokens WHERE user_id = :user_id');
        $stmt->execute([':user_id' => $user['id']]);

        Response::success(null, 'Logged out successfully');
    }

    /**
     * GET /api/v1/auth/me
     * 需认证
     */
    public static function me(): void
    {
        $user = Auth::requireUser();
        $db   = Database::getInstance();

        $stmt = $db->prepare('SELECT id, email, display_name, created_at FROM users WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $user['id']]);
        $row = $stmt->fetch();

        if (!$row) {
            Response::error('User not found', 404);
        }

        Response::success($row);
    }

    // ── 辅助方法 ──

    private static function recordLoginAttempt(PDO $db, string $email, bool $success): void
    {
        $stmt = $db->prepare(
            'INSERT INTO login_attempts (email, ip_address, success, attempted_at) VALUES (:email, :ip, :success, NOW())'
        );
        $stmt->execute([
            ':email'   => $email,
            ':ip'      => $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0',
            ':success' => $success ? 1 : 0,
        ]);
    }

    /**
     * 生成 UUID v4
     */
    private static function generateUUID(): string
    {
        $data = random_bytes(16);
        $data[6] = chr(ord($data[6]) & 0x0f | 0x40); // version 4
        $data[8] = chr(ord($data[8]) & 0x3f | 0x80); // variant RFC 4122
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
    }

    /**
     * 创建 access token
     */
    private static function createAccessToken(string $userId, string $email): string
    {
        $config = require __DIR__ . '/../config.php';
        return JWT::encode([
            'sub'   => $userId,
            'email' => $email,
            'type'  => 'access',
            'iat'   => time(),
            'exp'   => time() + ($config['jwt']['access_ttl'] ?? 900),
            'iss'   => $config['jwt']['issuer'] ?? 'SharedClipboard',
        ]);
    }

    /**
     * 创建 refresh token 并存储 hash
     */
    private static function createRefreshToken(PDO $db, string $userId): string
    {
        $config = require __DIR__ . '/../config.php';
        $token     = bin2hex(random_bytes(32)); // 64 字符
        $tokenHash = hash('sha256', $token);
        $expiresAt = date('Y-m-d H:i:s', time() + ($config['jwt']['refresh_ttl'] ?? 2592000));

        $stmt = $db->prepare(
            'INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at)
             VALUES (:user_id, :token_hash, :expires_at, NOW())'
        );
        $stmt->execute([
            ':user_id'    => $userId,
            ':token_hash' => $tokenHash,
            ':expires_at' => $expiresAt,
        ]);

        return $token;
    }
}
