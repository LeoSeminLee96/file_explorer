from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from explorer.service import Worker


class FailureTests(unittest.TestCase):
    def test_os_memory_ceiling_rejects_oversized_allocation(self):
        code = '''from explorer.memory import constrain_process
import sys
if not constrain_process(128):
    sys.exit(3)
try:
    allocation = bytearray(512 * 1024**2)
except MemoryError:
    print("memory-ceiling-enforced")
    sys.exit(0)
sys.exit(4)
'''
        completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('memory-ceiling-enforced', completed.stdout)

    def test_killed_worker_can_be_replaced_by_healthy_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'notes.md'
            path.write_text('# Notes\n\nThe project reviewed 1250 documents. The key result was an 18% increase in accuracy.', encoding='utf-8')
            worker = Worker()
            try:
                worker.start(action='inspect', path=str(path), memory_mb=128)
                worker.process.kill()
                worker.process.wait(timeout=5)
                worker.start(action='inspect', path=str(path), memory_mb=128)
                deadline, events = time.monotonic() + 10, []
                while time.monotonic() < deadline:
                    events.extend(worker.drain())
                    if any(e['event'] == 'inspected' for e in events):
                        break
                    time.sleep(.03)
                self.assertTrue(any(e['event'] == 'inspected' for e in events))
            finally:
                worker.stop()


if __name__ == '__main__':
    unittest.main()
