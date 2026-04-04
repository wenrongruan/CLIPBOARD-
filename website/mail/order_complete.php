<?php
session_start();
require_once __DIR__ . '/config.php';

// 限時優惠設定
$promoEndDate = strtotime('2025-12-31 23:59:59');
$promoActive = time() < $promoEndDate;
$promoDiscount = 20; // 20% OFF

$plans = [
    'trial' => ['label' => 'お試し 1,000,000通', 'amount_jpy' => 8000],
    'standard' => ['label' => 'スタンダード 10,000,000通', 'amount_jpy' => 60000],
    'highvolume' => ['label' => 'ハイボリューム 50,000,000通', 'amount_jpy' => 200000],
    'national' => ['label' => '全国放送 100,000,000通', 'amount_jpy' => 350000],
    'performance' => ['label' => '成果報酬型（クリック・CV課金）', 'amount_jpy' => 0],
];

$orderId = isset($_GET['order_id']) ? (int)$_GET['order_id'] : (int)($_SESSION['last_order_id'] ?? 0);
$order = null;
$infoMessage = null;
$errorMessage = null;

try {
    if ($orderId > 0) {
        $pdo = get_db_connection();
        $stmt = $pdo->prepare('SELECT * FROM orders WHERE id = :id LIMIT 1');
        $stmt->execute([':id' => $orderId]);
        $order = $stmt->fetch();
    }
} catch (Throwable $e) {
    $errorMessage = 'システムエラーが発生しました。';
}

if ($order && $_SERVER['REQUEST_METHOD'] === 'POST' && $order['payment_method'] === 'usdt') {
    $txHash = trim($_POST['usdt_tx_hash'] ?? '');
    if ($txHash !== '') {
        try {
            $pdo = get_db_connection();
            $update = $pdo->prepare('UPDATE orders SET usdt_tx_hash = :hash, updated_at = NOW() WHERE id = :id');
            $update->execute([':hash' => $txHash, ':id' => $order['id']]);
            $order['usdt_tx_hash'] = $txHash;
            $infoMessage = 'トランザクションハッシュを受け付けました。確認後にご連絡いたします。';
        } catch (Throwable $e) {
            $errorMessage = '更新に失敗しました。時間をおいて再度お試しください。';
        }
    } else {
        $errorMessage = 'トランザクションハッシュを入力してください。';
    }
}
?>
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>お申し込み完了 | <?php echo h($config['site']['brand']); ?></title>
    <link rel="icon" href="assets/favicon.ico">
    <!-- Google Analytics -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-GEQS1KPWVK"></script>
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){dataLayer.push(arguments);}
        gtag('js', new Date());
        gtag('config', 'G-GEQS1KPWVK');
        <?php if ($order): ?>
        // 追跡転換
        gtag('event', 'conversion', {
            'event_category': 'Order',
            'event_label': '<?php echo h($order['plan']); ?>',
            'value': <?php echo (int)$order['amount_jpy']; ?>
        });
        <?php endif; ?>
    </script>
    <style>
        :root {
            --nav-bg: #0b1f3a;
            --accent: #1f8f62;
            --accent-hover: #178556;
            --warning: #ff6b35;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: "Noto Sans JP","Hiragino Sans","Segoe UI",Arial,sans-serif; background:#f4f6fb; color:#1c2430; line-height: 1.6; }

        /* Header */
        header { background: var(--nav-bg); color: #fff; padding: 14px 24px; }
        .nav { display: flex; align-items: center; justify-content: space-between; max-width: 1200px; margin: 0 auto; }
        .brand { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; font-size: 16px; text-decoration: none; color: #fff; letter-spacing: 0.02em; }
        .brand-logo { height: 28px; width: auto; display: block; }
        .brand-text { color: #fff; }
        .nav-links { display: flex; gap: 8px; align-items: center; }
        .nav-links a { color: #e8edf7; padding: 8px 14px; text-decoration: none; font-size: 14px; border-radius: 6px; transition: all 0.2s; }
        .nav-links a:hover { background: rgba(255,255,255,0.1); }

        /* Progress Steps */
        .progress-bar { background: #fff; padding: 20px 24px; border-bottom: 1px solid #e5e9ef; }
        .progress-steps { display: flex; justify-content: center; gap: 0; max-width: 600px; margin: 0 auto; }
        .progress-step { flex: 1; text-align: center; position: relative; }
        .progress-step::after { content: ''; position: absolute; top: 15px; left: 50%; width: 100%; height: 2px; background: #e5e9ef; z-index: 0; }
        .progress-step:last-child::after { display: none; }
        .step-circle { width: 32px; height: 32px; border-radius: 50%; background: #e5e9ef; color: #6b7684; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; position: relative; z-index: 1; }
        .progress-step.active .step-circle { background: var(--accent); color: #fff; }
        .progress-step.completed .step-circle { background: var(--accent); color: #fff; }
        .progress-step.completed::after { background: var(--accent); }
        .step-label { font-size: 12px; color: #6b7684; margin-top: 8px; }
        .progress-step.active .step-label { color: var(--accent); font-weight: 600; }

        .container { max-width: 800px; margin: 32px auto 60px; padding: 0 18px; }

        /* Success Header */
        .success-header { text-align: center; margin-bottom: 32px; }
        .success-icon { width: 72px; height: 72px; background: linear-gradient(135deg, #e8f5f0, #d0ebe2); border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 36px; margin-bottom: 16px; }
        h1 { font-size: 26px; color: var(--nav-bg); margin-bottom: 8px; }
        .subtitle { color: #6b7684; }

        .card { background:#fff; border-radius:14px; box-shadow:0 8px 30px rgba(0,0,0,0.08); padding:28px; margin-bottom: 24px; }
        .card h2 { font-size: 18px; color: var(--nav-bg); margin-bottom: 16px; display: flex; align-items: center; gap: 10px; }

        /* Order Summary */
        .summary { background: linear-gradient(135deg, #0f2342, #1a3a5c); color:#fff; padding:24px; border-radius:12px; margin-bottom: 24px; }
        .summary-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }
        .order-number { }
        .order-number .label { font-size: 12px; opacity: 0.8; margin-bottom: 4px; }
        .order-number .value { font-size: 24px; font-weight: 700; color: #5ef3af; }
        .order-status { text-align: right; }
        .status-badge { display: inline-block; padding: 6px 14px; background: rgba(255,255,255,0.15); border-radius: 20px; font-size: 13px; font-weight: 600; }
        .summary-details { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.15); }
        .detail-item { }
        .detail-item .label { font-size: 12px; opacity: 0.7; margin-bottom: 4px; }
        .detail-item .value { font-weight: 600; }

        .muted { color:#6b7684; }
        .btn { display:inline-flex; align-items: center; justify-content: center; gap: 8px; padding:14px 24px; background:var(--accent); color:#fff; text-decoration:none; border:none; border-radius:8px; font-weight:700; font-size: 15px; cursor:pointer; transition: all 0.25s; box-shadow: 0 4px 14px rgba(31, 143, 98, 0.3); }
        .btn:hover { background: var(--accent-hover); transform: translateY(-2px); }
        .btn-full { width: 100%; }

        /* Payment Info */
        .payment-info { background: #f8fafc; border-radius: 10px; padding: 20px; margin: 16px 0; }
        .payment-info h3 { font-size: 15px; color: var(--nav-bg); margin-bottom: 12px; }
        .wallet-address { background: #fff; border: 2px solid #e5e9ef; border-radius: 8px; padding: 14px; font-family: monospace; font-size: 13px; word-break: break-all; margin: 8px 0; }
        .copy-btn { font-size: 12px; color: var(--accent); cursor: pointer; margin-left: 8px; }

        .note { background:#eef3f8; border-radius:10px; padding:16px; margin-top:16px; font-size: 14px; }
        .note.warning { background: #fff8f0; border: 1px solid #ffd9b3; color: #9c4221; }

        .message { padding:16px; border-radius:10px; margin-bottom:20px; display: flex; align-items: center; gap: 12px; }
        .message.info { background:#e8f7ef; color:#1f5b3b; border:1px solid #c9ebd8; }
        .message.error { background:#fff5f5; color:#c53030; border:1px solid #feb2b2; }

        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; font-weight: 600; margin-bottom: 8px; font-size: 14px; }
        input[type="text"] { width:100%; padding:12px 16px; border:2px solid #e5e9ef; border-radius:8px; font-size:15px; transition: border-color 0.2s; }
        input[type="text"]:focus { outline: none; border-color: var(--accent); }

        /* Next Steps */
        .next-steps { margin-top: 24px; }
        .next-steps h3 { font-size: 16px; color: var(--nav-bg); margin-bottom: 16px; }
        .steps-list { }
        .steps-list li { padding: 12px 0; border-bottom: 1px solid #e5e9ef; display: flex; align-items: flex-start; gap: 12px; }
        .steps-list li:last-child { border-bottom: none; }
        .step-num { width: 24px; height: 24px; background: var(--accent); color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; flex-shrink: 0; }

        /* Responsive */
        @media (max-width: 768px) {
            .nav-links { display: none; }
            .container { margin-top: 24px; }
            .card { padding: 20px; }
            h1 { font-size: 22px; }
            .summary { padding: 20px; }
            .summary-header { flex-direction: column; }
            .order-status { text-align: left; }
        }

        @media (max-width: 480px) {
            header { padding: 12px 16px; }
            .brand { font-size: 14px; }
            .container { padding: 0 14px; }
            .success-icon { width: 60px; height: 60px; font-size: 28px; }
            .order-number .value { font-size: 20px; }
        }
    </style>
</head>
<body>
    <header>
        <div class="nav">
            <a href="index.php" class="brand">
                <img src="assets/logo.svg" alt="<?php echo h($config['site']['brand']); ?>" class="brand-logo">
                <span class="brand-text"><?php echo h($config['site']['brand']); ?></span>
            </a>
            <div class="nav-links">
                <a href="index.php#plans">料金プラン</a>
                <a href="index.php#contact">お問い合わせ</a>
            </div>
        </div>
    </header>

    <!-- 進捗バー -->
    <div class="progress-bar">
        <div class="progress-steps">
            <div class="progress-step completed">
                <div class="step-circle">✓</div>
                <div class="step-label">情報入力</div>
            </div>
            <div class="progress-step active">
                <div class="step-circle">2</div>
                <div class="step-label">お支払い</div>
            </div>
            <div class="progress-step">
                <div class="step-circle">3</div>
                <div class="step-label">完了</div>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="success-header">
            <div class="success-icon">✓</div>
            <h1>お申し込みありがとうございました</h1>
            <p class="subtitle">ご入力内容を受け付けました。以下の手順でお支払いをお願いいたします。</p>
        </div>

        <?php if ($infoMessage): ?>
            <div class="message info">✓ <?php echo h($infoMessage); ?></div>
        <?php endif; ?>
        <?php if ($errorMessage): ?>
            <div class="message error">⚠ <?php echo h($errorMessage); ?></div>
        <?php endif; ?>

        <?php if (!$order): ?>
            <div class="card">
                <p style="text-align: center; padding: 32px 0;">
                    <span style="font-size: 48px; display: block; margin-bottom: 16px;">😕</span>
                    注文情報が見つかりませんでした。<br>
                    恐れ入りますが、再度お申し込みください。
                </p>
                <a href="order.php" class="btn btn-full">新規お申し込みへ</a>
            </div>
        <?php else: ?>
            <!-- 注文概要 -->
            <div class="summary">
                <div class="summary-header">
                    <div class="order-number">
                        <div class="label">注文番号</div>
                        <div class="value">#<?php echo h($order['id']); ?></div>
                    </div>
                    <div class="order-status">
                        <span class="status-badge">
                            <?php echo $order['status'] === 'paid' ? '✓ 支払い済み' : '⏳ 支払い待ち'; ?>
                        </span>
                    </div>
                </div>
                <div class="summary-details">
                    <div class="detail-item">
                        <div class="label">プラン</div>
                        <div class="value"><?php echo h($plans[$order['plan']]['label'] ?? $order['plan']); ?></div>
                    </div>
                    <div class="detail-item">
                        <div class="label">金額</div>
                        <div class="value"><?php echo $order['amount_jpy'] > 0 ? number_format((int)$order['amount_jpy']) . ' 円' : '成果報酬型'; ?></div>
                    </div>
                    <div class="detail-item">
                        <div class="label">お支払い方法</div>
                        <div class="value"><?php echo $order['payment_method'] === 'paypal' ? '💳 PayPal' : '🪙 USDT'; ?></div>
                    </div>
                </div>
            </div>

            <?php if ($order['plan'] === 'performance'): ?>
            <!-- 成果報酬型プランの場合 -->
            <div class="card">
                <h2>📧 担当者からのご連絡をお待ちください</h2>
                <p>成果報酬型プランをお選びいただきありがとうございます。</p>
                <p style="margin-top: 12px;">担当者より24時間以内にメール（<?php echo h($order['email']); ?>）にてご連絡いたします。</p>

                <div class="note">
                    <strong>💡 成果報酬型プランの流れ</strong><br>
                    <span style="font-size: 14px;">
                        1. 担当者とのヒアリング（配信内容・目標の確認）<br>
                        2. 配信プランのご提案・お見積もり<br>
                        3. ご承認後、配信開始<br>
                        4. 成果（クリック数・CV数）に応じたお支払い
                    </span>
                </div>

                <div class="next-steps">
                    <h3>📋 次のステップ</h3>
                    <ul class="steps-list">
                        <li>
                            <span class="step-num">1</span>
                            <div>担当者からのメールをお待ちください（24時間以内）</div>
                        </li>
                        <li>
                            <span class="step-num">2</span>
                            <div>配信したい広告内容の概要をご準備ください</div>
                        </li>
                        <li>
                            <span class="step-num">3</span>
                            <div>ご質問があればお気軽にお問い合わせください</div>
                        </li>
                    </ul>
                </div>

                <a href="index.php" class="btn btn-full" style="margin-top: 24px;">🏠 トップページへ戻る</a>
            </div>

            <?php elseif ($order['payment_method'] === 'paypal'): ?>
            <!-- PayPal支払い -->
            <div class="card">
                <h2>💳 PayPal でお支払い</h2>
                <p>以下のボタンから決済をお願いします。</p>

                <div class="payment-info">
                    <h3>お支払い情報</h3>
                    <div style="display: flex; justify-content: space-between; margin-top: 12px;">
                        <span>プラン</span>
                        <strong><?php echo h($plans[$order['plan']]['label'] ?? $order['plan']); ?></strong>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 8px;">
                        <span>お支払い金額</span>
                        <strong style="color: var(--accent); font-size: 20px;"><?php echo number_format((int)$order['amount_jpy']); ?> 円</strong>
                    </div>
                </div>

                <form action="https://www.paypal.com/cgi-bin/webscr" method="post">
                    <input type="hidden" name="cmd" value="_xclick">
                    <input type="hidden" name="business" value="<?php echo h($config['paypal']['business_email']); ?>">
                    <input type="hidden" name="item_name" value="メール広告 <?php echo h($plans[$order['plan']]['label'] ?? 'プラン'); ?>">
                    <input type="hidden" name="amount" value="<?php echo number_format((int)$order['amount_jpy'], 0, '.', ''); ?>">
                    <input type="hidden" name="currency_code" value="<?php echo h($config['paypal']['currency']); ?>">
                    <input type="hidden" name="custom" value="<?php echo h($order['id']); ?>">
                    <button type="submit" class="btn btn-full">🔒 PayPal で安全に支払う</button>
                </form>

                <div class="note">
                    <strong>💡 ご注意</strong><br>
                    <span style="font-size: 14px;">
                        ・支払い後、自動的に弊社で確認いたします<br>
                        ・決済完了メールは保管してください<br>
                        ・備考欄に注文番号 #<?php echo h($order['id']); ?> をご記入ください
                    </span>
                </div>
            </div>

            <?php else: ?>
            <!-- USDT支払い -->
            <div class="card">
                <h2>🪙 USDT でお支払い</h2>
                <p>以下いずれかのアドレスへご送金ください。</p>

                <div class="payment-info">
                    <h3>TRC20 アドレス（手数料が安い）</h3>
                    <div class="wallet-address" id="trc20Address">
                        <?php echo h($config['usdt']['trc20']); ?>
                        <span class="copy-btn" onclick="copyAddress('trc20Address')">📋 コピー</span>
                    </div>

                    <h3 style="margin-top: 16px;">ERC20 アドレス</h3>
                    <div class="wallet-address" id="erc20Address">
                        <?php echo h($config['usdt']['erc20']); ?>
                        <span class="copy-btn" onclick="copyAddress('erc20Address')">📋 コピー</span>
                    </div>

                    <div style="margin-top: 16px; padding: 12px; background: #fff; border-radius: 8px;">
                        <div style="display: flex; justify-content: space-between;">
                            <span>目安金額</span>
                            <strong style="color: var(--accent);"><?php echo number_format((int)$order['amount_jpy']); ?> 円相当</strong>
                        </div>
                        <div style="font-size: 12px; color: #6b7684; margin-top: 4px;">
                            ※当日レートで換算してください
                        </div>
                    </div>
                </div>

                <div class="note warning">
                    <strong>⚠️ 重要</strong><br>
                    <span style="font-size: 14px;">
                        ・メモ欄に注文番号 #<?php echo h($order['id']); ?> を必ずご記入ください<br>
                        ・送金後、下記フォームにトランザクションハッシュをご入力ください
                    </span>
                </div>

                <form method="post" action="<?php echo htmlspecialchars($_SERVER['REQUEST_URI']); ?>" style="margin-top: 24px;">
                    <div class="form-group">
                        <label>送金後のトランザクションハッシュ</label>
                        <input type="text" name="usdt_tx_hash" placeholder="例: 0x..." value="<?php echo h($order['usdt_tx_hash']); ?>">
                    </div>
                    <button type="submit" class="btn btn-full">📤 ハッシュを送信する</button>
                </form>
            </div>
            <?php endif; ?>

            <!-- 次のステップ（PayPal/USDT共通） -->
            <?php if ($order['plan'] !== 'performance'): ?>
            <div class="card">
                <div class="next-steps">
                    <h3>📋 お支払い後の流れ</h3>
                    <ul class="steps-list">
                        <li>
                            <span class="step-num">1</span>
                            <div>お支払いを確認次第、メールにてご連絡いたします</div>
                        </li>
                        <li>
                            <span class="step-num">2</span>
                            <div>配信原稿（広告内容）をメールでご提出ください</div>
                        </li>
                        <li>
                            <span class="step-num">3</span>
                            <div>ご希望の日時に配信を実施いたします</div>
                        </li>
                        <li>
                            <span class="step-num">4</span>
                            <div>配信完了後、レポートをお送りします</div>
                        </li>
                    </ul>
                </div>
            </div>
            <?php endif; ?>

        <?php endif; ?>
    </div>

    <script>
        function copyAddress(elementId) {
            const addressEl = document.getElementById(elementId);
            const address = addressEl.textContent.trim().split('\n')[0].trim();
            navigator.clipboard.writeText(address).then(() => {
                const copyBtn = addressEl.querySelector('.copy-btn');
                copyBtn.textContent = '✓ コピーしました';
                setTimeout(() => copyBtn.textContent = '📋 コピー', 2000);
            });
        }
    </script>
</body>
</html>
