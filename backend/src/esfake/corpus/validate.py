"""`esfake corpus validate`: what CI checks on the committed corpus (CLAUDE.md rule 6, EF-07).

CI only validates; it never assigns. Problems fail the build; warnings are printed and pass.
The leak check itself is `corpus.clusters.find_leaks`, with the same cosine and threshold that
built the clusters.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from esfake.corpus.dataset import CorpusRecord, DatasetInfo

# CLAUDE.md rule 6: above this share of excluded messages, the cluster threshold is reviewed.
EXCLUDED_REVIEW_SHARE = 0.05
HELD_OUT = ("eval", "test")


@dataclass
class ValidationReport:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_corpus(
    records: Sequence[CorpusRecord],
    info: DatasetInfo,
    *,
    threshold: float,
    embedding_model: str,
    textual_modalities: Collection[str],
) -> ValidationReport:
    """Everything but the leak check, which needs embeddings."""
    report = ValidationReport()
    unassigned = [r for r in records if r.case_id is None or r.cluster_id is None or not r.split]
    if unassigned:
        report.problems.append(
            f"{len(unassigned)} messages have no case_id, cluster or split: run "
            "`esfake corpus assign` and commit the result"
        )
    duplicates = [
        cid for cid, n in Counter(r.case_id for r in records if r.case_id).items() if n > 1
    ]
    if duplicates:
        report.problems.append(f"duplicate case_ids: {sorted(duplicates)}")

    splits_by_cluster: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.cluster_id is not None and record.split is not None:
            splits_by_cluster[record.cluster_id].add(record.split)
    mixed = sorted(cid for cid, splits in splits_by_cluster.items() if len(splits) > 1)
    if mixed:
        report.problems.append(f"clusters split across splits: {mixed}")

    if (info.cluster_threshold, info.embedding_model) != (threshold, embedding_model):
        report.problems.append(
            f"dataset.json was built with threshold {info.cluster_threshold} and "
            f"{info.embedding_model}, but the configuration says {threshold} and "
            f"{embedding_model}: re-cluster with `esfake corpus assign --new-major`"
        )

    held_out_clusters: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        if record.split in HELD_OUT and record.cluster_id is not None:
            group = str(record.modality) if record.label == "scam" else "legit"
            held_out_clusters[group, record.split].add(record.cluster_id)
    for modality in sorted(textual_modalities):
        missing = [s for s in HELD_OUT if not held_out_clusters[modality, s]]
        if missing:
            report.problems.append(
                f"modality {modality} has no cluster in {' or '.join(missing)}: add messages"
            )
    missing_legit = [s for s in HELD_OUT if not held_out_clusters["legit", s]]
    if missing_legit:
        report.warnings.append(
            f"no legitimate message in {' or '.join(missing_legit)}: false positives cannot be "
            "measured there"
        )

    excluded = sum(r.split == "excluded" for r in records)
    if records and excluded / len(records) > EXCLUDED_REVIEW_SHARE:
        report.warnings.append(
            f"{excluded} of {len(records)} messages are excluded, over 5 %: review the cluster "
            "threshold (a new major dataset version)"
        )
    return report
