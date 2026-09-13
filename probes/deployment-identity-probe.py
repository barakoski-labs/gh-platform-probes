#!/usr/bin/env python3
"""Observe deployment identity through direct REST; retain every response body."""

import argparse
import json
import os
from pathlib import Path
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
    parser.add_argument('--token-env', required=True)
    parser.add_argument('--reader-token-env')
    parser.add_argument('--environment', choices=['probe-env-a', 'probe-env-b'], default='probe-env-a')
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--steps', default='1,2,3,4a,5,6')
    args = parser.parse_args()
    steps = set(args.steps.split(','))
    if not steps or not steps <= {'1', '2', '3', '4a', '5', '6'}:
        parser.error('--steps must contain comma-separated values from 1,2,3,4a,5,6')
    parts = args.repo.split('/')
    if len(parts) != 2 or not all(parts) or any(p in {'.', '..'} for p in parts):
        parser.error('--repo must be OWNER/NAME')
    token = os.environ.get(args.token_env)
    reader = os.environ.get(args.reader_token_env) if args.reader_token_env else None
    if not token or (args.reader_token_env and not reader):
        parser.error('A named token environment variable is empty or missing')
    if reader == token:
        parser.error('The reader token must be distinct from the primary token')
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error('--out-dir must be empty to avoid overwriting observations')
    base = 'https://api.github.com/repos/' + '/'.join(urllib.parse.quote(p, safe='') for p in parts)
    opener = urllib.request.build_opener(NoRedirect)
    secrets = [token, reader]

    def call(name, method, suffix='', payload=None, auth=token):
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'deployment-identity-probe'}
        if auth:
            headers['Authorization'] = 'Bearer ' + auth
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(base + suffix, data=data, headers=headers, method=method)
        try:
            response = opener.open(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError:
            raise RuntimeError(name + ': transport failure; no HTTP response received') from None
        with response:
            status = response.code
            body = write_response(out / (name + '.json'), status, response.read(), secrets)
        return status, body

    def require(result, name):
        status, body = result
        if not 200 <= status < 300 or not isinstance(body, dict):
            raise RuntimeError(name + ': unusable response; see saved JSON')
        return body

    metadata = require(call('setup-repository', 'GET'), 'Repository lookup')
    branch = metadata.get('default_branch')
    if not isinstance(branch, str) or not branch:
        raise RuntimeError('Repository response has no default_branch')
    commit = require(call('setup-commit', 'GET', '/commits/' + urllib.parse.quote(branch, safe='')), 'Commit lookup')
    sha = commit.get('sha')
    if not isinstance(sha, str) or not sha:
        raise RuntimeError('Commit response has no sha')
    created = []

    def create(name):
        body = require(call(name, 'POST', '/deployments', {
            'ref': sha, 'environment': args.environment, 'auto_merge': False,
            'required_contexts': [], 'description': 'deployment-identity-probe',
        }), name)
        if type(body.get('id')) is not int:
            raise RuntimeError(name + ': deployment id missing or not an integer')
        created.append(body)
        return body

    a = None
    if '1' in steps:
        a = create('step-1-create')
    if '2' in steps:
        first = create('step-2-create-a')
        second = create('step-2-create-b')
        if first['id'] == second['id']:
            raise RuntimeError('BLOCKING: step 2 returned identical deployment ids')
        a = a or first
    if steps & {'3', '5'} and a is None:
        a = create('setup-create-a')
    if '3' in steps:
        suffix = '/deployments/' + str(a['id'])
        require(call('step-3-in-progress', 'POST', suffix + '/statuses', {'state': 'in_progress'}), 'Status update')
        require(call('step-3-success', 'POST', suffix + '/statuses', {'state': 'success'}), 'Status update')
        call('step-3-read-a-before', 'GET', suffix)
        create('step-3-create-b')
        call('step-3-read-a-after', 'GET', suffix)
    if '5' in steps:
        suffix = '/deployments/' + str(a['id'])
        call('step-5-unauthenticated', 'GET', suffix, auth=None)
        if reader:
            call('step-5-reader', 'GET', suffix, auth=reader)
        else:
            (out / 'step-5-reader-not-run.json').write_text(json.dumps({
                'status': 'not run', 'reason': '--reader-token-env was not supplied'
            }) + '\n', encoding='utf-8')
    if '6' in steps:
        temporary = create('step-6-create-throwaway')
        suffix = '/deployments/' + str(temporary['id'])
        status, _ = call('step-6-delete-first', 'DELETE', suffix)
        if not 200 <= status < 300:
            call('step-6-inactive', 'POST', suffix + '/statuses', {'state': 'inactive'})
            call('step-6-delete-after-inactive', 'DELETE', suffix)
    if '4a' in steps:
        if not created:
            create('step-4a-create')
        for body in created:
            creator = body.get('creator')
            if (not isinstance(creator, dict) or not {'login', 'type'} <= creator.keys()
                    or 'performed_via_github_app' not in body):
                raise RuntimeError('Step 4a: expected creator fields missing; inspect saved creation responses')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        print('deployment-identity-probe: ' + str(error), file=sys.stderr)
        sys.exit(1)
