# Normalized RDC Concrete Knowledge Base

This directory contains retrieval-ready Markdown copies of the current material in `data/`. The original files are preserved as the source of record. These copies use stable titles, frontmatter, explicit question variants, and Markdown headings so Open WebUI can split content at meaningful boundaries.

## Source mapping

| Normalized file | Raw source |
|---|---|
| `00-rdc-concrete-domain-profile.md` | `RDC Concrete.docx.txt` |
| `10-ids-edge-configuration-and-batching.md` | `Youtube Video Description and Link for Batching Query errors.txt` |
| `20-ids-erp-integration-troubleshooting.md` | `Title Ticket Not Showing or Reaching Knowledge.txt` and `Batching Integration Errors.docx.txt` |
| `30-ids-batching-fault-troubleshooting.md` | `Batching Integration Errors.docx.txt` |

## Editing rules

- Keep one operational problem or guide under one `##` heading.
- Put common operator wording in `Question variants` and `Search terms`.
- Do not combine unrelated fixes in one answer. If a source has several possible causes, keep each cause and its verification step separate.
- Never invent a missing screen path, threshold, calibration value, or safety instruction. Mark missing detail as `Not specified in the source` and link the approved guide or video.
- Keep raw source files unchanged. Update the normalized Markdown file, then reindex the Knowledge Base.
- Add `last_verified` and `source` when a new procedure is approved.

## Admin-panel ingestion

Upload the four substantive Markdown files to Knowledge Base `8bf6c71f-2ff8-4165-bbac-84408c7e2551`. Do not upload this README or the template as answer content. If your Open WebUI build exposes `Add Content -> Sync Directory`, use a folder containing only the four substantive files; sync is incremental, so unchanged files are not re-uploaded or re-embedded.

Recommended document settings for the first comparison:

- Focused Retrieval (RAG), not Full Context.
- Markdown Header Splitting enabled.
- Character splitter with a starting maximum of about 2,000 characters.
- Overlap around 200 characters.
- Chunk Min Size Target around 800-1,000 characters; lower it if two different fault sections are being merged.
- Keep hybrid search enabled if the deployment has it, because exact terms such as `ConfigBOM`, `FG code`, ticket IDs and fault text benefit from keyword retrieval.

These are starting points, not quality guarantees. Test a known query, a paraphrase, and an unknown query after each change. Re-index after changing the embedding model; re-indexing also applies the current chunking settings to existing Knowledge Base files.

## Adding a new question and solution

1. Copy `data/knowledge_templates/operational-qa.md`.
2. Give it one problem title and add operator wording under `Question variants`.
3. Record the exact symptom, preconditions, safe steps, verification, escalation and approved source.
4. Mark uncertain or plant-specific details as `Not specified` instead of filling the gap from general knowledge.
5. Add the file to the Knowledge Base, wait for processing, and re-index when chunk or embedding settings changed.
6. Test the exact question and at least one paraphrase. Verify the LangSmith trace shows the expected source under `01-retrieve`, accepted evidence under `03-validate-kb`, and the final answer under `09-nova-output`.

Do not overwrite a working procedure with an unverified chat answer. If a solution changes, retain the old source or update its `last_verified` and source reference so the change is auditable.
