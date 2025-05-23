import discord
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ButtonHandler:
    def __init__(self, bot):
        self.bot = bot
        self._handled_interactions = set()
        
    async def handle_button(self, interaction: discord.Interaction):
        """Handle button interactions"""
        # Skip jika interaksi sudah diproses
        if interaction.id in self._handled_interactions:
            return
            
        try:
            # Tandai interaksi sudah diproses
            self._handled_interactions.add(interaction.id)
            
            # Dapatkan custom ID button
            button_id = interaction.data.get('custom_id', '')
            
            if button_id == 'balance':
                if not interaction.response.is_done():
                    await self.handle_balance(interaction)
            elif button_id == 'buy':
                if not interaction.response.is_done():
                    await self.handle_buy(interaction)
            elif button_id == 'set_growid':
                if not interaction.response.is_done():
                    await self.handle_set_growid(interaction)
            elif button_id == 'check_growid':
                if not interaction.response.is_done():
                    await self.handle_check_growid(interaction)
            elif button_id == 'world':
                if not interaction.response.is_done():
                    await self.handle_world(interaction)
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Unknown button interaction", 
                        ephemeral=True
                    )
                
        except Exception as e:
            logger.error(f"Error handling button {button_id}: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while processing the button!", 
                    ephemeral=True
                )
            
        try:
            # Bersihkan interaksi yang sudah lama dengan cara yang lebih aman
            self._clean_old_interactions()
        except Exception as e:
            logger.error(f"Error cleaning old interactions: {e}")
    
    def _clean_old_interactions(self):
        """Bersihkan interaksi yang sudah lama (>5 menit)"""
        try:
            now = datetime.utcnow().timestamp()
            to_remove = set()
            
            for interaction_id in self._handled_interactions:
                try:
                    # Konversi interaction_id ke timestamp dengan cara yang lebih aman
                    created_at = int(str(interaction_id)[:19]) / 1000000
                    if now - created_at >= 300:  # 5 menit
                        to_remove.add(interaction_id)
                except (ValueError, IndexError):
                    # Jika ada error saat parsing ID, tambahkan ke list yang akan dihapus
                    to_remove.add(interaction_id)
                    
            # Hapus interaksi yang sudah lama
            self._handled_interactions -= to_remove
            
        except Exception as e:
            logger.error(f"Error in _clean_old_interactions: {e}")
    
    async def handle_balance(self, interaction: discord.Interaction):
        try:
            # Get user's GrowID and balance
            user_id = interaction.user.id
            
            # Get balance from database using your service
            from ext.balance_manager import BalanceManagerService
            balance_service = BalanceManagerService()
            growid = await balance_service.get_growid(user_id)
            
            if not growid:
                await interaction.response.send_message(
                    "❌ You haven't set your GrowID yet! Use the Set GrowID button first.", 
                    ephemeral=True
                )
                return
                
            # Get balance (implement your logic here)
            balance = "200 WL"  # Example
            
            embed = discord.Embed(
                title="💰 Balance Information",
                color=discord.Color.gold()
            )
            embed.add_field(name="GrowID", value=growid, inline=False)
            embed.add_field(name="Balance", value=balance, inline=False)
            embed.set_footer(text=f"Today at {datetime.now().strftime('%I:%M %p')}")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in handle_balance: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Failed to get balance information", 
                    ephemeral=True
                )
    
    async def handle_buy(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Buy feature coming soon!", 
            ephemeral=True
        )
        
    async def handle_set_growid(self, interaction: discord.Interaction):
        # Implement your set GrowID logic here
        modal = discord.ui.Modal(title="Set GrowID")
        growid_input = discord.ui.TextInput(
            label="Enter your GrowID",
            placeholder="YourGrowID",
            min_length=1,
            max_length=30
        )
        modal.add_item(growid_input)
        
        await interaction.response.send_modal(modal)
        
    async def handle_check_growid(self, interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            
            # Get GrowID from database using your service
            from ext.balance_manager import BalanceManagerService
            balance_service = BalanceManagerService()
            growid = await balance_service.get_growid(user_id)
            
            if not growid:
                await interaction.response.send_message(
                    "❌ You haven't set your GrowID yet! Use the Set GrowID button first.",
                    ephemeral=True
                )
                return
                
            await interaction.response.send_message(
                f"Your current GrowID is: **{growid}**",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in handle_check_growid: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Failed to check GrowID",
                    ephemeral=True
                )
    
    async def handle_world(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "World feature coming soon!",
            ephemeral=True
        )