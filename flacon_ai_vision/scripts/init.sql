-- Falcon AI Vision Database Initialization Script
-- This script runs automatically when the MySQL container starts

-- Create application user if not exists
CREATE USER IF NOT EXISTS 'falcon'@'%' IDENTIFIED BY 'falcon_ai_vision_pwd';
GRANT ALL PRIVILEGES ON eye_of_falcon.* TO 'falcon'@'%';
FLUSH PRIVILEGES;

-- Use the database
USE eye_of_falcon;

-- Enable event scheduler for automated tasks
SET GLOBAL event_scheduler = ON;

-- Create basic tables (if needed)
-- These should also be created by SQLAlchemy ORM
CREATE TABLE IF NOT EXISTS schema_version (
  id INT PRIMARY KEY AUTO_INCREMENT,
  version VARCHAR(50) NOT NULL,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY unique_version (version)
);

-- Log initial setup
INSERT IGNORE INTO schema_version (version) VALUES ('initial_setup_docker');

-- Create cleanup event (optional - cleanup old records)
CREATE EVENT IF NOT EXISTS cleanup_old_records
ON SCHEDULE EVERY 1 DAY
DO DELETE FROM events WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);

-- Default admin user (optional - can be created via API)
-- Note: Password should be hashed using passlib
-- INSERT IGNORE INTO users (username, email, hashed_password, is_active, role)
-- VALUES ('admin', 'admin@localhost', '<hashed_password>', TRUE, 'admin');
