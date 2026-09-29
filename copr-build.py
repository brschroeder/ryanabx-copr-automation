import subprocess
import json
import requests
import os
import time

REPOS = {
    "cosmic-app-library": "cosmic-applibrary",
    "cosmic-applets": "cosmic-applets",
    "cosmic-bg": "cosmic-bg",
    "cosmic-comp": "cosmic-comp",
    "cosmic-edit": "cosmic-edit",
    "cosmic-files": "cosmic-files",
    "cosmic-greeter": "cosmic-greeter",
    "cosmic-icon-theme": "cosmic-icons",
    "cosmic-idle": "cosmic-idle",
    "cosmic-initial-setup": "cosmic-initial-setup",
    "cosmic-launcher": "cosmic-launcher",
    "cosmic-monitor": "cosmic-monitor",
    "cosmic-notifications": "cosmic-notifications",
    "cosmic-osd": "cosmic-osd",
    "cosmic-osk": "cosmic-osk",
    "cosmic-panel": "cosmic-panel",
    "cosmic-player": "cosmic-player",
    "cosmic-randr": "cosmic-randr",
    "cosmic-screenshot": "cosmic-screenshot",
    "cosmic-session": "cosmic-session",
    "cosmic-settings": "cosmic-settings",
    "cosmic-settings-daemon": "cosmic-settings-daemon",
    "cosmic-store": "cosmic-store",
    "cosmic-term": "cosmic-term",
    "cosmic-wallpapers": "cosmic-wallpapers",
    "cosmic-workspaces": "cosmic-workspaces-epoch",
    "pop-launcher": "launcher",
    "xdg-desktop-portal-cosmic": "xdg-desktop-portal-cosmic",
    "cosmic-epoch": "cosmic-epoch",
}

NIGHTLY_COPR = "ryanabx/cosmic-epoch"
TAGGED_COPR = "ryanabx/cosmic-epoch-tagged"

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 30  # seconds, for GitHub API calls

# Set up authentication for GitHub API and COPR API

COPR_CONFIG = os.environ.get("COPR_AUTH")
if COPR_CONFIG:
    # Get the path to ~/.config/copr
    config_dir = os.path.expanduser("~/.config")
    config_file = os.path.join(config_dir, "copr")

    # Ensure the .config directory exists
    os.makedirs(config_dir, exist_ok=True)
    # Write content to the file
    with open(config_file, "w") as file:
        file.write(COPR_CONFIG)

    print(f"Configuration written to {config_file}")

TOKEN = os.environ.get("PAT_GITHUB")
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
else:
    print(
        "WARNING: PAT_GITHUB is not set; GitHub API calls will be "
        "unauthenticated (rate limit: 60 requests/hour)"
    )


def github_get(url: str, context: str):
    """
    GET a GitHub API endpoint, returning the parsed JSON or None on any
    failure (network error, HTTP error, invalid JSON).
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        print(f"WARNING: {context}: request failed: {exc}")
        return None
    if response.status_code != 200:
        print(f"WARNING: {context}: GitHub API returned HTTP {response.status_code}")
        return None
    try:
        return response.json()
    except ValueError as exc:
        print(f"WARNING: {context}: invalid JSON in response: {exc}")
        return None


def latest_succeeded_version(pkg: dict) -> str:
    """
    The source package version of a package's latest succeeded build,
    or an empty string if the package has no succeeded build yet.
    """
    build = pkg.get("latest_succeeded_build") or {}
    source = build.get("source_package") or {}
    return source.get("version") or ""


def latest_build_state(pkg: dict) -> str:
    """The state of a package's latest build, or '' if it has never been built."""
    build = pkg.get("latest_build") or {}
    return build.get("state") or ""


class Package:
    """
    Simple structure to represent a package from COSMIC
    """

    def __init__(
        self,
        package: str,
        upstream_repo_name: str,
        newest_nightly_commit: str,
        newest_nightly_tag: str,
        newest_tagged_tag: str,
        nightly_build_status: str,
        tagged_build_status: str,
    ):
        self.package = package
        self.upstream_repo_name = upstream_repo_name
        self.newest_nightly_commit = newest_nightly_commit
        self.newest_nightly_tag = newest_nightly_tag
        self.newest_tagged_tag = newest_tagged_tag
        self.nightly_build_status = nightly_build_status
        self.tagged_build_status = tagged_build_status
        # Get newest commit and tag
        self.newest_commit = self._get_latest_upstream_commit()
        self.newest_tag = self._get_latest_upstream_tag()

    def _get_latest_upstream_tag(self) -> str:
        """
        Get the latest tag for the upstream repo, or '' on any problem
        """
        data = github_get(
            f"{GITHUB_API}/repos/pop-os/{self.upstream_repo_name}/tags",
            f"latest tag for {self.package}",
        )
        if data is None:
            return ""
        if not isinstance(data, list) or not data:
            print(f"WARNING: {self.package}: upstream repo has no tags")
            return ""
        tag = str(data[0].get("name", "")).strip()
        if not tag:
            print(f"WARNING: {self.package}: first tag entry has no name")
            return ""
        # Tags look like "epoch-1.0.8": strip the prefix, if present
        if tag.startswith("epoch-"):
            tag = tag.removeprefix("epoch-")
        else:
            print(
                f"WARNING: {self.package}: tag {tag!r} does not start with "
                f"'epoch-'; using it as-is"
            )
        # Return the name with `-` replaced with `~`
        return tag.replace("-", "~")

    def _get_latest_upstream_commit(self) -> str:
        """
        Get the latest commit for the upstream repo, or '' on any problem
        """
        data = github_get(
            f"{GITHUB_API}/repos/pop-os/{self.upstream_repo_name}/commits",
            f"latest commit for {self.package}",
        )
        if data is None:
            return ""
        if not isinstance(data, list) or not data:
            print(f"WARNING: {self.package}: upstream repo has no commits")
            return ""
        git_sha = str(data[0].get("sha", ""))[0:7]
        if not git_sha:
            print(f"WARNING: {self.package}: could not extract commit sha")
            return ""
        return git_sha

    def should_build_nightly_package(self) -> bool:
        """
        `True` if should build nightly, `False` otherwise
        """
        if (
            self.newest_commit == "" or self.newest_tag == ""
        ):  # There was a problem getting the newest commit or tag
            print(
                f"{self.package}: could not determine upstream state, "
                f"skipping nightly build"
            )
            return False

        if self.nightly_build_status == "pending":
            print(f"{self.package}: Nightly build is already pending")
            return False
        if self.nightly_build_status == "running":
            print(f"{self.package}: Nightly build is already running")
            return False
        if self.newest_commit != self.newest_nightly_commit:
            old = self.newest_nightly_commit or "no build yet"
            print(
                f"{self.package}: Commit {self.newest_commit} is newer than "
                f"{old}. Needs nightly build."
            )
            return True
        if self.newest_tag != self.newest_nightly_tag:
            old = self.newest_nightly_tag or "no build yet"
            print(
                f"{self.package}: Tag {self.newest_tag} is newer than "
                f"{old}. Needs nightly build."
            )
            return True
        print(f"{self.package}: Nightly build up to date")
        return False

    def should_build_tagged_package(self) -> bool:
        """
        `True` if should build tagged, `False` otherwise
        """
        if self.newest_tag == "":  # There was a problem getting the newest tag
            print(
                f"{self.package}: could not determine upstream tag, "
                f"skipping tagged build"
            )
            return False
        if self.tagged_build_status == "pending":
            print(f"{self.package}: Tagged build is already pending")
            return False
        if self.tagged_build_status == "running":
            print(f"{self.package}: Tagged build is already running")
            return False
        if self.newest_tag != self.newest_tagged_tag:
            old = self.newest_tagged_tag or "no build yet"
            print(
                f"{self.package}: Tag {self.newest_tag} is newer than "
                f"{old}. Needs tagged build."
            )
            return True
        return False


def parse_tagged_tag(full_string: str, package: str = "") -> str:
    """
    Get the tag from a tagged copr version string, or '' if the string
    is empty or does not look like a version.
    """
    if not full_string:
        return ""
    if "-" not in full_string:
        if package:
            print(
                f"WARNING: {package}: unexpected tagged version "
                f"{full_string!r}; cannot extract tag"
            )
        return ""
    return full_string.rsplit("-", 1)[0].split(":", 1)[  # 1:1.0.8-1  # 1:1.0.8
        -1
    ]  # 1.0.8


def parse_nightly_tag(full_string: str) -> str:
    """
    Get the tag from a nightly copr version string, or '' if empty.
    """
    if not full_string:
        return ""
    return full_string.split("^", 1)[  # 1:1.0.8^git20260323.9973b03-1
        0
    ].split(  # 1:1.0.8
        ":", 1
    )[
        -1
    ]  # 1.0.8


def parse_nightly_commit(full_string: str, package: str = "") -> str:
    """
    Get the commit from a nightly copr version string, or '' if the
    string is empty or does not contain a ^git commit marker.
    """
    if not full_string:
        return ""
    if "^git" not in full_string:
        if package:
            print(
                f"WARNING: {package}: unexpected nightly version "
                f"{full_string!r}; cannot extract commit"
            )
        return ""
    return full_string.rsplit(".", 1)[  # 1:1.0.8^git20260323.9973b03-1
        -1
    ].split(  # 9973b03-1
        "-", 1
    )[
        0
    ]  # 9973b03


def main():
    # First, we list packages in the coprs
    copr_packages = json.loads(
        subprocess.run(
            [
                "copr-cli",
                "list-packages",
                "--with-latest-build",
                "--with-latest-succeeded-build",
                "--output-format",
                "json",
                NIGHTLY_COPR,
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    copr_nightly_packages = json.loads(
        subprocess.run(
            [
                "copr-cli",
                "list-packages",
                "--with-latest-build",
                "--with-latest-succeeded-build",
                "--output-format",
                "json",
                TAGGED_COPR,
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    nightly_builds: list[str] = []
    tagged_builds: list[str] = []

    for pkg in copr_packages:
        pkg_name = pkg["name"]
        tagged_pkg = next(
            (item for item in copr_nightly_packages if item["name"] == pkg_name), None
        )
        if tagged_pkg and pkg_name in REPOS.keys():
            print(f"Checking if {pkg_name} should build...")
            nightly_version = latest_succeeded_version(pkg)
            tagged_version = latest_succeeded_version(tagged_pkg)
            package = Package(
                pkg_name,
                REPOS[pkg_name],
                parse_nightly_commit(nightly_version, pkg_name),
                parse_nightly_tag(nightly_version),
                parse_tagged_tag(tagged_version, pkg_name),
                latest_build_state(pkg),
                latest_build_state(tagged_pkg),
            )
            if package.should_build_nightly_package():
                nightly_builds.append(package.package)
            if package.should_build_tagged_package():
                tagged_builds.append(package.package)
            time.sleep(5)
        else:
            print(f"Skipping {pkg_name}")

    print(f"Queueing builds:\n\nNightly:\n{nightly_builds}\n\nTagged:\n{tagged_builds}")

    for i in nightly_builds:
        try:
            subprocess.run(
                ["copr-cli", "build-package", "--timeout", "36000", "--name", i, NIGHTLY_COPR],
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass
    for i in tagged_builds:
        try:
            subprocess.run(
                ["copr-cli", "build-package", "--timeout", "36000", "--name", i, TAGGED_COPR],
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass


if __name__ == "__main__":
    main()
