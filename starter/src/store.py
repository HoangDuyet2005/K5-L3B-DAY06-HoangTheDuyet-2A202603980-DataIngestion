"""PostgreSQL + pgvector storage: stable IDs, idempotent upsert, exact cosine search, SQL filters."""
from __future__ import annotations

import math
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .config import FILTERABLE_FIELDS, TABLE_NAME
from .models import Chunk

_COLUMNS = ("chunk_id", "strategy", "document_id", "source", "pdf_page", "printed_page", "section",
            "segment_index", "chunk_index", "char_start", "char_end", "text", "content_hash",
            "embedding_model", "embedding", "metadata")
_RESULT_COLUMNS = ("chunk_id", "strategy", "document_id", "source", "pdf_page", "printed_page", "section",
                   "segment_index", "chunk_index", "char_start", "char_end", "text", "metadata")


def _vector_literal(vector: list[float], dimensions: int) -> str:
    if len(vector) != dimensions:
        raise ValueError(f"vector has {len(vector)} dimensions, expected {dimensions}")
    if not all(math.isfinite(x) for x in vector):
        raise ValueError("vector contains NaN/inf")
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError(f"invalid dimensions: {dimensions!r}")
        self.dimensions = dimensions
        self.table = sql.Identifier(TABLE_NAME)
        self.conn = psycopg.connect(database_url, connect_timeout=10)

    def close(self) -> None:
        self.conn.close()

    def pgvector_version(self) -> str:
        row = self.conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
        self.conn.commit()
        if not row:
            raise SystemExit("pgvector extension missing; see starter/README.md (init.sql).")
        return row[0]

    def create_schema(self) -> None:
        """Create the chunk table once; refuse to reuse a table built for another dimension."""
        self.pgvector_version()
        with self.conn.transaction():
            self.conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {t} (
                    chunk_id        text PRIMARY KEY,
                    strategy        text NOT NULL,
                    document_id     text NOT NULL,
                    source          text NOT NULL,
                    pdf_page        integer NOT NULL,
                    printed_page    integer NOT NULL,
                    section         text NOT NULL,
                    segment_index   integer NOT NULL,
                    chunk_index     integer NOT NULL,
                    char_start      integer NOT NULL,
                    char_end        integer NOT NULL,
                    text            text NOT NULL,
                    content_hash    text NOT NULL,
                    embedding_model text NOT NULL,
                    embedding       vector({dims}) NOT NULL,
                    metadata        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at      timestamptz NOT NULL DEFAULT now()
                )""").format(t=self.table, dims=sql.SQL(str(int(self.dimensions)))))
            self.conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} (strategy, document_id, section)")
                              .format(i=sql.Identifier(f"{TABLE_NAME}_strategy_section_idx"), t=self.table))
            row = self.conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = to_regclass(%s) AND attname = 'embedding'", (TABLE_NAME,)).fetchone()
        self.conn.commit()
        expected = f"vector({self.dimensions})"
        if not row or row[0] != expected:
            raise SystemExit(f"Table {TABLE_NAME} embedding column is {row[0] if row else None}, expected {expected}.")

    def existing_hashes(self, strategy: str, document_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            sql.SQL("SELECT chunk_id, content_hash FROM {t} WHERE strategy = %s AND document_id = %s")
            .format(t=self.table), (strategy, document_id)).fetchall()
        self.conn.commit()
        return dict(rows)

    def sync(self, strategy: str, document_id: str, all_chunk_ids: list[str], changed: list[Chunk],
             vectors: list[list[float]], hashes: dict[str, str], model_id: str) -> dict[str, int]:
        """In one transaction: upsert changed chunks, then delete chunks no longer produced."""
        if len(changed) != len(vectors):
            raise ValueError(f"{len(changed)} chunks but {len(vectors)} vectors")
        if len(set(all_chunk_ids)) != len(all_chunk_ids):
            raise ValueError("duplicate chunk IDs in one strategy")
        insert = sql.SQL("""
            INSERT INTO {t} ({cols}) VALUES ({vals})
            ON CONFLICT (chunk_id) DO UPDATE SET {updates}, updated_at = now()
        """).format(
            t=self.table,
            cols=sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
            vals=sql.SQL(", ").join(sql.SQL("%s::vector") if c == "embedding" else sql.Placeholder()
                                    for c in _COLUMNS),
            updates=sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
                                       for c in _COLUMNS if c != "chunk_id"))
        rows = []
        for chunk, vector in zip(changed, vectors):
            if chunk.metadata["strategy"] != strategy or chunk.document_id != document_id:
                raise ValueError(f"chunk {chunk.chunk_id} does not belong to {strategy}/{document_id}")
            m = chunk.metadata
            rows.append((chunk.chunk_id, strategy, chunk.document_id, chunk.source, chunk.page,
                         m["printed_page"], m["section"], m["segment_index"], m["chunk_index"],
                         m["char_start"], m["char_end"], chunk.text, hashes[chunk.chunk_id], model_id,
                         _vector_literal(vector, self.dimensions), Jsonb(m)))
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                if rows:
                    cursor.executemany(insert, rows)
                cursor.execute(
                    sql.SQL("DELETE FROM {t} WHERE strategy = %s AND document_id = %s "
                            "AND NOT (chunk_id = ANY(%s))").format(t=self.table),
                    (strategy, document_id, all_chunk_ids))
                deleted = cursor.rowcount
        self.conn.commit()
        return {"upserted": len(rows), "deleted_obsolete": deleted}

    def counts(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(sql.SQL(
            "SELECT strategy, embedding_model, count(*), count(DISTINCT chunk_id), count(DISTINCT content_hash) "
            "FROM {t} GROUP BY strategy, embedding_model ORDER BY strategy").format(t=self.table)).fetchall()
        self.conn.commit()
        return [{"strategy": r[0], "embedding_model": r[1], "rows": r[2], "distinct_ids": r[3],
                 "distinct_hashes": r[4]} for r in rows]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine-distance search (no ANN index) within one stored strategy.

        Filter keys are whitelisted column names; values are bound parameters.
        score = 1 - cosine distance.
        """
        conditions = [sql.SQL("strategy = %s")]
        params: list[Any] = [strategy]
        for key, value in (filters or {}).items():
            column = FILTERABLE_FIELDS.get(key)
            if column is None:
                raise ValueError(f"filter key {key!r} not allowed; allowed: {sorted(FILTERABLE_FIELDS)}")
            conditions.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            params.append(value)
        query = sql.SQL("SELECT {cols}, embedding <=> %s::vector AS distance FROM {t} WHERE {where} "
                        "ORDER BY distance, chunk_id LIMIT %s").format(
            cols=sql.SQL(", ").join(map(sql.Identifier, _RESULT_COLUMNS)),
            t=self.table, where=sql.SQL(" AND ").join(conditions))
        rows = self.conn.execute(query, [_vector_literal(query_vector, self.dimensions), *params, top_k]).fetchall()
        self.conn.commit()
        results = []
        for row in rows:
            record = dict(zip(_RESULT_COLUMNS + ("distance",), row))
            record["distance"] = float(record["distance"])
            record["score"] = 1.0 - record["distance"]
            results.append(record)
        return results
