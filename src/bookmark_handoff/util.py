# Logging, the file names items are queued under, and the per-item loop every handoff runs.

import re
import sys
import traceback


def log(message):
  print(message, flush=True)


def warn(message):
  print(f"warning: {message}", file=sys.stderr, flush=True)


def warn_exception(context):
  """Warns of the exception being handled, with its traceback."""
  warn(f"{context}:\n{traceback.format_exc().rstrip()}")


def slug(article):
  """Filesystem-safe, and the id keeps two articles with one title apart."""
  base = re.sub(r"[^A-Za-z0-9]+", "-", article.get("title") or "")[:60].strip("-")
  return f"{base or 'article'}-{article['id']}"


def hand_off_each(items, kind, hand_off):
  """HAND_OFF(item) for each item, which returns whether it went through; returns how many
  failed, of how many. An item that raises counts as failed and the rest still run, so one
  malformed item doesn't hold up the others on every run."""
  failed = 0
  for item in items:
    try:
      ok = hand_off(item)
    except Exception:
      warn_exception(f"{kind} {item.get('id')} failed; the next run retries it")
      ok = False
    failed += not ok
  return failed, len(items)
