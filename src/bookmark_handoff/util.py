# Logging, and the file names items are queued under.

import re
import sys


def log(message):
  print(message, flush=True)


def warn(message):
  print(f"warning: {message}", file=sys.stderr, flush=True)


def slug(article):
  """Filesystem-safe, and the id keeps two articles with one title apart."""
  base = re.sub(r"[^A-Za-z0-9]+", "-", article.get("title") or "")[:60].strip("-")
  return f"{base or 'article'}-{article['id']}"
