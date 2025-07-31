import os
import discord
import time
import asyncio
import logging
import subprocess
import requests
import zipfile
import stat
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

def find_chrome_binary():
    """Find Chrome/Chromium binary location"""
    possible_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/usr/bin/chrome",
        "/opt/google/chrome/google-chrome"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"✅ Found Chrome binary: {path}")
            return path
    
    logger.error("❌ No Chrome binary found")
    return None

def get_chrome_version(chrome_path):
    """Get Chrome version"""
    try:
        result = subprocess.run([chrome_path, "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"✅ Chrome version: {version}")
            # Extract major version number
            version_parts = version.split()[-1].split('.')
            major_version = version_parts[0] if version_parts else None
            return version, major_version
        else:
            logger.error(f"❌ Failed to get Chrome version: {result.stderr}")
            return None, None
    except Exception as e:
        logger.error(f"❌ Error getting Chrome version: {e}")
        return None, None

def download_chromedriver(major_version):
    """Download compatible ChromeDriver"""
    try:
        # ChromeDriver download directory
        driver_dir = "/tmp/chromedriver"
        driver_path = os.path.join(driver_dir, "chromedriver")
        
        # Check if already downloaded
        if os.path.exists(driver_path):
            logger.info(f"✅ ChromeDriver already exists at {driver_path}")
            return driver_path
        
        # Create directory
        os.makedirs(driver_dir, exist_ok=True)
        
        logger.info(f"📥 Downloading ChromeDriver for Chrome {major_version}...")
        
        # Get the latest ChromeDriver version for this Chrome version
        if int(major_version) >= 115:
            # For Chrome 115+, use the new API
            api_url = f"https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_{major_version}"
            try:
                response = requests.get(api_url, timeout=30)
                if response.status_code == 200:
                    driver_version = response.text.strip()
                    download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{driver_version}/linux64/chromedriver-linux64.zip"
                else:
                    raise Exception(f"API returned status {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ New API failed: {e}, trying fallback...")
                # Fallback to a known working version
                driver_version = "119.0.6045.105"
                download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{driver_version}/linux64/chromedriver-linux64.zip"
        else:
            # For older Chrome versions, use the old API
            api_url = f"https://chromedriver.storage.googleapis.com/LATEST_RELEASE_{major_version}"
            try:
                response = requests.get(api_url, timeout=30)
                if response.status_code == 200:
                    driver_version = response.text.strip()
                    download_url = f"https://chromedriver.storage.googleapis.com/{driver_version}/chromedriver_linux64.zip"
                else:
                    raise Exception(f"API returned status {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Failed to get ChromeDriver version: {e}")
                return None
        
        logger.info(f"📥 Downloading ChromeDriver {driver_version}...")
        
        # Download the zip file
        zip_path = os.path.join(driver_dir, "chromedriver.zip")
        response = requests.get(download_url, timeout=60)
        response.raise_for_status()
        
        with open(zip_path, 'wb') as f:
            f.write(response.content)
        
        logger.info("📂 Extracting ChromeDriver...")
        
        # Extract the zip file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(driver_dir)
        
        # Find the chromedriver executable
        for root, dirs, files in os.walk(driver_dir):
            for file in files:
                if file == "chromedriver":
                    extracted_path = os.path.join(root, file)
                    # Move to expected location
                    if extracted_path != driver_path:
                        os.rename(extracted_path, driver_path)
                    break
        
        # Make executable
        os.chmod(driver_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        
        # Clean up
        os.remove(zip_path)
        
        # Verify the driver works
        result = subprocess.run([driver_path, "--version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"✅ ChromeDriver downloaded successfully: {result.stdout.strip()}")
            return driver_path
        else:
            logger.error(f"❌ Downloaded ChromeDriver test failed: {result.stderr}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Failed to download ChromeDriver: {e}")
        return None

def setup_chromedriver():
    """Setup ChromeDriver with manual download"""
    try:
        # Find Chrome binary first
        chrome_binary = find_chrome_binary()
        if not chrome_binary:
            logger.error("❌ Chrome binary not found")
            return None, None
        
        # Get Chrome version
        chrome_version, major_version = get_chrome_version(chrome_binary)
        if not chrome_version or not major_version:
            logger.error("❌ Could not determine Chrome version")
            return None, None
        
        # Try system ChromeDriver first
        system_paths = [
            "/usr/bin/chromedriver",
            "/usr/local/bin/chromedriver",
            "/snap/bin/chromedriver"
        ]
        
        chromedriver_path = None
        for path in system_paths:
            if os.path.exists(path):
                # Test if it works with current Chrome
                try:
                    result = subprocess.run([path, "--version"], 
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        logger.info(f"✅ Found working system ChromeDriver: {path}")
                        chromedriver_path = path
                        break
                except Exception as e:
                    logger.warning(f"⚠️ System ChromeDriver at {path} failed test: {e}")
                    continue
        
        # If no working system driver, download one
        if not chromedriver_path:
            logger.info("📥 No working system ChromeDriver found, downloading...")
            chromedriver_path = download_chromedriver(major_version)
        
        if not chromedriver_path:
            logger.error("❌ Could not setup ChromeDriver")
            return None, None
        
        return chromedriver_path, chrome_binary
            
    except Exception as e:
        logger.error(f"❌ ChromeDriver setup error: {e}")
        return None, None

def create_chrome_options(chrome_binary):
    """Create Chrome options optimized for deployment"""
    options = Options()
    
    # Set binary location
    options.binary_location = chrome_binary
    
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
    options.add_argument("--memory-pressure-off")
    options.add_argument("--max_old_space_size=4096")
    
    # Additional stability options
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-dev-tools")
    options.add_argument("--single-process")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-in-process-stack-traces")
    options.add_argument("--log-level=3")
    
    # Anti-detection
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    return options

def fetch_price():
    """Fetch ANA price from Nirvana Finance"""
    driver = None
    
    try:
        # Setup ChromeDriver
        chromedriver_path, chrome_binary = setup_chromedriver()
        if not chromedriver_path or not chrome_binary:
            logger.error("❌ ChromeDriver setup failed")
            return None
        
        # Create Chrome options
        options = create_chrome_options(chrome_binary)
        
        # Create service
        service = Service(executable_path=chromedriver_path)
        
        # Initialize WebDriver
        logger.info("🚀 Initializing Chrome WebDriver...")
        driver = webdriver.Chrome(service=service, options=options)
        
        # Set timeouts
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(20)
        
        logger.info("🌐 Navigating to Nirvana Finance...")
        driver.get("https://mainnet.nirvana.finance/mint")
        
        # Wait for page to load
        logger.info("⏳ Waiting for page to load...")
        wait = WebDriverWait(driver, 60)
        
        # Multiple attempts to find price element
        price_selectors = [
            "DataPoint_dataPointValue__Bzf_E",
            "dataPointValue",
            "price-value",
            "price"
        ]
        
        logger.info("🔍 Looking for price element...")
        price_text = None
        
        for selector in price_selectors:
            try:
                logger.info(f"🔍 Trying selector: {selector}")
                element = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, selector))
                )
                
                # Additional wait for dynamic content
                time.sleep(8)
                
                # Get price text
                price_text = element.text
                logger.info(f"📝 Raw price text with selector '{selector}': '{price_text}'")
                
                if price_text and price_text.strip():
                    break
                    
            except Exception as e:
                logger.warning(f"⚠️ Selector '{selector}' failed: {e}")
                continue
        
        # Try CSS selectors as fallback
        if not price_text:
            css_selectors = [
                "span[data-testid='price']",
                ".price-value",
                "[class*='price']",
                "[class*='Price']",
                "[class*='dataPoint']",
                "[class*='DataPoint']"
            ]
            
            for selector in css_selectors:
                try:
                    logger.info(f"🔍 Trying CSS selector: {selector}")
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                    if element and element.text:
                        price_text = element.text
                        logger.info(f"📝 Found price with CSS selector '{selector}': '{price_text}'")
                        break
                except Exception as e:
                    logger.warning(f"⚠️ CSS selector '{selector}' failed: {e}")
                    continue
        
        # Process the price text
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
            logger.warning("⚠️ No price text found with any selector")
            # Take a screenshot for debugging
            try:
                screenshot_path = "/tmp/debug_screenshot.png"
                driver.save_screenshot(screenshot_path)
                logger.info(f"📸 Screenshot saved to {screenshot_path}")
                
                # Log page source snippet
                page_source = driver.page_source
                logger.info(f"📄 Page source length: {len(page_source)} characters")
                if "DataPoint" in page_source:
                    logger.info("✅ Found 'DataPoint' in page source")
                else:
                    logger.warning("⚠️ 'DataPoint' not found in page source")
                    
            except Exception as e:
                logger.warning(f"⚠️ Could not take screenshot: {e}")
            
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

@tasks.loop(seconds=120)  # Increased to 2 minutes to be more stable
async def update_bot_status():
    """Update bot status and channel name every 2 minutes"""
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
            logger.info("⏸️ Failed to fetch price, will retry next cycle")
            
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
    
    # Test Chrome setup before starting
    logger.info("🧪 Testing Chrome setup...")
    chrome_binary = find_chrome_binary()
    if chrome_binary:
        get_chrome_version(chrome_binary)
    
    # Test price fetching once before starting loop
    logger.info("🧪 Testing price fetch...")
    try:
        test_price = await asyncio.get_event_loop().run_in_executor(None, fetch_price)
        if test_price:
            logger.info(f"✅ Test fetch successful: ${test_price}")
        else:
            logger.warning("⚠️ Test fetch failed - bot will continue trying")
    except Exception as e:
        logger.error(f"❌ Test fetch error: {e}")
    
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
    
    # Check system setup
    chrome_binary = find_chrome_binary()
    if chrome_binary:
        logger.info("✅ Chrome binary found")
    else:
        logger.error("❌ Chrome binary not found - this will cause issues")
    
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
