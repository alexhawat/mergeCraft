"""Run the opt-in Discuss Action with one bound review-thread reply as its only write.

Module: mergecraft.action.discuss
Depends: mergecraft.action.discuss_thread, mergecraft.agents.discuss, httpx

Exports:
    Functions:
        run_discuss — Run the separate Action for a native review-thread mention.
"""

from __future__ import annotations

import asyncio
import html
import os

import httpx
from loguru import logger

from mergecraft.action.discuss_thread import (
    DiscussContextError,
    authorize_discussion,
    bind_discussion_mention,
    read_discussion_thread,
)
from mergecraft.action.review_state import MainResult
from mergecraft.agents.discuss import DiscussModelError, generate_discuss_reply
from mergecraft.analyzers.redact import redact_secrets
from mergecraft.errors import ConfigurationError
from mergecraft.findings.threads import positive_database_id
from mergecraft.modes.Discuss import build_discuss_context
from mergecraft.review.authorship import lookup_publisher_logins
from mergecraft.review_resolution import is_publisher_login
from mergecraft.run_outcome import RunOutcome
from mergecraft.scm.github import create_github_scm
from mergecraft.utils.payload import read_github_event
from mergecraft.utils.token import get_job_token

_RUN_TIMEOUT_S = 100


async def run_discuss(input_value: str) -> MainResult:
    """Handle Discuss separately from checkout, MCP and review publication."""
    if (
        input_value != "enabled"
        or os.environ.get("GITHUB_EVENT_NAME") != "pull_request_review_comment"
    ):
        return MainResult(
            success=False,
            error="Discuss requires discuss: enabled on a native pull_request_review_comment event.",
            outcome=RunOutcome.configuration_error,
        )
    try:
        async with asyncio.timeout(_RUN_TIMEOUT_S):
            await _answer_native_mention()
    except ConfigurationError as error:
        return MainResult(success=False, error=str(error), outcome=RunOutcome.configuration_error)
    except (DiscussContextError, DiscussModelError) as error:
        return MainResult(success=False, error=str(error), outcome=RunOutcome.infra_error)
    except TimeoutError:
        return MainResult(success=False, error="Discuss timed out.", outcome=RunOutcome.timed_out)
    except (httpx.HTTPError, RecursionError, TypeError, ValueError) as error:
        return MainResult(
            success=False,
            error=f"Discuss could not complete a request ({type(error).__name__}).",
            outcome=RunOutcome.infra_error,
        )
    return MainResult(success=True, outcome=RunOutcome.passed)


async def _answer_native_mention() -> None:
    event = read_github_event()
    if event is None:
        msg = "Discuss requires the native GitHub Actions event payload."
        raise ConfigurationError(msg)
    mention = bind_discussion_mention(event, os.environ)
    if mention is None:
        return

    try:
        token = get_job_token()
    except ValueError as error:
        msg = "Discuss requires a GitHub token for the reviewer App or PAT."
        raise ConfigurationError(msg) from error
    scm = create_github_scm(token)
    try:
        if not await authorize_discussion(scm, mention):
            return
        publishers = await lookup_publisher_logins(scm, token)
        if not publishers:
            msg = "Discuss requires the reviewer App or PAT used to publish the original finding."
            raise ConfigurationError(msg)
        if is_publisher_login(mention.login, publishers):
            return
        thread = await read_discussion_thread(scm, mention, publishers)
        if thread is None:
            return
        prompt = build_discuss_context(
            finding=thread.finding,
            path=thread.path,
            diff_hunk=thread.diff_hunk,
            prior_replies=thread.prior_replies,
            question=mention.body,
        )
        answer = await generate_discuss_reply(
            prompt, thread_key=f"{mention.repository_id}:{mention.pull_number}:{mention.root_id}"
        )
        # The comment may have been edited, deleted, or answered during generation.
        if await read_discussion_thread(scm, mention, publishers) != thread:
            return
        if not await authorize_discussion(scm, mention):
            return
        # The model can supply text only. In particular it cannot mint a
        # replay marker, ping users, or create GitHub suggestion blocks.
        text = html.escape(redact_secrets(answer), quote=False)
        text = text.replace("@", "@\u200b").replace("`", "&#96;").replace("~", "&#126;")
        text = text.replace("[", "&#91;")
        body = f"{text}\n\n{mention.reply_marker}"
        reply = await scm.post(
            f"{mention.pull_api_path}/comments/{mention.root_id}/replies",
            json={"body": body},
        )
        if (
            not isinstance(reply, dict)
            or positive_database_id(reply.get("id")) is None
            or positive_database_id(reply.get("in_reply_to_id")) != mention.root_id
            or reply.get("body") != body
            or not isinstance(user := reply.get("user"), dict)
            or not is_publisher_login(user.get("login"), publishers)
        ):
            msg = "GitHub did not confirm the Discuss reply."
            raise DiscussContextError(msg)
        logger.info("Discuss replied to review comment {}", mention.comment_id)
    finally:
        await scm.aclose()
