# ADR-0004: Structural privacy, redaction floors and Peru's data protection law

- Status: Accepted (2026-10-07)
- Date: 2026-10-06
- Deciders: Alessandro David
- Related: `docs/SPEC.md` (Requisitos no funcionales), `CLAUDE.md` rules 4, 5 and 13, ADR-0005, EF-06, EF-19, EF-24, EF-25

## Context

The messages people check carry other people's personal data: phone numbers, DNI, bank accounts, cards, emails and names. Often these belong to the victim, to the relative being impersonated, or to someone whose phone was stolen.

The service runs under Peru's Personal Data Protection Law (Ley N.° 29733) and its current regulation. That regulation was approved by Decreto Supremo N.° 016-2024-JUS, published on 2024-11-30, and has been in force since 2025-03-31. It replaced D.S. N.° 003-2013-JUS.

Processing involves transfers abroad: the LLM provider, Meta (WhatsApp) and the hosting provider. Many users are older adults.

Privacy that relies on "remember not to log it" fails the first time someone adds a debug line. Privacy must come from the shape of the system.

## Decision

### 1. Raw text never outlives the redactor

- **Type boundary.** Only the pipeline entry point accepts the raw message. It returns a `RedactedText` value, and every later stage, repository, log call and LLM client accepts only `RedactedText`. Mypy in strict mode plus a structural test keep that boundary.
- **Normalisation, before redaction.** NFKC, removal of zero-width characters, and removal of forwarding metadata.
- **Deterministic redaction.** Regular expressions with validators for Peruvian phone numbers, DNI, bank accounts and CCI, cards (Luhn check) and emails, plus the Yape holder pattern. Each item is replaced by a typed placeholder (for example `[PHONE]`), so rules can still see that a phone number was present.
- **Name redaction.** spaCy's Spanish model, `PER` entities only. An exemption list is built from `config/official_domains.yaml` and `config/modalities.yaml` so that brands such as BCP, Interbank or Yape survive.
- **URLs.** The redactor also applies to URLs. Identifiers in query strings and fragments are redacted before `url_redacted` is stored (ADR-0005).
- **Errors.** Pydantic models use `hide_input_in_errors=True`, and the 422 handler returns no body.
- **Logs.** The structlog pipeline never receives message text. `audit_log` never stores text.
- **Keys.**
  - Identities, message ids and text are stored only as HMACs, each prefixed with its `key_id`. During a key rotation, lookups try every active key.
  - Reply addresses are encrypted with AES-GCM under a separate key and deleted on send or after 24 h.
- **Retention.**
  - Text is purged after 30 days.
  - Donated text waiting to be labelled is kept at most 90 days.
  - The donated corpus is kept 2 years, or until the user withdraws it with their deletion code.
- **Consent first.** No verification is created without an accepted privacy notice. Every verification stores `privacy_notice_version`. Donation is opt-in per message, with `consent_version`.

### 2. How redaction floors are set

This ADR fixes the method. The values come later.

- **Deterministic types** (phone, DNI, account, card, email): the floor is 100 %. Canary values, with every format we support, must be absent from:
  - a database dump,
  - the captured logs,
  - the payload sent to a simulated LLM.

  This is a CI test (EF-06, EF-19).
- **Names (`PER`).** The floor is statistical:
  1. EF-06 builds a labelled set of message-like texts with gold name spans. It includes Peruvian given names and compound surnames, nicknames, lowercase and missing accents. Brand names and modality words serve as negatives.
  2. We measure recall per type, with a Wilson 95 % interval, and the survival rate of exempted brands, which must be 100 %.
  3. The spaCy model size (sm, md or lg) is chosen by recall against the 150 ms stage budget.
  4. The floor is the lower bound of the measured interval, rounded down to the nearest whole point. It is recorded with its date, the model and the dataset in an amendment to this ADR after EF-06.
  5. From then on, CI fails if name recall on that set falls below the floor.
- **Versioning.** `redactor_version` goes into every manifest. Any change to patterns, the model or the exemption list bumps it.

### 3. Legal compliance is a separate checklist (EF-25)

EF-25 checks the official text of Ley 29733 and D.S. 016-2024-JUS before production opens to the public in sprint 4. It covers:

- registration of the personal data bank with the Autoridad Nacional de Protección de Datos Personales,
- transfers abroad (LLM provider, Meta, hosting),
- the incident procedure,
- the privacy notice,
- minors,
- backups,
- retention of the donated corpus.

This ADR is a technical decision, not legal advice. A lawyer's review is desirable.

## Alternatives considered

- **Encrypted raw text, kept for debugging or labelling.** It increases the impact of a breach and the legal obligations. Labelling works on redacted text. Rejected.
- **Redaction by an LLM.** It sends raw text to a third party, which defeats the purpose. Rejected.
- **A heavier PII framework.** Possible, but regular expressions plus spaCy cover the required types with less weight. It can be revisited if EF-06 measures poor recall.
- **No name redaction.** Simpler, but names of victims and relatives would persist. Rejected.

## Consequences

- A breach exposes only redacted text, HMACs and metadata, and text disappears after 30 days.
- We cannot reproduce a user's exact message to debug a wrong verdict. Debugging works on redacted text and stored signals.
- Over-redaction can hide content a rule needed. Typed placeholders keep the signal "contains a phone number" without the number.
- Name recall will be below 100 %. That residual risk is measured, declared and bounded by the floor.

## References

- Ley N.° 29733, Ley de Protección de Datos Personales.
- Decreto Supremo N.° 016-2024-JUS: https://www.gob.pe/institucion/anpd/campa%C3%B1as/128319-nuevo-reglamento-de-proteccion-de-datos-personales
- MINJUSDH announcement: https://www.gob.pe/institucion/minjus/noticias/1067368-ejecutivo-aprueba-nuevo-reglamento-de-la-ley-de-proteccion-de-datos-personales

## Amendment 1 (2026-10-06): name-redaction floor, set after EF-06

### Method change: precision is measured too

The first measurement showed that the recogniser also takes sentence-initial verbs and other words for names ("Depositale", "Quedaste", "Mañana"). Each false `[NAME]` erases a word the rules may need, and "Depositale" is itself a scam signal. Precision is therefore reported next to recall, defined as the share of name spans that cover a real name.

### Sets

- **Development set** (`evals/redaction/names.jsonl`): 156 messages, 210 names. Used to choose the model and to design the filters.
- **Validation set** (`evals/redaction/names_validation.jsonl`): 103 messages, 120 names. It uses other phrasings and other name pools, was written before any measurement on it and was never used for tuning.

Both sets are synthetic. The generator is `evals/redaction/generate_names.py`, and every name is an invented combination of common Peruvian first names and surnames.

### Development measurements, used to choose

| Model | Recall | Precision | p95 |
| --- | --- | --- | --- |
| es_core_news_sm | 70.5 % | not measured | 3.5 ms |
| es_core_news_md | 83.3 % | 82.2 % | 4.0 ms |
| es_core_news_lg | 86.7 % | 77.8 % | 3.6 ms |
| md, entity kept only if it contains a proper noun | 81.9 % | 95.8 % | 4.0 ms |
| lg, entity kept only if it contains a proper noun | 86.2 % | 89.3 % | 4.1 ms |

### Decision (owner, 2026-10-06)

- **Model.** `es_core_news_lg` 3.8.0 on spaCy 3.8.16, running tok2vec, morphologizer and ner. A PER entity counts only if it contains a proper noun (PROPN).
- **Cue phrases.** A deterministic rule catches capitalised names right after cue phrases such as "soy", "hola", "felicidades", "mi nombre es", "te escribe" and "Sr./Sra./Dr./Ing./Lic.". It skips kinship and generic words ("Mamá", "Tía", "cliente", "Dios"). The rule was kept only because it raised recall on the validation set without lowering precision.
- **Brands.** Official brands from `config/official_domains.yaml` and `config/modalities.yaml` are always kept. They were 100 % kept on both sets.

### Validation measurements, which set the floor

| Variant | Recall (Wilson 95 % lower bound) | Precision | Negatives with a false `[NAME]` | p95 |
| --- | --- | --- | --- | --- |
| lg with the PROPN filter | 85.0 % (77.5 %) | 82.6 % | 2 of 7 | 9.0 ms |
| **lg with the PROPN filter and cue phrases** | **95.8 % (90.6 %)** | **84.1 %** | 3 of 7 | 9.9 ms |

### Floor

`name_recall_floor = 0.90`. It is the 90.6 % lower bound rounded down, stored in `config/thresholds.yaml`. CI fails if recall on the validation set drops below it (`test_name_recall_on_validation_meets_the_floor`).

### Known limits, declared and left untuned so the validation set stays clean

- **False positives seen on validation:** "Su", "Atte", "Jefe de Créditos", "Papá", "Feliz Navidad", "Gracias Dios" and "Lima".
- **Lowercase names** such as "oye ximena" are mostly missed.
- **Real messages.** The sets are synthetic and written by the developer, so recall on real messages may be lower. The floor must be re-measured on real donated and public messages (EF-09) with a fresh validation set.
- **Image size.** The lg model adds about 550 MB to the backend image and to its memory use.
