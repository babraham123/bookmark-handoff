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
