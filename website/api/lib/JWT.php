<?php
/**
 * 手动实现 JWT（HMAC-SHA256）
 * 不依赖第三方库，PHP 7.4 兼容
 */

class JWT
{
    /**
     * 创建 JWT token
     *
     * @param array $payload 载荷数据（如 user_id, email 等）
     * @return string 签名后的 JWT 字符串
     */
    public static function encode(array $payload): string
    {
        $jwtConfig = self::getJwtConfig();

        $header = [
            'alg' => 'HS256',
            'typ' => 'JWT',
        ];

        // 自动添加标准字段
        $now = time();
        $payload['iat'] = $now;
        $payload['iss'] = $jwtConfig['issuer'];

        // 如果没有显式设置 exp，使用 access_ttl
        if (!isset($payload['exp'])) {
            $payload['exp'] = $now + $jwtConfig['access_ttl'];
        }

        $headerEncoded = self::base64UrlEncode(json_encode($header));
        $payloadEncoded = self::base64UrlEncode(json_encode($payload));

        $signature = hash_hmac('sha256', $headerEncoded . '.' . $payloadEncoded, $jwtConfig['secret'], true);
        $signatureEncoded = self::base64UrlEncode($signature);

        return $headerEncoded . '.' . $payloadEncoded . '.' . $signatureEncoded;
    }

    /**
     * 验证并解码 JWT token
     *
     * @param string $token JWT 字符串
     * @return array|null 成功返回 payload 数组，失败返回 null
     */
    public static function decode(string $token): ?array
    {
        $jwtConfig = self::getJwtConfig();

        $parts = explode('.', $token);
        if (count($parts) !== 3) {
            return null;
        }

        [$headerEncoded, $payloadEncoded, $signatureEncoded] = $parts;

        // 验证签名
        $expectedSignature = hash_hmac('sha256', $headerEncoded . '.' . $payloadEncoded, $jwtConfig['secret'], true);
        $expectedSignatureEncoded = self::base64UrlEncode($expectedSignature);

        if (!hash_equals($expectedSignatureEncoded, $signatureEncoded)) {
            return null;
        }

        // 解码 header
        $header = json_decode(self::base64UrlDecode($headerEncoded), true);
        if ($header === null || ($header['alg'] ?? '') !== 'HS256') {
            return null;
        }

        // 解码 payload
        $payload = json_decode(self::base64UrlDecode($payloadEncoded), true);
        if ($payload === null) {
            return null;
        }

        // 验证过期时间
        if (isset($payload['exp']) && $payload['exp'] < time()) {
            return null;
        }

        // 验证发行者
        if (isset($payload['iss']) && $payload['iss'] !== $jwtConfig['issuer']) {
            return null;
        }

        return $payload;
    }

    /**
     * 缓存 JWT 配置
     */
    private static function getJwtConfig(): array
    {
        static $jwtConfig = null;
        if ($jwtConfig === null) {
            $config = require __DIR__ . '/../config.php';
            $jwtConfig = $config['jwt'];
        }
        return $jwtConfig;
    }

    /**
     * Base64 URL 安全编码
     */
    private static function base64UrlEncode(string $data): string
    {
        return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
    }

    /**
     * Base64 URL 安全解码
     */
    private static function base64UrlDecode(string $data): string
    {
        $remainder = strlen($data) % 4;
        if ($remainder !== 0) {
            $data .= str_repeat('=', 4 - $remainder);
        }
        return base64_decode(strtr($data, '-_', '+/'));
    }
}
