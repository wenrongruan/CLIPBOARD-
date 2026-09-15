"""i18n 字符串 - screenshot 领域。

截图功能：托盘菜单、热键设置、结果提示、macOS「屏幕录制」权限引导。
"""

STRINGS = {
    # ========== 简体中文 / Simplified Chinese ==========
    "zh_CN": {
        # 功能名 / 菜单
        "screenshot": '截图',
        "screenshot_region": '区域截图',
        "screenshot_full": '全屏截图',
        "screenshot_window": '窗口截图',

        # 结果提示
        "screenshot_saved": '截图已保存到历史并复制到剪贴板',
        "screenshot_saved_no_copy": '截图已保存到历史',
        "screenshot_failed": '截图失败: {error}',
        "screenshot_too_large": '截图过大，未保存（超过图片大小上限，可在设置 → 过滤与存储里调整）',

        # 设置项
        "screenshot_hotkey": '截图热键:',
        "screenshot_copy_to_clipboard": '截图后自动复制到剪贴板',

        # macOS 权限引导
        "screenshot_permission_title": '需要「屏幕录制」权限',
        "screenshot_permission_msg": (
            '截图功能需要「屏幕录制」权限才能读取屏幕内容。\n\n'
            '请前往：系统设置 → 隐私与安全性 → 屏幕录制\n'
            '勾选「共享剪贴板」，然后重启应用。'
        ),
        "screenshot_permission_hint": '如果暂时跳过，仍可通过托盘菜单尝试，但截图可能是空的。',
        "open_system_settings": '打开系统设置',
    },

    # ========== English ==========
    "en_US": {
        "screenshot": 'Screenshot',
        "screenshot_region": 'Capture Region',
        "screenshot_full": 'Capture Full Screen',
        "screenshot_window": 'Capture Window',

        "screenshot_saved": 'Screenshot saved to history and copied to clipboard',
        "screenshot_saved_no_copy": 'Screenshot saved to history',
        "screenshot_failed": 'Screenshot failed: {error}',
        "screenshot_too_large": 'Screenshot too large, not saved (exceeds image size limit; adjust it in Settings → Filter & Storage)',

        "screenshot_hotkey": 'Screenshot hotkey:',
        "screenshot_copy_to_clipboard": 'Copy screenshot to clipboard automatically',

        "screenshot_permission_title": 'Screen Recording permission required',
        "screenshot_permission_msg": (
            'Taking screenshots requires the Screen Recording permission to read the screen.\n\n'
            'Go to: System Settings → Privacy & Security → Screen Recording\n'
            'Enable "Shared Clipboard", then restart the app.'
        ),
        "screenshot_permission_hint": 'If you skip this, the tray menu still works but the capture may be blank.',
        "open_system_settings": 'Open System Settings',
    },

    # ========== 日本語 / Japanese ==========
    "ja_JP": {
        "screenshot": 'スクリーンショット',
        "screenshot_region": '範囲をキャプチャ',
        "screenshot_full": '全画面をキャプチャ',
        "screenshot_window": 'ウィンドウをキャプチャ',

        "screenshot_saved": 'スクリーンショットを履歴に保存し、クリップボードにコピーしました',
        "screenshot_saved_no_copy": 'スクリーンショットを履歴に保存しました',
        "screenshot_failed": 'スクリーンショットに失敗しました: {error}',
        "screenshot_too_large": 'スクリーンショットが大きすぎるため保存されませんでした（画像サイズ上限を超えています。設定 → フィルターと保存 で変更できます）',

        "screenshot_hotkey": 'スクリーンショットのホットキー:',
        "screenshot_copy_to_clipboard": 'キャプチャ後に自動でクリップボードへコピー',

        "screenshot_permission_title": '「画面収録」権限が必要です',
        "screenshot_permission_msg": (
            'スクリーンショット機能は画面の内容を読み取るために「画面収録」権限が必要です。\n\n'
            'システム設定 → プライバシーとセキュリティ → 画面収録\n'
            '「共有クリップボード」を有効にして、アプリを再起動してください。'
        ),
        "screenshot_permission_hint": 'スキップしてもトレイメニューから実行できますが、画像が空になる場合があります。',
        "open_system_settings": 'システム設定を開く',
    },

    # ========== 한국어 / Korean ==========
    "ko_KR": {
        "screenshot": '스크린샷',
        "screenshot_region": '영역 캡처',
        "screenshot_full": '전체 화면 캡처',
        "screenshot_window": '창 캡처',

        "screenshot_saved": '스크린샷을 기록에 저장하고 클립보드에 복사했습니다',
        "screenshot_saved_no_copy": '스크린샷을 기록에 저장했습니다',
        "screenshot_failed": '스크린샷 실패: {error}',
        "screenshot_too_large": '스크린샷이 너무 커서 저장하지 않았습니다 (이미지 크기 제한 초과, 설정 → 필터 및 저장에서 조정 가능)',

        "screenshot_hotkey": '스크린샷 단축키:',
        "screenshot_copy_to_clipboard": '캡처 후 자동으로 클립보드에 복사',

        "screenshot_permission_title": '「화면 기록」 권한이 필요합니다',
        "screenshot_permission_msg": (
            '스크린샷 기능은 화면 내용을 읽기 위해 「화면 기록」 권한이 필요합니다.\n\n'
            '시스템 설정 → 개인정보 보호 및 보안 → 화면 기록\n'
            '「공유 클립보드」를 체크한 뒤 앱을 재시작하세요.'
        ),
        "screenshot_permission_hint": '건너뛰어도 트레이 메뉴에서 실행할 수 있지만 이미지가 비어 있을 수 있습니다.',
        "open_system_settings": '시스템 설정 열기',
    },

    # ========== Español / Spanish ==========
    "es_ES": {
        "screenshot": 'Captura',
        "screenshot_region": 'Capturar región',
        "screenshot_full": 'Capturar pantalla completa',
        "screenshot_window": 'Capturar ventana',

        "screenshot_saved": 'Captura guardada en el historial y copiada al portapapeles',
        "screenshot_saved_no_copy": 'Captura guardada en el historial',
        "screenshot_failed": 'Error en la captura: {error}',
        "screenshot_too_large": 'Captura demasiado grande, no guardada (supera el límite de tamaño de imagen; ajústelo en Configuración → Filtro y almacenamiento)',

        "screenshot_hotkey": 'Tecla de captura:',
        "screenshot_copy_to_clipboard": 'Copiar la captura al portapapeles automáticamente',

        "screenshot_permission_title": 'Se requiere el permiso de grabación de pantalla',
        "screenshot_permission_msg": (
            'La función de captura necesita el permiso de grabación de pantalla para leer el contenido de la pantalla.\n\n'
            'Vaya a: Ajustes del Sistema → Privacidad y seguridad → Grabación de pantalla\n'
            'Active «Portapapeles Compartido» y reinicie la aplicación.'
        ),
        "screenshot_permission_hint": 'Si lo omite, el menú de la bandeja seguirá funcionando, pero la captura podría salir en blanco.',
        "open_system_settings": 'Abrir Ajustes del Sistema',
    },

    # ========== Français / French ==========
    "fr_FR": {
        "screenshot": 'Capture',
        "screenshot_region": 'Capturer une zone',
        "screenshot_full": 'Capturer tout l’écran',
        "screenshot_window": 'Capturer une fenêtre',

        "screenshot_saved": 'Capture enregistrée dans l’historique et copiée dans le presse-papiers',
        "screenshot_saved_no_copy": 'Capture enregistrée dans l’historique',
        "screenshot_failed": 'Échec de la capture : {error}',
        "screenshot_too_large": 'Capture trop volumineuse, non enregistrée (dépasse la limite de taille d’image ; modifiez-la dans Paramètres → Filtre et stockage)',

        "screenshot_hotkey": 'Raccourci de capture :',
        "screenshot_copy_to_clipboard": 'Copier automatiquement la capture dans le presse-papiers',

        "screenshot_permission_title": 'Autorisation « Enregistrement de l’écran » requise',
        "screenshot_permission_msg": (
            'La capture d’écran nécessite l’autorisation « Enregistrement de l’écran » pour lire le contenu de l’écran.\n\n'
            'Allez dans : Réglages Système → Confidentialité et sécurité → Enregistrement de l’écran\n'
            'Activez « Presse-papiers Partagé », puis redémarrez l’application.'
        ),
        "screenshot_permission_hint": 'Si vous passez cette étape, le menu de la barre reste utilisable mais la capture peut être vide.',
        "open_system_settings": 'Ouvrir les Réglages Système',
    },

    # ========== Deutsch / German ==========
    "de_DE": {
        "screenshot": 'Screenshot',
        "screenshot_region": 'Bereich aufnehmen',
        "screenshot_full": 'Ganzen Bildschirm aufnehmen',
        "screenshot_window": 'Fenster aufnehmen',

        "screenshot_saved": 'Screenshot im Verlauf gespeichert und in die Zwischenablage kopiert',
        "screenshot_saved_no_copy": 'Screenshot im Verlauf gespeichert',
        "screenshot_failed": 'Screenshot fehlgeschlagen: {error}',
        "screenshot_too_large": 'Screenshot zu groß, nicht gespeichert (übersteigt die Bildgrößengrenze; anpassbar unter Einstellungen → Filter & Speicher)',

        "screenshot_hotkey": 'Screenshot-Tastenkombination:',
        "screenshot_copy_to_clipboard": 'Screenshot automatisch in die Zwischenablage kopieren',

        "screenshot_permission_title": 'Berechtigung „Bildschirmaufnahme“ erforderlich',
        "screenshot_permission_msg": (
            'Die Screenshot-Funktion benötigt die Berechtigung „Bildschirmaufnahme“, um den Bildschirminhalt zu lesen.\n\n'
            'Gehen Sie zu: Systemeinstellungen → Datenschutz & Sicherheit → Bildschirmaufnahme\n'
            'Aktivieren Sie „Geteilte Zwischenablage“ und starten Sie die App neu.'
        ),
        "screenshot_permission_hint": 'Wenn Sie überspringen, funktioniert das Menüleisten-Menü weiterhin, der Screenshot kann aber leer sein.',
        "open_system_settings": 'Systemeinstellungen öffnen',
    },

    # ========== Русский / Russian ==========
    "ru_RU": {
        "screenshot": 'Снимок экрана',
        "screenshot_region": 'Снимок области',
        "screenshot_full": 'Снимок всего экрана',
        "screenshot_window": 'Снимок окна',

        "screenshot_saved": 'Снимок сохранён в историю и скопирован в буфер обмена',
        "screenshot_saved_no_copy": 'Снимок сохранён в историю',
        "screenshot_failed": 'Не удалось сделать снимок: {error}',
        "screenshot_too_large": 'Снимок слишком большой и не сохранён (превышен лимит размера изображения; измените его в Настройки → Фильтр и хранение)',

        "screenshot_hotkey": 'Горячая клавиша снимка:',
        "screenshot_copy_to_clipboard": 'Автоматически копировать снимок в буфер обмена',

        "screenshot_permission_title": 'Требуется разрешение «Запись экрана»',
        "screenshot_permission_msg": (
            'Для создания снимков экрана нужно разрешение «Запись экрана», чтобы читать содержимое экрана.\n\n'
            'Перейдите: Системные настройки → Конфиденциальность и безопасность → Запись экрана\n'
            'Включите «Общий буфер обмена» и перезапустите приложение.'
        ),
        "screenshot_permission_hint": 'Если пропустить, меню в трее продолжит работать, но снимок может получиться пустым.',
        "open_system_settings": 'Открыть системные настройки',
    },
}
