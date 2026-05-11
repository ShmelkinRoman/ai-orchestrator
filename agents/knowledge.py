import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# S1: ThreadedConnectionPool instead of single global connection
_pool = None
_pool_lock = threading.Lock()


def _ensure_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            import psycopg2.pool
            from config.settings import DATABASE_URL
            _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DATABASE_URL)
            return _pool
        except Exception as e:
            if os.getenv("KB_ENABLED", "false").lower() == "true":
                logger.warning("PostgreSQL pool init failed: %s", e)
            else:
                logger.debug("PostgreSQL pool init failed (KB_ENABLED=false): %s", e)
            return None


@contextmanager
def _conn_ctx(autocommit: bool = True):
    """Yield a pooled connection, return it on exit."""
    p = _ensure_pool()
    if p is None:
        yield None
        return
    conn = p.getconn()
    try:
        conn.autocommit = autocommit
        yield conn
    finally:
        p.putconn(conn)


def _vec(embedding: list[float]) -> str:
    return json.dumps(embedding)


def init_db() -> bool:
    with _conn_ctx() as conn:
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS code_chunks (
                        id          SERIAL PRIMARY KEY,
                        project_id  TEXT NOT NULL,
                        file_path   TEXT NOT NULL,
                        chunk_text  TEXT NOT NULL,
                        summary     TEXT,
                        embedding   vector(1536),
                        updated_at  TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS code_chunks_emb_idx
                    ON code_chunks USING hnsw (embedding vector_cosine_ops)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS project_context (
                        project_id      TEXT PRIMARY KEY,
                        repo_url        TEXT,
                        tech_stack      TEXT[],
                        readme_summary  TEXT,
                        components_md   TEXT,
                        updated_at      TIMESTAMP DEFAULT NOW()
                    )
                """)
            logger.info("Knowledge DB initialized")
            return True
        except Exception as e:
            logger.warning("Failed to init knowledge DB: %s", e)
            return False


def upsert_chunk(project_id: str, file_path: str, chunk_text: str,
                 embedding: list[float], summary: Optional[str] = None) -> bool:
    """Insert a single chunk. Prefer replace_file_chunks for full-file indexing."""
    with _conn_ctx() as conn:
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM code_chunks WHERE project_id=%s AND file_path=%s AND chunk_text=%s",
                    (project_id, file_path, chunk_text),
                )
                cur.execute(
                    """INSERT INTO code_chunks (project_id, file_path, chunk_text, summary, embedding, updated_at)
                       VALUES (%s, %s, %s, %s, %s::vector, NOW())""",
                    (project_id, file_path, chunk_text, summary, _vec(embedding)),
                )
            return True
        except Exception as e:
            logger.warning("upsert_chunk failed: %s", e)
            return False


def replace_file_chunks(project_id: str, file_path: str,
                        chunks: list[tuple[str, list[float]]]) -> int:
    """W4+W5: delete all old chunks for file and insert new ones atomically."""
    with _conn_ctx(autocommit=False) as conn:
        if not conn:
            return 0
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM code_chunks WHERE project_id=%s AND file_path=%s",
                    (project_id, file_path),
                )
                for chunk_text, embedding in chunks:
                    cur.execute(
                        """INSERT INTO code_chunks
                           (project_id, file_path, chunk_text, embedding, updated_at)
                           VALUES (%s, %s, %s, %s::vector, NOW())""",
                        (project_id, file_path, chunk_text, _vec(embedding)),
                    )
            conn.commit()
            return len(chunks)
        except Exception as e:
            conn.rollback()
            logger.warning("replace_file_chunks failed: %s", e)
            return 0


def search(project_id: str, query_embedding: list[float], limit: int = 8) -> list[dict]:
    with _conn_ctx() as conn:
        if not conn:
            return []
        try:
            vec = _vec(query_embedding)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT file_path, chunk_text, summary,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM code_chunks
                       WHERE project_id = %s
                       ORDER BY embedding <=> %s::vector
                       LIMIT %s""",
                    (vec, project_id, vec, limit),
                )
                return [
                    {"file_path": r[0], "chunk_text": r[1], "summary": r[2], "similarity": float(r[3])}
                    for r in cur.fetchall()
                ]
        except Exception as e:
            logger.warning("Knowledge search failed: %s", e)
            return []


def embed(text: str) -> list[float]:
    try:
        from config.settings import OPENROUTER_API_KEY
        resp = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": "openai/text-embedding-3-small", "input": text[:32000]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        logger.warning("Embedding request failed: %s", e)
        return []


def embed_batch(texts: list[str]) -> list[list[float]]:
    """S3: embed multiple texts in one API call. Returns [] on failure."""
    if not texts:
        return []
    try:
        from config.settings import OPENROUTER_API_KEY
        resp = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": "openai/text-embedding-3-small",
                  "input": [t[:32000] for t in texts]},
            timeout=60,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda x: x["index"])
        return [d["embedding"] for d in data]
    except Exception as e:
        logger.warning("Batch embedding failed: %s", e)
        return []


def search_knowledge(project_id: str, query: str, limit: int = 8) -> list[dict]:
    """High-level: embed query then search. Returns [] on any failure."""
    emb = embed(query)
    if not emb:
        return []
    return search(project_id, emb, limit)
