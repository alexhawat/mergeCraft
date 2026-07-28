---
name: git-archaeology
description: Investigate how code reached its current state — when a line, function, import, or whole file was changed or deleted, who removed it, and what it looked like before. Use when `git blame` came up empty, when content has been refactored away, or when you need the full evolution of a function across commits.
---

# Git history archaeology

`git blame` only sees what's still in the working tree. For anything that was
deleted, moved, or refactored away, you need the commands below. Most agents
under-use them and end up scrolling through `git log -p` instead.

## Output discipline (read first)

`git log -p` on a long-lived file can dump tens of thousands of lines and blow
the context window. Always:

1. **Start narrow.** Use `--oneline` or `--stat` to get a list of candidate
   commits.
2. **Drill in.** Use `git show <sha> -- <path>` for the diff of one specific
   commit.
3. **Scope the search.** Add `--since="3 months ago"`, `-n 20`, or a path
   restriction (`-- <path>`) so output stays manageable.
4. **Avoid `git log -p` without a path filter** on any non-trivial repo.

## Decision tree (by agent intent)

### "When did this exact line, string, or import disappear?"

```bash
git log -S'<exact-string>' --oneline -- <file>
```

The pickaxe. Returns commits that **changed the count** of that string in the
file. The most recent hit is typically the removal commit. Add `-p` only after
you've narrowed to a few candidates.

Notes:
- `-S` is exact-string by default. Add `--pickaxe-regex` to make it a regex.
- The argument is "cuddled" with `-S` (`-S'foo bar'`), no space.
- `-S` will not detect pure in-file moves (count unchanged). Use `-G` for that.
- `--pickaxe-all` shows the entire changeset of matching commits, useful when
  a commit changes both a definition and its call sites in other files.

### "When did the diff stop matching this regex?"

```bash
git log -G'<regex>' --oneline -- <file>
```

Like `-S` but matches any added or removed hunk line against the regex. Use
`-G` when:
- You don't know the exact string but know a pattern.
- You want to catch in-file moves (`-S` won't).
- You want to find any diff that touched a pattern, even if the count was
  preserved (e.g., a refactor that changed call sites without removing the
  function).

### "How did this function evolve over time?"

```bash
git log -L :<function-name>:<file>
```

Every commit that touched the function, with diffs scoped to just the function
body. Works for languages git understands (most mainstream ones).

### "How did lines N–M evolve?"

```bash
git log -L <N>,<M>:<file>
```

### "What's the full history of this file, including across renames?"

```bash
git log --follow --oneline -- <file>      # overview
git log --follow -p -- <file>             # with diffs (use sparingly)
```

`--follow` only works for a single file, not directories.

### "Where was a now-deleted line last present?"

Two-step pattern when you have an exact deleted string:

```bash
# 1. find a historical commit that contained the string
git log -S'<deleted-string>' --oneline --all -- <file>

# 2. reverse-blame from that commit to find the last commit it survived in
git blame --reverse <old-sha>..HEAD -- <file>
```

The reverse blame tells you, for each line, the last commit it survived in
before being modified or deleted. Pinpoints the exact deletion commit.

### "This file no longer exists — when was it deleted, and what was in it?"

```bash
# find all commits that touched the path, even on other branches
git log --all --full-history --oneline -- <deleted-path>

# the most recent of those is usually the deletion. confirm:
git show <sha> --stat

# view the file's contents at any commit where it existed
git show <sha>^:<deleted-path>
```

If you don't know the path, find it from filename alone:

```bash
# list all delete events with paths
git log --all --diff-filter=D --summary | grep -i '<filename>'

# or glob across all branches
git log --all --oneline -- '**/<filename>.*'
```

### "Who deleted it, in one shot?"

```bash
git rev-list -n 1 HEAD -- <deleted-path>     # the deletion commit
git show $(git rev-list -n 1 HEAD -- <deleted-path>) -- <deleted-path>
```

### "Restore a deleted file (locally, no commit)"

```bash
git restore --source=<deletion-sha>^ -- <deleted-path>
# or, on older git:
git checkout <deletion-sha>^ -- <deleted-path>
```

The `^` is critical — at the deletion commit the file is already gone, so we
read from its parent.

### "Search commit messages, not content"

```bash
git log --all --grep='<text>' --oneline
git log --all --grep='<text>' -i --oneline    # case-insensitive
```

Orthogonal to `-S`/`-G`, which only see the diff.

## Standard workflow for "why does this code look like this"

1. `git log --follow --oneline -- <file>` — overview of commits touching it.
2. If a recent commit looks suspicious: `git show <sha> -- <file>`.
3. If you expected to find something and it's missing:
   `git log -S'<expected-string>' --oneline -- <file>`.
4. For a specific function's full lifecycle:
   `git log -L :<fn>:<file>`.
5. For the deletion point of a known string: pickaxe to find an old commit
   that contained it, then `git blame --reverse <old-sha>..HEAD -- <file>`.

## Useful flags reference

| Flag | Effect |
|------|--------|
| `--all` | Search all refs, not just the current branch. Use when investigating something that may have lived only on a feature branch. |
| `--full-history` | Keeps commits that history-simplification would otherwise drop. Needed for accurate history across merges. |
| `--follow` | Track a single file across renames. Single-file only. |
| `-M` / `-C` | Detect renames (`-M`) and copies (`-C`) when reading diffs. |
| `--diff-filter=D` | Restrict to commits that **deleted** something. `A`=added, `M`=modified, `R`=renamed. |
| `--source` | When combined with `--all`, annotate each commit with the ref it was reached from. |
| `--pickaxe-all` | With `-S`/`-G`, show all files in the matching commit, not just the matching file. |
| `--pickaxe-regex` | Treat the `-S` argument as a regex. |
| `--since` / `--until` | Time-bound the search. Cheap perf win on big repos. |
| `-n <count>` | Cap result count. |
| `--stat` | Per-commit file stats instead of full patches. Good first pass. |

## Notes and pitfalls

- Always include `--` before paths to disambiguate from refs (e.g.
  `git log -S'foo' -- src/auth.ts`).
- `-S` triggers on **count change**. A pure refactor that moves a line within
  the same file will not match. Use `-G` for those.
- `-G` runs diff twice and greps; it's slower than `-S`. Scope with paths and
  `--since` on big repos.
- Without `--all`, `git log -- <path>` shows nothing if the path never existed
  on the current branch. When in doubt, add `--all`.
- `git log --full-history -- <path>` alone has had bugs in some git versions
  for deleted files; pair with `--all` for reliability.
- For files that were renamed, `git log -- <new-path>` only shows post-rename
  history. Use `--follow` (one file) or `git log --all -- <old-path>` when
  hunting across rename events.
