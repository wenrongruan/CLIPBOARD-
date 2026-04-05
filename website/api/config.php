<?php
/**
 * API 配置文件
 * 部署时修改此文件中的配置项
 */

return [
    // 数据库配置（阿里云 RDS MySQL）
    'db' => [
        'host'     => getenv('DB_HOST') ?: '127.0.0.1',
        'port'     => getenv('DB_PORT') ?: '3306',
        'database' => getenv('DB_NAME') ?: 'shared_clipboard',
        'username' => getenv('DB_USER') ?: 'root',
        'password' => getenv('DB_PASS') ?: '',
        'charset'  => 'utf8mb4',
    ],

    // JWT 配置
    'jwt' => [
        'secret'          => getenv('JWT_SECRET') ?: 'CHANGE_ME_TO_A_RANDOM_STRING_64_CHARS',
        'access_ttl'      => 900,      // 15 分钟
        'refresh_ttl'     => 2592000,  // 30 天
        'issuer'          => 'SharedClipboard',
    ],

    // 阿里云 OSS 配置
    'oss' => [
        'access_key_id'     => getenv('OSS_KEY_ID') ?: '',
        'access_key_secret' => getenv('OSS_KEY_SECRET') ?: '',
        'endpoint'          => getenv('OSS_ENDPOINT') ?: 'oss-cn-hangzhou.aliyuncs.com',
        'bucket'            => getenv('OSS_BUCKET') ?: 'shared-clipboard',
        'url_expiry'        => 3600,  // presigned URL 有效期 1 小时
    ],

    // Lemon Squeezy 支付
    'lemonsqueezy' => [
        'api_key'        => getenv('LS_API_KEY') ?: '',
        'webhook_secret' => getenv('LS_WEBHOOK_SECRET') ?: '',
        'store_id'       => getenv('LS_STORE_ID') ?: '',
        'variants'       => [    // Lemon Squeezy 中各套餐的 variant ID
            'basic'    => getenv('LS_VARIANT_BASIC') ?: '',
            'super'    => getenv('LS_VARIANT_SUPER') ?: '',
            'ultimate' => getenv('LS_VARIANT_ULTIMATE') ?: '',
        ],
    ],

    // 订阅分层
    'plans' => [
        'free'     => ['max_items' => 30,   'max_devices' => 2,    'retention_days' => 7,   'rate_limit' => 60],
        'basic'    => ['max_items' => 200,  'max_devices' => 3,    'retention_days' => 30,  'rate_limit' => 120],
        'super'    => ['max_items' => 500,  'max_devices' => 5,    'retention_days' => 0,   'rate_limit' => 300],
        'ultimate' => ['max_items' => 1000, 'max_devices' => 9999, 'retention_days' => 0,   'rate_limit' => 600],
    ],

    // 限速配置
    'rate_limit' => [
        'enabled'    => true,
        'storage'    => 'database',  // 'database' 或 'file'
    ],

    // CORS
    'cors' => [
        'allowed_origins' => ['*'],
        'allowed_methods' => ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        'allowed_headers' => ['Content-Type', 'Authorization'],
    ],
];
