import clustercheck


class MyCheck(clustercheck.Plugin):
    def check(self, host, args):
        return True, "my check"