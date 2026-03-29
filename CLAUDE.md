# Kensho — Project Conventions

## What is Kensho?
Multi-agent AI stock research assistant for a single Indian retail investor (NSE/BSE positional trader).
Delivers pre-trade analysis and behavioural guardrails via WhatsApp in under 60 seconds.
NOT a stock predictor. Every output is decision support only.

## Project Structure
```
agents/          # One file per agent
tools/           # @tool decorated functions, one concern per file
interface/       # WhatsApp webhook, formatter, language detection
infrastructure/  # CDK stack (the ONLY permitted deployment mechanism)
dashboard/       # React 18 frontend (build last)
tests/           # Mirrors source: test_tools/, test_agents/, test_e2e/
conftest.py      # Shared pytest fixtures
```

## Agent Framework
- Use `strands-agents` for all agents
- Model: `AnthropicModel(model_id="claude-sonnet-4-6")` — always this pattern
- Every agent exposes `run(query, session_context, **kwargs) -> AgentOutput`
- Every `@tool` function: decorator + docstring + type hints, no exceptions

## Credentials — NEVER hardcode
```python
from tools.secrets import get_secret
creds = get_secret("kensho/iifl")
```
Secrets Manager paths: `kensho/iifl`, `kensho/twilio`, `kensho/anthropic`, `kensho/config`
Never use `.env` files, environment variables, or DynamoDB for credentials in production.

## Data partitioning — CRITICAL
Every function that reads or writes data MUST accept `user_id` as an explicit parameter.
No global `USER_ID` constant is permitted anywhere in the codebase.

## Session Context
Every agent receives a `SessionContext` dataclass containing:
- `user_id`, `investor_profile`, `live_portfolio`, `sector_allocations`
- `cache_age_seconds`, `cache_is_stale`, `language` ("en" | "hi")

## Mandatory output rules
- Every response includes confidence level: HIGH (RAGAS > 0.8) / MEDIUM (0.6–0.8) / LOW (< 0.6)
- Every response ends with: "This is research assistance only. Not financial advice. Past performance does not guarantee future results."
- Position sizing runs on every analysis — never skipped
- Sector concentration check runs on every analysis — never skipped
- WhatsApp output hard ceiling: 1500 chars (truncate at last complete sentence, append "Full report on dashboard.")

## Testing gate — enforce strictly
```bash
# Tool built
pytest tests/test_tools/test_<tool>.py -v

# Agent built
pytest tests/test_agents/test_<agent>.py -v

# Sprint done — run in this order
pytest tests/ -v        # must be all green
cdk synth               # validate CloudFormation template
cdk diff                # review infra changes
cdk deploy              # deploy
```
- Use `moto` to mock all AWS calls
- Use `mock_anthropic_model` fixture — no real Anthropic API calls in tests
- Use `hypothesis` for property-based tests

## NSE ticker format
yfinance: `TICKER.NS` (e.g. `RELIANCE.NS`, `INFY.NS`)

## DynamoDB tables
`investor_profile`, `trade_journal`, `embeddings_metadata`, `session_state`,
`watchlist_alerts`, `news_cache`, `reports` — all PAY_PER_REQUEST

## Session TTLs (defined in tools/dynamo.py)
- `ONBOARDING_SESSION_TTL_SECONDS = 1800`
- `PANIC_COOLDOWN_SESSION_TTL_SECONDS = 300`

## Infrastructure
CDK stack at `infrastructure/cdk/kensho_stack.py` is the single source of truth.
No manual console changes permitted.
