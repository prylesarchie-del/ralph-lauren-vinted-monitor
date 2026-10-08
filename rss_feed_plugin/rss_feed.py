from flask import Flask, Response
import threading
import time
import db
import datetime
import html
import re
from logger import get_logger
from feedgen.feed import FeedGenerator

# Get logger for this module
logger = get_logger(__name__)


class RSSFeed:
    def __init__(self, queue):
        self.app = Flask(__name__)
        self.queue = queue
        self.items = []
        max_items_param = db.get_parameter("rss_max_items")
        try:
            self.max_items = int(max_items_param) if max_items_param else 100
        except (ValueError, TypeError):
            logger.warning(f"Invalid rss_max_items value: {max_items_param}, using default 100")
            self.max_items = 100

        # Initialize feed generator
        self.fg = FeedGenerator()
        self.fg.title("Vinted Notifications")
        self.fg.description("Latest items from Vinted matching your search queries")
        self.fg.link(href=f'http://localhost:{db.get_parameter("rss_port")}')
        self.fg.language("en")

        # Set up routes
        self.app.route("/")(self.serve_rss)

        # Start thread to check queue
        self.thread = threading.Thread(target=self.run_check_queue)
        self.thread.daemon = True
        self.thread.start()

    def run_check_queue(self):
        while True:
            try:
                self.check_rss_queue()
                time.sleep(0.1)  # Small sleep to prevent high CPU usage
            except Exception as e:
                logger.error(f"Error checking RSS queue: {str(e)}", exc_info=True)

    def check_rss_queue(self):
        if not self.queue.empty():
            try:
                content, url, text, buy_url, buy_text = self.queue.get()

                # Add item to the feed
                self.add_item_to_feed(content, url)
            except Exception as e:
                logger.error(
                    f"Error processing item for RSS feed: {str(e)}", exc_info=True
                )

    def parse_content(self, content):
        """
        Parse the formatted content to extract title, brand, price, and image.
        
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
            # Extract title (🆕 Title : {title})
            title_match = re.search(r'🆕\s*Title\s*:\s*(.+?)(?:\n|$)', content)
            if title_match:
                parsed['title'] = title_match.group(1).strip()
            else:
                # Fallback: try to extract any text before first newline or emoji
                first_line = content.split('\n')[0].strip()
                if first_line and not first_line.startswith('🆕'):
                    parsed['title'] = first_line
            
            # Extract brand (🛍️ Brand : {brand})
            brand_match = re.search(r'🛍️\s*Brand\s*:\s*(.+?)(?:\n|$)', content)
            if brand_match:
                parsed['brand'] = brand_match.group(1).strip()
            
            # Extract price (💶 Price : {price})
            price_match = re.search(r'💶\s*Price\s*:\s*(.+?)(?:\n|$)', content)
            if price_match:
                parsed['price'] = price_match.group(1).strip()
            
            # Extract image link (<a href="{image}">)
            image_match = re.search(r'<a\s+href=["\']([^"\']+)["\']', content)
            if image_match:
                parsed['image'] = image_match.group(1)
        except Exception as e:
            logger.debug(f"Error parsing content: {e}")
        
        return parsed

    def format_rss_description(self, brand, price, image):
        """
        Format the RSS description with just the values on separate lines.
        Title is excluded as it's already in the RSS entry title.
        
        Returns:
            str: Formatted description with HTML-escaped text and image link
        """
        lines = []
        
        if brand:
            lines.append(html.escape(brand))
        if price:
            lines.append(html.escape(price))
        if image:
            lines.append(f'<a href="{html.escape(image)}">{html.escape(image)}</a>')
        
        return '\n'.join(lines)

    def add_item_to_feed(self, content, url):
        # Parse content to extract values
        parsed = self.parse_content(content)
        title = parsed['title']
        
        # Ensure we have a title - use URL as last resort
        if not title:
            title = "Vinted Item"
            logger.warning(f"Could not extract title from content, using fallback for URL: {url}")
        
        # Add to our items list (for tracking)
        # Store as tuple: (title, url, parsed_data, published_datetime)
        published_time = datetime.datetime.now(datetime.timezone.utc)
        self.items.append((title, url, parsed, published_time))

        # Limit the number of items (keep most recent)
        if len(self.items) > self.max_items:
            self.items.pop(0)

    def serve_rss(self):
        # Rebuild feed generator with only the most recent items
        # This ensures we always return the most recent max_items
        self.fg = FeedGenerator()
        self.fg.title("Vinted Notifications")
        self.fg.description("Latest items from Vinted matching your search queries")
        self.fg.link(href=f'http://localhost:{db.get_parameter("rss_port")}')
        self.fg.language("en")

        # Add entries from items list (most recent first, limit to max_items)
        # Items are stored as (title, url, parsed_data, published_time)
        # Sort by published_time descending to get most recent first
        sorted_items = sorted(self.items, key=lambda x: x[3], reverse=True)
        for title, url, parsed, published_time in sorted_items[:self.max_items]:
            fe = self.fg.add_entry()
            fe.id(url)
            fe.title(title)
            fe.link(href=url)
            
            # Format description with just the values (title excluded as it's in entry title)
            description = self.format_rss_description(
                parsed['brand'],
                parsed['price'],
                parsed['image']
            )
            fe.description(description)
            fe.published(published_time)

        return Response(self.fg.rss_str(), mimetype="application/rss+xml")

    def run(self):

        try:
            port_param = db.get_parameter("rss_port")
            try:
                port = int(port_param) if port_param else 18473
            except (ValueError, TypeError):
                logger.warning(f"Invalid rss_port value: {port_param}, using default 18473")
                port = 18473
            logger.info(f"Starting RSS feed server on port {port}")
            self.app.run(host="0.0.0.0", port=port)
        except Exception as e:
            logger.error(f"Error starting RSS feed server: {str(e)}", exc_info=True)


def rss_feed_process(queue):
    """
    Process function for the RSS feed.

    Args:
        queue (Queue): The queue to get new items from
    """
    logger.info("RSS feed process started")
    try:
        feed = RSSFeed(queue)
        feed.run()
    except (KeyboardInterrupt, SystemExit):
        logger.info("RSS feed process stopped")
    except Exception as e:
        logger.error(f"Error in RSS feed process: {e}", exc_info=True)
