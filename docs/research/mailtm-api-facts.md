# Mail.tm API facts for a synchronous Python client

Researched 2026-10-21 against primary sources only.

Each claim is tagged:

- **DOCUMENTED** — official human docs or the API's own machine description
- **OBSERVED** — a live request made that day
- **UNKNOWN** — not in those sources, or not checked

## Sources

| Source | What it is | How it was read |
| --- | --- | --- |
| https://docs.mail.tm/ | Official docs (Nuxt site) | `WebFetch` returned the SPA shell ("Page not found") and no article text. Page text below is from loading the same URLs in a browser. |
| https://api.mail.tm/docs.jsonopenapi | OpenAPI 3.1.0, `info.title` `api.mail.tm`, `info.version` `3.0.0` | `GET` with `Accept: application/vnd.openapi+json`. `Content-Type: application/vnd.openapi+json`. |
| https://api.mail.tm/docs.jsonld | Hydra `ApiDocumentation` | Linked from every API response (`Link: <http://api.mail.tm/docs.jsonld>; rel="http://www.w3.org/ns/hydra/core#apiDocumentation"`) and from the docs "Download OpenAPI Spec" button. This file is Hydra JSON-LD, not OpenAPI. |
| https://api.mail.tm/contexts/Message and `/contexts/Account` | JSON-LD term lists | `GET` with `Accept: application/ld+json`. Vocabulary only. A term here is not proof it appears in a response. |
| Live `https://api.mail.tm` | Response headers and bodies | A small number of requests. One throwaway account was created and then deleted. The documented 8 QPS limit was not deliberately exceeded. |

The docs homepage says the API follows OpenAPI v3 and labels https://api.mail.tm/docs.jsonld as the download. The OpenAPI 3.1 document is the separate URL above. **DOCUMENTED** (homepage, https://docs.mail.tm/) and **OBSERVED** (`GET https://api.mail.tm/docs.jsonopenapi` → 200; `GET https://api.mail.tm/docs.json` → 404 `{"title":"An error occurred","detail":"Format \"json\" is not supported","status":404,"type":"/errors/404"}`).

Global security in the OpenAPI document is HTTP bearer, format JWT, on every operation. **DOCUMENTED** (`docs.jsonopenapi`, `security` and `components.securitySchemes.JWT`). That description is incomplete: unauthenticated calls work for some routes (see below).

---

## 1. Rate limits

### What the human docs say

**DOCUMENTED** (https://docs.mail.tm/, "Access to the API"): "The general quota limit is 8 queries per second (QPS) per IP address."

**DOCUMENTED** (https://docs.mail.tm/getting-started/error-handling): status **429** means "You exceeded the limit of 8 requests per second." The only recovery instruction is to delay about one second.

Those pages do not name a response header, do not mention `Retry-After`, and do not describe the 429 body. **DOCUMENTED** as an omission: `Retry-After` is undocumented.

The OpenAPI document does not mention rate limits, 429, or `Retry-After`. **DOCUMENTED** (`docs.jsonopenapi`: no `429` responses, no `Retry-After`).

### What responses actually advertised

Successful and error responses from collection, account, message, and domain routes included:

`ratelimit-policy: 30; w=60`

**OBSERVED** on, among others:

- `GET https://api.mail.tm/domains` → 200
- `GET https://api.mail.tm/docs.jsonopenapi` → 200
- `GET https://api.mail.tm/me` with a bearer token → 200
- `GET https://api.mail.tm/messages` with a bearer token → 200
- `GET https://api.mail.tm/messages/000000000000000000000000` → 404
- `GET https://api.mail.tm/messages` with `Authorization: Bearer not-a-jwt` → 401
- `DELETE https://api.mail.tm/accounts/{id}` → 204

That value uses the IETF `RateLimit-Policy` quota syntax: a quota of 30 over a window of 60 seconds. Mail.tm's docs do not define the header. No `RateLimit`, `X-RateLimit-*`, or `Retry-After` header was present on those responses. **OBSERVED**.

`POST /accounts` advertised a tighter policy on both success and validation failure:

`ratelimit-policy: 1; w=60`

**OBSERVED** on `POST https://api.mail.tm/accounts` → 201, and on `POST https://api.mail.tm/accounts` with an empty JSON object → 422.

### The one 429 that was seen

A second `POST https://api.mail.tm/accounts` sent about a second after another `POST /accounts` returned:

- status **429**
- body empty (not JSON)
- no `Content-Type`
- `ratelimit-policy: 1; w=60`
- no `Retry-After`

**OBSERVED.** This matches the account-creation window advertised above. It does not show what an 8-requests-per-second 429 looks like.

`POST /token` was different. A fully dumped `POST https://api.mail.tm/token` → 200 had only `cache-control`, `content-type`, `date`, `server`, `content-length`, and `connection`. No rate-limit header. Several `POST /token` calls about a second apart returned 200 or 401, never 429. **OBSERVED** (small sample). Whether `/token` is limited is **UNKNOWN**.

### What was not checked

Whether 8 requests in one second returns 429, and whether the 31st ordinary request in 60 seconds returns 429, was not tested. **UNKNOWN.** The docs (8 per second) and the live `30; w=60` header describe different quotas. Both can be true at once, but only the header and the account-creation 429 were observed.

---

## 2. Pagination

### Which routes take `page`

**DOCUMENTED** (OpenAPI `GET /messages` and `GET /domains`): query parameter `page`, integer, default `1`, not required, description "The collection page number", `allowEmptyValue: true`.

**DOCUMENTED** (https://docs.mail.tm/api/messages and https://docs.mail.tm/api/domains): the same `page` parameter, type int.

No other operation in the OpenAPI document defines a query parameter. There is no documented `itemsPerPage`, `seen`, or search query parameter. **DOCUMENTED** (`docs.jsonopenapi` path list).

### Collection JSON (JSON-LD)

**DOCUMENTED** (OpenAPI, `application/ld+json` schema for `GET /messages` and `GET /domains`). The object may contain:

| Field | Schema |
| --- | --- |
| `hydra:member` | array. The only **required** property. |
| `hydra:totalItems` | integer, minimum 0. Optional in the schema. |
| `hydra:view` | object, optional. Properties: `@id`, `@type`, `hydra:first`, `hydra:last`, `hydra:previous`, `hydra:next` (IRI strings). |
| `hydra:search` | object, optional. Properties: `@type`, `hydra:template`, `hydra:variableRepresentation`, `hydra:mapping[]` of `{@type, variable, property (string or null), required (boolean)}`. |

`hydra:member` items are `Message.jsonld-messages.read` or `Domain.jsonld` (section 3 and the domain note below).

The human docs show the same four Hydra members, always populated in the example, and say to read the total from `hydra:totalItems`. **DOCUMENTED** (https://docs.mail.tm/api/messages, https://docs.mail.tm/api/domains).

HAL and JSON:API variants in the same OpenAPI responses use `totalItems` and `itemsPerPage` as **response** fields. `itemsPerPage` is not a documented query parameter. **DOCUMENTED** (`docs.jsonopenapi`).

### Page size

**DOCUMENTED** (https://docs.mail.tm/api/messages): "There are up to 30 messages per page."

**DOCUMENTED** (https://docs.mail.tm/api/domains): "There are up to 30 domains per page."

The number 30 does not appear in the OpenAPI document. **DOCUMENTED** as absent there. The live domain list had one domain, and the live inbox had zero messages, so 30 was not measured. **UNKNOWN** in practice.

### What a real collection looked like

`GET https://api.mail.tm/domains` → 200, `Content-Type: application/ld+json`:

- `@context`, `@id` (`/domains`), `@type` (`hydra:Collection`)
- `hydra:totalItems`: `1`
- `hydra:member`: one domain object
- no `hydra:view`
- no `hydra:search`

**OBSERVED.** `GET https://api.mail.tm/domains?page=1` returned the same shape. **OBSERVED.**

`GET https://api.mail.tm/domains?page=2` → **200**, not 404:

- `hydra:totalItems` still `1`
- `hydra:member` `[]`
- `@id` still `/domains`
- no `hydra:view`

**OBSERVED.**

`GET https://api.mail.tm/messages` with a bearer token, empty inbox → 200:

```json
{"@context":"/contexts/Message","@id":"/messages","@type":"hydra:Collection","hydra:totalItems":0,"hydra:member":[]}
```

**OBSERVED.** `GET https://api.mail.tm/messages?page=2` returned the same body. **OBSERVED.**

`GET https://api.mail.tm/domains?itemsPerPage=1` → 200, same single member, plus:

```json
"hydra:view":{"@id":"/domains?itemsPerPage=1","@type":"hydra:PartialCollectionView"}
```

**OBSERVED.** The server echoed `itemsPerPage`. With only one domain, that call does not show whether the parameter shortens the page. **UNKNOWN.**

A client cannot require `hydra:view`, `hydra:next`, or `hydra:search` to be present. Past-the-end pages return 200 with an empty `hydra:member` and the same `hydra:totalItems`.

---

## 3. Message list item and message detail

Two schemas exist. Human docs: https://docs.mail.tm/api/messages. OpenAPI: `Message.jsonld-messages.read` (list member) and `Message.jsonld-message.read` (GET `/messages/{id}`). Nothing in either source was checked against a real message: SMTP to `in.mail.tm:25` timed out, and the inbox stayed empty. **OBSERVED** (`GET /messages` → `hydra:totalItems` 0). Nullability and the list-vs-detail conflicts below are therefore **UNKNOWN** on the wire unless a cell says otherwise.

OpenAPI marks almost no message property as required. The only explicit null union is `sourceUrl`: `["string", "null"]`. Other properties are not `nullable`. Omission and JSON `null` are not specified. **DOCUMENTED** (`docs.jsonopenapi`). Human examples use placeholders (`"string"`, `true`, `0`) and do not discuss null. **DOCUMENTED** (https://docs.mail.tm/api/messages).

`from` has no JSON Schema `type`. It has an example object `{"address","name"}`. `to`, `cc`, `bcc`, and `attachments` are `type: array` with `items.type: array`, while their examples are arrays of objects. Treat the `items.type: array` as a broken schema. **DOCUMENTED** (`docs.jsonopenapi`).

### GET `/messages` — each `hydra:member` element

| Field | Human docs example | OpenAPI list schema (`Message.jsonld-messages.read`) |
| --- | --- | --- |
| `@id`, `@type`, `@context` | string | `@id` and `@type` string, read-only. `@context` string or `{@vocab, hydra}`. |
| `id` | string | string, read-only |
| `accountId` | string | string, format `iri-reference`. Example in the schema is `https://example.com/`, which may not match a raw id. |
| `msgid` | string | string |
| `from` | object `{name, address}` strings | no type; example `{address, name}` |
| `to` | array of `{name, address}` | array; example is array of `{address, name}` |
| `subject` | string | string |
| `intro` | string | string |
| `seen` | boolean | boolean |
| `isDeleted` | boolean | boolean |
| `hasAttachments` | boolean | boolean |
| `size` | number `0` | integer |
| `downloadUrl` | string | string |
| `createdAt` | date-time `2022-04-01T00:00:00.000Z` | string, format `date-time` |
| `updatedAt` | date-time | string, format `date-time` |
| `sourceUrl` | absent from the example | string or null |

**DOCUMENTED** (both sources, as split in the table).

Not in the list example and not in the list schema: `text`, `html`, `cc`, `bcc`, `attachments`, `flagged`, `verifications`, `retention`, `retentionDate`. **DOCUMENTED.**

The only documented query parameter is `page` (section 2). **DOCUMENTED.**

### GET `/messages/{id}`

Human docs: "It has way more information than a message retrieved with GET /messages but it hasn't the `intro` member." **DOCUMENTED** (https://docs.mail.tm/api/messages).

OpenAPI `Message.jsonld-message.read` still includes `intro` (string). **DOCUMENTED** (`docs.jsonopenapi`). Whether a detail payload contains `intro` is **UNKNOWN**.

| Field | Human docs example | OpenAPI detail schema |
| --- | --- | --- |
| `@context`, `@id`, `@type`, `id` | strings | same as list |
| `accountId` | string | string, `iri-reference` |
| `msgid` | string | string |
| `from` | `{name, address}` strings | example object, no schema type |
| `to` | array of `{name, address}` | array; example is objects `{address, name}` |
| `cc` | array of **string** | array; example is objects `{address, name}` |
| `bcc` | array of **string** | array; example is objects `{address, name}` |
| `subject` | string | string |
| `intro` | absent; prose says it is not on the detail | string |
| `seen` | boolean | boolean |
| `flagged` | boolean | boolean |
| `isDeleted` | boolean | boolean |
| `verifications` | array of string | array of string |
| `retention` | boolean | boolean |
| `retentionDate` | date-time | string, format `date-time` |
| `text` | string | string |
| `html` | array of string | array of string |
| `hasAttachments` | boolean | boolean |
| `attachments` | array of objects, fields below | array; example objects with the same fields |
| `size` | number | integer |
| `downloadUrl` | string | string |
| `createdAt`, `updatedAt` | date-time | string, format `date-time` |
| `sourceUrl` | absent | string or null |

**DOCUMENTED.** `cc` / `bcc` item shape disagrees (string vs object). **UNKNOWN** which one is returned.

Attachment object, from the human example and the OpenAPI example (the schema does not define these keys, because `items.type` is wrong):

| Field | Example type |
| --- | --- |
| `id` | string (`"ATTACH000001"` in the OpenAPI example) |
| `filename` | string |
| `contentType` | string (`image/png` in the OpenAPI example) |
| `disposition` | string |
| `transferEncoding` | string (`base64` in the OpenAPI example) |
| `related` | boolean |
| `size` | number / integer (`666` in the OpenAPI example) |
| `downloadUrl` | string (`/messages/id/attachment/ATTACH000001` in the OpenAPI example) |

**DOCUMENTED** (https://docs.mail.tm/api/messages and `docs.jsonopenapi` example). Whether any of them can be null is **UNKNOWN**.

`html` is an array of strings in both sources, not one HTML string. **DOCUMENTED.**

### Related message operations (not the two payloads above)

**DOCUMENTED** (`docs.jsonopenapi` and https://docs.mail.tm/api/messages):

- `DELETE /messages/{id}` → 204, empty body in the human docs
- `PATCH /messages/{id}` — human docs: no body, response `{"seen": true}`, used to mark read. OpenAPI: required `application/merge-patch+json` body, write schema's only writable field is `seen` (boolean). The two descriptions disagree. Not called. **UNKNOWN** which one the server requires.
- `GET /messages/{id}/download` → 200 "Download the message", no body schema; 404 "Message not found"
- `GET /messages/{id}/attachment/{attachmentId}`
- `GET /sources/{id}` → `downloadUrl` and `data` strings, plus JSON-LD `@context`, `@id`, `@type`, `id`. Human docs: `data` is the raw source, so `downloadUrl` is optional in practice. OpenAPI `Source.jsonld-source.read` lists only those fields. The Hydra class also lists `mime_tree`, `mimeTree`, and `isDeleted`.

The Message JSON-LD context also names `magic`, `textFooter`, `mime_tree`, `meta`, `msgId`, `mimeTree`, and `mercureOptions`. **OBSERVED** (`GET https://api.mail.tm/contexts/Message`). They are not in the read schemas or the human examples. Whether they appear on a message is **UNKNOWN**.

---

## 4. Error response shapes

There is no single error JSON. Status code decides the shape. OpenAPI leaves 400, 404, and 422 bodies empty (`content` absent). **DOCUMENTED** (`docs.jsonopenapi`). The Hydra `Error` class lists many optional properties (`title`, `detail`, `status`, `type`, `message`, `code`, `hydra:title`, `hydra:description`, and others). `ConstraintViolationList` adds `violations`, `errorTitle`, `detail`, `hydra:title`, `hydra:description`. **DOCUMENTED** (`docs.jsonld`). Those lists are a superset, not the body you get.

Human status codes, with no body samples: **DOCUMENTED** (https://docs.mail.tm/getting-started/error-handling).

| Code | Docs gloss | Observed body |
| --- | --- | --- |
| 400 | Payload missing or empty | **OBSERVED** `POST /token` with `{}`. `Content-Type: application/json`. `{"type":"https://tools.ietf.org/html/rfc2616#section-10","title":"An error occurred","status":400,"detail":"Bad Request"}`. No `hydra:*`, no `message`, no `violations`. No `ratelimit-policy` in the captured headers. |
| 401 | Token missing or wrong. Bearer required except `POST /accounts` and `POST /token`. | **OBSERVED**, always `Content-Type: application/json`, `WWW-Authenticate: Bearer`, keys `code` (number) and `message` (string). No Hydra keys. |
| 404 | Unknown account or message | **OBSERVED** `GET /messages/000000000000000000000000`. `Content-Type: application/problem+json`. Body below. |
| 405 | Wrong method | **OBSERVED** `GET /token`. `Content-Type: application/ld+json`. Body below. |
| 418 | "I'm a teapot" | Not requested. **UNKNOWN.** |
| 422 | Address local-part too short, or domain not valid. No field list and no minimum length. | **OBSERVED** `Content-Type: application/problem+json`. `ConstraintViolationList` body below. |
| 429 | 8 per second; wait one second. No body described. | **OBSERVED** once, on a second `POST /accounts` inside the same minute: status 429, empty body, no `Content-Type`, no `Retry-After`. See section 1. The 8 QPS body is **UNKNOWN**. |

### 401 messages

**OBSERVED:**

- `GET /me` and `GET /messages` with no `Authorization`: `{"code":401,"message":"JWT Token not found"}`
- `GET /messages` with `Authorization: Bearer not-a-jwt`: `{"code":401,"message":"Invalid JWT Token"}`
- `POST /token` with a wrong password: `{"code":401,"message":"Invalid credentials."}`

### 404 body

**OBSERVED** `GET https://api.mail.tm/messages/000000000000000000000000`:

```json
{
  "@id": "/errors/404",
  "@type": "hydra:Error",
  "title": "An error occurred",
  "detail": "Not Found",
  "status": 404,
  "type": "/errors/404",
  "hydra:title": "An error occurred",
  "hydra:description": "Not Found"
}
```

Same shape for `GET https://api.mail.tm/contexts/Token` and for `GET https://api.mail.tm/docs.json` (detail text differs). **OBSERVED.**

Keys present together: RFC 7807-style `type`, `title`, `status`, `detail`, and Hydra `@id`, `@type`, `hydra:title`, `hydra:description`. No `message`, no `violations`.

### 405 body

**OBSERVED** `GET https://api.mail.tm/token`:

```json
{
  "@context": "/contexts/Error",
  "@type": "hydra:Error",
  "hydra:title": "An error occurred",
  "hydra:description": "No route found for \"GET http://api.mail.tm/token\": Method Not Allowed (Allow: POST)"
}
```

No `status`, `title`, `detail`, `message`, or `violations` in that body.

### 422 body

**OBSERVED** `POST https://api.mail.tm/accounts` with `{}`:

```json
{
  "@id": "/validation_errors/c1051bb4-d103-4f74-8988-acbcafc7fdc3",
  "@type": "ConstraintViolationList",
  "status": 422,
  "violations": [
    {
      "propertyPath": "address",
      "message": "This value should not be blank.",
      "code": "c1051bb4-d103-4f74-8988-acbcafc7fdc3"
    }
  ],
  "detail": "address: This value should not be blank.",
  "hydra:title": "An error occurred",
  "hydra:description": "address: This value should not be blank.",
  "type": "/validation_errors/c1051bb4-d103-4f74-8988-acbcafc7fdc3",
  "title": "An error occurred"
}
```

**OBSERVED** `POST /accounts` with address `a@maxxspace.com` (password `secret`): one violation, `propertyPath` `address`, `message` `This value is already used.`, `code` a UUID string.

**OBSERVED** `POST /accounts` with address `abcdefg@example.com`: one violation, `propertyPath` `address`, `message` `The domain "example.com" is not valid.`, `code` **null**.

`violations[].code` is sometimes a string and sometimes null. `detail` and `hydra:description` repeat `propertyPath` plus `message`. The empty-body 422 reported address only, not password (see account constraints).

---

## 5. Token lifetime and refresh

### How to get a token

**DOCUMENTED** (https://docs.mail.tm/getting-started/authentication): `POST /token` with JSON `address` and `password`. Example response:

```json
{"id": "string", "token": "string"}
```

Send `Authorization: Bearer TOKEN`. Create the account first. The page does not mention expiry, `exp`, or a refresh call.

**DOCUMENTED** (OpenAPI `POST /token`, operation `login_check_post`): request `address` and `password`, both string, `nullable: false`, both required. Response 200 `application/json` schema is only `token` (string, read-only, `nullable: false`, required). No `id`. No other success or error response is declared. No refresh path exists anywhere in the path list (`/accounts`, `/accounts/{id}`, `/domains`, `/domains/{id}`, `/me`, `/messages`, `/messages/{id}`, `/messages/{id}/attachment/{attachmentId}`, `/messages/{id}/download`, `/sources/{id}`, `/token`).

### What the token response and JWT contained

**OBSERVED** `POST https://api.mail.tm/token` → 200 `Content-Type: application/json`, keys `token`, `id`, and `@id`. `id` and `@id` were the account id (`@id` was `/accounts/{id}`). A second `POST /token` for the same account returned a different `token`.

JWT header **OBSERVED** by decoding (not by a docs claim): `{"typ":"JWT","alg":"HS512"}`.

Payload claims **OBSERVED**: `iat` (number), `roles` (`["ROLE_USER"]`), `address` (the mailbox), `id` (account id), `mercure.subscribe` (array with `/accounts/{id}`). There was no `exp`, no `nbf`, and no `sub`.

Both tokens were accepted: `GET /me` with the first token and `GET /me` with the second token each returned 200. Re-login did not immediately revoke the previous token. **OBSERVED.**

### Expiry and refresh

No lifetime is documented. **DOCUMENTED** as an omission (authentication page and OpenAPI).

The issued JWT did not contain an expiry claim, so a client cannot read a TTL out of it. **OBSERVED.**

Whether the server later rejects that JWT is **UNKNOWN**. It was not held until failure.

There is no refresh endpoint and no refresh grant. **DOCUMENTED** (OpenAPI path list; authentication page is silent). Getting another token means calling `POST /token` again with address and password. **OBSERVED** that this returns a new JWT while the previous one still works, at least immediately.

---

## Other facts the client design touches

### Domains

**DOCUMENTED** (https://docs.mail.tm/api/domains and OpenAPI `Domain.jsonld`): `GET /domains` and `GET /domains/{id}`. Member fields: `@id`, `@type`, `@context`, `id`, `domain`, `isActive`, `isPrivate`, `createdAt`, `updatedAt`. Pagination as in section 2, up to 30 per page in the human docs. Build an address as `user@` plus `domain`. `GET /domains/{id}` is described as useful for deleted or private domains.

**OBSERVED** `GET https://api.mail.tm/domains` (no token) → 200, `hydra:totalItems` 1, member:

- `id`: `6aa6b995482bea6f4a97f585`
- `domain`: `maxxspace.com`
- `isActive`: true
- `isPrivate`: false
- `createdAt` / `updatedAt`: `2026-09-13T00:00:00+00:00`

**OBSERVED** `GET https://api.mail.tm/domains/6aa6b995482bea6f4a97f585` with no token → 200 and the same fields.

The authentication page says bearer auth is required except for account creation and `/domains`. The error-handling page's exception list names only `POST /accounts` and `POST /token`. **DOCUMENTED**, and the two pages disagree about `GET /domains`. Live `GET /domains` and `GET /domains/{id}` succeeded with no token. **OBSERVED.**

### Account creation

**DOCUMENTED** (https://docs.mail.tm/api/accounts): `POST /accounts` JSON `address` and `password`. Response example: `@context`, `@id`, `@type`, `id`, `address`, `quota` (example `0`), `used` (example `0`), `isDisabled`, `isDeleted`, `createdAt`, `updatedAt`. No password in the response.

**DOCUMENTED** (OpenAPI `Account.jsonld-account.write`): `address` string, format `email`, required. `password` string, not required. Read schema matches the human fields; `address` is the only required read property. `quota` and `used` are integers. Flags are booleans. Timestamps are `date-time`.

**OBSERVED** `POST /accounts` with an 11-character local-part at `maxxspace.com` and a **1-character password** → **201**, `Content-Type: application/ld+json`, `Content-Location: /accounts/{id}`, `ratelimit-policy: 1; w=60`. Body keys: `@context`, `@id`, `@type`, `id`, `address`, `quota` **40000000**, `used` **0**, `isDisabled` **false**, `isDeleted` **false**, `createdAt`, `updatedAt` (`2026-10-21T12:49:48+00:00`). Password was not returned. The example `quota: 0` in the docs is a placeholder, not the live quota.

**OBSERVED** constraints from 422 bodies (section 4):

- missing address → `address` must not be blank
- domain not in the domain list → `The domain "…" is not valid.`
- address already registered → `This value is already used.`
- local-part length 1 (`a@maxxspace.com`) was rejected as already used, not as too short

A numeric minimum length for the local-part is **UNKNOWN**. The error-handling page says a too-short "username" can 422, but it never states the number, and this probe did not hit that message.

A 1-character password was accepted. **OBSERVED.** No password minimum is documented. OpenAPI does not require `password`. The empty-object 422 did not mention password. `POST /accounts` with a valid address and no password was not completed (that call returned the 429 in section 1). Whether password can be omitted is **UNKNOWN**.

Account JSON-LD context also names `roles`, `isError`, `ip`, `messages`, `userIdentifier`, `ipAddress`, `mercureOptions`. **OBSERVED** (`GET /contexts/Account`). None of those keys were in the 201 or `GET /me` bodies. **OBSERVED.**

### `/me` and other account routes

**DOCUMENTED** (https://docs.mail.tm/api/accounts and OpenAPI): `GET /me` returns the account for the bearer token. Same example fields as account read. `GET /accounts/{id}` requires the token of that account. `DELETE /accounts/{id}` → 204.

**OBSERVED** `GET https://api.mail.tm/me` → 200, same field set as create, `quota` 40000000, `used` 0. `@id` was `/me`. `Content-Location` was `/accounts/{id}`.

**OBSERVED** `DELETE https://api.mail.tm/accounts/{id}` → 204, empty body, no `Content-Type`. The throwaway account was removed.

OpenAPI does not define `GET /accounts` (no account collection). The entrypoint `GET /` returned `{"@context":"/contexts/Entrypoint","@id":"/","@type":"Entrypoint","domain":"/domains","message":"/messages"}`. **OBSERVED.**

### Real-time alternative to polling

**DOCUMENTED** (https://docs.mail.tm/api/webhooks): Mercure SSE, not webhooks. Hub `https://mercure.mail.tm/.well-known/mercure`, topic `/accounts/{id}`, `Authorization: Bearer` required. The event is an Account resource whose `used` changed, not the message.

The JWT's `mercure.subscribe` claim was that same topic. **OBSERVED.** A synchronous client that only polls still has to `GET /messages` (and `GET /messages/{id}` for the body) after it learns that `used` changed.

### Message query parameters

Only `page` is documented for `GET /messages`. **DOCUMENTED** (section 2). Filters such as `seen` are **UNKNOWN**.

---

## Implications for the client design

The current client is `mailtm_client_wrapper/client.py` (`MailTMClient`). It uses `https://api.mail.tm`, reads `hydra:member`, posts `{address, password}`, and sends `Authorization: Bearer`. Those parts match the docs and the live calls. The gaps below are the ones a synchronous design has to absorb.

1. **Budget for two different limits, and do not wait for `Retry-After`.** Docs say 8 requests per second and "wait one second" on 429. Live responses advertise `30; w=60` on ordinary routes and `1; w=60` on `POST /accounts`. The observed account-creation 429 had an empty body and no `Retry-After`. A retry helper that only sleeps `Retry-After` will not see a value. Account creation should be serialized to at most one `POST /accounts` per minute per IP. `POST /token` did not show that header and did not 429 in a handful of back-to-back calls; do not assume it shares the account limit.

2. **One `GET /messages` is the first page, not the mailbox.** The human docs cap a page at 30. `hydra:totalItems` is the total. `hydra:view` / `hydra:next` were absent on the live domain list and the empty inbox, so they are optional. `?page=2` past the end is 200 with `hydra:member: []` and the original total. Stop when the number of items gathered reaches `hydra:totalItems`, or when a page returns no members. `read_inbox()` does neither. Anything past the first page is dropped, and a full page of 30 looks complete.

3. **List and detail are different types.** The list item has `intro` and, in both written sources, does not carry `text`, `html`, or `attachments`. The detail has `text` (string) and `html` (array of strings). The client already fetches by id for the body; callers must not expect `intro` or `text` on both payloads. `cc` / `bcc` (string vs `{address,name}`) and whether detail includes `intro` are unresolved, so model them loosely until a real message is captured.

4. **Branch errors by status code.** 401 is `{"code","message"}`. 422 is `violations[]` with `propertyPath`, `message`, and a `code` that may be null, plus `detail` / `hydra:description`. 404 mixes `detail` and `hydra:description`. 400 on `/token` is `title` / `detail` / `status` / `type`. 429 may be an empty body. `raise_for_status()` plus `r.text` still surfaces the text, but one JSON parser will not fit all of them.

5. **Keep the password if the session must be renewed. There is nothing to refresh.** `POST /token` returns `token`, `id`, and `@id`. The JWT has `iat` and no `exp`. A second login returns a new token and leaves the old one valid, at least at once. No refresh route exists. The client stores `token` and ignores `id`, which is enough for bearer calls. It cannot schedule renewal from the token, and it will not notice a server-side expiry until a later call returns 401 `Invalid JWT Token`.

6. **Choose a domain with `isActive` and not `isPrivate`.** `get_domain()` uses `hydra:member[0].domain` and ignores the flags. Today that element is `maxxspace.com`, active and public. The docs include inactive and private domains on this collection.

7. **`/me` is the account snapshot for the token** (`quota`, `used`, flags). The client never calls it. Mercure pushes that account object when mail arrives; it does not push the message. Polling `GET /messages` remains the synchronous way to see mail.

8. **Password and local-part generators are inside what was accepted.** The helper uses a 10-character local-part and a 12-character password. A 1-character password was accepted, and a 1-character local-part was not rejected for length. No change is required for those lengths. The create rate limit matters more: two creates in the same minute can 429 with an empty body, and `create_account()` treats that as a generic failure.

## Unknowns

- Whether the documented 8 per second limit is still enforced, and the status, headers, and body of that 429. `Retry-After` was absent on the one 429 that was seen (account creation) and is undocumented. It is unverified whether any 429 sends it.
- Whether the 31st ordinary request in a 60-second window is rejected. The `30; w=60` header was advertised, not saturated.
- Whether `POST /token` is rate limited.
- The numeric minimum and maximum length of the address local-part. Docs say "too short" can 422. A one-character local-part came back "already used" instead.
- Whether `password` may be omitted when `address` is valid. OpenAPI does not require it. A one-character password was accepted. The omitted-password request hit 429 before validation.
- The real page size. "Up to 30" is only in the human docs. Whether `itemsPerPage` changes it is unverified (`?itemsPerPage=1` only echoed a partial view around a one-item collection).
- Which `hydra:search` variables exist. The member was absent on the collections that were fetched.
- A real list item and a real detail: field presence, nulls, `from` / `to` / `cc` / `bcc` shapes, whether detail includes `intro` and `sourceUrl`, and whether `accountId` is a raw id or an IRI.
- Whether `PATCH /messages/{id}` requires `{"seen": true}` or accepts an empty body.
- Server-side JWT lifetime, and whether an older token is revoked when `POST /token` is called again. Immediate overlap was observed. No `exp` claim.
- Extra JSON-LD context names (`magic`, `textFooter`, `ip`, and the others listed above) are not confirmed response fields.
- `418`, and the `Allow` header on 405 (the 405 body mentions `Allow: POST`; the response headers were not fully recorded).
- The two `Link` header values on `GET /messages` (the names were seen; the values were not saved).
