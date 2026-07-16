from fastmcp import FastMCP
from database import get_sales_df
from fastapi import FastAPI
import os
import uvicorn

mcp = FastMCP("Retail Assistant")


@mcp.tool()
def get_total_sales():

    sales = get_sales_df()

    revenue = float(
        sales["net_amount"].sum()
    )

    bills = int(
        sales["bill_no"].nunique()
    )

    units = int(
        sales["qty"].sum()
    )

    return {
        "revenue": revenue,
        "bills": bills,
        "units": units
    }


@mcp.tool()
def get_brand_sales(brand: str):

    sales = get_sales_df()

    df = sales[
        sales["brand"]
        .astype(str)
        .str.lower()
        ==
        brand.lower()
    ]

    revenue = float(
        df["net_amount"].sum()
    )

    units = int(
        df["qty"].sum()
    )

    return {
        "brand": brand,
        "revenue": revenue,
        "units": units
    }


@mcp.tool()
def get_top_brands():

    sales = get_sales_df()

    top = (
        sales.groupby("brand")
        ["net_amount"]
        .sum()
        .sort_values(
            ascending=False
        )
        .head(10)
    )

    return top.to_dict()


@mcp.tool()
def founder_summary():

    sales = get_sales_df()

    revenue = float(
        sales["net_amount"].sum()
    )

    top_brand = (
        sales.groupby("brand")
        ["net_amount"]
        .sum()
        .idxmax()
    )

    avg_bill = (
        sales["net_amount"]
        .sum()
        /
        sales["bill_no"]
        .nunique()
    )

    return {
        "total_revenue":
            revenue,
        "top_brand":
            top_brand,
        "average_bill":
            round(avg_bill, 2)
    }


app = mcp.http_app()

if __name__ == "__main__":

    PORT = int(
        os.environ.get(
            "PORT",
            8080
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT
    )