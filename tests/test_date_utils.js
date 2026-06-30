"use strict";

const assert = require("node:assert/strict");
const { parseDate } = require("../docs/assets/js/date-utils.js");

for (const [raw, expected] of [
  ["2026-05-15", [2026, 5, 15]],
  ["2026-06-30", [2026, 6, 30]],
  ["2026-07-01", [2026, 7, 1]],
]) {
  const date = parseDate(raw);
  assert.ok(date, `No se pudo interpretar ${raw}`);
  assert.equal(date.getFullYear(), expected[0]);
  assert.equal(date.getMonth() + 1, expected[1]);
  assert.equal(date.getDate(), expected[2]);
}

console.log("Fechas calendario validadas correctamente.");
