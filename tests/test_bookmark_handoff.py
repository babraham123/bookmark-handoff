"""Each handoff against in-memory fakes of the linkding and Readeck APIs and a temp
directory for the inboxes and state. No live services."""

import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bookmark_handoff as bh  # noqa: E402


class FakeLinkding:
  """linkding's /api/bookmarks/: `#tag` search with offset paging, and PATCH of tag_names."""

  def __init__(self, bookmarks, page_size=100, fail_patch=(), down=False):
    self.bookmarks = {b["id"]: b for b in copy.deepcopy(bookmarks)}
    self.page_size, self.fail_patch, self.down = page_size, set(fail_patch), down

  def request(self, method, path, body=None, raw=False):
    if self.down:
      raise ConnectionRefusedError("linkding is down")
    parts = urllib.parse.urlsplit(path)
    if method == "GET":
      query = urllib.parse.parse_qs(parts.query)
      tag = query["q"][0].removeprefix("#")
      offset = int(query.get("offset", ["0"])[0])
      matches = [b for b in self.bookmarks.values() if tag in b["tag_names"]]
      end = offset + self.page_size
      # linkding's `next` is an absolute URL on its public host name.
      next_url = None
      if end < len(matches):
        next_query = urllib.parse.urlencode(
          {"q": f"#{tag}", "limit": self.page_size, "offset": end}
        )
        next_url = f"https://archive.example.com/api/bookmarks/?{next_query}"
      return {"results": copy.deepcopy(matches[offset:end]), "next": next_url}
    if method == "PATCH":
      ld_id = int(parts.path.split("/")[3])
      if ld_id in self.fail_patch:
        raise ConnectionResetError("PATCH failed")
      self.bookmarks[ld_id]["tag_names"] = list(body["tag_names"])
      return self.bookmarks[ld_id]
    raise AssertionError(f"unexpected linkding {method} {path}")

  def tags(self, ld_id):
    return self.bookmarks[ld_id]["tag_names"]


class FakeReadeck:
  """Readeck's /api/bookmarks: POST, label search with offset paging, EPUB export, and
  PATCH of labels."""

  def __init__(self, articles=(), fail_post=False, fail_export=(), fail_patch=()):
    self.articles = {a["id"]: a for a in copy.deepcopy(list(articles))}
    self.fail_post, self.fail_export, self.fail_patch = fail_post, set(fail_export), set(fail_patch)
    self.posted = []

  def request(self, method, path, body=None, raw=False):
    parts = urllib.parse.urlsplit(path)
    if method == "POST" and parts.path == "/api/bookmarks":
      if self.fail_post:
        raise ConnectionRefusedError("Readeck refused")
      self.posted.append(body)
      return None
    if method == "GET" and parts.path == "/api/bookmarks":
      query = urllib.parse.parse_qs(parts.query)
      label = query["labels"][0]
      limit, offset = int(query["limit"][0]), int(query["offset"][0])
      matches = [a for a in self.articles.values() if label in a["labels"]]
      return copy.deepcopy(matches[offset : offset + limit])
    if method == "GET" and parts.path.endswith("/article.epub"):
      rd_id = parts.path.split("/")[3]
      if rd_id in self.fail_export:
        raise ConnectionResetError("export failed")
      assert raw
      return f"epub of {rd_id}".encode()
    if method == "PATCH":
      rd_id = parts.path.split("/")[3]
      if rd_id in self.fail_patch:
        raise ConnectionResetError("PATCH failed")
      labels = self.articles[rd_id]["labels"]
      labels[:] = [x for x in labels if x not in body["remove_labels"]] + body["add_labels"]
      return None
    raise AssertionError(f"unexpected Readeck {method} {path}")

  def labels(self, rd_id):
    return self.articles[rd_id]["labels"]


class HandoffTest(unittest.TestCase):
  def setUp(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.root = Path(tmp.name)
    self.books = self.root / "books"
    (self.books / "narrate/inbox").mkdir(parents=True)
    (self.books / "videos/inbox").mkdir(parents=True)
    (self.root / "state").mkdir()
    self.environ = {"BOOKS_DIR": str(self.books), "STATE_DIR": str(self.root / "state")}
    # The jobs log every item; keep the test output to the results.
    self.enterContext(redirect_stdout(io.StringIO()))
    self.enterContext(redirect_stderr(io.StringIO()))

  def cfg(self, **env):
    return bh.Config.from_env({**self.environ, **env})

  def inbox(self, kind):
    return sorted(p.name for p in (self.books / kind / "inbox").iterdir())


class LinkdingToReadeckTest(HandoffTest):
  def test_toread_bookmark_moves_to_readeck_and_is_retagged(self):
    linkding = FakeLinkding(
      [
        {"id": 1, "url": "https://a.example/1", "title": "One", "tag_names": ["toread", "news"]},
        {"id": 2, "url": "https://a.example/2", "title": "", "tag_names": ["toread"]},
        {"id": 3, "url": "https://a.example/3", "title": "Other", "tag_names": ["news"]},
      ]
    )
    readeck = FakeReadeck()

    self.assertEqual(bh.linkding_to_readeck(self.cfg(), linkding, readeck), (0, 2))

    self.assertEqual(
      readeck.posted,
      [
        {"url": "https://a.example/1", "labels": ["news"], "title": "One"},
        {"url": "https://a.example/2", "labels": []},
      ],
    )
    self.assertEqual(linkding.tags(1), ["news", "readeck"])
    self.assertEqual(linkding.tags(2), ["readeck"])
    self.assertEqual(linkding.tags(3), ["news"])
    self.assertEqual((self.root / "state/sent").read_text().split(), ["1", "2"])

  def test_every_page_is_read_before_retagging(self):
    bookmarks = [
      {"id": i, "url": f"https://a.example/{i}", "tag_names": ["toread"]} for i in range(1, 6)
    ]
    linkding = FakeLinkding(bookmarks, page_size=2)
    readeck = FakeReadeck()

    self.assertEqual(bh.linkding_to_readeck(self.cfg(), linkding, readeck), (0, 5))
    self.assertEqual(len(readeck.posted), 5)
    for i in range(1, 6):
      self.assertEqual(linkding.tags(i), ["readeck"])

  def test_refused_bookmark_stays_toread(self):
    linkding = FakeLinkding([{"id": 1, "url": "https://a.example/1", "tag_names": ["toread"]}])

    self.assertEqual(
      bh.linkding_to_readeck(self.cfg(), linkding, FakeReadeck(fail_post=True)), (1, 1)
    )
    self.assertEqual(linkding.tags(1), ["toread"])
    self.assertEqual((self.root / "state/sent").read_text(), "")

  def test_failed_retag_is_retried_without_saving_twice(self):
    bookmark = {"id": 7, "url": "https://a.example/7", "tag_names": ["toread"]}
    linkding, readeck = FakeLinkding([bookmark], fail_patch={7}), FakeReadeck()
    self.assertEqual(bh.linkding_to_readeck(self.cfg(), linkding, readeck), (1, 1))
    self.assertEqual(linkding.tags(7), ["toread"])

    linkding.fail_patch.clear()
    self.assertEqual(bh.linkding_to_readeck(self.cfg(), linkding, readeck), (0, 1))
    self.assertEqual(len(readeck.posted), 1)
    self.assertEqual(linkding.tags(7), ["readeck"])

  def test_tag_names_come_from_the_environment(self):
    linkding = FakeLinkding(
      [{"id": 1, "url": "https://a.example/1", "tag_names": ["later", "toread"]}]
    )
    readeck = FakeReadeck()
    cfg = self.cfg(TOREAD_TAG="later", READECK_TAG="in-readeck")

    self.assertEqual(bh.linkding_to_readeck(cfg, linkding, readeck), (0, 1))
    self.assertEqual(readeck.posted[0]["labels"], ["toread"])
    self.assertEqual(linkding.tags(1), ["toread", "in-readeck"])


class ReadeckToNarrateTest(HandoffTest):
  def test_listen_article_lands_in_the_inbox_with_its_spec(self):
    readeck = FakeReadeck(
      [
        {"id": "abc", "title": "A Long Read: Part 1", "lang": "de-AT", "labels": ["listen", "x"]},
        {"id": "def", "title": "Other", "lang": "en", "labels": ["x"]},
      ]
    )

    self.assertEqual(bh.readeck_to_narrate(self.cfg(), readeck), (0, 1))

    name = "A-Long-Read-Part-1-abc"
    inbox = self.books / "narrate/inbox"
    self.assertEqual(self.inbox("narrate"), [f"{name}.epub", f"{name}.json"])
    self.assertEqual((inbox / f"{name}.epub").read_bytes(), b"epub of abc")
    self.assertEqual(
      json.loads((inbox / f"{name}.json").read_text()), {"lang": "de", "collection": "articles"}
    )
    self.assertEqual(readeck.labels("abc"), ["x", "narrated"])
    self.assertEqual(readeck.labels("def"), ["x"])

  def test_every_page_is_read_before_relabelling(self):
    readeck = FakeReadeck([{"id": f"a{i}", "title": "t", "labels": ["listen"]} for i in range(120)])
    self.assertEqual(bh.readeck_to_narrate(self.cfg(), readeck), (0, 120))
    self.assertEqual(len(self.inbox("narrate")), 240)

  def test_missing_inbox_skips_the_job(self):
    (self.books / "narrate/inbox").rmdir()
    readeck = FakeReadeck([{"id": "abc", "title": "t", "labels": ["listen"]}])

    self.assertEqual(bh.readeck_to_narrate(self.cfg(), readeck), (0, 0))
    self.assertEqual(readeck.labels("abc"), ["listen"])

  def test_already_narrated_article_is_only_relabelled(self):
    (self.books / "readalouds/articles/T-abc").mkdir(parents=True)
    readeck = FakeReadeck([{"id": "abc", "title": "T", "labels": ["listen"]}], fail_export={"abc"})

    self.assertEqual(bh.readeck_to_narrate(self.cfg(), readeck), (0, 1))
    self.assertEqual(self.inbox("narrate"), [])
    self.assertEqual(readeck.labels("abc"), ["narrated"])

  def test_failed_export_leaves_no_partial_file_and_keeps_the_label(self):
    readeck = FakeReadeck([{"id": "abc", "title": "T", "labels": ["listen"]}], fail_export={"abc"})

    self.assertEqual(bh.readeck_to_narrate(self.cfg(), readeck), (1, 1))
    self.assertEqual(self.inbox("narrate"), [])
    self.assertEqual(readeck.labels("abc"), ["listen"])

  def test_paths_collection_and_labels_come_from_the_environment(self):
    narrate = self.root / "elsewhere"
    (narrate / "inbox").mkdir(parents=True)
    readeck = FakeReadeck([{"id": "abc", "title": "T", "labels": ["tts"]}])
    cfg = self.cfg(
      NARRATE_DIR=str(narrate),
      NARRATE_COLLECTION="essays",
      LISTEN_LABEL="tts",
      NARRATED_LABEL="spoken",
    )

    self.assertEqual(bh.readeck_to_narrate(cfg, readeck), (0, 1))
    self.assertEqual(json.loads((narrate / "inbox/T-abc.json").read_text())["collection"], "essays")
    self.assertEqual(readeck.labels("abc"), ["spoken"])

  def test_narration_lang(self):
    for tag, lang in [
      ("en_US", "en"),
      ("eng", "en"),
      ("EN", "en"),
      ("fr-CA", "fr"),
      ("nb", "no"),
      ("nn-NO", "no"),
      ("vi", "en"),
      ("", "en"),
      (None, "en"),
      ("not a tag!", "en"),
    ]:
      with self.subTest(tag=tag):
        self.assertEqual(bh.narration_lang(tag), lang)


class LinkdingToVideoTest(HandoffTest):
  def test_tolisten_bookmark_lands_in_the_video_inbox(self):
    linkding = FakeLinkding(
      [
        {
          "id": 4,
          "url": "https://youtu.be/x",
          "title": "",
          "website_title": "A Talk",
          "tag_names": ["tolisten", "lang:DE", "talks"],
        },
        {"id": 5, "url": "https://youtu.be/y", "title": "Plain", "tag_names": ["tolisten"]},
      ]
    )

    self.assertEqual(bh.linkding_to_video(self.cfg(), linkding), (0, 2))

    inbox = self.books / "videos/inbox"
    self.assertEqual(self.inbox("videos"), ["A-Talk-4.json", "Plain-5.json"])
    self.assertEqual(
      json.loads((inbox / "A-Talk-4.json").read_text()),
      {"url": "https://youtu.be/x", "title": "A Talk", "linkding_id": 4, "lang": "de"},
    )
    self.assertEqual(
      json.loads((inbox / "Plain-5.json").read_text()),
      {"url": "https://youtu.be/y", "title": "Plain", "linkding_id": 5},
    )
    self.assertEqual(linkding.tags(4), ["lang:DE", "talks", "transcribed"])
    self.assertEqual(linkding.tags(5), ["transcribed"])

  def test_already_transcribed_video_is_only_retagged(self):
    (self.books / "readalouds/videos/V-4").mkdir(parents=True)
    linkding = FakeLinkding(
      [{"id": 4, "url": "https://youtu.be/x", "title": "V", "tag_names": ["tolisten"]}]
    )

    self.assertEqual(bh.linkding_to_video(self.cfg(), linkding), (0, 1))
    self.assertEqual(self.inbox("videos"), [])
    self.assertEqual(linkding.tags(4), ["transcribed"])

  def test_failed_retag_keeps_the_request_queued(self):
    linkding = FakeLinkding(
      [{"id": 4, "url": "https://youtu.be/x", "title": "V", "tag_names": ["tolisten"]}],
      fail_patch={4},
    )

    self.assertEqual(bh.linkding_to_video(self.cfg(), linkding), (1, 1))
    self.assertEqual(self.inbox("videos"), ["V-4.json"])
    self.assertEqual(linkding.tags(4), ["tolisten"])

  def test_missing_inbox_skips_the_job(self):
    (self.books / "videos/inbox").rmdir()
    linkding = FakeLinkding([{"id": 4, "url": "https://youtu.be/x", "tag_names": ["tolisten"]}])

    self.assertEqual(bh.linkding_to_video(self.cfg(), linkding), (0, 0))
    self.assertEqual(linkding.tags(4), ["tolisten"])


APPS = {
  "LINKDING_URL": "http://linkding:9090",
  "LINKDING_API_TOKEN": "ld",
  "READECK_URL": "http://readeck:8000",
  "READECK_API_TOKEN": "rd",
}


class RunTest(HandoffTest):
  def run_with(self, environ, linkding=None, readeck=None):
    """run() with the apps NAME_URL configures replaced by the fakes."""
    real = bh.App.from_env

    def from_env(env, name, scheme):
      app = real(env, name, scheme)
      return app and {"LINKDING": linkding, "READECK": readeck}[name]

    with mock.patch.object(bh.App, "from_env", side_effect=from_env):
      return bh.run({**self.environ, **environ})

  def test_one_app_down_does_not_hold_up_the_others(self):
    linkding = FakeLinkding([], down=True)
    readeck = FakeReadeck([{"id": "abc", "title": "T", "labels": ["listen"]}])

    errors = self.run_with(APPS, linkding, readeck)

    self.assertEqual(
      errors, ["linkding to Readeck: linkding is down", "linkding to video: linkding is down"]
    )
    self.assertEqual(readeck.labels("abc"), ["narrated"])

  def test_failures_are_counted_per_job(self):
    linkding = FakeLinkding([{"id": 1, "url": "https://a.example/1", "tag_names": ["toread"]}])
    errors = self.run_with(APPS, linkding, FakeReadeck(fail_post=True))
    self.assertEqual(errors, ["linkding to Readeck: 1 of 1 failed"])

  def test_jobs_without_their_apps_are_skipped(self):
    linkding = FakeLinkding(
      [
        {"id": 1, "url": "https://a.example/1", "tag_names": ["toread"]},
        {"id": 2, "url": "https://youtu.be/x", "title": "V", "tag_names": ["tolisten"]},
      ]
    )
    environ = {k: v for k, v in APPS.items() if k.startswith("LINKDING")}

    self.assertEqual(self.run_with(environ, linkding), [])
    self.assertEqual(linkding.tags(1), ["toread"])
    self.assertEqual(linkding.tags(2), ["transcribed"])

  def test_url_without_token_is_a_config_error(self):
    with self.assertRaisesRegex(bh.ConfigError, "READECK_API_TOKEN"):
      bh.run({**self.environ, "READECK_URL": "http://readeck:8000"})

  def test_main_exits_nonzero_on_errors(self):
    with (
      mock.patch.dict(bh.os.environ, {"READECK_URL": "http://readeck:8000"}, clear=True),
      self.assertRaises(SystemExit) as exit,
    ):
      bh.main()
    self.assertEqual(exit.exception.code, 1)


class AppTest(unittest.TestCase):
  def request(self, app, *args, response=b'{"ok": true}', **kwargs):
    sent = []

    class Response(io.BytesIO):
      def __enter__(self):
        return self

      def __exit__(self, *exc):
        return False

    def urlopen(request, timeout):
      sent.append(request)
      return Response(response)

    with mock.patch.object(bh.urllib.request, "urlopen", side_effect=urlopen):
      result = app.request(*args, **kwargs)
    return sent[0], result

  def test_absolute_url_is_sent_to_the_configured_address_and_host(self):
    app = bh.App.from_env(
      {
        "LINKDING_URL": "http://10.0.0.17:9090/",
        "LINKDING_API_TOKEN": " t0k \n",
        "LINKDING_HOST": "archive.example.com:9090",
      },
      "LINKDING",
      "Token",
    )

    request, result = self.request(
      app, "GET", "https://archive.example.com/api/bookmarks/?q=%23toread&offset=100"
    )

    self.assertEqual(result, {"ok": True})
    self.assertEqual(
      request.full_url, "http://10.0.0.17:9090/api/bookmarks/?q=%23toread&offset=100"
    )
    self.assertEqual(request.get_method(), "GET")
    self.assertEqual(request.get_header("Host"), "archive.example.com:9090")
    self.assertEqual(request.get_header("Authorization"), "Token t0k")
    self.assertIsNone(request.data)

  def test_json_body_and_no_host_override_by_default(self):
    app = bh.App("http://readeck:8000", "abc", "Bearer")

    request, result = self.request(
      app, "PATCH", "/api/bookmarks/x", {"add_labels": ["a"]}, response=b""
    )

    self.assertIsNone(result)
    self.assertEqual(request.full_url, "http://readeck:8000/api/bookmarks/x")
    self.assertIsNone(request.get_header("Host"))
    self.assertEqual(request.get_header("Authorization"), "Bearer abc")
    self.assertEqual(request.get_header("Content-type"), "application/json")
    self.assertEqual(json.loads(request.data), {"add_labels": ["a"]})

  def test_raw_returns_bytes(self):
    _, result = self.request(
      bh.App("http://r", "t", "Bearer"), "GET", "/x.epub", raw=True, response=b"PK\x03\x04"
    )
    self.assertEqual(result, b"PK\x03\x04")


if __name__ == "__main__":
  unittest.main()
