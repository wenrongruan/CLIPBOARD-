<?php
/**
 * JSON 响应辅助类
 */

class Response
{
    /**
     * 输出 JSON 响应并退出
     *
     * @param mixed $data 响应数据
     * @param int   $code HTTP 状态码
     */
    public static function json($data, int $code = 200): void
    {
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    /**
     * 输出错误 JSON 响应并退出
     *
     * @param string $message 错误消息
     * @param int    $code    HTTP 状态码
     * @param array  $extra   额外数据，合并到响应中
     */
    public static function error(string $message, int $code = 400, array $extra = []): void
    {
        $body = array_merge([
            'success' => false,
            'error'   => $message,
        ], $extra);

        self::json($body, $code);
    }

    /**
     * 输出成功 JSON 响应并退出
     *
     * @param mixed  $data    响应数据
     * @param string $message 成功消息
     */
    public static function success($data = null, string $message = 'ok'): void
    {
        $body = ['success' => true];

        if (is_array($data)) {
            $body = array_merge($body, $data);
        }

        self::json($body, 200);
    }
}
