# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0a4

### Breaking Changes

- Remove the built-in Nous Portal provider in [75465ff3](https://github.com/alexhawat/mergeCraft/commit/75465ff3d333f775fbb4979ce1c42f33191ec5b2)

### Added

#### Agents

- Wire Codex to credential broker (W3) in [58cc5e02](https://github.com/alexhawat/mergeCraft/commit/58cc5e021d36289afdcc150bd6ab4af4a8c9ca97)
- Render stream events instead of raw dump (W7) in [694f4d51](https://github.com/alexhawat/mergeCraft/commit/694f4d512e428e28ecde698d6d9403c52661d9be)
- Classify post-run retries before resuming in [6f97c882](https://github.com/alexhawat/mergeCraft/commit/6f97c88243a993c5d7b61c452b10d4bd0e8d39a5)
- Add multi-reviewer merge and roster selection in [5ffc5310](https://github.com/alexhawat/mergeCraft/commit/5ffc5310e6bccee8ae7aa831241176e4dfd494dd)
- Support multiple bindings per role in registry in [d65c20d0](https://github.com/alexhawat/mergeCraft/commit/d65c20d03314f1c2e94b10f7858ea8906a031624)

#### Analyzers

- Disposition ledger, self-silencing, pinned settings, base runs in [5280e364](https://github.com/alexhawat/mergeCraft/commit/5280e3644a38dd3c115fb1a89e12c1fc505b2020)
- Add opt-in gherkin-lint catalog analyzer in [66322a7c](https://github.com/alexhawat/mergeCraft/commit/66322a7c8d232f9f21dbee363ac305c4e6a55332)
- Fail closed on unenforceable egress allowlist in [c8ab716a](https://github.com/alexhawat/mergeCraft/commit/c8ab716a04fc00f2d1072cc4996dd700b30466f0)

#### Ci

- Gate complete coverage shard sets in [b2a899ee](https://github.com/alexhawat/mergeCraft/commit/b2a899ee808d546c9dff06f5023a6f2bd66f6145)
- Ingest mutation artifacts as changed-function evidence in [82ef07f7](https://github.com/alexhawat/mergeCraft/commit/82ef07f7900232f914fd4fade1f502da59683af9)
- Ingest coverage artifacts and score CRAP on changed functions in [1461fa51](https://github.com/alexhawat/mergeCraft/commit/1461fa51d527b0ffccdec83a437dbea2e1610fb8)
- Automate the mechanical half of the action-pin cycle in [e767762e](https://github.com/alexhawat/mergeCraft/commit/e767762e2c02b26619cd03240e1d1020c6dc06e5)
- Upload actionlint, zizmor, semgrep SARIF; skip trufflehog in [4dfe72df](https://github.com/alexhawat/mergeCraft/commit/4dfe72df94e14a2a233df90c980bcecd791933e8)
- Ingest CI SARIF on green wait-for-ci in [e52be85f](https://github.com/alexhawat/mergeCraft/commit/e52be85fbd33c700076cb797f398da4e31118625)
- Wire action pin gate and digest-pin Action image in [#532](https://github.com/alexhawat/mergeCraft/pull/532)
- Ingest CI SARIF as review evidence in [95b11c75](https://github.com/alexhawat/mergeCraft/commit/95b11c757652ee0c5487cf871235cba20195c636)

#### Cli

- Expand jev help and save TYPESAFE_API_KEY in [0dfc5a07](https://github.com/alexhawat/mergeCraft/commit/0dfc5a074594d880e35824d93a7e3d7c242043b4)
- Add mergecraft jev enable/disable/status/set in [ff580acf](https://github.com/alexhawat/mergeCraft/commit/ff580acfd5d8776a7fb6adcfbaa011d30e3cce72)
- Open TTY sessions for bare commands in [f5187aeb](https://github.com/alexhawat/mergeCraft/commit/f5187aebad6d91ae7bccc1985146d4616d709fa4)
- Run local coverage and mutation on trusted CLI in [c1d9ded0](https://github.com/alexhawat/mergeCraft/commit/c1d9ded0e0a1f318ab6f56e506e78bff43393a18)
- Add verify-behavior reproduce and verify in [fe4d1581](https://github.com/alexhawat/mergeCraft/commit/fe4d15810e91f8b7ced8b9ce65e19dafe3ed7225)
- Apply self-review on the default branch in [db0c76b6](https://github.com/alexhawat/mergeCraft/commit/db0c76b6beba6c5028214b9a6dcc378df29b377c)
- Add provider status roster view with --github in [#520](https://github.com/alexhawat/mergeCraft/pull/520)
- Seed reviewer p0 on first provider auth (W8) in [c434d3a6](https://github.com/alexhawat/mergeCraft/commit/c434d3a601f420e3e933646e80af12139207fae5)
- Fail closed on unwired roster providers (W7) in [2f73d462](https://github.com/alexhawat/mergeCraft/commit/2f73d46259bd90bedb992aa05a3927ae3d5e48e2)
- Add mergecraft agent-local with layered config precedence in [86062fd7](https://github.com/alexhawat/mergeCraft/commit/86062fd79c5216656973a179c0f74252e79ec676)
- Add mergecraft agent roster authoring commands in [c84f7378](https://github.com/alexhawat/mergeCraft/commit/c84f73787337b76e3cb7a3313ab8889a67a81bf1)
- Add provider enable/disable toggle in [4db613d8](https://github.com/alexhawat/mergeCraft/commit/4db613d89182ed06b0835ff63070665edecf86a9)
- Workflow provider/model authoring in [8f8a89d8](https://github.com/alexhawat/mergeCraft/commit/8f8a89d83e2d6b292446b8e36ebf596ef782f897)
- Provider migrate and enforce config/secret split in [1cfae377](https://github.com/alexhawat/mergeCraft/commit/1cfae377f5a0fd77ed5e5bbf8ec0518df1d6710e)
- Agents setmodel and addbackupmodel in [1baa9f9d](https://github.com/alexhawat/mergeCraft/commit/1baa9f9d9258faf63b88131fc516c400fce73177)
- One provider auth command in [4768ad80](https://github.com/alexhawat/mergeCraft/commit/4768ad80af174cdcc064a26e9e0d7eb755002923)
- Model add/list/delete per provider in [227d53c1](https://github.com/alexhawat/mergeCraft/commit/227d53c1529e1841784d9893325fb3cfc013d20f)
- Provider add/list/edit/delete in [694164c5](https://github.com/alexhawat/mergeCraft/commit/694164c560d13b499878dec9b3e9ae59c3822c86)
- Add mergecraft update and commit in --version in [ccaed262](https://github.com/alexhawat/mergeCraft/commit/ccaed262c3ac7fa0b1ef4de3623108581a8a0ed6)
- Add --output-format hunk in [494416c3](https://github.com/alexhawat/mergeCraft/commit/494416c367d49410974872dde56c0f6485f24976)

#### Config

- Read tracing settings through typed env models in [8476c8d0](https://github.com/alexhawat/mergeCraft/commit/8476c8d020a41d48cce66d0382755a633c516842)
- Add typed env package and one .env reader in [fe0137e0](https://github.com/alexhawat/mergeCraft/commit/fe0137e0955eedbb84b82a91c781bcfb615112ab)
- Add operator trust knob for self-review (W9) in [00f46afe](https://github.com/alexhawat/mergeCraft/commit/00f46afed93f5379ff7bacc77ddd30720e8de14c)
- Add agent roster slot primitives and load/write in [b48067ac](https://github.com/alexhawat/mergeCraft/commit/b48067acd5e949fa97fee968177341c09b07867c)

#### Evals

- Replayable multi-round cases, harvest recipe, sourcing and spike kits in [97461241](https://github.com/alexhawat/mergeCraft/commit/974612418e444db92cc3693fa89f6ee744106d2a)
- Generalise human batch to a declared id and case list in [dfda9c0a](https://github.com/alexhawat/mergeCraft/commit/dfda9c0a387949dce0081cb97216d1839832c1bd)
- Enforce the trajectory gate from an approved protocol in [fcbb498f](https://github.com/alexhawat/mergeCraft/commit/fcbb498ff47f958f6fab74753f83a9102f4ea6ec)
- Add benchmark publication validation in [e79fdeec](https://github.com/alexhawat/mergeCraft/commit/e79fdeec4fe8cbd41bac18979b520997e690a924)
- Score trajectory auditor labels in [7d384ac9](https://github.com/alexhawat/mergeCraft/commit/7d384ac9acc02e9245e2ae1101f70916943ff5b6)
- Add offline judge calibration protocol in [ddd442d3](https://github.com/alexhawat/mergeCraft/commit/ddd442d3003ddc7f547cfd4a0e356d5d92291e7a)
- Prepare human golden review batch in [ec2481f6](https://github.com/alexhawat/mergeCraft/commit/ec2481f60a3de6d181740860e86e51316cfec130)
- Ingest flywheel cases with mandatory provenance in [#738](https://github.com/alexhawat/mergeCraft/pull/738)
- Approve and record who adjudicates a corpus label in [2e2e3151](https://github.com/alexhawat/mergeCraft/commit/2e2e3151640375522cbc2d901594510f1fd69600)
- Withhold the word calibrated from unadjudicated corpora in [edf66f4c](https://github.com/alexhawat/mergeCraft/commit/edf66f4cf07ed89bf82ac2ea29374e96f421155c)
- Lift J2 cost caps and faithfulness alerts to all providers in [01ba793a](https://github.com/alexhawat/mergeCraft/commit/01ba793a345ef9da5e9d95421e3cd94977b62352)
- Add review-skill drift gates and corpus harness for RS4 in [2bed6014](https://github.com/alexhawat/mergeCraft/commit/2bed60144de369a19c9a0731e5b21f4f4fcf2953)
- Emit per-lens capability numbers in [e0a48d9f](https://github.com/alexhawat/mergeCraft/commit/e0a48d9f1a0298df94b5031ee9336dba2e1100bd)

#### Evidence

- Record driver-native exec; make unread-file advisory in [a1c24fc7](https://github.com/alexhawat/mergeCraft/commit/a1c24fc749a3fa21e2462fdaed76926667c7eb99)
- Add a second shadow target and comparison job in [#737](https://github.com/alexhawat/mergeCraft/pull/737)
- Classify trajectory failures before counting in [09f82f47](https://github.com/alexhawat/mergeCraft/commit/09f82f478e133524c659a5c90e0c34a7f6721a40)

#### Findings

- Add scope axis and unified blocking predicate in [bf24f882](https://github.com/alexhawat/mergeCraft/commit/bf24f88256b5105da5b16ae2b493298f805215ca)
- Render a stable short finding id in [20cc4b51](https://github.com/alexhawat/mergeCraft/commit/20cc4b51d8747924ae142823ff253aab3d851d8d)

#### Jev

- Implement architecture checklist across TypeSafe paths in [a2367ca2](https://github.com/alexhawat/mergeCraft/commit/a2367ca22fcfc3d6071b360c53398f3ac44b9b6a)
- Wire review-path skip, packs, and shadow dispatch in [4ad8c098](https://github.com/alexhawat/mergeCraft/commit/4ad8c09861e673f9dd138110ebab6a5ab823aba3)
- Lens routing and escalate-only alignment in [83ab6fc9](https://github.com/alexhawat/mergeCraft/commit/83ab6fc9ab8fcf713e9d22ae027314893531c4ce)
- Parallel judge with evidence and claim packs in [26a9c6fc](https://github.com/alexhawat/mergeCraft/commit/26a9c6fc4c8d3fd60c404af0ca1545271d82925a)
- Hunk battery, ratchet, and shadow policy in [9b0fb326](https://github.com/alexhawat/mergeCraft/commit/9b0fb326af46dd8bc6020c43c1d8f1aab4b8b8e0)
- Async pinned client with cost, trace, kill-switch in [5373658d](https://github.com/alexhawat/mergeCraft/commit/5373658d17401f2b011b7c16d4e9ae398674c3ab)

#### Mcp

- Tell the agent its elapsed time once past 60% of the deadline in [b331e5c7](https://github.com/alexhawat/mergeCraft/commit/b331e5c725a75aaed586402eba4308c1bd214aa3)
- Allow git grep and ls-tree behind a pager-exec guard in [d3f6154f](https://github.com/alexhawat/mergeCraft/commit/d3f6154fbfa444c9e2fe2a7d325c1731f08ca973)
- Degrade checkout to api-only scope on fetch failure in [d625ff4a](https://github.com/alexhawat/mergeCraft/commit/d625ff4a76178be2069f51979be199ffc84fcc30)
- Allow read-only git verbs and PR number aliases in [ebfdcc4f](https://github.com/alexhawat/mergeCraft/commit/ebfdcc4f22509671245817407b331dd33daf8a29)
- Generate server.json and registry CI check in [18be2bc6](https://github.com/alexhawat/mergeCraft/commit/18be2bc6544a92c2bf81d67dc40fc11e0d7c519f)
- Add stdio transport for public profile in [2b75570a](https://github.com/alexhawat/mergeCraft/commit/2b75570a8eb2302e229bdd766780df83d7f8384c)
- Public role with six semantic tools in [bb0a3bae](https://github.com/alexhawat/mergeCraft/commit/bb0a3bae79e4e8f1750069fe3bf953e8549736c6)

#### Opencode

- Isolate review runs and trace inside OpenCode sessions in [f3ac2ce7](https://github.com/alexhawat/mergeCraft/commit/f3ac2ce7c33b065514be12a8fe54894e53ceebd0)
- Ship OpenCode 2.x and drive it through opencode run in [c6136fe1](https://github.com/alexhawat/mergeCraft/commit/c6136fe19e8333382e6e39ee0a49a2cf4a568e90)
- Add plugin, installer CLI and Logfire tracing in [e3ad5ebe](https://github.com/alexhawat/mergeCraft/commit/e3ad5ebead718f0b51ef0b4778d42aade459debb)
- Add first-class OpenCode integration assets in [143f805c](https://github.com/alexhawat/mergeCraft/commit/143f805c2db2a5a010195fea3eaf98fdf2d4889a)

#### Review

- Read the diff first and cover large PRs by line range in [7156014a](https://github.com/alexhawat/mergeCraft/commit/7156014a86a1bb128cb0b2623c52c53fde15bdef)
- Report code-measured LLM review generation time in [a63ef122](https://github.com/alexhawat/mergeCraft/commit/a63ef1227c285a6b7b37c0aa4d6ed757f165676e)
- Publish input and output token counts separately in [c1b9364d](https://github.com/alexhawat/mergeCraft/commit/c1b9364d078b0a8fea09ef4914921a9b0dd853dc)
- Show input and output token counts separately in [34ff66ee](https://github.com/alexhawat/mergeCraft/commit/34ff66ee6870a929b6e1a24c620a0eafc95bcb5d)
- Surface Jev questions and answers in the review body in [f4cdb5b6](https://github.com/alexhawat/mergeCraft/commit/f4cdb5b6c013f51997506001f12872d4259b30c9)
- Consume fenced behaviour-verification reports in [b50fec56](https://github.com/alexhawat/mergeCraft/commit/b50fec56546c7d5d50cf62e33a7dcb46f7845a2f)
- Load Copilot-style skills and MCP at review in [98b1be87](https://github.com/alexhawat/mergeCraft/commit/98b1be87df0d30d763fc8441930bcea19f001c0b)
- Persist completed reviews by id in [4ea02718](https://github.com/alexhawat/mergeCraft/commit/4ea02718a6f99a2097145452b9ecc5c53bab5893)
- Surface deferred findings and measure first-pass recall in [726808f2](https://github.com/alexhawat/mergeCraft/commit/726808f2bc55e57aefccb5c8ccee2aafbcb4b601)

#### Review Record

- Add run_health packet, step summary, and artifacts in [f34b2ef4](https://github.com/alexhawat/mergeCraft/commit/f34b2ef482cde4bd5aa0415c8c3932fc0974f2d4)
- Survive anchor 422 with pre-validation in [#530](https://github.com/alexhawat/mergeCraft/pull/530)
- Add deterministic sticky comment and preamble in [3a03993e](https://github.com/alexhawat/mergeCraft/commit/3a03993e98cad8ae238453232a1d2a40d0bb0ac0)

#### Skills

- Author code-review doctrine payload for RS3 in [99ce63dc](https://github.com/alexhawat/mergeCraft/commit/99ce63dc5203f6ff2a819363810a5f49b2c76e44)
- Add GitHub Copilot as an Agent Skills harness in [2e07c780](https://github.com/alexhawat/mergeCraft/commit/2e07c78063c6656283992068b91909a751b72a7e)
- Add grok-bot harness and document mergeCraft bot in [f17f2c3c](https://github.com/alexhawat/mergeCraft/commit/f17f2c3c87a45cb8eb83ac53b21f89f132e58977)

#### Trust

- Gate the sandbox override on an author allowlist in [8806c5b5](https://github.com/alexhawat/mergeCraft/commit/8806c5b53ab9feb18867228058145e346dfe1c4b)
- Export Logfire token env seam for #551 in [b3348397](https://github.com/alexhawat/mergeCraft/commit/b33483977d198343c385b47daa6d2e7322211c0e)
- Consolidate credential probe for #552 in [a9c1c541](https://github.com/alexhawat/mergeCraft/commit/a9c1c541fbff202c8d19d45ecb81adcbc80ada8e)
- Gate Codex sandbox override on agentSandbox policy in [2c1c0d0f](https://github.com/alexhawat/mergeCraft/commit/2c1c0d0f66607c8cca1ff55fa10f46aba503c3d0)

#### Verify

- Wire the live CDP driver and the JEV criterion seam in [#752](https://github.com/alexhawat/mergeCraft/pull/752)
- Launch Playwright when browser extra is present in [d37ad1d0](https://github.com/alexhawat/mergeCraft/commit/d37ad1d0404e358eb5c4d81aef9c0aea13da907d)
- Add browser driver protocol and extra in [9f183938](https://github.com/alexhawat/mergeCraft/commit/9f183938b00d684fd46ce13c27783ad8004681e2)
- Add versioned behaviour-report contract in [51cdb0c2](https://github.com/alexhawat/mergeCraft/commit/51cdb0c29727ad5385f7db1505b811efce011b5a)

#### Other

- Wrap Action phases in gha_log groups in [69d97146](https://github.com/alexhawat/mergeCraft/commit/69d971461f0a924e953fc72cf31b35b44a3e85d9)
- Bind App approvals to workflow provenance in [a5b28fe3](https://github.com/alexhawat/mergeCraft/commit/a5b28fe3e75cadeff6aecd9b293431d012ee0c8b)
- Write audit.jsonl for audit export in [c64defb5](https://github.com/alexhawat/mergeCraft/commit/c64defb535bf1284fe2fd11e47f2261206011b6a)
- Give review prompts a time budget and a code-reading rule in [7103a2d3](https://github.com/alexhawat/mergeCraft/commit/7103a2d33c9807fcb1784f2202015e4d50e6e9da)
- Add Ultramarine 1 Flash catalog, cost, and second reviewer in [#983](https://github.com/alexhawat/mergeCraft/pull/983)
- Implement loopback credential broker (W2) in [d087cd6a](https://github.com/alexhawat/mergeCraft/commit/d087cd6aeab2f907e3401270e8fd0de5433469a6)
- Derive truthful packet-bound check summaries in [38851e9b](https://github.com/alexhawat/mergeCraft/commit/38851e9be8a32cff70058485a0e02c9b07c8efe0)
- Make review traces readable in Datadog LLM Observability in [05c16d51](https://github.com/alexhawat/mergeCraft/commit/05c16d5139bbec28e7e3d7eb454fecc53a88512d)
- Serialise logging and harden gh secret writes (W6) in [8c18875e](https://github.com/alexhawat/mergeCraft/commit/8c18875ebc22e32e2c6dac750a6adfaef85e56fd)

### Fixed

#### Action

- Surface pin vs image source on the run record in [1b56d00b](https://github.com/alexhawat/mergeCraft/commit/1b56d00bc29dfd85b1c5b384d5746b430a9a3487)
- Select verified image for merged audit fixes in [492684ed](https://github.com/alexhawat/mergeCraft/commit/492684edcadd06aa99c3d15a12d162a15828ee38)
- Align slim digest with GHCR for 2a943ce9 in [c26f603a](https://github.com/alexhawat/mergeCraft/commit/c26f603a6579d1f811ffeb841a01ae8932b9beeb)
- Digest for Action SHA 55269319 in [2a943ce9](https://github.com/alexhawat/mergeCraft/commit/2a943ce9724e454944dabf695f2eab2c676b3dcb)
- Bump slim image digest for Action SHA 16ce044 in [21a9e1be](https://github.com/alexhawat/mergeCraft/commit/21a9e1becb3c34f3e120b717aee06abba3c115e3)

#### Agent Roster

- Inject OpenCode dispatch without opencode.py edits in [484040d2](https://github.com/alexhawat/mergeCraft/commit/484040d26677a80f1c151c226278a4f669fdf0cd)
- Thermos turn-3 CQ fixes for roster dispatch in [92351a25](https://github.com/alexhawat/mergeCraft/commit/92351a2551278c95147db9040204c504aa98e022)
- Wire roster merge path and Thermos audit fixes in [e5ccf055](https://github.com/alexhawat/mergeCraft/commit/e5ccf0559ca07ca19d04fb673e830cb881dee406)

#### Agents

- Only a subscription-login run can report an expired credential in [5638e256](https://github.com/alexhawat/mergeCraft/commit/5638e256465f723bf00d4e200f03bf9841f8d2f5)
- Anchor Claude deny rules and land verdict capture in [3d4e99fe](https://github.com/alexhawat/mergeCraft/commit/3d4e99fee80eb8a06be6281f2e2379cc3da0ac25)
- Harden the stderr drain and null-sink seam in [69f8a950](https://github.com/alexhawat/mergeCraft/commit/69f8a9501303dcfaae4b14b474e1f1967ae533e8)
- Deny write and web tools to the claude reviewer in [7ef79e7d](https://github.com/alexhawat/mergeCraft/commit/7ef79e7de7a1e12a1bc2d0a4bcd854fb3c468e9e)
- Bound opencode boot and stop reposting live prompts in [81715b5c](https://github.com/alexhawat/mergeCraft/commit/81715b5cf9f939766b722c0bef06d7759031bb7c)
- Drain agent stderr while streaming stdout in [ae93f1bc](https://github.com/alexhawat/mergeCraft/commit/ae93f1bcead0babf2d1a1ec099db4f14e4aaf933)
- Stop Action crash from token_budget circular import in [a7427d52](https://github.com/alexhawat/mergeCraft/commit/a7427d52a99250df2f8b35e1d38863219ef7ed66)
- Route Codex via openai_base_url for broker in [82a59867](https://github.com/alexhawat/mergeCraft/commit/82a59867803b2350039264de299aa63e6068a074)
- Route Codex via openai_base_url for broker in [0dca6a9f](https://github.com/alexhawat/mergeCraft/commit/0dca6a9f653e544d29b368941c1f8a4cbd462da0)
- Pass --verbose so claude accepts stream-json in [efcb0d4a](https://github.com/alexhawat/mergeCraft/commit/efcb0d4a3aad3a2227ee0cbdd8296825b98ef8f9)
- Surface bubblewrap failures and pin analyzers (W8) in [519a2f3b](https://github.com/alexhawat/mergeCraft/commit/519a2f3b640183686d963c8764bb2e65647c1555)
- Say why a claude run parsed no events in [7cb77881](https://github.com/alexhawat/mergeCraft/commit/7cb77881b165b73c8258eae173d432cd0ff09a95)
- Hash the checkout after mergeCraft's own config write in [0815b574](https://github.com/alexhawat/mergeCraft/commit/0815b5743aaf8acd161b27dee3434ebd30b7a69a)
- Degrade follow-on span harness inference failures in [95d24dff](https://github.com/alexhawat/mergeCraft/commit/95d24dff323d22556b1c7155317157cff0873c49)
- Honour legacy gateway creds for seeded providers in [28828045](https://github.com/alexhawat/mergeCraft/commit/288280451776857b6bf9408d1b25e468386a4798)
- Restore indexed provider keys and nous failover in [84cb8d05](https://github.com/alexhawat/mergeCraft/commit/84cb8d05066beba80dea3ed4fcaaca719416c3e3)
- Honor legacy NOUS_API_KEY in resolve_runtime_agent in [421fd9ed](https://github.com/alexhawat/mergeCraft/commit/421fd9edb0f011865f9cc4bc51ab90c8dc6fd14a)
- Honor indexed credentials for built-in providers in [9123856b](https://github.com/alexhawat/mergeCraft/commit/9123856b9b4d3c15f7f67fca8f7d36762402d298)
- Treat transient Nous 404 as retryable in [453e8b02](https://github.com/alexhawat/mergeCraft/commit/453e8b02fb37f25883c691a75238ac1781bb697b)
- Cover the initial opencode prompt with the timeout handler in [5e4ef8a6](https://github.com/alexhawat/mergeCraft/commit/5e4ef8a65c6620c55d7ea9ddc8497f71ec1bf4bb)
- Give retryability a single decision path in [7e9f14ec](https://github.com/alexhawat/mergeCraft/commit/7e9f14ec5834bf7b1446c1ace7b0bfd5c1011efd)
- Capture codex error and turn.failed events from stdout in [97d740a1](https://github.com/alexhawat/mergeCraft/commit/97d740a19ce2e65858d8fc9f52144950c2d7c027)
- Classify provider quota exhaustion as retryable in [e563765f](https://github.com/alexhawat/mergeCraft/commit/e563765f1bd0d4469291244a73a39442e1973b89)
- Drain opencode serve pipes for the process lifetime in [43577ef2](https://github.com/alexhawat/mergeCraft/commit/43577ef24ccdbe8d0f1e183f87dc51b2563612c9)
- Let a provider timeout fail over instead of killing the run in [d33ff241](https://github.com/alexhawat/mergeCraft/commit/d33ff2412450dd9bb8918e09a7fa95e2b06adf32)

#### Analyzers

- Keep baseline suppression on; catch two config loosenings in [9961716d](https://github.com/alexhawat/mergeCraft/commit/9961716df73ebc3c802ff05a931c0823895059d8)
- Close the five findings from the #1017 review in [3fe13712](https://github.com/alexhawat/mergeCraft/commit/3fe13712c1d2cc704da1c98cb41f6f6534a6431e)
- Close the four findings the review raised on #1017 in [3e9c9406](https://github.com/alexhawat/mergeCraft/commit/3e9c9406750df4e21941d66fec5591ed8ae98c54)
- Trufflehog markers count in prose, as the scanners do in [94c617a4](https://github.com/alexhawat/mergeCraft/commit/94c617a4fcee2e73908388a93b537fa7ece766b8)
- Drop trusted catalog analyzers to the agent UID in [5a3376d0](https://github.com/alexhawat/mergeCraft/commit/5a3376d0ab28c7685272c3a8c4d3318225653dec)
- Confine agentsec reads, keep token counts, fail closed in [681e58cd](https://github.com/alexhawat/mergeCraft/commit/681e58cd6989d8bb238416ffb47e782538670064)
- Honour an explicit zero inline budget in [f7af3ea0](https://github.com/alexhawat/mergeCraft/commit/f7af3ea0ddc2c99b416356f3294911d83bbbfde6)
- Stop trusting checkout caches and misplacing findings in [4e4f7526](https://github.com/alexhawat/mergeCraft/commit/4e4f7526910b05f46b3d0364f892c77450388515)
- Scope diff headers and label out-of-root SARIF paths in [37354f7a](https://github.com/alexhawat/mergeCraft/commit/37354f7a28620eb402e54938ae06d2fcb9c294d8)
- Provision from a trusted root and harden the lockfile in [f5789370](https://github.com/alexhawat/mergeCraft/commit/f5789370c65f797bb0855c06c4a5549c98bd6d8b)
- Preserve provisioning failure causes in [0edae3fb](https://github.com/alexhawat/mergeCraft/commit/0edae3fbc3dba3073280b51428bd851d68ec0422)
- Keep the CDP remedy flag readable through redaction in [b1feae65](https://github.com/alexhawat/mergeCraft/commit/b1feae65f480330a2109c225b44be7bd437f6563)
- Require exact trufflehog fixture paths in [745fcd93](https://github.com/alexhawat/mergeCraft/commit/745fcd935b059d5a32db255cf7828b9185a65b20)
- Pin darwin-arm64 trivy to native ARM64 in [56aa1caa](https://github.com/alexhawat/mergeCraft/commit/56aa1caa2b40160e41496d2830c9306e8b11953c)
- Keep MD060 off without a markdownlint config in [401a6a41](https://github.com/alexhawat/mergeCraft/commit/401a6a4131124031d347cdf94918cb90c8b54252)
- Degrade unknown markdownlint severities per finding in [41e3cf37](https://github.com/alexhawat/mergeCraft/commit/41e3cf37ef3e92828442cd84b070ca448327259d)
- Follow the markdownlint engine bump through the catalog in [661de399](https://github.com/alexhawat/mergeCraft/commit/661de3992c49cdf4b349073320ce1ab9331ec36a)
- Close the relay bypass and the seven other review findings in [7f21a7d0](https://github.com/alexhawat/mergeCraft/commit/7f21a7d05ffe641201f139df9db54a7873b16950)
- Build well-formed iptables deletes in the orphan sweeper in [0f4cedd5](https://github.com/alexhawat/mergeCraft/commit/0f4cedd5837e187fb9bc86c519105cfe7b1d5f53)
- Enforce filtered egress without host net admin in [24ef9bf2](https://github.com/alexhawat/mergeCraft/commit/24ef9bf266b05ff9f2d683acdc9c4bd5fa37e3a0)
- Kill namespace children after analyzer timeout in [1c975974](https://github.com/alexhawat/mergeCraft/commit/1c975974177e719967d7d7b340c040724239d385)
- Isolate privileged bootstrap from payload env in [d1e06ef8](https://github.com/alexhawat/mergeCraft/commit/d1e06ef86071dad08ba6d77bf473971a1ecbfc1c)
- Harden experimental egress isolation boundaries in [44742a7b](https://github.com/alexhawat/mergeCraft/commit/44742a7bf76e4c199c24a861ce122f59a21d207b)
- Close PR #606 review findings in filtered egress in [5365644c](https://github.com/alexhawat/mergeCraft/commit/5365644cab468f58e5ed1ac190bf88c6c8682251)
- Filter untrusted analyzer egress in [#538](https://github.com/alexhawat/mergeCraft/pull/538)
- Close PR #606 review findings in filtered egress in [f4bfded8](https://github.com/alexhawat/mergeCraft/commit/f4bfded84722f0a6af91fa17b31ac528fc351fbd)
- Trust push events for analyzer egress in [d7d2f641](https://github.com/alexhawat/mergeCraft/commit/d7d2f641bb2b15ee0fa23fb0b2114acb5ea398fb)
- Narrow entropy redaction for proven benign shapes in [#537](https://github.com/alexhawat/mergeCraft/pull/537)
- Keep egress for analyzers that declare a network allowlist in [fe606960](https://github.com/alexhawat/mergeCraft/commit/fe606960099d6c49a75713275b99c8cb5b642f6b)
- Tighten entropy redaction without mangling metadata in [7652ede6](https://github.com/alexhawat/mergeCraft/commit/7652ede6eed6395aef3c614e213b2f7192f0c47f)
- Stop duplicating inline findings in mechanical sections in [92a4e02f](https://github.com/alexhawat/mergeCraft/commit/92a4e02f5ee650ecd38af3a4f01d305da9d1695a)
- Demote inline findings without short ids in [b9ba1e27](https://github.com/alexhawat/mergeCraft/commit/b9ba1e2715ed80866223dd890c5ce9d64671f94c)
- Fail-soft short-id on render path in [759f0068](https://github.com/alexhawat/mergeCraft/commit/759f006891c3449d6f0469f55ad85058699a56b4)
- Resolve repo-native tools from .venv-dev in [a91b51c4](https://github.com/alexhawat/mergeCraft/commit/a91b51c4da3338f2de4e98eba5640d6096f91211)
- Structural JSON redaction and length-relative entropy in [c0ef2262](https://github.com/alexhawat/mergeCraft/commit/c0ef2262a86920b9f1ee77e6f2a3c3b8c194dae2)
- Distinguish skipped catalog from a clean scan in [202f9810](https://github.com/alexhawat/mergeCraft/commit/202f9810325b30574ac48135d6a990f2d951a7ab)
- Parse empty bandit JSON as a clean scan in [fa314cf6](https://github.com/alexhawat/mergeCraft/commit/fa314cf6769e16f1a9464e8c556dda0d6cdaca3e)
- Reject placeholder provenance pins in [19822573](https://github.com/alexhawat/mergeCraft/commit/19822573951215bb450bada55c87882b99123214)
- Never resolve a repo-native tool from arbitrary PATH in [e66f8826](https://github.com/alexhawat/mergeCraft/commit/e66f8826c83a3c15b10277e1a12f66c42b95e5fd)
- Ignore literal args in pass-through-wrapper in [43576cba](https://github.com/alexhawat/mergeCraft/commit/43576cba1d75199236af6b705917ecf3ce2a213f)
- Slice antislop snippets by decoded text in [0d7c20f3](https://github.com/alexhawat/mergeCraft/commit/0d7c20f3a1f742c90402de2f4b48984370f85d87)
- Match Python empty/obscuring except blocks in [b278a01f](https://github.com/alexhawat/mergeCraft/commit/b278a01fd1bc8ba174b734105b3755dadcaf19c7)

#### Auth

- Isolate privileged approval behind maintainer dispatch in [2acacaf4](https://github.com/alexhawat/mergeCraft/commit/2acacaf408ada9c824b8a41c99e91031f790864f)
- Bind approval API calls to the minted App token in [a1fdd25f](https://github.com/alexhawat/mergeCraft/commit/a1fdd25f189c250d649f4d042340e3513ee081ae)
- Reserve self-review approvals for the isolated job in [e02f186a](https://github.com/alexhawat/mergeCraft/commit/e02f186a732db44aab8adc436b59304b20b52460)
- Carry reviewer identity across App fallback in [595963aa](https://github.com/alexhawat/mergeCraft/commit/595963aaa66ce192381bb4f9d4145ab0dcfb1feb)
- Pass pretty JSON verbatim to gh secret set in [f46e1688](https://github.com/alexhawat/mergeCraft/commit/f46e1688f458979d23265934f34101be02da1466)

#### Authority

- Thermos round-2 remediation in [c5cab784](https://github.com/alexhawat/mergeCraft/commit/c5cab784d7150440a699e3bad750eac3cf15a0cf)
- Thermos round-2 remediation in [b7edba1d](https://github.com/alexhawat/mergeCraft/commit/b7edba1dd3bd4b20c7010b54c2ab6195195cc2bd)
- Thermos round-1 remediation in [f01301ed](https://github.com/alexhawat/mergeCraft/commit/f01301edadf9230f9bdfafc4f10b332c09781a5a)
- Thermos round-1 remediation in [714792a0](https://github.com/alexhawat/mergeCraft/commit/714792a0bb86715e4ad64349921710345f01687d)
- Reconcile AG1.1 snapshot tests for AG2 close-out in [c5c6aba2](https://github.com/alexhawat/mergeCraft/commit/c5c6aba27717eca0403745b6814ce34013130b5f)

#### Ci

- Register OpenCode Go at provider slot 9 in [729c78a6](https://github.com/alexhawat/mergeCraft/commit/729c78a63918b5b67047c13e21a0f4e9328da772)
- Describe a passing base without asserting attribution in [11018a1f](https://github.com/alexhawat/mergeCraft/commit/11018a1f79c8a68d81223649cfb301c992aaca36)
- Report unattributed CI failures instead of exonerating them in [abcadaff](https://github.com/alexhawat/mergeCraft/commit/abcadaff69da17fa20feba87ada2194ea768265e)
- Call a failure pre-existing only when the base failed in [fca42d30](https://github.com/alexhawat/mergeCraft/commit/fca42d30553964a9e014ec6401dc351d262d0dff)
- Extract failure paths only from failure context in [03e8898b](https://github.com/alexhawat/mergeCraft/commit/03e8898ba92b981683545baabe180ba5b93da59e)
- Keep the Jev key out of the review rungs' environment in [8943adab](https://github.com/alexhawat/mergeCraft/commit/8943adab61f1b4505bc2d371643b98b3b04091ab)
- Pass the Jev credential to each review rung in [97fb2fde](https://github.com/alexhawat/mergeCraft/commit/97fb2fdedf0b368eb1fe0840b67e9f17baf2fca2)
- Reject coverage metadata drift in [157f57a3](https://github.com/alexhawat/mergeCraft/commit/157f57a3d49a662433f6a5f678025d6ec45a52e4)
- Enforce actual module line coverage in [0b804ab8](https://github.com/alexhawat/mergeCraft/commit/0b804ab84bf5345c9dc95d517beb883ee4dc5068)
- Use mutmut interpreter and merge setup.cfg in [74de1ba4](https://github.com/alexhawat/mergeCraft/commit/74de1ba4c253b4cf1ce8bd168fb625b9fba7b9a7)
- Cap mutmut execution at max_mutants keys in [5644fd0c](https://github.com/alexhawat/mergeCraft/commit/5644fd0cff23064703db26b13108f5e48e480552)
- Invoke mutmut via supported selection config in [6c5c9bd4](https://github.com/alexhawat/mergeCraft/commit/6c5c9bd4087db29ef9b10e99b481fc03caf3b686)
- Skip ambiguous single-row duplicate coverage in [6c8ceb4a](https://github.com/alexhawat/mergeCraft/commit/6c8ceb4af65c89ce67dfc690d4cd4a0052feee77)
- Disambiguate duplicate method evidence by start line in [2140d92a](https://github.com/alexhawat/mergeCraft/commit/2140d92ae8c040a00646e67b1c2aed020a9cb87e)
- Close coverage/mutation ingest review holes in [b3d0eae9](https://github.com/alexhawat/mergeCraft/commit/b3d0eae9c664f04916a93078e334b90763745c5b)
- Fail-closed coverage and mutation evidence ingest in [ce71359d](https://github.com/alexhawat/mergeCraft/commit/ce71359d49335e4d586b91beefb183907575e89d)
- Pass check_runs into intelligence ingest in [bc253697](https://github.com/alexhawat/mergeCraft/commit/bc2536974275974ccc493b15216038cc3f9bce2d)
- Parse Cobertura with defusedxml in [04128b4f](https://github.com/alexhawat/mergeCraft/commit/04128b4f29eac23741e51efbd160edebb31f54eb)
- Resolve the current digest introduction, not the earliest in [e7b202c6](https://github.com/alexhawat/mergeCraft/commit/e7b202c69a04dcbd84dddfd8d22a0bd8e854b7f7)
- Verify the commit that introduced the digest, not the candidate head in [7a3f3022](https://github.com/alexhawat/mergeCraft/commit/7a3f30224a92510fd65cb5e887933d23bb143b02)
- Accept an image digest inherited through a merge in [85621bf1](https://github.com/alexhawat/mergeCraft/commit/85621bf1df1242367cd4129051fc0f611fe07ffb)
- Do not resolve the image from main's tip in the pin stage in [5ea310fa](https://github.com/alexhawat/mergeCraft/commit/5ea310fa5d70f7b8afda67a75bc9985ec327db49)
- Pass -r explicitly to the combined diff in [699c0ec6](https://github.com/alexhawat/mergeCraft/commit/699c0ec6b6629d5b71d28cf0a14f6346fa43911c)
- Count conflict-resolution merges toward the staleness budget in [818f587e](https://github.com/alexhawat/mergeCraft/commit/818f587e7b35f2c511a4cc4b10a5e034325f0a46)
- Count changes, not landings, in the pin staleness budget in [9c63ec1c](https://github.com/alexhawat/mergeCraft/commit/9c63ec1ce8dd81e8fa21ca2452f9740eb0cb7362)
- Guard the staleness job to main and report on push in [569582fc](https://github.com/alexhawat/mergeCraft/commit/569582fc870d713118a01c20972db7307ddc657e)
- Move Action-pin staleness off the required PR gate in [f78306c0](https://github.com/alexhawat/mergeCraft/commit/f78306c0a8fda5f3f3a687f0e60dd49c13c00ab1)
- Preserve integration matrix after workflow consolidation in [5a30b000](https://github.com/alexhawat/mergeCraft/commit/5a30b000ed301b8378651a3ec0483e097e9ced09)
- Scope live smoke credentials to the selected provider in [1ca57019](https://github.com/alexhawat/mergeCraft/commit/1ca57019a74da42a4812e9850d9e0d5eeb0ad306)
- Scan images for every supported pull request in [ca61ce93](https://github.com/alexhawat/mergeCraft/commit/ca61ce9315124c0e932ae0fb704f992d047e80fd)
- Give the live smoke its unprivileged home in [0659545b](https://github.com/alexhawat/mergeCraft/commit/0659545b132e6d928147972f48edbc93a6e00139)
- Bind App check provenance to the GitHub server in [32f82fc7](https://github.com/alexhawat/mergeCraft/commit/32f82fc72f36a7f059ac94ad6ee9840d2ea0323e)
- Rebuild actionlint with patched Go runtime in [bd68d59f](https://github.com/alexhawat/mergeCraft/commit/bd68d59f3f94e9af27a3817123ceaa7a79f9ce6e)
- Apply dependency patch with bundled git in [55877eee](https://github.com/alexhawat/mergeCraft/commit/55877eeee79356a9901d72d02f7eb32c4d9136db)
- Remediate image tooling and scan before release in [bd69c4f9](https://github.com/alexhawat/mergeCraft/commit/bd69c4f91c7f2b4e515d84d06bffc6f327558e35)
- Verify release provenance before action pin promotion in [e6739a1c](https://github.com/alexhawat/mergeCraft/commit/e6739a1c43dc1758f4cbe91f15c2ef7f9ecf49b8)
- Fail trufflehog SARIF conversion on an error-level scan log in [91d3dcef](https://github.com/alexhawat/mergeCraft/commit/91d3dcef11ca8135d2cbb88e62fe07486ee73a15)
- Use trufflehog --exclude-paths on filesystem in [0951dda9](https://github.com/alexhawat/mergeCraft/commit/0951dda9d63686faac6ad9f623db9d89be8a11f0)
- Ignore zizmor cache-poisoning on analyzer cache in [a8c0d2ff](https://github.com/alexhawat/mergeCraft/commit/a8c0d2ffb4ff8b663822322b78be241ee541706c)
- Inline actionlint SARIF template in workflow_lint in [a0e10094](https://github.com/alexhawat/mergeCraft/commit/a0e10094d2b407c09578bfadf346c2fc67a890aa)
- Repair cache pin and actionlint SARIF emit in [84b589d0](https://github.com/alexhawat/mergeCraft/commit/84b589d0c9468b3a6b1ade81637e0096d7e86e32)
- Close thermo T3 SARIF ingest gaps in [01986515](https://github.com/alexhawat/mergeCraft/commit/01986515b81cc083d42b4f593f29ea3f4d564004)
- Claude backstop respects Codex success and neutral in [2b3d241e](https://github.com/alexhawat/mergeCraft/commit/2b3d241ee56dd4dadab1370330e9ad8e1a996a24)
- Isolate base-measure venv from the PR job in [9987b399](https://github.com/alexhawat/mergeCraft/commit/9987b39910e931a007d2e28264a9953d80d0ed0f)
- Write evidence packets to RUNNER_TEMP, not the workspace in [20d445f7](https://github.com/alexhawat/mergeCraft/commit/20d445f795c7f05528f914f94d4a1024a2afb6e3)
- Repin the action digest and stop unit tests hitting GHCR in [6cb765b3](https://github.com/alexhawat/mergeCraft/commit/6cb765b352039cd3f5831d5de88dd8b552c879dc)
- Bump self-review Action pin to digest-corrected SHA in [51a3e8ea](https://github.com/alexhawat/mergeCraft/commit/51a3e8ea1ecde7a6cef22e2b3f7081b09895613c)
- Bump self-review Action SHA to 55269319 in [fa0b7057](https://github.com/alexhawat/mergeCraft/commit/fa0b705709b0f28692b27a5edb4ad99bb3868e0a)
- Pass --verbose to claude stream-json and harden analyzer provisioning in [bb3022b6](https://github.com/alexhawat/mergeCraft/commit/bb3022b6735de1a46d26dcbba76ac45ec27e9f60)
- Pass the dispatch ref as data, not as expanded template in [d7646ff1](https://github.com/alexhawat/mergeCraft/commit/d7646ff110954510cf19df4d2df2a2e0baf170a3)
- Pin the base worktree venv in the coverage delta gate in [ceaa3311](https://github.com/alexhawat/mergeCraft/commit/ceaa331160501d162fc56da05246315cca3ac81a)
- Cover Claude auth in the approval gate's HAS_AUTH in [95e2d937](https://github.com/alexhawat/mergeCraft/commit/95e2d93799b5e815d817ae39bc046dea643f0673)
- Stop persisting the checkout token into .git/config in [828fb071](https://github.com/alexhawat/mergeCraft/commit/828fb071f68091e74d8f6ff999042b73f40ea900)
- Carry the Claude rung to the current pin and wire its tracing in [e6dad834](https://github.com/alexhawat/mergeCraft/commit/e6dad8348aa3dc43df68648e51a838690ee8dc7c)
- Narrow getattr_tautology to object() targets in [c5281d4d](https://github.com/alexhawat/mergeCraft/commit/c5281d4df129f4939730e55a9150aeab57a06fba)
- Lazy-load mutation module map for testability in [4ba1df18](https://github.com/alexhawat/mergeCraft/commit/4ba1df189b9b1c17f3e43539abb9e7777b4c8a28)
- Honest coverage ratchet guards and docs in [9b485c1a](https://github.com/alexhawat/mergeCraft/commit/9b485c1a5dfbb1392248c43e5d17681aba45fdb2)
- Target .venv-dev for SARIF emit steps in [e23571fb](https://github.com/alexhawat/mergeCraft/commit/e23571fb8997249fba1bba6c9ff0bd536447760d)
- Drop global doctest-modules from make test in [64e66dc2](https://github.com/alexhawat/mergeCraft/commit/64e66dc205b8c83b523913b9a91b4dc73a279101)
- Stabilize coverage gate and analyzer override warnings in [c1fc35c2](https://github.com/alexhawat/mergeCraft/commit/c1fc35c2a6810417d4ca3a5a5a82a8ba76d6cd69)
- Preserve CI blame paths and audit CLI exit codes in [980f64c8](https://github.com/alexhawat/mergeCraft/commit/980f64c80efa65db0848e61b5782c8a1960b4995)
- Isolate test venv from subprocess uv sync (AG8) in [a8758b98](https://github.com/alexhawat/mergeCraft/commit/a8758b9819ac0549d3f642c5569f5e7580ac7c25)
- Bound zip archive decompression for logs and SARIF (MCB-14) in [28f8a236](https://github.com/alexhawat/mergeCraft/commit/28f8a236d8f965edbe5c1afe1443e21e5c9a1369)
- Tracing extra and enterprise reset for sink handoff in [472da9a8](https://github.com/alexhawat/mergeCraft/commit/472da9a8a7fd29e80e7da162f8c89fab511086ef)
- Resolve empty GITHUB_BASE_REF on push events in [189a7659](https://github.com/alexhawat/mergeCraft/commit/189a76591c8c71d31109c289e78ea45fb8fa2147)
- Stabilize tracing shard tests and integration gate in [57a69b49](https://github.com/alexhawat/mergeCraft/commit/57a69b49e357d61c85ed8a2f60cc80dce522cd27)
- Fail coverage gate when prefix data missing from report in [16b97bd9](https://github.com/alexhawat/mergeCraft/commit/16b97bd9edf92c382789e0d0a1fb05cee6c10e43)
- Run coverage-gate on PR workflow and relax branch floor margin in [b7a37e64](https://github.com/alexhawat/mergeCraft/commit/b7a37e64a211223be39571a43fc7d9252f6e09a0)
- Handle tokenize errors in mutation harness in [412b04c9](https://github.com/alexhawat/mergeCraft/commit/412b04c9d61799281e2ad90836c1f80aeadd8f86)
- Restore mutation sandbox and stable per-module seed in [3c80a44d](https://github.com/alexhawat/mergeCraft/commit/3c80a44d7fa6a9bdde4fe75f6fbe1a58b6e0217e)
- Thermos final cleanup in [e5c30bde](https://github.com/alexhawat/mergeCraft/commit/e5c30bde411bc46e7aa52296a39cb7edc2c84982)
- Thermos round-2 hygiene findings in [14076903](https://github.com/alexhawat/mergeCraft/commit/1407690381e0e498825378920d31cb86565b28d8)
- Bash shell for integration gate and last-line log parse in [ea3e064e](https://github.com/alexhawat/mergeCraft/commit/ea3e064e90de5eda31c2a4caf83d523294e68e2e)
- Finish thermos should-fix findings in [259fcb1e](https://github.com/alexhawat/mergeCraft/commit/259fcb1e2b1f3a679f9b5729092351346709d831)
- Address thermos review findings in [cf94c81e](https://github.com/alexhawat/mergeCraft/commit/cf94c81e499576609327445bfd1b535e9575198c)
- Make coverage and integration meta-gates falsifiable in [20f31b35](https://github.com/alexhawat/mergeCraft/commit/20f31b35ec05303c6655c850d414bc40be8cb1c2)
- Keep incomplete on SCM artifact listings in [b3be3bb4](https://github.com/alexhawat/mergeCraft/commit/b3be3bb470aa2af945996ac17349757c962d69f4)
- Return GitHubListedItems from list pagination in [4aa3bcda](https://github.com/alexhawat/mergeCraft/commit/4aa3bcda9ef2fcaf48d5dcfcbadc4f1b7c042933)
- Fail-closed when GitHub list pagination is truncated in [a2e3a4a9](https://github.com/alexhawat/mergeCraft/commit/a2e3a4a969786031c40fef961e48c5458f8a1526)
- Make coverage inherited-drift attribution reachable in [c2db6d4f](https://github.com/alexhawat/mergeCraft/commit/c2db6d4fb8f749be4b01518e326d0725f9890a07)
- Install local analyzers in base coverage worktree in [07cdfc94](https://github.com/alexhawat/mergeCraft/commit/07cdfc94b9452f426dafb4dcf47196ecf6bb035f)
- Compose review timeout budgets from one number in [b24bbdac](https://github.com/alexhawat/mergeCraft/commit/b24bbdacae3fd43a16eb3b21e1f177d5e00b7332)
- Pin gate-ordering tests to the HY3 step label in [0ed3d758](https://github.com/alexhawat/mergeCraft/commit/0ed3d7583e5e6e12dc7fd22e93a735acdbe4bbee)
- Label the Nous review step with the model it runs in [d77f5ffa](https://github.com/alexhawat/mergeCraft/commit/d77f5ffa21812e0822c5f4fa63e5388cd264c975)
- Install dev extras in the coverage-delta base worktree in [fc01f1c7](https://github.com/alexhawat/mergeCraft/commit/fc01f1c760a3f8b87cc1d1d65ba587e8938884c8)
- Drop --depth=1 so the pin staleness guard can measure in [d3c858bf](https://github.com/alexhawat/mergeCraft/commit/d3c858bf27c65df6491eb6d18f5f87e3ed2a9354)
- Restore carryover fake client and llms bundle in [c385ee62](https://github.com/alexhawat/mergeCraft/commit/c385ee62bc2f854708b647104bfb7cbbf863d13d)
- Unblock PR #442 self-review timeout and recallPass in [cfa36704](https://github.com/alexhawat/mergeCraft/commit/cfa36704cf6c58a6abe895e539a377c4599fa4bd)
- Resolve test_modes failures and recallPass schema pin in [93c4649d](https://github.com/alexhawat/mergeCraft/commit/93c4649d147c17657c403443fff7aec67bc89572)
- Wait for Codex fallback before the approval gate in [2d2b26ec](https://github.com/alexhawat/mergeCraft/commit/2d2b26ec0b5d8fde39c262d4394de432ea0cd672)

#### Ci Gate

- Set git identity in scratch clones in [f9282a8b](https://github.com/alexhawat/mergeCraft/commit/f9282a8b40a086290c8451f73f6b078424273047)
- Use synthetic branch on detached HEAD in tests in [5028d1b3](https://github.com/alexhawat/mergeCraft/commit/5028d1b32488c6e3ea8d063ba781982910709aaa)
- Address PR #581 review findings in [e0343521](https://github.com/alexhawat/mergeCraft/commit/e03435217dc2d22cb481a3bd0e63382e39124ffe)
- Address Thermos review findings in [13a1d7ab](https://github.com/alexhawat/mergeCraft/commit/13a1d7ab2812e93f92c1df96df30fd4e82ec3b0b)
- Skip delta when base measurement fails in [#536](https://github.com/alexhawat/mergeCraft/pull/536)
- Base worktree reads its own config in [#573](https://github.com/alexhawat/mergeCraft/pull/573)

#### Cli

- One-shot assign-model for harness providers in [#955](https://github.com/alexhawat/mergeCraft/pull/955)
- Make the surfaced CLI output tell the truth in [e3b7cb04](https://github.com/alexhawat/mergeCraft/commit/e3b7cb044a19ec9957de3045c23c42f3e9c220b9)
- Fail closed when TYPESAFE secret presence is unknown in [06215f2b](https://github.com/alexhawat/mergeCraft/commit/06215f2b74a6df7c77e087b7c11ba3bb1d1dd610)
- Replace any YAML boolean spelling for jev.enabled in [8bd60f63](https://github.com/alexhawat/mergeCraft/commit/8bd60f637094c1d081e03178170555e0c9eb87db)
- Patch the jev block in place instead of appending a duplicate in [9cdaee5a](https://github.com/alexhawat/mergeCraft/commit/9cdaee5a318dfb4b5523eee59db80e67fe5ef43a)
- Export only selected mutmut keys in [4a630ca8](https://github.com/alexhawat/mergeCraft/commit/4a630ca89f437229a8ba8ec5f3f5c177f2e66e46)
- Preserve setup.cfg and use mutmut interpreter in [0062914b](https://github.com/alexhawat/mergeCraft/commit/0062914bfe186f5c913c09f2e57e263419166a3b)
- Send TTY wizard prompts to stderr in [d47dd7b5](https://github.com/alexhawat/mergeCraft/commit/d47dd7b596348a9ca131b5fd599b5b5617a1aa81)
- Refuse local evidence unless shell is enabled in [42f718f7](https://github.com/alexhawat/mergeCraft/commit/42f718f7a6e4f5b570dbc046760a3974c79c4a8b)
- Honor parent flags when opening TTY sessions in [461c18dc](https://github.com/alexhawat/mergeCraft/commit/461c18dc574216890579c848256069dee5924657)
- Wrap or refuse live coverage/mutation runs in [4f47ee5f](https://github.com/alexhawat/mergeCraft/commit/4f47ee5f63335e0dd7cd9e3c5cc4dd0902a370e6)
- Run verify-behavior after Playwright sync launch in [f2099a8d](https://github.com/alexhawat/mergeCraft/commit/f2099a8d1bd87cc419094a8659e2dc75f85cd446)
- Handle non-UTF-8 untracked files without lossy patches in [918ebb1b](https://github.com/alexhawat/mergeCraft/commit/918ebb1b02384d29795c5dde55c6b4683a71143d)
- Preserve review diffs and validate installed eval paths in [356adf56](https://github.com/alexhawat/mergeCraft/commit/356adf56f70e9250de1d9c42d74c390e6fd32070)
- Align model fallback and auth onboarding in [ffa694a3](https://github.com/alexhawat/mergeCraft/commit/ffa694a36f4af1f21587f585a33e312f86e95fb9)
- Pair the .env anchor with the config path, restore changelog in [876a2eb6](https://github.com/alexhawat/mergeCraft/commit/876a2eb66f0643198f8203cf5053fb1bb57e6bce)
- Restore provider_cmd's no-repo-required .env resolution in [4c532b57](https://github.com/alexhawat/mergeCraft/commit/4c532b573a0586fec473ca50b554bc2311f3e535)
- Unify .env path resolution via shared helper in [a4163d98](https://github.com/alexhawat/mergeCraft/commit/a4163d980029fb01974e2d4b161a8f2bf472d482)
- Fail closed on invalid agent findings and seed aliases in [893f2ac0](https://github.com/alexhawat/mergeCraft/commit/893f2ac0dc38902d6a376a85e4030d2303fad99e)
- Compact credentials for gh secret set path in [6c5e873d](https://github.com/alexhawat/mergeCraft/commit/6c5e873d1076af9ee41115ff0a7023b4947e783d)
- Compact credentials for gh secret set path in [05d11d74](https://github.com/alexhawat/mergeCraft/commit/05d11d74cf6fd75e091237f3fbcabc35425ba721)
- Close three ways provider disable can leave a provider live in [ae08571a](https://github.com/alexhawat/mergeCraft/commit/ae08571a24f492ed3495348c35e4e5d182d1d5fe)
- Route the provider-toggle git call through git_argv in [7877b5eb](https://github.com/alexhawat/mergeCraft/commit/7877b5eb6981a44010d9fbfa4dc22e3222476907)
- Keep every owned env key when wire-workflow creates the block in [73349a5d](https://github.com/alexhawat/mergeCraft/commit/73349a5d6eeaa0242454fd6fbb05e4940e85220c)
- Fail closed on unsupported cloud_chain labels in [2451c0d3](https://github.com/alexhawat/mergeCraft/commit/2451c0d3da1496b47816cdb9eb8e9dac169840ad)
- Correct three runtime gaps in provider disable in [284a7bba](https://github.com/alexhawat/mergeCraft/commit/284a7bba2408a0c2e5a0ec4d66562a89f9a74df7)
- Make the workflow rollback atomic too in [a6424b7e](https://github.com/alexhawat/mergeCraft/commit/a6424b7e112a1be8625a8e5deea2307e1b3766c3)
- Validate migrated URLs and write the workflow atomically in [ae5cfb36](https://github.com/alexhawat/mergeCraft/commit/ae5cfb36e0d4ee8cb3fc9bfe5f6ba23f58354038)
- Replace the provider config atomically in [98970f92](https://github.com/alexhawat/mergeCraft/commit/98970f9292b278ebc20846061dff670695d6fc08)
- Roll the workflow back when the config write fails in [2753358f](https://github.com/alexhawat/mergeCraft/commit/2753358f887555e2abc6938c4c8ca287faf02240)
- Persist provider config only after the workflow write in [5cc99837](https://github.com/alexhawat/mergeCraft/commit/5cc9983700305c96b2d9c08e2ea58710746cc41d)
- Scope workflow paths to --cwd and apply url overrides in [dd194b08](https://github.com/alexhawat/mergeCraft/commit/dd194b08b3833ce5c961eecff6cbf381a4ba91f9)
- Seed builtin providers during mergecraft init in [787c947d](https://github.com/alexhawat/mergeCraft/commit/787c947d93e6aa0fe94493b45ade98765b62cfa3)
- Restore auth_codex shutil.which and legacy gateways in [3ee9c53b](https://github.com/alexhawat/mergeCraft/commit/3ee9c53bf08b45869e5eaca3a448df22e9539db9)
- Close Thermos runtime gaps in provider registry in [3720b032](https://github.com/alexhawat/mergeCraft/commit/3720b032ab915ce59f17b04614b1df2ab7a1d09f)
- Handle registry errors in plan command in [184e9ceb](https://github.com/alexhawat/mergeCraft/commit/184e9ceb87247d7d26eb5931060435a31c9716eb)
- Filter packet stems and wire --trace-dir persistence in [7330123e](https://github.com/alexhawat/mergeCraft/commit/7330123e2087af5a89b58b727b08883d58fdffb4)
- Address PR #492 Codex review anchors in [f7d702d2](https://github.com/alexhawat/mergeCraft/commit/f7d702d25bdda6e19fd0120ac1e89d3d584ae284)
- Close PR #492 review integration gaps in [cf3d6f98](https://github.com/alexhawat/mergeCraft/commit/cf3d6f98f3298eb883372fa242cde64047366eac)
- Address PR #492 review gaps for lane C in [738bee47](https://github.com/alexhawat/mergeCraft/commit/738bee47df365f3d7924a8d947467b43db8b5f90)
- Ignore .mergecraft/audit.jsonl on init in [f6ebe5da](https://github.com/alexhawat/mergeCraft/commit/f6ebe5da8a4908fbba1f4718a07d31cc137e2310)
- Let an explicit --model outrank MERGECRAFT_MODEL in [1c21aa9e](https://github.com/alexhawat/mergeCraft/commit/1c21aa9e456edd8412002036af1290332950f972)
- Report partial local auth writes honestly in [8f738268](https://github.com/alexhawat/mergeCraft/commit/8f738268c3b41a666a3b9ea13a6ba986bf478280)

#### Codex

- Run the Codex CLI in the repository it reviews in [573757d2](https://github.com/alexhawat/mergeCraft/commit/573757d2db14d53253a4c52f57a8146d47bdf424)
- Stop flat auth overriding a resolved registry key in [9dfd5eb2](https://github.com/alexhawat/mergeCraft/commit/9dfd5eb2a45c68ef935253358c5e464d60368a9d)

#### Config

- Share config sources, scan past comments, classify a sink typo in [259f3026](https://github.com/alexhawat/mergeCraft/commit/259f3026ede079579ae172678039600ea1947dfd)
- Fail closed on malformed tracing action inputs in [38084946](https://github.com/alexhawat/mergeCraft/commit/38084946e6ff42ca4ce969bb642ee38b9254755e)
- Refuse settings that silently mean something else in [49024192](https://github.com/alexhawat/mergeCraft/commit/49024192e78ca0de79eefc4d8cdcf3b53869676a)
- Refuse invalid settings and stop duplicate config keys in [18a91cf0](https://github.com/alexhawat/mergeCraft/commit/18a91cf0aeb25b760a466f596ac032a55b0b6842)
- Lazy-import source_resolve in workspace root in [a24dd9e0](https://github.com/alexhawat/mergeCraft/commit/a24dd9e09dc883474714341c1aaee477f72c83d6)
- Gateway path reads run-scope settings snapshot (AG9) in [0abd62be](https://github.com/alexhawat/mergeCraft/commit/0abd62becfe0bf4fb14f12855bce0f037d12fab7)
- Reject control characters in provider URLs in [bee9b806](https://github.com/alexhawat/mergeCraft/commit/bee9b8067db3dc19996930581e7c8429a6c3e24f)

#### Context

- Reserve truncation marker inside the byte cap in [12ba1ec8](https://github.com/alexhawat/mergeCraft/commit/12ba1ec845a2d92581772f39c2d821da397e9dcd)
- Drop refs when trusted cap pops a skill in [7adb3fac](https://github.com/alexhawat/mergeCraft/commit/7adb3facf057f27b03cb348be6df4d79b1ba021b)
- Sync record when untrusted cap drops a skill in [47a834e5](https://github.com/alexhawat/mergeCraft/commit/47a834e56faf09cff2d564582c16d3f290ddb658)
- Close Thermos turn-3 review-skill gaps in [b325f6dc](https://github.com/alexhawat/mergeCraft/commit/b325f6dc607e2e0874f5bfcc7d02d4a1d37afd03)
- Close Thermos turn-2 bundle and discovery gaps in [c32a27d0](https://github.com/alexhawat/mergeCraft/commit/c32a27d09a4d89552b79f0cd1959b636a43331e7)
- Address Thermos review-skill bundle findings in [e01184e6](https://github.com/alexhawat/mergeCraft/commit/e01184e6bd9016b2230eecaa342c27f04d3c8770)
- Close RS5 strictness and CLI bundle cap in [496a2bdb](https://github.com/alexhawat/mergeCraft/commit/496a2bdb7b5954e333a72ddecbd9335b033c2990)
- Repair review skill loader for RS2 in [558d9ca0](https://github.com/alexhawat/mergeCraft/commit/558d9ca0ad7d1e5c81acea7d526bb86aa2a7368e)

#### Deps

- Bump OpenTelemetry to 1.45.1 (CVE-2026-114603) in [b0d89441](https://github.com/alexhawat/mergeCraft/commit/b0d894414e7360e1ed09501d8bee179f05ec6053)
- Bump pyjwt, urllib3 and virtualenv for new advisories in [74820e1d](https://github.com/alexhawat/mergeCraft/commit/74820e1d319dcaa1bcb492e4fbbd27b0729eaed0)
- Bump pyjwt to 2.14.0 for the 2.13 advisories in [d8d9ad5c](https://github.com/alexhawat/mergeCraft/commit/d8d9ad5cb924abab9a1788d3205ada87f3326a7e)
- Bump soupsieve to 2.9.2 for pip-audit in [58d9d2eb](https://github.com/alexhawat/mergeCraft/commit/58d9d2eb1ad11603dd38e57622fca97b0114ccd8)
- Make uv.lock carry logfire 5.0.0 and realign ast-grep in [af6e6a42](https://github.com/alexhawat/mergeCraft/commit/af6e6a4205b99d8e003efd564da3f5ee8cb97041)
- Reconcile the group bump with every mirrored pin in [99b9a912](https://github.com/alexhawat/mergeCraft/commit/99b9a9124b702d3b30ba7e96108840fe657eae28)
- Regenerate lockfile, adapt to click 8.4 and sync ruff hook rev in [55711751](https://github.com/alexhawat/mergeCraft/commit/55711751abde2452d68e0dd77be9c00ae6ea2ab6)

#### Docker

- Pin the openssl packages past CVE-2026-84782 in [97c19416](https://github.com/alexhawat/mergeCraft/commit/97c1941655a4c54696eba9f8f42bfb7234c6cfbc)
- Bump pinned undici to 6.29.1 (CVE-2026-109869) in [dfcbe920](https://github.com/alexhawat/mergeCraft/commit/dfcbe920e2f1a38e1c015bdb26a74b48dcea1d3a)
- Build gh and actionlint with Go 1.27.2 and x/net 0.60.0 in [f78e6adc](https://github.com/alexhawat/mergeCraft/commit/f78e6adc5636e7fb7fd6ab2ba45accd422cd86ea)
- Pin libpcre2-8-0 to the current bookworm-security build in [45078537](https://github.com/alexhawat/mergeCraft/commit/45078537f069d0df003a89df9be0153740f607ac)
- Patch npm's bundled brace-expansion and undici in [20e8962d](https://github.com/alexhawat/mergeCraft/commit/20e8962daa45075c5e6fff447375c72ad9f57da1)
- Keep the runtime tree root-owned in [76d8561f](https://github.com/alexhawat/mergeCraft/commit/76d8561f9ee4b58393f62a30262eec84d0cf067f)
- Pin bookworm-security pcre2 for image scan in [cce1a394](https://github.com/alexhawat/mergeCraft/commit/cce1a39459d2ff44f1f70790027a9ac84eaed7c2)
- Include the packaged corpus before building in [c8c5bb78](https://github.com/alexhawat/mergeCraft/commit/c8c5bb786d62106a3c6432bdf63dec35efdc34aa)
- Copy hatch_build.py into the analyzers image layer in [ebeff279](https://github.com/alexhawat/mergeCraft/commit/ebeff279e5adc782fcf8d64a6eadf5718f120cd9)
- Copy hatch_build.py into Action image layer in [f6899504](https://github.com/alexhawat/mergeCraft/commit/f68995041ff6192fc3e20409889dd52423dc563b)

#### Evals

- Gate failed and inconclusive cases; maximise matching in [be925ebf](https://github.com/alexhawat/mergeCraft/commit/be925ebfe60d734a24501dbea8a557577a2dc98d)
- Make adjudication round-trippable in [e1bb753f](https://github.com/alexhawat/mergeCraft/commit/e1bb753ff14f6e08610521ca38dabd135a9fde74)
- Label live shadow rows and ingest dismissals in [4a093db0](https://github.com/alexhawat/mergeCraft/commit/4a093db09953d0de90a34923ddc81ee67b775d30)
- Refuse a case id that escapes the eval bank in [0a314ca6](https://github.com/alexhawat/mergeCraft/commit/0a314ca6bbcdc90bd6c564a5ce213ac5e693b762)
- Keep JSONL comment lines when adjudicating a label in [dfe85ce3](https://github.com/alexhawat/mergeCraft/commit/dfe85ce31a8fe2061ca73ea7c6097e7eb3be7eeb)

#### Evidence

- Parse sed diff reads in the command fallback in [193f1ce7](https://github.com/alexhawat/mergeCraft/commit/193f1ce7f936d4d3a907382c42766afaed39699c)
- A question-answering exit 1 is not a failed outcome in [0228ff49](https://github.com/alexhawat/mergeCraft/commit/0228ff490c98ee05b6bdebb4a4eb440e4f22396d)
- Keep trajectory hashes stable when publish fields are unset in [b57e2445](https://github.com/alexhawat/mergeCraft/commit/b57e2445eb4159d11c7728de938ecaaaa0d76e8b)
- Record the live shadow model from the packet in [4f64c973](https://github.com/alexhawat/mergeCraft/commit/4f64c973638ab0ed6acea3ea38928948f2383fc7)
- Reject an unlabelled shadow row before sorting in [1bb3eb1e](https://github.com/alexhawat/mergeCraft/commit/1bb3eb1ed830a223502a0c068df4289bb3d7945c)
- Compare the live gate with prompt 2.0.0 in [0a51ab8c](https://github.com/alexhawat/mergeCraft/commit/0a51ab8c02c328e954d83aaa8758a0c251d51f1d)
- Record the second shadow target from live emit in [b42e0a2f](https://github.com/alexhawat/mergeCraft/commit/b42e0a2fc74c5575b620f17af64bbde97d231aa3)
- Publish the shadow job as a corpus report in [3613f7da](https://github.com/alexhawat/mergeCraft/commit/3613f7da8dd02957184a3eaf61c5b2bfbfde5a84)
- Skip synthesized rows for partial shadow coverage in [a2342df5](https://github.com/alexhawat/mergeCraft/commit/a2342df541947ddbdc5b32033a135aac6bc7e3f3)
- Keep rev:path base reads as read evidence in [78810436](https://github.com/alexhawat/mergeCraft/commit/7881043655950bb354a49b21f3c9e707599cbf45)
- Stop argument paths manufacturing changed-unread-file in [8f3ff564](https://github.com/alexhawat/mergeCraft/commit/8f3ff5642871afe060c3247d235905208d1fee46)
- Read confirmed findings into the approval gate in [654da446](https://github.com/alexhawat/mergeCraft/commit/654da446e98d300c36dfc9fcc034d8c474725324)
- Surface discarded finding rows instead of dropping them in [546d99e2](https://github.com/alexhawat/mergeCraft/commit/546d99e250711d7b694e3bc68285eaec4e676aa5)

#### Findings

- Name the skipped slot and verdict model in the record in [f66dc3df](https://github.com/alexhawat/mergeCraft/commit/f66dc3df9204897141e3ae056a9009663f772d60)
- Trust only bot-authored sticky progress comments in [57da535e](https://github.com/alexhawat/mergeCraft/commit/57da535eaa67f684b778b36130a701321128178a)
- Keep ledger in sticky comment across final write in [53fcecea](https://github.com/alexhawat/mergeCraft/commit/53fcecea93d4cab2acf823155b9daa0b5e995cc0)
- Stop auth stem matching the author word family in [2f39b221](https://github.com/alexhawat/mergeCraft/commit/2f39b22153bb9fa26bcf68be04d87f7bbe7f878d)
- Corroboration cannot weaken a finding in [7af6d5de](https://github.com/alexhawat/mergeCraft/commit/7af6d5de26e01d098c7c5f603a9f5e1bf7a892c0)
- Severity follows impact, not incidental vocabulary in [1ecae3ac](https://github.com/alexhawat/mergeCraft/commit/1ecae3ac8460c5d4f6b6c953ba49040287a93b81)
- Stop marker stripping from truncating agent prose in [1b98a6b8](https://github.com/alexhawat/mergeCraft/commit/1b98a6b83931e868998568927b28a6ff1d502128)
- Unify short-id resolution across publish lanes in [e476bd8f](https://github.com/alexhawat/mergeCraft/commit/e476bd8f6a5632061ce335db95153ed3ce6f8212)
- Align ledger hydrate and deferred recording in [492bded0](https://github.com/alexhawat/mergeCraft/commit/492bded06874eded2cc416db9c49cca0ca419393)

#### Gates

- One definition of a passing check, reachable auto-merge in [ca6e7d41](https://github.com/alexhawat/mergeCraft/commit/ca6e7d411a5ee64ee1a011c0e7d3ef0a816c9e0c)
- Resolve gate mode from settings snapshot (AG4) in [3afb7e66](https://github.com/alexhawat/mergeCraft/commit/3afb7e66cbcb1b1cb97274839c9755aba61c1e39)
- Attach decision before decide_action (MCB-15) in [df78a071](https://github.com/alexhawat/mergeCraft/commit/df78a071271a3dc456294db9d14d8cbc6ce67421)

#### Git

- Match the HTTP status forms git actually emits in [6c3fd8c8](https://github.com/alexhawat/mergeCraft/commit/6c3fd8c8f91c221e3fa3423b50935aa32d078317)
- Authenticate git over HTTPS with basic auth, not Bearer in [b4bb29c3](https://github.com/alexhawat/mergeCraft/commit/b4bb29c3b28f96d47d927b6952e3b010aaa3b6fa)

#### Hygiene

- Deny Darwin .git writes and attach MD060 for cli2 in [d8f4b5d1](https://github.com/alexhawat/mergeCraft/commit/d8f4b5d1c9e7bf5c3f84ca1889d386f8c0482b76)
- Strip public W#.# tokens and filter CI SARIF in [6565b8b6](https://github.com/alexhawat/mergeCraft/commit/6565b8b66d0ae888af44c5f2e156290f115f752d)

#### Jev

- Dispatch-time skips must not render as a clean screen in [40843507](https://github.com/alexhawat/mergeCraft/commit/408435075350a019e9eedd96ca043fe9839af878)
- Fence untrusted content on every System One call in [5a2f0ce6](https://github.com/alexhawat/mergeCraft/commit/5a2f0ce642bcf0606e0212401934ba68f01da4a9)
- Resolve CI lint and docs index for architecture checklist in [e00376ef](https://github.com/alexhawat/mergeCraft/commit/e00376ef83de3557653dfcc6e546f8d9446d3c2d)
- Isolate status-less TypeSafe transport from review in [f3f6f4bc](https://github.com/alexhawat/mergeCraft/commit/f3f6f4bc249cbca24f727c935b23a93d46697158)
- Persist shadow judge and pin the model in [e58e25b1](https://github.com/alexhawat/mergeCraft/commit/e58e25b1cf48539bc4c29c6ff0d56b314db8a06f)
- Feed findings, isolate outages, honor thresholds in [34662a84](https://github.com/alexhawat/mergeCraft/commit/34662a843bcbe606dd000d85b6e608adc306ed1f)

#### Mcp

- Refuse every prefix of a blocked git option in [d88400d4](https://github.com/alexhawat/mergeCraft/commit/d88400d4a2129427788357945022b24265f78526)
- Refuse blocked git options after a swallowed `--` in [f204e8ee](https://github.com/alexhawat/mergeCraft/commit/f204e8ee55a327ec46ef34488cb0dd0e21fc3b40)
- Parse git grep context counts the way git does in [2f36dabd](https://github.com/alexhawat/mergeCraft/commit/2f36dabdb210c8b2083a3f850f88ddccca4bb82c)
- Refuse abbreviated and scope-widening git tool options in [c7cd8f4c](https://github.com/alexhawat/mergeCraft/commit/c7cd8f4ced0d5016b3387de0be09d4cfab84aff3)
- Close git grep context guard bypasses in [3c450d2b](https://github.com/alexhawat/mergeCraft/commit/3c450d2b9a0de77f387e27233fcab2d7fb2d6726)
- Deliver the time notice where the review agent and code mode see it in [49c682e0](https://github.com/alexhawat/mergeCraft/commit/49c682e0ee605fe11419dd04993486544925aed7)
- Steer git grep body reads to the native read tool in [8428c843](https://github.com/alexhawat/mergeCraft/commit/8428c84398f147d11ab8366096250a5855280616)
- Return only navigation fields from list_check_runs in [40e66444](https://github.com/alexhawat/mergeCraft/commit/40e664445af6a6891f8b6b427a466124333b247d)
- Remove the inert webhook route and ingress replay store in [07797935](https://github.com/alexhawat/mergeCraft/commit/0779793536b7a9edf6ffd755483c0f5020ece8c6)
- Warn on every run-bound reader fallback in [92247686](https://github.com/alexhawat/mergeCraft/commit/922476864783bcb0ce6089770edfe19f5a437006)
- Confine run_analyzers inputs and isolate its fixture in [7583927d](https://github.com/alexhawat/mergeCraft/commit/7583927d6693f0821bc8d636b0334df26a34362d)
- Tolerate patched sandbox probe when resetting cache in [4022dd4d](https://github.com/alexhawat/mergeCraft/commit/4022dd4d77cac90c3454321435f6b44b7e0fb946)
- Retain analyzer evidence by scope; commit-info read-only in [d7a7ea87](https://github.com/alexhawat/mergeCraft/commit/d7a7ea873f82e8771e6602eff6f44229f55cbc4b)
- Refuse --textconv and --ext-diff on every read-only verb in [a2608e6d](https://github.com/alexhawat/mergeCraft/commit/a2608e6d1c436578962b956d4809ca47eedac236)
- Terminal submission owns published review body in [#572](https://github.com/alexhawat/mergeCraft/pull/572)
- Bound monotonic anchor-422 recovery in [#570](https://github.com/alexhawat/mergeCraft/pull/570)
- Bind review scope evidence to the PR GitHub reports in [75cec782](https://github.com/alexhawat/mergeCraft/commit/75cec78282509321d727da699ef9c79798d176f6)
- Close three containment gaps found in review in [15ec8f91](https://github.com/alexhawat/mergeCraft/commit/15ec8f91b366f5ca27dd171fbd2ebed5f6f4dbfc)
- Deny config keys case-insensitively for extraheader in [ffd12c9d](https://github.com/alexhawat/mergeCraft/commit/ffd12c9d917ae6359450f750eaddd1b8cbd42c32)
- Confine git tool paths and deny credential reads in [7dd872a1](https://github.com/alexhawat/mergeCraft/commit/7dd872a1b7fe8aa763cd2ecc7790e8fcd27aaa94)
- Keep publication alive when a fingerprint is not hex in [28fec545](https://github.com/alexhawat/mergeCraft/commit/28fec54543f97bb80eef74335d6cedf56799c8a1)
- Use httpx for local health identity probe in [5046e48f](https://github.com/alexhawat/mergeCraft/commit/5046e48f1bb9d57eb5e13f1577d7d40d089b2f7a)
- Structured get_policy errors and honest dry_run response in [e65c0b2e](https://github.com/alexhawat/mergeCraft/commit/e65c0b2eceb6736de23bb88fb44a17b9d4ac0406)
- Dry-run non-durable and effective get_policy in [ef9dfb3f](https://github.com/alexhawat/mergeCraft/commit/ef9dfb3f031d951d201b048ea1ddb2cf2dac7ff5)
- Registry packageArguments, auth scope docs, close mkstemp fd in [8e3c7d96](https://github.com/alexhawat/mergeCraft/commit/8e3c7d96123fb7936b94ecde40de499fa6b11025)
- Harden review_change refs and fix install docs in [4bf7ed71](https://github.com/alexhawat/mergeCraft/commit/4bf7ed7152c1d31db65e3f5148a731c7a2a6cb28)
- Address Thermos code-quality findings in [5d74c13f](https://github.com/alexhawat/mergeCraft/commit/5d74c13fb457b232bc5a247f9cdd32506959da27)
- Tolerate fixture rows in get_review in [d3abc854](https://github.com/alexhawat/mergeCraft/commit/d3abc8544355099f54199ec780b39f53ff0afc98)
- Fail closed on truncated check-run lists in [8f26b291](https://github.com/alexhawat/mergeCraft/commit/8f26b2914210323ac4ec6ec8771902e5eb58c8fe)
- Refuse empty GitHub Bearer tokens in [b2d43351](https://github.com/alexhawat/mergeCraft/commit/b2d43351952d2d172c6075824a43f78e25a30f0c)

#### Modes

- Hash the rendered prompt for the mode version in [bd4f5171](https://github.com/alexhawat/mergeCraft/commit/bd4f51717e94acaa129dc3037d7669770fa68ae4)
- Align review prompts and docs with shipped contracts in [24b5d8f8](https://github.com/alexhawat/mergeCraft/commit/24b5d8f86b11b48cfd0ff5d2e57bae2b02ba7e9e)
- Align review prompts with shipped tool and budget contracts in [58878e7a](https://github.com/alexhawat/mergeCraft/commit/58878e7aedec340be9c2a9f14a056a488468f07d)

#### Opencode

- Open only a run-created temp dir to the reviewing agent in [a1b898e5](https://github.com/alexhawat/mergeCraft/commit/a1b898e507a3f31f504e241d55a6cd9913f64b67)
- Check the plugin's runtime entry, decode and redact headers in [d35cda6f](https://github.com/alexhawat/mergeCraft/commit/d35cda6f4c676a27ded52feda62c77ca25e0eabd)
- Unblock spilled output, path slugs and span errors in [a976ba9d](https://github.com/alexhawat/mergeCraft/commit/a976ba9d699fb9e57852e03472a9e3ccc8a0c540)
- Bridge flat opencode-go credential to the harness in [5d5483d9](https://github.com/alexhawat/mergeCraft/commit/5d5483d9e0912d07230ef3b42967d417472149a1)
- Chown the XDG data dir for the agent user in [52b59e39](https://github.com/alexhawat/mergeCraft/commit/52b59e39afe0a63e1c7e0db413ef288aef6c6fc5)
- Venv-agnostic MCP launcher and span pairing in [68ad736c](https://github.com/alexhawat/mergeCraft/commit/68ad736c35bb6985f05db240d1dce2c21c1a37ca)
- Discover MCP config at the project root in [dbabe528](https://github.com/alexhawat/mergeCraft/commit/dbabe5287c3d43308dd5289e47de96cd1f385221)
- Pin plugin manifest to the V2 contract in [023efcef](https://github.com/alexhawat/mergeCraft/commit/023efcef6f826abcba21b2e90a751a9da67d7039)
- Honor --target, valid OTLP ids, Docker assets in [b242ba7c](https://github.com/alexhawat/mergeCraft/commit/b242ba7c7e24f9337237ddc503cc822f75b25e92)
- Drop absent plugin dir from setup command in [0f2c6ce0](https://github.com/alexhawat/mergeCraft/commit/0f2c6ce052a6d186eba575cd6e74e1f021769393)
- Correct review-pr and logfire commands in [6c66720f](https://github.com/alexhawat/mergeCraft/commit/6c66720f6e500a1fbb05c361d841e54a98e9be89)

#### Policy

- Block required violations whatever severity they declare in [0067ad0a](https://github.com/alexhawat/mergeCraft/commit/0067ad0a9eb82c8e3f461ff4da6a51a99592d9a9)
- Make gate-facing severity the sole blocking authority in [5e3ac9d0](https://github.com/alexhawat/mergeCraft/commit/5e3ac9d023cc3b2509283c0b185fda51ebc070b7)
- Give enforcement modes distinct semantics (AG5) in [4660924a](https://github.com/alexhawat/mergeCraft/commit/4660924aac628765d151de9cff2d56fd1ff4d192)

#### Prep

- Isolate uv sync from checkout .venv in [a2192d90](https://github.com/alexhawat/mergeCraft/commit/a2192d9059aa8dc6ce444c26532ec744f3fb4bdf)
- Resolve package managers from prep venv bin in [a7883fa7](https://github.com/alexhawat/mergeCraft/commit/a7883fa736d8826435b9ab32a9e566b2d3d41123)
- Isolate python installs in dedicated venv (AP7) in [23dd6c44](https://github.com/alexhawat/mergeCraft/commit/23dd6c447cf0e872becafc32cf6febe14545b5a3)

#### Publication

- Treat empty config hash as no baseline in [b98c75ca](https://github.com/alexhawat/mergeCraft/commit/b98c75ca0fe34ee0868b7af3b290f3a2f98098d2)
- Overwrite spoofed raised_by on dispatch runs in [ce609e04](https://github.com/alexhawat/mergeCraft/commit/ce609e04668b600a25d3b82817b2879e44d4f8b2)
- Wire dispatch run recording and validate agent_id in [b5dee9a9](https://github.com/alexhawat/mergeCraft/commit/b5dee9a9dffa9bb4d350e8ffaa720faac815c4ad)
- Address PR #580 review findings on budget, attribution, preamble in [025fc12a](https://github.com/alexhawat/mergeCraft/commit/025fc12a55c52586f4cd073718f367f5a2f8a004)

#### Redaction

- Retain complete secrets containing punctuation in [f3c670aa](https://github.com/alexhawat/mergeCraft/commit/f3c670aa06fe97000b9ac11ef6cdef01c811d7ba)
- Preserve lowercase kebab ids in log messages in [50f3da55](https://github.com/alexhawat/mergeCraft/commit/50f3da55b19cc540ae6d3cee46ab338adfdcb0b6)

#### Release

- Match the pypi target to the new distribution name in [fea5942a](https://github.com/alexhawat/mergeCraft/commit/fea5942a459676fe09bf2d7e09e458d9d129891a)
- Keep the a3 post-release design, close the publish issue in [3a7b5279](https://github.com/alexhawat/mergeCraft/commit/3a7b5279bb831866992286903943b505e068ac61)
- Read the released version Craft actually passes in [adb07e58](https://github.com/alexhawat/mergeCraft/commit/adb07e5821a203f84311b76f7766aeda836dd8c1)
- Keep the versioned files in step on both bumps in [0d51f725](https://github.com/alexhawat/mergeCraft/commit/0d51f725b64dc1bc73f013eaa2efa4b6502224de)
- Regenerate server.json when preparing a release in [f77a7208](https://github.com/alexhawat/mergeCraft/commit/f77a7208d0395c60d3f2a6d82eedacdc483da5da)
- Validate candidates and recover staged image builds in [81e8eee2](https://github.com/alexhawat/mergeCraft/commit/81e8eee248512d3a6e06c19b9e28d3da2c86b8ae)

#### Review

- Narrow offline, venv, temp-dir and plugin trust checks in [64da19a2](https://github.com/alexhawat/mergeCraft/commit/64da19a212bc84eb917f454ed50a64be99dc7df8)
- Keep read-only reviews from failing on their own writes in [433cf99b](https://github.com/alexhawat/mergeCraft/commit/433cf99bade5ca085ec888d12e8304d86ed5831e)
- Close the two Major findings from the merged-head self-review in [bf7ee718](https://github.com/alexhawat/mergeCraft/commit/bf7ee71819629540310f49d745ec4fb9e3a5178e)
- Close the second large-diff review pass in [8af95a51](https://github.com/alexhawat/mergeCraft/commit/8af95a5157c3aaa5e68f27463af23b1aa28d33ac)
- Close the four large-diff review findings in [d84424f0](https://github.com/alexhawat/mergeCraft/commit/d84424f01b7d6a7a5ac560b4ab5825d978821f56)
- Stamp a skipped publication declined so the auditor ignores it in [847bfeba](https://github.com/alexhawat/mergeCraft/commit/847bfeba92f893c0510f2b118c2d03b7b71878dc)
- A recorded verdict that reaches no review says why in [446cdf5e](https://github.com/alexhawat/mergeCraft/commit/446cdf5e0a062b3054df46c8baa779e7490a4ff0)
- A secondary reviewer's infra failure reads as infra_error in [523dbcbc](https://github.com/alexhawat/mergeCraft/commit/523dbcbcc8152e273aee50e5962bdf3ec1a4a128)
- Publish the run record when no mode was selected in [7af87aea](https://github.com/alexhawat/mergeCraft/commit/7af87aea4c23fa452225dbad09d493e4a11382ce)
- Accumulate LLM timing across model-chain fallback attempts in [ff102849](https://github.com/alexhawat/mergeCraft/commit/ff102849c0fe2a3e89ad867539062622f71b1183)
- Attribute model-chain llm.call timing to reviewer in [36b625fd](https://github.com/alexhawat/mergeCraft/commit/36b625fd3ac7ae8d6993e20a6be9f9be1cbea6b1)
- Persist llm_review_timing in review result cache in [64f1a77b](https://github.com/alexhawat/mergeCraft/commit/64f1a77b5033b2159d0d5db7ad3db0116ace9464)
- Always ask an offline review for structured findings in [c6780990](https://github.com/alexhawat/mergeCraft/commit/c67809907ecc1e8ad0121da92124840b11636051)
- Scope agent reads and bind review identity to the run in [78de9d7a](https://github.com/alexhawat/mergeCraft/commit/78de9d7a9f843b4b2005d5de1c41f437f38bc13b)
- Publisher-identity sticky selection and verdict capture in [297fd624](https://github.com/alexhawat/mergeCraft/commit/297fd6244eb394166b2d4ca0ce931a308386aafd)
- Bind a recovered review's receipt from GitHub's state in [560bad83](https://github.com/alexhawat/mergeCraft/commit/560bad835aa5e92aec7ffa91417c1a4a0df0db07)
- Scope the run record to the final attempt's publication in [f14a8904](https://github.com/alexhawat/mergeCraft/commit/f14a8904dc7a51a96464b31f8caa178792fa1cf7)
- Retire threads by line and author; page full listings in [f56117c3](https://github.com/alexhawat/mergeCraft/commit/f56117c3787c9bdc13106c30ea7e285ad1914071)
- Publish the recorded verdict once, bound to its receipt in [9b4e905e](https://github.com/alexhawat/mergeCraft/commit/9b4e905e634a2fa535a602f42371a75d41600da5)
- Report the executed chain and remove legacy surfaces in [2393b9bc](https://github.com/alexhawat/mergeCraft/commit/2393b9bc4e26b792c7f4ec8a87e2c6850f25a013)
- List approval checks with the client contract in [9c807097](https://github.com/alexhawat/mergeCraft/commit/9c807097f1d9aaaf4dd695f75087c68611f49764)
- Derive the publisher login on read-side runs in [980ec40b](https://github.com/alexhawat/mergeCraft/commit/980ec40b276aa0af27cd0da0a0a22cd2fe578549)
- Read the publisher login from repo config in [19063865](https://github.com/alexhawat/mergeCraft/commit/19063865122ab1698034087f4e3f744d5e1c7ad3)
- Trust only this run's publisher bot in [8d2dba0d](https://github.com/alexhawat/mergeCraft/commit/8d2dba0d72720604fc6173236e1008523352d1b6)
- Ignore contributor-forged review markers in [57a05188](https://github.com/alexhawat/mergeCraft/commit/57a05188fccb662999de255a1b59941e8f18fcab)
- Keep user look-alike comments during migration in [12d96b1b](https://github.com/alexhawat/mergeCraft/commit/12d96b1b3a1ef0e881d4a426c8ea453ed6ddbe07)
- Cap finalized body while retaining durable state in [91a94718](https://github.com/alexhawat/mergeCraft/commit/91a94718638429aeea7e48a901e8019e3560030e)
- Consolidate run record into formal review in [d270670e](https://github.com/alexhawat/mergeCraft/commit/d270670e1de5fdbffd4a3f5122bf2db78091d297)
- Account for context-expansion tokens in the split summary in [c0a95d38](https://github.com/alexhawat/mergeCraft/commit/c0a95d38cfd969f441c4b8cd8ed4e7d3cada7364)
- Agree the step summary on a terminal verdict in [54f246a2](https://github.com/alexhawat/mergeCraft/commit/54f246a2f2d6e85a33f4eb11effb2e0244477df2)
- Report inconclusive when no credentialed reviewer ran in [64c456d8](https://github.com/alexhawat/mergeCraft/commit/64c456d8e84ef4be86f4a3be329874e30d0ff9a3)
- Hash verification report in cache key in [1de30813](https://github.com/alexhawat/mergeCraft/commit/1de30813c342deaaae6a3d304bdbb3e850550204)
- Include untracked source and surface exclusions in [3da6edd3](https://github.com/alexhawat/mergeCraft/commit/3da6edd318733629213dfca233a79939f87c76ae)
- Carry agent findings into the approval gate in [96cb4042](https://github.com/alexhawat/mergeCraft/commit/96cb40420403022876dde5fba98d0908c87faec8)
- Restore scope gate before publication in [18a0088d](https://github.com/alexhawat/mergeCraft/commit/18a0088d8f9d06da5c04d133cea122a8400768ef)
- Route unknown provenance and stamp skip entrypoint in [30586881](https://github.com/alexhawat/mergeCraft/commit/30586881ed996d0acd880b74f127f11371d18047)
- Harden publication provenance and D1 recovery in [003597c7](https://github.com/alexhawat/mergeCraft/commit/003597c7f7890ce1016649e45f7df700fa225161)
- Stamp raised_by server-side at merge time in [#574](https://github.com/alexhawat/mergeCraft/pull/574)
- Surface a refused terminal verdict in the run record in [5b78b2a5](https://github.com/alexhawat/mergeCraft/commit/5b78b2a55bc0db20c0960e01fc7864e3ad305c01)
- Bind publication scope to immutable run identity in [03bb35f1](https://github.com/alexhawat/mergeCraft/commit/03bb35f1ee3704140376bac9475d48b41290bde8)
- Default snapshot for zero-arg ReviewEngine (AG7) in [79fc834d](https://github.com/alexhawat/mergeCraft/commit/79fc834da656526009bef7a14adcb06fbf84bc4b)
- Reset engine timeout callback each run (AG7) in [a3a4ace0](https://github.com/alexhawat/mergeCraft/commit/a3a4ace03ac5990694c3e7b645f9e54b06a49bb3)
- Bind publication scope and snapshot settings (AG2) in [4180cf21](https://github.com/alexhawat/mergeCraft/commit/4180cf21be8f13bcd3645ab3353bc152fe6689f9)
- Raise dogfood token budget for this sweep PR in [307af7aa](https://github.com/alexhawat/mergeCraft/commit/307af7aa556b1b1f62d70bea466367bb547c7491)
- Close PR 495 CI and reviewer findings in [7ed8d8e8](https://github.com/alexhawat/mergeCraft/commit/7ed8d8e8d3ef1ac7c72a38a8a556b124994983a5)
- Distinguish unbound check-suite skip from empty failures in [9f6b3fcb](https://github.com/alexhawat/mergeCraft/commit/9f6b3fcb7b2363df1f26fa6a38ac0735bb8bd025)
- Fail-closed SARIF lines and drop unused adapter listing in [2e5521de](https://github.com/alexhawat/mergeCraft/commit/2e5521de751aef21c980f89a752351462e267d0d)
- Resume JSON object scan after skipped arrays in [46148d5e](https://github.com/alexhawat/mergeCraft/commit/46148d5e55316c3b806f6f4ef203342c044db8ce)
- Skip leading JSON arrays when extracting objects in [4b70d922](https://github.com/alexhawat/mergeCraft/commit/4b70d9229dffc969c7a958a156a430f3e1d4914c)
- Skip bad finding rows and stop packet reassembly in [a9087a37](https://github.com/alexhawat/mergeCraft/commit/a9087a37cb0ec6887987b56726b294852d234494)
- Finish remaining low Thermos quality findings in [31a81ff2](https://github.com/alexhawat/mergeCraft/commit/31a81ff2220b65bd74baee301472d03c36ee7c9c)
- Apply remaining branch and quality Thermos findings in [21315dbc](https://github.com/alexhawat/mergeCraft/commit/21315dbce0bdd4b6662619635d0dbec56575d423)
- Close remaining low Thermos findings in [a1c73831](https://github.com/alexhawat/mergeCraft/commit/a1c738318550d78448b3f6ec1037e41cee57eca8)
- Close remaining Thermos findings on lane A in [73661d3c](https://github.com/alexhawat/mergeCraft/commit/73661d3c2eef9a8ac98631c259b52322edc1fa99)
- Close Thermos findings from the analyzers-CI sweep in [5990ffc0](https://github.com/alexhawat/mergeCraft/commit/5990ffc0ae04e428774228a7b81fd28e5211369b)
- Approval gate reads agent findings in [30c3622d](https://github.com/alexhawat/mergeCraft/commit/30c3622d2de9a5c6291cc7936c1579034a56eae1)
- Unify publish short-id batch for body sections in [352bdb30](https://github.com/alexhawat/mergeCraft/commit/352bdb301f481d52b5539c2900eeda52c68d8f88)
- Refresh pre-rendered short ids at publish in [fbf78a3b](https://github.com/alexhawat/mergeCraft/commit/fbf78a3b86fefd987a5ca19944cc9ef1c305523a)
- Let an offline review record a terminal verdict in [118411e4](https://github.com/alexhawat/mergeCraft/commit/118411e483bcb97730c25e33004595b57c38f62b)
- Address mergecraft PR #442 review findings in [7b2fec4f](https://github.com/alexhawat/mergeCraft/commit/7b2fec4f3deb409e695adcac004b903554161001)
- Keep withdrawn findings out of recall deferred lane in [45e6f5f5](https://github.com/alexhawat/mergeCraft/commit/45e6f5f577f09ca8218251e26a9f0e85d98fe709)
- Dedupe recall against deferred overflow rows in [3da27bfa](https://github.com/alexhawat/mergeCraft/commit/3da27bfa2da520663e2438a25f6f068f4b817da0)
- Address thermo code-quality audit findings in [1b711526](https://github.com/alexhawat/mergeCraft/commit/1b711526512320cedc24059898cbef905c8c76dc)
- Preserve deferred overflow and pre-checkout ledger in [6ede2e79](https://github.com/alexhawat/mergeCraft/commit/6ede2e79420e823ec1bf4ec1dc4e1e22ba408c59)
- Correct ledger marker strip argument order in [9364907d](https://github.com/alexhawat/mergeCraft/commit/9364907d42d27c6acb01d062440c10a755e333d1)
- Thermo clean — ledger v2 strip and dead export cleanup in [333cff33](https://github.com/alexhawat/mergeCraft/commit/333cff339a1151e7f64268b8d2850d1b296e60c4)
- Remove thermo dead exports and corpus packaging in [43737919](https://github.com/alexhawat/mergeCraft/commit/43737919e339a837caf7b645c7119a52d83b8e28)
- Close remaining thermo wiring gaps in [9a1d71cd](https://github.com/alexhawat/mergeCraft/commit/9a1d71cd6fea981e74942bcbb18193cf317e6f12)

#### Review Record

- Re-finalize cached packet on outcome in [cd6ff87c](https://github.com/alexhawat/mergeCraft/commit/cd6ff87c91a03910f72f8b508be457f9a08ec8e5)
- Thermos turn 2 in [501ee610](https://github.com/alexhawat/mergeCraft/commit/501ee61079e06cabd1316a10ab7f4670001aa128)
- Thermos turn 1 in [6e5d813a](https://github.com/alexhawat/mergeCraft/commit/6e5d813afbefba98b6ea8bb0bc349a6c2f1020ac)
- Skip anchor index on hunkless diffs in [8612a8af](https://github.com/alexhawat/mergeCraft/commit/8612a8aff6192d208cb46de9a0bcf46eb1419396)

#### Reviewer Resilience

- Unblock CI after trust policy regression in [813352a9](https://github.com/alexhawat/mergeCraft/commit/813352a912c172a7384bff9f4c751f7945955fa1)
- Harden git config and review scope guards in [a6b96018](https://github.com/alexhawat/mergeCraft/commit/a6b9601811a682a62cb31208881b2eb355597983)

#### Runtime

- Fail-closed approval on budget exhaustion in [6bdc9882](https://github.com/alexhawat/mergeCraft/commit/6bdc9882f416d76ab0b6c7b011af8f137ff94372)
- Stop double-counting cached tokens in run budget in [2ba5eac2](https://github.com/alexhawat/mergeCraft/commit/2ba5eac2563f5d99629a2a0f1a7a234165f8851a)

#### Sandbox

- Keep fork headroom in the drop process cap in [0812846e](https://github.com/alexhawat/mergeCraft/commit/0812846e3bcfff3724b4f02139a03aa95b21de38)
- Size the process cap to the drop target uid in [95ea2a5e](https://github.com/alexhawat/mergeCraft/commit/95ea2a5e80c4a1e24013411607206253d2f0f399)
- Re-arm the parent-death signal after the drop in [d0c6ef60](https://github.com/alexhawat/mergeCraft/commit/d0c6ef60ebdaa59fb734e11e6755cf83644d8ea8)
- Resolve the sudo-elevated drop without the image policy in [704be3af](https://github.com/alexhawat/mergeCraft/commit/704be3afb09929df36449b6a9a80c9f537d09830)
- Drop root identity inside shell and analyzer namespaces in [bac1bb10](https://github.com/alexhawat/mergeCraft/commit/bac1bb108ed95d28b65a998e626379c662305b5f)
- Refuse --shell enabled without a backend in [66b12d95](https://github.com/alexhawat/mergeCraft/commit/66b12d95ff3a3786b82c084f830969fd0cc77e31)

#### Scm

- Bind one GitHub HTTP transport per event loop in [eb900251](https://github.com/alexhawat/mergeCraft/commit/eb9002519f20c133bc34fca9c429e7ee024f2b13)
- Satisfy mypy on ingress latin1 patch helpers in [98ac1ae8](https://github.com/alexhawat/mergeCraft/commit/98ac1ae8086ddc8a92a2ad8616a6214cc20e004b)
- Webhook ingress idempotency and header encoding in [404e77fa](https://github.com/alexhawat/mergeCraft/commit/404e77fa9f2f2aef260d427cd4958f35c488877d)

#### Security

- Re-pin the review tree baseline at checkout_pr in [a2f2cb94](https://github.com/alexhawat/mergeCraft/commit/a2f2cb94fd15c150ff3266cca0c03b3e656335ed)
- Skip analyzer runtime files in the review integrity hash in [2bcfb4bd](https://github.com/alexhawat/mergeCraft/commit/2bcfb4bda9fc290f17ba4445d41f2f8476191fdc)
- Scan emitted packets and stop suppressing mixed gate failures in [e9467dfc](https://github.com/alexhawat/mergeCraft/commit/e9467dfc7cd55ed6f26b922c1a09885dc828a4c3)
- Exclude Actions command-file channels from child env in [f9f6fba9](https://github.com/alexhawat/mergeCraft/commit/f9f6fba98908a2d37117c8d0fe892087884f92a0)
- Drop env-selected git config sources in [f460609b](https://github.com/alexhawat/mergeCraft/commit/f460609b236b7e1cc40517fe91779fd421b4980c)
- Close the sink-hit approval and gate-view gaps in [e26449d6](https://github.com/alexhawat/mergeCraft/commit/e26449d6aa0e03faa79246edd0dab3271ee5d797)
- Scan local sinks for credentials after the run in [9ac88de0](https://github.com/alexhawat/mergeCraft/commit/9ac88de0d34dd791eae7c86dd9ee5364df40d96e)
- Log cleanup and revocation failures at warning in [d179dfe2](https://github.com/alexhawat/mergeCraft/commit/d179dfe2c86541e30438446c7adf7d3d3019d80f)
- Allowlist child env and harden git subprocess env in [965bc183](https://github.com/alexhawat/mergeCraft/commit/965bc1837cbbc36cac5faf41b51d7eb4ac630e2e)
- Compose log redaction with run context in [47cd9d57](https://github.com/alexhawat/mergeCraft/commit/47cd9d57dc5ea134cbccff4d80bab097871330f3)
- One credential registry for fork guard and Codex auth in [e34805a1](https://github.com/alexhawat/mergeCraft/commit/e34805a1f10d301400284a039eb97d26e600d403)
- Stream broker SSE and align upstream timeout in [6d9781d3](https://github.com/alexhawat/mergeCraft/commit/6d9781d36b9388db50b3adb0801924b53745cf83)
- Broker base URL, pinned egress, and encoding headers in [8536320b](https://github.com/alexhawat/mergeCraft/commit/8536320b4e93a608a740c3f608fabcf1188824d9)
- Normalize broker paths and restore codex entry in [880aa1d6](https://github.com/alexhawat/mergeCraft/commit/880aa1d6fe89e507c6c3da0fe62fd045673ca86e)
- Harden credential broker for Thermos turn 1 in [1832efd0](https://github.com/alexhawat/mergeCraft/commit/1832efd01d658a1f581797717b0382164a1c0ba8)
- Pin git identity guards to live origin URLs in [35bca87a](https://github.com/alexhawat/mergeCraft/commit/35bca87a916c4f27cc6ac3e5f6cca08d73bb9aae)
- Harden git origin auth and integrity hashing in [57970ac8](https://github.com/alexhawat/mergeCraft/commit/57970ac8481b0b4087d850adf1eccdfae8e52749)
- Harden git fetch auth and integrity hashing in [dca1234b](https://github.com/alexhawat/mergeCraft/commit/dca1234b16aa380f61972fc30bfbf1687436c2d8)
- Tighten redaction and audit truncation verify in [c461b8ee](https://github.com/alexhawat/mergeCraft/commit/c461b8eedf8281382f7ad90a823740adb0faddf3)
- Enforce analyzer sandbox and scope infra findings in [732a1059](https://github.com/alexhawat/mergeCraft/commit/732a10594eb91bb44682f51e5e169350c0101e70)
- Drop dead SSRF branches hurting coverage floor in [142113e0](https://github.com/alexhawat/mergeCraft/commit/142113e0e68e6f9f91a3be27964357c2cdd3d7d3)
- Close lane A shell, sandbox, and git gaps in [ecab3d2d](https://github.com/alexhawat/mergeCraft/commit/ecab3d2dec26d140acbe6709035ae821029eecbb)
- Close lane A CI gaps for shell, sandbox, and opencode in [3a79b28c](https://github.com/alexhawat/mergeCraft/commit/3a79b28cfd38f2b18fb6bd33d39756a723019c08)
- Gate sandbox probe sudo behind CI guard in [f4b12106](https://github.com/alexhawat/mergeCraft/commit/f4b121063019f4b8cfc989804aaa8930f1ec4351)
- Fail closed on shell git boundary mounts in [ab33dcff](https://github.com/alexhawat/mergeCraft/commit/ab33dcffe618c5134434f9cb164cad828375dc82)
- Stop empty diff.external pin from breaking git diff in [09e99df5](https://github.com/alexhawat/mergeCraft/commit/09e99df5d73feab1a3e53fa87501f2a8c407a4bf)
- Lane A Thermos turns 2-3 follow-up in [4bd11536](https://github.com/alexhawat/mergeCraft/commit/4bd11536dadb01254dcff27664c0248d351e5401)
- Thermos turn 1 lane A integration fixes in [a0f73bbb](https://github.com/alexhawat/mergeCraft/commit/a0f73bbbad9db6fba74c01651aa06c5b638b3ff6)
- Sudo preserve-env by name and git invariant (AP4) in [eae75474](https://github.com/alexhawat/mergeCraft/commit/eae75474762028e2c92939df324972529113bd85)
- Per-client egress transport for DNS pinning (MCB-18) in [ee852413](https://github.com/alexhawat/mergeCraft/commit/ee852413d41894577bd61bf11a50b99a3bb9d319)
- Probe sandbox capabilities instead of CI (AP3) in [19cc199f](https://github.com/alexhawat/mergeCraft/commit/19cc199fadd458e9c6fe8f82aeaa4c283cd557fb)
- Gate privilege drop on image identity (AP6) in [c0d23663](https://github.com/alexhawat/mergeCraft/commit/c0d23663bf8a7f55b4d20a28df0b9b1a7b2ffac8)
- Narrow OpenCode review permissions (AP5) in [3553153d](https://github.com/alexhawat/mergeCraft/commit/3553153dd3ea890f01c195031dc1bc04f70dcce0)
- Harden root-side git argv and .git ownership (AP2) in [881d20f8](https://github.com/alexhawat/mergeCraft/commit/881d20f8024966a4d8af231be7c15b1650273a05)

#### Test

- Ignore a closed provider harness client in [da3a68fb](https://github.com/alexhawat/mergeCraft/commit/da3a68fb138340be31b6b9e3a65539e1d2eb97e2)
- Import anchor ceiling from review module in [0037de5f](https://github.com/alexhawat/mergeCraft/commit/0037de5f3732c330e20632f5193b72c0c6c761c1)
- Clear ambient GITHUB_ACTIONS in agent-local override test in [a87a3d4d](https://github.com/alexhawat/mergeCraft/commit/a87a3d4d04b13564a4c7b1462f5e46453cbf2940)
- Reconcile MCP and gateway tests for AG2 scope gates in [a91dab82](https://github.com/alexhawat/mergeCraft/commit/a91dab82e309e196fff24a1cb64f7c33c1e0d879)
- Wire reset_process_tracer_cache in OTLP exporter tests in [bca2e4e7](https://github.com/alexhawat/mergeCraft/commit/bca2e4e7800abb3e5131cc6e29ac23113553c246)
- Thermos info hygiene — cheat lint doc and fence path normalize in [75435ab6](https://github.com/alexhawat/mergeCraft/commit/75435ab6f42b0f640cc6d5803856d9f11661bc0a)

#### Tests

- Drop over-broad managed-provisioning skip in [1d66910f](https://github.com/alexhawat/mergeCraft/commit/1d66910fd89c338451752829acb045ee3caab497)
- Isolate offline cache tests from the ambient GitHub event in [8e132d38](https://github.com/alexhawat/mergeCraft/commit/8e132d38a07b76c6a1a0df55b6262d2b6165a898)
- Restore the parent-package attr after re-importing auth_cmd in [3100b2e4](https://github.com/alexhawat/mergeCraft/commit/3100b2e42c1a4f9bb9a54d5fe13ba7497a25c872)
- Clear test mypy errors and pin-guard doc drift in [#462](https://github.com/alexhawat/mergeCraft/pull/462)
- Isolate MCP server state under xdist in [4da685d8](https://github.com/alexhawat/mergeCraft/commit/4da685d83356258dd54a037c3f2f3ad64c8a4332)

#### Tracing

- Match reused OTLP exporters case-insensitively on OTel 1.45 in [aa747f07](https://github.com/alexhawat/mergeCraft/commit/aa747f075fd1441e2bc4d3208793e742bab4e194)
- Unwrap ToolResult text and stop array tag noise in [f70e93b7](https://github.com/alexhawat/mergeCraft/commit/f70e93b7269fafe6f8bde5a066c249c72ccbdc01)
- Show tool payloads in Datadog and drop the unused cost attr in [7f3edc03](https://github.com/alexhawat/mergeCraft/commit/7f3edc03b139ae0c9e7581ee7dd8c1c38dc3cfd5)
- Stop the tracer factory rebinding enterprise controls in [6a6a2fd2](https://github.com/alexhawat/mergeCraft/commit/6a6a2fd218455c9c4acbf3048c0ed00d8489fbfd)
- Decide the D7 export cap from snapshot provenance in [1a10691b](https://github.com/alexhawat/mergeCraft/commit/1a10691ba3e81aff586d6c5eb1da101b588c3329)
- Ignore fork YAML exportUntrustedContent in [ad61f1a6](https://github.com/alexhawat/mergeCraft/commit/ad61f1a6861c797398231dde74bb7b3d6a759c1e)
- Capture LLM bodies and parent tool.call spans in [6536a0c2](https://github.com/alexhawat/mergeCraft/commit/6536a0c257b90016a5d8beefcf25effdd9d450bf)
- Keep CLI region above Action overlay in [e68edde5](https://github.com/alexhawat/mergeCraft/commit/e68edde5542f9c937d45ae8936ad5ec09745c111)
- Keep Action input region over job env in [5a361de3](https://github.com/alexhawat/mergeCraft/commit/5a361de34824763d6812c36f9500b77d69efe22e)
- Honor MERGECRAFT_TRACING_REGION on Action Logfire in [7c2c241a](https://github.com/alexhawat/mergeCraft/commit/7c2c241ac53c8670cedcf0fe2e851fbef1d21130)
- Redact tool payloads as structures, not as text in [cd9f83d7](https://github.com/alexhawat/mergeCraft/commit/cd9f83d793c3b0987ddf1c85854b61c8b02a014a)
- Wire Logfire into the Action and ship the tracing extra in [039f773f](https://github.com/alexhawat/mergeCraft/commit/039f773f6ab290cf086e060c4f9313492d387b52)
- Extract enterprise reset seam for cache clear in [#509](https://github.com/alexhawat/mergeCraft/pull/509)
- Close trace redaction gaps (MCB-02/03/28/31) in [cdfe2bbb](https://github.com/alexhawat/mergeCraft/commit/cdfe2bbb6f2c3c81cb88178120ef5677038e9160)
- Gate claim_sink on sink transport topology in [928b0e8f](https://github.com/alexhawat/mergeCraft/commit/928b0e8f299c57342b9a632ff96bbe6530af45e8)
- Drop duplicate pending-sink reset in cache clear in [faee5c0b](https://github.com/alexhawat/mergeCraft/commit/faee5c0bfcf08fcf349a4e482ad8c4c34f9e054b)
- Discard stale claim_sink handoff under xdist in [34b41023](https://github.com/alexhawat/mergeCraft/commit/34b41023c46ec686406a80cbd1309df9d8f53d82)
- Record Gemini and Codex span token usage in [9067f9c9](https://github.com/alexhawat/mergeCraft/commit/9067f9c92599e8f66dae8f1c33a4d40927e8f1b5)

#### Trust

- Fail closed on unknown trust and named fallbacks in [2280decb](https://github.com/alexhawat/mergeCraft/commit/2280decba961e7ec79b6fb1a11af6086b8801030)
- Resolve the publisher login and record duplicate names in [e1b342bf](https://github.com/alexhawat/mergeCraft/commit/e1b342bf4f7688034b270d139251f89886f631ce)
- Enforce the shared-bot invariant over every source in [3e1d11f7](https://github.com/alexhawat/mergeCraft/commit/3e1d11f7a13c715844d4f0fb30bba744f7423195)
- Never consult /user for the Actions job token in [aff76ee9](https://github.com/alexhawat/mergeCraft/commit/aff76ee93c0c3acd29dcaef8ee6865619cf66b10)
- Refuse the shared Actions bot as authorship proof in [702efbfa](https://github.com/alexhawat/mergeCraft/commit/702efbfa089ef0f596fea2f4836ebbe352c30d8d)
- Check the bound PR and report removed surfaces in [77e7462f](https://github.com/alexhawat/mergeCraft/commit/77e7462f5a32713fe62a4a19698f7ea5e0799f4a)
- Bind a dispatch review from the composed prompt in [6949a901](https://github.com/alexhawat/mergeCraft/commit/6949a901b8faa18918808eb3e53512cb1eb255c7)
- Match linked-repo grants by slug and report the change set in [ff56a9c2](https://github.com/alexhawat/mergeCraft/commit/ff56a9c25bbff4a0124f6602115f738c727a0cae)
- Confine instruction reads and the Action startup env in [e5ffaa39](https://github.com/alexhawat/mergeCraft/commit/e5ffaa39db450f5ca7c714d047d9af79e2425974)
- Record the checkout diff and gate the checkpoint by author in [20ece21f](https://github.com/alexhawat/mergeCraft/commit/20ece21fe3802550f7528887e647fa85a7214f24)
- Bind the reviewed PR before trust and credentials in [b5cae49a](https://github.com/alexhawat/mergeCraft/commit/b5cae49a8b8670d386e3f2d784e173438aad94c9)
- Reconcile CI with sandbox gate and fork E2E in [e157462c](https://github.com/alexhawat/mergeCraft/commit/e157462c917f42275363eeca00b0c018e0d2d09e)
- Route chain picks through has_credentials_for_slug in [71893d67](https://github.com/alexhawat/mergeCraft/commit/71893d670f55cd9a4b637a076977608cc8c628c3)
- Complete fork credential and local egress edges in [2e634517](https://github.com/alexhawat/mergeCraft/commit/2e634517aa38f037344a83455fc91b5d9e08ef56)
- Harden egress gate and fork credential coverage in [761bc7bd](https://github.com/alexhawat/mergeCraft/commit/761bc7bde076876eef9bb4fd609b7a5e360201cb)
- Wire analyzer egress policy into execution path in [85ecd168](https://github.com/alexhawat/mergeCraft/commit/85ecd168e27fc2cc0551a140b5d7a43ffa7a1084)
- Resolve the trust tier from one event name, not two in [e656debc](https://github.com/alexhawat/mergeCraft/commit/e656debc215cb5b993edc56b5ea9020558d58aac)

#### Verify

- Honour negation before the special-case phrases in [c6a7bf78](https://github.com/alexhawat/mergeCraft/commit/c6a7bf78ae26ef6986c536ba5faec11774fe14cc)
- Never pass negated criteria; stub is a fallback in [fc1d4967](https://github.com/alexhawat/mergeCraft/commit/fc1d4967f80ef654e0f858d383606e29f2bd5095)
- Keep a Jev transport failure a named unverified result in [c39f6873](https://github.com/alexhawat/mergeCraft/commit/c39f68730be3a0c4dce99ae0931434ae86a631e1)
- Redact type-action secrets from report steps in [1c711663](https://github.com/alexhawat/mergeCraft/commit/1c7116630a4dfd5c77209c788b46fb24148398c2)
- Suppress all screenshots until pixel redaction in [86dae603](https://github.com/alexhawat/mergeCraft/commit/86dae603720c4979072fa1125acad5a70f5f5ee2)
- Suppress manual-auth screenshots until redaction in [31dc5cb3](https://github.com/alexhawat/mergeCraft/commit/31dc5cb3fbf1e5c0dedbbfe444557371a5e7a80c)
- Write report when browser actions fail in [e6cf8fcf](https://github.com/alexhawat/mergeCraft/commit/e6cf8fcf73439ba61d38db4ff0b4f53a4c2222d8)
- Retry ConnectionRefusedError on startup in [011d0c10](https://github.com/alexhawat/mergeCraft/commit/011d0c107138d717592eee8b931d96eff0701581)
- Skip screenshot when no artifacts dir in [aa9e75fc](https://github.com/alexhawat/mergeCraft/commit/aa9e75fcb2c8c3623f3c6e9c7dd7c3b6eff73c63)
- Order navigate except clauses for pyright in [7aabe80c](https://github.com/alexhawat/mergeCraft/commit/7aabe80cd3b069e50c472aba9773b7372948fd9e)
- Fail closed without the browser extra in [846a83a0](https://github.com/alexhawat/mergeCraft/commit/846a83a09602a32e5e01a8929959d83181173e09)
- Honor Actions event trust on the CLI in [73b1f452](https://github.com/alexhawat/mergeCraft/commit/73b1f452e1daa8d0751b37d81fecd9d4c8c157bc)
- Close Playwright on the start loop in [9ad1f55b](https://github.com/alexhawat/mergeCraft/commit/9ad1f55ba8702c953406860aa31befda224a8d38)
- Drive Chromium with async Playwright in [9b0f8195](https://github.com/alexhawat/mergeCraft/commit/9b0f8195fd8099f31962c1125dcae6da0ba6ed1e)

#### Workflows

- Hand the example gate the verdict, not the packet in [60c1652e](https://github.com/alexhawat/mergeCraft/commit/60c1652e3ee8ff3c887cc82bb29c658120e7cc50)
- Hand evidence packets between steps as files in [7c4b33db](https://github.com/alexhawat/mergeCraft/commit/7c4b33db7ccce1f508ae60e83f15da0d33c3a31f)
- Harden consumer scaffolds and pin by commit in [f9d466fa](https://github.com/alexhawat/mergeCraft/commit/f9d466fa0442ca14610129081f23701ccb4a9660)
- Stage trusted fallback scripts and bind the gate in [f09a978c](https://github.com/alexhawat/mergeCraft/commit/f09a978ca9a298c2dce0ac5a7ad69ad433961713)

#### Other

- Soft target, hard ceiling, and phase attribution in [#571](https://github.com/alexhawat/mergeCraft/pull/571)
- Close failed streams and preserve loopback routing in [4dbc61e5](https://github.com/alexhawat/mergeCraft/commit/4dbc61e540c2eae9baab01e5071934967ec60c03)
- Stamp the model that ran when the allowance is spent in [68dccf1f](https://github.com/alexhawat/mergeCraft/commit/68dccf1fc96e3b26e26b7311770397cc677d18e8)
- Read the packet file the self-review uploads in [8d40fc2b](https://github.com/alexhawat/mergeCraft/commit/8d40fc2b142d4ffd6221c7499bfb9160affe38be)
- Retain utils/token.py floor pending replacement in [27d4cfcc](https://github.com/alexhawat/mergeCraft/commit/27d4cfccb2ddf2c4e043790b168f3c39fa256669)
- Register the Jev gate page in the docs manifest in [f216886b](https://github.com/alexhawat/mergeCraft/commit/f216886b136f3f41344efe250f86f464e595c537)
- Accept configuration_error exit on fork PRT in [5b1bfa63](https://github.com/alexhawat/mergeCraft/commit/5b1bfa631e3e8abd2c1afce720fe8851300d7751)
- Relocate audit log and harden MCP port identity in [8693314f](https://github.com/alexhawat/mergeCraft/commit/8693314f253c6f98ee9eced70ead12ba687c7cea)
- Export the Action pin into the scaffolded workflow in [349f0ea8](https://github.com/alexhawat/mergeCraft/commit/349f0ea80960b91d7ba9bcf4798840a80a9ffba4)
- Exclude nested node_modules and pnpm store from the review hash in [3e022ac4](https://github.com/alexhawat/mergeCraft/commit/3e022ac462ec5875d9249c4518e97f26cdf6865c)
- Preserve custom loguru sinks on force reconfigure in [1f354bb6](https://github.com/alexhawat/mergeCraft/commit/1f354bb6f62668674ce98a1972b66ac5c62128a5)
- Fail when agent findings are invalid in [654d99f9](https://github.com/alexhawat/mergeCraft/commit/654d99f95ce42456ae0d3a7cbac206689c8ad604)
- Pipeline taxonomy and executor honesty (AG6) in [8cc87b4d](https://github.com/alexhawat/mergeCraft/commit/8cc87b4d608aa9dc87b54166f7ab039202570cb8)
- Accept PEP 440 versions in the compatibility gate in [58481a84](https://github.com/alexhawat/mergeCraft/commit/58481a8404b285810932f2965b37aaeeb431ddf7)
- Fail when the release tag does not exist in [2b8aaf15](https://github.com/alexhawat/mergeCraft/commit/2b8aaf15c3e7fa6175b64d6ef3ffdbd3ec8deee1)
- Use chown -h for symlink-safe workspace prep in [bdfd3d83](https://github.com/alexhawat/mergeCraft/commit/bdfd3d83496e435d5ed2002279846adf306ef944)
- Close PR #494 registry review blockers in [a061bfdc](https://github.com/alexhawat/mergeCraft/commit/a061bfdc6f2cf2c859855c73562b1b4da9b95a07)
- Scrub env and neutralise file args in gates in [2d475868](https://github.com/alexhawat/mergeCraft/commit/2d475868cbb4541caca4fa1a0d0a9e091641526c)
- Address Thermo code quality findings in [87f0f60c](https://github.com/alexhawat/mergeCraft/commit/87f0f60ce4f4371b07fd8de1d4a5b0a7fd69b5b9)
- Derive run-start credential checks from the auth kind in [22621515](https://github.com/alexhawat/mergeCraft/commit/22621515785711c5022bde6ff0280248c40a3d07)
- Check authors on a first push to a new remote branch in [451c7d70](https://github.com/alexhawat/mergeCraft/commit/451c7d70bcc2708d8a776883446ff862f93fdc03)
- Keep registry credentials over legacy env vars in [75695a8c](https://github.com/alexhawat/mergeCraft/commit/75695a8c9e67690f1172efe1579a3d55a0b38033)
- Fail closed when the untrusted sandbox cannot run in [988251d3](https://github.com/alexhawat/mergeCraft/commit/988251d364645aeca243878cc364f13ee7d00c4b)
- Address Thermo code-quality re-review findings in [516dd5a1](https://github.com/alexhawat/mergeCraft/commit/516dd5a10e2bf52c42c526ae8856e62eb4d40b1d)
- Derive terminal verdict from finalized findings in [ce674e7a](https://github.com/alexhawat/mergeCraft/commit/ce674e7afd100e60b32d5968ae30df80c7853771)
- Close the remaining #1012 review findings in [539e1421](https://github.com/alexhawat/mergeCraft/commit/539e14216f1b83cef5db50cdb7c4e86126318345)
- Emit OpenCode provider blocks for registry-only dual reviewer in [6fc8e8b9](https://github.com/alexhawat/mergeCraft/commit/6fc8e8b9bd6cad3e73faf6df1ca402e6e85d652b)
- Defer workflow manifest parse on local roster auth in [42f52219](https://github.com/alexhawat/mergeCraft/commit/42f5221986ed50b91b6ced1aacf17908d99d9392)
- CI regressions for provider blocks and zero-token cost in [276b2971](https://github.com/alexhawat/mergeCraft/commit/276b2971cff1a6971dc0af1224f6ec2d90c74542)
- Second-reviewer OpenCode providers and local roster auth in [5465ce05](https://github.com/alexhawat/mergeCraft/commit/5465ce059a53d0ca8a88f45581be550629f1e268)
- Satisfy ruff on curated model catalog in [6df921d6](https://github.com/alexhawat/mergeCraft/commit/6df921d69590cb56591b60a6dda3cac96d64559e)
- Preserve legacy models list on committed assign-model in [d8d9132f](https://github.com/alexhawat/mergeCraft/commit/d8d9132fb41a51f0ea7cfc639133f2efe8cef524)
- Keep NOUS_API_KEY on legacy credential path in [cbb98164](https://github.com/alexhawat/mergeCraft/commit/cbb981643dae3b035f40239e2afc82d5374e8d99)
- Land handed-off capture, scoping and packaging work in [0a77ce20](https://github.com/alexhawat/mergeCraft/commit/0a77ce20ee17df95b159818eff348172be8d4ba0)
- Bound negative memory and defer the sarif_upload default in [ad45304e](https://github.com/alexhawat/mergeCraft/commit/ad45304eb520100c6b4e2c9139f277805e57847a)
- Skip managed analyzer cache in offline diffs in [021dd273](https://github.com/alexhawat/mergeCraft/commit/021dd273fe7e030735da21c118a57e0edc3421c2)
- Root complete review traces in [327a6d2c](https://github.com/alexhawat/mergeCraft/commit/327a6d2c8fe0729262e790a22a7a005612bf1ec8)
- Preserve colon git pathspecs in [6e2e09ed](https://github.com/alexhawat/mergeCraft/commit/6e2e09edc2182b7deb5311c8b79d9f630bf56899)
- Record exact trajectory read operands in [a0af80d9](https://github.com/alexhawat/mergeCraft/commit/a0af80d901c38432f3d163a121ff69c38f638735)
- Detect installation token revoke failures in [9e8b327e](https://github.com/alexhawat/mergeCraft/commit/9e8b327e9ba2fe9d24d051d459f50f28a8af38b4)
- Separate reviewer and Git app tokens in [a51188bd](https://github.com/alexhawat/mergeCraft/commit/a51188bd2d70a1793b45c0ad8176f6045e078c82)
- Preserve uppercase source paths in redaction in [9afaacec](https://github.com/alexhawat/mergeCraft/commit/9afaacec29afd79680515b984b199726cca5547b)
- Sanitize trajectory evidence before persistence in [9c101677](https://github.com/alexhawat/mergeCraft/commit/9c101677dcdedb2c5982492af8c5128e7fdf05ab)
- Clear recovered publication failure in [10130b5e](https://github.com/alexhawat/mergeCraft/commit/10130b5ed76aa790f3bdb97be508aa377c18a029)
- Derive verdict from finalized findings in [a648bef2](https://github.com/alexhawat/mergeCraft/commit/a648bef2abe5a04e2c1e3399ac62e06703a0affb)
- Gate consumer MCP and keep userspace egress alive in [eb4e5d42](https://github.com/alexhawat/mergeCraft/commit/eb4e5d42ae1f6d09749b798c67e50881088b25b5)
- Repair three seams the pre-0.0.1 merge exposed in [0acc58cb](https://github.com/alexhawat/mergeCraft/commit/0acc58cb055df5d2b4de4aa290e351f6030fb867)
- Catch the errors httpcore raises, redact text beside JSON in [3f2c2e3e](https://github.com/alexhawat/mergeCraft/commit/3f2c2e3ef4ba60423b9085d705acbdb19155ceff)
- Pinned-address failover and empty archive members in [498a2e46](https://github.com/alexhawat/mergeCraft/commit/498a2e46952ec3e83083884c2835af3bc0a0b726)
- Thermos branch review round 3 final in [6f65e7d5](https://github.com/alexhawat/mergeCraft/commit/6f65e7d5588c03362a8e2a2c01154e00ca160865)
- Thermos branch review round 1 in [3316e65a](https://github.com/alexhawat/mergeCraft/commit/3316e65a1150ba21b0b008685543b2e1cb1c1401)
- Address Thermos round 3 explain replay findings routing in [bbfcc5a2](https://github.com/alexhawat/mergeCraft/commit/bbfcc5a2f8c7940d68bc7068aac68a67215b2a8e)
- Address Thermos round 2 findings for lane C in [8483c3ab](https://github.com/alexhawat/mergeCraft/commit/8483c3ab4d2e963f0e5aa46f97e01ee0914cba92)
- Address Thermos code quality findings for lane C in [bb45b595](https://github.com/alexhawat/mergeCraft/commit/bb45b595b89c57b3bfb3b59713c696c2cda3fbfe)
- Address Thermo BR2-L1–L10 low findings on 22c sweep in [e7b62e2a](https://github.com/alexhawat/mergeCraft/commit/e7b62e2a5894b1680e6182fbd013d09ac1e7f587)
- Address Thermos branch review findings on sweep branch in [6a8ab55c](https://github.com/alexhawat/mergeCraft/commit/6a8ab55c958258e3fadec99cc84908b82fb260e7)
- Read \__version__ from the installed distribution in [1d6edf3d](https://github.com/alexhawat/mergeCraft/commit/1d6edf3dc21f4e7097facc78bee2b70725d40339)
- Reuse offline analyzer pre-pass in run_analyzers in [93ff6489](https://github.com/alexhawat/mergeCraft/commit/93ff64899346d66e7d3b930a4d2d6e11a1aa0c70)

### Changed

#### Agents

- Remove unused AgentRunContext fields (D14) in [b92d7f31](https://github.com/alexhawat/mergeCraft/commit/b92d7f311e647594662a349d5db90f928a50d70a)
- Remove unused post-run reflection helpers in [636578d7](https://github.com/alexhawat/mergeCraft/commit/636578d7938ad1a1e584bc3840423337f13c0fef)
- Remove unused on_tool_use and AgentToolUseEvent in [#725](https://github.com/alexhawat/mergeCraft/pull/725)
- Remove unused on_activity_timeout in [#722](https://github.com/alexhawat/mergeCraft/pull/722)
- Remove dead helpers and re-export shims (A2) in [#627](https://github.com/alexhawat/mergeCraft/pull/627)
- Extract codex_broker module for Thermos turn 2 in [6ac36051](https://github.com/alexhawat/mergeCraft/commit/6ac36051f852aeea008e003ac194aac5fbbc5d17)
- Make Nous an ordinary registry provider in [2669e327](https://github.com/alexhawat/mergeCraft/commit/2669e32718030737339f0f0f908543d9bbfc3fa4)

#### Analyzers

- Dedupe diff-tool constants, drop dead registry API in [1bf80ac3](https://github.com/alexhawat/mergeCraft/commit/1bf80ac32c17f3e7070a5714dfa5dbb6e908d7f9)
- Nightly audit cleanup A1 — remove dead surface in [#626](https://github.com/alexhawat/mergeCraft/pull/626)
- Use antislop.scopes as the shared suffixes in [cfaf19d1](https://github.com/alexhawat/mergeCraft/commit/cfaf19d116f0465e34d315a0d0d9a1c7adfe2141)

#### Ci

- Remove unused multi-provider registry stubs in [9ccc6d98](https://github.com/alexhawat/mergeCraft/commit/9ccc6d98295560284b65807468b0ac7873ba677a)
- Move SARIF ingest to mergecraft.ci in [bb89e7aa](https://github.com/alexhawat/mergeCraft/commit/bb89e7aafbbce6ddf3d628edfef422bdaefb59b9)
- Resolve the PR number on workflow_dispatch in [b31a7360](https://github.com/alexhawat/mergeCraft/commit/b31a7360e6433f3b476795c94d4a3d9db5b2d518)
- Share unavailable CI payload and fail-closed listing in [90e79efb](https://github.com/alexhawat/mergeCraft/commit/90e79efbebb837183c2b64bf6fa5a887e532784f)
- Require listed runs and share GitHub send path in [d7dba24c](https://github.com/alexhawat/mergeCraft/commit/d7dba24ca999e97c040c7385a3bd415ebc6c9ab4)
- List check-suite runs once and download via GitHubClient in [ede67a4b](https://github.com/alexhawat/mergeCraft/commit/ede67a4bc3c65ed0fcaf63abc6f1338f17870bb1)
- Use one GitHubClient for SARIF ingest in [e30c1f3c](https://github.com/alexhawat/mergeCraft/commit/e30c1f3c08d193a450ef3f82bc6b77de120221fe)

#### Cli

- Give CLI JSON its own schema version constant in [#777](https://github.com/alexhawat/mergeCraft/pull/777)
- Remove dead explain branching after review-id check in [c3904d1e](https://github.com/alexhawat/mergeCraft/commit/c3904d1e3b3443d5439523a62262fb7759a5c9e1)

#### Config

- Drop a redundant import suppression in [6002fe44](https://github.com/alexhawat/mergeCraft/commit/6002fe44a946fcb7d35f7c07be27ae11d0c3a8b6)
- Drop the unused hosted-plan residue in [20c835b1](https://github.com/alexhawat/mergeCraft/commit/20c835b1d3ef3f0f796d632c3fb7fc9573a1e1aa)
- Resolve the config file once for every read view in [c285cce0](https://github.com/alexhawat/mergeCraft/commit/c285cce0af8268e9b486e0e009074139831edeab)

#### Mcp

- Keep \_EXACT_NAME_EXCEPTIONS out of __all__ for a clean merge with #1046 in [f445d553](https://github.com/alexhawat/mergeCraft/commit/f445d553ffa097c935347be17ec39a1a118d373e)
- Remove process_state shim and git_askpass_path bookkeeping in [#636](https://github.com/alexhawat/mergeCraft/pull/636)
- Complete Thermos quality consolidation in [5e551af4](https://github.com/alexhawat/mergeCraft/commit/5e551af436af2589445aece19f29b6c411d90d26)
- Remove dead codegen API and dedupe role dispatch in [01772814](https://github.com/alexhawat/mergeCraft/commit/0177281407fa1dbe57e877cba5adca926be26eeb)
- Zero Thermos quality findings in [84a88438](https://github.com/alexhawat/mergeCraft/commit/84a88438da1ebe3c9a2508d5306be5dacf1904a7)
- Resolve Thermos P2/P3 findings in [157fb2e2](https://github.com/alexhawat/mergeCraft/commit/157fb2e26e417cc8eb7098c46e74f681ace42ec2)

#### Redaction

- Preserve delimiters after matching values in [564cfc27](https://github.com/alexhawat/mergeCraft/commit/564cfc272c56050b26d9467f50ded2bde062a290)
- Thermos CQ round 1 fixes in [867ceeab](https://github.com/alexhawat/mergeCraft/commit/867ceeab6460f9ad5fd918b7c8e9c125a9e9767e)

#### Review

- Clear low thermo type and dead-param findings in [44501732](https://github.com/alexhawat/mergeCraft/commit/44501732b8ab39e3ac36894590c5af0e64b8479c)
- Tighten typed ToolState and deferred row helpers in [c7b469bd](https://github.com/alexhawat/mergeCraft/commit/c7b469bd1e61c4ca8679b85af96d74de3a8a0ddf)
- Eliminate redundant publish and eval scans in [4749196d](https://github.com/alexhawat/mergeCraft/commit/4749196d809068732898eab054ff79e362cc7fdd)
- Clear low thermo code-quality findings in [a1685e1c](https://github.com/alexhawat/mergeCraft/commit/a1685e1cfd33f92c479b1bfbd4e5d06ca793b18d)
- Clear remaining low thermo findings in [97fe2616](https://github.com/alexhawat/mergeCraft/commit/97fe2616ef9bebcd54b1676c01b559928df93bfa)
- Fix low thermo code-quality findings in [561a7ab8](https://github.com/alexhawat/mergeCraft/commit/561a7ab842e4b56c23c7e83cbb38ae5e7c75c6a8)

#### Scm

- Remove dead GitLab stub and unused package facades in [#637](https://github.com/alexhawat/mergeCraft/pull/637)
- Share ListedItems as the catalog contract in [472b8e89](https://github.com/alexhawat/mergeCraft/commit/472b8e895d61abceff0235d05f7e39df37aa817a)

#### Other

- Remove unwired Codex writeback post hook in [#644](https://github.com/alexhawat/mergeCraft/pull/644)
- Extract graph/auth layers and fix multi-reviewer merge in [ed617c6e](https://github.com/alexhawat/mergeCraft/commit/ed617c6ee62e686c67b9c69f38cc17092e1a4e88)
- Remove unused Starlette /healthz app in [c3961443](https://github.com/alexhawat/mergeCraft/commit/c396144308485863c3c0631b3c3218bdfb51724b)
- Remove unused ablation harness in [5f858535](https://github.com/alexhawat/mergeCraft/commit/5f8585350a92016d0264d4c7b2fcc32a69192859)
- Split finding merge out of the CI cycle in [6c750e0c](https://github.com/alexhawat/mergeCraft/commit/6c750e0c18518d63353095d0daa0855bffb4cc0b)
- Remove dead trust gate surface (B4) in [#638](https://github.com/alexhawat/mergeCraft/pull/638)
- Remove unwired perf and dead exports in [12cd0f69](https://github.com/alexhawat/mergeCraft/commit/12cd0f691f21ab4f97e9ec7fe4436bbc355eb927)
- Thermos hygiene for scope and stream handling in [ba278578](https://github.com/alexhawat/mergeCraft/commit/ba2785781c5c33865b9cd7a534680de43e43dad0)
- Remove unused public_comments pass-through in [c6d9cf56](https://github.com/alexhawat/mergeCraft/commit/c6d9cf56be41f49c9ab5e81c443ea78e17bfff65)
- Drop unused INPUT_TRACING_REGION Action branch in [d2d1ff5a](https://github.com/alexhawat/mergeCraft/commit/d2d1ff5a29505b3c1f0fd298af93662315e3af1e)
- Remove unused workflow permission port in [#712](https://github.com/alexhawat/mergeCraft/pull/712)
- Remove unused activity-timeout factory in [#717](https://github.com/alexhawat/mergeCraft/pull/717)
- Drop Playwright for browser-use + JEV stack in [4d71fdf3](https://github.com/alexhawat/mergeCraft/commit/4d71fdf34db6c4f557b3743d2a283d8c3e94a1a0)
- Move test seams out of the runtime package in [f596094b](https://github.com/alexhawat/mergeCraft/commit/f596094bac76267b49feed391da8a6b1f5a4e767)
- Delete unwired provider, context and profile seams in [ded23444](https://github.com/alexhawat/mergeCraft/commit/ded23444974c1c9019315ea138b9421d4c000c12)
- Thermos CQ round 3 final fixes in [0f214d91](https://github.com/alexhawat/mergeCraft/commit/0f214d9124702e42994ce1fc592f6035e94a8bba)
- Address Thermos code-quality findings on sweep branch in [aeb051e7](https://github.com/alexhawat/mergeCraft/commit/aeb051e76153bb339162597f03421576e81799de)

### Docs

#### Changelog

- Keep every 0.1.0a3 bullet a complete sentence in [09606cba](https://github.com/alexhawat/mergeCraft/commit/09606cbac4d81b2a8f85cb7ad21842a6add69a8f)
- Compact the 0.1.0a3 release notes in [7ed0982c](https://github.com/alexhawat/mergeCraft/commit/7ed0982c6b0ec21695bdefb38ab09144a6706359)
- State what 0.1.0a3 ships and does not in [14c58bf5](https://github.com/alexhawat/mergeCraft/commit/14c58bf5252668b4e0ddb5ddcab71e9625d001b3)
- Analyzer and evidence hardening; verifier seam test in [171d6797](https://github.com/alexhawat/mergeCraft/commit/171d679732eceb05ec4262e333171ee3ec26fd7a)
- Record the ci, config, release and housekeeping changes in [792e780b](https://github.com/alexhawat/mergeCraft/commit/792e780b3888ca130279ebc6c20f2746629936fa)
- Note opencode harness auth fixes in [6880a2fc](https://github.com/alexhawat/mergeCraft/commit/6880a2fc3695d90dee47a933c5eac3e7abfcb19f)
- Note the removed inert seams in [ad12d289](https://github.com/alexhawat/mergeCraft/commit/ad12d28987bb9e3c87d82cfd3d013d0bffe04c7c)
- Note the fail-closed tracing and one .env reader in [66076be9](https://github.com/alexhawat/mergeCraft/commit/66076be914bb4c0c1927683b9dbf7ec12c558a3b)
- Note verdict publication and fail-closed trust fixes in [c1d5798a](https://github.com/alexhawat/mergeCraft/commit/c1d5798a3f90b0e6f6bd1a65c860f9704022266c)
- Record evidence-based CI attribution in [7ae51e5e](https://github.com/alexhawat/mergeCraft/commit/7ae51e5e6cf631ce000ce6d5c9a9d578bb78a2ca)
- Record gate, matching and verify-behaviour changes in [7dade68f](https://github.com/alexhawat/mergeCraft/commit/7dade68f6475c3dd07910cbaf43c02b967c9fb12)
- Record sandbox and privilege hardening in [7a128819](https://github.com/alexhawat/mergeCraft/commit/7a1288199875cfa795a2c1360531f73516726961)
- Record the self-review trust hardening in [7e1a8a66](https://github.com/alexhawat/mergeCraft/commit/7e1a8a66ed7077dacdbcf4cca466093db79cc9df)
- Note the CI gate, live-result and dependency fixes in [9fc355e8](https://github.com/alexhawat/mergeCraft/commit/9fc355e8e1b4790a076c922f282c9f3885174058)
- Record credential logging and cleanup hardening in [e8463441](https://github.com/alexhawat/mergeCraft/commit/e8463441cb8e200db4a407ac97a0bcc3972a6753)
- Note the trust-boundary fixes in [af49c1a1](https://github.com/alexhawat/mergeCraft/commit/af49c1a159be343d31233f39de08881b082b275b)
- Record the agent pipe and tracing fixes in [b748895d](https://github.com/alexhawat/mergeCraft/commit/b748895daf36e981b716b3ed4ba0f2fda437c4b5)
- Record sticky-comment ledger and provenance fixes in [0e93b0eb](https://github.com/alexhawat/mergeCraft/commit/0e93b0eb48c883ea0cc33bf9f7301cd5d54926a4)
- Complete remediation summary in [b754b7b4](https://github.com/alexhawat/mergeCraft/commit/b754b7b4ce046440babfe11805f93c8633727564)
- Clarify remediation readiness in [6b0b94f8](https://github.com/alexhawat/mergeCraft/commit/6b0b94f85f9ba989774f2198dba86732ab7879e1)
- Summarize remediation hardening in [a2825471](https://github.com/alexhawat/mergeCraft/commit/a2825471bdec728cb6b4498d791c6f2803cbd99f)
- Note the live verify driver and Jev seam in [bccee3c2](https://github.com/alexhawat/mergeCraft/commit/bccee3c252584f52662480fe1eca79df60dd9101)
- Note shadow target, flywheel ingest, CLI JSON version in [c86fede5](https://github.com/alexhawat/mergeCraft/commit/c86fede527a4d67b875948d9fd9880a3883ae5ec)
- Note coverage marker, token floor, and suite honesty in [873ab098](https://github.com/alexhawat/mergeCraft/commit/873ab098c2b22344e69ecbc59c8c6775fb457caf)
- Note gate determinism and review-record changes in [f122db39](https://github.com/alexhawat/mergeCraft/commit/f122db3937972750a19322ad9cf1c60d0e73d3d0)
- Note CRAP and mutation evidence for #714 in [e215afca](https://github.com/alexhawat/mergeCraft/commit/e215afca08ea7cefd19f2066bb8481f69d332fd0)
- Consolidate audit-r2 lane a findings to one bullet each in [d54b94b2](https://github.com/alexhawat/mergeCraft/commit/d54b94b2bf15176969630510166d676fba816643)
- Record broker streaming and proxy fixes in [071dd385](https://github.com/alexhawat/mergeCraft/commit/071dd385bb7ce1bc5b95d02ecbb5406433a90191)
- Record the claude --verbose fix in [02800680](https://github.com/alexhawat/mergeCraft/commit/028006801196d04834e85d1b62e39475ff7e220f)
- Note the provider URL validation hardening in [d2ad2ee9](https://github.com/alexhawat/mergeCraft/commit/d2ad2ee9a9e414deccfb5ed589b7a1503facc5d3)
- Note the PR 498 review fixes in [6b11f904](https://github.com/alexhawat/mergeCraft/commit/6b11f904c97eb1b2768711328a9632f9dce8d1e3)
- Note the model precedence and offline verdict fixes in [37f84189](https://github.com/alexhawat/mergeCraft/commit/37f841895ca5072a70f19bad78939c6e95962924)

#### Cli

- List eval ingest in [84451922](https://github.com/alexhawat/mergeCraft/commit/844519224b623a61b6624ab8d6cecb6ce6f2853f)
- Add audit verify to generated reference in [5698112b](https://github.com/alexhawat/mergeCraft/commit/5698112bddf30d3276643c92f18939b38c459071)
- Provider registry CLI reference in [3de4f1f2](https://github.com/alexhawat/mergeCraft/commit/3de4f1f2022d08a5a48d0fbdf91ab8ba1df49f3f)

#### Evidence

- Stop the fixture notes from closing #737 in [005cbd82](https://github.com/alexhawat/mergeCraft/commit/005cbd826cee5cb04b22b90540da84192ce0c1ab)
- Scope the shadow job as a fixture replay in [8d7d9cc7](https://github.com/alexhawat/mergeCraft/commit/8d7d9cc7d56d11b7b1f0949c146c85226c7984e1)

#### Plan

- Record focused verification and remaining prerequisites in [8716bba8](https://github.com/alexhawat/mergeCraft/commit/8716bba8092161c69d6f457c7c100112c569e04e)
- Record passing CI and parity follow-up in [2850ef8f](https://github.com/alexhawat/mergeCraft/commit/2850ef8f59bdf5c0d700457b4d48dedcb0690c91)
- Record coverage fixture correction in [68e56cd9](https://github.com/alexhawat/mergeCraft/commit/68e56cd9405d4512b8963113f7a8140af8f01c1a)
- Record full baseline and cache verification in [a0103ba4](https://github.com/alexhawat/mergeCraft/commit/a0103ba4bf74d65c8a3e37a29e04ce1482a3976b)
- Refine analyzer cache contract in [cf123d7e](https://github.com/alexhawat/mergeCraft/commit/cf123d7e0ee2188d869b6624b68551fc2dd11e45)
- Record current remediation state in [98c4874b](https://github.com/alexhawat/mergeCraft/commit/98c4874b8b4eccbae0032e588e2e4aa00d7eb62c)
- Record final feature integration checks in [d2e55271](https://github.com/alexhawat/mergeCraft/commit/d2e55271eead551711f354d013473f0228b58765)
- Record shard and trajectory verification in [88ad50fe](https://github.com/alexhawat/mergeCraft/commit/88ad50fef694d64c5d2b814b5bd668e3a4d6ab45)
- Reconcile merged plans and evaluation evidence in [f233ec7b](https://github.com/alexhawat/mergeCraft/commit/f233ec7b8e473b906c2664c3c8b51d06b8b3edb1)
- Record tracing and calibration verification in [c3a3d78e](https://github.com/alexhawat/mergeCraft/commit/c3a3d78edb7ff9e84117203e8190429fd49124ed)
- Record evidence checks and publication prerequisites in [8ac00cc2](https://github.com/alexhawat/mergeCraft/commit/8ac00cc2b80858d96fdefe9639fee775444145c2)
- Record token and adjudication verification in [297707f5](https://github.com/alexhawat/mergeCraft/commit/297707f5ffab9b8e98ed477436557c6b6608ef59)
- Include token revocation response checks in [b5ef858f](https://github.com/alexhawat/mergeCraft/commit/b5ef858fd2accf5b5fa59f97290829142c69cc6c)
- Record independently verified runtime fixes in [ccbe4981](https://github.com/alexhawat/mergeCraft/commit/ccbe4981890c09232ac69463565a4a6883f9273f)
- Add reproduced filename redaction defect in [91ae8a5c](https://github.com/alexhawat/mergeCraft/commit/91ae8a5cc230e7d8edb5ba4c8b7cb15a0b3b9cd9)
- Track implementation and provisioning follow-up in [e9adc022](https://github.com/alexhawat/mergeCraft/commit/e9adc022805784852e5386e5d5183d8fc6201c60)
- Audit open issues and define remediation in [861b94ce](https://github.com/alexhawat/mergeCraft/commit/861b94ce90327b7bca47fbf95dfd912019abc2c8)
- Audit open issues and define remediation in [5c96261d](https://github.com/alexhawat/mergeCraft/commit/5c96261d643531f651ff8a5710aa6e3947a7354c)

#### Skills

- Pin agent package docs to the renamed guide in [ebd5d2b8](https://github.com/alexhawat/mergeCraft/commit/ebd5d2b8348c54c0241badb03b6a428df45e9e3b)
- Stop advertising a comment trigger the default workflow lacks in [fc1ed4b7](https://github.com/alexhawat/mergeCraft/commit/fc1ed4b7fa7ff4b0c6b3b4bd2622f049b4fa21aa)

#### Test Plans

- Name the handoff-sweep test plan by wave in [f1fe1034](https://github.com/alexhawat/mergeCraft/commit/f1fe10344ec76d97b268f9baf374d00fa4703c06)
- Record R3 reconciliation trace run in [16cd6101](https://github.com/alexhawat/mergeCraft/commit/16cd61013b986baa41fe49cd7c8b011647fdc25c)
- Record T3 behavioral module suites in [36853b12](https://github.com/alexhawat/mergeCraft/commit/36853b12173e7f575f73cef4beea33ad5305e960)
- Update Final SHA after thermos final cleanup in [dd97ef83](https://github.com/alexhawat/mergeCraft/commit/dd97ef83c2a9eb3a49d9f05d65166242d5876f3b)
- Pin Final SHA after thermos round-2 in [8ba29d18](https://github.com/alexhawat/mergeCraft/commit/8ba29d188cf6e3d5faafc84c37f641734b58e007)
- Update Final SHA after thermos info hygiene in [9aaecc3f](https://github.com/alexhawat/mergeCraft/commit/9aaecc3fdd74238ef0c4e52cb1858190d8e358b2)
- Update Final SHA after thermos remediation in [74af6e21](https://github.com/alexhawat/mergeCraft/commit/74af6e219ea1d154673eacb9261e8ad20d03aee9)
- Update Final SHA after thermos fixes in [b4ad8394](https://github.com/alexhawat/mergeCraft/commit/b4ad8394f994b81a9cd387d624bbd33ed659791f)
- Fix BF RED evidence sha in [ec3e5e6e](https://github.com/alexhawat/mergeCraft/commit/ec3e5e6e6f478ecf09337e5e7ae6ae2dcc29ea83)
- Record BD RED evidence sha in [ed0d2dc4](https://github.com/alexhawat/mergeCraft/commit/ed0d2dc4836140caf031991b3adcb8a6a95c31d4)
- Record BA RED evidence for provider registry in [2d4606b1](https://github.com/alexhawat/mergeCraft/commit/2d4606b1db9350740f21de225bef718926b608ec)

#### Other

- W4 broker coverage and limits in [#553](https://github.com/alexhawat/mergeCraft/pull/553)
- Add operator guide and close wave 11 W9 in [f331168f](https://github.com/alexhawat/mergeCraft/commit/f331168f5dbc3fedc7537ed0328ca7f9a41726b2)
- Name main as the branch the review pin resolves from in [1d2ba8fe](https://github.com/alexhawat/mergeCraft/commit/1d2ba8febc2b524e7e29736ff274ec4936d81c2c)
- Document lane C coverage gate and provider status in [0b44d217](https://github.com/alexhawat/mergeCraft/commit/0b44d217ca692940e014bf5e06df197405d092eb)
- Align doctrine and review inputs with shipped behaviour in [26eba3ba](https://github.com/alexhawat/mergeCraft/commit/26eba3baced849b1eb7adb8e81ec023f43f60e3a)
- The release link no longer points at a deleted section in [254985df](https://github.com/alexhawat/mergeCraft/commit/254985df55090f0725768edbfc726bd9056b8999)
- Clarify benchmark model pin provenance in [ea731826](https://github.com/alexhawat/mergeCraft/commit/ea7318261d09aa304d8bcd3650486488fd1bb857)
- Export the Action pin and honour the dispatch prompt in [1351c95a](https://github.com/alexhawat/mergeCraft/commit/1351c95a6950c1941355338adef339c4fa478963)
- Add changelog fixes and strip agent CLI tokens in [3fd9fcc8](https://github.com/alexhawat/mergeCraft/commit/3fd9fcc8eb32fa5e24bad65f2d1dd96e0de5d989)
- Document the jev CLI and changelog the surface in [f81b96ce](https://github.com/alexhawat/mergeCraft/commit/f81b96cef68fe839133470e70d0c3f4188d457a7)
- List gherkin, the catalog's 33rd language in [bf8ecaa7](https://github.com/alexhawat/mergeCraft/commit/bf8ecaa70561fbb2783855f5bcc16a5e8659c508)
- Regenerate llms-full.txt after review doctrine edits in [14fd777b](https://github.com/alexhawat/mergeCraft/commit/14fd777bbe4cb1899e47420a2592dbb95a7ccfe1)
- Note double-trace when an OTel plugin is present in [535fda46](https://github.com/alexhawat/mergeCraft/commit/535fda46417b06752f0f0e9332046db5de117b19)
- Document lane A fixes and token band in [6fee24c8](https://github.com/alexhawat/mergeCraft/commit/6fee24c89b743c723e194ac405d619466b77b08d)
- The release no longer moves :latest in [a311df56](https://github.com/alexhawat/mergeCraft/commit/a311df561d219a0cbe5181a29c530e35d16acd29)
- Document scope split and run record (W9) in [d92de57c](https://github.com/alexhawat/mergeCraft/commit/d92de57cd01787a4982b21c120f3e7ce6d21798a)
- W10 trust policy and resilience operator docs in [35ff1ef4](https://github.com/alexhawat/mergeCraft/commit/35ff1ef44cbf2335d722d397b93d3947158af6a1)
- Close lane D W8 docs and CHANGELOG in [56e2ef42](https://github.com/alexhawat/mergeCraft/commit/56e2ef42fd35886abfdab52267a99bcec6ec9510)
- Mark test-suite hygiene wave complete in [6a7fdf75](https://github.com/alexhawat/mergeCraft/commit/6a7fdf757800e618e04ce2871578687100d0f1da)
- Use a non-credential basic-auth example in redact_url in [6cd6c9db](https://github.com/alexhawat/mergeCraft/commit/6cd6c9db8488d2e9a663a7ccdb8c37e897d039e3)
- Close W7 lane B docs and final gate in [e8207082](https://github.com/alexhawat/mergeCraft/commit/e8207082fd7c27f616e18f84a0eb3b3cc453a4a7)
- Changelog and TRACING.md for Datadog tracing and OpenCode fixes in [f03053dc](https://github.com/alexhawat/mergeCraft/commit/f03053dc2e6958aa28bdfbe4302855385e9d4ace)
- Replace private citations and machine paths with public references in [dc582c3b](https://github.com/alexhawat/mergeCraft/commit/dc582c3b4726589f46219eb81683b3da320cdcb6)
- Changelog entry for LLM review timing in [8a121923](https://github.com/alexhawat/mergeCraft/commit/8a121923f45da706ea84d9dd1e0cda49cd4d1389)
- Sync assign-model help from Typer docstring in [aab8eb44](https://github.com/alexhawat/mergeCraft/commit/aab8eb4491e351574406ef392d0fc3c9d4e5240b)
- Rename AGENTS.md to AGENTS-mergecraft.md in [09d44123](https://github.com/alexhawat/mergeCraft/commit/09d441236e80a10758d4058b64e7ac60fe52925e)
- Document the opt-in verdict-capture environment knob in [1175d92c](https://github.com/alexhawat/mergeCraft/commit/1175d92cdc421eec2dda01c89141c340e871ffd8)
- Fix doc links and glossary anchors, document operator env vars in [5d8ecd7e](https://github.com/alexhawat/mergeCraft/commit/5d8ecd7e2784cc1be4e55bf0edd4611c8dcade8b)
- Drop the pullfrog line the README v2 promotion restored in [bdb4bebd](https://github.com/alexhawat/mergeCraft/commit/bdb4bebddce9696781606f6ddb3a6d969935eb14)
- Record the 2026-09-22 verified audit in [18e97db1](https://github.com/alexhawat/mergeCraft/commit/18e97db156ac2963091a3dd7f15a5ed88e11dc07)
- Regenerate benchmark publication CLI reference in [77c05b91](https://github.com/alexhawat/mergeCraft/commit/77c05b91fe044dce3f33dd383cf861f6c9049698)
- List all mergecraft init artifacts in [3ffdd697](https://github.com/alexhawat/mergeCraft/commit/3ffdd697b819996ecb94edc2d2356e41d1d0d86f)
- Clarify installation token cleanup in [2e89bc57](https://github.com/alexhawat/mergeCraft/commit/2e89bc57caab6813a492382bb25b38ef10e0a1cc)
- Correct the Jev gate enforcement claims in [75409e84](https://github.com/alexhawat/mergeCraft/commit/75409e84ba6d3f2ef16d7f3c66c5ce7358efa2c1)
- Land the Jev gate judgment patterns in [2fdbf8ac](https://github.com/alexhawat/mergeCraft/commit/2fdbf8ace8d5c4a1a3cc76185bce5eaed84b208a)
- Retarget W6.3 to live post-run provenance note in [4ce6a508](https://github.com/alexhawat/mergeCraft/commit/4ce6a50870280beb9c9040330c7e845129815230)
- Refresh llms-full after stripping wave-dot tokens in [5f3c91fe](https://github.com/alexhawat/mergeCraft/commit/5f3c91fe3106acfad63b0ba6790690a55fa543bd)
- Regenerate llms-full after behaviour-verification docs in [8b7632bb](https://github.com/alexhawat/mergeCraft/commit/8b7632bbe7aa862e7f5be3300eb2ea7b585def7b)
- Stop citing decision ledgers in public markdown in [f212673b](https://github.com/alexhawat/mergeCraft/commit/f212673b0ef12b8ab1ca2460e32a00f4cf1ceaed)
- Add Unreleased Jev entries for the System One judge in [d1ed558b](https://github.com/alexhawat/mergeCraft/commit/d1ed558ba0b01376f64538b924a2cff04ca37639)
- Document LiteLLM as OpenAI-compatible custom provider in [#716](https://github.com/alexhawat/mergeCraft/pull/716)
- Honour the dispatch prompt in the README example in [7274cad2](https://github.com/alexhawat/mergeCraft/commit/7274cad27ddc5a155525f3d5300c7f7e81dc7dd4)
- Export the Action pin in every shipped example in [b72d7abe](https://github.com/alexhawat/mergeCraft/commit/b72d7abe0a5a0b4d8b930cd8deb5e64c161a1c7d)
- Align READMEs with init workflow and CLI in [037d118c](https://github.com/alexhawat/mergeCraft/commit/037d118c92ba9d2fbdd5ac8a7a7355211f2e008d)
- Correct the staleness workflow's own header in [240ea654](https://github.com/alexhawat/mergeCraft/commit/240ea6543746170506546f24e0226fb01409fd3e)
- Match the staleness triggers to the workflow in [fcb562f8](https://github.com/alexhawat/mergeCraft/commit/fcb562f8df510d1e977480492bc726e17545a958)
- Record release provenance and action pin fixes in [245d64be](https://github.com/alexhawat/mergeCraft/commit/245d64be4a1511f3a8052944680f55e699efcc98)
- Regenerate llms-full for the .env resolution section in [e5dae75f](https://github.com/alexhawat/mergeCraft/commit/e5dae75f9f3e500bc523572e55ba7036553d4b97)
- Note unified .env path resolution in changelog in [ce7c8eed](https://github.com/alexhawat/mergeCraft/commit/ce7c8eed3f14551af553ba776b6a0a76b170781f)
- Nightly audit B5 — GitLab matrix, Python floor, manifest gaps in [1b56813e](https://github.com/alexhawat/mergeCraft/commit/1b56813e49dcadd74b9930ff5c03bd4522c03993)
- Regenerate llms-full.txt for the D7 provenance section in [4a918d4b](https://github.com/alexhawat/mergeCraft/commit/4a918d4bd8ccc51ba262eed70d37b035312dc15f)
- Note this repo reviews on pull_request_target only in [3035d6a6](https://github.com/alexhawat/mergeCraft/commit/3035d6a6e45b8415bcb87c9866ddc06189a8d86f)
- Use catalog labels in the provider-auth quick start in [ac16ace1](https://github.com/alexhawat/mergeCraft/commit/ac16ace159db40de2707d9bae2d7c3c8a64bef85)
- Regenerate the llms-full bundle after the tracing doc change in [47f8deb5](https://github.com/alexhawat/mergeCraft/commit/47f8deb5391013478eab934b6536096277e3aa68)
- Public MCP install and generated tool reference in [af064e0b](https://github.com/alexhawat/mergeCraft/commit/af064e0b92949efe452c7ce7c0d4f74e3d06904c)
- Refresh llms-full after CI SARIF blame wording in [c39c608f](https://github.com/alexhawat/mergeCraft/commit/c39c608f72387af7ee7e5219213bf80aed97ad0a)
- Refresh support matrix for hy3 catalog row in [334b610a](https://github.com/alexhawat/mergeCraft/commit/334b610a8937506fcd8ec9533af644efe34b7424)
- Describe HY3 as the self-review primary in [7c3f9286](https://github.com/alexhawat/mergeCraft/commit/7c3f9286c8fe13b9ced088498a209c605335e257)

### Internal

#### Action

- Pin self-review to verified manifest efd35675 in [babd89c8](https://github.com/alexhawat/mergeCraft/commit/babd89c8d55c7f52432c1d2e318886540223e322)
- Prepare verified image manifest db38f116 in [6f14e2cd](https://github.com/alexhawat/mergeCraft/commit/6f14e2cd86ce1901523e2b5f709156a8499eba0c)
- Prepare verified image manifest 559afd1b in [a55d790c](https://github.com/alexhawat/mergeCraft/commit/a55d790c29dd7eae7f3992991f71def969440416)
- Pin self-review to verified manifest 6261fc87 in [10e139db](https://github.com/alexhawat/mergeCraft/commit/10e139db4a783628458b0ccae44e91e868007133)
- Prepare verified image manifest 814361f6 in [62beb561](https://github.com/alexhawat/mergeCraft/commit/62beb561941e6b365ee608528c792065e75414d1)
- Pin self-review to verified manifest 677c192c in [4bc60b11](https://github.com/alexhawat/mergeCraft/commit/4bc60b11cd7f44a7a2f3ed4d30f5ee2f8d4c6e05)
- Prepare verified image manifest ac771551 in [b8cd5ba0](https://github.com/alexhawat/mergeCraft/commit/b8cd5ba017c52cc01f8d4e2a51ebe3344e878a08)
- Pin self-review to verified manifest 71dbdb74 in [9550dec6](https://github.com/alexhawat/mergeCraft/commit/9550dec66646d6812f217011b4b3695f41bfa559)
- Prepare verified image manifest c1902df2 in [71dbdb74](https://github.com/alexhawat/mergeCraft/commit/71dbdb74ff822c0b17cce5b865655718c80e28d2)
- Pin self-review to verified manifest 1bdb7803 in [232463fa](https://github.com/alexhawat/mergeCraft/commit/232463fad456f39cdeb3a8fb8b3d38e14b2b0ee7)
- Prepare verified image manifest 658252e5 in [1bdb7803](https://github.com/alexhawat/mergeCraft/commit/1bdb780322a77eb0f8bc4b1b8381f40d1e7ae71b)
- Pin self-review to verified manifest e855e1dd in [e847293a](https://github.com/alexhawat/mergeCraft/commit/e847293a1f0be6a7b330d443020cdd1ac2546f68)
- Prepare verified image manifest e6944fa3 in [e855e1dd](https://github.com/alexhawat/mergeCraft/commit/e855e1dd0fae87068d04a74622298722385fc5de)
- Pin self-review to verified manifest 6197b478 in [73465e43](https://github.com/alexhawat/mergeCraft/commit/73465e437ec5a945ed09aa59fe2e8fa745081825)
- Prepare verified image manifest 1d5158d1 in [6197b478](https://github.com/alexhawat/mergeCraft/commit/6197b4787c10fe391063834f537e322ff5ba55a2)
- Pin self-review to verified manifest 08274dda in [83c4e735](https://github.com/alexhawat/mergeCraft/commit/83c4e7354e0bb144a363d8fd6a71d789a1f1dd2c)
- Prepare verified image manifest 063cab16 in [08274dda](https://github.com/alexhawat/mergeCraft/commit/08274dda64c6cb7a664a799899e6d36f82d6728b)
- Pin self-review to verified manifest 1d479f7a in [68277fb1](https://github.com/alexhawat/mergeCraft/commit/68277fb13f977c73d32c49d1d291f63c5a246e9e)
- Prepare verified image manifest 03e27f6e in [1d479f7a](https://github.com/alexhawat/mergeCraft/commit/1d479f7a12ff2bfbf51e22e62a144b95b875890d)
- Pin self-review to verified manifest 8dac76bb in [49f6be51](https://github.com/alexhawat/mergeCraft/commit/49f6be51eea3bd0ec9685aa16ebea21c979ab6f3)
- Prepare verified image manifest in [8dac76bb](https://github.com/alexhawat/mergeCraft/commit/8dac76bb0215588e596a16ca376487e9eb444daf)
- Pin self-review to verified manifest f43254bb in [472bb1d7](https://github.com/alexhawat/mergeCraft/commit/472bb1d7416434770abd7afdeb209d31fb8617be)
- Prepare verified image manifest in [f43254bb](https://github.com/alexhawat/mergeCraft/commit/f43254bbb4a940d516c12b7b8571513b71dfa962)
- Pin self-review to verified manifest cfd157bc in [3a14a2c7](https://github.com/alexhawat/mergeCraft/commit/3a14a2c7511d90812d19cf63b108bc4850e75d0d)
- Prepare verified image manifest 5bf5ad20 in [cfd157bc](https://github.com/alexhawat/mergeCraft/commit/cfd157bc6d501e7e74dfd533e1a694ce0423d5f1)
- Pin self-review to verified manifest a591fbc1 in [cede6f98](https://github.com/alexhawat/mergeCraft/commit/cede6f98091ae024524d75a2ce69865fd6d90076)
- Prepare verified image manifest b88f3583 in [a591fbc1](https://github.com/alexhawat/mergeCraft/commit/a591fbc15bfd05656a93442f988c42a684a2411e)
- Pin self-review to verified manifest a5b6a32c in [062f9730](https://github.com/alexhawat/mergeCraft/commit/062f973084f46541bb0403f992ccc0a344cd7470)
- Prepare verified image manifest 2502796e in [a5b6a32c](https://github.com/alexhawat/mergeCraft/commit/a5b6a32cbf995a9686e8b381806580260ee3efa3)
- Pin self-review to verified manifest 7acf0240 in [cf249021](https://github.com/alexhawat/mergeCraft/commit/cf24902115a0f06b1709b0f9565d6b1798493306)
- Pin self-review to verified manifest 7acf0240 in [ad618019](https://github.com/alexhawat/mergeCraft/commit/ad618019c05ab73dd541bee119bca2db2465be9e)
- Prepare verified image manifest 1d68cfc3 in [7acf0240](https://github.com/alexhawat/mergeCraft/commit/7acf0240f68709fcd88f0e2bcbb03717f1cb6a86)
- Pin self-review to verified manifest b49e10c7 in [f3817c61](https://github.com/alexhawat/mergeCraft/commit/f3817c61ade0224ad9e7afebfc802fee880d4483)
- Prepare verified image manifest 8eab4fe9 in [b49e10c7](https://github.com/alexhawat/mergeCraft/commit/b49e10c7b445e8e7de1303304a69ac2db489e37b)
- Pin self-review to verified manifest ae7710ee in [91e4dfda](https://github.com/alexhawat/mergeCraft/commit/91e4dfdac7a4dcebfe453bde7910ced37b7ac5ce)
- Prepare verified image manifest a980268d43ef24a87680943967f06ab326df8c89817100133c9a0ddb3efd0275 in [ae7710ee](https://github.com/alexhawat/mergeCraft/commit/ae7710ee3b5bc4889360130dd3071ed500ab7319)
- Pin self-review to verified manifest 7360bb5d in [b0010a19](https://github.com/alexhawat/mergeCraft/commit/b0010a191ac0a2f50885e5a889e80151fbdcfbc3)
- Prepare verified image manifest b2c716aa42457027a1a854160a0e31778a4f73c0d069f9f9c2ee86be5c5577ac in [7360bb5d](https://github.com/alexhawat/mergeCraft/commit/7360bb5d01b42789912e2b7dbbc50a76783bbc99)
- Pin self-review to verified manifest 8d078a7d in [bfdb599f](https://github.com/alexhawat/mergeCraft/commit/bfdb599f88b02c099f2ab5bce0d45022722e9c20)
- Prepare verified image manifest 9e5ca55cf12121f733ebcdfcfddf78d9007b6afce5262952672d97c5e4fa93a8 in [8d078a7d](https://github.com/alexhawat/mergeCraft/commit/8d078a7d711d18d8e783e764ba040c22afdee7da)
- Pin self-review to verified manifest 866d7fd9 in [e4d5664d](https://github.com/alexhawat/mergeCraft/commit/e4d5664d58644b48a881deee1c68f4d4c91fe8a3)
- Prepare verified image manifest 9827b6d9 in [866d7fd9](https://github.com/alexhawat/mergeCraft/commit/866d7fd96009a64251e6aff80c2a5b3ea583adca)
- Pin self-review to verified manifest 97be876d in [7ac3bb65](https://github.com/alexhawat/mergeCraft/commit/7ac3bb65e31e70289f49769fb9158c57575cfeca)
- Prepare verified image manifest d22175b7 in [97be876d](https://github.com/alexhawat/mergeCraft/commit/97be876dcf64e28ea683e79003e6d1c6c2d5393b)
- Pin self-review to verified manifest 280cd0d5 in [395b0339](https://github.com/alexhawat/mergeCraft/commit/395b03392a002950046e1254c2a0668f54c7f880)
- Prepare verified image manifest 429091af in [280cd0d5](https://github.com/alexhawat/mergeCraft/commit/280cd0d539152c9b398f53acf607c8d7e74bc084)
- Pin self-review to verified manifest 3b149a41 in [10070f8b](https://github.com/alexhawat/mergeCraft/commit/10070f8b1859de3b632a9110b7b667b3b0fed7c0)
- Prepare verified image manifest 12ace767 in [3b149a41](https://github.com/alexhawat/mergeCraft/commit/3b149a41b095a651feab0f4021bae0e1564eebc5)
- Pin self-review to verified manifest 37e79f67 in [586d0386](https://github.com/alexhawat/mergeCraft/commit/586d038612ce7dea8ce17d2acd3fdad9b97e4e70)
- Prepare verified image manifest 960b0cc6 in [37e79f67](https://github.com/alexhawat/mergeCraft/commit/37e79f6771e3e7b092615ed15b7829d036f9479a)
- Pin self-review to verified manifest 492684ed in [258e50d4](https://github.com/alexhawat/mergeCraft/commit/258e50d4841241886e696c486a4606dc7cd2bf42)

#### Agent Isolation

- Fix absolute-url rewrite broker test infra in [f0785279](https://github.com/alexhawat/mergeCraft/commit/f078527989e7619b33aa27915359ce5ba02ed8b7)
- Cover broker branches for security floor in [7ff913e9](https://github.com/alexhawat/mergeCraft/commit/7ff913e90851b45e95482ea59253f8894cde63fd)
- Exempt codex.py from AG9 trunk guard in [9e10fa7d](https://github.com/alexhawat/mergeCraft/commit/9e10fa7d6e87d0f60780f24977dacee9b28d5a18)
- W1 RED suite for broker and Codex wire-up in [002e25e0](https://github.com/alexhawat/mergeCraft/commit/002e25e0c37548f5ee9243a6d74c5515b91e02fd)

#### Agent Roster

- Cover roster dispatch and terminal submission paths in [8da59b98](https://github.com/alexhawat/mergeCraft/commit/8da59b9818fd655dd52498d2897df685bf7ae0b4)
- Wire anthropic in roster workflow fixture in [a2183ece](https://github.com/alexhawat/mergeCraft/commit/a2183eced1373eaa772da59e3521665b564f187e)
- Reconcile W8 xfails after init seeding in [b40f0169](https://github.com/alexhawat/mergeCraft/commit/b40f0169669975a6f9abd974bc155137f0ebfd5a)
- Reconcile W7 xfails after auth manifest in [617f5141](https://github.com/alexhawat/mergeCraft/commit/617f51414a61ea2b99601672bc7b342c5c1a6dfc)
- Reconcile W6 xfails after multi-reviewer execution in [9a6926a6](https://github.com/alexhawat/mergeCraft/commit/9a6926a6b15132996035bc99094207668ddf7f78)
- Reconcile W5 xfails and add level-shape tests in [ddc88379](https://github.com/alexhawat/mergeCraft/commit/ddc88379defdd2d048d4e51d0e1096c6c81f0798)
- Reconcile W4 xfails after agent-local CLI in [a72af771](https://github.com/alexhawat/mergeCraft/commit/a72af7711cf2c0d8cbbd06ab2384b117f7d5607b)
- Reconcile W3 xfails after agent CLI in [1336b22f](https://github.com/alexhawat/mergeCraft/commit/1336b22fad4337158453f4894457b283facc3253)
- Reconcile W2 xfails after slot primitives in [8d64f546](https://github.com/alexhawat/mergeCraft/commit/8d64f546da075640ea4d075e9dd70da48ff5e9e3)
- Add RED suite for wave plan 11 in [85b504e8](https://github.com/alexhawat/mergeCraft/commit/85b504e86b5296567a607d1c4ce227b92509cd5a)

#### Agents

- Make opencode mid-boot cancel test deterministic in [34a2922c](https://github.com/alexhawat/mergeCraft/commit/34a2922cdddda270a33d7a86ce4e1aa8e9ea7594)
- Drop the unused MAX_STDERR_LINES constant in [7bd681be](https://github.com/alexhawat/mergeCraft/commit/7bd681be84ffa76bfaf3a35ca9b739c91006db10)
- D26 drop unused \__all_gateway_envs__ re-export shim in [0806caa7](https://github.com/alexhawat/mergeCraft/commit/0806caa7427f08ee5b9de8d5c3e055d686fe2285)
- Pin absolute Claude deny paths and Action capture location in [57ab89f0](https://github.com/alexhawat/mergeCraft/commit/57ab89f0feda835725dc7141f0f05b42170f1c39)
- Pin pipe drains, prompt fallback and tracing binding in [6265f880](https://github.com/alexhawat/mergeCraft/commit/6265f8805cf20da372d23b1ffdaa3b73aed55d9d)
- Drop unused indexed provider constants (D17) in [0885504d](https://github.com/alexhawat/mergeCraft/commit/0885504dbd2b1a3d77c749d7eff16ace5bc3916d)
- Drop unused AgentRunContext.stop_script in [ef8c7f0c](https://github.com/alexhawat/mergeCraft/commit/ef8c7f0cf91c11cacf21cc808a8e5ea3a88c72a4)
- Remove post-#627 dead lens stubs and tiny stubs in [#643](https://github.com/alexhawat/mergeCraft/pull/643)
- Pin opencode gateway signatures, not the whole file in [fb7fd75f](https://github.com/alexhawat/mergeCraft/commit/fb7fd75feafb320edb5befc399ea914624b931bb)
- Pin openai_base_url broker routing for Codex 0.149 in [9024a66c](https://github.com/alexhawat/mergeCraft/commit/9024a66c622ca68c9745a4e3f01995bcab47e0e9)
- Reset the D7 once-guard before counting warnings in [4c2b50d5](https://github.com/alexhawat/mergeCraft/commit/4c2b50d54f7e44295964f186009f47f1f26c3cb7)
- Red tests for Nous as registry provider in [#481](https://github.com/alexhawat/mergeCraft/pull/481)
- Add RED coverage for transient Nous 404 classification in [1c9a54a7](https://github.com/alexhawat/mergeCraft/commit/1c9a54a751940a2064c7222ac721683a65c14fc8)
- Add HD RED suite for span token attrs in [#436](https://github.com/alexhawat/mergeCraft/pull/436)

#### Analyzers

- Bump managed hadolint to 2.15.1 in [85c20cf6](https://github.com/alexhawat/mergeCraft/commit/85c20cf6f460ffe95a1f320a48bb22230d79f0bc)
- Red suite for analyzer and evidence hardening in [523959b9](https://github.com/alexhawat/mergeCraft/commit/523959b9dc1e9daedbb03a2c204060bb68c3538a)
- Drop unused PatternBackendName alias in [48d12c08](https://github.com/alexhawat/mergeCraft/commit/48d12c08a27b5b6b23dbed11b182eb36e8eb289d)
- Pin trusted cache, lock and attribution contracts in [c411070a](https://github.com/alexhawat/mergeCraft/commit/c411070a56095c13be45a1d76fe410589081a519)
- Name an unavailable egress namespace as a skip in [62d13607](https://github.com/alexhawat/mergeCraft/commit/62d136075fbf165e852a059405858ee15f8853c7)
- Skip CVE fixture when unshare stays unavailable in [ab916396](https://github.com/alexhawat/mergeCraft/commit/ab9163965fd4fee1594224c9504c410c43e745f6)
- Retry osv-scanner on a transient egress skip in [ea29bd37](https://github.com/alexhawat/mergeCraft/commit/ea29bd37f1835eecf499dc4afc28cec62f03058e)
- Require supported direct namespace backend in [8c980378](https://github.com/alexhawat/mergeCraft/commit/8c980378d1d7eca33005ab26f2869e74377f745a)
- Verify production timeout kills namespace child in [85e043c4](https://github.com/alexhawat/mergeCraft/commit/85e043c434225211771c4b25bf5999f4dfe0db2d)
- Use readable runtime after capability drop in [10211c36](https://github.com/alexhawat/mergeCraft/commit/10211c36d3c623887f4c28c56fbb38a2e43adf36)
- Resample against redact_secrets itself, not the entropy formula in [2aee1e93](https://github.com/alexhawat/mergeCraft/commit/2aee1e93e9e508e58fa11d73f204809ab74eb2ef)
- Resample entropy fixture until it clears the redaction threshold in [#650](https://github.com/alexhawat/mergeCraft/pull/650)
- Align provision_paths fixture with Client transport in [5ee7d4a1](https://github.com/alexhawat/mergeCraft/commit/5ee7d4a1e4875187bc1b1d7b514435775572ff6a)
- Add RED coverage for skipped catalog as unavailable in [6f5750ad](https://github.com/alexhawat/mergeCraft/commit/6f5750ad7682e7295bf6e3438d6b5ec7504c09e5)
- Add RED coverage for empty bandit JSON scans in [9a2d0358](https://github.com/alexhawat/mergeCraft/commit/9a2d03582a29dac8c6685b956ef8f2d75b458af2)
- Add RED coverage for placeholder provenance pins in [88a71357](https://github.com/alexhawat/mergeCraft/commit/88a713574ca292c30ab6b663210c35cdd3119a78)
- Pin repo-native binary resolution for #427 in [9cbb8582](https://github.com/alexhawat/mergeCraft/commit/9cbb8582bc3a8f43cff46a51b251a0cc281163fe)
- Pin antislop scopes import contract in [#423](https://github.com/alexhawat/mergeCraft/pull/423)
- Red tests for antislop matcher bugs in [27d0827d](https://github.com/alexhawat/mergeCraft/commit/27d0827d56a4191807276f62b0a47819074cc68f)

#### Audit

- Remove unwired comment_router staged library (D1) in [55c343ef](https://github.com/alexhawat/mergeCraft/commit/55c343ef4affe4a5a8d30d98b2f7232363293685)
- Remove dead review/enterprise/test-only modules (A3) in [#628](https://github.com/alexhawat/mergeCraft/pull/628)
- Add lane A privilege RED suite AP1.1–AP1.6 in [ab89570f](https://github.com/alexhawat/mergeCraft/commit/ab89570fc68f5e869ef1a25d5d4eea6a7b4b61f0)

#### Authority

- Drop satisfied AG6/AG7 xfail markers in [ab2971cb](https://github.com/alexhawat/mergeCraft/commit/ab2971cba92f30fbb5e086be8d41bcbc1d5a80b0)
- Reconcile orchestrator tests for dispatched status in [c7342b55](https://github.com/alexhawat/mergeCraft/commit/c7342b55e821d4a7dfa49370e76f14c3de9a828e)
- Reconcile AG1.2 tests after AG3 in [058520f3](https://github.com/alexhawat/mergeCraft/commit/058520f30caaafa217cefb99d98c7ae34e23341c)
- RED suite for lane C authority gates in [e67f8de8](https://github.com/alexhawat/mergeCraft/commit/e67f8de8c3532864580db228b5780dac4860e620)

#### Ci

- Red suite for ci, config, release and housekeeping items in [1617608f](https://github.com/alexhawat/mergeCraft/commit/1617608f362380bdd3267213b7bf740944ee34cb)
- Trust the second machine's author email for pushes in [89f411fe](https://github.com/alexhawat/mergeCraft/commit/89f411fe8dded09e9b215ff0f7e8a370e4271cf5)
- Raise the action-pin freshness drift guard to 120 in [b806fc1a](https://github.com/alexhawat/mergeCraft/commit/b806fc1ab8594d78087fdb85dc70bb59caed6985)
- Pin base-success non-overlap as unattributed in [845a496d](https://github.com/alexhawat/mergeCraft/commit/845a496d7ceed506b97617b70886d118adf2f1f6)
- Pin evidence-based CI blame and flaky verdicts in [6fa34ae4](https://github.com/alexhawat/mergeCraft/commit/6fa34ae4a8013694409a10daa051ec30842a3403)
- Add the RED suite for the CI gate honesty fixes in [dc53069a](https://github.com/alexhawat/mergeCraft/commit/dc53069a5dd9be14171cea3dc44073fdea72cc44)
- Isolate nested coverage gates from shards in [daaa613c](https://github.com/alexhawat/mergeCraft/commit/daaa613cbd9b8e2bb9a3ed598b04a00ca3e17a4d)
- Exercise shadow/enforce gate paths and complexity_from_source in [439b40ba](https://github.com/alexhawat/mergeCraft/commit/439b40ba7f86a483727b7d503070244587db494a)
- Trust github-actions bot for manifest commits in [9d024f56](https://github.com/alexhawat/mergeCraft/commit/9d024f56fcbc002a0e9852e001a30a75a8b42474)
- Isolate K6 harness check from sibling module name in [f70da761](https://github.com/alexhawat/mergeCraft/commit/f70da761eb51f0e38edb982b49b7f0b86aebc5a3)
- Require check_runs on intelligence coverage ingest in [94139a4d](https://github.com/alexhawat/mergeCraft/commit/94139a4de19edbcee339b91752a9764ac4152987)
- Drop C2-C4 xfails now that evidence paths are green in [f743a9eb](https://github.com/alexhawat/mergeCraft/commit/f743a9ebefcfe7d72d58f7241c261f790552e28c)
- Track ignored CRAP coverage.json fixtures in [fe843efd](https://github.com/alexhawat/mergeCraft/commit/fe843efd99e2091f0c98f99319459632fe698c2a)
- Red suite for CRAP and mutation evidence in [6d9154cc](https://github.com/alexhawat/mergeCraft/commit/6d9154cc72234f363f0e5b05a7f21a1471c1c9df)
- Copy objects for isolated coverage fixtures in [6b46de99](https://github.com/alexhawat/mergeCraft/commit/6b46de990035ea18230b2360169ef588e1b5dde3)
- Establish verified pre-release baseline in [79a6a158](https://github.com/alexhawat/mergeCraft/commit/79a6a158d4a89a9c40b7ad69d9842d523c451535)
- Cover W4 ingest skip and action-env branches in [39f27dc6](https://github.com/alexhawat/mergeCraft/commit/39f27dc697b6f6c474cb4ee75cfb3cedd1e7bc01)
- Reconcile W5 SARIF xfails and trufflehog skip in [d3c4b3fa](https://github.com/alexhawat/mergeCraft/commit/d3c4b3fab99889cd2cd67eca17df22b781022f12)
- Align lane A tests with AP4 and git_argv mocks in [c655dfe7](https://github.com/alexhawat/mergeCraft/commit/c655dfe7c79c16efe72f5eef70e92bb5b5eafd83)
- Add decision-module mutation harness in [67ddfd3a](https://github.com/alexhawat/mergeCraft/commit/67ddfd3a899dca94d7a2bef0c694e01821a10899)
- Remove D6 xpass carve-out and add cheat-signature lint in [da95da96](https://github.com/alexhawat/mergeCraft/commit/da95da966d931b5a6080f7d4dcd338fad9f5af9e)
- Tighten coverage floors and ratchet baseline in [5cb00009](https://github.com/alexhawat/mergeCraft/commit/5cb000097e72a6976415d661c67b8d5cc9ce5c5c)
- Lock coverage inherited-drift D9 for #485 in [9f7cc501](https://github.com/alexhawat/mergeCraft/commit/9f7cc5016d4201d5c7073de23ccc0f296cd74c06)
- Add RED coverage for CI SARIF evidence in [#464](https://github.com/alexhawat/mergeCraft/pull/464)
- Reconcile CG xfail markers for timeout budget in [912710ec](https://github.com/alexhawat/mergeCraft/commit/912710ec257583422bc1cbcb625ad806d7a62ab4)
- Red tests for review timeout budget composition in [77684b8f](https://github.com/alexhawat/mergeCraft/commit/77684b8fa1106e4fbdace9ab684897e3f041bab7)
- RED base-branch coverage gate pins for #432 in [ab2c8897](https://github.com/alexhawat/mergeCraft/commit/ab2c88975210a3cb5f37bbd03ad49ca2256b8166)
- RED coverage 82% floor pins for #431 in [f3e90195](https://github.com/alexhawat/mergeCraft/commit/f3e90195793800daab52daf7e25dca98a8373e3a)
- Pin review gate ordering before Codex fallback in [#433](https://github.com/alexhawat/mergeCraft/pull/433)
- RED called-workflow permissions lint in [#425](https://github.com/alexhawat/mergeCraft/pull/425)

#### Cli

- D33 drop unused \_TRACING_FLAGS in [da1c6256](https://github.com/alexhawat/mergeCraft/commit/da1c625686f942cba4966f1f5b9e08fb2f492000)
- Stop the .env corpus leaking into the process environment in [5e351b58](https://github.com/alexhawat/mergeCraft/commit/5e351b581fb98f64ceea3be44c50c4091a9f33ae)
- D21 drop unused \_indexed_label_from_env in [f0a12238](https://github.com/alexhawat/mergeCraft/commit/f0a12238426684e5722ac40cf3c3c6f28f20fa8e)
- Drop unused DEFAULT_NOUS_PORTAL (D18) in [bb7f9be1](https://github.com/alexhawat/mergeCraft/commit/bb7f9be15c47aa618966c3ef7be5465e332eaae6)
- Assert the actual doctor validation diagnostic in [8c99b06b](https://github.com/alexhawat/mergeCraft/commit/8c99b06be846b9534df0abc4876a8ac2cdce92ca)
- Assert the actual doctor validation diagnostic in [33fff390](https://github.com/alexhawat/mergeCraft/commit/33fff3908f8b6e58da9cb3967365da4eb41c1f9a)
- Tolerate wrapped lock summary under xdist in [8d205998](https://github.com/alexhawat/mergeCraft/commit/8d205998bf28bfb80e3f440ace88b181cfa709dc)
- Isolate legacy credential warning state between tests in [fb440310](https://github.com/alexhawat/mergeCraft/commit/fb44031092b7433007abb268130c93c344578aa4)
- Red tests for workflow provider/model authoring in [#484](https://github.com/alexhawat/mergeCraft/pull/484)
- Red tests for provider migrate in [#483](https://github.com/alexhawat/mergeCraft/pull/483)
- Red tests for agents setmodel and addbackupmodel in [#480](https://github.com/alexhawat/mergeCraft/pull/480)
- Red tests for unified provider auth in [#478](https://github.com/alexhawat/mergeCraft/pull/478)
- Red tests for model add/list/delete in [#479](https://github.com/alexhawat/mergeCraft/pull/479)
- Red tests for provider add/list/edit/delete in [#477](https://github.com/alexhawat/mergeCraft/pull/477)
- Validate diff-review JSON without short_id field in [736fee93](https://github.com/alexhawat/mergeCraft/commit/736fee93725ed74250d359f05f5659dc76822567)
- Reconcile CI audit.jsonl xfail markers in [613cce47](https://github.com/alexhawat/mergeCraft/commit/613cce476d9799f64c15e5ded0723c3102477286)
- Red tests for audit.jsonl gitignore on init in [18d3ced6](https://github.com/alexhawat/mergeCraft/commit/18d3ced6d09bcb1e311d819957d0a68feaab9855)
- Reconcile CF xfail markers in [24758c62](https://github.com/alexhawat/mergeCraft/commit/24758c62637052c33a499dbd8de38cbabd38f4c8)
- Red tests for update and version commit in [14cd399b](https://github.com/alexhawat/mergeCraft/commit/14cd399bb54603b698570ac4da55493ad48e841f)
- Reconcile CB hunk xfail markers and fix helpers in [8cba4ea5](https://github.com/alexhawat/mergeCraft/commit/8cba4ea525e5f7bfc65d81b7885fe06e4a96a399)
- Red tests for --output-format hunk in [401887fb](https://github.com/alexhawat/mergeCraft/commit/401887fb3f26d195245cfcfb10cd7ffbcef1193f)
- Pin partial local auth write contract in [#437](https://github.com/alexhawat/mergeCraft/pull/437)

#### Config

- Drop unused \_resolve_config_path helper in [ee03be3b](https://github.com/alexhawat/mergeCraft/commit/ee03be3b3b6fb28847dab25e208ff71ad37a7de4)
- Pin the fail-closed action-input and CLI exit paths in [cbd6e0ba](https://github.com/alexhawat/mergeCraft/commit/cbd6e0bae3fc26fdb230333f78a361948d5be70c)
- Pin the secret-field env key fallback in [e7d92c0c](https://github.com/alexhawat/mergeCraft/commit/e7d92c0c2ce8e107acb8aaf8da04329c112fa069)
- Author the RED suite for env and .env settings in [f241e846](https://github.com/alexhawat/mergeCraft/commit/f241e8461a4064e5beb4dbd3ed57484b8da0cdd8)
- Pin the fail-closed sandbox tier, not the fallback in [0500f1ed](https://github.com/alexhawat/mergeCraft/commit/0500f1ed887ec1c1b79ad32313287b50217ae746)
- Pin list-valued block replacement in [808f17e5](https://github.com/alexhawat/mergeCraft/commit/808f17e5bd2456ffb6bb5c88dd6b9b699326fa94)
- Drop stale hosted-plan assertions in [b2d6dcdb](https://github.com/alexhawat/mergeCraft/commit/b2d6dcdb93cd172a0bd5a594fdb3082b17f1090e)
- Pin the config and CLI surface contracts red in [2273a781](https://github.com/alexhawat/mergeCraft/commit/2273a78138c75ba746f70abe98346754e24e15b2)

#### Context

- Pin sole oversized skill truncated not dropped in [f6df7c89](https://github.com/alexhawat/mergeCraft/commit/f6df7c89f83f708cd3be9ed75a5bed37174ad664)
- Pin trusted-cap drop of referenced review skill in [8380c7e3](https://github.com/alexhawat/mergeCraft/commit/8380c7e3a76fb873ae500ab38867a4706d0dc17d)
- Pin F12 untrusted tight-cap record/prompt sync in [f998b3fa](https://github.com/alexhawat/mergeCraft/commit/f998b3fa64d5e47bdc3be69fbc7434be2029f28e)
- Align skill discovery fixtures with F7 skips in [306c31ea](https://github.com/alexhawat/mergeCraft/commit/306c31ea4171dad90944f42fc9424ceb821fe768)

#### Coverage

- Re-baseline floors from the merged tree in [7522bda0](https://github.com/alexhawat/mergeCraft/commit/7522bda02f4d3d25b62e5d7391404334a764fad1)
- Drop utils/token.py from MODULE_FLOORS in [f6049b4c](https://github.com/alexhawat/mergeCraft/commit/f6049b4c95eae3deb5ded59f445ee4b97488ac13)

#### Dependabot

- Update uv.lock with Python bumps and batch tracing apart in [31fe4e84](https://github.com/alexhawat/mergeCraft/commit/31fe4e843f1e8e21d0432bd73261e366d2cdf704)
- Target main instead of the stale pre-0.0.1 in [6112bebb](https://github.com/alexhawat/mergeCraft/commit/6112bebbf76eb57f279e1c348d20f00f5de9238b)

#### Deps

- Bump msgpack to 1.2.4 (CVE-2026-114613) in [4b4ccb47](https://github.com/alexhawat/mergeCraft/commit/4b4ccb47cd68b35ec423828a1578ae2e177c82f3)
- Bump filelock from 3.30.2 to 4.2.1 in [2c20fb57](https://github.com/alexhawat/mergeCraft/commit/2c20fb573c0f890b235e2c9adcd2c14fb90fc1ba)
- Bump virtualenv to 21.14.13 (CVE-2026-115586) in [526521a6](https://github.com/alexhawat/mergeCraft/commit/526521a67464ea2555da877bd8b8b246d526990b)
- Bump the github-actions-patch-minor group across 1 directory with 2 updates in [6b38ec22](https://github.com/alexhawat/mergeCraft/commit/6b38ec225324cfd793159675d4644f61691e1714)
- Bump the agent-clis-patch-minor group across 1 directory with 4 updates in [e7368396](https://github.com/alexhawat/mergeCraft/commit/e7368396ce91b2c8e93f0e73edf860df82e6834d)
- Bump logfire in [552e10a4](https://github.com/alexhawat/mergeCraft/commit/552e10a41dee55fb955d389d9070e0b5f52933e5)
- Bump actions/download-artifact from 7.0.0 to 8.0.2 in [5a7e68c5](https://github.com/alexhawat/mergeCraft/commit/5a7e68c579fcb7fc206f171496d71baba29e7dbf)
- Bump virtualenv to 21.14.12 in [39b77ecb](https://github.com/alexhawat/mergeCraft/commit/39b77ecb8c7074defcf58f2776bb0be05f97bd82)
- Bump certifi to 2026.10.19 (GHSA-6q48-6c7w-9gw2) in [30325e33](https://github.com/alexhawat/mergeCraft/commit/30325e339e45c0e31be60cd8c11187ab0644ed87)
- Bump aiohttp from 3.14.3 to 3.14.4 in [a1bf937e](https://github.com/alexhawat/mergeCraft/commit/a1bf937eb737dfd9d34df7748f222e231c45dc7f)
- Bump types-jsonschema in [78d74c28](https://github.com/alexhawat/mergeCraft/commit/78d74c28b2b0639217a88a23ed82faf53ff204ba)
- Bump the github-actions-patch-minor group across 1 directory with 8 updates in [46968579](https://github.com/alexhawat/mergeCraft/commit/46968579318a53c97d9158ad332f5d447c6d1486)
- Bump logfire in [f0016bd9](https://github.com/alexhawat/mergeCraft/commit/f0016bd954b8f9c4ee69f1c8b111287a97d0f4c4)
- Bump the agent-clis-patch-minor group across 1 directory with 3 updates in [a9595e12](https://github.com/alexhawat/mergeCraft/commit/a9595e12cf5e059520332f03d8e2b62364ceb9b5)
- Bump multidict from 6.7.1 to 6.9.1 in [8017b293](https://github.com/alexhawat/mergeCraft/commit/8017b293bf645acd6a67cb44326986242ae62755)
- Bump litellm from 1.95.0 to 1.95.1 in [f61c5b5a](https://github.com/alexhawat/mergeCraft/commit/f61c5b5ad6ad869b51d845b9985c959a41a5bbf5)
- Bump requests in [fc63ec6b](https://github.com/alexhawat/mergeCraft/commit/fc63ec6bda4a104938caba537971684bfa1b37ae)
- Land python patch/minor group with hook pin in [#719](https://github.com/alexhawat/mergeCraft/pull/719)
- Bump the agent-clis-patch-minor group in [#718](https://github.com/alexhawat/mergeCraft/pull/718)
- Bump the github-actions-patch-minor group with 2 updates in [#721](https://github.com/alexhawat/mergeCraft/pull/721)
- Bump smol-toml and markdownlint-cli in /tools in [19e99983](https://github.com/alexhawat/mergeCraft/commit/19e999836b74f40498f23febda1e8a58a257d6db)
- Bump the python-patch-minor group across 1 directory with 18 updates in [2c405cf0](https://github.com/alexhawat/mergeCraft/commit/2c405cf0b453ccdfe746b61a9987a4e916d8e241)
- Bump the agent-clis-patch-minor group across 1 directory with 4 updates in [ee9936c7](https://github.com/alexhawat/mergeCraft/commit/ee9936c75dfc3d628e2299a964f63309909e3cdf)
- Bump actions/create-github-app-token from 2.2.2 to 3.2.0 in [a59e4865](https://github.com/alexhawat/mergeCraft/commit/a59e4865faeb5ba1ef219d378ce392dbcdabff95)
- Bump golang in [879e215d](https://github.com/alexhawat/mergeCraft/commit/879e215deadd025ba96cffee4d097116c3cb03da)
- Bump actions/cache from 4.2.0 to 6.1.0 in [807acd19](https://github.com/alexhawat/mergeCraft/commit/807acd19ea7dee1be8827c06b702deb03b5a9b0e)
- Bump the agent-clis-patch-minor group in [567fc182](https://github.com/alexhawat/mergeCraft/commit/567fc182257edbd25c4d2f2122ff4b8515461c4d)
- Bump actions/setup-node from 4.4.0 to 7.0.0 in [47db9bb6](https://github.com/alexhawat/mergeCraft/commit/47db9bb6d8934933921cedfb49eadc9c5d81ccfc)
- Bump actions/attest-sbom from 2.4.0 to 4.1.0 in [ca44d951](https://github.com/alexhawat/mergeCraft/commit/ca44d951061e6ab16e5d399852efb2ca80b0134a)
- Bump actions/attest-build-provenance from 3.0.0 to 4.2.2 in [ae33efd2](https://github.com/alexhawat/mergeCraft/commit/ae33efd2b019aace9f4e6c69ad47c649b7058360)
- Bump the github-actions-patch-minor group with 2 updates in [9c72eaa9](https://github.com/alexhawat/mergeCraft/commit/9c72eaa9d1b373c990698adfe783dba7c44e8b02)
- Bump python from `23c5939` to `9ab8d9c` in [55e5181d](https://github.com/alexhawat/mergeCraft/commit/55e5181dadf8a5dd4329a4f5d79a03792cd48dcf)
- Bump the github-actions-patch-minor group across 1 directory with 2 updates in [4ab91858](https://github.com/alexhawat/mergeCraft/commit/4ab91858926cfb0873bfc983c9d073980f134cdb)
- Bump the agent-clis-patch-minor group across 1 directory with 4 updates in [35be804c](https://github.com/alexhawat/mergeCraft/commit/35be804c581f6d9b5c93f0d4a19e9be9450d1336)

#### Deps Dev

- Bump markdown-it from 14.3.1 to 14.3.3 in /tools in [d8650c8f](https://github.com/alexhawat/mergeCraft/commit/d8650c8f9762fdc5db98f25fe497fc8c00f781b3)
- Bump brace-expansion from 5.0.9 to 5.0.12 in /tools in [07088173](https://github.com/alexhawat/mergeCraft/commit/07088173710e275ee47046cb6579ccfa0adcfc4f)
- Bump types-pyyaml from 6.0.12.20260724 to 6.0.12.20260906 in [#720](https://github.com/alexhawat/mergeCraft/pull/720)
- Bump logfire from 4.40.0 to 5.0.0 in [e0edf5bf](https://github.com/alexhawat/mergeCraft/commit/e0edf5bf4c38c2324b461d7995130eb85fbbfcd1)
- Bump pytest-randomly from 4.1.0 to 5.0.0 in [9bf622a3](https://github.com/alexhawat/mergeCraft/commit/9bf622a3b4f75d9927ccaf588aac34da13d46e33)
- Bump pytest-cov from 6.0.0 to 7.1.0 in [efb940bd](https://github.com/alexhawat/mergeCraft/commit/efb940bd90a914927204588f0972b1dc5078a6f0)
- Bump mypy from 1.20.2 to 2.3.1 in [b4af6875](https://github.com/alexhawat/mergeCraft/commit/b4af687544e5c19dd3bdbfc4f340716f935eb31e)

#### Determinism

- Clear ambient GitHub event for every test in [4e4a0e25](https://github.com/alexhawat/mergeCraft/commit/4e4a0e252135f91c803da15b795dc15e2c0adbfb)
- Add scheduled random-seed test run in [8da49a2e](https://github.com/alexhawat/mergeCraft/commit/8da49a2e169a1bf616b32aedfc2ede8e5b4d71d3)
- Hold MCP test servers open through the assertion in [edd8a758](https://github.com/alexhawat/mergeCraft/commit/edd8a75893b5995889f410f9a41f4d0e9a9b19ac)
- Add red suite for gate determinism waves in [ede3964c](https://github.com/alexhawat/mergeCraft/commit/ede3964c5c187d8ce3d0a2f644f80969158bdedf)

#### Dev

- Add hypothesis for BR1 property-based tests in [c680cb64](https://github.com/alexhawat/mergeCraft/commit/c680cb6412209d2f03ef9fdd6f0e892242f36b40)
- Install vulture typos markdownlint jscpd for local review in [5777e124](https://github.com/alexhawat/mergeCraft/commit/5777e124ff70fdd2932c91285af67f57d110ee84)

#### Docs

- Classify the opt-in verdict-capture env knob in [d4ffad57](https://github.com/alexhawat/mergeCraft/commit/d4ffad57258c4703b6f65bf4f3ebf3fc4e490442)
- Accept a collapsed agent section, and refresh the bundle in [8716deed](https://github.com/alexhawat/mergeCraft/commit/8716deed19439e9aa7d6034d90da7e64dc98f4d6)

#### Dq1

- Reconcile xfails after DQ2 in [083e5e0c](https://github.com/alexhawat/mergeCraft/commit/083e5e0c4def8f70b2c0d0a53ca667a27d07768a)
- Document xfail reconciliation on impl branches in [9cb848f7](https://github.com/alexhawat/mergeCraft/commit/9cb848f7f6e313591b999ca2747d2690c6ae5493)
- Reconcile xfails after DQ3 and DQ4 in [3c05945e](https://github.com/alexhawat/mergeCraft/commit/3c05945e00c40856d77430a71be08fe95a00e18f)
- RED suite for audit remediation open issues in [2de91052](https://github.com/alexhawat/mergeCraft/commit/2de91052fd8916e9b4e7ef6c3604ce137ff4ce84)

#### Enterprise

- Align audit_producer_hk with MCB-21 external path in [0a41a7a8](https://github.com/alexhawat/mergeCraft/commit/0a41a7a8d28a8b2bd2550be6eb981f22cb88bcfe)
- Pin audit.jsonl producer contract for #417 in [d470ec94](https://github.com/alexhawat/mergeCraft/commit/d470ec94cda2b4052f89a868a3ab6514af8d8a40)

#### Evals

- Regenerate structural baseline in [21d2cccb](https://github.com/alexhawat/mergeCraft/commit/21d2cccb4f3521ed07ae94fe624a2fe6a7d013d9)
- RED suite for gate coverage, matching and verify provenance in [3b1fc9a7](https://github.com/alexhawat/mergeCraft/commit/3b1fc9a7d56f51d7cae1dc4830f62c8e9352e4ed)
- Record human decisions for golden batch 001 in [79dbf5e2](https://github.com/alexhawat/mergeCraft/commit/79dbf5e21a937ccb7bc20dbb61b554a4a2689165)
- Assert golden manifest invariants and corpus agreement in [ef11d586](https://github.com/alexhawat/mergeCraft/commit/ef11d586d6c255f1dae379c7a771b58027f174a2)
- Drop E4 xfails after cost-cap lift landed in [3b3074c9](https://github.com/alexhawat/mergeCraft/commit/3b3074c921416d78118457046123810a4b32580c)
- Block PRs on keyless structural eval-gate in [fbc68e53](https://github.com/alexhawat/mergeCraft/commit/fbc68e53d44dc88618f922ae8b5e4c29e34560bd)
- Drop ablation suite and pin plan 25 E2/E4 contracts in [9d4f1209](https://github.com/alexhawat/mergeCraft/commit/9d4f1209caa9879cd61b5747fe134a66082baf19)
- Public MCP tool selection and jailbreaks in [31bbabfb](https://github.com/alexhawat/mergeCraft/commit/31bbabfbaf32d7a3767fd0f9ad65e38e3a2c521a)
- Reconcile CE per-lens capability xfails in [ed39d56a](https://github.com/alexhawat/mergeCraft/commit/ed39d56a28634ac1cf69b6d7ce54cb0fe3d47d4a)
- Red tests for per-lens capability numbers in [786204d9](https://github.com/alexhawat/mergeCraft/commit/786204d929298e36b37898868a708a87f87a8ea4)

#### Evidence

- Pin the review-cost run-record line in [e91c3235](https://github.com/alexhawat/mergeCraft/commit/e91c32350443e5a904eb0c0c0210ec4add233158)
- Isolate the live-target stamp assertion in [22bb7f0f](https://github.com/alexhawat/mergeCraft/commit/22bb7f0f7e5385593c762da5ff787963ed992807)
- Reconcile second-shadow-target suite after R4 in [02c56c3e](https://github.com/alexhawat/mergeCraft/commit/02c56c3e24afce4b8ee5659a69bc691df51b6e94)
- Reject out-of-vocabulary eval expected_decision in [f5dc4f4e](https://github.com/alexhawat/mergeCraft/commit/f5dc4f4ea12337287ef8c48b6f2b76c757b40b01)
- Cover gate rule selection and #41 packet wiring in [bb96eac6](https://github.com/alexhawat/mergeCraft/commit/bb96eac689376479be191623471cf5e81b544f06)

#### Findings

- Reconcile RED markers now satisfied by LG2-LG4 in [6605ab26](https://github.com/alexhawat/mergeCraft/commit/6605ab26f50a147a83d66bceb447b48ce00927d1)
- Add RED suite for sticky-comment ledger in [5a388430](https://github.com/alexhawat/mergeCraft/commit/5a388430d8ccb3b31c7b51502e84e198bf498d56)
- Cover auth-stem author-family exclusion in [aeaffd56](https://github.com/alexhawat/mergeCraft/commit/aeaffd5683e22d3a0d3ed29368fa74622baf2e91)
- Round-trip Finding through every output format in [f410784d](https://github.com/alexhawat/mergeCraft/commit/f410784de119d5fb328ed8d85905cefb3bf54461)
- Red tests for stable short finding id in [538dd975](https://github.com/alexhawat/mergeCraft/commit/538dd975efa9182b91a84b345bc8ea730bd696ba)

#### Hygiene

- Drop satisfied H5 remediations xfails in [64088fc8](https://github.com/alexhawat/mergeCraft/commit/64088fc8447be5a082b6782d2b8f145699daf2ac)
- Pin H5 F1 no-backend raise and F2/F3 reds in [44255c31](https://github.com/alexhawat/mergeCraft/commit/44255c31122b820546d793125597ccc1f82b2ade)
- Drop satisfied H4 xfails after tracked-markdown checker in [44367781](https://github.com/alexhawat/mergeCraft/commit/44367781d31a2a67c52cad68893db1fb584735c2)
- Drop satisfied H3 xfails after markdownlint fallback in [d98a2b55](https://github.com/alexhawat/mergeCraft/commit/d98a2b5543edac3c5aebe260a992ed9687d8a994)
- Fix no-backend helper and drop satisfied H2 xfails in [336c908d](https://github.com/alexhawat/mergeCraft/commit/336c908dfc2c06abb4768a2c5ea219de8fc72c53)
- Pin RED contracts for H2-H4 platform defaults in [e672ac56](https://github.com/alexhawat/mergeCraft/commit/e672ac56893b87faacdfaa9b6a1dd3d434e7cb12)

#### Integration

- Post the model id the Nous Portal serves in [e868fbe2](https://github.com/alexhawat/mergeCraft/commit/e868fbe2a44597cb0c10f46d4834bccee2243604)
- Install tracing extra for coverage gate in [17dcac1a](https://github.com/alexhawat/mergeCraft/commit/17dcac1a6b745be8ea0f3eeadc56c67f12e6692a)

#### Jev

- Keep the usage-log assertion independent of global redaction in [f3b0df49](https://github.com/alexhawat/mergeCraft/commit/f3b0df49b0d3e81eb9cdc99bf1268fc2bb10db17)
- Cover the CLI writer and the review summary in [4158f564](https://github.com/alexhawat/mergeCraft/commit/4158f564f0712678e6b87794534eccc48d153201)
- Pin status-less TypeSafe transport skip in [ec299693](https://github.com/alexhawat/mergeCraft/commit/ec29969349a00403d7c118a9ba87410bcc64e676)
- Pin jev.model and persist shadow-judge record in [eb43d98e](https://github.com/alexhawat/mergeCraft/commit/eb43d98e4f6aee926b44e23b04da78f39f3579fa)
- Pin judge findings, outage skip, and config thresholds in [40f2a323](https://github.com/alexhawat/mergeCraft/commit/40f2a3239af036b27cf20534627af2a42dc12313)
- RED review-path skip and dispatch contracts in [b5c987d9](https://github.com/alexhawat/mergeCraft/commit/b5c987d9a772d3d0167255d4ed5aef886f3350db)
- Remove satisfied J1 xfails after J2-J5 in [9c402917](https://github.com/alexhawat/mergeCraft/commit/9c40291746c40efd4ca6bb379781f456164c812a)
- RED suite and eval corpus for J2-J5 in [7a4045cc](https://github.com/alexhawat/mergeCraft/commit/7a4045cc53662359c5e3e66e75ee264493f1ed82)

#### Logging

- Isolate configuration probe in [c241c426](https://github.com/alexhawat/mergeCraft/commit/c241c4263aaa0b2cba18cc7a8fc23147838fe496)
- Restore queued handlers after capture in [24990993](https://github.com/alexhawat/mergeCraft/commit/249909934789e20a08470db040c6f6a03c043b6d)

#### Mcp

- Pin git guards ahead of grep normalization in [39ce53ee](https://github.com/alexhawat/mergeCraft/commit/39ce53ee79e3e6fe3f7c23bf0e53d08eb9074eb8)
- D24 drop unused primary_repo_state_dir_safe in [3ccc3b7a](https://github.com/alexhawat/mergeCraft/commit/3ccc3b7a58b632ec6df7055388c7c109145ca74f)
- D22 drop unused \_recover_last_reviewed_sha in [a2621ba4](https://github.com/alexhawat/mergeCraft/commit/a2621ba4c54370ffba8eb2e99b9c6f5abf04b4f7)
- Pin the trusted-run gate and the capture upload in [915e7ef3](https://github.com/alexhawat/mergeCraft/commit/915e7ef310402c333ef66d1835b0942774df288c)
- Remove dead enrich_analyzer_comment_body helper in [8e92a649](https://github.com/alexhawat/mergeCraft/commit/8e92a649c18724d624209906e5e28daf050624b7)
- Allow reviewer dispatch tools on primary surface in [92c3f03f](https://github.com/alexhawat/mergeCraft/commit/92c3f03fd0e015220fef5c83316b1152af753d46)
- Fix checkout_pr alias mock for classmethod patch in [1c3a3ff8](https://github.com/alexhawat/mergeCraft/commit/1c3a3ff8ccdfc42d8c02e8887d0ab232ba106be3)
- Fix live git-core sandbox integration test in [9c229a3b](https://github.com/alexhawat/mergeCraft/commit/9c229a3b6ebfc7204693360cfe34ec8e648fa557)
- Reconcile public MCP xfail markers in [3b8f2570](https://github.com/alexhawat/mergeCraft/commit/3b8f257024569bc383d06c5cb7e14858bc63a5cf)
- Add public MCP product RED suite (MP1) in [6f1a2fd8](https://github.com/alexhawat/mergeCraft/commit/6f1a2fd844ce5ff0d8af326e83ff1a5ac9905abe)
- Add RED coverage for empty GitHub Bearer tokens in [26ee2de5](https://github.com/alexhawat/mergeCraft/commit/26ee2de5efdf7b1bd2c16a10b639d912629286b9)
- Pin isolation contract under xdist in [90485e1c](https://github.com/alexhawat/mergeCraft/commit/90485e1c23413f108265d5add679b323bf404e40)

#### Mergecraft

- Bump action pin to cfa36704 in [26d208f2](https://github.com/alexhawat/mergeCraft/commit/26d208f224a76d5a0930c1540a9461f14f60b4f5)
- Bump action pin for recallPass dogfood in [3a698631](https://github.com/alexhawat/mergeCraft/commit/3a6986316654ad7e0e524d631450d9ee9cf573d6)

#### Opencode

- Locate the evidence grant wherever the environment puts it in [95c42431](https://github.com/alexhawat/mergeCraft/commit/95c424319f27dfc7cc916da2d61d94989f140f11)
- Pin global-config isolation against the real CLI in [dee8858f](https://github.com/alexhawat/mergeCraft/commit/dee8858f2600f9e1d56e91c45d66af54367c7164)

#### Prep

- Cover node dependency prep fail-closed paths in [9cf53f07](https://github.com/alexhawat/mergeCraft/commit/9cf53f078c21835ef2b4c0dce8f4c3f2341672d1)
- Simulate venv binaries in prep mock in [68aa9cdb](https://github.com/alexhawat/mergeCraft/commit/68aa9cdbd7bfdd1fdcf92ecbd1b509984369dbe7)

#### Pyproject

- Add project urls and classifiers in [102d1aa6](https://github.com/alexhawat/mergeCraft/commit/102d1aa61d8570b4d1b840d90fcd35a7efe48bae)
- Exclude test/eval-support modules from the wheel in [0d2f4c6b](https://github.com/alexhawat/mergeCraft/commit/0d2f4c6b94382339c5ab9cd44a87502e43cc3923)

#### Release

- Publish to PyPI as mergecraft-action in [1003fe93](https://github.com/alexhawat/mergeCraft/commit/1003fe9379987a9199879455982789fe027157ff)
- Pin the generator version in the prepare bump premise in [f3b75155](https://github.com/alexhawat/mergeCraft/commit/f3b751551508094f4c274e24bf9ce9dfefc0cf8a)
- Pin the prepare-time version bump for pyproject and server.json in [bf87ba86](https://github.com/alexhawat/mergeCraft/commit/bf87ba86bb964d4535be08f7e33db872339a9809)

#### Reliability

- Drop constant RecoveryOutcome from cleanup_on_failure in [e21d11f2](https://github.com/alexhawat/mergeCraft/commit/e21d11f211d9414191f001eb11f8465d888f2718)
- Observe recovery cleanup and its failure path in [7c56a7f8](https://github.com/alexhawat/mergeCraft/commit/7c56a7f860a73acffc6193dcdcfe96abe0095a84)

#### Review

- Load the diff-first fixture trajectory in [a87b8824](https://github.com/alexhawat/mergeCraft/commit/a87b8824c0907d1c8bb923be1bd3cbf6f44848f8)
- Pin the recovered review receipt binding in [9b84f584](https://github.com/alexhawat/mergeCraft/commit/9b84f58449b50055e4c7811a4dfde3050c3f258e)
- Lift attempt-scoped record markers in [401c8a2f](https://github.com/alexhawat/mergeCraft/commit/401c8a2f9db8541544fb4fb91ac21a72871d6f9f)
- Add red tests for attempt-scoped record and incomplete publication in [f2af089c](https://github.com/alexhawat/mergeCraft/commit/f2af089cde97fc016276cf039a165a0efdeff257)
- Lift VP3 red markers now that retirement is bound in [c3230728](https://github.com/alexhawat/mergeCraft/commit/c3230728493c65261407c2188ead57e657e8ad5a)
- Lift VP2 red markers now that publication is bound in [28512c1f](https://github.com/alexhawat/mergeCraft/commit/28512c1fb5bcd584461bc0def962cdc171417eab)
- Add red suite for verdict publication and fail-closed defaults in [b4a61312](https://github.com/alexhawat/mergeCraft/commit/b4a61312206e483955902c2a26f78af775293968)
- Keep withdrawn findings hidden in review in [cf597648](https://github.com/alexhawat/mergeCraft/commit/cf5976489a8a57bb55e034d27fa81b5a224ba5dd)
- Track pre-footer snapshot in progress-comment pin in [16f90e98](https://github.com/alexhawat/mergeCraft/commit/16f90e9850b90aae707f6797950d45cc23072723)
- Expect context-expansion tokens in the split summary in [e164b2ee](https://github.com/alexhawat/mergeCraft/commit/e164b2ee63c1af5f6863624f9d7f283a104bd31d)
- Pin step-summary posture on a terminal verdict in [a399619a](https://github.com/alexhawat/mergeCraft/commit/a399619a828c2796320e1c5a1969f42acac5cc7c)
- Add RED coverage for approval gate agent findings in [c6a27a3d](https://github.com/alexhawat/mergeCraft/commit/c6a27a3d57b163704f112c7d4be024f6f41bfe27)
- Reconcile CD durable review xfail markers in [6e298279](https://github.com/alexhawat/mergeCraft/commit/6e2982798785b268cd88909f9563734667958b2c)
- Red tests for durable review by id in [39f34640](https://github.com/alexhawat/mergeCraft/commit/39f3464054d911529924600e5f5bce6a7a3efbe1)
- Switch self-review model to nous/tencent/hy3 in [2b0107b8](https://github.com/alexhawat/mergeCraft/commit/2b0107b8802b3ba07670deccd2892b8b0116616f)

#### Review Record

- Expect the publisher-identity rule for the legacy sticky in [76c667b1](https://github.com/alexhawat/mergeCraft/commit/76c667b13841f2eafca095918377ba419125195a)
- Packet cache re-finalize regression in [93c13257](https://github.com/alexhawat/mergeCraft/commit/93c132570b777d48c578dbf038cee700ab2956b1)
- Add #535 digest-pin suite and fix Finding.scope allowlist in [e6abf31f](https://github.com/alexhawat/mergeCraft/commit/e6abf31f4b32a12c7cbd05c4f7fcc150d9d4b06c)
- Fix W16 mock review_payload capture in [d220374e](https://github.com/alexhawat/mergeCraft/commit/d220374eaa3f98e18253b3798ace9bd76b82d976)
- Fix W14 status-check test defects in [ce632835](https://github.com/alexhawat/mergeCraft/commit/ce632835151f0b8017000fa267c4af7e443eaa4b)
- Drop W3 xfails and narrow loop cases in [b3430928](https://github.com/alexhawat/mergeCraft/commit/b3430928453b0a1a2dfa7c410550e39b44f0de8a)
- Fix scoped-finding fingerprints and D2 trajectory pin in [85deda20](https://github.com/alexhawat/mergeCraft/commit/85deda202bb0542c98db6f360c3ff57c15e7f9f5)
- Pin schema self-correct without xfail in [2d9abefd](https://github.com/alexhawat/mergeCraft/commit/2d9abefd716811a88feebdf0c51bef013fe986cb)
- Drop xfail from already-passing W3 pins in [105364a4](https://github.com/alexhawat/mergeCraft/commit/105364a4e9cb4735fff297d71a7a7cbc85b3a7f5)
- Add W1 RED suite for plan 12 in [b7227f61](https://github.com/alexhawat/mergeCraft/commit/b7227f61256d327ec307f06c147a4c855e5e1c59)

#### Reviewer Resilience

- Pin lowercase extraheader config refusal in [d8305c97](https://github.com/alexhawat/mergeCraft/commit/d8305c97c524ab76a5394b42b3e9da4504507931)
- Pin scope evidence regressions in [4e009b05](https://github.com/alexhawat/mergeCraft/commit/4e009b05e488d1ae95ce0cdb23d579b67206676c)
- Pin Thermos git config credential leak in [ea1d3c98](https://github.com/alexhawat/mergeCraft/commit/ea1d3c9853be8c3176f200438b5efaf27a8f75f5)
- Final xfail reconciliation for ci-resume in [d80fd074](https://github.com/alexhawat/mergeCraft/commit/d80fd07464476d07536977a47cde1f705a237720)
- Reconcile W9 xfails after implementation in [3dd34434](https://github.com/alexhawat/mergeCraft/commit/3dd34434692235394de0c38f1708e4591db50631)
- Reconcile W8 xfails after implementation in [256e1009](https://github.com/alexhawat/mergeCraft/commit/256e1009d9cff2ea010ca194ce86f4adcb99fe43)
- Reconcile W7 xfails after implementation in [5213e79b](https://github.com/alexhawat/mergeCraft/commit/5213e79bc92fa4f6c77db5e0db8792854c7c3aa7)
- Reconcile W6 xfails after implementation in [985c1b7d](https://github.com/alexhawat/mergeCraft/commit/985c1b7dce721c57bfa4ddc148335f6ae723128d)
- Reconcile W5 xfails and phase guard expectations in [2c294705](https://github.com/alexhawat/mergeCraft/commit/2c294705acd1a05bfe98a80696992fae1a4e4e4c)
- Reconcile W3/W4 xfails after implementation in [ae2be1cb](https://github.com/alexhawat/mergeCraft/commit/ae2be1cbe2aaeeee381bc2d4aff9b5763cbba4c3)
- Add W1 RED suite for plan 13 in [0454efe0](https://github.com/alexhawat/mergeCraft/commit/0454efe00a6b9a707aaed22a1ac23e0d35752647)

#### Scm

- Prune webhook-route pins and scope the httpx compat patch in [af086621](https://github.com/alexhawat/mergeCraft/commit/af086621ff7ecb5f7e5d9bbd15818695c9dcd0fa)
- Drop obsolete ci/providers/gitlab.py boundary guard in [253be6b3](https://github.com/alexhawat/mergeCraft/commit/253be6b3ce7b6675429cdde922437287e9cf7278)
- Align cd_webhooks redelivery with D9 idempotency in [3c203fe0](https://github.com/alexhawat/mergeCraft/commit/3c203fe00e21cc3edd953f1700432e3e98f1ceee)

#### Security

- Add red suite for credential logging and cleanup in [f975f870](https://github.com/alexhawat/mergeCraft/commit/f975f8709647da76b27b53884d3e92f17dec56a1)
- Drain mock upstream bodies on keep-alive reuse in [963420e1](https://github.com/alexhawat/mergeCraft/commit/963420e14b9672b0bf7098250edddd87a40c19d3)
- Broker streaming and timeout contracts in [c82c889a](https://github.com/alexhawat/mergeCraft/commit/c82c889aabab7f32fc484076c9e450026ef1ec46)
- Require throwaway in OPENAI_API_KEY for broker guard in [a4649c98](https://github.com/alexhawat/mergeCraft/commit/a4649c98e215090c1ff60d78b12ba668e96eaa82)
- Allow broker throwaway in credential env guard in [29cfa6a1](https://github.com/alexhawat/mergeCraft/commit/29cfa6a12d309b36dc590bd3ca491f6dc0e1013d)
- Codex-shaped broker path and gzip encoding in [f3f96f90](https://github.com/alexhawat/mergeCraft/commit/f3f96f90cc94d83ca9bd783b3396803778385197)
- Prove MCB-06 integrity gate through opencode._run in [0a4972bd](https://github.com/alexhawat/mergeCraft/commit/0a4972bd14926d03595e5fef690a688a9794384a)
- Stub origin URL in shell push matrix in [e3f5b350](https://github.com/alexhawat/mergeCraft/commit/e3f5b350809c2df86d60eb8be7151a8eb62f1165)
- Align live sandbox tests with host probe in [0c25dbd3](https://github.com/alexhawat/mergeCraft/commit/0c25dbd3101c82c192fff259daf8d9f24df8823c)
- Restore offline fence and auth xfails in [f9b23665](https://github.com/alexhawat/mergeCraft/commit/f9b2366565b997141c4325869a37b1e2503c9f69)

#### Self Review

- Clear lane D thermo findings in [3215d585](https://github.com/alexhawat/mergeCraft/commit/3215d585e88cd8314927879d6b87a0cfcbbd4f38)
- Fix W6 gha_log group harness calls in [b2ed9a20](https://github.com/alexhawat/mergeCraft/commit/b2ed9a2003db08ac74061720a6d55866424d2f6f)
- Drop W4 xfails after green SARIF ingest in [0217edef](https://github.com/alexhawat/mergeCraft/commit/0217edef9b38350b18549b461f7c7db6d7e91c52)
- Drop W3 xfails after cascade backstop greens in [2935baf1](https://github.com/alexhawat/mergeCraft/commit/2935baf1b97d38bd4fd6feae1cfbb03ccd915f4a)
- Drop W2 xfails after config flip greens in [1b031e78](https://github.com/alexhawat/mergeCraft/commit/1b031e78212bae5800ba93c8026cf08bc11d721a)
- Land lane D W1 RED suite with strict xfail in [e69ec353](https://github.com/alexhawat/mergeCraft/commit/e69ec353858c9becfd658a219ce6f0dab56c493e)

#### Suite

- Mark nine branch-walking suites with coverage marker in [68bfdad1](https://github.com/alexhawat/mergeCraft/commit/68bfdad1e6f457a0ffda090dbc24ea7fe732bc2e)
- Delete stale xfails and falsifiable exit codes in [e19c35bf](https://github.com/alexhawat/mergeCraft/commit/e19c35bfbdea5f5c138083eb505ba70d6e5c0cf8)

#### Tracing

- D25 drop unused \_SinkProtocol in [01ed0339](https://github.com/alexhawat/mergeCraft/commit/01ed03395980156f9097d1e43fb69a2a4c369300)
- Reconcile the env fail-closed contract in [349f7bdb](https://github.com/alexhawat/mergeCraft/commit/349f7bdbb6fc556044efc3d984defe5d8fab3344)
- Reset enterprise state in exporter tests in [35044e64](https://github.com/alexhawat/mergeCraft/commit/35044e64358e7aadb5cb1b64bdafe298c82a5207)
- Assert OTLP emit path in singleton test in [da12c399](https://github.com/alexhawat/mergeCraft/commit/da12c39993165eb506b3ac27cbae209297312794)
- Reset tracer cache in exporter tests in [84b7e00c](https://github.com/alexhawat/mergeCraft/commit/84b7e00cc70ada9f3dfa5a9ae76632d1e1a9cb90)

#### Trust

- Lift VP4 red markers now that defaults fail closed in [0101f1d6](https://github.com/alexhawat/mergeCraft/commit/0101f1d61f5f057f932dc6a2429b13d565546432)
- Give CI a git identity and state the Actions env in [12ef0a57](https://github.com/alexhawat/mergeCraft/commit/12ef0a57cf88511ee00eea387e570387cbe4c541)
- Author the RED suite for trust boundaries in [fc9fe0c3](https://github.com/alexhawat/mergeCraft/commit/fc9fe0c352d29fa322f7c4051eeb1feaa4d3f43e)
- Enable selfReview full in dogfood config in [578ad6a3](https://github.com/alexhawat/mergeCraft/commit/578ad6a3c916b9d54bd8f4916d33f616abfbeff4)
- Enable agentSandbox same-repo in dogfood config in [ac4d949c](https://github.com/alexhawat/mergeCraft/commit/ac4d949cb34b6f7f95e65c38b7986632acbe7821)
- Enable selfReview analyzers in dogfood config in [77048f72](https://github.com/alexhawat/mergeCraft/commit/77048f72a76c1e67293fc9e54f884a107f5a7cc4)
- Reconcile W4 xfails for credential probe in [b8020c2b](https://github.com/alexhawat/mergeCraft/commit/b8020c2bf7fa857ad8a27cf18d14f0dc8bd60ca6)
- Reconcile W3 xfails for analyzer egress policy in [cd0555a3](https://github.com/alexhawat/mergeCraft/commit/cd0555a3cad05a1800ea28bafce02dd6ed857211)
- Reconcile W2 xfails for agentSandbox policy in [f6b05a1b](https://github.com/alexhawat/mergeCraft/commit/f6b05a1b9fc56b9ae3f330301c06e4760ef6377d)

#### Trust Credentials

- Reconcile W6 entropy sweep xfail in [769147d7](https://github.com/alexhawat/mergeCraft/commit/769147d732131578a81375fa66e67cb505187eb5)
- W2b publication guard and reconcile W5 xfails in [1a42b813](https://github.com/alexhawat/mergeCraft/commit/1a42b813ce4d810528df1b48a12cd4ab346e545d)
- Add W1 RED suite for lane B in [0c026fbe](https://github.com/alexhawat/mergeCraft/commit/0c026fbef930aafe0fb3cbe6df6df02b8ed4d6a4)

#### Utils

- Cover the run-owned directory registry in [c3573fe2](https://github.com/alexhawat/mergeCraft/commit/c3573fe24430ecac418357ba32015d4250417a35)
- D35 drop test-only is_valid_time_string in [97959607](https://github.com/alexhawat/mergeCraft/commit/97959607322fe02541f772c095f111ce89e93837)
- Drop test-only \_is_transient_http_error alias in [a952216c](https://github.com/alexhawat/mergeCraft/commit/a952216c2a7552a159c4c59accbb7c4a6262ed1c)
- D27 drop unused \_slug_runnable in [38f36389](https://github.com/alexhawat/mergeCraft/commit/38f363895fdd379fdd7cacaa9bc9e16d16930d4a)
- D23 drop unused run_bounds budget defaults in [1e799703](https://github.com/alexhawat/mergeCraft/commit/1e7997035ce7d2cfba34db33ef12e64569e54e4b)
- D20 drop unused \_needs_no_ext_diff in [d00329bf](https://github.com/alexhawat/mergeCraft/commit/d00329bff73e597477d26c1c9390bd9e7297fbd3)

#### Verify

- Guard the named CDP skip and its readable remedy in [a54c047d](https://github.com/alexhawat/mergeCraft/commit/a54c047d0bd3e4b51b42f922b1587023c1af4b34)
- Make the CDP suite hermetic and detect a no-op driver in [8a615eeb](https://github.com/alexhawat/mergeCraft/commit/8a615eeb0505fbb200744b214c6fab7c8312db00)
- Drop R3 xfail markers after CDP driver + JEV seam land in [bdfd812b](https://github.com/alexhawat/mergeCraft/commit/bdfd812b1430f57ec6589a5ed658f015b37771de)
- RED suite for CDP driver and JEV criterion seam in [5d797787](https://github.com/alexhawat/mergeCraft/commit/5d7977870179d4aeff212fc68893772f74724795)
- Un-xfail Playwright close on same loop in [3cd5d799](https://github.com/alexhawat/mergeCraft/commit/3cd5d79985d553e7930eb42d92b96ce9e253897d)
- Xfail Playwright close on same loop in [71ae3722](https://github.com/alexhawat/mergeCraft/commit/71ae3722717ac5d50bda7dbbbcfad54a4af9cba6)
- Un-xfail async Playwright runner tests in [a7d003be](https://github.com/alexhawat/mergeCraft/commit/a7d003be3845b60303f81db38b988eca4d8d1d08)
- Pin async Playwright inside the runner loop in [689fd1da](https://github.com/alexhawat/mergeCraft/commit/689fd1da16335413e4de2cc273d17341180cbeeb)
- Un-xfail CLI run_async event-loop tests in [0da266b5](https://github.com/alexhawat/mergeCraft/commit/0da266b599199ab19bbb465cc80d2750c9ae6063)
- Pin CLI run_async after Playwright launch in [0ded08b4](https://github.com/alexhawat/mergeCraft/commit/0ded08b47f6e7389e2cdbecbde9d933f94002442)
- Un-xfail Playwright launch bind tests in [44ad8ee0](https://github.com/alexhawat/mergeCraft/commit/44ad8ee0a092d187d0e355b2e82e2d946b580308)
- Pin CLI Playwright launch when extra present in [ed1ac35d](https://github.com/alexhawat/mergeCraft/commit/ed1ac35d84e93d8f7686b872fcd93ed356cbc6d3)
- Un-xfail behaviour-verification suite after V5 in [95483a0b](https://github.com/alexhawat/mergeCraft/commit/95483a0bee57b608f10ca9e7f4f4dae7cef569c9)
- RED suite for browser behaviour verification in [6fefc0e0](https://github.com/alexhawat/mergeCraft/commit/6fefc0e0cc25eff3bcb3f15330baefc68bc983ab)

#### Workflows

- Make OpenCode Go the first reviewer and drop Nous in [ccb099c5](https://github.com/alexhawat/mergeCraft/commit/ccb099c580b5ad6f1d87c3ae1892724b19e42755)
- Restore the Jev key to the review rungs in [14fd10cb](https://github.com/alexhawat/mergeCraft/commit/14fd10cba337f96228ede40c1c2ea714453d6e90)
- Add red suite for self-review trust and scaffolds in [f1b9a0f0](https://github.com/alexhawat/mergeCraft/commit/f1b9a0f06e9f4e869ed4e6f8dcc762febc54f700)

#### Other

- Pin stage prepares P instead of pushing it in [c18f6625](https://github.com/alexhawat/mergeCraft/commit/c18f6625afd6a969bf19abacadbbb1d66cc70191)
- Fix RA1 fixtures and remove xfail markers in [494eefbc](https://github.com/alexhawat/mergeCraft/commit/494eefbcdb6788a2a36f26734b4da52f845e8e04)
- Add RED suite for lane B BR2-BR8 in [6eb79d8d](https://github.com/alexhawat/mergeCraft/commit/6eb79d8d0ba834ff4edcbf8ead0db4c4ff00185c)
- Replace a live Logfire token with fake values in [9fafcb9a](https://github.com/alexhawat/mergeCraft/commit/9fafcb9a2b810fea7910df3ea0111b062fb6c2a0)
- Consolidate lane D issue bullets under Unreleased in [32b8f307](https://github.com/alexhawat/mergeCraft/commit/32b8f307a833d7a35ca1d6e8ad5f591ffbda6234)
- Add W1 RED suite for lane C operator surface in [ae831725](https://github.com/alexhawat/mergeCraft/commit/ae8317252d052a84c6c0b1e11c2b9d0429f59938)
- Cover registry api-key precedence over flat auth in [1635f47b](https://github.com/alexhawat/mergeCraft/commit/1635f47b35dbb67cef05aa0d20d345eac7103c26)
- Stop a release from moving :latest and :analyzers in [58e4eb7d](https://github.com/alexhawat/mergeCraft/commit/58e4eb7d2c8421a5e828cc7fb343ec0ad376e58f)
- Author the RED suite for the removal waves in [d3f150d3](https://github.com/alexhawat/mergeCraft/commit/d3f150d3d64e73598aca300adacb948cd1a35272)
- Build gh and actionlint with Go 1.27.3 (CVE-2026-111943) in [79da5691](https://github.com/alexhawat/mergeCraft/commit/79da5691691352fb3ccdc6e5f629c9b0d26ffc37)
- Reconcile satisfied xfails in [6bcd35b6](https://github.com/alexhawat/mergeCraft/commit/6bcd35b6a8d02e1f82987be7de06df16bdbdf0fc)
- Reconcile satisfied xfails in [a46989c2](https://github.com/alexhawat/mergeCraft/commit/a46989c21642f40a9b59e4eec01c4ee055131a39)
- Reconcile satisfied xfails in [c4ac380e](https://github.com/alexhawat/mergeCraft/commit/c4ac380e2c96af21519b9bd104b209d5eae735c0)
- Run the live slice on OpenCode Go, never the ChatGPT login in [283aa586](https://github.com/alexhawat/mergeCraft/commit/283aa5864392b5b0960d716751bfa570292638a2)
- Use \_active_client() not removed _client seam in [a66d4684](https://github.com/alexhawat/mergeCraft/commit/a66d46842f1c4165b7e679b3dbd3d1ce5c2aa7ce)
- Author the RED suite for the handed-off items in [3e85e5d3](https://github.com/alexhawat/mergeCraft/commit/3e85e5d35501910c07fc7de2eb9062fcc17d57ed)
- Exercise cursor cloud client errors and retries in [f4f5c2b1](https://github.com/alexhawat/mergeCraft/commit/f4f5c2b197b5e31b964a38f8909dd23fd74ad6b2)
- Cover publish deterministic record paths in [55269319](https://github.com/alexhawat/mergeCraft/commit/5526931955df8974ed2cbc72c3810a6d3a9ff5d9)
- Branch and language scope mismatches; classify migration diffs in [7aa3c29d](https://github.com/alexhawat/mergeCraft/commit/7aa3c29d3d97575e2cbe978b0968e8cec274a6ae)
- Add behavioral suite for similar issue and change matching in [02ed08f3](https://github.com/alexhawat/mergeCraft/commit/02ed08f3719104e350edfdf40ba4f2e4f072f3e6)
- Author RED suite for lane A AP2–AP7 in [d5ab4d55](https://github.com/alexhawat/mergeCraft/commit/d5ab4d554f46ebca485d032d3ea1f449aa74e419)
- Add red contract tests for prompt and doc surfaces in [b6b3c7e7](https://github.com/alexhawat/mergeCraft/commit/b6b3c7e7d28ccd9fb87e3ff702d55c0e4156db40)
- Add W1 RED suite for lane A in [d00cc5a0](https://github.com/alexhawat/mergeCraft/commit/d00cc5a0420c4ac8ec7e07cb61d8cda4db49c8be)
- Red suite for diagnostics, ports, tokens in [1307986c](https://github.com/alexhawat/mergeCraft/commit/1307986cde1003c8dafd73eae7c29381c57cb419)
- Drive ingest_requirements with fixture specs in [544d9b21](https://github.com/alexhawat/mergeCraft/commit/544d9b21fd7c6476b7bbb6fcf755537872426fa6)
- Author RA1 RED suite for audit-r2 lane A in [58f12ee4](https://github.com/alexhawat/mergeCraft/commit/58f12ee4e5c1d789809c7388d0f5f5f9da046f57)
- Pin normalize_repo_path and dedup consequences in [1aa6d842](https://github.com/alexhawat/mergeCraft/commit/1aa6d8421918aa81dc72a87ad60916cc30799593)
- Pin privilege drop, gate env and sink scan in [b646fc40](https://github.com/alexhawat/mergeCraft/commit/b646fc40f7bff7a600fc65f50ef46978de41db46)
- Anchor the include patterns to the project root in [7bb9e905](https://github.com/alexhawat/mergeCraft/commit/7bb9e9054182d928f18a999e322995bddae8571c)
- Sort sentinel unified test imports for ruff I001 in [5e93c395](https://github.com/alexhawat/mergeCraft/commit/5e93c3950288104309cf773ee091c8fb6fe45182)
- Sort the in-body import blocks in [7b2c123b](https://github.com/alexhawat/mergeCraft/commit/7b2c123b724742d69175ed5b9abf72805b319bcd)
- Raise the action-pin drift ceiling for the catch-up cycle in [0e5b6102](https://github.com/alexhawat/mergeCraft/commit/0e5b61026c6092f71a36b6802618dde60c091ab4)
- Build the dist on a release dispatch, drop the dev bump, slim the wheel in [1b4b1e39](https://github.com/alexhawat/mergeCraft/commit/1b4b1e39ee018918e2058df9a7ab1371be620965)
- Serialise codex consumers, name an expired credential, tighten workflows in [7a7b39ad](https://github.com/alexhawat/mergeCraft/commit/7a7b39ade1b5ecb809576fa3cbc9deaa0fc3d133)
- Ruff format LLM review timing modules in [2d4981c6](https://github.com/alexhawat/mergeCraft/commit/2d4981c6134e6df1549629ff60e97298f9612262)
- Format runtime_provider_registry in [e96b2563](https://github.com/alexhawat/mergeCraft/commit/e96b2563a4f34733bac97d6c1efb248d83525a8e)
- Ruff format CLI workflow wiring in [6aefdfeb](https://github.com/alexhawat/mergeCraft/commit/6aefdfebbb1129e8164725511ff52bb341f189fa)
- Host the recorded transports and canary hook, drop the xfail in [362b0f08](https://github.com/alexhawat/mergeCraft/commit/362b0f08edfc5de9ad26d3381a760bac065ae6bc)
- Prune unwired-seam pins and retarget the residency test in [3f623179](https://github.com/alexhawat/mergeCraft/commit/3f623179e8959d961c7f14190b781799c0bf416c)
- Declare CODEX_AUTH_JSON on the reusable E2E workflow in [eed6509f](https://github.com/alexhawat/mergeCraft/commit/eed6509f3a6f94dfbfc24c4d808ae1bcd9e52e78)
- Pin the dependency contract and make tooling claims true in [bad71460](https://github.com/alexhawat/mergeCraft/commit/bad71460308e7d30b6bc013670c2d0cf32e455fc)
- Publish CodeQL results and install-check the dist in [c6c1ebdf](https://github.com/alexhawat/mergeCraft/commit/c6c1ebdfb4a93fd76aaa7f351d920ac462a9b142)
- Fail integration, live and privileged lanes when they test nothing in [e88d01b8](https://github.com/alexhawat/mergeCraft/commit/e88d01b8423828bf4efdffdc650fc93278216581)
- Gate carryover app token on job env in [9c4eeb3b](https://github.com/alexhawat/mergeCraft/commit/9c4eeb3ba55179b6f0f8cc8a11d61d9842663a60)
- Refresh mergecraft action pin from main in [e86a1cdd](https://github.com/alexhawat/mergeCraft/commit/e86a1cdd78f4d7a6417659489d823b3e9f342aa4)
- Refresh mergecraft action pin from main in [b5b34825](https://github.com/alexhawat/mergeCraft/commit/b5b3482564417263b01de96f924aa2321934419b)
- Keep the unresolved security audit out of the public tree in [5e090079](https://github.com/alexhawat/mergeCraft/commit/5e090079759dab23b146369ba26af07225397fcb)
- Enable jev in the dogfood config in [86951c87](https://github.com/alexhawat/mergeCraft/commit/86951c87dc7b50786364170f2b87f8dd4439eb84)
- Ignore coverage parallel data files in [03fa7fce](https://github.com/alexhawat/mergeCraft/commit/03fa7fce079fdcbbdac83c3a82c55083e6dac180)
- Stabilize coverage-sensitive safety paths in [70c5d6c8](https://github.com/alexhawat/mergeCraft/commit/70c5d6c840fd857c0b8f9f9155c3478c75345418)
- Isolate global coverage floor fixture in [cbdf2b0c](https://github.com/alexhawat/mergeCraft/commit/cbdf2b0c88412e3cfa1ad5238464edadbe5d9151)
- Rebaseline attributable coverage floors in [4abd9199](https://github.com/alexhawat/mergeCraft/commit/4abd919939d87700ce2be6e039a43ad7d5572871)
- Keep the security job green on a SARIF artifact 403 in [9eeb92df](https://github.com/alexhawat/mergeCraft/commit/9eeb92dfc91637418a4118edea00a4a676dde08b)
- Drop continue-on-error from the reusable changelog-preview call in [a24c9c79](https://github.com/alexhawat/mergeCraft/commit/a24c9c799e7450affeef8e3d3daac7dded159ba4)
- Keep Verify green when GitHub releases 504 in [1f3f9b57](https://github.com/alexhawat/mergeCraft/commit/1f3f9b5799ccaf2290ba970eb2a6732d9b5da7d7)
- Do not fail Verify on SARIF artifact upload 403s in [f67e28ee](https://github.com/alexhawat/mergeCraft/commit/f67e28eeb36dffb111ec673befcd0e8b90503e28)
- Fix RS1 fixture and wiring bugs found in RS2 in [ec6c5ced](https://github.com/alexhawat/mergeCraft/commit/ec6c5cedee47f16dc3716fd31fa9bb96cdc76c6a)
- Add RED suite for review-skill-doctrine RS1 in [e4ee9dc7](https://github.com/alexhawat/mergeCraft/commit/e4ee9dc7b90b3ef7483710d98f903199351cc432)
- Ignore local .opencode config in [78fbee18](https://github.com/alexhawat/mergeCraft/commit/78fbee18dc9827358e29d39b032251eb09d2d9b0)
- Run the filtered-egress enforcement test on a privileged runner in [faf280a0](https://github.com/alexhawat/mergeCraft/commit/faf280a04167ff174b63a82e56c0a3cee2a512ce)
- Run the filtered-egress enforcement test on a privileged runner in [2923d2c7](https://github.com/alexhawat/mergeCraft/commit/2923d2c7f9691881ed1d14f66806afcebf7fcd2b)
- Bump the reviewer action pin to 78bfbeb2 (pin 10) in [1db95201](https://github.com/alexhawat/mergeCraft/commit/1db95201b7fa5d54bc4e98b4b21eb33d5b1c40f1)
- Match action.yml runs.image to the GHCR digest for 78bfbeb2 in [3f5a2681](https://github.com/alexhawat/mergeCraft/commit/3f5a268130d6ac55f6271c359f704d066aedec9a)
- Bump the reviewer action pin to 78bfbeb2 (pin 10) in [4b2c9b6b](https://github.com/alexhawat/mergeCraft/commit/4b2c9b6b9b62312a58b30e0edc30368b6ee7903a)
- Document cache-poisoning exception for integration.yml's push trigger in [9f01511c](https://github.com/alexhawat/mergeCraft/commit/9f01511cad43c63606c44c52b8b853b8b6fd80af)
- Keep integration coverage for push and release-branch events in [77674307](https://github.com/alexhawat/mergeCraft/commit/77674307a662b26ba11827b8f78c68dd253cfc7b)
- Nightly audit C4 cleanup — wire mcp check, delete dead scripts in [1b636a4e](https://github.com/alexhawat/mergeCraft/commit/1b636a4ecebaf65eac7ff1f5e6a7520bd5dbcff2)
- Drop redundant integration job from ci.yml in [20d36d80](https://github.com/alexhawat/mergeCraft/commit/20d36d80027c5dfb4b2a96fedcc815ae773a88d7)
- Bump the reviewer action pin to e3a0cc27 (pin 9) in [#648](https://github.com/alexhawat/mergeCraft/pull/648)
- Match action.yml runs.image to the GHCR digest for 3f48d9fe in [95d225ca](https://github.com/alexhawat/mergeCraft/commit/95d225caae7f2a74705ec5473be7e21413c75c4e)
- Bump the reviewer action pin to 3f48d9fe (pin 8) in [42672307](https://github.com/alexhawat/mergeCraft/commit/4267230787dc49e55550ee89c4661b0d5a780ba5)
- Match action.yml runs.image to the GHCR digest for 7f0ef988 in [fb37aacd](https://github.com/alexhawat/mergeCraft/commit/fb37aacd329f56fb8e68577d1762d2ea01a55e04)
- Bump the reviewer action pin to 7f0ef988 (pin 7) in [102ff80d](https://github.com/alexhawat/mergeCraft/commit/102ff80d3bdca960d60a318d6a67cab554a94336)
- Stop leaked threads polluting captured stderr in [838662b6](https://github.com/alexhawat/mergeCraft/commit/838662b61d7ff534b3bddf7a8cc8bae00038d187)
- Match action.yml runs.image to the GHCR digest for 7fcdc6c2 in [a3dd0b6e](https://github.com/alexhawat/mergeCraft/commit/a3dd0b6e2f277d676e8594089d3f2a3c4ebbfd7b)
- Bump the reviewer action pin to 7fcdc6c2 (pin 6) in [da53c820](https://github.com/alexhawat/mergeCraft/commit/da53c820d19699cd61a39becdce091cf5d1fc7b6)
- Ignore generated hostile-repo fixture scripts in [401542d3](https://github.com/alexhawat/mergeCraft/commit/401542d3a5eee3040ccaa986a506886d797f555d)
- Match action.yml runs.image to the GHCR digest for 93a7897c in [2a0df7db](https://github.com/alexhawat/mergeCraft/commit/2a0df7db7b2f0d505ffc40addd08069bcede0d6b)
- Point the action pin at the digest commit in [a7932f23](https://github.com/alexhawat/mergeCraft/commit/a7932f236560c0c23ee08398c220b3dee14b0e9a)
- Match action.yml runs.image to the GHCR digest for 5d68b56f in [93a7897c](https://github.com/alexhawat/mergeCraft/commit/93a7897c1e7fecabb094759d5d05b3b20e23708a)
- Bump the reviewer action pin to the Logfire region fix in [1a619d30](https://github.com/alexhawat/mergeCraft/commit/1a619d30685870965740cc9e65873a86031a0d22)
- Retry workflow-lint GitHub-releases curls in [4e11637f](https://github.com/alexhawat/mergeCraft/commit/4e11637fdf62493cb003201f88ecd2039fef61e9)
- Switch Codex self-review to openai/gpt-terra in [f515b8ab](https://github.com/alexhawat/mergeCraft/commit/f515b8ab95033d5aa86aa11b8f61841d67f41db9)
- Switch the Codex review rung to gpt-5.6-terra in [a5a24ab7](https://github.com/alexhawat/mergeCraft/commit/a5a24ab71cb41b49d53e019ef73b8a59a01ff0ed)
- Convert trufflehog JSONL to SARIF for CI evidence in [0843c860](https://github.com/alexhawat/mergeCraft/commit/0843c8604be2eab5f972612dccd07bbcc02cadd2)
- Match action.yml runs.image to the GHCR digest for e5f9ed5f in [813026e3](https://github.com/alexhawat/mergeCraft/commit/813026e348e663d219b7db961632a57accbedc2a)
- Bump the reviewer action pin to the lane D promotion in [fc5cb4be](https://github.com/alexhawat/mergeCraft/commit/fc5cb4be7b35b8e74f4a488a739e586fb8b79900)
- Match action.yml runs.image to the GHCR digest for 4ab87265 in [bc61c431](https://github.com/alexhawat/mergeCraft/commit/bc61c4316bf5e740a6981cbae3239201810d042d)
- Bump the reviewer action pin to the lane E promotion in [32f9c0ed](https://github.com/alexhawat/mergeCraft/commit/32f9c0ed83a2d9ef7e1f9a02f0c65c56c1e6c59e)
- Match action.yml runs.image to the GHCR digest for 4182fd45 in [476f7891](https://github.com/alexhawat/mergeCraft/commit/476f78910e4f2165e2df547abc7d81ff185428a7)
- Bump the reviewer action pin to the lane B promotion in [fd760529](https://github.com/alexhawat/mergeCraft/commit/fd760529c0caf64b967902df95e7979e96ffeb76)
- Match action.yml runs.image to the GHCR digest for 3ed2c798 in [1a38d4d6](https://github.com/alexhawat/mergeCraft/commit/1a38d4d655dd0db6d7ab344d59ad90ea35415224)
- Bump the reviewer action pin to the lane A+C promotion in [4750028f](https://github.com/alexhawat/mergeCraft/commit/4750028fa6ac5de887213e211546955c61d510c7)
- Drop accidentally staged hostile git fixtures in [2c80b20b](https://github.com/alexhawat/mergeCraft/commit/2c80b20b87e3b4aa6ad396aa75577553db0d5953)
- Point action.yml at the image bootstrap published for the new pin in [9e8370f9](https://github.com/alexhawat/mergeCraft/commit/9e8370f9c046c65ee25233bf4c40f019b03d32cc)
- Bump the reviewer action pin to the three-plan promotion in [1d542440](https://github.com/alexhawat/mergeCraft/commit/1d54244003e4f4b0d40ca9d38db668b11a7c4234)
- Bump the reviewer action pin past the claude CLI fix in [87c2737a](https://github.com/alexhawat/mergeCraft/commit/87c2737a661549d906fa560eae1ee18ef100801e)
- Bump the reviewer action pin to the promotion merge in [59f73042](https://github.com/alexhawat/mergeCraft/commit/59f7304250107499f2e05d1a550c57af44b29f23)
- Merge pre-0.0.1 into lane C authority gates in [a5e19af3](https://github.com/alexhawat/mergeCraft/commit/a5e19af3ee497f064b44d9dcb583a3d6481276a7)
- Drop the Codex sandbox override from the token fix in [44c2d20f](https://github.com/alexhawat/mergeCraft/commit/44c2d20f53ea487b966ae8053841489debf26161)
- Post review check-runs from the job token, not a PAT in [15f1ba4d](https://github.com/alexhawat/mergeCraft/commit/15f1ba4dac2221781295fc809589da8733f92ff5)
- Bump the self-review Action pin to b3638ea7 in [19e45ea6](https://github.com/alexhawat/mergeCraft/commit/19e45ea68e1632aeaed7cd16f832251a48e094a2)
- Refresh the self-review Action pin to b34e9f25 in [5d710e81](https://github.com/alexhawat/mergeCraft/commit/5d710e814d88a24fc1585bf8f19c13437e932435)
- Add Claude as a cross-vendor review backstop in [1bd2d7c8](https://github.com/alexhawat/mergeCraft/commit/1bd2d7c8edc08c587b44001994bd64d63ea0429d)
- Disable checkout credential persistence on privilege-root in [495ebfc9](https://github.com/alexhawat/mergeCraft/commit/495ebfc90e67c00fa002e1725a779345928075f0)
- Cover webhook 8KiB cap and support_bundle root in [f4242b4a](https://github.com/alexhawat/mergeCraft/commit/f4242b4abffb4cd3ddb87a441a62ecc8205c60c8)
- Import ARCHIVE_MAX caps from archive_bounds module in [109c925f](https://github.com/alexhawat/mergeCraft/commit/109c925f9e74938e44f10052a23d4e24247ada4b)
- Cover audit verify and legacy merge after thermos fixes in [07c74529](https://github.com/alexhawat/mergeCraft/commit/07c745290e6d1a67921ad4c0e2788b44b535f041)
- Align lane B tests with thermos CQ round 1 API changes in [e39985b6](https://github.com/alexhawat/mergeCraft/commit/e39985b662a890a1fb55bf799154a73a431c28c1)
- Fix post-integration failures on lane B stack in [dec96bfd](https://github.com/alexhawat/mergeCraft/commit/dec96bfd4c155dc873c6b4d9e70c228d1f623049)
- Align harness/config tests with unified redaction sentinel in [ae710fe0](https://github.com/alexhawat/mergeCraft/commit/ae710fe001378daafa7e321185a31b84b972ef92)
- Gitignore local wave agent kit paths in [9276d6db](https://github.com/alexhawat/mergeCraft/commit/9276d6dbf15afabb9faff955955fa0a9aa7adc32)
- Sync tracing extra in bootstrap for unit tests in [1f002a01](https://github.com/alexhawat/mergeCraft/commit/1f002a0155742c30888ac6d6617436a484135438)
- RED contracts for test-suite hygiene wave in [f4595a89](https://github.com/alexhawat/mergeCraft/commit/f4595a89ebe4f4adc6fc30e7cf4ee4c06d8035b4)
- Cover mypy error SARIF and global opencode harness in [d71f04d6](https://github.com/alexhawat/mergeCraft/commit/d71f04d6aeef7b74464fb7a9bfc4374540ab6650)
- Align legacy suites with provider registry in [f0048797](https://github.com/alexhawat/mergeCraft/commit/f004879724d6b5b3b3b86d6b124bb2dfdc1c83f1)
- Bump the review pin and measure it against the branch tip in [982ab84a](https://github.com/alexhawat/mergeCraft/commit/982ab84a77514118a991733bfa2a45a5704c61b0)
- Detect self-review Action pin drift from the default branch in [6efa36d1](https://github.com/alexhawat/mergeCraft/commit/6efa36d13999cb0207fac2c03504e42ae310f86e)
- Fix flaky full-suite CI failures for Final gate in [93c18fce](https://github.com/alexhawat/mergeCraft/commit/93c18fce24d466b4512b587e6eb73d4294023eac)
- Gate coverage on the base branch after merge in [e8672678](https://github.com/alexhawat/mergeCraft/commit/e8672678eb1b8ac3891bec7c6f2293d7f6e62f85)
- Raise coverage floor to 82% in [27930f5b](https://github.com/alexhawat/mergeCraft/commit/27930f5bf36a926b7c26411bb11da6fb9319d1e7)
- Lint called-workflow permissions on uses jobs in [887b9c94](https://github.com/alexhawat/mergeCraft/commit/887b9c94405991545a0fbddc76f7ecb624dd7a79)
- Pin Codex home fallback tests off host /tmp in [c142d444](https://github.com/alexhawat/mergeCraft/commit/c142d4448c4f1dbf2b5166dd32d2e2d25fbed5b6)
- Cover provider, CLI, and antislop branches for #431 in [d4810326](https://github.com/alexhawat/mergeCraft/commit/d4810326ee06abddad5e93fdc8ab7322715b5991)
- Cover the payload gate at the real package version in [7e2ec3bf](https://github.com/alexhawat/mergeCraft/commit/7e2ec3bf1471fbd3c9d23c9f8868033b0b21662d)

### Other

- ci, docs: clear the zizmor and URI-secret findings from the #1012 review in [2d90070d](https://github.com/alexhawat/mergeCraft/commit/2d90070df2522211a61b321a4ad33f995389bf73)
- Keep calibration fingerprints stable after verdict capture redaction in [54254420](https://github.com/alexhawat/mergeCraft/commit/54254420cef18d22ee64d28cfdb176cabe02b391)
- Align judge calibration fixtures with resolved agent fingerprints in [d591534b](https://github.com/alexhawat/mergeCraft/commit/d591534ba47922de137655262ba35faf885d77f2)
- Address PR #1021 review: strict export, D6 raised_by, integrity scope, roster deadlines in [14bdca2c](https://github.com/alexhawat/mergeCraft/commit/14bdca2c0e98e5de592dfe9a0be181040ea664cf)
- Fix dual-reviewer dispatch, verdict submit, fingerprint export, and integrity baseline in [5196dd8d](https://github.com/alexhawat/mergeCraft/commit/5196dd8d55f84fd34b059fb08ce915ad25429abd)
- Restore harness resolve imports in Ultramarine catalog tests in [e8a865f0](https://github.com/alexhawat/mergeCraft/commit/e8a865f005c976222daf41137729c9abba0c4755)
- Fix ruff import order after OpenCode-only trim in [d1167826](https://github.com/alexhawat/mergeCraft/commit/d11678263e3f4af4fc54fafa95abe8f6c491ed6e)
- Trim Ultramarine to OpenCode harness only in [0911fb61](https://github.com/alexhawat/mergeCraft/commit/0911fb6146e6b44587801734155e1cb28813c0be)
- Wire Ultramarine output cap into Codex direct OpenAI HTTP path via generation proxy in [53d47a0d](https://github.com/alexhawat/mergeCraft/commit/53d47a0d71482def76be81aadbde94e826ec2952)
- Test submit_review_verdict preserves raised_by_models on deduped findings in [96f09590](https://github.com/alexhawat/mergeCraft/commit/96f095907c3d79ac3dc89cd4d83307818af99bb1)
- Pair reviewer models via raised_by_models on deduplicated findings in [75b2e8b6](https://github.com/alexhawat/mergeCraft/commit/75b2e8b6907be5ad6b3aef8010009814ec261229)
- Hook LLM review timing on NullSpan llm.call enter in [bb17efec](https://github.com/alexhawat/mergeCraft/commit/bb17efec75e30dbaa714c05505b323381362ef40)
- Keep deduped raised_by_model as str for AgentFinding wire schema in [c77a1165](https://github.com/alexhawat/mergeCraft/commit/c77a1165086c957b6fabac60e001fa1ec70628c9)
- Address mergecraft review: OpenCode output cap and dedupe model provenance in [aea5e23b](https://github.com/alexhawat/mergeCraft/commit/aea5e23bf3c32637599734052a3334ae8398930e)
- Regenerate support matrix for paperinstruments provider in [10139ee6](https://github.com/alexhawat/mergeCraft/commit/10139ee62f96bede2dce02d5b909dabf5fe2b3f5)
- Format curated_model_catalog.py for ruff format CI in [7a55b98a](https://github.com/alexhawat/mergeCraft/commit/7a55b98a2fd90ddc236d5c4946c75d12b7f7977c)
- Fix CI: ruff import order and built-in provider count (15) in [ca1c9d55](https://github.com/alexhawat/mergeCraft/commit/ca1c9d55637d1b54b6e0a9f692fb9a98c8804fee)
- Register OPENCODE_GO_API_KEY in credential authority in [1d899a0b](https://github.com/alexhawat/mergeCraft/commit/1d899a0b5c4e8a5bc21498792b41ebf991841ac6)
- Fix mergecraft review findings on opencode-go wiring in [4850c990](https://github.com/alexhawat/mergeCraft/commit/4850c990897cc43dd97e2d7123bd0138038c17dd)
- Fix OpenCode auth integrity baseline and use Go deepseek-v4.1-flash in [54aec49e](https://github.com/alexhawat/mergeCraft/commit/54aec49eb238192554a78d598f22bf00c48223ee)
- Document OpenCode Go DeepSeek models alongside Zen GPT Sol in [93639604](https://github.com/alexhawat/mergeCraft/commit/936396049ed5af6d99cbfeb1cb27fc402897d412)
- Regenerate reference docs after auth opencode command in [2f1b2508](https://github.com/alexhawat/mergeCraft/commit/2f1b2508c451eb8ae6872735f28144978b5f7140)
- Add OpenCode Zen subscription auth for opencode harness in [6dbd779a](https://github.com/alexhawat/mergeCraft/commit/6dbd779a58505b1a5edfd659b3c3e428e3e54c7e)
- revert(tests): restore DQ1 RED short-id failsoft markers in [241465ee](https://github.com/alexhawat/mergeCraft/commit/241465ee96edc101a1dc67093396320ff63a75e2)

_Plus 1 more_

## [Unreleased]

### Breaking — action required

- **The PyPI distribution is named `mergecraft-action`.** `merge-craft` cannot be
  registered: PyPI refuses a new project whose name differs from an existing one
  only by separators, and an unrelated `mergecraft` project already exists.
  **Fix:** install with `uv tool install mergecraft-action`, or the pinned git
  form. The CLI binary, the import package, the MCP server name, the Action name
  and the container image are all unchanged.

### Added

- OTLP traces read properly in Datadog LLM Observability. Every exported span
  carries `gen_ai.conversation.id` (the review's trace id), so each review is one
  session and pipeline spans (analyzers, phases, publish) are no longer dropped;
  OpenCode plugin spans join the same session. When the sink sends
  `dd-otlp-source: llmobs`, pipeline spans without a GenAI operation get
  `invoke_agent` (run root) or `execute_tool` and `gen_ai.provider.name=mergecraft`,
  which Datadog requires on every span; tool payloads move to
  `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result` so tool spans show their
  input and output; and the per-process `session_id` is renamed
  `mergecraft.session_id`. Other backends do not get these changes. Datadog prices
  LLM spans only from its own model catalog, so a model it does not list (such as
  `deepseek-v4.1-flash`) shows no cost there.
- OpenCode 2.x runs can trace the inside of the session: set
  `MERGECRAFT_OPENCODE_OTEL_PLUGIN` to an
  [opencode-plugin-otel-v2](https://github.com/alexhawat/opencode-plugin-otel-v2)
  checkout and, when tracing exports to `otel` or `logfire`, each run adds one span
  per LLM step (tokens, cost, finish reason) and per tool call, nested under the
  review's `mergecraft.agent.run` span. The plugin's prompt and tool bodies follow
  `tracing.content` and the untrusted-tier cap; its header values travel in env
  vars, never in the on-disk OpenCode config. Operator-only: repository config
  cannot enable it. Only a plugin whose runtime entry (the file `package.json`
  names, not unbuilt source) reads `captureContent` is loaded. Encoded OTLP env
  headers are decoded as the Python exporter decodes them, so the plugin
  authenticates with the same credential, and every forwarded credential is handed
  to the plugin's redactor so one echoed into a prompt or tool body is masked.
- Reviews now read the materialised diff first. Review and IncrementalReview
  render a shared hard instruction: `diffPath` (or `incrementalDiffPath`) is the
  authoritative review scope, `git diff` / `git grep` / `git log` must not be used
  to reconstruct it, and independent reads are batched into one turn. The
  instruction is rendered for every consumer, not only this repository's
  workflow.
- Diff line-range coverage: `changed-unread-file` reports the unread added-line
  ranges (`path:start-end`) instead of whole files, and `submit_review_verdict`
  nudges once with exactly those ranges before accepting the verdict. Reads of
  the diff file itself count (recorded as `diff_read_path` / `diff_read`), and a
  run with no observed reads is *unknown*, not unread. Deletion-only and
  mode-only sections stay in scope and are named until their path is read.
- A no-output/idle watchdog for CLI agent drivers: no parsed event for
  `agentIdleTimeout` seconds (default `900`, `0` disables) kills the attempt and
  reports the idle span, event count, whether the model produced output, the last
  provider error, and the stderr tail. The attempt still fails so the chain can
  advance, but the run outcome is `infra_error`, not a failed review.
- `run_metrics` on the merge evidence packet (schema `1.15.0`): tool calls, read
  calls and read turns, distinct files read, diff line counts, elapsed by phase
  (setup / analyzers / agent / judge / publish), and the last watchdog
  diagnostic. The deterministic run record renders it as a **Review cost** row.
  Measurement only — it never feeds the gate.
- Bounded file-group fan-out planner (`review/file_group_fanout.py`): a large
  diff splits into at most six balanced read-only groups, and a failed group is
  recorded rather than raised. Planning and degradation only; it is not wired
  into server-side roster dispatch in this release.
- Analyzer disposition ledger: every raw analyzer hit gets a stable `hit_id` and
  ends `kept`, `merged`, `downgraded` or `dropped:<stage>` with a required reason.
  The merge evidence packet (schema `1.14.0`) carries the ledger, per-stage counts
  and the baseline-suppression audit rows that were previously only logged; the
  pre-merge Analyzers row reads like `ruff 14 raw → 3 kept (9 out_of_scope, 2
  baseline)`. SARIF ingested via `ciEvidence.sarifArtifacts` follows the same
  contract (#941).
- `self-silencing` analyzer (in-process, every trust tier, no shell): reports added
  suppression markers (`# nosec`, `# noqa`, `// eslint-disable-next-line`,
  `#[allow(..)]`, `//nolint`, …) with the rule codes they silence, and loosening
  edits to `.mergecraft/config.yaml`, `ruff.toml` / `pyproject.toml`, ESLint config
  and scanner ignore files. Edits to `.mergecraft/**` and analyzer/linter config
  also keep a PR out of the `eligible` blast-radius lane (#942).
- `analyze_ci_failures` reads the base branch's recent runs itself, so a
  same-fingerprint base failure clears a failure as pre-existing with no
  agent-supplied arguments; the runs it used are recorded in the result and the CI
  evidence. A passing or unrecognised base status never clears one (#891).
- Opt-in `gherkin-lint` catalog analyzer: syntax and structure lint for changed
  `.feature` files, run through the repo's own pinned `gherkin-lint`. Disabled by
  default because the catalog has no managed npm runtime; enable it with
  `analyzers.overrides.gherkin-lint.enabled: true` (#854).

### Changed

- Review and IncrementalReview now tell the agent how long it has and how to
  read code, so a large review submits a verdict inside its timeout instead of
  being killed while still exploring. The prompt states the agent deadline (run
  timeout minus setup time) with checkpoints: stop exploring by ~60%, submit by
  ~80%. It also makes `run_analyzers` and `run_static_checks` the first calls
  after `checkout_pr`, reads code with a plain `grep -n` plus a ~60-line ranged
  read, forbids repeating a call whose result is already in context or retrying
  variants after a tool error, and runs `git diff <base>...HEAD` once when the
  diff file is refused. Triage now investigates the riskiest hunks first instead
  of pulling "as much context as you need". Because the agent has no clock, once
  it passes 60% of its deadline each successful tool result on the review
  agent's MCP route carries a notice such as `⏱ 16 of 25 min used, about 9 left:
  stop exploring…`, switching to "submit the verdict now" at 80%. A JSON-object
  result gets it as a `timeBudget` field (so OpenCode 2.x code mode, which
  parses the joined text, still sees valid JSON); a plain-text result gets a
  trailing line. Trajectory records and traces never see the notice. The
  verifier route and runs with no timeout get none, and the prompt shows a
  neutral line instead. `compute_modes` takes an optional `time_budget_minutes`.
  The prompt version hash changes.
- Incremental re-review is the default on a re-review. `checkout_pr` now computes
  the range whenever a prior reviewed sha is recoverable — not only when
  `select_mode` chose IncrementalReview — and reports
  `incrementalDiffStatus` (`ok` / `empty` / `unavailable`) with
  `incrementalDiffReason` and `lastReviewedSha`. When the range exists it is the
  review scope; the full diff is for anchoring only.
- The merge evidence packet schema is `1.15.0`; the trajectory record schema is
  `1.1.0` (optional `diff_read_path`, `diff_read`, `duration_ms` on a tool-call
  row, all omitted while unset).
- A PR's own `analyzers.*` configuration no longer applies to its own review. The
  analyzer settings (`enabled`, `overrides.<id>.enabled`, the `antislop` `rules` and
  `ignore`, `baseComparison`, `inlineBudget`, `impact`) are resolved from the PR's
  base — the operator-owned base snapshot, or the base commit's
  `.mergecraft/config.yaml` — and a head-side change is reported by
  `self-silencing` instead of applied. A symlinked or unreadable base config falls
  back to built-in defaults with a named reason. **Fix:** land analyzer-config
  changes in their own PR; they take effect from the next PR on (#942).

- A run whose analyzer disposition ledger is open — a pipeline stage lost a raw hit
  without recording why — now ends with a `neutral` approval conclusion instead of
  possibly `success`, and a run-scoped finding names the orphaned hits. A blocker
  still outranks it. **Fix:** none for consumers; the finding names the stage to fix
  (#941).

- A mistyped tracing sink (`tracing-to`, `MERGECRAFT_TRACING_TO` or `--tracing-to`
  with a typo such as `logfier`) now ends the run as `configuration_error` on the
  Action and exits with the configuration code on the CLI, naming the variable and
  the value. It used to end as `infra_error`, the outcome of an unclassified crash.
  With tracing off the typo is still ignored and now logs a warning (#930).

- The per-file `changed-unread-file` run-health finding is `Minor` instead of
  `Major`: still listed in the record, and the gate is unchanged — `gate_policy`
  still maps `changed-unread-file` to `request-changes` by rule id, so this only
  stops a Major row per unread file from burying the change-scoped reasons (#885).

- The Release workflow now dispatches CI/CD on the release branch it prepares, and
  CI/CD's `build-dist` job accepts a dispatch on a `release/*` branch or a `v*` tag, so
  the workflow path produces the `artifact-python-dist` the publish step needs. Its
  publish gate names the real approval, `craft publish` with publish credentials, instead
  of a label that nothing acts on (#1004, #1005).

- The wheel no longer ships five more checkout-only modules (`scm/webhooks.py`,
  `evidence/shadow_compare.py`, `evals/human_batch.py`, `evals/skill.py`,
  `agents/catalog_docs.py`); each is reached only from Make targets, scripts or tests (#947).

- The review job joins the `codex-subscription-auth` concurrency group, so two consumers
  never refresh the Codex subscription login at once. GitHub keeps one pending job per
  group, so a third queued review replaces the pending one and needs a re-run (#882).

- Every `actions/checkout` that does not push sets `persist-credentials: false`, and the
  redaction module's own URI patterns no longer flag in the CI secret scan, which allows
  one detector in one file rather than the whole file (#885).

- The structural eval baseline is regenerated with the three multi-round cases
  replayable: `inconclusive_rate` falls from 0.0816 to 0.0204 (3 of 49 cases were
  permanently blocked), with no behaviour change (#892).

### Fixed

- The `tracing` extra moves to OpenTelemetry 1.45.1 (semantic conventions
  0.66b1), which fixes CVE-2026-114603 in `opentelemetry-api` 1.44.0. That
  advisory failed the `pip-audit` security check on every build. The 1.45 OTLP
  exporter keeps its headers on its HTTP client, lowercased and merged with
  `OTEL_EXPORTER_OTLP_*` settings, so reuse of an exporter for the same endpoint
  and headers is matched case-insensitively against those; two new transitive packages,
  `opentelemetry-exporter-http-transport` and `opentelemetry-exporter-otlp-common`,
  come with it.
- A review whose verdict carries a finding with a model-made fingerprint
  (`ci-static-llms-full-stale`) now prints. The verdict back-fill stored the slug
  as-is; the CLI then failed with "fingerprint must be lowercase hex" before
  rendering anything. Back-filled fingerprints are now normalized to hex, as on
  every other path into the run. A slug that carries a path
  (`tests/x.py:30:pin-the-cli`) is hashed too, instead of failing the run with
  "unsafe fingerprint value" (exit 30) after its verdict was recorded.
- OpenCode reviews can read a tool result that was too large to return inline.
  OpenCode saves the full text under the run's data directory and tells the model
  to read it there, but the agent was denied that whole directory to keep the
  auth store out of reach, so every such read failed. The `tool-output` folder is
  now readable; the auth store beside it stays denied.
- A failed span exports with OTel status `ERROR`. Spans mergeCraft marked as failed
  went out as `unset`, so Datadog LLM Observability and Logfire counted a crashed
  run as a success and only its `error` attribute said otherwise.
- A trusted review whose repo gates write build output (`dist/`, regenerated docs)
  no longer fails its integrity check. `run_static_checks` re-pins the read-only
  baseline around in-place gates, as `checkout_pr` does, after first checking that
  nothing changed before the call — so an agent's own writes still fail the review.
- Model names, review ids, session ids and tool-call ids in trace attributes are no
  longer masked as `<redacted>`. These identifier attributes still pass the explicit
  secret patterns (`sk-…`, `ghp_…`, …) but skip the entropy heuristic, which read
  `deepseek-v4.1-flash` and 32-hex ids as secrets.
- OpenCode reviews can read the review diff with the `read` tool. The diff sits in
  the run's temp dir, outside the checkout, so `read` refused it and agents fell
  back to workarounds. The temp dir is now readable, except its isolated auth store,
  config dir and scratch HOME, but only when this run created it with `mkdtemp`: an
  operator-chosen or shared directory passed as the run's temp dir is not opened.
- OpenCode reviews no longer load the reviewed repository's own OpenCode config
  (`opencode.json`, `.opencode/`). A repository could otherwise add MCP servers or
  plugins — code that runs inside the reviewer — including from a fork PR.
- A review whose static checks run repo linters in the checkout no longer fails its
  integrity check: `.ruff_cache`, `.mypy_cache` and `.pytest_cache` are skipped like
  `__pycache__`.
- OpenCode reviews no longer load the operator's global OpenCode config. Each run
  gets an empty `OPENCODE_CONFIG_DIR`, so global MCP servers, plugins and agents
  stay out of the review — and a global MCP server named `mergecraft` no longer
  shadows the run's own server, which had left the agent without
  `submit_review_verdict` and every local review ending in "no terminal review
  verdict".
- An offline review (`mergecraft review`) that stops without a verdict is no
  longer told to commit and push a dirty working tree. The dirty-tree check now
  skips offline reviews even when no mode was selected, so the retry turn asks
  only for the missing verdict.
- OTLP spans now satisfy Datadog LLM Observability's GenAI checks.
  `mergecraft.agent.run` and `agent.attempt` carry
  `gen_ai.operation.name=invoke_agent`, the agent span splits its model slug into
  `gen_ai.provider.name` / `gen_ai.request.model`, OpenCode's `llm.call` carries
  `gen_ai.operation.name=chat`, and every exported span with the deprecated
  `gen_ai.system` also gets `gen_ai.provider.name`.
- A read-only review of a checkout with an in-tree virtualenv no longer fails its
  integrity check when Python writes bytecode mid-review: the checkout hash now
  skips `__pycache__` directories at any depth, as it already did `node_modules`.
  The rest of a virtualenv stays hashed.
- Reviews on PRs with many CI checks no longer stall and time out after listing
  check runs. `list_check_runs` now returns each run's id, name, status,
  conclusion, output title and `check_suite_id`, instead of GitHub's full
  check-run objects with their complete output text. One listing on a ~35-check
  PR had returned 184 KB to the reviewer, slowing every later turn to 90–120 s.
  Full check output is still available from `get_check_suite_logs`
- Reviewers no longer read whole functions through `git grep` context. When a
  `git grep` asks for more than 10 lines of context (`-A`/`-B`/`-C`, `-NUM`,
  `-W`, or an abbreviated long form such as `--after=60`, including inside a
  `(`…`)` expression), the `git` tool returns just the matching lines with their
  line numbers and a note to open the file with the read tool at that line.
  Options placed after the pattern are moved in front of it instead of failing
  with exit 128. A refused `sed`/`cat`/`head`/`tail`/`awk` call now names the
  read to use instead. In the same timed-out review, 102 `git` calls returned
  437 KB, mostly from `git grep -A 40..70`
- A workspace review no longer fails closed with "checkout integrity failure:
  tree changed during read-only review" when dependency prep creates nested
  `node_modules`. pnpm/yarn/npm lay down `apps/api/node_modules`,
  `packages/*/node_modules` and the like (and pnpm can drop `.pnpm-store`
  in-tree), all after the integrity baseline, so the hash now prunes those
  directory names at any depth instead of only at the checkout root. A nested
  `.git` metadata directory is pruned the same way.
- The reviewer's read-only `git` tool now refuses abbreviated spellings of the
  options it already blocks, plus a few that do the same harm. Git accepts any
  unique prefix of a long option, so `git grep --no-inde` went through as
  `--no-index` and `git cat-file --tex` ran a configured textconv filter. Which
  prefixes are unique depends on the git release: on the git 2.39 in the
  review image, `cat-file --filter` is short for `--filters`, while on git
  2.53 it is a different option. So every prefix of a blocked option is
  refused, apart from a short list of exact names checked on both releases.
  The
  tool also refuses `grep --untracked` / `--no-exclude-standard`, because they
  searched untracked and ignored files, including mergeCraft's own scratch
  (the askpass helper, OpenCode's `auth.json`) whenever the run temp dir is
  inside the checkout. It refuses `blame --contents` / `--ignore-revs-file`,
  which read a file the tool cannot confine; `cat-file --filters`, which runs a
  smudge filter; and `ls-remote --upload-pack` / `--exec`, which run a named
  command. These options are refused anywhere in the arguments, including after
  `--`, because git reads a `--` that follows `-e` as a pattern rather than
  the end of options (`git grep -e -- --untracked` still searched untracked
  files).
- Multi-reviewer rosters now dispatch secondary reviewers server-side when the
  primary harness never spawns them, fail closed with a clear error when a
  secondary cannot reach its provider, and always emit the `⏱ LLM review time`
  line (including a zero-second fallback when no LLM calls were timed).
- Exporting findings no longer crashes when a model supplies a slug-style
  `fingerprint`; non-hex values are normalized to a stable lowercase hex digest
  at write time.
- `submit_review_verdict` drops malformed draft findings instead of rejecting
  the whole terminal submission when one pre-recorded row is invalid.
- Checkout integrity hashing skips nested `node_modules`, `.pnpm-store`, run
  `evidence`, and OpenCode session dirs at any depth so harness scratch writes
  during read-only review no longer trigger exit 12.
- A review whose agent submits a verdict without calling `select_mode` now
  publishes the formal review with the run record. Before, the PR got only a
  short progress comment, with no tokens, cost, timing or findings, whenever the
  OpenCode Go rung answered and the Codex fallback did not run.
- The run record on the formal review shows the `Cost:` line. Cost was computed
  but only reached the step summary.
- A recorded review verdict that reaches no GitHub review now says why. The run
  publishes the verdict it recorded, and when it does not — the shadow protocol,
  a run that is not in a review mode, or a submission the post-run re-validation
  rejected (conflicting, stale-attempt, or semantically invalid) — the reason is
  recorded on the run's trajectory instead of returning silently. The row is
  stamped `failure_class: declined`, so the trajectory auditor does not report the
  skip as an `ignored-tool-error`. PR #1017's
  Codex rung recorded `request_changes`, published no review, and left nothing in
  the evidence packet to distinguish that from never having tried; only the
  failing `mergecraft-approval` check showed it.
- agentsec no longer reads a changed instruction or MCP manifest whose symlink
  resolves outside the repository root; the refusal is logged and reported as a
  named skip when it was the only candidate (#851).
- Numeric metadata such as `input_tokens=120` survives log redaction; credential
  named keys and long numeric runs still redact (#877).
- Trusted-tier catalog analyzers drop to the agent UID on the root backend, with
  their scratch tree and the baseline worktree handed to that UID first; an
  unlandable drop reports `unavailable` instead of running as root (#878).
- `run_checks` refuses to run an untrusted static gate without a sandbox context,
  whatever `shell` says, so the executor fails closed even if a caller does not
  (#887).

- A retired Codex subscription login ("refresh token was already used") is reported as
  `infra_error` with *reviewer credential expired - re-authenticate* and the commands
  that fix it, in the check summary and the run record, instead of an unexplained red
  check. There is no scheduled canary: probing the login refreshes it (#922).

- The carry-over workflow no longer falls back to the forgeable `github-actions[bot]`
  login for `MERGECRAFT_REVIEWER_BOT_LOGIN`; an unconfigured App yields an empty login (#913).

- `config tracing` lists the config files it read and agrees with `doctor` and
  `config explain` about `config.local.yaml` and a missing `MERGECRAFT_CONFIG`; the
  flag, environment and YAML precedence is unchanged (#919).

- A column-0 comment between items of a top-level sequence no longer leaves trailing
  items behind when the comment-preserving config writer replaces the key (#920).

- Commands Codex, Claude and OpenCode run natively are recorded on the trajectory with
  their exit status, so a failing command, a timeout and a later passing re-run are
  visible to the auditor; environment and transient failures carry a named class.
  Recording never fails a tool call and changes no review decision (#858).

- `tests/mcp/test_rpc.py` no longer leaves a fake package version cached for later
  tests (#1006).
## [0.1.0a3] — 2026-10-17

### Breaking — action required

- The built-in Nous Portal provider is gone: the `nous/...` catalog models,
  `mergecraft auth nous`, and the flat `NOUS_API_KEY` credential no longer
  exist, so a `nous/...` model now fails as an unregistered provider. **Fix:**
  register Nous (or any OpenAI-compatible endpoint) under `providers:` in
  `.mergecraft/config.yaml` with `url`, `harness: opencode` and an `envIndex`,
  and pass the key as `LLM_PROVIDER_<N>_API_KEY`. See
  [docs/authentication.md](docs/authentication.md).

- An invalid `trust.agentSandbox` value (for example `off`, a bare `false`, or a
  typo like `nevr`) now fails configuration validation instead of quietly
  becoming `dispatch`. **Fix:** set one of `never`, `merged-only`, `dispatch`, or
  `same-repo`; the four tiers still normalize whitespace and case.

- The `model_pin` action input no longer carries a default. Leaving it unset
  follows the repository's `modelPin` setting, and an explicit `disabled` now
  overrides a repository `modelPin: true`. **Fix:** leave `model_pin` unset to
  follow the repository, or set `enabled` / `disabled` explicitly; the previous
  `disabled` default meant an unset input could never override the repository.

- Settings the standalone runtime does not consume are accepted but now warn
  once when set to a non-default value: `gates.thermostat`, `tracing.redaction`,
  `stopScript`, `blastRadiusOverride`, `operatorPipeline`, and `autoMergeEnabled:
  true`. **Fix:** none required — the values still parse and round-trip; remove
  the key if the warning is unwanted.

- A malformed tracing environment variable or tracing Action input — the enable
  flag, the region, the content level, or the untrusted-content export — now
  fails configuration instead of being ignored. A typo such as `flase` used to
  drop the value and let a lower layer's more permissive one win; the run now
  fails closed as a configuration error naming the variable, and never prints
  its value. **Fix:** correct the spelling; `MERGECRAFT_TRACING_REGION` still
  accepts `us` and `eu`.

- The MCP server no longer mounts a webhook endpoint. **Fix:** none — a signed
  delivery was verified but processed nothing, and its replay window could never
  fire, so no review path consumed the route.

- Provider circuit-breaker, health, budget and routing-eval helpers that no
  review path called are removed. **Fix:** none — none of them was reachable
  from a review.

- Four context-retrieval modules no review path imported are removed. **Fix:**
  none — no review path imported them.

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not
  implemented instead of being accepted and ignored. **Fix:** use a `dispatch`
  mode that is implemented; `ensemble` and `shadow` are refused.

- The `sarif_upload` action input no longer declares a default, so an unset
  input reaches `.mergecraft/config.yaml`'s `analyzers.sarifUpload` as
  intended. **Fix:** set `sarif_upload` (or `analyzers.sarifUpload`) explicitly
  if you relied on the implicit `disabled`.

- Progress comments are recognised by the identity that published them, not by
  any bot. When neither the expected publisher nor a trusted self-review sticky
  id is available, the run creates a new progress comment — and with it a fresh
  ledger — rather than adopting a comment posted by the shared Actions bot.
  **Fix:** none required; pin the reviewer App (or the self-review workflow) if
  you want the existing sticky adopted.

- Enterprise audit events are no longer written to `.mergecraft/audit.jsonl`
  inside the workspace by default. **Fix:** set `MERGECRAFT_AUDIT_ROOT`, or read
  from the new default location.

- Every exit under `src/mergecraft/cli/` now routes through named constants and
  usage errors exit `2`. **Fix:** scripts that branched on exit code `1` for
  generic CLI failures must follow the new table — most former `1` paths now
  exit `30`; see [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md).

### Known limitations

- Evaluation in this release is structural replay only, not live detection, and
  no human-adjudicated, calibrated or benchmarked result ships in it.

Full long-form history, including the entries condensed or omitted here:
[docs/dev/changelog-archive.md](docs/dev/changelog-archive.md#010a3--long-form-entries).

### Added

- Code-measured LLM review generation time in every posted review record and CLI JSON/text output (`⏱ LLM review time: …`), including per-reviewer breakdown when multiple reviewers run (#983).

- `mergecraft agent assign-model` on the committed roster registers missing models, auto-wires harness providers into `mergecraft.yml`, and updates `with.model` for p0 assignments.

- Human golden-batch manifests declare their own batch id and case list, so a later batch can be reviewed without a code change; the first batch's nine case ids stay pinned as a frozen fixture.

- Behaviour-verification reports record which driver produced them — `cdp`, `stub`, or unset when not recorded — so a report says whether its page came from a real browser or the non-browser fallback.

- `docs/opencode.md` documents the integration: engine selection, commands, subagents, V2 MCP wiring, JEV scope, and Logfire tracing.

- `mergecraft verify-behavior` can reproduce a bug or check a running app and write a versioned report under `.mergecraft/artifacts/`.

- A versioned behaviour-verification report (`schema_version` 1.0.0) records what was observed, which criteria passed, and what blocked the run — without turning those results into code findings (#61)

- Reviews can ingest declared coverage receipts and report change-risk scores on the functions the PR actually touched, advisory by default (#714)

- Opt-in Jev / System One client (`jev.enabled`, default off) with cost accounting, a kill-switch, and GenAI spans; a missing TypeSafe key records a skip and does not fail the review (#728)

- Parallel shadow judge grades review findings and prose against their cited evidence without replacing the reviewer (#728)

- `mergecraft review --tracing-content` and Action `tracing-content` set the capture level without editing YAML

- Multiple reviewer-role bindings run on one PR; findings merge by path/body/line and produce exactly one verdict with strictest severity winning

- `mergecraft workflow sync` keeps `.github/workflows/mergecraft.yml` auth wiring aligned with roster models; unwired providers fail at CLI write time and at run start

- First `mergecraft provider auth` after `init` seeds `agents.reviewer` p0 so review works with no third command

- `docs/agent-roster.md` — operator guide for slots, named agents, local scope, multi-reviewer verdict rules, and the run-start trust snapshot

- `establish_review_scope` — evidence-backed second route into review scope when a materialized diff already describes the PR head

- Read-only git MCP verbs (`show-ref`, `for-each-ref`, `ls-remote`, `config --get`) and `checkout_pr` parameter aliases (`pr_number`, `issue_number`)

- Agent stream logs render human-readable lines instead of dumping raw provider NDJSON.

- `Finding.scope` (`change` | `run`, default `change`) and `FindingSource` `"trajectory"` so trajectory auditor rows are attributed as process evidence, not PR defects

- Job step summary (`GITHUB_STEP_SUMMARY`) written from `_publish` with outcome, pre-merge rows, and findings — capped at GitHub's 1 MiB with the header intact

- Evidence packet persisted to a workflow artifact on every review rung (`if: always`, 30-day retention) so the packet survives runner teardown

- `MERGECRAFT_ACTION_SHA` workflow variable — one pin definition shared by all three review rungs, with `make action-pin-check` enforcing staleness and rung parity (#532)

- Action image digest pin gate (`action-image-digest-check`) and halved `wait-for-ci` poll cadence (20s → 10s, #528)

- `mergecraft tracing logfire wire-workflow --region us|eu` writes `MERGECRAFT_TRACING_REGION` into the wired step's `env:`.

- `mergecraft provider disable <label>` clears a provider's credentials so GitHub CI stops using it, without hand-editing secrets or workflow YAML.

- `mergecraft provider enable <label>` names the authenticate half of that toggle; it delegates to the existing `provider auth` flow (#520)

- Offline public MCP tool-selection eval corpus under ``evals/mcp-public/`` with fixture prompts and deterministic scorer ``mergecraft.evals.mcp_public`` (no live LLM in ``make test``)

- `make action-pin-check` also measures the pin against the default branch's own tip, not just against the other branch's pin.

- `make action-pin-check` guards the self-review Action pin against drift.

- Open-PR finding ledger in the sticky progress comment — `mergecraft findings ledger --pr N` inspects inline, deferred, withdrawn, and unpublished fingerprints without filing GitHub issues

- Optional recall pass (`review.recallPass`, default off) dispatches `mergecraft-recall` after aggregation; novel findings always publish in the deferred lane

- Optional round-aware budgets (`review.roundBudgets`) scale token, cost, tool-call, and subagent ceilings by review round; defaults stay flat until opted in

- Lens execution recording on `ToolState`, review metadata, and merge-evidence packets; findings may carry optional `lens` attribution

- Collateral lists on `Critical` and `Major` findings name callers, tests, and other files that must move with the fix; inline comments render them under **Also update:**

- `make lint` checks that jobs calling local reusable workflows grant at least the permissions the callee declares, catching ``startup_failure`` permission mismatches at authoring time (#425)

- Consumer glossary (`docs/glossary.md`) — plain-language definitions for trust tier, typed findings, blast radius, and related landing-page terms; manifest row and `llms.txt` entry.

- Runnable CLI example trees under `examples/cli/` (local diff, branch range, patch file, and `--agent` JSONL) with `make cli-examples` / `cli-examples-check` and `docs/cli-examples.md` tour page

- Agent-loop reference workflow (`docs/agent-loop.md`) for `mergecraft review --agent` (#383)

- CLI and GitHub Action runs now enter one review engine over one immutable snapshot (#380)

- `mergecraft explain`, `ask`, and `replay` plus `run inspect` / `run diff` print output-only change, line Q&A, and stored-run views (#377)

- `mergecraft review --agent` negotiates protocol version against CLI JSON `schema_version` (both fields kept, aliased), reports retryable mismatches, and names token/cost/tool-call budgets (#379)

- `mergecraft review --agent` streams the first finding before the verdict; `--use-cache` and `--resume` reuse a local result cache; cancelling a review cleans up child processes (#378)

- `llms-full.txt` generated concatenation plus docs pin/link gate (`make llms-check`, folded into `make docs-check`).

- Added: generated CLI and Action reference pages (`docs/cli.md`, `docs/action-reference.md`) plus a docs manifest; `make docs-check` replaces landing-README table splices.

- Review specialists now report unique useful findings plus latency, cost, precision, and recall (#370)

- `.mergecraft/config.yaml` now carries a `schema_version`; unversioned files migrate on load, unknown versions fail closed, and deprecated keys warn before a breaking removal (#368)

- `mergecraft doctor --supply-chain` verifies lockfile reproducibility, bundled agent-CLI provenance, and analyzer version pins; every run manifest now records runtime and tool versions (#366)

- `mergecraft requirements inspect` and `explain` map ticket and local-spec text to requirement states without writing the reviewed tree; policy can require that evidence before a review passes (#352)

- `mergecraft describe` prints an output-only PR title, summary, walkthrough, risk, labels, TODOs, effort band, split advice, and similar-change notes (#351)

- `mergecraft capabilities` prints the review-only capability manifest (modes Review, IncrementalReview, Plan; identify / investigate / verify / explain / prioritize / suggest) (#350)

- Python 3.11 floor ADR (#343, option A): `docs/dev/python-version-floor.md` records parenthesize-now / binary-later.

- `osv-scanner` detect globs now include `uv.lock`, so repos using uv's lock file trigger vulnerability scanning without pip-audit (#309)

- docs: `flake8` and `pylint` catalog entries note they are legacy opt-in; enabled via config override only (#309)

- Catalog manifests for `knip` (JS/TS unused exports/dependencies, `scope: repo`, `category: quality`) and `vulture` (Python dead code, `scope: repo`, `category: quality`) (#337)

- `detekt` flipped to `default_enabled: auto`; activates on any `*.kt` or `*.kts` change, or when `detekt.yml` is detected — provides the default Kotlin lint path (#317)

- `sqlfluff` flipped to `default_enabled: auto`; activates on any `*.sql` change or `.sqlfluff` config presence — skips silently when no SQL dialect is declared (#319)

- `stylelint` flipped to `default_enabled: auto`; activates on any `*.css`/`*.scss` change or `stylelint.config.js`/`.stylelintrc.json` presence — provides the default CSS lint path (#320)

- `htmlhint` flipped to `default_enabled: auto`; activates on any `*.html` change or `.htmlhintrc` presence — provides the default HTML lint path (#321)

- `checkmake` flipped to `default_enabled: auto`; activates on any `Makefile`, `makefile`, or `*.mk` change — provides the default Make lint path (#325)

- `markdownlint` flipped to `default_enabled: auto`; activates on any `*.md` change or `.markdownlint.json`/`.markdownlint.yaml` presence — provides the default Markdown lint path (#326)

- `luacheck` flipped to `default_enabled: auto`; activates on any `*.lua` change or `.luacheckrc` presence — provides the default Lua lint path (#328)

- `fortitude` flipped to `default_enabled: auto`; activates on Fortran files (`*.f90`, `*.f95`, `*.`, `*.f03`, `*.f`, `*.for`) or `.fortitude.toml` — provides the default Fortran lint path (#329)

- `regal` flipped to `default_enabled: auto`; activates on any `*.rego` change — provides the default Rego/OPA policy lint path (#330)

- `psscriptanalyzer` flipped to `default_enabled: auto`, adds `*.psd1` detect glob, and sets `supports_fix: true` — provides the default PowerShell lint and auto-fix path (#331)

- `blinter` flipped to `default_enabled: auto`; activates on `*.bat`/`*.cmd` changes — provides the default Windows Batch lint path (#332)

- `smarty-lint` flipped to `default_enabled: auto`; `ANALYZERS.md` notes that `*.tpl` is ambiguous (Go templates, Terraform) — enable only when `.smarty-lint.json` confirms Smarty intent (#334)

- `ember-template-lint` flipped to `default_enabled: auto`, sets `supports_fix: true`; gates on `ember-cli-build.js` or `ember-source` in `package.json` — bare `*.hbs` files do not trigger it (#335)

- `phpcs` and `phpmd` remain `default_enabled: false`; catalog entries note they are legacy opt-in — `phpstan` (auto) is the default PHP signal (#316)

- `brakeman` flipped to `default_enabled: auto` with tight Rails detection — only activates on Rails marker files (`config/application.rb`, `config/routes.rb`), never on plain Ruby repos (#313)

- New catalog manifest for `bundler-audit` (Ruby gem vulnerability audit, `category: vuln`, `scope: repo`, detects on `Gemfile.lock`) (#313)

- `scripts/check_type_ignores.py` fails when a `type: ignore` or `cast(` in allowed `src/mergecraft/` lacks a one-line reason (#275); wired into `make lint`

- `scripts/check_xpass.py` fails when unexpected pytest xpasses remain on the allowed test tree (#276)

- xpass ratchet now runs as a `pytest_sessionfinish` conftest hook inside the coverage-gate pytest session — no standalone log file or extra CI step (#276)

- docs: README requirements and `docs/distribution.md` Marketplace copy state that mergeCraft 0.1.0 is GitHub-only; GitLab support is planned via the `ScmProvider` abstraction (#279)

- Added: a test-only provider-harness fixture schema and strict matcher (`tests/support/provider_harness`) so deterministic review tests can name the exact provider interaction they expect.

- Added: provider-harness recording workflow and operator docs (`docs/dev/provider-harness.md`); opt-in sanitized capture under.

- Repository context engine indexes per-file symbols (tree-sitter with generic fallback), provenance citations, and trust-gated instruction/skill discovery under `mergecraft.context`

- Call graph, change graph (changed symbol → dependents → tests → contracts), and `mergecraft context inspect` for provenance-backed context retrieval

- `mergecraft policy lint|test|explain` — validate policy rules, run should-trigger/should-not fixtures, and list effective rules with source layers

- Per-run budgets, bounded external-operation timeouts, and honest large-diff degradation (`RunBounds`, scope reduction reports, downgraded outcomes) for offline and Action reviews

- precision corpus gate (`evaluate_dg1_precision_corpus`) replays the corpus and compares confirmed precision against the pre-DG1 baseline

- `mergecraft mcp serve` and `mergecraft mcp list` expose the reviewer's MCP tool surface to external clients without widening trust tier or tool-class policy

- Named review profiles (`--profile fast|deep|security`) bundle model chain, analyzer focus, and run budgets; explicit CLI flags still win

- `mergecraft cache info|clear|prune` inspect and maintain the byte-bounded on-disk run cache

- `mergecraft doctor` diagnoses git, provider credentials, analyzer detection, auth, config, and MCP port availability without printing secrets

- `mergecraft config show|explain|validate` generalizes precedence inspection beyond tracing; local private-repo reviews ship no remote telemetry by default

- `mergecraft plan` previews model chain, toolset, analyzer detection, and token estimate without provider calls

- Run manifest fingerprints (model/CLI versions plus prompt, config, and policy hashes) for reproducible offline reviews

- `mergecraft review` machine contract: distinct process exit codes per `RunOutcome`, `--format text|json|jsonl|sarif`, and `--agent` JSONL streaming with an explicit `protocol_version`

- Added tracer baseline attributes (`mergecraft.run_id`, `mergecraft.version`, `mergecraft.trust_tier`, VCS and CI fields) merged into spans at close time, with explicit attributes taking precedence

- Added review-context env propagation into spawned agent CLI subprocesses, so subagent runs join the parent review's trace identity

- Added richer tool-call tracing: `gen_ai.tool.call.id` correlating request and response, per-call duration, and an MCP-vs-native origin distinction

- Added `mergecraft eval gate` — a release regression gate comparing a candidate result set against baseline with a declared tolerance band, wired as a blocking job in the release workflow

- Added agent registry binding model, prompt, toolset and budget per role with `mergecraft agents list|show|set` and `make agents-check`

- Added registry-driven harness render for Claude, OpenCode, Codex, Gemini, and Cursor with per-agent models and declared Codex degradation in run metadata

- Added typed specialist handoff and model-diversity policy for verification.

- Added change classifier and risk-based lens routing with recorded per-lens reasons in Review mode

- Promoted 20 themed review lenses from Review prose into registry entries with `mergecraft lens list|show|test`

- Added pluggable orchestrator with declarative pipeline file, trust gate for untrusted sources, and `mergecraft pipeline lint|show|explain`

- Added declared decision nodes for hybrid orchestration — typed triviality, lens selection, and finding disposition seams with pipeline-owned control flow

- Added: optional `harness` setting (`opencode` / `codex` / `claude` / `gemini` / `cursor`) to select the agent runtime independently of provider/model.

- Added: terminal-verdict protocol shadow mode (`gates.terminal_verdict`, default `shadow`) with a closed `VerdictDiagnostic` vocabulary; enforce still applies the fail-closed missing-verdict branch

- Added: `submit_review_verdict` — a typed MCP operation that records a review's terminal verdict (`approve` / `request_changes`), summary and structured findings.

- Published Python distributions are installed outside the checkout and carry build provenance before upload

- `pre-commit` blocks newly added large files and private keys, and scans staged changes for secrets with `gitleaks`

- `make test-durations` refreshes the committed `.test_durations` that least-duration sharding balances by

### Changed

- Agent entries with `dispatch: ensemble` or `shadow` are refused as not implemented instead of being accepted and ignored.

- `mergecraft policy` help and enforcement docs state that a review run does not enforce policy rules.

- Recorded Jev transports and the canary assertion moved out of the runtime package into the test suite.

- A prepared release branch keeps `server.json`'s advertised package version in step with `pyproject.toml`, so the branch no longer fails its own `mcp-server-json-check` drift gate.

- The local `.env` file and the tracing environment layer are read through one typed model each, so a variable's exact name and type live in one place and a new environment read has a defined home.

- The Gemini and Codex harness deny lists name the `push_branch` tool the way each CLI documents it, matching the spelling the other harnesses already used.

- Finding matching against a baseline maximises the number of matched issues, so recall no longer changes when baseline issues are reordered; the scorer version is now `1.1.0`.

- `mergecraft verify-behavior` now drives a real Chrome over the DevTools Protocol and scores each acceptance criterion and reproduction claim through Jev, instead of refusing every run.

- `mergecraft jev enable|disable|status|set` configures the Jev advisory screening gate.

- Order-dependent test coupling now surfaces on a scheduled, non-blocking unit-suite run whose seed is the per-run `github.run_id`, so a pinned seed no longer hides it.

- Bare CLI command names open a TTY interactive session.

- A second gate policy (prompt 2.0.0) records through the existing recorder.

- Production false positives and human dismissals can be ingested into the eval bank as versioned cases, each carrying explicit provenance.

- Consumer setup guidance now lists every file produced by `mergecraft init` that may be committed: the config, learnings file, workflow, and added `.gitignore` lines.

- CLI `--json` payloads carry their own schema version, decoupled from the review snapshot's. Both stay `1.0.0`, so no payload changes; the two can now be bumped independently (#777).

- `mergecraft jev enable` now requests `TYPESAFE_API_KEY` when it is not already set and writes it to `.env`.

- Review records, sticky progress comments, and the Actions step summary now show input and output token counts separately instead of one combined total (#801)

- `make test` no longer runs the nine branch-walking `test_cov_*` suites: they carry a new `coverage` marker and the `make test` selector is now `-m "not integration and not coverage"`.

- The coverage/mutation CI gate's `enforce` mode is now exercised under test — both `shadow` and `enforce`, asserting the gate action and `reaches`.

- The action-pin bump workflow no longer advertises a push it cannot perform.

- PR #742 drops Playwright as the behaviour-verification driver.

- `mergecraft verify-behavior` fails closed when the browser-use stack is unavailable, even with `--artifacts-dir` / `--input`; `--allow-stub` is the only stub opt-in (#61, #752)

- `verify_behavior.enabled: false` skips the run (kill switch); default remains enabled so invoking the CLI still runs on a trusted checkout (#61)

- `verify_candidate` verifies the commit that introduced an image digest rather than whichever commit the candidate range happens to end at.

- `trust.agentSandbox` ladder (`never` / `merged-only` / `dispatch` / `same-repo`) with `mergecraft trust show` and `mergecraft trust set-agent-sandbox` (#553)

- `docs/trust-policy.md` documents the sandbox override ladder, fork floor, and residual risks

- Action `logfire-token` exports to `MERGECRAFT_LOGFIRE_TOKEN` before the Logfire sink initialises (#551)

- Actions-visible warning when tracing targets Logfire but no token resolves (#551) #### Fixed

- Self-review on PRs that edit `.mergecraft/config.yaml` publishes again after the publication guard re-baselines the config hash post-`checkout_pr` (#584)

- Nous and custom gateway providers are detected when only `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` is set (#552)

- Bubblewrap namespace failures surface once as a non-blocking run observation instead of inflating the packet gate with repeated Major findings (#553)

- Entropy redaction no longer strips proven benign analyzer shapes — sweep evidence at `docs/dev/15-w6-entropy-sweep-report.json` (#537) #### Changed

- #553 boundary amended from the `pull_request_target` event to fork heads — same-repo `pull_request_target` may grant the override at `same-repo` tier

- Claude backstop no longer runs when an earlier rung succeeds or posts a verdict including `neutral` — only retryable rung failures without a verdict trigger Claude (#600) #### Changed

- Same-repo `pull_request_target` self-review runs trusted-tier analyzers when `trust.selfReview` is `analyzers` — execution trust without widening approval authority

- Declared CI SARIF artifacts are downloaded and recorded when `wait-for-ci` reaches `state=complete` (green or red).

- Action log phases (setup, model chain, agent dispatch, publish) emit collapsible `::group::` blocks in GitHub Actions logs #### Added

- Dogfood config sets `trust.agentSandbox: same-repo` so Codex `danger-full-access` is honoured on same-repo review runs (#553)

- CI SARIF ingest covers actionlint, zizmor, semgrep, and trufflehog alongside ruff, mypy, and bandit — matching `ci.yml` uploads and `ciEvidence.sarifArtifacts` (#464)

- TruffleHog CI evidence converts JSONL to SARIF so a clean scan uploads a valid empty-results document with tool metadata, not a blank file

- Hardened consumer template forwards wait-for-ci outputs and grants `actions: read` for ciEvidence SARIF ingest

- `evals/README.md` Harbor install pin is `v0.1.0a1`, and live detection is documented as `mergecraft review` (Harbor still calls the hidden `diff-review` alias)

- AGENTS.md and the consumer skill match the default workflow triggers

- The self-review Action pin on all three review rungs moves to `93a7897c`, pin 5 — GitHub Action Logfire honors `MERGECRAFT_TRACING_REGION` (#607)

- Self-review Codex fallback uses `openai/gpt-terra` (GPT 5.6 Terra) instead of `openai/gpt-codex`

- Dogfood `trust.selfReview` / `trust.agentSandbox` knobs apply after merge to the default branch — `pull_request_target` reads the base config snapshot, not the PR head

- `runBounds.tokenBudget` is the soft target; `tokenBudgetTolerance` (default `0.10`) sets the hard ceiling — set tolerance `0` to restore strict enforcement

- Run record and job step summary token lines name target, ceiling, over-target status, and per-phase attribution when phases are recorded

- Policy enforcement modes score a rule's blocking intent from the finding's gate-facing severity, so ``contributes_blocker`` is read off it rather than computed beside it.

- Render path: skip short-id assignment for non-hex fingerprints instead of aborting review output; export and explain paths stay strict (#493)

- Cheat-signature lint: narrow ``getattr_tautology`` to ``object`` targets so legitimate missing-attribute fallback asserts are not flagged; severity stays ``error`` (#501)

- Coverage ratchet: merge-base lookup failures and lowered-floor comparison failures are mutually exclusive, so honesty tests can assert which guard fired (#503)

- Coverage ratchet: document that the merge-base lowering guard is PR-only on ``push`` / ``workflow_dispatch``; absolute ``fail_under`` checks still run on all events (#506)

- Coverage ratchet: pin ``_default_base_branch`` resolution order (``GITHUB_BASE_REF`` → ``GITHUB_REF`` branch → ``pre-0.0.1``) without requiring a git remote (#507)

- **Breaking:** enterprise audit events are no longer written to ``.mergecraft/audit.jsonl`` inside the workspace by default; set ``MERGECRAFT_AUDIT_ROOT`` or read from the new default location

- Analyzer and trace redactors now emit the shared ``<redacted>`` placeholder from ``mergecraft.redaction_sentinel`` instead of the legacy ``[REDACTED]`` analyzer spelling

- Overflow agent findings now append to a server-written `### 🗂 Deferred findings` section with full finding text (non-blocking); analyzer overflow remains in `### 🔧 Mechanical findings`

- `review.verificationBudget` (default 24; `0` = no cap) caps verifier dispatches independently of `analyzers.inlineBudget`

- Harbor `MergecraftReviewAgent` resolves the default `uv tool install` ref lazily in `install` via `action_pin_minimal` instead of calling it at module import (#403)

- Landing README promoted from `readme_test.md` draft: agent-first layout, glossary links, auth table with recommended models, CLI how-it-works section, and `v0.1.0a1` Action pin (RV6)

- `mergecraft init` scaffolds a consumer-ready workflow (`alexhawat/mergeCraft@v0.1.0a1`, `pull_request` trigger, `models:` list) matching `examples/config.yaml` and Example 1 (RV6)

- ``probe_capabilities`` is ``lru_cache``-backed; ``reset_detection_cache`` clears the probe cache for xdist isolation

- ``detect_sandbox_method`` and ``network_namespace_available`` delegate to the cached capability probe with one unified privilege ladder

- Eval methodology: blocker precision is `None` (unpublished) when a run reports no blockers, and severity accuracy is `None` when there are no locality matches — never a vacuous 1.0

- Landing README redesigned as a REACH-style product page (outline B): problem/solution cards, architecture hero, numbered install, and jump-nav.

- `mergecraft review --help` now states that no flags are required and includes full example commands for local worktrees, GitHub branches, and present or past PRs

- Stale pytest `xfail(strict=False)` markers that were already passing are now real tests; remaining allowed-tree xfails are strict (#276)

- Changed: `gates.terminal_verdict` now defaults to `enforce`; missing terminal verdict reports `inconclusive`. Operators can still set `shadow`

- Changed: `create_pull_request_review` now records through the same validator as `submit_review_verdict`; GitHub posting is an internal publisher, not an agent tool

- The PR integration job runs keyless hermetic integration tests instead of passing on a check that a helper script exists, so a green run means tests executed

- An E2E live slice with no model configured reports `unavailable` in a warning and the step summary instead of a green `skipped`; a configured-but-broken slice still fails

- Live-provider tests report the HTTP status before parsing a response body, and never echo the credential or the request URL; the Nous leg posts the documented default model

- CodeQL results upload to code scanning on the events whose token can write `security-events`, and an analysis failure fails the job; fork and Dependabot pull requests analyse without uploading

- `make workflow-lint` no longer reports success on a host where it could not lint: it fails and says lint is unavailable

- `make docker-build` tags the image with a lowercase repository name, so the target can succeed

- Every runtime dependency is an exact pin, every third-party import in the package is declared, and the declarations nothing imports are gone

### Removed

- The MCP server no longer mounts a webhook endpoint; a signed delivery was verified but processed nothing, and its replay window could never fire.

- Provider circuit-breaker, health, budget and routing-eval helpers that no review path called are removed.

- Four context-retrieval modules no review path imported are removed.

- The unused `get-installation-token/main.py` script; the `get-installation-token` composite Action is unchanged

### Fixed

- The OpenCode harness hands its isolated `XDG_DATA_HOME` tree to the unprivileged agent user before `setpriv` drops privileges.

- An offline review called as a library without a findings file now asks the model for structured findings, as the CLI always does.

- A review whose agent calls `run_analyzers` on a host without a sandbox no longer fails closed with "checkout integrity failure: tree changed during read-only review".

- The Action images ship OpenCode 2.x (`@opencode/cli` 2.0.29) for every model routed through the OpenCode harness (Nous, OpenCode Zen and Go, MiniMax, TokenHub, custom providers).

- The hardened example workflow's approval gate now receives only the review verdict, not the whole evidence packet.

- The Codex reviewer now runs in the repository it reviews. An offline review started from another directory failed at once, because Codex refuses to run outside a git repository.

- The self-review passes each review step's evidence packet to later steps as a file.

- Both Action images replace the brace-expansion and undici copies bundled inside npm with their patched releases, pinned by checksum.

- A self-review re-run on a job token now picks up the earlier run's checkpoint and progress comment.

- `doctor`, `config show` / `config explain` and the config loader now agree on which files contribute.

- `doctor` fails before printing anything when its rendered output would contain a credential value, naming the environment key and never the value.

- Logfire workflow wiring accepts the lowercase `alexhawat/mergecraft@<ref>` spelling the docs print, while still refusing similarly-prefixed forks and an empty ref.

- `watch` and the review comment's run link honour `GITHUB_API_URL` / `GITHUB_SERVER_URL` for GitHub Enterprise hosts.

- The unused hosted-plan residue is gone: the two `AccountPlan` vocabularies, the context `plan` field and the `proxyModel` producers and consumers were removed, none of which had a reader.

- A Review run that records its verdict now publishes exactly one GitHub review from it, with the recorded findings as inline comments.

- An unknown or missing trust tier is treated as `untrusted` everywhere, including a tool context built without one.

- The recorded prompt version now reflects the rendered prompt the reviewer actually received, so two runs configured with different inline budgets record different versions.

- A configured inline budget of `0` is honoured everywhere: the offline analyzer pre-pass, the pipeline fallback and the rendered prompt now agree, instead of the pre-pass silently using the default.

- The review doctrine states the Python 3.11 install floor, and the `push` input, the compatibility matrix and the review checks describe review-only behaviour — no value grants commit or push.

- Documentation links and glossary anchors resolve on GitHub (the glossary's `{#id}` headings become real anchors), and the operator-facing `MERGECRAFT_*` knobs are documented in `docs/cli.md`.

- CI failures with no evidence of cause are now reported as **unattributed** — blocking, with `introduced_by_pr: unknown` — instead of being cleared as not-this-PR.

- `--allow-stub` permits the stub only when the browser stack is unavailable and logs why, instead of bypassing a reachable browser.

- Every agent CLI driver and the OpenCode server boot no longer hang when a child fills its stderr pipe.

- OpenCode server boot no longer blocks the event loop in a blocking `readline`.

- The Claude and Gemini reviewers can no longer write files, run shell tools or fetch the web.

- Tracing no longer clears a bound data-residency allowlist.

- The sticky progress comment keeps the finding ledger and the learnings delta across the final deterministic-record write, so a later run hydrates every prior record instead of losing it.

- Analyzer findings are attributed to the file that actually caused them again.

- GitHub App runs mint separate least-privilege API, Git, and cross-repository tokens. Cleanup attempts to revoke every internally minted token.

- Coverage gates use native line/branch metrics and accept only complete, fingerprinted shard sets. A single run trace covers setup through publication across Action, offline, and MCP execution.

- Evaluation records round-trip without dropping corpus data and write atomically after validation.

- The keyless shadow job is a fixture replay of two hard-coded packets. It does not read a live review and leaves #737 open.

- A live shadow row records the model on the packet (the slug that ran, else the configured reviewer). When the packet has no model, the row leaves it unset instead of claiming Claude.

- `mergecraft eval ingest --from-dismissals` turns recorded dismissal signals into structural eval cases. A dismissal is stored as `agent-seeded`, not as a human label (#738).

- Resetting the MCP shell sandbox cache tolerates a patched capability probe — it clears the probe cache only when a callable `cache_clear` is present — so test-isolation teardown no longer errors.

- `mergecraft verify-behavior` stays inert on a fork or `pull_request_target` Actions event instead of always skipping the trust gate (#61)

- `mergecraft review --verification-report` does not load a report on an untrusted checkout, including when a workflow treats the workspace as trusted (#61)

- Verify criteria are scored per criterion; reproduce matches page text to repro notes; `--start-command` retries navigate while the app comes up (#61)

- Local `--shell enabled` now refuses when no sandbox backend is available unless `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` is set; on macOS, `sandbox-exec` is the backend when present (#593)

- Tracked public markdown is linted for decision-ledger tokens, -dot citations, and pointers into gitignored plans; Priority 1 docs were rewritten to stand alone (#709)

- `trivy` on Apple Silicon provisions the native ARM64 build so the local coverage gate does not hang under Rosetta

- Action reviews no longer crash at startup with `infra_error` when loading the shared token cap (#741)

- Enabled Jev reviews now keep the shadow-judge record next to the evidence packet after the command finishes, so paid calibration rows are retrievable (#728)

- A TypeSafe connect, DNS, or timeout failure on the shadow judge records a skip and leaves the completed review successful (#728)

- `jev.model` accepts only the pinned `jev-1.13.0` id, so a configured newer version cannot run while audit rows still claim the pin (#728)

- The Action-pin staleness budget counts changes rather than landings.

- A stale self-review Action pin on `main` no longer fails every open pull request.

- The sticky run record lists Action pin (manifest C) next to baked image source (S) so pin-lag (pinning S deploys the previous digest) is visible without reading Action logs (#641)

- Consolidated integration CI retains Python 3.11 and 3.14 coverage after prerelease/main reconciliation; the coverage ratchet runs once on 3.14.

- Bring the GitLab review-support matrix correction from main to the prerelease branch.

- Local base-only reviews retain working-tree changes; remote comparisons deepen bounded shared history and fail explicitly rather than substitute endpoint diffs.

- Installed convergence evaluations include their recall corpus. Example drift checks run in disposable copies and no longer rewrite tracked outputs.

- Redaction preserves closing assignment brackets and ordinary source paths while retaining secret-pattern and high-entropy controls.

- Optional image live checks require an actual terminal review rather than CLI help.

- Self-review App tokens now refresh per provider attempt and revoke after the job.

- Action images use patched, checksum-pinned npm and GitHub CLI tooling and remove unused vulnerable pip bootstrap copies.

- Local review honors configured model chains, explicit/environment precedence, fallback restrictions, and cumulative budgets; a process without a terminal verdict is inconclusive (#592).

- Installed skills use a verified documentation commit containing every linked target and teach canonical, explicitly scoped provider authentication (#589).

- Analyzer isolation reports unsupported macOS accurately and warns when trusted execution lacks isolation.

- Credential broker stream failures now close the connection without inserting a second HTTP response, and client disconnects release upstream responses (#595)

- Brokered Codex runs preserve configured proxy bypass entries and always bypass proxies for the loopback broker, without changing parent proxy settings (#597)

- Removed an obsolete Codex broker auth branch that suppressed the API-key authentication diagnostic; subscription authentication is unchanged (#596)

- Release verification uses compatible GitHub CLI policy flags, validates deployment candidates automatically, and publishes canonical image tags only after signed staging digests verify.

- Release E2E now runs for reusable workflow callers, and image promotion requires verified signatures, source provenance, and SBOM attestations.

- Logfire `llm.call` rows now include the prompt mergeCraft sent and the model output, with a real duration instead of an empty ~2µs span

- Codex, Claude, and Gemini tool-use now shows up as `tool.call` children on the same Logfire trace as the review run

- Authentication quick start uses registry labels (`anthropic`, `openai`, `google`) instead of harness names that `provider auth` rejects (#590)

- GitHub Action Logfire tracing honors `MERGECRAFT_TRACING_REGION`, so an EU write token is no longer posted to the US ingest host (#607)

- Anchor-422 recovery no longer spins on an out-of-range comment index — it demotes all inline comments and posts once (#570)

- The published GitHub review body always matches the terminal submission; probe strings and split publication races no longer land a placeholder review (#572)

- Multi-reviewer findings carry server-stamped `raised_by` attribution on the published review; agents cannot supply the field via `submit_review_verdict` (#574)

- Token spend slightly over `runBounds.tokenBudget` warns and completes instead of failing at the cliff; crossing the hard ceiling still ends the run (#571)

- Base-branch coverage measurement reads that worktree's `.mergecraft/config.yaml` instead of the PR head's — a PR that adds a config key and its schema field no longer fails the base run (#573)

- A refused terminal verdict now reaches the deterministic run record by name.

- Git MCP containment: refuse `--no-index`, confine positional paths, deny credential paths (`.git/config`, askpass tree), and redact git failure text before it becomes a tool result

- Post-run retry loop classifies scope and policy refusals before resuming — deterministic refusals no longer spend a second provider turn

- Single Loguru writer with `enqueue=True` and explicit queue drain — runner logs no longer interleave mid-line from concurrent stdout/stderr writers

- Bubblewrap namespace failures surface `user_namespace_failure_hint` once per run (not gated behind a non-zero Codex exit code)

- `checkov` and `yamllint` catalog rows document linux-amd64 manifest-only provisioning instead of presenting as runtime failures

- Git config MCP: deny `config --list` and credential-bearing keys on `config --get-all` so brokered auth headers cannot leak through enumeration

- `get_commit_info` validates unified diff evidence before establishing review scope; successful `checkout_pr` records scope via `register_review_scope`

- Claude driver: pass ``--verbose`` alongside ``--print --output-format=stream-json``.

- Trajectory auditor classifies tool failures before counting them, so self-corrected schema slips, policy refusals, and environment faults no longer masquerade as ignored errors that block the PR

- Codex fallback routing reads `decision.verdict` from the in-process evidence packet instead of racing the check-runs API

- Pipeline predicate validation no longer rejects repository paths whose names contain substrings such as ``subprocess`` or ``import``; the closed regex is the sole control

- Pipeline severity predicates include ``Trivial`` and rank unknown severities below every taxonomy member instead of treating them as ``Minor``

- ``ReviewEngine.run`` clears the timeout callback on every invocation so a second run with ``on_timeout=None`` does not retain the first run's handler

- Required static checks block approval unless every row is explicitly ``passed`` or ``not_applicable``; ``unavailable``, ``error``, ``timeout``, and unknown statuses no longer satisfy the gate

- Review publication reads repo settings from the run-scope snapshot taken before untrusted execution instead of reloading ``.mergecraft/config.yaml`` from the mutable checkout

- Shipped ``operational_readiness`` policy pack rules now declare the required evidence keys ``enforcement: required`` consults before it treats the rule as satisfied

- Authenticated git operations against GitHub now work at all.

- `actions/checkout` no longer persists its token in the review workflow, the shipped hardened example, its template, or the dogfood artifact.

- ``prep`` lockfile selection prefers ``uv.lock`` over a stray ``requirements.txt``; ``should_run`` threads one ``cwd`` into ``run`` instead of reading ``Path.cwd`` twice

- The Action image now installs the `[tracing]` extra (`uv sync --frozen --no-dev --extra tracing`).

- `mergecraft.yml` now actually passes the tracing inputs it has supported since.

- ``redact_tool_payload`` caps UTF-8 byte length (not Python character count) and keeps a head slice plus a visible truncation marker instead of discarding the whole body

- ``redact_url`` preserves ``http`` vs ``https`` when redacting basic-auth userinfo

- ``tests/tracing/test_redaction_doctests.py`` executes ``mergecraft.tracing.redaction`` doctests

- Webhook signature verification encodes signature operands with UTF-8 surrogateescape before ``compare_digest``, so non-ASCII header bytes are rejected instead of raising ``TypeError``

- The MCP server no longer mounts a webhook endpoint: a signed delivery was verified but processed nothing

- `validate_http_url` rejects whitespace and control characters anywhere in a provider URL, not just at the ends.

- `mergecraft workflow` resolves a relative `--workflow` against `--cwd` on every subcommand.

- The consumer workflow file is replaced atomically by `mergecraft workflow`, matching the config writer. A crash mid-write used to leave it truncated

- `provider migrate` validates a migrated `NOUS_BASE_URL` through `validate_http_url` like every other URL entry point, instead of storing it unchecked

- `.mergecraft/config.yaml` is replaced atomically (temporary file plus rename, preserving permissions) by every CLI writer.

- `mergecraft workflow provider add --apply` writes the registry config only after the workflow file lands, and rolls the workflow back if that config write then fails.

- `mergecraft workflow provider add --url` on an already-registered provider now applies the validated endpoint to the row that is wired and persisted.

- Indexed registry credentials survive the legacy credential re-injection in `build_agent_env`.

- `list_check_runs` omits `check_runs` when the listing is truncated, instead of returning a partial catalog with `total_count`.

- Check-suite log fetch skips with a distinct unavailable payload when no GitHub client is bound, instead of looking like “no failed runs”

- Catalog-check rejects all-zero `sha256` provenance pins (placeholders that made `provision_managed_binary` treat a trailing-slash URL as a directory and fail with `Is a directory`).

- A transient Nous HTTP 404 (including a false billing/credits refusal) now fails over to the next model instead of stopping the run and reporting a missing `set_output` schema failure (#466)

- The approval gate now unions agent findings with analyzer findings, so an agent Critical or Major finding fails ``mergecraft-approval`` and the evidence packet's ``request_changes`` action.

- A clean mypy JSON typecheck no longer fails the SARIF convert step, so the mypy artifact still uploads for review evidence

- Evidence packet `decision.verdict` is a GitHub check conclusion (`success` / `failure` / `neutral`); schema version 1.9.0

- `mergecraft-approval` posts `neutral` when the evidence packet was not assembled, instead of omitting the check

- Custom provider slugs not in the operator registry now fail closed instead of silently routing to OpenCode; the built-in catalog allow-list was narrowed accordingly.

- Repo-native analyzers no longer fall back to an arbitrary PATH binary.

- An explicit `--model` now beats `MERGECRAFT_MODEL`.

- Offline reviews (`--base`/`--head`, `--diff`, `--cwd`) can record a terminal verdict.

- Retryability now has one decision path.

- Codex `error` and `turn.failed` events are no longer discarded.

- Provider quota exhaustion is now classified as retryable for failover.

- `opencode serve` output is now drained for the process lifetime.

- A provider timeout no longer kills the review.

- `mergecraft --version` reported `0.1.0` while the project was at `0.1.0a1`: the number was restated as a literal in `mergecraft/__init__.py` alongside `pyproject.toml` and the two drifted.

- `review --dry-run` skips the analyzer catalog while still materializing the diff and returning the review prompt (#401)

- `load_audit_events` skips malformed JSONL lines and non-dict payloads instead of raising (#398)

- `route_model` routes security specialist at `critical` risk to the same capable model as `high` instead of Haiku (#394)

- Checkout and packaged `defaults.yaml` copies drifted after README v2; `make pins-check` gates byte identity (#402, #414)

- Hermes generated skill package lists `GEMINI_API_KEY` and `NOUS_API_KEY` (not `GOOGLE_API_KEY`) in `required_environment_variables`, matching `docs/authentication.md` (#415)

- Coverage ratchet floor raised to 80% after new docs contract tests increased measured line coverage above the prior ceiling

- Transitive `h2` 4.4.0→4.4.1 in `uv.lock` for `pip-audit` (PYSEC-2026-3628)

- `mergecraft init` no longer emits `uses:./` in consumer repos — published Action ref instead (V8/)

- `mergecraft init` scaffold drops comment triggers and unsafe `github.event.comment.body` prompt wiring; defaults to `CLAUDE_CODE_OAUTH_TOKEN` (README Example 1 parity)

- Evidence image uploads, issue comments, and PR label tools work on review-only runs again

- Linked-repo contract breakage is included in ordinary PR checkout, not only `mergecraft xrepo explain`

- Linked-repo checkout reads only operator-granted siblings, and skips a sibling whose HEAD is not the pinned SHA

- Webhook signature verification fails closed without a configured secret

- Untrusted download and clone URLs are SSRF-checked, and binary downloads pin DNS to the validated addresses

- `bandit` now uses built-in `--format json` instead of the optional SARIF extra, so auto-enabled Python security coverage still runs on plain Bandit

- `bundler-audit` now runs the gem CLI (`bundler-audit check --format json`) instead of `bundle audit`, so Ruby lockfile audits actually execute

- `tflint` no longer passes changed `.tf` files as positional args (invalid since TFLint 0.47); it lints the working directory and the pipeline still scopes findings to the diff

- `bundler-audit`, `cargo-audit`, and `cargo-deny` findings no longer fake a line-1 GitHub anchor when the tool did not report a line; crate/gem coordinates stay in the message

- `clippy` now runs as `cargo clippy --message-format=json` (package/workspace) instead of passing PR paths as cargo args, so auto-enabled Clippy keeps rustc JSON findings

- A successful analyzer with empty stdout (for example a clean `tsc --noEmit`) is treated as passed instead of unavailable

- `tsc` project-level diagnostics without a file location (for example `error TS18003`) now surface as body-only findings instead of a silent pass

- `tsc` help text and other unmatched nonempty stdout now fail closed instead of counting as a clean pass

- Project-level `tsc` findings survive diff scoping when the PR only changes `.ts` / `.tsx` files

- `brakeman`: command changed from `-o brakeman.sarif` (writes to file) to `-o -` (stdout) so the SARIF output is captured by the adapter; `parser: sarif` is unchanged (Thermos Finding 1, #338)

- MCP HTTP server now issues a separate bearer token for the orchestrator ``/mcp`` route; reviewer/verifier harnesses keep ``ToolContext.mcp_auth_token`` for their role endpoints (#349)

- OpenCode HTTP ``llm.call`` usage attrs omit unset counters instead of zero-filling ``gen_ai.usage.*`` when the session response reports output tokens only (#297)

- `agents/claude`: `write_mcp_config` wrote a single MCP server entry pointing to `/mcp/reviewer` (derived from the orchestrator's `current_agent_id` at `_run` start).

- `mcp/git`: corrected `commit_changes` tool description — it performs a local commit only and does not push to the remote or produce a GitHub-verified commit (#259)

- `mcp/git`: `--namespace` is now refused outright rather than forwarded.

- Fixed eval corpus run directories splitting on slashes in model slugs (e.g. `openrouter/openai/gpt-5`) — run ids are sanitized to a single flat component (#219)

- Fixed live corpus reviews running in an empty scratch directory — the case's repo context is materialized before the review (#220)

- Benchmark result sets now record full version pins and a reproducibility digest, so same-commit runs are comparable (#140)

- Two ensemble models that both report no findings no longer escalate to a judge (#238)

- Reviews of Python repositories with `shell: disabled` no longer fail closed after a completed review just because dependency installation was skipped as a security policy

- Fixed: model-chain fallback now advances when the provider succeeds without a terminal verdict; a valid `request_changes` is a usable result and does not trigger fallback

- Fixed: explicit `harness:` now selects the runtime agent, not only span labels

- Fixed: a previously recorded `approve` is re-validated before GitHub publish, so a later confirmed blocker cannot ship an `APPROVE` review

- Fixed: body-only `create_pull_request_review` with `approved: false` no longer posts a GitHub `APPROVE`

- Fixed: `create_pull_request_review` now requires established review scope in Review modes, matching `submit_review_verdict`

- Fixed: terminal-verdict shadow mode now records a predicted outcome beside the legacy result on the live finalize path

- Fixed: a body-only COMMENT is no longer recorded as `request_changes`, and body-only `request_changes` is rejected unless it has real findings

- Fixed: publication must match the recorded terminal verdict and is re-validated before sending `APPROVE`

- Fixed: IncrementalReview `report_progress` no longer advances the model chain

- Fixed: Review completion via `create_pull_request_review` now records a terminal verdict, and IncrementalReview may complete via `report_progress` without mapping to `inconclusive`

- Fixed: verifier confirms persist outside replaceable analyzer run state, including agent-authored findings

- Fixed: a verifier `confirm` now persists the finding fingerprint so `approve` over a confirmed blocker is rejected on the live tool path, not only in unit tests that seed `verified_ids`

- Fixed: a stored `approve` is re-validated at finalize against current evidence, so a later failed required gate or verifier confirm cannot leave the run `passed`

- Fixed: a provider success without a usable terminal verdict now advances the model chain when fallback is allowed, instead of accepting the first process-successful result

- Fixed: a later `run_static_checks` call that matches no gates no longer wipes a prior failed row, so `approve` still fails closed

- Fixed: `approve` is now rejected on the live path when `run_static_checks` recorded a failed required gate; previously the validator only saw those rows in unit tests

- Fixed: a review run that completes without submitting a terminal verdict now reports `inconclusive` (a `neutral` check conclusion) instead of `passed`.

- The checkout tool refuses a pull request number other than the one the run was bound to, and refuses a fork pull request on a run trusted for execution or authority.

- The `MERGECRAFT_DISABLE_SECURITY_INSTRUCTIONS` environment switch is removed; the security paragraph is always in the system prompt.

- Inside GitHub Actions the CLI no longer loads a `.env` from the checked-out workspace at startup; set `MERGECRAFT_ENV` to load an explicit file. Local (non-Actions) runs are unchanged.

- Linked-repo grants now match an exact lowercase `owner/name`; a bare name no longer authorizes a same-named repository, and two manifest entries sharing a name are both refused.

- Harbor's agent wrapper invokes `mergecraft review` instead of the deprecated `diff-review` alias.

- The sandbox write/network test and the symlink-target chown test run in the privileged lanes built for them, and fail rather than skip inside those lanes

- The keyless provider-catalog smoke no longer hides behind a live gate and runs in the unit suite

- Both in-image test scripts pin the same `pytest` and `pytest-asyncio` as the project they test

### Security

- The Claude reviewer can no longer read the run's credential material.

- The review job declares `actions: read`, and no review rung falls back to the shared `github-actions[bot]` login when no reviewer App is configured.

- Untrusted static checks run inside the sandbox against a disposable copy-on-write view of the checkout.

- Local log sinks are scanned for credentials after the run.

- Transitive `soupsieve` 2.8.4→2.9.2 in `uv.lock` for `pip-audit` (CVE-2026-85999, CVE-2026-86000) (#728)

- Fork-controlled `.mergecraft/config.yaml` can no longer lift the untrusted tracing-content cap; export of prompt bodies on fork PRs requires the Action input, env, or trusted base settings

- MCP HTTP startup no longer treats a TCP connect probe as proof of identity; server-thread failures propagate and ``GET /health`` requires a per-run nonce

- Analyzer JSON and JSONL outputs are structurally redacted by key and value before persist, so non-prefixed secrets in trufflehog-style payloads do not reach prompts or ``.mergecraft/analyzer-runs/``

- Entropy-based secret redaction uses a length-relative threshold with benign-shape exclusions for git SHAs, hex runs, and identifiers so legitimate code tokens in logs are not mangled unnecessarily

- OpenCode review sessions deny ``webfetch``, ``external_directory``, and ``edit``; ``read`` is allowlisted to the checkout and evidence scratch instead of ``*``

- Post-run checkout integrity verification via ``security.review_integrity`` hashes the tree before review and fails closed on mutation

- ``setpriv`` argv carries ``--no-new-privs``, ``--inh-caps=-all``, and ``--bounding-set=-all``; fails closed when ``setpriv`` lacks ``--bounding-set`` support

- Root-side ``git`` subprocesses route through ``utils/git_hardening.git_argv`` with pinned safe-config keys; ``make lint`` enforces the route via ``scripts/check_git_argv.py``

- ``prepare_workspace_for_agent`` no longer recursively chowns ``.git``; sandbox shell binds every registered workspace root's ``.git`` read-only

- Linked-repo ``_rev_parse_commit`` rejects leading-dash revs, validates pinned SHA shape, and passes ``--end-of-options`` before the rev

- Sandbox capability probes run real isolation checks instead of gating on ``CI``; untrusted MCP shell refuses unsandboxed spawn unless ``MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1``

- Skipped untrusted analyzers emit a ``Minor`` finding (``rule_id: analyzers.sandbox-unavailable``) naming missing isolation primitives

- ``sudo-unshare`` shell spawn passes env by name via ``--preserve-env`` with ``env=env`` on ``Popen`` so provider keys never appear in argv

- Namespaced shell spawn hides every ``git`` binary and binds ``.git`` read-only inside ``unshare`` / ``sudo-unshare`` branches; unsandboxed opt-in runs the raw command without host mount soup

- Python ``prep`` installs into ``.mergecraft/prep-scratch/prep-venv`` with a default-deny env allowlist so PR build deps cannot mutate the reviewer's interpreter or inherit provider credentials

- Mutating MCP tools other than review-session verbs (`select_mode`, checkout, review publication) are refused unless a write-capable mode is selected, including before mode selection (#350)

- GitLab webhook `X-Gitlab-Token` is compared as a shared secret, not an HMAC of the body (#361)

- External URL retrieval also blocks decimal, hex, and short IPv4 forms, IPv6-mapped loopback, and DNS that resolves to loopback, link-local, or metadata; DNS failure is fail-closed (#362)

- Dependency and container-image vulnerability gates no longer report a pass without running a scanner (#362)

- Untrusted PR trees no longer receive a `shell` tool when PID-namespace isolation is unavailable (#287)

- Untrusted PR trees no longer run package install lifecycle scripts in the Action process when `shell` is the default `restricted` (#284)

- `mcp/git`: the glued single-token spelling (`-ckey=value`) is refused alongside the spaced and inline forms, so the alias-execution block no longer depends on how the flag was written.

- `mcp/git`: `git diff --output=<path>` wrote an arbitrary file through a read-only tool — the subcommand allowlist constrains the verb, not the flags the verb accepts.

- `mcp/git`: `-C`, `--git-dir`, and `--work-tree` are now confined to the resolved primary repo root; any path outside raises `ValueError` with the offending path in the message (#257)

- Linked-repo reads are grant-gated: a run can only load repos declared in its authorized set; linked-repo and ticket text render through the fence as untrusted data

- CLI offline reviews now derive a trust tier from review-source provenance; cloned or out-of-root paths review at untrusted tier unless the operator passes an explicit `--trust` override

- Executable repo config (`setupScript`, `prepushScript`, `stopScript`, `staticChecks[].command`) from an untrusted review source is ignored; declarative config still applies

- `build_mcp_app_for_role` with `role="reviewer"` or `role="verifier"` no longer mounts the orchestrator toolset at `/mcp`; only the role-specific path is active (#282)

- The changelog-preview workflow passes no repository secrets to the third-party reusable workflow it calls

- Cleanup and token-revocation failures are logged as warnings naming the step and path — including a residual askpass file — instead of being suppressed.

## [0.1.0] — 2026-08-14

> **Never published.** `0.1.0` was never tagged, has no GitHub release and no
> package upload; its entries are kept here as history. The version above,
> `0.1.0a3`, is the pre-release cut in its place. `0.1.0a1` (`521c0aed`) was an
> Action-only tag — no PyPI upload and no GitHub release; `0.1.0a2` was skipped.
> A consumer upgrading from `v0.1.0a1` should read the **Breaking — action
> required** block above.

Planned initial public release (never published): mergeCraft is a standalone,
BYOK GitHub Action for AI-powered PR review — no proprietary backend, no
account, review runs against your own Claude/Codex/Gemini subscription or API
key.

Full pre-release development history: see
[`docs/dev/changelog-archive.md`](docs/dev/changelog-archive.md).

### Added

- Multi-agent review drivers for Claude Code, Codex, Gemini CLI, Cursor
  Cloud, and OpenCode, each resolving from a subscription login or an API
  key with no proprietary backend in between
- Curated multi-provider catalog (Nous Research/DeepSeek, Tencent TokenHub,
  MiniMax) plus a generic custom OpenAI-compatible gateway, configurable via
  `.mergecraft/config.yaml` or `with:` inputs
- Ordered model chain with automatic fallback: entries missing credentials
  are skipped and retryable provider failures advance to the next entry
- Analyzer catalog covering linters and type-checkers (Ruff, MyPy, Pyright,
  ESLint, Biome, Oxlint), dependency and secret scanning (OSV-Scanner,
  Trivy, TruffleHog), pattern scanning (Semgrep/OpenGrep/ast-grep), contract
  diffing (oasdiff, Squawk, buf), GitHub-native tools (actionlint, zizmor,
  ShellCheck, Hadolint), and a first-party scanner for MCP/skill manifests;
  selection is trust-tier aware (`analyzers: off|auto|full|untrusted-only`)
- Merge Evidence Packet: every run emits a versioned, structured record of
  findings, analyzer checks, the blast-radius lane, and the structural
  decision, exposed as the Action's `evidence_packet` output
- Blast-radius classifier maps changed paths to low/medium/high merge
  lanes, with additive per-category repo overrides
- Structural `mergecraft-approval` status check — a pure function of typed
  findings, run completion, and trust tier, so a crashed or timed-out run
  reports `neutral` rather than silently passing
- Eight trajectory checks read the agent's own mediated tool calls (a file
  edited but never read, a tool error retried with nothing changed, and six
  more) and feed the evidence packet
- File-backed eval bank (`mergecraft eval add|list|replay|promote`) turns
  real review outcomes into regression cases and permanent pytest tests
- Optional tracing: a local JSONL sink plus Logfire/OTLP remote export, a
  full per-run span tree, and a redaction boundary that scrubs secrets
  before any sink sees them (`mergecraft tracing`, `mergecraft auth logfire`)
- `mergecraft findings export|carryover` files GitHub issues for review
  findings a merged PR left unresolved, so they survive past the merge
- Optional GitHub code-scanning upload (SARIF) for analyzer findings
  (`sarif_upload: enabled`)
- Per-run nonce fencing neutralizes prompt-injection attempts in untrusted
  PR titles, bodies, and comments before they reach the reviewing agent
- Comment-triggered runs (`@mergecraft`) are gated on the commenter's GitHub
  author association by default, extendable via `commentInvocationAllowlist`
- CI pipeline intelligence clusters failures, distinguishes flaky and
  pre-existing failures from ones the PR introduced, and blames failures to
  the hunks that caused them
- `mergecraft models|analyzers|eval|tracing|learnings|auth` CLI command
  groups; README's Action-input, Action-output, and CLI reference tables are
  generated from the live sources and CI-gated against drift
- Hardened example workflow
  (`examples/workflows/mergecraft-hardened.yml`) with a same-repo secret
  guard, wait-for-CI, and approval-check enforcement
- Release pipeline builds each image once, attaches SBOM and vulnerability
  scan reports, cosign-signs and attests the digests, then promotes tags by
  digest — no second rebuild between scan and release

### Changed

- Typed `ProviderConfig` for OpenAI-compatible gateways (capabilities declarative; API keys stay in env vars). No wire-format change to generated `opencode.json`
- **BREAKING** — `with: model:` is now the head of the effective model
  chain rather than a replacement for it; set `model_pin: enabled` (or
  `modelPin: true`) to restore the old single-model behavior
- **BREAKING** — comment-driven invocation under `pull_request_target` is
  refused by default; opt in with `allow_pr_target_comments: true`
- **BREAKING** — new learning entries land in a quarantined staging section
  by default instead of taking effect immediately; set
  `autopromoteLearnings: true` to restore auto-promotion
- **BREAKING** — an unrecognized `analyzers:` input value now resolves to
  the strictest tier (`untrusted-only`) instead of the most permissive
  (`auto`)

### Security

- Agent privilege drop fails closed: a run that cannot drop root aborts
  instead of continuing to execute the reviewing agent as root
- Trust tier is derived before any repo-controlled script or git setup
  runs, and an unrecognized event shape fails closed to `untrusted`
- Agent CLI subprocesses receive an explicit credential allowlist — no
  ambient GitHub tokens or inactive provider keys reach the process
- A first-party analyzer (`agentsec`) scans `.mcp.json`, `CLAUDE.md`,
  `AGENTS.md`, and skill files for policy violations, and still runs under
  `shell: disabled`
