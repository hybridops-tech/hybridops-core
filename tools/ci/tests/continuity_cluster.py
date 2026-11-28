"""Access to the disposable API server in check-continuity-api.sh."""

import json
import os
import subprocess
from http.client import HTTPConnection

from hyops.controller.client import ContractClient


def client():
    port = int(os.environ["HYOPS_TEST_PROXY_PORT"])
    return ContractClient(lambda: HTTPConnection("127.0.0.1", port, timeout=10))


def kubectl(namespace, *args, obj=None):
    return subprocess.run(
        ["kubectl", f"--namespace={namespace}", "--request-timeout=10s", *args],
        input=json.dumps(obj) if obj is not None else None,
        stdout=subprocess.PIPE,
        check=True,
        text=True,
        timeout=15,
    ).stdout
