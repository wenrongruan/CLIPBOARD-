"""i18n 字符串 - plugins 领域。

插件相关字符串:管理、运行时、权限、商店。
"""

STRINGS = {
    # ========== 简体中文 / Simplified Chinese ==========
    "zh_CN": {
        # 插件管理 Plugin management
        "plugins": '插件',
        "installed_plugins": '已安装插件',
        "open_plugins_dir": '打开插件目录',
        "reload_plugins": '重新加载',
        "view_plugin_logs": '查看日志',
        "plugin_dev_docs": '开发文档',
        "plugin_settings": '设置',
        "plugin_enabled": '已启用',
        "plugin_disabled": '已禁用',
        "plugin_missing_deps": '缺少依赖: {deps}',
        "plugin_incompatible": '版本不兼容',
        "plugin_error": '加载失败',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} 执行中... {percent}%',
        "plugin_timeout": '插件执行超时',
        "plugin_busy": '有插件正在执行，请等待完成',
        "plugin_not_loaded": '插件未加载: {id}',
        "plugin_exec_failed": '执行失败',
        "plugin_config_title": '{name} - 设置',
        "plugin_config_required": '请填写必填项',
        "plugin_save": '保存',
        "plugin_cancel": '取消',
        "plugin_saved_entry": '已保存为新条目',
        "plugin_replaced_entry": '已替换原内容',

        # 插件权限 Plugin permissions
        "plugin_perm_network": '网络访问',
        "plugin_perm_file_read": '读取文件',
        "plugin_perm_file_write": '写入文件',

        # 插件商店 Plugin store
        "plugin_store": '插件商店',
        "plugin_install": '安装',
        "plugin_uninstall": '卸载',
        "plugin_installing": '安装中...',
        "plugin_installed_tag": '已安装',
        "plugin_install_failed": '安装失败',
        "plugin_uninstall_confirm_title": '确认卸载',
        "plugin_uninstall_confirm": '确定要卸载插件「{name}」吗？',
        "plugin_uninstall_failed": '卸载失败',
        "plugin_store_loading": '正在加载插件列表...',
        "plugin_store_empty": '暂无可用插件',
        "plugin_store_error": '获取插件列表失败',
        "plugin_no_installed": '暂无已安装插件',
    },

    # ========== English ==========
    "en_US": {
        # 插件管理 Plugin management
        "plugins": 'Plugins',
        "installed_plugins": 'Installed Plugins',
        "open_plugins_dir": 'Open Plugins Folder',
        "reload_plugins": 'Reload',
        "view_plugin_logs": 'View Logs',
        "plugin_dev_docs": 'Dev Docs',
        "plugin_settings": 'Settings',
        "plugin_enabled": 'Enabled',
        "plugin_disabled": 'Disabled',
        "plugin_missing_deps": 'Missing dependencies: {deps}',
        "plugin_incompatible": 'Incompatible version',
        "plugin_error": 'Load failed',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} running... {percent}%',
        "plugin_timeout": 'Plugin execution timed out',
        "plugin_busy": 'A plugin is already running, please wait',
        "plugin_not_loaded": 'Plugin not loaded: {id}',
        "plugin_exec_failed": 'Execution failed',
        "plugin_config_title": '{name} - Settings',
        "plugin_config_required": 'Please fill in required fields',
        "plugin_save": 'Save',
        "plugin_cancel": 'Cancel',
        "plugin_saved_entry": 'Saved as new entry',
        "plugin_replaced_entry": 'Content replaced',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'Network access',
        "plugin_perm_file_read": 'File read',
        "plugin_perm_file_write": 'File write',

        # 插件商店 Plugin store
        "plugin_store": 'Plugin Store',
        "plugin_install": 'Install',
        "plugin_uninstall": 'Uninstall',
        "plugin_installing": 'Installing...',
        "plugin_installed_tag": 'Installed',
        "plugin_install_failed": 'Installation Failed',
        "plugin_uninstall_confirm_title": 'Confirm Uninstall',
        "plugin_uninstall_confirm": 'Are you sure you want to uninstall "{name}"?',
        "plugin_uninstall_failed": 'Uninstall failed',
        "plugin_store_loading": 'Loading plugin list...',
        "plugin_store_empty": 'No plugins available',
        "plugin_store_error": 'Failed to load plugin list',
        "plugin_no_installed": 'No plugins installed',
    },

    # ========== 日本語 / Japanese ==========
    "ja_JP": {
        # 插件管理 Plugin management
        "plugins": 'プラグイン',
        "installed_plugins": 'インストール済みプラグイン',
        "open_plugins_dir": 'プラグインフォルダを開く',
        "reload_plugins": '再読み込み',
        "view_plugin_logs": 'ログを見る',
        "plugin_dev_docs": '開発ドキュメント',
        "plugin_settings": '設定',
        "plugin_enabled": '有効',
        "plugin_disabled": '無効',
        "plugin_missing_deps": '依存関係不足: {deps}',
        "plugin_incompatible": 'バージョン非互換',
        "plugin_error": '読み込み失敗',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} 実行中... {percent}%',
        "plugin_timeout": 'プラグインがタイムアウトしました',
        "plugin_busy": 'プラグインが実行中です。お待ちください',
        "plugin_not_loaded": 'プラグインが読み込まれていません: {id}',
        "plugin_exec_failed": '実行に失敗しました',
        "plugin_config_title": '{name} - 設定',
        "plugin_config_required": '必須項目を入力してください',
        "plugin_save": '保存',
        "plugin_cancel": 'キャンセル',
        "plugin_saved_entry": '新しいエントリとして保存しました',
        "plugin_replaced_entry": '内容を置換しました',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'ネットワークアクセス',
        "plugin_perm_file_read": 'ファイル読み取り',
        "plugin_perm_file_write": 'ファイル書き込み',

        # 插件商店 Plugin store
        "plugin_store": 'プラグインストア',
        "plugin_install": 'インストール',
        "plugin_uninstall": 'アンインストール',
        "plugin_installing": 'インストール中...',
        "plugin_installed_tag": 'インストール済み',
        "plugin_install_failed": 'インストール失敗',
        "plugin_uninstall_confirm_title": 'アンインストールの確認',
        "plugin_uninstall_confirm": 'プラグイン「{name}」をアンインストールしますか？',
        "plugin_uninstall_failed": 'アンインストール失敗',
        "plugin_store_loading": 'プラグインリストを読み込み中...',
        "plugin_store_empty": '利用可能なプラグインはありません',
        "plugin_store_error": 'プラグインリストの読み込みに失敗しました',
        "plugin_no_installed": 'インストール済みプラグインはありません',
    },

    # ========== 한국어 / Korean ==========
    "ko_KR": {
        # 插件管理 Plugin management
        "plugins": '플러그인',
        "installed_plugins": '설치된 플러그인',
        "open_plugins_dir": '플러그인 폴더 열기',
        "reload_plugins": '다시 로드',
        "view_plugin_logs": '로그 보기',
        "plugin_dev_docs": '개발 문서',
        "plugin_settings": '설정',
        "plugin_enabled": '활성화됨',
        "plugin_disabled": '비활성화됨',
        "plugin_missing_deps": '누락된 종속성: {deps}',
        "plugin_incompatible": '호환되지 않는 버전',
        "plugin_error": '로드 실패',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} 실행 중... {percent}%',
        "plugin_timeout": '플러그인 실행 시간 초과',
        "plugin_busy": '플러그인이 실행 중입니다. 기다려 주세요',
        "plugin_not_loaded": '플러그인이 로드되지 않았습니다: {id}',
        "plugin_exec_failed": '실행 실패',
        "plugin_config_title": '{name} - 설정',
        "plugin_config_required": '필수 항목을 입력하세요',
        "plugin_save": '저장',
        "plugin_cancel": '취소',
        "plugin_saved_entry": '새 항목으로 저장됨',
        "plugin_replaced_entry": '내용이 교체됨',

        # 插件权限 Plugin permissions
        "plugin_perm_network": '네트워크 액세스',
        "plugin_perm_file_read": '파일 읽기',
        "plugin_perm_file_write": '파일 쓰기',

        # 插件商店 Plugin store
        "plugin_store": '플러그인 스토어',
        "plugin_install": '설치',
        "plugin_uninstall": '제거',
        "plugin_installing": '설치 중...',
        "plugin_installed_tag": '설치됨',
        "plugin_install_failed": '설치 실패',
        "plugin_uninstall_confirm_title": '제거 확인',
        "plugin_uninstall_confirm": '플러그인 "{name}"을(를) 제거하시겠습니까?',
        "plugin_uninstall_failed": '제거 실패',
        "plugin_store_loading": '플러그인 목록 로딩 중...',
        "plugin_store_empty": '사용 가능한 플러그인이 없습니다',
        "plugin_store_error": '플러그인 목록을 불러오지 못했습니다',
        "plugin_no_installed": '설치된 플러그인이 없습니다',
    },

    # ========== Español / Spanish ==========
    "es_ES": {
        # 插件管理 Plugin management
        "plugins": 'Plugins',
        "installed_plugins": 'Plugins instalados',
        "open_plugins_dir": 'Abrir carpeta de plugins',
        "reload_plugins": 'Recargar',
        "view_plugin_logs": 'Ver registros',
        "plugin_dev_docs": 'Docs de desarrollo',
        "plugin_settings": 'Configuración',
        "plugin_enabled": 'Habilitado',
        "plugin_disabled": 'Deshabilitado',
        "plugin_missing_deps": 'Dependencias faltantes: {deps}',
        "plugin_incompatible": 'Versión incompatible',
        "plugin_error": 'Error de carga',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} ejecutando... {percent}%',
        "plugin_timeout": 'Tiempo de espera del plugin agotado',
        "plugin_busy": 'Un plugin se está ejecutando, por favor espere',
        "plugin_not_loaded": 'Plugin no cargado: {id}',
        "plugin_exec_failed": 'Error de ejecución',
        "plugin_config_title": '{name} - Configuración',
        "plugin_config_required": 'Complete los campos obligatorios',
        "plugin_save": 'Guardar',
        "plugin_cancel": 'Cancelar',
        "plugin_saved_entry": 'Guardado como nueva entrada',
        "plugin_replaced_entry": 'Contenido reemplazado',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'Acceso a red',
        "plugin_perm_file_read": 'Lectura de archivos',
        "plugin_perm_file_write": 'Escritura de archivos',

        # 插件商店 Plugin store
        "plugin_store": 'Tienda de plugins',
        "plugin_install": 'Instalar',
        "plugin_uninstall": 'Desinstalar',
        "plugin_installing": 'Instalando...',
        "plugin_installed_tag": 'Instalado',
        "plugin_install_failed": 'Error de instalación',
        "plugin_uninstall_confirm_title": 'Confirmar desinstalación',
        "plugin_uninstall_confirm": '¿Está seguro de que desea desinstalar "{name}"?',
        "plugin_uninstall_failed": 'Error al desinstalar',
        "plugin_store_loading": 'Cargando lista de plugins...',
        "plugin_store_empty": 'No hay plugins disponibles',
        "plugin_store_error": 'Error al cargar la lista de plugins',
        "plugin_no_installed": 'No hay plugins instalados',
    },

    # ========== Français / French ==========
    "fr_FR": {
        # 插件管理 Plugin management
        "plugins": 'Plugins',
        "installed_plugins": 'Plugins installés',
        "open_plugins_dir": 'Ouvrir le dossier des plugins',
        "reload_plugins": 'Recharger',
        "view_plugin_logs": 'Voir les journaux',
        "plugin_dev_docs": 'Docs de développement',
        "plugin_settings": 'Paramètres',
        "plugin_enabled": 'Activé',
        "plugin_disabled": 'Désactivé',
        "plugin_missing_deps": 'Dépendances manquantes : {deps}',
        "plugin_incompatible": 'Version incompatible',
        "plugin_error": 'Échec du chargement',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} en cours... {percent}%',
        "plugin_timeout": "Délai d'exécution du plugin dépassé",
        "plugin_busy": "Un plugin est en cours d'exécution, veuillez patienter",
        "plugin_not_loaded": 'Plugin non chargé : {id}',
        "plugin_exec_failed": "Échec de l'exécution",
        "plugin_config_title": '{name} - Paramètres',
        "plugin_config_required": 'Veuillez remplir les champs obligatoires',
        "plugin_save": 'Enregistrer',
        "plugin_cancel": 'Annuler',
        "plugin_saved_entry": 'Enregistré comme nouvelle entrée',
        "plugin_replaced_entry": 'Contenu remplacé',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'Accès réseau',
        "plugin_perm_file_read": 'Lecture de fichiers',
        "plugin_perm_file_write": 'Écriture de fichiers',

        # 插件商店 Plugin store
        "plugin_store": 'Boutique de plugins',
        "plugin_install": 'Installer',
        "plugin_uninstall": 'Désinstaller',
        "plugin_installing": 'Installation...',
        "plugin_installed_tag": 'Installé',
        "plugin_install_failed": "Échec de l'installation",
        "plugin_uninstall_confirm_title": 'Confirmer la désinstallation',
        "plugin_uninstall_confirm": 'Êtes-vous sûr de vouloir désinstaller "{name}" ?',
        "plugin_uninstall_failed": 'Échec de la désinstallation',
        "plugin_store_loading": 'Chargement de la liste des plugins...',
        "plugin_store_empty": 'Aucun plugin disponible',
        "plugin_store_error": 'Impossible de charger la liste des plugins',
        "plugin_no_installed": 'Aucun plugin installé',
    },

    # ========== Deutsch / German ==========
    "de_DE": {
        # 插件管理 Plugin management
        "plugins": 'Plugins',
        "installed_plugins": 'Installierte Plugins',
        "open_plugins_dir": 'Plugin-Ordner öffnen',
        "reload_plugins": 'Neu laden',
        "view_plugin_logs": 'Protokolle anzeigen',
        "plugin_dev_docs": 'Entwicklerdoku',
        "plugin_settings": 'Einstellungen',
        "plugin_enabled": 'Aktiviert',
        "plugin_disabled": 'Deaktiviert',
        "plugin_missing_deps": 'Fehlende Abhängigkeiten: {deps}',
        "plugin_incompatible": 'Inkompatible Version',
        "plugin_error": 'Laden fehlgeschlagen',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} wird ausgeführt... {percent}%',
        "plugin_timeout": 'Plugin-Zeitüberschreitung',
        "plugin_busy": 'Ein Plugin wird ausgeführt, bitte warten',
        "plugin_not_loaded": 'Plugin nicht geladen: {id}',
        "plugin_exec_failed": 'Ausführung fehlgeschlagen',
        "plugin_config_title": '{name} - Einstellungen',
        "plugin_config_required": 'Bitte füllen Sie die Pflichtfelder aus',
        "plugin_save": 'Speichern',
        "plugin_cancel": 'Abbrechen',
        "plugin_saved_entry": 'Als neuer Eintrag gespeichert',
        "plugin_replaced_entry": 'Inhalt ersetzt',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'Netzwerkzugriff',
        "plugin_perm_file_read": 'Dateien lesen',
        "plugin_perm_file_write": 'Dateien schreiben',

        # 插件商店 Plugin store
        "plugin_store": 'Plugin-Store',
        "plugin_install": 'Installieren',
        "plugin_uninstall": 'Deinstallieren',
        "plugin_installing": 'Wird installiert...',
        "plugin_installed_tag": 'Installiert',
        "plugin_install_failed": 'Installation fehlgeschlagen',
        "plugin_uninstall_confirm_title": 'Deinstallation bestätigen',
        "plugin_uninstall_confirm": 'Möchten Sie "{name}" wirklich deinstallieren?',
        "plugin_uninstall_failed": 'Deinstallation fehlgeschlagen',
        "plugin_store_loading": 'Plugin-Liste wird geladen...',
        "plugin_store_empty": 'Keine Plugins verfügbar',
        "plugin_store_error": 'Plugin-Liste konnte nicht geladen werden',
        "plugin_no_installed": 'Keine Plugins installiert',
    },

    # ========== Русский / Russian ==========
    "ru_RU": {
        # 插件管理 Plugin management
        "plugins": 'Плагины',
        "installed_plugins": 'Установленные плагины',
        "open_plugins_dir": 'Открыть папку плагинов',
        "reload_plugins": 'Перезагрузить',
        "view_plugin_logs": 'Просмотр журналов',
        "plugin_dev_docs": 'Документация',
        "plugin_settings": 'Настройки',
        "plugin_enabled": 'Включен',
        "plugin_disabled": 'Отключен',
        "plugin_missing_deps": 'Отсутствуют зависимости: {deps}',
        "plugin_incompatible": 'Несовместимая версия',
        "plugin_error": 'Ошибка загрузки',

        # 插件运行 Plugin runtime
        "plugin_executing": '{name} выполняется... {percent}%',
        "plugin_timeout": 'Время выполнения плагина истекло',
        "plugin_busy": 'Плагин уже выполняется, пожалуйста подождите',
        "plugin_not_loaded": 'Плагин не загружен: {id}',
        "plugin_exec_failed": 'Ошибка выполнения',
        "plugin_config_title": '{name} - Настройки',
        "plugin_config_required": 'Пожалуйста, заполните обязательные поля',
        "plugin_save": 'Сохранить',
        "plugin_cancel": 'Отмена',
        "plugin_saved_entry": 'Сохранено как новая запись',
        "plugin_replaced_entry": 'Содержимое заменено',

        # 插件权限 Plugin permissions
        "plugin_perm_network": 'Сетевой доступ',
        "plugin_perm_file_read": 'Чтение файлов',
        "plugin_perm_file_write": 'Запись файлов',

        # 插件商店 Plugin store
        "plugin_store": 'Магазин плагинов',
        "plugin_install": 'Установить',
        "plugin_uninstall": 'Удалить',
        "plugin_installing": 'Установка...',
        "plugin_installed_tag": 'Установлен',
        "plugin_install_failed": 'Ошибка установки',
        "plugin_uninstall_confirm_title": 'Подтверждение удаления',
        "plugin_uninstall_confirm": 'Вы уверены, что хотите удалить "{name}"?',
        "plugin_uninstall_failed": 'Ошибка удаления',
        "plugin_store_loading": 'Загрузка списка плагинов...',
        "plugin_store_empty": 'Нет доступных плагинов',
        "plugin_store_error": 'Не удалось загрузить список плагинов',
        "plugin_no_installed": 'Нет установленных плагинов',
    },
}
