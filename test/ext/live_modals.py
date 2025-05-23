import discord
from discord import ui
import logging
from datetime import datetime

from .balance_manager import BalanceManagerService
from .product_manager import ProductManagerService
from .trx import TransactionManager

class BuyModal(ui.Modal, title="Buy Product"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.logger = logging.getLogger("BuyModal")
        self.balance_manager = BalanceManagerService(bot)
        self.product_manager = ProductManagerService(bot)
        self.trx_manager = TransactionManager(bot)

    code = ui.TextInput(
        label="Product Code",
        placeholder="Enter product code...",
        min_length=1,
        max_length=10,
        required=True
    )

    quantity = ui.TextInput(
        label="Quantity",
        placeholder="Enter quantity...",
        min_length=1,
        max_length=2,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
    
            # Get user's GrowID
            growid = await self.balance_manager.get_growid(interaction.user.id)
            if not growid:
                await interaction.followup.send("❌ Please set your GrowID first!", ephemeral=True)
                return
    
            # Validate product
            product = await self.product_manager.get_product(self.code.value)
            if not product:
                await interaction.followup.send("❌ Invalid product code!", ephemeral=True)
                return
    
            # Validate quantity
            try:
                quantity = int(self.quantity.value)
                if quantity <= 0:
                    raise ValueError()
            except ValueError:
                await interaction.followup.send("❌ Invalid quantity!", ephemeral=True)
                return
    
            # Process purchase
            try:
                result = await self.trx_manager.process_purchase(
                    growid=growid,
                    product_code=self.code.value,
                    quantity=quantity
                )
            except Exception as e:
                await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
                return
    
            embed = discord.Embed(
                title="✅ Purchase Successful",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Product", value=f"`{result['product_name']}`", inline=True)
            embed.add_field(name="Quantity", value=str(quantity), inline=True)
            embed.add_field(name="Total Price", value=f"{result['total_price']:,} WL", inline=True)
            embed.add_field(name="New Balance", value=f"{result['new_balance']:,} WL", inline=False)
    
            # Send purchase result via DM
            dm_sent = await self.trx_manager.send_purchase_result(
                user=interaction.user,
                items=result['items'],
                product_name=result['product_name']
            )
    
            if dm_sent:
                embed.add_field(
                    name="Purchase Details",
                    value="✉️ Check your DM for the detailed purchase result!",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Purchase Details",
                    value="⚠️ Could not send DM. Please enable DMs from server members to receive purchase details.",
                    inline=False
                )
    
            content_msg = "**Your Items:**\n"
            for item in result['items']:
                content_msg += f"```{item['content']}```\n"
    
            await interaction.followup.send(
                embed=embed,
                content=content_msg if not dm_sent else None,
                ephemeral=True
            )
    
        except Exception as e:
            self.logger.error(f"Error in BuyModal: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)

class SetGrowIDModal(ui.Modal, title="Set GrowID"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.logger = logging.getLogger("SetGrowIDModal")
        self.balance_manager = BalanceManagerService(bot)

    growid = ui.TextInput(
        label="GrowID",
        placeholder="Enter your GrowID...",
        min_length=3,
        max_length=20,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            if await self.balance_manager.register_user(interaction.user.id, self.growid.value):
                embed = discord.Embed(
                    title="✅ GrowID Set Successfully",
                    description=f"Your GrowID has been set to: `{self.growid.value}`",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                self.logger.info(f"Set GrowID for Discord user {interaction.user.id} to {self.growid.value}")
            else:
                await interaction.followup.send("❌ Failed to set GrowID", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error in SetGrowIDModal: {e}")
            await interaction.followup.send("❌ An error occurred", ephemeral=True)