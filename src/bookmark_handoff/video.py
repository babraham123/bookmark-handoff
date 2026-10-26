# The linkding to video handoff.

import json

from .app import tagged
from .util import log, slug, warn


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
