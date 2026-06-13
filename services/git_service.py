from git import Repo, InvalidGitRepositoryError
from core.config import ARTICLES_DIR

def init_git():
    try:
        repo = Repo(ARTICLES_DIR)
    except InvalidGitRepositoryError:
        repo = Repo.init(ARTICLES_DIR)
        repo.git.add(A=True)
        if repo.is_dirty() or repo.untracked_files:
            repo.index.commit("Initial Wiki Commit")
    return repo

git_repo = init_git()

def commit_changes(message: str):
    git_repo.git.add(A=True)
    if git_repo.is_dirty() or git_repo.untracked_files:
        git_repo.index.commit(message)