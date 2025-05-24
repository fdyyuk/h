import discord
from discord.ext import commands
import logging
from datetime import datetime, timedelta
import json
import asyncio
from typing import Optional, List
import io
import psutil
import platform
import aiohttp
from database import get_connection

from ext.constants import (
    CURRENCY_RATES,
    TRANSACTION_ADMIN_ADD,
    TRANSACTION_ADMIN_REMOVE,
    TRANSACTION_ADMIN_RESET,
    MAX_STOCK_FILE_SIZE,
    VALID_STOCK_FORMATS
)
from ext.balance_manager import BalanceManagerService
from ext.product_manager import ProductManagerService
from ext.trx import TransactionManager

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("AdminCog")
        
        # Initialize services
        self.balance_service = BalanceManagerService(bot)
        self.product_service = ProductManagerService(bot)
        self.trx_manager = TransactionManager(bot)
        
        # Load admin configuration
        try:
            with open('config.json') as f:
                config = json.load(f)
                self.admin_id = int(config['admin_id'])
                self.logger.info(f"Admin ID loaded: {self.admin_id}")
        except Exception as e:
            self.logger.error(f"Failed to load admin_id: {e}")
            raise

    async def _check_admin(self, ctx) -> bool:
        """Check if user has admin permissions"""
        is_admin = ctx.author.id == self.admin_id
        if not is_admin:
            await ctx.send("❌ You don't have permission to use admin commands!")
            self.logger.warning(f"Unauthorized access attempt by {ctx.author} (ID: {ctx.author.id})")
        return is_admin

    async def _process_stock_file(self, attachment) -> List[str]:
        """Process uploaded stock file"""
        if attachment.size > MAX_STOCK_FILE_SIZE:
            raise ValueError(f"File too large! Maximum size is {MAX_STOCK_FILE_SIZE/1024:.0f}KB")
            
        file_ext = attachment.filename.split('.')[-1].lower()
        if file_ext not in VALID_STOCK_FORMATS:
            raise ValueError(f"Invalid file format! Supported formats: {', '.join(VALID_STOCK_FORMATS)}")
            
        content = await attachment.read()
        text = content.decode('utf-8').strip()
        
        items = [line.strip() for line in text.split('\n') if line.strip()]
        if not items:
            raise ValueError("No valid items found in file!")
            
        return items

    async def _confirm_action(self, ctx, message: str, timeout: int = 30) -> bool:
        """Get confirmation for dangerous actions"""
        confirm_msg = await ctx.send(
            f"⚠️ **WARNING**\n{message}\nReact with ✅ to confirm or ❌ to cancel."
        )
        
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        try:
            reaction, user = await self.bot.wait_for(
                'reaction_add',
                timeout=timeout,
                check=lambda r, u: u == ctx.author and str(r.emoji) in ['✅', '❌']
            )
            return str(reaction.emoji) == '✅'
        except asyncio.TimeoutError:
            await ctx.send("❌ Operation timed out!")
            return False

    @commands.command(name="adminhelp")
    async def admin_help(self, ctx):
        """Show admin commands"""
        if not await self._check_admin(ctx):
            return

        try:
            embed = discord.Embed(
                title="🛠️ Admin Commands",
                description="Available administrative commands",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            command_categories = {
                "Product Management": [
                    "`addproduct <code> <name> <price> [description]`\nAdd new product",
                    "`editproduct <code> <field> <value>`\nEdit product details",
                    "`deleteproduct <code>`\nDelete product",
                    "`addstock <code>`\nAdd stock with file attachment"
                ],
                "Balance Management": [
                    "`addbal <growid> <amount> <WL/DL/BGL>`\nAdd balance",
                    "`reducebal <growid> <amount> <WL/DL/BGL>`\nRemove balance",
                    "`checkbal <growid>`\nCheck balance",
                    "`resetuser <growid>`\nReset balance"
                ],
                "Transaction Management": [
                    "`trxhistory <growid> [limit]`\nView transactions",
                    "`stockhistory <code> [limit]`\nView stock history"
                ],
                "System Management": [
                    "`systeminfo`\nShow bot system information",
                    "`announcement <message>`\nSend announcement to all users",
                    "`maintenance <on/off>`\nToggle maintenance mode",
                    "`blacklist <add/remove> <growid>`\nManage blacklisted users",
                    "`backup`\nCreate database backup"
                ]
            }

            for category, commands in command_categories.items():
                embed.add_field(
                    name=f"📋 {category}",
                    value="\n\n".join(commands),
                    inline=False
                )

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("❌ Error showing admin help!")
            self.logger.error(f"Error in admin_help: {e}")

    @commands.command(name="addproduct")
    async def add_product(self, ctx, code: str, name: str, price: int, *, description: Optional[str] = None):
        """Add new product
        Usage: !addproduct <code> <nama> <harga> [deskripsi]
        Example: !addproduct dl1 DiamondLock 100000 Real DL
        """
        if not await self._check_admin(ctx):
            return
            
        try:
            # Validasi harga
            if price <= 0:
                await ctx.send("❌ Harga harus lebih dari 0!")
                return
                
            result = await self.product_service.create_product(
                code=code,
                name=name,
                price=price,
                description=description
            )
            
            embed = discord.Embed(
                title="✅ Produk Ditambahkan",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Kode", value=result['code'], inline=True)
            embed.add_field(name="Nama", value=result['name'], inline=True)
            embed.add_field(name="Harga", value=f"{result['price']:,} WLs", inline=True)
            if result['description']:
                embed.add_field(name="Deskripsi", value=result['description'], inline=False)
            
            await ctx.send(embed=embed)
            self.logger.info(f"Product {code} added by {ctx.author}")
            
        except ValueError:
            await ctx.send("❌ Format salah! Harga harus berupa angka!")
            self.logger.error(f"Invalid price format in add_product command by {ctx.author}")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error adding product: {e}")
        
    @commands.command(name="addstock")
    async def add_stock(self, ctx, code: str):
        """Add stock from file
        Usage: !addstock <code> + file attachment
        File format: Satu stock per baris
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            # Cek file attachment
            if not ctx.message.attachments:
                await ctx.send("❌ Mohon lampirkan file teks berisi stock!")
                return
    
            # Verifikasi produk ada
            product = await self.product_service.get_product(code)
            if not product:
                await ctx.send(f"❌ Produk dengan kode `{code}` tidak ditemukan!")
                return
            
            # Proses file stock
            attachment = ctx.message.attachments[0]
            
            # Cek ukuran file
            if attachment.size > 1024 * 1024:  # Max 1MB
                await ctx.send("❌ File terlalu besar! Maksimal 1MB")
                return
    
            # Cek ekstensi file
            if not attachment.filename.endswith('.txt'):
                await ctx.send("❌ File harus berformat .txt!")
                return
    
            # Baca konten file
            content = await attachment.read()
            text = content.decode('utf-8').strip()
            
            # Split per baris dan bersihkan
            items = [line.strip() for line in text.split('\n') if line.strip()]
            
            if not items:
                await ctx.send("❌ File kosong atau tidak ada stock valid!")
                return
    
            # Progress message
            progress_msg = await ctx.send(f"⏳ Menambahkan {len(items)} stock...")
            
            # Tambah stock dengan progress
            added = 0
            failed = 0
            
            for i, item in enumerate(items, 1):
                try:
                    await self.product_service.add_stock_item(code, item, str(ctx.author.id))
                    added += 1
                    
                    # Update progress setiap 10 item
                    if i % 10 == 0:
                        await progress_msg.edit(content=f"⏳ Progress: {i}/{len(items)} stock...")
                except Exception as e:
                    self.logger.error(f"Failed to add stock item {item}: {e}")
                    failed += 1
    
            # Hapus pesan progress
            await progress_msg.delete()
            
            # Kirim hasil
            embed = discord.Embed(
                title="✅ Stock Ditambahkan",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Produk", value=f"{product['name']} ({code})", inline=False)
            embed.add_field(name="Total Stock", value=len(items), inline=True)
            embed.add_field(name="Berhasil", value=added, inline=True)
            embed.add_field(name="Gagal", value=failed, inline=True)
            
            await ctx.send(embed=embed)
            self.logger.info(f"Stock added for {code} by {ctx.author}: {added} success, {failed} failed")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error adding stock: {e}")
    
    @commands.command(name="addbal")
    async def add_balance(self, ctx, growid: str, amount: int):
        """Add balance to user
        Usage: !addbal <growid> <amount>
        Example: !addbal STEVE 100000
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            # Validasi jumlah
            if amount <= 0:
                await ctx.send("❌ Jumlah harus lebih dari 0!")
                return
    
            # Update balance
            new_balance = await self.balance_service.update_balance(
                growid=growid,
                wl=amount,  # Langsung dalam WL
                details=f"Added by admin {ctx.author}",
                transaction_type=TRANSACTION_ADMIN_ADD
            )
    
            embed = discord.Embed(
                title="✅ Balance Ditambahkan",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="GrowID", value=growid, inline=True)
            embed.add_field(name="Ditambahkan", value=f"{amount:,} WL", inline=True)
            embed.add_field(name="Balance Baru", value=f"{new_balance:,} WL", inline=False)
            embed.set_footer(text=f"Added by {ctx.author}")
    
            await ctx.send(embed=embed)
            self.logger.info(f"Balance added for {growid} by {ctx.author}: +{amount} WL")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error adding balance: {e}")
    
    @commands.command(name='reducestock')
    async def reduce_stock(self, ctx, code: str, count: int):
        """
        Reduce stock for a product and send the removed stock to admin's DM
        
        Usage:
        !reducestock <code> <count>
        
        Example:
        !reducestock DL 5
        """
        if not await self._check_admin(ctx):
            return
            
        try:
            # Check if count is valid
            if count <= 0:
                raise ValueError("Count must be positive")
                
            # Get product info first
            product = await self.product_service.get_product(code)
            if not product:
                raise ValueError(f"Product {code} not found")
                
            # Send progress message
            progress_msg = await ctx.send("⏳ Processing...")
    
            # Get and reduce stock using product service
            try:
                # Get available stock items before reduction
                stock_items = await self.product_service.get_available_stock(code, count)
                if len(stock_items) < count:
                    raise ValueError(f"Not enough stock! Only {len(stock_items)} items available")
    
                # Reduce stock using service
                await self.product_service.reduce_stock(
                    product_code=code,
                    quantity=count,
                    admin_id=str(ctx.author.id),
                    reason="Manual reduction by admin"
                )
    
                # Create stock file
                stock_file = io.StringIO()
                current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                stock_file.write(f"Stock reduction for {product['name']} ({code})\n")
                stock_file.write(f"Date: {current_time} UTC\n")
                stock_file.write(f"Reduced by: {ctx.author}\n")
                stock_file.write("-" * 50 + "\n")
                for i, item in enumerate(stock_items, 1):
                    stock_file.write(f"{i}. {item['content']}\n")
                stock_file.seek(0)
    
                # Send file to admin's DM
                await ctx.author.send(
                    "Here are the removed stock items:",
                    file=discord.File(
                        fp=io.BytesIO(stock_file.getvalue().encode()),
                        filename=f"stock_reduction_{code}_{current_time.replace(' ', '_')}.txt"
                    )
                )
    
                # Get current stock count using service
                current_stock = await self.product_service.get_stock_count(code)
    
                # Create success embed
                embed = discord.Embed(
                    title="✅ Stock Reduced",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(
                    name="Product", 
                    value=f"{product['name']} ({code})", 
                    inline=False
                )
                embed.add_field(
                    name="Reduced Amount", 
                    value=str(count), 
                    inline=True
                )
                embed.add_field(
                    name="Remaining Stock", 
                    value=str(current_stock), 
                    inline=True
                )
                
                embed.set_footer(text=f"Reduced by {ctx.author}")
                
                # Delete progress message and send result
                await progress_msg.delete()
                await ctx.send(embed=embed)
                
                # Log using service
                await self.product_service.log_admin_action(
                    admin_id=str(ctx.author.id),
                    action='REDUCE_STOCK',
                    target=code,
                    details=f"Reduced {count} items from {product['name']}"
                )
                
                self.logger.info(f"Stock reduced for {code} by {ctx.author}: {count} items")
                
            except Exception as e:
                raise ValueError(str(e))
                    
        except ValueError as e:
            if 'progress_msg' in locals():
                await progress_msg.delete()
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error reducing stock: {e}")
            
        except Exception as e:
            if 'progress_msg' in locals():
                await progress_msg.delete()
            await ctx.send("❌ An unexpected error occurred")
            self.logger.error(f"Error reducing stock: {e}")
    
    @commands.command(name='checkbal')
    async def check_balance(self, ctx, growid: str = None):
        """Check balance dari user
        Usage: !checkbal <growid>
        Example: !checkbal STEVE
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            if not growid:
                await ctx.send("❌ Please specify a GrowID!")
                return
    
            # Get user data using balance service
            user_data = await self.balance_service.get_user_data(growid)
            if not user_data:
                await ctx.send(f"❌ No user found with GrowID: {growid}")
                return
    
            # Get balance using balance service
            balance = await self.balance_service.get_balance(growid)
            if not balance:
                await ctx.send(f"❌ No balance found for GrowID: {growid}")
                return
    
            # Create embed
            embed = discord.Embed(
                title="💰 Balance Information",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            # User info
            embed.add_field(
                name="GrowID", 
                value=growid, 
                inline=True
            )
            if user_data.get('discord_id'):
                embed.add_field(
                    name="Discord", 
                    value=f"<@{user_data['discord_id']}>", 
                    inline=True
                )
    
            # Balance info
            total_wls = (balance.wl + (balance.dl * 100) + (balance.bgl * 10000))
            balance_text = []
            if balance.bgl > 0:
                balance_text.append(f"{balance.bgl:,} BGL")
            if balance.dl > 0:
                balance_text.append(f"{balance.dl:,} DL")
            if balance.wl > 0:
                balance_text.append(f"{balance.wl:,} WL")
            
            embed.add_field(
                name="Balance", 
                value=f"{' + '.join(balance_text) if balance_text else '0 WL'}\nTotal: {total_wls:,} WL", 
                inline=False
            )
    
            # Get transaction stats using transaction manager
            stats = await self.trx_manager.get_user_stats(growid)
            if stats:
                stats_text = [
                    f"Total Transactions: {stats['total_trx']:,}",
                    f"Total Spent: {stats['total_spent']:,} WL" if stats['total_spent'] else "Total Spent: 0 WL",
                    f"Last Transaction: {stats['last_trx']}" if stats['last_trx'] else "No transactions yet"
                ]
                
                embed.add_field(
                    name="Stats", 
                    value="\n".join(stats_text), 
                    inline=False
                )
    
            # Get recent transactions using transaction manager
            transactions = await self.trx_manager.get_user_transactions(growid, 5)
            if transactions:
                trx_text = []
                for trx in transactions:
                    price_text = f"{trx['total_price']:,} WL" if trx['total_price'] else "N/A"
                    trx_text.append(
                        f"• {trx['created_at']} - {trx['type']}\n"
                        f"  Price: {price_text}\n"
                        f"  Details: {trx['details']}"
                    )
                
                embed.add_field(
                    name="Recent Transactions",
                    value="\n".join(trx_text),
                    inline=False
                )
    
            embed.set_footer(text=f"Checked by {ctx.author} • Account created: {user_data['created_at']}")
            
            await ctx.send(embed=embed)
    
        except Exception as e:
            self.logger.error(f"Error checking balance: {e}")
            await ctx.send(f"❌ Error checking balance: {str(e)}")
            
    @commands.command(name="changeprice")
    async def change_price(self, ctx, code: str, new_price: int):
        """Change product price
        Usage: !changeprice <code> <new_price>
        Example: !changeprice DL1 100000
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            # Verify product exists
            product = await self.product_service.get_product(code)
            if not product:
                await ctx.send(f"❌ Product with code `{code}` not found!")
                return
    
            # Validate price
            if new_price <= 0:
                await ctx.send("❌ Price must be positive!")
                return
    
            # Update price
            success = await self.product_service.update_product(code, {'price': new_price})
            if success:
                embed = discord.Embed(
                    title="✅ Price Updated",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Product", value=f"{product['name']} ({code})", inline=False)
                embed.add_field(name="Old Price", value=f"{product['price']:,} WL", inline=True)
                embed.add_field(name="New Price", value=f"{new_price:,} WL", inline=True)
                embed.set_footer(text=f"Updated by {ctx.author}")
                
                await ctx.send(embed=embed)
                self.logger.info(f"Product {code} price changed by {ctx.author}: {product['price']} -> {new_price}")
            else:
                await ctx.send(f"❌ Failed to update price for {code}")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error changing price: {e}")

    @commands.command(name="deleteproduct")
    async def delete_product(self, ctx, code: str):
        """Delete a product
        Usage: !deleteproduct <code>
        Example: !deleteproduct DL1
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            # Verify product exists
            product = await self.product_service.get_product(code)
            if not product:
                await ctx.send(f"❌ Product with code `{code}` not found!")
                return
    
            # Confirm deletion
            if not await self._confirm_action(ctx, f"Are you sure you want to delete product {code} ({product['name']})?"):
                await ctx.send("❌ Operation cancelled.")
                return
    
            # Delete product
            success = await self.product_service.delete_product(code)
            if success:
                embed = discord.Embed(
                    title="✅ Product Deleted",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Code", value=code, inline=True)
                embed.add_field(name="Name", value=product['name'], inline=True)
                embed.set_footer(text=f"Deleted by {ctx.author}")
                
                await ctx.send(embed=embed)
                self.logger.info(f"Product {code} deleted by {ctx.author}")
            else:
                await ctx.send(f"❌ Failed to delete product {code}")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error deleting product: {e}")

    @commands.command(name="reducebal")
    async def reduce_balance(self, ctx, growid: str, amount: int = None):
        """Reduce user's balance
        Usage: !reducebal <growid> <amount>
        Example: !reducebal STEVE 100000
        """
        if not await self._check_admin(ctx):
            return
                
        try:
            # Cek jika amount tidak diberikan
            if amount is None:
                await ctx.send("❌ Please specify the amount!\nUsage: !reducebal <growid> <amount>")
                return
    
            if amount <= 0:
                await ctx.send("❌ Amount must be positive!")
                return
    
            # Get current balance first
            current_balance = await self.balance_service.get_balance(growid)
            if not current_balance:
                await ctx.send(f"❌ User {growid} not found!")
                return
                
            # Make amount negative for reduction
            wls = -amount
                
            new_balance = await self.balance_service.update_balance(
                growid=growid,
                wl=wls,
                details=f"Reduced by admin {ctx.author}",
                transaction_type=TRANSACTION_ADMIN_REMOVE
            )
    
            embed = discord.Embed(
                title="✅ Balance Reduced",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="GrowID", value=growid, inline=True)
            embed.add_field(name="Reduced", value=f"{amount:,} WL", inline=True)
            embed.add_field(name="New Balance", value=f"{new_balance:,} WL", inline=False)
            embed.set_footer(text=f"Reduced by {ctx.author}")
    
            await ctx.send(embed=embed)
            self.logger.info(f"Balance reduced from {growid} by {ctx.author}: -{amount} WL")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error reducing balance: {e}")
        
    @commands.command(name="trxhistory")
    async def transaction_history(self, ctx, growid: str, limit: int = 10):
        """View transaction history for a user
        Usage: !trxhistory <growid> [limit]
        Example: !trxhistory STEVE 5
        """
        if not await self._check_admin(ctx):
            return
    
        try:
            # Get transaction history
            history = await self.trx_manager.get_user_transactions(growid, limit)
            if not history:
                await ctx.send(f"❌ No transactions found for {growid}")
                return
    
            embed = discord.Embed(
                title=f"📜 Transaction History - {growid}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
    
            for trx in history:
                value = (
                    f"Type: {trx['type']}\n"
                    f"Amount: {trx['amount']:,} WL\n"
                    f"Details: {trx['details']}\n"
                    f"Date: {trx['created_at']}"
                )
                embed.add_field(
                    name=f"Transaction #{trx['id']}", 
                    value=value, 
                    inline=False
                )
    
            embed.set_footer(text=f"Showing last {len(history)} transactions")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error getting transaction history: {e}")
        
    @commands.command(name="systeminfo")
    async def system_info(self, ctx):
        """Show bot system information"""
        if not await self._check_admin(ctx):
            return

        try:
            # Get system info
            cpu_usage = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Get bot info
            uptime = datetime.utcnow() - self.bot.startup_time
            
            embed = discord.Embed(
                title="🤖 Bot System Information",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            # System Stats
            sys_info = (
                f"OS: {platform.system()} {platform.release()}\n"
                f"CPU Usage: {cpu_usage}%\n"
                f"RAM: {memory.used/1024/1024/1024:.1f}GB/{memory.total/1024/1024/1024:.1f}GB ({memory.percent}%)\n"
                f"Disk: {disk.used/1024/1024/1024:.1f}GB/{disk.total/1024/1024/1024:.1f}GB ({disk.percent}%)"
            )
            embed.add_field(name="💻 System", value=sys_info, inline=False)
            
            # Bot Stats
            bot_stats = (
                f"Uptime: {str(uptime).split('.')[0]}\n"
                f"Latency: {round(self.bot.latency * 1000)}ms\n"
                f"Servers: {len(self.bot.guilds)}\n"
                f"Commands: {len(self.bot.commands)}"
            )
            embed.add_field(name="🤖 Bot", value=bot_stats, inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error getting system info: {e}")

    @commands.command(name="announcement")
    async def announcement(self, ctx, *, message: str):
        """Send announcement to all users"""
        if not await self._check_admin(ctx):
            return

        try:
            if not await self._confirm_action(ctx, "Are you sure you want to send this announcement to all users?"):
                await ctx.send("❌ Announcement cancelled.")
                return

            # Get all users from database
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT discord_id FROM user_growid")
                users = cursor.fetchall()
            finally:
                if conn:
                    conn.close()

            embed = discord.Embed(
                title="📢 Announcement",
                description=message,
                color=discord.Color.gold(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Sent by {ctx.author}")

            sent_count = 0
            failed_count = 0

            progress_msg = await ctx.send("⏳ Sending announcement...")

            for user_data in users:
                try:
                    user = await self.bot.fetch_user(int(user_data['discord_id']))
                    if user:
                        await user.send(embed=embed)
                        sent_count += 1
                        if sent_count % 10 == 0:
                            await progress_msg.edit(content=f"⏳ Sending... ({sent_count}/{len(users)})")
                except:
                    failed_count += 1

            await progress_msg.delete()
            
            result_embed = discord.Embed(
                title="✅ Announcement Sent",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            result_embed.add_field(name="Total Users", value=len(users), inline=True)
            result_embed.add_field(name="Sent Successfully", value=sent_count, inline=True)
            result_embed.add_field(name="Failed", value=failed_count, inline=True)
            
            await ctx.send(embed=result_embed)
            self.logger.info(f"Announcement sent by {ctx.author}: {sent_count} success, {failed_count} failed")
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error sending announcement: {e}")

    @commands.command(name="maintenance")
    async def maintenance(self, ctx, mode: str):
        """Toggle maintenance mode"""
        if not await self._check_admin(ctx):
            return

        try:
            mode = mode.lower()
            if mode not in ['on', 'off']:
                await ctx.send("❌ Please specify 'on' or 'off'")
                return

            # Update maintenance status in database
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
                    ("maintenance_mode", "1" if mode == "on" else "0")
                )
                conn.commit()
            finally:
                if conn:
                    conn.close()

            embed = discord.Embed(
                title="🔧 Maintenance Mode",
                description=f"Maintenance mode has been turned **{mode}**",  # Removed ()
                color=discord.Color.orange() if mode == "on" else discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Changed by {ctx.author}")
            
            await ctx.send(embed=embed)
            self.logger.info(f"Maintenance mode {mode} by {ctx.author}")

            if mode == "on":
                # Notify all online users
                for guild in self.bot.guilds:
                    for member in guild.members:
                        if not member.bot and member.status != discord.Status.offline:
                            try:
                                await member.send(
                                    "⚠️ The bot is entering maintenance mode. "
                                    "Some features may be unavailable. "
                                    "We'll notify you when service is restored."
                                )
                            except:
                                continue
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error toggling maintenance mode: {e}")

    @commands.command(name="blacklist")
    async def blacklist(self, ctx, action: str, growid: str):
        """Manage blacklisted users"""
        if not await self._check_admin(ctx):
            return

        try:
            action = action.lower()
            if action not in ['add', 'remove']:
                await ctx.send("❌ Please specify 'add' or 'remove'")
                return

            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                if action == "add":
                    # Check if user exists
                    cursor.execute("SELECT growid FROM users WHERE growid = ?", (growid,))  # Removed ()
                    if not cursor.fetchone():
                        await ctx.send(f"❌ User {growid} not found!")
                        return

                    # Add to blacklist
                    cursor.execute(
                        "INSERT OR REPLACE INTO blacklist (growid, added_by, added_at) VALUES (?, ?, ?)",
                        (growid, str(ctx.author.id), datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))  # Removed ()
                    )
                else:
                    # Remove from blacklist
                    cursor.execute(
                        "DELETE FROM blacklist WHERE growid = ?",
                        (growid,)  # Removed ()
                    )

                conn.commit()

                embed = discord.Embed(
                    title="⛔ Blacklist Updated",
                    description=f"User {growid} has been {'added to' if action == 'add' else 'removed from'} the blacklist.",  # Removed ()
                    color=discord.Color.red() if action == 'add' else discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Updated by {ctx.author}")
                
                await ctx.send(embed=embed)
                self.logger.info(f"User {growid} {action}ed to blacklist by {ctx.author}")
                
            finally:
                if conn:
                    conn.close()
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error updating blacklist: {e}")

    @commands.command(name="backup")
    async def backup(self, ctx):
        """Create database backup"""
        if not await self._check_admin(ctx):
            return

        try:
            # Create backup filename with timestamp
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"backup_{timestamp}.db"
            
            # Create backup
            conn = None
            try:
                conn = get_connection()
                # Create backup in memory
                backup_data = io.BytesIO()
                for line in conn.iterdump():
                    backup_data.write(f'{line}\n'.encode('utf-8'))
                backup_data.seek(0)
                
                # Send backup file
                await ctx.send(
                    "✅ Database backup created!",
                    file=discord.File(backup_data, filename=backup_filename)
                )
                self.logger.info(f"Database backup created by {ctx.author}")
                
            finally:
                if conn:
                    conn.close()
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error creating backup: {e}")

async def setup(bot):
    """Setup the Admin cog"""
    try:
        if not hasattr(bot, 'admin_cog_loaded'):
            await bot.add_cog(AdminCog(bot))
            bot.admin_cog_loaded = True
            logger.info(f'Admin cog loaded successfully at {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC')
    except Exception as e:
        logger.error(f"Failed to setup Admin cog: {e}")
        logger.exception("Detailed setup error:")
        raise