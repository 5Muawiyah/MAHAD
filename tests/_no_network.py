# refuses every socket connection for the whole run, so a test that reached the network would fail
from __future__ import annotations

import socket


def _refuse(*args, **kwargs):
    raise RuntimeError("the suite runs without the network")


def pytest_sessionstart(session):
    socket.socket.connect = _refuse
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
