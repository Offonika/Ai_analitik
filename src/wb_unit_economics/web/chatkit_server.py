from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from chatkit.server import ChatKitServer
from chatkit.store import NotFoundError, Store
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    InferenceOptions,
    Page,
    ThreadItem,
    ThreadItemDoneEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
    UserMessageTextContent,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.ai import AiAnalyst
from wb_unit_economics.web.models import AiMessage, AiThread, User


@dataclass
class CabinetChatKitContext:
    db: Session
    user: User
    analyst: AiAnalyst
    report_id: str = ""
    client_id: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    assistant_citations: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )


class CabinetChatKitStore(Store[CabinetChatKitContext]):
    """ChatKit protocol adapter over the existing private AI tables."""

    async def load_thread(
        self, thread_id: str, context: CabinetChatKitContext
    ) -> ThreadMetadata:
        try:
            thread = repository.require_thread(context.db, context.user, thread_id)
        except PermissionError as exc:
            raise NotFoundError(thread_id) from exc
        return self._thread_metadata(thread)

    async def save_thread(
        self, thread: ThreadMetadata, context: CabinetChatKitContext
    ) -> None:
        existing = context.db.get(AiThread, thread.id)
        if existing is not None:
            try:
                existing = repository.require_thread(
                    context.db, context.user, thread.id
                )
            except PermissionError as exc:
                raise NotFoundError(thread.id) from exc
            existing.title = (thread.title or existing.title)[:200]
            if context.scope:
                repository.update_ai_thread_scope(existing, context.scope)
            return
        if not context.report_id:
            raise ValueError("ChatKit thread requires reportId metadata")
        report = repository.require_report(
            context.db, context.user, context.report_id
        )
        if context.client_id and context.client_id != report.client_id:
            raise PermissionError("report/client scope mismatch")
        repository.create_ai_thread(
            context.db,
            user=context.user,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            report_id=report.id,
            title=thread.title or "AI-аналитик",
            scope=context.scope,
            thread_id=thread.id,
        )
        context.db.flush()

    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: CabinetChatKitContext,
    ) -> Page[ThreadItem]:
        thread = repository.require_thread(context.db, context.user, thread_id)
        messages = repository.thread_messages(context.db, thread)
        items = [self._message_item(message) for message in messages]
        if order == "desc":
            items.reverse()
        if after:
            index = next(
                (index for index, item in enumerate(items) if item.id == after),
                None,
            )
            items = items[index + 1 :] if index is not None else []
        size = max(1, min(limit, 100))
        page_items = items[:size]
        return Page(
            data=page_items,
            has_more=len(items) > size,
            after=page_items[-1].id if len(items) > size and page_items else None,
        )

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: CabinetChatKitContext,
    ) -> Page[ThreadMetadata]:
        statement = select(AiThread).where(
            AiThread.user_id == context.user.id,
            AiThread.archived_at.is_(None),
        )
        statement = statement.order_by(
            AiThread.created_at.asc() if order == "asc" else AiThread.created_at.desc()
        )
        threads = list(context.db.scalars(statement))
        if after:
            index = next(
                (index for index, item in enumerate(threads) if item.id == after),
                None,
            )
            threads = threads[index + 1 :] if index is not None else []
        size = max(1, min(limit, 100))
        page_threads = threads[:size]
        return Page(
            data=[self._thread_metadata(item) for item in page_threads],
            has_more=len(threads) > size,
            after=(
                page_threads[-1].id
                if len(threads) > size and page_threads
                else None
            ),
        )

    async def add_thread_item(
        self,
        thread_id: str,
        item: ThreadItem,
        context: CabinetChatKitContext,
    ) -> None:
        thread = repository.require_thread(context.db, context.user, thread_id)
        if isinstance(item, UserMessageItem):
            repository.add_ai_message(
                context.db,
                thread=thread,
                role="user",
                content=self._user_text(item),
                chatkit_item_id=item.id,
            )
        elif isinstance(item, AssistantMessageItem):
            repository.add_ai_message(
                context.db,
                thread=thread,
                role="assistant",
                content="\n".join(part.text for part in item.content),
                chatkit_item_id=item.id,
                citations=context.assistant_citations.pop(item.id, []),
            )
        context.db.flush()

    async def save_item(
        self,
        thread_id: str,
        item: ThreadItem,
        context: CabinetChatKitContext,
    ) -> None:
        message = self._load_message(context, thread_id, item.id)
        if isinstance(item, UserMessageItem):
            message.content = self._user_text(item)
        elif isinstance(item, AssistantMessageItem):
            message.content = "\n".join(part.text for part in item.content)

    async def load_item(
        self,
        thread_id: str,
        item_id: str,
        context: CabinetChatKitContext,
    ) -> ThreadItem:
        return self._message_item(self._load_message(context, thread_id, item_id))

    async def delete_thread(
        self, thread_id: str, context: CabinetChatKitContext
    ) -> None:
        thread = repository.require_thread(context.db, context.user, thread_id)
        thread.archived_at = security.utcnow()

    async def delete_thread_item(
        self,
        thread_id: str,
        item_id: str,
        context: CabinetChatKitContext,
    ) -> None:
        context.db.delete(self._load_message(context, thread_id, item_id))

    async def save_attachment(self, attachment, context):  # type: ignore[no-untyped-def]
        raise NotImplementedError("ChatKit attachments are disabled")

    async def load_attachment(self, attachment_id, context):  # type: ignore[no-untyped-def]
        raise NotFoundError(attachment_id)

    async def delete_attachment(self, attachment_id, context):  # type: ignore[no-untyped-def]
        raise NotFoundError(attachment_id)

    def _load_message(
        self, context: CabinetChatKitContext, thread_id: str, item_id: str
    ) -> AiMessage:
        repository.require_thread(context.db, context.user, thread_id)
        message = context.db.scalar(
            select(AiMessage).where(
                AiMessage.thread_id == thread_id,
                AiMessage.chatkit_item_id == item_id,
            )
        )
        if message is None:
            raise NotFoundError(item_id)
        return message

    def _thread_metadata(self, thread: AiThread) -> ThreadMetadata:
        return ThreadMetadata(
            id=thread.id,
            title=thread.title,
            created_at=thread.created_at,
            metadata={
                "reportId": thread.report_run_id,
                "clientId": thread.client_id,
                "scopeHash": thread.scope_hash,
            },
        )

    def _message_item(self, message: AiMessage) -> ThreadItem:
        item_id = message.chatkit_item_id or f"msg_{message.id}"
        if message.role == "user":
            return UserMessageItem(
                id=item_id,
                thread_id=message.thread_id,
                created_at=message.created_at,
                content=[UserMessageTextContent(text=message.content)],
                attachments=[],
                inference_options=InferenceOptions(),
            )
        return AssistantMessageItem(
            id=item_id,
            thread_id=message.thread_id,
            created_at=message.created_at,
            content=[AssistantMessageContent(text=message.content)],
        )

    def _user_text(self, item: UserMessageItem) -> str:
        return "\n".join(
            str(part.text)
            for part in item.content
            if hasattr(part, "text") and str(part.text).strip()
        )[:8000]


class CabinetChatKitServer(ChatKitServer[CabinetChatKitContext]):
    def respond(
        self,
        thread: ThreadMetadata,
        input_user_message: UserMessageItem | None,
        context: CabinetChatKitContext,
    ) -> AsyncIterator[ThreadStreamEvent]:
        async def stream() -> AsyncIterator[ThreadStreamEvent]:
            db_thread = repository.require_thread(
                context.db, context.user, thread.id
            )
            if context.scope:
                repository.update_ai_thread_scope(db_thread, context.scope)
            question = (
                self.store._user_text(input_user_message)  # type: ignore[attr-defined]
                if input_user_message is not None
                else self._latest_user_question(context, db_thread)
            )
            answer = context.analyst.answer(
                context.db,
                user=context.user,
                thread=db_thread,
                question=question,
            )
            repository.add_ai_event(
                context.db,
                thread=db_thread,
                user=context.user,
                event_type="assistant_done",
                title="Ответ готов",
                message="Ответ сохранен через ChatKit.",
                status="ok" if answer.answer_source == "openai" else "fallback",
                payload={
                    "answerSource": answer.answer_source,
                    "model": answer.model,
                    "fallbackReason": answer.fallback_reason,
                    "toolNames": list(answer.tool_names),
                },
            )
            item_id = self.store.generate_item_id("message", thread, context)
            context.assistant_citations[item_id] = list(answer.citations)
            yield ThreadItemDoneEvent(
                item=AssistantMessageItem(
                    id=item_id,
                    thread_id=thread.id,
                    created_at=security.utcnow(),
                    content=[AssistantMessageContent(text=answer.content)],
                )
            )

        return stream()

    def _latest_user_question(
        self, context: CabinetChatKitContext, thread: AiThread
    ) -> str:
        messages = repository.thread_messages(context.db, thread, limit=20)
        return next(
            (item.content for item in reversed(messages) if item.role == "user"),
            "Продолжи анализ текущего отчета.",
        )
