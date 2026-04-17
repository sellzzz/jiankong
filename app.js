const statusEl = document.getElementById('status');
const bodyEl = document.getElementById('ratesBody');
const refreshInput = document.getElementById('refreshInterval');
const thresholdInput = document.getElementById('highlightThreshold');
const refreshNowBtn = document.getElementById('refreshNowBtn');

let timer = null;

function setStatus(message) {
  statusEl.textContent = message;
}

function formatUtc(input) {
  if (!input) return '—';
  const date = new Date(Number(input));
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 19);
}

function rateToPercentString(rawRate) {
  const rate = Number(rawRate);
  if (!Number.isFinite(rate)) return '—';
  return `${(rate * 100).toFixed(4)}%`;
}

function parseThreshold() {
  const percent = Number(thresholdInput.value);
  if (!Number.isFinite(percent) || percent < 0) {
    return 0.05;
  }
  return percent / 100;
}

function renderRows(rows) {
  if (!rows.length) {
    bodyEl.innerHTML = '<tr><td colspan="5" class="placeholder">未获取到数据，可能是接口临时不可用。</td></tr>';
    return;
  }

  const threshold = parseThreshold();
  const html = rows
    .sort((a, b) => Math.abs(Number(b.rate)) - Math.abs(Number(a.rate)))
    .map((row) => {
      const rate = Number(row.rate);
      const rateClass = Number.isFinite(rate) ? (rate >= 0 ? 'rate-positive' : 'rate-negative') : '';
      const shouldHighlight = Number.isFinite(rate) && Math.abs(rate) >= threshold;
      const trClass = shouldHighlight ? 'highlight' : '';
      return `
        <tr class="${trClass}">
          <td>${row.exchange}</td>
          <td>${row.symbol}</td>
          <td class="${rateClass}">${rateToPercentString(rate)}</td>
          <td>${formatUtc(row.nextFundingTime)}</td>
          <td>${formatUtc(row.updatedTime)}</td>
        </tr>
      `;
    })
    .join('');

  bodyEl.innerHTML = html;
}

async function fetchBinanceRates() {
  const url = 'https://fapi.binance.com/fapi/v1/premiumIndex';
  const response = await fetch(url);
  if (!response.ok) throw new Error('Binance 请求失败');
  const data = await response.json();

  return data
    .filter((item) => item.symbol.endsWith('USDT'))
    .slice(0, 80)
    .map((item) => ({
      exchange: 'Binance',
      symbol: item.symbol,
      rate: item.lastFundingRate,
      nextFundingTime: item.nextFundingTime,
      updatedTime: Date.now(),
    }));
}

async function fetchBybitRates() {
  const url = 'https://api.bybit.com/v5/market/tickers?category=linear';
  const response = await fetch(url);
  if (!response.ok) throw new Error('Bybit 请求失败');
  const payload = await response.json();
  const list = payload?.result?.list || [];

  return list.slice(0, 80).map((item) => ({
    exchange: 'Bybit',
    symbol: item.symbol,
    rate: item.fundingRate,
    nextFundingTime: item.nextFundingTime,
    updatedTime: Date.now(),
  }));
}

async function fetchOkxRates() {
  const instrumentsUrl = 'https://www.okx.com/api/v5/public/instruments?instType=SWAP';

  const instrumentsResp = await fetch(instrumentsUrl);
  if (!instrumentsResp.ok) throw new Error('OKX 合约列表请求失败');
  const instrumentsPayload = await instrumentsResp.json();

  const instIds = (instrumentsPayload?.data || [])
    .map((item) => item.instId)
    .filter((id) => id.endsWith('-USDT-SWAP'))
    .slice(0, 20);

  const requests = instIds.map(async (instId) => {
    const response = await fetch(`https://www.okx.com/api/v5/public/funding-rate?instId=${encodeURIComponent(instId)}`);
    if (!response.ok) return null;
    const payload = await response.json();
    const item = payload?.data?.[0];
    if (!item) return null;

    return {
      exchange: 'OKX',
      symbol: item.instId,
      rate: item.fundingRate,
      nextFundingTime: item.nextFundingTime,
      updatedTime: item.fundingTime || Date.now(),
    };
  });

  const results = await Promise.all(requests);
  return results.filter(Boolean);
}

async function refreshData() {
  const started = Date.now();
  setStatus('正在拉取数据...');

  const jobs = [fetchBinanceRates(), fetchBybitRates(), fetchOkxRates()];
  const settled = await Promise.allSettled(jobs);

  const rows = settled.flatMap((result) => (result.status === 'fulfilled' ? result.value : []));
  const failures = settled.filter((result) => result.status === 'rejected').length;

  renderRows(rows);

  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  if (failures === 0) {
    setStatus(`已更新 ${rows.length} 条数据，耗时 ${seconds}s`);
  } else {
    setStatus(`已更新 ${rows.length} 条数据，${failures} 个交易所请求失败，耗时 ${seconds}s`);
  }
}

function scheduleRefresh() {
  if (timer) clearInterval(timer);

  const seconds = Number(refreshInput.value);
  if (!Number.isFinite(seconds) || seconds < 10) {
    setStatus('刷新间隔过小，已使用 10 秒。');
  }
  const intervalMs = Math.max(10, Number.isFinite(seconds) ? seconds : 10) * 1000;

  timer = setInterval(() => {
    refreshData().catch((err) => {
      setStatus(`刷新失败：${err.message}`);
    });
  }, intervalMs);
}

refreshInput.addEventListener('change', scheduleRefresh);
thresholdInput.addEventListener('change', () => refreshData().catch((err) => setStatus(`刷新失败：${err.message}`)));
refreshNowBtn.addEventListener('click', () => refreshData().catch((err) => setStatus(`刷新失败：${err.message}`)));

scheduleRefresh();
refreshData().catch((err) => {
  setStatus(`初始化失败：${err.message}`);
});
