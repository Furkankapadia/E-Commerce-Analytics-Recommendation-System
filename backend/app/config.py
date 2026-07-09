import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_PATHS = {
    "orders": BASE_DIR / "olist_orders_dataset.csv",
    "order_items": BASE_DIR / "olist_order_items_dataset.csv",
    "products": BASE_DIR / "olist_products_dataset.csv",
    "customers": BASE_DIR / "olist_customers_dataset.csv",
    "payments": BASE_DIR / "olist_order_payments_dataset.csv",
    "translation": BASE_DIR / "product_category_name_translation.csv",
    "reviews": BASE_DIR / "olist_order_reviews_dataset.csv",
    "sellers": BASE_DIR / "olist_sellers_dataset.csv",
    "geolocation": BASE_DIR / "olist_geolocation_dataset.csv"
}

# API configuration
HOST = "127.0.0.1"
PORT = 8000
