<?php
/**
 * 阿里云 OSS 操作
 * 使用 REST API + HMAC-SHA1 v1 签名，不依赖 SDK
 * PHP 7.4 兼容
 */

class OSS
{
    /**
     * 上传对象到 OSS
     *
     * @param string $objectKey   对象键名（如 "images/xxx.jpg"）
     * @param string $data        文件二进制内容
     * @param string $contentType MIME 类型
     * @return bool 是否成功
     */
    public static function upload(string $objectKey, string $data, string $contentType = 'image/jpeg'): bool
    {
        $config = self::getConfig();
        $date = gmdate('D, d M Y H:i:s \G\M\T');
        $contentMd5 = base64_encode(md5($data, true));

        $canonicalResource = '/' . $config['bucket'] . '/' . $objectKey;
        $stringToSign = "PUT\n{$contentMd5}\n{$contentType}\n{$date}\n{$canonicalResource}";
        $signature = self::sign($stringToSign, $config['access_key_secret']);

        $url = sprintf(
            'https://%s.%s/%s',
            $config['bucket'],
            $config['endpoint'],
            $objectKey
        );

        $headers = [
            'Date: ' . $date,
            'Content-Type: ' . $contentType,
            'Content-MD5: ' . $contentMd5,
            'Authorization: OSS ' . $config['access_key_id'] . ':' . $signature,
            'Content-Length: ' . strlen($data),
        ];

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'PUT');
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $data);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 30);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        return $httpCode >= 200 && $httpCode < 300;
    }

    /**
     * 删除 OSS 对象
     *
     * @param string $objectKey 对象键名
     * @return bool 是否成功
     */
    public static function delete(string $objectKey): bool
    {
        $config = self::getConfig();
        $date = gmdate('D, d M Y H:i:s \G\M\T');

        $canonicalResource = '/' . $config['bucket'] . '/' . $objectKey;
        $stringToSign = "DELETE\n\n\n{$date}\n{$canonicalResource}";
        $signature = self::sign($stringToSign, $config['access_key_secret']);

        $url = sprintf(
            'https://%s.%s/%s',
            $config['bucket'],
            $config['endpoint'],
            $objectKey
        );

        $headers = [
            'Date: ' . $date,
            'Authorization: OSS ' . $config['access_key_id'] . ':' . $signature,
        ];

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'DELETE');
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 15);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        // 204 No Content 或 200 都算成功
        return $httpCode >= 200 && $httpCode < 300;
    }

    /**
     * 生成 GET presigned URL（预签名下载链接）
     *
     * @param string $objectKey 对象键名
     * @param int    $expiry    URL 有效期（秒）
     * @return string 预签名 URL
     */
    public static function getPresignedUrl(string $objectKey, int $expiry = 3600): string
    {
        $config = self::getConfig();
        $expires = time() + $expiry;

        $canonicalResource = '/' . $config['bucket'] . '/' . $objectKey;
        $stringToSign = "GET\n\n\n{$expires}\n{$canonicalResource}";
        $signature = self::sign($stringToSign, $config['access_key_secret']);

        $url = sprintf(
            'https://%s.%s/%s?OSSAccessKeyId=%s&Expires=%d&Signature=%s',
            $config['bucket'],
            $config['endpoint'],
            $objectKey,
            urlencode($config['access_key_id']),
            $expires,
            urlencode($signature)
        );

        return $url;
    }

    /**
     * HMAC-SHA1 签名（阿里云 OSS v1 签名）
     *
     * @param string $stringToSign 待签名字符串
     * @param string $secret       AccessKeySecret
     * @return string Base64 编码的签名
     */
    private static function sign(string $stringToSign, string $secret): string
    {
        return base64_encode(hash_hmac('sha1', $stringToSign, $secret, true));
    }

    /**
     * 获取 OSS 配置
     *
     * @return array
     */
    private static function getConfig(): array
    {
        static $config = null;
        if ($config === null) {
            $allConfig = require __DIR__ . '/../config.php';
            $config = $allConfig['oss'];
        }
        return $config;
    }
}
