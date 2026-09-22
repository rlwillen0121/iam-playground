Follow [AGENTS.md](AGENTS.md). Same lanes.

Contributors: orchestrate, then implement, then review when the proof section requires it.

Operators: lab-operator, local lab only, no source edits.

Never log passwords, bearer tokens, client secrets, authorization codes, cookies, or model API keys.

`./lab up`, `doctor`, `endpoints`, `down`, `reset`, `scenario`, `test smoke`, and `export` are runnable. `jdbc verify` reports that the JDBC client is implemented and does not open a database. Other unknown commands exit 2. A scenario exit of 2 is INDETERMINATE, not an unavailable command.
