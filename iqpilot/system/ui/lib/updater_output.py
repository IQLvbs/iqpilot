"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import collections
import subprocess
import threading


class StderrTail(collections.deque):
  thread: threading.Thread


def drain_stderr(process: subprocess.Popen, keep: int = 20) -> StderrTail:
  tail = StderrTail(maxlen=keep)

  def drain():
    if process.stderr is None:
      return
    with process.stderr:
      for line in process.stderr:
        if line.strip():
          tail.append(line.strip())

  thread = threading.Thread(target=drain, daemon=True)
  thread.start()
  tail.thread = thread
  return tail


def failure_reason(error: str, stderr_tail: collections.deque) -> str:
  if error:
    return error
  if stderr_tail:
    return stderr_tail[-1]
  return "the updater exited without reporting a reason"
