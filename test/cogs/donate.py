import discord
from discord.ext import commands
from ext.balance_manager import BalanceManagerService
from database import get_connection

class Donate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.webhook_id and "GrowID:" in message.content and "Deposit:" in message.content:
            lines = message.content.splitlines()
            growid = None
            text_deposit = ""
            for line in lines:
                if "GrowID:" in line:
                    growid = line.split("GrowID:")[-1].strip()
                elif "Deposit:" in line:
                    text_deposit = line.split("Deposit:")[-1].strip()

            if growid and text_deposit:
                wl, dl, bgl = self.parse_currency_amount(text_deposit)
                total_wl = wl + dl * 100 + bgl * 1000

                discord_id = await self.get_discord_id_by_growid(growid)
                if discord_id:
                    balance_service = BalanceManagerService(self.bot)
                    await balance_service.add_balance(discord_id, total_wl)
                    log_channel = self.bot.get_channel(self.bot.config.get("donation_log_channel", 0))
                    if log_channel:
                        await log_channel.send(f"[AUTO-DONASI] {growid} (+{total_wl} WL) dari Deposit: {text_deposit}")
                else:
                    print(f"[AUTO-DONASI] Gagal: GrowID '{growid}' tidak terdaftar.")

    def parse_currency_amount(self, text: str):
        wl = dl = bgl = 0
        text = text.lower()
        parts = [p.strip() for p in text.split(",")]
        for part in parts:
            if "world lock" in part:
                wl += int("".join(filter(str.isdigit, part)))
            elif "diamond lock" in part:
                dl += int("".join(filter(str.isdigit, part)))
            elif "blue gem lock" in part:
                bgl += int("".join(filter(str.isdigit, part)))
        return wl, dl, bgl

    async def get_discord_id_by_growid(self, growid: str):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE growid = ?", (growid,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

def setup(bot):
    bot.add_cog(Donate(bot))