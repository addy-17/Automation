from fastmcp import FastMCP
from database import get_sales_df, get_inventory_df, refresh_all_reports, get_sync_status
from fastapi import FastAPI
import os
import uvicorn
import threading
import time
import pandas as pd

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


# New MCP Tools for querying Ginesys reports
@mcp.tool()
def refresh_reports():
    """
    Forces an immediate sync of reports from the email inbox (IMAP) or local fallback files.
    Returns the sync status and row counts of loaded reports.
    """
    return refresh_all_reports(force=True)


@mcp.tool()
def get_data_dictionary():
    """
    Returns the columns, data types, sync metadata, and a sample row from
    the loaded Sales and Inventory reports.
    """
    status = get_sync_status()
    sales = get_sales_df()
    inventory = get_inventory_df()
    
    return {
        "sync_status": status,
        "sales_report": {
            "columns": list(sales.columns) if not sales.empty else [],
            "dtypes": {col: str(dtype) for col, dtype in sales.dtypes.items()} if not sales.empty else {},
            "sample_row": sales.head(1).to_dict(orient="records")[0] if not sales.empty else {}
        },
        "inventory_report": {
            "columns": list(inventory.columns) if not inventory.empty else [],
            "dtypes": {col: str(dtype) for col, dtype in inventory.dtypes.items()} if not inventory.empty else {},
            "sample_row": inventory.head(1).to_dict(orient="records")[0] if not inventory.empty else {}
        }
    }


@mcp.tool()
def query_sales_data(query_str: str = None, start_date: str = None, end_date: str = None, columns: list = None, limit: int = 50):
    """
    Query the in-memory sales report.
    - query_str: A pandas query string (e.g. `net_amount > 1000` or `brand == 'SE26608'`)
    - start_date / end_date: ISO date strings (YYYY-MM-DD) to filter bill_date
    - columns: Specific columns to return (helps reduce token size)
    - limit: Maximum rows to return (default 50, max 200)
    """
    sales = get_sales_df()
    if sales.empty:
        return {"message": "No sales data is currently loaded."}
        
    # Standardize date filtering
    if start_date or end_date:
        try:
            temp_date_col = pd.to_datetime(sales["bill_date"], errors='coerce')
            mask = pd.Series(True, index=sales.index)
            if start_date:
                mask = mask & (temp_date_col >= pd.to_datetime(start_date))
            if end_date:
                mask = mask & (temp_date_col <= pd.to_datetime(end_date))
            sales = sales[mask]
        except Exception as e:
            print(f"[Query Sales] Date filtering error: {e}")
            
    if query_str:
        try:
            sales = sales.query(query_str)
        except Exception as e:
            return {"error": f"Invalid query string: {e}. Please ensure it follows pandas query syntax."}
            
    if columns:
        valid_cols = [c for c in columns if c in sales.columns]
        if valid_cols:
            sales = sales[valid_cols]
            
    total_matches = len(sales)
    sales = sales.head(min(max(1, limit), 200))
    
    return {
        "total_matches": total_matches,
        "returned_rows": len(sales),
        "data": sales.to_dict(orient="records")
    }


@mcp.tool()
def query_inventory_data(query_str: str = None, department: str = None, division: str = None, columns: list = None, limit: int = 50):
    """
    Query the in-memory inventory report.
    - query_str: A pandas query string (e.g. `MRP > 1000` or `Section == 'SCARVES'`)
    - department: Filter by department name (case-insensitive)
    - division: Filter by division name (case-insensitive)
    - columns: Specific columns to return (helps reduce token size)
    - limit: Maximum rows to return (default 50, max 200)
    """
    inventory = get_inventory_df()
    if inventory.empty:
        return {"message": "No inventory data is currently loaded."}
        
    if department:
        inventory = inventory[inventory["Department"].astype(str).str.lower() == department.lower()]
        
    if division:
        inventory = inventory[inventory["Division"].astype(str).str.lower() == division.lower()]
        
    if query_str:
        try:
            inventory = inventory.query(query_str)
        except Exception as e:
            return {"error": f"Invalid query string: {e}. Please ensure it follows pandas query syntax."}
            
    if columns:
        valid_cols = [c for c in columns if c in inventory.columns]
        if valid_cols:
            inventory = inventory[valid_cols]
            
    total_matches = len(inventory)
    inventory = inventory.head(min(max(1, limit), 200))
    
    return {
        "total_matches": total_matches,
        "returned_rows": len(inventory),
        "data": inventory.to_dict(orient="records")
    }


# Background thread to sync reports periodically (every 10 minutes)
def run_background_sync():
    print("[Server] Starting background report sync daemon...")
    # Initial sync on startup
    try:
        res = refresh_all_reports(force=True)
        print(f"[Server] Startup sync completed: {res}")
    except Exception as e:
        print(f"[Server] Startup sync failed: {e}")
        
    while True:
        time.sleep(600)  # Sync every 10 minutes
        try:
            print("[Server] Running periodic report sync...")
            res = refresh_all_reports(force=True)
            print(f"[Server] Periodic sync completed: {res}")
        except Exception as e:
            print(f"[Server] Periodic sync failed: {e}")


# Start sync daemon thread
sync_thread = threading.Thread(target=run_background_sync, name="ReportSyncDaemon", daemon=True)
sync_thread.start()


app = mcp.http_app()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
