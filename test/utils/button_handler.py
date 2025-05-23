import logging
from datetime import datetime
import discord
from ext.balance_manager import BalanceManagerService

logger = logging.getLogger(__name__)

class ButtonHandler:
    def __init__(self, bot):
        self.bot = bot
        self._handled_interactions = set()
        self._locks = {}

    async def handle_button(self, interaction: discord.Interaction):
        """Handle button interactions"""
        # Skip jika interaksi sudah diproses
        if interaction.id in self._handled_interactions:
            logger.debug(f"Skipping already handled interaction: {interaction.id}")
            return
            
        try:
            # Tandai interaksi sudah diproses di awal
            self._handled_interactions.add(interaction.id)
            button_id = interaction.data.get('custom_id', '')

            # Fungsi helper untuk mengirim respons dengan aman
            async def safe_response(content=None, **kwargs):
                try:
                    # Cek apakah interaksi masih valid
                    if interaction.is_expired():
                        logger.debug(f"Interaction {interaction.id} has expired")
                        return False

                    if not interaction.response.is_done():
                        if content:
                            await interaction.response.send_message(content, **kwargs)
                            return True
                        return False
                    else:
                        # Hanya kirim followup jika benar-benar perlu
                        if content and not interaction.message:
                            await interaction.followup.send(content, **kwargs)
                        return False
                except discord.errors.InteractionResponded:
                    logger.debug(f"Interaction {interaction.id} already responded to")
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
                await safe_response("Buy feature coming soon!", ephemeral=True)
                
            elif button_id == 'set_growid':
                try:
                    from ext.live_modals import SetGrowIDModal
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
                await safe_response("World feature coming soon!", ephemeral=True)
                
            else:
                await safe_response("❌ Unknown button interaction", ephemeral=True)

        except Exception as e:
            logger.error(f"Error handling button {button_id}: {e}")
            if not interaction.response.is_done():
                await safe_response("❌ An error occurred", ephemeral=True)
            
    async def handle_balance(self, interaction: discord.Interaction) -> bool:
        try:
            user_id = interaction.user.id
            balance_service = BalanceManagerService(self.bot)
            growid = await balance_service.get_growid(user_id)
            
            if not growid:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ You haven't set your GrowID yet! Use the Set GrowID button first.",
                        ephemeral=True
                    )
                return True
                
            balance = await balance_service.get_balance(growid)
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
            user_id = interaction.user.id
            balance_service = BalanceManagerService(self.bot)
            growid = await balance_service.get_growid(user_id)
            
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