"""A small messy CSV for Cleaner tests: case and spacing variants, money as text, a placeholder."""
import random

random.seed(7)
REGIONS = ["North", "north ", " NORTH", "South", "south", "East"]
rows = ["customer_id,region,amount,age"]
for i in range(1, 121):
    region = random.choice(REGIONS)
    amount = random.choice(["$1,200.50", "$980", "1,050", "$75.25", "N/A", "$2,000"])
    if i == 60:
        amount = "about ten"
    age = "" if i % 9 == 0 else str(20 + i % 40)
    rows.append(f"C{1000 + i},{region},\"{amount}\",{age}")
CSV = ("\n".join(rows) + "\n").encode()
