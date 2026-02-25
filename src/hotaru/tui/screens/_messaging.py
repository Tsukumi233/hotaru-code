"""Messaging mixin for the session screen."""

import asyncio
from typing import Any, List, Optional

from textual.containers import ScrollableContainer

from ..context import use_local, use_route, use_sdk, use_sync
from ..dialogs import InputDialog, PermissionDialog, SelectDialog
from ..input_parsing import enrich_content_with_file_references
from ..widgets import AssistantTextPart, MessageBubble, PromptInput, Spinner
from ._rendering import now_timestamp


class MessagingMixin:
    """Mixin providing message send/receive logic for SessionScreen."""

    def _send_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            return
        self._reset_interrupt()

        if self.session_id:
            self.app.clear_session_redo(self.session_id)

        if content.startswith("!"):
            command = content[1:].strip()
            if not command:
                self.app.notify("Shell command cannot be empty.", severity="warning")
                return
            self._send_shell_command(raw_input=content, command=command)
            return

        container = self.query_one("#messages-container", ScrollableContainer)
        self._loading_spinner = Spinner("Thinking...")
        container.mount(self._loading_spinner)

        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.disabled = True

        self.run_worker(
            self._send_message_async(content),
            exclusive=True,
        )

    def _send_shell_command(self, raw_input: str, command: str) -> None:
        """Execute a local shell command in session view."""
        container = self.query_one("#messages-container", ScrollableContainer)
        container.mount(
            MessageBubble(
                content=raw_input,
                role="user",
                timestamp=now_timestamp(show=self._show_timestamps),
                classes="message user-message",
            )
        )
        container.scroll_end()

        self._loading_spinner = Spinner("Running shell command...")
        container.mount(self._loading_spinner)

        prompt = self.query_one("#prompt-input", PromptInput)
        prompt.disabled = True

        self.run_worker(
            self._run_shell_command_async(command, container),
            exclusive=True,
        )

    async def _run_shell_command_async(
        self,
        command: str,
        container: ScrollableContainer,
    ) -> None:
        """Run a shell command and render output as assistant content."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=use_sdk().cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()
            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            err = (stderr or b"").decode("utf-8", errors="replace").strip()
            combined = "\n".join(part for part in [output, err] if part)
            exit_code = proc.returncode or 0

            await self._remove_spinner()
            await container.mount(
                MessageBubble(
                    content="",
                    role="assistant",
                    agent="shell",
                    timestamp=now_timestamp(show=self._show_timestamps),
                    classes="message assistant-message",
                )
            )

            rendered_output = combined if combined else "(no output)"
            rendered = (
                "```text\n"
                f"$ {command}\n"
                f"{rendered_output}\n"
                f"[exit code: {exit_code}]\n"
                "```"
            )
            await container.mount(
                AssistantTextPart(
                    content=rendered,
                    part_id=f"shell-{hash(command)}",
                    classes="message assistant-message",
                )
            )

            if exit_code != 0:
                self.app.notify(
                    f"Shell command exited with code {exit_code}.",
                    severity="warning",
                )
            container.scroll_end()
        except Exception as exc:
            self.app.notify(f"Shell command failed: {exc}", severity="error")
            await self._remove_spinner()
        finally:
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = False
            prompt.focus()

    async def _remove_spinner(self) -> None:
        if not self._loading_spinner:
            return
        try:
            await self._loading_spinner.remove()
        except Exception:
            pass
        self._loading_spinner = None

    async def _send_message_async(self, content: str) -> None:
        """Send a message and stream assistant output."""
        from ...core.bus import Bus
        from ...permission import PermissionAsked, PermissionReply
        from ...question import QuestionAsked

        async def on_permission_asked(payload: Any) -> None:
            request_data = payload.properties
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = True
            try:
                result = await self.app.push_screen_wait(PermissionDialog(request=request_data))
                reply_type, message = result or ("reject", None)
                await self.app.runtime.permission.reply(
                    request_id=request_data["id"],
                    reply=PermissionReply(reply_type),
                    message=message,
                )
            except Exception:
                await self.app.runtime.permission.reply(
                    request_id=request_data["id"],
                    reply=PermissionReply.REJECT,
                )
            finally:
                prompt.disabled = False

        async def on_question_asked(payload: Any) -> None:
            request_data = payload.properties
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = True
            try:
                answers: List[List[str]] = []
                for question in request_data.get("questions", []):
                    title = question.get("header", "Question")
                    text = question.get("question", "Please choose")
                    options = question.get("options", []) or []
                    multiple = bool(question.get("multiple"))
                    allow_custom = question.get("custom", True)

                    if not options:
                        value = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder=text, submit_label="Submit")
                        )
                        answers.append([value] if value else [])
                        continue

                    if multiple:
                        lines = [f"{idx + 1}. {opt.get('label', f'Option {idx + 1}')}" for idx, opt in enumerate(options)]
                        prompt_text = f"{text}\n\n" + "\n".join(lines) + "\n\nEnter comma-separated option numbers."
                        raw = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder=prompt_text, submit_label="Submit")
                        )
                        selected: List[str] = []
                        if isinstance(raw, str):
                            for item in [piece.strip() for piece in raw.split(",") if piece.strip()]:
                                if item.isdigit():
                                    idx = int(item)
                                    if 1 <= idx <= len(options):
                                        selected.append(options[idx - 1].get("label", f"Option {idx}"))
                        if allow_custom and not selected:
                            custom = await self.app.push_screen_wait(
                                InputDialog(title=title, placeholder="Custom answer", submit_label="Submit")
                            )
                            if custom:
                                selected.append(custom)
                        answers.append(selected)
                        continue

                    dialog_options = [
                        (f"{opt.get('label', f'Option {idx + 1}')}: {opt.get('description', '')}", opt.get("label", ""))
                        for idx, opt in enumerate(options)
                    ]
                    selected = await self.app.push_screen_wait(
                        SelectDialog(title=f"{title}: {text}", options=dialog_options)
                    )
                    if selected is None and allow_custom:
                        custom = await self.app.push_screen_wait(
                            InputDialog(title=title, placeholder="Custom answer", submit_label="Submit")
                        )
                        answers.append([custom] if custom else [])
                    elif selected is None:
                        answers.append([])
                    else:
                        answers.append([selected])

                await self.app.runtime.question.reply(request_data["id"], answers)
            except Exception:
                await self.app.runtime.question.reject(request_data["id"])
            finally:
                prompt.disabled = False

        unsub = Bus.subscribe(PermissionAsked, on_permission_asked)
        unsub_question = Bus.subscribe(QuestionAsked, on_question_asked)
        try:
            sdk = use_sdk()
            sync = use_sync()
            local = use_local()

            agent = local.agent.current().get("name", "build")
            model_selection = local.model.current()
            model = None
            if model_selection:
                model = f"{model_selection.provider_id}/{model_selection.model_id}"

            if not self.session_id:
                session_data = await sdk.create_session(agent=agent, model=model)
                self.session_id = session_data["id"]
                sync.update_session(session_data)
                route = use_route()
                if route.is_session():
                    route.data.session_id = self.session_id
                self._refresh_header()

            enriched_content, attached_paths, warnings = enrich_content_with_file_references(
                content,
                cwd=sdk.cwd,
            )
            for warning in warnings:
                self.app.notify(warning, severity="warning")
            if attached_paths:
                attached_text = ", ".join(attached_paths[:3])
                if len(attached_paths) > 3:
                    attached_text += ", ..."
                self.app.notify(
                    f"Attached {len(attached_paths)} file(s): {attached_text}",
                    severity="information",
                )

            finalized = False
            async for event in sdk.send_message(
                session_id=self.session_id,
                content=enriched_content,
                agent=agent,
                model=model,
                files=[{"path": path} for path in attached_paths] if attached_paths else None,
            ):
                event_type = event.get("type")
                if event_type == "session.status":
                    status_data = event.get("data", {}).get("status", {})
                    status_type = status_data.get("type") if isinstance(status_data, dict) else None
                    if status_type != "idle":
                        continue

                    finalized = True
                    if self.session_id:
                        session_data = sync.get_session(self.session_id)
                        if session_data and isinstance(session_data.get("agent"), str):
                            local.agent.set(session_data["agent"])
                            self._refresh_prompt_meta()
                elif event_type == "error":
                    error_msg = event.get("data", {}).get("error", "Unknown error")
                    self.app.notify(f"Error: {error_msg}", severity="error")
                    await self._remove_spinner()

            # OpenCode-like behavior: message request completion is authoritative.
            # If idle event was missed in transit, force a final sync after stream loop exits.
            if self.session_id and not finalized:
                await sync.sync_session(self.session_id, sdk, force=True)
                session_data = sync.get_session(self.session_id)
                if session_data and isinstance(session_data.get("agent"), str):
                    local.agent.set(session_data["agent"])
                    self._refresh_prompt_meta()
                await self._load_session_history()
            container = self.query_one("#messages-container", ScrollableContainer)
            container.scroll_end()
        except Exception as e:
            self.app.notify(f"Error sending message: {str(e)}", severity="error")
            await self._remove_spinner()
        finally:
            unsub()
            unsub_question()
            await self._remove_spinner()
            prompt = self.query_one("#prompt-input", PromptInput)
            prompt.disabled = False
            prompt.focus()
            self._reset_interrupt()
