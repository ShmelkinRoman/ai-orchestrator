import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_conn = None


def _get_conn():
    global _conn
    if _conn is not None:
        try:
            with _conn.cursor() as cur:
                cur.execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None

    try:
        import psycopg2
        from config.settings import DATABASE_URL
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = True
        return _conn
    except Exception as e:
        import os
        if os.getenv("KB_ENABLED", "false").lower() == "true":
            logger.warning("PostgreSQL unavailable: %s", e)
        else:
            logger.debug("PostgreSQL unavailable (KB_ENABLED=false): %s", e)
        return None


def _vec(embedding: list[float]) -> str:
    return json.dumps(embedding)


def init_db() -> bool:
    conn = _get_conn()
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
    conn = _get_conn()
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


def search(project_id: str, query_embedding: list[float], limit: int = 8) -> list[dict]:
    conn = _get_conn()
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


def search_knowledge(project_id: str, query: str, limit: int = 8) -> list[dict]:
    """High-level: embed query then search. Returns [] on any failure."""
    emb = embed(query)
    if not emb:
        return []
    return search(project_id, emb, limit)
