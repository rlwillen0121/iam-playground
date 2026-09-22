import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
if (!html.includes("<title>IAM Playground</title>")) {
  throw new Error("title missing");
}
if (!html.includes("loopback")) {
  throw new Error("loopback missing");
}
for (const name of ["Overview", "Applications", "Data", "Scenarios", "Activity"]) {
  if (!html.includes(name)) {
    throw new Error("view missing: " + name);
  }
}
if (!html.includes("app.css") || !html.includes("app.js")) {
  throw new Error("page assets missing");
}
const banned = ["synthetic-lab-", "Bearer ", "LAB_ADMIN_TOKEN"];
for (const word of banned) {
  if (html.includes(word)) {
    throw new Error("page contains a secret-like value");
  }
}

const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");
const js = readFileSync(new URL("./app.js", import.meta.url), "utf8");
if (!css.trim() || !js.trim()) {
  throw new Error("page asset is empty");
}

mkdirSync(new URL("./dist/", import.meta.url), { recursive: true });
writeFileSync(new URL("./dist/index.html", import.meta.url), html);
writeFileSync(new URL("./dist/app.css", import.meta.url), css);
writeFileSync(new URL("./dist/app.js", import.meta.url), js);
