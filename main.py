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
    version="1.2.0" # Version updated for robustness
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

# --- NEW: More Robust Scraping Logic with Fallbacks & Better Logging ---
def scrape_amazon_product(driver, query: str):
    driver.get(f"https://www.amazon.in/s?k={query.replace(' ', '+')}")
    wait = WebDriverWait(driver, 15) # Increased wait time
    
    try:
        # --- Find and click the first product link ---
        print("Searching for product link...")
        first_product_link = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div[data-component-type='s-search-result'] h2 a")
        ))
        product_url = first_product_link.get_attribute('href')
        driver.get(product_url)
        print(f"Navigated to product page: {product_url}")

        # --- Scrape Name ---
        name = ""
        try:
            print("Finding product name...")
            name = wait.until(EC.presence_of_element_located((By.ID, "productTitle"))).text.strip()
            print(f"Found name: {name}")
        except TimeoutException:
            print("ERROR: Could not find product name by ID 'productTitle'.")
            return None

        # --- Scrape Price (with fallbacks) ---
        price = 0
        try:
            print("Finding product price...")
            price_str = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.a-price-whole"))).text.replace(',', '').strip()
            price = int(price_str)
            print(f"Found price: {price}")
        except TimeoutException:
            print("ERROR: Could not find price with 'span.a-price-whole'.")
            # Fallback for different price structures if needed
            return None # Fail for now if price is not found

        # --- Scrape Image (with fallbacks) ---
        image_url = ""
        try:
            print("Finding product image...")
            # This selector checks for two common image element IDs
            image_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#landingImage, #imgBlkFront")))
            image_url = image_element.get_attribute('src')
            print(f"Found image URL: {image_url}")
        except TimeoutException:
            print("ERROR: Could not find image with selectors '#landingImage, #imgBlkFront'.")
            return None # Fail for now if image is not found
        
        return {"name": name, "price": price, "image": image_url}

    except Exception as e:
        print(f"A critical error occurred during the scraping process: {e}")
        # Save a screenshot for debugging if something goes wrong
        driver.save_screenshot("debug_screenshot.png")
        return None

# --- API Endpoint (No changes needed here) ---
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

