# External client

`walkthrough.py` is the external-client example. It does not run itself.

It uses `urllib` to GET `/hr/changes` and POST to a target base URL passed in. It does not import the playground package. It does not open a database. Importing the module does not read HR and does not POST anywhere.

The caller supplies both URLs. Nothing is read from the environment. The client does not follow redirects and does not use proxy environment variables. A non-success status raises `WalkthroughError`. A connection failure raises `urllib.error.URLError`.

```python
from walkthrough import Walkthrough

client = Walkthrough("http://127.0.0.1:8090")
changes = client.get_changes(0)
client.post_target("http://127.0.0.1:9000", changes)
```

`post_target` posts to the target base URL it is given. It does not rewrite that URL into an HR path. HR changes are not target-account writes; a target change happens only when the caller invokes `post_target` or `apply`.
