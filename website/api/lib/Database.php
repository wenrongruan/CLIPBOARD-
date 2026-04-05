<?php
/**
 * PDO 数据库单例
 * 连接阿里云 RDS MySQL，utf8mb4，errmode exception，默认 fetch assoc
 */

class Database
{
    /** @var PDO|null */
    private static ?PDO $instance = null;

    /**
     * 获取 PDO 单例
     */
    public static function getInstance(): PDO
    {
        if (self::$instance === null) {
            $config = require __DIR__ . '/../config.php';
            $db = $config['db'];

            $dsn = sprintf(
                'mysql:host=%s;port=%s;dbname=%s;charset=%s',
                $db['host'],
                $db['port'],
                $db['database'],
                $db['charset']
            );

            self::$instance = new PDO($dsn, $db['username'], $db['password'], [
                PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES   => false,
                PDO::MYSQL_ATTR_INIT_COMMAND => "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci",
            ]);
        }

        return self::$instance;
    }

    /**
     * 禁止实例化
     */
    private function __construct() {}

    /**
     * 禁止克隆
     */
    private function __clone() {}
}
