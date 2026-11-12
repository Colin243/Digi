// node tests/picks_api_check.cjs — exercises api/submit + api/picks against an in-memory Redis.
const assert = require("assert");
process.env.KV_REST_API_URL = "https://kv.test"; process.env.KV_REST_API_TOKEN = "t"; process.env.PICKS_READ_KEY = "rk";
const db = new Map(), sets = new Map();
global.fetch = async (_u, opt) => {
  const [cmd, ...a] = JSON.parse(opt.body); let result = null;
  if (cmd === "SET") db.set(a[0], a[1]);
  else if (cmd === "SADD") { (sets.get(a[0]) || sets.set(a[0], new Set()).get(a[0])).add(a[1]); result = 1; }
  else if (cmd === "SMEMBERS") result = [...(sets.get(a[0]) || [])];
  else if (cmd === "MGET") result = a.map((k) => db.get(k) ?? null);
  else if (cmd === "DEL") result = db.delete(a[0]) ? 1 : 0;
  else if (cmd === "SREM") result = sets.get(a[0])?.delete(a[1]) ? 1 : 0;
  return { ok: true, json: async () => ({ result }) };
};
const dir = process.argv[2] || "review_site/picks_api";
const submit = require(require("path").resolve(dir, "submit.js")), read = require(require("path").resolve(dir, "picks.js"));
const call = async (h, req) => { let code = 0, body; const res = { status(c) { code = c; return this; }, json(b) { body = b; return this; } };
  await h({ headers: {}, ...req }, res); return { code, body }; };
(async () => {
  const doc = { pick_id: "picks-v2", name: "Jasmine", client_id: "abc", picks: { "s|t": { choices: [1] } } };
  assert.equal((await call(submit, { method: "GET" })).code, 405);
  assert.equal((await call(submit, { method: "POST", body: { ...doc, pick_id: "other" } })).code, 400);
  assert.equal((await call(submit, { method: "POST", body: { ...doc, padding: "x".repeat(400000) } })).code, 413);
  assert.equal((await call(submit, { method: "POST", body: JSON.stringify(doc) })).code, 200);
  assert.equal((await call(submit, { method: "POST", body: { ...doc, picks: { "s|t": { choices: [1, 3] } } } })).code, 200);  // replaces
  assert.equal((await call(read, { headers: {} })).code, 401);
  const r = await call(read, { headers: { "x-read-key": "rk" } });
  assert.equal(r.code, 200); assert.equal(r.body.submissions.length, 1);
  assert.deepEqual(r.body.submissions[0].picks["s|t"].choices, [1, 3]);
  const slot = r.body.submissions[0].slot;
  assert.equal((await call(read, { method: "DELETE", query: { slot }, headers: {} })).code, 401);
  assert.equal((await call(read, { method: "DELETE", query: { slot }, headers: { "x-read-key": "rk" } })).code, 200);
  assert.equal((await call(read, { headers: { "x-read-key": "rk" } })).body.submissions.length, 0);
  console.log("picks api ok");
})().catch((e) => { console.error(e); process.exit(1); });
