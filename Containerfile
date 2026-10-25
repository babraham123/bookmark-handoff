# bookmark_handoff.py with its pinned libraries. requirements.txt pins them by hash:
#   uv pip compile --generate-hashes --universal requirements.in -o requirements.txt
FROM docker.io/library/python:3.14-alpine
ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY bookmark_handoff.py /usr/local/bin/bookmark_handoff.py
ENTRYPOINT ["python3", "/usr/local/bin/bookmark_handoff.py"]
