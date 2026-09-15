"""Small, shell-free Homebrew command boundaries and report validation."""
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import re
import subprocess


def run_read(args, timeout=120):
    """Capture streams separately: Homebrew can warn beside valid JSON."""
    from .backend import _brew_cmd
    return subprocess.run(
        _brew_cmd(list(args)), capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=timeout,
        env={**os.environ, 'HOMEBREW_NO_COLOR': '1', 'LC_ALL': 'C',
             'HOMEBREW_NO_AUTO_UPDATE': '1'},
    )


def transcript(result):
    return '\n'.join(part.strip() for part in (result.stdout, result.stderr) if part)


def package_args(operation, package, qualified=None):
    name = qualified or package.full_name or package.name
    validate_name(name)
    return (operation, '--cask' if package.pkg_type == 'cask' else '--formula', name)


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(
        r'[A-Za-z0-9][A-Za-z0-9@+_.-]*(?:/[A-Za-z0-9][A-Za-z0-9@+_.-]*)*', name
    ):
        raise ValueError('Invalid Homebrew package name')
    return name


def version_install_args(formula, version):
    validate_name(formula)
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+_-]*', version):
        raise ValueError('Enter a version that starts with a number, such as 14.1.0')
    if '@' in formula and formula.rsplit('@', 1)[1] != version:
        raise ValueError('The formula suffix and requested version must match')
    return ('version-install', formula, version)


def parse_services(result):
    if result.returncode:
        raise ValueError(transcript(result) or 'Could not list user services')
    data = _json_response(result)
    if not isinstance(data, list):
        raise ValueError('Unexpected Homebrew services response')
    for service in data:
        if not isinstance(service, dict) or not isinstance(service.get('status'), str):
            raise ValueError('Invalid Homebrew service record')
        validate_name(service.get('name'))
    return data


def parse_vulns(result):
    # Status 1 means findings OR incomplete coverage, not necessarily a crash.
    if result.returncode not in (0, 1):
        raise ValueError(transcript(result) or 'Security scan failed')
    data = _json_response(result)
    if not isinstance(data, dict) or not isinstance(data.get('findings'), list):
        raise ValueError('Unexpected Homebrew vulnerability response')
    if not isinstance(data.get('skipped_formulae'), list) or not all(
        isinstance(name, str) for name in data['skipped_formulae']
    ):
        raise ValueError('Invalid skipped-package list')
    for finding in data['findings']:
        if not isinstance(finding, dict):
            raise ValueError('Invalid vulnerability finding')
        for key in ('formula', 'version'):
            if not isinstance(finding.get(key), str):
                raise ValueError('Invalid vulnerability package identity')
        for key in ('vulnerabilities', 'patched'):
            if not isinstance(finding.get(key), list):
                raise ValueError('Invalid vulnerability list')
            for vuln in finding[key]:
                if not isinstance(vuln, dict) or not isinstance(vuln.get('id'), str):
                    raise ValueError('Invalid vulnerability record')
                if not isinstance(vuln.get('fixed_versions'), list) or not all(
                    isinstance(version, str) for version in vuln['fixed_versions']
                ):
                    raise ValueError('Invalid fixed-version list')
    return data


def _json_response(result):
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise ValueError('Homebrew did not return a JSON report.\n' + transcript(result)) from error
