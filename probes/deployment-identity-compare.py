#!/usr/bin/env python3
"""Compare direct REST, gh api REST, and a selected GraphQL deployment node."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def write_response(path, status, raw, secrets):
    text = raw.decode('utf-8')
    if any(secret and secret in text for secret in secrets):
        raise RuntimeError('Response contains a credential; refusing to persist it')
    try:
        body = json.loads(text)
        encoded = text
    except ValueError:
        body = text
        encoded = json.dumps(text)
    def contains_secret(value):
        if isinstance(value, str):
            return any(secret and secret in value for secret in secrets)
        if isinstance(value, dict):
            return any(contains_secret(key) or contains_secret(child) for key, child in value.items())
        if isinstance(value, list):
            return any(contains_secret(child) for child in value)
        return False

    if contains_secret(body):
        raise RuntimeError('Response contains a credential; refusing to persist it')
    with path.open('x', encoding='utf-8') as stream:
        stream.write('{"http_status": ' + str(status) + ', "response_body": ' + encoded + '}\n')
    return body


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--deployment-id', required=True, type=int)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()
    parts = args.repo.split('/')
    if len(parts) != 2 or not all(parts) or any(p in {'.', '..'} for p in parts):
        parser.error('--repo must be OWNER/NAME')
    if args.deployment_id <= 0:
        parser.error('--deployment-id must be positive')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        parser.error('Set GH_TOKEN or GITHUB_TOKEN for both REST and gh api')
    secrets = [os.environ.get('GH_TOKEN'), os.environ.get('GITHUB_TOKEN')]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error('--out-dir must be empty')
    endpoint = 'repos/' + '/'.join(urllib.parse.quote(p, safe='') for p in parts) + '/deployments/' + str(args.deployment_id)
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'Authorization': 'Bearer ' + token, 'User-Agent': 'deployment-identity-compare'}
    request = urllib.request.Request('https://api.github.com/' + endpoint, headers=headers)
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    except urllib.error.HTTPError as error:
        response = error
    except urllib.error.URLError:
        raise RuntimeError('Direct REST transport failure; no HTTP response received') from None
    with response:
        rest = write_response(out / 'rest.json', response.code, response.read(), secrets)
    environment = os.environ.copy()
    environment.update({'GH_TOKEN': token, 'GH_HOST': 'github.com', 'GH_PROMPT_DISABLED': '1',
                        'GH_DEBUG': '', 'NO_COLOR': '1'})

    def cli(name, arguments):
        try:
            result = subprocess.run(['gh', 'api', '--hostname', 'github.com', '--include',
                                     '-H', 'Accept: application/vnd.github+json',
                                     '-H', 'X-GitHub-Api-Version: 2022-11-28'] + arguments,
                                    capture_output=True, env=environment, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(name + ': gh unavailable or timed out; no complete HTTP response') from None
        # --include supplies HTTP metadata; remove only its header block.
        match = re.match(rb'HTTP/[^\s]+\s+(\d{3})[^\r\n]*\r?\n', result.stdout)
        separator = re.search(rb'\r?\n\r?\n', result.stdout)
        if not match or not separator:
            raise RuntimeError(name + ': gh supplied no HTTP response; stderr is not a payload')
        return write_response(out / (name + '.json'), int(match.group(1)),
                              result.stdout[separator.end():], secrets)

    gh_rest = cli('gh-rest', [endpoint])
    node_id = rest.get('node_id') if isinstance(rest, dict) else None
    if not isinstance(node_id, str) or not node_id:
        raise RuntimeError('REST response lacks node_id; cannot perform same-object GraphQL lookup')
    query = '''query($id: ID!) {
      node(id: $id) {
        __typename
        id
        ... on Deployment {
          databaseId
          environment
          createdAt
          updatedAt
          description
          state
          creator { __typename login }
          commit { oid }
          payload
        }
      }
    }'''
    graphql = cli('graphql', ['graphql', '-f', 'query=' + query, '-f', 'id=' + node_id])

    def fields(value, prefix=''):
        found = set()
        if isinstance(value, dict):
            for key, child in value.items():
                path = prefix + '/' + key.replace('~', '~0').replace('/', '~1')
                found.add(path)
                found.update(fields(child, path))
        elif isinstance(value, list):
            for child in value:
                found.update(fields(child, prefix + '/*'))
        return found

    data = graphql.get('data') if isinstance(graphql, dict) else None
    node = data.get('node') if isinstance(data, dict) else None
    objects = {'rest': rest, 'gh-rest': gh_rest, 'graphql': node}
    observed = {name: fields(value) for name, value in objects.items()}
    union = set().union(*observed.values())
    diff = {'note': 'Literal field paths; GraphQL is limited to the selected node fields. '
                    'Absent fields do not establish schema unavailability. Null values count as present.',
            'graphql_query': query,
            'object_available': {name: isinstance(value, dict) for name, value in objects.items()},
            'fields': [{'path': path,
                        'present_in': [name for name, paths in observed.items() if path in paths],
                        'absent_in': [name for name, paths in observed.items() if path not in paths]}
                       for path in sorted(union) if not all(path in paths for paths in observed.values())]}
    (out / 'field-diff.json').write_text(json.dumps(diff, indent=2) + '\n', encoding='utf-8')
    if node is None or (isinstance(graphql, dict) and graphql.get('errors')):
        raise RuntimeError('GraphQL did not return a complete node; inspect graphql.json and field-diff.json')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        print('deployment-identity-compare: ' + str(error), file=sys.stderr)
        sys.exit(1)

