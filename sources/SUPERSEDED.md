# Superseded — do not read as guidance

These eleven files are the source documents this repository was built from, frozen
as an audit trail. **They are not current guidance.** The discipline is
`discipline/KERNEL.md` and the modules it routes to.

Reading them will actively mislead you. As a set they contain:

- **~35 contradictions between them**, including two incompatible error taxonomies, a
  fault-schedule form live in one document and declared retired in another, and one
  document claiming a bare `raise` loses the call site while another correctly states it
  preserves the traceback. Every one is resolved in `discipline/meta/CONFLICTS.md`.
- **~130 references to documents that do not exist**, 73 of them to a single `PROPOSAL.md`.
- **Project-specific material** from one application — package paths, a document renderer,
  bilingual catalogs, one filesystem's guarantees — presented as general rules.
- **Three clashing tag vocabularies**, one of which is cited by the wrong document.
- **Mandates with no mechanism**: mutation testing, MC/DC, fuzzing and strict typing are
  all required while naming almost no tool and no threshold.

Where each of their 324 sections went is recorded in `discipline/meta/PROVENANCE.md`:
262 migrated, 56 superseded, 6 dropped with a stated reason, none unaccounted for.

## The files

| Tag | File | Went to |
|---|---|---|
| SG | `Software Engineering Style Guidelines.md` | fully superseded by the doctrine below, which names the supersession itself |
| SE | `doctrine/SOFTWARE-ENGINEERING.md` | `law/ARCH`, `law/TYPE`, `law/ERR`, `law/EFCT`, `law/API`, `law/DEP`, `law/FLOW` |
| TD | `doctrine/TESTING.md` | `law/TEST` |
| CA | `doctrine/CHEAPEST-ABLE.md` | `ops/ALLOC` |
| AR | `manifests/architecture_manifest_default.md` | `frame/architecture` |
| ET | `manifests/error_tracing_contract_manifest.md` | `law/ERR`, `law/DIAG`, `fact/py-errors` |
| LO | `manifests/logging_observability_manifest.md` | `law/DIAG`, `fact/py-logging` |
| TY | `manifests/python_typing_contract_manifest.md` | `law/TYPE`, `fact/py-typing` |
| TT | `manifests/python_testing_tooling_manifest.md` | `law/TEST`, `fact/py-testing` |
| SP | `manifests/software_spec_discipline_manifest.md` | `frame/spec`, `law/FLOW` |
| AT | `manifests/claude_code_agent_teams_manifest.md` | `ops/teams` |

## Why they are kept

So the merge can be audited. A resolution recorded in `CONFLICTS.md` is only checkable
against the text it resolved. If a rule in `discipline/law/` looks wrong, the question to
ask is what its source said and why the resolution went the way it did — and both answers
are reachable from here.

They are frozen. Corrections belong in the discipline, not here.
