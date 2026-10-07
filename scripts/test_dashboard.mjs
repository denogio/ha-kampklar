import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

let Card;
const context = vm.createContext({
  HTMLElement: class {},
  customElements: { define: (_name, value) => { Card = value; } },
});
const source = await readFile(new URL("../www/kampklar-activities-card.js", import.meta.url), "utf8");
vm.runInContext(source.replaceAll("export function", "function"), context);
const { activitiesFromStates, signupData } = context;
const plain = (value) => JSON.parse(JSON.stringify(value));
const states = {
  "sensor.kampklar_born": {
    state: "2",
    attributes: { children: [
      { short_name: "Emil", entity_ids: { upcoming_activities: "sensor.emil" } },
      { short_name: "Ida", entity_ids: { upcoming_activities: "sensor.ida" } },
    ] },
  },
  "sensor.emil": { state: "1", attributes: { activities: [
    { id: 42, title: "Træning", date: "2026-10-15", signup_locked: false },
  ] } },
  "sensor.ida": { state: "1", attributes: { activities: [
    { id: 43, title: "Kamp", date: "2026-10-14", signup_locked: true },
  ] } },
};

test("finds both children, uses born fallback and sorts by date", () => {
  const activities = activitiesFromStates(states);
  assert.deepEqual(plain(activities.map((activity) => activity.id)), [43, 42]);
  assert.equal(activities[1].child, "Emil");
  assert.equal(activities[1].source, "sensor.emil");
});

test("includes the child's stable key in action data", () => {
  const keyedStates = {
    ...states,
    "sensor.kampklar_born": {
      ...states["sensor.kampklar_born"],
      attributes: { children: [{ ...states["sensor.kampklar_born"].attributes.children[0], key: "t11" }] },
    },
  };
  const activity = activitiesFromStates(keyedStates)[0];
  assert.equal(activity.child_key, "t11");
  assert.deepEqual(plain(signupData(activity, "frameld", "Er syg")), {
    activity_id: 42, child_key: "t11", comment: "Er syg",
  });
});

test("supports a child filter and a renamed parent entity", () => {
  const activities = activitiesFromStates({ ...states, "sensor.custom": states["sensor.kampklar_born"] }, {
    children_entity: "sensor.custom", child: "Emil",
  });
  assert.deepEqual(plain(activities.map((activity) => activity.id)), [42]);
});

test("ignores missing and unavailable entities instead of using stale attributes", () => {
  assert.deepEqual(plain(activitiesFromStates({})), []);
  assert.deepEqual(plain(activitiesFromStates({
    ...states, "sensor.kampklar_born": { ...states["sensor.kampklar_born"], state: "unavailable" },
  })), []);
  assert.equal(activitiesFromStates({
    ...states, "sensor.emil": { ...states["sensor.emil"], state: "unavailable" },
  }).length, 1);
});

test("signup sends ID and decline requires a nonempty trimmed comment", () => {
  const activity = states["sensor.emil"].attributes.activities[0];
  assert.deepEqual(plain(signupData(activity, "tilmeld", "")), { activity_id: 42 });
  assert.deepEqual(plain(signupData(activity, "frameld", "  Er syg  ", { config_entry_id: "account" })), {
    activity_id: 42, comment: "Er syg", config_entry_id: "account",
  });
  assert.throws(() => signupData(activity, "frameld", "   "), /begrundelse/);
  assert.throws(() => signupData({ ...activity, signup_locked: true }, "tilmeld", ""), /lukket/);
  assert.throws(() => signupData(undefined, "tilmeld", ""), /gyldigt ID/);
});

const key = "sensor.emil:42";
function mockCard(callService) {
  return {
    config: {}, result: {},
    drafts: new Map([[key, { comment: "Er syg", expanded: true }]]),
    activities: activitiesFromStates(states),
    _hass: { callService }, _updateBusy() {}, _render() {},
  };
}

test("calls the integration and clears the comment only after success", async () => {
  const calls = [];
  const card = mockCard(async (...args) => calls.push(plain(args)));
  await Card.prototype._submit.call(card, "frameld", key);
  assert.deepEqual(calls, [["kampklar", "frameld", { activity_id: 42, comment: "Er syg" }]]);
  assert.equal(card.drafts.get(key).comment, "");
  assert.equal(card.drafts.get(key).expanded, false);
  assert.match(card.result.textContent, /Frameldt: Emil/);
});

test("preserves the comment and displays backend errors", async () => {
  const card = mockCard(async () => { throw new Error("DBU afviste handlingen"); });
  await Card.prototype._submit.call(card, "frameld", key);
  assert.equal(card.drafts.get(key).comment, "Er syg");
  assert.equal(card.drafts.get(key).expanded, true);
  assert.equal(card.result.className, "error");
  assert.equal(card.result.textContent, "DBU afviste handlingen");
  assert.equal(card._busy, false);
});

test("does not send blank decline comments or duplicate clicks", async () => {
  let calls = 0;
  const card = mockCard(async () => { calls++; });
  card.drafts.get(key).comment = " ";
  await Card.prototype._submit.call(card, "frameld", key);
  assert.equal(calls, 0);
  card._busy = true;
  await Card.prototype._submit.call(card, "tilmeld", key);
  assert.equal(calls, 0);
});

test("checks latest sensor state before sending an action", async () => {
  let calls = 0;
  const card = mockCard(async () => { calls++; });
  card.activities = card.activities.map((activity) => ({ ...activity, signup_locked: true }));
  await Card.prototype._submit.call(card, "tilmeld", key);
  assert.equal(calls, 0);
  assert.match(card.result.textContent, /lukket/);
  card.activities = [];
  await Card.prototype._submit.call(card, "tilmeld", key);
  assert.equal(calls, 0);
  assert.match(card.result.textContent, /gyldigt ID/);
});

test("keeps comments from different sensor rows separate when activity IDs overlap", async () => {
  const calls = [];
  const card = mockCard(async (...args) => calls.push(plain(args)));
  const otherKey = "sensor.ida:42";
  card.activities.push({ ...card.activities[1], source: "sensor.ida", child: "Ida" });
  card.drafts.set(otherKey, { comment: "På ferie", expanded: true });
  await Card.prototype._submit.call(card, "frameld", otherKey);
  assert.deepEqual(calls, [["kampklar", "frameld", { activity_id: 42, comment: "På ferie" }]]);
  assert.equal(card.drafts.get(key).comment, "Er syg");
  assert.match(card.result.textContent, /Frameldt: Ida/);
});

test("blocks other actions while a DBU request is in flight", async () => {
  let finish;
  let calls = 0;
  const card = mockCard(() => { calls++; return new Promise((resolve) => { finish = resolve; }); });
  const pending = Card.prototype._submit.call(card, "frameld", key);
  await Card.prototype._submit.call(card, "tilmeld", key);
  assert.equal(calls, 1);
  assert.equal(card._busy, true);
  finish();
  await pending;
  assert.equal(card._busy, false);
});

// Minimal DOM stand-in for testing row controls without a browser dependency.
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.selectors = new Map();
    this.listeners = {};
    this.dataset = {};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) {
    if (!this.selectors.has(selector)) {
      const tag = selector === ".buttons" ? "div" : selector === "textarea" ? "textarea" : "p";
      this.selectors.set(selector, new Element(tag));
    }
    return this.selectors.get(selector);
  }
  addEventListener(event, callback) { this.listeners[event] = callback; }
}
context.document = { createElement: (tag) => new Element(tag) };

function rowCard() {
  return { drafts: new Map(), _button: Card.prototype._button, _render() {} };
}

test("keeps decline available when signup is closed", () => {
  const card = rowCard();
  const activity = activitiesFromStates(states)[1];
  const row = Card.prototype._row.call(card, activity);
  assert.deepEqual(row.querySelector(".buttons").children.map((button) => button.textContent), ["Tilmeld", "Frameld"]);
  const locked = Card.prototype._row.call(card, { ...activity, signup_locked: true });
  assert.deepEqual(locked.querySelector(".buttons").children.map((button) => button.textContent), ["Frameld"]);
  assert.match(locked.querySelector(".status").textContent, /tilmelding lukket/);
  const declined = Card.prototype._row.call(card, { ...activity, signup_locked: true, signup_status: "Frameldt" });
  assert.equal(declined.querySelector(".buttons").children.length, 0);
  assert.deepEqual(plain(signupData({ ...activity, signup_locked: true }, "frameld", "Er syg")), {
    activity_id: 42, comment: "Er syg",
  });
});

test("decline form preserves drafts and cancel does not call DBU", () => {
  const card = rowCard();
  const activity = activitiesFromStates(states)[1];
  card.drafts.set(key, { comment: "Er syg", expanded: true });
  let submits = 0;
  card._submit = () => { submits++; };
  const row = Card.prototype._row.call(card, activity);
  const form = row.children.find((element) => element.tagName === "FORM");
  assert.equal(form.querySelector("textarea").value, "Er syg");
  assert.deepEqual(form.querySelector(".buttons").children.map((button) => button.textContent), ["Send afbud", "Annuller"]);
  form.querySelector(".buttons").children[1].listeners.click();
  assert.equal(card.drafts.get(key).expanded, false);
  assert.equal(submits, 0);
});

test("DBU titles are rendered as text, never injected into HTML", () => {
  const card = rowCard();
  const title = '<img src="x" onerror="alert(1)">';
  const row = Card.prototype._row.call(card, { ...activitiesFromStates(states)[1], title });
  assert.equal(row.querySelector("h4").textContent, `Emil — ${title}`);
  assert.ok(!row.innerHTML.includes(title));
});

test("renders a chronological mixed-child list with a name on every row", () => {
  const activity = states["sensor.emil"].attributes.activities[0];
  const mixedStates = {
    ...states,
    "sensor.emil": { state: "2", attributes: { activities: [
      { ...activity, date: "2026-10-14", time: "18:00 - 19:00" },
      { ...activity, id: 44, date: "2026-10-14", time: "15:00 - 16:00" },
    ] } },
    "sensor.ida": { state: "1", attributes: { activities: [
      { ...activity, id: 43, date: "2026-10-14", time: "16:00 - 17:00" },
    ] } },
  };
  const card = {
    ...rowCard(), list: new Element("div"), shadowRoot: {},
    activities: activitiesFromStates(mixedStates),
    _row: Card.prototype._row, _updateBusy() {},
  };
  Card.prototype._render.call(card);
  assert.deepEqual(card.list.children.map((row) => row.querySelector("h4").textContent), [
    "Emil — Træning", "Ida — Træning", "Emil — Træning",
  ]);
  assert.deepEqual(card.list.children.map((row) => row.querySelector(".details").textContent.split("\\n")[0]), [
    "2026-10-14 · 15:00 - 16:00", "2026-10-14 · 16:00 - 17:00", "2026-10-14 · 18:00 - 19:00",
  ]);
});
