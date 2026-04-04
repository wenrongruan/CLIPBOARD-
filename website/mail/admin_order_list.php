<?php
session_start();
require_once __DIR__ . '/config.php';

$isAuthed = isset($_SESSION['admin_authed']) && $_SESSION['admin_authed'] === true;
$error = null;

if (!$isAuthed && ($_SERVER['REQUEST_METHOD'] === 'POST')) {
    $password = $_POST['password'] ?? '';
    if ($password === $config['admin']['password']) {
        $_SESSION['admin_authed'] = true;
        $isAuthed = true;
    } else {
        $error = 'パスワードが正しくありません。';
    }
}

$orders = [];
if ($isAuthed) {
    try {
        $pdo = get_db_connection();
        $stmt = $pdo->query('SELECT * FROM orders ORDER BY id DESC');
        $orders = $stmt->fetchAll();
    } catch (Throwable $e) {
        $error = '注文データを取得できませんでした。';
    }
}
?>
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>注文一覧 | 管理</title>
    <style>
        body { margin:0; font-family: "Noto Sans JP","Hiragino Sans","Segoe UI",Arial,sans-serif; background:#f6f7fb; color:#1c2430; }
        .container { max-width: 1100px; margin: 40px auto 60px; padding: 0 18px; }
        .card { background:#fff; border-radius:10px; box-shadow:0 8px 22px rgba(0,0,0,0.06); padding:24px; }
        table { width:100%; border-collapse: collapse; margin-top:12px; }
        th, td { padding:10px 8px; border-bottom:1px solid #e2e7ef; text-align:left; font-size:14px; }
        th { background:#0f2342; color:#fff; position: sticky; top:0; }
        .muted { color:#5f6b7a; }
        .error { background:#ffe5e5; color:#a12626; border:1px solid #f3b1b1; padding:10px 12px; border-radius:8px; margin-bottom:12px; }
        .login-box { max-width: 420px; margin: 0 auto; }
        input[type="password"] { width:100%; padding:11px; border:1px solid #d7dfe9; border-radius:6px; font-size:14px; }
        .btn { display:inline-block; margin-top:12px; padding:12px 18px; background:#1f8f62; color:#fff; text-decoration:none; border:none; border-radius:6px; font-weight:700; cursor:pointer; }
        .status { padding:4px 8px; border-radius:6px; font-size:12px; }
        .status.pending { background:#fff3cd; color:#8a6d3b; }
        .status.paid { background:#d4edda; color:#155724; }
    </style>
</head>
<body>
    <div class="container">
        <h1>注文一覧（簡易管理）</h1>
        <?php if (!$isAuthed): ?>
            <div class="card login-box">
                <p class="muted">パスワードを入力して一覧を表示します。</p>
                <?php if ($error): ?><div class="error"><?php echo h($error); ?></div><?php endif; ?>
                <form method="post">
                    <input type="password" name="password" placeholder="管理パスワード" required>
                    <button type="submit" class="btn">ログイン</button>
                </form>
            </div>
        <?php else: ?>
            <?php if ($error): ?><div class="error"><?php echo h($error); ?></div><?php endif; ?>
            <div class="card">
                <div class="muted">表示件数：<?php echo count($orders); ?></div>
                <div style="overflow-x:auto;">
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>プラン</th>
                            <th>金額(JPY)</th>
                            <th>会社名 / 担当者</th>
                            <th>Email / 電話</th>
                            <th>支払方法</th>
                            <th>ステータス</th>
                            <th>USDT Tx / PayPal Txn</th>
                            <th>作成日時</th>
                        </tr>
                        <?php foreach ($orders as $o): ?>
                            <tr>
                                <td>#<?php echo h($o['id']); ?></td>
                                <td><?php echo h($o['plan']); ?></td>
                                <td><?php echo number_format((int)$o['amount_jpy']); ?></td>
                                <td><?php echo h($o['company_name']); ?><br><span class="muted"><?php echo h($o['contact_name']); ?></span></td>
                                <td><?php echo h($o['email']); ?><br><span class="muted"><?php echo h($o['phone']); ?></span></td>
                                <td><?php echo $o['payment_method'] === 'paypal' ? 'PayPal' : 'USDT'; ?></td>
                                <td>
                                    <?php
                                    $statusClass = $o['status'] === 'paid' ? 'paid' : 'pending';
                                    ?>
                                    <span class="status <?php echo $statusClass; ?>"><?php echo h($o['status']); ?></span>
                                </td>
                                <td>
                                    <?php if ($o['payment_method'] === 'paypal'): ?>
                                        <?php echo h($o['paypal_txn_id'] ?: '-'); ?>
                                    <?php else: ?>
                                        <?php echo h($o['usdt_tx_hash'] ?: '-'); ?>
                                    <?php endif; ?>
                                </td>
                                <td><?php echo h($o['created_at']); ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </table>
                </div>
            </div>
        <?php endif; ?>
    </div>
</body>
</html>
