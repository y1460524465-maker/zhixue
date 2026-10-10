"""课本 / 题目向量库的检索底座。

架构图里"课本向量库""题目向量库"指向 Milvus。这里做成一主一备：

* :class:`MilvusVectorStore` —— 主路径，BGE-M3 向量 + Milvus 语义检索；
* :class:`KeywordIndex`      —— 备路径，BM25 关键词检索（无需 Milvus / 不需要 GPU）。

:class:`KnowledgeRetriever` 对外只暴露一个 ``search``，
调用方不用关心当前跑在哪条路径上，检索结果里会带 ``backend`` 字段说明来源。
"""

from __future__ import annotations

import re
import threading
from typing import Any, Iterable, Sequence

from zhixue.config import Settings, get_settings
from zhixue.logging_setup import get_logger
from zhixue.store import MySQL, get_mysql

logger = get_logger("vector")

BGE_M3_DIM = 1024

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """中英文混合分词。

    中文按“字 + 相邻双字”切分，能在不引入分词模型的前提下拿到
    接近 BM25 的效果；英文按标识符整体保留。
    """
    tokens = _TOKEN_RE.findall(text or "")
    chinese = [t for t in tokens if "\u4e00" <= t <= "\u9fff"]
    bigrams = [chinese[i] + chinese[i + 1] for i in range(len(chinese) - 1)]
    return [t.lower() for t in tokens] + bigrams


def _try_jieba(text: str) -> list[str] | None:
    try:
        import jieba  # type: ignore
    except Exception:
        return None
    return [w for w in jieba.lcut(text or "") if w.strip()]


# --------------------------------------------------------------------------- #
# 向量：BGE-M3
# --------------------------------------------------------------------------- #
class Embedder:
    """懒加载的 BGE-M3 编码器。加载失败就整体降级。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._model: Any = None
        self._failed = False
        self._lock = threading.Lock()

    @property
    def model(self) -> Any:
        if self._model is None and not self._failed:
            with self._lock:
                if self._model is None and not self._failed:
                    try:
                        from sentence_transformers import SentenceTransformer

                        self._model = SentenceTransformer(
                            self.settings.embedding_model_path, device="cpu"
                        )
                        logger.info("BGE-M3 加载完成: %s", self.settings.embedding_model_path)
                    except Exception as exc:
                        self._failed = True
                        logger.warning("BGE-M3 不可用(%s)，向量检索将降级为关键词检索", exc)
        return self._model

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def loaded(self) -> bool:
        """不触发加载的状态查询。"""
        return self._model is not None

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def dim(self) -> int:
        if self.model is None:
            return BGE_M3_DIM
        try:
            return int(self.model.get_sentence_embedding_dimension())
        except Exception:
            return BGE_M3_DIM

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self.model is None:
            raise RuntimeError("BGE-M3 未加载")
        vectors = self.model.encode(
            list(texts), normalize_embeddings=True, batch_size=8, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]


# --------------------------------------------------------------------------- #
# Milvus
# --------------------------------------------------------------------------- #
class MilvusVectorStore:
    """Milvus 语义检索。连不上或没装 pymilvus 时 ``available`` 为 False。"""

    def __init__(self, settings: Settings | None = None, embedder: Embedder | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or Embedder(self.settings)
        self._client: Any = None
        self._checked = False
        # Milvus 不在时不要卡住主流程：连接与检索都给短超时
        self._timeout = float(getattr(self.settings, "milvus_timeout", 3.0))

    @property
    def client(self) -> Any:
        if self._client is None and not self._checked:
            self._checked = True
            try:
                from pymilvus import MilvusClient

                uri = f"http://{self.settings.milvus_host}:{self.settings.milvus_port}"
                client = MilvusClient(uri=uri, timeout=self._timeout)
                client.list_collections()
                self._client = client
                logger.info("Milvus 连接成功: %s", uri)
            except Exception as exc:
                logger.warning("Milvus 不可用(%s)，向量检索将降级为关键词检索", exc)
        return self._client

    @property
    def available(self) -> bool:
        return self.client is not None and self.embedder.available

    def ensure_collection(self, name: str, drop: bool = False) -> bool:
        if self.client is None:
            return False
        try:
            if drop and self.client.has_collection(name):
                self.client.drop_collection(name)
            if not self.client.has_collection(name):
                self.client.create_collection(
                    collection_name=name,
                    dimension=self.embedder.dim,
                    metric_type="COSINE",
                    auto_id=False,
                    enable_dynamic_field=True,
                )
                logger.info("创建 Milvus collection: %s", name)
            return True
        except Exception as exc:
            logger.warning("创建 collection %s 失败: %s", name, exc)
            return False

    def index(self, name: str, records: list[dict[str, Any]], drop: bool = False) -> int:
        """把 ``records`` 写进向量库；每条至少要有 ``id`` 和 ``text``。"""
        if not self.available or not self.ensure_collection(name, drop=drop):
            return 0
        try:
            vectors = self.embedder.encode([r["text"] for r in records])
            payload = [
                {"id": r["id"], "vector": vec, **{k: v for k, v in r.items() if k not in ("id", "text")}}
                for r, vec in zip(records, vectors)
            ]
            self.client.insert(collection_name=name, data=payload)
            logger.info("写入 Milvus %s: %d 条", name, len(payload))
            return len(payload)
        except Exception as exc:
            logger.warning("写入 Milvus 失败: %s", exc)
            return 0

    def search(
        self, name: str, query: str, k: int = 5, subject: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.available or not self.client.has_collection(name):
            return []
        try:
            vector = self.embedder.encode([query])[0]
            expr = f'subject == "{subject}"' if subject else None
            hits = self.client.search(
                collection_name=name,
                data=[vector],
                limit=k,
                output_fields=["text", "title", "subject", "kp_id", "chapter", "source"],
                filter=expr,
            )
        except Exception as exc:
            logger.warning("Milvus 检索失败: %s", exc)
            return []

        results: list[dict[str, Any]] = []
        for hit in (hits[0] if hits else []):
            entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
            results.append(
                {
                    "id": hit.get("id"),
                    "score": float(hit.get("distance", 0.0)),
                    "text": entity.get("text", ""),
                    "title": entity.get("title", ""),
                    "subject": entity.get("subject", ""),
                    "kp_id": entity.get("kp_id", ""),
                    "chapter": entity.get("chapter", ""),
                    "source": entity.get("source", ""),
                    "backend": "milvus",
                }
            )
        return results


# --------------------------------------------------------------------------- #
# 关键词检索（BM25）
# --------------------------------------------------------------------------- #
class KeywordIndex:
    """基于 rank_bm25 的关键词索引，数据源是 MySQL。"""

    def __init__(self, mysql: MySQL | None = None) -> None:
        self.mysql = mysql or get_mysql()
        self._cache: dict[str, dict[str, Any]] = {}
        # RLock：_bm25 会在持锁时调用会再次加锁的 _rows
        self._lock = threading.RLock()

    def _rows(self, table: str) -> list[dict[str, Any]]:
        with self._lock:
            if table not in self._cache:
                try:
                    rows = self.mysql.query(f"SELECT * FROM `{table}`")
                except Exception as exc:
                    logger.warning("读取 %s 失败: %s", table, exc)
                    rows = []
                self._cache[table] = {"rows": rows, "index": None}
            return self._cache[table]["rows"]

    def refresh(self, table: str | None = None) -> None:
        with self._lock:
            if table:
                self._cache.pop(table, None)
            else:
                self._cache.clear()

    def _bm25(self, table: str):
        from rank_bm25 import BM25Okapi

        with self._lock:
            entry = self._cache.get(table)
        if entry is None:
            entry = {"rows": self._rows(table), "index": None}
            with self._lock:
                entry = self._cache.setdefault(table, entry)
        if entry["index"] is None and entry["rows"]:
            with self._lock:
                if entry["index"] is None:
                    corpus = [tokenize(self._search_text(table, row)) for row in entry["rows"]]
                    entry["index"] = BM25Okapi(corpus)
        return entry["rows"], entry["index"]

    @staticmethod
    def _search_text(table: str, row: dict[str, Any]) -> str:
        if table == "textbook_chunk":
            return f"{row.get('title', '')} {row.get('chapter', '')} {row.get('content', '')}"
        return f"{row.get('stem', '')} {row.get('answer', '')} {row.get('analysis', '')}"

    def search(
        self,
        table: str,
        query: str,
        k: int = 5,
        subject: str | None = None,
        kp_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows, index = self._bm25(table)
        if not rows or index is None:
            return []
        tokens = _try_jieba(query) or tokenize(query)
        scores = index.get_scores(tokens)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results: list[dict[str, Any]] = []
        for idx in order:
            row = rows[idx]
            if subject and row.get("subject") != subject:
                continue
            if kp_id and row.get("kp_id") != kp_id:
                continue
            results.append(
                {
                    "id": row.get("chunk_id") or row.get("q_id"),
                    "score": float(scores[idx]),
                    "text": self._search_text(table, row),
                    "title": row.get("title") or row.get("stem", ""),
                    "subject": row.get("subject", ""),
                    "kp_id": row.get("kp_id", ""),
                    "chapter": row.get("chapter", ""),
                    "source": row.get("source", ""),
                    "backend": "keyword",
                    "_row": row,
                }
            )
            if len(results) >= k:
                break
        return results


# --------------------------------------------------------------------------- #
# 对外统一入口
# --------------------------------------------------------------------------- #
class KnowledgeRetriever:
    """课本 / 题库检索。优先 Milvus，失败自动降级 BM25。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.mysql = get_mysql()
        self.embedder = Embedder(self.settings)
        self.milvus = MilvusVectorStore(self.settings, self.embedder)
        self.keyword = KeywordIndex(self.mysql)

    @property
    def backend(self) -> str:
        return "milvus" if self.milvus.available else "keyword"

    # -- 建索引 ------------------------------------------------------------ #
    def index_textbook(self, drop: bool = False) -> int:
        rows = self.mysql.query(
            "SELECT chunk_id, title, chapter, content, subject, kp_id, source FROM textbook_chunk"
        )
        records = [
            {
                "id": r["chunk_id"],
                "text": f"{r['title']} {r['chapter'] or ''} {r['content']}",
                "title": r["title"],
                "chapter": r["chapter"] or "",
                "subject": r["subject"],
                "kp_id": r["kp_id"] or "",
                "source": r["source"] or "",
            }
            for r in rows
        ]
        return self.milvus.index(self.settings.textbook_collection, records, drop=drop)

    def index_questions(self, drop: bool = False) -> int:
        rows = self.mysql.query(
            "SELECT q_id, stem, answer, analysis, subject, kp_id, source FROM question_bank"
        )
        records = [
            {
                "id": r["q_id"],
                "text": f"{r['stem']} {r['answer']} {r['analysis'] or ''}",
                "title": r["stem"][:120],
                "chapter": "",
                "subject": r["subject"],
                "kp_id": r["kp_id"],
                "source": r["source"] or "",
            }
            for r in rows
        ]
        return self.milvus.index(self.settings.question_collection, records, drop=drop)

    def rebuild(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "textbook": self.index_textbook(drop=True),
            "question": self.index_questions(drop=True),
        }

    # -- 检索 -------------------------------------------------------------- #
    def search_textbook(
        self, query: str, k: int = 5, subject: str | None = None
    ) -> list[dict[str, Any]]:
        hits = self.milvus.search(self.settings.textbook_collection, query, k=k, subject=subject)
        if hits:
            return hits
        return self.keyword.search("textbook_chunk", query, k=k, subject=subject)

    def search_questions(
        self,
        query: str,
        k: int = 5,
        subject: str | None = None,
        kp_id: str | None = None,
    ) -> list[dict[str, Any]]:
        hits = self.milvus.search(self.settings.question_collection, query, k=k, subject=subject)
        hits = [h for h in hits if not kp_id or h.get("kp_id") == kp_id]
        if hits:
            return hits
        return self.keyword.search("question_bank", query, k=k, subject=subject, kp_id=kp_id)

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "embedder_loaded": self.embedder.loaded,
            "embedder_failed": self.embedder.failed,
            "embedding_model": self.settings.embedding_model_path,
            "milvus": self.milvus.available,
            "milvus_uri": f"{self.settings.milvus_host}:{self.settings.milvus_port}",
            "collections": [
                self.settings.textbook_collection,
                self.settings.question_collection,
            ],
        }


_retriever: KnowledgeRetriever | None = None


def get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
    return _retriever


__all__ = [
    "Embedder",
    "MilvusVectorStore",
    "KeywordIndex",
    "KnowledgeRetriever",
    "get_retriever",
    "tokenize",
]
