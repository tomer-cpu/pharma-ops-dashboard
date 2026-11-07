/* Agroshtil grower offers – admin page */
(() => {
    const $ = (s, el = document) => el.querySelector(s);
    const $$ = (s, el = document) => [...el.querySelectorAll(s)];
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const API = '/api/agro';
    const state = { customers: [], settings: null, filter: 'all', search: '', parsed: null, mapping: [] };

    const STATUS_LABEL = {
        new: 'טרם נשלח', sent: 'ממתין לתשובה', interested: 'מעוניין', not_interested: 'לא מעוניין',
        not_sent: 'טרם נשלח', awaiting: 'ממתין לתשובה', partial: 'ענה חלקית', empty: 'אין שורות',
    };
    const SOURCE_LABEL = { web: 'דרך הקישור', whatsapp: 'וואטסאפ', sms: 'SMS', manual: 'סומן ידנית' };
    const CHANNEL_LABEL = { manual: 'וואטסאפ ידני', twilio: 'Twilio', whatsapp: 'WhatsApp API', web: 'קישור', sms: 'SMS' };

    async function api(path, opts = {}) {
        const res = await fetch(API + path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
            body: opts.body ? JSON.stringify(opts.body) : undefined,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `שגיאה ${res.status}`);
        return data;
    }

    function toast(msg) {
        const t = $('#toast');
        t.textContent = msg;
        t.classList.add('show');
        clearTimeout(toast._t);
        toast._t = setTimeout(() => t.classList.remove('show'), 2600);
    }

    const fmtDate = (iso) => {
        if (!iso) return '';
        const d = new Date(iso);
        return d.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit' }) + ' ' +
            d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
    };

    // ── Tabs ───────────────────────────────────────────────────
    $$('.tab').forEach((b) => b.addEventListener('click', () => {
        $$('.tab').forEach((x) => x.classList.toggle('active', x === b));
        $$('.panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + b.dataset.tab));
        if (b.dataset.tab === 'log') loadLog();
    }));

    // ── KPIs ───────────────────────────────────────────────────
    async function loadStats() {
        const s = await api('/stats');
        const answered = s.interested + s.not_interested;
        const sentTotal = s.sent + answered;
        const rate = sentTotal ? Math.round((answered / sentTotal) * 100) : 0;
        $('#kpis').innerHTML = [
            ['לקוחות', s.customers, `${s.items} ירקות/שורות`, ''],
            ['טרם נשלח', s.new, 'שורות ממתינות לשליחה', ''],
            ['ממתינים לתשובה', s.sent, `${s.customers_contacted} לקוחות קיבלו הצעה`, 'amber'],
            ['מעוניינים', s.interested, 'שורות', 'green'],
            ['לא מעוניינים', s.not_interested, 'שורות', 'red'],
            ['שיעור מענה', rate + '%', `${s.customers_responded} לקוחות ענו`, ''],
        ].map(([l, v, h, cls]) => `<div class="kpi ${cls}"><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`).join('');
    }

    // ── Customers ──────────────────────────────────────────────
    async function loadCustomers() {
        state.customers = await api('/customers');
        renderCustomers();
    }

    function matchesFilter(c) {
        const f = state.filter;
        if (f === 'review') return !!c.needs_review;
        if (f === 'interested') return c.counts.interested > 0;
        if (f === 'not_interested') return c.status === 'not_interested';
        if (f !== 'all' && c.status !== f) return false;
        return true;
    }

    function matchesSearch(c) {
        const q = state.search.trim().toLowerCase();
        if (!q) return true;
        const qDigits = q.replace(/\D/g, '');
        if (c.name.toLowerCase().includes(q)) return true;
        if (qDigits.length >= 3 && (c.phone.includes(qDigits) || c.phone_display.replace(/\D/g, '').includes(qDigits))) return true;
        return c.items.some((i) => (i.vegetable + ' ' + i.variety).toLowerCase().includes(q));
    }

    function renderCustomers() {
        const list = state.customers.filter((c) => matchesFilter(c) && matchesSearch(c));
        const el = $('#customers');
        if (!state.customers.length) {
            el.innerHTML = `<div class="card empty">עדיין אין לקוחות. עברו ללשונית <b>קליטת רשימה</b> כדי להתחיל.</div>`;
            return;
        }
        if (!list.length) {
            el.innerHTML = `<div class="card empty">אין לקוחות שמתאימים לסינון.</div>`;
            return;
        }
        el.innerHTML = list.map(renderCustomer).join('');
    }

    function renderCustomer(c) {
        const badges = [`<span class="badge b-${c.status}">${STATUS_LABEL[c.status] || c.status}</span>`];
        if (c.needs_review) badges.push('<span class="badge b-review">תשובה לבדיקה</span>');
        const meta = [];
        if (c.sent_at) meta.push(`נשלח ${fmtDate(c.sent_at)} (${CHANNEL_LABEL[c.send_channel] || c.send_channel})`);
        if (c.responded_at) meta.push(`ענה ${fmtDate(c.responded_at)}`);
        const sendLabel = c.counts.new ? '📤 שליחת הצעה' : '🔁 שליחה חוזרת';
        const canSend = c.counts.new || c.counts.sent;
        return `
        <div class="cust" data-id="${c.id}">
            <div class="cust-head">
                <span class="cust-name">${esc(c.name)}</span>
                <span class="phone">${esc(c.phone_display)}</span>
                ${badges.join(' ')}
                <span class="spacer"></span>
                ${canSend ? `<button class="btn small wa" data-act="send" data-resend="${c.counts.new ? 0 : 1}">${sendLabel}</button>` : ''}
                <button class="btn small" data-act="copy" title="העתקת הקישור האישי">🔗 קישור</button>
                <button class="btn small" data-act="edit" title="עריכת שם/נייד">✏️</button>
                <button class="btn small danger" data-act="del-cust" title="מחיקת לקוח">🗑️</button>
            </div>
            ${meta.length ? `<div class="cust-meta">${meta.join(' · ')}</div>` : ''}
            ${c.last_reply ? `<div class="reply">💬 תשובה אחרונה: “${esc(c.last_reply)}”</div>` : ''}
            ${c.customer_note ? `<div class="reply note">📝 הערת הלקוח: ${esc(c.customer_note)}</div>` : ''}
            <div class="items">${c.items.map(renderItem).join('')}</div>
        </div>`;
    }

    function renderItem(i) {
        const meta = [i.variety && `זן ${esc(i.variety)}`, i.quantity && esc(i.quantity), i.notes && esc(i.notes)].filter(Boolean).join(' · ');
        const src = i.response_source ? ` <span class="meta">(${SOURCE_LABEL[i.response_source] || i.response_source})</span>` : '';
        return `
        <div class="item" data-item="${i.id}">
            <span class="veg">🌿 ${esc(i.vegetable)}</span>
            ${meta ? `<span class="meta">${meta}</span>` : ''}
            <span class="spacer"></span>
            <span class="badge b-${i.status}">${STATUS_LABEL[i.status]}</span>${src}
            <span class="acts">
                <button class="icon-btn yes ${i.status === 'interested' ? 'on' : ''}" data-act="yes" title="סימון: מעוניין">✓</button>
                <button class="icon-btn no ${i.status === 'not_interested' ? 'on' : ''}" data-act="no" title="סימון: לא מעוניין">✗</button>
                <button class="icon-btn" data-act="undo" title="ביטול תשובה">↺</button>
                <button class="icon-btn" data-act="del-item" title="מחיקת שורה">🗑</button>
            </span>
        </div>`;
    }

    $('#customers').addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-act]');
        if (!btn) return;
        const custEl = btn.closest('.cust');
        const c = state.customers.find((x) => x.id === +custEl.dataset.id);
        const itemEl = btn.closest('.item');
        const itemId = itemEl && +itemEl.dataset.item;
        const item = itemId && c.items.find((i) => i.id === itemId);
        try {
            switch (btn.dataset.act) {
                case 'send':
                    return startSend([c], btn.dataset.resend === '1');
                case 'copy':
                    await navigator.clipboard.writeText(c.offer_link).catch(() => prompt('העתיקו את הקישור:', c.offer_link));
                    return toast('הקישור האישי הועתק');
                case 'edit': {
                    const name = prompt('שם לקוח:', c.name);
                    if (name === null) return;
                    const phone = prompt('נייד:', c.phone_display);
                    if (phone === null) return;
                    await api(`/customers/${c.id}`, { method: 'PUT', body: { name, phone } });
                    break;
                }
                case 'del-cust':
                    if (!confirm(`למחוק את ${c.name} וכל השורות שלו?`)) return;
                    await api(`/customers/${c.id}`, { method: 'DELETE' });
                    break;
                case 'yes':
                case 'no':
                case 'undo': {
                    const status = btn.dataset.act === 'yes' ? 'interested' : btn.dataset.act === 'no' ? 'not_interested'
                        : (item.sent_at ? 'sent' : 'new');
                    await api(`/items/${itemId}`, { method: 'PUT', body: { status } });
                    break;
                }
                case 'del-item':
                    if (!confirm(`למחוק את השורה "${item.vegetable}"?`)) return;
                    await api(`/items/${itemId}`, { method: 'DELETE' });
                    break;
            }
            await refresh();
        } catch (err) {
            toast(err.message);
        }
    });

    $$('#filters .chip').forEach((ch) => ch.addEventListener('click', () => {
        $$('#filters .chip').forEach((x) => x.classList.toggle('active', x === ch));
        state.filter = ch.dataset.f;
        renderCustomers();
    }));
    $('#search').addEventListener('input', (e) => { state.search = e.target.value; renderCustomers(); });

    // ── Sending ────────────────────────────────────────────────
    $('#send-all').addEventListener('click', () => {
        const targets = state.customers.filter((c) => c.counts.new > 0);
        if (!targets.length) return toast('כל הלקוחות כבר קיבלו הצעה');
        startSend(targets, false);
    });

    async function startSend(customers, resend) {
        const channel = $('#channel').value;
        if (channel === 'manual') return openQueue(customers, resend);
        if (!state.settings.channels[channel]) {
            return toast('הערוץ לא מוגדר בשרת – ראו לשונית "נוסח ההודעה וערוצים"');
        }
        if (!confirm(`לשלוח הצעה ל-${customers.length} לקוחות דרך ${CHANNEL_LABEL[channel]}?`)) return;
        try {
            const r = await api('/send', { method: 'POST', body: { customer_ids: customers.map((c) => c.id), channel, resend } });
            const failed = r.results.filter((x) => !x.ok);
            toast(failed.length ? `נשלחו ${r.processed - failed.length}, נכשלו ${failed.length}: ${failed[0].error}` : `נשלחו ${r.processed} הודעות`);
        } catch (err) { toast(err.message); }
        refresh();
    }

    const queue = { list: [], idx: 0, resend: false, current: null };

    function openQueue(customers, resend) {
        Object.assign(queue, { list: customers, idx: 0, resend });
        $('#queue').classList.add('show');
        showQueueItem();
    }

    async function showQueueItem() {
        if (queue.idx >= queue.list.length) {
            $('#queue').classList.remove('show');
            toast('סיימנו! התשובות יופיעו כאן כשהלקוחות ילחצו על הקישור');
            return refresh();
        }
        const c = queue.list[queue.idx];
        $('#q-count').textContent = `(${queue.idx + 1} מתוך ${queue.list.length})`;
        $('#q-bar').style.width = `${(queue.idx / queue.list.length) * 100}%`;
        $('#q-name').textContent = c.name;
        $('#q-phone').textContent = c.phone_display;
        $('#q-msg').textContent = 'טוען…';
        queue.current = null;
        try {
            queue.current = await api(`/customers/${c.id}/preview`);
            $('#q-msg').textContent = queue.current.message;
        } catch (err) { $('#q-msg').textContent = err.message; }
    }

    $('#q-open').addEventListener('click', async () => {
        if (!queue.current) return;
        const c = queue.list[queue.idx];
        window.open(queue.current.wa_link, '_blank', 'noopener');   // synchronous → not blocked
        try {
            await api('/send', { method: 'POST', body: { customer_ids: [c.id], channel: 'manual', resend: queue.resend } });
        } catch (err) { toast(err.message); }
        queue.idx++;
        showQueueItem();
    });
    $('#q-skip').addEventListener('click', () => { queue.idx++; showQueueItem(); });
    $('#q-close').addEventListener('click', () => { $('#queue').classList.remove('show'); refresh(); });

    // ── Import ─────────────────────────────────────────────────
    const FIELDS = [
        ['', '— התעלם —'], ['name', 'שם לקוח'], ['phone', 'נייד'], ['vegetable', 'ירק'],
        ['variety', 'זן'], ['quantity', 'כמות'], ['notes', 'הערות'],
    ];
    // Order matters: "טלפון לקוח" should map to phone, not name.
    const HEADER_RULES = [
        ['phone', /נייד|טלפון|פלאפון|סלולרי|phone|mobile|cell|tel/i],
        ['vegetable', /ירק|גידול|שתיל|מוצר|פריט|vegetable|crop|item|product/i],
        ['variety', /זן|variety|cultivar/i],
        ['quantity', /כמות|qty|quantity|amount/i],
        ['notes', /הער|notes?|comment/i],
        ['name', /שם|לקוח|מגדל|משק|name|customer|grower/i],
    ];

    function parseDelimited(text) {
        text = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n');
        const firstLine = text.split('\n').find((l) => l.trim()) || '';
        const delim = firstLine.includes('\t') ? '\t' : (firstLine.split(';').length > firstLine.split(',').length ? ';' : ',');
        const rows = [];
        let row = [], cell = '', q = false;
        for (let i = 0; i < text.length; i++) {
            const ch = text[i];
            if (q) {
                if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
                else if (ch === '"') q = false;
                else cell += ch;
            } else if (ch === '"' && cell === '') q = true;
            else if (ch === delim) { row.push(cell); cell = ''; }
            else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
            else cell += ch;
        }
        row.push(cell); rows.push(row);
        return rows.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c));
    }

    const looksLikePhone = (v) => /^\+?[\d\s\-()]{9,}$/.test(String(v).trim());

    function detectMapping(rows) {
        const header = rows[0] || [];
        const used = new Set();
        const mapping = header.map((h) => {
            for (const [field, re] of HEADER_RULES) {
                if (!used.has(field) && re.test(h)) { used.add(field); return field; }
            }
            return '';
        });
        const hasHeader = used.has('phone') || used.has('vegetable') || (used.size >= 2 && !header.some(looksLikePhone));
        if (hasHeader) return { hasHeader: true, mapping };
        // No header: guess by content — phone column is the one that looks like numbers
        const width = Math.max(...rows.map((r) => r.length));
        const phoneCol = [...Array(width).keys()].find((ci) => rows.slice(0, 10).filter((r) => looksLikePhone(r[ci] || '')).length >= Math.min(3, rows.length));
        const order = ['name', 'phone', 'vegetable', 'variety', 'quantity', 'notes'];
        let m = order.slice(0, width);
        if (phoneCol !== undefined && phoneCol !== 1) {
            const rest = order.filter((f) => f !== 'phone');
            m = [...Array(width).keys()].map((ci) => (ci === phoneCol ? 'phone' : rest.shift() || ''));
        }
        while (m.length < width) m.push('');
        return { hasHeader: false, mapping: m };
    }

    function normalizePhone(raw) {
        let d = String(raw || '').replace(/\D/g, '');
        if (d.startsWith('00')) d = d.slice(2);
        if (d.startsWith('972')) d = d.slice(3);
        if (d.startsWith('0')) d = d.slice(1);
        return d.length === 9 && d.startsWith('5') ? '972' + d : null;
    }

    function loadRows(rows) {
        if (!rows.length) return toast('לא נמצאו נתונים');
        const { hasHeader, mapping } = detectMapping(rows);
        state.parsed = { header: hasHeader ? rows[0] : null, body: hasHeader ? rows.slice(1) : rows };
        state.mapping = mapping;
        renderPreview();
    }

    function mappedRows() {
        let lastName = '', lastPhone = '';
        return state.parsed.body.map((r) => {
            const o = { name: '', phone: '', vegetable: '', variety: '', quantity: '', notes: '' };
            state.mapping.forEach((f, ci) => { if (f) o[f] = (o[f] ? o[f] + ' ' : '') + (r[ci] || ''); });
            // Excel lists often leave name/phone blank on follow-up rows of the same customer
            if (!o.name && !o.phone && o.vegetable) { o.name = lastName; o.phone = lastPhone; }
            if (o.name) lastName = o.name;
            if (o.phone) lastPhone = o.phone;
            let err = '';
            if (!normalizePhone(o.phone)) err = 'נייד לא תקין';
            else if (!o.vegetable) err = 'חסר ירק';
            else if (!o.name) err = 'חסר שם';
            return { ...o, _err: err };
        });
    }

    function renderPreview() {
        const width = Math.max(state.mapping.length, ...state.parsed.body.map((r) => r.length));
        while (state.mapping.length < width) state.mapping.push('');
        const head = state.mapping.map((f, ci) => `<th>
            ${state.parsed.header ? `<div style="font-weight:400;color:var(--muted)">${esc(state.parsed.header[ci] || '')}</div>` : ''}
            <select data-col="${ci}">${FIELDS.map(([v, l]) => `<option value="${v}" ${v === f ? 'selected' : ''}>${l}</option>`).join('')}</select>
        </th>`).join('');
        const rows = mappedRows();
        const body = state.parsed.body.slice(0, 300).map((r, ri) => `<tr>
            <td style="color:var(--muted)">${ri + 1}</td>
            ${[...Array(width).keys()].map((ci) => `<td>${esc(r[ci] || '')}</td>`).join('')}
            <td class="err">${rows[ri]._err}</td></tr>`).join('');
        $('#preview').innerHTML = `<thead><tr><th>#</th>${head}<th>בדיקה</th></tr></thead><tbody>${body}</tbody>`;
        const ok = rows.filter((r) => !r._err);
        const custs = new Set(ok.map((r) => normalizePhone(r.phone)));
        $('#preview-summary').textContent = `${rows.length} שורות · ${ok.length} תקינות · ${custs.size} לקוחות` +
            (rows.length - ok.length ? ` · ${rows.length - ok.length} עם שגיאה` : '') +
            (state.parsed.body.length > 300 ? ' · מוצגות 300 הראשונות' : '');
        $('#preview-card').style.display = '';
        $('#import-result').className = 'msg-box';
        $$('#preview select').forEach((s) => s.addEventListener('change', () => {
            state.mapping[+s.dataset.col] = s.value;
            renderPreview();
        }));
    }

    $('#parse').addEventListener('click', () => loadRows(parseDelimited($('#paste').value)));
    $('#sample').addEventListener('click', () => {
        $('#paste').value = [
            ['שם לקוח', 'נייד', 'ירק', 'זן', 'כמות'],
            ['משק כהן', '050-1234567', 'עגבניה', '5656', '10,000'],
            ['משק כהן', '050-1234567', 'מלפפון', '', '5,000'],
            ['משק כהן', '050-1234567', 'פלפל', 'מקסימוס', ''],
            ['יוסי לוי', '052-7654321', 'חסה', '', '3,000'],
            ['יוסי לוי', '052-7654321', 'כרוב', '', ''],
            ['מושב תלמי אליהו – רונית', '054-9876543', 'אבטיח', '', '2,500'],
        ].map((r) => r.join('\t')).join('\n');
        loadRows(parseDelimited($('#paste').value));
    });

    $('#file').addEventListener('change', async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        try {
            if (/\.xlsx?$/i.test(f.name)) {
                if (!window.XLSX) throw new Error('ספריית Excel לא נטענה – נסו לשמור כ-CSV');
                const wb = XLSX.read(await f.arrayBuffer(), { type: 'array' });
                const sheet = wb.Sheets[wb.SheetNames[0]];
                const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false, defval: '' })
                    .map((r) => r.map((c) => String(c).trim())).filter((r) => r.some((c) => c));
                loadRows(rows);
            } else {
                const buf = await f.arrayBuffer();
                let text = new TextDecoder('utf-8').decode(buf);
                if (text.includes('�')) text = new TextDecoder('windows-1255').decode(buf); // Hebrew Excel CSV
                $('#paste').value = text;
                loadRows(parseDelimited(text));
            }
        } catch (err) { toast(err.message); }
        e.target.value = '';
    });

    $('#do-import').addEventListener('click', async () => {
        const rows = mappedRows().filter((r) => !r._err).map(({ _err, ...r }) => r);
        const box = $('#import-result');
        if (!rows.length) {
            box.className = 'msg-box show bad';
            box.textContent = 'אין שורות תקינות לקליטה – בדקו את מיפוי העמודות.';
            return;
        }
        try {
            const r = await api('/import', { method: 'POST', body: { rows } });
            box.className = 'msg-box show ok';
            box.innerHTML = `נקלטו ${r.added_items} שורות · ${r.created_customers} לקוחות חדשים` +
                (r.skipped_duplicates ? ` · ${r.skipped_duplicates} כפילויות דולגו` : '') +
                (r.errors.length ? `<ul>${r.errors.slice(0, 10).map((x) => `<li>שורה ${x.row}: ${esc(x.error)}</li>`).join('')}</ul>` : '') +
                `<div style="margin-top:8px"><button class="btn small primary" id="go-track">למעבר לשליחה ←</button></div>`;
            $('#go-track').addEventListener('click', () => $('.tab[data-tab=track]').click());
            $('#paste').value = '';
            refresh();
        } catch (err) {
            box.className = 'msg-box show bad';
            box.textContent = err.message;
        }
    });

    // ── Message template & channels ───────────────────────────
    async function loadSettings() {
        state.settings = await api('/settings');
        $('#template').value = state.settings.template;
        renderTplPreview();
        const ch = state.settings.channels;
        $('#channels').innerHTML = Object.entries({ manual: 'וואטסאפ ידני', twilio: 'Twilio SMS/WhatsApp', whatsapp: 'WhatsApp Cloud API' })
            .map(([k, l]) => `<span class="badge ${ch[k] ? 'b-interested' : 'b-new'}" style="margin-left:6px">${ch[k] ? '✓' : '✗'} ${l}${ch[k] ? '' : ' – לא מוגדר'}</span>`).join('');
        $$('#channel option').forEach((o) => { if (!ch[o.value]) o.textContent = o.textContent.replace(/ \(לא מוגדר\)$/, '') + ' (לא מוגדר)'; });
        $('#wh-twilio').textContent = location.origin + '/api/agro/webhook/twilio';
        $('#wh-wa').textContent = location.origin + '/api/agro/webhook/whatsapp';
    }

    function renderTplPreview() {
        const c = state.customers.find((x) => x.items.length) ||
            { name: 'משק כהן', items: [{ vegetable: 'עגבניה', variety: '5656', quantity: '10,000', status: 'new' }, { vegetable: 'מלפפון', variety: '', quantity: '', status: 'new' }] };
        const items = c.items.filter((i) => i.status === 'new' || i.status === 'sent');
        const itemsText = (items.length ? items : c.items).map((i) => '• שתילי ' + i.vegetable + (i.variety ? ' זן ' + i.variety : '') + (i.quantity ? ` (${i.quantity})` : '')).join('\n');
        $('#tpl-preview').textContent = $('#template').value
            .replaceAll('{name}', c.name).replaceAll('{first_name}', c.name.split(' ')[0])
            .replaceAll('{items}', itemsText).replaceAll('{link}', location.origin + '/o/…');
    }

    $('#template').addEventListener('input', renderTplPreview);
    $('#tpl-reset').addEventListener('click', () => { $('#template').value = state.settings.default_template; renderTplPreview(); });
    $('#tpl-save').addEventListener('click', async () => {
        try {
            await api('/settings', { method: 'PUT', body: { template: $('#template').value } });
            toast('הנוסח נשמר');
        } catch (err) { toast(err.message); }
    });

    $('#reset-all').addEventListener('click', async () => {
        if (!confirm('למחוק את כל הלקוחות והתשובות? אין דרך לשחזר.')) return;
        if (prompt('הקלידו "מחק" לאישור') !== 'מחק') return;
        await api('/all', { method: 'DELETE' });
        toast('כל הנתונים נמחקו');
        refresh();
    });

    // ── Log ────────────────────────────────────────────────────
    async function loadLog() {
        const rows = await api('/messages?limit=100');
        $('#log').innerHTML = `<thead><tr><th>זמן</th><th>כיוון</th><th>ערוץ</th><th>לקוח</th><th>תוכן</th><th>סטטוס</th></tr></thead><tbody>` +
            (rows.length ? rows.map((m) => `<tr>
                <td style="white-space:nowrap">${fmtDate(m.created_at)}</td>
                <td>${m.direction === 'in' ? '⬅️ נכנס' : '➡️ יוצא'}</td>
                <td>${CHANNEL_LABEL[m.channel] || esc(m.channel)}</td>
                <td>${esc(m.name || '')} <span class="phone" style="color:var(--muted)">${esc(m.phone || '')}</span></td>
                <td style="white-space:pre-wrap;max-width:420px">${esc((m.body || '').slice(0, 400))}</td>
                <td>${esc(m.status || '')}</td></tr>`).join('') : '<tr><td colspan="6" class="empty">אין הודעות עדיין</td></tr>') + '</tbody>';
    }

    // ── Refresh loop ───────────────────────────────────────────
    async function refresh() {
        try {
            await Promise.all([loadStats(), loadCustomers()]);
            $('#live').textContent = 'עודכן ' + new Date().toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (err) { $('#live').textContent = 'שגיאת חיבור: ' + err.message; }
    }

    (async () => {
        await refresh();
        await loadSettings();
        setInterval(() => { if (!document.hidden && !$('#queue').classList.contains('show')) refresh(); }, 15000);
    })();
})();
