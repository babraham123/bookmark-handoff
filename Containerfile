# bookmark_handoff's zipapp, with the libraries requirements.txt pins by hash vendored in:
#   uv pip compile --generate-hashes --universal requirements.in -o requirements.txt
FROM docker.io/library/python:3.14-alpine AS build
COPY build.py requirements.txt /build/
COPY src /build/src
RUN python3 /build/build.py /bookmark_handoff

FROM docker.io/library/python:3.14-alpine
COPY --from=build /bookmark_handoff /usr/local/bin/bookmark_handoff
ENTRYPOINT ["python3", "/usr/local/bin/bookmark_handoff"]
