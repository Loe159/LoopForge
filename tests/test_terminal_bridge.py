from __future__ import annotations

import io
import unittest
from unittest import mock

from loopforge.engine.terminal_bridge import mirror_process


class _FakePtyProcess:
    def __init__(self, chunks: list[str], returncode: int = 0) -> None:
        self.chunks = iter(chunks)
        self.returncode = returncode

    def read(self, size: int = 1024) -> str:
        del size
        try:
            return next(self.chunks)
        except StopIteration:
            raise EOFError from None

    def wait(self) -> int:
        return self.returncode

    def isalive(self) -> bool:
        return True

    def write(self, value: str) -> int:
        return len(value)

    def sendintr(self) -> None:
        return None

    def setwinsize(self, rows: int, cols: int) -> None:
        del rows, cols


class TerminalBridgeTests(unittest.TestCase):
    def test_mirror_process_sends_the_same_output_to_console_and_parent(self) -> None:
        process = _FakePtyProcess(["Reasoning\r\n", "Tool call\r\n"])
        connection = mock.Mock()
        output = io.StringIO()

        returncode = mirror_process(
            process,
            connection,
            output=output,
            start_input=False,
        )

        self.assertEqual(returncode, 0)
        self.assertEqual(output.getvalue(), "Reasoning\r\nTool call\r\n")
        self.assertEqual(
            [call.args[0] for call in connection.send_bytes.call_args_list],
            [b"Reasoning\r\n", b"Tool call\r\n"],
        )


if __name__ == "__main__":
    unittest.main()
