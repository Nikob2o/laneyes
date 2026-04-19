let allDevices = [];
let currentFilter = "all";
let currentSearch = "";
let currentTab = "dashboard";
let currentLogStatus = "all";
let currentLogType = "all";
let charts = {};  // chart instances for cleanup
const CHART_COLORS = ["#6c5ce7", "#00b894", "#fdcb6e", "#e17055", "#74b9ff", "#a29bfe", "#55efc4", "#ff7675"];

// --- Init ---
document.addEventListener("DOMContentLoaded", () => {
    loadDashboard();
});

// --- Tabs ---
function switchTab(tab, btn) {
    currentTab = tab;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");

    document.getElementById("tab-dashboard").classList.toggle("hidden", tab !== "dashboard");
    document.getElementById("tab-devices").classList.toggle("hidden", tab !== "devices");
    document.getElementById("tab-logs").classList.toggle("hidden", tab !== "logs");

    if (tab === "dashboard") loadDashboard();
    else if (tab === "devices") { loadStats(); loadDevices(currentFilter); }
    else if (tab === "logs") loadLogs();
}

// --- Dashboard ---
async function loadDashboard() {
    try {
        const data = await api("/api/dashboard");
        renderDashboardStats(data.stats);
        renderTimelineChart(data.timeline);
        renderVendorsChart(data.vendors);
        renderOsChart(data.os_families);
        renderNewDevices(data.new_devices);
        renderGhostDevices(data.ghost_devices);
        renderRecentEvents(data.recent_events);
    } catch (e) {
        console.error("Failed to load dashboard:", e);
    }
}

function renderDashboardStats(s) {
    document.getElementById("dash-total").textContent = s.total_devices;
    document.getElementById("dash-online-pct").textContent = `${s.online_percent}% online`;
    document.getElementById("dash-online").textContent = s.online;
    document.getElementById("dash-new").textContent = s.new_this_week;
    document.getElementById("dash-unnamed").textContent = s.unnamed;

    const lsEl = document.getElementById("dash-lastscan");
    const lsStatus = document.getElementById("dash-lastscan-status");
    if (s.last_scan) {
        lsEl.textContent = formatAgo(s.last_scan.age_seconds);
        lsStatus.textContent = `Last ${s.last_scan.scan_type} scan — ${s.last_scan.status}`;
    } else {
        lsEl.textContent = "Never";
        lsStatus.textContent = "Last scan";
    }
}

function destroyChart(id) {
    if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function renderTimelineChart(timeline) {
    destroyChart("timeline");
    const ctx = document.getElementById("chart-timeline");
    if (!ctx) return;
    const labels = timeline.map(p => new Date(p.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" }));
    const data = timeline.map(p => p.hosts);
    charts.timeline = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Hosts found",
                data,
                borderColor: "#6c5ce7",
                backgroundColor: "rgba(108, 92, 231, 0.15)",
                fill: true,
                tension: 0.3,
                pointBackgroundColor: "#6c5ce7",
                pointBorderColor: "#fff",
                pointRadius: 4,
            }],
        },
        options: chartBaseOptions({ showY: true }),
    });
}

function renderVendorsChart(vendors) {
    destroyChart("vendors");
    const ctx = document.getElementById("chart-vendors");
    if (!ctx) return;
    charts.vendors = new Chart(ctx, {
        type: "bar",
        data: {
            labels: vendors.map(v => v.name.length > 20 ? v.name.slice(0, 20) + "…" : v.name),
            datasets: [{
                data: vendors.map(v => v.count),
                backgroundColor: CHART_COLORS,
                borderRadius: 4,
            }],
        },
        options: {
            ...chartBaseOptions({ showY: false, noLegend: true }),
            indexAxis: "y",
        },
    });
}

function renderOsChart(osFamilies) {
    destroyChart("os");
    const ctx = document.getElementById("chart-os");
    if (!ctx) return;
    charts.os = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: osFamilies.map(o => o.name),
            datasets: [{
                data: osFamilies.map(o => o.count),
                backgroundColor: CHART_COLORS,
                borderColor: "#1a1d27",
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "right",
                    labels: { color: "#8b8fa3", font: { size: 11 }, boxWidth: 12 },
                },
            },
        },
    });
}

function chartBaseOptions({ showY = true, noLegend = true } = {}) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: !noLegend, labels: { color: "#8b8fa3" } },
            tooltip: { backgroundColor: "#1a1d27", borderColor: "#2a2d3a", borderWidth: 1 },
        },
        scales: {
            x: {
                ticks: { color: "#8b8fa3", font: { size: 11 } },
                grid: { color: "rgba(138, 143, 163, 0.08)" },
            },
            y: {
                display: showY,
                beginAtZero: true,
                ticks: { color: "#8b8fa3", font: { size: 11 }, precision: 0 },
                grid: { color: "rgba(138, 143, 163, 0.08)" },
            },
        },
    };
}

function renderNewDevices(devices) {
    const ul = document.getElementById("list-new-devices");
    if (devices.length === 0) {
        ul.innerHTML = '<li class="widget-empty">None in the last 7 days</li>';
        return;
    }
    ul.innerHTML = devices.map(d => `
        <li class="clickable" onclick="openDeviceModal(${d.id})">
            <div class="widget-device-main">
                <div class="widget-device-name" title="${esc(d.display_name)}">${esc(d.display_name)}</div>
                <div class="widget-device-meta">${esc(d.ip_address || "-")} &middot; ${esc(d.vendor || "unknown")}</div>
            </div>
            <span class="widget-time" title="${formatDate(d.first_seen)}">${formatAgoDate(d.first_seen)}</span>
        </li>
    `).join("");
}

function renderGhostDevices(devices) {
    const ul = document.getElementById("list-ghost-devices");
    if (devices.length === 0) {
        ul.innerHTML = '<li class="widget-empty">None</li>';
        return;
    }
    ul.innerHTML = devices.map(d => `
        <li class="clickable" onclick="openDeviceModal(${d.id})">
            <div class="widget-device-main">
                <div class="widget-device-name" title="${esc(d.display_name)}">${esc(d.display_name)}</div>
                <div class="widget-device-meta">${esc(d.mac_address)}</div>
            </div>
            <span class="widget-time" title="${formatDate(d.last_seen)}">${formatAgoDate(d.last_seen)}</span>
        </li>
    `).join("");
}

function renderRecentEvents(events) {
    const ul = document.getElementById("list-recent-events");
    if (events.length === 0) {
        ul.innerHTML = '<li class="widget-empty">No scans yet</li>';
        return;
    }
    ul.innerHTML = events.map(e => `
        <li class="clickable" onclick="openEventModal(${e.id})">
            <span class="status-badge ${e.status}">${e.status}</span>
            <span class="log-type-pill">${e.scan_type}</span>
            <div class="widget-device-main" style="flex: 1;">
                <div class="widget-device-meta" title="${esc(e.message || '')}">${esc(truncate(e.message, 60) || "-")}</div>
            </div>
            <span class="widget-time">${formatAgoDate(e.started_at)}</span>
        </li>
    `).join("");
}

function formatAgo(seconds) {
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function formatAgoDate(isoStr) {
    if (!isoStr) return "-";
    const seconds = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
    return formatAgo(seconds);
}

// --- API Helpers ---
async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
}

// --- Stats ---
async function loadStats() {
    try {
        const stats = await api("/api/stats");
        document.getElementById("stat-total").textContent = stats.total_devices;
        document.getElementById("stat-online").textContent = stats.online;
        document.getElementById("stat-offline").textContent = stats.offline;
        document.getElementById("stat-scans").textContent = stats.total_scans;
    } catch (e) {
        console.error("Failed to load stats:", e);
    }
}

// --- Devices ---
async function loadDevices(status) {
    try {
        const url = status && status !== "all" ? `/api/devices?status=${status}` : "/api/devices";
        allDevices = await api(url);
        renderDevices();
    } catch (e) {
        console.error("Failed to load devices:", e);
    }
}

function renderDevices() {
    const tbody = document.getElementById("devices-body");
    let devices = allDevices;

    if (currentSearch) {
        const q = currentSearch.toLowerCase();
        devices = devices.filter(d =>
            (d.display_name || "").toLowerCase().includes(q) ||
            (d.ip_address || "").toLowerCase().includes(q) ||
            (d.mac_address || "").toLowerCase().includes(q) ||
            (d.vendor || "").toLowerCase().includes(q) ||
            (d.hostname || "").toLowerCase().includes(q)
        );
    }

    if (devices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No devices found</td></tr>';
        return;
    }

    tbody.innerHTML = devices.map(d => `
        <tr>
            <td><span class="status-dot ${d.is_online ? 'online' : 'offline'}"></span></td>
            <td title="${esc(d.display_name)}${d.hostname && d.custom_name ? ' (' + esc(d.hostname) + ')' : ''}">
                <div class="device-name">${esc(d.display_name)}</div>
                ${d.custom_name && d.hostname ? `<div class="device-hostname">${esc(d.hostname)}</div>` : ""}
            </td>
            <td title="${esc(d.ip_address || '')}">${esc(d.ip_address || "-")}</td>
            <td title="${esc(d.mac_address)}">${esc(d.mac_address)}</td>
            <td title="${esc(d.vendor || '')}">${esc(d.vendor || "-")}</td>
            <td title="${esc(d.os_info || '')}">${esc(d.os_info || "-")}</td>
            <td title="${formatDate(d.first_seen)}">${formatDate(d.first_seen)}</td>
            <td title="${formatDate(d.last_seen)}">${formatDate(d.last_seen)}</td>
            <td>
                <div class="action-btns">
                    <button class="action-btn" onclick="openDeviceModal(${d.id})" title="Details">&#9776;</button>
                    <button class="action-btn" onclick="deepScanDevice(${d.id}, '${esc(d.ip_address)}')" title="Deep Scan">&#128269;</button>
                </div>
            </td>
        </tr>
    `).join("");
}

// --- Filtering & Search ---
function filterDevices(status, btn) {
    currentFilter = status;
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    loadDevices(status);
}

function searchDevices(query) {
    currentSearch = query;
    renderDevices();
}

// --- Scanning ---
async function quickScan() {
    showScanStatus("Quick scan in progress...");
    disableScanButtons(true);
    try {
        const result = await api("/api/scan/quick", { method: "POST" });
        showScanStatus(`Found ${result.hosts_found} hosts (${result.new_devices} new)`, 3000);
        loadDevices(currentFilter);
        loadStats();
    } catch (e) {
        showScanStatus("Scan failed: " + e.message, 5000);
    } finally {
        disableScanButtons(false);
    }
}

async function deepScanAll() {
    showScanStatus("Deep scan in progress (this may take a while)...");
    disableScanButtons(true);
    try {
        const result = await api("/api/scan/deep", { method: "POST" });
        showScanStatus(`Deep scan complete: ${result.devices_scanned} devices analyzed`, 3000);
        loadDevices(currentFilter);
        loadStats();
    } catch (e) {
        showScanStatus("Deep scan failed: " + e.message, 5000);
    } finally {
        disableScanButtons(false);
    }
}

async function deepScanDevice(deviceId, ip) {
    showScanStatus(`Deep scanning ${ip}...`);
    try {
        const result = await api("/api/scan/deep", {
            method: "POST",
            body: JSON.stringify({ target_ip: ip }),
        });
        showScanStatus("Deep scan complete", 3000);
        loadDevices(currentFilter);
        loadStats();
        // Refresh modal if open
        if (!document.getElementById("modal-overlay").classList.contains("hidden")) {
            openDeviceModal(deviceId);
        }
    } catch (e) {
        showScanStatus("Deep scan failed: " + e.message, 5000);
    }
}

function showScanStatus(text, autoHideMs) {
    const el = document.getElementById("scan-status");
    const textEl = document.getElementById("scan-status-text");
    textEl.textContent = text;
    el.classList.remove("hidden");
    if (autoHideMs) {
        setTimeout(() => el.classList.add("hidden"), autoHideMs);
    }
}

function disableScanButtons(disabled) {
    document.getElementById("btn-quick-scan").disabled = disabled;
    document.getElementById("btn-deep-scan").disabled = disabled;
}

// --- Device Modal ---
async function openDeviceModal(deviceId) {
    const overlay = document.getElementById("modal-overlay");
    const title = document.getElementById("modal-title");
    const body = document.getElementById("modal-body");

    try {
        const [device, history] = await Promise.all([
            api(`/api/devices/${deviceId}`),
            api(`/api/devices/${deviceId}/history`),
        ]);

        title.textContent = device.display_name;

        let portsHtml = "";
        if (device.open_ports) {
            try {
                const ports = JSON.parse(device.open_ports);
                if (ports.length > 0) {
                    portsHtml = `
                        <div class="section-title">Open Ports</div>
                        <table class="ports-table">
                            <thead><tr><th>Port</th><th>Protocol</th><th>State</th><th>Service</th><th>Version</th></tr></thead>
                            <tbody>
                                ${ports.map(p => `<tr>
                                    <td>${p.port}</td><td>${p.protocol}</td>
                                    <td>${p.state}</td><td>${p.service}</td><td>${p.version || "-"}</td>
                                </tr>`).join("")}
                            </tbody>
                        </table>
                    `;
                }
            } catch (_) {}
        }

        let historyHtml = "";
        if (history.length > 0) {
            historyHtml = `
                <div class="section-title">Scan History (last ${history.length})</div>
                <div class="history-list">
                    ${history.map(h => `
                        <div class="history-item">
                            <span>${esc(h.ip_address)}</span>
                            <span class="badge">${h.scan_type}</span>
                            <span class="time">${formatDate(h.scan_time)}</span>
                        </div>
                    `).join("")}
                </div>
            `;
        }

        body.innerHTML = `
            <div class="detail-grid">
                <div class="detail-item">
                    <label>Custom Name</label>
                    <input type="text" id="edit-custom-name" value="${esc(device.custom_name || "")}"
                           placeholder="Give this device a name...">
                </div>
                <div class="detail-item">
                    <label>Status</label>
                    <span>${device.is_online ? '<span class="status-dot online"></span> Online' : '<span class="status-dot offline"></span> Offline'}</span>
                </div>
                <div class="detail-item">
                    <label>IP Address</label>
                    <span>${esc(device.ip_address || "-")}</span>
                </div>
                <div class="detail-item">
                    <label>MAC Address</label>
                    <span>${esc(device.mac_address)}</span>
                </div>
                <div class="detail-item">
                    <label>Hostname</label>
                    <span>${esc(device.hostname || "-")}</span>
                </div>
                <div class="detail-item">
                    <label>Vendor</label>
                    <span>${esc(device.vendor || "-")}</span>
                </div>
                <div class="detail-item">
                    <label>OS Info</label>
                    <span>${esc(device.os_info || "Run deep scan to detect")}</span>
                </div>
                <div class="detail-item">
                    <label>First Seen</label>
                    <span>${formatDate(device.first_seen)}</span>
                </div>
                <div class="detail-item detail-full">
                    <label>Notes</label>
                    <textarea id="edit-notes" placeholder="Add notes about this device...">${esc(device.notes || "")}</textarea>
                </div>
            </div>
            ${portsHtml}
            ${historyHtml}
            <div class="modal-actions">
                <button class="btn btn-primary" onclick="saveDevice(${device.id})">Save Changes</button>
                <button class="btn btn-secondary" onclick="deepScanDevice(${device.id}, '${esc(device.ip_address)}')">Deep Scan</button>
                <button class="btn btn-small" style="background:var(--danger);color:#fff;margin-left:auto" onclick="deleteDevice(${device.id})">Delete</button>
            </div>
        `;

        overlay.classList.remove("hidden");
    } catch (e) {
        console.error("Failed to load device:", e);
    }
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById("modal-overlay").classList.add("hidden");
}

async function saveDevice(deviceId) {
    const customName = document.getElementById("edit-custom-name").value.trim();
    const notes = document.getElementById("edit-notes").value.trim();
    try {
        await api(`/api/devices/${deviceId}`, {
            method: "PUT",
            body: JSON.stringify({ custom_name: customName, notes: notes }),
        });
        loadDevices(currentFilter);
        showScanStatus("Device updated", 2000);
    } catch (e) {
        showScanStatus("Failed to save: " + e.message, 3000);
    }
}

async function deleteDevice(deviceId) {
    if (!confirm("Delete this device and its history?")) return;
    try {
        await api(`/api/devices/${deviceId}`, { method: "DELETE" });
        closeModal();
        loadDevices(currentFilter);
        loadStats();
        showScanStatus("Device deleted", 2000);
    } catch (e) {
        showScanStatus("Failed to delete: " + e.message, 3000);
    }
}

// --- Helpers ---
function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(isoStr) {
    if (!isoStr) return "-";
    const d = new Date(isoStr);
    return d.toLocaleDateString("fr-FR", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit",
    });
}

// Keyboard: close modals on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeModal();
        closeEventModal();
    }
});

// --- Logs ---
async function loadLogs() {
    const params = new URLSearchParams();
    if (currentLogType !== "all") params.set("type", currentLogType);
    if (currentLogStatus !== "all") params.set("status", currentLogStatus);

    try {
        const events = await api("/api/events?" + params.toString());
        renderLogs(events);
    } catch (e) {
        console.error("Failed to load logs:", e);
    }
}

function renderLogs(events) {
    const tbody = document.getElementById("logs-body");
    if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No scan events match these filters</td></tr>';
        return;
    }

    tbody.innerHTML = events.map(e => `
        <tr class="log-row" onclick="openEventModal(${e.id})">
            <td><span class="status-badge ${e.status}">${e.status}</span></td>
            <td><span class="log-type-pill">${e.scan_type}</span></td>
            <td title="${esc(e.target || '')}">${esc(e.target || "-")}</td>
            <td>${e.hosts_found ?? 0}</td>
            <td>${e.new_devices ?? 0}</td>
            <td>${formatDuration(e.duration_ms)}</td>
            <td title="${formatDate(e.started_at)}">${formatDate(e.started_at)}</td>
            <td title="${esc(e.message || '')}">${esc(e.message || "-")}</td>
        </tr>
    `).join("");
}

function filterLogs(status, btn) {
    currentLogStatus = status;
    document.querySelectorAll(".log-filter-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    loadLogs();
}

function filterLogType(type, btn) {
    currentLogType = type;
    document.querySelectorAll(".log-type-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    loadLogs();
}

async function clearLogs() {
    if (!confirm("Delete all scan event logs?")) return;
    try {
        await api("/api/events", { method: "DELETE" });
        loadLogs();
        showScanStatus("Logs cleared", 2000);
    } catch (e) {
        showScanStatus("Failed to clear: " + e.message, 3000);
    }
}

async function openEventModal(eventId) {
    try {
        const e = await api(`/api/events/${eventId}`);
        const body = document.getElementById("event-modal-body");
        const title = document.getElementById("event-modal-title");

        title.textContent = `${e.scan_type.toUpperCase()} scan — ${e.status}`;

        const isError = e.status === "failed";
        const messageHtml = isError
            ? `<pre class="traceback">${esc(e.message || "")}</pre>`
            : `<div style="color: var(--text); font-size: 0.9rem;">${esc(e.message || "-")}</div>`;

        body.innerHTML = `
            <div class="detail-grid">
                <div class="detail-item">
                    <label>Status</label>
                    <span><span class="status-badge ${e.status}">${e.status}</span></span>
                </div>
                <div class="detail-item">
                    <label>Type</label>
                    <span>${e.scan_type}</span>
                </div>
                <div class="detail-item">
                    <label>Target</label>
                    <span>${esc(e.target || "-")}</span>
                </div>
                <div class="detail-item">
                    <label>Duration</label>
                    <span>${formatDuration(e.duration_ms)}</span>
                </div>
                <div class="detail-item">
                    <label>Hosts Found</label>
                    <span>${e.hosts_found ?? 0}</span>
                </div>
                <div class="detail-item">
                    <label>New Devices</label>
                    <span>${e.new_devices ?? 0}</span>
                </div>
                <div class="detail-item">
                    <label>Started</label>
                    <span>${formatDate(e.started_at)}</span>
                </div>
                <div class="detail-item">
                    <label>Finished</label>
                    <span>${formatDate(e.finished_at)}</span>
                </div>
                <div class="detail-item detail-full">
                    <label>${isError ? "Error / Traceback" : "Message"}</label>
                    ${messageHtml}
                </div>
            </div>
        `;

        document.getElementById("event-modal-overlay").classList.remove("hidden");
    } catch (err) {
        console.error("Failed to load event:", err);
    }
}

function closeEventModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById("event-modal-overlay").classList.add("hidden");
}

function truncate(str, n) {
    if (!str) return "";
    return str.length > n ? str.slice(0, n) + "…" : str;
}

function formatDuration(ms) {
    if (ms == null) return "-";
    if (ms < 1000) return `${ms} ms`;
    const s = (ms / 1000).toFixed(1);
    if (ms < 60000) return `${s} s`;
    const m = Math.floor(ms / 60000);
    const rem = ((ms % 60000) / 1000).toFixed(0);
    return `${m}m ${rem}s`;
}
