from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time


class Worker:
    """One isolated, on-demand parser. No permanent model or unbounded task queue."""
    def __init__(self):
        self.process = None
        self.messages = queue.Queue(maxsize=8)
        self.cancelled = threading.Event()
        self.started = 0
        self.action = ''
        self.reported_exit = False

    def start(self, **request):
        self.stop()
        self.messages = queue.Queue(maxsize=8)
        self.cancelled = threading.Event()
        self.action = request['action']
        self.reported_exit = False
        self.started = time.monotonic()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        # pythonw has no standard streams, so use the sibling console interpreter.
        executable = sys.executable
        if executable.lower().endswith('pythonw.exe'):
            executable = executable[:-11] + 'python.exe'
        self.process = subprocess.Popen([executable, '-m', 'explorer.worker'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=flags, encoding='utf-8', cwd=os.path.dirname(os.path.dirname(__file__)),
                                        start_new_session=os.name != 'nt')
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.close()
        threading.Thread(target=self._read, args=(self.process, self.messages, self.cancelled), daemon=True).start()

    @staticmethod
    def _read(process, messages, cancelled):
        try:
            for line in process.stdout:
                if cancelled.is_set():
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                while not cancelled.is_set():
                    try:
                        messages.put(event, timeout=.1)
                        break
                    except queue.Full:
                        pass
        finally:
            process.stdout.close()
            while not cancelled.is_set():
                try:
                    messages.put({'event': '_exit'}, timeout=.1)
                    break
                except queue.Full:
                    pass

    def drain(self):
        result = []
        for _ in range(12):
            try:
                event = self.messages.get_nowait()
            except queue.Empty:
                break
            if event['event'] == '_exit':
                self.reported_exit = True
                code = self.process.poll() if self.process else 0
                if code not in (None, 0):
                    result.append({'event': 'error', 'message': '문서 작업 프로세스가 종료되었습니다. 메모리 한도 또는 파일 손상을 확인하세요.'})
            else:
                result.append(event)
        if self.process and self.process.poll() is None and self.action == 'inspect' and time.monotonic() - self.started > 25:
            self.stop()
            result.append({'event': 'error', 'message': '미리보기 제한 시간(25초)을 초과했습니다.'})
        return result

    def stop(self):
        self.cancelled.set()
        if self.process:
            if self.process.poll() is None:
                if os.name == 'nt':
                    self.process.terminate()
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            try:
                self.process.wait(timeout=.25)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
            self.process = None
