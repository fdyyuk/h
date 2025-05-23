import discord
from discord.ext import commands
import os
import json
import logging
import asyncio
import aiohttp
import sqlite3
from pathlib import Path
from database import setup_database, get_connection
from datetime import datetime
from utils.command_handler import AdvancedCommandHandler
from utils.button_handler import ButtonHandler

# Setup logging dengan file handler
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Load config dengan validasi
def load_config():
    required_keys = {
        'token': str,
        'guild_id': (int, str),
        'admin_id': (int, str),
        'id_live_stock': (int, str),
        'id_log_purch': (int, str),
        'id_donation_log': (int, str),
        'id_history_buy': (int, str),
        'channels': dict,
        'roles': dict,
        'cooldowns': dict,
        'permissions': dict,
        'rate_limits': dict
    }
    
    try:
        with open('config.json', 'r') as config_file:
            config = json.load(config_file)

        # Validate and convert types
        for key, expected_type in required_keys.items():
            if key not in config:
                raise KeyError(f"Missing required key: {key}")
            
            # Handle multiple allowed types
            if isinstance(expected_type, tuple):
                if not isinstance(config[key], expected_type):
                    config[key] = expected_type[0](config[key])
            else:
                if not isinstance(config[key], expected_type):
                    config[key] = expected_type(config[key])

        return config

    except FileNotFoundError:
        logger.error("config.json file not found!")
        raise
    except json.JSONDecodeError:
        logger.error("config.json is not valid JSON!")
        raise
    except (KeyError, ValueError) as e:
        logger.error(f"Configuration error: {e}")
        raise

# Load config
config = load_config()
TOKEN = config['token']
GUILD_ID = int(config['guild_id'])
ADMIN_ID = int(config['admin_id'])
LIVE_STOCK_CHANNEL_ID = int(config['id_live_stock'])
LOG_PURCHASE_CHANNEL_ID = int(config['id_log_purch'])
DONATION_LOG_CHANNEL_ID = int(config['id_donation_log'])
HISTORY_BUY_CHANNEL_ID = int(config['id_history_buy'])

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=commands.DefaultHelpCommand(
                no_category='Commands',  # Kategori default untuk command tanpa cog
                sort_commands=True,      # Urutkan command secara alfabetis
                dm_help=False,          # Tampilkan help di channel, bukan DM
                show_hidden=False,      # Jangan tampilkan hidden commands
                verify_checks=True      # Cek permission sebelum menampilkan command
            )
        )
        self._command_handler_ready = False
        self.button_handler = ButtonHandler(self)  # Initialize button handler
        self.session = None
        self.admin_id = ADMIN_ID
        self.guild_id = GUILD_ID
        self.live_stock_channel_id = LIVE_STOCK_CHANNEL_ID
        self.log_purchase_channel_id = LOG_PURCHASE_CHANNEL_ID
        self.donation_log_channel_id = DONATION_LOG_CHANNEL_ID
        self.history_buy_channel_id = HISTORY_BUY_CHANNEL_ID
        self.config = config
        self.startup_time = datetime.utcnow()

    async def setup_hook(self):
        """Initialize bot components"""
        try:
            if not self._command_handler_ready:
                self.command_handler = AdvancedCommandHandler(self)
                self._command_handler_ready = True
                
            self.session = aiohttp.ClientSession()
            
            # Load extensions with proper error handling
            extensions = [
                'cogs.admin',
                'ext.live_stock',
                'ext.trx',
                'ext.donate',
                'ext.balance_manager',
                'ext.product_manager',
            ]
            
            loaded_extensions = set()  # Track loaded extensions
            
            for ext in extensions:
                try:
                    if ext not in loaded_extensions and not self.get_cog(ext.split('.')[-1].title()):
                        await self.load_extension(ext)
                        loaded_extensions.add(ext)
                        logger.info(f'✅ Loaded extension: {ext}')
                except Exception as e:
                    logger.error(f'❌ Failed to load {ext}: {e}')
                    logger.exception(f"Detailed error loading {ext}:")
                    continue
                    
        except Exception as e:
            logger.error(f"Fatal error in setup_hook: {e}")
            logger.exception("Detailed setup error:")

    async def close(self):
        """Cleanup when bot shuts down"""
        logger.info("Bot shutting down...")
        try:
            if self.session:
                await self.session.close()
        except Exception as e:
            logger.error(f"Error closing session: {e}")
        finally:
            await super().close()

    async def on_ready(self):
        """Event when bot is ready"""
        try:
            logger.info(f'Bot {self.user.name} is ready!')
            logger.info(f'Bot ID: {self.user.id}')
            logger.info(f'Guild ID: {self.guild_id}')
            logger.info(f'Admin ID: {self.admin_id}')
            
            # Verify channels exist
            guild = self.get_guild(self.guild_id)
            if not guild:
                logger.error(f"Could not find guild with ID {self.guild_id}")
                return

            channels = {
                'Live Stock': self.live_stock_channel_id,
                'Purchase Log': self.log_purchase_channel_id,
                'Donation Log': self.donation_log_channel_id,
                'History Buy': self.history_buy_channel_id,
                'Music': int(self.config['channels']['music']),
                'Logs': int(self.config['channels']['logs'])
            }

            for name, channel_id in channels.items():
                channel = guild.get_channel(channel_id)
                if not channel:
                    logger.error(f"Could not find {name} channel with ID {channel_id}")
                else:
                    logger.info(f"✅ Found {name} channel: {channel.name}")

            # Set custom status
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="Growtopia Shop | !help"
                ),
                status=discord.Status.online
            )
        except Exception as e:
            logger.error(f"Error in on_ready: {e}")
            logger.exception("Detailed on_ready error:")

    async def on_message(self, message):
        """Handle message events"""
        if message.author.bot:
            return

        try:
            # Log messages from specific channels
            if message.channel.id in [
                self.live_stock_channel_id,
                self.log_purchase_channel_id,
                self.donation_log_channel_id,
                self.history_buy_channel_id
            ]:
                logger.info(
                    f'Channel {message.channel.name}: '
                    f'{message.author}: {message.content}'
                )

            # Process commands only if message starts with prefix
            if message.content.startswith(self.command_prefix):
                await self.process_commands(message)
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            logger.exception("Detailed message processing error:")

    async def on_interaction(self, interaction: discord.Interaction):
        """Handle button interactions"""
        if interaction.type == discord.InteractionType.component:
            await self.button_handler.handle_button(interaction)

    async def on_command_error(self, ctx, error):
        """Global error handler for commands"""
        try:
            if isinstance(error, commands.CommandNotFound):
                return  # Ignore command not found errors
                
            command_name = ctx.command.name if ctx.command else ctx.invoked_with
            
            if isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ You don't have permission to use this command!", delete_after=5)
            elif isinstance(error, commands.CommandOnCooldown):
                await ctx.send(
                    f"⏰ Please wait {error.retry_after:.1f}s before using this command again!",
                    delete_after=5
                )
            else:
                logger.error(f"Unhandled command error in {command_name}: {error}")
                logger.exception("Detailed command error:")
                await ctx.send(
                    "❌ An error occurred while executing the command!",
                    delete_after=5
                )
        except Exception as e:
            logger.error(f"Error in error handler: {e}")
            logger.exception("Detailed error handler error:")

def run_bot():
    """Start the bot with proper error handling"""
    try:
        # Setup database
        setup_database()
        
        # Create and run bot
        bot = MyBot()
        bot.run(TOKEN, reconnect=True)
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.exception("Detailed fatal error:")
        
    finally:
        # Cleanup
        try:
            conn = get_connection()
            if conn:
                conn.close()
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

if __name__ == '__main__':
    run_bot()