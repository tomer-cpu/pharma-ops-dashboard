class FilterManager {
    constructor() {
        this.state = {
            site: null,
            product_line: null,
            time_range: '30d',
            date_from: null,
            date_to: null,
        };
        this.onChangeCallbacks = [];
    }

    async initialize() {
        const options = await api.getFilterOptions();

        // Populate site dropdown
        const siteSelect = document.getElementById('filter-site');
        if (siteSelect && options.sites) {
            siteSelect.innerHTML = '<option value="">All Sites</option>';
            options.sites.forEach(s => {
                siteSelect.innerHTML += `<option value="${s}">${s}</option>`;
            });
        }

        // Populate product line dropdown
        const prodSelect = document.getElementById('filter-product');
        if (prodSelect && options.product_lines) {
            prodSelect.innerHTML = '<option value="">All Products</option>';
            options.product_lines.forEach(p => {
                prodSelect.innerHTML += `<option value="${p}">${p}</option>`;
            });
        }

        // Time range buttons
        document.querySelectorAll('[data-range]').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.state.time_range = btn.dataset.range;
                this.state.date_from = null;
                this.state.date_to = null;
                this._triggerChange();
            });
        });

        // Custom date inputs
        const dateFrom = document.getElementById('filter-date-from');
        const dateTo = document.getElementById('filter-date-to');
        if (dateFrom && dateTo) {
            const onChange = () => {
                if (dateFrom.value && dateTo.value) {
                    this.state.date_from = dateFrom.value;
                    this.state.date_to = dateTo.value;
                    this.state.time_range = null;
                    document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
                    this._triggerChange();
                }
            };
            dateFrom.addEventListener('change', onChange);
            dateTo.addEventListener('change', onChange);
        }

        // Dropdowns
        if (siteSelect) {
            siteSelect.addEventListener('change', () => {
                this.state.site = siteSelect.value || null;
                this._triggerChange();
            });
        }
        if (prodSelect) {
            prodSelect.addEventListener('change', () => {
                this.state.product_line = prodSelect.value || null;
                this._triggerChange();
            });
        }
    }

    getParams() {
        const params = {};
        if (this.state.site) params.site = this.state.site;
        if (this.state.product_line) params.product_line = this.state.product_line;
        if (this.state.date_from && this.state.date_to) {
            params.date_from = this.state.date_from;
            params.date_to = this.state.date_to;
        } else if (this.state.time_range) {
            params.time_range = this.state.time_range;
        }
        return params;
    }

    onChange(callback) {
        this.onChangeCallbacks.push(callback);
    }

    _triggerChange() {
        api.clearCache();
        this.onChangeCallbacks.forEach(cb => cb());
    }
}
