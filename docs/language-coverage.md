# Language coverage for fixtures and the eval corpus

**Audience:** contributor

The analyzer catalog spans 33 languages and formats. The eval corpus and the
planted-defect fixtures cover a small subset. This page is the three deliverables of
the language sourcing sweep (#860): a coverage matrix, a sourced list of public pull
requests, and a prioritized work list. It supplies **material**; the mechanisms that
consume it (batch generalisation of the golden manifest, the detection-corpus
campaign) are tracked elsewhere.

What this page is not: it creates no repository, forks nothing and vendors no code.
Auditing the maintainer's own fixture repositories, filling their missing cells and
making them public are the maintainer's work and are listed in the work list below.

## Coverage matrix

"Analyzer tools" counts catalog entries that declare the language
(`mergecraft analyzers list` is the live source). "Golden corpus case" is a case under
`evals/cases/golden/`. "Planted-defect fixture" records the maintainer's private
`mergecraft-<lang>-example` repositories as the sweep issue described them on
2026-09-24; they were not re-read for this page. "Public PRs sourced here" counts the
entries in the table further down.

| Language | Analyzer tools | Golden corpus case | Planted-defect fixture (private) | Public PRs sourced here |
| --- | --- | --- | --- | --- |
| batch | 1 | no | no | 0 |
| c | 4 | no | yes | 2 |
| cloudformation | 1 | no | no | 0 |
| cpp | 4 | no | yes | 2 |
| css | 1 | no | no | 0 |
| docker | 1 | no | no | 2 |
| ember | 1 | no | no | 0 |
| fortran | 1 | no | no | 0 |
| gherkin | 1 | no | no | 0 |
| go | 6 | yes | yes | 2 |
| html | 1 | no | no | 0 |
| java | 5 | yes | yes | 2 |
| javascript | 10 | yes | yes | 2 |
| kotlin | 1 | no | yes | 2 |
| liquid | 1 | no | no | 0 |
| lua | 1 | no | no | 2 |
| make | 1 | no | no | 0 |
| markdown | 2 | no | no | 0 |
| php | 3 | no | no | 2 |
| powershell | 1 | no | no | 2 |
| prisma | 1 | no | no | 0 |
| python | 14 | yes | yes | 2 |
| rego | 1 | no | no | 0 |
| ruby | 5 | yes | yes | 2 |
| rust | 7 | yes | yes | 2 |
| shell | 1 | no | no | 2 |
| smarty | 1 | no | no | 0 |
| sql | 1 | no | no | 0 |
| swift | 1 | no | no | 2 |
| terraform | 2 | no | no | 1 |
| text | 1 | no | no | 0 |
| typescript | 11 | yes | yes | 2 |
| yaml | 5 | no | no | 0 |

Totals: 7 of 33 languages have a golden corpus case, 10 have a planted-defect fixture
(`c`, `cpp` and `kotlin` have a fixture but no golden case), and 23 have neither. Of
those 23, only `php` (three tools) and `yaml` (five) carry three or more catalog tools.

### Fixture category and difficulty cells

Each planted-defect fixture is meant to hold one pull request per category and
difficulty. Categories are `correctness`, `security`, `reliability`, `test-gap` and
`api-break`; difficulty tiers are `bug`, `medium` and `advanced`. What the sweep
issue reports:

| Tier | correctness | security | reliability | test-gap | api-break |
| --- | --- | --- | --- | --- | --- |
| bug | present | missing | present | missing | missing |
| medium | not audited | not audited | not audited | not audited | not audited |
| advanced | not audited | not audited | not audited | not audited | missing |

Every "not audited" cell needs a read of the ten repositories; this page does not guess.

## Sourced public pull requests

Method: GitHub search for merged pull requests per language (sorted by reactions, then
by a keyword query for languages where the label search returned too little), each
checked against the API on 2026-10-17 for: repository public and not archived, licence
an OSI-permissive SPDX identifier (MIT, Apache-2.0, BSD, ISC, MPL-2.0, Unlicense), pull
request merged, and small (at most six files and 150 changed lines, so it fits a fixture).
The defect class is read from the title and is a triage guess: confirm it against the diff
before vendoring. Vendoring needs the licence text and attribution preserved, and the
fixture must say it is vendored, not an official fork.

| Language | Repository | PR | Licence | Files / lines | Defect class (read from the title) |
| --- | --- | --- | --- | --- | --- |
| c | `arduino/ArduinoCore-renesas` | [#317](https://github.com/arduino/ArduinoCore-renesas/pull/317) | MIT | 2 / 8 | buffer overflow |
| c | `zephyrproject-rtos/zephyr` | [#115767](https://github.com/zephyrproject-rtos/zephyr/pull/115767) | Apache-2.0 | 1 / 52 | buffer overflow (odd lengths) |
| cpp | `godotengine/godot` | [#87297](https://github.com/godotengine/godot/pull/87297) | MIT | 5 / 27 | logic / numeric behaviour |
| cpp | `opencv/opencv_contrib` | [#3480](https://github.com/opencv/opencv_contrib/pull/3480) | Apache-2.0 | 2 / 24 | use of an uninitialised size before it is computed |
| go | `hashicorp/terraform-provider-aws` | [#11463](https://github.com/hashicorp/terraform-provider-aws/pull/11463) | MPL-2.0 | 2 / 29 | spurious diff / state handling |
| go | `helm/helm` | [#12879](https://github.com/helm/helm/pull/12879) | Apache-2.0 | 2 / 50 | logic: null values override |
| java | `jenkinsci/github-branch-source-plugin` | [#864](https://github.com/jenkinsci/github-branch-source-plugin/pull/864) | MIT | 1 / 25 | null handling |
| java | `spring-cloud/spring-cloud-kubernetes` | [#554](https://github.com/spring-cloud/spring-cloud-kubernetes/pull/554) | Apache-2.0 | 4 / 50 | data-type and ordering |
| javascript | `faressoft/terminalizer` | [#97](https://github.com/faressoft/terminalizer/pull/97) | MIT | 2 / 52 | error handling |
| javascript | `wwebjs/whatsapp-web.js` | [#1107](https://github.com/wwebjs/whatsapp-web.js/pull/1107) | Apache-2.0 | 1 / 2 | wrong call / API misuse |
| kotlin | `Kotlin/kotlinx-rpc` | [#445](https://github.com/Kotlin/kotlinx-rpc/pull/445) | Apache-2.0 | 5 / 65 | unchecked null cast (potential NPE) |
| kotlin | `maplibre/maplibre-compose` | [#1650](https://github.com/maplibre/maplibre-compose/pull/1650) | BSD-3-Clause | 2 / 57 | race at startup |
| php | `Aeliot-Tm/todo-registrar` | [#294](https://github.com/Aeliot-Tm/todo-registrar/pull/294) | MIT | 1 / 8 | null dereference |
| php | `symfony/symfony` | [#37327](https://github.com/symfony/symfony/pull/37327) | MIT | 2 / 8 | null handling / API contract |
| python | `fastapi/typer` | [#548](https://github.com/fastapi/typer/pull/548) | MIT | 2 / 50 | type-handling regression on a newer interpreter |
| python | `karpathy/nanochat` | [#186](https://github.com/karpathy/nanochat/pull/186) | MIT | 1 / 8 | state corruption (cache resize) |
| ruby | `puma/puma` | [#1808](https://github.com/puma/puma/pull/1808) | BSD-3-Clause | 4 / 95 | resource cleanup on signal |
| ruby | `zoolutions/sidekiq-unique-jobs` | [#781](https://github.com/zoolutions/sidekiq-unique-jobs/pull/781) | MIT | 2 / 4 | deprecated command |
| rust | `emilk/egui` | [#5640](https://github.com/emilk/egui/pull/5640) | Apache-2.0 | 2 / 23 | layout / sizing logic |
| rust | `emilk/egui` | [#5133](https://github.com/emilk/egui/pull/5133) | Apache-2.0 | 1 / 4 | repeated request loop |
| swift | `Quick/Quick` | [#1129](https://github.com/Quick/Quick/pull/1129) | Apache-2.0 | 2 / 13 | test discovery on a toolchain change |
| swift | `swiftlang/swift-package-manager` | [#7616](https://github.com/swiftlang/swift-package-manager/pull/7616) | Apache-2.0 | 4 / 104 | incremental build correctness |
| typescript | `refined-github/refined-github` | [#4168](https://github.com/refined-github/refined-github/pull/4168) | MIT | 1 / 2 | DOM handling regression |
| typescript | `remix-run/react-router` | [#7462](https://github.com/remix-run/react-router/pull/7462) | MIT | 2 / 58 | path handling with a base |
| lua | `dont-be-evil-company/kulala.nvim` | [#825](https://github.com/dont-be-evil-company/kulala.nvim/pull/825) | MIT | 3 / 137 | encoding (OAuth2 Basic auth) |
| lua | `pwntester/octo.nvim` | [#816](https://github.com/pwntester/octo.nvim/pull/816) | MIT | 1 / 8 | plugin integration |
| shell | `jeffreytse/zsh-vi-mode` | [#180](https://github.com/jeffreytse/zsh-vi-mode/pull/180) | MIT | 1 / 51 | terminal state handling |
| shell | `spaceship-prompt/spaceship-prompt` | [#770](https://github.com/spaceship-prompt/spaceship-prompt/pull/770) | MIT | 3 / 12 | context detection bug |
| terraform | `terraform-ibm-modules/terraform-ibm-landing-zone` | [#701](https://github.com/terraform-ibm-modules/terraform-ibm-landing-zone/pull/701) | Apache-2.0 | 2 / 4 | ACL handling via a module bug |
| powershell | `ChrisTitusTech/winutil` | [#4957](https://github.com/ChrisTitusTech/winutil/pull/4957) | MIT | 4 / 28 | compatibility |
| powershell | `andresharpe/dotbot` | [#57](https://github.com/andresharpe/dotbot/pull/57) | MIT | 3 / 54 | duration accounting |
| docker | `beringar/addon-influxdbv2` | [#1](https://github.com/beringar/addon-influxdbv2/pull/1) | MIT | 3 / 43 | end-of-life base image / broken download |
| docker | `mmalyska/containers` | [#367](https://github.com/mmalyska/containers/pull/367) | Apache-2.0 | 4 / 28 | build failure |

Not sourced in this pass: `batch`, `cloudformation`, `css`, `ember`, `fortran`, `html`,
`liquid`, `make`, `markdown`, `prisma`, `rego`, `smarty`, `sql`, `text`, `yaml`. Search over
these formats returned configuration churn (dependency bumps, documentation edits) rather
than defects. They need hand-picked sources, or synthetic fixtures labelled as such.

Two limits of this list. It is a candidate list, not a vetted corpus: the same search
also returned many dependency bumps and documentation changes, which were discarded by
hand, and a title is not a diff. And the introducing pull request for each defect, which
the sweep issue prefers over the fix alone, was not traced.

## Prioritized work list

1. **Golden corpus cases for languages that have none:** `c` and `cpp` (four catalog
   tools each, and a fixture already), then `php`, then `kotlin` and `swift`. Take the
   sourced pull requests above as the starting point, trace each to its introducing
   change, and confirm the defect on the diff. (Agent or operator work; needs no new
   repository.)
2. **New planted-defect fixtures for languages without one that have a sourced pull
   request:** `php`, `swift`, `lua`. Creating a repository is the maintainer's action.
3. **Audit the ten existing fixtures and `mergecraft-py-example`** (maintainer): list
   branches with no pull request, pull requests not merged, missing category and
   difficulty cells (the table above), and vendored upstreams older than the 2026-09-18
   pin that need refreshing. Add a licence and attribution notice to each and keep the
   "vendored, not an official fork" wording.
4. **Fill the missing cells** the audit finds: the `bug` tier has no `security`,
   `test-gap` or `api-break` case, and `advanced` has no `api-break` case.
5. **Make the fixtures public** once items 3 and 4 are done. Public fixtures become
   in-bounds sources for the failure-shaped trajectory harvest
   ([failure-trajectory-harvest.md](failure-trajectory-harvest.md)); until then their
   trajectories are out of bounds and must be flagged, not committed.
6. **Config and format languages** (`terraform`, `docker`, `powershell`, `shell`,
   `gherkin`, then the rest): hand-pick sources or write labelled synthetic fixtures; the
   public search is too noisy to mine.

## Constraints that apply to every item

Vendor only public code, record the licence and attribution, and never claim an official
fork. Trajectories used for the auditor come only from public sources; flag private-only
material instead of committing it.
