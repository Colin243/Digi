// POST /api/submit — store (or replace) one reviewer's picks. Anyone with the page can write, so the payload is
// validated and size-capped; each device has its own slot (name + client id), so a resubmission replaces it.
const { redis } = require("./_store");
const PICK_ID = process.env.PICK_ID || "picks-v2";
const MAX_BYTES = 300 * 1024;

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  let doc = req.body;
  try { if (typeof doc === "string") doc = JSON.parse(doc); } catch (e) { return res.status(400).json({ error: "bad json" }); }
  const raw = JSON.stringify(doc || {});
  if (raw.length > MAX_BYTES) return res.status(413).json({ error: "too large" });
  const name = String((doc && doc.name) || "").trim().slice(0, 40);
  const client = String((doc && doc.client_id) || "").replace(/[^a-z0-9]/gi, "").slice(0, 16);
  if (!doc || doc.pick_id !== PICK_ID || !name || !client || typeof doc.picks !== "object" || Array.isArray(doc.picks))
    return res.status(400).json({ error: "not a picks submission" });
  const slot = `${PICK_ID}:${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}:${client}`;
  try {
    await redis("SET", `picks:${slot}`, JSON.stringify({ ...doc, name, client_id: client, received_at: new Date().toISOString() }));
    await redis("SADD", `picks-index:${PICK_ID}`, slot);
  } catch (e) { return res.status(503).json({ error: "storage unavailable" }); }
  return res.status(200).json({ ok: true, places: Object.keys(doc.picks).length });
};
