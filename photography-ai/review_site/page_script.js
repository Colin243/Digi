(() => {
  const EX = JSON.parse(document.getElementById("data").textContent);
  const KEY = "shot-review-v1";
  // the exact answer version each reviewed example showed, so an approval can't carry over to edited text
  const shaOf = Object.fromEntries(EX.map((e) => [e.id, e.answer_sha]));
  const exportDoc = () => ({ name: state.name, reviews: state.reviews, updated_at: state.updated_at,
    answer_sha: Object.fromEntries(Object.keys(state.reviews).filter((id) => shaOf[id]).map((id) => [id, shaOf[id]])) });
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  };
  let state = { name: "", reviews: {} };
  try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && s.reviews) state = s; } catch (e) {}
  let filter = "all";
  let db = null, docRef = null, remoteOK = false;

  const rev = (id) => (state.reviews[id] ||= { overall: null, set: null, shots: [{}, {}, {}], comment: "" });
  const status = (id) => {
    const r = state.reviews[id];
    if (!r) return "";
    if (r.overall === "yes" || r.overall === "fix" || r.overall === "no") return r.overall;
    return (r.set || r.shots.some((s) => s.v)) ? "part" : "";
  };
  const reviewedCount = () => EX.filter((e) => ["yes", "fix", "no"].includes(status(e.id))).length;
  const current = () => {
    const h = location.hash.slice(1);
    return EX.find((e) => e.short === h) || EX[0];
  };

  // ---------- persistence: this browser always; the shared store when available ----------
  let saveTimer = null, inflight = Promise.resolve();
  function setSave(text, kind) { const s = $("save"); s.textContent = text; s.dataset.kind = kind || ""; }
  function changed() {
    if (!window.claude) { state.updated_at = new Date().toISOString(); try { localStorage.setItem(KEY, JSON.stringify(state)); setSave("Saved in this browser", "ok"); } catch (e) { setSave("This browser won't save — use Download my review before closing", "warn"); } renderProgress(); return; }
    state.updated_at = new Date().toISOString();
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
    renderProgress();
    if (!docRef) { setSave(remoteOK === false && db === null ? "Saved in this browser · use Copy my review" : "Saved in this browser", "warn"); return; }
    setSave("Saving…");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const body = JSON.parse(JSON.stringify({ ...exportDoc(), version: 1 }));
      inflight = inflight.then(() => docRef.set(body)).then(
        () => setSave("Saved", "ok"),
        (e) => { if (e && e.code === "invalid_argument") { docRef = null; setSave("Can't save to the shared review here · saved in this browser · use Copy my review", "warn"); }
                 else setSave("Not saved yet · will retry on your next change", "warn"); });
    }, 900);
  }

  async function connect() {
    try {
      if (!window.claude || !window.claude.use) throw 0;
      const [d, u] = await Promise.all([window.claude.use("db"), window.claude.use("user")]);
      db = d;
      const uid = u ? await u.id() : null;
      if (!d || !uid) { setSave("Saved in this browser · use Copy my review to send it", "warn"); return; }
      const ref = d.doc("reviews/" + uid);
      const timer = setTimeout(() => setSave("Can't reach the shared review yet · saving in this browser", "warn"), 10000);
      const snap = await ref.get();
      clearTimeout(timer);
      if (snap.exists) {
        const r = snap.data();
        if (!state.updated_at || (r.updated_at && r.updated_at > state.updated_at)) {
          state = { name: r.name || state.name, reviews: JSON.parse(JSON.stringify(r.reviews || {})), updated_at: r.updated_at };
          try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
        }
      }
      if (!state.name) { const me = await u.me(); if (me.name) state.name = me.name; }
      docRef = ref; remoteOK = true;
      setSave("Connected · your answers save automatically", "ok");
      render();
    } catch (e) { setSave("Saved in this browser · use Copy my review to send it", "warn"); }
  }

  // ---------- rendering ----------
  function renderProgress() {
    const n = reviewedCount();
    $("count").textContent = `${n} / ${EX.length} reviewed`;
    $("bar").style.width = (100 * n / EX.length) + "%";
  }
  function renderList() {
    const nav = $("list");
    nav.querySelectorAll("a").forEach((a) => a.remove());
    const cur = current();
    EX.forEach((e, i) => {
      const s = status(e.id);
      if (filter === "todo" && ["yes", "fix", "no"].includes(s)) return;
      nav.append(el("a", { href: "#" + e.short, "aria-current": String(e === cur) },
        el("span", { class: "dot", "data-s": s, "aria-hidden": "true" }),
        el("span", { class: "t", text: `${i + 1}. ${e.technique}` })));
    });
  }
  const frame = (img, label, aspect) => el("figure", { class: "frame" },
    el("button", { type: "button", "aria-label": "Enlarge " + label, onclick: () => openLight(img.src) },
      el("img", { src: img.src, alt: label, loading: "lazy", style: aspect ? `aspect-ratio:${aspect}` : "" })),
    el("figcaption", {}, el("span", { text: label }), el("span", { text: "CC0" })));

  function choice(options, value, onPick) {
    return el("div", { class: "verdict", role: "group" }, options.map(([o, t]) =>
      el("button", { type: "button", "data-o": o, "aria-pressed": String(value === o), onclick: () => onPick(value === o ? null : o) }, t)));
  }
  function shotCard(e, c, k) {
    const r = rev(e.id), s = r.shots[k] ||= {};
    const row = (dt, dd) => dd ? [el("dt", { text: dt }), el("dd", {}, dd)] : [];
    const list = (items, ordered) => items && items.length ? el(ordered ? "ol" : "ul", {}, items.map((x) => el("li", { text: x }))) : null;
    const card = el("section", { class: "shot", "data-v": s.v || "" },
      el("div", { class: "label", text: `Shot ${k + 1}` }),
      el("h3", { text: c.title }),
      el("dl", {},
        row("Where to stand", c.camera_position), row("Camera height", c.camera_height), row("Angle", c.camera_angle),
        row("Subject & pose", c.subject_position), row("Distance & framing", c.distance_and_framing),
        row("Lens & orientation", [c.zoom_or_lens, c.orientation].filter(Boolean).join(" · ")),
        row("Light", c.lighting_tip), row("Steps", list(c.steps, true)),
        row("Check on site", list(c.needs_on_site_check))),
      el("div", { class: "q" }, el("span", { class: "label", text: "Would you take this shot?" }),
        choice([["yes", "Would shoot"], ["fix", "Needs changes"], ["no", "Skip"]], s.v, (v) => { s.v = v; changed(); render(); })),
      el("textarea", { id: `fix-${e.short}-${k}`, placeholder: "What would you change? (optional)", "aria-label": `Changes for shot ${k + 1}`,
        oninput: (ev) => { s.fix = ev.target.value; changed(); } }));
    card.querySelector("textarea").value = s.fix || "";
    return card;
  }
  function render() {
    renderProgress(); renderList();
    const e = current(), i = EX.indexOf(e), r = rev(e.id), a = e.answer;
    if (!$("reviewer").matches(":focus")) $("reviewer").value = state.name || "";
    const sheet = el("article", { class: "sheet" },
      el("div", { class: "sheet-head" },
        el("h2", { text: e.technique.charAt(0).toUpperCase() + e.technique.slice(1) }),
        el("span", { class: "label", text: `Example ${i + 1} of ${EX.length} · ${e.short.toUpperCase()}` })),
      el("div", { class: "strip" },
        el("div", { class: "edge" }, el("span", { text: "INSPIRATION" }), el("span", { text: `${e.inspiration.length} FRAMES` })),
        el("div", { class: "frames" }, e.inspiration.map((img, k) => frame(img, `${k + 1}A`)))),
      el("div", { class: "style" },
        el("span", { class: "label", text: "What the AI says these photos share" }),
        el("p", { text: a.aesthetic.summary }),
        a.aesthetic.principles && a.aesthetic.principles.length ? el("ul", {}, a.aesthetic.principles.map((p) => el("li", { text: p }))) : null,
        el("details", { class: "notes" }, el("summary", { text: "How the AI read each inspiration photo" }),
          el("ol", {}, (a.inspiration_notes || []).map((n) => el("li", { text: n })))),
        el("div", { class: "q" }, el("span", { class: "label", text: "Do these inspiration photos share one clear look?" }),
          choice([["yes", "Clearly"], ["fix", "Loosely"], ["no", "Not really"]], r.set, (v) => { r.set = v; changed(); render(); }))),
      el("div", { class: "loc" },
        frame(e.target, "LOCATION", "4 / 3"),
        el("div", { class: "block" },
          el("span", { class: "label", text: "The new location (AI's reading)" }),
          el("p", { text: a.target_scene.description }),
          el("span", { class: "label", text: "Things to use" }),
          el("div", { class: "chips" }, (a.target_scene.key_elements || []).map((k) => el("span", { class: "chip", text: k }))),
          (a.target_scene.constraints || []).length ? el("span", { class: "label", text: "Watch out for" }) : null,
          (a.target_scene.constraints || []).length ? el("div", { class: "chips" }, a.target_scene.constraints.map((k) => el("span", { class: "chip", text: k }))) : null)),
      el("div", { class: "shots" }, a.compositions.map((c, k) => shotCard(e, c, k))),
      el("div", { class: "final" },
        el("div", { class: "q" }, el("span", { class: "label", text: "Should this example teach the app?" }),
          choice([["yes", "Yes, as is"], ["fix", "Yes, after fixes"], ["no", "No"]], r.overall, (v) => { r.overall = v; changed(); render(); })),
        el("div", { class: "q" }, el("label", { class: "label", for: `comment-${e.short}`, text: "Anything else? What's off, what would you do instead?" }),
          el("textarea", { id: `comment-${e.short}`, oninput: (ev) => { r.comment = ev.target.value; changed(); } })),
        e.ai_notes.length ? el("details", { class: "notes" }, el("summary", { text: "Show the AI reviewers' notes (after you decide)" }),
          el("div", { class: "ai" }, e.ai_notes.map((n) => el("p", {}, el("strong", { text: n.who + ": " }), n.note)))) : null,
        el("div", { class: "navrow" },
          el("button", { class: "btn", type: "button", onclick: () => go(i - 1), disabled: i === 0 ? "" : null }, "← Previous"),
          el("button", { class: "btn primary", type: "button", onclick: () => go(nextTodo(i)) }, "Next example →"))),
      el("p", { class: "credits" }, "Photos: Unsplash via Wikimedia Commons, CC0. ",
        [...e.inspiration, e.target].map((img, k) => el("a", { href: img.page, target: "_blank", rel: "noopener" }, (k ? " · " : "") + img.credit))));
    const c = sheet.querySelector(`#comment-${e.short}`); if (c) c.value = r.comment || "";
    $("sheet").replaceChildren(sheet);
  }
  const nextTodo = (i) => { for (let k = 1; k <= EX.length; k++) { const j = (i + k) % EX.length; if (!["yes", "fix", "no"].includes(status(EX[j].id))) return j; } return Math.min(i + 1, EX.length - 1); };
  function go(i) { if (i < 0 || i >= EX.length) return; location.hash = EX[i].short; window.scrollTo({ top: 0 }); }
  function openLight(src) { $("lightbox-img").src = src; $("lightbox").hidden = false; $("lightbox-close").focus(); }
  $("lightbox-close").addEventListener("click", () => { $("lightbox").hidden = true; });
  $("lightbox").addEventListener("click", (ev) => { if (ev.target.id === "lightbox") $("lightbox").hidden = true; });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("lightbox").hidden = true; });
  $("reviewer").addEventListener("input", (ev) => { state.name = ev.target.value; changed(); });
  for (const [id, f] of [["f-all", "all"], ["f-todo", "todo"]]) $(id).addEventListener("click", () => {
    filter = f; $("f-all").setAttribute("aria-pressed", String(f === "all")); $("f-todo").setAttribute("aria-pressed", String(f === "todo")); renderList(); });
  $("copy").addEventListener("click", () => {
    const text = JSON.stringify(exportDoc(), null, 1);
    const box = $("copybox"); box.value = text;
    navigator.clipboard?.writeText(text).then(() => { $("copy-status").textContent = "Copied. Paste it into a message to send it."; },
      () => { box.hidden = false; box.select(); $("copy-status").textContent = "Select all and copy the text below."; })
      ?? (box.hidden = false, box.select());
  });
  const standalone = !window.claude;  // a normal website (e.g. Vercel), not a claude.ai artifact
  if (standalone) { $("download").hidden = false; $("send-hint").hidden = false; }
  $("download").addEventListener("click", () => {
    const text = JSON.stringify(exportDoc(), null, 1);
    const who = (state.name || "review").trim().replace(/[^A-Za-z0-9_-]+/g, "-").toLowerCase() || "review";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    a.download = `shot-review-${who}-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    $("copy-status").textContent = `Downloaded ${reviewedCount()} of ${EX.length} reviews. Send the file back.`;
  });
  window.addEventListener("hashchange", render);
  render();
  setSave("Saved in this browser", "");
  if (window.claude) connect();
})();
