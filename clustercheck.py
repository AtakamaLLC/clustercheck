import abc
import argparse
import logging
import re
import time
from typing import Dict, List, Type

from urllib.parse import urlparse

import requests as requests
import yaml
import socket
import websocket

log = logging.getLogger("clustercheck")


class Plugin(abc.ABC):
    _plugins_ = {}

    @abc.abstractmethod
    def check(self, url, args):
        pass

    @classmethod
    def name(cls):
        return cls.__name__

    def __init_subclass__(cls: "Type[Plugin]"):
        Plugin._plugins_[cls.name()] = cls()

class Report:
    def __init__(self, ok: bool, msg: str, check: "CheckConfig"):
        self.ok = ok
        self.msg = msg
        self.check = check
        self.time = time.time()


class CheckConfig:
    def __init__(self, url, args, plugin=None, expect_status=200, expect_contains=None):
        self.url = url
        self.args = args
        self.plugin = plugin
        self.expect_status = expect_status
        self.expect_contains = expect_contains

    @staticmethod
    def from_dict(dct):
        args = dct.get("args", {})
        return CheckConfig(
            url=dct["url"],
            args=args,
            plugin=dct.get("plugin"),
            expect_status=dct.get("expect", {}).get("status", 200),
            expect_contains=dct.get("expect", {}).get("contains", None),
        )


class PluginConfig:
    def __init__(self, lib, name, args):
        self.lib = lib
        self.name = name
        self.args = args

    @staticmethod
    def from_dict(dct):
        return PluginConfig(
            lib=dct["lib"],
            name=dct["name"],
            args=dct.get("args", {}),
        )


class Config:
    def __init__(self, dns_map=None, plugins=None, checks=None):
        self.dns_map: Dict[str, str] = dns_map or {}
        self.checks: List[CheckConfig] = [
            CheckConfig.from_dict(ent) for ent in (checks or [])
        ]
        self.plugins: List[PluginConfig] = [
            PluginConfig.from_dict(ent) for ent in (plugins or [])
        ]

    @classmethod
    def from_file(cls, path):
        with open(path, "r") as f:
            cfg = yaml.safe_load(f)
        return cls.from_dict(cfg)

    @classmethod
    def from_dict(cls, dct):
        return cls(
            dns_map=dct.get("dns_map", {}),
            plugins=dct.get("plugins", []),
            checks=dct.get("checks", []),
        )


class Checker:
    def __init__(self, config):
        self.reports: List[Report] = []
        self.config = config
        self.results = []
        self.plugins = {}

    def check(self):
        self.setup_dns()
        self.load_plugins()
        self.check_all()
        return self.results

    def setup_dns(self):
        dns_map = {}
        for src, dest in self.config.dns_map.items():
            dns_map[src.lower().rstrip(".")] = dest

        def make_new_func(prv_func):
            def new_func(*args):
                map = dns_map.get(args[0].rstrip("."))
                if map:
                    return prv_func(*((map,) + args[1:]))
                else:
                    return prv_func(*args)

            return new_func

        socket.getaddrinfo = make_new_func(socket.getaddrinfo)
        socket.gethostbyname = make_new_func(socket.gethostbyname)
        socket.gethostbyname_ex = make_new_func(socket.gethostbyname_ex)

    def check_all(self):
        g: CheckConfig
        for g in self.config.checks:
            uri = urlparse(g.url)
            if g.plugin:
                p: Plugin = self.plugins[g.plugin]
                self.report(p.check(g.url, g.args), p.name, g)
            elif uri.scheme in ("http", "https"):
                if not g.args.get("method"):
                    g.args["method"] = "GET"
                try:
                    resp = requests.request(url=g.url, **g.args)
                    ok = resp.status_code == g.expect_status
                    if ok and g.expect_contains:
                        self.report(
                            re.search(g.expect_contains, resp.text),
                            "http(s) text contains",
                            g,
                        )
                    else:
                        self.report(ok, "http(s) status", g)
                except Exception as ex:
                    self.report(False, repr(ex), g)
            elif uri.scheme in ("ws", "wss"):
                ws = websocket.create_connection(g.url, **g.args)
                ws.ping()
                self.report(ws.connected, "websocket connected", g)
            else:
                self.report(False, "invalid scheme", g)

    def report(self, ok, msg, check):
        self.reports += [Report(bool(ok), msg, check)]

    def load_plugins(self):
        p: PluginConfig
        for p in self.config.plugins:
            self.load_plugin(p)
        self.plugins = Plugin._plugins_

    @staticmethod
    def load_plugin(p: PluginConfig):
        import importlib.util

        try:
            # import name
            importlib.import_module(p.lib)
        except ImportError:
            # or path to a file
            spec = importlib.util.spec_from_file_location("module.name", p.lib)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", help="set debug log level")
    parser.add_argument("--config", help="read config yml", default="checker.yml")
    return parser.parse_args()


def main():
    logging.basicConfig()
    args = parse_args()
    if args.debug:
        log.setLevel(logging.DEBUG)
    config = Config.from_file(args.config)
    checker = Checker(config)
    results = checker.check()
    print(results.format())


if __name__ == "__main__":
    main()
