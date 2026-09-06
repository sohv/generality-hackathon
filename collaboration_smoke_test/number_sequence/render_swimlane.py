"""Render one team run as a self-contained interactive swimlane HTML page.

Time runs top to bottom. Every agent and every shared file gets a lane. A file
interaction draws an arrow between the two lanes — file to agent for a read,
agent to file for a write — and labelled boxes sit on both lanes: the agent's
box says what it did ("write coord.txt"), the file's box says what happened to
it ("written by 1469"). Everything else is a box on the agent's lane alone.

Hover a box for details, or a file's lane line to see that file's entire
contents at that point in time. Click any box for a popup with the full text;
for a write that popup shows the whole resulting file as well as the diff.

    python -m number_sequence.render_swimlane RUN_DIRECTORY
    python -m number_sequence.render_swimlane path/to/run.eval --output view.html

Reuses extract_events, so it accepts the same targets and needs no network.
The page is one file with no external resources; open it directly in a browser.
"""
import argparse
import difflib
import html
import json
from pathlib import Path

from .extract_events import extract, resolve

FILE_TOOLS = ("read_file", "write_file")
# Comfortably above the largest reasoning block and file seen in these runs, so
# "the entire file" really is the entire file.
CAP = 20000

VERB = {"write_file": "write", "read_file": "read", "list_files": "list files",
        "submit_number": "submit", "exit_rollout": "exit",
        "message": "says", "model_error": "model error"}


def clip(text):
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= CAP else text[:CAP] + f"\n… [{len(text) - CAP} more characters]"


def short(agent):
    return agent[len("number_"):] if agent.startswith("number_") else agent


def build(records):
    """Attach file lanes, write diffs, per-moment file contents, and box labels."""
    agents, files, kinds, state = {}, {}, {}, {}
    events = []
    for record in records:
        agent = record["agent"] or "unattributed"
        agents[agent] = agents.get(agent, 0) + 1

        name = None
        if record["tool"] in FILE_TOOLS and isinstance(record["arguments"], dict):
            name = record["arguments"].get("name")
        detail = diff = content = None

        if record["tool"] == "write_file" and name:
            text = (record["arguments"] or {}).get("text") or ""
            if record["error"]:
                detail = "Write rejected; the file was left unchanged."
                content = state.get(name)
            else:
                previous = state.get(name)
                if '"appended_to"' in (record["output"] or ""):
                    # A version 9 write only adds: the argument is the new tail of
                    # the file, not its whole content, so replay what the host did.
                    base = previous or ""
                    if base and not base.endswith("\n"):
                        base += "\n"
                    text = base + text
                lines = difflib.unified_diff(
                    (previous or "").splitlines(), text.splitlines(),
                    fromfile=f"{name} before", tofile=f"{name} after", lineterm="", n=2)
                diff = "\n".join(lines) or "(write produced no change)"
                if previous is None:
                    diff = "[file created]\n" + diff
                state[name] = content = text
        elif record["tool"] == "read_file" and name:
            detail = content = record["output"]

        if name:
            files[name] = files.get(name, 0) + 1
        kind = record["tool"] or record["type"]
        kinds[kind] = kinds.get(kind, 0) + 1

        # For file interactions the arrow already carries read vs write, so the
        # boxes name only the other end: the file, and the agent.
        label = name if name else VERB.get(kind, kind)
        flabel = short(agent) if name else None

        events.append({
            "seq": record["seq"], "t": record["t"], "time": record["time"],
            "agent": agent, "short": short(agent), "type": record["type"],
            "tool": record["tool"], "kind": kind, "file": name,
            "label": label, "flabel": flabel,
            "args": clip(json.dumps(record["arguments"], indent=1) if record["arguments"] else None),
            "output": clip(record["output"]), "error": clip(record["error"]),
            "reasoning": clip(record["reasoning"]), "message": clip(record["message"]),
            "detail": clip(detail), "diff": clip(diff), "content": clip(content),
            "duration": record["duration_s"], "decided": record["decided_at"],
        })

    first = {}
    for event in events:
        first.setdefault(event["agent"], event["t"])
        if event["file"]:
            first.setdefault("f:" + event["file"], event["t"])

    def by_number(item):
        """Agents are named number_<N>; order the lanes by that assigned number."""
        tail = short(item[0])
        return (0, int(tail)) if tail.isdigit() else (1, 0, item[0])

    lanes = [{"id": "a:" + a, "kind": "agent", "label": a, "count": n}
             for a, n in sorted(agents.items(), key=by_number)]
    lanes += [{"id": "f:" + f, "kind": "file", "label": f, "count": n}
              for f, n in sorted(files.items(), key=lambda kv: first.get("f:" + kv[0], 0))]
    types = [{"id": k, "label": VERB.get(k, k), "count": n}
             for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])]
    return lanes, events, types


TEMPLATE = r"""<meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{
  --bg:#fbfaf9; --panel:#ffffff; --ink:#1c1a17; --muted:#6b645c; --line:#e3ded7;
  --lane-agent:#3f6fd8; --lane-file:#8a7048; --grid:#efeae3; --box:#f4f1ec;
  --on-strong:#ffffff;
  --t-list:#8d9298; --t-read:#3f8fd8; --t-write:#c98a25; --t-submit:#1f8a4c;
  --t-exit:#7a4fc0; --t-msg:#2aa39a; --t-err:#d0453e; --accent:#3f6fd8;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#16181c; --panel:#1d2026; --ink:#e8e6e3; --muted:#9a948c; --line:#2f343c;
  --lane-agent:#7aa2f7; --lane-file:#c9a227; --grid:#23272e; --box:#242932;
  --on-strong:#10141a;
  --t-list:#767c85; --t-read:#7aa2f7; --t-write:#e0af68; --t-submit:#4ade80;
  --t-exit:#c4a2f5; --t-msg:#4cd0c5; --t-err:#f07178; --accent:#7aa2f7;
}}
:root[data-theme="dark"]{
  --bg:#16181c; --panel:#1d2026; --ink:#e8e6e3; --muted:#9a948c; --line:#2f343c;
  --lane-agent:#7aa2f7; --lane-file:#c9a227; --grid:#23272e; --box:#242932;
  --on-strong:#10141a;
  --t-list:#767c85; --t-read:#7aa2f7; --t-write:#e0af68; --t-submit:#4ade80;
  --t-exit:#c4a2f5; --t-msg:#4cd0c5; --t-err:#f07178; --accent:#7aa2f7;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.app{display:grid;grid-template-columns:242px minmax(0,1fr) 180px;height:100vh}
aside{background:var(--panel);overflow:auto;padding:10px 12px}
.left{border-right:1px solid var(--line)}
.right{border-left:1px solid var(--line);padding:10px 8px;overflow:hidden;display:flex;flex-direction:column}
h1{font-size:13px;margin:2px 0 6px}
h2{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:14px 0 4px}
.meta{color:var(--muted);font-size:11.5px;margin-bottom:6px}
.row{display:flex;align-items:center;gap:6px;padding:2px 3px;border-radius:5px;cursor:pointer;font-size:12px}
.row:hover{background:var(--grid)}
.row input{margin:0;cursor:pointer;flex:none}
.row .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.row .ct{color:var(--muted);font-size:10.5px;flex:none}
.swatch{width:8px;height:8px;border-radius:2px;flex:none}
.btns{display:flex;gap:5px;margin:2px 0 4px;flex-wrap:wrap}
button{font:inherit;font-size:11px;padding:2px 8px;border:1px solid var(--line);background:var(--bg);
  color:var(--ink);border-radius:5px;cursor:pointer}
button:hover{border-color:var(--accent)}
.center{display:flex;flex-direction:column;overflow:hidden}
.heads{position:relative;height:54px;flex:none;overflow:hidden;
  border-bottom:1px solid var(--line);background:var(--panel)}
.headsInner{position:absolute;inset:0;will-change:transform}
.chip{position:absolute;top:4px;bottom:4px;width:79px;margin-left:-39.5px;cursor:grab;user-select:none;
  border:1px solid var(--line);border-radius:6px;background:var(--box);padding:2px 4px;
  display:flex;align-items:center;justify-content:center;text-align:center;
  font-size:10px;line-height:1.2;overflow:hidden;overflow-wrap:anywhere;
  transition:opacity .2s,border-color .15s}
.chip:hover{border-color:var(--accent)}
.chip .lbl{display:block;overflow:hidden;overflow-wrap:anywhere}
.chip.agent{border-left:3px solid var(--lane-agent)}
.chip.file{border-left:3px solid var(--lane-file)}
.chip.drag{cursor:grabbing;z-index:9;box-shadow:0 6px 18px rgba(0,0,0,.25)}
.canvas{flex:1;overflow:auto;position:relative}
#tip{position:fixed;z-index:60;max-width:540px;background:var(--panel);border:1px solid var(--line);
  border-radius:7px;padding:8px 10px;box-shadow:0 8px 26px rgba(0,0,0,.22);pointer-events:none;
  display:none;font-size:11.5px}
#tip h3,#mbody h3{margin:0 0 4px;font-size:12px}
pre{margin:5px 0 0;white-space:pre-wrap;word-break:break-word;background:var(--grid);
  padding:5px 6px;border-radius:5px;font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
#tip pre{max-height:230px;overflow:hidden}
.k{color:var(--muted)}
.add{color:var(--t-submit)} .del{color:var(--t-err)}
#modal{position:fixed;inset:0;z-index:80;background:rgba(0,0,0,.45);display:none;
  align-items:center;justify-content:center;padding:26px}
#modal.on{display:flex}
.sheet{background:var(--panel);border:1px solid var(--line);border-radius:10px;max-width:900px;
  width:100%;max-height:100%;overflow:auto;padding:16px 18px;box-shadow:0 20px 60px rgba(0,0,0,.4)}
.sheet .x{float:right}
.mini{flex:1;min-height:0;position:relative}
.hint{color:var(--muted);font-size:10.5px;margin-top:8px}
.ev{cursor:pointer}
.lanehit{cursor:help}
.flash{animation:flash 1.4s ease-out}
@keyframes flash{0%{stroke:var(--accent);stroke-width:3}100%{stroke-width:1}}
</style>

<div class="app">
  <aside class="left">
    <h1>__TITLE__</h1>
    <div class="meta" id="meta"></div>
    <div class="btns"><button id="resetAll">Reset view</button></div>
    <label class="row"><input type="checkbox" id="collapse">
      <span class="nm">Collapse (overview)</span></label>
    <h2>Agents</h2>
    <div class="btns"><button data-all="agent" data-on="1">Show all</button>
      <button data-all="agent" data-on="0">Hide all</button></div>
    <div id="agentList"></div>
    <h2>Files</h2>
    <div class="btns"><button data-all="file" data-on="1">Show all</button>
      <button data-all="file" data-on="0">Hide all</button></div>
    <div id="fileList"></div>
    <h2>Events</h2>
    <div class="btns"><button data-all="type" data-on="1">Show all</button>
      <button data-all="type" data-on="0">Hide all</button></div>
    <label class="row"><input type="checkbox" id="ihf" checked>
      <span class="nm">Include hidden files</span></label>
    <div id="typeList"></div>
    <div class="hint">Drag a lane header to reorder. Hover a box for details, or a file's lane
      line for its contents at that moment. Click a box for the full text.</div>
  </aside>

  <div class="center">
    <div class="heads"><div class="headsInner" id="heads"></div></div>
    <div class="canvas" id="canvas"><svg id="svg" xmlns="http://www.w3.org/2000/svg"></svg></div>
  </div>

  <aside class="right">
    <h2 style="margin-top:2px">Overview</h2>
    <div class="mini"><svg id="mini" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%"></svg></div>
  </aside>
</div>
<div id="tip"></div>
<div id="modal"><div class="sheet"><button class="x" id="mclose">Close</button><div id="mbody"></div></div></div>

<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const LINE_H = 11, PAD_Y = 6, MIN_H = 17, TOP = 26;
// Collapsed mode is the same diagram with the text removed and everything drawn
// tighter, so it reads like a large version of the overview strip.
const EXP = {laneW: 85, boxW: 76, padX: 70, gap: 6, chip: 79};
const COL = {laneW: 20, boxW: 14, padX: 26, gap: 3, chip: 16};
const COL_H = 10;
const lerp = (a, b, c) => a + (b - a) * c;
const laneW = c => lerp(EXP.laneW, COL.laneW, c);
const boxWAt = c => lerp(EXP.boxW, COL.boxW, c);
const padXAt = c => lerp(EXP.padX, COL.padX, c);
const gapAt = c => lerp(EXP.gap, COL.gap, c);
const hAt = (full, c) => lerp(full, COL_H, c);
const BOX_W = EXP.boxW;
const FS = 10, CH = 5.35, MAX_LINES = 3;
const STRONG = new Set(["submit_number", "exit_rollout"]);
const COLOR = {list_files:"--t-list", read_file:"--t-read", write_file:"--t-write",
  submit_number:"--t-submit", exit_rollout:"--t-exit", message:"--t-msg", model_error:"--t-err"};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const tone = e => css(COLOR[e.kind] || "--t-list");

// Greedy wrap that also hard-splits long tokens such as file names.
function wrap(s, maxChars, maxLines) {
  if (!s) return [""];
  const out = [];
  for (let word of s.split(/\s+/)) {
    while (word.length > maxChars) {
      if (out.length && out[out.length - 1] === "") out.pop();
      out.push(word.slice(0, maxChars)); word = word.slice(maxChars);
    }
    if (!out.length) { out.push(word); continue; }
    const last = out[out.length - 1];
    if ((last + " " + word).length <= maxChars) out[out.length - 1] = last + " " + word;
    else out.push(word);
  }
  if (out.length > maxLines) {
    const kept = out.slice(0, maxLines);
    kept[maxLines - 1] = kept[maxLines - 1].slice(0, Math.max(1, maxChars - 1)) + "…";
    return kept;
  }
  return out;
}
const MAXC = Math.floor((BOX_W - 8) / CH);
const boxH = lines => Math.max(MIN_H, lines * LINE_H + PAD_Y);

const lanes = DATA.lanes, events = DATA.events, types = DATA.types;
const byId = Object.fromEntries(lanes.map((l, i) => [l.id, (l.idx = i, l)]));
let order = lanes.map((_, i) => i), hidden = new Set(), hiddenTypes = new Set();
let includeHiddenFiles = true, selected = null, collapsed = false;
let cPrev = 0, cT = 0;
const laneX = {}, prevX = {};
let HEIGHT = 100, prevHeight = 100, grid = [];

const fileVisible = e => !!e.file && !hidden.has(byId["f:" + e.file]?.idx);
const shown = e => !hiddenTypes.has(e.kind) && !hidden.has(byId["a:" + e.agent]?.idx) &&
                   (!e.file || fileVisible(e) || includeHiddenFiles);
const arrowed = e => fileVisible(e);          // only then are the file box and arrow drawn
const visLanes = () => order.filter(i => !hidden.has(i));

// ---- URL state -------------------------------------------------------------
function readURL() {
  const q = new URLSearchParams(location.search);
  if (q.get("order")) {
    const want = q.get("order").split(",").map(Number).filter(n => lanes[n]);
    if (want.length) order = [...new Set(want)].concat(order.filter(i => !want.includes(i)));
  }
  if (q.get("hidden")) hidden = new Set(q.get("hidden").split(",").map(Number).filter(n => lanes[n]));
  if (q.get("types")) hiddenTypes = new Set(q.get("types").split(","));
  if (q.get("ihf") === "0") includeHiddenFiles = false;
  if (q.get("collapse") === "1") { collapsed = true; cPrev = cT = 1; }
}
function writeURL() {
  const q = new URLSearchParams();
  if (order.some((v, i) => v !== i)) q.set("order", order.join(","));
  if (hidden.size) q.set("hidden", [...hidden].join(","));
  if (hiddenTypes.size) q.set("types", [...hiddenTypes].join(","));
  if (!includeHiddenFiles) q.set("ihf", "0");
  if (collapsed) q.set("collapse", "1");
  history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : "") +
    (selected ? "#ev-" + selected : location.hash || ""));
}

// ---- layout ----------------------------------------------------------------
function computeX() {
  Object.assign(prevX, laneX);
  const W = laneW(cT), P = padXAt(cT);
  let slot = 0;
  for (const i of order) {
    laneX[lanes[i].id] = P + slot * W;
    if (!hidden.has(i)) slot++;
  }
}
// Only visible events take vertical space, so hiding lanes compresses the page.
// Consecutive events that draw no arrow share one row, so a burst of list_files
// or submits sits side by side instead of stretching downwards.
function layout() {
  const rows = [];
  let cur = null;
  for (const e of events) {
    if (e.yT !== undefined) e.yP = e.yT;
    if (!shown(e)) continue;
    // A submission never shares a row: the sequence is what is scored, so two
    // submissions at the same height would hide which of them went first.
    const lane = "a:" + e.agent;
    const canPack = !arrowed(e) && e.kind !== "submit_number";
    if (canPack && cur && cur.open && !cur.lanes.has(lane)) {
      cur.events.push(e); cur.lanes.add(lane);
    } else {
      cur = {events: [e], lanes: new Set([lane]), open: canPack};
      if (arrowed(e)) cur.lanes.add("f:" + e.file);
      rows.push(cur);
    }
  }
  let y = TOP;
  for (const r of rows) {
    const full = Math.max(...r.events.map(e => arrowed(e) ? Math.max(e.aH, e.fH) : e.aH));
    const h = hAt(full, cT);
    y += h / 2;
    for (const e of r.events) { e.yT = y; if (e.yP === undefined) e.yP = y; }
    y += h / 2 + gapAt(cT);
  }
  prevHeight = HEIGHT;
  HEIGHT = y + 30;

  const vis = events.filter(shown);
  const old = grid;
  grid = [];
  for (let i = 0, s = 0; s <= DATA.duration + 30; s += 30, i++) {
    let y2 = TOP;
    if (vis.length) {
      if (s <= vis[0].t) y2 = vis[0].yT;
      else {
        y2 = vis[vis.length - 1].yT;
        for (let j = 1; j < vis.length; j++) if (vis[j].t >= s) {
          const a = vis[j - 1], b = vis[j];
          y2 = a.yT + (b.yT - a.yT) * (b.t === a.t ? 0 : (s - a.t) / (b.t - a.t));
          break;
        }
      }
    }
    grid.push({s, y: y2, yP: old[i] ? old[i].y : y2});
  }
}

// ---- build once ------------------------------------------------------------
const svg = document.getElementById("svg"), heads = document.getElementById("heads");
const gGrid = document.createElementNS(NS, "g"), gLane = document.createElementNS(NS, "g");
const gHit = document.createElementNS(NS, "g"), gEv = document.createElementNS(NS, "g");
const defs = document.createElementNS(NS, "defs");
svg.append(defs, gGrid, gLane, gHit, gEv);
for (const [id, v] of [["ah-r", "--t-read"], ["ah-w", "--t-write"]]) {
  const m = document.createElementNS(NS, "marker");
  m.setAttribute("id", id); m.setAttribute("viewBox", "0 0 8 8");
  m.setAttribute("refX", "7"); m.setAttribute("refY", "4");
  m.setAttribute("markerWidth", "6"); m.setAttribute("markerHeight", "6");
  m.setAttribute("orient", "auto-start-reverse");
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", "M0,0 L8,4 L0,8 Z"); p.setAttribute("fill", css(v));
  m.append(p); defs.append(m);
}
const gridEls = [];
for (let s = 0; s <= DATA.duration + 30; s += 30) {
  const ln = document.createElementNS(NS, "line"), tx = document.createElementNS(NS, "text");
  ln.setAttribute("stroke", css("--grid")); ln.setAttribute("x1", 0);
  tx.setAttribute("x", 6); tx.setAttribute("fill", css("--muted"));
  tx.setAttribute("font-size", 9); tx.textContent = s + "s";
  gGrid.append(ln, tx); gridEls.push({ln, tx});
}
const laneEls = lanes.map(l => {
  const ln = document.createElementNS(NS, "line");
  ln.setAttribute("y1", 0);
  ln.setAttribute("stroke", css(l.kind === "agent" ? "--lane-agent" : "--lane-file"));
  ln.setAttribute("stroke-width", 2);
  gLane.append(ln); return ln;
});
// Wide transparent strips make the file lane lines hoverable between boxes.
const hits = lanes.map(l => {
  const r = document.createElementNS(NS, "rect");
  r.setAttribute("width", 14); r.setAttribute("y", 0); r.setAttribute("fill", "transparent");
  if (l.kind === "file") {
    r.setAttribute("class", "lanehit");
    r.addEventListener("mousemove", ev => laneTip(l, ev));
    r.addEventListener("mouseleave", () => hideTip());
  } else r.setAttribute("pointer-events", "none");
  gHit.append(r); return r;
});
const chips = lanes.map(l => {
  const d = document.createElement("div");
  d.className = "chip " + l.kind; d.dataset.lane = l.idx;
  d.innerHTML = '<span class="lbl"></span>';
  d.firstChild.textContent = l.label;
  d.title = l.label + " — " + l.count + " events";
  heads.append(d); return d;
});

function mkBox(lines, fill, stroke, ink, strong) {
  const g = document.createElementNS(NS, "g");
  const r = document.createElementNS(NS, "rect");
  r.setAttribute("height", boxH(lines.length)); r.setAttribute("width", BOX_W);
  r.setAttribute("rx", 4); r.setAttribute("fill", fill);
  r.setAttribute("stroke", stroke); r.setAttribute("stroke-width", strong ? 1.6 : 1);
  const t = document.createElementNS(NS, "text");
  t.setAttribute("font-size", FS); t.setAttribute("text-anchor", "middle");
  t.setAttribute("fill", ink); t.setAttribute("pointer-events", "none");
  if (strong) t.setAttribute("font-weight", "600");
  lines.forEach((s, i) => {
    const sp = document.createElementNS(NS, "tspan");
    sp.setAttribute("x", 0); sp.setAttribute("dy", i ? LINE_H : 0);
    sp.textContent = s; t.append(sp);
  });
  g.append(r, t);
  return {g, r, t, n: lines.length, h: boxH(lines.length), hFull: boxH(lines.length)};
}

const nodes = events.map(e => {
  const color = tone(e), strong = STRONG.has(e.kind);
  const g = document.createElementNS(NS, "g");
  g.setAttribute("class", "ev"); g.id = "ev-" + e.seq;
  let arrow = null, fbox = null;
  if (e.file) {
    arrow = document.createElementNS(NS, "line");
    arrow.setAttribute("stroke", color); arrow.setAttribute("stroke-width", 1.4);
    arrow.setAttribute("marker-end", e.tool === "read_file" ? "url(#ah-r)" : "url(#ah-w)");
    if (e.error) arrow.setAttribute("stroke-dasharray", "3 3");
    g.append(arrow);
    fbox = mkBox(wrap(e.flabel, MAXC, MAX_LINES), css("--box"), color, css("--ink"), false);
    g.append(fbox.g);
  }
  const abox = mkBox(wrap(e.label, MAXC, MAX_LINES),
                     strong ? color : css("--box"), color,
                     strong ? css("--on-strong") : css("--ink"), strong);
  if (e.error) abox.r.setAttribute("stroke-width", 2);
  g.append(abox.g); gEv.append(g);
  e.aH = abox.h; e.fH = fbox ? fbox.h : abox.h;

  abox.g.addEventListener("mouseenter", ev => showTip(e, "agent", ev));
  abox.g.addEventListener("mousemove", ev => moveTip(ev));
  abox.g.addEventListener("mouseleave", () => hideTip());
  abox.g.addEventListener("click", () => openModal(e, "agent"));
  if (fbox) {
    fbox.g.addEventListener("mouseenter", ev => showTip(e, "file", ev));
    fbox.g.addEventListener("mousemove", ev => moveTip(ev));
    fbox.g.addEventListener("mouseleave", () => hideTip());
    fbox.g.addEventListener("click", () => openModal(e, "file"));
  }
  return {e, g, abox, fbox, arrow};
});

// ---- paint -----------------------------------------------------------------
const mix = (a, b, m) => a === undefined ? b : a + (b - a) * m;
function place(box, cx, cy, BW, c) {
  const h = hAt(box.hFull, c);
  box.r.setAttribute("x", cx - BW / 2); box.r.setAttribute("y", cy - h / 2);
  box.r.setAttribute("width", BW); box.r.setAttribute("height", h);
  const op = Math.max(0, 1 - 2 * c);        // text fades out well before full collapse
  box.t.setAttribute("opacity", op);
  box.t.style.display = op > 0 ? "" : "none";
  if (op > 0) {
    // y is the first line's baseline: centre the whole block, then drop by
    // roughly half a cap height so the glyphs sit on the box's centre line.
    box.t.setAttribute("y", cy - (box.n - 1) * LINE_H / 2 + FS * 0.35);
    for (const sp of box.t.childNodes) sp.setAttribute("x", cx);
  }
}
function paint(m) {
  const c = mix(cPrev, cT, m), W = laneW(c), P = padXAt(c), BW = boxWAt(c);
  const width = P + Math.max(visLanes().length, 1) * W + P;
  const h = mix(prevHeight, HEIGHT, m);
  svg.setAttribute("width", width); svg.setAttribute("height", h);
  svg.setAttribute("viewBox", `0 0 ${width} ${h}`);

  lanes.forEach((l, i) => {
    const x = mix(prevX[l.id], laneX[l.id], m), off = hidden.has(i);
    laneEls[i].setAttribute("x1", x); laneEls[i].setAttribute("x2", x);
    laneEls[i].setAttribute("y2", h);
    laneEls[i].setAttribute("opacity", off ? 0 : (l.kind === "agent" ? .45 : .38));
    const hw = Math.max(4, Math.min(14, W - 2));
    hits[i].setAttribute("x", x - hw / 2); hits[i].setAttribute("width", hw);
    hits[i].setAttribute("height", h);
    hits[i].style.display = off ? "none" : "";
    const cw = lerp(EXP.chip, COL.chip, c);
    chips[i].style.width = cw + "px";
    chips[i].style.marginLeft = (-cw / 2) + "px";
    chips[i].style.transform = `translateX(${x}px)`;
    chips[i].style.opacity = off ? 0 : 1;
    chips[i].style.pointerEvents = off ? "none" : "auto";
    chips[i].firstChild.style.opacity = Math.max(0, 1 - 2 * c);
  });
  gridEls.forEach((el, i) => {
    const g = grid[i]; if (!g) return;
    const y = mix(g.yP, g.y, m);
    el.ln.setAttribute("x2", width); el.ln.setAttribute("y1", y); el.ln.setAttribute("y2", y);
    el.tx.setAttribute("y", y - 3);
  });
  for (const n of nodes) {
    const on = shown(n.e);
    n.g.style.display = on ? "" : "none";
    if (!on) continue;
    const y = mix(n.e.yP, n.e.yT, m), ax = mix(prevX["a:" + n.e.agent], laneX["a:" + n.e.agent], m);
    place(n.abox, ax, y, BW, c);
    const withFile = arrowed(n.e);
    if (n.fbox) { n.fbox.g.style.display = withFile ? "" : "none"; }
    if (n.arrow) n.arrow.style.display = withFile ? "" : "none";
    if (withFile) {
      const fx = mix(prevX["f:" + n.e.file], laneX["f:" + n.e.file], m);
      place(n.fbox, fx, y, BW, c);
      const read = n.e.tool === "read_file", dir = Math.sign(fx - ax) || 1;
      const aEdge = ax + dir * BW / 2, fEdge = fx - dir * BW / 2;
      n.arrow.setAttribute("x1", read ? fEdge : aEdge);
      n.arrow.setAttribute("x2", read ? aEdge : fEdge);
      n.arrow.setAttribute("y1", y); n.arrow.setAttribute("y2", y);
    }
  }
  drawMini();
}
function relayout(animate = true) {
  computeX(); layout(); writeURL();
  if (!animate) { paint(1); settle(); return; }
  const t0 = performance.now(), D = 420;
  let done = false;
  const finish = () => { if (done) return; done = true; paint(1); settle(); };
  (function step(now) {
    if (done) return;
    // A rAF timestamp can predate the performance.now() taken just above, which
    // would make p negative and extrapolate the layout backwards; clamp it.
    const p = Math.max(0, Math.min(1, (now - t0) / D));
    paint(1 - Math.pow(1 - p, 3));
    if (p < 1) requestAnimationFrame(step); else finish();
  })(performance.now());
  setTimeout(finish, D + 80);   // frames may never arrive; the end state must still be right
}
function settle() {
  Object.assign(prevX, laneX); prevHeight = HEIGHT; cPrev = cT;
  for (const e of events) e.yP = e.yT;
  for (const g of grid) g.yP = g.y;
}

// ---- minimap ---------------------------------------------------------------
const mini = document.getElementById("mini");
function drawMini() {
  const r = mini.getBoundingClientRect();
  const W = Math.max(r.width, 10), H = Math.max(r.height, 10);
  mini.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const vis = visLanes(), slot = {};
  const sx = i => vis.length < 2 ? W / 2 : 5 + i * (W - 14) / (vis.length - 1);
  vis.forEach((li, i) => slot[lanes[li].id] = sx(i));
  const sy = y => y / Math.max(HEIGHT, 1) * (H - 6) + 3;
  let out = "";
  vis.forEach((li, i) => out += `<line x1="${sx(i)}" y1="3" x2="${sx(i)}" y2="${H - 3}" stroke="${
    css(lanes[li].kind === "agent" ? "--lane-agent" : "--lane-file")}" stroke-width="1" opacity=".3"/>`);
  for (const n of nodes) {
    if (!shown(n.e)) continue;
    const ax = slot["a:" + n.e.agent]; if (ax === undefined) continue;
    const y = sy(n.e.yT), fx = arrowed(n.e) ? slot["f:" + n.e.file] : undefined;
    if (fx !== undefined) out += `<line x1="${Math.min(ax, fx)}" y1="${y}" x2="${
      Math.max(ax, fx)}" y2="${y}" stroke="${tone(n.e)}" stroke-width=".7" opacity=".55"/>`;
    out += `<circle cx="${ax}" cy="${y}" r="1.4" fill="${tone(n.e)}"/>`;
  }
  mini.innerHTML = out + `<rect id="vp" x="1" width="${W - 2}" height="10" fill="${css("--accent")}"
    opacity=".15" stroke="${css("--accent")}"/>`;
  syncVp();
}
function syncVp() {
  const vp = mini.querySelector("#vp"); if (!vp) return;
  const H = Math.max(mini.getBoundingClientRect().height, 10);
  vp.setAttribute("y", canvas.scrollTop / Math.max(HEIGHT, 1) * (H - 6) + 3);
  vp.setAttribute("height", Math.max(4, canvas.clientHeight / Math.max(HEIGHT, 1) * (H - 6)));
}
mini.addEventListener("mousedown", ev => {
  const jump = e2 => { const r = mini.getBoundingClientRect();
    canvas.scrollTop = (e2.clientY - r.top) / r.height * HEIGHT - canvas.clientHeight / 2; };
  jump(ev);
  const mv = e2 => jump(e2), up = () => {
    removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
  addEventListener("mousemove", mv); addEventListener("mouseup", up);
});

// ---- details ---------------------------------------------------------------
const tip = document.getElementById("tip"), modal = document.getElementById("modal");
const esc = s => (s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const diffHTML = d => esc(d).split("\n").map(l =>
  l.startsWith("+") ? `<span class="add">${l}</span>` :
  l.startsWith("-") ? `<span class="del">${l}</span>` : l).join("\n");

function body(e, side, full) {
  const cut = (s, n) => (full || !s || s.length <= n) ? s : s.slice(0, n) + "\n… [click for all]";
  let h = `<h3>${esc(e.kind)} <span class="k">· ${esc(e.agent)} · t=${e.t.toFixed(1)}s</span></h3>`;
  if (e.file) h += `<div class="k">file: ${esc(e.file)}</div>`;
  if (e.error) h += `<div class="del">error: ${esc(e.error)}</div>`;
  const fileFirst = side === "file" || e.tool === "write_file";
  if (fileFirst && e.file) {
    const heading = e.tool === "write_file" ? "the whole file after this write" : "the whole file at this point";
    h += `<div class="k" style="margin-top:5px">${esc(e.file)} — ${heading}</div>`;
    h += `<pre>${esc(cut(e.content ?? "(contents unknown at this point)", 1400))}</pre>`;
    if (e.diff) h += `<div class="k" style="margin-top:5px">what this write changed</div><pre>${
      diffHTML(cut(e.diff, 900))}</pre>`;
  }
  if (side !== "file") {
    if (e.reasoning) h += `<div class="k" style="margin-top:5px">reasoning</div><pre>${
      esc(cut(e.reasoning, 900))}</pre>`;
    if (e.message) h += `<div class="k" style="margin-top:5px">said</div><pre>${esc(cut(e.message, 700))}</pre>`;
    if (!fileFirst && e.detail) h += `<div class="k" style="margin-top:5px">contents read</div><pre>${
      esc(cut(e.detail, 1200))}</pre>`;
    else if (!fileFirst && e.output) h += `<div class="k" style="margin-top:5px">output</div><pre>${
      esc(cut(e.output, 700))}</pre>`;
  }
  if (full && e.args) h += `<div class="k" style="margin-top:5px">arguments</div><pre>${esc(e.args)}</pre>`;
  h += `<div class="k" style="margin-top:6px">#ev-${e.seq}${full ? "" : " · click for the full text"}</div>`;
  return h;
}
function showTip(e, side, ev) { tip.innerHTML = body(e, side, false); tip.style.display = "block"; moveTip(ev); }
function moveTip(ev) {
  tip.style.left = Math.min(ev.clientX + 16, innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = Math.min(Math.max(8, ev.clientY + 14), innerHeight - tip.offsetHeight - 8) + "px";
}
const hideTip = () => tip.style.display = "none";
// Hovering a file's lane line reports that file's contents as of that height.
function laneTip(lane, ev) {
  const name = lane.label;
  const y = ev.clientY - svg.getBoundingClientRect().top;
  let at = null;
  for (const e of events) {
    if (e.file !== name || !shown(e) || e.yT > y) continue;
    if (e.content !== null && e.content !== undefined) at = e;
  }
  const head = `<h3>${esc(name)}</h3><div class="k">contents at this point in time</div>`;
  tip.innerHTML = at
    ? head + `<pre>${esc(at.content.length > 1600 ? at.content.slice(0, 1600) + "\n…" : at.content)}</pre>` +
      `<div class="k" style="margin-top:5px">as of t=${at.t.toFixed(1)}s · ${esc(at.kind)} by ${esc(at.short)}</div>`
    : head + `<pre>(the file does not exist yet at this point)</pre>`;
  tip.style.display = "block"; moveTip(ev);
}
function openModal(e, side) {
  hideTip(); selected = e.seq; writeURL();
  document.getElementById("mbody").innerHTML = body(e, side, true);
  modal.classList.add("on");
}
const closeModal = () => modal.classList.remove("on");
document.getElementById("mclose").onclick = closeModal;
modal.addEventListener("click", ev => { if (ev.target === modal) closeModal(); });
addEventListener("keydown", ev => { if (ev.key === "Escape") closeModal(); });

// ---- sidebar ---------------------------------------------------------------
function sidebar() {
  const A = document.getElementById("agentList"), F = document.getElementById("fileList");
  const T = document.getElementById("typeList");
  A.innerHTML = F.innerHTML = T.innerHTML = "";
  for (const l of lanes) {
    const row = document.createElement("label");
    row.className = "row";
    row.innerHTML = `<input type="checkbox" ${hidden.has(l.idx) ? "" : "checked"}>
      <span class="swatch"></span><span class="nm"></span><span class="ct">${l.count}</span>`;
    row.querySelector(".nm").textContent = l.label;
    row.querySelector(".swatch").style.background = css(l.kind === "agent" ? "--lane-agent" : "--lane-file");
    row.querySelector("input").addEventListener("change", ev => {
      ev.target.checked ? hidden.delete(l.idx) : hidden.add(l.idx);
      relayout();
    });
    (l.kind === "agent" ? A : F).append(row);
  }
  for (const ty of types) {
    const row = document.createElement("label");
    row.className = "row";
    row.innerHTML = `<input type="checkbox" ${hiddenTypes.has(ty.id) ? "" : "checked"}>
      <span class="swatch"></span><span class="nm"></span><span class="ct">${ty.count}</span>`;
    row.querySelector(".nm").textContent = ty.label;
    row.querySelector(".swatch").style.background = css(COLOR[ty.id] || "--t-list");
    row.querySelector("input").addEventListener("change", ev => {
      ev.target.checked ? hiddenTypes.delete(ty.id) : hiddenTypes.add(ty.id);
      relayout();
    });
    T.append(row);
  }
}
for (const b of document.querySelectorAll("[data-all]")) b.onclick = () => {
  const on = b.dataset.on === "1";
  if (b.dataset.all === "type") {
    hiddenTypes = on ? new Set() : new Set(types.map(t => t.id));
  } else {
    for (const l of lanes) if (l.kind === b.dataset.all)
      on ? hidden.delete(l.idx) : hidden.add(l.idx);
  }
  sidebar(); relayout();
};
document.getElementById("ihf").addEventListener("change", ev => {
  includeHiddenFiles = ev.target.checked; relayout();
});
document.getElementById("collapse").addEventListener("change", ev => {
  collapsed = ev.target.checked; cT = collapsed ? 1 : 0; relayout();
});
document.getElementById("resetAll").onclick = () => {
  order = lanes.map((_, i) => i); hidden = new Set(); hiddenTypes = new Set();
  includeHiddenFiles = true; document.getElementById("ihf").checked = true;
  collapsed = false; cT = 0; document.getElementById("collapse").checked = false;
  selected = null; history.replaceState(null, "", location.pathname);
  sidebar(); relayout();
};

// ---- drag to reorder -------------------------------------------------------
let drag = null;
heads.addEventListener("mousedown", ev => {
  const chip = ev.target.closest(".chip"); if (!chip) return;
  const idx = +chip.dataset.lane;
  drag = {idx, chip, startX: ev.clientX, base: laneX[lanes[idx].id]};
  chip.classList.add("drag"); ev.preventDefault();
});
addEventListener("mousemove", ev => {
  if (!drag) return;
  const x = drag.base + (ev.clientX - drag.startX);
  drag.chip.style.transform = `translateX(${x}px)`;
  const vis = visLanes(), from = vis.indexOf(drag.idx);
  const target = Math.max(0, Math.min(vis.length - 1, Math.round((x - padXAt(cT)) / laneW(cT))));
  if (from !== -1 && target !== from) {
    vis.splice(from, 1); vis.splice(target, 0, drag.idx);
    let k = 0; order = order.map(i => hidden.has(i) ? i : vis[k++]);
    computeX(); paint(1); settle();
    drag.chip.style.transform = `translateX(${x}px)`;
  }
});
addEventListener("mouseup", () => {
  if (!drag) return;
  drag.chip.classList.remove("drag"); drag = null;
  computeX(); paint(1); settle(); writeURL();
});

// ---- anchors ---------------------------------------------------------------
function flash(seq) {
  const n = nodes.find(n => n.e.seq === seq); if (!n || !shown(n.e)) return;
  canvas.scrollTop = n.e.yT - canvas.clientHeight / 2;
  const r = n.abox.r;
  r.classList.remove("flash"); void r.getBoundingClientRect(); r.classList.add("flash");
}
function fromHash() {
  const m = /^#ev-(\d+)$/.exec(location.hash);
  if (m) { selected = +m[1]; flash(selected); }
}
addEventListener("hashchange", fromHash);

// ---- go --------------------------------------------------------------------
const canvas = document.getElementById("canvas");
canvas.addEventListener("scroll", () => {
  heads.style.transform = `translateX(${-canvas.scrollLeft}px)`; syncVp();
});
addEventListener("resize", drawMini);
document.getElementById("meta").textContent =
  `${DATA.agents} agents · ${DATA.files} files · ${events.length} events · ${DATA.duration.toFixed(0)}s`;
readURL();
document.getElementById("ihf").checked = includeHiddenFiles;
document.getElementById("collapse").checked = collapsed;
sidebar(); computeX(); Object.assign(prevX, laneX); layout(); settle(); paint(1); fromHash();
</script>
"""


def render(records, title):
    lanes, events, types = build(records)
    data = {"lanes": lanes, "events": events, "types": types,
            "duration": max((e["t"] for e in events), default=0),
            "agents": sum(l["kind"] == "agent" for l in lanes),
            "files": sum(l["kind"] == "file" for l in lanes)}
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(title))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path, help="Run directory, or a path to a .eval log")
    parser.add_argument("--output", type=Path, help="Default: swimlane.html inside the run directory")
    args = parser.parse_args()

    log_path, started_at, run_dir = resolve(args.target)
    records, _ = extract(log_path, started_at)
    output = args.output or run_dir / "swimlane.html"
    output.write_text(render(records, run_dir.name), encoding="utf-8")
    print(f"{output}: {len(records)} events, {output.stat().st_size / 1e6:.1f} MB — open it in a browser")


if __name__ == "__main__":
    main()
