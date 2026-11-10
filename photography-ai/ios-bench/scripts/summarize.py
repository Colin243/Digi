"""Turn the JSON files the phone app writes into the tables in docs/iphone-benchmark.md.

    python3 ios-bench/scripts/summarize.py ~/Downloads/bench-*.json

Standard library only. Prints markdown; paste the rows into the doc's results tables.
Budgets are checked against docs/iphone-benchmark.md section 4 (BUDGETS below).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

GB = 1024**3
# Keep in sync with docs/iphone-benchmark.md, section 4.
BUDGETS = {
    "on_site_e2e_s": 30.0,
    "decomposed_warm_e2e_s": 60.0,
    "decomposed_max_e2e_s": 90.0,
    "first_call_ttft_s": 3.0,
    "cold_load_s": 8.0,
    "peak_footprint_gb": 4.0,
    "min_available_gb": 1.0,
    "camera_recovery_s": 0.5,
}


BUDGET_ROWS: list[tuple[str, bool | None]] = []  # (check, True pass / False fail / None no data); reset per file


def camera_checks(r: dict) -> list[tuple[str, bool | None]]:
    """Camera pause/resume passes only if EVERY trial's restart delivered a frame within budget.

    The app's per-workload summary takes the max over recovered trials only, so a timeout (no first frame) was
    invisible and one good restart could turn the check green. Here any timeout, camera error, unavailable camera
    or missing sample fails, and a run with camera checks on but no samples is "no data", never a pass.
    """
    budget = BUDGETS["camera_recovery_s"]
    if not (r.get("config") or {}).get("camera_pause_resume", True):
        return []
    groups: dict[tuple[str, int], list] = {}
    for t in r.get("trials", []):
        groups.setdefault((t["workload"], t["size"]), []).append(t.get("camera"))
    if not groups:
        return [("camera pause/resume: trials recorded", None)]
    out = []
    for (wl, size), cams in sorted(groups.items()):
        n = len(cams)
        missing = sum(c is None for c in cams)
        errored = sum(1 for c in cams if c is not None and (c.get("error") or c.get("available") is False))
        timed_out = sum(1 for c in cams if c is not None and not (c.get("error") or c.get("available") is False)
                        and (c.get("recovered") is not True or c.get("first_frame_seconds") is None))
        ok = [c for c in cams if c is not None and not (c.get("error") or c.get("available") is False)
              and c.get("recovered") is True and c.get("first_frame_seconds") is not None]
        slow = sum(c["first_frame_seconds"] > budget for c in ok)
        within = len(ok) - slow
        name = (f"{wl}@{size} camera recovered within {budget} s on every trial "
                f"({within} ok / {slow} slow / {timed_out} timed out / {errored} errored / {missing} missing, of {n})")
        out.append((name, within == n if n else None))
    return out


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def f(x, fmt="{:.2f}"):
    return "" if x is None else fmt.format(x)


def gb(b):
    return "" if b is None else f"{b / GB:.2f}"


def overall(checks: list[tuple[str, bool | None]]) -> str:
    """FAIL if anything failed; NO DATA if nothing failed but something is missing (or there are no checks)."""
    if any(ok is False for _, ok in checks):
        return "FAIL"
    return "PASS" if checks and all(ok is True for _, ok in checks) else "NO DATA"


def main(paths: list[str]) -> None:
    if not paths:
        sys.exit(__doc__)
    for p in paths:
        BUDGET_ROWS.clear()
        r = json.loads(Path(p).read_text())
        BUDGET_ROWS = []
        d, rt, m, c = r["device"], r["runtime"], r.get("model") or {}, r["config"]
        print(f"## {r['id']} ({r['status']}{': ' + r['abort_reason'] if r.get('abort_reason') else ''})\n")
        print(f"- Device: {d.get('model_name') or d['machine']} ({d['machine']}), {d['system_name']} {d['system_version']} "
              f"({d.get('os_build')}), {d['physical_memory'] / GB:.1f} GB RAM, GPU {d.get('gpu_architecture')}, "
              f"build {d['build_configuration']}")
        print(f"- At start: available to app {gb(d['available_memory_at_start'])} GB, thermal {d['thermal_state_at_start']}, "
              f"low power {d['low_power_mode']}, battery {d.get('battery_level')} {d['battery_state']}, "
              f"uptime {d['system_uptime_at_start'] / 60:.0f} min, network {d['network_at_start']['status']}")
        print(f"- Runtime: mlx-swift-lm {rt['packages'].get('mlx-swift-lm')}, mlx-swift {rt['packages'].get('mlx-swift')}, "
              f"swift-transformers {rt['packages'].get('swift-transformers')}, MLX cache limit {rt['mlx_cache_limit'] / 2**20:.0f} MB, "
              f"prompt v{rt['prompt_version']}")
        print(f"- Model: {m.get('repo_id')} @ {str(m.get('revision'))[:12]} ({m.get('location')}, {gb(m.get('weights_bytes'))} GB)")
        print(f"- Config: preset {c['preset']}, repeats {c['repeats']}, sizes {c['sizes']}, camera pause/resume "
              f"{c['camera_pause_resume']}, cooldown {c['cooldown_seconds']} s\n")

        for name in ("load", "reload"):
            ld = r.get(name)
            if ld:
                print(f"- {name}: ok={ld['ok']} {f(ld.get('seconds'))} s, footprint {gb(ld['footprint_before'])} -> "
                      f"{gb(ld['footprint_after'])} GB (peak {gb(ld['peak_footprint'])}), available after {gb(ld['available_after'])} GB"
                      + (f", error {ld['error']}" if ld.get("error") else ""))
        print()

        print("| workload | px | n | first run (s) | warm median (s) | warm max (s) | TTFT median (s) | gen tok/s | prompt tok/s "
              "| peak footprint (GB) | min available (GB) | camera recovery median / max (s) | JSON valid |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in r.get("summary", []):
            print(f"| {s['workload']} | {s['size']} | {s['n']} | {f(s.get('first_e2e'), '{:.1f}')} | "
                  f"{f(s.get('warm_e2e_median'), '{:.1f}')} | {f(s.get('warm_e2e_max'), '{:.1f}')} | {f(s.get('ttft_median'))} | "
                  f"{f(s.get('gen_tok_per_sec_median'), '{:.1f}')} | {f(s.get('prompt_tok_per_sec_median'), '{:.0f}')} | "
                  f"{gb(s['peak_footprint_max'])} | {gb(s['min_available_min'])} | "
                  f"{f(s.get('camera_recovery_median'))} / {f(s.get('camera_recovery_max'))} | {s['json_valid']} |")
        print()

        # Decomposed split: what can be prepared before arriving vs what the user waits for on site.
        dec_trials = [t for t in r["trials"] if t["workload"] == "decomposed" and not t["first_after_load"] and not t.get("error")]
        if dec_trials:
            print("| px | n | inspiration prep: notes + aesthetic, median (s) | on site: target + compositions, median / max (s) |")
            print("|---|---|---|---|")
            for size in sorted({t["size"] for t in dec_trials}):
                ts = [t for t in dec_trials if t["size"] == size]
                prep = [sum(c["e2e_seconds"] for c in t["calls"] if c["stage"].startswith("notes_") or c["stage"] == "aesthetic_from_notes") for t in ts]
                site = [sum(c["e2e_seconds"] for c in t["calls"] if c["stage"] in ("target_scene", "compositions")) for t in ts]
                print(f"| {size} | {len(ts)} | {f(med(prep), '{:.1f}')} | {f(med(site), '{:.1f}')} / {f(max(site), '{:.1f}')} |")
                if med(site) is not None:
                    BUDGET_ROWS.append((f"decomposed@{size} on-site median <= {BUDGETS['on_site_e2e_s']} s",
                                        med(site) <= BUDGETS["on_site_e2e_s"]))
            print()

        # Per-trial drift: thermal behaviour over the run.
        print("| # | workload | px | inference (s) | gen tok/s (median of calls) | thermal start -> end | peak (GB) | camera back (s) |")
        print("|---|---|---|---|---|---|---|---|")
        for t in r["trials"]:
            tps = med([cl["generation_tokens_per_second"] for cl in t["calls"] if cl["generated_tokens"] >= 16])
            cam = (t.get("camera") or {}).get("first_frame_seconds")
            print(f"| {t['index'] + 1}{'*' if t['first_after_load'] else ''} | {t['workload']} | {t['size']} | "
                  f"{t['inference_seconds']:.1f} | {f(tps, '{:.1f}')} | {t['thermal_start']} -> {t['thermal_end']} | "
                  f"{gb(t['peak_footprint'])} | {f(cam)} |" + (f" error: {t['error']}" if t.get("error") else ""))
        print("\n`*` = first inference after load.\n")

        ev = [e for e in r.get("events", []) if e["kind"] != "scene_phase"]
        if ev:
            print("Events: " + "; ".join(f"{e['seconds_since_start']:.0f}s {e['kind']} {e['detail']}" for e in ev) + "\n")

        # Budget check.
        checks = list(BUDGET_ROWS)
        dec = [s for s in r.get("summary", []) if s["workload"] == "decomposed"]
        for s in dec:
            if s.get("warm_e2e_median") is not None:
                checks.append((f"decomposed@{s['size']} warm median <= {BUDGETS['decomposed_warm_e2e_s']} s",
                               s["warm_e2e_median"] <= BUDGETS["decomposed_warm_e2e_s"]))
            if s.get("warm_e2e_max") is not None:
                checks.append((f"decomposed@{s['size']} warm max <= {BUDGETS['decomposed_max_e2e_s']} s",
                               s["warm_e2e_max"] <= BUDGETS["decomposed_max_e2e_s"]))
        for s in r.get("summary", []):
            if s.get("ttft_median") is not None:
                checks.append((f"{s['workload']}@{s['size']} TTFT median <= {BUDGETS['first_call_ttft_s']} s",
                               s["ttft_median"] <= BUDGETS["first_call_ttft_s"]))
            checks.append((f"{s['workload']}@{s['size']} peak footprint <= {BUDGETS['peak_footprint_gb']} GB",
                           s["peak_footprint_max"] / GB <= BUDGETS["peak_footprint_gb"]))
            checks.append((f"{s['workload']}@{s['size']} min available >= {BUDGETS['min_available_gb']} GB",
                           s["min_available_min"] / GB >= BUDGETS["min_available_gb"]))
        checks += camera_checks(r)
        for (wl, size) in sorted({(t["workload"], t["size"]) for t in r.get("trials", [])}):
            ts = [t for t in r["trials"] if (t["workload"], t["size"]) == (wl, size)]
            bad = sum(bool(t.get("error")) for t in ts)
            checks.append((f"{wl}@{size} every trial finished without error ({len(ts) - bad}/{len(ts)})", bad == 0))
        if not r.get("trials"):
            checks.append(("trials recorded", None))
        if r.get("load", {}).get("seconds") is not None:
            checks.append((f"cold load <= {BUDGETS['cold_load_s']} s", r["load"]["seconds"] <= BUDGETS["cold_load_s"]))
        if checks:
            print("Budget check:")
            for name, ok in checks:
                print(f"- [{'x' if ok else ' '}] {'PASS' if ok else 'NO DATA' if ok is None else 'FAIL'}: {name}")
            print(f"\n**Overall: {overall(checks)}**")
            print()


if __name__ == "__main__":
    main(sys.argv[1:])
