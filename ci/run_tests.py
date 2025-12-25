#!/usr/bin/env python3
import os, time, random, json, pathlib, statistics
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

OUT = pathlib.Path("ci/out")
OUT.mkdir(parents=True, exist_ok=True)

# ---- Config via env (defaults work for your compose) ----
NET_BASE      = os.environ.get("NET_BASE", "")  # unused but handy if you pass base URLs
QDRANT_URL    = os.environ.get("QDRANT_URL", "http://qdrant:6333")
BACKEND_URL   = os.environ.get("BACKEND_URL", "http://backend:8000")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")

# Optional dataset (you already pull this via LFS)
DATASET_PATH  = os.environ.get("DATASET_PATH", "init_script/datasets/118k-answered.json")
N_QUERIES     = int(os.environ.get("N_QUERIES", "30"))  # how many random queries
TIMEOUT       = float(os.environ.get("TIMEOUT", "30"))

results = []

def ping(name, url, method="GET"):
    t0 = time.time()
    try:
        r = requests.request(method, url, timeout=TIMEOUT)
        ok = r.ok
    except Exception as e:
        ok = False
        r = None
    t1 = time.time()
    results.append({
        "kind": "ping",
        "service": name,
        "url": url,
        "ok": ok,
        "status": None if r is None else r.status_code,
        "ms": round((t1 - t0)*1000, 2),
        "query": None,
        "answer_len": None
    })
    return ok, r

def try_json(r):
    try:
        return r.json()
    except Exception:
        return None

# ---- 0) Smoke/regression pings (redundant to your shell smoke test, but logged for graphs) ----
ping("qdrant-root", f"{QDRANT_URL}/")
ping("backend-healthz", f"{BACKEND_URL}/healthz")
ping("open-webui-root", f"{OPENWEBUI_URL}/")

# ---- 1) Qdrant data sanity: collections + (optional) point counts ----
ok, r = ping("qdrant-collections", f"{QDRANT_URL}/collections")
collections = []
if ok and r is not None:
    data = try_json(r) or {}
    cols = data.get("result", {}).get("collections", [])
    collections = [c.get("name") for c in cols if isinstance(c, dict)]
    # Optionally check counts for up to a few collections
    for name in collections[:5]:
        okc, rc = ping(f"qdrant-count:{name}", f"{QDRANT_URL}/collections/{name}/points/count")
else:
    collections = []

# ---- 2) Build a query list from your dataset if present; otherwise use fallbacks ----
queries = []
dataset_found = False
try:
    if os.path.exists(DATASET_PATH):
        with open(DATASET_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Expecting a list of {"question": "...", "answer": "..."}; adapt if schema differs.
        pool = [d for d in data if isinstance(d, dict) and ("question" in d or "query" in d)]
        random.shuffle(pool)
        for d in pool[:max(N_QUERIES, 1)]:
            q = d.get("question") or d.get("query") or ""
            if q.strip():
                queries.append(q.strip())
        dataset_found = len(queries) > 0
except Exception:
    dataset_found = False

if not dataset_found:
    queries = [
        "What is Qdrant?",
        "Explain vector databases in one sentence.",
        "How to speed up retrieval with HNSW?",
        "What is embedding dimensionality?",
        "Benefits of RAG for documentation QA?",
        "What is cosine similarity?",
        "Tradeoffs: precision vs recall in search",
        "How to chunk long docs?",
        "What is FastAPI?",
        "What is uvicorn?"
    ] * max(1, N_QUERIES // 10)

# ---- 3) Query a backend endpoint (best effort) ----
# We’ll try a few common shapes; the script gracefully degrades if endpoints don’t exist.
def timed_get(url, params=None):
    t0 = time.time()
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        ok = r.ok
        js = try_json(r)
        text = ""
        if js and isinstance(js, dict):
            # heuristic: look for 'answer'/'result'/'output'
            for k in ("answer", "result", "output", "text"):
                if k in js and isinstance(js[k], str):
                    text = js[k]
                    break
        elif r and r.text:
            text = r.text[:500]
        ms = round((time.time() - t0)*1000, 2)
        return ok, r.status_code, ms, text
    except Exception:
        return False, None, round((time.time() - t0)*1000, 2), ""

def save_plot(fig, name):
    p = OUT / name
    fig.savefig(p, bbox_inches="tight", dpi=150)
    plt.close(fig)
    return str(p)

tested_any_queries = False

def record_query(service_name, url, q, ok, status, ms, ans):
    global results, tested_any_queries
    tested_any_queries = True
    results.append({
        "kind": "query",
        "service": service_name,
        "url": url,
        "ok": ok,
        "status": status,
        "ms": ms,
        "query": q,
        "answer_len": len(ans or "")
    })

# Try backend searchy endpoints in order
CANDIDATES = [
    ("backend-search", f"{BACKEND_URL}/search", "q"),
    ("backend-ask",    f"{BACKEND_URL}/ask",    "query"),
    ("backend-query",  f"{BACKEND_URL}/query",  "q"),
]

for q in queries:
    got_one = False
    for name, url, param in CANDIDATES:
        ok, status, ms, ans = timed_get(url, params={param: q})
        if status == 404:
            # endpoint doesn't exist; try next candidate
            continue
        record_query(name, url, q, ok, status, ms, ans)
        got_one = True
        break
    if not got_one:
        # Fall back to hitting backend root (still logs latency)
        ok, status, ms, ans = timed_get(BACKEND_URL, params=None)
        record_query("backend-root", BACKEND_URL, q, ok, status, ms, ans)

# ---- 4) Build DataFrame + graphs ----
df = pd.DataFrame(results)
df.to_csv(OUT / "results.csv", index=False)

# Success rate by service
svc = df.groupby("service")["ok"].mean().sort_values(ascending=False)
fig = plt.figure(figsize=(8,4.5))
svc.plot(kind="bar")
plt.title("Success Rate by Service")
plt.ylabel("Success ratio")
plt.ylim(0,1)
save_plot(fig, "success_rate_by_service.png")

# Latency (ms) by service (boxplot)
df_lat = df[df["ms"].notna()]
fig = plt.figure(figsize=(9,5))
df_lat.boxplot(column="ms", by="service", rot=45)
plt.title("Latency by Service (ms)")
plt.suptitle("")
plt.ylabel("ms")
save_plot(fig, "latency_by_service.png")

# Query-only latency histogram
df_q = df[df["kind"]=="query"]
if not df_q.empty:
    fig = plt.figure(figsize=(8,4.5))
    df_q["ms"].plot(kind="hist", bins=20)
    plt.title("Query Latency Distribution (ms)")
    plt.xlabel("ms")
    save_plot(fig, "query_latency_hist.png")

# Answer length vs latency scatter
if not df_q.empty:
    fig = plt.figure(figsize=(6,5))
    plt.scatter(df_q["answer_len"], df_q["ms"], alpha=0.5)
    plt.title("Answer Length vs Latency")
    plt.xlabel("answer length (chars)")
    plt.ylabel("ms")
    save_plot(fig, "answerlen_vs_latency.png")

# Simple HTML report
html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>CI Query Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 16px; }}
    h1, h2 {{ color: #333; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
    img {{ max-width: 100%; height: auto; border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #eee; padding: 6px 8px; text-align: left; }}
  </style>
</head>
<body>
  <h1>CI Query & Data Report</h1>
  <p><b>Collections seen in Qdrant:</b> {', '.join(collections) if collections else '(none detected or API unavailable)'}</p>
  <div class="grid">
    <div class="card"><h2>Success Rate</h2><img src="success_rate_by_service.png" /></div>
    <div class="card"><h2>Latency by Service</h2><img src="latency_by_service.png" /></div>
    <div class="card"><h2>Query Latency Histogram</h2><img src="query_latency_hist.png" /></div>
    <div class="card"><h2>Answer Length vs Latency</h2><img src="answerlen_vs_latency.png" /></div>
  </div>
  <h2>Raw Results (first 50)</h2>
  <table>
    <thead><tr><th>kind</th><th>service</th><th>status</th><th>ok</th><th>ms</th><th>query</th><th>answer_len</th></tr></thead>
    <tbody>
      {"".join(f"<tr><td>{row.kind}</td><td>{row.service}</td><td>{row.status}</td><td>{row.ok}</td><td>{row.ms}</td><td>{(row.query or '')[:80]}</td><td>{row.answer_len}</td></tr>" for row in df.head(50).itertuples())}
    </tbody>
  </table>
  <p>Dataset used: {"Yes" if dataset_found else "No (fallback queries)"} | N queries attempted: {len(df_q)}</p>
</body>
</html>
"""
(OUT / "report.html").write_text(html, encoding="utf-8")

print(f"Wrote artifacts to {OUT}")
