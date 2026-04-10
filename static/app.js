var currentPlate = '';
var pollInterval = null;
var spacesData = [];

function showAlert(id, msg) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 6000);
}

function formatDate(iso) {
    if (!iso) return '--';
    var d = new Date(iso);
    return d.toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' });
}

function formatDuration(minutes) {
    var h = Math.floor(minutes / 60);
    var m = Math.round(minutes % 60);
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
}

async function loadStats() {
    try {
        var resp = await fetch('/v1/admin/stats');
        var data = await resp.json();
        var occ = document.getElementById('occupiedCount');
        var avail = document.getElementById('availableCount');
        if (occ) occ.textContent = data.occupied;
        if (avail) avail.textContent = data.available;
    } catch (e) { /* silent */ }
}

async function handleEntry(e) {
    e.preventDefault();
    var btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = 'Registering...';
    try {
        var resp = await fetch('/v1/entry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plate_number: document.getElementById('plateNumber').value.trim(),
                driver_phone: document.getElementById('driverPhone').value.trim(),
                driver_email: document.getElementById('driverEmail').value.trim(),
                space_number: parseInt(document.getElementById('spaceNumber').value)
            })
        });
        var data = await resp.json();
        if (!resp.ok) {
            showAlert('alertError', data.detail || 'Registration failed');
        } else {
            showAlert('alertSuccess', 'Vehicle ' + data.plate + ' registered in space #' + data.space);
            document.getElementById('entryForm').reset();
            loadStats();
        }
    } catch (err) {
        showAlert('alertError', 'Network error: ' + err.message);
    }
    btn.disabled = false;
    btn.textContent = 'Register Entry';
}

async function handleLookup(e) {
    e.preventDefault();
    var plate = document.getElementById('exitPlate').value.trim();
    if (!plate) return;
    try {
        var resp = await fetch('/v1/exit/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plate_number: plate })
        });
        var data = await resp.json();
        if (!resp.ok) {
            showAlert('alertError', data.detail || 'Vehicle not found');
            return;
        }
        currentPlate = data.plate;
        document.getElementById('sumPlate').textContent = data.plate;
        document.getElementById('sumSpace').textContent = '#' + data.space_number;
        document.getElementById('sumEntry').textContent = formatDate(data.entry_time);
        document.getElementById('sumDuration').textContent = formatDuration(data.duration_minutes);
        document.getElementById('sumPhone').textContent = data.driver_phone;
        document.getElementById('sumAmount').textContent = 'KES ' + data.amount.toLocaleString();
        document.getElementById('lookupSection').classList.add('hidden');
        document.getElementById('summarySection').classList.remove('hidden');
    } catch (err) {
        showAlert('alertError', 'Network error: ' + err.message);
    }
}

async function initiatePayment() {
    var btn = document.getElementById('payBtn');
    btn.disabled = true;
    btn.textContent = 'Sending STK Push...';
    try {
        var resp = await fetch('/v1/exit/initiate-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plate_number: currentPlate })
        });
        var data = await resp.json();
        if (!resp.ok) {
            showAlert('alertError', data.detail || 'Payment initiation failed');
            btn.disabled = false;
            btn.textContent = 'Send M-Pesa STK Push';
            return;
        }
        if (data.status === 'free_exit') {
            document.getElementById('summarySection').classList.add('hidden');
            document.getElementById('freeExitSection').classList.remove('hidden');
            return;
        }
        document.getElementById('payPhone').textContent = data.phone;
        document.getElementById('payAmount').textContent = 'KES ' + data.amount.toLocaleString();
        document.getElementById('payRef').textContent = data.ref;
        document.getElementById('summarySection').classList.add('hidden');
        document.getElementById('paymentSection').classList.remove('hidden');
        if (data.stk_error) {
            console.warn('STK Push error:', data.stk_error);
        }
        startPolling(currentPlate, data.amount, data.ref);
    } catch (err) {
        showAlert('alertError', 'Network error: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'Send M-Pesa STK Push';
    }
}

function startPolling(plate, amount, ref) {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async function () {
        try {
            var resp = await fetch('/v1/exit/payment-status/' + encodeURIComponent(plate));
            var data = await resp.json();
            if (data.payment_status === 'COMPLETED') {
                clearInterval(pollInterval);
                pollInterval = null;
                document.getElementById('gateAmount').textContent = 'KES ' + (data.amount || amount).toLocaleString();
                document.getElementById('gateRef').textContent = data.ref || ref;
                document.getElementById('paymentSection').classList.add('hidden');
                document.getElementById('gateSection').classList.remove('hidden');
            }
        } catch (e) { /* continue polling */ }
    }, 1000);
}

function resetExit() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    currentPlate = '';
    document.getElementById('lookupSection').classList.remove('hidden');
    document.getElementById('summarySection').classList.add('hidden');
    document.getElementById('paymentSection').classList.add('hidden');
    document.getElementById('gateSection').classList.add('hidden');
    document.getElementById('freeExitSection').classList.add('hidden');
    document.getElementById('exitPlate').value = '';
    var btn = document.getElementById('payBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Send M-Pesa STK Push'; }
}

async function loadAdminDashboard() {
    try {
        var resp = await fetch('/v1/admin/stats');
        var stats = await resp.json();
        document.getElementById('statOccupied').textContent = stats.occupied;
        document.getElementById('statAvailable').textContent = stats.available;
        document.getElementById('statRevenue').textContent = stats.revenue_today.toLocaleString();
        document.getElementById('statExits').textContent = stats.exits_today;
    } catch (e) { /* silent */ }
    try {
        var resp2 = await fetch('/v1/admin/recent-exits');
        var exits = await resp2.json();
        var tbody = document.getElementById('exitsTable');
        if (exits.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-dim)">No exits yet today</td></tr>';
            return;
        }
        tbody.innerHTML = exits.map(function (ex) {
            return '<tr>' +
                '<td><strong>' + ex.plate_number + '</strong></td>' +
                '<td>#' + ex.space_number + '</td>' +
                '<td>' + formatDate(ex.entry_time) + '</td>' +
                '<td>' + formatDate(ex.exit_time) + '</td>' +
                '<td>' + formatDuration(ex.duration_minutes) + '</td>' +
                '<td style="color:var(--accent)">KES ' + ex.amount.toLocaleString() + '</td>' +
                '<td><code>' + (ex.transaction_ref || '--') + '</code></td>' +
                '<td><span class="badge badge-success">Paid</span></td>' +
                '</tr>';
        }).join('');
    } catch (e) { /* silent */ }
}

async function loadParkingMap() {
    try {
        var resp = await fetch('/v1/spaces');
        spacesData = await resp.json();
        renderMap(spacesData);
        var occupied = spacesData.filter(function (s) { return s.is_occupied; }).length;
        document.getElementById('occupancySummary').textContent =
            occupied + ' occupied / ' + (spacesData.length - occupied) + ' available of ' + spacesData.length + ' total';
    } catch (e) {
        document.getElementById('parkingGrid').innerHTML = '<p style="color:var(--danger)">Failed to load map data</p>';
    }
}

function renderMap(spaces) {
    var grid = document.getElementById('parkingGrid');
    grid.innerHTML = spaces.map(function (s) {
        var cls = s.is_occupied ? 'occupied' : 'available';
        return '<div class="space-cell ' + cls + '" data-space="' + s.space_number + '" ' +
            'onclick="showSpaceDetail(' + s.space_number + ')" title="Space #' + s.space_number + '">' +
            s.space_number + '</div>';
    }).join('');
}

function filterMap() {
    var filter = document.getElementById('mapFilter').value;
    var search = document.getElementById('mapSearch').value.trim().toUpperCase();
    var filtered = spacesData.filter(function (s) {
        if (filter === 'available' && s.is_occupied) return false;
        if (filter === 'occupied' && !s.is_occupied) return false;
        if (search && s.plate_number && s.plate_number.toUpperCase().indexOf(search) === -1 && !String(s.space_number).includes(search)) return false;
        if (search && !s.plate_number && !String(s.space_number).includes(search)) return false;
        return true;
    });
    renderMap(filtered);
}

async function showSpaceDetail(num) {
    document.getElementById('modalTitle').textContent = 'Space #' + num;
    var content = document.getElementById('modalContent');
    content.innerHTML = '<div class="loader"></div> Loading...';
    document.getElementById('spaceModal').classList.add('show');
    try {
        var resp = await fetch('/v1/spaces/' + num);
        var data = await resp.json();
        if (data.is_occupied) {
            var entry = new Date(data.entry_time);
            var now = new Date();
            var dur = (now - entry) / 60000;
            content.innerHTML =
                '<div class="info-row"><span class="label">Status</span><span class="badge badge-warning">Occupied</span></div>' +
                '<div class="info-row"><span class="label">Plate</span><span><strong>' + data.plate_number + '</strong></span></div>' +
                '<div class="info-row"><span class="label">Phone</span><span>' + data.driver_phone + '</span></div>' +
                '<div class="info-row"><span class="label">Email</span><span>' + data.driver_email + '</span></div>' +
                '<div class="info-row"><span class="label">Entry Time</span><span>' + formatDate(data.entry_time) + '</span></div>' +
                '<div class="info-row"><span class="label">Duration</span><span>' + formatDuration(dur) + '</span></div>';
        } else {
            content.innerHTML =
                '<div class="info-row"><span class="label">Status</span><span class="badge badge-success">Available</span></div>' +
                '<p style="margin-top:16px;color:var(--text-dim);text-align:center">This space is currently empty.</p>';
        }
    } catch (e) {
        content.innerHTML = '<p style="color:var(--danger)">Error loading space details</p>';
    }
}

function closeModal() {
    document.getElementById('spaceModal').classList.remove('show');
}

document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeModal();
});
