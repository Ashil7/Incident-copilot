"""Ownership-protected runbook ingestion, indexing, retrieval, and cited answers."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import Runbook, RunbookChunk, User, UserRole
from app.retrieval_schemas import (
    CitationResponse,
    RunbookAskRequest,
    RunbookAskResponse,
    RunbookResponse,
)
from app.services.audit import record_event
from app.services.llm_service import get_provider
from app.services.redactor import redact_text
from app.services.runbooks import retrieve_chunks, store_runbook, visible_runbook_query
from app.services.storage import get_storage
from app.task_queue import enqueue_runbook

router = APIRouter(prefix="/api/v1/runbooks", tags=["Runbooks"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def owned_runbook(session, runbook_id, user):
    query = visible_runbook_query(user).where(Runbook.id == str(runbook_id))
    runbook = session.scalar(query)
    if runbook is None:
        raise HTTPException(404, "Runbook not found.")
    return runbook


@router.post("", response_model=RunbookResponse, status_code=202)
def upload_runbook(
    request: Request,
    session: Database,
    user: CurrentUser,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    document: Annotated[UploadFile, File()],
    description: Annotated[str | None, Form(max_length=2000)] = None,
    is_global: Annotated[bool, Form()] = False,
):
    if is_global and user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator access required for global runbooks.")
    if not title.strip():
        raise HTTPException(422, "Runbook title must not be blank.")
    storage = get_storage(request.app.state.settings)
    stored = None
    committed = False
    try:
        stored = store_runbook(document, request.app.state.settings, storage)
        runbook = Runbook(
            owner_user_id=user.id,
            is_global=is_global,
            title=title.strip(),
            description=description.strip() or None if description else None,
            original_filename=document.filename,
            storage_key=stored.key,
            storage_scope=storage.scope,
            mime_type=(document.content_type or "").split(";", 1)[0].lower(),
            size_bytes=stored.size,
            sha256=stored.sha256,
            status="PENDING",
        )
        session.add(runbook)
        session.flush()
        record_event(session, user.id, "runbook.uploaded", "runbook", runbook.id)
        session.commit()
        committed = True
        enqueue_runbook(request, runbook.id)
        return runbook
    except HTTPException:
        session.rollback()
        if stored and not committed:
            storage.delete(stored.key)
        raise
    finally:
        document.file.close()


@router.get("", response_model=list[RunbookResponse])
def list_runbooks(session: Database, user: CurrentUser):
    return list(session.scalars(visible_runbook_query(user).order_by(Runbook.created_at.desc())))


@router.get("/{runbook_id:uuid}", response_model=RunbookResponse)
def get_runbook(runbook_id: UUID, session: Database, user: CurrentUser):
    return owned_runbook(session, runbook_id, user)


@router.delete("/{runbook_id:uuid}", status_code=204)
def delete_runbook(runbook_id: UUID, request: Request, session: Database, user: CurrentUser):
    runbook = owned_runbook(session, runbook_id, user)
    if runbook.is_global and user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator access required.")
    storage = get_storage(request.app.state.settings)
    if runbook.storage_scope != storage.scope:
        raise HTTPException(409, "Runbook belongs to another storage environment.")
    session.execute(delete(RunbookChunk).where(RunbookChunk.runbook_id == runbook.id))
    record_event(session, user.id, "runbook.deleted", "runbook", runbook.id)
    session.delete(runbook)
    session.commit()
    storage.delete(runbook.storage_key)


@router.post("/{runbook_id:uuid}/reindex", response_model=RunbookResponse, status_code=202)
def reindex_runbook(runbook_id: UUID, request: Request, session: Database, user: CurrentUser):
    runbook = owned_runbook(session, runbook_id, user)
    if runbook.is_global and user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator access required.")
    if runbook.status in {"PENDING", "INDEXING"}:
        raise HTTPException(409, "Runbook indexing is already active.")
    runbook.status, runbook.error_message = "PENDING", None
    record_event(session, user.id, "runbook.reindex_requested", "runbook", runbook.id)
    session.commit()
    enqueue_runbook(request, runbook.id)
    return runbook


@router.post("/ask", response_model=RunbookAskResponse)
def ask_runbooks(body: RunbookAskRequest, request: Request, session: Database, user: CurrentUser):
    provider = get_provider(request.app.state.settings)
    vector_result = provider.create_embeddings([body.question])
    if (
        len(vector_result.vectors) != 1
        or len(vector_result.vectors[0]) != request.app.state.settings.embedding_dimensions
    ):
        raise HTTPException(503, "Question embedding validation failed.")
    matches = retrieve_chunks(
        session, user, vector_result.vectors[0], request.app.state.settings, body.runbook_ids
    )
    if not matches:
        return RunbookAskResponse(
            answer="The available runbooks do not contain enough information.",
            insufficient_context=True,
            citations=[],
        )
    context = [{"chunk_id": chunk.id, "text": chunk.text} for _, chunk, _ in matches]
    generated = provider.answer_runbook_question(body.question, context)
    if generated.result.insufficient_context:
        return RunbookAskResponse(
            answer="The available runbooks do not contain enough information.",
            insufficient_context=True,
            citations=[],
        )
    allowed = {chunk.id for _, chunk, _ in matches}
    cited = [item.chunk_id for item in generated.result.citations]
    if not cited or not set(cited) <= allowed:
        raise HTTPException(503, "Runbook answer validation failed.")
    rows = {chunk.id: (chunk, runbook) for _, chunk, runbook in matches}
    citations = [
        CitationResponse(
            runbook_id=rows[chunk_id][1].id,
            runbook_title=rows[chunk_id][1].title,
            chunk_id=chunk_id,
            page_number=rows[chunk_id][0].page_number,
            section_name=rows[chunk_id][0].section_name,
            excerpt=rows[chunk_id][0].text[:300],
        )
        for chunk_id in dict.fromkeys(cited)
    ]
    return RunbookAskResponse(
        answer=redact_text(generated.result.answer, mask_ipv4=True),
        insufficient_context=generated.result.insufficient_context,
        citations=citations,
    )
