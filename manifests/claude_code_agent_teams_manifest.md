# Claude Code Agent Teams — Ground-Truth Manifest

**Purpose.** A citable [CC-FACT] reference for assembling a deployable Claude Code AGENT-TEAM
bootstrap kit — a "team in a folder" — that is grounded and honest about version sensitivity. This
file is GROUNDING, not a rulebook: it pins the mechanics of the experimental agent-teams feature and
the frontmatter contracts a kit relies on, so a convening prompt and a set of role files can be
authored against reality rather than recall. It does NOT teach when to convene a team for a given
problem (that is a judgment call) — it tells you what the machine actually does.

**Calibration.** Mechanics current as of **June 2026 / Claude Code v2.1.178 era**. The primary
in-repo source is `prompt.xml`; the verification source is `code.claude.com/docs`. Agent teams are
EXPERIMENTAL, disabled by default, and the tool surface has already drifted once (see §6) — so this
is a fast-moving target. Every factual claim is tagged **ESTABLISHED** (web-confirmed against
`code.claude.com/docs`, stable mechanic), **VERSION-DEPENDENT** (tie to a version; verify against the
reader's installed `claude --version`), or **OPEN** (attested only by `prompt.xml` or an estimate, not
independently web-confirmed). Claude-Code-specific mechanics also carry **[CC-FACT]**. The
adversarial-confirmation pass that grades each claim web-confirmed-vs-attested-only lives in
`result.cc_team_confirmations`; its one negative verdict is the v2.1.32 minimum-version number (§2,
§16).

**Sibling manifests (cross-referenced, not duplicated).** Specification discipline lives in
`software_spec_discipline_manifest.md`; architecture principles and quality criteria in
`architecture_manifest_default.md`; Python type-system and test-tooling FACTS in
`python_typing_contract_manifest.md` and `python_testing_tooling_manifest.md`. A team-bootstrap kit's
role files (subagent definitions reused as teammates, §9) should carry the discipline from those
manifests in their bodies; this manifest only governs the team-mechanics envelope around them.

---

## 1. Scope and provenance

[CC-FACT / ESTABLISHED] **Feature = Claude Code agent teams (experimental multi-agent).** One main
Claude Code session (the *lead*) spawns one or more *teammates*, each a separate full Claude Code
session with its own independent context window; the lead coordinates work, assigns tasks, and
synthesizes results; teammates work independently and communicate directly with each other.
(`code.claude.com/docs/en/agent-teams`, Architecture; matches `prompt.xml` lines 53–59.)

[CC-FACT] **Two-source grounding.** Where this manifest says ESTABLISHED, the claim was confirmed by
WebFetch of `code.claude.com/docs/en/agent-teams` or `.../sub-agents` or `.../costs` AND attested in
`prompt.xml`. Where it says OPEN, only `prompt.xml` (or an estimate) attests it — flagged so a kit does
not present an unverified figure as fact. The docs page itself declares "This page describes agent
teams as of v2.1.178," so treat the whole mechanic surface as a v2.1.178 snapshot.

---

## 2. Enablement

[CC-FACT / ESTABLISHED] **The single gate is the env flag `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`,**
set in the shell environment or in a `settings.json` `env` block:

```json
{ "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" } }
```

Confirmed verbatim by the agent-teams doc Warning box and "Enable agent teams" section, and by the
costs doc. **Without the flag, no team is set up at session start, no team directories are written,
and Claude does not spawn or propose teammates.** This is the load-bearing enablement fact and is
fully confirmable on the public web. A deployable kit MUST ship this `env` block (or instruct the user
to export the variable) or the whole feature is inert. (`code.claude.com/docs/en/agent-teams`;
`.../costs#agent-team-token-costs`; `prompt.xml` lines 53–58.)

[VERSION-DEPENDENT / OPEN] **Minimum version: Claude Code v2.1.32 or later** — attested by
`prompt.xml` line 53 ("v2.1.32+"). **This exact number could NOT be independently web-confirmed:** the
string "Agent teams require Claude Code v2.1.32 or later" did not appear in the primary text of the
agent-teams doc or the changelog when fetched; it surfaced only inside a WebSearch AI-synthesis that
also fabricated an unverifiable plan-tier requirement (a hallucination signal). Tag the figure
**[CC-FACT/verify]** and tell the reader to confirm the minimum version against
`code.claude.com/docs/en/agent-teams` and their installed `claude --version` before relying on it.

---

## 3. Subagents vs agent teams — decision rule and side-by-side

[CC-FACT] **Decision rule.** Default to **subagents** (delegated, lead-orchestrated sub-tasks, no
peer cross-talk) plus a lead steered by `CLAUDE.md`. Choose an **agent team** only when the work needs
**live, parallel, peer-to-peer cross-talk** — teammates that message each other directly, claim tasks
from a shared list, and falsify each other's work concurrently — and you accept the token premium
(§13) and the experimental limitations (§15). A linear "do A, then summarize B" pipeline does not earn
a team; mutual falsification across long-running parallel roles does. (Consistent with the
falsification-before-acceptance discipline in `software_spec_discipline_manifest.md` §B2 — a team is
the live, multi-agent realization of that pressure.)

[CC-FACT / ESTABLISHED] **Side-by-side.**

| Dimension | Subagents | Agent teams |
|---|---|---|
| Context | Each subagent invocation has its own context; results returned to the lead | Each teammate is a full independent Claude Code session with its own context window |
| Communication | Lead ↔ subagent only (request/response); no peer cross-talk | Peer-to-peer via mailbox (`SendMessage`); teammates message each other by name |
| Coordination | Lead orchestrates; no shared task list | Shared task list with claim/dependency/file-lock semantics (§6) |
| Lifecycle | Per-invocation; lead resumes via `SendMessage` (subagents doc) | Team forms on first spawn; cleanup automatic at session exit (§5) |
| Definition | `.claude/agents/<kebab>.md` frontmatter (§10) | Natural-language spawn; may *reference* a subagent definition as a role (§9) |
| Best for | Bounded delegated tasks, isolation, fan-out summarization | Live parallel collaboration with mutual review |
| Token cost | ~1× per delegated task | ~7× in plan mode, roughly proportional to team size (§13) |
| Enablement | Always available | Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |

(`code.claude.com/docs/en/agent-teams`; `.../sub-agents`.)

---

## 4. Team architecture and on-disk state

[CC-FACT / ESTABLISHED] **Components** (`code.claude.com/docs/en/agent-teams#architecture`):
- **Team lead** — the main Claude Code session that spawns teammates and coordinates work. Fixed and
  non-transferable for the session's lifetime (§5, §15).
- **Teammates** — separate Claude Code instances, each working assigned tasks, each its own context
  window. Teammates do **not** inherit the lead's conversation history.
- **Task list** — shared list of work items teammates claim and complete (§6).
- **Mailbox** — messaging system for inter-agent communication via `SendMessage` (§7).

[CC-FACT / ESTABLISHED] **Session-derived naming and on-disk state.** Teams and tasks are stored
locally under a name `session-` + the first eight characters of the session ID.
- **Team config:** `~/.claude/teams/{team-name}/config.json` — holds **runtime state** (session IDs,
  tmux pane IDs); generated automatically at session startup and updated as teammates join/idle/leave;
  **removed when the session ends.**
- **Task list:** `~/.claude/tasks/{team-name}/` — **persists** locally and is **never uploaded**, so a
  resumed session keeps its tasks.

[CC-FACT / ESTABLISHED] **A team is NOT configured from files.** Teams are created from natural
language (§5). The team `config.json` is runtime state: **do not edit it by hand or pre-author it —
your changes are overwritten on the next state update.** Critically, **there is no project-level team
config:** a file like `.claude/teams/teams.json` in a project directory is **not recognized as
configuration**; Claude treats it as an ordinary file.

> **Kit implication — "team in a folder" ≠ team config.** A deployable team-bootstrap kit is therefore
> **(a)** a set of subagent role files (`.claude/agents/*.md`, §10) reusable as teammates (§9),
> **(b)** a convening prompt in natural language that names the roles and the task, and **(c)** the
> enablement `env` block plus grounding (this manifest + siblings). It is NOT, and cannot be, a
> hand-authored team config JSON. Encode this so the kit does not ship a dead `teams.json`.

---

## 5. Bootstrap and lifecycle

[CC-FACT / ESTABLISHED] (`code.claude.com/docs/en/agent-teams#how-claude-starts-agent-teams`)
- **Formation:** a team forms when the **first teammate is spawned**, with the main session acting as
  the lead. No separate setup/create step (contrast §6).
- **Two paths:** (1) **you request** teammates explicitly; (2) **Claude proposes** teammates and **you
  confirm** before it proceeds. Either path is gated on the enablement flag (§2).
- **Plan-approval flow:** a teammate can be required to work in **read-only plan mode** until the lead
  approves; it submits a plan-approval request; the lead approves, or rejects with feedback; on
  rejection the teammate stays in plan mode and resubmits. (Drives the ~7× plan-mode token figure, §13.)
- **Cleanup:** automatic when the session ends — the team config directory is removed; no explicit
  cleanup step.

[CC-FACT / ESTABLISHED] **Hard structural constraints** (`.../agent-teams#limitations`): **one team
per session**; **no nested teams** (teammates cannot spawn their own teammates); **lead is fixed** for
the session lifetime (you cannot promote a teammate to lead or transfer leadership).

---

## 6. Coordination tools — current surface and the documented drift

[CC-FACT / ESTABLISHED] **Current task tools:** **`TaskCreate` / `TaskUpdate` / `TaskList` /
`TaskGet`**, plus **`SendMessage`** for messaging (§7). Task mechanics, confirmed verbatim:
- **Three states:** pending, in progress, completed.
- **Dependencies:** a pending task with unresolved dependencies cannot be claimed until those
  dependencies are completed.
- **File-locked claiming:** task claiming uses file locking to prevent race conditions when multiple
  teammates try to claim the same task simultaneously.

(`code.claude.com/docs/en/agent-teams#assign-and-claim-tasks`. The doc describes the behavior and
refers to "the task management tools" generically; the four literal names `TaskCreate/TaskUpdate/
TaskList/TaskGet` — `TaskGet` returns full detail vs `TaskList`'s minimal fields, and these split the
former single `TodoWrite` call, default since ~v2.1.142 — are corroborated by the
`anthropics/claude-code` issue tracker and third-party guides. `SendMessage` exists ONLY when
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, confirmed on `.../sub-agents#resume-subagents`.)

> ### [VERSION-DEPENDENT] DOCUMENTED DRIFT — `prompt.xml` is STALE here
> `prompt.xml` line 56 lists **`TeamCreate`** among the team tools. **`TeamCreate` and `TeamDelete` NO
> LONGER EXIST as of v2.1.178.** The agent-teams doc Note box states verbatim: "Before v2.1.178, you
> asked Claude to create and name a team first, and Claude used the TeamCreate and TeamDelete tools to
> set it up and remove it. Both tools no longer exist. The `team_name` input on the Agent tool is
> accepted but ignored, and the `team_name` field in `TaskCreated`, `TaskCompleted`, and
> `TeammateIdle` hook payloads carries the session-derived name and is deprecated." Consequences for a
> kit:
> - A team **forms automatically** when the first teammate is spawned (§5); **cleanup is automatic**
>   at session exit (§5). Do not script a create/name/delete step.
> - The Agent tool's **`team_name` input is accepted-but-ignored** — pass nothing meaningful through it
>   and rely on no residual effect.
> - Of the five tools `prompt.xml` names, **`TeamCreate` is obsolete**; the other four
>   (`TaskCreate`/`TaskUpdate`/`TaskList`/`SendMessage`) remain valid.
> - **State this drift explicitly and tell the reader to verify the tool surface against
>   `code.claude.com/docs/en/agent-teams` versus their installed `claude --version`** before deploying.

---

## 7. Communication model

[CC-FACT / ESTABLISHED] (`code.claude.com/docs/en/agent-teams#context-and-communication`)
- **Peer-to-peer mailbox:** teammates message each other directly via `SendMessage`.
- **Automatic delivery, no polling:** when a teammate sends a message it is delivered automatically;
  the lead does not poll for updates.
- **Idle notifications:** when a teammate finishes and stops, it automatically notifies the lead.
- **By-name addressing:** send to one specific teammate by name. **Broadcast = manual fan-out:** to
  reach everyone, send one message per recipient (there is no single broadcast primitive).
- **No shared history:** each teammate is a full independent session and does not inherit the lead's
  conversation context — pass needed context explicitly in the spawn prompt / task / message.

---

## 8. Permissions

[CC-FACT / ESTABLISHED] **Uniform at spawn.** Teammates start with the **lead's** permission settings
— **including `--dangerously-skip-permissions`** if the lead runs with it. After spawning you can
change individual teammate modes, but you **cannot set per-teammate modes at spawn time.**
(`code.claude.com/docs/en/agent-teams#permissions` and `#limitations`; `prompt.xml` line 58.)

> **Kit implication.** Because permission mode is inherited uniformly and is destructive when the lead
> skips permissions, a kit should pre-approve the common operations its roles need (so prompts do not
> bubble up from teammates) and must not assume a role file can sandbox itself to a stricter mode at
> spawn — tighten a teammate only *after* it is running. Note an implementation bug exists where
> teammates can lose tool access under `bypassPermissions` (open issues), distinct from the documented
> spawn-time behavior.

---

## 9. Reusing subagent definitions as teammates — the load-bearing bridge

[CC-FACT / ESTABLISHED] This is the mechanism that turns a folder of static role files into a team.
When spawning a teammate you may **reference a subagent type from any scope: project, user, plugin, or
CLI-defined.** Then (`code.claude.com/docs/en/agent-teams#use-subagent-definitions-for-teammates`):

1. **The teammate honors the definition's `tools` allowlist and `model`.**
2. **The definition's body is APPENDED** to the teammate's system prompt as additional instructions —
   it does **not** replace the base teammate prompt.
3. **Team coordination tools (`SendMessage`, the task tools) are ALWAYS available** to a teammate even
   when `tools` restricts other tools.
4. **The `skills` and `mcpServers` frontmatter fields are NOT applied on the teammate path.** Teammates
   load skills and MCP servers from **project and user settings**, the same as a regular session.

> **Emphasis — this is the bridge between the static role files a kit ships and the dynamic team
> feature.** A role defined once can serve as both a delegated subagent and a team teammate. But the
> bridge is lossy in two named ways that a kit author must design around:
> - **`skills:` and `mcpServers:` in a role's frontmatter are silently dropped when it runs as a
>   teammate.** If a role needs a skill or an MCP server, it must be available via project/user
>   settings, not pinned in the role file.
> - **`tools` and `model` carry over; the body is appended (not authoritative).** Write the role body
>   as additive instructions layered on a general teammate, not as a self-contained replacement system
>   prompt.

(Cross-reference: the discipline a role body should encode lives in
`software_spec_discipline_manifest.md` and `architecture_manifest_default.md`; this manifest only
states that the body is *appended*, not what it should say.)

---

## 10. Subagent frontmatter reference (`.claude/agents/<kebab>.md`)

[CC-FACT / ESTABLISHED] **Exactly 16 valid file-based frontmatter fields**, only `name` and
`description` required (`code.claude.com/docs/en/sub-agents#supported-frontmatter-fields`):

| Field | Req | Notes / allowed values |
|---|---|---|
| `name` | ✓ | Subagent identifier (kebab-case file name). |
| `description` | ✓ | When/why to use it; the only field the skills/agent docs call "recommended." |
| `tools` | | Allowlist of tools the agent may use (CSV/list). Coordination tools stay available on the teammate path regardless (§9). |
| `disallowedTools` | | Denylist; subtracts from the available set. |
| `model` | | `sonnet` \| `opus` \| `haiku` \| `fable` \| `<full model ID>` \| `inherit` (default `inherit`). |
| `permissionMode` | | `default` \| `acceptEdits` \| `auto` \| `dontAsk` \| `bypassPermissions` \| `plan`. |
| `maxTurns` | | Integer cap on agent turns. |
| `skills` | | Skills to load — **NOT applied on the teammate path (§9).** |
| `mcpServers` | | MCP servers — **NOT applied on the teammate path (§9).** |
| `hooks` | | Subagent-scoped hooks. |
| `memory` | | `user` \| `project` \| `local`. |
| `background` | | Run in background. |
| `effort` | | `low` \| `medium` \| `high` \| `xhigh` \| `max` (available levels depend on model). |
| `isolation` | | `worktree`. |
| `color` | | `red` \| `blue` \| `green` \| `yellow` \| `purple` \| `orange` \| `pink` \| `cyan`. |
| `initialPrompt` | | Auto-submitted as the first user turn when the agent runs as the **main** session via `--agent` or the `agent` setting. (Omitted from `prompt.xml`'s list — a doc gap, not an error.) |

[CC-FACT / ESTABLISHED] **`--agents` CLI JSON** accepts the **same fields plus `prompt`** (the system
prompt, equivalent to the markdown body): `description, prompt, tools, disallowedTools, model,
permissionMode, mcpServers, hooks, maxTurns, skills, initialPrompt, memory, effort, background, color`.
In CLI JSON the agent **name is the object key** (so `name` is not a JSON property).

[CC-FACT / ESTABLISHED] **Plugin subagents ignore `hooks`, `mcpServers`, and `permissionMode`.** A
kit distributed as a plugin must not rely on those three fields in its role files.

(All 16 fields and the CLI superset confirm `prompt.xml` lines 30–41; `prompt.xml` gives a narrower
`model` enum (`haiku|sonnet|opus|inherit`) — the doc adds `fable` and full model IDs and is the
authoritative superset.)

---

## 11. Slash-command / skill frontmatter reference

[VERSION-DEPENDENT] **Custom slash commands have been MERGED INTO SKILLS.** The slash-commands doc URL
now redirects to the skills doc, which states "Custom commands have been merged into skills."
- **Legacy path:** `.claude/commands/<name>.md` **still works**, with the same frontmatter
  (`description`, `argument-hint`, `allowed-tools`, `model`, and `$ARGUMENTS` / `$1`..`$n`
  substitution) — this is what `prompt.xml` lines 43–45 describe, still VALID but now legacy.
- **Recommended form:** `.claude/skills/<name>/SKILL.md`.
- **Precedence:** if a command and a skill share a name, **the skill wins.**

[CC-FACT / ESTABLISHED] **`SKILL.md` frontmatter fields** (`code.claude.com/docs/en/skills#frontmatter-reference`),
all optional, only `description` recommended: `name`, `description`, `when_to_use`, `argument-hint`,
`arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `disallowed-tools`,
`model`, `effort`, `context` (set to `fork`), `agent`. This **supersets** `prompt.xml`'s four
command fields. **Note the casing seam:** skills use hyphenated `allowed-tools` / `disallowed-tools`,
whereas subagents (§10) use camelCase `tools` / `disallowedTools`. Argument substitution uses
`$ARGUMENTS` and named/positional `$name` via the `arguments` field.

> **Kit relevance.** A team-bootstrap kit may ship convening commands/skills (e.g. a `/convene-review`
> skill that issues the natural-language spawn prompt). Prefer the `SKILL.md` form; if shipping legacy
> `.claude/commands/*.md`, restrict to the four legacy fields and expect the skill to win on any name
> clash.

---

## 12. Display and control

[CC-FACT / ESTABLISHED] **Two display modes** (`code.claude.com/docs/en/agent-teams#choose-a-display-mode`):
- **In-process** — any terminal. `Shift+Down` cycles teammates; `Ctrl+T` toggles the task list.
- **Split-panes** — **requires tmux or iTerm2.** **NOT supported in the VS Code terminal, Windows
  Terminal, or Ghostty.**

Controlled by the `teammateMode` setting / `--teammate-mode` flag (default `auto`). The **default
teammate model** is set in `/config`; **teammates do NOT inherit the lead's `/model` selection by
default.**

> ### [CC-FACT] Windows note — load-bearing for this kit
> Split-pane display needs tmux or iTerm2, neither of which runs in Windows Terminal or the VS Code
> terminal. On **Windows 11**, **in-process mode is the practical default.** A kit targeting Windows
> should document `Shift+Down` / `Ctrl+T` navigation, not rely on split panes, and either set
> `teammateMode` accordingly or leave it `auto` and tell the user split panes will not appear.

---

## 13. Token economics

[VERSION-DEPENDENT / ESTABLISHED upper bound] **Agent teams use approximately 7× more tokens than
standard sessions WHEN TEAMMATES RUN IN PLAN MODE; token usage is roughly proportional to team size.**
The 7× figure (with the plan-mode qualifier) and the roughly-proportional scaling are confirmed on
`code.claude.com/docs/en/costs`.

[OPEN] **The ~3× lower bound is an estimate.** `prompt.xml` says "~3–7×"; only the ~7× plan-mode
figure is attested by the docs. **Treat the 3× floor as an estimate, not a CC-FACT** — do not present
it as documented.

[CC-FACT] **Cost-control levers** a kit should encode: prefer **Sonnet** (or smaller) teammates via the
default-teammate-model setting; keep teams **small** (docs recommend starting at 3–5 teammates, ~5–6
tasks each — guidance, not an enforced ceiling, §16); write **focused spawn prompts**; **shut teammates
down promptly** when done; use plan mode deliberately given its ~7× multiplier.

---

## 14. Quality-gate hooks

[CC-FACT / ESTABLISHED] **Team hook events** (`code.claude.com/docs/en/agent-teams#enforce-quality-gates-with-hooks`):
**`TeammateIdle`**, **`TaskCreated`**, **`TaskCompleted`**. A hook returning **exit code 2** sends
feedback / prevents the action — e.g., block a task from being marked complete until a coverage or
test gate passes. These are **distinct** from the subagent `SubagentStart` / `SubagentStop` hooks.
(Recall from §6 that the `team_name` field in these three payloads is deprecated and carries the
session-derived name.)

> **Kit relevance.** Quality gates are how a deployable team enforces the falsification-before-
> acceptance and verification discipline of `software_spec_discipline_manifest.md` mechanically: a
> `TaskCompleted` hook that exits 2 unless the verification obligation is met turns a soft norm into a
> hard gate.

---

## 15. Limitations and risks

[CC-FACT / ESTABLISHED] Stated experimental limitations
(`code.claude.com/docs/en/agent-teams#limitations`), each with a kit-design implication:
- **No in-process resume:** `/resume` and `/rewind` do **not** restore in-process teammates. → Do not
  design a kit that depends on resuming a live team; the task list persists (§4) but the teammates do
  not.
- **Task-status lag:** teammates may fail to mark tasks complete, blocking dependents. → Design tasks
  to tolerate status lag; lean on `TaskCompleted` hooks (§14) and lead-side reconciliation.
- **Slow shutdown:** team teardown can be slow. → Budget for it; shut down promptly (§13).
- **One team per session; no nested teams; lead fixed** (§5). → A kit cannot recursively spawn
  sub-teams or hand off leadership.
- **Permissions set at spawn** (§8). → Cannot pre-set per-teammate modes.
- **Split panes need tmux/iTerm2** (§12). → In-process default on Windows.

---

## 16. Open questions and version caveats

- **[VERSION-DEPENDENT / OPEN] Minimum-version number (v2.1.32).** Attested only by `prompt.xml`;
  NOT independently web-confirmed (the figure appeared only in a WebSearch synthesis that also
  hallucinated a plan-tier requirement). Tag **[CC-FACT/verify]** and confirm against
  `code.claude.com/docs/en/agent-teams` and `claude --version`.
- **[OPEN] Token lower bound (~3×).** Estimate only; docs attest ~7× in plan mode and
  roughly-proportional scaling (§13).
- **[OPEN] Exact tool input schemas.** The prose docs describe `TaskCreate`/`TaskUpdate`/`TaskList`/
  `TaskGet`/`SendMessage` behaviorally; field-level shapes (e.g., `SendMessage` `to` by name vs agent
  ID, `TaskCreate` dependency syntax) are not on the prose pages — consult the Agent SDK reference
  (`agent-sdk/typescript`, `agent-sdk/python`) if exact JSON is needed.
- **[OPEN] Teammate-count ceiling.** Docs say "no hard limit" and recommend 3–5 (≈5–6 tasks each);
  the practical cap for a kit is judgment, not a documented number (§13).
- **[OPEN] Residual effect of the Agent tool's `team_name`.** Docs say "accepted but ignored"
  post-v2.1.178; a kit must not rely on it (§6).
- **[OPEN] Default teammate model when the spawn prompt is silent and `/config` "Default teammate
  model" is unset.** Docs imply teammates do not follow the lead's `/model` by default (§12), but the
  exact fallback model is not stated.
- **[VERSION-DEPENDENT] Whole-feature staleness.** `prompt.xml` is calibrated to the Claude Code
  2.1.x / Opus 4.6 era; the live docs reflect v2.1.178. Anything attested ONLY by `prompt.xml` and not
  found on `code.claude.com/docs` — notably the now-removed `TeamCreate`/`TeamDelete` (§6) and the
  legacy slash-command shape (§11) — must be re-verified against the user's installed `claude
  --version` before deploying.

---

## Sources

- Claude Code — Agent teams — https://code.claude.com/docs/en/agent-teams (Architecture, Enable,
  Start your first agent team, How Claude starts agent teams, Assign and claim tasks, Context and
  communication, Permissions, Use subagent definitions for teammates, Require plan approval, Choose a
  display mode, Specify teammates and models, Enforce quality gates with hooks, Limitations; v2.1.178
  Note box on removed `TeamCreate`/`TeamDelete`). Accessed 2026-06-17.
- Claude Code — Subagents — https://code.claude.com/docs/en/sub-agents (Supported frontmatter fields;
  `--agents` CLI JSON; `resume-subagents` re `SendMessage` gated on
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Accessed 2026-06-17.
- Claude Code — Skills — https://code.claude.com/docs/en/skills (Frontmatter reference; "Custom
  commands have been merged into skills"; legacy `.claude/commands/*.md`; skill-wins precedence).
  Accessed 2026-06-17.
- Claude Code — Costs — https://code.claude.com/docs/en/costs#agent-team-token-costs (enablement
  restatement; ~7× tokens in plan mode; roughly proportional to team size). Accessed 2026-06-17.
- In-repo attestation — `prompt.xml` lines 30–59 (agent-team primitive, subagent/slash-command
  frontmatter; STALE on `TeamCreate`/`TeamDelete` and the v2.1.32 figure per the adversarial pass).
  Accessed 2026-06-17.
- Corroboration (tool names, drift) — `anthropics/claude-code` issue tracker (e.g. #20243, #21901,
  #23874, #32723, #34750) and third-party guides; authoritative confirmation remains the agent-teams
  doc's v2.1.178 Note box. Accessed 2026-06-17.
- Adversarial confirmation ledger — research JSON `result.cc_team_confirmations` (12 verdicts; all
  `confirmed` except the v2.1.32 minimum-version, graded `unconfirmable` / `web_confirmed=false`).
  Accessed 2026-06-17.
