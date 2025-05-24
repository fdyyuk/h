import discord
import logging
import time
from datetime import datetime
from typing import Optional

from .product_manager import ProductManagerService
from .constants import CACHE_TIMEOUT

class LiveStockService:
    _instance = None

    def __new__(cls, bot):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, bot):
        if not self.initialized:
            self.bot = bot
            self.logger = logging.getLogger("LiveStockService")
            self.product_manager = ProductManagerService(bot)
            self._cache = {}
            self._cache_timeout = CACHE_TIMEOUT
            self.initialized = True

    def _get_cached(self, key: str):
        if key in self._cache:
            data = self._cache[key]
            if time.time() - data['timestamp'] < self._cache_timeout:
                return data['value']
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value):
        self._cache[key] = {
            'value': value,
            'timestamp': time.time()
        }

    async def create_stock_embed(self, products: list) -> discord.Embed:
        # Nonaktifkan caching untuk memastikan data selalu fresh
        embed = discord.Embed(
            title="🏪 Store Stock Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        if products:
            for product in sorted(products, key=lambda x: x['code']):
                # Force invalidate cache dan ambil data fresh
                self.product_manager.invalidate_cache(product['code'])
                stock_count = await self.product_manager.get_stock_count(product['code'])
                
                # Tambah logging untuk debugging
                self.logger.info(f"Live Stock Update - Product: {product['code']}, Stock Count: {stock_count}")
                
                value = (
                    f"💎 Code: `{product['code']}`\n"
                    f"📦 Stock: `{stock_count}`\n"
                    f"💰 Price: `{product['price']:,} WL`\n"
                )
                if product.get('description'):
                    value += f"📝 Info: {product['description']}\n"
                
                embed.add_field(
                    name=f"🔸 {product['name']} 🔸",
                    value=value,
                    inline=False
                )
        else:
            embed.description = "No products available."

        embed.set_footer(text=f"Last Update: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        return embed

    async def cleanup(self):
        """Cleanup resources"""
        self._cache.clear()