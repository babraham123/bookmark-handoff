#!/usr/bin/env python3
# Builds dist/bookmark_handoff: the package in src/ and the libraries requirements.txt pins,
# as one executable zipapp, which the Containerfile installs as /usr/local/bin/bookmark_handoff.
# Needs pip, and network access unless pip's cache has the pinned wheels.
# Usage:
#   python3 build.py [OUTPUT]

import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(output=ROOT / "dist" / "bookmark_handoff"):
  output = Path(output)
  output.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.TemporaryDirectory() as stage:
    # zipapp doesn't vendor dependencies, so they go in beside the package. The hashes pin
    # them as they do for the image; wheels only, so nothing is built.
    subprocess.run(
      [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        "--require-hashes",
        "--no-deps",
        "--only-binary",
        ":all:",
        "--no-compile",
        "--target",
        stage,
        "-r",
        ROOT / "requirements.txt",
      ],
      check=True,
    )
    shutil.copytree(ROOT / "src" / "bookmark_handoff", Path(stage) / "bookmark_handoff")
    zipapp.create_archive(
      stage,
      output,
      interpreter="/usr/bin/env python3",
      main="bookmark_handoff.cli:entry",
      filter=lambda path: "__pycache__" not in path.parts,
    )
  return output


if __name__ == "__main__":
  print(build(*sys.argv[1:]))
