#!/usr/bin/env python3
"""
Validate an interactive-code-map v3 HTML file before delivery.

Usage:
    python validate_code_map.py <path-to-html> [--source-root <repo-root>]

Checks are cumulative: malformed entries are reported instead of aborting the run,
so one bad card/group does not hide all the other problems.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

SECRET_PATTERNS = [
    ("OpenAI/DeepSeek style key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("Tavily API key", re.compile(r"tvly-[A-Za-z0-9_-]{12,}")),
    ("GitHub PAT", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("Private key header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

RAW_HTML_TAG_RE = re.compile(r"</?(?:code|div|span|br|p|ul|li|b|strong|em)\b[^>]*>", re.IGNORECASE)

SCRIPT_TAG_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)

REQUIRED_THEME_KEYS = ("fill", "stroke", "badgeBg", "badgeFg", "groupBg", "edge")
STAGE_TYPES = ("normal", "warn", "error")
KINDS = ("core", "summary")
REDACT_MARKER = "***REDACTED"
MAX_HTML_BYTES = 5 * 1024 * 1024
GROUP_TITLE_CLEARANCE = 44


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def has_positive_dims(obj: object) -> bool:
    return (
        isinstance(obj, dict)
        and all(is_number(obj.get(dim)) for dim in ("x", "y", "w", "h"))
        and obj["w"] > 0
        and obj["h"] > 0
    )


def boxes_overlap(a: dict, b: dict) -> bool:
    return (
        a["x"] < b["x"] + b["w"]
        and a["x"] + a["w"] > b["x"]
        and a["y"] < b["y"] + b["h"]
        and a["y"] + a["h"] > b["y"]
    )


def validate_ranges(ranges: object, fname: str, max_ln: int, owner_label: str, errors: list[str]) -> int:
    total = 0
    if not isinstance(ranges, list):
        errors.append(f"{owner_label} has non-list ranges: {ranges!r}")
        return 0
    for r in ranges:
        if not (
            isinstance(r, list)
            and len(r) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in r)
        ):
            errors.append(f"{owner_label} has invalid range entry: {r!r}")
            continue
        s, e = r
        if not (1 <= s <= e <= max_ln):
            errors.append(f"{owner_label} line range [{s}, {e}] out of bounds for '{fname}' (1..{max_ln}).")
        else:
            total += e - s + 1
    return total


def extract_app_data(html: str) -> str | None:
    """Find the <script id="app-data" type="application/json"> body, attribute order agnostic."""
    for attrs, body in SCRIPT_TAG_RE.findall(html):
        if re.search(r"\bid\s*=\s*[\"']?app-data[\"']?", attrs, re.IGNORECASE) and re.search(
            r"\btype\s*=\s*[\"']?application/json", attrs, re.IGNORECASE
        ):
            return body
    return None


def validate(html_path: pathlib.Path, source_root: pathlib.Path | None) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict = {}

    if not html_path.is_file():
        return [f"HTML file not found: {html_path}"], warnings, stats

    html = html_path.read_text(encoding="utf-8")

    # 0. Check unreplaced template placeholders
    for ph in ("__MAP_DATA__", "__PAGE_TITLE__"):
        if ph in html:
            errors.append(f"Unreplaced template placeholder found: {ph}")

    # 1. Secret leak scan across the entire HTML
    for label, pattern in SECRET_PATTERNS:
        m = pattern.search(html)
        if m:
            errors.append(f"Potential leaked secret ({label}) near offset {m.start()}: {m.group(0)[:10]}...")

    # 2. Extract and parse JSON payload
    raw_json = extract_app_data(html)
    if raw_json is None:
        errors.append('Missing <script id="app-data" type="application/json"> block.')
        return errors, warnings, stats
    # Backward compatibility: older generators escaped "</" as "<\/".
    raw_json = raw_json.replace("<\\/", "</")
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON in #app-data: {exc}")
        return errors, warnings, stats

    if not isinstance(data, dict):
        errors.append("'#app-data' must contain a JSON object.")
        return errors, warnings, stats

    required_keys = ("chains", "scenarios", "files", "sources", "themes", "groups", "cards", "edges")
    missing_keys = [key for key in required_keys if key not in data]
    for key in missing_keys:
        errors.append(f"Missing required key in #app-data: '{key}'")
    if missing_keys:
        return errors, warnings, stats

    # 3. Top-level shape guards (prevents confusing KeyError tracebacks)
    list_fields = ("chains", "scenarios", "files", "groups", "cards", "edges")
    dict_fields = ("sources", "themes")
    shape_ok = True
    for key in list_fields:
        if not isinstance(data[key], list):
            errors.append(f"'{key}' must be a JSON array.")
            shape_ok = False
    for key in dict_fields:
        if not isinstance(data[key], dict):
            errors.append(f"'{key}' must be a JSON object.")
            shape_ok = False
    if not shape_ok:
        return errors, warnings, stats

    chains = data["chains"]
    scenarios = data["scenarios"]
    files = data["files"]
    sources = data["sources"]
    themes = data["themes"]
    groups = data["groups"]
    cards = data["cards"]
    edges = data["edges"]

    # 4. Themes must be renderable (template reads these keys directly)
    if not themes:
        errors.append("'themes' must define at least one theme.")
    for tid, th in themes.items():
        if not isinstance(th, dict):
            errors.append(f"Theme '{tid}' must be a JSON object.")
            continue
        for key in REQUIRED_THEME_KEYS:
            value = th.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"Theme '{tid}' is missing non-empty string field '{key}'.")

    # 5. Chains
    chain_ids: set[str] = set()
    if not chains:
        errors.append("'chains' must contain at least one chain.")
    for idx, ch in enumerate(chains, start=1):
        if not isinstance(ch, dict):
            errors.append(f"Chain entry #{idx} must be a JSON object.")
            continue
        cid = ch.get("id")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"Chain entry #{idx} is missing a non-empty string 'id'.")
            continue
        if cid in chain_ids:
            errors.append(f"Duplicate chain id: '{cid}'")
            continue
        chain_ids.add(cid)
        if ch.get("tour") is not None and not isinstance(ch.get("tour"), list):
            errors.append(f"Chain '{cid}' has a non-list 'tour'.")

    # 6. Files & embedded sources
    file_keys: set[str] = set()
    for entry in files:
        if isinstance(entry, str):
            fkey, fpath = entry, None
        elif isinstance(entry, dict):
            fkey, fpath = entry.get("key"), entry.get("path")
        else:
            errors.append(f"Invalid entry in 'files': {entry!r}")
            continue

        if not isinstance(fkey, str) or not fkey:
            errors.append(f"Missing file key in 'files': {entry!r}")
            continue
        if fkey in file_keys:
            errors.append(f"Duplicate file key: '{fkey}'")
        file_keys.add(fkey)

        lines = sources.get(fkey)
        if not isinstance(lines, list) or not lines:
            errors.append(f"Source lines missing or empty for file '{fkey}'.")
            continue
        non_str = next((i for i, ln in enumerate(lines, start=1) if not isinstance(ln, str)), None)
        if non_str is not None:
            errors.append(f"Source '{fkey}' line {non_str} is not a string; every source line must be a JSON string.")
            continue

        if source_root is None:
            continue
        if not fpath:
            warnings.append(f"File '{fkey}' has no 'path'; skipped disk line/content verification.")
            continue
        if not isinstance(fpath, str):
            errors.append(f"File '{fkey}' has a non-string 'path'.")
            continue

        disk_file = (source_root / fpath).resolve()
        if not disk_file.is_file():
            warnings.append(f"Disk source not found for line-count check: {disk_file}")
            continue
        try:
            disk_lines = disk_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"Could not read disk source for '{fkey}' ({exc}); skipped line/content check.")
            continue

        if len(lines) != len(disk_lines):
            errors.append(
                f"Line count mismatch for '{fkey}': embedded {len(lines)} vs disk {len(disk_lines)} ({disk_file})"
            )
            continue

        # Content drift: catch wrong file/stale revision even when line counts happen to match.
        for ln_no, (embedded, on_disk) in enumerate(zip(lines, disk_lines), start=1):
            if REDACT_MARKER in embedded:
                continue
            if embedded != on_disk:
                errors.append(
                    f"Source drift for '{fkey}' at line {ln_no}: "
                    f"embedded {embedded[:80]!r} vs disk {on_disk[:80]!r}"
                )
                break

    for key in sources:
        if key not in file_keys:
            warnings.append(f"Source '{key}' is not listed in 'files'; it will not appear as a drawer tab.")

    # 7. Groups (validate dimensions before any geometry math)
    group_map: dict[str, dict] = {}
    for idx, g in enumerate(groups, start=1):
        if not isinstance(g, dict):
            errors.append(f"Group entry #{idx} must be a JSON object.")
            continue
        gid = g.get("id")
        if not isinstance(gid, str) or not gid:
            errors.append(f"Group entry #{idx} is missing a non-empty string 'id'.")
            continue
        if gid in group_map:
            errors.append(f"Duplicate group id: '{gid}'")
        group_map[gid] = g

        if not isinstance(g.get("chainId"), str) or g["chainId"] not in chain_ids:
            errors.append(f"Group '{gid}' references unknown chainId '{g.get('chainId')}'.")
        if not isinstance(g.get("theme"), str) or g["theme"] not in themes:
            errors.append(f"Group '{gid}' references unknown theme '{g.get('theme')}'.")

        if has_positive_dims(g):
            pass
        elif all(is_number(g.get(dim)) for dim in ("x", "y", "w", "h")):
            errors.append(f"Group '{gid}' must have positive width/height.")
        else:
            errors.append(f"Group '{gid}' is missing numeric x/y/w/h.")

    group_overlaps = []
    drawable_groups = [g for g in groups if has_positive_dims(g)]
    for i in range(len(drawable_groups)):
        for j in range(i + 1, len(drawable_groups)):
            if boxes_overlap(drawable_groups[i], drawable_groups[j]):
                group_overlaps.append((drawable_groups[i].get("id"), drawable_groups[j].get("id")))
    if group_overlaps:
        sample = ", ".join(f"{x}<->{y}" for x, y in group_overlaps[:6])
        errors.append(f"Detected {len(group_overlaps)} overlapping group pair(s): {sample}")

    # 8. Cards
    card_map: dict[str, dict] = {}
    for c in cards:
        if not isinstance(c, dict):
            errors.append(f"Card entry must be a JSON object: {c!r}")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"Card missing non-empty string 'id': {c!r}")
            continue
        if cid in card_map:
            errors.append(f"Duplicate card id: '{cid}'")
        card_map[cid] = c

        if not isinstance(c.get("chainId"), str) or c["chainId"] not in chain_ids:
            errors.append(f"Card '{cid}' references unknown chainId '{c.get('chainId')}'.")
        if not isinstance(c.get("theme"), str) or c["theme"] not in themes:
            errors.append(f"Card '{cid}' references unknown theme '{c.get('theme')}'.")

        dims_ok = all(is_number(c.get(dim)) for dim in ("x", "y", "w", "h"))
        if not dims_ok:
            errors.append(f"Card '{cid}' missing numeric x/y/w/h.")
        elif c["w"] <= 0 or c["h"] <= 0:
            errors.append(f"Card '{cid}' must have positive width/height.")
            dims_ok = False

        gid = c.get("groupId")
        if gid is not None:
            grp = group_map.get(gid) if isinstance(gid, str) else None
            if not grp:
                errors.append(f"Card '{cid}' references unknown groupId '{gid}'.")
            else:
                if grp.get("chainId") != c.get("chainId"):
                    errors.append(
                        f"Card '{cid}' chainId '{c.get('chainId')}' does not match "
                        f"its group '{gid}' chainId '{grp.get('chainId')}'."
                    )
                if dims_ok and has_positive_dims(grp):
                    if (
                        c["x"] < grp["x"]
                        or c["y"] < grp["y"] + GROUP_TITLE_CLEARANCE
                        or c["x"] + c["w"] > grp["x"] + grp["w"]
                        or c["y"] + c["h"] > grp["y"] + grp["h"]
                    ):
                        errors.append(
                            f"Card '{cid}' overflows its group '{gid}' bounds "
                            f"(keep >={GROUP_TITLE_CLEARANCE}px top clearance for the group title)."
                        )

        for field_name in ("note", "interview"):
            val = c.get(field_name)
            if val is None:
                continue
            if not isinstance(val, str):
                errors.append(f"Card '{cid}.{field_name}' must be a string.")
            elif RAW_HTML_TAG_RE.search(val):
                warnings.append(f"Card '{cid}.{field_name}' contains raw HTML tags; use plain text + `backticks`.")

        kind = c.get("kind", "core")
        if kind not in KINDS:
            errors.append(f"Card '{cid}' has invalid kind '{kind}' (expected 'core' or 'summary').")
        elif kind == "core":
            fname = c.get("file")
            if not isinstance(fname, str) or not fname or fname not in sources:
                errors.append(f"Core card '{cid}' references unknown source file '{fname}'.")
            else:
                source_lines = sources[fname]
                if not isinstance(source_lines, list) or not all(isinstance(ln, str) for ln in source_lines):
                    errors.append(f"Core card '{cid}' references source '{fname}' whose embedded lines are invalid.")
                else:
                    if fname not in file_keys:
                        errors.append(f"Core card '{cid}' uses '{fname}', but that file is not listed in 'files' (drawer tab missing).")
                    ranges = c.get("ranges") or []
                    if not ranges:
                        errors.append(f"Core card '{cid}' must define non-empty line 'ranges'.")
                    else:
                        hl_count = validate_ranges(ranges, fname, len(source_lines), f"Core card '{cid}'", errors)
                        if hl_count > 70:
                            errors.append(
                                f"Core card '{cid}' highlights {hl_count} lines (>70); split it into finer 10-45 line cards."
                            )
                        elif hl_count > 45:
                            warnings.append(
                                f"Core card '{cid}' highlights {hl_count} lines (>45); consider splitting into finer cards (10-45 lines each)."
                            )
            if not isinstance(c.get("interview"), str) or not c.get("interview", "").strip():
                warnings.append(f"Core card '{cid}' is missing 'interview' Q&A.")
        else:
            if c.get("ranges"):
                warnings.append(f"Summary card '{cid}' has non-empty 'ranges'; summary cards should use ranges: [].")

    card_overlaps = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            if isinstance(a, dict) and isinstance(b, dict) and has_positive_dims(a) and has_positive_dims(b) and boxes_overlap(a, b):
                card_overlaps.append((a.get("id"), b.get("id")))
    if card_overlaps:
        sample = ", ".join(f"{x}<->{y}" for x, y in card_overlaps[:8])
        errors.append(f"Detected {len(card_overlaps)} overlapping card pair(s): {sample}")

    # Overlapping highlight ranges: line-to-card reverse lookup would only find the first card.
    per_file: dict[str, list[tuple[int, int, str]]] = {}
    for c in cards:
        if not isinstance(c, dict) or c.get("kind") != "core":
            continue
        fname = c.get("file")
        if not isinstance(fname, str) or not fname:
            continue
        for r in c.get("ranges") or []:
            if isinstance(r, list) and len(r) == 2 and all(is_number(n) for n in r):
                per_file.setdefault(fname, []).append((r[0], r[1], c.get("id")))
    for fname, spans in per_file.items():
        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                s1, e1, id1 = spans[i]
                s2, e2, id2 = spans[j]
                if id1 != id2 and max(s1, s2) <= min(e1, e2):
                    warnings.append(
                        f"Cards '{id1}' and '{id2}' highlight overlapping lines in '{fname}'; "
                        f"line-click reverse lookup will only reach one of them."
                    )

    # 9. Edges & cross-chain presence
    cross_count = 0
    for e in edges:
        if not isinstance(e, dict):
            errors.append(f"Edge entry must be a JSON object: {e!r}")
            continue
        edge_chain = e.get("chainId")
        if edge_chain is not None and (not isinstance(edge_chain, str) or edge_chain not in chain_ids):
            errors.append(f"Edge {e.get('from')} -> {e.get('to')} references unknown chainId '{edge_chain}'.")
        frm, to = e.get("from"), e.get("to")
        if not isinstance(frm, str) or not isinstance(to, str) or frm not in card_map or to not in card_map:
            errors.append(f"Edge {frm} -> {to} references missing card id.")
            continue
        if e.get("crossChain"):
            cross_count += 1
            a, b = card_map[e["from"]], card_map[e["to"]]
            if a.get("chainId") == b.get("chainId"):
                warnings.append(
                    f"Edge {e.get('from')} -> {e.get('to')} is marked crossChain=true, "
                    f"but both cards belong to chain '{a.get('chainId')}'."
                )
    if len(chains) >= 2 and cross_count == 0:
        warnings.append("Multi-chain map has 0 crossChain=true edges; check if shared components should be linked.")

    # 10. Tours & scenarios
    for ch in chains:
        if not isinstance(ch, dict):
            continue
        tour = ch.get("tour") or []
        if not isinstance(tour, list):
            continue
        for tid in tour:
            if not isinstance(tid, str) or tid not in card_map:
                errors.append(f"Chain '{ch.get('id')}' tour references unknown card id '{tid}'.")

    if len(scenarios) < 2:
        warnings.append(f"Only {len(scenarios)} scenario(s) defined; recommend >=2 (including 1 normal + 1 error/fallback).")

    has_edge_stage = False
    scenario_ids: set[str] = set()
    for sc in scenarios:
        if not isinstance(sc, dict):
            errors.append(f"Scenario entry must be a JSON object: {sc!r}")
            continue
        sc_id = sc.get("id") or "<unnamed>"
        if not isinstance(sc_id, str):
            sc_id = "<unnamed>"
        if isinstance(sc.get("id"), str) and sc["id"]:
            if sc_id in scenario_ids:
                errors.append(f"Duplicate scenario id: '{sc_id}'")
            scenario_ids.add(sc_id)

        badge_type = sc.get("badgeType")
        if badge_type is not None and badge_type not in STAGE_TYPES:
            errors.append(f"Scenario '{sc_id}' has invalid badgeType '{badge_type}' (expected normal/warn/error).")

        steps = sc.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"Scenario '{sc_id}' must contain at least one step.")
            continue
        for idx, st in enumerate(steps, start=1):
            if not isinstance(st, dict):
                errors.append(f"Scenario '{sc_id}' step #{idx} must be a JSON object.")
                continue
            cid = st.get("cardId")
            if not isinstance(cid, str) or cid not in card_map:
                errors.append(f"Scenario '{sc_id}' step #{idx} references unknown cardId '{cid}'.")
                continue
            st_type = st.get("stageType", "normal")
            if st_type not in STAGE_TYPES:
                errors.append(f"Scenario '{sc_id}' step #{idx} has invalid stageType '{st_type}'.")
            elif st_type in ("warn", "error"):
                has_edge_stage = True

            for req in ("situation", "resolution"):
                txt = st.get(req)
                if not isinstance(txt, str) or not txt.strip():
                    errors.append(f"Scenario '{sc_id}' step #{idx} missing or non-string '{req}'.")
                elif RAW_HTML_TAG_RE.search(txt):
                    warnings.append(f"Scenario '{sc_id}' step #{idx}.{req} contains raw HTML tags; use `backticks`.")

            fr = st.get("focusRanges")
            if fr:
                card = card_map[cid]
                if card.get("kind") != "core":
                    errors.append(f"Scenario '{sc_id}' step #{idx} defines focusRanges on non-core card '{cid}'.")
                else:
                    fname = card.get("file")
                    lines = sources.get(fname) if isinstance(fname, str) else None
                    if not isinstance(lines, list):
                        errors.append(
                            f"Scenario '{sc_id}' step #{idx} cannot validate focusRanges: "
                            f"card '{cid}' has no embedded source."
                        )
                    else:
                        fr_count = validate_ranges(fr, fname, len(lines), f"Scenario '{sc_id}' step #{idx}", errors)
                        if 0 < fr_count < 5 or fr_count > 25:
                            warnings.append(
                                f"Scenario '{sc_id}' step #{idx} focusRanges cover {fr_count} lines; recommended 5-25."
                            )
    if scenarios and not has_edge_stage:
        warnings.append("Scenarios have no 'warn' or 'error' stage; add at least one edge/fallback/cancel scenario.")

    # 11. Syntax-check inline JS with node --check
    js_blocks = []
    for attrs, body in SCRIPT_TAG_RE.findall(html):
        if re.search(r"\btype\s*=\s*[\"']?application/json", attrs, re.IGNORECASE):
            continue
        if re.search(r"\bsrc\s*=", attrs, re.IGNORECASE):
            continue
        js_blocks.append(body)

    if not js_blocks:
        errors.append("No inline executable <script> found.")
    else:
        node_bin = shutil.which("node")
        if not node_bin:
            warnings.append("Node.js not found on PATH; skipped `node --check` JS syntax verification.")
        else:
            for idx, js_code in enumerate(js_blocks, start=1):
                with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as tf:
                    tf.write(js_code)
                    tmp_js = pathlib.Path(tf.name)
                try:
                    proc = subprocess.run([node_bin, "--check", str(tmp_js)], capture_output=True, text=True)
                    if proc.returncode != 0:
                        errors.append(f"JS syntax error in inline script #{idx}: {proc.stderr.strip()}")
                finally:
                    tmp_js.unlink(missing_ok=True)

    total_bytes = len(html.encode("utf-8"))
    if total_bytes > MAX_HTML_BYTES:
        warnings.append(
            f"HTML is {total_bytes / (1024 * 1024):.1f} MB (>5 MB); consider trimming embedded files or splitting the map."
        )

    stats = {
        "chains": len(chains),
        "scenarios": len(scenarios),
        "files": len(files),
        "core_cards": sum(1 for c in cards if isinstance(c, dict) and c.get("kind", "core") == "core"),
        "summary_cards": sum(1 for c in cards if isinstance(c, dict) and c.get("kind") == "summary"),
        "edges": len(edges),
        "cross_edges": cross_count,
        "bytes": total_bytes,
    }
    return errors, warnings, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an interactive-code-map v3 HTML file.")
    parser.add_argument("html", type=pathlib.Path, help="Path to generated HTML file")
    parser.add_argument("--source-root", type=pathlib.Path, default=None, help="Optional repo root for 1:1 line/content checks")
    args = parser.parse_args()

    errors, warnings, stats = validate(args.html, args.source_root)
    for w in warnings:
        print(f"[WARN] {w}")
    if errors:
        print("[FAIL] Validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(
        "[OK] Passed: "
        f"{stats.get('chains', 0)} chains, "
        f"{stats.get('scenarios', 0)} scenarios, "
        f"{stats.get('files', 0)} files, "
        f"{stats.get('core_cards', 0)} core + {stats.get('summary_cards', 0)} summary cards (0 overlaps), "
        f"{stats.get('edges', 0)} edges ({stats.get('cross_edges', 0)} cross-chain), "
        f"{stats.get('bytes', 0)} bytes, 0 secret leaks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
