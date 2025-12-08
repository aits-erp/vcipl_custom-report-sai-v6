import frappe

def execute(filters=None):
    filters = filters or {}

    columns = [
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Link",
         "options": "Item", "width": 150},

        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 200},

        {"label": "Item Group", "fieldname": "item_group", "fieldtype": "Link",
         "options": "Item Group", "width": 150},

        {"label": "Total Sales Amount", "fieldname": "total_amount", "fieldtype": "Currency", "width": 150},

        {"label": "Total Sold Qty", "fieldname": "total_qty", "fieldtype": "Float", "width": 120},

        {"label": "Total Stock Qty", "fieldname": "total_stock_qty", "fieldtype": "Float", "width": 140},

        {"label": "Safety Stock", "fieldname": "safety_stock", "fieldtype": "Float", "width": 120},

        {"label": "Shortage Qty", "fieldname": "shortage_qty", "fieldtype": "Float", "width": 120},

        # Drill-down clickable column
        {"label": "Warehouses", "fieldname": "details", "fieldtype": "Data", "width": 120},
    ]

    data = get_data(filters)
    return columns, data


def get_data(filters):

    params = {"docstatus": 1}
    conditions = " AND si.docstatus = %(docstatus)s"

    # Date Filters
    if filters.get("from_date"):
        conditions += " AND si.posting_date >= %(from_date)s"
        params["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND si.posting_date <= %(to_date)s"
        params["to_date"] = filters["to_date"]

    # Item Group Filter
    if filters.get("item_group"):
        conditions += " AND i.item_group = %(item_group)s"
        params["item_group"] = filters["item_group"]

    # Custom Item Type (default = Finished Goods)
    params["custom_item_type"] = filters.get("custom_item_type") or "Finished Goods"
    conditions += " AND i.custom_item_type = %(custom_item_type)s"

    # --------------------------------------
    # SALES QUERY
    # --------------------------------------
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
        WHERE 1=1
        {conditions}
        GROUP BY sii.item_code, i.item_name, i.item_group, i.safety_stock
        ORDER BY total_amount DESC
        LIMIT 100
    """

    rows = frappe.db.sql(sales_query, params, as_dict=True)

    if not rows:
        return []

    item_codes = [r.item_code for r in rows]

    # --------------------------------------
    # STOCK (BIN) QUERY
    # --------------------------------------
    bins = frappe.get_all(
        "Bin",
        filters={"item_code": ["in", item_codes]},
        fields=["item_code", "warehouse", "actual_qty"]
    )

    total_stock = {}
    for b in bins:
        total_stock[b.item_code] = total_stock.get(b.item_code, 0) + b.actual_qty

    # --------------------------------------
    # FINAL MERGE OF DATA
    # --------------------------------------
    for r in rows:
        item_code = r.item_code

        # Total stock across warehouses
        r["total_stock_qty"] = total_stock.get(item_code, 0)

        # Shortage calculation
        safety = r.get("safety_stock") or 0
        shortage = safety - r["total_stock_qty"]
        r["shortage_qty"] = shortage if shortage > 0 else 0

        # Drill-down clickable link
        r["details"] = "View Warehouses"

    return rows
