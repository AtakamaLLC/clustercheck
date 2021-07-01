import abc
import argparse
import logging
import re
import sys
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

    def format(self, fmt):
        pass_fail = "PASS" if self.ok else "FAIL"
        return fmt.format(
            ok=pass_fail, message=self.msg, config=self.check, time=self.time
        )


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
    DEFAULT_FORMAT = "{ok} [{time}] {message} {config.url}"

    def __init__(self, dns_map=None, plugins=None, checks=None):
        self.output_format = self.DEFAULT_FORMAT
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
    def __init__(self, config: Config):
        self.reports: List[Report] = []
        self.config = config
        self.results = []
        self.plugins = {}

    def reset(self):
        self.results = []

    def check(self):
        self.setup_dns(self.config.dns_map)
        self.load_plugins(self.config.plugins)
        self.check_all(self.config.checks)
        return self.results

    def ok(self):
        return all(r.ok for r in self.reports)

    @staticmethod
    def setup_dns(dns_map: Dict[str, str]):
        dns_map = dns_map.copy()

        for src, dest in dns_map.items():
            dns_map[src.lower().rstrip(".")] = dest

        def make_new_func(prv_func):
            def new_func(*args):
                map = dns_map.get(args[0].lower().rstrip("."))
                if map:
                    return prv_func(*((map,) + args[1:]))
                else:
                    return prv_func(*args)

            return new_func

        socket.getaddrinfo = make_new_func(socket.getaddrinfo)
        socket.gethostbyname = make_new_func(socket.gethostbyname)
        socket.gethostbyname_ex = make_new_func(socket.gethostbyname_ex)

    def check_all(self, checks: List[CheckConfig]):
        g: CheckConfig
        for g in checks:
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

    def report(self, ok: bool, msg: str, check: CheckConfig):
        self.reports += [Report(bool(ok), msg, check)]

    def print_reports(self, fmt, file, verbose):
        for r in self.reports:
            if not verbose and r.ok:
                continue
            file.write(r.format(fmt))
            file.write("\n")

    def load_plugins(self, plugins):
        p: PluginConfig
        log.debug("loading %s plugins", len(plugins))
        for p in plugins:
            self.load_plugin(p)
        # noinspection PyProtectedMember
        self.plugins = Plugin._plugins_

    @staticmethod
    def load_plugin(p: PluginConfig):
        import importlib.util

        try:
            # import name
            importlib.import_module(p.lib)
            log.debug("loaded as module: %s", p.lib)
        except ImportError:
            # or path to a file
            spec = importlib.util.spec_from_file_location("module.name", p.lib)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            log.debug("loaded as file: %s", p.lib)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", help="set verbose", action="store_true")
    parser.add_argument("--debug", help="set debug mode", action="store_true")
    parser.add_argument("--config", "-c", help="read config yml", default="checker.yml")
    return parser.parse_args()


def main():
    logging.basicConfig()
    args = parse_args()
    if args.debug:
        log.setLevel(logging.DEBUG)
    config = Config.from_file(args.config)
    checker = Checker(config)
    checker.check()
    checker.print_reports(config.output_format, sys.stderr, verbose=args.verbose)
    sys.exit(checker.ok())


if __name__ == "__main__":
    main()
