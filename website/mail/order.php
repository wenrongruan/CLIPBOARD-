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

$selectedPlanKey = $_GET['plan'] ?? $_POST['plan'] ?? 'standard';
if (!array_key_exists($selectedPlanKey, $plans)) {
    $selectedPlanKey = 'standard';
}
$selectedPlan = $plans[$selectedPlanKey];

// 计算优惠后价格
$originalPrice = $selectedPlan['amount_jpy'];
$discountedPrice = $promoActive && $originalPrice > 0 ? (int)($originalPrice * (100 - $promoDiscount) / 100) : $originalPrice;

$errors = [];
$form = [
    'company_name' => '',
    'contact_name' => '',
    'email' => '',
    'phone' => '',
    'schedule_note' => '',
    'campaign_note' => '',
    'payment_method' => 'paypal',
];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    foreach ($form as $field => $default) {
        $form[$field] = trim($_POST[$field] ?? '');
    }

    if ($form['company_name'] === '') {
        $errors[] = '会社名は必須です。';
    }
    if ($form['contact_name'] === '') {
        $errors[] = 'ご担当者名は必須です。';
    }
    if ($form['email'] === '' || !filter_var($form['email'], FILTER_VALIDATE_EMAIL)) {
        $errors[] = '有効なメールアドレスをご入力ください。';
    }
    if (!in_array($form['payment_method'], ['paypal', 'usdt'], true)) {
        $errors[] = '支払方法を選択してください。';
    }
    if (!array_key_exists($selectedPlanKey, $plans)) {
        $errors[] = 'プランを選択してください。';
    }

    if (!$errors) {
        try {
            $pdo = get_db_connection();
            $stmt = $pdo->prepare("
                INSERT INTO orders (
                    plan, amount_jpy, company_name, contact_name, email, phone,
                    schedule_note, campaign_note, payment_method,
                    paypal_txn_id, usdt_tx_hash, status, created_at, updated_at
                ) VALUES (
                    :plan, :amount_jpy, :company_name, :contact_name, :email, :phone,
                    :schedule_note, :campaign_note, :payment_method,
                    NULL, NULL, 'pending_payment', NOW(), NOW()
                )
            ");
            $stmt->execute([
                ':plan' => $selectedPlanKey,
                ':amount_jpy' => $selectedPlan['amount_jpy'],
                ':company_name' => $form['company_name'],
                ':contact_name' => $form['contact_name'],
                ':email' => $form['email'],
                ':phone' => $form['phone'] ?: null,
                ':schedule_note' => $form['schedule_note'],
                ':campaign_note' => $form['campaign_note'],
                ':payment_method' => $form['payment_method'],
            ]);
            $orderId = (int)$pdo->lastInsertId();
            $_SESSION['last_order_id'] = $orderId;

            // 发送 Telegram 通知（失败也不阻断流程）
            $userIp = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? 'Unknown';
            $timestamp = date('Y-m-d H:i:s');
            $planLabel = $plans[$selectedPlanKey]['label'] ?? $selectedPlanKey;
            $amountDisplay = $selectedPlan['amount_jpy'] > 0 ? number_format($selectedPlan['amount_jpy']) . ' 円' : '成果報酬型';

            $message = "🎉 <b>新订单提交！</b>\n\n";
            $message .= "📋 订单号: #{$orderId}\n";
            $message .= "⏰ 时间: {$timestamp}\n";
            $message .= "━━━━━━━━━━━━━━━\n";
            $message .= "🏢 公司: " . h($form['company_name']) . "\n";
            $message .= "👤 联系人: " . h($form['contact_name']) . "\n";
            $message .= "📧 邮箱: " . h($form['email']) . "\n";
            $message .= "📞 电话: " . ($form['phone'] ?: '未填写') . "\n";
            $message .= "━━━━━━━━━━━━━━━\n";
            $message .= "📦 套餐: {$planLabel}\n";
            $message .= "💰 金额: {$amountDisplay}\n";
            $message .= "💳 支付: " . ($form['payment_method'] === 'paypal' ? 'PayPal' : 'USDT') . "\n";
            $message .= "━━━━━━━━━━━━━━━\n";
            $message .= "🌐 IP: {$userIp}";

            send_telegram_notification($message);

            header('Location: order_complete.php?order_id=' . $orderId);
            exit;
        } catch (Throwable $e) {
            $errors[] = 'システムエラーが発生しました。時間をおいて再度お試しください。';
            error_log('[order.php] insert failed: '.$e->getMessage());
        }
    }
}
?>
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>お申し込み | <?php echo h($config['site']['brand']); ?></title>
    <link rel="icon" href="assets/favicon.ico">
    <link rel="stylesheet" href="assets/common.css">
    <link rel="stylesheet" href="assets/index.css">
    <link rel="stylesheet" href="assets/order.css">
    <!-- Google Analytics -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-GEQS1KPWVK"></script>
    <script src="assets/ga.js"></script>
</head>
<body class="order-page"
    data-focus-contact="0"
    data-promo-active="0"
    data-promo-end="0"
    data-contact-email-revealed="0"
    data-contact-email-user=""
    data-contact-email-domain=""
>
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
            <div class="progress-step active">
                <div class="step-circle">1</div>
                <div class="step-label">情報入力</div>
            </div>
            <div class="progress-step">
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
            <h1>オンラインお申し込み</h1>
            <p class="subtitle">必要事項をご入力ください。5分ほどで完了します。</p>
            <div style="background:#e8f5f0; border:1px solid #c9ebd8; color:#155d39; padding:12px 16px; border-radius:12px; margin:12px 0 20px; font-weight:600;">
                宛先リストの提出は不要。Jlikeプラットフォームから日本の60%+へ一斉到達、送信数は全プラン100倍に拡大しています。
            </div>

            <div class="plan-box">
                <div class="plan-info">
                <div class="plan-label">選択中のプラン</div>
                <div class="plan-name"><?php echo h($selectedPlan['label']); ?></div>
            </div>
            <div class="price-section">
                <?php if ($promoActive && $originalPrice > 0): ?>
                <div class="original-price"><?php echo number_format($originalPrice); ?> 円 <span class="discount-badge"><?php echo $promoDiscount; ?>%OFF</span></div>
                <div class="price"><?php echo number_format($discountedPrice); ?> 円</div>
                <?php elseif ($originalPrice > 0): ?>
                <div class="price"><?php echo number_format($originalPrice); ?> 円</div>
                <?php else: ?>
                <div class="price">成果に応じたお支払い</div>
                <div class="price-note">初期費用0円・リスクなし</div>
                <?php endif; ?>
            </div>
        </div>

        <div class="change-plan">
            <a href="index.php#plans">← プランを変更する</a>
        </div>

        <?php if ($errors): ?>
            <div class="errors">
                <?php foreach ($errors as $err): ?>
                    <div><?php echo h($err); ?></div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>

        <div class="card">
            <form method="post" id="orderForm" data-plan-key="<?php echo h($selectedPlanKey); ?>">
                <input type="hidden" name="plan" value="<?php echo h($selectedPlanKey); ?>">

                <div class="form-group">
                    <label>会社名<span class="required">*</span></label>
                    <input type="text" name="company_name" value="<?php echo h($form['company_name']); ?>" required placeholder="株式会社〇〇">
                </div>

                <div class="form-group">
                    <label>ご担当者名<span class="required">*</span></label>
                    <input type="text" name="contact_name" value="<?php echo h($form['contact_name']); ?>" required placeholder="山田 太郎">
                </div>

                <div class="form-group">
                    <label>メールアドレス<span class="required">*</span></label>
                    <input type="email" name="email" value="<?php echo h($form['email']); ?>" required placeholder="example@company.com">
                    <div class="form-hint">確認メールをお送りします</div>
                </div>

                <div class="form-group">
                    <label>電話番号</label>
                    <input type="tel" name="phone" value="<?php echo h($form['phone']); ?>" placeholder="03-1234-5678">
                    <div class="form-hint">任意：お急ぎの場合はお電話でご連絡することがあります</div>
                </div>

                <div class="form-group">
                    <label>希望配信時期</label>
                    <input type="text" name="schedule_note" value="<?php echo h($form['schedule_note']); ?>" placeholder="例：12月中旬、なるべく早く など">
                </div>

                <div class="form-group">
                    <label>広告の概要</label>
                    <textarea name="campaign_note" placeholder="配信したい内容の概要をご記入ください（商品・サービス名、ターゲット、目的など）"><?php echo h($form['campaign_note']); ?></textarea>
                    <div class="form-hint">詳細は後からメールでご提出いただけます</div>
                </div>

                <?php if ($selectedPlanKey !== 'performance'): ?>
                <div class="form-group">
                    <label>支払方法<span class="required">*</span></label>
                    <div class="radio-group">
                        <div class="radio-option">
                            <input type="radio" name="payment_method" value="paypal" id="pay_paypal" <?php echo $form['payment_method'] === 'paypal' ? 'checked' : ''; ?>>
                            <label for="pay_paypal">💳 PayPal</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" name="payment_method" value="usdt" id="pay_usdt" <?php echo $form['payment_method'] === 'usdt' ? 'checked' : ''; ?>>
                            <label for="pay_usdt">🪙 USDT</label>
                        </div>
                    </div>
                </div>
                <?php else: ?>
                <input type="hidden" name="payment_method" value="paypal">
                <div class="form-group">
                    <div style="background: #fff8f0; border: 1px solid #ffd9b3; padding: 16px; border-radius: 8px; color: #9c4221;">
                        <strong>💡 成果報酬型プランについて</strong><br>
                        <span style="font-size: 14px;">初期費用は不要です。配信後の成果（クリック数・CV数）に応じてお支払いいただきます。詳細は担当者よりご連絡いたします。</span>
                    </div>
                </div>
                <?php endif; ?>

                <button type="submit" class="btn" data-loading-text="送信中...">
                    <?php if ($selectedPlanKey === 'performance'): ?>
                    📨 無料相談を申し込む
                    <?php else: ?>
                    🚀 送信してお支払いへ進む
                    <?php endif; ?>
                </button>
            </form>

            <div class="trust-badges">
                <div class="trust-badge"><span>🔒</span> SSL暗号化通信</div>
                <div class="trust-badge"><span>✓</span> 個人情報保護</div>
                <div class="trust-badge"><span>⚡</span> 即日対応可能</div>
            </div>
        </div>
    </div>

    <script src="assets/common.js"></script>
    <script src="assets/index.js"></script>
</body>
</html>
