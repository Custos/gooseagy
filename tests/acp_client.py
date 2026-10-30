"""Small subprocess ACP client shared by offline and live contract checks."""
import json
import os
import selectors
import subprocess
import time


class Client:
    def __init__(self, command, env):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.counter = 0
        self.events = []

    def send(self, method, params, notify=False):
        obj = {"jsonrpc": "2.0", "method": method, "params": params}
        self.counter += 1
        if not notify:
            obj["id"] = self.counter
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        self.proc.stdin.flush()
        return self.counter

    def receive(self, timeout=12):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("ACP response deadline")
            data = os.read(self.proc.stdout.fileno(), 65536)
            if not data:
                raise RuntimeError("ACP worker closed stdout")
            self.buffer += data
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def wait(self, rid, timeout=12):
        deadline = time.monotonic() + timeout
        while True:
            event = self.receive(deadline - time.monotonic())
            self.events.append(event)
            if event.get("id") == rid:
                return event

    def request(self, method, params, timeout=12):
        return self.wait(self.send(method, params), timeout)

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        errors = self.proc.stderr.read().decode(errors="replace")
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.selector.close()
        return errors
