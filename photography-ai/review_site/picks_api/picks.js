// GET /api/picks — every stored submission, for `photo-ai picks pull`. Needs the read key (PICKS_READ_KEY env var),
// so the page itself can never read anyone's picks back.
const { redis } = require("./_store");
const PICK_ID = process.env.PICK_ID || "picks-v2";

module.exports = async (req, res) => {
  const key = process.env.PICKS_READ_KEY;
  if (!key || req.headers["x-read-key"] !== key) return res.status(401).json({ error: "read key required" });
  try {
    const slots = (await redis("SMEMBERS", `picks-index:${PICK_ID}`)) || [];
    const docs = slots.length ? await redis("MGET", ...slots.map((s) => `picks:${s}`)) : [];
    return res.status(200).json({ pick_id: PICK_ID, submissions: docs.filter(Boolean).map((d) => JSON.parse(d)) });
  } catch (e) { return res.status(503).json({ error: "storage unavailable" }); }
};
