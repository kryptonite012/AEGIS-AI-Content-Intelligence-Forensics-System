# Evidence-handling procedure (template)

1. **Authorisation.** Open a case only with a documented purpose and, where required, a legal or organisational basis, recorded in the case.
2. **Acquisition.** Obtain the most original copy available (not screenshots or re-encodes). Upload it unchanged. AEGIS records the SHA-256, size, detected type, acquisition time and uploader, and stores the original write-once.
3. **Verification.** Compare the server SHA-256 with any hash provided by the source. Run Verify integrity before reporting and periodically during long cases.
4. **Derivatives.** Work on AEGIS-generated derivatives (normalised text, thumbnails, redacted versions). Originals are never modified, and every derivative records its parent and transformations.
5. **Access.** Download originals only when needed; every download is audited. Use restricted classification for sensitive cases.
6. **Process evidence.** Attach drafts, revision histories and notes as `process_evidence`. They are evaluated by reviewers, not by detectors.
7. **Review and reporting.** Finalise only after an independent review decision. The report embeds evidence hashes, method versions and audit references.
8. **Retention and disposal.** Follow the retention policy. Deletion needs a request and a second person's approval, and is blocked under legal hold. Hashes and audit records remain as tombstones.

This technical procedure must be adopted, adapted and validated by the institution. It is not a legally certified chain-of-custody process.
