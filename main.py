import boto3
from fastapi import FastAPI, HTTPException, Body
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pydantic import BaseModel

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MoolyaMitra Scraping API",
    description="An API to scrape product data from e-commerce sites and save it to DynamoDB.",
    version="1.1.0" # Version updated
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
    # Add a user-agent to appear more like a real browser
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# --- UPDATED Scraping Logic with more robust selectors ---
def scrape_amazon_product(driver, query: str):
    driver.get(f"https://www.amazon.in/s?k={query.replace(' ', '+')}")
    wait = WebDriverWait(driver, 10)
    
    try:
        # Wait for search results to be present and find the first product link
        first_product_link = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div[data-component-type='s-search-result'] h2 a")
        ))
        product_url = first_product_link.get_attribute('href')
        driver.get(product_url)

        # Scrape details from the product page using updated selectors
        name = wait.until(EC.presence_of_element_located((By.ID, "productTitle"))).text.strip()
        
        # This is a more robust way to find the price
        price_str = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.a-price-whole"))).text.replace(',', '').strip()
        price = int(price_str)
        
        # This is a more robust way to find the main image
        image_url = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#landingImage, #imgBlkFront"))).get_attribute('src')
        
        return {"name": name, "price": price, "image": image_url}

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
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

