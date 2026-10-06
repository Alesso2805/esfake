# ADR-0005: URL analysis without network requests

- Status: Proposed
- Date: 2026-10-06
- Deciders: Alessandro David
- Related: `docs/SPEC.md` (Pipeline, Seguridad web), `CLAUDE.md` rule 10, ADR-0004, EF-12, EF-21

## Context

A large share of the target scams carry a link. Typical examples:

- A domain that imitates a bank or wallet, such as `bcp-validacion.com` or `yape-premios.net`.
- A URL shortener.
- An IDN homograph, where Cyrillic letters pass for Latin ones.

The obvious way to judge a link is to visit it, resolve it or ask a reputation service. All three are harmful here:

- **Privacy.** The URL is message-derived data, and its path or query often carries a token that identifies the victim. Sending it anywhere is a transfer to a third party (ADR-0004).
- **Tipping off the scammer.** Requesting a tracking link tells the scammer that the target is active.
- **Security.** Fetching attacker-chosen URLs from our servers invites server-side request forgery (SSRF) and exposure to malware.
- **Reproducibility.** Live pages, DNS and reputation lists change over time, so the same evaluation would give different results tomorrow.
- **Latency.** Network calls do not fit a 20 ms stage budget.

## Decision

### 1. No network activity for message URLs

For URLs that come from messages there are no HTTP requests, DNS lookups, WHOIS or RDAP queries, redirect expansion or reputation-API calls. Tests that fail on any socket use during URL analysis enforce this (EF-12).

### 2. Signals come only from versioned local data

- **Registered domain.** Taken from a vendored, dated snapshot of the Public Suffix List. If a library wraps the list (for example `tldextract`), it is configured to use only the vendored snapshot, because some libraries download the latest list on first use.
- **Shorteners.** Checked against a versioned list. A shortener is a signal in itself; we never expand it.
- **Brand token on a non-official domain.** A brand token (for example `bcp` or `yape`) inside a registered domain that is not on the official list. Tokens and official domains come from `config/official_domains.yaml`.
- **Lookalikes.** Two measures against each official domain:
  - The UTS #39 skeleton, computed from a vendored `confusables.txt` of a pinned Unicode version.
  - A normalised edit distance.

  The imitated domain is stored in `urls.lookalike_of` and the score in `urls.lookalike_score`.
- **IDN and punycode.** `xn--` labels are decoded. IDN labels and labels that mix scripts are flagged (`urls.is_idn`).

All of these data files are in the repository. Updating any of them is a commit and therefore changes the manifest.

### 3. Storage and display

- URLs are stored only in redacted form (`url_redacted`). The redactor (ADR-0004) removes identifiers in query strings and fragments. `url_redacted` is purged with the rest of the text at 30 days.
- The interface shows URLs neutralised (`hxxps://example[.]com`), never as clickable links. Highlighting uses offsets and never renders HTML from the user.

## Alternatives considered

- **Reputation services (Safe Browsing, VirusTotal, URLhaus).** Better coverage of known-bad URLs. Rejected for the MVP because they send message-derived data to a third party abroad, create an external dependency and make evaluations non-reproducible. Any future use needs a new ADR, a privacy review and, at minimum, local hash-prefix matching instead of per-URL lookups.
- **Expanding shorteners to see the destination.** It tips off the scammer and opens a server-side request forgery risk. Rejected.
- **Domain age through WHOIS or RDAP.** A strong signal, but it needs the network, has rate limits and is not reproducible. Rejected for the MVP.
- **Rendering pages in a sandbox.** Expensive, slow and exposed to the same tip-off problem. Out of scope.

## Consequences

- The stage is deterministic, fast, testable without mocks and leaks nothing.
- It misses brand-new malicious domains that imitate no listed brand and are not shorteners. Rules, similarity and the judge must cover those cases, and the evaluation reports them.
- The Public Suffix List, the shortener list, the official domains and `confusables.txt` age over time. Refreshing them is manual, and each refresh is a reviewed commit that changes the manifest.

## Verification

- A test fails if URL analysis opens any socket.
- Unit tests per signal: registered-domain extraction on multi-part suffixes such as `gob.pe` and `com.pe`, each listed shortener, a brand token on a non-official domain, confusable skeletons, and punycode decoding.
- Web tests (EF-21): URLs render neutralised and non-clickable, and highlighting never injects HTML.
