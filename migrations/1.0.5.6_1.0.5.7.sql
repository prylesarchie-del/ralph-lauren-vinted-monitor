BEGIN TRANSACTION;

-- Add Discord webhook parameters
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('discord_enabled', 'False'),
       ('discord_webhook_url', ''),
       ('discord_process_running', 'False');

-- Update version
UPDATE parameters
SET value = '1.0.5.7'
WHERE key = 'version';

COMMIT;
