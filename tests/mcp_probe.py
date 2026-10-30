#!/usr/bin/env python3
"""Local MCP fixture; its secret proves a model really called the tool."""
import json
import os
from pathlib import Path
import sys

for line in sys.stdin:
    req = json.loads(line)
    if 'id' not in req:
        continue
    method = req.get('method')
    if method == 'initialize':
        result = {'protocolVersion': req.get('params', {}).get('protocolVersion', '2024-11-05'),
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'local-proof', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'get_proof', 'description': 'Return the secret proof token. Call this tool to learn it.',
                             'inputSchema': {'type': 'object', 'properties': {}}}]}
    elif method == 'tools/call' and req.get('params', {}).get('name') == 'get_proof':
        if os.environ.get('PROOF_LOG'):
            with open(os.environ['PROOF_LOG'], 'a') as out:
                out.write('called\n')
        result = {'content': [{'type': 'text', 'text': os.environ.get('PROOF_TOKEN', 'fixture-proof')}]}
    elif method == 'ping':
        result = {}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32601, 'message': 'Unsupported method'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result}), flush=True)
