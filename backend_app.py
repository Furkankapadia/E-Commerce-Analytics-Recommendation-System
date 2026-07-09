import os
import sys
import uvicorn
import numpy as np
import pandas as pd
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from collections import defaultdict
from sklearn.linear_model import LinearRegression
from fastapi import FastAPI, APIRouter, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ==========================================
# 1. CONFIGURATION & DATA PATHS
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_FILES = {
    "orders": os.path.join(BASE_DIR, "olist_orders_dataset.csv"),
    "order_items": os.path.join(BASE_DIR, "olist_order_items_dataset.csv"),
    "products": os.path.join(BASE_DIR, "olist_products_dataset.csv"),
    "customers": os.path.join(BASE_DIR, "olist_customers_dataset.csv"),
    "payments": os.path.join(BASE_DIR, "olist_order_payments_dataset.csv"),
    "translation": os.path.join(BASE_DIR, "product_category_name_translation.csv"),
    "reviews": os.path.join(BASE_DIR, "olist_order_reviews_dataset.csv"),
    "sellers": os.path.join(BASE_DIR, "olist_sellers_dataset.csv"),
    "geolocation": os.path.join(BASE_DIR, "olist_geolocation_dataset.csv")
}

# ==========================================
# 2. DATA INGESTION & CACHE STATE
# ==========================================
class DataState:
    def __init__(self):
        self.orders = None
        self.order_items = None
        self.products = None
        self.customers = None
        self.payments = None
        self.translation = None
        self.reviews = None
        self.sellers = None
        
        # Joined DataFrames for analytics
        self.orders_customers = None
        self.sales_items = None
        self.product_sales = None

# Global cache instance
state = DataState()

def load_all_data():
    """
    Reads, cleans, and translates the CSV datasets, caching them in memory.
    """
    print("Loading datasets into memory...")
    
    # 1. Product Category Translations
    if os.path.exists(DATA_FILES["translation"]):
        translation_df = pd.read_csv(DATA_FILES["translation"])
    else:
        translation_df = pd.DataFrame(columns=["product_category_name", "product_category_name_english"])
        
    # Append missing categories
    extra_translations = pd.DataFrame([
        {"product_category_name": "pc_gamer", "product_category_name_english": "pc_gamer"},
        {"product_category_name": "portateis_cozinha_e_preparadores_de_alimentos", "product_category_name_english": "portable_kitchen_appliances"}
    ])
    translation_df = pd.concat([translation_df, extra_translations], ignore_index=True)
    translation_df = translation_df.drop_duplicates(subset=["product_category_name"])
    state.translation = translation_df

    # 2. Customers
    state.customers = pd.read_csv(DATA_FILES["customers"])

    # 3. Products
    products_df = pd.read_csv(DATA_FILES["products"])
    products_df["product_category_name"] = products_df["product_category_name"].fillna("unknown")
    state.products = products_df

    # 4. Orders (with datetime conversion & median imputation from notebook)
    orders_df = pd.read_csv(DATA_FILES["orders"])
    date_cols = [
        'order_purchase_timestamp',
        'order_approved_at',
        'order_delivered_carrier_date',
        'order_delivered_customer_date',
        'order_estimated_delivery_date'
    ]
    for col in date_cols:
        orders_df[col] = pd.to_datetime(orders_df[col], errors='coerce')
        
    for col in ['order_approved_at', 'order_delivered_carrier_date', 'order_delivered_customer_date']:
        median_val = orders_df[col].median()
        orders_df[col] = orders_df[col].fillna(median_val)
    state.orders = orders_df

    # 5. Order Items
    state.order_items = pd.read_csv(DATA_FILES["order_items"])

    # 6. Payments
    state.payments = pd.read_csv(DATA_FILES["payments"])

    # 7. Reviews (Optional)
    if os.path.exists(DATA_FILES["reviews"]):
        state.reviews = pd.read_csv(DATA_FILES["reviews"])
    else:
        state.reviews = pd.DataFrame(columns=["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message", "review_creation_date", "review_answer_timestamp"])

    # 8. Sellers (Optional)
    if os.path.exists(DATA_FILES["sellers"]):
        state.sellers = pd.read_csv(DATA_FILES["sellers"])

    # --- Pre-Joined Helper DataFrames ---
    state.orders_customers = pd.merge(state.orders, state.customers, on="customer_id", how="inner")
    
    products_translated = pd.merge(state.products, state.translation, on="product_category_name", how="left")
    products_translated["product_category_name_english"] = products_translated["product_category_name_english"].fillna("other")
    state.product_sales = pd.merge(state.order_items, products_translated, on="product_id", how="inner")

    state.sales_items = pd.merge(state.order_items, state.orders, on="order_id", how="inner")
    
    print("All datasets loaded successfully!")

# ==========================================
# 3. CORE ANALYTICS BUSINESS LOGIC
# ==========================================
def calculate_sales_analytics():
    total_sales = float(state.order_items["price"].sum())
    total_freight = float(state.order_items["freight_value"].sum())
    gross_revenue = total_sales + total_freight
    
    total_orders = state.orders["order_id"].nunique()
    aov = gross_revenue / total_orders if total_orders > 0 else 0
    
    sales_merged = state.sales_items.copy()
    sales_merged["revenue"] = sales_merged["price"] + sales_merged["freight_value"]
    sales_merged["year_month"] = sales_merged["order_purchase_timestamp"].dt.to_period("M").astype(str)
    
    monthly_sales = sales_merged.groupby("year_month")["revenue"].sum().reset_index().sort_values("year_month")
    
    return {
        "gross_revenue": round(gross_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": round(aov, 2),
        "monthly_trend": monthly_sales.to_dict(orient="records")
    }

def calculate_customer_analytics():
    total_customers = state.customers["customer_unique_id"].nunique()
    
    cust_orders = state.orders_customers.groupby("customer_unique_id")["order_id"].nunique().reset_index()
    returning_count = int((cust_orders["order_id"] > 1).sum())
    new_count = total_customers - returning_count
    
    # RFM metrics
    df_rfm = pd.merge(state.orders_customers, state.order_items, on="order_id", how="inner")
    df_rfm["total_value"] = df_rfm["price"] + df_rfm["freight_value"]
    
    ref_date = state.orders["order_purchase_timestamp"].max() + pd.Timedelta(days=1)
    rfm = df_rfm.groupby("customer_unique_id").agg({
        "order_purchase_timestamp": lambda x: (ref_date - x.max()).days,
        "order_id": "nunique",
        "total_value": "sum"
    }).reset_index()
    rfm.columns = ["customer_unique_id", "recency", "frequency", "monetary"]
    
    # Quintiles segment scores
    rfm["R_score"] = pd.qcut(rfm["recency"], 5, labels=[5, 4, 3, 2, 1], duplicates='drop').astype(int)
    rfm["F_score"] = rfm["frequency"].apply(lambda f: 1 if f == 1 else (3 if f == 2 else 5))
    rfm["M_score"] = pd.qcut(rfm["monetary"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop').astype(int)
    
    def get_segment(row):
        r, f = row["R_score"], row["F_score"]
        if r >= 4 and f >= 4: return "Champions"
        if r >= 3 and f >= 3: return "Loyal Customers"
        if r >= 4 and f == 1: return "Recent/New Customers"
        if r <= 2 and f >= 3: return "At Risk"
        return "Hibernating/Lost"
        
    rfm["segment"] = rfm.apply(get_segment, axis=1)
    
    return {
        "total_customers": total_customers,
        "new_customers": new_count,
        "returning_customers": returning_count,
        "returning_percentage": round((returning_count / total_customers) * 100, 2) if total_customers > 0 else 0,
        "customer_segments": rfm["segment"].value_counts().to_dict(),
        "sample_rfm": rfm.head(20).to_dict(orient="records")
    }

def calculate_product_analytics():
    df_prod = state.product_sales.copy()
    df_prod["total_revenue"] = df_prod["price"] + df_prod["freight_value"]
    
    top_categories_units = (
        df_prod.groupby("product_category_name_english")["order_item_id"]
        .count().reset_index().rename(columns={"order_item_id": "units_sold"})
        .sort_values("units_sold", ascending=False).head(10)
        .to_dict(orient="records")
    )
    
    top_categories_rev = (
        df_prod.groupby("product_category_name_english")["total_revenue"]
        .sum().reset_index().rename(columns={"total_revenue": "revenue"})
        .sort_values("revenue", ascending=False).head(10)
    )
    top_categories_rev["revenue"] = top_categories_rev["revenue"].round(2)
    
    top_products_sold = (
        df_prod.groupby(["product_id", "product_category_name_english"])["order_item_id"]
        .count().reset_index().rename(columns={"order_item_id": "units_sold"})
        .sort_values("units_sold", ascending=False).head(10)
        .to_dict(orient="records")
    )
    
    return {
        "top_categories_by_units": top_categories_units,
        "top_categories_by_revenue": top_categories_rev.to_dict(orient="records"),
        "top_products_by_units": top_products_sold
    }

def calculate_payment_analytics():
    total_payment = float(state.payments["payment_value"].sum())
    avg_payment = float(state.payments["payment_value"].mean())
    
    payment_methods = (
        state.payments.groupby("payment_type")
        .agg(transactions_count=("payment_sequential", "count"), total_value=("payment_value", "sum"))
        .reset_index()
    )
    payment_methods["total_value"] = payment_methods["total_value"].round(2)
    
    installment_stats = (
        state.payments.groupby("payment_installments")["payment_value"]
        .count().reset_index().rename(columns={"payment_value": "count"})
        .sort_values("payment_installments").head(15)
        .to_dict(orient="records")
    )
    
    return {
        "total_payment_value": round(total_payment, 2),
        "average_payment_value": round(avg_payment, 2),
        "payment_methods": payment_methods.to_dict(orient="records"),
        "installment_distribution": installment_stats
    }

def calculate_review_analytics():
    if state.reviews.empty:
        return {"average_score": 0.0, "total_reviews": 0, "sentiment_ratio": {"positive": 0, "neutral": 0, "negative": 0}}
        
    avg_score = float(state.reviews["review_score"].mean())
    total_reviews = int(state.reviews["review_id"].nunique())
    
    ratings_count = state.reviews["review_score"].value_counts().to_dict()
    positive = ratings_count.get(5, 0) + ratings_count.get(4, 0)
    neutral = ratings_count.get(3, 0)
    negative = ratings_count.get(2, 0) + ratings_count.get(1, 0)
    
    return {
        "average_score": round(avg_score, 2),
        "total_reviews": total_reviews,
        "sentiment_ratio": {
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "positive_percentage": round((positive / total_reviews) * 100, 2) if total_reviews > 0 else 0
        },
        "score_distribution": {str(k): int(v) for k, v in ratings_count.items()}
    }

# ==========================================
# 4. CUSTOM APRIORI RECOMMENDATIONS ENGINE
# ==========================================
class AprioriRecommender:
    def __init__(self, min_support=0.00002, min_confidence=0.01):
        self.min_support = min_support
        self.min_confidence = min_confidence
        self.rules = []

    def train(self):
        df_prod_sales = state.product_sales.copy()
        print("Training Apriori Recommender: Extracting transaction baskets...")
        baskets = df_prod_sales.groupby("order_id")["product_category_name_english"].apply(set).tolist()
        total_transactions = len(baskets)
        
        if total_transactions == 0:
            print("Apriori Training failed: Empty dataset.")
            return
            
        # 1. 1-itemsets
        item_counts = defaultdict(int)
        for basket in baskets:
            for item in basket:
                item_counts[item] += 1
        freq_1 = {it: ct/total_transactions for it, ct in item_counts.items() if (ct/total_transactions) >= self.min_support}
        
        # 2. 2-itemsets
        pair_counts = defaultdict(int)
        for basket in baskets:
            freq_in_b = [it for it in basket if it in freq_1]
            n = len(freq_in_b)
            for i in range(n):
                for j in range(i+1, n):
                    pair = tuple(sorted((freq_in_b[i], freq_in_b[j])))
                    pair_counts[pair] += 1
        freq_2 = {pair: ct/total_transactions for pair, ct in pair_counts.items() if (ct/total_transactions) >= self.min_support}

        # 3. Mined Rules
        self.rules = []
        for pair, pair_supp in freq_2.items():
            it_a, it_b = pair
            
            # Rule A -> B
            conf_a_b = pair_supp / freq_1[it_a]
            lift_a_b = conf_a_b / freq_1[it_b]
            if conf_a_b >= self.min_confidence:
                self.rules.append({"antecedent": it_a, "consequent": it_b, "support": round(pair_supp, 5), "confidence": round(conf_a_b, 4), "lift": round(lift_a_b, 2)})
                
            # Rule B -> A
            conf_b_a = pair_supp / freq_1[it_b]
            lift_b_a = conf_b_a / freq_1[it_a]
            if conf_b_a >= self.min_confidence:
                self.rules.append({"antecedent": it_b, "consequent": it_a, "support": round(pair_supp, 5), "confidence": round(conf_b_a, 4), "lift": round(lift_b_a, 2)})
                
        self.rules = sorted(self.rules, key=lambda x: (x["lift"], x["confidence"]), reverse=True)
        print(f"Apriori: Mined {len(self.rules)} rules successfully.")

    def get_recommendations(self, category_name: str, limit=5):
        if not self.rules:
            self.train()
        
        recs = []
        for r in self.rules:
            if r["antecedent"].lower() == category_name.lower():
                recs.append({
                    "recommended_category": r["consequent"],
                    "confidence": r["confidence"],
                    "lift": r["lift"],
                    "support": r["support"],
                    "type": "association_rule"
                })
                if len(recs) >= limit:
                    break
                    
        # Bestseller fallback if no rules trigger
        if not recs:
            try:
                top_cats = calculate_product_analytics()["top_categories_by_units"]
                for cat in top_cats:
                    name = cat["product_category_name_english"]
                    if name.lower() != category_name.lower():
                        recs.append({
                            "recommended_category": name,
                            "confidence": 0.0,
                            "lift": 0.0,
                            "support": 0.0,
                            "type": "bestseller_fallback"
                        })
                        if len(recs) >= limit: break
            except Exception as e:
                print(f"Fallback recommendations error: {e}")
        return recs

recommender = AprioriRecommender()

# ==========================================
# 5. SALES FORECASTING SERVICES
# ==========================================
def calculate_sales_forecast():
    df_sales = state.sales_items.copy()
    df_sales["revenue"] = df_sales["price"] + df_sales["freight_value"]
    df_sales["year_month"] = df_sales["order_purchase_timestamp"].dt.to_period("M")
    
    monthly_series = df_sales.groupby("year_month")["revenue"].sum().reset_index().sort_values("year_month")
    
    # Active range filtering
    monthly_series = monthly_series[
        (monthly_series["year_month"] >= "2017-01") & 
        (monthly_series["year_month"] <= "2018-08")
    ].reset_index(drop=True)
    
    n_months = len(monthly_series)
    if n_months < 3:
        return {"historical": [], "forecast": [], "next_month_forecast": 0.0, "next_quarter_forecast": 0.0, "growth_trend": "No Data"}
        
    monthly_series["time_index"] = np.arange(1, n_months + 1)
    monthly_series["month_of_year"] = monthly_series["year_month"].dt.month
    
    month_dummies = pd.get_dummies(monthly_series["month_of_year"], prefix="month", drop_first=True)
    X = pd.concat([monthly_series[["time_index"]], month_dummies], axis=1)
    
    for m in range(2, 13):
        col = f"month_{m}"
        if col not in X.columns: X[col] = 0
            
    X = X.reindex(sorted(X.columns), axis=1)
    y = monthly_series["revenue"]
    
    model = LinearRegression()
    model.fit(X, y)
    
    monthly_series["fitted"] = model.predict(X)
    
    # Predict next quarter
    last_idx = n_months
    last_period = monthly_series["year_month"].max()
    
    future_rows = []
    for step in range(1, 4):
        p = last_period + step
        t_idx = last_idx + step
        m = p.month
        feat = {"time_index": t_idx}
        for month_val in range(2, 13):
            feat[f"month_{month_val}"] = 1 if m == month_val else 0
        future_rows.append((p, feat))
        
    future_df = pd.DataFrame([fr[1] for fr in future_rows]).reindex(sorted(X.columns), axis=1)
    future_preds = np.clip(model.predict(future_df), 0, None)
    
    forecasts = [{"year_month": str(future_rows[i][0]), "predicted_revenue": round(float(future_preds[i]), 2)} for i in range(3)]
    
    historical = []
    for _, row in monthly_series.iterrows():
        historical.append({
            "year_month": str(row["year_month"]),
            "actual_revenue": round(float(row["revenue"]), 2),
            "fitted_revenue": round(float(row["fitted"]), 2)
        })
        
    slope = model.coef_[X.columns.get_loc("time_index")]
    
    return {
        "historical": historical,
        "forecast": forecasts,
        "next_month_forecast": forecasts[0]["predicted_revenue"],
        "next_quarter_forecast": sum(f["predicted_revenue"] for f in forecasts),
        "growth_trend": "Upward" if slope > 0 else "Downward"
    }

# ==========================================
# 6. FASTAPI WEB SERVER APIS
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    print("=== Launching Consolidated E-Commerce Backend ===")
    try:
        load_all_data()
        recommender.train()
        print("=== Startup Load Complete ===")
    except Exception as e:
        print(f"CRITICAL startup error: {e}")
    yield
    print("=== Closing Server ===")

app = FastAPI(
    title="E-Commerce Analytics API Server", 
    description="Unified API endpoints for Sales, Customers (RFM), Products, Payments, Reviews, Apriori Recommendations, and Sales Forecasting.",
    lifespan=lifespan
)

# CORS support for frontend dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "server": "online",
        "api_documentation": "/docs",
        "message": "Send requests to /api/endpoints"
    }

# Endpoint Routers
@app.get("/api/sales/")
def get_sales():
    return calculate_sales_analytics()

@app.get("/api/customers/")
def get_customers():
    return calculate_customer_analytics()

@app.get("/api/products/")
def get_products():
    return calculate_product_analytics()

@app.get("/api/payments/")
def get_payments():
    return calculate_payment_analytics()

@app.get("/api/reviews/")
def get_reviews():
    return calculate_review_analytics()

@app.get("/api/forecasting/")
def get_forecasting():
    return calculate_sales_forecast()

@app.get("/api/recommendations/rules")
def get_rules(limit: int = 50):
    return recommender.rules[:limit]

@app.get("/api/recommendations/category")
def get_recommendations_endpoint(category_name: str, limit: int = 5):
    recs = recommender.get_recommendations(category_name, limit)
    return {
        "category": category_name,
        "recommendations": recs
    }

# ==========================================
# 7. RUNNER COMMAND
# ==========================================
if __name__ == "__main__":
    print("Running server locally...")
    uvicorn.run("backend_app:app", host="127.0.0.1", port=8000, reload=True)
