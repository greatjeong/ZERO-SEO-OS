# ZERO SEO OS development continuity

Read `docs/개발기준-로드맵.md` before continuing development or describing progress.

The user explicitly requires development to stay aligned with the provided roadmaps. There are two distinct schemes: the technical foundation plan (A-01..A-04 then phases B..E), and the overall business execution roadmap (01..13, with 53 original checklist items). Do not merge their numbering or assume earlier business stages are complete. Current technical main stage: A-02, in progress, not complete. A-1/A-2 are site slots, distinct from development phases A-01/A-02. Version numbers are not phase numbers.

Before implementing a new task, explain which roadmap item it serves. Stay within the user's authorized task. Record out-of-phase work separately; do not advance the main phase merely because an isolated feature passes a test. Ask before materially changing roadmap scope or architecture.

A-01 is design-complete per the user's roadmap, not evidence that all database/policy/account features are implemented. A-03 currently has a Python connector using standard WordPress REST API; a dedicated WordPress plugin has not been built. A-04 has local A-1 integration evidence, not deployed multi-user SaaS or A-2 validation.

The user prefers complete replacement files/ZIPs and simple step-by-step Windows instructions. Never embed real credentials in files or output. Preserve keyword management, job queue, and JSON backup/restore. Never show connected/saved without actual verification. Preserve backend/.state when updating; it records test draft deduplication.

At session completion, record progress against the roadmap, the next in-scope task, checks performed, and remaining uncertainty. Git save/push for v0.2.2 remains unverified in this chat; do not claim it was done.

Latest planning deliverable: `docs/ZERO-통합로드맵-13단계-상세체크리스트.md`. It preserves the user's 13-stage image and 53 parent checklist items and adds proposed execution details and completion criteria. It is a review draft, NOT a recovered copy of the previous Word master plan. The user explicitly stopped searching for that old document; do not resume searching unless asked. No new feature implementation is authorized merely by the proposed checklist. Next technical focus remains clarifying A-02 screens, workflow, and completion criteria.

Read docs/오늘-개발마무리-2026-11-12.md at the next session. Verify Git commit/push and JSON backup status; these require user confirmation or evidence.

2026-11-13 update: read docs/v0.2.3-변경내역.md. Remote v0.2.2 commit 988084d was verified during this session. v0.2.3 adds manual append-only local SQLite workspace snapshots and v2 JSON including public site metadata; v1 restore remains supported. Preserve BOTH backend/.state/test-drafts.sqlite3 and workspace.sqlite3. No real WP requests were made this session. Main stage remains A-02. Browser E2E could not launch in this runtime; DOM UI regression tests and server tests are separate evidence. Do not claim live WP or multi-user SaaS validation.
