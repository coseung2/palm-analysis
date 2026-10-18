#!/usr/bin/env python3
"""Manual mask-correction tool for training_pack/data pseudo-labels.

The teacher's pseudo-labels aren't always clean (missing/truncated/wrong
lines) -- this serves a small local web app to touch them up by hand:
paint/erase per class directly over the photo, then save back to
data/masks/<stem>.png in the same format dataset.py already reads.

    python label_tool.py --data_dir training_pack/data

Opens http://127.0.0.1:8765/ in your browser. Review status (edited /
approved / rejected) is tracked in data/reviewed.csv, kept separate from
manifest.csv (which generate_pseudo_labels.py owns and may still be
appending to) so the two writers never race on the same file.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime
import http.server
import json
import socketserver
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

CLASS_COLORS = {0: (0, 0, 0), 1: (255, 0, 0), 2: (0, 0, 255), 3: (0, 255, 0)}  # class -> (R, G, B)


def load_manifest(data_dir: Path) -> dict:
    path = data_dir / "manifest.csv"
    info = {}
    if path.exists():
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                info[row["stem"]] = row
    return info


def load_reviewed(data_dir: Path) -> dict:
    path = data_dir / "reviewed.csv"
    reviewed = {}
    if path.exists():
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                reviewed[row["stem"]] = row
    return reviewed


def save_reviewed(data_dir: Path, reviewed: dict) -> None:
    path = data_dir / "reviewed.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stem", "status", "timestamp"])
        w.writeheader()
        for stem in sorted(reviewed):
            w.writerow(reviewed[stem])


def mark_reviewed(data_dir: Path, stem: str, status: str) -> None:
    reviewed = load_reviewed(data_dir)
    reviewed[stem] = {
        "stem": stem,
        "status": status,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    save_reviewed(data_dir, reviewed)


def class_index_to_bgra(mask: np.ndarray) -> np.ndarray:
    """Class 0 (background) -> fully transparent; 1/2/3 -> opaque class color."""
    h, w = mask.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for c, (r, g, b) in CLASS_COLORS.items():
        if c == 0:
            continue
        sel = mask == c
        out[sel] = (b, g, r, 255)
    return out


def bgra_to_class_index(bgra: np.ndarray) -> np.ndarray:
    """Inverse of class_index_to_bgra, robust to canvas anti-aliasing:
    alpha thresholds background vs. paint, nearest-color classifies the rest.
    """
    alpha = bgra[:, :, 3]
    rgb = bgra[:, :, [2, 1, 0]].astype(np.int32)
    colors = np.array([CLASS_COLORS[c] for c in (1, 2, 3)], dtype=np.int32)
    diff = rgb[:, :, None, :] - colors[None, None, :, :]
    dist = np.sum(diff * diff, axis=-1)  # int32: 255**2 * 3 fits easily, unlike int16
    nearest = np.argmin(dist, axis=-1).astype(np.uint8) + 1
    return np.where(alpha > 127, nearest, 0).astype(np.uint8)


INDEX_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Palm Line Mask Editor</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, sans-serif; background:#1b1b1f; color:#e8e8ec; display:flex; height:100vh; overflow:hidden; }
  #sidebar { width: 270px; background:#131316; border-right:1px solid #2a2a30; overflow-y:auto; flex-shrink:0; }
  #sidebar h2 { font-size:13px; padding:10px 12px 4px; color:#9a9aa4; text-transform:uppercase; letter-spacing:.05em; margin:0; display:flex; justify-content:space-between; align-items:center; }
  .stem-item { padding:6px 12px; cursor:pointer; font-size:12px; display:flex; align-items:center; gap:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .stem-item:hover { background:#202024; }
  .stem-item.active { background:#2d3548; }
  .dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
  .dot.pending-fail { background:#55555c; }
  .dot.pending-pass { background:#d9a441; }
  .dot.approved, .dot.edited { background:#4caf6b; }
  .dot.rejected { background:#d9534f; }
  #main { flex:1; display:flex; flex-direction:column; min-width:0; }
  #toolbar { display:flex; align-items:center; gap:10px; padding:10px 14px; background:#131316; border-bottom:1px solid #2a2a30; flex-wrap:wrap; }
  .btn { background:#26262c; border:1px solid #3a3a42; color:#e8e8ec; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
  .btn:hover { background:#323238; }
  .btn.active { outline:2px solid #6d8fff; }
  .swatch { width:14px; height:14px; border-radius:3px; display:inline-block; margin-right:6px; vertical-align:-2px; }
  #canvas-wrap { flex:1; display:flex; align-items:center; justify-content:center; overflow:auto; background:#0d0d10; position:relative; }
  #stage { position:relative; }
  canvas { position:absolute; top:0; left:0; image-rendering: pixelated; }
  #status { font-size:12px; color:#9a9aa4; margin-left:auto; }
  #help { font-size:11px; color:#75757e; padding:8px 14px; border-top:1px solid #2a2a30; }
  input[type=range] { width:110px; }
  .miniBtn { background:none; border:1px solid #3a3a42; color:#9a9aa4; border-radius:4px; padding:2px 8px; font-size:11px; cursor:pointer; }
</style>
</head>
<body>
  <div id="sidebar">
    <h2>Images <button class="miniBtn" id="refreshBtn">Refresh</button></h2>
    <div id="stemList"></div>
  </div>
  <div id="main">
    <div id="toolbar">
      <button class="btn" data-cls="1"><span class="swatch" style="background:rgb(255,0,0)"></span>Heart (1)</button>
      <button class="btn" data-cls="2"><span class="swatch" style="background:rgb(0,0,255)"></span>Head (2)</button>
      <button class="btn" data-cls="3"><span class="swatch" style="background:rgb(0,255,0)"></span>Life (3)</button>
      <button class="btn" data-cls="0"><span class="swatch" style="background:#444"></span>Eraser (0)</button>
      <label style="font-size:12px;">brush <input type="range" id="brush" min="1" max="30" value="5"><span id="brushVal">5</span></label>
      <button class="btn" id="undoBtn">Undo (Ctrl+Z)</button>
      <button class="btn" id="resetBtn">Reset</button>
      <button class="btn" id="viewBtn">Toggle overlay (V)</button>
      <button class="btn" id="saveBtn" style="background:#2d5b3a;">Save (S)</button>
      <button class="btn" id="approveBtn" style="background:#2d5b3a;">Approve, no edits (A)</button>
      <button class="btn" id="rejectBtn" style="background:#5b2d2d;">Reject (X)</button>
      <span id="status"></span>
    </div>
    <div id="canvas-wrap">
      <div id="stage">
        <canvas id="photoCanvas"></canvas>
        <canvas id="maskCanvas"></canvas>
        <canvas id="drawCanvas"></canvas>
      </div>
    </div>
    <div id="help">right-click: eraser&rarr;heart&rarr;head&rarr;life&rarr;save+next &middot; 1/2/3 class &middot; 0/E eraser &middot; [ ] brush size &middot; Ctrl+Z undo &middot; S save &middot; A approve &middot; X reject &middot; N/&rarr; next &middot; P/&larr; prev &middot; V toggle overlay</div>
  </div>
<script>
(async function() {
  const CLASS_COLORS = {0:[0,0,0],1:[255,0,0],2:[0,0,255],3:[0,255,0]};
  const DISPLAY_SIZE = 700;

  let items = [];
  let curIndex = -1;
  let curStem = null;
  let curClass = 1;
  let brush = 5;
  let overlayVisible = true;
  let drawing = false;
  let lastPt = null;
  let undoStack = [];
  let dirty = false;

  const photoCanvas = document.getElementById('photoCanvas');
  const maskCanvas = document.getElementById('maskCanvas');
  const drawCanvas = document.getElementById('drawCanvas');
  const stage = document.getElementById('stage');
  const statusEl = document.getElementById('status');

  const pctx = photoCanvas.getContext('2d');
  const mctx = maskCanvas.getContext('2d', {willReadFrequently: true});
  const dctx = drawCanvas.getContext('2d');

  function setStatus(s) { statusEl.textContent = s; }

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = url;
    });
  }

  function statusClass(item) {
    if (item.status === 'rejected') return 'rejected';
    if (item.status === 'edited' || item.status === 'approved') return 'approved';
    return (item.pass_filter === 'True') ? 'pending-pass' : 'pending-fail';
  }

  function renderList() {
    const el = document.getElementById('stemList');
    el.innerHTML = '';
    items.forEach((item, i) => {
      const div = document.createElement('div');
      div.className = 'stem-item' + (i === curIndex ? ' active' : '');
      div.innerHTML = `<span class="dot ${statusClass(item)}"></span>${item.stem}`;
      div.onclick = () => loadStem(i);
      el.appendChild(div);
    });
  }

  function composite() {
    dctx.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
    dctx.drawImage(photoCanvas, 0, 0);
    if (overlayVisible) {
      dctx.globalAlpha = 0.55;
      dctx.drawImage(maskCanvas, 0, 0);
      dctx.globalAlpha = 1.0;
    }
  }

  function pushUndo() {
    undoStack.push(mctx.getImageData(0, 0, maskCanvas.width, maskCanvas.height));
    if (undoStack.length > 25) undoStack.shift();
  }

  function undo() {
    if (!undoStack.length) return;
    mctx.putImageData(undoStack.pop(), 0, 0);
    dirty = true;
    composite();
  }

  async function fetchStemAssets(stem) {
    const [img, mimg] = await Promise.all([
      loadImage(`/image/${stem}.png`),
      loadImage(`/mask/${stem}.png?t=${Date.now()}`),
    ]);
    return {img, mimg};
  }

  function applyAssets(img, mimg) {
    [photoCanvas, maskCanvas, drawCanvas].forEach(c => {
      c.width = img.width; c.height = img.height;
      c.style.width = DISPLAY_SIZE + 'px'; c.style.height = DISPLAY_SIZE + 'px';
    });
    stage.style.width = DISPLAY_SIZE + 'px';
    stage.style.height = DISPLAY_SIZE + 'px';
    pctx.clearRect(0, 0, photoCanvas.width, photoCanvas.height);
    pctx.drawImage(img, 0, 0);
    mctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
    mctx.drawImage(mimg, 0, 0);
    composite();
  }

  async function reloadCurrent() {
    if (!curStem) return;
    const {img, mimg} = await fetchStemAssets(curStem);
    applyAssets(img, mimg);
    undoStack = [];
    dirty = false;
    selectClass(0);
    setStatus(`reset ${curStem}`);
  }

  async function loadStem(i) {
    if (i < 0 || i >= items.length) return;
    if (dirty) await saveCurrent('edited');
    curIndex = i;
    curStem = items[i].stem;
    undoStack = [];
    dirty = false;
    const {img, mimg} = await fetchStemAssets(curStem);
    applyAssets(img, mimg);
    selectClass(0);
    renderList();
    setStatus(`${curStem}  (${i + 1}/${items.length})`);
  }

  function canvasPoint(evt) {
    const rect = drawCanvas.getBoundingClientRect();
    const x = (evt.clientX - rect.left) / rect.width * maskCanvas.width;
    const y = (evt.clientY - rect.top) / rect.height * maskCanvas.height;
    return [x, y];
  }

  function strokeTo(x0, y0, x1, y1, cls) {
    mctx.save();
    mctx.lineWidth = brush * 2;
    mctx.lineCap = 'round';
    mctx.lineJoin = 'round';
    mctx.beginPath();
    mctx.moveTo(x0, y0);
    mctx.lineTo(x1, y1);
    if (cls === 0) {
      mctx.globalCompositeOperation = 'destination-out';
      mctx.strokeStyle = 'rgba(0,0,0,1)';
    } else {
      mctx.globalCompositeOperation = 'source-over';
      const c = CLASS_COLORS[cls];
      mctx.strokeStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
    }
    mctx.stroke();
    mctx.restore();
  }

  drawCanvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || !curStem) return;
    pushUndo();
    drawing = true;
    lastPt = canvasPoint(e);
    strokeTo(lastPt[0], lastPt[1], lastPt[0] + 0.01, lastPt[1] + 0.01, curClass);
    dirty = true;
    composite();
  });
  window.addEventListener('mousemove', (e) => {
    if (!drawing) return;
    const pt = canvasPoint(e);
    strokeTo(lastPt[0], lastPt[1], pt[0], pt[1], curClass);
    lastPt = pt;
    composite();
  });
  window.addEventListener('mouseup', () => { drawing = false; lastPt = null; });

  // Fast review workflow: right-click steps eraser -> heart -> head -> life,
  // and a right-click while on life saves + advances to the next image
  // (which resets back to eraser). Left-click always just paints.
  const CYCLE = [0, 1, 2, 3];
  let cycleIndex = 0;

  drawCanvas.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    if (!curStem) return;
    if (cycleIndex < CYCLE.length - 1) {
      selectClass(CYCLE[cycleIndex + 1]);
    } else {
      saveCurrent('edited').then(() => loadStem(Math.min(curIndex + 1, items.length - 1)));
    }
  });

  function selectClass(c) {
    curClass = c;
    cycleIndex = CYCLE.indexOf(c);
    document.querySelectorAll('[data-cls]').forEach(b => b.classList.toggle('active', +b.dataset.cls === c));
  }
  document.querySelectorAll('[data-cls]').forEach(b => b.onclick = () => selectClass(+b.dataset.cls));

  document.getElementById('brush').oninput = (e) => {
    brush = +e.target.value;
    document.getElementById('brushVal').textContent = brush;
  };

  async function saveCurrent(status) {
    if (!curStem) return;
    const b64 = maskCanvas.toDataURL('image/png').split(',')[1];
    await fetchJSON(`/api/save/${curStem}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mask_png_base64: b64, status}),
    });
    dirty = false;
    if (items[curIndex]) items[curIndex].status = status;
    renderList();
    setStatus(`saved ${curStem} as ${status}`);
  }

  async function rejectCurrent() {
    if (!curStem) return;
    await fetchJSON(`/api/status/${curStem}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: 'rejected'}),
    });
    dirty = false;
    if (items[curIndex]) items[curIndex].status = 'rejected';
    renderList();
    await loadStem(Math.min(curIndex + 1, items.length - 1));
  }

  document.getElementById('undoBtn').onclick = undo;
  document.getElementById('resetBtn').onclick = reloadCurrent;
  document.getElementById('viewBtn').onclick = () => { overlayVisible = !overlayVisible; composite(); };
  document.getElementById('saveBtn').onclick = () => saveCurrent('edited').then(() => loadStem(Math.min(curIndex + 1, items.length - 1)));
  document.getElementById('approveBtn').onclick = () => saveCurrent('approved').then(() => loadStem(Math.min(curIndex + 1, items.length - 1)));
  document.getElementById('rejectBtn').onclick = rejectCurrent;
  document.getElementById('refreshBtn').onclick = async () => {
    const data = await fetchJSON('/api/list');
    const before = curStem;
    items = data.items;
    curIndex = items.findIndex(it => it.stem === before);
    renderList();
    setStatus(`list refreshed (${items.length} images)`);
  };

  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === '1') selectClass(1);
    else if (e.key === '2') selectClass(2);
    else if (e.key === '3') selectClass(3);
    else if (e.key === '0' || e.key.toLowerCase() === 'e') selectClass(0);
    else if (e.key === '[') { brush = Math.max(1, brush - 1); document.getElementById('brush').value = brush; document.getElementById('brushVal').textContent = brush; }
    else if (e.key === ']') { brush = Math.min(30, brush + 1); document.getElementById('brush').value = brush; document.getElementById('brushVal').textContent = brush; }
    else if (e.ctrlKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    else if (e.key.toLowerCase() === 's') { e.preventDefault(); saveCurrent('edited').then(() => loadStem(Math.min(curIndex + 1, items.length - 1))); }
    else if (e.key.toLowerCase() === 'a') { saveCurrent('approved').then(() => loadStem(Math.min(curIndex + 1, items.length - 1))); }
    else if (e.key.toLowerCase() === 'x') { rejectCurrent(); }
    else if (e.key.toLowerCase() === 'n' || e.key === 'ArrowRight') { loadStem(Math.min(curIndex + 1, items.length - 1)); }
    else if (e.key.toLowerCase() === 'p' || e.key === 'ArrowLeft') { loadStem(Math.max(curIndex - 1, 0)); }
    else if (e.key.toLowerCase() === 'v') { overlayVisible = !overlayVisible; composite(); }
  });

  selectClass(0);
  const data = await fetchJSON('/api/list');
  items = data.items;
  renderList();
  if (items.length) {
    const firstUnreviewed = items.findIndex(it => !it.status);
    await loadStem(firstUnreviewed >= 0 ? firstUnreviewed : 0);
  } else {
    setStatus('no images found -- is generate_pseudo_labels.py done writing any yet?');
  }
})();
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    data_dir: Path = None

    def log_message(self, fmt, *args):  # keep console quiet
        pass

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status: int = 200) -> None:
        self._send_bytes(json.dumps(obj).encode("utf-8"), "application/json", status)

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        path = unquote(urlparse(self.path).path)
        data_dir = self.data_dir

        if path in ("/", "/index.html"):
            self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/list":
            manifest = load_manifest(data_dir)
            reviewed = load_reviewed(data_dir)
            stems = sorted(p.stem for p in (data_dir / "images").glob("*.png"))
            items = [
                {
                    "stem": s,
                    "pass_filter": manifest.get(s, {}).get("pass_filter", ""),
                    "status": reviewed.get(s, {}).get("status", ""),
                }
                for s in stems
            ]
            self._send_json({"items": items})
            return

        if path.startswith("/image/"):
            stem = path[len("/image/") :]
            if stem.endswith(".png"):
                stem = stem[: -len(".png")]
            fp = data_dir / "images" / f"{stem}.png"
            if not fp.exists():
                self.send_error(404)
                return
            self._send_bytes(fp.read_bytes(), "image/png")
            return

        if path.startswith("/mask/"):
            stem = path[len("/mask/") :]
            if stem.endswith(".png"):
                stem = stem[: -len(".png")]
            mask_fp = data_dir / "masks" / f"{stem}.png"
            if mask_fp.exists():
                mask = cv2.imread(str(mask_fp), cv2.IMREAD_GRAYSCALE)
            else:
                img = cv2.imread(str(data_dir / "images" / f"{stem}.png"))
                if img is None:
                    self.send_error(404)
                    return
                mask = np.zeros(img.shape[:2], dtype=np.uint8)
            bgra = class_index_to_bgra(mask)
            ok, buf = cv2.imencode(".png", bgra)
            self._send_bytes(buf.tobytes(), "image/png")
            return

        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib method name
        path = unquote(urlparse(self.path).path)
        data_dir = self.data_dir
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if path.startswith("/api/save/"):
            stem = path[len("/api/save/") :]
            payload = json.loads(body)
            png_bytes = base64.b64decode(payload["mask_png_base64"])
            bgra = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if bgra is None or bgra.shape[2] != 4:
                self._send_json({"ok": False, "error": "expected an RGBA PNG"}, status=400)
                return
            class_idx = bgra_to_class_index(bgra)
            (data_dir / "masks").mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(data_dir / "masks" / f"{stem}.png"), class_idx)
            mark_reviewed(data_dir, stem, payload.get("status", "edited"))
            self._send_json({"ok": True})
            return

        if path.startswith("/api/status/"):
            stem = path[len("/api/status/") :]
            payload = json.loads(body)
            mark_reviewed(data_dir, stem, payload["status"])
            self._send_json({"ok": True})
            return

        self.send_error(404)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", default="training_pack/data")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    if not (data_dir / "images").exists():
        raise SystemExit(f"no images/ under {data_dir} -- run generate_pseudo_labels.py first")
    (data_dir / "masks").mkdir(parents=True, exist_ok=True)

    Handler.data_dir = data_dir
    with Server((args.host, args.port), Handler) as httpd:
        url = f"http://{args.host}:{args.port}/"
        print(f"serving {data_dir.resolve()} at {url}")
        print("Ctrl+C to stop")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
