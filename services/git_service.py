from git import Repo, InvalidGitRepositoryError
from core.config import ARTICLES_DIR

_git_repo = None


def init_git():
    try:
        repo = Repo(ARTICLES_DIR)
    except InvalidGitRepositoryError:
        repo = Repo.init(ARTICLES_DIR)
        repo.git.add(A=True)
        if repo.is_dirty() or repo.untracked_files:
            repo.index.commit("Initial Wiki Commit")
    return repo


def get_repo():
    """Lazily initialize the repo on first use so importing this module has no
    side effects (keeps startup and tests clean)."""
    global _git_repo
    if _git_repo is None:
        _git_repo = init_git()
    return _git_repo


def commit_changes(message: str):
    repo = get_repo()
    repo.git.add(A=True)
    if repo.is_dirty() or repo.untracked_files:
        repo.index.commit(message)
