<?php
/**
 * API 单入口路由
 * 解析 REQUEST_URI，分发到对应控制器方法
 */

// 加载配置
$config = require __DIR__ . '/config.php';

// 加载核心库
require_once __DIR__ . '/lib/Database.php';
require_once __DIR__ . '/lib/JWT.php';
require_once __DIR__ . '/lib/Response.php';
require_once __DIR__ . '/lib/Auth.php';
require_once __DIR__ . '/lib/OSS.php';
require_once __DIR__ . '/lib/RateLimiter.php';

// 加载控制器
require_once __DIR__ . '/controllers/AuthController.php';
require_once __DIR__ . '/controllers/ClipboardController.php';
require_once __DIR__ . '/controllers/DeviceController.php';
require_once __DIR__ . '/controllers/SubscriptionController.php';
require_once __DIR__ . '/controllers/WebhookController.php';

// ── CORS Headers ──
$allowedOrigins = $config['cors']['allowed_origins'] ?? ['*'];
$origin = $_SERVER['HTTP_ORIGIN'] ?? '*';

if (in_array('*', $allowedOrigins, true)) {
    header('Access-Control-Allow-Origin: *');
} elseif (in_array($origin, $allowedOrigins, true)) {
    header('Access-Control-Allow-Origin: ' . $origin);
}

header('Access-Control-Allow-Methods: ' . implode(', ', $config['cors']['allowed_methods'] ?? ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']));
header('Access-Control-Allow-Headers: ' . implode(', ', $config['cors']['allowed_headers'] ?? ['Content-Type', 'Authorization']));
header('Content-Type: application/json; charset=utf-8');

// ── OPTIONS 预检 ──
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// ── 解析路径 ──
$uri = $_SERVER['REQUEST_URI'] ?? '/';
$path = parse_url($uri, PHP_URL_PATH);
// 去掉末尾斜杠（保留根 /）
$path = rtrim($path, '/') ?: '/';

$method = $_SERVER['REQUEST_METHOD'];

// ── 路由分发 ──

// Auth 路由
if ($path === '/api/v1/auth/register' && $method === 'POST') {
    AuthController::register();
} elseif ($path === '/api/v1/auth/login' && $method === 'POST') {
    AuthController::login();
} elseif ($path === '/api/v1/auth/refresh' && $method === 'POST') {
    AuthController::refresh();
} elseif ($path === '/api/v1/auth/logout' && $method === 'POST') {
    AuthController::logout();
} elseif ($path === '/api/v1/auth/me' && $method === 'GET') {
    AuthController::me();
}

// Device 路由
elseif ($path === '/api/v1/devices' && $method === 'GET') {
    DeviceController::listDevices();
} elseif ($path === '/api/v1/devices' && $method === 'POST') {
    DeviceController::register();
} elseif (preg_match('#^/api/v1/devices/([a-zA-Z0-9_-]+)$#', $path, $m) && $method === 'DELETE') {
    DeviceController::delete($m[1]);
}

// Clipboard 路由
elseif ($path === '/api/v1/clipboard/batch' && $method === 'POST') {
    ClipboardController::batchCreate();
} elseif ($path === '/api/v1/clipboard/sync' && $method === 'GET') {
    ClipboardController::sync();
} elseif ($path === '/api/v1/clipboard/items' && $method === 'GET') {
    ClipboardController::list();
} elseif (preg_match('#^/api/v1/clipboard/(\d+)/star$#', $path, $m) && $method === 'PUT') {
    ClipboardController::toggleStar((int)$m[1]);
} elseif (preg_match('#^/api/v1/clipboard/(\d+)/image$#', $path, $m) && $method === 'POST') {
    ClipboardController::uploadImage((int)$m[1]);
} elseif (preg_match('#^/api/v1/clipboard/(\d+)/image-url$#', $path, $m) && $method === 'GET') {
    ClipboardController::getImageUrl((int)$m[1]);
} elseif (preg_match('#^/api/v1/clipboard/(\d+)$#', $path, $m) && $method === 'DELETE') {
    ClipboardController::delete((int)$m[1]);
}

// Subscription 路由
elseif ($path === '/api/v1/subscription' && $method === 'GET') {
    SubscriptionController::status();
} elseif ($path === '/api/v1/subscription/checkout' && $method === 'POST') {
    SubscriptionController::checkout();
}

// Webhook 路由
elseif ($path === '/api/v1/webhooks/lemonsqueezy' && $method === 'POST') {
    WebhookController::handleLemonSqueezy();
}

// 404
else {
    Response::error('Not Found', 404);
}
