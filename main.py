import boto3
import requests
import gzip
import xml.etree.ElementTree as ET
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pydantic import BaseModel
import time
import re

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MoolyaMitra Scraping API",
    description="An API to discover product URLs from sitemaps and scrape their data into DynamoDB.",
    version="2.1.0" # Version updated for robust sitemap fetching
)

# --- Pydantic Models for Request Body ---
class SitemapScrapeRequest(BaseModel):
    site: str # e.g., "amazon"

# --- Selenium WebDriver Setup ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# --- Helper function to find elements with multiple fallback selectors ---
def find_element_with_fallbacks(driver, wait, selectors):
    for selector_type, selector_value in selectors:
        try:
            element = wait.until(EC.presence_of_element_located((selector_type, selector_value)))
            print(f"  [Success] Found element with selector: {selector_value}")
            return element
        except TimeoutException:
            print(f"  [Info] Could not find element with selector: {selector_value}. Trying next...")
    print("  [Error] Exhausted all fallback selectors. Element not found.")
    return None

# --- UPDATED: Functions to parse robots.txt and XML Sitemaps with User-Agent ---
def get_sitemap_urls_from_robots(site_url: str):
    """Fetches and parses robots.txt to find sitemap URLs."""
    print(f"Fetching robots.txt from {site_url}/robots.txt")
    try:
        # ADDED User-Agent header to mimic a real browser
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(f"{site_url}/robots.txt", headers=headers)
        response.raise_for_status()
        sitemap_urls = re.findall(r'Sitemap:\s*(.*)', response.text)
        print(f"Found {len(sitemap_urls)} sitemap(s) in robots.txt")
        return sitemap_urls
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Could not fetch robots.txt: {e}")
        return []

def get_product_urls_from_sitemap(sitemap_url: str):
    """Downloads a sitemap (handling .gz) and extracts product URLs."""
    print(f"Processing sitemap: {sitemap_url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(sitemap_url, headers=headers)
        response.raise_for_status()

        content = gzip.decompress(response.content) if sitemap_url.endswith('.gz') else response.content
        root = ET.fromstring(content)
        
        namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [url.text for url in root.findall('s:url/s:loc', namespace)]
        print(f"Extracted {len(urls)} URLs from {sitemap_url}")
        return urls
    except Exception as e:
        print(f"ERROR: Failed to process sitemap {sitemap_url}: {e}")
        return []

# --- Scrapes a specific product page URL (no changes needed here) ---
def scrape_amazon_product_page(driver, product_url: str):
    driver.get(product_url)
    wait = WebDriverWait(driver, 15)
    
    if "api-services.ge" in driver.current_url or "captcha" in driver.page_source.lower():
        print("[CRITICAL ERROR] Amazon is showing a CAPTCHA. Scraping cannot proceed for this URL.")
        return None

    try:
        print(f"Navigated to product page: {product_url}")
        name_selectors = [(By.ID, "productTitle"), (By.CSS_SELECTOR, "h1.a-size-large.a-spacing-none")]
        name_element = find_element_with_fallbacks(driver, wait, name_selectors)
        if not name_element: return None
        name = name_element.text.strip()

        price_selectors = [(By.CSS_SELECTOR, "span.a-price-whole"), (By.CSS_SELECTOR, ".priceToPay span.a-offscreen")]
        price_element = find_element_with_fallbacks(driver, wait, price_selectors)
        if not price_element: return None
        price_str = price_element.get_attribute("textContent").replace('₹', '').replace(',', '').strip()
        price = int(float(price_str))
        
        image_selectors = [(By.ID, "landingImage"), (By.ID, "imgBlkFront"), (By.CSS_SELECTOR, ".imgTagWrapper img")]
        image_element = find_element_with_fallbacks(driver, wait, image_selectors)
        if not image_element: return None
        image_url = image_element.get_attribute('src')
        
        asin_match = re.search(r'/(dp|gp/product)/([A-Z0-9]{10})', product_url)
        product_id = asin_match.group(2) if asin_match else "UNKNOWN"
        category = "Electronics" 

        return {"name": name, "price": price, "image": image_url, "productID": product_id, "category": category}

    except Exception as e:
        print(f"A critical error occurred while scraping {product_url}: {e}")
        return None

# --- Background task for the entire scraping job (Updated to be smarter) ---
def sitemap_scraping_task(site: str):
    print(f"\n--- Starting background sitemap scrape for {site} ---")
    site_map = {"amazon": "https://www.amazon.in"}
    base_url = site_map.get(site.lower())
    
    if not base_url:
        print(f"Site '{site}' not supported.")
        return

    all_sitemaps = get_sitemap_urls_from_robots(base_url)
    if not all_sitemaps:
        print("No sitemaps found. Exiting.")
        return
        
    # --- NEW: Intelligently select a product sitemap ---
    product_sitemap = None
    for sitemap in all_sitemaps:
        if 'sitemap_dp' in sitemap: # 'dp' usually means "detail page"
            product_sitemap = sitemap
            break
            
    if not product_sitemap:
        print("Could not find a specific product sitemap. Using the first one found.")
        product_sitemap = all_sitemaps[0]

    driver = get_driver()
    dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
    table = dynamodb.Table('MoolyaMitra-Products')
    
    try:
        product_urls = get_product_urls_from_sitemap(product_sitemap)
        
        for url in product_urls[:5]: # Scrape first 5 products for testing
            print(f"\n--- Scraping URL: {url} ---")
            scraped_data = scrape_amazon_product_page(driver, url)
            
            if scraped_data:
                item_to_save = {
                    "category": scraped_data["category"],
                    "productID": scraped_data["productID"],
                    "name": scraped_data["name"],
                    "description": f"Scraped data for product {scraped_data['productID']}.",
                    "image": scraped_data["image"],
                    "prices": {"Amazon": scraped_data["price"]},
                    "tags": [scraped_data["category"], "Scraped", "Sitemap"]
                }
                try:
                    table.put_item(Item=item_to_save)
                    print(f"  [SUCCESS] Saved item {item_to_save['productID']} to DynamoDB.")
                except Exception as e:
                    print(f"  [ERROR] Failed to save item {item_to_save['productID']} to DynamoDB: {e}")
            
            time.sleep(2)

    finally:
        driver.quit()
        print("\n--- Background sitemap scrape finished ---")

# --- API Endpoint to trigger the background task ---
@app.post("/start-sitemap-scrape")
def start_sitemap_scrape(request: SitemapScrapeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(sitemap_scraping_task, request.site)
    return {
        "status": "success",
        "message": f"Accepted. A background scraping job has been started for '{request.site}'. This may take a long time."
    }

