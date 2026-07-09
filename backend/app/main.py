from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .data_loader import load_all_data
from .services.recommender import train_recommender
from .routers import sales, customers, products, recommendations, forecasting, payments, reviews

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    print("=== Starting E-Commerce Analytics Backend ===")
    try:
        # Load the cache
        load_all_data()
        # Pre-train recommender rules on startup
        train_recommender()
        print("=== Backend initialized and ready to serve ===")
    except Exception as e:
        print(f"CRITICAL: Failed to initialize backend cache: {e}")
        
    yield
    # Shutdown actions (if any)
    print("=== Shutting down E-Commerce Analytics Backend ===")

app = FastAPI(
    title="E-Commerce Analytics & Recommendation System API",
    description="Backend API serving Sales, Customer (RFM), Product, Payment, and Review analytics alongside an Apriori recommendation engine.",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for Frontend connectivity
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(sales.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(forecasting.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "E-Commerce Analytics & Recommendation System API is active.",
        "documentation": "/docs"
    }
