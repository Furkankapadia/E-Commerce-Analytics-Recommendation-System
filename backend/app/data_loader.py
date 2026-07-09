import os
import pandas as pd
import numpy as np
from pathlib import Path
from .config import DATA_PATHS

class DataState:
    """
    In-memory cache for all loaded and processed DataFrames.
    """
    def __init__(self):
        self.orders = None
        self.order_items = None
        self.products = None
        self.customers = None
        self.payments = None
        self.translation = None
        self.reviews = None
        self.sellers = None
        self.geolocation = None
        
        # Joined DataFrames for quick analytics
        self.orders_customers = None
        self.sales_items = None
        self.product_sales = None

# Global state instance
state = DataState()

def load_all_data():
    """
    Loads and cleans all datasets, joining relevant ones and caching them in the global state.
    """
    print("Loading datasets into memory...")
    
    # 1. Load translation dictionary
    translation_path = DATA_PATHS["translation"]
    if os.path.exists(translation_path):
        translation_df = pd.read_csv(translation_path)
    else:
        # Fallback empty translation
        translation_df = pd.DataFrame(columns=["product_category_name", "product_category_name_english"])
    
    # Map the two missing categories manually
    extra_translations = pd.DataFrame([
        {"product_category_name": "pc_gamer", "product_category_name_english": "pc_gamer"},
        {"product_category_name": "portateis_cozinha_e_preparadores_de_alimentos", "product_category_name_english": "portable_kitchen_appliances"}
    ])
    
    # Concatenate translations and remove duplicates
    translation_df = pd.concat([translation_df, extra_translations], ignore_index=True)
    translation_df = translation_df.drop_duplicates(subset=["product_category_name"])
    state.translation = translation_df

    # 2. Load Customers
    state.customers = pd.read_csv(DATA_PATHS["customers"])

    # 3. Load Products and fill category nulls
    products_df = pd.read_csv(DATA_PATHS["products"])
    products_df["product_category_name"] = products_df["product_category_name"].fillna("unknown")
    state.products = products_df

    # 4. Load Orders and parse dates
    orders_df = pd.read_csv(DATA_PATHS["orders"])
    date_cols = [
        'order_purchase_timestamp',
        'order_approved_at',
        'order_delivered_carrier_date',
        'order_delivered_customer_date',
        'order_estimated_delivery_date'
    ]
    for col in date_cols:
        orders_df[col] = pd.to_datetime(orders_df[col], errors='coerce')
        
    # Replicate the notebook's median imputation for datetime nulls
    for col in ['order_approved_at', 'order_delivered_carrier_date', 'order_delivered_customer_date']:
        median_val = orders_df[col].median()
        orders_df[col] = orders_df[col].fillna(median_val)
        
    state.orders = orders_df

    # 5. Load Order Items
    state.order_items = pd.read_csv(DATA_PATHS["order_items"])

    # 6. Load Payments
    state.payments = pd.read_csv(DATA_PATHS["payments"])

    # 7. Load Reviews (Optional)
    if os.path.exists(DATA_PATHS["reviews"]):
        state.reviews = pd.read_csv(DATA_PATHS["reviews"])
    else:
        state.reviews = pd.DataFrame(columns=["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message", "review_creation_date", "review_answer_timestamp"])

    # 8. Load Sellers (Optional)
    if os.path.exists(DATA_PATHS["sellers"]):
        state.sellers = pd.read_csv(DATA_PATHS["sellers"])

    # 9. Load Geolocation (Optional)
    # We do not load the full 1M rows geolocation into memory automatically to save RAM unless requested
    
    # --- Create Joined Helper DataFrames ---
    # Merge Orders and Customers to map customer_unique_id to orders
    state.orders_customers = pd.merge(
        state.orders, 
        state.customers, 
        on="customer_id", 
        how="inner"
    )
    
    # Merge Order Items and Products with English category names
    products_translated = pd.merge(
        state.products, 
        state.translation, 
        on="product_category_name", 
        how="left"
    )
    products_translated["product_category_name_english"] = products_translated["product_category_name_english"].fillna("other")
    
    state.product_sales = pd.merge(
        state.order_items, 
        products_translated, 
        on="product_id", 
        how="inner"
    )

    # Merge Order Items with Orders
    state.sales_items = pd.merge(
        state.order_items, 
        state.orders, 
        on="order_id", 
        how="inner"
    )

    print("Datasets loaded and cached successfully!")
    return state

def get_data_state() -> DataState:
    """
    Returns the loaded data state. If it hasn't been loaded yet, loads it first.
    """
    if state.orders is None:
        load_all_data()
    return state
