"use strict";

document.documentElement.dataset.workbench = "static";

const VIEWS = ["overview", "applications", "data", "scenarios", "activity"];
const TARGET_HEALTH_URL = "http://127.0.0.1:8090/healthz";
const ADMIN_HEALTH_URL = "http://127.0.0.1:8091/healthz";
const USERS_URL = "http://127.0.0.1:8090/apps/app-a/scim/v2/Users?startIndex=1&count=50";
const SCENARIO_RUN_URL = "http://127.0.0.1:8091/scenarios/run";
const ACTIVITY_URL = "http://127.0.0.1:8091/activity";

let healthTicket = 0;
let usersTicket = 0;
let scenarioTicket = 0;
let activityTicket = 0;

function errorText(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return String(error);
}

function formatHttp(response, text) {
  let body = text;
  if (text) {
    try {
      body = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      body = text;
    }
  }
  return "HTTP " + response.status + " " + response.statusText + "\n" + body;
}

function prettyJson(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

async function fetchText(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    const text = await response.text();
    return formatHttp(response, text);
  } catch (error) {
    return errorText(error);
  }
}

async function loadHealth() {
  const ticket = ++healthTicket;
  const target = document.getElementById("health-target");
  const admin = document.getElementById("health-admin");
  target.textContent = "Loading.";
  admin.textContent = "Loading.";
  async function apply(element, url) {
    const text = await fetchText(url);
    if (ticket !== healthTicket) {
      return;
    }
    element.textContent = text;
  }
  await Promise.all([apply(target, TARGET_HEALTH_URL), apply(admin, ADMIN_HEALTH_URL)]);
}

async function loadUsers() {
  const ticket = ++usersTicket;
  const pre = document.getElementById("data-result");
  pre.textContent = "Loading.";
  try {
    const response = await fetch(USERS_URL, { cache: "no-store" });
    const text = await response.text();
    if (ticket !== usersTicket) {
      return;
    }
    if (!response.ok) {
      pre.textContent = formatHttp(response, text);
      return;
    }
    pre.textContent = prettyJson(text);
  } catch (error) {
    if (ticket !== usersTicket) {
      return;
    }
    pre.textContent = errorText(error);
  }
}

async function runScenario(id) {
  const ticket = ++scenarioTicket;
  const pre = document.getElementById("scenario-result");
  pre.textContent = "Loading.";
  try {
    const response = await fetch(SCENARIO_RUN_URL, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id, mode: "reference" }),
    });
    const text = await response.text();
    if (ticket !== scenarioTicket) {
      return;
    }
    pre.textContent = id + "\n" + formatHttp(response, text);
  } catch (error) {
    if (ticket !== scenarioTicket) {
      return;
    }
    pre.textContent = id + "\n" + errorText(error);
  }
}

async function loadActivity() {
  const ticket = ++activityTicket;
  const pre = document.getElementById("activity-result");
  pre.textContent = "Loading.";
  const text = await fetchText(ACTIVITY_URL);
  if (ticket !== activityTicket) {
    return;
  }
  pre.textContent = text;
}

function showView(name) {
  if (VIEWS.indexOf(name) === -1) {
    return;
  }
  for (const id of VIEWS) {
    document.getElementById(id).hidden = id !== name;
  }
  const buttons = document.querySelectorAll("button[data-view]");
  for (const button of buttons) {
    button.setAttribute("aria-pressed", button.getAttribute("data-view") === name ? "true" : "false");
  }
  if (name === "overview") {
    loadHealth();
  }
  if (name === "activity") {
    loadActivity();
  }
}

document.querySelector("nav").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) {
    return;
  }
  showView(button.getAttribute("data-view"));
});

document.getElementById("load-users").addEventListener("click", () => {
  loadUsers();
});

document.getElementById("scenario-list").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-scenario]");
  if (!button) {
    return;
  }
  const id = button.getAttribute("data-scenario");
  if (!id) {
    return;
  }
  runScenario(id);
});

showView("overview");
