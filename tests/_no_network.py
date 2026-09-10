# refuses every socket connection while the suite runs, so a test that reached the network would fail
from __future__ import annotations

import socket

import pytest


def _refuse(*args, **kwargs):
    raise RuntimeError("the suite runs without the network")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
