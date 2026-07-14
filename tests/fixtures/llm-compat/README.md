# LLM compatibility fixtures

These fixtures are synthetic protocol cases derived from the shapes observed
in the 2026-07-14 compatibility investigation.  They are deliberately marked
`synthetic`; they are not evidence of a successful live API call and contain
no credentials, headers, or full reasoning text.

Live probes write only hashes and length metadata beneath the ignored `.runs/`
directory.  A live payload must not be promoted into this directory without a
separate redaction review and provenance metadata.
