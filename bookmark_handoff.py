#!/usr/bin/env python3
# Moves bookmarks between self-hosted reading apps, by tag. Each run is one pass; a timer
# or cron job runs it every few minutes:
# - linkding bookmarks tagged `toread` go to Readeck, and the tag becomes `readeck`
# - Readeck articles labelled `listen` go to a narration inbox as EPUBs, each with a JSON
#   spec for its language and collection, and the label becomes `narrated`
# - linkding bookmarks tagged `tolisten` (YouTube videos) go to a video inbox as JSON
#   requests, and the tag becomes `transcribed`; a `lang:xx` tag picks the captions
# An item whose handoff fails keeps its tag or label, and the next run retries it. A job
# whose app isn't configured, or whose inbox doesn't exist, is skipped. Configuration is
# by environment variable; see README.md.
# Usage:
#   bookmark_handoff.py

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import langcodes

# Chatterbox Multilingual's languages, the TTS behind Calliope; anything else is read
# as English. Ref: https://github.com/resemble-ai/chatterbox
narrated_langs = {
  "ar",
  "da",
  "de",
  "el",
  "en",
  "es",
  "fi",
  "fr",
  "he",
  "hi",
  "it",
  "ja",
  "ko",
  "ms",
  "nl",
  "no",
  "pl",
  "pt",
  "ru",
  "sv",
  "sw",
  "tr",
  "zh",
}


def log(message):
  print(message, flush=True)


def warn(message):
  print(f"warning: {message}", file=sys.stderr, flush=True)


class ConfigError(Exception):
  pass


def env(environ, name, default=None):
  return environ.get(name, "").strip() or default


@dataclass
class Config:
  toread_tag: str
  readeck_tag: str
  listen_label: str
  narrated_label: str
  tolisten_tag: str
  transcribed_tag: str
  narrate_dir: Path
  narrate_collection: str
  videos_dir: Path
  video_collection: str
  readalouds_dir: Path
  state_dir: Path

  @classmethod
  def from_env(cls, environ):
    books = Path(env(environ, "BOOKS_DIR", "/books"))
    return cls(
      toread_tag=env(environ, "TOREAD_TAG", "toread"),
      readeck_tag=env(environ, "READECK_TAG", "readeck"),
      listen_label=env(environ, "LISTEN_LABEL", "listen"),
      narrated_label=env(environ, "NARRATED_LABEL", "narrated"),
      tolisten_tag=env(environ, "TOLISTEN_TAG", "tolisten"),
      transcribed_tag=env(environ, "TRANSCRIBED_TAG", "transcribed"),
      narrate_dir=Path(env(environ, "NARRATE_DIR", books / "narrate")),
      narrate_collection=env(environ, "NARRATE_COLLECTION", "articles"),
      videos_dir=Path(env(environ, "VIDEOS_DIR", books / "videos")),
      video_collection=env(environ, "VIDEO_COLLECTION", "videos"),
      readalouds_dir=Path(env(environ, "READALOUDS_DIR", books / "readalouds")),
      state_dir=Path(env(environ, "STATE_DIR", "/state")),
    )


class App:
  """One app's REST API. HOST, when set, is sent as the Host header, so the app can be
  reached on an internal address under its public host name."""

  def __init__(self, url, token, scheme, host=None):
    self.url = url.rstrip("/")
    self.host = host
    self.auth = f"{scheme} {token}"

  # Usage: App.from_env(environ, NAME, SCHEME); None when NAME_URL isn't set
  @classmethod
  def from_env(cls, environ, name, scheme):
    url = env(environ, f"{name}_URL")
    if not url:
      return None
    token = env(environ, f"{name}_API_TOKEN")
    if not token:
      raise ConfigError(f"{name}_URL is set but {name}_API_TOKEN isn't")
    return cls(url, token, scheme, env(environ, f"{name}_HOST"))

  # Raises on a non-2xx status. PATH may be a full URL the app built, like linkding's
  # `next`; only its path and query are used, since its host may not be the one we reach.
  def request(self, method, path, body=None, raw=False):
    parts = urllib.parse.urlsplit(path)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    headers = {"Authorization": self.auth}
    if self.host:
      headers["Host"] = self.host
    if body is not None:
      headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
      self.url + path,
      method=method,
      data=None if body is None else json.dumps(body).encode(),
      headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
      data = response.read()
    return data if raw else json.loads(data or "null")


def slug(article):
  """Filesystem-safe, and the id keeps two articles with one title apart."""
  base = re.sub(r"[^A-Za-z0-9]+", "-", article.get("title") or "")[:60].strip("-")
  return f"{base or 'article'}-{article['id']}"


def narration_lang(tag):
  """The article's language as Calliope's --lang: en_US, eng and EN all become en."""
  try:
    lang = langcodes.Language.get(tag or "").language
  except ValueError:
    return "en"
  # Bokmål and Nynorsk are both Norwegian to the TTS.
  lang = {"nb": "no", "nn": "no"}.get(lang, lang)
  return lang if lang in narrated_langs else "en"


def tagged(linkding, tag):
  """Every linkding bookmark tagged TAG."""
  # All pages first: retagging while paging would shift the offsets.
  query = urllib.parse.urlencode({"q": f"#{tag}", "limit": 100})
  bookmarks, url = [], f"/api/bookmarks/?{query}"
  while url:
    page = linkding.request("GET", url)
    bookmarks += page["results"]
    url = page.get("next")
  return bookmarks


def linkding_to_readeck(cfg, linkding, readeck):
  """Returns how many bookmarks failed, of how many."""
  bookmarks = tagged(linkding, cfg.toread_tag)

  # linkding ids Readeck has accepted. Readeck's API can't look a bookmark up by URL, so
  # this is what stops a retry after a failed retag from saving it twice.
  sent = cfg.state_dir / "sent"
  sent.touch()
  done = set(sent.read_text().split())
  failed = 0
  for bookmark in bookmarks:
    ld_id, link = str(bookmark["id"]), bookmark["url"]
    tags = [t for t in bookmark["tag_names"] if t != cfg.toread_tag]
    if ld_id in done:
      log(f"{link} (linkding {ld_id}) is already in Readeck; retagging only")
    else:
      body = {"url": link, "labels": tags}
      if bookmark.get("title"):
        body["title"] = bookmark["title"]
      try:
        readeck.request("POST", "/api/bookmarks", body)
      except OSError as e:
        warn(f"Readeck refused {link} (linkding {ld_id}): {e}; left tagged {cfg.toread_tag}")
        failed += 1
        continue
      with sent.open("a") as f:
        f.write(f"{ld_id}\n")
    try:
      linkding.request("PATCH", f"/api/bookmarks/{ld_id}/", {"tag_names": tags + [cfg.readeck_tag]})
    except OSError as e:
      warn(
        f"{link} is in Readeck, but retagging linkding {ld_id} failed: {e}; the next run retries it"
      )
      failed += 1
      continue
    log(f"handed off {link} (linkding {ld_id})")
  return failed, len(bookmarks)


def readeck_to_narrate(cfg, readeck):
  """Returns how many articles failed, of how many."""
  inbox = cfg.narrate_dir / "inbox"
  if not inbox.is_dir():
    log(f"no {inbox}; {cfg.listen_label} labels wait")
    return 0, 0
  # All pages first: relabelling while paging would shift the offsets.
  articles, limit = [], 50
  while True:
    query = urllib.parse.urlencode(
      {"labels": cfg.listen_label, "limit": limit, "offset": len(articles)}
    )
    page = readeck.request("GET", f"/api/bookmarks?{query}")
    articles += page
    if len(page) < limit:
      break

  failed = 0
  for article in articles:
    name, rd_id = slug(article), article["id"]
    # Already queued, narrated or failed by an earlier run whose relabel failed.
    done = [
      inbox / f"{name}.epub",
      cfg.readalouds_dir / cfg.narrate_collection / name,
      cfg.narrate_dir / "failed" / name,
      cfg.narrate_dir / "failed" / f"{name}.epub",
    ]
    if any(p.exists() for p in done):
      log(f"{name} is already queued or done; relabelling only")
    else:
      # Hidden temp names don't match the narrator's *.epub watch, so it never sees a
      # partial file. The spec lands first, so it's there when the EPUB appears.
      epub, spec = inbox / f".{name}.epub.tmp", inbox / f".{name}.json.tmp"
      try:
        epub.write_bytes(readeck.request("GET", f"/api/bookmarks/{rd_id}/article.epub", raw=True))
      except OSError as e:
        epub.unlink(missing_ok=True)
        warn(
          f"exporting {rd_id} ({article.get('title')}) failed: {e}; left labelled {cfg.listen_label}"
        )
        failed += 1
        continue
      spec.write_text(
        json.dumps(
          {"lang": narration_lang(article.get("lang")), "collection": cfg.narrate_collection}
        )
      )
      spec.rename(inbox / f"{name}.json")
      epub.rename(inbox / f"{name}.epub")
    try:
      readeck.request(
        "PATCH",
        f"/api/bookmarks/{rd_id}",
        {"remove_labels": [cfg.listen_label], "add_labels": [cfg.narrated_label]},
      )
    except OSError as e:
      warn(f"{name} is queued, but relabelling {rd_id} failed: {e}; the next run retries it")
      failed += 1
      continue
    log(f"queued {name} for narration")
  return failed, len(articles)


def linkding_to_video(cfg, linkding):
  """Returns how many bookmarks failed, of how many."""
  video_inbox = cfg.videos_dir / "inbox"
  if not video_inbox.is_dir():
    log(f"no {video_inbox}; {cfg.tolisten_tag} tags wait")
    return 0, 0
  bookmarks = tagged(linkding, cfg.tolisten_tag)

  failed = 0
  for bookmark in bookmarks:
    ld_id, link = bookmark["id"], bookmark["url"]
    title = bookmark.get("title") or bookmark.get("website_title") or ""
    name = slug({"title": title, "id": ld_id})
    tags = [t for t in bookmark["tag_names"] if t != cfg.tolisten_tag]
    # Already queued, transcribed or failed by an earlier run whose retag failed.
    done = [
      video_inbox / f"{name}.json",
      cfg.readalouds_dir / cfg.video_collection / name,
      cfg.videos_dir / "failed" / name,
    ]
    if any(p.exists() for p in done):
      log(f"{name} is already queued or done; retagging only")
    else:
      request = {"url": link, "title": title, "linkding_id": ld_id}
      lang = next(
        (t.split(":", 1)[1].lower() for t in tags if t.lower().startswith("lang:") and len(t) > 5),
        None,
      )
      if lang:
        request["lang"] = lang
      # A hidden temp name doesn't match the transcriber's *.json watch, so it never sees
      # a partial file.
      tmp = video_inbox / f".{name}.json.tmp"
      try:
        tmp.write_text(json.dumps(request))
        tmp.rename(video_inbox / f"{name}.json")
      except OSError as e:
        tmp.unlink(missing_ok=True)
        warn(f"queueing {link} (linkding {ld_id}) failed: {e}; left tagged {cfg.tolisten_tag}")
        failed += 1
        continue
    try:
      linkding.request(
        "PATCH", f"/api/bookmarks/{ld_id}/", {"tag_names": tags + [cfg.transcribed_tag]}
      )
    except OSError as e:
      warn(f"{name} is queued, but retagging linkding {ld_id} failed: {e}; the next run retries it")
      failed += 1
      continue
    log(f"queued {name} for transcription")
  return failed, len(bookmarks)


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
  # Each job runs whatever the others did: one app being down shouldn't hold up the rest.
  for job, apps, handoff in jobs:
    if None in apps:
      log(f"{job}: skipped, its apps aren't all configured")
      continue
    try:
      failed, total = handoff()
    except OSError as e:
      errors.append(f"{job}: {e}")
      continue
    if failed:
      errors.append(f"{job}: {failed} of {total} failed")
  return errors


def main():
  try:
    errors = run(os.environ)
  except ConfigError as e:
    errors = [str(e)]
  for error in errors:
    print(f"error: {error}", file=sys.stderr)
  sys.exit(1 if errors else 0)


if __name__ == "__main__":
  main()
