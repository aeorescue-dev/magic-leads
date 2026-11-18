/* Radar Ambiental BR — landing */
const state = {
  data: null,
  geo: null,
  maps: {},
  layers: {},
};

const PENDING_STATES = {
  PR: "IAT — extratos mensais em PDF (parser fase 2)",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function fmtInt(value) {
  return new Intl.NumberFormat("pt-BR").format(Number(value || 0));
}

function fmtMoney(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(Number(value || 0));
}

function fmtDate(value) {
  if (!value) return "—";
  const [year, month, day] = String(value).slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

function showToast(message) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function coverageFor(uf) {
  const info = state.data?.coverage?.states?.[uf] || {};
  if (uf === "MG") return { color: "#10b981", label: "Federal + estadual", detail: "SEMAD-MG WFS · quadrimestral" };
  if (PENDING_STATES[uf]) return { color: "#f59e0b", label: "Federal + fonte identificada", detail: PENDING_STATES[uf] };
  return { color: "#93c5fd", label: "Federal", detail: "IBAMA — cobertura nacional" };
}

function stateDetail(uf) {
  const info = state.data?.coverage?.states?.[uf] || {};
  const cov = coverageFor(uf);
  const el = $("#state-detail");
  if (!el) return;
  el.className = "notice " + (uf === "MG" ? "notice-green" : PENDING_STATES[uf] ? "notice-amber" : "notice-blue");
  el.innerHTML = `
    <b>${info.name || uf} (${uf})</b><br />
    <span class="small">${cov.label} · ${cov.detail}</span><br />
    <span class="small">Autos federais (2026): <b>${fmtInt(info.federal_autos)}</b></span><br />
    <span class="small">Licenças estaduais: <b>${fmtInt(info.state_licenses)}</b></span>
  `;
}

function initMap(id, { zoomControl = true } = {}) {
  const map = L.map(id, {
    zoomControl,
    scrollWheelZoom: false,
    attributionControl: true,
  }).setView([-14.2, -51.9], 4);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 12,
    attribution: "Tiles &copy; Esri",
  }).addTo(map);
  state.maps[id] = map;
  return map;
}

function stateLayer(map, { hero = false } = {}) {
  if (!state.geo) return;
  const layer = L.geoJSON(state.geo, {
    style: (feature) => {
      const code = String(feature.properties?.codarea || "").padStart(2, "0");
      const uf = codeToUf(code);
      const cov = coverageFor(uf);
      return {
        color: "#ffffff",
        weight: 1.2,
        fillColor: cov.color,
        fillOpacity: hero ? 0.72 : 0.55,
      };
    },
    onEachFeature: (feature, featureLayer) => {
      const code = String(feature.properties?.codarea || "").padStart(2, "0");
      const uf = codeToUf(code);
      const info = state.data?.coverage?.states?.[uf] || {};
      const cov = coverageFor(uf);
      featureLayer.bindTooltip(`${info.name || uf} · ${cov.label}`, { sticky: true });
      featureLayer.on("click", () => {
        stateDetail(uf);
        const select = $("#state");
        if (select) select.value = uf;
        map.fitBounds(featureLayer.getBounds(), { padding: [20, 20] });
      });
    },
  }).addTo(map);
  state.layers[map._container.id] = layer;
}

const CODE_TO_UF = {
  "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
  "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
  "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
  "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
};
function codeToUf(code) {
  return CODE_TO_UF[String(Number(code))] || CODE_TO_UF[code] || "—";
}

function renderStateList() {
  const list = $("#state-list");
  if (!list) return;
  const states = Object.values(state.data?.coverage?.states || {});
  states.sort((a, b) => (b.federal_autos || 0) - (a.federal_autos || 0));
  list.innerHTML = states.map((item) => {
    const cov = coverageFor(item.uf);
    return `
      <button class="state-row" type="button" data-uf="${item.uf}">
        <span><i class="dot" style="background:${cov.color}"></i><b>${item.uf}</b> <span class="muted small">${item.name}</span></span>
        <span class="small muted">${fmtInt(item.federal_autos)} autos</span>
      </button>`;
  }).join("");
  $$(".state-row", list).forEach((button) => {
    button.addEventListener("click", () => {
      const uf = button.dataset.uf;
      stateDetail(uf);
      const layer = state.layers["coverage-map"];
      if (layer) {
        layer.eachLayer((featureLayer) => {
          const code = String(featureLayer.feature?.properties?.codarea || "").padStart(2, "0");
          if (codeToUf(code) === uf) {
            state.maps["coverage-map"]?.fitBounds(featureLayer.getBounds(), { padding: [20, 20] });
          }
        });
      }
    });
  });
}

function fillStateSelect() {
  const select = $("#state");
  if (!select) return;
  const states = Object.values(state.data?.coverage?.states || {});
  states.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  select.innerHTML = `<option value="">Selecione</option>` + states.map((item) => `<option value="${item.uf}">${item.name} (${item.uf})</option>`).join("");
}

function bindForm() {
  const form = $("#lead-form");
  if (!form) return;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const msg = $("#form-msg");
    const consent = $("#consent");
    if (!consent?.checked) {
      showToast("É necessário autorizar o contacto para continuar.");
      return;
    }
    msg.style.display = "block";
    msg.textContent = "Pedido registado na demo. Em produção, a equipa responde em até 1 dia útil.";
    form.reset();
    showToast("Diagnóstico solicitado (mock).");
  });
}

function bindPlans() {
  $$("[data-plan]").forEach((button) => {
    button.addEventListener("click", () => {
      showToast(`Plano ${button.dataset.plan}: simulação disponível no dashboard.`);
      setTimeout(() => { window.location.href = "dashboard.html#planos"; }, 500);
    });
  });
}

async function main() {
  try {
    const [dataResponse, geoResponse] = await Promise.all([
      fetch("assets/data.json"),
      fetch("assets/br-states.geojson"),
    ]);
    state.data = await dataResponse.json();
    state.geo = await geoResponse.json();
  } catch (error) {
    console.error(error);
    showToast("Não foi possível carregar os dados da demo.");
    return;
  }

  const kpis = state.data.kpis || {};
  const map = [
    ["#stat-companies", kpis.federal_companies_2026],
    ["#stat-mg", kpis.mg_licenses],
    ["#stat-federal", kpis.sislic_licenses],
    ["#stat-expiring", kpis.expiring_90],
  ];
  map.forEach(([selector, value]) => {
    const el = $(selector);
    if (el) el.textContent = fmtInt(value);
  });

  initMap("hero-map", { zoomControl: false });
  stateLayer(state.maps["hero-map"], { hero: true });
  initMap("coverage-map");
  stateLayer(state.maps["coverage-map"]);
  Object.keys(state.maps).forEach((id) => {
    const layer = state.layers[id];
    if (layer) state.maps[id].fitBounds(layer.getBounds(), { padding: [10, 10] });
  });

  renderStateList();
  fillStateSelect();
  bindForm();
  bindPlans();
}

document.addEventListener("DOMContentLoaded", main);
