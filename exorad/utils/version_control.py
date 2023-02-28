import base64
import socket

import requests

from exorad import __url__
from exorad.__version__ import __version__ as current_ver
from exorad.log import Logger


class VersionError(Exception):
    pass


class VersionControl(Logger):
    def __init__(
        self, package_url=__url__, current_version=current_ver, force=False
    ):
        super().__init__()

        self.current_version = current_version
        if self._check_internet():
            self.content = self.get_content(package_url)
            if self.content:
                message, new_ver = self.get_message()

                if message != "":
                    self.warning("### NEW CODE VERSION ONLINE ###")
                    self.warning(
                        "your version: {}  - online version:{}".format(
                            self.current_version, new_ver
                        )
                    )
                    self.warning("changelog: \n {}".format(message))
                    if force:
                        raise VersionError(
                            "please update your code version. Your version: {} - online version:{}".format(
                                self.current_version, new_ver
                            )
                        )

    def get_content(self, package_url):
        splitted_url = package_url.split("/")
        url = (
            "https://api.github.com/repos/{}/{}/contents/CHANGELOG.md".format(
                splitted_url[-2], splitted_url[-1]
            )
        )
        self.debug("package url: {}".format(url))
        req = requests.get(url)
        if req.status_code == requests.codes.ok:
            self.status_code = True
            req = req.json()
            content = base64.b64decode(req["content"])
            content = content.decode("ascii")
            content = content.splitlines()
        else:
            self.status_code = False
            content = None
        return content

    def get_message(self):
        message = ""
        new_ver = ""
        for i, line in enumerate(self.content):
            if "## [" in line:
                if "## [Unreleased]" in line:
                    continue

                if "[{}]".format(self.current_version) in line:
                    self.debug("version already updated")
                    break
                else:
                    self.debug("found newer version online")
                    message += line + "\n"
                    new_ver = line[line.find("[") + 1 : line.find("]")]
                    for line_ in self.content[i + 1 :]:
                        if self.current_version in line_:
                            break
                        elif line_ != "":
                            message += line_ + "\n"
                    break
        return message, new_ver

    def _check_internet(self, host="8.8.8.8", port=53, timeout=3):
        """
        Host: 8.8.8.8 (google-public-dns-a.google.com)
        OpenPort: 53/tcp
        Service: domain (DNS/TCP)

        solution from https://stackoverflow.com/a/33117579
        """
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                (host, port)
            )
            return True
        except OSError as ex:
            print(ex)
            return False
