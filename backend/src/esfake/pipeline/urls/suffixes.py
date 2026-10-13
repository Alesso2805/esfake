"""Registered domains from a vendored Public Suffix List snapshot (ADR-0005 §2).

The list is read from the repository and never downloaded; a small reader replaces libraries
that fetch the latest list on first use. Its ICANN and private sections both apply, so
`bcp-seguro.github.io` is a registered domain of its own, as whoever controls it sees it.
Hosts and rules are compared in Unicode: punycode labels are decoded before the lookup.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class PublicSuffixList:
    version: str
    rules: frozenset[str]
    wildcards: frozenset[str]  # "ck" for the rule "*.ck"
    exceptions: frozenset[str]  # "www.ck" for the rule "!www.ck"
    top_level: frozenset[str]

    def public_suffix(self, host: str) -> str:
        """The longest matching rule, exceptions first; with none, the last label (rule "*")."""
        labels = host.split(".")
        for i in range(len(labels)):
            if ".".join(labels[i:]) in self.exceptions:
                return ".".join(labels[i + 1 :])
        for i in range(len(labels)):
            candidate = ".".join(labels[i:])
            if candidate in self.rules or ".".join(labels[i + 1 :]) in self.wildcards:
                return candidate
        return labels[-1]

    def registered_domain(self, host: str) -> str | None:
        """The public suffix plus one label; None when the host is a public suffix itself."""
        suffix = self.public_suffix(host)
        if host == suffix or not host.endswith("." + suffix):
            return None
        owner = host[: -len(suffix) - 1].rsplit(".", 1)[-1]
        return f"{owner}.{suffix}"

    def knows_top_level(self, label: str) -> bool:
        return label in self.top_level


@lru_cache(maxsize=4)
def load_public_suffix_list(path: Path) -> PublicSuffixList:
    version = ""
    rules: set[str] = set()
    wildcards: set[str] = set()
    exceptions: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("// VERSION:"):
            version = line.removeprefix("// VERSION:").strip()
        if not line or line.startswith("//"):
            continue
        rule = line.split()[0].lower()
        if rule.startswith("!"):
            exceptions.add(rule[1:])
        elif rule.startswith("*."):
            wildcards.add(rule[2:])
        else:
            rules.add(rule)
    if not version:
        raise ValueError(f"{path} has no VERSION line: use a dated snapshot")
    top_level = {rule.rsplit(".", 1)[-1] for rule in rules | wildcards | exceptions}
    return PublicSuffixList(
        version, frozenset(rules), frozenset(wildcards), frozenset(exceptions), frozenset(top_level)
    )
