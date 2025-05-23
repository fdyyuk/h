import logging
import asyncio
from datetime import datetime
import discord
from ext.balance_manager import BalanceManagerService
from ext.product_manager import ProductManagerService

logger = logging.getLogger(__name__)

class ButtonHandler:
    def __init__(self, bot):
        self.bot = bot
        self._handled_interactions = set()
        self._locks = {}
        
        try:
            self.balance_manager = BalanceManagerService(bot)
            self.product_manager = ProductManagerService(bot)
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            raise

    async def handle_button(self, interaction: discord.Interaction):
        """Handle button interactions"""
        if interaction.id in self._handled_interactions:
            logger.debug(f"Skipping already handled interaction: {interaction.id}")
            return
            
        try:
            async with asyncio.timeout(5.0):  # 5 detik timeout
                self._handled_interactions.add(interaction.id)
                button_id = interaction.data.get('custom_id', '')

                # Fungsi helper untuk mengirim respons dengan aman
                async def safe_response(content=None, **kwargs):
                    try:
                        # Tambahkan delay kecil untuk menghindari race condition
                        await asyncio.sleep(0.1)
                        
                        if interaction.is_expired():
                            logger.debug(f"Interaction {interaction.id} has expired")
                            return False

                        try:
                            if not interaction.response.is_done():
                                if content:
                                    await interaction.response.send_message(content, **kwargs)
                                    return True
                                return False
                            else:
                                if content:
                                    await interaction.followup.send(content, **kwargs)
                                    return True
                                return False
                        except discord.errors.InteractionResponded:
                            try:
                                if content:
                                    await interaction.followup.send(content, **kwargs)
                                    return True
                            except Exception as e:
                                logger.error(f"Error sending followup: {e}")
                                return False
                                
                    except Exception as e:
                        logger.error(f"Error in safe_response: {e}")
                        return False

                # Handle setiap button berdasarkan ID
                if button_id == 'balance':
                    success = await self.handle_balance(interaction)
                    if not success and not interaction.response.is_done():
                        await safe_response("❌ Failed to get balance", ephemeral=True)
                        
                elif button_id == 'buy':
                    if not hasattr(self, 'product_manager'):
                        logger.error("ProductManagerService not initialized")
                        await safe_response("❌ Service temporarily unavailable", ephemeral=True)
                        return
                    await safe_response("Buy feature coming soon!", ephemeral=True)
                    
                elif button_id == 'set_growid':
                    try:
                        from test.ext.live_modals import SetGrowIDModal
                        modal = SetGrowIDModal(self.bot)
                        if not interaction.response.is_done():
                            await interaction.response.send_modal(modal)
                    except Exception as e:
                        logger.error(f"Error showing SetGrowID modal: {e}")
                        await safe_response("❌ Failed to show SetGrowID modal", ephemeral=True)
                        
                elif button_id == 'check_growid':
                    success = await self.handle_check_growid(interaction)
                    if not success and not interaction.response.is_done():
                        await safe_response("❌ Failed to check GrowID", ephemeral=True)
                        
                elif button_id == 'world':
                    if not hasattr(self, 'product_manager'):
                        logger.error("ProductManagerService not initialized")
                        await safe_response("❌ Service temporarily unavailable", ephemeral=True)
                        return
                    await safe_response("World feature coming soon!", ephemeral=True)
                    
                else:
                    await safe_response("❌ Unknown button interaction", ephemeral=True)

        except asyncio.TimeoutError:
            logger.error("Button handler timeout")
            if not interaction.response.is_done():
                await safe_response("❌ Operation timed out", ephemeral=True)
        except Exception as e:
            logger.error(f"Error handling button {button_id}: {e}")
            if not interaction.response.is_done():
                await safe_response("❌ An error occurred", ephemeral=True)
        finally:
            self._clean_old_interactions()
            
    async def handle_balance(self, interaction: discord.Interaction) -> bool:
        try:
            if not hasattr(self, 'balance_manager'):
                logger.error("BalanceManagerService not initialized")
                await interaction.response.send_message(
                    "❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return False

            user_id = interaction.user.id
            growid = await self.balance_manager.get_growid(user_id)
            
            if not growid:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ You haven't set your GrowID yet! Use the Set GrowID button first.",
                        ephemeral=True
                    )
                return True
                
            balance = await self.balance_manager.get_balance(growid)
            if balance:
                embed = discord.Embed(
                    title="💰 Balance Information",
                    color=discord.Color.gold()
                )
                embed.add_field(name="GrowID", value=growid, inline=False)
                embed.add_field(name="Balance", value=balance.format(), inline=False)
                embed.set_footer(text=f"Today at {datetime.now().strftime('%I:%M %p')}")
                
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error in handle_balance: {e}")
            return False
            
    async def handle_check_growid(self, interaction: discord.Interaction) -> bool:
        try:
            if not hasattr(self, 'balance_manager'):
                logger.error("BalanceManagerService not initialized")
                await interaction.response.send_message(
                    "❌ Service temporarily unavailable",
                    ephemeral=True
                )
                return False

            user_id = interaction.user.id
            growid = await self.balance_manager.get_growid(user_id)
            
            if not growid:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ You haven't set your GrowID yet! Use the Set GrowID button first.",
                        ephemeral=True
                    )
                return True
                
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Your current GrowID is: **{growid}**",
                    ephemeral=True
                )
            return True
            
        except Exception as e:
            logger.error(f"Error in handle_check_growid: {e}")
            return False

    def _clean_old_interactions(self):
        """Bersihkan interaksi yang sudah lama (>5 menit)"""
        try:
            now = datetime.utcnow().timestamp()
            to_remove = {
                interaction_id for interaction_id in self._handled_interactions
                if now - int(str(interaction_id)[:19]) / 1000000 >= 300
            }
            self._handled_interactions -= to_remove
        except Exception as e:
            logger.error(f"Error cleaning old interactions: {e}")