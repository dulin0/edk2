## @file
#  GitHub API helper functions.
#
#  Copyright (c) Microsoft Corporation.
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#

import logging
import re
import requests

from collections import OrderedDict
from edk2toollib.utility_functions import RunCmd, RunPythonScript
from io import StringIO
from typing import List

"""GitHub API helper functions."""


def leave_pr_comment(
    token: str, owner: str, repo: str, pr_number: str, comment_body: str
):
    """Leaves a comment on a PR.

    Args:
        token (str): The GitHub token to use for authentication.
        owner (str): The GitHub owner (organization) name.
        repo (str): The GitHub repository name (e.g. 'edk2').
        pr_number (str): The pull request number.
        comment_body (str): The comment text. Markdown is supported.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"body": comment_body}
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()


def get_reviewers_for_range(
    workspace_path: str,
    maintainer_file_path: str,
    range_start: str = "master",
    range_end: str = "HEAD",
) -> List[str]:
    """Get the reviewers for the current branch.

       To get the reviewers for a single commit, set `range_start` and
       `range_end` to the commit SHA.

    Args:
        workspace_path (str): The workspace path.
        maintainer_file_path (str): The maintainer file path.
        range_start (str, optional): The range start ref. Defaults to "master".
        range_end (str, optional): The range end ref. Defaults to "HEAD".

    Returns:
        List[str]: A list of GitHub usernames.
    """

    if range_start == range_end:
        commits = [range_start]
    else:
        commit_stream_buffer = StringIO()
        cmd_ret = RunCmd(
            "git",
            f"log --format=format:%H {range_start}..{range_end}",
            workingdir=workspace_path,
            outstream=commit_stream_buffer,
            logging_level=logging.INFO,
        )
        if cmd_ret != 0:
            print(
                f"::error title=Commit Lookup Error!::Error getting branch commits: [{cmd_ret}]: {commit_stream_buffer.getvalue()}"
            )
            return []
        commits = commit_stream_buffer.getvalue().splitlines()

    raw_reviewers = []
    for commit_sha in commits:
        reviewer_stream_buffer = StringIO()
        cmd_ret = RunPythonScript(
            maintainer_file_path,
            f"-g {commit_sha}",
            workingdir=workspace_path,
            outstream=reviewer_stream_buffer,
            logging_level=logging.INFO,
        )
        if cmd_ret != 0:
            print(
                f"::error title=Reviewer Lookup Error!::Error calling GetMaintainer.py: [{cmd_ret}]: {reviewer_stream_buffer.getvalue()}"
            )
            return []

        commit_reviewers = reviewer_stream_buffer.getvalue()

        pattern = r"\[(.*?)\]"
        matches = re.findall(pattern, commit_reviewers)
        if not matches:
            return []

        print(
            f"::debug title=Commit {commit_sha[:7]} Reviewer(s)::{', '.join(matches)}"
        )

        raw_reviewers.extend(matches)

    reviewers = list(OrderedDict.fromkeys([r.strip() for r in raw_reviewers]))

    print(f"::debug title=Total Reviewer Set::{', '.join(reviewers)}")

    return reviewers


def get_pr_sha(token: str, owner: str, repo: str, pr_number: str) -> str:
    """Returns the commit SHA of given PR branch.

       This returns the SHA of the merge commit that GitHub creates from a
       PR branch. This commit contains all of the files in the PR branch in
       a single commit.

    Args:
        token (str): The GitHub token to use for authentication.
        owner (str): The GitHub owner (organization) name.
        repo (str): The GitHub repository name (e.g. 'edk2').
        pr_number (str): The pull request number.

    Returns:
        str: The commit SHA of the PR branch. An empty string is returned
             if the request fails.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(url, headers=headers)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        print(
            f"::error title=HTTP Error!::Error getting PR Commit Info: {response.reason}"
        )
        return ""

    commit_sha = response.json()["merge_commit_sha"]

    print(f"::debug title=PR {pr_number} Commit SHA::{commit_sha}")

    return commit_sha


def download_gh_file(github_url: str, local_path: str, token=None):
    """Downloads a file from GitHub.

    Args:
        github_url (str): The GitHub raw file URL.
        local_path (str): A local path to write the file contents to.
        token (_type_, optional): A GitHub authentication token.
            Only needed for a private repo. Defaults to None.
    """
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(github_url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        print(
            f"::error title=HTTP Error!::Error downloading {github_url}: {response.reason}"
        )
        return

    with open(local_path, "w", encoding="utf-8") as file:
        file.write(response.text)


def add_reviewers_to_pr(
    token: str, owner: str, repo: str, pr_number: str, user_names: List[str]
):
    """Adds the set of GitHub usernames as reviewers to the PR.

    Args:
        token (str): The GitHub token to use for authentication.
        owner (str): The GitHub owner (organization) name.
        repo (str): The GitHub repository name (e.g. 'edk2').
        pr_number (str): The pull request number.
        user_names (List[str]): List of GitHub usernames to add as reviewers.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    pr_author_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"

    response = requests.get(pr_author_url, headers=headers)
    if response.status_code != 200:
        print(f"::error title=HTTP Error!::Error getting PR author: {response.reason}")
        return
    pr_author = response.json().get("user").get("login").strip()
    while pr_author in user_names:
        user_names.remove(pr_author)
    data = {"reviewers": user_names}
    response = requests.post(url, json=data, headers=headers)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        if (
            response.status_code == 422
            and "Reviews may only be requested from collaborators"
            in response.json().get("message")
        ):
            print(
                f"::error title=User is not a Collaborator!::{response.json().get('message')}"
            )
            leave_pr_comment(
                token,
                owner,
                repo,
                pr_number,
                f"&#9888; **WARNING: Cannot add reviewers**: A user specified as a "
                f"reviewer for this PR is not a collaborator "
                f"of the edk2 repository. Please add them as a collaborator to the "
                f"repository and re-request the review.\n\n"
                f"Users requested:\n{', '.join(user_names)}",
            )
        elif response.status_code == 422:
            print(
                "::error title=Invalid Request!::The request is invalid. "
                "Verify the API request string."
            )
