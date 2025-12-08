import frappe

def execute(filters=None):
    if not filters:
        filters = {}

    # If user clicked a month → show invoice details
    if filters.get("due_month"):
        return get_invoice_details(filters.get("due_month"))

    # Show month summary
    return get_month_summary()


# ------------------------------------------------------------
# 1. SUMMARY VIEW (Month-wise Outstanding)
# ------------------------------------------------------------
def get_month_summary():
    rows = frappe.db.sql("""
        SELECT
            DATE_FORMAT(si.due_date, '%Y-%m') AS due_month,
            SUM(si.outstanding_amount) AS total_outstanding
        FROM `tabSales Invoice` si
        WHERE
              si.docstatus = 1
          AND si.outstanding_amount > 0
          AND si.due_date IS NOT NULL
        GROUP BY due_month
        ORDER BY due_month DESC
    """, as_dict=True)

    data = []
    for r in rows:

        # Clickable month logic
        r["display_month"] = {
            "value": r["due_month"],

            # IMPORTANT: Change report name below EXACT as your report name
            "onclick": (
                "frappe.query_reports['Custom Outstanding Debtors Month-wise']"
                ".set_filter_value('due_month', '{0}')"
            ).format(r["due_month"])
        }

        data.append(r)

    columns = [
        {
            "label": "Due Month",
            "fieldname": "display_month",
            "fieldtype": "Data",
            "width": 160
        },
        {
            "label": "Total Outstanding",
            "fieldname": "total_outstanding",
            "fieldtype": "Currency",
            "width": 180
        },
        # HIDDEN actual filter value
        {
            "label": "Due Month Hidden",
            "fieldname": "due_month",
            "fieldtype": "Data",
            "hidden": 1
        }
    ]

    return columns, data


# ------------------------------------------------------------
# 2. DETAILS VIEW (Invoice list for selected month)
# ------------------------------------------------------------
def get_invoice_details(month):
    data = frappe.db.sql("""
        SELECT
            si.name AS invoice_no,
            si.customer AS customer_code,
            si.customer_name,
            DATEDIFF(CURDATE(), si.due_date) AS days_overdue,
            si.outstanding_amount
        FROM `tabSales Invoice` si
        WHERE
              si.docstatus = 1
          AND si.outstanding_amount > 0
          AND DATE_FORMAT(si.due_date, '%Y-%m') = %s
        ORDER BY si.due_date ASC
    """, (month,), as_dict=True)

    columns = [
        {
            "label": "Invoice",
            "fieldname": "invoice_no",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 150
        },
        {
            "label": "Customer Code",
            "fieldname": "customer_code",
            "fieldtype": "Data",
            "width": 120
        },
        {
            "label": "Customer Name",
            "fieldname": "customer_name",
            "fieldtype": "Data",
            "width": 200
        },
        {
            "label": "Overdue Days",
            "fieldname": "days_overdue",
            "fieldtype": "Int",
            "width": 100
        },
        {
            "label": "Outstanding Amount",
            "fieldname": "outstanding_amount",
            "fieldtype": "Currency",
            "width": 150
        }
    ]

    return columns, data
