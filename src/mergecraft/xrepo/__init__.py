"""Cross-repository intelligence — linked repos, contracts, blast radius, citations."""

from mergecraft.xrepo.blast_radius import (
    ChangedContract,
    CrossRepoImpact,
    resolve_cross_repo_dependents,
)
from mergecraft.xrepo.citations import Citation, format_citation, validate_citation
from mergecraft.xrepo.contract_index import ContractIndex, index_contracts
from mergecraft.xrepo.linked_repos import (
    LinkedRepoAccessError,
    LinkedRepoEntry,
    LinkedReposManifest,
    RunGrant,
    load_linked_repo_content,
    parse_manifest,
    render_linked_repo_context,
)
from mergecraft.xrepo.review import XrepoFinding, XrepoReview, review_linked_repos

__all__ = [
    "ChangedContract",
    "Citation",
    "ContractIndex",
    "CrossRepoImpact",
    "LinkedRepoAccessError",
    "LinkedRepoEntry",
    "LinkedReposManifest",
    "RunGrant",
    "XrepoFinding",
    "XrepoReview",
    "format_citation",
    "index_contracts",
    "load_linked_repo_content",
    "parse_manifest",
    "render_linked_repo_context",
    "resolve_cross_repo_dependents",
    "review_linked_repos",
    "validate_citation",
]
