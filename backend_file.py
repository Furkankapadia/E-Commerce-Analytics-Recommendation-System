import os
import sys
import uvicorn
import sqlite3
import random
import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from collections import defaultdict
import shutil
from sklearn.linear_model import LinearRegression
from pydantic import BaseModel
from fastapi import FastAPI, APIRouter, Query, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

# ==========================================
# 1. CONFIGURATION & DATA PATHS
# ==========================================
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

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
# 2. UNIVERSAL SMART MAPPER ENGINE
# ==========================================
class UniversalEcommerceEngine:
    def __init__(self):
        self.df_transactions = None
        self.column_mapping = {}

    def set_data(self, df: pd.DataFrame):
        """
        Ingests the DataFrame, maps the columns dynamically, and cleans nulls/datatypes.
        """
        self.df_transactions = df.copy()
        self.column_mapping = self.map_columns(self.df_transactions)
        self.clean_mapped_data()

    def map_columns(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Scans column headers using fuzzy semantic keywords to identify key metrics.
        Ensures columns are mapped uniquely to avoid type/grouping conflicts.
        """
        mapping = {}
        cols = list(df.columns)
        matched_cols = set()

        rules = {
            "order_id": ["order_id", "invoiceno", "invoice", "transaction_id", "order_no", "order", "id", "bill_id", "restaurant id", "restaurant_id"],
            "customer_id": ["customer_unique_id", "customer_id", "customer", "user_id", "user", "client_id", "member_id", "buyer_id", "buyer"],
            "product_id": ["product_id", "product", "item_id", "sku", "code", "article_id", "article"],
            "category": ["category", "class", "dept", "department", "type", "group", "product_name", "product_category_name_english", "product_category_name", "product_id", "cuisine_type", "cuisines", "cuisine"],
            "date": ["date", "time", "timestamp", "day", "created_at", "order_purchase_timestamp", "invoicedate", "order_date_time"],
            "price": ["price", "unit_price", "amount", "value", "cost", "total", "revenue", "total_order_amount", "average cost for two", "average_cost_for_two"],
            "quantity": ["quantity", "qty", "units", "count", "items_ordered", "items"]
        }

        # Step 1: Exact matches (ensuring uniqueness)
        for key, keywords in rules.items():
            matched_col = None
            for keyword in keywords:
                for col in cols:
                    if col not in matched_cols and col.lower().strip() == keyword:
                        matched_col = col
                        break
                if matched_col:
                    break
            if matched_col:
                mapping[key] = matched_col
                matched_cols.add(matched_col)

        # Step 2: Substring matches for remaining keys
        for key, keywords in rules.items():
            if key in mapping:
                continue
            matched_col = None
            for keyword in keywords:
                for col in cols:
                    if col not in matched_cols and keyword in col.lower().strip():
                        matched_col = col
                        break
                if matched_col:
                    break
            if matched_col:
                mapping[key] = matched_col
                matched_cols.add(matched_col)

        # Date fallback parser
        if "date" not in mapping:
            for col in cols:
                if col in matched_cols:
                    continue
                # Exclude numeric columns and columns with non-date keywords (like ID, Code, rating, votes)
                if pd.api.types.is_numeric_dtype(df[col]) or any(k in col.lower() for k in ["id", "code", "votes", "rating", "phone", "zip", "post", "lat", "lng", "number"]):
                    continue
                try:
                    pd.to_datetime(df[col].iloc[:10], errors='raise')
                    mapping["date"] = col
                    matched_cols.add(col)
                    break
                except:
                    continue
            if "date" not in mapping:
                mapping["date"] = "_generate_dates"

        # Fallbacks for unmatched keys (attempting to use unmatched columns first)
        unmatched_cols = [c for c in cols if c not in matched_cols]
        default_fallback = unmatched_cols[0] if unmatched_cols else cols[0]

        if "category" not in mapping:
            mapping["category"] = mapping.get("product_id", default_fallback)
        if "product_id" not in mapping:
            mapping["product_id"] = unmatched_cols[0] if len(unmatched_cols) > 0 else cols[0]
            if unmatched_cols: matched_cols.add(unmatched_cols[0])
            unmatched_cols = [c for c in cols if c not in matched_cols]
        if "customer_id" not in mapping:
            mapping["customer_id"] = unmatched_cols[0] if len(unmatched_cols) > 0 else cols[0]
            if unmatched_cols: matched_cols.add(unmatched_cols[0])
            unmatched_cols = [c for c in cols if c not in matched_cols]
        if "order_id" not in mapping:
            mapping["order_id"] = cols[0]

        return mapping

    def clean_mapped_data(self):
        """
        Enforces types on mapped fields to prevent downstream math crashes by creating unique columns.
        Supports automatic synthetic generation of dates and payment methods if they are not in the dataset.
        """
        df = self.df_transactions
        m = self.column_mapping

        # Create unique mapped columns for each semantic key to prevent type/name conflicts
        # 1. Datetime formatting
        if m.get("date") == "_generate_dates" or "date" not in m:
            # Generate random dates distributed over the last 365 days
            np.random.seed(42)
            random_offsets = np.random.randint(0, 365, size=len(df))
            df["mapped_date"] = pd.Timestamp.now() - pd.to_timedelta(random_offsets, unit='D')
        else:
            date_col = m["date"]
            df["mapped_date"] = pd.to_datetime(df[date_col], errors='coerce')
            median_date = df["mapped_date"].median()
            df["mapped_date"] = df["mapped_date"].fillna(median_date if pd.notna(median_date) else pd.Timestamp.now())
        m["date"] = "mapped_date"

        # 2. Numeric Price formatting
        if "price" in m:
            price_col = m["price"]
            df["mapped_price"] = pd.to_numeric(df[price_col], errors='coerce').fillna(0.0)
        else:
            df["mapped_price"] = 0.0
        m["price"] = "mapped_price"

        # 3. Numeric Quantity formatting
        if "quantity" in m:
            qty_col = m["quantity"]
            df["mapped_quantity"] = pd.to_numeric(df[qty_col], errors='coerce').fillna(1).astype(int)
        else:
            df["mapped_quantity"] = 1
        m["quantity"] = "mapped_quantity"

        # 4. Strings formatting
        for key in ["order_id", "customer_id", "product_id", "category"]:
            if key in m:
                orig_col = m[key]
                df[f"mapped_{key}"] = df[orig_col].astype(str).fillna("unknown")
                m[key] = f"mapped_{key}"

        # 5. Reviews mapping (Optional)
        review_col = None
        for col in df.columns:
            if not col.startswith("mapped_") and ("review" in col.lower() or "rating" in col.lower() or "score" in col.lower()):
                review_col = col
                break
        if review_col:
            df["mapped_review_score"] = pd.to_numeric(df[review_col], errors='coerce').fillna(5).astype(int)
            m["review_score"] = "mapped_review_score"

        # 6. Payment method mapping (Optional)
        pay_col = None
        for col in df.columns:
            if not col.startswith("mapped_") and ("payment" in col.lower() or "method" in col.lower() or "pay_type" in col.lower()):
                pay_col = col
                break
        if pay_col:
            df["mapped_payment_type"] = df[pay_col].astype(str).fillna("unknown")
            m["payment_type"] = "mapped_payment_type"
        else:
            np.random.seed(42)
            methods = ["Credit Card", "UPI", "Cash", "Debit Card"]
            df["mapped_payment_type"] = np.random.choice(methods, size=len(df), p=[0.45, 0.35, 0.15, 0.05])
            m["payment_type"] = "mapped_payment_type"

# Global engine instance
engine = UniversalEcommerceEngine()

# ==========================================
# 3. DEFAULT DATA LOAD & JOIN PIPELINES
# ==========================================
def load_default_olist() -> pd.DataFrame:
    """
    Loads separate Olist files and joins them into a single consolidated transaction table.
    """
    consolidated_path = os.path.join(BASE_DIR, "consolidated_olist.csv")
    if os.path.exists(consolidated_path):
        print("Loading consolidated Olist cache from local storage...")
        try:
            return pd.read_csv(consolidated_path)
        except Exception as e:
            print(f"Failed to load consolidated cache: {e}. Rebuilding...")

    orders = pd.read_csv(DATA_FILES["orders"])
    order_items = pd.read_csv(DATA_FILES["order_items"])
    products = pd.read_csv(DATA_FILES["products"])
    customers = pd.read_csv(DATA_FILES["customers"])
    payments = pd.read_csv(DATA_FILES["payments"])
    
    # Category Translation
    if os.path.exists(DATA_FILES["translation"]):
        translation = pd.read_csv(DATA_FILES["translation"])
    else:
        translation = pd.DataFrame(columns=["product_category_name", "product_category_name_english"])
    
    extra_translations = pd.DataFrame([
        {"product_category_name": "pc_gamer", "product_category_name_english": "pc_gamer"},
        {"product_category_name": "portateis_cozinha_e_preparadores_de_alimentos", "product_category_name_english": "portable_kitchen_appliances"}
    ])
    translation = pd.concat([translation, extra_translations], ignore_index=True).drop_duplicates("product_category_name")
    
    # 1. Merge products with translations
    products_trans = pd.merge(products, translation, on="product_category_name", how="left")
    products_trans["product_category_name_english"] = products_trans["product_category_name_english"].fillna("other")
    
    # 2. Merge items and products
    df = pd.merge(order_items, products_trans, on="product_id", how="inner")
    
    # 3. Merge orders and customers
    orders_cust = pd.merge(orders, customers, on="customer_id", how="inner")
    df = pd.merge(df, orders_cust, on="order_id", how="inner")
    
    # 4. Group payments by order_id to keep 1 row per item
    pay_grouped = payments.groupby("order_id").agg({
        "payment_type": "first",
        "payment_value": "sum"
    }).reset_index()
    df = pd.merge(df, pay_grouped, on="order_id", how="left")
    
    # 5. Group reviews by order_id
    if os.path.exists(DATA_FILES["reviews"]):
        reviews = pd.read_csv(DATA_FILES["reviews"])
        rev_grouped = reviews.groupby("order_id").agg({"review_score": "mean"}).reset_index()
        df = pd.merge(df, rev_grouped, on="order_id", how="left")
        
    # Cache the consolidated dataset for future runs
    try:
        df.to_csv(consolidated_path, index=False)
        print("Cached consolidated Olist dataset locally for faster future startups.")
    except Exception as cache_err:
        print(f"Warning: Failed to save consolidated cache: {cache_err}")
        
    return df

def generate_synthetic_data() -> pd.DataFrame:
    """
    Generates a high-quality synthetic dataset when no local files are found,
    ensuring 100% startup reliability.
    """
    np.random.seed(42)
    n = 1000
    order_ids = [f"ORD-{np.random.randint(1000, 2000)}" for _ in range(n)]
    customer_ids = [f"CUST-{np.random.randint(100, 300)}" for _ in range(n)]
    product_ids = [f"PROD-{np.random.randint(10, 80)}" for _ in range(n)]
    categories = np.random.choice(["Electronics", "Clothing", "Home & Kitchen", "Books", "Sports", "Beauty"], size=n)
    dates = pd.date_range(start="2026-01-01", periods=n, freq="h")
    prices = np.round(np.random.uniform(5.0, 350.0, size=n), 2)
    quantities = np.random.randint(1, 4, size=n)
    payment_types = np.random.choice(["credit_card", "boleto", "debit_card", "voucher"], size=n, p=[0.7, 0.15, 0.1, 0.05])
    review_scores = np.random.choice([5, 4, 3, 2, 1], size=n, p=[0.6, 0.2, 0.1, 0.05, 0.05])
    
    return pd.DataFrame({
        "InvoiceNo": order_ids,
        "CustomerID": customer_ids,
        "ProductID": product_ids,
        "CategoryName": categories,
        "TransactionDate": dates,
        "UnitPrice": prices,
        "Quantity": quantities,
        "PaymentMethod": payment_types,
        "ReviewRating": review_scores
    })

def load_all_data():
    """
    Primary ingestion entrypoint. Loads previously uploaded file, Olist, or synthetic.
    """
    uploaded_path = os.path.join(BASE_DIR, "uploaded_transactions.csv")
    
    if os.path.exists(uploaded_path):
        print(f"Loading custom uploaded dataset from {uploaded_path}...")
        try:
            df = pd.read_csv(uploaded_path, encoding='utf-8')
        except:
            df = pd.read_csv(uploaded_path, encoding='latin1')
        engine.set_data(df)
    else:
        # Check if core Olist files exist
        core_files = ["orders", "order_items", "products", "customers", "payments"]
        all_exist = all(os.path.exists(DATA_FILES[f]) for f in core_files)
        
        if all_exist:
            print("Loading default Olist datasets...")
            try:
                df = load_default_olist()
                engine.set_data(df)
            except Exception as e:
                print(f"Error loading Olist dataset: {e}. Falling back to synthetic.")
                df = generate_synthetic_data()
                engine.set_data(df)
        else:
            print("No datasets found. Generating synthetic demo dataset...")
            df = generate_synthetic_data()
            engine.set_data(df)

# ==========================================
# 4. REFACTORED CORE ANALYTICS SERVICES
# ==========================================
def calculate_sales_analytics():
    df = engine.df_transactions
    m = engine.column_mapping
    
    # Check if shipping/freight is available in df columns
    freight_col = None
    for col in df.columns:
        if "freight" in col.lower() or "shipping" in col.lower():
            freight_col = col
            break
            
    total_sales = (df[m["price"]] * df[m["quantity"]]).sum()
    
    total_freight = 0.0
    if freight_col:
        total_freight = pd.to_numeric(df[freight_col], errors='coerce').fillna(0.0).sum()
        
    gross_revenue = float(total_sales + total_freight)
    
    total_orders = df[m["order_id"]].nunique()
    aov = gross_revenue / total_orders if total_orders > 0 else 0
    
    # Monthly sales trend
    df_temp = df.copy()
    df_temp["revenue"] = df_temp[m["price"]] * df_temp[m["quantity"]]
    if freight_col:
        df_temp["revenue"] += pd.to_numeric(df_temp[freight_col], errors='coerce').fillna(0.0)
        
    df_temp["year_month"] = df_temp[m["date"]].dt.to_period("M").astype(str)
    monthly_sales = df_temp.groupby("year_month")["revenue"].sum().reset_index().sort_values("year_month")
    
    return {
        "gross_revenue": round(gross_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": round(aov, 2),
        "monthly_trend": monthly_sales.to_dict(orient="records")
    }

def calculate_customer_analytics():
    df = engine.df_transactions
    m = engine.column_mapping
    
    total_customers = df[m["customer_id"]].nunique()
    
    cust_orders = df.groupby(m["customer_id"])[m["order_id"]].nunique().reset_index()
    returning_count = int((cust_orders[m["order_id"]] > 1).sum())
    new_count = total_customers - returning_count
    
    # RFM metrics
    df_rfm = df.copy()
    df_rfm["total_value"] = df_rfm[m["price"]] * df_rfm[m["quantity"]]
    
    ref_date = df[m["date"]].max() + pd.Timedelta(days=1)
    rfm = df_rfm.groupby(m["customer_id"]).agg({
        m["date"]: lambda x: (ref_date - x.max()).days,
        m["order_id"]: "nunique",
        "total_value": "sum"
    }).reset_index()
    rfm.columns = ["customer_id", "recency", "frequency", "monetary"]
    
    # Quintiles segment scores (using rank percentiles to prevent ValueError for duplicate bins)
    r_percentiles = rfm["recency"].rank(pct=True, method="first")
    rfm["R_score"] = (6 - pd.cut(r_percentiles, bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0], labels=[1, 2, 3, 4, 5], include_lowest=True).astype(int))
    
    rfm["F_score"] = rfm["frequency"].apply(lambda f: 1 if f == 1 else (3 if f == 2 else 5))
    
    m_percentiles = rfm["monetary"].rank(pct=True, method="first")
    rfm["M_score"] = pd.cut(m_percentiles, bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0], labels=[1, 2, 3, 4, 5], include_lowest=True).astype(int)
    
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
    df = engine.df_transactions
    m = engine.column_mapping
    
    df_prod = df.copy()
    df_prod["total_revenue"] = df_prod[m["price"]] * df_prod[m["quantity"]]
    
    top_categories_units = (
        df_prod.groupby(m["category"])[m["quantity"]]
        .sum().reset_index().rename(columns={m["quantity"]: "units_sold"})
        .sort_values("units_sold", ascending=False).head(10)
        .to_dict(orient="records")
    )
    
    top_categories_rev = (
        df_prod.groupby(m["category"])["total_revenue"]
        .sum().reset_index().rename(columns={"total_revenue": "revenue"})
        .sort_values("revenue", ascending=False).head(10)
    )
    top_categories_rev["revenue"] = top_categories_rev["revenue"].round(2)
    
    top_products_sold = (
        df_prod.groupby([m["product_id"], m["category"]])[m["quantity"]]
        .sum().reset_index().rename(columns={m["quantity"]: "units_sold"})
        .sort_values("units_sold", ascending=False).head(10)
        .to_dict(orient="records")
    )
    
    return {
        "top_categories_by_units": top_categories_units,
        "top_categories_by_revenue": top_categories_rev.to_dict(orient="records"),
        "top_products_by_units": top_products_sold
    }

def calculate_payment_analytics():
    df = engine.df_transactions
    m = engine.column_mapping
    
    df_temp = df.copy()
    df_temp["val"] = df_temp[m["price"]] * df_temp[m["quantity"]]
    
    total_payment = float(df_temp["val"].sum())
    
    payment_methods = (
        df_temp.groupby(m["payment_type"])
        .agg(transactions_count=(m["order_id"], "count"), total_value=("val", "sum"))
        .reset_index()
    )
    payment_methods["total_value"] = payment_methods["total_value"].round(2)
    
    # Check for installments
    inst_col = None
    for col in df.columns:
        if "installment" in col.lower():
            inst_col = col
            break
            
    if inst_col:
        installment_stats = (
            df.groupby(inst_col)[m["order_id"]]
            .count().reset_index().rename(columns={m["order_id"]: "count"})
            .sort_values(inst_col).head(15)
            .to_dict(orient="records")
        )
    else:
        installment_stats = [{"payment_installments": 1, "count": len(df)}]
        
    return {
        "total_payment_value": round(total_payment, 2),
        "average_payment_value": round(df_temp["val"].mean(), 2),
        "payment_methods": payment_methods.to_dict(orient="records"),
        "installment_distribution": installment_stats
    }

def calculate_review_analytics():
    df = engine.df_transactions
    m = engine.column_mapping
    
    if "review_score" not in m:
        return {
            "average_score": 5.0,
            "total_reviews": 0,
            "sentiment_ratio": {"positive": 0, "neutral": 0, "negative": 0},
            "score_distribution": {"5": 0}
        }
        
    avg_score = float(df[m["review_score"]].mean())
    total_reviews = int(df[m["order_id"]].nunique())
    
    ratings_count = df.groupby(m["order_id"])[m["review_score"]].mean().round().value_counts().to_dict()
    
    positive = ratings_count.get(5.0, 0) + ratings_count.get(4.0, 0)
    neutral = ratings_count.get(3.0, 0)
    negative = ratings_count.get(2.0, 0) + ratings_count.get(1.0, 0)
    
    return {
        "average_score": round(avg_score, 2),
        "total_reviews": total_reviews,
        "sentiment_ratio": {
            "positive": int(positive),
            "neutral": int(neutral),
            "negative": int(negative),
            "positive_percentage": round((positive / total_reviews) * 100, 2) if total_reviews > 0 else 0
        },
        "score_distribution": {str(int(k)): int(v) for k, v in ratings_count.items()}
    }

# ==========================================
# 5. CUSTOM APRIORI RECOMMENDATIONS ENGINE
# ==========================================
class AprioriRecommender:
    def __init__(self, min_support=0.00002, min_confidence=0.01):
        self.min_support = min_support
        self.min_confidence = min_confidence
        self.rules = []

    def train(self):
        df = engine.df_transactions
        m = engine.column_mapping
        
        print("Training Apriori Recommender: Extracting transaction baskets...")
        baskets = df.groupby(m["order_id"])[m["category"]].apply(set).tolist()
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
                    
        # Fallback to bestseller
        if not recs:
            try:
                top_cats = calculate_product_analytics()["top_categories_by_units"]
                for cat in top_cats:
                    name = cat[engine.column_mapping["category"]]
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
# 6. SALES FORECASTING SERVICES
# ==========================================
def calculate_sales_forecast():
    df = engine.df_transactions
    m = engine.column_mapping
    
    df_temp = df.copy()
    df_temp["revenue"] = df_temp[m["price"]] * df_temp[m["quantity"]]
    df_temp["year_month"] = df_temp[m["date"]].dt.to_period("M")
    
    monthly_series = df_temp.groupby("year_month")["revenue"].sum().reset_index().sort_values("year_month")
    
    n_months = len(monthly_series)
    if n_months < 3:
        return {"historical": [], "forecast": [], "next_month_forecast": 0.0, "next_quarter_forecast": 0.0, "growth_trend": "No Data"}
        
    monthly_series["time_index"] = np.arange(1, n_months + 1)
    monthly_series["month_of_year"] = monthly_series["year_month"].dt.month
    
    month_dummies = pd.get_dummies(monthly_series["month_of_year"], prefix="month", drop_first=True)
    X = pd.concat([monthly_series[["time_index"]], month_dummies], axis=1)
    
    for m_val in range(2, 13):
        col = f"month_{m_val}"
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
        m_val = p.month
        feat = {"time_index": t_idx}
        for month_val in range(2, 13):
            feat[f"month_{month_val}"] = 1 if m_val == month_val else 0
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
# 7. FASTAPI WEB SERVER APIS
# ==========================================
def print_analytics_report():
    """
    Synchronously calculates and prints the full E-Commerce Analytics report directly to stdout.
    """
    print("\n" + "="*50)
    print("          E-COMMERCE ANALYTICS REPORT          ")
    print("="*50)
    
    # Output mapped columns
    print("Autodetected Mapped Columns:")
    for key, val in engine.column_mapping.items():
        print(f"  - {key.upper()}: '{val}'")
    print("-"*50)
    
    sales = calculate_sales_analytics()
    print(f"Gross Revenue:         ${sales['gross_revenue']:,}")
    print(f"Total Orders:          {sales['total_orders']:,}")
    print(f"Average Order Value:   ${sales['average_order_value']:.2f}")
    
    cust = calculate_customer_analytics()
    print(f"Unique Customers:      {cust['total_customers']:,}")
    print(f"New vs Returning:      {cust['new_customers']:,} new / {cust['returning_customers']:,} returning")
    print(f"Customer Segments:     {cust['customer_segments']}")
    
    prod = calculate_product_analytics()
    print(f"Top 3 Categories (by units):")
    for i, cat in enumerate(prod['top_categories_by_units'][:3]):
        # Extract the name key dynamically
        cat_name = cat.get(engine.column_mapping["category"], cat.get("category", "unknown"))
        print(f"  {i+1}. {cat_name}: {cat['units_sold']:,} units")
        
    fc = calculate_sales_forecast()
    print(f"Next Month Forecast:   ${fc['next_month_forecast']:,}")
    print(f"Next Quarter Forecast: ${fc['next_quarter_forecast']:,}")
    print(f"Growth Trend:          {fc['growth_trend']}")
    
    rules = recommender.rules[:5]
    print(f"Top Apriori Rules Mined:")
    for r in rules:
        print(f"  - {r['antecedent']} -> {r['consequent']} (Conf: {r['confidence']:.2%}, Lift: {r['lift']})")
    print("="*50 + "\n")

# Global OTP storage: email -> { "otp": str, "user_data": dict }
otp_storage = {}

def load_env_file():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        print(f"Loading environment variables from {env_path}...")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    parts = line.split('=', 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    # Strip quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key] = val

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email_otp(target_email: str, otp: str) -> bool:
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = os.getenv("SMTP_PORT", "587")
    sender_email = os.getenv("SMTP_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    
    if not sender_email or not sender_password:
        print(f"\n[SMTP CONFIG WARNING] SMTP_EMAIL or SMTP_PASSWORD environment variables not found.")
        print(f"[SMTP MOCK] OTP for {target_email} is: {otp}\n")
        return False
        
    try:
        smtp_port = int(smtp_port)
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = target_email
        msg['Subject'] = f"BI-Predict OTP Verification Code: {otp}"
        
        body = f"""
        <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b0f19; padding: 25px; color: #f3f4f6;">
                <div style="max-width: 550px; margin: 0 auto; background: #111827; border-radius: 16px; padding: 30px; border: 1px solid #1f2937; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                    <h2 style="color: #6366f1; text-align: center; margin-bottom: 20px; font-family: sans-serif;">BI-Predict Verification</h2>
                    <p style="font-size: 1rem; color: #9ca3af; line-height: 1.5;">Hello,</p>
                    <p style="font-size: 1rem; color: #9ca3af; line-height: 1.5;">To complete your sign up and access your advanced analytical e-commerce dashboard, please enter the following One-Time Password (OTP) on the registration screen:</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <span style="font-size: 2.2rem; font-weight: bold; letter-spacing: 0.25em; color: #10b981; background: #1f2937; padding: 15px 30px; border-radius: 12px; border: 1px dashed #6366f1; display: inline-block; font-family: monospace;">{otp}</span>
                    </div>
                    <p style="font-size: 0.85rem; color: #6b7280; line-height: 1.4; text-align: center;">This code is valid for 10 minutes. If you did not request this registration, please ignore this email.</p>
                    <hr style="border: 0; border-top: 1px solid #1f2937; margin: 25px 0;">
                    <p style="font-size: 0.85rem; color: #6b7280; text-align: center; margin-bottom: 0;">BI-Predict Analytics Engine &copy; 2026</p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, target_email, msg.as_string())
        server.quit()
        
        print(f"[SMTP SUCCESS] Real verification email sent to {target_email} with OTP {otp}.")
        return True
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send email to {target_email}: {e}")
        return False

def init_auth_db():
    db_path = os.path.join(BASE_DIR, "users.db")
    print(f"Initializing users database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if table exists and if it has old schema (with 'company' column)
    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if columns and "company" in columns:
            print("Schema change detected: dropping old 'users' table...")
            cursor.execute("DROP TABLE users")
    except Exception as e:
        print(f"Table inspection error: {e}")
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

class SignUpRequest(BaseModel):
    name: str
    phone: str
    email: str
    password: str

class SignInRequest(BaseModel):
    email: str
    password: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    print("=== Launching Consolidated E-Commerce Backend ===")
    try:
        load_env_file()
        init_auth_db()
        load_all_data()
        recommender.train()
        print_analytics_report()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    print(f"\n[HTTP EXCEPTION CAUGHT] Status: {exc.status_code}, Detail: {exc.detail}")
    if exc.__cause__:
        print("[CAUSE DETECTED]")
        import traceback
        traceback.print_exception(type(exc.__cause__), exc.__cause__, exc.__cause__.__traceback__)
    if exc.__context__:
        print("[CONTEXT DETECTED]")
        import traceback
        traceback.print_exception(type(exc.__context__), exc.__context__, exc.__context__.__traceback__)
    print("--------------------------------------------------\n")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.get("/")
async def home():
    return {
        "server": "online",
        "api_documentation": "/docs",
        "message": "Send requests to /api/endpoints"
    }

import smtplib
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

class ReportRequest(BaseModel):
    email: str
    name: str

@app.post("/api/report/send")
async def send_report(req: ReportRequest):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except:
        smtp_port = 587
        
    sender_email = os.getenv("SMTP_EMAIL", "").strip()
    sender_password = os.getenv("SMTP_PASSWORD", "").strip()
    
    if not sender_email or not sender_password:
        raise HTTPException(
            status_code=400,
            detail="Mailing setup incomplete! Please fill your SMTP_EMAIL and SMTP_PASSWORD credentials inside the '.env' file in your project folder to authorize sending emails."
        )
        
    try:
        # 1. Fetch ML Prediction metrics to generate text summary
        sales_data = calculate_sales_analytics()
        customer_data = calculate_customer_analytics()
        product_data = calculate_product_analytics()
        
        # Format customer segment summary count
        segs_summary = ""
        for seg, count in customer_data.get("segments", {}).items():
            segs_summary += f"  - {seg}: {count} customers\n"
            
        # Format top product categories sold
        cats_summary = ""
        for idx, cat in enumerate(product_data.get("top_categories", [])):
            cat_name = cat.get("mapped_category", "Unknown").replace("_", " ")
            cats_summary += f"  - {idx+1}. {cat_name}: {cat.get('units_sold', 0)} units sold\n"
            
        report_content = f"""Subject: BI-Predict: E-Commerce Predictions & Recommendations Report

Dear {req.name},

Here is your E-Commerce Predictions and Customer Analysis Report compiled by the BI-Predict machine learning engine.

==================================================
              BI-PREDICT REPORT SUMMARY
==================================================
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Recipient Email: {req.email}

1. REVENUE FORECASTING (Linear Regression)
--------------------------------------------------
- Gross Sales Forecast (Next Month): ${sales_data.get('next_month_forecast', 0.0):,.2f}
- Projected Quarter Revenue: ${sales_data.get('next_quarter_forecast', 0.0):,.2f}
- Mapped Growth Slope Trend: {sales_data.get('growth_trend', 'Stable')}

2. CUSTOMER RFM VALUATION SEGMENTS
--------------------------------------------------
{segs_summary}
3. PRODUCT RANKINGS (Top Units Sold)
--------------------------------------------------
{cats_summary}

Please review the attached 'predictions_ledger.csv' file for the full list of customer RFM scores, recency/frequency metrics, and segment tag classifications.

Best regards,
BI-Predict AI Engine
--------------------------------------------------
This is an automated machine-learning generated dispatch.
"""
        # 2. Build the CSV attachment containing the full customer segments table
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w', encoding='utf-8')
        temp_file.write("Customer Unique ID,Recency (Days),Frequency (Orders),Monetary (Value),Segment Classification\n")
        
        for profile in customer_data.get("rfm_profiles", []):
            cust_id = profile.get("customer_id", "Unknown")
            recency = profile.get("recency", 0)
            frequency = profile.get("frequency", 0)
            monetary = profile.get("monetary", 0.0)
            segment = profile.get("segment", "Lost")
            temp_file.write(f"{cust_id},{recency},{frequency},{monetary:.2f},{segment}\n")
        temp_file.close()

        # 3. Create MIME Mail packet
        msg = MIMEMultipart()
        msg['From'] = f"BI-Predict Reports <{sender_email}>"
        msg['To'] = req.email
        msg['Subject'] = f"BI-Predict: E-Commerce Predictions Report for {req.name}"
        
        msg.attach(MIMEText(report_content, 'plain'))
        
        # Load CSV attachment
        with open(temp_file.name, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                'attachment; filename="predictions_ledger.csv"'
            )
            msg.attach(part)
            
        # Clear temporary path
        try:
            os.unlink(temp_file.name)
        except Exception:
            pass
            
        # 4. Connect to SMTP relay server and dispatch
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, req.email, msg.as_string())
        server.quit()
        
        return {
            "status": "success",
            "message": f"ML Predictions Report generated and sent to {req.email} successfully!"
        }
        
    except Exception as smtp_err:
        print(f"[SMTP ERROR] {str(smtp_err)}")
        raise HTTPException(
            status_code=500,
            detail=f"SMTP dispatch failure: {str(smtp_err)}. Please verify your SMTP login credentials or port state."
        )


@app.post("/api/auth/signup")
async def signup(user: SignUpRequest):
    db_path = os.path.join(BASE_DIR, "users.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, phone, email, password) VALUES (?, ?, ?, ?)",
            (user.name, user.phone, user.email, user.password)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Registration successful! Please sign in."}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An account with this email address already exists.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/api/auth/signin")
async def signin(credentials: SignInRequest):
    db_path = os.path.join(BASE_DIR, "users.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, email FROM users WHERE email = ? AND password = ?",
            (credentials.email, credentials.password)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "status": "success",
                "user": {
                    "name": row[0],
                    "email": row[1]
                }
            }
        else:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Endpoint Routers
@app.get("/api/sales/")
async def get_sales():
    return calculate_sales_analytics()

@app.get("/api/customers/")
async def get_customers():
    return calculate_customer_analytics()

@app.get("/api/products/")
async def get_products():
    return calculate_product_analytics()

@app.get("/api/payments/")
async def get_payments():
    return calculate_payment_analytics()

@app.get("/api/reviews/")
async def get_reviews():
    return calculate_review_analytics()

@app.get("/api/forecasting/")
async def get_forecasting():
    return calculate_sales_forecast()

@app.get("/api/recommendations/rules")
async def get_rules(limit: int = 50):
    return recommender.rules[:limit]

@app.get("/api/recommendations/category")
async def get_recommendations_endpoint(category_name: str, limit: int = 5):
    recs = recommender.get_recommendations(category_name, limit)
    return {
        "category": category_name,
        "recommendations": recs
    }

from fastapi import Request
from email.parser import BytesParser
from email.policy import default

@app.post("/api/upload/")
async def upload_datasets(request: Request):
    """
    Accepts flat CSV, Excel (.xlsx, .xls), or PDF transactions data,
    maps columns, and updates cached engines in memory.
    Runs 100% threadpool-free using email.parser to bypass AnyIO weakref bug in Python 3.14.
    """
    try:
        content_type = request.headers.get("content-type", "")
        body_bytes = await request.body()
        
        msg = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8") + body_bytes
        )
        
        file_bytes = None
        orig_filename = "uploaded_file.csv"
        
        if msg.is_multipart():
            for part in msg.iter_parts():
                cd = part.get("content-disposition", "")
                if 'name="file"' in cd:
                    file_bytes = part.get_payload(decode=True)
                    orig_filename = part.get_filename() or "uploaded_file.csv"
                    break
                    
        if file_bytes is None:
            raise ValueError("No file uploaded with key 'file'.")
            
        filename = orig_filename.lower()
        temp_path = os.path.join(BASE_DIR, f"temp_{orig_filename}")
        
        # Save the raw bytes directly to the temp file
        with open(temp_path, "wb") as buffer:
            buffer.write(file_bytes)
            
    except Exception as parse_err:
        raise HTTPException(status_code=400, detail=f"Failed to parse multipart request: {str(parse_err)}")
        
    print(f"New dataset received: {orig_filename}. Processing...")
    
    try:
        if filename.endswith('.csv'):
            try:
                df = pd.read_csv(temp_path, encoding='utf-8')
            except:
                df = pd.read_csv(temp_path, encoding='latin1')
                
        elif filename.endswith(('.xlsx', '.xls')):
            # Read first Excel sheet
            df = pd.read_excel(temp_path)
            
        elif filename.endswith('.pdf'):
            # Extract structured table cells from PDF pages
            import pdfplumber
            tables = []
            with pdfplumber.open(temp_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_table()
                    if extracted:
                        tables.extend(extracted)
            if not tables:
                raise ValueError("No tabular data detected in PDF. Ensure the PDF contains standard e-commerce transaction tables.")
            
            # Use first row as headers, clean nulls
            headers = [h if h is not None else f"col_{i}" for i, h in enumerate(tables[0])]
            data = tables[1:]
            df = pd.DataFrame(data, columns=headers)
            
        else:
            raise ValueError("Unsupported file format. Please upload .csv, .xlsx, .xls, or .pdf files.")
            
        # Clean columns to remove trailing spaces/carriage returns
        df.columns = [str(c).strip() for c in df.columns]
        
        # Save as standard clean CSV cache
        target_path = os.path.join(BASE_DIR, "uploaded_transactions.csv")
        df.to_csv(target_path, index=False)
        
        # Ingest and train
        engine.set_data(df)
        recommender.train()
        print_analytics_report()
        status = "success"
        message = f"File {orig_filename} processed, columns mapped, and models re-trained successfully!"
        
    except Exception as e:
        status = "error"
        message = f"Failed to process dataset file: {str(e)}"
        df = None
        
    # Clean up temp file
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception as cleanup_err:
            print(f"Warning: Failed to clean up temp file: {cleanup_err}")
            
    if status == "error":
        raise HTTPException(status_code=400, detail=message)
        
    return {
        "status": status,
        "message": message,
        "filename": orig_filename,
        "mapped_columns": engine.column_mapping,
        "total_rows": len(engine.df_transactions) if engine.df_transactions is not None else 0
    }

# ==========================================
# 8. RUNNER COMMAND & IMMEDIATE EXECUTION
# ==========================================
if __name__ == "__main__":
    print("Running data loading and analysis...")
    load_all_data()
    recommender.train()
    
    # Print the report directly to terminal stdout
    print_analytics_report()
    
    print("Starting server locally on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
