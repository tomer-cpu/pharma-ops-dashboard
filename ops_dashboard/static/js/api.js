class ApiClient {
    constructor() {
        this.baseUrl = window.location.origin;
        this.cache = new Map();
        this.cacheTTL = 25000;
    }

    async get(endpoint, params = {}) {
        const url = new URL(`${this.baseUrl}${endpoint}`);
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') {
                url.searchParams.set(k, v);
            }
        });

        const cacheKey = url.toString();
        const cached = this.cache.get(cacheKey);
        if (cached && Date.now() - cached.time < this.cacheTTL) {
            return cached.data;
        }

        const response = await fetch(url);
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        const data = await response.json();
        this.cache.set(cacheKey, { data, time: Date.now() });
        return data;
    }

    async put(endpoint, body) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        return response.json();
    }

    async post(endpoint, body) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `API error: ${response.status}`);
        }
        return response.json();
    }

    async delete(endpoint) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        return response.json();
    }

    clearCache() {
        this.cache.clear();
    }

    // ── Summary / Dashboard ──────────────────────────────────────
    getDashboardSummary(params) { return this.get('/api/summary/dashboard', params); }
    getHealthScore(params) { return this.get('/api/summary/health-score', params); }
    getAlerts(params) { return this.get('/api/summary/alerts', params); }

    // ── Quality (9 KPIs) ─────────────────────────────────────────
    getQualityKPIs(params) { return this.get('/api/quality/kpis', params); }
    getBatchRejections(params) { return this.get('/api/quality/batch-rejections', params); }
    getYieldBySite(params) { return this.get('/api/quality/yield-by-site', params); }
    getComplianceBreakdown(params) { return this.get('/api/quality/compliance-breakdown', params); }
    getDeviationTrend(params) { return this.get('/api/quality/deviation-trend', params); }
    getRftTrend(params) { return this.get('/api/quality/rft-trend', params); }
    getCapaTrend(params) { return this.get('/api/quality/capa-trend', params); }

    // ── Service (11 KPIs) ────────────────────────────────────────
    getServiceKPIs(params) { return this.get('/api/service/kpis', params); }
    getSupplyDemand(params) { return this.get('/api/service/supply-demand', params); }
    getOtifTrend(params) { return this.get('/api/service/otif-trend', params); }
    getLeadTimeTrend(params) { return this.get('/api/service/lead-time-trend', params); }
    getSlaTrend(params) { return this.get('/api/service/sla-trend', params); }
    getResponseTimeDist(params) { return this.get('/api/service/response-time-distribution', params); }
    getLeadTimeBySite(params) { return this.get('/api/service/lead-time-by-site', params); }
    getScheduleTrend(params) { return this.get('/api/service/schedule-trend', params); }
    getBackorderTrend(params) { return this.get('/api/service/backorder-trend', params); }
    getCapacityTrend(params) { return this.get('/api/service/capacity-trend', params); }

    // ── Cost (7 KPIs) ────────────────────────────────────────────
    getCostKPIs(params) { return this.get('/api/cost/kpis', params); }
    getWasteTrend(params) { return this.get('/api/cost/waste-trend', params); }
    getCostPerBatchTrend(params) { return this.get('/api/cost/cost-per-batch-trend', params); }
    getInventoryTrend(params) { return this.get('/api/cost/inventory-trend', params); }
    getCostBreakdown(params) { return this.get('/api/cost/breakdown', params); }
    getReworkTrend(params) { return this.get('/api/cost/rework-trend', params); }
    getCopqTrend(params) { return this.get('/api/cost/copq-trend', params); }
    getVarianceTrend(params) { return this.get('/api/cost/variance-trend', params); }

    // ── Efficiency (4 KPIs) ──────────────────────────────────────
    getEfficiencyKPIs(params) { return this.get('/api/efficiency/kpis', params); }
    getOeeTrend(params) { return this.get('/api/efficiency/oee-trend', params); }
    getDowntimeTrend(params) { return this.get('/api/efficiency/downtime-trend', params); }
    getOeeBySite(params) { return this.get('/api/efficiency/oee-by-site', params); }

    // ── Risk (4 KPIs) ────────────────────────────────────────────
    getRiskKPIs(params) { return this.get('/api/risk/kpis', params); }
    getSupplierRiskTrend(params) { return this.get('/api/risk/supplier-trend', params); }
    getRiskHeatmap(params) { return this.get('/api/risk/risk-heatmap', params); }

    // ── Filters ──────────────────────────────────────────────────
    getFilterOptions() { return this.get('/api/filters/options'); }

    // ── Settings ─────────────────────────────────────────────────
    getTargets() { return this.get('/api/settings/targets'); }
    updateTargets(updates) { return this.put('/api/settings/targets', updates); }
    getSites() { return this.get('/api/settings/sites'); }
    addSite(data) { return this.post('/api/settings/sites', data); }
    updateSite(name, data) { return this.put(`/api/settings/sites/${encodeURIComponent(name)}`, data); }
    deleteSite(name) { return this.delete(`/api/settings/sites/${encodeURIComponent(name)}`); }
    getProductLines() { return this.get('/api/settings/product-lines'); }
    addProductLine(data) { return this.post('/api/settings/product-lines', data); }
    deleteProductLine(name) { return this.delete(`/api/settings/product-lines/${encodeURIComponent(name)}`); }
    generateData(data) { return this.post('/api/settings/generate-data', data); }
}

const api = new ApiClient();
