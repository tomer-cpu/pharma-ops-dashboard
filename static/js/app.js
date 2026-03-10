let currentTab = 'overview';
let filterManager;
let refreshInterval;

// Helper: conditionally render a chart card only if its metric is enabled
function _cc(enabled, metric, canvasId, title, extraClass) {
    if (!enabled.has(metric)) return '';
    const cls = extraClass ? ' ' + extraClass : '';
    return `<div class="chart-card${cls}"><div class="chart-header"><h3>${title}</h3></div><div class="chart-body"><canvas id="${canvasId}"></canvas></div></div>`;
}

// Helper: build enabled metric names Set from targets array
function _enabledSet(targets) {
    return new Set(targets.filter(t => t.enabled).map(t => t.metric_name));
}

document.addEventListener('DOMContentLoaded', async () => {
    filterManager = new FilterManager();
    await filterManager.initialize();

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;
            loadTab(currentTab);
        });
    });

    // Filter changes reload current tab
    filterManager.onChange(() => loadTab(currentTab));

    // Settings modal
    setupSettingsModal();

    // Initial load
    await loadTab('overview');
    await loadHealthScore();

    // Auto-refresh
    refreshInterval = setInterval(async () => {
        api.clearCache();
        await loadTab(currentTab);
        await loadHealthScore();
        updateTimestamp();
    }, 30000);
});

async function loadTab(tabName) {
    const content = document.getElementById('tab-content');
    const params = filterManager.getParams();

    try {
        content.classList.add('loading');

        switch (tabName) {
            case 'overview': await renderOverviewTab(params); break;
            case 'quality': await renderQualityTab(params); break;
            case 'service': await renderServiceTab(params); break;
            case 'cost': await renderCostTab(params); break;
            case 'efficiency': await renderEfficiencyTab(params); break;
            case 'risk': await renderRiskTab(params); break;
            case 'setup': await renderSetupTab(); break;
        }
    } catch (err) {
        console.error('Error loading tab:', err);
        content.innerHTML = `<div class="error-message">Error loading data. Please try again.</div>`;
    } finally {
        content.classList.remove('loading');
    }
}

// ── OVERVIEW TAB (Overall Score Dashboard) ──────────────────────────

async function renderOverviewTab(params) {
    const [healthData, alerts] = await Promise.all([
        api.getHealthScore(params),
        api.getAlerts(params),
    ]);

    const breakdown = healthData.breakdown || [];
    const categories = ['quality', 'service', 'cost', 'efficiency', 'risk'];

    // Compute category scores
    const catScore = (items) => {
        const tw = items.reduce((s, m) => s + m.weight, 0);
        if (!tw) return 0;
        return items.reduce((s, m) => s + (m.score * m.weight / tw), 0);
    };

    const catScores = {};
    categories.forEach(cat => {
        const items = breakdown.filter(m => m.category === cat);
        catScores[cat] = Math.round(catScore(items));
    });

    const catLabels = { quality: 'Quality', service: 'Service', cost: 'Cost', efficiency: 'Efficiency', risk: 'Risk' };
    const catCssVars = { quality: 'var(--accent-blue)', service: 'var(--accent-purple)', cost: 'var(--accent-amber)', efficiency: 'var(--accent-teal)', risk: 'var(--accent-red)' };

    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <!-- Big Score Hero -->
        <div class="overview-hero">
            <div class="hero-gauge" id="overview-gauge"></div>
            <div class="hero-info">
                <div class="hero-score">${healthData.score}</div>
                <div class="hero-label">${healthData.label}</div>
                <div class="hero-sub">Overall Operational Health Score</div>
            </div>
            <div class="hero-categories">
                ${categories.filter(cat => breakdown.some(m => m.category === cat)).map(cat => `
                <div class="cat-score-card ${cat}">
                    <div class="cat-score-value">${catScores[cat]}</div>
                    <div class="cat-score-label">${catLabels[cat]}</div>
                    <div class="cat-score-bar"><div class="cat-score-fill" style="width:${catScores[cat]}%; background: ${catCssVars[cat]}"></div></div>
                </div>`).join('')}
            </div>
        </div>

        <!-- Metric Breakdown Table -->
        <div class="section-header" style="margin-top:28px">
            <h2>Score Breakdown by Metric</h2>
            <span class="hero-sub" style="font-size:12px; color:var(--text-muted)">Weighted contribution to overall score</span>
        </div>
        <div class="breakdown-table">
            <div class="breakdown-header">
                <span class="bk-col bk-name">Metric</span>
                <span class="bk-col bk-cat">Category</span>
                <span class="bk-col bk-current">Current</span>
                <span class="bk-col bk-target">Target</span>
                <span class="bk-col bk-score">Score</span>
                <span class="bk-col bk-weight">Weight</span>
                <span class="bk-col bk-contrib">Contribution</span>
                <span class="bk-col bk-bar">Performance</span>
            </div>
            ${breakdown.map(m => {
                const statusColor = m.status === 'on_target' ? 'var(--accent-green)' :
                                    m.status === 'warning' ? 'var(--accent-amber)' : 'var(--accent-red)';
                const statusIcon = m.status === 'on_target' ? '&#10003;' :
                                   m.status === 'warning' ? '&#9888;' : '&#10007;';
                return `
                <div class="breakdown-row">
                    <span class="bk-col bk-name">
                        <span class="bk-status-dot" style="background:${statusColor}">${statusIcon}</span>
                        ${m.display_name}
                    </span>
                    <span class="bk-col bk-cat"><span class="section-badge ${m.category}" style="font-size:10px;padding:1px 8px">${m.category}</span></span>
                    <span class="bk-col bk-current">${Formatters.formatValue(m.current_value, m.unit)}</span>
                    <span class="bk-col bk-target">${m.target_direction} ${m.target_value}${m.unit === '$' ? '' : m.unit}</span>
                    <span class="bk-col bk-score" style="color:${statusColor};font-weight:600">${m.score}</span>
                    <span class="bk-col bk-weight">${m.weight}</span>
                    <span class="bk-col bk-contrib" style="font-weight:600">${m.weighted_contribution.toFixed(1)}</span>
                    <span class="bk-col bk-bar">
                        <div class="mini-bar-bg"><div class="mini-bar-fill" style="width:${Math.min(m.score, 100)}%;background:${statusColor}"></div></div>
                    </span>
                </div>`;
            }).join('')}
        </div>

        <!-- Weight Distribution Chart -->
        <div class="charts-grid" style="margin-top:24px">
            <div class="chart-card">
                <div class="chart-header"><h3>Weight Distribution</h3></div>
                <div class="chart-body"><canvas id="chart-weight-dist"></canvas></div>
            </div>
            <div class="chart-card">
                <div class="chart-header"><h3>Score by Metric</h3></div>
                <div class="chart-body"><canvas id="chart-score-bars"></canvas></div>
            </div>
        </div>

        ${alerts.length > 0 ? `
        <div class="section-header">
            <h2>Active Alerts</h2>
            <span class="alert-count">${alerts.length}</span>
        </div>
        <div class="alerts-container" id="overview-alerts"></div>
        ` : ''}
    `;

    // Render big gauge
    renderGauge('overview-gauge', healthData.score, healthData.label);
    renderGauge('health-gauge', healthData.score, healthData.label);

    // Weight distribution donut
    createDonutChart('chart-weight-dist',
        breakdown.map(m => m.display_name),
        breakdown.map(m => m.weight),
        { colors: breakdown.map(m => CAT_COLORS[m.category] || '#64748b') }
    );

    // Score bars
    const scoreColors = breakdown.map(m =>
        m.status === 'on_target' ? '#22c55ecc' : m.status === 'warning' ? '#f59e0bcc' : '#ef4444cc'
    );
    createBarChart('chart-score-bars',
        breakdown.map(m => m.display_name),
        breakdown.map(m => m.score),
        { horizontal: true, colors: scoreColors, unit: '', yMin: 0 }
    );

    if (alerts.length > 0) {
        renderAlerts(document.getElementById('overview-alerts'), alerts);
    }
}

// ── QUALITY TAB ──────────────────────────────────────────────────────

async function renderQualityTab(params) {
    const [kpis, batchTrend, yieldBySite, complianceBreakdown, devTrend, rftTrend, capaTrend, targets] = await Promise.all([
        api.getQualityKPIs(params),
        api.getBatchRejections(params),
        api.getYieldBySite(params),
        api.getComplianceBreakdown(params),
        api.getDeviationTrend(params),
        api.getRftTrend(params),
        api.getCapaTrend(params),
        api.getTargets(),
    ]);

    const enabled = _enabledSet(targets);
    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="kpi-grid" id="quality-kpis"></div>
        <div class="charts-grid">
            ${_cc(enabled, 'batch_rejection_rate', 'chart-batch-rejection', 'Batch Rejection Rate Trend')}
            ${_cc(enabled, 'yield_rate', 'chart-yield-site', 'Yield Rate by Site')}
            ${_cc(enabled, 'deviation_rate', 'chart-deviation', 'Deviation Rate Trend')}
            ${_cc(enabled, 'right_first_time', 'chart-rft', 'Right First Time Trend')}
            ${_cc(enabled, 'capa_closure_time', 'chart-capa', 'CAPA Closure Time Trend')}
            ${_cc(enabled, 'compliance_score', 'chart-compliance', 'Compliance Score by Product Line')}
        </div>
    `;

    renderKPICards(document.getElementById('quality-kpis'), kpis);

    createLineChart('chart-batch-rejection',
        batchTrend.data_points.map(p => p.timestamp),
        [{ label: 'Rejection Rate', data: batchTrend.data_points.map(p => p.value), color: '#ef4444' }],
        { unit: '%' }
    );

    createBarChart('chart-yield-site',
        yieldBySite.map(s => s.site),
        yieldBySite.map(s => s.value),
        { unit: '%', yMin: 85 }
    );

    createLineChart('chart-deviation',
        devTrend.data_points.map(p => p.timestamp),
        [{ label: 'Deviation Rate', data: devTrend.data_points.map(p => p.value), color: '#f97316' }],
        { unit: '%' }
    );

    createLineChart('chart-rft',
        rftTrend.data_points.map(p => p.timestamp),
        [{ label: 'RFT %', data: rftTrend.data_points.map(p => p.value), color: '#22c55e' }],
        { unit: '%', yMin: 80 }
    );

    createLineChart('chart-capa',
        capaTrend.data_points.map(p => p.timestamp),
        [{ label: 'CAPA Days', data: capaTrend.data_points.map(p => p.value), color: '#3b82f6' }],
        { unit: ' days' }
    );

    createDonutChart('chart-compliance',
        complianceBreakdown.map(c => c.category),
        complianceBreakdown.map(c => c.value),
        { unit: '%' }
    );
}

// ── SERVICE TAB ──────────────────────────────────────────────────────

async function renderServiceTab(params) {
    const [kpis, supplyDemand, otifTrend, slaTrend, respDist, ltBySite, schedTrend, backorderTrend, capTrend, targets] = await Promise.all([
        api.getServiceKPIs(params),
        api.getSupplyDemand(params),
        api.getOtifTrend(params),
        api.getSlaTrend(params),
        api.getResponseTimeDist(params),
        api.getLeadTimeBySite(params),
        api.getScheduleTrend(params),
        api.getBackorderTrend(params),
        api.getCapacityTrend(params),
        api.getTargets(),
    ]);

    const enabled = _enabledSet(targets);
    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="kpi-grid" id="service-kpis"></div>
        <div class="charts-grid">
            ${_cc(enabled, 'supply_vs_demand', 'chart-supply-demand', 'Supply vs Demand')}
            ${_cc(enabled, 'otif_rate', 'chart-otif', 'OTIF Rate Trend')}
            ${_cc(enabled, 'sla_adherence', 'chart-sla', 'SLA Adherence Trend')}
            ${_cc(enabled, 'response_time', 'chart-resp-dist', 'Response Time Distribution')}
            ${_cc(enabled, 'schedule_adherence', 'chart-schedule', 'Schedule Adherence Trend')}
            ${_cc(enabled, 'backorder_rate', 'chart-backorder', 'Backorder Rate Trend')}
            ${_cc(enabled, 'capacity_utilization', 'chart-capacity', 'Capacity Utilization Trend')}
            ${_cc(enabled, 'lead_time', 'chart-lt-site', 'Lead Time by Site')}
        </div>
    `;

    renderKPICards(document.getElementById('service-kpis'), kpis);

    const supplyLabels = supplyDemand.supply.data_points.map(p => p.timestamp);
    createLineChart('chart-supply-demand', supplyLabels, [
        { label: 'Supply', data: supplyDemand.supply.data_points.map(p => p.value), color: '#22c55e' },
        { label: 'Demand', data: supplyDemand.demand.data_points.map(p => p.value), color: '#ef4444', fill: false },
    ], { unit: ' units' });

    createLineChart('chart-otif',
        otifTrend.data_points.map(p => p.timestamp),
        [{ label: 'OTIF %', data: otifTrend.data_points.map(p => p.value), color: '#a855f7' }],
        { unit: '%', yMin: 80 }
    );

    createLineChart('chart-sla',
        slaTrend.data_points.map(p => p.timestamp),
        [{ label: 'SLA %', data: slaTrend.data_points.map(p => p.value), color: '#3b82f6' }],
        { unit: '%', yMin: 80 }
    );

    createBarChart('chart-resp-dist',
        respDist.map(d => d.bucket),
        respDist.map(d => d.count),
        { colors: ['#22c55e', '#22c55e', '#f59e0b', '#f59e0b', '#ef4444', '#ef4444'] }
    );

    createLineChart('chart-schedule',
        schedTrend.data_points.map(p => p.timestamp),
        [{ label: 'Schedule Adherence %', data: schedTrend.data_points.map(p => p.value), color: '#8b5cf6' }],
        { unit: '%', yMin: 75 }
    );

    createLineChart('chart-backorder',
        backorderTrend.data_points.map(p => p.timestamp),
        [{ label: 'Backorder Rate %', data: backorderTrend.data_points.map(p => p.value), color: '#ef4444' }],
        { unit: '%' }
    );

    createLineChart('chart-capacity',
        capTrend.data_points.map(p => p.timestamp),
        [{ label: 'Capacity Utilization %', data: capTrend.data_points.map(p => p.value), color: '#06b6d4' }],
        { unit: '%', yMin: 50 }
    );

    createBarChart('chart-lt-site',
        ltBySite.map(s => s.site),
        ltBySite.map(s => s.value),
        { unit: ' days' }
    );
}

// ── COST TAB ─────────────────────────────────────────────────────────

async function renderCostTab(params) {
    const [kpis, wasteTrend, cpbTrend, invTrend, breakdown, reworkTrend, copqTrend, varTrend, targets] = await Promise.all([
        api.getCostKPIs(params),
        api.getWasteTrend(params),
        api.getCostPerBatchTrend(params),
        api.getInventoryTrend(params),
        api.getCostBreakdown(params),
        api.getReworkTrend(params),
        api.getCopqTrend(params),
        api.getVarianceTrend(params),
        api.getTargets(),
    ]);

    const enabled = _enabledSet(targets);
    const anyCostEnabled = kpis.length > 0;
    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="kpi-grid" id="cost-kpis"></div>
        <div class="charts-grid">
            ${_cc(enabled, 'waste_percentage', 'chart-waste', 'Waste % Trend')}
            ${_cc(enabled, 'cost_per_batch', 'chart-cpb', 'Cost per Batch Trend')}
            ${_cc(enabled, 'rework_rate', 'chart-rework', 'Rework Rate Trend')}
            ${_cc(enabled, 'copq', 'chart-copq', 'COPQ Trend')}
            ${_cc(enabled, 'production_cost_variance', 'chart-variance', 'Production Cost Variance Trend')}
            ${_cc(enabled, 'inventory_carrying_cost', 'chart-inventory', 'Inventory Carrying Cost Trend')}
            ${anyCostEnabled ? '<div class="chart-card span-2"><div class="chart-header"><h3>Cost Breakdown by Product</h3></div><div class="chart-body"><canvas id="chart-cost-breakdown"></canvas></div></div>' : ''}
        </div>
    `;

    renderKPICards(document.getElementById('cost-kpis'), kpis);

    createLineChart('chart-waste',
        wasteTrend.data_points.map(p => p.timestamp),
        [{ label: 'Waste %', data: wasteTrend.data_points.map(p => p.value), color: '#ef4444' }],
        { unit: '%' }
    );

    createLineChart('chart-cpb',
        cpbTrend.data_points.map(p => p.timestamp),
        [{ label: 'Cost per Batch', data: cpbTrend.data_points.map(p => p.value), color: '#f59e0b' }],
        { unit: '$' }
    );

    createLineChart('chart-rework',
        reworkTrend.data_points.map(p => p.timestamp),
        [{ label: 'Rework Rate', data: reworkTrend.data_points.map(p => p.value), color: '#f97316' }],
        { unit: '%' }
    );

    createLineChart('chart-copq',
        copqTrend.data_points.map(p => p.timestamp),
        [{ label: 'COPQ', data: copqTrend.data_points.map(p => p.value), color: '#dc2626' }],
        { unit: '$' }
    );

    createLineChart('chart-variance',
        varTrend.data_points.map(p => p.timestamp),
        [{ label: 'Cost Variance %', data: varTrend.data_points.map(p => p.value), color: '#fb923c' }],
        { unit: '%' }
    );

    createLineChart('chart-inventory',
        invTrend.data_points.map(p => p.timestamp),
        [{ label: 'Carrying Cost', data: invTrend.data_points.map(p => p.value), color: '#f97316' }],
        { unit: '$' }
    );

    createDonutChart('chart-cost-breakdown',
        breakdown.map(c => c.category),
        breakdown.map(c => c.value),
        { unit: '$', colors: COLORS.products }
    );
}

// ── EFFICIENCY TAB ───────────────────────────────────────────────────

async function renderEfficiencyTab(params) {
    const [kpis, oeeTrend, downtimeTrend, oeeBySite, targets] = await Promise.all([
        api.getEfficiencyKPIs(params),
        api.getOeeTrend(params),
        api.getDowntimeTrend(params),
        api.getOeeBySite(params),
        api.getTargets(),
    ]);

    const enabled = _enabledSet(targets);
    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="kpi-grid" id="efficiency-kpis"></div>
        <div class="charts-grid">
            ${_cc(enabled, 'oee', 'chart-oee', 'OEE Trend')}
            ${_cc(enabled, 'downtime_rate', 'chart-downtime', 'Downtime Rate Trend')}
            ${_cc(enabled, 'oee', 'chart-oee-site', 'OEE by Site', 'span-2')}
        </div>
    `;

    renderKPICards(document.getElementById('efficiency-kpis'), kpis);

    createLineChart('chart-oee',
        oeeTrend.data_points.map(p => p.timestamp),
        [{ label: 'OEE %', data: oeeTrend.data_points.map(p => p.value), color: '#14b8a6' }],
        { unit: '%', yMin: 60 }
    );

    createLineChart('chart-downtime',
        downtimeTrend.data_points.map(p => p.timestamp),
        [{ label: 'Downtime %', data: downtimeTrend.data_points.map(p => p.value), color: '#ef4444' }],
        { unit: '%' }
    );

    createBarChart('chart-oee-site',
        oeeBySite.map(s => s.site),
        oeeBySite.map(s => s.value),
        { unit: '%', yMin: 60, colors: COLORS.efficiency }
    );
}

// ── RISK TAB ─────────────────────────────────────────────────────────

async function renderRiskTab(params) {
    const [kpis, supplierTrend, heatmap, targets] = await Promise.all([
        api.getRiskKPIs(params),
        api.getSupplierRiskTrend(params),
        api.getRiskHeatmap(params),
        api.getTargets(),
    ]);

    const enabled = _enabledSet(targets);
    const anyRiskEnabled = kpis.length > 0;
    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="kpi-grid" id="risk-kpis"></div>
        <div class="charts-grid">
            ${_cc(enabled, 'supplier_risk_score', 'chart-supplier-risk', 'Supplier Risk Score Trend')}
            ${anyRiskEnabled ? '<div class="chart-card"><div class="chart-header"><h3>Risk Heatmap by Site</h3></div><div class="chart-body"><canvas id="chart-risk-heatmap"></canvas></div></div>' : ''}
        </div>
    `;

    renderKPICards(document.getElementById('risk-kpis'), kpis);

    createLineChart('chart-supplier-risk',
        supplierTrend.data_points.map(p => p.timestamp),
        [{ label: 'Supplier Risk', data: supplierTrend.data_points.map(p => p.value), color: '#ef4444' }],
        { unit: '' }
    );

    // Grouped bar chart for risk heatmap
    if (heatmap.length > 0) {
        createGroupedBarChart('chart-risk-heatmap',
            heatmap.map(s => s.site),
            [
                { label: 'Supplier Risk', data: heatmap.map(s => s.supplier_risk), color: '#ef4444' },
                { label: 'Stockout Risk', data: heatmap.map(s => s.stockout_risk), color: '#f87171' },
                { label: 'Batch Failure', data: heatmap.map(s => s.batch_failure), color: '#fb923c' },
                { label: 'Service Risk', data: heatmap.map(s => s.service_risk), color: '#fbbf24' },
            ],
            { yMin: 0 }
        );
    }
}

// ── SHARED COMPONENTS ────────────────────────────────────────────────

function renderAlerts(container, alerts) {
    container.innerHTML = alerts.map(a => `
        <div class="alert-card ${a.severity}">
            <div class="alert-icon">${a.severity === 'critical' ? '&#9888;' : '&#9432;'}</div>
            <div class="alert-content">
                <div class="alert-title">${a.display_name}</div>
                <div class="alert-message">${a.message}</div>
            </div>
            <span class="alert-badge ${a.category}">${a.category}</span>
        </div>
    `).join('');
}

async function loadHealthScore() {
    try {
        const params = filterManager ? filterManager.getParams() : {};
        const data = await api.getHealthScore(params);
        renderGauge('health-gauge', data.score, data.label);
    } catch (err) {
        console.error('Error loading health score:', err);
    }
}

function updateTimestamp() {
    const el = document.getElementById('last-updated');
    if (el) {
        el.textContent = 'Updated: ' + new Date().toLocaleTimeString();
    }
}

// ── SETTINGS MODAL (with weights + enable/disable) ───────────────────

function setupSettingsModal() {
    const btn = document.getElementById('settings-btn');
    const modal = document.getElementById('settings-modal');
    const closeBtn = document.getElementById('settings-close');
    const saveBtn = document.getElementById('settings-save');

    if (!btn || !modal) return;

    btn.addEventListener('click', async () => {
        modal.classList.add('active');
        await loadTargetsForm();
    });

    closeBtn?.addEventListener('click', () => modal.classList.remove('active'));
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.remove('active');
    });

    saveBtn?.addEventListener('click', async () => {
        const rows = document.querySelectorAll('.target-row');
        const updates = [];
        rows.forEach(row => {
            const targetInput = row.querySelector('.target-input');
            const weightInput = row.querySelector('.weight-input');
            const toggle = row.querySelector('.toggle-input');
            if (targetInput && weightInput) {
                updates.push({
                    metric_name: targetInput.dataset.metric,
                    value: parseFloat(targetInput.value),
                    weight: parseFloat(weightInput.value),
                    enabled: toggle ? toggle.checked : true,
                });
            }
        });

        try {
            await api.updateTargets(updates);
            modal.classList.remove('active');
            api.clearCache();
            await loadTab(currentTab);
            await loadHealthScore();
        } catch (err) {
            alert('Error saving targets: ' + err.message);
        }
    });
}

async function loadTargetsForm() {
    const container = document.getElementById('targets-form');
    if (!container) return;

    const targets = await api.getTargets();
    const grouped = { quality: [], service: [], cost: [], efficiency: [], risk: [] };
    targets.forEach(t => {
        if (grouped[t.category]) grouped[t.category].push(t);
    });

    const enabledTargets = targets.filter(t => t.enabled);
    const totalWeight = enabledTargets.reduce((s, t) => s + (t.weight || 0), 0);

    let html = `
        <div class="weight-summary">
            <span>Total Weight (enabled): </span>
            <span id="total-weight-display" class="weight-total">${totalWeight}</span>
            <span style="margin-left:auto;font-size:12px;color:var(--text-muted)">${enabledTargets.length} of ${targets.length} KPIs enabled</span>
        </div>
    `;

    const catLabels = { quality: 'Quality', service: 'Service', cost: 'Cost', efficiency: 'Efficiency', risk: 'Risk' };

    for (const [cat, items] of Object.entries(grouped)) {
        if (items.length === 0) continue;
        const catLabel = catLabels[cat] || cat;
        const catWeight = items.filter(t => t.enabled).reduce((s, t) => s + (t.weight || 0), 0);
        html += `<div class="targets-group">
            <h4><span class="section-badge ${cat}" style="font-size:11px;padding:2px 10px">${catLabel}</span> <span class="cat-weight-sum">(weight: ${catWeight})</span></h4>`;
        items.forEach(t => {
            const disabledClass = t.enabled ? '' : ' disabled';
            html += `
                <div class="target-row${disabledClass}">
                    <div class="target-row-left">
                        <label class="toggle-switch">
                            <input type="checkbox" class="toggle-input" data-metric="${t.metric_name}" ${t.enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                        <label class="target-label-name">${t.display_name}</label>
                    </div>
                    <div class="target-input-group">
                        <span class="target-direction">${t.direction}</span>
                        <input type="number" step="0.1" class="target-input" data-metric="${t.metric_name}" value="${t.value}" ${!t.enabled ? 'disabled' : ''}>
                        <span class="target-unit">${t.unit}</span>
                        <span class="weight-separator">|</span>
                        <span class="weight-label">W:</span>
                        <input type="number" step="1" min="0" max="100" class="weight-input" data-metric="${t.metric_name}" value="${t.weight || 10}" ${!t.enabled ? 'disabled' : ''}>
                    </div>
                </div>`;
        });
        html += '</div>';
    }
    container.innerHTML = html;

    // Toggle enable/disable behavior
    container.querySelectorAll('.toggle-input').forEach(toggle => {
        toggle.addEventListener('change', () => {
            const row = toggle.closest('.target-row');
            const inputs = row.querySelectorAll('.target-input, .weight-input');
            if (toggle.checked) {
                row.classList.remove('disabled');
                inputs.forEach(i => i.disabled = false);
            } else {
                row.classList.add('disabled');
                inputs.forEach(i => i.disabled = true);
            }
            updateWeightDisplay();
        });
    });

    // Live update total weight display
    container.querySelectorAll('.weight-input').forEach(input => {
        input.addEventListener('input', updateWeightDisplay);
    });

    function updateWeightDisplay() {
        let sum = 0;
        container.querySelectorAll('.target-row').forEach(row => {
            const toggle = row.querySelector('.toggle-input');
            const weight = row.querySelector('.weight-input');
            if (toggle && toggle.checked && weight) {
                sum += parseFloat(weight.value) || 0;
            }
        });
        const display = document.getElementById('total-weight-display');
        if (display) display.textContent = sum;
    }
}


// ── SETUP TAB ────────────────────────────────────────────────────

async function renderSetupTab() {
    const [sites, products] = await Promise.all([
        api.getSites(),
        api.getProductLines(),
    ]);

    const content = document.getElementById('tab-content');
    content.innerHTML = `
        <div class="setup-container">
            <!-- Sites Section -->
            <div class="setup-section">
                <div class="setup-card-header">
                    <h2>Sites</h2>
                    <span class="setup-count">${sites.length} active</span>
                </div>

                <div class="setup-add-form" id="add-site-form">
                    <input type="text" class="setup-input setup-input-name" id="new-site-name" placeholder="Site name">
                    <input type="number" step="0.1" class="setup-input setup-input-sm" id="new-site-vol" placeholder="Vol" value="1.0" title="Volume Multiplier">
                    <input type="number" step="0.1" class="setup-input setup-input-sm" id="new-site-cost" placeholder="Cost" value="1.0" title="Cost Multiplier">
                    <input type="number" step="0.1" class="setup-input setup-input-sm" id="new-site-quality" placeholder="Qual" value="0.0" title="Quality Offset">
                    <button class="setup-btn setup-btn-add" id="btn-add-site">+ Add</button>
                </div>

                <div class="setup-list" id="sites-list">
                    ${sites.map(s => `
                        <div class="setup-item" data-name="${s.name}">
                            <div class="setup-item-info">
                                <span class="setup-item-name">${s.name}</span>
                                <div class="setup-item-profile">
                                    <span class="profile-tag" title="Volume Multiplier">Vol: ${s.volume_mult}</span>
                                    <span class="profile-tag" title="Cost Multiplier">Cost: ${s.cost_mult}</span>
                                    <span class="profile-tag" title="Quality Offset">Qual: ${s.quality_offset}</span>
                                </div>
                            </div>
                            <div class="setup-item-actions">
                                <button class="setup-btn setup-btn-edit" onclick="editSite('${s.name}', ${s.volume_mult}, ${s.cost_mult}, ${s.quality_offset})">Edit</button>
                                <button class="setup-btn setup-btn-delete" onclick="removeSite('${s.name}')">Remove</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>

            <!-- Product Lines Section -->
            <div class="setup-section">
                <div class="setup-card-header">
                    <h2>Product Lines</h2>
                    <span class="setup-count">${products.length} active</span>
                </div>

                <div class="setup-add-form" id="add-product-form">
                    <input type="text" class="setup-input setup-input-name" id="new-product-name" placeholder="Product line name" style="flex:1">
                    <button class="setup-btn setup-btn-add" id="btn-add-product">+ Add</button>
                </div>

                <div class="setup-list" id="products-list">
                    ${products.map(p => `
                        <div class="setup-item" data-name="${p.name}">
                            <div class="setup-item-info">
                                <span class="setup-item-name">${p.name}</span>
                            </div>
                            <div class="setup-item-actions">
                                <button class="setup-btn setup-btn-delete" onclick="removeProduct('${p.name}')">Remove</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>

        <!-- Generate Data Button -->
        <div class="setup-generate">
            <button class="setup-btn setup-btn-generate" id="btn-generate-data">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.66 0 3-4.03 3-9s-1.34-9-3-9m0 18c-1.66 0-3-4.03-3-9s1.34-9 3-9"/></svg>
                Generate Mock Data for New Items
            </button>
            <span class="setup-generate-hint">Backfills 365 days of simulated data for any site/product combinations without data</span>
            <div id="generate-status" class="setup-status"></div>
        </div>
    `;

    // Wire up add buttons
    document.getElementById('btn-add-site').addEventListener('click', addNewSite);
    document.getElementById('btn-add-product').addEventListener('click', addNewProduct);
    document.getElementById('btn-generate-data').addEventListener('click', generateMockData);

    // Allow Enter key to submit
    document.getElementById('new-site-name').addEventListener('keydown', e => { if (e.key === 'Enter') addNewSite(); });
    document.getElementById('new-product-name').addEventListener('keydown', e => { if (e.key === 'Enter') addNewProduct(); });
}

async function addNewSite() {
    const name = document.getElementById('new-site-name').value.trim();
    if (!name) return;
    const vol = parseFloat(document.getElementById('new-site-vol').value) || 1.0;
    const cost = parseFloat(document.getElementById('new-site-cost').value) || 1.0;
    const qual = parseFloat(document.getElementById('new-site-quality').value) || 0.0;
    try {
        await api.addSite({ name, volume_mult: vol, cost_mult: cost, quality_offset: qual });
        api.clearCache();
        await renderSetupTab();
    } catch (err) {
        alert('Error adding site: ' + err.message);
    }
}

async function addNewProduct() {
    const name = document.getElementById('new-product-name').value.trim();
    if (!name) return;
    try {
        await api.addProductLine({ name });
        api.clearCache();
        await renderSetupTab();
    } catch (err) {
        alert('Error adding product line: ' + err.message);
    }
}

async function removeSite(name) {
    if (!confirm(`Remove site "${name}"? It will be hidden from filters but existing data is preserved.`)) return;
    try {
        await api.deleteSite(name);
        api.clearCache();
        await renderSetupTab();
        if (filterManager) await filterManager.initialize();
    } catch (err) {
        alert('Error removing site: ' + err.message);
    }
}

async function removeProduct(name) {
    if (!confirm(`Remove product line "${name}"? It will be hidden from filters but existing data is preserved.`)) return;
    try {
        await api.deleteProductLine(name);
        api.clearCache();
        await renderSetupTab();
        if (filterManager) await filterManager.initialize();
    } catch (err) {
        alert('Error removing product line: ' + err.message);
    }
}

async function editSite(name, vol, cost, qual) {
    const item = document.querySelector(`.setup-item[data-name="${name}"]`);
    if (!item) return;
    const info = item.querySelector('.setup-item-info');
    const actions = item.querySelector('.setup-item-actions');

    info.innerHTML = `
        <span class="setup-item-name">${name}</span>
        <div class="setup-edit-fields">
            <label>Vol: <input type="number" step="0.1" class="setup-input setup-input-sm" id="edit-vol" value="${vol}"></label>
            <label>Cost: <input type="number" step="0.1" class="setup-input setup-input-sm" id="edit-cost" value="${cost}"></label>
            <label>Qual: <input type="number" step="0.1" class="setup-input setup-input-sm" id="edit-qual" value="${qual}"></label>
        </div>
    `;
    actions.innerHTML = `
        <button class="setup-btn setup-btn-add" id="save-edit-${name}">Save</button>
        <button class="setup-btn setup-btn-secondary" onclick="renderSetupTab()">Cancel</button>
    `;
    document.getElementById(`save-edit-${name}`).addEventListener('click', async () => {
        const newVol = parseFloat(document.getElementById('edit-vol').value);
        const newCost = parseFloat(document.getElementById('edit-cost').value);
        const newQual = parseFloat(document.getElementById('edit-qual').value);
        try {
            await api.updateSite(name, { volume_mult: newVol, cost_mult: newCost, quality_offset: newQual });
            api.clearCache();
            await renderSetupTab();
        } catch (err) {
            alert('Error updating site: ' + err.message);
        }
    });
}

async function generateMockData() {
    const btn = document.getElementById('btn-generate-data');
    const status = document.getElementById('generate-status');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    status.textContent = '';
    status.className = 'setup-status';

    try {
        const result = await api.generateData({});
        api.clearCache();
        if (result.records_generated > 0) {
            status.textContent = `Generated ${result.records_generated.toLocaleString()} records successfully.`;
            status.classList.add('success');
            // Refresh filters so new sites/products appear
            if (filterManager) await filterManager.initialize();
        } else {
            status.textContent = 'All site/product combinations already have data. Nothing to generate.';
            status.classList.add('info');
        }
    } catch (err) {
        status.textContent = 'Error: ' + err.message;
        status.classList.add('error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.66 0 3-4.03 3-9s-1.34-9-3-9m0 18c-1.66 0-3-4.03-3-9s1.34-9 3-9"/></svg>
        Generate Mock Data for New Items`;
    }
}
