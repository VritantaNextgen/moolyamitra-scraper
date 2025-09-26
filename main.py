from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict
import boto3 # AWS SDK for Python
import time
import os

# Selenium imports for web automation
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# --- 1. Define Data Models ---
class ScrapeRequest(BaseModel):
    product_query: str = Field(..., description="The search term for the product, e.g., 'Prestige Iris Mixer Grinder'")
    category: str = Field(..., description="The category for the product, e.g., 'Home & Kitchen'")
    productID: str = Field(..., description="A unique ID for the product, e.g., 'HK005'")

# --- 2. Initialize FastAPI & DynamoDB ---
app = FastAPI(
    title="MoolyaMitra Scraping API",
    description="An API to scrape product data and save it to DynamoDB.",
    version="1.1.0"
)

# Initialize DynamoDB client. It will automatically use the permissions
# from the AWS environment it's running in (App Runner).
# Make sure your App Runner instance has an IAM role with DynamoDB write permissions.
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1') # Ensure this is your AWS region
table = dynamodb.Table('MoolyaMitra-Products') 

# --- 3. Scraping Function ---
def scrape_amazon_product(product_name: str) -> dict:
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    scraped_data = { "name": "Not Found", "price": 0.0, "image_url": "N/A" }

    try:
        driver.get("https://www.amazon.in")
        time.sleep(2)
        search_box = driver.find_element(By.ID, "twotabsearchtextbox")
        search_box.send_keys(product_name)
        search_box.submit()
        time.sleep(3)

        # Find the first product result
        first_result = driver.find_element(By.CSS_SELECTOR, "div[data-component-type='s-search-result']")
        
        try:
            product_title_element = first_result.find_element(By.CSS_SELECTOR, "span.a-size-medium.a-color-base.a-text-normal")
            scraped_data["name"] = product_title_element.text
        except NoSuchElementException: pass

        try:
            price_element = first_result.find_element(By.CSS_SELECTOR, ".a-price-whole")
            scraped_data["price"] = float(price_element.text.replace(",", ""))
        except NoSuchElementException: pass
            
        try:
            image_element = first_result.find_element(By.CSS_SELECTOR, "img.s-image")
            scraped_data["image_url"] = image_element.get_attribute('src')
        except NoSuchElementException: pass

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
    finally:
        driver.quit()
        
    return scraped_data

# --- 4. API Endpoint ---
@app.post("/scrape-and-save")
async def scrape_and_save_product(request: ScrapeRequest):
    print(f"Starting scrape for: {request.product_query}...")
    scraped_info = scrape_amazon_product(request.product_query)
    print(f"Scraping finished. Data: {scraped_info}")
    
    if scraped_info["name"] == "Not Found":
        raise HTTPException(status_code=404, detail=f"Could not find product details for '{request.product_query}' on Amazon.")

    item_to_save = {
        'category': request.category,
        'productID': request.productID,
        'name': scraped_info['name'],
        'description': f"Scraped data for '{request.product_query}'.",
        'image': scraped_info['image_url'],
        'prices': {'Amazon': scraped_info['price']},
        'tags': [request.category, "Scraped", "Trending"]
    }

    try:
        table.put_item(Item=item_to_save)
        print(f"Successfully saved item {request.productID} to DynamoDB.")
        return {"status": "success", "message": f"Successfully scraped and saved '{scraped_info['name']}'", "data": item_to_save}
    except Exception as e:
        print(f"Error saving to DynamoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save item to database. Check App Runner logs and IAM permissions. Error: {str(e)}")

