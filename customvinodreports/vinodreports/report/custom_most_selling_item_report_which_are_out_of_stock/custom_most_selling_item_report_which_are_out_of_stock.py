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
        columns.append({
            "label": f"{wh} Qty",
            "fieldname": wh.lower().replace(" ", "_").replace("-", "_"),
            "fieldtype": "Float",
            "width": 120
        })

    # Safety stock & shortage
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

    # default custom_item_type = Finished Goods
    if not filters.get("custom_item_type"):
        filters["custom_item_type"] = "Finished Goods"
    conditions += " AND i.custom_item_type = %(custom_item_type)s"
    params["custom_item_type"] = filters["custom_item_type"]

    # Pivot for warehouse qty
    warehouse_qty_columns = ", ".join([
        f"""SUM(CASE WHEN b.warehouse = '{wh}' THEN b.actual_qty ELSE 0 END) AS `{wh.lower().replace(" ", "_").replace("-", "_")}`"""
        for wh in warehouses
    ])

    # 🔥 Important fix → aggregate tabBin stock before joining (no duplication)
    query = f"""
        SELECT
            sii.item_code,
            i.item_name,
            i.item_group,

            SUM(sii.amount) AS total_amount,
            SUM(sii.qty) AS total_qty,

            {warehouse_qty_columns},

            COALESCE(i.safety_stock, 0) AS safety_stock,
            GREATEST(COALESCE(i.safety_stock, 0) -
                     SUM(COALESCE(b.actual_qty, 0)), 0) AS shortage_qty

        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        JOIN `tabItem` i ON i.name = sii.item_code
        LEFT JOIN (
            SELECT item_code, warehouse, SUM(actual_qty) AS actual_qty
            FROM `tabBin`
            GROUP BY item_code, warehouse
        ) b ON b.item_code = i.name

        WHERE 1 = 1
        {conditions}

        GROUP BY sii.item_code
        ORDER BY total_amount DESC
        LIMIT 100
    """

    return frappe.db.sql(query, params, as_dict=True)
