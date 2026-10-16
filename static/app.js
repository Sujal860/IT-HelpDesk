(function () {
  const palette = ['#236bce', '#20a28a', '#8b6de8', '#e5a33d', '#438cb8', '#d56c8e', '#6876c8'];

  function renderGanttChart(id) {
    const root = document.getElementById(id);
    if (!root) return;
    let rows = [];
    try { rows = JSON.parse(root.dataset.results || '[]'); } catch (_) { rows = []; }
    root.innerHTML = '';
    if (!rows.length) {
      root.innerHTML = '<div class="gantt-empty">No scheduling results to display.</div>';
      return;
    }
    const anchor = new Date(String(root.dataset.anchor || '').replace(' ', 'T'));
    const maxTime = Math.max(1, ...rows.map((r) => Number(r.completion_time || 0)));
    const chartWidth = Math.max(900, Math.min(6000, Math.ceil(maxTime * 1.2)));
    const ticks = 6;
    const fmt = (offset) => {
      const d = new Date(anchor.getTime() + offset * 60000);
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const mon = d.toLocaleString('en', { month: 'short' });
      return day + ' ' + mon + ' ' + hh + ':' + mm;
    };
    const axis = document.createElement('div');
    axis.className = 'gantt-axis';
    axis.innerHTML = '<div class="gantt-label"><strong>TIME</strong><small>date · hh:mm</small></div><div class="gantt-axis-track" style="min-width:' + chartWidth + 'px">' +
      Array.from({ length: ticks + 1 }, (_, i) => {
        const t = Math.round((maxTime * i) / ticks);
        return '<span style="left:' + (i / ticks * 100) + '%">' + fmt(t) + '</span>';
      }).join('') + '</div>';
    root.appendChild(axis);
    const row = document.createElement('div');
    row.className = 'gantt-row gantt-single-row';
    row.innerHTML = '<div class="gantt-label"><strong>PROCESSES</strong><small>' + rows.length + ' tickets</small></div><div class="gantt-timeline"><div class="gantt-track" style="min-width:' + chartWidth + 'px"></div></div>';
    const track = row.querySelector('.gantt-track');
    const timelineEnd = anchor.getTime() + maxTime * 60000;
    const addShade = (from, to) => {
      if (to <= from || to <= anchor.getTime() || from >= timelineEnd) return;
      const leftMinutes = Math.max(0, (from - anchor.getTime()) / 60000);
      const rightMinutes = Math.min(maxTime, (to - anchor.getTime()) / 60000);
      const shade = document.createElement('div');
      shade.className = 'gantt-off-hours';
      shade.style.left = leftMinutes / maxTime * 100 + '%';
      shade.style.width = (rightMinutes - leftMinutes) / maxTime * 100 + '%';
      shade.title = 'Non-working hours: 19:00–08:00';
      track.appendChild(shade);
    };
    let day = new Date(anchor);
    if (day.getHours() >= 19) {
      const nextMorning = new Date(day);
      nextMorning.setDate(nextMorning.getDate() + 1);
      nextMorning.setHours(8, 0, 0, 0);
      addShade(anchor.getTime(), nextMorning.getTime());
      day = new Date(nextMorning);
    } else if (day.getHours() < 8) {
      const morning = new Date(day);
      morning.setHours(8, 0, 0, 0);
      addShade(anchor.getTime(), morning.getTime());
      day = morning;
    }
    day.setHours(19, 0, 0, 0);
    while (day.getTime() < timelineEnd) {
      const nextMorning = new Date(day);
      nextMorning.setDate(nextMorning.getDate() + 1);
      nextMorning.setHours(8, 0, 0, 0);
      addShade(day.getTime(), nextMorning.getTime());
      day = new Date(nextMorning);
      day.setHours(19, 0, 0, 0);
    }
    rows.forEach((r, i) => {
      const start = Number(r.start_time || 0);
      const completion = Number(r.completion_time || 0);
      const service = Math.max(0, Number(r.service_time || completion - start));
      const left = start / maxTime * 100;
      const width = service / maxTime * 100;
      const code = 'HD-' + String(r.ticket_id).padStart(4, '0');
      const title = String(r.title || ('Ticket ' + r.ticket_id));
      const bar = document.createElement('div');
      bar.className = 'gantt-bar';
      bar.style.left = left + '%';
      bar.style.width = width + '%';
      bar.style.background = palette[i % palette.length];
      bar.title = code + ' · ' + title + ' · ' + fmt(start) + '–' + fmt(completion) + ' · service ' + String(Math.floor(service / 60)).padStart(2, '0') + ':' + String(service % 60).padStart(2, '0');
      const label = document.createElement('span');
      label.textContent = width >= 7 ? code : String(r.queue_order || i + 1);
      bar.appendChild(label);
      track.appendChild(bar);
    });
    root.appendChild(row);
    const note = document.createElement('div');
    note.className = 'gantt-scale-note';
    note.textContent = 'Work hours: 08:00–19:00. Shaded gaps mark overnight downtime; any ticket that cannot finish by 19:00 starts at 08:00 the next day.';
    root.appendChild(note);
  }

  window.renderGanttChart = renderGanttChart;
  document.addEventListener('DOMContentLoaded', function () {
    const textarea = document.querySelector('textarea[name="description"]');
    if (textarea) textarea.addEventListener('input', function () {
      textarea.style.height = 'auto';
      textarea.style.height = textarea.scrollHeight + 'px';
    });
  });
})();
