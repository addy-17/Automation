from fastmcp import FastMCP
from database import get_sales_df, get_inventory_df, refresh_all_reports, get_sync_status
from fastapi import FastAPI
import os
import uvicorn
import threading
import time
import pandas as pd

mcp = FastMCP("Retail Assistant")


def _get_mapped_columns(df):
    rev_col = next((c for c in df.columns if any(p in str(c).lower() for p in ['net_amount', 'net', 'amount', 'amt', 'sale', 'total'])), None)
    bill_col = next((c for c in df.columns if any(p in str(c).lower() for p in ['bill_no', 'bill', 'invoice', 'no', 'number', 'doc'])), None)
    qty_col = next((c for c in df.columns if any(p in str(c).lower() for p in ['qty', 'quantity', 'pcs', 'unit'])), None)
    brand_col = "brand" if "brand" in df.columns else next((c for c in df.columns if any(p in str(c).lower() for p in ['brand', 'item', 'article'])), None)
    return rev_col, bill_col, qty_col, brand_col


@mcp.tool()
def get_total_sales():
    sales = get_sales_df()
    if sales.empty:
        return {"revenue": 0.0, "bills": 0, "units": 0}

    rev_col, bill_col, qty_col, _ = _get_mapped_columns(sales)

    revenue = float(sales[rev_col].sum()) if rev_col else 0.0
    bills = int(sales[bill_col].nunique()) if bill_col else 0
    units = int(sales[qty_col].sum()) if qty_col else 0

    return {
        "revenue": revenue,
        "bills": bills,
        "units": units
    }


@mcp.tool()
def get_brand_sales(brand: str):
    sales = get_sales_df()
    if sales.empty:
        return {"brand": brand, "revenue": 0.0, "units": 0}

    rev_col, _, qty_col, brand_col = _get_mapped_columns(sales)

    if not brand_col:
        return {"brand": brand, "revenue": 0.0, "units": 0, "message": "No brand or item column detected."}

    df = sales[sales[brand_col].astype(str).str.lower() == brand.lower()]

    revenue = float(df[rev_col].sum()) if rev_col else 0.0
    units = int(df[qty_col].sum()) if qty_col else 0

    return {
        "brand": brand,
        "revenue": revenue,
        "units": units
    }


@mcp.tool()
def get_top_brands():
    sales = get_sales_df()
    if sales.empty:
        return {}

    rev_col, _, _, brand_col = _get_mapped_columns(sales)

    if not brand_col or not rev_col:
        return {"message": "Brand or revenue column not found."}

    top = (
        sales.groupby(brand_col)
        [rev_col]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )

    return top.to_dict()


@mcp.tool()
def founder_summary():
    sales = get_sales_df()
    if sales.empty:
        return {"total_revenue": 0.0, "top_brand": "None", "average_bill": 0.0}

    rev_col, bill_col, _, brand_col = _get_mapped_columns(sales)

    revenue = float(sales[rev_col].sum()) if rev_col else 0.0
    
    top_brand = "None"
    if brand_col and rev_col:
        try:
            top_brand = sales.groupby(brand_col)[rev_col].sum().idxmax()
        except Exception:
            pass

    avg_bill = 0.0
    if rev_col and bill_col:
        total_bills = sales[bill_col].nunique()
        if total_bills > 0:
            avg_bill = sales[rev_col].sum() / total_bills

    return {
        "total_revenue": revenue,
        "top_brand": top_brand,
        "average_bill": round(avg_bill, 2)
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


@mcp.tool()
def query_dataframe_stats(dataframe_name: str, metric: str, column: str = None, groupby: str = None, filter_query: str = None):
    """
    Perform statistical aggregations (sum, mean, count, unique_count, value_counts) on sales or inventory data.
    This lets you calculate sums, averages, and group stats directly on the server to answer quantitative business questions.
    - dataframe_name: 'sales' or 'inventory'
    - metric: 'sum', 'mean', 'count', 'unique_count', 'value_counts'
    - column: Column name to aggregate (e.g. 'Net Amount', 'Qty', 'MRP', 'Gross Amount')
    - groupby: Column name to group by (e.g. 'brand', 'Department', 'Store', 'Bill Date')
    - filter_query: Optional pandas query string to filter rows before aggregation (e.g. `brand == 'SainSisters'`)
    """
    if dataframe_name == "sales":
        df = get_sales_df()
    elif dataframe_name == "inventory":
        df = get_inventory_df()
    else:
        return {"error": "dataframe_name must be 'sales' or 'inventory'"}
        
    if df.empty:
        return {"message": f"Dataframe '{dataframe_name}' is empty or not loaded."}
        
    # Apply filter if provided
    if filter_query:
        try:
            df = df.query(filter_query)
        except Exception as e:
            return {"error": f"Invalid filter query: {e}"}
            
    if df.empty:
        return {"message": "No rows matched the filter criteria."}
        
    # Handle 'value_counts' (doesn't require a specific aggregation column, or counts values of the column)
    if metric == "value_counts":
        col_to_count = column or groupby
        if not col_to_count or col_to_count not in df.columns:
            return {"error": f"Please specify a valid column for value_counts. Available: {list(df.columns)}"}
        counts = df[col_to_count].value_counts().head(30)
        return {
            "metric": "value_counts",
            "column": col_to_count,
            "results": counts.to_dict()
        }
        
    if not column or column not in df.columns:
        return {"error": f"Please specify a valid column. Available columns: {list(df.columns)}"}
        
    # Perform aggregation
    try:
        if groupby:
            if groupby not in df.columns:
                return {"error": f"Groupby column '{groupby}' not found. Available: {list(df.columns)}"}
                
            grouped = df.groupby(groupby)[column]
            if metric == "sum":
                result = grouped.sum()
            elif metric == "mean":
                result = grouped.mean()
            elif metric == "count":
                result = grouped.count()
            elif metric == "unique_count":
                result = grouped.nunique()
            else:
                return {"error": f"Unsupported grouped metric '{metric}'"}
                
            # Sort descending and get top 30 to avoid token bloat
            result = result.sort_values(ascending=False).head(30)
            return {
                "metric": metric,
                "column": column,
                "groupby": groupby,
                "results": result.to_dict()
            }
        else:
            if metric == "sum":
                val = df[column].sum()
            elif metric == "mean":
                val = df[column].mean()
            elif metric == "count":
                val = df[column].count()
            elif metric == "unique_count":
                val = df[column].nunique()
            else:
                return {"error": f"Unsupported metric '{metric}'"}
                
            return {
                "metric": metric,
                "column": column,
                "result": float(val) if isinstance(val, (int, float, complex)) else str(val)
            }
    except Exception as e:
        return {"error": f"Aggregation error: {e}"}


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
