# One pass of every configured job, and its exit status.
# Usage:
#   bookmark_handoff

import argparse
import os
import sys

from .app import App
from .config import Config, ConfigError
from .narrate import readeck_to_narrate
from .toread import linkding_to_readeck
from .util import log, warn_exception
from .video import linkding_to_video


def run(environ):
  """One pass of every configured job; returns the errors."""
  cfg = Config.from_env(environ)
  linkding = App.from_env(environ, "LINKDING", "Token")
  readeck = App.from_env(environ, "READECK", "Bearer")
  jobs = [
    (
      "linkding to Readeck",
      (linkding, readeck),
      lambda: linkding_to_readeck(cfg, linkding, readeck),
    ),
    ("Readeck to narration", (readeck,), lambda: readeck_to_narrate(cfg, readeck)),
    ("linkding to video", (linkding,), lambda: linkding_to_video(cfg, linkding)),
  ]
  errors = []
  # Each job runs whatever the others did: one app being down, or answering with something
  # unexpected, shouldn't hold up the rest.
  for job, apps, handoff in jobs:
    if None in apps:
      log(f"{job}: skipped, its apps aren't all configured")
      continue
    try:
      failed, total = handoff()
    except Exception as e:
      warn_exception(f"{job} failed")
      errors.append(f"{job}: {type(e).__name__}: {e}")
      continue
    if failed:
      errors.append(f"{job}: {failed} of {total} failed")
  return errors


def main(argv):
  # No options; this is for --help. Configuration is by environment variable.
  argparse.ArgumentParser(
    prog="bookmark_handoff",
    description="Moves tagged linkding bookmarks to Readeck and to the video inbox, and "
    "labelled Readeck articles to the narration inbox, in one pass. Configured by "
    "environment variable; see README.md.",
  ).parse_args(argv)
  try:
    errors = run(os.environ)
  except ConfigError as e:
    errors = [str(e)]
  for error in errors:
    print(f"error: {error}", file=sys.stderr)
  return 1 if errors else 0


def entry():
  """The zipapp's entry point."""
  sys.exit(main(sys.argv[1:]))
