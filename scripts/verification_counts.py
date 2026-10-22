"""Count only complete successful test executions, never skipped or expected failures."""
import re


def python_passed(output):
    counts=re.findall(r'Ran (\d+) tests? in[^\n]*\n\s*\nOK\s*$',output)
    if len(counts)!=1 or int(counts[0])<1:raise ValueError('Python suite did not pass every case')
    return int(counts[0])


def client_passed(output):
    output=re.sub(r'\x1b\[[0-9;]*m','',output)
    result={}
    for field in ('tests','pass','fail','cancelled','skipped','todo'):
        values=re.findall(r'(?:ℹ|#)\s+'+field+r'\s+(\d+)',output)
        if len(values)!=1:raise ValueError('Client test summary is incomplete')
        result[field]=int(values[0])
    if result['tests']<1 or result['pass']!=result['tests'] or any(result[field] for field in ('fail','cancelled','skipped','todo')):
        raise ValueError('Client suite did not pass every case')
    return result['tests']
