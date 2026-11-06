# Stage 4B-13 — End-to-end evidence admission preflight

Stage 4B-13 adds `evaluate_preflighted_event_evidence`, the strict bridge between verified provenance, accepted operator review, PDF inspection, exact excerpts, and the existing event evidence policy.

## Invocation

Load provenance and capture manifests with `load_verified_evidence_manifest`, then load the operator review manifest with `load_evidence_review_manifest`. For each P1 evidence ID used by the event, supply its inspection manifest and the complete set of excerpt binding manifests:

```python
result = evaluate_preflighted_event_evidence(
    event,
    review_ingestion,
    {
        "EVD-EXAMPLE-01": (
            Path("archive/filing.pdf-inspection.json"),
            (Path("archive/fact-01.binding.json"),),
        )
    },
)
```

The preflight:
1. Requires every referenced evidence ID to exist in the provenance bundle.
2. Requires P1 evidence to have an accepted operator review.
3. Revalidates the PDF capture, inspection lineage, and all exact excerpt bindings through the Stage 4B-12 verifier.
4. Requires the operator-reviewed PDF page count to match the inspected page count.
5. Delegates to the existing fail-closed evidence policy only when preflight has no errors.

Missing or invalid artifacts return an ineligible result with reasons. The function does not change evidence tiers, review statuses, canonical events, or signal state.

## Important boundary

This is a preflight gate, not proof that the operator's interpretation is correct or that source authenticity is cryptographically established. A successful result means the required declared artifacts and review assertions are internally consistent and pass the existing admission rules. Human source review and material-attachment completeness remain required.

Do not use the lower-level `evaluate_reviewed_event_evidence` as a substitute for this artifact-aware preflight when a production caller requires PDF evidence lineage. Quarantined Stage 3C records remain excluded.
