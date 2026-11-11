# MVP implementation plan
1. Dedicated src Git repository; preserve input notes; real SDK experiment.
2. SQLite is the durable business checkpoint; LangGraph executes one stage, then atomically persists stage and result.
3. Separate Dev/Test/verification worktrees; pinned verification commit; one evidence-driven repair.
4. localhost FastAPI worker; CLI and Streamlit call API only.
5. Automated control/security tests; distinguish real acceptance from isolated tests and blockers.

Layout: ai_manager/, adapter/, tests/, scripts/, docs/.
Deferred: independent Reviewer, architect council, parallel scenarios, deployment, Service Fabric E2E, arbitrary commands.
