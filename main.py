import boto3
import re
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks
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

# --- Configuration for Different E-commerce Sites ---
# This is where you, as my teammate, will help by providing the XML paths (CSS selectors).
# I have pre-filled the ones for Amazon and Flipkart based on my analysis.
SITE_CONFIG = {
    "amazon": {
        "search_url": "https://www.amazon.in/s?k=",
        "selectors": {
            "search_result_link": "div[data-component-type='s-search-result'] h2 a",
            "name": "#productTitle",
            "price": "span.a-price-whole",
            "image": "#landingImage, #imgBlkFront"
        }
    },
    "flipkart": {
        "search_url": "https://www.flipkart.com/search?q=",
        "selectors": {
            "search_result_link": "._1fQZEK, ._4ddWXP a",
            "name": ".B_NuCI, ._35KyD6",
            "price": "._30jeq3._16Jk6d, ._1_WHN1",
            "image": "._396cs4._2amPTt._3qGmMb, ._2r_T1I"
        }
    }
}

# --- FastAPI App Initialization ---
app = FastAPI(
    title="MoolyaMitra Intelligent Scraping API",
    description="A modular, multi-site API to scrape product data and save it to DynamoDB.",
    version="3.0.0"
)

# --- Pydantic Models for API Request ---
class ScrapeRequest(BaseModel):
    product_query: str
    category: str
    productID: str
    site: str

# --- The Scraper Engine ---
class Scraper:
    def __init__(self, site: str):
        if site not in SITE_CONFIG:
            raise ValueError(f"Site '{site}' is not configured.")
        self.config = SITE_CONFIG[site]
        self.driver = self._get_driver()
        self.wait = WebDriverWait(self.driver, 15)

    def _get_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)

    def scrape(self, query: str):
        try:
            print(f"--- Starting scrape for '{query}' on {self.config['search_url']} ---")
            product_url = self._find_product_url(query)
            if not product_url:
                print("Could not find a valid product URL in search results.")
                return None
            
            return self._scrape_product_page(product_url)
        finally:
            self.driver.quit()

    def _find_product_url(self, query: str):
        search_url = f"{self.config['search_url']}{query.replace(' ', '+')}"
        self.driver.get(search_url)
        try:
            link_element = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, self.config['selectors']['search_result_link'])
            ))
            url = link_element.get_attribute('href')
            # Ensure the URL is absolute
            if not url.startswith("http"):
                base_url = "https://www.amazon.in" if "amazon" in self.config['search_url'] else "https://www.flipkart.com"
                url = base_url + url
            return url
        except TimeoutException:
            return None

    def _scrape_product_page(self, url: str):
        self.driver.get(url)
        try:
            name = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, self.config['selectors']['name']))).text.strip()
            price_raw = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, self.config['selectors']['price']))).get_attribute("textContent")
            image_url = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, self.config['selectors']['image']))).get_attribute('src')
            
            # Clean the price
            price_clean = re.sub(r'[₹,]', '', price_raw)
            price = int(float(price_clean))

            return {"name": name, "price": price, "image": image_url}
        except (TimeoutException, ValueError, AttributeError) as e:
            print(f"Failed to scrape details from {url}. Reason: {e}")
            return None

# --- Background Task & API Endpoint ---
def scrape_and_save_task(request: ScrapeRequest):
    """This function runs in the background to avoid timeouts."""
    print(f"Background task started for productID: {request.productID}")
    try:
        scraper = Scraper(request.site)
        scraped_data = scraper.scrape(request.product_query)

        if not scraped_data:
            print(f"Scraping failed for '{request.product_query}'.")
            return

        item_to_save = {
            "category": request.category,
            "productID": request.productID,
            "name": scraped_data["name"],
            "description": f"Data for '{scraped_data['name']}'.",
            "image": scraped_data["image"],
            "prices": {
                request.site.title(): scraped_data["price"]
            },
            "tags": [request.category, request.site.title()]
        }

        dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
        table = dynamodb.Table('MoolyaMitra-Products')
        table.put_item(Item=item_to_save)
        print(f"Successfully saved item {request.productID} to DynamoDB.")

    except Exception as e:
        print(f"A critical error occurred in the background task: {e}")

@app.post("/start-scrape-job")
def start_scrape_job(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Accepts a scrape request and starts it as a background job."""
    background_tasks.add_task(scrape_and_save_task, request)
    return {
        "status": "accepted",
        "message": f"Scraping job for '{request.product_query}' on {request.site} has been started in the background."
    }

