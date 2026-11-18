/* Radar Ambiental BR — dashboard demo */
const S = {
  data: null,
  geo: null,
  map: null,
  stateLayer: null,
  pointLayer: null,
  filtered: [],
  selected: null,
};

const CODE_TO_UF = {
  "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
  "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
  "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
  "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
};
const PENDING_STATES = { PR: "IAT — PDFs mensais (fase 2)" };
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const INT = new Intl.NumberFormat("pt-BR");

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function norm(value) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function fmtDate(value) {
  if (!value) return "—";
  const [y, m, d] = String(value).slice(0, 10).split("-");
  return d && m && y ? `${d}/${m}/${y}` : value;
}
function fmtCnpj(value) {
  const d = String(value || "").replace(/\D/g, "");
  if (d.length === 14) return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
  return value || "—";
}
function today() {
  return new Date((S.data?.today || "2026-11-18") + "T00:00:00");
}
function daysTo(value) {
  if (!value) return null;
  const date = new Date(String(value).slice(0, 10) + "T00:00:00");
  return Math.round((date - today()) / 86400000);
}
function kindLabel(kind) {
  return { infraction: "Auto de infração", license_expiring: "Licença a vencer", license_expired: "Licença vencida" }[kind] || "Oportunidade";
}
function kindClass(kind) {
  return { infraction: "pill-red", license_expiring: "pill-amber", license_expired: "pill-slate" }[kind] || "pill-slate";
}
function kindColor(kind) {
  return { infraction: "#ef4444", license_expiring: "#f59e0b", license_expired: "#64748b" }[kind] || "#64748b";
}
function coverageFor(uf) {
  if (uf === "MG") return { color: "#10b981", label: "Federal + estadual" };
  if (PENDING_STATES[uf]) return { color: "#f59e0b", label: "Federal + fonte identificada" };
  return { color: "#93c5fd", label: "Federal" };
}
function showToast(message) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 3200);
}

function initMap() {
  S.map = L.map("map", { scrollWheelZoom: false }).setView([-14.2, -51.9], 5);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 12,
    attribution: "Tiles &copy; Esri",
  }).addTo(S.map);

  S.stateLayer = L.geoJSON(S.geo, {
    style: (feature) => {
      const uf = CODE_TO_UF[String(Number(feature.properties?.codarea))] || "—";
      return { color: "#fff", weight: 1.2, fillColor: coverageFor(uf).color, fillOpacity: 0.5 };
    },
    onEachFeature: (feature, layer) => {
      const uf = CODE_TO_UF[String(Number(feature.properties?.codarea))] || "—";
      const info = S.data.coverage.states[uf] || {};
      layer.bindTooltip(`${info.name || uf} · ${coverageFor(uf).label}`, { sticky: true });
      layer.on("click", () => {
        const select = $("#f-uf");
        if (select) select.value = uf;
        updateMunicipalityOptions(uf);
        applyFilters();
      });
    },
  }).addTo(S.map);

  S.pointLayer = L.layerGroup().addTo(S.map);
}

function fillFilters() {
  const states = Object.values(S.data.coverage.states || {}).sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  $("#f-uf").innerHTML = `<option value="">Todos</option>` + states.map((s) => `<option value="${s.uf}">${esc(s.name)} (${s.uf})</option>`).join("");

  const categories = [...new Set(S.data.leads.map((item) => item.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  $("#f-category").innerHTML = `<option value="">Todas</option>` + categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");

  updateMunicipalityOptions("");
}

function updateMunicipalityOptions(uf) {
  const select = $("#f-municipality");
  const current = select.value;
  let municipalities = [];
  if (uf) {
    municipalities = S.data.municipalities.filter((m) => m.uf === uf).map((m) => m.name);
  } else {
    municipalities = S.data.leads.filter((l) => l.municipality).map((l) => l.municipality);
  }
  municipalities = [...new Set(municipalities)].sort((a, b) => a.localeCompare(b, "pt-BR"));
  select.innerHTML = `<option value="">Todos</option>` + municipalities.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

function applyFilters() {
  const uf = $("#f-uf").value;
  const municipality = $("#f-municipality").value;
  const kind = $("#f-kind").value;
  const source = $("#f-source").value;
  const category = $("#f-category").value;
  const fine = Number($("#f-fine").value || 0);
  const expiry = $("#f-expiry").value;
  const search = norm($("#f-search").value);

  S.filtered = S.data.leads.filter((item) => {
    if (uf && item.uf !== uf) return false;
    if (municipality && norm(item.municipality) !== norm(municipality)) return false;
    if (kind && item.kind !== kind) return false;
    if (source && item.source !== source) return false;
    if (category && item.category !== category) return false;
    if (fine && Number(item.fine || 0) < fine) return false;
    if (expiry) {
      if (!item.expires_at) return false;
      const days = daysTo(item.expires_at);
      if (expiry === "expired" && !(days < 0)) return false;
      if (expiry !== "expired" && !(days >= 0 && days <= Number(expiry))) return false;
    }
    if (search) {
      const haystack = norm([item.company, item.cnpj, item.cnpj_root, item.process, item.municipality, item.category].join(" "));
      if (!haystack.includes(search)) return false;
    }
    return true;
  });

  S.filtered.sort((a, b) => (b.priority || 0) - (a.priority || 0));
  const withCoords = S.filtered.filter((item) => item.lat && item.lng).length;
  $("#result-count").textContent = `${INT.format(S.filtered.length)} oportunidades · ${INT.format(withCoords)} no mapa`;
  renderList();
  renderPoints();
  if (S.selected && !S.filtered.some((item) => item.id === S.selected.id)) {
    S.selected = S.filtered[0] || null;
  }
  if (!S.selected && S.filtered.length) S.selected = S.filtered[0];
  renderQuickDossier();
}

function renderList() {
  const list = $("#opp-list");
  const items = S.filtered.slice(0, 120);
  if (!items.length) {
    list.innerHTML = `<div class="empty">Nenhuma oportunidade com estes filtros.</div>`;
    return;
  }
  list.innerHTML = items.map((item) => {
    const isFine = item.kind === "infraction";
    const value = isFine ? BRL.format(item.fine || 0) : fmtDate(item.expires_at);
    const meta = isFine ? `Multa · ${value}` : `Validade · ${value}`;
    return `
      <article class="opp" data-id="${esc(item.id)}">
        <div class="opp-head">
          <div>
            <div class="opp-title">${esc(item.company || "Empresa sem nome")}</div>
            <div class="opp-meta">
              <span>${esc(item.municipality || "—")}${item.uf ? " · " + esc(item.uf) : ""}</span>
              <span>${esc(item.cnpj ? fmtCnpj(item.cnpj) : item.cnpj_root ? `raiz ${item.cnpj_root}` : "sem CNPJ")}</span>
            </div>
          </div>
          <span class="pill ${kindClass(item.kind)}">${kindLabel(item.kind)}</span>
        </div>
        <div class="opp-numbers">
          <span class="pill pill-slate">${esc(item.source)}</span>
          <span class="small muted">${meta}</span>
          ${item.verified ? `<span class="pill pill-green">✓ verificado</span>` : `<span class="pill pill-amber">identidade parcial</span>`}
        </div>
        <div class="opp-actions">
          <button class="btn btn-ghost btn-sm" type="button" data-open="${esc(item.id)}">Ver dossiê</button>
        </div>
      </article>`;
  }).join("");
  if (S.filtered.length > 120) {
    list.insertAdjacentHTML("beforeend", `<div class="notice notice-blue">Mostrando 120 de ${INT.format(S.filtered.length)}. Refine os filtros para ver mais.</div>`);
  }
  $$("[data-open]", list).forEach((button) => {
    button.addEventListener("click", () => {
      const item = S.data.leads.find((lead) => lead.id === button.dataset.open);
      if (item) openDossier(item);
    });
  });
  $$(".opp", list).forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      const item = S.data.leads.find((lead) => lead.id === card.dataset.id);
      if (item) {
        S.selected = item;
        renderQuickDossier();
      }
    });
  });
}

function renderPoints() {
  S.pointLayer.clearLayers();
  const points = S.filtered.filter((item) => item.lat && item.lng);
  points.forEach((item) => {
    const marker = L.circleMarker([item.lat, item.lng], {
      radius: 5,
      color: "#fff",
      weight: 1,
      fillColor: kindColor(item.kind),
      fillOpacity: 0.9,
    });
    marker.bindPopup(
      `<b>${esc(item.company)}</b><br/>${esc(kindLabel(item.kind))}<br/>${esc(item.municipality || "")}${item.uf ? " · " + esc(item.uf) : ""}<br/><span style="color:#64748b">${esc(item.source)}</span>`
    );
    marker.on("click", () => {
      S.selected = item;
      renderQuickDossier();
    });
    marker.addTo(S.pointLayer);
  });
}

function renderQuickDossier() {
  const el = $("#quick-dossier");
  if (!el) return;
  const item = S.selected;
  if (!item) {
    el.innerHTML = `<div class="muted small">Selecione uma oportunidade para ver o dossiê.</div>`;
    return;
  }
  const isFine = item.kind === "infraction";
  el.innerHTML = `
    <div class="pill ${kindClass(item.kind)}">${kindLabel(item.kind)}</div>
    <h3 style="margin:10px 0 4px;font-size:16px;line-height:1.25">${esc(item.company)}</h3>
    <div class="small muted">${esc(item.municipality || "—")}${item.uf ? " · " + esc(item.uf) : ""} · ${esc(item.source)}</div>
    <div class="kv" style="margin-top:12px">
      <dt>CNPJ</dt><dd>${esc(item.cnpj ? fmtCnpj(item.cnpj) : item.cnpj_root ? `raiz ${item.cnpj_root}` : "—")}</dd>
      <dt>${isFine ? "Multa" : "Validade"}</dt><dd>${isFine ? BRL.format(item.fine || 0) : fmtDate(item.expires_at)}</dd>
      <dt>Processo</dt><dd>${esc(item.process || "—")}</dd>
      <dt>Fonte</dt><dd>${esc(item.source_label || item.source)}</dd>
    </div>
    <button class="btn btn-emerald btn-sm btn-block" type="button" id="open-selected" style="margin-top:12px">Abrir dossiê completo</button>
  `;
  $("#open-selected")?.addEventListener("click", () => openDossier(item));
}

function renderLicenseDetail(detail) {
  if (!detail) return "";
  const docs = detail.documents || [];
  const uniqueDocs = [...new Set(docs)];
  const counts = {};
  docs.forEach((doc) => { counts[doc] = (counts[doc] || 0) + 1; });
  const conditions = detail.conditions || [];
  const framework = detail.framework || {};
  const activities = detail.activities || [];
  const authorizations = detail.authorizations || [];
  const ada = detail.ada || {};
  return `
    <details class="license-details" open>
      <summary>Licenciamento — processo e condicionantes</summary>
      <div class="license-body">
        <div class="license-grid">
          <div><span>CNPJ</span><b>${esc(detail.cnpj || "—")}</b></div>
          <div><span>Razão social</span><b>${esc(detail.company || "—")}</b></div>
          <div><span>Nome fantasia</span><b>${esc(detail.trade_name || "—")}</b></div>
          <div><span>Empreendimento</span><b>${esc(detail.enterprise || "—")}</b></div>
          <div><span>Município</span><b>${esc(detail.municipality || "—")}</b></div>
          <div><span>Processo</span><b>${esc(detail.process || "—")}</b></div>
          <div><span>Status</span><b>${esc(detail.status || "—")}</b></div>
          <div><span>ADA preliminar</span><b>${ada.lat && ada.lng ? `${ada.lat}, ${ada.lng}` : "—"}</b></div>
        </div>

        <div class="license-section">
          <h4>Enquadramento</h4>
          <div class="license-grid">
            <div><span>Classe predominante</span><b>${esc(framework.class || "—")}</b></div>
            <div><span>Fator locacional</span><b>${esc(framework.locational_factor || "—")}</b></div>
            <div><span>Modalidade</span><b>${esc(framework.licensing_modality || "—")}</b></div>
            <div><span>Fase</span><b>${esc(framework.licensing_phase || "—")}</b></div>
            <div style="grid-column:1/-1"><span>Tipo de solicitação</span><b>${esc(framework.request_type || "—")}</b></div>
          </div>
        </div>

        <div class="license-section">
          <h4>Atividades (${INT.format(activities.length)})</h4>
          <div class="table-wrap">
            <table class="license-table">
              <thead><tr><th>Código</th><th>Descrição</th><th>Parâmetro</th><th>Quantidade</th><th>Unidade</th></tr></thead>
              <tbody>${activities.map((activity) => `<tr>
                <td><b>${esc(activity.code || "—")}</b></td>
                <td>${esc(activity.description || "—")}</td>
                <td>${esc(activity.parameter || "—")}</td>
                <td>${esc(activity.quantity || "—")}</td>
                <td>${esc(activity.unit || "—")}</td>
              </tr>`).join("")}</tbody>
            </table>
          </div>
        </div>

        <div class="license-section">
          <h4>Atos autorizativos (${INT.format(authorizations.length)})</h4>
          <div class="table-wrap">
            <table class="license-table">
              <thead><tr><th>Grupo</th><th>Tipo</th><th>Número</th><th>Entidade</th><th>Protocolo</th></tr></thead>
              <tbody>${authorizations.map((act) => `<tr>
                <td>${esc(act.group || "—")}</td>
                <td>${esc(act.type || "—")}</td>
                <td>${esc(act.number || "—")}</td>
                <td>${esc(act.entity || "—")}</td>
                <td>${esc(act.protocol_date || "—")}</td>
              </tr>`).join("")}</tbody>
            </table>
          </div>
        </div>

        <div class="license-section">
          <h4>Documentos (${INT.format(uniqueDocs.length)} únicos · ${INT.format(docs.length)} menções)</h4>
          <details>
            <summary class="small strong">Ver lista de documentos</summary>
            <ul class="doc-list">
              ${uniqueDocs.map((doc) => `<li>${esc(doc)}${counts[doc] > 1 ? ` <span class="muted">(${counts[doc]}×)</span>` : ""}</li>`).join("")}
            </ul>
          </details>
        </div>

        <div class="license-section">
          <h4>Condicionantes</h4>
          ${conditions.length
            ? `<ul class="doc-list">${conditions.map((condition) => `<li>${esc(condition.text || condition)}</li>`).join("")}</ul>`
            : `<div class="notice notice-amber">${esc(detail.conditions_note || "O recorte disponível não inclui o texto das condicionantes. Consulte o processo oficial.")}</div>`}
        </div>
      </div>
    </details>
  `;
}

function openDossier(item) {
  S.selected = item;
  renderQuickDossier();
  const isFine = item.kind === "infraction";
  const body = $("#modal-body");
  $("#modal-title").textContent = item.company || "Dossiê";
  $("#modal-kicker").textContent = kindLabel(item.kind).toUpperCase();
  body.innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <span class="pill ${kindClass(item.kind)}">${kindLabel(item.kind)}</span>
      <span class="pill pill-slate">${esc(item.source)}</span>
      ${item.verified ? `<span class="pill pill-green">✓ CNPJ verificado</span>` : `<span class="pill pill-amber">identidade parcial</span>`}
    </div>
    <dl class="kv">
      <dt>CNPJ</dt><dd>${esc(item.cnpj ? fmtCnpj(item.cnpj) : item.cnpj_root ? `raiz ${item.cnpj_root}` : "—")}</dd>
      <dt>UF / município</dt><dd>${esc(item.uf || "—")}${item.municipality ? " · " + esc(item.municipality) : ""}</dd>
      <dt>CNAE</dt><dd>${esc(item.cnae ? `${item.cnae}${item.cnae_desc ? " — " + item.cnae_desc : ""}` : "—")}</dd>
      <dt>Fonte</dt><dd>${esc(item.source_label || item.source)}</dd>
      <dt>Processo</dt><dd>${esc(item.process || "—")}</dd>
      <dt>${isFine ? "Data do auto" : "Emissão"}</dt><dd>${fmtDate(item.date)}</dd>
      ${isFine ? `<dt>Valor da multa</dt><dd>${BRL.format(item.fine || 0)}</dd>` : `<dt>Validade</dt><dd>${fmtDate(item.expires_at)}</dd>`}
      ${item.license_type ? `<dt>Tipo de licença</dt><dd>${esc(item.license_type)}</dd>` : ""}
      ${item.activity ? `<dt>Atividade</dt><dd>${esc(item.activity)}</dd>` : ""}
      <dt>Sócios (QSA)</dt><dd>${item.qsa_count ? `${item.qsa_count} sócio(s) — nomes/CPF não exibidos` : "não enriquecido"}</dd>
    </dl>
    ${item.description ? `<div class="notice notice-blue"><b>Descrição pública:</b><br/>${esc(item.description)}</div>` : ""}
    ${item.license_detail ? renderLicenseDetail(item.license_detail) : ""}
    <div class="notice notice-amber">
      <b>LGPD:</b> dados de empresa/CNPJ e fonte pública. Não exibimos CPF, nome de sócio, telefone ou e-mail pessoal.
      Este dossiê é inteligência e priorização; não substitui certidão ou parecer oficial.
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-emerald btn-sm" type="button" id="reserve">Reservar 72h (mock)</button>
      <button class="btn btn-ghost btn-sm" type="button" id="copy">Copiar resumo</button>
      ${item.url ? `<a class="btn btn-ghost btn-sm" href="${esc(item.url)}" target="_blank" rel="noopener">Abrir fonte oficial ↗</a>` : ""}
    </div>
  `;
  $("#modal").classList.add("open");
  $("#reserve")?.addEventListener("click", () => showToast("Reserva de 72h simulada para esta oportunidade."));
  $("#copy")?.addEventListener("click", async () => {
    const text = `${item.company} | ${item.cnpj ? fmtCnpj(item.cnpj) : item.cnpj_root || "sem CNPJ"} | ${kindLabel(item.kind)} | ${item.source} | ${item.process || ""}`;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Resumo copiado.");
    } catch {
      showToast("Não foi possível copiar.");
    }
  });
}

function closeModal() {
  $("#modal").classList.remove("open");
}

function renderCoverage() {
  const rows = Object.values(S.data.coverage.states || {}).sort((a, b) => (b.federal_autos || 0) - (a.federal_autos || 0));
  $("#coverage-body").innerHTML = rows.map((row) => {
    const cov = coverageFor(row.uf);
    const stateSource = row.uf === "MG" ? "SEMAD-MG WFS" : PENDING_STATES[row.uf] ? PENDING_STATES[row.uf] : "—";
    const freshness = row.uf === "MG" ? "quadrimestral" : PENDING_STATES[row.uf] ? "parser fase 2" : "—";
    return `<tr data-uf="${row.uf}" style="cursor:pointer">
      <td><b>${row.uf}</b></td><td>${esc(row.name)}</td>
      <td>${INT.format(row.federal_autos || 0)}</td>
      <td>${INT.format(row.state_licenses || 0)}</td>
      <td>${esc(stateSource)}</td><td>${esc(freshness)}</td>
      <td><span class="pill ${row.uf === "MG" ? "pill-green" : PENDING_STATES[row.uf] ? "pill-amber" : "pill-blue"}">${cov.label}</span></td>
    </tr>`;
  }).join("");
  $$("#coverage-body tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      const uf = tr.dataset.uf;
      $("#f-uf").value = uf;
      updateMunicipalityOptions(uf);
      applyFilters();
      activateTab("opps");
    });
  });
}

function activateTab(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
  if (name === "opps") setTimeout(() => S.map?.invalidateSize(), 120);
}

function bindUi() {
  ["f-uf", "f-municipality", "f-kind", "f-source", "f-category", "f-fine", "f-expiry"].forEach((id) => {
    $(`#${id}`)?.addEventListener("change", () => {
      if (id === "f-uf") updateMunicipalityOptions($("#f-uf").value);
      applyFilters();
    });
  });
  $("#f-search")?.addEventListener("input", applyFilters);
  $("#reset-filters")?.addEventListener("click", () => {
    ["f-uf", "f-municipality", "f-kind", "f-source", "f-category", "f-fine", "f-expiry", "f-search"].forEach((id) => {
      const el = $(`#${id}`);
      if (el) el.value = id === "f-fine" ? "0" : "";
    });
    updateMunicipalityOptions("");
    applyFilters();
  });
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  $$("[data-plan]").forEach((button) => {
    button.addEventListener("click", () => showToast(`Plano ${button.dataset.plan}: simulação registada (mock).`));
  });
  $("#mock-checkout")?.addEventListener("click", () => {
    const addons = $$("[data-addon]:checked").map((el) => el.dataset.addon);
    showToast(`Assinatura simulada: Pro${addons.length ? " + " + addons.join(", ") : ""}.`);
  });
  $("#modal-close")?.addEventListener("click", closeModal);
  $("#modal")?.addEventListener("click", (event) => {
    if (event.target.id === "modal") closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModal();
  });
  $("#toggle-filters")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("open");
  });
}

async function main() {
  try {
    const [dataResponse, geoResponse] = await Promise.all([
      fetch("assets/data.json"),
      fetch("assets/br-states.geojson"),
    ]);
    S.data = await dataResponse.json();
    S.geo = await geoResponse.json();
  } catch (error) {
    console.error(error);
    showToast("Falha ao carregar os dados da demo.");
    return;
  }

  const k = S.data.kpis || {};
  $("#kpi-leads").textContent = INT.format(k.leads || 0);
  $("#kpi-autos").textContent = INT.format(k.federal_autos_2026 || 0);
  $("#kpi-licenses").textContent = INT.format((k.mg_licenses || 0) + (k.sislic_licenses || 0));
  $("#kpi-expiring").textContent = INT.format(k.expiring_90 || 0);
  $("#kpi-coverage").textContent = "27 UF";

  fillFilters();
  initMap();
  bindUi();
  renderCoverage();
  applyFilters();
}

document.addEventListener("DOMContentLoaded", main);
