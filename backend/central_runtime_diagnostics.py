"""Allowlisted presence-only startup diagnostics. Never return environment values."""
import json

KEYS = ('DATABASE_URL', 'ZERO_OWNER_PASSWORD', 'ZERO_OWNER_PASSWORD_HASH',
        'ZERO_CENTRAL_ORIGIN', 'PORT', 'RAILWAY_SERVICE_ID', 'RAILWAY_ENVIRONMENT_ID')

def runtime_summary(env):
    states = {}
    for key in KEYS:
        value = env.get(key)
        if value is None:
            state = 'absent'
        elif not value.strip():
            state = 'empty'
        elif '${{' in value:
            state = 'unresolved_reference'
        else:
            state = 'present'
        states[key] = state
    return 'ZERO_RUNTIME_CONFIG ' + json.dumps(states, sort_keys=True)
