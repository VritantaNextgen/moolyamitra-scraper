import boto3
from fastapi import FastAPI, HTTPException, Body
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pydantic import BaseModel
import time

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MoolyaMitra Scraping API",
    description="An API to scrape product data from e-commerce sites and save it to DynamoDB.",
    version="1.3.0" # Version updated for advanced scraping
)

# --- Pydantic Models for Request Body ---
class ScrapeRequest(BaseModel):
    product_query: str
    category: str
    productID: str
    site: str

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

# --- NEW: Helper function to find elements with multiple fallback selectors ---
def find_element_with_fallbacks(driver, wait, selectors):
    """Tries a list of selectors in order and returns the first element found."""
    for selector_type, selector_value in selectors:
        try:
            element = wait.until(EC.presence_of_element_located((selector_type, selector_value)))
            print(f"  [Success] Found element with selector: {selector_value}")
            return element
        except TimeoutException:
            print(f"  [Info] Could not find element with selector: {selector_value}. Trying next...")
    print("  [Error] Exhausted all fallback selectors. Element not found.")
    return None

# --- NEW: Heavily revised scraping logic with fallbacks and better logging ---
def scrape_amazon_product(driver, query: str):
    driver.get(f"https://www.amazon.in/s?k={query.replace(' ', '+')}")
    wait = WebDriverWait(driver, 15)
    
    # --- CAPTCHA Check ---
    if "api-services.ge" in driver.current_url or "captcha" in driver.page_source.lower():
        print("[CRITICAL ERROR] Amazon is showing a CAPTCHA. Scraping cannot proceed.")
        return None

    try:
        # --- Find and click the first product link ---
        print("Searching for product link...")
        search_result_selectors = [
            (By.CSS_SELECTOR, "div[data-component-type='s-search-result'] h2 a"),
            (By.CSS_SELECTOR, ".s-result-item .a-link-normal.a-text-normal") # Fallback selector
        ]
        first_product_link = find_element_with_fallbacks(driver, wait, search_result_selectors)
        
        if not first_product_link:
            print("ERROR: Could not find the first product link in search results.")
            return None
            
        product_url = first_product_link.get_attribute('href')
        if not product_url.startswith("http"):
            product_url = "https://www.amazon.in" + product_url
        driver.get(product_url)
        print(f"Navigated to product page: {product_url}")

        # --- Scrape Name ---
        print("\nFinding product name...")
        name_selectors = [(By.ID, "productTitle"), (By.CSS_SELECTOR, "h1.a-size-large.a-spacing-none")]
        name_element = find_element_with_fallbacks(driver, wait, name_selectors)
        if not name_element: return None
        name = name_element.text.strip()
        print(f"Found name: {name}")

        # --- Scrape Price ---
        print("\nFinding product price...")
        price_selectors = [(By.CSS_SELECTOR, "span.a-price-whole"), (By.CSS_SELECTOR, ".priceToPay span.a-offscreen")]
        price_element = find_element_with_fallbacks(driver, wait, price_selectors)
        if not price_element: return None
        price_str = price_element.get_attribute("textContent").replace('₹', '').replace(',', '').strip()
        price = int(float(price_str))
        print(f"Found price: {price}")
        
        # --- Scrape Image ---
        print("\nFinding product image...")
        image_selectors = [(By.ID, "landingImage"), (By.ID, "imgBlkFront"), (By.CSS_SELECTOR, ".imgTagWrapper img")]
        image_element = find_element_with_fallbacks(driver, wait, image_selectors)
        if not image_element: return None
        image_url = image_element.get_attribute('src')
        print(f"Found image URL: {image_url}")
        
        return {"name": name, "price": price, "image": image_url}

    except Exception as e:
        print(f"A critical error occurred during the scraping process: {e}")
        driver.save_screenshot("debug_screenshot.png")
        return None

# --- API Endpoint ---
@app.post("/scrape-and-save")
def scrape_and_save(request: ScrapeRequest):
    driver = get_driver()
    scraped_data = None
    try:
        if request.site.lower() == "amazon":
            scraped_data = scrape_amazon_product(driver, request.product_query)
        else:
             raise HTTPException(status_code=400, detail=f"Scraping for site '{request.site}' is not supported.")

        if not scraped_data:
            raise HTTPException(status_code=404, detail=f"Could not find product details for '{request.product_query}' on Amazon.")

        item_to_save = {
            "category": request.category,
            "productID": request.productID,
            "name": scraped_data["name"],
            "description": f"Scraped data for '{request.product_query}'.",
            "image": scraped_data["image"],
            "prices": {
                "Amazon": scraped_data["price"]
            },
            "tags": [request.category, "Scraped", "Trending"]
        }

        try:
            dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
            table = dynamodb.Table('MoolyaMitra-Products')
            table.put_item(Item=item_to_save)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save data to DynamoDB: {str(e)}")

        return {
            "status": "success",
            "message": f"Successfully scraped and saved '{scraped_data['name']}'",
            "data": item_to_save
        }

    finally:
        driver.quit()

