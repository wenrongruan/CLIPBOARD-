"""i18n 字符串 - misc 领域。

未划入主要领域的字符串:剪贴板项、图片保存、数据迁移、关于。
"""

STRINGS = {
    # ========== 简体中文 / Simplified Chinese ==========
    "zh_CN": {
        # 剪贴板项 Clipboard items
        "confirm_delete": '确认删除',
        "delete_confirm_msg": '确定要删除这条记录吗？',
        "image": '[图片]',
        "from_device": '来自: {device}',

        # 图片保存 Image save
        "save_image": '保存图片',
        "image_load_failed": '无法加载图片数据',
        "save_failed": '保存失败: {error}',

        # 数据迁移 Data migration
        "migrate_data": '迁移数据',
        "migrate_data_confirm": '是否将现有数据迁移到新数据库？',
        "migrating": '正在迁移数据...',
        "migration_complete": '数据迁移完成，共迁移 {count} 条记录。',
        "migration_failed": '数据迁移失败: {error}',

        # 关于 About
        "about": '关于',
        "about_description": '一款跨设备剪贴板历史管理与同步工具',
        "official_website": '官方网站:',
        "github_repo": 'GitHub 仓库:',
        "download_page": '软件下载:',
    },

    # ========== English ==========
    "en_US": {
        # 剪贴板项 Clipboard items
        "confirm_delete": 'Confirm Delete',
        "delete_confirm_msg": 'Are you sure you want to delete this item?',
        "image": '[Image]',
        "from_device": 'From: {device}',

        # 图片保存 Image save
        "save_image": 'Save Image',
        "image_load_failed": 'Failed to load image data',
        "save_failed": 'Save failed: {error}',

        # 数据迁移 Data migration
        "migrate_data": 'Migrate Data',
        "migrate_data_confirm": 'Migrate existing data to the new database?',
        "migrating": 'Migrating data...',
        "migration_complete": 'Migration complete. {count} items migrated.',
        "migration_failed": 'Migration failed: {error}',

        # 关于 About
        "about": 'About',
        "about_description": 'A cross-device clipboard history management and sync tool',
        "official_website": 'Official Website:',
        "github_repo": 'GitHub Repository:',
        "download_page": 'Download:',
    },

    # ========== 日本語 / Japanese ==========
    "ja_JP": {
        # 剪贴板项 Clipboard items
        "confirm_delete": '削除の確認',
        "delete_confirm_msg": 'このアイテムを削除してもよろしいですか？',
        "image": '[画像]',
        "from_device": '送信元: {device}',

        # 图片保存 Image save
        "save_image": '画像を保存',
        "image_load_failed": '画像データの読み込みに失敗しました',
        "save_failed": '保存に失敗しました: {error}',

        # 数据迁移 Data migration
        "migrate_data": 'データ移行',
        "migrate_data_confirm": '既存のデータを新しいデータベースに移行しますか？',
        "migrating": 'データを移行中...',
        "migration_complete": '移行完了。{count} 件のアイテムを移行しました。',
        "migration_failed": '移行に失敗しました: {error}',

        # 关于 About
        "about": 'について',
        "about_description": 'クロスデバイスのクリップボード履歴管理と同期ツール',
        "official_website": '公式サイト:',
        "github_repo": 'GitHub リポジトリ:',
        "download_page": 'ダウンロード:',
    },

    # ========== 한국어 / Korean ==========
    "ko_KR": {
        # 剪贴板项 Clipboard items
        "confirm_delete": '삭제 확인',
        "delete_confirm_msg": '이 항목을 삭제하시겠습니까?',
        "image": '[이미지]',
        "from_device": '보낸 기기: {device}',

        # 图片保存 Image save
        "save_image": '이미지 저장',
        "image_load_failed": '이미지 데이터를 불러올 수 없습니다',
        "save_failed": '저장 실패: {error}',

        # 数据迁移 Data migration
        "migrate_data": '데이터 마이그레이션',
        "migrate_data_confirm": '기존 데이터를 새 데이터베이스로 마이그레이션하시겠습니까?',
        "migrating": '데이터 마이그레이션 중...',
        "migration_complete": '마이그레이션 완료. {count}개 항목이 마이그레이션되었습니다.',
        "migration_failed": '마이그레이션 실패: {error}',

        # 关于 About
        "about": '정보',
        "about_description": '크로스 디바이스 클립보드 기록 관리 및 동기화 도구',
        "official_website": '공식 웹사이트:',
        "github_repo": 'GitHub 저장소:',
        "download_page": '다운로드:',
    },

    # ========== Español / Spanish ==========
    "es_ES": {
        # 剪贴板项 Clipboard items
        "confirm_delete": 'Confirmar eliminación',
        "delete_confirm_msg": '¿Está seguro de que desea eliminar este elemento?',
        "image": '[Imagen]',
        "from_device": 'Desde: {device}',

        # 图片保存 Image save
        "save_image": 'Guardar imagen',
        "image_load_failed": 'No se pudieron cargar los datos de la imagen',
        "save_failed": 'Error al guardar: {error}',

        # 数据迁移 Data migration
        "migrate_data": 'Migrar datos',
        "migrate_data_confirm": '¿Migrar los datos existentes a la nueva base de datos?',
        "migrating": 'Migrando datos...',
        "migration_complete": 'Migración completada. {count} elementos migrados.',
        "migration_failed": 'Error en la migración: {error}',

        # 关于 About
        "about": 'Acerca de',
        "about_description": 'Herramienta de gestión y sincronización del historial del portapapeles entre dispositivos',
        "official_website": 'Sitio web oficial:',
        "github_repo": 'Repositorio GitHub:',
        "download_page": 'Descargar:',
    },

    # ========== Français / French ==========
    "fr_FR": {
        # 剪贴板项 Clipboard items
        "confirm_delete": 'Confirmer la suppression',
        "delete_confirm_msg": 'Êtes-vous sûr de vouloir supprimer cet élément?',
        "image": '[Image]',
        "from_device": 'De: {device}',

        # 图片保存 Image save
        "save_image": "Enregistrer l'image",
        "image_load_failed": "Impossible de charger les données de l'image",
        "save_failed": "Échec de l'enregistrement: {error}",

        # 数据迁移 Data migration
        "migrate_data": 'Migrer les données',
        "migrate_data_confirm": 'Migrer les données existantes vers la nouvelle base de données?',
        "migrating": 'Migration des données en cours...',
        "migration_complete": 'Migration terminée. {count} éléments migrés.',
        "migration_failed": 'Échec de la migration: {error}',

        # 关于 About
        "about": 'À propos',
        "about_description": "Outil de gestion et de synchronisation de l'historique du presse-papiers entre appareils",
        "official_website": 'Site officiel:',
        "github_repo": 'Dépôt GitHub:',
        "download_page": 'Télécharger:',
    },

    # ========== Deutsch / German ==========
    "de_DE": {
        # 剪贴板项 Clipboard items
        "confirm_delete": 'Löschen bestätigen',
        "delete_confirm_msg": 'Sind Sie sicher, dass Sie dieses Element löschen möchten?',
        "image": '[Bild]',
        "from_device": 'Von: {device}',

        # 图片保存 Image save
        "save_image": 'Bild speichern',
        "image_load_failed": 'Bilddaten konnten nicht geladen werden',
        "save_failed": 'Speichern fehlgeschlagen: {error}',

        # 数据迁移 Data migration
        "migrate_data": 'Daten migrieren',
        "migrate_data_confirm": 'Bestehende Daten in die neue Datenbank migrieren?',
        "migrating": 'Daten werden migriert...',
        "migration_complete": 'Migration abgeschlossen. {count} Elemente migriert.',
        "migration_failed": 'Migration fehlgeschlagen: {error}',

        # 关于 About
        "about": 'Über',
        "about_description": 'Ein geräteübergreifendes Tool zur Verwaltung und Synchronisierung der Zwischenablage',
        "official_website": 'Offizielle Website:',
        "github_repo": 'GitHub-Repository:',
        "download_page": 'Herunterladen:',
    },

    # ========== Русский / Russian ==========
    "ru_RU": {
        # 剪贴板项 Clipboard items
        "confirm_delete": 'Подтвердить удаление',
        "delete_confirm_msg": 'Вы уверены, что хотите удалить этот элемент?',
        "image": '[Изображение]',
        "from_device": 'От: {device}',

        # 图片保存 Image save
        "save_image": 'Сохранить изображение',
        "image_load_failed": 'Не удалось загрузить данные изображения',
        "save_failed": 'Ошибка сохранения: {error}',

        # 数据迁移 Data migration
        "migrate_data": 'Миграция данных',
        "migrate_data_confirm": 'Перенести существующие данные в новую базу данных?',
        "migrating": 'Миграция данных...',
        "migration_complete": 'Миграция завершена. Перенесено элементов: {count}.',
        "migration_failed": 'Ошибка миграции: {error}',

        # 关于 About
        "about": 'О программе',
        "about_description": 'Инструмент управления и синхронизации истории буфера обмена между устройствами',
        "official_website": 'Официальный сайт:',
        "github_repo": 'Репозиторий GitHub:',
        "download_page": 'Скачать:',
    },
}
