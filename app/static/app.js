let allDevices = [];
let currentFilter = "all";
let currentSearch = "";

// --- Init ---
document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    loadDevices();
});

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
            <td>
                <div class="device-name">${esc(d.display_name)}</div>
                ${d.custom_name && d.hostname ? `<div class="device-hostname">${esc(d.hostname)}</div>` : ""}
            </td>
            <td>${esc(d.ip_address || "-")}</td>
            <td>${esc(d.mac_address)}</td>
            <td>${esc(d.vendor || "-")}</td>
            <td>${esc(d.os_info || "-")}</td>
            <td>${formatDate(d.first_seen)}</td>
            <td>${formatDate(d.last_seen)}</td>
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

// Keyboard: close modal on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
});
