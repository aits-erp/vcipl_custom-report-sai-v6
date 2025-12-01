frappe.query_reports["Custom Most selling item report which are out of stock"] = {
    onload: function(report) {
        report.set_filter_value("custom_item_type", "Finished Goods");   // default value
    },
    filters: [
        {
            fieldname: "custom_item_type",
            label: __("Item Type"),
            fieldtype: "Data",
            default: "Finished Goods",
            reqd: 0
        }
    ]
};
