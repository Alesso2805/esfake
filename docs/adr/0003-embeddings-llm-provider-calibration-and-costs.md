# ADR-0003: Embeddings, LLM provider, threshold calibration and running costs

- Status: Accepted (2026-10-07)
- Date: 2026-10-06
- Deciders: Alessandro David
- Related: `CLAUDE.md` (Stack obligatorio, rules 11 and 12), ADR-0002, ADR-0004, EF-07, EF-10, EF-13, EF-14, EF-15, EF-18, EF-23, EF-25

## Context

The pipeline needs two models:

- An embedding model for similarity search and corpus clustering (384 dimensions, multilingual, CPU only, loaded only by the API process in production).
- A language model for the judge (ADR-0001) and for the LLM-only baseline (ADR-0006).

`CLAUDE.md` requires a provider that does not retain or train on our data. Rule 12 asks this ADR to record how thresholds are calibrated. EF-01 asks it to estimate infrastructure cost and to confirm Meta's WhatsApp free tier. The owner prefers free services wherever possible.

## Decision

### 1. Embedding model

**Model.** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`:

- 384 dimensions, Apache-2.0 licence, mean pooling, no input prefixes.
- Inputs are truncated at 128 tokens, which is enough for SMS and WhatsApp messages.

**Runtime.** fastembed on ONNX Runtime, using fastembed's quantised ONNX build (about 220 MB). No PyTorch: the image is hundreds of MB smaller and the process needs far less memory, so the API fits on a small instance next to spaCy. fastembed supports this model natively.

**Packaging.**

- Weights are downloaded at image build time, and the runtime works offline.
- CI caches the weights (EF-02).
- The manifest records the model id and a hash of the ONNX file.

**Checkpoint in EF-07, before freezing.**

1. Before the cluster threshold is fixed and splits are assigned, compare this model with `intfloat/multilingual-e5-small`, run through onnxruntime with the `query: ` prefix. The comparison uses our own labelled near-duplicate pairs.
2. Measure the share of corpus messages longer than 128 tokens.
3. If e5-small is clearly better, switch then and amend this ADR.

After splits are assigned, changing the model means re-clustering. That creates a new major dataset version and restarts the gate comparison.

**Published scores** (MTEB results repository, Spanish STS):

| Model | STS17 es-es | STS22 es |
| --- | --- | --- |
| MiniLM-L12-v2 | 85.6 | 56.6 |
| multilingual-e5-small | 85.3 | 67.0 |

Neither benchmark resembles short scam messages, which is why the EF-07 checkpoint uses our own data.

### 2. LLM provider and model

**Provider and model.** Amazon Bedrock running Anthropic's Claude Haiku 4.5. The exact Bedrock model id and client are fixed in EF-10 against the current Bedrock documentation. Code reaches the model only through `LLMClient`, so changing provider means changing one adapter.

**Why Bedrock.** Every provider we compared states that it does not train on API data. Only Bedrock documents that, by default, it does not store model inputs or outputs. The others need an approved zero-retention agreement:

- The Anthropic API deletes inputs and outputs within 30 days.
- OpenAI keeps abuse-monitoring logs up to 30 days.
- Vertex AI logs prompts for abuse detection unless an exception is granted.

Claude Haiku 4.5 is not among the Bedrock models that require retention.

**Required configuration** (checked in EF-10, re-checked in EF-18):

- The account's data-retention mode is `none` in every Region we call.
- Bedrock model-invocation logging stays disabled. If enabled, it would store prompts in our own CloudWatch or S3.
- Requests use Bedrock's global inference profile, because South America has no in-region profile for Claude. Processing may therefore happen in any commercial AWS Region. This is a transfer abroad and goes into the EF-25 checklist.
- The free tier of the Gemini Developer API must never be used. Its terms allow using inputs to improve products and allow human review.

**Price.** Anthropic's list price for Haiku 4.5 is US$1 per million input tokens and US$5 per million output tokens. We could not read Bedrock's price page, and regional endpoints can carry a premium. At about 800 input and 100 output tokens per call, one call costs roughly US$0.0013, so 1,000 calls cost about US$1.30.

### 3. Spending caps (`spend_ledger`)

| Scope | Cap | Behaviour at the cap |
| --- | --- | --- |
| LLM, production | US$10 per month, with a daily sub-cap of US$1 | Degraded mode: `suspicious` with the "limited verification" template (ADR-0001) |
| LLM, `make eval-record` (local) | US$5 per run, enforced by the CLI | The run stops and reports what is missing |
| WhatsApp | 1,000 service messages per month, the free tier, so US$0 | Each identity receives one notice with the link to the web |

**Expected use:**

- The pilot is about 20 people with about 10 verifications each. At most 40 % of verifications reach the model, so about 80 calls, roughly US$0.10.
- A public demo with up to 5,000 verifications a month means at most 2,000 calls, roughly US$2.60.
- A release evaluation (`eval` and `test` for the judge and for the LLM-only baseline, plus N = 3 live runs) is under 1,000 calls, roughly US$1.30.

### 4. WhatsApp pricing (confirmation for EF-01)

Meta's page on non-template messages states:

- "Effective October 1, 2026, Meta will charge on a per-message basis for service messages."
- "By market, rates for service messages are the same as the rates for utility and authentication messages."

The same page marks utility templates inside the customer service window as free only until that date.

The free tier of 1,000 delivered service messages per business phone number per month appears in Meta's pricing documentation as indexed by search. The pricing page we fetched on 2026-10-06 showed only the older text ("service conversations are now free"), so the free tier is **not yet quoted verbatim**.

We plan conservatively: messages are charged, the cap is 1,000 messages, and EF-23 checks the actual charges in WhatsApp Manager during the first month. The rate for Peru comes from Meta's rate card in EF-23. Under the cap above it does not affect cost.

### 5. Infrastructure: Oracle Cloud Infrastructure Always Free

**Decision.** Production runs on one Always Free Ampere A1 VM:

- Up to 2 OCPUs and 12 GB of RAM as a single instance.
- 200 GB of block storage and 20 GB of Object Storage.
- The home region is São Paulo or Santiago, because Always Free resources exist only in the home region.

Docker Compose runs the same services as in local development: the API with its internal listener, both workers, the web app, and PostgreSQL 16 with pgvector.

**Cost.**

| Item | Cost |
| --- | --- |
| Infrastructure | US$0 |
| Bedrock | Capped at US$10 per month; expected under US$3 |
| WhatsApp | US$0 under its cap |
| Domain (EF-18) | A yearly fee, or a free subdomain |

**Requirement relaxed.** Postgres is self-managed, not managed. We own upgrades, monitoring and backups. `docs/SPEC.md` and EF-18 were updated accordingly.

**Requirements that still hold:**

- The instance is always on and nothing suspends Postgres.
- A direct connection is available for `LISTEN`.
- pgvector is available.
- Backups are kept at most 30 days: a nightly `pg_dump` goes to Object Storage, a lifecycle rule deletes copies after 30 days, and EF-18 tests a restore.

**Risks and mitigations:**

- **Idle reclamation.** Oracle may reclaim Always Free instances whose CPU (95th percentile), network and memory (on A1) all stay below 20 % for 7 days. EF-18 monitors this and checks whether upgrading the account to Pay As You Go, which keeps Always Free resources at no cost, removes reclamation (not verified). We will not generate artificial load to evade the policy.
- **Capacity.** Creating an A1 instance can fail with "out of host capacity". The owner creates the VM well before sprint 4.
- **ARM64.** Images are built for `linux/arm64` as well as `linux/amd64`, and every dependency must ship arm64 builds: onnxruntime, spaCy, asyncpg and the pgvector image. This is checked when the images are first built (EF-04) and again in EF-18.
- **Single point of failure.** One VM serves everything. That is acceptable for a pilot and a demo, and an uptime monitor alerts on outages (EF-18).
- **The free offer may change.** Plan B is a DigitalOcean Droplet with managed PostgreSQL, about US$39 per month on 2026-10-06. It reuses the same Compose files except for the database service.

**Free options rejected** (2026-10-06):

| Option | Reason |
| --- | --- |
| Supabase Free | Pauses after a week of inactivity; no managed backups |
| Neon Free | Suspends after 5 minutes and cannot be disabled |
| Render Free | Web services sleep; the database is deleted after 30 days |
| Aiven Free | Powers off when idle; 1 GB of storage |
| Google Cloud e2-micro | Too little memory |
| AWS, Azure and Google credits | Expire within 3 to 12 months and require new accounts |

**Paid options that meet the original spec unchanged:**

| Option | Approximate cost per month |
| --- | --- |
| DigitalOcean (Droplet plus managed Postgres) | ~US$39 |
| Neon plus a Droplet | ~US$45 |
| Fly.io | ~US$62 |
| Render | ~US$65 |

### 6. Threshold calibration method (rule 12)

All values live in `config/thresholds.yaml`, which carries a version recorded in every manifest. Calibration uses `eval` only and never `test`.

**Cluster threshold (EF-07)**, fixed before splits are assigned:

1. Compute pairwise cosine similarity over the corpus.
2. Draw about 100 pairs in narrow bins around candidate cuts.
3. Label each pair by hand: "same message or a near-duplicate variant" versus "different".
4. Pick the cut with the best agreement with those labels, breaking ties towards the lower threshold, because grouping too much is safer than leaking near-duplicates across splits.

The labelled pairs are committed as evidence. Changing the threshold later creates a new major dataset version (`CLAUDE.md` rule 12).

**k and δ for similarity decisions (EF-13):**

- Grid search on `eval` over k ∈ {3, 5, 7} and δ ∈ {0.02, 0.04, …, 0.10}.
- The objective is to maximise the scam cases decided by similarity, with no legitimate `eval` case raised by similarity.
- Ties go to the larger δ.

**Out-of-distribution threshold (EF-14).** The 5th percentile of the maximum similarity to `index` among in-distribution `eval` messages. The proportion of each route is reported.

**Policy thresholds (EF-15).** Fitted on `eval` under the floors of ADR-0001 and the gate of ADR-0006.

## Alternatives considered

- **sentence-transformers on PyTorch.** Hundreds of MB more image and roughly 1 GB of RAM, for the same model. Rejected.
- **multilingual-e5-small or granite-embedding-107m-multilingual.** Both are 384-dimensional and comparable, but not natively supported by fastembed, so they need manual ONNX wiring. e5-small stays as the EF-07 contender.
- **Anthropic API directly.** The simplest setup, but it keeps data up to 30 days without a zero-retention agreement.
- **OpenAI or Vertex AI.** Cheaper per call, but both retain data for abuse monitoring by default. At our volume, price does not decide.
- **A self-hosted open model.** No third party at all, but CPU inference cannot meet the 3 s judge timeout on a small instance.

## Consequences

- The privacy requirement holds by default without negotiating an agreement. One AWS account and its configuration must be audited (EF-10, EF-18).
- LLM cost is negligible at pilot scale. The caps protect against abuse rather than against normal use.
- A small, CPU-only embedding stack keeps the free or cheap hosting options open.
- The embedding choice is provisional until EF-07, then frozen.
- Hosting is free but self-managed. Database operations and the reclamation risk are ours, with a costed plan B.
- Data crosses borders in every option: Bedrock's global profile, Meta and Oracle's region in Brazil or Chile. EF-25 must cover these transfers.

## References

- Bedrock data retention: https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html
- Bedrock abuse detection: https://docs.aws.amazon.com/bedrock/latest/userguide/abuse-detection.html
- Anthropic API data retention: https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
- OpenAI data controls: https://developers.openai.com/api/docs/guides/your-data
- Vertex AI data governance: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance
- Gemini API terms: https://ai.google.dev/gemini-api/terms
- fastembed supported models: https://qdrant.github.io/fastembed/examples/Supported_Models/
- MiniLM model card: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- e5-small model card: https://huggingface.co/intfloat/multilingual-e5-small
- MTEB results: https://github.com/embeddings-benchmark/results
- Meta, non-template messages: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
- Meta, pricing: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Oracle Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- Oracle regions: https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm
- Supabase pricing: https://supabase.com/pricing
- Neon pricing: https://neon.com/pricing
- Render free tier: https://render.com/docs/free
- Aiven free plan: https://aiven.io/docs/platform/concepts/free-plan
- DigitalOcean managed databases pricing: https://www.digitalocean.com/pricing/managed-databases

## Amendment 1 (2026-10-11): how the embedding checkpoint decides, fixed before measuring

§1 asks for a comparison between MiniLM and `multilingual-e5-small` on our own labelled near-duplicate pairs, and for a switch only if e5 is "clearly better". This amendment fixes what that means before any pair is labelled, as ADR-0006 did for the non-inferiority margin. The owner approved it on 2026-10-11.

### Contender

- `intfloat/multilingual-e5-small`, from the ONNX export in its own Hugging Face repository (`onnx/model.onnx`, fp32, about 470 MB).
- Mean pooling, L2-normalised vectors, and the `query: ` prefix on every text, e5's convention for symmetric similarity.
- fastembed does not ship it, so it is registered as a custom model. It is `embedding_contender` in `config/models.yaml` and the API never loads it.
- MiniLM is compared as deployed: fastembed's quantised ONNX build.

### Pairs

- `esfake corpus pairs` takes half the pairs near each model's cut.
- MiniLM's bins span cosine 0.70 to 0.98.
- e5's bins span the range that holds the same pairs by rank. e5 rates even unrelated messages around 0.8, so the same numbers would mean different things.
- One labelled set therefore serves both the checkpoint and the cluster threshold of whichever model wins (§6).

### Measures

Both models are scored on the same labelled pairs:

- **AUC** of cosine similarity for "same" against "different". It needs no threshold.
- **Best cut** by F1, with the §6 rule, and its agreement with the labels.
- **p95 latency** to embed one message, on the development machine. Each model is timed in a fresh process with no other model loaded (see below).
- **Long messages:** the share of corpus messages over 128 tokens (MiniLM's training length) and over 512 tokens (e5's window), each counted with its own tokenizer.

### Decision rule

e5-small replaces MiniLM only if both hold:

1. The lower bound of the 95 % paired bootstrap interval of AUC(e5) − AUC(MiniLM) is above 0. The bootstrap resamples pairs 10 000 times with a fixed seed.
2. Its p95 latency per message is at most 200 ms, the budget of the similarity layer.

Otherwise MiniLM stays. Switching costs a new image, a new threshold and re-clustering, and an AUC difference that the interval cannot tell from zero does not pay for that.

The results go to `docs/evals/embedding-comparison.json` and to a second amendment, whichever way they fall. Latency on the production VM (ARM) is checked again in EF-18.

### Latency is measured one model per process (clarified 2026-10-11, before any measurement)

A first dry run timed both models in the same process and made e5 look about 17 times slower than MiniLM: p50 around 120 ms against 6.5 ms. Each model alone takes about 6.5 ms (p50) and 8 ms (p95) on the development machine.

The cause is two ONNX Runtime sessions in one process slowing each other down. It hits whichever model runs second, and freeing the first session does not help. `esfake corpus compare-models` therefore times each model in a fresh process.

The same constraint holds in production: one ONNX Runtime session per process. The API loads only the embedding model, so it holds today. Any later ONNX model goes in its own process or must be measured together with this one.
