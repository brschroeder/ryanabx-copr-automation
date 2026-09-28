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
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github.v3+json",  # Use the GitHub API version
}


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
        Get the latest tag for the upstream repo
        """
        req = requests.get(
            f"https://api.github.com/repos/pop-os/{self.upstream_repo_name}/tags",
            headers=HEADERS,
        )
        if req.status_code == 200:
            json_data = req.json()
            res: str = json_data[0]["name"].strip()
            # Return the name with epoch- removed and with `-` replaced with `~`
            return res.split("epoch-", 1)[1].replace("-", "~")
        print(f"WARNING: Could not get latest tag for {self.package}")
        return ""

    def _get_latest_upstream_commit(self) -> str:
        """
        Get the latest commit for the upstream repo
        """
        req = requests.get(
            f"https://api.github.com/repos/pop-os/{self.upstream_repo_name}/commits",
            headers=HEADERS,
        )
        if req.status_code == 200:
            json_data = req.json()
            git_sha = json_data[0]["sha"][0:7]
            return git_sha
        print(f"WARNING: Could not get latest commit for {self.package}")
        return ""

    def should_build_nightly_package(self) -> bool:
        """
        `True` if should build nightly, `False` otherwise
        """
        if (
            self.newest_commit == "" or self.newest_tag == ""
        ):  # There was a problem getting the newest commit or tag
            return False

        if self.nightly_build_status == "pending":
            print(f"{self.package}: Nightly build is already pending")
            return False
        if self.nightly_build_status == "running":
            print(f"{self.package}: Nightly build is already running")
            return False
        if self.newest_commit != self.newest_nightly_commit:
            print(
                f"{self.package}: Commit {self.newest_commit} is newer than {self.newest_nightly_commit}. Needs nightly build."
            )
            return True
        if self.newest_tag != self.newest_nightly_tag:
            print(
                f"{self.package}: Tag {self.newest_tag} is newer than {self.newest_nightly_tag}. Needs nightly build."
            )
            return True
        print(f"{self.package}: Build not needed")
        return False

    def should_build_tagged_package(self) -> bool:
        """
        `True` if should build tagged, `False` otherwise
        """
        if self.newest_tag == "":  # There was a problem getting the newest tag
            return False
        if self.tagged_build_status == "pending":
            print(f"{self.package}: Tagged build is already pending")
            return False
        if self.tagged_build_status == "running":
            print(f"{self.package}: Tagged build is already running")
            return False
        if self.newest_tag != self.newest_tagged_tag:
            print(
                f"{self.package}: Tag {self.newest_tag} is newer than {self.newest_tagged_tag}. Needs tagged build."
            )
            return True
        return False


def parse_tagged_tag(full_string: str) -> str:
    """
    Get the tag from a tagged copr version string
    """
    return full_string.rsplit("-", 1)[0].split(":", 1)[  # 1:1.0.8-1  # 1:1.0.8
        -1
    ]  # 1.0.8


def parse_nightly_tag(full_string: str) -> str:
    """
    Get the tag from a nightly copr version string
    """
    return full_string.split("^", 1)[  # 1:1.0.8^git20260323.9973b03-1
        0
    ].split(  # 1:1.0.8
        ":", 1
    )[
        -1
    ]  # 1.0.8


def parse_nightly_commit(full_string: str) -> str:
    """
    Get the commit from a nightly copr version string
    """
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
            package = Package(
                pkg_name,
                REPOS[pkg_name],
                parse_nightly_commit(
                    pkg["latest_succeeded_build"]["source_package"]["version"]
                ),
                parse_nightly_tag(
                    pkg["latest_succeeded_build"]["source_package"]["version"]
                ),
                parse_tagged_tag(
                    tagged_pkg["latest_succeeded_build"]["source_package"]["version"]
                ),
                pkg["latest_build"]["state"],
                tagged_pkg["latest_build"]["state"],
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
