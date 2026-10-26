# The Readeck to narration handoff, and the language each article is read in.

import json
import urllib.parse

import langcodes

from .util import log, slug, warn

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


def narration_lang(tag):
  """The article's language as Calliope's --lang: en_US, eng and EN all become en."""
  try:
    lang = langcodes.Language.get(tag or "").language
  except ValueError:
    return "en"
  # Bokmål and Nynorsk are both Norwegian to the TTS.
  lang = {"nb": "no", "nn": "no"}.get(lang, lang)
  return lang if lang in narrated_langs else "en"


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
