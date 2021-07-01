# clustercheck

Check a cluster before it goes live.

## Usage:

```
clustercheck -c my.config
```


Example of config:

```
dns_map:
    www.blah.com: kube.aws.longthing.com
    www.bar.com: 12.34.56.7

plugins:
    - lib: myplugin.py
      name: MyCheck

checks:
    - url: "wss://dev-site.example.io"
      plugin: MyCheck
    - url: "wss://prod-site.example.io"
      plugin: MyCheck
    - url: "https://prod-site.example.io"
      expect: 
        contains: some-string
      args:
        verify: False
```

This will run 3 checks, 2 of them will re-use the same plugin (MyCheck), and the 3rd, will just hit the url with requests() lib.


Example of plugin:

```
class MyCheck(clustercheck.Plugin):
    def check(self, url, args):
        return True

```

Args are "anything in the args yml".   They are not checked, so plugins must verify these values.


# Check Execution
    - dns map is applied first, it monkey-patches the socket library
    - dns map is not inherited by subprocesses, it is python in-process only
    - each check is executed in order
    - if a plugin is not specified, the url must be valid
    - plugsin can be named as "module.name" or as "/path/to/file.py"
     

# Generic checks
    - urls are checked for status 200, unless expect: status: is changes.
    - websockets are only checked for a ping
    - args, if any, are passed to the `requests.request()` or `websocket.create_connection()` calls directly
    - default "method" for requests is "GET"

# Output format
    - output is recorded internally as (PASS/FAIL, time, message, check_config)
    - default output format is: "{ok} [{time}] {message} {config.url}"
    - passing results are not output unless --verbose is set
