import os
import io
import discord
from discord.ext import commands
from dotenv import load_dotenv
import law

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

description = "Retrieve Japanese law text"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', description=description, intents=intents)

@bot.group()
async def jplaw(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Invalid subcommand.')

@jplaw.command(name='treesync')
async def treesync(ctx):
    guild = discord.Object(GUILD_ID)
    await bot.tree.sync(guild=guild)
    await ctx.send('treesync')


@jplaw.command()
async def title(ctx, law_title: str):
    """Search Japanese law"""
    results = await law.title(law_title)
    with io.StringIO() as table:
        #print("|law_num|law_revision_id|law_title|", file=table)
        #print("|:------|:--------------|:--------|", file=table)
        for l in results[:5]:
            print(f"* {l['law_title']}", file=table)
            print(f"  * {l['law_num']}", file=table)
            print(f"  * {l['law_revision_id']}", file=table)
            #print(f"* |{l['law_num']}|{l['law_revision_id']}|{l['law_title']}|", file=table)
        await ctx.send(table.getvalue())

@jplaw.command()
async def text(ctx, law_id_or_num_or_revision_id: str):
    """Retrieve law text"""
    results = await law.text(law_id_or_num_or_revision_id)
    await ctx.send('\n'.join(results[:10]))

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
