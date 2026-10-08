BEGIN TRANSACTION;

-- Add retention_months parameter for database cleanup
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('retention_months', '2');

-- Update version
UPDATE parameters
SET value = '1.0.5.5'
WHERE key = 'version';

COMMIT;

