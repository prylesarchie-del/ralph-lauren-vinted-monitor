import threading
import time
import db
import datetime
import re
import requests
from urllib.parse import urlparse
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


class DiscordWebhook:
    def __init__(self, queue):
        self.queue = queue
        self.webhook_url = db.get_parameter("discord_webhook_url")
        
        # Start thread to check queue
        self.thread = threading.Thread(target=self.run_check_queue)
        self.thread.daemon = True
        self.thread.start()

    def run_check_queue(self):
        while True:
            try:
                self.check_discord_queue()
                time.sleep(0.1)  # Small sleep to prevent high CPU usage
            except Exception as e:
                logger.error(f"Error checking Discord queue: {str(e)}", exc_info=True)

    def check_discord_queue(self):
        if not self.queue.empty():
            try:
                content, url, text, buy_url, buy_text = self.queue.get()
                # Send item to Discord
                self.send_notification(content, url)
            except Exception as e:
                logger.error(
                    f"Error processing item for Discord webhook: {str(e)}", exc_info=True
                )

    def parse_content(self, content):
        """
        Parse the formatted content to extract title, brand, price, and image.
        This method is copied from rss_feed.py which works correctly.
        
        Returns:
            dict: Dictionary with 'title', 'brand', 'price', 'image' keys
        """
        parsed = {
            'title': '',
            'brand': '',
            'price': '',
            'image': ''
        }
        
        try:
            # Extract image link first (works for both formats)
            image_match = re.search(r'<a\s+href=["\']([^"\']+)["\']', content)
            if image_match:
                parsed['image'] = image_match.group(1)
            
            # Check if content uses emoji format (🆕 Title : ...)
            has_emoji_format = '🆕' in content or '💶' in content or '🛍️' in content
            
            if has_emoji_format:
                # Emoji format: 🆕 Title : {title}\n💶 Price : {price}\n🛍️ Brand : {brand}
                title_match = re.search(r'🆕\s*Title\s*:\s*(.+?)(?:\n|$)', content)
                if title_match:
                    parsed['title'] = title_match.group(1).strip()
                
                price_match = re.search(r'💶\s*Price\s*:\s*(.+?)(?:\n|$)', content)
                if price_match:
                    parsed['price'] = price_match.group(1).strip()
                
                brand_match = re.search(r'🛍️\s*Brand\s*:\s*(.+?)(?:\n|$)', content)
                if brand_match:
                    parsed['brand'] = brand_match.group(1).strip()
            else:
                # Simple line-based format: {title}\r\n{price}\r\n{brand}\r\n<a href="{image}">
                # Split by newlines (handle both \n and \r\n)
                lines = [line.strip() for line in re.split(r'\r?\n', content) if line.strip()]
                
                # Remove the image HTML line if present
                lines = [line for line in lines if not line.startswith('<a href')]
                
                # First line is title
                if len(lines) > 0:
                    parsed['title'] = lines[0]
                
                # Second line is price
                if len(lines) > 1:
                    parsed['price'] = lines[1]
                
                # Third line is brand
                if len(lines) > 2:
                    parsed['brand'] = lines[2]
        except Exception as e:
            logger.error(f"Error parsing content: {e}", exc_info=True)
        
        return parsed

    def create_embed(self, title, brand, price, image_url, item_url):
        """
        Create a Discord embed for a Vinted item.
        Format: Title (as embed title with link), Price, Brand (in description)
        
        Returns:
            dict: Discord embed object
        """
        # Build description with Price and Brand on separate lines (matching RSS feed format)
        # Format: Price (line 1), Brand (line 2)
        description_parts = []
        if price:
            description_parts.append(price)
        if brand:
            description_parts.append(brand)
        
        # Join with newline to ensure they're on separate lines
        description = "\n".join(description_parts)
        
        embed = {
            "title": title or "Vinted Item",
            "url": item_url,  # Makes the title clickable
            "description": description,
            "color": 0x00ff00,  # Green color
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "footer": {
                "text": "Vinted Notifications"
            }
        }
        
        # Add image if available
        if image_url:
            embed["image"] = {
                "url": image_url
            }
        
        return embed

    def format_price_with_symbol(self, price_str):
        """
        Format price string to use currency symbols instead of codes.
        Converts "8.0 GBP" to "£8.0", "10.5 EUR" to "€10.5", etc.
        
        Args:
            price_str (str): Price string like "8.0 GBP" or "10.5 EUR"
            
        Returns:
            str: Formatted price with symbol like "£8.0" or "€10.5"
        """
        if not price_str:
            return ""
        
        # Currency code to symbol mapping
        currency_map = {
            'GBP': '£',
            'EUR': '€',
            'USD': '$',
            'CAD': 'C$',
            'AUD': 'A$',
            'CHF': 'CHF',
            'PLN': 'zł',
            'CZK': 'Kč',
            'SEK': 'kr',
            'NOK': 'kr',
            'DKK': 'kr',
        }
        
        # Try to match currency code at the end
        for currency_code, symbol in currency_map.items():
            if price_str.upper().endswith(currency_code):
                # Extract the numeric part
                price_value = price_str[:-len(currency_code)].strip()
                return f"{symbol}{price_value}"
        
        # If no currency code found, return as-is
        return price_str

    def get_item_from_database(self, url):
        """
        Extract item ID from URL and get item data from database.
        This is more reliable than parsing the content string.
        
        Args:
            url (str): The Vinted item URL (e.g., https://www.vinted.fr/items/123456)
            
        Returns:
            tuple: (title, price, currency, photo_url) or None if not found
        """
        try:
            # Extract item ID from URL (format: https://www.vinted.fr/items/123456)
            parsed_url = urlparse(url)
            path_parts = [p for p in parsed_url.path.strip("/").split("/") if p]
            
            # Find the item ID (it's the number after "items" in the path)
            item_id = None
            if "items" in path_parts:
                items_index = path_parts.index("items")
                if items_index + 1 < len(path_parts):
                    item_id = path_parts[items_index + 1]
            
            if not item_id:
                # Try alternative: last numeric part of path
                for part in reversed(path_parts):
                    if part.isdigit():
                        item_id = part
                        break
            
            if item_id:
                # Query database for item
                conn = db.get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT title, price, currency, photo_url FROM items WHERE item=? ORDER BY timestamp DESC LIMIT 1",
                    (item_id,)
                )
                result = cursor.fetchone()
                conn.close()
                
                if result:
                    return result
        except Exception as e:
            logger.error(f"Error getting item from database: {e}", exc_info=True)
        
        return None

    def send_notification(self, content, url):
        """
        Send a notification to Discord via webhook.
        Uses the message template format to extract values.
        
        Args:
            content (str): The formatted content string
            url (str): The Vinted item URL
        """
        # Check if webhook URL is configured
        webhook_url = db.get_parameter("discord_webhook_url")
        if not webhook_url:
            return
        
        try:
            # Try to get item data from database first (most reliable)
            # The item was just added to the database, so it should be there
            db_item = self.get_item_from_database(url)
            
            if db_item:
                # Got data from database: (title, price, currency, photo_url)
                title, price_val, currency, image_url = db_item
                # Format price with currency symbol instead of code
                if price_val and currency:
                    price = self.format_price_with_symbol(f"{price_val} {currency}")
                else:
                    price = ""
                
                # Brand is not stored in database, so we need to parse it from content
                # The content should have the formatted template with brand info
                parsed = self.parse_content(content)
                brand = parsed.get('brand', '')
            else:
                # Fallback: parse from content (same as RSS feed)
                parsed = self.parse_content(content)
                
                title = parsed['title']
                if not title:
                    title = "Vinted Item"
                
                # Format price with currency symbol
                price_raw = parsed['price']
                price = self.format_price_with_symbol(price_raw)
                brand = parsed['brand']
                image_url = parsed['image']
            
            # Create embed using the values (matching RSS feed format: Title, Price, Brand)
            embed = self.create_embed(
                title=title,
                brand=brand,
                price=price,
                image_url=image_url,
                item_url=url
            )
            
            # Prepare payload
            payload = {
                "embeds": [embed],
                "username": "Vinted Notifications"
            }
            
            # Send webhook request
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Error sending Discord webhook: {str(e)}. "
                f"Response: {e.response.text if hasattr(e, 'response') and e.response else 'No response'}"
            )
        except Exception as e:
            logger.error(f"Error formatting Discord notification: {str(e)}", exc_info=True)


def discord_webhook_process(queue):
    """
    Process function for the Discord webhook.
    
    Args:
        queue (Queue): The queue to get new items from
    """
    logger.info("Discord webhook process started")
    try:
        webhook = DiscordWebhook(queue)
        # Keep the process running
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Discord webhook process stopped")
    except Exception as e:
        logger.error(f"Error in Discord webhook process: {e}", exc_info=True)
