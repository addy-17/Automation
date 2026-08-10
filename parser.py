import pandas as pd


def parse_bill_register(file_path_or_buffer):
    """
    Parses a POS Bill Register report from Ginesys in Excel format.
    Accepts a file path string, Path object, or file-like object (like io.BytesIO).
    """
    df = pd.read_excel(
        file_path_or_buffer,
        header=None
    )

    rows = []

    current_bill = None
    current_date = None
    current_customer = None

    for i in range(len(df)):

        row = df.iloc[i]

        # Detect bill header
        if (
            row[0] == "Toscee Collective"
            and pd.notna(row[4])
        ):

            current_date = row[1]
            current_bill = row[4]
            current_customer = row[9]

            continue

        # Detect item rows
        barcode = row[0]

        if (
            pd.notna(barcode)
            and isinstance(barcode, str)
            and barcode != "Barcode"
            and barcode != "MOP"
            and current_bill is not None
        ):

            item_name = row[1]
            qty = row[6]
            net = row[12]

            rows.append({

                "bill_no":
                    current_bill,

                "bill_date":
                    current_date,

                "customer":
                    current_customer,

                "barcode":
                    barcode,

                "item_name":
                    item_name,

                "qty":
                    qty,

                "net_amount":
                    net
            })

    sales_df = pd.DataFrame(rows)

    return sales_df


def parse_inventory(file_path_or_buffer):
    """
    Parses an inventory report from Ginesys in Excel or CSV format.
    Accepts a file path string, Path object, or file-like object (like io.BytesIO).
    """
    try:
        # Try reading as excel
        df = pd.read_excel(file_path_or_buffer)
    except Exception as e:
        # Fallback to CSV if Excel parsing fails (e.g. if the file content is CSV)
        try:
            if hasattr(file_path_or_buffer, 'seek'):
                file_path_or_buffer.seek(0)
            df = pd.read_csv(file_path_or_buffer)
        except Exception as e_inner:
            print(f"Error parsing inventory report: {e} | CSV fallback error: {e_inner}")
            df = pd.DataFrame()
    return df


def parse_generic_report(file_path_or_buffer):
    """
    Parses a tabular report generically by dynamically detecting the column header row.
    Accepts a file path string, Path object, or file-like object (like io.BytesIO).
    """
    try:
        # Load raw dataframe without headers first
        df_raw = pd.read_excel(file_path_or_buffer, header=None)
    except Exception as e:
        try:
            if hasattr(file_path_or_buffer, 'seek'):
                file_path_or_buffer.seek(0)
            df_raw = pd.read_csv(file_path_or_buffer, header=None)
        except Exception as e_inner:
            print(f"Error reading report generically: {e} | CSV error: {e_inner}")
            return pd.DataFrame()

    if df_raw.empty:
        return pd.DataFrame()

    # Find the header row
    # Heuristic: evaluate each row to see which one has the most non-null, unique-like column elements
    header_idx = 0
    max_score = -1
    
    for idx in range(min(15, len(df_raw))):
        row = df_raw.iloc[idx]
        # Count non-null string/numeric entries that are likely headers (non-empty and not just simple numbers)
        score = sum(1 for val in row if pd.notna(val) and len(str(val).strip()) > 0 and not str(val).strip().replace('.', '', 1).isdigit())
        if score > max_score:
            max_score = score
            header_idx = idx

    print(f"[Generic Parser] Automatically detected header row at index: {header_idx}")
    
    # Reload or slice the dataframe starting from the header row
    df = df_raw.iloc[header_idx + 1:].copy()
    
    # Extract headers
    headers = []
    for i, h in enumerate(df_raw.iloc[header_idx]):
        if pd.notna(h) and len(str(h).strip()) > 0:
            headers.append(str(h).strip())
        else:
            headers.append(f"Column_{i}")
            
    df.columns = headers
    
    # Drop rows that are completely empty
    df.dropna(how='all', inplace=True)
    
    # Reset index
    df.reset_index(drop=True, inplace=True)
    
    return df

