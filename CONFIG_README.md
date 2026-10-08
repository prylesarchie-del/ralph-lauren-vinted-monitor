# Configuration Update Script

This script allows you to update all configuration options available in the web UI by reading from a YAML configuration file.

## Prerequisites

Install the required dependency:
```bash
pip install pyyaml
```

## Usage

1. Copy the example configuration file:
   ```bash
   cp config.yaml.example config.yaml
   ```

2. Edit `config.yaml` with your desired settings. You can omit any parameters you don't want to change.

3. Run the script:
   ```bash
   python update_config.py config.yaml
   ```
   
   Or if you use the default filename (`config.yaml`):
   ```bash
   python update_config.py
   ```

## Configuration File Format

The configuration file uses YAML format. Here's what each section does:

### Telegram Bot Settings
- `telegram_enabled`: `true` or `false` - Enable/disable Telegram bot
- `telegram_token`: Bot token from BotFather
- `telegram_chat_id`: Chat ID where notifications will be sent

### RSS Feed Settings
- `rss_enabled`: `true` or `false` - Enable/disable RSS feed
- `rss_port`: Port number for RSS feed (default: 18473)
- `rss_max_items`: Maximum items in RSS feed (default: 100)

### Discord Webhook Settings
- `discord_enabled`: `true` or `false` - Enable/disable Discord webhook
- `discord_webhook_url`: Your Discord webhook URL

### System Settings
- `items_per_query`: Maximum items to fetch per query (default: 20)
- `query_refresh_delay`: Delay between query refreshes in seconds (default: 60)
- `query_delay`: Delay between processing each query in seconds (default: 5)
- `banwords`: Words to filter out, separated by `|||` (e.g., `"word1|||word2|||word3"`)

### Proxy Settings
- `check_proxies`: `true` or `false` - Verify proxies before using them
- `proxy_list`: Semicolon-separated list of proxies (format: `http://ip:port` or `ip:port`)
- `proxy_list_link`: URL to fetch proxies from (one per line)

### Advanced Settings
- `message_template`: Template for notification messages (variables: `{title}`, `{price}`, `{brand}`, `{image}`)
- `user_agents`: JSON array of user agents (e.g., `'["Mozilla/5.0...", "Mozilla/5.0..."]'`)
- `default_headers`: JSON object of default headers (e.g., `'{"Accept": "application/json"}'`)

## Examples

### Minimal Configuration (Discord only)
```yaml
discord_enabled: true
discord_webhook_url: "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
query_refresh_delay: 1200
items_per_query: 10
query_delay: 5
```

### Full Configuration
See `config.yaml.example` for a complete example with all options.

## Notes

- The script validates all configuration values before updating
- Boolean values must be `true`/`false` (not strings)
- Numeric values can be integers or floats
- JSON values (`user_agents`, `default_headers`) must be valid JSON strings
- If proxy settings are updated, the proxy cache is automatically reset
- Parameters not specified in the config file will remain unchanged

## Troubleshooting

If you encounter errors:
1. Check that the YAML file is valid (no syntax errors)
2. Ensure boolean values are `true`/`false`, not `"True"`/`"False"` or `"yes"`/`"no"`
3. Verify JSON strings are properly formatted
4. Check the logs for detailed error messages
