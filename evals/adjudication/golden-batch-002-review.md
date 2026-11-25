# Batch 002 review packet

Nine proposed findings, prepared as replacements for batch 001 under [#780](https://github.com/alexhawat/mergeCraft/issues/780) (closed as not planned on 2026-11-23). For each case, check whether the introducing change caused the described behavior at the cited lines. Reply with the case ID and `confirm`, `correct` with your edit, or `abstain`. You can also leave a case pending.

**Answered on 2026-11-25.** `alexhawat` confirmed all nine cases with no corrections. The decisions are recorded in the [manifest](golden-batch-002.json). The rest of this page is the packet as it was reviewed, so its cases still read “pending”.

| Case | Project | Proposed finding |
| --- | --- | --- |
| [B2-01](#b2-01) | Vite | Yarn PnP package lookup treats browser polyfills as builtins |
| [B2-02](#b2-02) | Vite | Package-name matching ignores explicit SSR external entry |
| [B2-03](#b2-03) | Vue | Required shallowReactive brand rejects plain object assignment |
| [B2-04](#b2-04) | Django | Casting exact admin search fields prevents use of ordinary database indexes |
| [B2-05](#b2-05) | Django | EmailMessage writes a caller-supplied To header twice |
| [B2-06](#b2-06) | Werkzeug | Cycle tracking crashes the debugger on unhashable exception instances |
| [B2-07](#b2-07) | GORM | FileWithLineNum reports an inner wrapper after caller extraction |
| [B2-08](#b2-08) | Spring Framework | Composite map key-set removal exposes a hidden duplicate key |
| [B2-09](#b2-09) | Tokio | Alternative timer reset registers with a different runtime |

## B2-01

**Yarn PnP package lookup treats browser polyfills as builtins** · correctness · pending

**When it happens**

In a Yarn Plug'n'Play project, resolve installed browser packages named buffer or string_decoder through Vite package metadata lookup.

**Proposed finding**

The new PnP resolution path calls resolveToUnqualified without considerBuiltins:false. The default treats names shared with Node builtins as builtin modules and returns no package location instead of resolving the installed browser-polyfill package; Vite then reports missing package metadata. The upstream fix explicitly disables builtin treatment in this package-only lookup.

[Inspect packages/vite/src/node/packages.ts lines 193–194 at the introducing commit](https://github.com/vitejs/vite/blob/1fc8c652c46a27f6229c9125e3b0d1662d2a0e67/packages/vite/src/node/packages.ts#L193-L194)

```typescript
  basedir: string,
  preserveSymlinks = false,
): string | undefined {
  if (pnp) {
    const pkg = pnp.resolveToUnqualified(pkgName, basedir)
    if (!pkg) return undefined
    return path.join(pkg, 'package.json')
  }

  let root = basedir
```

**Upstream evidence**

[Introducing PR #12441](https://github.com/vitejs/vite/pull/12441) merged 2023-03-21T06:42:23Z · [fix PR #12903](https://github.com/vitejs/vite/pull/12903) merged 2023-04-19T06:00:09Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `8d2931ba6d32fab6ca2831e2b293469236b67503` | `62ebe28d4023c1f67578b1977edd3371f44f475a` |
| Head | `ff02c9ace060ae9c9c654bc0ae1262597bb5c721` | `31d20aba7890cd6e5c48acb59cf47a2d90e2d7da` |
| Merge | `1fc8c652c46a27f6229c9125e3b0d1662d2a0e67` | `a0e10d5bc8b7ac6f27bd006a5cb65a56538fcede` |

Fix PR states: “Regression introduced by https://github.com/vitejs/vite/pull/12441”

**What the fix changed**

Pass { considerBuiltins: false } to pnp.resolveToUnqualified so installed packages sharing Node builtin names resolve as packages.

**Tests and scope**

No regression test was added in fix PR #12903; upstream fix body identifies installed buffer and string_decoder as failing inputs and links issue #12888. No local test was run.

No new upstream regression test in the fix PR; evidence consists of the explicit upstream causal statement, introducing call, and targeted option fix. The introducing helper resolvePkgJsonPath was later folded into resolvePackageData, so source line numbers differ at the fix commit. Requires Yarn PnP and an installed package sharing a Node builtin name; ordinary node_modules resolution uses a different path. Selected-path patch excerpts are copied from the GitHub PR-files API and are not a full PR checkout.

[Upstream license](https://github.com/vitejs/vite/blob/1fc8c652c46a27f6229c9125e3b0d1662d2a0e67/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/evidence.json) · [buggy-snippet.txt](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/buggy-snippet.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/LICENSE) · [fix-pr.json](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/fix.patch) · [fixed-snippet.txt](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/fixed-snippet.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-js-vite-pnp-builtins-001/introducing.patch)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/packages/vite/src/node/packages.ts
+++ b/packages/vite/src/node/packages.ts
@@ -1,9 +1,18 @@
 import fs from 'node:fs'
 import path from 'node:path'
-import { createDebugger, createFilter, resolveFrom } from './utils'
+import { createRequire } from 'node:module'
+import { createDebugger, createFilter, safeRealpathSync } from './utils'
 import type { ResolvedConfig } from './config'
 import type { Plugin } from './plugin'

+// eslint-disable-next-line @typescript-eslint/consistent-type-imports
+let pnp: typeof import('pnpapi') | undefined
+if (process.versions.pnp) {
+  try {
+    pnp = createRequire(import.meta.url)('pnpapi')
+  } catch {}
+}
+
 const isDebug = process.env.DEBUG
 const debug = createDebugger('vite:resolve-details', {
   onlyWhenFocused: true,
@@ -60,9 +69,9 @@ export function resolvePackageData(
       return pkg
     }
   }
-  let pkgPath: string | undefined
+  const pkgPath = resolvePkgJsonPath(id, basedir, preserveSymlinks)
+  if (!pkgPath) return null
   try {
-    pkgPath = resolveFrom(`${id}/package.json`, basedir, preserveSymlinks)
     pkg = loadPackageData(pkgPath, true, packageCache)
     if (packageCache) {
       packageCache.set(cacheKey!, pkg)
@@ -72,12 +81,8 @@ export function resolvePackageData(
     if (e instanceof SyntaxError) {
       isDebug && debug(`Parsing failed: ${pkgPath}`)
     }
-    // Ignore error for missing package.json
-    else if (e.code !== 'MODULE_NOT_FOUND') {
-      throw e
-    }
+    throw e
   }
-  return null
 }

 export function loadPackageData(
@@ -86,7 +91,7 @@ export function loadPackageData(
   packageCache?: PackageCache,
 ): PackageData {
   if (!preserveSymlinks) {
-    pkgPath = fs.realpathSync.native(pkgPath)
+    pkgPath = safeRealpathSync(pkgPath)
   }

   let cached: PackageData | undefined
@@ -178,3 +183,30 @@ export function watchPackageDataPlugin(config: ResolvedConfig): Plugin {
     },
   }
 }
+
+export function resolvePkgJsonPath(
+  pkgName: string,
+  basedir: string,
+  preserveSymlinks = false,
+): string | undefined {
+  if (pnp) {
+    const pkg = pnp.resolveToUnqualified(pkgName, basedir)
+    if (!pkg) return undefined
+    return path.join(pkg, 'package.json')
+  }
+
+  let root = basedir
+  while (root) {
+    const pkg = path.join(root, 'node_modules', pkgName, 'package.json')
+    try {
+      if (fs.existsSync(pkg)) {
+        return preserveSymlinks ? pkg : safeRealpathSync(pkg)
+      }
+    } catch {}
+    const nextRoot = path.dirname(root)
+    if (nextRoot === root) break
+    root = nextRoot
+  }
+
+  return undefined
+}
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/packages/vite/src/node/packages.ts
+++ b/packages/vite/src/node/packages.ts
@@ -60,7 +60,9 @@ export function resolvePackageData(

     let pkg: string | null
     try {
-      pkg = pnp.resolveToUnqualified(pkgName, basedir)
+      pkg = pnp.resolveToUnqualified(pkgName, basedir, {
+        considerBuiltins: false,
+      })
     } catch {
       return null
     }
```

</details>

## B2-02

**Package-name matching ignores explicit SSR external entry** · correctness · pending

**When it happens**

Set ssr.external to ['external-entry/entry'] and ssr.noExternal to ['external-entry']; import the same stateful entry both directly and from another external package.

**Proposed finding**

Replacing includes(id) with includes(pkgName) prevents an explicit package subpath from matching ssr.external. The package-level noExternal filter can then bundle that entry despite its explicit external declaration, splitting its module state from the Node-loaded copy. The fix prioritizes an exact id match and adds a state-sharing regression fixture.

[Inspect packages/vite/src/node/ssr/ssrExternal.ts lines 127–128 at the introducing commit](https://github.com/vitejs/vite/blob/5844d8e3480e7713acfa7655666bf0076dcb8879/packages/vite/src/node/ssr/ssrExternal.ts#L127-L128)

```typescript
      const pkgName = getNpmPackageName(id)
      if (!pkgName) {
        return undefined
      }
      if (ssr.external?.includes(pkgName)) {
        return true
      }
      if (typeof noExternal === 'boolean') {
        return !noExternal
      }
```

**Upstream evidence**

[Introducing PR #9146](https://github.com/vitejs/vite/pull/9146) merged 2022-07-15T21:40:24Z · [fix PR #9286](https://github.com/vitejs/vite/pull/9286) merged 2022-07-22T07:47:32Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `5ea70b3c3cd5f208471338c5832a3eba1aafb01d` | `0b083ca84a1b32f9f2c4d73444d30e0c80abe3b1` |
| Head | `259f91f3b6914f53d958e16db7dd63332fc67084` | `f318d9534dfdb3132af03a2ae3a9f985479a2483` |
| Merge | `5844d8e3480e7713acfa7655666bf0076dcb8879` | `d420f01d48c2291e82410b4649f274f8d1493a27` |

Fix PR states: “Fixes a regression introduced by: - https://github.com/vitejs/vite/pull/9146”

**What the fix changed**

Check ssr.external.includes(id) first so a specific entry is forced external; handle package-wide declarations separately and retain the externalizability check.

**Tests and scope**

playground/ssr-deps/__tests__/ssr-deps.spec.ts: msg from external using external entry. Upstream regression coverage was inspected; it was not run locally.

The proposed finding is the loss of exact subpath matching. The same fix also adjusts package-wide externalization so non-externalizable assets still pass through checks. Upstream integration coverage needs Vite SSR playground dependencies and a browser. Selected-path patch excerpts are copied from the GitHub PR-files API and are not a full PR checkout.

[Upstream license](https://github.com/vitejs/vite/blob/5844d8e3480e7713acfa7655666bf0076dcb8879/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/evidence.json) · [buggy-snippet.txt](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/buggy-snippet.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/LICENSE) · [fix-pr.json](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/fix.patch) · [fixed-snippet.txt](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/fixed-snippet.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/introducing.patch) · [regression-test-snippet.txt](../fixtures/golden/golden-b002-js-vite-ssr-entry-001/regression-test-snippet.txt)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/packages/vite/src/node/ssr/ssrExternal.ts
+++ b/packages/vite/src/node/ssr/ssrExternal.ts
@@ -120,13 +120,17 @@ export function createIsConfiguredAsSsrExternal(
   return (id: string) => {
     const { ssr } = config
     if (ssr) {
-      if (ssr.external?.includes(id)) {
+      const pkgName = getNpmPackageName(id)
+      if (!pkgName) {
+        return undefined
+      }
+      if (ssr.external?.includes(pkgName)) {
         return true
       }
       if (typeof noExternal === 'boolean') {
         return !noExternal
       }
-      if (noExternalFilter && !noExternalFilter(id)) {
+      if (noExternalFilter && !noExternalFilter(pkgName)) {
         return false
       }
     }
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/packages/vite/src/node/ssr/ssrExternal.ts
+++ b/packages/vite/src/node/ssr/ssrExternal.ts
@@ -124,9 +124,22 @@ export function createIsConfiguredAsSsrExternal(
       if (!pkgName) {
         return undefined
       }
-      if (ssr.external?.includes(pkgName)) {
+      if (
+        // If this id is defined as external, force it as external
+        // Note that individual package entries are allowed in ssr.external
+        ssr.external?.includes(id)
+      ) {
         return true
       }
+      if (
+        // A package name in ssr.external externalizes every entry
+        ssr.external?.includes(pkgName)
+      ) {
+        // Return undefined here to avoid short-circuiting the isExternalizable check,
+        // that will filter this id out if it is not externalizable (e.g. a CSS file)
+        // We return here to make ssr.external take precedence over noExternal
+        return undefined
+      }
       if (typeof noExternal === 'boolean') {
         return !noExternal
       }
@@ -154,7 +167,7 @@ function createIsSsrExternal(
     isBuild: true
   }

-  const isValidPackageEntry = (id: string) => {
+  const isExternalizable = (id: string) => {
     if (!bareImportRE.test(id) || id.includes('\0')) {
       return false
     }
@@ -176,7 +189,7 @@ function createIsSsrExternal(
     let external = false
     if (!id.startsWith('.') && !path.isAbsolute(id)) {
       external =
-        isBuiltin(id) || (isConfiguredAsExternal(id) ?? isValidPackageEntry(id))
+        isBuiltin(id) || (isConfiguredAsExternal(id) ?? isExternalizable(id))
     }
     processedIds.set(id, external)
     return external
```

</details>

## B2-03

**Required shallowReactive brand rejects plain object assignment** · correctness · pending

**When it happens**

Create const shallow = shallowReactive({ a: 1, b: 2 }); declare let values: typeof shallow; then assign values = { a: 1, b: 2 }.

**Proposed finding**

Changing the optional unique-symbol marker into a required property of type never makes a structurally equivalent plain object unassignable. No public caller can provide the uninhabitable required brand. The fix replaces it with an optional private-class brand; the added assignment test exercises this exact source compatibility regression.

[Inspect packages/reactivity/src/reactive.ts lines 109–109 at the introducing commit](https://github.com/vuejs/core/blob/3b561db4ab42d06166b002f13c0e97cb2bd4a061/packages/reactivity/src/reactive.ts#L109-L109)

```typescript
}

export declare const ShallowReactiveMarker: unique symbol

export type ShallowReactive<T> = T & { [ShallowReactiveMarker]: never }

/**
 * Shallow version of {@link reactive}.
 *
```

**Upstream evidence**

[Introducing PR #14493](https://github.com/vuejs/core/pull/14493) merged 2026-03-25T09:06:27Z · [fix PR #14641](https://github.com/vuejs/core/pull/14641) merged 2026-04-03T02:31:00Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `b147482311762888df6e4681a2c7526bff943fdf` | `81615d398a89beeccfe56a4a96fd2fba0c6fb37b` |
| Head | `1f7669281ebc1fb69dfddf14aa197f49ab0135b4` | `7d2de78f277cd664fc67b8e01b2b39f33a55ff28` |
| Merge | `3b561db4ab42d06166b002f13c0e97cb2bd4a061` | `302c47a4994bc8b47b8a2af6693d8cb6bbd4b06b` |

Fix PR states: “fix shallowReactive type regressions introduced by #14493”

**What the fix changed**

Use a private class with an optional private property as the brand, preserving distinction for unwrap types without requiring a symbol property for plain assignment.

**Tests and scope**

packages-private/dts-test/reactivity.test-d.ts: shallowReactive type should accept plain object assignment. Upstream regression coverage was inspected; it was not run locally.

This case targets plain-object assignability only; the fix PR also changes proxyRefs and collection unwrapping, which are outside the proposed finding. Type-level source compatibility defect, not a runtime reactivity failure. Selected-path patch excerpts are copied from the GitHub PR-files API and are not a full PR checkout.

[Upstream license](https://github.com/vuejs/core/blob/3b561db4ab42d06166b002f13c0e97cb2bd4a061/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/evidence.json) · [buggy-snippet.txt](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/buggy-snippet.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/LICENSE) · [fix-pr.json](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/fix.patch) · [fixed-snippet.txt](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/fixed-snippet.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/introducing.patch) · [regression-test-snippet.txt](../fixtures/golden/golden-b002-js-vue-shallow-brand-001/regression-test-snippet.txt)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/packages/reactivity/src/reactive.ts
+++ b/packages/reactivity/src/reactive.ts
@@ -106,7 +106,7 @@ export function reactive(target: object) {

 export declare const ShallowReactiveMarker: unique symbol

-export type ShallowReactive<T> = T & { [ShallowReactiveMarker]?: true }
+export type ShallowReactive<T> = T & { [ShallowReactiveMarker]: never }

 /**
  * Shallow version of {@link reactive}.
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/packages/reactivity/src/reactive.ts
+++ b/packages/reactivity/src/reactive.ts
@@ -104,9 +104,16 @@ export function reactive(target: object) {
   )
 }

-export declare const ShallowReactiveMarker: unique symbol
+// Use a private class brand instead of a marker property so shallow-reactive
+// types remain distinguishable in `UnwrapRef` without leaking the brand into
+// `keyof`/indexed access types or requiring the property for plain assignment.
+declare class ShallowReactiveBrandClass {
+  private __shallowReactiveBrand?: never
+}
+
+export type ShallowReactiveBrand = ShallowReactiveBrandClass

-export type ShallowReactive<T> = T & { [ShallowReactiveMarker]: never }
+export type ShallowReactive<T> = T & ShallowReactiveBrand

 /**
  * Shallow version of {@link reactive}.
```

</details>

## B2-04

**Casting exact admin search fields prevents use of ordinary database indexes** · performance · pending

**When it happens**

Configure a Django admin exact search on an indexed non-text field, such as search_fields = ["id__exact"], and search a large PostgreSQL table.

**Proposed finding**

For a non-text field such as an indexed integer id searched via id__exact, the introducing change annotates Cast(field_name, CharField()) and filters the cast alias. On PostgreSQL an ordinary integer/primary-key index cannot serve that cast expression, causing full scans on large tables. The fix removes Cast and validates each search term against its target field before building direct lookups.

[Inspect django/contrib/admin/options.py lines 1222–1227 at the introducing commit](https://github.com/django/django/blob/f223729f8f8380901473b244c0fc7c7dc397e3f1/django/contrib/admin/options.py#L1222-L1227)

```python
                    except FieldDoesNotExist:
                        lookup = construct_search(field)
                        orm_lookups.append(lookup)
                        continue
                    # Add string cast annotations for non-string exact lookups.
                    if not isinstance(field_obj, (models.CharField, models.TextField)):
                        str_annotations[f"{field_name}_str"] = Cast(
                            field_name, output_field=models.CharField()
                        )
                        orm_lookups.append(f"{field_name}_str__exact")
                    else:
                        lookup = construct_search(field)
                        orm_lookups.append(lookup)
                else:
```

**Upstream evidence**

[Introducing PR #17885](https://github.com/django/django/pull/17885) merged 2024-11-04T08:39:47Z · [fix PR #20538](https://github.com/django/django/pull/20538) merged 2026-01-30T16:45:39Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `03c0a3de722c4a7de9f3edfeb26417ebc8b90fe9` | `f87c2055b45356378a7c2a020eb872352d20f85e` |
| Head | `7d8962297c54ebbb8bb4eab7ca26ac42f41720be` | `12157a328fdb9801fbc99ff549630040baf2d089` |
| Merge | `f223729f8f8380901473b244c0fc7c7dc397e3f1` | `4cecf3039586ea738afafb9a28c946bff42c37c1` |

Fix PR states: “This PR fixes a performance regression introduced in PR #17885.”

**What the fix changed**

Remove string casts and validate each term against its target field before generating direct lookups. The ordinary indexed column can then remain in the search predicate.

**Tests and scope**

The fix adds invalid-value and mixed-term search regressions, ensuring invalid non-text lookups are skipped while valid direct lookups continue to work. These are behavioral regressions, not a query-plan/performance assertion. Upstream regression tests included, not run here.

No PostgreSQL query-plan reproduction or benchmark was run; index impact is explicit in the fix PR body and matches the removed Cast expression. The implementation was refactored between introducing and fixing PRs. The introducing version handles direct concrete field names (for example id__exact); do not use pk__exact to demonstrate this particular introducing hunk.

[Upstream license](https://github.com/django/django/blob/f223729f8f8380901473b244c0fc7c7dc397e3f1/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-python-django-admin-cast-001/evidence.json) · [introduced-source.txt](../fixtures/golden/golden-b002-python-django-admin-cast-001/introduced-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-python-django-admin-cast-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-python-django-admin-cast-001/LICENSE) · [base-source.txt](../fixtures/golden/golden-b002-python-django-admin-cast-001/base-source.txt) · [before-fix-source.txt](../fixtures/golden/golden-b002-python-django-admin-cast-001/before-fix-source.txt) · [fix-pr.json](../fixtures/golden/golden-b002-python-django-admin-cast-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-python-django-admin-cast-001/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-python-django-admin-cast-001/fixed-source.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-python-django-admin-cast-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-python-django-admin-cast-001/introducing.patch) · [regression-tests.txt](../fixtures/golden/golden-b002-python-django-admin-cast-001/regression-tests.txt) · [source-snapshots.json](../fixtures/golden/golden-b002-python-django-admin-cast-001/source-snapshots.json)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/django/contrib/admin/options.py
+++ b/django/contrib/admin/options.py
@@ -41,6 +41,7 @@
 from django.core.paginator import Paginator
 from django.db import models, router, transaction
 from django.db.models.constants import LOOKUP_SEP
+from django.db.models.functions import Cast
 from django.forms.formsets import DELETION_FIELD_NAME, all_valid
 from django.forms.models import (
     BaseInlineFormSet,
@@ -1207,9 +1208,33 @@ def construct_search(field_name):
         may_have_duplicates = False
         search_fields = self.get_search_fields(request)
         if search_fields and search_term:
-            orm_lookups = [
-                construct_search(str(search_field)) for search_field in search_fields
-            ]
+            str_annotations = {}
+            orm_lookups = []
+            for field in search_fields:
+                if field.endswith("__exact"):
+                    field_name = field.rsplit("__exact", 1)[0]
+                    try:
+                        field_obj = queryset.model._meta.get_field(field_name)
+                    except FieldDoesNotExist:
+                        lookup = construct_search(field)
+                        orm_lookups.append(lookup)
+                        continue
+                    # Add string cast annotations for non-string exact lookups.
+                    if not isinstance(field_obj, (models.CharField, models.TextField)):
+                        str_annotations[f"{field_name}_str"] = Cast(
+                            field_name, output_field=models.CharField()
+                        )
+                        orm_lookups.append(f"{field_name}_str__exact")
+                    else:
+                        lookup = construct_search(field)
+                        orm_lookups.append(lookup)
+                else:
+                    lookup = construct_search(str(field))
+                    orm_lookups.append(lookup)
+
+            if str_annotations:
+                queryset = queryset.annotate(**str_annotations)
+
             term_queries = []
             for bit in smart_split(search_term):
                 if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/django/contrib/admin/options.py
+++ b/django/contrib/admin/options.py
@@ -41,7 +41,6 @@
 from django.core.paginator import Paginator
 from django.db import models, router, transaction
 from django.db.models.constants import LOOKUP_SEP
-from django.db.models.functions import Cast
 from django.forms.formsets import DELETION_FIELD_NAME, all_valid
 from django.forms.models import (
     BaseInlineFormSet,
@@ -1137,6 +1136,12 @@ def get_search_results(self, request, queryset, search_term):

         # Apply keyword searches.
         def construct_search(field_name):
+            """
+            Return a tuple of (lookup, field_to_validate).
+
+            field_to_validate is set for non-text exact lookups so that
+            invalid search terms can be skipped (preserving index usage).
+            """
             if field_name.startswith("^"):
                 return "%s__istartswith" % field_name.removeprefix("^"), None
             elif field_name.startswith("="):
@@ -1148,7 +1153,7 @@ def construct_search(field_name):
             lookup_fields = field_name.split(LOOKUP_SEP)
             # Go through the fields, following all relations.
             prev_field = None
-            for i, path_part in enumerate(lookup_fields):
+            for path_part in lookup_fields:
                 if path_part == "pk":
                     path_part = opts.pk.name
                 try:
@@ -1159,15 +1164,9 @@ def construct_search(field_name):
                         if path_part == "exact" and not isinstance(
                             prev_field, (models.CharField, models.TextField)
                         ):
-                            field_name_without_exact = "__".join(lookup_fields[:i])
-                            alias = Cast(
-                                field_name_without_exact,
-                                output_field=models.CharField(),
-                            )
-                            alias_name = "_".join(lookup_fields[:i])
-                            return f"{alias_name}_str", alias
-                        else:
-                            return field_name, None
+                            # Use prev_field to validate the search term.
+                            return field_name, prev_field
+                        return field_name, None
                 else:
                     prev_field = field
                     if hasattr(field, "path_infos"):
@@ -1179,30 +1178,42 @@ def construct_search(field_name):
         may_have_duplicates = False
         search_fields = self.get_search_fields(request)
         if search_fields and search_term:
-            str_aliases = {}
             orm_lookups = []
             for field in search_fields:
-                lookup, str_alias = construct_search(str(field))
-                orm_lookups.append(lookup)
-                if str_alias:
-                    str_aliases[lookup] = str_alias
-
-            if str_aliases:
-                queryset = queryset.alias(**str_aliases)
+                orm_lookups.append(construct_search(str(field)))

             term_queries = []
             for bit in smart_split(search_term):
                 if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
                     bit = unescape_string_literal(bit)
-                or_queries = models.Q.create(
-                    [(orm_lookup, bit) for orm_lookup in orm_lookups],
-                    connector=models.Q.OR,
-                )
-                term_queries.append(or_queries)
-            queryset = queryset.filter(models.Q.create(term_queries))
+                # Build term lookups, skipping values invalid for their field.
+                bit_lookups = []
+                for orm_lookup, validate_field in orm_lookups:
+                    if validate_field is not None:
+                        formfield = validate_field.formfield()
+                        try:
+                            if formfield is not None:
+                                value = formfield.to_python(bit)
+                            else:
+                                # Fields like AutoField lack a form field.
+                                value = validate_field.to_python(bit)
+                        except ValidationError:
+                            # Skip this lookup for invalid values.
+                            continue
+                    else:
+                        value = bit
+                    bit_lookups.append((orm_lookup, value))
+                if bit_lookups:
+                    or_queries = models.Q.create(bit_lookups, connector=models.Q.OR)
+                    term_queries.append(or_queries)
+                else:
+                    # No valid lookups: add a filter that returns nothing.
+                    term_queries.append(models.Q(pk__in=[]))
+            if term_queries:
+                queryset = queryset.filter(models.Q.create(term_queries))
             may_have_duplicates |= any(
                 lookup_spawns_duplicates(self.opts, search_spec)
-                for search_spec in orm_lookups
+                for search_spec, _ in orm_lookups
             )
         return queryset, may_have_duplicates
```

</details>

## B2-05

**EmailMessage writes a caller-supplied To header twice** · correctness · pending

**When it happens**

Construct EmailMessage with a non-empty to list and headers={"To": "mailing-list@example.com"}, then inspect message().get_all("To").

**Proposed finding**

With non-empty to recipients and headers={"To": "mailing-list@example.com"}, the new list-header helper writes To from extra_headers, then the final extra_headers loop writes it again because the introducing change stops skipping To. Python email.Message assignment appends headers. The fix skips already-handled list headers and changes tests to get_all() so duplicates become visible.

[Inspect django/core/mail/message.py lines 273–276 at the introducing commit](https://github.com/django/django/blob/da82939e5a31dea21a4f4d5085dfcd449fcbed3a/django/core/mail/message.py#L273-L276)

```python
            msg['Date'] = formatdate(localtime=settings.EMAIL_USE_LOCALTIME)
        if 'message-id' not in header_names:
            # Use cached DNS_NAME for performance
            msg['Message-ID'] = make_msgid(domain=DNS_NAME)
        for name, value in self.extra_headers.items():
            if name.lower() == 'from':  # From is already handled
                continue
            msg[name] = value
        return msg

    def recipients(self):
        """
```

**Upstream evidence**

[Introducing PR #9454](https://github.com/django/django/pull/9454) merged 2017-12-30T14:55:42Z · [fix PR #18325](https://github.com/django/django/pull/18325) merged 2024-07-11T06:00:47Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `63349394170347241c48a445c843ff2be53e3a8a` | `d12184fedcd586e2c399ea40abe4bf865ebc87a6` |
| Head | `da82939e5a31dea21a4f4d5085dfcd449fcbed3a` | `a5511235e5bcfd52d986f3099632f67e32b2a4fe` |
| Merge | `da82939e5a31dea21a4f4d5085dfcd449fcbed3a` | `b9098538a966fdc1f2b5ee51c094ca3de4db6344` |

Fix PR states: “ticket-35033 as originally reported was caused by a regression introduced in ticket-28912 (PR #9454).”

**What the fix changed**

Skip To, Cc, and Reply-To in the final extra_headers loop because the list-header helper already handled them. Use get_all() in assertions to expose duplicate header values.

**Tests and scope**

The fix replaces single-header comparisons with message.get_all("To"), get_all("Cc"), and get_all("Reply-To") equality against one-element lists. test_to_header covers the To duplication newly introduced by #9454. Upstream regression tests included, not run here.

The pre-introducing version already had some duplicate-header behavior for Cc/Reply-To. The proposed defect is specifically the newly introduced To duplication, not a claim that all repeated-header variants originate in #9454.

[Upstream license](https://github.com/django/django/blob/da82939e5a31dea21a4f4d5085dfcd449fcbed3a/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-python-django-mail-headers-001/evidence.json) · [introduced-source.txt](../fixtures/golden/golden-b002-python-django-mail-headers-001/introduced-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-python-django-mail-headers-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-python-django-mail-headers-001/LICENSE) · [base-source.txt](../fixtures/golden/golden-b002-python-django-mail-headers-001/base-source.txt) · [before-fix-source.txt](../fixtures/golden/golden-b002-python-django-mail-headers-001/before-fix-source.txt) · [fix-pr.json](../fixtures/golden/golden-b002-python-django-mail-headers-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-python-django-mail-headers-001/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-python-django-mail-headers-001/fixed-source.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-python-django-mail-headers-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-python-django-mail-headers-001/introducing.patch) · [regression-tests.txt](../fixtures/golden/golden-b002-python-django-mail-headers-001/regression-tests.txt) · [source-snapshots.json](../fixtures/golden/golden-b002-python-django-mail-headers-001/source-snapshots.json)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/django/core/mail/message.py
+++ b/django/core/mail/message.py
@@ -254,11 +254,9 @@ def message(self):
         msg = self._create_message(msg)
         msg['Subject'] = self.subject
         msg['From'] = self.extra_headers.get('From', self.from_email)
-        msg['To'] = self.extra_headers.get('To', ', '.join(map(str, self.to)))
-        if self.cc:
-            msg['Cc'] = ', '.join(str(cc) for cc in self.cc)
-        if self.reply_to:
-            msg['Reply-To'] = self.extra_headers.get('Reply-To', ', '.join(str(r) for r in self.reply_to))
+        self._set_list_header_if_not_empty(msg, 'To', self.to)
+        self._set_list_header_if_not_empty(msg, 'Cc', self.cc)
+        self._set_list_header_if_not_empty(msg, 'Reply-To', self.reply_to)

         # Email header names are case-insensitive (RFC 2045), so we have to
         # accommodate that when doing comparisons.
@@ -273,7 +271,7 @@ def message(self):
             # Use cached DNS_NAME for performance
             msg['Message-ID'] = make_msgid(domain=DNS_NAME)
         for name, value in self.extra_headers.items():
-            if name.lower() in ('from', 'to'):  # From and To are already handled
+            if name.lower() == 'from':  # From is already handled
                 continue
             msg[name] = value
         return msg
@@ -408,6 +406,18 @@ def _create_attachment(self, filename, content, mimetype=None):
                                   filename=filename)
         return attachment

+    def _set_list_header_if_not_empty(self, msg, header, values):
+        """
+        Set msg's header, either from self.extra_headers, if present, or from
+        the values argument.
+        """
+        if values:
+            try:
+                value = self.extra_headers[header]
+            except KeyError:
+                value = ', '.join(str(v) for v in values)
+            msg[header] = value
+

 class EmailMultiAlternatives(EmailMessage):
     """
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/django/core/mail/message.py
+++ b/django/core/mail/message.py
@@ -286,7 +286,8 @@ def message(self):
             # Use cached DNS_NAME for performance
             msg["Message-ID"] = make_msgid(domain=DNS_NAME)
         for name, value in self.extra_headers.items():
-            if name.lower() != "from":  # From is already handled
+            # Avoid headers handled above.
+            if name.lower() not in {"from", "to", "cc", "reply-to"}:
                 msg[name] = value
         return msg

@@ -427,14 +428,13 @@ def _create_attachment(self, filename, content, mimetype=None):
     def _set_list_header_if_not_empty(self, msg, header, values):
         """
         Set msg's header, either from self.extra_headers, if present, or from
-        the values argument.
+        the values argument if not empty.
         """
-        if values:
-            try:
-                value = self.extra_headers[header]
-            except KeyError:
-                value = ", ".join(str(v) for v in values)
-            msg[header] = value
+        try:
+            msg[header] = self.extra_headers[header]
+        except KeyError:
+            if values:
+                msg[header] = ", ".join(str(v) for v in values)


 class EmailMultiAlternatives(EmailMessage):
```

</details>

## B2-06

**Cycle tracking crashes the debugger on unhashable exception instances** · correctness · pending

**When it happens**

Format a traceback whose exception class defines __hash__ = None (for example, a mutable custom exception).

**Proposed finding**

The newly added memo.add(exc_value) hashes the exception instance. A legitimate exception class with __hash__ = None raises TypeError while the debugger is formatting the original exception. The fix tracks id(exc_value), preserving cycle detection without requiring hashable exceptions.

[Inspect src/werkzeug/debug/tbtools.py lines 251–255 at the introducing commit](https://github.com/pallets/werkzeug/blob/bdc17e4cd10bbb17449006cef385ec953a11fc36/src/werkzeug/debug/tbtools.py#L251-L255)

```python
        self.groups = []
        memo = set()
        while True:
            self.groups.append(Group(exc_type, exc_value, tb))
            memo.add(exc_value)
            if PY2:
                break
            exc_value = exc_value.__cause__ or exc_value.__context__
            if exc_value is None or exc_value in memo:
                break
            exc_type = type(exc_value)
            tb = exc_value.__traceback__
        self.groups.reverse()
```

**Upstream evidence**

[Introducing PR #1540](https://github.com/pallets/werkzeug/pull/1540) merged 2019-05-12T14:55:29Z · [fix PR #1542](https://github.com/pallets/werkzeug/pull/1542) merged 2019-05-12T23:38:51Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `777500b64647ea47b21e52e5e113ba1d86014c05` | `bdc17e4cd10bbb17449006cef385ec953a11fc36` |
| Head | `44e38c2985bcd3a7c17467bead901b8f36528f5f` | `0e669f6be532801267d35de23c5f5237b8406d8a` |
| Merge | `bdc17e4cd10bbb17449006cef385ec953a11fc36` | `2cbdf2b02273daccf85845b1e1569096e65ffe58` |

Fix PR states: “fix minor regression introduced in #1540”

**What the fix changed**

Track id(exc_value) in the cycle-detection set, rather than hashing exception instances.

**Tests and scope**

Upstream test_non_hashable_exception defines MutableException(ValueError) with __hash__ = None and calls Traceback(*sys.exc_info()); the pre-fix code throws TypeError. Upstream regression tests included, not run here.

Upstream regression test included, not run here. The case targets debugger availability/correctness and makes no security claim.

[Upstream license](https://github.com/pallets/werkzeug/blob/bdc17e4cd10bbb17449006cef385ec953a11fc36/LICENSE.rst)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/evidence.json) · [introduced-source.txt](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/introduced-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/ATTRIBUTION.md) · [LICENSE](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/LICENSE) · [base-source.txt](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/base-source.txt) · [before-fix-source.txt](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/before-fix-source.txt) · [fix-pr.json](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/fix-pr.json) · [fix.patch](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/fixed-source.txt) · [introducing-pr.json](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/introducing-pr.json) · [introducing.patch](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/introducing.patch) · [regression-tests.txt](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/regression-tests.txt) · [source-snapshots.json](../fixtures/golden/golden-b002-python-werkzeug-unhashable-001/source-snapshots.json)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/src/werkzeug/debug/tbtools.py
+++ b/src/werkzeug/debug/tbtools.py
@@ -245,12 +245,14 @@ def __init__(self, exc_type, exc_value, tb):
         self.exception_type = exception_type

         self.groups = []
+        memo = set()
         while True:
             self.groups.append(Group(exc_type, exc_value, tb))
+            memo.add(exc_value)
             if PY2:
                 break
             exc_value = exc_value.__cause__ or exc_value.__context__
-            if exc_value is None:
+            if exc_value is None or exc_value in memo:
                 break
             exc_type = type(exc_value)
             tb = exc_value.__traceback__
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/src/werkzeug/debug/tbtools.py
+++ b/src/werkzeug/debug/tbtools.py
@@ -248,11 +248,11 @@ def __init__(self, exc_type, exc_value, tb):
         memo = set()
         while True:
             self.groups.append(Group(exc_type, exc_value, tb))
-            memo.add(exc_value)
+            memo.add(id(exc_value))
             if PY2:
                 break
             exc_value = exc_value.__cause__ or exc_value.__context__
-            if exc_value is None or exc_value in memo:
+            if exc_value is None or id(exc_value) in memo:
                 break
             exc_type = type(exc_value)
             tb = exc_value.__traceback__
```

</details>

## B2-07

**FileWithLineNum reports an inner wrapper after caller extraction** · correctness · pending

**When it happens**

Call FileWithLineNum through an external wrapper chain and compare the reported file:line with the established outer caller location.

**Proposed finding**

The introduction routes FileWithLineNum through an additional CallerFrame wrapper while retaining runtime.Callers(3). An external wrapper chain is therefore resolved one frame too early, changing the file:line returned by the established helper. The fix chooses explicit stack skips separately for CallerFrame and FileWithLineNum, and tests the wrapped call chain.

[Inspect utils/utils.go lines 55–59 at the introducing commit](https://github.com/go-gorm/gorm/blob/2c3d109af3057f0d0ee64104011f12ac7bdab9bc/utils/utils.go#L55-L59)

```go

    return runtime.Frame{}
}

// FileWithLineNum return the file name and line number of the current file
func FileWithLineNum() string {
    frame := CallerFrame()
    if frame.PC != 0 {
        return string(strconv.AppendInt(append([]byte(frame.File), ':'), int64(frame.Line), 10))
    }

    return ""
}
```

**Upstream evidence**

[Introducing PR #7610](https://github.com/go-gorm/gorm/pull/7610) merged 2025-10-30T10:56:26Z · [fix PR #7717](https://github.com/go-gorm/gorm/pull/7717) merged 2026-03-21T11:31:31Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `b88148363a954f69fa680b152dfd96a94ffea1e1` | `4380dd6dd1a56b7438cec1f4c5a786d006a2c29e` |
| Head | `0f6d61a85d68e0a3ce35cf57117fbca290f11ac9` | `a52dbae3c58bac0d111b9b338ae81f72e46ad6d7` |
| Merge | `2c3d109af3057f0d0ee64104011f12ac7bdab9bc` | `61520d7476a5b08cf09439da7bb2628f86d2cd25` |

Fix PR states: “After #7610, stack scanning was extracted into CallerFrame().”

**What the fix changed**

Use separate explicit stack-skip counts for CallerFrame and FileWithLineNum and exercise the wrapped call chain in the regression test.

**Tests and scope**

utils/utils_test.go: TestFileWithLineNumWrappedCallRegression. Upstream regression coverage was inspected; it was not run locally.

This affects caller source diagnostics, rather than database query results. The regression test and stack-depth changes were inspected at the merged fix; no Go tests were executed locally.

[Upstream license](https://github.com/go-gorm/gorm/blob/2c3d109af3057f0d0ee64104011f12ac7bdab9bc/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/evidence.json) · [buggy-source.txt](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/buggy-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/ATTRIBUTION.md) · [LICENSE.upstream](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/LICENSE.upstream) · [fix-test.txt](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/fix-test.txt) · [fix.patch](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/fixed-source.txt) · [task.patch](../fixtures/golden/golden-b002-systems-go-gorm-caller-depth/task.patch)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/utils/utils.go
+++ b/utils/utils.go
@@ -30,8 +30,12 @@ func sourceDir(file string) string {
    return filepath.ToSlash(s) + "/"
 }

-// FileWithLineNum return the file name and line number of the current file
-func FileWithLineNum() string {
+// CallerFrame retrieves the first relevant stack frame outside of GORM's internal implementation files.
+// It skips:
+//   - GORM's core source files (identified by gormSourceDir prefix)
+//   - Exclude test files (*_test.go)
+//   - go-gorm/gen's Generated files (*.gen.go)
+func CallerFrame() runtime.Frame {
    pcs := [13]uintptr{}
    // the third caller usually from gorm internal
    len := runtime.Callers(3, pcs[:])
@@ -41,10 +45,20 @@ func FileWithLineNum() string {
        frame, _ := frames.Next()
        if (!strings.HasPrefix(frame.File, gormSourceDir) ||
            strings.HasSuffix(frame.File, "_test.go")) && !strings.HasSuffix(frame.File, ".gen.go") {
-           return string(strconv.AppendInt(append([]byte(frame.File), ':'), int64(frame.Line), 10))
+           return frame
        }
    }

+   return runtime.Frame{}
+}
+
+// FileWithLineNum return the file name and line number of the current file
+func FileWithLineNum() string {
+   frame := CallerFrame()
+   if frame.PC != 0 {
+       return string(strconv.AppendInt(append([]byte(frame.File), ':'), int64(frame.Line), 10))
+   }
+
    return ""
 }
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/utils/utils.go
+++ b/utils/utils.go
@@ -36,9 +36,14 @@ func sourceDir(file string) string {
 //   - Exclude test files (*_test.go)
 //   - go-gorm/gen's Generated files (*.gen.go)
 func CallerFrame() runtime.Frame {
+   // Preserve the original CallerFrame stack depth after introducing callerFrame().
+   return callerFrame(4)
+}
+
+func callerFrame(skip int) runtime.Frame {
    pcs := [13]uintptr{}
-   // the third caller usually from gorm internal
-   len := runtime.Callers(3, pcs[:])
+   // skip is caller-path sensitive and should be selected by each public helper.
+   len := runtime.Callers(skip, pcs[:])
    frames := runtime.CallersFrames(pcs[:len])
    for i := 0; i < len; i++ {
        // second return value is "more", not "ok"
@@ -54,7 +59,8 @@ func CallerFrame() runtime.Frame {

 // FileWithLineNum return the file name and line number of the current file
 func FileWithLineNum() string {
-   frame := CallerFrame()
+   // Keep FileWithLineNum one frame outer than CallerFrame to preserve pre-v1.31.1 semantics.
+   frame := callerFrame(4)
    if frame.PC != 0 {
        return string(strconv.AppendInt(append([]byte(frame.File), ':'), int64(frame.Line), 10))
    }
```

</details>

## B2-08

**Composite map key-set removal exposes a hidden duplicate key** · correctness · pending

**When it happens**

Construct a CompositeMap with a key present in both backing maps and call compositeMap.keySet().remove(key).

**Proposed finding**

The introduced short-circuit OR skips removing the element from the second collection after the first removal succeeds. CompositeSet inherits this behavior and backs CompositeMap.keySet(); deleting an overlapping key therefore reveals the previously hidden second-map entry instead of removing the mapping. The fix overrides set removal to evaluate removals against both sets.

[Inspect spring-core/src/main/java/org/springframework/util/CompositeCollection.java lines 115–118 at the introducing commit](https://github.com/spring-projects/spring-framework/blob/f5a71230440381427d7d652e94a44a8658357025/spring-core/src/main/java/org/springframework/util/CompositeCollection.java#L115-L118)

```java
    public boolean add(E e) {
        throw new UnsupportedOperationException();
    }

    @Override
    public boolean remove(Object o) {
        return (this.first.remove(o) || this.second.remove(o));
    }

    @Override
    public boolean containsAll(Collection<?> c) {
        for (Object o : c) {
```

**Upstream evidence**

[Introducing PR #37332](https://github.com/spring-projects/spring-framework/pull/37332) merged 2026-10-02T14:26:54Z · [fix PR #37394](https://github.com/spring-projects/spring-framework/pull/37394) merged 2026-10-05T09:34:42Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `bc45a6a511bf739efa6e30cef7942c879df160fe` | `9b93e5f635dd6576cf049f8e1f8f623968c88047` |
| Head | `eab3c7bc0e4869fe005a34186cce4c5da3b5a203` | `751251815cc70f8ff34a55283ffaeb5fc4552a82` |
| Merge | `f5a71230440381427d7d652e94a44a8658357025` | `891f9f94dbd6dd4edcc8c6a86fd5907f0262b206` |

Fix PR states: “Since #37332, `CompositeCollection.remove(Object)` stops after removing the element from the first collection.”

**What the fix changed**

Override CompositeSet.remove so both backing sets are evaluated instead of short-circuiting after the first successful removal.

**Tests and scope**

spring-core/src/test/java/org/springframework/util/CompositeMapTests.java: CompositeMapTests.CollisionTests.keySetRemove. Upstream regression coverage was inspected; it was not run locally.

The Collection.remove single-instance behavior is intentional; the defect concerns inherited Set/Map view behavior. Upstream fix body reports the new regression test fails without the change. This task inspected that test and fix, but did not run Gradle.

[Upstream license](https://github.com/spring-projects/spring-framework/blob/f5a71230440381427d7d652e94a44a8658357025/LICENSE.txt)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/evidence.json) · [buggy-source.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/buggy-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/ATTRIBUTION.md) · [LICENSE.upstream](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/LICENSE.upstream) · [NOTICE.upstream](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/NOTICE.upstream) · [buggy-map-constructor.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/buggy-map-constructor.txt) · [buggy-map-view.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/buggy-map-view.txt) · [buggy-set.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/buggy-set.txt) · [fix-test.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/fix-test.txt) · [fix.patch](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/fixed-source.txt) · [task.patch](../fixtures/golden/golden-b002-systems-java-spring-composite-set-remove/task.patch)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/spring-core/src/main/java/org/springframework/util/CompositeCollection.java
+++ b/spring-core/src/main/java/org/springframework/util/CompositeCollection.java
@@ -114,9 +114,7 @@ public boolean add(E e) {

    @Override
    public boolean remove(Object o) {
-       boolean firstResult = this.first.remove(o);
-       boolean secondResult = this.second.remove(o);
-       return firstResult || secondResult;
+       return (this.first.remove(o) || this.second.remove(o));
    }

    @Override
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/spring-core/src/main/java/org/springframework/util/CompositeSet.java
+++ b/spring-core/src/main/java/org/springframework/util/CompositeSet.java
@@ -31,8 +31,25 @@
  */
 final class CompositeSet<E extends @Nullable Object> extends CompositeCollection<E> implements Set<E> {

+   private final Set<E> first;
+
+   private final Set<E> second;
+
+
    CompositeSet(Set<E> first, Set<E> second) {
        super(first, second);
+       this.first = first;
+       this.second = second;
+   }
+
+
+   @Override
+   public boolean remove(Object o) {
+       // A set contains a given element at most once: remove it from both sets
+       // so that an element hidden in the second set does not become visible.
+       boolean firstResult = this.first.remove(o);
+       boolean secondResult = this.second.remove(o);
+       return (firstResult || secondResult);
    }
```

</details>

## B2-09

**Alternative timer reset registers with a different runtime** · correctness · pending

**When it happens**

Enable the unstable alternative timer; create a Sleep under runtime A and reset it while running under runtime B.

**Proposed finding**

Timer::new computes its deadline using the original runtime handle, then unconditionally pushes the entry onto the current worker runtime registration queue. Resetting a sleep from another runtime can migrate its timer or panic in a current-thread runtime. The introducing patch removed the runtime identity guard; the fix restores the guard and falls back to registration through the original runtime handle.

[Inspect tokio/src/runtime/time_alt/timer.rs lines 30–35 at the introducing commit](https://github.com/tokio-rs/tokio/blob/923e72345c77aef4d11875d874ba67421b0412d3/tokio/src/runtime/time_alt/timer.rs#L30-L35)

```rust
}

impl Timer {
    #[track_caller]
    pub(crate) fn new(handle: scheduler::Handle, deadline: Instant) -> Self {
        let tick = deadline_to_tick(&handle, deadline);
        let entry = with_current_temp_local_context(|ctx| match ctx {
            Some(TempLocalContext::Running { registration_queue }) => {
                let entry = EntryHandle::new(tick);
                unsafe { registration_queue.push_front(entry.clone()) }
                entry
            }
            #[cfg(feature = "rt-multi-thread")]
            Some(TempLocalContext::Shutdown) => panic!("{RUNTIME_SHUTTING_DOWN_ERROR}"),
```

**Upstream evidence**

[Introducing PR #8132](https://github.com/tokio-rs/tokio/pull/8132) merged 2026-05-25T00:11:09Z · [fix PR #8169](https://github.com/tokio-rs/tokio/pull/8169) merged 2026-05-26T02:29:50Z

| Pin | Introducing PR | Fix PR |
|---|---|---|
| Base | `82fe082ef14c2e2b2c1c29ed9873c2ca6e6109ee` | `923e72345c77aef4d11875d874ba67421b0412d3` |
| Head | `7e1265c0da7b8ad60ba175530de03b0effed2177` | `9a3508a66373a7a5eab6111ebc434e8713d70cbb` |
| Merge | `923e72345c77aef4d11875d874ba67421b0412d3` | `37ced33efddccc6721588af6fbe095d34fa17d7d` |

Fix PR states: “Fix the regression introduced by <https://github.com/tokio-rs/tokio/pull/8132>.”

**What the fix changed**

Check that the current runtime is the original timer runtime before enqueueing locally; otherwise register through the original runtime handle.

**Tests and scope**

tokio/tests/time_alt.rs: reset_should_stay_on_same_runtime, reset_should_stay_on_same_runtime2. Upstream regression coverage was inspected; it was not run locally.

Applies to the alternative timer enabled through the unstable enable_alt_timer API; do not generalize to the default timer. Both upstream regression tests are present in the merged fix; they were inspected but not executed locally.

[Upstream license](https://github.com/tokio-rs/tokio/blob/923e72345c77aef4d11875d874ba67421b0412d3/LICENSE)

Local fixtures · [evidence.json](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/evidence.json) · [buggy-source.txt](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/buggy-source.txt) · [ATTRIBUTION.md](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/ATTRIBUTION.md) · [LICENSE.upstream](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/LICENSE.upstream) · [fix-test.txt](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/fix-test.txt) · [fix.patch](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/fix.patch) · [fixed-source.txt](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/fixed-source.txt) · [task.patch](../fixtures/golden/golden-b002-systems-rust-tokio-timer-runtime/task.patch)

<details>
<summary>Introducing diff excerpt</summary>

```diff
--- a/tokio/src/runtime/time_alt/timer.rs
+++ b/tokio/src/runtime/time_alt/timer.rs
@@ -1,5 +1,5 @@
 use super::{EntryHandle, TempLocalContext};
-use crate::runtime::scheduler::Handle as SchedulerHandle;
+use crate::runtime::scheduler;
 use crate::time::Instant;

 use std::pin::Pin;
@@ -9,143 +9,76 @@ use std::task::{Context, Poll};
 use crate::util::error::RUNTIME_SHUTTING_DOWN_ERROR;

 pub(crate) struct Timer {
-    sched_handle: SchedulerHandle,
-
     /// The entry in the timing wheel.
-    ///
-    /// - `Some` if the timer is registered / pending / woken up / cancelling.
-    /// - `None` if the timer is unregistered.
-    entry: Option<EntryHandle>,
-
-    /// The deadline for the timer.
-    deadline: Instant,
+    entry: EntryHandle,
 }

 impl std::fmt::Debug for Timer {
     fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
-        f.debug_struct("Timer")
-            .field("deadline", &self.deadline)
-            .finish()
+        f.debug_struct("Timer").finish()
     }
 }

 impl Drop for Timer {
     fn drop(&mut self) {
-        if let Some(entry) = self.entry.take() {
-            entry.cancel();
-        }
+        self.entry.cancel();
     }
 }

 impl Timer {
     #[track_caller]
-    pub(crate) fn new(sched_hdl: SchedulerHandle, deadline: Instant) -> Self {
-        // Panic if the time driver is not enabled
-        let _ = sched_hdl.driver().time();
-        Timer {
-            sched_handle: sched_hdl,
-            entry: None,
-            deadline,
-        }
-    }
-
-    pub(crate) fn deadline(&self) -> Instant {
-        self.deadline
-    }
-
-    pub(crate) fn is_elapsed(&self) -> bool {
-        self.entry.as_ref().is_some_and(|entry| entry.is_woken_up())
-    }
-
-    fn register(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
-        let this = self.get_mut();
-
-        with_current_temp_local_context(&this.sched_handle, |maybe_time_cx| {
-            let deadline = deadline_to_tick(&this.sched_handle, this.deadline);
-
-            match maybe_time_cx {
-                Some(TempLocalContext::Running {
-                    registration_queue: _,
-                    elapsed,
-                }) if deadline <= elapsed => Poll::Ready(()),
-
-                Some(TempLocalContext::Running {
-                    registration_queue,
-                    elapsed: _,
-                }) => {
-                    let hdl = EntryHandle::new(deadline, cx.waker().clone());
-                    this.entry = Some(hdl.clone());
-                    unsafe {
-                        registration_queue.push_front(hdl);
-                    }
-                    Poll::Pending
-                }
-                #[cfg(feature = "rt-multi-thread")]
-                Some(TempLocalContext::Shutdown) => panic!("{RUNTIME_SHUTTING_DOWN_ERROR}"),
-
-                _ => {
-                    let hdl = EntryHandle::new(deadline, cx.waker().clone());
-                    this.entry = Some(hdl.clone());
-                    push_from_remote(&this.sched_handle, hdl);
-                    Poll::Pending
-                }
+    pub(crate) fn new(handle: scheduler::Handle, deadline: Instant) -> Self {
+        let tick = deadline_to_tick(&handle, deadline);
+        let entry = with_current_temp_local_context(|ctx| match ctx {
+            Some(TempLocalContext::Running { registration_queue }) => {
+                let entry = EntryHandle::new(tick);
+                unsafe { registration_queue.push_front(entry.clone()) }
+                entry
             }
-        })
-    }
+            #[cfg(feature = "rt-multi-thread")]
+            Some(TempLocalContext::Shutdown) => panic!("{RUNTIME_SHUTTING_DOWN_ERROR}"),

-    pub(crate) fn poll_elapsed(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
-        match self.entry.as_ref() {
-            Some(entry) => entry.poll(cx),
-            None => self.register(cx),
-        }
-    }
+            _ => {
+                let entry = EntryHandle::new(tick);
+                push_from_remote(&handle, entry.clone());
+                entry
+            }
+        });

-    pub(crate) fn scheduler_handle(&self) -> &SchedulerHandle {
-        &self.sched_handle
+        Timer { entry }
     }

-    #[cfg(all(tokio_unstable, feature = "tracing"))]
-    pub(crate) fn driver(&self) -> &crate::runtime::time::Handle {
-        self.sched_handle.driver().time()
+    pub(crate) fn is_elapsed(&self) -> bool {
+        self.entry.is_woken_up()
     }

-    #[cfg(all(tokio_unstable, feature = "tracing"))]
-    pub(crate) fn clock(&self) -> &crate::time::Clock {
-        self.sched_handle.driver().clock()
+    pub(crate) fn poll_elapsed(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
+        self.entry.poll(cx)
     }
 }

-fn with_current_temp_local_context<F, R>(hdl: &SchedulerHandle, f: F) -> R
+fn with_current_temp_local_context<F, R>(f: F) -> R
 where
     F: FnOnce(Option<TempLocalContext<'_>>) -> R,
 {
     #[cfg(not(feature = "rt"))]
     {
-        let (_, _) = (hdl, f);
+        let _ = f;
         panic!("Tokio runtime is not enabled, cannot access the current wheel");
     }

     #[cfg(feature = "rt")]
     {
         use crate::runtime::context;

-        let is_same_rt =
-            context::with_current(|cur_hdl| cur_hdl.is_same_runtime(hdl)).unwrap_or_default();
-
-        if !is_same_rt {
-            // We don't want to create the timer in one runtime,
-            // but register it in a different runtime's timer wheel.
-            f(None)
-        } else {
-            context::with_scheduler(|maybe_cx| match maybe_cx {
-                Some(cx) => cx.with_time_temp_local_context(f),
-                None => f(None),
-            })
-        }
+        context::with_scheduler(|maybe_cx| match maybe_cx {
+            Some(cx) => cx.expect_multi_thread().with_time_temp_local_context(f),
+            None => f(None),
+        })
     }
 }

-fn push_from_remote(sched_hdl: &SchedulerHandle, entry_hdl: EntryHandle) {
+fn push_from_remote(sched_hdl: &scheduler::Handle, entry_hdl: EntryHandle) {
     #[cfg(not(feature = "rt"))]
     {
         let (_, _) = (sched_hdl, entry_hdl);
@@ -159,7 +92,7 @@ fn push_from_remote(sched_hdl: &SchedulerHandle, entry_hdl: EntryHandle) {
     }
 }

-fn deadline_to_tick(sched_hdl: &SchedulerHandle, deadline: Instant) -> u64 {
+fn deadline_to_tick(sched_hdl: &scheduler::Handle, deadline: Instant) -> u64 {
     let time_hdl = sched_hdl.driver().time();
     time_hdl.time_source().deadline_to_tick(deadline)
 }
```

</details>

<details>
<summary>Fix diff excerpt</summary>

```diff
--- a/tokio/src/runtime/time_alt/timer.rs
+++ b/tokio/src/runtime/time_alt/timer.rs
@@ -29,7 +29,7 @@ impl Timer {
     #[track_caller]
     pub(crate) fn new(handle: scheduler::Handle, deadline: Instant) -> Self {
         let tick = deadline_to_tick(&handle, deadline);
-        let entry = with_current_temp_local_context(|ctx| match ctx {
+        let entry = with_current_temp_local_context(&handle, |ctx| match ctx {
             Some(TempLocalContext::Running { registration_queue }) => {
                 let entry = EntryHandle::new(tick);
                 unsafe { registration_queue.push_front(entry.clone()) }
@@ -57,7 +57,7 @@ impl Timer {
     }
 }

-fn with_current_temp_local_context<F, R>(f: F) -> R
+fn with_current_temp_local_context<F, R>(sched_hdl: &scheduler::Handle, f: F) -> R
 where
     F: FnOnce(Option<TempLocalContext<'_>>) -> R,
 {
@@ -69,8 +69,39 @@ where

     #[cfg(feature = "rt")]
     {
+        use crate::loom::sync::Arc;
         use crate::runtime::context;

+        // There is no compile-time guarantee that the timer is
+        // always registered in the same runtime as it was created in,
+        // so we need to check it at runtime.
+        let is_same_rt = context::with_current(|cur_sched_hdl| {
+            use crate::runtime::scheduler::Handle;
+
+            match (sched_hdl, cur_sched_hdl) {
+                (Handle::CurrentThread(_), _) => {
+                    // this case is impossible as `tokio::runtime::Builder::enable_alt_timer`
+                    // is not supported in the current-thread runtime, but we'd better handle it
+                    // in case the API is misused in the future.
+                    unreachable!("alternative timer is not supported in the current-thread runtime")
+                }
+                (_, Handle::CurrentThread(_)) => false,
+                (Handle::MultiThread(sched_hdl), Handle::MultiThread(cur_sched_hdl)) => {
+                    Arc::as_ptr(sched_hdl) == Arc::as_ptr(cur_sched_hdl)
+                }
+            }
+        })
+        .unwrap_or_default();
+
+        if !is_same_rt {
+            // The timer is being registered from a runtime
+            // that is different from the runtime that the timer is created in,
+            // so we cannot access `TempLocalContext` of the original runtime.
+            return f(None);
+        }
+
+        // The timer is being registered from the same runtime that the timer is created in,
+        // so we can access `TempLocalContext`.
         context::with_scheduler(|maybe_cx| match maybe_cx {
             Some(cx) => cx.expect_multi_thread().with_time_temp_local_context(f),
             None => f(None),
```

</details>

## Your decisions

```text
B2-01 pending
B2-02 pending
B2-03 pending
B2-04 pending
B2-05 pending
B2-06 pending
B2-07 pending
B2-08 pending
B2-09 pending
```
