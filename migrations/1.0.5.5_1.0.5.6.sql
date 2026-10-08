BEGIN TRANSACTION;

-- Add query_delay parameter for delay between queries
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('query_delay', '5');

-- Update version
UPDATE parameters
SET value = '1.0.5.6'
WHERE key = 'version';

COMMIT;
