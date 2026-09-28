const chart = document.querySelector('#price-chart');
const context = chart.getContext('2d');
const chartEmpty = document.querySelector('#chart-empty');
const periodLabels = { '1d': 'Últimas 24 horas', '5d': 'Últimos 5 días', '1m': 'Último mes' };
let selectedPeriod = '1d';
let previousPrice = null;
let alarm = JSON.parse(localStorage.getItem('amper-alarm') || '{}');
let alertedAbove = false;
let alertedBelow = false;

const formatPrice = value => Number(value).toLocaleString('es-ES', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const formatTime = value => new Intl.DateTimeFormat('es-ES', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value));

function drawChart(points) {
  const width = chart.clientWidth;
  const height = chart.clientHeight;
  const scale = window.devicePixelRatio || 1;
  chart.width = Math.round(width * scale);
  chart.height = Math.round(height * scale);
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);
  chartEmpty.hidden = points.length > 0;
  if (!points.length) return;

  const pad = { top: 16, right: 12, bottom: 26, left: 62 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const values = points.map(point => point.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || max * 0.01 || 0.01;
  const low = min - spread * 0.14;
  const high = max + spread * 0.14;
  const x = index => pad.left + (points.length < 2 ? plotWidth / 2 : index / (points.length - 1) * plotWidth);
  const y = value => pad.top + (high - value) / (high - low) * plotHeight;

  context.font = '10px "DM Mono", monospace';
  context.textAlign = 'right';
  context.textBaseline = 'middle';
  for (let line = 0; line <= 3; line++) {
    const value = high - (high - low) * line / 3;
    const lineY = pad.top + plotHeight * line / 3;
    context.strokeStyle = '#e5eae6';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(pad.left, lineY);
    context.lineTo(width - pad.right, lineY);
    context.stroke();
    context.fillStyle = '#75817b';
    context.fillText(formatPrice(value), pad.left - 9, lineY);
  }

  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(x(index), y(point.price)) : context.moveTo(x(index), y(point.price)));
  const fill = context.createLinearGradient(0, pad.top, 0, pad.top + plotHeight);
  fill.addColorStop(0, 'rgba(38, 124, 98, .18)');
  fill.addColorStop(1, 'rgba(38, 124, 98, 0)');
  context.lineTo(x(points.length - 1), pad.top + plotHeight);
  context.lineTo(x(0), pad.top + plotHeight);
  context.closePath();
  context.fillStyle = fill;
  context.fill();

  context.beginPath();
  points.forEach((point, index) => index ? context.lineTo(x(index), y(point.price)) : context.moveTo(x(index), y(point.price)));
  context.strokeStyle = '#267c62';
  context.lineWidth = 2;
  context.lineJoin = 'round';
  context.stroke();

  const labels = [points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]];
  const positions = [pad.left, pad.left + plotWidth / 2, width - pad.right];
  labels.forEach((point, index) => {
    const date = new Date(point.timestamp);
    context.textAlign = index === 0 ? 'left' : index === 2 ? 'right' : 'center';
    context.fillStyle = '#75817b';
    context.fillText(selectedPeriod === '1d' ? date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }) : date.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' }), positions[index], height - 8);
  });
}

async function loadHistory() {
  try {
    const response = await fetch(`/api/history?period=${selectedPeriod}`, { cache: 'no-store' });
    const data = await response.json();
    drawChart(data.points);
    document.querySelector('#chart-range').textContent = periodLabels[selectedPeriod];
  } catch {
    chartEmpty.hidden = false;
    chartEmpty.textContent = 'No se pudo cargar el histórico';
  }
}

function checkAlarm(price) {
  const crossedAbove = alarm.above && price >= Number(alarm.above) && !alertedAbove;
  const crossedBelow = alarm.below && price <= Number(alarm.below) && !alertedBelow;
  if (crossedAbove || crossedBelow) {
    const message = crossedAbove ? `Amper ha superado ${formatPrice(alarm.above)} €` : `Amper ha bajado de ${formatPrice(alarm.below)} €`;
    document.querySelector('#alarm-note').textContent = message;
    if ('Notification' in window && Notification.permission === 'granted') new Notification('Alarma de Amper', { body: message });
    if (crossedAbove) alertedAbove = true;
    if (crossedBelow) alertedBelow = true;
  }
}

async function refreshQuote() {
  try {
    const response = await fetch('/api/quote', { cache: 'no-store' });
    const quote = await response.json();
    document.querySelector('#market-status').textContent = quote.status || 'Sin datos';
    document.querySelector('#state-dot').className = `state-dot ${quote.status === 'Conectado' ? 'online' : quote.status === 'Sin conexión con el proveedor' ? 'offline' : ''}`;
    document.querySelector('#polling-note').textContent = `Actualización cada ${quote.poll_seconds || 60} s`;
    if (quote.price == null) return;

    document.querySelector('#price').textContent = formatPrice(quote.price);
    const change = document.querySelector('#change');
    const metricChange = document.querySelector('#metric-change');
    if (quote.change != null) {
      const positive = quote.change >= 0;
      const sign = positive ? '+' : '';
      const detail = `${sign}${formatPrice(quote.change)} € (${sign}${Number(quote.change_percent).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%)`;
      change.textContent = detail;
      change.className = `change ${positive ? 'up' : 'down'}`;
      metricChange.textContent = detail;
      metricChange.className = positive ? 'positive' : 'negative';
    } else {
      change.textContent = 'Variación diaria no disponible';
      change.className = 'change neutral';
    }
    document.querySelector('#metric-volume').textContent = Number(quote.volume || 0).toLocaleString('es-ES');
    document.querySelector('#metric-updated').textContent = formatTime(quote.timestamp);
    checkAlarm(quote.price);
    if (previousPrice !== quote.price) {
      previousPrice = quote.price;
      await loadHistory();
    }
  } catch {
    document.querySelector('#market-status').textContent = 'API no disponible';
    document.querySelector('#state-dot').className = 'state-dot offline';
  }
}

document.querySelectorAll('[data-period]').forEach(button => button.addEventListener('click', () => {
  selectedPeriod = button.dataset.period;
  document.querySelectorAll('[data-period]').forEach(item => {
    const active = item === button;
    item.classList.toggle('active', active);
    item.setAttribute('aria-pressed', String(active));
  });
  loadHistory();
}));

document.querySelector('#save-alarm').addEventListener('click', () => {
  alarm = { above: document.querySelector('#alarm-above').value, below: document.querySelector('#alarm-below').value };
  localStorage.setItem('amper-alarm', JSON.stringify(alarm));
  alertedAbove = false;
  alertedBelow = false;
  document.querySelector('#alarm-note').textContent = 'Límites guardados en este navegador.';
});

document.querySelector('#notify-button').addEventListener('click', async () => {
  if (!('Notification' in window)) {
    document.querySelector('#alarm-note').textContent = 'Este navegador no admite notificaciones.';
    return;
  }
  const permission = await Notification.requestPermission();
  document.querySelector('#alarm-note').textContent = permission === 'granted' ? 'Notificaciones activadas.' : 'Notificaciones no autorizadas.';
});

document.querySelector('#alarm-above').value = alarm.above || '';
document.querySelector('#alarm-below').value = alarm.below || '';
window.addEventListener('resize', loadHistory);
refreshQuote();
loadHistory();
setInterval(refreshQuote, 15000);