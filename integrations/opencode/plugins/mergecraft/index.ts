/**
 * mergeCraft for OpenCode — plugin entrypoint.
 *
 * Targets the OpenCode V2 plugin API (`Plugin.define` + `setup(ctx)`) on the
 * `@opencode/plugin` 2.x contract. Everything here is defensive: a missing
 * or renamed domain method is logged and skipped rather than breaking the host.
 *
 * Responsibilities:
 *   - register the public mergecraft MCP server (`ctx.mcp.transform`)
 *   - optionally override /mergecraft/review with a non-native engine
 *   - redact credentials from prompts before admission
 *   - keep the reviewer subagent read-only and on-doctrine
 *   - emit one Logfire span per native review when a write token is present
 *
 * It never commits, pushes, or edits on mergeCraft's behalf, and it never
 * weakens a configured `deny`.
 */

import { Plugin } from "@opencode/plugin"

import { buildOtlpPayload, logfireTarget, randomHex } from "./otlp"

export type Engine = "native" | "cli" | "deep" | "mcp" | "quick"

export interface MergecraftOptions {
  /** Default engine behind /mergecraft/review. Default: "native". */
  engine?: Engine
  /** Register the public MCP server automatically. Default: true. */
  mcp?: boolean
  /** Emit a Logfire span per native review when a token is present. Default: true. */
  logfire?: boolean
  /** Redact credential-shaped strings from prompts. Default: true. */
  redact?: boolean
  /** Reviewer subagent name. Default: "mergecraft/reviewer". */
  reviewerAgent?: string
}

const MCP_SERVER_NAME = "mergecraft"
const MCP_COMMAND = ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"]

const DEFAULT_REVIEWER_AGENT = "mergecraft/reviewer"

/** Credential-shaped substrings that must never reach a model prompt. */
const SECRET_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/gh[pousr]_[A-Za-z0-9]{20,}/g, "[redacted-github-token]"],
  [/github_pat_[A-Za-z0-9_]{20,}/g, "[redacted-github-pat]"],
  [/sk-[A-Za-z0-9_-]{20,}/g, "[redacted-api-key]"],
  [/pylf_v[0-9]+_[A-Za-z0-9_]+/g, "[redacted-logfire-token]"],
  [/AKIA[0-9A-Z]{16}/g, "[redacted-aws-key]"],
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, "[redacted-private-key]"],
]

const DOCTRINE = [
  "This is a mergeCraft review. Review-only: never edit, write, or patch files.",
  "No finding without an anchor (file:line, diff hunk, or tool output).",
  "Grade severity, category, and confidence; exactly one verdict at the end.",
  "Check .mergecraft/learnings.md for withdrawn findings and do not re-raise them.",
  "Read REVIEW-CHECKS.md when it exists; otherwise use the built-in rubric.",
].join("\n")

function redact(text: string): string {
  let out = text
  for (const [pattern, replacement] of SECRET_PATTERNS) {
    out = out.replace(pattern, replacement)
  }
  return out
}

/**
 * Emit one OTLP span to Logfire. Best-effort: failures are logged, never thrown.
 * Logfire accepts the write token as the Bearer credential and derives the
 * project from the token, so no x-logfire-project header is sent.
 */
async function emitLogfireSpan(name: string, attributes: Record<string, string | number>): Promise<void> {
  const target = logfireTarget(process.env)
  if (!target) return
  const payload = buildOtlpPayload({
    name,
    attributes,
    traceId: randomHex(16),
    spanId: randomHex(8),
    nowMs: Date.now(),
    project: target.project,
  })
  try {
    await fetch(target.url, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${target.token}` },
      body: JSON.stringify(payload),
    })
  } catch (error) {
    console.error("[mergecraft] Logfire export failed:", error)
  }
}

function engineInstruction(engine: Engine): string {
  switch (engine) {
    case "cli":
      return "Run `mergecraft review --agent` and parse the JSONL `finding` events before the `verdict` line."
    case "deep":
      return "Run `mergecraft review`, then `mergecraft findings export` and (when useful) `mergecraft evidence show <id>`."
    case "mcp":
      return "Call the mergecraft MCP tools: `review_change`, then `inspect_finding` / `explain_finding`."
    case "quick":
      return "Run only `mergecraft analyzers detect` and `mergecraft analyzers run <id>`; report this as analyzers-only."
    default:
      return "Review the current change directly and grade it; do not shell out to mergecraft."
  }
}

export default Plugin.define({
  id: "mergecraft",
  async setup(ctx) {
    const options = ((ctx.options ?? {}) as MergecraftOptions) ?? {}
    const reviewerAgent = options.reviewerAgent ?? DEFAULT_REVIEWER_AGENT
    const cleanups: Array<() => void | Promise<void>> = []

    const guard = async (label: string, fn: () => Promise<unknown>): Promise<void> => {
      try {
        await fn()
      } catch (error) {
        console.error(`[mergecraft] ${label} skipped:`, error)
      }
    }

    // Register the public MCP server so `mcp.servers.mergecraft` is not needed
    // in opencode.jsonc.
    if (options.mcp !== false) {
      await guard("mcp transform", async () => {
        await ctx.mcp.transform((editor) => {
          editor.set(MCP_SERVER_NAME, { type: "local", command: MCP_COMMAND } as never)
        })
      })
    }

    // Make the default /mergecraft/review engine configurable. The markdown
    // command stays native; a non-native option installs a programmatic
    // override with the same name.
    const engine = options.engine ?? "native"
    if (engine !== "native") {
      await guard("command transform", async () => {
        const registration = await ctx.command.transform((editor) => {
          editor.add({
            name: "mergecraft/review",
            description: `mergeCraft review (${engine} engine)`,
            execute: async ({ sessionID, prompt, delivery }) => {
              await ctx.session.prompt({
                ...prompt,
                sessionID,
                text: `Review the current change with the mergeCraft ${engine} engine.\n\n${engineInstruction(engine)}\n\n${prompt.text}`,
                delivery,
              })
            },
          })
        })
        cleanups.push(() => registration.dispose())
      })
    }

    // Redact credentials from prompts before they are admitted.
    if (options.redact !== false) {
      await guard("prompt hook", async () => {
        const registration = await ctx.session.hook("prompt", (event) => {
          event.prompt.text = redact(event.prompt.text)
        })
        cleanups.push(() => registration.dispose())
      })
    }

    // Keep the reviewer subagent read-only and on-doctrine, and override
    // generation settings for review calls only.
    await guard("context hook", async () => {
      const registration = await ctx.session.hook("context", (event) => {
        if (event.agent !== reviewerAgent) return
        event.system.push({ type: "text", text: DOCTRINE })
        delete event.tools.write
        delete event.tools.edit
        delete event.tools.patch
        event.options.temperature = 0.2
      })
      cleanups.push(() => registration.dispose())
    })

    // Defense in depth: the reviewer agent may not edit or shell out even if a
    // broader rule allowed it. A configured deny is final and never weakened.
    await guard("permission hook", async () => {
      const registration = await ctx.permission.hook("evaluate", (event) => {
        if (event.agent !== reviewerAgent) return
        if (event.action !== "edit" && event.action !== "shell") return
        event.effect = "deny"
        event.message = "mergecraft reviewer is read-only"
      })
      cleanups.push(() => registration.dispose())
    })

    // Give mergecraft commands a generous-but-bounded timeout and pass through
    // the mergeCraft environment the host already holds.
    await guard("shell hook", async () => {
      const registration = await ctx.shell.hook("create.before", (event) => {
        if (!/(^|\s)mergecraft(\s|$)/.test(event.command)) return
        if (event.timeout > 900_000) event.timeout = 900_000
      })
      cleanups.push(() => registration.dispose())
    })

    // Trace each native review to Logfire when a token is configured.
    if (options.logfire !== false) {
      await guard("tool hook", async () => {
        const started = new Map<string, number>()
        const before = await ctx.tool.hook("execute.before", (event) => {
          if (event.tool !== "subagent") return
          const input = (event.input ?? {}) as Record<string, unknown>
          const agent = typeof input.agent === "string" ? input.agent : ""
          if (!agent.includes(reviewerAgent)) return
          started.set(event.sessionID, Date.now())
        })
        cleanups.push(() => before.dispose())

        const after = await ctx.tool.hook("execute.after", (event) => {
          const start = started.get(event.sessionID)
          if (start === undefined) return
          started.delete(event.sessionID)
          void emitLogfireSpan("mergecraft.review.native", {
            "mergecraft.engine": "native",
            "mergecraft.agent": reviewerAgent,
            "mergecraft.duration_ms": Date.now() - start,
            "mergecraft.status": event.status,
          })
        })
        cleanups.push(() => after.dispose())
      })
    }

    return () => {
      for (const cleanup of cleanups) {
        void cleanup()
      }
    }
  },
})
