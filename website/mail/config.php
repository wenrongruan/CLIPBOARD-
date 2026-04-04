<?php
// 基础配置
$config = [
    'db' => [
        'host' => '192.243.127.90',
        'name' => 'jlike',
        'user' => 'jlike',
        'pass' => 'hEMt8yrdJXdbLMeR',
        'charset' => 'utf8mb4',
    ],
    'paypal' => [
        'business_email' => 'v@vgogo.com', // 请替换为实际收款邮箱
        'currency' => 'JPY',
    ],
    'usdt' => [
        'trc20' => 'TWQ2hPAmrsZoygso4vkiqJJhsgFDhoZz9c',
        'erc20' => '0x873756b696ba9c2d0760178c2e696d5f64bde8f2',
        'memo_note' => '備考欄に必ず注文番号をご記入ください。',
    ],
    'site' => [
        'brand' => '日本メール放送センター',
        'domain' => 'www.jlike.com',
        'contact_email' => 'ads@jlike.com',
    ],
    'admin' => [
        'password' => 'RWRrwr123',
    ],
    'telegram' => [
        'bot_token' => '8339205881:AAH4Z_WnED_zV5OTPo159V0vKOv1f0WUQe8',
        'chat_id' => '7683339854',
    ],
];

function get_db_connection(): PDO
{
    global $config;

    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $dsn = sprintf(
        'mysql:host=%s;dbname=%s;charset=%s',
        $config['db']['host'],
        $config['db']['name'],
        $config['db']['charset']
    );

    $pdo = new PDO($dsn, $config['db']['user'], $config['db']['pass'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_TIMEOUT => 3, // avoid long hang if DB is unreachable
    ]);

    return $pdo;
}

function h(?string $value): string
{
    return htmlspecialchars($value ?? '', ENT_QUOTES, 'UTF-8');
}

/**
 * 发送 Telegram 通知
 */
function send_telegram_notification(string $message): bool
{
    global $config;

    $botToken = $config['telegram']['bot_token'] ?? '';
    $chatId = $config['telegram']['chat_id'] ?? '';

    if (empty($botToken) || empty($chatId)) {
        return false;
    }

    $url = "https://api.telegram.org/bot{$botToken}/sendMessage";

    $data = [
        'chat_id' => $chatId,
        'text' => $message,
        'parse_mode' => 'HTML',
    ];

    // cURL が使える場合は cURL を優先（短めのタイムアウトで待ちすぎ防止）
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 3,
            CURLOPT_POSTFIELDS => http_build_query($data),
            CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
        ]);
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        return $response !== false && $httpCode === 200;
    }

    // ファイルストリームのフォールバック（同じく短時間で諦める）
    $options = [
        'http' => [
            'method' => 'POST',
            'header' => 'Content-Type: application/x-www-form-urlencoded',
            'content' => http_build_query($data),
            'timeout' => 3,
        ],
    ];

    $context = stream_context_create($options);

    try {
        $result = @file_get_contents($url, false, $context);
        return $result !== false;
    } catch (Exception $e) {
        return false;
    }
}
