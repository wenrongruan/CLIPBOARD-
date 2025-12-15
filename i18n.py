"""
多语言支持模块 (Internationalization)
支持的语言: 中文、英文、日语、韩语、西班牙语、法语、德语、俄语
"""

from typing import Dict, Optional

# 支持的语言列表
SUPPORTED_LANGUAGES = {
    "zh_CN": "简体中文",
    "en_US": "English",
    "ja_JP": "日本語",
    "ko_KR": "한국어",
    "es_ES": "Español",
    "fr_FR": "Français",
    "de_DE": "Deutsch",
    "ru_RU": "Русский",
}

# 翻译字典
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ========== 简体中文 ==========
    "zh_CN": {
        # 通用
        "app_name": "共享剪贴板",
        "settings": "设置",
        "ok": "确定",
        "cancel": "取消",
        "yes": "是",
        "no": "否",
        "confirm": "确认",
        "error": "错误",
        "warning": "警告",
        "info": "信息",
        "success": "成功",

        # 主窗口
        "search_placeholder": "搜索剪贴板...",
        "pin_window": "固定窗口",
        "unpin_window": "取消固定",
        "minimize": "最小化",
        "quit_app": "退出应用",
        "prev_page": "◀ 上一页",
        "next_page": "下一页 ▶",
        "page_info": "{current} / {total}",

        # 设置对话框
        "general": "通用",
        "database": "数据库",
        "dock_position": "停靠位置:",
        "dock_right": "右侧",
        "dock_left": "左侧",
        "dock_top": "顶部",
        "dock_bottom": "底部",
        "global_hotkey": "全局热键:",
        "hotkey_placeholder": "例如: <cmd>+v",
        "hotkey_help": "热键格式说明:\n• <cmd> = Win键(Windows) / Cmd键(macOS)\n• <ctrl> = Ctrl键\n• <alt> = Alt键\n• <shift> = Shift键\n• 示例: <cmd>+v, <ctrl>+<shift>+c",
        "language": "语言:",

        # 数据库设置
        "db_type": "数据库类型:",
        "db_sqlite": "SQLite (本地文件)",
        "db_mysql": "MySQL (网络数据库)",
        "sqlite_config": "SQLite 配置",
        "mysql_config": "MySQL 配置",
        "db_path": "数据库路径:",
        "path_placeholder": "输入路径或点击浏览...",
        "browse": "浏览...",
        "select_db_file": "选择数据库文件位置",
        "host": "主机:",
        "port": "端口:",
        "username": "用户名:",
        "password": "密码:",
        "db_name": "数据库名:",
        "test_connection": "测试连接",
        "connection_success": "连接成功",
        "connection_failed": "连接失败",
        "missing_dependency": "缺少依赖",
        "pymysql_required": "pymysql 未安装，请运行:\npip install pymysql",
        "save_anyway": "{message}\n\n是否仍要保存设置？",

        # 剪贴板项
        "confirm_delete": "确认删除",
        "delete_confirm_msg": "确定要删除这条记录吗？",
        "image": "[图片]",
        "from_device": "来自: {device}",

        # 提示消息
        "need_restart": "需要重启",
        "restart_msg": "设置已更改，请重启应用程序以生效。",

        # 托盘菜单
        "show_window": "显示窗口",
        "quit": "退出",
    },

    # ========== English ==========
    "en_US": {
        # General
        "app_name": "Shared Clipboard",
        "settings": "Settings",
        "ok": "OK",
        "cancel": "Cancel",
        "yes": "Yes",
        "no": "No",
        "confirm": "Confirm",
        "error": "Error",
        "warning": "Warning",
        "info": "Information",
        "success": "Success",

        # Main window
        "search_placeholder": "Search clipboard...",
        "pin_window": "Pin window",
        "unpin_window": "Unpin window",
        "minimize": "Minimize",
        "quit_app": "Quit",
        "prev_page": "◀ Previous",
        "next_page": "Next ▶",
        "page_info": "{current} / {total}",

        # Settings dialog
        "general": "General",
        "database": "Database",
        "dock_position": "Dock position:",
        "dock_right": "Right",
        "dock_left": "Left",
        "dock_top": "Top",
        "dock_bottom": "Bottom",
        "global_hotkey": "Global hotkey:",
        "hotkey_placeholder": "e.g.: <cmd>+v",
        "hotkey_help": "Hotkey format:\n• <cmd> = Win key (Windows) / Cmd key (macOS)\n• <ctrl> = Ctrl key\n• <alt> = Alt key\n• <shift> = Shift key\n• Examples: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Language:",

        # Database settings
        "db_type": "Database type:",
        "db_sqlite": "SQLite (Local file)",
        "db_mysql": "MySQL (Network database)",
        "sqlite_config": "SQLite Configuration",
        "mysql_config": "MySQL Configuration",
        "db_path": "Database path:",
        "path_placeholder": "Enter path or click Browse...",
        "browse": "Browse...",
        "select_db_file": "Select database file location",
        "host": "Host:",
        "port": "Port:",
        "username": "Username:",
        "password": "Password:",
        "db_name": "Database name:",
        "test_connection": "Test Connection",
        "connection_success": "Connection Successful",
        "connection_failed": "Connection Failed",
        "missing_dependency": "Missing Dependency",
        "pymysql_required": "pymysql is not installed. Please run:\npip install pymysql",
        "save_anyway": "{message}\n\nSave settings anyway?",

        # Clipboard items
        "confirm_delete": "Confirm Delete",
        "delete_confirm_msg": "Are you sure you want to delete this item?",
        "image": "[Image]",
        "from_device": "From: {device}",

        # Messages
        "need_restart": "Restart Required",
        "restart_msg": "Settings have changed. Please restart the application for changes to take effect.",

        # Tray menu
        "show_window": "Show Window",
        "quit": "Quit",
    },

    # ========== 日本語 ==========
    "ja_JP": {
        # 一般
        "app_name": "共有クリップボード",
        "settings": "設定",
        "ok": "OK",
        "cancel": "キャンセル",
        "yes": "はい",
        "no": "いいえ",
        "confirm": "確認",
        "error": "エラー",
        "warning": "警告",
        "info": "情報",
        "success": "成功",

        # メインウィンドウ
        "search_placeholder": "クリップボードを検索...",
        "pin_window": "ウィンドウを固定",
        "unpin_window": "固定を解除",
        "minimize": "最小化",
        "quit_app": "終了",
        "prev_page": "◀ 前へ",
        "next_page": "次へ ▶",
        "page_info": "{current} / {total}",

        # 設定ダイアログ
        "general": "一般",
        "database": "データベース",
        "dock_position": "ドック位置:",
        "dock_right": "右",
        "dock_left": "左",
        "dock_top": "上",
        "dock_bottom": "下",
        "global_hotkey": "グローバルホットキー:",
        "hotkey_placeholder": "例: <cmd>+v",
        "hotkey_help": "ホットキーの形式:\n• <cmd> = Winキー(Windows) / Cmdキー(macOS)\n• <ctrl> = Ctrlキー\n• <alt> = Altキー\n• <shift> = Shiftキー\n• 例: <cmd>+v, <ctrl>+<shift>+c",
        "language": "言語:",

        # データベース設定
        "db_type": "データベースタイプ:",
        "db_sqlite": "SQLite (ローカルファイル)",
        "db_mysql": "MySQL (ネットワークデータベース)",
        "sqlite_config": "SQLite 設定",
        "mysql_config": "MySQL 設定",
        "db_path": "データベースパス:",
        "path_placeholder": "パスを入力または参照...",
        "browse": "参照...",
        "select_db_file": "データベースファイルの場所を選択",
        "host": "ホスト:",
        "port": "ポート:",
        "username": "ユーザー名:",
        "password": "パスワード:",
        "db_name": "データベース名:",
        "test_connection": "接続テスト",
        "connection_success": "接続成功",
        "connection_failed": "接続失敗",
        "missing_dependency": "依存関係が不足",
        "pymysql_required": "pymysqlがインストールされていません。\n実行してください: pip install pymysql",
        "save_anyway": "{message}\n\n設定を保存しますか？",

        # クリップボードアイテム
        "confirm_delete": "削除の確認",
        "delete_confirm_msg": "このアイテムを削除してもよろしいですか？",
        "image": "[画像]",
        "from_device": "送信元: {device}",

        # メッセージ
        "need_restart": "再起動が必要",
        "restart_msg": "設定が変更されました。変更を反映するにはアプリケーションを再起動してください。",

        # トレイメニュー
        "show_window": "ウィンドウを表示",
        "quit": "終了",
    },

    # ========== 한국어 ==========
    "ko_KR": {
        # 일반
        "app_name": "공유 클립보드",
        "settings": "설정",
        "ok": "확인",
        "cancel": "취소",
        "yes": "예",
        "no": "아니오",
        "confirm": "확인",
        "error": "오류",
        "warning": "경고",
        "info": "정보",
        "success": "성공",

        # 메인 윈도우
        "search_placeholder": "클립보드 검색...",
        "pin_window": "창 고정",
        "unpin_window": "고정 해제",
        "minimize": "최소화",
        "quit_app": "종료",
        "prev_page": "◀ 이전",
        "next_page": "다음 ▶",
        "page_info": "{current} / {total}",

        # 설정 대화상자
        "general": "일반",
        "database": "데이터베이스",
        "dock_position": "도킹 위치:",
        "dock_right": "오른쪽",
        "dock_left": "왼쪽",
        "dock_top": "위",
        "dock_bottom": "아래",
        "global_hotkey": "전역 단축키:",
        "hotkey_placeholder": "예: <cmd>+v",
        "hotkey_help": "단축키 형식:\n• <cmd> = Win키(Windows) / Cmd키(macOS)\n• <ctrl> = Ctrl키\n• <alt> = Alt키\n• <shift> = Shift키\n• 예: <cmd>+v, <ctrl>+<shift>+c",
        "language": "언어:",

        # 데이터베이스 설정
        "db_type": "데이터베이스 유형:",
        "db_sqlite": "SQLite (로컬 파일)",
        "db_mysql": "MySQL (네트워크 데이터베이스)",
        "sqlite_config": "SQLite 설정",
        "mysql_config": "MySQL 설정",
        "db_path": "데이터베이스 경로:",
        "path_placeholder": "경로 입력 또는 찾아보기...",
        "browse": "찾아보기...",
        "select_db_file": "데이터베이스 파일 위치 선택",
        "host": "호스트:",
        "port": "포트:",
        "username": "사용자 이름:",
        "password": "비밀번호:",
        "db_name": "데이터베이스 이름:",
        "test_connection": "연결 테스트",
        "connection_success": "연결 성공",
        "connection_failed": "연결 실패",
        "missing_dependency": "종속성 누락",
        "pymysql_required": "pymysql이 설치되지 않았습니다.\n실행하세요: pip install pymysql",
        "save_anyway": "{message}\n\n설정을 저장하시겠습니까?",

        # 클립보드 항목
        "confirm_delete": "삭제 확인",
        "delete_confirm_msg": "이 항목을 삭제하시겠습니까?",
        "image": "[이미지]",
        "from_device": "보낸 기기: {device}",

        # 메시지
        "need_restart": "재시작 필요",
        "restart_msg": "설정이 변경되었습니다. 변경 사항을 적용하려면 응용 프로그램을 다시 시작하세요.",

        # 트레이 메뉴
        "show_window": "창 표시",
        "quit": "종료",
    },

    # ========== Español ==========
    "es_ES": {
        # General
        "app_name": "Portapapeles Compartido",
        "settings": "Configuración",
        "ok": "Aceptar",
        "cancel": "Cancelar",
        "yes": "Sí",
        "no": "No",
        "confirm": "Confirmar",
        "error": "Error",
        "warning": "Advertencia",
        "info": "Información",
        "success": "Éxito",

        # Ventana principal
        "search_placeholder": "Buscar en portapapeles...",
        "pin_window": "Fijar ventana",
        "unpin_window": "Desfijar ventana",
        "minimize": "Minimizar",
        "quit_app": "Salir",
        "prev_page": "◀ Anterior",
        "next_page": "Siguiente ▶",
        "page_info": "{current} / {total}",

        # Diálogo de configuración
        "general": "General",
        "database": "Base de datos",
        "dock_position": "Posición de acoplamiento:",
        "dock_right": "Derecha",
        "dock_left": "Izquierda",
        "dock_top": "Arriba",
        "dock_bottom": "Abajo",
        "global_hotkey": "Tecla de acceso rápido:",
        "hotkey_placeholder": "ej.: <cmd>+v",
        "hotkey_help": "Formato de teclas:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Ejemplos: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Idioma:",

        # Configuración de base de datos
        "db_type": "Tipo de base de datos:",
        "db_sqlite": "SQLite (Archivo local)",
        "db_mysql": "MySQL (Base de datos en red)",
        "sqlite_config": "Configuración SQLite",
        "mysql_config": "Configuración MySQL",
        "db_path": "Ruta de base de datos:",
        "path_placeholder": "Ingrese ruta o haga clic en Examinar...",
        "browse": "Examinar...",
        "select_db_file": "Seleccionar ubicación del archivo de base de datos",
        "host": "Host:",
        "port": "Puerto:",
        "username": "Usuario:",
        "password": "Contraseña:",
        "db_name": "Nombre de base de datos:",
        "test_connection": "Probar conexión",
        "connection_success": "Conexión exitosa",
        "connection_failed": "Conexión fallida",
        "missing_dependency": "Dependencia faltante",
        "pymysql_required": "pymysql no está instalado.\nEjecute: pip install pymysql",
        "save_anyway": "{message}\n\n¿Guardar configuración de todos modos?",

        # Elementos del portapapeles
        "confirm_delete": "Confirmar eliminación",
        "delete_confirm_msg": "¿Está seguro de que desea eliminar este elemento?",
        "image": "[Imagen]",
        "from_device": "Desde: {device}",

        # Mensajes
        "need_restart": "Reinicio requerido",
        "restart_msg": "La configuración ha cambiado. Reinicie la aplicación para que los cambios surtan efecto.",

        # Menú de bandeja
        "show_window": "Mostrar ventana",
        "quit": "Salir",
    },

    # ========== Français ==========
    "fr_FR": {
        # Général
        "app_name": "Presse-papiers Partagé",
        "settings": "Paramètres",
        "ok": "OK",
        "cancel": "Annuler",
        "yes": "Oui",
        "no": "Non",
        "confirm": "Confirmer",
        "error": "Erreur",
        "warning": "Avertissement",
        "info": "Information",
        "success": "Succès",

        # Fenêtre principale
        "search_placeholder": "Rechercher dans le presse-papiers...",
        "pin_window": "Épingler la fenêtre",
        "unpin_window": "Désépingler la fenêtre",
        "minimize": "Réduire",
        "quit_app": "Quitter",
        "prev_page": "◀ Précédent",
        "next_page": "Suivant ▶",
        "page_info": "{current} / {total}",

        # Dialogue des paramètres
        "general": "Général",
        "database": "Base de données",
        "dock_position": "Position d'ancrage:",
        "dock_right": "Droite",
        "dock_left": "Gauche",
        "dock_top": "Haut",
        "dock_bottom": "Bas",
        "global_hotkey": "Raccourci global:",
        "hotkey_placeholder": "ex: <cmd>+v",
        "hotkey_help": "Format des raccourcis:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Exemples: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Langue:",

        # Paramètres de base de données
        "db_type": "Type de base de données:",
        "db_sqlite": "SQLite (Fichier local)",
        "db_mysql": "MySQL (Base de données réseau)",
        "sqlite_config": "Configuration SQLite",
        "mysql_config": "Configuration MySQL",
        "db_path": "Chemin de la base de données:",
        "path_placeholder": "Entrez le chemin ou cliquez sur Parcourir...",
        "browse": "Parcourir...",
        "select_db_file": "Sélectionner l'emplacement du fichier de base de données",
        "host": "Hôte:",
        "port": "Port:",
        "username": "Utilisateur:",
        "password": "Mot de passe:",
        "db_name": "Nom de la base de données:",
        "test_connection": "Tester la connexion",
        "connection_success": "Connexion réussie",
        "connection_failed": "Connexion échouée",
        "missing_dependency": "Dépendance manquante",
        "pymysql_required": "pymysql n'est pas installé.\nExécutez: pip install pymysql",
        "save_anyway": "{message}\n\nEnregistrer les paramètres quand même?",

        # Éléments du presse-papiers
        "confirm_delete": "Confirmer la suppression",
        "delete_confirm_msg": "Êtes-vous sûr de vouloir supprimer cet élément?",
        "image": "[Image]",
        "from_device": "De: {device}",

        # Messages
        "need_restart": "Redémarrage requis",
        "restart_msg": "Les paramètres ont été modifiés. Veuillez redémarrer l'application pour que les modifications prennent effet.",

        # Menu de la barre d'état
        "show_window": "Afficher la fenêtre",
        "quit": "Quitter",
    },

    # ========== Deutsch ==========
    "de_DE": {
        # Allgemein
        "app_name": "Geteilte Zwischenablage",
        "settings": "Einstellungen",
        "ok": "OK",
        "cancel": "Abbrechen",
        "yes": "Ja",
        "no": "Nein",
        "confirm": "Bestätigen",
        "error": "Fehler",
        "warning": "Warnung",
        "info": "Information",
        "success": "Erfolg",

        # Hauptfenster
        "search_placeholder": "Zwischenablage durchsuchen...",
        "pin_window": "Fenster anheften",
        "unpin_window": "Fenster lösen",
        "minimize": "Minimieren",
        "quit_app": "Beenden",
        "prev_page": "◀ Zurück",
        "next_page": "Weiter ▶",
        "page_info": "{current} / {total}",

        # Einstellungsdialog
        "general": "Allgemein",
        "database": "Datenbank",
        "dock_position": "Andockposition:",
        "dock_right": "Rechts",
        "dock_left": "Links",
        "dock_top": "Oben",
        "dock_bottom": "Unten",
        "global_hotkey": "Globale Tastenkombination:",
        "hotkey_placeholder": "z.B.: <cmd>+v",
        "hotkey_help": "Tastenkombinationsformat:\n• <cmd> = Win-Taste (Windows) / Cmd-Taste (macOS)\n• <ctrl> = Strg-Taste\n• <alt> = Alt-Taste\n• <shift> = Umschalt-Taste\n• Beispiele: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Sprache:",

        # Datenbankeinstellungen
        "db_type": "Datenbanktyp:",
        "db_sqlite": "SQLite (Lokale Datei)",
        "db_mysql": "MySQL (Netzwerkdatenbank)",
        "sqlite_config": "SQLite-Konfiguration",
        "mysql_config": "MySQL-Konfiguration",
        "db_path": "Datenbankpfad:",
        "path_placeholder": "Pfad eingeben oder auf Durchsuchen klicken...",
        "browse": "Durchsuchen...",
        "select_db_file": "Datenbankdatei-Speicherort auswählen",
        "host": "Host:",
        "port": "Port:",
        "username": "Benutzername:",
        "password": "Passwort:",
        "db_name": "Datenbankname:",
        "test_connection": "Verbindung testen",
        "connection_success": "Verbindung erfolgreich",
        "connection_failed": "Verbindung fehlgeschlagen",
        "missing_dependency": "Fehlende Abhängigkeit",
        "pymysql_required": "pymysql ist nicht installiert.\nFühren Sie aus: pip install pymysql",
        "save_anyway": "{message}\n\nEinstellungen trotzdem speichern?",

        # Zwischenablage-Elemente
        "confirm_delete": "Löschen bestätigen",
        "delete_confirm_msg": "Sind Sie sicher, dass Sie dieses Element löschen möchten?",
        "image": "[Bild]",
        "from_device": "Von: {device}",

        # Nachrichten
        "need_restart": "Neustart erforderlich",
        "restart_msg": "Die Einstellungen wurden geändert. Bitte starten Sie die Anwendung neu, damit die Änderungen wirksam werden.",

        # Taskleistenmenü
        "show_window": "Fenster anzeigen",
        "quit": "Beenden",
    },

    # ========== Русский ==========
    "ru_RU": {
        # Общие
        "app_name": "Общий буфер обмена",
        "settings": "Настройки",
        "ok": "ОК",
        "cancel": "Отмена",
        "yes": "Да",
        "no": "Нет",
        "confirm": "Подтвердить",
        "error": "Ошибка",
        "warning": "Предупреждение",
        "info": "Информация",
        "success": "Успешно",

        # Главное окно
        "search_placeholder": "Поиск в буфере обмена...",
        "pin_window": "Закрепить окно",
        "unpin_window": "Открепить окно",
        "minimize": "Свернуть",
        "quit_app": "Выход",
        "prev_page": "◀ Назад",
        "next_page": "Далее ▶",
        "page_info": "{current} / {total}",

        # Диалог настроек
        "general": "Общие",
        "database": "База данных",
        "dock_position": "Позиция закрепления:",
        "dock_right": "Справа",
        "dock_left": "Слева",
        "dock_top": "Сверху",
        "dock_bottom": "Снизу",
        "global_hotkey": "Глобальная горячая клавиша:",
        "hotkey_placeholder": "напр.: <cmd>+v",
        "hotkey_help": "Формат горячих клавиш:\n• <cmd> = Win (Windows) / Cmd (macOS)\n• <ctrl> = Ctrl\n• <alt> = Alt\n• <shift> = Shift\n• Примеры: <cmd>+v, <ctrl>+<shift>+c",
        "language": "Язык:",

        # Настройки базы данных
        "db_type": "Тип базы данных:",
        "db_sqlite": "SQLite (Локальный файл)",
        "db_mysql": "MySQL (Сетевая база данных)",
        "sqlite_config": "Настройки SQLite",
        "mysql_config": "Настройки MySQL",
        "db_path": "Путь к базе данных:",
        "path_placeholder": "Введите путь или нажмите Обзор...",
        "browse": "Обзор...",
        "select_db_file": "Выберите расположение файла базы данных",
        "host": "Хост:",
        "port": "Порт:",
        "username": "Имя пользователя:",
        "password": "Пароль:",
        "db_name": "Имя базы данных:",
        "test_connection": "Проверить соединение",
        "connection_success": "Соединение успешно",
        "connection_failed": "Соединение не удалось",
        "missing_dependency": "Отсутствует зависимость",
        "pymysql_required": "pymysql не установлен.\nВыполните: pip install pymysql",
        "save_anyway": "{message}\n\nСохранить настройки в любом случае?",

        # Элементы буфера обмена
        "confirm_delete": "Подтвердить удаление",
        "delete_confirm_msg": "Вы уверены, что хотите удалить этот элемент?",
        "image": "[Изображение]",
        "from_device": "От: {device}",

        # Сообщения
        "need_restart": "Требуется перезапуск",
        "restart_msg": "Настройки были изменены. Пожалуйста, перезапустите приложение для применения изменений.",

        # Меню в трее
        "show_window": "Показать окно",
        "quit": "Выход",
    },
}


class I18n:
    """国际化管理类"""

    _current_language: str = "zh_CN"
    _instance: Optional["I18n"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_language(cls, language: str):
        """设置当前语言"""
        if language in SUPPORTED_LANGUAGES:
            cls._current_language = language

    @classmethod
    def get_language(cls) -> str:
        """获取当前语言"""
        return cls._current_language

    @classmethod
    def get_languages(cls) -> Dict[str, str]:
        """获取所有支持的语言"""
        return SUPPORTED_LANGUAGES.copy()

    @classmethod
    def t(cls, key: str, **kwargs) -> str:
        """
        获取翻译文本

        Args:
            key: 翻译键
            **kwargs: 格式化参数

        Returns:
            翻译后的文本，如果找不到则返回键本身
        """
        translations = TRANSLATIONS.get(cls._current_language, {})
        text = translations.get(key, key)

        # 如果当前语言没有翻译，尝试使用英语
        if text == key and cls._current_language != "en_US":
            text = TRANSLATIONS.get("en_US", {}).get(key, key)

        # 格式化参数
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass

        return text


# 便捷函数
def t(key: str, **kwargs) -> str:
    """翻译便捷函数"""
    return I18n.t(key, **kwargs)


def set_language(language: str):
    """设置语言便捷函数"""
    I18n.set_language(language)


def get_language() -> str:
    """获取当前语言"""
    return I18n.get_language()


def get_languages() -> Dict[str, str]:
    """获取所有支持的语言"""
    return I18n.get_languages()
