// ===== 한국형 Kelly Position Sizing 분석기 (V2) =====

// ─── 숫자 포맷 헬퍼 ───────────────────────
const _fmt = n => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const W  = n => (n == null ? "—" : _fmt(n) + "원");
const N  = n => (n == null ? "—" : _fmt(n));
const P  = (n, d = 2) => (n == null ? "—" : Number(n).toFixed(d) + "%");
const PX = n => (n == null ? "—" : Number(n).toFixed(1) + "x");
const WON_UNIT = n => (n == null ? "—" : n >= 1e12 ? (n / 1e12).toFixed(1) + "조" : N(Math.round(n / 1e8)) + "억");

const GRADE_COLOR = { "A+": "var(--green)", "A": "var(--cyan)", "B+": "var(--purple)", "B": "var(--text2)", "C": "var(--orange)", "D": "var(--up)" };
const ITEM_ICON = { positive: "▲", negative: "▼", neutral: "●" };

// ─── 원화 입력창 콤마 자동 포맷 ───────────
function _posAfterDigits(str, n) {
  let count = 0;
  for (let i = 0; i < str.length; i++) {
    if (/\d/.test(str[i])) count++;
    if (count === n) return i + 1;
  }
  return str.length;
}

function _bindWonInput(id) {
  const el = document.getElementById(id);
  el.addEventListener("input", () => {
    const digitsBefore = (el.value.slice(0, el.selectionStart).match(/\d/g) || []).length;
    const raw = el.value.replace(/[^\d]/g, "");
    el.value = raw ? _comma(Number(raw)) : "";
    const pos = _posAfterDigits(el.value, digitsBefore);
    el.setSelectionRange(pos, pos);
  });
}

function _wonValue(id) {
  const raw = (document.getElementById(id).value || "").replace(/[^\d]/g, "");
  return raw ? parseFloat(raw) : 0;
}

_bindWonInput("ka-seed");
_bindWonInput("ka-price");

// ─── 이벤트 ───────────────────────────────
document.getElementById("ka-code").addEventListener("keydown", e => {
  if (e.key === "Enter") runKellyAnalysis();
});

// ─── 메인 분석 실행 ───────────────────────
async function runKellyAnalysis() {
  const seed    = _wonValue("ka-seed");
  const codeEl  = document.getElementById("ka-code");
  const price   = _wonValue("ka-price");
  const target  = parseFloat(document.getElementById("ka-target").value) || 10;

  if (!seed || seed <= 0) { alert("시드머니를 입력하세요."); return; }
  if (!codeEl.value.trim()) { alert("종목코드 또는 종목명을 입력하세요."); return; }

  const resolved = await resolveStockCode(codeEl.value);
  if (!resolved) {
    alert("종목을 찾을 수 없습니다. 6자리 종목코드 또는 정확한 종목명을 입력하세요.");
    return;
  }
  const code = resolved.code;
  codeEl.value = code;

  document.getElementById("ka-loading").classList.remove("d-none");
  document.getElementById("ka-result").classList.add("d-none");
  document.getElementById("ka-result").innerHTML = "";

  try {
    const resp = await fetch("/api/kelly/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, seed, current_price: price, target_pct: target })
    });
    const data = await resp.json();
    document.getElementById("ka-loading").classList.add("d-none");
    renderKellyResult(data);
    if (!data.error) addToKellyList(data);
  } catch (e) {
    document.getElementById("ka-loading").classList.add("d-none");
    document.getElementById("ka-result").innerHTML =
      `<div style="color:var(--up);padding:1rem">분석 실패: ${e.message}</div>`;
    document.getElementById("ka-result").classList.remove("d-none");
  }
}

// ─── 결과 렌더링 ──────────────────────────
function renderKellyResult(d) {
  const el = document.getElementById("ka-result");

  if (d.error) {
    el.innerHTML = `<div class="ka-result-card"><div class="ka-result-body" style="color:var(--up)">${d.error}</div></div>`;
    el.classList.remove("d-none");
    return;
  }

  el.innerHTML = buildResultHTML(d);
  el.classList.remove("d-none");

  requestAnimationFrame(() => setTimeout(() => {
    el.querySelector(".ka-score-bar")?.style.setProperty("width", d.grade_score + "%");
    el.querySelectorAll(".si-fill").forEach(bar => {
      bar.style.width = bar.dataset.score + "%";
    });
  }, 50));
}

function buildResultHTML(d) {
  const q = d.quote || {};
  const gradeColor = GRADE_COLOR[d.grade] || "var(--label)";
  const changeCls = q.up ? "text-up" : "text-down";
  const changeSign = q.up ? "+" : "-";
  const tradeTime = _fmtTradeTime(q.trade_datetime);
  const statusLabel = { OPEN: "장중", CLOSE: "장마감" }[q.market_status] || "";

  return `
<div class="ka-result-card">

  <!-- 헤더 -->
  <div class="ka-result-header">
    <div>
      <span class="ka-stock-name">${d.name}</span>
      <span class="ka-stock-code ms-2">(${d.code})</span>
    </div>
    <div class="ka-price">
      현재가 <strong style="color:var(--text)">${W(d.current_price)}</strong>
      ${q.change_pct != null ? `<span class="${changeCls}" style="font-size:0.82rem;margin-left:6px">${changeSign}${W(Math.abs(q.change_won || 0))} (${changeSign}${Math.abs(q.change_pct)}%)</span>` : ""}
      ${tradeTime ? `<div class="form-hint">${tradeTime}${statusLabel ? " · " + statusLabel : ""} 기준</div>` : ""}
    </div>
    <div class="ka-price">시드 <strong style="color:var(--text)">${W(d.seed)}</strong></div>
    <div class="ka-grade-chip" style="color:${gradeColor};border-color:${gradeColor}">
      <span class="ka-grade-letter">${d.grade}</span>
      <span class="ka-grade-sub">종목 등급</span>
    </div>
  </div>

  <div class="ka-result-body">

    <!-- ■ 종합점수 -->
    <div class="ka-total-score">
      <div class="d-flex align-items-end gap-3 mb-2">
        <div>
          <div class="ka-score-label">■ 종합점수 (종목 적합성, 100점 만점)</div>
          <div>
            <span class="ka-score-num" style="color:${gradeColor}">${d.grade_score}</span>
            <span class="ka-score-unit"> / 100점 · ${d.grade}등급</span>
          </div>
        </div>
        <div style="flex:1;padding-bottom:0.3rem">
          <div class="ka-score-bar-wrap">
            <div class="ka-score-bar" style="width:0%;background:linear-gradient(90deg,${gradeColor},${gradeColor}88)"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ■ Kelly Score + 투자비중 -->
    <div class="ka-kelly-summary-box mb-4">
      <div class="row g-3 align-items-center">
        <div class="col-12 col-md-4">
          <div class="ka-score-label">■ Kelly Score</div>
          <div><span class="ka-score-num" style="font-size:1.6rem;color:var(--cyan)">${d.kelly_score}</span><span class="ka-score-unit"> / 100</span></div>
          <div class="ka-stars">${d.stars}</div>
        </div>
        <div class="col-12 col-md-4">
          <div class="ka-score-label">■ 매수 적합도</div>
          <div class="ka-opinion-inline" style="color:${gradeColor}">${d.opinion}</div>
        </div>
        <div class="col-12 col-md-4">
          <div class="ka-score-label">■ Kelly 적정 투자비중</div>
          <div class="ka-position-value">시드의 <strong style="color:var(--cyan)">${d.position_pct}%</strong></div>
          <div class="form-hint">투자 예산 ${W(d.budget)} (Full Kelly 미사용, Half/Quarter 이하로 제한)</div>
        </div>
      </div>
    </div>

    <!-- 세부 점수 7항목 -->
    <div class="ka-items-title mb-2">세부 분석</div>
    <div class="ka3-scores-grid mb-4">
      ${buildScoreCard("기술적 지표", d.scores.technical, "var(--purple)")}
      ${buildScoreCard("수급 분석", d.scores.supply, "var(--orange)")}
      ${buildScoreCard("재무/밸류", d.scores.fundamental, "var(--cyan)")}
      ${buildScoreCard("컨센서스", d.scores.consensus, "var(--green)")}
      ${buildScoreCard("거래대금", d.scores.trading_value, "var(--yellow)")}
      ${buildScoreCard("시장 대비 상대강도", d.scores.relative_strength, "var(--down)")}
      ${buildScoreCard("손익비/리스크", d.scores.risk_reward, "var(--up)")}
    </div>

    <!-- 재무 핵심 지표 -->
    <div class="ka-items-title">재무 핵심 지표</div>
    <div class="ka-fin-grid mb-4">
      ${[
        ["매출 성장",  d.fin_summary.revenue_growth   != null ? P(d.fin_summary.revenue_growth, 1)   : "—"],
        ["영업이익률", d.fin_summary.operating_margin != null ? P(d.fin_summary.operating_margin, 1) : "—"],
        ["부채비율",   d.fin_summary.debt_ratio       != null ? P(d.fin_summary.debt_ratio, 1)       : "—"],
        ["PER",       d.fin_summary.per               != null ? PX(d.fin_summary.per)                : "—"],
        ["PBR",       d.fin_summary.pbr               != null ? PX(d.fin_summary.pbr)                : "—"],
        ["ROE",       d.fin_summary.roe               != null ? P(d.fin_summary.roe * 100, 1)        : "—"],
        ["시가총액",  WON_UNIT(d.fin_summary.market_cap)],
        ["목표주가",  d.scores.consensus.target_price != null ? W(d.scores.consensus.target_price) : "—"],
      ].map(([l, v]) => `
      <div class="ka-fin-cell">
        <div class="fc-label">${l}</div>
        <div class="fc-value">${v}</div>
      </div>`).join("")}
    </div>

    <!-- ■ 분할매수 가격 -->
    ${buildSplitBuySection(d)}
    ${buildFullSeedSplitSection(d)}

    <!-- ■ 상승 시 추가매수 전략 (불타기) -->
    ${buildPyramidSection(d)}

    <div class="row g-3 mb-2">
      <div class="col-12 col-lg-6">${buildStopSection(d)}</div>
      <div class="col-12 col-lg-6">${buildTakeProfitSection(d)}</div>
    </div>
    <div class="form-hint mb-4">
      ※ 손절가·목표가는 이번 조회 시점의 평균단가(${N(d.split_buy.avg_price || d.current_price)}원 — ${d.split_buy.avg_price ? "Kelly 비중 기준 분할매수 평균단가" : "매수 예산이 0이라 현재가로 대체"}) 기준으로 계산됩니다.
      실시간으로 자동 갱신되지 않으며, 가격이 바뀐 뒤 다시 계산하려면 재조회하세요.
      실제 매수한 평균단가가 다르다면 그 가격을 기준으로 직접 비율을 적용해 판단하세요.
    </div>

    <!-- ■ 핵심 이벤트 -->
    ${buildEventsSection(d)}

    <!-- ■ 시나리오 -->
    ${buildScenarioSection(d)}

    <!-- 결론 -->
    <div class="ka-verdict-banner">
      <div class="ka-verdict-label">결론</div>
      <div class="ka-verdict-text">${d.verdict}</div>
    </div>

  </div>
</div>`;
}

function _fmtTradeTime(iso) {
  if (!iso) return "";
  const m = iso.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[1]}.${m[2]}.${m[3]} ${m[4]}:${m[5]}` : "";
}

// ─── 세부 점수 카드 ───────────────────────
function buildScoreCard(label, res, color) {
  return `
<div class="ka-score-item">
  <div class="si-label">${label}</div>
  <div class="si-bar"><div class="si-fill" data-score="${res.score}" style="width:0%;background:${color}"></div></div>
  <div class="si-num" style="color:${color}">${res.score}점</div>
  ${res.items.map(([type, text]) => `
  <div class="ka-item ${type}"><span class="icon">${ITEM_ICON[type]}</span><span>${text}</span></div>`).join("")}
</div>`;
}

// ─── 분할매수 섹션 ────────────────────────
function _buildSplitBuyTable(sb, totalBudget) {
  const rows = sb.stages.map(s => `
<tr>
  <td style="font-weight:700;color:var(--cyan)">${s.round}차</td>
  <td class="text-end" style="color:var(--text);font-weight:600">${N(s.price)}원</td>
  <td class="text-end" style="color:var(--label)">${s.ratio_pct}%</td>
  <td class="text-end" style="color:var(--text2)">${W(s.allocated)}</td>
  <td class="text-end" style="color:var(--text);font-weight:600">${N(s.qty)}주</td>
  <td class="text-end" style="color:var(--text2)">${W(s.actual)}</td>
</tr>`).join("");

  return `
<div class="table-card mb-4">
  <div class="table-responsive">
    <table class="table table-dark table-sm mb-0" style="font-size:0.83rem">
      <thead><tr><th>회차</th><th class="text-end">진입가격</th><th class="text-end">배분비중</th>
        <th class="text-end">투자금액</th><th class="text-end">매수수량</th><th class="text-end">실투자금</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr style="border-top:1px solid var(--border);background:rgba(255,255,255,0.03)">
          <td style="font-weight:700;color:var(--label)">평균단가</td>
          <td class="text-end" style="color:var(--yellow);font-weight:700">${N(sb.avg_price)}원</td>
          <td class="text-end" style="color:var(--label)">100%</td>
          <td class="text-end" style="color:var(--text);font-weight:700">${W(totalBudget)}</td>
          <td class="text-end" style="color:var(--text);font-weight:700">${N(sb.total_qty)}주</td>
          <td class="text-end" style="color:var(--text);font-weight:700">${W(sb.total_cost)}</td>
        </tr>
      </tfoot>
    </table>
  </div>
</div>`;
}

// ─── 분할매수 ① Kelly 투자비중 기준 (종합점수/Kelly Score에 연동) ───
function buildSplitBuySection(d) {
  const sb = d.split_buy;

  let warning = "";
  if (sb.insufficient) {
    warning = d.position_pct === 0
      ? `<div class="ka-warning-box mb-3">⚠ Kelly Score ${d.kelly_score}점 — 매수 적합도가 "관망"이라 투자비중이 0%로 배정되어 신규 분할매수 대상이 아닙니다 (Kelly Score 60점 이상부터 비중이 배정됩니다). 아래 가격은 참고용 진입 레벨이며 투자금액/수량은 0으로 표시됩니다. 실제로 몇 주를 살 수 있는지는 아래 "시드 전액 기준" 표를 참고하세요.</div>`
      : `<div class="ka-warning-box mb-3">⚠ 시드 부족 — 배정된 투자예산(${W(d.budget)})으로는 이 가격대에서 1주도 매수할 수 없습니다.</div>`;
  }

  return `
<div class="ka-items-title mb-2">■ 분할매수 가격 — Kelly 투자비중 기준 (1차 → 2차 → 3차)</div>
<div class="ka-pos-note mb-2">${sb.reason} 총 예산은 시드의 ${d.position_pct}%(${W(d.budget)})입니다.</div>
${warning}
${_buildSplitBuyTable(sb, d.budget)}`;
}

// ─── 분할매수 ② 시드 전액 기준 (종합점수·Kelly 의견과 무관한 참고표) ───
function buildFullSeedSplitSection(d) {
  const sb = d.full_seed_split_buy;
  if (!sb) return "";

  const warning = sb.insufficient
    ? `<div class="ka-warning-box mb-3">⚠ 시드 전액(${W(d.seed)})으로도 이 가격대에서 1주를 매수할 수 없습니다.</div>`
    : "";

  return `
<div class="ka-items-title mb-2 mt-4">■ 분할매수 가격 — 시드 전액 기준 (참고용, 등급·Kelly 의견과 무관)</div>
<div class="ka-pos-note mb-2">
  ${sb.reason} 위 Kelly 비중 표와 달리, 등급·Kelly Score와 상관없이 <strong style="color:var(--text2)">시드 전액(${W(d.seed)})</strong>을 지금 실시간 가격에 투입한다고 가정했을 때의 참고용 표입니다.
  실제 매수 여부·비중은 위의 Kelly 적정 투자비중(${d.position_pct}%, ${d.opinion})을 기준으로 판단하세요.
</div>
${warning}
${_buildSplitBuyTable(sb, d.seed)}`;
}

// ─── 불타기 섹션 ──────────────────────────
function buildPyramidSection(d) {
  const p = d.pyramid;
  const verdictColor = p.verdict === "가능" ? "var(--green)" : p.verdict === "조건부(소량)" ? "var(--yellow)" : "var(--up)";
  const checks = p.conditions.map(([name, ok]) => `
<div class="ka-check-item ${ok ? "ok" : "no"}"><span class="icon">${ok ? "✓" : "✗"}</span><span>${name}</span></div>`).join("");

  return `
<div class="ka-items-title mb-2">■ 상승 시 추가매수 전략 (불타기)</div>
<div class="ka-pyramid-box mb-4">
  <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
    <span class="ka-pyramid-verdict" style="color:${verdictColor};border-color:${verdictColor}">${p.verdict}</span>
    <span style="color:var(--text2);font-size:0.85rem">${p.detail}</span>
  </div>
  <div class="ka-checklist">${checks}</div>
  ${p.gap_pct ? `<div class="form-hint mt-2">당일 갭: ${p.gap_pct >= 0 ? "+" : ""}${p.gap_pct}%</div>` : ""}
</div>`;
}

// ─── 손절가 섹션 ──────────────────────────
function buildStopSection(d) {
  const s = d.stop;
  return `
<div class="ka-side-card">
  <div class="ka-items-title mb-2">■ 손절가</div>
  <div class="d-flex align-items-center gap-2 mb-2">
    <span class="ka-type-badge">${s.stock_type}</span>
    <span class="form-hint">기준 ${s.stop_range}</span>
  </div>
  <div class="ka-big-price" style="color:var(--up)">${N(s.stop_price)}원</div>
  <div class="form-hint mt-1">${s.reason}</div>
</div>`;
}

// ─── 익절 섹션 ────────────────────────────
function buildTakeProfitSection(d) {
  const tp = d.take_profit;
  const rows = [
    ["1차", tp.stage1], ["2차", tp.stage2], ["최종", tp.stage3],
  ];
  return `
<div class="ka-side-card">
  <div class="ka-items-title mb-2">■ 목표가 (익절)</div>
  ${rows.map(([label, s]) => `
  <div class="ka-tp-row">
    <span class="ka-tp-label">${label} (+${s.pct}%)</span>
    <span class="ka-tp-price">${N(s.price)}원</span>
    <span class="form-hint">${s.note}</span>
  </div>`).join("")}
</div>`;
}

// ─── 핵심 이벤트 섹션 ─────────────────────
function buildEventsSection(d) {
  const ev = d.events;
  const rs = ev.relative_strength;

  const newsHtml = (ev.news && ev.news.length)
    ? ev.news.map(n => `<a href="${n.url}" target="_blank" rel="noopener" class="ka-link-item"><span class="ka-link-date">${n.date}</span>${n.title}</a>`).join("")
    : `<div class="form-hint">최근 뉴스 없음</div>`;

  const discHtml = ev.dart_key_missing
    ? `<div class="form-hint">DART API 키 미설정 — .env에 DART_API_KEY를 설정하면 공시가 표시됩니다.</div>`
    : (ev.disclosures && ev.disclosures.length)
      ? ev.disclosures.map(x => `<a href="${x.url}" target="_blank" rel="noopener" class="ka-link-item"><span class="ka-link-date">${x.date}</span>${x.title}</a>`).join("")
      : `<div class="form-hint">최근 3개월 내 공시 없음</div>`;

  return `
<div class="ka-items-title mb-2">■ 핵심 이벤트</div>
<div class="ka-event-grid mb-4">
  <div class="ka-event-cell">
    <div class="fc-label">실적 발표 예정일</div>
    <div class="fc-value">${ev.earnings || "미정"}</div>
  </div>
  <div class="ka-event-cell">
    <div class="fc-label">다음 FOMC</div>
    <div class="fc-value">${ev.fomc || "—"}</div>
  </div>
  <div class="ka-event-cell" style="grid-column:span 2">
    <div class="fc-label">업황 (시장 대비 상대강도)</div>
    <div class="fc-value" style="font-size:0.85rem">${rs.items.map(([, t]) => t).join(" · ")}</div>
  </div>
  <div class="ka-event-cell ka-event-list" style="grid-column:span 2">
    <div class="fc-label">최근 뉴스</div>
    ${newsHtml}
  </div>
  <div class="ka-event-cell ka-event-list" style="grid-column:span 2">
    <div class="fc-label">최근 공시 (DART)</div>
    ${discHtml}
  </div>
</div>`;
}

// ─── 시나리오 섹션 ────────────────────────
function buildScenarioSection(d) {
  const sc = d.scenarios;
  const cards = [
    ["강세 시나리오", sc.bull, "var(--up)"],
    ["중립 시나리오", sc.neutral, "var(--label)"],
    ["약세 시나리오", sc.bear, "var(--down)"],
  ];
  return `
<div class="ka-items-title mb-2">■ 시나리오</div>
<div class="ka-scenario-grid mb-4">
  ${cards.map(([label, text, color]) => `
  <div class="ka-scenario-card" style="border-color:${color}44">
    <div class="ka-scenario-label" style="color:${color}">${label}</div>
    <div class="ka-scenario-text">${text}</div>
  </div>`).join("")}
</div>`;
}

// ─── 누적 종목 비교 목록 ─────────────────
let kaListItems = [];

function addToKellyList(d) {
  kaListItems = kaListItems.filter(x => x.code !== d.code);
  kaListItems.unshift(d);
  renderKellyList();
}

function renderKellyList() {
  const el = document.getElementById("ka-list");
  if (kaListItems.length < 2) { el.innerHTML = ""; return; }

  el.innerHTML = `
<div class="section-title mt-2" style="font-size:1rem">
  <span class="badge-section">비교</span>분석 종목 비교
</div>
<div class="table-card">
  <div class="table-responsive">
    <table class="table table-dark table-hover table-sm mb-0">
      <thead>
        <tr>
          <th>종목</th>
          <th class="text-end">현재가</th>
          <th class="text-end">등급</th>
          <th class="text-end">Kelly Score</th>
          <th class="text-end">투자비중</th>
          <th class="text-end">예산</th>
          <th class="text-end">손절가</th>
          <th>매수 적합도</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${kaListItems.map((d, i) => {
          const gradeColor = GRADE_COLOR[d.grade] || "var(--label)";
          return `
<tr>
  <td class="ka-list-name-cell" onclick="jumpToKaItem(${i})">
      <strong>${d.name}</strong>
      <span style="color:var(--label);font-size:0.72rem;margin-left:4px">${d.code}</span></td>
  <td class="text-end">${N(d.current_price)}원</td>
  <td class="text-end" style="color:${gradeColor};font-weight:700">${d.grade}</td>
  <td class="text-end" style="font-weight:700">${d.kelly_score}</td>
  <td class="text-end" style="color:var(--cyan);font-weight:700">${d.position_pct}%</td>
  <td class="text-end">${W(d.budget)}</td>
  <td class="text-end" style="color:var(--up)">${N(d.stop.stop_price)}원</td>
  <td style="font-size:0.78rem">${d.opinion}</td>
  <td>
    <button class="btn btn-sm btn-outline-danger py-0 px-1"
            onclick="removeKaItem(${i})">✕</button>
  </td>
</tr>`;
        }).join("")}
      </tbody>
    </table>
  </div>
</div>`;
}

function removeKaItem(i) {
  kaListItems.splice(i, 1);
  renderKellyList();
}

function jumpToKaItem(i) {
  const d = kaListItems[i];
  if (!d) return;
  document.getElementById("ka-code").value = d.code;
  document.getElementById("ka-seed").value = _comma(d.seed);
  document.getElementById("ka-target").value = d.target_pct;
  document.getElementById("ka-price").value = "";
  renderKellyResult(d);
  document.getElementById("ka-result").scrollIntoView({ behavior: "smooth", block: "start" });
}
