CREATE TABLE `orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `plan` varchar(50) NOT NULL,
  `amount_jpy` int NOT NULL,
  `company_name` varchar(255) NOT NULL,
  `contact_name` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `phone` varchar(50) DEFAULT NULL,
  `schedule_note` text,
  `campaign_note` text,
  `payment_method` enum('paypal','usdt') NOT NULL,
  `paypal_txn_id` varchar(255) DEFAULT NULL,
  `usdt_tx_hash` varchar(255) DEFAULT NULL,
  `status` varchar(50) NOT NULL DEFAULT 'pending_payment',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
