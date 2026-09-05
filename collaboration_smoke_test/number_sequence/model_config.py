"""The explicitly requested model and conservative, tier-aware cost ceilings."""
import os

from inspect_ai.model import GenerateConfig, ModelCost
from run_smoke import api

# Luna stays the default. NUMBER_SEQUENCE_MODEL=glm selects the GLM 5.3 Flash
# condition the other experiments in this repository use, leaving every other
# setting identical so the two conditions differ only by the model.
# Include long-context and cache-write rates in reservations and Inspect stops.
# Logged token costs therefore conservatively overestimate ordinary short calls.
# GLM's rates match local_sweep/run.py and its published OpenRouter pricing.
MODELS = {
    'luna': ('openai/gpt-5.6-luna', 128000,
             ModelCost(input=.4, output=1.8, input_cache_write=.5, input_cache_read=.04)),
    'glm': ('z-ai/glm-5.3-flash', 8192,
            ModelCost(input=.075, output=.25, input_cache_write=.075, input_cache_read=.015)),
}
CHOICE = os.environ.get('NUMBER_SEQUENCE_MODEL', 'luna')
if CHOICE not in MODELS:
    raise ValueError(f"NUMBER_SEQUENCE_MODEL must be one of {sorted(MODELS)}")
MODEL_ID, MAX_OUTPUT_TOKENS, COST = MODELS[CHOICE]
MODEL = 'openrouter/' + MODEL_ID


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
