"""Portable CI and trusted-machine workflows for NBA Stats Explorer."""

try:
    from .main import NbaDbCi as NbaDbCi
except ModuleNotFoundError as exc:
    # Host-side change classification imports ``impact`` without installing the
    # generated Dagger SDK. The Dagger runtime always takes the normal branch.
    if exc.name != "dagger":
        raise
