// ===== 기술적 분석 차트 =====

let priceChart = null, rsiChart = null, macdChart = null, dispChart = null, volTechChart = null;

async function loadTechnicalData(code) {
  document.getElementById('tech-empty').classList.add('d-none');
  document.getElementById('tech-loading').classList.remove('d-none');
  document.getElementById('tech-area').classList.add('d-none');

  try {
    const resp = await fetch(`/api/stock/${code}/technical`);
    const json = await resp.json();
    const d = json.data;

    if (d.error) throw new Error(d.error);

    renderTechPills(d);
    renderPriceChart(d);
    renderRsiChart(d);
    renderMacdChart(d);
    renderDispChart(d);
    renderVolTechChart(d);
    renderTechSummary(d);

    document.getElementById('tech-loading').classList.add('d-none');
    document.getElementById('tech-area').classList.remove('d-none');
  } catch (e) {
    document.getElementById('tech-loading').classList.add('d-none');
    document.getElementById('tech-empty').textContent = '기술적 데이터 수집 실패: ' + e.message;
    document.getElementById('tech-empty').classList.remove('d-none');
  }
}

// ── 기준시각 / 장상태 포맷 ──
function _fmtTradeTime(iso) {
  if (!iso) return '';
  const m = iso.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[2]}.${m[3]} ${m[4]}:${m[5]}` : '';
}
function _marketStatusLabel(status) {
  return { OPEN: '장중', CLOSE: '장마감' }[status] || '';
}

// ── 기술적 분석 요약 문단 ──
function renderTechSummary(d) {
  const parts = [];

  const { current_ma5: ma5, current_ma20: ma20, current_ma60: ma60 } = d;
  if (ma5 && ma20 && ma60) {
    if (ma5 > ma20 && ma20 > ma60) parts.push('단기·중기 이동평균선이 정배열 상태로 상승 추세가 이어지고 있습니다.');
    else if (ma5 < ma20 && ma20 < ma60) parts.push('이동평균선이 역배열 상태로 하락 추세가 이어지고 있습니다.');
    else parts.push('이동평균선이 혼조세를 보여 뚜렷한 방향 없이 등락하는 구간입니다.');
  }

  // 20일선-60일선 골든/데드크로스 — 교차 자체보다 당일 거래량 동반 여부로 신뢰도를 구분
  const ma20Arr = d.ma20 || [], ma60Arr = d.ma60 || [];
  if (ma20Arr.length >= 2 && ma60Arr.length >= 2) {
    const m20_0 = ma20Arr[ma20Arr.length - 1], m20_1 = ma20Arr[ma20Arr.length - 2];
    const m60_0 = ma60Arr[ma60Arr.length - 1], m60_1 = ma60Arr[ma60Arr.length - 2];
    if ([m20_0, m20_1, m60_0, m60_1].every(v => v != null)) {
      const vol = d.volume || [], volMa = d.vol_ma20 || [];
      const volConfirmed = !!(vol.length && volMa.length && volMa[volMa.length - 1] &&
        vol[vol.length - 1] > volMa[volMa.length - 1] * 1.2);
      if (m20_1 <= m60_1 && m20_0 > m60_0) {
        parts.push(volConfirmed
          ? '20일선이 60일선을 상향 돌파하는 골든크로스가 거래량 증가를 동반해 발생했습니다 — 신뢰도 있는 신호로 볼 수 있습니다.'
          : '20일선이 60일선을 상향 돌파하는 골든크로스가 발생했지만, 거래량 증가가 동반되지 않아 신뢰도는 제한적입니다.');
      } else if (m20_1 >= m60_1 && m20_0 < m60_0) {
        parts.push(volConfirmed
          ? '20일선이 60일선을 하향 돌파하는 데드크로스가 거래량 증가를 동반해 발생했습니다 — 신뢰도 있는 하락 신호로 볼 수 있습니다.'
          : '20일선이 60일선을 하향 돌파하는 데드크로스가 발생했지만, 거래량 증가가 동반되지 않아 신뢰도는 제한적입니다.');
      }
    }
  }

  if (d.current_rsi != null) {
    if (d.current_rsi >= 70) parts.push(`RSI ${d.current_rsi}로 과매수 구간에 진입해 단기 조정 가능성에 유의해야 합니다.`);
    else if (d.current_rsi <= 30) parts.push(`RSI ${d.current_rsi}로 과매도 구간에 있어 기술적 반등 가능성이 있습니다.`);
    else parts.push(`RSI ${d.current_rsi}로 중립 구간에 위치해 있습니다.`);
  }

  const macd = d.macd || [], sig = d.macd_signal || [];
  if (macd.length >= 2 && sig.length >= 2) {
    const m0 = macd[macd.length - 1], m1 = macd[macd.length - 2];
    const s0 = sig[sig.length - 1], s1 = sig[sig.length - 2];
    if (m1 != null && s1 != null && m0 != null && s0 != null) {
      if (m1 < s1 && m0 > s0) parts.push('MACD가 시그널선을 상향 돌파하는 골든크로스가 발생해 상승 전환 신호가 나타났습니다.');
      else if (m1 > s1 && m0 < s0) parts.push('MACD가 시그널선을 하향 돌파하는 데드크로스가 발생해 하락 전환 신호가 나타났습니다.');
      else if (m0 > s0) parts.push('MACD가 시그널선 위에서 상승 추세를 유지하고 있습니다.');
      else parts.push('MACD가 시그널선 아래에서 하락 추세를 유지하고 있습니다.');
    }
  }

  if (d.current_disp20 != null) {
    if (d.current_disp20 >= 105) parts.push(`20일 이격도 ${d.current_disp20}로 이동평균 대비 과열 구간입니다.`);
    else if (d.current_disp20 <= 95) parts.push(`20일 이격도 ${d.current_disp20}로 이동평균 대비 저평가 구간입니다.`);
  }

  if (d.current_disp20 != null && d.current_disp60 != null) {
    if (d.current_disp20 > d.current_disp60) {
      parts.push(`이격도는 20일(${d.current_disp20})이 60일(${d.current_disp60})보다 높은 정배열 상태로, 단기 상승 탄력이 중기보다 강합니다.`);
    } else if (d.current_disp20 < d.current_disp60) {
      parts.push(`이격도는 20일(${d.current_disp20})이 60일(${d.current_disp60})보다 낮은 역배열 상태로, 단기 하락 탄력이 중기보다 약합니다.`);
    } else {
      parts.push('20일과 60일 이격도가 비슷한 수준으로 단기·중기 탄력 차이가 크지 않습니다.');
    }
  }

  const vol = d.volume || [], volMa = d.vol_ma20 || [];
  if (vol.length && volMa.length) {
    const v0 = vol[vol.length - 1], vAvg = volMa[volMa.length - 1];
    if (vAvg) {
      const ratio = v0 / vAvg;
      if (ratio >= 1.8) parts.push(`거래량이 20일 평균 대비 ${ratio.toFixed(1)}배로 급증해 수급 변화 가능성에 주목할 필요가 있습니다.`);
      else if (ratio <= 0.5) parts.push('거래량이 20일 평균보다 크게 줄어 관심이 저조한 상태입니다.');
    }
  }

  if (d.position_52w != null) {
    if (d.position_52w >= 80) parts.push(`52주 구간 내 상위 ${100 - d.position_52w}% 수준으로 고점 부근에 있습니다.`);
    else if (d.position_52w <= 20) parts.push(`52주 구간 내 하위 ${d.position_52w}% 수준으로 저점 부근에 있습니다.`);
  }

  const nearestResistance = (d.resistance_levels || [])[0];
  const nearestSupport = (d.support_levels || [])[0];
  if (nearestResistance || nearestSupport) {
    const bits = [];
    if (nearestResistance) bits.push(`저항선은 ${_comma(nearestResistance)}원`);
    if (nearestSupport) bits.push(`지지선은 ${_comma(nearestSupport)}원`);
    parts.push(`가장 가까운 ${bits.join(', ')}입니다.`);
  }

  document.getElementById('tech-summary-text').textContent =
    parts.length ? parts.join(' ') : '분석에 필요한 데이터가 부족합니다.';
}

// ── info-pill 요약 카드 ──
function renderTechPills(d) {
  const rsiCls = !d.current_rsi ? 'rsi-neutral'
               : d.current_rsi < 30 ? 'rsi-oversold'
               : d.current_rsi > 70 ? 'rsi-overbought'
               : 'rsi-neutral';
  const rsiLabel = !d.current_rsi ? '—'
                 : d.current_rsi < 30 ? '과매도'
                 : d.current_rsi > 70 ? '과매수'
                 : '중립';

  const dispCls = !d.current_disp20 ? ''
                : d.current_disp20 > 105 ? 'text-up'
                : d.current_disp20 < 95  ? 'text-down'
                : '';

  const pos = d.position_52w;
  const posCls = pos >= 70 ? 'text-up' : pos <= 30 ? 'text-down' : 'text-muted';

  const tradeTime = _fmtTradeTime(d.trade_datetime);
  const statusLabel = _marketStatusLabel(d.market_status);

  document.getElementById('tech-pills').innerHTML = `
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">현재가</div>
        <div class="pill-value">${_comma(d.current)}원</div>
        <div class="pill-sub">${tradeTime ? `${tradeTime}${statusLabel ? ' · ' + statusLabel : ''}` : '&nbsp;'}</div>
      </div>
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">52주 고점</div>
        <div class="pill-value text-up">${_comma(d.high_52w)}원</div>
        <div class="pill-sub">최고가</div>
      </div>
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">52주 저점</div>
        <div class="pill-value text-down">${_comma(d.low_52w)}원</div>
        <div class="pill-sub">최저가</div>
      </div>
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">52주 위치</div>
        <div class="pill-value ${posCls}">${pos}%</div>
        <div class="progress-52w"><div class="progress-52w-bar" style="width:${pos}%"></div></div>
      </div>
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">RSI (14일)</div>
        <div class="pill-value ${rsiCls}">${d.current_rsi ?? '—'}</div>
        <div class="pill-sub ${rsiCls}">${rsiLabel}</div>
      </div>
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <div class="info-pill">
        <div class="pill-label">이격도 (20일)</div>
        <div class="pill-value ${dispCls}">${d.current_disp20 ?? '—'}</div>
        <div class="pill-sub">100 기준</div>
      </div>
    </div>`;
}

// ── 이동평균선 설명 툴팁 ──
const MA_COLORS = { ma5:'#4ade80', ma20:'#facc15', ma60:'#fb923c', ma120:'#a78bfa' };

// ── 가격 + MA + 볼린저밴드 ──
function renderPriceChart(d) {
  if (priceChart) priceChart.destroy();

  const n = d.dates.length;
  const toXY = arr => (arr || []).map((v, i) => ({ x: i, y: v }));
  const flatLine = (value) => Array.from({ length: n }, (_, i) => ({ x: i, y: value }));

  const candleData = d.dates
    .map((_, i) => ({ x: i, o: d.open?.[i], h: d.high?.[i], l: d.low?.[i], c: d.close?.[i] }))
    .filter(p => p.o != null && p.h != null && p.l != null && p.c != null);

  const datasets = [
    // 볼린저밴드
    { type: 'line', label: 'BB 상단', data: toXY(d.bb_upper), borderColor: 'rgba(34,211,238,0.5)',
      borderWidth: 1, pointRadius: 0, fill: false, tension: 0.3, borderDash: [3, 3] },
    { type: 'line', label: 'BB 하단', data: toXY(d.bb_lower), borderColor: 'rgba(34,211,238,0.5)',
      borderWidth: 1, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(34,211,238,0.04)',
      tension: 0.3, borderDash: [3, 3] },
    { type: 'line', label: 'BB 중심(20일)', data: toXY(d.bb_mid), borderColor: 'rgba(34,211,238,0.3)',
      borderWidth: 1, pointRadius: 0, fill: false, tension: 0.3 },
    // 이동평균선
    { type: 'line', label: 'MA 5',   data: toXY(d.ma5),   borderColor: MA_COLORS.ma5,  borderWidth: 1.2, pointRadius: 0, fill: false, tension: 0.3 },
    { type: 'line', label: 'MA 20',  data: toXY(d.ma20),  borderColor: MA_COLORS.ma20, borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.3 },
    { type: 'line', label: 'MA 60',  data: toXY(d.ma60),  borderColor: MA_COLORS.ma60, borderWidth: 1.8, pointRadius: 0, fill: false, tension: 0.3 },
    { type: 'line', label: 'MA 120', data: toXY(d.ma120), borderColor: MA_COLORS.ma120,borderWidth: 2,   pointRadius: 0, fill: false, tension: 0.3 },
    // 지지/저항선 (technical.py의 스윙 고점/저점 기반 계산값)
    ...(d.resistance_levels || []).map(level => ({
      type: 'line', label: `저항 ${_comma(level)}원`, data: flatLine(level),
      borderColor: 'rgba(248,113,113,0.6)', borderWidth: 1, borderDash: [6, 3], pointRadius: 0, fill: false,
    })),
    ...(d.support_levels || []).map(level => ({
      type: 'line', label: `지지 ${_comma(level)}원`, data: flatLine(level),
      borderColor: 'rgba(96,165,250,0.6)', borderWidth: 1, borderDash: [6, 3], pointRadius: 0, fill: false,
    })),
    // 캔들스틱 (시가/고가/저가/종가) — chartjs-chart-financial
    // 라이브러리 내부적으로 close<open일 때 'up' 색상, close>open일 때 'down' 색상을 쓰는
    // (실제 상승/하락과 반대인) 네이밍이라 여기서 의도적으로 반대로 매핑함
    // (up→파랑/하락, down→빨강/상승 — 이 앱의 한국식 상승=빨강/하락=파랑 표기를 맞추기 위함)
    {
      type: 'candlestick',
      label: '캔들',
      data: candleData,
      backgroundColors: { up: 'rgba(96,165,250,0.7)', down: 'rgba(248,113,113,0.7)', unchanged: 'rgba(148,163,184,0.5)' },
      borderColors: { up: '#60a5fa', down: '#f87171', unchanged: '#94a3b8' },
    },
  ];

  priceChart = new Chart(document.getElementById('priceChart'), {
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: 'linear',
          min: 0, max: n - 1,
          ticks: {
            color: '#7c8ca0', font: { size: 9 }, maxRotation: 45, maxTicksLimit: 12,
            callback: (val) => d.dates[val] ?? '',
          },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
        y: {
          ticks: { color: '#7c8ca0', font: { size: 10 }, callback: v => _comma(v) },
          grid: { color: 'rgba(255,255,255,0.04)' },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: '#94a3b8', font: { size: 10 }, boxWidth: 12,
            filter: item => !item.text.startsWith('BB 하'),
          },
        },
        tooltip: {
          mode: 'index', intersect: false,
          callbacks: {
            title: items => d.dates[items[0]?.parsed?.x] ?? '',
            label: ctx => {
              if (ctx.dataset.type === 'candlestick') {
                const p = ctx.raw;
                return `시가 ${_comma(p.o)} 고가 ${_comma(p.h)} 저가 ${_comma(p.l)} 종가 ${_comma(p.c)}`;
              }
              return `${ctx.dataset.label}: ${ctx.parsed.y != null ? _comma(ctx.parsed.y) : '—'}`;
            },
          },
        },
      },
    },
  });
}

// ── RSI ──
function renderRsiChart(d) {
  if (rsiChart) rsiChart.destroy();

  // 기준선용 데이터
  const len = d.dates.length;
  const line70 = Array(len).fill(70);
  const line30 = Array(len).fill(30);
  const line50 = Array(len).fill(50);

  rsiChart = new Chart(document.getElementById('rsiChart'), {
    type: 'line',
    data: {
      labels: d.dates,
      datasets: [
        { label:'과매수(70)', data:line70, borderColor:'rgba(248,113,113,0.4)', borderWidth:1,
          borderDash:[4,4], pointRadius:0, fill:false },
        { label:'중립(50)',   data:line50, borderColor:'rgba(148,163,184,0.25)', borderWidth:1,
          borderDash:[2,4], pointRadius:0, fill:false },
        { label:'과매도(30)', data:line30, borderColor:'rgba(96,165,250,0.4)', borderWidth:1,
          borderDash:[4,4], pointRadius:0, fill:false },
        { label:'RSI',       data:d.rsi,  borderColor:'#c4b5fd', borderWidth:2,
          pointRadius:0, fill:false, tension:0.3 },
      ]
    },
    options: chartOptsLine({
      scales: {
        y: { min:0, max:100,
             ticks:{ color:'#7c8ca0', font:{size:10}, stepSize:25 },
             grid:{ color:'rgba(255,255,255,0.04)' } }
      }
    })
  });
}

// ── MACD ──
function renderMacdChart(d) {
  if (macdChart) macdChart.destroy();

  macdChart = new Chart(document.getElementById('macdChart'), {
    type: 'bar',
    data: {
      labels: d.dates,
      datasets: [
        { label:'히스토그램', data:d.macd_hist, type:'bar',
          backgroundColor: d.macd_hist.map(v => v >= 0
            ? 'rgba(248,113,113,0.5)' : 'rgba(96,165,250,0.5)') },
        { label:'MACD',    data:d.macd,        type:'line', borderColor:'#fb923c',
          borderWidth:1.5, pointRadius:0, fill:false, tension:0.3 },
        { label:'Signal',  data:d.macd_signal, type:'line', borderColor:'#60a5fa',
          borderWidth:1.5, pointRadius:0, fill:false, tension:0.3 },
      ]
    },
    options: chartOptsLine()
  });
}

// ── 이격도 ──
function renderDispChart(d) {
  if (dispChart) dispChart.destroy();

  const len = d.dates.length;
  dispChart = new Chart(document.getElementById('dispChart'), {
    type: 'line',
    data: {
      labels: d.dates,
      datasets: [
        { label:'105 기준', data:Array(len).fill(105), borderColor:'rgba(248,113,113,0.35)',
          borderWidth:1, borderDash:[4,4], pointRadius:0, fill:false },
        { label:'100 기준', data:Array(len).fill(100), borderColor:'rgba(148,163,184,0.3)',
          borderWidth:1, borderDash:[2,4], pointRadius:0, fill:false },
        { label:'95 기준',  data:Array(len).fill(95),  borderColor:'rgba(96,165,250,0.35)',
          borderWidth:1, borderDash:[4,4], pointRadius:0, fill:false },
        { label:'이격도(20일)', data:d.disp20, borderColor:'#4ade80',
          borderWidth:1.8, pointRadius:0, fill:false, tension:0.3 },
      ]
    },
    options: chartOptsLine({
      scales: {
        y: { ticks:{ color:'#7c8ca0', font:{size:10},
               callback: v => v.toFixed(0) }, grid:{ color:'rgba(255,255,255,0.04)' } }
      }
    })
  });
}

// ── 거래량 + 20일MA ──
function renderVolTechChart(d) {
  if (volTechChart) volTechChart.destroy();

  const avgVol = d.vol_ma20.filter(v => v).slice(-1)[0] || 1;

  volTechChart = new Chart(document.getElementById('volTechChart'), {
    type: 'bar',
    data: {
      labels: d.dates,
      datasets: [
        { label:'거래량', data:d.volume,
          backgroundColor: d.volume.map(v =>
            v > avgVol * 1.8 ? 'rgba(250,204,21,0.7)' : 'rgba(34,211,238,0.4)') },
        { label:'20일 평균', data:d.vol_ma20, type:'line',
          borderColor:'#f87171', borderWidth:1.5, pointRadius:0, fill:false, tension:0.3 }
      ]
    },
    options: chartOptsLine({
      plugins: { ...chartOptsBase().plugins,
        tooltip:{ callbacks:{ label: ctx => ctx.dataset.label+': '+(ctx.raw != null ? _comma(ctx.raw) : '—') } }
      }
    })
  });
}

// 공통 옵션
function chartOptsBase() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color:'#94a3b8', font:{size:10}, boxWidth:10 } },
      tooltip: { mode:'index', intersect:false }
    }
  };
}

function chartOptsLine(extra = {}) {
  const base = {
    ...chartOptsBase(),
    scales: {
      x: { ticks:{ color:'#7c8ca0', font:{size:9}, maxRotation:45,
             maxTicksLimit: 12 }, grid:{ color:'rgba(255,255,255,0.03)' } },
      y: { ticks:{ color:'#7c8ca0', font:{size:10}, callback: v => _comma(v) },
           grid:{ color:'rgba(255,255,255,0.04)' } }
    }
  };
  // deep merge plugins
  if (extra.plugins) {
    base.plugins = { ...base.plugins, ...extra.plugins };
    delete extra.plugins;
  }
  if (extra.scales) {
    base.scales = { ...base.scales, ...extra.scales };
    delete extra.scales;
  }
  return { ...base, ...extra };
}
