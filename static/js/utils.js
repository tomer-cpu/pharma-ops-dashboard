const Formatters = {
    number(val, decimals = 0) {
        return new Intl.NumberFormat('en-US', { maximumFractionDigits: decimals }).format(val);
    },
    percent(val, decimals = 1) {
        return val.toFixed(decimals) + '%';
    },
    currency(val) {
        if (Math.abs(val) >= 1000000) {
            return '$' + (val / 1000000).toFixed(1) + 'M';
        }
        if (Math.abs(val) >= 1000) {
            return '$' + (val / 1000).toFixed(0) + 'K';
        }
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(val);
    },
    days(val) {
        return val.toFixed(1) + 'd';
    },
    hours(val) {
        return val.toFixed(1) + 'h';
    },
    date(isoString) {
        const d = new Date(isoString + 'T00:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    },
    formatValue(val, unit) {
        switch (unit) {
            case '%': return Formatters.percent(val);
            case '$': return Formatters.currency(val);
            case 'days': return Formatters.days(val);
            case 'hours': return Formatters.hours(val);
            default: return Formatters.number(val, 1);
        }
    },
    changePercent(current, previous) {
        if (!previous) return 0;
        return ((current - previous) / Math.abs(previous) * 100).toFixed(1);
    }
};
