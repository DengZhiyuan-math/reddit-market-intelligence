# Compliance Guardrails

This document is product guidance for the Reddit Market Intelligence System. It is not legal advice, proof of Reddit approval, or a substitute for reviewing the current Reddit terms before production or commercial use.

## Access Modes

Projects must declare one of three access modes:

- `personal` — Personal or local experimentation within allowed Reddit API limits.
- `research` — Research use that still must remain inside permitted limits and policy boundaries.
- `commercial-approved` — Business or monetized use with an approved Reddit access path or separate agreement.

The system should treat business or commercial project context as blocked unless the project is explicitly marked `commercial-approved`.

## Commercial Use Guardrail

Reddit's Developer Terms and Data API Terms describe restrictions for commercial use, monetized products, and research in excess of rate limits. This project should not silently collect Reddit data for business or monetized use unless the access mode is `commercial-approved` and an approval reference is recorded.

## Retention And Deletion Policy

The default retention policy is conservative:

- `REDDIT_RETENTION_POLICY_DAYS=2`
- `REDDIT_DELETE_REMOVED_CONTENT=true`

The policy covers all downstream targets:

- raw text
- cleaned text
- embeddings
- LLM inputs
- LLM outputs
- market signals
- reports
- exports
- logs
- caches
- backups

Later phases must propagate deletion/removal handling across these targets instead of only deleting raw records.

## Rate Limit Expectations

The collector must use OAuth or login credentials, a descriptive User-Agent, and rate-limit-aware behavior. Later collection code must record and respect Reddit response headers such as `X-Ratelimit-Used`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset`.

## Prohibited Automation

This MVP is a market research and content strategy tool. The following workflows are excluded from the MVP codebase and are not planned v2 features:

- automatic posting
- automatic commenting
- private messaging
- voting
- multi-account operation
- account farming
- hidden promotion
- ban evasion

Transparent, manual, subreddit-rule-aware participation guidance may appear in reports, but engagement automation is outside the codebase boundary.

## Sources

- Reddit Data API Wiki: https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki
- Reddit Developer Terms: https://redditinc.com/policies/developer-terms
- Reddit Data API Terms: https://redditinc.com/policies/data-api-terms
