import json
from denvr.client import client
virtual = client('servers/virtual')

print("Shutting down server...")

print(
    virtual.stop_server(
        id="${id}",
        namespace="${namespace}",
        cluster="${cluster}",
    )
)
