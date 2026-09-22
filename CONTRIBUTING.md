# Contributing

Follow [AGENTS.md](AGENTS.md).

Orchestrate plans. Implement edits. Review runs before a publication claim and when auth, verifier, target protocol, or compose files change.

A small doc change still uses those lanes (orchestrate, then implement). It does not need every hidden lane unless the publication rule applies.

## Tests

`./lab doctor` must exit 2 today. `tests/lab_stub_test.sh` checks that stub.

Do not mark a capability verified without a test ID. While [docs/capabilities.md](docs/capabilities.md) says `planned`, the capability is not implemented and not verified.
