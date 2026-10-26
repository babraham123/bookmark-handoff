# linkding's and Readeck's REST APIs.

import json
import urllib.parse
import urllib.request

from .config import ConfigError, env


class App:
  """One app's REST API. HOST, when set, is sent as the Host header, so the app can be
  reached on an internal address under its public host name."""

  def __init__(self, url, token, scheme, host=None):
    self.url = url.rstrip("/")
    self.host = host
    self.auth = f"{scheme} {token}"

  # Usage: App.from_env(environ, NAME, SCHEME); None when NAME_URL isn't set
  @classmethod
  def from_env(cls, environ, name, scheme):
    url = env(environ, f"{name}_URL")
    if not url:
      return None
    token = env(environ, f"{name}_API_TOKEN")
    if not token:
      raise ConfigError(f"{name}_URL is set but {name}_API_TOKEN isn't")
    return cls(url, token, scheme, env(environ, f"{name}_HOST"))

  # Raises on a non-2xx status. PATH may be a full URL the app built, like linkding's
  # `next`; only its path and query are used, since its host may not be the one we reach.
  def request(self, method, path, body=None, raw=False):
    parts = urllib.parse.urlsplit(path)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    headers = {"Authorization": self.auth}
    if self.host:
      headers["Host"] = self.host
    if body is not None:
      headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
      self.url + path,
      method=method,
      data=None if body is None else json.dumps(body).encode(),
      headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
      data = response.read()
    return data if raw else json.loads(data or "null")


def tagged(linkding, tag):
  """Every linkding bookmark tagged TAG."""
  # All pages first: retagging while paging would shift the offsets.
  query = urllib.parse.urlencode({"q": f"#{tag}", "limit": 100})
  bookmarks, url = [], f"/api/bookmarks/?{query}"
  while url:
    page = linkding.request("GET", url)
    bookmarks += page["results"]
    url = page.get("next")
  return bookmarks
