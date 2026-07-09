import pandas as pd
import numpy as np
from ..data_loader import get_data_state

def get_sales_analytics():
    """
    Returns total sales, monthly sales trend, and average order value.
    """
    state = get_data_state()
    
    # Calculate Total Sales (price + freight)
    total_sales = float(state.order_items["price"].sum())
    total_freight = float(state.order_items["freight_value"].sum())
    gross_revenue = total_sales + total_freight
    
    # AOV (Average Order Value)
    total_orders = state.orders["order_id"].nunique()
    aov = gross_revenue / total_orders if total_orders > 0 else 0
    
    # Monthly sales trend
    sales_merged = state.sales_items.copy()
    sales_merged["revenue"] = sales_merged["price"] + sales_merged["freight_value"]
    sales_merged["year_month"] = sales_merged["order_purchase_timestamp"].dt.to_period("M").astype(str)
    
    monthly_sales = (
        sales_merged.groupby("year_month")["revenue"]
        .sum()
        .reset_index()
        .sort_values("year_month")
    )
    monthly_sales_list = monthly_sales.to_dict(orient="records")
    
    return {
        "gross_revenue": round(gross_revenue, 2),
        "total_orders": total_orders,
        "average_order_value": round(aov, 2),
        "monthly_trend": monthly_sales_list
    }

def get_customer_analytics():
    """
    Calculates customer counts, new vs returning customers, and aggregates RFM metrics.
    """
    state = get_data_state()
    
    # Unique customers
    total_customers = state.customers["customer_unique_id"].nunique()
    
    # New vs Returning
    cust_orders_count = state.orders_customers.groupby("customer_unique_id")["order_id"].nunique().reset_index()
    returning_customers = int((cust_orders_count["order_id"] > 1).sum())
    new_customers = total_customers - returning_customers
    
    # RFM Base Calculations
    # Join orders, items, and customers
    df_rfm_raw = pd.merge(state.orders_customers, state.order_items, on="order_id", how="inner")
    df_rfm_raw["total_value"] = df_rfm_raw["price"] + df_rfm_raw["freight_value"]
    
    # Recency reference point: max date in dataset + 1 day
    max_date = state.orders["order_purchase_timestamp"].max()
    ref_date = max_date + pd.Timedelta(days=1)
    
    rfm = df_rfm_raw.groupby("customer_unique_id").agg({
        "order_purchase_timestamp": lambda x: (ref_date - x.max()).days, # Recency
        "order_id": "nunique",                                           # Frequency
        "total_value": "sum"                                             # Monetary
    }).reset_index()
    
    rfm.columns = ["customer_unique_id", "recency", "frequency", "monetary"]
    
    # Assign scores using quintiles (1-5 scale)
    # Note: For recency, lower is better. For freq/monetary, higher is better.
    rfm["R_score"] = pd.qcut(rfm["recency"], 5, labels=[5, 4, 3, 2, 1], duplicates='drop').astype(int)
    
    # Frequency is heavily skewed to 1 purchase (approx 96%), so we bin it manually
    def bin_frequency(freq):
        if freq == 1:
            return 1
        elif freq == 2:
            return 3
        else:
            return 5
            
    rfm["F_score"] = rfm["frequency"].apply(bin_frequency)
    rfm["M_score"] = pd.qcut(rfm["monetary"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop').astype(int)
    
    # Segment label assignment based on R and F scores
    def label_segment(row):
        r, f = row["R_score"], row["F_score"]
        if r >= 4 and f >= 4:
            return "Champions"
        elif r >= 3 and f >= 3:
            return "Loyal Customers"
        elif r >= 4 and f == 1:
            return "Recent/New Customers"
        elif r <= 2 and f >= 3:
            return "At Risk"
        else:
            return "Hibernating/Lost"
            
    rfm["segment"] = rfm.apply(label_segment, axis=1)
    
    segment_counts = rfm["segment"].value_counts().to_dict()
    
    return {
        "total_customers": total_customers,
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "returning_percentage": round((returning_customers / total_customers) * 100, 2) if total_customers > 0 else 0,
        "customer_segments": segment_counts,
        "sample_rfm": rfm.head(20).to_dict(orient="records")
    }

def get_product_analytics():
    """
    Returns top selling products and categories by unit volume and revenue.
    """
    state = get_data_state()
    
    # Merge items, products, and translations
    df_prod = state.product_sales.copy()
    df_prod["total_revenue"] = df_prod["price"] + df_prod["freight_value"]
    
    # Top Categories by Units Sold
    top_categories_units = (
        df_prod.groupby("product_category_name_english")["order_item_id"]
        .count()
        .reset_index()
        .rename(columns={"order_item_id": "units_sold"})
        .sort_values("units_sold", ascending=False)
        .head(10)
        .to_dict(orient="records")
    )
    
    # Top Categories by Revenue
    top_categories_rev = (
        df_prod.groupby("product_category_name_english")["total_revenue"]
        .sum()
        .reset_index()
        .rename(columns={"total_revenue": "revenue"})
        .sort_values("revenue", ascending=False)
        .head(10)
    )
    top_categories_rev["revenue"] = top_categories_rev["revenue"].round(2)
    top_categories_rev_list = top_categories_rev.to_dict(orient="records")
    
    # Top 10 Products by units sold
    top_products_sold = (
        df_prod.groupby(["product_id", "product_category_name_english"])["order_item_id"]
        .count()
        .reset_index()
        .rename(columns={"order_item_id": "units_sold"})
        .sort_values("units_sold", ascending=False)
        .head(10)
        .to_dict(orient="records")
    )
    
    return {
        "top_categories_by_units": top_categories_units,
        "top_categories_by_revenue": top_categories_rev_list,
        "top_products_by_units": top_products_sold
    }

def get_payment_analytics():
    """
    Returns payment methods breakdown, average value, and installment profiles.
    """
    state = get_data_state()
    
    # Value distribution
    total_payment_value = float(state.payments["payment_value"].sum())
    avg_payment_value = float(state.payments["payment_value"].mean())
    
    # Payment Method distribution
    payment_methods = (
        state.payments.groupby("payment_type")
        .agg(
            transactions_count=("payment_sequential", "count"),
            total_value=("payment_value", "sum")
        )
        .reset_index()
    )
    payment_methods["total_value"] = payment_methods["total_value"].round(2)
    payment_methods_list = payment_methods.to_dict(orient="records")
    
    # Installment stats
    installment_stats = (
        state.payments.groupby("payment_installments")["payment_value"]
        .count()
        .reset_index()
        .rename(columns={"payment_value": "count"})
        .sort_values("payment_installments")
        .head(15) # Show up to 15 installments
        .to_dict(orient="records")
    )
    
    return {
        "total_payment_value": round(total_payment_value, 2),
        "average_payment_value": round(avg_payment_value, 2),
        "payment_methods": payment_methods_list,
        "installment_distribution": installment_stats
    }

def get_review_analytics():
    """
    Returns review rating average, volume, and sentiment classification.
    """
    state = get_data_state()
    
    if state.reviews.empty:
        return {
            "average_score": 0.0,
            "total_reviews": 0,
            "sentiment_ratio": {"positive": 0, "neutral": 0, "negative": 0}
        }
        
    avg_score = float(state.reviews["review_score"].mean())
    total_reviews = int(state.reviews["review_id"].nunique())
    
    # Group into Positive (5 & 4), Neutral (3), Negative (2 & 1)
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
