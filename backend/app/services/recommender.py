import pandas as pd
from collections import defaultdict
from ..data_loader import get_data_state
from .analytics import get_product_analytics

class AprioriRecommender:
    """
    Custom Apriori and Association Rule Mining system.
    Mines patterns between product categories to build recommendations.
    """
    def __init__(self, min_support=0.00002, min_confidence=0.01):
        self.min_support = min_support
        self.min_confidence = min_confidence
        self.rules = [] # List of dicts containing rules

    def train(self):
        """
        Trains the Apriori model on the current dataset cache.
        """
        state = get_data_state()
        df_prod_sales = state.product_sales.copy()
        
        print("Training Apriori Recommender: Extracting transaction baskets...")
        baskets = df_prod_sales.groupby("order_id")["product_category_name_english"].apply(set).tolist()
        
        total_transactions = len(baskets)
        if total_transactions == 0:
            print("Apriori Training failed: No transactions found.")
            return
            
        # 1. Count occurrences of 1-itemsets
        item_counts = defaultdict(int)
        for basket in baskets:
            for item in basket:
                item_counts[item] += 1
                
        # Filter 1-itemsets by min support
        frequent_1_itemsets = {}
        for item, count in item_counts.items():
            support = count / total_transactions
            if support >= self.min_support:
                frequent_1_itemsets[item] = support
                
        print(f"Apriori: Found {len(frequent_1_itemsets)} frequent categories (1-itemsets).")

        # 2. Count occurrences of 2-itemsets (pairs)
        pair_counts = defaultdict(int)
        for basket in baskets:
            freq_items_in_basket = [item for item in basket if item in frequent_1_itemsets]
            n = len(freq_items_in_basket)
            for i in range(n):
                for j in range(i + 1, n):
                    pair = tuple(sorted((freq_items_in_basket[i], freq_items_in_basket[j])))
                    pair_counts[pair] += 1

        # Filter 2-itemsets by min support
        frequent_2_itemsets = {}
        for pair, count in pair_counts.items():
            support = count / total_transactions
            if support >= self.min_support:
                frequent_2_itemsets[pair] = support
                
        print(f"Apriori: Found {len(frequent_2_itemsets)} frequent pairs (2-itemsets).")

        # 3. Generate Association Rules
        self.rules = []
        for pair, pair_support in frequent_2_itemsets.items():
            item_a, item_b = pair
            
            # Rule 1: A -> B
            support_a = frequent_1_itemsets[item_a]
            confidence_a_to_b = pair_support / support_a
            lift_a_to_b = confidence_a_to_b / frequent_1_itemsets[item_b]
            
            if confidence_a_to_b >= self.min_confidence:
                self.rules.append({
                    "antecedent": item_a,
                    "consequent": item_b,
                    "support": round(pair_support, 5),
                    "confidence": round(confidence_a_to_b, 4),
                    "lift": round(lift_a_to_b, 2)
                })
                
            # Rule 2: B -> A
            support_b = frequent_1_itemsets[item_b]
            confidence_b_to_a = pair_support / support_b
            lift_b_to_a = confidence_b_to_a / frequent_1_itemsets[item_a]
            
            if confidence_b_to_a >= self.min_confidence:
                self.rules.append({
                    "antecedent": item_b,
                    "consequent": item_a,
                    "support": round(pair_support, 5),
                    "confidence": round(confidence_b_to_a, 4),
                    "lift": round(lift_b_to_a, 2)
                })
                
        # Sort rules by Lift, then Confidence
        self.rules = sorted(self.rules, key=lambda x: (x["lift"], x["confidence"]), reverse=True)
        print(f"Apriori: Generated {len(self.rules)} association rules.")

    def get_recommendations(self, category_name: str, limit=5):
        """
        Returns recommendations for a given category. Falls back to top-selling categories
        if no direct rules are matched.
        """
        if not self.rules:
            self.train()
            
        recommendations = []
        for rule in self.rules:
            if rule["antecedent"].lower() == category_name.lower():
                recommendations.append({
                    "recommended_category": rule["consequent"],
                    "confidence": rule["confidence"],
                    "lift": rule["lift"],
                    "support": rule["support"],
                    "type": "association_rule"
                })
                if len(recommendations) >= limit:
                    break
                    
        # Fallback mechanism: recommend top selling categories (excluding current)
        if not recommendations:
            print(f"No association rule found for '{category_name}'. Using bestseller fallback.")
            try:
                prod_analytics = get_product_analytics()
                top_cats = prod_analytics["top_categories_by_units"]
                
                for cat in top_cats:
                    name = cat["product_category_name_english"]
                    if name.lower() != category_name.lower():
                        recommendations.append({
                            "recommended_category": name,
                            "confidence": 0.0,
                            "lift": 0.0,
                            "support": 0.0,
                            "type": "bestseller_fallback"
                        })
                        if len(recommendations) >= limit:
                            break
            except Exception as e:
                print(f"Error compiling bestseller fallback: {e}")
                
        return recommendations

# Global recommender instance
recommender = AprioriRecommender()

def train_recommender():
    recommender.train()

def get_category_recommendations(category_name: str, limit=5):
    return recommender.get_recommendations(category_name, limit)

def get_all_association_rules(limit=50):
    if not recommender.rules:
        recommender.train()
    return recommender.rules[:limit]
