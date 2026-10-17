"""Hybrid search over manuals, SOPs, repair-report sections and notes: SQLite FTS5 (BM25, exact IDs/protocols)
fused with local-embedding cosine by reciprocal rank. Filters are applied inside the query, never after."""
import re

import numpy as np

from .tools import db, q

MODEL = "BAAI/bge-small-en-v1.5"
_model = None
_cache = {}  # chunk_id order + matrix, rebuilt when the embedded-chunk count changes


def _embedder():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL)
    return _model


def embed_missing(batch=256):
    rows = q("SELECT chunk_id, title, text FROM chunks WHERE embedding IS NULL")
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = list(_embedder().embed([f"{r['title']}\n{r['text']}"[:2000] for r in part]))
        db().executemany("UPDATE chunks SET embedding=? WHERE chunk_id=?",
                         [(np.asarray(v, dtype=np.float32).tobytes(), r["chunk_id"]) for v, r in zip(vecs, part)])
        db().commit()
    return len(rows)


def _matrix():
    n = db().execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    if _cache.get("n") != n:
        rows = db().execute("SELECT chunk_id, embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
        ids = [r[0] for r in rows]
        m = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 384), np.float32)
        _cache.update(n=n, ids=ids, pos={c: i for i, c in enumerate(ids)}, m=m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9))
    return _cache


def search(query, k=6, doc_type=None, asset_id=None, well_type=None):
    """Top-k chunks with their ids as evidence. well_type also matches well-agnostic docs (SOPs have well_type NULL)."""
    where, args = [], []
    for col, val in (("doc_type", doc_type), ("asset_id", asset_id)):
        if val:
            where.append(f"c.{col}=?")
            args.append(val)
    if well_type:
        where.append("(c.well_type=? OR c.well_type IS NULL)")
        args.append(well_type)
    cond = (" AND " + " AND ".join(where)) if where else ""
    terms = re.findall(r"[\w\-]+", query)
    bm25 = []
    if terms:
        match = " OR ".join(f'"{t}"' for t in terms)
        bm25 = [r["chunk_id"] for r in q(
            f"""SELECT f.chunk_id FROM chunks_fts f JOIN chunks c USING (chunk_id) WHERE chunks_fts MATCH ?{cond}
                ORDER BY bm25(chunks_fts) LIMIT 30""", match, *args)]
    vec = []
    c = _matrix()
    if len(c["ids"]):
        allowed = None
        if where:
            allowed = {r["chunk_id"] for r in q(f"SELECT c.chunk_id FROM chunks c WHERE 1=1{cond}", *args)}
        qv = np.asarray(next(iter(_embedder().query_embed([query]))), dtype=np.float32)
        sims = c["m"] @ (qv / np.linalg.norm(qv))
        vec = [c["ids"][i] for i in np.argsort(-sims) if allowed is None or c["ids"][i] in allowed][:30]
    score = {}
    for ranking in (bm25, vec):
        for rank, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0) + 1 / (60 + rank)
    top = sorted(score, key=score.get, reverse=True)[:k]
    rows = [dict(r) for cid in top for r in db().execute(
        "SELECT chunk_id, doc_type, ref_id, asset_id, well_type, title, text FROM chunks WHERE chunk_id=?", (cid,))]
    return {"rows": rows, "evidence": [r["chunk_id"] for r in rows], "visual": "text"}


if __name__ == "__main__":
    print("embedded", embed_missing())
