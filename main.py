import os
import discord
import time
import asyncio
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from discord.ext import tasks
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Fetch and validate environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
VOICE_CHANNEL_ID = os.getenv("VOICE_CHANNEL_ID")

if not DISCORD_BOT_TOKEN:
    raise ValueError("❌ DISCORD_BOT_TOKEN is not set in environment variables.")
if not VOICE_CHANNEL_ID:
    raise ValueError("❌ VOICE_CHANNEL_ID is not set in environment variables.")

try:
    VOICE_CHANNEL_ID = int(VOICE_CHANNEL_ID)
except ValueError:
    raise ValueError("❌ VOICE_CHANNEL_ID must be a valid integer.")

# Setup Discord client
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
client = discord.Client(intents=intents)

last_price = None

def setup_chrome_driver():
    """Setup Chrome driver with Railway-compatible options"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # For Railway deployment
    chrome_bin = os.getenv("GOOGLE_CHROME_BIN")
    if chrome_bin:
        options.binary_location = chrome_bin
    
    return options

def fetch_price():
    """Fetch ANA price from Nirvana Finance"""
    options = setup_chrome_driver()
    
    try:
        # Try to use Railway's Chrome path first, then fallback to local
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)
        
        logger.info("🌐 Fetching ANA price...")
        driver.get("https://mainnet.nirvana.finance/mint")
        
        # Wait for price element to load
        wait = WebDriverWait(driver, 20)
        element = wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "DataPoint_dataPointValue__Bzf_E"))
        )
        
        # FIXED: Use time.sleep instead of await asyncio.sleep
        time.sleep(3)
        
        price_text = element.text.replace("USDC", "").replace("$", "").strip()
        logger.info(f"💰 Fetched price: {price_text}")
        
        return price_text
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch price: {e}")
        return None
    finally:
        try:
            driver.quit()
        except:
            pass

@tasks.loop(seconds=60)
async def update_bot_status():
    """Update bot status and channel name every 60 seconds"""
    global last_price
    
    if not client.is_ready():
        return
    
    try:
        # Run price fetching in executor to avoid blocking
        loop = asyncio.get_event_loop()
        price = await loop.run_in_executor(None, fetch_price)
        
        if price and price != last_price:
            # Update bot status
            await client.change_presence(activity=discord.Game(name=f"ANA: ${price}"))
            
            # Update voice channel name
            channel = client.get_channel(VOICE_CHANNEL_ID)
            if isinstance(channel, discord.VoiceChannel):
                await channel.edit(name=f"ANA: ${price}")
                logger.info(f"🔁 Updated channel name to ANA: ${price}")
                last_price = price
            else:
                logger.warning("⚠️ Voice channel not found or invalid.")
        else:
            logger.info("⏸️ No price change or failed fetch.")
            
    except Exception as e:
        logger.error(f"⚠️ Error updating status: {e}")

@client.event
async def on_ready():
    """Bot startup event"""
    logger.info(f"✅ Logged in as {client.user}")
    logger.info(f"🎯 Monitoring channel ID: {VOICE_CHANNEL_ID}")
    update_bot_status.start()

@client.event
async def on_disconnect():
    logger.warning("⚠️ Bot disconnected")

@client.event
async def on_resumed():
    logger.info("🔄 Reconnected to Discord")

if __name__ == "__main__":
    logger.info("🚀 Starting ANA Price Bot...")
    client.run(DISCORD_BOT_TOKEN)
