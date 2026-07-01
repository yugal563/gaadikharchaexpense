-- ==========================================
-- Database Schema for Vehicle Expense Tracker
-- Database: expenses
-- Target DB Platform: MySQL / MariaDB
-- ==========================================

CREATE DATABASE IF NOT EXISTS `expenses`;
USE `expenses`;

-- --------------------------------------------------
-- 1. Table: fuel
-- Stores expense records related to vehicle fueling.
-- --------------------------------------------------
CREATE TABLE IF NOT EXISTS `fuel` (
    `fuel_id` INT AUTO_INCREMENT PRIMARY KEY,
    `vehicle` VARCHAR(50) DEFAULT NULL,
    `registration_no` VARCHAR(20) DEFAULT NULL,
    `expense_date` DATE NOT NULL,
    `petrol_pump` VARCHAR(100) DEFAULT NULL,
    `location` VARCHAR(100) DEFAULT NULL,
    `fuel_type` VARCHAR(20) DEFAULT NULL,
    `liters` DECIMAL(10, 2) DEFAULT NULL,
    `rate_per_liter` DECIMAL(10, 2) DEFAULT NULL,
    `odometer` INT DEFAULT NULL,
    `amount` DECIMAL(12, 2) NOT NULL,
    `total_amount` DECIMAL(12, 2) DEFAULT NULL,
    `invoice_number` VARCHAR(50) DEFAULT NULL,
    `taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `non_taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `gst_percentage` DECIMAL(5, 2) DEFAULT NULL,
    `gst_amount` DECIMAL(12, 2) DEFAULT NULL,
    `payment_mode` VARCHAR(50) DEFAULT NULL,
    `paid` TINYINT(1) NOT NULL DEFAULT 0,
    `paid_to` VARCHAR(255) DEFAULT NULL,
    `contact_number` VARCHAR(15) DEFAULT NULL,
    `job_id` VARCHAR(36) DEFAULT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_fuel_registration_no` (`registration_no`),
    KEY `idx_fuel_expense_date` (`expense_date`),
    KEY `idx_fuel_job_id` (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------
-- 2. Table: maintenance
-- Stores vehicle maintenance, servicing, and repair details.
-- --------------------------------------------------
CREATE TABLE IF NOT EXISTS `maintenance` (
    `maintenance_id` INT AUTO_INCREMENT PRIMARY KEY,
    `vehicle` VARCHAR(50) DEFAULT NULL,
    `registration_no` VARCHAR(20) DEFAULT NULL,
    `expense_date` DATE NOT NULL,
    `service_type` VARCHAR(100) DEFAULT NULL,
    `vendor` VARCHAR(100) DEFAULT NULL,
    `vendor_type` VARCHAR(20) DEFAULT NULL,
    `maintenance_item` VARCHAR(100) DEFAULT NULL,
    `custom_maintenance_item` VARCHAR(255) DEFAULT NULL,
    `action_type` VARCHAR(50) DEFAULT NULL,
    `odometer` INT DEFAULT NULL,
    `next_service_due` INT DEFAULT NULL,
    `work_order_number` VARCHAR(50) DEFAULT NULL,
    `invoice_number` VARCHAR(50) DEFAULT NULL,
    `amount` DECIMAL(12, 2) NOT NULL,
    `total_amount` DECIMAL(12, 2) DEFAULT NULL,
    `taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `non_taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `gst_percentage` DECIMAL(5, 2) DEFAULT NULL,
    `gst_amount` DECIMAL(12, 2) DEFAULT NULL,
    `payment_mode` VARCHAR(50) DEFAULT NULL,
    `paid` TINYINT(1) NOT NULL DEFAULT 0,
    `paid_to` VARCHAR(255) DEFAULT NULL,
    `contact_number` VARCHAR(15) DEFAULT NULL,
    `items` TEXT DEFAULT NULL,
    `job_id` VARCHAR(36) DEFAULT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_maintenance_registration_no` (`registration_no`),
    KEY `idx_maintenance_expense_date` (`expense_date`),
    KEY `idx_maintenance_job_id` (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------
-- 3. Table: vehicle
-- Stores general vehicle expenditures (e.g., tolls, parking, challans, transport rentals).
-- --------------------------------------------------
CREATE TABLE IF NOT EXISTS `vehicle` (
    `vehicle_expense_id` INT AUTO_INCREMENT PRIMARY KEY,
    `vehicle` VARCHAR(50) DEFAULT NULL,
    `registration_no` VARCHAR(20) DEFAULT NULL,
    `expense_date` DATE NOT NULL,
    `challan_no` VARCHAR(50) DEFAULT NULL,
    `challan_type` VARCHAR(100) DEFAULT NULL,
    `violation_type` VARCHAR(255) DEFAULT NULL,
    `issued_by` VARCHAR(100) DEFAULT NULL,
    `due_date` DATE DEFAULT NULL,
    `parking_location` VARCHAR(100) DEFAULT NULL,
    `km_limit` INT DEFAULT NULL,
    `hour_limit` INT DEFAULT NULL,
    `excess_km_rate` DECIMAL(10, 2) DEFAULT NULL,
    `excess_hour_rate` DECIMAL(10, 2) DEFAULT NULL,
    `excess_km_amount` DECIMAL(12, 2) DEFAULT NULL,
    `excess_hour_amount` DECIMAL(12, 2) DEFAULT NULL,
    `driver_allowance` DECIMAL(12, 2) DEFAULT NULL,
    `toll_charges` DECIMAL(12, 2) DEFAULT NULL,
    `parking_charges` DECIMAL(12, 2) DEFAULT NULL,
    `other_charges` DECIMAL(12, 2) DEFAULT NULL,
    `start_odometer_reading` DECIMAL(10, 2) DEFAULT NULL,
    `end_odometer_reading` DECIMAL(10, 2) DEFAULT NULL,
    `journey_start_datetime` DATETIME DEFAULT NULL,
    `journey_end_datetime` DATETIME DEFAULT NULL,
    `invoice_number` VARCHAR(50) DEFAULT NULL,
    `amount` DECIMAL(12, 2) NOT NULL,
    `total_amount` DECIMAL(12, 2) DEFAULT NULL,
    `taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `non_taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `gst_percentage` DECIMAL(5, 2) DEFAULT NULL,
    `gst_amount` DECIMAL(12, 2) DEFAULT NULL,
    `gst_invoicing_type` VARCHAR(50) DEFAULT NULL,
    `gst_applicable_on_parking` TINYINT(1) DEFAULT NULL,
    `gst_applicable_on_toll` TINYINT(1) DEFAULT NULL,
    `gst_applicable_on_other_charges` TINYINT(1) DEFAULT NULL,
    `tds_percentage` DECIMAL(5, 2) DEFAULT NULL,
    `tds_amount` DECIMAL(12, 2) DEFAULT NULL,
    `payment_mode` VARCHAR(50) DEFAULT NULL,
    `paid` TINYINT(1) NOT NULL DEFAULT 0,
    `paid_to` VARCHAR(255) DEFAULT NULL,
    `contact_number` VARCHAR(15) DEFAULT NULL,
    `items` TEXT DEFAULT NULL,
    `job_id` VARCHAR(36) DEFAULT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_vehicle_registration_no` (`registration_no`),
    KEY `idx_vehicle_expense_date` (`expense_date`),
    KEY `idx_vehicle_job_id` (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------
-- 4. Table: other
-- Stores fallback/miscellaneous expenses.
-- --------------------------------------------------
CREATE TABLE IF NOT EXISTS `other` (
    `other_id` INT AUTO_INCREMENT PRIMARY KEY,
    `vehicle` VARCHAR(50) DEFAULT NULL,
    `registration_no` VARCHAR(20) DEFAULT NULL,
    `expense_date` DATE NOT NULL,
    `party_type` VARCHAR(100) DEFAULT NULL,
    `party` VARCHAR(100) DEFAULT NULL,
    `expense_name` VARCHAR(100) DEFAULT NULL,
    `vendor` VARCHAR(100) DEFAULT NULL,
    `location` VARCHAR(100) DEFAULT NULL,
    `invoice_number` VARCHAR(50) DEFAULT NULL,
    `amount` DECIMAL(12, 2) NOT NULL,
    `total_amount` DECIMAL(12, 2) DEFAULT NULL,
    `taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `non_taxable_amount` DECIMAL(12, 2) DEFAULT NULL,
    `gst_percentage` DECIMAL(5, 2) DEFAULT NULL,
    `gst_amount` DECIMAL(12, 2) DEFAULT NULL,
    `payment_mode` VARCHAR(50) DEFAULT NULL,
    `paid` TINYINT(1) NOT NULL DEFAULT 0,
    `paid_to` VARCHAR(255) DEFAULT NULL,
    `contact_number` VARCHAR(15) DEFAULT NULL,
    `items` TEXT DEFAULT NULL,
    `job_id` VARCHAR(36) DEFAULT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_other_registration_no` (`registration_no`),
    KEY `idx_other_expense_date` (`expense_date`),
    KEY `idx_other_job_id` (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------
-- 5. Table: stage_tracking
-- Tracks the receipt processing status across different pipeline stages.
-- --------------------------------------------------
CREATE TABLE IF NOT EXISTS `stage_tracking` (
    `job_id` VARCHAR(36) PRIMARY KEY,
    `filename` VARCHAR(255) DEFAULT NULL,
    `status` VARCHAR(50) DEFAULT NULL,
    `current_stage` VARCHAR(50) DEFAULT NULL,
    `original_url` VARCHAR(500) DEFAULT NULL,
    `preprocessed_url` VARCHAR(500) DEFAULT NULL,
    `category` VARCHAR(50) DEFAULT NULL,
    `expense_row_id` INT DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `stage1_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `stage2_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `stage3_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `stage4_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `stage5_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `stage6_completed_at` TIMESTAMP NULL DEFAULT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_stage_tracking_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
