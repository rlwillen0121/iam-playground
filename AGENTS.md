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

`lab-operator` runs `./lab` only. It does not edit the repo, does not use production IAM credentials, and does not call a model unless the user explicitly asked for a live trial. Today every lab command exits 2.

## Proof

Do not claim a capability is implemented or verified while `docs/capabilities.md` says `planned`. Do not claim the repo is public-ready without a review verdict of `Proven for publication`. Default visibility is private.

NEVER log or commit passwords, bearer tokens, client secrets, authorization codes, cookies, or model API keys.

A doc or fixture edit is orchestrate then implement. Full hidden-lane review is for publication and for auth, verifier, target-protocol, and compose changes.

## Setup

Today: `./lab doctor` (exits 2). The spec's other `./lab` commands are the intended interface and are not runnable.

## Config

- OpenCode: `opencode.json` and `.opencode/agents/`
- Claude Code: `examples/claude.agents`, `examples/claude.settings.json`, skill at `.claude/skills/lab-operator/`
- Codex: `examples/codex.config.toml`
- `CLAUDE.md` mirrors this file

No identity-provider MCP servers are part of this repo. The optional lab MCP pack is v0.2 and is not configured.
