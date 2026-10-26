# The linkding to Readeck handoff, and the state that keeps a retry from saving twice.

from .app import tagged
from .util import log, warn


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
