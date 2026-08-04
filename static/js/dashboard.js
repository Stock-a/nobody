// ===== 글로벌 시장 지표 =====

const MARKET_ORDER = ["KOSPI","KOSDAQ","S&P500","NASDAQ","DOW","WTI유가","VIX","USD/KRW"];

// 숫자 콤마 포맷 (환경 무관하게 항상 작동)
const _comma = n => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

let frgnChart = null;
let volumeChart = null;

async function refreshMarketData() {
  try {
    const resp = await fetch('/api/market');
    const json = await resp.json();
    renderMarketCards(json.data);
    document.getElementById('last-updated').textContent = '갱신: ' + json.timestamp.slice(11, 16);
  } catch {
    document.getElementById('last-updated').textContent = '수집 실패 — 재시도 중';
  }
}

function formatPrice(name, price) {
  if (name === 'USD/KRW') return _comma(price) + '원';
  if (name === 'WTI유가')  return '$' + price.toFixed(2);
  if (name === 'VIX')      return price.toFixed(2);
  if (price >= 1000)       return _comma(price);
  return price.toFixed(2);
}

function renderMarketCards(data) {
  const el = document.getElementById('market-cards');
  el.innerHTML = '';
  MARKET_ORDER.filter(k => data[k]).forEach(name => {
    const v = data[name];
    const cls   = v.up ? 'text-up' : 'text-down';
    const arrow = v.up ? '▲' : '▼';
    const sign  = v.change_pct >= 0 ? '+' : '';
    el.innerHTML += `
      <div class="col-6 col-md-3 col-xl-3">
        <div class="market-card">
          <div class="mkt-label">${name}</div>
          <div class="mkt-price ${cls}">${formatPrice(name, v.price)}</div>
          <div class="mkt-change ${cls}">${arrow} ${sign}${v.change_pct.toFixed(2)}%</div>
        </div>
      </div>`;
  });
}

refreshMarketData();
setInterval(refreshMarketData, 30000);


// ===== 종목코드/종목명 → 티커 변환 (공용) =====

async function resolveStockCode(query) {
  const trimmed = (query || '').trim();
  if (!trimmed) return null;
  if (/^\d{6}$/.test(trimmed)) return { code: trimmed, name: null };
  try {
    const resp = await fetch(`/api/stock/resolve?q=${encodeURIComponent(trimmed)}`);
    if (!resp.ok) return null;
    const j = await resp.json();
    return j.code ? j : null;
  } catch {
    return null;
  }
}

// ===== 종목 공통 입력 → 수급 + 기술적 분석 동시 로드 =====

async function loadStockData() {
  const input = document.getElementById('stock-code');
  const resolved = await resolveStockCode(input.value);
  if (!resolved) {
    alert('종목을 찾을 수 없습니다. 6자리 종목코드 또는 정확한 종목명을 입력하세요.');
    return;
  }
  input.value = resolved.code;
  // 두 탭 모두 로드
  loadFlowData(resolved.code);
  loadTechnicalData(resolved.code);
}

document.getElementById('stock-code').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadStockData();
});


// ===== 수급 분석 =====

async function loadFlowData(code) {
  document.getElementById('frgn-empty').classList.add('d-none');
  document.getElementById('frgn-loading').classList.remove('d-none');
  document.getElementById('frgn-area').classList.add('d-none');

  try {
    const [fr, vr] = await Promise.all([
      fetch(`/api/stock/${code}/frgn`).then(r => r.json()),
      fetch(`/api/stock/${code}/volume`).then(r => r.json())
    ]);

    document.getElementById('frgn-chart-title').innerHTML =
      `외인 / 기관 순매수 — <strong style="color:var(--cyan)">${fr.name || code}</strong>
       <span class="badge-indicator badge-ma">순매수량 기준</span>`;

    renderFlowSummary(fr.data);
    renderFlowCharts(fr.data, vr.data);
    renderFlowTable(fr.data);

    document.getElementById('frgn-loading').classList.add('d-none');
    document.getElementById('frgn-area').classList.remove('d-none');
  } catch {
    document.getElementById('frgn-loading').classList.add('d-none');
    document.getElementById('frgn-empty').textContent = '수급 데이터 수집 실패. 종목코드를 확인하세요.';
    document.getElementById('frgn-empty').classList.remove('d-none');
  }
}

function renderFlowSummary(data) {
  const recent = data.slice(0, 5);
  const fSum = recent.reduce((s, d) => s + d.foreign_net, 0);
  const iSum = recent.reduce((s, d) => s + d.institution_net, 0);
  const fCls = fSum >= 0 ? 'text-up' : 'text-down';
  const iCls = iSum >= 0 ? 'text-up' : 'text-down';

  document.getElementById('flow-summary-badges').innerHTML = `
    <div class="flow-badge">
      <span class="fb-label">외국인 5일 합계</span>
      <span class="fb-value ${fCls}">${fSum >= 0 ? '+' : '-'}${_comma(Math.abs(fSum))}주</span>
    </div>
    <div class="flow-badge">
      <span class="fb-label">기관 5일 합계</span>
      <span class="fb-value ${iCls}">${iSum >= 0 ? '+' : '-'}${_comma(Math.abs(iSum))}주</span>
    </div>`;
}

function renderFlowCharts(frgnData, volData) {
  const rev    = [...frgnData].reverse();
  const labels = rev.map(d => d.date);
  const fData  = rev.map(d => d.foreign_net);
  const iData  = rev.map(d => d.institution_net);

  if (frgnChart) frgnChart.destroy();
  frgnChart = new Chart(document.getElementById('frgnChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: '외국인', data: fData,
          backgroundColor: fData.map(v => v >= 0 ? 'rgba(248,113,113,0.75)' : 'rgba(96,165,250,0.75)') },
        { label: '기관',   data: iData,
          backgroundColor: iData.map(v => v >= 0 ? 'rgba(248,113,113,0.35)' : 'rgba(96,165,250,0.35)') }
      ]
    },
    options: chartOpts()
  });

  const vRev    = [...volData].slice(-20).map(d => d);
  const vLabels = vRev.map(d => d.date);
  const volumes = vRev.map(d => d.volume);
  const avgVol  = volumes.reduce((a, b) => a + b, 0) / volumes.length;

  if (volumeChart) volumeChart.destroy();
  volumeChart = new Chart(document.getElementById('volumeChart'), {
    type: 'bar',
    data: {
      labels: vLabels,
      datasets: [
        { label: '거래량', data: volumes,
          backgroundColor: volumes.map(v => v > avgVol * 1.5
            ? 'rgba(250,204,21,0.8)' : 'rgba(34,211,238,0.45)'),
          borderColor: 'transparent' },
        { label: '20일 평균', data: Array(volumes.length).fill(Math.round(avgVol)),
          type: 'line', borderColor: '#f87171', borderWidth: 1.5,
          pointRadius: 0, fill: false, tension: 0 }
      ]
    },
    options: {
      ...chartOpts(),
      plugins: { ...chartOpts().plugins,
        tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + _comma(ctx.raw) } }
      }
    }
  });
}

function renderFlowTable(data) {
  const tbody = document.getElementById('frgn-tbody');
  tbody.innerHTML = '';
  data.forEach(d => {
    const fc = d.foreign_net >= 0 ? 'text-up' : 'text-down';
    const ic = d.institution_net >= 0 ? 'text-up' : 'text-down';
    const sign = v => (v >= 0 ? '+' : '-') + _comma(Math.abs(v));
    tbody.innerHTML += `
      <tr>
        <td>${d.date}</td>
        <td class="text-end">${_comma(d.close)}원</td>
        <td class="text-end">${_comma(d.volume)}</td>
        <td class="text-end ${fc}">${sign(d.foreign_net)}</td>
        <td class="text-end ${ic}">${sign(d.institution_net)}</td>
      </tr>`;
  });
}

// 공통 차트 옵션
function chartOpts(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12 } },
      tooltip: { mode: 'index', intersect: false }
    },
    scales: {
      x: {
        ticks: { color: '#7c8ca0', font: { size: 10 }, maxRotation: 45 },
        grid:  { color: 'rgba(255,255,255,0.04)' }
      },
      y: {
        ticks: { color: '#7c8ca0', font: { size: 10 }, callback: v => _comma(v) },
        grid:  { color: 'rgba(255,255,255,0.04)' }
      }
    },
    ...extra
  };
}
