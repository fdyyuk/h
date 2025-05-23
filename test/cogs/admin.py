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
    


    @commands.command(name="reducebal")
    async def reduce_balance(self, ctx, growid: str, amount: int):
        """Reduce user's balance
        Usage: !reducebal <growid> <amount>
        Example: !reducebal STEVE 100000
        """
        if not await self._check_admin(ctx):
            return
                
        try:
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
            embed.add_field(name="New Balance", value=new_balance.format(), inline=False)
            embed.set_footer(text=f"Reduced by {ctx.author}")
    
            await ctx.send(embed=embed)
            self.logger.info(f"Balance reduced from {growid} by {ctx.author}: -{amount} WL")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Error reducing balance: {e}")
    
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
        
                # Get balance
                balance = await self.balance_service.get_balance(growid)
                if not balance:
                    await ctx.send(f"❌ No balance found for GrowID: {growid}")
                    return
        
                # Create embed
                embed = discord.Embed(
                    title="💰 Balance Information",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()  # Gunakan datetime.utcnow() untuk timestamp
                )
                
                embed.add_field(name="GrowID", value=growid, inline=False)
                embed.add_field(name="Balance", value=balance.format(), inline=False)
                embed.set_footer(text=f"Checked by {ctx.author}")
                
                await ctx.send(embed=embed)
        
            except Exception as e:
                self.logger.error(f"Error checking balance: {e}")
                await ctx.send("❌ An error occurred while checking balance!")
    
        @commands.command(name="resetuser")
        async def reset_user(self, ctx, growid: str):
            """Reset user balance"""
            if not await self._check_admin(ctx):
                return
    
            try:
                if not await self._confirm_action(ctx, f"Are you sure you want to reset {growid}'s balance?"):
                    await ctx.send("❌ Operation cancelled.")
                    return
    
                current_balance = await self.balance_service.get_balance(growid)  # Removed ()
                if not current_balance:
                    await ctx.send(f"❌ User {growid} not found!")
                    return
    
                # Reset balance
                new_balance = await self.balance_service.update_balance(
                    growid=growid,
                    wl=-current_balance.wl,
                    dl=-current_balance.dl,
                    bgl=-current_balance.bgl,
                    details=f"Balance reset by admin {ctx.author}",
                    transaction_type=TRANSACTION_ADMIN_RESET
                )
    
                embed = discord.Embed(
                    title="✅ Balance Reset",
                    description=f"User {growid}'s balance has been reset.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Previous Balance", value=current_balance.format(), inline=False)
                embed.add_field(name="New Balance", value=new_balance.format(), inline=False)
                embed.set_footer(text=f"Reset by {ctx.author}")
    
                await ctx.send(embed=embed)
                self.logger.info(f"Balance reset for {growid} by {ctx.author}")
                
            except Exception as e:
                await ctx.send(f"❌ Error: {str(e)}")
                self.logger.error(f"Error resetting user: {e}")

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