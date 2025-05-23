import discord
from discord import ui
from discord.ext import tasks
import logging
import time
import asyncio
from datetime import datetime

from .balance_manager import BalanceManagerService
from .product_manager import ProductManagerService
from .trx import TransactionManager
from .live_modals import BuyModal, SetGrowIDModal
from .constants import COOLDOWN_SECONDS

class StockView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = logging.getLogger("StockView")
        
        try:
            self.balance_manager = BalanceManagerService(bot)
            self.product_manager = ProductManagerService(bot)
            self.trx_manager = TransactionManager(bot)
        except Exception as e:
            self.logger.error(f"Error initializing services: {e}")
            raise
            
        self._cooldowns = {}
        self._interaction_locks = {}
        self._cache_cleanup.start()

    @tasks.loop(minutes=5)
    async def _cache_cleanup(self):
        """Cleanup expired cache entries"""
        try:
            current_time = time.time()
            self._cooldowns = {
                k: v for k, v in self._cooldowns.items()
                if current_time - v < COOLDOWN_SECONDS
            }
            self._interaction_locks = {
                k: v for k, v in self._interaction_locks.items()
                if current_time - v < 1.0
            }
        except Exception as e:
            self.logger.error(f"Error in cache cleanup: {e}")

    async def _check_cooldown(self, interaction: discord.Interaction) -> bool:
        try:
            user_id = interaction.user.id
            current_time = time.time()
            
            if user_id in self._cooldowns:
                remaining = COOLDOWN_SECONDS - (current_time - self._cooldowns[user_id])
                if remaining > 0:
                    await self._safe_interaction_response(
                        interaction,
                        content=f"⏳ Please wait {remaining:.1f} seconds...",
                        ephemeral=True
                    )
                    return False
            
            self._cooldowns[user_id] = current_time
            return True
        except Exception as e:
            self.logger.error(f"Error checking cooldown: {e}")
            return False

    async def _check_interaction_lock(self, interaction: discord.Interaction) -> bool:
        try:
            user_id = interaction.user.id
            current_time = time.time()
            
            if user_id in self._interaction_locks:
                if current_time - self._interaction_locks[user_id] < 1.0:
                    return False
            
            self._interaction_locks[user_id] = current_time
            return True
        except Exception as e:
            self.logger.error(f"Error checking interaction lock: {e}")
            return False

    async def _safe_interaction_response(self, interaction: discord.Interaction, **kwargs):
        try:
            # Tambahkan delay kecil untuk menghindari race condition
            await asyncio.sleep(0.1)
            
            if interaction.is_expired():
                self.logger.debug(f"Interaction {interaction.id} has expired")
                return
                
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(**kwargs)
                else:
                    await interaction.followup.send(**kwargs)
            except discord.errors.InteractionResponded:
                try:
                    await interaction.followup.send(**kwargs)
                except Exception as e:
                    self.logger.error(f"Error sending followup: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error in _safe_interaction_response: {e}")

    @discord.ui.button(
        label="Balance",
        emoji="💰",
        style=discord.ButtonStyle.primary,
        custom_id="balance:1"
    )
    async def button_balance_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_cooldown(interaction) or not await self._check_interaction_lock(interaction):
            return

        try:
            if not hasattr(self, 'balance_manager'):
                self.logger.error("BalanceManagerService not initialized")
                await self._safe_interaction_response(
                    interaction,
                    content="❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(interaction.user.id)
            if not growid:
                await interaction.followup.send("❌ Please set your GrowID first!", ephemeral=True)
                return

            balance = await self.balance_manager.get_balance(growid)
            if not balance:
                await interaction.followup.send("❌ Balance not found!", ephemeral=True)
                return

            embed = discord.Embed(
                title="💰 Balance Information",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="GrowID", value=f"`{growid}`", inline=False)
            embed.add_field(name="Balance", value=balance.format(), inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in balance callback: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)

    @discord.ui.button(
        label="Buy",
        emoji="🛒",
        style=discord.ButtonStyle.success,
        custom_id="buy:1"
    )
    async def button_buy_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_cooldown(interaction) or not await self._check_interaction_lock(interaction):
            return

        try:
            if not hasattr(self, 'product_manager'):
                self.logger.error("ProductManagerService not initialized")
                await self._safe_interaction_response(
                    interaction,
                    content="❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return

            growid = await self.balance_manager.get_growid(interaction.user.id)
            if not growid:
                await interaction.response.send_message(
                    "❌ Please set your GrowID first!", 
                    ephemeral=True
                )
                return
            
            modal = BuyModal(self.bot)
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"Error in buy callback: {e}")
            await self._safe_interaction_response(
                interaction,
                content="❌ An error occurred",
                ephemeral=True
            )

    @discord.ui.button(
        label="Set GrowID",
        emoji="🔑",
        style=discord.ButtonStyle.secondary,
        custom_id="set_growid:1"
    )
    async def button_set_growid_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_cooldown(interaction) or not await self._check_interaction_lock(interaction):
            return

        try:
            modal = SetGrowIDModal(self.bot)
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"Error in set growid callback: {e}")
            await self._safe_interaction_response(
                interaction,
                content="❌ An error occurred",
                ephemeral=True
            )

    @discord.ui.button(
        label="Check GrowID",
        emoji="🔍",
        style=discord.ButtonStyle.secondary,
        custom_id="check_growid:1"
    )
    async def button_check_growid_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_cooldown(interaction) or not await self._check_interaction_lock(interaction):
            return

        try:
            if not hasattr(self, 'balance_manager'):
                self.logger.error("BalanceManagerService not initialized")
                await self._safe_interaction_response(
                    interaction,
                    content="❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            
            growid = await self.balance_manager.get_growid(interaction.user.id)
            if not growid:
                await interaction.followup.send("❌ You haven't set your GrowID yet!", ephemeral=True)
                return

            embed = discord.Embed(
                title="🔍 GrowID Information",
                description=f"Your registered GrowID: `{growid}`",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in check growid callback: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)

    @discord.ui.button(
        label="World",
        emoji="🌍",
        style=discord.ButtonStyle.secondary,
        custom_id="world:1"
    )
    async def button_world_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_cooldown(interaction) or not await self._check_interaction_lock(interaction):
            return

        try:
            if not hasattr(self, 'product_manager'):
                self.logger.error("ProductManagerService not initialized")
                await self._safe_interaction_response(
                    interaction,
                    content="❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            
            world_info = await self.product_manager.get_world_info()
            if not world_info:
                await interaction.followup.send("❌ World information not available.", ephemeral=True)
                return

            embed = discord.Embed(
                title="🌍 World Information",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="World", value=f"`{world_info['world']}`", inline=True)
            if world_info.get('owner'):
                embed.add_field(name="Owner", value=f"`{world_info['owner']}`", inline=True)
            if world_info.get('bot'):
                embed.add_field(name="Bot", value=f"`{world_info['bot']}`", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in world callback: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)