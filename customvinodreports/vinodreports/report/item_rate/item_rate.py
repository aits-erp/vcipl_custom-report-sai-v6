import frappe

def execute(filters=None):
    data = frappe.db.sql("""
        SELECT
            i.item_code,
            i.item_name,
            DATE_FORMAT(sle.posting_date, '%%d-%%m-%%Y') AS latest_posting_date,
            FORMAT(sle.incoming_rate, 2) AS latest_incoming_rate,
            FORMAT(lci.applicable_charges, 2) AS latest_lcv
        FROM `tabItem` i

        /* Latest Incoming Rate from Stock Ledger Entry */
        LEFT JOIN `tabStock Ledger Entry` sle
            ON sle.name = (
                SELECT s2.name
                FROM `tabStock Ledger Entry` s2
                WHERE s2.item_code = i.item_code
                  AND s2.incoming_rate > 0
                ORDER BY s2.posting_date DESC, s2.posting_time DESC, s2.creation DESC
                LIMIT 1
            )

        /* Latest LCV from Landed Cost Voucher */
        LEFT JOIN `tabLanded Cost Item` lci
            ON lci.item_code = i.item_code
            AND lci.parent = (
                SELECT lcv2.name
                FROM `tabLanded Cost Voucher` lcv2
                JOIN `tabLanded Cost Item` lci2
                    ON lci2.parent = lcv2.name
                WHERE lci2.item_code = i.item_code
                  AND lcv2.docstatus = 1
                ORDER BY lcv2.posting_date DESC, lcv2.creation DESC
                LIMIT 1
            )

        ORDER BY i.item_code;
    """, as_dict=True)

    columns = [
        {"label": "Item Code", "fieldname": "item_code", "fieldtype": "Data", "width": 160},
        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 260},
        {"label": "Latest Incoming Date", "fieldname": "latest_posting_date", "fieldtype": "Data", "width": 140},
        {"label": "Latest Incoming Rate", "fieldname": "latest_incoming_rate", "fieldtype": "Currency", "width": 150},
        {"label": "Latest LCV", "fieldname": "latest_lcv", "fieldtype": "Currency", "width": 150},
    ]

    return columns, data
