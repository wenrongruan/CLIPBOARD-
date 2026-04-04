<?php
session_start();
require_once __DIR__ . '/config.php';

// 簡易検証コード：常に最新を生成（GETでもPOSTでも毎リクエスト更新）
$currentContactCode = '';
$isContactCodeSubmit = ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['contact_code_submit']));
if ($isContactCodeSubmit) {
    // 直前に発行したコードで検証
    $currentContactCode = $_SESSION['contact_code'] ?? '';
} else {
    // 非提出時は新しいコードを発行
    $currentContactCode = (string)random_int(10000, 99999);
    $_SESSION['contact_code'] = $currentContactCode;
}

// お問い合わせフォーム用検証コード
$currentFormCode = '';
$isFormCodeSubmit = ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['contact_form_submit']));
if ($isFormCodeSubmit) {
    // 提交时从 session 读取之前保存的验证码
    $currentFormCode = $_SESSION['form_code'] ?? '';
    // 调试：如果 session 中没有验证码，说明 session 有问题
    if ($currentFormCode === '') {
        error_log('Session form_code is empty. Session ID: ' . session_id());
    }
} else {
    // 非提交请求时生成新验证码
    $currentFormCode = (string)random_int(10000, 99999);
    $_SESSION['form_code'] = $currentFormCode;
}
$contactEmailRevealed = false;
$contactError = null;
$contactFormSuccess = false;
$contactFormError = null;
$contactEmail = $config['site']['contact_email'] ?? 'ads@jlike.com';
[$contactEmailUser, $contactEmailDomain] = array_pad(explode('@', $contactEmail, 2), 2, '');
if ($contactEmailDomain === '') {
    $contactEmailUser = 'ads';
    $contactEmailDomain = 'jlike.com';
}
if ($isContactCodeSubmit) {
    $input = trim($_POST['verify_code'] ?? '');
    if ($input === $currentContactCode) {
        $contactEmailRevealed = true;
        $_SESSION['contact_code'] = (string)random_int(10000, 99999); // 次回用に更新

        // 发送 Telegram 通知
        $userIp = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? 'Unknown';
        $userAgent = $_SERVER['HTTP_USER_AGENT'] ?? 'Unknown';
        $timestamp = date('Y-m-d H:i:s');

        $message = "📧 <b>有人获取了邮件地址</b>\n\n";
        $message .= "⏰ 时间: {$timestamp}\n";
        $message .= "🌐 IP: {$userIp}\n";
        $message .= "📱 设备: " . mb_substr($userAgent, 0, 100) . "\n";
        $message .= "📍 页面: 首页联系方式";

        send_telegram_notification($message);
    } else {
        $contactError = 'コードが正しくありません。';
        // 失敗時も次回用に更新
        $_SESSION['contact_code'] = (string)random_int(10000, 99999);
    }
}

// 联系表格提交处理
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['contact_form_submit'])) {
    $formCompany = trim($_POST['form_company'] ?? '');
    $formContact = trim($_POST['form_contact'] ?? '');
    $formEmail = trim($_POST['form_email'] ?? '');
    $formMessage = trim($_POST['form_message'] ?? '');
    $formVerifyCode = trim($_POST['form_verify_code'] ?? '');

    // 验证码检查
    if ($currentFormCode === '') {
        // Session 丢失，无法验证
        $contactFormError = 'セッションの有効期限が切れました。ページを更新して再度お試しください。';
        $_SESSION['form_code'] = (string)random_int(10000, 99999);
    } elseif ($formVerifyCode !== $currentFormCode) {
        $contactFormError = '検証コードが正しくありません。';
        // 失敗時も次回用に更新
        $_SESSION['form_code'] = (string)random_int(10000, 99999);
    } elseif ($formCompany === '' || $formContact === '' || $formEmail === '' || $formMessage === '') {
        $contactFormError = '全ての必須項目をご入力ください。';
        $_SESSION['form_code'] = (string)random_int(10000, 99999);
    } elseif (!filter_var($formEmail, FILTER_VALIDATE_EMAIL)) {
        $contactFormError = '有効なメールアドレスをご入力ください。';
        $_SESSION['form_code'] = (string)random_int(10000, 99999);
    } else {
        // 发送 Telegram 通知
        $userIp = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? 'Unknown';
        $timestamp = date('Y-m-d H:i:s');

        $message = "💬 <b>新的咨询表单提交！</b>\n\n";
        $message .= "⏰ 时间: {$timestamp}\n";
        $message .= "━━━━━━━━━━━━━━━\n";
        $message .= "🏢 公司: " . h($formCompany) . "\n";
        $message .= "👤 联系人: " . h($formContact) . "\n";
        $message .= "📧 邮箱: " . h($formEmail) . "\n";
        $message .= "━━━━━━━━━━━━━━━\n";
        $message .= "📝 内容:\n" . h($formMessage) . "\n";
        $message .= "━━━━━━━━━━━━━━━\n";
        $message .= "🌐 IP: {$userIp}";

        if (send_telegram_notification($message)) {
            $contactFormSuccess = true;
            $_SESSION['form_code'] = (string)random_int(10000, 99999);
        } else {
            $contactFormError = '送信に失敗しました。しばらくしてから再度お試しください。';
            $_SESSION['form_code'] = (string)random_int(10000, 99999);
        }
    }
}

// 限時優惠設定（結束日期）
$promoEndDate = strtotime('2025-12-31 23:59:59');
$promoActive = time() < $promoEndDate;
$promoDiscount = 20; // 20% OFF
$shouldFocusContact = (bool)($contactEmailRevealed || $contactFormSuccess || $contactFormError || $contactError);
?>
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo h($config['site']['brand']); ?> | 全日本メール広告放送サービス</title>
    <link rel="icon" href="assets/favicon.ico">
    <link rel="stylesheet" href="assets/common.css">
    <link rel="stylesheet" href="assets/index.css">
    <!-- Google Analytics -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-GEQS1KPWVK"></script>
    <script src="assets/ga.js"></script>
</head>
<body
    data-focus-contact="<?php echo $shouldFocusContact ? '1' : '0'; ?>"
    data-promo-active="<?php echo $promoActive ? '1' : '0'; ?>"
    data-promo-end="<?php echo $promoActive ? ($promoEndDate * 1000) : 0; ?>"
    data-contact-email-revealed="<?php echo $contactEmailRevealed ? '1' : '0'; ?>"
    data-contact-email-user="<?php echo h($contactEmailUser); ?>"
    data-contact-email-domain="<?php echo h($contactEmailDomain); ?>"
>
    <!-- 限時優惠橫幅 -->
    <?php if ($promoActive): ?>
    <div class="promo-banner">
        <span>🎉 期間限定キャンペーン実施中！全プラン<?php echo $promoDiscount; ?>%OFF</span>
        <div class="countdown" id="countdown">
            <span class="time-box" id="days">--日</span>
            <span class="time-box" id="hours">--時</span>
            <span class="time-box" id="mins">--分</span>
        </div>
    </div>
    <?php endif; ?>

    <header>
        <div class="nav">
            <a href="index.php" class="brand">
                <img src="assets/logo.svg" alt="<?php echo h($config['site']['brand']); ?>" class="brand-logo">
                <span class="brand-text"><?php echo h($config['site']['brand']); ?></span>
            </a>
            <button class="mobile-menu-btn" onclick="toggleMenu()" aria-label="メニュー">☰</button>
            <div class="nav-links" id="navLinks">
                <a href="#services">サービス概要</a>
                <a href="#plans">料金プラン</a>
                <a href="#flow">ご利用の流れ</a>
                <a href="#payment">お支払い方法</a>
                <a href="#contact">お問い合わせ</a>
                <a href="order.php" class="nav-cta">無料相談</a>
            </div>
        </div>
    </header>

    <section class="hero" id="top">
        <div class="content">
            <h1>日本全国に一斉配信できる<br>メール広告放送サービス</h1>
            <p>docomo・au・SoftBank・主要プロバイダに対応。<br>アプリ・ゲーム・EC・キャンペーンの認知拡大を強力にサポートします。</p>
            <div class="buttons">
                <a class="btn btn-primary" href="#plans">📊 料金プランを見る</a>
                <a class="btn btn-secondary" href="order.php">✨ 今すぐ申し込む</a>
            </div>
            <div class="hero-highlight">
                <span class="badge">覆盖力</span>
                <span>Jlike 发送无需提供收件人邮箱，直连平台数据库，一次触达日本 60%+ 有效邮箱人群。</span>
            </div>
        </div>
    </section>

    <!-- 実績統計 -->
    <div class="stats-bar">
        <div class="stats-grid">
            <div class="stat-item">
                <div class="stat-number">500+</div>
                <div class="stat-label">導入企業数</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">1億+</div>
                <div class="stat-label">累計配信数</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">98%</div>
                <div class="stat-label">顧客満足度</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">24h</div>
                <div class="stat-label">サポート対応</div>
            </div>
        </div>
    </div>

    <section class="section" id="services">
        <div class="content">
            <h2>サービス概要</h2>
            <p class="section-subtitle">日本全国への大量メール配信を、シンプルかつ効果的に実現します</p>
            <div class="cards">
                <div class="card">
                    <div class="card-icon">📧</div>
                    <h3>全国放送型メール配信</h3>
                    <p>日本全国の携帯キャリアと主要メールプロバイダに対して一斉配信するモデルです。広範囲に素早くリーチできます。</p>
                </div>
                <div class="card">
                    <div class="card-icon">📱</div>
                    <h3>対応キャリア・プロバイダ</h3>
                    <p>docomo / au / SoftBank / OCN / plala など主要経路を網羅し、幅広いターゲットへの到達を支援します。</p>
                </div>
                <div class="card">
                    <div class="card-icon">🎯</div>
                    <h3>利用シーン</h3>
                    <p>APP・ゲーム・EC・ブランドキャンペーン告知・短期プロモーションなど、即時認知拡大に最適です。</p>
                </div>
                <div class="card">
                    <div class="card-icon">🌐</div>
                    <h3>宛先リスト不要</h3>
                    <p>Jlike 送信は受信者リストの提供不要。プラットフォーム保有の活用可能なメールプールから、日本の 60% 以上に一斉到達します。</p>
                </div>
            </div>

            <h2 style="margin-top:72px;">特徴 / 優位性</h2>
            <p class="section-subtitle">安定性と効果を両立した配信インフラをご提供</p>
            <div class="cards">
                <div class="card">
                    <div class="card-icon">🚀</div>
                    <h3>大量配信インフラ</h3>
                    <p>大量配信に対応した専用インフラを保有し、ピーク時も安定運用を実現します。</p>
                </div>
                <div class="card">
                    <div class="card-icon">🔒</div>
                    <h3>複数 IP・MX で安定</h3>
                    <p>複数 IP / MX を用いた冗長構成で、到達性を確保しながら継続的な配信が可能です。</p>
                </div>
                <div class="card">
                    <div class="card-icon">📊</div>
                    <h3>簡易レポート</h3>
                    <p>配信通数・エラー数を中心とした簡易レポートを提供し、効果の可視化をサポートします。</p>
                </div>
            </div>
        </div>
    </section>

    <section class="section" id="plans">
        <div class="content">
            <h2>料金プラン</h2>
            <p class="section-subtitle">ご予算や目的に合わせて最適なプランをお選びください</p>
            <div style="max-width:820px; margin:0 auto 28px; text-align:center; background:#e8f5f0; border:1px solid #c9ebd8; color:#155d39; padding:12px 16px; border-radius:12px; font-weight:600;">
                宛先リストは不要。送信数をすべて100倍に拡大し、日本の60%+に一斉リーチ。例：100万通でもキャンペーン価格 ¥<?php echo $promoActive ? number_format(8000 * (100 - $promoDiscount) / 100) : number_format(8000); ?>。
            </div>
            <?php if ($promoActive): ?>
            <div style="text-align:center; margin-bottom:32px;">
                <span class="plan-discount" style="font-size:14px; padding:8px 16px;">🎁 今なら全プラン <?php echo $promoDiscount; ?>%OFF！キャンペーン終了まであとわずか</span>
            </div>
            <?php endif; ?>
            <div class="plan-cards">
                <!-- お試しプラン -->
                <div class="plan-card">
                    <div class="plan-name">お試し</div>
                    <div class="plan-volume">1,000,000 通</div>
                    <?php if ($promoActive): ?>
                    <div class="plan-original-price">通常 ¥8,000</div>
                    <div class="plan-discount"><?php echo $promoDiscount; ?>%OFF</div>
                    <div class="plan-price"><span class="currency">¥</span><?php echo number_format(8000 * (100 - $promoDiscount) / 100); ?></div>
                    <?php else: ?>
                    <div class="plan-price"><span class="currency">¥</span>8,000</div>
                    <?php endif; ?>
                    <ul class="plan-features">
                        <li>初回テストに最適</li>
                        <li>小規模配信向け</li>
                        <li>簡易レポート付き</li>
                    </ul>
                    <a class="btn btn-outline" href="order.php?plan=trial">このプランで申し込む</a>
                </div>

                <!-- スタンダードプラン（人気） -->
                <div class="plan-card featured">
                    <div class="plan-name">スタンダード</div>
                    <div class="plan-volume">10,000,000 通</div>
                    <?php if ($promoActive): ?>
                    <div class="plan-original-price">通常 ¥60,000</div>
                    <div class="plan-discount"><?php echo $promoDiscount; ?>%OFF</div>
                    <div class="plan-price"><span class="currency">¥</span><?php echo number_format(60000 * (100 - $promoDiscount) / 100); ?></div>
                    <?php else: ?>
                    <div class="plan-price"><span class="currency">¥</span>60,000</div>
                    <?php endif; ?>
                    <ul class="plan-features">
                        <li>最も人気のプラン</li>
                        <li>汎用的に活用可能</li>
                        <li>詳細レポート付き</li>
                        <li>優先サポート</li>
                    </ul>
                    <a class="btn btn-primary" href="order.php?plan=standard">このプランで申し込む</a>
                </div>

                <!-- ハイボリュームプラン -->
                <div class="plan-card">
                    <div class="plan-name">ハイボリューム</div>
                    <div class="plan-volume">50,000,000 通</div>
                    <?php if ($promoActive): ?>
                    <div class="plan-original-price">通常 ¥200,000</div>
                    <div class="plan-discount"><?php echo $promoDiscount; ?>%OFF</div>
                    <div class="plan-price"><span class="currency">¥</span><?php echo number_format(200000 * (100 - $promoDiscount) / 100); ?></div>
                    <?php else: ?>
                    <div class="plan-price"><span class="currency">¥</span>200,000</div>
                    <?php endif; ?>
                    <ul class="plan-features">
                        <li>大規模キャンペーン向け</li>
                        <li>全国告知に最適</li>
                        <li>詳細レポート付き</li>
                        <li>専任担当者サポート</li>
                    </ul>
                    <a class="btn btn-outline" href="order.php?plan=highvolume">このプランで申し込む</a>
                </div>

                <!-- 全国放送プラン -->
                <div class="plan-card">
                    <div class="plan-name">全国放送</div>
                    <div class="plan-volume">100,000,000 通〜</div>
                    <?php if ($promoActive): ?>
                    <div class="plan-original-price">通常 ¥350,000〜</div>
                    <div class="plan-discount"><?php echo $promoDiscount; ?>%OFF</div>
                    <div class="plan-price"><span class="currency">¥</span><?php echo number_format(350000 * (100 - $promoDiscount) / 100); ?>〜</div>
                    <?php else: ?>
                    <div class="plan-price"><span class="currency">¥</span>350,000〜</div>
                    <?php endif; ?>
                    <ul class="plan-features">
                        <li>カスタム配信設計</li>
                        <li>個別お見積もり</li>
                        <li>詳細レポート付き</li>
                        <li>専任担当者サポート</li>
                    </ul>
                    <a class="btn btn-outline" href="order.php?plan=national">お見積もり依頼</a>
                </div>

                <!-- 成果報酬型プラン（新規追加） -->
                <div class="plan-card performance">
                    <div class="plan-name">成果報酬型</div>
                    <div class="plan-volume">クリック・CV課金</div>
                    <div class="plan-price" style="font-size:24px;">成果に応じた<br>お支払い</div>
                    <ul class="plan-features">
                        <li>初期費用0円</li>
                        <li>クリック単価 ¥50〜</li>
                        <li>CV単価は応相談</li>
                        <li>リスクなく始められる</li>
                        <li>効果測定レポート付き</li>
                    </ul>
                    <a class="btn btn-primary" href="order.php?plan=performance" style="background: var(--warning);">無料相談する</a>
                </div>
            </div>
        </div>
    </section>

    <section class="section" id="flow" style="background: linear-gradient(180deg, #eef2f7, #fff);">
        <div class="content">
            <h2>ご利用の流れ</h2>
            <p class="section-subtitle">最短即日で配信開始！シンプルな4ステップ</p>
            <div class="steps">
                <div class="step">
                    <div class="step-number">1</div>
                    <h3>オンラインでお申し込み</h3>
                    <p>必要事項をフォームに入力して送信するだけ。5分で完了します。</p>
                    <a href="order.php" class="btn btn-primary" style="padding:10px 18px; font-size:13px; margin-top:12px;">今すぐ申し込む →</a>
                </div>
                <div class="step">
                    <div class="step-number">2</div>
                    <h3>お支払い</h3>
                    <p>PayPal または USDT でお支払い。成果報酬型は配信後のお支払いも可能です。</p>
                </div>
                <div class="step">
                    <div class="step-number">3</div>
                    <h3>配信原稿のご提出</h3>
                    <p>メールでご案内いたします。フォーム内での記載も可能です。</p>
                </div>
                <div class="step">
                    <div class="step-number">4</div>
                    <h3>配信実施 + レポート</h3>
                    <p>配信完了後に詳細レポートをお送りします。効果測定も万全です。</p>
                </div>
            </div>
        </div>
    </section>

    <!-- お客様の声（社会証明） -->
    <section class="section" id="testimonials">
        <div class="content">
            <h2>お客様の声</h2>
            <p class="section-subtitle">実際にご利用いただいたお客様からの評価</p>
            <div class="testimonials">
                <div class="testimonial">
                    <div class="testimonial-content">
                        初めてのメール広告で不安でしたが、担当者の方が丁寧にサポートしてくれました。結果も期待以上で、アプリのダウンロード数が2倍になりました。
                    </div>
                    <div class="testimonial-author">
                        <div class="testimonial-avatar">T</div>
                        <div class="testimonial-info">
                            <div class="testimonial-name">田中様</div>
                            <div class="testimonial-company">アプリ開発会社 マーケティング担当</div>
                        </div>
                    </div>
                </div>
                <div class="testimonial">
                    <div class="testimonial-content">
                        成果報酬型プランでリスクなく始められたのが良かったです。クリック単価も良心的で、ROIが非常に高かったです。継続利用を決めました。
                    </div>
                    <div class="testimonial-author">
                        <div class="testimonial-avatar">S</div>
                        <div class="testimonial-info">
                            <div class="testimonial-name">佐藤様</div>
                            <div class="testimonial-company">EC事業者 代表取締役</div>
                        </div>
                    </div>
                </div>
                <div class="testimonial">
                    <div class="testimonial-content">
                        他社と比較して配信スピードが早く、レポートも詳細でした。キャンペーン告知に最適なサービスだと思います。また利用したいです。
                    </div>
                    <div class="testimonial-author">
                        <div class="testimonial-avatar">M</div>
                        <div class="testimonial-info">
                            <div class="testimonial-name">松本様</div>
                            <div class="testimonial-company">ゲーム会社 プロモーション部</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="section" id="payment">
        <div class="content">
            <h2>お支払い方法</h2>
            <p class="section-subtitle">便利で安全なお支払い方法をご用意しています</p>
            <div class="payment-box">
                <div class="card">
                    <div class="card-icon">💳</div>
                    <h3>PayPal 即時決済</h3>
                    <p>世界中で使われる安全な決済システム。クレジットカードも利用可能です。備考欄に注文番号をご記入ください。</p>
                </div>
                <div class="card">
                    <div class="card-icon">🪙</div>
                    <h3>暗号資産 USDT</h3>
                    <p>TRC20 / ERC20 に対応。手数料を抑えた送金が可能です。メモ欄に注文番号を記載のうえ、トランザクションハッシュをご連絡ください。</p>
                </div>
                <div class="card">
                    <div class="card-icon">📈</div>
                    <h3>成果報酬型</h3>
                    <p>初期費用0円。配信後の成果に応じたお支払いなので、リスクなく始められます。まずはご相談ください。</p>
                </div>
            </div>
        </div>
    </section>

    <!-- 信頼性セクション -->
    <section class="section trust-section">
        <div class="content">
            <h2>選ばれる理由</h2>
            <p class="section-subtitle">多くの企業様にご信頼いただいている理由</p>
            <div class="trust-grid">
                <div class="trust-card">
                    <div class="trust-icon">🛡️</div>
                    <h3>安心のセキュリティ</h3>
                    <p>お客様の情報は厳重に管理。配信データも安全に保護されています。</p>
                </div>
                <div class="trust-card">
                    <div class="trust-icon">⚡</div>
                    <h3>スピード配信</h3>
                    <p>お申込みから最短即日で配信開始。急なキャンペーンにも対応可能です。</p>
                </div>
                <div class="trust-card">
                    <div class="trust-icon">🤝</div>
                    <h3>専任サポート</h3>
                    <p>経験豊富な担当者が最適な配信プランをご提案。24時間体制でサポートします。</p>
                </div>
            </div>
        </div>
    </section>

    <section class="section" id="contact">
        <div class="content">
            <h2>お問い合わせ</h2>
            <p class="section-subtitle">ご質問・ご相談はお気軽にどうぞ。24時間以内にご返信いたします。</p>
            <div class="contact">
                <div class="card">
                    <h3 style="margin-bottom:16px;">📧 メールでのお問い合わせ</h3>
                    <p style="margin-bottom:16px;">以下のボタンからメールアドレスを取得してください。</p>
                    <?php if ($contactError): ?>
                        <div class="errors" style="margin:10px 0;"><?php echo h($contactError); ?></div>
                    <?php endif; ?>
                    <?php if (!$contactEmailRevealed): ?>
                        <form method="post" action="<?php echo htmlspecialchars($_SERVER['PHP_SELF']); ?>#contact" style="margin-top:8px;">
                            <input type="hidden" name="contact_code_submit" value="1">
                            <div style="color:var(--muted); margin-bottom:12px; font-size:14px;">表示されたコードを入力してください：</div>
                            <div style="display:flex; gap:10px; align-items:center; flex-wrap: wrap;">
                                <div style="font-weight:700; letter-spacing:0.1em; padding:10px 16px; background:linear-gradient(135deg, #eef2f7, #e5eaf2); border-radius:8px; font-size:18px;">
                                    <?php echo h($currentContactCode); ?>
                                </div>
                                <input type="text" name="verify_code" placeholder="コードを入力" required style="max-width:140px; padding:10px 14px;">
                                <button class="btn btn-primary" type="submit" name="contact_code_submit" value="1" data-loading-text="表示中..." style="padding:10px 18px;">表示する</button>
                            </div>
                        </form>
                    <?php else: ?>
                        <div style="background:#e8f5f0; padding:16px; border-radius:10px; margin-bottom:16px;">
                            <div style="font-size:13px; color:var(--muted); margin-bottom:6px;">メールアドレス</div>
                            <div id="contact-email" style="font-size:16px; font-weight:600;"><?php echo h($config['site']['brand']); ?> &lt;<span data-user="<?php echo h($contactEmailUser); ?>" data-domain="<?php echo h($contactEmailDomain); ?>"><?php echo h($contactEmail); ?></span>&gt;</div>
                        </div>
                        <div style="display:flex; gap:12px; flex-wrap: wrap;">
                            <button class="btn btn-primary" type="button" id="copy-email" data-loading-text="コピー中...">📋 コピーする</button>
                            <a class="btn btn-secondary" id="mailto-link" href="#" style="background:var(--nav-bg); color:#fff; border:none;">✉️ メールを作成</a>
                        </div>
                    <?php endif; ?>
                    <p style="color:var(--muted); margin-top:16px; font-size:14px;">💡 通常24時間以内にご返信いたします。</p>
                </div>
                <div class="card">
                    <h3 style="margin-bottom:16px;">📝 お問い合わせフォーム</h3>
                    <?php if ($contactFormSuccess): ?>
                        <div style="background:#e8f5f0; border:1px solid #c9ebd8; color:#1f5b3b; padding:20px; border-radius:10px; text-align:center;">
                            <div style="font-size:32px; margin-bottom:12px;">✓</div>
                            <div style="font-weight:600; margin-bottom:8px;">送信完了しました</div>
                            <div style="font-size:14px;">お問い合わせありがとうございます。<br>24時間以内にご連絡いたします。</div>
                        </div>
                    <?php else: ?>
                        <?php if ($contactFormError): ?>
                            <div class="errors" style="margin-bottom:16px;"><?php echo h($contactFormError); ?></div>
                        <?php endif; ?>
                        <form method="post" action="<?php echo htmlspecialchars($_SERVER['PHP_SELF']); ?>#contact">
                            <input type="hidden" name="contact_form_submit" value="1">
                            <label>会社名 <span style="color:#e53e3e;">*</span></label>
                            <input type="text" name="form_company" required placeholder="株式会社〇〇" value="<?php echo h($_POST['form_company'] ?? ''); ?>">
                            <label style="margin-top:14px;">担当者名 <span style="color:#e53e3e;">*</span></label>
                            <input type="text" name="form_contact" required placeholder="山田 太郎" value="<?php echo h($_POST['form_contact'] ?? ''); ?>">
                            <label style="margin-top:14px;">メールアドレス <span style="color:#e53e3e;">*</span></label>
                            <input type="email" name="form_email" required placeholder="example@company.com" value="<?php echo h($_POST['form_email'] ?? ''); ?>">
                            <label style="margin-top:14px;">お問い合わせ内容 <span style="color:#e53e3e;">*</span></label>
                            <textarea name="form_message" required placeholder="ご質問やご要望をご記入ください..."><?php echo h($_POST['form_message'] ?? ''); ?></textarea>
                            <label style="margin-top:14px;">検証コード <span style="color:#e53e3e;">*</span></label>
                            <div style="display:flex; gap:10px; align-items:center; flex-wrap: wrap; margin-bottom:8px;">
                                <div style="font-weight:700; letter-spacing:0.1em; padding:10px 16px; background:linear-gradient(135deg, #eef2f7, #e5eaf2); border-radius:8px; font-size:18px;">
                                    <?php echo h($currentFormCode); ?>
                                </div>
                                <input type="text" name="form_verify_code" placeholder="コードを入力" required style="max-width:140px; padding:10px 14px;">
                            </div>
                            <div style="margin-top:16px;">
                                <button class="btn btn-primary" type="submit" data-loading-text="送信中..." style="width:100%; justify-content:center;">送信する →</button>
                            </div>
                        </form>
                    <?php endif; ?>
                </div>
            </div>
        </div>
    </section>

    <!-- CTA セクション -->
    <section style="background: linear-gradient(135deg, #0c203f, #1a4580); padding: 64px 24px; text-align: center;">
        <div class="content">
            <h2 style="color: #fff; margin-bottom: 16px;">今すぐ始めませんか？</h2>
            <p style="color: #c8d9ff; margin-bottom: 32px; max-width: 600px; margin-left: auto; margin-right: auto;">
                <?php if ($promoActive): ?>
                期間限定<?php echo $promoDiscount; ?>%OFFキャンペーン実施中！この機会をお見逃しなく。
                <?php else: ?>
                メール広告の効果を実感してください。まずはお試しプランからどうぞ。
                <?php endif; ?>
            </p>
            <div style="display:flex; gap:16px; justify-content:center; flex-wrap:wrap;">
                <a class="btn btn-primary" href="order.php" style="padding:16px 32px; font-size:16px;">🚀 今すぐ申し込む</a>
                <a class="btn btn-secondary" href="#contact" style="padding:16px 32px; font-size:16px;">💬 まずは相談する</a>
            </div>
        </div>
    </section>

    <?php
    // 簡易アクセスカウンター
    $counterFile = __DIR__ . '/counter.txt';
    $count = 0;
    if (file_exists($counterFile)) {
        $count = (int)file_get_contents($counterFile);
    }
    $count++;
    file_put_contents($counterFile, $count, LOCK_EX);
    ?>
    <footer>
        <div class="footer-content">
            <div class="footer-brand"><?php echo h($config['site']['brand']); ?></div>
            <p style="color:#a8b5c8; font-size:14px;">日本全国に向けたメール広告放送サービス</p>
            <div class="footer-links">
                <a href="#services">サービス概要</a>
                <a href="#plans">料金プラン</a>
                <a href="#flow">ご利用の流れ</a>
                <a href="#payment">お支払い方法</a>
                <a href="#contact">お問い合わせ</a>
            </div>
            <div class="footer-copy">
                &copy; <?php echo date('Y'); ?> <?php echo h($config['site']['brand']); ?>. All rights reserved.<br>
                <span style="font-size:12px; opacity:0.7;">総訪問者数: <?php echo number_format($count); ?></span>
            </div>
        </div>
    </footer>

    <!-- 返回顶部按钮 -->
    <a href="#top" class="back-to-top" id="backToTop" aria-label="トップへ戻る">↑</a>
    <script src="assets/common.js"></script>
    <script src="assets/index.js"></script>
</body>
</html>
