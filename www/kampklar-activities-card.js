// Dependency-free Home Assistant card. Register /local/kampklar-activities-card.js as a module.
export function activitiesFromStates(states, config = {}) {
  const entity = config.children_entity || (
    states["sensor.kampklar_boern"] ? "sensor.kampklar_boern" : "sensor.kampklar_born"
  );
  const parent = states[entity];
  if (!parent || ["unavailable", "unknown"].includes(parent.state)) return [];
  return (parent.attributes.children || []).flatMap((child) => {
    if (config.child && child.short_name !== config.child) return [];
    const source = states[child.entity_ids?.upcoming_activities];
    if (!source || ["unavailable", "unknown"].includes(source.state)) return [];
    return (source.attributes.activities || []).map((activity) => ({
      ...activity,
      child: child.short_name,
      source: source.entity_id || child.entity_ids.upcoming_activities,
    }));
  }).sort((a, b) => `${a.date || ""} ${a.time || ""}`.localeCompare(`${b.date || ""} ${b.time || ""}`));
}

export function signupData(activity, action, comment, config = {}) {
  if (!activity || !Number.isInteger(activity.id) || activity.id <= 0) {
    throw new Error("Aktiviteten har ikke et gyldigt ID.");
  }
  if (activity.signup_locked && action === "tilmeld") {
    throw new Error("Aktiviteten er lukket for tilmelding.");
  }
  const data = { activity_id: activity.id };
  if (config.config_entry_id) data.config_entry_id = config.config_entry_id;
  if (action === "frameld") {
    if (!comment.trim()) throw new Error("Skriv en begrundelse for frameldingen.");
    data.comment = comment.trim();
  }
  return data;
}

const activityKey = (activity) => `${activity.source}:${activity.id}`;

class KampklarActivitiesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.drafts = new Map();
    this.activities = [];
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        h2 { margin: 0 0 16px; font-size: 20px; font-weight: 500; }
        h3 { margin: 20px 0 8px; font-size: 18px; }
        article { padding: 12px 0; border-bottom: 1px solid var(--divider-color, #888); }
        article:last-child { border-bottom: 0; }
        h4 { margin: 0 0 6px; font-size: 16px; }
        label { display: block; margin: 12px 0 6px; }
        textarea, button { font: inherit; box-sizing: border-box; }
        textarea { width: 100%; padding: 10px; border-radius: 6px; resize: vertical;
          border: 1px solid var(--divider-color, #888); color: var(--primary-text-color);
          background: var(--card-background-color); }
        p { margin: 6px 0; line-height: 1.5; white-space: pre-line; }
        .buttons { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
        button { padding: 10px 16px; border: 0; border-radius: 6px; cursor: pointer;
          background: var(--primary-color, #1774c7); color: var(--text-primary-color, white); }
        button:disabled { opacity: .5; cursor: not-allowed; }
        .error { color: var(--error-color, #db4437); }
      </style>
      <ha-card>
        <h2></h2>
        <p id="result" role="status" aria-live="polite"></p>
        <div id="activities"></div>
      </ha-card>`;
    this.list = this.shadowRoot.querySelector("#activities");
    this.result = this.shadowRoot.querySelector("#result");
  }

  setConfig(config) {
    this.config = config;
    this.shadowRoot.querySelector("h2").textContent = config.title || "Kommende aktiviteter";
    this._signature = undefined;
    if (this._hass) this.hass = this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.config) return;
    const activities = activitiesFromStates(hass.states, this.config);
    const signature = JSON.stringify(activities);
    if (signature === this._signature) return;
    this._signature = signature;
    this.activities = activities;
    // Hold den igangværende formular stabil, indtil DBU-kaldet er afsluttet.
    if (!this._busy) this._render();
  }

  _render() {
    const active = this.shadowRoot.activeElement;
    const focusKey = active?.dataset.key;
    const selection = focusKey ? [active.selectionStart, active.selectionEnd] : undefined;
    this.list.replaceChildren();
    const groups = new Map();
    for (const activity of this.activities) {
      if (!groups.has(activity.child)) groups.set(activity.child, []);
      groups.get(activity.child).push(activity);
    }
    if (!groups.size) this.list.textContent = "Ingen tilgængelige kommende aktiviteter.";
    for (const [child, activities] of groups) {
      const heading = document.createElement("h3");
      heading.textContent = child;
      this.list.append(heading);
      for (const activity of activities) this.list.append(this._row(activity));
    }
    for (const key of this.drafts.keys()) {
      if (!this.activities.some((activity) => activityKey(activity) === key)) this.drafts.delete(key);
    }
    if (focusKey) {
      const input = [...this.list.querySelectorAll("textarea")].find((element) => element.dataset.key === focusKey);
      input?.focus();
      input?.setSelectionRange(...selection);
    }
    this._updateBusy();
  }

  _row(activity) {
    const key = activityKey(activity);
    const draft = this.drafts.get(key) || { comment: "", expanded: false };
    this.drafts.set(key, draft);
    const row = document.createElement("article");
    row.innerHTML = `<h4></h4><p class="details"></p><p class="status"></p><div class="buttons"></div>`;
    row.querySelector("h4").textContent = activity.title;
    row.querySelector(".details").textContent = [
      [activity.weekday, activity.date, activity.time].filter(Boolean).join(" · "),
      [activity.type, activity.location].filter(Boolean).join(" · "),
      activity.meeting_time && `Mødetid: ${activity.meeting_time}`, activity.pool,
    ].filter(Boolean).join("\n");
    row.querySelector(".status").textContent = `Status: ${activity.signup_status || "Ikke svaret"}${activity.signup_locked ? " (tilmelding lukket)" : ""}`;
    if (!Number.isInteger(activity.id) || activity.id <= 0) return row;
    const buttons = row.querySelector(".buttons");
    if (!activity.signup_locked) {
      this._button(buttons, "Tilmeld", () => this._submit("tilmeld", key));
    }
    // DBU kan tillade afbud, selv når nye tilmeldinger er lukket.
    // Den konkrete statusknap på aktivitetssiden valideres af backend.
    const declined = activity.signup_status_key === "frameldt" || activity.signup_status?.trim().toLowerCase() === "frameldt";
    if (!declined) {
      this._button(buttons, "Frameld", () => {
        draft.expanded = true;
        this._render();
        [...this.list.querySelectorAll("textarea")].find((input) => input.dataset.key === key)?.focus();
      });
    }
    if (draft.expanded && !declined) {
      const form = document.createElement("form");
      form.innerHTML = `<label>Begrundelse for framelding (obligatorisk)<textarea rows="2" required placeholder="Fx: Er syg"></textarea></label><div class="buttons"></div>`;
      const input = form.querySelector("textarea");
      input.dataset.key = key;
      input.value = draft.comment;
      input.addEventListener("input", () => { draft.comment = input.value; });
      const controls = form.querySelector(".buttons");
      this._button(controls, "Send afbud", () => {}, "submit");
      this._button(controls, "Annuller", () => {
        draft.expanded = false;
        this._render();
      });
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this._submit("frameld", key);
      });
      row.append(form);
    }
    return row;
  }

  _button(parent, label, callback, type = "button") {
    const button = document.createElement("button");
    button.type = type;
    button.textContent = label;
    button.addEventListener("click", callback);
    parent.append(button);
  }

  _updateBusy() {
    for (const control of this.list.querySelectorAll("button, textarea")) control.disabled = Boolean(this._busy);
  }

  async _submit(action, key) {
    if (this._busy) return;
    const draft = this.drafts.get(key);
    try {
      // Brug seneste sensordata, ikke en gammel aktivitet fra en click-handler.
      const activity = this.activities.find((item) => activityKey(item) === key);
      const data = signupData(activity, action, draft?.comment || "", this.config);
      this._busy = true;
      this._updateBusy();
      this.result.className = "";
      this.result.textContent = "Sender til DBU…";
      await this._hass.callService("kampklar", action, data);
      if (draft) { draft.comment = ""; draft.expanded = false; }
      this.result.textContent = `${action === "tilmeld" ? "Tilmeldt" : "Frameldt"}: ${activity.child} — ${activity.title}`;
    } catch (error) {
      this.result.className = "error";
      this.result.textContent = error.message || "Handlingen mislykkedes. Prøv igen senere.";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  getCardSize() { return 2 + this.activities.length * 3; }
}

customElements.define("kampklar-activities-card", KampklarActivitiesCard);
