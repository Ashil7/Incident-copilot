"""Secure runbook storage, extraction, chunking, indexing, and exact retrieval."""

import codecs
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import delete, or_, select

from app.models import Runbook, RunbookChunk, UserRole
from app.services.llm_service import get_provider
from app.services.redactor import redact_text
from app.services.storage import get_storage

ALLOWED = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
}
CHUNK_SIZE = 64 * 1024
SAFE_INDEX_FAILURE = "Runbook indexing failed. Check document and provider configuration."
EMBEDDING_BATCH_SIZE = 64


@dataclass(frozen=True)
class ExtractedSection:
    text: str
    page_number: int | None
    section_name: str | None


def store_runbook(upload, settings, storage):
    suffix = Path(upload.filename or "").suffix.lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if suffix not in ALLOWED or content_type not in ALLOWED[suffix]:
        raise HTTPException(422, "Only valid .txt, .md, and .pdf runbooks are supported.")

    def chunks():
        size = 0
        first_chunk = True
        decoder = None if suffix == ".pdf" else codecs.getincrementaldecoder("utf-8")()
        try:
            while chunk := upload.file.read(CHUNK_SIZE):
                if first_chunk and suffix == ".pdf" and not chunk.startswith(b"%PDF-"):
                    raise HTTPException(422, "Uploaded PDF signature is invalid.")
                first_chunk = False
                size += len(chunk)
                if size > settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, "Upload exceeds the configured size limit.")
                if decoder:
                    if b"\x00" in chunk:
                        raise HTTPException(422, "Runbook text contains invalid NUL bytes.")
                    decoder.decode(chunk)
                yield chunk
            if decoder:
                decoder.decode(b"", final=True)
            if not size:
                raise HTTPException(422, "Runbook must not be empty.")
        except UnicodeDecodeError:
            raise HTTPException(422, "Runbook text must be valid UTF-8.") from None

    return storage.put(chunks(), suffix)


def extract_sections(source, suffix):
    if suffix == ".pdf":
        reader = PdfReader(source)
        sections = []
        for number, page in enumerate(reader.pages, 1):
            text = normalize(page.extract_text() or "")
            if text:
                sections.append(ExtractedSection(redact_text(text, mask_ipv4=True), number, None))
        return sections
    return [
        ExtractedSection(
            redact_text(normalize(source.read().decode("utf-8")), mask_ipv4=True), None, None
        )
    ]


def normalize(text):
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def chunk_sections(sections, size, overlap):
    chunks = []
    for section in sections:
        start = 0
        while start < len(section.text):
            end = min(len(section.text), start + size)
            if end < len(section.text):
                boundary = section.text.rfind("\n", start, end)
                if boundary > start + size // 2:
                    end = boundary
            value = section.text[start:end].strip()
            if value:
                chunks.append(ExtractedSection(value, section.page_number, section.section_name))
            if end == len(section.text):
                break
            start = end - overlap
    return chunks


def index_runbook(session, runbook_id, settings, provider=None):
    runbook = session.get(Runbook, runbook_id)
    if runbook is None:
        return
    runbook.status, runbook.error_message = "INDEXING", None
    session.commit()
    try:
        storage = get_storage(settings)
        if runbook.storage_scope != storage.scope:
            raise ValueError("Storage scope mismatch.")
        with storage.open(runbook.storage_key) as source:
            sections = extract_sections(source, Path(runbook.storage_key).suffix)
        chunks = chunk_sections(
            sections, settings.runbook_chunk_characters, settings.runbook_chunk_overlap
        )
        if not chunks:
            raise ValueError("No extractable text.")
        provider = provider or get_provider(settings)
        vectors = []
        embedding_model = None
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            generated = provider.create_embeddings(
                [chunk.text for chunk in chunks[start : start + EMBEDDING_BATCH_SIZE]]
            )
            embedding_model = generated.model
            vectors.extend(generated.vectors)
        if len(vectors) != len(chunks) or any(
            len(vector) != settings.embedding_dimensions for vector in vectors
        ):
            raise ValueError("Embedding dimensions do not match the schema.")
        session.execute(delete(RunbookChunk).where(RunbookChunk.runbook_id == runbook.id))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            session.add(
                RunbookChunk(
                    runbook_id=runbook.id,
                    chunk_index=index,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section_name=chunk.section_name,
                    embedding=vector,
                    chunk_metadata={"embedding_model": embedding_model},
                )
            )
        runbook.status, runbook.indexed_at = "READY", datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
        runbook = session.get(Runbook, runbook_id)
        if runbook:
            runbook.status, runbook.error_message = "FAILED", SAFE_INDEX_FAILURE
            session.commit()


def visible_runbook_query(user):
    query = select(Runbook)
    if user.role != UserRole.ADMIN:
        query = query.where(or_(Runbook.owner_user_id == user.id, Runbook.is_global.is_(True)))
    return query


def cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norms if norms else 0.0


def retrieve_chunks(session, user, vector, settings, runbook_ids=None):
    query = select(RunbookChunk, Runbook).join(Runbook)
    if user.role != UserRole.ADMIN:
        query = query.where(or_(Runbook.owner_user_id == user.id, Runbook.is_global.is_(True)))
    query = query.where(Runbook.status == "READY")
    if runbook_ids:
        query = query.where(Runbook.id.in_(runbook_ids))
    if session.bind.dialect.name == "postgresql":
        distance = RunbookChunk.embedding.cosine_distance(vector)
        ranked_query = (
            query.add_columns(distance.label("distance"))
            .where(distance <= 1 - settings.retrieval_similarity_threshold)
            .order_by(distance, RunbookChunk.id)
            .limit(settings.retrieval_limit)
        )
        return [
            (1 - float(distance_value), chunk, runbook)
            for chunk, runbook, distance_value in session.execute(ranked_query)
        ]
    rows = session.execute(query).all()
    ranked = sorted(
        ((cosine(list(chunk.embedding), vector), chunk, runbook) for chunk, runbook in rows),
        key=lambda item: (-item[0], item[1].id),
    )
    return [
        item
        for item in ranked[: settings.retrieval_limit]
        if item[0] >= settings.retrieval_similarity_threshold
    ]
