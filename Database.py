from pathlib import Path
from Parser import parse_bill_register
import pandas as pd

BASE_DIR = Path(__file__).parent

sales_path = (
    BASE_DIR /
    "reports" /
    "sales.xlsx"
)

sales_df = parse_bill_register(
    sales_path
)


def extract_brand(name):

    if pd.isna(name):
        return "Unknown"

    words = str(name).split()

    if len(words) > 1:
        return words[1]

    return "Unknown"


sales_df["brand"] = (
    sales_df["item_name"]
    .apply(extract_brand)
)


def get_sales_df():

    return sales_df.copy()