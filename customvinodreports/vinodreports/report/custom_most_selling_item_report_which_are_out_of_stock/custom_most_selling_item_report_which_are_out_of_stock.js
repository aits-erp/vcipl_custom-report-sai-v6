frappe.query_reports["Custom Most selling item report which are out of stock"] = {
    filters: [
        
        {
            fieldname: "item_group",
            label: __("Item Group"),
            fieldtype: "Link",
            options: "Item Group",
            reqd: 0
        }
    ]
};
