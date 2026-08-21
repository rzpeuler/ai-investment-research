# P8-B2-R5-C Harness JSON Boundary Recovery Design

Status: DESIGN ONLY / IMPLEMENTATION NOT AUTHORIZED  
Task: `P8-B2-R5-C-HARNESS-JSON-RECOVERY-DESIGN`  
Date: 2026-08-21

## Decision summary

The recommended design is an independent, deterministic JSON Boundary Recovery
Adapter between raw provider output and the existing Validator. It is not a
schema repairer and it is not an LLM call. It may remove unambiguous transport
formatting, but it must never create fields, change values, infer content, or
lower validation requirements.

This task authorizes design documentation only. No recovery code, production
routing change, schema change, validator change, threshold change, or runtime
switch is authorized.

## Problem and goals

R5-A made validator-driven field repair bounded and effective for
`missing_required_field`, but repair requires a parsed object. R5-B did not
establish provider-level structured-output support. The remaining bottleneck is
therefore raw output that is not directly parseable as JSON.

The recovery layer should increase the number of outputs that reach the
unchanged Validator while preserving an honest distinction between formatting
noise and model failure.

## Proposed data flow

```text
Provider transport
  -> Raw Model Output + provider/model/usage metadata
  -> JsonBoundaryRecovery (pure, bounded, deterministic)
  -> existing Normalizer boundary
  -> existing Validator
  -> Generation Controller
       -> bounded field-level Repair for parsed validation failures
       -> Artifact / honest fallback on unrecoverable failure
```

The provider adapter remains responsible for transport, provider errors, usage,
and model identity. The recovery adapter is responsible only for locating and
strictly parsing one JSON object. The Generation Controller remains responsible
for budget, validation, repair rounds, audit aggregation, and fallback.

## Architectural placement

### Option A: enhance the Harness Provider parser

This is the smallest local change, but it couples transport and parsing,
duplicates behavior across providers, and can make recovered output look like
native structured output. It also makes failure evidence harder to compare.

### Option B: place recovery in Generation Controller

This gives one common control point, but makes the controller responsible for
provider-format details. It blurs the boundary between generation control and
syntax handling and complicates reuse by non-Harness providers.

### Option C: independent recovery adapter (recommended)

This keeps provider transport, boundary recovery, validation, and repair
separate. The adapter can be unit-tested with deterministic fixtures, can be
opted in per provider, and can emit explicit audit facts without adding a
provider call. It preserves the current LlmClient and production default
runtime until a separate implementation task is authorized.

## Allowed recovery operations

The future implementation may perform only these operations, in this order:

1. Remove a UTF-8 BOM and surrounding whitespace.
2. Recognize one Markdown JSON fence when it contains one complete object.
3. Scan quotes and escapes to locate one complete, balanced JSON object.
4. Parse the candidate with strict `json.loads` semantics.
5. Reject non-object roots, duplicate keys, multiple candidates, ambiguous
   boundaries, oversized input, and any candidate that still fails strict
   parsing.

Recovery must not perform JSON5 parsing, comment removal, trailing-comma
repair, single-quote conversion, unquoted-key conversion, type coercion,
field insertion/deletion, value rewriting, or LLM-assisted repair. A recovered
object always enters the unchanged Normalizer and Validator.

## Failure taxonomy

| Class | Meaning | Next action |
| --- | --- | --- |
| `ALREADY_JSON` | Whole response is one strict JSON object | Validate |
| `RECOVERED_MARKDOWN_FENCE` | One unambiguous fenced object was extracted | Validate and audit recovery |
| `RECOVERED_SINGLE_OBJECT` | One unambiguous balanced object was extracted | Validate and audit recovery |
| `NO_JSON_BOUNDARY` | No object boundary exists | Typed `json_format_failure` / honest fallback |
| `UNBALANCED_JSON` | Boundary scan cannot close safely | Typed `json_format_failure` / fallback |
| `STRICT_PARSE_ERROR` | Candidate requires syntax mutation | Typed `json_format_failure` / fallback |
| `AMBIGUOUS_MULTIPLE_OBJECTS` | More than one plausible object exists | Reject; never guess |
| `NON_OBJECT_ROOT` | Strict JSON parses but violates the provider object contract | Typed format failure |
| `OVERSIZE_REJECTED` | Raw output exceeds the configured safety bound | Typed format failure |
| `DUPLICATE_KEY_REJECTED` | Object contains duplicate keys | Typed format failure |

The distinction is deterministic: only boundary/transport formatting is
recoverable. Any operation that changes JSON syntax or chooses semantic content
is a genuine model/output failure, not recovery.

## Result contract

The adapter should return a typed result, conceptually:

```text
status: ALREADY_VALID | RECOVERED | REJECTED | AMBIGUOUS
method: direct_json | markdown_fence | single_object | none
candidate_count: integer
parsed_object: object | none
reason: stable reason code
input_length: integer
raw_output_sha256: string
recovery_latency_ms: number
```

`parsed_object` is absent for rejected or ambiguous results. The result must
not claim schema validity; that status belongs exclusively to the existing
Validator.

## Audit design

Every provider attempt must retain the existing provider/model/mode/latency/
usage fields. The recovery extension should add:

- `recovery_status` and `recovery_method`;
- `recovery_reason` and `candidate_count`;
- bounded `raw_output_length` and `raw_output_sha256`;
- `recovery_latency_ms`;
- `post_recovery_validation_status`;
- `provider_calls` unchanged, with recovery contributing zero calls.

Raw model output must not be persisted in the normal audit artifact. If a
temporary diagnostic excerpt is ever authorized, it must be bounded and
secret-redacted. Recovery, including a successful recovery, must never be
reported as provider structured-output support.

## Security and integrity boundaries

- Use a bounded, quote-aware linear scan; do not use executable evaluation.
- Enforce a maximum raw-output size before scanning or hashing.
- Use strict JSON parsing and explicit duplicate-key rejection.
- Do not persist raw prompts or raw model responses by default.
- Do not retry the provider invisibly; recovery is local and single-pass.
- Keep recovery and validator failures separately measurable.
- A recovered object still needs full schema validation and normalizer rules.
- Any exception in recovery becomes a typed failure, never a silent fallback.

## Measurement plan for a future implementation

The implementation task must run the same fixed benchmark subset before and
after recovery, with no threshold changes. It must report at least:

- direct JSON success;
- recovered JSON success by method;
- unrecoverable and ambiguous counts;
- `json_format_failure` count;
- schema-valid rate;
- provider calls, latency, and token usage;
- audit completeness, fake `MODEL_INFERENCE`, validator bypass, and silent
  retry counts.

The primary success criterion is an honest reduction in format failures without
any increase in fabricated fields, validator bypass, hidden calls, or audit
gaps. A schema-valid increase is necessary for promotion but is not assumed by
syntax recovery alone.

## Go / no-go decision

The design is worth implementing as a narrow R5-C experiment because it targets
the measured bottleneck and does not require unsupported provider structured
output. However, this task does not authorize implementation. A future task
must first add deterministic unit tests for every taxonomy class, then run the
fixed probe and benchmark.

R5-D is **not entered** by this design task. R5-D may begin only after a
separate authorized implementation passes offline validation and produces a
comparable benchmark artifact. P8-B3 remains **NOT_AUTHORIZED** and its
thresholds remain unchanged.

## P8-B3 impact

No immediate impact. The recovery layer can improve parse reachability, but it
cannot establish P8-B3 readiness. P8-B3 assessment must continue to use the
existing schema-valid, audit, budget, secret, retry, and production-adoption
gates. Recovery results must be reported as a separate dimension.

## Acceptance state

```text
P8-B2: IMPLEMENTED / PARTIAL / NOT ACCEPTED
R5-C: DESIGN COMPLETE / IMPLEMENTATION NOT AUTHORIZED
R5-D: BLOCKED PENDING R5-C IMPLEMENTATION + BENCHMARK
P8-B3: NOT_AUTHORIZED
PRODUCTION_ADOPTION: NOT_AUTHORIZED
```
