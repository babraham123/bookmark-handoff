# bookmark-handoff

bookmark-handoff moves bookmarks between self-hosted reading apps by tag, so saving a link once
is enough to read it in [Readeck](https://readeck.org/) or have it narrated:

| From | Tag or label | To | Then tagged |
|---|---|---|---|
| [linkding](https://github.com/sissbruecker/linkding) | `toread` | Readeck, with the bookmark's other tags as labels | `readeck` |
| Readeck | `listen` | the narration inbox, as `<slug>.epub` plus `<slug>.json` | `narrated` |
| linkding (YouTube videos) | `tolisten` | the video inbox, as `<slug>.json` | `transcribed` |

Each run is one pass over all three; run it from a timer or cron every few minutes. An item whose
handoff fails keeps its tag or label, and the next run retries it. A job whose apps aren't
configured, or whose inbox directory doesn't exist yet, is skipped, so it runs fine with only
linkding and Readeck.

The inboxes are plain directories for a batch job to watch, like
[TTS-Narrated-Ebook-Creator](https://github.com/babraham123/TTS-Narrated-Ebook-Creator) (Calliope)
for articles and [yt-to-audiobook](https://github.com/babraham123/yt-to-audiobook) for videos.

## Run

```bash
podman build -t bookmark-handoff -f Containerfile .
podman run --rm \
  -e LINKDING_URL=http://linkding:9090 -e LINKDING_API_TOKEN=... \
  -e READECK_URL=http://readeck:8000 -e READECK_API_TOKEN=... \
  -v ./state:/state -v /srv/media/books:/books \
  bookmark-handoff
```

Or without the image (Python 3.10+):

```bash
pip install --require-hashes -r requirements.txt
STATE_DIR=./state BOOKS_DIR=./books LINKDING_URL=... LINKDING_API_TOKEN=... ./bookmark_handoff.py
```

It exits 1 if any item or job failed, with the reasons on stderr.

## Configuration

All by environment variable.

| Variable | Default | |
|---|---|---|
| `LINKDING_URL` | | linkding's base URL; unset skips both linkding jobs |
| `LINKDING_API_TOKEN` | | linkding's REST API token (Settings → Integrations); required with the URL |
| `LINKDING_HOST` | | Host header to send, when the URL is an internal address the app only answers under its public name |
| `READECK_URL`, `READECK_API_TOKEN`, `READECK_HOST` | | The same for Readeck; unset skips both Readeck jobs |
| `TOREAD_TAG` | `toread` | linkding tag that sends a bookmark to Readeck |
| `READECK_TAG` | `readeck` | linkding tag it gets once Readeck has it |
| `LISTEN_LABEL` | `listen` | Readeck label that sends an article to narration |
| `NARRATED_LABEL` | `narrated` | Readeck label it gets once queued |
| `TOLISTEN_TAG` | `tolisten` | linkding tag that sends a video to transcription |
| `TRANSCRIBED_TAG` | `transcribed` | linkding tag it gets once queued |
| `BOOKS_DIR` | `/books` | Base for the three directories below |
| `NARRATE_DIR` | `$BOOKS_DIR/narrate` | Narration's `inbox/` and `failed/` |
| `VIDEOS_DIR` | `$BOOKS_DIR/videos` | Transcription's `inbox/` and `failed/` |
| `READALOUDS_DIR` | `$BOOKS_DIR/readalouds` | Finished books, one directory per collection |
| `NARRATE_COLLECTION` | `articles` | Collection named in each article's spec |
| `VIDEO_COLLECTION` | `videos` | Collection the transcriber writes videos into |
| `STATE_DIR` | `/state` | Holds `sent`, the linkding ids Readeck has accepted |

## Inbox contract

Files land under hidden temp names (`.<slug>.json.tmp`) and are renamed into place, so a watcher
matching `*.epub` or `*.json` never sees a partial file. `<slug>` is the title's letters and
digits joined by `-`, cut to 60 characters, then the bookmark's id.

- **Narration**: `<slug>.json` is `{"lang": "de", "collection": "articles"}`, and lands before
  `<slug>.epub`, Readeck's EPUB export of the article. `lang` is the article's language reduced to
  a two-letter code the narrator ([Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox))
  supports, or `en`.
- **Video**: `<slug>.json` is `{"url", "title", "linkding_id", "lang"}`; `lang` is there only when
  the bookmark has a `lang:xx` tag, which stays on the bookmark.

An item is only retagged, not queued again, once its `<slug>` is in the inbox, under
`$READALOUDS_DIR/<collection>/`, or under the inbox's sibling `failed/`. Readeck's API can't look
a bookmark up by URL, so `$STATE_DIR/sent` does the same for the Readeck handoff.

## Development

```bash
uv run --no-project --with-requirements requirements.txt python -m unittest discover -s tests
```

The tests run each handoff against in-memory fakes of the linkding and Readeck APIs. Update the
pinned libraries with:

```bash
uv pip compile --generate-hashes --universal requirements.in -o requirements.txt
```

## License

[MIT](LICENSE)
