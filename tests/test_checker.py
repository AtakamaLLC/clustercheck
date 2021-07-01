import os
import socket

import pytest

import clustercheck


@pytest.fixture
def generic_config():
    # to disable ssl checks:
    # http args: {"verify": False}
    # wss args: {"sslopt": {"cert_reqs": ssl.CERT_NONE}}
    yield clustercheck.Config(
        checks=[
            {
                "url": "https://www.google.com/search?q=atakama",
                "expect": {"status": 200, "contains": "atakama.com"},
            },
            {
                "url": "wss://dev-relay.vidaprivacy.io/",
            },
            {
                "url": "http://0.0.0.0/",
            },
        ]
    )


@pytest.fixture
def plugin_config():
    yield clustercheck.Config(
        plugins=[
            {"lib": os.path.join(os.path.dirname(__file__), "example_plugin.py"), "name": "MyCheck"}
        ],
        checks=[
            {
                "url": "wss://dev-relay.vidaprivacy.io/",
                "plugin": "MyCheck",
            },
        ]
    )


@pytest.fixture
def dnsmap_config():
    yield clustercheck.Config(dns_map={"www.microsoft.com": "www.google.com"})


def test_dns_inject(dnsmap_config):
    cfg = dnsmap_config
    checker = clustercheck.Checker(cfg)
    checker.setup_dns()
    ipaddr1 = socket.gethostbyname("www.microsoft.com")
    ipaddr2 = socket.gethostbyname("www.google.com")
    assert ipaddr1 == ipaddr2


def test_urls(generic_config):
    cfg = generic_config
    checker = clustercheck.Checker(cfg)
    checker.check_all()
    assert len(checker.reports) == len(cfg.checks)
    assert checker.reports[0].ok
    assert checker.reports[1].ok
    assert not checker.reports[2].ok


def test_plugins(plugin_config):
    cfg = plugin_config
    checker = clustercheck.Checker(cfg)
    checker.load_plugins()
    checker.check_all()
    assert len(checker.reports) == len(cfg.checks)
    assert checker.reports[0].ok
