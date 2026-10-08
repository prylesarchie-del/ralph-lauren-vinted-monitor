#!/usr/bin/env python3
"""
Configuration Update Script for Vinted Notifications

This script reads a YAML configuration file and updates the database
parameters that are available in the web UI.

Usage:
    python update_config.py [config_file]

If no config_file is provided, it defaults to 'config.yaml' in the current directory.
"""

import sys
import os
import yaml
import json
from pathlib import Path

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from logger import get_logger

logger = get_logger(__name__)


def validate_config(config):
    """
    Validate the configuration dictionary.
    
    Args:
        config (dict): Configuration dictionary
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Define valid parameter keys
    valid_keys = {
        # Telegram
        'telegram_enabled', 'telegram_token', 'telegram_chat_id',
        # RSS
        'rss_enabled', 'rss_port', 'rss_max_items',
        # Discord
        'discord_enabled', 'discord_webhook_url',
        # System
        'items_per_query', 'query_refresh_delay', 'query_delay', 'banwords',
        # Proxy
        'check_proxies', 'proxy_list', 'proxy_list_link',
        # Advanced
        'message_template', 'user_agents', 'default_headers'
    }
    
    # Check for invalid keys
    invalid_keys = set(config.keys()) - valid_keys
    if invalid_keys:
        return False, f"Invalid configuration keys: {', '.join(invalid_keys)}"
    
    # Validate boolean values
    boolean_keys = {'telegram_enabled', 'rss_enabled', 'discord_enabled', 'check_proxies'}
    for key in boolean_keys:
        if key in config:
            value = config[key]
            if not isinstance(value, bool):
                return False, f"{key} must be a boolean (True/False), got {type(value).__name__}"
    
    # Validate numeric values
    numeric_keys = {'rss_port', 'rss_max_items', 'items_per_query', 'query_refresh_delay', 'query_delay'}
    for key in numeric_keys:
        if key in config:
            value = config[key]
            if not isinstance(value, (int, float)):
                try:
                    int(value)
                except (ValueError, TypeError):
                    return False, f"{key} must be a number, got {type(value).__name__}"
    
    # Validate JSON strings
    json_keys = {'user_agents', 'default_headers'}
    for key in json_keys:
        if key in config:
            value = config[key]
            if isinstance(value, str):
                try:
                    json.loads(value)
                except json.JSONDecodeError as e:
                    return False, f"{key} must be valid JSON: {str(e)}"
            elif not isinstance(value, (list, dict)):
                return False, f"{key} must be a JSON string, list, or dict"
    
    return True, None


def convert_value(value):
    """
    Convert a value to the appropriate string format for database storage.
    
    Args:
        value: Value to convert
        
    Returns:
        str: String representation suitable for database storage
    """
    if isinstance(value, bool):
        return str(value)
    elif isinstance(value, (list, dict)):
        return json.dumps(value)
    elif value is None:
        return ''
    else:
        return str(value)


def update_config_from_file(config_file):
    """
    Read configuration from a YAML file and update the database.
    
    Args:
        config_file (str): Path to the YAML configuration file
        
    Returns:
        bool: True if successful, False otherwise
    """
    config_path = Path(config_file)
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_file}")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if not config:
            logger.error("Configuration file is empty or invalid")
            return False
        
        # Validate configuration
        is_valid, error_msg = validate_config(config)
        if not is_valid:
            logger.error(f"Configuration validation failed: {error_msg}")
            return False
        
        # Update parameters
        updated_count = 0
        skipped_count = 0
        
        for key, value in config.items():
            try:
                # Convert value to string format
                db_value = convert_value(value)
                
                # Update parameter in database
                db.set_parameter(key, db_value)
                logger.info(f"Updated {key} = {db_value}")
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update {key}: {str(e)}")
                skipped_count += 1
        
        # Reset proxy cache if proxy settings were updated
        proxy_keys = {'check_proxies', 'proxy_list', 'proxy_list_link'}
        if any(key in config for key in proxy_keys):
            db.set_parameter("last_proxy_check_time", "1")
            logger.info("Proxy cache reset (proxy settings were updated)")
        
        logger.info(f"Configuration update complete: {updated_count} parameters updated, {skipped_count} skipped")
        return True
        
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return False


def main():
    """Main entry point for the script."""
    # Default config file
    default_config = "config.yaml"
    
    # Get config file from command line argument or use default
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = default_config
    
    logger.info(f"Reading configuration from: {config_file}")
    
    success = update_config_from_file(config_file)
    
    if success:
        logger.info("Configuration updated successfully!")
        sys.exit(0)
    else:
        logger.error("Configuration update failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
