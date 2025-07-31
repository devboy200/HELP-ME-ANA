import os
import discord
import time
import asyncio
import logging
import subprocess
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

def create_chrome_options():
    """Create Chrome options optimized for Railway deployment"""
    options = Options()
    
    # Essential headless options
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")
    
    # Performance optimizations
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=TranslateUI")
    options.add_argument("--disable-ipc-flooding-protection")
    
    # Anti-detection
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Set Chrome binary location
    chrome_binary = "/usr/bin/google-chrome"
    options.binary_location = chrome_binary
    
    return options

def setup_chromedriver():
    """Setup and verify ChromeDriver installation"""
    chromedriver_path = "/usr/local/bin/chromedriver"
    
    # Check if ChromeDriver exists
    if not os.path.exists(chromedriver_path):
        logger.error(f"❌ ChromeDriver not found at {chromedriver_path}")
        return None
    
    # Check if ChromeDriver is executable
    if not os.access(chromedriver_path, os.X_OK):
        logger.warning(f"⚠️ ChromeDriver not executable, attempting to fix...")
        try:
            os.chmod(chromedriver_path, 0o755)
            logger.info("✅ Made ChromeDriver executable")
        except Exception as e:
            logger.error(f"❌ Failed to make ChromeDriver executable: {e}")
            return None
    
    # Test ChromeDriver
    try:
        result = subprocess.run([chromedriver_path, "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"✅ ChromeDriver working: {result.stdout.strip()}")
            return chromedriver_path
        else:
            logger.error(f"❌ ChromeDriver test failed: {result.stderr}")
            return None
    except Exception as e:
        logger.error(f"❌ ChromeDriver test error: {e}")
        return None

def fetch_price():
    """Fetch ANA price from Nirvana Finance"""
    driver = None
    
    try:
        # Setup ChromeDriver
        chromedriver_path = setup_chromedriver()
        if not chromedriver_path:
            logger.error("❌ ChromeDriver setup failed")
            return None
        
        # Create Chrome options
        options = create_chrome_options()
        
        # Create service
        service = Service(executable_path=chromedriver_path)
        
        # Initialize WebDriver
        logger.info("🚀 Initializing Chrome WebDriver...")
        driver = webdriver.Chrome(service=service, options=options)
        
        # Set timeouts
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(10)
        
        logger.info("🌐 Navigating to Nirvana Finance...")
        driver.get("https://mainnet.nirvana.finance/mint")
        
        # Wait for page to load
        logger.info("⏳ Waiting for page to load...")
        wait = WebDriverWait(driver, 30)
        
        # Wait for the price element
        logger.info("🔍 Looking for price element...")
        try:
            element = wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, "DataPoint_dataPointValue__Bzf_E"))
            )
            
            # Additional wait for dynamic content
            time.sleep(3)
            
            # Get price text
            price_text = element.text
            logger.info(f"📝 Raw price text: '{price_text}'")
            
            if price_text:
                # Clean the price text
                cleaned_price = price_text.replace("USDC", "").replace("$", "").strip()
                if cleaned_price:
                    try:
                        # Validate it's a number
                        float(cleaned_price)
                        logger.info(f"💰 Successfully fetched price: {cleaned_price}")
                        return cleaned_price
                    except ValueError:
                        logger.warning(f"⚠️ Invalid price format: {cleaned_price}")
                        return None
                else:
                    logger.warning("⚠️ Price text empty after cleaning")
                    return None
            else:
                logger.warning("⚠️ No price text found")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to find price element: {e}")
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
        
        # Run price fetching in executor to avoid blocking
        loop = asyncio.get_event_loop()
        price = await loop.run_in_executor(None, fetch_price)
        
        if price:
            if price != last_price:
                logger.info(f"📈 Price changed from {last_price} to {price}")
                
                # Update bot status
                try:
                    await client.change_presence(activity=discord.Game(name=f"ANA: ${price}"))
                    logger.info(f"✅ Updated bot status to: ANA: ${price}")
                except Exception as e:
                    logger.error(f"❌ Failed to update bot status: {e}")
                
                # Update voice channel name
                channel = client.get_channel(VOICE_CHANNEL_ID)
                if channel and isinstance(channel, discord.VoiceChannel):
                    try:
                        new_name = f"ANA: ${price}"
                        await channel.edit(name=new_name)
                        logger.info(f"🔁 Updated channel name to: {new_name}")
                        last_price = price
                    except discord.Forbidden:
                        logger.error("❌ No permission to edit channel name")
                    except discord.HTTPException as e:
                        if "rate limited" in str(e).lower():
                            logger.warning("⚠️ Rate limited, will try again next cycle")
                        else:
                            logger.error(f"❌ Failed to edit channel: {e}")
                    except Exception as e:
                        logger.error(f"❌ Unexpected error editing channel: {e}")
                else:
                    logger.warning(f"⚠️ Channel {VOICE_CHANNEL_ID} not found or not a voice channel")
            else:
                logger.info(f"⏸️ Price unchanged: ${price}")
        else:
            logger.info("⏸️ Failed to fetch price")
            
    except Exception as e:
        logger.error(f"⚠️ Error in update cycle: {str(e)}")

@client.event
async def on_ready():
    """Bot startup event"""
    logger.info(f"✅ Logged in as {client.user}")
    logger.info(f"🎯 Monitoring channel ID: {VOICE_CHANNEL_ID}")
    logger.info(f"🏠 Connected to {len(client.guilds)} guild(s)")
    
    # Verify target channel
    channel = client.get_channel(VOICE_CHANNEL_ID)
    if channel:
        logger.info(f"🎤 Target channel found: '{channel.name}' in '{channel.guild.name}'")
        if isinstance(channel, discord.VoiceChannel):
            logger.info("✅ Channel is a voice channel - ready to update!")
        else:
            logger.warning("⚠️ Target channel is not a voice channel!")
    else:
        logger.error(f"❌ Channel {VOICE_CHANNEL_ID} not found! Check your VOICE_CHANNEL_ID")
    
    # Test price fetching once before starting loop
    logger.info("🧪 Testing price fetch...")
    test_price = await asyncio.get_event_loop().run_in_executor(None, fetch_price)
    if test_price:
        logger.info(f"✅ Test fetch successful: ${test_price}")
    else:
        logger.warning("⚠️ Test fetch failed - bot will continue trying")
    
    # Start the update loop
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

def main():
    """Main function to start the bot"""
    logger.info("🚀 Starting ANA Price Bot...")
    logger.info(f"🐍 Python version: {os.sys.version}")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    
    # Check environment variables
    logger.info("🔍 Checking environment variables...")
    if DISCORD_BOT_TOKEN:
        logger.info("✅ DISCORD_BOT_TOKEN is set")
    if VOICE_CHANNEL_ID:
        logger.info(f"✅ VOICE_CHANNEL_ID is set: {VOICE_CHANNEL_ID}")
    
    # Check system dependencies
    chrome_bin = "/usr/bin/google-chrome"
    chromedriver_path = "/usr/local/bin/chromedriver"
    
    logger.info(f"🔍 Chrome binary: {chrome_bin} (exists: {os.path.exists(chrome_bin)})")
    logger.info(f"🔍 ChromeDriver: {chromedriver_path} (exists: {os.path.exists(chromedriver_path)})")
    
    # Verify Chrome installation
    if os.path.exists(chrome_bin):
        try:
            result = subprocess.run([chrome_bin, "--version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"✅ Chrome version: {result.stdout.strip()}")
            else:
                logger.error(f"❌ Chrome test failed: {result.stderr}")
        except Exception as e:
            logger.error(f"❌ Chrome test error: {e}")
    
    # Test ChromeDriver
    chromedriver_working = setup_chromedriver()
    if chromedriver_working:
        logger.info("✅ ChromeDriver is ready")
    else:
        logger.error("❌ ChromeDriver setup failed - bot may not work properly")
    
    # Start the bot
    try:
        client.run(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main()
