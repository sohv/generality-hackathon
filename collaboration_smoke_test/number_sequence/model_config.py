"""The explicitly requested model and conservative, tier-aware cost ceilings."""
from inspect_ai.model import GenerateConfig, ModelCost
from run_smoke import api

MODEL_ID = 'openai/gpt-5.6-luna'
MODEL = 'openrouter/' + MODEL_ID
MAX_OUTPUT_TOKENS = 128000
# Include long-context and cache-write rates in reservations and Inspect stops.
# Logged token costs therefore conservatively overestimate ordinary short calls.
COST = ModelCost(input=.4, output=1.8, input_cache_write=.5, input_cache_read=.04)


def pricing_snapshot():
    price = next(m for m in api('models')['data'] if m['id'] == MODEL_ID)
    return price


def max_call_cost(price):
    return (price['context_length']*max(COST.input,COST.input_cache_write)
            + MAX_OUTPUT_TOKENS*COST.output)/1e6


def generation_config(connections):
    # 128000 is Luna's native output ceiling; no smaller experiment output cap.
    return GenerateConfig(max_tokens=MAX_OUTPUT_TOKENS, max_connections=connections,
                          adaptive_connections=False, reasoning_effort='low')
