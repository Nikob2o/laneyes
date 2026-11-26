/* Laneyes — interface (refonte du 26/11/2026).
   Sans bibliothèque : la courbe est une SVG, les vues se choisissent par l'ancre (#/…). */
"use strict";

const etat = {
    vue: "ensemble",
    filtreEtat: "online",
    aIdentifier: false,
    recherche: "",
    journal: "tous",
    fiche: null,          // appareil ouvert dans le panneau
};

const $ = (sel, racine = document) => racine.querySelector(sel);
const $$ = (sel, racine = document) => [...racine.querySelectorAll(sel)];

// --- Outils ---------------------------------------------------------------

async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const corps = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const err = new Error(corps.error || `HTTP ${resp.status}`);
        err.corps = corps;
        throw err;
    }
    return corps;
}

function esc(texte) {
    const d = document.createElement("div");
    d.textContent = texte == null ? "" : String(texte);
    return d.innerHTML;
}

// Les dates de l'API sont en UTC sans fuseau.
function dateUtc(iso) {
    if (!iso) return null;
    return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
}

function ilYa(iso) {
    const d = dateUtc(iso);
    if (!d) return "—";
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return "à l'instant";
    if (s < 3600) return `${Math.round(s / 60)} min`;
    if (s < 86400) return `${Math.round(s / 3600)} h`;
    return `${Math.round(s / 86400)} j`;
}

function ilYaPhrase(iso) {
    const t = ilYa(iso);
    return t === "à l'instant" || t === "—" ? t : `il y a ${t}`;
}

function dateCourte(iso) {
    const d = dateUtc(iso);
    if (!d) return "—";
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}

function dateHeure(iso) {
    const d = dateUtc(iso);
    if (!d) return "—";
    return `${d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" })} ${d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
}

function duree(ms) {
    if (ms == null) return "—";
    if (ms < 60000) return `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
    const min = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return s ? `${min} min ${s} s` : `${min} min`;
}

// Bit « administré localement » : les téléphones récents tirent une MAC au hasard.
function macPrivee(mac) {
    return !!mac && /^.[26ae]/i.test(mac);
}

function fabricant(d) {
    if (d.vendor) return d.vendor;
    return macPrivee(d.mac_address) ? "MAC privée" : "Inconnu";
}

function nomAffiche(d) {
    if (d.custom_name) return d.custom_name;
    if (d.hostname) return d.hostname;
    if (d.vendor) return `${d.vendor} · inconnu`;
    return "Appareil inconnu";
}

function systeme(os) {
    if (!os) return "Inconnu";
    const s = os.toLowerCase();
    if (/apple|mac os|ios|darwin/.test(s)) return "Apple";
    if (s.includes("windows")) return "Windows";
    if (s.includes("android")) return "Android";
    if (s.includes("qnap")) return "QNAP";
    if (/linux|ubuntu|debian|raspbian/.test(s)) return "Linux";
    if (/bsd/.test(s)) return "BSD";
    return "Autre";
}

function pastille(enLigne) {
    return `<span class="point ${enLigne ? "point-enligne" : "point-horsligne"}" aria-hidden="true"></span>`;
}

let minuteurAnnonce = null;
function annoncer(texte, erreur = false) {
    const el = $("#annonce");
    el.textContent = texte;
    el.classList.toggle("annonce-erreur", erreur);
    el.hidden = false;
    clearTimeout(minuteurAnnonce);
    minuteurAnnonce = setTimeout(() => { el.hidden = true; }, 5000);
}

// --- Navigation -----------------------------------------------------------

function lireAncre() {
    const ancre = location.hash.replace(/^#\/?/, "");
    if (ancre === "appareils") return { vue: "appareils", aIdentifier: false };
    if (ancre === "a-identifier") return { vue: "appareils", aIdentifier: true };
    if (ancre === "journal") return { vue: "journal" };
    return { vue: "ensemble" };
}

function afficherVue() {
    const cible = lireAncre();
    etat.vue = cible.vue;
    $$(".vue").forEach((v) => { v.hidden = true; });
    $$(".nav a").forEach((a) => a.removeAttribute("aria-current"));
    const nav = location.hash.replace(/^#\/?/, "") || "ensemble";
    const lien = $(`.nav a[data-vue="${nav === "" ? "ensemble" : nav}"]`) || $('.nav a[data-vue="ensemble"]');
    lien.setAttribute("aria-current", "page");

    if (cible.vue === "appareils") {
        etat.aIdentifier = cible.aIdentifier;
        // « Appareils » s'ouvre sur les appareils en ligne ; « À identifier » et une recherche, sur tous.
        etat.filtreEtat = cible.aIdentifier || etat.recherche ? "all" : "online";
        $("#filtre-a-identifier").checked = etat.aIdentifier;
        $("#titre-appareils").textContent = etat.aIdentifier ? "À identifier" : "Appareils";
        $("#vue-appareils").hidden = false;
        majSegments();
        chargerAppareils();
    } else if (cible.vue === "journal") {
        $("#vue-journal").hidden = false;
        chargerJournal();
    } else {
        $("#vue-ensemble").hidden = false;
        chargerEnsemble();
    }
    chargerComptes();
}

async function chargerComptes() {
    try {
        const c = await api("/api/devices/counts");
        $("#compte-appareils").textContent = c.total;
        $("#compte-a-identifier").textContent = c.a_identifier;
        $("#seg-online").textContent = c.online;
        $("#seg-offline").textContent = c.offline;
        $("#seg-all").textContent = c.total;
        return c;
    } catch (e) {
        return null;
    }
}

// --- Vue d'ensemble -------------------------------------------------------

async function chargerEnsemble() {
    let data;
    try {
        data = await api("/api/dashboard");
    } catch (e) {
        annoncer("Impossible de charger la vue d'ensemble.", true);
        return;
    }
    const s = data.stats;
    $("#ch-enligne").textContent = s.online;
    $("#ch-enligne-pied").textContent = `sur ${s.total_devices} appareil${s.total_devices > 1 ? "s" : ""} connu${s.total_devices > 1 ? "s" : ""}`;
    $("#ch-nouveaux").textContent = s.new_this_week;
    const debutSemaine = new Date(Date.now() - 7 * 86400000);
    $("#ch-nouveaux-pied").textContent = `première apparition depuis le ${debutSemaine.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}`;
    $("#ch-a-identifier").textContent = s.unnamed;
    $("#ch-fantomes").textContent = s.ghosts;
    $("[data-archiver-fantomes]").disabled = s.ghosts === 0;
    $("#lien-enligne").textContent = `Les ${s.online} appareils en ligne`;

    const scan = s.last_scan;
    const etatScan = $("#etat-scan");
    if (scan) {
        const ok = scan.status !== "failed";
        const morceaux = [`Dernier scan ${ilYaPhrase(scan.started_at)}`];
        if (ok) morceaux.push(`${scan.hosts_found} hôte${scan.hosts_found > 1 ? "s" : ""}`);
        else morceaux.push("échec");
        if (scan.duration_ms != null) morceaux.push(duree(scan.duration_ms));
        etatScan.innerHTML = `<span class="point ${ok ? "point-enligne" : "point-echec"}" aria-hidden="true"></span>${esc(morceaux.join(" · "))}`;
    } else {
        etatScan.textContent = "Aucun scan pour l'instant";
    }

    dessinerCourbe(data.timeline);

    const nouveaux = $("#liste-nouveaux");
    nouveaux.innerHTML = data.new_devices.length ? data.new_devices.map((d) => `
        <li class="ligne-liste">
            ${pastille(d.is_online)}
            <button class="ligne-liste-texte" type="button" data-fiche="${d.id}">
                <span class="${d.custom_name ? "" : "sans-nom"} tronque">${esc(nomAffiche(d))}</span>
                <span class="mono petit">${esc(d.ip_address || "—")} · ${esc(ilYaPhrase(d.first_seen))}</span>
            </button>
            ${d.custom_name ? "" : `<button class="btn btn-petit" type="button" data-nommer="${d.id}">Nommer</button>`}
        </li>`).join("") : `<li class="vide">Aucun nouvel appareil depuis 7 jours.</li>`;

    $("#corps-enligne").innerHTML = data.online_devices.length ? data.online_devices.map((d) => `
        <tr class="ligne" data-fiche="${d.id}" tabindex="0">
            <td><span class="cellule-nom">${pastille(true)}<span class="${d.custom_name ? "" : "sans-nom"} tronque">${esc(nomAffiche(d))}</span></span></td>
            <td class="mono">${esc(d.ip_address || "—")}</td>
            <td class="mono discret">${esc(d.mac_address)}</td>
            <td class="secondaire tronque">${esc(fabricant(d))}</td>
            <td class="mono discret">${esc(ilYa(d.first_seen))}</td>
        </tr>`).join("") : `<tr><td colspan="5" class="vide">Aucun appareil en ligne. Lancez un scan rapide.</td></tr>`;
}

function dateJM(iso) {
    return `${iso.slice(8)}/${iso.slice(5, 7)}`;
}

// Le dernier point est la journée en cours : tracé en pointillé, et jamais pris comme
// référence (son maximum n'est pas encore atteint). La comparaison se fait sur la
// dernière journée complète.
function dessinerCourbe(points) {
    const conteneur = $("#courbe");
    const valeurs = points.map((p) => p.hosts);
    const connues = valeurs.filter((v) => v != null);
    if (!connues.length) {
        conteneur.innerHTML = `<p class="vide">Pas encore de scan rapide sur les 7 derniers jours.</p>`;
        $("#courbe-ecart").textContent = "";
        return;
    }
    // Largeur réelle du conteneur : les graduations gardent 11 px, même sur téléphone.
    const L = Math.max(300, Math.round(conteneur.clientWidth || 760)), H = L < 500 ? 200 : 250;
    const g = 40, d = L < 500 ? 24 : 16, h = 24, b = 30;
    let min = Math.min(...connues), max = Math.max(...connues);
    const pas = Math.max(1, Math.ceil((max - min + 2) / 4 / 5) * 5);
    min = Math.max(0, Math.floor((min - 1) / pas) * pas);
    max = min + pas * 4;
    const x = (i) => g + (i * (L - g - d)) / (points.length - 1);
    const y = (v) => h + ((max - v) * (H - h - b)) / (max - min);
    const iJour = points.length - 1;

    const grille = [0, 1, 2, 3, 4].map((k) => {
        const v = min + k * pas;
        return `<line x1="${g}" y1="${y(v)}" x2="${L - d}" y2="${y(v)}"/><text x="${g - 10}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    }).join("");

    // Journées complètes : trait plein ; une journée sans scan coupe la courbe.
    const segments = [];
    let courant = [];
    points.slice(0, iJour).forEach((p, i) => {
        if (p.hosts == null) { if (courant.length) segments.push(courant); courant = []; }
        else courant.push([x(i), y(p.hosts)]);
    });
    if (courant.length) segments.push(courant);
    const traces = segments.map((seg) => {
        const pts = seg.map(([a, c]) => `${a},${c}`).join(" ");
        const aire = seg.length > 1 ? `<polygon class="courbe-aire" points="${pts} ${seg[seg.length - 1][0]},${H - b} ${seg[0][0]},${H - b}"/>` : "";
        return `${aire}<polyline class="courbe-ligne" points="${pts}"/>`;
    }).join("");

    // Journée en cours : pointillé depuis la veille, point creux et libellé.
    const jour = points[iJour];
    let enCours = "";
    if (jour.hosts != null) {
        const veille = points[iJour - 1];
        const depart = veille && veille.hosts != null ? `<line class="courbe-en-cours" x1="${x(iJour - 1)}" y1="${y(veille.hosts)}" x2="${x(iJour)}" y2="${y(jour.hosts)}"/>` : "";
        enCours = `${depart}<circle class="courbe-point-en-cours" cx="${x(iJour)}" cy="${y(jour.hosts)}" r="4"/>`;
    }

    // Dernier point d'une journée complète, mis en avant.
    const complets = points.slice(0, iJour).map((p, i) => ({ ...p, i })).filter((p) => p.hosts != null);
    const premier = complets[0];
    const dernier = complets[complets.length - 1];
    const pointPlein = dernier ? `<circle class="courbe-point" cx="${x(dernier.i)}" cy="${y(dernier.hosts)}" r="4"/>` : "";

    const etiquettes = points.map((p, i) => {
        const [, mois, j] = p.date.split("-");
        if (L < 500 && i % 2 && i !== iJour) return "";
        return `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${i === 0 ? `${j}/${mois}` : j}</text>`;
    }).join("");

    const morceaux = [];
    if (premier) morceaux.push(`${premier.hosts} le ${dateJM(premier.date)}`);
    if (dernier && dernier !== premier) morceaux.push(`${dernier.hosts} le ${dateJM(dernier.date)}`);
    if (jour.hosts != null) morceaux.push(`${jour.hosts} aujourd'hui, journée en cours`);
    conteneur.innerHTML = `<svg class="courbe" viewBox="0 0 ${L} ${H}" role="img" aria-label="${esc("Maximum d'appareils en ligne par jour : " + morceaux.join(", "))}">
        <g class="courbe-grille">${grille}</g>${traces}${enCours}${pointPlein}
        <g class="courbe-axe">${etiquettes}</g></svg>
        ${jour.hosts != null ? `<p class="courbe-legende"><svg aria-hidden="true" width="24" height="8"><line class="courbe-en-cours" x1="2" y1="4" x2="22" y2="4"/></svg>Aujourd'hui, en cours : ${jour.hosts} pour l'instant</p>` : ""}`;

    if (premier && dernier && dernier !== premier) {
        const ecart = dernier.hosts - premier.hosts;
        $("#courbe-ecart").textContent =
            `${ecart > 0 ? "+" : ecart < 0 ? "−" : "±"}${Math.abs(ecart)} du ${dateJM(premier.date)} au ${dateJM(dernier.date)}`;
    } else {
        $("#courbe-ecart").textContent = "";
    }
}

// --- Appareils ------------------------------------------------------------

function majSegments() {
    $$("[data-etat]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.etat === etat.filtreEtat)));
}

let jetonAppareils = 0;
async function chargerAppareils() {
    const params = new URLSearchParams();
    if (etat.filtreEtat !== "all") params.set("status", etat.filtreEtat);
    if (etat.aIdentifier) params.set("a_identifier", "1");
    if (etat.recherche) params.set("q", etat.recherche);
    const jeton = ++jetonAppareils;
    let liste;
    try {
        liste = await api(`/api/devices?${params}`);
    } catch (e) {
        annoncer("Impossible de charger les appareils.", true);
        return;
    }
    if (jeton !== jetonAppareils) return;  // une frappe plus récente a déjà relancé la requête
    const corps = $("#corps-appareils");
    corps.innerHTML = liste.length ? liste.map((d) => `
        <tr class="ligne" data-fiche="${d.id}" tabindex="0">
            <td><span class="cellule-nom">${pastille(d.is_online)}<span class="nom-pile">
                <span class="${d.custom_name ? "" : "sans-nom"} tronque">${esc(nomAffiche(d))}</span>
                <span class="petit tronque">${esc(d.custom_name && d.hostname ? d.hostname : "—")}</span></span></span></td>
            <td class="mono">${esc(d.ip_address || "—")}</td>
            <td class="mono discret">${esc(d.mac_address)}</td>
            <td class="secondaire tronque">${esc(fabricant(d))}</td>
            <td class="secondaire">${esc(systeme(d.os_info))}</td>
            <td class="mono discret">${esc(ilYa(d.last_seen))}</td>
            <td class="cellule-action">${d.custom_name ? "" : `<button class="btn btn-petit" type="button" data-nommer="${d.id}">Nommer</button>`}</td>
        </tr>`).join("") : `<tr><td colspan="7" class="vide">${etat.recherche ? "Aucun appareil ne correspond à cette recherche." : "Aucun appareil dans ce filtre."}</td></tr>`;

    const c = await chargerComptes();
    if (c) {
        const morceaux = [`${liste.length} appareil${liste.length > 1 ? "s" : ""} affiché${liste.length > 1 ? "s" : ""}`];
        if (c.fantomes) morceaux.push(`${c.fantomes} hors ligne depuis plus de 7 jours, archivables en une fois`);
        $("#note-appareils").innerHTML = esc(morceaux.join(" · ")) +
            (c.fantomes ? ` · <button class="lien" type="button" data-archiver-fantomes>Archiver les fantômes</button>` : "");
    }
}

// --- Fiche ----------------------------------------------------------------

async function ouvrirFiche(id, { nommer = false } = {}) {
    let d, presence;
    try {
        [d, presence] = await Promise.all([api(`/api/devices/${id}`), api(`/api/devices/${id}/presence?days=14`)]);
    } catch (e) {
        annoncer("Impossible d'ouvrir la fiche.", true);
        return;
    }
    etat.fiche = d;
    $("#fiche-etat").innerHTML = `${pastille(d.is_online)}${esc(d.is_online ? `En ligne, vu ${ilYaPhrase(d.last_seen)}` : `Hors ligne, vu ${ilYaPhrase(d.last_seen)}`)}`;
    const nom = $("#fiche-nom");
    nom.value = d.custom_name || "";
    nom.placeholder = "Donner un nom à cet appareil";
    $("#fiche-notes").value = d.notes || "";

    const champs = [
        ["Adresse IP", d.ip_address || "—", true],
        ["MAC", d.mac_address, true],
        ["Nom d'hôte", d.hostname || "—", false],
        ["Fabricant", fabricant(d), false],
        ["Système", d.os_info || "Inconnu · lancer un scan approfondi", false],
        ["Vu la 1re fois", dateHeure(d.first_seen), true],
        ["Vu la dernière", ilYaPhrase(d.last_seen), true],
    ];
    $("#fiche-champs").innerHTML = champs.map(([k, v, mono]) =>
        `<dt>${esc(k)}</dt><dd class="${mono ? "mono" : ""}">${esc(v)}</dd>`).join("");

    const jours = presence.filter((j) => j.present).length;
    const frise = $("#fiche-frise");
    frise.setAttribute("aria-label", `Vu ${jours} jour${jours > 1 ? "s" : ""} sur les 14 derniers`);
    frise.innerHTML = presence.map((j) =>
        `<span class="frise-jour${j.present ? " present" : ""}" title="${esc(dateCourte(j.date))}${j.present ? " : vu" : " : absent"}"></span>`).join("");
    $("#fiche-frise-axe").innerHTML = `<span>${esc(dateCourte(presence[0].date))}</span><span>${esc(dateCourte(presence[presence.length - 1].date))}</span>`;

    let ports = [];
    try { ports = d.open_ports ? JSON.parse(d.open_ports) : []; } catch (e) { ports = []; }
    $("#fiche-ports").innerHTML = ports.length
        ? `<ul class="ports">${ports.map((p) => `<li><span class="mono">${esc(p.port)}/${esc(p.protocol || "tcp")}</span><span class="secondaire">${esc([p.service, p.product, p.version].filter(Boolean).join(" ") || "—")}</span></li>`).join("")}</ul>`
        : `<p class="vide-court">Pas encore de scan approfondi pour cet appareil.</p>`;
    $("#fiche-archiver").textContent = d.archived ? "Désarchiver" : "Archiver";

    $("#voile").hidden = false;
    $("#fiche").hidden = false;
    document.body.classList.add("fiche-ouverte");
    if (nommer) { nom.focus(); nom.select(); } else { $("#fiche-fermer").focus(); }
}

function fermerFiche() {
    $("#voile").hidden = true;
    $("#fiche").hidden = true;
    document.body.classList.remove("fiche-ouverte");
    etat.fiche = null;
}

async function enregistrerFiche() {
    const d = etat.fiche;
    if (!d) return;
    try {
        await api(`/api/devices/${d.id}`, {
            method: "PUT",
            body: JSON.stringify({ custom_name: $("#fiche-nom").value, notes: $("#fiche-notes").value }),
        });
    } catch (e) {
        annoncer("Enregistrement impossible.", true);
        return;
    }
    annoncer("Fiche enregistrée.");
    fermerFiche();
    rafraichir();
}

async function archiverFiche() {
    const d = etat.fiche;
    if (!d) return;
    try {
        await api(`/api/devices/${d.id}/${d.archived ? "unarchive" : "archive"}`, { method: "POST" });
    } catch (e) {
        annoncer("Archivage impossible.", true);
        return;
    }
    annoncer(d.archived ? "Appareil désarchivé." : `« ${nomAffiche(d)} » archivé : il ne s'affiche plus dans les listes.`);
    fermerFiche();
    rafraichir();
}

// --- Fantômes -------------------------------------------------------------

async function archiverFantomes() {
    let n;
    try {
        n = (await api("/api/devices/counts")).fantomes;
    } catch (e) { return; }
    if (!n) { annoncer("Aucun fantôme à archiver."); return; }
    const dialogue = $("#dialogue-fantomes");
    $("#dialogue-texte").textContent = `${n} appareil${n > 1 ? "s" : ""} hors ligne depuis plus de 7 jours ${n > 1 ? "seront masqués" : "sera masqué"} des listes. Rien n'est supprimé, et un appareil qui revient sur le réseau réapparaît de lui-même.`;
    dialogue.returnValue = "";
    dialogue.showModal();
    dialogue.addEventListener("close", async () => {
        if (dialogue.returnValue !== "oui") return;
        try {
            const r = await api("/api/devices/archive-ghosts", { method: "POST", body: JSON.stringify({ confirm: true }) });
            annoncer(`${r.archived} appareil${r.archived > 1 ? "s" : ""} archivé${r.archived > 1 ? "s" : ""}.`);
        } catch (e) {
            annoncer("Archivage impossible.", true);
        }
        rafraichir();
    }, { once: true });
}

// --- Scans ----------------------------------------------------------------

async function lancerScan(type, cible = null) {
    const boutons = $$("[data-scan], #fiche-scan");
    boutons.forEach((b) => { b.disabled = true; });
    annoncer(type === "quick" ? "Scan rapide en cours…" : "Scan approfondi en cours, cela peut prendre quelques minutes…");
    try {
        const r = await api(`/api/scan/${type}`, { method: "POST", body: JSON.stringify(cible ? { target_ip: cible } : {}) });
        if (type === "quick") {
            annoncer(`Scan terminé : ${r.hosts_found} hôte${r.hosts_found > 1 ? "s" : ""}, ${r.new_devices} nouveau${r.new_devices > 1 ? "x" : ""}.`);
        } else {
            annoncer(`Scan approfondi terminé : ${r.devices_scanned} appareil${r.devices_scanned > 1 ? "s" : ""} analysé${r.devices_scanned > 1 ? "s" : ""}.`);
        }
    } catch (e) {
        annoncer("Le scan a échoué ; le détail est dans le journal.", true);
    } finally {
        boutons.forEach((b) => { b.disabled = false; });
    }
    if (cible && etat.fiche) ouvrirFiche(etat.fiche.id);
    rafraichir();
}

// --- Journal --------------------------------------------------------------

const TYPES = { quick: "Rapide", deep: "Approfondi" };

async function chargerJournal() {
    const params = new URLSearchParams({ limit: "200" });
    if (etat.journal === "quick" || etat.journal === "deep") params.set("type", etat.journal);
    if (etat.journal === "failed") params.set("status", "failed");
    let evenements;
    try {
        evenements = await api(`/api/events?${params}`);
    } catch (e) {
        annoncer("Impossible de charger le journal.", true);
        return;
    }
    $$("[data-journal]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.journal === etat.journal)));
    $("#corps-journal").innerHTML = evenements.length ? evenements.map((e) => {
        const echec = e.status === "failed";
        const d = dateUtc(e.started_at);
        const heure = d ? `${d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}` : "—";
        return `<tr class="ligne-journal"${echec && e.message ? ` title="${esc(e.message.split("\n")[0])}"` : ""}>
            <td><span class="cellule-nom"><span class="point ${echec ? "point-echec" : "point-enligne"}" aria-hidden="true"></span><span class="mono">${esc(heure)}</span>${echec ? `<span class="sr">échec</span>` : ""}</span></td>
            <td class="secondaire">${esc(TYPES[e.scan_type] || e.scan_type)}</td>
            <td class="mono discret">${esc(e.target || "—")}</td>
            <td class="nombre mono">${echec ? "—" : esc(e.hosts_found)}</td>
            <td class="nombre mono ${e.new_devices ? "" : "discret"}">${echec ? "—" : esc(e.new_devices)}</td>
            <td class="nombre mono secondaire">${esc(duree(e.duration_ms))}</td>
        </tr>`;
    }).join("") : `<tr><td colspan="6" class="vide">Aucun scan dans ce filtre.</td></tr>`;
}

// --- Câblage --------------------------------------------------------------

function rafraichir() {
    if (etat.vue === "appareils") chargerAppareils();
    else if (etat.vue === "journal") chargerJournal();
    else chargerEnsemble();
    chargerComptes();
}

document.addEventListener("click", (ev) => {
    const nommer = ev.target.closest("[data-nommer]");
    if (nommer) { ouvrirFiche(nommer.dataset.nommer, { nommer: true }); return; }
    const fiche = ev.target.closest("[data-fiche]");
    if (fiche) { ouvrirFiche(fiche.dataset.fiche); return; }
    const scan = ev.target.closest("[data-scan]");
    if (scan) { lancerScan(scan.dataset.scan); return; }
    if (ev.target.closest("[data-archiver-fantomes]")) { archiverFantomes(); return; }
    const seg = ev.target.closest("[data-etat]");
    if (seg) { etat.filtreEtat = seg.dataset.etat; majSegments(); chargerAppareils(); return; }
    const j = ev.target.closest("[data-journal]");
    if (j) { etat.journal = j.dataset.journal; chargerJournal(); }
});

document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && etat.fiche) { fermerFiche(); return; }
    if (ev.key === "Enter" && ev.target.matches("tr[data-fiche]")) ouvrirFiche(ev.target.dataset.fiche);
});

let minuteurRecherche = null;
$("#recherche-appareils").addEventListener("input", (ev) => {
    etat.recherche = ev.target.value.trim();
    clearTimeout(minuteurRecherche);
    minuteurRecherche = setTimeout(chargerAppareils, 200);
});
$("#filtre-a-identifier").addEventListener("change", (ev) => {
    etat.aIdentifier = ev.target.checked;
    $("#titre-appareils").textContent = etat.aIdentifier ? "À identifier" : "Appareils";
    chargerAppareils();
});
// La recherche de la vue d'ensemble ouvre la liste complète, filtrée.
$("[data-recherche-globale]").addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    etat.recherche = ev.target.value.trim();
    etat.filtreEtat = "all";
    $("#recherche-appareils").value = etat.recherche;
    location.hash = "#/appareils";
});
$("#fiche-fermer").addEventListener("click", fermerFiche);
$("#voile").addEventListener("click", fermerFiche);
$("#fiche-enregistrer").addEventListener("click", enregistrerFiche);
$("#fiche-nom").addEventListener("keydown", (ev) => { if (ev.key === "Enter") enregistrerFiche(); });
$("#fiche-archiver").addEventListener("click", archiverFiche);
$("#fiche-scan").addEventListener("click", () => { if (etat.fiche) lancerScan("deep", etat.fiche.ip_address); });

window.addEventListener("hashchange", afficherVue);
afficherVue();
