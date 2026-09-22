# IAM Playground agent lanes

ALWAYS treat this repo as two jobs: **contributors** change this repo; a **lab operator** runs the local lab. NEVER mix source edits with a scenario run or a live model trial unless the user named both.

## Position

- A **main** agent with no parent is **orchestrate**.
- A **subagent** is **implement**, or one **blind review lane**.
- Orchestrate composes review. NEVER run full multi-lane review as a parentless root.

## Lanes

| Lane | Who | May edit source | May run the lab |
| --- | --- | --- | --- |
| `orchestrate` | main | no | no |
| `implement` | subagent | yes | no |
| `review` | subagent parent of lanes | no | no |
| `lane-rules` | hidden blind | no | no |
| `lane-security` | hidden blind | no | no |
| `lane-completeness` | hidden blind | no | no |
| `lane-eng` | hidden blind | no | no |
| `lane-lab` | hidden blind | no | no |
| `lab-operator` | primary | no | yes, local lab only |

ALWAYS-on review lanes: **rules**, **security**, **completeness**.
When Python, TypeScript, Java, Docker, protocol, verifier, auth, or fixture code changes, also **eng** and **lab**.

Hidden lanes stay hidden unless the user asks for audit.

`lab-operator` runs `./lab` only. It does not edit the repo, does not use production IAM credentials, and does not call a model unless the user explicitly asked for a live trial. `up`, `doctor`, `endpoints`, `down`, `reset`, `scenario`, `test smoke`, and `export` are runnable. `jdbc verify` reports that the JDBC client is implemented and does not open a database. That exit is not a connection. Other unknown commands exit 2. A scenario exit of 2 is INDETERMINATE, not an unavailable command. Do not treat a scenario exit as publication proof.

## Proof

Do not claim a capability is implemented or verified while `docs/capabilities.md` says `planned`. Do not claim the repo is public-ready without a review verdict of `Proven for publication`. Default visibility is private.

NEVER log or commit passwords, bearer tokens, client secrets, authorization codes, cookies, or model API keys.

A doc or fixture edit is orchestrate then implement. Full hidden-lane review is for publication and for auth, verifier, target-protocol, and compose changes.

## Setup

`./lab up` starts the local lab. `./lab doctor`, `./lab endpoints`, `./lab down`, `./lab reset --fixture enterprise-small-v1`, `./lab scenario`, `./lab test smoke`, and `./lab export` are runnable. `./lab jdbc verify` reports that the JDBC client is implemented and does not open a database. Other unknown commands exit 2.

## Config

- OpenCode: `opencode.json` and `.opencode/agents/`
- Claude Code: `examples/claude.agents`, `examples/claude.settings.json`, skill at `.claude/skills/lab-operator/`
- Codex: `examples/codex.config.toml`
- `CLAUDE.md` mirrors this file

No Okta, Entra, Lumos, SailPoint, or ConductorOne server is part of this repo. The lab MCP routes are HTTP handlers mounted at `/mcp` on the admin process.
