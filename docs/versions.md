# Versions

Pins used by Compose and `requirements.txt`. On 2026-09-22 a local Docker Compose v5.1.3 session on macOS started the images marked `started`. `pytest` 8.3.4 completed on the host (`59 passed`). The JDBC driver has not been used against a database. This is one machine, not a support matrix.

| Component | Version | Status |
| --- | --- | --- |
| PostgreSQL image | postgres:16.6 | started |
| Keycloak image | quay.io/keycloak/keycloak:26.0.7 | started |
| Python image | python:3.12.8-slim | started |
| FastAPI | 0.115.6 | imported by the API image |
| uvicorn | 0.34.0 | served the API image |
| SQLAlchemy | 2.0.36 | used by the API image |
| psycopg[binary] | 3.2.3 | used by the API image |
| pydantic | 2.10.4 | imported by the API image |
| httpx | 0.28.1 | locked; host tests import it |
| greenlet | 3.2.5 | required by SQLAlchemy on Linux |
| Workbench build image | node:22.14.0-alpine | built the workbench image |
| Workbench serve image | nginx:1.27.4-alpine | started |
| pytest | 8.3.4 | 59 passed on the host |
| OpenLDAP image | osixia/openldap:1.5.0 | started |
| PostgreSQL JDBC driver | 42.7.5 | pinned in `clients/jdbc/pom.xml`; not connected |

There is no MCP SDK. The lab MCP routes are HTTP handlers in `backend/iam_playground/mcp_pack`.
