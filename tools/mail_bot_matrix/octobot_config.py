"""Paper-only OctoBot daily profile settings; not proof of a live feed."""
import copy


def set_fifteen_minute_strategy(strategy):
    strategy = copy.deepcopy(strategy)
    if 'required_time_frames' not in strategy:
        raise ValueError('Expected SimpleStrategyEvaluator time frame configuration')
    strategy['required_time_frames'] = ['15m']
    return strategy
