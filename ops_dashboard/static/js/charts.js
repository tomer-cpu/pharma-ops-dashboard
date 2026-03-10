const COLORS = {
    quality: ['#3b82f6', '#06b6d4', '#0ea5e9', '#2563eb', '#0284c7', '#0891b2', '#38bdf8', '#60a5fa', '#7dd3fc'],
    service: ['#a855f7', '#d946ef', '#8b5cf6', '#c084fc', '#e879f9', '#7c3aed', '#9333ea', '#a78bfa', '#d8b4fe', '#f0abfc', '#c026d3'],
    cost: ['#f59e0b', '#f97316', '#fb923c', '#fbbf24', '#d97706', '#ea580c', '#fdba74'],
    efficiency: ['#14b8a6', '#06b6d4', '#0d9488', '#22d3ee'],
    risk: ['#ef4444', '#f87171', '#dc2626', '#fb7185'],
    sites: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6', '#f97316', '#ec4899'],
    products: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6'],
};

const CAT_COLORS = {
    quality: '#3b82f6',
    service: '#a855f7',
    cost: '#f59e0b',
    efficiency: '#14b8a6',
    risk: '#ef4444',
};

// Store chart instances for cleanup
const chartInstances = {};

function destroyChart(id) {
    if (chartInstances[id]) {
        chartInstances[id].destroy();
        delete chartInstances[id];
    }
}

function destroyAllCharts() {
    Object.keys(chartInstances).forEach(destroyChart);
}

function createLineChart(canvasId, labels, datasets, options = {}) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: datasets.map((ds, i) => ({
                label: ds.label,
                data: ds.data,
                borderColor: ds.color || COLORS.quality[i % COLORS.quality.length],
                backgroundColor: (ds.color || COLORS.quality[i % COLORS.quality.length]) + '20',
                fill: ds.fill !== false,
                tension: 0.3,
                pointRadius: labels.length > 60 ? 0 : 3,
                pointHoverRadius: 5,
                borderWidth: 2,
            })),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: datasets.length > 1,
                    labels: { color: '#94a3b8', usePointStyle: true, padding: 15 }
                },
                tooltip: {
                    backgroundColor: '#1e293b',
                    borderColor: '#475569',
                    borderWidth: 1,
                    titleColor: '#f1f5f9',
                    bodyColor: '#cbd5e1',
                    callbacks: {
                        label: function(ctx) {
                            const unit = options.unit || '';
                            if (unit === '$') return ctx.dataset.label + ': ' + Formatters.currency(ctx.parsed.y);
                            return ctx.dataset.label + ': ' + ctx.parsed.y + unit;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: '#1e293b' },
                    ticks: {
                        color: '#64748b',
                        maxTicksLimit: 12,
                        callback: function(val, index) {
                            return Formatters.date(this.getLabelForValue(val));
                        }
                    }
                },
                y: {
                    grid: { color: '#1e293b' },
                    ticks: {
                        color: '#64748b',
                        callback: function(val) {
                            if (options.unit === '$') return Formatters.currency(val);
                            if (options.unit === '%') return val + '%';
                            return val;
                        }
                    },
                    ...(options.yMin !== undefined && { min: options.yMin }),
                    ...(options.yMax !== undefined && { max: options.yMax }),
                }
            }
        }
    });

    chartInstances[canvasId] = chart;
    return chart;
}

function createBarChart(canvasId, labels, values, options = {}) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const colors = options.colors || COLORS.sites;

    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((_, i) => colors[i % colors.length] + 'cc'),
                borderColor: labels.map((_, i) => colors[i % colors.length]),
                borderWidth: 1,
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: options.horizontal ? 'y' : 'x',
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1e293b',
                    borderColor: '#475569',
                    borderWidth: 1,
                    titleColor: '#f1f5f9',
                    bodyColor: '#cbd5e1',
                    callbacks: {
                        label: function(ctx) {
                            const unit = options.unit || '';
                            if (unit === '$') return Formatters.currency(ctx.parsed[options.horizontal ? 'x' : 'y']);
                            return ctx.parsed[options.horizontal ? 'x' : 'y'] + unit;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: '#1e293b' },
                    ticks: {
                        color: '#94a3b8',
                        ...(options.horizontal && {
                            callback: function(val) {
                                if (options.unit === '$') return Formatters.currency(val);
                                if (options.unit === '%') return val + '%';
                                return val;
                            }
                        })
                    },
                    ...(options.horizontal && options.yMin !== undefined && { min: options.yMin }),
                },
                y: {
                    grid: { color: options.horizontal ? 'transparent' : '#1e293b' },
                    ticks: {
                        color: '#94a3b8',
                        autoSkip: false,
                        callback: function(val, index) {
                            if (options.horizontal) {
                                return this.getLabelForValue(val);
                            }
                            if (options.unit === '$') return Formatters.currency(val);
                            if (options.unit === '%') return val + '%';
                            return val;
                        }
                    },
                    ...(!options.horizontal && options.yMin !== undefined && { min: options.yMin }),
                }
            }
        }
    });

    chartInstances[canvasId] = chart;
    return chart;
}

function createGroupedBarChart(canvasId, labels, datasets, options = {}) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: datasets.map((ds, i) => ({
                label: ds.label,
                data: ds.data,
                backgroundColor: (ds.color || COLORS.risk[i % COLORS.risk.length]) + 'cc',
                borderColor: ds.color || COLORS.risk[i % COLORS.risk.length],
                borderWidth: 1,
                borderRadius: 4,
            })),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#94a3b8', usePointStyle: true, padding: 15 }
                },
                tooltip: {
                    backgroundColor: '#1e293b',
                    borderColor: '#475569',
                    borderWidth: 1,
                    titleColor: '#f1f5f9',
                    bodyColor: '#cbd5e1',
                }
            },
            scales: {
                x: {
                    grid: { color: '#1e293b' },
                    ticks: { color: '#94a3b8' },
                },
                y: {
                    grid: { color: '#1e293b' },
                    ticks: { color: '#94a3b8' },
                    ...(options.yMin !== undefined && { min: options.yMin }),
                }
            }
        }
    });

    chartInstances[canvasId] = chart;
    return chart;
}

function createDonutChart(canvasId, labels, values, options = {}) {
    destroyChart(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;

    const colors = options.colors || COLORS.products;

    const chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((_, i) => colors[i % colors.length] + 'cc'),
                borderColor: '#0f172a',
                borderWidth: 3,
                hoverOffset: 8,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#94a3b8', usePointStyle: true, padding: 12, font: { size: 11 } }
                },
                tooltip: {
                    backgroundColor: '#1e293b',
                    borderColor: '#475569',
                    borderWidth: 1,
                    titleColor: '#f1f5f9',
                    bodyColor: '#cbd5e1',
                    callbacks: {
                        label: function(ctx) {
                            const unit = options.unit || '';
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((ctx.parsed / total) * 100).toFixed(1);
                            if (unit === '$') return ctx.label + ': ' + Formatters.currency(ctx.parsed) + ' (' + pct + '%)';
                            return ctx.label + ': ' + ctx.parsed + unit + ' (' + pct + '%)';
                        }
                    }
                }
            }
        }
    });

    chartInstances[canvasId] = chart;
    return chart;
}

function renderGauge(containerId, score, label) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const angle = (score / 100) * 180;
    let color;
    if (score >= 80) color = '#22c55e';
    else if (score >= 60) color = '#f59e0b';
    else if (score >= 40) color = '#f97316';
    else color = '#ef4444';

    container.innerHTML = `
        <svg viewBox="0 0 200 120" class="gauge-svg">
            <defs>
                <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style="stop-color:#ef4444"/>
                    <stop offset="40%" style="stop-color:#f59e0b"/>
                    <stop offset="70%" style="stop-color:#22c55e"/>
                    <stop offset="100%" style="stop-color:#22c55e"/>
                </linearGradient>
            </defs>
            <!-- Background arc -->
            <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="#1e293b" stroke-width="12" stroke-linecap="round"/>
            <!-- Value arc -->
            <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="url(#gaugeGrad)" stroke-width="12" stroke-linecap="round"
                  stroke-dasharray="${(angle / 180) * 251.2} 251.2"
                  style="transition: stroke-dasharray 1s ease"/>
            <!-- Needle -->
            <line x1="100" y1="100" x2="${100 + 65 * Math.cos((180 - angle) * Math.PI / 180)}" y2="${100 - 65 * Math.sin((180 - angle) * Math.PI / 180)}"
                  stroke="${color}" stroke-width="2.5" stroke-linecap="round"
                  style="transition: all 1s ease"/>
            <circle cx="100" cy="100" r="4" fill="${color}"/>
            <!-- Score text -->
            <text x="100" y="88" text-anchor="middle" fill="#f1f5f9" font-size="22" font-weight="700">${score}</text>
            <text x="100" y="108" text-anchor="middle" fill="#94a3b8" font-size="10">${label}</text>
        </svg>
    `;
}
