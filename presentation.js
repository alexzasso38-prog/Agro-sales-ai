/* Presentation only: fictitious read-only snapshot, no backend or real login. */
(() => {
  const data = window.AGRO_PRESENTATION;
  const originalFetch = window.fetch.bind(window);
  const json = (value, status = 200) => Promise.resolve(new Response(JSON.stringify(value), {status, headers: {'Content-Type': 'application/json'}}));
  window.fetch = (input, options = {}) => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), location.href);
    const method = (options.method || request?.method || 'GET').toUpperCase();
    if (url.origin !== location.origin) return json({detail: 'Le connessioni esterne sono disabilitate nella presentazione.'}, 403);
    if (url.pathname === '/health') return json({status: 'ok', demo_mode: true, presentation: true});
    if (url.pathname.startsWith('/api/')) {
      const path = url.pathname.slice(4);
      if (path === '/auth/login' && method === 'POST') {
        return json({access_token: 'presentation-only-not-a-real-token', user: data['/auth/me'], demo_mode: true});
      }
      if (method !== 'GET') return json({detail: 'Modalità presentazione: puoi consultare le schermate. Salvataggi, invii e automazioni richiedono la demo locale con backend.'}, 409);
      return Object.hasOwn(data, path) ? json(data[path]) : json({detail: 'Questa schermata non è disponibile nella presentazione.'}, 404);
    }
    if (method !== 'GET') return json({detail: 'Operazione disabilitata nella presentazione.'}, 403);
    return originalFetch(input, options);
  };
  const banner = document.createElement('div');
  banner.id = 'presentation-notice';
  banner.setAttribute('role', 'note');
  banner.textContent = 'PRESENTAZIONE · Dati fittizi · Solo consultazione · Nessun invio, chiamata o agente attivo';
  banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:10000;background:#224434;color:white;padding:8px 12px;text-align:center;font:12px system-ui;pointer-events:none';
  if (document.body) document.body.appendChild(banner);
  else document.addEventListener("DOMContentLoaded", () => document.body.appendChild(banner), {once: true});
})();
