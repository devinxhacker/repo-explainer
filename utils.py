import requests
import base64
from urllib.parse import urlparse

def parse_github_url(url):
    """
    Parses your GitHub URL and extracts the repository owner and name.
    """
    parsed_url = urlparse(url)
    path_segments = parsed_url.path.strip("/").split("/")
    if len(path_segments) >= 2:
        owner, repo = path_segments[0], path_segments[1]
        # Support clone URLs ending in .git
        if repo.endswith('.git'):
            repo = repo[:-4]
        return owner, repo
    else:
        raise ValueError("Invalid GitHub URL provided!")

def fetch_repo_content(owner, repo, path='', token=None):
    """
    Fetches the content of your GitHub repository.
    """
    base_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(base_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()

def get_file_content(file_info):
    """
    Retrieves and decodes the content of files
    """
    if file_info['encoding'] == 'base64':
        return base64.b64decode(file_info['content']).decode('utf-8')
    else:
        return file_info['content']

def build_directory_tree(owner, repo, path='', token=None, indent=0, file_paths=None):
    """
    Builds a string representation of the directory tree and collects file paths.

    Note: Avoids using a mutable default for file_paths to prevent cross-call leakage
    of paths when scanning multiple repositories in the same process.
    """
    if file_paths is None:
        file_paths = []

    items = fetch_repo_content(owner, repo, path, token)
    tree_str = ""
    for item in items:
        # Skip GitHub meta/config directories
        if '.github' in item['path'].split('/'):
            continue
        if item['type'] == 'dir':
            tree_str += '    ' * indent + f"[{item['name']}/]\n"
            subtree_str, _ = build_directory_tree(owner, repo, item['path'], token, indent + 1, file_paths)
            tree_str += subtree_str
        else:
            tree_str += '    ' * indent + f"{item['name']}\n"
            # Indicate which file extensions should be included in the prompt!
            if item['name'].endswith(('.py', '.html', '.css', '.js', '.jsx', '.rst', '.md')):
                file_paths.append((indent, item['path']))
    return tree_str, file_paths

def retrieve_github_repo_info(
    url,
    token=None,
    max_files: int = 80,
    max_file_chars: int = 15000,
    total_chars_cap: int = 200_000,
):
    """
    Retrieves and formats repository information, including README, the directory tree,
    and file contents, while ignoring the .github folder.
    """
    owner, repo = parse_github_url(url)

    try:
        readme_info = fetch_repo_content(owner, repo, 'README.md', token)
        readme_content = get_file_content(readme_info)
        if len(readme_content) > max_file_chars:
            readme_content = readme_content[:max_file_chars] + "\n... [truncated]\n"
        formatted_string = f"README.md:\n```\n{readme_content}\n```\n\n"
    except Exception as e:
        formatted_string = "README.md: Not found or error fetching README\n\n"

    directory_tree, file_paths = build_directory_tree(owner, repo, token=token)

    formatted_string += f"Directory Structure:\n{directory_tree}\n"

    files_added = 0
    for indent, path in file_paths:
        if files_added >= max_files or len(formatted_string) >= total_chars_cap:
            break
        try:
            file_info = fetch_repo_content(owner, repo, path, token)
            file_content = get_file_content(file_info)
            if len(file_content) > max_file_chars:
                file_content = file_content[:max_file_chars] + "\n... [truncated]\n"
            snippet = '\n' + '    ' * indent + f"{path}:\n" + '    ' * indent + '```\n' + file_content + '\n' + '    ' * indent + '```\n'
            # Enforce total cap
            if len(formatted_string) + len(snippet) > total_chars_cap:
                remaining = max(total_chars_cap - len(formatted_string), 0)
                if remaining > 0:
                    snippet = snippet[:remaining]
                formatted_string += snippet
                break
            formatted_string += snippet
            files_added += 1
        except Exception:
            # Skip files that cannot be fetched (e.g., moved, deleted, or permission errors)
            continue

    return formatted_string