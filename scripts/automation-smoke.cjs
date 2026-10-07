// Real UI + worker end-to-end. Backend/frontend/worker must already be running.
// Only local demo URLs are accepted; every non-local browser request is blocked.
// Creates a unique, explicitly fictional CSV campaign, so reruns do not reuse
// an opted-out contact from another campaign.
const { chromium } = require("../frontend/node_modules/playwright");
const assert = require("node:assert/strict");
const base = process.env.AGRO_UI_URL || "http://127.0.0.1:5173";
const target = new URL(base);
assert(target.protocol === "http:" && ["127.0.0.1", "localhost"].includes(target.hostname) && !target.username && !target.password, "Usare soltanto una demo HTTP locale");

(async () => {
  const browser = await chromium.launch({
    ...(process.env.AGRO_BROWSER_PATH ? { executablePath: process.env.AGRO_BROWSER_PATH } : {}),
    headless: true, args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: "Europe/Rome" });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const errors = [], blocked = [];
    page.on("pageerror", error => errors.push(error.message));
    await context.route("**/*", route => {
      const hostname = new URL(route.request().url()).hostname;
      if (["127.0.0.1", "localhost"].includes(hostname)) return route.continue();
      blocked.push(hostname); return route.abort();
    });
    async function api(path) {
      return page.evaluate(async path => {
        const response = await fetch("/api" + path, { headers: { Authorization: "Bearer " + sessionStorage.getItem("agro_token") } });
        if (!response.ok) throw Error(await response.text());
        return response.json();
      }, path);
    }
    async function waitFor(check, description, timeout = 60000) {
      const until = Date.now() + timeout;
      while (Date.now() < until) {
        const result = await check();
        if (result) return result;
        await page.waitForTimeout(350);
      }
      throw Error("Tempo scaduto: " + description + ". Verifica che il worker sia attivo con --interval 1.");
    }
    async function navigate(name) {
      await page.locator(".sidebar .nav-item").filter({ hasText: name }).click();
    }
    await page.goto(base);
    assert.equal((await api("/meta")).demo_mode, true, "Il test si ferma fuori dalla demo");
    await page.getByRole("button", { name: "Entra nella demo", exact: true }).click();
    await page.getByRole("heading", { name: /Buongiorno,/ }).waitFor();
    const profile = await api("/profile");
    const suffix = Date.now();
    const name = `Campagna browser ${suffix} · FITTIZIA DEMO`;
    const escaped = value => '"' + String(value).replaceAll('"', '""') + '"';
    const csv = [
      "company_name,email,city,business_type,menu_text,source",
      ...Array.from({ length: 6 }, (_, index) => [
        `Ristorante Browser Demo ${suffix}-${index}`,
        `automation-${suffix}-${index}@horeca.test`, "Milano", "Ristorante",
        index % 2 === 0 ? profile.catalog.map(item => item.name).join("; ") : "",
        "Test browser — contatto interamente FITTIZIO DEMO",
      ].map(escaped).join(",")),
    ].join("\n");
    await navigate("Automazioni AI");
    await page.getByRole("heading", { name: "Automazioni AI", exact: true }).waitFor();
    await page.getByRole("button", { name: "Nuova campagna AI", exact: true }).first().click();
    let dialog = page.getByRole("dialog", { name: "Nuova campagna AI", exact: true });
    await dialog.getByLabel("Nome della campagna", { exact: true }).fill(name);
    await dialog.getByLabel("Numero di lead", { exact: true }).fill("6");
    await dialog.getByLabel("Origine dei contatti").selectOption("csv");
    await dialog.getByLabel("Carica il tuo CSV").setInputFiles({ name: "contatti-fittizi-demo.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await dialog.getByLabel("Score minimo / 100", { exact: true }).fill("70");
    await dialog.locator("summary").filter({ hasText: "Limiti e controllo" }).click();
    await dialog.getByLabel("Secondi demo per 1 giorno della sequenza", { exact: true }).fill("10");
    await dialog.getByRole("button", { name: "Crea campagna AI", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    const campaign = (await api("/campaigns")).find(item => item.name === name);
    assert(campaign, "Campagna persistita dal backend");
    const path = `/campaigns/${campaign.id}`;
    await page.getByRole("button", { name: "Avvia campagna AI", exact: true }).click();
    let detail = await waitFor(async () => {
      const item = await api(path);
      return item.leads.length === 6 && item.leads.every(lead => lead.score != null) && item.leads.some(lead => lead.draft_id) && item;
    }, "lead progressivi, qualificazione e bozze del worker");
    assert(detail.leads.some(lead => lead.score < 70));
    assert(detail.leads.some(lead => lead.score >= 70));
    assert(detail.tasks.length && detail.events.length);
    assert.equal(detail.agents.length, 6);
    await waitFor(async () => await page.locator(".automation-lead").count() === 6, "polling dei lead nella UI");
    assert(await page.getByRole("log").locator(".live-event").count() > 0);
    assert(await page.locator(".workflow-step.completed").count() > 0);
    console.log("PASS creazione via UI/CSV, worker reale, soglia, sei agenti, live activity e graph persistenti");

    await page.getByRole("button", { name: "Pausa campagna", exact: true }).click();
    await waitFor(async () => (await api(path)).status === "PAUSED", "campagna in pausa");
    await page.getByRole("button", { name: "Riprendi campagna", exact: true }).click();
    await waitFor(async () => (await api(path)).status === "RUNNING", "campagna ripresa");
    await page.getByRole("button", { name: "Metti in pausa Outreach Agent", exact: true }).click();
    await waitFor(async () => (await api(path)).agents.some(agent => agent.agent === "outreach" && agent.status === "PAUSED"), "agente in pausa");
    await page.getByRole("button", { name: "Riprendi Outreach Agent", exact: true }).click();
    await waitFor(async () => (await api(path)).agents.some(agent => agent.agent === "outreach" && agent.status !== "PAUSED"), "agente ripreso");
    console.log("PASS pausa/ripresa campagna e agente dai controlli UI");

    const lead = detail.leads.find(item => item.score >= 70 && item.draft_id);
    let card = page.locator(".automation-lead").filter({ hasText: lead.company_name });
    await card.getByRole("button", { name: "Rivedi e approva bozza", exact: true }).click();
    dialog = page.getByRole("dialog", { name: "Il tuo messaggio, la tua voce", exact: true });
    const body = dialog.getByLabel("Messaggio", { exact: true });
    await body.fill((await body.inputValue()) + "\nBozza demo revisionata dal browser.");
    await dialog.getByRole("button", { name: "Salva modifiche", exact: true }).click();
    await dialog.getByRole("button", { name: "Approva bozza", exact: true }).click();
    await dialog.getByRole("button", { name: "Simula invio", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    const leadPath = `/leads/${lead.lead_id}`;
    let leadDetail = await api(leadPath);
    assert(leadDetail.conversations.some(message => message.direction === "outbound" && message.simulated));
    assert(leadDetail.tasks.length > 0);
    await page.getByRole("button", { name: "Accelera tempo demo", exact: true }).click();
    await waitFor(async () => (await api(leadPath)).drafts.some(draft => draft.task_id && draft.status === "pending"), "follow-up generato dal worker");
    console.log("PASS modifica/approvazione/invio simulato e follow-up da scadenza accelerata");

    card = page.locator(".automation-lead").filter({ hasText: lead.company_name });
    await card.getByRole("button", { name: "Simula risposta lead", exact: true }).click();
    dialog = page.getByRole("dialog", { name: `Simula risposta lead · ${lead.company_name}`, exact: true });
    await dialog.getByLabel("Scenario della risposta").selectOption("interested");
    await dialog.getByLabel("Risposta personalizzata (facoltativa)", { exact: true }).fill("Sono interessato a 20 kg entro venerdì. Budget dichiarato 250 euro. Vorrei un preventivo.");
    await dialog.getByRole("button", { name: "Simula risposta", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    await waitFor(async () => (await api("/human-closer")).find(item => item.lead_id === lead.lead_id), "Sales Agent e Human Closer");
    leadDetail = await api(leadPath);
    assert.equal(leadDetail.stop_reason, "reply");
    assert(["interested", "handoff"].includes(leadDetail.stage));
    assert(leadDetail.tasks.every(task => ["completed", "cancelled"].includes(task.status)));
    assert(leadDetail.drafts.filter(draft => draft.kind === "outreach").every(draft => ["sent", "cancelled"].includes(draft.status)));
    assert((await api(path)).events.some(event => event.agent === "sales"));
    console.log("PASS risposta nello stesso workflow, estrazione Sales, stop follow-up, CRM e handoff automatici");

    await page.reload();
    await page.getByRole("heading", { name: /Buongiorno,/ }).waitFor();
    await navigate("Automazioni AI");
    await page.locator(".campaign-card").filter({ hasText: name }).click();
    await waitFor(async () => (await api(path)).leads.length === 6, "persistenza dopo refresh");
    await page.getByRole("button", { name: "Apri Human Closer", exact: true }).click();
    await page.getByRole("heading", { name: "Human Closer", exact: true }).waitFor();
    await page.locator("main").getByText(lead.company_name, { exact: true }).first().waitFor();
    assert((await page.locator("main").innerText()).includes(lead.company_name));
    await page.locator(".closer-inbox-item").filter({ hasText: lead.company_name }).click();
    await page.locator(".closer-detail").getByRole("heading", { name: lead.company_name, exact: true }).waitFor();
    await page.getByRole("button", { name: "Prendi in carico", exact: true }).click();
    const handoff = (await api("/human-closer")).find(item => item.lead_id === lead.lead_id);
    await waitFor(async () => (await api(`/human-closer/${handoff.id}`)).status === "in_progress", "presa in carico persistita");
    await page.getByRole("button", { name: "Segna won", exact: true }).click();
    await waitFor(async () => (await api(leadPath)).stage === "won", "esito commerciale nel CRM");
    console.log("PASS refresh, persistenza, presa in carico Human Closer ed esito won nel CRM");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Apri menu", exact: true }).click();
    await navigate("Automazioni AI");
    await page.getByRole("heading", { name: "Automazioni AI", exact: true }).waitFor();
    await page.locator(".campaign-card").filter({ hasText: name }).click();
    await page.locator(".agent-grid").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false, "Nessun overflow mobile");
    await page.screenshot({ path: require("node:path").join(require("node:os").tmpdir(), "agro-automation-mobile.png"), fullPage: true });
    const metrics = (await api("/dashboard")).metrics;
    assert.equal(metrics.sent_real, 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(blocked, []);
    console.log("PASS mobile 390 px, zero invii reali, zero richieste esterne, zero errori JavaScript");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
