#!/usr/bin/env python

# Copyright 2016 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Need to figure out why this only fails on travis
# pylint: disable=bad-continuation

"""Runs verify/test-go checks for kubernetes/kubernetes."""

import argparse
import os
import re
import subprocess
import sys


BRANCH_VERSION = {
    '1.2': '1.4',
    '1.3': '1.4',
    'master': '1.9',
}

VERSION_TAG = {
    '1.4': '1.4-v20161130-8958f82',
    '1.5': '1.5-v20161205-d664d14',
    '1.6': '1.6-v20161205-ad918bc',
    '1.7': '1.7-v20170713-c28e0556',
    '1.8': '1.8-v20170906-3a1c5ae5',
    '1.9': '1.9-v20171018-6ddbad97',
}


def check_output(*cmd):
    """Log and run the command, return output, raising on errors."""
    print >>sys.stderr, 'Run:', cmd
    return subprocess.check_output(cmd)


def check(*cmd):
    """Log and run the command, raising on errors."""
    print >>sys.stderr, 'Run:', cmd
    subprocess.check_call(cmd)


def retry(func, times=5):
    """call func until it returns true at most times times"""
    success = False
    for _ in range(0, times):
        success = func()
        if success:
            return success
    return success


def try_call(cmds):
    """returns true if check(cmd) does not throw an exception
    over all cmds where cmds = [[cmd, arg, arg2], [cmd2, arg]]"""
    try:
        for cmd in cmds:
            check(*cmd)
        return True
    # pylint: disable=bare-except
    except:
        return False


def main(branch, script, force, on_prow):
    """Test branch using script, optionally forcing verify checks."""
    # If branch has 3-part version, only take first 2 parts.
    verify_branch = re.match(r'master|release-(\d+\.\d+)', branch)
    if not verify_branch:
        raise ValueError(branch)
    # Extract version if any.
    ver = verify_branch.group(1) or verify_branch.group(0)
    tag = VERSION_TAG[BRANCH_VERSION.get(ver, ver)]
    force = 'y' if force else 'n'
    artifacts = '%s/_artifacts' % os.environ['WORKSPACE']
    k8s = os.getcwd()
    if not os.path.basename(k8s) == 'kubernetes':
        raise ValueError(k8s)

    check('rm', '-rf', '.gsutil')
    remote = 'bootstrap-upstream'
    uri = 'https://github.com/kubernetes/kubernetes.git'

    current_remotes = check_output('git', 'remote')
    if re.search('^%s$' % remote, current_remotes, flags=re.MULTILINE):
        check('git', 'remote', 'remove', remote)
    check('git', 'remote', 'add', remote, uri)
    check('git', 'remote', 'set-url', '--push', remote, 'no_push')
    # If .git is cached between runs this data may be stale
    check('git', 'fetch', remote)

    if not os.path.isdir(artifacts):
        os.makedirs(artifacts)

    if not on_prow:
        check(
            'docker', 'run', '--rm=true', '--privileged=true',
            '-v', '/var/run/docker.sock:/var/run/docker.sock',
            '-v', '/etc/localtime:/etc/localtime:ro',
            '-v', '%s:/go/src/k8s.io/kubernetes' % k8s,
            '-v', '%s:/workspace/artifacts' % artifacts,
            '-e', 'KUBE_FORCE_VERIFY_CHECKS=%s' % force,
            '-e', 'KUBE_VERIFY_GIT_BRANCH=%s' % branch,
            '-e', 'REPO_DIR=%s' % k8s,  # hack/lib/swagger.sh depends on this
            'gcr.io/k8s-testimages/kubekins-test:%s' % tag,
            'bash', '-c', 'cd kubernetes && %s' % script,
        )
    else:
        # make sure we are cd-ed to the repo
        k8s = '/go/src/k8s.io/kubernetes'
        os.chdir(k8s)

        # setup env
        os.environ['REPO_DIR'] = k8s # hack/lib/swagger.sh depends on this
        os.environ['KUBE_FORCE_VERIFY_CHECKS'] = str(force)
        os.environ['KUBE_VERIFY_GIT_BRANCH'] = str(branch)

        # TODO(bentheelder): mimic the other script too, and eventually
        # migrate this flag to be a bool between the two possible scripts instead.
        if script == './hack/jenkins/verify-dockerized.sh':
            # mimic k8s.io/kubernetes/hack/jenkins/verify-dockerized.sh
            # but patched slightly to work appropriately on prow
            path_prefix = os.environ['GOPATH'] + '/bin'
            path_prefix += ':' + k8s + '/third_party/etcd:/usr/local/go/bin'
            os.environ['PATH'] = path_prefix + ':' + os.environ['PATH']
            os.environ['ARTIFACTS_DIR'] = os.environ['WORKSPACE'] + '/artifacts'
            os.environ['LOG_LEVEL'] = '4'

            # setup requirements before make verify
            retry(lambda: try_call([
                ['go', 'get', 'github.com/tools/godep'],
                ['godep', 'version']
            ]))
            retry(lambda: try_call([
                ['bash', '-c', './hack/install-etcd.sh']
            ]))
            retry(lambda: try_call([
                ['bash', '-c', './hack/godep-restore.sh']
            ]), times=2)

            # and now `make verify`
            check('bash', '-c', 'make verify')



if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(
        'Runs verification checks on the kubernetes repo')
    PARSER.add_argument(
        '--branch', default='master', help='Upstream target repo')
    PARSER.add_argument(
        '--force', action='store_true', help='Force all verify checks')
    PARSER.add_argument(
        '--script',
        default='./hack/jenkins/test-dockerized.sh',
        help='Script in kubernetes/kubernetes that runs checks')
    PARSER.add_argument(
        '--prow', action='store_true', help='Force Prow mode'
    )
    ARGS = PARSER.parse_args()
    main(ARGS.branch, ARGS.script, ARGS.force, ARGS.prow)
