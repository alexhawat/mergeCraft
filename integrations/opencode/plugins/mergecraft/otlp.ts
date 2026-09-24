/**
 * Pure OTLP/Logfire helpers for the mergeCraft OpenCode plugin.
 *
 * This module has no OpenCode or Node imports so it can be unit-tested directly
 * (`node --experimental-strip-types`). `index.ts` owns the plugin wiring.
 */

export interface LogfireTarget {
  url: string
  token: string
  project?: string
}

const REGION_HOSTS: Readonly<Record<string, string>> = {
  eu: "logfire-eu.pydantic.dev",
  us: "logfire-us.pydantic.dev",
}

const DEFAULT_REGION = "us"

/**
 * Resolve the Logfire OTLP endpoint and write token. Returns null when no token
 * is configured. Mirrors `src/mergecraft/tracing/exporters.py`: the write token
 * is the Bearer credential, Logfire derives the project from it, and no
 * `x-logfire-project` header is sent.
 */
export function logfireTarget(env: Record<string, string | undefined>): LogfireTarget | null {
  const token = env.MERGECRAFT_LOGFIRE_TOKEN ?? env.LOGFIRE_TOKEN
  if (!token || token.trim() === "") return null
  const region = (env.MERGECRAFT_TRACING_REGION ?? DEFAULT_REGION).toLowerCase()
  const host = REGION_HOSTS[region] ?? REGION_HOSTS[DEFAULT_REGION]
  const project = env.MERGECRAFT_TRACING_PROJECT
  return project ? { url: `https://${host}/v1/traces`, token, project } : { url: `https://${host}/v1/traces`, token }
}

/**
 * Random hex of `bytes` bytes. OpenTelemetry requires non-zero trace and span
 * ids, so an all-zero draw is corrected by setting the final byte.
 */
export function randomHex(bytes: number): string {
  const list = new Uint8Array(bytes)
  globalThis.crypto.getRandomValues(list)
  let nonZero = false
  for (const byte of list) {
    if (byte !== 0) {
      nonZero = true
      break
    }
  }
  if (!nonZero) list[list.length - 1] = 1
  return Array.from(list, (byte) => byte.toString(16).padStart(2, "0")).join("")
}

export interface OtlpSpanInput {
  name: string
  attributes: Record<string, string | number>
  traceId: string
  spanId: string
  nowMs: number
  project?: string
  serviceName?: string
}

/** Build the OTLP/HTTP JSON body for one span. */
export function buildOtlpPayload(input: OtlpSpanInput): unknown {
  const timestamp = String(input.nowMs * 1_000_000)
  const resourceAttributes: Array<Record<string, unknown>> = [
    { key: "service.name", value: { stringValue: input.serviceName ?? "mergecraft-opencode" } },
  ]
  if (input.project) {
    resourceAttributes.push({ key: "deployment.environment", value: { stringValue: input.project } })
  }
  return {
    resourceSpans: [
      {
        resource: { attributes: resourceAttributes },
        scopeSpans: [
          {
            scope: { name: "mergecraft.opencode", version: "1" },
            spans: [
              {
                traceId: input.traceId,
                spanId: input.spanId,
                name: input.name,
                kind: 1,
                startTimeUnixNano: timestamp,
                endTimeUnixNano: timestamp,
                attributes: Object.entries(input.attributes).map(([key, value]) =>
                  typeof value === "number"
                    ? { key, value: { intValue: String(value) } }
                    : { key, value: { stringValue: value } },
                ),
              },
            ],
          },
        ],
      },
    ],
  }
}
