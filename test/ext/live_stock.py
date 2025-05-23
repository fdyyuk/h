import discord
from discord.ext import commands, tasks
import logging
import asyncio
import json
from datetime import datetime

from .live_service import LiveStockService
from .live_views import StockView
from .constants import UPDATE_INTERVAL

# Load config
with open('config.json') as config_file:
    config = json.load(config_file)
    LIVE_STOCK_CHANNEL_ID = int(config['id_live_stock'])

class LiveStock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message = None
        self.service = LiveStockService(bot)
        self.stock_view = StockView(bot)
        self.logger = logging.getLogger("LiveStock")
        self.ready = asyncio.Event()
        
        bot.add_view(self.stock_view)

    async def cog_load(self):
        """Called when cog is being loaded"""
        try:
            self.live_stock.start()
            self.logger.info("LiveStock cog loaded and task started")
        except Exception as e:
            self.logger.error(f"Error in cog_load: {e}")
            raise

    def cog_unload(self):
        """Called when cog is being unloaded"""
        if hasattr(self, 'live_stock'):
            self.live_stock.cancel()
        self.logger.info("LiveStock cog unloaded")

    async def get_or_create_message(self):
        """Get existing message or create new one"""
        channel = self.bot.get_channel(LIVE_STOCK_CHANNEL_ID)
        if not channel:
            self.logger.error(f"Could not find channel with ID {LIVE_STOCK_CHANNEL_ID}")
            return None

        try:
            # Get last message from bot
            async for msg in channel.history(limit=1):
                if msg.author == self.bot.user:
                    return msg
                    
            # If no message found, create new one
            products = await self.service.product_manager.get_all_products()
            embed = await self.service.create_stock_embed(products)
            return await channel.send(embed=embed, view=self.stock_view)
            
        except Exception as e:
            self.logger.error(f"Error in get_or_create_message: {e}")
            return None

    @tasks.loop(seconds=UPDATE_INTERVAL)
    async def live_stock(self):
        """Update live stock message"""
        try:
            if not self.message:
                self.message = await self.get_or_create_message()
                if not self.message:
                    return

            products = await self.service.product_manager.get_all_products()
            embed = await self.service.create_stock_embed(products)

            try:
                await self.message.edit(embed=embed, view=self.stock_view)
                self.logger.debug(f"Updated message {self.message.id}")
            except discord.NotFound:
                self.message = await self.get_or_create_message()
                self.logger.info("Created new message as old one was not found")
            
        except Exception as e:
            self.logger.error(f"Error in live_stock update: {e}")
            # Reset message if error occurs
            self.message = None

    @live_stock.before_loop
    async def before_live_stock(self):
        """Wait for bot to be ready before starting the loop"""
        await self.bot.wait_until_ready()

    @live_stock.error
    async def on_live_stock_error(self, exc):
        """Handle any errors in the live_stock loop"""
        self.logger.error(f"Error in live_stock task: {exc}")
        if self.live_stock.is_running():
            self.live_stock.restart()

async def setup(bot):
    """Setup the LiveStock cog"""
    try:
        await bot.add_cog(LiveStock(bot))
        logging.info('LiveStock cog loaded successfully')
    except Exception as e:
        logging.error(f"Error loading LiveStock cog: {e}")
        raise