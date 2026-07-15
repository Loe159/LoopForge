"""Error types exposed by the LoopForge command-line interface."""

from __future__ import annotations


DOCS_URL = "https://github.com/loopforge/loopforge#readme"


class CliError(Exception):
    def __init__(
        self,
        code: str,
        title: str,
        detail: str = "",
        *,
        fix: str | None = None,
        exit_code: int = 1,
        url: str = DOCS_URL,
    ) -> None:
        super().__init__(detail or title)
        self.code = code
        self.title = title
        self.detail = detail
        self.fix = fix
        self.exit_code = exit_code
        self.url = url


class CliUsageError(CliError):
    def __init__(self, code: str, title: str, detail: str = "", *, fix: str | None = None) -> None:
        super().__init__(code, title, detail, fix=fix, exit_code=2)


class CliRuntimeError(CliError):
    pass
