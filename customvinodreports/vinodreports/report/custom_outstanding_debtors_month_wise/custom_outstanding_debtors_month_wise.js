frappe.query_reports["Custom Outstanding Debtors Month-wise"] = {
    formatter: function(value, row, column, data, default_formatter) {
        // Drill down on clicking Total Outstanding
        if (column.fieldname === "total_outstanding" && data.month) {
            value = `<a href="javascript:frappe.query_report.set_filter_value('month', '${data.month}')">${value}</a>`;
            return value;
        }
        return default_formatter(value, row, column, data);
    },

    filters: [
        {
            fieldname: "month",
            label: "Month",
            fieldtype: "Data",
            hidden: 1
        }
    ]
};
