# Threat model

**Status: proposed.** This is not a description of controls in code. No control listed here exists in the repository yet.

The intended lab is local and bound to loopback. It holds synthetic people only. Secrets are never exported. The verifier cannot provision. An agent cannot reset the lab or edit policy. Credentials for one application must not read or mutate another.

Loopback binding is not the whole security model. This document does not claim those boundaries are enforced.
