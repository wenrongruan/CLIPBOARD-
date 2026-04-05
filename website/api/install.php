<?php
/**
 * 数据库初始化脚本
 * 创建所有必要的表结构
 *
 * 使用方式：浏览器访问 install.php?key=<JWT_SECRET>
 * 密码保护：URL 参数 key 须与 config.php 中的 JWT secret 一致
 */

header('Content-Type: text/plain; charset=utf-8');

// 加载配置
$config = require __DIR__ . '/config.php';

// 简单的密码保护
$key = $_GET['key'] ?? '';
if ($key === '' || $key !== $config['jwt']['secret']) {
    http_response_code(403);
    echo "403 Forbidden: 无效的安装密钥。\n";
    echo "请使用 ?key=<JWT_SECRET> 访问此脚本。\n";
    exit;
}

// 连接数据库
try {
    $db = $config['db'];
    $dsn = sprintf(
        'mysql:host=%s;port=%s;dbname=%s;charset=%s',
        $db['host'],
        $db['port'],
        $db['database'],
        $db['charset']
    );
    $pdo = new PDO($dsn, $db['username'], $db['password'], [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    echo "[OK] 数据库连接成功\n\n";
} catch (PDOException $e) {
    echo "[FAIL] 数据库连接失败: " . $e->getMessage() . "\n";
    exit(1);
}

// 定义所有表的 DDL
$tables = [
    'users' => "
        CREATE TABLE IF NOT EXISTS users (
            id CHAR(36) NOT NULL,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(100) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_email (email)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'refresh_tokens' => "
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id BIGINT NOT NULL AUTO_INCREMENT,
            user_id CHAR(36) NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            device_id VARCHAR(64) NOT NULL DEFAULT '',
            expires_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_token_hash (token_hash),
            KEY idx_user_id (user_id),
            KEY idx_expires_at (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'devices' => "
        CREATE TABLE IF NOT EXISTS devices (
            user_id CHAR(36) NOT NULL,
            device_id VARCHAR(64) NOT NULL,
            device_name VARCHAR(100) NOT NULL DEFAULT '',
            platform VARCHAR(20) NOT NULL DEFAULT '',
            last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, device_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'clipboard_items' => "
        CREATE TABLE IF NOT EXISTS clipboard_items (
            id BIGINT NOT NULL AUTO_INCREMENT,
            user_id CHAR(36) NOT NULL,
            content_type VARCHAR(10) NOT NULL DEFAULT 'TEXT',
            text_content TEXT,
            image_storage_key VARCHAR(255) DEFAULT NULL,
            image_thumbnail MEDIUMBLOB DEFAULT NULL,
            content_hash VARCHAR(64) NOT NULL,
            preview VARCHAR(500) NOT NULL DEFAULT '',
            device_id VARCHAR(64) NOT NULL DEFAULT '',
            device_name VARCHAR(100) NOT NULL DEFAULT '',
            created_at BIGINT NOT NULL,
            is_starred TINYINT NOT NULL DEFAULT 0,
            PRIMARY KEY (id),
            UNIQUE KEY uk_user_hash (user_id, content_hash),
            KEY idx_user_created (user_id, created_at),
            KEY idx_user_starred (user_id, is_starred),
            FULLTEXT KEY ft_content (text_content, preview)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'subscriptions' => "
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id CHAR(36) NOT NULL,
            plan VARCHAR(20) NOT NULL DEFAULT 'free',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            ls_subscription_id VARCHAR(64) DEFAULT NULL,
            max_items INT NOT NULL DEFAULT 30,
            max_devices INT NOT NULL DEFAULT 2,
            current_period_end DATETIME DEFAULT NULL,
            manage_url VARCHAR(500) DEFAULT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id),
            KEY idx_ls_sub_id (ls_subscription_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'usage_stats' => "
        CREATE TABLE IF NOT EXISTS usage_stats (
            user_id CHAR(36) NOT NULL,
            item_count INT NOT NULL DEFAULT 0,
            image_bytes_used BIGINT NOT NULL DEFAULT 0,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'login_attempts' => "
        CREATE TABLE IF NOT EXISTS login_attempts (
            id BIGINT NOT NULL AUTO_INCREMENT,
            email VARCHAR(255) NOT NULL,
            ip_address VARCHAR(45) NOT NULL DEFAULT '',
            success TINYINT NOT NULL DEFAULT 0,
            attempted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_email_time (email, attempted_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",

    'rate_limits' => "
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id VARCHAR(36) NOT NULL,
            tokens FLOAT NOT NULL DEFAULT 0,
            last_refill BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ",
];

// 逐个创建表
echo "开始创建表...\n";
echo str_repeat('-', 50) . "\n";

$successCount = 0;
$failCount = 0;

foreach ($tables as $name => $ddl) {
    try {
        $pdo->prepare($ddl)->execute();
        echo "[OK]   {$name}\n";
        $successCount++;
    } catch (PDOException $e) {
        echo "[FAIL] {$name} - " . $e->getMessage() . "\n";
        $failCount++;
    }
}

echo str_repeat('-', 50) . "\n";
echo sprintf("完成: %d 成功, %d 失败, 共 %d 个表\n", $successCount, $failCount, count($tables));

if ($failCount === 0) {
    echo "\n数据库初始化完成！请删除或禁用此脚本。\n";
} else {
    echo "\n部分表创建失败，请检查错误信息。\n";
}
