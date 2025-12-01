import frappe


def execute(filters=None):
    if not filters:
        filters = {}

    # Base report columns
    columns = [
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 220},
        {"label": "Item Group", "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 150},

        {"label": "Total Sales Amount", "fieldname": "total_amount", "fieldtype": "Currency", "width": 150},
        {"label": "Total Sold Qty", "fieldname": "total_qty", "fieldtype": "Float", "width": 120},
    ]

    # Add per-warehouse qty columns dynamically
    warehouses = frappe.get_all("Warehouse", pluck="name")
    for wh in warehouses:
        fieldname = wh.lower().replace(" ", "_").replace("-", "_")
        columns.append({
            "label": f"{wh} Qty",
            "fieldname": fieldname,
            "fieldtype": "Float",
            "width": 120
        })

    # ➤ New total of all warehouses column
    columns.append({
        "label": "All Warehouses Total Qty",
        "fieldname": "total_stock_qty",
        "fieldtype": "Float",
        "width": 150
    })

    # Safety stock and shortage columns
    columns += [
        {"label": "Safety Stock", "fieldname": "safety_stock", "fieldtype": "Float", "width": 120},
        {"label": "Shortage Qty", "fieldname": "shortage_qty", "fieldtype": "Float", "width": 130},
    ]

    return columns, get_data(filters, warehouses)


def get_data(filters, warehouses):
    params = {"docstatus": 1}
    conditions = " AND si.docstatus = %(docstatus)s"

    if filters.get("from_date"):
        conditions += " AND si.posting_date >= %(from_date)s"
        params["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND si.posting_date <= %(to_date)s"
        params["to_date"] = filters["to_date"]

    if filters.get("item_group"):
        conditions += " AND i.item_group = %(item_group)s"
        params["item_group"] = filters["item_group"]

    # Filter on custom_item_type with default Finished Goods
    if not filters.get("custom_item_type"):
        filters["custom_item_type"] = "Finished Goods"
    conditions += " AND i.custom_item_type = %(custom_item_type)s"
    params["custom_item_type"] = filters["custom_item_type"]

    # Sales summary query
    sales_query = f"""
        SELECT
            sii.item_code,
            i.item_name,
            i.item_group,
            SUM(sii.amount) AS total_amount,
            SUM(sii.qty) AS total_qty,
            COALESCE(i.safety_stock, 0) AS safety_stock
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        JOIN `tabItem` i ON i.name = sii.item_code
        WHERE 1 = 1
        {conditions}
        GROUP BY sii.item_code, i.item_name, i.item_group, i.safety_stock
        ORDER BY total_amount DESC
        LIMIT 100
    """

    sales_rows = frappe.db.sql(sales_query, params, as_dict=True)

    if not sales_rows:
        return []

    item_codes = [row["item_code"] for row in sales_rows]

    # Read current stock from Bin per item + warehouse
    bins = frappe.get_all(
        "Bin",
        filters={"item_code": ["in", item_codes]},
        fields=["item_code", "warehouse", "actual_qty"],
    )

    stock_map = {}
    total_stock = frappe._dict()

    for b in bins:
        key = (b.item_code, b.warehouse)
        stock_map[key] = b.actual_qty
        total_stock.setdefault(b.item_code, 0)
        total_stock[b.item_code] += b.actual_qty

    # Attach per-warehouse qty, total qty & shortage
    for row in sales_rows:
        item_code = row["item_code"]

        # Per warehouse qty
        for wh in warehouses:
            fieldname = wh.lower().replace(" ", "_").replace("-", "_")
            row[fieldname] = stock_map.get((item_code, wh), 0)

        available_qty = total_stock.get(item_code, 0)

        # ➤ New total of all warehouses field
        row["total_stock_qty"] = available_qty

        safety_stock = row.get("safety_stock") or 0
        shortage = safety_stock - available_qty
        row["shortage_qty"] = shortage if shortage > 0 else 0

    return sales_rows
