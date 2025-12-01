# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub
from frappe.query_builder import DocType
from frappe.query_builder.functions import IfNull
from frappe.utils import add_days, add_to_date, flt, getdate

from erpnext.accounts.utils import get_fiscal_year


def execute(filters=None):
    return Analytics(filters).run()


class Analytics:
    def __init__(self, filters=None):
        self.filters = frappe._dict(filters or {})
        self.date_field = (
            "transaction_date"
            if self.filters.doc_type in ["Sales Order", "Purchase Order"]
            else "posting_date"
        )
        self.months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        self.get_period_date_ranges()

    def update_company_list_for_parent_company(self):
        company_list = [self.filters.get("company")]

        selected_company = self.filters.get("company")
        if (
            selected_company
            and self.filters.get("show_aggregate_value_from_subsidiary_companies")
            and frappe.db.get_value("Company", selected_company, "is_group")
        ):
            lft, rgt = frappe.db.get_value("Company", selected_company, ["lft", "rgt"])
            child_companies = frappe.db.get_list(
                "Company", filters={"lft": [">", lft], "rgt": ["<", rgt]}, pluck="name"
            )

            company_list.extend(child_companies)

        self.filters["company"] = company_list

    def run(self):
        self.update_company_list_for_parent_company()
        self.get_columns()
        self.get_data()
        self.get_chart_data()

        # Show total row at the bottom (user requested final total)
        skip_total_row = 0

        return self.columns, self.data, None, self.chart, None, skip_total_row

    # ----------------------------------------------------------------------
    # COLUMN SETUP
    # ----------------------------------------------------------------------

    def get_columns(self):
        self.columns = [
            {
                "label": _(self.filters.tree_type),
                "options": self.filters.tree_type if self.filters.tree_type != "Order Type" else "",
                "fieldname": "entity",
                "fieldtype": "Link" if self.filters.tree_type != "Order Type" else "Data",
                "width": 140 if self.filters.tree_type != "Order Type" else 200,
            }
        ]

        # Extra name column only for pure Customer / Supplier / Item trees
        if self.filters.tree_type in ["Customer", "Supplier", "Item"]:
            self.columns.append(
                {
                    "label": _(self.filters.tree_type + " Name"),
                    "fieldname": "entity_name",
                    "fieldtype": "Data",
                    "width": 140,
                }
            )

        if self.filters.tree_type == "Item":
            self.columns.append(
                {
                    "label": _("UOM"),
                    "fieldname": "stock_uom",
                    "fieldtype": "Link",
                    "options": "UOM",
                    "width": 100,
                }
            )

        for end_date in self.periodic_daterange:
            period = self.get_period(end_date)
            self.columns.append(
                {"label": _(period), "fieldname": scrub(period), "fieldtype": "Float", "width": 120}
            )

        self.columns.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Float", "width": 120})

    # ----------------------------------------------------------------------
    # DATA FETCH
    # ----------------------------------------------------------------------

    def get_data(self):
        if self.filters.tree_type in ["Customer", "Supplier"]:
            # Customer: supports custom_sub_group via Customer doctypes
            self.get_sales_transactions_based_on_customers_or_suppliers()
            self.get_rows_for_customer_or_supplier()

        elif self.filters.tree_type == "Item":
            self.get_sales_transactions_based_on_items()
            self.get_rows()

        elif self.filters.tree_type in ["Customer Group", "Supplier Group", "Territory"]:
            self.get_sales_transactions_based_on_customer_or_territory_group()
            self.get_rows_by_group()

        elif self.filters.tree_type == "Item Group":
            self.get_sales_transactions_based_on_item_group()
            self.get_rows_by_group()

        elif self.filters.tree_type == "Order Type":
            if self.filters.doc_type != "Sales Order":
                self.data = []
                return
            self.get_sales_transactions_based_on_order_type()
            self.get_rows_by_group()

        elif self.filters.tree_type == "Project":
            self.get_sales_transactions_based_on_project()
            self.get_rows()

    # ----------------------------------------------------------------------
    # ORIGINAL / BASE QUERIES
    # ----------------------------------------------------------------------

    def get_sales_transactions_based_on_order_type(self):
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_total"
        else:
            value_field = "total_qty"

        doctype = DocType(self.filters.doc_type)

        self.entries = (
            frappe.qb.from_(doctype)
            .select(
                doctype.order_type.as_("entity"),
                doctype[self.date_field],
                doctype[value_field].as_("value_field"),
            )
            .where(
                (doctype.docstatus == 1)
                & (doctype.company.isin(self.filters.company))
                & (doctype[self.date_field].between(self.filters.from_date, self.filters.to_date))
                & (IfNull(doctype.order_type, "") != "")
            )
            .orderby(doctype.order_type)
        ).run(as_dict=True)

        self.get_teams()

    def get_sales_transactions_based_on_customers_or_suppliers(self):
        """
        Supports:
        - Supplier (original behaviour)
        - Customer with sub-groups (new: join Customer to fetch custom_sub_group)
        """
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_total"
        else:
            value_field = "total_qty"

        # Supplier path (unchanged)
        if self.filters.tree_type == "Supplier":
            entity = "supplier as entity"
            entity_name = "supplier_name as entity_name"
            filters = {
                "docstatus": 1,
                "company": ["in", self.filters.company],
                self.date_field: ("between", [self.filters.from_date, self.filters.to_date]),
            }
            if self.filters.doc_type in ["Sales Invoice", "Purchase Invoice", "Payment Entry"]:
                filters.update({"is_opening": "No"})

            self.entries = frappe.get_all(
                self.filters.doc_type,
                fields=[entity, entity_name, f"{value_field} as value_field", self.date_field],
                filters=filters,
            )

            # entity name map
            self.entity_names = {}
            for d in self.entries:
                self.entity_names.setdefault(d.entity, d.get("entity_name"))

            return

        # Customer path (tree_type == "Customer")
        if self.filters.tree_type == "Customer":
            if self.filters["value_quantity"] == "Value":
                value_field_doc = "base_net_total"
            else:
                value_field_doc = "total_qty"

            doctype = DocType(self.filters.doc_type)
            customer = DocType("Customer")

            entries = (
                frappe.qb.from_(doctype)
                .join(customer)
                .on(doctype.customer == customer.name)
                .select(
                    doctype.customer.as_("customer"),
                    customer.customer_name.as_("customer_name"),
                    customer.custom_sub_group.as_("custom_sub_group"),
                    doctype[value_field_doc].as_("value_field"),
                    doctype[self.date_field],
                )
                .where(
                    (doctype.docstatus == 1)
                    & (doctype.company.isin(self.filters.company))
                    & (doctype[self.date_field].between(self.filters.from_date, self.filters.to_date))
                )
            ).run(as_dict=True)

            self.entries = []
            self.sub_group_map = {}
            self.entity_names = {}

            for e in entries:
                cust = e.get("customer") or ""
                cname = e.get("customer_name") or ""
                sg = e.get("custom_sub_group") or None

                # save customer display name
                if cust:
                    self.entity_names.setdefault(cust, cname)

                if sg:
                    node = f"{cust}::SUB::{sg}"
                    self.sub_group_map.setdefault(cust, set()).add(sg)
                else:
                    node = cust

                self.entries.append(
                    {
                        "entity": node,
                        "value_field": e.get("value_field") or 0.0,
                        self.date_field: e.get(self.date_field),
                    }
                )

            # Ordered customer list (for stable output)
            self.customer_list = frappe.db.get_all(
                "Customer",
                filters={"name": ["in", list(self.entity_names.keys())]},
                fields=["name", "customer_name"],
                order_by="name",
            )
            return

    def get_sales_transactions_based_on_items(self):
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_amount"
        else:
            value_field = "stock_qty"

        doctype = DocType(self.filters.doc_type)
        doctype_item = DocType(f"{self.filters.doc_type} Item")

        self.entries = (
            frappe.qb.from_(doctype_item)
            .join(doctype)
            .on(doctype.name == doctype_item.parent)
            .select(
                doctype_item.item_code.as_("entity"),
                doctype_item.item_name.as_("entity_name"),
                doctype_item.stock_uom,
                doctype_item[value_field].as_("value_field"),
                doctype[self.date_field],
            )
            .where(
                (doctype_item.docstatus == 1)
                & (doctype.company.isin(self.filters.company))
                & (doctype[self.date_field].between(self.filters.from_date, self.filters.to_date))
            )
        ).run(as_dict=True)

        self.entity_names = {}
        for d in self.entries:
            self.entity_names.setdefault(d.entity, d.entity_name)

    # ----------------------------------------------------------------------
    # CUSTOMER GROUP / TERRITORY / SUPPLIER GROUP LOGIC
    # ----------------------------------------------------------------------

    def get_sales_transactions_based_on_customer_or_territory_group(self):
        """
        For Customer Group we join Customer to fetch:
        - customer_group (Parent group)
        - custom_sub_group (User-defined subgroup)
        - customer / customer_name (for 3rd level)
        and then build hierarchy:
        Customer Group -> Sub Group -> Customer
        """

        if self.filters["value_quantity"] == "Value":
            value_field_expr = "base_net_total"
        else:
            value_field_expr = "total_qty"

        # ---------------- CUSTOMER GROUP (with subgroup + customer) ---------------
        if self.filters.tree_type == "Customer Group":
            doctype = DocType(self.filters.doc_type)
            customer = DocType("Customer")

            entries = (
                frappe.qb.from_(doctype)
                .join(customer)
                .on(doctype.customer == customer.name)
                .select(
                    customer.customer_group.as_("entity_group"),
                    customer.custom_sub_group.as_("custom_sub_group"),
                    customer.name.as_("customer"),
                    customer.customer_name.as_("customer_name"),
                    doctype[value_field_expr].as_("value_field"),
                    doctype[self.date_field],
                )
                .where(
                    (doctype.docstatus == 1)
                    & (doctype.company.isin(self.filters.company))
                    & (doctype[self.date_field].between(self.filters.from_date, self.filters.to_date))
                )
            ).run(as_dict=True)

            # normalised structures
            self.entries = []
            self.sub_group_map = {}
            self.customer_map = {}      # key: subgroup node, value: set(customer)
            self.customer_labels = {}   # key: customer, value: "CUST-001 - Name"

            for e in entries:
                grp = e.get("entity_group") or ""
                sg = e.get("custom_sub_group") or None
                cust = e.get("customer")
                cname = e.get("customer_name") or ""

                # determine node (group or group::SUB::subgroup)
                if sg:
                    node = f"{grp}::SUB::{sg}"
                    self.sub_group_map.setdefault(grp, set()).add(sg)
                else:
                    node = grp

                # store row
                self.entries.append(
                    {
                        "entity": node,
                        "customer": cust,
                        "customer_name": cname,
                        self.date_field: e.get(self.date_field),
                        "value_field": e.get("value_field") or 0.0,
                    }
                )

                # customer per subgroup node
                if cust:
                    self.customer_map.setdefault(node, set()).add(cust)
                    # label: CUST-001 – Alfa Traders Pvt Ltd
                    label = cust
                    if cname:
                        label = f"{cust} - {cname}"
                    self.customer_labels[cust] = label

            # load all groups / depth_map
            self.get_groups()
            return

        # ---------------- OTHER TREE TYPES (original behaviour) ---------------
        if self.filters.tree_type == "Supplier Group":
            entity_field = "supplier as entity"
            self.get_supplier_parent_child_map()
        else:
            entity_field = "territory as entity"

        filters = {
            "docstatus": 1,
            "company": ["in", self.filters.company],
            self.date_field: ("between", [self.filters.from_date, self.filters.to_date]),
        }

        if self.filters.doc_type in ["Sales Invoice", "Purchase Invoice", "Payment Entry"]:
            filters.update({"is_opening": "No"})

        self.entries = frappe.get_all(
            self.filters.doc_type,
            fields=[entity_field, f"{value_field_expr} as value_field", self.date_field],
            filters=filters,
        )
        self.get_groups()

    def get_sales_transactions_based_on_item_group(self):
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_amount"
        else:
            value_field = "qty"

        doctype = DocType(self.filters.doc_type)
        doctype_item = DocType(f"{self.filters.doc_type} Item")

        self.entries = (
            frappe.qb.from_(doctype_item)
            .join(doctype)
            .on(doctype.name == doctype_item.parent)
            .select(
                doctype_item.item_group.as_("entity"),
                doctype_item[value_field].as_("value_field"),
                doctype[self.date_field],
            )
            .where(
                (doctype_item.docstatus == 1)
                & (doctype.company.isin(self.filters.company))
                & (doctype[self.date_field].between(self.filters.from_date, self.filters.to_date))
            )
        ).run(as_dict=True)

        self.get_groups()

    def get_sales_transactions_based_on_project(self):
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_total as value_field"
        else:
            value_field = "total_qty as value_field"

        entity = "project as entity"

        filters = {
            "docstatus": 1,
            "company": ["in", self.filters.company],
            "project": ["!=", ""],
            self.date_field: ("between", [self.filters.from_date, self.filters.to_date]),
        }

        if self.filters.doc_type in ["Sales Invoice", "Purchase Invoice", "Payment Entry"]:
            filters.update({"is_opening": "No"})

        self.entries = frappe.get_all(
            self.filters.doc_type, fields=[entity, value_field, self.date_field], filters=filters
        )

    # ----------------------------------------------------------------------
    # ROW BUILDING
    # ----------------------------------------------------------------------

    def get_rows_for_customer_or_supplier(self):
        """
        Handles Customer tree_type (with subgroups) and Supplier standard behaviour.
        """
        self.get_periodic_data()
        data = []

        # Customer tree: parent is Customer, child is its subgroups
        if self.filters.tree_type == "Customer":
            # iterate customers in deterministic order
            if hasattr(self, "customer_list") and self.customer_list:
                customer_iter = self.customer_list
            else:
                customer_iter = [
                    {"name": k, "customer_name": self.entity_names.get(k)}
                    for k in sorted(self.entity_names.keys())
                ]

            for c in customer_iter:
                cust = c.get("name")
                cname = c.get("customer_name")

                # parent customer row
                row = {"entity": cust, "entity_name": cname}
                total = 0.0
                for end_date in self.periodic_daterange:
                    period = self.get_period(end_date)
                    amount = flt(self.entity_periodic_data.get(cust, {}).get(period, 0.0))
                    row[scrub(period)] = amount
                    total += amount
                row["total"] = total
                data.append(row)

                # subgroups
                subgroups = sorted(list(self.sub_group_map.get(cust, []))) if hasattr(self, "sub_group_map") else []
                for sg in subgroups:
                    node = f"{cust}::SUB::{sg}"
                    row_sg = {"entity": node, "entity_name": None, "indent": 1}
                    total_sg = 0.0
                    for end_date in self.periodic_daterange:
                        period = self.get_period(end_date)
                        val = flt(self.entity_periodic_data.get(node, {}).get(period, 0.0))
                        row_sg[scrub(period)] = val
                        total_sg += val
                    row_sg["total"] = total_sg
                    data.append(row_sg)

            self.data = data
            return

        # Supplier tree (simple list)
        self.get_rows()

    def get_rows(self):
        self.data = []
        self.get_periodic_data()

        for entity, period_data in self.entity_periodic_data.items():
            row = {
                "entity": entity,
                "entity_name": self.entity_names.get(entity) if hasattr(self, "entity_names") else None,
            }
            total = 0
            for end_date in self.periodic_daterange:
                period = self.get_period(end_date)
                amount = flt(period_data.get(period, 0.0))
                row[scrub(period)] = amount
                total += amount

            row["total"] = total

            if self.filters.tree_type == "Item":
                row["stock_uom"] = period_data.get("stock_uom")

            self.data.append(row)

    def get_rows_by_group(self):
        # Build periodic data first
        self.get_periodic_data()

        # For Customer Group tree, roll up subgroup totals into parent groups
        if self.filters.tree_type == "Customer Group":
            self.rollup_subgroups_to_parent()

        out = []

        # IMPORTANT: iterate from leaves to root so that parent totals include children
        for d in reversed(self.group_entries):
            gname = d.name
            block = []  # rows that belong to this group (group + subgroups + customers)

            # ---------------- GROUP ROW ----------------
            row = {"entity": gname, "indent": self.depth_map.get(gname)}
            total = 0.0
            for end_date in self.periodic_daterange:
                period = self.get_period(end_date)
                amount = flt(self.entity_periodic_data.get(gname, {}).get(period, 0.0))
                row[scrub(period)] = amount

                # aggregate value into parent (original behaviour)
                if d.parent and (self.filters.tree_type != "Order Type" or d.parent == "Order Types"):
                    self.entity_periodic_data.setdefault(d.parent, frappe._dict()).setdefault(period, 0.0)
                    self.entity_periodic_data[d.parent][period] += amount

                total += amount

            row["total"] = total
            block.append(row)

            # ---------------- CUSTOMER GROUP SPECIAL: SUBGROUP + CUSTOMER ROWS -------------
            if self.filters.tree_type == "Customer Group":
                base_indent = (self.depth_map.get(gname) or 0)

                # SUBGROUP rows (direct children of this group)
                subgroups = sorted(list(self.sub_group_map.get(gname, []))) if hasattr(self, "sub_group_map") else []
                for sg in subgroups:
                    node = f"{gname}::SUB::{sg}"
                    row_sg = {"entity": node, "indent": base_indent + 1}
                    total_sg = 0.0
                    for end_date in self.periodic_daterange:
                        period = self.get_period(end_date)
                        val = flt(self.entity_periodic_data.get(node, {}).get(period, 0.0))
                        row_sg[scrub(period)] = val
                        total_sg += val
                    row_sg["total"] = total_sg
                    block.append(row_sg)

                    # CUSTOMER rows under this subgroup
                    customers = (
                        sorted(list(self.customer_map.get(node, [])))
                        if hasattr(self, "customer_map")
                        else []
                    )
                    for cust in customers:
                        label = self.customer_labels.get(cust, cust)
                        row_c = {
                            "entity": label,  # "CUST-001 - Alfa Traders Pvt Ltd"
                            "indent": base_indent + 2,
                        }
                        total_c = 0.0
                        for end_date in self.periodic_daterange:
                            period = self.get_period(end_date)
                            v = flt(self.entity_periodic_data.get(cust, {}).get(period, 0.0))
                            row_c[scrub(period)] = v
                            total_c += v
                        row_c["total"] = total_c
                        block.append(row_c)

            # prepend this block so that parent appears above all its descendants
            out = block + out

        self.data = out

    # ----------------------------------------------------------------------
    # PERIODIC DATA
    # ----------------------------------------------------------------------

    def get_periodic_data(self):
        self.entity_periodic_data = frappe._dict()

        for d in self.entries:
            # Supplier Group mapping
            if self.filters.tree_type == "Supplier Group":
                d["entity"] = self.parent_child_map.get(d.get("entity"))

            entity = d.get("entity")
            if not entity:
                continue

            raw_date = d.get(self.date_field)
            if not raw_date:
                continue

            period = self.get_period(raw_date)

            # base entity (group / subgroup / item / customer / project etc.)
            self.entity_periodic_data.setdefault(entity, frappe._dict()).setdefault(period, 0.0)
            self.entity_periodic_data[entity][period] += flt(d.get("value_field") or 0.0)

            # ITEM extra data
            if self.filters.tree_type == "Item":
                self.entity_periodic_data[entity]["stock_uom"] = d.get("stock_uom")

            # CUSTOMER GROUP: maintain customer-level totals for 3rd level
            if self.filters.tree_type == "Customer Group":
                cust = d.get("customer")
                if cust:
                    self.entity_periodic_data.setdefault(cust, frappe._dict()).setdefault(period, 0.0)
                    self.entity_periodic_data[cust][period] += flt(d.get("value_field") or 0.0)

    # ----------------------------------------------------------------------
    # PERIOD / DATE RANGE
    # ----------------------------------------------------------------------

    def get_period(self, posting_date):
        if self.filters.range == "Weekly":
            period = _("Week {0} {1}").format(str(posting_date.isocalendar()[1]), str(posting_date.year))
        elif self.filters.range == "Monthly":
            period = _(str(self.months[posting_date.month - 1])) + " " + str(posting_date.year)
        elif self.filters.range == "Quarterly":
            period = _("Quarter {0} {1}").format(
                str(((posting_date.month - 1) // 3) + 1), str(posting_date.year)
            )
        else:
            year = get_fiscal_year(posting_date, company=self.filters.company[0])
            period = str(year[0])
        return period

    def get_period_date_ranges(self):
        from dateutil.relativedelta import MO, relativedelta

        from_date, to_date = getdate(self.filters.from_date), getdate(self.filters.to_date)

        increment = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Yearly": 12}.get(self.filters.range, 1)

        if self.filters.range in ["Monthly", "Quarterly"]:
            from_date = from_date.replace(day=1)
        elif self.filters.range == "Yearly":
            from_date = get_fiscal_year(from_date)[1]
        else:
            from_date = from_date + relativedelta(from_date, weekday=MO(-1))

        self.periodic_daterange = []
        for _dummy in range(1, 53):
            if self.filters.range == "Weekly":
                period_end_date = add_days(from_date, 6)
            else:
                period_end_date = add_to_date(from_date, months=increment, days=-1)

            if period_end_date > to_date:
                period_end_date = to_date

            self.periodic_daterange.append(period_end_date)

            from_date = add_days(period_end_date, 1)
            if period_end_date == to_date:
                break

    # ----------------------------------------------------------------------
    # GROUP & TREE HELPERS
    # ----------------------------------------------------------------------

    def get_groups(self):
        if self.filters.tree_type == "Territory":
            parent = "parent_territory"
        if self.filters.tree_type == "Customer Group":
            parent = "parent_customer_group"
        if self.filters.tree_type == "Item Group":
            parent = "parent_item_group"
        if self.filters.tree_type == "Supplier Group":
            parent = "parent_supplier_group"

        self.depth_map = frappe._dict()

        self.group_entries = frappe.db.sql(
            f"""select name, lft, rgt , {parent} as parent
            from `tab{self.filters.tree_type}` order by lft""",
            as_dict=1,
        )

        for d in self.group_entries:
            if d.parent:
                self.depth_map.setdefault(d.name, self.depth_map.get(d.parent) + 1)
            else:
                self.depth_map.setdefault(d.name, 0)

    def get_teams(self):
        self.depth_map = frappe._dict()

        self.group_entries = frappe.db.sql(
            f""" select * from (select "Order Types" as name, 0 as lft,
            2 as rgt, '' as parent union select distinct order_type as name, 1 as lft, 1 as rgt, "Order Types" as parent
            from `tab{self.filters.doc_type}` where ifnull(order_type, '') != '') as b order by lft, name
        """,
            as_dict=1,
        )

        for d in self.group_entries:
            if d.parent:
                self.depth_map.setdefault(d.name, self.depth_map.get(d.parent) + 1)
            else:
                self.depth_map.setdefault(d.name, 0)

    def get_supplier_parent_child_map(self):
        self.parent_child_map = frappe._dict(
            frappe.db.sql(""" select name, supplier_group from `tabSupplier`""")
        )

    def rollup_subgroups_to_parent(self):
        """
        After entity_periodic_data is built, roll-up subgroup values into their parent.
        Subgroup node names follow the pattern: "<Parent>::SUB::<SubGroup>"
        """
        if not hasattr(self, "sub_group_map"):
            return

        for parent, sgs in self.sub_group_map.items():
            self.entity_periodic_data.setdefault(parent, frappe._dict())
            for sg in sgs:
                node = f"{parent}::SUB::{sg}"
                for d in self.periodic_daterange:
                    lbl = self.get_period(d)
                    val = flt(self.entity_periodic_data.get(node, {}).get(lbl, 0.0))
                    self.entity_periodic_data[parent].setdefault(lbl, 0.0)
                    self.entity_periodic_data[parent][lbl] += val
                    self.entity_periodic_data[parent].setdefault("total", 0.0)
                    self.entity_periodic_data[parent]["total"] += val

    # ----------------------------------------------------------------------
    # CHART
    # ----------------------------------------------------------------------

    def get_chart_data(self):
        length = len(self.columns)

        if self.filters.tree_type in ["Customer", "Supplier"]:
            labels = [d.get("label") for d in self.columns[2 : length - 1]]
        elif self.filters.tree_type == "Item":
            labels = [d.get("label") for d in self.columns[3 : length - 1]]
        else:
            labels = [d.get("label") for d in self.columns[1 : length - 1]]
        self.chart = {"data": {"labels": labels, "datasets": []}, "type": "line"}

        if self.filters["value_quantity"] == "Value":
            self.chart["fieldtype"] = "Currency"
        else:
            self.chart["fieldtype"] = "Float"
