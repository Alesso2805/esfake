"""`esfake corpus assign`: case_id, cluster and frozen split for new messages (CLAUDE.md rule 6).

A record without a split is new; every other record keeps its case_id, cluster and split.

1. case_id = HMAC of the source and the redacted text, with the corpus key ring.
2. Two messages are near-duplicates when their cosine (corpus.clusters) reaches the cluster
   threshold. New messages form connected components among themselves, and each component
   looks at the assigned clusters it touches (excluded messages never anchor one):
   - none: it becomes a new cluster, allocated in step 4;
   - one or more, all in the same split: it joins the smallest cluster_id and inherits the split;
   - clusters in different splits: the whole component goes to `excluded`, out of the index and
     the evaluation, so it cannot bridge them.
3. A synthetic message that would inherit `test` is discarded, and a new cluster with a
   synthetic member never goes to `test`.
4. New clusters are allocated per stratum (modality for scams, subcategory for legitimate
   messages) in the order of the hash of their cluster_id. Each goes to the split furthest below
   its quota of the stratum's messages (15 % test, 15 % eval, the rest index, counting what was
   assigned before), so every batch keeps the proportions. A stratum with at least three clusters
   gets at least one in `test` and one in `eval`.
"""

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from numpy.typing import NDArray

from esfake.corpus.clusters import cosine_matrix
from esfake.corpus.dataset import CorpusRecord, DatasetInfo, Split
from esfake.shared.hmac_keys import KeyRing

HELD_OUT_SHARE = 0.15  # each of test and eval; index takes the rest
MIN_CLUSTERS_FOR_HELD_OUT = 3


@dataclass
class AssignReport:
    new: int = 0
    new_clusters: int = 0
    inherited: int = 0
    excluded: int = 0
    discarded_synthetic: int = 0
    splits: Counter[str] = field(default_factory=Counter)


def case_id_for(record: CorpusRecord, keys: KeyRing) -> str:
    return keys.digest(f"{record.source}\n{record.text}")


def _cluster_id(case_ids: Sequence[str]) -> str:
    return "cl_" + hashlib.sha256(min(case_ids).encode()).hexdigest()[:16]


def _order(cluster_id: str) -> str:
    return hashlib.sha256(cluster_id.encode()).hexdigest()


def _stratum(records: Sequence[CorpusRecord]) -> str:
    counts = Counter(
        f"scam:{r.modality}" if r.label == "scam" else f"legit:{r.subcategory}" for r in records
    )
    return min(counts, key=lambda stratum: (-counts[stratum], stratum))


def _components(indices: list[int], similar: NDArray[np.bool_]) -> list[list[int]]:
    parent = {i: i for i in indices}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in np.argwhere(np.triu(similar[np.ix_(indices, indices)], k=1)):
        parent[root(indices[a])] = root(indices[b])
    groups: dict[int, list[int]] = defaultdict(list)
    for i in indices:
        groups[root(i)].append(i)
    return list(groups.values())


def _allocate(
    new_clusters: dict[str, list[CorpusRecord]], assigned: Sequence[CorpusRecord]
) -> dict[str, Split]:
    by_cluster: dict[str, list[CorpusRecord]] = defaultdict(list)
    for record in assigned:
        if record.split not in (None, "excluded") and record.cluster_id is not None:
            by_cluster[record.cluster_id].append(record)
    messages: dict[str, Counter[str]] = defaultdict(Counter)
    clusters: dict[str, Counter[str]] = defaultdict(Counter)
    for members in by_cluster.values():
        messages[_stratum(members)][str(members[0].split)] += len(members)
        clusters[_stratum(members)][str(members[0].split)] += 1
    total_messages: Counter[str] = Counter()
    total_clusters: Counter[str] = Counter()
    for members in [*by_cluster.values(), *new_clusters.values()]:
        total_messages[_stratum(members)] += len(members)
        total_clusters[_stratum(members)] += 1

    def choose(stratum: str, test_allowed: bool) -> Split:
        total = total_messages[stratum]
        held_out = math.floor(HELD_OUT_SHARE * total + 0.5)
        if total_clusters[stratum] >= MIN_CLUSTERS_FOR_HELD_OUT:
            for split in ("test", "eval") if test_allowed else ("eval",):
                if clusters[stratum][split] == 0:
                    return split
        deficits: dict[Split, int] = {
            "test": held_out - messages[stratum]["test"],
            "eval": held_out - messages[stratum]["eval"],
            "index": total - 2 * held_out - messages[stratum]["index"],
        }
        if not test_allowed:
            # A synthetic cluster cannot fill test's quota, so index takes what test lacks.
            deficits["index"] += max(0, deficits.pop("test"))
        # Ties go to test, then eval, then index.
        return max(deficits, key=deficits.__getitem__)

    allocation: dict[str, Split] = {}
    for cluster_id in sorted(new_clusters, key=_order):
        members = new_clusters[cluster_id]
        stratum = _stratum(members)
        split = choose(stratum, all(r.source != "synthetic" for r in members))
        allocation[cluster_id] = split
        messages[stratum][split] += len(members)
        clusters[stratum][split] += 1
    return allocation


def assign(
    records: Sequence[CorpusRecord],
    vectors: Sequence[Sequence[float]],
    threshold: float,
    keys: KeyRing,
    today: date,
) -> tuple[list[CorpusRecord], AssignReport]:
    """Assign the new records; `vectors` holds one embedding per record, in the same order."""
    if len(records) != len(vectors):
        raise ValueError("one embedding per record is required")
    report = AssignReport()
    new = [i for i, r in enumerate(records) if r.split is None]
    if not new:
        return list(records), report
    with_ids = [
        r if r.case_id is not None else r.model_copy(update={"case_id": case_id_for(r, keys)})
        for r in records
    ]
    ids = [str(r.case_id) for r in with_ids]
    if len(ids) != len(set(ids)):
        raise ValueError("two records share a case_id: the same text from the same source")
    similar = cosine_matrix(vectors) >= threshold
    anchors = [i for i, r in enumerate(records) if r.split not in (None, "excluded")]

    updates: dict[int, tuple[str, Split]] = {}
    discarded: set[int] = set()
    new_clusters: dict[str, list[int]] = {}
    for component in _components(new, similar):
        touched: dict[str, Split] = {}
        for _, a in np.argwhere(similar[np.ix_(component, anchors)]):
            anchor = records[anchors[a]]
            if anchor.cluster_id is not None and anchor.split is not None:
                touched[anchor.cluster_id] = anchor.split
        own_id = _cluster_id([ids[i] for i in component])
        if not touched:
            new_clusters[own_id] = component
        elif len(set(touched.values())) > 1:
            updates |= dict.fromkeys(component, (own_id, "excluded"))
            report.excluded += len(component)
        else:
            split = next(iter(touched.values()))
            for i in component:
                if split == "test" and records[i].source == "synthetic":
                    discarded.add(i)
                else:
                    updates[i] = (min(touched), split)
                    report.inherited += 1
    report.discarded_synthetic = len(discarded)

    assigned = [with_ids[i] for i in anchors] + [
        with_ids[i].model_copy(update={"cluster_id": cluster_id, "split": split})
        for i, (cluster_id, split) in updates.items()
    ]
    allocation = _allocate(
        {cid: [with_ids[i] for i in members] for cid, members in new_clusters.items()}, assigned
    )
    for cluster_id, members in new_clusters.items():
        updates |= dict.fromkeys(members, (cluster_id, allocation[cluster_id]))
    report.new, report.new_clusters = len(new), len(new_clusters)

    result = []
    for i, record in enumerate(with_ids):
        if i in discarded:
            continue
        if i in updates:
            cluster_id, split = updates[i]
            record = record.model_copy(
                update={"cluster_id": cluster_id, "split": split, "split_assigned_at": today}
            )
            report.splits[split] += 1
        result.append(record)
    return result, report


class DatasetVersionError(ValueError):
    pass


def unassigned(records: Sequence[CorpusRecord]) -> list[CorpusRecord]:
    """Clear clusters and splits, keeping case_ids, to re-cluster for a new major version."""
    return [
        r.model_copy(update={"cluster_id": None, "split": None, "split_assigned_at": None})
        for r in records
    ]


def next_dataset_info(
    info: DatasetInfo | None,
    *,
    threshold: float,
    embedding_model: str,
    new_major: bool,
) -> DatasetInfo:
    """The next version, carrying the count of discarded synthetic messages forward."""
    if info is None:
        version = "1.0"
    elif new_major:
        version = f"{int(info.dataset_version.split('.')[0]) + 1}.0"
    elif (info.cluster_threshold, info.embedding_model) != (threshold, embedding_model):
        raise DatasetVersionError(
            f"the splits were built with threshold {info.cluster_threshold} and "
            f"{info.embedding_model}; changing either re-clusters the whole corpus, which is a new "
            f"major version (rerun with --new-major)"
        )
    else:
        major, minor = info.dataset_version.split(".")
        version = f"{major}.{int(minor) + 1}"
    return DatasetInfo(
        dataset_version=version,
        cluster_threshold=threshold,
        embedding_model=embedding_model,
        discarded_synthetic=info.discarded_synthetic if info is not None else 0,
    )
