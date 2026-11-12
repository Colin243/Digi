// GET /api/picks — every stored submission, for `photo-ai picks pull`. DELETE /api/picks?slot=<slot> removes one
// (a test or bad submission). Both need the read key (PICKS_READ_KEY env var), so the page can never read or
// delete anyone's picks.
const { redis } = require("./_store");
const PICK_ID = process.env.PICK_ID || "picks-v2";

module.exports = async (req, res) => {
  const key = process.env.PICKS_READ_KEY;
  if (!key || req.headers["x-read-key"] !== key) return res.status(401).json({ error: "read key required" });
  if (req.method === "DELETE") {
    const slot = String((req.query && req.query.slot) || "");
    if (!slot.startsWith(`${PICK_ID}:`)) return res.status(400).json({ error: "slot required" });
    try {
      await redis("DEL", `picks:${slot}`);
      await redis("SREM", `picks-index:${PICK_ID}`, slot);
      return res.status(200).json({ ok: true, deleted: slot });
    } catch (e) { return res.status(503).json({ error: "storage unavailable" }); }
  }
  try {
    const slots = (await redis("SMEMBERS", `picks-index:${PICK_ID}`)) || [];
    const docs = slots.length ? await redis("MGET", ...slots.map((s) => `picks:${s}`)) : [];
    return res.status(200).json({ pick_id: PICK_ID, submissions: docs.map((d, i) => d && { ...JSON.parse(d), slot: slots[i] }).filter(Boolean) });
  } catch (e) { return res.status(503).json({ error: "storage unavailable" }); }
};
