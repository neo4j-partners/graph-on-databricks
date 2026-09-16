"""Genie Conversation API client.

Mirrors the pattern in `enrichment-pipeline/jobs/_demo_utils.py::ask_genie`, adapted to
the AskOut contract. The service issues a question against the configured
Genie Space and parses the first attachment that carries either text or a
query result.
"""

from __future__ import annotations

from datetime import timedelta

from databricks.sdk import WorkspaceClient

from ..core._config import AppConfig
from ..models import AnswerTable, AskOut


_DEFAULT_TIMEOUT_SECONDS = 120


def ask_genie(
    ws: WorkspaceClient,
    config: AppConfig,
    question: str,
    conversation_id: str | None,
) -> AskOut:
    if not config.genie_space_id:
        raise RuntimeError(
            "GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID is not configured; cannot ask Genie."
        )

    space_id = config.genie_space_id
    timeout = timedelta(seconds=_DEFAULT_TIMEOUT_SECONDS)

    if conversation_id:
        message = ws.genie.create_message_and_wait(
            space_id=space_id,
            conversation_id=conversation_id,
            content=question,
            timeout=timeout,
        )
    else:
        message = ws.genie.start_conversation_and_wait(
            space_id=space_id,
            content=question,
            timeout=timeout,
        )

    text = ""
    table: AnswerTable | None = None

    if message.attachments:
        for attachment in message.attachments:
            if attachment.text and attachment.text.content and not text:
                text = attachment.text.content

            if attachment.query and attachment.attachment_id and table is None:
                data_result = ws.genie.get_message_attachment_query_result(
                    space_id=space_id,
                    conversation_id=message.conversation_id or "",
                    message_id=message.message_id or "",
                    attachment_id=attachment.attachment_id,
                )
                sr = data_result.statement_response
                if sr and sr.manifest and sr.manifest.schema and sr.result:
                    columns = [c.name or "" for c in (sr.manifest.schema.columns or [])]
                    rows = sr.result.data_array or []
                    table = AnswerTable(
                        headers=columns,
                        rows=[[str(v) if v is not None else "" for v in row] for row in rows],
                    )

    return AskOut(
        conversation_id=message.conversation_id or "",
        message_id=message.message_id or "",
        text=text,
        table=table,
        summary=None,
    )
