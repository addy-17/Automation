import os
import io
import imaplib
import email
from email.header import decode_header
import datetime
import threading
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

# Import the parsing functions from parser
from parser import parse_bill_register, parse_inventory

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).parent

# Global in-memory caches and state
_sales_df = None
_inventory_df = None
_last_sync_time = None
_sync_source = "None"
_sync_lock = threading.Lock()


def extract_brand(name):
    if pd.isna(name):
        return "Unknown"

    words = str(name).split()

    if len(words) > 1:
        return words[1]

    return "Unknown"


def fetch_latest_report_attachment(subject_filter):
    """
    Connects to the configured IMAP server, searches for the latest email
    with the given subject filter, and extracts the first Excel or CSV attachment.
    Returns (attachment_bytes, filename) or None if not found/error.
    """
    imap_server = os.getenv("IMAP_SERVER")
    imap_port_str = os.getenv("IMAP_PORT", "993")
    email_user = os.getenv("EMAIL_USER")
    email_password = os.getenv("EMAIL_PASSWORD")

    if not email_user or "your-email" in email_user or not email_password or "your-app-password" in email_password:
        print(f"[IMAP] Credentials not configured for filter '{subject_filter}'. Skipping email fetch.")
        return None

    try:
        imap_port = int(imap_port_str)
        print(f"[IMAP] Connecting to {imap_server}:{imap_port} as {email_user}...")
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(email_user, email_password)
        mail.select("inbox")

        # Search for emails matching the subject filter
        search_query = f'SUBJECT "{subject_filter}"'
        status, messages = mail.search(None, search_query)
        if status != "OK":
            print(f"[IMAP] Search failed for query: {search_query}")
            mail.logout()
            return None

        message_ids = messages[0].split()
        if not message_ids:
            print(f"[IMAP] No emails found matching subject: {subject_filter}")
            mail.logout()
            return None

        # Fetch the latest matching message
        latest_id = message_ids[-1]
        print(f"[IMAP] Found {len(message_ids)} matching emails. Fetching latest (ID: {latest_id.decode()})...")
        status, data = mail.fetch(latest_id, "(RFC822)")
        if status != "OK":
            print(f"[IMAP] Failed to fetch message {latest_id.decode()}")
            mail.logout()
            return None

        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        # Look for attachments
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue

            filename = part.get_filename()
            if filename:
                # Decode the attachment filename
                decoded = decode_header(filename)
                filename = decoded[0][0]
                if isinstance(filename, bytes):
                    filename = filename.decode(decoded[0][1] or "utf-8", errors="ignore")

                # Check if it's an Excel or CSV file
                ext = Path(filename).suffix.lower()
                if ext in [".xlsx", ".xls", ".csv"]:
                    print(f"[IMAP] Found matching attachment: {filename}")
                    file_content = part.get_payload(decode=True)
                    mail.logout()
                    return file_content, filename

        mail.logout()
        print(f"[IMAP] No valid Excel/CSV attachment found in email '{subject_filter}'")
        return None
    except Exception as e:
        print(f"[IMAP] Error fetching email for '{subject_filter}': {e}")
        return None


def refresh_all_reports(force=False):
    """
    Refreshes the in-memory sales and inventory dataframes.
    Attempts to fetch from email first. Falls back to local files in the reports/ directory
    if email configuration is missing, fails, or reports aren't found in mail.
    """
    global _sales_df, _inventory_df, _last_sync_time, _sync_source

    with _sync_lock:
        # If already loaded and force is False, don't run again
        if not force and _sales_df is not None and _inventory_df is not None:
            return {
                "status": "Success (cached)",
                "sales_count": len(_sales_df),
                "inventory_count": len(_inventory_df),
                "source": _sync_source,
                "last_sync_time": _last_sync_time
            }

        print("[Sync] Initiating data synchronization...")
        sales_subject = os.getenv("SALES_SUBJECT_FILTER", "POS Bill Register")
        inventory_subject = os.getenv("INVENTORY_SUBJECT_FILTER", "Latest Inventory")

        temp_sales_df = None
        temp_inventory_df = None
        source_used = "None"

        # 1. Try to fetch from Email
        sales_email_data = fetch_latest_report_attachment(sales_subject)
        if sales_email_data:
            attachment_bytes, filename = sales_email_data
            try:
                print(f"[Sync] Parsing sales data from email attachment: {filename}")
                temp_sales_df = parse_bill_register(io.BytesIO(attachment_bytes))
                source_used = "Email"
            except Exception as e:
                print(f"[Sync] Error parsing sales email attachment: {e}")

        inventory_email_data = fetch_latest_report_attachment(inventory_subject)
        if inventory_email_data:
            attachment_bytes, filename = inventory_email_data
            try:
                print(f"[Sync] Parsing inventory data from email attachment: {filename}")
                temp_inventory_df = parse_inventory(io.BytesIO(attachment_bytes))
                if source_used == "None":
                    source_used = "Email"
                elif source_used != "Email":
                    source_used = "Mixed"
            except Exception as e:
                print(f"[Sync] Error parsing inventory email attachment: {e}")

        # 2. Fall back to Local Files for missing reports
        local_reports_dir = BASE_DIR / "reports"

        if temp_sales_df is None:
            sales_path = local_reports_dir / "sales.xlsx"
            if sales_path.exists():
                try:
                    print(f"[Sync] Email fetch failed/skipped. Loading sales from local file: {sales_path}")
                    temp_sales_df = parse_bill_register(sales_path)
                    source_used = "Local File" if source_used == "None" else "Mixed"
                except Exception as e:
                    print(f"[Sync] Error parsing local sales file: {e}")
            else:
                print("[Sync] Local sales report not found.")

        if temp_inventory_df is None:
            inventory_path = local_reports_dir / "Latest Inventory.xlsx"
            if inventory_path.exists():
                try:
                    print(f"[Sync] Email fetch failed/skipped. Loading inventory from local file: {inventory_path}")
                    temp_inventory_df = parse_inventory(inventory_path)
                    source_used = "Local File" if source_used == "None" else "Mixed"
                except Exception as e:
                    print(f"[Sync] Error parsing local inventory file: {e}")
            else:
                print("[Sync] Local inventory report not found.")

        # 3. Post-process and update cache
        if temp_sales_df is not None:
            if not temp_sales_df.empty:
                # Make sure brand column is calculated
                temp_sales_df["brand"] = temp_sales_df["item_name"].apply(extract_brand)
            _sales_df = temp_sales_df

        if temp_inventory_df is not None:
            _inventory_df = temp_inventory_df

        # Determine success status
        if _sales_df is not None and _inventory_df is not None:
            status = "Success"
            _sync_source = source_used
            _last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif _sales_df is not None or _inventory_df is not None:
            status = "Partial Success"
            _sync_source = source_used
            _last_sync_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            status = "Failed"

        return {
            "status": status,
            "sales_count": len(_sales_df) if _sales_df is not None else 0,
            "inventory_count": len(_inventory_df) if _inventory_df is not None else 0,
            "source": _sync_source,
            "last_sync_time": _last_sync_time
        }


def get_sales_df(force_refresh=False):
    """
    Returns a copy of the in-memory sales DataFrame, refreshing if needed.
    """
    global _sales_df
    if _sales_df is None or force_refresh:
        refresh_all_reports(force=force_refresh)
    if _sales_df is None:
        return pd.DataFrame()
    return _sales_df.copy()


def get_inventory_df(force_refresh=False):
    """
    Returns a copy of the in-memory inventory DataFrame, refreshing if needed.
    """
    global _inventory_df
    if _inventory_df is None or force_refresh:
        refresh_all_reports(force=force_refresh)
    if _inventory_df is None:
        return pd.DataFrame()
    return _inventory_df.copy()


def get_sync_status():
    """
    Returns metadata about the current in-memory cache status.
    """
    return {
        "last_sync_time": _last_sync_time,
        "source": _sync_source,
        "sales_loaded": _sales_df is not None,
        "sales_rows": len(_sales_df) if _sales_df is not None else 0,
        "inventory_loaded": _inventory_df is not None,
        "inventory_rows": len(_inventory_df) if _inventory_df is not None else 0
    }