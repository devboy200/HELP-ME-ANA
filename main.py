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
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Set Chrome binary location - Railway compatible paths
    chrome_bin = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/google-chrome")
    options.binary_location = chrome_bin
    
    logger.info(f"🔧 Chrome binary location: {chrome_bin}")
    
    return options

def fetch_price():
    """Fetch ANA price from Nirvana Finance"""
    options = setup_chrome_driver()
    driver = None
    
    try:
        # Specify ChromeDriver path explicitly - Railway compatible
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
        logger.info(f"🔧 ChromeDriver path: {chromedriver_path}")
        
        # Check if ChromeDriver exists
        if not os.path.exists(chromedriver_path):
            logger.error(f"❌ ChromeDriver not found at {chromedriver_path}")
            return None
            
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        
        logger.info("🌐 Fetching ANA price from Nirvana Finance...")
        driver.get("https://mainnet.nirvana.finance/mint")
        
        # Wait for the page to load completely
        wait = WebDriverWait(driver, 30)
        
        # Wait for price element to be present and visible
        logger.info("⏳ Waiting for price element to load...")
        element = wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "DataPoint_dataPointValue__Bzf_E"))
        )
        
        # Additional wait for dynamic content
        time.sleep(5)
        
        # Get the price text
        price_text = element.text
        logger.info(f"📝 Raw price text: '{price_text}'")
        
        # Clean up the price text
        if price_text:
            cleaned_price = price_text.replace("USDC", "").replace("$", "").strip()
            if cleaned_price:
                logger.info(f"💰 Cleaned price: {cleaned_price}")
                return cleaned_price
            else:
                logger.warning("⚠️ Price text is empty after cleaning")
                return None
        else:
            logger.warning("⚠️ No price text found in element")
            return None
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch price: {str(e)}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("🔄 ChromeDriver closed successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error closing ChromeDriver: {e}")

@tasks.loop(seconds=60)
async def update_bot_status():
    """Update bot status and channel name every 60 seconds"""
    global last_price
    
    if not client.is_ready():
        logger.info("⏳ Bot not ready yet, skipping update...")
        return
    
    try:
        logger.info("🔄 Starting price update cycle...")
        
        # Run price fetching in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        price = await loop.run_in_executor(None, fetch_price)
        
        if price and price != last_price:
            logger.info(f"📈 Price changed from {last_price} to {price}")
            
            # Update bot status
            await client.change_presence(activity=discord.Game(name=f"ANA: ${price}"))
            logger.info(f"✅ Updated bot status to: ANA: ${price}")
            
            # Update voice channel name
            channel = client.get_channel(VOICE_CHANNEL_ID)
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.edit(name=f"ANA: ${price}")
                    logger.info(f"🔁 Updated channel name to: ANA: ${price}")
                    last_price = price
                except discord.Forbidden:
                    logger.error("❌ No permission to edit channel name")
                except discord.HTTPException as e:
                    logger.error(f"❌ Failed to edit channel: {e}")
            else:
                logger.warning(f"⚠️ Channel {VOICE_CHANNEL_ID} not found or is not a voice channel")
        elif price == last_price:
            logger.info(f"⏸️ Price unchanged: ${price}")
        else:
            logger.info("⏸️ Failed to fetch price or price is None")
            
    except Exception as e:
        logger.error(f"⚠️ Error in update cycle: {str(e)}")
        logger.error(f"⚠️ Error type: {type(e).__name__}")

@client.event
async def on_ready():
    """Bot startup event"""
    logger.info(f"✅ Logged in as {client.user}")
    logger.info(f"🎯 Monitoring channel ID: {VOICE_CHANNEL_ID}")
    logger.info(f"🏠 Connected to {len(client.guilds)} guild(s)")
    
    # Verify the target channel exists
    channel = client.get_channel(VOICE_CHANNEL_ID)
    if channel:
        logger.info(f"🎤 Target channel found: '{channel.name}' in '{channel.guild.name}'")
        if isinstance(channel, discord.VoiceChannel):
            logger.info("✅ Channel is a voice channel - ready to update!")
        else:
            logger.warning("⚠️ Target channel is not a voice channel!")
    else:
        logger.error(f"❌ Channel {VOICE_CHANNEL_ID} not found! Check your VOICE_CHANNEL_ID")
    
    # Start the price update loop
    logger.info("🚀 Starting price update loop...")
    update_bot_status.start()

@client.event
async def on_disconnect():
    logger.warning("⚠️ Bot disconnected from Discord")

@client.event
async def on_resumed():
    logger.info("🔄 Reconnected to Discord")

@client.event
async def on_error(event, *args, **kwargs):
    logger.error(f"❌ Discord error in {event}: {args}, {kwargs}")

if __name__ == "__main__":
    logger.info("🚀 Starting ANA Price Bot...")
    logger.info(f"🐍 Python version: {os.sys.version}")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    
    # Check environment variables
    logger.info("🔍 Checking environment variables...")
    if DISCORD_BOT_TOKEN:
        logger.info("✅ DISCORD_BOT_TOKEN is set")
    if VOICE_CHANNEL_ID:
        logger.info(f"✅ VOICE_CHANNEL_ID is set: {VOICE_CHANNEL_ID}")
    
    # Check Chrome/ChromeDriver paths
    chrome_bin = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/google-chrome")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
    
    logger.info(f"🔍 Chrome binary: {chrome_bin} (exists: {os.path.exists(chrome_bin)})")
    logger.info(f"🔍 ChromeDriver: {chromedriver_path} (exists: {os.path.exists(chromedriver_path)})")
    
    try:
        client.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise
