import json
import logging

from denvr.client import client

logging.basicConfig(level=logging.DEBUG)
virtual = client('servers/virtual')

print("Shutting down server...")

print(
    virtual.stop_server(
        id="${id}",
        namespace="${namespace}",
        cluster="${cluster}",
    )
)
