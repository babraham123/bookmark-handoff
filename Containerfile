# bookmark_handoff's zipapp, with the libraries requirements.txt pins by hash vendored in:
#   uv pip compile --generate-hashes --universal requirements.in -o requirements.txt
FROM docker.io/library/python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd AS build
COPY build.py requirements.txt /build/
COPY src /build/src
RUN python3 /build/build.py /bookmark_handoff

FROM docker.io/library/python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd
# Nothing installs at run time, and pip's vendored urllib3 and msgpack would fail the scan
# gate.
RUN python3 -m pip uninstall -y pip
COPY --from=build /bookmark_handoff /usr/local/bin/bookmark_handoff
ENTRYPOINT ["python3", "/usr/local/bin/bookmark_handoff"]
