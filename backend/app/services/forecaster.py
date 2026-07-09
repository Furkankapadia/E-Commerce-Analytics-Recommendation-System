import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from ..data_loader import get_data_state

def generate_sales_forecast():
    """
    Aggregates historical sales by month, fits a Linear Regression model,
    and forecasts revenue for the next month and the next quarter.
    """
    state = get_data_state()
    
    # 1. Prepare time-series dataframe
    df_sales = state.sales_items.copy()
    df_sales["revenue"] = df_sales["price"] + df_sales["freight_value"]
    
    # Extract year-month and daily dates
    df_sales["year_month"] = df_sales["order_purchase_timestamp"].dt.to_period("M")
    
    # Group by month
    monthly_series = df_sales.groupby("year_month")["revenue"].sum().reset_index()
    monthly_series = monthly_series.sort_values("year_month")
    
    # Filter out months with very low incomplete data (e.g. 2016-09 or 2018-10 which might be tail ends)
    # The active period of Olist is Jan 2017 to Aug 2018
    monthly_series = monthly_series[
        (monthly_series["year_month"] >= "2017-01") & 
        (monthly_series["year_month"] <= "2018-08")
    ].reset_index(drop=True)
    
    n_months = len(monthly_series)
    if n_months < 3:
        # Fallback if there is not enough historical data
        return {
            "historical": [],
            "forecast": [],
            "next_month_forecast": 0.0,
            "next_quarter_forecast": 0.0,
            "growth_trend": "Insufficient Data"
        }
        
    # 2. Build feature matrix for regression
    # Time index (1 to N)
    monthly_series["time_index"] = np.arange(1, n_months + 1)
    
    # Month of year to capture seasonality (1 to 12)
    monthly_series["month_of_year"] = monthly_series["year_month"].dt.month
    
    # Convert month to dummy variables (One-hot encoding for seasonality)
    month_dummies = pd.get_dummies(monthly_series["month_of_year"], prefix="month", drop_first=True)
    
    # Combine features
    X = pd.concat([monthly_series[["time_index"]], month_dummies], axis=1)
    # Ensure all months (1-12) are represented in dummy columns so forecast columns align
    for m in range(2, 13):
        col_name = f"month_{m}"
        if col_name not in X.columns:
            X[col_name] = 0
            
    # Sort columns to keep shape consistent
    X = X.reindex(sorted(X.columns), axis=1)
    
    y = monthly_series["revenue"]
    
    # 3. Fit Linear Regression Model
    model = LinearRegression()
    model.fit(X, y)
    
    # 4. Predict historical values
    monthly_series["fitted_values"] = model.predict(X)
    
    # 5. Predict future months (next 3 months / quarter)
    last_time_index = n_months
    last_period = monthly_series["year_month"].max()
    
    future_rows = []
    for step in range(1, 4):
        future_period = last_period + step
        future_time_index = last_time_index + step
        future_month = future_period.month
        
        # Build features for this future step
        feat = {"time_index": future_time_index}
        for m in range(2, 13):
            feat[f"month_{m}"] = 1 if future_month == m else 0
            
        future_rows.append((future_period, feat))
        
    # Predict
    future_features = pd.DataFrame([f[1] for f in future_rows])
    future_features = future_features.reindex(sorted(future_features.columns), axis=1)
    future_predictions = model.predict(future_features)
    
    # Ensure no negative predictions
    future_predictions = np.clip(future_predictions, 0, None)
    
    forecast_results = []
    for i, (period, _) in enumerate(future_rows):
        forecast_results.append({
            "year_month": str(period),
            "predicted_revenue": round(float(future_predictions[i]), 2)
        })
        
    next_month_val = forecast_results[0]["predicted_revenue"]
    next_quarter_val = sum(item["predicted_revenue"] for item in forecast_results)
    
    # Historical output
    historical_results = []
    for _, row in monthly_series.iterrows():
        historical_results.append({
            "year_month": str(row["year_month"]),
            "actual_revenue": round(float(row["revenue"]), 2),
            "fitted_revenue": round(float(row["fitted_values"]), 2)
        })
        
    # Determine growth trend direction
    slope = model.coef_[X.columns.get_loc("time_index")]
    trend_dir = "Upward" if slope > 0 else "Downward"
    
    return {
        "historical": historical_results,
        "forecast": forecast_results,
        "next_month_forecast": round(next_month_val, 2),
        "next_quarter_forecast": round(next_quarter_val, 2),
        "growth_trend": trend_dir
    }
