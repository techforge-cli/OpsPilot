from unittest.mock import Mock

from opspilot.metrics import collect_native_snapshot


def test_memory_parser_accepts_proc_meminfo():
    shell = Mock()
    shell.run.return_value = (0, "MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 10 kB\nSwapFree: 5 kB\n", "", 0.1)
    result = collect_native_snapshot(shell)
    assert shell.run.call_count >= 1
    assert result["metrics"]["memory"]["mem_total_kb"] == 1000
