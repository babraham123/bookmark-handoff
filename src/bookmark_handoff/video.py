# The linkding to video handoff.

import json

from .app import tagged, tags_without
from .util import hand_off_each, log, slug, warn


def lang_tag_case(tag):
  """TAG in BCP 47's case: lowercase language, uppercase region, title-case script, so
  pt-br becomes pt-BR, the key YouTube lists its captions under. Only the case changes:
  standardizing would also rewrite codes like iw, which YouTube still uses for Hebrew."""
  lang, *subtags = tag.split("-")
  return "-".join(
    [lang.lower()]
    + [s.upper() if len(s) == 2 else s.title() if len(s) == 4 else s.lower() for s in subtags]
  )


def linkding_to_video(cfg, linkding):
  """Returns how many bookmarks failed, of how many."""
  video_inbox = cfg.videos_dir / "inbox"
  if not video_inbox.is_dir():
    log(f"no {video_inbox}; {cfg.tolisten_tag} tags wait")
    return 0, 0
  bookmarks = tagged(linkding, cfg.tolisten_tag)

  def hand_off(bookmark):
    ld_id, link = bookmark["id"], bookmark["url"]
    title = bookmark.get("title") or bookmark.get("website_title") or ""
    name = slug({"title": title, "id": ld_id})
    tags = tags_without(bookmark, cfg.tolisten_tag)
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
        (
          lang_tag_case(t.split(":", 1)[1])
          for t in tags
          if t.lower().startswith("lang:") and len(t) > 5
        ),
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
        return False
    try:
      linkding.request(
        "PATCH", f"/api/bookmarks/{ld_id}/", {"tag_names": tags + [cfg.transcribed_tag]}
      )
    except OSError as e:
      warn(f"{name} is queued, but retagging linkding {ld_id} failed: {e}; the next run retries it")
      return False
    log(f"queued {name} for transcription")
    return True

  return hand_off_each(bookmarks, "linkding bookmark", hand_off)
