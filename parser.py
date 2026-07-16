import pandas as pd


def parse_bill_register(file_path):

    df = pd.read_excel(
        file_path,
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
