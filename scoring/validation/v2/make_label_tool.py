#!/usr/bin/env python3
"""Build validation/v2/label_tool.html: a single self-contained local labelling page for the 40 v2 items. Python 3.9.

  make_label_tool.py [--out PATH]

Reads only validation/v2/items.jsonl, ../../registry.jsonl and validation/families.md. Nothing from
validation/v2/construction/ is read, embedded or referenced. The page has no network use (no external scripts,
fonts or images) and works from file://. Prints counts only, never item text."""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCORING = os.path.dirname(os.path.dirname(HERE))
ITEMS = os.path.join(HERE, "items.jsonl")
REGISTRY = os.path.join(SCORING, "registry.jsonl")
FAMILIES_MD = os.path.join(SCORING, "validation", "families.md")
OUT = os.path.join(HERE, "label_tool.html")

SHORT = 420
FIELD = re.compile(r"^(Core statement|Does not count|Note|Sub-attributes|Instance attribution|Decisions recorded)\b")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def shorten(s, n=SHORT):
    s = " ".join(s.split())
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + " …"


def parse_families(md):
    """[{id, rows, core, notcount, note}] in file order, from the '## <fam> (...) Rows: ...' sections."""
    fams, cur, field = [], None, None
    for line in md.splitlines():
        m = re.match(r"^## ([ABCP][12]) .*?Rows?: (.*)$", line)
        if m:
            cur = {"id": m.group(1), "rows": re.findall(r"[ABCP][12]-[A-Z]-\d+", m.group(2)),
                   "core": "", "notcount": "", "note": ""}
            fams.append(cur)
            field = None
            continue
        if line.startswith("## "):
            cur, field = None, None
            continue
        if cur is None:
            continue
        if not line.strip():
            field = None
            continue
        f = FIELD.match(line)
        if f:
            key = {"Core statement": "core", "Does not count": "notcount", "Note": "note"}.get(f.group(1))
            field = key
            if key:
                cur[key] = (cur[key] + " " + line.split(":", 1)[1].strip()).strip() if ":" in line else cur[key]
        elif field:
            cur[field] = (cur[field] + " " + line.strip()).strip()
    return fams


def build_units(registry, fams):
    in_family = {r for f in fams for r in f["rows"]}
    units = []
    for f in fams:
        ref = "Core: " + shorten(f["core"])
        if f["notcount"]:
            ref += "\n\nDoes not count: " + shorten(f["notcount"])
        if f["note"]:
            ref += "\n\nNote: " + shorten(f["note"])
        units.append({"id": f["id"], "kind": "family", "rows": f["rows"], "ref": ref})
    for r in registry:
        if r["id"] not in in_family:
            units.append({"id": r["id"], "kind": "row", "rows": [r["id"]], "ref": r["text"]})
    return units


def build(items, registry, fams_md):
    fams = parse_families(fams_md)
    reg_ids = {r["id"] for r in registry}
    problems = []
    if sorted(f["id"] for f in fams) != ["A1", "A2", "P1", "P2"]:
        problems.append("expected the four families A1, A2, P1, P2 in families.md, found %s" % [f["id"] for f in fams])
    for f in fams:
        if not f["core"] or not f["rows"] or not set(f["rows"]) <= reg_ids:
            problems.append("family %s: missing core statement or rows not in the registry" % f["id"])
    units = build_units(registry, fams)
    # families first in A1, A2, P1, P2 order, then singles in registry order
    order = {"A1": 0, "A2": 1, "P1": 2, "P2": 3}
    units.sort(key=lambda u: (u["kind"] != "family", order.get(u["id"], 0)))
    if len(units) != 24:
        problems.append("expected 24 units, built %d" % len(units))
    ids = [i["id"] for i in items]
    if not items or len(set(ids)) != len(ids) or any(set(i) != {"id", "text"} for i in items):
        problems.append("items.jsonl must hold unique {id, text} rows and nothing else")
    if problems:
        raise SystemExit("\n".join(problems))
    return units


def embed(obj):
    s = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(items, units, items_sha):
    return (TEMPLATE.replace("/*ITEMS*/", embed(items)).replace("/*UNITS*/", embed(units))
            .replace("/*KEY*/", items_sha[:12]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    items = read_jsonl(ITEMS)
    registry = read_jsonl(REGISTRY)
    with open(FAMILIES_MD, encoding="utf-8") as f:
        fams_md = f.read()
    units = build(items, registry, fams_md)
    with open(ITEMS, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    html = render(items, units, sha)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    sys.stdout.write("%s: %d items, %d units (%d families, %d single rows), %d bytes\n" % (
        a.out, len(items), len(units), sum(u["kind"] == "family" for u in units),
        sum(u["kind"] == "row" for u in units), len(html.encode("utf-8"))))


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Validation v2 labelling</title>
<style>
:root { --bg:#f6f5f2; --panel:#fff; --ink:#1d1d1b; --muted:#6b6a64; --line:#d9d6cd; --accent:#1f5f8b;
        --done:#2e7d4f; --todo:#b3402a; --hl:#e8f1f8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --panel:#202020; --ink:#ecebe6; --muted:#9a988f; --line:#3a3936; --accent:#6fb0dc;
          --done:#5fbf86; --todo:#e07a62; --hl:#1d2e3a; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; }
header { position:sticky; top:0; z-index:5; background:var(--panel); border-bottom:1px solid var(--line); padding:8px 16px; }
.row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
header h1 { font-size:15px; margin:0 12px 0 0; }
button { font:inherit; padding:5px 12px; border:1px solid var(--line); background:var(--panel); color:var(--ink);
         border-radius:6px; cursor:pointer; }
button:hover { border-color:var(--accent); }
button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
#progress { font-weight:600; }
#saved { color:var(--muted); font-size:13px; }
#saved.bad { color:var(--todo); }
#index { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
#index button { padding:2px 7px; font-size:12px; min-width:42px; border-color:var(--todo); color:var(--todo); }
#index button.done { border-color:var(--done); color:var(--done); }
#index button.cur { outline:2px solid var(--accent); outline-offset:1px; }
main { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1fr); gap:14px; padding:14px 16px; }
@media (max-width: 900px) { main { grid-template-columns:1fr; } }
section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
section h2 { font-size:14px; margin:0 0 8px; color:var(--muted); font-weight:600; }
#text { white-space:pre-wrap; overflow-wrap:anywhere; font-size:15px; }
.unit { border-top:1px solid var(--line); padding:5px 0; }
.unit:first-of-type { border-top:0; }
.unit.ticked { background:var(--hl); margin:0 -6px; padding:5px 6px; border-radius:5px; }
.unit label { display:inline-flex; gap:7px; align-items:center; cursor:pointer; font-weight:600; min-width:150px; }
.unit .fam { font-weight:400; color:var(--muted); font-size:12px; }
.unit select { font:inherit; font-size:13px; padding:2px 4px; }
.unit select:disabled { opacity:.35; }
.unit .rtog { border:0; background:none; color:var(--accent); font-size:12px; padding:0 4px; text-decoration:underline; }
.ref { display:none; white-space:pre-wrap; font-size:13px; color:var(--muted); margin:4px 0 2px 26px; overflow-wrap:anywhere; }
.ref.open { display:block; }
h3 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:12px 0 2px; }
textarea { width:100%; min-height:70px; font:inherit; padding:6px; border:1px solid var(--line); border-radius:6px;
           background:var(--bg); color:var(--ink); }
#status { margin-top:10px; font-weight:600; }
#status.done { color:var(--done); } #status.todo { color:var(--todo); }
#msg { margin-top:8px; font-size:13px; white-space:pre-wrap; color:var(--todo); }
.help { font-size:12px; color:var(--muted); }
</style>
</head>
<body>
<header>
  <div class="row">
    <h1>Validation v2 labelling</h1>
    <button id="prev">&larr; Previous</button>
    <button id="next">Next &rarr;</button>
    <span id="progress"></span>
    <span id="saved"></span>
    <span style="flex:1"></span>
    <button id="allref">Show all references</button>
    <button id="partial" title="Backup only; not accepted by the comparison">Export partial (backup, not final)</button>
    <button id="export" class="primary">Export CSV</button>
  </div>
  <div id="index"></div>
</header>
<main>
  <section><h2 id="itemhead"></h2><div id="text"></div></section>
  <section>
    <h2>Which units are present in this text?</h2>
    <div class="row" style="margin-bottom:6px">
      <button id="none">None present</button>
      <span class="help">Tick every unit stated in the text, or press None present. Strength is secondary.</span>
    </div>
    <div id="units"></div>
    <h3>Note</h3>
    <textarea id="note" placeholder="Optional note for this item"></textarea>
    <div id="status"></div>
    <div id="msg"></div>
  </section>
</main>
<script id="items-data" type="application/json">/*ITEMS*/</script>
<script id="units-data" type="application/json">/*UNITS*/</script>
<script>
(function () {
  "use strict";
  var ITEMS = JSON.parse(document.getElementById("items-data").textContent);
  var UNITS = JSON.parse(document.getElementById("units-data").textContent);
  var KEY = "label_tool_v2_20261028_/*KEY*/";
  var STRENGTHS = ["verbatim", "paraphrase", "pattern", "unsure"];
  var state = { cur: 0, items: {} };
  var storageOK = true;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  function entry(id) {
    if (!state.items[id]) state.items[id] = { units: {}, none: false, note: "" };
    return state.items[id];
  }
  function isDone(id) {
    var e = state.items[id];
    return !!e && (e.none || Object.keys(e.units).length > 0);
  }

  function load() {
    try {
      var raw = window.localStorage.getItem(KEY);
      if (raw) {
        var s = JSON.parse(raw);
        if (s && s.items) { state.items = s.items; state.cur = Math.min(Math.max(+s.cur || 0, 0), ITEMS.length - 1); }
      }
    } catch (err) { storageOK = false; }
  }
  function save() {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
      if (storageOK) { $("saved").textContent = "autosaved"; $("saved").className = ""; }
    } catch (err) {
      storageOK = false;
      $("saved").textContent = "AUTOSAVE UNAVAILABLE: export a partial CSV before closing";
      $("saved").className = "bad";
    }
  }

  var refOpen = {}, allRefs = false;

  function buildUnits() {
    var box = $("units");
    box.textContent = "";
    UNITS.forEach(function (u) {
      var wrap = el("div", "unit"); wrap.id = "u-" + u.id;
      var r = el("div", "row");
      var lab = el("label");
      var cb = el("input"); cb.type = "checkbox"; cb.id = "cb-" + u.id;
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(u.id));
      if (u.kind === "family") lab.appendChild(el("span", "fam", "family"));
      var sel = el("select"); sel.id = "st-" + u.id;
      var blank = el("option", null, "strength…"); blank.value = ""; sel.appendChild(blank);
      STRENGTHS.forEach(function (s) { var o = el("option", null, s); o.value = s; sel.appendChild(o); });
      var tog = el("button", "rtog", "reference"); tog.type = "button";
      r.appendChild(lab); r.appendChild(sel); r.appendChild(tog);
      var ref = el("div", "ref", u.ref); ref.id = "ref-" + u.id;
      wrap.appendChild(r); wrap.appendChild(ref);
      box.appendChild(wrap);
      cb.addEventListener("change", function () {
        var e = entry(ITEMS[state.cur].id);
        if (cb.checked) { e.units[u.id] = e.units[u.id] || ""; e.none = false; } else { delete e.units[u.id]; }
        save(); refresh();
      });
      sel.addEventListener("change", function () {
        var e = entry(ITEMS[state.cur].id);
        if (u.id in e.units) e.units[u.id] = sel.value;
        save(); refresh();
      });
      tog.addEventListener("click", function () { refOpen[u.id] = !refOpen[u.id]; refresh(); });
    });
  }

  function refresh() {
    var item = ITEMS[state.cur], e = entry(item.id);
    $("itemhead").textContent = "Item " + item.id + " (" + (state.cur + 1) + " of " + ITEMS.length + ")";
    $("text").textContent = item.text;
    UNITS.forEach(function (u) {
      var on = u.id in e.units;
      $("cb-" + u.id).checked = on;
      var sel = $("st-" + u.id);
      sel.disabled = !on;
      sel.value = on ? e.units[u.id] : "";
      $("u-" + u.id).className = "unit" + (on ? " ticked" : "");
      $("ref-" + u.id).className = "ref" + (allRefs || refOpen[u.id] ? " open" : "");
    });
    $("none").className = e.none ? "on" : "";
    if (document.activeElement !== $("note")) $("note").value = e.note;
    var done = ITEMS.filter(function (i) { return isDone(i.id); }).length;
    $("progress").textContent = done + " / " + ITEMS.length + " done";
    var st = $("status");
    st.textContent = isDone(item.id) ? "Done: " + (e.none ? "none present" : Object.keys(e.units).length + " unit(s) ticked")
                                     : "Not done: tick at least one unit or press None present";
    st.className = isDone(item.id) ? "done" : "todo";
    $("allref").textContent = allRefs ? "Hide all references" : "Show all references";
    var idx = $("index");
    idx.textContent = "";
    ITEMS.forEach(function (i, n) {
      var b = el("button", (isDone(i.id) ? "done" : "") + (n === state.cur ? " cur" : ""), i.id);
      b.type = "button";
      b.title = isDone(i.id) ? "done" : "not done";
      b.addEventListener("click", function () { go(n); });
      idx.appendChild(b);
    });
  }

  function go(n) {
    state.cur = Math.min(Math.max(n, 0), ITEMS.length - 1);
    $("msg").textContent = "";
    save(); refresh();
    window.scrollTo(0, 0);
  }

  function csvCell(s) {
    s = String(s == null ? "" : s);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function rows(onlyDone) {
    var out = [["item_id", "units_present", "strengths", "notes"]];
    ITEMS.forEach(function (i) {
      var e = state.items[i.id] || { units: {}, none: false, note: "" };
      var present = UNITS.filter(function (u) { return u.id in e.units; });
      var done = isDone(i.id);
      var units = !done ? "" : (e.none ? "none" : present.map(function (u) { return u.id; }).join(";"));
      var strengths = present.filter(function (u) { return e.units[u.id]; })
                             .map(function (u) { return u.id + "=" + e.units[u.id]; }).join(";");
      out.push([i.id, units, strengths, (e.note || "").trim()]);
    });
    return out;
  }
  function download(name, table) {
    var text = table.map(function (r) { return r.map(csvCell).join(","); }).join("\r\n") + "\r\n";
    var blob = new Blob([text], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); document.body.removeChild(a); }, 1000);
  }

  $("prev").addEventListener("click", function () { go(state.cur - 1); });
  $("next").addEventListener("click", function () { go(state.cur + 1); });
  $("allref").addEventListener("click", function () { allRefs = !allRefs; refresh(); });
  $("none").addEventListener("click", function () {
    var e = entry(ITEMS[state.cur].id);
    if (e.none) { e.none = false; }
    else {
      if (Object.keys(e.units).length && !window.confirm("Clear the ticked units and mark this item as none present?")) return;
      e.units = {}; e.none = true;
    }
    save(); refresh();
  });
  $("note").addEventListener("input", function () { entry(ITEMS[state.cur].id).note = $("note").value; save(); });
  $("export").addEventListener("click", function () {
    var open = ITEMS.filter(function (i) { return !isDone(i.id); }).map(function (i) { return i.id; });
    if (open.length) {
      $("msg").textContent = "Not exported. " + open.length + " item(s) not done: " + open.join(", ");
      return;
    }
    $("msg").textContent = "";
    download("labels_v2.csv", rows());
  });
  $("partial").addEventListener("click", function () {
    $("msg").textContent = "";
    download("labels_v2_PARTIAL_backup.csv", rows());
  });
  document.addEventListener("keydown", function (ev) {
    var t = ev.target && ev.target.tagName;
    if (t === "TEXTAREA" || t === "SELECT" || t === "INPUT" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === "ArrowLeft") go(state.cur - 1);
    if (ev.key === "ArrowRight") go(state.cur + 1);
  });

  load();
  buildUnits();
  refresh();
  save();
  if (!storageOK) { $("saved").textContent = "AUTOSAVE UNAVAILABLE: export a partial CSV before closing"; $("saved").className = "bad"; }
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
