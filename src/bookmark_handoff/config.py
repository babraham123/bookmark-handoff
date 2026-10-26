# The run's configuration, from environment variables.

from dataclasses import dataclass
from pathlib import Path


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
